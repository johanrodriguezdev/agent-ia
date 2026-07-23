"""
gui.py
Interfaz grafica futurista inspirada en JARVIS (Iron Man).
Muestra un nucleo energetico animado que reacciona a los estados del sistema.
Mejorado con HUD futurista, rejillas y efectos de brillo (glow).
"""

import sys
import math
from PyQt6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QRadialGradient, QFont, QPaintEvent, QPolygonF, QBrush, QIcon, QPixmap
from config_manager import get_agent_name

# Variable Global Hilo-Segura compartida con la logica background
GLOBAL_STATE = "IDLE"

def update_gui_state(new_state: str):
    global GLOBAL_STATE
    GLOBAL_STATE = new_state

class JarvisGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.current_state = "IDLE"
        self.animation_angle = 0.0
        self.pulse_radius = 0.0
        self.pulse_direction = 1
        self.scan_line_y = 0
        self.old_pos = None
        self.init_ui()

    def init_ui(self):
        agent_name = get_agent_name().upper()
        self.setWindowTitle(f"{agent_name} Core HUD")
        self.setFixedSize(400, 400)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(33)

        self.state_poll = QTimer(self)
        self.state_poll.timeout.connect(self.poll_state)
        self.state_poll.start(100)

        self._setup_tray_icon(agent_name)

    def poll_state(self):
        global GLOBAL_STATE
        if self.current_state != GLOBAL_STATE:
            self.current_state = GLOBAL_STATE
            self.pulse_radius = 0.0
            self.update()

    def animate(self):
        # Velocidad de rotacion segun estado
        rot_speed = 2
        if self.current_state == "PROCESSING": rot_speed = 10
        elif self.current_state == "LISTENING": rot_speed = 5
        elif self.current_state == "RESPONDING": rot_speed = 4
            
        self.animation_angle += rot_speed
        if self.animation_angle >= 360: self.animation_angle = 0

        # Pulsacion del nucleo
        pulse_speed = 0.8
        max_pulse = 12
        if self.current_state == "LISTENING":
            pulse_speed = 2.0
            max_pulse = 25
        elif self.current_state == "PROCESSING":
            pulse_speed = 3.0
            max_pulse = 15
            
        self.pulse_radius += pulse_speed * self.pulse_direction
        if self.pulse_radius > max_pulse: self.pulse_direction = -1
        elif self.pulse_radius < 0: self.pulse_direction = 1

        # Linea de escaneo HUD
        self.scan_line_y += 5
        if self.scan_line_y > self.height(): self.scan_line_y = 0

        self.update() 

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = QPointF(self.width() / 2, self.height() / 2)
        base_radius = 90

        # Colores segun estado
        colors = {
            "IDLE":       {"core": (0, 100, 255), "glow": (0, 50, 200, 60),  "ring": (0, 150, 255, 180)},
            "LISTENING":  {"core": (0, 255, 200), "glow": (0, 200, 255, 100), "ring": (255, 255, 255, 220)},
            "PROCESSING": {"core": (200, 0, 255), "glow": (150, 0, 255, 120), "ring": (255, 100, 255, 240)},
            "RESPONDING": {"core": (50, 150, 255), "glow": (100, 100, 255, 150), "ring": (200, 200, 255, 255)}
        }
        
        cfg = colors.get(self.current_state, colors["IDLE"])
        core_c = QColor(*cfg["core"])
        glow_c = QColor(*cfg["glow"])
        ring_c = QColor(*cfg["ring"])

        # 1. Dibujar Rejilla Hexagonal de fondo (Sutil)
        self.draw_hex_grid(painter, ring_c)

        # 2. Dibujar Glow Circular de fondo
        actual_r = base_radius + self.pulse_radius
        grad = QRadialGradient(center, actual_r * 1.5)
        grad.setColorAt(0, glow_c)
        grad.setColorAt(0.7, QColor(0, 0, 0, 0))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, actual_r * 1.5, actual_r * 1.5)

        # 3. Dibujar Anillos Externos HUD
        self.draw_hud_rings(painter, center, base_radius, ring_c)

        # 4. Dibujar Nucleo de Energia
        painter.setBrush(core_c)
        painter.setPen(QPen(ring_c, 2))
        painter.drawEllipse(center, 30, 30)
        
        # Brillo interno del nucleo
        inner_grad = QRadialGradient(center, 30)
        inner_grad.setColorAt(0, Qt.GlobalColor.white)
        inner_grad.setColorAt(0.5, core_c)
        inner_grad.setColorAt(1, QColor(0,0,0,0))
        painter.setBrush(inner_grad)
        painter.drawEllipse(center, 25, 25)

        # 5. Linea de escaneo vertical
        painter.setPen(QPen(QColor(ring_c.red(), ring_c.green(), ring_c.blue(), 40), 1))
        painter.drawLine(0, self.scan_line_y, self.width(), self.scan_line_y)

        # 6. Texto de Estado
        painter.setFont(QFont("Segoe UI Light", 14, QFont.Weight.Bold))
        painter.setPen(ring_c)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignBottom, f"SYSTEM: {self.current_state}")

    def draw_hud_rings(self, painter, center, radius, color):
        # Anillo de Rotacion Principal
        pen = QPen(color, 3)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        # Arcos segmentados
        for i in range(4):
            start = int(self.animation_angle + (i * 90)) * 16
            painter.drawArc(int(center.x() - radius), int(center.y() - radius), 
                            int(radius*2), int(radius*2), start, 45*16)
            
        # Anillo Fino de coordenadas
        pen.setWidth(1)
        pen.setColor(QColor(color.red(), color.green(), color.blue(), 80))
        painter.setPen(pen)
        painter.drawEllipse(center, radius + 15, radius + 15)
        
        # Marcas de HUD
        for i in range(12):
            angle = math.radians(i * 30 + self.animation_angle * 0.5)
            p1 = center + QPointF(math.cos(angle)*(radius+15), math.sin(angle)*(radius+15))
            p2 = center + QPointF(math.cos(angle)*(radius+25), math.sin(angle)*(radius+25))
            painter.drawLine(p1, p2)

    def draw_hex_grid(self, painter, color):
        pen = QPen(QColor(color.red(), color.green(), color.blue(), 20), 1)
        painter.setPen(pen)
        size = 20
        h = math.sqrt(3) * size
        for x in range(0, self.width() + size, int(size * 1.5)):
            for y in range(0, self.height() + int(h), int(h)):
                offset = (h / 2) if (x // (size * 1.5)) % 2 else 0
                self.draw_hexagon(painter, QPointF(x, y + offset), size)

    def draw_hexagon(self, painter, center, size):
        poly = QPolygonF()
        for i in range(6):
            angle = math.radians(60 * i)
            poly.append(center + QPointF(size * math.cos(angle), size * math.sin(angle)))
        painter.drawPolygon(poly)

    # Mouse events para mover la ventana
    def _setup_tray_icon(self, agent_name: str):
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(0, 100, 255))
        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip(f"{agent_name} — HUD")

        menu = QMenu()
        show_action = menu.addAction("Mostrar/Ocultar")
        show_action.triggered.connect(self._toggle_visible)
        quit_action = menu.addAction("Salir")
        quit_action.triggered.connect(QApplication.instance().quit)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _toggle_visible(self):
        self.setVisible(not self.isVisible())

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_visible()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "O.R.I.O.N.",
            "Continuo ejecutándome en segundo plano.",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.old_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.old_pos is not None:
            delta = event.globalPosition().toPoint() - self.old_pos
            self.move(self.pos() + delta)
            self.old_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event):
        self.old_pos = None

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = JarvisGUI()
    window.show()
    sys.exit(app.exec())
