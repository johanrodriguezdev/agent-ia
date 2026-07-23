# Auditoría de seguridad REQ-001

## Clasificación de riesgos implementados (según propuesta arquitectura-001.md)

### Acciones identificadas para clasificar

| Acción | Nivel propuesto | ¿Confirmación? | ¿Se implementa en este REQ? |
|--------|----------------|----------------|---------------------------|
| Leer información sistema (CPU, RAM) | Verde | No | Sí — SecurityManager |
| Buscar archivos (solo lectura) | Verde | No | Sí |
| Consultar clima / web | Verde | No | Sí |
| Chat conversacional | Verde | No | Sí |
| Abrir apps conocidas | Verde | No | Sí |
| Reproductor música/video | Verde | No | Sí |
| Screenshots | Verde | No | Sí |
| **Shutdown PC** | **Amarillo** | **Sí** | Sí |
| **Restart PC** | **Amarillo** | **Sí** | Sí |
| **Cerrar apps (taskkill /F)** | **Amarillo** | **Sí** | Sí |
| **Borrar archivos/carpetas** | **Amarillo** | **Sí** | Sí |
| **Ejecutar código IA** | **Amarillo** | **Sí** | Sí |
| **Crear/modificar skills** | **Amarillo** | **Sí** | Sí |
| Formatear discos | Rojo | Permiso explícito | No (no existe aún) |
| Borrar bases de datos | Rojo | Permiso explícito | No (no existe aún) |
| Exponer API keys | Rojo | Permiso explícito | Sí — se migran a .env |
| Modificar código O.R.I.O.N. | Rojo | Permiso explícito | Sí — skill_creator_skill |

### Niveles por canal

| Canal | Acciones permitidas |
|-------|-------------------|
| Desktop | Verde (directo), Amarillo (con confirmación), Rojo (bloqueado sin permiso explícito) |
| Telegram | Solo Verde |
| Discord | Solo Verde |
| Voz (wake word) | Solo Verde |

## Secretos auditados

### Estado actual (pre-REQ)
| Secreto | Ubicación | Riesgo |
|---------|-----------|--------|
| `deepseek_api_key` | `config.json` (texto plano, commiteado) | 🔴 Crítico |
| `telegram_token` | `config.json` (texto plano, commiteado) | 🔴 Crítico |

### Estado deseado (post-REQ)
| Secreto | Ubicación | Estado |
|---------|-----------|--------|
| `DEEPSEEK_API_KEY` | `.env` + variable de entorno | ✅ |
| `TELEGRAM_BOT_TOKEN` | `.env` + variable de entorno | ✅ |
| `AGENT_NAME`, `AGENT_PRONUNCIATION` | `config.json` (no sensible) | ✅ |

## Validación de inputs
- `system_ctrl.py`: `close_app()` usa `process_name` directamente en `taskkill` — necesita sanitización
- `code_execution_skill.py`: el código generado por IA debe validarse antes de ejecutar (ya tiene self-healing)
- `os_integration/system_actions.py`: `open_app()` recibe nombres directamente — necesita validación

## Recomendaciones adicionales
1. Añadir `import logging` y `logger = logging.getLogger(__name__)` como boilerplate en todos los módulos
2. Configurar `NUMPY_CUSTOM_LOGGING` o similar para evitar que librerías externas inunden los logs
3. No olvidar que `output.txt` existe — considerar si migrarlo o eliminarlo
4. El `.gitignore` debe incluir: `.env`, `logs/`, `*.log`, `__pycache__/`, `.venv/`

## Veredicto: ✅ APROBADO
Sin observaciones bloqueantes. Todos los riesgos identificados están cubiertos por la arquitectura propuesta.
