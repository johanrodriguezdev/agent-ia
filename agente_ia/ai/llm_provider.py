import hashlib
import os
import json
import logging
from collections import OrderedDict
from pathlib import Path

logger = logging.getLogger(__name__)

_response_cache: OrderedDict = OrderedDict()
CACHE_MAX_SIZE = 100


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


def _uncached_call(prov_name, messages, system_prompt, image_path, model_name):
    if prov_name == "gemini":
        return _ask_gemini(messages, system_prompt, image_path, model_name)
    elif prov_name == "ollama":
        return _ask_ollama(messages, system_prompt, image_path, model_name)
    elif prov_name == "openai":
        return _ask_openai(messages, system_prompt, image_path, model_name)
    elif prov_name == "deepseek":
        return _ask_deepseek(messages, system_prompt, image_path, model_name)
    else:
        return _ask_anthropic(messages, system_prompt, image_path, model_name)

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

def generate_response(messages, system_prompt, image_path=None):
    provider, vision_provider, fallback_provider, model_name = get_provider_config()

    active_provider = provider
    if image_path and os.path.exists(image_path):
        if vision_provider:
            active_provider = vision_provider

    try:
        response = _cached_call(active_provider, messages, system_prompt, image_path, model_name)
        if "Error:" in response and fallback_provider and fallback_provider != active_provider:
            raise Exception(response)
        return response
    except Exception as e:
        if fallback_provider and fallback_provider != active_provider:
            try:
                if fallback_provider == "ollama":
                    fallback_resp = _ask_ollama(messages, system_prompt, image_path, "qwen3:8b")
                else:
                    fallback_resp = _uncached_call(fallback_provider, messages, system_prompt, image_path, model_name)
                return f"[Fallback activado. Proveedor original falló por: {str(e)}]\n{fallback_resp}"
            except Exception as e2:
                return f"Error en proveedor principal ({str(e)}) y también en el de emergencia ({str(e2)})."
        return f"Error ({active_provider}): {str(e)}"

def _ask_anthropic(messages, system_prompt, image_path, model_name):
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
        
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1500,
        system=system_prompt,
        messages=anthropic_msgs
    )
    return response.content[0].text

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

def _ask_openai(messages, system_prompt, image_path, model_name):
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
    response = client.chat.completions.create(
        model=model,
        messages=openai_msgs,
        max_tokens=1500
    )
    return response.choices[0].message.content

def _ask_deepseek(messages, system_prompt, image_path, model_name):
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
    
    response = client.chat.completions.create(
        model=model,
        messages=deepseek_msgs,
        max_tokens=1500
    )
    return response.choices[0].message.content
