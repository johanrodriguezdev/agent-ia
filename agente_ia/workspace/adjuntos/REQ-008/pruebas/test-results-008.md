# Resultados de prueba REQ-008 — Rediseño GUI estilo "JARVIS" a pantalla completa

**Fecha:** 2026-08-05
**Agente:** orion-tester
**SPEC de referencia:** `workspace/adjuntos/REQ-008/spec/SPEC-008.md` (CA-01 a CA-17)
**Metodología:** cada criterio se verificó leyendo directamente el código fuente real
(`ui/gui.py`, `ui/widgets/*.py`, `ui/gui_workers.py`, `system_actions/system_info.py`,
`ai/memory_manager.py`, `agents/action_registry.py`, `core/security_manager.py`,
`ui/personality.py`, `config_manager.py`, `os_integration/weather_data.py`), no solo el
resumen de `desarrollo-log-008.md`.

## Compilación

`python -m py_compile` sobre los 19 archivos relevantes (los 11 previstos por
arquitectura-008.md + `ui/gui_workers.py` + los 8 widgets de `ui/widgets/`): **OK**, sin
errores.

## Tests existentes

- Pasados: **175/175** (0 fallos), ejecución independiente confirmada.
- Baseline (`origen/baseline-008.md`): 123 passed, 0 failed.
- Nuevos fallos: **ninguno**. Diferencia de 52 tests nuevos (todos pasan), consistente
  con lo reportado por `orion-dev`.
- Archivos de test nuevos verificados: `test_system_info_numeric.py` (7),
  `test_weather_data.py` (4), `test_memory_manager_recent.py` (6),
  `test_action_registry_spotify.py` (5), `test_personality_greeting.py` (12),
  `test_config_manager_display_name.py` (4), `test_gui_workers.py` (4),
  `test_gui_widgets.py` (9), + 1 caso agregado a `test_security_manager.py`.
- Se revisó el contenido real de varios de estos archivos (no solo su resultado en
  verde): las aserciones son específicas y no triviales (verifican texto exacto,
  orden por recencia, filtrado por categoría/usuario, llamada exacta a
  `execute_action`/`run_async` con los argumentos correctos, degradación explícita en
  fallos). Sin `assert True` ni tests vacíos.

## Criterios de la SPEC

| Criterio | Resultado | Nota |
|----------|-----------|------|
| CA-01 | PASS | `JarvisMainWindow(QMainWindow)` sin `FramelessWindowHint`; `main.py` llama `showMaximized()` (nunca `showFullScreen()` — no es kiosco). Barra de título nativa del SO con min/max/cerrar. |
| CA-02 | PASS | `JarvisMainWindow._init_ui()` arma `QHBoxLayout(Sidebar, center_column, RightPanel)`. `Sidebar.setFixedWidth(250)`, `RightPanel.setFixedWidth(350)` — coinciden con las medidas del mockup. Panel derecho contiene las 4 tarjetas (`SystemStatusCard`, `QuickActionsCard`, `RecentActivityCard`, `WeatherCard`) dentro de un `QScrollArea`. |
| CA-03 | PASS | `ui/personality.py:get_time_based_greeting()` — rangos verificados línea por línea: `hour>=19 or hour<5` → "Buenas noches" (evaluado primero, resuelve el envolvimiento de medianoche correctamente), `hour<12` → "Buenos días" (cubre 05:00–11:59, ya que 00:00–04:59 quedó cubierto arriba), resto → "Buenas tardes" (12:00–18:59). Coincide exactamente con los tres rangos de CA-03. Tests parametrizados con horas límite (19, 22, 0, 4 / 5, 8, 11 / 12, 15, 18) — todos pasan. |
| CA-04 | PASS | Cadena de resolución en `CenterPanel._resolve_display_name()`: `config_manager.get_display_name()` → `os.environ.get("USERNAME", "")` → cadena vacía. `grep -i "Johan"` sobre `ui/` y `config_manager.py` → **sin resultados**, confirmado que no está hardcodeado en ningún punto. |
| CA-05 | PASS | `Sidebar._NAV_ITEMS`: 7 ítems, solo `"inicio"` con `enabled=True`; los demás con `setEnabled(False)`, sin `clicked.connect()`. Test `test_sidebar_inicio_emits_nav_selected` confirma 1 botón habilitado / 6 deshabilitados, y que solo "Inicio" emite la señal. |
| CA-06 | PASS | `system_actions/system_info.py`: `get_cpu_percent()`/`get_ram_percent()`/`get_disk_percent()`/`get_network_io_counters()`, todas reales vía `psutil`/`shutil`, ninguna con valores fijos de ejemplo. `SystemStatusCard` las refresca con `QTimer(2000ms)` directo en el hilo de la GUI — justificado en arquitectura-008.md por ser syscalls locales no bloqueantes (`interval=None`); no hay ninguna llamada de red aquí. Degrada a `0.0`/`(0,0)` si `psutil` falla (verificado con tests). |
| CA-07 | PASS | `QuickActionsCard._run_action()` llama **exclusivamente** `run_async(execute_action, ..., channel=ChannelType.DESKTOP, user_id="default")` — nunca importa ni llama las funciones subyacentes (`open_notepad`, etc.) directo. Test confirma que el primer argumento pasado a `run_async` es la función `execute_action` real (identidad de objeto, `is`), no un mock separado. |
| CA-08 | PASS | `agents/action_registry.py:open_spotify()` prueba 3 rutas conocidas de instalación; si ninguna existe, hace `webbrowser.open("https://open.spotify.com")`. Sin login ni control de reproducción. Tests cubren: ruta instalada, fallback a navegador, excepción manejada sin crash (con `logger.error`, no `except: pass`). |
| CA-09 | PASS | `UnifiedMemory.get_recent(user_id, limit=4, category="interaction")` — `ORDER BY timestamp DESC LIMIT N`, filtra por `category="interaction"` (evita duplicar la copia `"semantic"` del mismo turno) y por `archived=0`. `RecentActivityCard.set_items([])` muestra `"Sin actividad reciente todavía."` explícito, nunca una lista en blanco silenciosa ni datos inventados. Tests cubren orden, límite, filtro por categoría, filtro por usuario, exclusión de archivados y estado vacío. |
| CA-10 | PASS | `os_integration/weather_data.py:get_weather_structured()` consulta `wttr.in/{city}?format=j1&lang=es` real (JSON, 5s timeout), retorna `WeatherData(temp_c, condition, city, time_str, date_str)` o `None` explícito en cualquier fallo — nunca inventa valores de ejemplo como "24°C"/"Bogotá, CO". `WeatherCard.set_data(None)` muestra "Clima no disponible." explícito. |
| CA-11 | PASS | `VoiceOrb` porta el `paintEvent` (anillos + núcleo + pulso) del `JarvisGUI` original, con paleta de color/velocidad de pulso por estado (`_STATE_COLORS`, dict de 4 entradas IDLE/LISTENING/PROCESSING/RESPONDING). Sin ningún análisis de amplitud/volumen de audio real — animación puramente dirigida por estado, tal como aprobó P4. |
| CA-12 | PASS | `CenterPanel.command_submitted` → `JarvisMainWindow._handle_command()` → `run_async(resolve, ..., ChannelType.DESKTOP, user_id="default")` con `from core.resolution import resolve` — mismo pipeline que usa `ui/cli.py`. Respuesta mostrada vía `CenterPanel.show_response()`; `memory.store(..., category="interaction")` se ejecuta también, dando paridad con el flujo CLI/voz. |
| CA-13 | PASS | `JarvisMainWindow.closeEvent()`: `event.ignore()` + `self.hide()` + notificación de bandeja — idéntico al comportamiento documentado del `JarvisGUI` anterior en el baseline. Solo el ítem "Salir" del menú de bandeja llama `QApplication.instance().quit`. Test `test_jarvis_main_window_close_hides_without_quitting_app` confirma `isVisible() is False` y que `QApplication.instance()` sigue vivo tras `close()`. |
| CA-14 | PASS | `main.py` construye `QApplication`/`JarvisMainWindow` en el hilo principal, dentro del mismo bloque `if not headless:` de siempre; `jarvis_runner` (lógica del asistente) sigue en `threading.Thread(daemon=True)`. `ui/gui_workers.py:CallableWorker.run()` ejecuta únicamente funciones Python puras (`fn(*args, **kwargs)`), nunca instancia ni toca un `QWidget` — confirmado leyendo el archivo completo. `WorkerSignals`/`CallableWorker` se construyen siempre desde el hilo de la GUI (invocados desde slots conectados a botones o desde `__init__` de widgets), preservando la afinidad de hilo necesaria para que Qt encole los callbacks correctamente. |
| CA-15 | PASS | Bloque `--headless` de `main.py` no fue tocado: sigue sin construir ningún objeto Qt y usa `jarvis_mind.join()` igual que antes del REQ. |
| CA-16 | PASS | Las 6 acciones de "Accesos rápidos" son GREEN. `core/security_manager.py:_register_action_registry_actions()` línea 362 tiene `"open_spotify"` agregado a `green_actions`. Test dedicado `test_green_actions_regression_free[open_spotify]` confirma `require_confirmation("open_spotify", "telegram")` retorna `True` **sin** invocar `input()` (falla la aserción si se llama) — reproduce exactamente el escenario de riesgo señalado por `orion-baseline`: sin este registro, el gate fail-closed de REQ-005 bloquearía la acción pese a estar en `ACTION_REGISTRY`. Verificado que **ambos** registros existen (`ACTION_REGISTRY` en `agents/action_registry.py` Y `green_actions` en `core/security_manager.py`) — no es solo el reporte de `orion-dev`, se confirmó leyendo ambos archivos línea por línea. |
| CA-17 | PASS | `python -m py_compile` limpio (ver arriba). `python -m pytest tests/` → 175 passed, 0 failed, sin regresiones frente al baseline de 123 passed / 0 failed. |

**Resultado: 17/17 criterios PASS.**

## Verificaciones adicionales solicitadas

### (a) Hallazgo del baseline — `open_spotify` en `security_manager.py::green_actions`
Confirmado de forma independiente, no solo repetido de `desarrollo-log-008.md`:
- `agents/action_registry.py:245` — entrada `"open_spotify"` en `ACTION_REGISTRY`.
- `core/security_manager.py:362` — `"open_spotify"` agregado a la lista `green_actions`
  dentro de `_register_action_registry_actions()`.
- Test `tests/test_security_manager.py::test_green_actions_regression_free[open_spotify]`
  ejercita el punto de entrada real (`security_manager.require_confirmation()`) y falla
  explícitamente si se llama `input()` — es decir, si alguien quitara la línea 362, este
  test fallaría (el gate volvería a bloquear la acción vía fail-closed). Verificación
  lógica: sin el registro en `green_actions`, `require_confirmation()` no encontraría el
  nombre clasificado y el sistema fail-closed (REQ-005) bloquearía por defecto — el
  comportamiento esperado se confirma tanto por lectura de código como por el test.

### (b) Restricción de hilo
Confirmado por lectura completa de `main.py`, `ui/gui.py` y `ui/gui_workers.py`:
- La construcción de `QApplication`/`JarvisMainWindow` ocurre exclusivamente en el hilo
  principal (bloque `if not headless:` de `main.py`, sin cambios de esa restricción).
- La lógica del asistente (`main()`) corre en `threading.Thread(daemon=True)`, separado.
- `ui/gui_workers.py:CallableWorker.run()` — leído completo — ejecuta únicamente
  `fn(*args, **kwargs)` (funciones Python puras: `execute_action`, `resolve`,
  `get_weather_structured`), sin ninguna instanciación de `QWidget` ni acceso a estado de
  UI desde dentro de `run()`.
- El bridge de estado continuo (`GLOBAL_STATE`/`update_gui_state()`) no cambió de
  mecanismo — sigue siendo polling de 100 ms desde el hilo de la GUI, tal como antes.
- No se encontró ningún punto donde un widget Qt se construya o mute fuera del hilo
  principal.

### (c) Bugs preexistentes corregidos durante el desarrollo
Ambos verificados como reales y como correcciones mínimas, sin efectos secundarios fuera
de lo pedido por la SPEC:

1. **`config_manager.py:load_config()`** — antes devolvía `DEFAULT_CONFIG` (el dict
   global) por referencia en sus dos ramas de "archivo no existe"/"archivo corrupto".
   Confirmado en el código actual: ambas ramas ahora hacen `return dict(DEFAULT_CONFIG)`
   (copia). Sin este fix, `set_display_name()` en un primer arranque (config.json
   inexistente) habría mutado el diccionario global compartido por el resto del proceso
   — bug real, corrección de una línea x2, estrictamente defensiva. Cubierto por
   `test_load_config_backfills_display_name_for_old_config` y los demás tests de
   `test_config_manager_display_name.py`.
2. **`os_integration/weather_data.py`** — la resolución de `areaName`/`region`/`country`
   ahora usa `.get("value", "")` en vez de indexar `["value"]` directo, evitando un
   `KeyError` si wttr.in devuelve un área con forma inesperada (presente pero sin la
   clave `"value"`). Confirmado en el código actual. El test
   `test_get_weather_structured_never_fabricates_default_city` cubre el caso de área
   vacía (`"nearest_area": [{}]`) y confirma que degrada a `"Ubicación desconocida"` sin
   excepción — aunque no reproduce el caso exacto más estrecho del bug original (un área
   presente con una clave distinta a `"value"`, p. ej. `{"areaName": [{"otro": "x"}]}`),
   el código con `.get()` cubre ambos casos por construcción. **Observación menor, no
   bloqueante:** un test que reprodujera el caso exacto (`areaName` presente pero sin
   `"value"`) habría sido una prueba más directa del defecto corregido; no se considera
   motivo de FAIL porque el comportamiento del código sí es correcto y está cubierto
   indirectamente.

Ninguna de las dos correcciones altera comportamiento aprobado en `arquitectura-008.md`
ni introduce alcance no pedido por SPEC-008.

## Regresión

| Área revisada | Resultado |
|----------------|-----------|
| Suite completa pytest (175 tests) | PASS — sin fallos nuevos vs. baseline de 123 |
| `ui/cli.py` (fuera de alcance, no debía tocarse) | Sin cambios — confirmado no modificado |
| `skills/weather_skill.py` (skill conversacional, debía quedar intacta) | Sin cambios — confirmado no modificado, sigue usando `format=3` |
| Modo `--headless` (`main.py`) | Sin cambios de comportamiento — bloque intacto |
| `security_manager.py` — clasificaciones RED/YELLOW existentes | Sin alteración — solo se agregó `"open_spotify"` a GREEN; los 10 tests de categorías RED y los de YELLOW siguen en verde |
| `except: pass` silencioso en código nuevo/modificado | No encontrado (`grep` sin resultados) |
| API keys/tokens hardcodeados en código nuevo/modificado | No encontrado |
| String `"Johan"` hardcodeado | No encontrado (`grep -i` sin resultados en `ui/` y `config_manager.py`) |

## Veredicto: PASS

17/17 criterios de aceptación de SPEC-008 verificados PASS contra el código real (no solo
contra el resumen de `orion-dev`). Compilación limpia. 175/175 tests pasan, sin
regresiones frente al baseline de 123/0. Los dos hallazgos críticos señalados por
`orion-baseline`/`orion-architect` (doble registro de `open_spotify`, restricción de
hilo) están correctamente resueltos y verificados de forma independiente. Los dos bugs
preexistentes corregidos son reales, mínimos y no introducen efectos secundarios fuera de
alcance. Handoff a `orion-qa`.
