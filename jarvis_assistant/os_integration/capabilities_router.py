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
import os
from nlp.parser import clean_text

# Carga el JSON una sola vez al importar el módulo
_JSON_PATH = os.path.join(os.path.dirname(__file__), "system_capabilities.json")

def _load_capabilities() -> list:
    try:
        with open(_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("capacidades", [])
    except Exception as e:
        print(f"[Aviso] No pude cargar system_capabilities.json: {e}")
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

def execute_capability(cap: dict) -> str:
    """
    Importa dinámicamente el módulo y llama la función indicada en el JSON.
    Mezcla los params por defecto del JSON con posibles extras del contexto.
    """
    modulo_name = cap.get("modulo", "")
    func_name   = cap.get("funcion", "")
    params      = cap.get("params", {})
    
    if not modulo_name or not func_name:
        return "Capacidad mal configurada en system_capabilities.json."
    
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

def try_capability(user_text: str) -> str | None:
    """
    Función de conveniencia: intenta hacer match y ejecutar en un solo paso.
    Retorna el resultado como string, o None si no hay coincidencia.
    Esto permite llamarlo en main.py con un simple if-check.
    """
    cap = match_capability(user_text)
    if cap:
        return execute_capability(cap)
    return None
