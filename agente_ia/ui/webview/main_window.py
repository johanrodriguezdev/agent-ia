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
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon

from ui.webview.app_icon import app_icon
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineScript, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

import config_manager
from config_manager import get_agent_name
from core.notificaciones import clear_notifier, register_notifier
from core.confirmation import register_confirmation_adapter
from core.security_manager import ChannelType
from ui.webview.bridge import Bridge
from ui.webview.confirmation_adapter import WebViewConfirmationAdapter
from ui.webview.file_drop import validate_dropped_file
from ui.webview.window_geometry import fit_size_to_screen, resolver_maximizado

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
        # Ver `changeEvent()`: Windows devuelve esta ventana de minimizada sin el
        # estado maximizado, y hay que reafirmarlo.
        self._maximizada_al_minimizar = False

        self.setWindowTitle(f"{self._agent_name} — Panel de control")
        # En la ventana Y en la aplicación. Sin lo segundo, la barra de tareas de Windows
        # sigue mostrando el icono de Python: agrupa por proceso, no por ventana, y quien
        # abrió su asistente no tiene por qué ver el logo del lenguaje en que está escrito.
        icono = app_icon()
        self.setWindowIcon(icono)
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icono)
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
        self._setup_notificaciones()
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
        # Copiar una respuesta o un bloque de codigo pasa por `navigator.clipboard`, que
        # QtWebEngine deja cerrado por defecto. Se habilita solo la escritura desde la
        # pagina propia: no hay contenido remoto cargado en este WebView.
        ajustes = page.settings()
        ajustes.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        ajustes.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanPaste, True)

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

        # Si hay una geometria guardada y sigue entrando en la pantalla de hoy, se respeta:
        # la app abre donde la dejaste. Si el monitor cambio (portatil que se desconecto de
        # una pantalla externa), la ventana quedaria fuera de vista, asi que se descarta y
        # se vuelve al calculo normal — nunca se restaura a ciegas.
        guardada = config_manager.get_window_geometry()
        if guardada and self._geometria_visible(guardada, available):
            self.setGeometry(guardada["x"], guardada["y"],
                             guardada["width"], guardada["height"])
            if guardada.get("maximized"):
                self.showMaximized()
            return

        width, height, x, y = fit_size_to_screen(
            (available.x(), available.y(), available.width(), available.height())
        )
        self.setGeometry(x, y, width, height)

    @staticmethod
    def _geometria_visible(geometria: dict, disponible) -> bool:
        """La ventana tiene que quedar mayormente dentro del area de trabajo actual."""
        derecha = geometria["x"] + geometria["width"]
        abajo = geometria["y"] + geometria["height"]
        return (
            geometria["x"] >= disponible.x() - 40
            and geometria["y"] >= disponible.y() - 10
            and derecha <= disponible.x() + disponible.width() + 40
            and abajo <= disponible.y() + disponible.height() + 40
        )

    def _guardar_geometria(self) -> None:
        """Recuerda donde estaba la ventana. Best-effort: nunca bloquea el cierre."""
        try:
            geo = self.normalGeometry() if self.isMaximized() else self.geometry()
            config_manager.set_window_geometry(
                geo.width(), geo.height(), geo.x(), geo.y(), self.isMaximized(),
            )
        except Exception as e:
            logger.warning(f"no se pudo guardar la geometria de la ventana: {e}")

    def _setup_state_polling(self) -> None:
        self._state_poll = QTimer(self)
        self._state_poll.timeout.connect(self.bridge.poll_state)
        self._state_poll.start(_STATE_POLL_INTERVAL_MS)

    def _setup_tray_icon(self) -> None:
        """Portado casi textual desde `JarvisMainWindow._setup_tray_icon()` (REQ-008/009,
        eliminado) — independiente del tipo de `centralWidget()` (CA-43)."""
        self.tray_icon = QSystemTrayIcon(self)
        # Antes era un cuadrado azul liso de 16x16: entre los iconos ocultos de Windows,
        # indistinguible de cualquier otra cosa. Ver `ui/webview/app_icon.py`.
        self.tray_icon.setIcon(app_icon())
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
        QApplication.instance().aboutToQuit.connect(self._guardar_geometria)
        QApplication.instance().aboutToQuit.connect(clear_notifier)

    def _close_terminal(self) -> None:
        """Best-effort: nunca bloquea el quit()."""
        try:
            from core.terminal_session import terminal_manager

            terminal_manager.close_all()
        except Exception as e:
            logger.warning(f"no se pudo cerrar la terminal al salir: {e}")

    def _setup_notificaciones(self) -> None:
        """Conecta los avisos del sistema (`core/notificaciones.py`) con la bandeja.

        El registro recibe llamadas desde CUALQUIER hilo —el planificador de flujos, un
        ritual proactivo—, y `QSystemTrayIcon` solo se puede tocar desde el hilo de la GUI.
        El puente es la senal `system_notification` del bridge: emitirla desde otro hilo la
        encola sola, que es exactamente la garantia que hace falta.
        """
        self.bridge.system_notification.connect(self._mostrar_notificacion)
        register_notifier(self.bridge.system_notification.emit)

    def _mostrar_notificacion(self, titulo: str, mensaje: str, nivel: str) -> None:
        """Corre en el hilo de la GUI (conexion en cola desde `_setup_notificaciones`)."""
        iconos = {
            "error": QSystemTrayIcon.MessageIcon.Critical,
            "ok": QSystemTrayIcon.MessageIcon.Information,
            "info": QSystemTrayIcon.MessageIcon.Information,
        }
        try:
            self.tray_icon.showMessage(titulo, mensaje, iconos.get(nivel, iconos["info"]), 6000)
        except Exception as e:
            logger.warning(f"no se pudo mostrar el aviso en la bandeja: {e}")
        # Y tambien dentro de la ventana: si esta abierta, el aviso de la bandeja se pierde
        # entre las notificaciones del sistema.
        self.bridge.notice_shown.emit(nivel, f"{titulo}. {mensaje}" if mensaje else titulo)

    def _toggle_visible(self) -> None:
        self.setVisible(not self.isVisible())

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_visible()

    # ------------------------------------------------------------ ciclo de vida del WebView (§5.4)
    def _on_load_finished(self, ok: bool) -> None:
        if ok:
            # El canal de Telegram, en una pestaña de la terminal, RECIÉN AHORA.
            #
            # Estaba en `__init__` y crear ahí el PTY reventaba con un access violation
            # nativo dentro de `winpty.spawn()`: se levantaba una consola antes de que
            # existiera el bucle de eventos. Y aunque no reventara, tampoco servía — la
            # página aún no había cargado, así que la pestaña se emitía hacia un frontend
            # que todavía no estaba escuchando y no aparecía por ningún lado.
            self.bridge.abrir_canal_telegram()
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
        click en la barra), por eso se escucha el cambio de estado de la ventana.

        Y se reafirma el maximizado al volver de minimizada: Windows restaura esta ventana
        con el tamaño de pantalla completa pero SIN el estado maximizado, con lo que el
        frontend volvía a dibujar el gutter y la app se veía encogida dentro de una ventana
        que nunca cambió de tamaño. Ver `window_geometry.resolver_maximizado()`."""
        super().changeEvent(event)
        if event.type() != QEvent.Type.WindowStateChange:
            return

        minimizada = bool(self.windowState() & Qt.WindowState.WindowMinimized)
        self._maximizada_al_minimizar, reafirmar = resolver_maximizado(
            minimizada, self.isMaximized(), self._maximizada_al_minimizar,
        )
        if reafirmar:
            # Dispara otro WindowStateChange, y es ese el que emite el estado bueno.
            self.showMaximized()
            return

        self.bridge.window_maximized_changed.emit(self.isMaximized())

    def closeEvent(self, event) -> None:
        """CA-01 — portado sin cambios de comportamiento: cerrar minimiza a la bandeja en
        vez de terminar el proceso (idéntico a `JarvisMainWindow.closeEvent()`)."""
        event.ignore()
        self._guardar_geometria()
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
                    self.bridge.drag_over_changed.emit(True)
                    return True
            elif event.type() == QEvent.Type.DragMove:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
            elif event.type() == QEvent.Type.DragLeave:
                self.bridge.drag_over_changed.emit(False)
            elif event.type() == QEvent.Type.Drop:
                self.bridge.drag_over_changed.emit(False)
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
        # Mismo punto que el boton del clip: `Bridge.attach_file()` valida, guarda la ruta
        # para el proximo mensaje y emite la senal. Antes esto emitia la senal por su
        # cuenta y la ruta se perdia — el chip mostraba el nombre y el agente nunca se
        # enteraba de que habia un archivo.
        self.bridge.attach_file(path)
        event.acceptProposedAction()
