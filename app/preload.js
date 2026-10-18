// Stellt der Oberfläche eine kleine, sichere Schnittstelle zum Programm bereit.
"use strict";
const { contextBridge, ipcRenderer } = require("electron");
const on = (ch, cb) => { const f = (e, d) => cb(d); ipcRenderer.on(ch, f); return () => ipcRenderer.removeListener(ch, f); };

contextBridge.exposeInMainWorld("easyApp", {
  getInfo: () => ipcRenderer.invoke("app:info"),
  setCloseMode: m => ipcRenderer.invoke("app:setCloseMode", m),
  checkForUpdates: () => ipcRenderer.invoke("app:checkUpdates"),
  downloadUpdate: () => ipcRenderer.invoke("app:downloadUpdate"),
  installUpdate: () => ipcRenderer.invoke("app:installUpdate"),
  onUpdate: cb => on("app:update", cb),
  openPath: w => ipcRenderer.invoke("app:openPath", w),
  restartComfy: () => ipcRenderer.invoke("app:restartComfy"),
  updateComfy: () => ipcRenderer.invoke("app:updateComfy"),
  changeComfy: () => ipcRenderer.invoke("app:changeComfy"),
  ollamaInfo: () => ipcRenderer.invoke("app:ollamaInfo"),
  installOllama: () => ipcRenderer.invoke("app:installOllama"),
  startOllama: () => ipcRenderer.invoke("app:startOllama"),
  onOllamaProgress: cb => on("ollama:progress", cb),
  setLang: l => ipcRenderer.invoke("app:setLang", l),
  getLang: () => ipcRenderer.invoke("app:getLang"),
  showItem: p => ipcRenderer.invoke("app:showItem", p),
  openFolder: p => ipcRenderer.invoke("app:openFolder", p),
  chooseGalleryDir: s => ipcRenderer.invoke("app:chooseGalleryDir", s),
  defaultGalleryDir: () => ipcRenderer.invoke("app:defaultGalleryDir"),
  hfWallet: () => ipcRenderer.invoke("app:hfWallet"),
  hfLogin: () => ipcRenderer.invoke("app:hfLogin"),
  hfLogout: () => ipcRenderer.invoke("app:hfLogout"),
  setup: {
    state: () => ipcRenderer.invoke("setup:state"),
    detect: () => ipcRenderer.invoke("setup:detect"),
    chooseFolder: s => ipcRenderer.invoke("setup:chooseFolder", s),
    chooseExisting: () => ipcRenderer.invoke("setup:chooseExisting"),
    freeSpace: f => ipcRenderer.invoke("setup:freeSpace", f),
    useExisting: s => ipcRenderer.invoke("setup:useExisting", s),
    install: o => ipcRenderer.invoke("setup:install", o),
    retry: () => ipcRenderer.invoke("setup:retry"),
    log: () => ipcRenderer.invoke("setup:log"),
    onStatus: cb => on("setup:status", cb),
    onError: cb => on("setup:error", cb),
    onWizard: cb => on("setup:wizard", cb),
  },
});
