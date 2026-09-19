"""
channels/telegram_confirmation_adapter.py
Adaptador de confirmación conversacional para ChannelType.TELEGRAM (REQ-018).

Puente entre security_manager.require_confirmation() (síncrono, corre en un hilo worker vía
asyncio.to_thread()) y el runtime asyncio nativo de python-telegram-bot. Análogo en intención
a ui/webview/confirmation_adapter.py::WebViewConfirmationAdapter (REQ-015), resolviendo un
cruce hilo-worker↔event-loop-asyncio en vez de hilo-worker↔hilo-Qt. Contrato de
core/confirmation.py sin cambios: confirm(action_name, mensaje) -> bool, 100% síncrono desde
la perspectiva de security_manager.

Incorpora, desde el diseño inicial, las correcciones no bloqueantes de
`pruebas/security-audit-018.md` (auditoría original + re-chequeo, 2026-08-20):
- Hallazgo B: `confirm()` siempre limpia `_pending[user_id]` y resuelve a `False` si el
  envío del mensaje de confirmación lanza una excepción (p. ej. loop cerrado durante un
  reinicio) — nunca deja una entrada huérfana permanente ni deja escapar la excepción sin
  pasar por el flujo normal de auditoría de `require_confirmation()`.
- Hallazgo E: la reserva de `_pending[user_id]` es SÍNCRONA (`reserve_pending()`),
  invocada por `cmd_eliminar()` (channels/telegram_bot.py) ANTES de
  `await asyncio.to_thread(...)` — cierra la ventana, angosta pero real, en la que un
  segundo mensaje casi simultáneo del mismo usuario podía llegar antes de que la entrada
  existiera en `_pending` (que antes se insertaba recién dentro de `confirm()`, ya en el
  hilo worker). `confirm()` ya no crea la entrada — asume que `reserve_pending()` corrió
  antes, en el mismo Task que procesa el update.
"""

import asyncio
import contextvars
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

CONFIRM_TIMEOUT_SECONDS = 120  # mismo valor que WebViewConfirmationAdapter (REQ-015, CA-07)
_SEND_TIMEOUT_SECONDS = 10     # tope defensivo para el envío del mensaje, distinto del timeout de confirmación

# Viaja de cmd_eliminar() (hilo del event loop) a TelegramConfirmationAdapter.confirm()
# (hilo worker de asyncio.to_thread()) por propagación de contextvars — cada invocación de
# to_thread() copia el contexto vigente al hilo nuevo (ver docs de asyncio.to_thread()).
_request_ctx: "contextvars.ContextVar[Optional[Tuple[str, int]]]" = contextvars.ContextVar(
    "_telegram_confirm_request_ctx", default=None
)


@dataclass
class _PendingConfirmation:
    event: threading.Event = field(default_factory=threading.Event)
    result: bool = False
    #: Si el próximo mensaje del usuario debe leerse como respuesta a esta confirmación.
    #:
    #: Hay dos formas de reservar y solo se distinguen en esto. `/eliminar` reserva
    #: **comprometido**: se sabe que va a preguntar, así que desde el primer instante
    #: cualquier mensaje del usuario es su respuesta — es lo que cerró la ventana del
    #: Hallazgo E y por eso el valor por defecto es True. El camino del agente reserva
    #: **especulativo**: la mayoría de los mensajes no confirman nada, y mientras el agente
    #: aún está pensando no se ha preguntado nada, así que un segundo mensaje es
    #: conversación normal y consumirlo lo haría desaparecer. Ahí empieza en False y pasa a
    #: True en cuanto la pregunta sale por el chat.
    consume_respuestas: bool = True


class ChatConfirmationAdapter:
    """Adaptador (action_name, mensaje) -> bool para un canal de chat con event loop propio.

    Nació como el de Telegram (REQ-018) y desde REQ-045 es la base también del de Discord
    (`channels/discord_confirmation_adapter.py`): la reserva por usuario, la espera con
    timeout, la lectura del "sí" y la limpieza son idénticas en los dos; lo único que cambia
    es cómo se manda el mensaje, y eso es `_send_message()`. Se registra vía
    `core.confirmation.register_confirmation_adapter(canal, adapter.confirm)` cuando el bot
    ya tiene loop.
    """

    def __init__(self) -> None:
        self._bot = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._pending: Dict[str, _PendingConfirmation] = {}
        self._lock = threading.Lock()

    def bind(self, bot, loop: asyncio.AbstractEventLoop) -> None:
        """Llamado una vez desde el callback post_init, con el bot y el loop ya corriendo."""
        self._bot = bot
        self._loop = loop

    @staticmethod
    def set_request_context(user_id: str, chat_id: int) -> None:
        """Llamado por cmd_eliminar() antes de asyncio.to_thread(require_confirmation, ...)."""
        _request_ctx.set((user_id, chat_id))

    def has_pending(self, user_id: str) -> bool:
        """Chequeo de solo lectura — no reserva nada (ver reserve_pending() para la
        verificación atómica y autoritativa real, REQ-018/Hallazgo E)."""
        with self._lock:
            return user_id in self._pending

    def reserve_pending(self, user_id: str, especulativa: bool = False) -> bool:
        """REQ-018/CA-09, Hallazgo E (security-audit-018.md, re-chequeo) — reserva SÍNCRONA
        de _pending[user_id], pensada para invocarse desde cmd_eliminar() ANTES de lanzar el
        hilo worker de asyncio.to_thread(). Es la verificación atómica y autoritativa de
        "una sola confirmación pendiente por usuario": al correr en el mismo Task que
        procesa el update, en vez de recién dentro de confirm() (que solo arranca cuando el
        hilo worker efectivamente empieza a ejecutarse), cierra por completo — no solo
        acota — la ventana donde un segundo mensaje casi simultáneo del mismo usuario podía
        colarse antes de que la entrada existiera. Retorna False si ya había una
        confirmación pendiente para este usuario (no reserva una segunda).

        `especulativa=True` es para quien reserva sin saber todavía si va a preguntar —el
        camino del agente con herramientas, que reserva al empezar CUALQUIER mensaje—. La
        reserva vale igual para excluir a otra, pero no empieza a consumir mensajes como
        respuestas hasta que la pregunta salga de verdad (ver `consume_respuestas`)."""
        with self._lock:
            if user_id in self._pending:
                return False
            self._pending[user_id] = _PendingConfirmation(
                consume_respuestas=not especulativa
            )
            return True

    def confirm(self, action_name: str, message: str) -> bool:
        """ConfirmFn — (action_name, mensaje) -> bool. Corre en el hilo worker de
        asyncio.to_thread(), nunca en el hilo del event loop (CA-08). Asume que
        reserve_pending(user_id) ya reservó la entrada correspondiente (REQ-018/Hallazgo E)
        — cmd_eliminar() siempre la llama antes de disparar este hilo, así que no vuelve a
        crear ni a validar duplicados acá."""
        ctx = _request_ctx.get()
        if ctx is None:
            logger.error(
                "TelegramConfirmationAdapter.confirm() invocado sin contexto de "
                "request (set_request_context() no se llamó antes) — denegado fail-closed"
            )
            return False
        user_id, chat_id = ctx

        with self._lock:
            pending = self._pending.get(user_id)
        if pending is None:
            # No debería ocurrir si el caller respeta el contrato (reserve_pending()
            # siempre antes de confirm()) — fail-closed defensivo, nunca crea una entrada
            # acá para no reabrir la ventana que Hallazgo E cerró.
            logger.error(
                f"TelegramConfirmationAdapter.confirm() sin reserva previa para "
                f"user_id={user_id} — denegado fail-closed (reserve_pending() no se llamó)"
            )
            return False

        try:
            # Se marca ANTES de enviar: en cuanto el mensaje salga, la respuesta puede
            # llegar de inmediato, y `resolve()` solo consume lo que ya fue preguntado.
            with self._lock:
                pending.consume_respuestas = True
            self._send_message(chat_id, message)
            answered_in_time = pending.event.wait(timeout=CONFIRM_TIMEOUT_SECONDS)
            with self._lock:
                confirmed = pending.result if answered_in_time else False
            if not answered_in_time:
                logger.warning(
                    f"Confirmación '{action_name}' para user_id={user_id} expiró tras "
                    f"{CONFIRM_TIMEOUT_SECONDS}s sin respuesta — fail-closed"
                )
            return confirmed
        except Exception as e:
            # REQ-018/Hallazgo B (security-audit-018.md) — cualquier excepción entre el
            # envío del mensaje y la resolución (p. ej. asyncio.run_coroutine_threadsafe()
            # lanzando porque el loop ya no está corriendo, caso de borde de
            # apagado/reinicio) se resuelve acá mismo a False (fail-closed, nunca True) en
            # vez de dejarla escapar — así require_confirmation() sigue su flujo normal de
            # auditoría (_log_audit con result="cancelada") en vez de perder el registro.
            logger.error(
                f"Error enviando/esperando confirmación '{action_name}' para "
                f"user_id={user_id}: {e}"
            )
            return False
        finally:
            # Limpieza incondicional — no importa por qué camino se llegó acá (respuesta,
            # timeout o excepción), nunca queda un Event vivo esperando algo que ya no
            # puede llegar. No-op si resolve() ya la sacó.
            with self._lock:
                self._pending.pop(user_id, None)

    def _send_message(self, chat_id: int, text: str) -> None:
        if self._bot is None or self._loop is None:
            logger.error(
                "TelegramConfirmationAdapter sin bind() — no se pudo enviar el mensaje de "
                "confirmación (la espera igual continúa y expirará por timeout)"
            )
            return
        future = asyncio.run_coroutine_threadsafe(
            self._bot.send_message(chat_id=chat_id, text=text), self._loop
        )
        try:
            future.result(timeout=_SEND_TIMEOUT_SECONDS)
        except Exception as e:
            logger.error(f"No se pudo enviar mensaje de confirmación a chat_id={chat_id}: {e}")

    def resolve(self, user_id: str, text: str) -> bool:
        """Llamado desde _intercept_confirmacion_pendiente() (hilo del event loop) con el
        próximo mensaje de texto del usuario. Retorna True si había una confirmación
        pendiente para user_id y este mensaje se consumió como respuesta (CA-05) — en ese
        caso el caller NO debe reenviar el texto a GlassGateway().process(). Retorna False
        si no había ninguna pendiente (mensaje normal, se procesa como siempre)."""
        with self._lock:
            pending = self._pending.get(user_id)
            if pending is None or not pending.consume_respuestas:
                # Reservado pero todavía sin preguntar: el agente sigue pensando y este
                # mensaje es conversación normal, no una respuesta. Consumirlo aquí lo
                # haría desaparecer sin que el usuario se enterase.
                return False
            self._pending.pop(user_id, None)
            # CA-06 — único criterio de "sí", igual que _desktop_confirm/WebViewConfirmationAdapter.
            pending.result = text.strip().lower() in ("sí", "si", "yes", "s")
        pending.event.set()
        return True

    def release_pending(self, user_id: str) -> None:
        """Libera una reserva que nunca llegó a usarse.

        La reserva se toma al empezar a procesar cualquier mensaje, porque no se sabe de
        antemano si el agente pedirá confirmación. La mayoría de las veces no la pide, y
        entonces hay que soltarla: si no, el usuario quedaría con una confirmación
        fantasma que bloquearía la siguiente de verdad. Nunca toca una que ya se preguntó
        —esa está esperando respuesta legítimamente—.
        """
        with self._lock:
            pending = self._pending.get(user_id)
            if pending is not None and not pending.consume_respuestas:
                del self._pending[user_id]


#: El nombre con el que nació (REQ-018); `channels/telegram_bot.py` y sus tests lo usan.
TelegramConfirmationAdapter = ChatConfirmationAdapter

telegram_confirmation_adapter = TelegramConfirmationAdapter()
