"""Easy Generate - Galerie.

Merkt sich zu jedem Ergebnis, mit welchem Modell es erstellt wurde, und listet die Dateien direkt
aus den Ordnern (bleibt also auch nach einem Neustart erhalten - die ComfyUI-"History" nicht).

Speicher-Arten (Einstellung "gallery_mode"):
  keep  - Ergebnisse behalten. Mit eigenem Ordner (gallery_dir) werden sie dorthin verschoben,
          sortiert in Unterordner pro Modell. Ohne eigenen Ordner bleiben sie im ComfyUI-Ausgabeordner.
  temp  - keine Galerie: Ergebnisse liegen in einem Zwischenordner und werden nach 24 Stunden geloescht.
"""
import asyncio
import os
import re
import shutil
import threading
import time

from aiohttp import web

from . import DATA, load_cfg, read_json, routes, write_json

try:
    import folder_paths
except Exception:
    folder_paths = None

INDEX_FILE = os.path.join(DATA, "gallery.json")
TEMP_DIR = os.path.join(DATA, "temp_results")
MEDIA = (".mp4", ".webm", ".mov", ".mkv", ".gif", ".png", ".jpg", ".jpeg", ".webp")
VIDEO = (".mp4", ".webm", ".mov", ".mkv", ".gif")
TEMP_HOURS = 24
UNKNOWN = "Ohne Zuordnung"


def output_dir():
    return folder_paths.get_output_directory() if folder_paths else os.path.join(DATA, "output")


def settings():
    c = load_cfg()
    mode = c.get("gallery_mode") or ""
    gdir = (c.get("gallery_dir") or "").strip()
    return mode, gdir


def roots():
    """Ordner, aus denen die Galerie liest: Kuerzel -> Pfad."""
    mode, gdir = settings()
    r = {"o": output_dir()}
    if gdir and os.path.isdir(gdir) and os.path.normcase(os.path.abspath(gdir)) != os.path.normcase(os.path.abspath(r["o"])):
        r["g"] = gdir
    if os.path.isdir(TEMP_DIR):
        r["t"] = TEMP_DIR
    return r


def index():
    return read_json(INDEX_FILE, {})


# Ein Schloss fuer alle Aenderungen am Index und fuers Vergeben von Dateinamen:
# mehrere Cloud-GPUs koennen gleichzeitig fertig werden.
LOCK = threading.RLock()


def save_index(ix):
    with LOCK:
        write_json(INDEX_FILE, ix)


def key(path):
    return os.path.normcase(os.path.abspath(path))


def safe_folder(name):
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", name or UNKNOWN).strip(" .")
    return (n or UNKNOWN)[:80]


def unique_path(folder, name):
    base, ext = os.path.splitext(name)
    p = os.path.join(folder, name)
    i = 1
    while os.path.exists(p) or os.path.exists(p + ".part"):
        p = os.path.join(folder, f"{base}_{i}{ext}")
        i += 1
    return p


def reserve_path(folder, name):
    """Freien Dateinamen sicher belegen (legt eine leere Datei an), auch wenn mehrere Downloads gleichzeitig laufen."""
    base, ext = os.path.splitext(name)
    i = 0
    while True:
        p = os.path.join(folder, name if i == 0 else f"{base}_{i}{ext}")
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return p
        except FileExistsError:
            i += 1


def resolve_output(f):
    """{filename, subfolder, type} aus ComfyUI -> absoluter Pfad im Ausgabeordner."""
    base = output_dir()
    if (f.get("type") or "output") == "temp" and folder_paths:
        base = folder_paths.get_temp_directory()
    p = os.path.abspath(os.path.join(base, f.get("subfolder") or "", f.get("filename") or ""))
    if not p.startswith(os.path.abspath(base) + os.sep) or not os.path.isfile(p):
        return None
    return p


def file_ref(path):
    """Pfad -> {r, p} fuer /easy/gallery/file (nur innerhalb der erlaubten Ordner)."""
    ap = os.path.abspath(path)
    for k, root in roots().items():
        rr = os.path.abspath(root)
        if ap.startswith(rr + os.sep):
            return {"r": k, "p": os.path.relpath(ap, rr).replace(os.sep, "/")}
    return None


# Schon einsortierte Auftraege merken: wird ein Ergebnis zweimal angefragt (z. B. Neuladen waehrend des Abholens),
# gibt es dieselben Dateien zurueck statt eines Duplikats.
JOBS_FILE = os.path.join(DATA, "placed_jobs.json")
_JOB_LOCKS = {}


def job_lock(job):
    return _JOB_LOCKS.setdefault(job, asyncio.Lock())


def job_get(job):
    if not job:
        return None
    refs = (read_json(JOBS_FILE, {}) or {}).get(job)
    if refs and all(path_from(r.get("r"), r.get("p")) for r in refs):
        return refs
    return None


def job_put(job, refs):
    if not job or not refs:
        return
    with LOCK:
        d = read_json(JOBS_FILE, {}) or {}
        d[job] = refs
        if len(d) > 300:
            d = dict(list(d.items())[-300:])
        write_json(JOBS_FILE, d)


def place(path, model, kind, prompt="", source="local"):
    """Neues Ergebnis einsortieren (verschieben je nach Einstellung) und im Index vermerken."""
    with LOCK:
        return _place(path, model, kind, prompt, source)


def _place(path, model, kind, prompt, source):
    mode, gdir = settings()
    target = path
    try:
        if mode == "temp":
            os.makedirs(TEMP_DIR, exist_ok=True)
            target = unique_path(TEMP_DIR, os.path.basename(path))
            shutil.move(path, target)
        elif mode == "keep" and gdir:
            folder = os.path.join(gdir, safe_folder(model))
            os.makedirs(folder, exist_ok=True)
            if os.path.normcase(os.path.dirname(os.path.abspath(path))) != os.path.normcase(os.path.abspath(folder)):
                target = unique_path(folder, os.path.basename(path))
                shutil.move(path, target)
    except Exception as e:
        print("[Easy Generate] Galerie: konnte Datei nicht verschieben:", e)
        target = path
    ix = index()
    ix[key(target)] = {"model": model or UNKNOWN, "kind": kind or ("video" if target.lower().endswith(VIDEO) else "image"),
                       "prompt": (prompt or "")[:500], "source": source, "created": time.time()}
    save_index(ix)
    return target


MODEL_KEYS = re.compile(rb'"(?:unet_name|ckpt_name|model_name)"\s*:\s*"([^"]{3,200})"')
_FILE_MAP = {"t": 0, "map": {}}


def model_map():
    """Modelldatei -> Titel des installierten Werkzeugs (aus den gespeicherten Ablaeufen)."""
    if time.time() - _FILE_MAP["t"] < 120:
        return _FILE_MAP["map"]
    from . import WF_DIR, registry
    m = {}
    for name, r in registry().items():
        wf = read_json(os.path.join(WF_DIR, name + ".json"), {})
        title = r.get("title") or name
        for node in wf.values() if isinstance(wf, dict) else []:
            for k in ("unet_name", "ckpt_name", "model_name"):
                v = (node.get("inputs") or {}).get(k) if isinstance(node, dict) else None
                if isinstance(v, str):
                    m.setdefault(os.path.basename(v).lower(), title)
    _FILE_MAP.update(t=time.time(), map=m)
    return m


def guess_model(path):
    """Fuer aeltere Dateien: ComfyUI schreibt den Ablauf in die Datei (PNG-Text / MP4-Metadaten).
    Daraus die verwendete Modelldatei lesen und dem Werkzeug zuordnen."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            head = fh.read(3 * 1024 * 1024)
            tail = b""
            if size > 6 * 1024 * 1024:
                fh.seek(-3 * 1024 * 1024, 2)
                tail = fh.read()
        found = MODEL_KEYS.findall(head + tail)
        if not found:
            found = re.findall(rb'\\"(?:unet_name|ckpt_name|model_name)\\"\s*:\s*\\"([^"\\]{3,200})', head + tail)
        mp = model_map()
        for f in found:
            name = os.path.basename(f.decode("utf-8", "ignore").replace("\\", "/")).lower()
            if name in mp:
                return mp[name]
        for f in found:
            n = os.path.splitext(os.path.basename(f.decode("utf-8", "ignore").replace("\\", "/")))[0]
            if n:
                return n
    except Exception:
        pass
    return None


def item_for(path, ix, root_key):
    st = os.stat(path)
    meta = ix.get(key(path)) or {}
    model = meta.get("model")
    if not model and root_key == "g":
        # Unterordner im Galerie-Ordner = Modellname
        rel = os.path.relpath(path, roots()["g"])
        parts = rel.replace("\\", "/").split("/")
        model = parts[0] if len(parts) > 1 else None
    if not model and os.path.basename(os.path.dirname(path)) == "easy-cloud":
        model = "Cloud"
    if not model and "guess" not in meta:
        g = guess_model(path)
        meta = dict(meta, guess=g or "")
        ix[key(path)] = dict(meta, model=g) if g else meta
        _DIRTY[0] = True
        model = g
    elif not model and meta.get("guess"):
        model = meta["guess"]
    ref = file_ref(path)
    return {"name": os.path.basename(path), "model": model or UNKNOWN,
            "kind": meta.get("kind") or ("video" if path.lower().endswith(VIDEO) else "image"),
            "prompt": meta.get("prompt", ""), "cloud": meta.get("source") == "cloud" or "easy-cloud" in path.replace("\\", "/"),
            "created": meta.get("created") or st.st_mtime, "size": st.st_size, "temp": root_key == "t",
            "r": ref["r"] if ref else None, "p": ref["p"] if ref else None, "path": path, "fav": bool(meta.get("fav"))}


def scan():
    maybe_cleanup()
    ix = index()
    items, seen = [], set()
    for rk, root in roots().items():
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("_tmp", "temp")]
            for f in files:
                if not f.lower().endswith(MEDIA):
                    continue
                p = os.path.join(dirpath, f)
                k = key(p)
                if k in seen:
                    continue
                seen.add(k)
                try:
                    items.append(item_for(p, ix, rk))
                except OSError:
                    pass
    items.sort(key=lambda x: -x["created"])
    # verwaiste Index-Eintraege aufraeumen, neu erkannte Modelle merken
    if _DIRTY[0] or any(k not in seen for k in ix):
        with LOCK:      # neu lesen, damit gerade hinzugekommene Ergebnisse nicht verloren gehen
            cur = index()
            for k in [k for k in cur if k in ix and k not in seen]:
                cur.pop(k, None)
            for k in seen:
                if k in ix:
                    cur[k] = ix[k]
            save_index(cur)
        _DIRTY[0] = False
    return items


def cleanup_temp():
    if not os.path.isdir(TEMP_DIR):
        return
    cut = time.time() - TEMP_HOURS * 3600
    for f in os.listdir(TEMP_DIR):
        p = os.path.join(TEMP_DIR, f)
        try:
            if os.path.isfile(p) and os.path.getmtime(p) < cut:
                os.remove(p)
        except OSError:
            pass


_LAST_CLEAN = [0.0]
_DIRTY = [False]


def maybe_cleanup():
    if time.time() - _LAST_CLEAN[0] > 600:
        _LAST_CLEAN[0] = time.time()
        try:
            cleanup_temp()
        except Exception:
            pass


maybe_cleanup()   # beim Start alte Zwischen-Ergebnisse loeschen


@routes.get("/easy/gallery")
async def gallery_list(request):
    items = await asyncio.to_thread(scan)
    mode, gdir = settings()
    total = sum(i["size"] for i in items)
    for i in items:
        i.pop("path", None)
    return web.json_response({"items": items, "mode": mode, "dir": gdir or output_dir(), "own_dir": bool(gdir),
                              "output_dir": output_dir(), "total": total, "temp_hours": TEMP_HOURS})


def path_from(r, p):
    root = roots().get(r)
    if not root or not p:
        return None
    rr = os.path.abspath(root)
    ap = os.path.abspath(os.path.join(rr, p))
    if not ap.startswith(rr + os.sep) or not os.path.isfile(ap):
        return None
    return ap


@routes.get("/easy/gallery/file")
async def gallery_file(request):
    ap = path_from(request.query.get("r"), request.query.get("p"))
    if not ap or not ap.lower().endswith(MEDIA):
        return web.Response(status=404)
    headers = {"Cache-Control": "no-cache"}
    if request.query.get("dl"):
        headers["Content-Disposition"] = 'attachment; filename="%s"' % os.path.basename(ap).replace('"', "")
    return web.FileResponse(ap, headers=headers)


@routes.post("/easy/gallery/add")
async def gallery_add(request):
    """Nach einer Erstellung: Dateien einsortieren. Antwort enthaelt die neuen Adressen."""
    data = await request.json()
    job = str(data.get("job") or "")
    async with job_lock(job or id(data)):
        done = job_get(job)
        if done:
            return web.json_response({"files": done})
        out = []
        for f in data.get("files") or []:
            p = resolve_output(f) if isinstance(f, dict) else None
            if not p:
                continue
            t = await asyncio.to_thread(place, p, str(data.get("model") or ""), str(data.get("kind") or ""), str(data.get("prompt") or ""),
                                        "cloud" if data.get("cloud") else "local")
            ref = file_ref(t)
            if ref:
                out.append(dict(ref, name=os.path.basename(t)))
        job_put(job, out)
    return web.json_response({"files": out})


@routes.post("/easy/gallery/fav")
async def gallery_fav(request):
    """Favorit (⭐) setzen oder entfernen – steht im Galerie-Index."""
    data = await request.json()
    ap = path_from(data.get("r"), data.get("p"))
    if not ap:
        return web.json_response({"error": "nicht gefunden"}, status=404)
    with LOCK:
        ix = index()
        m = dict(ix.get(key(ap)) or {})
        if not m.get("created"):
            try:
                m["created"] = os.path.getmtime(ap)
            except OSError:
                pass
        m["fav"] = bool(data.get("fav"))
        ix[key(ap)] = m
        save_index(ix)
    return web.json_response({"ok": True, "fav": m["fav"]})


@routes.post("/easy/gallery/delete")
async def gallery_delete(request):
    data = await request.json()
    ap = path_from(data.get("r"), data.get("p"))
    if not ap:
        return web.json_response({"error": "nicht gefunden"}, status=404)
    try:
        os.remove(ap)
    except OSError as e:
        return web.json_response({"error": str(e)}, status=500)
    with LOCK:
        ix = index()
        ix.pop(key(ap), None)
        save_index(ix)
    return web.json_response({"ok": True})


@routes.post("/easy/gallery/path")
async def gallery_path(request):
    """Absoluter Pfad einer Datei (fuer „Im Ordner zeigen“ im Programm)."""
    data = await request.json()
    ap = path_from(data.get("r"), data.get("p"))
    return web.json_response({"path": ap} if ap else {"error": "nicht gefunden"})


@routes.post("/easy/gallery/settings")
async def gallery_settings(request):
    data = await request.json()
    mode = data.get("mode")
    if mode not in ("keep", "temp"):
        return web.json_response({"error": "unbekannt"}, status=400)
    gdir = (data.get("dir") or "").strip()
    if mode == "keep" and gdir:
        try:
            os.makedirs(gdir, exist_ok=True)
            test = os.path.join(gdir, ".eg_test")
            with open(test, "w") as fh:
                fh.write("ok")
            os.remove(test)
        except Exception as e:
            return web.json_response({"error": "Ordner nicht beschreibbar: " + str(e)}, status=400)
    from . import CFG_FILE
    c = load_cfg()
    c["gallery_mode"] = mode
    c["gallery_dir"] = gdir if mode == "keep" else ""
    write_json(CFG_FILE, c)
    return web.json_response({"ok": True})


@routes.post("/easy/gallery/migrate")
async def gallery_migrate(request):
    """Bisherige Ergebnisse aus dem ComfyUI-Ausgabeordner in den Galerie-Ordner verschieben."""
    mode, gdir = settings()
    if mode != "keep" or not gdir:
        return web.json_response({"error": "Kein eigener Galerie-Ordner eingestellt."}, status=400)

    def work():
        with LOCK:
            return _migrate()

    def _migrate():
        ix = index()
        n = 0
        base = output_dir()
        for dirpath, dirs, files in os.walk(base):
            for f in files:
                if not f.lower().endswith(MEDIA):
                    continue
                p = os.path.join(dirpath, f)
                try:
                    if os.path.getsize(p) == 0:      # gerade reserviert, Download laeuft noch
                        continue
                except OSError:
                    continue
                meta = ix.get(key(p)) or {}
                model = meta.get("model") or ("Cloud" if os.path.basename(dirpath) == "easy-cloud" else (guess_model(p) or UNKNOWN))
                folder = os.path.join(gdir, safe_folder(model))
                try:
                    os.makedirs(folder, exist_ok=True)
                    t = unique_path(folder, f)
                    shutil.move(p, t)
                    m = ix.pop(key(p), None) or {"model": model, "created": os.path.getmtime(t)}
                    ix[key(t)] = m
                    n += 1
                except Exception:
                    pass
        save_index(ix)
        return n
    n = await asyncio.to_thread(work)
    return web.json_response({"moved": n})


@routes.get("/easy/gallery/count_output")
async def gallery_count_output(request):
    def work():
        n, size = 0, 0
        for dirpath, dirs, files in os.walk(output_dir()):
            for f in files:
                if f.lower().endswith(MEDIA):
                    n += 1
                    try:
                        size += os.path.getsize(os.path.join(dirpath, f))
                    except OSError:
                        pass
        return n, size
    n, size = await asyncio.to_thread(work)
    return web.json_response({"count": n, "size": size})
