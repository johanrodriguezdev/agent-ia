import speech_recognition as sr
import numpy as np

try:
    from ui.gui import update_gui_state
except ImportError:
    update_gui_state = lambda x: None

_whisper_model = None

def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        try:
            import whisper
            _whisper_model = whisper.load_model("base", device="cpu")
            print("[Whisper] Modelo local cargado (fallback offline)")
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


def listen_command() -> str:
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("* Ajustando nivel de ruido ambiente... (por favor, un segundo de silencio)")
        recognizer.adjust_for_ambient_noise(source, duration=1.5)
        print("* ¡Habla ahora! Escuchando comandos...")
        try:
            update_gui_state("LISTENING")
            audio = recognizer.listen(source, timeout=8, phrase_time_limit=15)
            print("* Procesando audio...")

            # Intentar Google API primero
            try:
                text = recognizer.recognize_google(audio, language="es-ES")
                return text
            except (sr.RequestError, sr.UnknownValueError):
                print("* Google API no disponible, intentando Whisper local...")
                text = _transcribe_whisper(audio)
                if text:
                    return text
                print("* Whisper tampoco pudo transcribir.")
                return ""

        except sr.WaitTimeoutError:
            print("No se ha detectado ninguna voz.")
            return ""
        except sr.UnknownValueError:
            print("No pude entender el sonido. Por favor, sé más claro.")
            return ""
        except sr.RequestError as e:
            print(f"No fue posible contactar los servicios de Speech a Texto: {e}")
            return ""
        except Exception as e:
            print(f"Ocurrió un error inesperado al acceder al micrófono: {e}")
            return ""
        finally:
            update_gui_state("IDLE")

    return ""
