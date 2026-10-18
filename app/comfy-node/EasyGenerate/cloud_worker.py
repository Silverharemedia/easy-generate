"""Easy Generate - Cloud-Helfer (eigener Prozess).

Wird vom ComfyUI-Knoten gestartet. Liest einen JSON-Auftrag von stdin
(inklusive HF-Token, damit er nicht in der Prozessliste steht) und schreibt
Statusmeldungen als JSON-Zeilen nach stdout.

Der Token wird ausschliesslich an HuggingFace geschickt
(huggingface.co, router.huggingface.co, *.hf.space).
"""
import json
import os
import re
import shutil
import sys
import time
import traceback
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
PYLIB = os.path.join(HERE, "data", "pylib")
if os.path.isdir(PYLIB):
    sys.path.insert(0, PYLIB)

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"   # nie still einen anderswo gespeicherten Token benutzen

MEDIA_EXT = (".mp4", ".webm", ".mov", ".mkv", ".gif", ".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXT = (".mp4", ".webm", ".mov", ".mkv")


def emit(**kw):
    sys.stdout.write(json.dumps(kw, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def hf_host(host):
    host = (host or "").lower().split(":")[0]
    return host == "huggingface.co" or host.endswith(".huggingface.co") or host.endswith(".hf.space")


def local_host(host):
    return (host or "").lower().split(":")[0] in ("127.0.0.1", "localhost")


# ------------------------------------------------------------------ Space-Formular
def num_range(desc):
    m = re.search(r"between\s+(-?[\d.]+)\s+and\s+(-?[\d.]+)", desc or "")
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def field_of(p, i):
    t = p.get("type") or {}
    py = p.get("python_type") or {}
    comp = (p.get("component") or "").lower()
    name = p.get("parameter_name") or ""
    label = p.get("label") or name or ("#" + str(i + 1))
    pyt = (py.get("type") or "").lower()
    desc = (t.get("description") or "") + " " + (py.get("description") or "")
    f = {"i": i, "name": name, "label": label, "component": p.get("component") or "",
         "required": not p.get("parameter_has_default", False),
         "default": p.get("parameter_default")}
    kind = "text"
    title = (t.get("title") or "").lower()
    if comp in ("image", "imageeditor", "imageslider", "gallery") or title == "imagedata":
        kind = "image"
    elif comp == "video" or title == "videodata":
        kind = "video"
    elif comp == "audio":
        kind = "audio"
    elif comp in ("file", "uploadbutton") or "filepath" in pyt:
        lname = (name + " " + label).lower()
        kind = "video" if "video" in lname else "audio" if "audio" in lname else "image" if re.search(r"image|img|frame|photo|bild|picture", lname) else "file"
    elif t.get("type") == "boolean" or comp == "checkbox" or pyt == "bool":
        kind = "bool"
    elif t.get("type") in ("number", "integer") or comp in ("slider", "number") or pyt in ("float", "int"):
        kind = "number"
        f["int"] = t.get("type") == "integer" or pyt == "int"
        lo, hi = num_range(desc)
        f["min"], f["max"] = lo, hi
    elif t.get("enum") or comp in ("dropdown", "radio"):
        kind = "choice"
    if t.get("enum"):
        f["choices"] = [str(x) for x in t["enum"]]
        if kind == "text":
            kind = "choice"
    m = re.search(r"options?:\s*([\w\-., ]+)", desc)
    if kind == "text" and m:
        ch = [x.strip() for x in m.group(1).split(",") if x.strip()]
        if 1 < len(ch) <= 30:
            f["choices"], kind = ch, "choice"
    lname = (name + " " + label).lower()
    if kind == "text" and re.search(r"filepath|file_path|_path\b", name.lower()):
        kind = "skip"          # versteckte Datei-Pfade anderer Funktionen
    f["kind"] = kind
    role = ""
    if kind == "text":
        if re.search(r"neg", lname):
            role = "negative"
        elif re.search(r"prompt|text|describ|caption", lname):
            role = "prompt"
    elif kind == "number":
        if re.search(r"seed", lname):
            role = "seed"
        elif re.search(r"duration|seconds|length|sekunden|dauer", lname):
            role = "duration"
        elif re.search(r"\bwidth|_w\b|width_", lname):
            role = "width"
        elif re.search(r"height|_h\b", lname):
            role = "height"
    elif kind == "bool" and re.search(r"random", lname):
        role = "randomize"
    elif kind in ("image", "video", "audio"):
        role = kind
    f["role"] = role
    return f


def summarize_api(info):
    eps = []
    named = (info or {}).get("named_endpoints") or {}
    for api_name, ep in named.items():
        params = ep.get("parameters") or []
        rets = ep.get("returns") or []
        fields = [field_of(p, i) for i, p in enumerate(params)]
        out = set()
        for r in rets:
            c = (r.get("component") or "").lower()
            tt = ((r.get("type") or {}).get("title") or "").lower()
            if c == "video" or tt == "videodata":
                out.add("video")
            elif c in ("image", "gallery") or tt == "imagedata":
                out.add("image")
            elif c in ("api", "file", "json"):
                out.add("any")
        score = len(fields)
        if "video" in out or "image" in out:
            score += 20
        elif "any" in out:
            score += 8
        if re.search(r"generat|infer|run|predict|text_to|image_to|t2v|i2v|create|process", api_name, re.I):
            score += 6
        if re.search(r"^/(update|handle|on_|change|load|refresh|reset|clear|toggle|get_|set_|show|hide|random|example|upload|_)", api_name, re.I):
            score -= 25
        if not any(f["role"] == "prompt" for f in fields) and not any(f["kind"] in ("image", "video") for f in fields):
            score -= 10
        eps.append({"api": api_name, "fields": fields, "out": sorted(out), "score": score})
    eps.sort(key=lambda e: -e["score"])
    return eps


# ------------------------------------------------------------------ Ergebnisse
def collect_files(obj, acc):
    if obj is None:
        return
    if isinstance(obj, str):
        if os.path.isfile(obj):
            acc.append(obj)
        return
    if isinstance(obj, dict):
        for k in ("video", "path", "name", "image", "value"):
            if k in obj:
                collect_files(obj[k], acc)
        return
    if isinstance(obj, (list, tuple)):
        for x in obj:
            collect_files(x, acc)


def save_outputs(paths, outdir, prefix):
    os.makedirs(outdir, exist_ok=True)
    saved = []
    seen = set()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for i, p in enumerate(paths):
        ext = os.path.splitext(p)[1].lower()
        if ext not in MEDIA_EXT or p in seen:
            continue
        seen.add(p)
        name = f"{prefix}_{stamp}_{len(saved) + 1}{ext}"
        dst = os.path.join(outdir, name)
        shutil.copyfile(p, dst)
        saved.append(name)
    # Videos zuerst
    saved.sort(key=lambda n: 0 if n.lower().endswith(VIDEO_EXT) else 1)
    return saved


def friendly(err):
    s = str(err)
    low = s.lower()
    if "quota" in low and ("gpu" in low or "zerogpu" in low):
        m = re.search(r"(\d+)\s*s\s*left", s)
        return ("ZEROGPU_QUOTA|" + (m.group(1) if m else "")) + "|" + s
    if "401" in s or "unauthorized" in low or "invalid credentials" in low or "invalid token" in low:
        return "AUTH|" + s
    if "402" in s or "payment required" in low or "insufficient" in low or "credits" in low and "exceed" in low:
        return "PAYMENT|" + s
    if "403" in s or "forbidden" in low:
        return "FORBIDDEN|" + s
    if "429" in s or "too many requests" in low or "rate limit" in low:
        return "RATE|" + s
    if "queue is full" in low or "queue_full" in low:
        return "QUEUE_FULL|" + s
    if "sleeping" in low or "paused" in low or "runtime_error" in low or "invalid state" in low:
        return "SPACE_DOWN|" + s
    return s


# ------------------------------------------------------------------ Aufträge
def space_client(job):
    from gradio_client import Client
    import huggingface_hub
    src = job["space"].strip()
    token = job.get("token") or None
    if src.startswith("http://") or src.startswith("https://"):
        host = urlparse(src).hostname
        if not hf_host(host):
            token = None                     # fremde Adresse: Token bleibt hier
            if not local_host(host):
                raise ValueError("Nur HuggingFace-Spaces werden unterstuetzt.")
        return Client(src, token=token, verbose=False, download_files=job["tmp"], analytics_enabled=False)
    if not re.match(r"^[\w.\-]+/[\w.\-]+$", src):
        raise ValueError("Ungueltige Space-Adresse: " + src)
    if token:
        info = huggingface_hub.space_info(src, token=token)
        host = urlparse(info.host or "").hostname if getattr(info, "host", None) else None
        if host and not hf_host(host):
            token = None
            return Client(info.host, token=None, verbose=False, download_files=job["tmp"], analytics_enabled=False)
    return Client(src, token=token, verbose=False, download_files=job["tmp"], analytics_enabled=False)


def op_info(job):
    c = space_client(job)
    info = c.view_api(print_info=False, return_format="dict")
    emit(type="result", endpoints=summarize_api(info))
    c.close()


def op_space(job):
    from gradio_client import handle_file
    emit(type="status", stage="connect")
    c = space_client(job)
    info = c.view_api(print_info=False, return_format="dict")
    eps = {e["api"]: e for e in summarize_api(info)}
    ep = eps.get(job["api"])
    if not ep:
        raise ValueError("Funktion nicht gefunden: " + str(job["api"]))
    values = job.get("values") or {}
    args = []
    for f in ep["fields"]:
        key = str(f["i"])
        v = values.get(key, None)
        if v is None or v == "":
            if f["kind"] in ("image", "video", "audio", "file", "skip"):
                v = f["default"] if f["kind"] == "skip" else None
            elif f["required"] and f["default"] is None:
                if f["kind"] == "text":
                    v = ""
                else:
                    raise ValueError("Pflichtfeld fehlt: " + f["label"])
            else:
                v = f["default"]
        if f["kind"] in ("image", "video", "audio", "file") and isinstance(v, str) and v:
            fp = v
            v = handle_file(fp)
            if f["kind"] == "video" and (f.get("component") or "").lower() == "video":
                v = {"video": v}
        elif f["kind"] == "number" and v is not None and not isinstance(v, bool):
            try:
                v = int(float(v)) if f.get("int") else float(v)
            except (TypeError, ValueError):
                pass
        elif f["kind"] == "bool":
            v = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "yes", "on")
        args.append(v)
    learned = {}
    res = None
    busy_tries = 0
    for attempt in range(8):
        emit(type="status", stage="submit")
        j = c.submit(*args, api_name=job["api"])
        watch_job(j)
        try:
            res = j.result()
            break
        except Exception as e:
            busy = re.search(r"at capacity|gpu limit|could not allocate|too many|concurrent|try again|retry", str(e), re.I) and \
                not re.search(r"exceeded your (free )?gpu quota|quota exceeded", str(e), re.I)
            if busy and busy_tries < 3:            # geteilte GPU kurz ausgelastet -> automatisch nochmal
                busy_tries += 1
                wait = 20 * busy_tries
                emit(type="status", stage="run", code="BUSY_RETRY", attempt=busy_tries, wait=wait)
                time.sleep(wait)
                continue
            fix = choice_fix(str(e), ep["fields"], args)
            if not fix or attempt == 7:
                raise
            i, choices, pick = fix                 # Space kennt nur bestimmte Werte -> merken und gueltigen nehmen
            learned[str(i)] = choices
            args[i] = pick
            emit(type="status", stage="run", code="RETRY_CHOICE", field=i, choices=choices)
    res = j.result()
    paths = []
    collect_files(res, paths)
    saved = save_outputs(paths, job["outdir"], "cloud")
    if not saved:
        raise ValueError("NO_OUTPUT|Der Space hat keine Datei zurueckgegeben: " + str(res)[:300])
    emit(type="result", files=saved, learned=learned)
    c.close()


def watch_job(j):
    last = None
    while not j.done():
        try:
            st = j.status()
            code = str(getattr(st.code, "value", st.code))
            prog = None
            pd = st.progress_data
            if pd:
                p = pd[-1]
                prog = {"index": getattr(p, "index", None), "length": getattr(p, "length", None),
                        "unit": getattr(p, "unit", None), "progress": getattr(p, "progress", None),
                        "desc": getattr(p, "desc", None)}
            cur = (code, st.rank, st.queue_size, round(st.eta or 0), json.dumps(prog))
            if cur != last:
                last = cur
                emit(type="status", stage="queue" if code in ("IN_QUEUE", "JOINING_QUEUE", "STARTING") else "run",
                     code=code, rank=st.rank, size=st.queue_size, eta=st.eta, progress=prog)
        except Exception:
            pass
        time.sleep(0.7)


CHOICE_RX = re.compile(r"Value:\s*(.*?)\s*is not in the list of choices:\s*(\[.*\])", re.S)


def choice_fix(msg, fields, args):
    """Gradio meldet „Value: X is not in the list of choices: [...]“ -> Feld finden, Auswahl merken, ersten Wert nehmen."""
    m = CHOICE_RX.search(msg)
    if not m:
        return None
    import ast
    try:
        choices = [str(x) for x in ast.literal_eval(m.group(2))]
    except Exception:
        return None
    if not choices:
        return None
    bad = m.group(1).strip()
    cand = [f for f in fields if f["kind"] in ("text", "choice") and str(args[f["i"]] if args[f["i"]] is not None else "").strip() == bad]
    if not cand:
        return None
    f = cand[0]
    return f["i"], choices, choices[0]

    from huggingface_hub import InferenceClient
    token = job.get("token")
    if not token:
        raise ValueError("AUTH|Kein HuggingFace-Token gespeichert.")
    task = job["task"]
    model = job["model"]
    provider = job.get("provider") or "auto"
    client = InferenceClient(provider=provider, api_key=token, timeout=1800)
    prompt = job.get("prompt") or ""
    neg = job.get("negative") or None
    seed = job.get("seed")
    extra = dict(job.get("extra") or {})
    emit(type="status", stage="run", code="PROCESSING")

    def call(use_extra):
        kw = {"model": model}
        if seed is not None:
            kw["seed"] = int(seed)
        if task == "text-to-video":
            if neg:
                kw["negative_prompt"] = [neg]
            if use_extra and extra:
                kw["extra_body"] = extra
            return client.text_to_video(prompt, **kw)
        if task == "image-to-video":
            with open(job["image"], "rb") as fh:
                img = fh.read()
            if neg:
                kw["negative_prompt"] = neg
            if use_extra and extra:
                kw.update(extra)
            return client.image_to_video(img, prompt=prompt or None, **kw)
        if task == "text-to-image":
            if neg:
                kw["negative_prompt"] = neg
            if use_extra:
                for k in ("width", "height"):
                    if extra.get(k):
                        kw[k] = int(extra[k])
                rest = {k: v for k, v in extra.items() if k not in ("width", "height")}
                if rest:
                    kw["extra_body"] = rest
            return client.text_to_image(prompt, **kw)
        if task == "image-to-image":
            with open(job["image"], "rb") as fh:
                img = fh.read()
            return client.image_to_image(img, prompt=prompt or None, **kw)
        raise ValueError("Unbekannte Aufgabe: " + task)

    try:
        out = call(True)
    except Exception as e:  # andere Anbieter verstehen nicht alle Zusatzwerte -> ohne nochmal
        msg = str(e)
        if extra and re.search(r"\b(400|422)\b|unprocessable|validation|unexpected|invalid", msg, re.I):
            emit(type="status", stage="run", code="RETRY")
            out = call(False)
        else:
            raise
    os.makedirs(job["outdir"], exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if isinstance(out, (bytes, bytearray)):
        ext = ".mp4" if "video" in task else ".png"
        if "video" in task and out[:4] == b"\x1aE\xdf\xa3":
            ext = ".webm"
        name = f"cloud_{stamp}_{os.urandom(2).hex()}{ext}"
        with open(os.path.join(job["outdir"], name), "wb") as fh:
            fh.write(out)
    else:  # PIL-Bild
        name = f"cloud_{stamp}_{os.urandom(2).hex()}.png"
        out.save(os.path.join(job["outdir"], name))
    emit(type="result", files=[name])


def main():
    job = json.loads(sys.stdin.readline() or "{}")
    try:
        op = job.get("op")
        if op == "info":
            op_info(job)
        elif op == "space":
            op_space(job)
        elif op == "provider":
            op_provider(job)
        elif op == "check":
            import gradio_client, huggingface_hub  # noqa
            emit(type="result", gradio=gradio_client.__version__, hub=huggingface_hub.__version__)
        else:
            raise ValueError("Unbekannter Auftrag")
    except Exception as e:
        tb = traceback.format_exc()
        token = job.get("token")
        msg = friendly(e)
        if token:
            msg = msg.replace(token, "hf_***")
            tb = tb.replace(token, "hf_***")
        emit(type="error", error=msg, trace=tb[-1500:])
    sys.stdout.flush()
    os._exit(0)  # Hintergrund-Threads von gradio_client nicht abwarten


if __name__ == "__main__":
    main()
