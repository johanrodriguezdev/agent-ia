# SPEC-018 — Confirmación conversacional para `/eliminar` en Telegram

**Estado:** ✅ COMPLETADO — aprobada por Johan sin ajustes, incluidos los 6 puntos "Asumidos" (2026-08-20)
**Categoría:** SEGURIDAD
**Tipo:** SEGURIDAD
**Fecha:** 2026-08-20

## Objetivo
Cerrar el bypass real de seguridad en `/eliminar [id]` de Telegram
(`channels/telegram_bot.py::cmd_eliminar`, línea 500), que hoy borra tareas llamando
`task_manager.delete_task()` directo, sin pasar por `security_manager.require_confirmation()`,
pese a que `delete_task` está clasificado 🟡 Amarillo (`core/security_manager.py:316`).

Johan eligió explícitamente la opción de mayor alcance: no el bloqueo mínimo (que dejaría
`/eliminar` permanentemente inutilizado en Telegram, ver investigación en `REQ-018-context.md`),
sino diseñar un mecanismo de confirmación conversacional real para Telegram — habilitado de forma
quirúrgica **solo para `delete_task`**, sin abrir la puerta al resto de las acciones Amarillas del
sistema ni relajar en bloque la política de canal ya decidida en REQ-006
(`CHANNEL_ALLOWED_LEVELS[ChannelType.TELEGRAM] = [RiskLevel.GREEN]`, sin cambios).

De paso, se cierra también el bypass de **auditoría** (no de seguridad) ya documentado en
SPEC-017 para `/completar`, `/nueva` y `/tareas`, que llaman `task_manager` directo en vez de
`agents/tool_registry.py::execute_tool()`.

## Alcance
- **Incluye:**
  - Gatear `/eliminar [id]` de Telegram vía `security_manager.require_confirmation("delete_task",
    ChannelType.TELEGRAM, ...)` — mismo punto único de decisión que ya usa
    `ui/webview/bridge.py::_delete_task_flow()` para Desktop.
  - Diseñar y registrar un **adaptador de confirmación conversacional nuevo** para
    `ChannelType.TELEGRAM` (`register_confirmation_adapter(ChannelType.TELEGRAM, ...)`): el bot
    envía "¿confirmás? sí/no", espera la respuesta del usuario, aplica timeout fail-closed.
  - Un **mecanismo de excepción por canal+acción**, separado de `CHANNEL_ALLOWED_LEVELS`, que
    habilite específicamente `delete_task` en Amarillo para el canal Telegram — sin tocar
    `CHANNEL_ALLOWED_LEVELS` en bloque ni ninguna otra acción registrada.
  - Conectar `/completar`, `/nueva` y `/tareas` de Telegram a `execute_tool()` usando los tools
    ya existentes `task_complete`/`task_create`/`task_list` (🟢 Verde, sin cambio de
    comportamiento observable) — solo trazabilidad en `audit.db`.
- **No incluye:**
  - Discord — confirmado en la investigación que no tiene comandos estructurados con el mismo
    patrón de bypass (`channels/discord_bot.py` sin cambios).
  - Agregar un tool `task_delete` en `agents/tool_registry.py` para borrar tareas por lenguaje
    natural — el REQ cierra el bypass del comando explícito `/eliminar`, no agrega una vía nueva
    de borrado (ver "Asumidos").
  - Cambiar la clasificación de riesgo de `delete_task` ni de ninguna otra acción existente.
  - Modificar `core/resolution.py::RESOLVERS`/`_try_task_tool()`.
  - Habilitar cualquier otra acción Amarilla en Telegram, Discord, Voice o API.
  - El hallazgo aparte de `except Exception: pass` silencioso en
    `channels/discord_bot.py::slash_limpiar` (líneas 182-186) — Johan confirmó que queda anotado
    para un REQ futuro, fuera de esta SPEC.

## Módulos afectados
- `channels/telegram_bot.py` — `cmd_eliminar()` (línea 500) pasa a llamar
  `security_manager.require_confirmation()` en vez de `task_manager.delete_task()` directo;
  `cmd_completar()` (468), `cmd_nueva()` (424) y `cmd_tareas()` (416) pasan a invocar
  `execute_tool("task_complete"/"task_create"/"task_list", ...)`; `handle_text()` (533) o un
  handler nuevo con prioridad sobre él debe interceptar el próximo mensaje de un usuario con una
  confirmación pendiente, antes de que llegue a `GlassGateway().process()`.
- `core/security_manager.py` — nuevo mecanismo de excepción por canal+acción (ver CA-02); sin
  tocar `CHANNEL_ALLOWED_LEVELS` en bloque ni ningún `RiskLevel` existente.
- `core/confirmation.py` — sin cambios de contrato: el adaptador que se registre para
  `ChannelType.TELEGRAM` debe seguir cumpliendo la firma síncrona `(action_name, mensaje) -> bool`
  (CA-11 de REQ-006) — el puente async→sync hacia `python-telegram-bot` es responsabilidad del
  adaptador nuevo, no de este módulo.
- Archivo nuevo (nombre y ubicación exacta a definir por `orion-architect`, p. ej.
  `channels/telegram_confirmation_adapter.py`) — adaptador de confirmación conversacional para
  `ChannelType.TELEGRAM`, análogo en intención a `ui/webview/confirmation_adapter.py::
  WebViewConfirmationAdapter` de REQ-015, pero resolviendo un puente async/asyncio en vez de un
  puente hilo-worker↔hilo-Qt.
- `main.py` — registra el adaptador nuevo al iniciar el bot de Telegram, análogo a como ya
  registra `register_confirmation_adapter(ChannelType.DESKTOP, _desktop_confirm)` (línea 59).
- `tests/` — cobertura nueva para CA-01 a CA-14 (ver criterios de aceptación).

## Comportamiento actual vs deseado
| Actual | Deseado |
|--------|---------|
| `/eliminar [id]` en Telegram borra la tarea llamando `task_manager.delete_task()` directo — sin pedir confirmación, sin pasar por `security_manager`, sin quedar en `audit.db`. Bypass real del gate Amarillo. | `/eliminar [id]` pide confirmación conversacional ("¿confirmás? sí/no") antes de borrar, a través del gate real de `security_manager.require_confirmation()`, con timeout fail-closed de 120s, y queda auditado en `audit.db` igual que cualquier otra acción Amarilla. |
| Telegram no tiene ningún adaptador de confirmación registrado — cualquier acción Amarilla (incluida `delete_task`) queda bloqueada sin excepción, por `CHANNEL_ALLOWED_LEVELS[TELEGRAM] = [GREEN]`. | Telegram tiene un adaptador de confirmación conversacional real, pero habilitado **solo** para `delete_task` — el resto de las acciones Amarillas (`shutdown`, `close_app`, `delete_file`, etc.) sigue bloqueado en Telegram exactamente igual que hoy. |
| `/completar`, `/nueva` y `/tareas` llaman `task_manager` directo — no quedan registrados en `audit.db`, aunque no representan riesgo de seguridad (GREEN). | Los tres pasan por `execute_tool()` — quedan auditados, comportamiento observable para el usuario idéntico. |

## Criterios de aceptación

- [ ] **CA-01 — `/eliminar` gateado.** `cmd_eliminar()` llama
  `security_manager.require_confirmation("delete_task", ChannelType.TELEGRAM, details=..., user_id=...)`
  antes de invocar `task_manager.delete_task()`. Si la confirmación no llega a `True`, la tarea NO
  se borra y el usuario recibe un mensaje de cancelación explícito (no el mensaje de éxito).

- [ ] **CA-02 — Excepción por canal+acción, no por canal en bloque.** Existe un mecanismo nuevo
  y explícito (estructura separada de `CHANNEL_ALLOWED_LEVELS`, p. ej. una tabla de excepciones
  `(canal, acción) → permitido`) que hace que, específicamente, `delete_task` en el canal Telegram
  se evalúe como candidato válido a pedir confirmación — sin modificar
  `CHANNEL_ALLOWED_LEVELS[ChannelType.TELEGRAM]` (que sigue siendo `[RiskLevel.GREEN]`, sin
  cambios) y sin introducir una regla genérica "Telegram + YELLOW = permitido".

- [ ] **CA-03 — Ninguna otra acción Amarilla se vuelve alcanzable en Telegram.** Test de
  regresión que recorre **todas** las acciones YELLOW hoy registradas y confirma que siguen
  denegadas en `ChannelType.TELEGRAM` después del cambio — excepto `delete_task`:
  `shutdown`, `restart`, `close_app`, `delete_file`, `delete_folder`, `delete_conversation`,
  `delete_project`, `execute_code`, `create_skill`, `modify_skill`, `delete_skill`,
  `send_message`, `CLOSE_APP`, `SYS_POWER_OFF`, `EXECUTE_CODE`, `CREATE_SKILL`, `MODIFY_SKILL`,
  `DELETE_SKILL`, `write_file_direct`, `save_file_desktop` (lista completa de YELLOW registrado
  hoy en `core/security_manager.py:300-382`).

- [ ] **CA-04 — Adaptador de confirmación conversacional registrado.** Existe un adaptador
  `(action_name, mensaje) -> bool` registrado vía
  `register_confirmation_adapter(ChannelType.TELEGRAM, ...)`. Al pedir confirmación, el bot envía
  al usuario, por Telegram, el mismo mensaje que ya arma `require_confirmation()`
  (`core/security_manager.py:262-274`: *"¿Estás seguro de que quieres ejecutar 'delete_task'?
  (...) Escribe 'sí' para confirmar, o cualquier otra cosa para cancelar"*) — el adaptador no
  duplica ni reformula ese texto.

- [ ] **CA-05 — Correlación con el próximo mensaje del usuario.** El siguiente mensaje de
  **texto** que envíe el mismo `user_id` (`str(update.effective_user.id)`, mismo identificador
  que ya usa `task_manager` para dueño de tarea) se intercepta **antes** de llegar a
  `GlassGateway().process()`/`resolve()`, y se interpreta como la respuesta a la confirmación
  pendiente — no se procesa además como un comando o mensaje nuevo. Se consume una sola vez.

- [ ] **CA-06 — Criterio de confirmación explícito, sin ambigüedad.** Solo cuenta como "sí"
  exactamente el mismo criterio que ya usa el resto del sistema (`_desktop_confirm`/
  `WebViewConfirmationAdapter` indirectamente, vía el mismo texto de prompt):
  `respuesta.strip().lower() in ("sí", "si", "yes", "s")`. Cualquier otro contenido — incluida una
  respuesta ambigua ("tal vez", "dale", "sip") o un comando nuevo del usuario — cuenta como
  cancelación. Nunca se interpreta ambigüedad como confirmación (fail-closed).

- [ ] **CA-07 — Timeout fail-closed de 120 segundos.** Mismo valor que
  `WebViewConfirmationAdapter.CONFIRM_TIMEOUT_SECONDS` (REQ-015,
  `ui/webview/confirmation_adapter.py:27`). Si el usuario no responde en ese lapso, la
  confirmación se resuelve a `False` — nunca `True` por defecto. El estado pendiente se limpia
  tras resolverse (por respuesta o por timeout) — nunca queda un estado de espera "vivo" para una
  respuesta que ya no puede llegar (mismo criterio que el Hallazgo B de `security-audit-015.md`).

- [ ] **CA-08 — No bloquea el loop de `asyncio` para otros usuarios.** Mientras una confirmación
  está pendiente para un `user_id`, otros usuarios del bot pueden seguir interactuando con
  normalidad (enviar mensajes, usar comandos, recibir respuestas) sin demora perceptible causada
  por la espera. El puente entre la llamada síncrona y bloqueante que exige el contrato de
  `core/confirmation.py` (CA-11 de REQ-006: *"Cada adaptador es una función síncrona... Si un
  canal async necesita confirmar de verdad, es responsabilidad de ese canal construir el puente
  async→sync"*) y el runtime `asyncio` de `python-telegram-bot` no debe ejecutarse en el hilo del
  event loop principal.

- [ ] **CA-09 — Una sola confirmación pendiente por usuario.** Si llega un segundo pedido de
  confirmación para el mismo `user_id` mientras el primero sigue pendiente, el sistema no apila
  ni reemplaza silenciosamente — comportamiento exacto a definir por `orion-architect` (ver
  "Asumidos"), pero debe quedar determinístico y documentado, nunca dejar dos esperas abiertas
  para el mismo usuario a la vez.

- [ ] **CA-10 — `/completar`, `/nueva`, `/tareas` auditados.** Los tres invocan
  `agents/tool_registry.py::execute_tool()` con los tools ya registrados `task_complete`,
  `task_create`, `task_list` respectivamente, en vez de llamar `task_manager` directo. El
  comportamiento observable (mensajes de éxito/error mostrados al usuario) es idéntico al actual
  — el único cambio es que ahora quedan registrados en `audit.db`. Ninguno de los tres cambia de
  `RiskLevel` (siguen 🟢 Verde).

- [ ] **CA-11 — Clasificación de riesgo intacta.** `delete_task` sigue registrado 🟡 YELLOW en
  `core/security_manager.py`. `task_complete`/`task_create`/`task_list` siguen 🟢 GREEN.
  `CHANNEL_ALLOWED_LEVELS` no se modifica para ningún canal (Telegram sigue `[GREEN]` como valor
  de la lista general — el mecanismo de CA-02 es una excepción aditiva evaluada aparte, nunca un
  reemplazo de esta lista).

- [ ] **CA-12 — Pipeline de `resolve()` intacto.** Cero cambios a `core/resolution.py::RESOLVERS`
  ni a `_try_task_tool()` — no se agrega ningún trigger de borrado por lenguaje natural. Test de
  regresión: `pytest tests/test_resolution.py` (o el archivo que corresponda) sigue en verde sin
  modificaciones.

- [ ] **CA-13 — Discord sin cambios.** `channels/discord_bot.py` no se modifica en este REQ.

- [ ] **CA-14 — Auditoría sin caminos paralelos.** La confirmación de Telegram queda registrada
  en `audit.db` con el mismo mecanismo (`_log_audit()`) y los mismos valores de `result` que ya
  usa el resto del sistema (`"confirmada"`, `"cancelada"`, `"bloqueada_..."`) — no se crea una
  tabla ni un mecanismo de auditoría nuevo y paralelo solo para Telegram.

## Casos borde
- Usuario no responde nunca → timeout de 120s → cancelado (CA-07).
- Usuario responde con algo ambiguo ("tal vez", "sip", "dale") → no es uno de los tokens exactos
  de CA-06 → cuenta como cancelación, no como confirmación.
- Usuario envía otro comando (`/tareas`, `/nueva algo`) mientras hay una confirmación pendiente →
  ese mensaje se consume como respuesta a la confirmación (CA-05), no como el comando nuevo. Como
  no coincide con los tokens de "sí", cuenta como cancelación. El comando que el usuario quiso
  ejecutar realmente se pierde — debe reenviarlo después de que la confirmación se resuelva.
- Usuario responde por **voz** en vez de texto mientras hay una confirmación pendiente → fuera de
  alcance de CA-05 (solo intercepta mensajes de texto): el mensaje de voz se transcribe y procesa
  por el camino normal (`resolve()`) mientras la confirmación pendiente sigue esperando hasta
  expirar por timeout, sin que la respuesta por voz la resuelva.
- Segundo `/eliminar` (u otra acción con confirmación pendiente) para el mismo usuario mientras el
  primero sigue esperando → ver CA-09 y "Asumidos".
- El proceso del bot se reinicia con una confirmación pendiente en memoria (sin persistencia en
  disco) → el estado pendiente y el hilo/tarea que lo esperaba se destruyen junto con el proceso —
  no queda un borrado a mitad de camino ni un estado huérfano después del reinicio. Mismo criterio
  que ya aplica hoy a la confirmación de Desktop (tampoco persiste entre reinicios).
- Telegram en un chat grupal (si el bot está agregado a un grupo, no solo chats privados) → la
  correlación de CA-05 es por `user_id`, no por `chat_id` — ver "Asumidos".

## Asumidos
- ASUMIDO: no se agrega ningún tool `task_delete` a `agents/tool_registry.py` — este REQ cierra
  el bypass del comando explícito `/eliminar`, no habilita borrado de tareas por lenguaje natural
  en ningún canal. Confirmar antes de implementar.
- ASUMIDO: ante una segunda confirmación pendiente para el mismo usuario mientras la primera sigue
  activa (CA-09), el comportamiento propuesto es **rechazar la segunda de inmediato** (el bot
  responde algo como "Ya tenés una confirmación pendiente, Señor — respondé sí/no primero") en vez
  de cancelar la primera silenciosamente o apilarlas. Confirmar con `orion-architect`/Johan antes
  de implementar.
- ASUMIDO: la correlación de CA-05 se hace únicamente por `user_id` (mismo identificador que ya
  usa `task_manager` para dueño de tarea), sin distinguir chat privado de chat grupal. Confirmar
  si el bot de Telegram de Johan se usa en grupos, donde esto podría ser relevante.
- ASUMIDO: 120 segundos de timeout (mismo valor que `WebViewConfirmationAdapter` de REQ-015) es
  un valor razonable también para Telegram, pese a que la dinámica de un chat es distinta a la de
  un modal en pantalla. Confirmar que no se prefiere un valor distinto.
- ASUMIDO: mensajes de voz mientras hay una confirmación pendiente no cuentan como respuesta
  válida (ver "Casos borde") — confirmar que este límite de alcance es aceptable.
- ASUMIDO: el nombre/ubicación exacta del adaptador nuevo, y el mecanismo concreto del puente
  async→sync (p. ej. `asyncio.to_thread()` + `threading.Event`, análogo a como
  `WebViewConfirmationAdapter` usa un `pyqtSignal` para cruzar del hilo worker al hilo de Qt, pero
  aplicado a un loop de `asyncio` en vez de un hilo de GUI) quedan a definición de
  `orion-architect` — esta SPEC fija el comportamiento observable (CA-01 a CA-14), no la
  implementación interna.
