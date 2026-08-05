"""
ui/widgets/sidebar.py
Sidebar izquierdo (~250px) del mockup JARVIS (REQ-008/CA-02, CA-05): logo + nombre de
agente dinámico, navegación de 7 ítems (solo "Inicio" funcional) e indicador
"Sistema activo".
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from config_manager import get_agent_name

_NAV_ITEMS = [
    ("inicio", "🏠  Inicio", True),
    ("conversaciones", "💬  Conversaciones", False),
    ("memoria", "🧠  Memoria", False),
    ("tareas", "✅  Tareas", False),
    ("archivos", "📁  Archivos", False),
    ("aplicaciones", "🔳  Aplicaciones", False),
    ("configuracion", "⚙️  Configuración", False),
]


class Sidebar(QFrame):
    """Sidebar izquierdo. Señal `nav_selected(str)` emitida solo por el ítem "Inicio"
    (REQ-008/CA-05: los otros 6 ítems son visibles pero no funcionales —
    `setEnabled(False)`, sin handler conectado, tal como aprueba arquitectura-008.md)."""

    nav_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(250)
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

        layout.addStretch(1)

        status_dot = QLabel("●  Sistema activo")
        status_dot.setObjectName("SidebarStatusActive")
        layout.addWidget(status_dot)

        status_sub = QLabel("Todo funcionando correctamente")
        status_sub.setObjectName("SidebarStatusSub")
        layout.addWidget(status_sub)

        self.setStyleSheet(_SIDEBAR_QSS)


_SIDEBAR_QSS = """
#Sidebar { background-color: #0d1220; border-right: 1px solid #1a2333; }
#SidebarLogo { color: #ffffff; font-size: 18px; font-weight: 600; letter-spacing: 2px; }
#SidebarNavButton {
    color: #8a93a6; background-color: transparent; border: none;
    text-align: left; padding: 10px 12px; border-radius: 8px; font-size: 13px;
}
#SidebarNavButton:enabled { color: #ffffff; background-color: rgba(79, 195, 255, 0.12); }
#SidebarNavButton:disabled { color: #555f73; }
#SidebarStatusActive { color: #33d17a; font-size: 12px; }
#SidebarStatusSub { color: #5a6478; font-size: 11px; }
"""
