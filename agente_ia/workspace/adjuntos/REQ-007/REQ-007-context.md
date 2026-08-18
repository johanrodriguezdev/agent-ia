# Contexto REQ-007 — Bucle de razonamiento real con LLM

## Resumen ejecutivo
O.R.I.O.N. hoy no razona: `core/base_agent.py::_DynamicAgentInstance.execute()` (líneas ~94-107)
prueba herramientas en un `for` en orden fijo hasta que una no lance `ActionDenied`, sin consultar
ningún LLM ni evaluar resultados. REQ-007 reemplaza ese loop por un bucle de razonamiento real:
recibe el pedido, consulta al LLM con las herramientas disponibles, ejecuta la elegida, mira el
resultado y decide reintentar, encadenar otra herramienta o responder.

## Pedido del humano (citado tal cual)
> "recibe el pedido, ve qué herramientas tiene, elige, ejecuta, mira el resultado y decide si
> reintentar, encadenar otra herramienta o responder — no 'primera que no falle'"

Motivación explícita: comparación directa con Jarvis/OpenClaw hecha por el humano en la
conversación de origen — O.R.I.O.N. se percibía "muy limitado" precisamente por la ausencia de
este bucle. Ya se verificó en código (durante REQ-006) que la "capa inteligente" que se suponía
debía razonar simplemente no existe hoy.

## Precondición: REQ-006 cerrado
REQ-006 (pipeline único de resolución) está `LISTO_PARA_COMMIT`, con prueba manual confirmada por
el humano. REQ-007 es la pieza que REQ-006 dejó explícitamente pendiente y preparada.

## Diseño de referencia ya existente — NO repetir el debate, partir de aquí
Ubicación: `workspace/adjuntos/REQ-006/propuestas/arquitectura-006.md`, sección final
**"[B] — Diseño de referencia para REQ-007 (NO implementar en REQ-006)"**, criterios CA-18 a CA-24.
Es diseño de referencia, **no contractual** — `orion-architect` de REQ-007 debe confirmarlo o
ajustarlo contra el código real ya construido en REQ-006, no repartir desde cero.

Puntos clave del diseño [B]:
- **CA-18 a CA-23**: nuevo módulo `core/reasoning_loop.py` que reemplaza
  `_DynamicAgentInstance.execute()`. Llama al LLM (vía `ai/llm_provider.py`, ya existente) con la
  lista de `ToolSpec` de `agents/tool_registry.py` (ya construido en REQ-006, contrato isomorfo a
  MCP: `name`, `description`, `parameters_schema`, `risk_level`, `invoke`, `origin`) convertida al
  formato de "tools" del proveedor LLM. El loop recibe la decisión de tool-call del LLM y
  **ejecuta exclusivamente vía `execute_tool()`** (nunca `ToolSpec.invoke` directo) — así el gate
  de seguridad de REQ-006/REQ-005 sigue aplicando sin cambios.
- **CA-24**: bug de `core/orchestrator.py::_decompose()` que rompe con la letra "y" (comparación
  por substring en vez de palabra completa). Fix con `\b` (word boundary) más red de seguridad
  `all(len(p) > 3 for p in parts)`. Documentado en referencia OpenClaw §7.2 (B1).
- **Riesgo de arrastre señalado**: modelo "durableApprovalSatisfied" de OpenClaw (evitar
  repreguntar la misma tool YELLOW varias veces en una sola conversación) — descartado en REQ-006
  por sobreingeniería, pero **a reconsiderar en REQ-007** porque el loop real hace esa pregunta
  con más frecuencia que el for-loop actual.
- **Patrón recomendado** (`workspace/referencias/openclaw/01-seguridad-y-aislamiento.md` §2.3):
  validar credenciales de tools remotos al construir la lista de tools disponibles para el loop,
  no al invocar.

## Piezas ya construidas en REQ-006 — reutilizar, NO reconstruir
- `agents/tool_registry.py` — contrato de `ToolSpec` (name, description, parameters_schema,
  risk_level, invoke, origin), isomorfo a MCP.
- `core/confirmation.py` — manejo de confirmaciones para niveles amarillo/rojo.
- `core/resolution.py` — pipeline único de resolución entre canales.
- `core/security_manager.py::ActionDenied` — excepción del gate de seguridad fail-closed
  (REQ-005), se dispara cuando una acción no pasa `require_confirmation()`.
- `execute_tool()` — punto de entrada único para invocar herramientas, gatea seguridad. El nuevo
  `reasoning_loop.py` debe usar exclusivamente este punto de entrada, igual que el resto de
  caminos de ejecución reales (`dispatch()`, `SkillManager.execute()`, `get_agent_tools()`,
  `agents/action_registry.execute_action()`, `os_integration/capabilities_router.execute_capability()`).

## Estado actual
- **Estado tracker:** NUEVO
- **Último agente:** orion-coordinador
- **Fecha última actualización:** 2026-08-04
- **Rama git:** —
- **Categoría:** CORE
- **Tipo de cambio:** (a definir en spec — probable REFACTOR/FEATURE_NUEVA, toca el motor de
  ejecución del agente; overlap con SEGURIDAD por tocar el gate de tools, pero la categoría
  principal es CORE)

## Decisiones tomadas
2026-08-04 | orion-coordinador | REQ creado — categoría=CORE | Detección por palabras clave: "bucle", "dispatcher"-adyacente (reemplaza el loop de ejecución del agente en core/base_agent.py), "main loop"/"handler" del motor de razonamiento. El humano ya indicó explícitamente que es la continuación directa de REQ-006 y que no requiere pregunta de categoría.
2026-08-04 | orion-coordinador | No se re-pregunta al humano | El pedido ya fue dado completo y autorizado explícitamente en la conversación de origen; se pasa directo a orion-spec.

## Descartado (y por qué)
<!-- Opciones evaluadas y rechazadas — evita repetir el debate -->
- (heredado de REQ-006, a confirmar por orion-spec/orion-architect) Modelo "durableApprovalSatisfied" de OpenClaw — descartado en REQ-006 por sobreingeniería. Reconsiderar aquí si el loop real genera fricción real de reconfirmación.

## Asumidos pendientes de confirmar
- Que la categoría principal es CORE y no SEGURIDAD, dado que el REQ toca el punto de invocación
  de tools pero no cambia la lógica de clasificación de riesgo en sí — a confirmar por
  `orion-spec`/`orion-security` si aplica.
- Que el diseño de referencia [B] (CA-18 a CA-24) se mantiene válido tal cual contra el código real
  de REQ-006, o si requiere ajustes — a resolver por `orion-architect`.

## Riesgos activos
- Riesgo de reconfirmación repetida de tools YELLOW en una sola conversación (ver "durableApprovalSatisfied" arriba) — sin mitigar todavía.
- El loop real puede introducir latencia/costo adicional por llamada a LLM en cada decisión de tool — no evaluado aún.

## Decisiones tomadas (orion-spec)
2026-08-04 | orion-spec | Leído diseño [B] completo (arquitectura-006.md CA-18 a CA-24) y código real: `core/base_agent.py`, `agents/tool_registry.py`, `core/confirmation.py`, `core/security_manager.py`, `core/orchestrator.py`, `ai/llm_provider.py`, `ai/claude_brain.py`, `config.json`.
2026-08-04 | orion-spec | Hallazgo NO documentado en el diseño [B]: `ai/llm_provider.py::generate_response()` no tiene ningún soporte de tool-calling nativo hoy — no envía `tools=` a ningún proveedor, y `_ask_anthropic` descarta cualquier bloque `tool_use` (usa `response.content[0].text` directo). `ai/claude_brain.py` tampoco usa tool-calling real: su patrón `learn_command`/`save_memory` es un bloque JSON embebido en texto libre, parseado con regex. El diseño [B] asume "convierte los ToolSpec a la forma de tools del proveedor" pero eso no existe en el código — requiere construirse en REQ-007, no reutilizarse. Se eleva como pregunta de clarificación #1 antes de redactar la SPEC.
2026-08-04 | orion-spec | `config.json` activo: `ai_provider=deepseek`, `ai_model=deepseek-chat` (no `anthropic`). Relevante para decidir alcance de proveedor(es) del loop — pregunta de clarificación #1.
2026-08-04 | orion-spec | Confirmado por lectura de código: `core/orchestrator.py::_decompose()` (líneas 91-102) reproduce el bug CA-24 tal cual lo describe [B] — `"y" in text.lower()` es el primer trigger de la lista y captura cualquier substring "y" (ej. "hoy", "voy", "muy"), no palabra completa.
2026-08-04 | orion-spec | Preguntas de clarificación formuladas al humano, spec en pausa hasta respuesta (ver preguntas en la conversación).

## Decisiones tomadas (respuestas del humano a las 6 preguntas de clarificación)
2026-08-04 | orion-spec | P1 alcance de proveedor: SOLO anthropic/deepseek/openai (formato compatible OpenAI) para tool-calling nativo. NO se implementa el mecanismo agnóstico JSON-en-texto para los 5 proveedores. Si el `ai_provider` activo no soporta tools, el loop degrada a llamada sin herramientas (ver SPEC-007 ASUMIDO 1 — el humano dejó ambas opciones abiertas, se documentó la elegida como asumido a confirmar).
2026-08-04 | orion-spec | P2 límite de iteraciones: 5 ciclos máximo (decide tool → ejecuta → mira resultado → decide de nuevo).
2026-08-04 | orion-spec | P3 tool YELLOW/RED denegada: el loop PARA de inmediato e informa al usuario cuando `execute_tool()` lanza `ActionDenied` — no intenta otra tool ni sigue razonando. `durableApprovalSatisfied` descartado explícitamente, fuera de alcance.
2026-08-04 | orion-spec | P4 historial: solo se registra el turno final (pedido + respuesta) en `agent_context_manager`; las iteraciones intermedias no generan entradas propias.
2026-08-04 | orion-spec | P5 canal/voz: el loop NO filtra tools por canal — ofrece la misma lista completa en los 4 canales; `execute_tool()`/`CHANNEL_ALLOWED_LEVELS` sigue siendo el único gate. Sin pre-filtrado nuevo específico de voz.
2026-08-04 | orion-spec | P6 fix CA-24 `_decompose()`: SÍ incluido en el alcance de REQ-007, usando el diseño ya definido en `[B]` (word boundary `\b` + red de seguridad `all(len(p) > 3 for p in parts)`).
2026-08-04 | orion-spec | SPEC-007.md redactado en `workspace/adjuntos/REQ-007/spec/SPEC-007.md` con 13 criterios de aceptación (CA-01 a CA-13, renumerados desde REQ-006 para que el documento sea autocontenido — tabla de trazabilidad a CA-18–24 incluida en la spec). Módulos afectados identificados: `core/reasoning_loop.py` (nuevo), `core/base_agent.py`, `ai/llm_provider.py`, `core/orchestrator.py`; sin cambios a `agents/tool_registry.py`, `core/security_manager.py`, `core/confirmation.py`.
2026-08-04 | orion-spec | 4 asumidos documentados en la SPEC, el más relevante: ASUMIDO 2 — el loop usa como única fuente de tools el registro de `agents/tool_registry.py` (`ToolSpec`, hoy solo 3: task_create/task_list/task_complete), NO el `self.tools: List[AgentTool]` que `_DynamicAgentInstance` recibe hoy del orquestador — el universo de tools del loop es más chico que el `for` que reemplaza, salvo que arquitectura decida migrar/envolver los `AgentTool` existentes. Pendiente de confirmación explícita por el humano junto con la aprobación de la SPEC.
2026-08-04 | orion-spec | SPEC presentada al humano para aprobación — flujo en pausa (`⏸️ ESPERANDO VALIDACIÓN`), no se avanza a `orion-baseline` sin OK explícito.

## Decisiones tomadas (segunda ronda — respuestas del humano a los 4 asumidos)
2026-08-04 | orion-spec | Asumido 1 (universo de tools) — CAMBIA el asumido original: el humano decide MIGRAR los `AgentTool` existentes (`"dispatcher"` de `main.py` + todos los de `skill_manager.get_agent_tools()`) a `ToolSpec`, dentro del alcance de REQ-007. Motivo explícito: un loop con menos capacidad que el `for` actual no resuelve el problema real que motivó el REQ. Se agregan CA-14 (inventario y migración completa, sin AgentTool huérfano), CA-15 (risk_level derivado de `security_manager.classify_action()` ya existente, no inventado), CA-16 (invoke migrado llama `skill.extract_params()` antes de `skill.execute()`, sin auto-gate duplicado dentro de invoke).
2026-08-04 | orion-spec | Asumido 2 (proveedor sin tools): CONFIRMADO tal cual — degrada en silencio a respuesta sin herramientas, sin aviso.
2026-08-04 | orion-spec | Asumido 3 (conteo del límite de 5): CONFIRMADO tal cual — 5 llamadas al LLM en total, incluida la que da la respuesta final.
2026-08-04 | orion-spec | Asumido 4 (alcance fix CA-24): CONFIRMADO tal cual — solo el parsing de la "y", sin tocar `MAX_CHAIN_DEPTH` ni `_execute_agent_chain()`.
2026-08-04 | orion-spec | SPEC-007.md actualizado: objetivo, alcance (incluye/no incluye), módulos afectados (`main.py`, `skills/skill_manager.py` consumido sin modificar, `agents/tool_registry.py` sin cambios de código), comportamiento actual vs deseado, 3 criterios nuevos (CA-14 a CA-16), 2 casos borde nuevos, sección de Asumidos reescrita (3 confirmados + 3 nuevos: ASUMIDO A naming de ToolSpec migrado reusa el Intent ya clasificado, ASUMIDO B el "dispatcher" catch-all también se migra como fallback genérico, ASUMIDO C sin período de coexistencia AgentTool/ToolSpec en paralelo), riesgo nuevo de drift si se agrega una skill después de la migración.
2026-08-04 | orion-spec | SPEC actualizada presentada al humano para aprobación final — flujo sigue en pausa (`⏸️ ESPERANDO VALIDACIÓN`).

## Decisiones tomadas (tercera ronda — aprobación final)
2026-08-04 | orion-spec | ASUMIDO A confirmado tal cual → CONFIRMADO 4: cada `ToolSpec` migrado de un intent de skill se nombra con el `Intent` ya clasificado (ej. "OPEN_APP"), no con el prefijo `skill_<intent>`.
2026-08-04 | orion-spec | ASUMIDO B confirmado tal cual → CONFIRMADO 5: el `"dispatcher"` catch-all (`main.py:31-35`) también se migra a `ToolSpec`, con `risk_level=GREEN`, como fallback genérico.
2026-08-04 | orion-spec | ASUMIDO C confirmado, con precisión adicional del humano → CONFIRMADO 6: la migración es un reemplazo COMPLETO, no una coexistencia temporal — `ToolSpec`/`agents/tool_registry.py` queda como único registro de herramientas del sistema; `AgentTool`/`AgentOrchestrator.register_tool()`/`self._tools` quedan obsoletos (consistente con el principio de REQ-006 de "un solo registro que cualquier canal puede invocar igual"). Se agregó CA-17 (nuevo) para que el retiro de `AgentTool` quede como decisión explícita y documentada de `orion-architect` (eliminar en este REQ o marcar para retiro posterior), nunca como ambigüedad sin registrar.
2026-08-04 | orion-spec | **SPEC-007 APROBADA por el humano.** Estado del documento actualizado a `✅ APROBADA` en `SPEC-007.md`. Total: 17 criterios de aceptación (CA-01 a CA-17), 6 confirmaciones explícitas documentadas en la sección Asumidos (además de los 4 casos borde/riesgos ya cubiertos).
2026-08-04 | orion-spec | `requerimientos.csv` actualizado vía `update-tracker.mjs`: `Aprobacion_SPEC=APROBADO`, `Tipo_Cambio=FEATURE_NUEVA`, `Estado=SPEC_APROBADO`.
2026-08-04 | orion-spec | Handoff emitido a `orion-baseline`.

## Decisiones tomadas (orion-baseline)
2026-08-04 | orion-baseline | Estado actual documentado en `origen/baseline-007.md` para los 6 módulos que SPEC-007 identifica como afectados (`core/base_agent.py`, `ai/llm_provider.py`, `agents/tool_registry.py`, `core/orchestrator.py`, `main.py`, `skills/skill_manager.py`) | Confirmación de código real, sin asumir sobre lo ya escrito en la SPEC/contexto.
2026-08-04 | orion-baseline | Confirmado: `ai/llm_provider.py` no tiene ningún vestigio de tool-calling nativo (ni `tools=`, ni parseo de `tool_use`/`tool_calls` en ningún `_ask_*`), y `_ask_anthropic()` asume `response.content[0].text` — rompería si el proveedor devolviera un bloque `tool_use` en esa posición | Coincide con el hallazgo ya registrado por orion-spec, verificado de nuevo por lectura directa del código.
2026-08-04 | orion-baseline | Confirmado: `core/orchestrator.py::_decompose()` (líneas 91-102) reproduce el bug de la "y" por substring tal cual describe CA-12, sin `\b` ni red de seguridad de longitud mínima hoy | Ningún test actual (`tests/test_agents.py::test_ca1_orchestrator`) prueba el comportamiento de `_decompose()`, solo que el método existe — el test del fix (CA-12) será enteramente nuevo.
2026-08-04 | orion-baseline | Confirmado: `skills/skill_manager.py::get_agent_tools()`/`_make_gated_tool_fn()` nunca llama a `extract_params()` (pasa `params` crudo directo a `skill.execute()`) y se auto-gatea con `require_confirmation()` dentro de `invoke`, devolviendo `"⛔ Acción no autorizada."` como string normal en vez de lanzar `ActionDenied` | Confirma exactamente el patrón que CA-16 dice que el `ToolSpec` migrado no debe repetir.
2026-08-04 | orion-baseline | Inventario real de `AgentTool` a migrar (CA-14): 22 intents repartidos en 10 archivos de skill + 1 catch-all `"dispatcher"` (`main.py:31-35`) = 23 `AgentTool` en total hoy | Detalle completo (tabla por skill) en `origen/baseline-007.md`; usado también como número base para el test de drift que sugiere la SPEC (`len(skill_manager.get_agent_tools())` = 22, sin el `+1`).
2026-08-04 | orion-baseline | `python -m pytest tests/ --tb=short -q` → 95 passed, 0 failed (3 warnings cosméticos preexistentes, no relacionados) | Verificado de nuevo por orion-baseline, no asumido a partir de lo que declaraba REQ-006 en el contexto.
2026-08-04 | orion-baseline | `python -m py_compile` limpio en los 6 módulos afectados que ya existen (`core/base_agent.py`, `core/orchestrator.py`, `ai/llm_provider.py`, `agents/tool_registry.py`, `main.py`, `skills/skill_manager.py`) más `core/security_manager.py`/`core/confirmation.py`/`core/resolution.py` (dependencias del gate) | `core/reasoning_loop.py` no existe todavía — confirmado, es el módulo nuevo que crea este REQ, no un fallo.
2026-08-04 | orion-baseline | Ningún fallo pre-existente encontrado — 0 fallos atribuibles a algo distinto de REQ-007 | Ver sección "Fallos pre-existentes" de `origen/baseline-007.md`.
2026-08-04 | orion-baseline | Cobertura de test existente relevante identificada: `tests/test_base_agent.py` (4 tests, cubre el fix H7/CA-09 del `for` que CA-01 elimina) y `tests/test_tool_registry.py` (7 tests, base de regresión de `execute_tool()` que CA-06 sigue usando); no existe hoy ningún test de `ai/llm_provider.py` | `orion-tester` debe tratar los tests de tool-calling (CA-03 a CA-05) como enteramente nuevos, sin base de regresión previa que comparar.

## Riesgos activos
- Un parámetro nuevo de `tools` en `generate_response()` que no entre en la cache key de `_cached_call()`/`_cache_key()` (`ai/llm_provider.py` líneas 14-30) produciría colisiones de caché entre una llamada con tools y una sin tools para el mismo texto — señalado para que `orion-architect` lo contemple explícitamente al extender la firma, no se decide en el baseline.
- Drift de migración AgentTool→ToolSpec (heredado de la SPEC, cuantificado ahora): 22 intents de skills + 1 dispatcher = 23 `AgentTool` a migrar; si alguno se omite sin documentar el motivo, incumple CA-14.
- `tests/test_base_agent.py` prueba directamente el `for` de `_DynamicAgentInstance.execute()` que CA-01 elimina — si CA-17 decide eliminar `AgentTool`/`_DynamicAgentInstance` en este mismo REQ (en vez de solo marcarlos obsoletos), estos 4 tests quedan huérfanos y `orion-dev`/`orion-tester` deben decidir explícitamente si se retiran, se adaptan, o se dejan como cobertura de código legado retenido — no asumir.

## Decisiones tomadas (orion-architect)
2026-08-04 | orion-architect | Propuesta técnica completa redactada en `propuestas/arquitectura-007.md` — cubre CA-01 a CA-17 y los 6 CONFIRMADOs | Ver documento para el detalle de cada módulo/clase/función.
2026-08-04 | orion-architect | Riesgo de colisión de cache (`_cache_key()` sin `tools`) resuelto: `generate_response()` bypasea `_cached_call()`/`_response_cache` por completo cuando `tools` está presente y el proveedor lo soporta, en vez de incorporar un hash del schema de tools a la cache key | Elimina la colisión de raíz en vez de mitigarla parcialmente; las llamadas del loop son inherentemente conversacionales/con estado, no candidatas naturales a cache de todos modos.
2026-08-04 | orion-architect | Multi-turno de tool-calling NO usa el protocolo nativo por proveedor (bloques `tool_use`/`tool_result` de Anthropic, mensajes `role="tool"` de OpenAI) — cada iteración del loop es una llamada de un solo turno, con el historial de tools ya ejecutadas aplanado como texto dentro del propio prompt (`_build_prompt()`) | Evita mantener 3 protocolos de continuación distintos con cero cobertura de test previa; hace `generate_response()` trivialmente mockeable; trade-off aceptado de perder eficiencia de contexto nativo.
2026-08-04 | orion-architect | CA-17: `AgentTool`/`BaseAgent.tools`/`DynamicAgentFactory.create_agent()` se MANTIENEN sin cambios de firma (dependencia dura no removible: `skills/skill_manager.py::get_agent_tools()` sigue construyendo `AgentTool`, y SPEC-007 no autoriza tocar ese archivo; además `tests/test_agents.py::test_ca2_base_agent`/`test_ca3_comunicacion` de REQ-002 los ejercitan directamente) | Hallazgo no anticipado por SPEC/baseline: eliminar `AgentTool` por completo rompería una dependencia real, no solo tests obsoletos.
2026-08-04 | orion-architect | CA-17: `AgentOrchestrator.register_tool()`/`self._tools` SÍ se eliminan en este REQ | Verificado que ningún test (`tests/test_agents.py::test_ca1_orchestrator`) los ejercita; tras quitar el bloque de `main.py` que los alimentaba quedan sin ningún lector/escritor real. `_execute_single_agent()`/`_execute_agent_chain()` pasan `[]` en su lugar.
2026-08-04 | orion-architect | `tests/test_base_agent.py`: 3 de 4 tests se reemplazan (prueban la semántica exacta del for-loop que CA-01 ordena eliminar); el 4to (`test_agent_tool_execute_no_propaga_excepcion_a_llamador`, prueba `AgentTool.execute()` en sí, no tocado) se mantiene tal cual | Ver sección "Disposición de tests/test_base_agent.py" en la propuesta.
2026-08-04 | orion-architect | Hallazgo no anticipado por SPEC-007 ni baseline-007.md: `_DynamicAgentInstance.execute()` (el método que CA-01 exige modificar) hoy no es alcanzable por ningún usuario real — verificado leyendo `main.py`, `core/orchestrator.py::process_task()` y `core/resolution.py::RESOLVERS` completos. Satisfacer solo la letra de CA-01 dejaría el bucle nuevo construido pero inalcanzable | Formulado como Pregunta 1 al humano en `propuestas/arquitectura-007.md` (Opción A: cablear en `core/resolution.py`'s resolver "claude" — desviación pequeña y documentada del alcance literal de SPEC / Opción B: alcance literal, cableado diferido a REQ futuro). No decidido unilateralmente — requiere respuesta explícita del humano junto con la aprobación de esta arquitectura.
2026-08-04 | orion-architect | Sub-pregunta dependiente de la Opción A: si el catch-all "claude" pasa a ser `reasoning_loop.run()`, `ai/claude_brain.py::ask_claude()` (personalidad JARVIS, memoria semántica, historial por usuario, side-channel de aprendizaje) deja de intervenir en esas conversaciones — CONFIRMADO 2 (5 llamadas totales incluida la final) impide delegarle la respuesta final como una llamada adicional sin violar el presupuesto | Formulado como Pregunta 2 al humano; mitigación propuesta si se aprueba A: system prompt propio de `reasoning_loop.py` mantiene el tono JARVIS pero no replica memoria semántica ni aprendizaje (regresión de UX acotada y documentada, no oculta).

## Descartado (y por qué) — orion-architect
2026-08-04 | orion-architect | Incluir un hash de `tools` en `_cache_key()` para evitar colisiones | Descartado a favor de bypasear la cache por completo cuando hay tools — más simple, elimina el riesgo de raíz en vez de mitigarlo, y las llamadas del loop no son buenas candidatas a cache de todos modos.
2026-08-04 | orion-architect | Mantener conversación multi-turno nativa del proveedor (bloques `tool_use`/`tool_result` de Anthropic, mensajes `role="tool"` de OpenAI/DeepSeek) entre iteraciones del loop | Descartado por fragilidad (riesgo real de error 400 por bloques mal pareados) y por la falta total de cobertura de test previa en `ai/llm_provider.py` para validarlo con confianza en las 3 SDKs a la vez; se eligió un prompt plano autocontenido por iteración en su lugar.
2026-08-04 | orion-architect | Eliminar `AgentTool`/`BaseAgent.tools`/`DynamicAgentFactory.create_agent()`'s parámetro `available_tools` por completo, tal como CONFIRMADO 6 sugiere en su redacción general | Descartado tras verificar que `skills/skill_manager.py` (no modificable en este REQ) sigue importando y construyendo `AgentTool`, y que `tests/test_agents.py` (REQ-002) los ejercita directamente — eliminarlos rompería una dependencia real, no solo código muerto.
2026-08-04 | orion-architect | Delegar la respuesta final del loop (cuando no hace falta ninguna tool) a `ai/claude_brain.py::ask_claude()` para preservar personalidad/memoria | Descartado: sería una llamada al LLM adicional a las del loop, violando el presupuesto de "5 llamadas en total incluida la final" (CONFIRMADO 2). Queda como Pregunta 2 al humano en vez de decisión unilateral.

## Decisiones tomadas (orion-architect — respuesta del humano a las 2 preguntas de diseño)
2026-08-04 | orion-architect | Pregunta 1 (reachability) respondida por el humano: Opción A — cablear `core/reasoning_loop.py` en el resolver "claude" de `core/resolution.py::_try_claude()` | Confirma la desviación pequeña y documentada del alcance literal de SPEC-007 (agrega `core/resolution.py` a los módulos tocados). Diseño final: el caso default (sin `claude_fn` inyectado, camino que usa `main.py`, único caller de producción confirmado por baseline) cae en `reasoning_loop.run()`; el caso con `claude_fn` inyectado (p.ej. `channels/gateway.py`) mantiene su comportamiento sin cambios — ese archivo no está en el alcance de SPEC-007 y no se lo obliga a pasar por el loop nuevo en este REQ.
2026-08-04 | orion-architect | Pregunta 2 (regresión de personalidad) respondida por el humano: mitigación aceptada tal cual — el loop responde con tono JARVIS propio pero sin memoria semántica ni side-channel de aprendizaje cuando resuelve sin `claude_fn` | Registrada explícitamente como deuda para un REQ futuro (posible integración de memoria semántica de `claude_brain`/`agent_context_manager` dentro del loop) — no se resuelve en REQ-007.
2026-08-04 | orion-architect | `propuestas/arquitectura-007.md` actualizada: ambas preguntas marcadas ✅ RESUELTO con la decisión del humano citada inline; agregado el diseño concreto de `_try_claude()` cableado; actualizada la tabla de Riesgos y mitigación (reachability y pérdida de personalidad pasan de "riesgo abierto" a "resuelto", se agrega riesgo nuevo y acotado de que `channels/gateway.py` queda fuera del loop en este REQ); agregado test sugerido para el cableado. | Documento queda con estado "✅ APROBADA" en su encabezado.
2026-08-04 | orion-architect | orion-security NO se invoca para este REQ — el bucle de razonamiento y la migración de tools no introducen ningún camino de ejecución nuevo fuera de los dos gates ya existentes y auditados (`router/dispatcher.py::dispatch()` y `agents/tool_registry.py::execute_tool()`); `ActionDenied` sigue siendo la única vía de denegación, sin lógica de seguridad nueva que auditar más allá de lo que REQ-005/REQ-006 ya cubren. | Señalado explícitamente al cerrar, per pedido del coordinador — si `orion-dev`/`orion-qa` detectan algo que sí lo amerite durante la implementación, deben señalarlo en su momento, no asumir que esta evaluación es definitiva para código aún no escrito.

## Decisiones tomadas (orion-dev)
2026-08-05 | orion-dev | Leído contexto completo, SPEC-007, arquitectura-007.md y baseline-007.md antes de escribir código, según proceso. | Precondición del agente.
2026-08-05 | orion-dev | **Hallazgo crítico: la implementación de REQ-007 ya existía completa en el working tree y ya estaba commiteada en git** (`b754ce3` 2026-07-22 "Fix mejora modulo Agente", `c3abfce` 2026-08-05 "Fix mejora agente UI funcioalidades") — ninguno de los dos commits menciona REQ-007. Los 9 archivos que `arquitectura-007.md` lista en "Archivos a modificar/crear" (`core/reasoning_loop.py`, `agents/skill_tools.py`, `core/base_agent.py`, `core/orchestrator.py`, `core/resolution.py`, `ai/llm_provider.py`, `main.py`, `tests/test_reasoning_loop.py`, `tests/test_llm_provider.py`, `tests/test_skill_tools.py`, `tests/test_base_agent.py`) coinciden literalmente con el diseño aprobado, incluidos los comentarios `REQ-007/CA-XX` citando cada criterio. El tracker/contexto nunca se actualizaron para reflejarlo (seguían en ARQUITECTURA_APROBADA / "Último agente: orion-architect"). | No se decidió por cuenta propia reescribir el código — reescribir algo ya correcto y ya en git introduce riesgo sin beneficio. Se documenta el hallazgo en vez de asumir silenciosamente que "no había nada hecho".
2026-08-05 | orion-dev | Verificación exhaustiva en vez de reimplementación: `python -m py_compile` limpio en los 9 archivos afectados; `pytest tests/` → 216 passed, 0 failed (baseline era 95/0, sin regresiones); los 31 tests específicos de REQ-007 (`test_reasoning_loop.py`, `test_llm_provider.py`, `test_skill_tools.py`, `test_base_agent.py`, más `test_agents.py` de regresión REQ-002) todos en verde; cobertura confirmada criterio por criterio de CA-01 a CA-17 + CONFIRMADO 1/4/5 + cableado de `_try_claude()` (Pregunta 1, Opción A); `requirements.txt` sin diferencias (coincide con "Dependencias nuevas: Ninguna" de la arquitectura); sin `except: pass` silencioso, sin `print()` de debug, sin secretos hardcodeados en los archivos nuevos. Detalle completo en `propuestas/desarrollo-log-007.md`. | Reemplaza la implementación que le correspondía a este paso del pipeline por una auditoría de conformidad, dado que el código ya existía.
2026-08-05 | orion-dev | No se ejecutó `git commit`/`add`/`push` en esta sesión — no hacía falta, el código ya estaba commiteado antes de que la sesión empezara. Se señala como pendiente para `orion-qa`/el humano: el proceso por el que este código llegó a `main` sin pasar por `orion-tester`/`orion-qa`/aprobación manual (según exige `.claude/rules/git.md`) fue irregular — no es un defecto técnico del código en sí, pero rompe el checklist de commits del pipeline. | Transparencia sobre el estado real del proceso, no se oculta la anomalía.

## Decisiones tomadas (orion-tester)
2026-08-05 | orion-tester | Verificación independiente completa, sin confiar únicamente en lo reportado por `orion-dev` (mismo rol que habría implementado el código) | `python -m py_compile` limpio en los 11 módulos afectados/dependencias del gate; `pytest tests/` ejecutado de cero: 216 passed, 0 failed (coincide con lo reportado); ejecución verbose dirigida de los 31 tests de REQ-007 + regresión REQ-002, uno por uno confirmado PASS.
2026-08-05 | orion-tester | 17/17 criterios de aceptación de SPEC-007 (CA-01 a CA-17) verificados PASS, más el cableado de producción (Pregunta 1, Opción A) | Detalle completo en `pruebas/test-results-007.md`. Verificación no se limitó a leer código y correr la suite existente — se agregaron pruebas funcionales end-to-end propias con `SkillManager`/`tool_registry` reales (solo `generate_response` mockeado): CA-12 con 6 casos manuales, CA-14/15 con registro real de 26 tools y comparación de `risk_level` contra `security_manager.classify_action()` en 6 intents reales, CA-07/CA-08/CA-10/CA-13 corriendo `reasoning_loop.run()` de punta a punta (gate de seguridad real, no mockeado) en vez de solo confiar en los mocks unitarios ya existentes.
2026-08-05 | orion-tester | Hallazgo nuevo de este paso (no reportado por `orion-dev`): `git show --stat c3abfce` confirma que ese commit no solo trae los 9 archivos de REQ-007 — bundlea en el mismo commit atómico los cambios reales de REQ-005 (`security_manager.py`/`confirmation.py`), REQ-006 (`resolution.py`/`tool_registry.py`) y **una reescritura completa de `ui/`** (`ui/gui.py`, 8 archivos nuevos en `ui/widgets/`, `ui/personality.py`, `ui/gui_workers.py`) no relacionada con ningún REQ de este tracker, más ~20 archivos de test ajenos a REQ-007 | Efecto práctico: es imposible revertir o aislar solo REQ-007 de ese commit. No es un defecto del código de REQ-007 en sí — se documenta para que `orion-qa`/el humano lo tengan presente al decidir cómo cerrar el proceso de commit. No se tocó `ui/` ni ningún archivo fuera del alcance de REQ-007 durante esta verificación.
2026-08-05 | orion-tester | Irregularidad de proceso ya señalada por `orion-dev` (código en `main` antes de tester/QA/aprobación manual, violando `.claude/rules/git.md`) — confirmada, no resuelta ni juzgada en este paso, queda documentada para `orion-qa`/el humano | Ver ambos hallazgos en `pruebas/test-results-007.md`, sección "Nota de proceso".
2026-08-05 | orion-tester | Veredicto: PASS. `requerimientos.csv` actualizado vía `update-tracker.mjs`: `Estado=EN_QA` | Handoff a `orion-qa`.

## Decisiones tomadas (orion-qa)
2026-08-05 | orion-qa | Auditoría de seguridad independiente sobre `core/reasoning_loop.py`, `agents/skill_tools.py`, `agents/tool_registry.py`, `ai/llm_provider.py`, `core/base_agent.py`, `core/orchestrator.py`, `core/resolution.py`, `main.py` | Confirmado: toda tool elegida por el LLM se ejecuta exclusivamente vía `execute_tool()` (sin `.invoke()` directo, grep sin resultados); `channel`/`user_id` nunca vienen del LLM (se sobrescriben tras copiar `call.arguments`); `_make_skill_invoke()` no duplica el gate (CA-16, sin `require_confirmation()` propio); `register_skill_tools()` falla cerrado si un intent no tiene `risk_level` clasificado; sin API keys/tokens hardcodeados; sin `except: pass` silencioso introducido por este REQ.
2026-08-05 | orion-qa | Reverificación independiente de compilación y suite dirigida (no solo repetición de lo reportado) | `python -m py_compile` limpio en los 9 archivos + 2 módulos de gate; `pytest` de los 31 tests de REQ-007 + regresión REQ-002 ejecutado de cero: 31/31 PASS, coincide con `orion-dev`/`orion-tester`.
2026-08-05 | orion-qa | Hallazgo menor no bloqueante (deuda preexistente, no introducida por REQ-007): `ai/llm_provider.py::get_provider_config()` usa `except Exception:` sin logging antes de devolver defaults; confirmado por `git log -p` que la función tiene esa forma desde antes de los commits de REQ-007 | No motiva rechazo — se documenta en `pruebas/qa-audit-007.md` para registro. También se señala como mejora menor sugerida (no bloqueante) que `_ask_openai`/`_ask_deepseek` no loguean el `except (JSONDecodeError, TypeError)` al parsear argumentos de tool call malformados, aunque el resultado igual queda cubierto por el gate y por el logging de `reasoning_loop.py`.
2026-08-05 | orion-qa | Hallazgo de proceso confirmado y NO resuelto (decisión del humano, no de este agente): código en `main` sin pasar por tester/QA/aprobación manual antes de los commits, commit `c3abfce` no aislable de REQ-005/006 + reescritura de `ui/` sin REQ propio | Ver sección dedicada en `pruebas/qa-audit-007.md`. Se documenta como asunto separado del veredicto técnico, sin decidir revertir nada.
2026-08-05 | orion-qa | Veredicto: ✅ COMPLETADO. `pruebas/qa-audit-007.md` generado. `requerimientos.csv` permanece en `EN_QA` (no se avanza a `LISTO_PARA_COMMIT` hasta el OK explícito del humano tras la prueba manual) | Se solicita al humano la prueba manual descrita en `pruebas/qa-audit-007.md` antes de entregar el mensaje de commit sugerido.

## Estado actual
- Estado tracker: EN_QA (QA aprobó; pendiente prueba manual del humano antes de LISTO_PARA_COMMIT)
- Último agente: orion-qa
- Rama git: `main` (el código de REQ-007 ya está en `main` vía `b754ce3`/`c3abfce`, no en una rama `feature/REQ-007-reasoning-loop` — esa rama propuesta por orion-architect nunca se creó; el trabajo real se hizo directo sobre `main`)

## Log de transiciones
2026-08-04 | — → NUEVO | orion-coordinador | REQ creado
2026-08-04 | NUEVO → EN_SPEC | orion-spec | Inicio de trabajo de spec, preguntas de clarificación pendientes de respuesta humana
2026-08-04 | EN_SPEC (sin cambio de estado) | orion-spec | SPEC-007.md redactado con las 6 decisiones del humano incorporadas; queda en EN_SPEC hasta aprobación explícita de la SPEC (no pasa a SPEC_APROBADO todavía)
2026-08-04 | EN_SPEC (sin cambio de estado) | orion-spec | SPEC-007.md ampliada con la migración AgentTool→ToolSpec (CA-14 a CA-16) tras la segunda ronda de clarificación; sigue en EN_SPEC hasta aprobación final explícita
2026-08-04 | EN_SPEC → SPEC_APROBADO | orion-spec | Humano aprobó SPEC-007 explícitamente (3 asumidos confirmados, CA-17 agregado). Handoff a orion-baseline.
2026-08-04 | SPEC_APROBADO → EN_ARQUITECTURA | orion-baseline | Baseline documentado (`origen/baseline-007.md`), 0 fallos pre-existentes, 95/95 tests en verde confirmados de nuevo. Handoff a orion-architect.
2026-08-04 | EN_ARQUITECTURA (sin cambio de estado) | orion-architect | Propuesta técnica completa entregada (`propuestas/arquitectura-007.md`), con 2 preguntas de diseño explícitas para el humano (reachability del loop y su efecto en `ask_claude()`). Sigue en EN_ARQUITECTURA hasta aprobación explícita — NO pasa a ARQUITECTURA_APROBADA todavía.
2026-08-04 | EN_ARQUITECTURA → ARQUITECTURA_APROBADA | orion-architect | Humano respondió las 2 preguntas de diseño (Opción A + mitigación aceptada) y aprobó explícitamente la arquitectura. Handoff a orion-dev.
2026-08-05 | ARQUITECTURA_APROBADA → EN_PRUEBAS | orion-dev | Código ya encontrado implementado y commiteado (`b754ce3`/`c3abfce`, fuera del ciclo documentado del pipeline). Verificación completa de conformidad contra los 17 CA realizada en vez de reimplementación; 216/216 tests en verde. Handoff a orion-tester.
2026-08-05 | EN_PRUEBAS → EN_QA | orion-tester | Verificación independiente (no solo repetición de lo reportado por orion-dev): 17/17 CA en PASS, 216/216 tests, más pruebas funcionales end-to-end propias. Irregularidad de proceso confirmada y ampliada (commit c3abfce bundlea REQ-005/006/007 + reescritura de ui/ no relacionada). Handoff a orion-qa.
2026-08-05 | EN_QA (sin cambio de estado) | orion-qa | Auditoría de seguridad/logging/consistencia aprobada (✅ COMPLETADO en `pruebas/qa-audit-007.md`); irregularidad de proceso confirmada y documentada como asunto separado, no resuelta. Sigue en EN_QA hasta el OK del humano en la prueba manual — NO pasa a LISTO_PARA_COMMIT todavía.
