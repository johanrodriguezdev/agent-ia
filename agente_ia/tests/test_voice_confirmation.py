"""
tests/test_voice_confirmation.py
Pruebas de la confirmación hablada (`voice/voice_confirmation.py`).

Este módulo decide si una acción que exige permiso se ejecuta o no, escuchando por un
micrófono abierto en una habitación. El invariante es de una sola dirección: **solo una
palabra concreta autoriza; todo lo demás deniega.** Silencio, ruido, un "sí", una frase a
medias, un timeout o un fallo: todo eso tiene que denegar.

Ningún test usa micrófono ni espera en tiempo real (`.claude/rules/testing.md`).
"""

import threading

from unittest.mock import patch

import pytest

from voice import voice_confirmation as vc


@pytest.fixture
def canal():
    """Canal con timeout corto: los tests que esperan no deben tardar."""
    return vc.VoiceConfirmation(timeout_s=0.3)


# ── Qué autoriza y qué no ───────────────────────────────────────────

@pytest.mark.parametrize("dicho", [
    "confirmo",
    "Confirmo",
    "eh, confirmo",
    "confirmo señor",
    "sí confirmo",
    "confirmado",
])
def test_solo_la_palabra_acordada_autoriza(dicho):
    assert vc.evalua_respuesta(dicho) is True


@pytest.mark.parametrize("dicho", [
    "si",
    "sí",
    "claro",
    "vale",
    "de acuerdo",
    "adelante",
    "hazlo",
    "ok",
])
def test_un_si_no_basta(dicho):
    """Un "sí" aparece en cualquier conversación de fondo; "confirmo" no se dice solo."""
    assert vc.evalua_respuesta(dicho) is not True


@pytest.mark.parametrize("dicho", ["no", "cancela", "detente", "olvidalo", "cancelar"])
def test_el_rechazo_explicito_se_reconoce(dicho):
    assert vc.evalua_respuesta(dicho) is False


@pytest.mark.parametrize("dicho", ["", "   ", "mmm", "que hora es", "pon musica"])
def test_lo_que_no_decide_no_autoriza(dicho):
    assert vc.evalua_respuesta(dicho) is not True


# ── El canal entre hilos ────────────────────────────────────────────

def test_una_respuesta_afirmativa_autoriza(canal):
    def responder():
        while not canal.hay_pendiente():
            pass
        canal.responder("confirmo")

    hilo = threading.Thread(target=responder, daemon=True)
    hilo.start()

    assert canal.solicitar("close_app") is True
    hilo.join(timeout=2)


def test_el_silencio_deniega(canal):
    """Nadie responde: expira el plazo y la acción no se ejecuta."""
    assert canal.solicitar("close_app") is False


def test_una_respuesta_cualquiera_deniega(canal):
    def responder():
        while not canal.hay_pendiente():
            pass
        canal.responder("vale, dale")

    threading.Thread(target=responder, daemon=True).start()

    assert canal.solicitar("delete_file") is False


def test_la_respuesta_se_consume_una_sola_vez(canal):
    """Un "confirmo" no puede autorizar la acción siguiente."""
    def responder():
        while not canal.hay_pendiente():
            pass
        canal.responder("confirmo")

    threading.Thread(target=responder, daemon=True).start()
    assert canal.solicitar("close_app") is True

    # Segunda acción, sin que nadie diga nada: no hereda el permiso anterior.
    assert canal.solicitar("shutdown") is False


def test_no_se_admiten_dos_confirmaciones_a_la_vez(canal):
    """Dos preguntas habladas simultáneas no se podrían distinguir en la respuesta."""
    arrancada = threading.Event()
    resultado = {}

    def primera():
        arrancada.set()
        resultado["primera"] = canal.solicitar("close_app")

    threading.Thread(target=primera, daemon=True).start()
    arrancada.wait(timeout=1)
    while not canal.hay_pendiente():
        pass

    assert canal.solicitar("shutdown") is False    # la segunda se deniega en el acto


def test_cancelar_libera_al_que_esperaba(canal):
    resultado = {}

    def pedir():
        resultado["r"] = canal.solicitar("close_app")

    hilo = threading.Thread(target=pedir, daemon=True)
    hilo.start()
    while not canal.hay_pendiente():
        pass

    canal.cancelar()
    hilo.join(timeout=2)

    assert resultado["r"] is False
    assert canal.hay_pendiente() is False


def test_responder_sin_peticion_no_rompe(canal):
    assert canal.responder("confirmo") is False


def test_se_puede_saber_que_accion_se_esta_confirmando(canal):
    def responder():
        while not canal.hay_pendiente():
            pass
        assert canal.accion_pendiente() == "delete_folder"
        canal.responder("confirmo")

    threading.Thread(target=responder, daemon=True).start()

    assert canal.solicitar("delete_folder") is True


# ── El mensaje que se pronuncia ─────────────────────────────────────

def test_la_pregunta_dice_que_se_va_a_hacer():
    """Una confirmación a ciegas ("¿confirma?") no es una confirmación."""
    hablado = vc.mensaje_hablado("close_app", "Voy a cerrar Chrome")

    assert "cerrar Chrome" in hablado
    assert "confirmo" in hablado.lower()


def test_sin_mensaje_al_menos_se_nombra_la_accion():
    hablado = vc.mensaje_hablado("shutdown", "")

    assert "shutdown" in hablado
    assert "confirmo" in hablado.lower()


# ── Fijación de la palabra acordada ─────────────────────────────────

def test_la_palabra_de_confirmacion_esta_fijada():
    """Cambiarla altera qué autoriza una acción de riesgo: no debe moverse sin querer."""
    assert "confirmo" in vc.PALABRAS_DE_CONFIRMACION
    assert "si" not in vc.PALABRAS_DE_CONFIRMACION
    assert "ok" not in vc.PALABRAS_DE_CONFIRMACION


# ─────────────────────────────────────────────
#  El agente no puede contestarse a sí mismo
#
#  De una sesión real (logs/orion.log, 2026-09-04 22:18:47 y 22:20:48): el agente pedía
#  permiso EN VOZ ALTA, el micrófono lo oía por los altavoces, y esa frase entraba como la
#  respuesta del usuario. Al no ser un "confirmo", contaba como rechazo antes de que el
#  humano dijera nada. Desde fuera se vive como "se la confirmé y dice que no confirmé".
# ─────────────────────────────────────────────

#: La pregunta que el agente pronuncia, con la forma real de `mensaje_hablado()`.
_LA_PREGUNTA = (
    "Estas seguro de que quieres ejecutar kit para pausar la musica de youtube. "
    "Diga confirmo para ejecutar o cualquier otra cosa para cancelar"
)

#: Trozos de esa pregunta tal como los transcribió el reconocedor en la sesión real.
_SU_PROPIA_VOZ = [
    "Estas seguro de que quieres ejecutar kit",
    "o cualquier otra cosa para cancelar si e",
]

#: Lo que dice el humano.
_LA_RESPUESTA = ["confirmo", "eh confirmo", "confirmado", "no", "cancela"]


def _oido_mientras_pregunta(texto):
    from voice.wake_word import _es_su_propia_pregunta

    with patch("ui.tts_engine.is_speaking", return_value=True), \
         patch("ui.tts_engine.current_speech_text", return_value=_LA_PREGUNTA):
        return _es_su_propia_pregunta(texto)


@pytest.mark.parametrize("captado", _SU_PROPIA_VOZ)
def test_el_agente_no_toma_su_pregunta_como_respuesta(captado):
    assert _oido_mientras_pregunta(captado) is True, captado


@pytest.mark.parametrize("respuesta", _LA_RESPUESTA)
def test_la_respuesta_del_humano_siempre_pasa(respuesta):
    """La mitad que casi se rompe al arreglar la otra.

    La pregunta dice "diga CONFIRMO para ejecutar", así que un "confirmo" a secas está
    contenido en ella palabra por palabra: con la comparación de eco tal cual, el filtro
    contra el agente terminaba descartando justo la respuesta del humano. Por eso el
    vocabulario de respuesta se quita de las dos partes antes de comparar.
    """
    assert _oido_mientras_pregunta(respuesta) is False, respuesta


def test_sin_locucion_no_hay_eco_que_descartar():
    from voice.wake_word import _es_su_propia_pregunta

    with patch("ui.tts_engine.current_speech_text", return_value=""):
        assert _es_su_propia_pregunta("lo que sea") is False

def test_la_captura_que_empezo_durante_la_pregunta_no_cuenta():
    """El segundo candado, independiente del contenido.

    `_confirmar_hablando()` ya pronuncia la pregunta ANTES de abrir la escucha para no
    oírse a sí mismo. No alcanzaba: el micrófono captura de forma continua, así que el
    trozo que empezó mientras el agente hablaba termina —y se transcribe— después de
    abrirse, y entraba como la respuesta del usuario.
    """
    import time

    from voice.voice_confirmation import VoiceConfirmation

    vc_local = VoiceConfirmation(timeout_s=0.5)
    antes = time.monotonic()
    # Separación real entre los dos instantes: sin ella, el reloj monótono devuelve el
    # mismo valor para "cuando el agente empezó a hablar" y "cuando abrió la escucha", y el
    # test pasaría o fallaría según la resolución del reloj de la máquina.
    time.sleep(0.02)

    hilo = threading.Thread(target=vc_local.solicitar, args=("pc_key",))
    hilo.start()
    while not vc_local.hay_pendiente() and hilo.is_alive():
        time.sleep(0.001)

    if vc_local.hay_pendiente():
        assert vc_local.acepta(antes) is False, "una captura anterior no puede responder"
        assert vc_local.acepta(time.monotonic()) is True, "una posterior sí"
    hilo.join(timeout=2)


def test_sin_peticion_no_se_acepta_nada():
    from voice.voice_confirmation import VoiceConfirmation

    import time

    assert VoiceConfirmation().acepta(time.monotonic()) is False
