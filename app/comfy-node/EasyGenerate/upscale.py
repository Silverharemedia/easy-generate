"""Easy Generate - Hochskalieren mit SeedVR2 (optional).

Installiert auf Wunsch die SeedVR2-Erweiterung (numz/ComfyUI-SeedVR2_VideoUpscaler) in ComfyUI.
Die Knoten selbst haengt die Oberflaeche nur an, wenn Hochskalieren gewaehlt ist.
Auf der eigenen Cloud-GPU ist sie schon im Docker-Abbild enthalten (siehe remote.py).
Die Modelle laedt SeedVR2 beim ersten Benutzen selbst nach models/SEEDVR2.
"""
import asyncio
import io
import os
import re
import shutil
import sys
import zipfile

import aiohttp
from aiohttp import web

from . import HERE, routes

SEEDVR2_TAG = "v2.5.23"
SEEDVR2_ZIP = f"https://codeload.github.com/numz/ComfyUI-SeedVR2_VideoUpscaler/zip/refs/tags/{SEEDVR2_TAG}"
SEEDVR2_DIR = os.path.join(os.path.dirname(HERE), "seedvr2_videoupscaler")
# torch nie anfassen - sonst koennte pip die passende Version (CUDA/ROCm) ersetzen
SKIP_REQS = ("torch", "torchvision", "torchaudio")

STATE = {"running": False, "status": "", "error": None, "done": False}


def installed():
    cn = os.path.dirname(HERE)
    try:
        names = os.listdir(cn)
    except OSError:
        return False
    return any("seedvr2" in n.lower() and not n.endswith(".disabled") and os.path.isdir(os.path.join(cn, n)) for n in names)


async def _pip(req_file):
    p = await asyncio.create_subprocess_exec(sys.executable, "-s", "-m", "pip", "install", "-r", req_file,
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await p.communicate()
    if p.returncode:
        raise RuntimeError("pip: " + out.decode("utf8", "replace")[-600:])


async def _install():
    STATE.update({"running": True, "status": "Lade SeedVR2 …", "error": None, "done": False})
    tmp = SEEDVR2_DIR + ".new"
    try:
        timeout = aiohttp.ClientTimeout(total=600, sock_connect=20)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(SEEDVR2_ZIP) as r:
                if r.status != 200:
                    raise RuntimeError(f"Download fehlgeschlagen ({r.status})")
                data = await r.read()
        STATE["status"] = "Entpacke …"
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = z.namelist()[0].split("/")[0] + "/"
            for m in z.infolist():
                rel = m.filename[len(root):] if m.filename.startswith(root) else ""
                if not rel or ".." in rel.split("/"):
                    continue
                dst = os.path.join(tmp, *rel.split("/"))
                if m.is_dir():
                    os.makedirs(dst, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with z.open(m) as fi, open(dst, "wb") as fo:
                    shutil.copyfileobj(fi, fo)
        req = os.path.join(tmp, "requirements.txt")
        if os.path.isfile(req):
            STATE["status"] = "Installiere Zusatzpakete …"
            with open(req, encoding="utf8") as fh:
                lines = [ln for ln in fh.read().splitlines()
                         if ln.strip() and not ln.lstrip().startswith("#")
                         and re.split(r"[<>=!~\[; ]", ln.strip())[0].lower() not in SKIP_REQS]
            req2 = os.path.join(tmp, "requirements-easy.txt")
            with open(req2, "w", encoding="utf8") as fh:
                fh.write("\n".join(lines) + "\n")
            await _pip(req2)
        shutil.rmtree(SEEDVR2_DIR, ignore_errors=True)
        os.replace(tmp, SEEDVR2_DIR)
        STATE.update({"status": "Fertig – ComfyUI wird neu gestartet.", "done": True})
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        STATE["error"] = str(e) or e.__class__.__name__
    finally:
        STATE["running"] = False


@routes.get("/easy/upscale/status")
async def upscale_status(request):
    return web.json_response({**STATE, "installed": installed(), "tag": SEEDVR2_TAG})


@routes.post("/easy/upscale/install")
async def upscale_install(request):
    if os.environ.get("EG_CLOUD"):
        return web.json_response({"error": "Auf der Cloud-GPU ist SeedVR2 schon dabei – bitte die Cloud-GPU aktualisieren."}, status=400)
    if not STATE["running"]:
        asyncio.create_task(_install())
    return web.json_response({"ok": True})
