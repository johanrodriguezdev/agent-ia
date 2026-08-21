"""
tests/test_webview_confirmation_adapter.py
REQ-015/CA-41 — `ui/webview/confirmation_adapter.py::WebViewConfirmationAdapter`.

`confirm()` es puramente `threading` (sin Qt) — se simula la respuesta de JS
(`confirm_response()`) desde OTRO hilo, exactamente como ocurriría en producción (JS
corre en el hilo de la GUI, `confirm()` bloquea el hilo worker de `QThreadPool`). No
requiere `qtbot`: `bridge` se mockea con `MagicMock`, ya que `confirm()` solo necesita que
`bridge.confirmation_requested.emit(...)` sea invocable.

También cubre el Hallazgo B de `security-audit-015.md` (§10.3): limpieza de
`self._pending` tras resolución y manejo defensivo de un `request_id` desconocido.
"""

import threading
import time
from unittest.mock import MagicMock

import ui.webview.confirmation_adapter as ca_module
from ui.webview.confirmation_adapter import WebViewConfirmationAdapter


def _make_adapter():
    bridge = MagicMock()
    captured_request_ids = []
    bridge.confirmation_requested.emit.side_effect = (
        lambda rid, action_name, message: captured_request_ids.append(rid)
    )
    adapter = WebViewConfirmationAdapter(bridge)
    return adapter, bridge, captured_request_ids


def _respond_once_ready(captured_request_ids, adapter, confirmed):
    while not captured_request_ids:
        time.sleep(0.005)
    adapter.confirm_response(captured_request_ids[0], confirmed)


def test_confirm_responde_true_cuando_confirm_response_llega_a_tiempo():
    adapter, bridge, request_ids = _make_adapter()

    responder = threading.Thread(target=_respond_once_ready, args=(request_ids, adapter, True))
    responder.start()
    result = adapter.confirm("delete_conversation", "¿Confirmás el borrado?")
    responder.join(timeout=5)

    assert result is True
    bridge.confirmation_requested.emit.assert_called_once()
    action_name = bridge.confirmation_requested.emit.call_args.args[1]
    assert action_name == "delete_conversation"


def test_confirm_responde_false_cuando_se_cancela():
    adapter, bridge, request_ids = _make_adapter()

    responder = threading.Thread(target=_respond_once_ready, args=(request_ids, adapter, False))
    responder.start()
    result = adapter.confirm("delete_conversation", "¿Confirmás el borrado?")
    responder.join(timeout=5)

    assert result is False


def test_confirm_hace_timeout_fail_closed(monkeypatch):
    """Fail-closed: si nadie responde, retorna `False`, nunca `True` por defecto."""
    monkeypatch.setattr(ca_module, "CONFIRM_TIMEOUT_SECONDS", 0.05)
    adapter, _bridge, _request_ids = _make_adapter()

    result = adapter.confirm("delete_conversation", "¿Confirmás el borrado?")

    assert result is False


def test_pending_se_limpia_tras_timeout_hallazgo_b(monkeypatch):
    monkeypatch.setattr(ca_module, "CONFIRM_TIMEOUT_SECONDS", 0.05)
    adapter, _bridge, _request_ids = _make_adapter()

    adapter.confirm("delete_conversation", "¿Confirmás?")

    assert adapter._pending == {}


def test_pending_se_limpia_tras_resolucion_exitosa_hallazgo_b():
    adapter, _bridge, request_ids = _make_adapter()

    responder = threading.Thread(target=_respond_once_ready, args=(request_ids, adapter, True))
    responder.start()
    adapter.confirm("delete_conversation", "¿Confirmás?")
    responder.join(timeout=5)

    assert adapter._pending == {}
    assert adapter._results == {}


def test_confirm_response_con_request_id_desconocido_no_lanza_hallazgo_b(caplog):
    adapter, _bridge, _request_ids = _make_adapter()

    adapter.confirm_response("request-id-inventado", True)  # no debe lanzar

    assert any("desconocido" in r.message.lower() for r in caplog.records)


def test_dos_confirmaciones_concurrentes_no_se_pisan():
    """Cada solicitud tiene su propio `request_id`/`Event` — dos confirmaciones en vuelo
    a la vez no deben cruzarse."""
    adapter, bridge, request_ids = _make_adapter()
    results = {}

    def run_confirm(key, action_name):
        results[key] = adapter.confirm(action_name, f"¿Confirmás {action_name}?")

    t1 = threading.Thread(target=run_confirm, args=("a", "delete_conversation"))
    t1.start()
    while len(request_ids) < 1:
        time.sleep(0.005)

    t2 = threading.Thread(target=run_confirm, args=("b", "delete_file"))
    t2.start()
    while len(request_ids) < 2:
        time.sleep(0.005)

    # Responder en orden inverso al que se crearon, para probar que no se confunden.
    adapter.confirm_response(request_ids[1], False)
    adapter.confirm_response(request_ids[0], True)

    t1.join(timeout=5)
    t2.join(timeout=5)

    assert results["a"] is True
    assert results["b"] is False
