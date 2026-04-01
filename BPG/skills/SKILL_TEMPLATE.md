# Skill-Template

> Template für universelle Skills im BDL Projekt

---

## Skill-Metadaten

```yaml
skill_id: SK-XXX
skill_name: [Name des Skills]
version: 1.0.0
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
authors: [Agent/Name]
universal: true  # Kann von allen Agenten genutzt werden
applicability:
  - AG-001  # Konzepter
  - AG-002  # Architekt
  - AG-003  # Daten-Analyst
  - AG-004  # Researcher
  - AG-005  # Developer
  - AG-006  # Dokumentar
  - AG-007  # Reviewer
  - AG-008  # Demo-Builder
  - AG-009  # Integrator
  - AG-010  # Checkpoint-Manager
```

---

## 1. Skill-Beschreibung

### 1.1 Zweck
[Kurze Beschreibung, was dieser Skill ermöglicht]

### 1.2 Anwendungsfälle
- [Anwendungsfall 1]
- [Anwendungsfall 2]
- [Anwendungsfall 3]

### 1.3 Input/Output

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| input_1 | [Typ] | [Beschreibung] |
| output_1 | [Typ] | [Beschreibung] |

---

## 2. Implementierung

### 2.1 Code/Prozess

```python
# Beispiel-Implementierung
# [Hauptlogik des Skills]
```

### 2.2 Verwendung

```python
# Beispiel-Aufruf
result = skill_name(input_data)
```

### 2.3 Konfiguration

```yaml
# Optional: Konfigurationsparameter
param1: value1
param2: value2
```

---

## 3. Versionierung & Änderungshistorie

### Änderungsprinzipien

1. **NIEMALS löschen** - Alte Versionen bleiben erhalten
2. **Erweitern** - Neue Fähigkeiten werden hinzugefügt
3. **Korrigieren** - Fehler werden dokumentiert und gelöst
4. **Verweisen** - Auf Fehler-Lösungen wird verwiesen

### Changelog

#### v1.0.0 (YYYY-MM-DD)
- [AG-XXX] Initiale Erstellung
- [Feature] Basis-Funktionalität

#### v1.1.0 (YYYY-MM-DD)
- [AG-XXX] Erweiterung: [Neue Fähigkeit]
- [Fix] Fehlerbehebung: [Problem] → [Lösung]

#### v1.2.0 (YYYY-MM-DD)
- [AG-XXX] Optimierung: [Beschreibung]
- [Error-Ref] Siehe: `error-log/SK-XXX-ERROR-001.md`

---

## 4. Fehler-Datenbank

### Aktive Fehler/Warnungen

| ID | Fehler | Lösung | Behoben in | Referenz |
|----|--------|--------|------------|----------|
| ERR-001 | [Beschreibung] | [Lösung] | v1.1.0 | [Link] |

### Fehler-Log-Dateien
- `error-log/SK-XXX-ERROR-001.md` - [Beschreibung]

---

## 5. Verwendungsnachweis

### Einsätze

| Datum | Agent | Task | Ergebnis | Skill-Update nötig? |
|-------|-------|------|----------|---------------------|
| YYYY-MM-DD | AG-XXX | [Task] | ✅/⚠️/❌ | Ja/Nein → [Commit] |

### Performance-Tracking

| Metrik | Wert | Ziel | Status |
|--------|------|------|--------|
| Erfolgsrate | X% | >95% | 🟢🟡🔴 |
| Durchschnittszeit | Xs | <Xs | 🟢🟡🔴 |
| Fehlerrate | X% | <5% | 🟢🟡🔴 |

---

## 6. Integration

### 6.1 Mit anderen Skills
- [[SK-YYY]] - [Beschreibung der Beziehung]
- [[SK-ZZZ]] - [Beschreibung der Beziehung]

### 6.2 In Agenten-Workflows
```
[Workflow-Diagramm mit Skill-Einsatz]
```

---

## 7. Qualitätssicherung

### 7.1 Checkliste vor Einsatz
- [ ] Input-Format geprüft?
- [ ] Konfiguration validiert?
- [ ] Abhängigkeiten verfügbar?

### 7.2 Checkliste nach Einsatz
- [ ] Output-Format korrekt?
- [ ] Keine Fehler aufgetreten?
- [ ] Performance akzeptabel?
- [ ] Skill-Update nötig? → Siehe Abschnitt 8

---

## 8. Kontinuierliche Verbesserung

### Nach jedem Einsatz prüfen:

1. **Fehler aufgetreten?**
   - JA → In Fehler-Datenbank dokumentieren (Abschnitt 4)
   - Lösung implementieren
   - Version erhöhen (z.B. v1.1.0 → v1.2.0)

2. **Optimierungspotenzial?**
   - JA → Neue Fähigkeit hinzufügen
   - Version erhöhen (z.B. v1.2.0 → v1.3.0)

3. **Neue Anwendungsfälle?**
   - JA → In Abschnitt 1.2 ergänzen
   - Dokumentation aktualisieren

### Update-Prozess

```bash
# 1. Skill-Datei bearbeiten
# 2. Changelog ergänzen
# 3. Falls Fehler: error-log/ erstellen
# 4. Version erhöhen
# 5. Checkpoint erstellen
./checkin.sh "SK-XXX: [Beschreibung der Änderung]"
```

---

## 9. Verknüpfungen

- [[05_Skill_Katalog]] - Übersicht aller Skills
- [[SK-XXX-ERROR-001]] - Fehler-Details (falls vorhanden)
- [Agenten-Dokumentation]

---

*Dieser Skill folgt dem BDL Skill-Management-System*
*Template-Version: 1.0*
