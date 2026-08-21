"""
tests/test_webview_smoke.py
REQ-015/CA-03, CA-05, CA-42 (integración) + §10.1 (Hallazgo A, capa 2 runtime) —
`QWebEngineView` REAL en modo offscreen (`QT_QPA_PLATFORM=offscreen`, ya fijado en
`tests/conftest.py`): carga `index.html` de verdad, espera a que `app.js` termine de
suscribirse (`window.__ORION_APP_READY__`), y verifica vía `page().runJavaScript()`:

- CA-03: `getComputedStyle(#app-shell).backgroundColor` no queda transparente en ningún
  tema (red de regresión automatizada del bug #1 de REQ-014 — bleed-through).
- CA-05: el input del composer tiene borde/fondo/placeholder no vacíos (red de
  regresión del bug #3 de REQ-014 — input invisible).
- §10.1: 3 casos adversariales (título de conversación, nombre de archivo dropeado,
  mensaje de confirmación) con `<img src=x onerror=...>` — no debe ejecutar nada, el nodo
  de destino debe quedar con el string literal completo como `textContent`.

Marcados `@pytest.mark.webview_smoke` (ver `tests/conftest.py::pytest_configure`) — no
sustituyen la inspección visual real en Windows que exige la SPEC para CA-03/CA-04/CA-05,
son una red de regresión automatizada adicional (arquitectura-015.md §7, "Repetir el
patrón de REQ-014").

Sin red, sin tocar la DB real ni `config.json` real: `memory.list_conversations()` y
`config_manager.get_ui_theme()`/`get_agent_name()` van mockeados antes de construir la
ventana.
"""

import json

import pytest
from PyQt6.QtCore import QEventLoop, QTimer

pytestmark = pytest.mark.webview_smoke

_JS_TIMEOUT_MS = 8000


def _run_js_sync(page, code, timeout_ms=_JS_TIMEOUT_MS):
    loop = QEventLoop()
    holder = {}

    def _on_result(value):
        holder["value"] = value
        holder["done"] = True
        loop.quit()

    page.runJavaScript(code, _on_result)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return holder.get("value")


@pytest.fixture
def ready_window(qtbot, monkeypatch):
    from ai.memory_manager import memory
    import config_manager
    import ui.webview.main_window as main_window_module

    # Sin red, sin DB real, sin config.json real (.claude/rules/testing.md).
    monkeypatch.setattr(memory, "list_conversations", lambda **kwargs: [])
    monkeypatch.setattr(config_manager, "get_ui_theme", lambda: "light")
    monkeypatch.setattr(config_manager, "set_ui_theme", lambda name: None)
    monkeypatch.setattr(main_window_module, "get_agent_name", lambda: "noddoo")

    window = main_window_module.MainWindow()
    qtbot.addWidget(window)
    page = window.web_view.page()

    qtbot.waitUntil(
        lambda: _run_js_sync(page, "!!window.__ORION_APP_READY__") is True,
        timeout=20000,
    )

    yield window, page


# ---------------------------------------------------------------------------
# CA-03 — bleed-through: fondo nunca transparente, en ningún tema
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_fondo_de_app_shell_no_es_transparente(ready_window, qtbot, theme_name):
    _window, page = ready_window
    _run_js_sync(page, f"document.documentElement.dataset.theme = {theme_name!r};")
    qtbot.wait(50)

    bg = _run_js_sync(page, "getComputedStyle(document.getElementById('app-shell')).backgroundColor")

    assert bg not in (None, "", "rgba(0, 0, 0, 0)", "transparent")


# ---------------------------------------------------------------------------
# CA-05 — input invisible: borde/fondo/placeholder siempre presentes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("theme_name", ["dark", "light"])
def test_composer_input_tiene_borde_fondo_y_placeholder(ready_window, qtbot, theme_name):
    _window, page = ready_window
    _run_js_sync(page, f"document.documentElement.dataset.theme = {theme_name!r};")
    qtbot.wait(50)

    row_bg = _run_js_sync(
        page, "getComputedStyle(document.getElementById('composer-input-row')).backgroundColor"
    )
    row_border_width = _run_js_sync(
        page, "getComputedStyle(document.getElementById('composer-input-row')).borderTopWidth"
    )
    placeholder = _run_js_sync(
        page, "document.getElementById('composer-input').getAttribute('placeholder')"
    )

    assert row_bg not in (None, "", "rgba(0, 0, 0, 0)", "transparent")
    assert row_border_width not in (None, "", "0px")
    assert placeholder


# ---------------------------------------------------------------------------
# §10.1 (Hallazgo A) — 3 casos adversariales XSS runtime
# ---------------------------------------------------------------------------

def test_titulo_de_conversacion_xss_no_ejecuta_queda_como_texto_literal(ready_window, qtbot):
    window, page = ready_window
    payload = "<img src=x onerror=window.__xss_fired_title=true>"
    conv_json = json.dumps([
        {"conversation_id": "c1", "title": payload, "last_activity": "", "turn_count": 1}
    ])

    window.bridge.conversation_list_updated.emit(conv_json)
    qtbot.wait(200)

    fired = _run_js_sync(page, "window.__xss_fired_title === true")
    assert fired is not True

    text = _run_js_sync(
        page,
        "(function(){var el = document.querySelector('.conv-title'); "
        "return el ? el.textContent : null;})()",
    )
    assert text == payload


def test_nombre_de_archivo_dropeado_xss_no_ejecuta_queda_como_texto_literal(ready_window, qtbot):
    window, page = ready_window
    payload = "<img src=x onerror=window.__xss_fired_file=true>"

    window.bridge.file_attached.emit("/tmp/x.txt", payload, True, "")
    qtbot.wait(200)

    fired = _run_js_sync(page, "window.__xss_fired_file === true")
    assert fired is not True

    text = _run_js_sync(page, "document.getElementById('attachment-chip-name').textContent")
    assert text == payload


def test_mensaje_de_confirmacion_xss_no_ejecuta_queda_como_texto_literal(ready_window, qtbot):
    window, page = ready_window
    payload = "<img src=x onerror=window.__xss_fired_confirm=true>"

    window.bridge.confirmation_requested.emit("req-xss-1", "delete_conversation", payload)
    qtbot.wait(200)

    fired = _run_js_sync(page, "window.__xss_fired_confirm === true")
    assert fired is not True

    text = _run_js_sync(
        page,
        "(function(){var el = document.querySelector('.modal-message'); "
        "return el ? el.textContent : null;})()",
    )
    assert text == payload
