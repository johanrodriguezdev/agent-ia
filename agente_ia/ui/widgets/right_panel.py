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

from PyQt6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from ui.widgets.quick_actions_card import QuickActionsCard
from ui.widgets.recent_activity_card import RecentActivityCard
from ui.widgets.system_status_card import SystemStatusCard
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
        self.setStyleSheet("#RightPanel { background-color: transparent; }")
