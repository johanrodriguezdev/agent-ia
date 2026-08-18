"""
ui/widgets/voice_orb.py
Visualizador circular central (REQ-008/CA-11) — versión reducida (~220x220px) del
`paintEvent` del `JarvisGUI` original (anillo + núcleo + pulso), sin la rejilla
hexagonal de fondo ni la línea de escaneo de ventana completa (ya no aplica: ahora es
un widget dentro de `CenterPanel`, no una ventana de 400x400). Sigue dirigido por los
4 estados existentes vía `set_state()`, sin ningún análisis de audio real (animación
simulada, igual que en el `JarvisGUI` original).
"""

import math

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from ui.theme import DARK_PALETTE, register_themed


class VoiceOrb(QWidget):
    """Orbe de voz central. `set_state(state)` cambia colores/velocidad de pulso; la
    animación corre con un `QTimer` propio de 33ms (mismo intervalo del `JarvisGUI`
    original)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(220, 220)
        self.current_state = "IDLE"
        self.animation_angle = 0.0
        self.pulse_radius = 0.0
        self.pulse_direction = 1
        # REQ-013/CA-04: los colores dejan de ser una constante de módulo y pasan a venir
        # de la paleta activa. El juego oscuro es idéntico al que había antes del REQ.
        self._state_colors = DARK_PALETTE.orb_colors

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(33)
        register_themed(self)

    def apply_theme(self, palette) -> None:
        """REQ-013/CA-01 — repinta el orbe con los colores del tema recibido."""
        self._state_colors = palette.orb_colors
        self.update()

    def set_state(self, state: str) -> None:
        if state != self.current_state:
            self.current_state = state
            self.pulse_radius = 0.0
            self.update()

    def _animate(self) -> None:
        rot_speed = 2
        if self.current_state == "PROCESSING":
            rot_speed = 10
        elif self.current_state == "LISTENING":
            rot_speed = 5
        elif self.current_state == "RESPONDING":
            rot_speed = 4
        self.animation_angle = (self.animation_angle + rot_speed) % 360

        pulse_speed, max_pulse = 0.8, 12
        if self.current_state == "LISTENING":
            pulse_speed, max_pulse = 2.0, 25
        elif self.current_state == "PROCESSING":
            pulse_speed, max_pulse = 3.0, 15

        self.pulse_radius += pulse_speed * self.pulse_direction
        if self.pulse_radius > max_pulse:
            self.pulse_direction = -1
        elif self.pulse_radius < 0:
            self.pulse_direction = 1

        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = QPointF(self.width() / 2, self.height() / 2)
        base_radius = 60

        cfg = self._state_colors.get(self.current_state, self._state_colors["IDLE"])
        core_c = QColor(*cfg["core"])
        glow_c = QColor(*cfg["glow"])
        ring_c = QColor(*cfg["ring"])

        actual_r = base_radius + self.pulse_radius
        grad = QRadialGradient(center, actual_r * 1.5)
        grad.setColorAt(0, glow_c)
        grad.setColorAt(0.7, QColor(0, 0, 0, 0))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, actual_r * 1.5, actual_r * 1.5)

        self._draw_rings(painter, center, base_radius, ring_c)

        painter.setBrush(core_c)
        painter.setPen(QPen(ring_c, 2))
        painter.drawEllipse(center, 22, 22)

        inner_grad = QRadialGradient(center, 22)
        inner_grad.setColorAt(0, QColor(Qt.GlobalColor.white))
        inner_grad.setColorAt(0.5, core_c)
        inner_grad.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(inner_grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, 18, 18)

    def _draw_rings(self, painter: QPainter, center: QPointF, radius: float, color: QColor) -> None:
        pen = QPen(color, 3)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(4):
            start = int(self.animation_angle + (i * 90)) * 16
            painter.drawArc(
                int(center.x() - radius), int(center.y() - radius),
                int(radius * 2), int(radius * 2), start, 45 * 16,
            )

        pen.setWidth(1)
        pen.setColor(QColor(color.red(), color.green(), color.blue(), 80))
        painter.setPen(pen)
        painter.drawEllipse(center, radius + 12, radius + 12)

        for i in range(12):
            angle = math.radians(i * 30 + self.animation_angle * 0.5)
            p1 = center + QPointF(math.cos(angle) * (radius + 12), math.sin(angle) * (radius + 12))
            p2 = center + QPointF(math.cos(angle) * (radius + 20), math.sin(angle) * (radius + 20))
            painter.drawLine(p1, p2)
