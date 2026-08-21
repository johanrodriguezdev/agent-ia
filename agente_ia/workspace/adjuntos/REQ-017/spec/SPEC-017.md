# SPEC-017 — Completar/listar/crear tareas en lote sin trabarse por falta de ID exacto

**Estado:** ✅ COMPLETADO — Aprobada por Johan tal cual, sin ajustes, incluidos los 4 puntos ASUMIDO (2026-08-20)
**Categoría:** CORE
**Tipo:** MEJORA
**Fecha:** 2026-08-20

## Objetivo
Cuando el usuario pide una acción sobre "todas" sus tareas pendientes (ej. "completa todas las
tareas pendientes", "ya completé todas las pendientes") sin dar un ID exacto, el agente hoy no
resuelve la acción: según la redacción exacta, o bien devuelve el listado de tareas sin actuar, o
bien pregunta "¿cuál tarea completaste?" en vez de identificar las tareas pendientes y actuar sobre
todas. Este REQ hace que el agente reconozca la intención de "lote" (alcance total, no un ítem) para
la familia de comandos de tareas y actúe directamente, sin pedirle al usuario que repita el comando
en un formato exacto — manteniendo intacta la confirmación obligatoria de acciones 🟡 Amarillo/🔴
Rojo (sin excepción de "lote").

## Alcance
- **Incluye:**
  - Reconocer "todas/todos/todo" (y variantes equivalentes) como alcance de lote para
    **completar** tareas pendientes, cuando no se especifica un ID explícito.
  - Resolver ese lote de forma determinística (listar tareas pendientes del `user_id` del canal y
    completarlas), sin depender de `core/reasoning_loop.py` ni de ninguna llamada a un LLM para
    este caso puntual — hipótesis de diseño default confirmada contra el código (ver "Verificación
    de arquitectura" abajo); `orion-architect` puede apartarse de esta hipótesis si encuentra algo
    que la contradiga, pero debe justificarlo.
  - Que el fix alcance a los 3 canales por los que hoy se puede escribir un comando de tareas en
    lenguaje natural: Desktop (webview), Telegram (texto libre) y Discord (texto libre) — los tres
    pasan por el mismo `core/resolution.py::resolve()` → `_try_task_tool`, así que un cambio ahí
    no requiere tocar nada específico por canal (ver "Módulos afectados").
  - Desambiguar el caso en que el texto dispara a la vez la señal de "listar" (`_TASK_LIST_TRIGGERS`,
    ej. substring "tareas pendientes") y la señal de "completar todo" — debe priorizar completar
    en lote sobre solo listar, cuando ambas coexisten en el mismo texto (ver "Casos borde").
- **No incluye (fuera de alcance, alcance B explícitamente descartado por el humano):**
  - No se cambia `RESOLVERS` ni el orden/lógica general de `core/resolution.py::resolve()`.
  - No se cambia el comportamiento de `routine`/`autopilot`/`learned`/`capability`/`intent`/`claude`.
  - No se conecta `channels/gateway.py` al `reasoning_loop`/tool-calling del LLM — el fallback de
    Telegram/Discord (`_ask_claude_for_user`, chat plano sin tools) queda exactamente igual.
  - No se generaliza esta capacidad a otras categorías de comando (solo tareas: crear/listar/
    completar). Cualquier otra ambigüedad (ej. "abre todas mis apps") queda fuera.
  - No se toca el comando estructurado de Telegram `/completar [id]` (ni `/tareas`, `/nueva`,
    `/eliminar [id]`) — ya exige un ID explícito, no tiene el problema de ambigüedad que resuelve
    este REQ.
  - No se agrega "crear varias tareas a la vez" ni "eliminar varias a la vez" — el disparador
    original de Johan es sobre **completar**, y `delete_task` es 🟡 Amarillo (no se expande su
    superficie sin una SPEC propia que lo evalúe).

## Módulos afectados
- `core/resolution.py` — `_try_task_tool()` (líneas ~144-175) y sus triggers (`_TASK_COMPLETE_TRIGGERS`,
  `_is_task_complete_phrase()`, líneas ~126-141): debe reconocer la señal de "todas/todo" y
  priorizarla sobre `_TASK_LIST_TRIGGERS` cuando ambas coexisten en el texto.
- `agents/tool_registry.py` — `_task_complete_invoke()` (líneas ~109-149): hoy solo extrae UN id
  vía regex y, sin ID y con >1 pendiente, devuelve una aclaración; debe ganar la rama de "completar
  todas las pendientes del usuario" (vía `task_manager.list_tasks()` + `task_manager.complete_task()`
  en bucle), sin perder el comportamiento actual para ID explícito ni para el caso de una sola
  tarea pendiente. `orion-architect` decide si esto vive dentro de `_task_complete_invoke()` o en
  un `ToolSpec` nuevo (ej. `task_complete_all`) — ambas opciones fueron evaluadas como técnicamente
  viables, ninguna fue descartada todavía (ver "Descartado" en el contexto, queda pendiente para
  arquitectura).
- `tasks/task_manager.py` — sin cambios de firma esperados; se reutilizan `list_tasks()` (línea
  ~354) y `complete_task()` (línea ~403) tal como existen hoy.
- **Sin cambios esperados** (documentado para que `orion-tester`/`orion-qa` no asuman regresión si
  ven estos archivos sin tocar): `core/reasoning_loop.py`, `agents/skill_tools.py`,
  `channels/gateway.py`, `channels/telegram_bot.py`, `channels/discord_bot.py`,
  `core/security_manager.py`, `intent/intentions.py`.

## Verificación de arquitectura (confirmado contra código real, no asumido)
- Los 3 canales relevantes llegan al **mismo** `core/resolution.py::resolve()`, que corre siempre
  la misma lista fija `RESOLVERS` (`routine → autopilot → learned → task_tool → capability → intent
  → claude`) sin importar el canal — solo el último paso (`claude`) varía por canal:
  - **Desktop:** `ui/webview/bridge.py::send_message()` (línea 182-184) llama
    `resolve(text, ChannelType.DESKTOP, user_id="default")`.
  - **Telegram (texto libre):** `channels/telegram_bot.py::handle_text()` (línea ~533) →
    `channels/gateway.py::GlassGateway.process()` (línea 45) → `resolve(text, message.channel,
    message.user_id, claude_fn=...)` con `user_id=str(user.id)` (línea 354).
  - **Discord (texto libre):** `channels/discord_bot.py::_process_message()` (línea 55) →
    mismo `GlassGateway.process()`, con `user_id=f"discord_{user_id}"` (línea 61).
  - Como `_try_task_tool` es el 4° resolver (antes de `intent` y `claude`) y su lógica es pura
    coincidencia de substrings sobre `text` — no usa `claude_fn` ni depende del canal — un cambio
    ahí alcanza a los 3 canales automáticamente, sin tocar `gateway.py` ni los bots.
- **Telegram tiene además un camino paralelo y estructurado** que este REQ NO toca:
  `channels/telegram_bot.py::cmd_completar()` (línea 468, comando `/completar [id]`) llama
  `task_manager.complete_task()` **directo**, sin pasar por `resolve()`/`_try_task_tool`/
  `execute_tool()`. Ya exige un ID numérico explícito (no tiene la ambigüedad de "todas"), así que
  queda fuera de alcance. **Nota de riesgo pre-existente, no introducida por este REQ:** ese mismo
  comando directo existe también para `/eliminar [id]` (línea 500, `task_manager.delete_task()`
  directo) — `delete_task` está clasificado 🟡 Amarillo en `security_manager.py` (línea 316), pero
  este camino de Telegram lo ejecuta sin pasar por `security_manager.require_confirmation()`. Es un
  hallazgo de seguridad real pero anterior a REQ-017 y fuera de su objetivo (NLU de comandos
  ambiguos, no auditoría de gates existentes) — se documenta acá para que quede registrado y no se
  pierda, no para resolverlo en este REQ.
- `task_complete` está registrado `RiskLevel.GREEN` en `agents/tool_registry.py` (línea 192) — hoy
  NO requiere confirmación, a diferencia de `delete_task` (🟡 Amarillo). Completar varias tareas en
  lote seguirá sin requerir confirmación, consistente con esta clasificación existente y con la
  decisión de UX de Johan (ver "Criterios de aceptación").
- `tasks/task_manager.py::list_tasks()`/`complete_task()` filtran solo por `user_id`, no por
  `channel` — como Desktop usa `user_id="default"` fijo y Telegram/Discord usan IDs reales
  distintos (`str(user.id)` / `discord_{id}`), "todas las tareas pendientes" solo alcanza a las
  tareas creadas **desde el mismo canal/user_id** que el comando. Esta partición es preexistente y
  no la introduce ni la resuelve este REQ (ver "Casos borde").

## Comportamiento actual vs deseado
| Texto de ejemplo | Actual | Deseado |
|---|---|---|
| "completa todas las tareas pendientes" (contiene el substring "tareas pendientes") | `_try_task_tool` la matchea como `_TASK_LIST_TRIGGERS` primero y devuelve el listado de tareas, sin completar nada | Reconoce la intención de completar en lote (prioriza sobre "solo listar") y completa todas las pendientes |
| "ya completé todas las tareas pendientes" | Matchea `_is_task_complete_phrase()`, cae en `_task_complete_invoke()`; el regex no encuentra ID; si hay >1 pendiente, responde "¿Podría indicarme el número de la tarea...?" | Detecta "todas" en el texto, lista las pendientes del usuario y las completa todas, sin preguntar cuál |
| "completa la tarea #3" (ID explícito) | Completa solo la tarea #3 | Sin cambios — sigue completando solo la tarea #3 |
| "completa mi tarea" (1 sola pendiente, sin ID) | Auto-completa la única pendiente | Sin cambios — sigue auto-completando la única pendiente |
| "completa mis tareas" (0 pendientes) | "No tiene ninguna tarea pendiente en este momento, Señor." | Sin cambios |
| `/completar 3` (Telegram, comando estructurado) | Completa la tarea #3 directo, sin gate | Sin cambios — fuera de alcance |

## Criterios de aceptación
- [ ] Con 2 o más tareas pendientes y un texto que exprese "completar todas" (sin ID explícito,
      variantes razonables: "completa todas las tareas pendientes", "ya completé todas las
      pendientes", "termina todas mis tareas", etc.), el sistema completa **todas** las tareas
      pendientes del `user_id` correspondiente, sin pedir aclaración ni devolver solo el listado.
- [ ] El mensaje de respuesta confirma cuántas tareas se completaron (idealmente listando sus
      títulos/IDs), no un genérico "listo".
- [ ] Con exactamente 1 tarea pendiente y sin ID explícito: comportamiento sin cambios (auto-completa
      esa única tarea, mismo mensaje que hoy).
- [ ] Con 0 tareas pendientes: comportamiento sin cambios ("No tiene ninguna tarea pendiente...").
- [ ] Con un ID explícito en el texto (ej. "completa la tarea #3"): comportamiento sin cambios,
      completa solo esa tarea, incluso si el texto también contiene la palabra "todas" en otro
      sentido (ej. "de todas mis tareas, completa la #3" — el ID explícito tiene prioridad).
- [ ] El mismo texto de "completar todas" produce el mismo resultado en los 3 canales: Desktop,
      Telegram (texto libre) y Discord (texto libre) — verificado con al menos un test por canal
      que ejercite `resolve()` end-to-end con el `user_id`/`channel` real de cada uno.
- [ ] Cada tarea completada en el lote sigue pasando por `agents/tool_registry.py::execute_tool()`
      (el gate real), no se agrega ningún camino que llame `task_manager.complete_task()` sin pasar
      por ese punto — verificable con un test que espíe/mockee `execute_tool` o
      `security_manager.require_confirmation`.
- [ ] No se pide ninguna confirmación adicional antes de completar el lote (decisión de UX de
      Johan: se ejecuta y se notifica el resultado después) — consistente con que `task_complete`
      sigue clasificado `RiskLevel.GREEN`, sin cambios en `core/security_manager.py`.
- [ ] `delete_task` y cualquier otra acción 🟡/🔴 no reciben ningún cambio de comportamiento por
      este REQ: siguen pidiendo confirmación exactamente igual, sin excepción de "lote" — test de
      regresión explícito que confirme que un `delete_task` en lote (si se intentara) seguiría
      bloqueado sin confirmación.
- [ ] `/completar [id]` de Telegram (comando estructurado) sigue funcionando exactamente igual, sin
      tocar `channels/telegram_bot.py`.
- [ ] `core/reasoning_loop.py`, `RESOLVERS` y el resto de los resolvers de `core/resolution.py`
      quedan sin cambios de comportamiento — test de regresión de `tests/test_resolution.py` y
      `tests/test_reasoning_loop.py` pasa sin modificaciones.
- [ ] Suite `pytest` completa existente sigue pasando sin nuevos fallos.

## Casos borde
- **Texto ambiguo entre "listar" y "completar todo"** (ej. "completa todas las tareas pendientes",
  que contiene el substring de `_TASK_LIST_TRIGGERS` "tareas pendientes"): debe priorizarse la
  señal de completar en lote sobre el listado simple. `orion-architect` debe especificar el criterio
  de desambiguación exacto (ej.: la presencia de un verbo de completar — "completa", "termina",
  "marca", "ya completé" — antes de evaluar el trigger de listado puro).
- **ID explícito + palabra "todas" en el mismo texto** (ej. "de todas mis tareas, la #3 ya la
  hice"): el ID explícito gana, se completa solo esa tarea.
- **Partición por canal/`user_id`:** "todas las tareas pendientes" dicho desde Telegram solo
  alcanza a las tareas con `user_id=str(telegram_user_id)`; no incluye tareas creadas desde Desktop
  (`user_id="default"`) ni Discord (`user_id=f"discord_{id}"`). Esto es un comportamiento
  preexistente del sistema de tareas, no introducido ni resuelto por este REQ — se documenta para
  que no se confunda con un bug nuevo si Johan lo nota al usar varios canales.
- **Volumen alto de tareas pendientes** (ej. 20+): al ser resolución determinística (sin LLM), no
  aplica el límite de `MAX_LLM_CALLS=5`, pero conviene un tope razonable de tareas completadas por
  invocación y de longitud del mensaje de respuesta — `orion-architect` debe proponer un límite
  (ej. alinear con el `limit=20` que ya usa `list_tasks()` por defecto) y qué pasa si se supera
  (¿completa las primeras N y avisa que hay más, o pide confirmación de que son muchas?).
- **Canal VOICE:** no fue parte de lo pedido explícitamente por Johan (pidió Desktop/Telegram/
  Discord), pero como pasa por el mismo `resolve()`/`_try_task_tool`, heredará este comportamiento
  automáticamente. `CHANNEL_ALLOWED_LEVELS` permite GREEN en VOICE, así que no hay bloqueo de canal
  — se documenta como efecto colateral esperado, no como objetivo de este REQ.

## Restricción de seguridad — NO NEGOCIABLE (confirmada por Johan, no se vuelve a preguntar)
`.claude/rules/security-levels.md` y el gate fail-closed de REQ-005 se mantienen sin ninguna
excepción para este REQ: ninguna acción 🟡 Amarillo/🔴 Rojo se ejecuta sin pasar por
`security_manager.require_confirmation()`, acción por acción, sin bulk-bypass. Hoy `task_complete`
es 🟢 Verde (no pide confirmación) y así se mantiene — completar varias a la vez no cambia su
clasificación de riesgo ni introduce un camino que la esquive. Si en el futuro `task_complete`
cambiara a Amarillo/Rojo, cada tarea del lote seguiría pidiendo su propia confirmación individual,
sin agrupar.

## Asumidos
- ASUMIDO: la ubicación exacta de la lógica de "completar todas" (dentro de `_task_complete_invoke()`
  vs. un `ToolSpec`/función nueva) queda a criterio de `orion-architect` — ambas opciones cumplen
  esta SPEC.
- ASUMIDO: el tope de tareas por invocación de lote (ver "Casos borde") lo define `orion-architect`;
  esta SPEC solo exige que exista un comportamiento razonable y documentado, no un número específico.
- CONFIRMADO (ya no es un asumido): el hallazgo de seguridad pre-existente en `/eliminar` de
  Telegram (bypass del gate para una acción 🟡 Amarillo) queda fuera de este REQ. Johan decidió
  abrirlo como REQ de seguridad aparte (a iniciar por separado vía `orion-coordinador`) — no se
  mezcla con REQ-017.
- ASUMIDO: "variantes razonables" de la frase de lote (ver criterios) se interpretan de forma
  amplia pero determinística (palabras clave: "todas", "todos", "todo"), no vía LLM — si en QA se
  encuentra una redacción común que no dispara ninguna variante cubierta, se ajustan los triggers,
  no se agrega dependencia de LLM (eso sería alcance B).
