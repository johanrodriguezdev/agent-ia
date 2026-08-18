"""
ui/widgets/composer.py
Barra de composición inferior (REQ-013/CA-17, CA-18, CA-19, CA-16).

Contiene la fila de chips de accesos directos, el input de comando, el toggle de modo
manos libres (movido acá desde `CenterPanel` en REQ-013) y el botón de enviar.

Los chips de tipo `action` NUNCA importan ni llaman la función subyacente: pasan
exclusivamente por `run_async(execute_action, ..., channel=ChannelType.DESKTOP)`, igual
que `QuickActionsCard`, para que el gate fail-closed de `core/security_manager.py` se
ejecute como en cualquier otro canal (CA-19, `.claude/rules/security-levels.md`).

El resultado de un chip de acción se muestra en `ComposerActionStatus` y NO se persiste ni
se convierte en burbuja: no pasó por `resolve()`, así que no es un turno de conversación —
mezclarlo en el feed haría que el historial guardado y el feed visible dejaran de coincidir
al recargar la conversación.

REQ-013 (3ra pasada, fix condición de carrera CA-09): `set_input_enabled(False)` bloquea
`_input`/`_send_button` mientras `JarvisMainWindow` tiene una resolución en curso, para que
sea físicamente imposible emitir un segundo `command_submitted` que pise
`_pending_user_text` de la ventana antes de que se persista el primer turno (ver
qa-audit-013.md). Con el input deshabilitado, `_input.returnPressed` no se dispara y
`_send_button.clicked` no se dispara — no hace falta un guard adicional en `_emit_command`.
"""

from string import Template

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from agents.action_registry import execute_action
from core.security_manager import ChannelType
from ui.gui_workers import run_async
from ui.theme import Palette, qss_tokens, register_themed

# REQ-009/CA-01: texto/tooltip del toggle de modo manos libres por estado. Movidos desde
# `center_panel.py` junto con el widget; el comportamiento no cambia.
_WAKE_TOGGLE_TEXT = {
    "INACTIVE": "🎙",
    "LISTENING_WAKE": "🎙",
    "AWAKE": "🎙",
}
_WAKE_TOGGLE_TOOLTIP = {
    "INACTIVE": "Modo manos libres: inactivo",
    "LISTENING_WAKE": "Modo manos libres: escuchando wake word",
    "AWAKE": "Modo manos libres: despierto",
}

# REQ-013 (3ra pasada)/CA-09, CA-16: placeholder mostrado mientras `set_input_enabled(False)`
# bloquea el envío — feedback visual explícito de que el composer está ocupado resolviendo.
_PLACEHOLDER_IDLE = "Escribe un comando o habla con Noddoo..."
_PLACEHOLDER_BUSY = "Noddoo está pensando..."

# CA-18: `template` precarga el input y deja al usuario completar/enviar; `action` ejecuta
# una acción del registro. Ningún chip envía un comando por su cuenta.
_CHIPS = [
    {"label": "Resumen del día", "kind": "template",
     "payload": "Dame un resumen de mi actividad reciente y tareas pendientes"},
    {"label": "Recuérdame algo", "kind": "template", "payload": "Recuérdame que "},
    {"label": "Investigación rápida", "kind": "template", "payload": "Investiga sobre "},
    {"label": "📷 Captura de pantalla", "kind": "action", "payload": "take_screenshot"},
    {"label": "🌐 Abrir navegador", "kind": "action", "payload": "open_browser"},
]


class Composer(QFrame):
    """Fila de chips + input + toggle manos libres + enviar."""

    command_submitted = pyqtSignal(str)
    hands_free_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Composer")
        self._updating_wake_toggle = False
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 8, 24, 16)
        outer.setSpacing(8)

        outer.addWidget(self._build_chips_row())

        self._action_status = QLabel("")
        self._action_status.setObjectName("ComposerActionStatus")
        self._action_status.setWordWrap(True)
        outer.addWidget(self._action_status)

        command_row = QHBoxLayout()
        command_row.setSpacing(8)

        self._input = QLineEdit()
        self._input.setObjectName("CommandInput")
        self._input.setPlaceholderText(_PLACEHOLDER_IDLE)
        self._input.returnPressed.connect(self._emit_command)
        command_row.addWidget(self._input)

        self._wake_toggle = QPushButton(_WAKE_TOGGLE_TEXT["INACTIVE"])
        self._wake_toggle.setObjectName("WakeToggleButton")
        self._wake_toggle.setCheckable(True)
        self._wake_toggle.setChecked(False)
        self._wake_toggle.setToolTip(_WAKE_TOGGLE_TOOLTIP["INACTIVE"])
        self._wake_toggle.setProperty("wakeState", "INACTIVE")
        self._wake_toggle.toggled.connect(self._on_wake_toggle_clicked)
        command_row.addWidget(self._wake_toggle)

        self._send_button = QPushButton("➤")
        self._send_button.setObjectName("CommandSendButton")
        self._send_button.clicked.connect(self._emit_command)
        command_row.addWidget(self._send_button)

        outer.addLayout(command_row)
        register_themed(self)

    def _build_chips_row(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("ChipsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(44)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("ChipsRow")
        row = QHBoxLayout(content)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(8)

        self._chip_buttons = []
        for chip in _CHIPS:
            button = QPushButton(chip["label"])
            button.setObjectName("ComposerChip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("chipKind", chip["kind"])
            button.clicked.connect(
                lambda _checked, c=chip: self._on_chip_clicked(c)
            )
            row.addWidget(button)
            self._chip_buttons.append(button)

        row.addStretch(1)
        scroll.setWidget(content)
        return scroll

    # ------------------------------------------------------------------ API
    def text(self) -> str:
        return self._input.text()

    def set_text(self, text: str) -> None:
        self._input.setText(text)

    def clear(self) -> None:
        self._input.clear()

    def set_wake_state(self, state: str) -> None:
        """REQ-009/CA-01, CA-03, CA-05 — refleja el estado de 3 valores del modo manos
        libres en el toggle, sin re-emitir la señal."""
        self._updating_wake_toggle = True
        try:
            self._wake_toggle.setChecked(state != "INACTIVE")
            self._wake_toggle.setToolTip(
                _WAKE_TOGGLE_TOOLTIP.get(state, _WAKE_TOGGLE_TOOLTIP["INACTIVE"])
            )
            self._wake_toggle.setProperty("wakeState", state)
            self._wake_toggle.style().unpolish(self._wake_toggle)
            self._wake_toggle.style().polish(self._wake_toggle)
        finally:
            self._updating_wake_toggle = False

    def apply_theme(self, palette: Palette) -> None:
        """REQ-013/CA-01 — reestiliza el composer con la paleta activa."""
        self.setStyleSheet(_qss(palette))

    def set_input_enabled(self, enabled: bool) -> None:
        """REQ-013 (3ra pasada)/CA-09, CA-16 — bloquea `_input`/`_send_button` mientras hay
        una resolución en curso (ver docstring del módulo). Con el widget deshabilitado Qt
        no entrega `returnPressed` ni `clicked`, así que un segundo envío queda descartado
        por construcción, no solo oculto tras un guard.

        Cambia también el placeholder para que quede explícito por qué el input no responde
        (feedback visual, no solo funcional) — sin esto el usuario podría creer que la app
        se colgó."""
        self._input.setEnabled(enabled)
        self._send_button.setEnabled(enabled)
        self._input.setPlaceholderText(_PLACEHOLDER_IDLE if enabled else _PLACEHOLDER_BUSY)

    # -------------------------------------------------------------- internos
    def _emit_command(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.command_submitted.emit(text)

    def _on_wake_toggle_clicked(self, checked: bool) -> None:
        """REQ-009/CA-03, CA-05 — reemite el clic del usuario como `hands_free_toggled`.

        No se re-emite cuando el cambio viene de `set_wake_state()` (guard
        `_updating_wake_toggle`), para no generar un loop de señales entre el estado
        reflejado por polling y el clic real del usuario."""
        if self._updating_wake_toggle:
            return
        self.hands_free_toggled.emit(checked)

    def _on_chip_clicked(self, chip: dict) -> None:
        if chip["kind"] == "template":
            self._input.setText(chip["payload"])
            self._input.setFocus()
            self._input.setCursorPosition(len(chip["payload"]))
            return

        self._action_status.setText("Ejecutando...")
        run_async(
            execute_action,
            self._on_action_done,
            self._on_action_error,
            chip["payload"],
            channel=ChannelType.DESKTOP,
            user_id="default",
        )

    def _on_action_done(self, result: object) -> None:
        self._action_status.setText(str(result))

    def _on_action_error(self, message: str) -> None:
        self._action_status.setText(f"Error: {message}")


# REQ-013: `string.Template` con `$token`, NUNCA `str.format()` (ver `ui/theme.py`).
_QSS_TEMPLATE = Template("""
#Composer { background-color: transparent; }
#ChipsScroll, #ChipsRow { background-color: transparent; border: none; }
#ComposerChip {
    color: $text_secondary; background-color: $bg_elevated; border: 1px solid $border;
    border-radius: 14px; padding: 5px 12px; font-size: 11px;
}
#ComposerChip:hover { color: $text_primary; background-color: $bg_hover; border-color: $accent; }
#ComposerActionStatus { color: $text_muted; font-size: 11px; }
#CommandInput {
    background-color: $bg_input; color: $text_primary; border: 1px solid $border;
    border-radius: 22px; padding: 10px 18px; font-size: 13px;
}
#CommandInput:focus { border: 1px solid $accent; }
#CommandSendButton {
    background-color: $bg_input; color: $accent; border: 1px solid $border;
    border-radius: 22px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px;
}
#CommandSendButton:hover { background-color: $bg_hover; }
#WakeToggleButton {
    background-color: $bg_input; color: $text_secondary; border: 1px solid $border;
    border-radius: 22px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px;
    font-size: 16px;
}
#WakeToggleButton[wakeState="LISTENING_WAKE"] { color: $accent; border: 1px solid $accent; }
#WakeToggleButton[wakeState="AWAKE"] { color: $success; border: 1px solid $success; }
QScrollBar:horizontal { background: transparent; height: 6px; margin: 0px; }
QScrollBar::handle:horizontal { background: $scroll_handle; border-radius: 3px; min-width: 24px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
""")


def _qss(palette: Palette) -> str:
    return _QSS_TEMPLATE.substitute(qss_tokens(palette))
