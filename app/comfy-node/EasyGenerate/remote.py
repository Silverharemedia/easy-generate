"""Easy Generate - eigene Cloud-GPU mit ComfyUI.

Legt im HuggingFace-Konto einen privaten Docker-Space an, auf dem ComfyUI + diese Erweiterung laufen,
und reicht Anfragen der Oberflaeche dorthin durch (/easy/remote/...). So laufen die eigenen Vorlagen
genau wie zu Hause - nur auf einer gemieteten Grafikkarte.

Sicherheit: Der Space ist privat. Zugriff erfolgt mit dem Space-Schluessel (nur Lesen).
Der Haupt-Schluessel liegt als Space-Secret im eigenen Space (fuer gesperrte Modelle);
dort laeuft nur ComfyUI und Easy Generate - kein fremder Code.
"""
import asyncio
import base64
import json
import os
import time
from urllib.parse import quote, urlparse

import aiohttp
from aiohttp import web

from . import DATA, HERE, VERSION, routes
from .cloud import (HF, CACHE, HFError, _rented_entry, _resume_watches, cstate, ensure_watch, hf, json_body_required,
                    save_cstate, space_token, token)

SPACE_NAME = "eg-comfyui"
MAX_SLOTS = 20
# Nur erhoehen, wenn sich etwas aendert, das auf der Cloud-GPU selbst laufen muss
# (dann wird dort ein Update angeboten). 2 = Fortschritt per /easy/progress.
REMOTE_API = 6          # 3 = Schnellstart-Speicher (/data); 4 = Modelle beim Start auf die lokale Platte kopieren; 5 = Zeitlimit/Platzpruefung beim Kopieren; 6 = SeedVR2 zum Hochskalieren
BUCKET_NAME = "eg-models"

DOCKERFILE = """FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg libgl1 libglib2.0-0 \\
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 EG_CLOUD=1
WORKDIR /home/user
RUN pip install --user torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
RUN git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git \\
    && pip install --user -r ComfyUI/requirements.txt && pip install --user psutil
# SeedVR2 zum Hochskalieren (nur benutzt, wenn man es im Studio waehlt; torch bleibt unangetastet)
RUN git clone --depth 1 --branch v2.5.23 https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler.git ComfyUI/custom_nodes/seedvr2_videoupscaler \\
    && grep -viE '^(torch|torchvision|torchaudio)([<>=~! ]|$)' ComfyUI/custom_nodes/seedvr2_videoupscaler/requirements.txt > /tmp/seedvr2-req.txt \\
    && pip install --user -r /tmp/seedvr2-req.txt
COPY --chown=user EasyGenerate /home/user/ComfyUI/custom_nodes/EasyGenerate
COPY --chown=user start.sh /home/user/start.sh
EXPOSE 7860
CMD ["sh", "/home/user/start.sh"]
"""

# Ist der Schnellstart-Speicher (privater Bucket) unter /data eingebunden, liegen die Modelle dort dauerhaft.
START_SH = """#!/bin/sh
cd /home/user
if [ -d /data ] && [ -w /data ]; then
  mkdir -p /data/models
  echo "[Easy Generate] Schnellstart: hole Modelle aus dem Speicher ..."
  python - <<'EOF'
import os, sys, shutil, time, concurrent.futures as cf
src, dst = "/data/models", "/home/user/ComfyUI/models"
DEADLINE = 15 * 60           # laenger nie warten – sonst laeuft die bezahlte GPU nur fuers Kopieren
for root, _, files in os.walk(dst):          # halbe Kopien vom letzten Mal wegraeumen
    for f in files:
        if f.endswith(".cp"):
            try: os.remove(os.path.join(root, f))
            except OSError: pass
jobs = []
for root, _, files in os.walk(src):
    for f in files:
        if ".part" in f or ".up-" in f:
            continue
        a = os.path.join(root, f); b = os.path.join(dst, os.path.relpath(a, src))
        try:
            sa = os.path.getsize(a)
            if os.path.isfile(b) and os.path.getsize(b) == sa:
                continue
        except OSError:
            continue
        jobs.append((a, b, sa))
os.makedirs(dst, exist_ok=True)
free = shutil.disk_usage(dst).free - 20 * 1024 ** 3      # 20 GB Reserve fuer Ergebnisse/neue Modelle
keep = []
for a, b, sa in sorted(jobs, key=lambda x: x[2]):
    if sa <= free:
        keep.append((a, b)); free -= sa
if len(keep) < len(jobs):
    print("[Easy Generate] Schnellstart: zu wenig Platz – %d Dateien bleiben im Speicher" % (len(jobs) - len(keep)), flush=True)
def cp(ab):
    a, b = ab
    os.makedirs(os.path.dirname(b), exist_ok=True)
    with open(a, "rb") as fi, open(b + ".cp", "wb") as fo:
        shutil.copyfileobj(fi, fo, 64 * 1024 * 1024)
    os.replace(b + ".cp", b)
    return os.path.getsize(b)
t, n = time.time(), 0
ex = cf.ThreadPoolExecutor(8)
futs = [ex.submit(cp, x) for x in keep]
try:
    for fut in cf.as_completed(futs, timeout=DEADLINE):
        try:
            n += fut.result()
        except Exception as e:
            print("[Easy Generate] Schnellstart: Fehler", e, flush=True)
except cf.TimeoutError:
    print("[Easy Generate] Schnellstart: Zeitlimit erreicht – fehlende Modelle werden normal geladen", flush=True)
    sys.stdout.flush(); os._exit(0)
dt = max(time.time() - t, 0.1)
print("[Easy Generate] Schnellstart: %d Dateien, %.1f GB in %.0f s (%.0f MB/s)" % (len(keep), n / 1e9, dt, n / dt / 1e6), flush=True)
EOF
  export EG_MODEL_STORE=/data/models
fi
exec python ComfyUI/main.py --listen 0.0.0.0 --port 7860 --disable-auto-launch
"""

README = """---
title: Easy Generate ComfyUI
emoji: 🎬
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

Private Cloud-GPU fuer [Easy Generate](https://github.com/Silverharemedia/easy-generate):
ComfyUI mit der Easy-Generate-Erweiterung. Wird von Easy Generate verwaltet.
"""


def slot_of(x):
    try:
        return max(1, int(x.get("slot") or 1))
    except Exception:
        return 1


def space_name(slot):
    return SPACE_NAME if slot <= 1 else f"{SPACE_NAME}-{slot}"


def comfy_entries():
    """Alle eigenen Cloud-GPUs (GPU 1, GPU 2, ...), nach Nummer sortiert."""
    return sorted([x for x in cstate().get("rented", []) if x.get("kind") == "comfy"], key=slot_of)


def comfy_entry(slot=1):
    for x in comfy_entries():
        if slot_of(x) == int(slot or 1):
            return x
    return None


def req_slot(request, data=None):
    v = (data or {}).get("slot") if data else None
    if v is None:
        v = request.query.get("slot")
    try:
        return max(1, min(MAX_SLOTS, int(v or 1)))
    except Exception:
        return 1


def node_files():
    """Dateien der Erweiterung fuer den Space (ohne Nutzerdaten)."""
    out = []
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in ("data", "__pycache__")]
        for f in files:
            if f.endswith((".pyc",)) or f == "cloud_worker.py":
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, HERE).replace(os.sep, "/")
            out.append(("EasyGenerate/" + rel, p))
    return out


async def commit_files(repo_id, files, message):
    """Dateien per Commit-API hochladen (kleine Textdateien, base64)."""
    lines = [json.dumps({"key": "header", "value": {"summary": message, "description": ""}})]
    for path, content in files:
        if isinstance(content, str):
            content = content.encode("utf-8")
        lines.append(json.dumps({"key": "file", "value": {"content": base64.b64encode(content).decode(), "path": path, "encoding": "base64"}}))
    body = ("\n".join(lines) + "\n").encode()
    headers = {"Authorization": "Bearer " + token(), "Content-Type": "application/x-ndjson", "User-Agent": "EasyGenerate"}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as s:
        async with s.post(f"{HF}/api/spaces/{repo_id}/commit/main", data=body, headers=headers) as r:
            text = await r.text()
            if r.status >= 400:
                raise HFError(r.status, text)


def program_files():
    files = [("Dockerfile", DOCKERFILE), ("README.md", README), ("start.sh", START_SH)]
    for path, p in node_files():
        with open(p, "rb") as fh:
            files.append((path, fh.read()))
    return files


@routes.post("/easy/cloud/comfy/create")
async def comfy_create(request):
    if not json_body_required(request):
        return web.json_response({"error": "bad request"}, status=400)
    data = await request.json()
    hw = str(data.get("hardware") or "rtx-pro-6000")
    sleep = int(data.get("sleep") or 900)
    if not token():
        return web.json_response({"error": "AUTH"}, status=400)
    used = {slot_of(x) for x in comfy_entries()}
    slot = int(data.get("slot") or 0) or next((n for n in range(1, MAX_SLOTS + 1) if n not in used), MAX_SLOTS + 1)
    if slot in used:
        return web.json_response({"error": f"GPU {slot} gibt es schon."}, status=400)
    if slot > MAX_SLOTS:
        return web.json_response({"error": f"Hoechstens {MAX_SLOTS} Cloud-GPUs."}, status=400)
    name = space_name(slot)
    try:
        me = await hf("GET", "/api/whoami-v2")
        user = me["name"]
        sid = f"{user}/{name}"
        payload = {"name": name, "type": "space", "sdk": "docker", "private": True,
                   "hardware": hw, "sleepTimeSeconds": sleep,
                   "secrets": [{"key": "HF_TOKEN", "value": token()}]}
        try:
            await hf("POST", "/api/repos/create", body=payload, timeout=60)
        except HFError as e:
            if e.status != 409:
                raise

        def save_entry():
            st = cstate()
            st["rented"] = [x for x in st.get("rented", []) if x["id"] != sid]
            st["rented"].append({"id": sid, "from": "ComfyUI (Easy Generate)" + (f" · GPU {slot}" if slot > 1 else ""), "kind": "comfy", "slot": slot, "hardware": hw, "sleep": sleep,
                                 "created": time.time(), "version": VERSION, "api": REMOTE_API, "pause_when_ready": bool(data.get("pause_when_ready"))})
            save_cstate(st)
        save_entry()      # sofort merken: schlaegt danach etwas fehl, bleibt die (bezahlte) GPU trotzdem sichtbar und pausierbar
        await commit_files(sid, program_files(), f"Easy Generate {VERSION}")
        try:
            await hf("POST", f"/api/spaces/{sid}/secrets", body={"key": "HF_TOKEN", "value": token()})
        except Exception:
            pass
        try:
            await hf("POST", f"/api/spaces/{sid}/hardware", body={"flavor": hw, "sleepTimeSeconds": sleep})
        except HFError as e:
            if e.status == 402 or "payment" in e.text.lower() or "credit" in e.text.lower():
                return web.json_response({"error": "PAYMENT|" + e.text[:300]}, status=400)
            raise
        save_entry()
        if data.get("pause_when_ready"):
            ensure_watch(sid)
        if cstate().get("model_store"):
            try:
                await _set_volumes(sid, True, await _bucket_id())
            except Exception as err:
                print("[Easy Generate] Schnellstart-Speicher konnte nicht eingebunden werden:", err)
        return web.json_response({"id": sid, "slot": slot})
    except HFError as e:
        msg = e.text
        try:
            msg = json.loads(e.text).get("error", msg)
        except Exception:
            pass
        code = "AUTH" if e.status in (401, 403) else ""
        return web.json_response({"error": (code + "|" if code else "") + str(msg)[:400]}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


@routes.post("/easy/cloud/comfy/update")
async def comfy_update(request):
    """Programm auf der Cloud-GPU auf den Stand dieser Easy-Generate-Version bringen."""
    data = await request.json() if request.can_read_body else {}
    xs = comfy_entries() if (data or {}).get("all") else [comfy_entry(req_slot(request, data))]
    xs = [x for x in xs if x]
    if not xs:
        return web.json_response({"error": "Keine Cloud-GPU eingerichtet."}, status=400)
    try:
        files = program_files()
        for x in xs:
            was_off = await _is_off(x["id"])
            try:
                await commit_files(x["id"], files, f"Easy Generate {VERSION}")
            finally:
                if was_off:          # pausierte GPU nicht durch das Update starten
                    await _keep_off(x["id"])
            st = cstate()
            e = _rented_entry(st, x["id"])
            if e:
                e["version"] = VERSION
                e["api"] = REMOTE_API
                save_cstate(st)
        return web.json_response({"ok": True})
    except HFError as e:
        return web.json_response({"error": str(e)}, status=400)


async def _info(x):
    slot = slot_of(x)
    out = {"exists": True, "id": x["id"], "slot": slot, "B": base_path(slot), "hardware": x.get("hardware"), "remote_version": x.get("version"),
           "version": VERSION, "space_token": bool(space_token()), "needs_update": int(x.get("api") or 1) < REMOTE_API,
           "sleep": x.get("sleep")}
    if x.get("auto_paused_why") and time.time() - float(x.get("auto_paused_at") or 0) < 3600:
        out["auto_paused"] = x["auto_paused_why"]
    try:
        rt = await hf("GET", f"/api/spaces/{x['id']}/runtime")
        out["stage"] = rt.get("stage")
        out["current"] = (rt.get("hardware") or {}).get("current")
    except HFError as e:
        out["stage"] = "GONE" if e.status == 404 else "ERROR"
    except Exception:
        out["stage"] = "UNKNOWN"
    return out


def base_path(slot):
    """Adresse fuer die Oberflaeche: GPU 1 = /easy/remote, GPU 2 = /easy/remote2 ..."""
    return "/easy/remote" if slot <= 1 else f"/easy/remote{slot}"


@routes.get("/easy/cloud/comfy/info")
async def comfy_info(request):
    x = comfy_entry(req_slot(request))
    if not x:
        return web.json_response({"exists": False, "space_token": bool(space_token()), "version": VERSION})
    return web.json_response(await _info(x))


@routes.get("/easy/cloud/comfy/list")
async def comfy_list(request):
    xs = comfy_entries()
    items = await asyncio.gather(*[_info(x) for x in xs]) if xs else []
    return web.json_response({"items": list(items), "space_token": bool(space_token()), "version": VERSION})


# ------------------------------------------------------------------ Schnellstart-Speicher (optional)
# Ein privater Bucket im eigenen HF-Konto wird in alle Cloud-GPUs unter /data eingebunden.
# Modelle werden dort nur einmal gespeichert; jeder weitere Start findet sie sofort.
# Privater Speicher ist bei Hugging Face bis 100 GB (kostenloses Konto) bzw. 1 TB (PRO) inklusive.
async def _bucket_id():
    me = await hf("GET", "/api/whoami-v2")
    return f"{me['name']}/{BUCKET_NAME}"


async def _set_volumes(sid, on, bid):
    if on:
        await hf("PUT", f"/api/spaces/{sid}/volumes", body={"volumes": [{"type": "bucket", "source": bid, "mountPath": "/data"}]}, timeout=30)
    else:
        try:
            await hf("DELETE", f"/api/spaces/{sid}/volumes", timeout=30)
        except HFError as e:
            if e.status != 404:
                raise


async def _is_off(sid):
    """Ist die GPU aus? Unbekannt (Fehler) zaehlt sicherheitshalber als aus – lieber einmal zu oft pausieren als bezahlen."""
    for _ in range(2):
        try:
            rt = await hf("GET", f"/api/spaces/{sid}/runtime", timeout=15)
            return str(rt.get("stage") or "").upper() in ("PAUSED", "SLEEPING", "STOPPED")
        except Exception:
            await asyncio.sleep(2)
    return True


async def _keep_off(sid):
    """Pausieren – und nach kurzer Zeit nachsehen, ob HF die GPU durch die Aenderung doch wieder gestartet hat."""
    async def once():
        for _ in range(3):
            try:
                await hf("POST", f"/api/spaces/{sid}/pause", timeout=15)
                return True
            except Exception:
                await asyncio.sleep(3)
        print("[Easy Generate] Achtung: Cloud-GPU konnte nicht pausiert werden:", sid)
        return False
    await once()

    async def later():
        await asyncio.sleep(20)
        try:
            rt = await hf("GET", f"/api/spaces/{sid}/runtime", timeout=15)
            if str(rt.get("stage") or "").upper() not in ("PAUSED", "STOPPED"):
                await once()
        except Exception:
            await once()
    asyncio.ensure_future(later())


@routes.get("/easy/cloud/comfy/storage")
async def comfy_storage_info(request):
    st = cstate()
    out = {"on": bool(st.get("model_store")), "bucket": None, "size": None, "files": None}
    if not token():
        return web.json_response(out)
    try:
        bid = await _bucket_id()
        out["bucket"] = bid
        b = await hf("GET", f"/api/buckets/{bid}", timeout=15)
        out["size"], out["files"], out["exists"] = b.get("size"), b.get("totalFiles"), True
    except HFError as e:
        out["exists"] = False if e.status == 404 else None
    except Exception:
        pass
    return web.json_response(out)


@routes.post("/easy/cloud/comfy/storage")
async def comfy_storage(request):
    data = await request.json()
    act = str(data.get("action") or "")
    if not token():
        return web.json_response({"error": "AUTH"}, status=400)
    try:
        bid = await _bucket_id()
        if act == "on":
            try:
                await hf("POST", f"/api/buckets/{bid}", body={"visibility": "private"}, timeout=30)
            except HFError as e:
                if e.status != 409:
                    raise
            files = program_files()
            for x in comfy_entries():
                was_off = await _is_off(x["id"])
                try:
                    if int(x.get("api") or 1) < REMOTE_API:          # Startskript mit /data-Unterstuetzung aufspielen
                        await commit_files(x["id"], files, f"Easy Generate {VERSION}")
                        st = cstate(); e = _rented_entry(st, x["id"])
                        if e:
                            e["version"], e["api"] = VERSION, REMOTE_API
                            save_cstate(st)
                    await _set_volumes(x["id"], True, bid)
                finally:
                    if was_off:          # eine pausierte GPU bleibt pausiert (kein ungewollter, bezahlter Start) – auch bei Fehlern
                        await _keep_off(x["id"])
            st = cstate(); st["model_store"] = True; save_cstate(st)
        elif act in ("off", "delete"):
            for x in comfy_entries():
                was_off = await _is_off(x["id"])
                try:
                    await _set_volumes(x["id"], False, bid)
                finally:
                    if was_off:
                        await _keep_off(x["id"])
            st = cstate(); st["model_store"] = False; save_cstate(st)
            if act == "delete":
                try:
                    await hf("DELETE", f"/api/buckets/{bid}", timeout=30)
                except HFError as e:
                    if e.status != 404:
                        raise
        else:
            return web.json_response({"error": "unbekannt"}, status=400)
        return web.json_response({"ok": True})
    except HFError as e:
        msg = e.text
        try:
            msg = json.loads(e.text).get("error", msg)
        except Exception:
            pass
        code = "PAYMENT|" if e.status == 402 else ("AUTH|" if e.status in (401, 403) else "")
        return web.json_response({"error": code + str(msg)[:400]}, status=400)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ------------------------------------------------------------------ Durchreichen an die Cloud-GPU
async def target(slot=1):
    x = comfy_entry(slot)
    if not x:
        raise web.HTTPNotFound(text="Keine Cloud-GPU eingerichtet.")
    host = x.get("host")
    if not host:
        info = await hf("GET", f"/api/spaces/{x['id']}")
        host = info.get("host") or (f"https://{info['subdomain']}.hf.space" if info.get("subdomain") else "")
        if not host:
            raise web.HTTPServiceUnavailable(text="Adresse der Cloud-GPU unbekannt.")
        st = cstate()
        e = _rented_entry(st, x["id"])
        if e:
            e["host"] = host
            save_cstate(st)
    h = (urlparse(host).hostname or "").lower()
    if not h.endswith(".hf.space"):
        raise web.HTTPForbidden(text="Unerwartete Adresse.")
    return host.rstrip("/")


def auth_headers():
    t = space_token()
    if not t:
        raise web.HTTPUnauthorized(text="AUTH")
    return {"Authorization": "Bearer " + t, "X-HF-Authorization": "Bearer " + t}


_SESSION = {}


def session():
    s = _SESSION.get("s")
    if s is None or s.closed:
        s = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=600))
        _SESSION["s"] = s
    return s


async def remote_ws(request, slot=1):
    host = await target(slot)
    headers = auth_headers()
    url = host.replace("https://", "wss://", 1) + "/ws?clientId=" + request.query.get("clientId", "eg")
    local = web.WebSocketResponse(heartbeat=30)
    await local.prepare(request)
    try:
        async with session().ws_connect(url, headers=headers, heartbeat=30) as rws:
            async def up():
                async for m in local:
                    if m.type == aiohttp.WSMsgType.TEXT:
                        await rws.send_str(m.data)
            t = asyncio.ensure_future(up())
            async for m in rws:
                if m.type == aiohttp.WSMsgType.TEXT:
                    await local.send_str(m.data)
                elif m.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
            t.cancel()
    except Exception as e:
        try:
            await local.send_str(json.dumps({"type": "eg_remote_error", "data": {"error": str(e)[:300]}}))
        except Exception:
            pass
    await local.close()
    return local


@routes.route("*", r"/easy/remote{slot:\d*}/{tail:.*}")
async def remote_proxy(request):
    tail = request.match_info["tail"]
    slot = int(request.match_info.get("slot") or 1)
    if tail == "ws":
        return await remote_ws(request, slot)
    # Nur echte Nutzung zaehlt (Auftrag schicken, Bild hochladen, Modell laden, Ergebnis abholen) –
    # automatisches Nachfragen (Fortschritt, Warteschlange, Version …) haelt die GPU NICHT wach.
    if request.method != "GET" or tail.startswith("view"):
        act(slot)["last"] = time.time()
    host = await target(slot)
    headers = auth_headers()
    if request.headers.get("Content-Type"):
        headers["Content-Type"] = request.headers["Content-Type"]
    body = await request.read() if request.can_read_body else None
    url = f"{host}/{tail}"
    if request.query_string:
        url += "?" + request.query_string
    try:
        r = await session().request(request.method, url, headers=headers, data=body, allow_redirects=False)
    except Exception as e:
        return web.json_response({"error": "REMOTE_DOWN|" + str(e)[:300]}, status=502)
    try:
        ctype = r.headers.get("Content-Type", "application/octet-stream")
        if r.status in (401, 403, 404) and "text/html" in ctype:
            await r.read()
            return web.json_response({"error": "REMOTE_DOWN|HTTP %d" % r.status}, status=502)
        resp = web.StreamResponse(status=r.status, headers={"Content-Type": ctype})
        if r.headers.get("Content-Length"):
            resp.content_length = int(r.headers["Content-Length"])
        await resp.prepare(request)
        async for chunk in r.content.iter_chunked(1024 * 1024):
            await resp.write(chunk)
        await resp.write_eof()
        return resp
    finally:
        r.release()


@routes.post("/easy/cloud/comfy/fetch")
async def comfy_fetch(request):
    """Ergebnisse von der Cloud-GPU auf den PC holen und in die Galerie einsortieren."""
    from . import gallery
    data = await request.json()
    job = str(data.get("job") or "")
    if job:
        async with gallery.job_lock("gpu:" + job):
            done = gallery.job_get("gpu:" + job)
            if done:
                return web.json_response({"files": done})
            resp = await _comfy_fetch(request, data)
            try:
                gallery.job_put("gpu:" + job, json.loads(resp.body).get("files") or [])
            except Exception:
                pass
            return resp
    return await _comfy_fetch(request, data)


async def _comfy_fetch(request, data):
    from . import gallery
    slot = req_slot(request, data)
    act(slot)["last"] = time.time()
    host = await target(slot)
    headers = auth_headers()
    outdir = os.path.join(gallery.output_dir(), "easy-cloud-gpu")
    os.makedirs(outdir, exist_ok=True)
    refs = []
    for f in data.get("files") or []:
        name = os.path.basename(str(f.get("filename") or ""))
        if not name:
            continue
        q = "filename=%s&subfolder=%s&type=%s" % tuple(quote(str(f.get(k) or d), safe="")
                                                       for k, d in (("filename", ""), ("subfolder", ""), ("type", "output")))
        dst = gallery.reserve_path(outdir, name)   # zwei GPUs liefern oft denselben Dateinamen
        try:
            async with session().get(f"{host}/view?{q}", headers=headers) as r:
                if r.status != 200:
                    os.remove(dst)
                    continue
                with open(dst + ".part", "wb") as fh:
                    async for chunk in r.content.iter_chunked(1024 * 1024):
                        fh.write(chunk)
            os.replace(dst + ".part", dst)
        except Exception:
            for p in (dst, dst + ".part"):
                try:
                    os.remove(p)
                except OSError:
                    pass
            raise
        act(slot)["last"] = time.time()
        t = await asyncio.to_thread(gallery.place, dst, str(data.get("model") or ""), str(data.get("kind") or ""),
                                    str(data.get("prompt") or ""), "cloud")
        ref = gallery.file_ref(t)
        if ref:
            refs.append(dict(ref, name=os.path.basename(t)))
    return web.json_response({"files": refs})


# ------------------------------------------------------------------ Leerlauf-Waechter
# Unabhaengig von HuggingFace: Laeuft die Cloud-GPU laenger als die eingestellte Zeit ohne Auftrag,
# pausiert Easy Generate sie selbst. (Wird regelmaessig von der Oberflaeche angestossen.)
ACT = {"last": time.time(), "checked": 0, "busy": False}   # "last" = GPU 1 (alt), weitere GPUs in SLOTS
SLOTS = {}


def act(slot=1):
    if slot <= 1:
        return ACT
    return SLOTS.setdefault(slot, {"last": time.time()})


def touch_space(sid):
    """Leerlauf-Uhr der GPU zuruecksetzen, zu der dieser Space gehoert."""
    for x in comfy_entries():
        if x["id"] == sid:
            act(slot_of(x))["last"] = time.time()


async def _idle_check():
    if not token():
        return
    for x in comfy_entries():
        try:
            await _idle_one(x)
        except Exception as err:
            print("[Easy Generate] Leerlauf-Pruefung:", err)


HUNG = int(os.environ.get("EG_HUNG") or 40 * 60)     # so lange ohne jede Fortschrittsmeldung, obwohl ein Auftrag laeuft = haengt


async def _pause_idle(x, why):
    try:
        await hf("POST", f"/api/spaces/{x['id']}/pause")
        st = cstate()
        e = _rented_entry(st, x["id"])
        if e:
            e["auto_paused_at"] = time.time()
            e["auto_paused_why"] = why
            save_cstate(st)
        print(f"[Easy Generate] Cloud-GPU {x['id']} wurde pausiert: {why}")
    except Exception as err:
        print("[Easy Generate] Cloud-GPU konnte nicht pausiert werden:", err)


async def _idle_one(x):
    slot = slot_of(x)
    A = act(slot)
    try:
        rt = await hf("GET", f"/api/spaces/{x['id']}/runtime", timeout=15)
    except Exception:
        return
    stage = rt.get("stage")
    if stage != "RUNNING":
        A["last"] = time.time()            # Uhr laeuft erst, wenn sie wirklich bereit ist
        A.pop("unreach", None); A.pop("seq", None)
        if stage in ("BUILDING", "APP_STARTING", "RUNNING_BUILDING", "RUNNING_APP_STARTING"):
            A.setdefault("boot", time.time())
            if time.time() - A["boot"] > 45 * 60:   # Start haengt (bezahlt!) -> anhalten
                A.pop("boot", None)
                await _pause_idle(x, "Start dauerte ueber 45 Min.")
        else:
            A.pop("boot", None)
        return
    A.pop("boot", None)
    limit = int(x.get("sleep") or 900)
    host, headers = None, auth_headers()
    try:
        host = await target(slot)
        async with session().get(host + "/queue", headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as r:
            q = await r.json() if r.status == 200 else None
    except Exception:
        q = None
    if q is None:
        # laeuft (bezahlt), antwortet aber nicht: nach der Leerlaufzeit trotzdem pausieren
        A.setdefault("unreach", time.time())
        if time.time() - A["unreach"] >= limit and time.time() - A["last"] >= limit:
            A.pop("unreach", None)
            await _pause_idle(x, f"antwortete {limit // 60} Min. nicht")
        return
    A.pop("unreach", None)
    if q.get("queue_running") or q.get("queue_pending"):
        # Haengt der laufende Auftrag? (keine Fortschrittsmeldung seit HUNG)
        try:
            async with session().get(host + "/easy/progress?since=999999999", headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as r:
                seq = (await r.json()).get("seq") if r.status == 200 else None
        except Exception:
            seq = None
        if seq is not None and seq != A.get("seq"):
            A["seq"], A["seq_t"] = seq, time.time()
        if q.get("queue_running") and A.get("seq_t") and time.time() - A["seq_t"] > HUNG:
            try:
                async with session().post(host + "/interrupt", headers=headers, timeout=aiohttp.ClientTimeout(total=20)):
                    pass
                async with session().post(host + "/queue", headers=dict(headers, **{"Content-Type": "application/json"}), data=json.dumps({"clear": True}), timeout=aiohttp.ClientTimeout(total=20)):
                    pass
            except Exception:
                pass
            A.pop("seq", None); A.pop("seq_t", None)
            await _pause_idle(x, f"Auftrag hing {HUNG // 60} Min. ohne Fortschritt")
            return
        A["last"] = time.time()
        return
    A.pop("seq", None); A.pop("seq_t", None)
    if time.time() - A["last"] < limit:
        return
    try:
        async with session().get(host + "/easy/models/status", headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as r:
            ms = await r.json() if r.status == 200 else {}
        if ms.get("running") or ms.get("uploading"):
            A["last"] = time.time()
            return
    except Exception:
        pass
    await _pause_idle(x, f"{limit // 60} Min. ohne Auftrag")


async def _tick():
    try:
        _resume_watches()
        await _idle_check()
    finally:
        ACT["busy"] = False


def tick():
    """Hoechstens einmal pro Minute: Bereit-Waechter fortsetzen und Leerlauf pruefen."""
    if ACT["busy"] or time.time() - ACT["checked"] < 60:
        return
    ACT["checked"] = time.time()
    ACT["busy"] = True
    asyncio.ensure_future(_tick())


@routes.post("/easy/cloud/comfy/touch")
async def comfy_touch(request):
    data = await request.json() if request.can_read_body else {}
    act(req_slot(request, data if isinstance(data, dict) else {}))["last"] = time.time()
    return web.json_response({"ok": True})
