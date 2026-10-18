// Easy Generate – Übersetzung Deutsch → Englisch.
// Die Oberfläche ist auf Deutsch geschrieben; ist Englisch gewählt, übersetzt dieses Skript
// alle Texte im Fenster (auch später eingefügte) anhand der Tabelle unten.
(function () {
  "use strict";
  const EN = {
    // Navigation & allgemein
    "Video": "Video", "Bild": "Image", "Galerie": "Gallery", "Modelle": "Models", "Einstellungen": "Settings",
    "Verbinde …": "Connecting …", "Bereit": "Ready", "ComfyUI nicht erreichbar": "ComfyUI not reachable",
    "Ein-/Ausklappen": "Expand/collapse", "Abbrechen": "Cancel", "Speichern": "Save", "Aktualisieren": "Refresh",
    "Installieren": "Install", "Herunterladen": "Download", "Laden": "Download", "Benutzen": "Use", "Neu": "New",
    "Zurück": "Back", "Fehler": "Error", "Fehler:": "Error:", "Lade …": "Loading …", "Suche …": "Searching …",
    "Starte …": "Starting …", "Erweitert": "Advanced", "Format": "Format", "Größe": "Size", "Länge:": "Length:",
    "Anzahl Bilder": "Number of images", "zufällig": "random", "Übernehmen": "Apply", "Verwerfen": "Discard",
    "Alle": "All", "Bilder": "Images", "Videos": "Videos", "Modell": "Model", "Modell:": "Model:",
    "Schnell": "Fast", "Normal": "Normal", "Groß": "Large", "Quer 16:9": "Landscape 16:9", "Hoch 9:16": "Portrait 9:16",
    "Quadrat": "Square", "Wie Bild": "Like image", "Programm": "Application", "Version": "Version",

    // Studio
    "Video erstellen": "Create video", "Bild erstellen": "Create image", "Erstellen": "Create",
    "Beschreibe eine Szene oder gib ein Startbild vor.": "Describe a scene or provide a start image.",
    "Beschreibe dein Bild – oder lade ein Bild zum Bearbeiten hoch (je nach Modell).": "Describe your image – or upload an image to edit (depending on the model).",
    "+ Weitere Modelle": "+ More models", "Was soll passieren?": "What should happen?",
    "Was soll im Video passieren?": "What should happen in the video?", "Beschreibe dein Video": "Describe your video",
    "Was soll am Bild passieren / entstehen?": "What should change or be created?", "Beschreibe dein Bild": "Describe your image",
    "z. B. Eine Katze läuft durch einen verschneiten Wald, sanftes Morgenlicht, Kamera folgt langsam": "e.g. A cat walks through a snowy forest, soft morning light, camera slowly follows",
    "z. B. Ein gemütliches Café in Paris bei Regen, warmes Licht, fotorealistisch": "e.g. A cozy café in Paris in the rain, warm light, photorealistic",
    "✨ Prompt mit KI verbessern": "✨ Improve prompt with AI", "✨ Denke nach …": "✨ Thinking …",
    "Vorschlag (Englisch – die Modelle verstehen Englisch am besten):": "Suggestion (English – the models understand English best):",
    "Noch etwas ändern? (z. B. „nachts“, „mehr Action“, „im Anime-Stil“)": "Change anything? (e.g. “at night”, “more action”, “anime style”)",
    "Wunsch eintippen, dann Enter": "Type a request, then press Enter",
    "Was soll NICHT vorkommen?": "What should NOT appear?", "leer = Standard der Vorlage": "empty = template default",
    "Eingebaute Prompt-Verbesserung des Modells (lokal, etwas langsamer)": "Model's built-in prompt enhancement (local, a bit slower)",
    "Schnell-Modus": "Fast mode",
    "Seed (gleicher Seed + gleicher Prompt = gleiches Ergebnis)": "Seed (same seed + same prompt = same result)", "Seed": "Seed",
    "Hier erscheint dein Ergebnis.": "Your result will appear here.", "Tipp: Erst klein testen, dann groß erstellen.": "Tip: test small first, then create large.",
    "Nochmal (neuer Seed)": "Again (new seed)", "In der Warteschlange …": "In the queue …", "Läuft …": "Running …",
    "Fertig – lade Ergebnis …": "Done – loading result …", "Abgebrochen.": "Cancelled.",
    "Fertig, aber keine Ausgabe gefunden. Schau in den Ausgabe-Ordner.": "Done, but no output found. Check the output folder.",
    "Fehler beim Erstellen. Details stehen im ComfyUI-Protokoll.": "Error while creating. Details are in the ComfyUI log.",
    "ComfyUI läuft nicht.": "ComfyUI is not running.", "Es wird gerade etwas erstellt …": "Something is being created right now …",
    "Dieses Werkzeug braucht keinen Text – einfach die Eingabe auswählen und starten.": "This tool needs no text – just choose the input and start.",
    "Bitte beschreibe zuerst, was entstehen soll.": "Please describe first what should be created.",
    "Tippe zuerst deine Idee ein – auf Deutsch und kurz ist okay.": "Type your idea first – short is fine, any language.",
    "Für dieses Modell fehlen noch Dateien – sie werden gerade geladen oder der Download wurde unterbrochen.": "Some files for this model are still missing – they are downloading or the download was interrupted.",
    "Zu den Modellen": "Go to models", "(Modelle fehlen noch)": "(files still missing)",
    "Modelle ansehen": "Browse models", "Beliebt:": "Popular:",
    "Wähle unter": "Choose one under", "eins aus – es wird mit einem Klick heruntergeladen und eingerichtet.": "– it is downloaded and set up with one click.",
    "klicken zum Ändern": "click to change", "Bild hierher ziehen oder": "Drag an image here or", "Video hierher ziehen oder": "Drag a video here or",
    "Audiodatei hierher ziehen oder": "Drag an audio file here or", "klicken": "click",
    "Dauer wird bei der ersten Erstellung gemessen – danach siehst du hier eine Schätzung.": "The duration is measured on the first run – after that you'll see an estimate here.",
    "⏱ Geschätzte Dauer:": "⏱ Estimated time:", "· gleich fertig …": "· almost done …",
    "Bild": "Image", "Video": "Video", "Audio": "Audio",

    // Galerie
    "Deine zuletzt erstellten Videos und Bilder": "Your recently created videos and images", "Noch nichts erstellt.": "Nothing created yet.",
    "Galerie konnte nicht geladen werden.": "Could not load the gallery.",

    // Modelle
    "Alle Vorlagen, die ComfyUI lokal ausführen kann. Installieren lädt die nötigen Dateien automatisch in die richtigen Ordner.": "All templates ComfyUI can run locally. Installing downloads the required files into the right folders automatically.",
    "Suchen … (z. B. LTX, Wan, Flux, Qwen)": "Search … (e.g. LTX, Wan, Flux, Qwen)", "Beliebteste": "Most popular", "Neueste": "Newest", "Kleinste": "Smallest",
    "nur installierte": "installed only", "🎬 Video": "🎬 Video", "🖼️ Bild": "🖼️ Image",
    "✓ installiert": "✓ installed", "⬇ wird geladen": "⬇ downloading", "nicht installiert": "not installed", "Dateien vorhanden": "files present",
    "Fehlende laden": "Get missing files", "Einblenden": "Show", "Ausblenden": "Hide", "Entfernen": "Remove", "Anhalten": "Pause", "Download angehalten": "Download paused",
    "⚠ Lizenz: nicht in der EU": "⚠ License: not in the EU", "⚠ Lizenzhinweis": "⚠ License notice",
    "Verstanden, trotzdem installieren": "Understood, install anyway", "Erneut versuchen": "Try again",
    "Dateien löschen und Speicher freigeben": "Delete files and free up space",
    "Das Werkzeug verschwindet aus der Liste.": "The tool is removed from the list.",
    "Es gibt keine Dateien, die nur hiervon genutzt werden.": "There are no files used only by this tool.",
    "Zusätzlich kannst du die Modelldateien löschen, die nur dieses Werkzeug braucht": "You can also delete the model files only this tool needs",
    "Die Lizenz der MiniMax-H3-Modelldateien schliesst die lokale Nutzung in der EU, Grossbritannien, Suedkorea und den USA aus (auch fuer die erzeugten Videos). Bitte pruefe vor der Installation, ob du sie nutzen darfst.":
      "The MiniMax H3 model license excludes local use in the EU, the UK, South Korea and the USA (including generated videos). Please check whether you are allowed to use it before installing.",
    "ComfyUI konnte im Hintergrund nicht geladen werden.": "ComfyUI could not be loaded in the background.",
    "Umwandlung lieferte keinen Ablauf.": "Conversion produced no workflow.",
    "Keine Verbindung zum Download-Server (Internet/Firewall pruefen)": "No connection to the download server (check internet/firewall)",
    "Download verweigert – dieses Modell braucht einen HuggingFace-Zugang (Token in den Einstellungen)": "Download refused – this model needs HuggingFace access (token in Settings)",
    "Download unvollstaendig – wird beim naechsten Versuch fortgesetzt": "Download incomplete – will resume on the next try",

    // Einstellungen
    "Nach Updates suchen": "Check for updates", "Du hast die neueste Version.": "You have the latest version.", "Jetzt laden": "Download now",
    "Update-Fehler – erneut versuchen": "Update error – try again", "⬇ Update wird geladen …": "⬇ Downloading update …",
    "✅ Update bereit – jetzt neu starten": "✅ Update ready – restart now",
    "ComfyUI (die KI im Hintergrund)": "ComfyUI (the AI engine in the background)", "ComfyUI aktualisieren": "Update ComfyUI", "Neu starten": "Restart",
    "Ausgabe-Ordner öffnen": "Open output folder", "Modell-Ordner öffnen": "Open models folder", "Anderes ComfyUI wählen": "Choose another ComfyUI",
    "Ordner:": "Folder:", "Wird von Easy Generate verwaltet.": "Managed by Easy Generate.", "Eigenes ComfyUI (extern).": "Your own ComfyUI (external).",
    "Diese Seite läuft im Browser. Öffne Easy Generate als Programm für Updates und Verwaltung.": "This page runs in a browser. Open the Easy Generate app for updates and management.",
    "Bitte warten, bis die aktuelle Erstellung fertig ist.": "Please wait until the current job has finished.",
    "ComfyUI wird aktualisiert und neu gestartet – das Fenster lädt danach neu …": "ComfyUI is being updated and restarted – the window will reload afterwards …",
    "Beim Schließen des Programms": "When closing the application", "Jedes Mal fragen": "Ask every time",
    "ComfyUI immer mit schließen": "Always close ComfyUI too", "ComfyUI weiterlaufen lassen": "Keep ComfyUI running",
    "ComfyUI belegt im Hintergrund Grafikspeicher.": "ComfyUI uses graphics memory in the background.",
    "✨ KI-Prompt-Helfer": "✨ AI prompt helper", "Lokal (Ollama)": "Local (Ollama)", "kostenlos, privat": "free, private",
    "Claude": "Claude", "beste Qualität": "best quality",
    "Läuft komplett auf deinem PC, kostenlos und privat. Das Sprachmodell gibt den Grafikspeicher nach jeder Antwort sofort wieder frei.": "Runs entirely on your PC, free and private. The language model frees graphics memory right after each answer.",
    "Prüfe Ollama …": "Checking Ollama …", "Ollama installieren": "Install Ollama", "Ollama starten": "Start Ollama", "Starte Ollama …": "Starting Ollama …",
    "Lade Ollama herunter …": "Downloading Ollama …", "Installiere Ollama … (dauert etwa eine Minute)": "Installing Ollama … (takes about a minute)",
    "Ollama ist installiert, läuft aber gerade nicht.": "Ollama is installed but not running.",
    "Ollama ist noch nicht installiert. Ein Klick genügt – ca. 1 GB Download.": "Ollama is not installed yet. One click is enough – about 1 GB download.",
    "Ollama läuft nicht. Installiere es von ollama.com oder öffne Easy Generate als Programm.": "Ollama is not running. Install it from ollama.com or open the Easy Generate app.",
    "Ollama läuft nicht – bitte Ollama starten.": "Ollama is not running – please start Ollama.",
    "Empfohlene Modelle – per Klick laden": "Recommended models – download with one click", "Verwendetes Modell": "Model in use",
    "Noch kein Modell – lade oben eins mit einem Klick.": "No model yet – download one above with one click.",
    "3,3 GB · schnell, kann auch Bilder ansehen (empfohlen)": "3.3 GB · fast, can also look at images (recommended)",
    "5,2 GB · sehr gute Texte, keine Bilder": "5.2 GB · very good text, no images", "8,1 GB · beste Qualität, kann Bilder ansehen": "8.1 GB · best quality, can look at images",
    "Beste Qualität, sieht auch dein Startbild an. API-Key von": "Best quality, also looks at your start image. API key from",
    "(getrennt vom Claude-Abo, Abrechnung nach Verbrauch; mit Haiku 5.5 Bruchteile eines Cents pro Verbesserung).": "(separate from a Claude subscription, pay per use; with Haiku 5.5 a fraction of a cent per improvement).",
    "API-Key": "API key", "Claude Haiku 5.5 – sehr günstig, schnell": "Claude Haiku 5.5 – very cheap, fast", "Claude Sonnet 5.5 – noch besser, teurer": "Claude Sonnet 5.5 – even better, more expensive",
    "Gespeichert.": "Saved.", "gespeichert ✓": "saved ✓",
    "HuggingFace-Zugang (optional)": "HuggingFace access (optional)",
    "Nur nötig, falls ein Modell beim Download „Zugang verweigert“ meldet. Token von huggingface.co → Settings → Access Tokens.": "Only needed if a model reports “access denied” when downloading. Token from huggingface.co → Settings → Access Tokens.",
    "Eigene Vorlage importieren": "Import your own template", "Für Profis: einen in ComfyUI per": "For pros: add a workflow saved in ComfyUI via",
    "„Export (API)“": "“Export (API)”", "gespeicherten Ablauf als eigenes Werkzeug hinzufügen.": "as your own tool.",
    "Name, z. B. Mein Flux-Workflow": "Name, e.g. My Flux workflow", "Datei wählen …": "Choose file …",
    "Keine gültige JSON-Datei.": "Not a valid JSON file.", "Das ist das normale Format. Bitte in ComfyUI „Export (API)“ verwenden.": "That is the normal format. Please use “Export (API)” in ComfyUI.",
    "Kein API-Ablauf erkannt.": "No API workflow detected.", "Sprache / Language": "Sprache / Language",
    "Die Oberfläche wird nach dem Umschalten neu geladen.": "The interface reloads after switching.",

    // Fehlerhinweise
    "→ Zu wenig Grafikspeicher. Wähle „Schnell“, ein kürzeres Video oder ein kleineres Modell.": "→ Not enough graphics memory. Choose “Fast”, a shorter video or a smaller model.",
    "→ Ein Modell fehlt. Unter „Modelle“ das Modell (erneut) installieren.": "→ A model file is missing. (Re)install the model under “Models”.",
    "→ Ein Baustein fehlt. Unter Einstellungen „ComfyUI aktualisieren“ ausführen.": "→ A component is missing. Run “Update ComfyUI” in Settings.",
    "→ Einstellungen: KI-Prompt-Helfer prüfen.": "→ Check Settings: AI prompt helper.",
    "Bitte zuerst eine Idee eintippen.": "Please type an idea first.", "Kein Claude-API-Key hinterlegt (Einstellungen).": "No Claude API key saved (Settings).",
    "Kein Ollama-Modell gewaehlt (Einstellungen).": "No Ollama model selected (Settings).", "Keine Verbindung. Laeuft Ollama bzw. bist du online?": "No connection. Is Ollama running / are you online?",
    "Ollama nicht erreichbar": "Ollama not reachable", "Zu wenig Speicherplatz": "Not enough disk space",
    "🔑 Diese Modelle sind bei HuggingFace zugangsbeschränkt.": "🔑 These models are gated on HuggingFace.",
    "Einmalig freischalten (kostenlos, ca. 2 Minuten):": "Unlock once (free, about 2 minutes):",
    "Kostenloses Konto anlegen bzw. anmelden:": "Create a free account or sign in:",
    "Auf dieser Seite auf": "On this page, click", "klicken:": ":", "Einen Zugangsschlüssel erstellen (Typ": "Create an access token (type",
    "):": "):", "Den Schlüssel hier einfügen:": "Paste the token here:", "Speichern & erneut laden": "Save & download again",

    // Einrichtung (setup.html)
    "Willkommen!": "Welcome!", "ComfyUI": "ComfyUI",
    "Easy Generate braucht": "Easy Generate needs", "– das ist die KI-Maschine, die im Hintergrund die Bilder und Videos berechnet.": "– the AI engine that computes images and videos in the background.",
    "Suche nach vorhandenen ComfyUI-Installationen …": "Looking for existing ComfyUI installations …", "Weiter": "Next",
    "Anderen Ordner auswählen …": "Choose another folder …", "ComfyUI neu installieren (empfohlen)": "Install ComfyUI fresh (recommended)",
    "Sauber, aktuell und von Easy Generate verwaltet – inklusive Updates per Knopfdruck.": "Clean, up to date and managed by Easy Generate – including one-click updates.",
    "Es wurde kein vorhandenes ComfyUI gefunden.": "No existing ComfyUI was found.", "ComfyUI installieren": "Install ComfyUI",
    "Easy Generate lädt das offizielle ComfyUI-Paket (ca. 2 GB) und richtet alles ein.": "Easy Generate downloads the official ComfyUI package (about 2 GB) and sets everything up.",
    "Deine Grafikkarte": "Your graphics card", "Installationsordner": "Installation folder", "Ändern …": "Change …",
    "Modelle aus": "Reuse models from", "mitbenutzen (spart Speicherplatz und Download)": "(saves disk space and downloads)",
    "Da hat etwas nicht geklappt": "Something went wrong", "Anderes ComfyUI wählen / neu installieren": "Choose another ComfyUI / reinstall",
    "Protokoll anzeigen": "Show log", "Bereite Installation vor …": "Preparing installation …",
    "Starte die KI im Hintergrund …": "Starting the AI engine in the background …", "Entpacke ComfyUI … (das dauert ein paar Minuten)": "Extracting ComfyUI … (this takes a few minutes)",
    "Aktualisiere ComfyUI …": "Updating ComfyUI …", "Aktualisiere Programmbibliotheken … (kann einige Minuten dauern)": "Updating libraries … (can take a few minutes)",
    "Starte ComfyUI neu, um Easy Generate zu aktualisieren …": "Restarting ComfyUI to update Easy Generate …",
    "In diesem Ordner wurde kein ComfyUI gefunden (main.py fehlt).": "No ComfyUI found in this folder (main.py missing).",
    "Zu diesem ComfyUI wurde kein Python gefunden. Wähle besser „ComfyUI neu installieren“.": "No Python was found for this ComfyUI. Better choose “Install ComfyUI fresh”.",
    "– kein Python gefunden, nicht nutzbar": "– no Python found, not usable", "Vorhandenes nutzen:": "Use existing:",
    "ComfyUI hat sich beim Start beendet.": "ComfyUI exited during startup.", "ComfyUI startet nicht (Zeitüberschreitung).": "ComfyUI does not start (timeout).",
    "Nach dem Entpacken wurde ComfyUI nicht gefunden.": "ComfyUI was not found after extracting.",
    "ComfyUI-Ordner nicht gefunden.": "ComfyUI folder not found.",
  };

  // Texte mit Zahlen/Namen
  const PAT = [
    [/^Bereit · (.+)$/, "Ready · $1"],
    [/^(.+) \(Modelle fehlen noch\)$/, "$1 (files still missing)"],
    [/^(\S+): (Keine Verbindung zum Download-Server.*|Download verweigert.*|Download unvollstaendig.*|Server antwortet mit Fehler (\d+))$/, (m, f, rest) => f + ": " + (EN[rest] || rest.replace(/^Server antwortet mit Fehler/, "Server returned error"))],
    [/^Schritt (\d+) von (\d+)$/, "Step $1 of $2"],
    [/^Arbeite: (.+)$/, "Working: $1"],
    [/^Fertig in (.+) Min\.$/, "Done in $1 min."],
    [/^(\d+) Bilder erstellen$/, "Create $1 images"],
    [/^\((\d+) Bilder bei (.+) fps\)$/, "($1 frames at $2 fps)"],
    [/^(\d+) s$/, "$1 s"],
    [/^(\d+) Vorlagen · (\d+) installiert · Größenangaben = Download beim ersten Installieren \(gemeinsame Dateien werden nur einmal geladen\)\.$/, "$1 templates · $2 installed · sizes = download on first install (shared files are only downloaded once)."],
    [/^⚠ (\d+)\/(\d+) Dateien$/, "⚠ $1/$2 files"],
    [/^Lade (\d+) Datei\(en\) · (.+)$/, "Downloading $1 file(s) · $2"],
    [/^noch ca\. (.+)$/, "about $1 left"],
    [/^· noch ca\. (.+)$/, "· about $1 left"],
    [/^ca\. (.+)$/, "approx. $1"],
    [/^(\d+(?:[.,]\d+)?) Std\.$/, "$1 h"], [/^(\d+) Min\.$/, "$1 min"], [/^(\d+) Sek\.$/, "$1 s"],
    [/^(.+) – klicken zum Ändern$/, "$1 – click to change"],
    [/^Noch kein Video-Modell installiert$/, "No video model installed yet"],
    [/^(\S+) Noch kein Video-Modell installiert$/, "$1 No video model installed yet"],
    [/^(\S+) Noch kein Bild-Modell installiert$/, "$1 No image model installed yet"],
    [/^Bitte zuerst „(.+)“ auswählen\.$/, "Please choose “$1” first."],
    [/^Bild-Upload fehlgeschlagen \((.+)\)$/, "Image upload failed ($1)"],
    [/^„(.+)“ entfernen\?$/, "Remove “$1”?"],
    [/^„(.+)“ hinzugefügt\.$/, "“$1” added."],
    [/^⏳ Richte „(.+)“ ein …$/, "⏳ Setting up “$1” …"],
    [/^✅ „(.+)“ ist bereit!(.*)$/, "✅ “$1” is ready!$2"],
    [/^ \((\d+) Datei\(en\) aus dem Download-Ordner eingesortiert\)$/, " ($1 file(s) moved from your Downloads folder)"],
    [/^⬇ „(.+)“: (\d+) Datei\(en\) werden geladen\.(.*)$/, "⬇ “$1”: downloading $2 file(s).$3"],
    [/^ (\d+) vorhandene eingesortiert\.$/, " $1 existing file(s) sorted in."],
    [/^🗑 „(.+)“ entfernt(.*)\.$/, "🗑 “$1” removed$2."],
    [/^ – (.+) frei$/, " – $1 freed"],
    [/^Vorlage nicht gefunden: (.+)$/, "Template not found: $1"],
    [/^Ollama läuft ✓ · (\d+) Modell\(e\) installiert$/, "Ollama is running ✓ · $1 model(s) installed"],
    [/^✅ (.+) wird jetzt für den Prompt-Helfer verwendet\.$/, "✅ $1 is now used for the prompt helper."],
    [/^✅ (.+) geladen und als Prompt-Helfer eingestellt\.$/, "✅ $1 downloaded and set as prompt helper."],
    [/^⬆ Update (.+) verfügbar – installieren$/, "⬆ Update $1 available – install"],
    [/^⬇ Update wird geladen … (\d+)%$/, "⬇ Downloading update … $1%"],
    [/^Version (.+) ist verfügbar\.$/, "Version $1 is available."],
    [/^Version (.+)$/, "Version $1"],
    [/^Schnell-Modus \((.+)\)$/, "Fast mode ($1)"],
    [/^\(gespeichert (.+) – leer lassen zum Behalten\)$/, "(saved $1 – leave empty to keep)"],
    [/^(\d+) Modell\(e\) gefunden\.$/, "$1 model(s) found."],
    [/^Lade Ollama herunter … (.+)$/, "Downloading Ollama … $1"],
    [/^Lade ComfyUI für (.+) herunter …$/, "Downloading ComfyUI for $1 …"],
    [/^Erkannt: (.+)$/, "Detected: $1"],
    [/^Vorhandenes nutzen: (.+)$/, "Use existing: $1"],
    [/^Freier Speicher dort: (\d+) GB · ComfyUI braucht ca\. 6 GB, jedes Video-Modell zusätzlich 20–60 GB\.$/, "Free space there: $1 GB · ComfyUI needs about 6 GB, each video model another 20–60 GB."],
    [/^Zu wenig Speicherplatz: benoetigt (.+) GB, frei (.+) GB\.$/, "Not enough disk space: $1 GB needed, $2 GB free."],
    [/^(\d+) s · (.*)$/, "$1 s · $2"],
    [/^Starte die KI im Hintergrund … \((\d+) s\)$/, "Starting the AI engine … ($1 s)"],
  ];

  let lang = "de";
  try { lang = localStorage.getItem("eg_lang") || "de"; } catch (e) {}

  function tr(s) {
    if (lang !== "en" || !s) return s;
    const lead = s.match(/^\s*/)[0], trail = s.match(/\s*$/)[0];
    const core = s.trim().replace(/\s+/g, " ");
    if (!core) return s;
    if (Object.prototype.hasOwnProperty.call(EN, core)) return lead + EN[core] + trail;
    for (const [re, rep] of PAT) if (re.test(core)) return lead + core.replace(re, rep) + trail;  // rep kann Text oder Funktion sein
    // Mehrzeilige Meldungen: Zeile für Zeile
    if (core.includes("→") || /\n/.test(s)) {
      const parts = s.split(/(\n+)/).map(p => /\n/.test(p) ? p : (p.trim() ? tr(p) : p));
      return parts.join("");
    }
    return s;
  }
  function walk(root) {
    if (lang !== "en" || !root) return;
    if (root.nodeType === 3) { const v = tr(root.nodeValue); if (v !== root.nodeValue) root.nodeValue = v; return; }
    if (root.nodeType !== 1 || /^(SCRIPT|STYLE|TEXTAREA|CODE|PRE)$/.test(root.tagName)) {
      if (root.nodeType === 1 && root.tagName === "TEXTAREA") attrs(root);
      return;
    }
    attrs(root);
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let n;
    while ((n = w.nextNode())) {
      if (n.nodeType === 1) { attrs(n); continue; }
      const p = n.parentElement;
      if (p && /^(SCRIPT|STYLE|TEXTAREA|CODE|PRE)$/.test(p.tagName)) continue;
      const v = tr(n.nodeValue); if (v !== n.nodeValue) n.nodeValue = v;
    }
  }
  function attrs(el) {
    for (const a of ["placeholder", "title"]) {
      const v = el.getAttribute && el.getAttribute(a);
      if (v) { const t = tr(v); if (t !== v) el.setAttribute(a, t); }
    }
  }
  function start() {
    if (lang !== "en") return;
    document.documentElement.lang = "en";
    walk(document.body);
    new MutationObserver(ms => {
      for (const m of ms) {
        if (m.type === "characterData") walk(m.target);
        else if (m.type === "attributes") attrs(m.target);
        else m.addedNodes.forEach(walk);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["placeholder", "title"] });
  }
  window.EG_I18N = {
    get lang() { return lang; },
    tr,
    setLang(l, reload = true) {
      lang = l === "en" ? "en" : "de";
      try { localStorage.setItem("eg_lang", lang); } catch (e) {}
      if (window.easyApp && window.easyApp.setLang) window.easyApp.setLang(lang);
      if (reload) location.reload();
    },
    // Sprache aus dem Programm übernehmen (falls dort anders eingestellt)
    async sync() {
      if (window.easyApp && window.easyApp.getLang) {
        try {
          const l = await window.easyApp.getLang();
          if (l && l !== lang) { lang = l; try { localStorage.setItem("eg_lang", l); } catch (e) {} location.reload(); }
        } catch (e) {}
      }
    },
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
  window.EG_I18N.sync();
})();
