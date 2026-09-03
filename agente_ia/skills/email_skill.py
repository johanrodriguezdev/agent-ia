"""
skills/email_skill.py
Deja que el dueño pregunte por su correo: "¿tengo correos importantes?".

La skill NO lee el correo por su cuenta: se lo pide a `core/email_reader.py`, que corre
como entrada no confiable (`ChannelType.EMAIL`) y devuelve texto ya resumido. Esa
separación es el punto entero: quien pregunta está en un canal de confianza, pero lo que
se lee viene de cualquiera y no puede convertirse en una acción.

Lo que devuelve `execute()` es siempre texto para mostrar. Aunque un correo diga "abrí
esta página" o "borrá esos archivos", acá llega como una frase de un resumen, no como una
orden que el dispatcher vaya a ejecutar.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from skills.base_skill import BaseSkill

logger = logging.getLogger(__name__)

INTENT = "CHECK_EMAIL"
INTENT_GUARDAR = "SAVE_EMAIL_ATTACHMENT"
INTENT_ENVIAR = "SEND_EMAIL"
INTENT_MARCAR = "MARK_EMAIL_READ"

_RE_DIRECCION = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_RE_ASUNTO = re.compile(
    r"asunto\s+(?:de\s+|:\s*)?[\"'«]?(.+?)[\"'»]?(?=\s+(?:diciendo|que\s+diga|con\s+el\s+texto|y\s+dice)\b|$)",
    re.IGNORECASE,
)
_RE_CUERPO = re.compile(
    r"(?:diciendo|que\s+diga|con\s+el\s+texto|y\s+dice)\s+(?:que\s+)?[\"'«]?(.+?)[\"'»]?$",
    re.IGNORECASE | re.DOTALL,
)
_RE_DE_QUIEN = re.compile(
    r"(?:correo|mail|mensaje)\s+de\s+([\w.@+-]+)", re.IGNORECASE,
)

#: Lo que viene después de "adjunto"/"archivo". Se prueba PRIMERO porque es la única forma
#: de recuperar un nombre con espacios ("informe final.pdf") sin tragarse también el verbo.
_RE_DESPUES = re.compile(
    r"(?:adjunto|archivo|attachment)\s+(?:llamado\s+|que\s+se\s+llama\s+)?(.+)$",
    re.IGNORECASE,
)
#: Respaldo sin palabra clave: "descargá informe.pdf". Sin espacios a propósito — si los
#: admitiera se comería la frase entera.
_RE_ARCHIVO = re.compile(r"\S+\.[A-Za-z0-9]{1,8}\b")


class EmailSkill(BaseSkill):
    """Consulta el correo y devuelve un resumen de lo que llegó."""

    @property
    def name(self) -> str:
        return "EmailSkill"

    @property
    def description(self) -> str:
        return (
            "Revisa el correo entrante y resume lo que llegó desde la última consulta, "
            "sin marcarlo como leído ni actuar sobre lo que digan los mensajes."
        )

    def get_intents(self) -> List[str]:
        return [INTENT, INTENT_GUARDAR, INTENT_ENVIAR, INTENT_MARCAR]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            ("tengo correos", INTENT),
            ("tengo correos importantes", INTENT),
            ("revisa mi correo", INTENT),
            ("revisa el correo", INTENT),
            ("hay algo nuevo en el correo", INTENT),
            ("que llego al mail", INTENT),
            ("mira mi bandeja de entrada", INTENT),
            ("algo importante en el mail", INTENT),
            ("resumime los correos", INTENT),
            ("chequea el correo", INTENT),
            ("llego algun correo", INTENT),
            ("novedades en el correo", INTENT),

            ("guarda el adjunto", INTENT_GUARDAR),
            ("guardame el adjunto", INTENT_GUARDAR),
            ("descarga el adjunto", INTENT_GUARDAR),
            ("descargame el archivo del correo", INTENT_GUARDAR),
            ("guarda el archivo que llego por correo", INTENT_GUARDAR),
            ("baja el adjunto del correo", INTENT_GUARDAR),
            ("guarda ese archivo adjunto", INTENT_GUARDAR),
            ("descarga el documento adjunto", INTENT_GUARDAR),

            ("envia un correo", INTENT_ENVIAR),
            ("manda un correo a", INTENT_ENVIAR),
            ("mandale un mail a", INTENT_ENVIAR),
            ("responde ese correo", INTENT_ENVIAR),
            ("contesta el correo de", INTENT_ENVIAR),
            ("respondele diciendo", INTENT_ENVIAR),
            ("escribile un correo a", INTENT_ENVIAR),
            ("responde el mensaje de soporte", INTENT_ENVIAR),

            ("marca el correo como leido", INTENT_MARCAR),
            ("marca ese mail como leido", INTENT_MARCAR),
            ("marcalo como leido", INTENT_MARCAR),
            ("dalo por leido", INTENT_MARCAR),
            ("marca como leidos los correos", INTENT_MARCAR),
        ]

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        """Saca el nombre del archivo pedido.

        Se devuelve bajo la clave `filename` a propósito: es una de las claves que
        `security_manager.format_details()` muestra en el pedido de confirmación, así que
        el usuario ve QUÉ archivo va a guardar antes de decir que sí. Con otro nombre de
        clave, la confirmación sería un "¿seguro?" a ciegas.
        """
        if intent == INTENT_GUARDAR:
            return {"filename": self._nombre_pedido(text)}
        if intent == INTENT_ENVIAR:
            return self._datos_de_envio(text)
        if intent == INTENT_MARCAR:
            de_quien = _RE_DE_QUIEN.search(text or "")
            return {"name": de_quien.group(1) if de_quien else ""}
        return {}

    @staticmethod
    def _datos_de_envio(text: str) -> Dict[str, Any]:
        """Saca destinatario, asunto y cuerpo de la frase.

        `destinatario` y `asunto` viajan con esos nombres porque están en
        `_DETAILS_ALLOWED_KEYS`: enviar correo es ROJO, y el prompt del PIN tiene que decir
        a quién se le va a escribir. Autorizar sin ver eso sería firmar en blanco.
        """
        crudo = (text or "").strip()
        direccion = _RE_DIRECCION.search(crudo)
        asunto = _RE_ASUNTO.search(crudo)
        cuerpo = _RE_CUERPO.search(crudo)
        de_quien = _RE_DE_QUIEN.search(crudo)

        return {
            "destinatario": direccion.group(0) if direccion else "",
            "asunto": asunto.group(1).strip() if asunto else "",
            "cuerpo": cuerpo.group(1).strip() if cuerpo else "",
            # A quién responder cuando no se dio una dirección: "contestá el correo de Ana".
            "name": de_quien.group(1) if de_quien else "",
            "raw_text": crudo,
        }

    @staticmethod
    def _nombre_pedido(text: str) -> str:
        crudo = (text or "").strip()
        despues = _RE_DESPUES.search(crudo)
        if despues:
            return despues.group(1).strip(" \"'")
        con_extension = _RE_ARCHIVO.search(crudo)
        if con_extension:
            return con_extension.group(0).strip()
        return ""

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        if intent == INTENT_GUARDAR:
            return self._guardar_adjunto(params)
        if intent == INTENT_ENVIAR:
            return self._enviar(params)
        if intent == INTENT_MARCAR:
            return self._marcar_leido(params)
        return self._revisar()

    # ── Capacidades de escritura ────────────────────────────────────

    @staticmethod
    def _capacidad_apagada(capacidad: str) -> Optional[str]:
        """Return el mensaje a mostrar si `capacidad` está apagada, o None si está activa."""
        from core import email_capabilities
        from core.address import vocative

        if email_capabilities.esta_activa(capacidad):
            return None
        etiqueta = email_capabilities.CAPACIDADES[capacidad]["label"]
        return (
            f"«{etiqueta}» está desactivado{vocative()}. Podés activarlo en "
            f"Configuración → Seguridad, en «Capacidades del correo». Viene apagado a "
            f"propósito porque escribe sobre tu cuenta."
        )

    def _enviar(self, params: Dict[str, Any]) -> str:
        """Envía o responde un correo. Ya pasó el gate ROJO cuando esto corre."""
        from core.address import vocative
        from core import email_reader, email_sender

        apagado = self._capacidad_apagada("send")
        if apagado:
            return apagado

        cuerpo = (params.get("cuerpo") or "").strip()
        if not cuerpo:
            return (
                f"No entendí qué querés que diga el correo{vocative()}. Probá con "
                f"«respondé el correo de Ana diciendo que lo vemos el lunes»."
            )

        destino = (params.get("destinatario") or "").strip()
        asunto = (params.get("asunto") or "").strip()
        responder_a = None
        cuenta = None

        if not destino:
            # Sin dirección explícita, se responde a un correo que YA leímos. Nunca se
            # inventa un destinatario: si no hay a quién, no se manda nada.
            original = self._correo_referido(params.get("name"))
            if original is None:
                return (
                    f"No sé a quién escribirle{vocative()}. Decime la dirección, o pedime "
                    f"que responda un correo que ya te haya resumido."
                )
            try:
                mensaje = email_reader.traer_mensaje(original.cuenta, original.uid)
            except Exception as e:
                logger.error(f"No se pudo recuperar el correo a responder: {e}")
                return f"No pude recuperar ese correo para responderlo{vocative()}: {e}"

            datos = email_sender.datos_para_responder(mensaje)
            destino = datos["destinatario"]
            asunto = asunto or datos["asunto"]
            responder_a = datos
            cuenta = original.cuenta

        config = self._config_de(cuenta)
        if config is None:
            return f"No tengo ninguna cuenta de correo configurada para enviar{vocative()}."

        try:
            resumen = email_sender.enviar(config, destino, asunto, cuerpo, responder_a)
        except email_sender.EnvioError as e:
            return f"No pude enviar el correo{vocative()}: {e}"
        except Exception as e:
            logger.error(f"Fallo inesperado al enviar correo: {e}")
            return f"No pude enviar el correo{vocative()}: {e}"
        return f"Correo enviado {resumen}{vocative()}."

    def _marcar_leido(self, params: Dict[str, Any]) -> str:
        from core.address import vocative
        from core import email_reader

        apagado = self._capacidad_apagada("mark_read")
        if apagado:
            return apagado

        correo = self._correo_referido(params.get("name"))
        if correo is None:
            return (
                f"No sé cuál correo marcar{vocative()}. Pedime primero que revise el "
                f"correo, o decime de quién es."
            )
        try:
            email_reader.marcar_leido(correo.cuenta, correo.uid)
        except Exception as e:
            logger.error(f"No se pudo marcar como leído: {e}")
            return f"No pude marcarlo como leído{vocative()}: {e}"
        return f"Marqué como leído el correo de {correo.remitente}{vocative()}."

    @staticmethod
    def _correo_referido(nombre: Optional[str]):
        """Return el correo del último resumen que coincide con `nombre`, o el único.

        Si hay varios y no se nombró a nadie devuelve None: elegir por su cuenta a quién
        responderle o qué marcar no es algo que deba hacer sin que se lo digan.
        """
        from core import email_reader

        correos = email_reader.ultimos_correos()
        if not correos:
            return None
        if nombre:
            objetivo = nombre.strip().lower()
            for correo in correos:
                if objetivo in correo.remitente.lower():
                    return correo
            return None
        return correos[0] if len(correos) == 1 else None

    @staticmethod
    def _config_de(cuenta: Optional[str]):
        from core import email_reader

        cuentas = email_reader.cargar_cuentas()
        if cuenta and cuenta in cuentas:
            return cuentas[cuenta]
        return next(iter(cuentas.values()), None)

    # ── Guardar un adjunto ──────────────────────────────────────────

    def _guardar_adjunto(self, params: Dict[str, Any]) -> str:
        """Baja a disco un adjunto ya autorizado.

        Cuando esto corre, `security_manager` YA confirmó la acción amarilla mostrándole
        al usuario el nombre del archivo. Acá no se vuelve a preguntar: se busca el
        adjunto entre los del último resumen, se trae ese correo puntual y se escribe.
        """
        from core.address import vocative
        from core import email_attachments, email_reader

        pedido = (params.get("filename") or "").strip()
        correos = email_reader.ultimos_correos()
        disponibles = [(c, a) for c in correos for a in c.adjuntos]

        if not disponibles:
            return (
                f"No tengo ningún adjunto pendiente{vocative()}. Pedime primero que revise "
                f"el correo."
            )

        elegido = self._elegir(disponibles, pedido)
        if elegido is None:
            lista = "\n".join(f"  {a.describir()}" for _, a in disponibles)
            return (
                f"No encontré un adjunto que se llame «{pedido}»{vocative()}. "
                f"Los que tengo son:\n{lista}"
            )

        correo, adjunto = elegido
        try:
            mensaje = email_reader.traer_mensaje(correo.cuenta, correo.uid)
            ruta = email_attachments.guardar(mensaje, adjunto.nombre)
        except Exception as e:
            logger.error(f"No se pudo guardar el adjunto '{adjunto.nombre}': {e}")
            return f"No pude guardar «{adjunto.nombre}»{vocative()}: {e}"

        aviso = ""
        if adjunto.peligroso:
            marca = email_attachments.icono("⚠️", "(!)")
            aviso = (
                f"\n{marca} Recordá que es un archivo ejecutable: no lo abras si no sabés "
                f"exactamente qué es."
            )
        return f"Guardé «{adjunto.nombre}» en {ruta}{vocative()}.{aviso}"

    @staticmethod
    def _elegir(disponibles, pedido: str):
        """Return `(correo, adjunto)` que corresponde a `pedido`, o None.

        Sin nombre pedido se elige solo si hay UNO solo: adivinar entre varios archivos de
        terceros no es algo que deba hacer por su cuenta.
        """
        from core import email_attachments

        if not pedido:
            return disponibles[0] if len(disponibles) == 1 else None
        adjunto = email_attachments.buscar([a for _, a in disponibles], pedido)
        if adjunto is None:
            return None
        for correo, candidato in disponibles:
            if candidato is adjunto:
                return correo, candidato
        return None

    # ── Revisar el correo ───────────────────────────────────────────

    def _revisar(self) -> str:
        from core.address import vocative
        from core import email_reader

        if not email_reader.esta_configurado():
            return (
                f"No tengo el correo configurado todavía{vocative()}. Hay que completar la "
                f"sección 'email' de config.json con el servidor, el usuario y una "
                f"contraseña de aplicación leída del entorno."
            )

        try:
            resumen = email_reader.revisar()
        except Exception as e:
            # Nunca propagar: un fallo leyendo correo no puede tumbar la conversación.
            logger.error(f"Fallo al revisar el correo: {e}")
            return f"No pude revisar el correo ahora mismo{vocative()}: {e}"

        if not resumen:
            return f"No llegó nada nuevo desde la última revisión{vocative()}."
        return resumen
