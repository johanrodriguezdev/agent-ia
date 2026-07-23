# Baseline REQ-001

## Estado actual del sistema

### Secretos
- `config.json` contiene `telegram_token` y `deepseek_api_key` en texto plano (commiteado al repo)
- Solo `llm_provider.py` usa variables de entorno como fallback (ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY)
- Los bots (Telegram, Discord) leen tokens desde `config.json`
- No existe `.env` ni `.env.example`
- No existe `.gitignore` para `.env`

### Logging
- No hay logging centralizado
- ~70+ llamadas a `print()` dispersas en 25+ archivos
- Los errores usan `print(f"[Aviso] ...")` como pseudo-logging
- 6 instancias de `except: pass` silencioso en `llm_provider.py`, `main.py`, `wake_word.py`
- Único archivo de salida: `output.txt` (binario, inaccesible como texto)
- Los bots (Telegram, Discord) tienen `logging.basicConfig` para sí mismos

### Seguridad
- `shutdown_pc()` en `os_integration/system_ctrl.py:51` ejecuta `os.system("shutdown /s /t 5")` sin confirmación
- `close_app()` en `system_ctrl.py:117` usa `taskkill /IM ... /F` sin confirmación
- Telegram tiene `_handle_shutdown()` con texto de "cancela apagado" pero **sin implementación real** de cancelación
- No hay clasificación de riesgo en ninguna acción
- Todos los canales (Desktop, Telegram, Discord) tienen el mismo nivel de acceso

### Tests
- `pytest` no está instalado en el entorno
- Los tests existentes en `tests/` usan `print()` directamente (no `assert`)
- Los tests dependen de redes externas (API calls)

## Archivos que serán modificados (previsión)
- `agente_ia/config.json` — remover secretos
- `agente_ia/config_manager.py` — añadir carga de `.env`
- `agente_ia/main.py` — inicializar logging centralizado
- `agente_ia/os_integration/system_ctrl.py` — añadir confirmaciones
- `agente_ia/os_integration/system_actions.py` — añadir confirmaciones
- `agente_ia/executor/handlers.py` — clasificar acciones por riesgo
- `agente_ia/channels/telegram_bot.py` — restringir por canal
- `agente_ia/channels/discord_bot.py` — restringir por canal
- `agente_ia/channels/gateway.py` — verificar permisos por canal
- `agente_ia/skills/system_control_skill.py` — confirmación en shutdown
- `agente_ia/skills/file_system_skill.py` — confirmación en borrado
- `agente_ia/skills/code_execution_skill.py` — confirmación antes de ejecutar
- `agente_ia/skills/skill_creator_skill.py` — confirmación antes de crear skills
- `agente_ia/ai/llm_provider.py` — reemplazar `except: pass`
- `agente_ia/voice/wake_word.py` — reemplazar `except: pass`
- `agente_ia/.env` — nuevo (no commiteado)
- `agente_ia/.env.example` — nuevo
- `agente_ia/.gitignore` — nuevo o modificar existente
- `agente_ia/logs/` — nuevo directorio para archivos de log
- Múltiples archivos `.py` — reemplazar `print()` por `logging`

## Fallos pre-existentes (no atribuibles a este REQ)
- pytest no instalado — no se pueden ejecutar tests automáticos
- Los tests existentes usan `print()` en vez de `assert` — no son detectables por pytest
- `config.json` contiene secretos en texto plano (esto se arregla en este REQ)
