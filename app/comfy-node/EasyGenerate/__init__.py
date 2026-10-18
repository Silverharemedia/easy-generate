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

VERSION = "1.0.0"
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


@routes.get("/easy/version")
async def easy_version(request):
    return web.json_response({"version": VERSION})


# ---------------------------------------------------------------- Einstellungen
DEFAULT_CFG = {"provider": "ollama", "claude_key": "", "claude_model": "claude-haiku-5-5",
               "ollama_url": "http://127.0.0.1:11434", "ollama_model": "", "hf_token": "",
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
    for k in ("claude_key", "hf_token"):
        if isinstance(data.get(k), str) and data[k].strip():
            cfg[k] = data[k].strip()
        if data.get(k + "_clear"):
            cfg[k] = ""
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
    for t in catalog():
        ms = template_models(t["name"])
        have = sum(1 for m in ms if model_present(m))
        r = reg.get(t["name"], {})
        items.append(dict(t, model_count=len(ms), model_have=have,
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
        "items": [{k: x.get(k) for k in ("name", "got", "size", "status", "template", "error")} for x in q],
    })


@routes.post("/easy/models/cancel")
async def easy_models_cancel(request):
    DL["cancel"] = True
    return web.json_response({"ok": True})


@routes.post("/easy/models/clear")
async def easy_models_clear(request):
    DL["queue"] = [x for x in DL["queue"] if x["status"] in ("queued", "loading")]
    return web.json_response({"ok": True})


# ---------------------------------------------------------------- Prompt-Helfer
SYSTEM_PROMPT = """You are an expert prompt writer for open-source generative models running in ComfyUI.
Target: {target}. Rewrite the user's idea into one strong prompt for this model.
General rules:
- English, one flowing paragraph, concrete and visual, about 60-170 words. No lists, no markdown.
- Keep every element the user asked for. Do not add unrelated people, logos or text overlays.
{rules}
Reply ONLY with JSON: {{"prompt": "<the English prompt>", "de": "<one or two German sentences explaining what you changed>"}}"""

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
    system = SYSTEM_PROMPT.format(target=f"{model_title} ({kind})", rules=rules)
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
            body = {"model": model, "stream": False, "format": "json", "keep_alive": 0,
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


print(f"[Easy Generate] Erweiterung {VERSION} bereit unter /easy")

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
