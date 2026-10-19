# Easy Generate

**Bilder und Videos mit KI erstellen – einfach, ohne Knoten und ohne Kommandozeile.**
Auf dem eigenen PC, auf einer gemieteten Cloud-GPU oder kostenlos in der Hugging-Face-Cloud.

Easy Generate ist eine Windows-Oberfläche für [ComfyUI](https://github.com/comfyanonymous/ComfyUI): Modell wählen, beschreiben, was entstehen soll, fertig. Die komplizierten ComfyUI-Abläufe laufen unsichtbar im Hintergrund.

> 💡 **Idee & Konzept:** Sergey Jidkov ([Silverharemedia](https://github.com/Silverharemedia))

*English: Easy Generate is a simple Windows app for AI image and video generation with ComfyUI – locally, on your own rented cloud GPUs or for free in the Hugging Face cloud. The interface is available in 12 languages.*

---

## Installation

1. Unter **[Releases](https://github.com/Silverharemedia/easy-generate/releases/latest)** die Datei `Easy-Generate-Setup-x.y.z.exe` herunterladen und ausführen.
2. Easy Generate starten. Beim ersten Start sucht das Programm ein vorhandenes ComfyUI oder installiert auf Wunsch ein neues – passend zur Grafikkarte (AMD, NVIDIA oder Intel, wird automatisch erkannt).
3. Unter **Modelle** ein Bild- oder Video-Modell auswählen und installieren – die Dateien landen automatisch im richtigen Ordner.

Updates installiert Easy Generate selbst (Einstellungen → „Nach Updates suchen“).

## Funktionen

### 🎬 Erstellen
- **Video** und **Bild** – Prompt eingeben, Format, Größe und Länge wählen, fertig. Start-, End- und Referenzbilder per Drag & Drop.
- **Drei Wege zu rechnen**, direkt im Studio umschaltbar:
  - 🖥️ **Mein PC** – lokal mit der eigenen Grafikkarte.
  - 🚀 **Meine Cloud-GPU** – die eigenen Vorlagen auf einer gemieteten Grafikkarte (siehe unten).
  - ☁️ **HuggingFace-Cloud** – kostenlose ZeroGPU-Spaces oder Bezahlung pro Video, ganz ohne Download.
- ✨ **KI-Prompt-Helfer** – macht aus einer kurzen Idee (auch auf Deutsch) einen guten englischen Prompt; lokal über Ollama oder mit Claude. Sieht auf Wunsch auch das Startbild an.
- ➕ **Weiter** – verlängert ein fertiges Video: das letzte Bild wird automatisch Startbild des nächsten Abschnitts (für Szenen über 20 Sekunden).
- 🎲 **Varianten** – mehrere Versionen mit verschiedenen Seeds auf einmal, auf Wunsch verteilt auf alle GPUs.
- 🧠 **Speicher-Warnung**, wenn ein Modell zu groß für PC-Arbeitsspeicher + Grafikkarte ist.
- ⏱️ **Zeitschätzung** – lernt aus deinen bisherigen Erstellungen, wie lange ein Video ungefähr dauert.

### 📋 Warteschlange
- Beliebig viele Videos hintereinander in Auftrag geben – jeder Rechner (PC, GPU 1, GPU 2 …) arbeitet seine eigene Warteschlange ab, **alle gleichzeitig**.
- Eigene Spalte neben dem Ergebnis: **Vorschaubild**, Modell und Prompt jedes Auftrags, **eigene Farbe je GPU**.
- 📋 **Prompt kopieren** und ↩ **Bild + Prompt übernehmen** für den nächsten Lauf – auch bei fertigen Aufträgen („Zuletzt fertig“).
- Aufträge überstehen Neuladen und Sprachwechsel; einzelne Aufträge lassen sich entfernen oder abbrechen.

### 🚀 Eigene Cloud-GPUs
- Easy Generate legt im eigenen Hugging-Face-Konto einen **privaten Server mit ComfyUI** an – die eigenen Vorlagen laufen dort genau wie zu Hause, nur auf großen Grafikkarten (z. B. L40S, A100, RTX PRO 6000).
- **Mehrere GPUs gleichzeitig** mieten und nutzen, z. B. GPU 1 für Bild → Video, GPU 2 für Text → Video. Die GPU-Wahl wird pro Modell gemerkt.
- Modelle werden direkt im Rechenzentrum geladen – kein Download auf den PC nötig.
- **Kosten im Blick:** Guthaben, Verbrauch im Monat und „reicht noch für ≈ X Std.“ direkt im Studio – auch für mehrere laufende GPUs zusammen.
- 🛑 **Tageslimit:** ab einem selbst gewählten Betrag pro Tag werden alle Cloud-GPUs automatisch pausiert.
- ⚡ **Schnellstart (optional):** Modelle bleiben in einem privaten Hugging-Face-Speicher und müssen nach dem Aufwachen nicht neu geladen werden (inklusive bis 100 GB, mit PRO 1 TB).
- 🛡️ **Sicherheitsnetz:** Hängt ein Auftrag (40 Min. ohne Fortschritt), antwortet eine GPU nicht mehr oder startet sie ewig nicht, wird sie automatisch pausiert. Updates und Einstellungen starten pausierte GPUs nie ungewollt.
- **Spart Geld:** Pausieren/Starten mit einem Klick, automatisches Ausschalten ohne Nutzung, ☕ „Pausieren, wenn die Warteschlange fertig ist“ (für „ich gehe kurz weg“) und ☕ „nach dem Einrichten pausieren“.

### ☁️ Hugging-Face-Cloud
- 🆓 **Gratis** – kostenlose ZeroGPU-Spaces mit dem täglichen Gratis-Kontingent; alle Einstellungen eines Space (Qualität, Auflösung, Länge …) direkt im Studio.
- 💳 **Pro Video bezahlen** – Inference Providers (Wan, LTX, MiniMax, Flux …) zum Preis des Anbieters, ohne Aufschlag.
- 🖥️ **GPU mieten** – Spaces stundenweise auf eigener Hardware.
- **Guthaben-Anzeige** mit Anmeldung bei Hugging Face und „Wofür reicht es?“-Übersicht.
- Warnt, wenn ein Space von einem fremden Gratis-Dienst abhängt (und deshalb trotz gemieteter GPU warten müsste).

### 📦 Modelle
- Alle ComfyUI-Vorlagen (LTX, Wan, Flux, Qwen-Image, MiniMax, …) mit **1-Klick-Installation**, Fortschrittsanzeige, Fortsetzen nach Abbruch und Entfernen.
- Wahlweise „für meinen PC“ oder „nur für die Cloud-GPU“ (ohne Download).
- Hilft bei gesperrten Modellen (Hugging-Face-Freischaltung).

### 📁 Galerie
- Alle Ergebnisse, **nach Modell sortiert**, mit Prompt – auch Ergebnisse aus der Cloud.
- 🔎 **Suche** nach Prompt/Modell und ⭐ **Favoriten**.
- Speicherort frei wählbar (ohne doppelten Speicherplatz) oder Galerie ganz abschalten.

### 🛡️ Zuverlässigkeit
- **Absturz-Erkennung:** Stürzt ComfyUI ab (z. B. Speicher voll bei sehr großen Modellen), zeigt Easy Generate das deutlich an, sichert das Protokoll und startet ComfyUI automatisch neu.
- 🌡️ **Monitor** mit Auslastung, Grafikspeicher und Temperaturen von CPU und GPU.
- Beim Schließen auf Wunsch ComfyUI beenden und laufende Cloud-GPUs pausieren.

### 🌍 12 Sprachen
Deutsch, English, Français, Español, Polski, Čeština, Hrvatski, Русский, العربية, हिन्दी, 中文, 日本語 – umschaltbar in den Einstellungen.

## Sicherheit & Datenschutz

- Dein **Hugging-Face-Schlüssel bleibt auf deinem PC** und wird ausschließlich an Hugging Face selbst gesendet.
- Fremde Gratis-Spaces bekommen nie deinen Haupt-Schlüssel, sondern nur einen eigenen Schlüssel ohne Rechte.
- Eigene Cloud-GPUs sind **private** Spaces in deinem Konto; dort läuft nur ComfyUI mit Easy Generate.
- Bezahlt wird direkt bei Hugging Face bzw. dem Anbieter – Easy Generate zeigt nur Guthaben und Verbrauch an.

## Aufbau

- `app/` – das Windows-Programm (Electron): Einrichtung, Start und Überwachung von ComfyUI, Updates.
- `app/comfy-node/EasyGenerate/` – die Erweiterung für ComfyUI mit der eigentlichen Oberfläche (`/easy`), Galerie, Cloud-Anbindung und Cloud-GPU-Steuerung.
- `app/comfy-node/EasyGenerate/ui/lang/` – die Übersetzungen (je Sprache eine Datei).

Neue Versionen baut GitHub Actions (`.github/workflows/release.yml`) und veröffentlicht sie als Update.

## Mitwirkende

- **Sergey Jidkov** ([Silverharemedia](https://github.com/Silverharemedia)) – Idee, Konzept und Tests
- Umsetzung mit [Claude](https://claude.ai) (Anthropic)

## Lizenz

Easy Generate ist frei und offen: [MIT-Lizenz](LICENSE). Jeder darf es kostenlos nutzen, weitergeben und verändern.
