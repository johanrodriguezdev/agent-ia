"""
channels/telegram_bot.py
Bot de Telegram para Glass — versión completa.

- Aislamiento por usuario (memoria y conversación separadas)
- Capturas de pantalla enviadas como foto al chat
- Apagar y reiniciar el PC desde Telegram
- Notas de voz nativas con edge-tts + FFmpeg
- Audio dividido en partes para textos largos
"""

import os
import re
import json
import asyncio
import tempfile
import logging
import subprocess
from pathlib import Path

logging.basicConfig(
    format="%(asctime)s [Telegram] %(levelname)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

GLASS_VOICE   = "es-CO-GonzaloNeural"
MAX_AUDIO_CHARS = 900


# ── Token ──────────────────────────────────────────────────────────

def _get_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if token:
        return token
    try:
        config_path = Path(__file__).parent.parent / "config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f).get("telegram_token", "")
    except Exception:
        return ""


# ── FFmpeg ─────────────────────────────────────────────────────────

def _has_ffmpeg() -> bool:
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False

FFMPEG_AVAILABLE = _has_ffmpeg()


# ── Limpieza TTS ───────────────────────────────────────────────────

def _clean_for_tts(text: str) -> str:
    text = re.sub(r'==+\s*[^=]+\s*==+', '', text)
    text = re.sub(r'\*{1,3}|_{1,3}|`{1,3}|~{1,2}', '', text)
    text = re.sub(r'https?://\S+|www\.\S+', '', text)
    text = re.sub(r'[•·▸►→←↑↓✅❌⚠️💡🔊💬✓✗]', '', text)
    text = re.sub(r'\([^)]{1,20}\)', '', text)
    text = re.sub(r'\n{2,}', '. ', text)
    text = re.sub(r'\n', ', ', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[,\s]+\.', '.', text)
    text = re.sub(r'\.{2,}', '.', text)
    return text.strip()


def _split_for_tts(text: str, max_chars: int = MAX_AUDIO_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    parts, current = [], ""
    sentences = re.split(r'(?<=[.!?])\s+', text)

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            sub_parts = re.split(r'(?<=,)\s+', sentence)
            for sub in sub_parts:
                if len(current) + len(sub) + 1 <= max_chars:
                    current += " " + sub if current else sub
                else:
                    if current:
                        parts.append(current.strip())
                    current = sub
        elif len(current) + len(sentence) + 1 <= max_chars:
            current += " " + sentence if current else sentence
        else:
            if current:
                parts.append(current.strip())
            current = sentence

    if current:
        parts.append(current.strip())

    return [p for p in parts if len(p) >= 10]


# ── TTS — Generar audio ────────────────────────────────────────────

async def _generate_audio(text: str) -> tuple[str | None, str]:
    try:
        import edge_tts

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            mp3_path = f.name

        communicate = edge_tts.Communicate(text, GLASS_VOICE)
        await communicate.save(mp3_path)

        if not Path(mp3_path).exists() or Path(mp3_path).stat().st_size < 500:
            try:
                os.unlink(mp3_path)
            except Exception:
                pass
            return None, "none"

        if FFMPEG_AVAILABLE:
            ogg_path = mp3_path.replace(".mp3", ".ogg")
            r = subprocess.run([
                "ffmpeg", "-i", mp3_path,
                "-c:a", "libopus", "-b:a", "64k",
                ogg_path, "-y", "-loglevel", "quiet"
            ], capture_output=True, timeout=30)
            try:
                os.unlink(mp3_path)
            except Exception:
                pass
            if r.returncode == 0 and Path(ogg_path).exists():
                return ogg_path, "voice"

        return mp3_path, "audio"

    except ImportError:
        logger.warning("edge-tts no instalado: pip install edge-tts")
        return None, "none"
    except Exception as e:
        logger.warning(f"TTS error: {e}")
        return None, "none"


async def send_voice_parts(update, text: str):
    """Divide el texto y envía cada parte como nota de voz."""
    clean = _clean_for_tts(text)
    if not clean:
        return

    parts = _split_for_tts(clean)
    logger.info(f"Enviando {len(parts)} parte(s) de audio")

    for i, part in enumerate(parts):
        try:
            await update.message.chat.send_action("record_voice")
        except Exception:
            pass

        audio_path, audio_type = await _generate_audio(part)
        if not audio_path or not Path(audio_path).exists():
            continue

        try:
            with open(audio_path, "rb") as af:
                if audio_type == "voice":
                    await update.message.reply_voice(voice=af)
                else:
                    await update.message.reply_audio(
                        audio=af, title="Glass", performer="Glass Assistant"
                    )
        except Exception as e:
            logger.warning(f"Error enviando parte {i+1}: {e}")
        finally:
            try:
                os.unlink(audio_path)
            except Exception:
                pass

        if i < len(parts) - 1:
            await asyncio.sleep(0.5)


# ── STT ────────────────────────────────────────────────────────────

def _transcribe_audio(audio_path: str) -> str:
    try:
        import whisper
        model = whisper.load_model("small")
        result = model.transcribe(audio_path, language="es")
        text = result.get("text", "").strip()
        if text:
            return text
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Whisper falló: {e}")

    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        with sr.AudioFile(audio_path) as src:
            audio = r.record(src)
        return r.recognize_google(audio, language="es-ES")
    except Exception as e:
        logger.warning(f"Google Speech falló: {e}")
        return ""


# ── Envío de respuesta ─────────────────────────────────────────────

async def _send_response(update, context, response, send_voice: bool = False):
    """
    Envía la respuesta completa:
    - Siempre: texto
    - Si hay image_path: foto (captura de pantalla)
    - Si send_voice: notas de voz
    """
    # Texto
    await _send_long_message(update, response.text)

    # Imagen (captura de pantalla)
    if response.image_path and Path(response.image_path).exists():
        try:
            with open(response.image_path, "rb") as img:
                await update.message.reply_photo(
                    photo=img,
                    caption="Captura de pantalla, Señor."
                )
        except Exception as e:
            logger.warning(f"Error enviando captura: {e}")
        finally:
            try:
                os.unlink(response.image_path)
            except Exception:
                pass

    # Voz
    if send_voice:
        await send_voice_parts(update, response.text)


async def _send_long_message(update, text: str):
    MAX = 4000
    if len(text) <= MAX:
        await update.message.reply_text(text)
        return

    chunks, current = [], ""
    for p in text.split("\n"):
        if len(current) + len(p) + 1 > MAX:
            if current:
                chunks.append(current.strip())
            current = p
        else:
            current += "\n" + p if current else p
    if current:
        chunks.append(current.strip())

    for i, chunk in enumerate(chunks):
        if i > 0:
            await asyncio.sleep(0.4)
        suffix = f"\n_(Parte {i+1}/{len(chunks)})_" if len(chunks) > 1 else ""
        await update.message.reply_text(chunk + suffix)


# ── Comandos ───────────────────────────────────────────────────────

async def cmd_start(update, context):
    from config_manager import get_agent_name
    agent = get_agent_name().upper()
    name = update.effective_user.first_name or "usuario"
    await update.message.reply_text(
        f"*Sistemas en línea, {name}.*\n\n"
        f"Soy *{agent}*, su asistente de IA personal.\n\n"
        f"*Formas de comunicarse:*\n"
        f"• Texto — cualquier pregunta o comando\n"
        f"• Voz — mándeme un audio y respondo con voz\n"
        f"• Imagen — la analizo y describo\n\n"
        f"*Comandos:*\n"
        f"/voz — activar respuestas con audio\n"
        f"/texto — solo texto\n"
        f"/memoria — ver mi historial\n"
        f"/limpiar — reiniciar conversación\n"
        f"/ayuda — todos los comandos\n\n"
        f"¿En qué puedo asistirle, Señor?",
        parse_mode="Markdown"
    )


async def cmd_ayuda(update, context):
    from config_manager import get_agent_name
    agent = get_agent_name().upper()
    await update.message.reply_text(
        f"*{agent} — Comandos disponibles*\n\n"
        f"*Respuesta:*\n"
        f"/voz — respuestas con nota de voz\n"
        f"/texto — solo texto\n\n"
        f"*Conversación:*\n"
        f"/memoria — ver historial de conversaciones\n"
        f"/limpiar — reiniciar conversación\n"
        f"/estado — verificar sistemas\n\n"
        f"*Control del PC:*\n"
        f"'toma una captura' — foto de pantalla al chat\n"
        f"'apaga el pc' — apagar equipo en 10 segundos\n"
        f"'reinicia el pc' — reiniciar equipo en 10 segundos\n"
        f"'qué hora es' — hora actual\n"
        f"'info del sistema' — specs del PC\n"
        f"'cuánta RAM tengo' — memoria disponible\n"
        f"'uso del CPU' — estado del procesador",
        parse_mode="Markdown"
    )


async def cmd_voz(update, context):
    context.user_data["voice_mode"] = True
    ffmpeg_info = "Nota de voz nativa" if FFMPEG_AVAILABLE else "Archivo MP3 (instala FFmpeg para nota de voz nativa)"
    await update.message.reply_text(
        f"*Modo voz activado, Señor.*\n\n"
        f"Voz: {GLASS_VOICE}\n"
        f"Audio: {ffmpeg_info}\n\n"
        f"Use /texto para desactivarlo.",
        parse_mode="Markdown"
    )


async def cmd_texto(update, context):
    context.user_data["voice_mode"] = False
    await update.message.reply_text(
        "Modo texto activado, Señor. Solo responderé con texto."
    )


async def cmd_memoria(update, context):
    """Muestra el historial de conversaciones del usuario."""
    from ai.user_manager import registry
    user = update.effective_user
    session = registry.get_or_create(
        user_id=str(user.id),
        user_name=user.first_name or "Usuario",
        channel="telegram"
    )
    summary = session.get_memory_summary()
    await update.message.reply_text(
        f"*Registros de {user.first_name}*\n\n{summary}",
        parse_mode="Markdown"
    )


async def cmd_limpiar(update, context):
    from ai.user_manager import registry
    user = update.effective_user
    session = registry.get(str(user.id), "telegram")
    if session:
        session.clear_history()
    await update.message.reply_text(
        "Historial de conversación reiniciado, Señor. Listo para nuevas órdenes."
    )


async def cmd_estado(update, context):
    import datetime
    from ai.user_manager import registry

    now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    voice_mode = context.user_data.get("voice_mode", False)

    try:
        import edge_tts
        tts_status = f"edge-tts ({GLASS_VOICE})"
    except ImportError:
        tts_status = "No instalado (pip install edge-tts)"

    ffmpeg_status = "Nota de voz nativa" if FFMPEG_AVAILABLE else "Sin FFmpeg (winget install ffmpeg)"

    await update.message.reply_text(
        f"*Estado de Glass — {now}*\n\n"
        f"Bot Telegram: Activo\n"
        f"Motor IA: Operativo\n"
        f"Usuarios activos: {registry.active_count()}\n"
        f"Motor de voz: {tts_status}\n"
        f"FFmpeg: {ffmpeg_status}\n"
        f"Modo: {'Voz' if voice_mode else 'Texto'}",
        parse_mode="Markdown"
    )


# ── Handlers de mensajes ───────────────────────────────────────────

async def handle_text(update, context):
    from channels.gateway import GlassGateway, GlassMessage, MessageType

    user = update.effective_user
    text = (update.message.text or "").strip()
    if not text:
        return

    voice_mode = context.user_data.get("voice_mode", False)
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    # Detectar comandos de PC en texto libre
    text_lower = text.lower()
    if any(w in text_lower for w in ["apaga el pc", "apagar el pc", "apaga la pc", "apagar la computadora"]):
        await _handle_shutdown(update, context, voice_mode)
        return

    if any(w in text_lower for w in ["reinicia el pc", "reiniciar el pc", "reinicia la pc", "reiniciar el equipo"]):
        await _handle_restart(update, context, voice_mode)
        return

    msg = GlassMessage(
        user_id=str(user.id),
        user_name=user.first_name or "Usuario",
        text=text, channel="telegram",
        msg_type=MessageType.TEXT
    )
    response = GlassGateway().process(msg)
    await _send_response(update, context, response, send_voice=voice_mode)


async def handle_voice(update, context):
    from channels.gateway import GlassGateway, GlassMessage, MessageType

    user = update.effective_user

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="record_voice"
    )

    vf = await context.bot.get_file(update.message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        tmp = f.name
    await vf.download_to_drive(tmp)

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    transcribed = _transcribe_audio(tmp)
    try:
        os.unlink(tmp)
    except Exception:
        pass

    if not transcribed:
        await update.message.reply_text(
            "No pude entender el audio, Señor. ¿Podría repetirlo?"
        )
        return

    await update.message.reply_text(
        f"_Escuché: \"{transcribed}\"_", parse_mode="Markdown"
    )

    # Detectar comandos de PC en voz
    text_lower = transcribed.lower()
    if any(w in text_lower for w in ["apaga el pc", "apagar el pc", "apaga la pc"]):
        await _handle_shutdown(update, context, send_voice=True)
        return

    if any(w in text_lower for w in ["reinicia el pc", "reiniciar el pc", "reinicia la pc"]):
        await _handle_restart(update, context, send_voice=True)
        return

    msg = GlassMessage(
        user_id=str(user.id),
        user_name=user.first_name or "Usuario",
        text=transcribed, channel="telegram",
        msg_type=MessageType.VOICE
    )
    response = GlassGateway().process(msg)
    await _send_response(update, context, response, send_voice=True)


# ── Acciones del PC ────────────────────────────────────────────────

async def _handle_shutdown(update, context, send_voice: bool = False):
    """Apaga el PC con confirmación y cuenta regresiva."""
    msg = (
        "Iniciando secuencia de apagado, Señor.\n"
        "El equipo se apagará en 10 segundos.\n\n"
        "Envíe 'cancela apagado' para abortar."
    )
    await update.message.reply_text(msg)

    if send_voice:
        await send_voice_parts(update, msg)

    try:
        import os as _os
        _os.system("shutdown /s /t 10")
    except Exception as e:
        await update.message.reply_text(f"Error al iniciar apagado: {e}")


async def _handle_restart(update, context, send_voice: bool = False):
    """Reinicia el PC con cuenta regresiva."""
    msg = (
        "Iniciando secuencia de reinicio, Señor.\n"
        "El equipo se reiniciará en 10 segundos.\n\n"
        "Envíe 'cancela reinicio' para abortar."
    )
    await update.message.reply_text(msg)

    if send_voice:
        await send_voice_parts(update, msg)

    try:
        import os as _os
        _os.system("shutdown /r /t 10")
    except Exception as e:
        await update.message.reply_text(f"Error al iniciar reinicio: {e}")


async def handle_photo(update, context):
    user = update.effective_user
    caption = update.message.caption or "Describe esta imagen en detalle en español."
    voice_mode = context.user_data.get("voice_mode", False)

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    photo = update.message.photo[-1]
    pf = await context.bot.get_file(photo.file_id)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        tmp = f.name
    await pf.download_to_drive(tmp)

    try:
        import anthropic, base64
        with open(tmp, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        resp = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=1024,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg", "data": data
                }},
                {"type": "text",
                 "text": f"Eres GLASS, asistente formal tipo JARVIS. Responde en español: {caption}"}
            ]}]
        )
        result = resp.content[0].text
    except Exception as e:
        result = f"No pude analizar la imagen, Señor: {str(e)[:80]}"
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass

    from channels.gateway import GlassResponse
    await _send_response(
        update, context,
        GlassResponse(text=result),
        send_voice=voice_mode
    )


async def handle_error(update, context):
    logger.error(f"Error: {context.error}")
    if update and update.message:
        await update.message.reply_text(
            "Error inesperado, Señor. Por favor intente de nuevo."
        )


# ── Punto de entrada ───────────────────────────────────────────────

def run_telegram_bot():
    try:
        from telegram.ext import (
            Application, CommandHandler, MessageHandler, filters
        )
    except ImportError:
        print("\n[Error] pip install python-telegram-bot==20.7\n")
        return

    token = _get_token()
    if not token:
        print("\n[Error] Sin token en config.json\n")
        return

    try:
        from config_manager import get_agent_name
        agent = get_agent_name().upper()
    except Exception:
        agent = "GLASS"

    print(f"\n{'='*50}")
    print(f"  {agent} — Bot Telegram completo")
    print(f"  Voz: {GLASS_VOICE}")
    print(f"  FFmpeg: {'Nota de voz nativa' if FFMPEG_AVAILABLE else 'Sin FFmpeg'}")
    print(f"  Aislamiento: por usuario activo")
    print(f"  PC: apagado / reinicio / captura activados")
    print(f"  /voz en Telegram para activar audio")
    print(f"  Ctrl+C para detener")
    print(f"{'='*50}\n")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("ayuda",   cmd_ayuda))
    app.add_handler(CommandHandler("help",    cmd_ayuda))
    app.add_handler(CommandHandler("voz",     cmd_voz))
    app.add_handler(CommandHandler("texto",   cmd_texto))
    app.add_handler(CommandHandler("memoria", cmd_memoria))
    app.add_handler(CommandHandler("limpiar", cmd_limpiar))
    app.add_handler(CommandHandler("estado",  cmd_estado))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_text
    ))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_error_handler(handle_error)

    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    run_telegram_bot()
