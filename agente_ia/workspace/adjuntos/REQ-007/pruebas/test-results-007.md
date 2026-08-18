# Resultados de prueba REQ-007 — Bucle de razonamiento real con LLM

**Fecha:** 2026-08-05
**Agente:** orion-tester

## ⚠️ Nota de proceso — irregularidad heredada, no generada en este paso

El código de REQ-007 llegó a `main` **antes** de pasar por `orion-tester`/`orion-qa`/aprobación
manual, vía dos commits que no mencionan REQ-007 en su mensaje:
- `b754ce3` (2026-07-22, "Fix mejora modulo Agente")
- `c3abfce` (2026-08-05, "Fix mejora agente UI funcioalidades")

Esto viola el checklist de `.claude/rules/git.md` ("orion-qa aprobó" + "el humano hizo la prueba
manual final" antes de cualquier commit). `orion-dev` de esta sesión ya lo documentó en
`propuestas/desarrollo-log-007.md`; este paso lo confirma y agrega un hallazgo adicional:

**Hallazgo nuevo de este paso:** `git show --stat c3abfce` muestra que ese commit no solo trae
los 9 archivos de REQ-007 — bundlea en el mismo commit atómico los cambios reales de
`core/security_manager.py`/`core/confirmation.py` (REQ-005), `core/resolution.py`/
`agents/tool_registry.py` (REQ-006), **y una reescritura completa de `ui/`**
(`ui/gui.py`, `ui/widgets/*` nuevo — 8 archivos, `ui/personality.py`, `ui/gui_workers.py`) junto
con ~20 archivos de test no relacionados a REQ-007. Efecto práctico: es imposible revertir o
aislar solo REQ-007 de ese commit si hiciera falta — quedó soldado a REQ-005/006 y a un cambio
de UI no documentado por ningún REQ de este tracker. No es un defecto del código de REQ-007 en
sí; se deja registrado para que el humano y `orion-qa` lo tengan presente al decidir cómo cerrar
el proceso de commit de este REQ.

No se tocó `ui/` ni ningún archivo fuera del alcance de REQ-007 durante esta verificación
(`core/`, `agents/`, `ai/`, `requirements.txt`, `tests/`), tal como se indicó al iniciar este
paso.

## Compilación
`python -m py_compile` sobre los 9 archivos afectados + 3 dependencias del gate de seguridad
(`core/reasoning_loop.py`, `agents/skill_tools.py`, `core/base_agent.py`, `core/orchestrator.py`,
`core/resolution.py`, `ai/llm_provider.py`, `main.py`, `skills/skill_manager.py`,
`agents/tool_registry.py`, `core/security_manager.py`, `core/confirmation.py`): **OK**, sin
errores.

## Tests existentes
- Suite completa (`python -m pytest tests/ --tb=short -q`), ejecutada de forma independiente en
  este paso (no se reutilizó el resultado reportado por `orion-dev`): **216 passed, 0 failed**
  (3 warnings cosméticos preexistentes, no relacionados).
- Coincide exactamente con lo reportado en `desarrollo-log-007.md` (baseline 95/0 →
  216/0, +121 tests nuevos, 0 regresiones).
- Ejecución dirigida y verbose de los 31 tests específicos de REQ-007 + regresión REQ-002
  (`test_reasoning_loop.py` 9, `test_llm_provider.py` 8, `test_skill_tools.py` 6,
  `test_base_agent.py` 3, `test_agents.py` 5): **31/31 PASS**, uno por uno confirmado por nombre.

## Verificación independiente adicional (más allá de la suite de pytest)

No se confió únicamente en lo que reportó `orion-dev` (mismo rol que habría implementado el
código) ni en los nombres de los tests. Se ejecutaron pruebas funcionales end-to-end propias,
con el `SkillManager` real y `tool_registry` real (solo `generate_response` mockeado):

| Prueba manual adicional | Resultado |
|---|---|
| `_decompose()` con 6 casos reales (`"hoy quiero..."`, `"voy... y compro pan"`, `"me llamo Yolanda"`, `"compra pan y luego café"`, `"él y tú vamos"`, `"muyyy cansado"`) | Los 6 casos se comportan exactamente como describe la SPEC (CA-12): word-boundary correcto, red de seguridad de longitud descarta el split de `"él y tú vamos"`. |
| `register_dispatcher_tool()` + `register_skill_tools()` sobre `SkillManager` real | Sin `RuntimeError` — 26 tools registrados (22 intents de skill + 1 dispatcher + 3 `task_manager` de REQ-006), coincide con el inventario de `baseline-007.md`. |
| `risk_level` de tools migrados vs `security_manager.classify_action()` en 6 intents reales (`SYS_POWER_OFF`, `TAKE_SCREENSHOT`, `GET_TIME`, `OPEN_FOLDER`, `EXECUTE_CODE`, `CREATE_SKILL`) | Los 6 coinciden exactamente (CA-15 confirmado con datos reales, no solo con el ejemplo hipotético de la SPEC). |
| `reasoning_loop.run()` end-to-end: LLM pide tool GREEN (`GET_TIME`) real | Ejecuta vía `execute_tool()`, responde con el resultado final tras 2 llamadas al LLM. |
| `reasoning_loop.run()` end-to-end: LLM pide tool YELLOW (`SYS_POWER_OFF`) sin adaptador de confirmación en canal desktop | `ActionDenied` fail-closed real corta el loop de inmediato — **1 sola llamada al LLM**, sin reintento (CA-08 confirmado con el gate real, no un mock de `execute_tool`). |
| `reasoning_loop.run()` con LLM que siempre pide tool (nunca da respuesta final) | Exactamente **5 llamadas al LLM**, cierra con el mensaje de límite, sin una 6ª (CA-07). |
| Mismo escenario anterior | `agent_context_manager.update_context()` llamado exactamente **2 veces** pese a 5 iteraciones internas (CA-10). |
| `reasoning_loop.run()` con tool inexistente en el registro | `execute_tool()` lanza `ActionDenied("tool no registrado")`, tratado igual que cualquier otra denegación (CA-08) — comportamiento documentado explícitamente en "Casos borde" de la SPEC. |
| `reasoning_loop.run()` con tool real que lanza `Exception` genérica (no `ActionDenied`) dentro de `invoke` | No crashea — se loguea como warning, el resultado fallido se agrega al historial y el LLM continúa en la siguiente iteración (CA-13 confirmado con una excepción real, no simulada por mock de `execute_tool`). |
| Lectura de `core/resolution.py::_try_claude()` | Cableado exactamente como describe "Opción A" aprobada: sin `claude_fn` cae en `reasoning_loop.run()`; con `claude_fn` inyectado, comportamiento sin cambios. |
| `grep ".invoke(" core/reasoning_loop.py` | Sin resultados — confirma CA-06 por evidencia estática directa, no solo por el test que ya lo verificaba. |
| `main.py` — grep de `AgentTool(` y `orchestrator.register_tool` | Sin llamadas reales (solo un comentario informativo) — confirma CA-17 (retiro de `register_tool()`/`self._tools`, `AgentTool` se mantiene por dependencia dura de `skill_manager.py`, documentado). |

## Criterios de la SPEC

| Criterio | Resultado | Nota |
|----------|-----------|------|
| CA-01 | PASS | `_DynamicAgentInstance.execute()` sin `for`, delega a `reasoning_loop.run()`; confirmado por lectura + ejecución real. |
| CA-02 | PASS | `_build_tool_list()` reusa `parameters_schema` tal cual, sin reescritura. |
| CA-03 | PASS | `generate_response(..., tools=None)` retrocompatible; tools solo se reenvían con `anthropic`/`deepseek`/`openai`. |
| CA-04 | PASS | `_ask_anthropic()` arma `input_schema`, parsea `tool_use` en `LLMToolResponse`; ya no asume `response.content[0].text`. |
| CA-05 | PASS | `_ask_openai()`/`_ask_deepseek()` arman `{"type":"function",...}`, parsean `tool_calls`. |
| CA-06 | PASS | Confirmado por grep estático (`.invoke(` ausente) y por ejecución real — todo pasa por `execute_tool()`. |
| CA-07 | PASS | Confirmado end-to-end: exactamente 5 llamadas al LLM, cierre con mensaje de límite, sin 6ª llamada. |
| CA-08 | PASS | Confirmado end-to-end con gate real (no mock): `ActionDenied` corta el loop en la 1ª iteración. |
| CA-09 | PASS | `generate_response()` usa `_uncached_call()` cuando hay `tools`, nunca `_cached_call()`; test dedicado en verde. |
| CA-10 | PASS | Confirmado end-to-end: `update_context()` exactamente 2 veces pese a 5 iteraciones internas. |
| CA-11 | PASS | `_build_tool_list()` no recibe `channel`; filtrado sigue siendo exclusivo de `execute_tool()`. |
| CA-12 | PASS | Confirmado con 6 casos manuales propios además del test existente — word boundary + red de seguridad correctos. |
| CA-13 | PASS | Confirmado end-to-end con excepción real (no mockeada): no crashea, LLM reintenta y responde. |
| CA-14 | PASS | 22 intents de skill + 1 dispatcher migrados; ninguno perdido silenciosamente (verificado por conteo real: 26 tools = 22+1+3 task_manager). |
| CA-15 | PASS | `risk_level` derivado de `security_manager.classify_action()`, confirmado con 6 intents reales; `RuntimeError` fail-closed si falta clasificación (código leído, comportamiento coherente con REQ-005). |
| CA-16 | PASS | `_make_skill_invoke()` llama `extract_params()` → `execute()`, sin `require_confirmation()` propio (confirmado por lectura directa). |
| CA-17 | PASS | Decisión documentada y verificada: `AgentTool` se mantiene (dependencia dura confirmada), `AgentOrchestrator.register_tool()`/`self._tools` eliminados (grep sin resultados en `main.py`/`core/orchestrator.py`). |
| Cableado (Pregunta 1, Opción A) | PASS | `core/resolution.py::_try_claude()` cae en `reasoning_loop.run()` sin `claude_fn`; con `claude_fn` mantiene comportamiento previo — confirmado por lectura directa del código real. |

**17/17 criterios de aceptación en PASS**, más el cableado de producción (Opción A) que la
arquitectura agregó como parte del alcance aprobado.

## Regresión

| Área revisada | Resultado |
|---------------|-----------|
| `tests/test_agents.py` (REQ-002, `AgentTool`/`AgentOrchestrator`) | PASS — 5/5, sin romper `test_ca2_base_agent` (que depende de `AgentTool` mantenido por CA-17). |
| `tests/test_base_agent.py` | PASS — 3/3 (3 de 4 tests originales reemplazados a propósito por el fix de CA-01, documentado en `arquitectura-007.md`; el 4to se conserva sin cambios). |
| `tests/test_tool_registry.py` (base de REQ-006, `execute_tool()`) | PASS — parte de los 216 verdes; no se detectó cambio de comportamiento del gate. |
| Suite completa (216 tests) | PASS — 0 fallos nuevos frente al baseline de 95/0 documentado por `orion-baseline`. |

## Veredicto: PASS

17/17 criterios de aceptación de SPEC-007 verificados de forma independiente (lectura de código
+ suite de pytest propia + pruebas funcionales end-to-end adicionales, no solo repetición de lo
reportado por `orion-dev`). Sin regresiones. La única salvedad es de **proceso**, no de código:
este REQ llegó a `main` sin pasar por `orion-tester`/`orion-qa`/aprobación manual antes del
commit, y el commit `c3abfce` bundlea REQ-007 junto con REQ-005/006 y una reescritura de `ui/`
no relacionada — ambos hallazgos quedan documentados arriba para que `orion-qa` y el humano los
tengan presentes, sin bloquear el avance técnico del REQ.
