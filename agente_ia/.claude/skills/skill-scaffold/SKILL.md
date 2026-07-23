---
name: skill-scaffold
description: >
  Genera el boilerplate de un skill nuevo de O.R.I.O.N. Crea el archivo .py
  en skills/ con la estructura BaseSkill, training data, extract_params y
  execute. Se invoca desde orion-dev cuando un REQ requiere crear un skill nuevo.
---

# Skill: Skill Scaffold Generator — O.R.I.O.N.

## Cuándo se usa
Cuando `orion-dev` necesita crear un skill nuevo desde cero. Este skill genera
el archivo base listo para implementar.

## Template generado

```python
import re
from typing import Optional, List, Tuple, Dict, Any
from skills.base_skill import BaseSkill

class {{SkillName}}(BaseSkill):
    @property
    def name(self) -> str:
        return "{{skill_name}}"

    @property
    def description(self) -> str:
        return "{{description}}"

    def get_intents(self) -> List[str]:
        return [{{intents_list}}]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            {{training_data}}
        ]

    def extract_params(self, text: str) -> Optional[Dict[str, Any]]:
        text_lower = text.lower()
        {{extract_logic}}

    def execute(self, params: Dict[str, Any]) -> str:
        {{execute_logic}}
```

## Parámetros de entrada
- `skill_name`: nombre en snake_case (ej: `calendar_skill`)
- `SkillName`: nombre en PascalCase (ej: `CalendarSkill`)
- `description`: descripción corta
- `intents`: lista de strings con los intents
- `training_data`: lista de (frase, intent)
- `extract_logic`: código Python para extraer parámetros
- `execute_logic`: código Python para ejecutar la acción

## Reglas
- El archivo se crea en `agente_ia/skills/<skill_name>.py`
- No necesita registro manual — `skill_manager` lo descubre automáticamente
- Después de crear el archivo, el skill está disponible en el próximo reinicio o
  invocando `skill_manager.reload_skills()`
