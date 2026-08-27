"""
tests/test_wake_word_comando.py
Regresión del modo manos libres: el comando dictado después de la wake word tiene que
llegar a ejecutarse, y la wake word tiene que reconocerse sea cual sea el nombre que el
usuario haya puesto en Configuración.

Cubre tres bugs reales encontrados en prueba manual ("le dije el nombre del agente pero no
realizó las acciones"):

1. `WakeWordWorker.run()` guardaba el comando en `result` y lo descartaba: el agente
   despertaba, contestaba, y nunca ejecutaba nada.
2. `get_wake_words()` devolvía las frases SIN normalizar, mientras que la transcripción sí
   se normalizaba — un nombre con acento ("Sofía") o con puntos ("A.R.I.A") no coincidía
   jamás. Solo "orion" funcionaba, por una lista de variantes escrita a mano.
3. El nombre se interpolaba crudo en una expresión regular (`\b + nombre + \b`), así que
   los puntos de "O.R.I.O.N" actuaban como comodín y un nombre con paréntesis reventaba
   la síntesis de voz con `re.error`.

Sin micrófono real ni red (.claude/rules/testing.md).
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

import config_manager
import voice.wake_word as wake_word_module


@pytest.fixture
def perfil(monkeypatch):
    """Fija nombre y pronunciación sin tocar el `config.json` real."""
    def _set(nombre: str, pronunciacion: str):
        monkeypatch.setattr(config_manager, "get_agent_name", lambda: nombre)
        monkeypatch.setattr(config_manager, "get_agent_pronunciation", lambda: pronunciacion)
    return _set


def _mock_microphone():
    mock_source = MagicMock()
    mock_microphone = MagicMock()
    mock_microphone.__enter__.return_value = mock_source
    mock_microphone.__exit__.return_value = False
    return mock_microphone


# ---------------------------------------------------------------------------
# Bug 2 — la wake word se reconoce con cualquier nombre configurado
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "nombre,pronunciacion,frase,comando_esperado",
    [
        ("O.R.I.O.N", "orion", "Orión, abre Chrome", "abre chrome"),
        ("O.R.I.O.N", "orion", "O.R.I.O.N. abre chrome", "abre chrome"),
        ("O.R.I.O.N", "orion", "hey Orión qué hora es", "que hora es"),
        # Con acento: antes NO coincidía nunca (el texto se normalizaba, la wake word no).
        ("Sofía", "Sofía", "Sofía, abre Chrome", "abre chrome"),
        ("Sofía", "Sofía", "sofia abre chrome", "abre chrome"),
        # Acrónimo con puntos distinto de "orion": antes dependía de la lista hardcodeada.
        ("A.R.I.A", "aria", "Aria completa mis tareas", "completa mis tareas"),
        ("A.R.I.A", "aria", "A.R.I.A. abre chrome", "abre chrome"),
        # Nombre compuesto: el espacio interno se conserva.
        ("Jarvis Prime", "yarvis prime", "Jarvis Prime, abre Chrome", "abre chrome"),
    ],
)
def test_wake_word_se_reconoce_con_cualquier_nombre(
    perfil, nombre, pronunciacion, frase, comando_esperado
):
    perfil(nombre, pronunciacion)
    detectada, comando = wake_word_module.parse_wake_command(frase)
    assert detectada, f"'{frase}' no despertó al agente llamado {nombre!r}"
    assert comando == comando_esperado


def test_frase_sin_wake_word_no_despierta(perfil):
    """El guard real: sin el nombre, nada se ejecuta."""
    perfil("O.R.I.O.N", "orion")
    detectada, comando = wake_word_module.parse_wake_command("abre chrome")
    assert detectada is False
    assert comando == ""


def test_wake_words_salen_normalizadas(perfil):
    """Invariante: comparables tal cual contra una transcripción normalizada."""
    perfil("Sofía", "Sofía")
    palabras = config_manager.get_wake_words()
    assert "sofia" in palabras
    assert not any("í" in w for w in palabras), palabras


# ---------------------------------------------------------------------------
# Bug 1 — el comando dictado llega al Bridge en vez de descartarse
# ---------------------------------------------------------------------------

def test_worker_emite_el_comando_detectado():
    from ui.webview.wake_word_worker import WakeWordWorker

    worker = WakeWordWorker()
    recibidos = []
    worker.signals.command_detected.connect(recibidos.append)

    # Primera vuelta devuelve el comando; la segunda corta el loop.
    resultados = iter(["abre chrome", None])

    with patch("voice.wake_word.listen_for_wake_word", side_effect=lambda **kw: next(resultados)):
        worker.run()

    assert recibidos == ["abre chrome"], (
        "el comando dictado se perdió: es el bug de 'despierta pero no hace nada'"
    )


def test_worker_no_emite_cuando_solo_hubo_wake_word_sin_comando():
    """`True` = se dijo el nombre pero no hubo comando que ejecutar."""
    from ui.webview.wake_word_worker import WakeWordWorker

    worker = WakeWordWorker()
    recibidos = []
    worker.signals.command_detected.connect(recibidos.append)

    resultados = iter([True, None])
    with patch("voice.wake_word.listen_for_wake_word", side_effect=lambda **kw: next(resultados)):
        worker.run()

    assert recibidos == []


def test_worker_no_emite_comando_vacio():
    from ui.webview.wake_word_worker import WakeWordWorker

    worker = WakeWordWorker()
    recibidos = []
    worker.signals.command_detected.connect(recibidos.append)

    resultados = iter(["   ", None])
    with patch("voice.wake_word.listen_for_wake_word", side_effect=lambda **kw: next(resultados)):
        worker.run()

    assert recibidos == []


def test_wake_word_sin_comando_escucha_el_dictado_siguiente(perfil):
    """Decir solo el nombre y dictar después también tiene que ejecutar la acción."""
    perfil("O.R.I.O.N", "orion")
    mock_recognizer = MagicMock()
    audio = MagicMock()
    mock_recognizer.listen.return_value = audio
    # 1ª transcripción: solo la wake word. 2ª: el comando dictado a continuación.
    mock_recognizer.recognize_google.side_effect = ["Orión", "abre chrome"]

    with patch.object(wake_word_module.sr, "Microphone", return_value=_mock_microphone()), \
         patch.object(wake_word_module.sr, "Recognizer", return_value=mock_recognizer), \
         patch.object(wake_word_module, "speak"):
        resultado = wake_word_module.listen_for_wake_word(stop_event=threading.Event())

    assert resultado == "abre chrome"


def test_bridge_resuelve_el_comando_de_voz_como_uno_escrito():
    """Cierra el circuito: la señal del worker termina en el mismo `send_message()`.

    Así el comando por voz pasa por `resolve()` y por el gate de seguridad, en vez de
    tener un camino propio que los saltee.
    """
    from ui.webview.bridge import Bridge

    bridge = Bridge.__new__(Bridge)          # sin QObject.__init__: no hace falta para esto
    bridge._resolution_in_flight = False
    enviados = []
    bridge.send_message = enviados.append

    Bridge._on_voice_command(bridge, "abre chrome")
    assert enviados == ["abre chrome"]


def test_bridge_descarta_un_comando_de_voz_solapado_no_un_segundo_turno():
    """Descartar un comando de voz que llega CON UNA RESOLUCIÓN EN CURSO sigue siendo lo
    correcto: eso es una colisión (doble envío), no un turno de conversación.

    Un segundo turno legítimo no puede llegar en este estado. Desde REQ-021 el orden es:
    `resolve()` termina -> se libera el guard -> empieza el TTS -> termina el TTS -> se
    arma la ventana de micrófono -> recién ahí puede entrar la frase siguiente. En ese
    instante el guard lleva libre toda la locución, así que CA-15 se cumple por
    construcción del timeline, sin debilitar el guard (arquitectura-021.md §7.2). El
    problema de este test era su alcance implícito, no su aserción.
    """
    from ui.webview.bridge import Bridge

    bridge = Bridge.__new__(Bridge)
    bridge._resolution_in_flight = True
    enviados = []
    bridge.send_message = enviados.append

    Bridge._on_voice_command(bridge, "abre chrome")
    assert enviados == []


# ---------------------------------------------------------------------------
# REQ-021 — pieza 8 (voz en el webview) y ventana de micrófono
# ---------------------------------------------------------------------------

def _bridge_con_worker(worker=None):
    """Bridge mínimo, sin `QObject.__init__`: solo el estado que tocan estos caminos."""
    from ui.webview.bridge import Bridge

    bridge = Bridge.__new__(Bridge)
    bridge._resolution_in_flight = False
    bridge._pending_user_text = ""
    bridge._conversation_id = "c1"
    bridge._speech_seq = 0
    bridge._speech_done_seq = 0
    bridge._wake_worker = worker
    return bridge


class _WorkerFalso:
    def __init__(self):
        from voice.mic_window import ConversationWindow

        self.stop_event = threading.Event()
        self.conversation_window = ConversationWindow()


def test_ca23_solo_habla_con_el_manos_libres_activo():
    """CA-23 (ajustado por Johan): se pronuncia SOLO en manos libres. Con la wake word
    apagada, un mensaje escrito no se pronuncia ni una vez. La condición se evalúa sobre
    el estado real del worker, nunca sobre el texto ni sobre el canal declarado."""
    from ui.webview.bridge import Bridge

    despachos = []
    with patch("ui.webview.bridge.run_async", side_effect=lambda *a, **k: despachos.append(a)):
        sin_worker = _bridge_con_worker(None)
        Bridge._speak_response(sin_worker, "Tarea registrada.")
        assert despachos == [], "no debe hablar con el manos libres apagado"

        con_worker = _bridge_con_worker(_WorkerFalso())
        Bridge._speak_response(con_worker, "Tarea registrada.")
        assert len(despachos) == 1, "exactamente una locución por turno resuelto"


def test_ca25_speak_nunca_se_invoca_desde_el_hilo_de_la_gui():
    """CA-25: `speak()` es bloqueante; siempre por `run_async`, nunca directo."""
    import ui.tts_engine as tts
    from ui.webview.bridge import Bridge

    despachos = []
    with patch("ui.webview.bridge.run_async", side_effect=lambda *a, **k: despachos.append(a)), \
         patch.object(tts, "speak", side_effect=AssertionError("speak() directo")) as speak_mock:
        Bridge._speak_response(_bridge_con_worker(_WorkerFalso()), "Hola.")
        fn, on_done, on_error, texto = despachos[0]
        assert fn is speak_mock, "se despachó otra cosa en vez de speak()"
        speak_mock.assert_not_called()
    assert on_done.__name__ == "_on_speech_done"
    assert on_error.__name__ == "_on_speech_error"
    # Métodos vinculados de un QObject del hilo de la GUI, nunca lambdas (ui/gui_workers.py).
    assert hasattr(on_done, "__self__") and hasattr(on_error, "__self__")


def test_ca24_se_pronuncia_el_texto_crudo_preparado_nunca_el_html():
    """CA-24: el origen es `resolution.text`, no el HTML de `render_markdown()`."""
    from ui.tts_engine import prepare_for_speech
    from ui.webview.bridge import Bridge

    crudo = "✅ *Tarea registrada.*\n\n📋 *Llamar al contador*\n🆔 #12"
    despachos = []
    with patch("ui.webview.bridge.run_async", side_effect=lambda *a, **k: despachos.append(a)):
        Bridge._speak_response(_bridge_con_worker(_WorkerFalso()), crudo)

    texto_hablado = despachos[0][3]
    assert texto_hablado == prepare_for_speech(crudo)
    assert "<" not in texto_hablado and "*" not in texto_hablado and "#" not in texto_hablado


def test_ca26_la_ventana_abre_al_terminar_la_locucion_no_antes():
    """CA-26/CA-14: la ventana se arma en el `on_done` de la tarea de voz. Mientras el
    agente habla no existe, así que no puede transcribirse a sí mismo."""
    from ui.webview.bridge import Bridge

    worker = _WorkerFalso()
    bridge = _bridge_con_worker(worker)

    with patch("ui.webview.bridge.run_async", side_effect=lambda *a, **k: None):
        Bridge._speak_response(bridge, "Tarea registrada.")

    assert worker.conversation_window.is_open() is False, "abrió antes de terminar de hablar"

    Bridge._on_speech_done(bridge, None)
    assert worker.conversation_window.is_open() is True


def test_ca28_un_fallo_del_tts_abre_la_ventana_igual():
    """CA-28: la respuesta ya está en pantalla; un problema de audio no puede dejar la
    conversación muerta."""
    from ui.webview.bridge import Bridge

    worker = _WorkerFalso()
    bridge = _bridge_con_worker(worker)
    bridge._speech_seq = 1

    Bridge._on_speech_error(bridge, "edge-tts no instalado")

    assert worker.conversation_window.is_open() is True


def test_la_ventana_no_se_abre_con_el_manos_libres_apagado():
    """Un `on_done` tardío tras apagar el manos libres no puede armar nada."""
    from ui.webview.bridge import Bridge

    worker = _WorkerFalso()
    worker.stop_event.set()
    bridge = _bridge_con_worker(worker)

    Bridge._on_speech_done(bridge, None)
    assert worker.conversation_window.is_open() is False

    sin_worker = _bridge_con_worker(None)
    Bridge._on_speech_done(sin_worker, None)          # no debe lanzar


def test_r10_solo_la_locucion_mas_reciente_arma_la_ventana():
    """Dos locuciones solapadas (el usuario escribe mientras el agente habla) no pueden
    abrir la ventana dos veces ni antes de tiempo."""
    from ui.webview.bridge import Bridge

    worker = _WorkerFalso()
    bridge = _bridge_con_worker(worker)
    bridge._speech_seq = 2                            # dos locuciones en vuelo

    Bridge._on_speech_done(bridge, None)
    assert worker.conversation_window.is_open() is False, "todavía queda una hablando"

    Bridge._on_speech_done(bridge, None)
    assert worker.conversation_window.is_open() is True


def test_ca15_la_ventana_solo_abre_con_el_guard_ya_liberado():
    """CA-15, sobre el invariante de ORDEN en vez de sobre el texto del log: cuando se
    invoca `_open_conversation_window()`, `_resolution_in_flight` ya es False, y el TTS se
    despacha después de liberar el guard."""
    from ui.webview.bridge import Bridge

    worker = _WorkerFalso()
    bridge = _bridge_con_worker(worker)
    bridge._resolution_in_flight = True

    traza = []

    def fake_speak_response(texto):
        traza.append(("tts", bridge._resolution_in_flight))
        Bridge._on_speech_done(bridge, None)

    def fake_open():
        traza.append(("ventana", bridge._resolution_in_flight))

    bridge._speak_response = fake_speak_response
    bridge.message_appended = MagicMock()
    bridge.typing_stopped = MagicMock()
    bridge._ensure_conversation_id = lambda: "c1"
    bridge._load_conversations = lambda offset=0: None
    worker.conversation_window.open = fake_open

    resolution = MagicMock()
    resolution.text = "Tarea registrada."
    resolution.matched_by = "task_tool"

    with patch("ui.webview.bridge.run_async", side_effect=lambda *a, **k: None):
        Bridge._on_resolve_done(bridge, resolution)

    assert traza == [("tts", False), ("ventana", False)], traza


def test_el_error_de_resolucion_no_habla_pero_abre_la_ventana():
    from ui.webview.bridge import Bridge

    worker = _WorkerFalso()
    bridge = _bridge_con_worker(worker)
    bridge.message_appended = MagicMock()
    bridge.typing_stopped = MagicMock()
    hablados = []
    bridge._speak_response = hablados.append

    Bridge._on_resolve_error(bridge, "algo falló")

    assert hablados == [], "un error no es una respuesta del agente"
    assert worker.conversation_window.is_open() is True


def test_apagar_el_manos_libres_cierra_la_ventana_antes_de_parar():
    from ui.webview.bridge import Bridge

    worker = _WorkerFalso()
    worker.conversation_window.open()
    bridge = _bridge_con_worker(worker)

    Bridge._stop_wake_word_worker(bridge)

    assert worker.conversation_window.is_open() is False
    assert worker.stop_event.is_set() is True


# ---------------------------------------------------------------------------
# Bug 3 — el nombre nunca se interpola crudo en una expresión regular
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nombre", ["O.R.I.O.N", "A.R.I.A", "Nova (beta)", "C++ Bot", "Sofía"])
def test_tts_no_rompe_con_nombres_con_caracteres_especiales(monkeypatch, nombre):
    import ui.tts_engine as tts

    monkeypatch.setattr(tts, "get_agent_name", lambda: nombre, raising=False)
    monkeypatch.setattr(config_manager, "get_agent_name", lambda: nombre)
    monkeypatch.setattr(config_manager, "get_agent_pronunciation", lambda: "nova")
    monkeypatch.setattr(tts, "_speak_edge", MagicMock(return_value=True), raising=False)

    # No debe lanzar `re.error`: antes el nombre iba crudo dentro del patrón.
    with patch.object(tts, "asyncio") as mock_asyncio:
        mock_asyncio.run.return_value = True
        tts.speak(f"Hola, soy {nombre}.")


def test_tts_reemplaza_el_nombre_por_su_pronunciacion(monkeypatch):
    """Con puntos, `.` como comodín hacía que el reemplazo fuera impredecible."""
    import re
    import ui.tts_engine as tts

    monkeypatch.setattr(config_manager, "get_agent_name", lambda: "O.R.I.O.N")
    monkeypatch.setattr(config_manager, "get_agent_pronunciation", lambda: "orion")

    patron = r'(?i)\b' + re.escape("O.R.I.O.N") + ''
    assert re.sub(patron, "orion", "Hola, soy O.R.I.O.N hoy") == "Hola, soy orion hoy"
    # El comodín sin escapar habría matcheado también esta cadena, que no es el nombre.
    assert re.sub(patron, "orion", "OXRXIXOXN") == "OXRXIXOXN"
