"""
ui/widgets/recent_activity_card.py
Tarjeta "Actividad reciente" (REQ-008/CA-09): últimas interacciones reales del usuario
vía `ai/memory_manager.py:UnifiedMemory.get_recent()`. Se puebla una vez en `__init__`
(consulta SQLite local rápida, no requiere `QThreadPool`).
"""

from typing import List

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ai.memory_manager import MemoryItem, memory

_EMPTY_STATE_TEXT = "Sin actividad reciente todavía."


class RecentActivityCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._items_layout = None
        self._build_ui()
        self.set_items(memory.get_recent(user_id="default", limit=4))

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(8)

        title = QLabel("Actividad reciente")
        title.setObjectName("CardTitle")
        outer.addWidget(title)

        self._items_layout = QVBoxLayout()
        self._items_layout.setSpacing(6)
        outer.addLayout(self._items_layout)

        self.setStyleSheet(_CARD_QSS)

    def set_items(self, items: List[MemoryItem]) -> None:
        """`items`: lista de `MemoryItem`. Lista vacía -> estado vacío explícito, nunca
        datos inventados ni un widget silenciosamente en blanco."""
        while self._items_layout.count():
            child = self._items_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not items:
            empty = QLabel(_EMPTY_STATE_TEXT)
            empty.setObjectName("RecentActivityEmpty")
            self._items_layout.addWidget(empty)
            return

        for item in items:
            wrapper = QFrame()
            row = QHBoxLayout(wrapper)
            row.setContentsMargins(0, 0, 0, 0)

            text = QLabel(_truncate(getattr(item, "text", "")))
            text.setObjectName("RecentActivityText")
            row.addWidget(text, 1)

            time_label = QLabel(_format_time(getattr(item, "timestamp", "")))
            time_label.setObjectName("RecentActivityTime")
            row.addWidget(time_label)

            self._items_layout.addWidget(wrapper)


def _truncate(text: str, max_len: int = 40) -> str:
    text = text.replace("\n", " ")
    return text[:max_len] + "..." if len(text) > max_len else text


def _format_time(timestamp: str) -> str:
    if not timestamp or len(timestamp) < 16:
        return ""
    return timestamp[11:16]


_CARD_QSS = """
#Card { background-color: #111a2c; border-radius: 14px; }
#CardTitle { color: #ffffff; font-size: 14px; font-weight: 600; }
#RecentActivityText { color: #c3c9d6; font-size: 12px; }
#RecentActivityTime { color: #5a6478; font-size: 11px; }
#RecentActivityEmpty { color: #5a6478; font-size: 12px; }
"""
