"""
core/warmup.py
Carga en segundo plano lo que tarda, mientras el usuario todavía no ha preguntado nada.

El borrador de progreso destapó esto: entre "Entendiendo lo que me pides" y "Pensando"
había un hueco de dieciséis segundos que nadie había medido nunca, porque hasta ahora ese
tramo se veía igual que el resto de la espera. Al desglosarlo, lo que se carga la primera
vez que alguien pregunta algo es:

    clasificador de intenciones (scikit-learn + modelo)     ~4.6 s
    gestor de skills                                        ~0.4 s
    torch                                                  ~10.8 s
    modelo de embeddings (sentence-transformers)           ~50.6 s

Más de un minuto, pagado íntegramente en la primera pregunta del usuario. Y no porque el
sistema sea lento: clasificar una frase, una vez cargado el modelo, tarda **dos
milisegundos**. Es todo coste de arranque, colocado en el peor momento posible.

Este módulo lo mueve a donde corresponde: un hilo que arranca con la aplicación y va
cargando mientras el usuario abre la ventana, lee el saludo y escribe su primer mensaje. No
hace nada nuevo — solo lo hace antes.

Garantías:

- **No bloquea.** Hilo daemon; si la aplicación se cierra a mitad, no la retiene.
- **No cambia el comportamiento.** Cada módulo conserva su carga perezosa. Si el usuario
  pregunta antes de que termine, espera lo que falte, exactamente como hoy.
- **No puede romper el arranque.** Un fallo aquí se registra y ya: lo peor que pasa es que
  se vuelva a la situación anterior.
"""

import logging
import threading
import time
from typing import Callable, List, Tuple

logger = logging.getLogger(__name__)

_hilo: threading.Thread = None
_terminado = threading.Event()
#: Protege el arranque: dos llamadas casi simultaneas veian ambas `is_alive() == False`
#: -el hilo aun no habia empezado- y creaban dos hilos precargando lo mismo a la vez.
_arranque_lock = threading.Lock()


def _cargar_clasificador() -> None:
    from intent.classifier import classify_command

    # Clasificar una frase corta fuerza la carga real del modelo, no solo el import.
    classify_command("hola")


def _cargar_skills() -> None:
    from skills.skill_manager import skill_manager  # noqa: F401


def _cargar_embeddings() -> None:
    from ai.embedding_engine import get_model

    get_model()


#: Orden deliberado: primero lo que hace falta para responder CUALQUIER mensaje, aunque sea
#: "hola"; al final lo más caro, que solo hace falta si la respuesta necesita buscar en la
#: memoria. Así, si el usuario pregunta a los cinco segundos de abrir la app, lo que ya está
#: cargado es justo lo que va a usar.
_TAREAS: List[Tuple[str, Callable[[], None]]] = [
    ("clasificador de intenciones", _cargar_clasificador),
    ("gestor de skills", _cargar_skills),
    ("modelo de embeddings", _cargar_embeddings),
]


def _precargar() -> None:
    inicio = time.time()
    for nombre, tarea in _TAREAS:
        t0 = time.time()
        try:
            tarea()
            logger.info(f"[Precarga] {nombre}: listo en {time.time() - t0:.1f}s")
        except Exception as e:
            # Que falle la precarga no puede impedir que el agente funcione: el módulo
            # correspondiente lo volverá a intentar cuando de verdad se necesite.
            logger.warning(f"[Precarga] {nombre} falló ({e}); se cargará al usarse")
    logger.info(f"[Precarga] completada en {time.time() - inicio:.1f}s")
    _terminado.set()


def start_warmup() -> None:
    """Arranca la precarga en segundo plano. Llamar una vez, al iniciar la aplicación."""
    global _hilo

    with _arranque_lock:
        if _hilo is not None and _hilo.is_alive():
            return      # ya está en marcha; llamarlo dos veces no duplica el trabajo

        _terminado.clear()
        _hilo = threading.Thread(target=_precargar, name="warmup", daemon=True)
        _hilo.start()
    logger.info("[Precarga] iniciada en segundo plano")


def esta_lista() -> bool:
    """Return True si la precarga terminó. Para diagnóstico y tests."""
    return _terminado.is_set()


def esperar(timeout: float = None) -> bool:
    """Bloquea hasta que la precarga termine. Solo para tests: en producción nadie espera."""
    return _terminado.wait(timeout=timeout)
