import speech_recognition as sr
import logging
import threading
import time
from typing import Callable, Optional
import numpy as np
from ui.tts_engine import speak
from nlp.parser import clean_text
from config_manager import get_wake_words, get_agent_name

logger = logging.getLogger(__name__)

_whisper_model = None

def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        try:
            import whisper
            _whisper_model = whisper.load_model("base", device="cpu")
            print("[Whisper] Modelo local cargado para wake word (fallback offline)")
        except Exception:
            _whisper_model = False
    return _whisper_model if _whisper_model is not False else None

def _transcribe_whisper(audio_data: sr.AudioData) -> str:
    try:
        model = _get_whisper()
        if model is None:
            return ""
        raw = audio_data.get_raw_data()
        audio_np = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        result = model.transcribe(audio_np, language="es", fp16=False)
        return result.get("text", "").strip()
    except Exception:
        return ""

def parse_wake_command(text: str) -> tuple[bool, str]:
    text_clean = clean_text(text)
    wake_words = get_wake_words()
    wake_words.extend([name.replace("j", "y") for name in wake_words if "j" in name])

    for word in wake_words:
        pos = text_clean.find(word)
        if pos != -1:
            command = text_clean[pos + len(word):].strip()
            return True, command
    return False, ""

def _report_awake(wake_state_callback: Optional[Callable[[str], None]]) -> None:
    """Reportar el estado 'AWAKE' por el canal nuevo (REQ-009/CA-04), nunca silenciado."""
    if wake_state_callback is None:
        return
    try:
        wake_state_callback("AWAKE")
    except Exception as e:
        logger.error(f"fallo en wake_state_callback: {e}")


def listen_for_wake_word(
    stop_event: Optional[threading.Event] = None,
    wake_state_callback: Optional[Callable[[str], None]] = None,
):
    """Escuchar hasta detectar la wake word, o retornar por cancelación/KeyboardInterrupt.

    Retorna: `str` con el comando extraído tras la wake word, `True` si se detectó la wake
    word sin comando extra, `False` si se interrumpió con `KeyboardInterrupt`, o `None` si
    `stop_event` fue señalado (REQ-009/CA-05 — parada cooperativa, best-effort).

    `stop_event`/`wake_state_callback` son opcionales (`None` por defecto): sin ellos, el
    comportamiento es idéntico al existente antes de REQ-009 (uso desde `ui/cli.py` en
    modo headless, CA-07). Cuando se pasa `wake_state_callback` (uso desde la GUI), esta
    función omite la mutación de `GLOBAL_STATE` vía `update_gui_state()` para no hacer
    parpadear la píldora "Modo activo" existente con el ciclo del modo manos libres
    (REQ-009, ver "Decisión: no reusar GLOBAL_STATE desde la GUI").
    """
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = False
    recognizer.energy_threshold = 400

    with sr.Microphone() as source:
        print("\n[Modo Manos Libres]: Escuchando... Di \"Nodo\" para activarme")
        recognizer.adjust_for_ambient_noise(source, duration=1)

        while True:
            if stop_event is not None and stop_event.is_set():
                return None

            try:
                audio = recognizer.listen(source, timeout=1, phrase_time_limit=6)

                try:
                    from ui.tts_engine import is_speaking, signal_barge_in
                    if is_speaking():
                        signal_barge_in()
                        print("[Barge-in] Usuario interrumpio")
                except Exception:
                    pass

                if wake_state_callback is None:
                    try:
                        from ui.gui import update_gui_state
                        update_gui_state("LISTENING")
                    except Exception:
                        pass

                text = ""
                try:
                    text = recognizer.recognize_google(audio, language="es-ES")
                except sr.UnknownValueError:
                    # REQ-009 (hallazgo post-QA, prueba manual): logging de diagnostico
                    # minimo — Google Speech no pudo transcribir el audio capturado. No
                    # cambia el comportamiento (sigue intentando el fallback local), solo
                    # deja evidencia de por que no hubo texto en este ciclo.
                    logger.info(
                        "[Wake word] Google Speech no pudo transcribir el audio "
                        "(UnknownValueError); probando fallback local"
                    )
                    text = _transcribe_whisper(audio)
                except sr.RequestError as e:
                    # REQ-009 (hallazgo post-QA, prueba manual): idem, pero distingue el
                    # caso de fallo de conexion/cuota con la API de Google del caso de
                    # audio no reconocido — son causas raiz distintas para diagnosticar.
                    logger.warning(
                        f"[Wake word] Fallo de conexion con la API de Google Speech ({e}); "
                        "probando fallback local"
                    )
                    text = _transcribe_whisper(audio)

                if not text:
                    # REQ-009 (hallazgo post-QA): ningun motor devolvio texto. Con el
                    # fallback local (Whisper) no instalado por defecto (ver
                    # requirements.txt), este es el desenlace normal de cualquier fallo de
                    # recognize_google — antes quedaba en silencio total, indistinguible de
                    # "no se dijo nada".
                    logger.info(
                        "[Wake word] Ningun motor de reconocimiento devolvio texto en este "
                        "ciclo (silencio, audio ambiguo, o fallback local no disponible)"
                    )
                    continue

                is_wake, extracted_cmd = parse_wake_command(text)
                if is_wake:
                    print(f"[Nodo detectado]: '{text}'")
                    if extracted_cmd:
                        _report_awake(wake_state_callback)
                        return extracted_cmd
                    else:
                        speak("Lo escucho, Senor")
                        _report_awake(wake_state_callback)
                        return True
                else:
                    # REQ-009 (hallazgo post-QA, prueba manual de Johan: "Probe lo manos
                    # libres activando el audio pero no me escucha"): evidencia clave para
                    # la proxima prueba — deja registrado que SI transcribio, pero el texto
                    # no matcheo ninguna wake word configurada (ver diagnostico en
                    # desarrollo-log-009.md).
                    logger.info(
                        f"[Wake word] Texto reconocido no coincide con ninguna wake word "
                        f"configurada: '{text}'"
                    )

            except sr.WaitTimeoutError:
                pass
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                text = _transcribe_whisper(audio) if 'audio' in dir() else ""
                if text:
                    is_wake, extracted_cmd = parse_wake_command(text)
                    if is_wake:
                        if extracted_cmd:
                            _report_awake(wake_state_callback)
                            return extracted_cmd
                        speak("Lo escucho, Senor")
                        _report_awake(wake_state_callback)
                        return True
                continue
            except KeyboardInterrupt:
                print("\nSaliendo de modo manos libres...")
                return False
            finally:
                if wake_state_callback is None:
                    try:
                        from ui.gui import update_gui_state
                        update_gui_state("IDLE")
                    except Exception:
                        pass

            time.sleep(0.05)
