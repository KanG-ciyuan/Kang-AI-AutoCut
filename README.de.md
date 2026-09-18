# Kang AI-AutoCut

**Local-first Agentic AI Video Production System**

**Lokales, agentisches KI-Videoproduktionssystem**

**Languages:** [English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Bahasa Indonesia](README.id.md) | Deutsch | [Español](README.es.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3-3776AB)](README.md#installation)
[![FFmpeg](https://img.shields.io/badge/ffmpeg-required-007808)](README.md#installation)
[![Local-first](https://img.shields.io/badge/local--first-yes-4c1)](docs/decisions/ADR-0007-local-first.md)
[![Agent-oriented](https://img.shields.io/badge/agent--oriented-yes-8957e5)](README.md#use-with-an-ai-agent)
[![Tests](https://img.shields.io/badge/tests-1062%20passing-brightgreen)](README.md#installation)
[![macOS](https://img.shields.io/badge/macOS-tested-000000)](README.md#installation)
[![Baseline](https://img.shields.io/badge/baseline-pre--third--SKU-orange)](README.md#frozen-baseline)

*Die Badges sind statisch und beschreiben die eingefrorene Baseline. Dieses
Repository führt keinen CI-Workflow aus, und die Zahlen in den Badges sind kein
Live-Status.*

Kang AI-AutoCut ist ein Agent-orientiertes Videoproduktionssystem, kein
FFmpeg-Stitching-Skript. Es nimmt autorisiertes Rohmaterial und ein klar
formuliertes kreatives Ziel entgegen und führt die Arbeit durch **acht
Produktionsstufen** — Materialverständnis, Schnittintelligenz, narrative Planung,
Timeline-Konstruktion, Bild-Finishing, Typografie, Audio, Mastering, Review und
Reparatur — mit **menschlicher Freigabe als ausdrücklichem Gate**.

Es läuft auf Ihrem eigenen Rechner. Der Produktionskontrollpfad und die
Medienverarbeitung sind local-first; externe KI-Anbieter erhalten ausschließlich
die Eingaben, die für freigegebene Intelligenz- oder Generierungsaufgaben
ausdrücklich erforderlich sind. Jede kreative Entscheidung wird aufgezeichnet, und
das System weigert sich, einen Erfolg zu melden, den es nicht messen kann.

> **Kommerziell zuerst, von der Architektur her erweiterbar.** Kommerzielle Werbung
> ist der erste produktionsvalidierte Workflow. Die Architektur ist darauf
> ausgelegt, sich auf breitere Creator- und Medien-Workflows auszuweiten.

```
Raw Footage
    ↓
Understand  →  Plan  →  Edit
    ↓
Picture  ·  Typography  ·  Audio
    ↓
Assemble & Master
    ↓
Review  →  Repair  →  Human Approval
    ↓
Final Video
```

---

## Warum Kang AI-AutoCut

Die meisten KI-Videowerkzeuge erzeugen **ein Video, einmal**, in einem Chatfenster.
Ein erneuter Lauf liefert ein anderes Video, und nichts am Prozess ist
nachvollziehbar.

Kang AI-AutoCut behandelt Videoproduktion als **Engineering-Pipeline**:

| Gewöhnliche KI-Videoausgabe | Kang AI-AutoCut |
|---|---|
| Einmaliges Ergebnis, schwer wiederholbar | Ein wiederverwendbarer Workflow, den Sie erneut ausführen |
| Entscheidungen leben in einem Chat-Protokoll | Jede Entscheidung ist ein aufgezeichnetes Artefakt |
| Ein Fehlschlag bedeutet, von vorn zu beginnen | Jobs werden ab der Stufe fortgesetzt, die angehalten hat |
| „Es sieht fertig aus“ ist die einzige Prüfung | Die Ausgabe wird gemessen: Frames, schwarze Frames, Freezes, Loudness, True Peak, Master-Hash |
| Ein Modell kann einen Schritt stillschweigend überspringen | Eine Stufe **kann nicht bestehen, ohne die Fähigkeit zu benennen, die sie ausgeführt hat** |
| Menschliches Urteilsvermögen bleibt unsichtbar | Menschliche Beiträge erfolgen an benannten Gates und werden protokolliert |
| Ihr Material wird zu einem Anbieter hochgeladen | Die Verarbeitung ist local-first; Anbieter erhalten nur die Eingaben, die eine Aufgabe erfordert |

---

## Was Sie bauen können

**Derzeit produktionsvalidiert:**

- **Kommerzielle Werbung und E-Commerce-Produktvideos** — der erste Workflow, der
  von Anfang bis Ende durchgeführt wurde, einschließlich der Verifikation des
  Delivery-Masters.
- **Kurzformatige Produktinhalte für Social Media** — vertikale, kurze
  Werbeschnitte, die dieselben acht Stufen verwenden.

**Richtungen, in die die Architektur erweitert werden soll** — *noch nicht
produktionsvalidiert*:

- Videos von Creators und Self-Media-Anbietern
- Produktdemonstrationen und Erklärinhalte
- Marken- und Kampagneninhalte
- weitere strukturierte Videoproduktions-Workflows

Das System ist heute kommerziell ausgerichtet. Nichts hier behauptet, dass jede
Videokategorie bereits unterstützt wird, und ein Framework für Inhaltsmodi
existiert noch nicht.

---

## So funktioniert es

### Was Sie tun

1. **Rohmaterial hinzufügen** — richten Sie das System auf ein Verzeichnis mit
   Quellvideos.
2. **Das Ziel benennen** — Produkt, Plattform, Sprache, Zieldauer und das, was das
   Video behaupten darf und was nicht.
3. **Den Agenten die Pipeline ausführen lassen** — er arbeitet die Stufen ab und
   hält an, wenn er Sie braucht.
4. **Die Gates beantworten** — Texte freigeben, ein fehlendes Artefakt liefern oder
   eine kreative Entscheidung treffen.
5. **Das fertige Video freigeben** — ein namentlich genannter Mensch gibt den
   Master frei. Diese Freigabe ist eine eigene Entscheidung, getrennt vom Review,
   und sie benennt genau den Master, den sie freigibt.

### Was das System tut

Der Produktionskontrollpfad (der Fast Path) führt **acht semantische Stufen** aus:

| # | Stufe | Was geschieht |
|---|---|---|
| 1 | **PREPARE** | Quellinventar mit unveränderlichen Digests pro Datei |
| 2 | **UNDERSTAND SHOTS** | Medien werden analysiert; gemessene Zeitstempel werden auf ein CFR-Analyseraster abgebildet, um echte visuelle Segmente zu finden |
| 3 | **PLAN THE EDIT** | Timeline-Bereiche werden gegen beobachtbare Handlung validiert — ein Schnitt, der den Beginn der Handlung oder deren Ergebnis verfehlt, wird abgelehnt |
| 4 | **FINISH THE PICTURE** | Quellbereiche werden über die Timebase-Invariante extrahiert, gemessen und pro Shot wird eine KEEP / REVIEW / CORRECT-Entscheidung getroffen |
| 5 | **PLAN THE WORDS** | Die Erzählabdeckung (Narration Coverage) wird **vor** jeglicher bezahlter Voice-Arbeit geprüft; anschließend wird der Bildschirmtext gerendert |
| 6 | **BUILD THE AUDIO** | FIT / SYNC / RHYTHM werden getrennt beurteilt; danach wird der Mix erstellt und **gemessen** |
| 7 | **ASSEMBLE & MASTER** | Delivery-Master wird erzeugt und anschließend gegen die Datei selbst verifiziert |
| 8 | **REVIEW & REPAIR** | Alle Review-Dimensionen werden beurteilt; das Urteil wird abgeleitet; menschliches Freigabe-Gate |

### Wie die beiden Sichten einander zugeordnet sind

```
USER VIEW                          SYSTEM VIEW (8 stages)
─────────────────────────────      ──────────────────────────────────────
1  add raw footage            →    PREPARE
2  state the goal             →    (job manifest + brief)
3  understand the material    →    UNDERSTAND SHOTS
4  build the editing strategy →    PLAN THE EDIT
5  construct the timeline     →    PLAN THE EDIT
6  finish the picture         →    FINISH THE PICTURE
7  titles / copy / typography →    PLAN THE WORDS
8  voice / music / audio      →    BUILD THE AUDIO
9  assemble and master        →    ASSEMBLE & MASTER
10 review and repair          →    REVIEW & REPAIR
11 human approval             →    REVIEW & REPAIR (human release gate)
12 final video                →    delivered master
```

### Stufen halten bewusst an

Wenn eine erforderliche Eingabe fehlt, **hält der Lauf an und benennt, wer handeln
muss**. Das ist ein Producer Gate (Produzenten-Gate: das System hält bewusst an, bis ein deklarierter Produzent ein Artefakt bereitstellt oder freigibt):

```
   Stage ──▶ [ PRODUCER GATE ] ──▶ Stage
                 │
                 ├─ which artifact is missing
                 ├─ which producer is responsible (AUTO / CODEX / HUMAN / ADAPTER)
                 ├─ the input and output contract
                 ├─ the procedure to follow
                 ├─ the evidence required
                 └─ what must become true to resume
```

**Ein Gate ist kein Fehler.** Es bedeutet, dass das System es ablehnt, eine
kreative Entscheidung zu erfinden oder Arbeit zu behaupten, die es nicht geleistet
hat. Manche Stufen sind automatisiert; andere brauchen legitimerweise einen
Agenten, einen Provider-Adapter oder einen Menschen. Die englischen Formulierungen
„generate or prepare“, „Agent supplies“ und „job-authored when required“ werden in
dieser README bewusst verwendet — auf Deutsch entsprechend „erzeugen oder
bereitstellen“, „der Agent stellt bereit“ und „bei Bedarf vom Job verfasst“.

---

## Aktuelle Fähigkeiten

### Heute verfügbar und verifiziert

| Fähigkeit | Hinweise |
|---|---|
| Import von Quellmaterial und unveränderliches Inventar | SHA-256 pro Datei, vor der Verwendung erneut verifiziert |
| VFR-sicheres Medienverständnis | gemessene Zeitstempel werden auf ein CFR-Analyseraster abgebildet |
| Visuelle Segmentierung | läuft auf dem Raster, das die Engine tatsächlich dekodiert |
| Validierung von Timeline-Bereichen | lehnt Schnitte ab, die beobachtbare Handlung verfehlen |
| Extraktion von Quellbereichen | jeder Bereich wird aus einem gemessenen Zeitstempel aufgelöst |
| Bildausführung | erzeugt ein echtes Video-Artefakt, das danach erneut gemessen wird |
| Erzählabdeckung (Narration Coverage) | läuft vor jeder bezahlten Voice-Generierung |
| Typografie-Rendering | echte Ausgabe aus dem Layout und den Schriften des jeweiligen Jobs |
| Audio-Mixing und Mastering | echter Mix mit gemessener Loudness, True Peak und Clipping |
| Packaging und finaler Master | `final/master.mp4` plus gemessene technische QA |
| Review-Vertrag und Release-Urteil | jede Dimension wird genau einmal beurteilt; das Urteil wird abgeleitet, nicht behauptet |
| Gezielte Reparaturplanung | auf die betroffene Ebene begrenzt |
| Menschliches Release-Gate | eine eigenständige Entscheidung, die den Master benennt, den sie freigibt |
| Interventions-Ledger | wird automatisch geschrieben, wann immer ein Gate einen Lauf anhält |
| Fortsetzen und Invalidierung | setzt an der ersten unvollständigen Stufe fort; die Invalidierung einer Stufe öffnet alles Nachgelagerte erneut |
| Integritätsprüfung des Masters | Digest wird neu berechnet; ein gelöschter oder veränderter Master besteht die Verifikation nicht |

### Durch Gate gehalten / vom Job verfasst

Diese laufen, aber das Artefakt, das sie konsumieren, wird pro Job bereitgestellt —
von einem Agenten, einem Adapter oder einem Menschen:

| Fähigkeit | Was weiterhin bereitgestellt werden muss |
|---|---|
| Schreibgeschützte Bildmessung | in diesem Repository wird kein Messwerkzeug mitgeliefert |
| Schutz der Produktauthentizität | ebenso; seine Toleranzprüfungen sind noch nicht mit echten Daten gelaufen |
| KEEP / REVIEW / CORRECT-Entscheidung | die Entscheidung läuft; nichts hier reagiert auf ein `CORRECT` |
| Verifikation des Audioprogramms (FIT / SYNC / RHYTHM) | die Voice-Platzierung, die sie konsumiert |
| Voice- / Musikgenerierung | wird von einem Provider-Adapter bereitgestellt; **nicht eingebaut** |

### Geplant / erweiterbar

Nicht implementiert und nicht beansprucht: ein automatisierter kommerzieller
Reviewer, generische Backend-Compiler, eine Artefakt-Registry, eine Job-Queue, ein
unbeaufsichtigter Ein-Befehl-Runner und breitere Workflows für Inhaltsmodi.

---

## Verwendung mit einem KI-Agenten

Kang AI-AutoCut ist darauf ausgelegt, **mit einem Agenten betrieben zu werden** —
mit einem Modell, das auf Ihrem Dateisystem und in Ihrer Shell handeln kann, nicht
mit einem reinen Chat-Modell.

Es ist **an kein einzelnes Agent-Produkt gebunden**. Die Kompatibilität richtet
sich nach den Fähigkeiten:

| Der Agent muss in der Lage sein, … | Warum |
|---|---|
| Repository-Dateien zu lesen | `README.md`, `PROJECT_IDENTITY.md`, `AGENTS.md` zu befolgen |
| Shell-Befehle auszuführen | FFmpeg, FFprobe, Python, die Testsuite |
| lokale Dateien zu lesen und zu schreiben | Job-Status, Artefakte, Medien-Staging |
| Python- und FFmpeg-Workflows auszuführen | jede Stufe ist lokal und deterministisch |
| strukturierte JSON-Artefakte zu verstehen | Jobs, Reviews, Evidenzen, Manifeste |
| **an einem Producer Gate anzuhalten** | und Sie zu fragen, statt zu raten |
| die Grenzen des Repositories zu respektieren | Medien außerhalb von Git, keine Secrets, keine maschinengebundenen Pfade |

Beispiele für leistungsfähige Agenten sind Codex, DeepSeek Harness, Claude Code und
weitere Coding- oder Computer-Use-Agenten. **Dies sind Beispiele, keine
Voraussetzungen und keine empfohlenen Integrationen.**

**Ein reines Chat-Modell kann dieses System nicht betreiben.** Ohne Dateisystem-
und Shell-Zugriff kann es die Pipeline nicht ausführen; es kann nur über sie
sprechen.

### Interne Governance vs. öffentliche Kompatibilität

Das sind zwei verschiedene Dinge, und beide gelten:

- **Intern** nutzt der validierte Produktions-Workflow **Codex als übergeordneten
  Supervisor.** Dort liegt die kreative Autorität, und das System ist so gebaut,
  dass keine deterministische Komponente entscheidet, was ein Video aussagen soll.
- **Nach außen** bleibt das Repository **Agent-agnostisch**, soweit es die
  Architektur zulässt. Nichts im Kontrollpfad ist fest an den Agenten eines
  einzelnen Anbieters gebunden.

---

## Schnellstart für Agenten

Geben Sie einem leistungsfähigen Coding-Agenten die Repository-URL und eine
Aufforderung wie diese:

```text
Installiere Kang AI-AutoCut auf diesem Computer gemäß den Anweisungen im
Repository.

Repository: https://github.com/KanG-ciyuan/Kang-AI-AutoCut

Bevor du etwas änderst:
1. Lies README.md, PROJECT_IDENTITY.md und AGENTS.md.
2. Prüfe die Umgebung: Python, FFmpeg/FFprobe und die Python-Pakete, die der
   Code tatsächlich importiert.
3. Melde, was fehlt. Installiere nichts, was ich nicht freigegeben habe.

Dann:
4. Konfiguriere den lokalen Workspace und den Medien-Root ausschließlich über
   logische Rollen und Umgebungsvariablen. Halte Medien außerhalb von Git.
5. Schreibe niemals einen API-Schlüssel, ein Token oder Zugangsdaten in eine
   versionierte Datei, ein Log oder einen Commit.
6. Führe die Selbsttests des Repositories aus, bevor du meinen ersten Video-Job
   erstellst.

Wenn wir einen Job starten:
7. Führe den Produktionskontrollpfad aus und halte an jedem Producer Gate an.
8. Frage mich, wenn ein Gate eine menschliche Entscheidung oder eine kreative
   Freigabe braucht.
9. Erfinde keine Texte, keine Art Direction und keine Aussagen in meinem Namen.
```

**Was der Agent weiterhin von Hand erledigen muss.** Die Installation ist heute
*nicht* vollständig automatisiert: Es gibt keinen Installer, kein
Packaging-Manifest und keine deklarierte Dependency-Lockdatei. Der Agent muss die
Umgebung prüfen, die von Ihnen freigegebenen Voraussetzungen installieren und
lokale Pfade konfigurieren. Die nachfolgende README listet genau auf, was
verifiziert ist, und das Repository enthält keine `pyproject.toml` und keine
`requirements.txt` — das ist eine bekannte Dokumentationslücke, kein versteckter
Schritt.

---

## Installation

### Verifizierte Voraussetzungen

| Voraussetzung | Status |
|---|---|
| **Python 3** | verifiziert mit 3.11.15. Das Repository deklariert keine Mindestversion — betrachten Sie das als Lücke. |
| **FFmpeg und FFprobe** | erforderlich. Verifiziert mit ffmpeg/ffprobe 9.0.1. |
| **`numpy`** | wird vom Modul für Medienverständnis benötigt |
| **`Pillow`** | wird vom Ausführungsadapter für Typografie benötigt |
| **macOS** | verifiziert auf macOS arm64. Windows und Linux sind **nicht** verifiziert. |

Es existiert keine `pyproject.toml`, keine `setup.py` und keine `requirements.txt`,
daher werden hier keine Versions-Pins behauptet. Lesen Sie die Imports, statt einer
Lockdatei zu vertrauen, die es nicht gibt.

### Einrichtung

```sh
git clone https://github.com/KanG-ciyuan/Kang-AI-AutoCut.git
cd AI-AutoCut

# Local configuration: resolves environment variables, never machine paths
cp config/examples/autocut.env.example .env.local
# edit .env.local: set AUTOCUT_MEDIA_ROOT and AUTOCUT_WORKSPACE
```

### Installation überprüfen

```sh
# Full offline regression — no network, no media required
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests

# End-to-end execution proof — builds its own media, produces a real master
python3 scripts/run_pre_exam_proof.py --job-root /tmp/pre-exam-proof
```

Der Proof ist bewusst zweiphasig: Er hält am menschlichen Release-Gate an,
schreibt die Freigabe unter Benennung des **verifizierten** Masters und wird
anschließend bis zum Abschluss fortgesetzt. Er schlägt fehl, wenn der Master
gelöscht oder verändert wird.

### Ihr erster Job

```sh
# 1. Initialize a job (generic: any product, any source count)
python3 -m src.ai_autocut.job_foundation \
    --job-id my-first-job \
    --product-name 'My Product' \
    --source-root /path/to/footage \
    --workspace /path/to/job-workspace

# 2. Run the production control path
python3 -m src.ai_autocut.fast_path --job-root /path/to/job-workspace
```

Der Lauf hält am ersten Producer Gate an und teilt Ihnen mit, was als Nächstes
benötigt wird.

Vollständige Anleitung:
[`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md).

---

## Agent- und LLM-Kompatibilität

Vier verschiedene Ebenen lassen sich leicht verwechseln. Das System hält sie
bewusst auseinander:

| Ebene | Was sie ist | In diesem Projekt |
|---|---|---|
| **LLM** | ein Schlussfolgerungsmodell | austauschbar, sofern überhaupt ein Modell verwendet wird |
| **Agent** | ein Modell **plus Werkzeuge**, das auf diesem Repository handeln kann | erforderlich, um das System zu betreiben |
| **Provider** | ein optionaler externer Dienst für Generierung oder Intelligenz | optional anbindbar; **nicht eingebaut** |
| **Ausführungs-Engine** | die deterministische lokale Python/FFmpeg-Pipeline | die einzige Instanz, der zugetraut wird zu melden, dass ein Schritt erfolgreich war |

**Kein Vendor-Lock-in, konstruktionsbedingt.** Der Kontrollpfad ruft
deterministische lokale Module auf. Wo ein Modell oder ein Anbieter beteiligt ist,
ist er ein Produzent, der ein Artefakt über einen deklarierten Vertrag bereitstellt
— ein Austausch des Modells oder Anbieters verändert die Pipeline daher nicht.

**Doch Kompatibilität ist eine Frage der Fähigkeiten, nicht der Marke.** Ein
Modell, das keine Dateien lesen und schreiben, keine Shell-Befehle ausführen und
kein Gate respektieren kann, kann dieses System nicht betreiben, so leistungsfähig
es beim Schlussfolgern auch sein mag.

---

## Audio- und KI-Provider-Architektur

Das aktuelle Repository führt **lokales Mixing und Mastering** für die Audio-Assets
durch, die der Job bereitstellt. Es ruft bewusst **keinen** Voice-, Musik- oder
Soundeffekt-Anbieter auf. Audio-Synthese ist hier nicht implementiert.

```
External Audio Provider   (future Adapter layer — NOT built in)
        ↓
  generated VO / BGM / SFX assets
        ↓
  job-local audio assets
        ↓
  Audio Program  →  local Mix  →  local Master
                     (measured: loudness, true peak, clipping)
```

**Was heute existiert:** Die Stufe `BUILD THE AUDIO` konsumiert job-lokale
Audio-Assets, mischt sie mit FFmpeg gegen die Ziele des jeweiligen Jobs und misst
das Ergebnis. Sie lehnt einen Mix ab, dessen Sample-Peak die Vollaussteuerung
erreicht.

**Was nicht existiert:** jegliche eingebaute Anbieterintegration. Es gibt keine
Ein-Klick-Voice-Generierung, und dieses Repository enthält keinen Provider-Client.

**Historischer Kontext, korrekt eingeordnet.** Voice-over wurde in früheren
validierten Produktionsarbeiten über **MiniMax `speech-2.8-hd`** erzeugt, und ein
vorangegangenes Job-Manifest verzeichnet **Doubao Seed Audio 1.0**. Beides sind
**historisch evaluierte Experimente**, dokumentiert in
[`docs/providers/audio-provider.md`](docs/providers/audio-provider.md) — keine
aktuellen, eingebauten Produktionsintegrationen. Ihre Erkenntnisse haben die
Audio-Policy geprägt; ihre Clients sind nicht Teil dieses Repositories.

In diesem Repository erscheint nirgends ein Schlüssel-, Token- oder
Zugangsdatenwert. Zugangsdaten werden ausschließlich über den Namen der
Umgebungsvariablen referenziert.

---

## Kommerzieller Nutzen und Produktionsnutzen

Der Nutzen liegt in der Architektur, nicht in einem Versprechen über Ergebnisse:

- **Ein wiederverwendbarer Workflow, keine einmalige Ausgabe.** Führen Sie
  denselben Produktionsprozess für das nächste Produkt aus, statt ein neues
  Gespräch zu beginnen.
- **Wiederholbare Produktion.** Dieselben Stufen, Verträge und Gates gelten für
  jeden Job, sodass Prozesswissen sich ansammelt, statt zu verfliegen.
- **Prüfbare kreative Entscheidungen.** Jede Wahl ist ein Artefakt mit Evidenz,
  sodass ein Review nach dem *Warum* fragen kann, nicht nur nach dem *Was*.
- **Fortsetzbare Jobs.** Ein Job, der durch ein Gate oder einen Fehler angehalten
  wurde, wird ab der Stufe fortgesetzt, an der er angehalten hat, statt von vorn.
- **Deterministische Ausführung.** Rendering, Extraktion und Messung sind lokal und
  reproduzierbar; die Behauptung eines Modells ist niemals die Evidenz.
- **Das Quellmaterial ist wiederverwendbar.** Gutes Material kann mehrere Varianten
  bedienen, ohne dass neu gedreht werden muss.
- **Strukturiertes Review und strukturierte Reparatur.** Die Reparatur ist auf die
  betroffene Ebene gerichtet, nicht auf eine vollständige Neuerzeugung — ein
  freigegebener Schnitt wird also nicht stillschweigend ersetzt.
- **Messbare Validierung der Ausgabe.** Frame-Anzahl, schwarze Frames, eingefrorene
  Frames, Loudness, True Peak und der Master-Digest werden aus der Datei gemessen.
- **Menschliche Eingriffe sind sichtbar.** Das System protokolliert, wann ein Gate
  geöffnet wurde, wer gehandelt hat und wann es aufgelöst wurde.
- **Lokale Hoheit über die Medien.** Quellmedien werden nicht automatisch in eine
  Cloud-Pipeline hochgeladen; Kontrollpfad und Medienverarbeitung bleiben auf Ihrem
  Rechner, und ein freigegebener externer Anbieter erhält nur die Eingaben, die
  eine Aufgabe ausdrücklich erfordert.
- **Flexibilität bei den Anbietern.** Die Generierung liegt hinter einer Grenze,
  sodass die Wahl eines Anbieters austauschbar ist.

Was dies **nicht** behauptet: garantierte Qualität, garantierte Conversion- oder
Umsatzergebnisse oder eine garantierte Verkürzung der Schnittzeit. Nichts in diesem
Repository belegt das.

---

## Architektur

| Dokument | Inhalt |
|---|---|
| [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md) | Interaktionsmodell, Produktionskontrollpfad, Reifegrad |
| [`docs/architecture/supervisor-authority.md`](docs/architecture/supervisor-authority.md) | die Zuständigkeitsgrenze des Codex-Supervisors |
| [`docs/architecture/backend-neutral-timeline.md`](docs/architecture/backend-neutral-timeline.md) | eine Timeline, drei Backends |
| [`docs/architecture/operations.md`](docs/architecture/operations.md) | Pfadrollen, ASCII-Staging, Verifikationsregel |
| [`docs/contracts/`](docs/contracts/) | eingefrorene Verträge |
| [`docs/policies/`](docs/policies/) | Policy für Schnitt, Shots, Typografie, Audio und Review |
| [`docs/decisions/`](docs/decisions/) | Architecture Decision Records |
| [`docs/audit/production-chain-manifest.md`](docs/audit/production-chain-manifest.md) | Verdrahtung und Reifegrad je Fähigkeit |
| [`docs/audit/execution-runbook.md`](docs/audit/execution-runbook.md) | wie jede Grenze ausgeführt wird |
| [`docs/audit/gate-g0-history.md`](docs/audit/gate-g0-history.md) | wie die eingefrorene Baseline erreicht wurde |

### Repository-Struktur

```
src/ai_autocut/          production code
  fast_path.py             the eight-stage control path
  producer_registry.py     every required artifact and its producer
  execution_contracts.py   the four execution boundaries
  execution_adapters.py    job-scoped picture / typography / audio / packaging
  timebase_adapter.py      the source-timestamp invariant
  media_probe.py           measured facts about a real media file
  ...                      contracts, policies, validators

tests/                   offline regression suite
schemas/                 frozen contracts and the Gold manifest
docs/                    architecture, contracts, policies, decisions, audits
scripts/                 the execution proof and the local-env wrapper
examples/                example job shape
config/examples/         configuration template
```

---

## Local-First-Design

Local-First ist eine Anforderung, kein vorübergehender Zustand. Der
Produktionskontrollpfad und die gesamte Medienverarbeitung laufen auf dem lokalen
Rechner, mit Python, FFmpeg/FFprobe und dem lokalen Dateisystem, in
deterministischer Orchestrierung. Freigegebene externe KI-APIs dürfen für
ausgewählte Intelligenz- oder Generierungsaufgaben verwendet werden; sie sind
niemals der Kontrollpfad. Cloud-Infrastruktur — Objektspeicher, Serverplattformen,
verteilte Worker, Dashboards, Benutzerkonten — fehlt bewusst. Siehe
[ADR-0007](docs/decisions/ADR-0007-local-first.md).

In diesem Repository erscheint kein maschinengebundener absoluter Pfad. Jeder
Laufzeitort ist eine logische Rolle, die aus einer Umgebungsvariablen aufgelöst
wird; siehe [`docs/architecture/operations.md`](docs/architecture/operations.md)
und [`config/examples/autocut.env.example`](config/examples/autocut.env.example).

---

## Aktueller Status

| | |
|---|---|
| Eingefrorene Baseline | `pre-third-sku-blind-v1` → `b65a73b53040bd1ff5defe25e624a28f623b6847` |
| Freeze-Status | `CLOSED_AND_FROZEN` |
| Exam-Gültigkeit | `PASS_WITH_EXPLICIT_PRODUCER_GATES` |
| Nächste geplante Produktionsphase | Third-SKU-Blind-Exam — **nicht begonnen** |

Ein funktionierender **durch Gates geführter Produktionskontrollpfad** existiert und
hat einen echten, unabhängig verifizierten Delivery-Master erzeugt. Er ist kein
unbeaufsichtigter Ein-Klick-Editor und behauptet das auch nicht.

---

## Bekannte Einschränkungen

- **Kein unbeaufsichtigter Ein-Befehl-Editor.** Producer Gates halten den Lauf
  konstruktionsbedingt an, und einige benötigen einen Menschen oder einen Agenten.
- **Kein automatisierter kommerzieller Reviewer.** Der Review-Vertrag hält ein
  Urteil fest; er erzeugt keines.
- **Bildmessung und Produktschutz sind vom Job verfasst.** Hier wird kein
  Messwerkzeug mitgeliefert, und die Toleranzprüfungen des Schutzes sind noch nicht
  mit echten Daten gelaufen — das Gate hat nachweislich abgelehnt, aber noch nicht
  bewertet.
- **Der `CORRECT`-Zweig der Bildverarbeitung hat noch nie ausgelöst** — in keinem
  Produktionslauf.
- **Kein eingebauter Audio-Anbieter.** Die Synthese ist nicht implementiert; die
  Pipeline konsumiert job-lokale Assets.
- **Typografie belegt die Ausführung, nicht die Art Direction.** Es gibt keinen
  Planer für die Hierarchie des Bildschirmtexts und keine Validierung von
  Produktverdeckungen; ein Job liefert sein eigenes Layout.
- **Der Ausführungs-Proof verwendet erzeugtes lokales Audio.** Er belegt den
  Mixing- und Mastering-Pfad, nicht eine echte Voice-Performance.
- **Keine Artefakt-Registry und keine Job-Queue.** Große Staging-Daten werden von
  Hand aufgeräumt.
- **Keine generischen Backend-Compiler.** `compile_for_backend` wirft für jedes
  Backend einen Fehler; die Ausführung erfolgt stattdessen über job-spezifische
  Adapter.
- **Kein deklariertes Dependency-Manifest.** Es existiert keine `pyproject.toml`
  und keine Lockdatei.
- **Nur auf macOS verifiziert.** Windows und Linux sind ungetestet.
- **Erfasst, ungelöst:** laufbewusste visuelle Segmentierung (C-01) und
  automatische Verifikation der ausgewählten Bereiche („needs vision“).

---

## Roadmap

1. **Den Third-SKU-Blind-Exam gegen `pre-third-sku-blind-v1` ausführen.**
2. Die finale Qualität, die Häufigkeit von Producer Gates und menschliche Eingriffe
   messen.
3. Die Evidenz aus dem Blind-Lauf nutzen, um zu entscheiden, welche verbleibenden
   vom Job verfassten Fähigkeiten als Nächstes automatisiert werden sollten.

Die eingefrorene Baseline soll **als eingefroren** untersucht werden: Vor dem
Blind-Lauf ist keine Automatisierungsarbeit für die Zeit vor dem Exam eingeplant,
damit das Exam das abgenommene System misst und nicht ein System, das sich noch
unter ihm verändert.

---

## Eingefrorene Baseline

```
tag             pre-third-sku-blind-v1
target commit   b65a73b53040bd1ff5defe25e624a28f623b6847
```

**Was „eingefroren“ hier bedeutet:** Es existiert eine reproduzierbare Baseline vor
dem Exam. Der getaggte Commit ist genau das System, das auditiert und abgenommen
wurde, sodass der nächste Exam-Lauf gegen einen bekannten Zustand verglichen werden
kann und nicht gegen eine Erinnerung daran.

**Was es nicht bedeutet:** dass das Produkt fertig ist, dass jede Fähigkeit
automatisiert ist oder dass das System produktionsvollständig ist.
Dokumentations-Commits können nach dem Tag auf `main` landen; der Tag selbst
bewegt sich nicht.

---

## Lizenz

**Apache-2.0.** Der vollständige Lizenztext steht in [LICENSE](LICENSE).
Begründung, die Entscheidung gegen eine `NOTICE`-Datei und Punkte, die für eine
spätere Phase offen sind, sind in
[LICENSE_DECISION_PENDING.md](LICENSE_DECISION_PENDING.md) festgehalten.

---

## Kanonische Identität

- Projekt-ID: `ai-autocut`
- Standardbranch: `main`
- Laufzeit-Datenwurzel: logische Rolle `AUTOCUT_WORKSPACE`
- Medienwurzel: logische Rolle `AUTOCUT_MEDIA_ROOT`

Der maschinenlesbare Identitätsdatensatz ist
[PROJECT_IDENTITY.md](PROJECT_IDENTITY.md). Die Eintrittsregeln für Agenten stehen
in [AGENTS.md](AGENTS.md).
