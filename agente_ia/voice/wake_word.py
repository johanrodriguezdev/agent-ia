import speech_recognition as sr
import logging
import threading
import time
from typing import Callable, Optional
import numpy as np
from ui.tts_engine import speak
from nlp.parser import clean_text
from config_manager import (
    get_wake_words, get_agent_name, get_agent_pronunciation, normalize_for_match,
)
from core.address import vocative

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
    """Detecta la wake word en `text` y devuelve `(detectada, comando_restante)`.

    Ambos lados se normalizan con `normalize_for_match()` —la misma función que ya usa
    `get_wake_words()`— para que la comparación sea simétrica. Con `clean_text()` no lo
    era: un nombre deletreado por el reconocedor ("O.R.I.O.N.") quedaba como "o r i o n"
    y no coincidía con "orion".
    """
    text_clean = normalize_for_match(text)
    wake_words = get_wake_words()
    wake_words.extend([name.replace("j", "y") for name in wake_words if "j" in name])

    for word in wake_words:
        pos = text_clean.find(word)
        if pos != -1:
            command = text_clean[pos + len(word):].strip()
            return True, command
    return False, ""

def _transcribe(recognizer: sr.Recognizer, audio: sr.AudioData) -> str:
    """Transcribe con Google y cae a Whisper local si falla, sin tragarse el motivo."""
    try:
        return recognizer.recognize_google(audio, language="es-ES")
    except sr.UnknownValueError:
        logger.info(
            "[Wake word] Google Speech no pudo transcribir el audio "
            "(UnknownValueError); probando fallback local"
        )
    except sr.RequestError as e:
        logger.warning(
            f"[Wake word] Fallo de conexion con la API de Google Speech ({e}); "
            "probando fallback local"
        )
    return _transcribe_whisper(audio)


def _listen_for_followup(recognizer: sr.Recognizer, source) -> str:
    """Captura el comando que sigue a la wake word cuando se dijo el nombre a secas.

    Reusa el `source` del micrófono ya abierto por `listen_for_wake_word()`: abrir un
    segundo `sr.Microphone()` anidado deja el dispositivo tomado y falla en Windows.
    """
    try:
        audio = recognizer.listen(source, timeout=6, phrase_time_limit=12)
    except sr.WaitTimeoutError:
        logger.info("[Wake word] Nadie dictó un comando tras despertar")
        return ""
    except Exception as e:
        logger.error(f"[Wake word] fallo escuchando el comando posterior: {e}")
        return ""

    text = _transcribe(recognizer, audio)
    if not text:
        logger.info("[Wake word] El comando posterior no se pudo transcribir")
    return text.strip()


def _report_state(
    wake_state_callback: Optional[Callable[[str], None]], state: str,
) -> None:
    """Reportar un estado por el canal de REQ-009/CA-04, nunca silenciado."""
    if wake_state_callback is None:
        return
    try:
        wake_state_callback(state)
    except Exception as e:
        logger.error(f"fallo en wake_state_callback: {e}")


def _report_awake(wake_state_callback: Optional[Callable[[str], None]]) -> None:
    """Reportar el estado 'AWAKE' por el canal nuevo (REQ-009/CA-04), nunca silenciado."""
    _report_state(wake_state_callback, "AWAKE")


def listen_for_wake_word(
    stop_event: Optional[threading.Event] = None,
    wake_state_callback: Optional[Callable[[str], None]] = None,
    conversation_window=None,
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

    `conversation_window` (REQ-021, pieza 6) es opcional y por defecto `None`: sin él, el
    comportamiento es exactamente el de antes de REQ-021 —siempre hace falta la wake
    word—, así que el uso headless desde `ui/cli.py` no cambia. Cuando se pasa (lo hace
    `ui/webview/wake_word_worker.py`), una frase transcrita durante la ventana abierta se
    acepta SIN wake word y se devuelve por este mismo `return`: mismo camino, misma señal
    `command_detected`, mismo `resolve()`, mismo gate de seguridad.
    """
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = False
    recognizer.energy_threshold = 400

    agent_label = get_agent_pronunciation() or get_agent_name()

    with sr.Microphone() as source:
        print(f"\n[Modo Manos Libres]: Escuchando... Di \"{agent_label}\" para activarme")
        recognizer.adjust_for_ambient_noise(source, duration=1)

        while True:
            if stop_event is not None and stop_event.is_set():
                return None

            # REQ-021/CA-13: la ventana venció sin voz -> el estado visible vuelve solo a
            # "esperando la wake word". Se evalúa acá arriba y no al final del `while`
            # porque varias ramas del cuerpo salen por `continue`.
            if conversation_window is not None and conversation_window.expired_now():
                _report_state(wake_state_callback, "LISTENING_WAKE")

            try:
                # REQ-021/CA-14: se marca ANTES de escuchar. Un chunk que empezó a
                # capturarse mientras el agente hablaba no puede aceptarse sin wake word
                # aunque termine después de abrirse la ventana.
                listen_started_at = time.monotonic()
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

                # REQ-021/CA-12: dentro de la ventana de conversación, la frase se acepta
                # sin exigir la wake word. `consume()` la cierra en el acto: UNA frase por
                # ventana, aunque el ruido siga.
                if conversation_window is not None \
                        and conversation_window.accepts(listen_started_at):
                    conversation_window.consume()
                    _report_awake(wake_state_callback)
                    logger.info(f"[Ventana] frase aceptada sin wake word: {text!r}")
                    return text.strip()

                is_wake, extracted_cmd = parse_wake_command(text)
                if is_wake:
                    print(f"[{agent_label} detectado]: '{text}'")
                    if extracted_cmd:
                        _report_awake(wake_state_callback)
                        return extracted_cmd
                    # Se dijo el nombre a secas: se avisa y se escucha el comando en la
                    # misma sesión de micrófono. Antes se devolvía `True` y el comando que
                    # el usuario dictaba a continuación se perdía por completo.
                    speak(f"Lo escucho{vocative()}")
                    _report_awake(wake_state_callback)
                    followup = _listen_for_followup(recognizer, source)
                    return followup if followup else True
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
                        speak(f"Lo escucho{vocative()}")
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
