"""
tests/test_wake_word_gui.py
REQ-009 — cobertura nueva para el toggle de modo manos libres en la GUI JARVIS:
`CenterPanel`/`HeaderBar` (CA-01, CA-02), `ui/gui.py:WakeWordWorker`/`JarvisMainWindow`
(CA-03, CA-04, CA-05, CA-08, CA-09, CA-10) y el caso borde de doble clic.

Con `pytest-qt` (`qtbot`) en modo offscreen (fijado en tests/conftest.py). Nunca toca
`sr.Microphone()` real: `voice.wake_word.listen_for_wake_word` va mockeado en todos los
tests que ejercitan `WakeWordWorker`/`JarvisMainWindow`, y `QThreadPool.globalInstance()`
se reemplaza para no arrancar hilos reales (evita bloquear la suite).
"""

import logging
from unittest.mock import MagicMock

import pytest

import ui.gui as gui_module
import ui.widgets.recent_activity_card as recent_activity_module
import ui.widgets.weather_card as weather_card_module
from ui.gui import JarvisMainWindow, WakeWordWorker
from ui.widgets.center_panel import CenterPanel
from ui.widgets.header_bar import HeaderBar


@pytest.fixture
def no_external_io(monkeypatch):
    """Evita que `WeatherCard` haga una petición HTTP real y que `RecentActivityCard`
    lea la base de datos de memoria real al construir `JarvisMainWindow` (mismo patrón
    de tests/test_gui_widgets.py, REQ-008)."""
    monkeypatch.setattr(weather_card_module, "run_async", lambda *a, **k: None)
    monkeypatch.setattr(recent_activity_module.memory, "get_recent", lambda **kwargs: [])


@pytest.fixture
def no_real_threadpool(monkeypatch):
    """Reemplaza `QThreadPool.globalInstance().start(...)` por una lista de workers
    "arrancados" sin ejecutar `run()` de verdad — evita que un test dispare un hilo real
    que llame a `sr.Microphone()`."""
    started = []
    fake_pool = MagicMock()
    fake_pool.start = lambda worker: started.append(worker)
    monkeypatch.setattr(gui_module.QThreadPool, "globalInstance", staticmethod(lambda: fake_pool))
    return started


@pytest.fixture(autouse=True)
def reset_wake_state():
    """`WAKE_STATE` es una variable de módulo compartida — restaurarla entre tests para
    que el orden de ejecución no afecte otras pruebas de la suite."""
    yield
    gui_module.update_wake_state("INACTIVE")


# ---------------------------------------------------------------------------
# CA-01: CenterPanel — toggle visible desde el arranque, inicial "inactivo"
# ---------------------------------------------------------------------------

def test_center_panel_wake_toggle_starts_unchecked(qtbot):
    panel = CenterPanel()
    qtbot.addWidget(panel)

    toggle = panel.findChild(type(panel._wake_toggle), "WakeToggleButton")
    assert toggle is not None
    assert toggle.isChecked() is False
    assert toggle.property("wakeState") == "INACTIVE"


def test_center_panel_set_wake_state_does_not_reemit_signal(qtbot):
    panel = CenterPanel()
    qtbot.addWidget(panel)

    received = []
    panel.hands_free_toggled.connect(received.append)

    panel.set_wake_state("LISTENING_WAKE")

    assert received == []
    assert panel._wake_toggle.isChecked() is True
    assert panel._wake_toggle.property("wakeState") == "LISTENING_WAKE"


def test_center_panel_toggle_click_emits_hands_free_toggled(qtbot):
    panel = CenterPanel()
    qtbot.addWidget(panel)

    received = []
    panel.hands_free_toggled.connect(received.append)

    panel._wake_toggle.click()

    assert received == [True]


# ---------------------------------------------------------------------------
# CA-02: HeaderBar — indicador de wake word separado de la píldora "Modo activo"
# ---------------------------------------------------------------------------

def test_header_bar_wake_indicator_is_separate_widget(qtbot):
    header = HeaderBar()
    qtbot.addWidget(header)

    assert header._wake_indicator is not header._mode_pill

    mode_pill_text_before = header._mode_pill.text()
    header.set_wake_state("LISTENING_WAKE")
    assert header._mode_pill.text() == mode_pill_text_before  # no se pisan

    wake_text_before = header._wake_indicator.text()
    header.set_state("LISTENING")
    assert header._wake_indicator.text() == wake_text_before  # no se confunden


# ---------------------------------------------------------------------------
# CA-03: encender el toggle arranca el worker en background, sin bloquear
# ---------------------------------------------------------------------------

def test_toggle_on_starts_worker_without_blocking(qtbot, no_external_io, no_real_threadpool):
    window = JarvisMainWindow()
    qtbot.addWidget(window)

    window._on_hands_free_toggled(True)

    assert len(no_real_threadpool) == 1
    assert isinstance(no_real_threadpool[0], WakeWordWorker)
    assert window._wake_worker is no_real_threadpool[0]


def test_double_click_toggle_does_not_start_two_workers(qtbot, no_external_io, no_real_threadpool):
    window = JarvisMainWindow()
    qtbot.addWidget(window)

    window._on_hands_free_toggled(True)
    window._on_hands_free_toggled(True)

    assert len(no_real_threadpool) == 1


# ---------------------------------------------------------------------------
# CA-04: detección de wake word reporta "AWAKE" y nunca invoca resolve()
# ---------------------------------------------------------------------------

def test_wake_word_worker_detected_does_not_call_resolve(monkeypatch):
    states = []
    monkeypatch.setattr(gui_module, "update_wake_state", lambda s: states.append(s))

    call_count = {"n": 0}

    def fake_listen(stop_event=None, wake_state_callback=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            wake_state_callback("AWAKE")
            return True
        stop_event.set()
        return None

    monkeypatch.setattr("voice.wake_word.listen_for_wake_word", fake_listen)

    resolve_mock = MagicMock()
    monkeypatch.setattr("core.resolution.resolve", resolve_mock)

    worker = WakeWordWorker()
    worker.run()

    assert "AWAKE" in states
    resolve_mock.assert_not_called()


# ---------------------------------------------------------------------------
# CA-05: apagar el toggle pide parada cooperativa (stop_event) del worker activo
# ---------------------------------------------------------------------------

def test_toggle_off_sets_stop_event_on_active_worker(qtbot, no_external_io, no_real_threadpool):
    window = JarvisMainWindow()
    qtbot.addWidget(window)

    window._on_hands_free_toggled(True)
    worker = window._wake_worker
    assert worker.stop_event.is_set() is False

    window._on_hands_free_toggled(False)
    assert worker.stop_event.is_set() is True


# ---------------------------------------------------------------------------
# CA-08: togglear (encender/apagar) nunca dispara speak()/TTS
# ---------------------------------------------------------------------------

def test_toggle_never_calls_speak(qtbot, no_external_io, no_real_threadpool, monkeypatch):
    speak_mock = MagicMock()
    monkeypatch.setattr("ui.tts_engine.speak", speak_mock)

    window = JarvisMainWindow()
    qtbot.addWidget(window)

    window._on_hands_free_toggled(True)
    window._on_hands_free_toggled(False)

    speak_mock.assert_not_called()


# ---------------------------------------------------------------------------
# CA-09: aboutToQuit / cierre real del proceso detiene el worker activo
# ---------------------------------------------------------------------------

def test_stop_wake_word_worker_is_noop_without_active_worker(qtbot, no_external_io):
    window = JarvisMainWindow()
    qtbot.addWidget(window)

    window._stop_wake_word_worker()  # no debe lanzar sin worker activo


def test_stop_wake_word_worker_stops_active_worker(qtbot, no_external_io, no_real_threadpool):
    window = JarvisMainWindow()
    qtbot.addWidget(window)

    window._on_hands_free_toggled(True)
    worker = window._wake_worker

    window._stop_wake_word_worker()

    assert worker.stop_event.is_set() is True


def test_about_to_quit_signal_stops_active_worker(qtbot, no_external_io, no_real_threadpool):
    """CA-09 — verifica el *wiring* real hecho en `_setup_tray_icon()`
    (`QApplication.instance().aboutToQuit.connect(self._stop_wake_word_worker)`), no solo
    el método `_stop_wake_word_worker()` en aislamiento."""
    from PyQt6.QtWidgets import QApplication

    window = JarvisMainWindow()
    qtbot.addWidget(window)

    window._on_hands_free_toggled(True)
    worker = window._wake_worker
    assert worker.stop_event.is_set() is False

    QApplication.instance().aboutToQuit.emit()

    assert worker.stop_event.is_set() is True


# ---------------------------------------------------------------------------
# CA-10: fallo dentro del worker se loguea (nunca silenciado) y resetea a "inactivo"
# ---------------------------------------------------------------------------

def test_wake_word_worker_logs_error_and_resets_to_inactive(monkeypatch, caplog):
    def fake_listen(stop_event=None, wake_state_callback=None):
        raise OSError("mic no disponible")

    monkeypatch.setattr("voice.wake_word.listen_for_wake_word", fake_listen)

    worker = WakeWordWorker()
    with caplog.at_level(logging.ERROR):
        worker.run()  # no debe propagar la excepción (QRunnable no tiene dónde)

    assert gui_module.WAKE_STATE == "INACTIVE"
    assert any("mic no disponible" in record.message for record in caplog.records)


def test_poll_state_clears_wake_worker_reference_when_inactive(qtbot, no_external_io, no_real_threadpool):
    """Complementa CA-05/CA-10: `_poll_state()` libera `self._wake_worker` cuando el
    canal vuelve a INACTIVE, permitiendo un nuevo ON posterior (mitigación de doble clic
    documentada en arquitectura-009.md)."""
    window = JarvisMainWindow()
    qtbot.addWidget(window)

    window._on_hands_free_toggled(True)
    assert window._wake_worker is not None

    # Forzar una transición real (INACTIVE -> LISTENING_WAKE -> INACTIVE): `_poll_state()`
    # solo actúa cuando detecta un cambio respecto a `self._current_wake_state`.
    gui_module.update_wake_state("LISTENING_WAKE")
    window._poll_state()
    assert window._wake_worker is not None  # todavía activo mientras escucha

    gui_module.update_wake_state("INACTIVE")
    window._poll_state()

    assert window._wake_worker is None
