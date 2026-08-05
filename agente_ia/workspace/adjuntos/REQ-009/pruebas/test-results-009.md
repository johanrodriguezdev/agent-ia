# Resultados de prueba REQ-009 — Control de modo manos libres (wake word) en la GUI JARVIS

## Compilación
`python -m py_compile` sobre los 6 archivos modificados: **OK**, sin errores.
```
voice/wake_word.py
ui/gui.py
ui/widgets/center_panel.py
ui/widgets/header_bar.py
ui/cli.py
main.py
```

## Tests existentes (regresión, previos a este REQ)
- Pasados: 175/175 (baseline heredado de `orion-dev`/`orion-baseline`, re-verificado por
  `orion-tester` antes de escribir tests nuevos).
- Nuevos fallos: ninguno.
- Mismos 3 warnings pre-existentes documentados en `baseline-009.md` (deprecation
  `aifc`/`audioop` de `speech_recognition`, `PytestReturnNotNoneWarning` en
  `test_agents.py::test_ca1_orchestrator`).

## Tests nuevos escritos por orion-tester

`arquitectura-009.md` proponía 12 pruebas sugeridas (una por CA + 2 de regresión), pero
`orion-dev` no las implementó (correspondía a este paso, según el DoD del REQ). Se
escribieron **22 tests nuevos**, headless, sin tocar `sr.Microphone()`/hardware real, en
3 archivos:

- `tests/test_wake_word.py` (5 tests) — lógica pura de `voice/wake_word.py`: parada
  cooperativa (`stop_event`), comportamiento sin cambios cuando `stop_event=None`
  (CA-07), y `_report_awake()` (callback nunca silenciado, CA-04/riesgos).
- `tests/test_cli_gui_active.py` (3 tests) — `CLI.__init__(gui_active=...)` y el efecto
  en `get_input_method()` (CA-06/CA-07), y default `False` bit-a-bit (CA-07).
- `tests/test_wake_word_gui.py` (14 tests, con `pytest-qt`/`qtbot` en modo offscreen) —
  `CenterPanel`/`HeaderBar` (CA-01/CA-02), `WakeWordWorker`/`JarvisMainWindow` (CA-03,
  CA-04, CA-05, CA-08, CA-09, CA-10) y el caso borde de doble clic. `QThreadPool` y
  `listen_for_wake_word()` van mockeados en todos los tests que ejercitan el worker —
  nunca se arranca un hilo real ni se toca el micrófono.

Suite completa tras agregarlos: **197 passed** (175 previos + 22 nuevos), mismos 3
warnings, sin regresiones.

```
tests/test_wake_word.py::test_stop_event_causes_listen_for_wake_word_to_return_none PASSED
tests/test_wake_word.py::test_listen_for_wake_word_without_stop_event_does_not_crash_on_first_check PASSED
tests/test_wake_word.py::test_report_awake_calls_callback_with_awake PASSED
tests/test_wake_word.py::test_report_awake_with_none_callback_is_noop PASSED
tests/test_wake_word.py::test_report_awake_logs_callback_exception_without_raising PASSED
tests/test_cli_gui_active.py::test_get_input_method_hides_option_3_when_gui_active PASSED
tests/test_cli_gui_active.py::test_get_input_method_shows_option_3_when_headless PASSED
tests/test_cli_gui_active.py::test_cli_default_constructor_keeps_option_3_bit_for_bit PASSED
tests/test_wake_word_gui.py::test_center_panel_wake_toggle_starts_unchecked PASSED
tests/test_wake_word_gui.py::test_center_panel_set_wake_state_does_not_reemit_signal PASSED
tests/test_wake_word_gui.py::test_center_panel_toggle_click_emits_hands_free_toggled PASSED
tests/test_wake_word_gui.py::test_header_bar_wake_indicator_is_separate_widget PASSED
tests/test_wake_word_gui.py::test_toggle_on_starts_worker_without_blocking PASSED
tests/test_wake_word_gui.py::test_double_click_toggle_does_not_start_two_workers PASSED
tests/test_wake_word_gui.py::test_wake_word_worker_detected_does_not_call_resolve PASSED
tests/test_wake_word_gui.py::test_toggle_off_sets_stop_event_on_active_worker PASSED
tests/test_wake_word_gui.py::test_toggle_never_calls_speak PASSED
tests/test_wake_word_gui.py::test_stop_wake_word_worker_is_noop_without_active_worker PASSED
tests/test_wake_word_gui.py::test_stop_wake_word_worker_stops_active_worker PASSED
tests/test_wake_word_gui.py::test_about_to_quit_signal_stops_active_worker PASSED
tests/test_wake_word_gui.py::test_wake_word_worker_logs_error_and_resets_to_inactive PASSED
tests/test_wake_word_gui.py::test_poll_state_clears_wake_worker_reference_when_inactive PASSED
```

## Criterios de la SPEC

| Criterio | Resultado | Nota |
|----------|-----------|------|
| CA-01: `CenterPanel` muestra el toggle junto a ➤, inicial "inactivo" (OFF) | PASS | `test_center_panel_wake_toggle_starts_unchecked`: el botón `WakeToggleButton` existe, `isChecked() is False`, `wakeState` inicial `"INACTIVE"`. Revisión de código: insertado en `command_row` entre `_command_input` y `send_btn` — adyacente al botón ➤. |
| CA-02: `HeaderBar` muestra indicador separado de la píldora "Modo activo" | PASS | `test_header_bar_wake_indicator_is_separate_widget`: `_wake_indicator is not _mode_pill`; `set_wake_state()` no toca el texto de `_mode_pill` y `set_state()` no toca el texto de `_wake_indicator` — no se pisan ni se confunden. |
| CA-03: clic ON → GUI no se congela (worker en background) + ícono/toggle pasan a "escuchando" | PASS | `test_toggle_on_starts_worker_without_blocking`: `_on_hands_free_toggled(True)` crea un `WakeWordWorker` y llama `QThreadPool.globalInstance().start(...)` — retorno inmediato del handler (no bloqueante por diseño: `start()` no espera a que `run()` termine). El cambio visual a "escuchando" se verifica indirectamente vía `WakeWordWorker.run()`, que llama `update_wake_state("LISTENING_WAKE")` al tope de cada iteración (código revisado; el valor lo reflejan `set_wake_state()` de ambos widgets, ya cubiertos por CA-01/CA-02). |
| CA-04: wake word detectada → "despierto", retoma "escuchando" automáticamente, `resolve()` nunca se invoca | PASS | `test_wake_word_worker_detected_does_not_call_resolve`: con `listen_for_wake_word` mockeado para reportar `AWAKE` y luego señalar `stop_event`, se confirma `"AWAKE"` en los estados reportados y `core.resolution.resolve` **nunca** llamado. El retorno automático a "escuchando" es estructural: `WakeWordWorker.run()` vuelve a llamar `update_wake_state("LISTENING_WAKE")` al tope de cada iteración del `while`. |
| CA-05: clic OFF → parada cooperativa (~6s best-effort), vuelve a "inactivo" | PASS | `test_stop_event_causes_listen_for_wake_word_to_return_none` (nivel `voice/wake_word.py`: `stop_event` seteado → retorna `None` sin llamar `recognizer.listen()`) + `test_toggle_off_sets_stop_event_on_active_worker`/`test_stop_wake_word_worker_stops_active_worker` (nivel GUI: el clic OFF setea `worker.stop_event`). |
| CA-06: con GUI activa, `get_input_method()` no ofrece la opción "3" | PASS | `test_get_input_method_hides_option_3_when_gui_active`: con `CLI(gui_active=True)`, ni `"3)"` ni `"Modo manos libres"` aparecen en stdout. |
| CA-07: en `--headless`, opción "3" sigue igual que antes (sin regresión) | PASS | `test_get_input_method_shows_option_3_when_headless` + `test_cli_default_constructor_keeps_option_3_bit_for_bit` (nivel CLI) + `test_listen_for_wake_word_without_stop_event_does_not_crash_on_first_check` (nivel `wake_word.py`: sin `stop_event`/`wake_state_callback`, mismas ramas que antes de REQ-009, incluyendo el camino `KeyboardInterrupt`). |
| CA-08: togglear (ON u OFF) nunca dispara `speak()`/TTS | PASS | `test_toggle_never_calls_speak`: `ui.tts_engine.speak` mockeado, se togglea ON y luego OFF (worker real no llega a ejecutar `run()`, `QThreadPool` mockeado) — `speak` nunca invocado. |
| CA-09: cerrar la ventana con el modo ON no cuelga el proceso ni lanza excepción no manejada | PASS | `test_about_to_quit_signal_stops_active_worker`: verifica el *wiring* real (`QApplication.instance().aboutToQuit.connect(self._stop_wake_word_worker)` hecho en `_setup_tray_icon()`) emitiendo la señal real y confirmando que `stop_event` del worker activo queda seteado. Complementado por `test_stop_wake_word_worker_is_noop_without_active_worker` (no lanza sin worker activo). |
| CA-10: fallo en `listen_for_wake_word()` se loguea (no `except: pass`), toggle vuelve a "inactivo", GUI no crashea | PASS | `test_wake_word_worker_logs_error_and_resets_to_inactive`: con `listen_for_wake_word` mockeado para lanzar `OSError("mic no disponible")`, `worker.run()` no propaga la excepción, `caplog` contiene el `ERROR` con el mensaje, y `WAKE_STATE == "INACTIVE"` al terminar (vía `finally`). |

**10/10 criterios PASS.**

## Regresión

| Área revisada | Resultado |
|----------------|-----------|
| Suite completa (175 tests previos a REQ-009) | PASS — sin nuevos fallos, mismos 3 warnings |
| `ui/cli.py` en modo headless (`CLI()` sin argumentos) | PASS — bit a bit igual (opción "3" sigue visible y funcional) |
| `voice/wake_word.py` sin `stop_event`/`wake_state_callback` (uso actual del CLI) | PASS — mismas ramas de código que antes de REQ-009 (verificado con test dedicado) |
| Caso borde: doble clic rápido en el toggle | PASS — `test_double_click_toggle_does_not_start_two_workers`: un segundo `ON` mientras hay worker activo se ignora, no arranca un segundo `WakeWordWorker` |
| Caso borde: `_poll_state()` libera `self._wake_worker` solo en transición real a INACTIVE | PASS — `test_poll_state_clears_wake_worker_reference_when_inactive` |
| Píldora "Modo activo" (`GLOBAL_STATE`/4 valores) vs. nuevo canal `WAKE_STATE`/3 valores | PASS — `test_header_bar_wake_indicator_is_separate_widget` confirma que no se pisan |

## Alcance no cubierto por automatización (verificado por revisión de código, no por test)
- Render visual real (colores/QSS por estado, iconografía 🎙/🟢) — sin ventana real
  disponible en este entorno (offscreen), no verificable por pixel; el mecanismo de datos
  que lo alimenta (`wakeState` property + `set_wake_state()`) sí está cubierto.
- Latencia real de ~6-7s de la parada cooperativa (best-effort) — verificado el mecanismo
  (`stop_event` revisado al tope del `while`), no el tiempo de reloj real (requeriría
  micrófono real o un sleep largo en la suite, fuera de lo razonable para CI).

## Veredicto: PASS

---

## Ciclo 2 — Retest tras diagnóstico post-QA (2026-08-05)

### Contexto
Johan reportó una falla en la prueba manual tras el `orion-qa` APROBADO original ("Probé lo
manos libres activando el audio pero no me escucha"). `orion-dev` investigó (ver
`desarrollo-log-009.md`, sección "Ciclo 2"), descartó bugs de wiring/threading/wake-words, y
confirmó que el fallback local Whisper nunca estuvo instalado — por lo que cualquier fallo de
`recognizer.recognize_google()` quedaba completamente silencioso. Agregó logging de
diagnóstico (`logger.info`/`logger.warning`) dentro de tres puntos de
`voice/wake_word.py::listen_for_wake_word()`, sin tocar ningún control de flujo existente
(mismos `continue`, mismo fallback a Whisper, mismos retornos). Único archivo tocado en este
ciclo: `voice/wake_word.py`.

### Compilación
`python -m py_compile voice/wake_word.py`: **OK**, sin errores.

### Tests existentes (regresión completa)
```
python -m pytest tests/ --tb=short -q
```
**197 passed**, mismos 3 warnings pre-existentes (aifc/audioop deprecation +
`PytestReturnNotNoneWarning` en `test_agents.py::test_ca1_orchestrator`) — sin nuevos fallos.
No fue necesario agregar tests nuevos: el cambio es aditivo (logging dentro de ramas `except`
ya cubiertas por los 22 tests existentes de wake word) y no introduce ninguna rama de código
nueva que requiera cobertura propia — se re-ejecutaron específicamente los 22 tests
relacionados para confirmarlo:
```
python -m pytest tests/test_wake_word.py tests/test_wake_word_gui.py tests/test_cli_gui_active.py -v
→ 22 passed, 2 warnings
```

### Re-verificación de los 10 criterios de la SPEC tras el cambio

| Criterio | Resultado | Nota |
|----------|-----------|------|
| CA-01 | PASS | `ui/widgets/center_panel.py` no fue tocado en este ciclo. `test_center_panel_wake_toggle_starts_unchecked` re-ejecutado, sigue en verde. |
| CA-02 | PASS | `ui/widgets/header_bar.py` no fue tocado. `test_header_bar_wake_indicator_is_separate_widget` re-ejecutado, sigue en verde. |
| CA-03 | PASS | `ui/gui.py` no fue tocado. `test_toggle_on_starts_worker_without_blocking` re-ejecutado, sigue en verde. |
| CA-04 | PASS | `_report_awake()` (cycle 1, sin cambios en cycle 2) y el camino de detección de wake word no fueron alterados — el logging nuevo vive únicamente en las ramas de "no se pudo transcribir"/"no matcheó", antes del punto de detección. `test_wake_word_worker_detected_does_not_call_resolve` re-ejecutado, sigue en verde; revisión de código confirma que `is_wake=True` sigue devolviendo exactamente igual que antes (líneas 142-151 sin diff). |
| CA-05 | PASS | El chequeo de `stop_event` al tope del `while` (línea 86-87) no fue tocado. `test_stop_event_causes_listen_for_wake_word_to_return_none` re-ejecutado, sigue en verde. |
| CA-06 | PASS | `ui/cli.py` no fue tocado. `test_get_input_method_hides_option_3_when_gui_active` re-ejecutado, sigue en verde. |
| CA-07 | PASS | Crítico para este ciclo: los 2 `except` nuevos (`sr.UnknownValueError`, `sr.RequestError`) agregan `logger.info`/`logger.warning` pero preservan el mismo fallback a `_transcribe_whisper(audio)` y el mismo `continue` posterior — comportamiento bit a bit igual para el camino CLI/headless (que no pasa `wake_state_callback`, así que el logging nuevo es indiferente a quién llama). `test_listen_for_wake_word_without_stop_event_does_not_crash_on_first_check` y `test_cli_default_constructor_keeps_option_3_bit_for_bit` re-ejecutados, siguen en verde. |
| CA-08 | PASS | `ui/gui.py`/toggle no tocados. `test_toggle_never_calls_speak` re-ejecutado, sigue en verde. El logging nuevo tampoco invoca `speak()` en ningún punto (confirmado por lectura de código: solo `logger.info`/`logger.warning`). |
| CA-09 | PASS | `ui/gui.py`/`aboutToQuit` no tocados. `test_about_to_quit_signal_stops_active_worker` re-ejecutado, sigue en verde. |
| CA-10 | PASS | Relevante directamente para el hallazgo de este ciclo: antes, un fallo de `recognize_google()` (`UnknownValueError`/`RequestError`) quedaba sin ningún rastro si el fallback Whisper tampoco producía texto — comportamiento indistinguible de silencio, aunque técnicamente no era un `except: pass` (el `continue` seguía siendo alcanzado tras pasar por `_transcribe_whisper`). Ahora cada una de esas 3 ramas (`UnknownValueError`, `RequestError`, "ningún motor devolvió texto") tiene su propio `logger.info()`/`logger.warning()` explícito antes de continuar — cumple el espíritu de CA-10 ("el error se registra por logging, no se silencia") también para este camino de fallo parcial, no solo para el mic no disponible (que sigue cubierto, sin cambios, por `WakeWordWorker.run()` en `ui/gui.py`). Verificado por lectura directa del diff (ver abajo) — no requiere test nuevo porque no cambia ninguna rama de retorno/control de flujo, solo agrega observabilidad. |

**10/10 criterios PASS.**

### Verificación específica: sin `except: pass` silencioso introducido
Se inspeccionó el diff completo de `voice/wake_word.py` con `git diff` y se listaron todos los
bloques `except` del archivo resultante:
- Nuevos en este ciclo: `except sr.UnknownValueError:` (línea 110) y
  `except sr.RequestError as e:` (línea 120) — ambos con `logger.info()`/`logger.warning()`
  explícito antes del fallback, ninguno usa `pass`.
- Preexistentes sin cambios (ya señalados por `orion-baseline`/`orion-qa` como deuda técnica
  fuera de alcance de REQ-009): `except Exception: pass` en `_get_whisper()`/
  `_transcribe_whisper()` (líneas 22, 35), en el bloque de barge-in y en las llamadas a
  `update_gui_state()` (líneas 97-98, 104-105, 187-188 — solo se ejecutan en el camino CLI,
  `wake_state_callback is None`), y el `except sr.WaitTimeoutError:`/`except
  sr.UnknownValueError:`/`except sr.RequestError:` del bloque `try` externo (líneas 163-178,
  código legado que en la práctica ya no se alcanza para `UnknownValueError`/`RequestError`
  porque el `try` interno los captura primero — no modificado en este REQ).

Ninguno de los `except: pass` preexistentes fue tocado ni ampliado por este cambio.

### Regresión
| Área revisada | Resultado |
|----------------|-----------|
| Suite completa (197 tests) | PASS — sin nuevos fallos, mismos 3 warnings |
| 22 tests de wake word (`test_wake_word.py`, `test_wake_word_gui.py`, `test_cli_gui_active.py`) | PASS — sin modificación, todos en verde |
| `voice/wake_word.py` sin `stop_event`/`wake_state_callback` (uso actual del CLI headless) | PASS — mismas ramas de retorno, solo logging adicional |

### Alcance no cubierto por automatización (verificado por revisión de código, no por test)
- Contenido real transcripto por Google Speech al decir "Nodo" en la máquina de Johan — solo
  observable en la próxima prueba manual vía `logs/orion.log`/consola (es precisamente la
  evidencia que este ciclo agrega instrumentación para capturar). Fuera del alcance de
  `orion-tester` (requiere hardware de audio real y la voz de Johan).

### Veredicto: PASS
