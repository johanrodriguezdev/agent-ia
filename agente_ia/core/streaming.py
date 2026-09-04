"""
core/streaming.py
Ver la respuesta mientras se escribe, en vez de esperarla entera.

Hasta acá, entre la pregunta y la respuesta había tres puntos y una línea de progreso: el
texto aparecía completo de golpe, después de diez o quince segundos. La respuesta tarda lo
mismo con streaming o sin él; lo que cambia es que se empieza a leer al segundo, y eso es
casi todo lo que uno entiende por "rápido".

Mismo molde chico que `core/progress.py` y `core/notificaciones.py`: un sumidero global que
registra quien quiera ver los pedazos, y el proveedor los emite sin saber si hay alguien.
Con esto, `generate_response()` y todos sus llamadores conservan la firma que ya tenían —
no hay un `on_chunk` atravesando quince funciones.

**Solo se activa donde tiene sentido.** El sumidero lo registra el escritorio para el turno
en curso y lo retira al terminar. Sin sumidero —consola, Telegram, tests, resúmenes
internos, cualquier llamada al modelo que no sea "contestarle al usuario ahora"— el
proveedor usa el camino de siempre, sin streaming.

**Nunca cambia el resultado.** El texto que devuelve el proveedor es el mismo con streaming
o sin él: los pedazos son un adelanto para la pantalla, no la fuente de la verdad. Si el
streaming falla a mitad, el proveedor reintenta la llamada normal (ver
`ai/llm_provider.py`) y el usuario ve la respuesta completa igual.
"""

import logging
import threading
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

logger = logging.getLogger(__name__)

#: (pedazo_de_texto) -> None. Se llama desde el hilo que esté hablando con el modelo.
SinkFn = Callable[[str], None]

_sink: Optional[SinkFn] = None
_lock = threading.Lock()

#: Permiso POR HILO y por tramo de codigo. No alcanza con tener un sumidero registrado: en
#: un mismo turno el sistema le habla al modelo varias veces por cosas que NO son la
#: respuesta (resumir la memoria, reescribir una repregunta, leer una captura, resumir un
#: correo). Sin este permiso, ese texto se colaria en la burbuja del chat y desapareceria
#: al llegar la respuesta de verdad. Por defecto nadie transmite: hay que pedirlo.
_local = threading.local()


def register_sink(fn: Optional[SinkFn]) -> None:
    """Registra (o reemplaza) a quien recibe los pedazos de la respuesta."""
    global _sink
    with _lock:
        _sink = fn


def clear_sink() -> None:
    """Retira el sumidero. Se llama al terminar cada turno, salga bien o mal."""
    register_sink(None)


@contextmanager
def permitido() -> Iterator[None]:
    """Marca el tramo de codigo cuya salida SI es la respuesta al usuario.

    Lo usan los dos caminos conversacionales (`core/reasoning_loop.py` y
    `ai/claude_brain.py`) alrededor de su llamada al modelo. Todo lo demas —resumenes,
    clasificacion, herramientas que a su vez consultan al modelo— queda afuera y no
    transmite, aunque corra en el mismo turno y en el mismo hilo.
    """
    anterior = getattr(_local, "activo", False)
    _local.activo = True
    try:
        yield
    finally:
        _local.activo = anterior


def hay_sink() -> bool:
    """¿Hay alguien esperando ver ESTA respuesta escribirse?

    Lo consulta el proveedor para decidir si pide la respuesta en streaming: hacen falta
    las dos cosas, un sumidero registrado y el permiso del tramo actual.
    """
    if not getattr(_local, "activo", False):
        return False
    with _lock:
        return _sink is not None


def emitir(pedazo: str) -> None:
    """Entrega un pedazo de respuesta. Silencioso si nadie escucha, nunca lanza."""
    if not pedazo:
        return
    with _lock:
        sink = _sink
    if sink is None:
        return
    try:
        sink(pedazo)
    except Exception as e:
        # Un fallo pintando la respuesta no puede tumbar la respuesta.
        logger.error(f"el sumidero de streaming falló: {e}")
