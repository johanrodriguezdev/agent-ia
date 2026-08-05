# SPEC-009 — Control de modo manos libres (wake word) en la GUI JARVIS

**Estado:** ✅ COMPLETADO (aprobada por Johan, 2026-08-05)
**Categoría:** UI
**Tipo:** FEATURE_NUEVA
**Fecha:** 2026-08-05

## Objetivo
Agregar a la GUI JARVIS (REQ-008) un control para activar/desactivar el modo manos libres
(wake word) con feedback visual de su estado, hoy solo accesible desde la opción "3" del menú
bloqueante de `ui/cli.py`. El objetivo es que el usuario pueda encender/apagar la escucha
pasiva del wake word desde la GUI, viendo en todo momento si Nodo está escuchando o si detectó
la palabra de activación — sin necesidad de usar el CLI.

## Alcance
- Incluye:
  - Un control tipo toggle (encender/apagar) en el `CenterPanel`, junto a la barra de comando.
  - Un ícono de estado en el `HeaderBar`, separado de la píldora de estado existente
    (IDLE/LISTENING/PROCESSING/RESPONDING), que refleja el estado del modo manos libres.
  - 3 estados visuales: **inactivo** / **escuchando wake word** / **despierto** (wake word
    detectado).
  - Ejecución de `listen_for_wake_word()` en background (sin congelar la GUI), con una señal de
    parada cooperativa nueva en `voice/wake_word.py` para poder apagar el modo desde el toggle.
  - Ocultar la opción "3" del menú de `ui/cli.py::get_input_method()` cuando la sesión corre con
    GUI activa (no headless).
- No incluye:
  - Encadenar automáticamente la captura de un comando de voz después de detectar el wake word,
    ni enviarlo a `core/resolution.py:resolve()`. El ciclo de este REQ termina en "Nodo detectó
    el wake word y lo refleja visualmente" — la ejecución de la orden queda para un REQ
    posterior.
  - Feedback sonoro (TTS/`speak()`) al encender/apagar el toggle desde la GUI — es puramente
    visual.
  - Eliminar código de `ui/cli.py` ni de `voice/wake_word.py` relacionado al modo manos libres
    del CLI — en modo `--headless` (sin GUI) la opción "3" sigue funcionando exactamente igual
    que hoy.
  - Un 4to estado visual dedicado a errores (mic no disponible / permiso denegado). Ver
    "Casos borde" para el comportamiento mínimo esperado en ese caso.

## Módulos afectados
- `ui/widgets/center_panel.py` — nuevo botón toggle de modo manos libres junto al botón de
  enviar (➤) de la barra de comando; expone una señal (p. ej. `hands_free_toggled(bool)`).
- `ui/widgets/header_bar.py` — nuevo ícono/indicador de estado de modo manos libres,
  independiente de la píldora "Modo activo" existente; método `set_wake_state()` (o
  equivalente) para reflejar los 3 estados.
- `ui/gui.py` — orquesta el toggle: arranca/detiene el listener en background (vía
  `QThreadPool`/worker, no bloqueante), mantiene el nuevo estado de 3 valores accesible por
  polling (mismo mecanismo de `GLOBAL_STATE`/`QTimer` de 100ms, o una variable hermana
  dedicada), y limpia el worker al cerrar la ventana (`closeEvent`).
- `voice/wake_word.py` — agrega un mecanismo de cancelación cooperativa (flag/`threading.Event`)
  revisado dentro del `while True` de `listen_for_wake_word()`, y una forma de reportar el nuevo
  estado de 3 valores sin romper el uso actual desde `main.py` (CLI opción "3" en modo headless
  debe seguir funcionando sin cambios).
- `ui/cli.py` — `get_input_method()` condiciona si imprime la línea `3) Modo manos libres (Wake
  Word)` según si la GUI está activa en la sesión.
- `main.py` — expone/propaga la señal de "GUI activa" (basada en el `headless` que ya se calcula
  en el bloque `if __name__ == "__main__":`) para que `ui/cli.py` pueda consultarla.

## Comportamiento actual vs deseado
| Actual | Deseado |
|--------|---------|
| El modo manos libres solo se activa eligiendo "3" en el prompt bloqueante del CLI. | Se puede activar/desactivar también desde un toggle visual en la GUI, sin usar el CLI. |
| No hay ningún indicador visual de que Nodo está escuchando el wake word desde la GUI. | Un ícono en el `HeaderBar` (y el propio estado del toggle en `CenterPanel`) muestra si el modo está inactivo, escuchando, o si detectó el wake word. |
| `listen_for_wake_word()` no tiene forma de cancelarse salvo `KeyboardInterrupt`. | Existe una señal de parada cooperativa que el toggle de la GUI puede usar para apagar el modo (best-effort, hasta ~6s de latencia). |
| La opción "3" del CLI aparece siempre, incluso corriendo con GUI. | La opción "3" se oculta del menú del CLI cuando la sesión corre con GUI activa (para evitar dos caminos compitiendo por `sr.Microphone()`); en `--headless` sigue igual que hoy. |

## Criterios de aceptación
- [ ] CA-01: El `CenterPanel` muestra un botón/toggle de modo manos libres junto al botón ➤,
      visible desde el arranque de la GUI, en estado inicial "inactivo" (OFF).
- [ ] CA-02: El `HeaderBar` muestra un ícono/indicador de estado del modo manos libres,
      separado visualmente de la píldora "Modo activo" existente (IDLE/LISTENING/PROCESSING/
      RESPONDING no se pisan ni se confunden con este nuevo indicador).
- [ ] CA-03: Al hacer clic en el toggle estando OFF, el modo manos libres pasa a ON: (a) la GUI
      no se congela ni deja de responder mientras el listener corre en background, (b) el ícono
      del `HeaderBar` y el estado del toggle cambian a "escuchando wake word".
- [ ] CA-04: Al detectarse el wake word mientras el modo está ON, el indicador cambia a
      "despierto"; inmediatamente después el sistema retoma automáticamente la escucha del wake
      word (vuelve a "escuchando") sin ejecutar ni resolver ningún comando — `resolve()` no se
      invoca como resultado de este ciclo.
- [ ] CA-05: Al hacer clic en el toggle estando ON, el modo pasa a OFF: el listener en background
      se detiene de forma best-effort (latencia esperada de hasta ~6s, coherente con
      `timeout=1`/`phrase_time_limit=6` de `recognizer.listen()`), y el indicador vuelve a
      "inactivo".
- [ ] CA-06: Corriendo la GUI (modo no headless), el menú de `ui/cli.py::get_input_method()` no
      imprime/ofrece la opción "3) Modo manos libres (Wake Word)".
- [ ] CA-07: Corriendo en modo `--headless` (sin GUI), el menú del CLI sigue mostrando y
      funcionando la opción "3" exactamente igual que antes de este REQ (sin regresión).
- [ ] CA-08: Encender o apagar el toggle desde la GUI no dispara ningún `speak()`/TTS — el
      cambio es puramente visual.
- [ ] CA-09: Cerrar la ventana de la GUI mientras el modo manos libres está ON no deja el
      proceso colgado ni lanza excepciones no manejadas — el worker en background se detiene
      como parte del cierre.
- [ ] CA-10: Si `listen_for_wake_word()` falla (p. ej. `sr.Microphone()` no disponible o
      permiso de micrófono denegado) mientras el modo está ON, el error se registra por
      `logging` (no se silencia con `except: pass`), el toggle vuelve a "inactivo" y la GUI
      sigue usable (no crashea).

## Casos borde
- Doble clic rápido sobre el toggle (encender/apagar en sucesión inmediata): no debe disparar
  dos listeners en paralelo ni dejar el estado inconsistente.
- Cierre de la ventana GUI con el modo manos libres activo: el worker en background debe
  detenerse como parte del cierre (ver CA-09), sin excepción no manejada ni hilo huérfano
  bloqueando la salida del proceso.
- Micrófono no disponible o permiso denegado al intentar activar el toggle: no debe crashear la
  GUI; vuelve a "inactivo" con el error logueado (ver CA-10). No se implementa un 4to estado
  visual dedicado a esto en este REQ (confirmado por Johan — ver "Asumidos").
- Fallos repetidos de reconocimiento (`sr.RequestError` u otra excepción no esperada dentro del
  loop de `listen_for_wake_word()`): no deben dejar el toggle "trabado" en estado ON sin forma
  de apagarlo desde la GUI.
- Ejecución en `--headless` (sin GUI): el comportamiento de la opción "3" del CLI debe quedar
  bit a bit igual al actual — este REQ no debe introducir ninguna regresión en ese camino.

## Asumidos
- ASUMIDO: 3 estados visuales (inactivo / escuchando wake word / despierto), sin un 4to estado
  dedicado a errores — aplicado como default razonable por la sesión orquestadora, no se le
  presentó a Johan como pregunta con opciones estructuradas. Confirmar antes de implementar; si
  lo objeta, es un ajuste menor de UI, no bloqueante para el resto de la SPEC.
- ASUMIDO: sin feedback sonoro (TTS) al encender/apagar el toggle desde la GUI — mismo caso que
  el punto anterior (default aplicado, no confirmado con opciones estructuradas). Confirmar antes
  de implementar.
- ASUMIDO: la señal de "GUI activa" para condicionar la opción "3" del CLI se deriva del mismo
  flag `headless` que ya calcula `main.py` en su bloque `if __name__ == "__main__":` — el
  mecanismo concreto para propagarlo a `ui/cli.py` (parámetro, atributo de módulo compartido,
  etc.) queda a definición de `orion-architect`.
