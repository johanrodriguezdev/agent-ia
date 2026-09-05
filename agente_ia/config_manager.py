import json
import os
import logging
import re
import unicodedata

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
    "user_title": "Señor",
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
    "openrouter_api_key": "OPENROUTER_API_KEY",
}

#: Que clave le corresponde a cada proveedor de modelo. Ollama no aparece: es local y no
#: lleva credencial.
_PROVEEDOR_A_CLAVE = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "gemini_api_key",
    "openrouter": "openrouter_api_key",
    "deepseek": "deepseek_api_key",
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
            if "user_title" not in config:
                config["user_title"] = DEFAULT_CONFIG["user_title"]
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
            # `ensure_ascii=False`: sin esto, "Peña" se guarda como "Peña" y el
            # archivo deja de ser legible para el humano que a veces lo edita a mano.
            json.dump(config, f, indent=4, ensure_ascii=False)
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
    """Persist the agent's name, preserving the capitalization the user typed.

    Antes se guardaba en minúsculas, lo que arruinaba nombres estilizados como
    "O.R.I.O.N" en la ventana y la bandeja. Las comparaciones que necesitan
    insensibilidad a mayúsculas (`get_wake_words()`) ya normalizan por su cuenta.
    """
    config = load_config()
    config["agent_name"] = new_name.strip()
    save_config(config)


def set_agent_pronunciation(pronunciation: str) -> None:
    """Persist how the agent's name sounds, para la detección de wake word."""
    config = load_config()
    config["agent_pronunciation"] = pronunciation.strip()
    save_config(config)


def get_user_title() -> str:
    """Return cómo el agente se dirige al usuario (por defecto "Señor").

    Acceso de configuración puro — igual que `get_display_name()`. Una cadena vacía es
    una elección válida del usuario ("que no me trate de ninguna forma"), y quien
    construye la frase decide qué hacer con ella; esta capa no aplica política.
    """
    config = load_config()
    return config.get("user_title", DEFAULT_CONFIG["user_title"])


def set_user_title(title: str) -> None:
    config = load_config()
    config["user_title"] = title.strip()
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


def get_telegram_autostart() -> bool:
    """Return si el canal de Telegram arranca junto con la app de escritorio.

    Encendido por defecto: tener el bot configurado y que no atienda porque nadie lo lanzo
    a mano es justo lo que se venia perdiendo. Se apaga poniendo `telegram_autostart` en
    `false` dentro de config.json.

    Ante un valor raro, ENCENDIDO: es el comportamiento util, y el canal ya esta acotado
    por su cuenta —Telegram solo puede ejecutar acciones verdes (`CHANNEL_ALLOWED_LEVELS`)—
    asi que arrancarlo de mas no abre ninguna puerta que no estuviera ya abierta.
    """
    valor = load_config().get("telegram_autostart", True)
    return valor is not False


def set_telegram_autostart(activo: bool) -> None:
    config = load_config()
    config["telegram_autostart"] = bool(activo)
    save_config(config)


def get_telegram_token() -> str:
    return _get_config_value("telegram_token")


def get_api_key(proveedor: str) -> str:
    """Return la API key de un proveedor: variable de entorno y, si no, `config.json`.

    Un unico punto para todos. Antes cada `_ask_*()` de `ai/llm_provider.py` la leia por su
    cuenta, y dos de ellas usaban `cfg.get("openai_api_key", la_del_entorno)`: con la clave
    presente pero VACIA en config.json —el estado de una instalacion recien clonada— esa
    forma pisa una variable de entorno que si sirve, y el proveedor se queda sin credencial
    sin que nada lo explique. `anthropic`, por el contrario, solo miraba el entorno e
    ignoraba lo que hubiera en config.json.

    Un proveedor desconocido (u `ollama`, que es local) devuelve cadena vacia.
    """
    clave = _PROVEEDOR_A_CLAVE.get(str(proveedor or "").strip().lower())
    return _get_config_value(clave).strip() if clave else ""


def env_var_de_proveedor(proveedor: str) -> str:
    """Return el nombre de la variable de entorno de un proveedor, para poder nombrarla en
    un mensaje al humano ("configura OPENROUTER_API_KEY"). Vacio si no lleva credencial."""
    clave = _PROVEEDOR_A_CLAVE.get(str(proveedor or "").strip().lower())
    return _ENV_KEY_MAP.get(clave, "") if clave else ""


def get_deepseek_api_key() -> str:
    return _get_config_value("deepseek_api_key")


def get_discord_token() -> str:
    return _get_config_value("discord_token")


def normalize_for_match(text: str) -> str:
    """Normaliza texto para comparar contra una transcripción de voz.

    Debe producir la MISMA forma que `nlp.parser.clean_text()` aplica al texto
    transcrito, o las wake words nunca coincidirían. La diferencia clave es la
    puntuación *dentro* de una palabra: un nombre estilizado como "O.R.I.O.N" tiene que
    colapsar a "orion" (que es lo que el reconocedor devuelve al oírlo), no a "o r i o n".

    No se importa `clean_text` acá a propósito: `config_manager` es una dependencia base
    de casi todo el proyecto y no debe arrastrar el paquete `nlp` (que carga el
    clasificador) solo para normalizar una cadena.
    """
    lowered = text.lower().strip()
    without_accents = "".join(
        c for c in unicodedata.normalize("NFD", lowered)
        if unicodedata.category(c) != "Mn"
    )
    # Los separadores internos de un acrónimo se borran ("o.r.i.o.n" -> "orion"); el resto
    # de los caracteres no alfanuméricos pasan a espacio, igual que en `clean_text()`.
    without_dots = re.sub(r"(?<=\w)[.\-_'’](?=\w)", "", without_accents)
    cleaned = re.sub(r"[^a-z0-9 ]", " ", without_dots)
    return re.sub(r"\s+", " ", cleaned).strip()


def get_wake_words() -> list[str]:
    """Return las frases que despiertan al agente, ya normalizadas para comparar.

    Todas salen normalizadas con `normalize_for_match()`: antes se devolvían crudas, así
    que un nombre con acento ("Sofía") o con puntos ("A.R.I.A") no coincidía NUNCA con la
    transcripción — que sí llega normalizada. Solo funcionaba "orion" por la lista de
    variantes fonéticas de más abajo, que está escrita a mano.
    """
    name = normalize_for_match(get_agent_name())
    pronunciation = normalize_for_match(get_agent_pronunciation())

    bases = {b for b in (name, pronunciation) if b}
    if not bases:
        bases = {normalize_for_match(DEFAULT_CONFIG["agent_name"])}

    # Variantes fonéticas de "orion": lo que suelen devolver los motores de voz al oírlo.
    if "orion" in bases:
        bases.update([
            "hay gris", "ahi gris", "ay gris", "y gris",
            "iris", "idris", "ygris", "hi gris",
        ])

    words = []
    for b in bases:
        words.extend([
            f"hey {b}",
            b,
            f"oye {b}",
            f"hola {b}",
            f"despierta {b}",
            f"hey {b} despierta",
        ])

    return sorted(set(words), key=len, reverse=True)


# --------------------------------------------------------------------- geometria de ventana

def get_window_geometry() -> dict:
    """Ultimo tamano/posicion de la ventana, o `{}` si nunca se guardo.

    Se persiste para que la app abra donde la dejaste. Un valor corrupto o de una pantalla
    que ya no existe se descarta acá mismo devolviendo `{}`: quien llama vuelve al calculo
    normal contra la pantalla disponible (`ui/webview/window_geometry.py`), que nunca
    deja la ventana fuera de la vista.
    """
    bruto = load_config().get("window_geometry")
    if not isinstance(bruto, dict):
        return {}
    try:
        geometria = {
            "width": int(bruto["width"]),
            "height": int(bruto["height"]),
            "x": int(bruto["x"]),
            "y": int(bruto["y"]),
            "maximized": bool(bruto.get("maximized", False)),
        }
    except (KeyError, TypeError, ValueError):
        logger.warning("window_geometry invalida en config.json — se ignora")
        return {}
    if geometria["width"] < 400 or geometria["height"] < 300:
        return {}
    return geometria


def set_window_geometry(width: int, height: int, x: int, y: int,
                        maximized: bool = False) -> None:
    config = load_config()
    config["window_geometry"] = {
        "width": int(width), "height": int(height),
        "x": int(x), "y": int(y), "maximized": bool(maximized),
    }
    save_config(config)


# --------------------------------------------------------------------- proveedor y modelo

def get_ai_provider() -> str:
    return (load_config().get("ai_provider") or "").strip().lower()


def get_ai_model() -> str:
    return (load_config().get("ai_model") or "").strip()


def set_ai_provider_and_model(provider: str, model: str = "") -> None:
    """Cambia con QUE modelo responde el agente.

    Los dos valores se escriben juntos a proposito: dejar `ai_provider` nuevo con el
    `ai_model` del anterior es la forma mas facil de terminar pidiendole a DeepSeek un
    modelo de Anthropic y ver un 404 sin explicacion.
    """
    provider = (provider or "").strip().lower()
    if not provider:
        return
    config = load_config()
    config["ai_provider"] = provider
    config["ai_model"] = (model or "").strip()
    save_config(config)
    logger.info(f"proveedor de IA cambiado a {provider} ({config['ai_model'] or 'modelo por defecto'})")


# --------------------------------------------------------------------- enrutado por tarea

def get_task_providers() -> dict:
    """Return el mapeo `task_providers` de config.json, o `{}`.

    La lectura autoritativa para el modelo la hace `ai/llm_provider.py`; esta existe para
    la pantalla de configuracion, que necesita mostrar lo que hay hoy.
    """
    mapeo = load_config().get("task_providers")
    return mapeo if isinstance(mapeo, dict) else {}


def set_task_providers(mapeo: dict) -> None:
    """Escribe el mapeo completo. Un mapeo vacio borra la clave.

    Se escribe entero y no clave por clave a proposito: la pantalla siempre manda el estado
    completo, y asi no quedan tareas huerfanas de una edicion a medias.
    """
    config = load_config()
    if mapeo:
        config["task_providers"] = mapeo
    else:
        config.pop("task_providers", None)
    save_config(config)
    logger.info(f"enrutado por tarea actualizado: {sorted(mapeo)}")

