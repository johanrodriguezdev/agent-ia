# Baseline REQ-017

**Agente:** orion-baseline
**Fecha:** 2026-08-20
**Rama git verificada:** `feature/REQ-015-webview-ui` (sigue siendo la rama activa del working
tree; REQ-017 tampoco tiene rama propia todavía, igual que REQ-016 — pendiente de decisión del
humano, lo confirma `orion-architect` según `.claude/rules/git.md`).

## Nota de working tree — mismo estado compartido que REQ-015/016

`git status --short` confirma el mismo diff sin commitear de REQ-015 (12 `D` en `ui/widgets/*`,
`ui/gui.py`, `ui/theme.py`; varios `M`; `ui/webview/` y `tests/test_webview_*.py` sin trackear),
más `workspace/adjuntos/REQ-014/`, `REQ-015/`, `REQ-016/`, `REQ-017/` sin trackear. Ninguno de los
3 archivos que este REQ va a tocar (`core/resolution.py`, `agents/tool_registry.py`,
`tasks/task_manager.py`) aparece en el `git status` — están en su estado committeado limpio, sin
relación con el diff pendiente de REQ-015/016. También apareció `workspace/adjuntos/REQ-018/` sin
trackear (otro REQ en curso en paralelo, fuera del alcance de esta sesión).

## Estado actual del sistema

### `core/resolution.py` — comportamiento EXACTO confirmado leyendo el archivo completo

Triggers léxicos (líneas 116-130):
```python
_TASK_CREATE_TRIGGERS = (
    "recuérdame", "recuerdame", "recordarme", "recordatorio",
    "agrega tarea", "agregar tarea", "nueva tarea", "crear tarea",
    "no olvidar", "no olvides", "pendiente:", "tarea:",
)
_TASK_LIST_TRIGGERS = (
    "mis tareas", "tareas pendientes", "tareas programadas", "listado de tareas",
    "lista de tareas", "ver tareas", "qué tareas", "que tareas", "dime mis tareas",
    "cuáles son mis tareas", "cuales son mis tareas",
)
_TASK_COMPLETE_TRIGGERS = (
    "ya complete la tarea", "ya completé la tarea", "tarea terminada", "tarea completada",
    "marcar tarea", "ya termine la tarea", "ya terminé la tarea", "listo complete la tarea",
    "listo termine la tarea",
)
```

`_is_task_complete_phrase()` (líneas 133-141):
```python
def _is_task_complete_phrase(text_lower: str) -> bool:
    if any(t in text_lower for t in _TASK_COMPLETE_TRIGGERS):
        return True
    mentions_task = "tarea" in text_lower or "recordatorio" in text_lower
    mentions_done = (
        "listo" in text_lower or "hecho" in text_lower
        or "completad" in text_lower or "terminad" in text_lower
    )
    return mentions_task and mentions_done
```
Nota exacta de matching: `mentions_task` matchea por substring, así que "tarea" ⊂ "tareas" cuenta.
`mentions_done` exige el stem "completad"/"terminad" (participio: completad-o/a,
terminad-o/a) — verbos en otra conjugación como "termine" (yo termine) o "completé" NO satisfacen
`mentions_done` salvo que además caigan en uno de los 9 `_TASK_COMPLETE_TRIGGERS` literales.

`_try_task_tool()` (líneas 144-175) — **orden de evaluación es secuencial con `return` temprano
(equivalente a if/elif/elif), NUNCA se evalúan los tres bloques para el mismo texto**:
```python
def _try_task_tool(text, channel, user_id):
    text_lower = text.lower().strip()
    try:
        if any(t in text_lower for t in _TASK_CREATE_TRIGGERS):
            result = execute_tool("task_create", {"text": text, "user_id": user_id,
                                                    "channel": channel.value}, channel, user_id)
            return ResolutionResult(text=result, matched_by="task_tool", channel=channel)

        if any(t in text_lower for t in _TASK_LIST_TRIGGERS):
            result = execute_tool("task_list", {"user_id": user_id}, channel, user_id)
            return ResolutionResult(text=result, matched_by="task_tool", channel=channel)

        if _is_task_complete_phrase(text_lower):
            result = execute_tool("task_complete", {"text": text, "user_id": user_id},
                                   channel, user_id)
            return ResolutionResult(text=result, matched_by="task_tool", channel=channel)
    except ActionDenied as e:
        return ResolutionResult(text=_denied_message(e), matched_by="task_tool",
                                 channel=channel, denied=True)
    return None
```
Prioridad real hoy: **create > list > complete**. Si `create` no matchea, se prueba `list`; solo si
`list` tampoco matchea se evalúa `_is_task_complete_phrase()`. Si ninguno matchea, `_try_task_tool`
devuelve `None` y `resolve()` sigue con el siguiente resolver (`capability` → `intent` → `claude`).

**Hallazgo verificado con ejecución real (no asumido) — corrige/matiza la tabla "Comportamiento
actual vs deseado" de SPEC-017.md:** se ejecutaron las 3 funciones de trigger contra los ejemplos
literales de la SPEC y de los criterios de aceptación:

| Texto | create | list | complete_phrase | Resultado real hoy |
|---|---|---|---|---|
| "completa todas las tareas pendientes" | False | **True** (matchea "tareas pendientes") | — (no se evalúa) | `task_list` |
| "ya completé todas las tareas pendientes" | False | **True** (matchea "tareas pendientes") | — (no se evalúa) | `task_list` |
| "termina todas mis tareas" | False | **True** (matchea "mis tareas") | — (no se evalúa) | `task_list` |
| "completa mis tareas" | False | **True** (matchea "mis tareas") | — (no se evalúa) | `task_list` |
| "ya completé todas las pendientes" | False | False | False | Ninguno — `_try_task_tool` devuelve `None`, sigue a `capability`/`intent`/`claude` |
| "marca todas como completadas" | False | False | False (sin la palabra "tarea") | Ninguno — igual que arriba |
| "tarea completada" (sin "todas") | False | False | True | `task_complete` (single-id o aclaración) |
| "ya complete la tarea" (trigger literal) | False | False | True | `task_complete` |

**Esto es distinto de lo que documenta la tabla de SPEC-017.md** para la fila "ya completé todas
las tareas pendientes" (la SPEC dice que esa frase "Matchea `_is_task_complete_phrase()`, cae en
`_task_complete_invoke()`" — verificado que en realidad **nunca llega ahí**: matchea
`_TASK_LIST_TRIGGERS` por el substring "tareas pendientes" y retorna el listado antes de evaluar
`_is_task_complete_phrase()`). El caso borde que SPEC-017.md señala explícitamente solo para
"completa todas las tareas pendientes" (colisión con `_TASK_LIST_TRIGGERS`) en realidad es **el
comportamiento dominante**: casi cualquier frase natural de "completar todas" que además mencione
"tareas"/"mis tareas"/"tareas pendientes" cae en la rama `list`, no en la rama `complete`, con el
código actual — no es un caso aislado. Además, textos como "ya completé todas las pendientes" (sin
la palabra "tarea" o "tareas" exacta) o "marca todas como completadas" (sin "tarea" en absoluto) no
matchean ningún trigger hoy y caen fuera de `_try_task_tool` por completo (siguen a `capability` →
`intent` → `claude`, no a la aclaración de `_task_complete_invoke`). Esto no invalida el objetivo de
la SPEC ni sus criterios de aceptación (que están redactados en términos de comportamiento
*deseado*, no del mecanismo interno), pero es información que `orion-architect` necesita para
diseñar el criterio de desambiguación: el punto de intercepción de "todas" debe ubicarse **antes**
del chequeo de `_TASK_LIST_TRIGGERS`, no solo antes de `_is_task_complete_phrase()`, y debe cubrir
frases que hoy no matchean ningún trigger en absoluto (no solo resolver una colisión puntual).

Además, el ejemplo de la fila "0 pendientes" de la misma tabla ("completa mis tareas" → dice que el
resultado actual es "No tiene ninguna tarea pendiente en este momento, Señor.") tampoco es preciso
para ese texto exacto: "completa mis tareas" matchea `_TASK_LIST_TRIGGERS` ("mis tareas") y por lo
tanto resuelve vía `task_list` → `task_manager.get_task_summary()`, cuyo mensaje para 0 tareas
totales es **"No tiene ninguna tarea registrada, Señor. Todo está en orden."** (`tasks/task_manager.py`
línea 498) — un texto distinto al que cita la SPEC, y que además lista tareas completadas si las
hay, no solo pendientes. El mensaje "No tiene ninguna tarea pendiente en este momento, Señor." SÍ es
real y se confirmó ejecutándolo — pero es el que devuelve `_task_complete_invoke()` (línea 133,
`agents/tool_registry.py`) cuando el texto llega a la rama `complete` con 0 pendientes (ej. "tarea
completada" con 0 pendientes), no cuando llega vía `task_list`.

`RESOLVERS` (líneas 243-251) y `resolve()` (desde línea 254): sin relación directa con este REQ,
confirmado que el orden fijo (`routine → autopilot → learned → task_tool → capability → intent →
claude`) no se toca — coincide con lo que dice SPEC-017.md ("Módulos afectados", sin cambios en
`RESOLVERS`).

### `agents/tool_registry.py` — comportamiento EXACTO confirmado

`execute_tool()` (líneas 71-84) — único punto de gate real para tools: busca el `ToolSpec` en
`_REGISTRY`, levanta `ActionDenied` si no existe, llama
`security_manager.require_confirmation(spec.name, channel, details=..., user_id=user_id)` y solo
si no deniega invoca `spec.invoke(params)`. Confirmado que `task_complete`/`task_list`/`task_create`
están registrados con `RiskLevel.GREEN` (líneas 168, 180, 192) — `require_confirmation()` para
GREEN nunca pide confirmación (comportamiento heredado de REQ-006/REQ-005, no se re-verificó su
implementación interna porque `core/security_manager.py` está fuera del alcance de este REQ según
la SPEC).

`_task_complete_invoke()` (líneas 109-149) — lógica exacta:
```python
def _task_complete_invoke(params: dict) -> str:
    text = params.get("text", "")
    user_id = params["user_id"]
    text_lower = text.lower()

    match = re.search(r"(?:tarea|numero|número|id)\s*#?(\d+)", text_lower)
    task_id = int(match.group(1)) if match else None

    if task_id is not None:
        success = task_manager.complete_task(task_id, user_id)
        if success:
            return f"☑️ *Excelente, Señor.* He marcado la tarea #{task_id} como completada."
        return f"No encontré ninguna tarea pendiente con el ID #{task_id}, Señor."

    pending_tasks = task_manager.list_tasks(user_id, status="pending")   # limit=20 por defecto

    if not pending_tasks:
        return "No tiene ninguna tarea pendiente en este momento, Señor."

    if len(pending_tasks) == 1:
        task = pending_tasks[0]
        task_manager.complete_task(task["id"], user_id)
        return (f"☑️ *¡Trabajo terminado!* He deducido que se refería a la tarea "
                f"*'{task['title']}'* y la he marcado como completada.")

    resp = ("He notado que tiene varias tareas pendientes, Señor. ¿Podría indicarme el "
            "número de la tarea que completó? (Ej: 'listo tarea 2')\n\nSus tareas pendientes:\n")
    for t in pending_tasks:
        resp += f"• #{t['id']} - {t['title']}\n"
    return resp
```
El regex `r"(?:tarea|numero|número|id)\s*#?(\d+)"` extrae **como máximo un ID numérico** — si el
texto tiene un ID explícito, ese ID gana siempre, sin importar si el texto también contiene "todas"
(confirma el criterio de aceptación de "ID explícito gana"). Sin ID: si hay 0 pendientes, mensaje
fijo; si hay exactamente 1, autocompleta; si hay ≥2, arma el texto de aclaración enumerando
`#id - título` de cada una — **este es el mensaje de aclaración real que originó el disparador de
Johan** (confirma el hallazgo de `orion-spec`). No hay ninguna rama hoy que complete más de una
tarea en la misma invocación.

`ToolSpec` de `task_complete` (líneas 184-194): `parameters_schema` solo declara `{text, user_id}`,
sin ningún campo de "lote"/"todas" ni de lista de IDs — confirma el gap de esquema que ya señaló
`orion-spec` en el contexto.

### `tasks/task_manager.py` — firmas exactas confirmadas, sin cambios esperados

- `list_tasks(self, user_id: str, status: str = "pending", limit: int = 20) -> list[dict]`
  (línea 354-370). El default de `status` YA es `"pending"` — `_task_complete_invoke` lo llama
  explícito (`status="pending"`) mismo valor que el default, sin filtro adicional por canal (solo
  por `user_id`, coincide con la partición por canal que documentó `orion-spec`). `limit=20` por
  defecto — coincide con el límite que SPEC-017.md sugiere reusar para el tope de lote.
- `complete_task(self, task_id: int, user_id: str) -> bool` (línea 403-414). `UPDATE ... WHERE
  id=? AND user_id=?`, retorna `bool` según `cursor.rowcount > 0` — atómico por llamada, sin
  soporte nativo de batch (habría que iterar en el caller para completar varias).
- Ninguna de las dos firmas necesita cambiar para cumplir SPEC-017.md — confirmado, coincide con lo
  que dice la sección "Módulos afectados" de la SPEC ("sin cambios de firma esperados").

### Compilación y tests de las áreas afectadas — confirmado

`python -m py_compile` sobre `core/resolution.py`, `agents/tool_registry.py`,
`tasks/task_manager.py`, y (por estar mencionados como "sin cambios esperados" en la SPEC, para
tener una referencia de que compilan hoy) `core/reasoning_loop.py`, `core/security_manager.py`,
`intent/intentions.py`, `channels/gateway.py`, `channels/telegram_bot.py`,
`channels/discord_bot.py`, `ui/webview/bridge.py` — **sin errores, todos compilan limpio**.

`python -m pytest tests/test_resolution.py tests/test_tool_registry.py tests/test_reasoning_loop.py
--tb=short -q` → **27 passed**, sin fallos. `tests/test_resolution.py` no tiene ningún test que
ejercite el contenido de `_try_task_tool` más allá de confirmar que los métodos legacy de
`channels/gateway.py` fueron removidos (líneas 27-48) — no hay test hoy de la lógica de prioridad
create/list/complete ni de la rama de aclaración con ≥2 pendientes. `tests/test_tool_registry.py`
tiene un solo test de `task_list` (línea 107) — ninguno de `task_complete`/`_task_complete_invoke`.
No existe `tests/test_task_manager.py` (confirmado por `Glob`, sin resultados). Esto no es un fallo
pre-existente, es simplemente ausencia de cobertura — relevante para que `orion-tester` sepa que
casi toda la cobertura de los 11 CA de SPEC-017.md será test nuevo, no modificación de test
existente.

## Archivos que serán modificados (previsión)

Según "Módulos afectados" de SPEC-017.md, verificado contra el código real arriba:

- `core/resolution.py` — `_try_task_tool()` (líneas 144-175) y sus triggers
  (`_TASK_COMPLETE_TRIGGERS` líneas 126-130, `_is_task_complete_phrase()` líneas 133-141): debe
  reconocer la señal de "todas/todo" y evaluarla **antes** del chequeo de `_TASK_LIST_TRIGGERS`
  (no solo antes de `_is_task_complete_phrase()` — ver hallazgo arriba sobre por qué el punto de
  intercepción debe moverse más arriba en la cadena, no solo reordenar los dos últimos bloques).
- `agents/tool_registry.py` — `_task_complete_invoke()` (líneas 109-149) y/o un `ToolSpec` nuevo
  (ej. `task_complete_all`, decisión de `orion-architect`): debe ganar la rama de "completar todas
  las pendientes" vía `task_manager.list_tasks()` + `task_manager.complete_task()` en bucle, sin
  romper la rama de ID explícito (líneas 121-128) ni la de auto-completar única pendiente (líneas
  135-141).
- `tasks/task_manager.py` — **sin cambios de firma esperados** (confirmado arriba); se reutilizan
  `list_tasks()` (línea 354) y `complete_task()` (línea 403) tal como existen hoy.

**Sin cambios esperados** (confirmado que compilan y pasan sus tests hoy, documentado para que
`orion-tester`/`orion-qa` no asuman regresión si los ven sin tocar): `core/reasoning_loop.py`,
`agents/skill_tools.py`, `channels/gateway.py`, `channels/telegram_bot.py`,
`channels/discord_bot.py`, `core/security_manager.py`, `intent/intentions.py`.

Tests nuevos previstos (no existe ninguno hoy que cubra esta lógica, ver arriba): al menos un test
por canal (Desktop/Telegram/Discord) que ejercite `resolve()` end-to-end con el `user_id`/`channel`
real de cada uno (CA explícito de la SPEC), tests de `_try_task_tool`/`_task_complete_invoke` para
0/1/2+/N pendientes, ID explícito con y sin "todas" en el mismo texto, y un test de regresión que
confirme que `delete_task` (🟡) sigue bloqueado sin confirmación aunque se intente "en lote".

## Fallos pre-existentes (no atribuibles a este REQ)

`python -m pytest tests/ --tb=short -q` sobre el working tree tal cual está hoy (mismo diff de
REQ-015 sin commitear encima, ver nota de working tree arriba):

```
2 failed, 420 passed, 11 warnings in 42.57s
```

- `tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` — FAIL,
  `ModuleNotFoundError: No module named 'anthropic'`.
- `tests/test_llm_provider.py::test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto` — FAIL,
  mismo `ModuleNotFoundError: No module named 'anthropic'`.
- Causa: dependencia del SDK `anthropic` no instalada en el entorno actual — mismos 2 fallos ya
  documentados en `baseline-016.md` (2 failed, 365 passed allá vs 420 passed acá — la diferencia de
  passed es por los tests nuevos de REQ-015/016 que se sumaron entre sesiones, no por este REQ). No
  relacionado con `core/resolution.py`, `agents/tool_registry.py` ni `tasks/task_manager.py`.
- Ambos fallos son pre-existentes al REQ-017 y no deben atribuirse al trabajo de este flujo.

`tests/conftest.py` línea 38: `os.environ.setdefault("PYTEST_QT_API", "pyqt6")` sigue aplicado
incondicionalmente al importar el módulo (no depende de qué área se esté testeando) — confirmado
que no hace falta ninguna acción extra para este REQ aunque no toque Qt/webview, porque el `setdefault`
ya corre siempre que se importa `conftest.py`, sin gate por marcador ni por archivo bajo test.

## Riesgos activos identificados en esta sesión

- El punto de intercepción de "todas/todo" debe ubicarse antes del chequeo de
  `_TASK_LIST_TRIGGERS`, no solo antes de `_is_task_complete_phrase()` — si `orion-architect` solo
  reordena los dos últimos bloques (list vs complete) sin mover el chequeo de "todas" más arriba en
  la cadena, seguirá sin resolver la mayoría de las frases reales de "completar todas" (ver tabla de
  verificación arriba: 4 de 4 variantes de "todas" probadas con la palabra "tareas"/"mis tareas"
  caen hoy en `task_list`, no en `task_complete`).
- Frases de "completar todas" que no contienen la palabra "tarea"/"tareas" en absoluto (ej. "ya
  completé todas las pendientes", "marca todas como completadas") no matchean ningún trigger hoy —
  `_try_task_tool` devuelve `None` y el texto sigue a `capability`/`intent`/`claude`, sin llegar
  siquiera a la aclaración. Si `orion-architect` diseña el criterio de "todas" apoyado únicamente en
  extender `_is_task_complete_phrase()`, estas frases seguirían sin cubrirse — depende de qué tan
  amplio defina el criterio de detección de "todas" (fuera del alcance de `orion-baseline` decidirlo,
  se documenta como riesgo para que no se pierda).
- Los 2 fallos pre-existentes de `test_llm_provider.py` (`ModuleNotFoundError: anthropic`) seguirán
  apareciendo en la corrida de `orion-tester` — deben documentarse como ya presentes, no como
  regresión introducida por REQ-017.
- Working tree compartido con el diff de REQ-015/016 sin commitear (mismo riesgo ya registrado en
  el contexto de ambos REQs) — cualquier `git diff`/`git status` durante REQ-017 va a mezclar los
  tres REQs hasta que Johan decida el orden de commits.
