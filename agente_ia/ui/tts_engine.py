import pyttsx3

# ✅ BUG CORREGIDO: El motor TTS ya NO se inicializa al importar el módulo.
# Antes, si los drivers de audio fallaban al arrancar, TODA la aplicación
# crasheaba antes de mostrar siquiera el menú. Ahora se inicializa la
# primera vez que se necesita (patrón "lazy initialization").

_engine = None

def _get_engine():
    """
    Retorna el motor TTS. Lo inicializa solo si aún no existe.
    Si falla, retorna None sin romper el flujo principal de Glass.
    """
    global _engine
    if _engine is not None:
        return _engine
    
    try:
        _engine = pyttsx3.init()
        _engine.setProperty('rate', 155)

        # Buscar voz en español
        voices = _engine.getProperty('voices')
        for voice in voices:
            if "ES" in voice.id.upper() or "SPANISH" in voice.id.upper() or "ESPAÑOL" in voice.id.upper():
                _engine.setProperty('voice', voice.id)
                break

        return _engine

    except Exception as e:
        print(f"[Aviso] El motor de voz (TTS) no pudo iniciarse: {e}")
        print("[Aviso] Glass funcionará en modo silencioso hasta que se resuelva el problema de audio.")
        _engine = None
        return None


def speak(text: str):
    """
    Reproduce el texto por voz.
    Si el motor no está disponible, Glass continúa funcionando en silencio
    (el texto igual se muestra en pantalla por la CLI).
    """
    if not text:
        return

    engine = _get_engine()
    if engine is None:
        return  # Sin audio pero sin crash — Glass sigue funcionando
        
    try:
        from ui.gui import update_gui_state
        update_gui_state("RESPONDING")
    except ImportError:
        pass

    try:
        from config_manager import get_agent_name, get_agent_pronunciation
        import re
        agent_name = get_agent_name()
        agent_pron = get_agent_pronunciation()
        if agent_name.lower() != agent_pron.lower():
            text = re.sub(r'(?i)\b' + agent_name + r'\b', agent_pron, text)
    except Exception:
        pass

    try:
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"[Falla de voz]: {e}")
        # ✅ Si el motor falla en medio de una sesión, lo reseteamos
        # para que el próximo intento vuelva a intentar inicializarlo.
        global _engine
        _engine = None
    finally:
        try:
            from ui.gui import update_gui_state
            update_gui_state("IDLE")
        except Exception:
            pass
