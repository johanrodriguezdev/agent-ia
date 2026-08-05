# SPEC-007 — Bucle de razonamiento real con LLM (reasoning loop)

**Estado:** ✅ APROBADA
**Categoría:** CORE
**Tipo:** FEATURE_NUEVA
**Fecha:** 2026-08-04
**Aprobada:** 2026-08-04 | por el humano | ver "Confirmados por el humano" en la sección Asumidos

## Nota sobre numeración de criterios
Esta SPEC renumera desde **CA-01** en vez de continuar CA-18–CA-24 del diseño de
referencia de REQ-006. Motivo: SPEC-007 es un documento autocontenido que debe poder
leerse y auditarse sin abrir `arquitectura-006.md`; renumerar evita que un lector externo
confunda "CA-18" con "criterio 18 de esta spec". La trazabilidad se conserva en la tabla
de abajo.

| SPEC-007 | Diseño de referencia [B] (arquitectura-006.md) |
|---|---|
| CA-01 a CA-05, CA-08 | CA-18 a CA-23 (loop de razonamiento) |
| CA-11 | CA-24 (fix `_decompose()`) |
| CA-06, CA-07, CA-09, CA-10, CA-12, CA-13 | Nuevos — no existían en `[B]`, surgen de las respuestas del humano a las preguntas de clarificación y de la lectura del código real (`ai/llm_provider.py` sin tool-calling nativo) |
| CA-14, CA-15, CA-16 | Nuevos — surgen de la segunda ronda de clarificación: el humano decidió que el universo de tools del loop debe migrar los `AgentTool` existentes (`main.py`, `skill_manager.get_agent_tools()`) a `ToolSpec`, no limitarse a las 3 tools de `task_manager` ya registradas. |

## Objetivo
Reemplazar el `for` fijo de `core/base_agent.py::_DynamicAgentInstance.execute()` — que
prueba herramientas en orden hasta que una no lance `ActionDenied`, sin consultar ningún
LLM — por un bucle de razonamiento real: recibe el pedido, consulta al LLM con las
herramientas disponibles (`ToolSpec` de `agents/tool_registry.py`), ejecuta la elegida
exclusivamente vía `execute_tool()`, evalúa el resultado y decide si reintenta, encadena
otra herramienta o responde. Incluye también el fix del bug de `_decompose()` en
`core/orchestrator.py` (comparación por substring con la letra "y").

El humano confirmó explícitamente (segunda ronda de clarificación) que el loop debe tener
**al menos la misma capacidad** que el `for` actual: no alcanza con que el LLM razone si
solo puede elegir entre 3 herramientas de tareas — debe poder elegir entre todo lo que
`_DynamicAgentInstance` puede ejecutar hoy (abrir apps, volumen, capturas, etc.). Por eso
esta SPEC agrega la migración de los `AgentTool` existentes (`main.py`,
`skill_manager.get_agent_tools()`) a `ToolSpec`, como parte del mismo REQ.

## Alcance

### Incluye
- Nuevo módulo `core/reasoning_loop.py` que reemplaza el `for` de
  `_DynamicAgentInstance.execute()`.
- Conversión de la lista de `ToolSpec` del registro (`agents/tool_registry.py`) al formato
  de "tools" que exige la API de tool-calling del proveedor LLM activo.
- Extensión de `ai/llm_provider.py` para soportar tool-calling nativo **solo** en los
  proveedores con formato compatible OpenAI: `anthropic`, `deepseek`, `openai`. `gemini` y
  `ollama` quedan fuera de este REQ.
- Fallback explícito y determinista cuando el `ai_provider` activo no está en esa lista de
  tres (hoy sería el caso de cualquier config con `gemini`/`ollama`, no del `deepseek`
  actual, que sí entra en el alcance).
- Ejecución de toda tool elegida por el LLM exclusivamente vía
  `agents/tool_registry.py::execute_tool()` — nunca `ToolSpec.invoke` directo.
- Límite duro de 5 iteraciones del ciclo decide→ejecuta→evalúa.
- Manejo de `ActionDenied`: el loop para de inmediato e informa al usuario, sin
  reintentar con otra tool ni volver a consultar al LLM en esa invocación.
- Registro en `agent_context_manager` limitado al turno final (pedido + respuesta), sin
  entradas por cada iteración interna.
- El loop ofrece la misma lista de tools al LLM sin importar el canal (`DESKTOP`,
  `TELEGRAM`, `DISCORD`, `VOICE`) — el filtrado de qué se puede ejecutar sigue siendo
  responsabilidad exclusiva de `execute_tool()`/`security_manager` (`CHANNEL_ALLOWED_LEVELS`),
  sin lógica nueva de pre-filtrado por canal dentro del loop.
- Fix de `core/orchestrator.py::_decompose()` (CA-24 de `[B]`): comparación de palabra
  completa (`\b`, word boundary) en vez de substring, con la red de seguridad
  `all(len(p) > 3 for p in parts)` ya diseñada en `[B]`.
- **Migración de los `AgentTool` existentes a `ToolSpec`** (agregado en la segunda ronda de
  clarificación, decisión explícita del humano): se inventaría y envuelve como `ToolSpec`
  todo lo que hoy es alcanzable vía `orchestrator.register_tool()` en `main.py` —
  concretamente: (a) el `AgentTool` `"dispatcher"` registrado a mano
  (`main.py:31-35`, envuelve `router/dispatcher.py::dispatch_as_tool()`), y (b) cada
  `AgentTool` `skill_<intent>` que produce `skills/skill_manager.py::get_agent_tools()`
  (uno por cada intent de cada skill cargada en `skills/`). Se reutiliza `register_tool()`
  de `agents/tool_registry.py` **sin modificar ese módulo** — la migración es código nuevo
  que llama a una función ya existente, no un cambio de contrato.
- Retiro (eliminación o marcado explícito para retiro posterior — decisión de
  `orion-architect`, documentada) del registro `AgentTool`/`AgentOrchestrator.register_tool()`
  una vez migrado: `ToolSpec`/`agents/tool_registry.py` queda como el único registro de
  herramientas del sistema (CONFIRMADO 6, decisión explícita del humano).

### No incluye
- Tool-calling nativo para `gemini` u `ollama` (fuera de alcance explícito, decisión del
  humano).
- Mecanismo agnóstico de proveedor basado en JSON-en-texto (patrón que ya usa
  `ai/claude_brain.py` para `learn_command`/`save_memory`) como alternativa universal —
  descartado explícitamente por el humano para este REQ.
- Modelo `durableApprovalSatisfied` (aprobación recordada entre iteraciones o turnos para
  evitar reconfirmar la misma tool YELLOW) — descartado explícitamente, fuera de alcance.
- Cualquier cambio al contrato `ToolSpec` (`name`, `description`, `parameters_schema`,
  `risk_level`, `invoke`, `origin`) — se consume tal cual quedó de REQ-006.
- Cualquier cambio a `CHANNEL_ALLOWED_LEVELS`, `require_confirmation()`, o al fail-closed
  de `security_manager.py` — el gate de seguridad no se toca, solo se consume.
- Unificación de historiales entre `ai/claude_brain.py::_conversation_histories` y
  `agent_context_manager` — límite ya documentado y descartado en REQ-006, sigue fuera de
  alcance aquí.
- Modificar `skills/skill_manager.py` o `agents/tool_registry.py` — ambos se consumen tal
  cual (`get_agent_tools()`/`get_all_skills()` de uno, `register_tool()` del otro), sin
  tocar su código.
- Cualquier acción alcanzable **solo** por los otros caminos de ejecución que ya existían
  antes de REQ-006/007 (`os_integration/capabilities_router.py`,
  `agents/action_registry.py` vía Autopilot, `learning/routines_engine.py`,
  `learning/command_learning.py`) — esos caminos no pasan por
  `orchestrator.register_tool()` hoy, así que no son parte del universo de `AgentTool` que
  este REQ migra. Quedan fuera de alcance salvo que un REQ futuro los conecte.

## Módulos afectados

| Módulo | Qué cambia |
|--------|-----------|
| `core/reasoning_loop.py` (nuevo) | Bucle de razonamiento: arma la lista de tools desde `agents/tool_registry.py`, llama al LLM, ejecuta la tool elegida vía `execute_tool()`, evalúa resultado, decide continuar/parar, hasta 5 iteraciones o `ActionDenied`. |
| `core/base_agent.py` | `_DynamicAgentInstance.execute()` deja de iterar `self.tools: List[AgentTool]` en un `for` — delega a `core/reasoning_loop.py`. La clase `AgentTool` y el registro basado en ella quedan obsoletos tras la migración (CA-14, CONFIRMADO 6) — `orion-architect` decide si se eliminan en este REQ o se marcan para retiro posterior, documentando cuál. |
| `ai/llm_provider.py` | `generate_response()` gana un parámetro opcional de tools; `_ask_anthropic()` envía `tools=` a la API de Anthropic y parsea bloques `tool_use` de la respuesta (hoy solo lee `response.content[0].text`, que además rompería con `IndexError` si la respuesta es solo un tool call). `_ask_deepseek()`/`_ask_openai()` (ambos vía SDK `openai`) ganan soporte de `tools=`/`tool_choice` y parseo de `tool_calls`. `_ask_gemini()`/`_ask_ollama()` no se tocan. |
| `core/orchestrator.py` | `_decompose()` (líneas 91-102): fix de comparación por palabra completa (`\b`) + red de seguridad de longitud mínima por parte, según diseño `[B]`/CA-24. `AgentOrchestrator.register_tool()`/`self._tools` (líneas 15, 21-23) quedan obsoletos junto con `AgentTool` (CONFIRMADO 6) — misma decisión de retiro que `core/base_agent.py`. |
| `agents/tool_registry.py` | **Sin cambios de código.** Se consume `register_tool()`/`list_tool_names()`/`get_tool()`/`execute_tool()` tal cual existen desde REQ-006 — la migración de `AgentTool` llama a `register_tool()` desde fuera, no modifica el módulo. |
| `skills/skill_manager.py` | **Sin cambios de código.** Se consume `get_agent_tools()` (o `get_all_skills()` + `get_intents()`/`extract_params()`, según decida arquitectura) para inventariar qué migrar — el humano pidió explícitamente no modificar este módulo. |
| `main.py` | Punto de wiring a definir por `orion-architect`: hoy registra el `AgentTool` `"dispatcher"` (líneas 31-35) y cada tool de `skill_manager.get_agent_tools()` (líneas 37-38) en `orchestrator.register_tool()`. Ese registro pasa a construir `ToolSpec` equivalentes vía `agents/tool_registry.py::register_tool()` en su lugar (o además, si arquitectura decide mantener el camino legacy en paralelo durante una transición — a definir, ver Asumidos). |
| `core/security_manager.py`, `core/confirmation.py` | Sin cambios — se consumen tal cual (gate de REQ-005/REQ-006 no se toca). Los `risk_level` de los `ToolSpec` migrados se derivan de clasificaciones ya registradas por `_register_intent_actions()`/`_register_action_registry_actions()` (REQ-005), no se inventan nuevas. |
| `core/agent_context.py` / `agent_context_manager` | Sin cambios de contrato — el loop lo llama con la misma disciplina que ya usa `AgentOrchestrator._execute_single_agent()` hoy (un `update_context` por rol), no una llamada por iteración interna. |
| `config.json` | Sin cambios de esquema — se lee `ai_provider` (ya existente) para decidir si el loop activa tool-calling nativo. |

## Comportamiento actual vs deseado

| Actual | Deseado |
|--------|---------|
| `_DynamicAgentInstance.execute()` prueba cada `AgentTool` en un `for` fijo hasta que una no lance excepción ni denegación — sin LLM, sin evaluar si el resultado realmente responde al pedido. | `core/reasoning_loop.py` consulta al LLM con la lista de `ToolSpec` disponibles; el LLM elige, el loop ejecuta vía `execute_tool()`, evalúa el resultado y el LLM decide reintentar, encadenar otra tool o responder — hasta 5 iteraciones. |
| `ai/llm_provider.py::generate_response()` no soporta tool-calling en ningún proveedor — cualquier "elección de herramienta" hoy es responsabilidad de código Python, no del LLM. | `generate_response()` soporta tool-calling nativo en `anthropic`/`deepseek`/`openai`; con otro proveedor activo, cae a una llamada sin herramientas (ver Asumidos). |
| Una denegación (`ActionDenied`) durante el `for` de `_DynamicAgentInstance` se traga silenciosamente (`continue`) y se prueba la siguiente tool. | Una `ActionDenied` durante el loop de razonamiento **para el loop de inmediato** e informa al usuario — no se intenta otra tool ni se vuelve a consultar al LLM en esa invocación. |
| `core/orchestrator.py::_decompose()` rompe con cualquier texto que contenga la letra "y" como substring (ej. "hoy", "voy", "muy"), generando sub-tareas espurias. | `_decompose()` solo separa por la palabra completa " y " (word boundary), con red de seguridad que descarta partes de 3 caracteres o menos. |
| El universo de herramientas que `_DynamicAgentInstance` puede usar hoy son los `AgentTool` registrados en `main.py` (el `"dispatcher"` catch-all + uno por cada intent de cada skill vía `get_agent_tools()`) — capacidad amplia, pero probada sin LLM real (el `for` no razona). | El loop de razonamiento tiene la **misma o mayor** capacidad: todos esos `AgentTool` se migran a `ToolSpec` y quedan disponibles para que el LLM los elija con criterio, no solo en orden fijo. |

## Criterios de aceptación

- [ ] **CA-01** — `_DynamicAgentInstance.execute()` (`core/base_agent.py`) ya no contiene el
  `for tool in self.tools` que prueba herramientas en orden fijo; delega la ejecución a
  `core/reasoning_loop.py`.
- [ ] **CA-02** — Existe una función en `core/reasoning_loop.py` que convierte la lista de
  `ToolSpec` (`agents/tool_registry.py::list_tool_names()`/`get_tool()`) al formato de
  tools del proveedor activo, reusando `parameters_schema` de cada `ToolSpec` sin
  reescribir el JSON Schema a mano.
- [ ] **CA-03** — `ai/llm_provider.py::generate_response()` acepta una lista de tools
  opcional y la reenvía al proveedor activo únicamente si este es `anthropic`, `deepseek`
  u `openai`. Con cualquier otro proveedor activo (`gemini`, `ollama`, o uno no
  reconocido), `generate_response()` ignora el parámetro de tools y responde en modo
  texto plano, sin lanzar excepción.
- [ ] **CA-04** — `_ask_anthropic()` envía `tools=` a la API de Anthropic cuando se le
  pasan tools, y parsea correctamente una respuesta que contiene uno o más bloques
  `tool_use` (no asume que `response.content[0]` es siempre texto).
- [ ] **CA-05** — `_ask_deepseek()`/`_ask_openai()` envían `tools=`/`tool_choice` al SDK
  `openai` cuando se les pasan tools, y parsean `tool_calls` de la respuesta.
- [ ] **CA-06** — Toda tool elegida por el LLM se ejecuta exclusivamente vía
  `agents/tool_registry.py::execute_tool(name, params, channel, user_id)` — ningún camino
  de `core/reasoning_loop.py` llama `ToolSpec.invoke` directo (verificable por lectura
  estática/grep del módulo).
- [ ] **CA-07** — El loop nunca ejecuta más de 5 ciclos de "decide tool → ejecuta → mira
  resultado → decide de nuevo" para una misma invocación. Al alcanzar el ciclo 5 sin que
  el LLM haya devuelto una respuesta final, el loop cierra devolviendo un mensaje que dice
  explícitamente que no pudo completar la tarea en el límite de intentos (no se cuelga, no
  itera indefinidamente).
- [ ] **CA-08** — Si `execute_tool()` lanza `ActionDenied` en cualquier iteración, el loop
  retorna de inmediato un mensaje informando la denegación al usuario — no ejecuta otra
  tool, no vuelve a llamar al LLM, no continúa el ciclo.
- [ ] **CA-09** — No existe en `core/reasoning_loop.py` ningún mecanismo de caché o
  recuerdo de aprobaciones entre iteraciones o entre turnos de conversación (sin
  `durableApprovalSatisfied` ni equivalente) — cada intento de tool YELLOW/RED pasa
  siempre por `require_confirmation()` vía `execute_tool()`, sin excepción.
- [ ] **CA-10** — Por cada invocación completa del loop, `agent_context_manager` recibe
  exactamente una entrada `role="user"` (el pedido original) y una entrada
  `role="assistant"` (la respuesta final) — ninguna entrada adicional por iteración
  interna, tool-call o resultado intermedio.
- [ ] **CA-11** — La lista de tools que el loop ofrece al LLM es idéntica sin importar el
  `channel` recibido (`DESKTOP`, `TELEGRAM`, `DISCORD`, `VOICE`) — `core/reasoning_loop.py`
  no filtra tools por `risk_level` ni por `CHANNEL_ALLOWED_LEVELS`; solo `execute_tool()`
  decide si la ejecución se permite.
- [ ] **CA-12** — `core/orchestrator.py::_decompose()` separa sub-tareas por la palabra
  completa " y " (word boundary), no por substring: un texto como "voy a la tienda y
  compro pan" se descompone en dos partes ("voy a la tienda", "compro pan"); un texto
  como "hoy quiero revisar mis tareas" **no** se descompone (la "y" de "hoy" no dispara el
  split). Incluye la red de seguridad `all(len(p) > 3 for p in parts)` — si alguna parte
  resultante tiene 3 caracteres o menos, se descarta el split y se trata el texto como una
  sola tarea.
- [ ] **CA-13** — `python -m py_compile` limpio en todos los archivos modificados/creados;
  la suite `pytest tests/ --tb=short` completa sigue en verde (sin nuevos fallos) además de
  los tests nuevos que cubran CA-01 a CA-17.
- [ ] **CA-14** — Todo `AgentTool` alcanzable hoy vía `orchestrator.register_tool()` en
  `main.py` tiene un `ToolSpec` equivalente registrado en `agents/tool_registry.py` antes
  de que `core/reasoning_loop.py` quede activo: el `AgentTool` `"dispatcher"`
  (`main.py:31-35`) y cada `AgentTool` `skill_<intent>` que produce
  `skill_manager.get_agent_tools()` (uno por cada intent de cada skill cargada). Ninguno se
  pierde silenciosamente — si alguno se decide excluir deliberadamente, queda documentado
  con el motivo (no una omisión). `core/reasoning_loop.py` lee su universo de tools
  exclusivamente del registro de `agents/tool_registry.py` (`list_tool_names()`/`get_tool()`),
  no de `self.tools: List[AgentTool]`.
- [ ] **CA-15** — El `risk_level` de cada `ToolSpec` migrado de un intent de skill se
  deriva de la clasificación ya existente en `security_manager` (`classify_action(intent)`,
  registrada por `_register_intent_actions()`/`_register_action_registry_actions()` en
  REQ-005) — no se declara un nivel nuevo o distinto para el mismo intent bajo otro nombre.
  Un test verifica que, para una muestra de intents ya clasificados (ej. `OPEN_APP`=GREEN,
  `CLOSE_APP`=YELLOW), el `ToolSpec` migrado correspondiente tiene el mismo `risk_level`.
- [ ] **CA-16** — Cada `ToolSpec` migrado de una skill construye los parámetros reales de
  ejecución llamando a `skill.extract_params(intent, text)` **antes** de `skill.execute(intent, params)`
  dentro de su función `invoke` — no reutiliza el patrón actual de `get_agent_tools()` /
  `_make_gated_tool_fn()`, que pasa `params` sin extraer entidades y además se auto-gatea
  llamando a `security_manager.require_confirmation()` directamente dentro de `invoke`
  (duplicaría el gate que ya hace `execute_tool()`, y devolvería el string
  `"⛔ Acción no autorizada."` como si fuera una respuesta exitosa — el mismo bug de forma
  que CA-09/H7 ya corrigió para el resto del sistema). El `invoke` migrado no debe volver a
  llamar `require_confirmation()` por su cuenta.
- [ ] **CA-17** — Tras la migración, `main.py` ya no llama a
  `orchestrator.register_tool(AgentTool(...))` ni itera `skill_manager.get_agent_tools()`
  para registrar `AgentTool` — todo el registro de herramientas de `main.py` pasa por
  `agents/tool_registry.py::register_tool()` con `ToolSpec`. La clase `AgentTool`
  (`core/base_agent.py`) y `AgentOrchestrator.register_tool()`/`self._tools`
  (`core/orchestrator.py`) quedan explícitamente documentados como obsoletos en el
  desarrollo-log del REQ — eliminados en este REQ o marcados para retiro posterior, pero
  nunca dejados como ambigüedad sin registrar (CONFIRMADO 6).

## Casos borde
- El LLM elige una tool que no existe en el registro (`get_tool()` devuelve `None`):
  `execute_tool()` ya levanta `ActionDenied("tool no registrado")` (comportamiento
  existente de REQ-006, sin cambios) — el loop lo trata igual que cualquier otra
  `ActionDenied` (CA-08): para e informa.
- El LLM no elige ninguna tool y responde directo en la primera iteración: el loop debe
  aceptar esa respuesta como final sin forzar ninguna iteración adicional (no confundir
  "el LLM no quiso usar herramientas" con "hay que seguir insistiendo").
- El proveedor activo cambia entre invocaciones (el usuario edita `config.json` en
  caliente): el loop debe leer `ai_provider` en cada invocación, no cachear la decisión de
  "tools sí/no" de una ejecución anterior.
- Respuesta del LLM con tool call malformado (JSON de parámetros inválido, o que no
  cumple `parameters_schema`): el loop no debe crashear — debe tratarlo como un resultado
  de iteración fallido y permitir que el LLM lo intente de nuevo (dentro del límite de 5),
  o cerrar con mensaje de error legible si se agotan los intentos.
- Task compuesta ("recuérdame comprar pan y avísame en 1 hora"): puede requerir más de una
  tool en cadena (`task_create` dos veces, por ejemplo) — el loop debe permitir encadenar
  sin necesitar que `_decompose()` la parta primero; ambos mecanismos (loop y
  `_decompose()`) son independientes y no deben pisarse.
- `_decompose()` con texto que solo tiene una "y" pegada a otra palabra sin espacios
  (ej. "muyyy cansado"): la red de seguridad de longitud mínima evita splits espurios de
  fragmentos cortos, pero el fix principal es el `\b` de palabra completa, no la longitud
  — ambos deben probarse por separado.
- Un intent de skill sin clasificación registrada en `security_manager` (`classify_action()`
  devuelve `None`): `register_tool()` ya llama a `security_manager.register_action()`, que
  exige un `risk_level` no-`None` como argumento — si no hay clasificación previa que
  reutilizar (CA-15), la migración de ese intent puntual debe fallar de forma visible en
  tiempo de carga (no registrar el tool en silencio con un nivel inventado), para que quede
  detectado antes de que un usuario lo sufra.
- Una skill cuyo `extract_params(intent, text)` devuelve `{}` (implementación por defecto
  de `BaseSkill`, no sobrescrita): el `ToolSpec` migrado igual debe registrarse y ser
  invocable — el comportamiento de "no extraje nada" ya existe hoy y no es un caso nuevo
  que este REQ deba resolver, solo no debe crashear el `invoke`.

## Asumidos

### Confirmados por el humano (segunda ronda de clarificación — ya no son asumidos abiertos)
- **CONFIRMADO 1** (antes ASUMIDO 1) — Cuando el `ai_provider` activo no soporta
  tool-calling nativo en el alcance de este REQ (`gemini`/`ollama`/no reconocido), el loop
  **degrada silenciosamente a una llamada sin herramientas** (responde con el LLM en modo
  texto plano, sin ofrecer tools, sin aviso explícito al usuario). Confirmado tal cual por
  el humano.
- **CONFIRMADO 2** (antes ASUMIDO 3) — El límite de 5 iteraciones cuenta **llamadas al
  LLM en total, incluida la llamada final que da la respuesta** — no ejecuciones de tools
  por separado. Confirmado tal cual por el humano.
- **CONFIRMADO 3** (antes ASUMIDO 4) — El fix de `_decompose()` (CA-12) no modifica
  `MAX_CHAIN_DEPTH` (5, `core/orchestrator.py:9`) ni la lógica de `_execute_agent_chain()`
  — solo corrige qué cuenta como separador válido. Confirmado tal cual por el humano.
- **RESUELTO** (antes ASUMIDO 2) — El universo de tools del loop **sí** incluye la
  migración completa de `AgentTool` → `ToolSpec` (el `"dispatcher"` catch-all de `main.py`
  más todo lo de `skill_manager.get_agent_tools()`), no se limita a las 3 tools de
  `task_manager` ya existentes. Ya no es un asumido: es alcance confirmado de este REQ
  (ver CA-14 a CA-16 arriba). Motivo explícito del humano: un loop con menos capacidad que
  el `for` actual no resuelve el problema que motivó el REQ.

### Confirmados por el humano (tercera ronda — aprobación final de la SPEC)
- **CONFIRMADO 4** (antes ASUMIDO A) — El nombre (`ToolSpec.name`) de cada tool migrado de
  un intent de skill reutiliza el mismo `action_name` ya clasificado por
  `security_manager` (el valor del `Intent`, ej. `"OPEN_APP"`), **no** el prefijo
  `skill_<intent_lower>` que usa el `AgentTool` de `get_agent_tools()` hoy. Confirmado tal
  cual por el humano.
- **CONFIRMADO 5** (antes ASUMIDO B) — El `AgentTool` catch-all `"dispatcher"`
  (`dispatch_as_tool`, `main.py:31-35`) también se migra a un `ToolSpec`, con
  `risk_level=GREEN` (el gate real ocurre dentro de `dispatch()` por la acción que
  finalmente resuelve, igual que ya rige para `task_create`/`task_list`/`task_complete`
  desde REQ-006), como fallback genérico — no se elimina. Confirmado tal cual por el
  humano.
- **CONFIRMADO 6** (antes ASUMIDO C) — La migración es un **reemplazo completo**, no una
  coexistencia temporal: `ToolSpec`/`agents/tool_registry.py` queda como el único registro
  de herramientas del sistema tras este REQ. El registro `AgentTool`/
  `orchestrator.register_tool()` (`core/base_agent.py::AgentTool`,
  `core/orchestrator.py::AgentOrchestrator.register_tool()`/`self._tools`) **queda
  obsoleto** una vez migrado — consistente con el principio ya aplicado en REQ-006 de "un
  solo registro que cualquier canal puede invocar igual". Confirmado explícitamente por el
  humano. Implicación para `orion-architect`: debe decidir si `AgentTool`/
  `AgentOrchestrator.register_tool()`/`self._tools` se eliminan en este mismo REQ o quedan
  como código muerto marcado para retiro en un REQ de limpieza posterior — cualquiera de
  las dos opciones es aceptable siempre que quede documentado explícitamente cuál se
  eligió y por qué (no debe quedar como un olvido).

## Riesgos activos (heredados del contexto, no resueltos por esta SPEC)
- Latencia/costo adicional por llamada a LLM en cada decisión de tool, hasta 5 llamadas
  por invocación del loop — no se define en esta SPEC ningún presupuesto de costo ni
  timeout de red; queda para arquitectura si hace falta acotarlo.
- Un usuario con varias tools YELLOW en la misma conversación reconfirma cada vez (sin
  `durableApprovalSatisfied`) — aceptado explícitamente como comportamiento esperado para
  este REQ, no un defecto a corregir aquí.
- La migración de `AgentTool` → `ToolSpec` (CA-14 a CA-16) amplía el alcance real de
  `orion-dev` más allá de "solo construir el loop" — ahora también toca el inventario
  completo de skills cargadas dinámicamente en `skills/`. Riesgo de que alguna skill
  quede fuera de la migración sin que se note hasta que un usuario la pida por el loop y
  no esté disponible; mitigación sugerida para pruebas: un test que compare
  `len(skill_manager.get_agent_tools()) + 1` (el `+1` del `"dispatcher"`) contra la
  cantidad de `ToolSpec` migrados, para detectar drift si se agrega una skill nueva más
  adelante y alguien olvida re-ejecutar la migración.
