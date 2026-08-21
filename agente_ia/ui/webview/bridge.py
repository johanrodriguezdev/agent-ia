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
from datetime import datetime
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QThreadPool, Qt, pyqtSignal, pyqtSlot

import config_manager
from core.security_manager import ChannelType, RiskLevel, _RISK_LEVEL_ORDER
from ui.gui_workers import run_async
from ui.webview.gui_state import GLOBAL_STATE, WAKE_STATE  # noqa: F401 (ver poll_state)
from ui.webview.markdown_render import render_markdown
from ui.webview.theme import resolve_theme_name
from ui.webview.wake_word_worker import WakeWordWorker

logger = logging.getLogger(__name__)

# REQ-013: mismo tamaño de página del listado de conversaciones del sidebar, portado tal
# cual — ver docstring del módulo, nota sobre `conversation_list_updated`.
_CONVERSATION_PAGE_SIZE = 30

# CA-39: los 5 chips de `ui/widgets/composer.py::_CHIPS` (REQ-013, eliminado), portados
# con el mismo contenido literal (arquitectura-015.md §1, fila CA-39).
_CHIPS: List[Dict[str, str]] = [
    {"label": "Resumen del día", "kind": "template",
     "payload": "Dame un resumen de mi actividad reciente y tareas pendientes"},
    {"label": "Recuérdame algo", "kind": "template", "payload": "Recuérdame que "},
    {"label": "Investigación rápida", "kind": "template", "payload": "Investiga sobre "},
    {"label": "📷 Captura de pantalla", "kind": "action", "payload": "take_screenshot"},
    {"label": "🌐 Abrir navegador", "kind": "action", "payload": "open_browser"},
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
    typing_started = pyqtSignal()
    typing_stopped = pyqtSignal()
    gui_state_changed = pyqtSignal(str)
    wake_state_changed = pyqtSignal(str)
    theme_changed = pyqtSignal(str)
    confirmation_requested = pyqtSignal(str, str, str)   # request_id, action_name, message
    file_attached = pyqtSignal(str, str, bool, str)      # path, name, accepted, reason
    chips_loaded = pyqtSignal(str)                   # json: [{label, kind, payload, risk_level}]
    error_occurred = pyqtSignal(str)

    # ------------------------------------------------------------ Python → JS (REQ-016)
    tasks_loaded = pyqtSignal(str)                   # json: lista cruda de task_manager.list_all_tasks()
    projects_loaded = pyqtSignal(str)                # json: [{id, name, created_at, conversation_count}]
    project_conversations_loaded = pyqtSignal(str, int)  # json (shape de conversation_list_updated), project_id
    project_removed = pyqtSignal(int)                # project_id

    # ------------------------------------------------------------ Python → JS (REQ-019)
    security_overrides_loaded = pyqtSignal(str)       # json: [{row_id, label, description, effective_level, base_level, options}]
    security_override_saved = pyqtSignal(str, str)    # row_id, nuevo_nivel — CA-10
    security_override_save_rejected = pyqtSignal(str)  # row_id — CA-21

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self._confirmation_adapter = None  # asignado por MainWindow tras construirse (§4.3)

        self._conversation_id: Optional[str] = None
        self._pending_user_text: str = ""
        self._resolution_in_flight: bool = False
        self._pending_conversation_offset: int = 0

        self._wake_worker: Optional[WakeWordWorker] = None
        self._current_gui_state: str = GLOBAL_STATE
        self._current_wake_state: str = WAKE_STATE

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
        self.chips_loaded.emit(json.dumps(_build_chips_payload()))
        self.theme_changed.emit(resolve_theme_name(config_manager.get_ui_theme()))
        self._load_conversations(offset=0)

    # ------------------------------------------------------------ mensajes (§4.1)
    @pyqtSlot(str)
    def send_message(self, text: str) -> None:
        """CA-20..CA-24 — guarda `text` como pendiente, deshabilita envío (guard
        server-side, CA-24: el bridge es invocable desde JS sin pasar por el estado
        `disabled` del DOM, a diferencia de un `QWidget` deshabilitado) y resuelve."""
        if self._resolution_in_flight:
            logger.warning("send_message() ignorado: ya hay una resolución en curso")
            return
        if not text:
            return

        self._pending_user_text = text
        self._resolution_in_flight = True
        self.message_appended.emit(json.dumps({
            "role": "user", "html": render_markdown(text), "timestamp": _now_iso(),
        }))
        self.typing_started.emit()

        from core.resolution import resolve
        run_async(resolve, self._on_resolve_done, self._on_resolve_error, text,
                   ChannelType.DESKTOP, user_id="default")

    def _on_resolve_done(self, resolution) -> None:
        from ai.memory_manager import memory

        result_text = resolution.text
        self.message_appended.emit(json.dumps({
            "role": "assistant", "html": render_markdown(result_text), "timestamp": _now_iso(),
        }))
        self.typing_stopped.emit()

        conversation_id = self._ensure_conversation_id()
        run_async(
            memory.store_turn, None, None,
            self._pending_user_text, result_text, conversation_id,
            user_id="default", matched_by=getattr(resolution, "matched_by", ""),
        )
        self._pending_user_text = ""
        self._resolution_in_flight = False
        self._load_conversations(offset=0)

    def _on_resolve_error(self, message: str) -> None:
        """Un error no es una respuesta de la IA — no se persiste (mismo criterio que
        `JarvisMainWindow._on_command_error()`, REQ-013/eliminado)."""
        self.message_appended.emit(json.dumps({
            "role": "assistant", "html": render_markdown(f"Error: {message}"),
            "timestamp": _now_iso(),
        }))
        self.typing_stopped.emit()
        self._pending_user_text = ""
        self._resolution_in_flight = False

    def _ensure_conversation_id(self) -> str:
        from ai.memory_manager import memory

        if not self._conversation_id:
            self._conversation_id = memory.new_conversation_id()
        return self._conversation_id

    # ------------------------------------------------------------ conversaciones (§4.1)
    @pyqtSlot()
    def new_conversation(self) -> None:
        self._conversation_id = None
        self._pending_user_text = ""
        self.conversation_cleared.emit()

    @pyqtSlot(str)
    def select_conversation(self, conversation_id: str) -> None:
        from ai.memory_manager import memory

        self._conversation_id = conversation_id
        run_async(memory.get_conversation_turns, self._on_turns_loaded, self._on_turns_error,
                  conversation_id, user_id="default")

    def _on_turns_loaded(self, turns) -> None:
        payload = [
            {
                "id": item.id, "role": item.role or "assistant",
                "html": render_markdown(item.text), "timestamp": item.timestamp,
            }
            for item in turns
        ]
        self.turns_loaded.emit(json.dumps(payload))

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
            user_id="default",
        )
        if not confirmed:
            return
        deleted = memory.delete_conversation(conversation_id, user_id="default")
        if deleted:
            memory.unassign_conversation_from_project(conversation_id, user_id="default")  # REQ-016/CA-21
            self.conversation_removed.emit(conversation_id)

    def _on_delete_error(self, message: str) -> None:
        logger.error(f"Error eliminando conversación: {message}")
        self.error_occurred.emit(message)

    def _load_conversations(self, offset: int = 0) -> None:
        from ai.memory_manager import memory

        self._pending_conversation_offset = offset
        run_async(memory.list_conversations, self._on_conversations_loaded,
                  self._on_conversations_error, user_id="default",
                  limit=_CONVERSATION_PAGE_SIZE, offset=offset)

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
        return task_manager.list_all_tasks(user_id="default")

    def _on_tasks_loaded(self, tasks) -> None:
        self.tasks_loaded.emit(json.dumps(tasks))

    def _emit_tasks_loaded(self) -> None:
        """Se llama SIEMPRE desde el hilo worker que ya está ejecutando una mutación (crear/
        completar/borrar) — nunca agenda un run_async() anidado, solo relee la lista en el
        mismo hilo y emite (mismo patrón cross-thread ya usado por
        `conversation_removed.emit()` en `_delete_conversation_flow`)."""
        from tasks.task_manager import task_manager
        tasks = task_manager.list_all_tasks(user_id="default")
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
            user_id="default", title=title, channel="desktop",
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
        task_manager.complete_task(task_id, user_id="default")
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
            user_id="default",
        )
        if not confirmed:
            return
        task_manager.delete_task(task_id, user_id="default")
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
        return memory.list_projects(user_id="default")

    def _on_projects_loaded(self, projects) -> None:
        self.projects_loaded.emit(self._projects_payload(projects))

    def _emit_projects_loaded(self) -> None:
        from ai.memory_manager import memory
        self.projects_loaded.emit(self._projects_payload(memory.list_projects(user_id="default")))

    @pyqtSlot(str)
    def create_project(self, name: str) -> None:
        """CA-14 — nombre vacío/solo espacios rechazado en el cliente Y acá (defensa en
        profundidad, mismo criterio que `send_message()` con texto vacío)."""
        if not name.strip():
            return
        run_async(self._create_project_flow, None, self._on_project_error, name.strip())

    def _create_project_flow(self, name: str) -> None:
        from ai.memory_manager import memory
        memory.create_project(user_id="default", name=name)
        self._emit_projects_loaded()

    @pyqtSlot(str, int)
    def assign_conversation_to_project(self, conversation_id: str, project_id: int) -> None:
        """CA-16, CA-20 — reasigna si ya pertenecía a otro proyecto (garantizado por la PK de
        `project_conversations`)."""
        run_async(self._assign_flow, None, self._on_project_error, conversation_id, project_id)

    def _assign_flow(self, conversation_id: str, project_id: int) -> None:
        from ai.memory_manager import memory
        memory.assign_conversation_to_project(conversation_id, project_id, user_id="default")
        self._emit_projects_loaded()

    @pyqtSlot(str)
    def unassign_conversation_from_project(self, conversation_id: str) -> None:
        """CA-16 (desasignar) — llamado desde la vista de detalle de un proyecto."""
        run_async(self._unassign_flow, None, self._on_project_error, conversation_id)

    def _unassign_flow(self, conversation_id: str) -> None:
        from ai.memory_manager import memory
        memory.unassign_conversation_from_project(conversation_id, user_id="default")
        self._emit_projects_loaded()

    @pyqtSlot(int)
    def request_project_conversations(self, project_id: int) -> None:
        """CA-17 — vista de detalle. El `project_id` viaja también en la señal de vuelta
        (`project_conversations_loaded(json, project_id)`) para que la UI descarte una
        respuesta tardía si el usuario ya cambió de proyecto (caso borde de SPEC-016: doble
        click rápido no debe mezclar datos de dos proyectos distintos)."""
        run_async(self._fetch_project_conversations, None, self._on_project_error, project_id)

    def _fetch_project_conversations(self, project_id: int) -> None:
        from ai.memory_manager import memory
        conversations = memory.list_conversations_by_project(project_id, user_id="default")
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
            user_id="default",
        )
        if not confirmed:
            return
        deleted = memory.delete_project(project_id, user_id="default")
        if deleted:
            self.project_removed.emit(project_id)   # CA-19: las conversaciones NO se tocan
            self._emit_projects_loaded()

    def _on_project_error(self, message: str) -> None:
        logger.error(f"Error en operación de proyectos: {message}")
        self.error_occurred.emit(message)

    # ------------------------------------------------------------ seguridad (REQ-019/§3.3)
    @pyqtSlot()
    def request_security_overrides(self) -> None:
        """CA-19 — carga perezosa: se llama solo al abrir la sección 'Seguridad' de la
        pantalla de Configuración, nunca desde request_initial_state()."""
        self.security_overrides_loaded.emit(json.dumps(_build_security_overrides_payload()))

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
                  action_name, channel=ChannelType.DESKTOP, user_id="default")

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
            QThreadPool.globalInstance().start(self._wake_worker)
        else:
            self._stop_wake_word_worker()

    def _stop_wake_word_worker(self) -> None:
        if self._wake_worker is not None:
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


def _build_chips_payload() -> List[Dict[str, Any]]:
    """CA-40 — `risk_level` se consulta en el momento (nunca hardcodeado): si la
    clasificación de una acción cambia, el color del chip se actualiza solo."""
    from core.security_manager import security_manager

    result = []
    for chip in _CHIPS:
        entry = dict(chip)
        if chip["kind"] == "action":
            level = security_manager.classify_action(chip["payload"])
            entry["risk_level"] = level.value if level is not None else None
        else:
            entry["risk_level"] = None
        result.append(entry)
    return result


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
