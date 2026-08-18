"""
ui/theme.py
Punto ÚNICO de paleta del panel de escritorio (REQ-013/CA-01, CA-02, CA-03, CA-04, CA-21).

Antes de este REQ el tema oscuro estaba hardcodeado en el QSS de 10+ archivos de
`ui/widgets/` (más el `setStyleSheet()` inline de `ui/gui.py` y los RGB de `voice_orb.py`).
Acá viven ahora los dos únicos juegos de colores del sistema — `DARK_PALETTE` y
`LIGHT_PALETTE` — y el `ThemeManager` que los aplica en caliente.

Reglas de este módulo que NO deben cambiarse sin volver a arquitectura
(ver `workspace/adjuntos/REQ-013/propuestas/arquitectura-013.md`, §3.1):

1. **El QSS se genera con `string.Template` (`$token`), NUNCA con `str.format()`.**
   El QSS está lleno de llaves `{ }`; `"...".format(**tokens)` reventaría con
   `KeyError`/`IndexError` en cada bloque de reglas. Cada módulo con estilo propio define
   su `_QSS_TEMPLATE = Template(...)` y su `_qss(palette)` hace
   `_QSS_TEMPLATE.substitute(qss_tokens(palette))`. No "simplificar" a `.format()`.

2. **Ningún color viene de `config.json`.** La preferencia persistida solo elige CUÁL de
   las dos paletas constantes se usa (`resolve_theme_name()` normaliza cualquier valor
   desconocido a `dark`). Ningún string de un archivo editable llega jamás a
   `setStyleSheet()` — eso cierra el vector de inyección de hoja de estilo y es lo que
   mantiene este REQ en 🟢 Verde (`.claude/rules/security-levels.md`).

3. **`ChatBubble` no se registra en `theme_changed`.** Se crean y destruyen a decenas por
   conversación; suscribir cada una dejaría cientos de conexiones vivas. Las burbujas se
   estilan por herencia del QSS de `ChatFeed`, que sí está registrado.
"""

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

import config_manager

logger = logging.getLogger(__name__)

# Colores del `VoiceOrb` por estado. El juego oscuro reproduce EXACTAMENTE el
# `_STATE_COLORS` que vivía en `ui/widgets/voice_orb.py` antes de REQ-013.
_DARK_ORB: Dict[str, Dict[str, Tuple[int, ...]]] = {
    "IDLE":       {"core": (0, 100, 255),  "glow": (0, 50, 200, 60),    "ring": (0, 150, 255, 180)},
    "LISTENING":  {"core": (0, 255, 200),  "glow": (0, 200, 255, 100),  "ring": (255, 255, 255, 220)},
    "PROCESSING": {"core": (200, 0, 255),  "glow": (150, 0, 255, 120),  "ring": (255, 100, 255, 240)},
    "RESPONDING": {"core": (50, 150, 255), "glow": (100, 100, 255, 150), "ring": (200, 200, 255, 255)},
}

# En modo claro se oscurecen los núcleos y se baja el alfa del halo para que el orbe no
# se lave sobre fondo blanco.
_LIGHT_ORB: Dict[str, Dict[str, Tuple[int, ...]]] = {
    "IDLE":       {"core": (11, 111, 191), "glow": (11, 111, 191, 45),  "ring": (11, 111, 191, 170)},
    "LISTENING":  {"core": (0, 150, 120),   "glow": (0, 170, 140, 70),   "ring": (0, 120, 100, 200)},
    "PROCESSING": {"core": (124, 58, 179),  "glow": (124, 58, 179, 80),  "ring": (110, 40, 160, 220)},
    "RESPONDING": {"core": (30, 90, 190),   "glow": (60, 90, 200, 90),   "ring": (30, 70, 160, 230)},
}


@dataclass(frozen=True)
class Palette:
    """Juego completo de tokens de color de un tema. Inmutable a propósito: nadie muta
    una paleta en caliente, se cambia la paleta entera."""

    name: str
    bg_window: str
    bg_surface: str      # sidebar
    bg_elevated: str     # tarjetas, burbuja del asistente
    bg_input: str
    bg_hover: str
    border: str
    border_subtle: str
    text_primary: str
    text_secondary: str
    text_muted: str
    text_disabled: str
    accent: str
    accent_soft: str
    on_accent: str       # texto sobre `accent`
    success: str
    warning: str
    danger: str
    bubble_user_bg: str
    bubble_user_fg: str
    bubble_ai_bg: str
    bubble_ai_fg: str
    scroll_handle: str
    orb_colors: Dict[str, Dict[str, Tuple[int, ...]]] = field(default_factory=dict)


DARK_PALETTE = Palette(
    name="dark",
    bg_window="#070b14",
    bg_surface="#0d1220",
    bg_elevated="#111a2c",
    bg_input="#10182a",
    bg_hover="#14203a",
    border="#1e2a42",
    border_subtle="#1a2333",
    text_primary="#ffffff",
    text_secondary="#8a93a6",
    # REQ-013: `#5a6478` (el valor previo al REQ) daba 2.92:1 sobre `bg_elevated`, muy por
    # debajo del 4.5:1 de CA-03. Aclarado a `#808a9c` (4.99:1). Ver desarrollo-log-013.md.
    text_muted="#808a9c",
    # REQ-013 (2da pasada, CA-03 FAIL de orion-tester): `#555f73` daba 2.909:1 sobre
    # `bg_surface` (usado en `#SidebarNavButton:disabled`, sidebar.py:126) — muy por debajo
    # de 4.5:1. Aclarado a `#717e99` (4.58:1). Ver desarrollo-log-013.md.
    text_disabled="#717e99",
    accent="#4fc3ff",
    accent_soft="#132a3f",
    on_accent="#06121f",
    success="#33d17a",
    warning="#ffb84d",
    danger="#ff6b6b",
    bubble_user_bg="#1b4a6e",
    bubble_user_fg="#eaf6ff",
    bubble_ai_bg="#111a2c",
    bubble_ai_fg="#e6eaf2",
    scroll_handle="#24304a",
    orb_colors=_DARK_ORB,
)

LIGHT_PALETTE = Palette(
    name="light",
    bg_window="#f4f6fa",
    bg_surface="#ffffff",
    bg_elevated="#ffffff",
    bg_input="#ffffff",
    bg_hover="#eef2f8",
    border="#d7dee9",
    border_subtle="#e6ebf2",
    text_primary="#101828",
    text_secondary="#4d5769",
    # REQ-013: `#6d7889` daba 4.47:1 sobre blanco, justo por debajo del umbral de CA-03.
    # Oscurecido a `#636d7d` (5.23:1). Ver desarrollo-log-013.md.
    text_muted="#636d7d",
    # REQ-013 (2da pasada, CA-03 FAIL de orion-tester): `#a6b0bf` daba 2.191:1 sobre
    # `bg_surface` (usado en `#SidebarNavButton:disabled`, sidebar.py:126) — muy por debajo
    # de 4.5:1. Oscurecido a `#6f7680` (4.59:1). Ver desarrollo-log-013.md.
    text_disabled="#6f7680",
    # REQ-013 (2da pasada): `#0b6fbf` daba 4.494:1 contra `accent_soft`, por debajo de 4.5:1
    # exigido para texto normal (se usa en `#ModePill`/12px, `#NewConversationButton`/12px,
    # `#WakeIndicator`/14px — ninguno califica como texto grande). Oscurecido a `#0a68b3`
    # (4.98:1 contra `accent_soft`, y mejora el resto de los pares con `accent`). Ver
    # desarrollo-log-013.md.
    accent="#0a68b3",
    accent_soft="#e4f0fb",
    on_accent="#ffffff",
    success="#1a7f43",
    warning="#9a5b00",
    danger="#b3261e",
    bubble_user_bg="#0b6fbf",
    bubble_user_fg="#ffffff",
    bubble_ai_bg="#eef2f7",
    bubble_ai_fg="#101828",
    scroll_handle="#c3cddb",
    orb_colors=_LIGHT_ORB,
)

THEMES: Dict[str, Palette] = {"dark": DARK_PALETTE, "light": LIGHT_PALETTE}
DEFAULT_THEME = "dark"


def qss_tokens(palette: Palette) -> Dict[str, str]:
    """Return the palette as a flat `{token: hex}` dict apto para `Template.substitute()`.

    Excluye `orb_colors` (no es un string y no se sustituye en QSS; lo consume
    `VoiceOrb.apply_theme()` directo desde la paleta).
    """
    tokens: Dict[str, Any] = asdict(palette)
    tokens.pop("orb_colors", None)
    return {key: str(value) for key, value in tokens.items()}


def resolve_theme_name(raw: Any) -> str:
    """Normaliza un nombre de tema de origen no confiable (`config.json`) al catálogo.

    Cualquier valor fuera de `THEMES` cae a `DEFAULT_THEME` con un warning — nunca lanza
    ni deja pasar un string arbitrario hacia la selección de paleta.
    """
    name = (raw or "").strip().lower() if isinstance(raw, str) else ""
    if name not in THEMES:
        logger.warning("tema desconocido en configuración: %r — se usa %s", raw, DEFAULT_THEME)
        return DEFAULT_THEME
    return name


class ThemeManager(QObject):
    """Singleton de módulo (`theme_manager`) que mantiene el tema activo y notifica el
    cambio a todos los widgets registrados (REQ-013/CA-01)."""

    theme_changed = pyqtSignal(object)  # emite una `Palette`

    def __init__(self, parent=None):
        super().__init__(parent)
        self._name = DEFAULT_THEME

    def current_name(self) -> str:
        return self._name

    def palette(self) -> Palette:
        return THEMES[self._name]

    def load_from_config(self) -> None:
        """Lee la preferencia persistida y la aplica (REQ-013/CA-02).

        Se llama ANTES de construir los widgets, para que arranquen ya con el tema
        correcto y no haya un flash del tema anterior.
        """
        self._apply(resolve_theme_name(config_manager.get_ui_theme()), persist=False)

    def set_theme(self, name: str) -> None:
        """Cambia el tema activo, lo persiste y lo emite. No-op si no cambió."""
        self._apply(resolve_theme_name(name), persist=True)

    def toggle(self) -> str:
        """Alterna claro <-> oscuro y devuelve el nombre del tema resultante."""
        self.set_theme("light" if self._name == "dark" else "dark")
        return self._name

    def _apply(self, name: str, persist: bool) -> None:
        if name == self._name:
            return
        self._name = name
        if persist:
            config_manager.set_ui_theme(name)
        self.theme_changed.emit(self.palette())


theme_manager = ThemeManager()


def register_themed(widget) -> None:
    """Aplica la paleta activa al widget y lo suscribe a los cambios futuros.

    `widget` debe implementar `apply_theme(palette)`. Se conecta un bound method de un
    `QObject`, así que PyQt6 desconecta la señal solo cuando el widget se destruye — no
    hace falta `disconnect()` manual.
    """
    widget.apply_theme(theme_manager.palette())
    theme_manager.theme_changed.connect(widget.apply_theme)
