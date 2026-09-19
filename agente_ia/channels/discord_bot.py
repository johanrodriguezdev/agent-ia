"""
channels/discord_bot.py
Bot de Discord para Noddoo.

Capacidades:
  - Mensajes de texto en cualquier canal donde esté invitado
  - Comandos slash: /noddoo /memoria /limpiar /ayuda
  - Mencionar al bot (@Noddoo tu pregunta)
  - Mensajes de voz (archivos de audio adjuntos)
  - Respuestas en embeds elegantes con el estilo de Noddoo
  - Multiservidor — cada servidor tiene su contexto

Instalación:
  pip install discord.py

Configuración:
  1. Ve a https://discord.com/developers/applications
  2. Crea una aplicación → Bot → copia el token
  3. Activa "Message Content Intent" en el portal de Discord
  4. Agrega en config.json: { "discord_token": "TU_TOKEN" }
  O variable de entorno: DISCORD_BOT_TOKEN=TU_TOKEN
"""

import os
import json
import asyncio
import tempfile
import logging
from pathlib import Path
from core.address import vocative, vocative_start

logging.basicConfig(
    format="%(asctime)s [Discord] %(levelname)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def _get_token() -> str:
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if token:
        return token
    from config_manager import get_discord_token
    return get_discord_token() or ""


def _get_agent_name() -> str:
    from config_manager import load_config
    try:
        cfg = load_config()
        return cfg.get("agent_name", "noddoo").upper()
    except Exception:
        return "NODDOO"


def _process_message(user_id: str, user_name: str, text: str, image_path: str = None) -> str:
    """Procesa un mensaje a través del Gateway de Glass."""
    try:
        from channels.gateway import GlassGateway, GlassMessage, MessageType
        msg_type = MessageType.IMAGE if image_path else MessageType.TEXT
        msg = GlassMessage(
            # Sin prefijo de canal: `user_id` ya llega resuelto por
            # `core.user_identity.canonical_user_id()`. Envolverlo aqui ("discord_owner")
            # devolvia al dueno a un espacio de memoria propio de Discord.
            user_id=user_id,
            user_name=user_name,
            text=text,
            channel="discord",
            msg_type=msg_type,
            image_path=image_path
        )
        gateway = GlassGateway()
        response = gateway.process(msg)
        return response.text
    except Exception as e:
        logger.error(
            f"Error en discord_bot._process_message() | usuario={user_id} ({user_name}) | "
            f"canal=discord: {e}",
            exc_info=True
        )
        return (
            "Lo siento, he encontrado un inconveniente inesperado. "
            "Intente de nuevo en un momento."
        )



async def _slash_autorizado(interaction, comando: str) -> bool:
    """Return True si quien lanza el comando slash puede ser atendido.

    Los comandos slash no pasan por `on_message`, asi que cada uno necesita su propia
    comprobacion. Si devuelve False ya respondio al usuario y el comando debe cortar.
    """
    from core.authorized_users import UNAUTHORIZED_MESSAGE, is_authorized

    autor_id = str(interaction.user.id)
    if is_authorized("discord", autor_id):
        return True

    logger.warning(f"Discord: /{comando} rechazado de un remitente no autorizado (id={autor_id})")
    try:
        await interaction.response.send_message(UNAUTHORIZED_MESSAGE, ephemeral=True)
    except Exception as e:
        logger.error(f"No se pudo avisar al remitente no autorizado: {e}")
    return False


def _responder_confirmacion(author_id: str, texto: str) -> bool:
    """Return True si `texto` era la respuesta a una confirmación pendiente de `author_id`.

    Va ANTES de mirar si el mensaje menciona al bot: quien contesta «sí» a una pregunta no
    vuelve a mencionarlo. Si se consumió, el mensaje no va al agente (REQ-045/CA-04).
    """
    from channels.discord_confirmation_adapter import discord_confirmation_adapter

    if not texto:
        return False
    return discord_confirmation_adapter.resolve(author_id, texto)


async def _procesar_con_confirmacion(
    author_id: str, channel_id: int, user_id: str, user_name: str, text: str,
    image_path: str = None,
) -> str:
    """Corre el turno del agente en un hilo, con el adaptador de confirmación preparado.

    Mismo patrón que `channels/telegram_bot.py::_procesar_con_confirmacion` (REQ-018):

    - `asyncio.to_thread`: el turno puede tardar decenas de segundos con herramientas, y
      hasta REQ-045 corría dentro de la corutina, con el event loop de discord.py parado
      —sin heartbeats ni otros mensajes— todo ese tiempo. Peor: la respuesta «sí» del
      usuario no podía llegar nunca, porque el bot estaba sordo esperándola.
    - La reserva es especulativa: la mayoría de los mensajes no confirman nada. Se toma
      antes del hilo (es lo que copia el contexto al worker) y se suelta al terminar; si
      ya había una confirmación en curso para este usuario se procesa igual, pero sin
      contexto, así que una acción amarilla que aparezca se deniega en vez de colarse en la
      espera ajena.
    """
    from channels.discord_confirmation_adapter import discord_confirmation_adapter

    reservado = discord_confirmation_adapter.reserve_pending(author_id, especulativa=True)
    if reservado:
        discord_confirmation_adapter.set_request_context(author_id, channel_id)
    try:
        return await asyncio.to_thread(_process_message, user_id, user_name, text, image_path)
    finally:
        if reservado:
            discord_confirmation_adapter.release_pending(author_id)


def run_discord_bot():
    """Inicia el bot de Discord."""
    try:
        import discord
        from discord.ext import commands
        from discord import app_commands
    except ImportError:
        print("\n[Error] discord.py no está instalado.")
        print("Ejecuta: pip install discord.py\n")
        return

    token = _get_token()
    if not token:
        print("\n[Error] No encontré el token de Discord.")
        print("Agrega DISCORD_BOT_TOKEN como variable de entorno\n")
        return

    agent = _get_agent_name()

    # Intents necesarios
    intents = discord.Intents.default()
    intents.message_content = True  # IMPORTANTE: activar en el portal de Discord

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f"\n{'='*45}")
        print(f"  {agent} - Bot de Discord activo")
        print(f"  Conectado como: {bot.user}")
        print(f"{'='*45}\n")
        # REQ-045 — el adaptador de confirmación existe recién cuando hay loop y bot: acá.
        # Sin esto, toda acción amarilla por Discord se denegaba fail-closed sin preguntar.
        from channels.discord_confirmation_adapter import discord_confirmation_adapter
        from core.confirmation import register_confirmation_adapter
        from core.security_manager import ChannelType

        discord_confirmation_adapter.bind(bot, asyncio.get_running_loop())
        register_confirmation_adapter(ChannelType.DISCORD, discord_confirmation_adapter.confirm)

        # Sincronizar comandos slash
        try:
            synced = await bot.tree.sync()
            print(f"  {len(synced)} comandos slash sincronizados\n")
        except Exception as e:
            print(f"  Error sincronizando comandos: {e}\n")

    @bot.event
    async def on_message(message):
        """Responde cuando alguien menciona al bot."""
        if message.author == bot.user:
            return

        # REQ-045 — «sí» a una confirmación pendiente llega sin mencionar al bot. Va antes
        # del filtro de mención: si se consume como respuesta, no es un mensaje para el
        # agente. Solo puede tener una pendiente quien ya fue atendido (y autorizado).
        if _responder_confirmacion(str(message.author.id), message.content or ""):
            return

        # Solo responder si se menciona al bot
        if bot.user not in message.mentions:
            await bot.process_commands(message)
            return

        # Control de acceso por identidad: quien no esté en `authorized_users.json` no es
        # atendido. Va antes de procesar el texto y antes de descargar adjuntos — un agente
        # con herramientas no distingue permisos por usuario, así que el corte tiene que
        # estar en la puerta. Fail-closed: sin archivo o sin la clave `discord`, nadie pasa.
        from core.authorized_users import UNAUTHORIZED_MESSAGE, is_authorized

        author_id = str(message.author.id)
        if not is_authorized("discord", author_id):
            logger.warning(
                f"Discord: mensaje rechazado de un remitente no autorizado "
                f"(id={author_id}, nombre={message.author.display_name!r})"
            )
            try:
                await message.reply(UNAUTHORIZED_MESSAGE)
            except Exception as e:
                logger.error(f"No se pudo avisar al remitente no autorizado: {e}")
            return

        # Limpiar la mención del texto
        text = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if not text and not message.attachments:
            text = "Hola"

        image_path = None
        if message.attachments:
            for att in message.attachments:
                if att.content_type and att.content_type.startswith('image/'):
                    temp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                    image_path = temp.name
                    temp.close()
                    await att.save(image_path)
                    break

        async with message.channel.typing():
            from core.user_identity import canonical_user_id

            result = await _procesar_con_confirmacion(
                author_id, message.channel.id,
                canonical_user_id("discord", message.author.id),
                message.author.display_name,
                text,
                image_path=image_path,
            )
            
        if image_path:
            try:
                os.unlink(image_path)
            except Exception as e:
                # Esperable (el archivo puede seguir abierto), pero no mudo: si los
                # temporales empiezan a acumularse, este es el unico rastro.
                logger.debug(f"no se pudo borrar el temporal: {e}")

        # Responder con embed elegante
        embed = discord.Embed(
            description=result[:4096],
            color=0x0096FF  # Azul estilo Noddoo
        )
        embed.set_footer(text=f"{agent} Assistant")
        await message.reply(embed=embed)

    # ── Comandos slash ─────────────────────────────────────────────

    @bot.tree.command(name="noddoo", description=f"Habla con {agent}")
    @app_commands.describe(mensaje=f"Tu pregunta o comando para {agent}")
    async def slash_noddoo(interaction: discord.Interaction, mensaje: str):
        from core.user_identity import canonical_user_id

        if not await _slash_autorizado(interaction, "noddoo"):
            return

        await interaction.response.defer()
        result = await _procesar_con_confirmacion(
            str(interaction.user.id), interaction.channel_id,
            canonical_user_id("discord", interaction.user.id),
            interaction.user.display_name,
            mensaje,
        )
        embed = discord.Embed(
            description=result[:4096],
            color=0x0096FF
        )
        embed.set_author(name=f"@{interaction.user.display_name} preguntó:", icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"{agent} Assistant")
        await interaction.followup.send(embed=embed)

    @bot.tree.command(name="limpiar", description=f"Reinicia la conversación con {agent}")
    async def slash_limpiar(interaction: discord.Interaction):
        if not await _slash_autorizado(interaction, "limpiar"):
            return
        try:
            from ai.claude_brain import clear_conversation
            clear_conversation()
        except Exception as e:
            # El usuario pidio empezar de cero: si no se pudo, decirlo. En silencio, el
            # agente sigue arrastrando la conversacion vieja y parece que ignora el pedido.
            logger.warning(f"no se pudo limpiar la conversacion: {e}")
        await interaction.response.send_message(
            f"Historial reiniciado. Listo para nuevas órdenes{vocative()}.",
            ephemeral=True
        )

    @bot.tree.command(name="ayuda", description=f"Ver comandos de {agent}")
    async def slash_ayuda(interaction: discord.Interaction):
        if not await _slash_autorizado(interaction, "ayuda"):
            return
        embed = discord.Embed(
            title=f"{agent} — Comandos",
            color=0x0096FF
        )
        embed.add_field(
            name="Cómo usar",
            value=f"• Menciona al bot: `@{agent} tu pregunta`\n• Usa `/noddoo tu pregunta`",
            inline=False
        )
        embed.add_field(
            name="Comandos slash",
            value="`/noddoo` — hacer una pregunta\n`/limpiar` — reiniciar conversación\n`/ayuda` — este menú",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    bot.run(token)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    run_discord_bot()
