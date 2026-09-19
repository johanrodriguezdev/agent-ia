"""
core/cancelacion.py
Poder frenar un turno que ya está en marcha.

Hasta acá, entre que mandabas un mensaje y llegaba la respuesta no había salida: el
composer se bloqueaba y solo quedaba esperar. Si el pedido salió mal, o el agente se metió
en una búsqueda de cuarenta segundos que ya no interesa, la única opción era aguantar.

El diseño es el mismo molde chico de `core/progress.py` y `core/confirmation.py`: un
registro global, sin objetos que viajen por veinte firmas de funciones. Quien trabaja
pregunta `esta_cancelado()` en los puntos donde parar es seguro; quien manda llama a
`cancelar()`.

**Cancelación COOPERATIVA, no forzada.** No se mata ningún hilo ni se interrumpe una
llamada HTTP a mitad: eso dejaría archivos a medio escribir y estructuras a medio
actualizar. Lo que se hace es marcar el turno y que el trabajo se detenga en el próximo
punto seguro — entre dos resolvers, entre dos llamadas al modelo, antes de ejecutar la
siguiente herramienta. En la práctica, el corte llega en menos de un segundo salvo que
justo esté esperando la respuesta del modelo, que puede tardar lo suyo.

Por eso la interfaz NO espera: al pedir el stop se desbloquea sola, y si la respuesta del
turno cancelado llega igual, se descarta (ver `Bridge._on_resolve_done`). Cancelar tiene
que sentirse instantáneo aunque por debajo no lo sea.

**Los turnos se identifican.** Sin identificador, un stop tardío del turno anterior
cancelaría el siguiente, que ya nada tiene que ver. Cada turno abre el suyo con
`nuevo_turno()` y `cancelar(turno_id)` solo aplica si coincide con el que está corriendo.
"""

import itertools
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_contador = itertools.count(1)

_turno_actual: Optional[int] = None
_turno_cancelado: Optional[int] = None


class TurnoCancelado(Exception):
    """El turno se canceló mientras se resolvía.

    La levantan los puntos de control que no pueden devolver un resultado parcial con
    sentido. Quien la reciba debe abandonar el turno sin escribir nada al historial.
    """


def nuevo_turno() -> int:
    """Abre un turno cancelable y devuelve su identificador."""
    global _turno_actual
    with _lock:
        _turno_actual = next(_contador)
        return _turno_actual


def cerrar_turno(turno_id: Optional[int] = None) -> None:
    """Cierra el turno: a partir de acá `esta_cancelado()` vuelve a ser False.

    Se llama al terminar la resolución, salga bien o mal. Sin esto, una cancelación
    quedaría pegada y el turno siguiente arrancaría creyéndose cancelado.
    """
    global _turno_actual, _turno_cancelado
    with _lock:
        if turno_id is not None and _turno_actual != turno_id:
            return
        _turno_actual = None
        _turno_cancelado = None


def cancelar(turno_id: Optional[int] = None) -> bool:
    """Pide frenar el turno en curso. Return True si había uno para frenar.

    Con `turno_id`, solo cancela si es el que está corriendo — así un stop que llega tarde
    no se lleva puesto al turno siguiente.
    """
    global _turno_cancelado
    with _lock:
        if _turno_actual is None:
            return False
        if turno_id is not None and turno_id != _turno_actual:
            logger.info("stop de un turno viejo (%s), el actual es %s: se ignora",
                        turno_id, _turno_actual)
            return False
        _turno_cancelado = _turno_actual
    logger.info("turno %s cancelado por el usuario", _turno_cancelado)
    return True


def esta_cancelado(turno_id: Optional[int] = None) -> bool:
    """¿Hay que abandonar? Barato: solo mira dos enteros bajo un lock."""
    with _lock:
        if _turno_cancelado is None:
            return False
        if turno_id is not None:
            return turno_id == _turno_cancelado
        return _turno_cancelado == _turno_actual


def abortar_si_cancelado(donde: str = "") -> None:
    """Punto de control: levanta `TurnoCancelado` si el usuario pidió parar.

    `donde` es solo para el log — sirve para saber en qué punto se cortó de verdad.
    """
    if esta_cancelado():
        logger.info("turno abandonado%s", f" en {donde}" if donde else "")
        raise TurnoCancelado(donde or "cancelado por el usuario")
# ── Turnos remotos (REQ-047) ──────────────────────────────────────────────────────────
#
# Lo de arriba es UN turno de proceso: el del escritorio, que tiene un botón de detener. Un
# canal remoto es otra cosa: varios usuarios, cada uno con su mensaje en curso en su propio
# hilo, y cada uno tiene que poder frenar EL SUYO con `/detener` sin tocar el de nadie más
# ni el del escritorio. Por eso acá los turnos se identifican por una clave
# (`canal:usuario`) además del número. El diseño es el mismo: cooperativo, con puntos de
# control, y un stop tardío no se lleva puesto al turno siguiente de la misma clave.

_remotos_en_curso: dict[str, int] = {}
_remotos_cancelados: set[int] = set()


def clave_remota(canal, user_id: str) -> str:
    """Return la clave con la que se identifica el turno de un usuario en un canal."""
    valor = getattr(canal, "value", canal)
    return f"{str(valor or '').strip().lower()}:{str(user_id or '').strip()}"


def abrir_turno_remoto(clave: str) -> int:
    """Abre (o reemplaza) el turno en curso de `clave` y devuelve su identificador."""
    with _lock:
        turno_id = next(_contador)
        anterior = _remotos_en_curso.get(clave)
        if anterior is not None:
            _remotos_cancelados.discard(anterior)
        _remotos_en_curso[clave] = turno_id
        return turno_id


def cerrar_turno_remoto(clave: str, turno_id: int) -> None:
    """Cierra el turno si sigue siendo el de `clave`; olvida su cancelación."""
    with _lock:
        if _remotos_en_curso.get(clave) == turno_id:
            del _remotos_en_curso[clave]
        _remotos_cancelados.discard(turno_id)


def cancelar_remoto(clave: str) -> bool:
    """Pide frenar el turno en curso de `clave`. Return True si había uno."""
    with _lock:
        turno_id = _remotos_en_curso.get(clave)
        if turno_id is None:
            return False
        _remotos_cancelados.add(turno_id)
    logger.info("turno remoto %s (%s) cancelado por el usuario", turno_id, clave)
    return True


def esta_cancelado_remoto(turno_id: int) -> bool:
    with _lock:
        return turno_id in _remotos_cancelados


def abortar_si_cancelado_remoto(turno_id: int, donde: str = "") -> None:
    """Punto de control para un turno remoto: levanta `TurnoCancelado` si se pidió parar."""
    if esta_cancelado_remoto(turno_id):
        logger.info("turno remoto %s abandonado%s", turno_id, f" en {donde}" if donde else "")
        raise TurnoCancelado(donde or "detenido por el usuario")


def control_remoto(turno_id: int):
    """Return el callable `(donde) -> None` que `reasoning_loop.ejecutar_vuelta` usa como
    punto de control entre herramientas para un turno remoto."""
    return lambda donde="": abortar_si_cancelado_remoto(turno_id, donde)
