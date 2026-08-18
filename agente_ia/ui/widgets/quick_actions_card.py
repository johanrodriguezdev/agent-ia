"""
ui/widgets/quick_actions_card.py
Tarjeta "Accesos rápidos" (REQ-008/CA-07, CA-08): grid 2x3 de botones mapeados a
`agents/action_registry.py:ACTION_REGISTRY`. Cada click pasa EXCLUSIVAMENTE por
`run_async(execute_action, ...)` con `channel=ChannelType.DESKTOP` explícito — nunca
invoca la función subyacente directo, para que el gate de seguridad fail-closed de
`core/security_manager.py` se ejecute igual que en cualquier otro canal.
"""

from string import Template

from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QVBoxLayout

from agents.action_registry import execute_action
from core.security_manager import ChannelType
from ui.gui_workers import run_async
from ui.theme import Palette, qss_tokens, register_themed

_QUICK_ACTIONS = [
    ("open_explorer", "📁", "Explorador"),
    ("open_browser", "🌐", "Navegador"),
    ("open_notepad", "📝", "Notas"),
    ("open_calculator", "🧮", "Calculadora"),
    ("take_screenshot", "📷", "Captura"),
    ("open_spotify", "🎵", "Spotify"),
]


class QuickActionsCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(8)

        title = QLabel("Accesos rápidos")
        title.setObjectName("CardTitle")
        outer.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (action_name, icon, label) in enumerate(_QUICK_ACTIONS):
            btn = QPushButton(f"{icon}\n{label}")
            btn.setObjectName("QuickActionButton")
            btn.clicked.connect(lambda _checked, name=action_name: self._run_action(name))
            grid.addWidget(btn, i // 2, i % 2)
        outer.addLayout(grid)

        self._status_label = QLabel("")
        self._status_label.setObjectName("QuickActionsStatus")
        self._status_label.setWordWrap(True)
        outer.addWidget(self._status_label)
        register_themed(self)

    def apply_theme(self, palette: Palette) -> None:
        """REQ-013/CA-01 - reestiliza la tarjeta con la paleta activa."""
        self.setStyleSheet(_qss(palette))

    def _run_action(self, action_name: str) -> None:
        run_async(
            execute_action,
            self._on_action_done,
            self._on_action_error,
            action_name,
            channel=ChannelType.DESKTOP,
            user_id="default",
        )

    def _on_action_done(self, result: object) -> None:
        self._status_label.setText(str(result))

    def _on_action_error(self, message: str) -> None:
        self._status_label.setText(f"Error: {message}")


# REQ-013: `string.Template` con `$token`, NUNCA `str.format()` (ver `ui/theme.py`).
_QSS_TEMPLATE = Template("""
#Card { background-color: $bg_elevated; border-radius: 14px; }
#CardTitle { color: $text_primary; font-size: 14px; font-weight: 600; }
#QuickActionButton {
    color: $text_secondary; background-color: $bg_input; border: 1px solid $border;
    border-radius: 10px; padding: 10px 4px; font-size: 11px;
}
#QuickActionButton:hover { background-color: $bg_hover; color: $text_primary; }
#QuickActionsStatus { color: $text_muted; font-size: 11px; }
""")


def _qss(palette: Palette) -> str:
    return _QSS_TEMPLATE.substitute(qss_tokens(palette))
