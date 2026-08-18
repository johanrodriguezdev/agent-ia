"""
ui/widgets/chat_bubble.py
Burbuja individual del feed conversacional (REQ-013/CA-13, CA-14).

Deliberadamente tonta: no conoce el `ThemeManager` ni la memoria. Se estiliza por
herencia del QSS de `ChatFeed`, que sí está registrado en `theme_changed` — se crean y
destruyen a decenas por conversación y suscribir cada una dejaría cientos de conexiones
vivas (arquitectura-013.md §3.1, riesgo 8).

La distinción visual usuario/asistente se hace con la propiedad dinámica `role`, que el
QSS del feed lee como `#ChatBubble[role="user"]`.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel

# Ancho máximo de una burbuja como fracción del ancho del feed: una respuesta larga no
# ocupa la línea completa, que es lo que hace ilegible un muro de texto.
_MAX_WIDTH_RATIO = 0.72
_MIN_MAX_WIDTH = 240

_ROLES = ("user", "assistant")


class ChatBubble(QFrame):
    """Una burbuja de conversación. `role` ∈ {"user", "assistant"}."""

    def __init__(self, text: str, role: str = "assistant", parent=None):
        super().__init__(parent)
        self.setObjectName("ChatBubble")
        self._role = role if role in _ROLES else "assistant"
        self.setProperty("role", self._role)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)

        self._label = QLabel(text)
        self._label.setObjectName("ChatBubbleText")
        self._label.setWordWrap(True)
        # El usuario puede seleccionar y copiar una respuesta — antes de REQ-013 el texto
        # vivía en un QLabel de estado truncado a 200 caracteres y no era copiable.
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._label)

    def role(self) -> str:
        return self._role

    def text(self) -> str:
        return self._label.text()

    def set_text(self, text: str) -> None:
        self._label.setText(text)

    def set_available_width(self, width: int) -> None:
        """Acota el ancho de la burbuja a `_MAX_WIDTH_RATIO` del ancho del feed."""
        self.setMaximumWidth(max(_MIN_MAX_WIDTH, int(width * _MAX_WIDTH_RATIO)))
