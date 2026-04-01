# SK-007: Python Module Structure

> Modulare Python-Architektur mit Separation of Concerns

---

## Skill-Metadaten

```yaml
skill_id: SK-007
skill_name: Python Module Structure
version: 1.0.0
created: 2026-03-09
last_updated: 2026-03-09
authors: [AG-002, AG-005]
universal: true
applicability:
  - AG-002  # Architektur-Definition
  - AG-005  # Developer (primär)
  - AG-007  # Reviewer (Code-Review)
```

---

## 1. Skill-Beschreibung

### 1.1 Zweck
Erstellung modularer, wartbarer Python-Projekte mit klaren Verantwortlichkeiten, Type Hints und Dokumentation.

### 1.2 Anwendungsfälle
- MVP-Strukturierung
- Core-Engine-Module
- API-Entwicklung
- Test-Strukturen

### 1.3 Input/Output

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| module_name | str | Name des Moduls |
| components | list | Liste der Komponenten |
| template | str | Architektur-Template |
| output | str | Generierte Verzeichnisstruktur |

---

## 2. Implementierung

### 2.1 Modul-Template

```python
"""
[Module-Name]

[Kurze Beschreibung des Modulzwecks]

Usage:
    from [package] import [Module]
    
    instance = [Module]()
    result = instance.method()

Author: [AG-XXX]
Date: YYYY-MM-DD
Version: 1.0.0
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import logging

# Logger Setup
logger = logging.getLogger(__name__)


class ModuleError(Exception):
    """Base exception for this module"""
    pass


class ValidationError(ModuleError):
    """Raised when validation fails"""
    pass


@dataclass
class ModuleConfig:
    """Configuration for the module"""
    param1: str = "default"
    param2: int = 10
    debug: bool = False


class ModuleComponent:
    """
    [Beschreibung der Komponente]
    
    Attributes:
        config: Modul-Konfiguration
        state: Interner Zustand
    
    Example:
        >>> comp = ModuleComponent(ModuleConfig(debug=True))
        >>> comp.process(data)
    """
    
    def __init__(self, config: Optional[ModuleConfig] = None):
        self.config = config or ModuleConfig()
        self.state = {}
        self._setup()
    
    def _setup(self) -> None:
        """Interne Initialisierung"""
        logger.info(f"Initializing {self.__class__.__name__}")
    
    def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Hauptverarbeitungsmethode
        
        Args:
            data: Input-Daten
            
        Returns:
            Verarbeitete Daten
            
        Raises:
            ValidationError: Bei ungültigen Daten
        """
        try:
            validated = self._validate(data)
            result = self._process_impl(validated)
            return result
        except Exception as e:
            logger.error(f"Processing failed: {e}")
            raise ModuleError(f"Processing failed: {e}") from e
    
    def _validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validiert Input-Daten"""
        if not isinstance(data, dict):
            raise ValidationError("Data must be a dictionary")
        return data
    
    def _process_impl(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Implementierung der Verarbeitung"""
        raise NotImplementedError("Subclasses must implement this method")


def utility_function(input_data: str) -> str:
    """
    Utility-Funktion mit Docstring
    
    Args:
        input_data: Beschreibung
        
    Returns:
        Beschreibung
    """
    return input_data.upper()
```

### 2.2 Verzeichnis-Struktur Generator

```python
from pathlib import Path
from typing import List

class PythonModuleGenerator:
    """SK-007: Python Module Structure Generator"""
    
    STRUCTURE_TEMPLATES = {
        'core_engine': {
            'dirs': ['models', 'core', 'processing', 'utils'],
            'files': {
                '__init__.py': '# Package initialization\n__version__ = "1.0.0"',
                'config.py': '# Configuration settings',
                'exceptions.py': '# Custom exceptions'
            }
        },
        'api': {
            'dirs': ['routes', 'middleware', 'schemas'],
            'files': {
                '__init__.py': '',
                'main.py': '# FastAPI/Flask main application',
                'dependencies.py': '# Dependency injection'
            }
        },
        'test_suite': {
            'dirs': ['unit', 'integration', 'fixtures'],
            'files': {
                '__init__.py': '',
                'conftest.py': '# pytest configuration',
                'test_base.py': '# Base test class'
            }
        }
    }
    
    def create_module(self, name: str, template: str, 
                      base_path: str = ".") -> Path:
        """Erstellt neue Modulstruktur"""
        
        module_path = Path(base_path) / name
        template_config = self.STRUCTURE_TEMPLATES.get(template, {})
        
        # Verzeichnisse erstellen
        for dir_name in template_config.get('dirs', []):
            (module_path / dir_name).mkdir(parents=True, exist_ok=True)
            (module_path / dir_name / '__init__.py').touch()
        
        # Dateien erstellen
        for file_name, content in template_config.get('files', {}).items():
            file_path = module_path / file_name
            file_path.write_text(content)
        
        return module_path
    
    def add_component(self, module_path: str, 
                      component_name: str,
                      component_type: str = 'class') -> Path:
        """Fügt neue Komponente hinzu"""
        
        file_path = Path(module_path) / f"{component_name}.py"
        
        if component_type == 'class':
            content = f'''"""
{component_name.capitalize()} Component
"""

from typing import Dict, Any


class {component_name.capitalize()}:
    """Description of {component_name}"""
    
    def __init__(self):
        pass
    
    def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process data"""
        return data
'''
        elif component_type == 'function':
            content = f'''"""
{component_name} utilities
"""

from typing import Any


def {component_name}(input_data: Any) -> Any:
    """
    Description of {component_name}
    
    Args:
        input_data: Description
        
    Returns:
        Description
    """
    return input_data
'''
        
        file_path.write_text(content)
        return file_path
```

---

## 3. Changelog

#### v1.0.0 (2026-03-09)
- [AG-005] Initiale Implementierung
- [Feature] Modul-Template mit Docstrings
- [Feature] Verzeichnis-Struktur Generator
- [Feature] Komponenten-Generator

---

## 4. Fehler-Datenbank
| ID | Fehler | Lösung | Behoben in | Referenz |
|----|--------|--------|------------|----------|
| - | Noch keine Fehler | - | - | - |

---

*Skill-Version: 1.0.0*
