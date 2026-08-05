"""
tests/test_gui_workers.py
Pruebas de `ui/gui_workers.py:run_async()`/`CallableWorker` (REQ-008) con pytest-qt
(`qtbot`), que ejercita `QThreadPool` real sin abrir una ventana (`QT_QPA_PLATFORM`
offscreen, fijado en tests/conftest.py).
"""

from ui.gui_workers import run_async


def test_run_async_emits_finished_with_result(qtbot):
    received = {}

    def slow_add(a, b):
        return a + b

    def on_done(result):
        received["value"] = result

    run_async(slow_add, on_done, None, 2, 3)

    qtbot.waitUntil(lambda: "value" in received, timeout=2000)
    assert received["value"] == 5


def test_run_async_emits_error_on_exception(qtbot):
    received = {}

    def boom():
        raise ValueError("fallo simulado")

    def on_error(message):
        received["error"] = message

    run_async(boom, None, on_error)

    qtbot.waitUntil(lambda: "error" in received, timeout=2000)
    assert "fallo simulado" in received["error"]


def test_run_async_passes_kwargs(qtbot):
    received = {}

    def greet(name="", greeting="hola"):
        return f"{greeting}, {name}"

    def on_done(result):
        received["value"] = result

    run_async(greet, on_done, None, name="Ana", greeting="hola")

    qtbot.waitUntil(lambda: "value" in received, timeout=2000)
    assert received["value"] == "hola, Ana"


def test_run_async_without_callbacks_does_not_raise(qtbot):
    calls = {"count": 0}

    def noop():
        calls["count"] += 1
        return None

    run_async(noop)

    qtbot.wait(200)
    assert calls["count"] == 1
