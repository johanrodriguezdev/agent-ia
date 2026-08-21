# Contexto REQ-017 — Mejor comprensión/ejecución de acciones vía interpretación de lenguaje natural

## Resumen ejecutivo
Johan pidió que el agente entienda mejor las órdenes y actúe en vez de trabarse pidiendo que
repita el comando en un formato exacto. El disparador fue: le dijo "completa todas las tareas
pendientes" y el agente respondió preguntando "¿cuál tarea ya terminaste hoy?" en vez de resolverlo.
Eligió explícitamente la opción amplia (usar el LLM para interpretar intención y actuar
directamente cuando sea razonable), pero rechazó que "todo lo interprete por lenguaje natural" de
forma descontrolada — quiere que actúe, no que se quede esperando el formato exacto. Punto crítico:
esto NO puede significar saltarse las confirmaciones obligatorias de `security-levels.md` (Amarillo/Rojo).

## Estado actual
- **Estado tracker:** SPEC_APROBADO (CSV actualizado vía `update-tracker.mjs`: NUEVO → EN_SPEC →
  SPEC_APROBADO, `Aprobacion_SPEC=APROBADO`, `Tipo_Cambio=MEJORA`)
- **Último agente:** orion-spec (✅ COMPLETADO — SPEC-017.md aprobada por Johan, handoff emitido a
  `orion-baseline`)
- **Fecha última actualización:** 2026-08-20
- **Rama git:** feature/REQ-015-webview-ui (rama activa del repo al crear el REQ — no asumida como
  rama de trabajo de REQ-017; orion-architect debe confirmar con el humano si corresponde una rama
  nueva `feature/REQ-017-...` antes de tocar código)
- **Categoría:** CORE (overlap con INTEGRACION descartado — Johan eligió Alcance A, acotado a la
  familia de comandos de tareas, no el pipeline general)
- **Tipo de cambio:** MEJORA (confirmado — Alcance A, no FEATURE_NUEVA)

## Respuestas de Johan a las preguntas de clarificación (recibidas vía el orquestador, 2026-08-20)
1. **Alcance → (A) acotado.** Solo la familia de comandos de tareas (crear/listar/completar), no el
   rediseño del pipeline de `core/resolution.py::resolve()`. La pregunta 5 (límite de
   `MAX_LLM_CALLS` para alcance B) queda sin objeto.
2. **Canales → Desktop + Telegram + Discord**, no solo Desktop. Pidió explícitamente evaluar la
   opción más simple: extender el trigger léxico de `_try_task_tool` en `core/resolution.py` para
   reconocer "todas/todo" y resolver el lote de forma determinística vía
   `task_manager.list_tasks()` + `complete_task()`, SIN necesitar el LLM/`reasoning_loop` para este
   caso — usarla como hipótesis de diseño default para la SPEC, dejando la decisión final a
   `orion-architect`.
3. **Restricción de seguridad (confirmación Amarillo/Rojo, sin bulk-bypass) → confirmada.** Ya se le
   había remarcado antes de este REQ — no se le repreguntó. Documentada en SPEC-017.md como
   restricción dura.
4. **UX de lote → sin confirmación previa.** Completar directamente y notificar el resultado
   después, consistente con que `task_complete` ya es 🟢 Verde hoy (no pide confirmación).

## Verificación adicional post-respuestas (código real, para responder el pedido explícito del
orquestador de confirmar si los 3 canales pasan por el mismo `resolve()`)
- **Confirmado:** Desktop (`ui/webview/bridge.py:182-184`), Telegram texto libre
  (`channels/telegram_bot.py::handle_text` → `channels/gateway.py::GlassGateway.process()`) y
  Discord (`channels/discord_bot.py::_process_message` → mismo `GlassGateway.process()`) los 3
  llaman a `core/resolution.py::resolve()`, que corre siempre la misma lista fija `RESOLVERS` sin
  importar el canal — `_try_task_tool` (4° resolver) es pura coincidencia de substrings sobre
  `text`, no depende de `claude_fn` ni de canal. Confirma la hipótesis de diseño de Johan: un fix
  en `_try_task_tool`/`agents/tool_registry.py` alcanza a los 3 canales sin tocar `gateway.py` ni
  los bots.
- **Hallazgo nuevo — Telegram tiene un camino paralelo estructurado que NO pasa por `resolve()`:**
  `channels/telegram_bot.py` registra comandos slash `/tareas`, `/nueva`, `/completar [id]`,
  `/eliminar [id]` (líneas 818-821) que llaman a `tasks/task_manager.py` **directo**
  (`cmd_completar` línea 468, `cmd_eliminar` línea 500), sin pasar por `resolve()` ni por
  `execute_tool()`. `/completar` ya exige un ID explícito así que no tiene la ambigüedad que
  resuelve este REQ (queda fuera de alcance, documentado en SPEC-017.md). Pero `/eliminar [id]`
  llama `task_manager.delete_task()` sin pasar por `security_manager.require_confirmation()`, pese
  a que `delete_task` está clasificado 🟡 Amarillo (`core/security_manager.py:316`) — es un gate
  bypasseado preexistente, NO introducido por REQ-017. Se documentó en SPEC-017.md como riesgo
  conocido fuera de alcance (sección "Asumidos"), no se corrige en este REQ para no meter alcance
  no pedido por Johan; queda pendiente confirmar si amerita un REQ de seguridad aparte.
- Discord no tiene comandos slash de tareas (solo `/noddoo`, `/memoria`, `/limpiar`, `/ayuda`) — todo
  el manejo de tareas en Discord pasa por texto libre → `resolve()`, sin camino paralelo.
- Confirmado también: el canal VOICE (`main.py:160-191`) pasa por el mismo `resolve()` — no fue
  pedido por Johan pero heredará el comportamiento como efecto colateral (documentado en
  SPEC-017.md, "Casos borde", no es objetivo de este REQ).

## Mensajes originales de Johan (verbatim, español, 2 mensajes seguidos)

**Mensaje 1:**
> Quiero que el agente pueda tener mejor comprensión o dime como puedo entrenar para que aprenda a
> realizar acciones por ejemplo le dije que complete todas las tareas pendientes y me pregunto que
> cual tarea ya termine hoy

**Mensaje 2** (tras ofrecerle 2 opciones: (a) fix chico solo para "completar todas las tareas",
(b) capacidad general de interpretación por lenguaje natural para ejecutar acciones — eligió (b),
la más amplia):
> No quiero que todo la IA lo interprete por lenguaje natural para que haga acciones no que se
> quede esperando hasta que le diga exactamente para que lo haga

**Interpretación confirmada con Johan:** quiere que el agente use al LLM para interpretar la
intención del usuario y ACTUAR directamente cuando sea razonable, en vez de trabarse pidiendo que
el usuario repita el comando en un formato/frase exacta que un detector léxico rígido pueda
matchear.

## Investigación de arquitectura ya hecha (sesión previa, por subagente Explore)
Resumen para que orion-spec/orion-architect no la repitan desde cero. **Verificar contra el código
real de todas formas — esto es un resumen, no la fuente de verdad.**

1. No existe ningún skill de tareas en `skills/` (ese directorio es solo weather/web/
   file_system/etc.). El manejo de tareas vive FUERA del sistema `BaseSkill`, como triggers
   léxicos de substring en `core/resolution.py` (función `_try_task_tool`, ~líneas 116-175), que
   llaman a `agents/tool_registry.py` (`_task_complete_invoke`, ~línea 109-149) →
   `tasks/task_manager.py::complete_task(task_id, user_id)` (línea 403).

2. El "extract" real de completar tarea es un regex en `agents/tool_registry.py` línea ~121:
   `re.search(r"(?:tarea|numero|número|id)\s*#?(\d+)", text_lower)` — solo extrae UN id numérico.
   Sin match y con >1 tarea pendiente, cae a pedir aclaración (líneas ~143-149): "He notado que
   tiene varias tareas pendientes... ¿Podría indicarme el número de la tarea que completó?" — esa
   es la fuente real de la pregunta que le hizo a Johan.

3. Pipeline de resolución: `core/resolution.py` define `RESOLVERS` en orden fijo (~línea 243-250):
   `routine → autopilot → learned → task_tool → capability → intent → claude`, recorridos por
   `resolve()` (línea 254). El clasificador entrenable TF-IDF+SVM (`intent/ai_classifier.py`) NUNCA
   ve comandos de tareas porque `Intent` (`intent/intentions.py`) no tiene ningún intent de tareas
   — el `_try_task_tool` lo intercepta antes por substring.

4. SÍ existe un fallback LLM con tool-calling real: `core/reasoning_loop.py`
   (`_build_tool_list()` línea ~33, `execute_tool()` línea ~112, tope `MAX_LLM_CALLS=5` línea ~20)
   — pero solo tiene tools de "una tarea a la vez" (`task_create`/`task_list`/`task_complete`,
   `agents/tool_registry.py` ~línea 152-194), sin ninguna de "listar y completar en lote". Si el
   LLM llama `task_complete` sin id, recibe el texto de aclaración y lo devuelve tal cual en vez de
   iterar `task_list` → `task_complete` por cada resultado.

5. `learning/command_learning.py` (TEACH_COMMAND) es solo un diccionario frase→[acciones] literal
   grabado por el usuario — no generaliza, no es relevante para esto.

## Punto crítico de seguridad — NO NEGOCIABLE por este REQ
`.claude/rules/security-levels.md` (niveles verde/amarillo/rojo) y REQ-005 (deny-list fail-closed
en `core/security_manager.py`) son reglas vigentes del proyecto, no negociables por REQ-017. Que el
agente "actúe directamente" por interpretación de lenguaje natural NO puede significar saltarse la
confirmación obligatoria de acciones 🟡 Amarillo/🔴 Rojo. Como mucho, este REQ puede hacer que el
agente entienda MEJOR qué acción/es querés (ej: identificar que "todas las tareas pendientes" son 3
ids concretos vía `task_list` antes de actuar) sin trabarse en falta de comprensión — pero cualquier
acción que hoy requiera `security_manager.require_confirmation()` lo sigue requiriendo exactamente
igual, acción por acción, sin bulk-bypass.

`orion-spec` DEBE:
1. Preguntarle a Johan explícitamente si entiende y acepta esta restricción (no es negociable, viene
   de reglas ya vigentes del proyecto).
2. Aclarar con él el alcance real, como pregunta central de la spec — no asumir la interpretación
   más amplia sin confirmación explícita:
   - **Alcance A (acotado):** solo la familia de comandos de tareas (arreglo puntual sobre
     `_try_task_tool` / `agents/tool_registry.py` / tools de `core/reasoning_loop.py`).
   - **Alcance B (amplio):** todo el pipeline de resolución (`core/resolution.py`) se apoya más en
     `core/reasoning_loop.py`/tool-calling del LLM en vez de triggers léxicos rígidos, como
     mecanismo general para cualquier categoría de comando futuro. Esto es un cambio de arquitectura
     central del agente, con superficie de riesgo mucho mayor (todo comando pasaría más seguido por
     un LLM con tools en vez de un match determinístico barato).

## Decisiones tomadas
2026-08-20 | orion-coordinador | REQ creado — categoría=CORE | Detección por palabras clave: "main
loop"/"dispatcher" implícito en el disparador (`core/resolution.py`, `core/reasoning_loop.py`,
pipeline de resolución de comandos); posible overlap con INTEGRACION si el alcance se confirma
amplio (uso general de LLM/tool-calling), a decidir por orion-spec junto con el humano.

2026-08-20 | orion-spec | Verificación de hallazgos #1-3 de la investigación previa (sesión anterior,
subagente Explore): CONFIRMADOS contra código real — `_try_task_tool` en
`core/resolution.py:144-175`, `_task_complete_invoke` en `agents/tool_registry.py:109-149` con
regex `(?:tarea|numero|número|id)\s*#?(\d+)` que solo extrae UN id, y `intent/intentions.py` sin
ningún intent de tareas (grep sin resultados) | Lectura directa de los 3 archivos.

2026-08-20 | orion-spec | `task_complete` está registrado `RiskLevel.GREEN`
(`agents/tool_registry.py:192`) — NO requiere confirmación hoy, a diferencia de `delete_task` que
es `YELLOW` (`core/security_manager.py:316`). Confirma el punto que dejó orion-coordinador: no hace
falta preguntarle a Johan "¿debe confirmar?" como si fuera una regla de seguridad — hoy YA no
confirma, por diseño (GREEN nunca pide confirmación, `security_manager.py:254-256`). Lo que sí
puede valer la pena preguntar es un matiz de UX (no de seguridad): si completar varias tareas de
una sola vez sin ningún resumen previo puede sorprender a Johan, aunque la regla de seguridad no lo
exija | Verificado en código.

2026-08-20 | orion-spec | CORRECCIÓN al hallazgo previo #4 de la investigación anterior:
`core/reasoning_loop.py` NO está limitado a 3 tools de "una tarea a la vez". Existe
`agents/skill_tools.py::register_dispatcher_tool()` que registra un tool catch-all `"dispatcher"`
(GREEN) que re-clasifica y despacha CUALQUIER intent vía `router/dispatcher.py:dispatch_as_tool()`,
y `register_skill_tools()` registra un `ToolSpec` por cada intent de cada skill cargada (risk_level
heredado de `security_manager`, fail-closed si falta clasificación) — ambos se llaman en
`main.py:64-65` al arrancar el proceso. Es decir: el reasoning_loop YA tiene acceso al surface
completo de comandos del agente (no solo a tareas) cuando se lo invoca. Esto reduce el "esfuerzo de
construir infraestructura nueva" que tenía Alcance B en la descripción original — la
infraestructura de tool-calling genérico ya existe y está cableada; lo que cambiaría en B es
CUÁNDO/CON QUÉ FRECUENCIA `core/resolution.py::resolve()` decide apoyarse en ella en vez de en los
resolvers léxicos, no si existe o no | Lectura de `agents/skill_tools.py` y `main.py:44,64-65`.

2026-08-20 | orion-spec | Hallazgo nuevo — gap de canal, no cubierto por la investigación previa:
`_try_claude()` en `core/resolution.py:220-241` solo usa el `reasoning_loop` con tool-calling
cuando NO se le pasa un `claude_fn` custom. `ui/webview/bridge.py:182-184` (la app de escritorio,
rama activa `feature/REQ-015-webview-ui`, donde Johan interactúa) llama
`resolve(text, ChannelType.DESKTOP, user_id="default")` SIN `claude_fn` → sí llega al
`reasoning_loop` completo. Pero `channels/gateway.py:91-93` (Telegram/Discord) y
`core/orchestrator.py:50` SÍ pasan un `claude_fn` propio (`_ask_claude_for_user` /
`fallback_to_claude`) que terminan en `ai/claude_brain.ask_claude()` — chat plano, sin
tool-calling ni acceso a `execute_tool()` (confirmado: no hay ningún parámetro `tools=` en su
firma). Implicación directa para la SPEC: si el fix depende del `reasoning_loop`, hoy solo
funcionaría en el canal Desktop/webview — en Telegram/Discord el mismo comando ambiguo seguiría
sin poder actuar, porque el fallback ahí no tiene herramientas | Lectura de `core/resolution.py`,
`channels/gateway.py:77-129`, `core/orchestrator.py:50`, `ui/webview/bridge.py:164-184`,
`ai/claude_brain.py` (sin `tools=` en `ask_claude()`).

2026-08-20 | orion-spec | Hallazgo nuevo — matiz sobre el disparador real del bug: la frase
paraphraseada en el handoff ("completa todas las tareas pendientes") en realidad matchea primero
`_TASK_LIST_TRIGGERS` (substring literal "tareas pendientes", `core/resolution.py:121-125`) ANTES
de evaluar `_is_task_complete_phrase()` — con esa redacción exacta, `resolve()` devolvería el
listado de tareas, no una pregunta de aclaración. La frase que probablemente disparó
"¿cuál tarea ya terminaste hoy?" es una variante en pasado (ej. "ya completé todas las tareas
pendientes"), que sí matchea `_is_task_complete_phrase()` (mentions_task=True vía "tarea",
mentions_done=True vía substring "completad" dentro de "completado/completé") y cae en
`_task_complete_invoke()`, cuyo regex de un solo id no encuentra nada y, con >1 pendiente, devuelve
el texto de aclaración. No se pudo confirmar el texto EXACTO porque el mensaje de Johan en el
contexto es una paráfrasis suya de lo que escribió, no una cita literal capturada por el sistema.
No cambia la conclusión de fondo (el regex de un solo id es la causa raíz), pero sí importa para
que orion-tester después redacte casos de prueba con la redacción real, no con la paráfrasis |
Lectura de `core/resolution.py:116-175` y `agents/tool_registry.py:109-149`.

2026-08-20 | orion-spec | Hallazgo nuevo — gap de esquema en `task_complete`: el `ToolSpec` solo
declara `{text, user_id}` (`agents/tool_registry.py:184-194`), sin un parámetro `task_id` directo
— el LLM tendría que embeber el id dentro de `text` (ej. "tarea #3") para que el regex de
`_task_complete_invoke` lo parsee. Combinado con que cada llamada completa como máximo UNA tarea,
un flujo "listar y completar todas" hecho solo con las tools de a una (sin agregar una tool nueva
de lote) se queda sin presupuesto de `MAX_LLM_CALLS=5` (`core/reasoning_loop.py:20`) a partir de 4
tareas pendientes (1 llamada de list + 4 de complete = 5, sin margen para la respuesta final al
usuario) — refuerza que una tool dedicada de "listar y actuar en lote" (ya sugerida en el handoff
de orion-coordinador) no es un "nice to have" sino casi un requisito para que el caso de uso real
de Johan (varias tareas pendientes) funcione de forma confiable | Cálculo sobre
`agents/tool_registry.py:184-194` y `core/reasoning_loop.py:20,69-140`.

2026-08-20 | orion-spec | Hallazgo nuevo — contradice el supuesto que traía el handoff de
orion-coordinador ("mismo user_id='default' para todos, así que probablemente no haya ambigüedad
real"): NO es cierto que todos los canales usen `user_id="default"`. Solo `ui/webview/bridge.py`
(Desktop) lo hardcodea. `channels/telegram_bot.py:354` usa `user_id=str(user.id)` (ID real de
Telegram) y `channels/discord_bot.py:61` usa `user_id=f"discord_{user_id}"`. Y
`tasks/task_manager.py::list_tasks()`/`complete_task()` (líneas 354-370, 403-414) filtran solo por
`user_id`, no por `channel` — así que las tareas creadas desde Telegram no son visibles ni
completables con "todas mis pendientes" dicho desde Desktop, y viceversa. Es una partición real
preexistente del sistema de tareas (no introducida por REQ-017, y no depende de que el LLM
interprete mal nada) — no bloquea la SPEC pero conviene que Johan lo sepa como limitación conocida,
por si su expectativa real es "todas mis tareas sin importar desde dónde las creé" | Lectura de
`channels/telegram_bot.py:354`, `channels/discord_bot.py:61`, `tasks/task_manager.py:354-370,403-414`.

## Descartado (y por qué)
- Ninguna opción de arquitectura fue descartada todavía — corresponde a orion-spec/orion-architect
  una vez definido el alcance (A o B, ver arriba).

## Asumidos pendientes de confirmar
- Alcance A vs B (ver "Punto crítico de seguridad" arriba) — pregunta central que orion-spec debe
  resolver con Johan antes de redactar la SPEC. Nota: el riesgo/esfuerzo de B sigue siendo mayor que
  A, pero por un motivo distinto al que se pensaba — no es que B requiera construir tool-calling
  genérico desde cero (ya existe, ver hallazgo de `agents/skill_tools.py` arriba), sino que B
  significa que MÁS categorías de comando (no solo tareas) empiecen a resolverse más seguido vía una
  llamada real al LLM en vez de un match determinístico gratis, con el costo/latencia/riesgo de
  interpretación que eso implica.
- Tipo de cambio (MEJORA vs FEATURE_NUEVA) — depende del alcance que se confirme.
- Rama git de trabajo — no se asumió ninguna; la rama activa del repo (`feature/REQ-015-webview-ui`)
  pertenece a otro REQ en curso y no debe usarse para REQ-017 sin decidirlo explícitamente.
- Si el fix debe alcanzar también a Telegram/Discord, sabiendo que hoy su fallback conversacional
  (`_ask_claude_for_user`) no tiene acceso a ninguna tool — ver hallazgo de gap de canal arriba.
- Si a Johan le importa que "todas mis tareas pendientes" separe por canal (partición real por
  `user_id` distinto en Telegram/Discord vs Desktop) o si en la práctica solo usa un canal y no es
  un problema real hoy.

## Riesgos activos
- Que el alcance termine siendo B (pipeline general) sin que el humano haya dimensionado el
  cambio de arquitectura y su superficie de riesgo (más comandos dependiendo de LLM con tools en
  vez de match determinístico).
- Que la restricción de seguridad (confirmación obligatoria Amarillo/Rojo, sin bulk-bypass) se
  diluya al implementar "completar en lote" si no se especifica explícitamente en la SPEC y en la
  arquitectura.
- Si el fix se implementa apoyado en `core/reasoning_loop.py`, hoy NO alcanzaría a Telegram/Discord
  (fallback ahí es chat plano sin tools) salvo que se decida explícitamente conectar
  `channels/gateway.py` al reasoning_loop — lo cual ampliaría el alcance/esfuerzo más allá de lo
  discutido con Johan hasta ahora.
- Un flujo "listar y completar en lote" armado solo con las tools de a una (sin tool nueva
  dedicada) puede agotar `MAX_LLM_CALLS=5` con 4+ tareas pendientes, dejando al usuario sin
  respuesta final aunque las tareas sí se hayan completado.

## Log de transiciones
2026-08-20 | — → NUEVO | orion-coordinador | REQ creado
2026-08-20 | NUEVO (sin cambio de estado tracker, CSV no tocado esta sesión) | orion-spec |
Verificación de la investigación de arquitectura previa contra código real completada (confirmada
en lo esencial, con 4 hallazgos nuevos/correcciones — ver "Decisiones tomadas"). Preguntas de
clarificación identificadas y devueltas al orquestador porque Johan no está presente en esta
sesión. SPEC-017.md aún NO redactada — pendiente de respuestas antes de continuar.
2026-08-20 | NUEVO (sin cambio de estado tracker — CSV se actualiza a SPEC_APROBADO recién cuando
Johan apruebe) | orion-spec | Respuestas de Johan recibidas (Alcance A, 3 canales, restricción de
seguridad confirmada, sin confirmación de UX previa al lote). Verificación adicional de código
confirmó que Desktop/Telegram/Discord comparten `resolve()` y reveló dos hallazgos nuevos (comando
`/completar` de Telegram ya estructurado y fuera de alcance; bypass de seguridad preexistente en
`/eliminar` de Telegram, documentado como riesgo fuera de alcance). SPEC-017.md redactada en
`workspace/adjuntos/REQ-017/spec/SPEC-017.md`. Estado: ⏸️ ESPERANDO VALIDACIÓN humana explícita —
el flujo no continúa a `orion-baseline` hasta que Johan responda APROBADO / AJUSTAR / RECHAZADO.
2026-08-20 | SPEC_APROBADO | orion-spec | Johan aprobó SPEC-017.md TAL CUAL, sin ajustes, incluidos
los 4 puntos ASUMIDO. Decidió además que el hallazgo de seguridad de `/eliminar` de Telegram (gate
bypasseado para una acción 🟡 Amarillo, documentado en la SPEC como fuera de alcance) se abre como
REQ de seguridad aparte — lo inicia el orquestador por separado vía `orion-coordinador`, no se
mezcla con REQ-017. SPEC-017.md actualizada a Estado ✅ COMPLETADO. CSV actualizado vía
`update-tracker.mjs`: `Estado` NUEVO → EN_SPEC → SPEC_APROBADO, `Aprobacion_SPEC=APROBADO`,
`Tipo_Cambio=MEJORA`. `Rama` sigue `—` (no es tarea de `orion-spec`, la confirma `orion-architect`
según `.claude/rules/git.md`).
2026-08-20 | SPEC_APROBADO → (handoff) | orion-spec | DoD de `orion-spec` cerrado. Handoff emitido:
`@orion-baseline REQ-017 | spec=workspace/adjuntos/REQ-017/spec/SPEC-017.md`

## Decisiones tomadas
2026-08-20 | orion-baseline | 3 archivos previstos a modificar (`core/resolution.py`,
`agents/tool_registry.py`, sin cambios de firma en `tasks/task_manager.py`), confirmados contra el
código real línea por línea | Ver `origen/baseline-017.md`.

2026-08-20 | orion-baseline | Corrección/matiz a la tabla "Comportamiento actual vs deseado" de
SPEC-017.md: se ejecutó (no se asumió) `_TASK_CREATE_TRIGGERS`/`_TASK_LIST_TRIGGERS`/
`_is_task_complete_phrase()` contra los textos de ejemplo de la SPEC. Confirmado que
`_try_task_tool()` evalúa create → list → complete en cadena secuencial con `return` temprano
(equivalente a if/elif/elif, nunca se evalúan los 3 para el mismo texto). Hallazgo: la fila de la
tabla "ya completé todas las tareas pendientes" (SPEC dice que llega a
`_is_task_complete_phrase()`/`_task_complete_invoke()`) en realidad matchea `_TASK_LIST_TRIGGERS`
("tareas pendientes") ANTES y nunca llega a evaluar la rama de completar — mismo resultado para
"completa todas las tareas pendientes", "termina todas mis tareas" y "completa mis tareas" (las 4
variantes de "todas" probadas caen en `task_list`, no en `task_complete`). Además, frases sin la
palabra "tarea"/"tareas" (ej. "ya completé todas las pendientes", "marca todas como completadas")
no matchean ningún trigger hoy y ni siquiera llegan a `_try_task_tool` con resultado — siguen a
`capability`/`intent`/`claude`. El mensaje "No tiene ninguna tarea pendiente en este momento,
Señor." que cita la SPEC para el caso de 0 pendientes SÍ es real, pero es el que devuelve
`_task_complete_invoke()` cuando se llega por la rama `complete` (no por "completa mis tareas", que
resuelve vía `task_list` → `get_task_summary()` → mensaje distinto, "No tiene ninguna tarea
registrada..."). No cambia los criterios de aceptación de la SPEC (están redactados en términos de
comportamiento deseado, no de mecanismo interno), pero es información crítica para que
`orion-architect` ubique el punto de intercepción de "todas" ANTES del chequeo de
`_TASK_LIST_TRIGGERS` (no solo antes de `_is_task_complete_phrase()`) y decida si también cubre
frases sin la palabra "tarea" explícita | Ejecución directa de las 3 funciones contra 8 textos de
ejemplo (ver tabla completa en `origen/baseline-017.md`).

2026-08-20 | orion-baseline | Fallos pre-existentes: 2 (`tests/test_llm_provider.py`,
`ModuleNotFoundError: No module named 'anthropic'`), mismos que documentó `baseline-016.md`, no
relacionados con los archivos que este REQ modifica | `pytest tests/ -q` → `2 failed, 420 passed`.
Suite acotada (`test_resolution.py`, `test_tool_registry.py`, `test_reasoning_loop.py`) → 27
passed, sin fallos. `PYTEST_QT_API` ya se fija incondicionalmente en `conftest.py:38` — no requiere
acción extra aunque REQ-017 no toque Qt/webview.

2026-08-20 | orion-baseline | Gap de cobertura confirmado: no existe `tests/test_task_manager.py`;
`tests/test_resolution.py` no ejercita la lógica interna de `_try_task_tool`; `tests/test_tool_registry.py`
solo tiene un test de `task_list`. Casi toda la cobertura de los 11 CA de SPEC-017.md será test
nuevo | Grep sobre `tests/`.

## Riesgos activos
- El punto de intercepción de "todas/todo" debe ubicarse antes del chequeo de
  `_TASK_LIST_TRIGGERS`, no solo antes de `_is_task_complete_phrase()` — si `orion-architect` solo
  reordena los dos últimos bloques sin mover el chequeo más arriba, la mayoría de las frases reales
  de "completar todas" seguirán sin resolverse (ver decisión de orion-baseline arriba).
- Frases de "completar todas" sin la palabra "tarea"/"tareas" (ej. "ya completé todas las
  pendientes") no matchean ningún trigger hoy — depende de qué tan amplio `orion-architect` defina
  el criterio de detección de "todas".
- Los 2 fallos pre-existentes de `test_llm_provider.py` (`ModuleNotFoundError: anthropic`)
  seguirán apareciendo en la corrida de `orion-tester` — no es regresión de REQ-017.
- Working tree compartido con el diff de REQ-015/016 sin commitear — cualquier `git diff`/`git
  status` durante REQ-017 va a mezclar los tres REQs hasta que Johan decida el orden de commits.

## Estado actual
- Estado tracker: SPEC_APROBADO (sin cambio — DoD de `orion-baseline` no incluye transición de
  Estado del tracker; CSV no tocado esta sesión)
- Último agente: orion-baseline
- Fecha última actualización: 2026-08-20
- Rama git: feature/REQ-015-webview-ui (activa del repo, no confirmada como rama de trabajo de
  REQ-017 — pendiente de `orion-architect`)

## Log de transiciones
2026-08-20 | SPEC_APROBADO (sin cambio de estado tracker — DoD de `orion-baseline` no transiciona
Estado) | orion-baseline | `baseline-017.md` redactado en `workspace/adjuntos/REQ-017/origen/`.
3 archivos previstos a modificar, fallos pre-existentes registrados (2, no relacionados), hallazgo
de discrepancia en la tabla de comportamiento actual de la SPEC documentado (no bloquea, informa a
`orion-architect`). Handoff emitido a `orion-architect`.

## Decisiones tomadas
2026-08-20 | orion-architect | Hallazgo nuevo (verificado con ejecución real, no cubierto por SPEC
ni baseline): `_is_task_complete_phrase("completa la tarea #3")` y
`_is_task_complete_phrase("completa mi tarea")` devuelven `False` — ninguno de los dos ejemplos de
las filas "ID explícito"/"1 sola pendiente" de la tabla de SPEC-017.md matchea ningún trigger HOY
(`create=False, list=False, complete_phrase=False` para ambos), porque `mentions_done` en
`_is_task_complete_phrase()` solo reconoce el participio ("completad"/"terminad"), no el
imperativo/presente ("completa"). Mismo tipo de inexactitud que ya corrigió `orion-baseline` para la
fila de "todas", pero en dos filas distintas que baseline no probó. No cambia los CA (redactados en
términos de comportamiento deseado), pero cambia qué texto de prueba usar para CA-03/CA-05 (no se
puede usar el texto literal de la tabla de SPEC-017.md, hay que usar uno que ya matchea hoy, ej. "ya
completé mi tarea") | Ejecución directa de `_is_task_complete_phrase()` contra los 2 textos.

2026-08-20 | orion-architect | Verificado que el regex de ID que usa hoy `_task_complete_invoke()`
(`(?:tarea|numero|número|id)\s*#?(\d+)`) NO matchea el propio ejemplo de casos borde de
SPEC-017.md ("de todas mis tareas, la #3 ya la hice") porque el `#3` no está precedido por
tarea/numero/id — condición necesaria para que CA-05/CA-06 (ID gana sobre "todas") sea cumplible con
el ejemplo literal de la SPEC. Decisión: ampliar `_TASK_ID_RE` en `agents/tool_registry.py` para
aceptar también un `#N` suelto (segunda alternativa del regex), y exponer `has_explicit_task_id()`
para que `core/resolution.py` lo reutilice sin duplicar el regex en dos módulos | Ejecución directa
del regex actual contra el ejemplo de SPEC-017.md, "Casos borde".

2026-08-20 | orion-architect | Punto de intercepción de "todas": nueva función
`_is_bulk_complete_phrase()` en `core/resolution.py`, insertada en `_try_task_tool()` ANTES del
chequeo de `_TASK_LIST_TRIGGERS` (después de `create`, que mantiene su prioridad sin cambios) — implementa
el hallazgo crítico de `orion-baseline`. Requiere verbo de completar ("complet"/"termin"/"marc") Y
la palabra todas/todos/todo (ambas condiciones, no una sola) para reducir falsos positivos. Dentro
de ese mismo bloque, el chequeo de ID explícito (`has_explicit_task_id()`) se evalúa PRIMERO y gana
siempre sobre "todas" y sobre "listar" (CA-05, CA-06) | Ver `arquitectura-017.md` §2.1.

2026-08-20 | orion-architect | Tool nuevo `task_complete_all` (`ToolSpec`, GREEN) en
`agents/tool_registry.py`, en vez de extender `_task_complete_invoke()` in-place — mantiene esa
función con una sola responsabilidad, y el nombre de acción distinto queda trazable por separado en
`security_manager`/logs. `_task_complete_all_invoke()` reutiliza `list_tasks()`+`complete_task()` en
bucle, gateado UNA vez por invocación de lote (no N veces por tarea) — mismo patrón que ya usa hoy
`_task_complete_invoke()` en su rama de auto-completar la única pendiente. Tope de lote:
`_TASK_COMPLETE_ALL_LIMIT=20`, alineado con el default de `list_tasks()` (sugerencia de SPEC-017.md,
adoptada tal cual) | Ver `arquitectura-017.md` §2.2, §6.

2026-08-20 | orion-architect | Decisión explícita de NO convertir el chequeo de ID explícito en un
gate independiente de nivel superior (que dispararía para cualquier texto con un `#N` suelto, sin
relación a "todas"/"listar") — queda condicionado a `bulk_all or list_trigger`, actuando solo como
desempate en los casos que la SPEC pide desambiguar. Consecuencia declarada: el ejemplo
"completa la tarea #3" sin colisión con "todas"/"listar" queda sin cambios (ver hallazgo de arriba)
— pendiente de confirmar con Johan si ese alcance más chico es aceptable (pregunta abierta en
`arquitectura-017.md` §10) | Ver `arquitectura-017.md` §2.1, "Por qué el chequeo de ID explícito
está condicionado".

2026-08-20 | orion-architect | Evaluado si corresponde `orion-security` (mismo criterio que REQ-016
§11): NO corresponde — no se toca `core/security_manager.py`, no se registra ninguna acción en un
nivel distinto de GREEN, no se introduce ningún camino que evite `execute_tool()`/
`require_confirmation()`, no se manejan secretos ni `os.system()`/`subprocess` | Ver
`arquitectura-017.md` §8.

## Descartado (y por qué)
2026-08-20 | orion-architect | Extender `_task_complete_invoke()` in-place con una rama de "todas"
en vez de crear `task_complete_all` como `ToolSpec` nuevo: descartado — mezclaría dos
responsabilidades (completar una tarea por ID/deducción vs. completar todas) en la misma función y
perdería trazabilidad de acción distinta en `security_manager`/logs | Ver `arquitectura-017.md` §2.2.

2026-08-20 | orion-architect | Convertir `has_explicit_task_id()` en un gate de nivel superior
(disparando para cualquier texto con ID explícito, no solo en colisión con "todas"/"listar"):
descartado por ahora — ampliaría la superficie de intercepción de `_try_task_tool()` más allá de lo
necesario para cumplir la SPEC, con riesgo de falsos positivos en texto sin relación a tareas (ej.
referencias con `#N` sueltas). Queda como pregunta abierta para Johan, no decidido unilateralmente |
Ver `arquitectura-017.md` §2.1, §10.

## Asumidos pendientes de confirmar
- ¿Se acepta que "completa la tarea #3" (sin "todas" ni colisión con `list`) quede sin cambios por
  este REQ (nunca llegó a completarse determinísticamente, hallazgo nuevo), o se amplía el alcance
  para arreglarlo también? Ver `arquitectura-017.md` §10, pregunta 1.
- ¿Se mantiene "todo" (singular) en el set de palabras clave de "todas" pese al riesgo de falso
  positivo documentado (§7 de la arquitectura), tal como lo aprobó Johan en el ASUMIDO de
  SPEC-017.md, o se acota a solo "todas"/"todos"? Ver `arquitectura-017.md` §10, pregunta 2.
- Rama de trabajo: propuesta `feature/REQ-017-completar-tareas-lote`, no creada todavía — pendiente
  de confirmación explícita de Johan (regla de `git.md`).

## Riesgos activos
- Falso positivo de `_is_bulk_complete_phrase()` con la palabra "todo" (singular) combinada
  casualmente con un verbo de completar en la misma oración sin relación a tareas — riesgo bajo,
  documentado con mitigación en `arquitectura-017.md` §7, mismo tipo de trade-off ya aceptado en el
  módulo desde REQ-006.
- Ampliar `_TASK_ID_RE` para aceptar `#N` suelto podría cambiar el resultado de textos que ya
  matcheaban `_is_task_complete_phrase()` por otra razón (de "auto-deducir" a "completar ID
  específico") — cambio de comportamiento de bajo impacto, documentado en `arquitectura-017.md` §7.

## Estado actual
- Estado tracker: SPEC_APROBADO (sin cambio — CSV se actualiza a ARQUITECTURA_APROBADA recién
  cuando Johan apruebe la propuesta; DoD de `orion-architect` no transiciona el tracker antes de la
  aprobación humana)
- Último agente: orion-architect
- Fecha última actualización: 2026-08-20
- Rama git: feature/REQ-015-webview-ui (activa del repo, NO es la rama de trabajo de REQ-017 —
  propuesta `feature/REQ-017-completar-tareas-lote` pendiente de confirmación de Johan)

## Log de transiciones
2026-08-20 | SPEC_APROBADO (sin cambio de estado tracker) | orion-architect |
`arquitectura-017.md` redactada en `workspace/adjuntos/REQ-017/propuestas/`. Cobertura de los 12
CA de SPEC-017.md documentada, 2 hallazgos nuevos verificados contra código real (ver "Decisiones
tomadas"), 2 preguntas abiertas para Johan sin bloquear el resto de la propuesta. Estado: ⏸️
ESPERANDO APROBACIÓN humana explícita — el flujo no continúa a `orion-dev` hasta que Johan responda
APROBADO / AJUSTAR / RECHAZADO.

## Decisiones tomadas
2026-08-20 | orion-architect | Johan respondió las 2 preguntas abiertas de `arquitectura-017.md`
§10 y APROBÓ la propuesta con 2 ajustes menores:
1. El bug preexistente "completa la tarea #3"/"completa mi tarea" no matchea ningún trigger hoy
   (hallazgo de §0 de la arquitectura) — Johan confirmó que NO se arregla en REQ-017, queda
   registrado para un REQ futuro (no se abre desde este flujo). Ver "Descartado" abajo.
2. "Todo" (singular) se saca del set de palabras clave de "todas" — queda solo "todas"/"todos".
   Motivo de Johan: es la palabra de mayor riesgo de falso positivo del set (frases sin relación a
   tareas, ej. "todo bien"), y los 3 ejemplos literales de SPEC-017.md ya matchean con "todas" sin
   necesitarla. Es un ajuste menor respecto al ASUMIDO original de SPEC-017.md ("todas/todos/todo"),
   documentado con motivo (mismo criterio de REQ-015/REQ-016 para ajustes menores respecto a la
   propuesta) | Aplicado en `arquitectura-017.md` §2.1, §7, "Ajustes de Johan" (nueva sección al
   inicio del documento).

2026-08-20 | orion-architect | `arquitectura-017.md` marcada como ✅ APROBADA. DoD de
`orion-architect` cerrado: los 12 CA referenciados, módulos/clases/funciones/firmas exactas
especificadas, flujo de datos documentado, dependencias nuevas identificadas (ninguna), riesgos con
mitigación documentados, pruebas sugeridas listadas, aprobación humana explícita recibida.

## Descartado (y por qué)
2026-08-20 | orion-architect | **Descartado del alcance de REQ-017, pendiente de REQ futuro:**
arreglar que "completa la tarea #3" y "completa mi tarea" no completen ninguna tarea hoy (no
matchean ningún trigger de `_try_task_tool()`, hallazgo verificado con ejecución real en
`arquitectura-017.md` §0 — no lo había detectado ni SPEC-017.md ni `baseline-017.md`, que no
probaron esos textos específicos). Johan decidió explícitamente NO ampliar el alcance de REQ-017
para cubrirlo, y que se abra como REQ aparte más adelante (no lo inicia este flujo). Queda
documentado acá para que no se pierda cuando se decida abrirlo | Confirmado por Johan, 2026-08-20.

## Estado actual
- Estado tracker: ARQUITECTURA_APROBADA (CSV actualizado vía `update-tracker.mjs`:
  `Aprobacion_Arquitectura=APROBADO`, `Estado=ARQUITECTURA_APROBADA`)
- Último agente: orion-architect
- Fecha última actualización: 2026-08-20
- Rama git: feature/REQ-015-webview-ui (activa del repo, sigue sin ser la rama de trabajo de
  REQ-017 — la propuesta `feature/REQ-017-completar-tareas-lote` de `arquitectura-017.md` §9
  todavía NO fue confirmada explícitamente por Johan en su respuesta; `orion-dev` debe confirmarla
  con él antes de asumirla, por `.claude/rules/git.md`)

## Log de transiciones
2026-08-20 | SPEC_APROBADO → ARQUITECTURA_APROBADA | orion-architect | Johan aprobó
`arquitectura-017.md` con 2 ajustes menores (ver "Decisiones tomadas" arriba). CSV actualizado vía
`update-tracker.mjs`. No corresponde `orion-security` (evaluado en `arquitectura-017.md` §8, sin
objeción de Johan). Handoff emitido: `@orion-dev REQ-017 |
arquitectura=workspace/adjuntos/REQ-017/propuestas/arquitectura-017.md`

## Decisiones tomadas
2026-08-20 | orion-dev | Implementación 1:1 con `arquitectura-017.md` §2.1/§2.2, sin desviaciones
de diseño. `core/resolution.py`: `import re` a nivel de módulo, `_TASK_BULK_ALL_RE`
(`\b(?:todas|todos)\b`, sin "todo" singular por el ajuste de Johan), `_TASK_BULK_COMPLETE_VERB_
STEMS`, `_is_bulk_complete_phrase()`, y el bloque de desambiguación insertado en `_try_task_tool()`
entre `create` y `_is_task_complete_phrase()` (ID explícito gana siempre sobre `bulk_all`/
`list_trigger`). `agents/tool_registry.py`: `import re` movido a nivel de módulo, `_TASK_ID_RE`
ampliado (`#N` suelto como segunda alternativa), `has_explicit_task_id()`, `_task_complete_invoke()`
con una sola línea modificada (extracción del match), `task_complete_all` como `ToolSpec` nuevo
GREEN con `_TASK_COMPLETE_ALL_LIMIT=20`. Ningún archivo fuera de los 2 previstos por la arquitectura
fue tocado (confirmado: `tasks/task_manager.py`, `core/reasoning_loop.py`, `channels/*`,
`core/security_manager.py`, `intent/intentions.py` sin diff) | Ver
`workspace/adjuntos/REQ-017/propuestas/desarrollo-log-017.md`.

2026-08-20 | orion-dev | Ajuste menor de datos de prueba (no de diseño): el texto que la
arquitectura sugería para CA-03 ("ya completé mi tarea") se verificó con ejecución real que NO
matchea `_is_task_complete_phrase()` hoy (`mentions_done` requiere el substring "completad", que
"completé" no contiene) — mismo tipo de imprecisión que ya había corregido `orion-baseline` en otras
filas de la tabla, no verificada para esta variante puntual. Se usó en su lugar "ya completé la
tarea" (literal exacto de `_TASK_COMPLETE_TRIGGERS`, confirmado que matchea antes de escribir el
test). No cambia ningún CA ni ninguna línea de código de producción | Ver
`tests/test_resolution.py::test_un_pendiente_sin_id_sin_cambios` y `desarrollo-log-017.md`.

2026-08-20 | orion-dev | `requirements.txt` no se tocó — el diff visible en `git status` es de
REQ-015/016, preexistente en el working tree compartido (confirmado con `git diff --stat
requirements.txt` antes de esta entrega, sin cambios de esta sesión). Consistente con
`arquitectura-017.md` §4 ("Ninguna" dependencia nueva) | Verificación directa con git.

## Verificación local
`python -m pytest tests/test_resolution.py tests/test_tool_registry.py --tb=short -q` → 35 passed
(17 tests nuevos: 8 en `test_resolution.py`, 9 en `test_tool_registry.py`, cobertura de los 12 CA de
SPEC-017.md documentada en `desarrollo-log-017.md`). `python -m pytest tests/test_reasoning_loop.py
--tb=short -q` → 9 passed (CA-11). `python -m pytest tests/ --tb=short -q` → 2 failed, 437 passed —
mismos 2 fallos preexistentes de `baseline-017.md` (`test_llm_provider.py`,
`ModuleNotFoundError: anthropic`, confirmados aislados), sin regresión nueva (CA-12).

## Estado actual
- Estado tracker: EN_PRUEBAS (CSV actualizado vía `update-tracker.mjs`)
- Último agente: orion-dev
- Fecha última actualización: 2026-08-20
- Rama git: feature/REQ-015-webview-ui (confirmada por Johan explícitamente para REQ-017 — NO se
  crea la rama `feature/REQ-017-completar-tareas-lote` que proponía `arquitectura-017.md` §9; se
  sigue trabajando sobre la misma rama compartida con REQ-015/016, sin commitear)

## Log de transiciones
2026-08-20 | ARQUITECTURA_APROBADA → EN_PRUEBAS | orion-dev | Implementación completa, DoD de
`orion-dev` cerrado (banner mostrado antes de escribir código, solo lo aprobado en arquitectura, sin
`except: pass` silencioso, sin prints de debug, sin dependencias nuevas, `desarrollo-log-017.md`
generado, NO se ejecutó `git commit`). CSV actualizado vía `update-tracker.mjs`: `Estado` →
EN_PRUEBAS. Handoff emitido: `@orion-tester REQ-017 |
dev-log=workspace/adjuntos/REQ-017/propuestas/desarrollo-log-017.md |
spec=workspace/adjuntos/REQ-017/spec/SPEC-017.md`

## Decisiones tomadas
2026-08-20 | orion-tester | 12/12 criterios PASS (no 11 — recuento directo de SPEC-017.md da 12
checkboxes, mismo recuento ya señalado por `orion-architect` en `arquitectura-017.md` §1; el
handoff de `orion-dev` decía "11 CA" por error de conteo, no afecta el resultado) | Ver
`workspace/adjuntos/REQ-017/pruebas/test-results-017.md`.

2026-08-20 | orion-tester | Verificación NO basada en confianza en el reporte de `orion-dev`: cada
criterio se probó por lectura directa de `core/resolution.py`/`agents/tool_registry.py` reales más
ejecución independiente (scripts ad hoc fuera de los tests de `orion-dev`) que ejercitan `resolve()`
end-to-end con `unittest.mock.patch` como spy sobre `execute_tool`. Confirmado con los textos
literales de `baseline-017.md`: las 3 variantes de "todas" que antes caían en `task_list` (bug
original que motivó el REQ) ahora disparan `task_complete_all`; la 4ª variante ("completa mis
tareas", sin "todas") correctamente sigue en `task_list` sin cambios. ID explícito + "todas" en el
mismo texto (`"de todas mis tareas, completa la #3"`) confirmado ganando sobre el lote. "todo"
singular (`"todo bien, completa la tarea"`) confirmado SIN disparar falso positivo (ajuste de Johan
funcionando). Los 3 canales (Desktop `user_id="default"`, Telegram `user_id="123"`, Discord
`user_id="discord_456"`) confirmados con `resolve()` real, cada uno completando solo sus propias
tareas | Ver `test-results-017.md`, sección "Verificaciones adicionales".

2026-08-20 | orion-tester | Tope de 20 tareas por invocación probado manualmente con 20 pendientes
mockeadas: completa las 20 y agrega nota de "puede haber más", sin corte abrupto ni excepción | Ver
`test-results-017.md`.

2026-08-20 | orion-tester | No-regresión confirmada con `git diff --stat`: `core/reasoning_loop.py`,
`channels/telegram_bot.py`, `channels/discord_bot.py`, `channels/gateway.py`, `tasks/task_manager.py`
sin ningún cambio. El único diff presente en `core/security_manager.py` es de REQ-015/016
(identificado por comentarios explícitos dentro del propio diff — `register_action("delete_task",
...)`/`"delete_conversation"`/`"delete_project"`), no de REQ-017 | Verificado con `git diff`.

2026-08-20 | orion-tester | Suite completa corrida de forma independiente: `2 failed, 437 passed` —
mismos 2 fallos preexistentes de `test_llm_provider.py` (`ModuleNotFoundError: anthropic`)
documentados desde `baseline-016.md`/`baseline-017.md`, sin regresión nueva. Confirmado también que
`tests/test_resolution.py` solo tuvo líneas agregadas (git diff), ningún test preexistente
modificado, y que `tests/test_reasoning_loop.py` tiene diff cero | Ver `test-results-017.md`.

## Estado actual
- Estado tracker: EN_QA (CSV actualizado vía `update-tracker.mjs`)
- Último agente: orion-tester
- Fecha última actualización: 2026-08-20
- Rama git: feature/REQ-015-webview-ui (sin cambios respecto a lo confirmado por `orion-dev`)

## Log de transiciones
2026-08-20 | EN_PRUEBAS → EN_QA | orion-tester | `test-results-017.md` generado en
`workspace/adjuntos/REQ-017/pruebas/`, 12/12 criterios PASS, sin regresiones. DoD de `orion-tester`
cerrado (compilación verificada, cada criterio de SPEC-017.md probado, tests existentes ejecutados
sin nuevos fallos). CSV actualizado vía `update-tracker.mjs`: `Estado` → EN_QA. Handoff emitido:
`@orion-qa REQ-017 | test-results=workspace/adjuntos/REQ-017/pruebas/test-results-017.md`

## Decisiones tomadas
2026-08-20 | orion-qa | Auditoría de seguridad re-verificada de forma independiente, no por
confianza en `orion-dev`/`orion-tester`: `git diff` propio sobre `core/resolution.py`,
`agents/tool_registry.py`, `core/security_manager.py`, `requirements.txt`,
`tests/test_resolution.py`, `tests/test_tool_registry.py`. Confirmado: `task_complete_all` (nuevo)
es `RiskLevel.GREEN` en el `ToolSpec` real, mismo nivel que `task_complete` individual, sin ningún
camino que pida confirmación de forma distinta — el bucle de `complete_task()` dentro de
`_task_complete_all_invoke()` ocurre DESPUÉS del gate único de `execute_tool()`, no antes ni en
paralelo. `git diff -- core/security_manager.py` re-confirmado: las 3 líneas de diff
(`delete_conversation`, `delete_task`, `delete_project`, las 3 YELLOW) son atribuibles a
REQ-015/REQ-016 por comentario explícito en el propio diff, cero líneas de REQ-017 — la
clasificación de riesgo existente (`delete_task` YELLOW, deny-list fail-closed de REQ-005) no fue
tocada. Sin `eval`/`exec`/`os.system`/`subprocess` en el regex/lógica nueva de "todas" (grep
dirigido sobre el diff, sin hallazgos). Sin secretos hardcodeados. Sin `except: pass` silencioso —
el código nuevo vive dentro del `try/except ActionDenied` preexistente de `_try_task_tool()`, que ya
maneja el error sin tragarlo. `requirements.txt` re-confirmado sin diff de REQ-017 (las 4 líneas
presentes son de REQ-015, con comentario explícito). Tests nuevos inspeccionados directamente
(no solo contados): son sustantivos, no placeholders (`test_task_complete_all_pasa_por_gate` envuelve
la función real de `security_manager`, `test_task_complete_all_es_green_sin_confirmar` usa trampa de
`AssertionError` sobre `input()`) | Ver `workspace/adjuntos/REQ-017/pruebas/qa-audit-017.md`.

2026-08-20 | orion-qa | Único hallazgo: `agents/tool_registry.py:225` (línea nueva de este REQ)
mide 102 caracteres, 2 por encima del límite de 100 de `python-style.md` — hallazgo cosmético, sin
impacto funcional ni de seguridad, no bloquea el veredicto. Registrado para corregir en la próxima
edición del archivo | Ver `qa-audit-017.md`, sección "Consistencia de código".

## Estado actual
- Estado tracker: EN_QA (sin cambio — CSV se actualiza a LISTO_PARA_COMMIT recién cuando Johan haga
  la prueba manual final y confirme OK; DoD de `orion-qa` no transiciona el tracker antes de esa
  confirmación)
- Último agente: orion-qa
- Fecha última actualización: 2026-08-20
- Rama git: feature/REQ-015-webview-ui (sin cambios respecto a lo confirmado por `orion-dev`)

## Log de transiciones
2026-08-20 | EN_QA (sin cambio de estado tracker) | orion-qa | `qa-audit-017.md` generado en
`workspace/adjuntos/REQ-017/pruebas/`, veredicto ✅ COMPLETADO. DoD de `orion-qa` cerrado (seguridad
revisada explícitamente, logging verificado, convenciones de código revisadas con 1 hallazgo menor
no bloqueante, `qa-audit-017.md` generado con veredicto explícito, NO se ejecutó `git commit`). Por
pedido explícito del orquestador (REQ-015/016 también pendientes de la misma prueba manual), la
solicitud de validación manual a Johan NO se emite desde esta sesión — se devuelve el resumen al
orquestador para que la consolide con las de REQ-015/016.
