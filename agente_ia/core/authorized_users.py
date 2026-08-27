"""
core/authorized_users.py
Control de acceso por identidad para los canales remotos (Telegram, Discord).

Antes de este módulo, `channels/telegram_bot.py` no comprobaba **quién** escribía: cualquier
persona que encontrara el bot era atendida como si fuera el dueño. Como las acciones
clasificadas 🟢 verde se ejecutan sin confirmación, y "tomar capturas de pantalla" es una de
ellas (`.claude/rules/security-levels.md`), un desconocido podía pedir una captura y
recibirla por el chat (`channels/gateway.py::_handle_screenshot` ->
`telegram_bot.py::reply_photo`). Las acciones 🟡 amarillas tampoco ayudaban: la confirmación
se le pedía al propio remitente, así que se autorizaba a sí mismo.

Modelo de confianza, el mismo que documenta OpenClaw para su caso: **un solo operador de
confianza**. Un agente con herramientas no es una frontera de seguridad entre varios
usuarios mutuamente desconfiados — quien puede hablarle comparte su autoridad para ejecutar.
Por eso esto es una lista de identidades permitidas, no un sistema de permisos por usuario.

Decisiones:

- **Los canales locales no se filtran.** `DESKTOP` y `VOICE` corren en la máquina del
  usuario: quien tiene acceso físico al equipo ya tiene acceso al agente, y filtrarlos solo
  serviría para que un archivo mal escrito deje a Johan fuera de su propia aplicación.
- **Fail-closed en los remotos.** Archivo ausente, corrupto, o sin la clave del canal
  significa "nadie autorizado", nunca "todos autorizados". Mismo criterio que REQ-005.
- **Archivo separado de `config.json`.** Igual que `security_overrides.json` en REQ-019: una
  corrupción de la configuración general no debe poder abrir el bot al mundo.
- **Recarga por mtime.** Autorizar a alguien no exige reiniciar el bot.
"""

import json
import logging
import os
import threading
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTHORIZED_USERS_FILE = os.path.join(_PROJECT_ROOT, "authorized_users.json")

#: Canales que corren en la máquina del usuario y por tanto no se filtran por identidad.
LOCAL_CHANNELS: Tuple[str, ...] = ("desktop", "voice", "cli")

#: Canales remotos: exigen que la identidad esté en la lista para ser atendidos.
REMOTE_CHANNELS: Tuple[str, ...] = ("telegram", "discord")

#: Lo que se le responde a quien no está autorizado. Neutro a propósito: no confirma que
#: exista un dueño, no nombra al agente y no da pistas de qué sabe hacer.
UNAUTHORIZED_MESSAGE = "No estás autorizado para usar este asistente."

_cache: Optional[Dict[str, Set[str]]] = None
_cache_stamp: Optional[Tuple[float, int]] = None
_lock = threading.Lock()


def _normalize_channel(channel) -> str:
    """Acepta `ChannelType` o `str` y devuelve la clave en minúsculas."""
    value = getattr(channel, "value", channel)
    return str(value).strip().lower()


def _parse(raw: dict) -> Dict[str, Set[str]]:
    """Convierte el JSON crudo a {canal: {ids}}, descartando lo que no encaje.

    Una entrada inválida se ignora individualmente en vez de invalidar el archivo entero:
    un error de tecleo en la lista de Discord no debe dejar a Telegram sin autorizados.
    """
    parsed: Dict[str, Set[str]] = {}
    for channel, ids in raw.items():
        key = str(channel).strip().lower()
        if key.startswith("_"):
            continue    # convención de comentario dentro del JSON, no es un canal
        if key not in REMOTE_CHANNELS:
            logger.warning(f"authorized_users.json: canal desconocido '{channel}', ignorado")
            continue
        if not isinstance(ids, list):
            logger.warning(f"authorized_users.json: '{channel}' no es una lista, ignorado")
            continue
        parsed[key] = {str(i).strip() for i in ids if str(i).strip()}
    return parsed


def _load() -> Dict[str, Set[str]]:
    """Return el mapa de autorizados, releyendo el archivo solo si cambió."""
    global _cache, _cache_stamp

    try:
        stat = os.stat(AUTHORIZED_USERS_FILE)
        stamp = (stat.st_mtime, stat.st_size)
    except FileNotFoundError:
        # Fail-closed: sin archivo, ningún remitente remoto está autorizado.
        logger.warning(
            "authorized_users.json no existe: ningún usuario remoto será atendido. "
            "Cree el archivo con las identidades autorizadas por canal."
        )
        with _lock:
            _cache, _cache_stamp = {}, None
        return {}
    except OSError as e:
        logger.error(f"No se pudo consultar authorized_users.json: {e}")
        return {}

    with _lock:
        if _cache is not None and _cache_stamp == stamp:
            return _cache

    try:
        with open(AUTHORIZED_USERS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        # Un archivo corrupto NO abre el bot: se trata como lista vacía.
        logger.error(f"authorized_users.json ilegible, nadie queda autorizado: {e}")
        with _lock:
            _cache, _cache_stamp = {}, stamp
        return {}

    if not isinstance(raw, dict):
        logger.error("authorized_users.json no es un objeto JSON, nadie queda autorizado")
        with _lock:
            _cache, _cache_stamp = {}, stamp
        return {}

    parsed = _parse(raw)
    with _lock:
        _cache, _cache_stamp = parsed, stamp
    return parsed


def is_authorized(channel, external_id) -> bool:
    """Return True si `external_id` puede ser atendido en `channel`.

    `channel` es SIEMPRE el canal real que pasa el caller, nunca uno deducido del texto —
    mismo invariante que `core/security_manager.py`. Los canales locales devuelven True sin
    consultar el archivo.
    """
    key = _normalize_channel(channel)

    if key in LOCAL_CHANNELS:
        return True

    if key not in REMOTE_CHANNELS:
        # Canal desconocido: fail-closed, como cualquier acción sin clasificar (REQ-005).
        logger.warning(f"is_authorized(): canal no reconocido '{key}', se deniega")
        return False

    identity = str(external_id).strip() if external_id is not None else ""
    if not identity:
        logger.warning(f"is_authorized(): identidad vacía en '{key}', se deniega")
        return False

    return identity in _load().get(key, set())


def list_authorized(channel) -> List[str]:
    """Return las identidades autorizadas de un canal. Para diagnóstico y tests."""
    return sorted(_load().get(_normalize_channel(channel), set()))


def clear_cache() -> None:
    """Vacía la caché. Existe para los tests."""
    global _cache, _cache_stamp
    with _lock:
        _cache, _cache_stamp = None, None
