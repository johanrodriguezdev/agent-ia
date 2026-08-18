import json
import os
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_CONFIG = {
    "agent_name": "noddoo",
    "agent_pronunciation": "nodo",
    "display_name": "",
    "weather_city": "",
    "ui_theme": "dark",
}

_ENV_KEY_MAP = {
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "telegram_token": "TELEGRAM_BOT_TOKEN",
    "discord_token": "DISCORD_BOT_TOKEN",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
}


def load_config():
    # ✅ BUG CORREGIDO (REQ-008): las dos ramas de abajo devolvían el objeto
    # DEFAULT_CONFIG por referencia. Cualquier caller que mutara el dict retornado
    # (p. ej. set_display_name()) corrompía el default global compartido por el resto
    # del proceso. Se retorna siempre una copia.
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
            if "agent_name" not in config:
                config["agent_name"] = DEFAULT_CONFIG["agent_name"]
            if "agent_pronunciation" not in config:
                config["agent_pronunciation"] = DEFAULT_CONFIG["agent_pronunciation"]
            if "display_name" not in config:
                config["display_name"] = DEFAULT_CONFIG["display_name"]
            if "weather_city" not in config:
                config["weather_city"] = DEFAULT_CONFIG["weather_city"]
            if "ui_theme" not in config:
                config["ui_theme"] = DEFAULT_CONFIG["ui_theme"]
            return config
    except (json.JSONDecodeError, IOError):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)


def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except IOError as e:
        logger.error(f"Error saving config: {e}")


def _get_config_value(key: str, default: str = "") -> str:
    env_var = _ENV_KEY_MAP.get(key)
    if env_var:
        env_value = os.environ.get(env_var)
        if env_value:
            return env_value
    config = load_config()
    return config.get(key, default)


def get_agent_name() -> str:
    config = load_config()
    return config.get("agent_name", "noddoo")


def set_agent_name(new_name: str):
    config = load_config()
    config["agent_name"] = new_name.strip().lower()
    save_config(config)


def get_display_name() -> str:
    """Return the configured display name for the GUI greeting (REQ-008/CA-04).

    Acceso de configuración puro — la política de fallback (config → variable de
    entorno del SO → sin nombre) vive en `ui/widgets/center_panel.py`, no acá.
    """
    config = load_config()
    return config.get("display_name", "")


def set_display_name(name: str):
    config = load_config()
    config["display_name"] = name.strip()
    save_config(config)


def get_weather_city() -> str:
    """Return the configured city for the GUI weather panel (REQ-012/CA-01).

    Acceso de configuración puro — igual que `get_display_name()`. El fallback a
    geolocalización por IP cuando no hay ciudad configurada vive en
    `os_integration/weather_data.py` (`city=""`), no acá.
    """
    config = load_config()
    return config.get("weather_city", "")


def set_weather_city(city: str) -> None:
    config = load_config()
    config["weather_city"] = city.strip()
    save_config(config)


def get_ui_theme() -> str:
    """Return the persisted UI theme name for the desktop panel (REQ-013/CA-02).

    Acceso de configuración puro — igual que `get_display_name()`/`get_weather_city()`.
    La validación del nombre contra el catálogo de temas vive en
    `ui/theme.py:resolve_theme_name()`, no acá: un `config.json` editado a mano puede
    contener cualquier cosa y esta capa no decide política.
    """
    config = load_config()
    return config.get("ui_theme", DEFAULT_CONFIG["ui_theme"])


def set_ui_theme(theme: str) -> None:
    """Persist the UI theme preference (REQ-013/CA-02)."""
    config = load_config()
    config["ui_theme"] = theme.strip().lower()
    save_config(config)


def get_agent_pronunciation() -> str:
    config = load_config()
    return config.get("agent_pronunciation", get_agent_name())


def get_telegram_token() -> str:
    return _get_config_value("telegram_token")


def get_deepseek_api_key() -> str:
    return _get_config_value("deepseek_api_key")


def get_discord_token() -> str:
    return _get_config_value("discord_token")


def get_wake_words() -> list[str]:
    name = get_agent_name().lower()
    pronunciation = get_agent_pronunciation().lower()

    bases = {name, pronunciation}

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

    return sorted(list(set(words)), key=len, reverse=True)
