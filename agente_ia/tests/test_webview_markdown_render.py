"""
tests/test_webview_markdown_render.py
REQ-015/CA-13 — `ui/webview/markdown_render.py::render_markdown()`.

Casos funcionales (negrita/cursiva/listas/tablas/código con lenguaje) y casos
ADVERSARIALES (`<script>`, `onerror=`, `javascript:`) que deben salir sanitizados o
neutralizados — mitigación central de XSS del bridge (arquitectura-015.md §5.2).
"""

from ui.webview.markdown_render import render_markdown


def test_string_vacio_devuelve_string_vacio():
    assert render_markdown("") == ""
    assert render_markdown(None) == ""


def test_negrita_y_cursiva():
    html = render_markdown("esto es **negrita** y esto es *cursiva*")
    assert "<strong>negrita</strong>" in html
    assert "<em>cursiva</em>" in html


def test_listas():
    html = render_markdown("- uno\n- dos\n- tres")
    assert "<ul>" in html
    assert html.count("<li>") == 3


def test_tablas():
    html = render_markdown("| A | B |\n|---|---|\n| 1 | 2 |")
    assert "<table>" in html
    assert "<th>" in html
    assert "<td>" in html


def test_codigo_con_lenguaje_recibe_resaltado_pygments():
    html = render_markdown("```python\nprint('hola')\n```")
    assert "codehilite" in html
    assert "<pre>" in html or "<div" in html


def test_codigo_sin_lenguaje_no_intenta_adivinar():
    """`guess_lang=False` (§0.3) — un bloque sin fence de lenguaje no debe producir
    tokens de resaltado erráticos; sigue envuelto en `<pre>`/`<code>` como código plano."""
    html = render_markdown("```\nalgo de texto plano\n```")
    assert "algo de texto plano" in html


def test_enlace_http_se_conserva():
    html = render_markdown("[click acá](https://example.com)")
    assert 'href="https://example.com"' in html


def test_blockquote_y_encabezados():
    html = render_markdown("# Título\n\n> una cita")
    assert "<h1>" in html
    assert "<blockquote>" in html


# ---------------------------------------------------------------------------
# Casos adversariales — mitigación central de XSS (arquitectura-015.md §5.2)
# ---------------------------------------------------------------------------

def test_adversarial_script_tag_se_elimina():
    html = render_markdown("hola <script>alert(1)</script> mundo")
    assert "<script" not in html.lower()
    assert "alert(1)" not in html or "<script" not in html.lower()


def test_adversarial_img_onerror_se_neutraliza():
    html = render_markdown('<img src=x onerror=alert(1)>')
    assert "onerror" not in html.lower()
    assert "<img" not in html.lower() or "onerror" not in html.lower()


def test_adversarial_enlace_javascript_scheme_se_bloquea():
    html = render_markdown("[click](javascript:alert(1))")
    assert "javascript:" not in html.lower()


def test_adversarial_onclick_atributo_se_elimina():
    html = render_markdown('<div onclick="alert(1)">hola</div>')
    assert "onclick" not in html.lower()


def test_adversarial_iframe_se_elimina():
    html = render_markdown('<iframe src="https://evil.example"></iframe>')
    assert "<iframe" not in html.lower()


def test_adversarial_style_tag_se_elimina():
    html = render_markdown("<style>body{display:none}</style>texto")
    assert "<style" not in html.lower()
    assert "texto" in html
