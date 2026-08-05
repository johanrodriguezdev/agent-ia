# Arquitectura REQ-005 — Deny-list central de acciones Rojo aplicada en código

## Decisión de fondo (responde a hallazgo 1 de orion-baseline)

**El "punto central" no es un único archivo interceptor — es una única función de decisión
(`SecurityManager.require_confirmation()`, extendida) dentro de `core/security_manager.py`,
invocada explícitamente desde el punto de entrada de cada uno de los 7 caminos de ejecución
verificados en código** (los 3 que cita la SPEC + los 4 que encontró orion-baseline).

Justificación de por qué no es posible un único interceptor estructural: `dispatch()`,
`skill.execute()` (llamado directo desde `get_agent_tools()`), y `fn(**params)` (llamado desde
`action_registry`/`capabilities_router`) son tres formas de invocación completamente distintas en
Python (paso por diccionario de rutas, método de instancia, y `getattr`/closure sobre función
suelta) que no comparten ningún framework de middleware ni un único frame de pila común. No existe
hoy ningún decorador, metaclase o registro de hooks que las una. Construir ese framework de
interceptación genérico sería un refactor estructural grande, fuera del alcance acotado que el
humano fijó para REQ-005 (riesgo de scope creep ya señalado en el contexto). En su lugar:

- La **lógica de decisión** (clasificar, aplicar fail-closed, pedir PIN, resolver canal real,
  auditar) vive en un solo lugar: `core/security_manager.py`. Nadie duplica esa lógica.
- Cada camino de ejecución llama a esa función **una sola vez, en su punto de entrada más externo
  que aún no dependa de que otro código intermedio ya haya gateado la misma acción** — evitando
  doble-gateo (ver mapa de puntos de inserción abajo, diseñado explícitamente para que ninguna
  acción pase por dos prompts o dos intentos de PIN).
- Dos de los 4 caminos adicionales (`learning/routines_engine.py`, `agents/task_executor.py`) no
  necesitan su propia llamada al gate: ambos ya delegan en `agents/action_registry.py` para
  ejecutar la función real, así que basta con centralizar el gate ahí (`execute_action()`, nueva
  función) y hacer que routines/Autopilot llamen a esa función en vez de acceder a
  `ACTION_REGISTRY[...]["fn"]` directamente. Un tercer camino (`learning/command_learning.py`) no
  ejecuta nada por sí mismo — reencola cada acción a través de `dispatch()` (vía
  `execute_simulated_action` en `main.py`), así que queda cubierto transitivamente sin tocarlo.

## Cobertura de criterios de la SPEC

| Criterio (SPEC-005) | Cómo lo satisface esta propuesta |
|---|---|
| Punto central único que cubre `dispatch()`, `skill_manager.execute()`, `get_agent_tools()` | Los 3 llaman a `security_manager.require_confirmation()` en su punto de entrada exacto (ver mapa abajo), sin duplicar lógica de decisión. |
| 10 categorías RED registradas, incluidas las 6 sin implementar | `_register_default_actions()` en `security_manager.py` agrega `send_email_as_user`, `post_social_media`, `elevated_system_command`, `install_uninstall_software`, `modify_system_env_vars`, `grant_third_party_access` como RED, junto a las 4 ya existentes. |
| Fail-closed: acción sin clasificar se bloquea | `require_confirmation()`: la rama `level is None` deja de tratarse como `GREEN` y pasa a bloquear + auditar `"bloqueada_no_clasificada"`. `is_action_allowed()` recibe el mismo cambio (`None → False`) para no dejar una vía de fail-open paralela (tenía 2 llamadores externos: `channels/telegram_bot.py`, `core/proactive_engine.py`). |
| Resistencia a bypass de skill/handler que no llama `require_confirmation()` por su cuenta | El gate se mueve **fuera** del cuerpo de cada skill/handler y se ejecuta antes de invocarlo, en `dispatch()`, `SkillManager.execute()`, el wrapper de `get_agent_tools()`, `execute_action()` y `execute_capability()`. Ninguna de estas 5 funciones de entrada puede saltarse el gate porque el gate se ejecuta antes de resolver o invocar la función objetivo, no dentro de ella. |
| Resistencia a prompt-injection (incluye pin/confirmación falsos en params) | El gate solo lee `action_name` y `channel` de la invocación. Nunca lee `params["pin"]`, `params["confirmed"]` ni nada del cuerpo de la skill/LLM — la única fuente de PIN es `getpass.getpass()` interactivo dentro de `require_pin()`, que no toca `params`. Esto ya es así hoy; se documenta como invariante de diseño que ningún cambio de REQ-005 debe romper. |
| Reclasificación de RED bloqueada | `register_action()` rechaza (retorna `False`, `logger.critical`, audita `"reclasificacion_bloqueada"`) cualquier intento de bajar el nivel de una acción cuyo nivel actual es `RED`. |
| Test por canal (Telegram/Discord/Desktop) | `resolve_channel()` centraliza la resolución; los 3 canales existentes más `API` y `UNKNOWN` (nuevos) están en `CHANNEL_ALLOWED_LEVELS`, todos GREEN-only salvo DESKTOP. |
| Única vía de excepción: PIN maestro, solo DESKTOP | Sin cambios en esa rama de `require_confirmation()` — ya está correctamente restringida a `channel == ChannelType.DESKTOP`. Se preserva intacta. |
| Auditoría en `audit.db` | Sin cambios de esquema; se agregan dos resultados nuevos de auditoría (`"bloqueada_no_clasificada"`, `"reclasificacion_bloqueada"`) al vocabulario ya usado por `_log_audit()`. |
| Regresión cero en GREEN | Inventario completo de orion-baseline usado para registrar **todos** los intents reales (no los 4 nombres que no correspondían a ningún intent) más las ~20 funciones de `action_registry.py`. Ver detalle de clasificación abajo. |
| YELLOW sin cambio de UX | Ninguna de las 6 acciones YELLOW ya protegidas (`shutdown`, `close_app`, `execute_code`, `create_skill`, `modify_skill`, `delete_skill`) cambia su llamada a `require_confirmation()` ni el mensaje de `input()`. |
| Tests unitarios por las 10 categorías RED + no-clasificada + reclasificación | Ver "Pruebas sugeridas". |
| Suite existente sin nuevos fallos | Los cambios no tocan la superficie pública que ejercita `tests/test_agents.py` (orchestrator/base_agent conservan sus firmas; solo se añade una clave `"channel"` a un diccionario interno). |

## Hallazgos propios adicionales (más allá del inventario de orion-baseline)

Durante el diseño encontré dos puntos que orion-baseline no cubrió y que el fail-closed rompería
si no se corrigen — los agrego al alcance porque son consecuencia directa de cerrar el fail-open:

1. **`core/proactive_engine.py:90`** llama
   `security_manager.is_action_allowed(f"proactive_{trigger.agent.name}", ChannelType.DESKTOP)`
   con un nombre de acción **dinámico** (`"proactive_ProactiveAssistant"` hoy) que nunca está
   pre-registrado. Con fail-open esto siempre pasaba silenciosamente; con fail-closed bloquearía
   **todos** los rituales proactivos (briefing, saludo diario, chequeo horario) desde el primer
   disparo. Fix: cambiar la clave a un nombre estable `"proactive_trigger"` (no depender del
   nombre del agente) y registrarlo GREEN.
2. **`main.py`** nunca inyecta `"channel"` en `params` antes de llamar `dispatch()` directamente
   (línea `result = dispatch(intent, params)` del loop principal, y dentro de
   `execute_simulated_action` para comandos aprendidos). Hoy es inofensivo porque `require_confirmation`
   no se invocaba desde ahí. Con el gate puesto en `dispatch()`, cualquier acción YELLOW disparada
   desde el loop interactivo de escritorio (que es 100% desktop: opciones de texto/voz/wake-word)
   se evaluaría como canal `UNKNOWN` (solo GREEN) y quedaría bloqueada — una regresión real para
   `shutdown`, `close_app`, etc. usadas a diario desde la consola. Fix: `main.py` debe fijar
   `params["channel"] = "desktop"` antes de esas llamadas, igual que ya se hace para
   `orchestrator.process_task(..., channel="desktop")` en el resto del archivo.

## Módulos a modificar

- `core/security_manager.py` — núcleo de la decisión (ver "Nuevas clases/funciones").
- `router/dispatcher.py` — gate en `dispatch()`; quitar default duro `"desktop"` en `dispatch_as_tool()`.
- `skills/skill_manager.py` — gate en `execute()`; wrapper gateado en `get_agent_tools()`.
- `core/base_agent.py` — propagar `channel` real al nivel superior del dict en `_DynamicAgentInstance.execute()`.
- `core/orchestrator.py` — sin cambio de lógica (ya construye `context_data["channel"]` correctamente); se deja documentado que el fix real vive en `base_agent.py`, que es donde se pierde el dato.
- `os_integration/system_ctrl.py` — eliminar `_resolve_channel()` local, usar `security_manager.resolve_channel()`.
- `skills/code_execution_skill.py`, `skills/skill_creator_skill.py` — quitar default `ChannelType.DESKTOP` al leer `params.get("channel")`.
- `agents/action_registry.py` — nueva función `execute_action()` como único punto de ejecución gateado del registro.
- `agents/task_executor.py` — usar `execute_action()` en vez de invocar `fn` directo; aceptar `channel`.
- `learning/routines_engine.py` — usar `agents.action_registry.execute_action()`; aceptar `channel`.
- `os_integration/capabilities_router.py` — gate en `execute_capability()`; aceptar `channel`.
- `core/proactive_engine.py` — nombre de acción estable `"proactive_trigger"` (hallazgo propio #1).
- `main.py` — inyectar `channel="desktop"` en los 3 puntos que llaman `dispatch()`/`try_routine()`/`executor.execute()`/`try_capability()` sin canal (hallazgo propio #2).
- `.claude/rules/security-levels.md` — nota de que RED ahora se aplica también en código (cambio documental, lo hace orion-dev).
- `tests/test_security_manager.py` — nuevo, único archivo con funciones `test_*` reales para que la suite de seguridad se ejecute.

## Nuevas clases/funciones

### `core/security_manager.py`
- `ChannelType.API = "api"` y `ChannelType.UNKNOWN = "unknown"` — nuevos miembros del enum.
  `CHANNEL_ALLOWED_LEVELS[ChannelType.API]` y `[ChannelType.UNKNOWN]` → `[RiskLevel.GREEN]`.
  `UNKNOWN` es el valor de resolución cuando el canal real no puede determinarse — reemplaza al
  default implícito `DESKTOP` que causaba el channel-spoofing (hallazgo 2 de baseline).
- `SecurityManager.resolve_channel(self, channel: "ChannelType | str | None") -> ChannelType` —
  **nueva**, única función de resolución de canal del sistema. Reemplaza la lógica hoy duplicada en
  `os_integration/system_ctrl.py:_resolve_channel()`. Diferencia clave respecto a la versión
  actual: si `channel` es `None` o no coincide con ningún valor conocido, retorna
  `ChannelType.UNKNOWN` (GREEN-only) en vez de `ChannelType.DESKTOP` (el más permisivo). Esto cierra
  el bug de channel-spoofing en su origen: cualquier caller que "pierda" el canal real deja de
  heredar por defecto el nivel de confianza más alto del sistema.
- `SecurityManager.register_action(self, name: str, level: RiskLevel) -> bool` — **modificada**.
  Si `name` ya está clasificado `RED` y `level != RED`, rechaza el cambio (`logger.critical`,
  audita `"reclasificacion_bloqueada"`, retorna `False`) sin alterar `self._actions[name]`. En
  cualquier otro caso, aplica el cambio y retorna `True`. No se protege degradar YELLOW→GREEN
  (fuera del alcance literal de la SPEC — solo pide proteger RED); se documenta como riesgo
  residual aceptado.
- `SecurityManager.require_confirmation(self, action_name: str, channel: "ChannelType | str | None", details: str = "", user_id: str = "default") -> bool` —
  **modificada**. Primera línea: `channel = self.resolve_channel(channel)` (antes exigía un
  `ChannelType` ya resuelto; ahora acepta lo que cada caller tenga a mano — string, `None`, o
  `ChannelType`). La rama `if level is None or level == RiskLevel.GREEN` se divide:
  - `level is None` → bloquea, audita `"bloqueada_no_clasificada"`, retorna `False` (era el
    fail-open que exige cerrar la SPEC).
  - `level == RiskLevel.GREEN` → sin cambios (permite, audita `"permitida"`).
  Las ramas YELLOW y RED (incluida la del PIN maestro) **no se tocan** — preserva la UX YELLOW y
  la única vía de excepción RED tal cual están hoy.
- `SecurityManager.is_action_allowed(self, action_name: str, channel: ChannelType) -> bool` —
  **modificada**: `if level is None: return False` (antes `True`). Cierra la segunda vía de
  fail-open que existía en paralelo a `require_confirmation()` (usada por
  `channels/telegram_bot.py` y `core/proactive_engine.py`).
- `SecurityManager.check_coverage(self, action_names: List[str]) -> List[str]` — **nueva**,
  utilidad de diagnóstico (no bloquea nada). Retorna la sublista de `action_names` que no tiene
  clasificación registrada. Pensada para que `main.py` la llame una vez al arrancar con la lista de
  todos los `Intent` reales + intents de skills, y haga `logger.warning` de cualquier hueco — red de
  seguridad para detectar en logs, antes de que un usuario lo sufra, un intent nuevo que se agregó
  sin clasificar.
- `_register_default_actions()` — **modificada**: se quitan las 4 entradas GREEN con nombre que no
  corresponde a ningún intent real (`web_search`, `play_media`, `screenshot`, `weather` — sus
  equivalentes correctos se registran en `_register_intent_actions()`, ver abajo). Se agregan las 6
  categorías RED nuevas. `restart`, `delete_file`, `delete_folder`, `send_message` (YELLOW, sin
  implementación real) **se dejan tal cual** — pre-registro preventivo, mismo criterio que ya usa la
  SPEC para las 6 categorías RED sin implementar; no es limpieza silenciosa, queda documentado aquí
  como deuda conocida y aceptada.
- `_register_intent_actions()` — **nueva**, se llama junto a `_register_default_actions()` al
  importar el módulo. Registra, usando `Intent.value` como clave (no el nombre de intent
  renombrado — decisión explícita para no tocar `intent/intentions.py`), la clasificación de cada
  intent real del sistema según el inventario de `baseline-005.md`:
  - GREEN: `OPEN_APP`, `SEARCH_WEB`, `OPEN_FOLDER`, `LIST_FILES`, `CREATE_FILE`, `GET_TIME`,
    `TAKE_SCREENSHOT`, `WIKIPEDIA_SUMMARY`, `RECALL_MEMORY`, `TEACH_COMMAND`, `PC_CLICK`,
    `PC_TYPE`, `PC_SCROLL`, `SYS_VOL_UP`, `SYS_VOL_DOWN`, `SYS_MUTE`, `AUTOPILOT`, `CALCULATE`,
    `SEARCH_FILES`, `FOLDER_SIZE`, `FIND_LARGEST`, `SYSTEM_INFO`, `CPU_INFO`, `RAM_INFO`, `CHAT`,
    `UNKNOWN`, `FILE_ANALYSIS`, `PLAY_MUSIC`, `ANALYZE_SCREEN`, `LIST_SKILLS`, `GET_WEATHER`,
    `BROWSE_WEB`.
  - YELLOW: `CLOSE_APP`, `SYS_POWER_OFF`, `EXECUTE_CODE`, `CREATE_SKILL`, `MODIFY_SKILL`,
    `DELETE_SKILL`.
  - **Decisión explícita a confirmar por el humano**: `SYS_VOL_UP`/`SYS_VOL_DOWN`/`SYS_MUTE` y
    `PC_CLICK`/`PC_TYPE`/`PC_SCROLL` quedan **GREEN** (sin confirmación), pese a que
    `security-levels.md` sugiere YELLOW para "cambiar configuraciones del sistema" y control de
    mouse/teclado. Se elige preservar el comportamiento actual (cero fricción) porque la SPEC
    excluye explícitamente cambios de UX en YELLOW y el alcance ya fue acotado por el humano contra
    scope creep. Se documenta como brecha regla-vs-código heredada, no introducida ni cerrada por
    REQ-005 — candidata a un REQ futuro específico de "clasificación de acciones físicas del PC".
  - `CREATE_FILE` se clasifica GREEN (crear un archivo nuevo no es "modificar archivos existentes").
- `_register_action_registry_actions()` — **nueva**, se llama junto a las anteriores. Registra,
  usando la clave literal de `ACTION_REGISTRY` (`agents/action_registry.py`) como nombre de acción,
  GREEN para todas las funciones actuales excepto:
  - **Decisión explícita a confirmar por el humano**: `write_file_direct` y `save_file_desktop` se
    clasifican **YELLOW** (escriben/sobrescriben archivos en el Escritorio con contenido
    parcialmente influenciable por el planificador de Autopilot/LLM). Esto introduce un `input()`
    de confirmación donde hoy no existe ninguno, dentro de una secuencia de Autopilot que hoy corre
    sin pausas — es un cambio de comportamiento real, no solo de clasificación, y se señala aparte
    en el resumen de aprobación para que el humano lo apruebe o pida cambiarlo a GREEN.
  - El resto (`open_chrome`, `open_notepad`, `open_explorer`, `open_calculator`, `open_browser`,
    `close_window`, `open_file_in_notepad`, `get_active_window_info`, `write_text`, `press_key`,
    `hotkey_action`, `take_screenshot`, `wait_seconds`, `generate_ai_summary`,
    `get_current_datetime`, `get_disk_info`, `open_url`, `search_google`) → GREEN, equivalentes a
    sus contrapartes ya GREEN accesibles vía `dispatch()`.
  - `write_text`/`press_key`/`hotkey_action` (pyautogui genérico) quedan GREEN por continuidad de
    comportamiento actual, pero se documentan como riesgo residual: son primitivas de automatización
    de entrada arbitraria, con potencial de daño equivalente al de `CodeExecutionSkill` sin
    sandbox — mismo tipo de limitación que el REQ ya excluye explícitamente (detección por
    comportamiento, no por nombre). Queda para la iniciativa REQ-006 si se decide acotar más.
- `_register_default_actions()`, `_register_intent_actions()`, `_register_action_registry_actions()`
  se ejecutan las 3 al final del módulo, igual que hoy se ejecuta `_register_default_actions()`.

### `router/dispatcher.py`
- `dispatch(intent: Intent, params: dict) -> str` — se agrega, **antes** de la rama que delega a
  `skill_manager.execute()`, nada (esa rama gatea internamente, ver abajo, para no gatear dos
  veces). Se agrega el gate únicamente **antes** de `handler(params)` en la rama de handlers
  legacy (`executor/handlers.py`, `executor/system_action_handlers.py`), que hoy no tiene ninguna
  protección propia:
  ```python
  action_name = intent.value if hasattr(intent, "value") else str(intent)
  if not security_manager.require_confirmation(action_name, params.get("channel"), details=f"dispatch:{action_name}"):
      return "⛔ Acción no autorizada."
  ```
- `dispatch_as_tool(params: dict) -> str` — se quita el default duro:
  `intent_params["channel"] = params.get("channel")` (antes `params.get("channel", "desktop")`).
  La resolución segura ahora ocurre dentro de `require_confirmation()` vía `resolve_channel()`.

### `skills/skill_manager.py`
- `SkillManager.execute(self, intent: str, params: dict) -> str` — gate agregado antes de
  `skill.execute(intent, params)`:
  ```python
  if not security_manager.require_confirmation(intent, params.get("channel"), details=f"skill:{skill.name}:{intent}"):
      return "⛔ Acción no autorizada."
  ```
  Con esto, `dispatch()` **no** necesita gatear antes de delegar a `skill_manager.execute()` (ya
  gatea internamente) — evita doble prompt para acciones YELLOW que pasan por skill modular. Y
  `SkillManager.execute()` queda protegido también si alguna vez se llama directo, sin pasar por
  `dispatch()` (hoy no ocurre, pero es exactamente el caso que la SPEC pide cubrir como camino
  independiente).
- `SkillManager.get_agent_tools(self) -> List[AgentTool]` — se reemplaza la lambda inline por una
  función nombrada gateada (más legible y testeable que un lambda anónimo):
  ```python
  def _make_gated_tool_fn(skill: BaseSkill, intent: str) -> Callable[[dict], str]:
      def _run(params: dict) -> str:
          channel = params.get("channel") or (params.get("context") or {}).get("channel")
          if not security_manager.require_confirmation(intent, channel, details=f"agent_tool:{skill.name}:{intent}"):
              return "⛔ Acción no autorizada."
          return skill.execute(intent, params)
      return _run
  ```
  y en el loop de `get_agent_tools()`: `function=_make_gated_tool_fn(skill, intent)`. Esta es la
  única de las tres rutas oficiales de la SPEC que no delega en `skill_manager.execute()` — llama
  `skill.execute()` directo — por eso necesita su propio gate explícito.

### `core/base_agent.py`
- `_DynamicAgentInstance.execute(self, task: str, context: dict = None) -> str` — única línea
  modificada:
  ```python
  result = tool.execute({"task": task, "context": context or {}, "channel": (context or {}).get("channel")})
  ```
  Corrige el hallazgo 2 de orion-baseline en su origen: `context_data` ya trae `"channel"` correcto
  desde `AgentOrchestrator._execute_single_agent()`/`_execute_agent_chain()` — el bug era que se
  perdía al construir el dict que efectivamente recibe `AgentTool.execute()`. No hace falta tocar
  `core/orchestrator.py`.

### `os_integration/system_ctrl.py`
- Se elimina `_resolve_channel()`. `shutdown_pc()` y `close_app()` cambian
  `ch = _resolve_channel(channel)` por `ch = security_manager.resolve_channel(channel)`.

### `skills/code_execution_skill.py`, `skills/skill_creator_skill.py`
- `channel = params.get("channel", ChannelType.DESKTOP)` → `channel = params.get("channel")`. El
  default permisivo se elimina de cada skill individual; `require_confirmation()` resuelve con
  `ChannelType.UNKNOWN` si de verdad no hay canal.

### `agents/action_registry.py`
- `execute_action(name: str, params: Optional[dict] = None, channel: "ChannelType | str | None" = None, user_id: str = "default") -> str` —
  **nueva**, único punto de ejecución gateado del registro:
  ```python
  def execute_action(name: str, params: Optional[dict] = None, channel=None, user_id: str = "default") -> str:
      info = ACTION_REGISTRY.get(name)
      if not info:
          return f"Acción '{name}' no reconocida."
      if not security_manager.require_confirmation(name, channel, details=f"action_registry:{name}", user_id=user_id):
          return f"⛔ Acción '{name}' no autorizada."
      fn = info["fn"]
      params = params or {}
      return fn(**params) if params else fn()
  ```
  `get_action()` se mantiene (introspección/planner), pero deja de ser el camino de ejecución.

### `agents/task_executor.py`
- `TaskExecutor.execute(self, plan: list[dict], on_step_done=None, channel=None) -> str` y
  `execute_single(self, action_name: str, params: dict = {}, channel=None) -> str` — reemplazan
  `action_info["fn"](**params)` por `execute_action(action_name, params, channel=channel)`.

### `learning/routines_engine.py`
- `execute_routine_actions(actions: list[dict], channel=None) -> str` y
  `try_routine(user_text: str, channel=None) -> str | None` — reemplazan el acceso directo a
  `ACTION_REGISTRY[action_name]["fn"]` por `agents.action_registry.execute_action(action_name, params, channel=channel)`.

### `os_integration/capabilities_router.py`
- `execute_capability(cap: dict, channel=None) -> str` — gate agregado antes de `func(**params)`,
  usando como nombre de acción `f"{modulo_name}.{func_name}"` (namespace propio para evitar
  colisión con nombres de `action_registry`). Como `system_capabilities.json` no existe hoy
  (`_load_capabilities()` retorna `[]`), este camino está dormido — el fail-closed asegura que el
  día que alguien agregue una entrada al JSON, no se ejecute nada hasta que también se registre su
  clasificación en código. Se documenta como propiedad de seguridad intencional, no como fallo.
- `try_capability(user_text: str, channel=None) -> str | None` — recibe y propaga `channel`.

### `core/proactive_engine.py`
- Línea `action_key = f"proactive_{trigger.agent.name}"` → `action_key = "proactive_trigger"`
  (hallazgo propio #1). Se registra `"proactive_trigger"` GREEN en `_register_default_actions()`.

### `main.py`
- Antes de `result = dispatch(intent, params)` (loop principal): `params["channel"] = "desktop"`.
- Dentro de `execute_simulated_action(action_text)`: `act_params["channel"] = "desktop"` antes de
  `dispatch(act_intent, act_params)`.
- `try_routine(command)` → `try_routine(command, channel="desktop")`.
- `executor.execute(plan, on_step_done=on_step)` → `executor.execute(plan, on_step_done=on_step, channel="desktop")`.
- `try_capability(command)` → `try_capability(command, channel="desktop")`.
- (Opcional recomendado, no bloqueante) llamar `security_manager.check_coverage(...)` una vez al
  arrancar con la lista de intents reales + de skills, y loggear cualquier hueco con
  `logger.warning`.

## Flujo de datos

```
Entrada (Telegram/Discord/API/Voice/Desktop)
        │
        ▼
channels/*.py ──channel real conocido──▶ orchestrator.process_task(text, channel, user_id)
        │
        ├─▶ _try_quick_dispatch ──▶ dispatch(intent, params={"channel": channel, ...})  [ya correcto hoy]
        │
        └─▶ _process_with_agents ──▶ _execute_single_agent/_execute_agent_chain
                    ──▶ context_data["channel"] = channel
                    ──▶ agent.execute(task, context_data)
                          ──▶ _DynamicAgentInstance.execute()
                                ──▶ tool.execute({"task":.., "context":.., "channel": context["channel"]})  [FIX]
                                      │
                    ┌─────────────────┼─────────────────────┐
                    ▼                                        ▼
           tool = "dispatcher"                      tool = "skill_<intent>"
           dispatch_as_tool(params)                  _make_gated_tool_fn(skill, intent)(params)
           channel = params.get("channel")           channel = params.get("channel") or context.channel
           ──▶ dispatch(intent, params)               ──▶ security_manager.require_confirmation(intent, channel)
                                                             │ bloqueado ──▶ "⛔ Acción no autorizada."
                                                             │ permitido ──▶ skill.execute(intent, params)
                    │
                    ▼
        dispatch(intent, params)
          channel = params.get("channel")
          ┌─ skill_manager.handles_intent(intent)?
          │      sí ──▶ skill_manager.execute(intent, params)
          │              ──▶ security_manager.require_confirmation(intent, channel)
          │                    │ bloqueado ──▶ "⛔ Acción no autorizada."
          │                    │ permitido ──▶ skill.execute(intent, params)
          │      no ──▶ security_manager.require_confirmation(action_name, channel)
          │               │ bloqueado ──▶ "⛔ Acción no autorizada."
          │               │ permitido ──▶ handler(params)   [executor/handlers.py, system_action_handlers.py]
          └───────────────┘

main.py (loop desktop) ──channel="desktop" inyectado──▶ try_routine / TaskExecutor.execute / try_capability
        │
        ▼
routines_engine / task_executor ──▶ agents.action_registry.execute_action(name, params, channel)
                                          ──▶ security_manager.require_confirmation(name, channel)
                                                │ bloqueado ──▶ mensaje de error, no se ejecuta fn
                                                │ permitido ──▶ fn(**params)

os_integration/capabilities_router.py ──▶ execute_capability(cap, channel)
                                          ──▶ security_manager.require_confirmation("modulo.funcion", channel)
                                                │ bloqueado / permitido (igual patrón)

─── Dentro de security_manager.require_confirmation() (única lógica de decisión) ───
channel = resolve_channel(channel)                 # None/desconocido → UNKNOWN, no DESKTOP
level = classify_action(action_name)               # None si nunca se registró
level is None            → auditar "bloqueada_no_clasificada", return False        [FAIL-CLOSED]
level == GREEN            → auditar "permitida", return True
level == YELLOW            → is_action_allowed? no → auditar "bloqueada_canal", False
                             sí → input() de confirmación (sin cambios) → auditar, return
level == RED               → auditar "intento_rojo"
                             channel == DESKTOP and has_pin()? → require_pin() (getpass, 3 intentos)
                                 verificado → auditar "autorizada_rojo", return True
                             cualquier otro caso → mensaje "ROJO. No autorizada.", return False
```

## Archivos a modificar/crear

- `core/security_manager.py`
- `router/dispatcher.py`
- `skills/skill_manager.py`
- `core/base_agent.py`
- `os_integration/system_ctrl.py`
- `skills/code_execution_skill.py`
- `skills/skill_creator_skill.py`
- `agents/action_registry.py`
- `agents/task_executor.py`
- `learning/routines_engine.py`
- `os_integration/capabilities_router.py`
- `core/proactive_engine.py`
- `main.py`
- `.claude/rules/security-levels.md`
- `tests/test_security_manager.py` (nuevo)

## Dependencias nuevas

Ninguna. Todo el diseño usa `enum`, `sqlite3`, `logging`, `getpass` (ya en uso) y las funciones
propias del proyecto. No se agrega nada a `requirements.txt`.

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| Doble prompt de confirmación (YELLOW) si dos capas gatean la misma acción | Diseño explícito de "un solo gate por acción": `dispatch()` no gatea si delega a `skill_manager.execute()` (que gatea internamente); cada camino tiene exactamente un punto de gate en su propia función de entrada. Test dedicado cuenta invocaciones de `require_confirmation`/`input`. |
| Fail-closed rompe funcionalidad real no inventariada | Inventario de `baseline-005.md` usado como fuente de verdad para clasificar el 100% de los intents y funciones de `action_registry.py` conocidos hoy; `check_coverage()` como red de diagnóstico en logs para detectar huecos futuros sin bloquear el arranque. |
| Regresión en `core/proactive_engine.py` (nombre de acción dinámico nunca registrado) | Detectado en el diseño (hallazgo propio #1); fix incluido en el alcance: nombre estable `"proactive_trigger"` registrado GREEN. |
| Regresión en `main.py` (dispatch directo sin canal → YELLOW bloqueado en desktop) | Detectado en el diseño (hallazgo propio #2); fix incluido: inyectar `channel="desktop"` en los 4 puntos de llamada identificados. |
| Nueva fricción en Autopilot por clasificar `write_file_direct`/`save_file_desktop` como YELLOW | Cambio de comportamiento real, no solo de clasificación — señalado aparte para aprobación humana explícita; alternativa de dejarlos GREEN documentada si el humano prefiere no introducir la pausa. |
| `capabilities_router.py` dormido hoy (JSON inexistente); riesgo futuro si alguien agrega una capacidad peligrosa sin clasificarla | Fail-closed bloquea por diseño cualquier capacidad nueva no clasificada explícitamente en código — es una propiedad de seguridad, no un caso pendiente. |
| Protección de reclasificación solo cubre RED (no YELLOW→GREEN) | Coincide literalmente con el alcance de la SPEC; riesgo residual aceptado y documentado, no oculto. |
| Contaminación de estado del singleton `SecurityManager` entre tests (dict `_actions` compartido en memoria de proceso) | Tests de reclasificación se auto-verifican (RED no puede degradarse, así que no corrompen el estado real); tests de fail-closed usan nombres de acción exclusivos de test (`"__test_unclassified__"`) que no colisionan con producción. |
| Brecha regla-vs-código preexistente (volumen, mouse/teclado) queda sin cerrar | Documentado como decisión explícita, no como omisión — la SPEC excluye cambios de UX YELLOW y el humano acotó el alcance contra scope creep; candidato a REQ futuro. |

## Pruebas sugeridas

Todas en `tests/test_security_manager.py` (funciones `test_*` reales, ejecutables por pytest —
corrige el patrón muerto que orion-baseline encontró en `test_classifier.py`/`test_dispatcher.py`/
`test_autopilot.py`/`test_memory.py`). Mocks vía `unittest.mock.patch` para `input()` y
`getpass.getpass()`; `monkeypatch` de pytest para `ORION_AUTH_PIN` y para `core.security_manager.AUDIT_DB`
apuntando a `tmp_path` (nunca se toca el `audit.db` real), según `.claude/rules/testing.md`.

1. `test_all_ten_red_categories_registered` — parametrizado sobre las 10 categorías RED; cada una
   `classify_action(...) == RiskLevel.RED`. (CA "10 categorías RED".)
2. `test_unclassified_action_blocked_by_default` — nombre inventado nunca registrado →
   `require_confirmation()` retorna `False`; audita `"bloqueada_no_clasificada"`. (CA fail-closed.)
3. `test_bypass_without_own_confirmation_call_is_blocked` — simula un handler/skill que intenta
   ejecutar `"format_disk"` **sin** llamar `require_confirmation()` por su cuenta, pasando
   directamente por uno de los puntos de gate (`dispatch()`); verifica que el cuerpo de la acción
   nunca se ejecuta (usar una función simulada con un flag booleano que solo se pone en `True` si
   se ejecuta). (CA resistencia a bypass.)
4. `test_prompt_injection_fake_pin_ignored` — invoca el gate para una acción RED en DESKTOP con
   `ORION_AUTH_PIN` sin configurar, pasando parámetros simulados con `{"pin": "0000", "confirmed": True}`
   que el gate nunca lee; debe seguir bloqueado. (CA resistencia a prompt-injection.)
5. `test_register_action_cannot_downgrade_red` — registra `"format_disk"` como RED (ya lo está),
   intenta `register_action("format_disk", RiskLevel.GREEN)`, verifica que retorna `False` y que
   `classify_action("format_disk")` sigue siendo `RED`. (CA reclasificación.)
6. `test_red_action_blocked_per_channel` — parametrizado sobre TELEGRAM/DISCORD/VOICE/API/UNKNOWN;
   ninguno permite RED, ni con `has_pin() == True`. (CA por canal.)
7. `test_red_action_desktop_without_pin_configured_blocked` — `has_pin() == False`, canal DESKTOP →
   bloqueado sin ofrecer excepción (caso borde ya correcto, test de no-regresión).
8. `test_red_action_authorized_via_pin_desktop_only` — mockea `getpass.getpass` retornando el PIN
   correcto, `ORION_AUTH_PIN` seteado vía monkeypatch, canal DESKTOP → `True`. Repetir con canal
   TELEGRAM (mismo PIN "correcto" simulado en `params`, no interactivo) → sigue bloqueado. (CA vía
   única de excepción.)
9. `test_red_action_blocked_logged_in_audit` y `test_red_action_authorized_logged_in_audit` —
   `AUDIT_DB` redirigida a `tmp_path`; se inspecciona la tabla `audit_log` y se verifica
   timestamp/canal/acción/resultado. (CA auditoría.)
10. `test_green_actions_regression_free` — parametrizado sobre una muestra representativa de
    intents GREEN reales (`OPEN_APP`, `SEARCH_WEB`, `GET_TIME`, `CHAT`, etc.) y de
    `action_registry` (`open_chrome`, `get_disk_info`, etc.) → `require_confirmation()` retorna
    `True` sin invocar `input()`. (CA regresión cero.)
11. `test_yellow_ux_unchanged` — mockea `input()` devolviendo `"si"`/`"no"`; verifica que
    `"shutdown"` sigue pidiendo confirmación exactamente igual que antes (mismo mensaje, mismo
    comportamiento confirmar/cancelar). (CA UX YELLOW sin cambios.)
12. `test_channel_resolution_defaults_safe` — `resolve_channel(None)`, `resolve_channel("valor_basura")`
    → `ChannelType.UNKNOWN`; `resolve_channel("api")` → `ChannelType.API`; `resolve_channel(ChannelType.DESKTOP)`
    → idempotente. (Regresión directa del hallazgo 2 de baseline.)
13. `test_agent_chain_propagates_real_channel` — construye un `AgentTool` de prueba que captura el
    `params` recibido; ejecuta `_DynamicAgentInstance.execute(task, context={"channel": "telegram", ...})`
    y verifica que `params["channel"] == "telegram"` a nivel superior (no `None`, no `"desktop"`
    implícito). Prueba directa del fix de channel-spoofing en `core/base_agent.py`.
14. `test_action_registry_execute_action_gated` — `execute_action("format_disk_test_stub", ...)`
    con un stub temporal registrado como RED en `ACTION_REGISTRY` (o usando un nombre de acción de
    prueba clasificado RED vía `register_action`) → bloqueado, la función subyacente no se invoca.
15. `test_capabilities_router_execute_capability_gated` — capacidad de prueba (dict `cap` construido
    en el test, sin depender de `system_capabilities.json`) apuntando a una función inocua no
    clasificada → bloqueada por fail-closed con el mensaje correspondiente.
16. `test_proactive_trigger_action_registered_green` — `is_action_allowed("proactive_trigger", ChannelType.DESKTOP) is True`.
    Regresión directa del hallazgo propio #1.
17. `test_intent_and_skill_actions_fully_classified` — reúne todos los valores de `Intent` más
    `get_intents()` de cada skill cargada por `skill_manager`, llama `check_coverage(...)`, y
    verifica que la lista de faltantes es vacía. Vive como guarda de regresión permanente contra
    intents/skills futuros agregados sin clasificar.

Además: verificar `python -m pytest tests/ --tb=short -v` completo (los 5 tests de
`test_agents.py` deben seguir pasando) como parte del DoD de `orion-tester`, no como test nuevo.
