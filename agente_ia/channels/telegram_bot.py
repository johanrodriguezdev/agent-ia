"""
channels/telegram_bot.py
Bot de Telegram para Glass — Audio dividido en partes, sin cortes.

Mejoras:
  - Textos largos se dividen en múltiples audios seguidos (sin cortar frases)
  - Limpieza profunda del texto antes de TTS (sin marcadores wiki, markdown, etc.)
  - Notas de voz nativas con FFmpeg (OGG/OPUS)
  - Fallback a archivo MP3 si no hay FFmpeg

Requisitos:
  pip install edge-tts python-telegram-bot==20.7
  winget install ffmpeg
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

GLASS_VOICE = "es-CO-GonzaloNeural"

# Máximo de caracteres por audio — balance entre calidad y velocidad
# 900 chars ≈ 45-60 segundos de audio, suficiente para respuestas completas
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


# ── Limpieza de texto para TTS ─────────────────────────────────────

def _clean_for_tts(text: str) -> str:
    """
    Limpieza profunda del texto antes de enviarlo al motor de voz.
    Elimina todos los elementos que suenan mal o generan desorden en audio.
    """
    # 1. Eliminar marcadores de Wikipedia (== Título ==)
    text = re.sub(r'==+\s*[^=]+\s*==+', '', text)

    # 2. Eliminar markdown de Telegram
    text = re.sub(r'\*{1,3}', '', text)   # negrita
    text = re.sub(r'_{1,3}', '', text)    # cursiva
    text = re.sub(r'`{1,3}', '', text)    # código
    text = re.sub(r'~{1,2}', '', text)    # tachado

    # 3. Eliminar URLs (suenan horribles en TTS)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)

    # 4. Eliminar emojis y símbolos especiales
    text = re.sub(r'[•·▸▹►▻→←↑↓]', '', text)
    text = re.sub(r'[✅❌⚠️💡🔊💬✓✗]', '', text)

    # 5. Eliminar paréntesis con contenido corto (siglas, refs)
    text = re.sub(r'\([^)]{1,20}\)', '', text)

    # 6. Limpiar líneas con solo guiones o asteriscos
    text = re.sub(r'^[\s\-\*_=]+$', '', text, flags=re.MULTILINE)

    # 7. Reemplazar saltos de línea por pausas naturales
    text = re.sub(r'\n{2,}', '. ', text)
    text = re.sub(r'\n', ', ', text)

    # 8. Limpiar espacios múltiples y puntuación repetida
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[,\s]+\.', '.', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r',{2,}', ',', text)

    # 9. Eliminar caracteres no pronunciables
    text = re.sub(r'[<>\[\]{}|\\^~]', '', text)

    return text.strip()


def _split_for_tts(text: str, max_chars: int = MAX_AUDIO_CHARS) -> list[str]:
    """
    Divide el texto en bloques para TTS respetando oraciones completas.
    Nunca corta en medio de una oración.
    Retorna lista de strings, cada uno <= max_chars.
    """
    if len(text) <= max_chars:
        return [text]

    parts = []
    # Dividir por oraciones (punto + espacio, signos de interrogación/exclamación)
    sentences = re.split(r'(?<=[.!?])\s+', text)

    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Si la oración sola ya supera el límite, dividir por comas
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

    # Filtrar partes vacías o muy cortas (menos de 10 chars)
    return [p for p in parts if len(p) >= 10]


# ── TTS — Generar audio ────────────────────────────────────────────

async def _generate_single_audio(text: str) -> tuple[str | None, str]:
    """
    Genera un archivo de audio para un bloque de texto.
    Retorna (ruta, tipo) donde tipo es 'voice' (OGG) o 'audio' (MP3).
    """
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

        # Con FFmpeg → OGG para nota de voz nativa
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
        return None, "none"
    except Exception as e:
        logger.warning(f"Error generando audio: {e}")
        return None, "none"


async def send_voice_parts(update, text: str):
    """
    Divide el texto en partes y envía cada una como nota de voz separada.
    El usuario recibe todas las partes seguidas sin cortes de frases.
    """
    clean = _clean_for_tts(text)
    if not clean:
        return

    parts = _split_for_tts(clean)
    total = len(parts)

    logger.info(f"Enviando {total} parte(s) de audio")

    for i, part in enumerate(parts):
        try:
            await update.message.chat.send_action("record_voice")
        except Exception:
            pass

        audio_path, audio_type = await _generate_single_audio(part)

        if not audio_path or not Path(audio_path).exists():
            logger.warning(f"No se generó audio para parte {i+1}")
            continue

        try:
            with open(audio_path, "rb") as af:
                if audio_type == "voice":
                    await update.message.reply_voice(voice=af)
                else:
                    await update.message.reply_audio(
                        audio=af,
                        title=f"Glass {'('+str(i+1)+'/'+str(total)+')' if total > 1 else ''}",
                        performer="Glass Assistant"
                    )
        except Exception as e:
            logger.warning(f"Error enviando parte {i+1}: {e}")
        finally:
            try:
                os.unlink(audio_path)
            except Exception:
                pass

        # Pequeña pausa entre partes para que lleguen en orden
        if i < total - 1:
            await asyncio.sleep(0.5)


# ── STT — Transcribir audio ────────────────────────────────────────

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

async def _send_response(update, text: str, send_voice: bool = False):
    """Envía texto siempre. Si send_voice=True, también envía audio(s)."""
    await _send_long_message(update, text)

    if send_voice:
        await send_voice_parts(update, text)


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
        f"• Voz — envíe un audio y respondo con voz\n"
        f"• Imagen — la analizo y describo\n\n"
        f"*Comandos:*\n"
        f"/voz — activar respuestas con audio\n"
        f"/texto — solo texto\n"
        f"/ayuda — todos los comandos\n"
        f"/limpiar — reiniciar conversación\n"
        f"/estado — verificar sistemas\n\n"
        f"¿En qué puedo asistirle, Señor?",
        parse_mode="Markdown"
    )


async def cmd_ayuda(update, context):
    from config_manager import get_agent_name
    agent = get_agent_name().upper()
    await update.message.reply_text(
        f"*{agent} — Comandos disponibles*\n\n"
        f"*Modo de respuesta:*\n"
        f"/voz — Glass responde con nota de voz\n"
        f"/texto — solo respuestas de texto\n\n"
        f"*Conversación:*\n"
        f"/limpiar — reiniciar conversación\n"
        f"/estado — verificar sistemas\n"
        f"/ayuda — este menú\n\n"
        f"*Control del PC:*\n"
        f"'apaga el pc' — apagar equipo\n"
        f"'reinicia el pc' — reiniciar equipo\n"
        f"'toma una captura' — foto de pantalla al chat\n"
        f"'qué hora es' — hora actual\n"
        f"'info del sistema' — specs del PC\n"
        f"'cuánta RAM tengo' — memoria disponible\n"
        f"'uso del CPU' — procesador actual",
        parse_mode="Markdown"
    )


async def cmd_voz(update, context):
    context.user_data["voice_mode"] = True
    ffmpeg_info = "Nota de voz nativa activa" if FFMPEG_AVAILABLE else (
        "Archivo de audio (instala FFmpeg para nota de voz:\nwinget install ffmpeg)"
    )
    await update.message.reply_text(
        f"*Modo voz activado, Señor.*\n\n"
        f"Voz: {GLASS_VOICE}\n"
        f"FFmpeg: {ffmpeg_info}\n\n"
        f"Textos largos se enviarán en varias notas de voz seguidas.\n"
        f"Use /texto para desactivarlo.",
        parse_mode="Markdown"
    )


async def cmd_texto(update, context):
    context.user_data["voice_mode"] = False
    await update.message.reply_text(
        "Modo texto activado, Señor. Solo responderé con texto."
    )


async def cmd_limpiar(update, context):
    try:
        from ai.claude_brain import clear_conversation
        clear_conversation()
    except Exception:
        pass
    await update.message.reply_text(
        "Historial reiniciado, Señor. Listo para nuevas órdenes."
    )


async def cmd_estado(update, context):
    import datetime
    now = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    voice_mode = context.user_data.get("voice_mode", False)

    try:
        import edge_tts
        tts_status = f"edge-tts ({GLASS_VOICE})"
    except ImportError:
        tts_status = "No instalado (pip install edge-tts)"

    ffmpeg_status = "Nota de voz nativa" if FFMPEG_AVAILABLE else "Sin FFmpeg — archivo MP3"

    await update.message.reply_text(
        f"*Estado de Glass — {now}*\n\n"
        f"Bot Telegram: Activo\n"
        f"Motor IA: Operativo\n"
        f"Memoria: Funcionando\n"
        f"Motor de voz: {tts_status}\n"
        f"FFmpeg: {ffmpeg_status}\n"
        f"Modo actual: {'Voz' if voice_mode else 'Texto'}\n"
        f"Limite audio: {MAX_AUDIO_CHARS} chars por nota",
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

    msg = GlassMessage(
        user_id=str(user.id),
        user_name=user.first_name or "Usuario",
        text=text, channel="telegram",
        msg_type=MessageType.TEXT
    )
    response = GlassGateway().process(msg)
    await _send_response(update, response.text, send_voice=voice_mode)


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
            "No pude entender el audio, Señor. ¿Podría repetirlo o escribirlo?"
        )
        return

    await update.message.reply_text(
        f"_Escuché: \"{transcribed}\"_", parse_mode="Markdown"
    )

    msg = GlassMessage(
        user_id=str(user.id),
        user_name=user.first_name or "Usuario",
        text=transcribed, channel="telegram",
        msg_type=MessageType.VOICE
    )
    response = GlassGateway().process(msg)
    # Siempre con voz cuando el usuario habló
    await _send_response(update, response.text, send_voice=True)


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
                {"type": "text", "text": f"Eres GLASS, asistente formal tipo JARVIS. Responde en español concisamente: {caption}"}
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

    await _send_response(update, result, send_voice=voice_mode)


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
    print(f"  {agent} — Bot Telegram activo")
    print(f"  Voz: {GLASS_VOICE}")
    print(f"  FFmpeg: {'Nota de voz nativa' if FFMPEG_AVAILABLE else 'No disponible'}")
    print(f"  Limite audio: {MAX_AUDIO_CHARS} chars por nota")
    print(f"  /voz en Telegram para activar audio")
    print(f"  Ctrl+C para detener")
    print(f"{'='*50}\n")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("ayuda",   cmd_ayuda))
    app.add_handler(CommandHandler("help",    cmd_ayuda))
    app.add_handler(CommandHandler("voz",     cmd_voz))
    app.add_handler(CommandHandler("texto",   cmd_texto))
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
