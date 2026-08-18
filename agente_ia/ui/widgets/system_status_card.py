"""
ui/widgets/system_status_card.py
Tarjeta "Estado del sistema" (REQ-008/CA-06): anillo de progreso circular ("salud del
sistema" = 100 - promedio(cpu%, ram%, disk%), decisión de diseño aprobada en
arquitectura-008.md) + 4 filas CPU/RAM/Disco/Red con datos reales de
`system_actions/system_info.py`, refrescadas con un `QTimer` propio de 2000ms —
ejecutado directo en el hilo de la GUI (syscalls locales rápidas, no I/O de red).
"""

from string import Template

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from system_actions import system_info
from ui.theme import DARK_PALETTE, Palette, qss_tokens, register_themed

_REFRESH_MS = 2000
_NAMES = {"cpu": "CPU", "ram": "Memoria", "disk": "Disco", "net": "Red"}


class CircularProgress(QWidget):
    """Anillo de progreso pintado a mano. `set_percent(value)` es testeable sin timer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(120, 120)
        self._percent = 0.0
        # REQ-013/CA-04: el anillo se pinta a mano, no por QSS, asi que sus colores
        # tambien vienen de la paleta (si no, quedaria ilegible en tema claro).
        self._track_color = QColor(DARK_PALETTE.border)
        self._arc_color = QColor(DARK_PALETTE.accent)
        self._text_color = QColor(DARK_PALETTE.text_primary)

    def set_colors(self, track: str, arc: str, text: str) -> None:
        """Recolorea el anillo desde la paleta activa."""
        self._track_color = QColor(track)
        self._arc_color = QColor(arc)
        self._text_color = QColor(text)
        self.update()

    def set_percent(self, value: float) -> None:
        self._percent = max(0.0, min(100.0, value))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(10, 10, self.width() - 20, self.height() - 20)

        bg_pen = QPen(self._track_color, 8)
        painter.setPen(bg_pen)
        painter.drawEllipse(rect)

        fg_pen = QPen(self._arc_color, 8)
        fg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(fg_pen)
        span = int(-360 * 16 * (self._percent / 100.0))
        painter.drawArc(rect, 90 * 16, span)

        painter.setPen(self._text_color)
        painter.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{int(round(self._percent))}%")


class SystemStatusCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._prev_net = None
        self._build_ui()
        # Lectura de "precalentamiento": psutil.cpu_percent(interval=None) devuelve 0.0
        # en la primera llamada del proceso; se descarta antes de mostrar el primer valor.
        system_info.get_cpu_percent()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(_REFRESH_MS)
        self._refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(8)

        title = QLabel("Estado del sistema")
        title.setObjectName("CardTitle")
        outer.addWidget(title)

        row = QGridLayout()
        self._ring = CircularProgress()
        row.addWidget(self._ring, 0, 0, 4, 1)

        self._labels = {}
        for i, key in enumerate(("cpu", "ram", "disk", "net")):
            label = QLabel(self._format_row(key, 0.0))
            label.setObjectName("SystemStatusRow")
            self._labels[key] = label
            row.addWidget(label, i, 1)

        outer.addLayout(row)
        register_themed(self)

    def apply_theme(self, palette: Palette) -> None:
        """REQ-013/CA-01 - QSS de la tarjeta + colores del anillo pintado a mano."""
        self.setStyleSheet(_qss(palette))
        self._ring.set_colors(palette.border, palette.accent, palette.text_primary)

    @staticmethod
    def _format_row(key: str, value: float) -> str:
        return f"{_NAMES[key]}  {value:.0f}%"

    def set_values(self, cpu: float, ram: float, disk: float, net: float) -> None:
        """Actualiza el ring y las 4 filas. Testeable sin arrancar el `QTimer`."""
        self._labels["cpu"].setText(self._format_row("cpu", cpu))
        self._labels["ram"].setText(self._format_row("ram", ram))
        self._labels["disk"].setText(self._format_row("disk", disk))
        self._labels["net"].setText(self._format_row("net", net))
        health = 100.0 - ((cpu + ram + disk) / 3.0)
        self._ring.set_percent(health)

    def _refresh(self) -> None:
        cpu = system_info.get_cpu_percent()
        ram = system_info.get_ram_percent()
        disk = system_info.get_disk_percent()
        sent, recv = system_info.get_network_io_counters()
        net = self._net_percent(sent, recv)
        self.set_values(cpu, ram, disk, net)

    def _net_percent(self, sent: int, recv: int) -> float:
        """Aproximación de actividad de red reciente: bytes transferidos desde la
        última lectura, escalados a un porcentaje (200 KB entre lecturas -> 100%).
        SPEC-008/arquitectura-008.md piden "datos reales de psutil" para Red pero no
        definen una fórmula exacta de "%" — esta es la interpretación tomada dentro de
        la libertad de diseño aprobada en REQ-008-context.md, documentada en
        desarrollo-log-008.md."""
        prev = self._prev_net
        self._prev_net = (sent, recv)
        if prev is None:
            return 0.0
        delta = max(0, (sent - prev[0]) + (recv - prev[1]))
        return max(0.0, min(100.0, (delta / (200 * 1024)) * 100))


# REQ-013: `string.Template` con `$token`, NUNCA `str.format()` (ver `ui/theme.py`).
_QSS_TEMPLATE = Template("""
#Card { background-color: $bg_elevated; border-radius: 14px; }
#CardTitle { color: $text_primary; font-size: 14px; font-weight: 600; }
#SystemStatusRow { color: $text_secondary; font-size: 12px; }
""")


def _qss(palette: Palette) -> str:
    return _QSS_TEMPLATE.substitute(qss_tokens(palette))
