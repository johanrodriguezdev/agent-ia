"""
ui/webview/mapa_conexiones.py
REQ-052 — el Mapa de conexiones: qué tiene conectado el agente, en un solo lugar.

La pantalla «Mapa» de la barra superior dibuja al agente en el centro y, alrededor, los
modelos con los que responde, los canales por los que se le puede hablar, los servidores
MCP que le prestan herramientas y los flujos que aprendió. Este módulo arma los DATOS
de ese dibujo; el dibujo lo hace `frontend/js/map_panel.js`.

Reglas:
- **Nunca un secreto.** Se dice si una clave está puesta y de dónde sale
  (`config_manager.origen_de_credencial`), nunca su valor. Lo mismo con las variables de
  los servidores MCP (`mcp_config.listar_servidores` ya viene sin valores). Un test lo
  fija: el JSON completo no contiene ninguna credencial configurada.
- **Solo lectura.** No conecta, no sondea, no arranca nada: cuenta lo que hay. Lo único
  con costo es mirar los procesos (¿hay un bot de Telegram corriendo?), y eso lo hace
  `telegram_launcher` con `psutil`, así que el bridge lo llama fuera del hilo de la GUI.
- **Texto para `textContent`.** Todo lo que sale de acá lo inserta JS como texto (§10.1
  de REQ-015): nombres de servidores y flujos vienen de la configuración o de un comando
  dictado, nunca son HTML de confianza.
"""

import logging
from typing import Any, Dict, List

import config_manager

logger = logging.getLogger(__name__)

#: Los proveedores de modelos, con la credencial que los enciende. El orden es el de la
#: pantalla de Claves.
_PROVEEDORES = (
    ("deepseek", "DeepSeek", "deepseek_api_key"),
    ("openrouter", "OpenRouter", "openrouter_api_key"),
    ("anthropic", "Claude", "anthropic_api_key"),
    ("openai", "OpenAI", "openai_api_key"),
    ("gemini", "Gemini", "gemini_api_key"),
)

#: Estados posibles de un nodo, de más a menos vivo. El JS los pinta con el color del
#: tema: `activo` verde, `configurado` acento, `inactivo` gris, `error` rojo.
ESTADOS = ("activo", "configurado", "inactivo", "error")


def _nodo(id_: str, label: str, estado: str, detalle: str = "", **extra: Any) -> Dict[str, Any]:
    if estado not in ESTADOS:
        raise ValueError(f"estado de nodo desconocido: {estado!r}")
    return {"id": id_, "label": label, "estado": estado, "detalle": detalle, **extra}


# ---------------------------------------------------------------------------- modelos

def _modelos() -> List[Dict[str, Any]]:
    activo = config_manager.get_ai_provider()
    modelo_activo = config_manager.get_ai_model()
    filas = []
    for pid, label, clave in _PROVEEDORES:
        origen = config_manager.origen_de_credencial(clave)
        if pid == activo and origen:
            estado, detalle = "activo", f"responde ahora · {modelo_activo}" if modelo_activo else "responde ahora"
        elif origen:
            estado, detalle = "configurado", "clave puesta" + (" (entorno)" if origen == "entorno" else "")
        elif pid == activo:
            estado, detalle = "error", "elegido, pero sin clave"
        else:
            estado, detalle = "inactivo", "sin clave"
        filas.append(_nodo(pid, label, estado, detalle, activo=pid == activo))
    return filas


# ---------------------------------------------------------------------------- canales

def _telegram(sesiones_terminal: List[Dict[str, Any]]) -> Dict[str, Any]:
    from channels import telegram_launcher

    if not config_manager.origen_de_credencial("telegram_token"):
        return _nodo("telegram", "Telegram", "inactivo", "sin token del bot")
    if any(s.get("titulo") == "Telegram" for s in sesiones_terminal):
        return _nodo("telegram", "Telegram", "activo", "bot corriendo en la terminal")
    try:
        if telegram_launcher._ya_hay_uno_corriendo():
            return _nodo("telegram", "Telegram", "activo", "bot corriendo aparte")
    except Exception as e:
        logger.warning(f"Mapa: no se pudo mirar si el bot de Telegram corre: {e}")
    if not config_manager.get_telegram_autostart():
        return _nodo("telegram", "Telegram", "configurado", "token puesto · no arranca solo")
    return _nodo("telegram", "Telegram", "configurado", "token puesto · sin proceso")


def _discord() -> Dict[str, Any]:
    if not config_manager.origen_de_credencial("discord_token"):
        return _nodo("discord", "Discord", "inactivo", "sin token del bot")
    return _nodo("discord", "Discord", "configurado", "token puesto · se lanza aparte")


def _correo() -> Dict[str, Any]:
    from core import email_capabilities, email_commands, email_reader

    try:
        cuentas = email_reader.cargar_cuentas()
    except Exception as e:
        logger.warning(f"Mapa: no se pudieron leer las cuentas de correo: {e}")
        return _nodo("email", "Correo", "error", "configuración ilegible")
    if not cuentas:
        return _nodo("email", "Correo", "inactivo", "sin cuenta configurada")
    capacidades = email_capabilities.cargar()
    encendidas = [k for k, v in capacidades.items() if v]
    partes = [f"{len(cuentas)} cuenta{'s' if len(cuentas) != 1 else ''}"]
    if email_commands.esta_activa():
        partes.append("atiende órdenes")
    if "send" in encendidas:
        partes.append("puede enviar")
    return _nodo("email", "Correo", "activo", " · ".join(partes), capacidades=encendidas)


def _voz(wake_state: str) -> Dict[str, Any]:
    textos = {
        "LISTENING_WAKE": ("activo", "esperando la palabra de activación"),
        "AWAKE": ("activo", "escuchando"),
        "RECONNECTING": ("error", "sin micrófono, reintentando"),
    }
    estado, detalle = textos.get(wake_state, ("inactivo", "manos libres apagado"))
    return _nodo("voice", "Voz", estado, detalle)


def _canales(wake_state: str, sesiones_terminal: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        _nodo("desktop", "Escritorio", "activo", "esta ventana"),
        _voz(wake_state),
        _telegram(sesiones_terminal),
        _discord(),
        _correo(),
    ]


# ---------------------------------------------------------------------------- MCP y flujos

def _servidores_mcp() -> List[Dict[str, Any]]:
    from core.mcp_config import listar_servidores

    filas = []
    for s in listar_servidores():
        if not s["enabled"]:
            estado, detalle = "inactivo", "apagado"
        elif s["conectado"]:
            n = len(s["herramientas"])
            estado = "activo"
            detalle = f"{n} herramienta{'s' if n != 1 else ''} habilitada{'s' if n != 1 else ''}"
            if not n:
                detalle = "conectado · nada habilitado todavía"
        elif any(not v["origen"] for v in s["variables"]):
            faltan = [v["nombre"] for v in s["variables"] if not v["origen"]]
            estado, detalle = "error", "falta " + ", ".join(faltan)
        else:
            estado, detalle = "error", "no conectó"
        filas.append(_nodo(
            s["nombre"], s["nombre"], estado, detalle,
            transporte=s["transporte"], destino=s["destino"],
            herramientas=list(s["herramientas"]), permitidas=list(s["permitidas"]),
            canales=list(s["canales"]),
        ))
    return filas


def _flujos() -> List[Dict[str, Any]]:
    from core.flows import TERMINALES, flow_store

    filas = []
    for flujo in flow_store.listar():
        if flujo.estado in ("corriendo", "esperando"):
            estado = "activo"
        elif flujo.estado == "fallido":
            estado = "error"
        elif flujo.horario:
            estado = "configurado"
        else:
            estado = "inactivo"
        n = len(flujo.pasos)
        detalle = f"{n} paso{'s' if n != 1 else ''}"
        if flujo.horario:
            detalle += f" · {flujo.horario}"
        if flujo.estado not in TERMINALES and flujo.paso_actual:
            detalle += f" · en el paso {flujo.paso_actual}"
        filas.append(_nodo(str(flujo.id), flujo.nombre, estado, detalle, estado_flujo=flujo.estado))
    return filas


# ---------------------------------------------------------------------------- todo junto

def construir(wake_state: str = "INACTIVE",
              sesiones_terminal: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """Return el mapa completo. Cada bloque se protege solo: si uno falla, los demás salen.

    `wake_state` y `sesiones_terminal` los pasa el bridge porque son estado de la GUI
    (`gui_state.WAKE_STATE`, `terminal_manager.listado()`), no de la configuración.
    """
    from core.autonomy import estado as estado_autonomia

    mapa: Dict[str, Any] = {
        "agente": {
            "nombre": config_manager.get_agent_name(),
            "proveedor": config_manager.get_ai_provider(),
            "modelo": config_manager.get_ai_model(),
            "autonomia": {"nivel": "normal", "activo": False},
        },
        "modelos": [], "canales": [], "mcp": [], "flujos": [],
        "terminales": len(sesiones_terminal or []),
    }
    try:
        mapa["agente"]["autonomia"] = estado_autonomia()
    except Exception as e:
        logger.warning(f"Mapa: sin estado de autonomía: {e}")
    for clave, fabrica in (
        ("modelos", _modelos),
        ("canales", lambda: _canales(wake_state, sesiones_terminal or [])),
        ("mcp", _servidores_mcp),
        ("flujos", _flujos),
    ):
        try:
            mapa[clave] = fabrica()
        except Exception as e:
            logger.error(f"Mapa: no se pudo armar el bloque '{clave}': {e}")
    return mapa


# ---------------------------------------------------------------------------- para el agente

_TITULOS = (("modelos", "Modelos"), ("canales", "Canales"), ("mcp", "Servidores MCP"),
            ("flujos", "Flujos"))
_MARCAS = {"activo": "●", "configurado": "◐", "inactivo": "○", "error": "✕"}


def resumen_para_modelo(mapa: Dict[str, Any]) -> str:
    """Return el mapa como texto, para que el agente conteste «¿qué tenés conectado?».

    Mismo contenido que dibuja el panel (y por eso mismas garantías: sin secretos). Una
    línea por nodo con su estado y su detalle; el modelo redacta a partir de esto.
    """
    agente = mapa.get("agente", {})
    cabecera = f"{agente.get('nombre', 'Agente')} responde con {agente.get('proveedor') or '?'}"
    if agente.get("modelo"):
        cabecera += f" · {agente['modelo']}"
    autonomia = agente.get("autonomia") or {}
    if autonomia.get("activo"):
        cabecera += f" · modo autonomía: {autonomia.get('nivel')}"
    lineas = [cabecera]
    for clave, titulo in _TITULOS:
        nodos = mapa.get(clave) or []
        lineas.append(f"\n{titulo}:")
        if not nodos:
            lineas.append("  (ninguno)")
        for n in nodos:
            detalle = f" — {n['detalle']}" if n.get("detalle") else ""
            lineas.append(f"  {_MARCAS.get(n['estado'], '?')} {n['label']}: {n['estado']}{detalle}")
    if mapa.get("terminales"):
        lineas.append(f"\nTerminales abiertas: {mapa['terminales']}")
    lineas.append("\n(● activo · ◐ configurado · ○ inactivo · ✕ con problema)")
    return "\n".join(lineas)
