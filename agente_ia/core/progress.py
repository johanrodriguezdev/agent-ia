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
    "task_create": "Anotando el recordatorio",
    "task_list": "Revisando tus tareas",
    "task_complete": "Marcando la tarea",
    "task_complete_all": "Marcando las tareas",
}

#: Longitud máxima del detalle que acompaña al aviso. Es una línea de estado, no un párrafo.
MAX_CHARS_DETALLE = 60


def report_tool(nombre: str, detalle: str = "") -> None:
    """Anuncia el uso de una herramienta con un texto que se entienda.

    `detalle` es el dato concreto —la consulta, la dirección— recortado para que quepa en
    una línea. Se muestra entre comillas para que se distinga del verbo.
    """
    texto = _TEXTOS_POR_HERRAMIENTA.get(nombre, f"Usando {nombre}")

    limpio = " ".join((detalle or "").split())
    if limpio:
        if len(limpio) > MAX_CHARS_DETALLE:
            limpio = limpio[:MAX_CHARS_DETALLE].rstrip() + "…"
        texto = f"{texto}: {limpio}"

    report(texto)
