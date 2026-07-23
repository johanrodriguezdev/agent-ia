import asyncio
import logging
import os
import re
import subprocess
import tempfile
import threading
import time

logger = logging.getLogger(__name__)

_voice = "es-ES-ElviraNeural"
_speaking = False
_speak_lock = threading.Lock()
_barge_in = False


def is_speaking() -> bool:
    return _speaking


def signal_barge_in():
    global _barge_in
    _barge_in = True


async def _speak_edge(text: str) -> bool:
    global _speaking, _barge_in
    import edge_tts
    communicate = edge_tts.Communicate(text, _voice)
    mp3_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            mp3_path = f.name
        await asyncio.wait_for(communicate.save(mp3_path), timeout=15)
        with _speak_lock:
            _speaking = True
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
        if mp3_path and os.path.exists(mp3_path):
            try:
                os.unlink(mp3_path)
            except Exception:
                pass


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
        except Exception:
            pass


def speak(text: str):
    if not text:
        return

    from config_manager import get_agent_name, get_agent_pronunciation
    agent_name = get_agent_name()
    agent_pron = get_agent_pronunciation()
    if agent_name.lower() != agent_pron.lower():
        text = re.sub(r'(?i)\b' + agent_name + r'\b', agent_pron, text)

    try:
        import edge_tts
        ok = asyncio.run(_speak_edge(text))
        if not ok:
            print("[Voz] No se pudo generar audio")
    except ImportError:
        print("[Voz] edge-tts no instalado")
