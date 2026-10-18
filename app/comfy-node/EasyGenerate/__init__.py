"""Easy Generate - ComfyUI-Erweiterung.

Stellt die Easy-Generate-Oberflaeche unter /easy bereit und kuemmert sich um
Vorlagen, Modelle (pruefen, einsortieren, laden, entfernen) und den Prompt-Helfer.
Es werden keine Knoten hinzugefuegt.
"""
import asyncio
import json
import os
import shutil
import sys
import time

import aiohttp
from aiohttp import web
from server import PromptServer

VERSION = "1.4.0"
HERE = os.path.dirname(os.path.abspath(__file__))
UI_FILE = os.path.join(HERE, "ui", "index.html")
DATA = os.path.join(HERE, "data")
WF_DIR = os.path.join(DATA, "workflows")
CFG_FILE = os.path.join(DATA, "config.json")
REG_FILE = os.path.join(DATA, "installed.json")
os.makedirs(WF_DIR, exist_ok=True)

routes = PromptServer.instance.routes
MODEL_EXT = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin", ".sft")
GB = 1024 ** 3


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ---------------------------------------------------------------- Seite
@routes.get("/easy")
async def easy_page(request):
    return web.FileResponse(UI_FILE, headers={"Cache-Control": "no-store"})


@routes.get("/easy/i18n.js")
async def easy_i18n(request):
    return web.FileResponse(os.path.join(HERE, "ui", "i18n.js"), headers={"Cache-Control": "no-store", "Content-Type": "application/javascript"})


@routes.get("/easy/version")
async def easy_version(request):
    return web.json_response({"version": VERSION})


# ---------------------------------------------------------------- Einstellungen
DEFAULT_CFG = {"provider": "ollama", "claude_key": "", "claude_model": "claude-haiku-5-5",
               "ollama_url": "http://127.0.0.1:11434", "ollama_model": "", "hf_token": "", "hf_space_token": "",
               "active": {"video": "", "image": ""}}


def load_cfg():
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    cfg.update(read_json(CFG_FILE, {}))
    return cfg


def public_cfg(cfg):
    out = dict(cfg)
    k = out.pop("claude_key", "")
    out["claude_key_set"] = bool(k)
    out["claude_key_hint"] = ("…" + k[-4:]) if k else ""
    t = out.pop("hf_token", "")
    out["hf_token_set"] = bool(t)
    st = out.pop("hf_space_token", "")
    out["hf_space_token_set"] = bool(st)
    return out


@routes.get("/easy/config")
async def easy_get_cfg(request):
    return web.json_response(public_cfg(load_cfg()))


@routes.post("/easy/config")
async def easy_set_cfg(request):
    data = await request.json()
    cfg = load_cfg()
    for k in ("provider", "claude_model", "ollama_url", "ollama_model"):
        if isinstance(data.get(k), str):
            cfg[k] = data[k].strip()
    for k in ("claude_key", "hf_token", "hf_space_token"):
        if isinstance(data.get(k), str) and data[k].strip():
            cfg[k] = data[k].strip()
        if data.get(k + "_clear"):
            cfg[k] = ""
    if cfg.get("hf_space_token") and cfg["hf_space_token"] == cfg.get("hf_token"):
        cfg["hf_space_token"] = ""
        write_json(CFG_FILE, cfg)
        return web.json_response(dict(public_cfg(cfg), error="SAME_TOKEN"))
    if isinstance(data.get("active"), dict):
        cfg["active"].update({k: v for k, v in data["active"].items() if k in ("video", "image") and isinstance(v, str)})
    write_json(CFG_FILE, cfg)
    return web.json_response(public_cfg(cfg))


# ---------------------------------------------------------------- Vorlagen-Katalog
def template_dirs():
    dirs = []
    for p in sys.path:
        try:
            if not os.path.isdir(p):
                continue
            for name in os.listdir(p):
                if name.lower().startswith("comfyui_workflow_templates"):
                    t = os.path.join(p, name, "templates")
                    if os.path.isdir(t) and t not in dirs:
                        dirs.append(t)
        except Exception:
            pass
    return dirs


def find_template(name):
    name = os.path.basename(name)
    for d in template_dirs():
        f = os.path.join(d, name + ".json")
        if os.path.isfile(f):
            return f
    return None


def collect_models(obj, found):
    if isinstance(obj, dict):
        if isinstance(obj.get("name"), str) and isinstance(obj.get("directory"), str) and isinstance(obj.get("url"), str):
            found.setdefault(obj["name"], {"name": obj["name"], "directory": obj["directory"].strip("/\\"), "url": obj["url"]})
        for v in obj.values():
            collect_models(v, found)
    elif isinstance(obj, list):
        for v in obj:
            collect_models(v, found)


_MODELS_CACHE = {}


def template_models(name):
    if name in _MODELS_CACHE:
        return _MODELS_CACHE[name]
    f = find_template(name)
    found = {}
    if f:
        collect_models(read_json(f, {}), found)
    _MODELS_CACHE[name] = list(found.values())
    return _MODELS_CACHE[name]


def license_note(name, t):
    text = (name + " " + " ".join(t.get("models", [])) + " " + " ".join(t.get("tags", []))).lower()
    if "minimax" in text or "fasth3" in text or "minimax h3" in text:
        return ("Die Lizenz der MiniMax-H3-Modelldateien schliesst die lokale Nutzung in der EU, "
                "Grossbritannien, Suedkorea und den USA aus (auch fuer die erzeugten Videos). "
                "Bitte pruefe vor der Installation, ob du sie nutzen darfst.")
    return ""


CAT_KIND = {"Image": "image", "Image Tools": "image", "Video": "video", "Video Tools": "video"}
_CATALOG = None


def catalog():
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    out, seen = [], set()
    for d in template_dirs():
        idx = os.path.join(d, "index.json")
        if not os.path.isfile(idx):
            continue
        for cat in read_json(idx, []):
            kind = CAT_KIND.get(cat.get("title", ""))
            if not kind:
                continue
            for t in cat.get("templates", []):
                n = t.get("name", "")
                if not n or n in seen or n.startswith("api_") or t.get("openSource") is False:
                    continue
                if not find_template(n):
                    continue
                seen.add(n)
                out.append({
                    "name": n, "title": t.get("title", n), "description": t.get("description", ""),
                    "kind": kind, "tool": cat.get("title", "").endswith("Tools"),
                    "tags": t.get("tags", []), "models": t.get("models", []), "date": t.get("date", ""),
                    "size": t.get("size", 0) or 0, "usage": t.get("usage", 0) or 0, "vram": t.get("vram", 0) or 0,
                    "thumb": f"/templates/{n}-1.{t.get('mediaSubtype', 'webp')}",
                    "license_note": license_note(n, t),
                })
    _CATALOG = out
    return out


def model_present(m):
    import folder_paths
    try:
        return bool(folder_paths.get_full_path(m["directory"], m["name"]))
    except Exception:
        return False


def registry():
    return read_json(REG_FILE, {})


@routes.get("/easy/catalog")
async def easy_catalog(request):
    reg = registry()
    items = []
    acc = access_cache()
    if not ACCESS["busy"]:
        asyncio.create_task(_bg_refresh())      # Zugaenge im Hintergrund pruefen (max. 1x pro Tag)
    for t in catalog():
        ms = template_models(t["name"])
        have = sum(1 for m in ms if model_present(m))
        r = reg.get(t["name"], {})
        need, manual = access_for_template(t["name"], acc)
        items.append(dict(t, model_count=len(ms), model_have=have, access_need=need, access_manual=manual,
                          installed=bool(r) and os.path.isfile(os.path.join(WF_DIR, t["name"] + ".json")),
                          enabled=r.get("enabled", True)))
    return web.json_response({"items": items})


@routes.get("/easy/template/{name}")
async def easy_template(request):
    f = find_template(request.match_info["name"])
    if not f:
        return web.json_response({"error": "nicht gefunden"}, status=404)
    return web.FileResponse(f)


# ---------------------------------------------------------------- installierte Werkzeuge
def safe_name(n):
    n = os.path.basename(str(n))
    if not n or n.startswith("."):
        raise ValueError("Ungueltiger Name")
    return n


@routes.get("/easy/installed")
async def easy_installed(request):
    reg = registry()
    out = []
    for name, r in reg.items():
        wf = os.path.join(WF_DIR, name + ".json")
        if os.path.isfile(wf):
            ms = template_models(name) if not r.get("custom") else []
            out.append(dict(r, name=name, ready=all(model_present(m) for m in ms)))
    return web.json_response({"items": out})


@routes.get("/easy/workflow/{name}")
async def easy_get_workflow(request):
    p = os.path.join(WF_DIR, safe_name(request.match_info["name"]) + ".json")
    if not os.path.isfile(p):
        return web.json_response({"error": "nicht gefunden"}, status=404)
    return web.FileResponse(p)


@routes.post("/easy/workflow/{name}")
async def easy_set_workflow(request):
    """Speichert einen umgewandelten (API-)Ablauf samt Eintrag in der Liste."""
    name = safe_name(request.match_info["name"])
    data = await request.json()
    wf, meta = data.get("workflow"), data.get("meta", {})
    if not isinstance(wf, dict) or not wf or not all(isinstance(v, dict) and "class_type" in v for v in wf.values()):
        return web.json_response({"error": "Kein gueltiger API-Ablauf"}, status=400)
    write_json(os.path.join(WF_DIR, name + ".json"), wf)
    reg = registry()
    entry = reg.get(name, {})
    entry.update({k: meta[k] for k in ("title", "kind", "custom", "thumb", "description") if k in meta})
    entry.setdefault("enabled", True)
    entry["added"] = entry.get("added") or time.strftime("%Y-%m-%d")
    reg[name] = entry
    write_json(REG_FILE, reg)
    return web.json_response({"ok": True})


@routes.post("/easy/enable/{name}")
async def easy_enable(request):
    name = safe_name(request.match_info["name"])
    data = await request.json()
    reg = registry()
    if name in reg:
        reg[name]["enabled"] = bool(data.get("enabled", True))
        write_json(REG_FILE, reg)
    return web.json_response({"ok": True})


@routes.post("/easy/uninstall/{name}")
async def easy_uninstall(request):
    """Entfernt ein Werkzeug. Mit delete_models werden nur Modelle geloescht, die kein anderes Werkzeug braucht."""
    import folder_paths
    name = safe_name(request.match_info["name"])
    data = await request.json()
    reg = registry()
    reg.pop(name, None)
    write_json(REG_FILE, reg)
    p = os.path.join(WF_DIR, name + ".json")
    if os.path.isfile(p):
        os.remove(p)
    deleted, kept, freed = [], [], 0
    if data.get("delete_models"):
        still = set()
        for other in reg:
            for m in template_models(other):
                still.add(m["name"])
        for m in template_models(name):
            if m["name"] in still:
                kept.append(m["name"])
                continue
            path = folder_paths.get_full_path(m["directory"], m["name"])
            if path and os.path.isfile(path):
                freed += os.path.getsize(path)
                os.remove(path)
                deleted.append(m["name"])
        refresh_model_cache()
    return web.json_response({"ok": True, "deleted": deleted, "kept": kept, "freed": freed})


@routes.get("/easy/uninstall_preview/{name}")
async def easy_uninstall_preview(request):
    import folder_paths
    name = safe_name(request.match_info["name"])
    reg = registry()
    still = set()
    for other in reg:
        if other != name:
            for m in template_models(other):
                still.add(m["name"])
    out, total = [], 0
    for m in template_models(name):
        path = folder_paths.get_full_path(m["directory"], m["name"])
        size = os.path.getsize(path) if path and os.path.isfile(path) else 0
        shared = m["name"] in still
        if not shared:
            total += size
        out.append({"name": m["name"], "size": size, "shared": shared, "present": bool(path)})
    return web.json_response({"models": out, "freed": total})


# ---------------------------------------------------------------- Modelle einsortieren
def downloads_dir():
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]
            g = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
                path = p.value
                ctypes.windll.ole32.CoTaskMemFree(p)
                if path and os.path.isdir(path):
                    return path
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Downloads")


def target_path(directory):
    import folder_paths
    paths = folder_paths.get_folder_paths(directory)
    if not paths:
        raise ValueError("Unbekannter Modellordner: " + directory)
    os.makedirs(paths[0], exist_ok=True)
    return paths[0]


def refresh_model_cache():
    try:
        import folder_paths
        if hasattr(folder_paths, "filename_list_cache"):
            folder_paths.filename_list_cache.clear()
    except Exception:
        pass


def locate_misplaced(name):
    import folder_paths
    cands = [os.path.join(downloads_dir(), name), os.path.join(folder_paths.models_dir, name)]
    for key in list(folder_paths.folder_names_and_paths.keys()):
        try:
            p = folder_paths.get_full_path(key, name)
            if p:
                cands.append(p)
        except Exception:
            pass
    for c in cands:
        if c and os.path.isfile(c) and os.path.getsize(c) > 1024 * 1024:
            return c
    return None


@routes.post("/easy/models/prepare")
async def easy_models_prepare(request):
    data = await request.json()
    models = {}
    for t in data.get("templates", []):
        for m in template_models(t):
            models.setdefault(m["name"], m)
    result = []
    for m in models.values():
        entry = dict(m)
        try:
            if model_present(m):
                entry["status"] = "ok"
            else:
                src = locate_misplaced(m["name"])
                if src:
                    dst = os.path.join(target_path(m["directory"]), m["name"])
                    await asyncio.to_thread(shutil.move, src, dst)
                    entry["status"] = "moved"
                    entry["from"] = src
                else:
                    entry["status"] = "missing"
        except Exception as e:
            entry["status"] = "missing"
            entry["error"] = str(e)
        result.append(entry)
    refresh_model_cache()
    return web.json_response({"models": result})


# ---------------------------------------------------------------- Downloads (Warteschlange)
DL = {"queue": [], "running": False, "speed": 0, "current": "", "errors": [], "cancel": False}


async def _download_one(session, m):
    dst = os.path.join(target_path(m["directory"]), m["name"])
    if os.path.isfile(dst):
        m["got"] = m["size"] = os.path.getsize(dst)
        return
    part = dst + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    token = load_cfg().get("hf_token")
    if token and "huggingface.co" in m["url"]:
        headers["Authorization"] = "Bearer " + token
    async with session.get(m["url"], headers=headers) as r:
        if r.status in (401, 403):
            raise RuntimeError("Download verweigert – dieses Modell braucht einen HuggingFace-Zugang (Token in den Einstellungen)")
        if r.status == 416 and have:
            os.replace(part, dst)
            return
        if r.status not in (200, 206):
            raise RuntimeError(f"Server antwortet mit Fehler {r.status}")
        if r.status == 200:
            have = 0
        m["size"] = int(r.headers.get("Content-Length", 0)) + have
        DL["current"] = m["name"]
        last_t, last_b, got = time.time(), have, have
        with open(part, "ab" if have else "wb") as f:
            async for chunk in r.content.iter_chunked(4 * 1024 * 1024):
                if DL["cancel"]:
                    raise asyncio.CancelledError()
                await asyncio.to_thread(f.write, chunk)
                got += len(chunk)
                m["got"] = got
                now = time.time()
                if now - last_t >= 1:
                    DL["speed"] = (got - last_b) / (now - last_t)
                    last_t, last_b = now, got
    if m["size"] and os.path.getsize(part) < m["size"]:
        raise RuntimeError("Download unvollstaendig – wird beim naechsten Versuch fortgesetzt")
    os.replace(part, dst)


async def _worker():
    DL["running"] = True
    DL["cancel"] = False
    try:
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=120)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            while True:
                m = next((x for x in DL["queue"] if x["status"] == "queued"), None)
                if not m or DL["cancel"]:
                    break
                m["status"] = "loading"
                for attempt in range(3):
                    try:
                        await _download_one(s, m)
                        m["status"] = "ok"
                        break
                    except asyncio.CancelledError:
                        m["status"] = "paused"
                        raise
                    except Exception as e:
                        msg = str(e)
                        if isinstance(e, aiohttp.ClientConnectorError) or "Cannot connect" in msg:
                            msg = "Keine Verbindung zum Download-Server (Internet/Firewall pruefen)"
                        if attempt == 2 or "verweigert" in msg:
                            m["status"] = "error"
                            m["error"] = msg
                            DL["errors"].append(f"{m['name']}: {msg}")
                            break
                        await asyncio.sleep(3)
                refresh_model_cache()
    except asyncio.CancelledError:
        for x in DL["queue"]:
            if x["status"] in ("queued", "loading"):
                x["status"] = "paused"
    finally:
        DL["running"] = False
        DL["speed"] = 0
        DL["current"] = ""
        refresh_model_cache()


@routes.post("/easy/models/download")
async def easy_models_download(request):
    data = await request.json()
    names = {x["name"] for x in DL["queue"]}
    added = []
    for m in data.get("models", []):
        if not m.get("url") or not m.get("name"):
            continue
        if m["name"] in names:
            for x in DL["queue"]:
                if x["name"] == m["name"] and x["status"] in ("error", "paused"):
                    x["status"] = "queued"
                    x.pop("error", None)
            continue
        item = {"name": m["name"], "directory": m["directory"], "url": m["url"], "got": 0, "size": 0,
                "status": "queued", "template": data.get("template", "")}
        DL["queue"].append(item)
        added.append(item)
    # Groessen holen + Speicherplatz pruefen
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            for m in added:
                try:
                    async with s.head(m["url"], allow_redirects=True) as r:
                        m["size"] = int(r.headers.get("Content-Length", 0))
                except Exception:
                    pass
        need = sum(max(0, x["size"] - x["got"]) for x in DL["queue"] if x["status"] in ("queued", "loading"))
        if added:
            free = shutil.disk_usage(target_path(added[0]["directory"])).free
            if need and need > free - 2 * GB:
                for m in added:
                    DL["queue"].remove(m)
                return web.json_response({"error": f"Zu wenig Speicherplatz: benoetigt {need / GB:.1f} GB, frei {free / GB:.1f} GB."}, status=400)
    except Exception:
        pass
    DL["errors"] = []
    if not DL["running"]:
        asyncio.create_task(_worker())
    return web.json_response({"ok": True})


@routes.get("/easy/models/status")
async def easy_models_status(request):
    q = DL["queue"]
    active = [x for x in q if x["status"] in ("queued", "loading")]
    return web.json_response({
        "running": DL["running"], "speed": DL["speed"], "current": DL["current"], "errors": DL["errors"],
        "got": sum(x["got"] for x in active), "total": sum(x["size"] for x in active),
        "items": [{k: x.get(k) for k in ("name", "got", "size", "status", "template", "error", "url")} for x in q],
    })


@routes.post("/easy/models/cancel")
async def easy_models_cancel(request):
    DL["cancel"] = True
    return web.json_response({"ok": True})


@routes.post("/easy/models/clear")
async def easy_models_clear(request):
    DL["queue"] = [x for x in DL["queue"] if x["status"] in ("queued", "loading")]
    return web.json_response({"ok": True})


# ---------------------------------------------------------------- Zugangspruefung (HuggingFace)
# Manche Modelle sind auf HuggingFace "gated": Man muss einmalig zustimmen und einen Schluessel (Token) hinterlegen.
# Wir pruefen das vorab, damit der Nutzer die Anleitung sieht, bevor ein Download scheitert.
import hashlib
import re as _re

ACCESS_FILE = os.path.join(DATA, "access_cache.json")
ACCESS_TTL = 24 * 3600
ACCESS = {"busy": False}


def hf_repo(url):
    m = _re.match(r"https://huggingface\.co/([^/]+/[^/]+)/", url or "")
    return m.group(1) if m else None


def token_hash():
    t = load_cfg().get("hf_token") or ""
    return hashlib.sha256(t.encode()).hexdigest()[:12] if t else ""


async def check_repo(session, repo, sample_url):
    """Liefert {gated, manual, ok}. ok = Download ist mit dem aktuellen Schluessel moeglich."""
    token = load_cfg().get("hf_token") or ""
    headers = {"Authorization": "Bearer " + token} if token else {}
    info = {"gated": False, "manual": False, "ok": True, "checked": time.time(), "tok": token_hash()}
    try:
        async with session.get(f"https://huggingface.co/api/models/{repo}", headers=headers) as r:
            if r.status == 200:
                j = await r.json()
                g = j.get("gated", False)
                info["gated"] = bool(g)
                info["manual"] = g == "manual"
            elif r.status in (401, 403, 404):
                info["gated"] = True
        if info["gated"] and sample_url:
            async with session.head(sample_url, headers=headers, allow_redirects=False) as r:
                info["ok"] = r.status in (200, 206, 301, 302, 303, 307, 308)
    except Exception:
        info["error"] = True
        info["ok"] = None   # unbekannt (z. B. offline)
    return info


def access_cache():
    return read_json(ACCESS_FILE, {})


def catalog_repos():
    repos = {}
    for t in catalog():
        for m in template_models(t["name"]):
            r = hf_repo(m["url"])
            if r and r not in repos:
                repos[r] = m["url"]
    return repos


async def refresh_access(repos, force=False):
    cache = access_cache()
    th = token_hash()
    todo = {r: u for r, u in repos.items()
            if force or r not in cache or cache[r].get("tok") != th or time.time() - cache[r].get("checked", 0) > ACCESS_TTL
            or cache[r].get("ok") is None}
    if not todo:
        return cache
    sem = asyncio.Semaphore(6)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
        async def one(r, u):
            async with sem:
                cache[r] = await check_repo(s, r, u)
        await asyncio.gather(*(one(r, u) for r, u in todo.items()))
    write_json(ACCESS_FILE, cache)
    return cache


async def _bg_refresh():
    if ACCESS["busy"]:
        return
    ACCESS["busy"] = True
    try:
        await refresh_access(catalog_repos())
    except Exception:
        pass
    finally:
        ACCESS["busy"] = False


def access_for_template(name, cache, only_missing=False):
    need, manual = [], False
    for m in template_models(name):
        if only_missing and model_present(m):
            continue
        r = hf_repo(m["url"])
        c = cache.get(r) if r else None
        if c and c.get("gated") and c.get("ok") is False and r not in need:
            need.append(r)
            manual = manual or c.get("manual", False)
    return need, manual


@routes.post("/easy/access_check")
async def easy_access_check(request):
    """Prueft (frisch) die Zugaenge fuer die fehlenden Dateien einer Vorlage."""
    data = await request.json()
    name = str(data.get("template", ""))
    repos = {}
    for m in template_models(name):
        if model_present(m):
            continue
        r = hf_repo(m["url"])
        if r and r not in repos:
            repos[r] = m["url"]
    cache = await refresh_access(repos, force=True)
    need, manual = access_for_template(name, cache, only_missing=True)
    unknown = [r for r in repos if cache.get(r, {}).get("ok") is None]
    return web.json_response({"need": need, "manual": manual, "unknown": unknown, "token_set": bool(load_cfg().get("hf_token"))})


# ---------------------------------------------------------------- Prompt-Helfer
SYSTEM_PROMPT = """You are an expert prompt writer for open-source generative models running in ComfyUI.
Target: {target}. Rewrite the user's idea into one strong prompt for this model.
General rules:
- English, one flowing paragraph, concrete and visual, about 60-170 words. No lists, no markdown.
- Keep every element the user asked for. Do not add unrelated people, logos or text overlays.
{rules}
Reply ONLY with JSON: {{"prompt": "<the English prompt>", "de": "<one or two {explain_lang} sentences explaining what you changed>"}}"""

RULES = {
    "video": ("- Present tense. Start with the main action, then describe movements in order, subjects, setting.\n"
              "- Name camera shot and movement (e.g. slow dolly-in, handheld tracking shot).\n"
              "- Describe lighting, colors, mood and style.\n"
              "- If the model makes sound, describe ambience, effects, music; put spoken dialogue in quotes.\n"
              "- One continuous shot that fits the given length, no scene cuts."),
    "image": ("- Describe subject, composition, setting, lighting, colors, lens/camera feel and style.\n"
              "- If text should appear in the image, put the exact text in quotes and say where it goes."),
    "with_image": ("- An input image is given. Do not re-describe everything in it; describe what should change or happen, "
                   "staying consistent with the image."),
}


@routes.get("/easy/ollama_models")
async def easy_ollama_models(request):
    cfg = load_cfg()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
            async with s.get(cfg["ollama_url"].rstrip("/") + "/api/tags") as r:
                j = await r.json()
        return web.json_response({"models": [m["name"] for m in j.get("models", [])]})
    except Exception:
        return web.json_response({"models": [], "error": "Ollama nicht erreichbar"})


def parse_answer(text):
    text = (text or "").strip()
    try:
        start, end = text.find("{"), text.rfind("}")
        j = json.loads(text[start:end + 1])
        if isinstance(j.get("prompt"), str) and j["prompt"].strip():
            return {"prompt": j["prompt"].strip(), "de": str(j.get("de", "")).strip()}
    except Exception:
        pass
    return {"prompt": text.strip("`"), "de": ""}


@routes.post("/easy/assist")
async def easy_assist(request):
    data = await request.json()
    idea = str(data.get("prompt", "")).strip()
    wish = str(data.get("wish", "")).strip()
    kind = "image" if data.get("kind") == "image" else "video"
    seconds = data.get("seconds", 5)
    model_title = str(data.get("model", ""))[:120] or ("a video model" if kind == "video" else "an image model")
    image_b64 = data.get("image")
    if not idea and not wish:
        return web.json_response({"error": "Bitte zuerst eine Idee eintippen."}, status=400)
    cfg = load_cfg()
    rules = RULES[kind] + ("\n" + RULES["with_image"] if image_b64 else "")
    explain_lang = {"en": "English", "ru": "Russian"}.get(data.get("lang"), "German")
    system = SYSTEM_PROMPT.format(target=f"{model_title} ({kind})", rules=rules, explain_lang=explain_lang)
    user = (f"Video length: {seconds} seconds.\n" if kind == "video" else "") + f"User idea (may be German): {idea or '(none)'}"
    if wish:
        user += f"\nChange request from the user (apply it): {wish}"
    try:
        timeout = aiohttp.ClientTimeout(total=120)
        if cfg["provider"] == "claude":
            if not cfg["claude_key"]:
                return web.json_response({"error": "Kein Claude-API-Key hinterlegt (Einstellungen)."}, status=400)
            content = []
            if image_b64 and "," in image_b64:
                head, b64 = image_b64.split(",", 1)
                content.append({"type": "image", "source": {"type": "base64", "media_type": head.split(";")[0].replace("data:", "") or "image/jpeg", "data": b64}})
            content.append({"type": "text", "text": user})
            body = {"model": cfg["claude_model"] or DEFAULT_CFG["claude_model"], "max_tokens": 800,
                    "system": system, "messages": [{"role": "user", "content": content}]}
            headers = {"x-api-key": cfg["claude_key"], "anthropic-version": "2023-06-01", "content-type": "application/json"}
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.post("https://api.anthropic.com/v1/messages", json=body, headers=headers) as r:
                    j = await r.json()
            if "error" in j:
                return web.json_response({"error": "Claude: " + j["error"].get("message", "Fehler")}, status=400)
            text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        else:
            model = cfg["ollama_model"]
            if not model:
                return web.json_response({"error": "Kein Ollama-Modell gewaehlt (Einstellungen)."}, status=400)
            msg = {"role": "user", "content": user}
            if image_b64 and "," in image_b64 and any(x in model.lower() for x in ("vl", "llava", "vision", "gemma3", "gemma4", "minicpm")):
                msg["images"] = [image_b64.split(",", 1)[1]]
            body = {"model": model, "stream": False, "format": "json", "keep_alive": 0, "think": False,
                    "options": {"temperature": 0.7}, "messages": [{"role": "system", "content": system}, msg]}
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.post(cfg["ollama_url"].rstrip("/") + "/api/chat", json=body) as r:
                    j = await r.json()
            if "error" in j:
                return web.json_response({"error": "Ollama: " + str(j["error"])}, status=400)
            text = j.get("message", {}).get("content", "")
        return web.json_response(parse_answer(text))
    except aiohttp.ClientConnectorError:
        return web.json_response({"error": "Keine Verbindung. Laeuft Ollama bzw. bist du online?"}, status=502)
    except Exception as e:
        return web.json_response({"error": "Fehler: " + str(e)}, status=500)


# ---------------------------------------------------------------- System-Anzeige (CPU / RAM / GPU)
import subprocess
import threading

GPU_STAT = {"util": None, "proc": None, "started": False}

# Liest unter Windows die GPU-Auslastung aus den Leistungsindikatoren (wie im Task-Manager):
# pro Grafikkarte die am staerksten ausgelastete Engine-Art (3D, Compute, ...), davon das Maximum.
PS_GPU = r"""
$ErrorActionPreference='SilentlyContinue'
while($true){
  $s=(Get-Counter -Counter '\GPU Engine(*)\Utilization Percentage' -SampleInterval 2).CounterSamples
  $g=@{}
  foreach($c in $s){ if($c.InstanceName -match 'luid_(0x[0-9a-f]+_0x[0-9a-f]+).*engtype_(\w+)'){ $k=$matches[1]+'|'+$matches[2]; $g[$k]=[double]$g[$k]+$c.CookedValue } }
  $m=0; foreach($v in $g.Values){ if($v -gt $m){$m=$v} }
  [Console]::Out.WriteLine([math]::Round([math]::Min(100,$m),1)); [Console]::Out.Flush()
}
"""


def _gpu_reader():
    try:
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        if os.name == "nt":
            p = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_GPU],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, creationflags=flags)
        else:
            p = subprocess.Popen(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits", "-l", "2"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        GPU_STAT["proc"] = p
        for line in p.stdout:
            try:
                GPU_STAT["util"] = float(line.strip().split(",")[0])
            except ValueError:
                pass
    except Exception:
        GPU_STAT["util"] = None


def ensure_gpu_reader():
    if not GPU_STAT["started"]:
        GPU_STAT["started"] = True
        threading.Thread(target=_gpu_reader, daemon=True).start()


PS_SPECS = r"""
$ErrorActionPreference='SilentlyContinue'
$c = Get-CimInstance Win32_Processor | Select-Object -First 1
$m = @(Get-CimInstance Win32_PhysicalMemory)
$o = [ordered]@{
  cpu_name = ($c.Name).Trim(); cores = $c.NumberOfCores; threads = $c.NumberOfLogicalProcessors; mhz = $c.MaxClockSpeed
  ram_type = ($m | Select-Object -First 1).SMBIOSMemoryType; ram_speed = ($m | Measure-Object -Property ConfiguredClockSpeed -Maximum).Maximum
  ram_rated = ($m | Measure-Object -Property Speed -Maximum).Maximum; ram_modules = @($m | ForEach-Object { [int64]$_.Capacity })
}
$o | ConvertTo-Json -Compress
"""
RAM_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 30: "LPDDR4", 34: "DDR5", 35: "LPDDR5"}
_SPECS = None


def hw_specs():
    global _SPECS
    if _SPECS is not None:
        return _SPECS
    s = {}
    try:
        if os.name == "nt":
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_SPECS],
                               capture_output=True, text=True, timeout=20, creationflags=0x08000000)
            j = json.loads(r.stdout.strip() or "{}")
            mods = [m for m in (j.get("ram_modules") or []) if m]
            s = {"cpu_name": j.get("cpu_name") or "", "cores": j.get("cores"), "threads": j.get("threads"),
                 "mhz": j.get("mhz"), "ram_type": RAM_TYPES.get(j.get("ram_type") or 0, ""),
                 "ram_speed": j.get("ram_speed") or j.get("ram_rated"), "ram_modules": mods}
        else:
            import platform
            name = ""
            try:
                with open("/proc/cpuinfo") as f:
                    for line in f:
                        if line.startswith("model name"):
                            name = line.split(":", 1)[1].strip()
                            break
            except Exception:
                pass
            s = {"cpu_name": name or platform.processor(), "cores": None, "threads": os.cpu_count(), "mhz": None,
                 "ram_type": "", "ram_speed": None, "ram_modules": []}
        try:
            import psutil
            s["cores"] = s.get("cores") or psutil.cpu_count(logical=False)
            s["threads"] = s.get("threads") or psutil.cpu_count(logical=True)
        except Exception:
            pass
    except Exception:
        pass
    _SPECS = s
    return s


@routes.get("/easy/specs")
async def easy_specs(request):
    return web.json_response(await asyncio.to_thread(hw_specs))


@routes.get("/easy/sysinfo")
async def easy_sysinfo(request):
    ensure_gpu_reader()
    out = {"cpu": None, "ram_used": None, "ram_total": None, "gpu": GPU_STAT["util"], "vram_used": None, "vram_total": None, "gpu_name": ""}
    try:
        import psutil
        out["cpu"] = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        out["ram_used"], out["ram_total"] = vm.total - vm.available, vm.total
    except Exception:
        pass
    try:
        import comfy.model_management as mm
        dev = mm.get_torch_device()
        total = mm.get_total_memory(dev)
        free = mm.get_free_memory(dev)
        if dev.type != "cpu":
            out["vram_total"], out["vram_used"] = total, max(0, total - free)
            out["gpu_name"] = mm.get_torch_device_name(dev)
    except Exception:
        pass
    return web.json_response(out)


# ---------------------------------------------------------------- Ollama: Modelle laden
OLLAMA_PULL = {"running": False, "model": "", "status": "", "completed": 0, "total": 0, "error": None, "done": False}


async def _ollama_pull(model):
    OLLAMA_PULL.update({"running": True, "model": model, "status": "Starte …", "completed": 0, "total": 0, "error": None, "done": False})
    cfg = load_cfg()
    try:
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=600)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(cfg["ollama_url"].rstrip("/") + "/api/pull", json={"model": model, "stream": True}) as r:
                async for line in r.content:
                    try:
                        j = json.loads(line)
                    except Exception:
                        continue
                    if j.get("error"):
                        raise RuntimeError(j["error"])
                    OLLAMA_PULL["status"] = j.get("status", "")
                    if j.get("total"):
                        OLLAMA_PULL["total"], OLLAMA_PULL["completed"] = j["total"], j.get("completed", 0)
        cfg = load_cfg()
        cfg["provider"], cfg["ollama_model"] = "ollama", model
        write_json(CFG_FILE, cfg)
        OLLAMA_PULL["done"] = True
    except Exception as e:
        OLLAMA_PULL["error"] = "Ollama nicht erreichbar" if isinstance(e, aiohttp.ClientConnectorError) else str(e)
    finally:
        OLLAMA_PULL["running"] = False


@routes.post("/easy/ollama/pull")
async def easy_ollama_pull(request):
    data = await request.json()
    model = str(data.get("model", "")).strip()
    if not model:
        return web.json_response({"error": "Kein Modell angegeben"}, status=400)
    if not OLLAMA_PULL["running"]:
        asyncio.create_task(_ollama_pull(model))
    return web.json_response({"ok": True})


@routes.get("/easy/ollama/pull_status")
async def easy_ollama_pull_status(request):
    return web.json_response(OLLAMA_PULL)


try:
    from . import cloud  # noqa: F401  (registriert die Cloud-Routen)
except Exception as _e:
    print("[Easy Generate] Cloud-Modul nicht geladen:", _e)

print(f"[Easy Generate] Erweiterung {VERSION} bereit unter /easy")

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
