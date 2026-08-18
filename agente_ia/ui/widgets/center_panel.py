"""
ui/widgets/center_panel.py
Columna central del panel (REQ-008/CA-02..CA-04, CA-11, CA-12 · REQ-012 · REQ-013).

Desde REQ-013 este widget es un COMPOSITOR delgado de tres piezas:

    [ _empty_state ]  saludo + subtítulo + avatar + `VoiceOrb`, visible solo con el feed vacío
    [ _feed        ]  `ChatFeed`, la conversación (CA-13, CA-14)
    [ _composer    ]  `Composer`, chips + input + manos libres + enviar (CA-17, CA-18)

Su API pública NO cambió: `command_submitted`, `hands_free_toggled`, `set_state()`,
`set_wake_state()` y `show_response()` siguen con la misma firma y semántica, y el saludo
(`_display_name`, `_greeting_label`, `_greeting_timer`, `_refresh_greeting`) sigue viviendo
en este archivo con los mismos nombres privados que en REQ-012 — de eso dependen sus
pruebas (arquitectura-013.md §4.4, riesgo 1).

El avatar de Nodo (`NodeAvatar`) es un PLACEHOLDER: un `QLabel` con emoji. Cuando exista el
asset gráfico se reemplaza por un `QLabel` con `QPixmap` en `_build_empty_state()`; este REQ
no agrega ningún archivo binario al repositorio.
"""

import os
from string import Template

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import config_manager
from ui.personality import get_time_based_greeting
from ui.theme import Palette, qss_tokens, register_themed
from ui.widgets.chat_feed import ChatFeed
from ui.widgets.composer import Composer
from ui.widgets.voice_orb import VoiceOrb

_GREETING_REFRESH_MS = 60_000  # REQ-012/CA-06 — intervalo confirmado por Johan en SPEC-012

_SUBTITLE_TEXT = "¿En qué puedo ayudarte hoy?"
_AVATAR_TEXT = "🤖"


def _resolve_display_name() -> str:
    """Cadena de resolución de CA-04: config (`display_name`) → variable de entorno del
    SO (`USERNAME`) → sin nombre. Nunca hardcodea un nombre de persona (ver
    arquitectura-008.md, sección "Resolución de display_name")."""
    name = config_manager.get_display_name()
    if name:
        return name
    return os.environ.get("USERNAME", "")


class CenterPanel(QFrame):
    """Columna central. Re-emite las señales del `Composer` para que `ui/gui.py` siga
    conectándose exactamente al mismo lugar que antes de REQ-013."""

    command_submitted = pyqtSignal(str)
    hands_free_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CenterPanel")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._display_name = _resolve_display_name()
        self._empty_state = self._build_empty_state()
        layout.addWidget(self._empty_state)

        self._feed = ChatFeed()
        layout.addWidget(self._feed, 1)

        self._composer = Composer()
        self._composer.command_submitted.connect(self.command_submitted.emit)
        self._composer.hands_free_toggled.connect(self.hands_free_toggled.emit)
        layout.addWidget(self._composer)

        register_themed(self)
        self._sync_empty_state()

        self._greeting_timer = QTimer(self)
        self._greeting_timer.timeout.connect(self._refresh_greeting)
        self._greeting_timer.start(_GREETING_REFRESH_MS)

    def _build_empty_state(self) -> QWidget:
        """Bloque de bienvenida: saludo + subtítulo + avatar + orbe (CA-16, CA-20)."""
        container = QWidget()
        container.setObjectName("EmptyState")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(32, 24, 32, 8)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        avatar = QLabel(_AVATAR_TEXT)
        avatar.setObjectName("NodeAvatar")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(avatar)

        self._greeting_label = QLabel(get_time_based_greeting(self._display_name))
        self._greeting_label.setObjectName("GreetingLabel")
        self._greeting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._greeting_label)

        subtitle = QLabel(_SUBTITLE_TEXT)
        subtitle.setObjectName("GreetingSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        self._orb = VoiceOrb()
        orb_row = QHBoxLayout()
        orb_row.addStretch(1)
        orb_row.addWidget(self._orb)
        orb_row.addStretch(1)
        layout.addLayout(orb_row)

        return container

    # ------------------------------------------------------------------ API
    @property
    def _wake_toggle(self):
        """El toggle de manos libres vive ahora en el `Composer` (REQ-013/CA-16).

        Se expone acá para que el contrato de REQ-009 (`panel._wake_toggle`) siga siendo
        válido pese al cambio de layout.
        """
        return self._composer._wake_toggle

    def set_state(self, state: str) -> None:
        """El texto de estado lo muestra `HeaderBar._mode_pill`; acá solo se anima el orbe."""
        self._orb.set_state(state)

    def set_wake_state(self, state: str) -> None:
        self._composer.set_wake_state(state)

    def show_response(self, text: str) -> None:
        """CA-14 — la respuesta de la IA entra como burbuja del asistente (antes iba a un
        `QLabel` de estado truncado a 200 caracteres)."""
        self._feed.add_message(text, "assistant")
        self._sync_empty_state()

    def add_user_message(self, text: str) -> None:
        """CA-13 — el mensaje del usuario aparece de inmediato, antes de resolver."""
        self._feed.add_message(text, "user")
        self._sync_empty_state()

    def load_turns(self, turns) -> None:
        """CA-06 — reemplaza el feed por los turnos de una conversación existente."""
        self._feed.load_turns(turns)
        self._sync_empty_state()

    def clear_feed(self) -> None:
        """CA-07 — vacía el feed y vuelve a mostrar el bloque de bienvenida."""
        self._feed.clear_messages()
        self._sync_empty_state()

    def apply_theme(self, palette: Palette) -> None:
        """REQ-013/CA-01 — reestiliza la columna; feed, composer y orbe se registran solos."""
        self.setStyleSheet(_qss(palette))

    def set_input_enabled(self, enabled: bool) -> None:
        """REQ-013 (3ra pasada)/CA-09 — delega en el `Composer`: bloquea el envío de un
        segundo comando mientras `JarvisMainWindow` tiene una resolución en curso (fix de la
        condición de carrera de `_pending_user_text`, ver qa-audit-013.md)."""
        self._composer.set_input_enabled(enabled)

    # -------------------------------------------------------------- internos
    def _sync_empty_state(self) -> None:
        """El bloque de bienvenida solo se ve con el feed vacío (CA-20)."""
        self._empty_state.setVisible(self._feed.is_empty())

    def _refresh_greeting(self) -> None:
        """Reevalúa el saludo cada `_GREETING_REFRESH_MS` (REQ-012/CA-06..CA-08).

        Reusa `self._display_name` capturado en `_build_ui()` — solo la franja horaria
        puede cambiar entre disparos, no el nombre. Solo repinta si el texto cambió
        (CA-07), para evitar renders innecesarios. Sigue corriendo aunque el bloque esté
        oculto: cuando el usuario vuelva a una conversación nueva, el saludo ya está al día.
        """
        greeting = get_time_based_greeting(self._display_name)
        if greeting != self._greeting_label.text():
            self._greeting_label.setText(greeting)


# REQ-013: `string.Template` con `$token`, NUNCA `str.format()` (ver `ui/theme.py`).
_QSS_TEMPLATE = Template("""
#CenterPanel { background-color: transparent; }
#EmptyState { background-color: transparent; }
#NodeAvatar { font-size: 56px; }
#GreetingLabel { color: $text_primary; font-size: 32px; font-weight: 300; }
#GreetingSubtitle { color: $text_secondary; font-size: 14px; }
""")


def _qss(palette: Palette) -> str:
    return _QSS_TEMPLATE.substitute(qss_tokens(palette))
