# Skill Consolidation Protocol (SCP)

> Protokoll zur Konsolidierung von Skills aus Worktree Branches und Projekten

---

## 🎯 Zweck

Dieses Protokoll stellt sicher, dass:
1. Skills aus allen Worktree Branches im Hauptbranch konsolidiert werden
2. Keine redundanten Skills erstellt werden
3. Ähnliche Skills zusammengeführt werden
4. Der Hauptbranch als zentrale Skill-Organisation fungiert

---

## 🔄 Konsolidierungs-Workflow

```
Worktree Branch Skills
        ↓
[Skill Discovery]
        ↓
[Redundanz-Check] ←→ Hauptbranch Skills
        ↓
┌───────────────────────────────┐
│ Redundant?                    │
├───────────────────────────────┤
│ JA → [Merge] → [Update]       │
│ NEIN → [Neuer Skill]          │
└───────────────────────────────┘
        ↓
[Hauptbranch Update]
        ↓
[Checkpoint: CP-MAIN-SKILL-XXX]
```

---

## 📋 Schritt-für-Schritt Konsolidierung

### Schritt 1: Skill Discovery

In jedem Worktree Branch:

```bash
# Suche nach Skill-Dateien
find . -name "SK-*.md" -o -name "skill*.md" -o -name "*Skill*.md"

# Suche nach Skill-Verzeichnissen
find . -type d -name "skills" -o -name "skill"

# Suche nach Code-Snippets mit Skill-Potenzial
grep -r "class.*Skill" --include="*.py" .
grep -r "def.*skill" --include="*.py" .
```

### Schritt 2: Redundanz-Check

Vor Erstellung eines neuen Skills:

```markdown
## Redundanz-Checkliste

### Existierende Skills prüfen
- [ ] [[05_Skill_Katalog]] konsultiert
- [ ] Ähnliche Funktionalität vorhanden?
  - SK-XXX: [Beschreibung der Ähnlichkeit]
  - SK-XXX: [Beschreibung der Ähnlichkeit]

### Entscheidung
- [ ] **ERWEITERN** - Bestehenden Skill erweitern
- [ ] **NEU** - Neuer Skill nötig (keine Überschneidung > 70%)

### Begründung für neuen Skill
[Warum ist ein neuer Skill notwendig?]
[Was unterscheidet ihn von bestehenden Skills?]
```

### Schritt 3: Similarity Matrix

| Neuer Skill | SK-001 | SK-002 | SK-003 | ... | Entscheidung |
|-------------|--------|--------|--------|-----|--------------|
| Mein Skill | 20% | 15% | 60% | ... | ERWEITERN SK-003 |

**Regeln:**
- > 70% Ähnlichkeit → Bestehenden Skill erweitern
- 30-70% Ähnlichkeit → Prüfen ob Erweiterung oder neuer Skill
- < 30% Ähnlichkeit → Neuer Skill

### Schritt 4: Konsolidierung durchführen

#### Option A: Bestehenden Skill erweitern

```bash
# 1. Skill-Datei im Hauptbranch öffnen
vim 00_BestPractice/skills/active/SK-XXX.md

# 2. Neue Funktionalität hinzufügen
# 3. Changelog aktualisieren
# 4. Version erhöhen (Minor oder Major)
# 5. Checkpoint erstellen
./checkin.sh "SK-XXX: Konsolidierung aus [Branch] - [Beschreibung]"
```

#### Option B: Neuen Skill erstellen

```bash
# 1. Nächste Skill-ID ermitteln
ls 00_BestPractice/skills/active/SK-*.md | sort -V | tail -1

# 2. Template kopieren
cp 00_BestPractice/skills/SKILL_TEMPLATE.md \
   00_BestPractice/skills/active/SK-XXX_Name.md

# 3. Ausfüllen
# 4. In Katalog eintragen
# 5. Checkpoint erstellen
./checkin.sh "SK-XXX: Neuer Skill aus [Branch] - [Name]"
```

---

## 🛡️ Anti-Redundanz Maßnahmen

### 1. Skill-DNA-Prüfung

Jeder Skill hat eine "DNA" - charakteristische Merkmale:

```yaml
skill_dna:
  primary_function: [Hauptfunktion]
  input_types: [Liste der Input-Typen]
  output_types: [Liste der Output-Typen]
  technologies: [Verwendete Technologien]
  complexity: [low/medium/high]
  scope: [universal/agent_specific]
```

Vor neuer Skill-Erstellung: DNA-Vergleich mit existierenden Skills.

### 2. Automatische Ähnlichkeitsprüfung

```python
def check_skill_similarity(new_skill, existing_skills):
    """
    Prüft Ähnlichkeit zwischen neuem und existierenden Skills
    """
    similarities = {}
    
    for skill_id, skill in existing_skills.items():
        score = 0
        
        # Funktionale Ähnlichkeit
        if new_skill['primary_function'] == skill['primary_function']:
            score += 40
        
        # Input/Output Ähnlichkeit
        input_overlap = set(new_skill['input_types']) & set(skill['input_types'])
        score += len(input_overlap) * 10
        
        output_overlap = set(new_skill['output_types']) & set(skill['output_types'])
        score += len(output_overlap) * 10
        
        # Technologie-Ähnlichkeit
        tech_overlap = set(new_skill['technologies']) & set(skill['technologies'])
        score += len(tech_overlap) * 5
        
        similarities[skill_id] = min(score, 100)
    
    return similarities
```

### 3. Konsolidierungs-Checkliste

Vor Erstellung eines neuen Skills:

- [ ] Alle Worktree Branches nach Skills durchsucht?
- [ ] [[05_Skill_Katalog]] konsultiert?
- [ ] [[06_Skill_Consolidation_Protocol]] angewendet?
- [ ] Ähnlichkeitsprüfung durchgeführt (max. Ähnlichkeit < 70%)?
- [ ] Begründung für neuen Skill dokumentiert?
- [ ] Redundanz-Check von AG-007 (Reviewer) bestätigt?

---

## 📊 Konsolidierungs-Tracking

### Tabelle: Skills aus Worktree Branches

| Branch | Skill/Template | Status | Konsolidiert als | Datum |
|--------|---------------|--------|------------------|-------|
| feature-konzept | AG-001_Konzepter.md | ℹ️ Template | Kein Skill (Agent-Template) | - |
| feature-konzept | AG-002_Architekt.md | ℹ️ Template | Kein Skill (Agent-Template) | - |
| feature-daten | AG-003_Analyse.md | ℹ️ Template | Kein Skill (Agent-Template) | - |
| develop | Pre-commit Hooks | ✅ Skill | SK-006 (Erweitert) | 2026-03-09 |
| develop | Tests | ✅ Skill | SK-007 (Erweitert) | 2026-03-09 |
| feature-daten | JSON Schemas | ✅ Skill | SK-005 (Erweitert) | 2026-03-09 |

---

## 🔄 Automatische Konsolidierung

### Skript: skill_consolidation.sh

```bash
#!/bin/bash
# Automatische Skill-Konsolidierung aus Worktree Branches

TARGET="/path/to/project"
echo "🔍 Suche nach Skills in Worktree Branches..."

for branch in feature-konzept develop feature-daten docs; do
    WORKTREE="$TARGET/.git-worktrees/$branch"
    
    if [ -d "$WORKTREE/skills" ]; then
        echo "📂 Skills in $branch gefunden:"
        
        for skill in "$WORKTREE/skills"/SK-*.md; do
            if [ -f "$skill" ]; then
                skill_name=$(basename "$skill")
                
                # Prüfe ob Skill bereits im Hauptbranch existiert
                if [ -f "$TARGET/00_BestPractice/skills/active/$skill_name" ]; then
                    echo "  ⚠️  $skill_name existiert bereits - Vergleiche Versionen"
                    # Versionsvergleich und Merge-Logik hier
                else
                    echo "  ✅ $skill_name ist neu - Kopiere in Hauptbranch"
                    cp "$skill" "$TARGET/00_BestPractice/skills/active/"
                fi
            fi
        done
    fi
done

echo "✅ Konsolidierung abgeschlossen"
```

---

## 📈 Konsolidierungs-Metriken

| Metrik | Ziel | Aktuell |
|--------|------|---------|
| Redundanz-Rate | < 5% | 0% |
| Konsolidierungszeit | < 10 Min/Skill | 5 Min |
| Branch-Abdeckung | 100% | 100% |

---

## 🔗 Verknüpfungen

- [[05_Skill_Katalog]] - Übersicht aller Skills
- [[SKILL_TEMPLATE]] - Template für neue Skills
- [[SKILL_UPDATE_PROTOKOLL]] - Update nach Einsatz
- [[04_Agenten_Master_System]] - Skill-Einsatz

---

*Dieses Protokoll wird bei jeder Branch-Konsolidierung angewendet.*
*Letzte Aktualisierung: 2026-03-09*
