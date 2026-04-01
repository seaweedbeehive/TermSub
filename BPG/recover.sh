#!/bin/bash
################################################################################
# KIMECO - KOKIEU Checkpoint System
# recover.sh - Interaktiver Recovery-Assistent
#
# Verwendung:
#   ./recover.sh                    # Interaktiver Modus
#   ./recover.sh --list             # Alle Checkpoints auflisten
#   ./recover.sh --last             # Letzten Checkpoint wiederherstellen
#   ./recover.sh CP-XXX-XXX-XXXX    # Spezifischen Checkpoint nutzen
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
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Konfiguration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Ins Projekt-Root wechseln
cd "$PROJECT_ROOT"

# Header anzeigen
show_header() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}           🛡️  KIMECO CHECKPOINT RECOVERY SYSTEM               ${CYAN}║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# Liste aller Checkpoints anzeigen
list_checkpoints() {
    echo -e "${BLUE}📋 Verfügbare Checkpoints:${NC}"
    echo ""
    
    # Checkpoints mit Details abrufen
    local count=0
    while IFS= read -r tag; do
        count=$((count + 1))
        local date_info=$(git log -1 --format=%ai "$tag" 2>/dev/null | cut -d' ' -f1-2)
        local subject=$(git tag -l --format='%(contents:subject)' "$tag" 2>/dev/null | head -1)
        local body=$(git tag -l --format='%(contents:body)' "$tag" 2>/dev/null)
        local branch=$(echo "$body" | grep "^Branch:" | cut -d':' -f2 | xargs)
        local type=$(echo "$body" | grep "^Checkpoint-Typ:" | cut -d':' -f2 | xargs)
        
        # Farbe basierend auf Typ
        local type_color="$NC"
        case "$type" in
            *MILESTONE*) type_color="$GREEN" ;;
            *BACKUP*) type_color="$YELLOW" ;;
            *RECOVERY*) type_color="$RED" ;;
            *RELEASE*) type_color="$CYAN" ;;
        esac
        
        printf "${CYAN}%2d)${NC} ${YELLOW}%-35s${NC} ${BLUE}%s${NC}\n" "$count" "$tag" "$date_info"
        printf "    Branch: ${GREEN}%-15s${NC} Typ: ${type_color}%s${NC}\n" "${branch:-unbekannt}" "${type:-BACKUP}"
        echo ""
    done < <(git tag -l "CP-*" --sort=-creatordate)
    
    if [ $count -eq 0 ]; then
        echo -e "${YELLOW}⚠️  Keine Checkpoints gefunden${NC}"
        echo -e "${BLUE}💡 Tipp: Verwende ./BPG/checkin.sh um Checkpoints zu erstellen${NC}"
        return 1
    fi
    
    return 0
}

# Checkpoint-Details anzeigen
show_checkpoint_details() {
    local checkpoint="$1"
    echo ""
    echo -e "${BLUE}📊 Checkpoint-Details für ${YELLOW}$checkpoint${NC}:"
    echo -e "${CYAN}───────────────────────────────────────────────────────────────${NC}"
    git show "$checkpoint" --no-patch --format="%ai%n%an <%ae>%n%n%B" 2>/dev/null || {
        echo -e "${RED}❌ Checkpoint nicht gefunden${NC}"
        return 1
    }
    echo -e "${CYAN}───────────────────────────────────────────────────────────────${NC}"
    echo ""
    
    # Geänderte Dateien anzeigen
    echo -e "${BLUE}📁 Enthaltene Dateien:${NC}"
    git show "$checkpoint" --name-only --format="" | head -20
    local total_files=$(git show "$checkpoint" --name-only --format="" | wc -l)
    if [ "$total_files" -gt 20 ]; then
        echo -e "${BLUE}... und $((total_files - 20)) weitere Dateien${NC}"
    fi
    echo ""
}

# Interaktive Recovery
interactive_recovery() {
    show_header
    
    # Aktuellen Status anzeigen
    local current_branch=$(git branch --show-current)
    local current_commit=$(git rev-parse --short HEAD)
    echo -e "${BLUE}📍 Aktueller Status:${NC}"
    echo "  Branch: $current_branch"
    echo "  Commit: $current_commit"
    echo ""
    
    # Checkpoints anzeigen
    if ! list_checkpoints; then
        exit 1
    fi
    
    # Auswahl treffen
    echo ""
    read -p "Nummer des Recovery-Checkpoints (oder 'q' für Abbruch): " choice
    
    if [[ "$choice" == "q" ]]; then
        echo -e "${BLUE}👋 Abbruch${NC}"
        exit 0
    fi
    
    # Checkpoint anhand der Nummer ermitteln
    local checkpoint=$(git tag -l "CP-*" --sort=-creatordate | sed -n "${choice}p")
    
    if [ -z "$checkpoint" ]; then
        echo -e "${RED}❌ Ungültige Auswahl${NC}"
        exit 1
    fi
    
    # Details anzeigen
    show_checkpoint_details "$checkpoint"
    
    # Recovery-Optionen
    echo -e "${BLUE}🔧 Recovery-Optionen:${NC}"
    echo ""
    echo -e "  ${YELLOW}1)${NC} HARD RESET ${RED}(⚠️  Alle aktuellen Änderungen werden verworfen!)${NC}"
    echo -e "  ${YELLOW}2)${NC} Neuen Branch erstellen ${GREEN}(✅ Sicher, empfohlen)${NC}"
    echo -e "  ${YELLOW}3)${NC} Worktree aus Checkpoint erstellen ${GREEN}(✅ Parallel arbeiten)${NC}"
    echo -e "  ${YELLOW}4)${NC} Nur anzeigen (keine Änderung)"
    echo -e "  ${YELLOW}5)${NC} Abbrechen"
    echo ""
    read -p "Wahl (1-5): " action
    
    case "$action" in
        1)
            echo ""
            echo -e "${RED}╔═══════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${RED}║${NC}  ⚠️  WARNUNG: HARD RESET                                  ${RED}║${NC}"
            echo -e "${RED}║${NC}                                                              ${RED}║${NC}"
            echo -e "${RED}║${NC}  Alle uncommitteten und seit dem Checkpoint gemachten      ${RED}║${NC}"
            echo -e "${RED}║${NC}  Änderungen gehen VERLOREN!                                ${RED}║${NC}"
            echo -e "${RED}╚═══════════════════════════════════════════════════════════════╝${NC}"
            echo ""
            read -p "Zur Bestätigung 'JA' eingeben: " confirm
            
            if [ "$confirm" = "JA" ]; then
                git reset --hard "$checkpoint"
                echo ""
                echo -e "${GREEN}✅ Reset auf $checkpoint durchgeführt${NC}"
                echo ""
                echo -e "${BLUE}📍 Neuer Status:${NC}"
                echo "  Branch: $(git branch --show-current)"
                echo "  Commit: $(git rev-parse --short HEAD)"
            else
                echo -e "${YELLOW}⚠️  Abbruch - Keine Änderungen vorgenommen${NC}"
            fi
            ;;
            
        2)
            echo ""
            read -p "Name für den Recovery-Branch: " branchname
            
            if [ -z "$branchname" ]; then
                branchname="recovery-$(date +%Y%m%d-%H%M)"
                echo -e "${BLUE}Standard-Name verwendet: $branchname${NC}"
            fi
            
            # Prüfen ob Branch existiert
            if git rev-parse --verify "$branchname" >/dev/null 2>&1; then
                echo -e "${YELLOW}⚠️  Branch '$branchname' existiert bereits${NC}"
                branchname="${branchname}-$(date +%H%M%S)"
                echo -e "${BLUE}Neuer Name: $branchname${NC}"
            fi
            
            git checkout -b "$branchname" "$checkpoint"
            echo ""
            echo -e "${GREEN}✅ Recovery-Branch '$branchname' erstellt${NC}"
            echo ""
            echo -e "${BLUE}📍 Status:${NC}"
            echo "  Branch: $branchname"
            echo "  Checkpoint: $checkpoint"
            echo ""
            echo -e "${BLUE}💡 Sie können jetzt in diesem Branch arbeiten${NC}"
            ;;
            
        3)
            echo ""
            read -p "Name für den Worktree-Ordner: " worktree_name
            
            if [ -z "$worktree_name" ]; then
                worktree_name="recovery-$(date +%H%M)"
            fi
            
            local worktree_path=".git-worktrees/$worktree_name"
            
            if [ -d "$worktree_path" ]; then
                echo -e "${YELLOW}⚠️  Worktree existiert bereits${NC}"
                worktree_name="${worktree_name}-$(date +%S)"
                worktree_path=".git-worktrees/$worktree_name"
            fi
            
            # Neuen Branch für Worktree erstellen
            local wt_branch="wt-$worktree_name"
            git branch "$wt_branch" "$checkpoint"
            git worktree add "$worktree_path" "$wt_branch"
            
            echo ""
            echo -e "${GREEN}✅ Worktree erstellt: $worktree_path${NC}"
            echo ""
            echo -e "${BLUE}📍 Zum Worktree wechseln:${NC}"
            echo "  cd $worktree_path"
            echo ""
            echo -e "${BLUE}💡 Der Worktree basiert auf Checkpoint: $checkpoint${NC}"
            ;;
            
        4)
            echo -e "${BLUE}📊 Nur Anzeige-Modus${NC}"
            git show "$checkpoint" --stat
            ;;
            
        5|*)
            echo -e "${BLUE}👋 Abbruch - Keine Änderungen${NC}"
            exit 0
            ;;
    esac
}

# Letzten Checkpoint wiederherstellen
restore_last() {
    show_header
    
    local last_checkpoint=$(git tag -l "CP-*" --sort=-creatordate | head -1)
    
    if [ -z "$last_checkpoint" ]; then
        echo -e "${RED}❌ Keine Checkpoints gefunden${NC}"
        exit 1
    fi
    
    echo -e "${BLUE}🔄 Letzter Checkpoint: ${YELLOW}$last_checkpoint${NC}"
    echo ""
    
    # Automatisch neuen Branch erstellen
    local branchname="recovery-last-$(date +%H%M)"
    git checkout -b "$branchname" "$last_checkpoint"
    
    echo -e "${GREEN}✅ Wiederherstellung abgeschlossen${NC}"
    echo "  Branch: $branchname"
    echo "  Checkpoint: $last_checkpoint"
}

# Schnelle Wiederherstellung eines spezifischen Checkpoints
restore_specific() {
    local checkpoint="$1"
    
    if ! git rev-parse "$checkpoint" >/dev/null 2>&1; then
        echo -e "${RED}❌ Checkpoint '$checkpoint' nicht gefunden${NC}"
        echo ""
        echo -e "${BLUE}Verfügbare Checkpoints:${NC}"
        git tag -l "CP-*" | head -10
        exit 1
    fi
    
    show_header
    show_checkpoint_details "$checkpoint"
    
    local branchname="recovery-$(date +%H%M)"
    git checkout -b "$branchname" "$checkpoint"
    
    echo -e "${GREEN}✅ Wiederherstellung auf Branch '$branchname' abgeschlossen${NC}"
}

# Hilfe anzeigen
show_help() {
    echo "KIMECO Checkpoint Recovery System"
    echo ""
    echo "Verwendung:"
    echo "  ./recover.sh                    Interaktiver Recovery-Assistent"
    echo "  ./recover.sh --list, -l         Alle Checkpoints auflisten"
    echo "  ./recover.sh --last             Letzten Checkpoint wiederherstellen"
    echo "  ./recover.sh CP-XXX-XXX-XXXX    Spezifischen Checkpoint wiederherstellen"
    echo "  ./recover.sh --help, -h         Diese Hilfe anzeigen"
    echo ""
    echo "Beispiele:"
    echo "  ./recover.sh                    # Interaktiver Modus"
    echo "  ./recover.sh --last             # Schnellwiederherstellung"
    echo "  ./recover.sh CP-MAIN-BACKUP-20260309-1301"
    echo ""
    echo "Für mehr Informationen siehe BPG/01_Git_Workflow_&_Checkpoints.md"
}

# Hauptlogik
case "${1:-}" in
    --list|-l)
        show_header
        list_checkpoints
        ;;
    --last)
        restore_last
        ;;
    --help|-h)
        show_help
        ;;
    "")
        interactive_recovery
        ;;
    CP-*)
        restore_specific "$1"
        ;;
    *)
        echo -e "${RED}❌ Unbekannte Option: $1${NC}"
        echo ""
        show_help
        exit 1
        ;;
esac

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  KIMECO Checkpoint Recovery System v1.0.0${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
