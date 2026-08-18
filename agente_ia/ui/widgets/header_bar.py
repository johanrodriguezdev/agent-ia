"""
ui/widgets/header_bar.py
Header superior derecho (REQ-008/CA-02): píldora "Modo activo" reflejando los 4 estados
existentes (IDLE/LISTENING/PROCESSING/RESPONDING) + icono de notificación decorativo,
sin handler real (Asumido de SPEC-008 — no existe un sistema de notificaciones en este
REQ; ver arquitectura-008.md).
"""

from string import Template

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from ui.theme import Palette, qss_tokens, register_themed, theme_manager

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

# REQ-013/CA-01: icono y tooltip del selector de tema. La clave es el tema ACTIVO; el
# texto describe hacia dónde lleva el clic.
_THEME_TOGGLE_ICON = {"dark": "☀", "light": "🌙"}
_THEME_TOGGLE_TOOLTIP = {
    "dark": "Cambiar a tema claro",
    "light": "Cambiar a tema oscuro",
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

        # A la IZQUIERDA de `_mode_pill`: los tres indicadores de estado de voz quedan
        # agrupados y el control de preferencia queda separado de ellos (arquitectura §2).
        self._theme_toggle = QPushButton()
        self._theme_toggle.setObjectName("ThemeToggle")
        self._theme_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_toggle.clicked.connect(self._on_theme_toggle_clicked)
        self._sync_theme_toggle()
        layout.addWidget(self._theme_toggle)

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

        register_themed(self)

    def apply_theme(self, palette: Palette) -> None:
        """REQ-013/CA-01 — reestiliza el header y resincroniza el icono del selector."""
        self.setStyleSheet(_qss(palette))
        self._sync_theme_toggle()

    def _on_theme_toggle_clicked(self) -> None:
        """Delega en el `ThemeManager`; el icono se actualiza por la señal `theme_changed`
        (vía `apply_theme`), no acá — así queda sincronizado aunque el tema cambie desde
        otro lugar."""
        theme_manager.toggle()

    def _sync_theme_toggle(self) -> None:
        name = theme_manager.current_name()
        self._theme_toggle.setText(_THEME_TOGGLE_ICON.get(name, "☀"))
        self._theme_toggle.setToolTip(_THEME_TOGGLE_TOOLTIP.get(name, ""))

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


# REQ-013: `string.Template` con `$token`, NUNCA `str.format()` — el QSS está lleno de
# llaves `{ }` (ver el docstring de `ui/theme.py`).
_QSS_TEMPLATE = Template("""
#HeaderBar { background-color: transparent; }
#ThemeToggle {
    color: $text_secondary; background-color: $bg_elevated; border: 1px solid $border;
    border-radius: 16px; min-width: 32px; max-width: 32px;
    min-height: 32px; max-height: 32px; margin-right: 8px; font-size: 14px;
}
#ThemeToggle:hover { color: $accent; background-color: $bg_hover; }
#ModePill {
    color: $accent; background-color: $accent_soft;
    border: 1px solid $border; border-radius: 16px; padding: 6px 16px; font-size: 12px;
}
#NotificationBell {
    color: $text_secondary; background-color: $bg_elevated; border-radius: 16px;
    min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
    margin-left: 8px;
}
#WakeIndicator {
    color: $text_secondary; background-color: $bg_elevated; border-radius: 16px;
    min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
    margin-left: 8px; font-size: 14px;
}
#WakeIndicator[wakeState="LISTENING_WAKE"] { color: $accent; background-color: $accent_soft; }
#WakeIndicator[wakeState="AWAKE"] { color: $success; background-color: $bg_hover; }
""")


def _qss(palette: Palette) -> str:
    return _QSS_TEMPLATE.substitute(qss_tokens(palette))
