"""Easy Generate - Cloud ueber HuggingFace.

Drei Wege:
  1. Gratis:        ZeroGPU-Spaces (Tageskontingent des eigenen HF-Kontos)
  2. Pro Video:     Inference Providers (Abrechnung ueber das HF-Guthaben)
  3. GPU mieten:    einen Space ins eigene Konto kopieren und mit bezahlter GPU starten

Der HF-Token liegt nur lokal in data/config.json und wird ausschliesslich an
HuggingFace-Adressen geschickt (huggingface.co, router.huggingface.co, *.hf.space).
"""
import asyncio
import json
import os
import re
import sys
import time
import uuid
from urllib.parse import quote, urlparse

import aiohttp
from aiohttp import web

from . import DATA, HERE, load_cfg, read_json, routes, write_json

try:
    import folder_paths
except Exception:  # nur fuer Tests ausserhalb von ComfyUI
    folder_paths = None

HF = "https://huggingface.co"
PYLIB = os.path.join(DATA, "pylib")
WORKER = os.path.join(HERE, "cloud_worker.py")
CLOUD_FILE = os.path.join(DATA, "cloud.json")
TMP = os.path.join(DATA, "cloud_tmp")
SUB = "easy-cloud"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
PKGS = ["gradio_client>=2.7,<3", "huggingface_hub>=2.2,<3"]


def out_dir():
    base = folder_paths.get_output_directory() if folder_paths else os.path.join(DATA, "output")
    return os.path.join(base, SUB)


def input_path(name):
    if not name:
        return None
    if folder_paths:
        try:
            p = folder_paths.get_annotated_filepath(name)
            if os.path.isfile(p):
                return p
        except Exception:
            pass
        p = os.path.join(folder_paths.get_input_directory(), name)
        if os.path.isfile(p):
            return p
    return None


def is_hf_url(url):
    h = (urlparse(url).hostname or "").lower()
    return h == "huggingface.co" or h.endswith(".huggingface.co") or h.endswith(".hf.space")


def token():
    """Haupt-Schluessel: nur fuer huggingface.co und router.huggingface.co (Konto, Abrechnung, Pay-per-Video, Mieten)."""
    return (load_cfg().get("hf_token") or "").strip()


def space_token():
    """Space-Schluessel: wird an Spaces (*.hf.space) geschickt. Deren Programmcode stammt von Dritten,
    deshalb nie der Haupt-Schluessel, sondern ein eigener Schluessel ohne Rechte (nur fuers Gratis-Kontingent)
    bzw. mit reinem Leserecht (fuer die eigenen, privaten Miet-Spaces)."""
    return (load_cfg().get("hf_space_token") or "").strip()


def cstate():
    return read_json(CLOUD_FILE, {"rented": [], "pause_on_exit": True, "costs": {}})


def save_cstate(s):
    write_json(CLOUD_FILE, s)


class HFError(Exception):
    def __init__(self, status, text):
        super().__init__(f"HTTP {status}: {text[:300]}")
        self.status = status
        self.text = text


async def hf(method, path, auth=True, body=None, params=None, timeout=30):
    """Anfrage an huggingface.co. Der Token geht nur hierhin."""
    url = path if path.startswith("http") else HF + path
    if not is_hf_url(url):
        raise ValueError("Nur HuggingFace-Adressen erlaubt")
    headers = {"User-Agent": "EasyGenerate"}
    t = token()
    if auth and t:
        headers["Authorization"] = "Bearer " + t
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
        async with s.request(method, url, headers=headers, json=body, params=params, allow_redirects=True) as r:
            text = await r.text()
            if r.status >= 400:
                raise HFError(r.status, text)
            try:
                return json.loads(text) if text else {}
            except Exception:
                return {"_text": text}


CACHE = {}


async def cached(key, ttl, fn):
    c = CACHE.get(key)
    if c and time.time() - c[0] < ttl:
        return c[1]
    v = await fn()
    CACHE[key] = (time.time(), v)
    return v


def json_body_required(request):
    # Kosten verursachende Aufrufe nur von unserer eigenen Seite (fetch mit JSON)
    return (request.content_type or "").startswith("application/json")


# ------------------------------------------------------------------ Preise (Schaetzwerte)
# USD pro Sekunde Video bzw. pro Bild. Die Anbieter rechnen unterschiedlich ab;
# Easy Generate lernt nach jeder Erstellung den echten Preis aus der HF-Abrechnung dazu.
PRICE_RULES = [
    (r"minimax-h3", ("s", 0.10)),
    (r"ltx-2\.3|ltx-2-19b|ltx-2/|ltx-2$|ltx2", ("s", 0.06)),
    (r"ltx-video|ltxv", ("s", 0.02)),
    (r"wan.*(5b|1\.3b)", ("s", 0.03)),
    (r"wan.*(a14b|14b|t2v-720|i2v-720|t2v$|i2v$)", ("s", 0.08)),
    (r"wan.*480", ("s", 0.05)),
    (r"wan", ("s", 0.08)),
    (r"hunyuan", ("s", 0.075)),
    (r"longcat", ("s", 0.06)),
    (r"cogvideo|mochi|skyreels", ("s", 0.08)),
    (r"flux.*(schnell|klein)|z-image|sdxl|lightning|turbo", ("img", 0.005)),
    (r"flux.*dev|qwen-image|hidream|sd3|stable-diffusion-3", ("img", 0.025)),
    (r"flux.*pro|seedream|imagen", ("img", 0.04)),
]


def price_for(provider_id, task):
    pid = (provider_id or "").lower()
    for rx, val in PRICE_RULES:
        if re.search(rx, pid):
            return {"unit": val[0], "usd": val[1]}
    return {"unit": "s", "usd": 0.08} if "video" in task else {"unit": "img", "usd": 0.03}


# ------------------------------------------------------------------ Konto & Guthaben
async def _account():
    t = token()
    out = {"token_set": bool(t)}
    if not t:
        return out
    try:
        me = await hf("GET", "/api/whoami-v2")
        tok = (me.get("auth") or {}).get("accessToken") or {}
        out["user"] = {"name": me.get("name"), "fullname": me.get("fullname"), "avatar": me.get("avatarUrl"),
                       "isPro": bool(me.get("isPro")), "canPay": bool(me.get("canPay")),
                       "orgs": [o.get("name") for o in me.get("orgs") or []]}
        role = tok.get("role")
        out["token_role"] = role
        if role == "fineGrained":
            perms = set()
            for sc in (tok.get("fineGrained") or {}).get("scoped") or []:
                for p in sc.get("permissions") or []:
                    perms.add(p)
            for p in (tok.get("fineGrained") or {}).get("global") or []:
                perms.add(p)
            out["token_perms"] = sorted(perms)
    except HFError as e:
        out["error"] = "AUTH" if e.status in (401, 403) else str(e)
        return out
    except Exception as e:
        out["error"] = "OFFLINE|" + str(e)
        return out
    try:
        b = await hf("GET", "/api/settings/billing/usage")
        cats, total = {}, 0
        for cat, items in (b.get("usage") or {}).items():
            if isinstance(items, list):
                s = sum(float(i.get("totalCostMicroUSD") or 0) for i in items if isinstance(i, dict))
                cats[cat] = s / 1e6
                total += s
        out["usage"] = {"period": b.get("period") or {}, "total": total / 1e6, "cats": cats}
    except HFError as e:
        out["usage_error"] = "PERM" if e.status in (401, 403) else str(e.status)
    except Exception as e:
        out["usage_error"] = str(e)
    st_tok = space_token()
    if st_tok:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
                async with s.get(HF + "/api/whoami-v2", headers={"Authorization": "Bearer " + st_tok}) as r:
                    sj = await r.json() if r.status == 200 else {}
            at = (sj.get("auth") or {}).get("accessToken") or {}
            uname = out.get("user", {}).get("name")
            read_own = at.get("role") in ("read", "write")
            fg = at.get("fineGrained") or {}
            for sc in fg.get("scoped") or []:
                ent = sc.get("entity") or {}
                if ent.get("name") == uname and "repo.content.read" in (sc.get("permissions") or []):
                    read_own = True
            out["space_token"] = {"ok": bool(sj), "role": at.get("role"), "same_user": sj.get("name") == uname, "read_own": read_own}
        except Exception:
            out["space_token"] = {"ok": None}
    out["included"] = 2.0 if out.get("user", {}).get("isPro") else 0.0
    out["zerogpu_min"] = 40 if out.get("user", {}).get("isPro") else 5
    st = cstate()
    out["costs"] = st.get("costs", {})
    out["zgpu_left"] = st.get("zgpu_left")
    return out


@routes.get("/easy/cloud/account")
async def cloud_account(request):
    force = request.query.get("force") == "1"
    if force:
        CACHE.pop("account", None)
    return web.json_response(await cached("account", 60, _account))


# ------------------------------------------------------------------ Bibliotheken (gradio_client, huggingface_hub)
SETUP = {"running": False, "done": False, "error": None, "log": []}


async def run_worker(job, on_line=None, timeout=3600):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    env["GRADIO_ANALYTICS_ENABLED"] = "False"
    env["PYTHONIOENCODING"] = "utf-8"
    job = dict(job)
    job.setdefault("tmp", TMP)
    job.setdefault("outdir", out_dir())
    os.makedirs(TMP, exist_ok=True)
    _prune_tmp()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-s", WORKER, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env, cwd=DATA, creationflags=NO_WINDOW)
    proc.stdin.write((json.dumps(job) + "\n").encode())
    await proc.stdin.drain()
    proc.stdin.close()
    result = None
    t0 = time.time()
    try:
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=max(5, timeout - (time.time() - t0)))
            if not line:
                break
            try:
                m = json.loads(line.decode("utf-8", "replace"))
            except Exception:
                continue
            if m.get("type") in ("result", "error"):
                result = m
            elif on_line:
                on_line(m)
    except asyncio.TimeoutError:
        proc.kill()
        return {"type": "error", "error": "Zeitueberschreitung"}
    finally:
        if proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), 10)
            except Exception:
                proc.kill()
    if result is None:
        err = (await proc.stderr.read()).decode("utf-8", "replace")[-800:]
        t = token()
        if t:
            err = err.replace(t, "hf_***")
        result = {"type": "error", "error": "Cloud-Helfer abgebrochen: " + (err or "unbekannt")}
    return result


def _prune_tmp():
    """Zwischendateien von Spaces (Downloads) nach 6 Stunden loeschen."""
    cut = time.time() - 6 * 3600
    for root, dirs, files in os.walk(TMP, topdown=False):
        for f in files:
            p = os.path.join(root, f)
            try:
                if os.path.getmtime(p) < cut:
                    os.remove(p)
            except OSError:
                pass
        if root != TMP:
            try:
                os.rmdir(root)
            except OSError:
                pass


def libs_ready():
    return os.path.isdir(os.path.join(PYLIB, "gradio_client")) and os.path.isdir(os.path.join(PYLIB, "huggingface_hub"))


async def _setup():
    SETUP.update(running=True, done=False, error=None, log=[])
    try:
        os.makedirs(PYLIB, exist_ok=True)
        cmd = [sys.executable, "-s", "-m", "pip", "install", "--upgrade", "--target", PYLIB,
               "--no-warn-script-location", "--disable-pip-version-check", "--no-input"] + PKGS
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                    creationflags=NO_WINDOW)
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            s = line.decode("utf-8", "replace").strip()
            if s:
                SETUP["log"] = (SETUP["log"] + [s])[-30:]
        await proc.wait()
        if proc.returncode != 0:
            raise RuntimeError("pip: " + " / ".join(SETUP["log"][-4:]))
        chk = await run_worker({"op": "check"}, timeout=120)
        if chk.get("type") != "result":
            raise RuntimeError(chk.get("error", "Pruefung fehlgeschlagen"))
        SETUP["done"] = True
    except Exception as e:
        SETUP["error"] = str(e)
    finally:
        SETUP["running"] = False


@routes.get("/easy/cloud/setup")
async def cloud_setup_status(request):
    return web.json_response({"ready": libs_ready(), **SETUP})


@routes.post("/easy/cloud/setup")
async def cloud_setup(request):
    if not SETUP["running"]:
        asyncio.ensure_future(_setup())
    return web.json_response({"ok": True})


# ------------------------------------------------------------------ Modelle bei Anbietern (Pay-per-Video)
TASKS = {"t2v": "text-to-video", "i2v": "image-to-video", "t2i": "text-to-image", "i2i": "image-to-image"}
PINNED = [
    "Wan-AI/Wan2.2-T2V-A14B", "Wan-AI/Wan2.2-I2V-A14B", "Lightricks/LTX-2", "tencent/HunyuanVideo-1.5",
    "Wan-AI/Wan2.2-TI2V-5B", "larryvrh/MiniMax-H3-Turbo-Lora", "meituan-longcat/LongCat-Video",
    "Wan-AI/Wan2.1-T2V-14B", "Wan-AI/Wan2.1-I2V-14B-720P", "tencent/HunyuanVideo", "zai-org/CogVideoX-5b",
    "genmo/mochi-1-preview", "Lightricks/LTX-Video-0.9.5", "tencent/HunyuanVideo-I2V",
    "black-forest-labs/FLUX.1-dev", "black-forest-labs/FLUX.1-schnell", "Qwen/Qwen-Image", "Tongyi-MAI/Z-Image-Turbo",
    "black-forest-labs/FLUX.1-Kontext-dev", "Qwen/Qwen-Image-Edit",
]
EU_LICENSE = re.compile(r"minimax-h3", re.I)


async def _models(task):
    params = [("pipeline_tag", task), ("inference_provider", "all"), ("sort", "likes"), ("limit", "500"),
              ("expand[]", "inferenceProviderMapping"), ("expand[]", "likes"), ("expand[]", "tags"), ("expand[]", "downloads")]
    q = "&".join(f"{k}={quote(v)}" for k, v in params)
    items = await hf("GET", "/api/models?" + q, auth=False, timeout=40)
    out = []
    for m in items if isinstance(items, list) else []:
        mp = m.get("inferenceProviderMapping") or []
        if isinstance(mp, dict):
            mp = [dict(v, provider=k) for k, v in mp.items()]
        provs = [{"provider": p.get("provider"), "id": p.get("providerId"), "status": p.get("status")}
                 for p in mp if p.get("task") in (task, None) and p.get("status") in ("live", None)]
        if not provs:
            continue
        tags = m.get("tags") or []
        mid = m.get("id") or m.get("modelId")
        lora = any(str(t).startswith("base_model:adapter:") for t in tags) or "lora" in tags or \
            all("lora" in (p["id"] or "").lower() for p in provs)
        pinned = mid in PINNED
        price = price_for(provs[0]["id"] or mid, task)
        out.append({"id": mid, "providers": provs, "likes": m.get("likes", 0), "lora": lora and not pinned,
                    "pinned": pinned, "price": price,
                    "license_eu": bool(EU_LICENSE.search(mid + " " + " ".join(p["id"] or "" for p in provs)))})
    out.sort(key=lambda x: (0 if x["pinned"] else 1, PINNED.index(x["id"]) if x["pinned"] else 0, -x["likes"]))
    return out


@routes.get("/easy/cloud/models")
async def cloud_models(request):
    task = TASKS.get(request.query.get("task", "t2v"), "text-to-video")
    try:
        items = await cached("models:" + task, 3600, lambda: _models(task))
        costs = cstate().get("costs", {})
        for it in items:
            c = costs.get(it["id"])
            it["learned"] = c
        return web.json_response({"items": items, "task": task})
    except Exception as e:
        return web.json_response({"items": [], "error": str(e)})


# ------------------------------------------------------------------ Spaces (Gratis / gemietet)
RECOMMENDED = {
    "video": ["Lightricks/LTX-2-3", "Lightricks/ltx-video-distilled", "Lightricks/LTX-2.5", "alexnasa/ltx-2-TURBO",
              "zerogpu-aoti/wan2-2-fp8da-aoti-faster", "multimodalart/wan2-1-fast", "multimodalart/wan-2-2-first-last-frame",
              "Upsampler/wan-2-2-14b-image-to-video", "MiniMaxAI/MiniMax-H3-Turbo-Lora", "multimodalart/minimax-h3",
              "mrfakename/minimax-h3-ultra-fast", "Pepe104/MiniMax-H3-Turbo-Lora-UNCENSORED"],
    "image": ["Qwen/Qwen-Image-2.1", "black-forest-labs/flux-3-image-klein", "Tongyi-MAI/Z-Image-Turbo",
              "hugging-apps/qwen-image-2-1-lightning", "prithivMLmods/Qwen-Image-Edit-2511-LoRAs-Fast", "OpenMOSS-Team/MOSS-Image"],
}
SEARCH = {
    "video": ["video", "wan", "ltx", "minimax-h3", "hunyuan", "i2v", "animate"],
    "image": ["image", "flux", "qwen-image", "z-image", "sdxl", "image-edit"],
}


def space_item(s, kind):
    rt = s.get("runtime") or {}
    hw = (rt.get("hardware") or {}).get("current")
    card = s.get("cardData") or {}
    sid = s.get("id")
    return {"id": sid, "title": card.get("title") or sid.split("/")[-1], "emoji": card.get("emoji") or "",
            "desc": card.get("short_description") or "", "likes": s.get("likes", 0), "stage": rt.get("stage"),
            "hardware": hw, "zero": hw == "zero-a10g", "kind": kind,
            "license_eu": bool(EU_LICENSE.search(sid or "")),
            "recommended": sid in RECOMMENDED.get(kind, [])}


async def _search_spaces(term, kind):
    params = [("search", term), ("sort", "likes"), ("limit", "60"), ("expand[]", "runtime"), ("expand[]", "likes"),
              ("expand[]", "cardData"), ("expand[]", "sdk")]
    q = "&".join(f"{k}={quote(v)}" for k, v in params)
    items = await hf("GET", "/api/spaces?" + q, auth=False, timeout=30)
    return [space_item(s, kind) for s in items if isinstance(s, dict) and s.get("sdk") in (None, "gradio")]


async def _spaces(kind):
    res = {}
    terms = SEARCH[kind]
    found = await asyncio.gather(*(_search_spaces(t, kind) for t in terms), return_exceptions=True)
    for lst in found:
        if isinstance(lst, list):
            for it in lst:
                res.setdefault(it["id"], it)
    missing = [sid for sid in RECOMMENDED[kind] if sid not in res]

    async def one(sid):
        try:
            s = await hf("GET", f"/api/spaces/{sid}?expand[]=runtime&expand[]=likes&expand[]=cardData", auth=False)
            s["id"] = sid
            res[sid] = space_item(s, kind)
        except Exception:
            pass
    await asyncio.gather(*(one(s) for s in missing))
    items = [x for x in res.values() if x["zero"] and x["stage"] in ("RUNNING", "RUNNING_BUILDING", "RUNNING_APP_STARTING")]
    items.sort(key=lambda x: (0 if x["recommended"] else 1, RECOMMENDED[kind].index(x["id"]) if x["recommended"] else 0, -x["likes"]))
    return items


@routes.get("/easy/cloud/spaces")
async def cloud_spaces(request):
    kind = "image" if request.query.get("kind") == "image" else "video"
    q = request.query.get("q", "").strip()
    try:
        if q:
            items = [x for x in await _search_spaces(q, kind) if x["zero"] or x["stage"] == "RUNNING"]
            items.sort(key=lambda x: (0 if x["zero"] else 1, -x["likes"]))
        else:
            items = await cached("spaces:" + kind, 1800, lambda: _spaces(kind))
        return web.json_response({"items": items})
    except Exception as e:
        return web.json_response({"items": [], "error": str(e)})


def parse_space(s):
    """Space-ID aus Eingabe (ID, huggingface.co/spaces/..., *.hf.space)."""
    s = (s or "").strip().rstrip("/")
    m = re.match(r"^(?:https?://)?(?:www\.)?huggingface\.co/spaces/([\w.\-]+/[\w.\-]+)", s)
    if m:
        return m.group(1)
    if re.match(r"^[\w.\-]+/[\w.\-]+$", s):
        return s
    if re.match(r"^https?://[\w.\-]+\.hf\.space", s):
        return s.split("?")[0]
    if re.match(r"^http://(127\.0\.0\.1|localhost)(:\d+)?", s):   # eigener lokaler Gradio-Server
        return s
    return None


# ---- Auswahlwerte aus dem Programmcode des Space lesen (z. B. alle Aufloesungen fuer „Canvas“).
# Der Code wird nur gelesen (ast.parse), niemals ausgefuehrt.
import ast as _ast


def _str_list(v, names):
    if isinstance(v, (_ast.List, _ast.Tuple, _ast.Set)):
        vals = [e.value for e in v.elts if isinstance(e, _ast.Constant) and isinstance(e.value, str)]
        return vals if len(vals) >= 2 and len(vals) == len(v.elts) else None
    if isinstance(v, _ast.Dict):
        vals = [k.value for k in v.keys if isinstance(k, _ast.Constant) and isinstance(k.value, str)]
        return vals if len(vals) >= 2 and len(vals) == len(v.keys) else None
    if isinstance(v, _ast.Name):
        return names.get(v.id)
    if isinstance(v, _ast.Call):            # list(X), list(X.keys()), sorted(X)
        if v.args:
            return _str_list(v.args[0], names)
        if isinstance(v.func, _ast.Attribute) and v.func.attr == "keys":
            return _str_list(v.func.value, names)
    if isinstance(v, _ast.Attribute) and v.attr == "keys":
        return _str_list(v.value, names)
    return None


def _scan_source(src):
    tree = _ast.parse(src)
    names, widgets = {}, []
    for _ in range(2):   # zweimal, damit Verweise auf spaeter definierte Listen aufgeloest werden
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.Assign, _ast.AnnAssign)):
                targets = node.targets if isinstance(node, _ast.Assign) else [node.target]
                vals = _str_list(node.value, names) if node.value is not None else None
                if vals:
                    for t in targets:
                        if isinstance(t, _ast.Name):
                            names[t.id] = vals
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            if "choices" in kw:
                ch = _str_list(kw["choices"], names)
                lab = kw.get("label")
                if ch:
                    widgets.append((lab.value if isinstance(lab, _ast.Constant) and isinstance(lab.value, str) else "", ch))
    return names, widgets


async def _space_sources(sid):
    """Python-Dateien eines Space (nur lesen). Zwischengespeichert fuer 1 Stunde."""
    key = "srcfiles:" + sid
    if key in CACHE and time.time() - CACHE[key][0] < 3600:
        return CACHE[key][1]
    tree = await hf("GET", f"/api/spaces/{sid}/tree/main")
    files = [t["path"] for t in (tree if isinstance(tree, list) else []) if t.get("type") == "file"
             and t["path"].endswith(".py") and (t.get("size") or 0) < 400000]
    files.sort(key=lambda p: (0 if p in ("app.py", "main.py") else 1, p.count("/"), p))
    out = []
    for path in files[:8]:
        try:
            res = await hf("GET", f"/spaces/{sid}/raw/main/{quote(path)}", timeout=30)
        except Exception:
            continue
        src = res.get("_text") if isinstance(res, dict) else None
        if src:
            out.append((path, src))
    CACHE[key] = (time.time(), out)
    return out


SPACE_ID_RX = re.compile(r"""["']([A-Za-z0-9][\w.\-]{1,95}/[A-Za-z0-9][\w.\-]{1,95})["']""")


def _dep_candidates(src):
    """Space-IDs, die der Code per gradio_client / Client(...) aufruft."""
    if "gradio_client" not in src and "Client(" not in src:
        return set()
    cands = set()
    for m in re.finditer(r"Client\(\s*([^,)\n]+)", src):
        arg = m.group(1).strip()
        mm = SPACE_ID_RX.fullmatch(arg)
        if mm:
            cands.add(mm.group(1))
        elif re.fullmatch(r"[A-Za-z_]\w*", arg):      # Variable -> deren Wert suchen
            for d in re.finditer(r"\b%s\s*=\s*(.+)" % re.escape(arg), src):
                for x in SPACE_ID_RX.findall(d.group(1)):
                    cands.add(x)
    return {c for c in cands if not c.lower().endswith((".py", ".json", ".safetensors"))}


async def _space_deps(sid):
    key = "deps:" + sid
    if key in CACHE and time.time() - CACHE[key][0] < 3600:
        return CACHE[key][1]
    cands = set()
    for path, src in await _space_sources(sid):
        cands |= _dep_candidates(src)
    deps = []
    for c in sorted(cands):
        if c == sid:
            continue
        try:
            sp = await hf("GET", f"/api/spaces/{c}?expand[]=runtime", auth=False)
            hw = ((sp.get("runtime") or {}).get("hardware") or {}).get("current")
            deps.append({"id": c, "zero": hw == "zero-a10g", "hardware": hw})
        except Exception:
            pass
    CACHE[key] = (time.time(), deps)
    return deps


@routes.get("/easy/cloud/space_deps")
async def cloud_space_deps(request):
    sid = parse_space(request.query.get("space", ""))
    if not sid or sid.startswith("http"):
        return web.json_response({"deps": []})
    try:
        return web.json_response({"deps": await _space_deps(sid)})
    except Exception as e:
        return web.json_response({"deps": [], "error": str(e)})


async def _choices_from_source(sid, endpoints):
    want = [(ep, f) for ep in endpoints for f in ep["fields"] if f["kind"] == "text" and f.get("role") not in ("prompt", "negative") and not f.get("choices")]
    if not want:
        return
    names, widgets = {}, []
    for path, src in await _space_sources(sid):
        try:
            n, w = await asyncio.to_thread(_scan_source, src)
            names.update(n)
            widgets += w
        except SyntaxError:
            pass
    for ep, f in want:
        nm = re.sub(r"[^a-z0-9]", "", (f.get("name") or "").lower())
        lab = (f.get("label") or "").lower()
        dflt = f.get("default")
        best = None
        for wl, ch in widgets:                                # 1. gleich beschriftete Auswahl im Code
            if lab and wl and wl.lower().strip() == lab.strip():
                best = ch
        if not best and nm and len(nm) >= 3:                  # 2. Liste, deren Name den Feldnamen enthaelt (CANVAS_PRESETS ...)
            cands = [ch for k, ch in names.items() if nm in re.sub(r"[^a-z0-9]", "", k.lower())]
            if dflt:
                cands = [c for c in cands if dflt in c] or cands
            if cands:
                best = max(cands, key=len)
        if not best and isinstance(dflt, str) and dflt:       # 3. Liste, die den Standardwert enthaelt
            cands = [ch for ch in names.values() if dflt in ch] + [ch for _, ch in widgets if dflt in ch]
            if cands:
                best = max(cands, key=len)
        if best and len(best) <= 60:
            f["kind"], f["choices"] = "choice", best
            if not f.get("default") or f["default"] not in best:
                f["default"] = best[0]


@routes.post("/easy/cloud/space_info")
async def cloud_space_info(request):
    data = await request.json()
    sid = parse_space(data.get("space"))
    if not sid:
        return web.json_response({"error": "Das ist keine gültige Space-Adresse."}, status=400)
    if not libs_ready():
        return web.json_response({"error": "SETUP"}, status=400)
    key = "info:" + sid
    if not data.get("force") and key in CACHE and time.time() - CACHE[key][0] < 1800:
        return web.json_response(CACHE[key][1])
    meta = {}
    if not sid.startswith("http"):
        try:
            s = await hf("GET", f"/api/spaces/{sid}?expand[]=runtime&expand[]=cardData&expand[]=likes&expand[]=private")
            s["id"] = sid
            meta = space_item(s, "video")
            meta["private"] = s.get("private")
        except HFError as e:
            return web.json_response({"error": "Space nicht gefunden (" + str(e.status) + ")."}, status=404)
        except Exception:
            pass
        if meta.get("stage") in ("PAUSED", "SLEEPING", "STOPPED") and not mine(sid):
            return web.json_response({"error": "SPACE_DOWN|" + str(meta.get("stage")), "meta": meta}, status=409)
    r = await run_worker({"op": "info", "space": sid, "token": space_token()}, timeout=180)
    if r.get("type") != "result":
        return web.json_response({"error": r.get("error"), "meta": meta}, status=502)
    if not sid.startswith("http"):
        try:
            await _choices_from_source(sid, r["endpoints"])
        except Exception as e:
            print("[Easy Generate] Space-Quelltext nicht auswertbar:", e)
    learned = cstate().get("choices", {})
    for ep in r["endpoints"]:
        for i, ch in (learned.get(sid + ep["api"]) or {}).items():
            for f in ep["fields"]:
                if str(f["i"]) == str(i) and ch:
                    f["kind"], f["choices"] = "choice", ch
                    if f.get("default") in (None, "") or str(f.get("default")) not in ch:
                        f["default"] = ch[0]
    out = {"space": sid, "meta": meta, "endpoints": r["endpoints"]}
    CACHE[key] = (time.time(), out)
    return web.json_response(out)


# ------------------------------------------------------------------ Aufträge
JOBS = {}


def _job_view(j):
    return {k: v for k, v in j.items() if k not in ("task",)}


async def _billing_total():
    try:
        b = await hf("GET", "/api/settings/billing/usage")
        return sum(float(i.get("totalCostMicroUSD") or 0) for items in (b.get("usage") or {}).values()
                   if isinstance(items, list) for i in items if isinstance(i, dict)) / 1e6
    except Exception:
        return None


async def _learn_cost(model, before, units):
    """Nach einer Erstellung den tatsaechlichen Preis aus der Abrechnung ablesen (kommt mit Verzoegerung)."""
    if before is None or not units:
        return
    for wait in (60, 180, 600):
        await asyncio.sleep(wait)
        after = await _billing_total()
        if after is not None and after > before + 1e-6:
            st = cstate()
            c = st.setdefault("costs", {}).get(model) or {"n": 0, "usd": 0.0}
            c["n"] += 1
            c["usd"] += after - before
            c["units"] = c.get("units", 0) + units
            c["per_unit"] = c["usd"] / max(1e-9, c["units"])
            st["costs"][model] = c
            save_cstate(st)
            CACHE.pop("account", None)
            return


async def _run_job(j, spec):
    def on(m):
        if m.get("type") == "status":
            j["status"] = m
            j["updated"] = time.time()
    before = await _billing_total() if spec.get("op") == "provider" else None
    r = await run_worker(spec, on_line=on, timeout=3600)
    j["finished"] = time.time()
    if r.get("type") == "result":
        from . import gallery
        files = []
        for f in r.get("files", []):
            src = os.path.join(out_dir(), f)
            try:
                t = await asyncio.to_thread(gallery.place, src, spec.get("title") or j["label"], spec.get("kind") or "",
                                            spec.get("prompt") or "", "cloud")
                ref = gallery.file_ref(t)
            except Exception:
                ref = None
            files.append(dict(ref, name=os.path.basename(t)) if ref else {"filename": f, "subfolder": SUB, "type": "output"})
        j["files"] = files
        if r.get("learned") and spec.get("op") == "space":
            st = cstate()
            ch = st.setdefault("choices", {}).setdefault(spec["space"] + spec["api"], {})
            ch.update(r["learned"])
            save_cstate(st)
            CACHE.pop("info:" + spec["space"], None)
            j["learned"] = r["learned"]
        j["state"] = "done"
        if spec.get("op") == "provider":
            asyncio.ensure_future(_learn_cost(spec["model"], before, j.get("units", 0)))
    else:
        err = str(r.get("error") or "Fehler")
        j["state"] = "error"
        j["error"] = err
        j["trace"] = r.get("trace")
        m = re.match(r"ZEROGPU_QUOTA\|(\d*)", err)
        if m:
            st = cstate()
            st["zgpu_left"] = {"seconds": int(m.group(1)) if m.group(1) else 0, "at": time.time()}
            save_cstate(st)
    if spec.get("space") and mine(spec.get("space")):
        st = cstate()
        for x in st.get("rented", []):
            if x["id"] == spec["space"]:
                x["last_used"] = time.time()
        save_cstate(st)


@routes.post("/easy/cloud/run")
async def cloud_run(request):
    if not json_body_required(request):
        return web.json_response({"error": "bad request"}, status=400)
    data = await request.json()
    if not libs_ready():
        return web.json_response({"error": "SETUP"}, status=400)
    mode = data.get("mode")
    if mode == "provider":
        if not token():
            return web.json_response({"error": "AUTH|Kein HuggingFace-Token gespeichert."}, status=400)
        task = TASKS.get(data.get("task"))
        if not task:
            return web.json_response({"error": "Unbekannte Aufgabe"}, status=400)
        spec = {"op": "provider", "task": task, "model": str(data.get("model")), "provider": str(data.get("provider") or "auto"),
                "prompt": str(data.get("prompt") or ""), "negative": str(data.get("negative") or ""),
                "seed": data.get("seed"), "extra": data.get("extra") if isinstance(data.get("extra"), dict) else {},
                "token": token()}
        if task in ("image-to-video", "image-to-image"):
            p = input_path(data.get("image"))
            if not p:
                return web.json_response({"error": "Bitte zuerst ein Startbild wählen."}, status=400)
            spec["image"] = p
        units = float(data.get("units") or (5 if "video" in task else 1))
        label = spec["model"]
    elif mode == "space":
        sid = parse_space(data.get("space"))
        if not sid:
            return web.json_response({"error": "Ungültige Space-Adresse"}, status=400)
        values = {}
        files = data.get("files") if isinstance(data.get("files"), dict) else {}
        for k, v in (data.get("values") or {}).items():
            values[str(k)] = v
        for k, name in files.items():
            p = input_path(name)
            if p:
                values[str(k)] = p
        spec = {"op": "space", "space": sid, "api": str(data.get("api")), "values": values, "token": space_token()}
        units = 0
        label = sid
        if mine(sid):
            st = cstate()
            x = _rented_entry(st, sid)
            if x and x.get("pause_when_ready"):      # du erstellst gerade etwas -> nicht automatisch pausieren
                x["pause_when_ready"] = False
                save_cstate(st)
            await _wake(sid)
    else:
        return web.json_response({"error": "Unbekannter Modus"}, status=400)
    spec["title"] = str(data.get("title") or label)[:80]
    spec["kind"] = "image" if data.get("kind") == "image" else "video"
    spec.setdefault("prompt", str(data.get("prompt_text") or ""))
    jid = uuid.uuid4().hex[:12]
    j = {"id": jid, "mode": mode, "label": label, "state": "running", "started": time.time(), "units": units,
         "status": {"stage": "start"}}
    JOBS[jid] = j
    j["task"] = asyncio.ensure_future(_run_job(j, spec))
    for old in [k for k, v in JOBS.items() if v.get("finished") and time.time() - v["finished"] > 3600]:
        JOBS.pop(old, None)
    return web.json_response({"id": jid})


@routes.get("/easy/cloud/job/{id}")
async def cloud_job(request):
    j = JOBS.get(request.match_info["id"])
    if not j:
        return web.json_response({"error": "unbekannt"}, status=404)
    return web.json_response(_job_view(j))


@routes.post("/easy/cloud/job/{id}/cancel")
async def cloud_job_cancel(request):
    j = JOBS.get(request.match_info["id"])
    if j and j.get("task") and not j["task"].done():
        j["task"].cancel()
        j["state"] = "error"
        j["error"] = "Abgebrochen."
        j["finished"] = time.time()
    return web.json_response({"ok": True})


@routes.get("/easy/cloud/gallery")
async def cloud_gallery(request):
    d = out_dir()
    items = []
    if os.path.isdir(d):
        for n in os.listdir(d):
            p = os.path.join(d, n)
            if os.path.isfile(p) and n.lower().endswith((".mp4", ".webm", ".mov", ".mkv", ".gif", ".png", ".jpg", ".jpeg", ".webp")):
                items.append({"filename": n, "subfolder": SUB, "type": "output", "mtime": os.path.getmtime(p)})
    items.sort(key=lambda x: -x["mtime"])
    return web.json_response({"items": items[:120]})


# ------------------------------------------------------------------ GPU mieten (eigener Space)
async def _hardware():
    items = await hf("GET", "/api/spaces/hardware", auth=False)
    out = []
    for h in items if isinstance(items, list) else []:
        acc = h.get("accelerator") or {}
        if not acc or h.get("name") in ("zero-a10g",):
            continue
        per_min = float(h.get("unitCostUSD") or 0)
        if (h.get("unitLabel") or "minute") == "hour":
            per_min /= 60
        out.append({"name": h.get("name"), "pretty": h.get("prettyName") or h.get("name"), "vram": acc.get("vram"),
                    "gpu": acc.get("model"), "qty": acc.get("quantity"), "ram": h.get("ram"), "cpu": h.get("cpu"),
                    "per_hour": round(per_min * 60, 2)})
    out.sort(key=lambda x: x["per_hour"])
    return out


@routes.get("/easy/cloud/hardware")
async def cloud_hardware(request):
    try:
        return web.json_response({"items": await cached("hardware", 3600, _hardware)})
    except Exception as e:
        return web.json_response({"items": [], "error": str(e)})


def mine(sid):
    return any(x["id"] == sid for x in cstate().get("rented", []))


# ---- „Sobald bereit pausieren“: wartet im Hintergrund, bis die GPU fertig geladen hat, und pausiert sie dann.
WATCH = {}


def _rented_entry(st, sid):
    for x in st.get("rented", []):
        if x["id"] == sid:
            return x
    return None


async def _ready_watch(sid):
    try:
        t0 = time.time()
        while time.time() - t0 < 2 * 3600:
            st = cstate()
            x = _rented_entry(st, sid)
            if not x or not x.get("pause_when_ready"):
                return
            try:
                rt = await hf("GET", f"/api/spaces/{sid}/runtime")
            except Exception:
                await asyncio.sleep(30)
                continue
            stage = rt.get("stage")
            if stage == "RUNNING":
                await hf("POST", f"/api/spaces/{sid}/pause")
                st = cstate()
                x = _rented_entry(st, sid)
                if x:
                    x["pause_when_ready"] = False          # gilt nur fuer diesen einen Start
                    x["auto_paused_at"] = time.time()
                    save_cstate(st)
                print(f"[Easy Generate] {sid} ist fertig geladen und wurde automatisch pausiert.")
                return
            if stage in ("PAUSED", "SLEEPING", "STOPPED", "BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "DELETING"):
                return
            await asyncio.sleep(20)
    except Exception as e:
        print("[Easy Generate] Bereit-Waechter:", e)
    finally:
        WATCH.pop(sid, None)


def ensure_watch(sid):
    if sid not in WATCH:
        WATCH[sid] = asyncio.ensure_future(_ready_watch(sid))


def _resume_watches():
    for x in cstate().get("rented", []):
        if x.get("pause_when_ready"):
            ensure_watch(x["id"])


async def _wake(sid):
    try:
        from . import remote as _r
        _r.touch_space(sid)
    except Exception:
        pass
    try:
        rt = await hf("GET", f"/api/spaces/{sid}/runtime")
        if rt.get("stage") in ("PAUSED", "SLEEPING", "STOPPED"):
            await hf("POST", f"/api/spaces/{sid}/restart")
    except Exception:
        pass


@routes.post("/easy/cloud/rent")
async def cloud_rent(request):
    if not json_body_required(request):
        return web.json_response({"error": "bad request"}, status=400)
    data = await request.json()
    src = parse_space(data.get("space"))
    hw = str(data.get("hardware") or "")
    sleep = int(data.get("sleep") or 900)
    if not src or src.startswith("http"):
        return web.json_response({"error": "Bitte einen HuggingFace-Space wählen (z. B. Lightricks/LTX-2-3)."}, status=400)
    if not token():
        return web.json_response({"error": "AUTH"}, status=400)
    try:
        me = await hf("GET", "/api/whoami-v2")
        user = me["name"]
        name = re.sub(r"[^\w.\-]", "-", "eg-" + src.split("/")[-1])[:90]
        target = f"{user}/{name}"
        try:
            await hf("POST", f"/api/spaces/{src}/duplicate",
                     body={"repository": target, "private": True, "hardware": hw, "sleepTimeSeconds": sleep}, timeout=60)
        except HFError as e:
            if e.status == 409:  # gibt es schon -> nur Hardware setzen
                await hf("POST", f"/api/spaces/{target}/hardware", body={"flavor": hw, "sleepTimeSeconds": sleep})
            else:
                raise
        st = cstate()
        st["rented"] = [x for x in st.get("rented", []) if x["id"] != target]
        st["rented"].append({"id": target, "from": src, "hardware": hw, "sleep": sleep, "created": time.time(),
                             "pause_when_ready": bool(data.get("pause_when_ready"))})
        save_cstate(st)
        if data.get("pause_when_ready"):
            ensure_watch(target)
        return web.json_response({"id": target})
    except HFError as e:
        msg = e.text
        try:
            msg = json.loads(e.text).get("error", msg)
        except Exception:
            pass
        code = "PAYMENT" if e.status == 402 or re.search(r"payment|billing|credit", msg, re.I) else "AUTH" if e.status in (401, 403) else ""
        return web.json_response({"error": (code + "|" if code else "") + msg}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def _rented_status():
    st = cstate()
    hwmap = {}
    try:
        hwmap = {h["name"]: h for h in await cached("hardware", 3600, _hardware)}
    except Exception:
        pass
    out = []

    async def one(x):
        it = dict(x)
        try:
            rt = await hf("GET", f"/api/spaces/{x['id']}/runtime")
            hw = (rt.get("hardware") or {})
            it.update(stage=rt.get("stage"), current=hw.get("current"), requested=hw.get("requested"),
                      sleep=rt.get("gcTimeout", x.get("sleep")))
        except HFError as e:
            it["stage"] = "GONE" if e.status == 404 else "ERROR"
        except Exception:
            it["stage"] = "UNKNOWN"
        h = hwmap.get(it.get("requested") or it.get("current") or it.get("hardware"))
        it["per_hour"] = h["per_hour"] if h else None
        it["pretty"] = h["pretty"] if h else (it.get("current") or it.get("hardware"))
        it["billing"] = it.get("stage") in ("RUNNING", "RUNNING_BUILDING", "BUILDING", "APP_STARTING", "RUNNING_APP_STARTING")
        out.append(it)
    await asyncio.gather(*(one(x) for x in st.get("rented", [])))
    out.sort(key=lambda x: -x.get("created", 0))
    return out


@routes.get("/easy/cloud/runtime")
async def cloud_runtime(request):
    """Zustand einer gemieteten GPU (baut / startet / laeuft / aus)."""
    sid = request.query.get("space", "")
    if not mine(sid) or not token():
        return web.json_response({"error": "unbekannt"}, status=400)
    try:
        rt = await hf("GET", f"/api/spaces/{sid}/runtime")
        hw = rt.get("hardware") or {}
        x = _rented_entry(cstate(), sid) or {}
        if x.get("pause_when_ready"):
            ensure_watch(sid)
        return web.json_response({"stage": rt.get("stage"), "hardware": hw.get("current"), "requested": hw.get("requested"),
                                  "message": (rt.get("errorMessage") or "")[:500], "pause_when_ready": bool(x.get("pause_when_ready")),
                                  "auto_paused_at": x.get("auto_paused_at")})
    except HFError as e:
        return web.json_response({"error": str(e)}, status=400)
    except Exception as e:
        return web.json_response({"error": "OFFLINE|" + str(e)}, status=502)


@routes.post("/easy/cloud/wake")
async def cloud_wake(request):
    data = await request.json()
    sid = str(data.get("space") or "")
    if not mine(sid):
        return web.json_response({"error": "unbekannt"}, status=400)
    await _wake(sid)
    return web.json_response({"ok": True})


@routes.get("/easy/cloud/rented")
async def cloud_rented(request):
    _resume_watches()
    if not token():
        return web.json_response({"items": [], "pause_on_exit": cstate().get("pause_on_exit", True)})
    return web.json_response({"items": await _rented_status(), "pause_on_exit": cstate().get("pause_on_exit", True)})


@routes.post("/easy/cloud/rented/{action}")
async def cloud_rented_action(request):
    if not json_body_required(request):
        return web.json_response({"error": "bad request"}, status=400)
    action = request.match_info["action"]
    data = await request.json()
    if action == "pause_when_ready":
        sid = str(data.get("space") or "")
        st = cstate()
        x = _rented_entry(st, sid)
        if not x:
            return web.json_response({"error": "unbekannt"}, status=400)
        x["pause_when_ready"] = bool(data.get("value"))
        save_cstate(st)
        if x["pause_when_ready"]:
            ensure_watch(sid)
        return web.json_response({"ok": True})
    if action == "pause_on_exit":
        st = cstate()
        st["pause_on_exit"] = bool(data.get("value"))
        save_cstate(st)
        return web.json_response({"ok": True})
    sid = str(data.get("space") or "")
    if not mine(sid):
        return web.json_response({"error": "Dieser Space wurde nicht von Easy Generate gemietet."}, status=400)
    try:
        if action == "pause":
            await hf("POST", f"/api/spaces/{sid}/pause")
        elif action == "start":
            await _wake(sid)
            await hf("POST", f"/api/spaces/{sid}/restart")
        elif action == "hardware":
            body = {"flavor": str(data.get("hardware"))}
            if data.get("sleep"):
                body["sleepTimeSeconds"] = int(data["sleep"])
            await hf("POST", f"/api/spaces/{sid}/hardware", body=body)
            st = cstate()
            for x in st["rented"]:
                if x["id"] == sid:
                    x["hardware"] = body["flavor"]
            save_cstate(st)
        elif action == "sleep":
            await hf("POST", f"/api/spaces/{sid}/sleeptime", body={"seconds": int(data.get("sleep") or 900)})
        elif action == "delete":
            org, name = sid.split("/", 1)
            try:
                await hf("DELETE", "/api/repos/delete", body={"type": "space", "name": name, "organization": org})
            except HFError as e:
                if e.status != 404:
                    raise
            st = cstate()
            st["rented"] = [x for x in st["rented"] if x["id"] != sid]
            save_cstate(st)
        elif action == "forget":
            st = cstate()
            st["rented"] = [x for x in st["rented"] if x["id"] != sid]
            save_cstate(st)
        else:
            return web.json_response({"error": "unbekannt"}, status=400)
        return web.json_response({"ok": True})
    except HFError as e:
        return web.json_response({"error": str(e)}, status=400)


@routes.post("/easy/cloud/pause_all")
async def cloud_pause_all(request):
    """Wird beim Beenden von Easy Generate aufgerufen (falls eingestellt)."""
    st = cstate()
    if not st.get("pause_on_exit", True) or not token():
        return web.json_response({"paused": 0})
    n = 0
    for x in st.get("rented", []):
        try:
            rt = await hf("GET", f"/api/spaces/{x['id']}/runtime", timeout=8)
            if rt.get("stage") not in ("PAUSED", "SLEEPING", "STOPPED"):
                await hf("POST", f"/api/spaces/{x['id']}/pause", timeout=8)
                n += 1
        except Exception:
            pass
    return web.json_response({"paused": n})
