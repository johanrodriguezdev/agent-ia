import json
import os

COMMANDS_FILE = os.path.join(os.path.dirname(__file__), 'commands.json')

def get_custom_commands() -> dict:
    """Busca y recupera los comandos aprendidos desde el archivo JSON de Jarvis."""
    if os.path.exists(COMMANDS_FILE):
        try:
            with open(COMMANDS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_custom_command(phrase: str, actions: list):
    """Acopla una nueva frase ligada a una lista de acciones."""
    commands = get_custom_commands()
    # Usamos clave en minúscula para asegurar coincidencias ignorando el case
    commands[phrase.lower().strip()] = actions
    
    with open(COMMANDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(commands, f, indent=4, ensure_ascii=False)

def run_custom_command(phrase: str, execute_callback) -> bool:
    """
    Si la expresión se identifica como un comando aprendido, 
    extrae sus acciones encadenadas y ejecuta el callback de orquestación central.
    """
    commands = get_custom_commands()
    phrase_lower = phrase.lower().strip()
    
    for key, actions in commands.items():
        if key in phrase_lower:
            for action in actions:
                # Dispara cada acción simulando que es un comando hablado por separado
                execute_callback(action)
            return True
            
    return False
