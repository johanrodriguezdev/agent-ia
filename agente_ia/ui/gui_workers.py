"""
ui/gui_workers.py
Helper de concurrencia (REQ-008) para operaciones de I/O de un solo disparo disparadas
por eventos de UI — clima, accesos rápidos, barra de comando. NO reemplaza el mecanismo
de polling de `GLOBAL_STATE` (ver `ui/gui.py`), que sigue siendo el bridge del estado
continuo IDLE/LISTENING/PROCESSING/RESPONDING desde el hilo trabajador.

Regla de seguridad (ver arquitectura-008.md): los callbacks `on_done`/`on_error` pasados
a `run_async()` deben ser siempre métodos vinculados (`bound methods`) de un widget/
`QObject` que vive en el hilo de la GUI — nunca funciones sueltas de módulo ni `lambda`
que mute un widget desde fuera. Así Qt garantiza que la señal se entregue en el hilo
correcto (conexión "Auto" se resuelve a "Queued" cuando el receptor vive en otro hilo).
"""

import logging
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """Señales emitidas por un `CallableWorker` al terminar."""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)


class CallableWorker(QRunnable):
    """Ejecuta `fn(*args, **kwargs)` en un hilo de `QThreadPool`.

    Nunca crea ni toca un `QWidget` — solo ejecuta funciones Python puras y emite el
    resultado (o el error) por señal, para que Qt encole la entrega en el hilo correcto.
    """

    def __init__(self, fn: Callable, *args: Any, **kwargs: Any):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as e:
            logger.error(f"Error en worker de {getattr(self.fn, '__name__', self.fn)}: {e}")
            self.signals.error.emit(str(e))
            return
        self.signals.finished.emit(result)


def run_async(
    fn: Callable,
    on_done: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    *args: Any,
    **kwargs: Any,
) -> CallableWorker:
    """Ejecuta `fn(*args, **kwargs)` en `QThreadPool.globalInstance()` sin bloquear la GUI.

    `on_done`/`on_error`, si se pasan, deben ser métodos vinculados de un `QObject` del
    hilo de la GUI (ver docstring del módulo).
    """
    worker = CallableWorker(fn, *args, **kwargs)
    if on_done is not None:
        worker.signals.finished.connect(on_done)
    if on_error is not None:
        worker.signals.error.connect(on_error)
    QThreadPool.globalInstance().start(worker)
    return worker
