# Auditoría QA REQ-007 — Bucle de razonamiento real con LLM

**Fecha:** 2026-08-05
**Agente:** orion-qa

## ⚠️ Hallazgo de proceso — separado del veredicto técnico

Este código llegó a `main` **antes** de pasar por `orion-tester`/`orion-qa`/aprobación manual
del humano, vía dos commits que no mencionan REQ-007 en su mensaje:

- `b754ce3` (2026-07-22, "Fix mejora modulo Agente")
- `c3abfce` (2026-08-05, "Fix mejora agente UI funcioalidades")

Esto viola el checklist de `.claude/rules/git.md` ("orion-qa aprobó" + "el humano hizo la
prueba manual final" antes de cualquier commit). `orion-dev` y `orion-tester` ya lo
documentaron en `propuestas/desarrollo-log-007.md` y `pruebas/test-results-007.md`
respectivamente. `orion-tester` agregó un hallazgo adicional que confirmo por lectura propia
de `git show --stat c3abfce`: ese commit no es aislable a REQ-007 — bundlea en un solo commit
atómico:

- Los 9 archivos de REQ-007 (`core/reasoning_loop.py`, `agents/skill_tools.py`, etc.)
- Cambios reales de REQ-005 (`core/security_manager.py`, `core/confirmation.py`)
- Cambios reales de REQ-006 (`core/resolution.py`, `agents/tool_registry.py`)
- Una reescritura completa de `ui/` (`ui/gui.py`, `ui/widgets/*` nuevo — 8 archivos,
  `ui/personality.py`, `ui/gui_workers.py`) no asociada a ningún REQ del tracker
- ~20 archivos de test no relacionados a REQ-007

**Efecto práctico:** no existe forma de revertir o aislar solo REQ-007 de ese commit si en
algún momento hiciera falta — quedó soldado a REQ-005/006 y a un cambio de UI sin REQ propio.

**No resuelvo esta irregularidad ni decido si hay que revertir nada — es decisión del
humano.** La dejo documentada como hallazgo de proceso, independiente de si el código en sí
cumple la SPEC y los estándares de seguridad/calidad (sí los cumple, ver abajo). Dos
consecuencias prácticas que sí planteo para que el humano decida, no como conclusión propia:

1. El "mensaje de commit sugerido" que este agente entregaría al final de este flujo (paso 7,
   tras el OK manual) sería **documental únicamente** — no hay nada que commitear, porque el
   código ya está commiteado. Sirviría como registro retroactivo en el tracker de qué REQ
   cubre qué ya-commiteado, no como un `git commit` real pendiente.
2. Si el humano quisiera en algún momento auditar o revertir selectivamente REQ-005/006/007
   o el cambio de `ui/`, hoy no puede hacerlo a nivel de commit — tendría que ser a nivel de
   archivo/función.

## Seguridad

Revisión de `core/reasoning_loop.py`, `agents/skill_tools.py`, `agents/tool_registry.py`,
`ai/llm_provider.py`, `core/base_agent.py`, `core/orchestrator.py`, `core/resolution.py` y
`main.py` (los 9 archivos de REQ-007 + los puntos de gate que consumen).

- **Sin API keys/tokens hardcodeados.** `_ask_anthropic`/`_ask_openai`/`_ask_deepseek` leen
  `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`get_deepseek_api_key()` de entorno o `config.json`
  (patrón preexistente a REQ-007, no introducido por este REQ). Grep dirigido de patrones de
  key literal (`sk-...`, `api_key = "..."`) sobre todo el árbol: sin resultados.
- **Ejecución de tools exclusivamente vía `execute_tool()`.** Confirmado por lectura de
  `core/reasoning_loop.py` línea 112: la única llamada de ejecución es
  `execute_tool(call.name, params, resolved_channel, user_id)`. Grep de `.invoke(` en el
  archivo: sin resultados (coincide con CA-06 y con lo reportado por `orion-tester`). Esto
  es el punto crítico de seguridad de todo el REQ — un loop dirigido por LLM que pudiera
  saltarse el gate sería el escenario de mayor riesgo, y no ocurre.
- **`channel`/`user_id` nunca vienen del LLM.** `run()` documenta el invariante
  explícitamente (líneas 72-77) y lo aplica: `params["channel"] = resolved_channel.value` y
  `params["user_id"] = user_id` se asignan **después** de copiar `call.arguments`,
  sobrescribiendo cualquier valor que el LLM hubiera propuesto para esas claves. Correcto —
  mismo invariante que ya regía en `security_manager.py`/`resolution.py` desde REQ-005/006.
- **`agents/skill_tools.py::register_skill_tools()` — fail-closed real.** Si un intent no
  tiene `risk_level` clasificado en `security_manager`, se lanza `RuntimeError` en tiempo de
  carga en vez de registrar el tool con un nivel inventado (líneas 58-64). Verificado que
  esto es consistente con `agents/tool_registry.py::ToolSpec` (campo `risk_level` sin
  default — un `ToolSpec` sin nivel no compila).
- **`agents/skill_tools.py::_make_skill_invoke()` no duplica el gate.** El `invoke` migrado
  llama `extract_params()` → `execute()` sin volver a llamar
  `security_manager.require_confirmation()` por su cuenta (CA-16) — evita el bug de forma
  que antes hacía que una denegación se devolviera como si fuera una respuesta exitosa. El
  gate real ocurre una sola vez, dentro de `execute_tool()`.
- **Acciones destructivas piden confirmación.** El camino sigue siendo:
  `reasoning_loop.run()` → `execute_tool()` → `security_manager.require_confirmation()`.
  Ninguna tool YELLOW/RED se ejecuta sin pasar por ahí — no hay atajo nuevo introducido por
  el loop. `ActionDenied` corta el loop de inmediato (CA-08) sin reintento ni nueva consulta
  al LLM, verificado en código (`reasoning_loop.py` líneas 113-117) y en la prueba end-to-end
  de `orion-tester` con el gate real (no mockeado).
- **`_build_tool_list()` no filtra por canal (CA-11), por diseño explícito de la SPEC** — el
  LLM ve el mismo catálogo de tools sin importar `DESKTOP`/`TELEGRAM`/`DISCORD`/`VOICE`. Esto
  es correcto siempre que `execute_tool()` siga siendo el único punto real de decisión, que
  es lo que confirmé arriba. Nota para tenerlo presente (no es un hallazgo, es documentación
  de diseño): en canal `VOICE`, donde `CHANNEL_ALLOWED_LEVELS` solo permite GREEN, el LLM
  puede "elegir" una tool YELLOW/RED igual, y el gate la deniega — comportamiento esperado,
  ya cubierto por la lógica de `security_manager.py` de REQ-005, sin cambios de este REQ.
- **Prompt de sistema (`_SYSTEM_PROMPT`) sin secretos ni instrucciones que debiliten el
  gate** — no le pide al LLM clasificar riesgo ni le da autoridad sobre confirmaciones;
  solo le pide no reintentar tras una denegación (redundante con lo que el código ya fuerza
  estructuralmente en CA-08, no es la única defensa).

## Niveles de riesgo

- **Verde (puede actuar sin preguntar):** herramientas GREEN migradas de skills (ej.
  `GET_TIME`, `OPEN_FOLDER` según muestreo de `orion-tester`), el `"dispatcher"` catch-all
  (`CONFIRMADO 5`, GREEN — el gate real ocurre dentro de `dispatch()` según la acción que
  finalmente resuelve), `task_create`/`task_list`/`task_complete` (heredados de REQ-006).
- **Amarillo (debe confirmar):** herramientas YELLOW migradas de skills (ej. `CLOSE_APP`
  según SPEC; `SYS_POWER_OFF` fue verificado por `orion-tester` como caso real que corta el
  loop por `ActionDenied` en canal desktop sin adaptador de confirmación — comportamiento
  fail-closed correcto para ese escenario, no una omisión).
- **Rojo (no ejecuta):** ninguna acción RED del deny-list de REQ-005 se reclasifica ni se
  evita en este REQ — `register_skill_tools()` reutiliza `security_manager.classify_action()`
  tal cual (CA-15), sin inventar niveles nuevos.
- **Se implementaron confirmaciones:** sí — sin cambios al mecanismo (`require_confirmation()`
  de `security_manager.py`/`core/confirmation.py`, ambos fuera de alcance de REQ-007 y no
  tocados). El loop nuevo se apoya en el gate existente en vez de reimplementarlo o
  evitarlo, que era el riesgo principal a verificar en esta auditoría.

## Logging

- Sin `except: pass` ni `except Exception: pass` silencioso en ningún archivo de REQ-007.
  Grep dirigido (`except.*:\s*pass$`) sobre todo el árbol del proyecto: sin resultados.
- `core/reasoning_loop.py` línea 121: `logger.warning(...)` antes de tratar una excepción de
  tool como resultado fallido de iteración (CA-13) — correcto, registra antes de continuar.
- `agents/tool_registry.py::register_tool()` y `agents/skill_tools.py::register_skill_tools()`
  registran en `logger.info` cada tool que se da de alta — trazabilidad del inventario de
  herramientas en el arranque.
- `core/resolution.py::resolve()` línea 282: `logger.warning` si algún resolver dejara escapar
  un `ActionDenied` sin capturarlo — red de seguridad de logging, no solo de ejecución.
- **Hallazgo menor, no bloqueante, no introducido por REQ-007:**
  `ai/llm_provider.py::get_provider_config()` (línea 65-78) usa `except Exception:` sin
  logging antes de devolver defaults (`"anthropic", "", "", ""`). Confirmado por
  `git log -p` que esta función existe con la misma forma desde antes de los commits de
  REQ-007 — es deuda preexistente, no algo que este REQ haya agregado. Lo señalo para que
  quede registrado, pero no es motivo de rechazo de REQ-007: ese archivo sí cumple
  `python-style.md` en todo el código nuevo que agrega (`_ask_anthropic`/`_ask_openai`/
  `_ask_deepseek` con tools, parseo de `tool_calls`).
- `except (json.JSONDecodeError, TypeError): args = {}` en `_ask_openai`/`_ask_deepseek`
  (parseo de argumentos de tool call malformados) tampoco loguea antes de continuar. Es un
  caso cubierto explícitamente por el "Caso borde" de SPEC-007 ("tool call malformado... no
  debe crashear"), y el resultado (`args = {}`) igual pasa por `execute_tool()` con params
  vacíos, quedando sujeto al mismo `except Exception` con `logger.warning` de
  `reasoning_loop.py` si `invoke()` falla por falta de parámetros. No es un agujero de
  seguridad (no hay ejecución sin gate), pero es una desviación menor de
  `python-style.md` ("Siempre registrar el error antes de ignorarlo"). Lo marco como mejora
  menor sugerida, no como bloqueante — no oculta una denegación ni una acción destructiva,
  solo un parseo de argumentos que de todas formas termina logueado un nivel más arriba.

## Consistencia de código

- Convenciones de `python-style.md` respetadas en el código nuevo: type hints en funciones
  públicas nuevas (`_build_tool_list() -> list[dict]`, `run(...) -> str`, etc.), `snake_case`
  para funciones, imports ordenados (estándar → third-party → local) en
  `core/reasoning_loop.py` y `agents/skill_tools.py`.
- Sin `print()` de debug en ningún archivo de REQ-007 — grep dirigido sin resultados.
- Sin dead code evidente en los archivos de REQ-007. `core/base_agent.py::AgentTool` y
  `_DynamicAgentInstance.tools` se conservan deliberadamente (decisión documentada en
  arquitectura-007.md "Decisión CA-17": dependencia dura de `skills/skill_manager.py` y de
  `tests/test_agents.py`) — no es código muerto sin justificar, es una decisión de
  arquitectura explícita con motivo registrado.
  `AgentOrchestrator.register_tool()`/`self._tools` sí se eliminaron de
  `core/orchestrator.py` — confirmado por lectura directa del archivo, no queda rastro salvo
  el comentario informativo en `main.py`.
- `requirements.txt` sin cambios — coincide con lo declarado por arquitectura (sin
  dependencias nuevas) y confirmado independientemente.
- Compilación (`python -m py_compile`) limpia en los 9 archivos afectados + los 2 módulos de
  gate (`core/security_manager.py`, `core/confirmation.py`) — reejecutada de forma
  independiente en este paso, no solo repetida de los agentes anteriores.
- Suite dirigida (31 tests: `test_reasoning_loop.py`, `test_llm_provider.py`,
  `test_skill_tools.py`, `test_base_agent.py`, `test_agents.py`) reejecutada de forma
  independiente en este paso: **31/31 PASS**, coincide exactamente con lo reportado por
  `orion-dev` y `orion-tester`.

## Veredicto: ✅ COMPLETADO

Los 17 criterios de aceptación de SPEC-007 están verificados de forma independiente por
tres roles distintos (`orion-dev` retroactivo, `orion-tester`, y esta auditoría de
`orion-qa`), con evidencia de código real, no solo repetición de reportes previos. El punto
de mayor riesgo del REQ — que un bucle dirigido por LLM pudiera ejecutar acciones sin pasar
por el gate de seguridad — está descartado por lectura directa (`execute_tool()` es el único
camino de ejecución, sin `.invoke()` directo en ningún punto) y por prueba end-to-end con el
gate real. Sin secretos expuestos, sin `except: pass` silencioso introducido por este REQ, sin
duplicación del gate de confirmación, sin regresiones (216/216 tests, 121 nuevos).

El hallazgo de proceso (código commiteado en `main` sin pasar por el pipeline, mezclado con
REQ-005/006 y una reescritura de `ui/` no relacionada) **no invalida el veredicto técnico** —
se documenta arriba como asunto separado para que el humano decida cómo proceder.

## Prueba manual solicitada al humano

Dado que el código ya está en `main` desde hace días y en uso, esta prueba manual no es un
"antes de mergear" — es una verificación de que lo que ya corre en producción se comporta como
describe la SPEC, en condiciones reales (LLM real, no mockeado, que es lo único que ninguna de
las tres verificaciones anteriores pudo cubrir).

1. Con Noddoo corriendo normalmente (canal desktop, proveedor `anthropic` o `deepseek` activo
   en `config.json`), pide algo que requiera una tool GREEN real, ej. *"¿qué hora es?"* o
   *"abre la calculadora"*. Verifica que responda correctamente y que en los logs
   (`logger.info` de `reasoning_loop`/`tool_registry`) se vea la tool elegida y ejecutada.
2. Pide algo que encadene razonamiento, ej. *"recuérdame comprar pan en una hora y avísame"*
   (task compuesta) — verifica que la respuesta tenga sentido y no se cuelgue ni tarde
   excesivamente (límite de 5 llamadas al LLM).
3. Pide una acción YELLOW real, ej. *"cierra el bloc de notas"* (si está abierto) o intenta
   apagar el PC por voz/texto — verifica que **pida confirmación explícita** antes de
   ejecutar, y que si respondes que no, la acción no se ejecute.
4. Verifica el criterio principal del REQ: que la respuesta a un pedido ambiguo o que
   requiere info previa (ej. *"¿tengo tareas pendientes?"* seguido de *"marca la primera como
   completada"*) demuestre que el sistema está *razonando sobre el resultado*, no solo
   probando herramientas en orden fijo como antes de este REQ.

Responde:
- OK → entrego el mensaje de commit sugerido (documental, ver nota de proceso arriba — el
  código ya está commiteado, esto quedaría como registro retroactivo en el tracker)
- FALLA [descripción] → vuelve a orion-dev
