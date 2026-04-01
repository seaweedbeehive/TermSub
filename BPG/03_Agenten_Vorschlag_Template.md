# Agenten-Vorschlag Template

> Template für die Erstellung neuer Agenten-Vorschläge, wenn eine Aufgabe nicht optimal von bestehenden Agenten abgedeckt wird.

---

## 🆕 Wann einen neuen Agenten vorschlagen?

### Checkliste: Neuer Agent nötig?

- [ ] **Kein bestehender Agent** passt zur Aufgaben-Domäne?
- [ ] **Wiederholende Aufgaben** dieses Typs werden erwartet?
- [ ] **Spezifische Expertise** wird benötigt?
- [ ] **Qualitätsanforderungen** rechtfertigen Spezialisierung?
- [ ] **Mindestens 3/5 Kriterien** erfüllt?

**Wenn JA → Neuen Agenten vorschlagen**

---

## 📝 Vorschlag ausfüllen

### Header

```yaml
Vorschlag-ID: V-AG-XXX-[Datum]
Status: [ENTWURF / VORGELEGT / GENEHMIGT / ABGELEHNT]
Eingereicht: YYYY-MM-DD
Vorgeschlagener Agenten-ID: AG-XXX
```

---

### 1. Agenten-Name

**Vorschlag:** [Name des neuen Agenten]

**Begründung des Namens:**
[Warum passt dieser Name?]

---

### 2. Domäne & Expertise

**Primäre Domäne:**
[In welchem Bereich soll der Agent arbeiten?]

**Spezifische Expertise:**
- [ ] Expertise 1
- [ ] Expertise 2
- [ ] Expertise 3
- [ ] Expertise 4
- [ ] Expertise 5

**Unterscheidung von bestehenden Agenten:**

| Agent | Domäne | Warum nicht passend? |
|-------|--------|---------------------|
| AG-001 | Konzeption | ... |
| AG-002 | Architektur | ... |
| AG-003 | Datenanalyse | ... |
| AG-004 | Recherche | ... |
| AG-005 | Entwicklung | ... |
| AG-006 | Dokumentation | ... |
| AG-007 | Review | ... |
| AG-008 | Demo-Building | ... |
| AG-009 | Integration | ... |
| AG-010 | Checkpoint-Mgmt | ... |

---

### 3. Aktivierungs-Trigger

**Wann wird dieser Agent aktiv?**

- [ ] Trigger 1: [Beschreibung]
- [ ] Trigger 2: [Beschreibung]
- [ ] Trigger 3: [Beschreibung]

**Beispiel-Aufgaben:**
1. [Konkretes Beispiel 1]
2. [Konkretes Beispiel 2]
3. [Konkretes Beispiel 3]

---

### 4. Input/Output Spezifikation

#### Input

**Benötigte Informationen:**
- [ ] Input 1: [Beschreibung]
- [ ] Input 2: [Beschreibung]
- [ ] Input 3: [Beschreibung]

**Input-Format:**
[Markdown / JSON / Code / Freitext / ...]

#### Output

**Erwartetes Ergebnis:**
[Beschreibung des Outputs]

**Output-Format:**
```markdown
---
agent: AG-XXX
agent_name: [Name]
task_type: [Typ]
created: YYYY-MM-DD_HH-MM
---

# [Titel]

## 1. [Section 1]
...

## 2. [Section 2]
...
```

---

### 5. Worktree-Zuordnung

**Vorgeschlagener Worktree:**
- [ ] main (Root) - Nur für produktionskritische Agenten
- [ ] develop - Für Entwicklungs-Agenten
- [ ] feature-konzept - Für Konzeptions-Agenten
- [ ] feature-daten - Für Daten-Agenten
- [ ] docs - Für Dokumentations-Agenten
- [ ] Neuer Worktree: [Name]

**Begründung:**
[Warum dieser Worktree?]

---

### 6. System-Prompt Entwurf

```
Du bist [Name], [kurze Beschreibung].

DEINE AUFGABE:
- [Aufgabe 1]
- [Aufgabe 2]
- [Aufgabe 3]

PRINZIPIEN:
1. [Prinzip 1]
2. [Prinzip 2]
3. [Prinzip 3]

OUTPUT-REGELN:
- [Regel 1]
- [Regel 2]
- [Regel 3]

CHECKPOINT: Arbeitet im [Branch] Branch.
```

---

### 7. Entscheidungs-Kriterien Bewertung

| Kriterium | Gewicht | Bewertung (1-5) | Gewichteter Wert |
|-----------|---------|-----------------|------------------|
| Einzigartigkeit | 30% | /5 | |
| Nutzungshäufigkeit | 25% | /5 | |
| Qualitätsgewinn | 25% | /5 | |
| Komplexität | 20% | /5 | |
| **GESAMT** | **100%** | | **/5** |

**Mindestens 3.0/5.0 erforderlich für Genehmigung**

---

### 8. Ähnliche Agenten (Recherche)

**Bestehende Agenten, die ähnlich sind:**

| Agent | Ähnlichkeit | Unterschiede |
|-------|-------------|--------------|
| AG-XXX | [Hoch/Mittel/Gering] | [Unterschiede] |

**Kann ein bestehender Agent erweitert werden statt neuen zu erstellen?**
- [ ] Ja → [Vorschlag zur Erweiterung]
- [ ] Nein → Begründung: ...

---

### 9. Implementierungs-Aufwand

**Geschätzter Aufwand:**
- [ ] Klein (< 30 Min)
- [ ] Mittel (30-60 Min)
- [ ] Groß (> 60 Min)

**Benötigte Ressourcen:**
- [ ] Nur Dokumentation
- [ ] Template-Erstellung
- [ ] Test-Tasks
- [ ] Review-Prozess

---

### 10. Genehmigung

**Entscheidung:**
- [ ] **GENEHMIGT** → In [[02_Agenten_Katalog]] aufnehmen
- [ ] **ABGELEHNT** → Begründung: ...
- [ ] **ÜBERARBEITUNG NÖTIG** → Kommentare: ...

**Entscheidungsdatum:** YYYY-MM-DD

**Entscheidung durch:** [Name/Rolle]

**Kommentare:**
...

---

## 🚀 Nach Genehmigung: Implementierung

### Schritte zur Agenten-Erstellung

1. **In Katalog aufnehmen**
   - [[02_Agenten_Katalog]] aktualisieren
   - Neue AG-XXX ID vergeben
   - Profil eintragen

2. **System-Prompt finalisieren**
   - Prompt optimieren
   - Beispiele hinzufügen
   - Format festlegen

3. **Templates erstellen**
   - Output-Template
   - Input-Checkliste
   - Quick-Start-Anleitung

4. **Testen**
   - Beispiel-Aufgabe durchführen
   - Output überprüfen
   - Iteration falls nötig

5. **Dokumentation**
   - BPG aktualisieren
   - Agenten-Übersicht ergänzen
   - Checkpoint setzen

---

## 📋 Beispiel: Ausgefüllter Vorschlag

### Beispiel: V-AG-011-20260309

```yaml
Vorschlag-ID: V-AG-011-20260309
Status: GENEHMIGT
Eingereicht: 2026-03-09
Vorgeschlagener Agenten-ID: AG-011
```

**Agenten-Name:** UI/UX-Designer

**Domäne:** Interface-Design und User Experience

**Begründung:**
Für Demo-Erstellung und Prototyping benötigen wir spezialisierte UI/UX-Expertise, die über den Demo-Builder (AG-008) hinausgeht. Der Demo-Builder konzentriert sich auf die Demo-Struktur, während der UI/UX-Designer sich auf visuelle Gestaltung und Interaktionsdesign fokussiert.

**Aktivierungs-Trigger:**
- Mockups erstellen
- User Flows designen
- Interface-Vorschläge entwickeln

**Worktree:** feature-konzept

**Entscheidung: GENEHMIGT (4.2/5.0)**

---

*Template-Version: 1.0*  
*Checkpoint: CP-DOCS-INITIAL-20260309-1301*

#Agenten #Vorschlag #Template #NeuerAgent
