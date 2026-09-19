# SPEC-045 — Discord con confirmaciones y sin bloquear el bot

**Categoría:** BOT (+ SEGURIDAD) · **Tipo:** MEJORA + SEGURIDAD · **Fecha:** 2026-09-19
**Origen:** hallazgo 13 de la revisión de código de REQ-043 (se ofrecían `discord` y
`voice` como canales para herramientas MCP sin que exista adaptador de confirmación: el
gate las denegaba igual). Al mirar `channels/discord_bot.py` apareció el segundo problema.

## Problema

1. **Discord no puede confirmar nada.** `core/confirmation.py` tiene adaptador para
   escritorio (`ui/webview/confirmation_adapter.py`) y para Telegram
   (`channels/telegram_confirmation_adapter.py`, REQ-018). Para `ChannelType.DISCORD` no
   hay ninguno, así que toda acción amarilla —y toda herramienta MCP, amarillas por
   construcción— se deniega fail-closed por Discord aunque el usuario esté delante.
2. **El bot se bloquea mientras el agente piensa.** `on_message` y `/noddoo` llaman a
   `_process_message()` de forma síncrona dentro de la corutina: el event loop de
   discord.py queda parado durante todo el turno (con herramientas, decenas de segundos).
   Mientras tanto no se atienden heartbeats ni otros mensajes; Telegram lo resuelve con
   `asyncio.to_thread` desde REQ-018.

## Criterios de aceptación

| # | Criterio |
|---|---|
| CA-01 | Existe `channels/discord_confirmation_adapter.py::DiscordConfirmationAdapter`, con el mismo contrato que el de Telegram (`bind`, `set_request_context`, `reserve_pending`, `confirm`, `resolve`, `release_pending`) y el mismo comportamiento (timeout 120 s fail-closed, una pendiente por usuario, reserva especulativa, limpieza incondicional). Reutiliza la implementación de Telegram (`ChatConfirmationAdapter`) en vez de copiarla; solo cambia cómo se envía el mensaje. |
| CA-02 | `_send_message(chat_id, texto)` envía por el canal de Discord (`bot.get_channel`/`fetch_channel`) desde el hilo worker vía `run_coroutine_threadsafe`; un envío que falla no impide la espera (expira por timeout, fail-closed). |
| CA-03 | El adaptador se registra para `ChannelType.DISCORD` en `on_ready` (`register_confirmation_adapter`), ligado al bot y al loop en curso. |
| CA-04 | En `on_message`, un mensaje de texto de un usuario con confirmación pendiente se consume como respuesta (`resolve`) **aunque no mencione al bot** y no se reenvía al agente. Un mensaje sin pendiente sigue igual que hoy. |
| CA-05 | El turno del agente (mención y `/noddoo`) corre en `asyncio.to_thread`, con `reserve_pending(especulativa=True)` + `set_request_context(user_id, channel_id)` antes y `release_pending` después — mismo patrón que `channels/telegram_bot.py::_procesar_con_confirmacion`. |
| CA-06 | El `user_id` con el que se reserva y se resuelve es `str(message.author.id)` (el mismo en los dos puntos); el que viaja al gateway sigue siendo `canonical_user_id("discord", …)`. |
| CA-07 | `core/mcp_config.CANALES_HABILITABLES` pasa a `("desktop", "telegram", "discord")`; `voice` sigue fuera (sin adaptador). Docs y tests actualizados. |
| CA-08 | Los 21 tests del adaptador de Telegram siguen pasando sin cambios; tests nuevos para el adaptador de Discord y para la integración (`_procesar_con_confirmacion`, interceptación de respuestas). Sin red ni bot real. |

## Fuera de alcance

- Adaptador para voz: la política de voz es solo verde (`security-levels.md`), no hay
  nada que confirmar.
- Botones/reacciones de Discord como forma de confirmar: la respuesta es texto («sí»),
  como en Telegram (CA-06 de REQ-018), para tener un solo criterio de "sí".
