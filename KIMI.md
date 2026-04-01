# KIMI SYSTEM KONTEXT

> Diese Datei wird zu Beginn JEDER Session gelesen.
> 
> **Projekt:** VideoTranslationPro  
> **Status:** Initialisierung  
> **Letzte Aktualisierung:** 2026-04-01  
> **Checkpoint:** CP-MAIN-INITIAL-20260401-0900

---

## 🎯 Projektübersicht

| Attribut | Wert |
|----------|------|
| **Name** | VideoTranslationPro |
| **Ziel** | [Wird vom Benutzer definiert] |
| **Status** | Phase 1: Initialisierung |
| **Startdatum** | 2026-04-01 |
| **Sprache** | Deutsch (Dokumentation), Englisch (Code je nach Konvention) |

### Kurzbeschreibung
Dieses Projekt wurde mit dem **KIMECO Best Practice Guide für Agentische KI** initialisiert. Es nutzt:
- **Multi-Agenten-System** (AG-001 bis AG-012)
- **Git-Workflow mit Checkpoints** (.git-worktrees/)
- **Skill-Management** (universelle Wiederverwendbarkeit)
- **Automatische Berichterstellung** (99_Berichte/)

---

## 👤 Meine Rolle

Ich agiere als **KI-Partner** mit folgenden Verantwortlichkeiten:

1. **Strategische Beratung** - Konzepte entwickeln und bewerten
2. **Technische Umsetzung** - Code qualitativ hochwertig implementieren
3. **Dokumentation** - Wissen nachvollziehbar aufbereiten
4. **Qualitätssicherung** - Reviews und Validierungen durchführen
5. **Projekt-Management** - Checkpoints, Berichte, Tracking

---

## 📁 Projektstruktur

```
VideoTranslationPro/
├── 🧠 KIMI.md                    ← System-Kontext (Diese Datei)
├── 📂 01_Docs/                    ← Konzeptionelle Dokumente
│   ├── 01_Konzept/
│   ├── 02_Architektur/
│   └── 03_Anforderungen/
├── 📂 02_Code/                    ← Implementierung
│   ├── src/
│   ├── tests/
│   └── config/
├── 📂 03_Data/                    ← Daten & Analysen
│   ├── raw/
│   ├── processed/
│   └── external/
├── 📂 04_Output/                  ← Output & Ergebnisse
│   ├── reports/
│   ├── exports/
│   └── demos/
├── 📂 99_Berichte/                ← Task-Abschluss-Berichte
│   └── YYYY-MM-DD_HH-MM_Task.md
├── 📂 BPG/                        ← Best Practice Guides
│   ├── 00_BestPractice_Guide_Agentische_KI.md
│   ├── 01_Git_Workflow_&_Checkpoints.md
│   ├── 02_Agenten_Katalog.md
│   ├── 03_Agenten_Vorschlag_Template.md
│   ├── 04_Agenten_Master_System.md
│   ├── checkin.sh
│   └── recover.sh
├── 00_Masterindex.md              ← Navigation & Links
└── .git/                          ← Git Repository
    └── .git-worktrees/            ← Worktree-Verzeichnisse
        ├── develop/
        ├── feature-konzept/
        ├── feature-daten/
        └── docs/
```

---

## ⚖️ Grundsätze (Nicht verhandelbar)

### Qualitätsgrundsätze
1. **Kein Bauchgefühl – nur Daten** - Entscheidungen werden begründet
2. **Hypothesen klar trennen von Fakten** - Unsicherheiten transparent kommunizieren
3. **Iteration über Perfektion** - Brauchbar und dokumentiert schlägt perfekt und vergessen
4. **Checkpoints vor Risiko** - Jede wichtige Änderung wird versioniert

### Arbeitsgrundsätze
5. **Eine Aufgabe = Ein Agent** - Spezialisierung maximiert Qualität
6. **Kontext vor Ausführung** - Kimi.md wird zu Beginn jeder Session gelesen
7. **Bericht nach jeder Aufgabe** - Kein Task ohne Dokumentation
8. **Verknüpfung schafft Wissen** - Obsidian-kompatible Links [[Dokument]]

### Technische Grundsätze
9. **Git als Gedächtnis** - Jedes Commit ist Teil der Projekthistorie
10. **Worktrees für Parallelität** - Feature-Branches isoliert bearbeiten
11. **Skills wiederverwenden** - Redundanz vermeiden durch universelle Skills

---

## 📊 Leitmetriken

| Metrik | Ziel | Aktuell | Status |
|--------|------|---------|--------|
| Checkpoint-Rate | > 90% | 0% | ⏳ |
| Berichtsrate | 100% | 0% | ⏳ |
| Agenten-Match-Rate | > 95% | - | ⏳ |
| Code-Qualität | > 4.0/5 | - | ⏳ |
| Dokumentationsabdeckung | > 80% | 0% | ⏳ |

---

## 📋 Output-Standards

### Dokumente
- **Format:** Markdown mit YAML-Frontmatter
- **Links:** Obsidian-kompatible WikiLinks `[[Dokument]]`
- **Struktur:** Klare Hierarchie mit Überschriften
- **Zeitstempel:** `YYYY-MM-DD_HH-MM` in Dateinamen

### Code
- **Sprache:** Je nach Projekt (wird definiert)
- **Style:** Konsistent, dokumentiert, getestet
- **Versionierung:** Semantische Versionierung
- **Review:** Vor Merge in develop

### Berichte
- **Ort:** `99_Berichte/YYYY-MM-DD_HH-MM_Taskname.md`
- **Template:** Siehe BPG Phase 6
- **Inhalt:** Ausgeführte Arbeit, Ergebnisse, Fehler, nächste Schritte

---

## ✅ Checklisten

### Vor JEDER Session
- [ ] `KIMI.md` gelesen und verstanden
- [ ] Aktuellen Branch/Worktree geprüft
- [ ] Änderungs-Detection durchgeführt (`git status`)
- [ ] Neue/geänderte Dateien integriert
- [ ] Passenden Agenten identifiziert (AG-001 bis AG-012)

### Nach JEDER Aufgabe
- [ ] Änderungen committet (`git add -A && git commit`)
- [ ] Checkpoint erstellt (`./BPG/checkin.sh "Beschreibung"`)
- [ ] Bericht erstellt in `99_Berichte/`
- [ ] Dokumente verknüpft (`[[Links]]`)
- [ ] Masterindex aktualisiert
- [ ] Offene Punkte dokumentiert

### Bei Projekt-Meilensteinen
- [ ] Alle Tests erfolgreich
- [ ] Dokumentation aktualisiert
- [ ] Review durch AG-007 durchgeführt
- [ ] Checkpoint vom Typ MILESTONE erstellt
- [ ] `Kimi.md` aktualisiert

---

## 🤖 Agenten-Quick-Reference

| Du möchtest... | Agent | Worktree |
|----------------|-------|----------|
| Eine neue Idee entwickeln | AG-001 Konzepter | feature-konzept |
| Ein System designen | AG-002 Architekt | feature-konzept |
| Daten analysieren | AG-003 Daten-Analyst | feature-daten |
| Recherche betreiben | AG-004 Researcher | feature-daten |
| Code schreiben | AG-005 Developer | develop |
| Dokumentieren | AG-006 Dokumentar | docs |
| Qualität prüfen | AG-007 Reviewer | develop |
| Eine Demo bauen | AG-008 Demo-Builder | develop |
| Branches mergen | AG-009 Integrator | develop |
| Checkpoint erstellen | AG-010 Checkpoint-Manager | main |
| Demo validieren | AG-011 Scenario-Planner | docs |
| Projekt evaluieren | AG-012 Projekt-Evaluator | docs |

---

## 🔗 Wichtige Links

- [[00_Masterindex]] - Zentrale Navigation
- [[BPG/00_BestPractice_Guide_Agentische_KI]] - Vollständiger Guide
- [[BPG/02_Agenten_Katalog]] - Alle Agenten
- [[BPG/01_Git_Workflow_&_Checkpoints]] - Git-Workflow

---

## 📝 Offene Punkte / Next Steps

| # | Aufgabe | Priorität | Agent | Status |
|---|---------|-----------|-------|--------|
| 1 | Projektvision und Ziele definieren | Hoch | AG-001 | ⏳ |
| 2 | Technische Anforderungen erfassen | Hoch | AG-002 | ⏳ |
| 3 | Datenquellen identifizieren | Mittel | AG-003 | ⏳ |
| 4 | Architektur-Konzept erstellen | Mittel | AG-002 | ⏳ |
| 5 | Erste Implementierung starten | Niedrig | AG-005 | ⏳ |

---

*Dieses Dokument lebt – bei Prozessänderungen aktualisieren.*
*Checkpoint: CP-MAIN-INITIAL-20260401-0900*
