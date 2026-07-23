# SPEC-001 — Sistema de seguridad y estabilidad

**Estado:** ⏸️ ESPERANDO VALIDACIÓN
**Categoría:** SEGURIDAD
**Tipo:** SEGURIDAD
**Fecha:** 2026-07-20

## Objetivo
Implementar un sistema integral de seguridad y estabilidad en O.R.I.O.N. que clasifique todas las acciones del asistente en niveles de riesgo, exija confirmación humana en acciones destructivas, proteja secretos mediante variables de entorno, establezca logging estructurado y persistente, y restrinja herramientas según el canal de comunicación.

## Alcance
- Incluye:
  - Sistema de niveles verde/amarillo/rojo para todas las acciones del sistema
  - Confirmación humana obligatoria en shutdown, borrado de archivos, taskkill /F
  - Migración de API keys y tokens de `config.json` a variables de entorno (`.env`)
  - Sistema de logging centralizado con `logging` + `RotatingFileHandler`
  - Eliminación de `except: pass` silencioso en todo el código base
  - Allowlist de herramientas por canal (Desktop, Telegram, Discord)
- No incluye:
  - Creación de nuevos canales (WhatsApp, ManyChat) — eso sería otro REQ
  - Cifrado de la base de datos de memoria
  - Autenticación de usuarios por contraseña (solo control de permisos)

## Módulos afectados
- `agente_ia/config.json` y `agente_ia/config_manager.py` — migrar secretos a `.env`
- `agente_ia/main.py` — inicializar logging centralizado al arranque
- `agente_ia/system_ctrl.py` — añadir confirmación en shutdown, restart, close_app
- `agente_ia/os_integration/system_actions.py` — añadir confirmación en acciones destructivas
- `agente_ia/executor/handlers.py` — clasificar acciones por nivel de riesgo
- `agente_ia/channels/telegram_bot.py` — restringir herramientas según allowlist
- `agente_ia/channels/discord_bot.py` — restringir herramientas según allowlist
- `agente_ia/channels/gateway.py` — integrar verificación de permisos por canal
- `agente_ia/skills/system_control_skill.py` — confirmación en shutdown
- `agente_ia/skills/file_system_skill.py` — confirmación en borrado de archivos
- `agente_ia/skills/code_execution_skill.py` — confirmación antes de ejecutar código
- `agente_ia/skills/skill_creator_skill.py` — confirmación antes de crear/modificar skills
- Todos los archivos `.py` — reemplazar `except: pass` con logging

## Comportamiento actual vs deseado

| Aspecto | Actual | Deseado |
|---------|--------|---------|
| Seguridad | Sin niveles de riesgo. shutdown() ejecuta sin preguntar | Verde/amarillo/rojo. Destructivo pide confirmación |
| Secretos | `deepseek_api_key` y `telegram_token` en texto plano en `config.json` | Leídos de variables de entorno (`.env`) |
| Logging | `print()` disperso, `except: pass` silencioso en ~15 lugares | logging estructurado con archivo rotativo, sin `except: pass` |
| Permisos por canal | Telegram y Discord tienen el mismo acceso que Desktop | Telegram/Discord tienen acciones restringidas (solo verde) |

## Criterios de aceptación

### CA1 — Niveles de riesgo
- [ ] Toda acción del sistema está clasificada como verde, amarillo o rojo
- [ ] Las acciones amarillas muestran confirmación y esperan respuesta antes de ejecutar
- [ ] Las acciones rojas están bloqueadas por defecto (solo con permiso explícito)

### CA2 — Confirmaciones
- [ ] `shutdown_pc()` pide confirmación antes de apagar
- [ ] `close_app()` con `/F` pide confirmación
- [ ] Borrar archivos/carpetas pide confirmación
- [ ] Ejecutar código generado por IA (code_execution_skill) pide confirmación
- [ ] Crear/modificar skills automáticamente pide confirmación
- [ ] Si el usuario cancela, se retorna mensaje claro sin ejecutar

### CA3 — Secretos en .env
- [ ] `deepseek_api_key`, `telegram_token` y cualquier otra key se leen de variables de entorno
- [ ] `config.json` ya no contiene secretos (solo configuración no sensible)
- [ ] `config_manager.py` tiene fallback si la variable de entorno no existe
- [ ] Existe un archivo `.env.example` con las variables necesarias (sin valores reales)
- [ ] `.env` está en `.gitignore`

### CA4 — Logging centralizado
- [ ] `main.py` inicializa logging con `RotatingFileHandler` al arrancar
- [ ] Todos los submódulos usan `logging.getLogger(__name__)` en vez de `print()`
- [ ] Los logs se escriben a `agente_ia/logs/orion.log` con rotación (5 MB, 3 backups)
- [ ] Formato: `YYYY-MM-DD HH:MM:SS [módulo] NIVEL: mensaje`
- [ ] No hay nuevos `except: pass` o `except Exception: pass` sin logging

### CA5 — Allowlist por canal
- [ ] Telegram solo puede ejecutar acciones verdes
- [ ] Discord solo puede ejecutar acciones verdes
- [ ] Desktop mantiene acceso completo (con confirmaciones en amarillo/rojo)
- [ ] Voz (wake word) solo acciones verdes
- [ ] Si un canal intenta una acción no permitida, se responde con mensaje claro

## Casos borde
- ¿Qué pasa si no existe `.env`? → `config_manager.py` muestra advertencia y usa defaults no sensibles
- ¿Qué pasa si el logging falla (permisos de escritura)? → Fallback a consola, no bloquear el arranque
- ¿Qué pasa si el usuario no responde la confirmación? → Timeout de 30s, se cancela la acción
- ¿Confirmaciones en Telegram? → Botón inline "Sí / No" o respuesta de texto

## Asumidos
- ASUMIDO: Se usará el módulo `logging` estándar de Python con `RotatingFileHandler`
- ASUMIDO: El archivo `.env` se cargará con `python-dotenv`
- ASUMIDO: `config.json` mantendrá `agent_name` y `agent_pronunciation` (no sensibles)
- ASUMIDO: Voz (wake word) no tendrá interfaz de confirmación — solo acciones verdes
