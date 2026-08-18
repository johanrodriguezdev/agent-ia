# Baseline REQ-012 — Fix ubicación de clima y saludo dinámico congelado en GUI JARVIS

**Fecha:** 2026-08-05
**Agente:** orion-baseline
**SPEC de referencia:** `workspace/adjuntos/REQ-012/spec/SPEC-012.md` (✅ aprobada)

## Estado actual del sistema

### 1. `config_manager.py`
- `DEFAULT_CONFIG` (líneas 15-19) solo tiene `agent_name`, `agent_pronunciation`,
  `display_name`. **No existe** ninguna clave `weather_city`.
- `load_config()` (líneas 31-51) hace backfill manual clave por clave para configs
  viejas (`if "agent_name" not in config: ...`, etc. para las 3 claves de arriba). No
  hay backfill para `weather_city` — hay que añadirlo siguiendo el mismo patrón (líneas
  42-47).
- `get_display_name()` / `set_display_name()` (líneas 83-96) son el patrón de
  referencia exacto que SPEC-012 pide replicar: `get_*` hace `load_config().get(key, "")`,
  `set_*` hace `config[key] = value.strip()` y `save_config(config)`. `set_display_name`
  no usa `.lower()` (a diferencia de `set_agent_name`) — coherente con CA-02
  ("mismo criterio que `set_display_name()`", solo `.strip()`, sin normalizar mayúsculas).
- `save_config()` (líneas 54-59) ya maneja `IOError` con logging — reutilizable sin cambios.
- No hay ninguna función `get_weather_city`/`set_weather_city` en el archivo hoy.

### 2. `ui/widgets/weather_card.py`
- `WeatherCard.__init__` (líneas 19-23) llama `self._build_ui()` y luego `self._fetch()`
  en el constructor — I/O de red disparado inmediatamente al crear el widget.
- `_fetch()` (líneas 56-57) llama `run_async(get_weather_structured, self._on_done,
  self._on_error)` — **sin argumento de ciudad**, es decir invoca
  `get_weather_structured` con su default `city=""` (geolocalización 100% por IP). Este
  es el bug raíz confirmado por `orion-spec`.
- No importa `config_manager` actualmente (solo importa
  `os_integration.weather_data` y `ui.gui_workers`).
- `set_data()` (líneas 65-76) y el resto del widget no requieren cambios según el
  alcance de la SPEC.

### 3. `ui/widgets/center_panel.py`
- `_resolve_display_name()` (líneas 37-44) ya usa `config_manager.get_display_name()`
  con fallback a `os.environ.get("USERNAME", "")` — patrón de resolución de config que
  puede servir de referencia, aunque SPEC-012 no lo toca.
- `CenterPanel.__init__` (líneas 54-58) solo llama `self._build_ui()`. **No hay ningún
  `QTimer`** en la clase hoy.
- `_build_ui()` (líneas 60-116) calcula `greeting = get_time_based_greeting(display_name)`
  **una sola vez** (línea 66) y lo asigna a `self._greeting_label = QLabel(greeting)`
  (línea 68). Nunca se vuelve a invocar `get_time_based_greeting` después de la
  construcción — confirma el bug raíz de "saludo congelado" identificado por
  `orion-spec`.
- No hay imports de `QTimer` en el archivo (`from PyQt6.QtCore import Qt, pyqtSignal`,
  línea 10 — sin `QTimer`).
- No hay ningún método de cleanup/`closeEvent`/`__del__` en la clase.

### Precedente de `QTimer` ya existente en el codebase (relevante para CA-06/CA-09)
`ui/widgets/system_status_card.py` (líneas 61-64) ya usa el patrón:
```python
self._timer = QTimer(self)          # parented al widget -> Qt lo destruye/detiene
self._timer.timeout.connect(self._refresh)
self._timer.start(_REFRESH_MS)
```
Al pasar `self` como parent del `QTimer`, Qt lo destruye automáticamente (y por tanto
detiene) cuando el widget padre se destruye — sin necesidad de código de cleanup
explícito. Este es el único otro widget del proyecto con un timer periódico y es
candidato natural de patrón a replicar para CA-06/CA-09 en `CenterPanel`. (Se documenta
como referencia; la decisión de diseño concreta le corresponde a `orion-architect`.)

### `os_integration/weather_data.py` y `ui/personality.py` (fuera de alcance de lógica, confirmado)
- `get_weather_structured(city: str = "") -> Optional[WeatherData]` (línea 34) **ya
  acepta `city` como parámetro** y ya lo usa para construir la URL de wttr.in (línea
  41-42) y como fallback de `city_name` (línea 60). No requiere cambios — confirma lo
  que dice SPEC-012 ("sin cambios de lógica esperados").
- `get_time_based_greeting(display_name: str = "") -> str` (línea 95 de
  `ui/personality.py`) es pura (usa `datetime.now()` internamente, sin estado) y ya está
  cubierta por `tests/test_personality_greeting.py` (12 tests, todos en verde). No
  requiere cambios — confirma lo que dice SPEC-012.

## Archivos que serán modificados (previsión)

- `config_manager.py` — agregar clave `weather_city` a `DEFAULT_CONFIG`, backfill en
  `load_config()`, funciones `get_weather_city()` / `set_weather_city()` (CA-01, CA-02).
- `ui/widgets/weather_card.py` — importar `config_manager`, hacer que `_fetch()` lea
  `config_manager.get_weather_city()` y la pase a `get_weather_structured(city)` (CA-03,
  CA-04).
- `ui/widgets/center_panel.py` — importar `QTimer` de `PyQt6.QtCore`, agregar el timer
  en `__init__`/`_build_ui()`, y un método de callback que reevalúe el saludo y
  actualice `_greeting_label` solo si cambió (CA-06, CA-07, CA-08, CA-09).

Probables adiciones de test (no modifican lógica de producción, pero son archivos que
`orion-dev`/`orion-tester` tocarán):
- `tests/test_config_manager_display_name.py` (o un archivo nuevo
  `tests/test_config_manager_weather_city.py`) — para CA-01, CA-02, siguiendo el patrón
  exacto ya usado ahí para `display_name` (redirección de `CONFIG_FILE` a `tmp_path`).
- `tests/test_gui_widgets.py` — para CA-03/CA-04 (WeatherCard) y CA-06/CA-07/CA-08/CA-09
  (CenterPanel), siguiendo el patrón de `no_external_io` / `qtbot` ya presente.

No se prevén cambios en `os_integration/weather_data.py` ni `ui/personality.py` (SPEC-012
lo excluye explícitamente y el código actual ya soporta lo que la SPEC necesita).

## Fallos pre-existentes (no atribuibles a este REQ)

Ninguno. `python -m pytest tests/ --tb=short` → **216 passed, 0 failed** (3 warnings
menores no relacionados: 2 `DeprecationWarning` de `speech_recognition`/`aifc`/`audioop`
en una librería de terceros, 1 `PytestReturnNotNoneWarning` en
`tests/test_agents.py::test_ca1_orchestrator`, preexistente y fuera del alcance de
categoría UI).

`python -m py_compile` sobre los 5 módulos relevantes (`config_manager.py`,
`ui/widgets/weather_card.py`, `ui/widgets/center_panel.py`,
`os_integration/weather_data.py`, `ui/personality.py`) → compila sin errores.

## Nota sobre trabajo concurrente (REQ-007 / REQ-011)

El árbol de trabajo tiene cambios sin commitear en `main.py`,
`workspace/adjuntos/REQ-007/REQ-007-context.md`, `tests/test_main.py` y
`tests/test_gui_widgets.py` — corresponden a trabajo en curso de otro REQ
(identificado por los comentarios en el diff como **REQ-011**, no REQ-007: agrega
`test_tray_icon_activo_sin_ventana_mostrada_ca04` sobre el ícono de bandeja del
sistema, `QSystemTrayIcon`). Esto **no toca** `config_manager.py`,
`ui/widgets/weather_card.py` ni `ui/widgets/center_panel.py` — sin solapamiento directo
con el alcance de REQ-012.

Sí hay un solapamiento de **archivo** (no de contenido) a vigilar: REQ-011 ya agregó
tests al final de `tests/test_gui_widgets.py` sin commitear. Cuando `orion-dev` agregue
los tests de CA-03/CA-04/CA-06..CA-09 de REQ-012 al mismo archivo, ambos REQs tendrán
cambios simultáneos sin commit ahí — no es un bug de REQ-012, pero puede generar un
diff mezclado si se commitea antes de que REQ-011 cierre. Se registra como riesgo,
sin asumir que sea un fallo.

No se detectó nada anómalo en `core/`, `agents/` ni `ai/` (alcance de REQ-007) que
afecte a REQ-012.
