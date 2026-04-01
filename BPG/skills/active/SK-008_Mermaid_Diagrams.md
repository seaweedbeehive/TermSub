# SK-008: Mermaid Diagram Generation

> Automatische Diagramm-Erstellung für Architektur und Workflows

---

## Skill-Metadaten

```yaml
skill_id: SK-008
skill_name: Mermaid Diagram Generation
version: 1.0.0
created: 2026-03-09
last_updated: 2026-03-09
authors: [AG-002, AG-006]
universal: true
applicability:
  - AG-002  # Architektur-Diagramme
  - AG-004  # Recherche-Visualisierung
  - AG-006  # Dokumentations-Diagramme
  - AG-008  # Demo-Diagramme
```

---

## 1. Skill-Beschreibung

### 1.1 Zweck
Generierung von Mermaid-Diagrammen für Architektur, Workflows, Datenflüsse und Systemlandschaften.

### 1.2 Anwendungsfälle
- System-Architektur (AG-002)
- Agenten-Workflows
- Datenflüsse
- Entscheidungsbäume

### 1.3 Input/Output

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| diagram_type | str | 'flowchart', 'sequence', 'class', 'er' |
| data | dict | Diagramm-Daten |
| output | str | Mermaid-Code |

---

## 2. Implementierung

```python
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class Node:
    id: str
    label: str
    shape: str = "rect"  # rect, circle, diamond
    style: Optional[str] = None

@dataclass
class Edge:
    from_id: str
    to_id: str
    label: Optional[str] = None
    style: str = "-->"  # -->, -.->, ==>

class MermaidGenerator:
    """SK-008: Mermaid Diagram Generation"""
    
    SHAPES = {
        'rect': ['[', ']'],
        'circle': ['((', '))'],
        'diamond': ['{', '}'],
        'cylinder': ['[(', ')]'],
        'subroutine': ['[[', ']]']
    }
    
    def generate_flowchart(self, nodes: List[Node], 
                          edges: List[Edge],
                          direction: str = "TD") -> str:
        """Generiert Flowchart-Diagramm"""
        lines = [f"```mermaid", f"flowchart {direction}", ""]
        
        # Nodes
        for node in nodes:
            shape_chars = self.SHAPES.get(node.shape, ['[', ']'])
            line = f"    {node.id}{shape_chars[0]}\"{node.label}\"{shape_chars[1]}"
            if node.style:
                line += f":::{node.style}"
            lines.append(line)
        
        lines.append("")
        
        # Edges
        for edge in edges:
            line = f"    {edge.from_id} {edge.style} {edge.to_id}"
            if edge.label:
                line += f"|\"{edge.label}\"|"
            lines.append(line)
        
        lines.append("```")
        return '\n'.join(lines)
    
    def generate_sequence(self, participants: List[str],
                         interactions: List[Dict]) -> str:
        """Generiert Sequenzdiagramm"""
        lines = ["```mermaid", "sequenceDiagram", ""]
        
        # Participants
        for p in participants:
            lines.append(f"    participant {p}")
        
        lines.append("")
        
        # Interactions
        for i in interactions:
            arrow = ">>" if i.get('type') == 'request' else ">>">           lines.append(f"    {i['from']}-{arrow}{i['to']}: {i['message']}")
        
        lines.append("```")
        return '\n'.join(lines)
    
    def generate_er_diagram(self, entities: Dict[str, Dict]) -> str:
        """Generiert ER-Diagramm"""
        lines = ["```mermaid", "erDiagram", ""]
        
        for entity_name, entity_data in entities.items():
            lines.append(f"    {entity_name} {{")
            for attr in entity_data.get('attributes', []):
                lines.append(f"        {attr['type']} {attr['name']} {attr.get('pk', '')}")
            lines.append("    }")
        
        # Relationships
        for rel in entity_data.get('relationships', []):
            lines.append(f"    {rel['from']} {rel['notation']} {{ rel['to'] }} : \"{rel['label']}\"")
        
        lines.append("```")
        return '\n'.join(lines)
    
    def generate_from_structure(self, structure: Dict,
                                diagram_type: str = "flowchart") -> str:
        """Generiert Diagramm aus strukturierten Daten"""
        if diagram_type == "flowchart":
            nodes = [Node(**n) for n in structure.get('nodes', [])]
            edges = [Edge(**e) for e in structure.get('edges', [])]
            return self.generate_flowchart(nodes, edges)
        elif diagram_type == "sequence":
            return self.generate_sequence(
                structure.get('participants', []),
                structure.get('interactions', [])
            )
        elif diagram_type == "er":
            return self.generate_er_diagram(structure.get('entities', {}))
        
        return ""
```

---

## 3. Changelog

#### v1.0.0 (2026-03-09)
- [AG-002] Initiale Implementierung
- [Feature] Flowchart-Generierung
- [Feature] Sequenzdiagramme
- [Feature] ER-Diagramme

---

*Skill-Version: 1.0.0*
