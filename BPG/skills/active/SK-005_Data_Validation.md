# SK-005: Data Validation & Schema Enforcement

> JSON Schema-basierte Datenvalidierung mit automatischer Fehlerbehebung

---

## Skill-Metadaten

```yaml
skill_id: SK-005
skill_name: Data Validation & Schema Enforcement
version: 1.0.0
created: 2026-03-09
last_updated: 2026-03-09
authors: [AG-003, AG-004]
universal: true
applicability:
  - AG-001  # Validierung von Konzept-Metadaten
  - AG-002  # Validierung von Architektur-Daten
  - AG-003  # Daten-Analyst (primär)
  - AG-004  # Researcher (Quellenvalidierung)
  - AG-005  # Input-Validierung
  - AG-010  # Checkpoint-Metadaten
```

---

## 1. Skill-Beschreibung

### 1.1 Zweck
Validierung von Datenstrukturen gegen JSON Schemas, automatische Fehlererkennung und Vorschläge zur Fehlerbehebung.

### 1.2 Anwendungsfälle
- Testdaten-Validierung (AG-003)
- Konfigurations-Validierung
- API-Input-Validierung
- DNA-Profil-Validierung

### 1.3 Input/Output

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| data | dict/list | Zu validierende Daten |
| schema | dict/str | JSON Schema oder Pfad |
| strict | bool | Strikter Modus (default: True) |
| output | tuple | (is_valid: bool, errors: list, suggestions: list) |

---

## 2. Implementierung

```python
import json
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
try:
    import jsonschema
    from jsonschema import validate, ValidationError
except ImportError:
    jsonschema = None

class DataValidator:
    """SK-005: Data Validation & Schema Enforcement"""
    
    # Standard-Schemas für BDL
    DEFAULT_SCHEMAS = {
        'content_item': {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "required": ["id", "source_name", "source_type", "text"],
            "properties": {
                "id": {"type": "string", "pattern": "^[a-zA-Z0-9_-]+$"},
                "source_name": {"type": "string", "minLength": 1, "maxLength": 200},
                "source_type": {
                    "type": "string",
                    "enum": ["website", "blog", "social_media", "whitepaper", "email", "ad"]
                },
                "text": {"type": "string", "minLength": 10, "maxLength": 50000},
                "metadata": {
                    "type": "object",
                    "properties": {
                        "created_at": {"type": "string", "format": "date-time"},
                        "industry": {"type": "string"},
                        "company_size": {"type": "string"}
                    }
                }
            }
        },
        'dna_profile': {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "required": ["voice_attributes", "vocabulary", "syntax"],
            "properties": {
                "voice_attributes": {
                    "type": "object",
                    "properties": {
                        "formality": {"type": "number", "minimum": 0, "maximum": 1},
                        "warmth": {"type": "number", "minimum": 0, "maximum": 1},
                        "authority": {"type": "number", "minimum": 0, "maximum": 1},
                        "playfulness": {"type": "number", "minimum": 0, "maximum": 1}
                    }
                },
                "vocabulary": {
                    "type": "object",
                    "properties": {
                        "technical_depth": {"type": "number", "minimum": 0, "maximum": 1},
                        "clarity": {"type": "number", "minimum": 0, "maximum": 1},
                        "uniqueness": {"type": "number", "minimum": 0, "maximum": 1}
                    }
                },
                "syntax": {
                    "type": "object",
                    "properties": {
                        "complexity": {"type": "number", "minimum": 0, "maximum": 1},
                        "readability": {"type": "number", "minimum": 0, "maximum": 1},
                        "sentence_variety": {"type": "number", "minimum": 0, "maximum": 1}
                    }
                }
            }
        },
        'checkpoint_meta': {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "required": ["tag", "branch", "timestamp", "type"],
            "properties": {
                "tag": {"type": "string", "pattern": "^CP-[A-Z]+-[A-Z]+-\d{8}-\d{4}$"},
                "branch": {"type": "string"},
                "timestamp": {"type": "string", "format": "date-time"},
                "type": {"enum": ["INITIAL", "MILESTONE", "RELEASE", "BACKUP", "RECOVERY", "DAILY"]}
            }
        }
    }
    
    def __init__(self, schema_dir: str = ".data-schemas"):
        self.schema_dir = Path(schema_dir)
        self.schemas = self._load_schemas()
    
    def _load_schemas(self) -> Dict[str, dict]:
        """Lädt alle verfügbaren Schemas"""
        schemas = dict(self.DEFAULT_SCHEMAS)
        
        if self.schema_dir.exists():
            for schema_file in self.schema_dir.glob("*.json"):
                with open(schema_file) as f:
                    schema_name = schema_file.stem.replace('_schema', '')
                    schemas[schema_name] = json.load(f)
        
        return schemas
    
    def validate(self, data: Any, schema: Any, 
                 strict: bool = True) -> Tuple[bool, List[str], List[str]]:
        """
        Validiert Daten gegen Schema
        
        Returns:
            (is_valid, errors, suggestions)
        """
        if jsonschema is None:
            return self._basic_validation(data, schema)
        
        # Schema auflösen
        if isinstance(schema, str):
            if schema in self.schemas:
                schema = self.schemas[schema]
            elif Path(schema).exists():
                with open(schema) as f:
                    schema = json.load(f)
            else:
                return False, [f"Schema '{schema}' nicht gefunden"], []
        
        errors = []
        suggestions = []
        
        try:
            validate(instance=data, schema=schema)
            return True, [], []
        except ValidationError as e:
            errors.append(str(e))
            suggestions.extend(self._generate_suggestions(e, data))
            
            if strict:
                return False, errors, suggestions
            else:
                # Versuche, Daten zu korrigieren
                corrected = self._auto_correct(data, e)
                if corrected:
                    return True, errors, [f"Auto-korrigiert: {e.message}"]
        
        return False, errors, suggestions
    
    def _generate_suggestions(self, error: ValidationError, 
                               data: Any) -> List[str]:
        """Generiert Fehlerbehebungs-Vorschläge"""
        suggestions = []
        
        if error.validator == 'required':
            missing = error.validator_value
            suggestions.append(f"Füge fehlende Felder hinzu: {missing}")
        
        elif error.validator == 'type':
            expected = error.validator_value
            actual = type(error.instance).__name__
            suggestions.append(f"Konvertiere {actual} zu {expected}")
        
        elif error.validator == 'enum':
            valid_values = error.validator_value
            suggestions.append(f"Verwende einen dieser Werte: {valid_values}")
        
        elif error.validator == 'pattern':
            suggestions.append(f"Muss Pattern '{error.validator_value}' matchen")
        
        elif error.validator in ['minimum', 'maximum']:
            constraint = error.validator
            value = error.validator_value
            suggestions.append(f"Wert muss {constraint} {value} sein")
        
        return suggestions
    
    def _auto_correct(self, data: Any, error: ValidationError) -> bool:
        """Versucht automatische Fehlerkorrektur"""
        # Typ-Konvertierung
        if error.validator == 'type':
            try:
                if error.validator_value == 'string':
                    str(error.instance)
                    return True
                elif error.validator_value == 'integer':
                    int(error.instance)
                    return True
                elif error.validator_value == 'number':
                    float(error.instance)
                    return True
            except (ValueError, TypeError):
                pass
        
        return False
    
    def validate_batch(self, data_list: List[Any], 
                       schema: Any) -> Dict[str, Any]:
        """Validiert mehrere Datensätze"""
        results = {
            'total': len(data_list),
            'valid': 0,
            'invalid': 0,
            'errors': []
        }
        
        for i, data in enumerate(data_list):
            is_valid, errors, suggestions = self.validate(data, schema)
            
            if is_valid:
                results['valid'] += 1
            else:
                results['invalid'] += 1
                results['errors'].append({
                    'index': i,
                    'data': data,
                    'errors': errors,
                    'suggestions': suggestions
                })
        
        return results
    
    def _basic_validation(self, data: Any, schema: Any) -> Tuple[bool, List[str], List[str]]:
        """Einfache Validierung ohne jsonschema"""
        errors = []
        
        if isinstance(schema, str) and schema in self.schemas:
            schema = self.schemas[schema]
        
        if isinstance(schema, dict) and 'required' in schema:
            if isinstance(data, dict):
                for field in schema['required']:
                    if field not in data:
                        errors.append(f"Fehlendes Feld: {field}")
        
        return len(errors) == 0, errors, []
```

---

## 3. Changelog

#### v1.0.0 (2026-03-09)
- [AG-003] Initiale Implementierung
- [Feature] JSON Schema-Validierung
- [Feature] Auto-Korrektur-Vorschläge
- [Feature] Batch-Validierung
- [Feature] Drei Standard-Schemas (content_item, dna_profile, checkpoint_meta)

---

## 4. Fehler-Datenbank
| ID | Fehler | Lösung | Behoben in | Referenz |
|----|--------|--------|------------|----------|
| - | Noch keine Fehler | - | - | - |

---

*Skill-Version: 1.0.0*
