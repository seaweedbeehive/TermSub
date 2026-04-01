# SK-004: Obsidian WikiLinks & Knowledge Graph

> Semantische Verknüpfungen und automatische Index-Generierung

---

## Skill-Metadaten

```yaml
skill_id: SK-004
skill_name: Obsidian WikiLinks & Knowledge Graph
version: 1.1.0
created: 2026-03-09
last_updated: 2026-03-09
authors: [AG-006, Alle Agenten]
universal: true
applicability:
  - AG-001
  - AG-002
  - AG-003
  - AG-004
  - AG-005
  - AG-006
  - AG-007
  - AG-008
  - AG-009
  - AG-010
```

---

## 1. Skill-Beschreibung

### 1.1 Zweck
Erstellung und Verwaltung von Obsidian-kompatiblen WikiLinks (`[[...]]`), automatische Backlink-Generierung und Knowledge Graph Aufbau durch semantische Verknüpfungen.

### 1.2 Anwendungsfälle
- Dokumentenverknüpfung (alle Agenten)
- Automatischer Index-Generator (AG-006)
- Knowledge Graph Visualisierung
- Backlink-Übersichten

### 1.3 Input/Output

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| source_doc | str | Ausgangsdokument |
| target_docs | list | Ziel-Dokumente |
| link_text | str | Optional: Anzeigetext |
| output | str | WikiLink-Code |

---

## 2. Implementierung

```python
import re
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Set

class ObsidianWikiLinks:
    """SK-004: WikiLinks & Knowledge Graph Management"""
    
    def create_link(self, target: str, 
                    display_text: str = None,
                    anchor: str = None) -> str:
        """
        Erstellt WikiLink
        
        Formate:
        - [[Ziel]]
        - [[Ziel|Anzeigetext]]
        - [[Ziel#Anchor]]
        """
        if display_text and anchor:
            return f"[[{target}#{anchor}|{display_text}]]"
        elif display_text:
            return f"[[{target}|{display_text}]]"
        elif anchor:
            return f"[[{target}#{anchor}]]"
        else:
            return f"[[{target}]]"
    
    def extract_links(self, content: str) -> List[dict]:
        """Extrahiert alle WikiLinks aus Content"""
        pattern = r'\[\[([^\]|]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]'
        matches = re.findall(pattern, content)
        
        links = []
        for target, anchor, display in matches:
            links.append({
                'target': target.strip(),
                'anchor': anchor.strip() if anchor else None,
                'display': display.strip() if display else target.strip()
            })
        return links
    
    def find_backlinks(self, target_doc: str, 
                       docs_directory: str = ".") -> List[str]:
        """Findet alle Dokumente, die auf target_doc verlinken"""
        target_name = Path(target_doc).stem
        backlinks = []
        
        for md_file in Path(docs_directory).rglob("*.md"):
            if any(x in str(md_file) for x in ['.git', '.obsidian']):
                continue
                
            content = md_file.read_text()
            links = self.extract_links(content)
            
            for link in links:
                if link['target'] == target_name or \
                   link['target'] == str(md_file.relative_to(docs_directory)):
                    backlinks.append(str(md_file.relative_to(docs_directory)))
                    break
        
        return backlinks
    
    def generate_index(self, root_dir: str = ".") -> dict:
        """Generiert Knowledge Graph Statistiken"""
        stats = {
            'total_docs': 0,
            'total_links': 0,
            'avg_links_per_doc': 0,
            'orphaned_docs': [],
            'most_linked': [],
            'tags': set()
        }
        
        doc_links = defaultdict(list)
        link_targets = defaultdict(int)
        
        for md_file in Path(root_dir).rglob("*.md"):
            if any(x in str(md_file) for x in ['.git', '.obsidian', '.git-worktrees']):
                continue
            
            stats['total_docs'] += 1
            content = md_file.read_text()
            
            # Extract links
            links = self.extract_links(content)
            doc_name = str(md_file.relative_to(root_dir))
            doc_links[doc_name] = links
            
            for link in links:
                link_targets[link['target']] += 1
            
            stats['total_links'] += len(links)
            
            # Extract tags
            tags = re.findall(r'#\w+', content)
            stats['tags'].update(tags)
        
        # Calculate averages
        if stats['total_docs'] > 0:
            stats['avg_links_per_doc'] = stats['total_links'] / stats['total_docs']
        
        # Find orphaned docs (no incoming links)
        all_doc_names = set(Path(d).stem for d in doc_links.keys())
        linked_docs = set(link_targets.keys())
        stats['orphaned_docs'] = list(all_doc_names - linked_docs)
        
        # Most linked docs
        stats['most_linked'] = sorted(
            link_targets.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        return stats
    
    def suggest_links(self, content: str, 
                      available_docs: List[str]) -> List[str]:
        """Schlägt potenzielle Links basierend auf Content vor"""
        suggestions = []
        content_lower = content.lower()
        
        for doc in available_docs:
            doc_name = Path(doc).stem.lower()
            # Simple matching: doc name appears in content
            if doc_name in content_lower and f"[[{doc}" not in content:
                suggestions.append(doc)
        
        return suggestions
    
    def validate_links(self, root_dir: str = ".") -> List[dict]:
        """Validiert alle WikiLinks (prüft auf tote Links)"""
        broken_links = []
        
        # Collect all available docs
        available_docs = set()
        for md_file in Path(root_dir).rglob("*.md"):
            if not any(x in str(md_file) for x in ['.git', '.obsidian']):
                available_docs.add(md_file.stem)
                available_docs.add(str(md_file.relative_to(root_dir)))
        
        # Check links
        for md_file in Path(root_dir).rglob("*.md"):
            if any(x in str(md_file) for x in ['.git', '.obsidian']):
                continue
                
            content = md_file.read_text()
            links = self.extract_links(content)
            
            for link in links:
                target = link['target']
                if target not in available_docs:
                    broken_links.append({
                        'source': str(md_file.relative_to(root_dir)),
                        'target': target,
                        'line': content[:content.find(f"[[{target}")].count('\n') + 1
                    })
        
        return broken_links
```

---

## 3. Changelog

#### v1.1.0 (2026-03-09)
- [AG-006] Automatische Link-Vorschläge
- [Feature] Tote Link-Validierung
- [Feature] Knowledge Graph Statistiken

#### v1.0.0 (2026-03-09)
- [AG-006] Initiale Implementierung
- [Feature] WikiLink-Erstellung
- [Feature] Backlink-Generierung

---

## 4. Fehler-Datenbank
| ID | Fehler | Lösung | Behoben in | Referenz |
|----|--------|--------|------------|----------|
| - | Noch keine Fehler | - | - | - |

---

*Skill-Version: 1.1.0*
