"""
core/mcp_oauth.py
OAuth 2.1 para servidores MCP remotos: descubrimiento, registro dinámico, autorización con
PKCE y refresco de tokens.

Sin esto, O.R.I.O.N. solo puede hablar con servidores stdio locales o con los que aceptan
un token fijo en una cabecera. Los servidores alojados que importan —el Notion oficial,
Linear y varios más— exigen el flujo completo.

El flujo, tal como lo especifica MCP (OAuth 2.1 + RFC 9728 + RFC 8414 + RFC 7591):

1. Una petición sin credenciales devuelve 401 con `WWW-Authenticate: Bearer
   resource_metadata="..."`, que dice dónde está la metadata del recurso protegido.
2. Esa metadata nombra a su servidor de autorización.
3. Del servidor de autorización se leen sus endpoints (`/.well-known/oauth-authorization-server`).
4. Si no tenemos `client_id`, se registra uno solo (registro dinámico, RFC 7591).
5. Se abre el navegador con PKCE y se espera la vuelta en un puerto local.
6. El código se canjea por un `access_token` (y un `refresh_token` si el servidor lo da).

**El login NUNCA ocurre solo.** Abrir un navegador y quedarse esperando durante el arranque
de O.R.I.O.N. sería inaceptable: si falta el token, se avisa y se sigue. La autorización se
pide a mano con `python -m core.mcp_manager login <servidor>`, igual que el
`openclaw mcp login` que sirvió de referencia.

Los tokens se guardan en `mcp_tokens.json`, que está en .gitignore: son credenciales
reales, equivalentes a una contraseña.
"""

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

TOKENS_FILE = os.path.join(os.path.dirname(__file__), "..", "mcp_tokens.json")

#: Puerto fijo del loopback. Muchos servidores de autorización exigen que la URI de
#: redirección esté registrada de antemano y no aceptan un puerto que cambia en cada
#: intento; con el registro dinámico declaramos exactamente esta.
PUERTO_REDIRECCION = 8765
REDIRECT_URI = f"http://127.0.0.1:{PUERTO_REDIRECCION}/callback"

#: Margen con el que se considera vencido un token antes de que lo esté de verdad. Sin
#: esto, un token que vence durante la llamada haría fallar la petición en curso.
MARGEN_VENCIMIENTO = 60.0

TIMEOUT_HTTP = 15.0
TIMEOUT_AUTORIZACION = 300.0

_PATRON_RESOURCE_METADATA = re.compile(r'resource_metadata="([^"]+)"', re.IGNORECASE)


class OAuthError(Exception):
    """Falla en cualquier paso del flujo de autorización."""


# ── Almacén de tokens ───────────────────────────────────────────────

def cargar_tokens() -> Dict[str, Dict[str, Any]]:
    """Return {servidor: datos}. Ante cualquier problema, {} — habrá que volver a loguear."""
    if not os.path.exists(TOKENS_FILE):
        return {}
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except Exception as e:
        logger.error(f"mcp_tokens.json ilegible ({type(e).__name__}): {e}")
        return {}
    return datos if isinstance(datos, dict) else {}


def guardar_tokens(datos: Dict[str, Dict[str, Any]]) -> None:
    """Escribe el almacén con swap atómico y permisos restringidos.

    El archivo contiene credenciales vivas: se crea con permiso solo para el dueño donde el
    sistema operativo lo soporte. En Windows `chmod` no hace gran cosa, pero no cuesta nada
    y sirve si el proyecto se lleva a otra máquina.
    """
    directorio = os.path.dirname(os.path.abspath(TOKENS_FILE)) or "."
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".mcp_tokens_", dir=directorio)
    except OSError as e:
        logger.error(f"No se pudo crear el temporal de mcp_tokens.json: {e}")
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, sort_keys=True)
        try:
            os.chmod(tmp_path, 0o600)
        except OSError as e:
            logger.debug(f"No se pudieron restringir los permisos de mcp_tokens.json: {e}")
        os.replace(tmp_path, TOKENS_FILE)
    except OSError as e:
        logger.error(f"No se pudo guardar mcp_tokens.json: {e}")
        try:
            os.remove(tmp_path)
        except OSError as e:
            # El fallo principal ya quedo registrado arriba; esto es solo el temporal que
            # no se pudo limpiar. Igual se deja dicho: si empiezan a quedar .tmp sueltos
            # al lado del archivo de configuracion, este es el unico rastro.
            logger.debug(f"quedo un temporal sin borrar: {e}")


def olvidar(servidor: str) -> bool:
    """Borra las credenciales de `servidor`. Return True si había algo que borrar."""
    datos = cargar_tokens()
    if datos.pop(servidor, None) is None:
        return False
    guardar_tokens(datos)
    logger.info(f"mcp:{servidor}: credenciales OAuth borradas")
    return True


# ── Descubrimiento ──────────────────────────────────────────────────

def _get_json(url: str) -> Optional[dict]:
    import requests

    try:
        respuesta = requests.get(
            url, timeout=TIMEOUT_HTTP, headers={"Accept": "application/json"},
        )
    except Exception as e:
        logger.debug(f"No se pudo consultar {url}: {e}")
        return None
    if respuesta.status_code != 200:
        logger.debug(f"{url} respondió {respuesta.status_code}")
        return None
    try:
        datos = respuesta.json()
    except ValueError:
        return None
    return datos if isinstance(datos, dict) else None


def url_de_metadata_desde_401(respuesta) -> Optional[str]:
    """Saca la URL de metadata del `WWW-Authenticate` de un 401 (RFC 9728)."""
    cabecera = respuesta.headers.get("WWW-Authenticate", "") if respuesta is not None else ""
    match = _PATRON_RESOURCE_METADATA.search(cabecera or "")
    return match.group(1) if match else None


def descubrir_servidor_de_autorizacion(url_mcp: str,
                                       url_metadata: Optional[str] = None) -> str:
    """Return la URL base del servidor de autorización que protege a `url_mcp`.

    Se intenta primero la metadata del recurso protegido (la ruta que manda el estándar).
    Si el servidor no la publica —hay bastantes así— se cae al mismo origen que el
    endpoint MCP, que es lo que hacen en la práctica los clientes reales.
    """
    partes = urllib.parse.urlsplit(url_mcp)
    origen = f"{partes.scheme}://{partes.netloc}"

    candidatas = []
    if url_metadata:
        candidatas.append(url_metadata)
    candidatas.append(urllib.parse.urljoin(origen, "/.well-known/oauth-protected-resource"))

    for candidata in candidatas:
        metadata = _get_json(candidata)
        if not metadata:
            continue
        servidores = metadata.get("authorization_servers")
        if isinstance(servidores, list) and servidores:
            primero = str(servidores[0]).rstrip("/")
            logger.info(f"Servidor de autorización descubierto: {primero}")
            return primero

    logger.info(f"Sin metadata de recurso protegido; se asume el mismo origen: {origen}")
    return origen


def descubrir_endpoints(base_autorizacion: str) -> Dict[str, Any]:
    """Return la metadata del servidor de autorización (RFC 8414).

    Se prueban las dos rutas que se usan en la práctica; si ninguna responde, se arman los
    endpoints por convención en vez de fallar — hay servidores que funcionan y no publican
    metadata.
    """
    base = base_autorizacion.rstrip("/")
    for ruta in ("/.well-known/oauth-authorization-server",
                 "/.well-known/openid-configuration"):
        metadata = _get_json(base + ruta)
        if metadata and metadata.get("authorization_endpoint"):
            return metadata

    logger.warning(
        f"{base} no publica metadata de OAuth; se usan los endpoints por convención"
    )
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
    }


def registrar_cliente(metadata: Dict[str, Any], nombre_cliente: str = "O.R.I.O.N") -> str:
    """Registra un cliente nuevo y return su `client_id` (registro dinámico, RFC 7591)."""
    import requests

    endpoint = metadata.get("registration_endpoint")
    if not endpoint:
        raise OAuthError(
            "el servidor no soporta registro dinámico y no hay 'client_id' configurado: "
            "declaralo a mano en config.json bajo 'oauth': {'client_id': '...'}"
        )
    try:
        respuesta = requests.post(endpoint, timeout=TIMEOUT_HTTP, json={
            "client_name": nombre_cliente,
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        })
    except Exception as e:
        raise OAuthError(f"no se pudo registrar el cliente en {endpoint}: {e}") from e

    if respuesta.status_code not in (200, 201):
        raise OAuthError(
            f"el registro dinámico falló ({respuesta.status_code}): {respuesta.text[:200]}"
        )
    try:
        client_id = respuesta.json().get("client_id")
    except ValueError as e:
        raise OAuthError(f"el registro devolvió algo que no es JSON: {e}") from e
    if not client_id:
        raise OAuthError("el registro no devolvió 'client_id'")
    logger.info(f"Cliente OAuth registrado dinámicamente: {client_id}")
    return str(client_id)


# ── PKCE y loopback ─────────────────────────────────────────────────

def generar_pkce() -> Tuple[str, str]:
    """Return `(verifier, challenge)` para PKCE con S256."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


class _RecolectorDeCodigo(BaseHTTPRequestHandler):
    """Atiende UNA vuelta del navegador y guarda el `code` en el servidor."""

    def do_GET(self):  # noqa: N802 (nombre impuesto por BaseHTTPRequestHandler)
        parametros = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        self.server.codigo = (parametros.get("code") or [None])[0]
        self.server.estado = (parametros.get("state") or [None])[0]
        self.server.error = (parametros.get("error") or [None])[0]

        if self.server.codigo:
            cuerpo = "<h2>Listo</h2><p>Ya podés volver a O.R.I.O.N. y cerrar esta pestaña.</p>"
        else:
            cuerpo = f"<h2>No se pudo autorizar</h2><p>{self.server.error or 'sin detalle'}</p>"
        datos = f"<html><meta charset='utf-8'><body>{cuerpo}</body></html>".encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, formato, *args):
        # Silencia el log a stderr de http.server, que rompería la salida de la consola.
        logger.debug(f"oauth-loopback: {formato % args}")


def esperar_codigo(estado_esperado: str, timeout: float = TIMEOUT_AUTORIZACION) -> str:
    """Levanta el loopback, espera la redirección del navegador y return el `code`.

    Se verifica el `state`: sin eso, cualquier página abierta en el navegador del usuario
    podría llamar a este puerto y hacernos canjear un código ajeno (CSRF).
    """
    try:
        servidor = HTTPServer(("127.0.0.1", PUERTO_REDIRECCION), _RecolectorDeCodigo)
    except OSError as e:
        raise OAuthError(
            f"no se pudo abrir el puerto {PUERTO_REDIRECCION} para recibir la respuesta "
            f"del navegador: {e}"
        ) from e

    servidor.codigo = servidor.estado = servidor.error = None
    servidor.timeout = 1.0

    hilo = threading.Thread(target=_atender_hasta_recibir, args=(servidor, timeout), daemon=True)
    hilo.start()
    hilo.join(timeout + 5)

    try:
        servidor.server_close()
    except OSError as e:
        logger.debug(f"No se pudo cerrar el loopback: {e}")

    if servidor.error:
        raise OAuthError(f"el servidor de autorización rechazó el pedido: {servidor.error}")
    if not servidor.codigo:
        raise OAuthError("no llegó ninguna autorización desde el navegador (tiempo agotado)")
    if servidor.estado != estado_esperado:
        raise OAuthError("el 'state' de la respuesta no coincide: se descarta por seguridad")
    return servidor.codigo


def _atender_hasta_recibir(servidor, timeout: float) -> None:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if servidor.codigo or servidor.error:
            return
        servidor.handle_request()


# ── Canje y refresco ────────────────────────────────────────────────

def _pedir_token(endpoint: str, datos: Dict[str, str]) -> Dict[str, Any]:
    import requests

    try:
        respuesta = requests.post(
            endpoint, data=datos, timeout=TIMEOUT_HTTP,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
        )
    except Exception as e:
        raise OAuthError(f"no se pudo contactar el endpoint de token: {e}") from e

    if respuesta.status_code != 200:
        raise OAuthError(
            f"el canje de token falló ({respuesta.status_code}): {respuesta.text[:200]}"
        )
    try:
        token = respuesta.json()
    except ValueError as e:
        raise OAuthError(f"el endpoint de token no devolvió JSON: {e}") from e
    if not token.get("access_token"):
        raise OAuthError("la respuesta no trae 'access_token'")
    return token


def _con_vencimiento(token: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte el `expires_in` relativo en un instante absoluto.

    Guardar el relativo sería inútil apenas se cierre el proceso: al releerlo no habría
    forma de saber cuánto tiempo pasó.
    """
    guardado = dict(token)
    segundos = token.get("expires_in")
    if isinstance(segundos, (int, float)) and not isinstance(segundos, bool):
        guardado["expires_at"] = time.time() + float(segundos)
    return guardado


def esta_vencido(token: Dict[str, Any]) -> bool:
    vence = token.get("expires_at")
    if not isinstance(vence, (int, float)) or isinstance(vence, bool):
        return False   # sin vencimiento declarado, se usa hasta que el servidor diga que no
    return time.time() >= (vence - MARGEN_VENCIMIENTO)


def refrescar(servidor: str, guardado: Dict[str, Any]) -> Optional[str]:
    """Renueva el access token con el refresh token. None si no se pudo."""
    refresh = guardado.get("refresh_token")
    endpoint = guardado.get("token_endpoint")
    client_id = guardado.get("client_id")
    if not (refresh and endpoint and client_id):
        return None

    try:
        token = _pedir_token(endpoint, {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
        })
    except OAuthError as e:
        logger.warning(
            f"mcp:{servidor}: no se pudo refrescar el token ({e}); hay que loguear de nuevo"
        )
        return None

    nuevo = dict(guardado)
    nuevo.update(_con_vencimiento(token))
    # Un servidor puede no devolver refresh_token nuevo: se conserva el anterior, que
    # sigue siendo válido. Borrarlo obligaría a un login manual en la próxima renovación.
    if not token.get("refresh_token"):
        nuevo["refresh_token"] = refresh

    datos = cargar_tokens()
    datos[servidor] = nuevo
    guardar_tokens(datos)
    logger.info(f"mcp:{servidor}: token renovado sin intervención")
    return nuevo["access_token"]


def access_token_valido(servidor: str) -> Optional[str]:
    """Return un access token usable para `servidor`, refrescando si hace falta. None si no hay."""
    guardado = cargar_tokens().get(servidor)
    if not isinstance(guardado, dict) or not guardado.get("access_token"):
        return None
    if not esta_vencido(guardado):
        return guardado["access_token"]
    return refrescar(servidor, guardado)


def login(servidor: str, url_mcp: str, oauth_config: Optional[Dict[str, Any]] = None,
          url_metadata: Optional[str] = None, abrir_navegador: bool = True) -> str:
    """Corre el flujo completo y deja las credenciales guardadas. Return el access token.

    Es interactivo a propósito: abre el navegador y espera. Nunca se llama desde el
    arranque automático.
    """
    oauth_config = oauth_config or {}

    base = oauth_config.get("authorization_server") or descubrir_servidor_de_autorizacion(
        url_mcp, url_metadata,
    )
    metadata = descubrir_endpoints(base)
    client_id = oauth_config.get("client_id") or registrar_cliente(metadata)

    verifier, challenge = generar_pkce()
    estado = secrets.token_urlsafe(24)

    parametros = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": estado,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # RFC 8707: ata el token a este recurso concreto. Un servidor que lo ignore no se
        # rompe; uno que lo respete no acepta que el token se use en otro lado.
        "resource": url_mcp,
    }
    if oauth_config.get("scope"):
        parametros["scope"] = oauth_config["scope"]

    url_autorizacion = (
        metadata["authorization_endpoint"] + "?" + urllib.parse.urlencode(parametros)
    )
    print(f"\nAutorizá el acceso en el navegador:\n  {url_autorizacion}\n")
    if abrir_navegador:
        try:
            webbrowser.open(url_autorizacion)
        except Exception as e:
            logger.warning(f"No se pudo abrir el navegador solo ({e}); abrí la URL a mano")

    codigo = esperar_codigo(estado)
    token = _pedir_token(metadata["token_endpoint"], {
        "grant_type": "authorization_code",
        "code": codigo,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": verifier,
        "resource": url_mcp,
    })

    guardado = _con_vencimiento(token)
    guardado.update({
        "client_id": client_id,
        "token_endpoint": metadata["token_endpoint"],
        "authorization_server": base,
    })
    datos = cargar_tokens()
    datos[servidor] = guardado
    guardar_tokens(datos)
    logger.info(f"mcp:{servidor}: autorizado y credenciales guardadas")
    return guardado["access_token"]
