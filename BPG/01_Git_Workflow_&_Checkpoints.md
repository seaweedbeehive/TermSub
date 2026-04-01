# Git Workflow & Checkpoint System

> Systematische Versionskontrolle mit Worktrees und Recovery-Checkpoints für maximale Sicherheit

---

## 🎯 Grundprinzip

**Jede Session ist versioniert. Jeder Zustand ist wiederherstellbar.**

Durch die Kombination von Git Worktrees, strukturierten Branches und automatisierten Checkpoints erreichen wir:
- **Parallele Arbeit** an verschiedenen Features ohne Konflikte
- **Sofortige Recovery** bei Systemabstürzen oder Fehlern
- **Klare Trennung** zwischen Stammverzeichnis (main) und Entwicklungsarbeit
- **Vollständige Nachvollziehbarkeit** aller Änderungen

---

## 📁 Repository-Struktur

```
KIMECO - KOKIEU/                          ← Hauptverzeichnis (main Branch)
├── 🌳 .git/                              ← Git Repository
├── 🌿 .git-worktrees/                    ← Worktree-Verzeichnisse
│   ├── develop/                          ← Hauptentwicklungs-Branch
│   ├── feature-konzept/                  ← Konzeptionelle Arbeit
│   ├── feature-daten/                    ← Datenanalyse & -pflege
│   └── docs/                             ← Dokumentation & Guides
├── 📂 BPG/                               ← Best Practice Guides
│   ├── 00_BestPractice_Guide_Agentische_KI.md
│   ├── 00_BestPractice_Guide_Dashboard.html
│   └── 01_Git_Workflow_&_Checkpoints.md  ← Dieses Dokument
├── 📂 03_Diagnose-Tool Kulturhäuser/     ← Projektspezifisch
└── ...
```

---

## 🔄 Branch-Architektur

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

---

## 🛡️ Checkpoint-System

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

---

## 🛠️ Worktree-Workflow

### 1. Arbeit im richtigen Worktree beginnen

```bash
# Option A: Direkt ins Worktree-Verzeichnis wechseln
cd .git-worktrees/feature-konzept

# Option B: Von überall mit Git Worktree Befehl
git worktree add .git-worktrees/feature-konzept feature-konzept
```

### 2. Änderungen durchführen und committen

```bash
# Im jeweiligen Worktree-Verzeichnis
git add -A
git commit -m "feat: Neue Konzeption für X

- Detail 1
- Detail 2

Branch: feature-konzept
Checkpoint-Ref: CP-KONZEPT-MILESTONE-20260309-1600"
```

### 3. Checkpoint erstellen (wichtig!)

```bash
# Annotierten Tag erstellen
git tag -a CP-KONZEPT-MILESTONE-20260309-1600 -m "🛡️ CHECKPOINT: feature-konzept Meilenstein

Erstellt: 2026-03-09 16:00
Zweck: Konzeptphase abgeschlossen
Status: BEREIT FÜR REVIEW
Änderungen: Konzept-Dokumentation vollständig
Recovery-Punkt: Ja"
```

### 4. Änderungen in develop mergen

```bash
# Zuerst ins develop Worktree wechseln
cd ../develop
git merge feature-konzept --no-ff -m "merge: Konzept-Feature integriert

Quelle: feature-konzept
Ziel: develop
Konflikte: Keine"
```

### 5. In main mergen (nur stabil getestete Änderungen)

```bash
# Von develop nach main (im Root-Verzeichnis)
cd ../../  # Zurück zum Root
git merge develop --no-ff -m "release: Stabile Version

Quelle: develop
Version: v1.x.x
Status: PRODUKTIONSBEREIT"
```

---

## 🚨 Recovery-Szenarien

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

---

## 📋 Checkpoint-Erstellung Checkliste

### Vor jedem Checkpoint:

- [ ] Alle Änderungen committet?
- [ ] Tests erfolgreich (falls vorhanden)?
- [ ] Dokumentation aktualisiert?
- [ ] Keine unbeabsichtigten Dateien im Staging?

### Checkpoint-Erstellung:

- [ ] Namenskonvention eingehalten: `CP-{BRANCH}-{TYP}-{YYYYMMDD}-{HHMM}`
- [ ] Annotierter Tag mit `-a` erstellt?
- [ ] Aussagekräftige Nachricht mit Status?
- [ ] Recovery-Punkt explizit markiert?

### Nach dem Checkpoint:

- [ ] Tag erfolgreich gepusht (falls Remote existiert): `git push origin CP-XXX`
- [ ] Checkpoint in Dokumentation vermerkt?
- [ ] Team informiert (falls relevant)?

---

## 🔧 Automatisierung: Checkpoint-Skript

### checkin.sh - Schnelles Checkpoint erstellen

```bash
#!/bin/bash
# checkin.sh - Erstellt automatisch einen Checkpoint
# Verwendung: ./checkin.sh "Beschreibung der Änderungen"

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

### recover.sh - Recovery-Assistent

```bash
#!/bin/bash
# recover.sh - Interaktiver Recovery-Assistent
# Verwendung: ./recover.sh

echo "🛡️ KIMECO Checkpoint Recovery System"
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

---

## 📊 Checkpoint-Übersicht (Dashboard)

### Aktuelle Checkpoints

```
┌─────────────────────────────────────────────────────────────┐
│  BRANCH      │  CHECKPOINT                    │  STATUS     │
├─────────────────────────────────────────────────────────────┤
│  main        │  CP-MAIN-INITIAL-20260309-1301 │  ✅ AKTIV   │
│  develop     │  CP-DEVELOP-INITIAL-20260309-1301│  ✅ AKTIV │
│  feature-konzept│ CP-KONZEPT-INITIAL-20260309-1301│ ✅ AKTIV │
│  feature-daten│  CP-DATEN-INITIAL-20260309-1301│  ✅ AKTIV  │
│  docs        │  CP-DOCS-INITIAL-20260309-1301 │  ✅ AKTIV   │
└─────────────────────────────────────────────────────────────┘
```

### Checkpoint-Statistik

| Metrik | Wert |
|--------|------|
| Gesamt-Checkpoints | 5 |
| Letzter Checkpoint | 2026-03-09 13:01 |
| Recovery-Punkte verfügbar | 5 |
| Branches mit Checkpoints | 5/5 (100%) |

---

## 🎯 Best Practices

### 1. Checkpoint-Häufigkeit

| Aktivität | Empfohlene Häufigkeit |
|-----------|----------------------|
| Feature-Entwicklung | Nach jedem Meilenstein |
| Dokumentation | Nach Abschluss jedes Abschnitts |
| Datenanalyse | Vor und nach großen Änderungen |
| Experimente | Vor dem Experiment (Backup) |
| Tägliche Arbeit | Am Ende jedes Arbeitstags |

### 2. Commit-Nachrichten Format

```
{type}: {kurze Beschreibung}

{Details}

Branch: {branch-name}
Checkpoint-Ref: {checkpoint-tag}
```

**Typen:**
- `feat:` - Neue Funktionalität
- `fix:` - Fehlerbehebung
- `docs:` - Dokumentation
- `checkpoint:` - Checkpoint-Commit
- `merge:` - Merge-Commit
- `release:` - Release-Commit

### 3. Worktree-Wechsel Workflow

```bash
# 1. Aktuellen Stand sichern
git add -A && git commit -m "wip: Zwischenstand"

# 2. Checkpoint erstellen
./checkin.sh "Vor Branch-Wechsel"

# 3. Zum anderen Worktree wechseln
cd ../anderer-worktree

# 4. Status prüfen
git status

# 5. Arbeit fortsetzen
```

---

## 🔗 Integration mit Best Practice Guide

Dieser Git Workflow ist ein **Erweiterung** des bestehenden Best Practice Guides für Agentische KI:

| BPG Phase | Git Integration |
|-----------|-----------------|
| Phase 1: System-Kontext | `Kimi.md` versioniert im main Branch |
| Phase 2: Wissensorganisation | Obsidian-Dateien in docs Branch |
| Phase 3: Änderungs-Detection | Git Diff und Status Checks |
| Phase 4: Zeitstempel | Commit-Timestamps + Checkpoint-Tags |
| Phase 6: Berichterstellung | Commit Messages als Dokumentation |

---

## 🚀 Quick Start

**Neue Session starten:**

```bash
# 1. Ins entsprechende Worktree wechseln
cd .git-worktrees/feature-konzept

# 2. Status prüfen
git status

# 3. Neueste Änderungen holen (falls Remote existiert)
git pull origin feature-konzept

# 4. Arbeit beginnen
```

**Session abschließen:**

```bash
# 1. Alle Änderungen committen
git add -A
git commit -m "feat: Beschreibung"

# 2. Checkpoint erstellen
./BPG/checkin.sh "Session-Abschluss"

# 3. Zusammenführen (falls fertig)
cd ../develop
git merge feature-konzept
```

## 🔗 Integration mit Agenten-System

Dieser Git-Workflow ist Teil des umfassenderen **Agenten-Git-Integration-Systems** (Phase 11 im Best Practice Guide).

### Detaillierte Workflows:

| Workflow | Beschreibung | Dokument |
|----------|--------------|----------|
| Agenten-Worktree-Zuordnung | Welcher Agent arbeitet in welchem Worktree/Branch | [[00_BestPractice_Guide_Agentische_KI#11.2 Agenten-Worktree-Branch-Zuordnung (Vollständig)]] |
| Agenten-Git-Workflow | Schritt-für-Schritt für jeden Agenten | [[00_BestPractice_Guide_Agentische_KI#11.3 Der vollständige Agenten-Git-Workflow]] |
| Multi-Agenten-Workflows | Parallele Arbeit mehrerer Agenten | [[00_BestPractice_Guide_Agentische_KI#11.6 Multi-Agenten-Git-Workflows (Detailliert)]] |
| Agenten-Recovery | Recovery-Szenarien für Agenten | [[00_BestPractice_Guide_Agentische_KI#11.7 Recovery-Szenarien für Agenten-Worktrees]] |
| Agenten-Checklisten | Vor/nach der Arbeit mit Agenten | [[00_BestPractice_Guide_Agentische_KI#11.8 Agenten-Git-Checklisten]] |

### Schnellzugriff Agenten-Worktrees:

| Agent | Worktree | Branch |
|-------|----------|--------|
| AG-001/AG-002 | `.git-worktrees/feature-konzept/` | `feature-konzept` |
| AG-003/AG-004 | `.git-worktrees/feature-daten/` | `feature-daten` |
| AG-005/AG-007/AG-008/AG-009 | `.git-worktrees/develop/` | `develop` |
| AG-006 | `.git-worktrees/docs/` | `docs` |
| AG-010 | Root (`.`) | `main` |

---

*Letzte Aktualisierung: 2026-03-09 16:00*
*Checkpoint-Version: CP-DOCS-AGENTEN-GIT-20260309-1600*
*Git-Integration: v1.0*

#Git #Workflow #Checkpoint #Recovery #Worktree #VersionControl #Agenten #Integration
