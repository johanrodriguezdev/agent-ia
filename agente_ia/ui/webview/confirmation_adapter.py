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


# `security_manager.require_confirmation()` arma UN solo texto para todos los canales, y
# lo termina con la instrucción de la consola ("Escribe 'sí' para confirmar..."). En un
# modal con botones Confirmar/Cancelar esa línea es falsa: no hay dónde escribir nada. Se
# recorta acá, en el adaptador del WebView, y no en el `security_manager`, para no tocar el
# texto que sí necesitan la consola y los otros canales.
_COLETILLA_CONSOLA = "Escribe"


def _sin_coletilla_de_consola(message: str) -> str:
    lineas = [l for l in message.splitlines() if not l.strip().startswith(_COLETILLA_CONSOLA)]
    return "\n".join(lineas).strip()


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

    def _manos_libres_activo(self) -> bool:
        """Return True si hay un worker de wake word escuchando ahora mismo.

        La comparación es `is True` y no `bool(...)` a propósito. Cualquier objeto no vacío
        es "verdadero" en Python —un `MagicMock` de un test, un valor inesperado de una
        refactorización futura— y aquí equivocarse significa esperar veinte segundos una
        respuesta hablada que nadie va a dar, en vez de mostrar el modal. Solo un `True`
        literal desvía al camino de voz.
        """
        try:
            return self._bridge._hands_free_active() is True
        except Exception as e:
            # Ante la duda, el modal: es el camino que siempre funciona.
            logger.warning(f"No se pudo determinar el estado del manos libres: {e}")
            return False

    def _confirmar_hablando(self, action_name: str, message: str) -> bool:
        """Pregunta en voz alta y espera un "confirmo". Fail-closed en todo lo demás."""
        from ui.tts_engine import prepare_for_speech, speak
        from voice.voice_confirmation import mensaje_hablado, voice_confirmation

        pregunta = mensaje_hablado(action_name, message)
        try:
            # Se pronuncia ANTES de abrir la escucha: si se abriera antes, el micrófono
            # capturaría la propia pregunta como si fuera la respuesta.
            speak(prepare_for_speech(pregunta))
        except Exception as e:
            # Sin voz no hay confirmación hablada posible, y adivinar no es una opción.
            logger.error(f"No se pudo pronunciar la confirmación de '{action_name}': {e}")
            return False

        return voice_confirmation.solicitar(action_name)

    def confirm(self, action_name: str, message: str) -> bool:
        """Adaptador síncrono/bloqueante — se registra vía
        `core.confirmation.register_confirmation_adapter(ChannelType.DESKTOP, adapter.confirm)`.
        Corre siempre en el hilo worker que ejecuta la acción, nunca en el hilo de la GUI.

        Con el manos libres activo la confirmación se pide HABLANDO, no con un modal. Un
        modal en mitad de una conversación por voz obliga a dejar de hablar e ir al ratón,
        y con la ventana de micrófono abierta cualquiera podría provocar ese modal contando
        con un clic distraído. Sin manos libres, el modal sigue siendo lo correcto.
        """
        if self._manos_libres_activo():
            return self._confirmar_hablando(action_name, message)

        request_id = uuid.uuid4().hex
        message = _sin_coletilla_de_consola(message)
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
