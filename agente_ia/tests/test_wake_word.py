"""
tests/test_wake_word.py
REQ-009 — cobertura nueva para el mecanismo de cancelación cooperativa y el canal de
reporte de estado agregados a `voice/wake_word.py::listen_for_wake_word()`.

Sin micrófono real: `sr.Microphone`/`sr.Recognizer` van mockeados (.claude/rules/testing.md).
"""

import threading
from unittest.mock import MagicMock, patch

import voice.wake_word as wake_word_module


def _mock_microphone():
    mock_source = MagicMock()
    mock_microphone = MagicMock()
    mock_microphone.__enter__.return_value = mock_source
    mock_microphone.__exit__.return_value = False
    return mock_microphone


# ---------------------------------------------------------------------------
# CA-05: stop_event ya seteado -> listen_for_wake_word() retorna None sin escuchar
# ---------------------------------------------------------------------------

def test_stop_event_causes_listen_for_wake_word_to_return_none():
    stop_event = threading.Event()
    stop_event.set()

    mock_recognizer = MagicMock()

    with patch.object(wake_word_module.sr, "Microphone", return_value=_mock_microphone()), \
         patch.object(wake_word_module.sr, "Recognizer", return_value=mock_recognizer):
        result = wake_word_module.listen_for_wake_word(stop_event=stop_event)

    assert result is None
    mock_recognizer.listen.assert_not_called()


def test_listen_for_wake_word_without_stop_event_does_not_crash_on_first_check():
    """CA-07: sin stop_event (uso actual del CLI), la revisión `stop_event is not None`
    no debe lanzar — solo se salta la parada cooperativa, tal como antes de REQ-009."""
    mock_recognizer = MagicMock()
    mock_recognizer.listen.side_effect = wake_word_module.sr.WaitTimeoutError()

    call_state = {"n": 0}
    orig_listen = mock_recognizer.listen

    def listen_side_effect(*args, **kwargs):
        call_state["n"] += 1
        if call_state["n"] > 1:
            raise KeyboardInterrupt()
        raise wake_word_module.sr.WaitTimeoutError()

    mock_recognizer.listen.side_effect = listen_side_effect

    with patch.object(wake_word_module.sr, "Microphone", return_value=_mock_microphone()), \
         patch.object(wake_word_module.sr, "Recognizer", return_value=mock_recognizer):
        result = wake_word_module.listen_for_wake_word()

    assert result is False  # camino de KeyboardInterrupt, comportamiento preexistente


# ---------------------------------------------------------------------------
# CA-04 / riesgos: _report_awake nunca deja una excepción del callback sin loguear
# ---------------------------------------------------------------------------

def test_report_awake_calls_callback_with_awake():
    received = []
    wake_word_module._report_awake(received.append)
    assert received == ["AWAKE"]


def test_report_awake_with_none_callback_is_noop():
    # No debe lanzar cuando no hay callback (uso desde el CLI, wake_state_callback=None).
    wake_word_module._report_awake(None)


def test_report_awake_logs_callback_exception_without_raising(caplog):
    import logging

    def boom(_state):
        raise RuntimeError("callback roto")

    with caplog.at_level(logging.ERROR):
        wake_word_module._report_awake(boom)  # no debe propagar

    assert any("callback roto" in record.message for record in caplog.records)
