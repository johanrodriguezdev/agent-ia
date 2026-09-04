"""
ui/webview/main_window.py
`MainWindow(QMainWindow)` — shell frameless con un único `QWebEngineView` a pantalla
completa (REQ-015/CA-01..CA-05, arquitectura-015.md §2, §5.1, §5.3, §5.4).

Reemplaza a `JarvisMainWindow` (REQ-008/013, eliminado en `ui/gui.py`). El árbol de
widgets Qt visible se reduce a UNO SOLO: la ventana top-level frameless con el
`QWebEngineView` — no hay ningún otro `QWidget` con estilo propio en el medio que pueda
repetir el bug de bleed-through de REQ-014 (ver arquitectura-015.md §5.1).

`fit_size_to_screen()` se llama ANTES de `show()` (que lo invoca `main.py`, no esta
clase) — nunca `showMaximized()` (§5.1, evita los márgenes extra que DWM añade en
maximizado+frameless en Windows).
"""

import json
import logging
import os

from PyQt6.QtCore import QEvent, Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
from PyQt6.QtWebEngineWidgets import QWebEngineView

from config_manager import get_agent_name
from core.confirmation import register_confirmation_adapter
from core.security_manager import ChannelType
from ui.webview.bridge import Bridge
from ui.webview.confirmation_adapter import WebViewConfirmationAdapter
from ui.webview.file_drop import validate_dropped_file
from ui.webview.window_geometry import fit_size_to_screen

logger = logging.getLogger(__name__)

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")
_INDEX_HTML = os.path.join(_FRONTEND_DIR, "index.html")
_ERROR_HTML = os.path.join(_FRONTEND_DIR, "error.html")

_STATE_POLL_INTERVAL_MS = 100  # mismo intervalo que el polling de REQ-008/009


class _LoggingWebEnginePage(QWebEnginePage):
    """§5.4 — errores de JS no capturados se loguean, nunca se silencian ni se muestran
    como diálogo nativo (que rompería la estética frameless)."""

    def javaScriptConsoleMessage(self, level, message, line_number, source_id) -> None:
        logger.debug(f"[JS console] {source_id}:{line_number} — {message}")


class MainWindow(QMainWindow):
    """Ventana principal WebView. Frameless, `QWebEngineView` a pantalla completa, tray,
    drag&drop nativo de archivos (CA-23)."""

    def __init__(self):
        super().__init__()
        self._agent_name = get_agent_name().upper()
        self._wake_worker_ref_owner = None  # ver Bridge — el worker vive en el Bridge

        self.setWindowTitle(f"{self._agent_name} — Panel de control")
        # CA-01: sin barra de título nativa — los 3 controles (min/max/cerrar) se dibujan
        # enteramente en CSS/HTML dentro del WebView.
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        # CA-01/CA-03: fondo transparente a nivel de ventana — el compositor del SO deja
        # ver el escritorio fuera del rectángulo con esquinas redondeadas que dibuja el
        # CSS. Sin esto, la ventana quedaría con un rectángulo opaco detrás del contenido
        # con esquinas redondeadas (una variante nueva del bug de bleed-through de REQ-014).
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(1024, 640)

        self._init_web_view()
        self._init_bridge()
        self._fit_to_screen()
        self._setup_tray_icon()
        self._setup_state_polling()

        self.setAcceptDrops(True)
        self.web_view.installEventFilter(self)

    # ------------------------------------------------------------ construcción
    def _init_web_view(self) -> None:
        self.web_view = QWebEngineView(self)
        page = _LoggingWebEnginePage(self.web_view)
        self.web_view.setPage(page)
        self._inject_agent_name_script(page)

        # Ver comentario de WA_TranslucentBackground arriba — mismo motivo, ahora a nivel
        # del propio widget/página, para que el área fuera del contenido pintado por CSS
        # también sea transparente y no un rectángulo blanco/negro sólido (CA-03).
        self.web_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        page.setBackgroundColor(QColor(Qt.GlobalColor.transparent))

        self.setCentralWidget(self.web_view)

        self.web_view.loadFinished.connect(self._on_load_finished)
        page.renderProcessTerminated.connect(self._on_render_process_terminated)

        self.web_view.load(QUrl.fromLocalFile(_INDEX_HTML))

    def _inject_agent_name_script(self, page) -> None:
        """CA-46: el avatar del estado vacío y la etiqueta de la barra de título muestran
        la inicial/nombre del agente (`get_agent_name()`). Se inyecta como variable
        global ANTES de que corra cualquier script de la página — un valor estático que
        no cambia en caliente no justifica ampliar el contrato de `Bridge` (§4) con un
        slot/señal nuevo solo para esto (ver desarrollo-log-015.md)."""
        script = QWebEngineScript()
        script.setName("orion-agent-name")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        escaped = get_agent_name().replace("\\", "\\\\").replace('"', '\\"')
        script.setSourceCode(f'window.__ORION_AGENT_NAME__ = "{escaped}";')
        page.scripts().insert(script)

    def _init_bridge(self) -> None:
        self.bridge = Bridge(self, self)
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        # §4.3: se construye y registra RECIÉN ACÁ (no a nivel de módulo como hace
        # `main.py` con el adaptador de consola) — si `MainWindow()` falla en construirse
        # (modo headless), el adaptador de consola registrado al importar `main.py` sigue
        # siendo el activo, sin cambio de comportamiento.
        self._confirmation_adapter = WebViewConfirmationAdapter(self.bridge)
        self.bridge.set_confirmation_adapter(self._confirmation_adapter)
        register_confirmation_adapter(ChannelType.DESKTOP, self._confirmation_adapter.confirm)

        # Renombrar al agente desde Configuración se aplica sin reiniciar: el título de la
        # ventana y la bandeja son los dos lugares que el frontend no puede repintar.
        self.bridge.profile_saved.connect(self._on_profile_saved)

    def _on_profile_saved(self, payload_json: str) -> None:
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as e:
            logger.error(f"perfil guardado con JSON inválido, no se renombró la ventana: {e}")
            return
        self._agent_name = str(payload.get("agent_name", self._agent_name)).upper()
        self.setWindowTitle(f"{self._agent_name} — Panel de control")
        if getattr(self, "tray_icon", None) is not None:
            self.tray_icon.setToolTip(f"{self._agent_name} — Panel de control")

    def _fit_to_screen(self) -> None:
        """CA-04 — clampea siempre contra el área de trabajo disponible (excluye la
        barra de tareas), llamado ANTES de `show()` (que invoca `main.py`, no esta
        clase)."""
        screen = QApplication.primaryScreen()
        if screen is None:
            logger.warning("fit_to_screen(): sin pantalla primaria detectada, se omite")
            return
        available = screen.availableGeometry()
        width, height, x, y = fit_size_to_screen(
            (available.x(), available.y(), available.width(), available.height())
        )
        self.setGeometry(x, y, width, height)

    def _setup_state_polling(self) -> None:
        self._state_poll = QTimer(self)
        self._state_poll.timeout.connect(self.bridge.poll_state)
        self._state_poll.start(_STATE_POLL_INTERVAL_MS)

    def _setup_tray_icon(self) -> None:
        """Portado casi textual desde `JarvisMainWindow._setup_tray_icon()` (REQ-008/009,
        eliminado) — independiente del tipo de `centralWidget()` (CA-43)."""
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

        # REQ-009/CA-09: pide la parada cooperativa del worker de wake word (si estaba
        # activo) al cierre real del proceso — best-effort, no bloquea el quit().
        QApplication.instance().aboutToQuit.connect(self.bridge.stop_wake_word_worker)

        # Igual con las terminales embebidas: si el proceso termina, los shells que abrió
        # el panel se terminan con él. Una shell viva sin ventana que la muestre es
        # exactamente lo que el gate de `terminal_open` intenta evitar.
        QApplication.instance().aboutToQuit.connect(self._close_terminal)

    def _close_terminal(self) -> None:
        """Best-effort: nunca bloquea el quit()."""
        try:
            from core.terminal_session import terminal_manager

            terminal_manager.close_all()
        except Exception as e:
            logger.warning(f"no se pudo cerrar la terminal al salir: {e}")

    def _toggle_visible(self) -> None:
        self.setVisible(not self.isVisible())

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_visible()

    # ------------------------------------------------------------ ciclo de vida del WebView (§5.4)
    def _on_load_finished(self, ok: bool) -> None:
        if ok:
            return
        logger.error("Fallo al cargar index.html en el WebView — cargando error.html")
        self.web_view.load(QUrl.fromLocalFile(_ERROR_HTML))

    def _on_render_process_terminated(self, termination_status, exit_code) -> None:
        """El proceso de renderizado de Chromium es un proceso SEPARADO del proceso
        Python — un crash ahí no puede tumbar el proceso Python (§5.4)."""
        logger.error(
            f"Proceso de renderizado de Chromium terminado (status={termination_status}, "
            f"exit_code={exit_code}) — recargando"
        )
        self.web_view.load(QUrl.fromLocalFile(_INDEX_HTML))

    def changeEvent(self, event) -> None:
        """El gutter transparente y las esquinas redondeadas de `#app-shell` (layout.css)
        solo tienen sentido en tamaño normal: maximizado dejaban un borde visible que
        impedía que la app se viera a pantalla completa. El frontend necesita saber el
        estado para anularlos, y `showMaximized()` no es el único camino (Win+↑, doble
        click en la barra), por eso se escucha el cambio de estado de la ventana."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.bridge.window_maximized_changed.emit(self.isMaximized())

    def closeEvent(self, event) -> None:
        """CA-01 — portado sin cambios de comportamiento: cerrar minimiza a la bandeja en
        vez de terminar el proceso (idéntico a `JarvisMainWindow.closeEvent()`)."""
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            self._agent_name,
            "Continuo ejecutándome en segundo plano.",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )

    # ------------------------------------------------------------ drag & drop nativo (CA-23, §5.3)
    def eventFilter(self, obj, event) -> bool:
        """Intercepta el drop nativo sobre el `QWebEngineView` ANTES de que Chromium lo
        consuma internamente (§5.3 — comportamiento no garantizado por documentación
        oficial, validado empíricamente en la verificación manual de este REQ; ver
        desarrollo-log-015.md)."""
        if obj is self.web_view:
            if event.type() == QEvent.Type.DragEnter:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Type.DragMove:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Type.Drop:
                self._handle_drop(event)
                return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        self._handle_drop(event)

    def _handle_drop(self, event) -> None:
        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return
        path = urls[0].toLocalFile()
        name = os.path.basename(path) if path else ""
        accepted, reason = validate_dropped_file(path)
        self.bridge.file_attached.emit(path, name, accepted, reason)
        event.acceptProposedAction()
