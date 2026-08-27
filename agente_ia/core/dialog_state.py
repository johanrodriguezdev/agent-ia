"""
core/dialog_state.py
Estado de diálogo pendiente por `(user_id, canal)` — REQ-021.

Mecanismo GENERAL y reutilizable: cuando a una acción le falta un dato obligatorio, en vez
de inventarlo se deja una pregunta en el aire y la frase siguiente se lee como su
respuesta. En v1 la única acción cableada es `task_create` (`core/resolution.py`), pero
nada acá conoce las tareas.

Invariantes (auditoría de seguridad `propuestas/security-audit-021.md`):

- **La clave es `(user_id, canal)`**, construida siempre desde los argumentos que recibió
  el resolver — nunca del texto del usuario. Es lo que impide que el diálogo de un
  usuario de Telegram conteste al de otro (H6).
- **`user_id` vacío se rechaza** con `ValueError` (H3): un diálogo sin dueño no debe
  existir, porque todos esos usuarios compartirían la clave `("", canal)`.
- **`PendingDialog` es `frozen`**: la acción destino se fija al abrir y no hay ningún
  camino por el que el contenido de un slot pueda cambiarla (CA-19). Avanzar el diálogo
  construye una instancia nueva; nunca se muta la existente.
- **El estado vive en memoria del proceso**, nunca en disco. Reiniciar la app pierde el
  diálogo y no crea nada — decisión explícita de Johan ("descartar en silencio").
- **La expiración se evalúa al LEER** (`get()`), sin hilo de fondo ni timer. Un diálogo
  abandonado no consume nada y no emite ningún mensaje (CA-07).
- **`last_progress_at` solo lo mueven `open()` y `fill()`** (CA-32): un desvío de tema no
  compra tiempo, así el TTL corre desde el último avance real.
"""

import logging
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: ~3 min. ASUMIDO de la SPEC, valor de partida ajustable tras la prueba en vivo. Vive
#: en un único lugar, a propósito.
DIALOG_TTL_SECONDS: float = 180.0


@dataclass(frozen=True)
class PendingDialog:
    """Una intención incompleta esperando un dato. Inmutable: avanzar crea otra."""

    action: str
    slots: Dict[str, str]
    missing: Tuple[str, ...]
    question: str
    user_id: str
    channel_value: str
    last_progress_at: float

    @property
    def next_slot(self) -> Optional[str]:
        """Return el slot que se está preguntando ahora, o None si ya está completo."""
        return self.missing[0] if self.missing else None


class DialogStore:
    """Diálogos pendientes vivos, particionados por `(user_id, canal)`.

    `threading.RLock` en todos los métodos: `resolve()` corre en un hilo de `QThreadPool`
    en el webview, en el hilo del bot en Telegram/Discord y en el principal en la consola.
    """

    def __init__(
        self,
        ttl_seconds: float = DIALOG_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.RLock()
        self._dialogs: Dict[Tuple[str, str], PendingDialog] = {}

    # ── clave ──────────────────────────────────────────────────
    @staticmethod
    def _channel_value(channel) -> str:
        """Return el valor del canal ya resuelto que pasó el caller.

        Acepta `ChannelType` o `str` porque es lo que hacen el resto de los módulos, pero
        NUNCA deduce el canal de un texto ni de `params` — solo lee el argumento.
        """
        return str(getattr(channel, "value", channel))

    def _key(self, user_id: str, channel) -> Tuple[str, str]:
        return (str(user_id), self._channel_value(channel))

    # ── ciclo de vida ──────────────────────────────────────────
    def open(
        self, user_id: str, channel, *, action: str, slots: Dict[str, str],
        missing: Tuple[str, ...], question: str,
    ) -> PendingDialog:
        """Abrir un diálogo pendiente. La acción destino queda fijada acá para siempre.

        Lanza `ValueError` si `user_id` es falsy (H3) o si `action` viene vacía.
        """
        if not user_id:
            raise ValueError(
                "DialogStore.open() exige un user_id: un diálogo sin dueño se compartiría "
                "entre todos los usuarios del canal"
            )
        if not action:
            raise ValueError("DialogStore.open() exige una acción destino")

        dialog = PendingDialog(
            action=action,
            slots=dict(slots or {}),
            missing=tuple(missing or ()),
            question=question,
            user_id=str(user_id),
            channel_value=self._channel_value(channel),
            last_progress_at=self._clock(),
        )
        with self._lock:
            self._dialogs[self._key(user_id, channel)] = dialog
        logger.info(
            f"[Diálogo] abierto action={action} falta={dialog.missing} "
            f"user={user_id} canal={dialog.channel_value}"
        )
        return dialog

    def get(self, user_id: str, channel) -> Optional[PendingDialog]:
        """Return el diálogo vivo de `(user_id, canal)`, o None.

        Purga al leer: un diálogo sin avance por más del TTL se descarta EN SILENCIO —
        no se crea nada y no se emite ningún mensaje al usuario (CA-07).
        """
        if not user_id:
            return None
        key = self._key(user_id, channel)
        with self._lock:
            dialog = self._dialogs.get(key)
            if dialog is None:
                return None
            if self._clock() - dialog.last_progress_at > self._ttl_seconds:
                del self._dialogs[key]
                logger.info(
                    f"[Diálogo] expirado en silencio action={dialog.action} "
                    f"user={dialog.user_id} canal={dialog.channel_value}"
                )
                return None
            return dialog

    def fill(self, user_id: str, channel, slot: str, value: str) -> Optional[PendingDialog]:
        """Llenar un slot y avanzar el diálogo. Mueve `last_progress_at` (CA-32)."""
        key = self._key(user_id, channel)
        with self._lock:
            dialog = self.get(user_id, channel)
            if dialog is None:
                return None
            slots = dict(dialog.slots)
            slots[slot] = value
            missing = tuple(s for s in dialog.missing if s != slot)
            updated = replace(
                dialog, slots=slots, missing=missing, last_progress_at=self._clock(),
            )
            self._dialogs[key] = updated
            return updated

    def touch_question(self, user_id: str, channel, question: str) -> Optional[PendingDialog]:
        """Registrar la última repregunta emitida. NO mueve el reloj (CA-32)."""
        key = self._key(user_id, channel)
        with self._lock:
            dialog = self.get(user_id, channel)
            if dialog is None:
                return None
            updated = replace(dialog, question=question)
            self._dialogs[key] = updated
            return updated

    def cancel(self, user_id: str, channel) -> None:
        """Cerrar el diálogo. Se usa tanto al cancelarlo como al completarlo."""
        with self._lock:
            self._dialogs.pop(self._key(user_id, channel), None)

    def clear_all(self) -> None:
        """Vaciar el estado. Solo para tests (fixture `autouse` de `conftest.py`)."""
        with self._lock:
            self._dialogs.clear()


#: Singleton de módulo, mismo patrón que `task_manager` y `security_manager`.
dialog_store = DialogStore()
