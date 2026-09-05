import asyncio
import logging
import os
import re
import subprocess
import tempfile
import threading
import time

from core.address import vocative

logger = logging.getLogger(__name__)

_voice = "es-ES-ElviraNeural"
_speaking = False
#: Texto en curso, para que el barge-in pueda descartar el eco propio.
_current_text = ""
_speak_lock = threading.Lock()
_barge_in = False

# ─────────────────────────────────────────────
#  REQ-021 (pieza 8) — preparación de texto para voz
#
#  Único lugar del sistema donde se decide QUÉ se pronuncia (CA-27). Lo consumen las dos
#  superficies que hablan: `ui/cli.py::display_output` (consola) y
#  `ui/webview/bridge.py::_speak_response` (webview). Duplicar esta lógica garantizaría
#  drift entre ambas — el agente sonaría distinto según desde dónde se le hable.
#
#  `speak()`, `is_speaking()`, `signal_barge_in()` y `_speak_edge()` NO se tocan.
# ─────────────────────────────────────────────

SPEECH_TRUNCATE_THRESHOLD: int = 400   # umbral de DECISIÓN (idéntico al de ui/cli.py:49)
SPEECH_TRUNCATE_AT: int = 380          # punto de corte (idéntico al de ui/cli.py:50)

# Los marcadores de encabezado y de lista se anclan a principio de línea, así que el
# barrido de marcado corre ANTES del aplanado de saltos de línea.
_MD_FENCE_RE = re.compile(r"```[A-Za-z0-9_+\-]*\n?")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_BULLET_RE = re.compile(r"(?m)^[ \t]*[-*+][ \t]+")
_MD_HEADER_RE = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]*")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HASH_NUMBER_RE = re.compile(r"#(\d+)")
# Barrido final incondicional: CA-24 exige que no quede ningún `*` ni `#`. Se suma `~`
# (tachado de `format_task_list()`) y el backtick suelto, por el mismo motivo.
_MARKUP_LEFTOVER_RE = re.compile(r"[*#`~_]")
# Rangos Unicode de emoji, con `re` y sin dependencias nuevas (ver arquitectura-021.md §9).
# Cubren los de `format_task_created()`/`format_task_list()`: ✅ 📋 🆔 ⏰ 🔁 ⚠️ ☑️ ⛔ ☐ ➡.
_EMOJI_RANGES = (
    (0x2190, 0x21FF),    # flechas
    (0x2300, 0x23FF),    # simbolos tecnicos (reloj, alarma)
    (0x2460, 0x24FF),    # alfanumericos encerrados
    (0x25A0, 0x27BF),    # formas geometricas, misceianeos y dingbats
    (0x2B00, 0x2BFF),    # flechas y simbolos misceianeos
    (0x1F000, 0x1FAFF),  # pictogramas, emoticonos, banderas
    (0xFE0E, 0xFE0F),    # selectores de variacion
    (0x200D, 0x200D),    # zero-width joiner
)
_EMOJI_RE = re.compile(
    "[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in _EMOJI_RANGES) + "]"
)
_INLINE_SPACES_RE = re.compile(r"[ \t]{2,}")
_LINE_EDGE_SPACES_RE = re.compile(r"(?m)^[ \t]+|[ \t]+$")


def prepare_for_speech(text: str) -> str:
    """Return `text` listo para `speak()`: sin markdown, sin HTML, sin emojis, en una
    línea y truncado (CA-24, CA-27).

    El aplanado (`"\\n"` -> `". "`), el umbral de 400, el corte en 380 al último punto y
    la coletilla con `vocative()` son idénticos a los que tenía `ui/cli.py` antes de
    REQ-021 — lo único que cambia en la consola es que ahora suena limpia.
    """
    if not text:
        return ""

    # 1. Marcado: se quitan los delimitadores, se conserva el contenido.
    clean = _MD_FENCE_RE.sub("", text)
    clean = _MD_LINK_RE.sub(r"\1", clean)
    clean = _MD_BULLET_RE.sub("", clean)
    clean = _MD_HEADER_RE.sub("", clean)
    clean = _HTML_TAG_RE.sub("", clean)

    # 2. "#12" -> "número 12", para que "🆔 #12" no pierda el dato al barrer el `#`.
    clean = _HASH_NUMBER_RE.sub(r"número \1", clean)

    # 3. Barrido final incondicional de los símbolos de marcado que hayan sobrevivido.
    clean = _MARKUP_LEFTOVER_RE.sub("", clean)

    # 4. Emojis.
    clean = _EMOJI_RE.sub("", clean)

    # 5. Higiene de espacios — inaudible, solo evita huecos donde había un emoji.
    clean = _INLINE_SPACES_RE.sub(" ", clean)
    clean = _LINE_EDGE_SPACES_RE.sub("", clean)

    # 6. Aplanado, literal como en `ui/cli.py:46`.
    spoken = clean.replace("\n", ". ").strip()

    # 7. Truncado — mismo umbral, mismo corte y misma coletilla que la consola de hoy.
    if len(spoken) > SPEECH_TRUNCATE_THRESHOLD:
        spoken = (
            spoken[:SPEECH_TRUNCATE_AT].rsplit(".", 1)[0]
            + f"... La información completa está en su pantalla{vocative()}."
        )
    return spoken


def is_speaking() -> bool:
    return _speaking


def current_speech_text() -> str:
    """Return el texto que se está pronunciando ahora mismo, o cadena vacía.

    Lo consume `voice/wake_word.py` para distinguir una interrupción real del usuario del
    eco de los propios altavoces: si lo que capta el micrófono es un trozo de esto, no es
    una interrupción, es el agente oyéndose a sí mismo.
    """
    with _speak_lock:
        return _current_text


def signal_barge_in():
    global _barge_in
    _barge_in = True


async def _speak_edge(text: str) -> bool:
    global _speaking, _barge_in, _current_text
    import edge_tts
    communicate = edge_tts.Communicate(text, _voice)
    mp3_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            mp3_path = f.name
        await asyncio.wait_for(communicate.save(mp3_path), timeout=15)
        with _speak_lock:
            _speaking = True
            _current_text = text
        _play_mp3_windows(mp3_path)
        return True
    except asyncio.TimeoutError:
        logger.warning("edge-tts agotó el tiempo de espera (15s)")
        return False
    except Exception as e:
        logger.warning(f"Error edge-tts: {e}")
        return False
    finally:
        with _speak_lock:
            _speaking = False
            _barge_in = False
            _current_text = ""
        if mp3_path and os.path.exists(mp3_path):
            try:
                os.unlink(mp3_path)
            except Exception as e:
                # Esperable (el archivo puede seguir abierto), pero no mudo: si los
                # temporales empiezan a acumularse, este es el unico rastro.
                logger.debug(f"no se pudo borrar el temporal: {e}")


def _play_mp3_windows(mp3_path: str):
    global _barge_in
    proc = subprocess.Popen(
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", mp3_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    start = time.time()
    max_duration = 60
    while proc.poll() is None:
        if _barge_in:
            proc.kill()
            break
        if time.time() - start > max_duration:
            logger.warning(f"Reproducción excedió {max_duration}s, forzando cierre")
            proc.kill()
            break
        time.sleep(0.05)
    if proc.poll() is None:
        try:
            proc.kill()
        except Exception as e:
            # Carrera esperable: el reproductor pudo terminar entre el `poll()` y el
            # `kill()`. Se deja en debug por si alguna vez quedan procesos colgados.
            logger.debug(f"no se pudo cerrar el reproductor: {e}")


def speak(text: str):
    if not text:
        return

    from config_manager import get_agent_name, get_agent_pronunciation
    agent_name = get_agent_name()
    agent_pron = get_agent_pronunciation()
    if agent_name.lower() != agent_pron.lower():
        # `re.escape` es obligatorio: el nombre lo escribe el usuario en Configuración y
        # puede traer puntos ("O.R.I.O.N", donde `.` sería comodín) o paréntesis, que sin
        # escapar rompen la expresión y dejan a la app muda con un `re.error`.
        # `\b` no ancla contra un nombre que termina en signo de puntuación, así que el
        # límite derecho se exige solo cuando el nombre termina en carácter de palabra.
        pattern = r'(?i)\b' + re.escape(agent_name) + (r'\b' if agent_name[-1:].isalnum() else '')
        text = re.sub(pattern, agent_pron, text)

    try:
        import edge_tts
        ok = asyncio.run(_speak_edge(text))
        if not ok:
            print("[Voz] No se pudo generar audio")
    except ImportError:
        print("[Voz] edge-tts no instalado")
