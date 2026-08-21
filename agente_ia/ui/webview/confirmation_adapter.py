"""
ui/webview/confirmation_adapter.py
`WebViewConfirmationAdapter` — adaptador de confirmación YELLOW para `ChannelType.DESKTOP`
basado en modal WebView + `threading.Event` (REQ-015/CA-41, arquitectura-015.md §4.3, con
la limpieza de Hallazgo B de `security-audit-015.md` incorporada — ver §10.3).

Reemplaza en runtime, solo si `MainWindow` se construye con éxito, al adaptador de
consola (`main.py::_desktop_confirm`, registrado a nivel de módulo al importar `main.py`)
— si la construcción de `MainWindow` falla (modo headless), el adaptador de consola sigue
siendo el activo, sin cambio de comportamiento.

Diseño fail-closed: el hilo worker que invoca `confirm()` (nunca el hilo de la GUI —
`security_manager.require_confirmation()` corre siempre dentro de `run_async()`) queda
bloqueado hasta que JS responde vía `confirm_response()` (que sí corre en el hilo de la
GUI, entregado de forma segura entre hilos porque `confirmation_requested` es un
`pyqtSignal`) o hasta que expira el timeout — en cuyo caso retorna `False`, nunca `True`
por defecto.
"""

import logging
import threading
import uuid
from typing import Dict

logger = logging.getLogger(__name__)

CONFIRM_TIMEOUT_SECONDS = 120


class WebViewConfirmationAdapter:
    """Adaptador `(action_name, message) -> bool` registrado para `ChannelType.DESKTOP`.

    `bridge` es la instancia de `ui.webview.bridge.Bridge` ya construida — se usa
    únicamente para emitir `confirmation_requested` (Qt encola la entrega en el hilo de
    la GUI automáticamente, sin necesidad de gestionar el cruce de hilos a mano acá).
    """

    def __init__(self, bridge):
        self._bridge = bridge
        self._pending: Dict[str, threading.Event] = {}
        self._results: Dict[str, bool] = {}
        self._lock = threading.Lock()

    def confirm(self, action_name: str, message: str) -> bool:
        """Adaptador síncrono/bloqueante — se registra vía
        `core.confirmation.register_confirmation_adapter(ChannelType.DESKTOP, adapter.confirm)`.
        Corre siempre en el hilo worker que ejecuta la acción, nunca en el hilo de la GUI.
        """
        request_id = uuid.uuid4().hex
        event = threading.Event()
        with self._lock:
            self._pending[request_id] = event

        self._bridge.confirmation_requested.emit(request_id, action_name, message)
        answered_in_time = event.wait(timeout=CONFIRM_TIMEOUT_SECONDS)

        with self._lock:
            # Hallazgo B (security-audit-015.md, §10.3): limpieza de `self._pending` tras
            # resolución, se haya respondido a tiempo o no — nunca queda un `Event` vivo
            # esperando una respuesta que ya no puede llegar.
            self._pending.pop(request_id, None)
            confirmed = self._results.pop(request_id, False) if answered_in_time else False

        if not answered_in_time:
            logger.warning(
                f"Confirmación '{action_name}' (request_id={request_id}) expiró sin "
                f"respuesta tras {CONFIRM_TIMEOUT_SECONDS}s — fail-closed"
            )
        return confirmed

    def confirm_response(self, request_id: str, confirmed: bool) -> None:
        """`@pyqtSlot` de `Bridge.confirm_response()` — corre en el hilo de la GUI.

        Hallazgo B (security-audit-015.md, §10.3): manejo defensivo de un `request_id`
        desconocido (ya resuelto, expirado, o nunca emitido por este proceso) — se loguea
        y se retorna sin lanzar, nunca se asume que el request sigue vivo.
        """
        with self._lock:
            event = self._pending.get(request_id)
            if event is None:
                logger.warning(
                    f"confirm_response() con request_id desconocido o ya resuelto: "
                    f"{request_id!r}"
                )
                return
            self._results[request_id] = bool(confirmed)
            event.set()
