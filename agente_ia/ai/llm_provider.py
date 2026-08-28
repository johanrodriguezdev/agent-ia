import hashlib
import os
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_response_cache: OrderedDict = OrderedDict()
CACHE_MAX_SIZE = 100


@dataclass(frozen=True)
class ToolCallRequest:
    """Un tool call que el LLM decidió invocar (REQ-007, CA-04/CA-05)."""
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class LLMToolResponse:
    """Respuesta de un proveedor que soporta tool-calling nativo (REQ-007, CA-03).

    `tool_calls` vacío + `text` presente == el LLM decidió responder en texto plano en vez
    de usar una herramienta (caso borde de SPEC-007, no es un error)."""
    text: Optional[str]
    tool_calls: list


def _cache_key(messages, system_prompt, image_path, provider):
    raw = json.dumps({"m": messages, "s": system_prompt, "i": image_path, "p": provider}, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()


def _cached_call(prov_name, messages, system_prompt, image_path, model_name):
    key = _cache_key(messages, system_prompt, image_path, prov_name)
    if key in _response_cache:
        _response_cache.move_to_end(key)
        logger.debug(f"Cache hit para {prov_name}")
        return _response_cache[key]

    result = _uncached_call(prov_name, messages, system_prompt, image_path, model_name)
    _response_cache[key] = result
    if len(_response_cache) > CACHE_MAX_SIZE:
        _response_cache.popitem(last=False)
    return result


def _uncached_call(prov_name, messages, system_prompt, image_path, model_name, tools=None):
    if prov_name == "gemini":
        return _ask_gemini(messages, system_prompt, image_path, model_name)
    elif prov_name == "ollama":
        return _ask_ollama(messages, system_prompt, image_path, model_name)
    elif prov_name == "openai":
        return _ask_openai(messages, system_prompt, image_path, model_name, tools=tools)
    elif prov_name == "deepseek":
        return _ask_deepseek(messages, system_prompt, image_path, model_name, tools=tools)
    else:
        return _ask_anthropic(messages, system_prompt, image_path, model_name, tools=tools)

def get_provider_config():
    try:
        config_path = Path(__file__).parent.parent / "config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        provider = config.get("ai_provider", "anthropic").lower()
        vision_provider = config.get("vision_provider", "").lower()
        fallback_provider = config.get("fallback_provider", "").lower()
        model_name = config.get("ai_model", "")
        
        return provider, vision_provider, fallback_provider, model_name
    except Exception:
        return "anthropic", "", "", ""

#: Modelo por defecto de cada proveedor de respaldo. Sin esto se le pedía al respaldo el
#: modelo configurado para el principal — "deepseek-chat" no existe en Ollama, así que el
#: respaldo fallaba por una razón distinta a la del principal y quedaba igual de inútil.
_MODELO_POR_PROVEEDOR = {
    "ollama": "qwen3:8b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-20241022",
    "gemini": "gemini-1.5-flash",
}


def generate_response(messages, system_prompt, image_path=None, tools=None):
    """`tools` (REQ-007, CA-03): lista opcional de dicts `{name, description,
    parameters_schema}`. Se reenvía al proveedor activo únicamente si soporta tool-calling
    nativo en el alcance de este REQ (`anthropic`/`deepseek`/`openai`, CONFIRMADO 1) — con
    cualquier otro proveedor, se ignora en silencio y se responde en modo texto plano, sin
    lanzar excepción. Retrocompatible: por defecto es `None`, ningún caller existente rompe.
    """
    provider, vision_provider, fallback_provider, model_name = get_provider_config()

    active_provider = provider
    if image_path and os.path.exists(image_path):
        if vision_provider:
            active_provider = vision_provider
            # Y con el proveedor cambia el modelo. `model_name` es el configurado para el
            # principal —"deepseek-chat"—, y pedírselo a Gemini falla igual que pedirle
            # "gemini-1.5-flash" a DeepSeek. Es el mismo descuido que tenía la cadena de
            # respaldo: cambiar de proveedor sin cambiar de modelo garantiza el error.
            if vision_provider != provider:
                model_name = _MODELO_POR_PROVEEDOR.get(vision_provider, "")

    tools_supported = active_provider in ("anthropic", "deepseek", "openai")
    effective_tools = tools if (tools and tools_supported) else None

    try:
        if effective_tools:
            # CA-09: nunca se cachea una llamada con tools — bypass total de
            # _cached_call()/_response_cache en vez de incorporar un hash del schema de
            # tools a la cache key (ver desarrollo-log-007.md para la justificación).
            response = _uncached_call(
                active_provider, messages, system_prompt, image_path, model_name,
                tools=effective_tools,
            )
        else:
            response = _cached_call(active_provider, messages, system_prompt, image_path, model_name)
        if isinstance(response, str) and "Error:" in response and _cadena_de_respaldo(
            active_provider, fallback_provider
        ):
            raise Exception(response)
        return response
    except Exception as e:
        return _intentar_respaldos(
            active_provider, e, messages, system_prompt, image_path, model_name,
            effective_tools, fallback_provider,
        )


def _cadena_de_respaldo(activo, fallback_config) -> list:
    """Return los proveedores a los que caer, en orden, sin repetir el que ya falló.

    Acepta un proveedor suelto (lo que había) o una lista: se puede encadenar más de uno
    sin romper la configuración de nadie.
    """
    if not fallback_config:
        return []
    if isinstance(fallback_config, str):
        candidatos = [p.strip() for p in fallback_config.replace(",", " ").split()]
    else:
        candidatos = [str(p).strip() for p in fallback_config]

    vistos, cadena = {activo}, []
    for p in candidatos:
        if p and p not in vistos:
            vistos.add(p)
            cadena.append(p)
    return cadena


def _intentar_respaldos(
    activo, error_original, messages, system_prompt, image_path, model_name,
    tools, fallback_config,
):
    """Recorre la cadena de respaldo hasta que alguno responda.

    Tres diferencias con lo que hacía antes:

    - Recorre una CADENA, no un único respaldo. Si el segundo también está caído, prueba el
      siguiente en vez de rendirse.
    - Conserva las herramientas si el respaldo las soporta. Antes se perdían, así que el
      agente caía a un modo en el que no podía buscar ni consultar nada, justo cuando ya
      estaba teniendo un mal día.
    - El aviso va al registro, no a la respuesta. Que el proveedor principal fallara es un
      problema de operación, no algo que el usuario deba leer mezclado con lo que preguntó.
    """
    cadena = _cadena_de_respaldo(activo, fallback_config)
    if not cadena:
        logger.error(f"Proveedor '{activo}' falló y no hay respaldo configurado: {error_original}")
        return f"Error ({activo}): {error_original}"

    logger.warning(f"Proveedor '{activo}' falló ({error_original}); probando respaldos: {cadena}")

    errores = [f"{activo}: {error_original}"]
    for respaldo in cadena:
        try:
            modelo = _MODELO_POR_PROVEEDOR.get(respaldo, model_name)
            soporta_tools = respaldo in ("anthropic", "deepseek", "openai")
            respuesta = _uncached_call(
                respaldo, messages, system_prompt, image_path, modelo,
                tools=tools if (tools and soporta_tools) else None,
            )
            if isinstance(respuesta, str) and respuesta.startswith("Error:"):
                raise Exception(respuesta)
            logger.info(f"Respaldo '{respaldo}' respondió correctamente")
            return respuesta
        except Exception as e:
            logger.warning(f"El respaldo '{respaldo}' también falló: {e}")
            errores.append(f"{respaldo}: {e}")

    logger.error(f"Todos los proveedores fallaron: {errores}")
    return (
        "No consigo comunicarme con ningún proveedor de modelo en este momento. "
        "Revise su conexión y la configuración de claves."
    )

def _ask_anthropic(messages, system_prompt, image_path, model_name, tools=None):
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "Error: ANTHROPIC_API_KEY no está configurada."

    model = model_name if model_name else "claude-3-5-sonnet-20241022"

    # Adaptar mensajes a formato Anthropic
    anthropic_msgs = []
    for m in messages:
        anthropic_msgs.append({"role": m["role"], "content": [{"type": "text", "text": m["content"]}]})

    if image_path and os.path.exists(image_path) and anthropic_msgs and anthropic_msgs[-1]["role"] == "user":
        import base64
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")
        anthropic_msgs[-1]["content"].insert(0, {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}
        })

    # REQ-007/CA-04: convierte `parameters_schema` de cada tool al `input_schema` que
    # espera la API de Anthropic, sin reescribir el JSON Schema a mano.
    api_tools = None
    if tools:
        api_tools = [
            {"name": t["name"], "description": t["description"], "input_schema": t["parameters_schema"]}
            for t in tools
        ]

    client = anthropic.Anthropic(api_key=api_key)
    kwargs = {"tools": api_tools} if api_tools else {}
    response = client.messages.create(
        model=model,
        max_tokens=1500,
        system=system_prompt,
        messages=anthropic_msgs,
        **kwargs,
    )

    if not api_tools:
        return response.content[0].text

    # No asumir que `response.content[0]` es siempre texto (bug confirmado en
    # baseline-007.md): la respuesta puede traer uno o más bloques `tool_use`.
    text_parts, tool_calls = [], []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCallRequest(id=block.id, name=block.name, arguments=block.input))
    return LLMToolResponse(text="\n".join(text_parts) if text_parts else None, tool_calls=tool_calls)

def _ask_gemini(messages, system_prompt, image_path, model_name):
    import google.generativeai as genai
    api_key = os.environ.get("GEMINI_API_KEY", "")
    try:
        config_path = Path(__file__).parent.parent / "config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            api_key = cfg.get("gemini_api_key", api_key)
    except Exception as e:
        logger.debug(f"No se pudo leer gemini_api_key de config.json: {e}")

    if not api_key:
        return "Error: GEMINI_API_KEY no está configurada en variables ni en config.json."
        
    genai.configure(api_key=api_key)
    model_id = model_name if model_name else "gemini-1.5-flash"
    
    gemini_msgs = []
    for m in messages[:-1]:
        role = "user" if m["role"] == "user" else "model"
        gemini_msgs.append({"role": role, "parts": [m["content"]]})
        
    model = genai.GenerativeModel(model_id, system_instruction=system_prompt)
    chat = model.start_chat(history=gemini_msgs)
    
    last_msg_content = messages[-1]["content"] if messages else ""
    if image_path and os.path.exists(image_path):
        from PIL import Image
        img = Image.open(image_path)
        response = chat.send_message([img, last_msg_content])
    else:
        response = chat.send_message(last_msg_content)
        
    return response.text

def _ask_ollama(messages, system_prompt, image_path, model_name):
    import requests
    import json
    import time
    
    model = model_name if model_name else "llama3"
    api_url = "http://localhost:11434/api/chat"
    
    ollama_msgs = [{"role": "system", "content": system_prompt}]
    for m in messages[:-1]:
        ollama_msgs.append({"role": m["role"], "content": m["content"]})
        
    last_msg = {"role": "user", "content": messages[-1]["content"] if messages else ""}
    if image_path and os.path.exists(image_path):
        import base64
        with open(image_path, "rb") as f:
            last_msg["images"] = [base64.standard_b64encode(f.read()).decode("utf-8")]
    ollama_msgs.append(last_msg)
    
    # Desactivar "thinking" para modelos qwen3 (causa 500 sin esto)
    options = {}
    if "qwen3" in model.lower():
        options["num_ctx"] = 4096
    
    data = {
        "model": model,
        "messages": ollama_msgs,
        "stream": False,
        "options": options,
    }
    
    # Desactivar thinking explícitamente para qwen3
    if "qwen3" in model.lower():
        data["think"] = False
    
    # Reintentar hasta 2 veces ante errores 500
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            r = requests.post(api_url, json=data, timeout=180)
            r.raise_for_status()
            response_data = r.json()
            content = response_data.get("message", {}).get("content", "")
            return content if content else "No obtuve respuesta del modelo."
        except requests.exceptions.HTTPError as e:
            if r.status_code == 500 and attempt < max_retries:
                time.sleep(2)
                continue
            return f"Error de Ollama (HTTP {r.status_code}): El modelo puede estar sobrecargado. Intenta de nuevo."
        except requests.exceptions.ConnectionError:
            return "Error: Ollama no está ejecutándose. Inícialo con 'ollama serve'."
        except requests.exceptions.Timeout:
            return "Error: Ollama tardó demasiado en responder. El modelo puede ser muy pesado para tu hardware."
        except Exception as e:
            return f"Error conectando con Ollama: {str(e)}"

def _ask_openai(messages, system_prompt, image_path, model_name, tools=None):
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY", "")
    try:
        config_path = Path(__file__).parent.parent / "config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            api_key = cfg.get("openai_api_key", api_key)
    except Exception as e:
        logger.debug(f"No se pudo leer openai_api_key de config.json: {e}")

    if not api_key:
        return "Error: OPENAI_API_KEY no está configurada."

    client = OpenAI(api_key=api_key)
    model = model_name if model_name else "gpt-4o-mini"

    openai_msgs = [{"role": "system", "content": system_prompt}]
    for m in messages[:-1]:
        openai_msgs.append({"role": m["role"], "content": m["content"]})

    last_msg = {"role": "user", "content": []}
    last_text = messages[-1]["content"] if messages else ""
    last_msg["content"].append({"type": "text", "text": last_text})

    if image_path and os.path.exists(image_path):
        import base64
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")
        last_msg["content"].append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}
        })

    openai_msgs.append(last_msg)

    # REQ-007/CA-05: formato de tools `{"type":"function","function":{...}}` del SDK
    # `openai` — compartido con `_ask_deepseek` porque ambos usan el mismo SDK.
    api_tools = None
    if tools:
        api_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"], "description": t["description"], "parameters": t["parameters_schema"],
                },
            }
            for t in tools
        ]

    kwargs = {"tools": api_tools, "tool_choice": "auto"} if api_tools else {}
    response = client.chat.completions.create(
        model=model,
        messages=openai_msgs,
        max_tokens=1500,
        **kwargs,
    )
    msg = response.choices[0].message

    if not api_tools:
        return msg.content

    tool_calls = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_calls.append(ToolCallRequest(id=tc.id, name=tc.function.name, arguments=args))
    return LLMToolResponse(text=msg.content, tool_calls=tool_calls)

def _ask_deepseek(messages, system_prompt, image_path, model_name, tools=None):
    from openai import OpenAI
    from config_manager import get_deepseek_api_key
    api_key = get_deepseek_api_key()

    if not api_key:
        return "Error: DEEPSEEK_API_KEY no está configurada."

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    model = model_name if model_name else "deepseek-chat"

    deepseek_msgs = [{"role": "system", "content": system_prompt}]
    for m in messages[:-1]:
        deepseek_msgs.append({"role": m["role"], "content": m["content"]})

    # DeepSeek oficial aún no tiene un endpoint de visión público idéntico,
    # por lo que pasaremos por ahora todo como texto
    last_text = messages[-1]["content"] if messages else ""
    if image_path and os.path.exists(image_path):
        last_text += "\n[Aviso: El usuario envió una imagen, pero DeepSeek-Chat actual es de texto. Dile que no puedes ver imágenes por ahora]"

    deepseek_msgs.append({"role": "user", "content": last_text})

    # REQ-007/CA-05: mismo formato de tools que `_ask_openai` (ambos usan el SDK `openai`).
    api_tools = None
    if tools:
        api_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"], "description": t["description"], "parameters": t["parameters_schema"],
                },
            }
            for t in tools
        ]

    kwargs = {"tools": api_tools, "tool_choice": "auto"} if api_tools else {}
    response = client.chat.completions.create(
        model=model,
        messages=deepseek_msgs,
        max_tokens=1500,
        **kwargs,
    )
    msg = response.choices[0].message

    if not api_tools:
        return msg.content

    tool_calls = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_calls.append(ToolCallRequest(id=tc.id, name=tc.function.name, arguments=args))
    return LLMToolResponse(text=msg.content, tool_calls=tool_calls)
