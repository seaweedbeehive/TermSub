# SK-006: Shell Automation & Scripting

> Robuste Shell-Skripte mit Fehlerbehandlung und Logging

---

## Skill-Metadaten

```yaml
skill_id: SK-006
skill_name: Shell Automation & Scripting
version: 1.0.0
created: 2026-03-09
last_updated: 2026-03-09
authors: [AG-010, Alle Agenten]
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
Erstellung robuster, portabler Shell-Skripte mit konsistenter Fehlerbehandlung, Logging und Best Practices.

### 1.2 Anwendungsfälle
- Git-Workflow-Automatisierung
- Datei-Operationen
- Build-Prozesse

### 1.3 Input/Output

| Parameter | Typ | Beschreibung |
|-----------|-----|--------------|
| script_template | str | Template-Typ |
| variables | dict | Zu ersetzende Variablen |
| output | str | Generiertes Shell-Skript |

---

## 2. Implementierung

### 2.1 Skript-Template

```bash
#!/bin/bash
# SK-006: Shell Script Template

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Farben
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

error_exit() {
    echo -e "${RED}ERROR: $*${NC}" >&2
    exit 1
}

main() {
    log "Starte $0"
    # Hauptlogik hier
    log "Erfolgreich beendet"
}

main "$@"
```

### 2.2 Python-Wrapper

```python
import subprocess
from typing import List, Tuple, Optional

class ShellAutomation:
    """SK-006: Shell Automation"""
    
    def run_command(self, command: str, 
                    cwd: Optional[str] = None) -> Tuple[int, str, str]:
        """Führt Befehl aus"""
        result = subprocess.run(
            command.split(),
            cwd=cwd,
            capture_output=True,
            text=True
        )
        return result.returncode, result.stdout, result.stderr
```

---

## 3. Changelog

#### v1.0.0 (2026-03-09)
- [AG-010] Initiale Implementierung

---

*Skill-Version: 1.0.0*
