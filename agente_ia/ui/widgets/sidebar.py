"""
ui/widgets/sidebar.py
Sidebar izquierdo (280px) del panel (REQ-008/CA-02, CA-05 · REQ-013/CA-05, CA-08): logo +
nombre de agente dinámico, navegación de 7 ítems, lista de conversaciones e indicador
"Sistema activo".

REQ-013: el ancho pasa de 250 a 280px (títulos de conversación legibles), "Conversaciones"
queda habilitado y debajo de la navegación aparece `ConversationList`. Los otros 5 ítems
siguen deshabilitados (CA-08). El sidebar solo re-emite: no consulta la base de datos.
"""

from string import Template

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from config_manager import get_agent_name
from ui.theme import Palette, qss_tokens, register_themed
from ui.widgets.conversation_list import ConversationList

_NAV_ITEMS = [
    ("inicio", "🏠  Inicio", True),
    ("conversaciones", "💬  Conversaciones", True),
    ("memoria", "🧠  Memoria", False),
    ("tareas", "✅  Tareas", False),
    ("archivos", "📁  Archivos", False),
    ("aplicaciones", "🔳  Aplicaciones", False),
    ("configuracion", "⚙️  Configuración", False),
]


class Sidebar(QFrame):
    """Sidebar izquierdo. `nav_selected(str)` la emiten los ítems habilitados ("Inicio" y,
    desde REQ-013, "Conversaciones"); los otros 5 son visibles pero no funcionales —
    `setEnabled(False)`, sin handler conectado (REQ-008/CA-05, REQ-013/CA-08)."""

    nav_selected = pyqtSignal(str)
    # REQ-013: re-emisiones de `ConversationList` — `ui/gui.py` se conecta al Sidebar y
    # no necesita conocer el widget interno.
    conversation_selected = pyqtSignal(str)
    new_conversation_requested = pyqtSignal()
    more_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(280)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 24, 16, 16)
        layout.setSpacing(4)

        logo = QLabel(get_agent_name().upper())
        logo.setObjectName("SidebarLogo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)
        layout.addSpacing(24)

        for key, label, enabled in _NAV_ITEMS:
            btn = QPushButton(label)
            btn.setObjectName("SidebarNavButton")
            btn.setEnabled(enabled)
            btn.setCheckable(True)
            btn.setChecked(enabled)
            if enabled:
                btn.clicked.connect(lambda _checked, k=key: self.nav_selected.emit(k))
            layout.addWidget(btn)

        separator = QFrame()
        separator.setObjectName("SidebarSeparator")
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addSpacing(12)
        layout.addWidget(separator)
        layout.addSpacing(8)

        self._conversations = ConversationList()
        self._conversations.conversation_selected.connect(self.conversation_selected.emit)
        self._conversations.new_conversation_requested.connect(
            self.new_conversation_requested.emit
        )
        self._conversations.more_requested.connect(self.more_requested.emit)
        layout.addWidget(self._conversations, 1)

        status_dot = QLabel("●  Sistema activo")
        status_dot.setObjectName("SidebarStatusActive")
        layout.addWidget(status_dot)

        status_sub = QLabel("Todo funcionando correctamente")
        status_sub.setObjectName("SidebarStatusSub")
        layout.addWidget(status_sub)

        register_themed(self)

    # --------------------------------------------------------- conversaciones
    def set_conversations(self, items, append: bool = False) -> None:
        """REQ-013/CA-05 - delega en `ConversationList` (datos ya cargados fuera del
        hilo de la GUI por `ui/gui.py`)."""
        self._conversations.set_conversations(items, append=append)

    def set_active_conversation(self, conversation_id) -> None:
        self._conversations.set_active(conversation_id)

    def set_has_more(self, has_more: bool) -> None:
        self._conversations.set_has_more(has_more)

    def conversation_count(self) -> int:
        return self._conversations.count()

    def apply_theme(self, palette: Palette) -> None:
        """REQ-013/CA-01 — reestiliza la barra completa (la lista de conversaciones se
        estiliza sola, es un widget registrado aparte)."""
        self.setStyleSheet(_qss(palette))


# REQ-013: `string.Template` con `$token`, NUNCA `str.format()` (ver `ui/theme.py`).
_QSS_TEMPLATE = Template("""
#Sidebar { background-color: $bg_surface; border-right: 1px solid $border_subtle; }
#SidebarLogo { color: $text_primary; font-size: 18px; font-weight: 600; letter-spacing: 2px; }
#SidebarNavButton {
    color: $text_secondary; background-color: transparent; border: none;
    text-align: left; padding: 10px 12px; border-radius: 8px; font-size: 13px;
}
#SidebarNavButton:enabled { color: $text_primary; background-color: $accent_soft; }
#SidebarNavButton:disabled { color: $text_disabled; }
#SidebarSeparator { background-color: $border_subtle; max-height: 1px; min-height: 1px; }
#SidebarStatusActive { color: $success; font-size: 12px; }
#SidebarStatusSub { color: $text_muted; font-size: 11px; }
""")


def _qss(palette: Palette) -> str:
    return _QSS_TEMPLATE.substitute(qss_tokens(palette))
