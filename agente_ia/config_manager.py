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
    "agent_name": "glass"
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
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
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
    return config.get("agent_name", "glass")


def set_agent_name(new_name: str):
    config = load_config()
    config["agent_name"] = new_name.strip().lower()
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
