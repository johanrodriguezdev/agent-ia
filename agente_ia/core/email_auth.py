"""
core/email_auth.py
Verificación de que un correo viene de quien dice venir (DKIM / SPF / DMARC).

Por qué hace falta: `allowed_senders` filtra por la dirección del campo `From`, y ese campo
lo escribe quien manda. Sin verificar nada, cualquiera puede poner `jefe@empresa.com` ahí y
pasar el filtro. La verificación no la hacemos nosotros —la hizo el servidor de correo al
recibir el mensaje— y queda anotada en la cabecera `Authentication-Results`.

**El detalle que hace o rompe esto:** esa cabecera también la puede escribir el que manda.
Un atacante agrega su propio `Authentication-Results: loquesea; dkim=pass` y, si le
creemos, la verificación no sirvió de nada. Por eso solo se acepta la cabecera cuyo
identificador de servidor (`authserv-id`, lo primero que aparece) esté en la lista de
servidores que el usuario declaró como suyos. Sin esa lista no se puede verificar nada, y
se dice: "desconocido" en vez de un "pass" mentiroso.

Es el mismo razonamiento del `trustedAuthservIds` de OpenClaw
(`openclaw-main/docs/automation/imap.md`).

Configuración, dentro de una cuenta de la sección `email`::

    "sender_auth": {
      "min": "verified",
      "trusted_authserv_ids": ["mx.google.com"]
    }

`min` puede ser:

- `none` (por defecto): no se exige nada. Se sigue anotando qué se pudo comprobar.
- `verified`: hace falta `dkim=pass` o `spf=pass` de un servidor de confianza.
- `strict`: hace falta `dmarc=pass`, que es el que ata el `From` visible al dominio firmante.
"""

import logging
import re
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

NIVEL_NONE = "none"
NIVEL_VERIFIED = "verified"
NIVEL_STRICT = "strict"
_NIVELES = (NIVEL_NONE, NIVEL_VERIFIED, NIVEL_STRICT)

RESULTADO_PASS = "pass"
RESULTADO_FAIL = "fail"
RESULTADO_DESCONOCIDO = "desconocido"

_RE_METODO = re.compile(r"\b(dkim|spf|dmarc)\s*=\s*([a-z]+)", re.IGNORECASE)


def _authserv_id(cabecera: str) -> str:
    """Return el identificador del servidor que escribió la cabecera (lo primero que va)."""
    return (cabecera or "").split(";", 1)[0].strip().split()[0].lower() if cabecera.strip() else ""


def _metodos(cabecera: str) -> Dict[str, str]:
    """Return {'dkim': 'pass', 'spf': 'fail', ...} tal como los reportó el servidor."""
    encontrados: Dict[str, str] = {}
    # Se salta el authserv-id: un servidor llamado "spf=pass.ejemplo.com" no puede
    # colarse como si fuera un resultado.
    cuerpo = cabecera.split(";", 1)[1] if ";" in cabecera else ""
    for metodo, resultado in _RE_METODO.findall(cuerpo):
        encontrados.setdefault(metodo.lower(), resultado.lower())
    return encontrados


def _cabeceras_confiables(mensaje, confiables: List[str]) -> List[str]:
    """Return solo las cabeceras `Authentication-Results` puestas por un servidor nuestro."""
    try:
        todas = mensaje.get_all("Authentication-Results") or []
    except Exception as e:
        logger.warning(f"No se pudieron leer las cabeceras de autenticación: {e}")
        return []

    permitidos = {str(c).strip().lower() for c in confiables if str(c).strip()}
    if not permitidos:
        # Sin lista de servidores propios NO se puede distinguir la cabecera real de una
        # que agregó el atacante. Se descartan todas: es preferible "desconocido" a un
        # "pass" que no significa nada.
        return []
    return [str(c) for c in todas if _authserv_id(str(c)) in permitidos]


def evaluar(mensaje, config: Dict[str, Any]) -> Tuple[str, bool]:
    """Return `(detalle, aceptado)` para `mensaje` según la política de `config`.

    `detalle` es texto corto para el resumen ("dkim=pass spf=pass", "sin verificar").
    `aceptado` dice si el correo pasa la política mínima configurada.
    """
    config = config if isinstance(config, dict) else {}
    nivel = str(config.get("min", NIVEL_NONE)).strip().lower()
    if nivel not in _NIVELES:
        logger.warning(f"sender_auth.min '{nivel}' no es válido; se usa '{NIVEL_NONE}'")
        nivel = NIVEL_NONE

    confiables = config.get("trusted_authserv_ids") or []
    if not isinstance(confiables, list):
        logger.warning("sender_auth.trusted_authserv_ids no es una lista — se ignora")
        confiables = []

    cabeceras = _cabeceras_confiables(mensaje, confiables)
    if not cabeceras:
        detalle = RESULTADO_DESCONOCIDO
        # Con `none` no se exige nada, así que un correo sin verificar igual pasa.
        return detalle, nivel == NIVEL_NONE

    resultados: Dict[str, str] = {}
    for cabecera in cabeceras:
        for metodo, resultado in _metodos(cabecera).items():
            # Gana el mejor resultado entre las cabeceras confiables: un servidor puede
            # anotar dkim y otro spf.
            if resultados.get(metodo) != RESULTADO_PASS:
                resultados[metodo] = resultado

    detalle = " ".join(f"{m}={r}" for m, r in sorted(resultados.items())) or RESULTADO_DESCONOCIDO

    if nivel == NIVEL_NONE:
        return detalle, True
    if nivel == NIVEL_STRICT:
        return detalle, resultados.get("dmarc") == RESULTADO_PASS
    return detalle, RESULTADO_PASS in (resultados.get("dkim"), resultados.get("spf"))


def advertir_si_falta_configuracion(cuenta: str, config_cuenta: Dict[str, Any]) -> None:
    """Avisa una vez si hay allow-list de remitentes sin verificación que la respalde.

    Filtrar por dirección sin verificar autenticación da una sensación de seguridad que no
    existe: el campo `From` lo escribe quien manda. No se bloquea nada —el canal sigue sin
    poder ejecutar— pero el usuario tiene que saberlo.
    """
    tiene_lista = bool(config_cuenta.get("allowed_senders"))
    auth = config_cuenta.get("sender_auth") or {}
    verifica = bool(isinstance(auth, dict) and auth.get("trusted_authserv_ids"))
    if tiene_lista and not verifica:
        logger.warning(
            f"Cuenta '{cuenta}': hay 'allowed_senders' pero no 'sender_auth."
            f"trusted_authserv_ids'. El campo From se puede falsificar, así que la lista "
            f"filtra ruido pero no impide una suplantación. Ver core/email_auth.py."
        )
