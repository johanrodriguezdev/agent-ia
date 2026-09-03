"""
core/email_sender.py
Envío de correo por SMTP, incluido responder a un mensaje ya leído.

**Esto es lo más peligroso que hace O.R.I.O.N. con el correo**, y por eso tiene tres
cerraduras distintas, ninguna de las cuales reemplaza a las otras:

1. **La capacidad** (`core/email_capabilities.py`): apagada por defecto. Se enciende a mano
   desde la pantalla "Configuración". Con esto apagado, ni se llega a preguntar.
2. **El nivel de riesgo**: enviar correo es 🔴 Rojo en `.claude/rules/security-levels.md` y
   está registrado como tal desde REQ-005. Eso significa PIN maestro en escritorio y
   bloqueo total desde Telegram, Discord y voz. No se baja ese nivel para hacerlo cómodo:
   `security_manager.register_action()` ni siquiera lo permitiría.
3. **El tope de destinatarios**: como mucho `MAX_DESTINATARIOS` por envío. Un agente no
   puede convertirse en un emisor masivo por un malentendido.

Configuración SMTP, dentro de la cuenta correspondiente de la sección `email`::

    "smtp": {
      "host": "smtp.gmail.com",
      "port": 587,
      "user": "vos@gmail.com",
      "password": "${ORION_EMAIL_PASSWORD}",
      "from_name": "Soporte"
    }

Si no hay bloque `smtp`, esta cuenta no puede enviar: no se adivinan credenciales a partir
de las de IMAP, porque adivinar mal acá significa filtrar una contraseña a un servidor
equivocado.
"""

import email.message
import email.utils
import logging
import re
import smtplib
import ssl
from typing import Any, Dict, List, Optional

from core.mcp_client import expandir_secreto

logger = logging.getLogger(__name__)

#: Tope duro por envío. No es configurable a propósito: el caso legítimo de este agente es
#: responder o avisar a una persona, nunca difundir.
MAX_DESTINATARIOS = 5

MAX_CUERPO_CHARS = 20_000
TIMEOUT_SMTP = 30

_RE_DIRECCION = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


class EnvioError(Exception):
    """No se pudo enviar: configuración, credenciales, destinatario o servidor."""


def direccion_valida(direccion: str) -> bool:
    """Return True si `direccion` tiene forma de correo. Validación de forma, no de existencia."""
    return bool(_RE_DIRECCION.match((direccion or "").strip()))


def _config_smtp(config_cuenta: Dict[str, Any]) -> Dict[str, Any]:
    smtp = config_cuenta.get("smtp")
    if not isinstance(smtp, dict):
        raise EnvioError(
            "esta cuenta no tiene bloque 'smtp' en config.json, así que no puede enviar"
        )
    host = str(smtp.get("host", "")).strip()
    usuario = str(expandir_secreto(smtp.get("user", ""))).strip()
    clave = str(expandir_secreto(smtp.get("password", "")))
    if not (host and usuario and clave):
        raise EnvioError("faltan host, user o password en el bloque 'smtp'")
    return {
        "host": host,
        "port": int(smtp.get("port", 587)),
        "user": usuario,
        "password": clave,
        "from_name": str(smtp.get("from_name", "")).strip(),
    }


def _normalizar_destinatarios(destinatarios) -> List[str]:
    # `getaddresses` y no un `split` por espacios: la forma «Ana <ana@x.com>» es de lo más
    # común y partirla por el espacio la rompe en dos cosas, ninguna de las cuales es una
    # dirección. Esta función de la stdlib entiende la lista entera, comas y nombres
    # incluidos.
    if isinstance(destinatarios, str):
        crudos = [destinatarios]
    else:
        crudos = [str(d) for d in (destinatarios or []) if str(d).strip()]

    limpios: List[str] = []
    for nombre, direccion in email.utils.getaddresses(crudos):
        direccion = (direccion or "").strip()
        if not direccion_valida(direccion):
            etiqueta = f"{nombre} <{direccion}>".strip() if nombre else (direccion or "(vacío)")
            raise EnvioError(f"«{etiqueta}» no parece una dirección de correo")
        if direccion not in limpios:
            limpios.append(direccion)

    if not limpios:
        raise EnvioError("no hay ningún destinatario")
    if len(limpios) > MAX_DESTINATARIOS:
        raise EnvioError(
            f"{len(limpios)} destinatarios superan el tope de {MAX_DESTINATARIOS} por envío"
        )
    return limpios


def _construir(smtp: Dict[str, Any], destinatarios: List[str], asunto: str, cuerpo: str,
               responder_a: Optional[Dict[str, str]] = None) -> email.message.EmailMessage:
    mensaje = email.message.EmailMessage()
    mensaje["From"] = (
        email.utils.formataddr((smtp["from_name"], smtp["user"]))
        if smtp["from_name"] else smtp["user"]
    )
    mensaje["To"] = ", ".join(destinatarios)
    mensaje["Subject"] = asunto or "(sin asunto)"
    mensaje["Date"] = email.utils.formatdate(localtime=True)
    mensaje["Message-ID"] = email.utils.make_msgid()

    if responder_a and responder_a.get("message_id"):
        # Sin estas dos cabeceras la respuesta aparece como un hilo nuevo en el cliente de
        # quien la recibe, que para un caso de soporte es exactamente lo que no se quiere.
        mensaje["In-Reply-To"] = responder_a["message_id"]
        referencias = responder_a.get("references") or ""
        mensaje["References"] = (
            f"{referencias} {responder_a['message_id']}".strip()
        )

    mensaje.set_content(cuerpo[:MAX_CUERPO_CHARS])
    return mensaje


def enviar(config_cuenta: Dict[str, Any], destinatarios, asunto: str, cuerpo: str,
           responder_a: Optional[Dict[str, str]] = None) -> str:
    """Envía el correo y return un resumen legible de lo que se mandó.

    NO consulta el gate de seguridad ni el interruptor de capacidad: eso lo hace quien
    llama (`skills/email_skill.py`), que es el único que conoce el canal real. Este módulo
    solo sabe hablar SMTP.
    """
    smtp = _config_smtp(config_cuenta)
    lista = _normalizar_destinatarios(destinatarios)
    if not (cuerpo or "").strip():
        raise EnvioError("el cuerpo del correo está vacío")

    mensaje = _construir(smtp, lista, asunto, cuerpo, responder_a)

    try:
        contexto = ssl.create_default_context()
        if smtp["port"] == 465:
            with smtplib.SMTP_SSL(smtp["host"], smtp["port"], timeout=TIMEOUT_SMTP,
                                  context=contexto) as servidor:
                servidor.login(smtp["user"], smtp["password"])
                servidor.send_message(mensaje)
        else:
            with smtplib.SMTP(smtp["host"], smtp["port"], timeout=TIMEOUT_SMTP) as servidor:
                servidor.starttls(context=contexto)
                servidor.login(smtp["user"], smtp["password"])
                servidor.send_message(mensaje)
    except smtplib.SMTPAuthenticationError as e:
        raise EnvioError(f"el servidor rechazó las credenciales SMTP: {e}") from e
    except Exception as e:
        raise EnvioError(f"no se pudo enviar por {smtp['host']}:{smtp['port']}: {e}") from e

    logger.warning(
        f"Correo ENVIADO a {', '.join(lista)} desde {smtp['user']} | asunto: {asunto!r}"
    )
    return f"a {', '.join(lista)} con el asunto «{asunto}»"


def datos_para_responder(mensaje) -> Dict[str, str]:
    """Saca de un mensaje leído lo necesario para responderle en el mismo hilo."""
    _, remitente = email.utils.parseaddr(str(mensaje.get("From", "")))
    return {
        "destinatario": remitente,
        "message_id": str(mensaje.get("Message-ID", "")).strip(),
        "references": str(mensaje.get("References", "")).strip(),
        "asunto": _asunto_de_respuesta(str(mensaje.get("Subject", ""))),
    }


def _asunto_de_respuesta(original: str) -> str:
    limpio = (original or "").strip() or "(sin asunto)"
    return limpio if limpio.lower().startswith("re:") else f"Re: {limpio}"
