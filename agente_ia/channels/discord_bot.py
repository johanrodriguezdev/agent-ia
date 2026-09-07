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

            result = _process_message(
                canonical_user_id("discord", message.author.id),
                message.author.display_name,
                text,
                image_path=image_path
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
        result = _process_message(
            canonical_user_id("discord", interaction.user.id),
            interaction.user.display_name,
            mensaje
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
