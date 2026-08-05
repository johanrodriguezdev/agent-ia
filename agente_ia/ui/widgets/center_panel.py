"""
ui/widgets/center_panel.py
Zona central del mockup (REQ-008/CA-02, CA-03, CA-04, CA-11, CA-12): saludo dinámico,
subtítulo, visualizador de voz (`VoiceOrb`), texto de estado y barra de comando conectada
al mismo pipeline de resolución que usa `ui/cli.py` (`core/resolution.py:resolve()`).
"""

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

import config_manager
from ui.personality import get_time_based_greeting
from ui.widgets.voice_orb import VoiceOrb

_STATE_STATUS_TEXT = {
    "IDLE": "En espera...",
    "LISTENING": "Escuchando...",
    "PROCESSING": "Procesando...",
    "RESPONDING": "Respondiendo...",
}

# REQ-009/CA-01: texto/tooltip del toggle de modo manos libres por estado.
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


def _resolve_display_name() -> str:
    """Cadena de resolución de CA-04: config (`display_name`) → variable de entorno del
    SO (`USERNAME`) → sin nombre. Nunca hardcodea un nombre de persona (ver
    arquitectura-008.md, sección "Resolución de display_name")."""
    name = config_manager.get_display_name()
    if name:
        return name
    return os.environ.get("USERNAME", "")


class CenterPanel(QFrame):
    """Zona central. Señal `command_submitted(str)` emitida al enviar la barra de
    comando; `show_response(text)` para mostrar el resultado."""

    command_submitted = pyqtSignal(str)
    hands_free_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CenterPanel")
        self._updating_wake_toggle = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        display_name = _resolve_display_name()
        greeting = get_time_based_greeting(display_name)

        self._greeting_label = QLabel(greeting)
        self._greeting_label.setObjectName("GreetingLabel")
        self._greeting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._greeting_label)

        subtitle = QLabel("¿En qué puedo ayudarte hoy?")
        subtitle.setObjectName("GreetingSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(24)

        self._orb = VoiceOrb()
        orb_row = QHBoxLayout()
        orb_row.addStretch(1)
        orb_row.addWidget(self._orb)
        orb_row.addStretch(1)
        layout.addLayout(orb_row)

        self._status_label = QLabel(_STATE_STATUS_TEXT["IDLE"])
        self._status_label.setObjectName("VoiceStatusLabel")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

        layout.addStretch(1)

        command_row = QHBoxLayout()
        self._command_input = QLineEdit()
        self._command_input.setObjectName("CommandInput")
        self._command_input.setPlaceholderText("Escribe un comando o habla con Jarvis...")
        self._command_input.returnPressed.connect(self._emit_command)
        command_row.addWidget(self._command_input)

        self._wake_toggle = QPushButton(_WAKE_TOGGLE_TEXT["INACTIVE"])
        self._wake_toggle.setObjectName("WakeToggleButton")
        self._wake_toggle.setCheckable(True)
        self._wake_toggle.setChecked(False)
        self._wake_toggle.setToolTip(_WAKE_TOGGLE_TOOLTIP["INACTIVE"])
        self._wake_toggle.setProperty("wakeState", "INACTIVE")
        self._wake_toggle.toggled.connect(self._on_wake_toggle_clicked)
        command_row.addWidget(self._wake_toggle)

        send_btn = QPushButton("➤")
        send_btn.setObjectName("CommandSendButton")
        send_btn.clicked.connect(self._emit_command)
        command_row.addWidget(send_btn)
        layout.addLayout(command_row)

        self.setStyleSheet(_CENTER_QSS)

    def _emit_command(self) -> None:
        text = self._command_input.text().strip()
        if not text:
            return
        self._command_input.clear()
        self.command_submitted.emit(text)

    def set_state(self, state: str) -> None:
        self._orb.set_state(state)
        self._status_label.setText(_STATE_STATUS_TEXT.get(state, _STATE_STATUS_TEXT["IDLE"]))

    def show_response(self, text: str) -> None:
        self._status_label.setText(text[:200])

    def _on_wake_toggle_clicked(self, checked: bool) -> None:
        """REQ-009/CA-03, CA-05 — reemite el clic del usuario como `hands_free_toggled`.

        No se re-emite cuando el cambio de `checked` viene de `set_wake_state()` (guard
        `self._updating_wake_toggle`), para no generar un loop de señales entre el estado
        reflejado por polling y el clic real del usuario."""
        if self._updating_wake_toggle:
            return
        self.hands_free_toggled.emit(checked)

    def set_wake_state(self, state: str) -> None:
        """REQ-009/CA-01, CA-03, CA-05 — refleja el estado de 3 valores del modo manos
        libres (INACTIVE/LISTENING_WAKE/AWAKE) en el toggle, sin re-emitir la señal."""
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


_CENTER_QSS = """
#CenterPanel { background-color: transparent; }
#GreetingLabel { color: #ffffff; font-size: 32px; font-weight: 300; }
#GreetingSubtitle { color: #8a93a6; font-size: 14px; }
#VoiceStatusLabel { color: #4fc3ff; font-size: 13px; }
#CommandInput {
    background-color: #10182a; color: #ffffff; border: 1px solid #24304a;
    border-radius: 22px; padding: 10px 18px; font-size: 13px;
}
#CommandSendButton {
    background-color: #10182a; color: #4fc3ff; border: 1px solid #24304a;
    border-radius: 22px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px;
}
#WakeToggleButton {
    background-color: #10182a; color: #8a93a6; border: 1px solid #24304a;
    border-radius: 22px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px;
    font-size: 16px;
}
#WakeToggleButton[wakeState="LISTENING_WAKE"] {
    color: #4fc3ff; border: 1px solid #4fc3ff;
}
#WakeToggleButton[wakeState="AWAKE"] {
    color: #00e08a; border: 1px solid #00e08a;
}
"""
