"""
core/mcp_manager.py
Conecta los servidores MCP declarados en config.json, descubre sus herramientas y las
registra en O.R.I.O.N. pasando por el gate de `agents/tool_registry.py`.

Este módulo es el puente entre "hablar el protocolo" (`core/mcp_client.py`) y "decidir qué
entra" (`core/remote_tools_policy.py`). No relaja ninguna de las dos cosas: toda
herramienta descubierta se propone con `origin="mcp_remote"` y `register_tool()` la acepta
o la rechaza según la allow-list.

Definición de servidores en config.json::

    "mcp_servers": {
      "notion":   { "command": "npx", "args": ["-y", "@notionhq/notion-mcp-server"],
                    "env": { "NOTION_TOKEN": "${NOTION_TOKEN}" } },
      "calendar": { "url": "https://mcp.ejemplo.com/mcp",
                    "headers": { "Authorization": "Bearer ${CALENDAR_TOKEN}" },
                    "enabled": true, "connect_timeout": 10, "request_timeout": 30 }
    }

Declarar un servidor no habilita ninguna herramienta: eso lo decide `mcp_allowlist.json`.
Son dos archivos a propósito — "a qué me conecto" y "qué le acepto" son decisiones
distintas, y la segunda es la que importa para la seguridad.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from agents.tool_registry import ToolSpec, register_tool, unregister_tool
from core.mcp_client import MCPClient, MCPError, crear_transporte
from core.remote_tools_policy import canales_permitidos, is_tool_allowed, nombre_calificado
from core.security_manager import (
    CHANNEL_ACTION_EXCEPTIONS,
    RiskLevel,
    security_manager,
)

logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "config.json")

#: Servidores conectados en esta ejecución: {nombre: MCPClient}.
_CLIENTES: Dict[str, MCPClient] = {}

#: Último intento de reconexión por servidor, para no reintentar en bucle.
_ULTIMO_INTENTO: Dict[str, float] = {}
SEGUNDOS_ENTRE_RECONEXIONES = 30.0


def cargar_definiciones() -> Dict[str, Dict[str, Any]]:
    """Return los servidores declarados en config.json. Ante cualquier problema, {}."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            servidores = json.load(f).get("mcp_servers", {})
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.error(f"No se pudo leer 'mcp_servers' de config.json: {e}")
        return {}

    if not isinstance(servidores, dict):
        logger.error("'mcp_servers' en config.json no es un objeto JSON — se ignora")
        return {}

    validos: Dict[str, Dict[str, Any]] = {}
    for nombre, definicion in servidores.items():
        if not isinstance(nombre, str) or not nombre.strip():
            logger.warning(f"Servidor MCP con nombre inválido, se ignora: {nombre!r}")
            continue
        if not isinstance(definicion, dict):
            logger.warning(f"La definición de '{nombre}' no es un objeto — se ignora")
            continue
        validos[nombre.strip().lower()] = definicion
    return validos


def _nivel_declarado(tool: Dict[str, Any]) -> Tuple[RiskLevel, bool]:
    """Return `(nivel, es_destructiva)` a partir de las anotaciones del servidor.

    Las `annotations` de MCP (`readOnlyHint`, `destructiveHint`, ...) las escribe el
    servidor, así que **solo pueden endurecer, nunca ablandar**: un `readOnlyHint: true`
    NO baja nada a verde. Es el mismo principio de REQ-019.

    Una herramienta marcada destructiva NO se sube a rojo, y es deliberado: rojo exige PIN
    maestro, y sin `ORION_AUTH_PIN` configurado quedaría bloqueada para siempre sin forma
    de destrabarla — el mismo autobloqueo que REQ-019 evitó poniéndole techo amarillo al
    catálogo de la UI. Se queda en amarillo (confirmación en cada uso) y además se la
    excluye de cualquier excepción de canal: una acción destructiva remota se confirma
    sentado frente al PC, nunca por un atajo desde el celular.
    """
    anotaciones = tool.get("annotations")
    destructiva = bool(isinstance(anotaciones, dict) and anotaciones.get("destructiveHint"))
    return RiskLevel.YELLOW, destructiva


def _crear_invoke(servidor: str, nombre_tool: str):
    """Devuelve el callable que `execute_tool()` va a invocar tras pasar el gate.

    Busca el cliente en `_CLIENTES` en cada llamada en vez de capturarlo en la clausura.
    Esa diferencia es la que hace posible la reconexión: si el servidor se cae y se vuelve
    a levantar, basta con reemplazar la entrada del diccionario y todas las herramientas ya
    registradas siguen funcionando sin volver a registrarlas.
    """

    def _invoke(params: Dict[str, Any]) -> str:
        cliente = _CLIENTES.get(servidor) or _reconectar(servidor)
        if cliente is None:
            return f"Error: el servidor '{servidor}' no está disponible."

        try:
            return cliente.call_tool(nombre_tool, params or {})
        except MCPError as e:
            primer_error = e
            logger.warning(f"mcp:{servidor}: falló '{nombre_tool}' ({e}); se reintenta una vez")

        # Un servidor stdio que murió deja el proceso caído para siempre: sin este
        # reintento, TODAS las llamadas siguientes fallarían hasta reiniciar O.R.I.O.N.
        cliente = _reconectar(servidor)
        if cliente is None:
            # Se arrastra el error original: "no se pudo reconectar" a secas esconde la
            # causa real, que es lo único que sirve para diagnosticar.
            return (
                f"Error: '{servidor}' falló ({primer_error}) y no se pudo reconectar."
            )
        try:
            return cliente.call_tool(nombre_tool, params or {})
        except MCPError as e:
            # Se devuelve texto en vez de propagar: `execute_tool()` no atrapa, y una
            # excepción acá tumbaría el turno entero del loop de razonamiento en vez de
            # dejarlo leer el fallo y seguir.
            return f"Error: no se pudo ejecutar '{nombre_tool}' en '{servidor}': {e}"

    return _invoke


def _conectar_cliente(nombre: str, definicion: Dict[str, Any]) -> MCPClient:
    """Crea el transporte, arma el cliente y hace el handshake. Lanza `MCPError` si falla."""
    cliente = MCPClient(
        nombre, crear_transporte(nombre, definicion),
        connect_timeout=float(definicion.get("connect_timeout", 10.0)),
        request_timeout=float(definicion.get("request_timeout", 30.0)),
    )
    cliente.initialize()
    return cliente


def _reconectar(servidor: str) -> Optional[MCPClient]:
    """Rehace la conexión con `servidor` sin volver a registrar sus herramientas.

    No re-registra a propósito: las herramientas ya están puestas y resuelven el cliente
    dinámicamente. Volver a descubrir acá haría que una llamada fallida dispare un
    registro completo, con el catálogo cambiando debajo de un turno en curso — para eso
    está `recargar_servidor()`, que es explícito.

    Con enfriamiento: un servidor que no levanta no puede provocar un intento de
    reconexión por cada herramienta que el modelo invoque.
    """
    ahora = time.monotonic()
    ultimo = _ULTIMO_INTENTO.get(servidor)
    if ultimo is not None and (ahora - ultimo) < SEGUNDOS_ENTRE_RECONEXIONES:
        return None
    _ULTIMO_INTENTO[servidor] = ahora

    definicion = cargar_definiciones().get(servidor)
    if definicion is None:
        logger.error(f"mcp:{servidor}: ya no está declarado en config.json")
        return None

    anterior = _CLIENTES.pop(servidor, None)
    if anterior is not None:
        try:
            anterior.close()
        except Exception as e:
            logger.debug(f"mcp:{servidor}: no se pudo cerrar la conexión anterior: {e}")

    try:
        cliente = _conectar_cliente(servidor, definicion)
    except MCPError as e:
        logger.error(f"mcp:{servidor}: no se pudo reconectar: {e}")
        return None

    _CLIENTES[servidor] = cliente
    logger.info(f"mcp:{servidor}: reconectado")
    return cliente


def _schema_de(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza el `inputSchema` de MCP al `parameters_schema` de `ToolSpec`.

    Un servidor puede omitirlo o mandar algo que no es un objeto; se cae a un schema vacío
    válido en vez de registrar un `ToolSpec` con forma rota que fallaría más tarde, lejos
    de la causa.
    """
    schema = tool.get("inputSchema")
    if isinstance(schema, dict) and schema.get("type") == "object":
        return schema
    return {"type": "object", "properties": {}}


def _habilitar_canales(nombre_registrado: str, servidor: str, destructiva: bool) -> List[str]:
    """Agrega las excepciones de canal declaradas para `servidor`. Return los aplicados.

    Usa `CHANNEL_ACTION_EXCEPTIONS`, el mecanismo que REQ-018 creó exactamente para esto:
    habilitar una acción amarilla puntual en un canal que de otro modo no la tendría, sin
    abrirle el resto. Nunca toca la política general del canal.
    """
    if destructiva:
        logger.warning(
            f"'{nombre_registrado}' está anotada como destructiva por el servidor: no se le "
            f"habilita ningún canal remoto, solo se confirma desde el escritorio."
        )
        return []

    aplicados = []
    for canal_str in canales_permitidos(servidor):
        canal = security_manager.resolve_channel(canal_str)
        if canal.value != canal_str:
            logger.warning(f"Canal '{canal_str}' desconocido en mcp_allowlist.json — se ignora")
            continue
        CHANNEL_ACTION_EXCEPTIONS.add((canal, nombre_registrado))
        aplicados.append(canal_str)
    return aplicados


def registrar_tools(cliente: MCPClient, servidor: str) -> Tuple[int, int]:
    """Descubre las herramientas de `cliente` y registra las permitidas.

    Return `(registradas, rechazadas)`. Rechazada == no estaba en la allow-list o su
    nombre no pudo calificarse; en ambos casos `register_tool()` ya dejó el motivo en el log.
    """
    # El cliente queda como el activo de `servidor` ANTES de registrar nada: los `invoke`
    # lo resuelven por acá en cada llamada, así que registrar herramientas sin dejar el
    # cliente puesto produciría tools que no encuentran a nadie.
    _CLIENTES[servidor] = cliente

    try:
        catalogo = cliente.list_tools()
    except MCPError as e:
        logger.error(f"mcp:{servidor}: no se pudo listar herramientas: {e}")
        return 0, 0

    registradas, rechazadas = 0, 0
    for tool in catalogo:
        nombre_tool = (tool.get("name") or "").strip()
        if not nombre_tool:
            logger.warning(f"mcp:{servidor}: herramienta sin nombre en el catálogo, se ignora")
            rechazadas += 1
            continue

        nivel, destructiva = _nivel_declarado(tool)
        nombre_registrado = nombre_calificado(servidor, nombre_tool)
        spec = ToolSpec(
            name=nombre_registrado,
            description=(tool.get("description") or f"Herramienta '{nombre_tool}' de {servidor}"),
            parameters_schema=_schema_de(tool),
            risk_level=nivel,
            invoke=_crear_invoke(servidor, nombre_tool),
            origin="mcp_remote",
        )
        if not register_tool(spec):
            rechazadas += 1
            continue

        registradas += 1
        canales = _habilitar_canales(nombre_registrado, servidor, destructiva)
        logger.info(
            f"mcp:{servidor}: '{nombre_tool}' registrada como '{nombre_registrado}' "
            f"(canales: {', '.join(canales) if canales else 'solo escritorio'})"
        )
    return registradas, rechazadas


def conectar_servidor(nombre: str, definicion: Dict[str, Any]) -> Optional[MCPClient]:
    """Conecta un servidor y registra sus herramientas permitidas. None si no se pudo."""
    if definicion.get("enabled") is False:
        logger.info(f"mcp:{nombre}: deshabilitado en config.json, no se conecta")
        return None
    try:
        cliente = _conectar_cliente(nombre, definicion)
    except MCPError as e:
        logger.error(f"mcp:{nombre}: no se pudo conectar: {e}")
        return None
    except (TypeError, ValueError) as e:
        logger.error(f"mcp:{nombre}: definición inválida en config.json: {e}")
        return None

    _CLIENTES[nombre] = cliente   # antes de registrar: los invoke resuelven por acá
    registradas, rechazadas = registrar_tools(cliente, nombre)
    if registradas == 0:
        logger.warning(
            f"mcp:{nombre}: conectado pero sin ninguna herramienta habilitada "
            f"({rechazadas} rechazadas). Revisá mcp_allowlist.json."
        )
    return cliente


# ── Recarga en caliente ─────────────────────────────────────────────

def desregistrar_servidor(nombre: str) -> int:
    """Saca del sistema todo lo que aportó `nombre`. Return cuántas herramientas se quitaron.

    Quita las tres cosas que deja un servidor conectado: el cliente, las herramientas del
    registro y sus excepciones de canal. Olvidar la tercera dejaría a `security_manager`
    con permisos vivos apuntando a acciones que ya no existen — inofensivo hoy, pero una
    trampa el día que un nombre se reutilice.
    """
    cliente = _CLIENTES.pop(nombre, None)
    if cliente is not None:
        try:
            cliente.close()
        except Exception as e:
            logger.warning(f"mcp:{nombre}: problema al cerrar: {e}")

    quitadas = _tools_de(nombre)
    for tool in quitadas:
        unregister_tool(tool)
    for entrada in [e for e in CHANNEL_ACTION_EXCEPTIONS if e[1] in quitadas]:
        CHANNEL_ACTION_EXCEPTIONS.discard(entrada)

    _ULTIMO_INTENTO.pop(nombre, None)
    if quitadas:
        logger.info(f"mcp:{nombre}: {len(quitadas)} herramienta(s) desregistrada(s)")
    return len(quitadas)


def recargar_servidor(nombre: str) -> str:
    """Desconecta y vuelve a conectar `nombre`, releyendo config y allow-list. Return resumen.

    Es lo que permite agregar un servidor, cambiar la allow-list o cortar el acceso a algo
    sin reiniciar O.R.I.O.N.
    """
    desregistrar_servidor(nombre)
    definicion = cargar_definiciones().get(nombre.strip().lower())
    if definicion is None:
        return f"'{nombre}' ya no está declarado en config.json: quedó desconectado."

    cliente = conectar_servidor(nombre.strip().lower(), definicion)
    if cliente is None:
        return f"'{nombre}' no se pudo conectar (ver el log)."
    return f"'{nombre}': {len(_tools_de(nombre.strip().lower()))} herramienta(s)."


def recargar() -> Dict[str, str]:
    """Recarga TODOS los servidores. Return {servidor: resumen}."""
    for nombre in list(_CLIENTES):
        desregistrar_servidor(nombre)
    return conectar_todos()


# ── OAuth ───────────────────────────────────────────────────────────

def login_servidor(nombre: str) -> str:
    """Corre el flujo OAuth interactivo para `nombre` y return el resultado en palabras."""
    return login_servidor_detallado(nombre)[1]


def login_servidor_detallado(nombre: str) -> Tuple[bool, str]:
    """Corre el flujo OAuth interactivo para `nombre`. Return `(autorizado, mensaje)`.

    `autorizado` es True solo cuando se obtuvieron y guardaron credenciales nuevas: es lo
    que la pantalla usa para decidir si recarga el servidor (REQ-043). Antes lo deducía
    buscando "autorizado" en el texto, y un servidor llamado "autorizador" bastaba para
    engañarla.

    Antes de abrir el navegador se intenta conectar a propósito: el 401 que devuelve el
    servidor trae la ubicación de su metadata (RFC 9728), y con eso el descubrimiento no
    tiene que adivinar cuál es el servidor de autorización.
    """
    from core import mcp_oauth

    clave = nombre.strip().lower()
    definicion = cargar_definiciones().get(clave)
    if definicion is None:
        return False, f"No hay ningún servidor '{nombre}' en config.json."
    url = (definicion.get("url") or "").strip()
    if not url:
        return False, f"'{nombre}' es un servidor stdio local: no usa OAuth."

    url_metadata = None
    try:
        transporte = crear_transporte(clave, definicion)
        MCPClient(clave, transporte).initialize()
        return False, f"'{nombre}' ya respondió sin pedir autorización: no hace falta loguearse."
    except MCPError:
        url_metadata = getattr(transporte, "url_metadata_oauth", None)
    except Exception as e:
        logger.debug(f"mcp:{clave}: sondeo previo al login falló ({e})")

    try:
        mcp_oauth.login(clave, url, definicion.get("oauth"), url_metadata)
    except mcp_oauth.OAuthError as e:
        return False, f"No se pudo autorizar '{nombre}': {e}"
    return True, f"'{nombre}' autorizado. Recargá con: python -m core.mcp_manager reload {nombre}"


def logout_servidor(nombre: str) -> str:
    """Borra las credenciales guardadas de `nombre`."""
    from core import mcp_oauth

    clave = nombre.strip().lower()
    if mcp_oauth.olvidar(clave):
        return f"Credenciales de '{nombre}' borradas."
    return f"'{nombre}' no tenía credenciales guardadas."


def conectar_todos() -> Dict[str, str]:
    """Conecta todos los servidores declarados. Return {servidor: resumen legible}.

    Nunca lanza: un servidor caído no puede impedir que O.R.I.O.N. arranque.
    """
    resumen: Dict[str, str] = {}
    for nombre, definicion in cargar_definiciones().items():
        try:
            cliente = conectar_servidor(nombre, definicion)
        except Exception as e:
            logger.error(f"mcp:{nombre}: error inesperado al conectar: {e}")
            resumen[nombre] = f"error: {e}"
            continue
        if cliente is None:
            resumen[nombre] = "no conectado"
        else:
            propias = [n for n in _tools_de(nombre)]
            resumen[nombre] = f"{len(propias)} herramienta(s)"
    return resumen


def _tools_de(servidor: str) -> List[str]:
    from agents.tool_registry import list_tool_names

    prefijo = nombre_calificado(servidor, "")
    return [n for n in list_tool_names() if n.startswith(prefijo)]


def probar_servidor(nombre: str) -> str:
    """Conecta, lista y reporta — sin registrar nada. El `mcp doctor --probe` de OpenClaw.

    Guardar una definición no prueba que el servidor responda; esto sí. Se usa para
    diagnosticar antes de confiar en que algo quedó andando.
    """
    definiciones = cargar_definiciones()
    definicion = definiciones.get(nombre.strip().lower())
    if definicion is None:
        disponibles = ", ".join(sorted(definiciones)) or "ninguno"
        return f"No hay ningún servidor '{nombre}' en config.json. Declarados: {disponibles}."

    lineas = [f"Servidor '{nombre}':"]
    try:
        transporte = crear_transporte(nombre, definicion)
        cliente = MCPClient(
            nombre, transporte,
            connect_timeout=float(definicion.get("connect_timeout", 10.0)),
            request_timeout=float(definicion.get("request_timeout", 30.0)),
        )
        info = cliente.initialize()
        version = info.get("version", "")
        lineas.append(f"  conexión: OK ({info.get('name', '?')} {version})".rstrip())
        catalogo = cliente.list_tools()
    except MCPError as e:
        lineas.append(f"  conexión: FALLÓ — {e}")
        return "\n".join(lineas)

    if not catalogo:
        lineas.append("  el servidor no publica ninguna herramienta")
        cliente.close()
        return "\n".join(lineas)

    for capacidad, etiqueta in (("resources", "recurso(s)"), ("prompts", "prompt(s)")):
        if not cliente.soporta(capacidad):
            continue
        try:
            cuantos = len(
                cliente.list_resources() if capacidad == "resources" else cliente.list_prompts()
            )
            lineas.append(f"  también publica {cuantos} {etiqueta}")
        except MCPError as e:
            lineas.append(f"  no se pudieron listar sus {etiqueta}: {e}")

    canales = canales_permitidos(nombre)
    lineas.append(f"  publica {len(catalogo)} herramienta(s):")
    for tool in catalogo:
        nombre_tool = (tool.get("name") or "?").strip()
        if not is_tool_allowed(nombre, nombre_tool):
            lineas.append(f"    - {nombre_tool}: bloqueada (no está en mcp_allowlist.json)")
            continue
        _, destructiva = _nivel_declarado(tool)
        # Se dice canal por canal y no una vez al final: una herramienta destructiva no
        # recibe los canales del servidor, y un resumen general lo ocultaría.
        alcance = "solo escritorio (destructiva)" if destructiva else ", ".join(canales)
        lineas.append(f"    - {nombre_tool}: PERMITIDA — {alcance or 'solo escritorio'}")
    cliente.close()
    return "\n".join(lineas)


def cerrar_todos() -> None:
    """Cierra los servidores conectados. Simetría con `conectar_todos()`."""
    for nombre, cliente in list(_CLIENTES.items()):
        try:
            cliente.close()
        except Exception as e:
            logger.warning(f"mcp:{nombre}: problema al cerrar: {e}")
    _CLIENTES.clear()


def estado() -> Dict[str, List[str]]:
    """Return {servidor: [herramientas registradas]}, para diagnóstico."""
    return {nombre: _tools_de(nombre) for nombre in _CLIENTES}


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    argumentos = sys.argv[1:]

    comando = argumentos[0] if argumentos else ""
    objetivo = argumentos[1] if len(argumentos) > 1 else ""

    if comando == "probe" and objetivo:
        print(probar_servidor(objetivo))
    elif comando == "login" and objetivo:
        print(login_servidor(objetivo))
    elif comando == "logout" and objetivo:
        print(logout_servidor(objetivo))
    elif comando == "reload":
        if objetivo:
            print(recargar_servidor(objetivo))
        else:
            for servidor, detalle in recargar().items():
                print(f"{servidor}: {detalle}")
    elif comando == "list":
        declarados = cargar_definiciones()
        if not declarados:
            print("No hay servidores MCP declarados en config.json ('mcp_servers').")
        for nombre, definicion in declarados.items():
            destino = definicion.get("url") or definicion.get("command") or "?"
            estado_txt = "deshabilitado" if definicion.get("enabled") is False else "habilitado"
            print(f"{nombre}: {destino} ({estado_txt})")
    else:
        print("Uso:\n"
              "  python -m core.mcp_manager list\n"
              "  python -m core.mcp_manager probe  <servidor>\n"
              "  python -m core.mcp_manager login  <servidor>   (OAuth, abre el navegador)\n"
              "  python -m core.mcp_manager logout <servidor>\n"
              "  python -m core.mcp_manager reload [servidor]   (sin reiniciar O.R.I.O.N.)")
