import speech_recognition as sr

try:
    from ui.gui import update_gui_state
except ImportError:
    update_gui_state = lambda x: None

def listen_command() -> str:
    """
    Controla el uso del micrófono para obtener un input de voz y transformarlo
    a texto.
    """
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("* Ajustando nivel de ruido ambiente... (por favor, un segundo de silencio)")
        # Ajuste dinámico del background noise para evitar falsos positivos
        recognizer.adjust_for_ambient_noise(source, duration=1.5)
        
        print("* ¡Habla ahora! Escuchando comandos...")
        try:
            update_gui_state("LISTENING")
            # Captura el audio. Timeout = tiempo máximo esperando que inicies.
            # phrase_time_limit = tiempo total máximo de grabación desde que inicias a hablar.
            audio = recognizer.listen(source, timeout=8, phrase_time_limit=15)
            
            print("* Procesando audio...")
            # Petición a la API gratuita de Google incorporada (lenguaje Español Fijo)
            text = recognizer.recognize_google(audio, language="es-ES")
            return text
            
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
