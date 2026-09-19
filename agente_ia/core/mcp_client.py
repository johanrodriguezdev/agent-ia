"""
core/mcp_client.py
Cliente MCP (Model Context Protocol) síncrono: transportes stdio y HTTP, más el subconjunto
de JSON-RPC 2.0 que hace falta para descubrir y ejecutar herramientas de otro programa.

**Por qué escrito a mano y no con el SDK oficial.** El SDK de MCP es asyncio de punta a
punta. `core/confirmation.py` declara explícitamente que el sistema de confirmación es
100% síncrono, y `agents/tool_registry.py::execute_tool()` —el gate por el que pasa toda
herramienta— también lo es. Meter un runtime async debajo obligaría a un puente
async→sync en cada llamada, que es exactamente la complejidad que ese módulo evitó a
propósito. Lo que se implementa acá es el protocolo completo de HERRAMIENTAS
(`initialize`, `tools/list`, `tools/call`); `resources`, `prompts` y `sampling` quedan
fuera porque no hacen falta para lo que O.R.I.O.N. necesita de un servidor MCP.

Este módulo NO decide nada de seguridad: solo habla el protocolo. Quién puede registrarse
y con qué nivel de riesgo lo deciden `core/remote_tools_policy.py` y
`agents/tool_registry.py`.
"""

import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Versión de protocolo que anunciamos en `initialize`. Se elige la más ampliamente
#: soportada a propósito: si el servidor habla una más nueva, responde con la suya y
#: seguimos igual (el handshake de MCP lo permite). Subirla sin necesidad solo agrega
#: servidores que rechazan la conexión.
PROTOCOL_VERSION = "2024-11-05"

CONNECT_TIMEOUT_DEFAULT = 10.0
REQUEST_TIMEOUT_DEFAULT = 30.0

#: Tope de páginas en `tools/list`. Un servidor que devolviera siempre un `nextCursor`
#: nuevo colgaría el arranque de O.R.I.O.N. para siempre.
_MAX_PAGINAS = 20

#: Cada cuánto se comprueba, mientras se espera una respuesta por stdio, que el servidor
#: siga vivo. Ver `StdioTransport.send_request()`.
_INTERVALO_LATIDO = 0.5

_PATRON_ENV = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


class MCPError(Exception):
    """Falla de protocolo, de transporte o error devuelto por el servidor."""


def expandir_secreto(valor: Any) -> Any:
    """Resuelve `"${VAR}"` contra el entorno; cualquier otro valor pasa tal cual.

    Existe para que una credencial no tenga que escribirse literal en config.json (la
    misma razón por la que OpenClaw guarda los headers sensibles fuera del archivo de
    configuración). Una variable no definida devuelve cadena vacía y se avisa: es
    preferible que el servidor rechace la autenticación con un error claro a mandarle el
    texto "${NOTION_TOKEN}" como si fuera un token.
    """
    if not isinstance(valor, str):
        return valor
    match = _PATRON_ENV.match(valor.strip())
    if not match:
        return valor
    nombre = match.group(1)
    resuelto = os.environ.get(nombre)
    if resuelto is None:
        # REQ-043 — el valor pegado en Configuración → Conexiones (`config.json →
        # mcp_variables`). El entorno manda, igual que con las claves de API.
        from core.mcp_config import valor_de_variable

        resuelto = valor_de_variable(nombre)
    if resuelto is None:
        logger.warning(
            f"La variable '{nombre}' no está definida ni en el entorno ni en la configuración "
            f"— se envía vacía"
        )
        return ""
    return resuelto


def _expandir_dict(datos: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not isinstance(datos, dict):
        return {}
    return {str(k): str(expandir_secreto(v)) for k, v in datos.items()}


# ── Transportes ─────────────────────────────────────────────────────

class StdioTransport:
    """Habla con un servidor MCP lanzado como subproceso, por stdin/stdout.

    El framing de stdio en MCP es JSON delimitado por saltos de línea (no el
    `Content-Length` de LSP).

    Dos detalles que no son opcionales:

    - **stderr se drena en un hilo.** Un servidor que escriba diagnósticos y nadie los
      lea llena el pipe del sistema operativo y se cuelga. Además sus mensajes son la
      única pista cuando algo no arranca, así que van al log con prefijo.
    - **stdout también se lee en un hilo**, hacia una cola. Leer una línea de un pipe es
      bloqueante y en Windows no hay forma portátil de darle timeout; con la cola, el
      timeout lo pone `queue.get()`.
    """

    def __init__(self, nombre: str, command: str, args: Optional[List[str]] = None,
                 cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None):
        self.nombre = nombre
        entorno = dict(os.environ)
        entorno.update(_expandir_dict(env))
        try:
            self._proc = subprocess.Popen(
                [command] + list(args or []),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd or None,
                env=entorno,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except (OSError, ValueError) as e:
            raise MCPError(f"no se pudo lanzar '{command}': {e}") from e

        self._entrantes: "queue.Queue[str]" = queue.Queue()
        self._lector = threading.Thread(
            target=self._leer_stdout, daemon=True, name=f"mcp-stdout-{nombre}",
        )
        self._lector.start()
        self._drenador = threading.Thread(
            target=self._drenar_stderr, daemon=True, name=f"mcp-stderr-{nombre}",
        )
        self._drenador.start()

    def _leer_stdout(self) -> None:
        try:
            for linea in self._proc.stdout:
                if linea.strip():
                    self._entrantes.put(linea.strip())
        except (ValueError, OSError) as e:
            logger.debug(f"mcp:{self.nombre}: se cerró stdout ({e})")

    def _drenar_stderr(self) -> None:
        try:
            for linea in self._proc.stderr:
                if linea.strip():
                    logger.debug(f"mcp:{self.nombre}: {linea.rstrip()}")
        except (ValueError, OSError) as e:
            logger.debug(f"mcp:{self.nombre}: se cerró stderr ({e})")

    def _escribir(self, mensaje: dict) -> None:
        if self._proc.poll() is not None:
            raise MCPError(f"el servidor '{self.nombre}' terminó (código {self._proc.returncode})")
        try:
            self._proc.stdin.write(json.dumps(mensaje, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError) as e:
            raise MCPError(f"no se pudo escribir a '{self.nombre}': {e}") from e

    def send_request(self, mensaje: dict, timeout: float) -> dict:
        self._escribir(mensaje)
        esperado = mensaje.get("id")
        limite = time.monotonic() + timeout
        while True:
            restante = limite - time.monotonic()
            if restante <= 0:
                metodo = mensaje.get("method")
                raise MCPError(
                    f"'{self.nombre}' no respondió a '{metodo}' en {timeout}s"
                )
            try:
                # Se espera en tajadas cortas en vez de un `get(timeout=restante)` de una
                # sola pieza para poder mirar si el proceso sigue vivo. Sin esto, un
                # servidor que se muere a mitad de una llamada nos hacía esperar el timeout
                # completo —30s por defecto— para descubrir algo que ya se sabía.
                cruda = self._entrantes.get(timeout=min(restante, _INTERVALO_LATIDO))
            except queue.Empty:
                if self._proc.poll() is None:
                    continue
                # Murió. Puede haber alcanzado a dejar la respuesta en la cola antes de
                # irse, así que se vacía lo pendiente antes de dar el error.
                respuesta = self._drenar_pendientes(esperado)
                if respuesta is not None:
                    return respuesta
                raise MCPError(
                    f"el servidor '{self.nombre}' terminó (código {self._proc.returncode}) "
                    f"mientras se esperaba '{mensaje.get('method')}'"
                )
            try:
                recibido = json.loads(cruda)
            except json.JSONDecodeError:
                logger.warning(f"mcp:{self.nombre}: línea que no es JSON, se ignora: {cruda[:200]}")
                continue
            # Un servidor puede mandar notificaciones (sin `id`) o respuestas a otra
            # petición mientras esperamos la nuestra: se descartan sin romper el ciclo.
            if isinstance(recibido, dict) and recibido.get("id") == esperado:
                return recibido
            logger.debug(f"mcp:{self.nombre}: mensaje fuera de turno, se ignora: {cruda[:200]}")

    def _drenar_pendientes(self, esperado) -> Optional[dict]:
        """Return la respuesta a `esperado` si quedó en la cola; None si no está."""
        while True:
            try:
                cruda = self._entrantes.get_nowait()
            except queue.Empty:
                return None
            try:
                recibido = json.loads(cruda)
            except json.JSONDecodeError:
                continue
            if isinstance(recibido, dict) and recibido.get("id") == esperado:
                return recibido

    def send_notification(self, mensaje: dict) -> None:
        self._escribir(mensaje)

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                self._proc.stdin.close()
            except (OSError, ValueError) as e:
                logger.debug(f"mcp:{self.nombre}: no se pudo cerrar stdin: {e}")
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning(f"mcp:{self.nombre}: no terminó solo, se lo mata")
                self._proc.kill()


class HttpTransport:
    """Habla con un servidor MCP por HTTP (transporte "streamable HTTP").

    La respuesta puede llegar como JSON directo o como un stream SSE; se aceptan las dos
    porque los servidores reales usan ambas. Si el servidor abre sesión devolviendo la
    cabecera `Mcp-Session-Id`, se reenvía en todo lo siguiente — sin eso, un servidor con
    estado trata cada petición como una conexión nueva y `tools/call` falla después de un
    `initialize` que parecía haber salido bien.
    """

    def __init__(self, nombre: str, url: str, headers: Optional[Dict[str, str]] = None,
                 oauth: Any = None):
        self.nombre = nombre
        self.url = url
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self._headers.update(_expandir_dict(headers))
        self._session_id: Optional[str] = None
        # `oauth: true` o `oauth: {...}` en config.json activan el flujo; ausente lo apaga.
        self._oauth: Optional[Dict[str, Any]] = (
            oauth if isinstance(oauth, dict) else ({} if oauth else None)
        )
        #: La deja un 401: dice dónde está la metadata del recurso protegido (RFC 9728).
        #: `mcp_manager.login()` la usa para no tener que adivinar el servidor de autorización.
        self.url_metadata_oauth: Optional[str] = None

    @property
    def usa_oauth(self) -> bool:
        return self._oauth is not None

    def _cabeceras(self) -> Dict[str, str]:
        cabeceras = dict(self._headers)
        if self._session_id:
            cabeceras["Mcp-Session-Id"] = self._session_id
        # El token se resuelve en CADA petición y no una vez al construir el transporte:
        # `access_token_valido()` refresca solo si hace falta, así que una sesión larga no
        # se cae cuando el token vence a mitad de camino.
        if self._oauth is not None and "Authorization" not in cabeceras:
            from core.mcp_oauth import access_token_valido

            token = access_token_valido(self.nombre)
            if token:
                cabeceras["Authorization"] = f"Bearer {token}"
        return cabeceras

    def _post(self, mensaje: dict, timeout: float):
        import requests

        try:
            return requests.post(
                self.url, json=mensaje, headers=self._cabeceras(), timeout=timeout,
            )
        except Exception as e:
            raise MCPError(f"no se pudo contactar a '{self.nombre}' ({self.url}): {e}") from e

    def send_request(self, mensaje: dict, timeout: float) -> dict:
        respuesta = self._post(mensaje, timeout)
        nueva_sesion = respuesta.headers.get("Mcp-Session-Id")
        if nueva_sesion:
            self._session_id = nueva_sesion
        if respuesta.status_code == 401:
            from core.mcp_oauth import url_de_metadata_desde_401

            self.url_metadata_oauth = url_de_metadata_desde_401(respuesta)
            if self._oauth is None:
                raise MCPError(
                    f"'{self.nombre}' exige autorización OAuth. Agregá \"oauth\": true a su "
                    f"definición en config.json y después ejecutá: "
                    f"python -m core.mcp_manager login {self.nombre}"
                )
            raise MCPError(
                f"'{self.nombre}' rechazó las credenciales. Ejecutá: "
                f"python -m core.mcp_manager login {self.nombre}"
            )
        if respuesta.status_code >= 400:
            raise MCPError(
                f"'{self.nombre}' respondió HTTP {respuesta.status_code}: {respuesta.text[:200]}"
            )
        return self._parsear(respuesta, mensaje.get("id"))

    def _parsear(self, respuesta, esperado) -> dict:
        tipo = (respuesta.headers.get("Content-Type") or "").lower()
        if "text/event-stream" not in tipo:
            try:
                return respuesta.json()
            except ValueError as e:
                raise MCPError(f"'{self.nombre}' devolvió algo que no es JSON: {e}") from e

        # SSE: interesan las líneas `data:`; puede venir más de un evento y solo una es
        # la respuesta a nuestra petición.
        ultimo = None
        for linea in respuesta.text.splitlines():
            if not linea.startswith("data:"):
                continue
            cuerpo = linea[len("data:"):].strip()
            if not cuerpo:
                continue
            try:
                mensaje = json.loads(cuerpo)
            except json.JSONDecodeError:
                continue
            if isinstance(mensaje, dict) and mensaje.get("id") == esperado:
                return mensaje
            ultimo = mensaje
        if ultimo is not None:
            return ultimo
        raise MCPError(f"'{self.nombre}' no devolvió ninguna respuesta utilizable por SSE")

    def send_notification(self, mensaje: dict) -> None:
        # Una notificación no lleva respuesta; el servidor contesta 202 y cuerpo vacío.
        self._post(mensaje, REQUEST_TIMEOUT_DEFAULT)

    def close(self) -> None:
        self._session_id = None


# ── Cliente ─────────────────────────────────────────────────────────

class MCPClient:
    """Un servidor MCP conectado: handshake, catálogo de herramientas y ejecución."""

    def __init__(self, nombre: str, transporte,
                 connect_timeout: float = CONNECT_TIMEOUT_DEFAULT,
                 request_timeout: float = REQUEST_TIMEOUT_DEFAULT):
        self.nombre = nombre
        self._transporte = transporte
        self._connect_timeout = connect_timeout
        self._request_timeout = request_timeout
        self._siguiente_id = 0
        self._inicializado = False
        self.server_info: Dict[str, Any] = {}
        #: Lo que el servidor declaró saber hacer en el handshake. Se consulta antes de
        #: pedirle recursos o prompts: preguntarle por algo que no ofrece produce un error
        #: JSON-RPC que ensucia el log sin aportar nada.
        self.capabilities: Dict[str, Any] = {}

    def _nuevo_id(self) -> int:
        self._siguiente_id += 1
        return self._siguiente_id

    def _pedir(self, metodo: str, params: Optional[dict] = None,
               timeout: Optional[float] = None) -> dict:
        mensaje = {"jsonrpc": "2.0", "id": self._nuevo_id(), "method": metodo}
        if params is not None:
            mensaje["params"] = params
        respuesta = self._transporte.send_request(mensaje, timeout or self._request_timeout)
        if not isinstance(respuesta, dict):
            raise MCPError(f"'{self.nombre}' devolvió una respuesta con forma inesperada")
        if "error" in respuesta:
            error = respuesta["error"] or {}
            raise MCPError(
                f"'{self.nombre}' rechazó '{metodo}': {error.get('message', error)} "
                f"(código {error.get('code', '?')})"
            )
        resultado = respuesta.get("result")
        return resultado if isinstance(resultado, dict) else {}

    def initialize(self) -> Dict[str, Any]:
        """Hace el handshake. Return el `serverInfo` que declaró el servidor."""
        resultado = self._pedir("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "orion", "version": "1.0"},
        }, timeout=self._connect_timeout)

        self.server_info = resultado.get("serverInfo") or {}
        capacidades = resultado.get("capabilities")
        self.capabilities = capacidades if isinstance(capacidades, dict) else {}
        version = resultado.get("protocolVersion")
        if version and version != PROTOCOL_VERSION:
            # No es un error: el servidor tiene derecho a responder con la suya.
            logger.info(
                f"mcp:{self.nombre}: habla la versión '{version}' y nosotros "
                f"'{PROTOCOL_VERSION}'; se continúa."
            )
        try:
            self._transporte.send_notification({
                "jsonrpc": "2.0", "method": "notifications/initialized",
            })
        except MCPError as e:
            # No es fatal: el handshake ya salió bien y el catálogo se puede pedir igual.
            # Hay servidores HTTP que responden 404/405 a una notificación en vez del 202
            # que manda el protocolo; tumbar por eso una conexión que funciona sería peor.
            logger.warning(f"mcp:{self.nombre}: no se pudo enviar 'initialized': {e}")
        self._inicializado = True
        logger.info(
            f"mcp:{self.nombre}: conectado "
            f"({self.server_info.get('name', 'servidor sin nombre')} "
            f"{self.server_info.get('version', '')})".rstrip()
        )
        return self.server_info

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return el catálogo completo de herramientas, resolviendo la paginación."""
        if not self._inicializado:
            raise MCPError(f"'{self.nombre}': hay que llamar a initialize() antes de listar")
        return self._paginar("tools/list", "tools")

    def call_tool(self, nombre_tool: str, argumentos: Optional[dict] = None) -> str:
        """Ejecuta una herramienta y devuelve su resultado ya convertido a texto."""
        if not self._inicializado:
            raise MCPError(f"'{self.nombre}': hay que llamar a initialize() antes de ejecutar")

        resultado = self._pedir("tools/call", {
            "name": nombre_tool,
            "arguments": argumentos or {},
        })
        texto = _contenido_a_texto(resultado.get("content"))
        if resultado.get("isError"):
            # El servidor reporta el fallo dentro del resultado, no como error JSON-RPC.
            # Se devuelve como texto —no se lanza— para que el loop de razonamiento pueda
            # leerlo y decidir qué hacer en vez de perder el turno entero.
            return f"Error de la herramienta '{nombre_tool}': {texto or 'sin detalle'}"
        return texto

    def soporta(self, capacidad: str) -> bool:
        """Return True si el servidor declaró la capacidad ('tools', 'resources', 'prompts').

        Un servidor que no la declara igual podría responder, pero preguntarle es pedir un
        error: se prefiere no molestarlo y decir que no la tiene.
        """
        return isinstance(self.capabilities.get(capacidad), dict)

    def list_resources(self) -> List[Dict[str, Any]]:
        """Return los recursos que publica el servidor (vacío si no soporta `resources`)."""
        if not self._inicializado:
            raise MCPError(f"'{self.nombre}': hay que llamar a initialize() antes de listar")
        if not self.soporta("resources"):
            return []
        return self._paginar("resources/list", "resources")

    def read_resource(self, uri: str) -> str:
        """Lee un recurso por URI y lo devuelve como texto."""
        if not self._inicializado:
            raise MCPError(f"'{self.nombre}': hay que llamar a initialize() antes de leer")
        resultado = self._pedir("resources/read", {"uri": uri})

        partes = []
        for bloque in resultado.get("contents") or []:
            if not isinstance(bloque, dict):
                continue
            if bloque.get("text"):
                partes.append(str(bloque["text"]))
            elif bloque.get("blob"):
                # Binario: se avisa en vez de volcar base64 dentro de una respuesta de texto.
                partes.append(f"[contenido binario en {bloque.get('uri', uri)}]")
        return "\n".join(partes).strip()

    def list_prompts(self) -> List[Dict[str, Any]]:
        """Return las plantillas de prompt del servidor (vacío si no soporta `prompts`)."""
        if not self._inicializado:
            raise MCPError(f"'{self.nombre}': hay que llamar a initialize() antes de listar")
        if not self.soporta("prompts"):
            return []
        return self._paginar("prompts/list", "prompts")

    def get_prompt(self, nombre_prompt: str, argumentos: Optional[dict] = None) -> str:
        """Resuelve una plantilla de prompt y devuelve su texto ya armado."""
        if not self._inicializado:
            raise MCPError(f"'{self.nombre}': hay que llamar a initialize() antes de pedir")
        resultado = self._pedir("prompts/get", {
            "name": nombre_prompt,
            "arguments": argumentos or {},
        })

        partes = []
        for mensaje in resultado.get("messages") or []:
            if not isinstance(mensaje, dict):
                continue
            texto = _contenido_a_texto(mensaje.get("content"))
            if texto:
                partes.append(f"{mensaje.get('role', 'user')}: {texto}")
        return "\n".join(partes).strip()

    def _paginar(self, metodo: str, clave: str) -> List[Dict[str, Any]]:
        """Recorre un listado paginado de MCP. Compartido por tools, resources y prompts."""
        elementos: List[Dict[str, Any]] = []
        cursor = None
        for pagina in range(_MAX_PAGINAS):
            resultado = self._pedir(metodo, {"cursor": cursor} if cursor else None)
            lote = resultado.get(clave)
            if isinstance(lote, list):
                elementos.extend(x for x in lote if isinstance(x, dict))
            cursor = resultado.get("nextCursor")
            if not cursor:
                break
            if pagina == _MAX_PAGINAS - 1:
                logger.warning(
                    f"mcp:{self.nombre}: se cortó la paginación de '{metodo}' en "
                    f"{_MAX_PAGINAS} páginas"
                )
        return elementos

    def close(self) -> None:
        try:
            self._transporte.close()
        except Exception as e:
            logger.warning(f"mcp:{self.nombre}: problema al cerrar el transporte: {e}")
        self._inicializado = False


def _contenido_a_texto(contenido) -> str:
    """Aplana el `content` de MCP a texto plano.

    Un bloque puede ser texto, imagen o un recurso embebido. O.R.I.O.N. entrega el
    resultado de una herramienta como string, así que lo no textual se describe en vez de
    descartarse en silencio — quien lea el resultado tiene que enterarse de que vino algo
    que no se pudo mostrar.
    """
    if isinstance(contenido, str):
        return contenido
    # Un mensaje de `prompts/get` trae UN bloque suelto, no una lista: sin esto, todo
    # prompt del servidor se resolvía a cadena vacía.
    if isinstance(contenido, dict):
        contenido = [contenido]
    if not isinstance(contenido, list):
        return ""

    partes = []
    for bloque in contenido:
        if not isinstance(bloque, dict):
            continue
        tipo = bloque.get("type")
        if tipo == "text":
            partes.append(str(bloque.get("text", "")))
        elif tipo == "resource":
            recurso = bloque.get("resource") or {}
            if isinstance(recurso, dict) and recurso.get("text"):
                partes.append(str(recurso["text"]))
            else:
                partes.append(f"[recurso: {recurso.get('uri', 'sin uri')}]")
        elif tipo:
            partes.append(f"[contenido de tipo '{tipo}' no representable como texto]")
    return "\n".join(p for p in partes if p).strip()


def crear_transporte(nombre: str, definicion: Dict[str, Any]):
    """Construye el transporte que corresponda a `definicion`. Lanza `MCPError` si no cuadra.

    Un servidor se define con `command` (stdio) o con `url` (HTTP), nunca con los dos ni
    con ninguno: adivinar cuál quiso el usuario sería peor que fallar con un mensaje claro.
    """
    command = (definicion.get("command") or "").strip()
    url = (definicion.get("url") or "").strip()

    if command and url:
        raise MCPError(f"'{nombre}' define 'command' y 'url' a la vez: elegí uno")
    if command:
        return StdioTransport(
            nombre, command,
            args=definicion.get("args") or [],
            cwd=definicion.get("cwd"),
            env=definicion.get("env"),
        )
    if url:
        return HttpTransport(
            nombre, url,
            headers=definicion.get("headers"),
            oauth=definicion.get("oauth"),
        )
    raise MCPError(f"'{nombre}' no define ni 'command' (stdio) ni 'url' (HTTP)")
