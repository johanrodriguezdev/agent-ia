"""
voice/mic_window.py
Ventana de conversación del modo manos libres — REQ-021 (pieza 6).

**La ventana no abre ningún micrófono ni ninguna escucha nueva.** Cambia el *predicado de
aceptación* del bucle que `listen_for_wake_word()` ya está corriendo: durante ~15 s, una
frase transcrita se acepta aunque no traiga la wake word, en vez de descartarse.

Por qué así y no abriendo una escucha propia: `voice/wake_word.py::_listen_for_followup`
documenta que abrir un segundo `sr.Microphone()` anidado deja el dispositivo tomado y
falla en Windows. Reusando el bucle existente no hay micrófono nuevo, ni llamada
bloqueante nueva, ni riesgo de dispositivo trabado; y el sondeo del estado sale gratis a
~1 Hz por el `timeout=1` que el bucle ya usa.

Es el canal bridge -> worker, mismo patrón que el `stop_event` que ya cruza esos dos
hilos: el hilo de Qt solo escribe (`open`/`cancel`), el hilo del micrófono solo lee
(`accepts`/`consume`/`expired_now`). Ninguno espera al otro — no hay `Event.wait()`, no
hay `join()`, no hay cola: **no existe deadlock posible**. Si el bridge muere o nunca
llama a `open()`, el sistema degrada exactamente al comportamiento de hoy (wake word
obligatoria): fail-closed hacia el estado seguro.
"""

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

#: ~15 s. ASUMIDO de la SPEC, valor de partida ajustable tras la prueba en vivo. Vive en
#: un único lugar a propósito (condición 2 del hallazgo H4 de la auditoría de seguridad).
MIC_WINDOW_SECONDS: float = 15.0


class ConversationWindow:
    """Ventana temporal en la que se acepta una frase sin wake word."""

    def __init__(
        self,
        duration_s: float = MIC_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._duration_s = duration_s
        self._clock = clock
        self._lock = threading.Lock()
        self._opened_at: Optional[float] = None
        self._deadline: Optional[float] = None

    # ── escritura: hilo de Qt ──────────────────────────────────
    def open(self) -> None:
        """Arma la ventana. Se llama en el `on_done` de la tarea de voz (CA-26).

        Nunca por sondeo de `is_speaking()`: en `_speak_edge()` la bandera `_speaking` se
        pone en `True` DESPUÉS de sintetizar el mp3, así que hay hasta 15 s en los que el
        agente está por hablar y `is_speaking()` devuelve `False`. Un sondeo abriría el
        micrófono justo ahí y el agente se transcribiría a sí mismo.
        """
        with self._lock:
            now = self._clock()
            self._opened_at = now
            self._deadline = now + self._duration_s
        logger.info(f"[Ventana] abierta por {self._duration_s:.0f}s")

    def cancel(self) -> None:
        """Cierra la ventana ya: manos libres OFF, parada de la app."""
        with self._lock:
            estaba_abierta = self._deadline is not None
            self._opened_at = None
            self._deadline = None
        if estaba_abierta:
            logger.info("[Ventana] cerrada por cancelación")

    # ── lectura: hilo del micrófono ────────────────────────────
    def opened_at(self) -> Optional[float]:
        with self._lock:
            return self._opened_at

    def is_open(self) -> bool:
        """Return True si la ventana está armada y no venció."""
        with self._lock:
            return self._deadline is not None and self._clock() < self._deadline

    def accepts(self, listen_started_at: float) -> bool:
        """Return True si un chunk que EMPEZÓ a capturarse en `listen_started_at` puede
        aceptarse sin wake word.

        El segundo candado de CA-14: no basta con que la ventana esté abierta, el chunk
        tiene que haber empezado DESPUÉS de abrirse. Un chunk que se empezó a capturar
        mientras el agente hablaba se descarta aunque termine después — casi con seguridad
        contiene la voz del propio agente.
        """
        with self._lock:
            if self._deadline is None or self._opened_at is None:
                return False
            if self._clock() >= self._deadline:
                return False
            return listen_started_at >= self._opened_at

    def consume(self) -> None:
        """Cierra la ventana tras aceptar una frase: UNA frase por ventana.

        Es la mitigación principal del ruido ambiente (condición 1 del hallazgo H4 de la
        auditoría): sin esto, un ruido continuo podría encadenar ejecuciones durante los
        15 s completos.
        """
        with self._lock:
            self._opened_at = None
            self._deadline = None

    def expired_now(self) -> bool:
        """Return True una sola vez, en la transición abierta -> vencida (CA-13).

        Sin hilo de fondo ni timer: la expiración se evalúa al leer, igual que la del
        diálogo pendiente.
        """
        with self._lock:
            if self._deadline is None:
                return False
            if self._clock() < self._deadline:
                return False
            self._opened_at = None
            self._deadline = None
        logger.info("[Ventana] vencida sin voz; vuelve a exigirse la wake word")
        return True
