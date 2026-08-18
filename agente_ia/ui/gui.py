"""
gui.py
Interfaz gráfica de escritorio "JARVIS" (REQ-008): ventana maximizada con barra de
título nativa del SO, navegación lateral, saludo dinámico, visualizador de voz central
y panel derecho con estado del sistema / accesos rápidos / actividad reciente / clima.

Reemplaza el HUD flotante `JarvisGUI(QWidget)` anterior por `JarvisMainWindow(QMainWindow)`.
Mantiene `GLOBAL_STATE`/`update_gui_state()` a nivel de módulo, sin cambios de firma ni de
import path — `main.py:154` sigue haciendo `from ui.gui import update_gui_state` igual que
antes (ver arquitectura-008.md, "Por qué mantener el polling de 100 ms").

REQ-013: la ventana pasa a orquestar la conversación (feed de burbujas, listado de
conversaciones del sidebar y persistencia de turnos) y a leer/aplicar el tema activo.
Toda la I/O de SQLite del panel sale por `run_async()`: el hilo de la GUI nunca consulta
la base (arquitectura-013.md §4.3, flujos A-E).
"""

import logging
import sys
import threading
from string import Template
from typing import List, Optional

from PyQt6.QtCore import Qt, QRunnable, QThreadPool, QTimer
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QMenu, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from config_manager import get_agent_name
from core.security_manager import ChannelType
from ui.gui_workers import run_async
from ui.theme import Palette, qss_tokens, register_themed, theme_manager
from ui.widgets.center_panel import CenterPanel
from ui.widgets.header_bar import HeaderBar
from ui.widgets.right_panel import RightPanel
from ui.widgets.sidebar import Sidebar

logger = logging.getLogger(__name__)

# REQ-013: tamaño de página del listado de conversaciones del sidebar.
_CONVERSATION_PAGE_SIZE = 30

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
        # REQ-013: `None` = conversación nueva todavía sin acuñar; el id se materializa
        # recién cuando se persiste el primer turno (CA-07).
        self._conversation_id: Optional[str] = None
        self._pending_user_text: str = ""
        self._pending_conversation_offset: int = 0
        # REQ-013/CA-02: el tema se carga ANTES de construir los widgets — cada uno se
        # autorregistra en su __init__ y arranca ya con la paleta correcta, sin parpadeo.
        theme_manager.load_from_config()
        self._init_ui()
        self._reload_conversations()

    def _init_ui(self) -> None:
        self.setWindowTitle(f"{self._agent_name} — Panel de control")
        self.setMinimumSize(1024, 640)

        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = Sidebar()
        # "Inicio" y "Conversaciones" apuntan a la única vista existente; su selección no
        # requiere acción porque ya es la vista mostrada (los otros 5 ítems siguen
        # deshabilitados — ver ui/widgets/sidebar.py). REQ-013: la lista de conversaciones
        # del sidebar sí está cableada.
        self.sidebar.conversation_selected.connect(self._on_conversation_selected)
        self.sidebar.new_conversation_requested.connect(self._on_new_conversation)
        self.sidebar.more_requested.connect(self._on_more_conversations)
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

        register_themed(self)

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
        red/Claude).

        REQ-013/CA-13: la burbuja del usuario se pinta ANTES de lanzar la resolución, para
        que el envío se sienta inmediato aunque `resolve()` tarde.

        REQ-013 (3ra pasada)/CA-09: `_pending_user_text` es un slot único — si un segundo
        comando se enviara antes de que este resuelva, pisaría el texto y `store_turn()`
        persistiría una atribución user/assistant incorrecta (ver qa-audit-013.md). Se
        deshabilita el composer aquí y se reactiva recién en `_on_command_done()`/
        `_on_command_error()`, así que solo puede haber una resolución en vuelo a la vez —
        la condición de carrera queda eliminada por construcción, no oculta.
        """
        from core.resolution import resolve

        self.center_panel.add_user_message(text)
        self._pending_user_text = text
        self.center_panel.set_input_enabled(False)
        run_async(resolve, self._on_command_done, self._on_command_error, text, ChannelType.DESKTOP,
                  user_id="default")

    def _on_command_done(self, resolution) -> None:
        """REQ-013/CA-14, CA-09 — muestra la respuesta y persiste el turno completo.

        La persistencia va por `run_async` sin callbacks: `store_turn()` calcula DOS
        embeddings y hasta REQ-013 el `memory.store()` equivalente corría en el hilo de la
        GUI, congelando la ventana. Los errores quedan logueados dentro de
        `CallableWorker.run()`, así que no se pierde diagnóstico.
        """
        from ai.memory_manager import memory

        result_text = resolution.text
        self.center_panel.show_response(result_text)

        conversation_id = self._ensure_conversation_id()
        run_async(
            memory.store_turn,
            None,
            None,
            self._pending_user_text,
            result_text,
            conversation_id,
            user_id="default",
            matched_by=getattr(resolution, "matched_by", ""),
        )
        self._pending_user_text = ""
        # REQ-013 (3ra pasada)/CA-09: recién acá se reactiva el composer — mientras
        # `_pending_user_text` no se haya leído para este `store_turn()`, ningún segundo
        # comando puede pisarlo (ver `_handle_command`).
        self.center_panel.set_input_enabled(True)
        self._reload_conversations()

    def _on_command_error(self, message: str) -> None:
        """Muestra el error en el feed y NO persiste el turno: un error no es una respuesta
        de la IA, y guardarlo ensuciaría el historial y la memoria semántica."""
        self.center_panel.show_response(f"Error: {message}")
        self._pending_user_text = ""
        # REQ-013 (3ra pasada)/CA-09: reactivar también en el camino de error — si no, un
        # error dejaría el composer bloqueado para siempre.
        self.center_panel.set_input_enabled(True)

    # ------------------------------------------------------------ conversaciones
    def _ensure_conversation_id(self) -> str:
        """REQ-013/CA-07 — acuña el id de la conversación nueva en su primer turno."""
        from ai.memory_manager import memory

        if not self._conversation_id:
            self._conversation_id = memory.new_conversation_id()
        return self._conversation_id

    def _reload_conversations(self, offset: int = 0) -> None:
        """REQ-013/CA-05 — recarga el listado del sidebar SIEMPRE fuera del hilo de la GUI.

        Con `offset > 0` agrega una página al final (botón "Ver más") en vez de reemplazar
        lo mostrado.
        """
        from ai.memory_manager import memory

        self._pending_conversation_offset = offset
        run_async(
            memory.list_conversations,
            self._on_conversations_loaded,
            self._on_conversations_error,
            user_id="default",
            limit=_CONVERSATION_PAGE_SIZE,
            offset=offset,
        )

    def _on_conversations_loaded(self, conversations: List) -> None:
        append = bool(self._pending_conversation_offset)
        self.sidebar.set_conversations(conversations, append=append)
        self.sidebar.set_has_more(len(conversations) == _CONVERSATION_PAGE_SIZE)
        self.sidebar.set_active_conversation(self._conversation_id)

    def _on_conversations_error(self, message: str) -> None:
        logger.error(f"No se pudo cargar el listado de conversaciones: {message}")

    def _on_more_conversations(self) -> None:
        self._reload_conversations(offset=self.sidebar.conversation_count())

    def _on_conversation_selected(self, conversation_id: str) -> None:
        """REQ-013/CA-06 — abre en el feed una conversación existente."""
        from ai.memory_manager import memory

        self._conversation_id = conversation_id
        run_async(
            memory.get_conversation_turns,
            self._on_turns_loaded,
            self._on_turns_error,
            conversation_id,
            user_id="default",
        )

    def _on_turns_loaded(self, turns: List) -> None:
        self.center_panel.load_turns(turns)
        self.sidebar.set_active_conversation(self._conversation_id)

    def _on_turns_error(self, message: str) -> None:
        logger.error(f"No se pudo cargar la conversación: {message}")
        self.center_panel.show_response(f"Error: {message}")

    def _on_new_conversation(self) -> None:
        """REQ-013/CA-07 — vacía el feed sin borrar nada; el id se acuña con el primer
        mensaje, de modo que dos clics seguidos no dejan conversaciones fantasma."""
        self._conversation_id = None
        self._pending_user_text = ""
        self.center_panel.clear_feed()
        self.sidebar.set_active_conversation(None)

    def apply_theme(self, palette: Palette) -> None:
        """REQ-013/CA-01 — fondo de la ventana; cada widget hijo se reestiliza por su cuenta."""
        self.setStyleSheet(_qss(palette))

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


# REQ-013: `string.Template` con `$token`, NUNCA `str.format()` (ver `ui/theme.py`).
_QSS_TEMPLATE = Template("""
QMainWindow { background-color: $bg_window; }
QToolTip { color: $text_primary; background-color: $bg_elevated; border: 1px solid $border; }
""")


def _qss(palette: Palette) -> str:
    return _QSS_TEMPLATE.substitute(qss_tokens(palette))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = JarvisMainWindow()
    window.showMaximized()
    sys.exit(app.exec())
