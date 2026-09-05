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


def test_sin_mensaje_al_menos_se_dice_que_se_va_a_hacer():
    """Se mantiene la intención —una confirmación a ciegas no es una confirmación— y
    cambia el idioma: antes se pronunciaba el nombre interno ("shutdown"), ahora se dice
    qué hace. El nombre de la función no le dice nada a quien tiene que autorizarla."""
    hablado = vc.mensaje_hablado("shutdown", "")

    assert "apague el computador" in hablado
    assert "shutdown" not in hablado
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


# ─────────────────────────────────────────────
#  La pregunta de autorización, en español y no en nombres de función
# ─────────────────────────────────────────────

@pytest.mark.parametrize("accion,detalle,esperado", [
    ("terminal_run_command", "dispatch:terminal_run_command | command=git status",
     "ejecute un comando en la terminal"),
    ("pc_key", "webview:pc_key | name=space", "pulse una tecla"),
    ("CLOSE_APP", "dispatch:CLOSE_APP | app_name=chrome", "cierre una aplicación"),
    ("delete_conversation", "webview:delete_conversation | name=Certificados",
     "borre una conversación"),
])
def test_la_pregunta_no_dice_nombres_de_funcion(accion, detalle, esperado):
    """Antes preguntaba "¿Estás seguro de que quieres ejecutar 'terminal_run_command'?", y
    por voz `pc_key` sonaba "ejecutar kit". Pedirle permiso a alguien en un idioma que no
    habla no es pedirle permiso: o dice que sí a ciegas, o dice que no por las dudas."""
    from core.acciones_legibles import pregunta

    texto = pregunta(accion, detalle)
    assert esperado in texto
    assert accion not in texto, f"la pregunta todavía nombra la función: {texto}"


def test_la_pregunta_conserva_el_dato_concreto():
    """Lo que se simplifica es el envoltorio, NUNCA el detalle: autorizar "ejecute un
    comando" sin ver cuál es autorizar a ciegas."""
    from core.acciones_legibles import pregunta

    texto = pregunta("terminal_run_command",
                     "dispatch:terminal_run_command | command=rm -rf /tmp/x")
    assert "rm -rf /tmp/x" in texto


def test_el_prefijo_de_trazabilidad_no_se_le_muestra_al_humano():
    """`dispatch:CLOSE_APP` identifica el camino de invocación y va a la auditoría; al
    humano que autoriza no le dice nada."""
    from core.acciones_legibles import pregunta

    texto = pregunta("CLOSE_APP", "dispatch:CLOSE_APP | app_name=chrome")
    assert "dispatch:" not in texto
    assert "app_name=" not in texto
    assert "chrome" in texto


def test_una_accion_sin_traduccion_sigue_siendo_legible():
    """No hace falta que el diccionario esté completo para que la pregunta se entienda."""
    from core.acciones_legibles import describir

    assert describir("una_accion_nueva_cualquiera") == "ejecute una accion nueva cualquiera"
    assert describir("") == "ejecute una acción"


def test_todas_las_acciones_que_piden_permiso_tienen_traduccion():
    """Red de regresión: una acción amarilla o roja sin descripción escrita a mano cae en
    la derivada, que se entiende pero se lee peor. Esta prueba avisa al agregar una."""
    from agents.skill_tools import (register_dispatcher_tool, register_family_tools,
                                    register_skill_tools)
    from agents.user_defined_tools import register_user_defined_tools
    from core.acciones_legibles import _DESCRIPCIONES
    from core.security_manager import RiskLevel, security_manager
    from skills.skill_manager import skill_manager

    register_dispatcher_tool()
    register_skill_tools(skill_manager)
    register_family_tools(skill_manager)
    register_user_defined_tools()

    piden_permiso = {
        accion for accion, nivel in security_manager._actions.items()
        if nivel in (RiskLevel.YELLOW, RiskLevel.RED)
    }

    # `security_manager` es un singleton de proceso, así que otros tests le registran sus
    # propias acciones inventadas ("algo_denegado") y quedan ahí para el resto de la
    # sesión. Se filtran quedándose solo con las que ALGÚN módulo de producción nombra:
    # una acción de test no aparece fuera de `tests/`.
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    fuentes = "\n".join(
        f.read_text(encoding="utf-8", errors="replace")
        for f in raiz.rglob("*.py")
        if "tests" not in f.parts and "openclaw-main" not in f.parts
    )
    de_produccion = {
        a for a in piden_permiso if f'"{a}"' in fuentes or f"'{a}'" in fuentes
    }
    sin_traducir = sorted(de_produccion - set(_DESCRIPCIONES))
    assert not sin_traducir, (
        f"estas acciones le piden permiso al humano y no tienen una descripción en "
        f"español: {sin_traducir}"
    )

def test_el_turno_completo_de_una_confirmacion_hablada():
    """El recorrido entero, en el orden en que pasa de verdad.

    1. El agente pronuncia la pregunta y el micrófono lo oye por los altavoces.
    2. Esa captura empezó ANTES de abrirse la escucha -> el candado temporal la descarta.
    3. Llega otra captura, ya dentro de la escucha, pero sigue siendo su propia voz ->
       la descarta el candado de contenido.
    4. El humano dice "confirmo" -> se acepta.

    Los tres pasos importan por separado, y hasta anoche fallaban los tres: la primera
    frase que llegara —fuese de quien fuese— se tomaba como la respuesta, y como no era un
    "confirmo", contaba como rechazo antes de que el humano abriera la boca.
    """
    import threading
    import time

    from voice.voice_confirmation import VoiceConfirmation

    pregunta = ("Estas seguro de que quieres ejecutar kit para pausar la musica de "
                "youtube. Diga confirmo para ejecutar o cualquier otra cosa para cancelar")
    vc_local = VoiceConfirmation(timeout_s=3)

    empezo_mientras_hablaba = time.monotonic()
    time.sleep(0.02)

    veredicto = {}
    hilo = threading.Thread(
        target=lambda: veredicto.setdefault("ok", vc_local.solicitar("pc_key"))
    )
    hilo.start()
    while not vc_local.hay_pendiente() and hilo.is_alive():
        time.sleep(0.001)

    with patch("ui.tts_engine.is_speaking", return_value=True),          patch("ui.tts_engine.current_speech_text", return_value=pregunta):
        from voice.wake_word import _es_su_propia_pregunta

        # (2) el eco que empezó antes de abrirse la escucha
        assert vc_local.acepta(empezo_mientras_hablaba) is False

        # (3) su propia voz, ya dentro de la escucha
        eco = "o cualquier otra cosa para cancelar si e"
        assert vc_local.acepta(time.monotonic()) is True, "el candado temporal la dejaría pasar"
        assert _es_su_propia_pregunta(eco) is True, "y el de contenido la tiene que frenar"

        # (4) el humano
        assert _es_su_propia_pregunta("confirmo") is False
        vc_local.responder("confirmo")

    hilo.join(timeout=3)
    assert veredicto.get("ok") is True, "el 'confirmo' del humano tenía que autorizar"

def test_la_auditoria_conserva_el_nombre_tecnico():
    """Lo que se simplificó es lo que LEE EL HUMANO, no lo que queda registrado.

    El log de auditoría existe para poder reconstruir después qué se ejecutó, y ahí
    "cierre una aplicación" no sirve: hace falta `close_app` y el prefijo del camino de
    invocación. Si esta separación se pierde, se gana claridad en la pregunta y se pierde
    trazabilidad — un mal negocio.
    """
    from unittest.mock import patch as _patch

    from core.security_manager import ChannelType, security_manager

    vistos = []
    with _patch.object(security_manager, "_log_audit",
                       lambda accion, canal, res, uid, det: vistos.append((accion, det))),          _patch("core.confirmation.get_confirmation_adapter",
                return_value=lambda accion, mensaje: True):
        security_manager.require_confirmation(
            "close_app", ChannelType.DESKTOP,
            details="dispatch:CLOSE_APP | app_name=chrome",
        )

    assert vistos, "no se auditó la confirmación"
    accion, detalle = vistos[-1]
    assert accion == "close_app"
    assert "dispatch:CLOSE_APP" in detalle, "el prefijo de trazabilidad tiene que quedar"
    assert "app_name=chrome" in detalle
