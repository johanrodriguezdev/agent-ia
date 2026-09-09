# Baseline REQ-028 — estado del sistema antes del cambio

**Fecha:** 2026-09-08 | **Rama:** `feature/REQ-027-reasoning-loop-nativo` (commit `327defe`)

## Qué existe hoy
- `voice/wake_word.py::listen_for_wake_word()` — el bucle de escucha. Abre `sr.Microphone()`
  UNA vez (`:315`), fuera del `while True`, y no vuelve a abrirlo nunca. Es el único punto
  del sistema que toma el micrófono para wake word, y lo usan los dos caminos: la GUI
  (`ui/webview/wake_word_worker.py`) y el headless (`ui/cli.py`, opción 3).
- Estados de manos libres: `INACTIVE` / `LISTENING_WAKE` / `AWAKE`
  (`ui/webview/gui_state.py`). No existe ningún estado intermedio para "perdí el micrófono".
- Avisos al usuario: `core/notificaciones.py::notificar(titulo, mensaje, nivel)` ya llega a
  la bandeja y a la ventana, y es seguro llamarlo desde un hilo trabajador.

## Archivos que serán modificados
- `voice/wake_word.py` — el cambio real
- `ui/webview/gui_state.py` — estado nuevo
- `ui/webview/frontend/js/composer.js` — etiqueta del estado nuevo
- `tests/` — archivo nuevo de reconexión

## Fallos pre-existentes (NO los introduce este REQ)
- `tests/test_task_slots.py::test_la_hora_dicha_se_respeta` falla cualquier día después de
  las 17:00: el test depende del reloj de pared, no del código. Medido el 2026-09-08 a las
  20:39 — `1879 passed, 1 failed`.
- El resto de la suite pasa.
