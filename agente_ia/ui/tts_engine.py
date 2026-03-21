import pyttsx3

# Inicializa el motor al nivel de módulo pero con prevención de errores
try:
    engine = pyttsx3.init()
    engine.setProperty('rate', 155)

    voices = engine.getProperty('voices')
    for voice in voices:
        if "ES" in voice.id.upper() or "SPANISH" in voice.id.upper() or "ESPAÑOL" in voice.id.upper():
            engine.setProperty('voice', voice.id)
            break
except Exception as e:
    print(f"[Aviso] El motor de sintetizador de voz (TTS) no pudo conectarse: {e}")
    engine = None

def speak(text: str):
    """
    Toma un texto y lo reproduce por voz simulada.
    Se encapsula con un try/except para impedir que bloquee o rompa el bucle de Jarvis
    en caso de problemas de hardware/drivers de sonido.
    """
    if not text or engine is None:
        return
        
    try:
        from ui.gui import update_gui_state
        update_gui_state("RESPONDING")
        engine.say(text)
        engine.runAndWait()
    except ImportError:
        # Previene falla en caso no estemos corriendo GUI localmente
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"[Falla al intentar reproducir voz]: {e}")
    finally:
        try:
            update_gui_state("IDLE")
        except:
            pass
