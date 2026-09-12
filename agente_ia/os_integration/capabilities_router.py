"""
capabilities_router.py
Motor de despacho que carga system_capabilities.json y decide si un
comando del usuario puede resolverse con una capacidad del SO declarada
en el JSON (sin depender del clasificador ML).

Orden de prioridad en main.py:
  1. Comandos aprendidos por el usuario (command_learning.py)
  2. Capacidades del sistema operativo (este módulo)       <-- aquí
  3. Clasificador ML (intent.classifier)
"""

import json
import importlib
import logging
import os
from nlp.parser import clean_text
from core.security_manager import security_manager, format_details

logger = logging.getLogger(__name__)

#: El archivo vive en la RAÍZ del proyecto, junto a `config.json` y los demás archivos de
#: usuario — no dentro de `os_integration/`. Buscarlo al lado de este módulo dejaba las 14
#: capacidades declaradas sin cargar desde el rename de la carpeta (commit `fb0edc5`), y el
#: aviso se perdía entre las líneas del arranque: la función existía, el archivo existía, y
#: no se hablaban. Se encontró revisando por qué el arranque imprimía ese aviso.
_RAIZ_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_JSON_PATH = os.path.join(_RAIZ_PROYECTO, "system_capabilities.json")


# Carga el JSON una sola vez al importar el módulo
def _load_capabilities() -> list:
    """Return las capacidades declaradas, o lista vacía si no hay archivo o está roto.

    Se distinguen los dos casos a propósito: el archivo es OPCIONAL (una instalación sin él
    funciona igual, ver `agents/user_defined_tools.py`), pero un archivo que existe y no se
    puede leer es un problema que hay que ver en el log, no un silencio.
    """
    if not os.path.exists(_JSON_PATH):
        logger.info(
            "system_capabilities.json no existe: no hay capacidades declaradas por el usuario"
        )
        return []
    try:
        with open(_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        capacidades = data.get("capacidades", [])
        logger.info(f"system_capabilities.json: {len(capacidades)} capacidades declaradas")
        return capacidades
    except Exception as e:
        logger.error(f"system_capabilities.json existe pero no se pudo cargar: {e}")
        return []

_CAPABILITIES = _load_capabilities()

def match_capability(user_text: str):
    """
    Busca si alguna frase del capabilities.json está contenida en el texto del usuario.
    Retorna la entrada completa (dict) si hay coincidencia, o None si no hay.
    """
    text_clean = clean_text(user_text)
    
    for cap in _CAPABILITIES:
        for frase in cap.get("frases", []):
            if frase in text_clean:
                return cap
    return None

def execute_capability(cap: dict, channel=None) -> str:
    """
    Importa dinámicamente el módulo y llama la función indicada en el JSON.
    Mezcla los params por defecto del JSON con posibles extras del contexto.
    """
    modulo_name = cap.get("modulo", "")
    func_name   = cap.get("funcion", "")
    params      = cap.get("params", {})

    if not modulo_name or not func_name:
        return "Capacidad mal configurada en system_capabilities.json."

    action_name = f"{modulo_name}.{func_name}"
    if not security_manager.require_confirmation(
        action_name, channel, details=format_details(f"capability:{action_name}", params)
    ):
        return f"⛔ Capacidad '{action_name}' no autorizada."

    try:
        modulo = importlib.import_module(modulo_name)
        func   = getattr(modulo, func_name)
        result = func(**params) if params else func()
        return result
    except ModuleNotFoundError:
        return f"Módulo '{modulo_name}' no encontrado."
    except AttributeError:
        return f"La función '{func_name}' no existe en '{modulo_name}'."
    except Exception as e:
        return f"Error al ejecutar la capacidad '{func_name}': {e}"

def try_capability(user_text: str, channel=None) -> str | None:
    """
    Función de conveniencia: intenta hacer match y ejecutar en un solo paso.
    Retorna el resultado como string, o None si no hay coincidencia.
    Esto permite llamarlo en main.py con un simple if-check.
    """
    cap = match_capability(user_text)
    if cap:
        return execute_capability(cap, channel=channel)
    return None
