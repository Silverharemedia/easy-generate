// Easy Generate – Hauptprozess
// Kümmert sich um: ComfyUI finden/installieren/starten, die Easy-Generate-Erweiterung einspielen,
// das Programmfenster, die Schließen-Abfrage und Updates.
"use strict";
const { app, BrowserWindow, ipcMain, dialog, shell, session } = require("electron");
const path = require("path");
const fs = require("fs");
const os = require("os");
const http = require("http");
const https = require("https");
const { spawn, execFile } = require("child_process");

const IS_WIN = process.platform === "win32";
const APP_ICON = path.join(__dirname, "build", "icon.ico");
const CFG_FILE = () => path.join(app.getPath("userData"), "config.json");
const LOG_FILE = () => path.join(app.getPath("userData"), "comfyui.log");
const NODE_SRC = () => app.isPackaged ? path.join(process.resourcesPath, "comfy-node", "EasyGenerate") : path.join(__dirname, "comfy-node", "EasyGenerate");
const NODE_VERSION = (() => { try { return (fs.readFileSync(path.join(NODE_SRC(), "__init__.py"), "utf8").match(/VERSION = "([^"]+)"/) || [])[1] || "0"; } catch (e) { return "0"; } })();
const PACKAGES = {
  amd: { label: "AMD (ROCm)", file: "ComfyUI_windows_portable_amd.7z" },
  nvidia: { label: "NVIDIA (CUDA)", file: "ComfyUI_windows_portable_nvidia.7z" },
  intel: { label: "Intel Arc", file: "ComfyUI_windows_portable_intel.7z" },
};
const RELEASE_BASE = "https://github.com/comfyanonymous/ComfyUI/releases/latest/download/";

let win = null, cfg = null, quitting = false, comfyChild = null, updateReady = false;

// ------------------------------------------------------------------ Konfiguration
function loadCfg() {
  try { cfg = JSON.parse(fs.readFileSync(CFG_FILE(), "utf8")); } catch (e) { cfg = {}; }
  cfg.closeMode = cfg.closeMode || "ask";
  return cfg;
}
function saveCfg() { fs.mkdirSync(path.dirname(CFG_FILE()), { recursive: true }); fs.writeFileSync(CFG_FILE(), JSON.stringify(cfg, null, 1)); }

// ------------------------------------------------------------------ Hilfen
const exists = p => { try { return !!p && fs.existsSync(p); } catch (e) { return false; } };
const sleep = ms => new Promise(r => setTimeout(r, ms));
function send(ch, data) { if (win && !win.isDestroyed()) win.webContents.send(ch, data); }
function status(text, extra) { send("setup:status", Object.assign({ text }, extra || {})); }

function getJSON(url, timeout = 2500) {
  return new Promise(resolve => {
    const req = http.get(url, { timeout }, res => {
      let d = ""; res.on("data", c => d += c);
      res.on("end", () => { try { resolve(res.statusCode < 400 ? JSON.parse(d) : null); } catch (e) { resolve(null); } });
    });
    req.on("error", () => resolve(null)); req.on("timeout", () => { req.destroy(); resolve(null); });
  });
}
function run(cmd, args, opts) {
  return new Promise(resolve => execFile(cmd, args, Object.assign({ windowsHide: true, maxBuffer: 1 << 24 }, opts || {}), (err, out, errOut) => resolve({ err, out: String(out || ""), errOut: String(errOut || "") })));
}

// Läuft auf einem Port ein ComfyUI? Liefert system_stats oder null.
const comfyAt = port => getJSON(`http://127.0.0.1:${port}/system_stats`);

async function pidOnPort(port) {
  if (!IS_WIN) return null;
  const r = await run("netstat", ["-ano", "-p", "TCP"]);
  for (const line of r.out.split(/\r?\n/)) {
    const m = line.trim().split(/\s+/);
    if (m.length >= 5 && /LISTEN/i.test(m[3]) && m[1].endsWith(":" + port)) return parseInt(m[4], 10);
  }
  return null;
}
async function killComfy() {
  const port = cfg.comfy && cfg.comfy.port;
  const pids = new Set();
  if (comfyChild && comfyChild.pid) pids.add(comfyChild.pid);
  if (cfg.comfyPid) pids.add(cfg.comfyPid);
  if (port) { const p = await pidOnPort(port); if (p) pids.add(p); }
  for (const pid of pids) {
    if (!pid || pid < 5) continue;
    if (IS_WIN) await run("taskkill", ["/PID", String(pid), "/T", "/F"]);
    else { try { process.kill(pid); } catch (e) {} }
  }
  comfyChild = null; cfg.comfyPid = null; saveCfg();
  for (let i = 0; i < 20 && port && await comfyAt(port); i++) await sleep(500);
}

// ------------------------------------------------------------------ ComfyUI finden
function pythonFor(comfyDir) {
  const parent = path.dirname(comfyDir);
  const c = [
    path.join(parent, "python_embeded", "python.exe"), path.join(comfyDir, ".venv", "Scripts", "python.exe"),
    path.join(comfyDir, "venv", "Scripts", "python.exe"), path.join(parent, ".venv", "Scripts", "python.exe"),
    path.join(parent, "venv", "Scripts", "python.exe"), path.join(parent, "python", "python.exe"),
    path.join(parent, "env", "python.exe"), path.join(comfyDir, "python_embeded", "python.exe"),
  ];
  return c.find(exists) || null;
}
function isComfyDir(d) { return exists(path.join(d, "main.py")) && exists(path.join(d, "custom_nodes")) && exists(path.join(d, "comfy")); }

function findComfyDirs(root, depth) {
  const out = [];
  const walk = (d, lvl) => {
    if (lvl > depth || /node_modules|\$Recycle|Windows$|site-packages/i.test(d)) return;
    let ents; try { ents = fs.readdirSync(d, { withFileTypes: true }); } catch (e) { return; }
    if (isComfyDir(d)) { out.push(d); return; }
    for (const e of ents) if (e.isDirectory() && !e.name.startsWith(".")) walk(path.join(d, e.name), lvl + 1);
  };
  walk(root, 0);
  return out;
}

async function detectInstalls() {
  const home = os.homedir(), la = process.env.LOCALAPPDATA || path.join(home, "AppData", "Local");
  const roots = [
    [path.join(la, "AMD", "AI_Bundle"), 3], [path.join(home, "Documents"), 2], [path.join(home, "Desktop"), 2],
    [path.join(home, "Downloads"), 2], [home, 2], ["C:\\", 2], ["D:\\", 2], ["E:\\", 2],
  ];
  const seen = new Set(), found = [];
  for (const [r, d] of roots) {
    if (!exists(r)) continue;
    for (const dir of findComfyDirs(r, d)) {
      const key = dir.toLowerCase(); if (seen.has(key)) continue; seen.add(key);
      const py = pythonFor(dir);
      found.push({ comfyDir: dir, python: py, label: /AI_Bundle/i.test(dir) ? "AMD AI Bundle" : exists(path.join(path.dirname(dir), "python_embeded")) ? "ComfyUI Portable" : "ComfyUI", usable: !!py });
    }
  }
  // Läuft schon irgendwo ein ComfyUI?
  const running = await comfyAt(8188);
  return { found, running: !!running };
}

async function detectGPU() {
  if (!IS_WIN) return { names: [], pick: "nvidia" };
  const r = await run("powershell", ["-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"]);
  const names = r.out.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  let pick = null;
  if (names.some(n => /NVIDIA|GeForce|RTX|Quadro/i.test(n))) pick = "nvidia";
  else if (names.some(n => /Radeon.*(RX|PRO|AI)|Radeon\s+\d/i.test(n))) pick = "amd";
  else if (names.some(n => /Intel.*Arc/i.test(n))) pick = "intel";
  else if (names.some(n => /AMD|Radeon/i.test(n))) pick = "amd";
  return { names, pick };
}

// ------------------------------------------------------------------ Download + Entpacken
function download(url, dest, onProgress, redirects = 0) {
  return new Promise((resolve, reject) => {
    const part = dest + ".part";
    const have = exists(part) ? fs.statSync(part).size : 0;
    const req = https.get(url, { headers: Object.assign({ "User-Agent": "EasyGenerate" }, have ? { Range: `bytes=${have}-` } : {}) }, res => {
      if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location) {
        res.resume();
        if (redirects > 8) return reject(new Error("Zu viele Weiterleitungen"));
        return resolve(download(new URL(res.headers.location, url).toString(), dest, onProgress, redirects + 1));
      }
      if (res.statusCode === 416 && have) { res.resume(); fs.renameSync(part, dest); return resolve(); }
      if (![200, 206].includes(res.statusCode)) { res.resume(); return reject(new Error("Download-Fehler " + res.statusCode)); }
      const start = res.statusCode === 206 ? have : 0;
      const total = parseInt(res.headers["content-length"] || "0", 10) + start;
      const out = fs.createWriteStream(part, { flags: start ? "a" : "w" });
      let got = start, last = Date.now(), lastGot = got, speed = 0;
      res.on("data", c => {
        got += c.length;
        const now = Date.now();
        if (now - last > 800) { speed = (got - lastGot) / ((now - last) / 1000); last = now; lastGot = got; onProgress && onProgress(got, total, speed); }
      });
      res.pipe(out);
      out.on("finish", () => { if (total && got < total) return reject(new Error("Download unterbrochen – bitte erneut versuchen (wird fortgesetzt)")); fs.renameSync(part, dest); resolve(); });
      res.on("error", reject); out.on("error", reject);
    });
    req.on("error", reject);
  });
}
function sevenZip() {
  const p = require("7zip-bin").path7za;
  return p.replace("app.asar", "app.asar.unpacked");
}
function extract(archive, destDir, onProgress) {
  return new Promise((resolve, reject) => {
    const p = spawn(sevenZip(), ["x", archive, "-o" + destDir, "-y", "-bsp1", "-bso0"], { windowsHide: true });
    let buf = "";
    p.stdout.on("data", d => { buf += d.toString(); const m = buf.match(/(\d+)%/g); if (m) { onProgress(parseInt(m[m.length - 1], 10)); buf = ""; } });
    p.on("error", reject);
    p.on("close", code => code === 0 ? resolve() : reject(new Error("Entpacken fehlgeschlagen (Code " + code + ")")));
  });
}

async function installComfy({ gpu, folder, shareFrom }) {
  const pkg = PACKAGES[gpu] || PACKAGES.nvidia;
  fs.mkdirSync(folder, { recursive: true });
  const archive = path.join(folder, pkg.file);
  status(`Lade ComfyUI für ${pkg.label} herunter …`, { phase: "download", pct: 0 });
  await download(RELEASE_BASE + pkg.file, archive, (got, total, speed) => {
    const pct = total ? got / total * 100 : 0;
    const left = speed > 0 && total ? (total - got) / speed : 0;
    status(`Lade ComfyUI für ${pkg.label} herunter …`, { phase: "download", pct, detail: `${(got / 1073741824).toFixed(2)} / ${(total / 1073741824).toFixed(2)} GB · ${(speed / 1048576).toFixed(1)} MB/s${left ? " · noch ca. " + Math.ceil(left / 60) + " Min." : ""}` });
  });
  status("Entpacke ComfyUI … (das dauert ein paar Minuten)", { phase: "extract", pct: 0 });
  await extract(archive, folder, pct => status("Entpacke ComfyUI … (das dauert ein paar Minuten)", { phase: "extract", pct }));
  try { fs.unlinkSync(archive); } catch (e) {}
  const root = path.join(folder, "ComfyUI_windows_portable");
  const comfyDir = path.join(root, "ComfyUI");
  if (!isComfyDir(comfyDir)) throw new Error("Nach dem Entpacken wurde ComfyUI nicht gefunden.");
  if (shareFrom) writeSharedModels(comfyDir, shareFrom);
  cfg.comfy = { comfyDir, python: path.join(root, "python_embeded", "python.exe"), managed: true, portable: root, port: cfg.comfy && cfg.comfy.port || 8188, gpu };
  saveCfg();
}

function writeSharedModels(comfyDir, otherComfyDir) {
  const folders = ["checkpoints", "diffusion_models", "unet", "text_encoders", "clip", "clip_vision", "vae", "loras", "controlnet",
    "upscale_models", "latent_upscale_models", "embeddings", "audio_encoders", "model_patches", "style_models", "diffusers", "vae_approx"];
  const lines = ["# Von Easy Generate angelegt: Modelle aus einer anderen ComfyUI-Installation mitbenutzen", "easy_generate_shared:",
    `  base_path: ${JSON.stringify(otherComfyDir.replace(/\\/g, "/"))}`];
  for (const f of folders) lines.push(`  ${f}: models/${f}/`);
  fs.writeFileSync(path.join(comfyDir, "extra_model_paths.yaml"), lines.join("\n") + "\n");
}

// ------------------------------------------------------------------ Erweiterung einspielen
function copyDir(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const e of fs.readdirSync(src, { withFileTypes: true })) {
    if (e.name === "data" || e.name === "__pycache__") continue;      // Nutzerdaten nie überschreiben
    const s = path.join(src, e.name), d = path.join(dst, e.name);
    if (e.isDirectory()) copyDir(s, d); else fs.copyFileSync(s, d);
  }
}
function installNode(comfyDir) {
  const cn = path.join(comfyDir, "custom_nodes");
  copyDir(NODE_SRC(), path.join(cn, "EasyGenerate"));
  const old = path.join(cn, "EinfachVideo");          // Vorgänger deaktivieren
  if (exists(old) && !exists(old + ".disabled")) { try { fs.renameSync(old, old + ".disabled"); } catch (e) {} }
}

// ------------------------------------------------------------------ ComfyUI starten
async function freePort(start) {
  for (let p = start; p < start + 20; p++) {
    if (await comfyAt(p)) continue;
    if (IS_WIN && await pidOnPort(p)) continue;
    return p;
  }
  return start;
}
function tailLog(n = 4000) { try { const s = fs.readFileSync(LOG_FILE(), "utf8"); return s.slice(-n); } catch (e) { return ""; } }

async function startComfy() {
  const c = cfg.comfy;
  if (!c || !c.comfyDir || !exists(c.comfyDir)) throw new Error("ComfyUI-Ordner nicht gefunden.");
  installNode(c.comfyDir);
  // Läuft schon? Dann prüfen, ob es "unseres" ist und die Erweiterung aktuell ist.
  const st = await comfyAt(c.port || 8188);
  if (st) {
    const v = await getJSON(`http://127.0.0.1:${c.port || 8188}/easy/version`);
    if (v && v.version === NODE_VERSION) return;
    status("Starte ComfyUI neu, um Easy Generate zu aktualisieren …", { phase: "start" });
    await killComfy();
  }
  if (!c.python || !exists(c.python)) {
    c.python = pythonFor(c.comfyDir);
    if (!c.python) throw new Error("Zu diesem ComfyUI wurde kein Python gefunden. Wähle unter „Anderes ComfyUI“ eine andere Installation oder installiere ComfyUI neu.");
  }
  c.port = await freePort(c.port || 8188); saveCfg();
  const log = fs.openSync(LOG_FILE(), "w");
  const args = ["-s", path.join(c.comfyDir, "main.py"), "--windows-standalone-build", "--disable-auto-launch", "--listen", "127.0.0.1", "--port", String(c.port)]
    .concat(Array.isArray(c.extraArgs) ? c.extraArgs : []);
  comfyChild = spawn(c.python, args, { cwd: path.dirname(c.comfyDir), windowsHide: true, detached: true, stdio: ["ignore", log, log], env: Object.assign({}, process.env, { PYTHONIOENCODING: "utf-8" }) });
  comfyChild.unref();
  cfg.comfyPid = comfyChild.pid; saveCfg();
  let exited = null;
  comfyChild.on("exit", code => { exited = code; });
  const t0 = Date.now();
  while (Date.now() - t0 < 15 * 60 * 1000) {
    if (await comfyAt(c.port)) return;
    if (exited !== null || (comfyChild && comfyChild.exitCode !== null)) throw new Error("ComfyUI hat sich beim Start beendet.\n\n" + tailLog(1500));
    const last = tailLog(300).split(/\r?\n/).filter(Boolean).pop() || "";
    status("Starte die KI im Hintergrund …", { phase: "start", detail: `${Math.round((Date.now() - t0) / 1000)} s · ${last.slice(0, 120)}` });
    await sleep(1000);
  }
  throw new Error("ComfyUI startet nicht (Zeitüberschreitung).\n\n" + tailLog(1500));
}

async function launch() {
  try {
    status("Starte die KI im Hintergrund …", { phase: "start" });
    await startComfy();
    await win.loadURL(`http://127.0.0.1:${cfg.comfy.port}/easy`);
  } catch (e) {
    await win.loadFile(path.join(__dirname, "setup.html"));
    send("setup:error", { message: String(e.message || e) });
  }
}

// ------------------------------------------------------------------ Updates (Easy Generate selbst)
let updater = null;
function initUpdater() {
  if (!app.isPackaged) return;
  try {
    updater = require("electron-updater").autoUpdater;
    updater.autoDownload = false;
    updater.autoInstallOnAppQuit = true;
    updater.on("update-available", i => send("app:update", { status: "available", version: i.version }));
    updater.on("download-progress", p => send("app:update", { status: "progress", percent: p.percent }));
    updater.on("update-downloaded", i => { updateReady = true; send("app:update", { status: "ready", version: i.version }); });
    updater.on("error", e => send("app:update", { status: "error", message: String(e && e.message || e) }));
    setTimeout(() => updater.checkForUpdates().catch(() => {}), 8000);
  } catch (e) { updater = null; }
}

// ------------------------------------------------------------------ ComfyUI aktualisieren
async function updateComfy() {
  const c = cfg.comfy;
  if (!c || !c.portable) return { error: "Nur für das von Easy Generate installierte ComfyUI möglich." };
  await win.loadFile(path.join(__dirname, "setup.html"));
  status("Aktualisiere ComfyUI …", { phase: "update" });
  await killComfy();
  const upd = path.join(c.portable, "update");
  let r = await run(c.python, [path.join(upd, "update.py"), c.comfyDir, "--stable"], { cwd: upd });
  if (exists(path.join(upd, "update_new.py"))) {
    try { fs.renameSync(path.join(upd, "update_new.py"), path.join(upd, "update.py")); } catch (e) {}
    r = await run(c.python, [path.join(upd, "update.py"), c.comfyDir, "--skip_self_update", "--stable"], { cwd: upd });
  }
  status("Aktualisiere Programmbibliotheken … (kann einige Minuten dauern)", { phase: "update" });
  const r2 = await run(c.python, ["-s", "-m", "pip", "install", "-r", path.join(c.comfyDir, "requirements.txt")], { cwd: c.portable });
  if (r2.err) fs.appendFileSync(LOG_FILE(), "\n[pip]\n" + r2.out + r2.errOut);
  await launch();
  return { ok: true };
}

// ------------------------------------------------------------------ Fenster
function forceQuit() {
  // win.close() wartet auf die Seite; nach einem Treiber-Absturz antwortet sie evtl. nie mehr.
  // Deshalb hart beenden: Fenster zerstören und Prozess verlassen.
  quitting = true;
  if (updateReady && updater) { try { setTimeout(() => app.exit(0), 8000).unref(); updater.quitAndInstall(true, false); return; } catch (e) {} }   // geladenes Update beim Beenden installieren
  try { for (const w of BrowserWindow.getAllWindows()) w.destroy(); } catch (e) {}
  setTimeout(() => process.exit(0), 3000).unref();
  app.exit(0);
}
function createWindow() {
  win = new BrowserWindow({
    width: 1400, height: 920, minWidth: 900, minHeight: 600, backgroundColor: "#0e1014", title: "Easy Generate",
    icon: APP_ICON, autoHideMenuBar: true, show: false,
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false },
  });
  win.setMenu(null);
  win.once("ready-to-show", () => win.show());
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\/(127\.0\.0\.1|localhost)/.test(url)) return { action: "allow", overrideBrowserWindowOptions: { autoHideMenuBar: true, icon: APP_ICON, backgroundColor: "#0e1014" } };
    shell.openExternal(url); return { action: "deny" };
  });
  let closing = false;
  win.on("close", async e => {
    if (quitting) return;
    e.preventDefault();
    if (closing) { forceQuit(); return; }               // zweiter Klick aufs Kreuz: sofort beenden
    closing = true;
    let close = cfg.closeMode === "always";
    const running = cfg.comfy && await comfyAt(cfg.comfy.port);
    if (running && cfg.closeMode === "ask") {
      const T = {
        de: { b: ["Ja, schließen", "Nein, weiterlaufen lassen"], m: "Soll ComfyUI auch geschlossen werden?", d: "Das gibt den Grafikspeicher wieder frei. Lässt du es laufen, startet Easy Generate beim nächsten Mal schneller.", c: "Nicht mehr fragen – ComfyUI immer automatisch schließen" },
        en: { b: ["Yes, close it", "No, keep it running"], m: "Close ComfyUI as well?", d: "This frees your graphics memory. If you keep it running, Easy Generate starts faster next time.", c: "Don't ask again – always close ComfyUI automatically" },
        ru: { b: ["Да, закрыть", "Нет, оставить запущенным"], m: "Закрыть и ComfyUI?", d: "Это освободит видеопамять. Если оставить его запущенным, Easy Generate в следующий раз запустится быстрее.", c: "Больше не спрашивать – всегда закрывать ComfyUI автоматически" },
      }[cfg.lang] || null;
      const t = T || { b: ["Ja, schließen", "Nein, weiterlaufen lassen"], m: "Soll ComfyUI auch geschlossen werden?", d: "Das gibt den Grafikspeicher wieder frei.", c: "Nicht mehr fragen – ComfyUI immer automatisch schließen" };
      const r = await dialog.showMessageBox(win, {
        type: "question", title: "Easy Generate", buttons: t.b, defaultId: 0, cancelId: 1, message: t.m, detail: t.d, checkboxLabel: t.c, checkboxChecked: false,
      });
      close = r.response === 0;
      if (close && r.checkboxChecked) { cfg.closeMode = "always"; saveCfg(); }
    }
    // Aufräumen mit Zeitlimit – hängt etwas (z. B. nach einem Grafiktreiber-Absturz), wird trotzdem beendet
    const cleanup = (async () => {
      if (running) await pauseRented();
      if (running && close) await killComfy();
    })();
    await Promise.race([cleanup, sleep(15000)]);
    forceQuit();
  });
  // Reagiert die Oberfläche nicht mehr (z. B. Grafiktreiber abgestürzt), kann man trotzdem schließen
  win.on("unresponsive", () => { if (closing) forceQuit(); });
}

// ------------------------------------------------------------------ HuggingFace-Guthaben
// Das Guthaben (Prepaid-Credits) zeigt HuggingFace nur auf der angemeldeten Abrechnungsseite.
// Dafür gibt es ein eigenes Anmeldefenster mit getrennter Sitzung; die Cookies bleiben auf dem PC
// und gehen nur an huggingface.co.
const HF_PART = "persist:huggingface";
const isHF = u => { try { const h = new URL(u).hostname; return h === "huggingface.co" || h.endsWith(".huggingface.co"); } catch (e) { return false; } };
function decodeEntities(s) {
  return s.replace(/&(#x[0-9a-f]+|#\d+|quot|amp|apos|lt|gt|nbsp);/gi, (m, b) => {
    const k = b.toLowerCase();
    if (k[0] === "#") return String.fromCodePoint(k[1] === "x" ? parseInt(k.slice(2), 16) : parseInt(k.slice(1), 10));
    return { quot: '"', amp: "&", apos: "'", lt: "<", gt: ">", nbsp: "\u00a0" }[k];
  });
}
function parseWallet(html) {
  const out = {};
  const re = /data-props\s*=\s*(?:"([^"]*)"|'([^']*)')/gi;
  let m;
  const visit = (o, depth) => {
    if (!o || typeof o !== "object" || depth > 8) return;
    if (o.entity && typeof o.entity === "object" && typeof o.entity.currentBalanceUsd === "number" && (o.entity.type || "user") === "user") out.balance = o.entity.currentBalanceUsd;
    if (out.balance == null && typeof o.invoiceCreditsCents === "number") out.balance = o.invoiceCreditsCents / 100;
    for (const k of ["includedNanoUsd", "usedNanoUsd", "limitNanoUsd"]) if (typeof o[k] === "number" && out[k] == null) out[k] = o[k];
    for (const v of Object.values(o)) if (v && typeof v === "object") visit(v, depth + 1);
  };
  while ((m = re.exec(html))) { try { visit(JSON.parse(decodeEntities(m[1] != null ? m[1] : m[2])), 0); } catch (e) {} }
  return out;
}
async function hfWallet() {
  try {
    const ses = session.fromPartition(HF_PART);
    const r = await ses.fetch("https://huggingface.co/settings/billing", { headers: { Accept: "text/html" } });
    if (!r.ok || !isHF(r.url) || /\/login/.test(new URL(r.url).pathname)) return { login: true };
    const w = parseWallet(await r.text());
    if (w.balance == null) return { login: !w.includedNanoUsd, unknown: true, ...w };
    return { ...w, at: Date.now() };
  } catch (e) { return { error: String(e.message || e) }; }
}
function hfLogin() {
  return new Promise(resolve => {
    const w = new BrowserWindow({
      width: 520, height: 780, parent: win, title: "HuggingFace – Anmelden", icon: APP_ICON, autoHideMenuBar: true, backgroundColor: "#ffffff",
      webPreferences: { partition: HF_PART, contextIsolation: true, nodeIntegration: false, sandbox: true },
    });
    w.setMenu(null);
    let done = false;
    const finish = ok => { if (done) return; done = true; resolve(ok); if (!w.isDestroyed()) w.close(); };
    w.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });
    w.webContents.on("did-navigate", (e, url) => { if (isHF(url) && new URL(url).pathname.startsWith("/settings/billing")) setTimeout(() => finish(true), 600); });
    w.on("closed", () => { if (!done) { done = true; resolve(false); } });
    w.loadURL("https://huggingface.co/login?next=%2Fsettings%2Fbilling");
  });
}
async function hfLogout() { try { await session.fromPartition(HF_PART).clearStorageData(); } catch (e) {} return true; }
async function pauseRented() {
  // Gemietete GPUs (eigene Spaces) beim Beenden pausieren, damit keine Kosten weiterlaufen.
  if (!cfg.comfy || !cfg.comfy.port) return;
  await new Promise(resolve => {
    const req = http.request({ host: "127.0.0.1", port: cfg.comfy.port, path: "/easy/cloud/pause_all", method: "POST", headers: { "Content-Type": "application/json" }, timeout: 8000 }, res => { res.resume(); res.on("end", resolve); });
    req.on("error", resolve); req.on("timeout", () => { req.destroy(); resolve(); });
    req.end("{}");
  });
}

// ------------------------------------------------------------------ IPC
ipcMain.handle("app:showItem", (e, p) => { try { if (typeof p === "string" && fs.existsSync(p)) shell.showItemInFolder(p); } catch (err) {} return true; });
ipcMain.handle("app:openFolder", (e, p) => { try { if (typeof p === "string" && fs.existsSync(p) && fs.statSync(p).isDirectory()) shell.openPath(p); } catch (err) {} return true; });
ipcMain.handle("app:chooseGalleryDir", async (e, start) => {
  const T = { de: "Ordner für deine Videos und Bilder wählen", en: "Choose a folder for your videos and images", ru: "Выбери папку для видео и изображений" };
  const r = await dialog.showOpenDialog(win, { title: T[cfg.lang] || T.de, defaultPath: start || app.getPath("videos"), properties: ["openDirectory", "createDirectory"] });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle("app:defaultGalleryDir", () => path.join(app.getPath("videos"), "Easy Generate"));
ipcMain.handle("app:hfWallet", () => hfWallet());
ipcMain.handle("app:hfLogin", () => hfLogin());
ipcMain.handle("app:hfLogout", () => hfLogout());
ipcMain.handle("app:openExternal", (e, url) => { if (isHF(url)) shell.openExternal(url); return true; });
ipcMain.handle("app:info", () => ({
  version: app.getVersion(), nodeVersion: NODE_VERSION, comfyRoot: cfg.comfy && (cfg.comfy.portable || cfg.comfy.comfyDir),
  managed: !!(cfg.comfy && cfg.comfy.managed), canUpdateComfy: !!(cfg.comfy && cfg.comfy.portable), closeMode: cfg.closeMode, port: cfg.comfy && cfg.comfy.port,
}));
ipcMain.handle("app:setCloseMode", (e, m) => { if (["ask", "always", "never"].includes(m)) { cfg.closeMode = m; saveCfg(); } return true; });
ipcMain.handle("app:checkUpdates", async () => {
  if (!updater) return { error: app.isPackaged ? "Update-Dienst nicht verfügbar." : "Updates gibt es nur in der installierten Version." };
  try { const r = await updater.checkForUpdates(); const v = r && r.updateInfo && r.updateInfo.version; return { available: !!v && v !== app.getVersion(), version: v }; }
  catch (e) { return { error: "Update-Prüfung fehlgeschlagen: " + (e.message || e) }; }
});
ipcMain.handle("app:downloadUpdate", async () => { if (updater) { try { await updater.downloadUpdate(); } catch (e) { send("app:update", { status: "error", message: String(e.message || e) }); } } return true; });
ipcMain.handle("app:installUpdate", async () => { quitting = true; if (updater) updater.quitAndInstall(false, true); return true; });
ipcMain.handle("app:openPath", (e, which) => {
  const c = cfg.comfy || {};
  const p = which === "output" ? path.join(c.comfyDir || "", "output") : which === "models" ? path.join(c.comfyDir || "", "models") : (c.portable || c.comfyDir);
  if (p && exists(p)) shell.openPath(p);
  return true;
});
ipcMain.handle("app:restartComfy", async () => { await win.loadFile(path.join(__dirname, "setup.html")); await killComfy(); await launch(); return true; });
ipcMain.handle("app:updateComfy", () => updateComfy());
ipcMain.handle("app:changeComfy", async () => { await win.loadFile(path.join(__dirname, "setup.html")); send("setup:wizard", {}); return true; });

// Einrichtungsassistent
ipcMain.handle("setup:state", async () => ({ hasComfy: !!(cfg.comfy && cfg.comfy.comfyDir && exists(cfg.comfy.comfyDir)), version: app.getVersion() }));
ipcMain.handle("setup:detect", async () => {
  const [inst, gpu] = await Promise.all([detectInstalls(), detectGPU()]);
  const defFolder = path.join(process.env.SystemDrive ? process.env.SystemDrive + "\\" : os.homedir(), "EasyGenerate");
  return Object.assign(inst, { gpu, packages: PACKAGES, defaultFolder: defFolder });
});
ipcMain.handle("setup:chooseFolder", async (e, start) => {
  const r = await dialog.showOpenDialog(win, { title: "Wohin soll ComfyUI installiert werden?", defaultPath: start, properties: ["openDirectory", "createDirectory"] });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle("setup:chooseExisting", async () => {
  const r = await dialog.showOpenDialog(win, { title: "ComfyUI-Ordner auswählen (der Ordner mit main.py)", properties: ["openDirectory"] });
  if (r.canceled) return null;
  let d = r.filePaths[0];
  if (!isComfyDir(d) && isComfyDir(path.join(d, "ComfyUI"))) d = path.join(d, "ComfyUI");
  if (!isComfyDir(d)) return { error: "In diesem Ordner wurde kein ComfyUI gefunden (main.py fehlt)." };
  return { comfyDir: d, python: pythonFor(d), usable: !!pythonFor(d) };
});
ipcMain.handle("setup:freeSpace", async (e, folder) => {
  try { let p = folder; while (p && !exists(p)) p = path.dirname(p); const s = fs.statfsSync(p); return s.bavail * s.bsize; } catch (e) { return null; }
});
ipcMain.handle("setup:useExisting", async (e, sel) => {
  cfg.comfy = { comfyDir: sel.comfyDir, python: sel.python, managed: false, portable: exists(path.join(path.dirname(sel.comfyDir), "update", "update.py")) ? path.dirname(sel.comfyDir) : null, port: 8188 };
  saveCfg(); await launch(); return true;
});
ipcMain.handle("setup:install", async (e, opts) => {
  try { await installComfy(opts); await launch(); return { ok: true }; }
  catch (err) { return { error: String(err.message || err) }; }
});
ipcMain.handle("setup:retry", async () => { await launch(); return true; });
ipcMain.handle("setup:log", () => tailLog(6000));

// ------------------------------------------------------------------ Ollama (Prompt-Helfer)
function ollamaExe() {
  const la = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
  return [path.join(la, "Programs", "Ollama", "ollama.exe"), "C:\\Program Files\\Ollama\\ollama.exe"].find(exists) || null;
}
const ollamaUp = () => getJSON("http://127.0.0.1:11434/api/tags", 2000);
async function startOllama() {
  if (await ollamaUp()) return { ok: true };
  const exe = ollamaExe();
  if (!exe) return { error: "Ollama ist nicht installiert." };
  const p = spawn(exe, ["serve"], { detached: true, windowsHide: true, stdio: "ignore" });
  p.unref();
  for (let i = 0; i < 40; i++) { if (await ollamaUp()) return { ok: true }; await sleep(500); }
  return { error: "Ollama startet nicht. Bitte den PC neu starten und erneut versuchen." };
}
async function installOllama() {
  if (!IS_WIN) return { error: "Die automatische Installation gibt es nur unter Windows." };
  const prog = (text, pct) => send("ollama:progress", { text, pct });
  const setup = path.join(app.getPath("temp"), "OllamaSetup.exe");
  try {
    await download("https://ollama.com/download/OllamaSetup.exe", setup, (got, total, speed) =>
      prog(`Lade Ollama herunter … ${(got / 1048576).toFixed(0)} / ${(total / 1048576).toFixed(0)} MB · ${(speed / 1048576).toFixed(1)} MB/s`, total ? got / total * 100 : 0));
    prog("Installiere Ollama … (dauert etwa eine Minute)", 100);
    const r = await run(setup, ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]);
    if (r.err && !ollamaExe()) return { error: "Installation fehlgeschlagen: " + (r.err.message || r.err) };
    try { fs.unlinkSync(setup); } catch (e) {}
    prog("Starte Ollama …", 100);
    return await startOllama();
  } catch (e) { return { error: "Ollama konnte nicht installiert werden: " + (e.message || e) }; }
}
ipcMain.handle("app:ollamaInfo", async () => ({ installed: !!ollamaExe(), running: !!(await ollamaUp()) }));
ipcMain.handle("app:installOllama", () => installOllama());
ipcMain.handle("app:startOllama", () => startOllama());
ipcMain.handle("app:setLang", (e, l) => { if (["de", "en", "ru"].includes(l)) { cfg.lang = l; saveCfg(); } return true; });
ipcMain.handle("app:getLang", () => cfg.lang || "de");

// ------------------------------------------------------------------ Start
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(async () => {
    loadCfg();
    createWindow();
    initUpdater();
    await win.loadFile(path.join(__dirname, "setup.html"));
    if (cfg.comfy && cfg.comfy.comfyDir && exists(cfg.comfy.comfyDir)) launch();
    else send("setup:wizard", {});
  });
  app.on("window-all-closed", () => app.quit());
}
