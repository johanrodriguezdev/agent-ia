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

def get_wake_words() -> list[str]:
    name = get_agent_name().lower()
    return [
        f"hey {name}", 
        name, 
        f"oye {name}", 
        f"hola {name}",
        f"despierta {name}",
        f"hey {name} despierta"
    ]
