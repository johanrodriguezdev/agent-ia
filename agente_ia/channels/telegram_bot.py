"""
channels/telegram_bot.py
Bot de Telegram para Noddoo — versión completa.

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
from core.address import vocative, vocative_start

logging.basicConfig(
    format="%(asctime)s [Telegram] %(levelname)s: %(message)s",
    level=logging.INFO
)

# `httpx` registra cada peticion con la URL COMPLETA, y en la API de Telegram el token va
# dentro de la URL:
#
#     HTTP Request: POST https://api.telegram.org/bot<ID>:<TOKEN>/getUpdates "200 OK"
#
# Son varias lineas por minuto, cada una con la credencial entera. Antes eso solo ensuciaba
# una consola; desde que el canal corre en una pestaña de la terminal de la app, esa salida
# la guarda `TerminalSession` en su scrollback — y `terminal_read_output` puede mandarsela
# al proveedor del modelo. El gate de esa herramienta existe justamente porque "en una
# terminal puede haber quedado impresa una clave" (.claude/rules/security-levels.md); no
# hay por que ponersela delante.
#
# Se sube a WARNING: los fallos de red se siguen viendo, el trafico normal no.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

GLASS_VOICE   = "es-ES-AlvaroNeural"
MAX_AUDIO_CHARS = 900


# ── Token ──────────────────────────────────────────────────────────

def _get_token() -> str:
    from config_manager import get_telegram_token
    return get_telegram_token()


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

    try:
        from config_manager import get_agent_name, get_agent_pronunciation
        agent_name = get_agent_name()
        agent_pron = get_agent_pronunciation()
        if agent_name.lower() != agent_pron.lower():
            # Reemplazar ignorando mayúsculas/minúsculas usando re. `re.escape` es
            # obligatorio: el nombre viene de Configuración y puede traer puntos
            # ("O.R.I.O.N", donde `.` sería comodín) o paréntesis, que sin escapar rompen
            # la expresión. `\b` solo aplica si el nombre termina en carácter de palabra.
            pattern = (r'(?i)\b' + re.escape(agent_name)
                       + (r'\b' if agent_name[-1:].isalnum() else ''))
            text = re.sub(pattern, agent_pron, text)
    except Exception as e:
        # Sin esto, el agente se pronuncia con el nombre escrito en vez del fonetico y no
        # hay forma de saber por que (el texto sale igual, solo suena mal).
        logger.warning(f"no se pudo aplicar la pronunciacion del agente: {e}")

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
            except Exception as e:
                # Esperable (el archivo puede seguir abierto), pero no mudo: si los
                # temporales empiezan a acumularse, este es el unico rastro.
                logger.debug(f"no se pudo borrar el temporal: {e}")
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
            except Exception as e:
                # Esperable (el archivo puede seguir abierto), pero no mudo: si los
                # temporales empiezan a acumularse, este es el unico rastro.
                logger.debug(f"no se pudo borrar el temporal: {e}")
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
        except Exception as e:
            logger.debug(f"no se pudo mostrar 'grabando audio' en el chat: {e}")

        audio_path, audio_type = await _generate_audio(part)
        if not audio_path or not Path(audio_path).exists():
            continue

        try:
            with open(audio_path, "rb") as af:
                if audio_type == "voice":
                    await update.message.reply_voice(voice=af)
                else:
                    await update.message.reply_audio(
                        audio=af, title="Noddoo", performer="Noddoo Assistant"
                    )
        except Exception as e:
            logger.warning(f"Error enviando parte {i+1}: {e}")
        finally:
            try:
                os.unlink(audio_path)
            except Exception as e:
                # Esperable (el archivo puede seguir abierto), pero no mudo: si los
                # temporales empiezan a acumularse, este es el unico rastro.
                logger.debug(f"no se pudo borrar el temporal: {e}")

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
        # Whisper es opcional (no esta en requirements.txt): sin el, la transcripcion local
        # no esta disponible y se sigue por el camino de siempre. Se deja dicho para que
        # "no me transcribe los audios" tenga una explicacion a mano.
        logger.info("transcripcion local no disponible: falta el paquete 'whisper'")
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
                    caption=f"Captura de pantalla{vocative()}."
                )
        except Exception as e:
            logger.warning(f"Error enviando captura: {e}")
        finally:
            try:
                os.unlink(response.image_path)
            except Exception as e:
                # Esperable (el archivo puede seguir abierto), pero no mudo: si los
                # temporales empiezan a acumularse, este es el unico rastro.
                logger.debug(f"no se pudo borrar el temporal: {e}")

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
        f"¿En qué puedo asistirle{vocative()}?",
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
        f"/detener — frenar lo que está haciendo\n"
        f"/estado — verificar sistemas\n"
        f"/skills — administrar módulos (skills)\n\n"
        f"*Tareas y Recordatorios:*\n"
        f"/tareas — ver tareas pendientes\n"
        f"/nueva [texto] — crear tarea rápida\n"
        f"/completar [id] — marcar tarea como hecha\n"
        f"/eliminar [id] — eliminar tarea\n"
        f"O diga: 'recuérdame mañana a las 9am...'\n\n"
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
        f"*Modo voz activado{vocative()}.*\n\n"
        f"Voz: {GLASS_VOICE}\n"
        f"Audio: {ffmpeg_info}\n\n"
        f"Use /texto para desactivarlo.",
        parse_mode="Markdown"
    )


async def cmd_texto(update, context):
    context.user_data["voice_mode"] = False
    await update.message.reply_text(
        f"Modo texto activado{vocative()}. Solo responderé con texto."
    )


async def cmd_memoria(update, context):
    """Muestra el historial de conversaciones del usuario."""
    from ai.user_manager import registry
    user = update.effective_user
    session = registry.get_or_create(
        user_id=_owner_uid(user),
        user_name=user.first_name or "Usuario",
        channel="telegram"
    )
    summary = session.get_memory_summary()
    await update.message.reply_text(
        f"*Registros de {user.first_name}*\n\n{summary}",
        parse_mode="Markdown"
    )


async def cmd_detener(update, context):
    """`/detener`: frena el turno en curso de ESTE usuario (REQ-047).

    Es el botón de detener del escritorio, para el celular. Cooperativo: el turno para en
    el próximo punto seguro (antes de la siguiente llamada al modelo o de la siguiente
    herramienta), así que puede tardar lo que tarde la llamada en curso. Llega mientras el
    turno corre porque la Application procesa updates en concurrencia (REQ-018).
    """
    from core import cancelacion

    clave = cancelacion.clave_remota("telegram", _owner_uid(update.effective_user))
    if cancelacion.cancelar_remoto(clave):
        texto = f"Deteniendo{vocative()}. Paro en cuanto termine lo que está haciendo ahora."
    else:
        texto = f"No hay nada en curso que detener{vocative()}."
    await update.message.reply_text(texto)


async def cmd_limpiar(update, context):
    from ai.user_manager import registry
    user = update.effective_user
    session = registry.get(_owner_uid(user), "telegram")
    if session:
        session.clear_history()
    await update.message.reply_text(
        f"Historial de conversación reiniciado{vocative()}. Listo para nuevas órdenes."
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
        f"*Estado de Noddoo — {now}*\n\n"
        f"Bot Telegram: Activo\n"
        f"Motor IA: Operativo\n"
        f"Usuarios activos: {registry.active_count()}\n"
        f"Motor de voz: {tts_status}\n"
        f"FFmpeg: {ffmpeg_status}\n"
        f"Modo: {'Voz' if voice_mode else 'Texto'}",
        parse_mode="Markdown"
    )


async def cmd_skills(update, context):
    try:
        from skills.skill_manager import skill_manager
        skill_list = "\n".join([f"• *{s.name}*: {s.description}" for s in skill_manager.skills])
        if not skill_list:
            skill_list = "No hay skills cargadas en el sistema modular."
        await update.message.reply_text(f"*Panel de Skills (Módulos)*\n\n{skill_list}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error cargando el panel de skills: {e}")


# ── Comandos de Tareas y Recordatorios ─────────────────────────────

async def cmd_tareas(update, context):
    """Muestra las tareas pendientes del usuario."""
    from core.security_manager import ChannelType
    from agents.tool_registry import execute_tool

    user = update.effective_user
    user_id = str(user.id)
    # REQ-018/CA-10 — reemplazo limpio: task_list es GREEN, execute_tool() no cambia el
    # comportamiento observable, solo agrega auditoría en audit.db. Si algún cambio futuro
    # bloqueara esta acción, ActionDenied llegaría a handle_error() (error handler global,
    # ya registrado) — fail-safe aceptable, sin try/except especial para este caso.
    summary = execute_tool("task_list", {"user_id": user_id}, ChannelType.TELEGRAM, user_id=user_id)
    await update.message.reply_text(summary, parse_mode="Markdown")


async def cmd_nueva(update, context):
    """Crea una nueva tarea. Uso: /nueva recuérdame mañana a las 9am llamar al banco"""
    from tasks.task_manager import task_manager
    from core.security_manager import security_manager, ChannelType, format_details

    user = update.effective_user
    user_id = str(user.id)
    text = " ".join(context.args) if context.args else ""

    if not text:
        await update.message.reply_text(
            f"*¿Qué tarea desea agregar{vocative()}?*\n\n"
            "Uso: /nueva [descripción de la tarea]\n\n"
            "Ejemplos:\n"
            "• /nueva recuérdame mañana a las 9am llamar al banco\n"
            "• /nueva entregar informe el viernes\n"
            "• /nueva todos los lunes revisar correos\n\n"
            "También puede simplemente decirme:\n"
            "'Recuérdame mañana a las 9am llamar al banco'",
            parse_mode="Markdown"
        )
        return

    # REQ-018/CA-10 — mismo gate público que execute_tool() usa internamente, solo para
    # que la invocación quede auditada en audit.db (GREEN, sin efecto en el resultado ni
    # bloqueo posible). No se usa execute_tool("task_create", ...) porque
    # agents/tool_registry.py::_task_create_invoke() no replica el fallback de "tarea
    # simple" de este comando (ver arquitectura-018.md §3, decisión CA-10).
    security_manager.require_confirmation(
        "task_create", ChannelType.TELEGRAM,
        details=format_details("tool:task_create", {"text": text, "user_id": user_id}),
        user_id=user_id,
    )

    result = task_manager.create_from_natural(text, user_id, "telegram")
    if result:
        msg = task_manager.format_task_created(result)
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        # Si no parseó como tarea natural, crear como tarea simple
        import datetime
        remind_at = datetime.datetime.now() + datetime.timedelta(hours=1)
        task_id = task_manager.create_task(
            user_id=str(user.id),
            title=text,
            channel="telegram",
            remind_at=remind_at.isoformat()
        )
        await update.message.reply_text(
            f"✅ *Tarea registrada{vocative()}.*\n\n"
            f"📋 *{text}*\n"
            f"🆔 #{task_id}\n"
            f"⏰ Recordatorio: en 1 hora\n\n"
            f"Le notificaré en el momento indicado.",
            parse_mode="Markdown"
        )


async def cmd_completar(update, context):
    """Marca una tarea como completada. Uso: /completar [id]"""
    from tasks.task_manager import task_manager
    from core.security_manager import security_manager, ChannelType, format_details

    user = update.effective_user
    user_id = str(user.id)

    if not context.args:
        await update.message.reply_text(
            f"Indique el número de tarea{vocative()}.\n"
            "Uso: /completar [id]\n\n"
            "Use /tareas para ver sus tareas pendientes."
        )
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"El ID de tarea debe ser un número{vocative()}.")
        return

    # REQ-018/CA-10 — mismo criterio que cmd_nueva(): auditoría vía require_confirmation()
    # directo, sin execute_tool() (el tool task_complete espera texto libre + su propio
    # regex de extracción de ID, con ramas de auto-completar/pedir aclaración que este
    # comando no tiene hoy — ver arquitectura-018.md §3).
    security_manager.require_confirmation(
        "task_complete", ChannelType.TELEGRAM,
        details=format_details("tool:task_complete", {"text": str(task_id), "user_id": user_id}),
        user_id=user_id,
    )

    success = task_manager.complete_task(task_id, user_id)
    if success:
        await update.message.reply_text(
            f"☑️ *Tarea #{task_id} completada.*\n\n"
            f"Excelente trabajo{vocative()}. Tarea archivada.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"No encontré la tarea #{task_id} en sus pendientes{vocative()}."
        )


async def cmd_eliminar(update, context):
    """Elimina una tarea. Uso: /eliminar [id]"""
    from tasks.task_manager import task_manager
    from core.security_manager import security_manager, ChannelType
    from channels.telegram_confirmation_adapter import telegram_confirmation_adapter

    user = update.effective_user
    user_id = str(user.id)

    if not context.args:
        await update.message.reply_text(
            f"Indique el número de tarea{vocative()}.\n"
            "Uso: /eliminar [id]\n\n"
            "Use /tareas para ver sus tareas."
        )
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(f"El ID de tarea debe ser un número{vocative()}.")
        return

    # REQ-018/CA-09, Hallazgo E (security-audit-018.md, re-chequeo) — reserva SÍNCRONA,
    # en este mismo Task, ANTES de lanzar el hilo worker de asyncio.to_thread(). Es la
    # verificación atómica y autoritativa: cierra por completo (no solo acota) la ventana
    # donde un segundo mensaje casi simultáneo del mismo usuario podía llegar antes de que
    # la entrada existiera en _pending (que antes se insertaba recién dentro de confirm(),
    # ya en el hilo worker).
    if not telegram_confirmation_adapter.reserve_pending(user_id):
        await update.message.reply_text(
            f"Ya tenés una confirmación pendiente{vocative()} — respondé sí/no primero."
        )
        return

    telegram_confirmation_adapter.set_request_context(user_id, update.effective_chat.id)

    # REQ-018/CA-01, CA-08 — require_confirmation() es síncrono y, para 'delete_task' en
    # Telegram, ahora bloquea (vía el adaptador) hasta 120s esperando la respuesta del
    # usuario. Corre en un hilo worker (asyncio.to_thread) para no bloquear el loop de
    # asyncio de python-telegram-bot — otros usuarios siguen operando con normalidad
    # mientras este usuario tiene una confirmación pendiente (CA-08, Hallazgo A —
    # requiere .concurrent_updates(True) en run_telegram_bot(), ver más abajo).
    confirmed = await asyncio.to_thread(
        security_manager.require_confirmation,
        "delete_task",
        ChannelType.TELEGRAM,
        details=f"task_id={task_id}",
        user_id=user_id,
    )

    if not confirmed:
        await update.message.reply_text(
            f"Eliminación de la tarea #{task_id} cancelada{vocative()}."
        )
        return

    success = task_manager.delete_task(task_id, user_id)
    if success:
        await update.message.reply_text(
            f"🗑 *Tarea #{task_id} eliminada{vocative()}.*",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"No encontré la tarea #{task_id} en su lista{vocative()}."
        )


# ── Handlers de mensajes ───────────────────────────────────────────


def _owner_uid(user) -> str:
    """Return el `user_id` canonico con el que guardar y buscar la memoria.

    Todas las identidades autorizadas son el mismo dueno, asi que lo que se cuenta por
    Telegram y lo que se dice por voz en el escritorio acaban en el mismo espacio. NO se usa
    para las confirmaciones pendientes (esas identifican una sesion de chat concreta: dos
    autorizados no deben poder responderse la confirmacion el uno al otro) ni para la
    auditoria de `require_confirmation()`, que necesita saber quien lo pidio de verdad.
    """
    from core.user_identity import canonical_user_id

    return canonical_user_id("telegram", getattr(user, "id", None))

async def _intercept_confirmacion_pendiente(update, context):
    """Handler de máxima prioridad (group=-1) — intercepta CUALQUIER mensaje de texto,
    incluidos comandos slash, cuando el usuario que lo envía tiene una confirmación
    pendiente (REQ-018, CA-05; "Casos borde" de SPEC-018.md: un comando nuevo mientras hay
    confirmación pendiente se consume como respuesta, no se ejecuta). Los
    CommandHandler/MessageHandler de group=0 (incluido handle_text) nunca ven el update si
    esto lo consume — se corta la propagación con ApplicationHandlerStop.

    Registrado con filters.TEXT SIN excluir comandos (a diferencia de handle_text, que sí
    los excluye) — necesita capturar también los comandos, porque el caso borde de la SPEC
    (/tareas, /nueva algo mientras hay confirmación pendiente) exige que ese mensaje se
    consuma como respuesta a la confirmación, no que dispare su propio CommandHandler."""
    from telegram.ext import ApplicationHandlerStop
    from channels.telegram_confirmation_adapter import telegram_confirmation_adapter

    message = update.message
    if message is None or not message.text:
        return
    user = update.effective_user
    if user is None:
        return

    if telegram_confirmation_adapter.resolve(str(user.id), message.text):
        raise ApplicationHandlerStop


async def _intercept_no_autorizado(update, context):
    """Corta cualquier update de quien no esté en `authorized_users.json` (group=-2).

    Es el primer handler de la cadena: si esto no deja pasar el update, ningún otro lo ve.
    Un agente con herramientas no distingue permisos por usuario — quien puede hablarle
    comparte su autoridad para ejecutar —, así que el control tiene que estar en la puerta
    y no repartido por cada comando.

    Un update sin remitente identificable se deniega igual (fail-closed): no hay forma de
    comprobar quién lo manda.
    """
    from telegram.ext import ApplicationHandlerStop
    from core.authorized_users import UNAUTHORIZED_MESSAGE, is_authorized

    user = update.effective_user
    user_id = str(user.id) if user is not None else ""

    if is_authorized("telegram", user_id):
        return

    logger.warning(
        f"Telegram: update rechazado de un remitente no autorizado "
        f"(id={user_id or 'desconocido'}, username={getattr(user, 'username', None)!r})"
    )

    # Se responde algo neutro en vez de ignorar en silencio: quien escriba por error merece
    # saber que no va a obtener respuesta. El texto no confirma de quién es el bot ni qué
    # sabe hacer.
    try:
        if update.effective_chat is not None:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text=UNAUTHORIZED_MESSAGE
            )
    except Exception as e:
        logger.error(f"No se pudo avisar al remitente no autorizado: {e}")

    raise ApplicationHandlerStop


async def _procesar(update, msg):
    """Procesa un mensaje dejando al agente capaz de pedir confirmación por el chat.

    Sin esto, cualquier acción amarilla que el agente intente desde Telegram —escribir en
    una aplicación, pulsar algo— muere con "denegado por security_manager": el adaptador
    de confirmación exige saber a qué chat preguntar, y ese dato solo lo tenía el comando
    `/eliminar`. El agente con herramientas nunca lo recibió, así que la excepción de canal
    que le abría `pc_type` y `pc_click` no servía de nada en la práctica.

    Van juntas dos cosas, y la segunda no es opcional:

    - La **reserva y el contexto**, que le dicen al adaptador a quién preguntar. Se reserva
      antes de empezar aunque la mayoría de los mensajes no vayan a confirmar nada, y se
      suelta al terminar si no se usó.
    - Sacar el procesamiento del hilo del event loop. `process()` es síncrono y bloquea:
      si se ejecuta aquí, el bot se queda sordo mientras dura, y la respuesta que está
      esperando —el "sí" del usuario— no puede llegar nunca. Sería un bloqueo mutuo con
      el reloj corriendo hasta el timeout.
    """
    from channels.gateway import GlassGateway
    from channels.telegram_confirmation_adapter import telegram_confirmation_adapter

    user = update.effective_user
    user_id = str(getattr(user, "id", "")) if user is not None else ""
    chat = update.effective_chat

    reservado = False
    if user_id and chat is not None:
        reservado = telegram_confirmation_adapter.reserve_pending(user_id, especulativa=True)
        if reservado:
            # Debe quedar puesto ANTES de `to_thread`: es lo que copia el contexto al hilo
            # worker. Si no se pudo reservar hay otra confirmación en curso para este
            # usuario; se procesa igual, pero sin contexto, así que una acción amarilla
            # que aparezca por el camino se deniega en vez de colarse en la espera ajena.
            telegram_confirmation_adapter.set_request_context(user_id, chat.id)

    try:
        return await asyncio.to_thread(GlassGateway().process, msg)
    finally:
        if reservado:
            telegram_confirmation_adapter.release_pending(user_id)


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

    # REQ-006/B6: se elimina el pre-chequeo de "apaga el pc"/"reinicia el pc" que había
    # acá — ahora `GlassGateway().process()` resuelve TODO el texto vía
    # `core/resolution.py:resolve()`, que ya clasifica y despacha `SYS_POWER_OFF`/etc. por
    # el mismo camino gateado que cualquier otro intent. El resultado funcional es idéntico
    # (YELLOW seguía bloqueado en Telegram antes y después de este cambio, por
    # `CHANNEL_ALLOWED_LEVELS`), solo cambia el texto de la denegación de la frase
    # específica en español de `_handle_shutdown`/`_handle_restart` al mensaje genérico de
    # `resolve()`. `_handle_shutdown`/`_handle_restart` quedan disponibles para invocación
    # directa (p.ej. desde comandos explícitos ya existentes o tests).
    msg = GlassMessage(
        user_id=_owner_uid(user),
        user_name=user.first_name or "Usuario",
        text=text, channel="telegram",
        msg_type=MessageType.TEXT
    )
    response = await _procesar(update, msg)
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
    except Exception as e:
        # Esperable (el archivo puede seguir abierto), pero no mudo: si los
        # temporales empiezan a acumularse, este es el unico rastro.
        logger.debug(f"no se pudo borrar el temporal: {e}")

    if not transcribed:
        await update.message.reply_text(
            f"No pude entender el audio{vocative()}. ¿Podría repetirlo?"
        )
        return

    await update.message.reply_text(
        f"_Escuché: \"{transcribed}\"_", parse_mode="Markdown"
    )

    # REQ-006/B6: mismo motivo que en handle_text() — el pre-chequeo de apagado/reinicio
    # se elimina, `GlassGateway().process()` resuelve el texto transcrito completo.
    msg = GlassMessage(
        user_id=_owner_uid(user),
        user_name=user.first_name or "Usuario",
        text=transcribed, channel="telegram",
        msg_type=MessageType.VOICE
    )
    response = await _procesar(update, msg)
    await _send_response(update, context, response, send_voice=True)


# ── Acciones del PC ────────────────────────────────────────────────

async def _handle_shutdown(update, context, send_voice: bool = False):
    # REQ-005: se enruta por el punto central (require_confirmation), no por el pre-chequeo
    # is_action_allowed(): así la decisión respeta CHANNEL_ALLOWED_LEVELS *y* queda el
    # intento registrado en la auditoría. Para YELLOW desde Telegram el gate deniega antes
    # de llegar a pedir confirmación por consola, que acá sería inalcanzable para el usuario.
    from core.security_manager import security_manager, ChannelType
    user = update.effective_user
    if not security_manager.require_confirmation(
        "shutdown",
        ChannelType.TELEGRAM,
        details="telegram:_handle_shutdown",
        user_id=str(getattr(user, "id", "desconocido")),
    ):
        msg = f"Lo siento{vocative()}. Por razones de seguridad no puedo apagar el PC desde Telegram."
        await update.message.reply_text(msg)
        return
    msg = (
        f"Iniciando secuencia de apagado{vocative()}.\n"
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
    # REQ-005: mismo criterio que _handle_shutdown() — gate central, no pre-chequeo.
    from core.security_manager import security_manager, ChannelType
    user = update.effective_user
    if not security_manager.require_confirmation(
        "restart",
        ChannelType.TELEGRAM,
        details="telegram:_handle_restart",
        user_id=str(getattr(user, "id", "desconocido")),
    ):
        msg = f"Lo siento{vocative()}. Por razones de seguridad no puedo reiniciar el PC desde Telegram."
        await update.message.reply_text(msg)
        return
    msg = (
        f"Iniciando secuencia de reinicio{vocative()}.\n"
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
    from channels.gateway import GlassGateway, GlassMessage, MessageType

    pf = await context.bot.get_file(photo.file_id)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        tmp = f.name
    await pf.download_to_drive(tmp)

    try:
        msg = GlassMessage(
            user_id=_owner_uid(user),
            user_name=user.first_name or "Usuario",
            text=caption,
            channel="telegram",
            msg_type=MessageType.IMAGE,
            image_path=tmp
        )
        response = await _procesar(update, msg)
    except Exception as e:
        from channels.gateway import GlassResponse
        response = GlassResponse(text=f"No pude analizar la imagen{vocative()}: {str(e)[:80]}")
    finally:
        try:
            os.unlink(tmp)
        except Exception as e:
            # Esperable (el archivo puede seguir abierto), pero no mudo: si los
            # temporales empiezan a acumularse, este es el unico rastro.
            logger.debug(f"no se pudo borrar el temporal: {e}")

    await _send_response(
        update, context,
        response,
        send_voice=voice_mode
    )


async def handle_document(update, context):
    user = update.effective_user
    doc = update.message.document
    filename = doc.file_name
    caption = update.message.caption or ""
    voice_mode = context.user_data.get("voice_mode", False)

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    from channels.gateway import GlassGateway, GlassMessage, MessageType

    df = await context.bot.get_file(doc.file_id)
    tmp_dir = tempfile.gettempdir()
    filepath = os.path.join(tmp_dir, filename)
    await df.download_to_drive(filepath)

    if not caption or ("analiza" not in caption.lower() and "resumen" not in caption.lower()):
        text_to_process = f"analiza el archivo {filepath}"
    else:
        text_to_process = f"{caption} {filepath}"

    try:
        msg = GlassMessage(
            user_id=_owner_uid(user),
            user_name=user.first_name or "Usuario",
            text=text_to_process,
            channel="telegram",
            msg_type=MessageType.TEXT
        )
        response = await _procesar(update, msg)
    except Exception as e:
        from channels.gateway import GlassResponse
        response = GlassResponse(text=f"No pude procesar el archivo{vocative()}: {str(e)[:80]}")
    finally:
        try:
            os.unlink(filepath)
        except Exception as e:
            # Esperable (el archivo puede seguir abierto), pero no mudo: si los
            # temporales empiezan a acumularse, este es el unico rastro.
            logger.debug(f"no se pudo borrar el temporal: {e}")

    await _send_response(update, context, response, send_voice=voice_mode)


async def handle_error(update, context):
    logger.error(f"Error: {context.error}")
    if update and update.message:
        await update.message.reply_text(
            f"Error inesperado{vocative()}. Por favor intente de nuevo."
        )


# ── Punto de entrada ───────────────────────────────────────────────

async def _post_init_telegram(application) -> None:
    """Callback post_init de la Application (REQ-018) — corre una vez, dentro del event
    loop ya arrancado por python-telegram-bot, antes de que empiece el polling. Es el
    primer punto del ciclo de vida donde existe un loop corriendo del que capturar una
    referencia (asyncio.get_running_loop()) — intentarlo antes, en el cuerpo síncrono de
    run_telegram_bot(), fallaría porque ese loop todavía no existe en ese punto."""
    from core.confirmation import register_confirmation_adapter
    from core.security_manager import ChannelType
    from channels.telegram_confirmation_adapter import telegram_confirmation_adapter

    loop = asyncio.get_running_loop()
    telegram_confirmation_adapter.bind(application.bot, loop)
    register_confirmation_adapter(ChannelType.TELEGRAM, telegram_confirmation_adapter.confirm)
    logger.info("Adaptador de confirmación conversacional registrado para ChannelType.TELEGRAM")


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
        agent = "NODDOO"

    print(f"\n{'='*50}")
    print(f"  {agent} - Bot Telegram completo")
    print(f"  Voz: {GLASS_VOICE}")
    print(f"  FFmpeg: {'Nota de voz nativa' if FFMPEG_AVAILABLE else 'Sin FFmpeg'}")
    print(f"  Aislamiento: por usuario activo")
    print(f"  PC: apagado / reinicio / captura activados")
    print(f"  Tareas: sistema de recordatorios activo")
    print(f"  /voz en Telegram para activar audio")
    print(f"  Ctrl+C para detener")
    print(f"{'='*50}\n")

    app = (
        Application.builder()
        .token(token)
        .concurrent_updates(True)   # REQ-018/Hallazgo A (security-audit-018.md) — sin esto,
                                    # PTB despacha updates uno a la vez (SimpleUpdateProcessor
                                    # default, max_concurrent_updates=1) y el bot completo queda
                                    # bloqueado hasta 120s para todos los usuarios mientras uno
                                    # solo tiene una confirmación de /eliminar pendiente.
        .post_init(_post_init_telegram)
        .build()
    )

    # ── Control de acceso por identidad ────────────────────────────
    # group=-2: por delante de TODO lo demás, incluido el interceptor de confirmaciones.
    # `TypeHandler(Update, ...)` cubre cualquier update —texto, comandos, voz, fotos y
    # documentos—, en vez de tener que recordar añadir el filtro a cada handler nuevo.
    # Sin esto, cualquiera que encontrara el bot era atendido como el dueño: las acciones
    # verdes se ejecutan sin confirmar, y "tomar captura de pantalla" es una de ellas.
    from telegram import Update as _Update
    from telegram.ext import TypeHandler

    app.add_handler(TypeHandler(_Update, _intercept_no_autorizado), group=-2)

    # ── Interceptor de confirmación pendiente (REQ-018/CA-05) ───────
    # Prioridad máxima entre los handlers de mensajes (group=-1, corre antes que el group=0
    # donde viven todos los CommandHandler/handle_text) — intercepta cualquier mensaje de
    # texto, incluidos comandos slash, cuando el usuario que lo envía tiene una confirmación
    # pendiente.
    app.add_handler(
        MessageHandler(filters.TEXT, _intercept_confirmacion_pendiente), group=-1
    )

    # ── Comandos existentes ────────────────────────────────────────
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("ayuda",   cmd_ayuda))
    app.add_handler(CommandHandler("help",    cmd_ayuda))
    app.add_handler(CommandHandler("voz",     cmd_voz))
    app.add_handler(CommandHandler("texto",   cmd_texto))
    app.add_handler(CommandHandler("memoria", cmd_memoria))
    app.add_handler(CommandHandler("limpiar", cmd_limpiar))
    app.add_handler(CommandHandler("detener", cmd_detener))
    app.add_handler(CommandHandler("stop",    cmd_detener))
    app.add_handler(CommandHandler("estado",  cmd_estado))
    app.add_handler(CommandHandler("skills",  cmd_skills))

    # ── Comandos de Tareas ─────────────────────────────────────────
    app.add_handler(CommandHandler("tareas",    cmd_tareas))
    app.add_handler(CommandHandler("nueva",     cmd_nueva))
    app.add_handler(CommandHandler("completar", cmd_completar))
    app.add_handler(CommandHandler("eliminar",  cmd_eliminar))

    # ── Handlers de mensajes ───────────────────────────────────────
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_text
    ))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_error_handler(handle_error)

    # ── Iniciar scheduler de tareas ────────────────────────────────
    try:
        from tasks.task_scheduler import task_scheduler
        task_scheduler.set_telegram_app(app)
        task_scheduler.start()
        print("  [+] Scheduler de tareas — activo")
    except Exception as e:
        print(f"  [!] Scheduler de tareas — error: {e}")

    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    run_telegram_bot()
