"""
core/progress.py
Canal para contar qué está haciendo el agente mientras lo hace.

Hasta aquí, entre que enviabas un mensaje y llegaba la respuesta solo había tres puntos
suspensivos. Si la respuesta tardaba diez segundos porque estaba buscando en internet y
leyendo dos páginas, se veía igual que si estuviera colgado. La diferencia entre "está
pensando" y "se ha caído" no estaba en ninguna parte.

El diseño es deliberadamente pequeño. Un único registro de callbacks, como
`core/confirmation.py`: quien quiera enterarse se registra, y quien trabaja llama a
`report()` sin saber si hay alguien escuchando. Sin nadie registrado —consola, Telegram,
tests— `report()` es una comprobación de `None` y no cuesta nada.

Dos garantías que hacen que se pueda llamar desde cualquier sitio sin pensarlo:

- **Nunca lanza.** Un fallo contando lo que se hace jamás puede tumbar lo que se está
  haciendo. Cualquier excepción del reportero se registra y se traga.
- **Nunca bloquea.** El reportero recibe el mensaje y devuelve el control de inmediato; si
  necesita cruzar de hilo (el webview lo hace, con una señal de Qt), es asunto suyo.
"""

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

#: (mensaje) -> None. Se llama desde el hilo que esté trabajando, sea cual sea.
ReporterFn = Callable[[str], None]

_reporter: Optional[ReporterFn] = None
_lock = threading.Lock()


def register_reporter(fn: Optional[ReporterFn]) -> None:
    """Registra (o reemplaza) el destinatario de los avisos de progreso."""
    global _reporter
    with _lock:
        _reporter = fn
    logger.info("Reportero de progreso %s", "registrado" if fn else "retirado")


def clear_reporter() -> None:
    """Retira el reportero. Lo usan el cierre de la aplicación y los tests."""
    register_reporter(None)


def report(mensaje: str) -> None:
    """Cuenta qué se está haciendo ahora mismo. Silencioso si nadie escucha."""
    if not mensaje:
        return

    with _lock:
        reporter = _reporter
    if reporter is None:
        return

    try:
        reporter(mensaje)
    except Exception as e:
        # Contar lo que se hace no puede romper lo que se hace.
        logger.warning(f"El reportero de progreso falló con '{mensaje[:40]}': {e}")


# ─────────────────────────────────────────────
#  Traducción de nombres técnicos a algo legible
# ─────────────────────────────────────────────

#: Qué mostrar por cada herramienta. El nombre técnico (`web_search`) no le dice nada a
#: nadie; "Buscando en internet" sí. Una herramienta que no esté aquí cae en el texto
#: genérico, que sigue siendo mejor que el silencio.
_TEXTOS_POR_HERRAMIENTA = {
    "web_search": "Buscando en internet",
    "web_read": "Leyendo la página",
    "wikipedia_search": "Consultando Wikipedia",
    "research": "Investigando",
    "http_request": "Consultando un servicio web",
    "task_create": "Anotando el recordatorio",
    "task_list": "Revisando tus tareas",
    "task_complete": "Marcando la tarea",
    "task_complete_all": "Marcando las tareas",
    # REQ-053 — el resto de lo que el agente hace seguido. Antes todo esto salía como
    # "Usando file_read", que en la lista de pasos de la respuesta no le dice nada a nadie.
    "file_read": "Leyendo el archivo",
    "image_look": "Mirando la imagen",   # REQ-062
    "file_list": "Mirando la carpeta",
    "file_search": "Buscando archivos",
    "file_write": "Escribiendo el archivo",
    "file_create": "Creando el archivo",
    "file_edit": "Editando el archivo",
    "file_delete": "Borrando el archivo",
    "file_move": "Moviendo el archivo",
    "git_status": "Mirando el estado de git",
    "git_diff": "Mirando los cambios",
    "git_log": "Mirando el historial de git",
    "code_index": "Indexando el código",
    "code_search": "Buscando en el código",
    "project_tree": "Mirando la estructura del proyecto",
    "project_run": "Ejecutando en el proyecto",
    "project_start": "Arrancando el proceso",
    "project_output": "Leyendo la salida del proceso",
    "project_stop": "Deteniendo el proceso",
    "terminal_run_command": "Ejecutando en la terminal",
    "terminal_read_output": "Leyendo la terminal",
    "browser_open": "Abriendo en el navegador",
    "browser_page": "Mirando la página abierta",
    "browser_text": "Leyendo la página abierta",
    "browser_act": "Actuando en el navegador",
    "browser_tabs": "Mirando las pestañas",
    "pc_look": "Mirando la pantalla",
    "pc_screenshot": "Tomando una captura",
    "pc_find": "Buscando en la pantalla",
    "pc_click": "Haciendo click",
    "pc_type": "Escribiendo",
    "pc_key": "Pulsando teclas",
    "pc_act": "Actuando en la pantalla",
    "document_create": "Creando el documento",
    "document_edit": "Editando el documento",
    "document_inspect": "Mirando el documento",
    "document_to_pdf": "Convirtiendo a PDF",
    "spreadsheet_create": "Creando la hoja de cálculo",
    "presentation_create": "Creando la presentación",
    "intent_create": "Aprendiendo el flujo",
    "intent_list": "Revisando los flujos",
    "intent_cancel": "Cancelando el flujo",
    "mcp_list_servers": "Revisando los servidores MCP",
    "mcp_probe_server": "Probando el servidor MCP",
    "mcp_add_server": "Declarando el servidor MCP",
    "mcp_allow_tools": "Habilitando herramientas MCP",
    "connection_map": "Mirando qué hay conectado",
    "chat_project_list": "Revisando los proyectos",
    "chat_project_create": "Creando el proyecto",
    "chat_project_assign_current": "Guardando el chat en el proyecto",
}

#: Prefijo con el que `core/mcp_manager.py` registra las herramientas remotas:
#: `mcp__servidor__tool`. Se parte por el primer `__` (el nombre del servidor no puede
#: llevarlo, ver `core/mcp_config.py`).
_PREFIJO_MCP = "mcp__"


def _texto_de_herramienta(nombre: str) -> str:
    """Return el verbo legible de una herramienta, local o remota."""
    if nombre in _TEXTOS_POR_HERRAMIENTA:
        return _TEXTOS_POR_HERRAMIENTA[nombre]
    if nombre.startswith(_PREFIJO_MCP) and "__" in nombre[len(_PREFIJO_MCP):]:
        servidor, herramienta = nombre[len(_PREFIJO_MCP):].split("__", 1)
        return f"Consultando {servidor}: {herramienta}"
    return f"Usando {nombre}"

#: Longitud máxima del detalle que acompaña al aviso. Es una línea de estado, no un párrafo.
MAX_CHARS_DETALLE = 60


def report_tool(nombre: str, detalle: str = "") -> None:
    """Anuncia el uso de una herramienta con un texto que se entienda.

    `detalle` es el dato concreto —la consulta, la dirección— recortado para que quepa en
    una línea. Se muestra entre comillas para que se distinga del verbo.
    """
    texto = _texto_de_herramienta(nombre)

    limpio = " ".join((detalle or "").split())
    if limpio:
        if len(limpio) > MAX_CHARS_DETALLE:
            limpio = limpio[:MAX_CHARS_DETALLE].rstrip() + "…"
        texto = f"{texto}: {limpio}"

    report(texto)
