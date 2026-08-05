"""
ui/widgets/header_bar.py
Header superior derecho (REQ-008/CA-02): píldora "Modo activo" reflejando los 4 estados
existentes (IDLE/LISTENING/PROCESSING/RESPONDING) + icono de notificación decorativo,
sin handler real (Asumido de SPEC-008 — no existe un sistema de notificaciones en este
REQ; ver arquitectura-008.md).
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel

_STATE_LABELS = {
    "IDLE": "Modo activo",
    "LISTENING": "Escuchando",
    "PROCESSING": "Procesando",
    "RESPONDING": "Respondiendo",
}

# REQ-009/CA-02: indicador de estado del modo manos libres, independiente de
# `_mode_pill`/`_STATE_LABELS` — nunca se pisan ni se confunden.
_WAKE_STATE_LABELS = {
    "INACTIVE": "Manos libres: inactivo",
    "LISTENING_WAKE": "Manos libres: escuchando",
    "AWAKE": "Manos libres: despierto",
}
_WAKE_STATE_ICONS = {
    "INACTIVE": "🎙",
    "LISTENING_WAKE": "🎙",
    "AWAKE": "🟢",
}


class HeaderBar(QFrame):
    """Header superior. `set_state()` refleja el mismo estado global de 4 valores que
    `VoiceOrb` — no introduce ningún concepto nuevo de "modos"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HeaderBar")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.addStretch(1)

        self._mode_pill = QLabel(f"〜  {_STATE_LABELS['IDLE']}  ›")
        self._mode_pill.setObjectName("ModePill")
        layout.addWidget(self._mode_pill)

        self._wake_indicator = QLabel(_WAKE_STATE_ICONS["INACTIVE"])
        self._wake_indicator.setObjectName("WakeIndicator")
        self._wake_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._wake_indicator.setToolTip(_WAKE_STATE_LABELS["INACTIVE"])
        self._wake_indicator.setProperty("wakeState", "INACTIVE")
        layout.addWidget(self._wake_indicator)

        bell = QLabel("🔔")
        bell.setObjectName("NotificationBell")
        bell.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(bell)

        self.setStyleSheet(_HEADER_QSS)

    def set_state(self, state: str) -> None:
        label = _STATE_LABELS.get(state, _STATE_LABELS["IDLE"])
        self._mode_pill.setText(f"〜  {label}  ›")

    def set_wake_state(self, state: str) -> None:
        """REQ-009/CA-02 — refleja el estado de 3 valores del modo manos libres en
        `_wake_indicator`, sin tocar `_mode_pill` (widget e icono separados)."""
        icon = _WAKE_STATE_ICONS.get(state, _WAKE_STATE_ICONS["INACTIVE"])
        label = _WAKE_STATE_LABELS.get(state, _WAKE_STATE_LABELS["INACTIVE"])
        self._wake_indicator.setText(icon)
        self._wake_indicator.setToolTip(label)
        self._wake_indicator.setProperty("wakeState", state)
        self._wake_indicator.style().unpolish(self._wake_indicator)
        self._wake_indicator.style().polish(self._wake_indicator)


_HEADER_QSS = """
#HeaderBar { background-color: transparent; }
#ModePill {
    color: #4fc3ff; background-color: rgba(20, 40, 70, 0.6);
    border: 1px solid #234; border-radius: 16px; padding: 6px 16px; font-size: 12px;
}
#NotificationBell {
    color: #8a93a6; background-color: #121a2b; border-radius: 16px;
    min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
    margin-left: 8px;
}
#WakeIndicator {
    color: #8a93a6; background-color: #121a2b; border-radius: 16px;
    min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
    margin-left: 8px; font-size: 14px;
}
#WakeIndicator[wakeState="LISTENING_WAKE"] { color: #4fc3ff; background-color: rgba(20, 40, 70, 0.6); }
#WakeIndicator[wakeState="AWAKE"] { color: #00e08a; background-color: rgba(0, 60, 40, 0.6); }
"""
