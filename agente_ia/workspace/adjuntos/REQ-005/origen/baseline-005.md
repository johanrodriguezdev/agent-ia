# Baseline REQ-005 — Deny-list central de acciones Rojo aplicada en código

## Estado actual del sistema

### `core/security_manager.py` (punto de clasificación existente hoy)
- Singleton `SecurityManager` (`security_manager = SecurityManager()`, instanciado al importar el
  módulo). `__new__` implementa el patrón singleton clásico (no hay lock; en un solo proceso/hilo
  principal no es problema práctico hoy).
- `RiskLevel(Enum)`: GREEN / YELLOW / RED. `ChannelType(Enum)`: DESKTOP / TELEGRAM / DISCORD / VOICE.
- `CHANNEL_ALLOWED_LEVELS`: DESKTOP permite GREEN+YELLOW; TELEGRAM/DISCORD/VOICE solo GREEN. RED no
  aparece en ningún canal de esta tabla — el único camino de excepción para RED es el bloque especial
  dentro de `require_confirmation()` (PIN maestro, solo si `channel == DESKTOP`).
- `_actions: Dict[str, RiskLevel]` — diccionario en memoria del proceso, poblado por
  `_register_default_actions()` al importar el módulo (23 acciones registradas: 9 YELLOW, 10 GREEN,
  4 RED). Ver inventario completo abajo.
- `register_action(name, level)` — **público, sin ninguna protección**. Cualquier código que importe
  `security_manager` puede llamarlo para registrar o **reescribir** la clasificación de cualquier
  acción, incluidas las 4 RED ya registradas (`format_disk`, `delete_database`, `expose_secrets`,
  `modify_source_code`). No hay lista de "acciones protegidas" ni control de quién llama.
- `classify_action(name) -> Optional[RiskLevel]` — devuelve `None` si el nombre no está en `_actions`.
- `is_action_allowed(action_name, channel) -> bool` — si `classify_action` devuelve `None`, **retorna
  `True` (fail-open)**. Este es el comportamiento central que SPEC-005 exige invertir.
- `require_confirmation(action_name, channel, details, user_id) -> bool` — es el único punto que
  hoy implementa lógica de bloqueo real:
  - Si `level is None` **o** `level == GREEN` → permite y audita como "permitida" (una acción sin
    clasificar hoy se trata igual que GREEN).
  - Si el canal no admite ese nivel (`is_action_allowed` falso) → bloquea y audita
    "bloqueada_canal".
  - YELLOW → pide confirmación por `input()` en consola (bloqueante, solo tiene sentido en canal
    DESKTOP interactivo; en Telegram/Discord esto se traduciría en un `input()` colgado en el
    proceso del bot si alguna vez se invocara desde ahí — hoy no ocurre porque
    `CHANNEL_ALLOWED_LEVELS` ya bloquea YELLOW fuera de DESKTOP antes de llegar a este bloque).
  - RED → audita "intento_rojo"; si `channel == DESKTOP` y `has_pin()` es verdadero, pide PIN
    (`require_pin`, hasta 3 intentos, `getpass.getpass`); si se verifica, audita
    "autorizada_rojo" y permite. En cualquier otro caso imprime mensaje y **retorna `False`**
    (bloqueado). Caso borde de la SPEC ("canal sin PIN configurado → bloqueado sin excepción")
    **ya se cumple hoy** tal cual está el código: `has_pin() == False` hace que la rama del PIN no
    se evalúe y caiga al bloqueo final.
- **`require_confirmation()` es opt-in**: nada en `dispatch()`, `skill_manager.execute()`,
  `skill_manager.get_agent_tools()`, `executor/handlers.py` ni `executor/system_action_handlers.py`
  lo invoca automáticamente. Cada skill que hoy protege algo lo hace porque su propio `execute()`
  decidió llamarlo explícitamente (ver inventario).
- Auditoría: `audit.db` (SQLite, en la raíz del proyecto, tabla `audit_log`) ya existe y funciona
  para toda llamada a `require_confirmation()` — pero como esa llamada es opt-in, solo quedan
  auditadas las acciones cuyo código decidió pasar por ahí.
- `_init_audit()` / `_log_audit()` capturan excepciones y solo hacen `logger.warning`, nunca fallan
  el flujo — comportamiento correcto y ya alineado con `python-style.md`.

### Caminos de ejecución identificados (más de los 3 que cita la SPEC)
La SPEC-005 declara 3 caminos a cubrir. La exploración de `main.py` encontró que existen **más
caminos previos** que pueden ejecutar una acción antes de llegar siquiera a `dispatch()`,
`skill_manager.execute()` o `get_agent_tools()`. Se documentan aquí porque afectan directamente el
criterio de "ningún skill/handler/canal puede ejecutarlas" — si el punto central se ubica solo
dentro de `dispatch()`/`skill_manager`, estos caminos quedarían fuera:

1. **`router/dispatcher.py:dispatch()`** — enruta `Intent` → handler legacy (`executor/handlers.py`,
   `executor/system_action_handlers.py`) o skill modular. No pasa por `security_manager` en ningún
   punto propio; solo se protege indirectamente si el handler/skill al que delega lo hace por su
   cuenta.
2. **`router/dispatcher.py:dispatch_as_tool()`** — usado como `AgentTool("dispatcher", ...)` en
   `main.py` para el orquestador de agentes. Clasifica el texto con
   `intent.classifier.classify_command` y llama a `dispatch()`. Determina el canal así:
   `intent_params["channel"] = params.get("channel", "desktop")` — **default "desktop" si no
   viene explícito**.
3. **`skills/skill_manager.py:execute()`** — invocado desde `dispatch()` cuando
   `skill_manager.handles_intent(intent)`. Llama directo a `skill.execute(intent, params)`.
4. **`skills/skill_manager.py:get_agent_tools()`** — genera un `AgentTool` por cada intent de cada
   skill, registrado individualmente en `main.py` vía `orchestrator.register_tool(tool)`.
   `AgentTool.function` es `lambda params, s=skill, i=intent: s.execute(i, params)` — llama
   `skill.execute()` **directo**, sin pasar por `dispatch()` ni por `dispatch_as_tool()`.
5. **`core/orchestrator.py:AgentOrchestrator._try_quick_dispatch()`** — camino "rápido" que sí
   propaga el `channel` real recibido (`params["channel"] = channel`) al invocar el
   `_legacy_dispatcher` (que es `dispatch()`). Este camino es correcto en cuanto a canal.
6. **`core/orchestrator.py:AgentOrchestrator._execute_single_agent()` /
   `_execute_agent_chain()`** — camino "de agentes" (cuando `_try_quick_dispatch` no resuelve, o
   cuando hay descomposición de subtareas). Crea un `_DynamicAgentInstance` con **todas** las
   `AgentTool` registradas (incluida `dispatcher` y cada `skill_*` individual) y llama
   `agent.execute(task, context_data)` → `_DynamicAgentInstance.execute()` itera las tools y llama
   `tool.execute({"task": task, "context": context or {}})`.
   **Hallazgo crítico de channel-spoofing/pérdida de canal:** el diccionario que se pasa a
   `tool.execute()` es `{"task": task, "context": context or {}}` — **no incluye la clave
   `"channel"` en el nivel superior**, aunque `context_data` sí trae `"channel": channel` **dentro**
   de `context`. Como resultado:
   - Si la tool ejecutada es `dispatcher` (`dispatch_as_tool`), su código lee
     `params.get("channel", "desktop")` → **siempre cae al default `"desktop"`**, sin importar si
     la tarea vino de Telegram/Discord/Voice.
   - Si la tool ejecutada es un `skill_<intent>` individual de `get_agent_tools()`, `skill.execute()`
     recibe `params={"task":.., "context":..}` sin `"channel"`; cualquier skill que haga
     `params.get("channel")` obtiene `None`, y en `os_integration/system_ctrl.py:_resolve_channel(None)`
     eso se traduce en `ChannelType.DESKTOP` — **el canal más permisivo** (único que admite YELLOW y
     PIN maestro para RED).
   - Esto significa que **hoy, cualquier acción YELLOW invocada a través del camino "de agentes"
     del orquestador (no el "quick dispatch") se evalúa como si viniera de DESKTOP**, incluso si el
     usuario real está en Telegram. Es una instancia real y ya explotable del caso borde "Channel
     spoofing" que la SPEC-005 pide cubrir explícitamente — no es un riesgo hipotético, es el
     comportamiento actual verificado en código.
7. **`os_integration/capabilities_router.py:try_capability()`** — se ejecuta en `main.py` **antes**
   de `classify_command()`/`dispatch()` (prioridad 2, después de comandos aprendidos). Hace
   `importlib.import_module(modulo)` + `getattr(modulo, func_name)` + `func(**params)` según
   `os_integration/system_capabilities.json`. No pasa por `security_manager` en absoluto y no hay
   límite sobre qué módulo/función puede invocar más allá del contenido del JSON.
8. **`learning/command_learning.py:run_custom_command()`** — comandos "enseñados" por el usuario
   (`Intent.TEACH_COMMAND`), guardados en `learning/commands.json`. Se ejecutan en `main.py` **antes**
   de rutinas/capacidades/clasificador, invocando `execute_simulated_action()` → `classify_command()`
   + `dispatch()` por cada acción de la secuencia. Este camino sí termina en `dispatch()`, pero el
   registro de la secuencia (`save_custom_command`) no valida en absoluto qué acciones se encadenan.
9. **`learning/routines_engine.py:try_routine()`** — rutinas proactivas/manuales
   (`learning/routines.json`). Ejecuta cada paso resolviendo la función directo desde
   `agents.action_registry.ACTION_REGISTRY[action_name]["fn"]` y llamándola con `fn(**params)`.
   **No pasa por `security_manager` ni por `dispatch()` en ningún punto.**
10. **`agents/task_executor.py:TaskExecutor.execute()` / `execute_single()`** (camino "Autopilot",
    activado en `main.py` por palabras gatillo: "autopilot", "ejecuta tarea", "crea un", "redacta",
    "haz un") — resuelve cada paso del plan generado por `agents/task_planner.py` directo desde
    `agents.action_registry.ACTION_REGISTRY` y llama `fn(**params)`. **Tampoco pasa por
    `security_manager` ni por `dispatch()`.**

**Conclusión de este hallazgo:** `agents/action_registry.py` (24 funciones registradas: apps,
escritura de archivos, pyautogui, capturas, red) es invocado por **dos caminos adicionales**
(rutinas y Autopilot) que hoy ejecutan sin pasar jamás por `security_manager`, y ninguna de sus
funciones llama `require_confirmation()` por su cuenta. Ninguna de las 24 acciones de
`action_registry.py` es hoy "roja" según `security-levels.md` (son en su mayoría GREEN:
abrir apps, capturas, info de disco/ventana; `write_file_direct`/`save_file_desktop` podrían
considerarse YELLOW-adyacentes por escribir archivos, pero no están clasificadas). Se documenta
como hallazgo porque el `SPEC-005` lista solo 3 caminos como "Módulos afectados" y **no menciona
`agents/action_registry.py`, `learning/routines_engine.py`, `agents/task_executor.py` ni
`os_integration/capabilities_router.py`** — decisión de si estos caminos entran en el alcance de
REQ-005 o quedan documentados como riesgo activo corresponde a `orion-architect` y al humano, no a
este agente.

### `skills/base_skill.py`
- Contrato mínimo: `name`, `description`, `get_intents()`, `get_training_data()`,
  `extract_params()`, `execute()`. No tiene ningún hook de seguridad — cada skill decide
  individualmente si llama a `security_manager`.

### `skills/skill_manager.py`
- Descubre skills dinámicamente listando `.py` en `skills/` (excluye `__init__.py`, `base_skill.py`,
  `skill_manager.py`), las instancia por reflexión (`inspect.isclass` + `issubclass(BaseSkill)`) y
  las registra. `_discover_skills()` es el hook de hot-reload usado por `SkillCreatorSkill`.
- `execute(intent, params)` y `get_agent_tools()` son los dos caminos ya documentados arriba —
  confirmado en código que **no comparten ninguna validación común**, son implementaciones
  independientes que ambas terminan en `skill.execute()`.

## Archivos que serán modificados (previsión)

- `agente_ia/core/security_manager.py` — probable ubicación del punto central o de su extensión;
  fail-closed por defecto, registro de las 6 acciones RED nuevas, protección contra reclasificación
  de RED en `register_action()`.
- `agente_ia/router/dispatcher.py` — `dispatch()` y `dispatch_as_tool()` no tienen chequeo de
  seguridad hoy; `dispatch_as_tool()` además tiene el bug de channel default a "desktop" descrito
  arriba.
- `agente_ia/skills/skill_manager.py` — `execute()` y `get_agent_tools()`, los dos caminos que
  llegan a `skill.execute()` sin pasar por ningún chequeo común.
- `agente_ia/executor/handlers.py`, `agente_ia/executor/system_action_handlers.py` — handlers
  legacy sin ninguna llamada a `security_manager`; deben quedar clasificados explícitamente
  (inventario abajo) para no romperse con fail-closed.
- `agente_ia/main.py` — punto de registro de ambos caminos de `AgentTool` (`dispatcher` +
  individuales de `get_agent_tools()`).
- `agente_ia/core/orchestrator.py` — **no está en la lista de módulos afectados de la SPEC, pero
  es donde vive el bug de channel-spoofing verificado** (`_execute_single_agent`/
  `_execute_agent_chain` no propagan `channel` al nivel superior del dict que reciben las
  `AgentTool`). Se señala para que `orion-architect` decida si corresponde a REQ-005 o queda como
  riesgo activo documentado.
- `agente_ia/.claude/rules/security-levels.md` — nota de que RED ahora se aplica también en código.
- `agente_ia/tests/` — nuevos tests de seguridad; ver hallazgo crítico sobre el estado actual de la
  suite de tests más abajo (la mayoría de los archivos existentes no se ejecutan bajo pytest).

Módulos que la SPEC no menciona pero el código revela como caminos de ejecución alternativos
(decisión de alcance pendiente de `orion-architect`):
- `agente_ia/os_integration/capabilities_router.py`
- `agente_ia/agents/action_registry.py`
- `agente_ia/agents/task_executor.py` (y transitoriamente `agents/task_planner.py`)
- `agente_ia/learning/routines_engine.py`
- `agente_ia/learning/command_learning.py` (termina en `dispatch()`, pero sin validar qué se
  encadena al guardar la rutina)

## Inventario completo de acciones/intents actuales (criterio de "regresión cero")

### Ya registradas en `security_manager._register_default_actions()`

| Acción (`register_action`) | Nivel hoy | ¿Algo la invoca realmente con ese nombre? |
|---|---|---|
| `shutdown` | YELLOW | Sí — `os_integration/system_ctrl.py:shutdown_pc()`, llamado desde `handle_sys_power_off` (handler legacy) y `SystemControlSkill` (intent `SYS_POWER_OFF`). |
| `restart` | YELLOW | **No** — no existe ninguna función `restart_pc` ni intent `SYS_RESTART` en el código. Acción pre-registrada sin implementación real hoy. |
| `close_app` | YELLOW | Sí — `os_integration/system_ctrl.py:close_app()`, llamado desde `handle_close_app` (handler legacy). No hay skill modular para `CLOSE_APP` (sigue siendo handler legacy puro). |
| `delete_file` | YELLOW | **No** — no existe ninguna función que borre un archivo individual invocando este nombre de acción. `os_integration/file_system.py` solo tiene `create_file`, `list_files`, `open_folder`. Acción pre-registrada sin implementación real hoy. |
| `delete_folder` | YELLOW | **No** — igual que arriba, no hay implementación real. |
| `execute_code` | YELLOW | Sí — `skills/code_execution_skill.py:CodeExecutionSkill.execute()`, intent `EXECUTE_CODE`. |
| `create_skill` | YELLOW | Sí — `skills/skill_creator_skill.py:SkillCreatorSkill.execute()`, intent `CREATE_SKILL`. |
| `modify_skill` | YELLOW | Sí — mismo archivo, intent `MODIFY_SKILL`. |
| `delete_skill` | YELLOW | Sí — mismo archivo, intent `DELETE_SKILL` (borra el `.py` con `os.remove`). |
| `send_message` | YELLOW | **No encontrado** — no hay ningún intent `SEND_MESSAGE` ni llamada a `require_confirmation("send_message", ...)` en `skills/`, `executor/`, ni `channels/`. Acción pre-registrada sin implementación real localizada. |
| `system_info` | GREEN | Sí (indirecto) — intent `SYSTEM_INFO` existe (`InfoSkill` y `system_action_handlers.handle_system_info`), pero **ninguno de los dos llama a `security_manager`**; la clasificación GREEN nunca se consulta en la práctica hoy. |
| `search_files` | GREEN | Sí — intent `SEARCH_FILES` → `system_action_handlers.handle_search_files`; no llama a `security_manager` (no hace falta porque hoy nada lo exige). |
| `web_search` | GREEN | **No coincide el nombre** — el intent real es `SEARCH_WEB` (`handle_search_web`), no `web_search`. Nunca se consulta esta entrada. |
| `chat` | GREEN | Coincide con `Intent.CHAT` conceptualmente, pero `handle_chat()` no llama a `security_manager`. |
| `open_app` | GREEN | Coincide con `Intent.OPEN_APP` conceptualmente (`handle_open_app`), no se consulta hoy. |
| `play_media` | GREEN | **No coincide el nombre** — el intent real es `PLAY_MUSIC` (`MediaSkill`), no `play_media`. |
| `screenshot` | GREEN | **No coincide el nombre** — el intent real es `TAKE_SCREENSHOT`. |
| `weather` | GREEN | **No coincide el nombre** — el intent real es `GET_WEATHER` (`WeatherSkill`). |
| `list_files` | GREEN | Coincide con `Intent.LIST_FILES`, no se consulta hoy. |
| `format_disk` | RED | No implementado en código (correcto, es pre-registro preventivo). |
| `delete_database` | RED | No implementado en código (correcto, pre-registro preventivo). |
| `expose_secrets` | RED | No implementado en código (correcto, pre-registro preventivo). |
| `modify_source_code` | RED | No implementado en código (correcto, pre-registro preventivo). |

**Hallazgo importante:** de las 23 acciones pre-registradas, varias GREEN usan un nombre de acción
que **no coincide con ningún `Intent` real del sistema** (`web_search` vs `SEARCH_WEB`,
`play_media` vs `PLAY_MUSIC`, `screenshot` vs `TAKE_SCREENSHOT`, `weather` vs `GET_WEATHER`). Esto
no rompe nada hoy porque `classify_action()` para esos intents reales nunca se invoca (nadie llama
`require_confirmation()` con esos nombres), pero es relevante para `orion-architect`: si el diseño
fail-closed usa el nombre de `Intent` como clave de clasificación en el punto central, estas 4
entradas GREEN "pre-registradas" no protegerán nada — hay que registrar con el nombre de intent
real, no renombrar el intent.

### Intents/acciones completos del sistema — mapa de riesgo esperado según `security-levels.md`

Se listó cada intent en `intent/intentions.py` y cada intent devuelto por `get_intents()` de cada
skill en `skills/*.py`, cruzado con si hoy pasa por algún chequeo:

| Intent / acción | Manejador | ¿Pasa por `security_manager` hoy? | Nivel esperado (security-levels.md) |
|---|---|---|---|
| `OPEN_APP` | `handlers.handle_open_app` (legacy) | No | 🟢 GREEN — "Abrir aplicaciones conocidas" |
| `CLOSE_APP` | `handlers.handle_close_app` → `system_ctrl.close_app` | **Sí**, vía `close_app` | 🟡 YELLOW — "Cerrar aplicaciones (taskkill /F)" — ya correcto |
| `SEARCH_WEB` | `handlers.handle_search_web` | No | 🟢 GREEN — "Buscar en Wikipedia o web" |
| `OPEN_FOLDER` | `handlers.handle_open_folder` / `FileSystemSkill` | No | 🟢 GREEN — "Listar archivos y directorios" (abrir carpeta es equivalente de solo-lectura) |
| `LIST_FILES` | `handlers.handle_list_files` / `FileSystemSkill` | No | 🟢 GREEN |
| `CREATE_FILE` | `handlers.handle_create_file` / `FileSystemSkill` | No | No listada explícitamente en `security-levels.md`; crear un archivo nuevo no es "modificar archivos existentes" (eso es YELLOW) — más cercana a GREEN, pero es una decisión de clasificación que le corresponde a `orion-architect`/humano, no asumida aquí. |
| `GET_TIME` | `handlers.handle_get_time` / `SystemControlSkill` | No | 🟢 GREEN — "Decir la hora/fecha" |
| `SYS_VOL_UP` / `SYS_VOL_DOWN` / `SYS_MUTE` | `handlers.*` / `SystemControlSkill` | No | 🟡 YELLOW según regla ("Cambiar configuraciones del sistema (volumen...)")  — **hoy NO pide confirmación**, es una brecha ya existente entre la regla documental y el código, no introducida por REQ-005. |
| `TAKE_SCREENSHOT` | `handlers.handle_take_screenshot` / `SystemControlSkill` | No | 🟢 GREEN — "Tomar screenshots" |
| `SYS_POWER_OFF` | `handlers.handle_sys_power_off` → `system_ctrl.shutdown_pc` | **Sí**, vía `shutdown` | 🟡 YELLOW — ya correcto |
| `WIKIPEDIA_SUMMARY` | `handlers.handle_wikipedia_summary` | No | 🟢 GREEN |
| `RECALL_MEMORY` | `handlers.handle_recall_memory` | No | 🟢 GREEN — "Recordar y recuperar información de la memoria" |
| `TEACH_COMMAND` | manejado directo en `main.py` (no pasa por `dispatch`) | No | No clasificada; crea una rutina persistida en `commands.json`, no ejecuta nada peligroso por sí misma. |
| `PC_CLICK` / `PC_TYPE` / `PC_SCROLL` | `handlers.*` (control de mouse/teclado real vía `pc_controller`) | No | No está listada explícitamente en `security-levels.md`. Es control físico del PC (clicks/tecleo arbitrario) — con mayor potencial de daño que un GREEN típico; queda como duda para `orion-architect`/humano, no asumida aquí. |
| `AUTOPILOT` | disparado por palabras clave en `main.py`, no es un `Intent` despachado por `dispatch()` | No | Cadena de acciones de `action_registry` — ver caminos 9 y 10 arriba. |
| `CALCULATE` | `system_action_handlers.handle_calculate` | No | 🟢 GREEN (no listada explícita, operación pura sin efectos secundarios) |
| `SEARCH_FILES` | `system_action_handlers.handle_search_files` | No | 🟢 GREEN — "Buscar archivos (solo lectura)" |
| `FOLDER_SIZE` / `FIND_LARGEST` | `system_action_handlers.*` | No | 🟢 GREEN (solo lectura) |
| `SYSTEM_INFO` / `CPU_INFO` / `RAM_INFO` | `system_action_handlers.*` / `InfoSkill` | No | 🟢 GREEN — "Leer información del sistema (CPU, RAM...)" |
| `CHAT` / `UNKNOWN` | `handlers.handle_chat` / `handle_unknown` | No | 🟢 GREEN — "Responder preguntas conversacionales" |
| `EXECUTE_CODE` | `CodeExecutionSkill` | **Sí**, vía `execute_code` | 🟡 YELLOW — "Ejecutar código generado por IA" — ya correcto (pero el sandboxing del código en sí queda fuera de alcance de REQ-005, confirmado en la SPEC) |
| `FILE_ANALYSIS` | `FileAnalysisSkill` | No | 🟢 GREEN (solo lectura + resumen); si el LLM no está disponible, retorna mensaje sin bloquear. |
| `PLAY_MUSIC` | `MediaSkill` | No | 🟢 GREEN — "Reproducir música/video en el navegador" |
| `ANALYZE_SCREEN` | `ScreenAnalysisSkill` | No | 🟢 GREEN — "Tomar screenshots" + análisis (equivalente a screenshot + chat) |
| `CREATE_SKILL` / `MODIFY_SKILL` / `DELETE_SKILL` | `SkillCreatorSkill` | **Sí**, vía `create_skill`/`modify_skill`/`delete_skill` | 🟡 YELLOW — "Crear/modificar skills automáticamente" — ya correcto |
| `LIST_SKILLS` | `SkillCreatorSkill._list_skills()` | No — y además **`LIST_SKILLS` está en `get_intents()` de `SkillCreatorSkill` pero el `execute()` de la skill no tiene una rama `elif intent == "LIST_SKILLS"`** (solo maneja CREATE/MODIFY/DELETE; cae al `return "No entendí qué operación..."` final). Es un bug pre-existente ajeno a REQ-005, se documenta para no confundirlo con una regresión. | 🟢 GREEN (solo lectura) |
| `SYS_VOL_UP`/etc. ya cubiertos arriba | | | |
| `GET_WEATHER` | `WeatherSkill` | No | 🟢 GREEN — "Consultar clima" |
| `BROWSE_WEB` | `WebBrowsingSkill` | No | 🟢 GREEN — equivalente a búsqueda web |

**Acciones de `agents/action_registry.py`** (24 funciones, alcanzables solo vía Autopilot/rutinas,
no vía `dispatch()`): `open_chrome`, `open_notepad`, `open_explorer`, `open_calculator`,
`open_browser`, `close_window`, `write_file_direct`, `open_file_in_notepad`,
`get_active_window_info`, `write_text`, `press_key`, `hotkey_action`, `save_file_desktop`,
`take_screenshot`, `wait_seconds`, `generate_ai_summary`, `get_current_datetime`, `get_disk_info`,
`open_url`, `search_google`. Ninguna llama a `security_manager`. La mayoría son GREEN equivalentes
a sus contrapartes de `dispatch()` (abrir apps, captura, búsqueda). `write_file_direct` y
`save_file_desktop` escriben archivos sin restricción — no son técnicamente "modificar archivos
existentes" (crean/sobreescriben en el Escritorio con nombre generado o indicado), pero se
acercan más a YELLOW que a GREEN; queda como decisión de `orion-architect`/humano.

## Fallos pre-existentes (no atribuibles a este REQ)

### Compilación
`python -m py_compile` limpio (exit 0) en todos los módulos previstos como afectados (`core/`,
`router/`, `skills/`, `executor/`, `os_integration/`, `agents/`, `learning/`, `main.py`,
`core/orchestrator.py`, `core/base_agent.py`). No hay errores de sintaxis pre-existentes en el área
que toca REQ-005.

### Suite de tests — hallazgo crítico
`cd agente_ia && python -m pytest tests/ --tb=short -v` → **5 passed** (todos de
`tests/test_agents.py`). Resultado:
```
tests/test_agents.py::test_ca1_orchestrator PASSED
tests/test_agents.py::test_ca2_base_agent PASSED
tests/test_agents.py::test_ca3_comunicacion PASSED
tests/test_agents.py::test_ca4_proactividad PASSED
tests/test_agents.py::test_ca5_contexto PASSED
5 passed, 1 warning in 13.42s
```
Pero **`tests/test_classifier.py`, `tests/test_dispatcher.py`, `tests/test_autopilot.py` y
`tests/test_memory.py` no son recolectados por pytest en absoluto** (`--collect-only` sobre esos 4
archivos → "no tests collected"). Causa verificada leyendo el código: son scripts standalone
antiguos con una función `run_tests()` y bloque `if __name__ == "__main__":`, **sin ninguna función
con prefijo `test_`** ni `assert` — pytest los ignora silenciosamente porque no cumplen la
convención de descubrimiento (`python_files`/`python_functions` por defecto). Esto no es un fallo
que pytest reporte como FAIL; es ausencia total de cobertura real detrás de una apariencia de
archivos de test. **Pre-existente, no atribuible a REQ-005** — pero relevante porque los criterios
de aceptación de la SPEC (tests de fail-closed, reclasificación, prompt-injection, cobertura de las
10 categorías RED) deben escribirse como funciones `test_*` reales dentro de un archivo nuevo
(ej. `tests/test_security_manager.py`) para que efectivamente se ejecuten — replicar el patrón de
`tests/test_dispatcher.py` etc. dejaría los nuevos tests de seguridad sin ejecutarse nunca.

### Otros hallazgos de comportamiento pre-existente (no fallos de compilación/tests, pero relevantes)
- **Channel-spoofing real y verificado** (no solo hipotético) en el camino "de agentes" del
  orquestador (`core/orchestrator.py:_execute_single_agent`/`_execute_agent_chain` →
  `AgentTool.execute({"task":.., "context":..})` sin `"channel"` en el nivel superior) — ver detalle
  en la sección de caminos de ejecución arriba.
- `LIST_SKILLS` está declarado en `get_intents()` de `SkillCreatorSkill` pero no tiene rama en su
  `execute()` — cae al mensaje de error genérico. Bug funcional pre-existente, no relacionado con
  seguridad.
- 4 nombres de acción GREEN pre-registrados en `security_manager` no coinciden con ningún `Intent`
  real (`web_search`, `play_media`, `screenshot`, `weather` vs. `SEARCH_WEB`, `PLAY_MUSIC`,
  `TAKE_SCREENSHOT`, `GET_WEATHER`).
- `restart`, `delete_file`, `delete_folder`, `send_message` están pre-registrados como YELLOW pero
  no tienen ninguna implementación real en el código hoy (no son una regresión, son placeholders
  para funcionalidad que no existe).
- Brecha regla-vs-código: `SYS_VOL_UP`/`SYS_VOL_DOWN`/`SYS_MUTE` (cambiar volumen) y
  `PC_CLICK`/`PC_TYPE`/`PC_SCROLL` (control de mouse/teclado) no llaman a `security_manager` hoy,
  pese a que `security-levels.md` sugiere que cambiar configuraciones del sistema es 🟡 YELLOW.
  Ninguna está en el inventario de las 10 categorías RED de la SPEC, así que no bloquea el alcance
  de REQ-005, pero es relevante para el criterio de "regresión cero": si `orion-architect` decide
  clasificar estas acciones al construir el registro fail-closed, un cambio de "sin control hoy" a
  "YELLOW" sería un cambio de UX deliberado, no una regresión — debe ser una decisión explícita, no
  un efecto colateral del fail-closed.
