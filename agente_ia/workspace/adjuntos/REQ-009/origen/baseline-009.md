# Baseline REQ-009

## Estado actual del sistema

El modo manos libres (wake word) existe hoy solo como un camino del CLI bloqueante
(`ui/cli.py`), sin ninguna integración visual con la GUI JARVIS (`ui/gui.py`, REQ-008). No hay
baseline funcional de un "toggle" o "indicador de wake word" — es funcionalidad nueva sobre la
GUI; lo que sí existe y se va a modificar es el mecanismo de wake word del CLI y los widgets de
la GUI donde se va a insertar el control.

### `ui/widgets/center_panel.py` (`CenterPanel`)
- Widget `QFrame` con: saludo dinámico, `VoiceOrb`, label de estado (`_status_label`), y una
  barra de comando (`QLineEdit` + `QPushButton("➤")`) que emite `command_submitted(str)`.
- No expone ningún control de wake word. No tiene ninguna señal `hands_free_toggled` ni
  método `set_wake_state()` — ambos son nuevos, a agregar por este REQ.
- `set_state(state)` ya existe y refleja los 4 estados (IDLE/LISTENING/PROCESSING/RESPONDING)
  sobre `VoiceOrb` y `_status_label` — es el mecanismo existente que el nuevo indicador de wake
  word NO debe pisar (CA-02 exige que sean visualmente independientes).

### `ui/widgets/header_bar.py` (`HeaderBar`)
- Widget `QFrame` con una píldora de texto (`_mode_pill`, objeto `ModePill`) que refleja los
  mismos 4 estados globales vía `set_state()`, más un ícono de campana (`🔔`) puramente
  decorativo, sin handler.
- No tiene ningún ícono/indicador de wake word ni método `set_wake_state()` — es nuevo.

### `ui/gui.py` (`JarvisMainWindow`, `GLOBAL_STATE`, `update_gui_state()`)
- `GLOBAL_STATE` es una variable de módulo (string) actualizada por `update_gui_state()`,
  consultada por polling cada 100ms desde `JarvisMainWindow._poll_state()` (via `QTimer`), que
  a su vez llama a `center_panel.set_state()` y `header_bar.set_state()`.
- No hay ningún mecanismo hoy para lanzar/detener workers en `QThreadPool` fuera de
  `ui/gui_workers.py:run_async()` (usado para `resolve()` y `execute_action()`, tareas que
  terminan solas). No existe ningún patrón existente de worker de larga duración cancelable
  (el caso de `listen_for_wake_word()` es distinto: bucle infinito que hay que poder detener).
- `closeEvent()` actualmente solo oculta la ventana a la bandeja del sistema (no termina el
  proceso) — no limpia ningún worker porque hoy no hay ninguno de larga duración. Este REQ debe
  agregar la limpieza del worker de wake word ahí (CA-09).
- No importa ni referencia `voice/wake_word.py` en ningún punto actual.

### `voice/wake_word.py` (`listen_for_wake_word()`)
- Función **bloqueante**: abre `sr.Microphone()` como context manager y corre un `while True`
  interno. Solo termina por: (a) detectar la wake word (retorna `str` con el comando extraído,
  o `True` si no había comando extra tras la wake word), o (b) `KeyboardInterrupt` (retorna
  `False`).
- **No existe ningún mecanismo de cancelación cooperativa** — ni `threading.Event` ni flag de
  parada revisado dentro del loop. Confirma el riesgo ya anotado en el contexto: agregar esta
  señal es responsabilidad de `orion-architect`/`orion-dev` en este REQ.
- Ya reporta estado a la GUI hoy, pero de forma indirecta y con manejo silencioso de errores: en
  cada iteración hace `from ui.gui import update_gui_state; update_gui_state("LISTENING")` (al
  empezar a escuchar audio) y en el `finally` de cada iteración `update_gui_state("IDLE")` —
  ambos envueltos en `try/except Exception: pass` (líneas 69-73 y 111-115) para no romper el
  flujo si la GUI no está disponible en modo headless. Esto reutiliza el estado global de 4
  valores (IDLE/LISTENING/...) — **no** el nuevo estado de 3 valores de wake word que pide la
  SPEC (inactivo/escuchando/despierto); ese es un canal nuevo a diseñar.
- No tiene ningún reporte de estado "despierto" (wake word detectada) hacia la GUI — solo
  `print()` a consola (línea 86).
- Nota de estilo: hay dos `except Exception: pass` sin logging (líneas 66-67 y 111-115, y el
  `except Exception` de `_get_whisper`/`_transcribe_whisper`) — preexistentes, no atribuibles a
  este REQ, pero relevantes si `orion-architect`/`orion-qa` deciden tocar esas rutas al agregar
  la señal de cancelación (la regla `python-style.md` prohíbe `except: pass` sin logging para
  código nuevo; el código existente no se resuelve en este REQ salvo que la arquitectura lo
  requiera para CA-10).

### `ui/cli.py` (`CLI.get_input_method()`)
- Imprime siempre las 3 opciones (`1`, `2`, `3`) sin ninguna condición. No recibe ningún
  parámetro ni consulta ningún flag de "GUI activa" — es una clase sin estado más allá de los
  métodos. Este REQ debe darle una forma de saber si la sesión corre con GUI (constructor,
  parámetro, o módulo compartido — a definir por `orion-architect`, ver "Asumido pendiente" en
  el contexto).

### `main.py` (bloque `if __name__ == "__main__":`)
- Calcula `headless = "--headless" in sys.argv` (línea 187) y, si no es headless, intenta
  levantar la GUI (`JarvisMainWindow`) en el hilo principal; si falla, cae a `headless = True`.
- El bucle del asistente (`main()`, con el CLI bloqueante) corre siempre en un hilo daemon
  separado (`jarvis_runner`, vía `threading.Thread`), independientemente de si hay GUI o no.
- Hoy `headless` es una variable local del bloque `if __main__`, **no se propaga** a
  `ui/cli.py` ni a ningún otro módulo — es exactamente el gap que señala la SPEC (CA-06/CA-07)
  y que quedó como "asumido pendiente de definición" para `orion-architect`.
- `CLI()` se instancia sin argumentos (línea 72, dentro de `main()`) — cualquier cambio de
  firma del constructor de `CLI` para pasarle el flag de GUI activa debe considerar este punto
  de instanciación.

## Archivos que serán modificados (previsión)
- `ui/widgets/center_panel.py` — agregar botón/toggle de wake word junto a `send_btn` (➤) y
  señal `hands_free_toggled(bool)`.
- `ui/widgets/header_bar.py` — agregar ícono/indicador de estado de wake word independiente de
  `_mode_pill`, y método `set_wake_state()` (o equivalente) para los 3 estados nuevos.
- `ui/gui.py` — orquestar arranque/parada del worker de wake word en background (no bloqueante),
  exponer/consumir el nuevo estado de 3 valores (probablemente variable hermana de
  `GLOBAL_STATE`, consultada por el mismo `QTimer` de 100ms en `_poll_state()`), conectar la
  señal del toggle, y limpiar el worker en `closeEvent()`.
- `voice/wake_word.py` — agregar mecanismo de cancelación cooperativa (`threading.Event` o
  flag) revisado dentro del `while True` de `listen_for_wake_word()`, y forma de reportar el
  estado de 3 valores sin romper el uso actual desde `main.py` (CLI opción "3" en headless debe
  seguir funcionando sin cambios de comportamiento observable).
- `ui/cli.py` — `get_input_method()` debe condicionar la línea `3) Modo manos libres (Wake
  Word)` según si la sesión tiene GUI activa; requiere que la clase `CLI` reciba ese dato de
  alguna forma (mecanismo a definir por `orion-architect`).
- `main.py` — propagar la señal de "GUI activa" (basada en `headless`, calculado en el bloque
  `if __name__ == "__main__":`, línea 187) hacia donde se instancia `CLI()` (línea 72, dentro de
  `main()`) para que `ui/cli.py` pueda consultarla.

## Fallos pre-existentes (no atribuibles a este REQ)
Ninguno funcional. Suite completa: **175 passed**, 3 warnings pre-existentes (sin cambios
respecto a la última corrida conocida, post-rename a Noddoo):
- `DeprecationWarning: 'aifc' is deprecated` (vía `speech_recognition/__init__.py`, dependencia
  externa).
- `DeprecationWarning: 'audioop' is deprecated` (idem, dependencia externa).
- `PytestReturnNotNoneWarning` en `tests/test_agents.py::test_ca1_orchestrator` (el test
  retorna un valor en vez de solo usar `assert`).

Compilación (`python -m py_compile`) de los 6 archivos que este REQ va a tocar: **OK**, sin
errores — `ui/widgets/center_panel.py`, `ui/widgets/header_bar.py`, `ui/gui.py`,
`voice/wake_word.py`, `ui/cli.py`, `main.py`.

Cobertura de tests existente sobre las zonas afectadas (informativo, no es un fallo):
- `tests/test_gui_widgets.py` cubre `CenterPanel` (solo el saludo, CA-03/CA-04 de REQ-008) y
  `JarvisMainWindow.closeEvent()` (CA-13 de REQ-008) — no cubre `header_bar.py`, no tiene
  ningún test del futuro toggle/estado de wake word.
- No existe ningún archivo `tests/test_wake_word.py` ni `tests/test_cli.py` — cero cobertura
  actual de `voice/wake_word.py` y `ui/cli.py`. `orion-tester` deberá crear tests nuevos para
  los criterios de aceptación de este REQ que los toquen (CA-05, CA-06, CA-07, CA-09, CA-10).
