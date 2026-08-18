"""
ui/widgets/conversation_list.py
Lista de conversaciones del sidebar (REQ-013/CA-05, CA-06, CA-07, CA-10).

Widget de PRESENTACIÓN pura: no consulta SQLite ni conoce `memory`. `ui/gui.py` carga los
datos vía `run_async()` y se los entrega ya materializados con `set_conversations()`, para
que el hilo de la GUI nunca haga I/O de base de datos (caso borde de la SPEC: cientos de
conversaciones no deben retrasar el arranque).

Vive en su propio módulo — y no dentro de `sidebar.py` — porque es lo único de la barra con
estado dinámico y con pruebas propias; `Sidebar` queda como contenedor declarativo.
"""

from string import Template
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from ui.theme import Palette, qss_tokens, register_themed

_NEW_CONVERSATION_TEXT = "＋  Nueva conversación"
_MORE_TEXT = "Ver más"
_EMPTY_TEXT = "Sin conversaciones todavía"

# `Qt.ItemDataRole.UserRole` guarda el `conversation_id` de cada fila: el texto visible es
# un título truncado y no sirve como identificador.
_ID_ROLE = Qt.ItemDataRole.UserRole


class ConversationList(QWidget):
    """Botón "Nueva conversación" + lista + botón "Ver más"."""

    conversation_selected = pyqtSignal(str)
    new_conversation_requested = pyqtSignal()
    more_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ConversationList")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._new_button = QPushButton(_NEW_CONVERSATION_TEXT)
        self._new_button.setObjectName("NewConversationButton")
        self._new_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_button.clicked.connect(self.new_conversation_requested.emit)
        layout.addWidget(self._new_button)

        self._list = QListWidget()
        self._list.setObjectName("ConversationItems")
        self._list.setFrameShape(QListWidget.Shape.NoFrame)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list, 1)

        self._more_button = QPushButton(_MORE_TEXT)
        self._more_button.setObjectName("MoreConversationsButton")
        self._more_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_button.clicked.connect(self.more_requested.emit)
        self._more_button.setVisible(False)
        layout.addWidget(self._more_button)

        register_themed(self)

    # ------------------------------------------------------------------ API
    def set_conversations(self, items, append: bool = False) -> None:
        """Puebla la lista con `ConversationSummary`s.

        `append=True` agrega una página al final (paginación "Ver más") en vez de
        reemplazar lo mostrado.
        """
        active = self.active_conversation()
        if not append:
            self._list.clear()

        for summary in items:
            conversation_id = getattr(summary, "conversation_id", "")
            if not conversation_id:
                continue
            entry = QListWidgetItem(getattr(summary, "title", "") or "(sin título)")
            entry.setData(_ID_ROLE, conversation_id)
            entry.setToolTip(getattr(summary, "title", ""))
            self._list.addItem(entry)

        if self._list.count() == 0:
            placeholder = QListWidgetItem(_EMPTY_TEXT)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(placeholder)
        elif active:
            self.set_active(active)

    def set_active(self, conversation_id: Optional[str]) -> None:
        """Marca la conversación abierta. `None` deselecciona todo (conversación nueva)."""
        if conversation_id is None:
            self._list.clearSelection()
            self._list.setCurrentItem(None)
            return
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(_ID_ROLE) == conversation_id:
                self._list.setCurrentItem(item)
                return
        self._list.clearSelection()

    def active_conversation(self) -> Optional[str]:
        item = self._list.currentItem()
        return item.data(_ID_ROLE) if item is not None else None

    def conversation_ids(self) -> List[str]:
        """Ids actualmente mostrados, en orden (lo usa `ui/gui.py` para el `offset`)."""
        ids = []
        for index in range(self._list.count()):
            conversation_id = self._list.item(index).data(_ID_ROLE)
            if conversation_id:
                ids.append(conversation_id)
        return ids

    def count(self) -> int:
        return len(self.conversation_ids())

    def set_has_more(self, has_more: bool) -> None:
        self._more_button.setVisible(bool(has_more))

    def apply_theme(self, palette: Palette) -> None:
        """REQ-013/CA-01 — reestiliza la lista con la paleta activa."""
        self.setStyleSheet(_qss(palette))

    # -------------------------------------------------------------- internos
    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        conversation_id = item.data(_ID_ROLE)
        if conversation_id:
            self.conversation_selected.emit(conversation_id)


# REQ-013: `string.Template` con `$token`, NUNCA `str.format()` (ver `ui/theme.py`).
_QSS_TEMPLATE = Template("""
#ConversationList { background-color: transparent; }
#NewConversationButton {
    color: $accent; background-color: $accent_soft; border: 1px solid $border;
    border-radius: 8px; padding: 8px 10px; font-size: 12px; text-align: left;
}
#NewConversationButton:hover { background-color: $bg_hover; }
#ConversationItems {
    background-color: transparent; border: none; color: $text_secondary; font-size: 12px;
}
#ConversationItems::item { padding: 7px 10px; border-radius: 8px; }
#ConversationItems::item:hover { background-color: $bg_hover; color: $text_primary; }
#ConversationItems::item:selected { background-color: $accent_soft; color: $text_primary; }
#MoreConversationsButton {
    color: $text_muted; background-color: transparent; border: none;
    padding: 6px; font-size: 11px;
}
#MoreConversationsButton:hover { color: $accent; }
QScrollBar:vertical { background: transparent; width: 6px; margin: 0px; }
QScrollBar::handle:vertical { background: $scroll_handle; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
""")


def _qss(palette: Palette) -> str:
    return _QSS_TEMPLATE.substitute(qss_tokens(palette))
