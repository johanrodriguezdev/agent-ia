"""
core/http_seguro.py
REQ-031 — El único lugar donde se decide si el agente puede pedir una dirección de internet.

Antes de esto, `os_integration/web_search.py::leer_pagina()` validaba **solo el esquema**:
cualquier `http://` se pedía, incluido `http://127.0.0.1:3000` o `http://192.168.1.1`. Y
como `web_read` es 🟢 verde, eso era alcanzable desde Telegram: un mensaje podía hacer que el
agente leyera el panel de un servicio local o el router y devolviera el contenido al chat.
Reproducido antes de escribir este módulo (`workspace/adjuntos/REQ-031/origen/`).

Tres decisiones que son el módulo entero:

- **Se mira la IP resuelta, no el texto de la URL.** `localhost`, `127.0.0.1`, `0x7f.1` y un
  dominio que resuelve a `10.0.0.5` son el mismo ataque escrito de cuatro maneras. Filtrar
  por texto es filtrar la ortografía del atacante.
- **Las redirecciones se siguen a mano, revalidando cada salto.** `requests` las sigue solo:
  validar la primera dirección y confiar en el resto es el error clásico, porque una URL
  pública puede redirigir a una interna.
- **Se corta por tamaño mientras se descarga**, no después: una respuesta de gigabytes no
  puede llenar la memoria antes de que a alguien se le ocurra medirla.

Límite conocido y no cerrado: entre que se valida el nombre y se abre la conexión, el DNS
puede cambiar de respuesta (DNS rebinding). Cerrarlo exige conectarse a la IP ya validada
forzando el `Host`, que rompe SNI en HTTPS. Queda documentado en el contexto del REQ.
"""

import ipaddress
import logging
import socket
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class DestinoBloqueado(Exception):
    """La dirección no se puede pedir. El mensaje explica por qué, en castellano."""


#: Lo único que se puede pedir. `file://`, `ftp://` y `data:` quedan afuera por no estar acá,
#: que es más seguro que enumerarlos: mañana aparece otro esquema y sigue estando afuera.
ESQUEMAS_PERMITIDOS = ("http", "https")

MAX_REDIRECCIONES = 5
TIMEOUT_SEGUNDOS = 15
#: Tope de lo que se descarga. Lo que se le devuelve al modelo se recorta mucho antes; esto
#: es la barrera contra una respuesta que quiera llenar la memoria del proceso.
MAX_BYTES = 2 * 1024 * 1024

_METODOS_PERMITIDOS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")


@dataclass
class Respuesta:
    """Lo que devuelve `pedir()`. `truncada` avisa que el cuerpo se cortó por tamaño."""

    status: int
    texto: str
    url_final: str
    content_type: str = ""
    truncada: bool = False
    headers: Dict[str, str] = field(default_factory=dict)


def _es_interna(ip: "ipaddress.IPv4Address | ipaddress.IPv6Address") -> bool:
    """Return True si la IP es de la propia máquina, de la red local o reservada.

    `is_link_local` cubre `169.254.0.0/16`, que incluye `169.254.169.254`: el endpoint de
    metadatos de las nubes, donde viven las credenciales de la instancia. Es el destino
    clásico de un SSRF y por eso se nombra acá, aunque ya esté cubierto.
    """
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _direcciones_de(host: str, puerto: int) -> list:
    """Return las IPs a las que resuelve `host`. Levanta `DestinoBloqueado` si no resuelve."""
    try:
        info = socket.getaddrinfo(host, puerto, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, ValueError) as e:
        logger.info(f"no se pudo resolver el destino '{host}': {e}")
        raise DestinoBloqueado(
            f"No pude resolver «{host}»: puede estar mal escrito o no existir."
        ) from e
    return [entrada[4][0] for entrada in info]


def validar_url(url: str) -> str:
    """Return la URL si se puede pedir. Levanta `DestinoBloqueado` con el motivo si no.

    Se rechaza si **cualquiera** de las IPs a las que resuelve el nombre es interna: un
    dominio puede devolver varias, y alcanzar con una para que la conexión termine adentro.
    """
    texto = str(url or "").strip()
    if not texto:
        raise DestinoBloqueado("No me dijiste qué dirección abrir.")

    partes = urlparse(texto)
    if partes.scheme.lower() not in ESQUEMAS_PERMITIDOS:
        raise DestinoBloqueado(
            f"Solo puedo abrir direcciones http:// o https://, y «{partes.scheme or texto[:20]}» "
            f"no lo es."
        )
    host = partes.hostname
    if not host:
        raise DestinoBloqueado(f"«{texto[:60]}» no tiene un servidor al que conectarse.")

    puerto = partes.port or (443 if partes.scheme.lower() == "https" else 80)
    for direccion in _direcciones_de(host, puerto):
        try:
            ip = ipaddress.ip_address(direccion.split("%")[0])  # %scope de IPv6
        except ValueError:
            logger.warning(f"dirección irreconocible al resolver '{host}': {direccion!r}")
            raise DestinoBloqueado(f"No pude verificar a dónde apunta «{host}».")
        if _es_interna(ip):
            logger.warning(
                f"Destino interno bloqueado: '{host}' resuelve a {ip}. Pedir direcciones de "
                f"la propia máquina o de la red local desde una herramienta del agente es "
                f"exactamente el SSRF que REQ-031 cierra."
            )
            raise DestinoBloqueado(
                f"«{host}» apunta a la propia máquina o a la red local, y no puedo abrir "
                f"direcciones internas: solo internet."
            )
    return texto


def pedir(
    url: str,
    metodo: str = "GET",
    headers: Optional[Dict[str, Any]] = None,
    cuerpo: Optional[Any] = None,
    timeout: int = TIMEOUT_SEGUNDOS,
    max_bytes: int = MAX_BYTES,
) -> Respuesta:
    """Hace la petición validando el destino en cada redirección. Return `Respuesta`.

    Levanta `DestinoBloqueado` si el destino no se puede pedir, y `OSError` si la conexión
    falla — el llamador decide cómo contarlo.
    """
    import requests

    verbo = str(metodo or "GET").upper()
    if verbo not in _METODOS_PERMITIDOS:
        raise DestinoBloqueado(
            f"«{verbo}» no es un método que pueda usar. Puedo: {', '.join(_METODOS_PERMITIDOS)}."
        )

    cabeceras = {"User-Agent": "Mozilla/5.0 (compatible; asistente personal)"}
    cabeceras.update({str(k): str(v) for k, v in (headers or {}).items()})

    actual = validar_url(url)
    for salto in range(MAX_REDIRECCIONES + 1):
        # `allow_redirects=False` es el punto: cada salto vuelve a pasar por `validar_url()`.
        respuesta = requests.request(
            verbo, actual, headers=cabeceras, data=cuerpo, timeout=timeout,
            allow_redirects=False, stream=True,
        )
        if respuesta.is_redirect or respuesta.status_code in (301, 302, 303, 307, 308):
            destino = respuesta.headers.get("Location", "")
            respuesta.close()
            if not destino:
                raise DestinoBloqueado("El servidor redirigió a ninguna parte.")
            actual = validar_url(requests.compat.urljoin(actual, destino))
            logger.debug(f"redirección {salto + 1} → {actual}")
            continue

        crudo = b""
        truncada = False
        for trozo in respuesta.iter_content(8192):
            crudo += trozo
            if len(crudo) >= max_bytes:
                truncada = True
                break
        respuesta.close()

        codificacion = respuesta.encoding or "utf-8"
        return Respuesta(
            status=respuesta.status_code,
            texto=crudo.decode(codificacion, errors="replace"),
            url_final=actual,
            content_type=respuesta.headers.get("Content-Type", ""),
            truncada=truncada,
            headers=dict(respuesta.headers),
        )

    raise DestinoBloqueado(
        f"Esa dirección redirige más de {MAX_REDIRECCIONES} veces y dejé de seguirla."
    )
