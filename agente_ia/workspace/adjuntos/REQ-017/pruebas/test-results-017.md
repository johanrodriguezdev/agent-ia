# Resultados de prueba REQ-017 — Completar tareas en lote ("todas") sin trabarse

**Agente:** orion-tester
**Fecha:** 2026-08-20
**Fuentes verificadas:** `SPEC-017.md` (12 criterios de aceptación — el handoff de orion-dev decía
"11 CA", pero el recuento directo del archivo da 12, mismo recuento que ya señaló orion-architect en
`arquitectura-017.md` §1; no bloquea, se numeran CA-01 a CA-12 como hizo la arquitectura),
`arquitectura-017.md`, `desarrollo-log-017.md`, `baseline-017.md`.

**Metodología:** no se confió en el reporte de orion-dev. Cada criterio se verificó por lectura
directa de `core/resolution.py` y `agents/tool_registry.py` reales, y además con ejecución
independiente (scripts ad hoc fuera de los tests ya escritos por orion-dev) que ejercitan
`resolve()` end-to-end con `unittest.mock.patch` sobre `agents.tool_registry.execute_tool` como spy,
usando los textos literales documentados por `baseline-017.md` y por el handoff.

## Compilación
- `python -m py_compile core/resolution.py agents/tool_registry.py tests/test_resolution.py tests/test_tool_registry.py`: **OK**

## Tests existentes (suite completa, corrida independiente)
- Pasados: **437/439**
- Nuevos fallos: **ninguno**
- Fallos: 2, ambos preexistentes y ya documentados en `baseline-017.md`
  (`tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` y
  `test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto`, `ModuleNotFoundError: No module named
  'anthropic'` — dependencia no instalada en el entorno, sin relación con `core/resolution.py` ni
  `agents/tool_registry.py`).
- `tests/test_resolution.py` + `tests/test_tool_registry.py` + `tests/test_reasoning_loop.py` en
  aislado: **44 passed** (27 preexistentes + 17 nuevos de REQ-017, coincide con lo reportado por
  orion-dev).
- Confirmado con `git diff` que `tests/test_resolution.py` solo tuvo líneas **agregadas** (bloque
  nuevo al final, con separador "REQ-017"), ningún test preexistente fue modificado — consistente
  con CA-11 ("test de regresión... pasa sin modificaciones").
- Confirmado con `git diff --stat` que `tests/test_reasoning_loop.py` tiene **cero** diff.

## Criterios de la SPEC (12, numerados CA-01 a CA-12 como en `arquitectura-017.md`)

| CA | Criterio (resumen) | Resultado | Nota |
|----|---------------------|-----------|------|
| CA-01 | 2+ pendientes, "completar todas" → completa en lote, sin aclaración ni solo-listado | **PASS** | Verificado independientemente vía `resolve()` real (spy sobre `execute_tool`) con las 3 variantes de "todas" que `baseline-017.md` documentó cayendo en `task_list` antes de este REQ: `"completa todas las tareas pendientes"`, `"ya completé todas las tareas pendientes"`, `"termina todas mis tareas"` — las 3 ahora disparan `task_complete_all`, ninguna `task_list`. También verificadas las 2 variantes que antes no matcheaban ningún trigger (`"ya completé todas las pendientes"`, `"marca todas como completadas"`) — ambas ahora `bulk=True`. El bug original que motivó el REQ está corregido. |
| CA-02 | Mensaje confirma cuántas se completaron, con títulos/IDs, no genérico "listo" | **PASS** | Verificado con `execute_tool("task_complete_all", ...)` mockeando `list_tasks`/`complete_task`: mensaje real `"☑️ *¡Trabajo terminado!* Completé 2 tareas, Señor:\n• #1 - lavar el auto\n• #2 - pagar la luz"`. Test `test_mensaje_bulk_lista_ids_y_titulos` y `test_task_complete_all_completa_todas_las_pendientes` confirman lo mismo. |
| CA-03 | 1 pendiente, sin ID → sin cambios | **PASS** | `test_un_pendiente_sin_id_sin_cambios` usa texto que ya matchea `_is_task_complete_phrase()` hoy ("ya completé la tarea", ajuste de datos de prueba documentado por orion-dev, verificado correcto — "ya completé mi tarea" en efecto no matchea por el stem "completad"); resuelve vía `task_complete`, no `task_complete_all`, mismo mensaje de auto-deducción. Rama de código sin tocar (confirmado por lectura). |
| CA-04 | 0 pendientes → sin cambios | **PASS** | `test_cero_pendientes_sin_cambios` y `test_task_complete_all_cero_pendientes` cubren ambas ramas (list y el tool nuevo). Mensajes iguales a los preexistentes documentados por `baseline-017.md`. |
| CA-05 | ID explícito → sin cambios, completa solo esa, incluso con "todas" en otro sentido | **PASS** | Verificado independientemente con los 2 ejemplos literales de casos borde de la SPEC: `"de todas mis tareas, la #3 ya la hice"` y `"de todas mis tareas, completa la #3"` — ambos resuelven `task_complete` (no `task_complete_all`), con `text` intacto pasado al tool. `has_explicit_task_id()` confirmado como el desempate real en `_try_task_tool()` por lectura de código. |
| CA-06 | Mismo texto → mismo resultado en Desktop/Telegram/Discord, con ≥1 test por canal ejercitando `resolve()` end-to-end con `user_id`/`channel` real | **PASS** | `test_mismo_texto_bulk_en_3_canales` en `tests/test_resolution.py` es un test real (no placeholder): llama `resolve()` 3 veces con `ChannelType.DESKTOP/user_id="default"`, `ChannelType.TELEGRAM/user_id="123"`, `ChannelType.DISCORD/user_id="discord_456"` — mismos valores que documentó `orion-spec` en el contexto como los `user_id` reales de cada canal. Verificado independientemente con script propio: los 3 canales disparan `task_complete_all`, cada uno completa únicamente sus propias tareas (partición por `user_id` preexistente respetada). |
| CA-07 | Cada tarea completada pasa por `execute_tool()` (gate real) | **PASS** | `test_task_complete_all_pasa_por_gate` usa un spy real sobre `security_manager.require_confirmation` (no mock ciego — envuelve la función original) y confirma orden de llamadas: `require_confirmation("task_complete_all", ...)` ANTES de cualquier `complete_task`. Confirmado también por lectura: `_task_complete_all_invoke` es la única función que llama a `task_manager.complete_task()` en bucle, y solo se alcanza dentro de `execute_tool()` después del gate. |
| CA-08 | Sin confirmación adicional (GREEN se mantiene) | **PASS** | `risk_level=RiskLevel.GREEN` confirmado en el `ToolSpec` real. `test_task_complete_all_es_green_sin_confirmar` usa un `input()` que lanza `AssertionError` si se llama — no se dispara. |
| CA-09 | `delete_task`/🟡/🔴 sin cambios de comportamiento, test de regresión | **PASS** | `test_delete_task_yellow_sigue_bloqueado_en_lote` no es un placeholder: llama `security_manager.require_confirmation("delete_task", ChannelType.TELEGRAM, ...)` real (sin mocks) y confirma `False`. `core/security_manager.py` sin diff de REQ-017 (el único diff presente en el archivo es de REQ-015/016, identificado por comentarios explícitos en el propio diff, confirmado con `git diff`). |
| CA-10 | `/completar [id]` de Telegram sigue igual, sin tocar `telegram_bot.py` | **PASS** | `git diff --stat -- channels/telegram_bot.py` → sin salida (cero cambios). |
| CA-11 | `reasoning_loop`, `RESOLVERS` y demás resolvers sin cambios de comportamiento; tests de regresión pasan sin modificaciones | **PASS** | `git diff --stat -- core/reasoning_loop.py` → sin salida. `RESOLVERS` (lista y orden, 7 resolvers `routine→autopilot→learned→task_tool→capability→intent→claude`) confirmado idéntico por lectura. `tests/test_reasoning_loop.py` sin diff, 9/9 passed. Tests preexistentes de `test_resolution.py` solo tuvieron líneas agregadas al final, ninguno modificado. |
| CA-12 | Suite pytest completa sin nuevos fallos | **PASS** | Corrida independiente: `2 failed, 437 passed` — mismos 2 fallos preexistentes de `test_llm_provider.py` documentados en `baseline-017.md`, sin regresión nueva. |

**Veredicto por criterio: 12/12 PASS.**

## Verificaciones adicionales pedidas explícitamente en el handoff

- **Desambiguación "completa todas las tareas pendientes" ya NO devuelve el listado** — confirmado
  con las 4 variantes literales de `baseline-017.md` (3 con "todas" ahora completan en lote; la 4ª,
  `"completa mis tareas"`, no contiene "todas" así que correctamente sigue resolviendo `task_list`
  sin cambios — no era parte del bug a corregir).
- **ID explícito + "todas" en el mismo texto → gana el ID** — confirmado con caso concreto
  (`"de todas mis tareas, completa la #3"` → `task_complete`, no `task_complete_all`).
- **"todo" (singular) NO dispara el lote** — probado `"todo bien, completa la tarea"` y `"eso es
  todo, completa la tarea"`: ambos con `_is_bulk_complete_phrase()==False`; end-to-end, el primero ni
  siquiera es interceptado por `_try_task_tool` (cae a `intent:PC_SCROLL`, comportamiento del
  clasificador general, sin relación con este REQ ni regresión). Frase de lote real sin la palabra
  "todo" (`"completa todas las tareas pendientes"`) confirmada disparando el lote correctamente — el
  ajuste de Johan no rompió el caso positivo.
- **3 canales cubiertos automáticamente por tocar `_try_task_tool()` una sola vez** — confirmado:
  `_try_task_tool` no depende de `channel` ni de `claude_fn`, y el test `test_mismo_texto_bulk_en_3_canales`
  ejercita `resolve()` end-to-end con los `user_id` reales de cada canal (no placeholders).
- **Tope de 20 tareas por invocación** — confirmado en código (`_TASK_COMPLETE_ALL_LIMIT = 20`) y
  probado manualmente con 20 pendientes: completa las 20 y agrega la nota `"Procesé el máximo de 20
  tareas por vez. Si tiene más pendientes, puede pedírmelo de nuevo."` — comportamiento razonable,
  sin excepción ni corte abrupto.
- **No-regresión de `core/reasoning_loop.py`, `RESOLVERS`, `security_manager.py`** — confirmado sin
  diff en los dos primeros; el diff presente en `security_manager.py` es de REQ-015/016 (comentarios
  explícitos en el propio diff lo identifican), no de REQ-017.
- **`task_complete`/`task_complete_all` siguen GREEN, sin confirmación** — confirmado en código y con
  test que falla si se invoca `input()`.
- **No-regresión general de REQ-015/016** — la suite completa (437 passed) incluye toda la cobertura
  de esos REQs sin nuevos fallos; no se detectó ninguna sorpresa fuera de los 2 fallos preexistentes
  ya conocidos.

## Regresión

| Área revisada | Resultado |
|---------------|-----------|
| `core/resolution.py` — resto de `RESOLVERS` (routine, autopilot, learned, capability, intent, claude) | Sin cambios de comportamiento (código sin tocar fuera de `_try_task_tool`, tests preexistentes pasan) |
| `core/reasoning_loop.py` | Sin diff, 9/9 tests preexistentes pasan |
| `core/security_manager.py` | Sin diff atribuible a REQ-017 |
| `channels/telegram_bot.py`, `channels/discord_bot.py`, `channels/gateway.py` | Sin diff |
| `tasks/task_manager.py` | Sin diff, firmas `list_tasks()`/`complete_task()` reutilizadas tal cual |
| Suite completa (439 tests) | 437 passed, 2 failed (preexistentes, no relacionados) |

## Veredicto: **PASS**

12/12 criterios de aceptación de SPEC-017.md verificados PASS por ejecución directa e independiente
(no por confianza en el reporte de orion-dev). Sin regresiones nuevas. El REQ pasa a `orion-qa`.
