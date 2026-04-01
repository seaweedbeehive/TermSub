#!/bin/bash
################################################################################
# KIMECO - KOKIEU Checkpoint System
# checkin.sh - Erstellt automatisch einen annotierten Checkpoint-Tag
#
# Verwendung: 
#   ./checkin.sh "Beschreibung der Änderungen"
#   ./checkin.sh                    # Interaktiver Modus
#
# Autor: KIMECO System
# Version: 1.0.0
# Datum: 2026-03-09
################################################################################

set -e

# Farben für Output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Konfiguration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Ins Projekt-Root wechseln
cd "$PROJECT_ROOT"

# Git-Informationen ermitteln
BRANCH=$(git branch --show-current 2>/dev/null) || {
    echo -e "${RED}❌ Fehler: Kein Git Repository gefunden${NC}"
    exit 1
}

TIMESTAMP=$(date +"%Y%m%d-%H%M")
DATETIME=$(date +"%Y-%m-%d %H:%M")
FULL_TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S %z")

# Beschreibung ermitteln
if [ -z "$1" ]; then
    echo -e "${BLUE}📝 Checkpoint-Beschreibung eingeben (Enter für Standard):${NC}"
    read -r MESSAGE
    MESSAGE="${MESSAGE:-Automatischer Checkpoint}"
else
    MESSAGE="$1"
fi

# Branch-Präfix bestimmen
case "$BRANCH" in
    "main") 
        PREFIX="MAIN"
        BRANCH_TYPE="Produktion"
        ;;
    "develop") 
        PREFIX="DEVELOP"
        BRANCH_TYPE="Integration"
        ;;
    "feature-konzept") 
        PREFIX="KONZEPT"
        BRANCH_TYPE="Konzeption"
        ;;
    "feature-daten") 
        PREFIX="DATEN"
        BRANCH_TYPE="Datenarbeit"
        ;;
    "docs") 
        PREFIX="DOCS"
        BRANCH_TYPE="Dokumentation"
        ;;
    feature-*)
        PREFIX="$(echo "$BRANCH" | tr '[:lower:]' '[:upper:]' | sed 's/FEATURE-//')"
        BRANCH_TYPE="Feature"
        ;;
    *) 
        PREFIX="${BRANCH^^}"
        BRANCH_TYPE="Custom"
        ;;
esac

# Checkpoint-Typ ermitteln
echo ""
echo -e "${BLUE}🎯 Checkpoint-Typ wählen:${NC}"
echo "  1) BACKUP    - Sicherung vor Änderungen"
echo "  2) MILESTONE - Wichtiger Meilenstein"
echo "  3) DAILY     - Tägliche Sicherung"
echo "  4) RELEASE   - Release-Version"
echo "  5) RECOVERY  - Wiederherstellungspunkt"
echo "  6) CUSTOM    - Eigener Typ"
read -p "Auswahl (1-6, Standard: BACKUP): " type_choice

case "$type_choice" in
    1|"") CHECKPOINT_TYPE="BACKUP" ;;
    2) CHECKPOINT_TYPE="MILESTONE" ;;
    3) CHECKPOINT_TYPE="DAILY" ;;
    4) CHECKPOINT_TYPE="RELEASE" ;;
    5) CHECKPOINT_TYPE="RECOVERY" ;;
    6) 
        read -p "Eigener Typ: " CHECKPOINT_TYPE
        CHECKPOINT_TYPE="${CHECKPOINT_TYPE^^}"
        ;;
    *) CHECKPOINT_TYPE="BACKUP" ;;
esac

# Tag-Name generieren
TAG_NAME="CP-${PREFIX}-${CHECKPOINT_TYPE}-${TIMESTAMP}"

# Prüfen ob Tag bereits existiert
if git rev-parse "$TAG_NAME" >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Checkpoint $TAG_NAME existiert bereits${NC}"
    TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
    TAG_NAME="CP-${PREFIX}-${CHECKPOINT_TYPE}-${TIMESTAMP}"
    echo -e "${BLUE}📝 Neuer Name: $TAG_NAME${NC}"
fi

# Uncommittete Änderungen prüfen
UNCOMMITTED=$(git status --porcelain)
if [ -n "$UNCOMMITTED" ]; then
    echo ""
    echo -e "${YELLOW}⚠️  Uncommittete Änderungen gefunden:${NC}"
    git status --short
    echo ""
    read -p "Änderungen automatisch committen? (j/n): " commit_choice
    
    if [[ "$commit_choice" =~ ^[Jj]$ ]]; then
        git add -A
        git commit -m "checkpoint: ${MESSAGE}

Branch: ${BRANCH}
Type: ${CHECKPOINT_TYPE}
Timestamp: ${DATETIME}" || {
            echo -e "${YELLOW}⚠️  Keine Änderungen zum Commiten${NC}"
        }
    else
        echo -e "${YELLOW}⚠️  Checkpoint wird ohne aktuelle Änderungen erstellt${NC}"
    fi
fi

# Letzten Commit-Hash ermitteln
LAST_COMMIT=$(git rev-parse --short HEAD)
COMMIT_MSG=$(git log -1 --pretty=%B | head -1)

# Checkpoint-Tag erstellen
echo ""
echo -e "${BLUE}🏷️  Erstelle Checkpoint: ${TAG_NAME}${NC}"

git tag -a "$TAG_NAME" -m "🛡️ CHECKPOINT: ${BRANCH}
═══════════════════════════════════════════════════════════════

📋 INFORMATIONEN
───────────────────────────────────────────────────────────────
Erstellt:       ${FULL_TIMESTAMP}
Branch:         ${BRANCH}
Branch-Type:    ${BRANCH_TYPE}
Checkpoint-Typ: ${CHECKPOINT_TYPE}
Beschreibung:   ${MESSAGE}

🔖 GIT REFERENZ
───────────────────────────────────────────────────────────────
Commit-Hash:    ${LAST_COMMIT}
Commit-Msg:     ${COMMIT_MSG}

🎯 STATUS
───────────────────────────────────────────────────────────────
Recovery-Punkt: JA
Wiederherstellbar: JA
Backup:         JA

═══════════════════════════════════════════════════════════════
KIMECO Checkpoint System v1.0.0
Erstellt mit: ./BPG/checkin.sh"

# Erfolgsmeldung
echo ""
echo -e "${GREEN}✅ Checkpoint erfolgreich erstellt!${NC}"
echo ""
echo -e "${BLUE}📊 Checkpoint-Details:${NC}"
echo "  Name:    $TAG_NAME"
echo "  Branch:  $BRANCH"
echo "  Typ:     $CHECKPOINT_TYPE"
echo "  Zeit:    $DATETIME"
echo "  Commit:  $LAST_COMMIT"
echo ""
echo -e "${BLUE}🔄 Verfügbare Befehle:${NC}"
echo "  Alle Checkpoints anzeigen:  git tag -l 'CP-*'"
echo "  Checkpoint-Details:         git show $TAG_NAME"
echo "  Auf Checkpoint zurück:      git reset --hard $TAG_NAME"
echo "  Recovery-Branch erstellen:  git checkout -b recovery $TAG_NAME"
echo ""
echo -e "${YELLOW}💡 Tipp: Verwende ./BPG/recover.sh für interaktive Wiederherstellung${NC}"

# Log-Eintrag erstellen
LOG_FILE=".git-worktrees/checkpoint-log.txt"
mkdir -p "$(dirname "$LOG_FILE")"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] $TAG_NAME - $BRANCH - $CHECKPOINT_TYPE - $MESSAGE" >> "$LOG_FILE"
