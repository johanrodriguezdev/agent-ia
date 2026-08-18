"""
ui/widgets/weather_card.py
Tarjeta de clima (REQ-008/CA-10): temperatura, condición, ciudad y hora/fecha reales de
`os_integration/weather_data.py:get_weather_structured()`. Se dispara vía `run_async()`
al construirse — I/O de red real, nunca en el hilo de la GUI.
"""

from typing import Optional

from string import Template

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

import config_manager
from os_integration.weather_data import WeatherData, get_weather_structured
from ui.gui_workers import run_async
from ui.theme import Palette, qss_tokens, register_themed

_UNAVAILABLE_TEXT = "Clima no disponible."


class WeatherCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._build_ui()
        self._fetch()

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(8)

        left = QVBoxLayout()
        title = QLabel("Clima")
        title.setObjectName("CardTitle")
        left.addWidget(title)

        self._temp_label = QLabel("--°C")
        self._temp_label.setObjectName("WeatherTemp")
        left.addWidget(self._temp_label)

        self._condition_label = QLabel("Cargando...")
        self._condition_label.setObjectName("WeatherCondition")
        left.addWidget(self._condition_label)
        outer.addLayout(left, 1)

        right = QVBoxLayout()
        self._city_label = QLabel("")
        self._city_label.setObjectName("WeatherCity")
        right.addWidget(self._city_label)

        self._datetime_label = QLabel("")
        self._datetime_label.setObjectName("WeatherDateTime")
        right.addWidget(self._datetime_label)
        outer.addLayout(right)
        register_themed(self)

    def apply_theme(self, palette: Palette) -> None:
        """REQ-013/CA-01 - reestiliza la tarjeta con la paleta activa."""
        self.setStyleSheet(_qss(palette))

    def _fetch(self) -> None:
        city = config_manager.get_weather_city()
        run_async(get_weather_structured, self._on_done, self._on_error, city)

    def _on_done(self, data: Optional[WeatherData]) -> None:
        self.set_data(data)

    def _on_error(self, _message: str) -> None:
        self.set_data(None)

    def set_data(self, data: Optional[WeatherData]) -> None:
        """`None` -> estado "no disponible" explícito; nunca deja valores de ejemplo."""
        if data is None:
            self._temp_label.setText("--°C")
            self._condition_label.setText(_UNAVAILABLE_TEXT)
            self._city_label.setText("")
            self._datetime_label.setText("")
            return
        self._temp_label.setText(f"{data.temp_c:.0f}°C")
        self._condition_label.setText(data.condition)
        self._city_label.setText(data.city)
        self._datetime_label.setText(f"{data.time_str}  ·  {data.date_str}")


# REQ-013: `string.Template` con `$token`, NUNCA `str.format()` (ver `ui/theme.py`).
_QSS_TEMPLATE = Template("""
#Card { background-color: $bg_elevated; border-radius: 14px; }
#CardTitle { color: $text_primary; font-size: 14px; font-weight: 600; }
#WeatherTemp { color: $text_primary; font-size: 26px; font-weight: 300; }
#WeatherCondition { color: $text_secondary; font-size: 12px; }
#WeatherCity { color: $text_secondary; font-size: 12px; }
#WeatherDateTime { color: $text_muted; font-size: 11px; }
""")


def _qss(palette: Palette) -> str:
    return _QSS_TEMPLATE.substitute(qss_tokens(palette))
