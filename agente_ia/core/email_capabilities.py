"""
core/email_capabilities.py
Interruptores de las capacidades de ESCRITURA sobre el correo: enviar y marcar como leído.

Son dos cosas distintas y conviene no confundirlas:

- **La capacidad** (este módulo): ¿existe siquiera esta función en esta instalación? La
  decide el usuario desde la pantalla "Configuración". Por defecto: NO.
- **El riesgo** (`core/security_manager.py`): si la capacidad está activa, ¿cuánta
  confirmación hace falta cada vez que se usa? Lo decide el código, y el usuario solo puede
  SUBIRLO (REQ-019), nunca bajarlo.

Las dos tienen que dar permiso. Encender el interruptor no baja ninguna barrera: enviar
correo sigue siendo 🔴 Rojo —lo dice `.claude/rules/security-levels.md` y lo registra
REQ-005 como `send_email_as_user`—, así que sigue pidiendo el PIN maestro en escritorio y
sigue bloqueado desde cualquier canal remoto. El interruptor apagado hace que ni siquiera
llegue a preguntarse.

**Fail-closed en la dirección correcta.** Archivo ausente, corrupto o con basura adentro se
trata como TODO APAGADO. Es lo contrario de `security_overrides.json` —donde un archivo
inválido significa "nivel de código", no "sin restricciones"— pero es el mismo principio:
ante la duda, la opción que menos puede hacer daño. Acá esa opción es no poder escribir.

Archivo propio (`email_capabilities.json`) y no una clave más en config.json, por la misma
razón que `core/security_config.py`: que una corrupción de la configuración general no
pueda encender sola una capacidad de escritura, ni al revés.
"""

import json
import logging
import os
import tempfile
from typing import Dict

logger = logging.getLogger(__name__)

CAPABILITIES_FILE = os.path.join(
    os.path.dirname(__file__), "..", "email_capabilities.json",
)

#: Catálogo cerrado. Una clave que no esté acá se ignora al leer y se rechaza al escribir:
#: el archivo no puede inventar capacidades que el código no implementa.
CAPACIDADES: Dict[str, Dict[str, str]] = {
    "send": {
        "label": "Enviar correos",
        "description": (
            "Permite que el agente redacte y envíe correo desde tu cuenta. Sigue siendo "
            "una acción de riesgo alto: pide el PIN maestro en el escritorio y está "
            "bloqueada desde Telegram, Discord y voz."
        ),
    },
    "mark_read": {
        "label": "Marcar correos como leídos",
        "description": (
            "Permite que el agente marque como leído lo que ya te resumió. Pide "
            "confirmación cada vez. Con esto apagado, tu bandeja queda intacta."
        ),
    },
}


def cargar() -> Dict[str, bool]:
    """Return {capacidad: activa}. Ante cualquier problema, todo en False."""
    apagadas = {clave: False for clave in CAPACIDADES}

    if not os.path.exists(CAPABILITIES_FILE):
        return apagadas
    try:
        with open(CAPABILITIES_FILE, "r", encoding="utf-8") as f:
            crudo = json.load(f)
    except Exception as e:
        # `except Exception` amplio y logueado, igual que core/security_config.py: el caso
        # realista es un archivo truncado a mitad de escritura (UnicodeDecodeError).
        logger.error(
            f"email_capabilities.json ilegible ({type(e).__name__}) — se apagan TODAS las "
            f"capacidades de escritura de correo hasta que se corrija: {e}"
        )
        return apagadas

    if not isinstance(crudo, dict):
        logger.error("email_capabilities.json no es un objeto JSON — todo apagado")
        return apagadas

    resultado = dict(apagadas)
    for clave, valor in crudo.items():
        if clave not in CAPACIDADES:
            logger.warning(f"Capacidad de correo desconocida en el archivo, se ignora: {clave!r}")
            continue
        if not isinstance(valor, bool):
            # Un "true" string o un 1 NO encienden nada: solo un booleano de verdad.
            logger.warning(f"Valor inválido para '{clave}' ({valor!r}) — se deja apagada")
            continue
        resultado[clave] = valor
    return resultado


def esta_activa(capacidad: str) -> bool:
    """Return True solo si `capacidad` está explícitamente encendida."""
    return bool(cargar().get(capacidad, False))


def activar(capacidad: str, activa: bool) -> bool:
    """Enciende o apaga `capacidad`. Return True si se guardó.

    Rechaza cualquier clave fuera del catálogo: la UI no puede crear capacidades nuevas
    mandando un id inventado.
    """
    if capacidad not in CAPACIDADES:
        logger.warning(f"Se intentó configurar una capacidad de correo inexistente: {capacidad!r}")
        return False
    if not isinstance(activa, bool):
        logger.warning(f"Valor no booleano para '{capacidad}': {activa!r}")
        return False

    estado = cargar()
    estado[capacidad] = activa
    if not _escribir(estado):
        return False

    # A nivel WARNING y no INFO: encender una capacidad de escritura sobre el correo del
    # usuario es un evento que tiene que poder rastrearse después en el log.
    logger.warning(
        f"Capacidad de correo '{capacidad}' {'ACTIVADA' if activa else 'desactivada'} "
        f"por el usuario"
    )
    return True


def _escribir(estado: Dict[str, bool]) -> bool:
    """Escritura atómica, mismo patrón que core/security_config.py."""
    directorio = os.path.dirname(os.path.abspath(CAPABILITIES_FILE)) or "."
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".email_capabilities_", dir=directorio)
    except OSError as e:
        logger.error(f"No se pudo crear el temporal de email_capabilities.json: {e}")
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(estado, f, indent=2, sort_keys=True)
        os.replace(tmp_path, CAPABILITIES_FILE)   # atómico en Windows y POSIX
        return True
    except OSError as e:
        logger.error(f"No se pudo guardar email_capabilities.json: {e}")
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False


def filas_para_ui() -> list:
    """Return el catálogo con su estado, listo para la pantalla "Configuración"."""
    estado = cargar()
    return [
        {
            "id": clave,
            "label": meta["label"],
            "description": meta["description"],
            "enabled": estado.get(clave, False),
        }
        for clave, meta in CAPACIDADES.items()
    ]
