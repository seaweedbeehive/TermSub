# Skill-Katalog: Universelle Fähigkeiten für alle Agenten

> Zentrale Übersicht aller Skills mit Aktualisierungs-Methodik

---

## 🎯 Grundprinzip: Universelle Skills

**Jeder Skill ist von JEDEM Agenten nutzbar.**

Skills sind **nicht agentenspezifisch** - sie sind universelle Werkzeuge, die je nach Bedarf eingesetzt werden. Ein Skill, der ursprünglich für AG-005 (Developer) entwickelt wurde, kann genauso von AG-001 (Konzepter) oder AG-006 (Dokumentar) verwendet werden.

---

## 📚 Aktive Skills

### Content & Dokumentation

| ID | Skill | Version | Verwendung | Agenten |
|----|-------|---------|------------|---------|
| [[SK-001]] | PDF Report Generation | 1.0.0 | PDF-Berichte erstellen | AG-003, AG-005, AG-006, AG-007, AG-008 |
| [[SK-002]] | Markdown Structure | 1.1.0 | YAML-Frontmatter & Struktur | ALLE |
| [[SK-004]] | Obsidian WikiLinks | 1.1.0 | Verknüpfungen & Graph | ALLE |

### Daten & Validierung

| ID | Skill | Version | Verwendung | Agenten |
|----|-------|---------|------------|---------|
| [[SK-005]] | Data Validation | 1.0.0 | JSON Schema-Validierung | AG-001, AG-002, AG-003, AG-004, AG-005, AG-010 |

### Automation & Workflow

| ID | Skill | Version | Verwendung | Agenten |
|----|-------|---------|------------|---------|
| [[SK-003]] | Git Checkpoint Management | 1.2.0 | Checkpoints & Recovery | ALLE |
| [[SK-006]] | Shell Automation | 1.0.0 | Shell-Skripte | ALLE |

### Entwicklung & Architektur

| ID | Skill | Version | Verwendung | Agenten |
|----|-------|---------|------------|---------|
| [[SK-007]] | Python Module Structure | 1.0.0 | Modulare Architektur | AG-002, AG-005, AG-007 |
| [[SK-008]] | Mermaid Diagrams | 1.0.0 | Diagramm-Generierung | AG-002, AG-004, AG-006, AG-008 |

---

## 🔧 Skill-Verzeichnisstruktur

```
00_BestPractice/skills/
├── SKILL_TEMPLATE.md              # Template für neue Skills
├── 05_Skill_Katalog.md            # Diese Datei
├── active/                        # Aktive Skills
│   ├── SK-001_PDF_Report_Generation.md
│   ├── SK-002_Markdown_Structure.md
│   ├── SK-003_Git_Checkpoint_Management.md
│   ├── SK-004_Obsidian_WikiLinks.md
│   ├── SK-005_Data_Validation.md
│   ├── SK-006_Shell_Automation.md
│   ├── SK-007_Python_Module_Structure.md
│   └── SK-008_Mermaid_Diagrams.md
├── deprecated/                    # Veraltete Skills (nie löschen!)
└── error-log/                     # Fehler-Dokumentation
    └── SK-XXX-ERROR-001.md
```

---

## 🔄 Kontinuierliche Verbesserung: Das SKILL-UPDATE-PROTOKOLL

### Nach JEDEM Skill-Einsatz: 5-Minuten-Review

```markdown
## Skill-Einsatz Review

**Skill:** SK-XXX
**Agent:** AG-XXX
**Datum:** YYYY-MM-DD
**Task:** [Beschreibung]

### 1. Fehler aufgetreten?
- [ ] Nein → Weiter zu 2
- [ ] Ja → Dokumentiere:
  - Fehler: [Beschreibung]
  - Ursache: [Analyse]
  - Lösung: [Implementierung]
  - → Skill-Datei updaten (Changelog + Fehler-Datenbank)
  - → Version erhöhen (z.B. 1.0.0 → 1.0.1)

### 2. Optimierungspotenzial?
- [ ] Nein → Weiter zu 3
- [ ] Ja → Dokumentiere:
  - Idee: [Beschreibung]
  - Implementierung: [Code]
  - → Skill-Datei updaten (Changelog)
  - → Version erhöhen (z.B. 1.0.1 → 1.1.0)

### 3. Neue Anwendungsfälle?
- [ ] Nein → Fertig
- [ ] Ja → Dokumentiere:
  - Anwendungsfall: [Beschreibung]
  - Beispiel: [Code]
  - → Skill-Datei updaten (Abschnitt 1.2)

### 4. Update durchgeführt?
- [ ] Skill-Datei aktualisiert
- [ ] Version erhöht
- [ ] Changelog ergänzt
- [ ] Checkpoint erstellt: `./checkin.sh "SK-XXX: Update [Beschreibung]"`
```

### Update-Prozess Schritt-für-Schritt

#### Schritt 1: Fehler identifizieren

**Während des Einsatzes:**
- Fehler aufschreiben
- Kontext notieren (Input, erwarteter Output, tatsächlicher Output)
- Lösung entwickeln

#### Schritt 2: Skill-Datei bearbeiten

```bash
# 1. Skill-Datei öffnen
# 2. Abschnitt 4 "Fehler-Datenbank" ergänzen
# 3. Abschnitt 3 "Changelog" aktualisieren
# 4. Implementierung korrigieren/erweitern
```

#### Schritt 3: Version erhöhen

| Änderung | Version-Update | Beispiel |
|----------|---------------|----------|
| Bugfix | Patch ++ | 1.0.0 → 1.0.1 |
| Neue Feature | Minor ++ | 1.0.1 → 1.1.0 |
| Breaking Change | Major ++ | 1.1.0 → 2.0.0 |

#### Schritt 4: Checkpoint erstellen

```bash
./checkin.sh "SK-003: Fix [Beschreibung] - Fehler behoben"
```

---

## ⚠️ Wichtige Regeln

### 1. NIEMALS löschen
- Alte Skill-Versionen bleiben erhalten
- Fehler sind Lernmaterial
- Veraltete Skills wandern nach `deprecated/`, werden aber nicht gelöscht

### 2. IMMER dokumentieren
- Jeder Fehler wird dokumentiert
- Jede Lösung wird dokumentiert
- Jede neue Anwendung wird dokumentiert

### 3. KONSISTENT versionieren
- Semantic Versioning (MAJOR.MINOR.PATCH)
- Changelog nach jedem Update
- Klare Commit-Messages

### 4. UNIVERSELL nutzbar
- Keine Agenten-Bindung
- Alle können alle Skills nutzen
- Kombination von Skills erlaubt und erwünscht

---

## 📊 Skill-Nutzungs-Statistiken

### Erfasste Metriken

| Metrik | Beschreibung | Tracking |
|--------|-------------|----------|
| Einsatzhäufigkeit | Wie oft wurde der Skill genutzt? | Pro Skill in Abschnitt 5 |
| Erfolgsrate | % erfolgreicher Einsätze | Pro Skill |
| Durchschnittszeit | Ø Zeit für Skill-Anwendung | Pro Skill |
| Fehlerrate | % fehlgeschlagener Versuche | Pro Skill |

### Monatliches Review

```markdown
# Skill-Nutzungs-Review YYYY-MM

## Häufigste Skills
1. SK-XXX: X Einsätze
2. SK-XXX: X Einsätze

## Skills mit Problemen
- SK-XXX: Y Fehler → Update nötig?

## Neue Skill-Vorschläge
- [Vorschlag 1]

## Updates durchgeführt
- SK-XXX: v1.0.0 → v1.1.0
```

---

## 🆕 Neuen Skill erstellen

### Schritt 1: Template verwenden

```bash
cp SKILL_TEMPLATE.md active/SK-XXX_Name.md
```

### Schritt 2: Ausfüllen

- Alle Abschnitte vervollständigen
- Implementierung einfügen
- Anwendungsfälle definieren

### Schritt 3: In Katalog eintragen

- Diese Datei editieren
- In Tabelle einfügen
- Verknüpfung erstellen

### Schritt 4: Checkpoint

```bash
./checkin.sh "SK-XXX: Neuer Skill [Name] erstellt"
```

---

## 🔗 Skill-Kombinationen

### Empfohlene Kombinationen

| Workflow | Skills | Ergebnis |
|----------|--------|----------|
| Konzept → PDF | SK-002 + SK-001 | Strukturiertes Konzept als PDF |
| Daten → Report | SK-005 + SK-002 + SK-001 | Validierter Daten-Report |
| Architektur → Doku | SK-007 + SK-008 + SK-002 | Modulare Architektur mit Diagrammen |
| Checkpoint → Recovery | SK-003 + SK-006 | Automatisierte Versionskontrolle |

---

## 📈 Skill-Roadmap

### Q1 2026
- [x] SK-001 bis SK-008 initial erstellen
- [ ] Erste Updates basierend auf Einsatz
- [ ] Nutzungsstatistiken sammeln

### Q2 2026
- [ ] Neue Skills nach Bedarf
- [ ] Skill-Optimierungen
- [ ] Kombinations-Workflows dokumentieren

### Q3 2026
- [ ] Automatische Skill-Vorschläge
- [ ] Performance-Optimierung
- [ ] Erweiterte Templates

---

## 📝 Änderungshistorie (dieser Katalog)

| Datum | Änderung | Autor |
|-------|----------|-------|
| 2026-03-09 | Initialer Katalog mit 8 Skills | AG-006 |

---

*Dieser Katalog wird nach jedem Skill-Update aktualisiert.*
*Für Updates: Siehe Abschnitt "Kontinuierliche Verbesserung"*
