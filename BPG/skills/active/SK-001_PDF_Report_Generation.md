# SK-001: PDF Report Generation

> Universelle PDF-Berichtsgenerierung mit konsistentem BDL-Layout

---

## Skill-Metadaten

```yaml
skill_id: SK-001
skill_name: PDF Report Generation
version: 1.0.0
created: 2026-03-09
last_updated: 2026-03-09
authors: [AG-005, AG-006]
universal: true
applicability:
  - AG-003  # Daten-Analyst (Analyse-Reports)
  - AG-005  # Developer (Code-Doku)
  - AG-006  # Dokumentar (Berichte)
  - AG-007  # Reviewer (Review-Reports)
  - AG-008  # Demo-Builder (Demo-Material)
```

---

## 1. Skill-Beschreibung

### 1.1 Zweck
Erstellung professioneller PDF-Berichte aus strukturierten Daten mit einheitlichem BDL-Branding, automatischer Seitenzahl, Kopf-/Fußzeilen und konsistentem Layout.

### 1.2 Anwendungsfälle
- Audit-Berichte (BDL Analyse-Ergebnisse)
- Review-Reports (AG-007 Output)
- Datenanalyse-Reports (AG-003 Output)
- Demo-Materialien (AG-008 Output)
- Technische Dokumentation (AG-006 Output)

### 1.3 Input/Output

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| content | dict | Strukturierte Inhalte (Titel, Sections, Tabellen) |
| template | str | Optional: Template-Name ('default', 'audit', 'minimal') |
| output_path | str | Zielpfad für PDF |
| output | str | Pfad zur generierten PDF |

---

## 2. Implementierung

```python
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from datetime import datetime

class PDFReportGenerator:
    """Universeller PDF-Report-Generator"""
    
    def __init__(self, template='default'):
        self.template = template
        self.styles = self._setup_styles()
        self.brand_colors = {
            'primary': colors.HexColor('#6366f1'),
            'text': colors.HexColor('#1f2937'),
            'light': colors.HexColor('#f3f4f6')
        }
    
    def _setup_styles(self):
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            'BDLTitle', parent=styles['Heading1'],
            fontSize=24, textColor=self.brand_colors['primary'],
            spaceAfter=30, alignment=1
        ))
        return styles
    
    def generate(self, content: dict, output_path: str) -> str:
        doc = SimpleDocTemplate(output_path, pagesize=A4)
        story = []
        
        # Title
        story.append(Paragraph(content['title'], self.styles['BDLTitle']))
        story.append(Spacer(1, 12))
        
        # Sections
        for section in content.get('sections', []):
            story.append(Paragraph(section['heading'], self.styles['Heading2']))
            for para in section.get('paragraphs', []):
                story.append(Paragraph(para, self.styles['Normal']))
            story.append(Spacer(1, 12))
        
        doc.build(story)
        return output_path
```

---

## 3. Changelog

#### v1.0.0 (2026-03-09)
- [AG-005] Initiale Implementierung
- [Feature] Basis-Layout mit BDL-Branding

---

## 4. Fehler-Datenbank
| ID | Fehler | Lösung | Behoben in | Referenz |
|----|--------|--------|------------|----------|
| - | Noch keine Fehler | - | - | - |

---

*Skill-Version: 1.0.0*
