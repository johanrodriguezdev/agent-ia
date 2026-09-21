"""
ui/webview/bridge.py
`Bridge(QObject)` — única superficie expuesta a JS vía `QWebChannel` (REQ-015/CA-42,
arquitectura-015.md §4). Cada método público invocable desde JS es un `@pyqtSlot` con
tipos declarados explícitamente; ningún slot ejecuta `eval`/código arbitrario ni importa
módulos fuera de la lista concreta de §4: `resolve()`, `execute_action()`, 5 funciones de
`ai/memory_manager.py` (`store_turn`, `list_conversations`, `get_conversation_turns`,
`new_conversation_id`, `delete_conversation`), y `WakeWordWorker` (que a su vez usa
`listen_for_wake_word()`, nunca importado directo acá)... y (REQ-016) 4 funciones de
`tasks/task_manager.py` (`create_task`, `list_all_tasks`, `complete_task`, `delete_task`,
todas ya existentes, sin modificar) + 6 funciones nuevas de `ai/memory_manager.py`
(`create_project`, `list_projects`, `assign_conversation_to_project`,
`unassign_conversation_from_project`, `list_conversations_by_project`, `delete_project`)
... y (REQ-019) 2 funciones de `core/security_manager.py`
(`classify_action`/`classify_action_base`, ya existentes/nuevas) + 2 funciones de
`core/security_config.py` (`load_security_overrides`, `save_security_overrides`) para
los slots `request_security_overrides()`/`save_security_override()`. Ningún slot nuevo
permite bajar el nivel efectivo de una acción — la validación vive en `security_manager`
(rank, vía `_RISK_LEVEL_ORDER` importado directo, nunca copiado) y se repite server-side
en el propio slot, nunca confiando en las opciones que ofreció el `<select>` de JS
(CA-21). El catálogo `_SECURITY_ROWS_V1` acota v1 a 8 filas fijas de la categoría
"apertura de aplicaciones y navegación" — nunca incluye ninguna de las 10 claves Rojo de
REQ-005 (CA-08) y nunca ofrece un nivel por encima de "yellow"
(`_V1_MAX_OFFERABLE_LEVEL`, evita auto-bloqueo sin PIN configurado).
Ningún slot nuevo importa `tasks/task_manager.py` ni el código de proyectos de
`ai/memory_manager.py` fuera de esta lista — JS nunca los toca directo (CA-34).

Decisiones de implementación no fijadas letra por letra en la tabla de §4.1/§4.2 (ver
desarrollo-log-015.md para el detalle completo):
- `request_initial_state()`: slot nuevo, sin equivalente literal en §4.1. JS lo llama una
  única vez, inmediatamente después de que `window.bridge` queda disponible (`app.js`).
  Necesario porque una señal Qt emitida ANTES de que JS se suscriba se pierde — emitir
  `chips_loaded`/`conversation_list_updated`/`theme_changed` "al arrancar" (como pide
  CA-39/CA-08) directamente desde `__init__` correría ese riesgo.
- El resultado de un chip de acción (CA-39/CA-40) se reporta como un turno `role="system"`
  vía `message_appended` (CA-14 ya define ese rol para contenido centrado sin burbuja) en
  vez de inventar un evento nuevo — no se persiste (no pasó por `resolve()`, mismo
  criterio que `Composer._on_action_done()` en REQ-013/eliminado).
- `conversation_list_updated` lleva el payload literal `[{...}]` de §4.2 (sin envolver en
  `{append, has_more}`); `sidebar.js` decide "reemplazar" vs "agregar" por el comando que
  disparó la carga (recuerda si el último pedido fue `load_more_conversations`) y calcula
  `has_more` comparando `list.length` contra la misma constante de página que usa acá
  `_CONVERSATION_PAGE_SIZE` — evita reabrir el contrato de datos ya aprobado.
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, QThreadPool, Qt, pyqtSignal, pyqtSlot

import config_manager
from core.security_manager import ChannelType, RiskLevel, _RISK_LEVEL_ORDER
from core.cancelacion import cancelar as cancelar_turno
from core.cancelacion import cerrar_turno, nuevo_turno
from core.terminal_session import TerminalUnavailable, terminal_manager
from core import imagenes
from ui.webview.file_drop import validate_dropped_file
from ui.gui_workers import run_async
from ui.webview.gui_state import GLOBAL_STATE, WAKE_STATE  # noqa: F401 (ver poll_state)
from ui.webview.markdown_render import render_markdown
from core.user_identity import OWNER_USER_ID
from ui.webview.theme import resolve_theme_name
from ui.webview.wake_word_worker import WakeWordWorker

logger = logging.getLogger(__name__)

# REQ-013: mismo tamaño de página del listado de conversaciones del sidebar, portado tal
# cual — ver docstring del módulo, nota sobre `conversation_list_updated`.
_CONVERSATION_PAGE_SIZE = 30

# REQ-026 (addendum 1, post-prueba-manual de Johan): de los 3 accesos rápidos que
# sobrevivían a los 5 chips originales de CA-39 (REQ-015), Johan pidió sacar "📷 Captura de
# pantalla" y "🌐 Abrir navegador" de la barra del composer — la capacidad del agente
# (`take_screenshot`/`open_browser` por texto/voz) NO se toca, solo este atajo de UI
# (SPEC-026-addendum-1.md, "Aclaración de alcance"). Queda un único acceso rápido
# ("Recuérdame algo"), que además deja de tener su propia fila: se renderiza junto a los 4
# modos en `#actions-row` (mismo componente visual `.mode-btn`, sin estado de toggle —
# `composer.js::renderQuickActions()`). Se mantiene como catálogo propio en vez de fundirse
# en `core/composer_modes.py::listar_modos()` porque no es un modo real (no tiene
# `tool_names`/`tarea`/`prompt_hint`, nunca prioriza nada) — opción de modelado más simple
# señalada como válida por `ui-design-026-addendum-1.md` §1 ("Nota de frontera").
_QUICK_ACTIONS: List[Dict[str, str]] = [
    {"label": "Recuérdame algo", "kind": "template", "payload": "Recuérdame que ",
     "icon": "bell"},
]

# REQ-019/§3.1 — catálogo de la categoría v1 ("apertura de aplicaciones y navegación",
# ASUMIDO de SPEC-019). Vive acá (no en security_manager.py) porque es contenido de
# presentación —labels en español, agrupación de negocio—, igual que _CHIPS arriba;
# security_manager.py se mantiene "puro" (mecanismo, no producto). 8 filas cubren las 9
# claves confirmadas por baseline (`open_app` + `OPEN_APP` colapsadas en una sola fila).
_SECURITY_ROWS_V1: List[Dict[str, Any]] = [
    {"id": "open_app", "label": "Abrir aplicaciones",
     "description": "Abrir cualquier aplicación reconocida por su nombre.",
     "keys": ["open_app", "OPEN_APP"]},
    {"id": "open_chrome", "label": "Abrir Chrome",
     "description": "Abrir el navegador Google Chrome.", "keys": ["open_chrome"]},
    {"id": "open_notepad", "label": "Abrir Bloc de notas",
     "description": "Abrir el Bloc de notas de Windows.", "keys": ["open_notepad"]},
    {"id": "open_explorer", "label": "Abrir Explorador de archivos",
     "description": "Abrir el explorador de archivos de Windows.", "keys": ["open_explorer"]},
    {"id": "open_calculator", "label": "Abrir Calculadora",
     "description": "Abrir la calculadora de Windows.", "keys": ["open_calculator"]},
    {"id": "open_browser", "label": "Abrir navegador",
     "description": "Abrir el navegador predeterminado.", "keys": ["open_browser"]},
    {"id": "open_spotify", "label": "Abrir Spotify",
     "description": "Abrir la aplicación de Spotify.", "keys": ["open_spotify"]},
    {"id": "open_url", "label": "Abrir una URL",
     "description": "Abrir una dirección web específica.", "keys": ["open_url"]},
]
_SECURITY_ROW_BY_ID: Dict[str, Dict[str, Any]] = {row["id"]: row for row in _SECURITY_ROWS_V1}

# REQ-019/§11.2 (Hallazgo B de security-audit-019.md) — única fuente de verdad del
# ranking: derivada de `core.security_manager._RISK_LEVEL_ORDER` (importado arriba),
# nunca mantenida a mano en paralelo. Solo se usa para construir el JSON de `options`
# hacia JS (JS nunca calcula rank — CA-22).
_ORDERED_LEVEL_VALUES: List[str] = [
    level.value for level in sorted(_RISK_LEVEL_ORDER, key=lambda lvl: _RISK_LEVEL_ORDER[lvl])
]

# REQ-019/§11.3 (Hallazgo C de security-audit-019.md, decisión adoptada) — techo v1: el
# catálogo de arriba nunca ofrece ni acepta "red", para no autobloquear una acción hoy
# GREEN sin ORION_AUTH_PIN configurado y sin vía de recuperación desde la UI. Política del
# catálogo de este módulo, no del núcleo de seguridad — una categoría futura con acciones
# YELLOW podría necesitar llegar a RED sin reabrir security_manager.py.
_V1_MAX_OFFERABLE_LEVEL = RiskLevel.YELLOW

_EDGE_MAP: Dict[str, Qt.Edge] = {
    "n": Qt.Edge.TopEdge,
    "s": Qt.Edge.BottomEdge,
    "e": Qt.Edge.RightEdge,
    "w": Qt.Edge.LeftEdge,
    "ne": Qt.Edge.TopEdge | Qt.Edge.RightEdge,
    "nw": Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
    "se": Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
    "sw": Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
}


def _now_iso() -> str:
    return datetime.now().isoformat()


class Bridge(QObject):
    """Objeto único registrado como `window.bridge` en JS (`QWebChannel`).

    `main_window` es la instancia de `ui.webview.main_window.MainWindow` — se usa
    únicamente para los controles de ventana (CA-01, CA-02): `windowHandle()` para
    resize/move nativos, y `showMinimized()`/`showMaximized()`/`close()` para los 3
    controles de la barra de título CSS.
    """

    # ------------------------------------------------------------ Python → JS (§4.2)
    conversation_list_updated = pyqtSignal(str)      # json: [{conversation_id, title, last_activity, turn_count}]
    conversation_cleared = pyqtSignal()
    conversation_removed = pyqtSignal(str)           # conversation_id
    turns_loaded = pyqtSignal(str)                   # json: [{id, role, html, timestamp}]
    message_appended = pyqtSignal(str)               # json: {role, html, timestamp}
    progress_updated = pyqtSignal(str)               # que esta haciendo ahora mismo
    typing_started = pyqtSignal()
    typing_stopped = pyqtSignal()
    gui_state_changed = pyqtSignal(str)
    wake_state_changed = pyqtSignal(str)
    theme_changed = pyqtSignal(str)
    confirmation_requested = pyqtSignal(str, str, str)   # request_id, action_name, message
    file_attached = pyqtSignal(str, str, bool, str)      # path, name, accepted, reason
    #: REQ-054/063 — (ruta, miniatura `data:` URL o "") del adjunto que acaba de entrar.
    #: Va aparte de `file_attached` para no cambiarle la firma a lo que ya la escucha.
    attachment_preview = pyqtSignal(str, str)
    #: REQ-063 — los adjuntos pendientes se consumieron (se mandó el mensaje) o se vaciaron:
    #: la página quita todos los chips.
    attachments_cleared = pyqtSignal()
    #: REQ-054 — la imagen a tamaño completo para el visor: (ruta, `data:` URL).
    image_loaded = pyqtSignal(str, str)
    #: REQ-055 — el último intercambio salió de la conversación (regenerar/editar): la
    #: página quita sus dos burbujas.
    last_turn_removed = pyqtSignal()
    #: REQ-055 — texto para dejar escrito en el cuadro (editar el último mensaje).
    composer_text_requested = pyqtSignal(str)
    chips_loaded = pyqtSignal(str)                   # json: {modes: [...], quick_actions: [...]} (REQ-026)
    error_occurred = pyqtSignal(str)
    window_maximized_changed = pyqtSignal(bool)
    #: REQ-033 — estado del modo autonomía, como JSON. La ventana lo muestra mientras esté
    #: encendido: Johan eligió que no expire solo, así que la mitigación es que sea
    #: imposible no verlo.
    autonomy_changed = pyqtSignal(str)

    # ------------------------------------------------------------ Python → JS (REQ-016)
    tasks_loaded = pyqtSignal(str)                   # json: lista cruda de task_manager.list_all_tasks()
    projects_loaded = pyqtSignal(str)                # json: [{id, name, created_at, conversation_count}]
    project_conversations_loaded = pyqtSignal(str, int)  # json (shape de conversation_list_updated), project_id
    project_removed = pyqtSignal(int)                # project_id

    # ------------------------------------------------------------ Python → JS (REQ-019)
    profile_loaded = pyqtSignal(str)                  # json: {agent_name, agent_pronunciation, display_name, user_title}
    profile_saved = pyqtSignal(str)                   # json: mismo shape, ya normalizado y persistido
    security_overrides_loaded = pyqtSignal(str)       # json: [{row_id, label, description, effective_level, base_level, options}]
    security_override_saved = pyqtSignal(str, str)    # row_id, nuevo_nivel — CA-10
    security_override_save_rejected = pyqtSignal(str)  # row_id — CA-21
    email_capabilities_loaded = pyqtSignal(str)       # json: [{id, label, description, enabled}]
    email_capability_saved = pyqtSignal(str, bool)    # id, nuevo estado
    email_capability_save_rejected = pyqtSignal(str)  # id
    flows_loaded = pyqtSignal(str)                    # json: [{id, nombre, estado, pasos, ...}]
    # REQ-052 — el Mapa de conexiones: {agente, modelos, canales, mcp, flujos}. Sin secretos.
    connection_map_loaded = pyqtSignal(str)

    # ------------------------------------------------------------ terminal embebida
    # `terminal_output` lleva el flujo CRUDO de la PTY, con las secuencias ANSI intactas:
    # el que las interpreta es xterm.js del otro lado. Cualquier limpieza acá rompería los
    # colores, el borrado de línea y el posicionamiento del cursor.
    terminal_output = pyqtSignal(str, str)            # session_id, trozo crudo
    terminal_state = pyqtSignal(str, str, str)        # session_id, estado, detalle
    terminal_tabs = pyqtSignal(str)                   # json: [{id, titulo, cwd, activa}]

    # ------------------------------------------------------------ avisos y turno en curso
    # `error_occurred` ya existia pero moria en un console.error del navegador: los fallos
    # eran invisibles para el usuario. `notice_shown` es el canal de avisos VISIBLES
    # (nivel: error | info | ok) que pinta js/toasts.js.
    # Pedazos de la respuesta a medida que el modelo la escribe (`core/streaming.py`).
    # Antes el texto aparecia entero de golpe despues de diez segundos; ahora se lee
    # mientras llega. El mensaje definitivo sigue viniendo por `message_appended`, ya
    # convertido a HTML y saneado: estos pedazos son texto plano de adelanto.
    message_chunk = pyqtSignal(str)
    notice_shown = pyqtSignal(str, str)               # nivel, mensaje
    # Aviso del SISTEMA (bandeja): lo emite `MainWindow` desde cualquier hilo — un flujo
    # que falla de madrugada corre en el hilo del planificador, no en el de la GUI.
    system_notification = pyqtSignal(str, str, str)   # titulo, mensaje, nivel
    # Arrastrando un archivo por encima de la ventana: el drop ya funcionaba, pero no se
    # veia por ningun lado que se pudiera soltar.
    drag_over_changed = pyqtSignal(bool)
    conversation_search_results = pyqtSignal(str)     # json: [{conversation_id, title, snippet, ...}]
    models_loaded = pyqtSignal(str)                   # json: {proveedores, activo}
    task_models_loaded = pyqtSignal(str)              # json: {tareas, catalogo, general}
    connections_loaded = pyqtSignal(str)              # json: {conexiones} — nunca los valores
    setup_required = pyqtSignal(str)                  # id de la seccion que hay que abrir
    project_items_loaded = pyqtSignal(str, int)       # json: [{kind, item_id, label}], project_id
    assignable_items_loaded = pyqtSignal(str)         # json: {flujos, modulos}
    mcp_servers_loaded = pyqtSignal(str)              # json: {servidores, variables}, sin valores
    mcp_probe_result = pyqtSignal(str, str)           # servidor, texto del sondeo

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self._confirmation_adapter = None  # asignado por MainWindow tras construirse (§4.3)

        self._conversation_id: Optional[str] = None
        self._pending_user_text: str = ""
        # REQ-053 — los pasos del turno en curso (qué herramientas usó), para mostrarlos
        # plegados debajo de la respuesta. Se llenan desde `_on_progress`, en el hilo que
        # trabaja; `list.append` es atómico en CPython y acá no hace falta más.
        self._pasos_del_turno: List[str] = []
        self._primer_turno: bool = False
        #: REQ-055 — `store_turn` corre en otro hilo (calcula embeddings) y tarda. Mientras
        #: el último turno se está guardando, «Regenerar»/«Editar» no pueden borrar "el
        #: último par" de la base: borrarían el anterior. La acción queda encolada y se
        #: ejecuta en `_tras_guardar_turno()`.
        self._guardando_turno: bool = False
        self._accion_tras_guardar: Optional[Callable[[], None]] = None
        #: REQ-057 — cuándo arrancó el turno en curso (`time.monotonic()`), para avisar
        #: solo si la respuesta tardó.
        self._turno_inicio: Optional[float] = None
        #: REQ-055 (revisión) — el último par que se ve en pantalla, ¿está en la base?
        #: Un turno que terminó en error se muestra pero no se guarda: Regenerar/Editar
        #: sobre él no pueden borrar "el último par" de la base (sería el anterior, el
        #: bueno). Con `False`, trabajan sobre `_ultimo_texto_usuario` sin tocar la base.
        self._ultimo_par_persistido: bool = True
        self._ultimo_texto_usuario: str = ""
        # (conversation_id, texto del usuario, respuesta) del primer turno, a la espera de
        # que el turno esté guardado para pedirle un título (REQ-053).
        self._titulo_pendiente: Optional[tuple] = None
        self._resolution_in_flight: bool = False
        self._pending_conversation_offset: int = 0
        # REQ-051 — «Nuevo chat aquí» dentro de un proyecto: el chat todavía no existe (se
        # crea con el primer mensaje), así que se recuerda a qué proyecto va.
        self._pending_project_id: Optional[int] = None

        self._wake_worker: Optional[WakeWordWorker] = None
        self._current_gui_state: str = GLOBAL_STATE
        self._current_wake_state: str = WAKE_STATE

        # REQ-021 (pieza 8) — locuciones despachadas y terminadas. Solo cuando no queda
        # ninguna en vuelo se arma la ventana de micrófono: si el usuario escribió mientras
        # el agente hablaba, el `on_done` de la locución vieja no puede abrirla antes de
        # tiempo (riesgo R10). Ambos contadores se tocan solo desde el hilo de la GUI.
        self._speech_seq: int = 0
        self._speech_done_seq: int = 0

        # Turno cancelable en curso (`core/cancelacion.py`). `_turno_cancelado_id` recuerda
        # cual se freno para poder descartar su respuesta si llega igual.
        self._turno_id: Optional[int] = None
        self._turno_cancelado_id: Optional[int] = None

        # Archivo adjunto esperando al proximo mensaje. Antes la ruta se emitia hacia JS y
        # ahi moria: se veia el nombre en un chip y el agente nunca se enteraba de que
        # habia un archivo. Se guarda de este lado porque es quien arma el turno.
        #: REQ-063 — varios adjuntos por mensaje, en el orden en que entraron; tope
        #: `imagenes.MAX_ADJUNTOS`.
        self._pending_attachments: List[str] = []
        #: REQ-054 — rutas de imágenes que esta sesión ya mostró en una burbuja. Son las
        #: únicas que `request_image()` sirve a tamaño completo: el slot es alcanzable desde
        #: cualquier script de la página (§10.2), y no tiene por qué leer cualquier archivo.
        self._imagenes_mostradas: set = set()

        # REQ-026: espejo EFÍMERO (nunca se persiste a disco) del modo activo en el
        # frontend. `composer.js` es la fuente de verdad real — este espejo solo existe
        # para que `request_models()` pueda reflejar "fijado por tarea" cuando se invoca
        # desacoplado de `send_message()` (p. ej. al abrir el menú de modelos, o al
        # arrancar la app). NUNCA se usa para decidir el ruteo real de un turno:
        # `send_message(text, modo)` siempre usa su propio argumento explícito.
        self._modo_activo: Optional[str] = None

        # La terminal tiene DOS entradas posibles —el panel y la herramienta del agente— y
        # una sola salida: esta. Se engancha al construir el bridge, no al abrir el panel,
        # para que un comando lanzado por el agente con el panel cerrado igual termine
        # viéndose en pantalla (el frontend abre el panel al recibir `terminal_state`).
        terminal_manager.set_sink(self._emit_terminal_output, self._emit_terminal_state)

    def set_confirmation_adapter(self, adapter) -> None:
        """Llamado por `MainWindow.__init__` tras construir el `WebViewConfirmationAdapter`
        (§4.3) — separa la construcción (que necesita el `Bridge` ya creado, para emitir
        `confirmation_requested`) de esta referencia inversa."""
        self._confirmation_adapter = adapter

    # ------------------------------------------------------------ polling de estado (§0.4)
    def poll_state(self) -> None:
        """Llamado por el `QTimer` de 100ms de `MainWindow` — mismo mecanismo de polling
        que `JarvisMainWindow._poll_state()` (REQ-008/009, eliminado): `listen_for_wake_word()`
        corre en un hilo `QRunnable` fuera del control de señales Qt, no hay alternativa
        mejor que pollear `ui.webview.gui_state`.
        """
        from ui.webview import gui_state as gs

        if self._current_gui_state != gs.GLOBAL_STATE:
            self._current_gui_state = gs.GLOBAL_STATE
            self.gui_state_changed.emit(self._current_gui_state)

        if self._current_wake_state != gs.WAKE_STATE:
            self._current_wake_state = gs.WAKE_STATE
            self.wake_state_changed.emit(self._current_wake_state)
            if self._current_wake_state == "INACTIVE":
                # REQ-009: libera la referencia para permitir un nuevo ON (mitigación de
                # doble clic ya validada en REQ-013/eliminado).
                self._wake_worker = None

    # ------------------------------------------------------------ arranque (ver docstring)
    @pyqtSlot()
    def request_initial_state(self) -> None:
        """JS llama esto una única vez, apenas `window.bridge` está disponible."""
        self.chips_loaded.emit(json.dumps({
            "modes": _build_modes_payload(),
            "quick_actions": _build_quick_actions_payload(),
        }))
        self.theme_changed.emit(resolve_theme_name(config_manager.get_ui_theme()))
        self._emitir_autonomia()
        # El estado de la ventana también: `window_maximized_changed` solo se emite cuando
        # el estado CAMBIA, así que una página recién cargada —el arranque con geometría
        # maximizada guardada, o una recarga tras un crash del render— no sabía que estaba
        # maximizada y dibujaba el gutter de tamaño normal a pantalla completa.
        if self._main_window is not None:
            self.window_maximized_changed.emit(self._main_window.isMaximized())
        self._load_conversations(offset=0)

        # Primer arranque sin `config.json` (ni variables de entorno): sin una sola clave de
        # proveedor la app no puede contestar nada, así que abrimos donde se ponen en vez de
        # dejar al usuario delante de un chat que solo devuelve errores. Solo ocurre cuando la
        # app está inservible: en una instalación que funciona no aparece nunca.
        if falta_configurar_proveedor():
            logger.info("No hay ninguna clave de proveedor: abriendo Configuración → Claves de IA")
            self.setup_required.emit("claves")

    # ------------------------------------------------------------ mensajes (§4.1)
    @pyqtSlot(str, str)
    def send_message(self, text: str, modo: str = "") -> None:
        """CA-20..CA-24 — guarda `text` como pendiente, deshabilita envío (guard
        server-side, CA-24: el bridge es invocable desde JS sin pasar por el estado
        `disabled` del DOM, a diferencia de un `QWidget` deshabilitado) y resuelve.

        `modo` (REQ-026) es el id del modo estratégico activo en el composer
        (`""` si no hay ninguno) — se pasa tal cual a `resolve()`, que lo propaga hasta
        `reasoning_loop.run()` para priorizar tools y, si el modo lo define, fijar
        `tarea`. `composer.js::doSend()` es el único call site real; el default vacío
        acá es solo defensivo (Qt invoca el slot con los 2 args siempre).
        """
        if self._resolution_in_flight:
            logger.warning("send_message() ignorado: ya hay una resolución en curso")
            return
        if not text and not self._pending_attachments:
            return

        # REQ-063 — una imagen sola, sin texto, también es un mensaje («¿qué es esto?»
        # implícito): el modelo la recibe con el marcador y nada más.
        text, imagenes_del_turno = self._con_adjunto(text)
        self._iniciar_turno(text, modo, imagenes_del_turno)

    def _iniciar_turno(self, text: str, modo: str, imagen) -> None:
        """Arranca la resolución de `text` (ya con su marcador de adjunto, si lo hay).

        Es el cuerpo de `send_message()`, separado para que «Regenerar» (REQ-055) pueda
        volver a mandar el mismo texto guardado —que ya trae el marcador— sin pasar otra
        vez por `_con_adjunto()`, que consumiría un adjunto pendiente que no es de este
        mensaje.
        """
        self._pending_user_text = text
        self._ultimo_texto_usuario = text
        self._ultimo_par_persistido = False
        self._resolution_in_flight = True
        self._turno_inicio = time.monotonic()   # REQ-057
        self._turno_id = nuevo_turno()
        self._pasos_del_turno = []
        # El reportero se registra por turno y se retira al acabar: fuera de una resolución
        # no hay nada que contar, y así ningún proceso de fondo puede escribir en la línea
        # de estado de un turno que ya terminó.
        from core.progress import register_reporter

        register_reporter(self._on_progress)

        # Mismo criterio que el reportero de progreso: el sumidero se registra por turno y
        # se retira al terminar. Fuera de un turno no hay pantalla esperando, y ninguna
        # llamada interna al modelo (resumenes, clasificacion) debe ir a parar al chat.
        from core.streaming import register_sink

        register_sink(self._on_stream_chunk)

        # REQ-051 — la conversación existe desde el primer mensaje (antes recién al
        # terminar el turno): así una herramienta del turno puede referirse a «este chat».
        from core import conversacion_activa

        conversacion_activa.fijar(self._ensure_conversation_id())

        self.message_appended.emit(json.dumps(self._payload_de_usuario(text, _now_iso())))
        self.typing_started.emit()

        from core.resolution import resolve
        historial = self._historial_de_la_conversacion()
        # REQ-053 — si es el primer intercambio, al guardarlo se le pide un título corto.
        self._primer_turno = not historial
        # REQ-054 — la imagen del turno solo viaja si la hay: los dobles de `resolve` con
        # la firma vieja no conocen el kwarg. REQ-063: una sola va como string, varias como
        # lista (`ai/llm_provider.rutas_de_imagen` acepta las dos formas).
        extra = {"image_path": imagen} if imagen else {}
        run_async(resolve, self._on_resolve_done, self._on_resolve_error, text,
                   ChannelType.DESKTOP, user_id=OWNER_USER_ID, modo=(modo or None),
                   historial=historial, **extra)

    # ------------------------------------------------------------ regenerar / editar (REQ-055)
    @pyqtSlot()
    def regenerate_last(self) -> None:
        """«Regenerar»: borra el último intercambio de la conversación y vuelve a mandar
        el mismo mensaje del usuario, con su imagen si la tenía.

        Como en cualquier app de chat: la respuesta que no convenció desaparece y llega
        otra en su lugar, sin que la conversación acumule las dos. El borrado va por
        `memory.delete_last_turn()` (solo el último par user/assistant, solo de este
        usuario) y ocurre ANTES de resolver, para que el historial que ve el modelo no
        incluya la respuesta que se está reemplazando.
        """
        if self._resolution_in_flight:
            logger.warning("regenerate_last() ignorado: hay una resolución en curso")
            return
        if not self._conversation_id:
            self.notice_shown.emit("info", "No hay una respuesta que regenerar.")
            return
        if self._guardando_turno:
            # La respuesta acaba de llegar y todavía se está escribiendo en la base: si se
            # borrara ahora "el último par", sería el anterior. Se espera a que termine.
            self._accion_tras_guardar = self.regenerate_last
            return
        if not self._ultimo_par_persistido:
            # El último par en pantalla terminó en error y no está en la base: no hay nada
            # que borrar allá; se reenvía lo que se ve.
            self.last_turn_removed.emit()
            self._reenviar(self._ultimo_texto_usuario)
            return
        from ai.memory_manager import memory

        # El turno se reserva ANTES del borrado asíncrono: si el pool tarda (embeddings en
        # cola) y mientras tanto entra otro mensaje, habría dos resoluciones a la vez.
        self._resolution_in_flight = True
        conversation_id = self._conversation_id
        run_async(memory.delete_last_turn,
                  lambda usuario: self._tras_borrar_para_regenerar(usuario, conversation_id),
                  self._on_error_borrando_turno, conversation_id, user_id=OWNER_USER_ID)

    def _tras_borrar_para_regenerar(self, usuario, conversation_id: str) -> None:
        self._resolution_in_flight = False
        if usuario is None:
            self.notice_shown.emit("info", "No hay una respuesta que regenerar.")
            return
        if conversation_id != self._conversation_id:
            # El usuario cambió de conversación mientras se borraba: el par ya no está en
            # la base, pero reenviarlo iría a parar al chat equivocado.
            logger.warning("regenerar: la conversación cambió durante el borrado; no se reenvía")
            return
        self.last_turn_removed.emit()
        self._reenviar(usuario.text or "")

    def _reenviar(self, texto: str) -> None:
        """Vuelve a mandar `texto` (que ya trae su marcador de adjunto) con su imagen si
        el archivo sigue existiendo."""
        _, rutas = imagenes.separar_adjuntos(texto)
        vivas = [r for r in rutas if imagenes.es_imagen(r) and os.path.exists(r)]
        imagen = vivas[0] if len(vivas) == 1 else (vivas or None)
        logger.info(f"regenerando la última respuesta de {self._conversation_id}")
        self._iniciar_turno(texto, "", imagen)

    @pyqtSlot()
    def edit_last(self) -> None:
        """«Editar»: saca el último intercambio de la conversación y deja el mensaje del
        usuario escrito en el cuadro para corregirlo y volver a mandarlo.

        Si el mensaje llevaba un adjunto, vuelve al chip (`attach_file`), así el mensaje
        corregido viaja con la misma imagen o archivo sin tener que buscarlo de nuevo.
        """
        if self._resolution_in_flight:
            logger.warning("edit_last() ignorado: hay una resolución en curso")
            return
        if not self._conversation_id:
            self.notice_shown.emit("info", "No hay un mensaje que editar.")
            return
        if self._guardando_turno:
            self._accion_tras_guardar = self.edit_last
            return
        if not self._ultimo_par_persistido:
            self.last_turn_removed.emit()
            self._devolver_al_cuadro(self._ultimo_texto_usuario)
            return
        from ai.memory_manager import memory

        # Igual que en Regenerar: el turno se reserva mientras el borrado está en el pool,
        # o un mensaje que entre en ese hueco correría en paralelo.
        self._resolution_in_flight = True
        conversation_id = self._conversation_id
        run_async(memory.delete_last_turn,
                  lambda usuario: self._tras_borrar_para_editar(usuario, conversation_id),
                  self._on_error_borrando_turno, conversation_id, user_id=OWNER_USER_ID)

    def _tras_borrar_para_editar(self, usuario, conversation_id: str) -> None:
        self._resolution_in_flight = False
        if usuario is None:
            self.notice_shown.emit("info", "No hay un mensaje que editar.")
            return
        if conversation_id != self._conversation_id:
            logger.warning("editar: la conversación cambió durante el borrado; no se toca el cuadro")
            return
        self.last_turn_removed.emit()
        self._devolver_al_cuadro(usuario.text or "")

    def _devolver_al_cuadro(self, texto_guardado: str) -> None:
        """Deja el texto (sin el marcador) en el cuadro y su adjunto de vuelta en el chip."""
        texto, rutas = imagenes.separar_adjuntos(texto_guardado)
        for ruta in rutas:
            if os.path.exists(ruta):
                self.attach_file(ruta)
        logger.info(f"editando el último mensaje de {self._conversation_id}")
        self.composer_text_requested.emit(texto)

    def _on_error_borrando_turno(self, message: str) -> None:
        logger.error(f"No se pudo borrar el último intercambio: {message}")
        self._resolution_in_flight = False
        self.error_occurred.emit("No pude quitar la última respuesta de la conversación.")

    def _on_stream_chunk(self, pedazo: str) -> None:
        """Recibe un pedazo de respuesta DESDE EL HILO que habla con el modelo.

        Solo emite: `pyqtSignal.emit()` cruza al hilo de la GUI por su cuenta. Si el turno
        ya se cancelo, se descarta — seguir escribiendo en pantalla una respuesta que el
        usuario mando a parar seria peor que no cancelar nada.
        """
        if self._turno_id is not None and self._turno_id == self._turno_cancelado_id:
            return
        self.message_chunk.emit(pedazo)

    def _con_adjunto(self, text: str) -> "tuple[str, Any]":
        """Suma al mensaje las rutas de los adjuntos que esperan, si hay.

        Return `(texto, imagen del turno)`: la imagen es `None` si no hay, la ruta (str) si
        hay una, o la lista de rutas si hay varias (REQ-063). Las rutas van COMPLETAS y una
        por linea al final: es lo que necesita cualquiera de los dos caminos que pueden
        leer el archivo — el intent `FILE_ANALYSIS` (`skills/file_analysis_skill.py`, que
        resuelve rutas absolutas) y el modelo, que puede pedir la herramienta
        correspondiente. Antes no llegaba por ninguno: adjuntar era decorativo.

        REQ-054: las imagenes ademas vuelven aparte para que el modelo las VEA en este
        turno (`resolve(image_path=...)`), igual que ve las fotos de Telegram y Discord.

        Los adjuntos se consumen en el turno: si el usuario manda otro mensaje despues, ya
        no viajan. Adjuntar una vez y que se pegue a los diez mensajes siguientes seria peor
        que no adjuntar.
        """
        rutas, self._pending_attachments = list(self._pending_attachments), []
        if not rutas:
            return text, None
        self.attachments_cleared.emit()
        vivas = []
        for ruta in rutas:
            if os.path.exists(ruta):
                vivas.append(ruta)
            else:
                logger.warning(f"el adjunto ya no existe al enviar: {ruta}")
        if len(vivas) < len(rutas):
            self.notice_shown.emit(
                "error", "Un archivo adjunto ya no está donde estaba." if len(rutas) - len(vivas) == 1
                else f"{len(rutas) - len(vivas)} archivos adjuntos ya no están donde estaban.",
            )
        if not vivas:
            return text, None

        logger.info(f"mensaje enviado con {len(vivas)} adjunto(s): {vivas}")
        imagenes_del_turno = [r for r in vivas if imagenes.es_imagen(r)]
        imagen = (imagenes_del_turno[0] if len(imagenes_del_turno) == 1
                  else (imagenes_del_turno or None))
        return imagenes.marcar_adjuntos(text, vivas).lstrip(), imagen

    def _payload_de_usuario(self, texto: str, timestamp: str, **extra: Any) -> Dict[str, Any]:
        """Arma el mensaje del usuario para la pantalla (REQ-054).

        Los marcadores «[Imagen adjunta: C:\\…\\captura.png]» no se muestran como texto:
        la burbuja lleva una miniatura por imagen (`adjuntos[].miniatura`, un `data:` URL
        que `chat.js` pone en un `<img>` por propiedad, nunca por innerHTML) y un chip con
        el nombre por cada adjunto que no es imagen. Las rutas completas siguen en el texto
        guardado, que es lo que ve el modelo, y viajan en `adjuntos[].ruta` para que el
        visor pueda pedir la imagen entera (`request_image`).
        """
        texto_visible, rutas = imagenes.separar_adjuntos(texto)
        payload: Dict[str, Any] = {
            "role": "user", "html": render_markdown(texto_visible), "timestamp": timestamp,
            **extra,
        }
        if rutas:
            adjuntos = []
            for ruta in rutas:
                es_imagen = imagenes.es_imagen(ruta)
                adjuntos.append({
                    "nombre": os.path.basename(ruta),
                    "miniatura": imagenes.miniatura_data_url(ruta) if es_imagen else "",
                    "ruta": ruta if es_imagen else "",
                })
                if es_imagen:
                    self._imagenes_mostradas.add(ruta)
            payload["adjuntos"] = adjuntos
        return payload

    @pyqtSlot(str)
    def request_image(self, ruta: str) -> None:
        """REQ-054 — la imagen entera para el visor, como `data:` URL (`image_loaded`).

        Solo sirve rutas que esta sesión ya mostró en una burbuja (`_imagenes_mostradas`):
        el slot lo puede invocar cualquier script de la página, y leer archivos arbitrarios
        del disco no es lo que se le pidió. Se codifica fuera del hilo de la GUI: una foto de
        cámara tarda lo suyo.
        """
        if ruta not in self._imagenes_mostradas:
            logger.warning(f"request_image ignorado: ruta no mostrada en esta sesión ({ruta!r})")
            return

        def _codificar() -> str:
            return imagenes.miniatura_data_url(ruta, lado=imagenes.LADO_VISOR)

        run_async(_codificar, lambda url: self.image_loaded.emit(ruta, url or ""), None)

    def _on_progress(self, mensaje: str) -> None:
        """Recibe el aviso desde el hilo que trabaja y lo entrega a la interfaz.

        `progress_updated` es un `pyqtSignal`, así que Qt encola la entrega en el hilo de la
        GUI por su cuenta: este método puede llamarse desde cualquier hilo sin cuidados.

        Además de mostrarlo en la línea de estado, el aviso se guarda como un paso del
        turno (REQ-053): cuando llega la respuesta, la interfaz muestra plegado qué hizo el
        agente para llegar a ella. Solo cuentan las herramientas: «Pensando» y
        «Entendiendo lo que me pides» son el ritmo del bucle, no algo que se hizo.
        """
        self.progress_updated.emit(mensaje)
        self._registrar_paso(mensaje)

    #: Avisos que no son un paso: el bucle avisando que sigue vivo.
    _AVISOS_QUE_NO_SON_PASOS = ("Pensando", "Entendiendo lo que me pides")
    #: Techo de pasos que se guardan por turno. Un turno con más que esto ya se corta
    #: por presupuesto; el techo es para que un reportero desbocado no llene memoria.
    _MAX_PASOS_POR_TURNO = 40

    def _registrar_paso(self, mensaje: str) -> None:
        texto = (mensaje or "").strip()
        if not texto or texto.startswith(self._AVISOS_QUE_NO_SON_PASOS):
            return
        pasos = getattr(self, "_pasos_del_turno", None)
        if pasos is None:
            return
        if pasos and pasos[-1] == texto:      # la misma herramienta dos veces seguidas
            return
        if len(pasos) < self._MAX_PASOS_POR_TURNO:
            pasos.append(texto)

    def _tomar_pasos(self) -> List[str]:
        """Return los pasos del turno y deja la lista vacía para el siguiente."""
        pasos = list(getattr(self, "_pasos_del_turno", None) or [])
        self._pasos_del_turno = []
        return pasos

    def _stop_progress(self) -> None:
        """Retira el reportero y limpia la línea de estado.

        Todo va envuelto por el mismo principio que rige `core/progress.py`: contar lo que
        se hace no puede romper lo que se hace. Este método corre justo antes de entregar
        la respuesta al usuario, así que un fallo aquí —una señal sobre un objeto Qt a
        medio construir, por ejemplo— no puede impedir que la respuesta llegue.
        """
        try:
            from core.progress import clear_reporter
            from core.streaming import clear_sink

            clear_reporter()
            clear_sink()
        except Exception as e:
            logger.warning(f"No se pudo retirar el reportero de progreso: {e}")

        try:
            self.progress_updated.emit("")
        except Exception as e:
            logger.warning(f"No se pudo limpiar la línea de progreso: {e}")

    def _titular_si_es_el_primer_turno(self) -> None:
        """REQ-053 — con el primer turno ya guardado, le pide al modelo un título corto.

        Va en su propio `run_async`, después de refrescar la barra: la conversación
        aparece enseguida con el título derivado y, un par de segundos después, con el
        corto. Un modelo caído no cambia nada: `titular_si_corresponde` nunca lanza.
        """
        pendiente, self._titulo_pendiente = self._titulo_pendiente, None
        if not pendiente:
            return
        from core import titulos

        conversation_id, texto_usuario, texto_asistente = pendiente
        run_async(
            titulos.titular_si_corresponde,
            lambda puesto: self._refrescar_listados() if puesto else None,
            lambda mensaje: logger.info(f"Sin título automático: {mensaje}"),
            conversation_id, texto_usuario, texto_asistente, user_id=OWNER_USER_ID,
        )

    def _tras_guardar_turno(self, _resultado=None) -> None:
        """Con el turno ya en la base: la barra lateral se refresca y, si una herramienta
        pidió guardar «este chat» en un proyecto cuando todavía no tenía turnos
        (REQ-051), ahora sí se puede."""
        from ai.memory_manager import memory
        from core import conversacion_activa

        pendiente = conversacion_activa.tomar_asignacion_pendiente()
        if pendiente is not None:
            conversation_id, project_id = pendiente
            try:
                memory.assign_conversation_to_project(conversation_id, project_id, user_id=OWNER_USER_ID)
            except Exception as e:
                logger.error(f"No se pudo guardar el chat en el proyecto {project_id}: {e}")
        self._load_conversations(offset=0)
        self._emit_projects_loaded()   # REQ-051: un tool del turno pudo mover este chat
        self._titular_si_es_el_primer_turno()
        # REQ-055 — lo que el usuario pidió mientras se guardaba (regenerar/editar).
        self._guardando_turno = False
        self._ultimo_par_persistido = True
        accion, self._accion_tras_guardar = self._accion_tras_guardar, None
        if accion is not None:
            accion()

    def _on_error_guardando_turno(self, message: str) -> None:
        """El guardado falló: se suelta la marca para que regenerar/editar no queden
        colgados para siempre, y se descarta la acción encolada (no hay par que borrar)."""
        logger.error(f"No se pudo guardar el turno: {message}")
        self._guardando_turno = False
        self._accion_tras_guardar = None

    def _on_resolve_done(self, resolution) -> None:
        from ai.memory_manager import memory

        self._stop_progress()

        # Turno cancelado: la respuesta llego igual (la cancelacion es cooperativa y el
        # modelo ya estaba contestando) pero el usuario dijo que no la queria. No se
        # muestra ni se guarda en el historial: seria poner en la conversacion algo que
        # el usuario pidio expresamente descartar.
        turno = self._turno_id
        cerrar_turno(turno)
        self._turno_id = None
        if turno is not None and turno == self._turno_cancelado_id:
            self._turno_cancelado_id = None
            self._pending_user_text = ""
            self._resolution_in_flight = False
            return

        result_text = resolution.text
        pasos = self._tomar_pasos()
        self.message_appended.emit(json.dumps({
            "role": "assistant", "html": render_markdown(result_text), "timestamp": _now_iso(),
            "pasos": pasos,
        }))
        self.typing_stopped.emit()
        self._avisar_si_no_esta_mirando(result_text)

        conversation_id = self._ensure_conversation_id()
        if self._primer_turno:
            # Sin el marcador «[Imagen adjunta: C:\\…]»: una ruta hace que cualquier mensaje
            # pase el umbral y el modelo titularía a partir de un path.
            self._titulo_pendiente = (
                conversation_id, imagenes.separar_adjunto(self._pending_user_text)[0], result_text,
            )
        self._primer_turno = False
        self._guardando_turno = True
        # REQ-059 — `pasos` solo si hay: los dobles de `store_turn` con la firma vieja no
        # conocen el kwarg.
        extra_turno = {"pasos": pasos} if pasos else {}
        run_async(
            memory.store_turn, self._tras_guardar_turno, self._on_error_guardando_turno,
            self._pending_user_text, result_text, conversation_id,
            user_id=OWNER_USER_ID, matched_by=getattr(resolution, "matched_by", ""),
            **extra_turno,
        )
        self._pending_user_text = ""
        self._resolution_in_flight = False
        # REQ-021 (pieza 8): el TTS va DESPUÉS de liberar el guard, y la ventana de
        # micrófono se arma más tarde todavía, al terminar la locución. Son dos instantes
        # separados por toda la locución — es lo que hace que el segundo turno de una
        # conversación nunca llegue con una resolución en curso (CA-15), sin tocar el guard.
        self._speak_response(result_text)

    # ------------------------------------------------------------ aviso al llegar (REQ-057)
    #: Por debajo de esto no se avisa: una respuesta que tardó tres segundos la vio llegar.
    _SEGUNDOS_PARA_AVISAR = 8.0

    def _ventana_a_la_vista(self) -> bool:
        """Return si la ventana está visible y activa (el usuario la está mirando)."""
        ventana = self._main_window
        try:
            return bool(ventana.isVisible() and not ventana.isMinimized() and ventana.isActiveWindow())
        except Exception as e:
            logger.debug(f"no se pudo saber si la ventana está a la vista: {e}")
            return True

    def _avisar_si_no_esta_mirando(self, texto: str) -> None:
        """Un aviso del sistema cuando la respuesta llega y la ventana no está al frente.

        Pedirle algo largo al agente y pasar a otra cosa mientras trabaja es el uso normal;
        hasta acá había que volver a mirar para saber si terminó. Solo si tardó
        (`_SEGUNDOS_PARA_AVISAR`) y solo si la ventana no está activa: si la estás mirando,
        la respuesta ya está ahí. Va por `core/notificaciones.py`, que la bandeja muestra.
        """
        inicio = self._turno_inicio
        if inicio is None or time.monotonic() - inicio < self._SEGUNDOS_PARA_AVISAR:
            return
        if self._ventana_a_la_vista():
            return
        from core.notificaciones import notificar

        primera = " ".join((texto or "").split())
        if len(primera) > 140:
            primera = primera[:140].rstrip() + "…"
        notificar("Respuesta lista", primera, "ok")

    # ------------------------------------------------------------ voz de la respuesta (pieza 8)
    def _hands_free_active(self) -> bool:
        """Return True si el modo manos libres está realmente activo.

        Se evalúa sobre el estado REAL del worker, nunca sobre el texto ni sobre el canal
        declarado (CA-23 ajustado por Johan): el webview pronuncia solo cuando hay manos
        libres, no las respuestas a lo que se escribe con la wake word apagada.
        """
        worker = self._wake_worker
        return worker is not None and not worker.stop_event.is_set()

    def _speak_response(self, raw_text: str) -> None:
        """Pronuncia la respuesta del agente — exactamente una vez por turno resuelto."""
        if not self._hands_free_active():
            return

        from ui.tts_engine import prepare_for_speech, speak

        # CA-24: sobre el texto CRUDO, nunca sobre el HTML de `render_markdown()`.
        # `solo_voz=True`: si se llega aca es porque el manos libres esta activo, y
        # entonces la voz es el canal por el que el usuario esta esperando la respuesta —
        # no un extra sobre lo que ya lee en pantalla.
        speech_text = prepare_for_speech(raw_text, solo_voz=True)
        if not speech_text:
            self._open_conversation_window()
            return

        self._speech_seq += 1
        # CA-25: `speak()` es bloqueante (edge-tts + reproducción); nunca desde el hilo de
        # la GUI. `run_async` además entrega el `on_done` en el hilo de la GUI, que es el
        # gancho que necesita la ventana de micrófono (CA-26).
        run_async(speak, self._on_speech_done, self._on_speech_error, speech_text)

    def _on_speech_done(self, _result) -> None:
        """CA-26 — la ventana de micrófono abre acá, encadenada al fin de la locución."""
        self._finish_speech()

    def _on_speech_error(self, message: str) -> None:
        """CA-28 — un fallo del TTS no puede dejar la conversación muerta."""
        logger.warning(f"TTS falló, la ventana de micrófono se abre igual: {message}")
        self._finish_speech()

    def _finish_speech(self) -> None:
        self._speech_done_seq += 1
        if self._speech_done_seq < self._speech_seq:
            return                      # hay otra locución más nueva todavía sonando
        self._open_conversation_window()

    def _open_conversation_window(self) -> None:
        """Arma la ventana de ~15 s en la que se acepta una frase sin wake word."""
        worker = self._wake_worker
        if worker is None or worker.stop_event.is_set():
            return                      # manos libres OFF: no se abre nada
        worker.conversation_window.open()

    def _on_resolve_error(self, message: str) -> None:
        """Un error no es una respuesta de la IA — no se persiste (mismo criterio que
        `JarvisMainWindow._on_command_error()`, REQ-013/eliminado)."""
        self._stop_progress()

        # Un turno cancelado termina levantando `TurnoCancelado` desde el punto de corte,
        # y llega hasta acá como cualquier otro fallo. Pero no es un fallo: es lo que el
        # usuario pidió. Pintarlo como "Error: ..." seria acusar al agente de romperse por
        # haber obedecido.
        turno = self._turno_id
        cerrar_turno(turno)
        self._turno_id = None
        if turno is not None and turno == self._turno_cancelado_id:
            self._turno_cancelado_id = None
            self._pending_user_text = ""
            self._resolution_in_flight = False
            return
        self.message_appended.emit(json.dumps({
            "role": "assistant", "html": render_markdown(f"Error: {message}"),
            "timestamp": _now_iso(),
            "pasos": self._tomar_pasos(),   # lo que alcanzó a hacer antes de fallar
        }))
        self.typing_stopped.emit()
        self._pending_user_text = ""
        self._resolution_in_flight = False
        # No se pronuncia (un error no es una respuesta del agente), pero tampoco se deja
        # la conversación muerta: en manos libres la ventana se abre igual (CA-28).
        self._open_conversation_window()

    def _historial_de_la_conversacion(self) -> Optional[list]:
        """Return los turnos de la conversación abierta, para que el modelo los vea.

        Antes el modelo recibía el contexto por USUARIO de `agent_context`: los últimos
        cinco registros de cualquier conversación, con las respuestas cortadas a 200
        caracteres. Johan le pidió "mejorá ese mensaje" y el agente no tenía el mensaje.
        Los turnos completos de cada conversación estaban guardados desde REQ-013; solo
        faltaba dárselos.
        """
        if not self._conversation_id:
            return None
        from ai.memory_manager import memory

        try:
            turnos = memory.get_conversation_turns(self._conversation_id, user_id=OWNER_USER_ID,
                                                   limit=60)
        except Exception as e:
            logger.warning(f"no se pudo leer la conversación {self._conversation_id}: {e}")
            return None
        return [{"role": t.role or "user", "content": t.text or ""} for t in turnos
                if getattr(t, "role", None) in ("user", "assistant")]

    def _ensure_conversation_id(self) -> str:
        from ai.memory_manager import memory

        if not self._conversation_id:
            self._conversation_id = memory.new_conversation_id()
            if self._pending_project_id is not None:
                # REQ-051 — nació desde «Nuevo chat aquí». `assign` exige que el chat ya
                # tenga turnos guardados, y eso pasa al terminar el turno: queda pedido y
                # `_tras_guardar_turno()` lo aplica. Mismo camino que la herramienta
                # `chat_project_assign_current` en un chat recién empezado.
                from core import conversacion_activa

                proyecto, self._pending_project_id = self._pending_project_id, None
                conversacion_activa.pedir_asignacion(self._conversation_id, proyecto)
        return self._conversation_id

    # ------------------------------------------------------------ conversaciones (§4.1)
    @pyqtSlot()
    def new_conversation(self) -> None:
        self._conversation_id = None
        self._pending_project_id = None
        self._pending_user_text = ""
        self.conversation_cleared.emit()

    @pyqtSlot(int)
    def new_conversation_in_project(self, project_id: int) -> None:
        """REQ-051 — «Nuevo chat aquí» en la barra lateral: como `new_conversation()`, pero
        el chat que nazca con el primer mensaje queda en `project_id`."""
        self.new_conversation()
        self._pending_project_id = int(project_id) if project_id else None

    @pyqtSlot(str)
    def select_conversation(self, conversation_id: str) -> None:
        self._conversation_id = conversation_id
        # Lo que está en pantalla es lo guardado: Regenerar/Editar pueden ir a la base.
        self._ultimo_par_persistido = True
        # Leer los turnos Y armar el payload fuera del hilo de la GUI: las miniaturas de
        # las imágenes (REQ-054) se decodifican con Pillow, y una conversación con veinte
        # capturas congelaría la ventana si se hiciera acá.
        run_async(self._cargar_turnos, self._on_turns_loaded, self._on_turns_error,
                  conversation_id)

    def _cargar_turnos(self, conversation_id: str) -> tuple:
        from ai.memory_manager import memory

        turns = memory.get_conversation_turns(conversation_id, user_id=OWNER_USER_ID)
        return conversation_id, self._payload_de_turnos(turns)

    def _on_turns_loaded(self, resultado) -> None:
        conversation_id, payload = resultado
        if conversation_id != self._conversation_id:
            # Dos clics rápidos en la barra: la carga de la primera conversación (lenta si
            # tiene muchas imágenes) llegó después de abrir la segunda. Se descarta, o se
            # pintarían los turnos de A sobre B.
            logger.debug(f"turnos de {conversation_id} descartados: ya se abrió otra conversación")
            return
        self.turns_loaded.emit(json.dumps(payload))

    def _payload_de_turnos(self, turns) -> list:
        payload = []
        for item in turns:
            if (item.role or "assistant") == "user":
                # REQ-054 — la miniatura o el chip del adjunto también al reabrir el chat.
                payload.append(self._payload_de_usuario(item.text, item.timestamp, id=item.id))
                continue
            entrada = {
                "id": item.id, "role": item.role or "assistant",
                "html": render_markdown(item.text), "timestamp": item.timestamp,
            }
            # REQ-059 — los pasos guardados con la respuesta, si los hubo.
            pasos = list(getattr(item, "pasos", None) or [])
            if pasos:
                entrada["pasos"] = pasos
            payload.append(entrada)
        return payload

    def _on_turns_error(self, message: str) -> None:
        logger.error(f"No se pudo cargar la conversación: {message}")
        self.error_occurred.emit(message)

    @pyqtSlot(str)
    def request_delete_conversation(self, conversation_id: str) -> None:
        """§10.2 (Hallazgo C de security-audit-015.md) — ya NO asume que JS mostró su
        propio modal: dispara internamente el flujo de confirmación YELLOW antes de tocar
        `memory.delete_conversation()`. Despachado siempre vía `run_async()` (nunca el
        hilo de la GUI) porque el paso de confirmación puede bloquear hasta 120s."""
        run_async(self._delete_conversation_flow, None, self._on_delete_error, conversation_id)

    def _delete_conversation_flow(self, conversation_id: str) -> None:
        from ai.memory_manager import memory
        from core.security_manager import format_details, security_manager

        confirmed = security_manager.require_confirmation(
            "delete_conversation",
            ChannelType.DESKTOP,
            # §10.2: clave "name" deliberada — "conversation_id" no está en
            # _DETAILS_ALLOWED_KEYS de format_details(), perdería trazabilidad silenciosa.
            details=format_details("webview:delete_conversation", {"name": conversation_id}),
            user_id=OWNER_USER_ID,
        )
        if not confirmed:
            return
        deleted = memory.delete_conversation(conversation_id, user_id=OWNER_USER_ID)
        if deleted:
            memory.unassign_conversation_from_project(conversation_id, user_id=OWNER_USER_ID)  # REQ-016/CA-21
            self.conversation_removed.emit(conversation_id)

    def _on_delete_error(self, message: str) -> None:
        logger.error(f"Error eliminando conversación: {message}")
        self.error_occurred.emit(message)

    @pyqtSlot(str)
    def export_conversation(self, conversation_id: str) -> None:
        """REQ-056 — «Exportar a Markdown» desde el menú de un chat en la barra lateral.

        Mismo gate que la herramienta `chat_export_current` (🟡 amarillo: crea un archivo
        en el equipo) y mismo criterio que `request_delete_conversation`: el slot es
        alcanzable desde cualquier script de la página, así que la confirmación va acá, y
        el flujo corre fuera del hilo de la GUI porque la confirmación puede esperar.
        """
        if not conversation_id:
            return
        run_async(self._export_conversation_flow, None, self._on_export_error, conversation_id)

    def _export_conversation_flow(self, conversation_id: str) -> None:
        from ai.memory_manager import memory
        from core.documentos import DocumentoRechazado
        from core.exportar_chat import exportar
        from core.security_manager import format_details, security_manager

        titulo = memory.get_conversation_title(conversation_id, user_id=OWNER_USER_ID)
        confirmed = security_manager.require_confirmation(
            "chat_export_current",
            ChannelType.DESKTOP,
            details=format_details("webview:export_conversation",
                                   {"name": titulo or conversation_id}),
            user_id=OWNER_USER_ID,
        )
        if not confirmed:
            return
        try:
            ruta = exportar(conversation_id, OWNER_USER_ID)
        except DocumentoRechazado as e:
            self.notice_shown.emit("error", str(e))
            return
        self.notice_shown.emit("ok", f"Conversación guardada en {ruta}")

    def _on_export_error(self, message: str) -> None:
        logger.error(f"Error exportando conversación: {message}")
        self.error_occurred.emit("No pude exportar la conversación.")

    def _load_conversations(self, offset: int = 0) -> None:
        from ai.memory_manager import memory

        self._pending_conversation_offset = offset
        # REQ-051 — «Recientes» muestra lo que no está en ningún proyecto; lo demás se ve
        # bajo su proyecto en la misma barra.
        run_async(memory.list_conversations, self._on_conversations_loaded,
                  self._on_conversations_error, user_id=OWNER_USER_ID,
                  limit=_CONVERSATION_PAGE_SIZE, offset=offset, sin_proyecto=True)

    def _on_conversations_loaded(self, conversations) -> None:
        payload = [
            {
                "conversation_id": c.conversation_id, "title": c.title,
                "last_activity": c.last_activity, "turn_count": c.turn_count,
            }
            for c in conversations
        ]
        self.conversation_list_updated.emit(json.dumps(payload))

    def _on_conversations_error(self, message: str) -> None:
        logger.error(f"No se pudo cargar el listado de conversaciones: {message}")
        self.error_occurred.emit(message)

    @pyqtSlot(int)
    def load_more_conversations(self, offset: int) -> None:
        self._load_conversations(offset=offset)

    # ------------------------------------------------------------ tareas (REQ-016/§5.1)
    @pyqtSlot()
    def request_tasks(self) -> None:
        """CA-05, CA-12 — se llama solo al abrir el modal de Tareas, NUNCA desde
        request_initial_state()."""
        run_async(self._fetch_tasks, self._on_tasks_loaded, self._on_task_error)

    def _fetch_tasks(self):
        from tasks.task_manager import task_manager
        return task_manager.list_all_tasks(user_id=OWNER_USER_ID)

    def _on_tasks_loaded(self, tasks) -> None:
        self.tasks_loaded.emit(json.dumps(tasks))

    def _emit_tasks_loaded(self) -> None:
        """Se llama SIEMPRE desde el hilo worker que ya está ejecutando una mutación (crear/
        completar/borrar) — nunca agenda un run_async() anidado, solo relee la lista en el
        mismo hilo y emite (mismo patrón cross-thread ya usado por
        `conversation_removed.emit()` en `_delete_conversation_flow`)."""
        from tasks.task_manager import task_manager
        tasks = task_manager.list_all_tasks(user_id=OWNER_USER_ID)
        self.tasks_loaded.emit(json.dumps(tasks))

    @pyqtSlot(str, str, str, str)
    def create_task(self, title: str, description: str, due_date: str, priority: str) -> None:
        """CA-06 — título obligatorio; el resto opcional. `due_date`/`priority` en blanco
        ("") delegan el default a `task_manager.create_task()` (vence en 1h, prioridad
        'normal'), sin reimplementar esa lógica acá."""
        if not title.strip():
            return
        run_async(self._create_task_flow, None, self._on_task_error,
                  title.strip(), description, due_date, priority)

    def _create_task_flow(self, title, description, due_date, priority) -> None:
        from tasks.task_manager import task_manager
        task_manager.create_task(
            user_id=OWNER_USER_ID, title=title, channel="desktop",
            description=description or "", due_date=due_date or None,
            remind_at=due_date or None, priority=priority or "normal",
        )
        self._emit_tasks_loaded()

    @pyqtSlot(int)
    def complete_task(self, task_id: int) -> None:
        """CA-07 — sin confirmación (no es destructivo, no está en el alcance YELLOW de
        CA-33)."""
        run_async(self._complete_task_flow, None, self._on_task_error, task_id)

    def _complete_task_flow(self, task_id: int) -> None:
        from tasks.task_manager import task_manager
        task_manager.complete_task(task_id, user_id=OWNER_USER_ID)
        self._emit_tasks_loaded()

    @pyqtSlot(int)
    def request_delete_task(self, task_id: int) -> None:
        """CA-08, CA-33 — replica EXACTO el flujo de `request_delete_conversation()`/
        `_delete_conversation_flow()` (arquitectura-015.md §10.2): confirmación YELLOW antes
        de tocar `task_manager.delete_task()`, nunca al revés."""
        run_async(self._delete_task_flow, None, self._on_task_error, task_id)

    def _delete_task_flow(self, task_id: int) -> None:
        from tasks.task_manager import task_manager
        from core.security_manager import format_details, security_manager

        confirmed = security_manager.require_confirmation(
            "delete_task", ChannelType.DESKTOP,
            details=format_details("webview:delete_task", {"name": str(task_id)}),
            user_id=OWNER_USER_ID,
        )
        if not confirmed:
            return
        task_manager.delete_task(task_id, user_id=OWNER_USER_ID)
        self._emit_tasks_loaded()

    def _on_task_error(self, message: str) -> None:
        logger.error(f"Error en operación de tareas: {message}")
        self.error_occurred.emit(message)

    # ------------------------------------------------------------ proyectos (REQ-016/§5.2)
    def _projects_payload(self, projects) -> str:
        return json.dumps([
            {"id": p.id, "name": p.name, "created_at": p.created_at,
             "conversation_count": p.conversation_count}
            for p in projects
        ])

    @pyqtSlot()
    def request_projects(self) -> None:
        """CA-13 — carga perezosa, solo al abrir el modal de Proyectos."""
        run_async(self._fetch_projects, self._on_projects_loaded, self._on_project_error)

    def _fetch_projects(self):
        from ai.memory_manager import memory
        return memory.list_projects(user_id=OWNER_USER_ID)

    def _on_projects_loaded(self, projects) -> None:
        self.projects_loaded.emit(self._projects_payload(projects))

    def _emit_projects_loaded(self) -> None:
        from ai.memory_manager import memory
        self.projects_loaded.emit(self._projects_payload(memory.list_projects(user_id=OWNER_USER_ID)))

    @pyqtSlot(str)
    def create_project(self, name: str) -> None:
        """CA-14 — nombre vacío/solo espacios rechazado en el cliente Y acá (defensa en
        profundidad, mismo criterio que `send_message()` con texto vacío)."""
        if not name.strip():
            return
        run_async(self._create_project_flow, None, self._on_project_error, name.strip())

    def _create_project_flow(self, name: str) -> None:
        from ai.memory_manager import memory
        memory.create_project(user_id=OWNER_USER_ID, name=name)
        self._emit_projects_loaded()

    @pyqtSlot(str, int)
    def assign_conversation_to_project(self, conversation_id: str, project_id: int) -> None:
        """CA-16, CA-20 — reasigna si ya pertenecía a otro proyecto (garantizado por la PK de
        `project_conversations`)."""
        run_async(self._assign_flow, None, self._on_project_error, conversation_id, project_id)

    def _assign_flow(self, conversation_id: str, project_id: int) -> None:
        from ai.memory_manager import memory
        memory.assign_conversation_to_project(conversation_id, project_id, user_id=OWNER_USER_ID)
        self._emit_projects_loaded()
        self._load_conversations(offset=0)   # REQ-051: sale de «Recientes»

    @pyqtSlot(str)
    def unassign_conversation_from_project(self, conversation_id: str) -> None:
        """CA-16 (desasignar) — llamado desde la vista de detalle de un proyecto."""
        run_async(self._unassign_flow, None, self._on_project_error, conversation_id)

    def _unassign_flow(self, conversation_id: str) -> None:
        from ai.memory_manager import memory
        memory.unassign_conversation_from_project(conversation_id, user_id=OWNER_USER_ID)
        self._emit_projects_loaded()
        self._load_conversations(offset=0)   # REQ-051: vuelve a «Recientes»

    @pyqtSlot(int)
    def request_project_conversations(self, project_id: int) -> None:
        """CA-17 — vista de detalle. El `project_id` viaja también en la señal de vuelta
        (`project_conversations_loaded(json, project_id)`) para que la UI descarte una
        respuesta tardía si el usuario ya cambió de proyecto (caso borde de SPEC-016: doble
        click rápido no debe mezclar datos de dos proyectos distintos)."""
        run_async(self._fetch_project_conversations, None, self._on_project_error, project_id)

    def _fetch_project_conversations(self, project_id: int) -> None:
        from ai.memory_manager import memory
        conversations = memory.list_conversations_by_project(project_id, user_id=OWNER_USER_ID)
        payload = json.dumps([
            {"conversation_id": c.conversation_id, "title": c.title,
             "last_activity": c.last_activity, "turn_count": c.turn_count}
            for c in conversations
        ])
        self.project_conversations_loaded.emit(payload, project_id)

    @pyqtSlot(int)
    def request_delete_project(self, project_id: int) -> None:
        """CA-18, CA-33 — mismo flujo YELLOW que `delete_task`/`delete_conversation`."""
        run_async(self._delete_project_flow, None, self._on_project_error, project_id)

    def _delete_project_flow(self, project_id: int) -> None:
        from ai.memory_manager import memory
        from core.security_manager import format_details, security_manager

        confirmed = security_manager.require_confirmation(
            "delete_project", ChannelType.DESKTOP,
            details=format_details("webview:delete_project", {"name": str(project_id)}),
            user_id=OWNER_USER_ID,
        )
        if not confirmed:
            return
        deleted = memory.delete_project(project_id, user_id=OWNER_USER_ID)
        if deleted:
            self.project_removed.emit(project_id)   # CA-19: las conversaciones NO se tocan
            self._emit_projects_loaded()

    def _on_project_error(self, message: str) -> None:
        logger.error(f"Error en operación de proyectos: {message}")
        self.error_occurred.emit(message)

    # ------------------------------------------------------------ perfil (nombre y trato)
    @pyqtSlot()
    def request_profile(self) -> None:
        """Carga perezosa: se llama al abrir la sección 'Perfil' de Configuración."""
        self.profile_loaded.emit(json.dumps(_build_profile_payload()))

    @pyqtSlot(str, str, str, str)
    def save_profile(
        self, agent_name: str, agent_pronunciation: str, display_name: str, user_title: str
    ) -> None:
        """Persiste el perfil y lo re-emite ya normalizado.

        El nombre del agente es el único campo obligatorio: si llega vacío se conserva el
        actual en vez de dejar la app sin nombre. Los otros tres admiten vacío como
        elección deliberada del usuario. Se emite `profile_loaded` además de
        `profile_saved` para que la ventana (título, bandeja, logo del sidebar) se
        actualice en vivo, sin reiniciar.
        """
        name = agent_name.strip() or config_manager.get_agent_name()
        config_manager.set_agent_name(name)
        config_manager.set_agent_pronunciation(agent_pronunciation.strip() or name)
        config_manager.set_display_name(display_name)
        config_manager.set_user_title(user_title)

        payload = _build_profile_payload()
        logger.info(f"Perfil actualizado: agente={payload['agent_name']!r}")
        self.profile_saved.emit(json.dumps(payload))
        self.profile_loaded.emit(json.dumps(payload))

    # ------------------------------------------------------------ seguridad (REQ-019/§3.3)
    @pyqtSlot()
    def request_security_overrides(self) -> None:
        """CA-19 — carga perezosa: se llama solo al abrir la sección 'Seguridad' de la
        pantalla de Configuración, nunca desde request_initial_state()."""
        self.security_overrides_loaded.emit(json.dumps(_build_security_overrides_payload()))

    # ------------------------------------------------------------ flujos durables
    @pyqtSlot()
    def request_flows(self) -> None:
        """Carga perezosa: solo al abrir el panel de Flujos."""
        self.flows_loaded.emit(json.dumps(_build_flows_payload()))

    # ------------------------------------------------------------ mapa de conexiones (REQ-052)
    @pyqtSlot()
    def request_connection_map(self) -> None:
        """Arma el Mapa de conexiones y lo emite. Nunca incluye una credencial.

        Va por `run_async()` porque saber si el bot de Telegram corre aparte recorre la
        lista de procesos (`telegram_launcher._ya_hay_uno_corriendo`), y eso no es para el
        hilo de la GUI. El estado de la GUI que hace falta (manos libres, pestañas de la
        terminal) se toma acá, antes de salir del hilo.
        """
        from ui.webview import gui_state as gs
        from ui.webview import mapa_conexiones

        wake_state = gs.WAKE_STATE
        sesiones = terminal_manager.listado()
        run_async(
            lambda: mapa_conexiones.construir(wake_state, sesiones),
            lambda mapa: self.connection_map_loaded.emit(json.dumps(mapa)),
            lambda mensaje: logger.error(f"Mapa de conexiones: {mensaje}"),
        )

    @pyqtSlot(int)
    def run_flow(self, flow_id: int) -> None:
        """Ejecuta un flujo desde la pantalla.

        Va con `ChannelType.DESKTOP` porque hay alguien mirando: un paso amarillo puede
        pedir confirmación de verdad, a diferencia del disparo por horario. Cada paso sigue
        pasando por su gate — la pantalla no es una vía para saltárselo.
        """
        run_async(
            self._run_flow_flow,
            lambda _r: self.request_flows(),
            lambda message: self._on_flow_error(message),
            flow_id,
        )

    def _run_flow_flow(self, flow_id: int) -> None:
        from core.flows import ejecutar, flow_store, reiniciar
        from core.security_manager import ChannelType

        flujo = flow_store.obtener(int(flow_id))
        if flujo is None:
            raise ValueError("el flujo ya no existe")
        if flujo.terminado:
            # "Ejecutar de nuevo": `ejecutar()` no toca un flujo terminado, así que sin
            # esto el botón no haría nada.
            reiniciar(flujo)
        ejecutar(int(flow_id), canal=ChannelType.DESKTOP)

    @pyqtSlot(int)
    def cancel_flow(self, flow_id: int) -> None:
        run_async(
            self._cancel_flow_flow,
            lambda _r: self.request_flows(),
            lambda message: self._on_flow_error(message),
            flow_id,
        )

    def _cancel_flow_flow(self, flow_id: int) -> None:
        from core.flows import desprogramar, flow_store

        flow_store.cancelar(int(flow_id))
        desprogramar(int(flow_id))

    @pyqtSlot(int)
    def request_delete_flow(self, flow_id: int) -> None:
        run_async(
            self._delete_flow_flow,
            lambda _r: self.request_flows(),
            lambda message: self._on_flow_error(message),
            flow_id,
        )

    def _delete_flow_flow(self, flow_id: int) -> None:
        from core.flows import desprogramar, flow_store

        desprogramar(int(flow_id))
        flow_store.borrar(int(flow_id))

    @pyqtSlot(int, int)
    def remove_flow_step(self, flow_id: int, indice: int) -> None:
        """Quita un paso de un flujo. Es la razón de ser de esta pantalla.

        La pantalla existe para VER lo que se creó hablando y corregir un paso que salió
        mal, no para armar flujos arrastrando cajas: el flujo se crea diciéndolo.
        """
        run_async(
            self._remove_flow_step_flow,
            lambda _r: self.request_flows(),
            lambda message: self._on_flow_error(message),
            flow_id, indice,
        )

    def _remove_flow_step_flow(self, flow_id: int, indice: int) -> None:
        from core.flows import TERMINALES, flow_store

        flujo = flow_store.obtener(int(flow_id))
        if flujo is None:
            raise ValueError("el flujo ya no existe")
        if flujo.estado not in TERMINALES and flujo.paso_actual > 0:
            # Sacar un paso de un flujo a medio correr desalinea `paso_actual` con la
            # lista: lo ya hecho dejaría de coincidir con lo que dice el registro.
            raise ValueError("no se puede editar un flujo que está a medio ejecutar")
        if not 0 <= int(indice) < len(flujo.pasos):
            raise ValueError("ese paso no existe")
        if len(flujo.pasos) == 1:
            raise ValueError("un flujo sin pasos no tiene sentido: borralo entero")

        flujo.pasos.pop(int(indice))
        flujo.paso_actual = 0
        flujo.estado = "pendiente"
        flujo.motivo = ""
        for paso in flujo.pasos:
            paso.estado, paso.resultado = "pendiente", ""
        flow_store.guardar(flujo)

    def _on_flow_error(self, message: str) -> None:
        logger.warning(f"Operación sobre un flujo falló: {message}")
        self.error_occurred.emit(str(message))
        self.request_flows()

    # ------------------------------------------------------------ detener el turno
    @pyqtSlot()
    def stop_resolution(self) -> None:
        """Frena el turno en curso.

        La cancelación es cooperativa (ver `core/cancelacion.py`): se marca el turno y el
        trabajo se detiene en el próximo punto seguro. La interfaz NO espera a que eso
        pase — se desbloquea acá mismo, y si la respuesta del turno cancelado llega igual,
        `_on_resolve_done()` la descarta. Cancelar tiene que sentirse instantáneo aunque
        por debajo no lo sea.
        """
        if not cancelar_turno(self._turno_id):
            return
        self._turno_cancelado_id = self._turno_id
        self._resolution_in_flight = False
        self._stop_progress()
        self.typing_stopped.emit()
        self.notice_shown.emit("info", "Listo, lo dejo acá.")

    # ------------------------------------------------------------ adjuntar archivo
    @pyqtSlot()
    def open_attach_dialog(self) -> None:
        """Abre el diálogo nativo de archivos.

        El botón del clip era solo un cartel que decía "arrastrá el archivo": un clip que
        no abre nada es un botón roto a los ojos de cualquiera. El archivo elegido pasa por
        la MISMA validación que el drag&drop (`file_drop.validate_dropped_file`), que es
        donde viven el límite de tamaño y la lista de extensiones — no se duplica.
        """
        from PyQt6.QtWidgets import QFileDialog

        ruta, _ = QFileDialog.getOpenFileName(
            self._main_window, "Elegir un archivo para adjuntar", "",
            "Archivos soportados (*.txt *.md *.pdf *.png *.jpg *.jpeg *.csv *.json *.py);;Todos (*.*)",
        )
        if not ruta:
            return
        self.attach_file(ruta)

    def attach_file(self, path: str) -> bool:
        """Deja un archivo listo para el proximo mensaje. Return True si se acepto.

        UNICO punto de adjuntado: lo usan el boton del clip y el drag&drop nativo
        (`MainWindow._handle_drop`). Antes cada uno emitia la senal por su cuenta y la ruta
        se perdia en los dos casos — el chip mostraba el nombre y nada mas.
        """
        aceptado, motivo = validate_dropped_file(path)
        if aceptado and path in self._pending_attachments:
            self.notice_shown.emit("info", f"«{os.path.basename(path)}» ya está adjunto.")
            return True
        if aceptado and len(self._pending_attachments) >= imagenes.MAX_ADJUNTOS:
            self.notice_shown.emit(
                "info", f"Hasta {imagenes.MAX_ADJUNTOS} adjuntos por mensaje. Mandá estos y después seguís.",
            )
            return False
        if aceptado:
            self._pending_attachments.append(path)
        self.file_attached.emit(path, os.path.basename(path), aceptado, motivo)
        # REQ-054 — el chip muestra la imagen que va a viajar, no solo su nombre.
        self.attachment_preview.emit(
            path, imagenes.miniatura_data_url(path, lado=96) if aceptado and imagenes.es_imagen(path) else "",
        )
        if aceptado:
            logger.info(f"adjunto listo para el proximo mensaje: {path}")
        return aceptado

    @pyqtSlot()
    def paste_from_clipboard(self) -> None:
        """REQ-054 — Ctrl+V con una imagen (o un archivo) en el portapapeles.

        La página no puede darle a Python los bytes de lo que se pegó —Chromium no expone
        rutas y mandar la imagen en base64 por QWebChannel es lento—, así que `composer.js`
        solo avisa y acá se lee el portapapeles del sistema, en el hilo de la GUI:

        - una imagen (captura con Win+Shift+S, «Copiar imagen» en el navegador) se guarda
          como PNG en la carpeta del usuario y se adjunta;
        - un archivo copiado del Explorador (`hasUrls`) se adjunta por su ruta, con la
          misma validación que el clip y el arrastre.

        Nada de esto viaja solo: queda como adjunto pendiente hasta que el usuario manda el
        mensaje, y el chip lo muestra mientras espera.
        """
        from PyQt6.QtWidgets import QApplication

        portapapeles = QApplication.clipboard()
        if portapapeles is None:
            return
        imagen = portapapeles.image()
        if not imagen.isNull():
            ruta = imagenes.ruta_para_imagen_pegada(OWNER_USER_ID)
            if not imagen.save(ruta, "PNG"):
                logger.error(f"no se pudo guardar la imagen pegada en {ruta}")
                self.notice_shown.emit("error", "No pude guardar la imagen pegada.")
                return
            logger.info(
                f"imagen pegada del portapapeles: {ruta} ({imagen.width()}x{imagen.height()})"
            )
            self.attach_file(ruta)
            return

        datos = portapapeles.mimeData()
        if datos is not None and datos.hasUrls():
            # `toLocalFile()` devuelve barras normales; la ruta se muestra y se guarda en el
            # texto del mensaje, así que va con las del sistema.
            locales = [os.path.normpath(u.toLocalFile()) for u in datos.urls() if u.isLocalFile()]
            if locales:
                # REQ-063 — varios archivos copiados: todos, hasta el tope (el que sobra
                # avisa por su cuenta).
                for local in locales:
                    if not self.attach_file(local) and len(self._pending_attachments) >= imagenes.MAX_ADJUNTOS:
                        break
                return
        self.notice_shown.emit("info", "No hay una imagen ni un archivo en el portapapeles.")

    @pyqtSlot(str)
    def clear_attachment(self, path: str = "") -> None:
        """El usuario saco un chip: ese archivo ya no viaja con el proximo mensaje. Con la
        ruta vacia se sacan todos."""
        if not path:
            self._pending_attachments = []
            self.attachments_cleared.emit()
            return
        self._pending_attachments = [r for r in self._pending_attachments if r != path]

    # ------------------------------------------------------------ conversaciones
    @pyqtSlot(str, str)
    def rename_conversation(self, conversation_id: str, title: str) -> None:
        """Le pone un título propio a una conversación. Vacío vuelve al derivado."""
        from ai.memory_manager import memory

        if memory.rename_conversation(conversation_id, title, user_id=OWNER_USER_ID):
            self._refrescar_listados()
        else:
            self.notice_shown.emit("error", "No pude renombrar esa conversación.")

    def _refrescar_listados(self) -> None:
        """«Recientes» y los proyectos: un chat que vive en un proyecto no está en
        «Recientes», y su título tiene que refrescarse donde sí está."""
        self._load_conversations(offset=0)
        try:
            self._emit_projects_loaded()
        except Exception as e:
            logger.warning(f"no se pudo refrescar la lista de proyectos: {e}")

    @pyqtSlot(str)
    def search_conversations(self, query: str) -> None:
        """Busca DENTRO de lo que se dijo, no solo en los títulos que están en pantalla.

        Va por `run_async()` porque recorre toda la tabla de memorias con LIKE: en una base
        grande eso es medio segundo, y medio segundo en el hilo de la GUI se ve como un
        tirón mientras se escribe.
        """
        run_async(self._search_flow, self._on_search_done, self._on_search_error, query)

    def _search_flow(self, query: str):
        from ai.memory_manager import memory

        return memory.search_conversations(query, user_id=OWNER_USER_ID)

    def _on_search_done(self, resultados) -> None:
        self.conversation_search_results.emit(json.dumps(resultados))

    def _on_search_error(self, message: str) -> None:
        logger.error(f"Error buscando en conversaciones: {message}")
        self.notice_shown.emit("error", "No pude buscar en el historial.")

    # ------------------------------------------------------------ ejecutar en la terminal
    @pyqtSlot(str)
    def run_command_in_terminal(self, command: str) -> None:
        """Manda a la terminal un comando salido de un bloque de código del chat.

        Es el mismo gate que usa el agente (`terminal_run_command`, 🟡 con el comando a la
        vista), y a propósito: el comando lo escribió el modelo, no el usuario. Que esté en
        un bloque de código bonito no lo hace más confiable que si el agente lo propusiera
        por su cuenta.
        """
        run_async(self._run_command_in_terminal_flow, None, self._on_terminal_error, command)

    def _run_command_in_terminal_flow(self, command: str) -> None:
        from agents.tool_registry import execute_tool
        from core.security_manager import ActionDenied

        command = (command or "").strip()
        if not command:
            return
        try:
            execute_tool("terminal_run_command", {"command": command},
                         ChannelType.DESKTOP, user_id=OWNER_USER_ID)
        except ActionDenied as e:
            logger.info(f"comando no ejecutado en la terminal: {e}")
            self.notice_shown.emit("info", "No ejecuté el comando.")

    # ------------------------------------------------------------ modos (REQ-026)
    def _tarea_activa(self) -> str:
        """`tarea` efectiva según el modo activo (espejo `self._modo_activo`), o
        `"razonamiento"` si no hay modo o el modo no fija ninguna. Único lugar que
        resuelve esta lógica — la usan tanto `request_models()` como `set_active_mode()`
        para no duplicarla."""
        from core.composer_modes import get_mode

        modo_def = get_mode(self._modo_activo)
        if modo_def and modo_def.tarea:
            return modo_def.tarea
        return "razonamiento"

    @pyqtSlot(str)
    def set_active_mode(self, modo_id: str) -> None:
        """JS llama esto al togglear un `.mode-btn` (activar o desactivar). Actualiza el
        espejo efímero y reemite `models_loaded` con la tarea del nuevo modo, para que el
        selector del composer refleje "Fijado: ..." si corresponde (mismo patrón que
        REQ-022). `modo_id` vacío = "sin modo" (toggle a apagado)."""
        from core.composer_modes import get_mode

        modo_def = get_mode(modo_id)
        self._modo_activo = modo_def.id if modo_def else None
        self.models_loaded.emit(json.dumps(_build_models_payload(self._tarea_activa())))

    # ------------------------------------------------------------ proveedor y modelo
    @pyqtSlot()
    def request_models(self) -> None:
        self.models_loaded.emit(json.dumps(_build_models_payload(self._tarea_activa())))

    @pyqtSlot(str, str)
    def set_model(self, provider: str, model: str) -> None:
        """Cambia con qué modelo responde el agente, sin reiniciar.

        `generate_response()` lee `config.json` en CADA llamada (`get_provider_config()`),
        así que el cambio aplica desde el turno siguiente sin tocar nada más.
        """
        from ai.llm_provider import destinos_de_tarea

        if destinos_de_tarea("razonamiento"):
            # REQ-022/CA-03/CA-04: hay un destino fijado por tarea para "razonamiento" —
            # cambiar acá no tendría efecto real en la próxima respuesta
            # (`_destinos_iniciales()` lo prioriza por encima de `ai_provider`/`ai_model`).
            # Se ignora sin tocar `config.json` y sin avisar — el frontend ya debería
            # mostrar el botón deshabilitado (CA-02), esto es el gate real del lado
            # servidor para cuando la invocación igual llega (mismo criterio que el resto
            # de `bridge.py`: la UI deshabilitada es cosmética, el gate que importa vive
            # acá, porque los slots son invocables desde cualquier script de la página).
            logger.info("set_model ignorado: 'razonamiento' tiene un destino fijado por tarea")
            return

        if provider not in _MODELOS_CONOCIDOS:
            logger.warning(f"proveedor desconocido: {provider!r} — se ignora")
            self.notice_shown.emit("error", "Ese proveedor no está en el catálogo.")
            return
        modelos = _MODELOS_CONOCIDOS[provider]["modelos"]
        if model and model not in modelos:
            logger.warning(f"modelo {model!r} no listado para {provider!r} — se ignora")
            self.notice_shown.emit("error", "Ese modelo no está en el catálogo del proveedor.")
            return

        config_manager.set_ai_provider_and_model(provider, model or (modelos[0] if modelos else ""))
        self.models_loaded.emit(json.dumps(_build_models_payload()))
        self.notice_shown.emit("ok", f"Ahora respondo con {_MODELOS_CONOCIDOS[provider]['label']}.")

    # ------------------------------------------------------------ credenciales
    @pyqtSlot()
    def request_connections(self) -> None:
        """Que credenciales estan puestas y de donde salen. Nunca sus valores."""
        self.connections_loaded.emit(json.dumps(_build_connections_payload()))

    @pyqtSlot(str, str)
    def save_connection(self, clave: str, valor: str) -> None:
        """Guarda una credencial en `config.json`.

        Se valida contra `_CONEXIONES`: este slot es invocable desde cualquier script de la
        pagina, asi que lo que llega no decide que clave se escribe.
        """
        if clave not in {c["id"] for c in _CONEXIONES}:
            logger.warning(f"save_connection: clave desconocida {clave!r}")
            self.notice_shown.emit("error", "Esa credencial no existe.")
            return

        if not config_manager.set_credencial(clave, valor):
            self.notice_shown.emit("error", "No se guardó: el valor estaba vacío.")
            return

        etiqueta = next(c["label"] for c in _CONEXIONES if c["id"] == clave)
        self.request_connections()

        # Si el entorno tiene esa misma variable, manda el entorno: decirlo aca evita que
        # el usuario pegue una clave, vea "guardada", y siga sin funcionar sin saber por que.
        if config_manager.origen_de_credencial(clave) == "entorno":
            self.notice_shown.emit(
                "info",
                f"Guardada, pero {etiqueta} sigue usando la variable de entorno, que manda "
                f"sobre el archivo. Borrala del entorno para que valga esta.",
            )
        else:
            self.notice_shown.emit("ok", f"Clave de {etiqueta} guardada.")

    @pyqtSlot(str)
    def clear_connection(self, clave: str) -> None:
        """Quita una credencial del archivo."""
        if clave not in {c["id"] for c in _CONEXIONES}:
            logger.warning(f"clear_connection: clave desconocida {clave!r}")
            return

        etiqueta = next(c["label"] for c in _CONEXIONES if c["id"] == clave)
        if config_manager.borrar_credencial(clave):
            self.notice_shown.emit("ok", f"Clave de {etiqueta} borrada.")
        self.request_connections()

    # ------------------------------------------------------------ servidores MCP (REQ-043)
    @pyqtSlot()
    def request_mcp_servers(self) -> None:
        """Qué servidores MCP hay, cómo están y qué variables usan. Nunca sus valores."""
        self.mcp_servers_loaded.emit(json.dumps(_build_mcp_payload()))

    def _mcp_nombre_valido(self, nombre: str) -> str:
        """Return el nombre normalizado si es un servidor declarado; "" si no.

        Los slots de abajo son invocables desde cualquier script de la página, así que lo
        que llega no decide sobre qué servidor se actúa: solo uno que exista en la
        configuración (mismo criterio que `_CONEXIONES` para las claves). `existe()` es una
        lectura de config, no el listado completo: esto corre en el hilo de la GUI.
        """
        from core.mcp_config import existe

        clave = existe(nombre)
        if clave:
            return clave
        logger.warning(f"MCP: servidor desconocido desde la página: {nombre!r}")
        self.notice_shown.emit("error", "Ese servidor MCP no existe.")
        return ""

    def _mcp_confirmar(self, accion: str, params: Dict[str, Any]) -> bool:
        """El mismo gate amarillo que las herramientas del agente, con el mismo nombre.

        Un solo `action_name` → una sola clasificación, un solo texto de confirmación y una
        sola entrada de auditoría, venga del chat o del botón.
        """
        from core.security_manager import format_details, security_manager

        return security_manager.require_confirmation(
            accion, ChannelType.DESKTOP,
            details=format_details(f"webview:{accion}", params),
            user_id=OWNER_USER_ID,
        )

    @pyqtSlot(str, bool)
    def set_mcp_server_enabled(self, nombre: str, activo: bool) -> None:
        """Enciende o apaga un servidor, con el gate amarillo de `mcp_set_server_enabled`.

        Encender arranca el proceso del servidor y registra sus herramientas: es la misma
        acción amarilla que desde el chat, y el slot es alcanzable desde cualquier script
        de la página. Va por `run_async()` como todo lo que confirma.
        """
        clave = self._mcp_nombre_valido(nombre)
        if not clave:
            return
        run_async(
            self._mcp_set_enabled_flow, self._on_mcp_done, self._on_mcp_error, clave, bool(activo),
        )

    def _mcp_set_enabled_flow(self, clave: str, activo: bool) -> str:
        from core.mcp_config import aplicar, habilitar_servidor, resumen_para_humano

        if not self._mcp_confirmar(
            "mcp_set_server_enabled",
            {"name": clave, "task": "encender" if activo else "apagar"},
        ):
            return ""
        habilitar_servidor(clave, activo)
        return resumen_para_humano(aplicar(clave))

    @pyqtSlot(str)
    def remove_mcp_server(self, nombre: str) -> None:
        """Quita un servidor. Pasa por el mismo gate amarillo que la herramienta del agente."""
        clave = self._mcp_nombre_valido(nombre)
        if not clave:
            return
        run_async(self._mcp_remove_flow, self._on_mcp_done, self._on_mcp_error, clave)

    def _mcp_remove_flow(self, clave: str) -> str:
        from core.mcp_config import quitar_servidor
        from core.mcp_manager import desregistrar_servidor

        if not self._mcp_confirmar("mcp_remove_server", {"name": clave}):
            return ""
        quitadas = desregistrar_servidor(clave)
        quitar_servidor(clave)
        return f"{clave} quitado ({quitadas} herramienta(s) desregistrada(s))."

    @pyqtSlot(str, str, str)
    def save_mcp_allowed_tools(self, nombre: str, patrones: str, canales: str) -> None:
        """Guarda qué herramientas se aceptan. Gate amarillo con la lista a la vista."""
        clave = self._mcp_nombre_valido(nombre)
        if not clave:
            return
        run_async(
            self._mcp_allow_flow, self._on_mcp_done, self._on_mcp_error,
            clave, str(patrones or ""), str(canales or ""),
        )

    def _mcp_allow_flow(self, clave: str, patrones: str, canales: str) -> str:
        from core.mcp_config import aplicar, permitir_herramientas, resumen_para_humano

        lista = [p for p in re.split(r"[,\s]+", patrones) if p]
        lista_canales = [c for c in re.split(r"[,\s]+", canales) if c]
        if not self._mcp_confirmar(
            "mcp_allow_tools",
            {"name": clave, "herramientas": lista, "canales": lista_canales},
        ):
            return ""
        permitir_herramientas(clave, lista, lista_canales or None)
        return resumen_para_humano(aplicar(clave))

    @pyqtSlot(str)
    def probe_mcp_server(self, nombre: str) -> None:
        """Conecta y lista sin registrar nada; el resultado vuelve por `mcp_probe_result`."""
        clave = self._mcp_nombre_valido(nombre)
        if not clave:
            return
        run_async(self._mcp_probe_flow, None, self._on_mcp_error, clave)

    def _mcp_probe_flow(self, clave: str) -> None:
        from core.mcp_manager import probar_servidor

        self.mcp_probe_result.emit(clave, probar_servidor(clave))

    @pyqtSlot(str)
    def login_mcp_server(self, nombre: str) -> None:
        """Flujo OAuth del servidor (abre el navegador). El resultado vuelve como aviso."""
        clave = self._mcp_nombre_valido(nombre)
        if not clave:
            return
        run_async(self._mcp_login_flow, self._on_mcp_done, self._on_mcp_error, clave)

    def _mcp_login_flow(self, clave: str) -> str:
        from core.mcp_config import aplicar, resumen_para_humano
        from core.mcp_manager import login_servidor_detallado

        autorizado, mensaje = login_servidor_detallado(clave)
        if not autorizado:
            return mensaje
        # Con credenciales nuevas, reconectar acá mismo: el mensaje de la CLI ("recargá
        # con python -m ...") no le sirve a quien está delante de la pantalla.
        return f"{clave} autorizado. {resumen_para_humano(aplicar(clave))}"

    @pyqtSlot(str, str, str, str)
    def add_mcp_server(self, nombre: str, tipo: str, destino: str, variables: str) -> None:
        """Declara un servidor desde el formulario (REQ-046), con el gate de `mcp_add_server`.

        `variables` son NOMBRES separados por coma; se declaran como referencias
        `${NOMBRE}` (env para un servidor local, `Authorization` para uno remoto) y el valor
        se pega después en el bloque «Variables»: por acá no viaja ningún secreto. Va por
        `run_async()` como todo lo que confirma.
        """
        run_async(
            self._mcp_add_flow, self._on_mcp_done, self._on_mcp_error,
            str(nombre or ""), str(tipo or ""), str(destino or ""), str(variables or ""),
        )

    def _mcp_add_flow(self, nombre: str, tipo: str, destino: str, variables: str) -> str:
        from core.mcp_config import (
            MCPConfigRechazada, agregar_servidor, aplicar, normalizar_nombre,
            resumen_para_humano,
        )

        clave = normalizar_nombre(nombre)          # lanza MCPConfigRechazada → _on_mcp_error
        nombres = [v for v in re.split(r"[,\s]+", variables) if v]
        referencias = {v: f"${{{v}}}" for v in nombres}
        es_http = tipo == "http"
        detalle = {"name": clave, "url" if es_http else "command": destino}
        if not self._mcp_confirmar("mcp_add_server", detalle):
            return ""
        if es_http:
            cabeceras = {"Authorization": referencias[nombres[0]]} if nombres else None
            agregar_servidor(clave, url=destino, headers=cabeceras)
        else:
            agregar_servidor(clave, command=destino, env=referencias or None)
        return resumen_para_humano(aplicar(clave))

    @pyqtSlot(str, str)
    def save_mcp_variable(self, variable: str, valor: str) -> None:
        """Guarda el valor de una `${VARIABLE}` que algún servidor referencia.

        `definir_variable()` rechaza cualquier nombre que ningún servidor use: lo que llega
        del JS no decide qué clave se escribe. El valor no pasa por el modelo ni por el log.
        """
        from core.mcp_config import definir_variable, origen_de_variable

        try:
            guardada = definir_variable(variable, valor)
        except OSError as e:
            logger.error(f"MCP: no se pudo guardar la variable {variable}: {e}")
            self.notice_shown.emit("error", f"No se pudo guardar {variable}: {e}")
            return
        if not guardada:
            self.notice_shown.emit(
                "error", "No se guardó: esa variable no la usa ningún servidor, o venía vacía.",
            )
            return
        self.request_mcp_servers()
        if origen_de_variable(variable) == "entorno":
            self.notice_shown.emit(
                "info",
                f"Guardada, pero {variable} sigue tomándose del entorno, que manda sobre el "
                f"archivo.",
            )
        else:
            self.notice_shown.emit(
                "ok", f"Variable {variable} guardada. Reconectá el servidor para que la use.",
            )

    @pyqtSlot(str)
    def clear_mcp_variable(self, variable: str) -> None:
        """Quita una variable guardada en el archivo."""
        from core.mcp_config import borrar_variable

        try:
            if borrar_variable(variable):
                self.notice_shown.emit("ok", f"Variable {variable} borrada.")
        except OSError as e:
            logger.error(f"MCP: no se pudo borrar la variable {variable}: {e}")
            self.notice_shown.emit("error", f"No se pudo borrar {variable}: {e}")
        self.request_mcp_servers()

    def _on_mcp_done(self, resumen) -> None:
        self.request_mcp_servers()
        if resumen:
            self.notice_shown.emit("ok", str(resumen))

    def _on_mcp_error(self, message: str) -> None:
        logger.error(f"MCP desde la pantalla: {message}")
        self.notice_shown.emit("error", f"No se pudo: {message}")
        self.request_mcp_servers()

    # ------------------------------------------------------------ modelo por tarea
    @pyqtSlot()
    def request_task_models(self) -> None:
        """Qué modelo atiende cada tarea, y el catálogo para cambiarlo."""
        self.task_models_loaded.emit(json.dumps(_build_task_models_payload()))

    @pyqtSlot(str, str)
    def save_task_models(self, tarea: str, destinos_json: str) -> None:
        """Fija los modelos de una tarea, en orden de preferencia.

        Varios destinos = rotación: si el primero se queda sin cuota —lo normal en los
        catálogos gratuitos— se prueba el siguiente dentro de la misma llamada, sin
        abandonar la tarea ni caer al proveedor de pago.

        Una lista vacía borra el enrutado: esa tarea vuelve al modelo general. Todo se
        valida contra `_MODELOS_CONOCIDOS`: este slot es invocable desde cualquier script
        de la página, así que lo que llega NO decide qué se escribe en `config.json`.
        """
        if tarea not in {t["id"] for t in _TAREAS_ENRUTABLES}:
            logger.warning(f"tarea desconocida en save_task_models: {tarea!r}")
            self.notice_shown.emit("error", "Esa tarea no existe.")
            return

        try:
            crudos = json.loads(destinos_json or "[]")
        except json.JSONDecodeError as e:
            logger.warning(f"save_task_models con JSON invalido: {e}")
            self.notice_shown.emit("error", "No pude leer los modelos elegidos.")
            return

        ya_configurados = _destinos_ya_configurados()
        destinos = []
        for crudo in crudos if isinstance(crudos, list) else []:
            if not isinstance(crudo, dict):
                continue
            proveedor = str(crudo.get("proveedor", "")).strip().lower()
            modelo = str(crudo.get("modelo", "")).strip()
            conocido = _MODELOS_CONOCIDOS.get(proveedor)
            en_catalogo = bool(conocido) and modelo in conocido["modelos"]
            if not en_catalogo and (proveedor, modelo) not in ya_configurados:
                logger.warning(f"destino fuera del catalogo, se ignora: {proveedor}/{modelo}")
                continue
            if (proveedor, modelo) not in destinos:
                destinos.append((proveedor, modelo))

        if crudos and not destinos:
            self.notice_shown.emit("error", "Ninguno de esos modelos está en el catálogo.")
            return

        mapeo = dict(config_manager.get_task_providers())
        if not destinos:
            mapeo.pop(tarea, None)
        elif len(destinos) == 1:
            # Forma compacta para el caso comun: config.json se sigue leyendo a mano.
            proveedor, modelo = destinos[0]
            mapeo[tarea] = {"proveedor": proveedor, "modelo": modelo}
        else:
            mapeo[tarea] = [{"proveedor": p, "modelo": m} for p, m in destinos]

        config_manager.set_task_providers(mapeo)
        self.request_task_models()

        etiqueta = next(t["label"] for t in _TAREAS_ENRUTABLES if t["id"] == tarea)
        if destinos:
            self.notice_shown.emit(
                "ok", f"«{etiqueta}» usa ahora {len(destinos)} modelo(s)."
            )
        else:
            self.notice_shown.emit("ok", f"«{etiqueta}» vuelve al modelo general.")

    # ------------------------------------------------------------ elementos de proyecto
    @pyqtSlot(int)
    def request_project_items(self, project_id: int) -> None:
        from ai.memory_manager import memory

        items = memory.list_items_by_project(int(project_id), user_id=OWNER_USER_ID)
        self.project_items_loaded.emit(json.dumps(items), int(project_id))

    @pyqtSlot(str, str, int, str)
    def assign_item_to_project(self, kind: str, item_id: str, project_id: int,
                               label: str) -> None:
        """Mete un flujo o un módulo en un proyecto (las conversaciones tienen su propio
        slot desde REQ-016)."""
        from ai.memory_manager import memory

        if memory.assign_item_to_project(kind, item_id, int(project_id), label=label,
                                         user_id=OWNER_USER_ID):
            self.request_project_items(int(project_id))
            self.request_projects()
        else:
            self.notice_shown.emit("error", "No pude asignarlo a ese proyecto.")

    @pyqtSlot(str, str, int)
    def unassign_item_from_project(self, kind: str, item_id: str, project_id: int) -> None:
        from ai.memory_manager import memory

        memory.unassign_item_from_project(kind, item_id, user_id=OWNER_USER_ID)
        self.request_project_items(int(project_id))
        self.request_projects()

    @pyqtSlot()
    def request_assignable_items(self) -> None:
        """Qué se puede meter en un proyecto, además de conversaciones: los flujos que
        existen y los módulos de la app. Los módulos son un catálogo fijo — sirven para
        anotar "esta parte del sistema es de este proyecto", que es lo que pidió el
        usuario al hablar de "opciones o módulos"."""
        self.assignable_items_loaded.emit(json.dumps(_build_assignable_payload()))

    # ------------------------------------------------------------ terminal embebida
    def abrir_canal_telegram(self) -> None:
        """Levanta el canal de Telegram en una pestaña de la terminal, al arrancar.

        NO es un `@pyqtSlot`, a proposito: lo llama `MainWindow` una vez al iniciar, y
        ningun script de la pagina puede invocarlo. Un slot alcanzable desde JS que abre
        pestañas de terminal seria otra superficie que gatear.

        La pestaña es de SOLO LECTURA y corre un comando fijo, asi que no pasa por la
        confirmacion de `terminal_open` (🟡 amarilla) y no la elude: lo que esa confirmacion
        protege es la shell —la capacidad de ejecutar cualquier cosa— y aca no hay ninguna.
        Ver `channels/telegram_launcher.py`.
        """
        from channels.telegram_launcher import (comando, motivo_para_no_arrancar,
                                                raiz_del_proyecto)
        from core.terminal_session import TerminalUnavailable, terminal_manager

        motivo = motivo_para_no_arrancar()
        if motivo:
            logger.info(f"Telegram: no se arranca — {motivo}")
            return

        try:
            sesion = terminal_manager.crear_proceso(
                comando(), titulo="Telegram", cwd=raiz_del_proyecto(),
            )
        except TerminalUnavailable as e:
            # Sin terminal embebida no hay donde mostrarlo. No es motivo para dejar al
            # usuario sin canal: se cae a la consola aparte, que es lo que habia antes.
            logger.warning(f"Telegram: sin terminal embebida ({e}); se abre aparte")
            from channels.telegram_launcher import arrancar_si_procede

            arrancar_si_procede()
            return
        except Exception as e:
            logger.error(f"Telegram: no se pudo abrir la pestaña del canal: {e}")
            return

        logger.info(f"Telegram: canal corriendo en la pestaña '{sesion.id}'")
        self._emit_terminal_tabs()

    @pyqtSlot()
    def terminal_open(self) -> None:
        """Abre el panel de terminal: se engancha a las sesiones vivas, o crea la primera.

        Solo se confirma cuando hay que ABRIR un shell nuevo. Volver a mostrar una terminal
        que ya está corriendo no ejecuta nada, así que no vuelve a preguntar.

        Va por `run_async()` como todo lo que confirma: `require_confirmation()` bloquea
        hasta 120s esperando el modal y el hilo de la GUI es justo el que tiene que seguir
        pintando ese modal.
        """
        run_async(self._terminal_open_flow, None, self._on_terminal_error)

    @pyqtSlot()
    def terminal_new(self) -> None:
        """Pestaña nueva: siempre es un shell nuevo, así que siempre se confirma."""
        run_async(self._terminal_new_flow, None, self._on_terminal_error)

    def _terminal_open_flow(self) -> None:
        # Solo cuentan las sesiones INTERACTIVAS. Las de solo lectura que abre la app por su
        # cuenta —el canal de Telegram— no valen como "ya hay una terminal abierta": si
        # valieran, su sola existencia saltaria la confirmacion y el usuario acabaria con un
        # shell que nunca autorizo, abierto por una pestaña que puso el sistema.
        activa = terminal_manager.active()
        if terminal_manager.hay_interactiva() and activa is not None:
            self._emit_terminal_tabs()
            self.terminal_state.emit(activa.id, "abierta", activa.cwd)
            return
        self._terminal_new_flow()

    def _terminal_new_flow(self) -> None:
        from core.security_manager import security_manager

        confirmada = security_manager.require_confirmation(
            "terminal_open",
            ChannelType.DESKTOP,
            # Texto fijo escrito a mano, no `format_details()` con parámetros: acá no hay
            # ningún dato del usuario que sanear, y lo que el modal necesita decir es qué
            # implica el "sí" — no el nombre interno de la acción.
            details="webview:terminal_open | abre una consola con tus permisos, "
                    "en la carpeta del proyecto",
            user_id=OWNER_USER_ID,
        )
        if not confirmada:
            self.terminal_state.emit("", "denegada", "No se abrió la terminal.")
            return

        try:
            terminal_manager.crear()
        except TerminalUnavailable as e:
            logger.error(f"no se pudo abrir la terminal: {e}")
            self.terminal_state.emit("", "error", str(e))

    @pyqtSlot(str, str)
    def terminal_input(self, session_id: str, data: str) -> None:
        """Teclas del usuario hacia la shell, tal cual (Tab, Ctrl+C, flechas incluidos).

        Sin gate por diseño: la sesión ya se autorizó al abrirse y confirmar tecla por
        tecla no sería una terminal. Lo que sí queda de cada comando es el registro de
        auditoría que escribe `TerminalSession._audit_lines()`.
        """
        sesion = terminal_manager.get(session_id)
        if sesion is None:
            return
        sesion.write(data)

    @pyqtSlot(str, int, int)
    def terminal_resize(self, session_id: str, cols: int, rows: int) -> None:
        """Le dice a la consola cuántas columnas tiene ahora, para que el shell corte
        bien las líneas y `git`/`pip` dibujen a lo ancho real del panel."""
        sesion = terminal_manager.get(session_id)
        if sesion is None:
            return
        sesion.resize(int(cols), int(rows))

    @pyqtSlot(str)
    def terminal_focus(self, session_id: str) -> None:
        """Marca qué pestaña está a la vista: es contra esa que trabaja el agente."""
        if terminal_manager.set_active(session_id):
            self._emit_terminal_tabs()

    @pyqtSlot(str)
    def terminal_close(self, session_id: str) -> None:
        """Cierra una pestaña Y mata su proceso: no queda una shell viva sin ventana."""
        terminal_manager.close(session_id or None)
        self._emit_terminal_tabs()

    @pyqtSlot()
    def terminal_close_all(self) -> None:
        terminal_manager.close_all()
        self._emit_terminal_tabs()

    @pyqtSlot()
    def request_terminal_tabs(self) -> None:
        self._emit_terminal_tabs()

    def _emit_terminal_tabs(self) -> None:
        self.terminal_tabs.emit(json.dumps(terminal_manager.listado()))

    def _emit_terminal_output(self, session_id: str, chunk: str) -> None:
        """Sink de salida — se invoca DESDE EL HILO LECTOR de la PTY.

        Solo emite: `pyqtSignal.emit()` desde otro hilo lo encola Qt en el hilo de la GUI
        (conexión automática → Queued), que es exactamente la garantía que se necesita acá.
        """
        self.terminal_output.emit(session_id, chunk)

    def _emit_terminal_state(self, session_id: str, estado: str, detalle: str) -> None:
        self.terminal_state.emit(session_id, estado, detalle)
        self._emit_terminal_tabs()

    def _on_terminal_error(self, message: str) -> None:
        logger.error(f"Error en la terminal: {message}")
        self.terminal_state.emit("", "error", str(message))

    # ------------------------------------------------- capacidades de correo
    @pyqtSlot()
    def request_email_capabilities(self) -> None:
        """Carga perezosa, igual que `request_security_overrides()`.

        Estas filas NO son overrides de riesgo: son interruptores de "existe o no existe
        esta función". Van juntas en la pantalla porque las dos son decisiones de
        seguridad del usuario, pero no comparten mecanismo — enviar correo sigue siendo
        ROJO con el interruptor encendido.
        """
        from core.email_capabilities import filas_para_ui

        self.email_capabilities_loaded.emit(json.dumps(filas_para_ui()))

    @pyqtSlot(str, bool)
    def save_email_capability(self, cap_id: str, enabled: bool) -> None:
        """Enciende o apaga una capacidad de escritura de correo.

        El catálogo de `core/email_capabilities.py` es cerrado: un `cap_id` inventado por
        JS se rechaza allá, no acá, para que la validación viva junto al dato.
        """
        run_async(
            self._save_email_capability_flow,
            lambda _result: self.email_capability_saved.emit(cap_id, enabled),
            lambda message: self._on_email_capability_error(cap_id, message),
            cap_id, enabled,
        )

    def _save_email_capability_flow(self, cap_id: str, enabled: bool) -> None:
        from core.email_capabilities import activar

        if not activar(cap_id, bool(enabled)):
            raise ValueError(f"no se pudo guardar la capacidad '{cap_id}'")

    def _on_email_capability_error(self, cap_id: str, message: str) -> None:
        logger.warning(f"save_email_capability('{cap_id}') falló: {message}")
        self.email_capability_save_rejected.emit(cap_id)

    @pyqtSlot(str, str)
    def save_security_override(self, row_id: str, level: str) -> None:
        """CA-21 — defensa en profundidad: revalida rank server-side sin importar qué
        opciones ofreció el `<select>` de JS. Cualquier excepción del flujo (row_id
        desconocido, nivel inválido, intento de bajada, o nivel por encima del techo v1)
        se enruta a `_on_security_override_error()`, que emite
        `security_override_save_rejected(row_id)` — el pseudocódigo original de
        arquitectura-019.md §3.3 solo logueaba en el callback de error sin emitir esa
        señal; se corrige acá siguiendo la nota de implementación explícita del propio
        documento ("confirmar el mecanismo exacto... no asumir la forma del mensaje de
        error")."""
        run_async(
            self._save_security_override_flow,
            lambda _result: self.security_override_saved.emit(row_id, level),
            lambda message: self._on_security_override_error(row_id, message),
            row_id, level,
        )

    def _save_security_override_flow(self, row_id: str, level: str) -> None:
        from core.security_config import save_security_overrides
        from core.security_manager import security_manager

        row = _SECURITY_ROW_BY_ID.get(row_id)
        if row is None:
            logger.warning(f"save_security_override(): row_id desconocido: {row_id!r} — ignorado")
            raise ValueError("row_id desconocido")

        try:
            requested = RiskLevel(level)
        except ValueError:
            logger.warning(f"save_security_override(): nivel inválido: {level!r} — ignorado")
            raise

        accepted_keys: List[str] = []
        all_ok = True

        if _RISK_LEVEL_ORDER[requested] > _RISK_LEVEL_ORDER[_V1_MAX_OFFERABLE_LEVEL]:
            # CA-16/§11.3 — techo v1: rechazado por política de catálogo, no por el core.
            logger.warning(
                f"save_security_override(): '{level}' excede el techo v1 (yellow) para "
                f"'{row_id}' — rechazado (política de catálogo, no de core)"
            )
            all_ok = False
        else:
            for key in row["keys"]:
                current = security_manager.classify_action(key)
                if current is None:
                    logger.warning(
                        f"save_security_override(): clave '{key}' sin clasificar (CA-05) "
                        f"— se rechaza la fila"
                    )
                    all_ok = False
                    continue
                can_apply = _RISK_LEVEL_ORDER[requested] >= _RISK_LEVEL_ORDER[current]
                security_manager.log_override_attempt(key, requested, current, accepted=can_apply)
                if can_apply:
                    accepted_keys.append(key)
                else:
                    all_ok = False

        if not all_ok or not accepted_keys:
            # CA-21: todo o nada por fila — evita que open_app suba y OPEN_APP se quede
            # atrás si una de las dos claves fuera rechazada.
            raise PermissionError("nivel rechazado o fila incompleta")

        save_security_overrides({key: requested.value for key in accepted_keys})

    def _on_security_override_error(self, row_id: str, message: str) -> None:
        """Cubre los 3 casos de `raise` de `_save_security_override_flow()` (row_id
        inválido, nivel inválido, o rechazo por bajada/techo v1) — único camino de error
        hacia la señal de rechazo (CA-21)."""
        logger.warning(f"save_security_override() no aplicado para '{row_id}': {message}")
        self.security_override_save_rejected.emit(row_id)

    # ------------------------------------------------------------ chips (§4.1, CA-39/CA-40)
    @pyqtSlot(str)
    def run_chip_action(self, action_name: str) -> None:
        """Los chips `kind="template"` se resuelven enteramente en JS (prellenan el
        input) — este slot solo existe para `kind="action"`, y siempre pasa por
        `execute_action()` (nunca ejecuta la acción "directo"), igual que
        `Composer._on_chip_clicked()` en REQ-013 (eliminado)."""
        from agents.action_registry import execute_action

        run_async(execute_action, self._on_chip_action_done, self._on_chip_action_error,
                  action_name, channel=ChannelType.DESKTOP, user_id=OWNER_USER_ID)

    def _on_chip_action_done(self, result: Any) -> None:
        """No persiste ni se convierte en turno de conversación (no pasó por `resolve()`)
        — se reporta como mensaje `role="system"` (CA-14), centrado, sin burbuja."""
        self.message_appended.emit(json.dumps({
            "role": "system", "html": render_markdown(str(result)), "timestamp": _now_iso(),
        }))

    def _on_chip_action_error(self, message: str) -> None:
        self.message_appended.emit(json.dumps({
            "role": "system", "html": render_markdown(f"Error: {message}"),
            "timestamp": _now_iso(),
        }))

    # ------------------------------------------------------------ tema (§4.1, CA-37)
    @pyqtSlot(str)
    def set_theme(self, name: str) -> None:
        resolved = resolve_theme_name(name)
        config_manager.set_ui_theme(resolved)
        self.theme_changed.emit(resolved)

    # ------------------------------------------------------------ voz (§4.1, §0.4)
    @pyqtSlot(bool)
    def toggle_wake_word(self, enabled: bool) -> None:
        if enabled:
            if self._wake_worker is not None:
                # Ya hay un worker activo (incluso deteniéndose) — ignora el clic para
                # evitar dos WakeWordWorker compitiendo por sr.Microphone() (REQ-009).
                return
            self._wake_worker = WakeWordWorker()
            self._wake_worker.signals.command_detected.connect(self._on_voice_command)
            # Encender el micrófono YA ES pedir atención: se abre la misma ventana de ~15s
            # que se arma después de cada respuesta, así la PRIMERA frase se acepta sin
            # exigir el nombre del agente.
            #
            # Sin esto, el usuario apretaba el micrófono, hablaba, y el agente descartaba
            # la frase en silencio por no traer wake word — indistinguible de estar
            # colgado (visto en vivo: 'Busca en YouTube de Bon Jovi', 2026-09-03 21:50).
            # Y el problema no era solo de expectativa: el reconocedor suele comerse la
            # primera palabra, que es justo donde va el nombre.
            #
            # No se debilita el modo: pasados los 15s vuelve a exigirse la wake word, y la
            # ventana se cierra al aceptar UNA frase (`consume()`). Sigue sirviendo para
            # dejarlo encendido sin que cualquier conversación lo despierte.
            self._open_conversation_window()
            QThreadPool.globalInstance().start(self._wake_worker)
            self.notice_shown.emit(
                "info", "Te escucho. Puedes hablar sin decir mi nombre por unos segundos.",
            )
        else:
            self._stop_wake_word_worker()

    def _on_voice_command(self, text: str) -> None:
        """Resuelve un comando dictado por voz igual que uno escrito.

        Llega por conexión en cola desde el hilo del worker, así que este cuerpo corre en
        el hilo principal y puede reusar `send_message()` tal cual — mismo pipeline
        (`resolve()`), mismo gate de seguridad, misma persistencia en el historial. Si ya
        hay una resolución en curso, `send_message()` lo ignora con su propio guard.
        """
        if self._resolution_in_flight:
            logger.warning(f"Comando por voz ignorado (resolución en curso): {text!r}")
            return
        self.send_message(text)

    def _stop_wake_word_worker(self) -> None:
        if self._wake_worker is not None:
            # REQ-021: primero se cierra la ventana de conversación y después se pide la
            # parada. Así, entre ambas cosas, no queda un instante en el que se acepte una
            # frase sin wake word con el manos libres ya apagado.
            self._wake_worker.conversation_window.cancel()
            self._wake_worker.stop_event.set()

    def stop_wake_word_worker(self) -> None:
        """Envoltorio público — llamado por `MainWindow` desde `aboutToQuit` (CA-09,
        mismo criterio que `JarvisMainWindow._stop_wake_word_worker()` en REQ-009)."""
        self._stop_wake_word_worker()

    # ------------------------------------------------------------ confirmación YELLOW (§4.3)
    @pyqtSlot(str, bool)
    def confirm_response(self, request_id: str, confirmed: bool) -> None:
        if self._confirmation_adapter is None:
            logger.warning("confirm_response() sin adaptador de confirmación registrado")
            return
        self._confirmation_adapter.confirm_response(request_id, confirmed)

    # ------------------------------------------------------------ chrome de ventana (§4.1, CA-01/CA-02)
    @pyqtSlot(str)
    def start_resize(self, edge: str) -> None:
        window_handle = self._main_window.windowHandle()
        if window_handle is None:
            logger.warning("start_resize(): windowHandle() no disponible todavía")
            return
        edges = _EDGE_MAP.get(edge)
        if edges is None:
            logger.warning(f"start_resize(): edge desconocido: {edge!r}")
            return
        window_handle.startSystemResize(edges)

    @pyqtSlot()
    def start_move(self) -> None:
        window_handle = self._main_window.windowHandle()
        if window_handle is None:
            logger.warning("start_move(): windowHandle() no disponible todavía")
            return
        window_handle.startSystemMove()

    # ------------------------------------------------------------ modo autonomía (REQ-033)
    def _emitir_autonomia(self) -> None:
        from core.autonomy import estado

        try:
            self.autonomy_changed.emit(json.dumps(estado()))
        except Exception as e:
            logger.error(f"no se pudo emitir el estado de autonomía: {e}")

    @pyqtSlot(str, str)
    def set_autonomy_mode(self, nivel: str, pin: str) -> None:
        """Enciende o apaga el modo autonomía. Lo llama la pantalla de Configuración.

        Es deliberado que esto **no** sea una `ToolSpec`: si el agente pudiera encender su
        propia autonomía, bastaría una instrucción inyectada en una página que esté leyendo
        para que se suelte solo. Se enciende desde la pantalla, que es un acto del humano.
        """
        from core.autonomy import (NIVEL_NORMAL, NIVEL_TOTAL, NIVELES_VALIDOS,
                                   guardar_modo, preparar_rama)
        from core.security_manager import security_manager

        if nivel not in NIVELES_VALIDOS:
            logger.warning(f"set_autonomy_mode: nivel desconocido {nivel!r}, se ignora")
            self.error_occurred.emit("Ese nivel de autonomía no existe.")
            return

        if nivel == NIVEL_TOTAL:
            if not security_manager.has_pin():
                self.error_occurred.emit(
                    "Para el nivel total hace falta un PIN maestro configurado "
                    "(ORION_AUTH_PIN). Sin PIN no habría nada que verificar."
                )
                return
            if not security_manager.verify_pin(pin or ""):
                logger.warning("PIN incorrecto al intentar encender el modo autonomía total")
                self.error_occurred.emit("PIN incorrecto.")
                return

        rama = ""
        if nivel == NIVEL_TOTAL:
            try:
                rama, _anterior = preparar_rama()
            except RuntimeError as e:
                self.error_occurred.emit(str(e))
                return

        try:
            guardar_modo(nivel, rama)
        except (ValueError, OSError) as e:
            logger.error(f"no se pudo guardar el modo autonomía: {e}")
            self.error_occurred.emit("No pude guardar el cambio.")
            return

        self._emitir_autonomia()
        if nivel == NIVEL_NORMAL:
            self.notice_shown.emit("info", "Modo autonomía apagado: vuelvo a preguntar antes de actuar.")
        else:
            self.notice_shown.emit(
                "info",
                f"Modo autonomía encendido ({nivel})."
                + (f" Trabajo sobre la rama {rama}." if rama else ""),
            )

    @pyqtSlot()
    def window_minimize(self) -> None:
        self._main_window.showMinimized()

    @pyqtSlot()
    def window_toggle_maximize(self) -> None:
        if self._main_window.isMaximized():
            self._main_window.showNormal()
        else:
            self._main_window.showMaximized()

    @pyqtSlot()
    def window_close(self) -> None:
        """Dispara el mismo `closeEvent` que minimiza a bandeja (CA-01, portado de
        `JarvisMainWindow.closeEvent()`, REQ-008/009, sin cambios de comportamiento)."""
        self._main_window.close()


#: Catálogo de proveedores y modelos que se ofrecen desde la interfaz. Es una lista
#: cerrada a propósito: `set_model()` y `save_task_models()` validan contra ella, así que un
#: script que corra en la página no puede escribir cualquier cosa en `config.json` (los
#: slots del bridge son invocables desde JS — mismo criterio que `_SECURITY_ROWS_V1` para
#: la pantalla de seguridad). Agregar un modelo nuevo es agregar una línea acá.
#:
#: Los `:free` de OpenRouter son gratuitos de verdad (verificado contra el catálogo de
#: openrouter.ai el 2026-09-04) y TODOS soportan tool-calling, que es lo que el agente
#: necesita para usar herramientas. Ojo: los IDs gratuitos entran y salen del catálogo —
#: si uno empieza a responder "model not found", se reemplaza acá por otro de
#: https://openrouter.ai/models?max_price=0
_MODELOS_CONOCIDOS: Dict[str, Dict[str, Any]] = {
    "deepseek": {"label": "DeepSeek", "modelos": ["deepseek-chat", "deepseek-reasoner"]},
    "anthropic": {"label": "Claude", "modelos": [
        "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
    ]},
    "openai": {"label": "OpenAI", "modelos": ["gpt-4o-mini", "gpt-4o"]},
    "gemini": {"label": "Gemini", "modelos": ["gemini-1.5-flash", "gemini-1.5-pro"]},
    "openrouter": {"label": "OpenRouter", "modelos": [
        # Generalistas
        "z-ai/glm-5.2:free",
        "minimax/minimax-m3:free",
        "minimax/minimax-m2.7:free",
        "thinkingmachines/inkling:free",
        "thinkingmachines/inkling-small:free",
        "inclusionai/ling-3.0-flash-fin:free",
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia/nemotron-3.5-lightning:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "dots-studio/dots-3-note-preview:free",
        "liquid/lfm-2.5-2.6b:free",
        # Orientados a codigo
        "cohere/north-mini-code:free",
        "poolside/laguna-s-2.1:free",
        "poolside/laguna-xs-2.1:free",
        # Comodin: OpenRouter elige por su cuenta entre los gratuitos
        "openrouter/free",
    ]},
    "ollama": {"label": "Ollama (local)", "modelos": ["qwen3:8b", "llama3.1:8b"]},
}

#: Las tareas que el sistema etiqueta de verdad en sus llamadas al modelo. Si una tarea no
#: está acá, ponerla en `task_providers` no haría nada: no hay ningún `generate_response()`
#: que la nombre. La lista se mantiene junto a los `tarea=` del código.
_TAREAS_ENRUTABLES: List[Dict[str, str]] = [
    {
        "id": "razonamiento",
        "label": "Respuesta principal",
        "descripcion": "Lo que te contesta en el chat. Usa herramientas, así que necesita "
                       "un modelo que las soporte.",
    },
    {
        "id": "codigo",
        "label": "Escribir código",
        "descripcion": "Cuando le pides un script. Hay modelos gratuitos especializados "
                       "que lo hacen bien.",
    },
    {
        "id": "ligera",
        "label": "Trabajo mecánico",
        "descripcion": "Resumir correos y páginas, compactar el historial, destilar "
                       "memoria. Es lo que más conviene mandar a un modelo gratuito.",
    },
    # REQ-061 — la imagen pegada o adjunta (REQ-054) va a este modelo. Sin nada elegido,
    # al `vision_provider` de config.json; sin ninguno de los dos, al modelo general, que
    # puede no verla.
    {
        "id": "vision",
        "label": "Ver imágenes",
        "descripcion": "Cuando pegás o adjuntás una imagen. Necesita un modelo que vea "
                       "imágenes (Gemini, Claude, GPT-4o…): uno de solo texto no sirve por "
                       "barato que sea.",
    },
]


#: Módulos de la app que se pueden anotar dentro de un proyecto. No son funcionalidad
#: nueva: son las piezas que ya existen, para poder decir "esta parte es de este
#: proyecto" y encontrarla después.
_MODULOS_ASIGNABLES: List[Dict[str, str]] = [
    {"id": "terminal", "label": "Terminal embebida"},
    {"id": "correo", "label": "Correo (canal restringido)"},
    {"id": "flujos", "label": "Flujos durables"},
    {"id": "tareas", "label": "Tareas y recordatorios"},
    {"id": "memoria", "label": "Memoria y conversaciones"},
    {"id": "voz", "label": "Voz y manos libres"},
    {"id": "mcp", "label": "Servidores MCP"},
    {"id": "seguridad", "label": "Niveles de seguridad"},
]


#: Las credenciales que la app sabe usar, y como se le explican al humano.
#:
#: Lista CERRADA, mismo criterio que `_MODELOS_CONOCIDOS` y `_SECURITY_ROWS_V1`: los slots
#: que la escriben son invocables desde cualquier script de la pagina, asi que lo que llega
#: no decide que clave se toca. Cada `id` tiene que existir en `_ENV_KEY_MAP` de
#: `config_manager.py`, que es quien de verdad las lee.
_CONEXIONES: List[Dict[str, str]] = [
    {
        "id": "deepseek_api_key",
        "label": "DeepSeek",
        "descripcion": "El proveedor de pago que responde por defecto.",
        "variable": "DEEPSEEK_API_KEY",
    },
    {
        "id": "openrouter_api_key",
        "label": "OpenRouter",
        "descripcion": "Da acceso a los 18 modelos gratuitos del catálogo.",
        "variable": "OPENROUTER_API_KEY",
    },
    {
        "id": "anthropic_api_key",
        "label": "Claude (Anthropic)",
        "descripcion": "Opcional. Solo hace falta si eliges Claude como modelo.",
        "variable": "ANTHROPIC_API_KEY",
    },
    {
        "id": "openai_api_key",
        "label": "OpenAI",
        "descripcion": "Opcional. Solo hace falta si eliges GPT como modelo.",
        "variable": "OPENAI_API_KEY",
    },
    {
        "id": "gemini_api_key",
        "label": "Gemini",
        "descripcion": "Opcional. Se usa también para leer imágenes.",
        "variable": "GEMINI_API_KEY",
    },
    {
        "id": "telegram_token",
        "label": "Telegram",
        "descripcion": "El token del bot, de BotFather. Sin él, el canal no arranca.",
        "variable": "TELEGRAM_BOT_TOKEN",
    },
    {
        "id": "discord_token",
        "label": "Discord",
        "descripcion": "Opcional. El token del bot de Discord.",
        "variable": "DISCORD_BOT_TOKEN",
    },
]


#: De estas siete, las que hacen que el agente pueda contestar. Telegram y Discord son
#: canales: su ausencia quita una puerta de entrada, no la capacidad de responder.
_CLAVES_DE_PROVEEDOR = (
    "deepseek_api_key", "openrouter_api_key",
    "anthropic_api_key", "openai_api_key", "gemini_api_key",
)


def falta_configurar_proveedor() -> bool:
    """True si no hay NINGUNA clave de proveedor: la app no puede responder nada."""
    return not any(
        config_manager.origen_de_credencial(clave) for clave in _CLAVES_DE_PROVEEDOR
    )


def _build_mcp_payload() -> Dict[str, Any]:
    """Servidores MCP y las variables que referencian. NUNCA el valor de una variable.

    `listar_servidores()` ya devuelve solo el origen de cada variable ("entorno",
    "archivo" o ""); acá se agrupan las variables por nombre para el bloque de la pantalla.
    """
    from core.mcp_config import CANALES_HABILITABLES, listar_servidores

    servidores = listar_servidores()
    variables: Dict[str, Dict[str, Any]] = {}
    for fila in servidores:
        for v in fila["variables"]:
            entrada = variables.setdefault(
                v["nombre"], {"nombre": v["nombre"], "origen": v["origen"], "servidores": []},
            )
            entrada["servidores"].append(fila["nombre"])
    return {
        "servidores": servidores,
        "variables": sorted(variables.values(), key=lambda v: v["nombre"]),
        "canales": list(CANALES_HABILITABLES),
    }


def _build_connections_payload() -> Dict[str, Any]:
    """Que credenciales hay y de donde salen. NUNCA el valor de ninguna.

    Se manda si esta puesta y donde, y nada mas. Devolver la clave a la pagina la pondria
    en el DOM, en una captura de pantalla o en un volcado del webview — y para decidir si
    hay que cambiarla no hace ninguna falta verla.
    """
    filas = []
    for fila in _CONEXIONES:
        filas.append({
            **fila,
            "origen": config_manager.origen_de_credencial(fila["id"]),
        })
    return {"conexiones": filas}


def _es_gratuito(modelo: str) -> bool:
    """En OpenRouter lo gratis lo marca el sufijo del ID, no el proveedor."""
    return str(modelo).endswith(":free")


def _destino_legible(proveedor: str, modelo: str) -> str:
    etiqueta = _MODELOS_CONOCIDOS.get(proveedor, {}).get("label", proveedor)
    return f"{etiqueta} · {modelo}" if modelo else etiqueta


def _destinos_ya_configurados() -> set:
    """Los destinos que YA están escritos en `config.json`, mirando todas las tareas.

    Se aceptan al guardar aunque no figuren en `_MODELOS_CONOCIDOS`: los IDs gratuitos de
    OpenRouter entran y salen del catálogo, y sin esto, el día que un modelo guardado deja
    de estar en la lista, esa tarea queda congelada — cada intento de guardar se rechaza
    por culpa del modelo que justamente se quiere sacar. Volver a escribir algo que ya
    estaba escrito no habilita nada nuevo, así que la validación del catálogo sigue
    cumpliendo su papel: frenar destinos NUEVOS que la página no debería poder inventar.
    """
    from ai.llm_provider import destinos_de_tarea

    ya = set()
    for tarea in _TAREAS_ENRUTABLES:
        ya.update(destinos_de_tarea(tarea["id"]))
    return ya


def _texto_sin_eleccion_de_vision() -> str:
    """Qué pasa con una imagen si en «Ver imágenes» no se eligió nada."""
    try:
        from ai.llm_provider import get_provider_config

        _, vision_provider, _, _ = get_provider_config()
    except Exception as e:
        logger.debug(f"no se pudo leer el vision_provider: {e}")
        vision_provider = ""
    if vision_provider:
        etiqueta = _MODELOS_CONOCIDOS.get(vision_provider, {}).get("label", vision_provider)
        return f"Usa {etiqueta} (vision_provider de config.json)."
    return "Usa el modelo general, que puede no ver imágenes."


def _build_task_models_payload() -> Dict[str, Any]:
    """Qué modelo atiende cada tarea, y el catálogo para cambiarlo."""
    from ai.llm_provider import destinos_de_tarea

    tareas = []
    for tarea in _TAREAS_ENRUTABLES:
        destinos = [
            {
                "proveedor": proveedor,
                "modelo": modelo,
                "label": _destino_legible(proveedor, modelo),
                "gratis": _es_gratuito(modelo),
            }
            for proveedor, modelo in destinos_de_tarea(tarea["id"])
        ]
        entrada = {**tarea, "destinos": destinos}
        if tarea["id"] == "vision":
            # REQ-061 — sin elección no cae al modelo general sino al `vision_provider`
            # de config.json (si lo hay): que la pantalla diga la verdad.
            entrada["sin_eleccion"] = _texto_sin_eleccion_de_vision()
        tareas.append(entrada)

    catalogo = [
        {
            "proveedor": pid,
            "modelo": modelo,
            "label": _destino_legible(pid, modelo),
            "gratis": _es_gratuito(modelo),
        }
        for pid, datos in _MODELOS_CONOCIDOS.items()
        for modelo in datos["modelos"]
    ]

    return {
        "tareas": tareas,
        "catalogo": catalogo,
        "general": _destino_legible(config_manager.get_ai_provider(),
                                    config_manager.get_ai_model()),
        "avisos": _avisos_de_claves(tareas),
    }


def _avisos_de_claves(tareas: List[Dict[str, Any]]) -> List[str]:
    """Proveedores elegidos que todavía no tienen credencial.

    Sin esto, elegir un modelo gratuito de OpenRouter sin haber puesto la clave se ve como
    un cambio exitoso: la pantalla confirma que quedó guardado, y el error solo aparece
    mucho después, en medio de una respuesta del chat, con un mensaje que el humano ya no
    relaciona con lo que tocó en Configuración.
    """
    faltan = []
    for tarea in tareas:
        for destino in tarea["destinos"]:
            proveedor = destino["proveedor"]
            if proveedor in faltan or proveedor == "ollama":
                continue
            if not config_manager.get_api_key(proveedor):
                faltan.append(proveedor)

    return [
        f"Falta la clave de {_MODELOS_CONOCIDOS.get(p, {}).get('label', p)}: "
        f"esos modelos no van a responder hasta que configures "
        f"{config_manager.env_var_de_proveedor(p) or 'su API key'}."
        for p in faltan
    ]


def _build_models_payload(tarea: str = "razonamiento") -> Dict[str, Any]:
    """Catálogo + qué está activo ahora, para el selector del composer.

    `tarea` (REQ-026): generaliza el "fijado por tarea" de REQ-022 más allá de
    `"razonamiento"` hardcodeado — ahora la decide el modo activo del composer
    (`Bridge._tarea_activa()`), sin cambiar nada acá salvo qué clave se consulta.
    """
    from ai.llm_provider import destinos_de_tarea

    activo_proveedor = config_manager.get_ai_provider()
    activo_modelo = config_manager.get_ai_model()
    proveedores = [
        {
            "id": pid,
            "label": datos["label"],
            "modelos": datos["modelos"],
            "activo": pid == activo_proveedor,
        }
        for pid, datos in _MODELOS_CONOCIDOS.items()
    ]
    etiqueta = _MODELOS_CONOCIDOS.get(activo_proveedor, {}).get("label", activo_proveedor or "?")

    # REQ-022/CA-01 (generalizado por REQ-026): si `tarea` tiene destino(s) fijado(s) en
    # `task_providers`, el selector del chat no tiene efecto real — se le informa al
    # frontend para que lo muestre deshabilitado (CA-02) en vez de dejar que el usuario
    # elija algo que no aplica.
    fijados = destinos_de_tarea(tarea)
    fijado_por_tarea = None
    if fijados:
        fijado_por_tarea = {
            "etiqueta": " / ".join(_destino_legible(p, m) for p, m in fijados),
        }

    return {
        "proveedores": proveedores,
        "activo": {
            "proveedor": activo_proveedor,
            "modelo": activo_modelo,
            "label": etiqueta,
            # Lo que se ve en el composer: el modelo si se conoce, si no el proveedor.
            "resumen": activo_modelo or etiqueta,
        },
        "fijado_por_tarea": fijado_por_tarea,   # None si CA-05 (sin fijar)
    }


def _build_assignable_payload() -> Dict[str, Any]:
    """Flujos y módulos que se pueden meter en un proyecto."""
    flujos: List[Dict[str, str]] = []
    try:
        from core.flows import flow_store

        for flujo in flow_store.listar():
            flujos.append({"id": str(flujo.id), "label": flujo.nombre})
    except Exception as e:
        # Sin flujos disponibles la pantalla sigue sirviendo para módulos: no se cae.
        logger.warning(f"no se pudieron listar los flujos para proyectos: {e}")

    return {"flujos": flujos, "modulos": _MODULOS_ASIGNABLES}


def _build_modes_payload() -> List[Dict[str, Any]]:
    """REQ-026 — catálogo de los 4 modos estratégicos para `#actions-row` (addendum 1:
    antes `#modes-row`, fila propia; ahora comparte fila con "Recuérdame algo"). La
    definición vive en `core/composer_modes.py`; acá solo se proyecta al shape que consume
    `composer.js::renderModes()` (id + label, nada de tools/tarea/prompt_hint — eso es
    interno del backend, el frontend no lo necesita)."""
    from core.composer_modes import listar_modos

    return [{"id": modo.id, "label": modo.label} for modo in listar_modos()]


def _build_quick_actions_payload() -> List[Dict[str, Any]]:
    """CA-40 — `risk_level` se consulta en el momento (nunca hardcodeado): si la
    clasificación de una acción cambia, el color del chip se actualiza solo (la rama
    `kind == "action"` queda sin consumidor real desde el addendum 1 de REQ-026, que redujo
    `_QUICK_ACTIONS` a un único acceso `template` — se deja sin retirar por si vuelve a
    necesitarse un acceso rápido de acción más adelante, mismo criterio que el addendum
    aplicó a `run_chip_action()`: código sin uso actual no es lo mismo que código a borrar
    a ciegas)."""
    from core.security_manager import security_manager

    result = []
    for chip in _QUICK_ACTIONS:
        entry = dict(chip)
        if chip["kind"] == "action":
            level = security_manager.classify_action(chip["payload"])
            entry["risk_level"] = level.value if level is not None else None
        else:
            entry["risk_level"] = None
        result.append(entry)
    return result


def _build_profile_payload() -> Dict[str, Any]:
    """Estado actual del perfil, leído siempre de `config.json` (nunca de una caché)."""
    return {
        "agent_name": config_manager.get_agent_name(),
        "agent_pronunciation": config_manager.get_agent_pronunciation(),
        "display_name": config_manager.get_display_name(),
        "user_title": config_manager.get_user_title(),
    }


def _build_flows_payload() -> List[Dict[str, Any]]:
    """Return los flujos del usuario en la forma que consume `flows_panel.js`.

    Todo lo que sale de acá lo inserta JS con `textContent` (§10.1): el nombre de un flujo
    y el resultado de un paso son texto que puede venir de un comando dictado o de la
    salida de una acción, así que nunca es HTML de confianza.
    """
    from core.flows import TERMINALES, flow_store

    payload: List[Dict[str, Any]] = []
    for flujo in flow_store.listar():
        payload.append({
            "id": flujo.id,
            "nombre": flujo.nombre,
            "estado": flujo.estado,
            "motivo": flujo.motivo,
            "horario": flujo.horario,
            "paso_actual": flujo.paso_actual,
            "terminado": flujo.estado in TERMINALES,
            # `editable` lo decide Python y no JS: es la misma condición que revalida
            # `remove_flow_step()`, y así el botón no aparece cuando la operación se va a
            # rechazar igual.
            "editable": flujo.estado in TERMINALES or flujo.paso_actual == 0,
            "pasos": [
                {
                    "accion": paso.accion,
                    "estado": paso.estado,
                    "resultado": paso.resultado,
                    "condicion": paso.condicion.describir() if paso.condicion else "",
                }
                for paso in flujo.pasos
            ],
        })
    return payload


def _build_security_overrides_payload() -> List[Dict[str, Any]]:
    """REQ-019/§3.4, §11.2/§11.3 — payload de la sección 'Seguridad'. `options` nunca
    ofrece un nivel inferior al vigente (CA-16) ni por encima del techo v1 (CA-16/§11.3)."""
    from core.security_manager import security_manager

    result = []
    for row in _SECURITY_ROWS_V1:
        effective_levels = [security_manager.classify_action(k) for k in row["keys"]]
        if any(level is None for level in effective_levels):
            logger.warning(f"Fila de seguridad '{row['id']}' tiene una clave sin clasificar — omitida (CA-05)")
            continue
        # Defensivo: si por algún motivo las claves de una misma fila quedaran
        # desalineadas, se muestra la más conservadora (mínimo), nunca la más permisiva.
        effective = min(effective_levels, key=lambda l: _RISK_LEVEL_ORDER[l])
        base_levels = [
            b for b in (security_manager.classify_action_base(k) for k in row["keys"]) if b is not None
        ]
        base = min(base_levels, key=lambda l: _RISK_LEVEL_ORDER[l]) if base_levels else effective

        current_rank = _RISK_LEVEL_ORDER[effective]
        ceiling_rank = max(current_rank, _RISK_LEVEL_ORDER[_V1_MAX_OFFERABLE_LEVEL])
        options = _ORDERED_LEVEL_VALUES[current_rank:ceiling_rank + 1]

        result.append({
            "row_id": row["id"], "label": row["label"], "description": row["description"],
            "effective_level": effective.value,
            "base_level": base.value,
            "options": options,
        })
    return result
