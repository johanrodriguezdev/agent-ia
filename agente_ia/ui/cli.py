from ui.stt.transcriber import listen_command
from ui.tts_engine import prepare_for_speech, speak
from ui.personality import format_response
from config_manager import get_agent_name

class CLI:
    def __init__(self, gui_active: bool = False):
        """REQ-009/CA-06, CA-07: `gui_active=True` oculta la opción "3" del menú (la GUI
        tiene su propio toggle de modo manos libres — evita que ambos caminos compitan
        por `sr.Microphone()`). Default `False` conserva el comportamiento headless
        exactamente igual al de antes de este REQ."""
        self._gui_active = gui_active

    def get_input_method(self) -> str:
        agent_name = get_agent_name().upper()
        print("\n" + "="*30)
        print(f"🤖 {agent_name} ASSISTANT - COMMANDS")
        print("="*30)
        print("1) Escribir comando por texto")
        print("2) Dictar comando por voz")
        if not self._gui_active:
            print("3) Modo manos libres (Wake Word)")
        print("q) Salir")
        print("="*30)
        choice = input("Selecciona una opción: ")
        return choice.strip().lower()
        
    def get_text_command(self) -> str:
        return input("Ingresa tu comando: ")
        
    def get_voice_command(self) -> str:
        return listen_command()
        
    def display_output(self, text: str, read_aloud: bool = True):
        # 1. Personalidad Jarvis
        formal_text = format_response(text)
        
        # 2. Pintar en pantalla
        agent_name = get_agent_name().upper()
        print(f"\n[➡ {agent_name}]: {formal_text}")
        
        # 3. Voz
        if read_aloud:
            # REQ-021/CA-27: la preparación del texto para voz (aplanado, limpieza de
            # markdown/HTML/emojis, umbral de 400, corte en 380 y coletilla con
            # `vocative()`) vive en un único lugar, `ui/tts_engine.py`, compartido con el
            # webview. Antes estaba inline acá y la consola pronunciaba literalmente los
            # asteriscos y los emojis de `format_task_created()`.
            speak(prepare_for_speech(formal_text))
