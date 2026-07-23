import speech_recognition as sr
import logging
import time
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

def listen_for_wake_word():
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = False
    recognizer.energy_threshold = 400

    with sr.Microphone() as source:
        print("\n[Modo Manos Libres]: Escuchando... Di \"Orion\" para activarme")
        recognizer.adjust_for_ambient_noise(source, duration=1)

        while True:
            try:
                audio = recognizer.listen(source, timeout=1, phrase_time_limit=6)

                try:
                    from ui.tts_engine import is_speaking, signal_barge_in
                    if is_speaking():
                        signal_barge_in()
                        print("[Barge-in] Usuario interrumpio")
                except Exception:
                    pass

                try:
                    from ui.gui import update_gui_state
                    update_gui_state("LISTENING")
                except Exception:
                    pass

                text = ""
                try:
                    text = recognizer.recognize_google(audio, language="es-ES")
                except (sr.RequestError, sr.UnknownValueError):
                    text = _transcribe_whisper(audio)

                if not text:
                    continue

                is_wake, extracted_cmd = parse_wake_command(text)
                if is_wake:
                    print(f"[Orion detectado]: '{text}'")
                    if extracted_cmd:
                        return extracted_cmd
                    else:
                        speak("Lo escucho, Senor")
                        return True

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
                            return extracted_cmd
                        speak("Lo escucho, Senor")
                        return True
                continue
            except KeyboardInterrupt:
                print("\nSaliendo de modo manos libres...")
                return False
            finally:
                try:
                    from ui.gui import update_gui_state
                    update_gui_state("IDLE")
                except Exception:
                    pass

            time.sleep(0.05)
