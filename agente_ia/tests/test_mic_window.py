"""
tests/test_mic_window.py

REQ-021 (pieza 6) — `voice/mic_window.py::ConversationWindow` y la rama de aceptación sin
wake word de `voice/wake_word.py::listen_for_wake_word()`.

El riesgo #1 del REQ es que el agente se escuche a sí mismo y cree tareas fantasma
(CA-14). Acá se prueba el doble candado: la ventana solo existe cuando el TTS terminó, y
además un chunk que empezó a capturarse antes de abrirse se rechaza.

Sin micrófono real, sin red y sin `sleep` real: el reloj se inyecta
(.claude/rules/testing.md).
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

import config_manager
import voice.wake_word as wake_word_module
from voice.mic_window import MIC_WINDOW_SECONDS, ConversationWindow


class FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _mock_microphone():
    mock_source = MagicMock()
    mock_microphone = MagicMock()
    mock_microphone.__enter__.return_value = mock_source
    mock_microphone.__exit__.return_value = False
    return mock_microphone


# ─────────────────────────────────────────────
#  ConversationWindow — CA-12, CA-13, CA-14
# ─────────────────────────────────────────────

def test_ca12_ca13_ciclo_de_la_ventana():
    clock = FakeClock()
    window = ConversationWindow(duration_s=15.0, clock=clock)

    assert window.accepts(clock.now) is False, "cerrada por defecto: fail-closed"
    assert window.is_open() is False

    window.open()
    assert window.is_open() is True
    assert window.accepts(clock.now) is True

    clock.advance(14.9)
    assert window.accepts(clock.now) is True, "dentro de los ~15 s"

    clock.advance(0.2)                                  # 15.1 s
    assert window.accepts(clock.now) is False, "vencida"
    assert window.is_open() is False


def test_ca14_un_chunk_anterior_a_la_apertura_se_rechaza():
    """El segundo candado: la frase empezó a capturarse mientras el agente hablaba."""
    clock = FakeClock()
    window = ConversationWindow(duration_s=15.0, clock=clock)

    empezo_mientras_hablaba = clock.now - 2
    window.open()

    assert window.accepts(empezo_mientras_hablaba) is False
    assert window.accepts(window.opened_at()) is True


def test_consume_cierra_la_ventana():
    """Una frase por ventana: es la mitigación principal contra el ruido ambiente."""
    clock = FakeClock()
    window = ConversationWindow(duration_s=15.0, clock=clock)
    window.open()

    assert window.accepts(clock.now) is True
    window.consume()
    assert window.accepts(clock.now) is False, "la segunda frase de la misma ventana"


def test_cancel_cierra_en_el_acto():
    """Manos libres OFF a mitad de la ventana."""
    clock = FakeClock()
    window = ConversationWindow(duration_s=15.0, clock=clock)
    window.open()

    window.cancel()

    assert window.accepts(clock.now) is False
    assert window.expired_now() is False, "cancelar no es vencer: no hay que reportar nada"


def test_ca13_expired_now_reporta_una_sola_vez():
    clock = FakeClock()
    window = ConversationWindow(duration_s=15.0, clock=clock)
    window.open()

    assert window.expired_now() is False, "todavía abierta"

    clock.advance(16)
    assert window.expired_now() is True
    assert window.expired_now() is False, "la transición se reporta una sola vez"


def test_expired_now_no_reporta_si_nunca_se_abrio():
    window = ConversationWindow(clock=FakeClock())
    assert window.expired_now() is False


def test_consume_no_dispara_un_reporte_de_expiracion():
    """Tras consumir, el worker vuelve a LISTENING_WAKE por su propio bucle."""
    clock = FakeClock()
    window = ConversationWindow(duration_s=15.0, clock=clock)
    window.open()
    window.consume()

    clock.advance(30)
    assert window.expired_now() is False


def test_la_duracion_vive_en_un_solo_lugar():
    """Condición 2 del hallazgo H4 de la auditoría: poder bajarla tras la prueba en vivo
    sin rediseñar nada."""
    assert MIC_WINDOW_SECONDS == 15.0
    assert ConversationWindow().is_open() is False


def test_no_hay_hilos_ni_timers():
    """Prohibición 6 de la auditoría: la expiración se evalúa al leer, sin hilo de fondo
    ni timer. Y ningún hilo espera al otro: sin `wait()`/`join()` no hay deadlock."""
    import ast
    from pathlib import Path

    src = Path(wake_word_module.__file__).resolve().parent / "mic_window.py"
    arbol = ast.parse(src.read_text(encoding="utf-8"))

    prohibidos = {"Timer", "Thread", "wait", "join", "sleep"}
    llamadas = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call):
            func = nodo.func
            nombre = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            llamadas.add(nombre)

    assert prohibidos.isdisjoint(llamadas), llamadas & prohibidos


# ─────────────────────────────────────────────
#  listen_for_wake_word — la rama de aceptación sin wake word
# ─────────────────────────────────────────────

@pytest.fixture
def perfil(monkeypatch):
    monkeypatch.setattr(config_manager, "get_agent_name", lambda: "O.R.I.O.N")
    monkeypatch.setattr(config_manager, "get_agent_pronunciation", lambda: "orion")


def _escuchar_una_frase(frase: str, conversation_window):
    """Corre `listen_for_wake_word()` con un recognizer falso que dice `frase` una vez."""
    mock_recognizer = MagicMock()
    mock_recognizer.listen.return_value = MagicMock()
    # La 2ª vuelta corta el bucle vía stop_event.
    stop_event = threading.Event()

    def transcribir(audio, language=None):
        stop_event.set()
        return frase

    mock_recognizer.recognize_google.side_effect = transcribir

    with patch.object(wake_word_module.sr, "Microphone", return_value=_mock_microphone()), \
         patch.object(wake_word_module.sr, "Recognizer", return_value=mock_recognizer), \
         patch.object(wake_word_module, "speak"):
        return wake_word_module.listen_for_wake_word(
            stop_event=stop_event, conversation_window=conversation_window,
        )


def test_ca12_con_la_ventana_abierta_la_frase_se_acepta_sin_wake_word(perfil):
    window = ConversationWindow(duration_s=15.0)
    window.open()

    resultado = _escuchar_una_frase("llamar al contador", window)

    assert resultado == "llamar al contador"
    assert window.accepts(window.opened_at() or 0) is False, "consume() debía cerrarla"


def test_ca13_con_la_ventana_cerrada_la_misma_frase_no_se_resuelve(perfil):
    window = ConversationWindow(duration_s=15.0)      # nunca se abrió

    resultado = _escuchar_una_frase("llamar al contador", window)

    assert resultado is None, "sin ventana debe seguir exigiéndose la wake word"


def test_sin_ventana_el_comportamiento_es_el_de_siempre(perfil):
    """Compatibilidad: `ui/cli.py` y los tests existentes llaman sin el parámetro."""
    resultado = _escuchar_una_frase("orión abre chrome", None)

    assert resultado == "abre chrome"


def test_la_frase_con_wake_word_sigue_funcionando_con_la_ventana_cerrada(perfil):
    window = ConversationWindow(duration_s=15.0)

    resultado = _escuchar_una_frase("orión abre chrome", window)

    assert resultado == "abre chrome"


def test_ca13_al_vencer_la_ventana_el_estado_vuelve_a_listening_wake(perfil):
    clock = FakeClock()
    window = ConversationWindow(duration_s=15.0, clock=clock)
    window.open()
    clock.advance(16)

    estados = []
    resultado = _escuchar_una_frase_con_estado("ruido cualquiera", window, estados)

    assert "LISTENING_WAKE" in estados
    assert resultado is None


def _escuchar_una_frase_con_estado(frase: str, conversation_window, estados: list):
    mock_recognizer = MagicMock()
    mock_recognizer.listen.return_value = MagicMock()
    stop_event = threading.Event()

    def transcribir(audio, language=None):
        stop_event.set()
        return frase

    mock_recognizer.recognize_google.side_effect = transcribir

    with patch.object(wake_word_module.sr, "Microphone", return_value=_mock_microphone()), \
         patch.object(wake_word_module.sr, "Recognizer", return_value=mock_recognizer), \
         patch.object(wake_word_module, "speak"):
        return wake_word_module.listen_for_wake_word(
            stop_event=stop_event, wake_state_callback=estados.append,
            conversation_window=conversation_window,
        )


# ─────────────────────────────────────────────
#  El worker le pasa su ventana al bucle
# ─────────────────────────────────────────────

def test_el_worker_pasa_su_ventana_a_listen_for_wake_word():
    from ui.webview.wake_word_worker import WakeWordWorker

    worker = WakeWordWorker()
    recibidos = []

    def fake_listen(**kwargs):
        recibidos.append(kwargs)
        return None

    with patch("voice.wake_word.listen_for_wake_word", side_effect=fake_listen):
        worker.run()

    assert recibidos[0]["conversation_window"] is worker.conversation_window


def test_el_worker_cancela_la_ventana_al_terminar():
    from ui.webview.wake_word_worker import WakeWordWorker

    worker = WakeWordWorker()
    worker.conversation_window.open()

    with patch("voice.wake_word.listen_for_wake_word", side_effect=lambda **kw: None):
        worker.run()

    assert worker.conversation_window.is_open() is False


# ─────────────────────────────────────────────
#  CA-29 (a) — el barge-in sigue funcionando
#
#  Mitad PRE-EXISTENTE de CA-29: `signal_barge_in()` corta la locución en curso y el
#  bucle de escucha lo señala en cuanto el usuario habla encima del agente. Llegó a este
#  REQ sin una sola ocurrencia de "barge" en toda la suite (test-results-021.md §FAIL),
#  así que estos tests valen como red: la ventana de micrófono se apoya en que el usuario
#  pueda cortar al agente, y sin ellos nadie se enteraría si dejara de cortarse.
#
#  La mitad NUEVA de CA-29 —que el diálogo pendiente sobrevive a la interrupción— vive en
#  `tests/test_dialog_resolution.py`, donde están las fixtures del diálogo.
# ─────────────────────────────────────────────


class _ProcesoFalso:
    """`ffplay` falso: `poll()` devuelve la secuencia dada, `kill()` se cuenta."""

    def __init__(self, polls):
        self._polls = list(polls)
        self.poll_calls = 0
        self.killed = 0

    def poll(self):
        self.poll_calls += 1
        return self._polls[min(self.poll_calls - 1, len(self._polls) - 1)]

    def kill(self):
        self.killed += 1


def test_ca29_el_barge_in_corta_la_locucion_en_curso(monkeypatch):
    """CA-29: con `_barge_in` señalado, la reproducción se mata en el acto en vez de
    esperar a que el audio termine solo."""
    import ui.tts_engine as tts

    monkeypatch.setattr(tts, "_barge_in", False)      # global de proceso: se restaura solo

    # `poll()` devolvería None dos veces y 0 a la tercera: el audio terminaría solo.
    proceso = _ProcesoFalso([None, None, 0])
    monkeypatch.setattr(tts.subprocess, "Popen", lambda *a, **k: proceso)

    tts.signal_barge_in()                              # el usuario habla encima del agente
    tts._play_mp3_windows("audio_falso.mp3")

    assert proceso.killed >= 1, "el barge-in no cortó la locución"
    assert proceso.poll_calls <= 2, (
        "esperó a que el audio terminara solo en vez de cortarlo en el primer chequeo"
    )


def test_ca29_sin_barge_in_la_locucion_termina_sola(monkeypatch):
    """El contraste que le da valor al test de arriba: sin interrupción no se mata nada."""
    import ui.tts_engine as tts

    monkeypatch.setattr(tts, "_barge_in", False)
    proceso = _ProcesoFalso([None, None, 0])
    monkeypatch.setattr(tts.subprocess, "Popen", lambda *a, **k: proceso)

    tts._play_mp3_windows("audio_falso.mp3")

    assert proceso.killed == 0, "se cortó una locución que nadie interrumpió"
    assert proceso.poll_calls >= 3, "no dejó terminar el audio"


def test_ca29_el_bucle_de_escucha_senala_el_barge_in_mientras_el_agente_habla(perfil):
    """CA-29: si entra audio del usuario con el agente hablando, el bucle señala el corte.

    `voice/wake_word.py` importa `is_speaking`/`signal_barge_in` DENTRO del bucle, así que
    parchear los atributos del módulo `ui.tts_engine` alcanza al punto real de uso.
    """
    import ui.tts_engine as tts

    with patch.object(tts, "is_speaking", return_value=True),          patch.object(tts, "signal_barge_in") as senal:
        _escuchar_una_frase("llamar al contador", None)

    assert senal.called, "el usuario habló encima del agente y nadie cortó la locución"


def test_ca29_sin_locucion_en_curso_el_bucle_no_senala_barge_in(perfil):
    """Fail-safe del lado contrario: cortar una locución que no existe apagaría la
    siguiente (`_barge_in` queda pegado hasta el `finally` de `_speak_edge`)."""
    import ui.tts_engine as tts

    with patch.object(tts, "is_speaking", return_value=False),          patch.object(tts, "signal_barge_in") as senal:
        _escuchar_una_frase("llamar al contador", None)

    assert not senal.called, "señaló un barge-in sin nadie hablando"

def test_una_frase_larga_que_empezo_a_tiempo_no_se_pierde():
    """El caso que aparece al permitir dictar frases largas.

    Se empieza a hablar en el segundo 10 de una ventana de 15 y se habla 10 segundos: la
    frase se transcribe en el segundo 20. Antes el vencimiento se medía contra el reloj de
    ese momento, así que se descartaba — y desde fuera se vive como que el agente ignoró
    una instrucción que se dictó a tiempo. La ventana promete "durante estos segundos
    puedes hablar sin decir mi nombre"; terminar la frase es parte de hablar.
    """
    reloj = FakeClock()
    ventana = ConversationWindow(duration_s=15.0, clock=reloj)
    ventana.open()

    empezo_a_hablar = reloj.now + 10
    reloj.advance(20)          # la frase duró 10 s: se pregunta en el segundo 20

    assert ventana.accepts(empezo_a_hablar) is True


def test_una_frase_que_empezo_despues_de_vencer_no_entra():
    """La otra mitad: juzgar por el inicio no puede volver la ventana eterna."""
    reloj = FakeClock()
    ventana = ConversationWindow(duration_s=15.0, clock=reloj)
    ventana.open()

    empezo_tarde = reloj.now + 16
    reloj.advance(20)

    assert ventana.accepts(empezo_tarde) is False
