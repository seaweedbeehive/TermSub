# SK-002: Markdown Structure & YAML Frontmatter

> Strukturierte Markdown-Dokumentenerstellung mit YAML-Frontmatter

---

## Skill-Metadaten

```yaml
skill_id: SK-002
skill_name: Markdown Structure & YAML Frontmatter
version: 1.1.0
created: 2026-03-09
last_updated: 2026-03-09
authors: [AG-001, AG-002, AG-006]
universal: true
applicability:
  - AG-001  # Konzepter
  - AG-002  # Architekt
  - AG-003  # Daten-Analyst
  - AG-004  # Researcher
  - AG-005  # Developer
  - AG-006  # Dokumentar
  - AG-007  # Reviewer
  - AG-008  # Demo-Builder
```

---

## 1. Skill-Beschreibung

### 1.1 Zweck
Einheitliche Strukturierung aller Markdown-Dokumente mit YAML-Frontmatter für Metadaten, konsistente Überschriften-Hierarchie und semantische Verknüpfungen.

### 1.2 Anwendungsfälle
- Konzept-Dokumente (AG-001)
- Architektur-Dokumente (AG-002)
- Analyse-Reports (AG-003)
- Technische Dokumentation (AG-005, AG-006)
- Review-Reports (AG-007)

### 1.3 Input/Output

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| metadata | dict | YAML-Frontmatter Daten |
| sections | list | Dokument-Sections |
| links | list | WikiLinks [[...]] |
| output | str | Komplettes Markdown-Dokument |

---

## 2. Implementierung

```python
from datetime import datetime
from typing import Dict, List, Optional

class MarkdownStructure:
    """Markdown-Dokumenten-Strukturierung"""
    
    # Standard-Templates für verschiedene Dokumenttypen
    TEMPLATES = {
        'concept': {
            'sections': ['Ideen-Grundlage', 'Strategische Ausrichtung', 
                        'Umsetzungsansatz', 'Nächste Schritte'],
            'required_meta': ['agent', 'task_type', 'created']
        },
        'architecture': {
            'sections': ['Überblick', 'Komponenten', 'Datenmodell', 
                        'Schnittstellen'],
            'required_meta': ['agent', 'task_type', 'created']
        },
        'analysis': {
            'sections': ['Datenquellen', 'Methodik', 'Ergebnisse', 
                        'Handlungsempfehlungen'],
            'required_meta': ['agent', 'task_type', 'created']
        },
        'report': {
            'sections': ['Zusammenfassung', 'Geprüfte Aspekte', 
                        'Findings', 'Gesamtbewertung'],
            'required_meta': ['agent', 'review_target', 'review_type']
        }
    }
    
    def create_document(self, doc_type: str, metadata: dict, 
                       content: dict) -> str:
        """
        Erstellt strukturiertes Markdown-Dokument
        
        Args:
            doc_type: 'concept', 'architecture', 'analysis', 'report'
            metadata: YAML-Frontmatter Daten
            content: Section-Inhalte
        """
        template = self.TEMPLATES.get(doc_type, self.TEMPLATES['concept'])
        
        # YAML Frontmatter
        yaml_lines = ['---']
        for key, value in metadata.items():
            if isinstance(value, list):
                yaml_lines.append(f"{key}:")
                for item in value:
                    yaml_lines.append(f"  - {item}")
            else:
                yaml_lines.append(f"{key}: {value}")
        yaml_lines.append('---\n')
        
        # Title
        md_lines = [f"# {content.get('title', 'Untitled')}\n"]
        
        # Sections
        for section_name in template['sections']:
            md_lines.append(f"## {section_name}\n")
            
            section_content = content.get('sections', {}).get(section_name, {})
            
            # Paragraphs
            for para in section_content.get('paragraphs', []):
                md_lines.append(f"{para}\n")
            
            # Tables
            for table in section_content.get('tables', []):
                md_lines.append(self._create_table(table))
            
            # Lists
            for item in section_content.get('list', []):
                md_lines.append(f"- {item}")
            md_lines.append("")  # Leerzeile
        
        # Verknüpfungen
        if 'links' in content:
            md_lines.append("\n---\n")
            md_lines.append("## Verknüpfungen\n")
            for link in content['links']:
                md_lines.append(f"- [[{link}]]")
        
        return '\n'.join(yaml_lines + md_lines)
    
    def _create_table(self, data: list) -> str:
        """Erstellt Markdown-Tabelle aus Listen"""
        if not data or not data[0]:
            return ""
        
        lines = []
        # Header
        lines.append("| " + " | ".join(str(cell) for cell in data[0]) + " |")
        # Separator
        lines.append("| " + " | ".join(["---"] * len(data[0])) + " |")
        # Rows
        for row in data[1:]:
            lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
        
        return '\n'.join(lines) + '\n'
    
    def validate_frontmatter(self, content: str, doc_type: str) -> tuple[bool, list]:
        """Validiert YAML-Frontmatter"""
        import yaml
        
        errors = []
        template = self.TEMPLATES.get(doc_type)
        
        if not template:
            return False, [f"Unbekannter Dokumenttyp: {doc_type}"]
        
        # Extrahiere YAML
        if not content.startswith('---'):
            return False, ["Kein YAML-Frontmatter gefunden"]
        
        try:
            yaml_end = content.find('---', 3)
            if yaml_end == -1:
                return False, ["YAML-Frontmatter nicht korrekt abgeschlossen"]
            
            yaml_content = content[3:yaml_end]
            metadata = yaml.safe_load(yaml_content)
            
            # Prüfe required fields
            for field in template['required_meta']:
                if field not in metadata:
                    errors.append(f"Fehlendes Pflichtfeld: {field}")
            
            return len(errors) == 0, errors
            
        except yaml.YAMLError as e:
            return False, [f"YAML-Parsing-Fehler: {e}"]
```

---

## 3. Changelog

#### v1.1.0 (2026-03-09)
- [AG-006] Template-System erweitert
- [Feature] Vier Standard-Templates (concept, architecture, analysis, report)
- [Feature] Automatische Tabellengenerierung
- [Feature] Frontmatter-Validierung

#### v1.0.0 (2026-03-09)
- [AG-001] Initiale Implementierung
- [Feature] YAML-Frontmatter-Generierung
- [Feature] Section-Strukturierung

---

## 4. Fehler-Datenbank
| ID | Fehler | Lösung | Behoben in | Referenz |
|----|--------|--------|------------|----------|
| - | Noch keine Fehler | - | - | - |

---

*Skill-Version: 1.1.0*
