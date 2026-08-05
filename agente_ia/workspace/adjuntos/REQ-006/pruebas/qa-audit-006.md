# Auditoría QA REQ-006 [A] (CA-01 a CA-17)

`orion-qa` — auditoría de seguridad/calidad final, gate previo a la prueba manual del
humano. No repite la verificación funcional de `orion-tester` (17/17 PASS, 95 tests, 0
regresiones, ver `pruebas/test-results-006.md`) — se enfoca en seguridad, niveles de
riesgo, logging, convenciones y consistencia con la arquitectura aprobada.

Archivos auditados: `core/resolution.py`, `core/security_manager.py`, `core/base_agent.py`,
`core/orchestrator.py`, `router/dispatcher.py`, `main.py`, `channels/gateway.py`,
`channels/telegram_bot.py`, `agents/tool_registry.py`, `core/confirmation.py` — código
fuente completo leído (no solo diffs) más `git diff` dirigido para separar cambios de
REQ-006 de líneas preexistentes.

## Seguridad

- **Sin secretos hardcodeados.** Grep dirigido (`api_key|token|secret|password\s*=\s*"..."`)
  sobre los 10 archivos auditados: 0 coincidencias. `channels/telegram_bot.py::_get_token()`
  sigue leyendo el token vía `config_manager.get_telegram_token()`, no en texto plano.

- **`ActionDenied` no expone stacktraces ni rutas de archivo.**
  - `core/security_manager.py::ActionDenied.__init__` construye el mensaje solo a partir de
    `action_name`, `channel.value` y `reason` (string corto pasado por el propio código, no
    input crudo del usuario) — sin `traceback`, sin `__file__`, sin `repr(exc)`.
  - `core/resolution.py::_denied_message()` devuelve exactamente
    `f"⛔ Acción '{exc.action_name}' no autorizada."` — no incluye `exc.reason` ni `exc.channel`
    en el texto que llega al usuario final, solo el nombre de la acción.
  - Los dos gates reales (`router/dispatcher.py::dispatch()` y
    `agents/tool_registry.py::execute_tool()`) levantan `ActionDenied` con `reason` genérico
    (`"denegado por security_manager"` / `"tool no registrado"`), nunca con detalle de
    excepción interna.
  - Todos los resolvers de `RESOLVERS` en `core/resolution.py` capturan su propio
    `ActionDenied` localmente y producen `ResolutionResult(denied=True, text=_denied_message(...))`;
    `resolve()` tiene además una red de seguridad `except ActionDenied` de nivel superior.
    Ningún camino deja que `ActionDenied` suba sin capturar hasta un handler que imprima
    `str(exc)` con detalle interno al usuario.

- **`CHANNEL_ALLOWED_LEVELS` no fue tocado en su contenido para los 4 canales existentes**
  (`DESKTOP=[GREEN,YELLOW]`, `TELEGRAM/DISCORD/VOICE=[GREEN]`) — confirmado por `git diff`.
  Se agregaron dos entradas nuevas (`API`, `UNKNOWN`), ambas `[GREEN]`, aditivas y
  consistentes con el resto de la matriz fail-closed. `resolve_channel()` (nuevo) resuelve
  `None`/valor no reconocido a `ChannelType.UNKNOWN` en vez de `DESKTOP` — decisión
  correcta, un caller que "pierde" el canal no hereda el nivel más permisivo.

- **`register_action()` ahora rechaza degradar una acción ya RED** (con `logger.critical` +
  entrada de auditoría `"reclasificacion_bloqueada"`) — refuerzo defensivo consistente con
  el deny-list fail-closed de REQ-005, no presente antes.

- La deny-list RED de 10 categorías de REQ-005 (`format_disk`, `delete_database`,
  `expose_secrets`, `modify_source_code`, `send_email_as_user`, `post_social_media`,
  `elevated_system_command`, `install_uninstall_software`, `modify_system_env_vars`,
  `grant_third_party_access`) está intacta en `_register_default_actions()`.

## Niveles de riesgo

- `task_create`/`task_list`/`task_complete` están registrados como `RiskLevel.GREEN` en
  `agents/tool_registry.py` (líneas ~152-194) vía `register_tool()` → `register_action()`,
  y ahora pasan por `execute_tool()`, que es un gate real (`ActionDenied` si no está
  registrado o si `security_manager` deniega, y solo entonces `spec.invoke(params)`).
  Cierra H3 (antes `channels/gateway.py::_try_create_task/_try_list_tasks/_try_complete_task`
  llamaban a `tasks/task_manager.py` directo, sin ningún gate) — confirmado que esos tres
  métodos fueron eliminados de `channels/gateway.py` (`git diff`, -115 líneas).
  Clasificación GREEN correcta: preserva el comportamiento visible actual (crear tareas por
  Telegram no estaba bloqueado antes) mientras ahora queda auditado — el fix es de
  visibilidad/clasificación, no de bloqueo nuevo, tal como documenta la arquitectura.

- **Ningún canal ganó capacidad YELLOW/RED nueva.** Telegram/Discord/Voice siguen limitados
  a `[GREEN]` en `CHANNEL_ALLOWED_LEVELS` (sin cambios). Solo `ChannelType.DESKTOP` tiene un
  adaptador de confirmación real registrado (`main.py::_desktop_confirm`, vía
  `register_confirmation_adapter(ChannelType.DESKTOP, _desktop_confirm)`); ningún canal
  remoto registra adaptador, así que su rama YELLOW cae en
  `"bloqueada_sin_adaptador"` (fail-closed) — confirmado en `core/security_manager.py`.

- **Hallazgo menor, no bloqueante — inconsistencia entre `desarrollo-log-006.md` y el diff
  real.** El log de desarrollo afirma `_handle_shutdown()`/`_handle_restart()` en
  `channels/telegram_bot.py` quedaron "sin cambios (ya gateaban correctamente desde
  REQ-005)". El `git diff` muestra que sí cambiaron: pasaron de
  `security_manager.is_action_allowed("shutdown", ChannelType.TELEGRAM)` (solo compara
  nivel vs. canal, sin logging de auditoría) a
  `security_manager.require_confirmation("shutdown", ChannelType.TELEGRAM, details=..., user_id=...)`
  (el gate central completo, con `_log_audit`). El resultado observable para el usuario de
  Telegram es idéntico (`shutdown`/`restart` siguen clasificados `YELLOW`, Telegram sigue
  `[GREEN]` únicamente ⇒ denegado), pero ahora el intento queda registrado en `audit.db` con
  `user_id`, que antes no ocurría. Es una mejora de seguridad real (más logging, no menos),
  consistente con `security-levels.md`, y no representa scope creep peligroso — pero el
  desarrollo-log debería corregirse para reflejar el cambio real. No amerita rechazo.

## Logging

- Los dos `except Exception: pass` de `channels/gateway.py` señalados explícitamente en el
  encargo fueron corregidos:
  - El envoltorio en `process()` alrededor de `self._save_semantic(...)` (era
    `try: ... except Exception: pass`) fue eliminado — la responsabilidad de manejar el
    error se movió dentro del propio método.
  - `_save_semantic()` pasó de `except Exception: pass` a
    `except Exception as e: logger.warning(f"Error guardando memoria semántica: {e}")` —
    confirmado que **no** se loguea `text` ni `result` (contenido del usuario), solo el
    mensaje de la excepción, igual que pide la arquitectura.
- No se encontraron nuevos `except Exception: pass` silenciosos introducidos por REQ-006 en
  ninguno de los 10 archivos auditados (`git diff` completo revisado archivo por archivo).
- Observación no bloqueante: `channels/telegram_bot.py` conserva varios
  `except Exception: pass` preexistentes (limpieza de archivos temporales con `os.unlink`,
  `chat.send_action` best-effort, fallback de traducción TTS) — confirmado vía `git diff`
  que **ninguno de estos fue tocado por REQ-006**; son de I/O de UI de bajo riesgo (no
  ocultan errores de negocio ni de seguridad), no los dos señalados en el encargo. Se deja
  como nota de deuda técnica preexistente, no como motivo de rechazo de este REQ.
- `resolve()` loguea `f"resolve() canal=... user=...: {text[:80]}"` — trunca el texto del
  usuario a 80 caracteres, razonable para debugging sin volcar payloads completos.
- `format_details()` en `security_manager.py` usa una **allowlist** explícita de claves
  (`app_name`, `task`, `path`, etc., nunca `channel` ni el `params` crudo) para lo que se
  imprime en el prompt de confirmación y se persiste en `audit.db` — diseño correcto para
  evitar que credenciales o contenido de archivo terminen en el log de auditoría.

## Consistencia de código

- **Type hints**: presentes en las funciones públicas de los 3 módulos nuevos
  (`core/resolution.py`, `core/confirmation.py`, `agents/tool_registry.py`) y en las firmas
  modificadas de `security_manager.py` (`resolve_channel`, `register_action`, `check_coverage`).
- **Sin `print()` de debug** en el código de producción nuevo/modificado. Se verificaron los
  10 archivos: `main.py` y `channels/telegram_bot.py` conservan `print()` de banner de
  arranque en consola (preexistentes, no debug, no tocados por el diff de REQ-006 salvo el
  cálculo de `channel` en `main.py`). El único `print(msg)` remanente dentro de
  `security_manager.py` (rama RED, ~línea 292) está **fuera del rango del diff de REQ-006**
  — confirmado con `git diff`, el hunk de la rama YELLOW termina y salta directo a
  `_register_default_actions()` sin tocar la rama RED — consistente con lo que declara la
  arquitectura ("El resto de la función ... no cambia una sola línea"). No es una regresión
  de este REQ.
- **Límite de 100 caracteres**: hallazgo menor no bloqueante. Un pequeño número de líneas
  nuevas supera el límite —comentarios de separación decorativa
  (`core/resolution.py:44/47`, `agents/tool_registry.py:87/90`, ambos ~137 chars) y algunos
  `logger.info(f"...")` de una sola línea (`core/confirmation.py:31` = 107 chars,
  `agents/tool_registry.py:60` = 103 chars, y varias líneas de docstring/comentario en
  `core/security_manager.py`). Ninguna es lógica de negocio ni afecta legibilidad real en
  editores modernos; se señala por completitud de la regla, no bloquea el REQ.
- **Imports**: orden estándar → third-party → local respetado en los archivos nuevos
  (`core/resolution.py`, `core/confirmation.py`, `agents/tool_registry.py`).
- **Sin scope creep**: no existe `core/reasoning_loop.py` ni ningún otro archivo de la
  sección `[B]` de la SPEC (CA-18 a CA-24) — verificado (`find . -iname "*reasoning_loop*"`
  sin resultados). El código de REQ-006 se limita estrictamente a CA-01 a CA-17.
- **Bug de `_try_intent` (`intent.value` sobre un `str` plano)**: la corrección
  (`intent_name = intent.value if hasattr(intent, "value") else str(intent)`) replica
  exactamente el patrón defensivo preexistente de `router/dispatcher.py:50`
  (`action_name = intent.value if hasattr(intent, "value") else str(intent)`). Consistente
  con el resto del sistema, no introduce un riesgo nuevo — es el mismo patrón ya probado en
  producción, aplicado en un segundo punto que antes no lo necesitaba.

## Observación no bloqueante — cadena `AgentTool`/`_DynamicAgentInstance` (CA-09)

`AgentTool.execute()` en `core/base_agent.py` sigue envolviendo `self.function(params)` en
un `except Exception as e: return f"Error en herramienta '{self.name}': {str(e)[:100]}"`
genérico — esto captura y convierte `ActionDenied` en un string en vez de propagarla, lo
que significa que el `except ActionDenied: continue` agregado a
`_DynamicAgentInstance.execute()` (el fix de CA-09/H7) **nunca se dispara realmente para
instancias reales de `AgentTool`**, solo para dobles de test que levantan `ActionDenied`
directamente (como hace `tests/test_base_agent.py`, que documenta esta limitación
explícitamente en su docstring, citando la Observación A de `orion-security`).

Se investigó si esto es una brecha de seguridad viva: **no lo es**. `core/orchestrator.py`
confirma que `process_task()` delega el 100% de la resolución a `core.resolution.resolve()`;
`_process_with_agents()` / `_execute_single_agent()` / `_execute_agent_chain()` (y por lo
tanto `_DynamicAgentInstance.execute()` y `AgentTool.execute()`) no tienen ningún invocador
vivo en el pipeline de REQ-006 — se conservan solo por compatibilidad estructural con
`tests/test_agents.py`, según el propio docstring del módulo. Lo mismo aplica a
`router/dispatcher.py::dispatch_as_tool()`, que también traga `ActionDenied` en su
`except Exception` genérico, pero solo se usa como la tool "dispatcher" de ese mismo camino
muerto.

**Conclusión**: no bloquea REQ-006 [A] porque no hay ningún camino de ejecución real que lo
alcance hoy. Es una mina latente para REQ-007 (bucle de agente con herramientas, CA-18 a
CA-24): si esa iniciativa reactiva `_process_with_agents`/`_DynamicAgentInstance` como
camino vivo, `AgentTool.execute()` deberá dejar propagar `ActionDenied` (o el
`_DynamicAgentInstance` deberá inspeccionar el string de error de otra forma) para que el
fix de H7 funcione en producción, no solo en tests. Recomiendo que el baseline de REQ-007
registre este punto explícitamente.

## Veredicto: ✅ COMPLETADO

Ningún hallazgo de los anteriores es bloqueante:
- Seguridad: sin secretos, `ActionDenied` no filtra información interna, `CHANNEL_ALLOWED_LEVELS`
  intacto para los 4 canales existentes, deny-list RED intacta.
- Niveles de riesgo: `task_*` correctamente GREEN y gateados, ningún canal ganó capacidad
  nueva YELLOW/RED.
- Logging: los dos `except: pass` señalados en el encargo están corregidos sin filtrar
  contenido de usuario.
- Convenciones: type hints, sin debug prints nuevos, imports ordenados; los excesos de
  línea de 100 caracteres son cosméticos (comentarios/logs), no bloquean.
- Consistencia arquitectónica: sin scope creep hacia `[B]`; el fix de `_try_intent` es
  coherente con el resto del sistema.

Se documentan dos observaciones no bloqueantes para seguimiento (no requieren volver a
`orion-dev` en este REQ):
1. Corregir `desarrollo-log-006.md` para reflejar el cambio real en
   `_handle_shutdown`/`_handle_restart` de `channels/telegram_bot.py` (`is_action_allowed` →
   `require_confirmation`).
2. Registrar en el baseline de REQ-007 que `AgentTool.execute()` deberá dejar propagar
   `ActionDenied` si se reactiva el camino `_DynamicAgentInstance`.

**Falta la prueba manual del humano antes de `LISTO_PARA_COMMIT`.** No se generó ni
ejecutó ningún `git commit`.
