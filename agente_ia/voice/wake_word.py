import speech_recognition as sr
from ui.tts_engine import speak
from nlp.parser import clean_text
from config_manager import get_wake_words, get_agent_name

def parse_wake_command(text: str) -> tuple[bool, str]:
    """
    Analiza el texto para detectar la wake word y extraer el comando consecuente si existe.
    """
    text_clean = clean_text(text)
    
    wake_words = get_wake_words()
    # Adicionalmente, permitimos la forma castellanizada temporalmente para cualquier nombre
    wake_words.extend([name.replace("j", "y") for name in wake_words if "j" in name])
    
    for word in wake_words:
        # Buscamos si la palabra clave está en el texto
        pos = text_clean.find(word)
        if pos != -1:
            # Extraemos todo lo que el usuario haya dicho DESPUÉS de la palabra clave
            command = text_clean[pos + len(word):].strip()
            return True, command
            
    return False, ""

def listen_for_wake_word():
    """
    Escucha de forma continua el micrófono con un consumo optimizado usando frases cortas.
    Retorna True si solo detectó la palabra clave (esperando siguiente comando).
    Retorna el 'comando' en string si el usuario lo dijo en la misma frase.
    """
    recognizer = sr.Recognizer()
    
    # Optimización: Reducimos un poco el threshold dinámico de energía 
    # y la limitamos para que libere la CPU mas seguido.
    recognizer.dynamic_energy_threshold = False
    recognizer.energy_threshold = 400 

    with sr.Microphone() as source:
        print("\n[🦻 Modo Wake Word]: Escuchando de fondo continuamente...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        
        while True:
            try:
                # Ampliamos a 6 segundos para dar margen si dice el comando en la misma frase
                audio = recognizer.listen(source, timeout=1, phrase_time_limit=6)
                
                try:
                    from ui.gui import update_gui_state
                    update_gui_state("LISTENING")
                except: pass
                
                text = recognizer.recognize_google(audio, language="es-ES")
                is_wake, extracted_cmd = parse_wake_command(text)
                
                if is_wake:
                    print(f"[✅ Wake Word Detectada]: '{text}'")
                    if extracted_cmd:
                        # Dijo "[Nombre] + comando", entregamos directo
                        return extracted_cmd
                    else:
                        # Solo dijo "[Nombre]"
                        speak("Sí, te escucho")
                        return True
                        
            except sr.WaitTimeoutError:
                # Silencio detectado, dejamos continuar el bucle sano
                pass
            except sr.UnknownValueError:
                # Trató de procesar sonido ininteligible, ignoramos
                pass
            except sr.RequestError as e:
                print(f"[Error de Conexión] La escucha falló: {e}")
                speak("Tengo un problema de red escuchando")
                return False
            except KeyboardInterrupt:
                print("\nSaliendo de escucha continua...")
                return False
            finally:
                try:
                    from ui.gui import update_gui_state
                    update_gui_state("IDLE")
                except: pass
