"""
core/mcp_config.py
Único escritor de la configuración de servidores MCP: `config.json → mcp_servers`,
`config.json → mcp_variables` y `mcp_allowlist.json`.

Antes de REQ-043 el soporte MCP estaba completo por debajo (`core/mcp_client.py`,
`core/mcp_manager.py`, `core/remote_tools_policy.py`, `core/mcp_oauth.py`) pero la única
forma de usarlo era editar dos JSON a mano y correr `python -m core.mcp_manager` en una
consola. Este módulo es lo que permite que el agente declare un servidor por instrucción
("conectate al servidor de Notion, el comando es ...") y que la pantalla de Configuración
lo muestre, lo pruebe, lo apague y guarde sus secretos — sin abrir ningún archivo.

Decisiones:

- **Los secretos nunca viajan por el chat.** En `env` y `headers` solo se aceptan
  referencias `${VARIABLE}`; un valor literal se rechaza y el mensaje dice dónde ponerlo.
  Lo que el usuario le escribe al agente llega al proveedor del modelo: un token ahí es un
  token filtrado. El valor se pega en Configuración → Conexiones (`mcp_variables`) o se
  define como variable de entorno, y `core/mcp_client.py::expandir_secreto()` lo resuelve
  al conectar.
- **Lista cerrada derivada para las variables.** `definir_variable()` solo acepta nombres
  que algún servidor declarado referencie. El slot del bridge que la llama es alcanzable
  desde cualquier script de la página, así que lo que llega no decide qué clave se escribe
  (mismo criterio que `_CONEXIONES` en `ui/webview/bridge.py`).
- **Sin canal de correo, nunca.** `permitir_herramientas()` admite `desktop`, `telegram`,
  `discord` y `voice`; `email`, `api` y `unknown` no son habilitables: la entrada que un
  tercero puede originar no alcanza herramientas amarillas (constraint del proyecto).
- **Escritura atómica de la allow-list**, igual que `core/security_config.py`: un archivo
  a medio escribir es, para `remote_tools_policy.load_allowlist()`, "no se permite nada".
  Es fail-closed, pero dejaría al usuario sin herramientas hasta que alguien lo note.
- **Este módulo no conecta nada por su cuenta.** `aplicar_y_resumir()` delega en
  `mcp_manager.recargar_servidor()` y traduce el resultado a palabras; `listar_servidores()`
  es solo lectura.
"""

import json
import logging
import os
import re
import shlex
import tempfile
from typing import Any, Dict, List, Optional, Sequence

import config_manager
from core import remote_tools_policy as politica
from core.remote_tools_policy import CANALES_POR_DEFECTO, load_allowlist, parse_nombre_calificado

logger = logging.getLogger(__name__)


class MCPConfigRechazada(ValueError):
    """La operación no se hizo; el mensaje dice por qué, en palabras para el usuario."""


#: Canales desde los que se puede habilitar una herramienta remota. `email`, `api` y
#: `unknown` no están a propósito: lo que un desconocido puede originar no alcanza acciones
#: amarillas (ver `project_entrada_no_confiable` y `security-levels.md`).
CANALES_HABILITABLES = ("desktop", "telegram", "discord", "voice")

_PATRON_NOMBRE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_PATRON_REFERENCIA = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
_NOMBRES_RESERVADOS = frozenset({"__proto__", "constructor", "prototype"})

_CLAVE_SERVIDORES = "mcp_servers"
_CLAVE_VARIABLES = "mcp_variables"

#: Dónde se le dice al usuario que ponga un secreto. Se repite en varios mensajes, así que
#: vive en un solo lugar.
_DONDE_VAN_LOS_SECRETOS = (
    "Configuración → Conexiones → Servidores MCP (bloque «Variables»), o como variable de "
    "entorno del sistema"
)


# ── Nombres y referencias ───────────────────────────────────────────

def normalizar_nombre(nombre: Any) -> str:
    """Return el nombre del servidor en minúsculas y validado. Lanza `MCPConfigRechazada`."""
    limpio = str(nombre or "").strip().lower()
    if not limpio:
        raise MCPConfigRechazada("El servidor necesita un nombre.")
    if limpio in _NOMBRES_RESERVADOS or not _PATRON_NOMBRE.match(limpio):
        raise MCPConfigRechazada(
            f"'{limpio}' no sirve como nombre de servidor: letras minúsculas, números, guion "
            f"y guion bajo, empezando por letra y de hasta 40 caracteres."
        )
    return limpio


def _referencia(valor: Any) -> Optional[str]:
    """Return el nombre de la variable si `valor` es `${VARIABLE}`, o None."""
    if not isinstance(valor, str):
        return None
    match = _PATRON_REFERENCIA.match(valor.strip())
    return match.group(1) if match else None


def _validar_solo_referencias(datos: Any, etiqueta: str) -> Dict[str, str]:
    """Return `datos` como dict str→"${VAR}". Un valor literal se rechaza (CA-02)."""
    if datos in (None, "", {}):
        return {}
    if not isinstance(datos, dict):
        raise MCPConfigRechazada(f"'{etiqueta}' tiene que ser un objeto {{nombre: '${{VARIABLE}}'}}.")
    limpios: Dict[str, str] = {}
    for clave, valor in datos.items():
        nombre = str(clave or "").strip()
        if not nombre:
            raise MCPConfigRechazada(f"'{etiqueta}' tiene una entrada sin nombre.")
        if _referencia(valor) is None:
            raise MCPConfigRechazada(
                f"El valor de '{nombre}' en '{etiqueta}' tiene que ser una referencia como "
                f"'${{{nombre.upper()}}}', nunca el secreto escrito. El valor real se pone en "
                f"{_DONDE_VAN_LOS_SECRETOS}: un secreto que pasa por el chat viaja al "
                f"proveedor del modelo."
            )
        limpios[nombre] = str(valor).strip()
    return limpios


# ── config.json → mcp_servers ───────────────────────────────────────

def _servidores_declarados(config: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Return las definiciones válidas de `config.json`, con nombres normalizados."""
    config = config if config is not None else config_manager.load_config()
    crudo = config.get(_CLAVE_SERVIDORES)
    if not isinstance(crudo, dict):
        return {}
    validos: Dict[str, Dict[str, Any]] = {}
    for nombre, definicion in crudo.items():
        if isinstance(nombre, str) and nombre.strip() and isinstance(definicion, dict):
            validos[nombre.strip().lower()] = definicion
    return validos


def _guardar_servidores(config: Dict[str, Any], servidores: Dict[str, Dict[str, Any]]) -> None:
    config[_CLAVE_SERVIDORES] = servidores
    config_manager.save_config(config)


def partir_comando(comando: Any) -> List[str]:
    """Return el comando como lista `[ejecutable, arg, ...]` a partir de una cadena.

    El modelo manda el comando completo en una sola cadena ("npx -y @notionhq/server")
    para que el modal de confirmación lo muestre entero; acá se parte con las reglas de la
    shell (`shlex`, modo POSIX apagado para que una ruta de Windows no pierda sus barras).
    """
    texto = str(comando or "").strip()
    if not texto:
        return []
    try:
        partes = shlex.split(texto, posix=False)
    except ValueError as e:
        raise MCPConfigRechazada(f"No entendí el comando (comillas sin cerrar): {e}") from e
    # En modo no-POSIX las comillas se conservan en el token; se quitan las que envuelven
    # un argumento entero (una ruta con espacios entre comillas), que es para lo que se pusieron.
    return [
        p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p
        for p in partes if p
    ]


def agregar_servidor(
    nombre: Any,
    *,
    command: Any = None,
    args: Any = None,
    url: Any = None,
    env: Any = None,
    headers: Any = None,
) -> Dict[str, Any]:
    """Declara un servidor nuevo en `config.json`. Return la definición guardada.

    `command` puede venir como cadena completa ("npx -y paquete") o como ejecutable más
    `args`. Lanza `MCPConfigRechazada` si el nombre no sirve, ya existe, si se dan
    `command` y `url` a la vez o ninguno, o si `env`/`headers` traen un secreto literal.
    """
    clave = normalizar_nombre(nombre)
    comando_texto = str(command or "").strip()
    url_texto = str(url or "").strip()

    if comando_texto and url_texto:
        raise MCPConfigRechazada("Un servidor se define con un comando (local) o con una URL, no con los dos.")
    if not comando_texto and not url_texto:
        raise MCPConfigRechazada("Necesito el comando que lo arranca (servidor local) o su URL (servidor HTTP).")
    if url_texto and not re.match(r"^https?://", url_texto, re.IGNORECASE):
        raise MCPConfigRechazada(f"La URL '{url_texto}' tiene que empezar por http:// o https://.")

    config = config_manager.load_config()
    servidores = _servidores_declarados(config)
    if clave in servidores:
        raise MCPConfigRechazada(
            f"Ya hay un servidor llamado '{clave}'. Quitalo primero o usá otro nombre."
        )

    definicion: Dict[str, Any] = {"enabled": True}
    if comando_texto:
        partes = partir_comando(comando_texto)
        extra = [str(a) for a in (args or []) if str(a).strip()] if isinstance(args, list) else []
        definicion["command"] = partes[0]
        definicion["args"] = partes[1:] + extra
        variables = _validar_solo_referencias(env, "env")
        if variables:
            definicion["env"] = variables
    else:
        definicion["url"] = url_texto
        cabeceras = _validar_solo_referencias(headers, "headers")
        if cabeceras:
            definicion["headers"] = cabeceras

    servidores[clave] = definicion
    _guardar_servidores(config, servidores)
    logger.info(f"mcp:{clave}: servidor declarado ({'stdio' if comando_texto else 'http'})")
    return dict(definicion)


def quitar_servidor(nombre: Any) -> bool:
    """Borra el servidor de `config.json` y de la allow-list. Return si existía."""
    clave = normalizar_nombre(nombre)
    config = config_manager.load_config()
    servidores = _servidores_declarados(config)
    existia = clave in servidores
    if existia:
        servidores.pop(clave)
        _guardar_servidores(config, servidores)
    permisos = _leer_allowlist_cruda()
    if clave in permisos:
        permisos.pop(clave)
        _escribir_allowlist(permisos)
    if existia:
        logger.info(f"mcp:{clave}: servidor quitado de la configuración")
    return existia


def habilitar_servidor(nombre: Any, activo: bool) -> None:
    """Enciende o apaga un servidor sin borrar su definición."""
    clave = normalizar_nombre(nombre)
    config = config_manager.load_config()
    servidores = _servidores_declarados(config)
    if clave not in servidores:
        raise MCPConfigRechazada(f"No hay ningún servidor '{clave}'.")
    servidores[clave]["enabled"] = bool(activo)
    _guardar_servidores(config, servidores)
    logger.info(f"mcp:{clave}: {'habilitado' if activo else 'deshabilitado'}")


# ── mcp_allowlist.json ──────────────────────────────────────────────

def _leer_allowlist_cruda() -> Dict[str, Any]:
    """Return el JSON tal cual está, para reescribirlo conservando lo de otros servidores.

    A diferencia de `load_allowlist()` (que normaliza y descarta lo inválido), acá se
    conserva todo lo que sea un objeto: reescribir la allow-list para tocar un servidor no
    puede borrarle la entrada a otro por un detalle de forma.
    """
    ruta = politica.MCP_ALLOWLIST_FILE
    if not os.path.exists(ruta):
        return {}
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            crudo = json.load(f)
    except Exception as e:
        logger.error(f"mcp_allowlist.json ilegible, se reescribe desde cero: {e}")
        return {}
    return crudo if isinstance(crudo, dict) else {}


def _escribir_allowlist(datos: Dict[str, Any]) -> None:
    ruta = politica.MCP_ALLOWLIST_FILE
    directorio = os.path.dirname(os.path.abspath(ruta)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".mcp_allowlist_", dir=directorio)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, ruta)   # atómico en Windows y POSIX
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError as e:
            logger.warning(f"No se pudo limpiar el temporal {tmp_path}: {e}")
        raise


def permitir_herramientas(
    nombre: Any,
    patrones: Sequence[Any],
    canales: Optional[Sequence[Any]] = None,
) -> Dict[str, List[str]]:
    """Escribe qué herramientas de `nombre` se aceptan y desde qué canales. Return lo escrito.

    Reemplaza la entrada del servidor (no acumula): lo que el usuario dijo esta vez es la
    lista completa. Una lista vacía se rechaza — para cortar todo está `quitar_servidor()`
    o `habilitar_servidor(False)`, que dicen lo que hacen.
    """
    clave = normalizar_nombre(nombre)
    if clave not in _servidores_declarados():
        raise MCPConfigRechazada(f"No hay ningún servidor '{clave}': primero hay que declararlo.")

    if isinstance(patrones, str):
        patrones = [p for p in re.split(r"[,\s]+", patrones) if p]
    limpios: List[str] = []
    for patron in patrones or []:
        texto = str(patron or "").strip().lower()
        if texto and texto not in limpios:
            limpios.append(texto)
    if not limpios:
        raise MCPConfigRechazada("Necesito al menos un nombre o patrón de herramienta (por ejemplo 'search' o 'read_*').")

    if canales is None or canales == "" or canales == []:
        canales_limpios = list(CANALES_POR_DEFECTO)
    else:
        if isinstance(canales, str):
            canales = [c for c in re.split(r"[,\s]+", canales) if c]
        canales_limpios = []
        for canal in canales:
            texto = str(canal or "").strip().lower()
            if texto not in CANALES_HABILITABLES:
                raise MCPConfigRechazada(
                    f"El canal '{texto}' no se puede habilitar para herramientas remotas. "
                    f"Válidos: {', '.join(CANALES_HABILITABLES)}."
                )
            if texto not in canales_limpios:
                canales_limpios.append(texto)
        if "desktop" not in canales_limpios:
            # El escritorio es donde se confirma: sin él, una herramienta amarilla quedaría
            # habilitada solo en canales que no pueden mostrar el modal.
            canales_limpios.insert(0, "desktop")

    permisos = _leer_allowlist_cruda()
    permisos[clave] = {"tools": limpios, "canales": canales_limpios}
    _escribir_allowlist(permisos)
    logger.info(f"mcp:{clave}: permitidas {limpios} en {canales_limpios}")
    return {"tools": limpios, "canales": canales_limpios}


# ── Variables (secretos) ────────────────────────────────────────────

def variables_referenciadas(config: Optional[Dict[str, Any]] = None) -> Dict[str, List[str]]:
    """Return {VARIABLE: [servidores que la usan]} para todo `${VARIABLE}` declarado."""
    referencias: Dict[str, List[str]] = {}
    for nombre, definicion in _servidores_declarados(config).items():
        for bloque in ("env", "headers"):
            datos = definicion.get(bloque)
            if not isinstance(datos, dict):
                continue
            for valor in datos.values():
                variable = _referencia(valor)
                if variable and nombre not in referencias.setdefault(variable, []):
                    referencias[variable].append(nombre)
    return referencias


def _variables_guardadas(config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    config = config if config is not None else config_manager.load_config()
    datos = config.get(_CLAVE_VARIABLES)
    if not isinstance(datos, dict):
        return {}
    return {str(k): str(v) for k, v in datos.items() if isinstance(k, str) and str(v).strip()}


def valor_de_variable(nombre: str) -> Optional[str]:
    """Return el valor guardado en `config.json → mcp_variables`, o None. Lo usa `mcp_client`.

    El entorno lo consulta el propio `expandir_secreto()` antes de llegar acá: la variable
    de entorno manda sobre el archivo, igual que con las claves de API.
    """
    try:
        return _variables_guardadas().get(str(nombre or "").strip()) or None
    except Exception as e:
        logger.warning(f"No se pudo leer '{_CLAVE_VARIABLES}' de config.json: {e}")
        return None


def origen_de_variable(nombre: str) -> str:
    """Return "entorno", "archivo" o "" — nunca el valor."""
    limpio = str(nombre or "").strip()
    if os.environ.get(limpio):
        return "entorno"
    return "archivo" if _variables_guardadas().get(limpio) else ""


def definir_variable(nombre: Any, valor: Any) -> bool:
    """Guarda el valor de una `${VARIABLE}` que algún servidor referencia. Return si se escribió."""
    limpio = str(nombre or "").strip()
    if limpio not in variables_referenciadas():
        logger.warning(f"definir_variable: '{limpio}' no la usa ningún servidor MCP declarado")
        return False
    texto = str(valor or "").strip()
    if not texto:
        return False
    config = config_manager.load_config()
    variables = _variables_guardadas(config)
    variables[limpio] = texto
    config[_CLAVE_VARIABLES] = variables
    config_manager.save_config(config)
    # El VALOR no se registra nunca: este log acaba en un archivo.
    logger.info(f"mcp: variable '{limpio}' guardada en config.json")
    return True


def borrar_variable(nombre: Any) -> bool:
    """Quita una variable guardada. Return si había algo que quitar."""
    limpio = str(nombre or "").strip()
    config = config_manager.load_config()
    variables = _variables_guardadas(config)
    if limpio not in variables:
        return False
    variables.pop(limpio)
    config[_CLAVE_VARIABLES] = variables
    config_manager.save_config(config)
    logger.info(f"mcp: variable '{limpio}' borrada de config.json")
    return True


# ── Estado legible ──────────────────────────────────────────────────

def destino_legible(definicion: Dict[str, Any]) -> str:
    """Return "npx -y paquete" o la URL: lo que identifica al servidor para una persona."""
    if definicion.get("url"):
        return str(definicion["url"])
    partes = [str(definicion.get("command") or "")] + [str(a) for a in definicion.get("args") or []]
    return " ".join(p for p in partes if p)


def listar_servidores() -> List[Dict[str, Any]]:
    """Return el estado de cada servidor declarado, para el agente y para la pantalla.

    Solo lectura: no conecta ni sondea nada. Nunca incluye el valor de una variable.
    """
    from core import mcp_manager

    config = config_manager.load_config()
    permisos = load_allowlist()
    conectados = mcp_manager.estado()
    filas: List[Dict[str, Any]] = []
    for nombre, definicion in sorted(_servidores_declarados(config).items()):
        entrada = permisos.get(nombre) or {}
        registradas = []
        for calificado in conectados.get(nombre, []):
            partes = parse_nombre_calificado(calificado)
            registradas.append(partes[1] if partes else calificado)

        variables = []
        for bloque in ("env", "headers"):
            datos = definicion.get(bloque)
            if not isinstance(datos, dict):
                continue
            for valor in datos.values():
                variable = _referencia(valor)
                if variable and variable not in [v["nombre"] for v in variables]:
                    variables.append({"nombre": variable, "origen": origen_de_variable(variable)})

        filas.append({
            "nombre": nombre,
            "transporte": "http" if definicion.get("url") else "stdio",
            "destino": destino_legible(definicion),
            "enabled": definicion.get("enabled") is not False,
            "permitidas": list(entrada.get("tools", [])),
            "canales": list(entrada.get("canales", [])),
            "conectado": nombre in conectados,
            "herramientas": sorted(registradas),
            "variables": variables,
        })
    return filas


def aplicar_y_resumir(nombre: Any) -> str:
    """Recarga `nombre` en caliente y return qué pasó, en palabras.

    Es lo que convierte "guardé el JSON" en "quedó andando": conecta, registra lo permitido
    y cuenta. Un servidor que no levanta no lanza — se dice, con el motivo que dejó el log.
    """
    from core import mcp_manager

    clave = normalizar_nombre(nombre)
    definicion = _servidores_declarados().get(clave)
    if definicion is None:
        return f"'{clave}' ya no está declarado."
    if definicion.get("enabled") is False:
        mcp_manager.desregistrar_servidor(clave)
        return f"'{clave}' quedó deshabilitado: sus herramientas ya no están disponibles."

    try:
        mcp_manager.recargar_servidor(clave)
    except Exception as e:
        logger.error(f"mcp:{clave}: error inesperado al recargar: {e}")
        return f"'{clave}' guardado, pero no se pudo conectar: {e}"

    fila = next((f for f in listar_servidores() if f["nombre"] == clave), None)
    if fila is None or not fila["conectado"]:
        return (
            f"'{clave}' quedó guardado pero no respondió al conectar. Probalo con "
            f"mcp_probe_server para ver el error; si necesita una variable, hay que definirla en "
            f"{_DONDE_VAN_LOS_SECRETOS}."
        )

    publicadas = _herramientas_publicadas(clave)
    partes = [f"'{clave}' conectado."]
    if publicadas is not None:
        partes.append(f"Publica {len(publicadas)} herramienta(s): {', '.join(publicadas) or '—'}.")
    if fila["herramientas"]:
        partes.append(
            f"Habilitadas {len(fila['herramientas'])}: {', '.join(fila['herramientas'])} "
            f"(canales: {', '.join(fila['canales']) or 'escritorio'})."
        )
    else:
        partes.append(
            "Ninguna está habilitada todavía: preguntale al usuario cuáles quiere usar y "
            "habilitalas con mcp_allow_tools. Lo que no se nombra no entra."
        )
    faltan = [v["nombre"] for v in fila["variables"] if not v["origen"]]
    if faltan:
        partes.append(
            f"Variables sin definir: {', '.join(faltan)} — se definen en {_DONDE_VAN_LOS_SECRETOS}."
        )
    return " ".join(partes)


def _herramientas_publicadas(clave: str) -> Optional[List[str]]:
    """Return los nombres que publica el servidor conectado, o None si no se pudo listar."""
    from core import mcp_manager
    from core.mcp_client import MCPError

    cliente = mcp_manager._CLIENTES.get(clave)
    if cliente is None:
        return None
    try:
        return sorted((t.get("name") or "").strip() for t in cliente.list_tools() if t.get("name"))
    except MCPError as e:
        logger.warning(f"mcp:{clave}: no se pudieron listar sus herramientas: {e}")
        return None
