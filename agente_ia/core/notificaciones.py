"""
core/notificaciones.py
Avisar de algo que pasó cuando nadie estaba mirando la ventana.

Hasta acá, lo único que la app notificaba al sistema era "sigo ejecutándome en segundo
plano" al cerrarla. Un flujo programado que falla a las tres de la mañana, un ritual
proactivo que corrió, un correo que importa: de todo eso te enterabas solo si abrías la
app y te ponías a mirar. Un asistente que no avisa obliga a vigilarlo, que es exactamente
lo contrario de tener un asistente.

Mismo molde chico que `core/progress.py` y `core/confirmation.py`: un registro global,
quien quiera enterarse se registra, y quien trabaja llama a `notificar()` sin saber si hay
alguien escuchando ni en qué hilo está. Sin nadie registrado —consola, bots, tests— es una
comprobación de `None` y no cuesta nada.

Dos garantías, iguales a las de `progress.py`:

- **Nunca lanza.** Un fallo avisando no puede tumbar lo que se estaba haciendo.
- **Nunca bloquea.** Quien se registra recibe el aviso y devuelve el control; si tiene que
  cruzar de hilo (el escritorio lo hace, con una señal de Qt), es asunto suyo.
"""

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

#: (titulo, mensaje, nivel) -> None. `nivel` es "info" | "ok" | "error".
NotificadorFn = Callable[[str, str, str], None]

NIVELES = ("info", "ok", "error")

_notificador: Optional[NotificadorFn] = None
_lock = threading.Lock()


def register_notifier(fn: Optional[NotificadorFn]) -> None:
    """Registra (o reemplaza) a quien muestra los avisos del sistema."""
    global _notificador
    with _lock:
        _notificador = fn
    logger.info("Notificador %s", "registrado" if fn else "retirado")


def clear_notifier() -> None:
    """Retira el notificador. Lo usan el cierre de la aplicación y los tests."""
    register_notifier(None)


def hay_notificador() -> bool:
    """¿Hay alguien mostrando los avisos ahora mismo?

    Lo consulta quien tenga un camino propio para avisar (el recordatorio de una tarea sabe
    levantar un globo de Windows por su cuenta) y no quiera avisar dos veces si la ventana
    ya lo va a mostrar.
    """
    with _lock:
        return _notificador is not None


def notificar(titulo: str, mensaje: str = "", nivel: str = "info") -> None:
    """Avisa de algo que pasó. Silencioso si nadie escucha."""
    titulo = (titulo or "").strip()
    if not titulo:
        return
    if nivel not in NIVELES:
        nivel = "info"

    with _lock:
        notificador = _notificador
    if notificador is None:
        logger.info("aviso sin destinatario: %s — %s", titulo, mensaje)
        return

    try:
        notificador(titulo, (mensaje or "").strip(), nivel)
    except Exception as e:
        logger.error(f"el notificador falló al mostrar '{titulo}': {e}")
