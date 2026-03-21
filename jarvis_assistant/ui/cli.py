from ui.stt.transcriber import listen_command
from ui.tts_engine import speak
from ui.personality import format_response
from config_manager import get_agent_name

class CLI:
    def get_input_method(self) -> str:
        agent_name = get_agent_name().upper()
        print("\n" + "="*30)
        print(f"🤖 {agent_name} ASSISTANT - COMMANDS")
        print("="*30)
        print("1) Escribir comando por texto")
        print("2) Dictar comando por voz")
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
            # Para la voz, quitamos saltos de línea y formateamos un poco
            text_to_speak = formal_text.replace("\n", ". ")
            
            # Truncar si es muy largo
            if len(text_to_speak) > 400:
                short_text = text_to_speak[:380].rsplit('.', 1)[0] + "... La información completa está en su pantalla, Señor."
                speak(short_text)
            else:
                speak(text_to_speak)
