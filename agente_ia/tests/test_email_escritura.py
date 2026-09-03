"""
tests/test_email_escritura.py
Capacidades de ESCRITURA sobre el correo: enviar y marcar como leído.

Lo que protege esta suite: **que estas dos funciones existan sin debilitar nada**. Son las
únicas cosas que O.R.I.O.N. escribe sobre una cuenta ajena al propio PC, y dependen de dos
permisos independientes que tienen que dar los dos:

- El **interruptor** de `core/email_capabilities.py`, apagado de fábrica, que el usuario
  enciende desde "Configuración".
- El **nivel de riesgo**, que el interruptor no toca: enviar sigue siendo ROJO (PIN maestro
  en escritorio, bloqueado en remoto) y marcar como leído sigue siendo amarillo.

Ningún test manda un correo de verdad ni se conecta a un servidor.
"""

import email.message
import email.policy
import json

import pytest

from core import email_capabilities, email_sender
from core.security_manager import ChannelType, RiskLevel, security_manager


@pytest.fixture(autouse=True)
def _capacidades_en_temporal(monkeypatch, tmp_path):
    """Nunca escribir el email_capabilities.json real."""
    monkeypatch.setattr(
        email_capabilities, "CAPABILITIES_FILE", str(tmp_path / "email_capabilities.json"),
    )


# ── Los dos permisos son independientes ─────────────────────────────

def test_enviar_correo_sigue_siendo_rojo():
    """Lo dice .claude/rules/security-levels.md. El interruptor no lo cambia."""
    assert security_manager.classify_action("SEND_EMAIL") == RiskLevel.RED
    assert security_manager.classify_action("send_email_as_user") == RiskLevel.RED


def test_no_se_puede_bajar_el_nivel_de_enviar_correo():
    """Aunque alguien lo intentara desde código nuevo, `register_action` lo bloquea."""
    assert security_manager.register_action("SEND_EMAIL", RiskLevel.YELLOW) is False
    assert security_manager.classify_action("SEND_EMAIL") == RiskLevel.RED


def test_enviar_esta_bloqueado_desde_los_canales_remotos():
    for canal in (ChannelType.TELEGRAM, ChannelType.DISCORD, ChannelType.VOICE,
                  ChannelType.EMAIL):
        assert not security_manager.require_confirmation("SEND_EMAIL", canal), canal


def test_marcar_leido_es_amarillo():
    assert security_manager.classify_action("MARK_EMAIL_READ") == RiskLevel.YELLOW


def test_encender_el_interruptor_no_cambia_el_nivel():
    """La prueba de que son cosas distintas: activar la capacidad no toca el riesgo."""
    email_capabilities.activar("send", True)

    assert security_manager.classify_action("SEND_EMAIL") == RiskLevel.RED


# ── El interruptor ──────────────────────────────────────────────────

def test_de_fabrica_todo_viene_apagado():
    assert email_capabilities.cargar() == {"send": False, "mark_read": False}
    assert not email_capabilities.esta_activa("send")


def test_se_puede_encender_y_apagar():
    assert email_capabilities.activar("send", True) is True
    assert email_capabilities.esta_activa("send")

    assert email_capabilities.activar("send", False) is True
    assert not email_capabilities.esta_activa("send")


def test_encender_una_no_enciende_la_otra():
    email_capabilities.activar("send", True)

    assert not email_capabilities.esta_activa("mark_read")


def test_un_archivo_corrupto_apaga_todo():
    """Fail-closed en la dirección correcta: ante la duda, no poder escribir."""
    with open(email_capabilities.CAPABILITIES_FILE, "w", encoding="utf-8") as f:
        f.write("{roto")

    assert email_capabilities.cargar() == {"send": False, "mark_read": False}


def test_un_json_que_no_es_objeto_apaga_todo():
    with open(email_capabilities.CAPABILITIES_FILE, "w", encoding="utf-8") as f:
        json.dump(["send"], f)

    assert not email_capabilities.esta_activa("send")


def test_un_valor_que_no_es_booleano_no_enciende_nada():
    """Un "true" string o un 1 no alcanzan: solo un booleano de verdad."""
    with open(email_capabilities.CAPABILITIES_FILE, "w", encoding="utf-8") as f:
        json.dump({"send": "true", "mark_read": 1}, f)

    assert email_capabilities.cargar() == {"send": False, "mark_read": False}


def test_no_se_pueden_inventar_capacidades():
    """La UI no puede crear una capacidad nueva mandando un id que el código no implementa."""
    assert email_capabilities.activar("borrar_todo", True) is False

    with open(email_capabilities.CAPABILITIES_FILE, "w", encoding="utf-8") as f:
        json.dump({"borrar_todo": True}, f)

    assert "borrar_todo" not in email_capabilities.cargar()


def test_las_filas_para_la_ui_traen_su_estado():
    email_capabilities.activar("mark_read", True)

    filas = {f["id"]: f for f in email_capabilities.filas_para_ui()}

    assert filas["mark_read"]["enabled"] is True
    assert filas["send"]["enabled"] is False
    assert filas["send"]["label"] and filas["send"]["description"]


# ── Envío ───────────────────────────────────────────────────────────

_SMTP = {"smtp": {"host": "smtp.x.com", "port": 587, "user": "yo@x.com",
                  "password": "clave", "from_name": "Soporte"}}


def test_sin_bloque_smtp_no_se_puede_enviar():
    """No se adivinan credenciales desde IMAP: adivinar mal es filtrar una contraseña."""
    with pytest.raises(email_sender.EnvioError, match="no tiene bloque 'smtp'"):
        email_sender.enviar({}, "a@b.com", "hola", "texto")


def test_una_direccion_invalida_se_rechaza():
    with pytest.raises(email_sender.EnvioError, match="no parece una dirección"):
        email_sender.enviar(_SMTP, "esto no es un correo", "hola", "texto")


def test_no_se_envia_con_el_cuerpo_vacio():
    with pytest.raises(email_sender.EnvioError, match="cuerpo"):
        email_sender.enviar(_SMTP, "a@b.com", "hola", "   ")


def test_hay_un_tope_de_destinatarios():
    """Un agente no puede volverse un emisor masivo por un malentendido."""
    muchos = ", ".join(f"d{i}@x.com" for i in range(email_sender.MAX_DESTINATARIOS + 1))

    with pytest.raises(email_sender.EnvioError, match="tope"):
        email_sender.enviar(_SMTP, muchos, "hola", "texto")


def test_los_destinatarios_repetidos_cuentan_una_vez():
    assert email_sender._normalizar_destinatarios("a@b.com, a@b.com") == ["a@b.com"]


def test_se_acepta_el_formato_con_nombre():
    assert email_sender._normalizar_destinatarios("Ana <ana@x.com>") == ["ana@x.com"]


def test_el_envio_llega_al_servidor_smtp(monkeypatch):
    enviados = []

    class _ServidorFalso:
        def __init__(self, host, port, timeout=None):
            enviados.append(("conectado", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            enviados.append(("starttls",))

        def login(self, usuario, clave):
            enviados.append(("login", usuario))

        def send_message(self, mensaje):
            enviados.append(("enviado", mensaje))

    monkeypatch.setattr(email_sender.smtplib, "SMTP", _ServidorFalso)

    resumen = email_sender.enviar(_SMTP, "a@b.com", "Asunto", "El cuerpo")

    assert "a@b.com" in resumen
    mensaje = [e[1] for e in enviados if e[0] == "enviado"][0]
    assert mensaje["To"] == "a@b.com"
    assert mensaje["Subject"] == "Asunto"
    assert "Soporte" in mensaje["From"]
    assert ("starttls",) in enviados


def test_el_puerto_465_usa_ssl_directo(monkeypatch):
    usados = []
    monkeypatch.setattr(
        email_sender.smtplib, "SMTP",
        lambda *a, **k: pytest.fail("con 465 no debería usarse SMTP en claro"),
    )

    class _SSLFalso:
        def __init__(self, host, port, timeout=None, context=None):
            usados.append(port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, c):
            pass

        def send_message(self, m):
            pass

    monkeypatch.setattr(email_sender.smtplib, "SMTP_SSL", _SSLFalso)
    config = {"smtp": dict(_SMTP["smtp"], port=465)}

    email_sender.enviar(config, "a@b.com", "x", "y")

    assert usados == [465]


# ── Respuesta en el mismo hilo ──────────────────────────────────────

def _original():
    mensaje = email.message.EmailMessage()
    mensaje["From"] = "Ana <ana@empresa.com>"
    mensaje["Subject"] = "Problema con la factura"
    mensaje["Message-ID"] = "<abc123@empresa.com>"
    mensaje["References"] = "<anterior@empresa.com>"
    mensaje.set_content("no me llega")
    return email.message_from_bytes(mensaje.as_bytes(), policy=email.policy.default)


def test_de_un_correo_leido_se_saca_a_quien_responder():
    datos = email_sender.datos_para_responder(_original())

    assert datos["destinatario"] == "ana@empresa.com"
    assert datos["message_id"] == "<abc123@empresa.com>"
    assert datos["asunto"] == "Re: Problema con la factura"


def test_no_se_duplica_el_re_del_asunto():
    mensaje = email.message.EmailMessage()
    mensaje["From"] = "a@b.com"
    mensaje["Subject"] = "Re: ya respondido"
    mensaje.set_content("x")

    datos = email_sender.datos_para_responder(
        email.message_from_bytes(mensaje.as_bytes(), policy=email.policy.default),
    )

    assert datos["asunto"] == "Re: ya respondido"


def test_la_respuesta_va_en_el_hilo_original(monkeypatch):
    """Sin In-Reply-To y References, para quien recibe es un hilo nuevo — inservible en soporte."""
    capturado = {}

    class _ServidorFalso:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            pass

        def login(self, u, c):
            pass

        def send_message(self, mensaje):
            capturado["mensaje"] = mensaje

    monkeypatch.setattr(email_sender.smtplib, "SMTP", _ServidorFalso)
    datos = email_sender.datos_para_responder(_original())

    email_sender.enviar(_SMTP, datos["destinatario"], datos["asunto"], "ya lo vemos", datos)

    mensaje = capturado["mensaje"]
    assert mensaje["In-Reply-To"] == "<abc123@empresa.com>"
    assert "<anterior@empresa.com>" in mensaje["References"]
    assert "<abc123@empresa.com>" in mensaje["References"]


# ── La skill respeta el interruptor ─────────────────────────────────

def test_con_el_envio_apagado_la_skill_explica_como_activarlo():
    from skills.email_skill import EmailSkill

    salida = EmailSkill().execute("SEND_EMAIL", {"cuerpo": "hola", "destinatario": "a@b.com"})

    assert "Configuración" in salida
    assert "desactivado" in salida.lower()


def test_con_marcar_leido_apagado_tampoco_se_marca(monkeypatch):
    from core import email_reader
    from skills.email_skill import EmailSkill

    def _no_llamar(*a, **k):
        raise AssertionError("no debería tocar el buzón con la capacidad apagada")

    monkeypatch.setattr(email_reader, "marcar_leido", _no_llamar)

    salida = EmailSkill().execute("MARK_EMAIL_READ", {})

    assert "desactivado" in salida.lower()


def test_sin_cuerpo_no_se_manda_nada():
    from skills.email_skill import EmailSkill

    email_capabilities.activar("send", True)

    salida = EmailSkill().execute("SEND_EMAIL", {"destinatario": "a@b.com", "cuerpo": ""})

    assert "No entendí qué querés que diga" in salida


def test_sin_destinatario_ni_correo_previo_no_se_inventa_uno(monkeypatch):
    from core import email_reader
    from skills.email_skill import EmailSkill

    email_capabilities.activar("send", True)
    monkeypatch.setattr(email_reader, "ultimos_correos", lambda: [])

    salida = EmailSkill().execute("SEND_EMAIL", {"cuerpo": "hola", "destinatario": ""})

    assert "No sé a quién escribirle" in salida


# ── Extracción de la frase ──────────────────────────────────────────

def test_se_extrae_destinatario_asunto_y_cuerpo():
    from skills.email_skill import EmailSkill

    params = EmailSkill().extract_params(
        "SEND_EMAIL",
        "manda un correo a ana@empresa.com con asunto Reunion diciendo que confirmo",
    )

    assert params["destinatario"] == "ana@empresa.com"
    assert params["asunto"] == "Reunion"
    # El "que" de "diciendo que ..." se descarta: es parte de la frase, no del mensaje.
    assert params["cuerpo"] == "confirmo"


def test_una_respuesta_sin_direccion_recuerda_de_quien():
    from skills.email_skill import EmailSkill

    params = EmailSkill().extract_params(
        "SEND_EMAIL", "responde el correo de ana diciendo que lo vemos el lunes",
    )

    assert params["destinatario"] == ""
    assert params["name"] == "ana"
    assert params["cuerpo"] == "lo vemos el lunes"


# ── El puente con la pantalla "Configuración" ───────────────────────

def test_el_bridge_expone_las_capacidades():
    """La UI las lee por el mismo camino perezoso que los overrides de seguridad."""
    from ui.webview.bridge import Bridge

    assert hasattr(Bridge, "request_email_capabilities")
    assert hasattr(Bridge, "save_email_capability")
    assert hasattr(Bridge, "email_capabilities_loaded")


def test_guardar_desde_el_bridge_enciende_la_capacidad():
    from ui.webview.bridge import Bridge

    Bridge._save_email_capability_flow(None, "send", True)

    assert email_capabilities.esta_activa("send")


def test_el_bridge_rechaza_un_id_inventado():
    """JS no puede crear capacidades nuevas mandando un id que el código no implementa."""
    from ui.webview.bridge import Bridge

    with pytest.raises(ValueError):
        Bridge._save_email_capability_flow(None, "borrar_todo", True)
