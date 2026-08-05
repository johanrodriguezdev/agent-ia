# Desarrollo REQ-008

Rediseño completo de la GUI de escritorio de O.R.I.O.N.: de HUD flotante 400x400
(`JarvisGUI(QWidget)`) a panel de control "JARVIS" maximizado con barra de título nativa
(`JarvisMainWindow(QMainWindow)`), sidebar de navegación, saludo dinámico, visualizador
de voz central, barra de comando, y panel derecho con estado del sistema / accesos
rápidos / actividad reciente / clima.

Implementado exactamente lo aprobado en `arquitectura-008.md`, salvo dos desviaciones
menores documentadas más abajo.

## Archivos modificados

- `system_actions/system_info.py` — 4 funciones numéricas nuevas no bloqueantes
  (`get_cpu_percent()`, `get_ram_percent()`, `get_disk_percent()`,
  `get_network_io_counters()`), cada una degrada a `0.0`/`(0, 0)` si psutil falla o no
  está disponible, con `logger.error()` — nunca `except: pass` silencioso.
- `ai/memory_manager.py` — nuevo método `UnifiedMemory.get_recent(user_id, limit,
  category="interaction")`: últimas interacciones reales por recencia, sin filtro de
  query ni umbral de importancia (a diferencia de `search_semantic()`).
- `agents/action_registry.py` — nueva función `open_spotify()` (busca el `.exe` en 3
  rutas conocidas; si no existe, abre `open.spotify.com` en el navegador) + entrada
  `"open_spotify"` en `ACTION_REGISTRY` (categoría `"app"`).
- `core/security_manager.py` — **hallazgo del baseline resuelto**: `"open_spotify"`
  agregado a la lista de `green_actions` dentro de `_register_action_registry_actions()`.
  Sin esto, el gate fail-closed (REQ-005) bloqueaba la acción pese a estar en
  `ACTION_REGISTRY` — verificado con
  `tests/test_security_manager.py::test_green_actions_regression_free[open_spotify]`.
- `ui/personality.py` — nueva función `get_time_based_greeting(display_name="")`:
  19:00-04:59 "Buenas noches" (evaluado primero por envolver medianoche), 05:00-11:59
  "Buenos días", 12:00-18:59 "Buenas tardes"; con coma + nombre si `display_name` no es
  vacío.
- `config_manager.py` — `DEFAULT_CONFIG["display_name"] = ""`; `load_config()` rellena
  `display_name` en configuraciones viejas que no lo tienen; nuevas
  `get_display_name()`/`set_display_name(name)`. **Bug encontrado y corregido durante
  testing**: `load_config()` retornaba el objeto `DEFAULT_CONFIG` global por referencia
  en sus dos ramas de "archivo no existe / corrupto", así que cualquier mutación del
  dict devuelto (p. ej. `set_display_name()` en el primer arranque) corrompía el default
  compartido por el resto del proceso. Corregido a `return dict(DEFAULT_CONFIG)` en
  ambas ramas — ver sección "Decisiones de implementación".
- `ui/gui.py` — reescritura completa: `JarvisGUI(QWidget)` reemplazado por
  `JarvisMainWindow(QMainWindow)`. Mantiene `GLOBAL_STATE`/`update_gui_state()` a nivel
  de módulo sin cambios de firma ni de import path. Ensambla `Sidebar`/`HeaderBar`/
  `CenterPanel`/`RightPanel`, hace polling de `GLOBAL_STATE` cada 100 ms (propaga a
  `CenterPanel.set_state()`/`HeaderBar.set_state()`), resuelve la barra de comando vía
  `run_async(resolve, ...)`, y porta `closeEvent()`/`QSystemTrayIcon` sin cambios de
  comportamiento respecto al `JarvisGUI` anterior.
- `main.py` — bloque de construcción de GUI (dentro de `if not headless:`): import y
  clase cambiados a `JarvisMainWindow`, `window.show()` → `window.showMaximized()`. El
  bloque `--headless` y el `try/except` que degrada a headless si la GUI falla no se
  tocaron.
- `requirements.txt` — agregado `pytest-qt` bajo una sección nueva "Testing (REQ-008)".
- `tests/conftest.py` — agregado `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`
  antes de cualquier import de PyQt6, para que toda la suite (no solo los tests de GUI)
  corra sin necesitar un servidor gráfico real.
- `tests/test_security_manager.py` — extendido el test parametrizado de regresión GREEN
  (`test_green_actions_regression_free`) con `"open_spotify"`.

## Archivos creados

- `os_integration/weather_data.py` — `WeatherData` (dataclass) + `get_weather_structured(city="")`:
  consulta `wttr.in/{city}?format=j1&lang=es` (JSON, 5s timeout), retorna `None` en
  cualquier fallo de red o forma inesperada del JSON (nunca inventa datos). **Bug
  encontrado y corregido durante testing**: la resolución de `areaName`/`region`/
  `country` indexaba `[0]["value"]` sin manejar el caso de un área presente pero con
  forma inesperada (sin la clave `"value"`), lanzando `KeyError` en vez de degradar a
  `"Ubicación desconocida"` como pretendía el resto de la lógica. Corregido a
  `.get("value", "")` con valores por defecto seguros — ver "Decisiones de
  implementación".
- `ui/gui_workers.py` — `WorkerSignals(QObject)` (`finished`/`error`), `CallableWorker(QRunnable)`,
  y `run_async(fn, on_done=None, on_error=None, *args, **kwargs)` sobre
  `QThreadPool.globalInstance()`. Usado para toda I/O de red/subprocess/`resolve()`
  disparada desde un slot de la GUI — nunca se llama esa I/O directo en el hilo principal.
- `ui/widgets/__init__.py` — vacío, sin lógica.
- `ui/widgets/sidebar.py` — `Sidebar(QFrame)`: logo + nombre de agente
  (`config_manager.get_agent_name()`), 7 botones de navegación (solo "Inicio"
  habilitado, emite `nav_selected(str)`), indicador "Sistema activo".
- `ui/widgets/header_bar.py` — `HeaderBar(QFrame)`: píldora de modo activo (refleja los
  4 estados existentes) + icono de notificación decorativo. `set_state(str)`.
- `ui/widgets/voice_orb.py` — `VoiceOrb(QWidget)`: versión reducida (~220x220px) del
  `paintEvent` de anillos/pulso/núcleo del `JarvisGUI` original, sin la rejilla
  hexagonal ni la línea de escaneo de ventana completa. `set_state(str)`.
- `ui/widgets/center_panel.py` — `CenterPanel(QFrame)`: saludo dinámico (cadena de
  resolución de nombre: config → `os.environ["USERNAME"]` → sin nombre), subtítulo,
  `VoiceOrb`, texto de estado, barra de comando (`QLineEdit` + botón). Señal
  `command_submitted(str)`; método `show_response(text)`.
- `ui/widgets/right_panel.py` — `RightPanel(QFrame)`: ensambla las 4 tarjetas dentro de
  un `QScrollArea`.
- `ui/widgets/system_status_card.py` — `CircularProgress(QWidget)` (arco pintado a mano)
  + `SystemStatusCard(QFrame)`: `QTimer` propio de 2000ms llamando directo a
  `system_info` (syscalls locales, no red). `set_values(cpu, ram, disk, net)`.
- `ui/widgets/quick_actions_card.py` — `QuickActionsCard(QFrame)`: grid 2x3 de botones
  mapeados a `open_explorer`/`open_browser`/`open_notepad`/`open_calculator`/
  `take_screenshot`/`open_spotify`, todos vía `run_async(execute_action, ...,
  channel=ChannelType.DESKTOP)`.
- `ui/widgets/recent_activity_card.py` — `RecentActivityCard(QFrame)`:
  `set_items(list[MemoryItem])`, estado vacío explícito.
- `ui/widgets/weather_card.py` — `WeatherCard(QFrame)`: `set_data(Optional[WeatherData])`,
  estado "no disponible" explícito en `None`.

## Tests creados/extendidos

- `tests/test_system_info_numeric.py` (7 tests)
- `tests/test_weather_data.py` (4 tests)
- `tests/test_memory_manager_recent.py` (6 tests)
- `tests/test_action_registry_spotify.py` (5 tests)
- `tests/test_personality_greeting.py` (6 tests)
- `tests/test_config_manager_display_name.py` (4 tests)
- `tests/test_gui_workers.py` (4 tests, `pytest-qt`)
- `tests/test_gui_widgets.py` (9 tests, `pytest-qt`) — cubre CA-03, CA-04, CA-05, CA-06,
  CA-07, CA-09, CA-10, CA-13
- `tests/test_security_manager.py` — 1 caso agregado al test parametrizado existente
  (`"open_spotify"`)

Total: 123 tests baseline + 52 nuevos = **175 tests, 0 fallos** (`python -m pytest
tests/ --tb=short -q`). Sin regresiones respecto a `baseline-008.md`.

## Dependencias agregadas

- `requirements.txt` — `pytest-qt` (instalado: `pytest-qt-4.5.0`). Solo para testing;
  no se agrega ninguna dependencia de producción nueva.

## Decisiones de implementación

1. **`_make_card_frame()` no implementado como helper compartido** (mencionado en
   arquitectura-008.md para `right_panel.py`). En su lugar, cada tarjeta
   (`SystemStatusCard`, `QuickActionsCard`, `RecentActivityCard`, `WeatherCard`) se
   auto-estiliza (`setObjectName("Card")` + QSS propio con el mismo selector `#Card`).
   Motivo: mantiene cada tarjeta 100% autocontenida y testeable de forma aislada sin
   levantar `RightPanel`, tal como pide la sección "Pruebas sugeridas" de la propia
   arquitectura (p. ej. `SystemStatusCard().set_values(18, 42, 31, 12)` sin
   dependencias). Un helper externo habría sido una capa de envoltura redundante sobre
   tarjetas que ya son `QFrame` completos.
2. **Fórmula de "% de Red" en `SystemStatusCard`** no estaba definida en
   arquitectura-008.md más allá de "datos reales de psutil". Se implementó como
   actividad relativa: bytes transferidos desde la última lectura de
   `get_network_io_counters()`, escalados linealmente (200 KB entre lecturas de 2s →
   100%). Documentado en el docstring de `_net_percent()`.
3. **Bug corregido en `config_manager.load_config()`** (no relacionado con una decisión
   de diseño, sino un defecto real destapado por `tests/test_config_manager_display_name.py`):
   devolvía `DEFAULT_CONFIG` por referencia en vez de una copia en sus dos ramas de
   "no existe archivo"/"archivo corrupto", permitiendo que un caller mutara el default
   global compartido. Corregido a `dict(DEFAULT_CONFIG)`. Cambio de una línea x2,
   estrictamente defensivo, sin alterar ningún comportamiento aprobado.
4. **Bug corregido en `os_integration/weather_data.py`** (mismo tipo de hallazgo, vía
   `tests/test_weather_data.py::test_get_weather_structured_never_fabricates_default_city`):
   la resolución de ciudad/región/país indexaba `[0]["value"]` sin usar `.get()`,
   lanzando `KeyError` en vez de degradar a `"Ubicación desconocida"` cuando wttr.in
   devuelve un área con forma inesperada. Corregido a `.get("value", "")` con
   listas/dicts por defecto seguros — el comportamiento pretendido original (degradar,
   no fallar) ahora sí se cumple.
5. **`nav_selected("inicio")` no dispara ninguna acción en `JarvisMainWindow`**: "Inicio"
   es la única vista existente en este REQ, así que seleccionarla no requiere ningún
   cambio de estado (ya es la vista mostrada). Los otros 6 ítems del sidebar están
   deshabilitados (CA-05), sin handler.

## Compilación y regresión

```
python -m py_compile <27 archivos tocados/creados>   → OK, sin errores
python -m pytest tests/ --tb=short -q                → 175 passed, 0 failed
```

## Estado

- `open_spotify` verificado en ambos puntos de registro (`ACTION_REGISTRY` +
  `security_manager.green_actions`) — hallazgo del baseline resuelto y cubierto por
  test.
- Ningún `except: pass` silencioso introducido. Ningún `print()` de debug. Ninguna API
  key/token hardcodeado.
- No se ejecutó `git commit`, `git add` ni `git push`. No se creó ninguna rama.
