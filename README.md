# Easy Generate

Einfache Windows-Oberfläche für lokale **Bild- und Videogenerierung** mit [ComfyUI](https://github.com/comfyanonymous/ComfyUI) – ohne Knoten, ohne Kommandozeile.

## Installation

1. Unter **[Releases](https://github.com/Silverharemedia/easy-generate/releases/latest)** die Datei `Easy-Generate-Setup-x.y.z.exe` herunterladen und ausführen.
2. Easy Generate starten. Beim ersten Start sucht das Programm ein vorhandenes ComfyUI oder installiert auf Wunsch ein neues (AMD, NVIDIA oder Intel – wird automatisch erkannt).
3. Unter **Modelle** ein Bild- oder Video-Modell auswählen und installieren – die Dateien landen automatisch im richtigen Ordner.

Updates installiert Easy Generate selbst (Einstellungen → „Nach Updates suchen“).

## Funktionen

- 🎬 **Video** und 🖼️ **Bild** – Prompt eingeben, Format/Größe/Länge wählen, fertig. Start- und Referenzbilder per Drag & Drop.
- 📦 **Modelle** – alle lokalen ComfyUI-Vorlagen (LTX, Wan, Flux, Qwen-Image, …) mit 1-Klick-Installation, Fortschrittsanzeige, Fortsetzen nach Abbruch und Entfernen.
- ✨ **KI-Prompt-Helfer** – lokal über Ollama oder mit Claude.
- 📁 **Galerie** aller Ergebnisse.

## Aufbau

- `app/` – das Windows-Programm (Electron): Einrichtung, Start von ComfyUI, Updates.
- `app/comfy-node/EasyGenerate/` – die Erweiterung für ComfyUI mit der eigentlichen Oberfläche (`/easy`).

Eine neue Version entsteht, indem die Versionsnummer in `app/package.json` erhöht und ein Tag `vX.Y.Z` gepusht wird – GitHub baut dann das Setup und veröffentlicht es als Update.
