# Arquitectura REQ-008 — Rediseño GUI estilo "JARVIS" a pantalla completa

**Fecha:** 2026-08-04
**Agente:** orion-architect
**SPEC de referencia:** `workspace/adjuntos/REQ-008/spec/SPEC-008.md` (CA-01 a CA-17)
**Baseline de referencia:** `workspace/adjuntos/REQ-008/origen/baseline-008.md`

## Decisión de fondo: ventana estándar del SO, no frameless

`ui/gui.py` actual usa `FramelessWindowHint` + arrastre manual con mouse porque no tiene
barra de título nativa. El mockup **sí** trae barra de título con min/max/cerrar, y CA-01
pide explícitamente "barra de título visible y controles minimizar/maximizar/cerrar
funcionales" en modo maximizado (no kiosco, según P2). En vez de reimplementar una barra de
título custom pintada a mano (riesgo, más código, más superficie de bugs), esta propuesta usa
`QMainWindow` **sin** `FramelessWindowHint`, con `showMaximized()` — la barra de título nativa
de Windows resuelve min/max/cerrar gratis, correctamente, y sin arrastre manual. Se elimina el
bloque `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent` de arrastre (ya no aplica, la
gestiona el SO). Este es un cambio de UX consciente respecto al HUD flotante actual — ver
Riesgos.

## Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| CA-01 | `ui/gui.py:JarvisMainWindow(QMainWindow)` + `main.py` llama `window.showMaximized()` (nunca `showFullScreen()`, que sería modo kiosco). Barra de título nativa del SO — min/max/cerrar funcionan sin código adicional. |
| CA-02 | `JarvisMainWindow` arma `QHBoxLayout(sidebar, center, right_panel)` sobre `QWidget` central, instanciando `Sidebar`, `CenterPanel`, `RightPanel` de `ui/widgets/`. |
| CA-03 | `ui/personality.py:get_time_based_greeting()` nueva, usa `datetime.now().hour`; `CenterPanel` la llama una sola vez en `__init__`. |
| CA-04 | `config_manager.py:get_display_name()/set_display_name()` nuevos (`DEFAULT_CONFIG["display_name"] = ""`). `CenterPanel` resuelve: config → `os.environ["USERNAME"]` (Windows) → sin nombre (saludo sin coma). Nunca "Johan" literal en código. |
| CA-05 | `ui/widgets/sidebar.py:Sidebar` — 7 `QPushButton` en `QVBoxLayout`; solo el de "Inicio" tiene `setEnabled(True)` y emite `pyqtSignal(str) nav_selected`; los otros 6 quedan `setEnabled(False)` (visibles, sin handler). |
| CA-06 | `system_actions/system_info.py` — 4 funciones numéricas nuevas no bloqueantes (`get_cpu_percent()` con `interval=None`, `get_ram_percent()`, `get_disk_percent()`, `get_network_io_counters()`). `SystemStatusCard` las refresca con `QTimer` cada 2000 ms, llamada directa en el hilo de la GUI (justificación: son syscalls locales rápidas, no I/O de red — ver "Por qué QTimer directo aquí y no QThreadPool"). |
| CA-07 | `ui/widgets/quick_actions_card.py:QuickActionsCard` — cada botón llama `run_async(execute_action, name=<accion>, channel=ChannelType.DESKTOP, user_id="default")`; nunca invoca la función subyacente (`open_notepad`, etc.) directamente. |
| CA-08 | `agents/action_registry.py:open_spotify()` nueva (busca rutas conocidas, si no existe hace `webbrowser.open("https://open.spotify.com")`) + entrada en `ACTION_REGISTRY`. **Y** `core/security_manager.py:_register_action_registry_actions()` — `"open_spotify"` agregado a `green_actions` (hallazgo de baseline, incorporado aquí explícitamente). |
| CA-09 | `ai/memory_manager.py:UnifiedMemory.get_recent(user_id, limit=4, category="interaction")` nuevo — `ORDER BY timestamp DESC`, sin filtro de importancia. `RecentActivityCard` muestra estado vacío explícito si la lista es `[]`. |
| CA-10 | `os_integration/weather_data.py` (nuevo) — `get_weather_structured(city="") -> Optional[WeatherData]`, usa `wttr.in/...?format=j1&lang=es`. `WeatherCard` la consume vía `run_async()` (I/O de red, nunca en el hilo de la GUI). |
| CA-11 | `ui/widgets/voice_orb.py:VoiceOrb(QWidget)` — porta el `paintEvent` de anillos/pulso/núcleo del `JarvisGUI` actual (líneas 87-184 de `ui/gui.py` de hoy), alimentado por el mismo `GLOBAL_STATE` vía polling de 100 ms. Sin análisis de audio real (aprobado en P4). |
| CA-12 | `CenterPanel` — `QLineEdit` + botón enviar; `returnPressed`/`clicked` → señal `command_submitted(str)` → `JarvisMainWindow._handle_command()` → `run_async(resolve, text, ChannelType.DESKTOP, user_id="default")` → al terminar, muestra la respuesta y llama `memory.store(...)` (paridad con el flujo de `main.py`/CLI). |
| CA-13 | `JarvisMainWindow.closeEvent()` — portado sin cambios de comportamiento del `JarvisGUI` actual (`event.ignore()` + `self.hide()` + notificación de bandeja); `QSystemTrayIcon` con menú "Mostrar/Ocultar"/"Salir" también portado igual. |
| CA-14 | `main.py` sigue construyendo la ventana en el hilo principal, dentro del mismo bloque `if not headless` (solo cambia la clase importada y `show()`→`showMaximized()`). Ningún `QWidget`/`QObject` con affinity de GUI se crea fuera del hilo principal: los workers de `QThreadPool` (`ui/gui_workers.py`) ejecutan funciones Python puras en `run()`, nunca instancian widgets. |
| CA-15 | Bloque `--headless` de `main.py` no se toca. El `try/except Exception` que degrada a headless si la GUI falla al construirse se mantiene igual, ahora envolviendo la construcción de `JarvisMainWindow`. |
| CA-16 | Los 6 accesos rápidos son GREEN (5 ya existentes + `open_spotify` agregado explícitamente). Cero acciones nuevas AMARILLO/ROJO. Ver sección "Evaluación de `orion-security`". |
| CA-17 | `python -m py_compile` sobre los 11 archivos tocados (los 9 previstos por baseline + `ui/widgets/*` + `ui/gui_workers.py` como nuevos). Suite pytest nueva descrita en "Pruebas sugeridas" — ningún archivo modificado queda sin al menos un test de su lógica no-Qt. |

## Módulos a modificar

- `ui/gui.py` — reemplazo completo de `JarvisGUI` por `JarvisMainWindow(QMainWindow)`. Mantiene
  `GLOBAL_STATE`/`update_gui_state()` a nivel de módulo (mismo nombre e import path — `main.py`
  no cambia su línea 154 `from ui.gui import update_gui_state`). Ensambla los widgets de
  `ui/widgets/`, gestiona el `QTimer` de polling (100 ms) y el `QSystemTrayIcon`.
- `main.py` — bloque `if not headless` (líneas ~189-197): `from ui.gui import QApplication,
  JarvisMainWindow`; `window.showMaximized()` en vez de `window.show()`. Sin cambios de
  hilos/estructura.
- `system_actions/system_info.py` — 4 funciones nuevas (numéricas, no bloqueantes), sin tocar
  las funciones de texto existentes.
- `skills/weather_skill.py` — **sin cambios** (se confirma que la skill conversacional
  `format=3` queda intacta, tal como exige SPEC-008).
- `ai/memory_manager.py` — método nuevo `get_recent()` en `UnifiedMemory`.
- `agents/action_registry.py` — función nueva `open_spotify()` + entrada en `ACTION_REGISTRY`.
  Se agrega `import logging; logger = logging.getLogger(__name__)` al tope del archivo (no
  existe hoy) para poder loguear el `except Exception` de `open_spotify()` sin `pass` silencioso,
  cumpliendo `python-style.md`.
- `core/security_manager.py` — una línea: `"open_spotify"` agregado a la lista `green_actions`
  dentro de `_register_action_registry_actions()` (línea ~360-364). Sin tocar ninguna otra
  clasificación existente.
- `ui/personality.py` — función nueva `get_time_based_greeting()`. `get_random_greeting()` y
  `format_response()` quedan intactas.
- `config_manager.py` — `DEFAULT_CONFIG["display_name"] = ""` + `get_display_name()` /
  `set_display_name()`, mismo patrón que `get_agent_name()`/`set_agent_name()`.

## Nuevas clases/funciones

### Paquete `ui/widgets/` (nuevo)
Justificado por `python-style.md` ("una clase principal por archivo") — el rediseño requiere
~8 clases nuevas con responsabilidades claramente separadas; meterlas todas en `ui/gui.py`
volvería el archivo inmanejable y no testeable por partes.

- `ui/widgets/__init__.py` — vacío, solo re-exports si hacen falta (sin lógica).
- `ui/widgets/sidebar.py`
  - `Sidebar(QFrame)` — logo + nombre de agente (`config_manager.get_agent_name()`), 7 botones
    de navegación (solo "Inicio" habilitado), indicador "Sistema activo". Señal
    `nav_selected(str)`.
- `ui/widgets/header_bar.py`
  - `HeaderBar(QFrame)` — píldora "Modo activo" (label de texto, sin lógica propia) + icono de
    notificación decorativo (sin handler, según Asumidos de SPEC-008). Método
    `set_state(state: str)` para reflejar los 4 estados.
- `ui/widgets/voice_orb.py`
  - `VoiceOrb(QWidget)` — versión reducida del `paintEvent` del `JarvisGUI` actual (anillo +
    núcleo + pulso, sin rejilla hexagonal de fondo completa ni línea de escaneo de ventana
    completa — se simplifican porque ahora el widget mide ~200x200px, no 400x400 de ventana
    entera). Método `set_state(state: str)` dispara `pulse_radius = 0.0` + `self.update()`.
- `ui/widgets/center_panel.py`
  - `CenterPanel(QFrame)` — saludo (`get_time_based_greeting()` + resolución de nombre),
    subtítulo, `VoiceOrb`, texto "Escuchando..."/estado, barra de comando (`QLineEdit` +
    `QPushButton`). Señal `command_submitted(str)`. Método `show_response(text: str)`.
- `ui/widgets/right_panel.py`
  - `RightPanel(QFrame)` — arma verticalmente las 4 tarjetas siguientes dentro de un
    `QVBoxLayout`, con `_make_card_frame(title: str) -> QFrame` como helper de estilo
    compartido (esquinas redondeadas, fondo más claro).
- `ui/widgets/system_status_card.py`
  - `CircularProgress(QWidget)` — anillo de progreso pintado a mano (`QPainter.drawArc`),
    método `set_percent(value: float)`.
  - `SystemStatusCard(QFrame)` — contiene `CircularProgress` + 4 filas (CPU/RAM/Disco/Red).
    `QTimer` propio (2000 ms) llama a `system_actions.system_info` directamente (ver
    justificación de no usar `QThreadPool` aquí). Método `set_values(cpu, ram, disk, net)`
    testeable sin timer.
- `ui/widgets/quick_actions_card.py`
  - `QuickActionsCard(QFrame)` — grid 2x3 de `QPushButton`, cada uno mapeado a un nombre de
    `ACTION_REGISTRY` (`open_explorer`, `open_browser`, `open_notepad`, `open_calculator`,
    `take_screenshot`, `open_spotify`). Todos pasan por `run_async(execute_action, ...)`.
- `ui/widgets/recent_activity_card.py`
  - `RecentActivityCard(QFrame)` — método `set_items(items: list[MemoryItem])`; si `items` está
    vacío, muestra un `QLabel` de estado vacío explícito ("Sin actividad reciente todavía.").
- `ui/widgets/weather_card.py`
  - `WeatherCard(QFrame)` — método `set_data(data: Optional[WeatherData])`; `None` → estado "no
    disponible" explícito (nunca deja los campos anteriores ni valores de ejemplo).

### `ui/gui_workers.py` (nuevo)
- `WorkerSignals(QObject)` — `finished = pyqtSignal(object)`, `error = pyqtSignal(str)`.
- `CallableWorker(QRunnable)` — ejecuta `fn(*args, **kwargs)` en un hilo del
  `QThreadPool.globalInstance()`; nunca crea/toca un `QWidget`.
- `run_async(fn, on_done=None, on_error=None, *args, **kwargs) -> CallableWorker` — helper de
  conveniencia usado por `WeatherCard`, `QuickActionsCard` y `CenterPanel`.

### Funciones nuevas en módulos existentes
- `system_actions/system_info.py`:
  - `get_cpu_percent() -> float` — `psutil.cpu_percent(interval=None)` (no bloqueante).
  - `get_ram_percent() -> float` — `psutil.virtual_memory().percent`.
  - `get_disk_percent(drive: str = "C:\\") -> float` — `shutil.disk_usage`.
  - `get_network_io_counters() -> tuple[int, int]` — bytes enviados/recibidos acumulados
    (contador crudo de `psutil.net_io_counters()`); el cálculo de porcentaje/delta entre dos
    lecturas vive en `SystemStatusCard` (mantiene `system_info.py` puro y testeable sin estado
    oculto entre llamadas).
- `os_integration/weather_data.py` (nuevo archivo):
  - `@dataclass WeatherData` — `temp_c: float`, `condition: str`, `city: str`, `time_str: str`,
    `date_str: str`.
  - `get_weather_structured(city: str = "") -> Optional[WeatherData]` — consulta
    `wttr.in/{city}?format=j1&lang=es` (timeout 5s, mismo patrón try/except que
    `weather_skill.py`); `time_str`/`date_str` se calculan localmente con `datetime.now()` (no
    dependen de que wttr.in los incluya). Retorna `None` si falla — nunca inventa datos.
- `ai/memory_manager.py`:
  - `UnifiedMemory.get_recent(self, user_id="default", limit=4, category="interaction") ->
    List[MemoryItem]` — filtra por `category="interaction"` por defecto para no duplicar la
    copia `"semantic"` que `main.py` guarda del mismo turno (línea 166-172 de `main.py`).
- `agents/action_registry.py`:
  - `open_spotify() -> str` — busca `%APPDATA%\Spotify\Spotify.exe`,
    `C:\Program Files\Spotify\Spotify.exe`, `C:\Program Files (x86)\Spotify\Spotify.exe`; si
    ninguna existe, `webbrowser.open("https://open.spotify.com")`.
- `ui/personality.py`:
  - `get_time_based_greeting(display_name: str = "") -> str`.
- `config_manager.py`:
  - `get_display_name() -> str`, `set_display_name(name: str)`.

## Flujo de datos

1. **Arranque:** `main.py` (hilo principal) construye `QApplication` + `JarvisMainWindow()` →
   `showMaximized()`. `JarvisMainWindow.__init__` arma `Sidebar`/`HeaderBar`/`CenterPanel`/
   `RightPanel`, inicia el `QTimer` de polling de `GLOBAL_STATE` (100 ms, sin cambios respecto a
   hoy) y el `QTimer` propio de `SystemStatusCard` (2000 ms). En paralelo, `threading.Thread`
   daemon (`jarvis_runner`) arranca `main()` (loop CLI/voz) — sin cambios.
2. **Estado de voz (IDLE/LISTENING/PROCESSING/RESPONDING):** hilo trabajador →
   `update_gui_state()` (variable global) → `QTimer` de 100 ms en `JarvisMainWindow` → propaga a
   `VoiceOrb.set_state()` y `HeaderBar.set_state()`. Mecanismo sin cambios (ver justificación
   abajo).
3. **Tarjeta "Estado del sistema":** `QTimer` propio de `SystemStatusCard` (hilo GUI) llama
   directo a `system_info.get_cpu_percent()/get_ram_percent()/get_disk_percent()/
   get_network_io_counters()` → `set_values()` actualiza `CircularProgress` + las 4 filas.
4. **Tarjeta "Accesos rápidos":** click de botón → `run_async(execute_action, name=..., 
   channel=ChannelType.DESKTOP)` (hilo del `QThreadPool`) → `execute_action()` →
   `security_manager.require_confirmation()` (GREEN → `True` inmediato, sin UI de
   confirmación) → función real (`open_notepad`, `open_spotify`, etc.) → resultado vuelve por
   `WorkerSignals.finished` (queued connection segura hacia el hilo GUI) → callback en el
   widget muestra el resultado.
5. **Tarjeta "Actividad reciente":** se puebla una vez en `__init__` de `RightPanel` (llamada
   directa a `memory.get_recent()`, es una consulta SQLite local rápida, no requiere
   `QThreadPool`) — se puede refrescar en el mismo ciclo que `SystemStatusCard` si se decide en
   desarrollo, sin cambio de arquitectura.
6. **Tarjeta "Clima":** al construirse `WeatherCard`, dispara `run_async(get_weather_structured)`
   (I/O de red real, siempre vía `QThreadPool`) → `finished` → `set_data(WeatherData)`; `error` →
   `set_data(None)` (estado "no disponible").
7. **Barra de comando:** usuario escribe texto → `CenterPanel.command_submitted` →
   `JarvisMainWindow._handle_command(text)` → `run_async(resolve, text, ChannelType.DESKTOP,
   user_id="default")` (hilo del pool; `resolve()` puede tardar — llamadas a Claude, red, etc.,
   nunca debe correr en el hilo GUI) → al terminar: `memory.store(f"{text} | {result.text}",
   category="interaction")` (dentro del mismo worker, no bloquea GUI) → `finished` →
   `CenterPanel.show_response(result.text)`.
8. **Cierre de ventana:** botón "×" → `closeEvent()` → `event.ignore()` + `hide()` + notificación
   de bandeja (idéntico a hoy). Solo "Salir" del menú de bandeja llama
   `QApplication.instance().quit()`.

## Por qué mantener el polling de 100 ms para `GLOBAL_STATE` (y no usar señales Qt ahí)

Se evaluó explícitamente reemplazar `GLOBAL_STATE` + polling por señales Qt cross-thread
(`pyqtSignal` emitida desde `jarvis_runner`). Se descarta para este REQ:
- `main.py:154-157` ya importa `update_gui_state` como función de módulo simple, sin ninguna
  referencia a un objeto Qt — introducir señales ahí obligaría a que el hilo trabajador
  conociera una instancia de `QObject` de la GUI (acoplamiento nuevo, mayor superficie de
  cambio en un archivo (`main.py`) que SPEC-008 quiere tocar lo mínimo posible).
  El wrapping actual (`try/except Exception` que solo hace `logger.debug` si la GUI no está
  disponible) depende de que `update_gui_state` sea una función de módulo tolerante a que la
  GUI no exista (modo headless) — una señal Qt real fallaría de forma distinta si no hay
  `QApplication`.
- Es un patrón de alta frecuencia pero de bajo costo (una comparación de string cada 100 ms) ya
  probado en producción sin incidentes reportados. Cambiarlo agrega riesgo sin beneficio medible
  para este REQ, que es de UI, no de arquitectura de concurrencia.
- **Sí se introduce** el patrón de señales Qt (`QThreadPool`/`QRunnable`/`pyqtSignal`) para las
  necesidades **nuevas** de este REQ que son I/O real de un solo disparo (clima, accesos
  rápidos, barra de comando) — ahí sí es el patrón idiomático correcto de Qt (ver
  `ui/gui_workers.py` arriba), porque son operaciones puntuales disparadas por eventos de UI,
  no un flujo continuo de estado desde un hilo persistente.
- Regla de seguridad del patrón nuevo: los callbacks `on_done`/`on_error` pasados a `run_async()`
  deben ser siempre métodos vinculados (`bound methods`) de un widget/`QObject` que vive en el
  hilo de la GUI — nunca funciones sueltas de módulo ni `lambda` que mute un widget desde fuera.
  Esto es lo que garantiza que Qt encole la ejecución del callback en el hilo correcto
  (conexión "Auto" se resuelve a "Queued" cuando el receptor es un `QObject` de otro hilo).
  `orion-qa` debe verificar este punto en cada uso de `run_async()`.

## Resolución de `display_name` (CA-04)

Cadena de resolución en `CenterPanel.__init__` (no en `config_manager.py`, que se mantiene
como acceso de configuración puro y testeable sin política de UI):
1. `config_manager.get_display_name()` — si no es `""`, se usa tal cual.
2. Si está vacío: `os.environ.get("USERNAME", "")` (mismo patrón ya usado por
   `system_actions/system_info.py:get_windows_username()`).
3. Si ambos están vacíos: el saludo se muestra sin nombre (`"Buenos días"` en vez de
   `"Buenos días, "`) — `get_time_based_greeting()` ya maneja `display_name=""` así.
Ningún punto del código tiene el string `"Johan"` hardcodeado.

## Resolución del anillo "100%" de "Estado del sistema" (decisión a confirmar por el humano)

SPEC-008/CA-06 no define qué número exacto va en el centro del anillo grande (el mockup muestra
un "100%" estático junto a métricas individuales bajas — CPU 18%, RAM 42%, etc. — por lo que no
puede ser "% de uso" literal). Esta propuesta decide: el anillo muestra
`100 - promedio(cpu%, ram%, disk%)`, redondeado y saturado a `[0, 100]`, con la etiqueta "Salud
del sistema" — un valor real (nunca fijo) derivado de los mismos datos de `psutil`, consistente
con el espíritu "todo funcionando correctamente" del sidebar. **Queda marcado como ASUMIDO para
que el humano lo corrija explícitamente si la intención original era otra** (p. ej. un valor
puramente decorativo, o basado en uptime).

## Archivos a modificar/crear

Modificar:
- `agente_ia/ui/gui.py`
- `agente_ia/main.py`
- `agente_ia/system_actions/system_info.py`
- `agente_ia/ai/memory_manager.py`
- `agente_ia/agents/action_registry.py`
- `agente_ia/core/security_manager.py`
- `agente_ia/ui/personality.py`
- `agente_ia/config_manager.py`
- `agente_ia/requirements.txt` (dependencia de test)

Crear:
- `agente_ia/ui/widgets/__init__.py`
- `agente_ia/ui/widgets/sidebar.py`
- `agente_ia/ui/widgets/header_bar.py`
- `agente_ia/ui/widgets/voice_orb.py`
- `agente_ia/ui/widgets/center_panel.py`
- `agente_ia/ui/widgets/right_panel.py`
- `agente_ia/ui/widgets/system_status_card.py`
- `agente_ia/ui/widgets/quick_actions_card.py`
- `agente_ia/ui/widgets/recent_activity_card.py`
- `agente_ia/ui/widgets/weather_card.py`
- `agente_ia/ui/gui_workers.py`
- `agente_ia/os_integration/weather_data.py`

No se toca (confirmado): `ui/cli.py`, `voice/wake_word.py`, `core/resolution.py`,
`router/dispatcher.py`, `intent/classifier.py`, `skills/weather_skill.py`.

## Dependencias nuevas

- **`psutil`**: ya instalado (v7.2.2), suficiente para las 4 métricas nuevas — no hace falta
  ninguna librería adicional para CPU/RAM/Disco/Red.
- **`wttr.in?format=j1`**: JSON estándar, se parsea con `json` de la librería estándar
  (`json.loads` sobre la respuesta de `urllib.request`) — no hace falta ningún parser HTTP/JSON
  de terceros.
- **`pytest-qt`** (nueva, solo para tests): necesaria para poder instanciar y ejercitar los
  widgets PyQt6 nuevos (`Sidebar`, `SystemStatusCard`, etc.) en pytest sin abrir una ventana real
  — provee el fixture `qtbot` y maneja `QApplication`/`QT_QPA_PLATFORM=offscreen` de forma
  estándar en el ecosistema PyQt. Se agrega a `requirements.txt` con un comentario que la marca
  como dependencia de testing, no de runtime.
- No se requiere ninguna librería de íconos externa: los íconos de `Sidebar`/`QuickActionsCard`
  se resuelven con `QStyle.StandardPixmap` (íconos incluidos en PyQt6) como aproximación
  razonable, dentro de la libertad de ajuste visual confirmada en P3.

## Evaluación de `orion-security` (confirmación explícita del architect)

SPEC-008 (P7) y el baseline concluyeron que no hace falta `orion-security` como paso extra.
Como architect, **confirmo esa conclusión con criterio propio**, incluyendo el análisis
específico de `open_spotify` (la única acción realmente nueva de este REQ):

- `open_spotify()` sigue exactamente el mismo patrón que las acciones GREEN ya auditadas en
  REQ-005 (`open_chrome`, `open_browser`, etc.): abre un ejecutable conocido del sistema o una
  URL pública vía `webbrowser.open`. No lee ni transmite credenciales, no escribe ni borra
  archivos, no requiere privilegios elevados, no expone secretos.
- Pasa **exclusivamente** por `execute_action()` → `security_manager.require_confirmation()` —
  el `QuickActionsCard` nunca llama `open_spotify()` directo (verificado en el diseño de
  `ui/widgets/quick_actions_card.py` arriba). Cero caminos nuevos sin gate.
- Se agrega explícitamente a `green_actions` en `core/security_manager.py` (el hallazgo de
  baseline queda resuelto en este diseño) — si no se hiciera, la acción quedaría bloqueada por
  fail-closed (no autorizada), nunca "permitida sin gate"; es decir, el peor caso de omitir este
  paso es una regresión funcional (CA-08 falla), no un agujero de seguridad.
- La barra de comando (CA-12) reutiliza `core/resolution.py:resolve()` sin cambios — el mismo
  pipeline gateado que ya usa `ui/cli.py` hoy, con `channel=ChannelType.DESKTOP` fijo (nunca
  inferido del texto del usuario, respetando el invariante de `security_manager.py:239-246`).
- Ninguna de las 6 acciones de "Accesos rápidos" queda clasificada AMARILLO o ROJO (CA-16).
- **Conclusión: no se requiere `orion-security` para REQ-008.** Si en desarrollo apareciera
  alguna necesidad no prevista aquí (p. ej. Spotify terminara requiriendo credenciales), el
  desviarse de esta arquitectura debe volver a este agente antes de continuar.

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| `psutil.cpu_percent(interval=None)` devuelve `0.0` en la primera lectura del proceso | `SystemStatusCard` hace una lectura de "precalentamiento" al construirse (antes de arrancar el `QTimer` visible) para que el primer refresco visible ya sea representativo. |
| Bloquear el hilo GUI si algún acceso rápido, el clima o `resolve()` se invocan directo en vez de vía `run_async()` | Regla de diseño explícita y verificable: toda I/O de red/subprocess/`resolve()` pasa por `ui/gui_workers.py:run_async()`. `orion-qa` revisa que no haya llamadas directas a `execute_action`/`get_weather_structured`/`resolve` desde un slot conectado a un botón. |
| `open_spotify` sin registrar en `security_manager.green_actions` (hallazgo de baseline) | Incorporado explícitamente en este diseño (sección "Módulos a modificar" y "Nuevas clases/funciones"); test dedicado en `tests/test_security_manager.py` que falla si se elimina. |
| Duplicados en "Actividad reciente" (cada turno se guarda 2 veces: `category="interaction"` y `"semantic"`, ver `main.py:166-172`) | `get_recent()` filtra por `category="interaction"` por defecto, excluyendo la copia semántica del mismo turno. |
| Callback de `run_async()` ejecutado en el hilo equivocado si se conecta a una función no vinculada a un `QObject` | Regla de diseño documentada arriba + revisión de `orion-qa` en cada uso. |
| Multi-monitor: `showMaximized()` se abre donde decida Qt/Windows, sin lógica de centrado explícita | Ya asumido y aceptado en SPEC-008; no se agrega lógica de selección de monitor en este REQ. |
| wttr.in sin red o con timeout | Ya cubierto por `run_async()` (no bloquea GUI) + timeout de 5s existente + estado "no disponible" explícito en `WeatherCard` (nunca deja datos viejos como si fueran actuales sin indicarlo... revisar en desarrollo si se quiere distinguir "cargando" de "error"). |
| Cambio de UX: se pierde el arrastre libre de ventana del HUD flotante actual al pasar a `QMainWindow` estándar | Cambio intencional y aprobado (P2). Si el humano lo objeta en la prueba manual final, es un ajuste de alcance a resolver antes de `LISTO_PARA_COMMIT`, no un bug. |
| `pytest-qt` requiere un backend Qt "offscreen" en máquinas sin display (CI futuro) | Fijar `QT_QPA_PLATFORM=offscreen` en `tests/conftest.py` o `pytest.ini` para que la suite corra igual con o sin entorno gráfico. |
| Anillo central "100%" con semántica ambigua en el mockup | Decisión explícita documentada arriba (salud = 100 - promedio(cpu,ram,disk)), marcada como ASUMIDO para confirmación humana. |

## Pruebas sugeridas

Todas nuevas (ninguno de los 8-9 módulos tocados tiene cobertura pytest hoy, según baseline).
Se separa deliberadamente la lógica no-Qt (100% testeable con pytest puro) de los widgets Qt
(testeados con `pytest-qt`, sin aserciones de pixel/visuales).

- `tests/test_system_info_numeric.py` — `get_cpu_percent()`/`get_ram_percent()`/
  `get_disk_percent()`/`get_network_io_counters()` con `psutil` mockeado (valores válidos,
  `psutil` no instalado → degrada a `0.0`/`(0,0)` sin excepción). Cubre CA-06.
- `tests/test_weather_data.py` — `get_weather_structured()` con `urllib.request.urlopen`
  mockeado: JSON válido → `WeatherData` correcto; timeout/`Exception` → `None`; ciudad vacía →
  URL sin segmento de ciudad. Cubre CA-10.
- `tests/test_memory_manager_recent.py` — `get_recent()` con `tmp_path`/DB temporal: orden por
  `timestamp DESC`, respeta `limit`, filtra por `category`, usuario sin interacciones → `[]`.
  Cubre CA-09.
- `tests/test_action_registry_spotify.py` — `open_spotify()` con `os.path.isfile` y
  `subprocess.Popen`/`webbrowser.open` mockeados: ruta existente → abre app; ninguna ruta →
  abre navegador; excepción → mensaje de error logueado (sin `except: pass`). Cubre CA-08.
- `tests/test_security_manager.py` (extender el existente) — `"open_spotify"` está clasificado
  `RiskLevel.GREEN` tras `_register_action_registry_actions()`; `require_confirmation("open_spotify",
  ChannelType.DESKTOP)` retorna `True` sin pedir confirmación. Cubre CA-08/CA-16.
- `tests/test_personality_greeting.py` — `get_time_based_greeting()` con `datetime` mockeado:
  antes de 12:00 → "Buenos días"; 12:00-18:59 → "Buenas tardes"; 19:00-04:59 → "Buenas noches";
  con y sin `display_name`. Cubre CA-03/CA-04.
- `tests/test_config_manager_display_name.py` — `get_display_name()`/`set_display_name()` sobre
  `config.json` temporal (`tmp_path`), default `""`. Cubre CA-04.
- `tests/test_gui_workers.py` (`pytest-qt`) — `run_async()` con función rápida → señal
  `finished` con el resultado correcto (`qtbot.waitSignal`); función que lanza excepción → señal
  `error` con el mensaje. Cubre la base de CA-07/CA-10/CA-12.
- `tests/test_gui_widgets.py` (`pytest-qt`) — sin aserciones visuales/pixel:
  - `Sidebar`: click en "Inicio" emite `nav_selected("inicio")`; los otros 6 botones tienen
    `isEnabled() == False`. Cubre CA-05.
  - `SystemStatusCard.set_values(18, 42, 31, 12)` deja los labels con esos valores exactos
    (sin arrancar el `QTimer`). Cubre CA-06.
  - `QuickActionsCard`: click en un botón llama `execute_action` (patch) con
    `channel=ChannelType.DESKTOP` y el nombre de acción correcto — nunca la función subyacente
    directo. Cubre CA-07.
  - `RecentActivityCard.set_items([])` muestra el texto de estado vacío;
    `set_items([MemoryItem(...)])` renderiza el texto e incluye la hora. Cubre CA-09.
  - `WeatherCard.set_data(None)` muestra "no disponible"; `set_data(WeatherData(...))` muestra
    los 4 campos. Cubre CA-10.
  - `CenterPanel`: al construirse con `display_name` mockeado, el label de saludo coincide con
    `get_time_based_greeting(...)`. Cubre CA-03/CA-04.
  - `JarvisMainWindow`: `close()` deja `isVisible() == False` y la app sigue viva (no se llama
    `quit()`); construida con `QApplication` en modo `offscreen`. Cubre CA-13.
- `python -m py_compile` sobre los 11 archivos modificados/creados + `python -m pytest tests/`
  completo (debe seguir en 123 + N nuevos, 0 fallos). Cubre CA-17.
