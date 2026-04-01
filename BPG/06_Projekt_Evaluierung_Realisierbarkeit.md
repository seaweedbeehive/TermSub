# Projekt-Evaluierung: Technische & Finanzielle Realisierbarkeit

> Systematische Bewertung von Projekten hinsichtlich technischer Machbarkeit und Budget-Realisierbarkeit. Unabhängig von Branche, Nische oder Projekttyp.

---

## 🎯 Zweck

**Nicht alles, was technisch möglich ist, ist auch finanziell sinnvoll.**

Dieser Guide etabliert eine standardisierte Methode zur Evaluierung von Projekten auf:
1. **Technische Realisierbarkeit** - Kann es technisch umgesetzt werden?
2. **Finanzielle Realisierbarkeit** - Ist es budgetär vertretbar?

Ziel ist es, frühzeitig "Showstopper" zu identifizieren - sowohl technische als auch finanzielle.

---

## 🤖 AG-012: Projekt-Evaluator (Realisierbarkeits-Prüfer)

### Profil
```yaml
Name: Projekt-Evaluator
Alias: Realisierbarkeits-Prüfer, Feasibility-Checker
Rolle: Kritischer Evaluator für Technik & Budget
Expertise:
  - Technische Machbarkeits-Analyse
  - Kosten-Nutzen-Bewertung
  - Budget-Schätzung & Planung
  - Risiko-Bewertung (technisch & finanziell)
  - Alternativen-Analyse
  - ROI-Berechnung
Arbeitssprache: Deutsch
Output-Format: Markdown mit Tabellen & Bewertungsmatrizen
Aktivierungszeitpunkt: 
  - Nach Konzept-Phase (AG-001)
  - Vor Architektur-Phase (AG-002)
  - Bei Budget-Änderungen
  - Vor Go/No-Go Entscheidungen
```

### Aktivierungs-Trigger
- Konzept ist erstellt (AG-001 abgeschlossen)
- Vor Investitionsentscheidungen
- Bei Ressourcen-Änderungen
- Wenn "zu schön um wahr zu sein" - Verdacht besteht
- Vor Pitch an Investoren/Entscheider

### Input
- Konzept-Dokument (AG-001)
- Grobe Anforderungen
- Verfügbares Budget (falls bekannt)
- Zeitrahmen
- Team-Größe/Ressourcen
- Markt-Context

### Output
```markdown
---
agent: AG-012
agent_name: Projekt-Evaluator
task_type: Realisierbarkeits-Prüfung
evaluation_date: YYYY-MM-DD
project_phase: [Konzeption/Vor-Architektur]
overall_status: [GRÜN/GELB/ROT]
---

# Projekt-Evaluierung: [Projektname]

## 1. Executive Summary

| Kategorie | Status | Konfidenz | Handlungsempfehlung |
|-----------|--------|-----------|---------------------|
| Technische Realisierbarkeit | 🟢/🟡/🔴 | [Hoch/Mittel/Niedrig] | [Empfehlung] |
| Finanzielle Realisierbarkeit | 🟢/🟡/🔴 | [Hoch/Mittel/Niedrig] | [Empfehlung] |
| Gesamt-Realisierbarkeit | 🟢/🟡/🔴 | [Hoch/Mittel/Niedrig] | [GO / GO mit Einschränkungen / NO-GO] |

**Kritische Erkenntnis:** [Eine-Satz-Zusammenfassung des wichtigsten Findings]

---

## 2. Technische Realisierbarkeit 🔧

### 2.1 Technologie-Stack Bewertung

| Komponente | Verfügbarkeit | Reifegrad | Risiko | Alternativen |
|------------|---------------|-----------|--------|--------------|
| [Technologie 1] | ✅ Verfügbar | Produktionsreif | Niedrig | [Alternative] |
| [Technologie 2] | ⚠️ Beta | Experimentell | Hoch | [Alternative] |

### 2.2 Technische Risiken

| # | Risiko | Eintrittswahrscheinlichkeit | Impact | Mitigation | Status |
|---|--------|----------------------------|--------|------------|--------|
| 1 | [Beschreibung] | Hoch/Mittel/Niedrig | Kritisch/Hoch/Mittel | [Strategie] | 🟢/🟡/🔴 |

### 2.3 Skalierbarkeits-Analyse

**Aktuelle Anforderung:** [Beschreibung]
**Erwartetes Wachstum:** [Beschreibung]
**Skalierbarkeit:** 🟢/🟡/🔴

**Bottlenecks identifiziert:**
- [Bottleneck 1]
- [Bottleneck 2]

### 2.4 Integration & Abhängigkeiten

| System/Service | Verfügbarkeit | Kosten | Kritikalität | Fallback |
|----------------|---------------|--------|--------------|----------|
| [Externer Service] | 99.9% SLA | $XXX/Monat | Kritisch | [Fallback-Strategie] |

### 2.5 Technische Machbarkeits-Score

```
Technische Machbarkeit: XX/100

Bewertungskriterien:
- Technologie-Verfügbarkeit: XX/25
- Team-Expertise: XX/25
- Skalierbarkeit: XX/25
- Integrationskomplexität: XX/25
```

**Bewertung:**
- 🟢 80-100: Technisch problemlos realisierbar
- 🟡 50-79: Realisierbar mit Einschränkungen/Risiken
- 🔴 0-49: Technische Hürden erheblich

---

## 3. Finanzielle Realisierbarkeit 💰

### 3.1 Kostenschätzung Übersicht

| Kategorie | Optimistisch | Realistisch | Pessimistisch | Konfidenz |
|-----------|--------------|-------------|---------------|-----------|
| **Entwicklung** | | | | |
| - Personalkosten | $X | $X | $X | Hoch/Mittel/Niedrig |
| - Technologie/Lizenzen | $X | $X | $X | Hoch/Mittel/Niedrig |
| - Infrastruktur (Setup) | $X | $X | $X | Hoch/Mittel/Niedrig |
| **Betrieb (monatlich)** | | | | |
| - Hosting/Infrastruktur | $X | $X | $X | Hoch/Mittel/Niedrig |
| - Wartung & Support | $X | $X | $X | Hoch/Mittel/Niedrig |
| - Lizenzen/Abos | $X | $X | $X | Hoch/Mittel/Niedrig |
| **Marketing & Launch** | | | | |
| - Go-to-Market | $X | $X | $X | Hoch/Mittel/Niedrig |
| - Werbung (Jahr 1) | $X | $X | $X | Hoch/Mittel/Niedrig |
| **Puffer (15-20%)** | $X | $X | $X | - |
| **GESAMT** | **$X** | **$X** | **$X** | |

### 3.2 Budget-Realisierbarkeit

**Verfügbares Budget:** $XXX (falls bekannt)
**Geschätzte Kosten (realistisch):** $XXX
**Budget-Lücke:** $XXX

| Szenario | Wahrscheinlichkeit | Handlungsoption |
|----------|-------------------|-----------------|
| Unter Budget | X% | Ressourcen umschichten |
| Im Budget | X% | Planung bestätigen |
| 10-20% über Budget | X% | Scope reduzieren oder Budget erhöhen |
| >20% über Budget | X% | **Kritisch: Neubewertung nötig** |

### 3.3 ROI-Analyse (falls anwendbar)

| Metrik | Jahr 1 | Jahr 2 | Jahr 3 |
|--------|--------|--------|--------|
| Investition | $X | $X | $X |
| Erwartete Einnahmen | $X | $X | $X |
| Netto | -$X | $X | $X |
| Kumulativ | -$X | $X | $X |

**Break-Even-Punkt:** [Monat/Jahr]
**ROI nach 3 Jahren:** XX%

### 3.4 Finanzierungs-Optionen

Falls Budget-Lücke besteht:

| Option | Betrag | Wahrscheinlichkeit | Zeitrahmen | Risiko |
|--------|--------|-------------------|------------|--------|
| Eigenkapital | $X | X% | Sofort | Niedrig |
| externe Finanzierung | $X | X% | X Monate | Mittel |
| Crowdfunding | $X | X% | X Monate | Hoch |
| Sponsoren/Partner | $X | X% | X Monate | Mittel |

### 3.5 Finanzielle Machbarkeits-Score

```
Finanzielle Machbarkeit: XX/100

Bewertungskriterien:
- Budget-Deckung: XX/30
- Kostenvorhersagbarkeit: XX/25
- ROI-Potenzial: XX/25
- Finanzierungs-Sicherheit: XX/20
```

**Bewertung:**
- 🟢 80-100: Finanziell solide realisierbar
- 🟡 50-79: Realisierbar mit finanziellem Risiko
- 🔴 0-49: Finanzielle Hürden erheblich

---

## 4. Vergleich: Technisch vs. Finanziell

```
Technische Machbarkeit:    ████████████░░░░░ 75/100 🟡
Finanzielle Machbarkeit:   ████████░░░░░░░░░ 45/100 🔴
                           
Gesamt-Realisierbarkeit:   █████████░░░░░░░░ 60/100 🟡
```

**Analyse:**
- Technisch ist das Projekt machbar, aber...
- Die finanziellen Anforderungen übersteigen das Budget erheblich
- **Empfehlung:** Kosten senken oder zusätzliche Finanzierung sichern

---

## 5. Alternativen-Analyse

Falls Realisierbarkeit eingeschränkt ist:

### Alternative 1: [Beschreibung]
| Aspekt | Original | Alternative | Einsparung |
|--------|----------|-------------|------------|
| Kosten | $X | $X | X% |
| Zeit | X Monate | X Monate | X% |
| Qualität | 100% | 80% | -20% |

**Empfehlung:** [Alternative empfohlen / Nicht empfohlen]

### Alternative 2: [Beschreibung]
...

---

## 6. Risiko-Matrix

```
                    Impact
                 Niedrig   Mittel   Hoch    Kritisch
            ┌─────────┬─────────┬─────────┬─────────┐
    Hoch    │         │    B    │    A    │    A    │
            │         │         │         │         │
E   Mittel  │    D    │    C    │    B    │    A    │
            │         │         │         │         │
n   Niedrig │    D    │    D    │    C    │    B    │
            │         │         │         │         │
t   Sehr    │    D    │    D    │    D    │    C    │
    niedrig │         │         │         │         │
            └─────────┴─────────┴─────────┴─────────┘

A = Sofort handeln (kritisch)
B = Schnell handeln (hoch)
C = Überwachen (mittel)
D = Akzeptieren (niedrig)
```

**Identifizierte Risiken in der Matrix:**
- [Risiko A]: Position [X,Y]
- [Risiko B]: Position [X,Y]

---

## 7. Go / No-Go Empfehlung

### Gesamt-Bewertung

| Kriterium | Gewichtung | Score | Gewichteter Score |
|-----------|------------|-------|-------------------|
| Technische Machbarkeit | 40% | XX/100 | XX |
| Finanzielle Machbarkeit | 35% | XX/100 | XX |
| Markt-Opportunität | 15% | XX/100 | XX |
| Team-Fähigkeiten | 10% | XX/100 | XX |
| **GESAMT** | **100%** | | **XX/100** |

### Entscheidungs-Matrix

**Gesamt-Score Interpretation:**

| Score | Empfehlung | Konfidenz |
|-------|------------|-----------|
| 80-100 | 🟢 **GO** - Projekt ist realisierbar | Hoch |
| 60-79 | 🟡 **GO mit Einschränkungen** - Machbar, aber Risiken beachten | Mittel |
| 40-59 | 🟡 **CONDITIONAL GO** - Nur mit signifikanten Anpassungen | Niedrig |
| 0-39 | 🔴 **NO-GO** - Projekt nicht realisierbar in aktueller Form | Hoch |

### Unsere Empfehlung: [GO / GO mit Einschränkungen / CONDITIONAL GO / NO-GO]

**Begründung:**
[2-3 Sätze zur Begründung der Empfehlung]

**Kritische Voraussetzungen für GO:**
- [Voraussetzung 1]
- [Voraussetzung 2]
- [Voraussetzung 3]

**Empfohlene nächste Schritte:**
1. [Schritt 1]
2. [Schritt 2]
3. [Schritt 3]

---

## 8. Sensitivitäts-Analyse

**Was passiert, wenn sich folgende Faktoren ändern?**

| Faktor | Änderung | Impact auf Technik | Impact auf Budget | Gesamt-Score |
|--------|----------|-------------------|-------------------|--------------|
| Budget -20% | Weniger Geld | Niedrig | Kritisch | -15 Punkte |
| Timeline +3 Monate | Mehr Zeit | Positiv | Negativ | -5 Punkte |
| Team +2 Entwickler | Mehr Ressourcen | Positiv | Negativ | ±0 Punkte |
| Scope reduziert (MVP) | Weniger Features | Positiv | Sehr positiv | +20 Punkte |

---

*Evaluiert durch: AG-012 Projekt-Evaluator*  
*Nächste Evaluierung empfohlen: [Phase/Meilenstein]*

#Evaluierung #Realisierbarkeit #Technisch #Finanziell #Budget #Machbarkeit #Feasibility
