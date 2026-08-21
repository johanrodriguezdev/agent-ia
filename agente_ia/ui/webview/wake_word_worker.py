"""
ui/webview/wake_word_worker.py
`WakeWordWorker(QRunnable)` — mismo diseño exacto que el `WakeWordWorker` de `ui/gui.py`
(REQ-009, eliminado en REQ-015): mismo `stop_event`, mismo `try/finally` con
`update_wake_state("INACTIVE")`. Cero cambios de comportamiento observable respecto al
mecanismo actual (arquitectura-015.md §0.4) — solo cambia de dónde importa
`update_wake_state` (`ui.webview.gui_state`, no `ui.gui`).

`voice/wake_word.py` (prohibido tocar) no se modifica una línea: se le sigue pasando
`wake_state_callback=update_wake_state` explícitamente, con lo que su rama de import de
`ui.gui` (solo alcanzable cuando `wake_state_callback is None`) nunca se ejecuta.
"""

import logging
import threading

from PyQt6.QtCore import QRunnable

from ui.webview.gui_state import update_wake_state

logger = logging.getLogger(__name__)


class WakeWordWorker(QRunnable):
    """REQ-009/CA-03, CA-05, CA-09, CA-10 — corre `listen_for_wake_word()` (bloqueante) en
    un hilo de `QThreadPool`, en loop hasta parada cooperativa o excepción.

    `self.stop_event` es un `threading.Event` seguro entre hilos: `MainWindow` lo setea
    desde el hilo principal para pedir la parada (best-effort, ~6-7s de latencia); este
    worker lo revisa indirectamente vía `listen_for_wake_word()`, que retorna `None`
    cuando fue señalado.
    """

    def __init__(self):
        super().__init__()
        self.stop_event = threading.Event()

    def run(self) -> None:
        from voice.wake_word import listen_for_wake_word

        try:
            while not self.stop_event.is_set():
                update_wake_state("LISTENING_WAKE")
                result = listen_for_wake_word(
                    stop_event=self.stop_event, wake_state_callback=update_wake_state
                )
                if result is None:
                    # Parada cooperativa (stop_event) o KeyboardInterrupt (False también
                    # sale del loop para no dejar el toggle "trabado" en ON).
                    break
                if result is False:
                    break
        except Exception as e:
            logger.error(f"Error en WakeWordWorker (listen_for_wake_word): {e}")
        finally:
            update_wake_state("INACTIVE")
