# Agenten-Master-System

> Zentrale Steuerung und Koordination aller KI-Agenten. Dieses Dokument definiert den Auswahl-Prozess, die Aktivierung und die Nutzung der Agenten.

---

## 🎯 Grundprinzip: Der Agenten-Orchestrator

**Jede Aufgabe durchläuft den Agenten-Auswahl-Prozess.**

Bevor eine Aufgabe ausgeführt wird, analysiert das System:
1. Welche Domäne? → Agenten-Filter
2. Passender Agent vorhanden? → Ja: Aktivieren / Nein: Vorschlagen
3. Worktree gewechselt? → Ja: Wechseln
4. Aufgabe ausführen → Nach Best Practices
5. Checkpoint → Dokumentation

---

## 🔍 Agenten-Auswahl-Algorithmus

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
    
ELSE:
    → Agenten-Vorschlag erstellen
    → Template ausfüllen: [[03_Agenten_Vorschlag_Template]]
    → Benutzer um Genehmigung fragen
    → Bei Genehmigung: Neuen Agenten erstellen
    → Mit neuem Agenten fortfahren
```

---

## 🤖 Agenten-Aktivierungs-Protokoll

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
- [ ] Worktree geprüft
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
**Checkpoint erstellt:** [CP-XXX-XXX-XXXXXXX-XXXX]
**Bericht verfasst:** [Ja/Nein]
**Nächste Schritte:** [Beschreibung]
```

---

## 📋 Agenten-Quick-Reference

### Sofort-Auswahl nach Aufgaben-Typ

| Du möchtest... | Agent | Befehl/Workflow |
|----------------|-------|-----------------|
| Eine neue Idee entwickeln | AG-001 | `Konzepter` + Input |
| Ein System designen | AG-002 | `Architekt` + Anforderungen |
| Daten analysieren | AG-003 | `Daten-Analyst` + Datensatz |
| Recherche betreiben | AG-004 | `Researcher` + Thema |
| Code schreiben | AG-005 | `Developer` + Spezifikation |
| Dokumentieren | AG-006 | `Dokumentar` + Zielgruppe |
| Qualität prüfen | AG-007 | `Reviewer` + Artefakt |
| Eine Demo bauen | AG-008 | `Demo-Builder` + Features |
| Branches mergen | AG-009 | `Integrator` + Branches |
| Checkpoint erstellen | AG-010 | `Checkpoint-Manager` + Typ |

### Worktree-zu-Agenten-Mapping

| Worktree | Primäre Agenten | Sekundäre Agenten |
|----------|-----------------|-------------------|
| main | AG-010 | - |
| develop | AG-005, AG-007, AG-008, AG-009 | AG-010 |
| feature-konzept | AG-001, AG-002 | AG-004, AG-007 |
| feature-daten | AG-003, AG-004 | AG-007 |
| docs | AG-006 | AG-007, AG-010 |

---

## 🔄 Multi-Agenten-Workflows

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
[Demo bereit]
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

---

## 🆕 Agenten-Vorschlags-Prozess (detailliert)

### Schritt-für-Schritt

#### 1. Erkennen

**Signal: Kein passender Agent gefunden**

```
System: "Kein passender Agent für Aufgabe: [Beschreibung]"
System: "Domäne: [Domäne] erkannt"
System: "Bestehende Agenten in dieser Domäne: [Liste oder 'Keine']"
System: "→ NEUEN AGENTEN VORSCHLAGEN?"
```

#### 2. Analysieren

**Fragen zur Klärung:**

1. **Wie oft** wird diese Aufgabenart voraussichtlich anfallen?
   - [ ] Einmalig → Bestehenden Agenten anpassen
   - [ ] Gelegentlich → Bestehenden Agenten erweitern
   - [ ] Regelmäßig → Neuen Agenten erstellen

2. **Welche spezifische Expertise** wird benötigt?
   - [ ] Allgemein → Bestehender Agent kann erweitert werden
   - [ ] Spezialisiert → Neuer Agent sinnvoll

3. **Wie komplex** ist die Aufgabe?
   - [ ] Einfach → Bestehender Agent
   - [ ] Komplex → Spezialisierter Agent

#### 3. Vorschlag erstellen

**Template verwenden:** [[03_Agenten_Vorschlag_Template]]

```markdown
# Agenten-Vorschlag: V-AG-XXX-[Datum]

## Zusammenfassung
- **Name:** [Vorgeschlagener Name]
- **Domäne:** [Domäne]
- **Unterschied zu AG-XXX:** [Erklärung]
- **Erwartete Nutzung:** [Häufig/Mittel/Selten]

## System-Prompt (Entwurf)
```
[Prompt]
```

## Empfehlung
[Erstellen / Nicht erstellen / Erweitern]
```

#### 4. Entscheidung

**Benutzer-Entscheidung einholen:**

```
┌─────────────────────────────────────────────────────────┐
│  NEUEN AGENTEN VORSCHLAGEN                              │
├─────────────────────────────────────────────────────────┤
│  Name: [Name]                                           │
│  Domäne: [Domäne]                                       │
│  Unterschied: [Beschreibung]                            │
├─────────────────────────────────────────────────────────┤
│  [ ] Agenten erstellen                                  │
│  [ ] Bestehenden Agenten erweitern                      │
│  [ ] Einmalig ohne neuen Agenten arbeiten               │
│  [ ] Vorschlag ablehnen                                 │
└─────────────────────────────────────────────────────────┘
```

#### 5. Implementieren (falls gewählt)

**Bei "Agenten erstellen":**

1. Neue AG-XXX ID vergeben (nächste freie Nummer)
2. In [[02_Agenten_Katalog]] eintragen
3. System-Prompt finalisieren
4. Templates erstellen
5. Test-Aufgabe durchführen
6. Dokumentation aktualisieren
7. Checkpoint setzen

**Bei "Bestehenden erweitern":**

1. Bestehenden Agenten identifizieren
2. System-Prompt erweitern
3. Neue Aktivierungs-Trigger hinzufügen
4. Dokumentation aktualisieren
5. Checkpoint setzen

---

## 📊 Agenten-Nutzungs-Monitoring

### Tracking-Tabelle

```markdown
# Agenten-Nutzungsstatistik

## Monat: YYYY-MM

| Agent | Einsätze | Ø Dauer | Qualität | Häufigste Aufgabe |
|-------|----------|---------|----------|-------------------|
| AG-001 | 0 | - | - | - |
| AG-002 | 0 | - | - | - |
| AG-003 | 0 | - | - | - |
| AG-004 | 0 | - | - | - |
| AG-005 | 0 | - | - | - |
| AG-006 | 0 | - | - | - |
| AG-007 | 0 | - | - | - |
| AG-008 | 0 | - | - | - |
| AG-009 | 0 | - | - | - |
| AG-010 | 0 | - | - | - |

## Insights
- **Meistgenutzter Agent:** [Agent]
- **Seltenster Agent:** [Agent]
- **Durchschnittsqualität:** [X/5]
- **Vorschlag für neue Agenten:** [Ja/Nein] → [Domäne]
```

### Review-Fragen (monatlich)

1. **Werden alle Agenten genutzt?**
   - Nicht genutzte Agenten → Prüfen ob nötig oder entfernen

2. **Gibt es wiederholende Aufgaben ohne Agent?**
   → Neuen Agenten vorschlagen

3. **Gibt es Qualitätsprobleme bei bestehenden Agenten?**
   → System-Prompts optimieren

4. **Sind die Worktree-Zuordnungen sinnvoll?**
   → Anpassen falls nötig

---

## 🚨 Fehlerbehandlung

### Fall 1: Falscher Agent gewählt

**Erkennung:** Output passt nicht zur Aufgabe

**Lösung:**
1. Aktuelle Arbeit pausieren/speichern
2. Korrekten Agenten identifizieren
3. Input für korrekten Agenten aufbereiten
4. Mit korrektem Agenten fortfahren
5. Dokumentieren was schiefgelaufen ist

### Fall 2: Agent nicht verfügbar

**Erkennung:** Agent wird aufgerufen aber nicht gefunden

**Lösung:**
1. [[02_Agenten_Katalog]] prüfen
2. Falls nicht vorhanden → Neuen Agenten vorschlagen
3. Falls vorhanden aber nicht gefunden → Katalog-Struktur prüfen

### Fall 3: Zirkelbezug zwischen Agenten

**Erkennung:** Agent A ruft Agent B, der Agent A aufruft

**Lösung:**
1. Zirkel erkennen und unterbrechen
2. Klare Aufgabentrennung definieren
3. Eventuell neuen Agenten erstellen für überlappende Funktionalität

---

## 🔗 Integration mit Best Practices

### Verknüpfte Dokumente

- [[00_BestPractice_Guide_Agentische_KI]] - Allgemeine Best Practices (INKL. Phase 11: Agenten-Git-Integration)
- [[00_BestPractice_Guide_Agentische_KI#Phase 11: Agenten-Git-Integration & Branch-Workflows]] - Detaillierte Git-Integration
- [[01_Git_Workflow_&_Checkpoints]] - Versionskontrolle
- [[02_Agenten_Katalog]] - Agenten-Details
- [[03_Agenten_Vorschlag_Template]] - Vorschlag-Template
- [[04_Agenten_Master_System]] - Dieses Dokument

### Worktree-Zuordnung (Quick Reference)

| Agent | Worktree | Branch | Siehe auch |
|-------|----------|--------|------------|
| AG-001/AG-002 | `.git-worktrees/feature-konzept/` | `feature-konzept` | [[00_BestPractice_Guide_Agentische_KI#Agenten-Worktree-Zuordnung]] |
| AG-003/AG-004 | `.git-worktrees/feature-daten/` | `feature-daten` | [[00_BestPractice_Guide_Agentische_KI#Agenten-Worktree-Zuordnung]] |
| AG-005/AG-007/AG-008/AG-009 | `.git-worktrees/develop/` | `develop` | [[00_BestPractice_Guide_Agentische_KI#Agenten-Worktree-Zuordnung]] |
| AG-006 | `.git-worktrees/docs/` | `docs` | [[00_BestPractice_Guide_Agentische_KI#Agenten-Worktree-Zuordnung]] |
| AG-010 | Root (`.`) | `main` | [[00_BestPractice_Guide_Agentische_KI#Agenten-Worktree-Zuordnung]] |

### Checklisten-Integration

**Vor Agenten-Auswahl:**
- [ ] Aufgabe verstanden?
- [ ] Domäne identifiziert?
- [ ] Bestehende Artefakte geprüft?

**Nach Agenten-Auswahl:**
- [ ] Richtiger Worktree?
- [ ] Input vollständig?
- [ ] System-Prompt geladen?

**Nach Aufgaben-Ausführung:**
- [ ] Output-Format korrekt?
- [ ] Qualität geprüft?
- [ ] Checkpoint gesetzt?
- [ ] Bericht erstellt?

---

## 🚀 Quick Start: Erste Agenten-Nutzung

### Beispiel: Neue Konzeptaufgabe

```
1. "Ich möchte ein Konzept für X entwickeln"
   ↓
2. System erkennt: Domäne = Konzeption
   → Agent AG-001 Konzepter passt
   ↓
3. Worktree-Wechsel prüfen:
   → Aktuell in main
   → Wechsel zu .git-worktrees/feature-konzept
   ↓
4. Input vorbereiten:
   → Kimi.md gelesen
   → Ziele definiert
   → Rahmenbedingungen notiert
   ↓
5. AG-001 Konzepter aktivieren:
   → System-Prompt laden
   → Input übergeben
   ↓
6. Konzept entwickeln
   ↓
7. Output verifizieren
   ↓
8. Checkpoint erstellen:
   ./BPG/checkin.sh "AG-001: Konzept für X"
   ↓
9. Bericht erstellen in 99_Berichte/
```

---

## 📈 Weiterentwicklung

### Roadmap

- [ ] **Q1:** Basis-Agenten etablieren (AG-001 bis AG-010)
- [ ] **Q2:** Nutzungsstatistiken sammeln
- [ ] **Q3:** Agenten-Optimierung basierend auf Statistiken
- [ ] **Q4:** Neue Agenten nach Bedarf

### Mögliche zukünftige Agenten

- **AG-011 UI/UX-Designer:** Interface-Design
- **AG-012 Test-Engineer:** Testplanung & -durchführung
- **AG-013 DevOps-Engineer:** Deployment & Infrastruktur
- **AG-014 Security-Experte:** Sicherheitsprüfungen
- **AG-015 Performance-Optimizer:** Performance-Analyse

---

*Letzte Aktualisierung: 2026-03-09*  
*Checkpoint: CP-DOCS-INITIAL-20260309-1301*  
*Agenten-System-Version: 1.0*

#Agenten #MasterSystem #Orchestrierung #Workflow #MultiAgent
