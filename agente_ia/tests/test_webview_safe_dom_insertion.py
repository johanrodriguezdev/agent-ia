"""
tests/test_webview_safe_dom_insertion.py
REQ-015/§10.1 (Hallazgo A de security-audit-015.md) — capa 1, estática.

Grep estructural sobre el código fuente de `ui/webview/frontend/js/{sidebar,composer,
confirm_modal}.js`: falla si aparece `.innerHTML` o `insertAdjacentHTML` en cualquiera de
los 3 archivos — a diferencia de `chat.js`, ninguno de los 3 necesita insertar HTML real
(título de conversación, nombre de archivo dropeado, mensaje/`action_name` del modal de
confirmación son todos texto NO confiable, ver arquitectura-015.md §10.1).

No sustituye la prueba runtime adversarial de `tests/test_webview_smoke.py` — un grep no
detecta, por ejemplo, un `textContent` correcto combinado con un atributo `href` mal
filtrado en un `<a>` creado dinámicamente — pero sí detecta con certeza el vector
principal señalado por la auditoría.
"""

import re
from pathlib import Path

import pytest

_FRONTEND_JS_DIR = (
    Path(__file__).resolve().parent.parent / "ui" / "webview" / "frontend" / "js"
)

# Los 3 archivos que la auditoría señaló como no cubiertos por sanitización server-side,
# más los 2 archivos nuevos de REQ-016 (arquitectura-016.md §10): siguen el mismo molde
# exacto — texto no confiable (título de tarea/proyecto, título de conversación reutilizado
# en el picker) insertado vía textContent, nunca innerHTML.
_MUST_NOT_USE_INNERHTML = [
    "sidebar.js", "composer.js", "confirm_modal.js", "tasks_panel.js", "projects_panel.js",
    "settings_panel.js",   # REQ-019
]

_UNSAFE_PATTERN = re.compile(r"\.innerHTML\s*=|insertAdjacentHTML\s*\(")


@pytest.mark.parametrize("filename", _MUST_NOT_USE_INNERHTML)
def test_archivo_no_usa_innerhtml_ni_insertadjacenthtml(filename):
    path = _FRONTEND_JS_DIR / filename
    assert path.is_file(), f"no se encontró {path}"
    source = path.read_text(encoding="utf-8")

    match = _UNSAFE_PATTERN.search(source)
    assert match is None, (
        f"{filename} usa una inserción insegura de HTML ({match.group(0)!r}) — regla de "
        "§10.1: todo campo del bridge que no sea 'html' pre-sanitizado va por "
        "textContent/setAttribute, nunca innerHTML/insertAdjacentHTML."
    )


@pytest.mark.parametrize("filename", _MUST_NOT_USE_INNERHTML)
def test_archivo_usa_textcontent_para_insertar_texto(filename):
    """Contraste positivo: confirma que el archivo SÍ inserta texto (con `textContent`),
    no que simplemente no toca el DOM en absoluto."""
    path = _FRONTEND_JS_DIR / filename
    source = path.read_text(encoding="utf-8")
    assert ".textContent" in source, f"{filename} no usa textContent — ¿inserta texto de otra forma?"


def test_chat_js_es_la_unica_excepcion_documentada():
    """`chat.js` SÍ usa `innerHTML`, pero únicamente para el campo `html` ya sanitizado
    por `render_markdown()`+`bleach` (§5.2) — este test confirma que la excepción sigue
    viva y documentada, no que desapareció silenciosamente."""
    path = _FRONTEND_JS_DIR / "chat.js"
    source = path.read_text(encoding="utf-8")
    assert ".innerHTML" in source
    assert "item.html" in source


def test_ningun_otro_archivo_js_del_frontend_usa_innerhtml():
    """Red de seguridad adicional: ni `app.js`, `theme.js`, `bridge_client.js` ni
    `window_chrome.js` deberían necesitar `innerHTML` en ningún momento — si alguno
    empieza a usarlo, hay que auditar ese campo explícitamente."""
    allowed = {"chat.js"}
    offenders = []
    for js_file in sorted(_FRONTEND_JS_DIR.glob("*.js")):
        if js_file.name in allowed:
            continue
        source = js_file.read_text(encoding="utf-8")
        if _UNSAFE_PATTERN.search(source):
            offenders.append(js_file.name)
    assert not offenders, f"archivos con innerHTML/insertAdjacentHTML no auditados: {offenders}"
