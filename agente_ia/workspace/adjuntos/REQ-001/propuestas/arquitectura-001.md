# Arquitectura REQ-001 — Sistema de seguridad y estabilidad

## Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| CA1 — Niveles de riesgo | Nueva clase `SecurityManager` en `agente_ia/core/security_manager.py` que clasifica acciones y media ejecución |
| CA2 — Confirmaciones | `SecurityManager.require_confirmation()` intercepta acciones amarillas/rojas antes de ejecutar |
| CA3 — Secretos en .env | `config_manager.py` modificado para cargar `python-dotenv`. Nuevo `.env.example`. `.gitignore` actualizado |
| CA4 — Logging centralizado | Nuevo módulo `agente_ia/core/logger_setup.py` con `RotatingFileHandler`. Reemplazar `print()` y `except: pass` |
| CA5 — Allowlist por canal | `SecurityManager` expone `get_allowed_levels(channel)` que gateway.py consulta antes de rutear |

## Arquitectura propuesta

### Nuevos archivos
- `agente_ia/core/security_manager.py` — Clase `SecurityManager` (singleton) con:
  - `classify_action(action_name) -> str` — retorna "green", "yellow", "red"
  - `require_confirmation(action_name, params, channel) -> bool` — muestra confirmación, espera respuesta
  - `get_allowed_levels(channel) -> List[str]` — qué niveles permite cada canal
  - `register_action(name, level, handler)` — registro de acciones con su nivel
  - `ACTION_REGISTRY` — dict estático con todas las acciones del sistema clasificadas

- `agente_ia/core/logger_setup.py` — Configuración centralizada de logging:
  - `setup_logging(log_dir="logs", log_level=logging.INFO)` — inicializa logging
  - `RotatingFileHandler` con 5 MB, 3 backups
  - Formato: `%(asctime)s [%(name)s] %(levelname)s: %(message)s`
  - Logger raíz y por módulo

- `agente_ia/.env.example` — Plantilla con variables necesarias (sin valores reales)

### Archivos a modificar

#### 1. `agente_ia/config_manager.py` — Carga de .env
```python
from dotenv import load_dotenv
load_dotenv()
# Antes de leer config.json, intentar variables de entorno:
# os.getenv("DEEPSEEK_API_KEY", config_json.get("deepseek_api_key", ""))
```

#### 2. `agente_ia/main.py` — Inicialización
```python
from core.logger_setup import setup_logging
setup_logging()
```

#### 3. `agente_ia/os_integration/system_ctrl.py` — Confirmaciones
- `shutdown_pc()`: llamar `SecurityManager.require_confirmation("shutdown", ...)` antes de `os.system()`
- `close_app()`: llamar confirmación antes de `taskkill /F`

#### 4. `agente_ia/executor/handlers.py` — Clasificar acciones
- Mapear cada handler a un nivel de riesgo
- Los handlers destructivos pasan por `SecurityManager` antes de ejecutar

#### 5. `agente_ia/channels/gateway.py` — Allowlist
- Antes de procesar un mensaje, consultar `SecurityManager.get_allowed_levels(channel)`
- Si la acción no está permitida, responder "No tengo permiso para hacer eso por [canal]"

#### 6. `agente_ia/channels/telegram_bot.py` y `discord_bot.py`
- Pasar `channel="telegram"/"discord"` a gateway
- No cambiar handlers directamente; la restricción se aplica en gateway

#### 7. `agente_ia/skills/system_control_skill.py`
- `execute()` llama a `SecurityManager.require_confirmation()` antes de shutdown

#### 8. `agente_ia/skills/file_system_skill.py`
- Acciones de borrar/renombrar requieren confirmación

#### 9. `agente_ia/skills/code_execution_skill.py`
- Confirmación antes de ejecutar código generado por IA

#### 10. `agente_ia/skills/skill_creator_skill.py`
- Confirmación antes de crear/modificar/borrar skills

#### 11. Archivos con `except: pass`
- `agente_ia/ai/llm_provider.py` — 3 instancias → logging
- `agente_ia/main.py` — 1 instancia → logging
- `agente_ia/voice/wake_word.py` — 2 instancias → logging

#### 12. Archivos con `print()` → `logging.getLogger(__name__)`
- ~25 archivos, ~70+ llamadas a `print()`
- Prioridad: archivos de producción (no tests)
- Tests: se actualizan en una segunda pasada

### Flujo de datos

```
Usuario (cualquier canal)
  → gateway.py
    → SecurityManager.get_allowed_levels(channel)
      → ¿acción permitida en este canal? NO → "No puedo hacer eso"
      → ¿nivel amarillo/rojo?
        → SecurityManager.require_confirmation()
          → Usuario confirma? NO → "Cancelado"
          → SÍ → ejecuta acción normalmente
      → ¿nivel verde? → ejecuta directamente
```

## Archivos a modificar/crear

### Nuevos
- `agente_ia/core/__init__.py`
- `agente_ia/core/security_manager.py`
- `agente_ia/core/logger_setup.py`
- `agente_ia/.env.example`
- `agente_ia/.gitignore` (añadir `.env`, `logs/`, `*.log`)

### Modificar
- `agente_ia/config.json` — remover `telegram_token`, `deepseek_api_key`
- `agente_ia/config_manager.py` — cargar .env
- `agente_ia/main.py` — init logging
- `agente_ia/os_integration/system_ctrl.py` — confirmaciones
- `agente_ia/os_integration/system_actions.py` — confirmaciones
- `agente_ia/executor/handlers.py` — clasificar acciones
- `agente_ia/channels/gateway.py` — allowlist por canal
- `agente_ia/channels/telegram_bot.py` — pasar channel a gateway
- `agente_ia/channels/discord_bot.py` — pasar channel a gateway
- `agente_ia/skills/system_control_skill.py` — confirmación
- `agente_ia/skills/file_system_skill.py` — confirmación
- `agente_ia/skills/code_execution_skill.py` — confirmación
- `agente_ia/skills/skill_creator_skill.py` — confirmación
- `agente_ia/ai/llm_provider.py` — reemplazar `except: pass`
- `agente_ia/voice/wake_word.py` — reemplazar `except: pass`
- `agente_ia/.gitignore` — añadir entries

## Dependencias nuevas
- `python-dotenv` — para cargar `.env`

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| Confirmaciones rompen flujo de voz (no hay UI para confirmar) | Voz solo permite acciones verdes. Amarillo/Rojo responden "No puedo hacer eso por voz" |
| Muchos archivos modificados → alto riesgo de merge conflict | Trabajar en rama feature/REQ-001, commits atómicos por sub-sistema |
| `print()` → `logging` cambia comportamiento de salida estándar | Mantener un logger de consola además del archivo rotativo |
| python-dotenv puede no estar instalado | Fallback a leer de config.json (sin secretos nuevos), advertencia en logs |

## Pruebas sugeridas
1. Verificar que shutdown pide confirmación (Desktop)
2. Verificar que shutdown desde Telegram responde "No permitido"
3. Verificar que `.env` carga correctamente y `config.json` ya no requiere secretos
4. Verificar que logs se escriben en `logs/orion.log` con rotación
5. Verificar que `except: pass` fue reemplazado en llm_provider.py y wake_word.py
6. Verificar que code_execution_skill pide confirmación antes de correr código
