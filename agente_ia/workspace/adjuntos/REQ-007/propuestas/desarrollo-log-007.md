# Desarrollo REQ-007 — Bucle de razonamiento real con LLM

**Fecha:** 2026-08-05
**Agente:** orion-dev

## Hallazgo previo a implementar — código ya existente y ya commiteado

Antes de escribir una sola línea, `orion-dev` leyó `REQ-007-context.md`, `SPEC-007.md`,
`arquitectura-007.md` y `origen/baseline-007.md` completos, y luego el código real de los
módulos que la arquitectura ordena tocar. **Los 9 archivos que `arquitectura-007.md` lista en
"Archivos a modificar/crear" ya existen en el working tree y coinciden literalmente con el
diseño aprobado** (mismos nombres de función, misma lógica, mismos comentarios `REQ-007/CA-XX`
citando los criterios uno por uno).

Verificado con `git log --diff-filter=A -- <archivo>`: los archivos nuevos
(`core/reasoning_loop.py`, `agents/skill_tools.py`, `tests/test_reasoning_loop.py`,
`tests/test_llm_provider.py`, `tests/test_skill_tools.py`) y las modificaciones a
`core/base_agent.py`, `core/orchestrator.py`, `core/resolution.py`, `ai/llm_provider.py`,
`main.py`, `tests/test_base_agent.py` ya están **commiteados** en:
- `b754ce3` (2026-07-22, "Fix mejora modulo Agente")
- `c3abfce` (2026-08-05, "Fix mejora agente UI funcioalidades")

Ninguno de los dos mensajes de commit menciona REQ-007, y `REQ-007-context.md`/
`requerimientos.csv` seguían en `ARQUITECTURA_APROBADA` / "Último agente: orion-architect" al
iniciar esta sesión — el trabajo de implementación se hizo (probablemente por el humano
directamente, o en una sesión no documentada), pero nunca se cerró el ciclo de tracking del
pipeline O.R.I.O.N. (sin `desarrollo-log-007.md`, sin actualización de contexto, sin avance de
`Estado` en el CSV).

**Decisión de esta sesión:** no reescribir código que ya está correcto y ya en git — eso
arriesgaría romper algo que funciona sin necesidad. En su lugar, `orion-dev` hizo una
verificación completa de que el código existente cumple `arquitectura-007.md`/`SPEC-007.md`
criterio por criterio, y produce esta documentación retroactiva para que el pipeline (tracker,
contexto, y el siguiente agente `orion-tester`) tenga el registro que le falta. No se
ejecutó ningún `git commit`/`add`/`push` en esta sesión — no hacía falta, el código ya estaba
commiteado antes de que esta sesión empezara.

## Verificación realizada (no implementación nueva)

- `python -m py_compile` limpio en los 9 archivos afectados (`core/reasoning_loop.py`,
  `core/base_agent.py`, `core/orchestrator.py`, `core/resolution.py`, `ai/llm_provider.py`,
  `agents/skill_tools.py`, `agents/tool_registry.py`, `main.py`, `skills/skill_manager.py`).
- `python -m pytest tests/ --tb=short -q` → **216 passed, 0 failed** (baseline era 95
  passed/0 failed — 121 tests nuevos, 0 regresiones).
- Ejecución dirigida de los tests de este REQ (31 tests, todos verdes):
  `tests/test_reasoning_loop.py` (9), `tests/test_llm_provider.py` (8),
  `tests/test_skill_tools.py` (6), `tests/test_base_agent.py` (3),
  `tests/test_agents.py` (5, regresión REQ-002 sin romper).
- Cobertura por criterio confirmada por lectura de código + nombre de test:
  - **CA-01**: `_DynamicAgentInstance.execute()` sin `for tool in self.tools`, delega a
    `reasoning_loop.run()` — `test_dynamic_agent_execute_delega_a_reasoning_loop`.
  - **CA-02**: `_build_tool_list()` expone `parameters_schema` sin reescritura —
    `test_build_tool_list_expone_parameters_schema_sin_modificar`.
  - **CA-03/CONFIRMADO 1**: `generate_response(..., tools=None)` retrocompatible; degradación
    silenciosa fuera de `anthropic`/`deepseek`/`openai` —
    `test_ca03_generate_response_sin_tools_comportamiento_no_roto`,
    `test_confirmado1_gemini_ignora_tools_en_silencio`.
  - **CA-04/CA-05**: `_ask_anthropic`/`_ask_openai`/`_ask_deepseek` parsean `tool_use`/
    `tool_calls` en `LLMToolResponse` — `test_ca04_*`, `test_ca05_*`.
  - **CA-06**: grep estático confirma que `core/reasoning_loop.py` no llama `.invoke(` en
    ningún punto (solo `execute_tool()`) — `test_ca06_reasoning_loop_nunca_llama_invoke_directo`.
  - **CA-07**: `MAX_LLM_CALLS = 5`, sin 6ª llamada — `test_ca07_agota_5_llamadas_sin_una_sexta`.
  - **CA-08**: `ActionDenied` corta el loop de inmediato —
    `test_ca08_action_denied_corta_de_inmediato`.
  - **CA-09**: `generate_response()` bypasea `_cached_call()` cuando hay `tools` —
    `test_ca09_generate_response_bypassa_cache_con_tools`.
  - **CA-10**: `agent_context_manager.update_context()` exactamente 2 veces por invocación —
    `test_ca10_update_context_se_llama_exactamente_dos_veces`.
  - **CA-11**: `_build_tool_list()` no recibe `channel` —
    `test_build_tool_list_no_filtra_por_channel`.
  - **CA-12**: `_decompose()` con `\b` + `all(len(p) > 3 for p in parts)` en
    `core/orchestrator.py` (verificado por lectura directa, casos "hoy"/"voy a la tienda y
    compro pan" cubiertos en `tests/test_agents.py`).
  - **CA-13**: `except Exception` genérico dentro del loop, no crashea —
    `test_ca13_exception_generica_no_crashea_y_sigue_el_loop`.
  - **CA-14/CONFIRMADO 4**: `register_skill_tools()` nombra cada `ToolSpec` con el `Intent`
    crudo — `test_ca14_confirmado4_intent_real_se_registra_con_nombre_crudo`.
  - **CA-15**: `risk_level` viene de `security_manager.classify_action()`, `RuntimeError`
    fail-closed si falta clasificación — `test_ca15_risk_level_viene_de_security_manager_no_inventado`,
    `test_ca15_intent_sin_clasificar_falla_cerrado`.
  - **CA-16**: `invoke` llama `extract_params()` → `execute()`, sin `require_confirmation()`
    propio — `test_ca16_invoke_llama_extract_params_luego_execute_sin_auto_gate`.
  - **CA-17**: `AgentTool` se mantiene (dependencia dura de `skills/skill_manager.py` y
    `tests/test_agents.py`, documentado en `arquitectura-007.md` "Decisión CA-17");
    `AgentOrchestrator.register_tool()`/`self._tools` eliminados de
    `core/orchestrator.py` — confirmado por grep, ningún caller real los usa hoy salvo un
    comentario informativo en `main.py`.
  - **Cableado (Pregunta 1, Opción A)**: `core/resolution.py::_try_claude()` cae en
    `core/reasoning_loop.run()` cuando no hay `claude_fn` inyectado; con `claude_fn` (p.ej.
    `channels/gateway.py`) el comportamiento no cambia — confirmado por lectura del código.
- `requirements.txt`: sin diferencias — confirmado (`git diff requirements.txt` vacío), tal
  como anticipaba la arquitectura ("Dependencias nuevas: Ninguna").
- Sin `except: pass` silencioso, sin `print()` de debug, sin API keys/tokens hardcodeados en
  `core/reasoning_loop.py` ni `agents/skill_tools.py` (grep dirigido, sin resultados).

## Archivos verificados (ya modificados/creados antes de esta sesión, no por `orion-dev` en
esta sesión)
- `core/reasoning_loop.py` (nuevo)
- `agents/skill_tools.py` (nuevo)
- `core/base_agent.py` (modificado — `_DynamicAgentInstance.execute()`)
- `core/orchestrator.py` (modificado — `_decompose()`, retiro de `register_tool()`/`self._tools`)
- `core/resolution.py` (modificado — `_try_claude()` cablea `reasoning_loop.run()`)
- `ai/llm_provider.py` (modificado — tool-calling en `anthropic`/`deepseek`/`openai`)
- `main.py` (modificado — registro de tools vía `agents/skill_tools.py`)
- `tests/test_reasoning_loop.py` (nuevo)
- `tests/test_llm_provider.py` (nuevo)
- `tests/test_skill_tools.py` (nuevo)
- `tests/test_base_agent.py` (modificado — 3 de 4 tests reemplazados, 1 conservado, tal como
  documenta "Disposición de tests/test_base_agent.py" en `arquitectura-007.md`)

## Dependencias agregadas
Ninguna — confirmado, sin diferencias en `requirements.txt`.

## Decisiones de implementación
Ninguna decisión nueva de esta sesión — el código ya construido sigue `arquitectura-007.md`
al pie de la letra, incluyendo la Decisión CA-17 (qué se elimina vs qué se conserva) ya
documentada en ese archivo. La única decisión de esta sesión fue **no tocar código que ya
está correcto y en git**, y documentar el estado real en su lugar.

## Pendiente para orion-tester / orion-qa
- Confirmar independientemente los 17 CA (esta verificación fue hecha por el mismo rol que
  habría implementado el código, conviene una segunda mirada).
- Señalar al humano, en algún punto del pipeline, el proceso irregular por el que este código
  llegó a `main` sin pasar por `orion-tester`/`orion-qa`/aprobación manual antes del commit
  (`c3abfce`/`b754ce3`) — no es un bloqueante técnico, pero rompe el checklist de
  `.claude/rules/git.md` ("orion-qa aprobó" + "el humano hizo la prueba manual final" antes
  de cualquier commit).
