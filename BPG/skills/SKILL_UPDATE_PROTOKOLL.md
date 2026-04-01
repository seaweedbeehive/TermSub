# Skill-Update-Protokoll

> Template für das 5-Minuten-Review nach jedem Skill-Einsatz

---

## Metadata

```yaml
protokoll_id: SUP-YYYY-MM-DD-SK-XXX
skill: SK-XXX
skill_name: [Name]
skill_version_vorher: X.X.X
skill_version_nachher: X.X.X
agent: AG-XXX
datum: YYYY-MM-DD
zeitaufwand: X Minuten
```

---

## 1. Einsatz-Beschreibung

### 1.1 Task
[Beschreibung der Aufgabe]

### 1.2 Verwendete Skills
- [ ] SK-XXX: [Verwendungszweck]
- [ ] SK-XXX: [Verwendungszweck]

### 1.3 Input
```
[Beschreibung der Input-Daten]
```

### 1.4 Erwarteter Output
```
[Beschreibung des erwarteten Ergebnisses]
```

### 1.5 Tatsächlicher Output
```
[Beschreibung des tatsächlichen Ergebnisses]
```

---

## 2. Fehler-Analyse

### 2.1 Fehler aufgetreten?
- [ ] **Nein** → Springe zu Abschnitt 3
- [ ] **Ja** → Weiter mit 2.2

### 2.2 Fehler-Details

| Feld | Beschreibung |
|------|-------------|
| **Fehler-ID** | ERR-XXX (neu vergeben) |
| **Fehlertyp** | Syntax / Logik / Performance / Dokumentation |
| **Fehlermeldung** | [Original-Fehlermeldung] |
| **Kontext** | [Wann trat der Fehler auf?] |

### 2.3 Ursachen-Analyse
```
[Warum ist der Fehler aufgetreten?]
[Root-Cause-Analyse]
```

### 2.4 Lösung
```
[Wie wurde der Fehler behoben?]
[Code-Änderung / Prozess-Änderung]
```

### 2.5 Prävention
```
[Wie kann dieser Fehler in Zukunft vermieden werden?]
[Skill-Dokumentation / Checkliste / Validation]
```

### 2.6 Skill-Update nötig?
- [ ] **Ja** → Abschnitt 4
- [ ] **Nein** (nur Dokumentation) → Abschnitt 3

---

## 3. Optimierung

### 3.1 Optimierungspotenzial identifiziert?
- [ ] **Nein** → Springe zu Abschnitt 4
- [ ] **Ja** → Weiter mit 3.2

### 3.2 Optimierungs-Idee
```
[Beschreibung der Optimierung]
[Warum ist das besser?]
```

### 3.3 Implementierung
```
[Code / Prozess / Dokumentation]
[Konkrete Änderung]
```

### 3.4 Skill-Update nötig?
- [ ] **Ja** → Abschnitt 4
- [ ] **Nein** → Abschnitt 5

---

## 4. Skill-Update

### 4.1 Update-Typ
| Typ | Auswahl | Version-Update |
|-----|---------|----------------|
| Bugfix | [ ] | Patch ++ (1.0.0 → 1.0.1) |
| Neue Feature | [ ] | Minor ++ (1.0.1 → 1.1.0) |
| Breaking Change | [ ] | Major ++ (1.1.0 → 2.0.0) |
| Dokumentation | [ ] | Keine Änderung |

### 4.2 Durchgeführte Änderungen
- [ ] Abschnitt 1 (Beschreibung) aktualisiert
- [ ] Abschnitt 2 (Implementierung) aktualisiert
- [ ] Abschnitt 3 (Changelog) ergänzt
- [ ] Abschnitt 4 (Fehler-Datenbank) ergänzt
- [ ] Neue Anwendungsfälle hinzugefügt
- [ ] Version erhöht: X.X.X → X.X.X

### 4.3 Changelog-Eintrag
```markdown
#### vX.X.X (YYYY-MM-DD)
- [AG-XXX] [Typ]: [Beschreibung]
- [Error-Ref] ERR-XXX: [Fehlerbehebung / -referenz]
```

### 4.4 Fehler-Datenbank-Eintrag (falls Bugfix)
```markdown
| ERR-XXX | [Beschreibung] | [Lösung] | vX.X.X | [[SUP-YYYY-MM-DD-SK-XXX]] |
```

---

## 5. Abschluss

### 5.1 Tests durchgeführt?
- [ ] Skill funktioniert wie erwartet
- [ ] Keine Regressionen
- [ ] Dokumentation aktuell

### 5.2 Checkpoint erstellt?
```bash
./checkin.sh "SK-XXX: vX.X.X - [Kurzbeschreibung]"
```

**Checkpoint-Tag:** CP-XXX-XXX-YYYYMMDD-HHMM

### 5.3 Zeitaufwand gesamt
- Analyse: X Minuten
- Implementierung: X Minuten
- Dokumentation: X Minuten
- **Gesamt: X Minuten**

---

## 6. Lessons Learned

### Für den Skill
```
[Was wurde über den Skill gelernt?]
[Best Practices / Anti-Patterns]
```

### Für zukünftige Einsätze
```
[Empfehlungen für zukünftige Nutzung]
[Häufige Fehler vermeiden]
```

### Für andere Agenten
```
[Welche anderen Agenten sollten über dieses Update informiert werden?]
[Relevanz für AG-XXX, AG-XXX]
```

---

## Anhänge

### Relevante Dateien
- Skill-Datei: `active/SK-XXX.md`
- Error-Log: `error-log/SK-XXX-ERR-XXX.md` (falls neu)
- Beispiel-Code: [Pfad]

### Verknüpfungen
- [[SK-XXX]] - Der aktualisierte Skill
- [[05_Skill_Katalog]] - Übersicht
- [[TASK-XXX]] - Zugehörige Task (falls vorhanden)

---

*Dieses Protokoll wird im 99_Berichte/ Ordner gespeichert*
*Namenskonvention: SUP-YYYY-MM-DD-SK-XXX_[Agent].md*
