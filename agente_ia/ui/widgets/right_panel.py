"""
ui/widgets/right_panel.py
Panel derecho (~350px) del mockup (REQ-008/CA-02): apila las 4 tarjetas — Estado del
sistema, Accesos rápidos, Actividad reciente, Clima — dentro de un `QScrollArea`.

Decisión de implementación: cada tarjeta (`SystemStatusCard`, `QuickActionsCard`,
`RecentActivityCard`, `WeatherCard`) se estiliza a sí misma (`objectName("Card")` +
QSS propio) en vez de recibir un frame externo de un helper `_make_card_frame()`
compartido. Esto mantiene cada tarjeta 100% autocontenida y testeable de forma aislada
sin levantar `RightPanel` (ver "Pruebas sugeridas" de arquitectura-008.md, p. ej.
`SystemStatusCard().set_values(18, 42, 31, 12)` sin dependencias); el helper original
habría sido una capa de envoltura redundante sobre tarjetas que ya son `QFrame`
completos. Documentado en desarrollo-log-008.md.
"""

from string import Template

from PyQt6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from ui.widgets.quick_actions_card import QuickActionsCard
from ui.widgets.recent_activity_card import RecentActivityCard
from ui.widgets.system_status_card import SystemStatusCard
from ui.theme import Palette, qss_tokens, register_themed
from ui.widgets.weather_card import WeatherCard


class RightPanel(QFrame):
    """Panel derecho. Se puebla una vez en `__init__` — `SystemStatusCard` arranca su
    propio `QTimer`, `RecentActivityCard` consulta memoria una vez, `WeatherCard`
    dispara su propio `run_async()`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RightPanel")
        self.setFixedWidth(350)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 24, 16, 16)
        layout.setSpacing(16)

        self.system_status_card = SystemStatusCard()
        layout.addWidget(self.system_status_card)

        self.quick_actions_card = QuickActionsCard()
        layout.addWidget(self.quick_actions_card)

        self.recent_activity_card = RecentActivityCard()
        layout.addWidget(self.recent_activity_card)

        self.weather_card = WeatherCard()
        layout.addWidget(self.weather_card)

        layout.addStretch(1)
        scroll.setWidget(content)
        register_themed(self)

    def apply_theme(self, palette: Palette) -> None:
        """REQ-013/CA-01 - estiliza el contenedor y su scroll. Las 4 tarjetas se
        registran solas en el `ThemeManager`, no se propaga nada a mano."""
        self.setStyleSheet(_qss(palette))


# REQ-013: `string.Template` con `$token`, NUNCA `str.format()` (ver `ui/theme.py`).
_QSS_TEMPLATE = Template("""
#RightPanel { background-color: transparent; }
QScrollArea { background-color: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0px; }
QScrollBar::handle:vertical { background: $scroll_handle; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
""")


def _qss(palette: Palette) -> str:
    return _QSS_TEMPLATE.substitute(qss_tokens(palette))
