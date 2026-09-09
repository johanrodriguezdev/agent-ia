# SPEC-027 — Bucle de razonamiento de nivel agente

**Estado:** ⏸️ ESPERANDO VALIDACIÓN
**Categoría:** CORE
**Tipo:** MEJORA
**Fecha:** 2026-09-08

## Objetivo
`core/reasoning_loop.py` es hoy un encadenador de herramientas con techo bajo: re-serializa
el historial de tools como texto plano, ejecuta una sola tool por vuelta y se queda sin aire
a la cuarta. Eso hace fallar tres de las siete capacidades auditadas —razonamiento complejo,
investigación multi-fuente y autonomía multi-paso— por la MISMA causa raíz. Este REQ lo
convierte en un bucle de agente real: conversación nativa `tool_use`/`tool_result` con el
proveedor, presupuesto de llamadas proporcional a lo que el usuario pidió, y ejecución de
todas las herramientas que el modelo pida en una vuelta.

## Alcance

- Incluye:
  - **Cambio 1 — Protocolo nativo.** El historial de herramientas viaja al modelo como
    conversación multi-turno nativa (`tool_use`/`tool_result` en Anthropic; `assistant` con
    `tool_calls` + `role="tool"` en la familia del SDK `openai`), en lugar del mensaje `user`
    autocontenido que arma hoy `_build_prompt()`. Son **2 adaptadores reales**: Anthropic, y
    la familia `openai`/`deepseek`/`openrouter` que comparte SDK.
  - **Cambio 2 — Presupuesto variable.** `MAX_LLM_CALLS = 5` fijo pasa a ser un presupuesto
    que depende del modo estratégico activo (`core/composer_modes.py`, REQ-026) y del canal.
  - **Cambio 3 — Todas las tool calls de la vuelta.** `response.tool_calls[0]` deja de
    descartar el resto: se ejecutan todas, en secuencia, cada una por `execute_tool()` con su
    propio gate y su propia confirmación.
  - **Cambio 4 — Llamada de cierre sin herramientas.** Consecuencia directa del cambio 2: con
    presupuestos de 25 o 40, agotarlos y devolver el mensaje enlatado de hoy tira a la basura
    39 vueltas de trabajo. Se agrega una última llamada al modelo sin herramientas para que
    cierre con lo que ya reunió. El mismo mecanismo sirve para el cierre tras una denegación.
  - **Cambio 5 — Transversal.** `max_tokens=1500` de los 5 puntos de `ai/llm_provider.py`
    pasa a una constante única con un valor mayor.
  - Actualizar `ai/claude_brain.py` solo en su tope de rondas (`MAX_TOOL_ROUNDS`).

- No incluye:
  - **Herramientas de repositorio y código** (leer/editar/buscar archivos, git, diffs). Es la
    capacidad 2 de las 7 auditadas y va en un REQ aparte y POSTERIOR — decisión de Johan
    registrada en el contexto. Este REQ no crea ninguna herramienta nueva.
  - Encender MCP, ni agregar una herramienta HTTP genérica (capacidad 5).
  - Migrar `ai/claude_brain.py` al protocolo nativo (su contrato es otro: historial de sesión
    por usuario, imágenes y bloques JSON de aprendizaje). Ver `## PENDIENTE DE JOHAN`.
  - Ejecutar las tool calls de una vuelta **en paralelo**. Es secuencial: una confirmación
    humana concurrente con otra ejecución es exactamente lo que el gate no debe permitir.
  - Corte del turno por costo o tiempo real (descartado por Johan: más piezas nuevas de las
    necesarias; `core/cancelacion.py` ya cubre la fuga).
  - Cualquier cambio al modelo de seguridad de REQ-005/REQ-006/REQ-019: niveles, canales,
    `CHANNEL_ALLOWED_LEVELS`, `CHANNEL_ACTION_EXCEPTIONS`, overrides.
  - Persistir el historial `tool_use`/`tool_result` entre turnos. `agent_context` sigue
    guardando un par user/assistant por invocación de `run()` (REQ-007/CA-10).
  - Cambios de UI, de catálogo de modos visible, o de `ui/webview/bridge.py`.
  - Streaming del texto intermedio de las vueltas con herramientas.

## Módulos afectados

- `core/reasoning_loop.py` — el grueso del REQ. `_build_prompt()` deja de ser el único
  constructor de mensajes y pasa a ser el aplanador de degradación (CA-07); el bucle arma un
  historial neutral de tool calls/resultados; `MAX_LLM_CALLS` pasa a ser el presupuesto por
  defecto y aparece la resolución de presupuesto por modo y canal; el `response.tool_calls[0]`
  de la línea 317 pasa a recorrer toda la lista; se agrega la llamada de cierre sin
  herramientas.
- `ai/llm_provider.py` — `_ask_anthropic` (hoy `:568-570` envuelve TODO como
  `{"type":"text"}`), `_ask_openai` (`:711-713` pasa `content` crudo), `_ask_deepseek` y
  `_ask_openrouter` traducen el historial neutral a su protocolo nativo;
  `_llamada_en_streaming()` recibe los mensajes ya traducidos; `_ask_gemini`/`_ask_ollama`
  reciben el historial aplanado a texto; los 5 `max_tokens=1500` (`:595`, `:756`, `:834`,
  `:867`, `:974`) pasan a una constante.
- `core/composer_modes.py` — `ModoComposer` gana el presupuesto de llamadas, en el mismo
  catálogo donde ya viven `tool_names` y `tarea`. Un segundo mapeo modo→presupuesto en otro
  módulo sería exactamente la duplicación que este archivo existe para evitar.
- `ai/claude_brain.py` — `MAX_TOOL_ROUNDS` 3 → 5. Nada más: no conoce modos ni los recibe.
- `tests/test_reasoning_loop.py`, `tests/test_llm_provider.py`, `tests/test_claude_brain.py`,
  `tests/test_composer_modes.py` — cobertura nueva y actualización de los tests que fijan
  `MAX_LLM_CALLS`, CA-07 y CA-08 de REQ-007.

**Módulos que este REQ NO debe tocar** (y es un criterio de aceptación, no un comentario):
`core/resolution.py`, `ui/webview/bridge.py`, `tests/modelo_falso.py`,
`agents/tool_registry.py`, `core/security_manager.py`, `core/cancelacion.py`.

La solución técnica exacta —dónde vive la representación neutral, cómo se llama la función
traductora, si el aplanado de degradación queda en `_build_prompt()` o se muda— la define
`orion-architect`. Esta SPEC fija el comportamiento observable.

## Comportamiento actual vs deseado

| Actual | Deseado |
|--------|---------|
| `_build_prompt()` re-serializa el historial de tools como texto plano en un único mensaje `user` autocontenido (`core/reasoning_loop.py:192`) | El historial viaja como conversación multi-turno nativa del proveedor, correlacionada por el `id` de cada tool call |
| `_ask_anthropic` envuelve todo mensaje como `[{"type":"text","text":...}]` (`:568-570`) | Traduce el historial neutral a bloques `tool_use` (assistant) y `tool_result` (user) |
| `_ask_openai`/`_ask_deepseek`/`_ask_openrouter` pasan `content` crudo y no contemplan `role="tool"` | Traducen a `assistant` con `tool_calls` + un mensaje `{"role":"tool","tool_call_id",...}` por resultado |
| El `id` de `ToolCallRequest` se parsea y se descarta | El `id` es lo que correlaciona la llamada con su resultado |
| `MAX_LLM_CALLS = 5` fijo, respuesta final incluida → máximo 4 herramientas por turno | Presupuesto por modo y canal: 8 sin modo, 40 en Código, 25 en Investigación, 12 en Flujos, 10 en Tareas, 5 en canales que no son escritorio |
| `call = response.tool_calls[0]` — el resto se descarta (`:317`) | Se ejecutan todas las de la vuelta, en orden, cada una por `execute_tool()` |
| Agotar el presupuesto devuelve "No pude completar la tarea en el número de intentos disponibles" y descarta todo lo reunido | Una última llamada sin herramientas para que el modelo cierre con lo que tiene; el enlatado queda como fallback |
| Una denegación corta el turno con un mensaje fijo, sin contar lo que ya se había ejecutado en esa vuelta | Corta la secuencia y hace una llamada de cierre sin herramientas para redactar la respuesta; el enlatado queda como fallback |
| `max_tokens=1500` repetido en 5 puntos | Una constante única, 4096, usada en los 5 |
| `ai/claude_brain.py::MAX_TOOL_ROUNDS = 3` → 2 herramientas útiles por mensaje de Telegram/Discord | 5 rondas |

---

## Presupuesto: los números y por qué

El presupuesto cuenta **llamadas al modelo**, no herramientas ejecutadas. Fundamentos:

1. Es lo que ya significa la constante (`for call_number in range(1, MAX_LLM_CALLS + 1)`
   envuelve la llamada al modelo, no la ejecución de la tool).
2. El costo y la latencia los pone la llamada al modelo. Una `task_list` local no cuesta nada.
3. Contar herramientas castigaría exactamente la conducta que premia el cambio 3: un modelo
   que pide 4 lecturas juntas gastaría 4 y uno que las pide de a una gastaría lo mismo pero
   con 4 vueltas de latencia. Sería un incentivo al revés.

| Situación | Presupuesto | Herramientas útiles | Justificación |
|---|---|---|---|
| Escritorio, sin modo | **8** | 7 | Hoy 5 deja 4 herramientas, y una cadena normal ("buscá → leé → resumí → respondé") ya son 4: cualquier callejón sin salida (una tool que falla, un reintento con otros parámetros) revienta el techo antes de terminar. 8 deja margen para dos correcciones sin que un "hola" quede habilitado a gastar un presupuesto de investigación. |
| Escritorio, modo **Investigación** | **25** | 24 | Investigar de verdad es 1 búsqueda + N lecturas + reformular + síntesis. Con 6 a 10 fuentes leídas y una o dos búsquedas reformuladas se llega a ~20; por debajo de eso el modelo tiene que elegir entre profundidad y amplitud. Por encima de ~30 el rendimiento marginal cae solo: la ventana de contexto se llena con los `web_read` antes que el presupuesto. |
| Escritorio, modo **Código/script** | **40** | 39 | Un ciclo de código es escribir → ejecutar → leer el error → corregir → ejecutar: 3 o más herramientas por iteración. 40 son ~13 iteraciones, que es lo que separa "te ejecuto un snippet" de "te dejo el script andando". Es además el presupuesto que va a heredar el REQ posterior de repositorios (editar un repo son ~20 pasos): fijarlo acá evita volver a tocarlo. |
| Escritorio, modo **Nodos/flujos** | **12** | 11 | Un flujo se lista, se ejecuta, se reanuda o se cancela, y cada paso puede encadenar. Más que un chat suelto, pero acotado: no es una búsqueda abierta. |
| Escritorio, modo **Tareas** | **10** | 9 | Crear/listar/completar son operaciones cortas y de resultado inmediato. Apenas por encima del default porque activar el modo es señal de que viene más de una operación seguida. |
| **Cualquier canal ≠ `DESKTOP`** | **5 (techo)** | 4 | Es el valor de hoy: cero regresión. En voz un turno largo es silencio que nadie puede cortar —el botón de detener es de escritorio— y encima `CHANNEL_ALLOWED_LEVELS` solo deja verdes ahí, así que una cadena larga sirve poco. Es además la regla fail-closed: un canal en el que nadie pensó (`API`, `EMAIL`, `UNKNOWN`) hereda el comportamiento de hoy, nunca el 40. |
| Telegram/Discord (`ai/claude_brain.py`) | **5 rondas** | 5 | Bucle aparte, constante aparte (`MAX_TOOL_ROUNDS`, hoy 3 = 3 herramientas). Sube a 5 por el mismo criterio del techo de canal remoto. Ojo con la semántica: allí la constante cuenta **rondas de herramientas**, y la llamada de cierre ya existe y va aparte — no es el mismo número que `MAX_LLM_CALLS`. |

Regla efectiva: `presupuesto = min(techo_del_canal, presupuesto_del_modo_o_default)`.
Un `modo` solo llega desde el composer de escritorio (`Bridge.send_message()`), así que en la
práctica el `min()` nunca recorta nada — está para que sea estructuralmente imposible que un
canal remoto termine con 40 llamadas si mañana alguien propaga un modo desde otro lado.

---

## Criterios de aceptación

### A. Protocolo nativo `tool_use`/`tool_result`

- [ ] **CA-01** — Tras una vuelta que ejecutó herramientas, la lista `messages` que recibe
  `generate_response()` en la vuelta siguiente contiene, además del mensaje `user` original,
  una entrada que representa las tool calls pedidas y otra que representa sus resultados,
  correlacionadas por el `id` de cada `ToolCallRequest`.
  *Verificación:* pytest. `generate_response` mockeado; la 1ª respuesta es un `LLMToolResponse`
  con `ToolCallRequest(id="tc_1", ...)`; assert de que en la 2ª llamada `messages` tiene ≥3
  entradas y `"tc_1"` aparece en las dos nuevas.

- [ ] **CA-02** — El historial que produce `core/reasoning_loop.py` es **neutral respecto del
  proveedor**: no contiene claves nativas de Anthropic (`"tool_use"`, `"tool_result"`,
  `"input_schema"`) ni de la familia OpenAI (`"tool_calls"`, `"tool_call_id"`,
  `role="tool"`). La traducción ocurre exclusivamente en `ai/llm_provider.py`.
  *Verificación:* pytest, mismo patrón de grep estático que
  `test_ca06_reasoning_loop_nunca_llama_invoke_directo` + assert sobre la estructura de
  `messages` capturada. *Motivo:* `generate_response()` puede cambiar de proveedor a mitad de
  turno (cooldown + cadena de respaldo, REQ-022); si el bucle emitiera forma nativa de un
  proveedor, el respaldo recibiría un historial que no entiende.

- [ ] **CA-03** — `_ask_anthropic` traduce ese historial a bloques nativos: un mensaje
  `assistant` con uno o más `{"type":"tool_use","id","name","input"}` y un mensaje `user` con
  los `{"type":"tool_result","tool_use_id","content"}` correspondientes.
  *Verificación:* pytest con el cliente `anthropic` mockeado; assert sobre el `messages=` con
  que se llama `client.messages.create`.

- [ ] **CA-04** — `_ask_openai`, `_ask_deepseek` y `_ask_openrouter` traducen el mismo
  historial al protocolo del SDK `openai`: un `assistant` con
  `tool_calls=[{"id","type":"function","function":{"name","arguments"}}]` y un mensaje
  `{"role":"tool","tool_call_id","content"}` por resultado.
  *Verificación:* pytest parametrizado sobre los 3 adaptadores, con `OpenAI` mockeado; assert
  sobre `messages=` en `client.chat.completions.create`.

- [ ] **CA-05** — Un `id` de tool call vacío o ausente no rompe el turno: el adaptador genera
  uno sintético y estable para esa llamada, y lo usa consistentemente en el `assistant` y en
  el resultado.
  *Verificación:* pytest con `ToolCallRequest(id="", ...)`; la vuelta siguiente se arma sin
  excepción y ni `tool_use_id` ni `tool_call_id` viajan vacíos. *Motivo:* algunos modelos
  gratuitos de OpenRouter devuelven el `id` vacío; hoy da igual porque nunca se usaba.

- [ ] **CA-06** — El camino con streaming y el camino sin streaming mandan al SDK exactamente
  la misma lista de mensajes para el mismo historial: `_llamada_en_streaming()` los recibe ya
  traducidos.
  *Verificación:* pytest; assert de igualdad entre los `messages` capturados en ambos caminos.

- [ ] **CA-07** — Con un proveedor SIN tool-calling (`gemini`, `ollama`), el historial se
  aplana a texto antes de llegar al adaptador, de modo que el modelo igual ve qué herramientas
  se ejecutaron y con qué resultado. El texto aplanado para un historial dado es idéntico al
  que produce hoy `_build_prompt()`.
  *Verificación:* pytest; `_ask_gemini`/`_ask_ollama` reciben `messages` donde todo `content`
  es `str` (nunca lista ni dict), y el texto coincide con el actual.

- [ ] **CA-08** — `generate_response()` sigue aceptando el formato viejo
  (`[{"role": str, "content": str}]`) y con ese formato produce byte a byte la misma llamada
  al proveedor que antes de REQ-027, en los 5 adaptadores. El formato nuevo es **aditivo**.
  *Verificación:* pytest; comparar el `messages=` capturado contra el esperado de hoy. *Motivo:*
  es lo que protege a `ai/claude_brain.py`, `core/compaction.py` y a todo caller interno.

- [ ] **CA-09** — Una imagen adjunta (`image_path`) convive con el historial de herramientas:
  se sigue adjuntando al último mensaje de rol `user` con contenido de texto, nunca a un
  mensaje que transporta resultados de herramienta.
  *Verificación:* pytest; historial con resultados de tool + `image_path` → el adaptador no
  adjunta la imagen al mensaje de resultados, y la llamada al SDK es válida.

- [ ] **CA-10** — Los tests de REQ-021/CA-22 sobre el aplanado
  (`test_ca22_*` de `tests/test_reasoning_loop.py`) siguen pasando sin cambios de expectativa.

### B. Presupuesto variable según modo y canal

- [ ] **CA-11** — El presupuesto por defecto (sin modo, canal `DESKTOP`) es 8:
  `core.reasoning_loop.MAX_LLM_CALLS == 8`.
  *Verificación:* pytest, assert directo sobre la constante.

- [ ] **CA-12** — Cada modo declara su presupuesto en el catálogo de
  `core/composer_modes.py`, junto a `tool_names` y `tarea` — no en una tabla paralela en otro
  módulo. Valores: Código/script 40, Investigación 25, Nodos/flujos 12, Tareas 10.
  *Verificación:* pytest sobre `listar_modos()`.

- [ ] **CA-13** — Con un modo activo, `run()` hace como máximo el presupuesto de ese modo.
  *Verificación:* pytest; `generate_response` mockeado que siempre pide una tool →
  `call_count == 25` con `modo="investigacion"` y `== 40` con `modo="codigo"`.

- [ ] **CA-14** — Un `modo` vacío o desconocido cae en el presupuesto por defecto (fail-safe de
  `get_mode()`), nunca en el más alto.
  *Verificación:* pytest; `modo="inexistente"` y `modo=""` → 8 llamadas.

- [ ] **CA-15** — Techo por canal: en cualquier canal distinto de `DESKTOP` el presupuesto
  efectivo es 5, aunque llegue un modo con presupuesto mayor.
  *Verificación:* pytest; `run(..., channel="voice", modo="codigo")` → `call_count == 5`.
  Repetido para `"telegram"`, `"email"` y `"unknown"`.

- [ ] **CA-16** — `ai/claude_brain.py::MAX_TOOL_ROUNDS == 5`, y `claude_brain` no conoce ni
  recibe el concepto de modo.
  *Verificación:* pytest; assert del valor + `inspect.signature(ask_claude)` sin parámetro
  `modo` + grep de `composer_modes` ausente en `ai/claude_brain.py`.

- [ ] **CA-17** — **La firma de `core.reasoning_loop.run()` no cambia en REQ-027**: sigue
  siendo `(task, channel, user_id="default", agent_name="reasoning_loop", estado=None,
  modo=None)`. El presupuesto se deriva de `modo` y `channel`, que ya son parámetros.
  *Verificación:* pytest con `inspect.signature`. *Motivo:* `tests/modelo_falso.py` instala un
  `run()` falso que es una **función plana**, no un `MagicMock`; un kwarg nuevo explota con
  `TypeError` en 58 tests ajenos (pasó en REQ-026). Sin cambio de firma, el riesgo desaparece
  de raíz en vez de mitigarse.

- [ ] **CA-18** — Un turno que se resuelve en una sola vuelta hace exactamente 1 llamada al
  modelo, con cualquier presupuesto: el presupuesto es un techo, nunca un objetivo.
  *Verificación:* pytest; respuesta sin `tool_calls` y `modo="codigo"` → `call_count == 1`.

- [ ] **CA-19** — El presupuesto no cambia el comportamiento de REQ-026: los 4 modos siguen
  priorizando sus `tool_names` vía `_reordenar_priorizando()` (sin filtrar el resto) y
  fijando su `tarea`.
  *Verificación:* tests existentes de REQ-026, sin cambios.

### C. Todas las tool calls de la vuelta

- [ ] **CA-20** — Si el modelo pide N tool calls en una vuelta, se ejecutan las N, en el orden
  en que vinieron.
  *Verificación:* pytest; `LLMToolResponse` con 3 `ToolCallRequest` → `execute_tool` mockeado
  con `call_count == 3` y el orden de nombres coincidente.

- [ ] **CA-21** — Cada una pasa por `agents/tool_registry.py::execute_tool()` por separado, con
  su propio nivel de riesgo y su propia confirmación. No existe forma de que la segunda se
  ejecute "aprovechando" la confirmación de la primera.
  *Verificación:* pytest (3 llamadas separadas a `execute_tool`, nunca una agrupada) + el grep
  estático existente de `.invoke(` sobre `core/reasoning_loop.py`.

- [ ] **CA-22** — `channel`, `user_id` y `texto_original` se inyectan en los params de **cada
  una** de las N llamadas, pisando cualquier valor que el modelo hubiera propuesto.
  *Verificación:* pytest; 3 tool calls, una con `arguments={"channel":"desktop","user_id":"atacante"}`
  → los 3 `execute_tool` reciben el canal y el usuario del caller confiable.

- [ ] **CA-23** — Los N resultados vuelven al modelo en **una sola vuelta**, cada uno
  correlacionado con el `id` de su tool call.
  *Verificación:* pytest; 3 tool calls → la siguiente llamada a `generate_response` lleva los 3
  ids y los 3 resultados.

- [ ] **CA-24** — Una vuelta con N herramientas consume **1** unidad del presupuesto, no N.
  *Verificación:* pytest; cada vuelta pide 3 tools y nunca hay respuesta final →
  `generate_response.call_count == MAX_LLM_CALLS` y `execute_tool.call_count == 3 ×
  MAX_LLM_CALLS`.

- [ ] **CA-25** — Si una de las N es denegada (`ActionDenied`), las que quedan de esa vuelta
  **no se ejecutan**.
  *Verificación:* pytest; 3 tool calls, la 2ª denegada → `execute_tool.call_count == 2`.

- [ ] **CA-26** — Una herramienta que lanza una excepción cualquiera que **no** sea
  `ActionDenied` no corta la secuencia: se registra su resultado como error (REQ-007/CA-13) y
  se sigue con las restantes de la vuelta.
  *Verificación:* pytest; 3 tools, la 1ª lanza `RuntimeError` → `execute_tool.call_count == 3`
  y el modelo recibe 3 resultados, uno con el texto de error.

- [ ] **CA-27** — `abortar_si_cancelado()` se evalúa además **entre herramientas** dentro de la
  misma vuelta, no solo una vez por vuelta. Con el cambio 3 una sola vuelta puede ser larga, y
  el botón de detener no puede quedar esperando a que termine.
  *Verificación:* pytest; 4 tool calls con la cancelación activada después de la 2ª →
  `execute_tool.call_count == 2` y el turno corta.

### D. Llamada de cierre sin herramientas

- [ ] **CA-28** — Agotado el presupuesto sin respuesta final, `run()` hace **una** llamada más
  al modelo con `tools=None`, pasándole el historial completo, para que redacte la respuesta
  con lo que ya reunió.
  *Verificación:* pytest; presupuesto 8, el modelo siempre pide tool →
  `generate_response.call_count == 9` y la 9ª con `tools=None`.

- [ ] **CA-29** — Tras una denegación, `run()` hace **una** llamada de cierre con `tools=None`
  que recibe los resultados de las herramientas que sí corrieron y el hecho de la denegación.
  No hay ninguna vuelta posterior: con `tools=None` el modelo no puede reintentar la acción
  denegada ni probar una alternativa, que es la intención literal de REQ-007/CA-08.
  *Verificación:* pytest; 1ª vuelta con tool denegada → `generate_response.call_count == 2`,
  la 2ª con `tools=None`, y no hay una 3ª.

- [ ] **CA-30** — La llamada de cierre está **fuera** del presupuesto y es como máximo una por
  turno. No puede encadenar.
  *Verificación:* pytest (implícito en CA-28: 8 + 1, nunca 8 + 2).

- [ ] **CA-31** — Si la llamada de cierre falla (sin proveedor) o vuelve vacía, la respuesta al
  usuario es exactamente el mensaje enlatado de hoy: `"No pude completar la tarea en el número
  de intentos disponibles…"` en el caso de presupuesto agotado, y
  `"⛔ No puedo ejecutar esa acción{vocative()}: {reason}"` en el caso de denegación.
  *Verificación:* pytest; `generate_response` que devuelve `SIN_PROVEEDOR` y `""` en la llamada
  de cierre, un caso por cada situación.

- [ ] **CA-32** — `estado["denied"]` sigue quedando en `True` ante una denegación, haya o no
  llamada de cierre. `core/resolution.py` no cambia de comportamiento y sigue sin colgarle
  recordatorios ni repreguntas a un mensaje de denegación.
  *Verificación:* pytest; assert sobre el dict `estado` + los tests existentes de
  `core/resolution.py` sin cambios.

### E. `max_tokens`

- [ ] **CA-33** — Existe una única constante de tope de tokens de salida en
  `ai/llm_provider.py` con valor **4096**, y los 5 puntos que hoy dicen `max_tokens=1500`
  (`:595`, `:756`, `:834`, `:867`, `:974`) la usan.
  *Verificación:* pytest con grep estático: `"max_tokens=1500"` no aparece en el archivo, la
  constante existe y vale 4096, y hay 5 usos.

- [ ] **CA-34** — El valor es **único**, no por tarea: no hay tabla nueva, ni clave nueva en
  `config.json`, ni parámetro nuevo en `generate_response()`.
  *Verificación:* pytest (firma de `generate_response` sin parámetro nuevo) + grep de
  `max_tokens` ausente en `config.json`.
  *Motivo:* `max_tokens` es un techo, no un objetivo — una respuesta de "qué hora es" sigue
  costando 20 tokens y subirlo no encarece nada. Una tabla por tarea sería una segunda
  estructura de ruteo al lado de `task_providers` para un parámetro que solo muerde en una
  dirección.

- [ ] **CA-35** — 4096 no supera el tope de salida de ninguno de los modelos por defecto de
  `_MODELO_POR_PROVEEDOR` (`claude-3-5-sonnet` 8192, `gpt-4o-mini` 16384, `deepseek-chat`
  8192, y los gratuitos de OpenRouter en uso).
  *Verificación:* prueba manual — un turno real por cada proveedor configurado en
  `config.json`, sin error de API. *Motivo de no elegir 8192:* varios modelos gratuitos de
  OpenRouter tienen tope de salida menor y rechazan la petición con error duro; sería una
  regresión que aparece justo en los modelos que Johan usa por ser gratis.

### F. No regresión sobre los invariantes

- [ ] **CA-36** — Gate REQ-005/REQ-006 intacto: toda ejecución sigue pasando por
  `execute_tool()`, nunca por `ToolSpec.invoke` directo. `.invoke(` no aparece en
  `core/reasoning_loop.py`.
  *Verificación:* `test_ca06_reasoning_loop_nunca_llama_invoke_directo` existente, sin cambios.

- [ ] **CA-37** — El gate por canal sigue denegando lo que corresponde: una tool amarilla
  pedida por voz sigue lanzando `ActionDenied`.
  *Verificación:* tests de gate existentes de `tests/test_reasoning_loop.py`, sin cambios.

- [ ] **CA-38** — Degradación con proveedor sin tool-calling: si `generate_response()` devuelve
  texto plano en vez de `LLMToolResponse`, `run()` lo acepta como respuesta final
  (REQ-007/CONFIRMADO 1). `gemini` y `ollama` no se rompen.
  *Verificación:* test existente + CA-07.

- [ ] **CA-39** — El botón de detener sigue cortando: `abortar_si_cancelado()` al inicio de
  cada vuelta (existente) y entre herramientas (CA-27).
  *Verificación:* tests de `core/cancelacion.py` existentes + CA-27.

- [ ] **CA-40** — Una llamada con `tools` sigue sin pasar por `_cached_call()`
  (REQ-007/CA-09): la caché nunca ve una llamada con herramientas.
  *Verificación:* test existente.

- [ ] **CA-41** — `agent_context` sigue recibiendo un solo par user/assistant por invocación de
  `run()`, sin importar cuántas vueltas ni cuántas herramientas hubo (REQ-007/CA-10).
  *Verificación:* test existente.

- [ ] **CA-42** — El aviso de cambio de proveedor (REQ-022/CA-12) sigue funcionando cuando el
  respaldo entra a mitad de un turno que ya tiene historial de herramientas.
  *Verificación:* pytest; forzar fallo del destino principal en la 2ª vuelta y assert de que
  `aviso` queda relleno y el texto final lo lleva.

- [ ] **CA-43** — `tests/modelo_falso.py` no requiere ningún cambio (consecuencia de CA-17), y
  `core/resolution.py` tampoco.
  *Verificación:* `git diff --stat` de la rama no toca esos dos archivos.

- [ ] **CA-44** — La suite completa (`python -m pytest tests/ --tb=short`) no gana ningún fallo
  nuevo respecto del baseline previo al REQ.
  *Verificación:* comparación contra `baseline-027.md`.

- [ ] **CA-45** — Prueba manual de extremo a extremo, en la app real: (a) un "hola" responde en
  una vuelta; (b) con modo Investigación activo, una pregunta que exige varias fuentes encadena
  más de 4 herramientas y responde citando lo leído; (c) el botón de detener corta un turno
  largo a mitad de una vuelta con varias herramientas; (d) una acción amarilla dentro de una
  vuelta de varias herramientas sigue mostrando su modal de confirmación.

---

## Casos borde

- **Vuelta con muchas tool calls.** No hay tope por vuelta (Johan lo descartó). Un modelo
  confundido podría pedir 50 llamadas en una sola vuelta; lo que lo acota es el gate por
  herramienta, la cancelación entre herramientas (CA-27) y el propio presupuesto de vueltas.
- **El modelo pide la misma tool dos veces en la misma vuelta con los mismos argumentos.** Se
  ejecutan las dos: deduplicar sería adivinar (dos `task_create` idénticos pueden ser dos
  tareas iguales a propósito). Cada una tiene su `id` y su resultado.
- **Denegación en la PRIMERA tool de la vuelta.** No hay resultados previos que reportar; la
  llamada de cierre recibe solo la denegación. Si falla, el usuario ve el `⛔` de siempre.
- **Respuesta con texto y tool calls a la vez.** Anthropic puede devolver bloques `text` y
  `tool_use` juntos. El texto de una vuelta intermedia no es la respuesta final: se conserva en
  el mensaje `assistant` del historial (es parte del razonamiento del modelo) y no se muestra
  al usuario hasta la vuelta que cierra.
- **Cambio de proveedor a mitad de turno** (cooldown o respaldo, REQ-022). El historial neutral
  se traduce recién en el adaptador que efectivamente atiende, así que sobrevive al cambio
  (CA-02). Este es el motivo de que la representación sea neutral y no nativa.
- **Modelo de OpenRouter que anuncia tool-calling pero devuelve `id` vacío o argumentos que no
  parsean.** `id` vacío → CA-05. Argumentos no parseables → ya se resuelve hoy con
  `arguments = {}` en los adaptadores; no cambia.
- **Presupuesto alto + ventana de contexto.** Con 40 vueltas y resultados largos, el historial
  puede exceder la ventana del modelo. Fuera de alcance resolverlo (no hay compactación del
  historial de herramientas en este REQ), pero el fallo debe ser un error del proveedor
  manejado como cualquier otro —cadena de respaldo, aviso, respuesta al usuario— y nunca un
  crash del turno.
- **Voz + `max_tokens` 4096.** Una respuesta de 4096 tokens leída por TTS son varios minutos.
  Es una condición **preexistente** (con 1500 ya son minutos) que este REQ agrava pero no
  introduce; hoy la acota el prompt de sistema. Ver `## PENDIENTE DE JOHAN`.
- **Canal `EMAIL`.** Hoy `core/email_reader.py` no pasa por `reasoning_loop` y su política de
  canal está vacía a propósito. El techo de 5 de CA-15 lo cubre igual, por si mañana lo hace:
  un texto que puede originar cualquiera del planeta no debe poder disparar 40 llamadas al
  modelo.

## Asumidos

- ASUMIDO: la representación neutral del historial de herramientas puede vivir como mensajes
  con `content` estructurado dentro de la misma lista `messages` que ya recibe
  `generate_response()`, sin cambiar la firma de esa función. Confirmar con `orion-architect`
  (la alternativa —un parámetro nuevo— tocaría a todos los callers y a `_cached_call`).
- ASUMIDO: el aplanado de degradación de CA-07 puede reutilizar la lógica actual de
  `_build_prompt()`/`_append_history_lines()` tal cual, sin reescribirla. Confirmar dónde
  queda (mismo módulo o `ai/llm_provider.py`) con `orion-architect`.
- ASUMIDO: el presupuesto es un entero por modo en `ModoComposer` y no una fórmula. Los 4
  valores quedan fijados en código, sin exponerlos en `config.json` — no hay pedido de que el
  usuario los ajuste, y una clave más de configuración es una superficie más que mantener.
- ASUMIDO: `ai/claude_brain.py` sigue re-serializando resultados como texto (su bucle propio,
  `:190-204`) y solo se le sube `MAX_TOOL_ROUNDS`. Confirmar — está en `## PENDIENTE DE JOHAN`.

## Impacto en tests existentes (para `orion-baseline` y la implementación)

Tres tests de `tests/test_reasoning_loop.py` cambian de expectativa, y es intencional:

1. `test_ca07_agota_5_llamadas_sin_una_sexta` — ya referencia el símbolo
   `reasoning_loop.MAX_LLM_CALLS`, así que el conteo se adapta solo al 8; pero con CA-28 pasa a
   haber una llamada de cierre, así que el assert correcto es `MAX_LLM_CALLS + 1` y el texto
   enlatado deja de ser la única salida posible.
2. `test_ca08_action_denied_corta_de_inmediato` — hoy afirma `call_count == 1`. Con CA-29 pasa
   a 2, y hay que agregar el assert de `tools=None` en la segunda. **Es el único punto del REQ
   que relaja una conducta ya fijada por test en un camino de seguridad**, y por eso está
   explicitado acá y no escondido en la implementación. Lo que CA-08 protege —"no reintenta, no
   prueba otra tool"— queda garantizado por construcción (sin herramientas no hay nada que
   reintentar), no por prompt.
3. Cualquier test que fije `max_tokens=1500` en `tests/test_llm_provider.py`.

---

## PENDIENTE DE JOHAN

**P-1. ¿La llamada de cierre tras una denegación lleva `tools=None` (recomendado) o el
catálogo completo?**
Tu decisión registrada dice "se corta la secuencia ahí y se le informa al modelo", pero no dice
si en esa llamada el modelo sigue teniendo herramientas.
- Opción A (**recomendada, es la que specifiqué**): `tools=None`. El modelo redacta la
  respuesta con lo que pasó y no puede reintentar la acción denegada ni buscar un rodeo. La
  garantía es estructural, no depende de que obedezca el prompt.
- Opción B: catálogo completo y el bucle sigue. Es lo que haría un agente genérico, pero deja
  la garantía de "no reintentes" apoyada solo en una frase del prompt de sistema.
- Consecuencia de A: hay que actualizar `test_ca08_action_denied_corta_de_inmediato` de
  `call_count == 1` a `== 2`. Es el único test de seguridad que este REQ modifica.

**P-2. ¿Entra el cambio 4 (llamada de cierre al agotar el presupuesto) en este REQ?**
No estaba en el encargo; lo agregué porque el cambio 2 lo vuelve necesario: agotar 40 vueltas
y devolver "No pude completar la tarea en el número de intentos disponibles" tira a la basura
39 vueltas de investigación pagada.
- Recomendación: **sí, entra.** Es el mismo mecanismo que P-1 y que el que `ai/claude_brain.py`
  ya usa hoy (`:207-212`), o sea que no es una pieza nueva del sistema.
- Si decís que no: se caen CA-28, CA-30 y CA-31 (parte de presupuesto agotado), y el
  presupuesto alto queda a medio aprovechar.

**P-3. ¿`ai/claude_brain.py` (Telegram/Discord) también migra al protocolo nativo?**
- Recomendación: **no en este REQ.** Su contrato es distinto —historial de sesión por usuario,
  imágenes, bloques JSON de aprendizaje— y migrarlo duplica el tamaño del REQ sin destrabar
  ninguna de las 3 capacidades que motivan esto (las 3 son de escritorio). Acá recibe solo el
  subidón de `MAX_TOOL_ROUNDS` 3 → 5.
- Costo de postergarlo: Telegram sigue con razonamiento de segunda respecto del escritorio, que
  es justo la asimetría que el propio módulo dice haber venido a arreglar.

**P-4. ¿Querés un tope de tokens más bajo para el canal de voz?**
Con 4096 tokens, una respuesta larga leída por TTS son varios minutos que nadie puede cortar.
- Recomendación: **fuera de alcance de REQ-027** (es una condición preexistente, no una que
  introduzca este REQ), pero es un candidato claro a REQ chico posterior: un techo de salida
  por canal, ~500 tokens en `VOICE`.
- Si lo querés acá, se agrega como CA en la sección E y hay que decidir el número.

**P-5. Rama git.** El contexto la deja sin definir; la rama actual es
`feature/mcp-correo-flujos`, que no tiene que ver con este REQ. ¿Rama nueva desde `main`?
