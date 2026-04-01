# Skill Master Index

> Zentrale Organisations- und Verteilungsstelle für alle Skills

---

## 🎯 Hauptbranch als Skill-Zentrum

Der **Hauptbranch (main)** ist die alleinige Quelle der Wahrheit für alle Skills.

```
┌─────────────────────────────────────────────────────────┐
│                    MAIN BRANCH                          │
│              (Skill-Zentrale)                           │
├─────────────────────────────────────────────────────────┤
│  00_BestPractice/skills/                                │
│    ├── active/         ← Alle aktiven Skills            │
│    ├── deprecated/     ← Veraltete Skills (nie löschen) │
│    ├── error-log/      ← Fehler-Dokumentation           │
│    ├── SKILL_TEMPLATE.md                                │
│    ├── SKILL_UPDATE_PROTOKOLL.md                        │
│    ├── 05_Skill_Katalog.md                              │
│    ├── 06_Skill_Consolidation_Protocol.md               │
│    └── 07_Skill_Master_Index.md        ← Diese Datei    │
└─────────────────────────────────────────────────────────┘
         ↓
    Verteilung an
         ↓
┌─────────┬─────────┬─────────┬─────────┐
│ feature │ develop │ feature │  docs   │
│-konzept │         │ -daten  │         │
└─────────┴─────────┴─────────┴─────────┘
```

---

## 📋 Aktive Skills (Konsolidiert)

### Content & Dokumentation

| ID | Name | Version | Universal | Status |
|----|------|---------|-----------|--------|
| SK-001 | PDF Report Generation | 1.0.0 | ✅ | 🟢 Aktiv |
| SK-002 | Markdown Structure | 1.1.0 | ✅ | 🟢 Aktiv |
| SK-004 | Obsidian WikiLinks | 1.1.0 | ✅ | 🟢 Aktiv |

### Daten & Validierung

| ID | Name | Version | Universal | Status |
|----|------|---------|-----------|--------|
| SK-005 | Data Validation | 1.0.0 | ✅ | 🟢 Aktiv |

### Automation & Workflow

| ID | Name | Version | Universal | Status |
|----|------|---------|-----------|--------|
| SK-003 | Git Checkpoint Management | 1.2.0 | ✅ | 🟢 Aktiv |
| SK-006 | Shell Automation | 1.0.0 | ✅ | 🟢 Aktiv |

### Entwicklung & Architektur

| ID | Name | Version | Universal | Status |
|----|------|---------|-----------|--------|
| SK-007 | Python Module Structure | 1.0.0 | ✅ | 🟢 Aktiv |
| SK-008 | Mermaid Diagrams | 1.0.0 | ✅ | 🟢 Aktiv |

---

## 🔄 Skill-Verteilung an Worktree Branches

### Automatische Verteilung

```bash
#!/bin/bash
# Skill-Verteilung vom Hauptbranch an Worktrees

TARGET="/Users/FYS/.../00_Christl/CHRISTL"
SKILL_SOURCE="$TARGET/00_BestPractice/skills/active"

echo "🔄 Verteile Skills an Worktree Branches..."

for branch in feature-konzept develop feature-daten docs; do
    WORKTREE="$TARGET/.git-worktrees/$branch"
    SKILL_TARGET="$WORKTREE/.skills-cache"
    
    # Erstelle Cache-Verzeichnis
    mkdir -p "$SKILL_TARGET"
    
    # Kopiere aktuelle Skills
    cp "$SKILL_SOURCE"/SK-*.md "$SKILL_TARGET/"
    
    echo "✅ $branch: Skills aktualisiert"
done

echo "✅ Verteilung abgeschlossen"
```

### Manuelle Verteilung

```bash
# Einzelnen Skill in Worktree kopieren
cp 00_BestPractice/skills/active/SK-001.md .git-worktrees/develop/.skills-cache/
```

---

## 🛡️ Anti-Redundanz System

### Regel 1: Hauptbranch = Single Source of Truth

```
Worktree Branch          Hauptbranch
     ↓                        ↓
  Skill? → Nein → Erstelle → Redundanz-Check
   ↓ Ja                        ↓
  Verwende ← ← ← ← ← ← ← ← ← ← ┘
```

### Regel 2: Keine lokalen Skill-Modifikationen

**Verboten:** Skills direkt in Worktree Branches modifizieren

**Erlaubt:**
1. Skill im Hauptbranch aktualisieren
2. Checkpoint erstellen
3. In Worktrees verteilen

### Regel 3: Redundanz-Check vor Erstellung

```python
def before_skill_creation():
    """
    Muss vor Erstellung jedes neuen Skills ausgeführt werden
    """
    checks = [
        check_05_skill_katalog(),
        check_06_consolidation_protocol(),
        check_similarity_matrix(),
        get_reviewer_approval()  # AG-007
    ]
    return all(checks)
```

---

## 📊 Skill-Statistiken

```yaml
stats:
  total_skills: 8
  universal_skills: 8
  agent_specific_skills: 0
  deprecated_skills: 0
  
  by_category:
    content_docs: 3
    data_validation: 1
    automation: 2
    development: 2
  
  version_distribution:
    v1_0_x: 5
    v1_1_x: 2
    v1_2_x: 1
  
  update_frequency:
    last_30_days: 8
    last_90_days: 8
```

---

## 🎯 Skill-Roadmap

### Q1 2026
- [x] 8 Basis-Skills etabliert
- [x] Konsolidierungs-Protokoll erstellt
- [ ] Erste Updates aus Worktree Einsätzen

### Q2 2026
- [ ] Skills aus Worktree Learnings erweitern
- [ ] Automatische Verteilung etablieren
- [ ] Skill-Nutzungs-Metriken sammeln

### Q3 2026
- [ ] Neue Skills nach Bedarf
- [ ] Skill-Kombinations-Workflows
- [ ] Performance-Optimierung

---

## 🔗 Schnellzugriff

| Dokument | Zweck |
|----------|-------|
| [[05_Skill_Katalog]] | Vollständige Skill-Beschreibungen |
| [[06_Skill_Consolidation_Protocol]] | Konsolidierung aus Branches |
| [[SKILL_TEMPLATE]] | Template für neue Skills |
| [[SKILL_UPDATE_PROTOKOLL]] | Nach-Einsatz Review |

---

*Hauptbranch: Einzige Quelle der Wahrheit*
*Updates nur im Hauptbranch, dann Verteilung*
*Letzte Aktualisierung: 2026-03-09*
