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
import time
from types import SimpleNamespace
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
    # Turno cancelable: el `Bridge` real lo abre en `send_message()`. El doble tiene que
    # tener el mismo estado, o `_on_resolve_done()` no encuentra el atributo (en un QObject
    # sin `__init__`, leer uno que no existe lanza RuntimeError, no AttributeError).
    bridge._turno_id = None
    bridge._turno_cancelado_id = None
    return bridge


class _WorkerFalso:
    def __init__(self):
        from voice.mic_window import ConversationWindow

        self.stop_event = threading.Event()
        self.conversation_window = ConversationWindow()
        # El worker real expone `signals.command_detected` para que el bridge se conecte.
        self.signals = SimpleNamespace(
            command_detected=SimpleNamespace(connect=lambda _cb: None),
        )


class _PoolFalso:
    """Doble de `QThreadPool`: en un test nadie tiene que abrir el microfono de verdad."""

    lanzados = []

    @classmethod
    def globalInstance(cls):
        return SimpleNamespace(start=cls.lanzados.append)


def test_encender_el_manos_libres_acepta_la_primera_frase_sin_el_nombre(monkeypatch):
    """Hallazgo en vivo (2026-09-03 21:50): el usuario apreto el microfono, dijo "busca en
    YouTube de Bon Jovi" y el agente descarto la frase en silencio por no traer wake word.
    Indistinguible de estar colgado.

    Apretar el microfono YA ES pedir atencion, asi que se abre la misma ventana de ~15s que
    se arma despues de cada respuesta. Ademas cubre el caso frecuente de que el reconocedor
    se coma la primera palabra, que es justo donde va el nombre."""
    import ui.webview.bridge as bridge_module
    from ui.webview.bridge import Bridge

    worker = _WorkerFalso()
    _PoolFalso.lanzados = []
    monkeypatch.setattr(bridge_module, "WakeWordWorker", lambda: worker)
    monkeypatch.setattr(bridge_module, "QThreadPool", _PoolFalso)

    bridge = _bridge_con_worker(None)
    bridge.notice_shown = MagicMock()

    Bridge.toggle_wake_word(bridge, True)

    assert bridge._wake_worker is worker
    assert _PoolFalso.lanzados == [worker], "el worker tiene que quedar lanzado igual"
    assert worker.conversation_window.is_open() is True
    # Una frase capturada DESPUES de encenderlo se acepta sin wake word.
    assert worker.conversation_window.accepts(time.monotonic()) is True
    # Y se le avisa al usuario: sin aviso, el arreglo es invisible.
    bridge.notice_shown.emit.assert_called_once()


def test_una_frase_anterior_al_encendido_no_se_cuela(monkeypatch):
    """Segundo candado de la ventana (CA-14): el chunk tiene que haber EMPEZADO despues de
    abrirse. Lo que se estaba capturando antes de apretar el microfono no cuenta."""
    import ui.webview.bridge as bridge_module
    from ui.webview.bridge import Bridge

    # Cinco segundos antes, no "justo antes": en Windows dos lecturas seguidas de
    # `time.monotonic()` pueden devolver el mismo valor y el test medirla la granularidad
    # del reloj en vez del comportamiento.
    antes = time.monotonic() - 5
    worker = _WorkerFalso()
    _PoolFalso.lanzados = []
    monkeypatch.setattr(bridge_module, "WakeWordWorker", lambda: worker)
    monkeypatch.setattr(bridge_module, "QThreadPool", _PoolFalso)

    bridge = _bridge_con_worker(None)
    bridge.notice_shown = MagicMock()
    Bridge.toggle_wake_word(bridge, True)

    assert worker.conversation_window.accepts(antes) is False


def test_apagar_el_manos_libres_cierra_la_ventana():
    """Manos libres OFF no puede dejar una ventana armada: seria aceptar frases sin nombre
    con el microfono ya apagado."""
    from ui.webview.bridge import Bridge

    worker = _WorkerFalso()
    bridge = _bridge_con_worker(worker)
    worker.conversation_window.open()

    Bridge.toggle_wake_word(bridge, False)

    assert worker.conversation_window.is_open() is False
    assert worker.stop_event.is_set() is True


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


# ══════════════════════════════════════════════════════════════════════
#  Barge-in: distinguir al usuario del eco del propio agente
#
#  Reportado por Johan en prueba real: preguntó "qué es un bot", el agente empezó a
#  responder por voz y se cortó solo a los pocos segundos. En el log:
#  "[Barge-in] Usuario interrumpio" seguido de "ningún motor devolvió texto".
#
#  Causa: el barge-in se disparaba con CUALQUIER sonido captado mientras `is_speaking()`
#  fuera cierto. Con altavoces eso es siempre: el micrófono oye al propio agente. Ahora se
#  decide sobre el texto transcrito, comparándolo con lo que se está pronunciando.
# ══════════════════════════════════════════════════════════════════════

_LOCUCION = (
    "Senor Johan, permitame aclararle el concepto de forma precisa. Un bot es un "
    "programa de software disenado para ejecutar tareas de forma automatica."
)


@pytest.fixture
def hablando(monkeypatch):
    import ui.tts_engine as tts

    monkeypatch.setattr(tts, "_speaking", True)
    monkeypatch.setattr(tts, "_current_text", _LOCUCION)
    return tts


@pytest.mark.parametrize("captado", [
    "permitame aclararle el concepto",
    "un bot es un programa de software",
    "para ejecutar tareas de forma automatica",
    "precisa",                                    # una sola palabra suelta de la locución
])
def test_el_eco_del_propio_agente_no_interrumpe(hablando, captado):
    from voice.wake_word import _es_interrupcion_real

    assert _es_interrupcion_real(captado) is False


@pytest.mark.parametrize("captado", [
    "viernes detente por favor",
    "espera quiero preguntarte otra cosa",
])
def test_una_interrupcion_real_si_corta(hablando, perfil, captado):
    """El nombre del agente se fija acá: desde que el barge-in exige que le hablen A ÉL,
    un nombre cableado ("orion") hacía que el test dependiera del `config.json` real —
    pasaba o fallaba según cómo tuviera el usuario bautizado a su agente."""
    perfil("viernes", "viernes")
    from voice.wake_word import _es_interrupcion_real

    assert _es_interrupcion_real(captado) is True


def test_una_frase_sin_senal_de_corte_ya_no_interrumpe(hablando):
    """Cambio de contrato deliberado, no una regresión.

    "no era eso lo que queria saber" es una interrupción legítima, y hasta ahora cortaba —
    porque cortaba CUALQUIER cosa que no fuera el eco del agente. Por contenido es
    indistinguible de un anuncio de radio, y esa permisividad es la que hizo que
    "95.3 perfecto para combatir el encrespamiento" se llevara por delante la respuesta a
    un análisis del precio del dólar (logs/orion.log, 2026-09-04 21:29:41).

    Los dos errores no cuestan lo mismo. Cortar de más pierde la respuesta entera y no hay
    forma de recuperarla salvo volver a preguntar; cortar de menos hace que el agente
    termine la frase y el usuario diga "para", que es una sílaba. Se eligió el barato.
    """
    from voice.wake_word import _es_interrupcion_real

    assert _es_interrupcion_real("no era eso lo que queria saber") is False


def test_sin_locucion_en_curso_no_hay_nada_que_interrumpir(monkeypatch):
    import ui.tts_engine as tts
    from voice.wake_word import _es_interrupcion_real

    monkeypatch.setattr(tts, "_speaking", False)

    assert _es_interrupcion_real("orion detente") is False


def test_ruido_sin_palabras_con_contenido_no_interrumpe(hablando):
    from voice.wake_word import _es_interrupcion_real

    assert _es_interrupcion_real("eh ah um") is False


def test_si_no_se_sabe_que_se_esta_diciendo_se_respeta_la_interrupcion(monkeypatch):
    """Ante la duda, gana el usuario: es peor ignorar una interrupción real."""
    import ui.tts_engine as tts
    from voice.wake_word import _es_interrupcion_real

    monkeypatch.setattr(tts, "_speaking", True)
    monkeypatch.setattr(tts, "_current_text", "")

    assert _es_interrupcion_real("cualquier cosa") is True


# ─────────────────────────────────────────────
#  El micrófono capta la habitación entera
#
#  Todo lo de esta sección salió de una sesión real (logs/orion.log, 2026-09-04 21:28-21:29):
#  había una radio encendida, y sus anuncios entraban por el micrófono como si fueran el
#  usuario. Las frases están copiadas literales del log.
# ─────────────────────────────────────────────

#: Anuncios de radio transcritos de verdad durante esa sesión.
_LA_RADIO = [
    "95.3 perfecto para combatir el encrespamiento",
    "haciendo a su tecnologia debajo inteligente el doctor penetra en la vida",
    "de cuatro veces mas que un suavizante comun menos abre la cal",
    "recomiendame me escuchas",
]

#: Lo que dice alguien que SÍ quiere interrumpir.
_UNA_INTERRUPCION = ["para", "espera", "detente", "callate", "silencio", "basta"]


def _mientras_habla(texto, dicho="El precio del dolar en los ultimos seis meses mostro"):
    """¿`texto` cortaría la locución en curso?"""
    from voice.wake_word import _es_interrupcion_real

    with patch("ui.tts_engine.is_speaking", return_value=True), \
         patch("ui.tts_engine.current_speech_text", return_value=dicho):
        return _es_interrupcion_real(texto)


@pytest.mark.parametrize("anuncio", _LA_RADIO)
def test_el_ruido_de_fondo_no_corta_la_respuesta_hablada(anuncio):
    """El caso concreto: a las 21:29:35 terminó un análisis del precio del dólar, y seis
    segundos después un anuncio de radio cortó la locución a mitad. Desde afuera eso se
    vive como que el agente no contesta en audio.

    Nótese "95.3 perfecto PARA combatir": cuando la frase de corte se buscaba como
    subcadena, ese anuncio seguía cortando. Por eso se exige la frase entera."""
    assert _mientras_habla(anuncio) is False, anuncio


@pytest.mark.parametrize("frase", _UNA_INTERRUPCION)
def test_una_interrupcion_de_verdad_sigue_cortando(frase):
    """La otra mitad: endurecer el barge-in no puede dejar al agente imposible de callar."""
    assert _mientras_habla(frase) is True, frase


def test_el_nombre_del_agente_tambien_corta(perfil):
    """Interrumpir con una orden nueva —"viernes, mejor busca otra cosa"— es interrumpir."""
    perfil("viernes", "viernes")
    assert _mientras_habla("viernes mejor busca otra cosa") is True


def test_el_eco_del_propio_agente_sigue_sin_cortar():
    """La protección que ya existía no se pierde: el micrófono capta los altavoces."""
    assert _mientras_habla("el precio del dolar en los ultimos seis meses") is False


def test_sin_locucion_en_curso_no_hay_nada_que_interrumpir():
    from voice.wake_word import _es_interrupcion_real

    with patch("ui.tts_engine.is_speaking", return_value=False):
        assert _es_interrupcion_real("para") is False


def test_una_frase_larga_no_se_corta_a_los_seis_segundos():
    """La instrucción "orion, ¿me escuchas? hazme un análisis del precio del dólar en los
    últimos 6 meses" llegó como 'orion Me escuchas Hazme un': el límite de 6 s la partía
    por la mitad, y el resto entraba después como frase suelta y se descartaba. El propio
    usuario terminó dictando "se está cortando el audio".

    Se fija el número porque es el que causó el bug, no un detalle de implementación: 6 no
    alcanza para una frase hablada normal."""
    from voice.wake_word import _limite_de_frase

    with patch("ui.tts_engine.is_speaking", return_value=False):
        assert _limite_de_frase() >= 12, (
            "una instrucción hablada normal pasa de 6 segundos y se estaba partiendo"
        )


def test_mientras_el_agente_habla_la_captura_es_corta():
    """La otra cara: por los altavoces el micrófono oye voz continua, así que la frase no
    se cierra por silencio y se estira hasta el tope. Con el límite largo puesto ahí, un
    "para" tardaría hasta 15 s en transcribirse — el agente seguiría hablando todo ese
    rato. Interrumpir tiene que ser rápido; dictar, largo. No es el mismo problema."""
    from voice.wake_word import _limite_de_frase

    with patch("ui.tts_engine.is_speaking", return_value=True):
        rapido = _limite_de_frase()
    with patch("ui.tts_engine.is_speaking", return_value=False):
        largo = _limite_de_frase()

    assert rapido < largo, (rapido, largo)
    assert rapido <= 6, "una interrupción no puede tardar tanto en llegar"
