import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_CONFIG = {
    "agent_name": "glass"
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
            # Ensure agent_name exists in loaded config
            if "agent_name" not in config:
                config["agent_name"] = DEFAULT_CONFIG["agent_name"]
            return config
    except (json.JSONDecodeError, IOError):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG

def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except IOError as e:
        print(f"Error saving config: {e}")

def get_agent_name() -> str:
    config = load_config()
    return config.get("agent_name", "glass")

def set_agent_name(new_name: str):
    config = load_config()
    config["agent_name"] = new_name.strip().lower()
    save_config(config)

def get_agent_pronunciation() -> str:
    config = load_config()
    return config.get("agent_pronunciation", get_agent_name())

def get_wake_words() -> list[str]:
    name = get_agent_name().lower()
    pronunciation = get_agent_pronunciation().lower()
    
    bases = {name, pronunciation}
    
    # Manejar el caso de "O.R.I.O.N." / "Orion" y los errores comunes de Google STT en español
    if "orion" in name or "orion" in pronunciation:
        bases.update([
            "hay gris", "ahí gris", "ay gris", "y gris", 
            "orion", "orion", "iris", "idris", "ygris", "hi gris"
        ])
        
    words = []
    for b in bases:
        words.extend([
            f"hey {b}", 
            b, 
            f"oye {b}", 
            f"hola {b}",
            f"despierta {b}",
            f"hey {b} despierta"
        ])
        
    # Ordenar por longitud descendente para que intente capturar primero "hey ahi gris" 
    # antes que "ahi gris" solo, y evitar cortes incorrectos
    return sorted(list(set(words)), key=len, reverse=True)
