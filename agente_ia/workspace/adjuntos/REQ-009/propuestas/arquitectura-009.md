# Arquitectura REQ-009 — Control de modo manos libres (wake word) en la GUI JARVIS

## Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| CA-01 | `CenterPanel` agrega `self._wake_toggle` (`QPushButton` checkable, objectName `WakeToggleButton`), insertado en `command_row` a la izquierda del botón ➤. Estado inicial `unchecked` = "inactivo" desde la construcción del widget (no depende de polling para el primer render). |
| CA-02 | `HeaderBar` agrega `self._wake_indicator` (`QLabel` nuevo, objectName `WakeIndicator`), widget **separado** de `self._mode_pill`. Además, a nivel de datos: el nuevo canal `WAKE_STATE` (módulo `ui/gui.py`) es una variable independiente de `GLOBAL_STATE`, y `WakeWordWorker` (ver abajo) **no** escribe en `GLOBAL_STATE` — evita que el toggle GUI haga parpadear la píldora "Modo activo" existente (ver "Decisión: no reusar `GLOBAL_STATE` desde la GUI"). |
| CA-03 | `CenterPanel.hands_free_toggled(bool)` → `JarvisMainWindow._on_hands_free_toggled(True)` → crea `WakeWordWorker` y lo lanza en `QThreadPool.globalInstance()` (no bloqueante, mismo mecanismo que `run_async()` mas sin ser one-shot). `WakeWordWorker.run()` llama `update_wake_state("LISTENING_WAKE")` **antes** de invocar `listen_for_wake_word()` (que tarda ~1s en `adjust_for_ambient_noise`), así el ícono/toggle reflejan "escuchando" de inmediato, sin esperar al mic. |
| CA-04 | `listen_for_wake_word()` recibe el nuevo parámetro `wake_state_callback`; al detectar la wake word invoca `wake_state_callback("AWAKE")` y retorna. `WakeWordWorker.run()` vuelve a llamar `listen_for_wake_word()` en la siguiente iteración del `while`, que al re-entrar reporta `"LISTENING_WAKE"` de nuevo — sin que nada en esta cadena llame a `core/resolution.py:resolve()`. |
| CA-05 | `listen_for_wake_word()` recibe `stop_event: threading.Event`, revisado al tope de cada iteración del `while True` (antes de `recognizer.listen(timeout=1, phrase_time_limit=6)`). Peor caso: hasta ~1s (esperando inicio de frase) + 6s (frase en curso) ≈ el "~6s" ya aceptado por Johan. Al detectar `stop_event.is_set()`, retorna `None` (nuevo valor centinela) y `WakeWordWorker` sale del loop y reporta `"INACTIVE"`. |
| CA-06 | `ui/cli.py::CLI.__init__(self, gui_active: bool = False)` nuevo; `get_input_method()` solo imprime `"3) Modo manos libres (Wake Word)"` si `not self._gui_active`. |
| CA-07 | `CLI()` sin argumentos sigue dando `gui_active=False` (valor por defecto) → comportamiento bit a bit idéntico al actual en `--headless`. `listen_for_wake_word()` sin argumentos nuevos (`stop_event=None`, `wake_state_callback=None`) ejecuta exactamente las mismas ramas de código que hoy — ver "Decisión: parámetros opcionales para no romper el camino CLI". |
| CA-08 | Ningún método nuevo (`_on_hands_free_toggled`, `WakeWordWorker.__init__`/`run` en sus ramas de arranque/parada, `set_wake_state()` de los widgets) llama a `speak()`/TTS. El único `speak()` que puede sonar en esta cadena (`voice/wake_word.py` línea 90, "Lo escucho, Señor" cuando la wake word no trae comando) es preexistente y no depende de si el toggle GUI disparó la escucha o el CLI — ver nota en "Riesgos y mitigación". |
| CA-09 | `JarvisMainWindow._setup_tray_icon()` conecta `QApplication.instance().aboutToQuit` a `self._stop_wake_word_worker` (pide `stop_event.set()` del worker activo, si existe). `closeEvent()` no cambia (sigue minimizando a bandeja sin terminar el proceso, comportamiento heredado de REQ-008/CA-13) — el modo manos libres sigue corriendo en segundo plano mientras la ventana está oculta, igual que cualquier otro estado de la GUI hoy. Ver "Riesgos y mitigación" para el detalle de por qué esto no cuelga el proceso. |
| CA-10 | `WakeWordWorker.run()` envuelve la llamada a `listen_for_wake_word()` en `try/except Exception as e: logger.error(...)`. En el `finally` siempre reporta `update_wake_state("INACTIVE")` (tanto en el camino de parada cooperativa como en el de excepción), lo que hace que `CenterPanel.set_wake_state()`/`HeaderBar.set_wake_state()` vuelvan a "inactivo" vía polling. La excepción nunca se propaga fuera de `run()` (es un `QRunnable`, Qt no tiene dónde propagarla) — la GUI sigue usable. |

## Módulos a modificar

- `voice/wake_word.py` — nuevos parámetros opcionales `stop_event`/`wake_state_callback` en `listen_for_wake_word()`; nuevo valor de retorno centinela (`None`) para parada cooperativa; nuevo canal de reporte de estado desacoplado del `GLOBAL_STATE` existente.
- `ui/gui.py` — nueva variable de módulo `WAKE_STATE` + `update_wake_state()`; nueva clase auxiliar `WakeWordWorker(QRunnable)`; `JarvisMainWindow` orquesta arranque/parada del worker, extiende `_poll_state()`, conecta `aboutToQuit`.
- `ui/widgets/center_panel.py` — nuevo botón toggle + señal `hands_free_toggled(bool)` + método `set_wake_state(str)`.
- `ui/widgets/header_bar.py` — nuevo indicador `_wake_indicator` + método `set_wake_state(str)`.
- `ui/cli.py` — `CLI.__init__(gui_active=False)`; `get_input_method()` condiciona la opción "3".
- `main.py` — `main(boot_mode=None, gui_active=False)`; `CLI(gui_active=gui_active)`; `jarvis_runner()` pasa `gui_active=(not headless)` (closure sobre la variable `headless` ya calculada en el bloque `if __name__ == "__main__":`, sin nuevo estado compartido).

## Nuevas clases/funciones

- `WakeWordWorker(QRunnable)` en `ui/gui.py` — clase auxiliar pequeña (permitido por `python-style.md`, vive junto a `JarvisMainWindow` que ya la orquesta). Expone `self.stop_event = threading.Event()`; `run()` hace loop de `listen_for_wake_word()` hasta stop/excepción, reportando por `update_wake_state()`.
- `update_wake_state(new_state: str) -> None` en `ui/gui.py` — sibling de `update_gui_state()`, muta `WAKE_STATE` (variable de módulo, valores `"INACTIVE"` / `"LISTENING_WAKE"` / `"AWAKE"`).
- `JarvisMainWindow._on_hands_free_toggled(checked: bool) -> None` — handler del toggle; ignora clics repetidos mientras hay un worker activo (mitiga doble clic, ver casos borde).
- `JarvisMainWindow._stop_wake_word_worker() -> None` — pide parada cooperativa (`stop_event.set()`) del worker activo si existe; usada desde el toggle OFF y desde `aboutToQuit`.
- `CenterPanel.set_wake_state(state: str) -> None` — refleja el estado de 3 valores en el toggle (checked/unchecked + propiedad Qt `wakeState` para QSS), sin re-emitir `hands_free_toggled` (guard `self._updating_wake_toggle`).
- `HeaderBar.set_wake_state(state: str) -> None` — refleja el estado de 3 valores en `_wake_indicator` (texto + propiedad Qt `wakeState`).
- `CLI.__init__(self, gui_active: bool = False)` — nuevo constructor.

## Flujo de datos

**Encender (CA-03):**
`CenterPanel` (clic toggle) → señal `hands_free_toggled(True)` → `JarvisMainWindow._on_hands_free_toggled` → crea `WakeWordWorker`, `QThreadPool.globalInstance().start(worker)` → `WakeWordWorker.run()` (hilo de QThreadPool) llama `update_wake_state("LISTENING_WAKE")` inmediatamente, luego `listen_for_wake_word(stop_event=..., wake_state_callback=update_wake_state)` (bloqueante, en background) → `JarvisMainWindow._poll_state()` (QTimer 100ms, hilo principal) detecta el cambio en `WAKE_STATE` → `center_panel.set_wake_state(...)` + `header_bar.set_wake_state(...)`.

**Wake word detectada (CA-04):**
Dentro de `listen_for_wake_word()`, al reconocer la palabra clave → `wake_state_callback("AWAKE")` (muta `WAKE_STATE` directo, mismo hilo worker) → retorna `True`/`str` → `WakeWordWorker.run()` vuelve a invocar `listen_for_wake_word()` → reporta `"LISTENING_WAKE"` de nuevo. `resolve()` nunca se invoca en esta cadena.

**Apagar (CA-05):**
`CenterPanel` (clic toggle) → `hands_free_toggled(False)` → `_on_hands_free_toggled` → `_stop_wake_word_worker()` → `worker.stop_event.set()` (mutación de `threading.Event`, segura entre hilos). El hilo worker revisa el evento al tope de su próxima iteración (hasta ~6-7s) → `listen_for_wake_word()` retorna `None` → `WakeWordWorker.run()` sale del loop → `finally: update_wake_state("INACTIVE")` → `_poll_state()` detecta el cambio → widgets a "inactivo" → `_poll_state()` también limpia `self._wake_worker = None`.

**Error (CA-10):**
`listen_for_wake_word()` lanza excepción (p. ej. `sr.Microphone()` sin dispositivo) → propaga fuera de la función (ocurre antes/durante el `with sr.Microphone()`, fuera de los `try/except` internos del loop) → capturada en `WakeWordWorker.run()` → `logger.error(...)` → `finally: update_wake_state("INACTIVE")` → mismo camino de polling que el apagado manual.

**Cierre real del proceso (CA-09):**
Menú de bandeja "Salir" → `QApplication.instance().quit()` → señal `aboutToQuit` → `_stop_wake_word_worker()` (best-effort, no bloquea el `quit()`).

**Ocultar opción 3 del CLI (CA-06/CA-07):**
`main.py` bloque `if __name__ == "__main__":` calcula `headless` (sin cambios) → `jarvis_runner()` (closure) llama `main(gui_active=(not headless))` → `main()` instancia `CLI(gui_active=gui_active)` → `get_input_method()` consulta `self._gui_active`.

## Archivos a modificar/crear
- `voice/wake_word.py`
- `ui/gui.py`
- `ui/widgets/center_panel.py`
- `ui/widgets/header_bar.py`
- `ui/cli.py`
- `main.py`

No se crean archivos nuevos — los 6 coinciden exactamente con la previsión de `orion-baseline`.

## Dependencias nuevas
Ninguna. Todo lo usado (`PyQt6.QtCore.QRunnable`/`QThreadPool`, `threading.Event`, `logging`) ya está en `requirements.txt` y en uso en el código base (`ui/gui_workers.py`, `voice/wake_word.py`).

## Decisiones de diseño (para que quede explícito, no implícito)

### Decisión: parámetros opcionales para no romper el camino CLI
`listen_for_wake_word(stop_event: Optional[threading.Event] = None, wake_state_callback: Optional[Callable[[str], None]] = None)`. Cuando ambos son `None` (como los llama `main.py` hoy, sin cambios), el código ejecuta exactamente las mismas ramas que existen actualmente — incluyendo el `try/except Exception: pass` preexistente que sigue reportando a `update_gui_state()` (canal viejo de 4 valores). Es la única forma de garantizar CA-07 (bit a bit igual en headless) sin duplicar la función.

### Decisión: no reusar `GLOBAL_STATE` desde la GUI (justificación para tocar `voice/wake_word.py` más allá de agregar la cancelación)
El baseline advirtió que `listen_for_wake_word()` ya muta `GLOBAL_STATE` (LISTENING/IDLE) en cada iteración vía el `except Exception: pass` preexistente (líneas ~69-73/111-115), pensado para el uso del CLI. Si el worker de la GUI llamara a la función tal cual, ese efecto secundario seguiría disparándose en cada iteración del modo manos libres (aprox. cada 1-7s mientras está ON), hacía parpadear la píldora "Modo activo"/`VoiceOrb` del `HeaderBar`/`CenterPanel` con "Escuchando..."/"En espera..." sin relación con ningún comando en curso — lo cual viola el espíritu de CA-02 ("no se pisan ni se confunden"), no solo en lo visual sino en el dato subyacente. Por eso `listen_for_wake_word()` decide **cuál** canal actualizar según si recibió `wake_state_callback`: si se pasó (siempre el caso desde la GUI), usa *solo* el canal nuevo y **omite** la mutación de `GLOBAL_STATE`; si no se pasó (siempre el caso del CLI, `None` por defecto), mantiene el comportamiento preexistente sin cambios. Esto es exactamente la excepción que el baseline anticipó ("el código existente no se resuelve en este REQ salvo que la arquitectura lo requiera para CA-10" — aquí aplica el mismo razonamiento para CA-02).

### Decisión: sin señales Qt cross-thread, todo por polling
Se mantiene el patrón ya establecido en REQ-008 (`GLOBAL_STATE` + `QTimer` de 100ms) para el nuevo canal, en vez de introducir `pyqtSignal` emitidas desde el hilo de `QThreadPool`. Motivo: es el mismo patrón ya validado en este código base para cruzar de hilo trabajador a hilo GUI, minimiza superficie nueva, y evita mezclar dos mecanismos de sincronización distintos para dos "familias" de estado que en la práctica se leen desde el mismo `_poll_state()`.

### Nota para Johan (no es una desviación de CA-08, pero es una interacción a tener presente)
Cuando la wake word se detecta sin comando adicional, `voice/wake_word.py` línea 90 sigue diciendo por TTS "Lo escucho, Señor" — ese `speak()` es preexistente y no depende de si la escucha la disparó el CLI o el toggle de la GUI. CA-08 solo prohíbe TTS *al togglear* (encender/apagar), no al detectar la wake word en sí, así que esto no es una violación de la SPEC. Pero como este REQ explícitamente no encadena captura de comando tras la GUI (CA-04), el usuario podría escuchar "Lo escucho, Señor" seguido de silencio (vuelve a "escuchando" sin pedir nada). Se deja así por estar fuera del alcance textual de la SPEC — si Johan lo quiere silenciar en el camino GUI, es un ajuste menor (pasar un flag adicional a `listen_for_wake_word()` para suprimir ese `speak()` específico) que puede resolverse en este mismo REQ si lo pide ahora, o quedar para un REQ posterior.

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| Doble clic rápido en el toggle dispara dos `WakeWordWorker` en paralelo, compitiendo por `sr.Microphone()`. | `_on_hands_free_toggled(True)` ignora el clic si `self._wake_worker is not None` (ya hay un worker activo, incluso si está en proceso de detenerse). `self._wake_worker` solo se limpia a `None` cuando `_poll_state()` observa `WAKE_STATE == "INACTIVE"` — un ON inmediatamente después de un OFF quedará ignorado hasta que el worker previo termine de apagarse (~hasta 6-7s), evitando el paralelismo a costa de una latencia visible que ya es best-effort por SPEC. |
| Cierre del proceso vía bandeja "Salir" mientras el worker de `QThreadPool` está bloqueado dentro de una llamada C (`sr.Microphone`/PyAudio), sin ser un `threading.Thread` de Python rastreado por el intérprete. | `aboutToQuit` pide `stop_event.set()` antes de que Qt cierre el loop de eventos (best-effort, igual que CA-05). En el peor caso el hilo de `QThreadPool` sigue vivo unos segundos más tras el `sys.exit(app.exec())` del hilo principal — como no es un `threading.Thread` no-daemon visible para Python, no bloquea la finalización del intérprete; se acepta como el mismo trade-off de latencia ya aprobado por Johan para CA-05, aplicado también al cierre. |
| `sr.Microphone()` falla dentro de `with` (antes de entrar al `while` interno) — la excepción nace fuera de los `try/except` existentes del loop. | Se captura en el nivel del *llamador* nuevo (`WakeWordWorker.run()`), no dentro de `voice/wake_word.py` — evita tocar el control de flujo interno del loop (que la SPEC no pide cambiar) y centraliza el manejo de CA-10 en un solo lugar nuevo, ya con `logging` explícito (nunca `except: pass`). |
| Cerrar la ventana (`closeEvent`, minimizar a bandeja) mientras el modo manos libres está ON dejaría el listener corriendo sin ningún indicador visible (ventana oculta). | Aceptado a propósito: es el mismo comportamiento que ya tiene cualquier otro estado de la GUI al minimizar (REQ-008/CA-13 — minimizar no pausa nada). El usuario puede reabrir la ventana desde la bandeja para ver/apagar el estado; no se interpreta como "proceso colgado" (CA-09 solo exige que no cuelgue ni lance excepciones, no que se detenga automáticamente al ocultar). |
| Callback `wake_state_callback` lanza una excepción inesperada dentro del loop de `listen_for_wake_word()` (p. ej. bug futuro en `update_wake_state`). | Cada invocación del callback dentro de `voice/wake_word.py` se envuelve en su propio `try/except Exception as e: logger.error(...)` — nunca silenciado, consistente con `python-style.md` y con el espíritu de CA-10 aunque el fallo no venga del micrófono. |
| Fallos repetidos de reconocimiento (`sr.RequestError` u otra excepción dentro del `while` interno) dejan el toggle "trabado" en ON. | Esas excepciones ya están contempladas dentro del `while` existente (no rompen el loop, seguido de `continue`/`pass`), así que `listen_for_wake_word()` sigue viva y seguirá revisando `stop_event` en la próxima iteración — el usuario puede apagar el toggle en cualquier momento con la misma latencia best-effort de CA-05. |

## Pruebas sugeridas

Una por criterio, pensadas para `pytest-qt` (`qtbot`, backend offscreen ya fijado en `tests/conftest.py`) y `unittest.mock`, siguiendo el patrón de `tests/test_gui_widgets.py`:

- **CA-01**: `test_center_panel_wake_toggle_starts_unchecked` — instanciar `CenterPanel`, `findChild(QPushButton, "WakeToggleButton")` existe y `.isChecked() is False`.
- **CA-02**: `test_header_bar_wake_indicator_is_separate_widget` — `HeaderBar` expone `_wake_indicator` y `_mode_pill` como objetos distintos; llamar `header_bar.set_state("LISTENING")` (canal viejo) y comprobar que `_wake_indicator.text()` no cambia; llamar `header_bar.set_wake_state("LISTENING_WAKE")` y comprobar que `_mode_pill.text()` no cambia.
- **CA-03**: `test_toggle_on_starts_worker_without_blocking` (mock de `ui.gui.QThreadPool.globalInstance().start` o de `WakeWordWorker.run` para no tocar el micrófono real) — emitir `hands_free_toggled(True)` en una `JarvisMainWindow` de test, verificar que se creó un `WakeWordWorker` y que `QThreadPool.start` fue llamado (no bloqueante: el test no debe esperar tiempo real).
- **CA-04**: `test_wake_word_worker_detected_does_not_call_resolve` — con `voice.wake_word.listen_for_wake_word` mockeado para devolver `True` una vez y luego bloquear/lanzar `StopIteration` controlada, verificar que `update_wake_state("AWAKE")` se llamó y que `core.resolution.resolve` (mockeado) **nunca** fue invocado.
- **CA-05**: `test_stop_event_causes_listen_for_wake_word_to_return_none` — llamar directo a `listen_for_wake_word(stop_event=<Event ya seteado>)` con `sr.Microphone`/`sr.Recognizer` mockeados, verificar que retorna `None` sin entrar al `while` (o en la primera vuelta).
- **CA-06**: `test_get_input_method_hides_option_3_when_gui_active` — `CLI(gui_active=True).get_input_method()` con `builtins.input` mockeado; capturar stdout (`capsys`) y verificar que `"3)"` no aparece.
- **CA-07**: `test_get_input_method_shows_option_3_when_headless` — `CLI(gui_active=False).get_input_method()` (o `CLI()` sin argumentos), verificar que `"3)"` sigue apareciendo, igual que antes del REQ.
- **CA-08**: `test_toggle_never_calls_speak` — patchear `voice.wake_word.speak`/`ui.tts_engine.speak`, emitir `hands_free_toggled(True)` y luego `hands_free_toggled(False)` sobre una ventana de test (con el worker real mockeado para no tocar hardware), verificar `speak.assert_not_called()`.
- **CA-09**: extender el `test_jarvis_main_window_close_hides_without_quitting_app` existente, o uno nuevo `test_about_to_quit_stops_wake_word_worker` — con un `WakeWordWorker` fake asignado a `window._wake_worker`, emitir `QApplication.instance().aboutToQuit`, verificar que `stop_event.is_set()` es `True` y que no se lanza ninguna excepción no manejada.
- **CA-10**: `test_wake_word_worker_logs_error_and_resets_to_inactive` — con `listen_for_wake_word` mockeado para lanzar `OSError("mic no disponible")`, ejecutar `WakeWordWorker.run()` directamente (sin `QThreadPool`, es solo un método), verificar (a) `caplog` contiene un `ERROR` con el mensaje, (b) `ui.gui.WAKE_STATE == "INACTIVE"` al terminar, (c) no se propaga ninguna excepción fuera de `run()`.
- **Regresión / caso borde doble clic**: `test_double_click_toggle_does_not_start_two_workers` — emitir `hands_free_toggled(True)` dos veces seguidas sin que `WAKE_STATE` haya vuelto a `"INACTIVE"` entre medio; verificar que solo se creó/arrancó un `WakeWordWorker`.
- **Regresión / suite completa**: correr `pytest tests/ --tb=short -v` completo — debe seguir en 175+N passed (N = tests nuevos de este REQ), mismos 3 warnings pre-existentes documentados en `baseline-009.md`, sin nuevos fallos.
