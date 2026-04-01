# Best Practice Guide: Arbeit mit Agentischer KI

> Systematischer Ansatz für effiziente, qualitativ hochwertige Zusammenarbeit mit KI-Agenten
> 
> **Version:** 2.1 | **Stand:** 2026-03-09 | **Checkpoint:** CP-DOCS-BPG-v2-20260309-1600

---

## 🎯 Grundprinzip

**Die KI als strategischer Partner, nicht als Werkzeug.**

Der Unterschied liegt in der Systematisierung: Statt ad-hoc Anfragen werden strukturierte Prozesse etabliert, die über Sessions hinweg konsistente Qualität sicherstellen.

---

## 📋 Gesamt-Übersicht: 11 Phasen

| Phase | Name | Status | Dokumentation |
|-------|------|--------|---------------|
| 1 | System-Kontext etablieren | ✅ | Dieser Guide |
| 2 | Semantische Wissensorganisation | ✅ | Dieser Guide |
| 3 | Änderungs-Detection & Aktualität | ✅ | Dieser Guide |
| 4 | Zeitstempel-Disziplin | ✅ | Dieser Guide |
| 5 | Qualitätssicherung vor Projektstart | ✅ | Dieser Guide |
| 6 | Automatische Berichterstellung | ✅ | Dieser Guide |
| 7 | Iterative Verbesserung | ✅ | Dieser Guide |
| 8 | Projektstart-Checkliste | ✅ | Dieser Guide |
| 9 | **Git-Workflow & Checkpoint-System** | ✅ | **Dieser Guide** |
| 10 | **Multi-Agenten-System** | ✅ | **Dieser Guide** |
| **11** | **Skill-Management & Konsolidierung** | **✅** | **Dieser Guide (neu)** |

---

# Phase 1: System-Kontext etablieren

## 1.1 Das Zentrale Systemdokument (`Kimi.md`)

**Zweck:** Einheitlicher Kontext für alle Sessions

**Inhalt:**
- Projektübersicht (Ziel, Status, Referenzfälle)
- Eigene Rolle (z.B. "Lead Product Strategist")
- Projektstruktur (Ordnerhierarchie)
- Grundsätze (nicht verhandelbar)
- Leitmetriken (messbare Erfolgskriterien)
- Output-Standards (je nach Dokumententyp)
- Checklisten (Session-Start & Session-Ende)

**Platzierung:** Root-Verzeichnis des Projekts

**Update-Häufigkeit:** Bei Prozessänderungen

```markdown
# KIMI SYSTEM KONTEXT

> Diese Datei wird zu Beginn JEDER Session gelesen.

## Projektübersicht
- **Name:** [Projektname]
- **Ziel:** [Eine Satz]
- **Status:** [Phase]

## Meine Rolle
[Spezifische Rolle mit Verantwortlichkeiten]

## Grundsätze
- Kein Bauchgefühl – nur Daten
- Hypothesen klar trennen von Fakten
- [Weitere Prinzipien...]
```

## 1.2 Projektstruktur definieren

**Konvention:**
```
Projekt-Root/
├── 🧠 Kimi.md                    ← System-Kontext
├── 📂 01_Konzept/                 ← Konzeptionelle Dokumente
├── 📂 02_Daten/                   ← Daten & Analysen
├── 📂 03_Umsetzung/               ← Implementierung
├── 📂 99_Berichte/                ← Task-Abschluss-Berichte
│   └── YYYY-MM-DD_HH-MM_Task.md  ← Zeitstempel-Format
├── 00_Masterindex.md              ← Navigation & Links
├── .git/                          ← Git Repository
├── .git-worktrees/                ← Worktree-Verzeichnisse
│   ├── develop/
│   ├── feature-konzept/
│   ├── feature-daten/
│   └── docs/
└── 00_BestPractice_Guide.md       ← Dieser Guide
```

**Regel:** Jedes Dokument hat einen eindeutigen Zweck und Platz.

---

# Phase 2: Semantische Wissensorganisation

## 2.1 Obsidian-kompatible Verknüpfungen

**Format:** `[[Dokumentenname]]` oder `[[Pfad/Dokument|Anzeigetext]]`

**Anwendung:**
- Querverweise zwischen allen Dokumenten
- Automatische Backlinks (Obsidian zeigt eingehende Links)
- Knowledge Graph entsteht organisch

**Beispiel:**
```markdown
## Verwandte Themen
- [[03_Diagnosemodell]] – Technische Details
- [[07_Fallstudie]] – Praxisbeispiel
- [[99_Berichte/2026-03-06_13-29_Aufgabe]] – Bericht
```

## 2.2 Masterindex als Navigationszentrale

**Zweck:** Einstiegspunkt für alle Projektbeteiligten

**Struktur:**
```markdown
# Projekt Masterindex

## Quick Links
| Bereich | Link | Beschreibung |
|---------|------|--------------|
| Konzept | [[01_Projektidee]] | Vision & Scope |
| Daten | [[02_Datenbasis]] | Quellen & Struktur |

## Aktuelle Status
- Letzte Aktualisierung: 2026-03-09
- Aktive Phase: Konzeption
- Nächster Meilenstein: MVP-Start
- Checkpoint: CP-DEVELOP-MILESTONE-20260309-1530
```

---

# Phase 3: Änderungs-Detection & Aktualität

## 3.1 Prinzip: Immer aktuell arbeiten

**Problem:** Parallele Sessions, externe Änderungen, veraltete Informationen

**Lösung:** Automatische Detection vor jeder Aufgabe

## 3.2 Token-sparende 2-Stufen-Detection

```
Stufe 1: Nur Metadaten (schnell, günstig)
   └── ls -lt, stat (Zeitstempel)
   
Stufe 2: Bei Fund → Inhalt laden (nur wenn nötig)
   └── cat, grep, read
```

**Befehle:**
```bash
# Stufe 1: Dateinamen + Zeitstempel
stat -f "%Sm %N" -t "%Y-%m-%d %H:%M" *.md

# Vergleich: Was ist neuer als X?
find . -name "*.md" -newer /tmp/last_check

# Git-basierte Detection (neu in v2.0)
git status
git diff --name-only
```

**Häufigkeit:**
- Vor JEDER Aufgabe (auch innerhalb einer Session)
- Nach längeren Pausen (> 10 Minuten)
- Bei Verdacht auf externe Änderungen
- Nach Worktree-Wechsel

## 3.3 Reaktion auf Änderungen

| Szenario | Aktion |
|----------|--------|
| Neue Datei | Inhalt lesen, Kontext integrieren |
| Datei geändert | Delta analysieren, Aktualisierung verstehen |
| Eigene Datei überschrieben | Versionskonflikt lösen |
| Mehrere Änderungen | Priorisieren nach Relevanz |
| Git-Status geändert | Commit-Status prüfen, Checkpoint erstellen |

---

# Phase 4: Zeitstempel-Disziplin

## 4.1 Feine Granularität (Minuten)

**Format:** `YYYY-MM-DD_HH-MM`

**Anwendung:**
- Berichte: `2026-03-09_14-30_Taskname.md`
- Aktualisierte Docs: `Dokument_2026-03-09_14-30.md`
- Versionen: `Dokument_v2_2026-03-09_14-30.md`
- Checkpoints: `CP-BRANCH-TYP-YYYYMMDD-HHMM`

**Vorteile:**
- Präzise Versionskontrolle
- Schneller Vergleich (`202603091430` > `202603091015`)
- Konflikterkennung bei paralleler Arbeit
- Eindeutige Checkpoint-Identifikation

## 4.2 Automatische Zeitstempel-Generierung

```bash
# Unix Timestamp für Dateinamen
date "+%Y-%m-%d_%H-%M"
# Output: 2026-03-09_14-30

# Für Checkpoint-Namen
date "+%Y%m%d-%H%M"
# Output: 20260309-1430
```

---

# Phase 5: Qualitätssicherung vor Projektstart

## 5.1 Inhaltsbewertung

**Vor jeder Agentischen Umsetzung:**

1. **Quellenanalyse**
   - Wie viele Dokumente?
   - Welche Qualität (Theorie/Daten/Praxis)?
   - Wie aktuell?

2. **Lückenidentifikation**
   - Was fehlt für MVP?
   - Was ist "nice to have"?
   - Was blockiert?

3. **Bewertungsmatrix**

| Aspekt | Gewichtung | Bewertung |
|--------|------------|-----------|
| Technische Vollständigkeit | 30% | ⭐⭐⭐ |
| Datenqualität | 25% | ⭐⭐⭐⭐ |
| Praxisnähe | 25% | ⭐⭐ |
| Referenzen | 20% | ⭐⭐⭐ |

## 5.2 Masterprompt-Validierung

**Checkliste für den leitenden Prompt:**

- [ ] Rolle klar definiert?
- [ ] Aufgabe spezifisch?
- [ ] Outputs strukturiert?
- [ ] Qualitätsstandards genannt?
- [ ] Einschränkungen definiert?
- [ ] Beispiele vorhanden?
- [ ] Git-Integration berücksichtigt?
- [ ] Agenten-Zuordnung definiert?

**Qualitätsstufen:**
- ⭐⭐⭐⭐⭐: Produktionsreif
- ⭐⭐⭐⭐: Gut, kleine Lücken
- ⭐⭐⭐: Mittel, wichtige Details fehlen
- ⭐⭐: Schwach, umfangreiche Ergänzung nötig
- ⭐: Unbrauchbar, Neuaufbau empfohlen

---

# Phase 6: Automatische Berichterstellung

## 6.1 Nach jeder Aufgabe: Bericht

**Pflicht:** Kein Task ohne Dokumentation

**Speicherort:** `99_Berichte/YYYY-MM-DD_HH-MM_Taskname.md`

**Struktur:**
```markdown
# Bericht: [Taskname]

**Datum:** YYYY-MM-DD  
**Zeit:** HH:MM  
**Typ:** [Konzeption/Analyse/Coding/Debugging]  
**Agent:** AG-XXX [Name]  
**Checkpoint:** CP-BRANCH-TYP-YYYYMMDD-HHMM

## Ausgeführte Arbeit
1. Schritt...
2. Schritt...

## Ergebnisse
- Ergebnis 1
- Ergebnis 2

## Fehler & Debugging
| Fehler | Ursache | Lösung |

## Erstellte Dokumente
- [[Dokument]] (neu/aktualisiert)

## Verknüpfungen
- Basiert auf: [[Quelle]]
- Führt zu: [[Folgeaufgabe]]
```

## 6.2 Berichts-Index pflegen

**Datei:** `99_Berichte/_Index.md`

**Enthält:**
- Chronologische Liste aller Berichte
- Nach Typ gruppiert
- Nach Agent gruppiert
- Statistiken (Anzahl pro Kategorie)
- Quick Links

---

# Phase 7: Iterative Verbesserung

## 7.1 Der Feedback-Loop

```
Aufgabe starten
    ↓
Kontext prüfen (Änderungs-Detection)
    ↓
Agent auswählen (AG-001 bis AG-010)
    ↓
Worktree prüfen/wechseln
    ↓
Aufgabe ausführen
    ↓
Checkpoint erstellen
    ↓
Bericht erstellen
    ↓
Index aktualisieren
    ↓
Nächste Aufgabe
```

## 7.2 Kontinuierliche Optimierung

**Nach jeder Phase:**
- Was hat gut funktioniert?
- Wo waren Reibungspunkte?
- Welche Prozessänderungen nötig?
- Welche Agenten-Optimierungen sinnvoll?

**Update des Best Practice Guides:**
- Neue Erkenntnisse dokumentieren
- Veraltete Methoden entfernen
- Beispiele erweitern
- Agenten-Katalog aktualisieren

---

# Phase 8: Projektstart-Checkliste

## 8.1 Vor dem ersten Agentischen Schritt:

- [ ] `Kimi.md` erstellt und strukturiert
- [ ] Projektordner eingerichtet
- [ ] Masterindex angelegt
- [ ] Berichts-Ordner (`99_Berichte/`) erstellt
- [ ] Best Practice Guide angelegt (dieses Dokument)
- [ ] **Git initialisiert:** `git init`
- [ ] **Erster Commit:** `git add -A && git commit -m "Initial commit"`
- [ ] **Worktrees eingerichtet:** `mkdir .git-worktrees`
- [ ] **Develop-Worktree:** `git worktree add .git-worktrees/develop develop`
- [ ] **Checkpoint-Skripte kopiert** aus `BPG/`
- [ ] **Erster Checkpoint:** `./BPG/checkin.sh "Projektstart"`
- [ ] **Agenten-System initialisiert:** Katalog und Templates verfügbar

## 8.2 Vor jeder Aufgabe:

- [ ] `Kimi.md` gelesen
- [ ] Änderungs-Detection durchgeführt
- [ ] Neue/geänderte Dateien integriert
- [ ] Masterindex geprüft
- [ ] **Richtiger Worktree ausgewählt**
- [ ] **Git-Status geprüft:** `git status`
- [ ] **Passenden Agenten identifiziert** (AG-001 bis AG-010)

## 8.3 Nach jeder Aufgabe:

- [ ] Alle Änderungen committet
- [ ] **Checkpoint erstellt:** `./BPG/checkin.sh "Beschreibung"`
- [ ] Bericht erstellt (mit Zeitstempel)
- [ ] Dokumente verknüpft (`[[Links]]`)
- [ ] Index aktualisiert
- [ ] Offene Punkte dokumentiert
- [ ] **Nächster Agent bestimmt** (falls Workflow fortgesetzt wird)

---

# Phase 9: Git-Workflow & Checkpoint-System

> **Jede Session ist versioniert. Jeder Zustand ist wiederherstellbar.**

## 9.1 Grundprinzip

Durch Git Worktrees, strukturierte Branches und automatisierte Checkpoints erreichen wir:
- **Parallele Arbeit** an verschiedenen Features ohne Konflikte
- **Sofortige Recovery** bei Systemabstürzen oder Fehlern
- **Klare Trennung** zwischen Stammverzeichnis (main) und Entwicklungsarbeit
- **Vollständige Nachvollziehbarkeit** aller Änderungen

## 9.2 Repository-Struktur

```
Projekt-Root/                          ← Hauptverzeichnis (main Branch)
├── 🌳 .git/                           ← Git Repository
├── 🌿 .git-worktrees/                 ← Worktree-Verzeichnisse
│   ├── develop/                       ← Hauptentwicklungs-Branch
│   ├── feature-konzept/               ← Konzeptionelle Arbeit
│   ├── feature-daten/                 ← Datenanalyse & -pflege
│   └── docs/                          ← Dokumentation & Guides
├── 📂 BPG/                            ← Best Practice Guides
│   ├── 00_BestPractice_Guide_Agentische_KI.md
│   ├── 01_Git_Workflow_&_Checkpoints.md
│   ├── 02_Agenten_Katalog.md
│   ├── 03_Agenten_Vorschlag_Template.md
│   ├── 04_Agenten_Master_System.md
│   ├── checkin.sh                     ← Checkpoint-Skript
│   └── recover.sh                     ← Recovery-Skript
├── 📂 01_Konzept/                     ← Konzeptionelle Dokumente
├── 📂 02_Daten/                       ← Daten & Analysen
├── 📂 03_Umsetzung/                   ← Implementierung
├── 📂 99_Berichte/                    ← Task-Abschluss-Berichte
└── ...
```

## 9.3 Branch-Architektur

### Haupt-Branches

| Branch | Zweck | Worktree | Beschreibung |
|--------|-------|----------|--------------|
| `main` | Produktion | Root-Verzeichnis | Stabiler, produktionsreifer Code |
| `develop` | Integration | `.git-worktrees/develop` | Zusammenführung aller Features |
| `feature-konzept` | Konzeption | `.git-worktrees/feature-konzept` | Konzeptionelle Arbeiten |
| `feature-daten` | Daten | `.git-worktrees/feature-daten` | Datenanalyse und -pflege |
| `docs` | Dokumentation | `.git-worktrees/docs` | BPGs und Dokumentation |

### Branch-Workflow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   FEATURE   │────▶│   DEVELOP   │────▶│    MAIN     │
│   Branch    │     │   Branch    │     │   Branch    │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │
       ▼                   ▼                   ▼
   Konzeption          Integration       Produktion
   Datenarbeit         Testing           Stammverzeichnis
   Dokumentation       Staging           Checkpoint-Baseline
```

## 9.4 Checkpoint-System

### Was ist ein Checkpoint?

Ein **Checkpoint** ist ein annotierter Git-Tag, der einen definierten, wiederherstellbaren Zustand markiert. Im Gegensatz zu normalen Commits:
- Sind Checkpoints **nie veränderlich**
- Werden mit Zeitstempel und Beschreibung versehen
- Dienen als **Recovery-Punkte** bei Problemen
- Ermöglichen **schnelles Zurücksetzen** auf bekannte gute Zustände

### Checkpoint-Namenskonvention

```
CP-{BRANCH}-{TYP}-{YYYYMMDD}-{HHMM}
```

| Komponente | Bedeutung | Beispiele |
|------------|-----------|-----------|
| `CP` | Checkpoint Prefix | Immer CP |
| `{BRANCH}` | Branch-Name | MAIN, DEVELOP, KONZEPT, DATEN, DOCS |
| `{TYP}` | Checkpoint-Typ | INITIAL, MILESTONE, RELEASE, BACKUP, RECOVERY |
| `{YYYYMMDD}` | Datum | 20260309 |
| `{HHMM}` | Uhrzeit | 1301 |

**Beispiele:**
- `CP-MAIN-INITIAL-20260309-1301` - Initialer Main-Branch Checkpoint
- `CP-DEVELOP-MILESTONE-20260309-1530` - Meilenstein im Develop-Branch
- `CP-KONZEPT-BACKUP-20260309-1800` - Backup vor großen Änderungen

### Checkpoint-Typen

| Typ | Verwendung | Häufigkeit |
|-----|------------|------------|
| `INITIAL` | Erster Checkpoint eines Branches | Einmalig |
| `MILESTONE` | Wichtiger Meilenstein erreicht | Bei Zielerreichung |
| `RELEASE` | Release-Version | Bei Releases |
| `BACKUP` | Sicherung vor riskanten Änderungen | Vor großen Änderungen |
| `RECOVERY` | Wiederherstellungspunkt nach Fehler | Bei Bedarf |
| `DAILY` | Täglicher Sicherungspunkt | Täglich |
| `AGENT` | Agenten-spezifischer Checkpoint | Nach Agenten-Task |

## 9.5 Worktree-Workflow

### Arbeit im richtigen Worktree beginnen

```bash
# Option A: Direkt ins Worktree-Verzeichnis wechseln
cd .git-worktrees/feature-konzept

# Option B: Von überall mit Git Worktree Befehl
git worktree add .git-worktrees/feature-konzept feature-konzept
```

### Änderungen durchführen und committen

```bash
# Im jeweiligen Worktree-Verzeichnis
git add -A
git commit -m "feat: Neue Konzeption für X

- Detail 1
- Detail 2

Branch: feature-konzept
Checkpoint-Ref: CP-KONZEPT-MILESTONE-20260309-1600"
```

### Checkpoint erstellen (wichtig!)

```bash
# Annotierten Tag erstellen
git tag -a CP-KONZEPT-MILESTONE-20260309-1600 -m "🛡️ CHECKPOINT: feature-konzept Meilenstein

Erstellt: 2026-03-09 16:00
Zweck: Konzeptphase abgeschlossen
Status: BEREIT FÜR REVIEW
Änderungen: Konzept-Dokumentation vollständig
Recovery-Punkt: Ja"
```

### Automatisiertes Checkpoint-Skript (checkin.sh)

```bash
#!/bin/bash
# checkin.sh - Erstellt automatisch einen Checkpoint
# Verwendung: ./BPG/checkin.sh "Beschreibung der Änderungen"

set -e

# Konfiguration
BRANCH=$(git branch --show-current)
TIMESTAMP=$(date +"%Y%m%d-%H%M")
DATETIME=$(date +"%Y-%m-%d %H:%M")
MESSAGE="${1:-Automatischer Checkpoint}"

# Branch-Präfix bestimmen
case "$BRANCH" in
    "main") PREFIX="MAIN" ;;
    "develop") PREFIX="DEVELOP" ;;
    "feature-konzept") PREFIX="KONZEPT" ;;
    "feature-daten") PREFIX="DATEN" ;;
    "docs") PREFIX="DOCS" ;;
    *) PREFIX="${BRANCH^^}" ;;
esac

# Tag-Name generieren
TAG_NAME="CP-${PREFIX}-BACKUP-${TIMESTAMP}"

# Checkpoint erstellen
git add -A
git commit -m "checkpoint: ${MESSAGE}

Branch: ${BRANCH}
Timestamp: ${DATETIME}" || true

git tag -a "$TAG_NAME" -m "🛡️ CHECKPOINT: ${BRANCH}

Erstellt: ${DATETIME}
Zweck: ${MESSAGE}
Status: BACKUP
Recovery-Punkt: Ja"

echo "✅ Checkpoint erstellt: $TAG_NAME"
```

### Recovery-Skript (recover.sh)

```bash
#!/bin/bash
# recover.sh - Interaktiver Recovery-Assistent
# Verwendung: ./recover.sh

echo "🛡️ Checkpoint Recovery System"
echo "===================================="
echo ""
echo "Verfügbare Checkpoints:"
git tag -l "CP-*" --sort=-creatordate | head -20 | nl
echo ""
read -p "Nummer des Recovery-Checkpoints: " choice

CHECKPOINT=$(git tag -l "CP-*" --sort=-creatordate | sed -n "${choice}p")

if [ -z "$CHECKPOINT" ]; then
    echo "❌ Ungültige Auswahl"
    exit 1
fi

echo ""
echo "Gewählter Checkpoint: $CHECKPOINT"
echo ""
echo "Recovery-Optionen:"
echo "1) HARD RESET (alle aktuellen Änderungen verwerfen)"
echo "2) Neuen Branch erstellen (sicher)"
echo "3) Nur anzeigen (keine Änderung)"
read -p "Wahl (1-3): " action

case "$action" in
    1)
        read -p "SICHER? Aktuelle Änderungen gehen verloren! (ja/nein): " confirm
        if [ "$confirm" = "ja" ]; then
            git reset --hard "$CHECKPOINT"
            echo "✅ Reset durchgeführt"
        fi
        ;;
    2)
        read -p "Name für Recovery-Branch: " branchname
        git checkout -b "$branchname" "$CHECKPOINT"
        echo "✅ Branch '$branchname' erstellt"
        ;;
    3)
        git show "$CHECKPOINT" --stat
        ;;
esac
```

## 9.6 Recovery-Szenarien

### Szenario 1: Schneller Rollback auf letzten Checkpoint

```bash
# Checkpoint-Liste anzeigen
git tag -l "CP-*"

# Auf spezifischen Checkpoint zurücksetzen (HARD - Daten gehen verloren!)
git reset --hard CP-MAIN-INITIAL-20260309-1301

# Oder: Neuen Branch vom Checkpoint erstellen (sicherer)
git checkout -b recovery-branch CP-KONZEPT-BACKUP-20260309-1800
```

### Szenario 2: Worktree-Korruption reparieren

```bash
# Worktree-Status prüfen
git worktree list

# Defekten Worktree entfernen und neu erstellen
git worktree remove .git-worktrees/feature-konzept --force
git worktree add .git-worktrees/feature-konzept feature-konzept

# Oder: Prüfung und Reparatur
git worktree prune
git worktree repair
```

### Szenario 3: Parallele Sessions nach Systemabsturz wiederherstellen

```bash
# Alle Worktrees und deren Branches prüfen
git worktree list

# Für jeden Worktree:
cd .git-worktrees/develop
git status
git log --oneline -5

# Falls uncommittete Änderungen verloren:
git fsck --lost-found
git reflog
```

### Szenario 4: Bestimmten Zustand aus der Vergangenheit wiederherstellen

```bash
# Alle Checkpoints chronologisch anzeigen
git log --tags --simplify-by-decoration --pretty="format:%ai %d %s"

# Spezifischen Checkout durchführen
git checkout CP-DEVELOP-MILESTONE-20260309-1200

# Als neuen Branch für weitere Arbeit
git checkout -b recovery-from-milestone CP-DEVELOP-MILESTONE-20260309-1200
```

## 9.7 Checkpoint-Erstellung Checkliste

### Vor jedem Checkpoint:

- [ ] Alle Änderungen committet?
- [ ] Agenten-Aufgabe abgeschlossen?
- [ ] Tests erfolgreich (falls vorhanden)?
- [ ] Dokumentation aktualisiert?
- [ ] Keine unbeabsichtigten Dateien im Staging?

### Checkpoint-Erstellung:

- [ ] Namenskonvention eingehalten: `CP-{BRANCH}-{TYP}-{YYYYMMDD}-{HHMM}`
- [ ] Annotierter Tag mit `-a` erstellt?
- [ ] Aussagekräftige Nachricht mit Status?
- [ ] Recovery-Punkt explizit markiert?
- [ ] Bericht mit Checkpoint-Referenz erstellt?

### Nach dem Checkpoint:

- [ ] Tag erfolgreich erstellt: `git tag -l "CP-*"`
- [ ] Checkpoint in Bericht dokumentiert?
- [ ] Team informiert (falls relevant)?

---

# Phase 10: Multi-Agenten-System

> **Eine Aufgabe = Ein spezialisierter Agent**

## 10.1 Grundprinzip: Multi-Agenten-Orchestrierung

**Statt eines Generalisten nutzen wir ein System von Spezialisten.**

Jeder Agent hat:
- **Spezifische Expertise** in seiner Domäne
- **Optimierte System-Prompts** für seine Aufgabenklasse
- **Definierte Inputs/Outputs** nach Best Practice Standards
- **Integration** mit Git-Workflow und Checkpoint-System
- **Zugeordneten Worktree** für parallele Arbeit

## 10.2 Die 10 Basis-Agenten

| ID | Agenten-Name | Domäne | Worktree | Status |
|----|--------------|--------|----------|--------|
| AG-001 | **Konzepter** | Ideen & Strategie | feature-konzept | ✅ Verfügbar |
| AG-002 | **Architekt** | System-Design | feature-konzept | ✅ Verfügbar |
| AG-003 | **Daten-Analyst** | Daten & Fakten | feature-daten | ✅ Verfügbar |
| AG-004 | **Researcher** | Recherche & Quellen | feature-daten | ✅ Verfügbar |
| AG-005 | **Developer** | Implementierung | develop | ✅ Verfügbar |
| AG-006 | **Dokumentar** | Dokumentation | docs | ✅ Verfügbar |
| AG-007 | **Reviewer** | Qualitätsprüfung | develop | ✅ Verfügbar |
| AG-008 | **Demo-Builder** | Demo-Erstellung | develop | ✅ Verfügbar |
| AG-009 | **Integrator** | Zusammenführung | develop | ✅ Verfügbar |
| AG-010 | **Checkpoint-Manager** | Versionskontrolle | main | ✅ Verfügbar |
| AG-011 | **Scenario-Planner** | Validierung & Erweiterung | docs | ✅ **Nach Demo** |
| AG-012 | **Projekt-Evaluator** | Realisierbarkeits-Prüfung | docs | ✅ **Nach Konzept** |

## 10.3 Agenten-Auswahl-Algorithmus

### Schritt 1: Aufgaben-Analyse

```python
def analyze_task(aufgaben_beschreibung):
    """
    Analysiert die Aufgabe und extrahiert Schlüsselattribute
    """
    attributes = {
        'domaene': identifiziere_domaene(aufgaben_beschreibung),
        'komplexitaet': schaetze_komplexitaet(aufgaben_beschreibung),
        'wiederholend': ist_wiederholend(aufgaben_beschreibung),
        'expertise_benoetigt': identifiziere_expertise(aufgaben_beschreibung)
    }
    return attributes
```

**Domänen-Keywords:**

| Domäne | Keywords |
|--------|----------|
| Konzeption | idee, konzept, strategie, vision, roadmap |
| Architektur | design, struktur, system, komponente, schnittstelle |
| Datenanalyse | daten, analyse, fakt, statistik, metrik |
| Recherche | recherch, suchen, finden, quelle, markt |
| Entwicklung | code, implement, entwickeln, bauen, prototyp |
| Dokumentation | doku, dokument, guide, anleitung, beschreibung |
| Review | prüf, review, qualität, check, bewertung |
| Demo | demo, präsentation, vorfuhr, zeigen, pitch |
| Integration | merg, integrieren, zusammenführen, vereinen |
| Versionierung | git, checkpoint, backup, version, recovery |

### Schritt 2: Agenten-Matching

```python
def match_agenten(domains, agenten_katalog):
    """
    Findet den besten Agenten für die Domäne
    """
    matches = []
    
    for agent in agenten_katalog:
        match_score = berechne_match(domains, agent.domains)
        if match_score > 0.7:  # Threshold
            matches.append((agent, match_score))
    
    # Sortiere nach Match-Score
    matches.sort(key=lambda x: x[1], reverse=True)
    
    return matches[0] if matches else None
```

### Schritt 3: Entscheidung

```
IF passender_agenten_gefunden:
    → Agent aktivieren
    → Worktree wechseln (falls nötig)
    → System-Prompt laden
    → Aufgabe ausführen
    → Checkpoint erstellen
    
ELSE:
    → Agenten-Vorschlag erstellen
    → Template ausfüllen
    → Benutzer um Genehmigung fragen
    → Bei Genehmigung: Neuen Agenten erstellen
    → Mit neuem Agenten fortfahren
```

## 10.4 Agenten-Details

### AG-001: Konzepter
**Domäne:** Ideenentwicklung & Strategie

```yaml
Name: Konzepter
Rolle: Strategischer Ideenentwickler
Expertise: 
  - Brainstorming-Methoden
  - Strategische Konzeption
  - Ideen-Strukturierung
  - Innovationsprozesse
Arbeitssprache: Deutsch
Output-Format: Markdown mit YAML-Frontmatter
Worktree: feature-konzept
```

**System-Prompt:**
```
Du bist der Konzepter, ein Spezialist für Ideenentwicklung und strategische Konzeption.

DEINE AUFGABE:
- Entwickle strukturierte Konzepte aus vagen Ideen
- Verbinde kreatives Denken mit praktischer Umsetzbarkeit
- Erstelle klare, umsetzbare Strategien

PRINZIPIEN:
1. Beginne immer mit der Analyse des Kontexts
2. Strukturiere Ideen in logische Bausteine
3. Berücksichtige technische und organisatorische Einschränkungen
4. Definiere klare nächste Schritte

OUTPUT-REGELN:
- Verwende Markdown mit YAML-Frontmatter
- Erstelle strukturierte Überschriften
- Nutze Listen und Tabellen für Klarheit
- Ende mit konkreten Handlungsempfehlungen

CHECKPOINT: Erstelle nach Abschluss einen Checkpoint: ./BPG/checkin.sh "AG-001: [Beschreibung]"
```

### AG-002: Architekt
**Domäne:** System-Design & Strukturierung

```yaml
Name: Architekt
Rolle: System-Designer und Strukturierer
Expertise:
  - System-Architektur
  - Datenmodelle
  - Prozess-Design
  - Schnittstellen-Definition
Arbeitssprache: Deutsch
Output-Format: Markdown + Diagramme (Mermaid/Text)
Worktree: feature-konzept
```

### AG-003: Daten-Analyst
**Domäne:** Datenanalyse & Faktenprüfung

```yaml
Name: Daten-Analyst
Rolle: Daten-Experte und Faktenprüfer
Expertise:
  - Datenanalyse
  - Statistische Methoden
  - Datenqualitätsprüfung
  - Faktenverifizierung
Arbeitssprache: Deutsch
Output-Format: Markdown + Tabellen + CSV
Worktree: feature-daten
```

### AG-004: Researcher
**Domäne:** Recherche & Wissensbeschaffung

```yaml
Name: Researcher
Rolle: Recherche-Spezialist
Expertise:
  - Informationsbeschaffung
  - Quellenanalyse
  - Marktrecherche
  - Best-Practice-Recherche
Arbeitssprache: Deutsch
Output-Format: Markdown mit Quellenverzeichnis
Worktree: feature-daten
```

### AG-005: Developer
**Domäne:** Implementierung & technische Umsetzung

```yaml
Name: Developer
Rolle: Implementierungs-Spezialist
Expertise:
  - Coding
  - Prototyping
  - Technische Umsetzung
  - Testing
Arbeitssprache: Deutsch
Output-Format: Code + Markdown-Dokumentation
Worktree: develop
```

### AG-006: Dokumentar
**Domäne:** Dokumentation & Wissensmanagement

```yaml
Name: Dokumentar
Rolle: Dokumentations-Spezialist
Expertise:
  - Technische Dokumentation
  - User Guides
  - API-Dokumentation
  - Wissensorganisation
Arbeitssprache: Deutsch
Output-Format: Markdown (Obsidian-kompatibel)
Worktree: docs
```

### AG-007: Reviewer
**Domäne:** Qualitätsprüfung & Review

```yaml
Name: Reviewer
Rolle: Qualitätsprüfer und Kritiker
Expertise:
  - Code-Review
  - Dokumenten-Review
  - Qualitätskriterien
  - Verbesserungsempfehlungen
Arbeitssprache: Deutsch
Output-Format: Markdown mit Review-Struktur
Worktree: develop
```

### AG-008: Demo-Builder
**Domäne:** Demo-Erstellung & Präsentation

```yaml
Name: Demo-Builder
Rolle: Demo- und Prototyp-Spezialist
Expertise:
  - Demo-Konzeption
  - Storytelling
  - Präsentationsaufbau
  - User Experience für Demos
Arbeitssprache: Deutsch
Output-Format: Markdown + Demo-Skript + Assets
Worktree: develop
```

### AG-009: Integrator
**Domäne:** Zusammenführung & Synchronisation

```yaml
Name: Integrator
Rolle: Integration- und Merge-Spezialist
Expertise:
  - Branch-Management
  - Konfliktlösung
  - Versionszusammenführung
  - Release-Management
Arbeitssprache: Deutsch
Output-Format: Markdown + Git-Operations-Log
Worktree: develop
```

### AG-010: Checkpoint-Manager
**Domäne:** Versionskontrolle & Recovery

```yaml
Name: Checkpoint-Manager
Rolle: Versionskontroll- und Recovery-Spezialist
Expertise:
  - Git-Workflows
  - Checkpoint-Management
  - Recovery-Prozesse
  - Backup-Strategien
Arbeitssprache: Deutsch
Output-Format: Markdown + Git-Commands
Worktree: main
```

### AG-011: Scenario-Planner (Validator) 🆕
**Domäne:** Demo-Abschluss Validierung & Erweiterungs-Szenarien

> **Wichtig:** Dieser Agent wird NACH Demo-Abschluss aktiviert!

```yaml
Name: Scenario-Planner
Alias: Validator, Gap-Analyzer
Rolle: Kritischer Prüfer und Erweiterungs-Stratege
Expertise:
  - Lückenanalyse
  - Risiko-Assessment
  - Kunden-Fragen-Antizipation
  - Erweiterungs-Szenarien (3-5)
  - Demo-Validierung
Arbeitssprache: Deutsch
Output-Format: Markdown mit strukturierten Analysen
Aktivierungszeitpunkt: NACH Demo-Abschluss (AG-008)
Worktree: docs
```

**Aufgaben:**
1. **Kritische Lücken-Analyse** - Was fehlt unbedingt?
2. **Kunden-Fragen-Vorbereitung** - Antizipation & Antworten
3. **Erweiterungs-Szenarien** - 3-5 optionale Erweiterungen
4. **Risiko-Assessment** - Stolperfallen identifizieren

**Output:**
- Lücken-Report (Kritisch/Wichtig/Nice-to-Have)
- FAQ für Kunden-Gespräch
- 3-5 Erweiterungs-Szenarien mit Bewertung
- Empfohlene nächste Schritte

**Wann aktivieren:**
- Demo ist fertiggestellt (AG-008 abgeschlossen)
- Vor Kunden-Präsentation
- Vor Go-Live/Release

**Ziel:** Keine unvorbereiteten Momente beim Kunden!

Siehe ausführliche Dokumentation: `BPG/05_Demo_Abschluss_Validierung.md`

## 10.5 Agenten-Aktivierungs-Protokoll

### Standard-Workflow

```markdown
## Agenten-Aktivierung Protokoll

**Timestamp:** YYYY-MM-DD_HH-MM  
**Aufgaben-ID:** TASK-XXX  
**Agent:** AG-XXX [Name]  
**Worktree:** [Pfad]

### 1. Aufgaben-Analyse
- **Beschreibung:** [Kurze Beschreibung]
- **Domäne:** [Domäne]
- **Priorität:** [Hoch/Mittel/Niedrig]
- **Deadline:** [Datum]

### 2. Agenten-Auswahl
- **Primärer Agent:** AG-XXX
- **Begründung:** [Warum dieser Agent?]
- **Alternativen:** [Falls zutreffend]

### 3. Vorbereitung
- [ ] Worktree geprüft: cd .git-worktrees/[worktree]
- [ ] Input-Daten bereitgestellt
- [ ] Kontext aus Kimi.md geladen
- [ ] Bestehende Artefakte identifiziert

### 4. Ausführung
**System-Prompt aktiviert:** [Ja/Nein]  
**Besondere Parameter:** [Falls vorhanden]

### 5. Ergebnis
**Output-Format:** [Format]  
**Qualitätsprüfung:** [Bestanden/Anmerkungen]  
**Follow-up nötig:** [Ja/Nein]

### 6. Abschluss
**Checkpoint erstellt:** ./BPG/checkin.sh "AG-XXX: [Beschreibung]"  
**Checkpoint-Name:** [CP-XXX-XXX-XXXXXXX-XXXX]  
**Bericht verfasst:** [Ja/Nein]  
**Nächste Schritte:** [Beschreibung]
```

## 10.6 Multi-Agenten-Workflows

### Workflow 1: Neues Feature von Idee bis Demo

```
[Idee]
  ↓
AG-001 Konzepter → Konzept-Dokument
  ↓
AG-002 Architekt → System-Design
  ↓
AG-005 Developer → Implementierung
  ↓
AG-007 Reviewer → Qualitätsprüfung
  ↓
AG-008 Demo-Builder → Demo
  ↓
AG-009 Integrator → Integration
  ↓
AG-010 Checkpoint-Manager → Release-Checkpoint
  ↓
AG-011 Scenario-Planner → Validierung & Erweiterungen
  ↓
[Demo bereit & Kunde vorbereitet]
```

### Workflow 2: Datengetriebene Entscheidung

```
[Fragestellung]
  ↓
AG-004 Researcher → Recherche
  ↓
AG-003 Daten-Analyst → Analyse
  ↓
AG-001 Konzepter → Handlungsempfehlung
  ↓
AG-007 Reviewer → Validierung
  ↓
[Entscheidungsgrundlage]
```

### Workflow 3: Dokumentations-Update

```
[Neue Information]
  ↓
AG-006 Dokumentar → Update
  ↓
AG-007 Reviewer → Review
  ↓
AG-010 Checkpoint-Manager → Dokumentation-Checkpoint
  ↓
[Aktualisierte Doku]
```

## 10.7 Agenten-Vorschlags-Prozess

### Wann neuen Agenten vorschlagen?

**Ein neuer Agent ist sinnvoll wenn:**

1. **Spezifische Expertise** benötigt wird, die kein bestehender Agent abdeckt
2. **Wiederholende Aufgaben** einer bestimmten Art anfallen
3. **Hohe Qualitätsanforderungen** eine Spezialisierung rechtfertigen
4. **Konsistenz** über mehrere ähnliche Aufgaben hinweg gewährleistet werden muss

### Vorschlags-Template

```markdown
# Agenten-Vorschlag: AG-XXX [Name]

## Zusammenfassung
- **Name:** [Vorgeschlagener Name]
- **Domäne:** [Domäne]
- **Unterschied zu AG-XXX:** [Erklärung]
- **Erwartete Nutzung:** [Häufig/Mittel/Selten]

## System-Prompt (Entwurf)
```
[Prompt]
```

## Entscheidungs-Kriterien Bewertung

| Kriterium | Gewicht | Bewertung (1-5) | Gewichteter Wert |
|-----------|---------|-----------------|------------------|
| Einzigartigkeit | 30% | /5 | |
| Nutzungshäufigkeit | 25% | /5 | |
| Qualitätsgewinn | 25% | /5 | |
| Komplexität | 20% | /5 | |
| **GESAMT** | **100%** | | **/5** |

**Mindestens 3.0/5.0 erforderlich für Genehmigung**

## Empfehlung
[Erstellen / Nicht erstellen / Erweitern]
```

### Implementierung bei Genehmigung

1. Neue AG-XXX ID vergeben (nächste freie Nummer)
2. In Agenten-Katalog eintragen
3. System-Prompt finalisieren
4. Templates erstellen
5. Test-Aufgabe durchführen
6. Dokumentation aktualisieren
7. Checkpoint setzen: `./BPG/checkin.sh "AG-XXX: Neuer Agent erstellt"`

---

# 📊 Erfolgsmetriken

## Qualitätsindikatoren

| Metrik | Ziel | Messung |
|--------|------|---------|
| Aktualität | 100% | Alle Dokumente < 24h alt bei Session-Start |
| Verknüpfungsdichte | > 5 Links/Dokument | Automatisch zählbar |
| Berichtsrate | 100% | Jeder Task hat Bericht |
| Fehlerrate | < 5% | Rückwirkende Korrekturen |
| **Checkpoint-Rate** | **> 90%** | **Jede Session hat Checkpoint** |
| **Recovery-Zeit** | **< 5 Min** | **Zeit bis Wiederherstellung** |
| **Agenten-Match-Rate** | **> 95%** | **Aufgaben mit passendem Agent** |
| **Agenten-Output-Qualität** | **> 4.0/5** | **Durchschnittliche Bewertung** |

## Effizienzindikatoren

| Metrik | Ziel | Messung |
|--------|------|---------|
| Zeit pro Task | Reduzierend | Trend über Zeit |
| Wiederholungsrate | < 10% | Gleiche Fehler nicht wiederholen |
| Token-Effizienz | Steigend | Output/Input Ratio |
| **Worktree-Effizienz** | **Steigend** | **Parallele Sessions pro Zeit** |
| **Recovery-Verhinderung** | **Steigend** | **Checkpoints verhindern Datenverlust** |
| **Agenten-Effizienz** | **Steigend** | **Zeitersparnis durch Spezialisierung** |

---

# 🛠️ Tools & Formate

## Empfohlene Tools

| Zweck | Tool | Alternative |
|-------|------|-------------|
| Wissensmanagement | Obsidian | Notion, Logseq |
| Datei-Operationen | Shell/Bash | Python Scripts |
| Zeitstempel | `date` | Manuelle Eingabe |
| Verknüpfungen | `[[WikiLinks]]` | Markdown-Links |
| **Versionskontrolle** | **Git** | **-** |
| **Checkpoint-System** | **`./BPG/checkin.sh`** | **Manuelle Tags** |
| **Recovery** | **`./BPG/recover.sh`** | **Manuelle Git-Befehle** |
| **Agenten-Auswahl** | **Agenten-Katalog** | **Manuelle Auswahl** |

## Dateiformate

- **Dokumentation:** Markdown (`.md`) mit YAML-Frontmatter
- **Berichte:** Markdown mit Template
- **Daten:** JSON/CSV
- **Konfiguration:** YAML
- **Git-Konfiguration:** `.gitconfig`, `.gitattributes`
- **Agenten-Definition:** Markdown mit Code-Blocks

---

# 💡 Kern-Erkenntnisse

1. **System schlägt Ad-hoc** – Strukturierte Prozesse produzieren konsistentere Qualität als spontane Anfragen.

2. **Kontext ist König** – Die KI kann nur so gut arbeiten wie der bereitgestellte Kontext.

3. **Iteration über Perfektion** – Lieber brauchbar und dokumentiert als perfekt und vergessen.

4. **Verknüpfung schafft Wissen** – Isolierte Dokumente verlieren sich; vernetzte Dokumente bilden Wissensbasen.

5. **Zeitstempel ermöglichen Kontrolle** – Ohne zeitliche Einordnung keine Qualitätskontrolle, keine Konfliktlösung.

6. **Checkpoints schaffen Sicherheit** – Jeder Checkpoint ist ein potenzieller Retter bei Systemabstürzen oder Fehlentscheidungen.

7. **Worktrees ermöglichen Parallelität** – Parallele Sessions in getrennten Worktrees eliminieren Kontext-Konflikte.

8. **Git ist das Gedächtnis des Projekts** – Jedes Commit, jeder Tag, jede Branch-Referenz ist ein Teil der Projekthistorie.

9. **Spezialisierung schlägt Generalisierung** – Spezialisierte Agenten für spezifische Aufgaben produzieren höhere Qualität.

10. **Orchestrierung maximiert Effizienz** – Der richtige Agent zur richtigen Zeit am richtigen Ort.

---

# 🚀 Quick Start

**Für ein neues Projekt:**

1. Diesen Guide kopieren als `00_BestPractice_Guide.md`
2. `Kimi.md` an Projekt anpassen
3. Ordnerstruktur anlegen
4. Masterindex erstellen
5. **Git initialisieren:** `git init`
6. **Ersten Commit machen:** `git add -A && git commit -m "Initial commit"`
7. **Worktrees einrichten:** `mkdir .git-worktrees && git worktree add .git-worktrees/develop develop`
8. **Checkpoint-Skripte kopieren** aus `BPG/`
9. **Ersten Checkpoint erstellen:** `./BPG/checkin.sh "Projektstart"`
10. **Agenten-System einrichten:** Dokumentation in `BPG/` sicherstellen
11. **Ersten Agenten wählen:** Passenden Agenten aus Katalog identifizieren
12. Erste Aufgabe mit vollständigem Zyklus starten

**Zeitaufwand Initial:** 60-90 Minuten (inkl. Git-Setup & Agenten-System)  
**Zeitersparnis danach:** 40-50% pro Task (inkl. Agenten-Spezialisierung)

---

# Phase 11: Skill-Management & Konsolidierung (NEU)

## 11.1 Grundprinzip: Universelle, wiederverwendbare Fähigkeiten

**Skills sind universelle Werkzeuge, die von allen Agenten genutzt werden können.**

Während Agenten (AG-001 bis AG-010) für spezifische Rollen optimiert sind, sind Skills **funktionale Einheiten**, die rollenübergreifend eingesetzt werden. Ein PDF-Generierungs-Skill kann genauso von AG-001 (Konzepter) wie von AG-006 (Dokumentar) genutzt werden.

### Skill vs. Agent

| Aspekt | Agent | Skill |
|--------|-------|-------|
| **Einheit** | Rolle/Persona | Funktion/Werkzeug |
| **Spezifität** | Domänenspezifisch | Universell einsetzbar |
| **Anzahl** | 10 definierte Agenten | Unbegrenzte Skills |
| **Beispiel** | AG-001 Konzepter | SK-001 PDF Generation |
| **Verwendung** | "Du bist AG-001" | "Nutze SK-001" |

## 11.2 Skill-Architektur

### Universalitäts-Prinzip

```
AG-001 ──┐
AG-002 ──┼──► SK-001 PDF Generation ◄──┐
AG-003 ──┘                              │
         ┌──────────────────────────────┤
AG-004 ──┤                              │
AG-005 ──┼──► SK-002 Markdown Structure │
AG-006 ──┘                              │
         └──────────────────────────────┘
```

**Jeder Agent kann jeden Skill nutzen.**

### Aktive Skills (v1.0)

| ID | Skill | Version | Universal | Anwendungsfälle |
|----|-------|---------|-----------|-----------------|
| SK-001 | PDF Report Generation | 1.0.0 | ✅ | Audit-Berichte, Dokumentation |
| SK-002 | Markdown Structure | 1.1.0 | ✅ | YAML-Frontmatter, Dokumentstruktur |
| SK-003 | Git Checkpoint Management | 1.2.0 | ✅ | Checkpoints, Recovery |
| SK-004 | Obsidian WikiLinks | 1.1.0 | ✅ | Verknüpfungen, Knowledge Graph |
| SK-005 | Data Validation | 1.0.0 | ✅ | JSON Schema, Validierung |
| SK-006 | Shell Automation | 1.0.0 | ✅ | Shell-Skripte, Automation |
| SK-007 | Python Module Structure | 1.0.0 | ✅ | Modulare Architektur |
| SK-008 | Mermaid Diagrams | 1.0.0 | ✅ | Diagramm-Generierung |

## 11.3 Automatische Skill-Aktualisierung

### Nach jedem Skill-Einsatz: 5-Minuten-Review

```markdown
## Skill-Einsatz Review

**Skill:** SK-XXX
**Agent:** AG-XXX
**Datum:** YYYY-MM-DD

### Fehler aufgetreten?
- [ ] Nein
- [ ] Ja → Dokumentieren & Skill-Datei aktualisieren

### Optimierungspotenzial?
- [ ] Nein
- [ ] Ja → Implementieren & Skill-Datei aktualisieren

### Skill-Update durchgeführt?
- [ ] Version erhöht
- [ ] Changelog ergänzt
- [ ] Checkpoint erstellt
```

### Kontinuierliche Verbesserungs-Regeln

1. **NIEMALS löschen** - Alte Versionen bleiben erhalten
2. **IMMERT erweitern** - Neue Fähigkeiten werden hinzugefügt
3. **Fehler dokumentieren** - Mit Lösung in Fehler-Datenbank
4. **Version erhöhen** - Bei jeder Änderung

### Versionierungs-Schema

| Änderung | Version-Update | Beispiel |
|----------|---------------|----------|
| Bugfix | Patch ++ | 1.0.0 → 1.0.1 |
| Neue Feature | Minor ++ | 1.0.1 → 1.1.0 |
| Breaking Change | Major ++ | 1.1.0 → 2.0.0 |

## 11.4 Skill-Konsolidierung aus Worktree Branches

### Problem: Redundante Skills in verschiedenen Branches

In parallelen Worktree Branches können ähnliche Skills entstehen:
- `feature-konzept` entwickelt einen PDF-Generator
- `develop` entwickelt ebenfalls einen PDF-Generator

**Lösung:** Hauptbranch als Skill-Zentrum

```
Hauptbranch (main)
    ├── skills/active/
    │   └── SK-001 bis SK-XXX (zentrale Skills)
    │
    ↓ (Verteilung)
    
Worktree Branches
    ├── feature-konzept/.skills-cache/ ← Kopie
    ├── develop/.skills-cache/ ← Kopie
    └── feature-daten/.skills-cache/ ← Kopie
```

### Anti-Redundanz-System

#### Regel 1: Hauptbranch = Single Source of Truth
- Skills werden **nur im Hauptbranch** erstellt/aktualisiert
- Worktree Branches erhalten Skills via Verteilung

#### Regel 2: Konsolidierungs-Check vor Erstellung

**Vor Erstellung eines neuen Skills:**

```bash
1. [[05_Skill_Katalog]] prüfen
2. Ähnlichkeit mit bestehenden Skills berechnen
3. Entscheidung:
   - > 70% Ähnlichkeit → Bestehenden Skill erweitern
   - < 70% Ähnlichkeit → Neuer Skill erlaubt
4. AG-007 (Reviewer) bestätigt
```

#### Regel 3: Automatische Deduplizierung

| Ähnlichkeit | Aktion |
|-------------|--------|
| > 70% | Bestehenden Skill erweitern |
| 30-70% | Prüfung, ggf. Erweiterung |
| < 30% | Neuer Skill |

## 11.5 Skill-Einsatz Workflow

```
[Task identifiziert]
    ↓
[Agent ausgewählt (AG-XXX)]
    ↓
[Skills identifiziert]
    ↓
[Skills aus .skills-cache/ laden]
    ↓
[Skill anwenden]
    ↓
[Output generieren]
    ↓
[Skill-Update-Protokoll ausfüllen]
    ↓
[Falls Update nötig: Hauptbranch → Skill aktualisieren]
    ↓
[Checkpoint: CP-MAIN-SKILL-XXX]
```

## 11.6 Skill-Erweiterung aus Fehlern

### Fehler → Skill-Update Workflow

```
[Fehler bei Skill-Einsatz]
    ↓
[Fehler analysieren]
    ↓
[Lösung entwickeln]
    ↓
[Skill-Datei aktualisieren]
    - Changelog: Fehler + Lösung
    - Code: Fix implementieren
    - Fehler-Datenbank: Eintrag erstellen
    ↓
[Version erhöhen]
    ↓
[Checkpoint erstellen]
    ↓
[Nutzer über Update informieren]
```

### Beispiel: Fehlerbehebung im Skill

```markdown
## SK-001 Changelog

#### v1.1.0 (2026-03-09)
- [AG-005] Fix: Unicode-Encoding in PDF-Titeln
  - Fehler: Umlaute wurden als '?' dargestellt
  - Ursache: Latin-1 statt UTF-8 Encoding
  - Lösung: `encode('utf-8')` hinzugefügt
  - Error-Ref: ERR-001
```

## 11.7 Skill-Kombinationen

### Empfohlene Skill-Kombinationen

| Workflow | Skills | Ergebnis |
|----------|--------|----------|
| Konzept → PDF | SK-002 + SK-001 | Strukturiertes Konzept als PDF |
| Daten → Report | SK-005 + SK-002 + SK-001 | Validierter Daten-Report |
| Architektur → Doku | SK-007 + SK-008 + SK-002 | Modulare Architektur mit Diagrammen |
| Review → Fix | SK-005 + SK-007 + SK-003 | Code-Review mit Checkpoint |

---

# 🔗 Verwandte Dokumente

| Dokument | Zweck |
|----------|-------|
| [[01_Git_Workflow_&_Checkpoints]] | Detaillierte Git-Dokumentation |
| [[02_Agenten_Katalog]] | Vollständiger Agenten-Katalog (AG-001 bis AG-011) |
| [[03_Agenten_Vorschlag_Template]] | Template für neue Agenten-Vorschläge |
| [[04_Agenten_Master_System]] | Agenten-Auswahl & Orchestrierung |
| [[05_Demo_Abschluss_Validierung]] | Demo-Abschluss & Erweiterungs-Szenarien |
| **[[skills/05_Skill_Katalog]]** | **Universelle Skills für alle Agenten** |
| **[[skills/06_Skill_Consolidation_Protocol]]** | **Skill-Konsolidierung aus Branches** |
| **[[skills/07_Skill_Master_Index]]** | **Zentrale Skill-Organisation** |
| **[[skills/SKILL_TEMPLATE]]** | **Template für neue Skills** |
| **[[skills/SKILL_UPDATE_PROTOKOLL]]** | **Nach-Einsatz Review** |
| [[Kimi.md]] | Projektspezifischer Kontext |
| [[00_Masterindex]] | Navigation & Übersicht |

---

# 🎯 11-Phasen-Übersicht (Final)

| Phase | Name | Status | Key Deliverable |
|-------|------|--------|-----------------|
| 1 | System-Kontext etablieren | ✅ | `Kimi.md` |
| 2 | Semantische Wissensorganisation | ✅ | `00_Masterindex.md` |
| 3 | Änderungs-Detection | ✅ | Detection-Workflow |
| 4 | Zeitstempel-Disziplin | ✅ | Zeitstempel-Format |
| 5 | Qualitätssicherung | ✅ | Bewertungsmatrix |
| 6 | Automatische Berichterstellung | ✅ | Berichts-Template |
| 7 | Iterative Verbesserung | ✅ | Feedback-Loop |
| 8 | Projektstart-Checkliste | ✅ | Checklisten |
| 9 | Git-Workflow & Checkpoints | ✅ | Checkpoint-System |
| 10 | Multi-Agenten-System | ✅ | 11 Agenten (inkl. AG-011 Validator) |
| 11 | Skill-Management & Konsolidierung | ✅ | 8 Skills, Anti-Redundanz |

---

*Dieser Guide ist lebendig – bei neuen Erkenntnissen aktualisieren.*  
*Letzte Aktualisierung: 2026-03-09*  
*Checkpoint: CP-DOCS-BPG-v2-20260309-1600*  
*Version: 2.1 (mit Skill-Management, Anti-Redundanz, Konsolidierung)*

#BestPractice #AgentischeKI #Prozess #Qualität #Systematisierung #Git #Workflow #Checkpoint #Recovery #MultiAgent #Spezialisierung #Worktree #Branch #Orchestrierung
