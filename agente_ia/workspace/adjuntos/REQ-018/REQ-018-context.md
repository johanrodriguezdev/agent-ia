# Contexto REQ-018 — Bypass del gate de confirmación Amarillo en `/eliminar` de Telegram

## Resumen ejecutivo
El comando slash de Telegram `/eliminar [id]` borra una tarea llamando directo a
`task_manager.delete_task()`, sin pasar por `security_manager.require_confirmation()`. Como
`delete_task` está clasificado 🟡 Amarillo, esto es un bypass real del mecanismo fail-closed
introducido por REQ-005. Objetivo del REQ: confirmar el alcance exacto del bypass (¿solo
`/eliminar`? ¿Discord también?) y diseñar un fix mínimo y quirúrgico que haga pasar ese camino
por el gate de confirmación existente, sin tocar la clasificación de riesgo ni el resto del
pipeline de `resolve()`.

## Origen de este REQ
Este REQ **nace de una investigación de REQ-017** (mejora de comandos de tareas en lote,
categoría CORE) pero es **completamente independiente** — no se mezcla con REQ-017 ni bloquea
su avance. Fue documentado por `orion-spec` en
`workspace/adjuntos/REQ-017/spec/SPEC-017.md`, sección "Verificación de arquitectura", y
confirmado por Johan como REQ aparte.

### Cita textual completa de SPEC-017.md (líneas 81-91)
> **Telegram tiene además un camino paralelo y estructurado** que este REQ NO toca:
> `channels/telegram_bot.py::cmd_completar()` (línea 468, comando `/completar [id]`) llama
> `task_manager.complete_task()` **directo**, sin pasar por `resolve()`/`_try_task_tool`/
> `execute_tool()`. Ya exige un ID numérico explícito (no tiene la ambigüedad de "todas"), así
> que queda fuera de alcance. **Nota de riesgo pre-existente, no introducida por este REQ:** ese
> mismo comando directo existe también para `/eliminar [id]` (línea 500,
> `task_manager.delete_task()` directo) — `delete_task` está clasificado 🟡 Amarillo en
> `security_manager.py` (línea 316), pero este camino de Telegram lo ejecuta sin pasar por
> `security_manager.require_confirmation()`. Es un hallazgo de seguridad real pero anterior a
> REQ-017 y fuera de su objetivo (NLU de comandos ambiguos, no auditoría de gates existentes) —
> se documenta acá para que quede registrado y no se pierda, no para resolverlo en este REQ.

### Aclaración importante
`/completar [id]` **no tiene el mismo problema** — `complete_task` está clasificado
`RiskLevel.GREEN` en `agents/tool_registry.py` (línea 192), no requiere confirmación de por sí.
El bypass es específico de `/eliminar [id]` porque `delete_task` SÍ es 🟡 Amarillo. Los comandos
equivalentes en lenguaje natural (vía `resolve()` → `_try_task_tool` → `execute_tool()`) **sí**
pasan correctamente por el gate — este bypass es específico del camino estructurado del comando
slash `/eliminar`, no de todo Telegram ni de la ruta de lenguaje natural.

## Estado actual
- **Estado tracker:** ARQUITECTURA_APROBADA (`Aprobacion_Arquitectura=APROBADO` en CSV, vía
  `update-tracker.mjs`) — CSV sin cambios adicionales tras el addendum de seguridad; el estado
  del tracker no retrocede por una auditoría, el ciclo de re-chequeo vive en
  `arquitectura-018.md` §15 y `pruebas/security-audit-018.md`
- **Último agente:** orion-security (re-chequeo del addendum de seguridad completado — veredicto
  ✅ APROBADO, Hallazgo A resuelto y verificado experimentalmente; 1 hallazgo nuevo no bloqueante,
  E, documentado para `orion-dev` junto con B y C. Handoff emitido a `orion-dev`.)
- **Fecha última actualización:** 2026-08-20
- **Rama git:** — (rama activa del repo es `feature/REQ-015-webview-ui`; no asumir que este REQ
  usa esa rama — Johan no especificó una al aprobar la arquitectura; `.claude/rules/git.md`
  exige preguntar antes de asumirla. No bloquea el handoff a `orion-security`/`orion-dev` —
  queda pendiente para cuando corresponda crear la rama de trabajo)
- **Categoría:** SEGURIDAD
- **Tipo de cambio:** SEGURIDAD

## Alcance a investigar (por orion-spec / orion-baseline / orion-architect — NO resuelto acá)
1. **Confirmar el alcance exacto del bypass.** ¿Es solo `/eliminar [id]`, o hay otros comandos
   slash de `channels/telegram_bot.py` (`/tareas`, `/nueva`, `/completar`, y cualquier otro no
   listado todavía) con el mismo patrón de "llamar directo a `task_manager`/otro módulo sensible
   sin pasar por `execute_tool()`/`security_manager.require_confirmation()`"? `/completar` está
   descartado (ver aclaración arriba), pero revisar **todos** los comandos slash del archivo, no
   asumir que el problema es solo de tareas — podría haber un comando que toque archivos, apagado,
   u otra acción Amarilla/Roja con el mismo patrón.
2. **Confirmar si Discord tiene el mismo patrón.** Revisar `channels/discord_bot.py` por
   comandos estructurados (no solo el camino de texto libre vía `GlassGateway.process()`, que ya
   se confirmó correcto en REQ-017) que puedan tener el mismo problema.
3. **Diseñar el fix mínimo.** Lo más probable es que `/eliminar [id]` deba pasar por el mismo
   mecanismo de confirmación que ya usa el resto del sistema para `delete_task` (Amarillo) — en
   Telegram eso probablemente implica un flujo de confirmación conversacional (¿mensaje "¿confirmás?
   sí/no"?). Revisar si ya existe un patrón de confirmación conversacional en Telegram para otras
   acciones amarillas, o si hay que diseñarlo de cero.
4. **Alcance quirúrgico obligatorio.** Este REQ toca el gate fail-closed de REQ-005
   (`core/security_manager.py`) — el fix debe ser mínimo, sin tocar la clasificación de riesgo
   existente (`RiskLevel` de `delete_task`, `complete_task`, etc.) ni el resto del pipeline de
   `resolve()` documentado en REQ-017.

## Decisiones tomadas
2026-08-20 | orion-coordinador | REQ creado — categoría=SEGURIDAD | Categoría ya identificada por el humano en el origen del REQ (hallazgo documentado en SPEC-017.md); confirmado por palabras clave propias de la regla de detección: "seguridad", "confirmación", "verde/amarillo/rojo", "permiso" — no hay categoría más apropiada (no es CORE: no toca dispatcher/router, es específicamente un bypass de gate de seguridad en un canal BOT).
2026-08-20 | orion-coordinador | orion-security es obligatorio en este REQ, no opcional | A diferencia de REQ-016/REQ-017, este REQ es exactamente el caso para el que existe orion-security: bypass real de un gate ya existente (fail-closed de REQ-005), no una feature nueva que solo "toca" seguridad tangencialmente.
2026-08-20 | orion-spec | SPEC-018 aprobada | Aprobado por Johan (vía coordinador) **tal cual, sin ajustes**, incluidos los 6 puntos "Asumidos" (no se agrega `task_delete`; segunda confirmación pendiente se rechaza de inmediato — CA-09; correlación por `user_id` sin distinguir grupal/privado; timeout de 120s; mensajes de voz no cuentan como respuesta; nombre/ubicación del adaptador y mecanismo del puente async→sync quedan a definición de `orion-architect`). Los 6 asumidos quedan confirmados como decisión, ya no como pendientes — `orion-baseline`/`orion-architect` no deben repreguntarlos.
2026-08-20 | orion-spec | Tipo de cambio: SEGURIDAD | Identificado por `orion-coordinador` en la creación del REQ, confirmado sin cambios durante la SPEC.
2026-08-20 | orion-baseline | 4 archivos/módulos previstos a modificar + 1 archivo nuevo del adaptador | Ver `origen/baseline-018.md` — código real de `cmd_eliminar()`/`cmd_completar()`/`cmd_nueva()`/`cmd_tareas()`/`handle_text()` transcrito línea por línea, `CHANNEL_ALLOWED_LEVELS`/`require_confirmation()`/`_register_default_actions()` de `security_manager.py` confirmados, `core/confirmation.py` confirmado sin cambios de contrato, cero adaptadores TELEGRAM/DISCORD confirmado por grep exhaustivo.
2026-08-20 | orion-baseline | Corrección a SPEC-018.md "Módulos afectados": el registro del adaptador NO va en `main.py` | `main.py` nunca importa ni inicia `channels/telegram_bot.py` — son dos procesos standalone distintos (confirmado por grep: único rastro de "telegram" en `main.py` es un comentario). El registro real debe ir dentro de `channels/telegram_bot.py::run_telegram_bot()`, antes de `app.run_polling()`. Señalado para que `orion-architect` lo corrija en la propuesta.
2026-08-20 | orion-baseline | CA-10 tiene fricción real con `agents/tool_registry.py` tal como existe hoy | `_task_create_invoke` no replica el fallback de `cmd_nueva()` (crear tarea simple si `create_from_natural()` falla); `_task_complete_invoke` espera `text` libre con su propio regex + auto-completar/pedir aclaración, no un `task_id` explícito como `cmd_completar()` hoy, y devuelve un mensaje de error distinto para "no encontrada". `task_list` sí es equivalente limpio. Requiere decisión explícita de `orion-architect`, no cableado directo — ver detalle completo en `origen/baseline-018.md`.
2026-08-20 | orion-architect | Corrección de SPEC aplicada: adaptador se registra en `channels/telegram_bot.py::run_telegram_bot()` (vía callback `post_init` de la `Application`, no una línea suelta), no en `main.py` | Confirma y ejecuta la corrección que `orion-baseline` había señalado. El callback `post_init` es necesario (no solo "correcto") porque es el primer punto del ciclo de vida de la `Application` donde existe un event loop de `asyncio` ya corriendo del que capturar la referencia que el adaptador necesita para su puente async→sync — capturarlo antes, en el cuerpo síncrono de `run_telegram_bot()`, no es posible. Ver `arquitectura-018.md` §4.3.
2026-08-20 | orion-architect | CA-02: mecanismo de excepción implementado como `CHANNEL_ACTION_EXCEPTIONS: set[tuple[ChannelType, str]]` en `core/security_manager.py`, evaluado dentro de `is_action_allowed()` como condición OR adicional a `CHANNEL_ALLOWED_LEVELS` (nunca su reemplazo) | Cambio estrictamente aditivo/monótono — para cualquier par no listado en el set, el comportamiento es idéntico al actual. Única entrada: `(ChannelType.TELEGRAM, "delete_task")`. Grep confirmó que el único otro caller de `is_action_allowed()` (`core/proactive_engine.py:90`, acción GREEN, canal DESKTOP) no se ve afectado. Ver `arquitectura-018.md` §4.1.
2026-08-20 | orion-architect | CA-08: puente async→sync implementado con `asyncio.to_thread()` (en `cmd_eliminar()`) + `threading.Event` (en el adaptador) + `asyncio.run_coroutine_threadsafe()` (para que el adaptador, corriendo en el hilo worker, pueda enviar el mensaje de Telegram real de vuelta en el event loop principal) | Evita `asyncio.Event`, que exigiría que el `confirm()` del adaptador corriera dentro de una corutina con acceso directo al loop — pero `confirm()` debe seguir siendo 100% síncrono por contrato de `core/confirmation.py` (CA-11 de REQ-006, sin cambios). La correlación usuario↔hilo-worker se resuelve con un `contextvars.ContextVar`, propagado automáticamente por `asyncio.to_thread()` al hilo nuevo (documentado en la librería estándar) — cada invocación concurrente de distintos usuarios tiene su propia copia de contexto aislada. Ver `arquitectura-018.md` §5.
2026-08-20 | orion-architect | CA-05: intercepción de la próxima respuesta implementada como handler nuevo `_intercept_confirmacion_pendiente`, registrado en `group=-1` (mayor prioridad que el `group=0` donde viven todos los `CommandHandler`/`handle_text` existentes), con filtro `filters.TEXT` sin excluir comandos, cortando la propagación con `ApplicationHandlerStop` cuando consume un mensaje | Necesario para que se cumpla literalmente el caso borde de `SPEC-018.md` ("un comando nuevo como `/tareas` mientras hay confirmación pendiente se consume como respuesta, no se ejecuta") — `handle_text()` sola no alcanza, porque su filtro (`filters.TEXT & ~filters.COMMAND`) excluye deliberadamente los comandos slash, que tienen su propio `CommandHandler` en `group=0` y nunca llegarían a `handle_text()`. Ver `arquitectura-018.md` §6.3.
2026-08-20 | orion-architect | CA-10: `/tareas` se conecta a `execute_tool("task_list", ...)` tal cual pide la SPEC; `/completar` y `/nueva` NO se conectan a `execute_tool()` — mantienen su llamada directa a `task_manager` sin cambios, precedida por `security_manager.require_confirmation("task_complete"/"task_create", ChannelType.TELEGRAM, ...)` solo para auditar (GREEN, sin efecto en el resultado) | Resuelve la fricción que señaló `orion-baseline` sin tocar `agents/tool_registry.py` (evita el riesgo de regresión sobre el camino de lenguaje natural que usa esas mismas funciones) y sin dejar `/completar`/`/nueva` sin auditoría (lo que Johan pidió explícitamente). Se aparta de la letra literal de CA-10 ("invocan `execute_tool()`") pero cumple su objetivo real. **Necesita aprobación explícita de Johan** — ver `arquitectura-018.md` §3 y §14.
2026-08-20 | orion-architect | Recomendación: `orion-security` corre como paso dedicado antes de `orion-dev` | Aplicando el mismo criterio usado en `arquitectura-016.md` §11 ("¿el REQ introduce una superficie o un patrón de riesgo todavía no evaluado?", no "¿toca algo destructivo?"), mi análisis propio coincide con la decisión ya registrada por `orion-coordinador` en este mismo contexto — pero por razón distinta a la simple categoría SEGURIDAD del REQ: CA-02 y CA-04/CA-09 introducen dos piezas de **mecanismo nuevo** (primera excepción granular canal+acción del sistema; primer adaptador de confirmación async/multiusuario), no contenido nuevo sobre mecanismo ya auditado (que sí era el caso de REQ-016). Confirmado además que `SPEC-018.md` NO fija `orion-security` como CA obligatorio — las 14 CA no lo mencionan; la obligatoriedad viene de la decisión de `orion-coordinador`, no del contrato de la SPEC. Ver `arquitectura-018.md` §12.
2026-08-20 | orion-architect | Johan aprobó `arquitectura-018.md` (vía coordinador), confirmando explícitamente los 2 puntos abiertos sin ajustes: (1) CA-10 — SÍ, `/completar`/`/nueva` quedan con su lógica actual, auditados sin forzar `execute_tool()`; (2) `orion-security` — SÍ, corre como paso dedicado antes de `orion-dev` | Aprobación humana explícita recibida, DoD de `orion-architect` completo. `arquitectura-018.md` marcada ✅ APROBADA (encabezado y §13/§14 actualizados con la resolución). CSV actualizado vía `update-tracker.mjs` en 3 pasos (el script no permite saltar estados intermedios: `SPEC_APROBADO → EN_BASELINE → EN_ARQUITECTURA → ARQUITECTURA_APROBADA`, mismo patrón que usó `orion-spec` para `NUEVO → EN_SPEC → SPEC_APROBADO`), más `Aprobacion_Arquitectura=APROBADO` en el último paso. `Rama` queda sin asignar — Johan no la especificó en esta aprobación y `.claude/rules/git.md` exige preguntar antes de asumir una; no bloquea el handoff.
2026-08-20 | orion-architect | `orion-security` auditó `arquitectura-018.md` (`pruebas/security-audit-018.md`) y devolvió ❌ REQUIERE CAMBIOS: Hallazgo A bloqueante (`Application.builder()` sin `.concurrent_updates(True)` — PTB despacha updates uno a la vez por defecto, `SimpleUpdateProcessor(max_concurrent_updates=1)`, así que el puente async→sync de §5.1 mueve el bloqueo del hilo del SO a un hilo worker pero NO mueve el bloqueo del dispatcher de updates de PTB; mientras `cmd_eliminar()` espera hasta 120s, el bot completo queda sordo para todos los usuarios — DoS trivial y no privilegiado, verificado por `orion-security` directo contra el código fuente instalado de `python-telegram-bot==20.7`), más 2 hallazgos no bloqueantes (B: `confirm()` no limpia `_pending` si `asyncio.run_coroutine_threadsafe()` lanza antes de programar el envío, entrada huérfana permanente; C: el test de CA-03 de §11 lista las 19 YELLOW a mano en vez de derivarlas del registro real de `security_manager`, se desincroniza en silencio ante una YELLOW nueva) | Aplicado el fix de Hallazgo A en `arquitectura-018.md` §15 (addendum, sin reabrir §1-§14): `.concurrent_updates(True)` agregado al builder de `run_telegram_bot()`, más un test de integración nuevo que construye una `Application` real y verifica `app.concurrent_updates > 1` (el test aislado de CA-08 original no cubría este punto porque nunca instanciaba una `Application` real). Hallazgos B y C quedan documentados en §15.2/§15.3 para que `orion-dev` los resuelva directo, sin volver a pasar por `orion-architect` (mismo criterio que los Hallazgos B/C de `security-audit-015.md`/`security-audit-019.md`). Agregada además una nota propia (no un hallazgo nuevo, señalada para que `orion-security` la evalúe en el re-chequeo): con concurrencia real habilitada, existe una ventana angosta de correlación si el mismo usuario manda dos mensajes casi simultáneos (`/eliminar` seguido de inmediato por otra cosa, sin el tiempo real que toma ver el prompt y responder) — distinto del caso borde ya cubierto por la SPEC (que es sobre una respuesta posterior al prompt, no simultánea). No se volvió a consultar a Johan — instrucción explícita del coordinador: es corrección técnica de seguridad, no decisión de alcance. CSV **no tocado** — el estado sigue en `ARQUITECTURA_APROBADA`, el addendum no es una nueva aprobación de arquitectura, es la resolución de una auditoría dentro del mismo ciclo. Aviso de "listo para re-chequeo" entregado al coordinador; próximo paso es que `orion-security` vuelva a auditar `arquitectura-018.md` §15.

## Investigación (orion-spec, 2026-08-20) — antes de redactar SPEC-018

### Tabla completa de comandos slash — `channels/telegram_bot.py`
| Comando | Línea | Qué llama | Nivel de riesgo (`security_manager`) | ¿Pasa por el gate hoy? |
|---|---|---|---|---|
| `/start` | 277 | Texto estático | No aplica | No aplica — sin acción sensible |
| `/ayuda`, `/help` | 299 | Texto estático | No aplica | No aplica |
| `/voz` | 330 | `context.user_data["voice_mode"]=True` (flag de sesión en memoria) | No clasificada | No aplica — no sensible |
| `/texto` | 342 | ídem, `False` | No clasificada | No aplica |
| `/memoria` | 349 | `session.get_memory_summary()` → `ai/memory_manager.py` (solo lectura) | No clasificada (lectura) | No aplica — sin escritura/borrado |
| `/limpiar` | 365 | `session.clear_history()` — vacía una lista en memoria de proceso; **no toca ninguna DB** (verificado en `ai/user_manager.py:195-197`) | No clasificada | No aplica — no persiste, no hay DB de por medio |
| `/estado` | 376 | Lecturas de estado (edge_tts, ffmpeg, `registry.active_count()`) | No clasificada (lectura) | No aplica |
| `/skills` | 403 | `skill_manager.skills` (lectura) | No clasificada (lectura) | No aplica |
| `/tareas` | 416 | `task_manager.get_task_summary()` directo — bypassa el wrapper `task_list` de `agents/tool_registry.py` | 🟢 VERDE (equivalente `task_list`, registrado GREEN) | Bypassa `execute_tool()`, pero sin impacto de seguridad — GREEN no exige confirmación de todas formas. Solo pierde auditoría en `audit.db`. |
| `/nueva [texto]` | 424 | `task_manager.create_from_natural()` / `create_task()` directo — bypassa el wrapper `task_create` | 🟢 VERDE (equivalente `task_create`, GREEN) | Igual que `/tareas` — bypass de auditoría, no de seguridad. |
| `/completar [id]` | 468 | `task_manager.complete_task()` directo — bypassa el wrapper `task_complete` | 🟢 VERDE (equivalente `task_complete`, GREEN) | Ya documentado en SPEC-017 — bypass de auditoría, no de seguridad (`complete_task` es GREEN). |
| `/eliminar [id]` | 500 | `task_manager.delete_task()` directo — **no existe ningún wrapper `task_delete` registrado en `agents/tool_registry.py` ni en ningún otro lugar del sistema** | 🟡 **AMARILLO** (acción `"delete_task"`, `core/security_manager.py:316`) | **NO pasa por el gate — es el único bypass con impacto real de seguridad de todo el archivo.** |

Conclusión: dentro de Telegram, **solo `/eliminar` es un bypass de seguridad real**. `/tareas`, `/nueva`
y `/completar` comparten el mismo patrón estructural (llaman `task_manager` directo en vez de
`execute_tool()`), pero como sus acciones equivalentes ya son 🟢 Verde, el bypass ahí es de
**auditoría** (no quedan en `audit.db`), no de autorización. Ningún otro comando del archivo
(control del PC, apagado, archivos) se ejecuta desde un comando slash — esas acciones solo llegan
por texto libre vía `handle_text()` → `GlassGateway().process()` → `resolve()`, que sí gatea
correctamente (confirmado por el comentario de línea 546-554 sobre `SYS_POWER_OFF`).

### `channels/discord_bot.py` — sin el mismo patrón
Discord expone solo 3 comandos slash: `/noddoo` (línea 163, delega a `_process_message()` →
`GlassGateway().process()` → camino gateado, igual que la mención `@bot`), `/limpiar` (línea 180,
solo llama `ai/claude_brain.py::clear_conversation()`, no toca `task_manager` ni ningún módulo
clasificado) y `/ayuda` (línea 192, texto estático). **Discord no tiene comandos de tareas en
absoluto** (`/tareas`, `/nueva`, `/completar`, `/eliminar` no existen ahí) — no hay bypass
equivalente. Hallazgo aparte, no relacionado con seguridad: `slash_limpiar` (líneas 182-186) tiene
un `except Exception: pass` silencioso al llamar `clear_conversation()`, lo que viola
`.claude/rules/python-style.md` — se documenta acá para no perderlo, pero no es parte del alcance
de este REQ salvo que el humano decida incluirlo.

### Mecanismo de confirmación conversacional — NO existe para Telegram/Discord, y es una decisión ya tomada, no un vacío
`core/confirmation.py` define el registro de adaptadores por canal. Grep de
`register_confirmation_adapter(...)` en todo el repo: el único adaptador real registrado es
`ChannelType.DESKTOP` (`main.py:59` vía `_desktop_confirm`, y `ui/webview/main_window.py:126` vía
`WebViewConfirmationAdapter`). **Cero adaptadores para TELEGRAM o DISCORD.**

Pero hay algo más importante que la ausencia de adaptador: `CHANNEL_ALLOWED_LEVELS` en
`core/security_manager.py:54-61` excluye 🟡 Amarillo para Telegram/Discord/Voice/API por completo
(`[RiskLevel.GREEN]` únicamente) — es una **política de canal**, evaluada en
`require_confirmation()` (línea 258, `is_action_allowed()`) **antes** de siquiera buscar un
adaptador. Esto significa que aunque hoy se registrara un adaptador de confirmación para Telegram,
`delete_task` seguiría denegándose igual, porque el nivel YELLOW nunca llega a ser "permitido" para
ese canal.

Y esto **no es un vacío de diseño**: es una decisión humana explícita ya tomada en REQ-006, citada
textualmente en `workspace/adjuntos/REQ-006/REQ-006-context.md:319`:
> `CHANNEL_ALLOWED_LEVELS` NO se modifica; Telegram/Discord/Voice/API siguen sin adaptador de
> confirmación real, por lo tanto YELLOW sigue bloqueado ahí exactamente igual que hoy — Decisión
> humana explícita en SPEC-006 (**paridad = capacidad, no autoridad**). CA-10 desacopla el
> mecanismo de pedir confirmación, no relaja la política de quién puede confirmar qué.

Confirmado también en `workspace/adjuntos/REQ-006/pruebas/qa-audit-006.md:66-71`: "Ningún canal
ganó capacidad YELLOW/RED nueva. Telegram/Discord/Voice siguen limitados a `[GREEN]`... su rama
YELLOW cae en `bloqueada_sin_adaptador` (fail-closed)". Es comportamiento probado con tests, no
accidental.

**Consecuencia directa para el fix de REQ-018:** conectar `cmd_eliminar` a
`security_manager.require_confirmation("delete_task", ChannelType.TELEGRAM, ...)` tal cual, sin
ningún otro cambio, haría que `/eliminar` **siempre se deniegue** — quedaría permanentemente
inutilizado por Telegram (mismo destino que "apaga el pc" hoy), no "arreglado" en el sentido de
"ahora pide confirmación y funciona". Para que `/eliminar` vuelva a poder borrar algo por Telegram
haría falta (a) un adaptador de confirmación conversacional nuevo para `ChannelType.TELEGRAM`, y
(b) ampliar `CHANNEL_ALLOWED_LEVELS[ChannelType.TELEGRAM]` para incluir YELLOW — lo segundo
revierte/matiza la decisión explícita de REQ-006, y como `CHANNEL_ALLOWED_LEVELS` no tiene
granularidad por acción hoy (es una lista por canal, no por acción×canal), técnicamente abriría la
puerta a **todas** las acciones Amarillas en Telegram (`shutdown`, `close_app`, `delete_file`,
`delete_skill`, etc.), no solo a `delete_task`, salvo que también se diseñe un mecanismo de
excepción por acción — trabajo adicional no quirúrgico.

### Corrección a la "Aclaración importante" del resumen ejecutivo (arriba)
La afirmación original de que "los comandos equivalentes en lenguaje natural (vía `resolve()` →
`_try_task_tool` → `execute_tool()`) sí pasan correctamente por el gate" **no aplica a borrar
tareas**: no existe ningún wrapper `task_delete` en `agents/tool_registry.py`, y
`core/resolution.py::_try_task_tool()` (líneas 144-175) solo reconoce triggers de crear
(`_TASK_CREATE_TRIGGERS`), listar (`_TASK_LIST_TRIGGERS`) y completar (`_is_task_complete_phrase`)
— no hay ningún trigger de borrado. **Hoy, en todo el sistema, las únicas dos vías para borrar una
tarea son `/eliminar` en Telegram (bug, sin gate) y `ui/webview/bridge.py::request_delete_task()`
en el WebView de escritorio (correctamente gateado, líneas 363-380).** No existe ninguna vía de
lenguaje natural equivalente contra la cual comparar — la afirmación original era una suposición
sin verificar, no un hecho confirmado en código.

### Discrepancia (no introducida por este REQ) con `.claude/rules/security-levels.md`
La regla de reglas del proyecto dice, en su sección "Por canal": *"Telegram/Discord: Amarillo
siempre requiere confirmación explícita, Rojo bloqueado"*. El código real (`CHANNEL_ALLOWED_LEVELS`)
implementa lo contrario y de forma deliberada desde REQ-006: Telegram/Discord son GREEN-only, igual
que Voz. Se documenta para que quede registrado — no se resuelve en este REQ salvo que el humano lo
pida explícitamente.

## Respuestas de Johan a las preguntas de clarificación (2026-08-20, vía coordinador)
1. **Dirección del fix → opción (b): diseñar confirmación conversacional para Telegram.** No el
   bloqueo mínimo. Incluye resolver explícitamente cómo evitar que esto abra TODAS las acciones
   Amarillas en Telegram de golpe — se necesita una excepción por acción, no ampliar
   `CHANNEL_ALLOWED_LEVELS[TELEGRAM]` en bloque. Johan reconoce explícitamente la tensión con la
   decisión de REQ-006 ("capacidad, no autoridad") y la acepta como una excepción puntual y
   deliberada para esta acción — con el mismo criterio de "piso de seguridad": se habilita
   Amarillo solo para `delete_task`, no se abre la puerta completa.
2. **Auditoría extra → SÍ.** Conectar también `/completar`, `/nueva` y `/tareas` a
   `execute_tool()` por trazabilidad, aunque no cambien de comportamiento (ya son Verde).
3. **Bug de `except Exception: pass` en `discord_bot.py::slash_limpiar`** → queda anotado como
   hallazgo aparte para un REQ futuro, fuera de esta SPEC.
4. **Corrección de contexto** (no existe vía de lenguaje natural para borrar tareas) →
   confirmada, ya corregida arriba en "Aclaración importante" y en la sección de investigación.
5. **Restricción no negociable de siempre** (no tocar clasificación de riesgo existente,
   `delete_task` sigue Amarillo, no tocar `RESOLVERS`/`resolve()`) → sigue aplicando.

Punto no respondido explícitamente por Johan: si se debía agregar un tool `task_delete` a
`agents/tool_registry.py` para habilitar borrado por lenguaje natural. Se asumió que NO (fuera de
alcance — el REQ cierra un bypass existente, no agrega una capacidad nueva) y quedó registrado
como ASUMIDO en `spec/SPEC-018.md`, pendiente de confirmación explícita antes de implementar.

## Descartado (y por qué)
- Fix mínimo/bloqueo total de `/eliminar` en Telegram (opción "a" presentada a Johan) — descartado
  explícitamente por decisión de Johan a favor de diseñar confirmación conversacional real
  (opción "b"). Ver "Respuestas de Johan" arriba.
- 2026-08-20 | orion-architect | CA-10: adaptar `agents/tool_registry.py` (`_task_create_invoke`/
  `_task_complete_invoke`) para que acepten un modo "ID/texto ya parseado" y así poder conectar
  `/completar`/`/nueva` a `execute_tool()` tal cual pide la letra literal de CA-10 | Descartada:
  esas mismas funciones sirven también al camino de lenguaje natural
  (`core/resolution.py::_try_task_tool()`) — agregarles ramas nuevas, aunque gateadas por
  parámetro, aumenta la superficie de un código ya cubierto por tests de REQ-006/REQ-017 y usado
  por un pipeline que CA-12 exige dejar intacto. Contradice el mandato de "alcance quirúrgico
  obligatorio" del propio REQ. Ver `arquitectura-018.md` §3.
- 2026-08-20 | orion-architect | CA-10: dejar `/completar` y `/nueva` sin ninguna auditoría nueva
  (opción "b" que ofreció `orion-baseline`) | Descartada como decisión final (no se implementa):
  contradice el pedido explícito de Johan ("Auditoría extra → SÍ... los tres"). En su lugar se
  eligió auditar vía `security_manager.require_confirmation()` llamado directo, sin pasar por
  `execute_tool()` — ver "Decisiones tomadas" y `arquitectura-018.md` §3.

## Asumidos — CONFIRMADOS por Johan al aprobar SPEC-018 (2026-08-20)
Los 6 puntos de abajo ya NO están pendientes — Johan aprobó la SPEC tal cual, incluidos
explícitamente los 6 asumidos, sin pedir ningún ajuste. Quedan como decisión tomada, vinculante
para `orion-baseline`/`orion-architect`/`orion-dev` — no se repreguntan salvo que aparezca
información nueva durante baseline/arquitectura que los contradiga (en cuyo caso se señala al
humano, no se asume una resolución distinta en silencio). Ver sección "Asumidos" completa de
`spec/SPEC-018.md` — resumen:
- No se agrega tool `task_delete` a `agents/tool_registry.py` (sin vía de borrado por lenguaje
  natural en este REQ).
- Ante una segunda confirmación pendiente para el mismo usuario, se propone **rechazar la
  segunda de inmediato** en vez de apilarla o cancelar la primera silenciosamente (CA-09).
- Correlación de la respuesta sí/no por `user_id` únicamente, sin distinguir chat privado de
  grupal.
- Timeout de 120s (igual a `WebViewConfirmationAdapter` de REQ-015) también tiene sentido para
  Telegram.
- Mensajes de voz mientras hay una confirmación pendiente no cuentan como respuesta válida.
- Nombre/ubicación del adaptador nuevo y mecanismo concreto del puente async→sync quedan a
  definición de `orion-architect` — la SPEC fija comportamiento observable, no implementación.

## Riesgos activos
- Bypass real y activo del gate fail-closed de REQ-005 para `/eliminar [id]` en Telegram — una
  tarea puede borrarse sin confirmación humana explícita, violando `.claude/rules/security-levels.md`.
- Confirmado: no hay bypass adicional con impacto de seguridad en el resto de comandos slash de
  Telegram (solo bypass de auditoría en `/tareas`/`/nueva`/`/completar`, acciones GREEN) ni en
  Discord (sin comandos de tareas). Alcance del bypass real cerrado y acotado a `/eliminar`.
- Resuelto (era riesgo, ahora es decisión tomada): Johan eligió explícitamente diseñar
  confirmación conversacional real (opción "b") en vez del bloqueo mínimo, con pleno conocimiento
  de que esto matiza la decisión "capacidad, no autoridad" de REQ-006 — ver "Respuestas de Johan".
- Riesgo nuevo, activo mientras `SPEC-018.md` no esté aprobada: el mecanismo de excepción por
  canal+acción (CA-02) y el puente async→sync para Telegram (CA-08) son las dos piezas técnicas
  más delicadas de esta SPEC — si `orion-architect` no las resuelve con cuidado, el riesgo es (a)
  abrir sin querer otras acciones Amarillas en Telegram, o (b) bloquear el loop de `asyncio` de
  `python-telegram-bot` para todos los usuarios mientras una confirmación está pendiente para uno
  solo. Ambos quedaron como criterios de aceptación explícitos y testeables (CA-02/CA-03, CA-08)
  precisamente por este riesgo.
- Nuevo (orion-baseline, 2026-08-20): SPEC-018.md "Módulos afectados" indica que `main.py`
  registra el adaptador nuevo — esto es incorrecto en el código real, `main.py` no inicia el
  proceso del bot de Telegram. Si `orion-architect`/`orion-dev` implementan tal cual dice la
  SPEC sin corregirlo, el adaptador quedaría registrado en un proceso que nunca corre
  `cmd_eliminar()`, y `/eliminar` seguiría cayendo en `"bloqueada_sin_adaptador"` en producción
  pese a que el código "parezca" completo y los tests unitarios (que no levantan el proceso real)
  podrían pasar igual. Mitigación: registrar dentro de `channels/telegram_bot.py::
  run_telegram_bot()`. Ver `origen/baseline-018.md`.
- Nuevo (orion-baseline, 2026-08-20): riesgo de que `orion-architect`/`orion-dev` interpreten
  CA-10 ("comportamiento observable idéntico") de forma demasiado literal y rompan el fallback de
  `/nueva` (tarea simple si falla el parseo natural) o cambien silenciosamente el mensaje de error
  y las ramas de comportamiento de `/completar` al conectarlos a `execute_tool()`. Sin
  clasificación de riesgo de seguridad (ambos siguen GREEN), pero sí es una regresión funcional
  real si no se diseña con cuidado. Ver detalle en `origen/baseline-018.md`, sección
  "Discrepancias nuevas encontradas".
- Cero cobertura de test previa sobre `channels/telegram_bot.py` (no existe ningún
  `tests/test_telegram*.py`) — no hay una red de regresión existente que proteger; toda la
  cobertura de CA-01 a CA-14 depende de tests escritos desde cero por `orion-dev`/`orion-tester`.

## Preguntas de clarificación — RESUELTAS y SPEC APROBADA (cierre, 2026-08-20)
Las 5 preguntas que había dejado pendientes esta sesión de `orion-spec` fueron respondidas por
Johan el mismo día (ver "Respuestas de Johan" arriba). Con esas respuestas se redactó
`spec/SPEC-018.md` (14 criterios de aceptación CA-01 a CA-14, casos borde, 6 asumidos explícitos)
y Johan la **aprobó tal cual, sin ajustes, incluidos los 6 asumidos**. SPEC-018.md queda
`✅ COMPLETADO`. CSV actualizado vía `update-tracker.mjs`: `Estado=SPEC_APROBADO`,
`Tipo_Cambio=SEGURIDAD`, `Aprobacion_SPEC=APROBADO` (transición hecha en dos pasos,
`NUEVO → EN_SPEC → SPEC_APROBADO`, porque el script no permite saltar `EN_SPEC`). Handoff emitido
a `orion-baseline`.

## Log de transiciones
2026-08-20 | — → NUEVO | orion-coordinador | REQ creado a partir de hallazgo de orion-spec durante REQ-017
2026-08-20 | NUEVO → NUEVO (sin cambio de estado) | orion-spec | Investigación exhaustiva completada (tabla de comandos Telegram/Discord, mecanismo de confirmación conversacional confirmado inexistente y por qué, corrección de la "Aclaración importante"). SPEC-018.md NO redactada todavía — Johan no estaba en vivo en esta sesión. Preguntas de clarificación quedan pendientes de respuesta antes de redactar la SPEC. CSV no tocado (Estado tracker sigue NUEVO).
2026-08-20 | NUEVO → NUEVO (sin cambio de estado) | orion-spec | Johan respondió las 5 preguntas de clarificación (eligió opción "b": confirmación conversacional real para Telegram, con excepción quirúrgica por acción). `spec/SPEC-018.md` redactada con 14 criterios de aceptación testeables (CA-01 a CA-14), casos borde y asumidos explícitos. Estado de la SPEC: ⏸️ ESPERANDO VALIDACIÓN. CSV NO tocado — pendiente de aprobación humana explícita antes de pasar a SPEC_APROBADO.
2026-08-20 | NUEVO → EN_SPEC → SPEC_APROBADO | orion-spec | Johan aprobó SPEC-018.md tal cual, sin ajustes, incluidos los 6 puntos "Asumidos". SPEC-018.md marcada ✅ COMPLETADO. CSV actualizado vía `update-tracker.mjs --id REQ-018 --Estado SPEC_APROBADO --Aprobacion_SPEC APROBADO --Tipo_Cambio SEGURIDAD` (dos llamadas, pasando por EN_SPEC). Handoff emitido a `orion-baseline`.
2026-08-20 | SPEC_APROBADO → SPEC_APROBADO (sin cambio de estado) | orion-baseline | Baseline exhaustivo completado sobre código real (no se confió en el resumen de orion-spec sin re-verificar). `origen/baseline-018.md` redactado. CSV **no tocado** — instrucción explícita del handoff recibido ("tu DoD no incluye transición de Estado, no lo toques"); la transición de Estado queda para el agente que corresponda según el pipeline. Handoff emitido a `orion-architect`.
2026-08-20 | SPEC_APROBADO → SPEC_APROBADO (sin cambio de estado) | orion-architect | Propuesta técnica completa redactada en `propuestas/arquitectura-018.md` (14 secciones: cobertura de los 14 CA, decisión justificada de CA-10, mecanismo de excepción CA-02, adaptador nuevo completo con firmas exactas, flujo de datos, riesgos y mitigación, pruebas sugeridas, recomendación sobre `orion-security`). CSV **no tocado** — DoD de `orion-architect` exige aprobación humana explícita antes de transicionar a ARQUITECTURA_APROBADA (Paso 5 del proceso), y esa aprobación todavía no llegó. Handoff a `orion-dev` (o a `orion-security` si Johan confirma la recomendación de §12) queda pendiente de esa aprobación — no se emite todavía.
2026-08-20 | SPEC_APROBADO → EN_BASELINE → EN_ARQUITECTURA → ARQUITECTURA_APROBADA (3 pasos, el script no permite saltar estados intermedios) | orion-architect | Johan aprobó `arquitectura-018.md` (vía coordinador), confirmando sin ajustes los 2 puntos abiertos (CA-10 y `orion-security`, ver "Decisiones tomadas"). `arquitectura-018.md` marcada ✅ APROBADA. CSV actualizado: `Estado=ARQUITECTURA_APROBADA`, `Aprobacion_Arquitectura=APROBADO`. `Rama` sin asignar (Johan no la especificó, no se asume). **Handoff emitido a `orion-security`** (paso dedicado confirmado por Johan) — no a `orion-dev` directamente.
2026-08-20 | ARQUITECTURA_APROBADA → ARQUITECTURA_APROBADA (sin cambio de estado) | orion-architect | `orion-security` devolvió ❌ REQUIERE CAMBIOS sobre `arquitectura-018.md` (`pruebas/security-audit-018.md`) — 1 hallazgo bloqueante (A, DoS trivial por falta de `.concurrent_updates(True)`), 2 no bloqueantes (B, C). Aplicado el fix de A en `arquitectura-018.md` §15 (addendum corto, sin reabrir §1-§14): línea `.concurrent_updates(True)` + test de integración nuevo. B y C documentados en §15.2/§15.3 para que `orion-dev` los resuelva directo. CSV **no tocado** — el addendum no cambia el estado del tracker, solo resuelve una auditoría dentro del mismo ciclo de `ARQUITECTURA_APROBADA`. No se consultó a Johan (instrucción explícita del coordinador: corrección técnica de seguridad, no decisión de alcance). **Aviso de "listo para re-chequeo" entregado al coordinador — el flujo espera que `orion-security` vuelva a auditar antes de emitir el handoff a `orion-dev`.**
2026-08-20 | ARQUITECTURA_APROBADA → ARQUITECTURA_APROBADA (sin cambio de estado) | orion-security | Re-chequeo de `arquitectura-018.md` §15 completado — `pruebas/security-audit-018.md` sección "Re-chequeo" — **veredicto ✅ APROBADO**. Hallazgo A confirmado resuelto con evidencia experimental directa contra `python-telegram-bot==20.7` instalado (no solo lectura del addendum): reproducido el bug sin el fix (`app.concurrent_updates == 1`), confirmado el fix (`== 256` con `.concurrent_updates(True)`), y confirmado que el test de integración nuevo distingue correctamente ambos casos (falla sin el fix, pasa con él) — construye una `Application` real, cerrando el gap de cobertura del test original que solo probaba el adaptador aislado. Encontrado 1 hallazgo nuevo no bloqueante (E) a partir de la nota propia del arquitecto en §15.1: ventana de correlación entre mensajes casi simultáneos del mismo usuario — evaluado sin compromiso de CA-06/CA-09 (no puede producir confirmación afirmativa no intencionada, no puede duplicar confirmaciones pendientes, sistema permanece fail-closed), impacto acotado a UX/correlación alcanzable solo por cliente automatizado en ráfaga. Corrección recomendada y documentada para `orion-dev` (reserva síncrona de `_pending` antes del `await`), mismo tratamiento que B y C — no requiere otra vuelta a `orion-architect`. CSV **no tocado** — el re-chequeo no cambia el estado del tracker (sigue `ARQUITECTURA_APROBADA`); la transición a `EN_DESARROLLO` le corresponde a `orion-dev`. **Handoff emitido a `orion-dev`** con `security-audit-018.md` (auditoría original + re-chequeo) como entrada obligatoria — 3 correcciones no bloqueantes pendientes de implementar en esta etapa (Hallazgos B, C, E).

2026-08-20 | orion-security | Auditoría completada — `pruebas/security-audit-018.md` — **veredicto ❌ REQUIERE CAMBIOS**, 1 hallazgo bloqueante + 2 no bloqueantes de corrección obligatoria | **Hallazgo A (bloqueante):** `run_telegram_bot()` construye `Application.builder()` sin `.concurrent_updates(...)` — verificado directamente contra el código fuente instalado de `python-telegram-bot==20.7` (`telegram/ext/_applicationbuilder.py:214-215`, default `SimpleUpdateProcessor(max_concurrent_updates=1)`; `telegram/ext/_application.py:1145-1170`, `_update_fetcher()` es una única Task que `await`s cada update completo antes de tomar el siguiente cuando `max_concurrent_updates == 1`). Consecuencia: mientras `cmd_eliminar()` de un usuario espera hasta 120s dentro de `await asyncio.to_thread(require_confirmation, ...)`, el dispatcher entero de PTB queda suspendido — **ningún otro usuario del bot recibe respuesta a nada durante esa espera**. Esto invalida CA-08 tal como está escrito, y convierte el propio mecanismo de seguridad en un vector de denegación de servicio trivial (cualquier usuario puede bloquear el bot completo por 120s repetidamente con solo no responder a `/eliminar`). El test de CA-08 sugerido en arquitectura §11 no lo detecta porque prueba el adaptador aislado con un `threading.Thread` genérico, sin instanciar una `Application` real. Corrección: agregar `.concurrent_updates(True)` (o un entero) al builder, más un test de integración que verifique la configuración real. **Hallazgo B (no bloqueante, corrección obligatoria):** `TelegramConfirmationAdapter.confirm()` no envuelve `asyncio.run_coroutine_threadsafe(...)` (dentro de `_send_message()`) en `try/except` — si esa llamada lanza (p. ej. loop cerrado durante un reinicio), la excepción escapa antes de llegar a la limpieza de `_pending[user_id]`, dejando una entrada huérfana permanente (ese usuario queda inhabilitado para `/eliminar` hasta reiniciar el proceso) y sin auditar. Mismo patrón que el Hallazgo B de `security-audit-015.md` — corrección acotada (try/finally), resoluble directo en `orion-dev`. **Hallazgo C (no bloqueante, corrección obligatoria):** el test de CA-03 (arquitectura §11) enumera las 19 acciones YELLOW restantes como lista hardcodeada en vez de derivarlas dinámicamente del registro real de `security_manager` — se degrada silenciosamente si se registra una acción YELLOW nueva en el futuro (p. ej. vía el override de REQ-019) sin actualizar la lista a mano. Corrección: derivar la lista con `[name for name, level in security_manager._actions.items() if level == RiskLevel.YELLOW]` (o un accessor público equivalente) en el momento de correr el test. **Punto 1 del encargo, verificado sin hallazgo:** `CHANNEL_ACTION_EXCEPTIONS` es un `set` estático en código, sin ningún punto de carga desde disco/config/usuario, y completamente ortogonal al mecanismo de override de REQ-019 (`_merge_with_override()` no recibe `channel`, no toca `CHANNEL_ALLOWED_LEVELS` ni `CHANNEL_ACTION_EXCEPTIONS`, confirmado leyendo `arquitectura-019.md` completa — cero referencias cruzadas entre ambos REQs). **Punto 4 del encargo, verificado sin hallazgo:** correlación de `_pending`/`resolve()` estrictamente por `str(update.effective_user.id)`, fuente confiable de la API de Telegram, sin ningún camino de que el mensaje de un usuario resuelva la confirmación de otro. **Punto 5, verificado sin hallazgo:** auditoría vía `_log_audit()` existente, sin tabla paralela (con la salvedad de que el camino de excepción del Hallazgo B tampoco audita, ligado a la misma corrección). Handoff emitido a `orion-architect` con los 3 hallazgos — el REQ no avanza a `orion-dev` hasta que se incorporen (especialmente el Hallazgo A, que es indispensable para que CA-08 sea cierto).

2026-08-20 | orion-security | Re-chequeo completado sobre `arquitectura-018.md` §15 (addendum post-auditoría) — `pruebas/security-audit-018.md` sección "Re-chequeo" — **veredicto ✅ APROBADO**, Hallazgo A resuelto y verificado, 1 hallazgo nuevo no bloqueante (E) | **Hallazgo A: RESUELTO Y VERIFICADO CON EVIDENCIA EXPERIMENTAL**, no solo lectura del addendum — ejecuté código real contra el paquete `python-telegram-bot==20.7` instalado: `Application.builder().token(...).build()` sin el fix da `app.concurrent_updates == 1` (bug reproducido); con `.concurrent_updates(True)` da `256` (fix correcto, confirmado contra `Application.concurrent_updates` → `self._update_processor.max_concurrent_updates`, propiedad real, no cacheada). El test de integración nuevo (`test_run_telegram_bot_concurrent_updates_habilitado`) construye una `Application` **real** — no el adaptador aislado, que era exactamente el gap que dejó pasar el bug original — y se verificó experimentalmente que la aserción `app.concurrent_updates > 1` falla si alguien revierte el fix (no es un test placebo). Confirmado además que `channels/telegram_bot.py` no usa `ConversationHandler` (grep), así que la advertencia propia de la librería sobre `concurrent_updates` + handlers con estado no aplica acá — el fix no introduce ese riesgo. Confirmado en el repo real que el código todavía no tiene el fix aplicado (`grep concurrent_updates channels/telegram_bot.py` → 0 resultados, `run_telegram_bot()` línea 804 sin cambios) — esperado, el addendum es diseño, `orion-dev` todavía no corrió sobre este REQ. **Hallazgo E (nuevo, no bloqueante) — respuesta al punto 2 del encargo (nota propia del arquitecto en §15.1):** existe una ventana real, distinta de la ya aceptada en §10 fila 1 de la arquitectura, donde un segundo mensaje del MISMO usuario, llegado casi simultáneo con `/eliminar` (antes de que el hilo worker de `asyncio.to_thread()` alcance a insertar en `_pending[user_id]` dentro de `confirm()`), no se correlaciona como respuesta — `resolve()` no encuentra la entrada y el mensaje cae al procesamiento normal en vez de consumirse. Evaluado el impacto: **no compromete CA-06/CA-09** — no puede producir una confirmación afirmativa no intencionada (`resolve()` solo marca `True` si `_pending[user_id]` ya existe), no puede producir dos confirmaciones pendientes simultáneas (la verificación atómica bajo `self._lock` en `confirm()` sigue intacta), y el sistema permanece fail-closed en el peor caso (la confirmación original expira sola a los 120s, CA-07). Impacto acotado a pérdida de correlación UX, alcanzable en la práctica solo por un cliente automatizado en ráfaga, no por uso humano normal. Clasificado **no bloqueante** — mismo criterio que B/C. Corrección recomendada (documentada en detalle en `security-audit-018.md`): mover la reserva de `_pending[user_id]` a una llamada síncrona nueva (`reserve_pending()`) dentro de `cmd_eliminar()`, **antes** del `await asyncio.to_thread(...)` — cierra la ventana por completo (no solo la acota) y, como efecto colateral, convierte en garantía dura la carrera ya documentada y aceptada en §10 fila 1. No cambia el contrato de `core/confirmation.py` ni el patrón general del adaptador. **Hallazgos B y C: confirmados correctamente documentados** en `arquitectura-018.md` §15.2/§15.3 — ambos remiten al detalle completo en `security-audit-018.md` y ambos incluyen la instrucción explícita de que `orion-dev` los implementa directo sin volver a `orion-architect`; sin cambios necesarios de mi parte. **El REQ puede avanzar a `orion-dev`** con 3 correcciones no bloqueantes pendientes (B, C, E) para implementar en esa misma etapa — ninguna requiere otra vuelta de arquitectura ni de seguridad. Handoff emitido a `orion-dev`.

## Riesgos activos (cont.)
- **RESUELTO (2026-08-20, ver re-chequeo arriba):** el hallazgo bloqueante sobre `.concurrent_updates(...)` faltante en `run_telegram_bot()` fue corregido en `arquitectura-018.md` §15.1 y verificado por `orion-security` con evidencia experimental contra el paquete real instalado — CA-08 pasa a ser cierto con el fix. Ya no es un riesgo activo bloqueante; queda como trabajo de implementación pendiente para `orion-dev` (el fix es de diseño, el código real todavía no lo tiene).
- No bloqueante pero pendiente de implementación explícita en `orion-dev`: limpieza de `_pending` bajo excepción en el envío del mensaje de confirmación (Hallazgo B), derivación dinámica de la lista YELLOW en el test de CA-03 (Hallazgo C), y reserva síncrona de `_pending[user_id]` en `cmd_eliminar()` antes del `await` para cerrar la ventana de correlación de mensajes casi simultáneos del mismo usuario (Hallazgo E, nuevo) — ver `pruebas/security-audit-018.md`, sección "Re-chequeo".
