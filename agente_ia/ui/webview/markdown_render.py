"""
ui/webview/markdown_render.py
`render_markdown()` — Markdown → HTML sanitizado, mitigación central de XSS del bridge
(REQ-015/CA-13, arquitectura-015.md §0.3, §5.2).

Pipeline (server-side, Python — JS nunca parsea Markdown ni sanitiza):
1. `markdown.markdown()` con extensiones `fenced_code`/`tables`/`codehilite`
   (`guess_lang=False` deliberado: sin esto, `codehilite` adivina el lenguaje de bloques
   sin fence explícito, con resultados erráticos — forzar que solo bloques con ```lang
   tengan resaltado es más predecible y más fácil de testear).
2. `bleach.clean()` con allowlist estricta de tags/atributos/protocolos — bloquea
   `<script>`, `onerror=`, `javascript:`, y cualquier tag/atributo fuera de la lista.
3. El resultado va directo a `element.innerHTML` en JS (único campo del bridge marcado
   como `html` pre-sanitizado — ver la regla general de §10.1 sobre el resto de campos).
"""

import logging
from typing import Dict, List

import bleach
import markdown

logger = logging.getLogger(__name__)

_MARKDOWN_EXTENSIONS = ["fenced_code", "tables", "codehilite"]
_MARKDOWN_EXTENSION_CONFIGS = {"codehilite": {"guess_lang": False}}

# CA-13: cobertura de tags exigida (párrafos, énfasis, listas, código, tablas, enlaces,
# citas, encabezados) — allowlist deliberada, no denylist.
ALLOWED_TAGS: List[str] = [
    "p", "br", "strong", "em", "b", "i", "ul", "ol", "li", "code", "pre", "span", "div",
    "table", "thead", "tbody", "tr", "th", "td", "a", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6",
]

# `class` en cualquier tag (necesario para los tokens `.codehilite`/Pygments generados
# por `codehilite`), `href` solo en `<a>` — nunca `javascript:` (bloqueado por `protocols`).
ALLOWED_ATTRS: Dict[str, List[str]] = {
    "*": ["class"],
    "a": ["href", "class"],
}

ALLOWED_PROTOCOLS: List[str] = ["http", "https"]


def render_markdown(text: str) -> str:
    """Convierte `text` (Markdown) a HTML sanitizado, listo para `innerHTML`.

    String vacío/`None` devuelve `""` sin invocar `markdown`/`bleach` — evita procesar
    texto vacío innecesariamente y deja el caso borde explícito para los tests.
    """
    if not text:
        return ""
    raw_html = markdown.markdown(
        text,
        extensions=_MARKDOWN_EXTENSIONS,
        extension_configs=_MARKDOWN_EXTENSION_CONFIGS,
    )
    return bleach.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
