"""
channels/discord_confirmation_adapter.py
Adaptador de confirmación conversacional para ChannelType.DISCORD (REQ-045).

Hasta REQ-045, Discord no tenía adaptador: `core/confirmation.py` no encontraba a quién
preguntar y `require_confirmation()` denegaba fail-closed toda acción amarilla —y toda
herramienta MCP, que es amarilla por construcción— aunque el usuario estuviera delante
del chat. Telegram sí lo tenía desde REQ-018.

Es el adaptador de Telegram con otro transporte: `ChatConfirmationAdapter`
(`channels/telegram_confirmation_adapter.py`) ya resuelve la reserva por usuario, la
espera con timeout fail-closed, la lectura del «sí» y la limpieza incondicional. Lo único
propio de Discord es cómo se manda el mensaje: por el canal (`bot.get_channel`) desde el
hilo worker, vía `run_coroutine_threadsafe` sobre el loop de discord.py.

Contrato con `channels/discord_bot.py`, el mismo que el de Telegram:
- `bind(bot, loop)` en `on_ready`, y `register_confirmation_adapter(ChannelType.DISCORD,
  adapter.confirm)`.
- Antes de lanzar el turno en un hilo: `reserve_pending(user_id, especulativa=True)` y
  `set_request_context(user_id, channel_id)`. Después: `release_pending(user_id)`.
- En cada mensaje de texto, ANTES de mirar si menciona al bot: `resolve(user_id, texto)`.
  Si devuelve True, el mensaje era la respuesta a una confirmación y no va al agente.
"""

import asyncio
import logging

from channels.telegram_confirmation_adapter import _SEND_TIMEOUT_SECONDS, ChatConfirmationAdapter

logger = logging.getLogger(__name__)


class DiscordConfirmationAdapter(ChatConfirmationAdapter):
    """(action_name, mensaje) -> bool para ChannelType.DISCORD."""

    def _send_message(self, chat_id: int, text: str) -> None:
        """Manda la pregunta al canal `chat_id` desde el hilo worker.

        Si no se puede enviar, no se lanza: la espera sigue y expira por timeout
        (fail-closed), igual que en Telegram. Un error acá nunca puede convertirse en un
        "sí".
        """
        if self._bot is None or self._loop is None:
            logger.error(
                "DiscordConfirmationAdapter sin bind() — no se pudo enviar el mensaje de "
                "confirmación (la espera igual continúa y expirará por timeout)"
            )
            return
        future = asyncio.run_coroutine_threadsafe(self._enviar(chat_id, text), self._loop)
        try:
            future.result(timeout=_SEND_TIMEOUT_SECONDS)
        except Exception as e:
            logger.error(f"No se pudo enviar mensaje de confirmación al canal {chat_id}: {e}")

    async def _enviar(self, chat_id: int, text: str) -> None:
        canal = self._bot.get_channel(chat_id)
        if canal is None:
            # Un canal que el bot todavía no tiene en caché (recién invitado, o un hilo
            # nuevo): se pide a la API en vez de darlo por perdido.
            canal = await self._bot.fetch_channel(chat_id)
        await canal.send(text)


discord_confirmation_adapter = DiscordConfirmationAdapter()
