"""
ui/widgets/chat_feed.py
Feed conversacional scrolleable (REQ-013/CA-13, CA-14, CA-15, CA-06, CA-07).

Contenedor de `ChatBubble` y dueño de su QSS. No tiene lógica de negocio: no consulta la
memoria ni resuelve comandos — `ui/gui.py` le pasa el texto ya listo.

Autoscroll (CA-15): setear `scrollbar.setValue(maximum())` justo después de `addWidget()`
NO funciona, porque el layout todavía no se recalculó y `maximum()` sigue siendo el viejo.
Por eso el salto se dispara desde `rangeChanged`, que Qt emite cuando el rango ya es el
nuevo. Y solo se aplica si el usuario ya estaba cerca del fondo, para no arrancarle la
vista mientras relee un mensaje anterior.
"""

from string import Template
from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ui.theme import Palette, qss_tokens, register_themed
from ui.widgets.chat_bubble import ChatBubble

# "Cerca del fondo" en píxeles: por debajo de esta distancia se considera que el usuario
# está siguiendo la conversación en vivo.
_NEAR_BOTTOM_PX = 40


class ChatFeed(QScrollArea):
    """Lista vertical de burbujas con autoscroll condicional."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatFeed")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._content = QWidget()
        self._content.setObjectName("ChatFeedContent")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(10)
        self._layout.addStretch(1)
        self.setWidget(self._content)

        self._bubbles: List[ChatBubble] = []
        self._autoscroll_pending = False
        self.verticalScrollBar().rangeChanged.connect(self._on_range_changed)

        register_themed(self)

    # ------------------------------------------------------------------ API
    def add_message(self, text: str, role: str = "assistant") -> ChatBubble:
        """Agrega una burbuja al final y devuelve la burbuja creada (CA-13, CA-14)."""
        bubble = ChatBubble(text, role)
        bubble.set_available_width(self.viewport().width() or self.width())

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch(1)

        wrapper = QWidget()
        wrapper.setObjectName("ChatBubbleRow")
        wrapper.setLayout(row)

        # Se inserta ANTES del stretch final, que es siempre el último ítem del layout.
        self._layout.insertWidget(self._layout.count() - 1, wrapper)
        self._bubbles.append(bubble)

        self._autoscroll_pending = self._is_near_bottom()
        return bubble

    def load_turns(self, turns) -> None:
        """Reemplaza el contenido por los turnos de una conversación (CA-06).

        `turns` es una lista de `MemoryItem`; un turno sin rol se muestra como del
        asistente (nunca se descarta ni se inventa un rol de usuario).
        """
        self.clear_messages()
        for turn in turns:
            role = getattr(turn, "role", None) or "assistant"
            self.add_message(getattr(turn, "text", ""), role)
        self._autoscroll_pending = True  # al abrir una conversación se va al final

    def clear_messages(self) -> None:
        """Vacía el feed (CA-07). Usa `deleteLater()` para no filtrar widgets."""
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._bubbles.clear()

    def message_count(self) -> int:
        return len(self._bubbles)

    def is_empty(self) -> bool:
        return not self._bubbles

    def bubbles(self) -> List[ChatBubble]:
        """Copia de las burbujas actuales, en orden de inserción."""
        return list(self._bubbles)

    def scroll_to_bottom(self) -> None:
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def apply_theme(self, palette: Palette) -> None:
        """REQ-013/CA-01 — reestiliza el feed Y sus burbujas (que heredan este QSS)."""
        self.setStyleSheet(_qss(palette))

    # -------------------------------------------------------------- internos
    def _is_near_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        if bar.maximum() == 0:
            return True
        return bar.value() >= bar.maximum() - _NEAR_BOTTOM_PX

    def _on_range_changed(self, _minimum: int, maximum: int) -> None:
        """Consume el flag de autoscroll cuando Qt ya recalculó el rango (CA-15)."""
        if self._autoscroll_pending:
            self._autoscroll_pending = False
            self.verticalScrollBar().setValue(maximum)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = self.viewport().width()
        for bubble in self._bubbles:
            bubble.set_available_width(width)


# REQ-013: `string.Template` con `$token`, NUNCA `str.format()` (ver `ui/theme.py`).
_QSS_TEMPLATE = Template("""
#ChatFeed { background-color: transparent; border: none; }
#ChatFeedContent { background-color: transparent; }
#ChatBubbleRow { background-color: transparent; }
#ChatBubble { border-radius: 14px; background-color: $bubble_ai_bg; }
#ChatBubble[role="user"] { background-color: $bubble_user_bg; }
#ChatBubble #ChatBubbleText { color: $bubble_ai_fg; font-size: 13px; }
#ChatBubble[role="user"] #ChatBubbleText { color: $bubble_user_fg; font-size: 13px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0px; }
QScrollBar::handle:vertical { background: $scroll_handle; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
""")


def _qss(palette: Palette) -> str:
    return _QSS_TEMPLATE.substitute(qss_tokens(palette))
