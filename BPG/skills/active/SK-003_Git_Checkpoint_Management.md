# SK-003: Git Checkpoint Management

> Automatisierte Versionskontrolle mit Checkpoints und Recovery

---

## Skill-Metadaten

```yaml
skill_id: SK-003
skill_name: Git Checkpoint Management
version: 1.2.0
created: 2026-03-09
last_updated: 2026-03-09
authors: [AG-010, Alle Agenten]
universal: true
applicability:
  - AG-001
  - AG-002
  - AG-003
  - AG-004
  - AG-005
  - AG-006
  - AG-007
  - AG-008
  - AG-009
  - AG-010
```

---

## 1. Skill-Beschreibung

### 1.1 Zweck
Systematische Erstellung annotierter Git-Tags (Checkpoints) für jede Session, automatische Recovery-Unterstützung und konsistente Namenskonventionen.

### 1.2 Anwendungsfälle
- Session-Abschluss (alle Agenten)
- Backup vor riskanten Änderungen
- Meilenstein-Markierung
- Wiederherstellung nach Fehlern

### 1.3 Input/Output

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| message | str | Checkpoint-Beschreibung |
| type | str | 'MILESTONE', 'BACKUP', 'RELEASE', 'RECOVERY' |
| branch | str | Aktueller Branch (auto-detected) |
| output | str | Tag-Name des Checkpoints |

---

## 2. Implementierung

### 2.1 Checkpoint-Erstellung (checkin.sh)

```bash
#!/bin/bash
# SK-003: Checkpoint Management Script

set -e

# Git-Root finden
if git rev-parse --show-toplevel > /dev/null 2>&1; then
    GIT_ROOT=$(git rev-parse --show-toplevel)
    cd "$GIT_ROOT"
else
    echo "❌ Kein Git-Repository gefunden"
    exit 1
fi

# Konfiguration
BRANCH=$(git branch --show-current)
TIMESTAMP=$(date +"%Y%m%d-%H%M")
DATETIME=$(date +"%Y-%m-%d %H:%M")
MESSAGE="${1:-Automatischer Checkpoint}"

# Branch-Präfix
case "$BRANCH" in
    "main") PREFIX="MAIN" ;;
    "develop") PREFIX="DEVELOP" ;;
    "feature-konzept") PREFIX="KONZEPT" ;;
    "feature-daten") PREFIX="DATEN" ;;
    "docs") PREFIX="DOCS" ;;
    *) PREFIX="${BRANCH^^}" ;;
esac

# Typ bestimmen
if [[ "$MESSAGE" =~ [Rr]elease ]]; then
    TYPE="RELEASE"
elif [[ "$MESSAGE" =~ [Bb]ackup|[Ss]icherung ]]; then
    TYPE="BACKUP"
elif [[ "$MESSAGE" =~ [Rr]ecovery ]]; then
    TYPE="RECOVERY"
else
    TYPE="MILESTONE"
fi

# Tag generieren
TAG_NAME="CP-${PREFIX}-${TYPE}-${TIMESTAMP}"

# Commit & Tag
git add -A
git commit -m "checkpoint: ${MESSAGE}

Branch: ${BRANCH}
Timestamp: ${DATETIME}" || true

git tag -a "$TAG_NAME" -m "🛡️ CHECKPOINT: ${BRANCH}

Erstellt: ${DATETIME}
Zweck: ${MESSAGE}
Status: ${TYPE}
Recovery-Punkt: Ja"

echo "✅ Checkpoint: $TAG_NAME"
```

### 2.2 Recovery (recover.sh)

```bash
#!/bin/bash
# SK-003: Recovery Script

set -e

GIT_ROOT=$(git rev-parse --show-toplevel)
cd "$GIT_ROOT"

# Schneller Rollback
if [ "$1" = "--last" ]; then
    LAST_CP=$(git tag -l "CP-*" --sort=-creatordate | head -1)
    [ -z "$LAST_CP" ] && echo "❌ Keine Checkpoints" && exit 1
    
    echo "Letzter Checkpoint: $LAST_CP"
    read -p "Zurücksetzen? (ja/nein): " confirm
    [ "$confirm" = "ja" ] && git reset --hard "$LAST_CP"
    exit 0
fi

# Interaktiver Modus
echo "🛡️ Checkpoint Recovery"
git tag -l "CP-*" --sort=-creatordate | head -20 | nl
read -p "Nummer (oder 'q'): " choice
[ "$choice" = "q" ] && exit 0

CHECKPOINT=$(git tag -l "CP-*" --sort=-creatordate | sed -n "${choice}p")
[ -z "$CHECKPOINT" ] && echo "❌ Ungültig" && exit 1

echo "Checkpoint: $CHECKPOINT"
echo "1) HARD RESET"
echo "2) Neuer Branch"
echo "3) Details"
read -p "Wahl: " action

case "$action" in
    1) read -p "SICHER? (ja/nein): " c && [ "$c" = "ja" ] && git reset --hard "$CHECKPOINT" ;;
    2) read -p "Branch-Name: " b && git checkout -b "$b" "$CHECKPOINT" ;;
    3) git show "$CHECKPOINT" --stat ;;
esac
```

### 2.3 Python-Wrapper

```python
import subprocess
from datetime import datetime
from typing import Optional, List

class CheckpointManager:
    """SK-003: Git Checkpoint Management"""
    
    def create_checkpoint(self, message: str, 
                         checkpoint_type: str = "MILESTONE") -> str:
        """Erstellt neuen Checkpoint"""
        result = subprocess.run(
            ["./checkin.sh", message],
            capture_output=True,
            text=True,
            check=True
        )
        # Extrahiere Tag-Name aus Output
        for line in result.stdout.split('\n'):
            if 'CP-' in line and '✅' in line:
                return line.split(':')[-1].strip()
        return "Unknown"
    
    def list_checkpoints(self, branch: Optional[str] = None) -> List[dict]:
        """Listet alle Checkpoints"""
        result = subprocess.run(
            ["git", "tag", "-l", "CP-*", "--sort=-creatordate"],
            capture_output=True,
            text=True,
            check=True
        )
        
        checkpoints = []
        for line in result.stdout.strip().split('\n'):
            if line:
                # Parse: CP-BRANCH-TYPE-YYYYMMDD-HHMM
                parts = line.split('-')
                if len(parts) >= 5:
                    checkpoints.append({
                        'tag': line,
                        'branch': parts[1],
                        'type': parts[2],
                        'date': f"{parts[3][:4]}-{parts[3][4:6]}-{parts[3][6:8]}",
                        'time': f"{parts[4][:2]}:{parts[4][2:4]}"
                    })
        return checkpoints
    
    def recover(self, checkpoint_tag: str, 
                mode: str = "hard") -> bool:
        """Recovery auf Checkpoint"""
        if mode == "hard":
            subprocess.run(
                ["git", "reset", "--hard", checkpoint_tag],
                check=True
            )
        elif mode == "branch":
            timestamp = datetime.now().strftime("%Y%m%d-%H%M")
            branch_name = f"recovery-{timestamp}"
            subprocess.run(
                ["git", "checkout", "-b", branch_name, checkpoint_tag],
                check=True
            )
        return True
```

---

## 3. Changelog

#### v1.2.0 (2026-03-09)
- [AG-010] Python-Wrapper hinzugefügt
- [Feature] Programmatische Checkpoint-Verwaltung
- [Feature] Liste mit Metadaten

#### v1.1.0 (2026-03-09)
- [AG-010] Automatische Branch-Erkennung
- [Feature] Checkpoint-Typ-Auto-Detection
- [Fix] Bessere Fehlerbehandlung

#### v1.0.0 (2026-03-09)
- [AG-010] Initiale Skripte
- [Feature] checkin.sh
- [Feature] recover.sh

---

## 4. Fehler-Datenbank
| ID | Fehler | Lösung | Behoben in | Referenz |
|----|--------|--------|------------|----------|
| ERR-001 | Git-Root nicht gefunden | Automatische Erkennung mit `git rev-parse` | v1.1.0 | - |

---

*Skill-Version: 1.2.0*
