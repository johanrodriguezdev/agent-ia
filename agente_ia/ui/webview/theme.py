"""
ui/webview/theme.py
Fuente única de verdad EN PYTHON de las paletas del panel WebView (REQ-015/CA-35, CA-36,
CA-38 · arquitectura-015.md §0.3, §1). Los mismos hex se declaran también como CSS custom
properties estáticas en `ui/webview/frontend/css/theme.css` — un test dedicado
(`tests/test_webview_theme.py`) parsea ese `.css` y compara contra `DARK_TOKENS`/
`LIGHT_TOKENS` para detectar drift entre ambas copias.

Paleta neutra (grises sin tinte, superficies casi planas y un único acento) — reemplaza
la paleta GitHub-like heredada de `REQ-014-context.md`. Cada par texto/fondo que el layout
combina de verdad está verificado contra WCAG AA en `tests/test_webview_contrast.py`; si se
cambia un hex acá hay que correr ese test antes de darlo por bueno.

Sin `QObject`/señales — a diferencia de `ui/theme.py::ThemeManager` (REQ-013, eliminado):
la notificación de cambio de tema va por el bridge (`Bridge.theme_changed`), no por un
`pyqtSignal` interno. Este módulo es texto plano, sin ningún import de Qt.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

DARK_TOKENS: Dict[str, str] = {
    "bg_primary": "#0c0d0f",
    "bg_secondary": "#131417",
    "bg_input": "#17191c",
    "bg_hover": "#1f2226",
    "border": "#262930",
    "text_primary": "#e8eaed",
    "text_secondary": "#9aa0a6",
    "text_accent": "#58a6ff",
    "bubble_user": "#1c2430",
    "bubble_agent": "#15171a",
    "success": "#3fb950",
    "warning": "#d29922",
    "danger": "#f85149",
}

LIGHT_TOKENS: Dict[str, str] = {
    "bg_primary": "#ffffff",
    "bg_secondary": "#f7f8f9",
    "bg_input": "#f1f2f4",
    "bg_hover": "#e8eaed",
    "border": "#e2e4e8",
    "text_primary": "#17181a",
    "text_secondary": "#5f6368",
    "text_accent": "#0969da",
    "bubble_user": "#eaeef4",
    "bubble_agent": "#f7f8f9",
    "success": "#1a7f37",
    "warning": "#9a6700",
    "danger": "#cf222e",
}

THEMES: Dict[str, Dict[str, str]] = {"dark": DARK_TOKENS, "light": LIGHT_TOKENS}

# REQ-015/CA-38: cambia de "dark" (REQ-013) a "light" — ya validado en REQ-014 addendum §7.
DEFAULT_THEME = "light"


def resolve_theme_name(raw: Any) -> str:
    """Normaliza un nombre de tema de origen no confiable (`config.json`) al catálogo.

    Portado tal cual desde `ui/theme.py::resolve_theme_name()` (REQ-013, eliminado):
    cualquier valor fuera de `THEMES` cae a `DEFAULT_THEME` con un warning — nunca lanza
    ni deja pasar un string arbitrario hacia la selección de paleta.
    """
    name = (raw or "").strip().lower() if isinstance(raw, str) else ""
    if name not in THEMES:
        logger.warning("tema desconocido en configuración: %r — se usa %s", raw, DEFAULT_THEME)
        return DEFAULT_THEME
    return name
