"""
gui.py
Interfaz gráfica de escritorio "JARVIS" (REQ-008): ventana maximizada con barra de
título nativa del SO, navegación lateral, saludo dinámico, visualizador de voz central
y panel derecho con estado del sistema / accesos rápidos / actividad reciente / clima.

Reemplaza el HUD flotante `JarvisGUI(QWidget)` anterior por `JarvisMainWindow(QMainWindow)`.
Mantiene `GLOBAL_STATE`/`update_gui_state()` a nivel de módulo, sin cambios de firma ni de
import path — `main.py:154` sigue haciendo `from ui.gui import update_gui_state` igual que
antes (ver arquitectura-008.md, "Por qué mantener el polling de 100 ms").
"""

import logging
import sys
import threading

from PyQt6.QtCore import Qt, QRunnable, QThreadPool, QTimer
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QMenu, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from config_manager import get_agent_name
from core.security_manager import ChannelType
from ui.gui_workers import run_async
from ui.widgets.center_panel import CenterPanel
from ui.widgets.header_bar import HeaderBar
from ui.widgets.right_panel import RightPanel
from ui.widgets.sidebar import Sidebar

logger = logging.getLogger(__name__)

# Variable Global Hilo-Segura compartida con la logica background
GLOBAL_STATE = "IDLE"

# REQ-009: canal de estado del modo manos libres (wake word), independiente de
# GLOBAL_STATE — nunca se pisan ni se confunden (CA-02). Valores: "INACTIVE" /
# "LISTENING_WAKE" / "AWAKE".
WAKE_STATE = "INACTIVE"


def update_gui_state(new_state: str):
    global GLOBAL_STATE
    GLOBAL_STATE = new_state


def update_wake_state(new_state: str):
    global WAKE_STATE
    WAKE_STATE = new_state


class WakeWordWorker(QRunnable):
    """REQ-009/CA-03, CA-05, CA-09, CA-10 — corre `listen_for_wake_word()` (bloqueante) en
    un hilo de `QThreadPool`, en loop hasta parada cooperativa o excepción.

    `self.stop_event` es un `threading.Event` seguro entre hilos: `JarvisMainWindow`
    lo setea desde el hilo principal para pedir la parada (best-effort, ~6-7s de
    latencia); este worker lo revisa indirectamente vía `listen_for_wake_word()`, que
    retorna `None` cuando fue señalado.
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


class JarvisMainWindow(QMainWindow):
    """Ventana principal "JARVIS". Barra de título nativa (sin `FramelessWindowHint`),
    abierta con `showMaximized()` desde `main.py` (CA-01)."""

    def __init__(self):
        super().__init__()
        self._current_state = "IDLE"
        self._current_wake_state = "INACTIVE"
        self._wake_worker: WakeWordWorker | None = None
        self._agent_name = get_agent_name().upper()
        self._init_ui()

    def _init_ui(self) -> None:
        self.setWindowTitle(f"{self._agent_name} — Panel de control")
        self.setMinimumSize(1024, 640)

        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = Sidebar()
        # "Inicio" es la única vista existente en este REQ; su selección no requiere
        # ninguna acción porque ya es la vista mostrada (los otros 6 ítems están
        # deshabilitados — ver ui/widgets/sidebar.py).
        root_layout.addWidget(self.sidebar)

        center_column = QVBoxLayout()
        center_column.setContentsMargins(0, 0, 0, 0)
        center_column.setSpacing(0)

        self.header_bar = HeaderBar()
        center_column.addWidget(self.header_bar)

        self.center_panel = CenterPanel()
        self.center_panel.command_submitted.connect(self._handle_command)
        self.center_panel.hands_free_toggled.connect(self._on_hands_free_toggled)
        center_column.addWidget(self.center_panel, 1)

        root_layout.addLayout(center_column, 1)

        self.right_panel = RightPanel()
        root_layout.addWidget(self.right_panel)

        self.setStyleSheet("QMainWindow { background-color: #070b14; }")

        self._state_poll = QTimer(self)
        self._state_poll.timeout.connect(self._poll_state)
        self._state_poll.start(100)

        self._setup_tray_icon()

    def _poll_state(self) -> None:
        global GLOBAL_STATE, WAKE_STATE
        if self._current_state != GLOBAL_STATE:
            self._current_state = GLOBAL_STATE
            self.center_panel.set_state(self._current_state)
            self.header_bar.set_state(self._current_state)

        if self._current_wake_state != WAKE_STATE:
            self._current_wake_state = WAKE_STATE
            self.center_panel.set_wake_state(self._current_wake_state)
            self.header_bar.set_wake_state(self._current_wake_state)
            if self._current_wake_state == "INACTIVE":
                # REQ-009: el worker (si lo había) ya terminó su ciclo — liberar la
                # referencia para permitir un nuevo ON (ver mitigación de doble clic).
                self._wake_worker = None

    def _on_hands_free_toggled(self, checked: bool) -> None:
        """REQ-009/CA-03, CA-05 — enciende/apaga el modo manos libres desde la GUI."""
        if checked:
            if self._wake_worker is not None:
                # Ya hay un worker activo (incluso deteniéndose) — ignorar el clic para
                # evitar dos WakeWordWorker compitiendo por sr.Microphone() (caso borde
                # de doble clic de SPEC-009).
                return
            self._wake_worker = WakeWordWorker()
            QThreadPool.globalInstance().start(self._wake_worker)
        else:
            self._stop_wake_word_worker()

    def _stop_wake_word_worker(self) -> None:
        """REQ-009/CA-05, CA-09 — pide parada cooperativa (best-effort) del worker activo."""
        if self._wake_worker is not None:
            self._wake_worker.stop_event.set()

    def _handle_command(self, text: str) -> None:
        """CA-12: la barra de comando reutiliza `core/resolution.py:resolve()` — nunca se
        llama directo desde el hilo de la GUI, siempre vía `run_async()` (puede implicar
        red/Claude)."""
        from core.resolution import resolve

        run_async(resolve, self._on_command_done, self._on_command_error, text, ChannelType.DESKTOP,
                  user_id="default")

    def _on_command_done(self, resolution) -> None:
        result_text = resolution.text
        self.center_panel.show_response(result_text)
        from ai.memory_manager import memory
        memory.store(f"{resolution.matched_by} | {result_text}", category="interaction")

    def _on_command_error(self, message: str) -> None:
        self.center_panel.show_response(f"Error: {message}")

    def _setup_tray_icon(self) -> None:
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(0, 100, 255))
        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip(f"{self._agent_name} — Panel de control")

        menu = QMenu()
        show_action = menu.addAction("Mostrar/Ocultar")
        show_action.triggered.connect(self._toggle_visible)
        quit_action = menu.addAction("Salir")
        quit_action.triggered.connect(QApplication.instance().quit)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

        # REQ-009/CA-09: cierre real del proceso (menú de bandeja "Salir") pide la parada
        # cooperativa del worker de wake word, si estaba activo. Best-effort, no bloquea
        # el quit() (ver arquitectura-009.md, "Limpieza del worker... no en closeEvent").
        QApplication.instance().aboutToQuit.connect(self._stop_wake_word_worker)

    def _toggle_visible(self) -> None:
        self.setVisible(not self.isVisible())

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_visible()

    def closeEvent(self, event) -> None:
        """CA-13: portado sin cambios de comportamiento respecto al `JarvisGUI` anterior —
        cerrar minimiza a la bandeja en vez de terminar el proceso."""
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "Noddoo",
            "Continuo ejecutándome en segundo plano.",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = JarvisMainWindow()
    window.showMaximized()
    sys.exit(app.exec())
