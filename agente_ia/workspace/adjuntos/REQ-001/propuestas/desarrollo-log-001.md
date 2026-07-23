# Desarrollo REQ-001 — Sistema de seguridad y estabilidad

## Archivos creados
- `agente_ia/core/__init__.py` — paquete core
- `agente_ia/core/logger_setup.py` — logging centralizado con RotatingFileHandler (5 MB, 3 backups)
- `agente_ia/core/security_manager.py` — SecurityManager singleton + RiskLevel enum + ChannelType + acciones default clasificadas
- `agente_ia/.env.example` — plantilla de variables de entorno
- `agente_ia/.gitignore` — excluye .env, logs/, *.db, __pycache__

## Archivos modificados (continuación)
- `agente_ia/executor/handlers.py` — channel propagado a system_ctrl.shutdown_pc() y close_app()
- `agente_ia/tasks/task_scheduler.py` — token via config_manager
- `agente_ia/start_bots.py` — token detection via config_manager
- `agente_ia/ai/llm_provider.py` — deepseek key via config_manager

## Pendiente para REQ futuro
- Migrar ~50 `print()` a logging.getLogger() (baja prioridad)
- Tests automatizados
- Implementar verificación real de 2FA para acciones RED

## Decisión: system_actions.py y file_system_skill.py sin cambios
- system_actions.py solo abre apps (GREEN) y close_active_window es Alt+F4 reversible
- file_system_skill.py no tiene intents de DELETE, solo OPEN_FOLDER/LIST_FILES/CREATE_FILE (todos GREEN)

## Dependencias agregadas
- `requirements.txt` — python-dotenv==1.0.1

## Decisiones de implementación
- SecurityManager como singleton para acceso global desde cualquier módulo
- RiskLevel enum con GREEN, YELLOW, RED
- ChannelType enum con DESKTOP, TELEGRAM, DISCORD, VOICE
- Desktop permite GREEN + YELLOW (con confirmación)
- Telegram, Discord, Voice solo GREEN
- Confirmation en Desktop vía input() con timeout conceptual (espera respuesta)
- Logging con formato estándar y RotatingFileHandler (5 MB, 3 backups) + consola
- No se modificaron todos los `print()` → logging (quedan ~50 pendientes para un REQ futuro)
- No se creó el directorio logs/ ni el archivo .gitignore previo (ahora existen)
