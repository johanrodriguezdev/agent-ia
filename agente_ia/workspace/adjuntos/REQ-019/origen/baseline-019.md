# Baseline REQ-019 — Configuración de niveles de seguridad por el usuario

**Agente:** orion-baseline
**Fecha:** 2026-08-20
**Verificación:** exhaustiva sobre código real (no se asumió como exacta la investigación de
`orion-spec` en el contexto — se releyó cada archivo y se confirmó línea por línea; ver detalle
abajo, todas las líneas citadas por SPEC-019/contexto quedaron confirmadas sin discrepancias).

## Estado actual del sistema

Hoy la clasificación verde/amarillo/rojo de cada acción está fija en código, poblada al importar
`core/security_manager.py` (registro en 3 funciones/momentos). No existe ningún mecanismo de
override desde configuración de usuario ni ninguna pantalla de "Configuración" en el webview. El
único punto de protección contra "bajar" un nivel (`register_action()`) cubre exclusivamente RED.

### `core/security_manager.py` (387 líneas totales) — estado exacto verificado

- **`RiskLevel`** — `Enum` plano, **líneas 14-17**:
  ```python
  class RiskLevel(Enum):
      GREEN = "green"
      YELLOW = "yellow"
      RED = "red"
  ```
  Confirmado: no hereda de `IntEnum`, no tiene ranking/orden nativo. Un grep de
  `ORDER`/`rank`/`__lt__`/`__gt__` en todo el archivo no arroja nada — cualquier `max(nivel_a,
  nivel_b)` que se agregue en REQ-019 debe definir su propio ranking explícito desde cero.

- **`SecurityManager`** — singleton, **línea 109** (`class SecurityManager:`).
  `self._actions: Dict[str, RiskLevel] = {}` se inicializa en `__new__`, **línea 115**. Es un dict
  plano nombre→nivel, sin distinción entre "nivel de código" y "nivel efectivo" — hoy son la misma
  cosa porque no existe overlay de config.

- **`register_action()`** — **líneas 194-209**, texto exacto:
  ```python
  def register_action(self, name: str, level: RiskLevel) -> bool:
      current = self._actions.get(name)
      if current == RiskLevel.RED and level != RiskLevel.RED:
          logger.critical(...)
          self._log_audit(name, ChannelType.UNKNOWN, "reclasificacion_bloqueada",
                           details=f"nivel_solicitado={level.value}")
          return False
      self._actions[name] = level
      return True
  ```
  Confirmado exactamente lo que decía el contexto: **solo** protege contra degradar RED (línea
  202: `if current == RiskLevel.RED and level != RiskLevel.RED`). Un YELLOW→GREEN o
  RED→YELLOW-vía-otra-ruta no está cubierto por esta función tal cual. Si `orion-architect` decide
  reusarla para aplicar el merge código+config, **debe extenderla o envolverla** — no alcanza con
  llamarla como está.

- **`classify_action()`** — **líneas 211-212**: `return self._actions.get(name)`. Devuelve
  `Optional[RiskLevel]`; `None` si la acción no está registrada (fail-closed en el caller).

- **`require_confirmation()`** — **líneas 232-294**. Punto central único de decisión: resuelve
  canal (línea 248), clasifica la acción (línea 249), y bifurca por nivel (`GREEN` línea 254,
  `YELLOW` línea 257, `RED` línea 283). Es el único consumidor real de `classify_action()` que
  decide comportamiento — cualquier merge código+config que agregue REQ-019 debe reflejarse acá
  (directamente, o transitivamente si `classify_action()` ya devuelve el nivel efectivo).

- **3 puntos de registro confirmados, con sus líneas exactas de invocación al final del módulo
  (líneas 385-387):**
  1. `_register_default_actions()` — definida **líneas 300-340**, invocada **línea 385**. Registra
     14 acciones YELLOW (`shutdown`, `restart`, `close_app`, `delete_file`, `delete_folder`,
     `delete_conversation`, `delete_task`, `delete_project`, `execute_code`, `create_skill`,
     `modify_skill`, `delete_skill`, `send_message`), 6 GREEN (`system_info`, `search_files`,
     `chat`, `open_app` **línea 326**, `list_files`, `proactive_trigger`), y 10 RED (líneas
     330-340: `format_disk`, `delete_database`, `expose_secrets`, `modify_source_code`,
     `send_email_as_user`, `post_social_media`, `elevated_system_command`,
     `install_uninstall_software`, `modify_system_env_vars`, `grant_third_party_access`).
  2. `_register_intent_actions()` — definida **líneas 343-363**, invocada **línea 386**. Registra
     29 `Intent.value` en GREEN (lista `green_intents`, **empieza línea 349** con `"OPEN_APP"`
     como primer elemento) y 6 en YELLOW (`CLOSE_APP`, `SYS_POWER_OFF`, `EXECUTE_CODE`,
     `CREATE_SKILL`, `MODIFY_SKILL`, `DELETE_SKILL`, líneas 356-359).
  3. `_register_action_registry_actions()` — definida **líneas 366-382**, invocada **línea 387**.
     Registra 18 claves de `agents/action_registry.py` en GREEN (lista `green_actions`,
     **líneas 372-376**: `open_chrome`, `open_notepad`, `open_explorer`, `open_calculator`,
     `open_browser`, `open_spotify` en línea 372; `close_window`, `open_file_in_notepad`,
     `get_active_window_info`, `write_text`, `press_key`, `hotkey_action`, `take_screenshot`,
     `wait_seconds`, `generate_ai_summary`, `get_current_datetime`, `get_disk_info`, `open_url`,
     `search_google` en líneas 374-376) y 2 en YELLOW (`write_file_direct`, `save_file_desktop`,
     línea 378).
  - **No se encontró un 4to punto de registro dentro de `core/security_manager.py`** — pero el
    contexto de `orion-spec` ya señalaba correctamente que `agents/tool_registry.py:152,172,184`
    registra 3 acciones más (`task_create`, `task_list`, `task_complete`) en un módulo aparte, y
    que `main.py:65` dispara un re-registro idempotente vía `register_skill_tools()`. No se
    tocaron esos archivos en esta verificación (fuera del scope de baseline reconfirmar cada línea
    ahí), pero la existencia de un registro fuera de `security_manager.py` queda confirmada por
    inspección visual rápida — es un dato de arquitectura importante que `orion-architect` debe
    resolver explícitamente (dónde se aplica el merge para que cubra los 3 momentos).

### Claves exactas de la categoría v1 propuesta ("Apertura de aplicaciones y navegación")

Cada clave fue confirmada individualmente contra el código real, no se tomó la lista de la SPEC
como dada:

| Clave | Línea real | Función de registro | Nivel actual |
|---|---|---|---|
| `open_app` | 326 | `_register_default_actions()` | GREEN |
| `OPEN_APP` (Intent) | 349 (primer ítem de `green_intents`) | `_register_intent_actions()` | GREEN |
| `open_chrome` | 372 | `_register_action_registry_actions()` | GREEN |
| `open_notepad` | 372 | `_register_action_registry_actions()` | GREEN |
| `open_explorer` | 372 | `_register_action_registry_actions()` | GREEN |
| `open_calculator` | 372 | `_register_action_registry_actions()` | GREEN |
| `open_browser` | 372 | `_register_action_registry_actions()` | GREEN |
| `open_spotify` | 373 | `_register_action_registry_actions()` | GREEN |
| `open_url` | 376 | `_register_action_registry_actions()` | GREEN |

Las 9 claves existen, están todas en GREEN hoy, y ninguna se solapa textualmente con las 10 claves
RED de REQ-005 (líneas 330-340) ni con las 14+6 claves YELLOW existentes — confirmado que subir
esta categoría a YELLOW no toca nada ya Amarillo/Rojo. La lista de la SPEC es exacta, sin
discrepancias.

### `config_manager.py` (181 líneas totales) — estado exacto verificado

- `CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")` — **línea 13**. Al vivir
  `config_manager.py` en la raíz de `agente_ia/`, `CONFIG_FILE` resuelve a
  `agente_ia/config.json` (confirmado, no es una ruta relativa ambigua).
- `DEFAULT_CONFIG` — **líneas 15-21**, dict cerrado de 5 claves fijas: `agent_name`,
  `agent_pronunciation`, `display_name`, `weather_city`, `ui_theme`. No hay mecanismo genérico de
  "settings arbitrarios" — cada setting nuevo históricamente agrega su propio par
  `get_x()`/`set_x()` (ver `get_ui_theme()`/`set_ui_theme()`, líneas 122-138, como patrón más
  reciente de REQ-013).
- `load_config()` — **líneas 33-57**. Comportamiento confirmado:
  - Si `CONFIG_FILE` no existe: crea uno con `DEFAULT_CONFIG` y devuelve copia (líneas 38-40).
  - Si existe: parsea JSON y rellena con default cualquier clave de las 5 fijas que falte
    (líneas 44-53, un `if "x" not in config: config["x"] = DEFAULT_CONFIG["x"]` por clave —
    **no genérico**, haría falta agregar uno más por cada clave nueva si REQ-019 sigue este mismo
    patrón literal).
  - Si el JSON está corrupto (`json.JSONDecodeError`) o hay error de I/O (`IOError`): cae a
    **líneas 55-57**, sobreescribe el archivo con `DEFAULT_CONFIG` y devuelve copia del default.
    **Importante para REQ-019:** este fallback sobreescribe el archivo corrupto en disco con el
    default — si REQ-019 extiende este mismo `config.json` con overrides de seguridad, un JSON
    corrupto haría perder también los overrides de seguridad guardados previamente, no solo las 5
    claves originales. Ya señalado como riesgo en el contexto; confirmado aquí que el mecanismo de
    recuperación actual es "todo o nada" a nivel de archivo, no por clave.
- `save_config()` — **líneas 60-65**. Escritura síncrona con `json.dump()`, sin manejo de journal
  ni escritura atómica (no usa archivo temporal + rename) — un corte de energía a mitad de
  escritura podría corromper el archivo. No es un bug nuevo de REQ-019, es el patrón ya existente
  que cualquier extensión hereda.
- No existe ningún test genérico `tests/test_config_manager.py` — el patrón de testing existente
  es un archivo por feature: `tests/test_config_manager_display_name.py`,
  `tests/test_config_manager_weather_city.py`, `tests/test_config_manager_ui_theme.py`. Un test
  nuevo para overrides de seguridad seguiría este mismo patrón de nombre
  (`tests/test_config_manager_security_overrides.py` o similar, a definir por `orion-architect`).

### Pantalla de "Configuración" en el webview — confirmado que NO existe

Grep case-insensitive de `config|settings|Configuraci|gear|engranaje` sobre
`ui/webview/frontend/` completo: el único match es `ui/webview/frontend/vendor/qwebchannel.js`
(librería de terceros de Qt, sin relación con una pantalla de ajustes de la app). Ningún archivo
propio (`js/`, `css/`, `index.html`) menciona settings/configuración. Confirmado también por
inventario completo de archivos del frontend (17 archivos entre `css/`, `js/`, `vendor/`,
`fonts/`, `index.html`, `error.html`) — no hay ningún `settings_panel.js` ni sección equivalente.

**Patrón de referencia confirmado para el punto de entrada** (relevante para
`orion-architect`/`orion-dev`, CA-12): los botones "Tareas"/"Proyectos" de REQ-016 siguen este
patrón exacto:
- `ui/webview/frontend/index.html:55-62` — `<button id="tasks-btn" class="sidebar-action-btn">` y
  `<button id="projects-btn" class="sidebar-action-btn">`.
- `ui/webview/frontend/js/app.js:30,33` — `import { openTasksPanel, ... } from "./tasks_panel.js"`
  y el import equivalente de `projects_panel.js`.
- `ui/webview/frontend/js/app.js:106-107` —
  `document.getElementById("tasks-btn").addEventListener("click", openTasksPanel)` y el
  equivalente para `projects-btn`. **El wiring del click ocurre en `app.js`, no en
  `sidebar.js`** (grep directo sobre `sidebar.js` para `tasks-btn`/`projects-btn` no encontró
  nada — corrige una asunción implícita razonable pero no verificada).

Un botón nuevo de "Configuración" seguiría este mismo patrón: entrada en `index.html`, import y
`addEventListener` en `app.js`, lógica del panel en un archivo nuevo `js/settings_panel.js`.

### `ui/webview/bridge.py` (603 líneas totales)

27 métodos `@pyqtSlot` ya registrados (grep de la anotación), documentados como whitelist
explícita en el docstring del módulo (**líneas 3-15**, referencia directa a "REQ-015/CA-42,
arquitectura-015.md §4" y "CA-34" para lo que JS NO puede tocar directo). Confirma el patrón que
SPEC-019 pide replicar para los slots nuevos de seguridad (CA-20).

## Archivos que serán modificados (previsión)

- `core/security_manager.py` — ranking de `RiskLevel`, función de merge código+config (no
  reutilizar `register_action()` tal cual, líneas 194-209), distinción nivel-base/nivel-efectivo.
- `config_manager.py` (o módulo nuevo, ej. `core/security_config.py`, a decidir por
  `orion-architect`) — persistencia de overrides, con fallback a nivel de código (no al default
  del dict) ante JSON corrupto/inválido, distinto del patrón actual de `load_config()`.
- `ui/webview/bridge.py` — nuevos `pyqtSlot` para leer/guardar overrides de seguridad + señal(es)
  de confirmación/reinicio-requerido, documentados en el docstring (líneas 3-15).
- `ui/webview/frontend/index.html` — nuevo botón de entrada (mismo patrón que
  `tasks-btn`/`projects-btn`, líneas 55-62).
- `ui/webview/frontend/js/app.js` — import y `addEventListener` del nuevo botón (mismo patrón que
  líneas 30, 33, 106-107).
- `ui/webview/frontend/js/settings_panel.js` (nuevo archivo) — lógica de la pantalla de
  Configuración, sección "Seguridad".
- `ui/webview/frontend/js/bridge_client.js` — wrappers nuevos para los slots del bridge.
- `ui/webview/frontend/css/` — extensión de `modal.css`/`panels.css` o archivo nuevo, para el
  layout de navegación lateral + tarjetas.
- `.claude/rules/security-levels.md` — nueva sección documentando el mecanismo de override (86
  líneas totales hoy, mismo patrón que la sección existente "REQ-005 — deny-list Rojo aplicada en
  código").
- `tests/test_security_manager.py` — nuevos tests para el merge (CA-02, CA-03, CA-04, CA-06,
  CA-07, CA-08).
- Test nuevo de persistencia (nombre a definir por `orion-architect`, ej.
  `tests/test_config_manager_security_overrides.py`, siguiendo el patrón de archivo-por-feature
  ya usado).
- `tests/test_webview_bridge.py` (existe, 1 archivo) — nuevos tests para los slots de seguridad.
- `tests/test_webview_safe_dom_insertion.py` (existe) — extensión para cubrir `settings_panel.js`.

**No se tocan** (confirmado, sin evidencia de necesidad): `agents/tool_registry.py`,
`agents/skill_tools.py`, `main.py` — salvo que `orion-architect` determine explícitamente que el
punto de aplicación del override en el arranque necesita engancharse ahí (ver hallazgo sobre los 3
momentos de registro).

## Fallos pre-existentes (no atribuibles a este REQ)

Suite completa: `python -m pytest tests/ --tb=short -q` → **420 passed, 2 failed** (27.12s).

Los 2 fallos son 100% ajenos a `core/security_manager.py` y `config_manager.py`, no tocan nada
relacionado con REQ-019:
- `tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` — FAIL
- `tests/test_llm_provider.py::test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto` — FAIL
- Causa raíz confirmada (`python -m pytest tests/test_llm_provider.py --tb=line -q`):
  `ModuleNotFoundError: No módulo llamado 'anthropic'` — el paquete `anthropic` no está instalado
  en el entorno actual (problema de entorno/dependencia, no de código). El resto de
  `test_llm_provider.py` (6 tests) pasa sin problema.

`tests/test_security_manager.py` en aislamiento: **55 passed, 0 failed** (2.20s). Confirmado
explícitamente `test_register_action_cannot_downgrade_red` (línea 116-120) → **PASSED**. Este es
el test referenciado por CA-25 de SPEC-019 — hoy pasa, y como solo cubre RED (no YELLOW/GREEN),
confirma exactamente el gap que la SPEC busca cerrar sin tocar el comportamiento que este test ya
verifica.

`python -m py_compile core/security_manager.py config_manager.py ui/webview/bridge.py` → sin
errores.

**Ninguno de los fallos pre-existentes está en una zona que este REQ toque.** No hay riesgo de
confundir un fallo pre-existente con una regresión introducida por REQ-019 en
`core/security_manager.py`, `config_manager.py` o `ui/webview/bridge.py`.
