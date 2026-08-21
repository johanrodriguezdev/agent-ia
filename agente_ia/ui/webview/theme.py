"""
ui/webview/theme.py
Fuente única de verdad EN PYTHON de las paletas del panel WebView (REQ-015/CA-35, CA-36,
CA-38 · arquitectura-015.md §0.3, §1). Los mismos hex se declaran también como CSS custom
properties estáticas en `ui/webview/frontend/css/theme.css` — un test dedicado
(`tests/test_webview_theme.py`) parsea ese `.css` y compara contra `DARK_TOKENS`/
`LIGHT_TOKENS` para detectar drift entre ambas copias.

Valores partidos literalmente de los hex ya validados y documentados en
`REQ-014-context.md` (ver arquitectura-015.md §1, fila CA-35).

Sin `QObject`/señales — a diferencia de `ui/theme.py::ThemeManager` (REQ-013, eliminado):
la notificación de cambio de tema va por el bridge (`Bridge.theme_changed`), no por un
`pyqtSignal` interno. Este módulo es texto plano, sin ningún import de Qt.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

DARK_TOKENS: Dict[str, str] = {
    "bg_primary": "#0d1117",
    "bg_secondary": "#161b22",
    "bg_input": "#1c2333",
    "bg_hover": "#252d3f",
    "border": "#30363d",
    "text_primary": "#e6edf3",
    "text_secondary": "#8b949e",
    "text_accent": "#58a6ff",
    "bubble_user": "#1f77b4",
    "bubble_agent": "#2d2d2d",
    "success": "#3fb950",
    "warning": "#d29922",
    "danger": "#f85149",
}

LIGHT_TOKENS: Dict[str, str] = {
    "bg_primary": "#ffffff",
    "bg_secondary": "#f6f8fa",
    "bg_input": "#f0f2f5",
    "bg_hover": "#e8eaed",
    "border": "#d0d7de",
    "text_primary": "#24292f",
    "text_secondary": "#57606a",
    "text_accent": "#0969da",
    "bubble_user": "#d1e5ff",
    "bubble_agent": "#e8eaed",
    "success": "#2da44e",
    "warning": "#bf8700",
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
