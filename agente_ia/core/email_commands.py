"""
core/email_commands.py
Órdenes por correo, acotadas (REQ-049).

El correo es entrada que cualquiera puede originar, y por eso su canal
(`ChannelType.EMAIL`) tiene política vacía: ni siquiera las acciones verdes. Eso no cambia.
Lo que este módulo agrega es un camino **estrecho** para que el dueño le mande una orden al
agente por correo y reciba la respuesta por correo:

- Solo correos cuyo remitente esté en `command_senders` (direcciones exactas) **y** que
  superen `sender_auth` con nivel `verified` (DKIM o SPF `pass` de un servidor de la lista
  `trusted_authserv_ids` de esa cuenta). El `From` lo escribe quien manda; sin la
  verificación, la lista no vale nada. Sin `trusted_authserv_ids` no se puede verificar y
  no se atiende ninguna orden (fail-closed, con log).
- Solo correos cuyo asunto empieza por el prefijo configurado (`ORION:` por defecto): la
  orden es explícita, no "cualquier correo".
- La orden se resuelve con el bucle de razonamiento en el canal EMAIL, sin turnos previos.
  Las únicas herramientas que ese canal alcanza son las remotas **de solo lectura** que el
  usuario habilitó para correo (`mcp_allow_tools` con `canales=email`, desde el escritorio y
  con confirmación): `core/mcp_manager._habilitar_canales` solo agrega la excepción EMAIL a
  las que el servidor anota `readOnlyHint: true`. El adaptador de confirmación de este canal
  (`confirmar_por_correo`) aprueba exactamente esas y deniega todo lo demás.
- La respuesta vuelve al remitente en el mismo hilo (`Re:`). No pasa por el interruptor
  «Enviar correos» ni por el gate 🔴 `send_email_as_user`: no es el agente escribiéndole a
  quien quiera como el usuario, es la respuesta a una orden verificada, y el interruptor
  «Atender órdenes por correo» (`email_capabilities`, apagado por defecto) es la decisión
  explícita del usuario. Queda en la auditoría como `email_command_reply`.
- Estado propio (`comandos::cuenta::user::buzón`) en `email_state.json`: atender órdenes no
  consume los correos nuevos que el lector de resúmenes todavía no mostró.

Configuración, dentro de `email` (o de cada cuenta de `accounts`)::

    "command_senders": ["yo@gmail.com"],
    "command_prefix": "ORION:",
    "command_poll_minutes": 5,
    "sender_auth": {"min": "verified", "trusted_authserv_ids": ["mx.google.com"]}
"""

import email.utils
import logging
import threading
from typing import Any, Dict, List, Optional

from core import email_auth, email_reader, email_sender
from core.security_manager import CHANNEL_ACTION_EXCEPTIONS, ChannelType

logger = logging.getLogger(__name__)

CAPACIDAD = "commands"
PREFIJO_POR_DEFECTO = "ORION:"
POLL_MINUTOS_POR_DEFECTO = 5
MAX_ORDEN_CHARS = 4000
MAX_RESPUESTA_CHARS = 8000

_hilo: Optional[threading.Thread] = None
_detener = threading.Event()


class OrdenRechazada(Exception):
    """El correo no cumple lo que hace falta para ser una orden; el mensaje dice por qué."""


# ── Configuración ───────────────────────────────────────────────────

def _config_de(cuenta_config: Dict[str, Any], clave: str, defecto: Any) -> Any:
    """Return `clave` de la cuenta o, si no está, de la sección `email` general."""
    if clave in cuenta_config:
        return cuenta_config[clave]
    return email_reader.cargar_config().get(clave, defecto)


def remitentes_autorizados(cuenta_config: Dict[str, Any]) -> List[str]:
    crudo = _config_de(cuenta_config, "command_senders", [])
    if not isinstance(crudo, list):
        return []
    return [str(d).strip().lower() for d in crudo if isinstance(d, str) and d.strip()]


def prefijo(cuenta_config: Dict[str, Any]) -> str:
    valor = str(_config_de(cuenta_config, "command_prefix", PREFIJO_POR_DEFECTO) or "").strip()
    return valor or PREFIJO_POR_DEFECTO


def esta_activa() -> bool:
    from core.email_capabilities import esta_activa

    return esta_activa(CAPACIDAD)


# ── Adaptador de confirmación del canal EMAIL ───────────────────────

def es_preautorizada_por_correo(action_name: str) -> bool:
    """Return True solo para una herramienta remota con excepción de canal para EMAIL.

    Esas excepciones las escribe únicamente `mcp_manager._habilitar_canales`, y solo para
    herramientas `readOnlyHint` no destructivas que el usuario habilitó para correo. Es la
    lista cerrada de lo que un correo puede pedir.
    """
    nombre = str(action_name or "")
    return nombre.startswith("mcp__") and (ChannelType.EMAIL, nombre) in CHANNEL_ACTION_EXCEPTIONS


def confirmar_por_correo(action_name: str, message: str) -> bool:
    """ConfirmFn del canal EMAIL: no hay nadie delante para preguntar.

    Aprueba lo que el usuario ya autorizó de antemano desde el escritorio (las remotas de
    solo lectura habilitadas para correo) y deniega todo lo demás. `require_confirmation()`
    lo audita como cualquier otra confirmación.
    """
    if es_preautorizada_por_correo(action_name):
        logger.info(f"Orden por correo: '{action_name}' preautorizada (solo lectura)")
        return True
    logger.warning(f"Orden por correo: '{action_name}' NO está preautorizada — denegada")
    return False


# ── Una orden ───────────────────────────────────────────────────────

def extraer_orden(mensaje, cuenta_config: Dict[str, Any]) -> Optional[str]:
    """Return el texto de la orden si el asunto lleva el prefijo; None si no es una orden."""
    asunto = str(mensaje.get("Subject", "") or "").strip()
    pref = prefijo(cuenta_config)
    if not asunto.lower().startswith(pref.lower()):
        return None
    resto = asunto[len(pref):].strip()
    cuerpo = email_reader._cuerpo_de(mensaje, MAX_ORDEN_CHARS).strip()
    texto = f"{resto}\n\n{cuerpo}".strip() if cuerpo else resto
    return texto[:MAX_ORDEN_CHARS] or None


def validar_remitente(mensaje, cuenta_config: Dict[str, Any]) -> str:
    """Return la dirección del remitente si puede dar órdenes; lanza `OrdenRechazada` si no."""
    permitidos = remitentes_autorizados(cuenta_config)
    if not permitidos:
        raise OrdenRechazada("no hay 'command_senders' configurados: nadie puede dar órdenes")

    _, direccion = email.utils.parseaddr(str(mensaje.get("From", "")))
    direccion = (direccion or "").strip().lower()
    if direccion not in permitidos:
        raise OrdenRechazada(f"'{direccion}' no está en command_senders")

    auth = dict(cuenta_config.get("sender_auth") or {})
    if not auth.get("trusted_authserv_ids"):
        raise OrdenRechazada(
            "sin 'sender_auth.trusted_authserv_ids' no se puede verificar quién manda el "
            "correo: no se atiende ninguna orden"
        )
    # El nivel mínimo para una orden es `verified`, aunque la cuenta tenga `none` para el
    # resumen: leer un correo suplantado es ruido; obedecerlo es otra cosa.
    if str(auth.get("min", "")).lower() != email_auth.NIVEL_STRICT:
        auth["min"] = email_auth.NIVEL_VERIFIED
    detalle, aceptado = email_auth.evaluar(mensaje, auth)
    if not aceptado:
        raise OrdenRechazada(f"'{direccion}' no supera la verificación ({detalle}); puede ser una suplantación")
    return direccion


def ejecutar_orden(texto: str) -> str:
    """Resuelve la orden en el canal EMAIL. Return el texto de la respuesta."""
    from core.reasoning_loop import run
    from core.user_identity import OWNER_USER_ID

    respuesta = run(texto, ChannelType.EMAIL, user_id=OWNER_USER_ID, prior_turns=[])
    return (respuesta or "").strip()[:MAX_RESPUESTA_CHARS] or "No obtuve ninguna respuesta."


def procesar_mensaje(cuenta: str, cuenta_config: Dict[str, Any], mensaje) -> Optional[str]:
    """Atiende un correo si es una orden válida. Return la respuesta enviada, o None.

    Primero se mira si es una orden (prefijo), después quién la manda y si está verificado,
    y recién ahí se ejecuta. Un correo que no es orden no genera ni un log de warning: la
    bandeja está llena de correos que no son para el agente.
    """
    texto = extraer_orden(mensaje, cuenta_config)
    if texto is None:
        return None
    try:
        remitente = validar_remitente(mensaje, cuenta_config)
    except OrdenRechazada as e:
        logger.warning(f"Orden por correo descartada ({cuenta}): {e}")
        return None

    logger.info(f"Orden por correo de '{remitente}' ({cuenta}): {texto[:80]!r}")
    respuesta = ejecutar_orden(texto)
    _responder(cuenta_config, mensaje, remitente, respuesta)
    return respuesta


def _responder(cuenta_config: Dict[str, Any], mensaje, remitente: str, respuesta: str) -> None:
    from core.security_manager import security_manager

    datos = email_sender.datos_para_responder(mensaje)
    try:
        resumen = email_sender.enviar(cuenta_config, [remitente], datos["asunto"], respuesta, datos)
    except email_sender.EnvioError as e:
        logger.error(f"No se pudo responder la orden por correo a '{remitente}': {e}")
        return
    try:
        security_manager.log_action(
            "email_command_reply", ChannelType.EMAIL, "enviada", user_id="owner",
            details=f"respuesta {resumen}",
        )
    except Exception as e:
        logger.warning(f"No se pudo auditar la respuesta por correo: {e}")


# ── El poller ───────────────────────────────────────────────────────

def _clave_estado(cuenta: str, config: Dict[str, Any], buzon: str) -> str:
    return f"comandos::{cuenta}::{config.get('user', '')}::{buzon}"


def revisar_ordenes() -> List[str]:
    """Busca órdenes nuevas en todas las cuentas y las atiende. Return las respuestas."""
    if not esta_activa():
        return []
    respuestas: List[str] = []
    for cuenta, config in email_reader.cargar_cuentas().items():
        if not remitentes_autorizados(config):
            continue
        try:
            respuestas.extend(_revisar_cuenta(cuenta, config))
        except email_reader.EmailError as e:
            logger.error(f"Órdenes por correo, cuenta '{cuenta}': {e}")
        except Exception as e:
            logger.error(f"Órdenes por correo, cuenta '{cuenta}': error inesperado: {e}")
    return respuestas


def _revisar_cuenta(cuenta: str, config: Dict[str, Any]) -> List[str]:
    buzon = str(config.get("mailbox", "INBOX"))
    conexion = email_reader._conectar(config)
    try:
        estado_conexion, _ = conexion.select(buzon, readonly=True)
        if estado_conexion != "OK":
            raise email_reader.EmailError(f"no se pudo abrir el buzón '{buzon}'")

        estado = email_reader._cargar_estado()
        clave = _clave_estado(cuenta, config, buzon)
        ultimo_uid = estado.get(clave)

        criterio = f"{int(ultimo_uid) + 1}:*" if ultimo_uid else "1:*"
        respuesta, datos = conexion.uid("SEARCH", None, "UID", criterio)
        if respuesta != "OK":
            raise email_reader.EmailError("la búsqueda de órdenes falló")
        uids = (datos[0] or b"").split()
        if ultimo_uid:
            uids = [u for u in uids if int(u) > int(ultimo_uid)]
        if not uids:
            return []

        uid_maximo = max(int(u) for u in uids)
        if ultimo_uid is None:
            # Estreno: se anota dónde está el buzón y no se atiende nada viejo — una orden
            # de hace meses no tiene por qué ejecutarse hoy.
            estado[clave] = uid_maximo
            email_reader._guardar_estado(estado)
            return []

        respuestas: List[str] = []
        for uid in uids:
            mensaje = email_reader._fetch_uid(conexion, uid)
            if mensaje is None:
                continue
            resultado = procesar_mensaje(cuenta, config, mensaje)
            if resultado is not None:
                respuestas.append(resultado)
        estado[clave] = uid_maximo
        email_reader._guardar_estado(estado)
        return respuestas
    finally:
        try:
            conexion.logout()
        except Exception as e:
            logger.debug(f"No se pudo cerrar la conexión IMAP limpiamente: {e}")


def _bucle(intervalo_s: float) -> None:
    while not _detener.wait(intervalo_s):
        if not esta_activa():
            continue
        try:
            revisar_ordenes()
        except Exception as e:
            logger.error(f"Órdenes por correo: fallo en la revisión periódica: {e}")


def start_polling() -> bool:
    """Arranca el hilo que revisa órdenes. Return si arrancó.

    No arranca si el interruptor está apagado o no hay cuentas: encenderlo después exige
    reiniciar, igual que las demás capacidades de correo.
    """
    global _hilo
    if _hilo is not None and _hilo.is_alive():
        return True
    if not esta_activa() or not email_reader.esta_configurado():
        return False
    minutos = email_reader.cargar_config().get("command_poll_minutes", POLL_MINUTOS_POR_DEFECTO)
    try:
        intervalo = max(1.0, float(minutos)) * 60.0
    except (TypeError, ValueError):
        intervalo = POLL_MINUTOS_POR_DEFECTO * 60.0
    _detener.clear()
    _hilo = threading.Thread(target=_bucle, args=(intervalo,), name="ordenes-por-correo", daemon=True)
    _hilo.start()
    logger.info(f"Órdenes por correo: revisando cada {intervalo / 60:.0f} min")
    return True


def stop_polling() -> None:
    _detener.set()
