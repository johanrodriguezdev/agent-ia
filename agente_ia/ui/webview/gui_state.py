"""
ui/webview/gui_state.py
Estado puro compartido entre el hilo de la GUI y los hilos trabajadores (REQ-015/§0.4).

Reemplaza a `ui/gui.py::GLOBAL_STATE`/`WAKE_STATE` en un path nuevo — deliberadamente NO
`ui/gui.py` (la SPEC exige eliminar ese archivo por completo, ver arquitectura-015.md
§0.4 y "Descartado" en REQ-015-context.md). Cero imports de PyQt/Qt: este módulo es texto
plano, testeable con `pytest` puro, sin necesidad de `qtbot`/offscreen.

`ui/webview/main_window.py::MainWindow` pollea estas dos variables con un `QTimer` (mismo
mecanismo de polling de 100ms ya validado en REQ-008/REQ-009 — `listen_for_wake_word()`
corre en un hilo `QRunnable` fuera del control de señales Qt, así que no hay alternativa
mejor) y emite los cambios por el bridge (`gui_state_changed`/`wake_state_changed`) para
que JS actualice el DOM.

`main.py:154` importa `update_gui_state` de este módulo (antes: `ui.gui`), envuelto en el
mismo `try/except Exception` defensivo que ya existía.
"""

import logging

logger = logging.getLogger(__name__)

# Variable global hilo-segura compartida con la lógica de fondo (REQ-008).
# Valores: "IDLE" | "LISTENING" | "PROCESSING" | "RESPONDING".
GLOBAL_STATE = "IDLE"

# REQ-009: canal de estado del modo manos libres (wake word), independiente de
# GLOBAL_STATE — nunca se pisan ni se confunden. Valores: "INACTIVE" / "LISTENING_WAKE" /
# "AWAKE".
WAKE_STATE = "INACTIVE"


def update_gui_state(new_state: str) -> None:
    global GLOBAL_STATE
    GLOBAL_STATE = new_state


def update_wake_state(new_state: str) -> None:
    global WAKE_STATE
    WAKE_STATE = new_state
