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
