import hashlib
import os
import json
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ai import provider_health
from core import streaming, tool_history

logger = logging.getLogger(__name__)

_response_cache: OrderedDict = OrderedDict()
CACHE_MAX_SIZE = 100

#: REQ-027/CA-33 — tope de tokens de salida, único para los 5 adaptadores. Es un TECHO, no
#: un objetivo: subirlo no encarece una respuesta corta, solo deja de cortarla. 4096 y no
#: 8192 porque varios modelos gratuitos de OpenRouter tienen un tope de salida menor y
#: rechazan la petición con error duro — sería una regresión justo en los modelos que se
#: usan por ser gratis.
MAX_TOKENS_SALIDA = 4096


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


def _debe_cachear(tools, messages) -> bool:
    """REQ-027/CA-40 (generaliza CA-09 de REQ-007): la cache no ve ni una llamada con
    herramientas ni un historial de herramientas.

    Lo segundo es lo que agrega REQ-027 y no es cosmetico: la llamada de cierre va con
    `tools=None` y hoy entraria a la cache, asi que cachearla seria devolver manana la
    respuesta de hoy ante un historial identico. Ademas mantiene `_cache_key()` —que hace
    `json.dumps` de `messages`— a salvo de contenido estructurado, cuyo fallo de
    serializacion se registraria como fallo del PROVEEDOR y lo mandaria a cooldown.
    """
    return not tools and not tool_history.tiene_historial_de_herramientas(messages)


def _uncached_call(prov_name, messages, system_prompt, image_path, model_name, tools=None):
    # REQ-027/CA-07: si esta llamada no lleva herramientas, el historial se aplana a texto.
    # Un unico punto cubre tres casos que si no serian tres parches: (1) `gemini`/`ollama`,
    # que nunca reciben tools; (2) la llamada de cierre, que va con `tools=None` a
    # CUALQUIER proveedor —y la API de Anthropic rechaza bloques `tool_use`/`tool_result`
    # en una peticion que no declara `tools`—; (3) cualquier caller interno que algun dia
    # reciba un historial estructurado. Sin bloques, `aplanar()` devuelve la MISMA lista.
    if not tools:
        messages = tool_history.aplanar(messages)
    if prov_name == "gemini":
        return _ask_gemini(messages, system_prompt, image_path, model_name)
    elif prov_name == "ollama":
        return _ask_ollama(messages, system_prompt, image_path, model_name)
    elif prov_name == "openai":
        return _ask_openai(messages, system_prompt, image_path, model_name, tools=tools)
    elif prov_name == "deepseek":
        return _ask_deepseek(messages, system_prompt, image_path, model_name, tools=tools)
    elif prov_name == "openrouter":
        return _ask_openrouter(messages, system_prompt, image_path, model_name, tools=tools)
    else:
        return _ask_anthropic(messages, system_prompt, image_path, model_name, tools=tools)

def get_provider_config():
    try:
        import config_manager
        with open(config_manager.CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        provider = config.get("ai_provider", "anthropic").lower()
        vision_provider = config.get("vision_provider", "").lower()
        fallback_provider = config.get("fallback_provider", "").lower()
        model_name = config.get("ai_model", "")
        
        return provider, vision_provider, fallback_provider, model_name
    except Exception:
        return "anthropic", "", "", ""


def get_proveedor_de_tarea(tarea):
    """Return `(proveedor, modelo)` para `tarea`, o `("", "")` si no hay mapeo.

    Envoltorio de `destinos_de_tarea()` que devuelve solo el primero. Sigue existiendo
    porque es la forma en que se lee "a donde va esta tarea" cuando no interesa la
    rotacion: la config, las formas aceptadas y el fail-safe son los de alli.
    """
    destinos = destinos_de_tarea(tarea)
    return destinos[0] if destinos else ("", "")


def destinos_de_tarea(tarea) -> List[Tuple[str, str]]:
    """Return TODOS los `(proveedor, modelo)` configurados para `tarea`, en orden.

    Es la version en plural de `get_proveedor_de_tarea()`, y existe por los catalogos
    gratuitos: en OpenRouter conviene tener varios modelos para la misma tarea porque se
    quedan sin cuota todo el tiempo. Con una lista, cuando el primero contesta 429 se pasa
    al siguiente en vez de abandonar la tarea o irse al proveedor de pago.

    Formas aceptadas en `task_providers` (todas conviven)::

        "ligera": "ollama"
        "resumen": {"proveedor": "openrouter", "modelo": "google/gemma-4-31b-it:free"}
        "codigo":  {"proveedor": "openrouter", "modelos": ["a:free", "b:free"]}
        "razonamiento": [
            {"proveedor": "openrouter", "modelo": "z-ai/glm-5.2:free"},
            {"proveedor": "deepseek",   "modelo": "deepseek-chat"}
        ]

    Cualquier problema —archivo ilegible, forma rara— devuelve lista vacia, es decir "usa
    el proveedor de siempre". Nunca lanza: enrutar mal una tarea interna no puede tumbar
    la conversacion.
    """
    if not tarea or tarea == "general":
        return []
    try:
        # La ruta la resuelve `config_manager`, la misma que usa la pantalla de
        # configuracion: si la pantalla escribe en un archivo y esto lee de otro, lo que
        # el humano elige no tiene efecto. Se lee a mano y NO con `load_config()` porque
        # esa funcion reescribe config.json con los valores por defecto cuando no puede
        # parsearlo — consultar el modelo de una tarea no puede borrar la configuracion.
        import config_manager
        with open(config_manager.CONFIG_FILE, "r", encoding="utf-8") as f:
            mapeo = json.load(f).get("task_providers", {})
    except Exception as e:
        logger.debug(f"No se pudo leer task_providers de config.json: {e}")
        return []
    if not isinstance(mapeo, dict):
        return []

    entrada = mapeo.get(tarea)
    if entrada is None:
        return []

    destinos: List[Tuple[str, str]] = []
    for opcion in (entrada if isinstance(entrada, list) else [entrada]):
        destinos.extend(_leer_opcion_de_tarea(tarea, opcion))

    # Sin duplicados y conservando el orden: repetir un destino solo gasta su timeout dos
    # veces cuando esta caido.
    vistos, unicos = set(), []
    for destino in destinos:
        if destino not in vistos:
            vistos.add(destino)
            unicos.append(destino)
    return unicos


def _leer_opcion_de_tarea(tarea, opcion) -> List[Tuple[str, str]]:
    """Convierte UNA entrada de `task_providers` en destinos. Nunca lanza."""
    if isinstance(opcion, str):
        proveedor = opcion.strip().lower()
        return [(proveedor, "")] if proveedor else []

    if isinstance(opcion, dict):
        proveedor = str(opcion.get("proveedor") or opcion.get("provider") or "").strip().lower()
        if not proveedor:
            logger.warning(f"task_providers['{tarea}']: una opcion sin proveedor, se ignora")
            return []
        modelos = opcion.get("modelos") or opcion.get("models")
        if isinstance(modelos, list):
            return [(proveedor, str(m).strip()) for m in modelos if str(m).strip()]
        modelo = opcion.get("modelo") or opcion.get("model") or ""
        return [(proveedor, str(modelo).strip())]

    logger.warning(f"task_providers['{tarea}'] tiene una opcion invalida, se ignora: {opcion!r}")
    return []


#: Modelo por defecto de cada proveedor de respaldo. Sin esto se le pedía al respaldo el
#: modelo configurado para el principal — "deepseek-chat" no existe en Ollama, así que el
#: respaldo fallaba por una razón distinta a la del principal y quedaba igual de inútil.
_MODELO_POR_PROVEEDOR = {
    "ollama": "qwen3:8b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-20241022",
    "gemini": "gemini-1.5-flash",
    # OpenRouter cobra por modelo, no por proveedor: el sufijo `:free` es lo que hace que
    # esta línea no gaste nada. Los IDs de los modelos gratuitos CAMBIAN con el tiempo
    # (entran y salen del catálogo) — si empieza a responder "model not found", buscar el
    # reemplazo en https://openrouter.ai/models?max_price=0 y cambiarlo acá o en
    # `task_providers` de config.json, que acepta {"proveedor": ..., "modelo": ...}.
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
}

#: Proveedores donde la cuota y el limite de tasa son POR MODELO, no por cuenta. En
#: OpenRouter cada modelo gratuito tiene su propio cupo: que uno conteste 429 no dice nada
#: de los otros veinte, y apartar el proveedor entero dejaria fuera a todos los que
#: seguian funcionando. En DeepSeek, Anthropic u OpenAI es al reves — la cuota es de la
#: cuenta, asi que apartar solo un modelo haria que el siguiente mensaje vuelva a chocar
#: contra la misma pared. Ollama queda fuera a proposito: es local y no tiene cuota, asi
#: que distinguir por modelo solo agregaria una clave mas sin ganar nada.
_PROVEEDORES_POR_MODELO = ("openrouter",)


def _modelo_para_cooldown(proveedor: str, modelo: str) -> str:
    """Return el modelo con el que apartar a un destino, o "" para apartar al proveedor."""
    return modelo if proveedor in _PROVEEDORES_POR_MODELO else ""


#: Quién soporta tool-calling nativo (REQ-007). Estaba escrito a mano en `generate_response`
#: y otra vez en `_intentar_respaldos`: agregar un proveedor y olvidar una de las dos copias
#: dejaba al respaldo sin herramientas justo cuando más falta hacen. Una sola fuente.
_PROVEEDORES_CON_TOOLS = ("anthropic", "deepseek", "openai", "openrouter")


def _destinos_iniciales(tarea, provider, model_name, vision_provider, image_path):
    """Return los `(proveedor, modelo)` con los que arrancar, en orden de preferencia.

    Uno solo en el caso normal —el proveedor configurado—; varios cuando la tarea tiene
    una lista en `task_providers`, que es lo que permite rotar entre modelos gratuitos.
    """
    destinos = []
    for prov_tarea, modelo_tarea in destinos_de_tarea(tarea):
        # Sin modelo explicito en la config, el del proveedor. Cambiar de proveedor sin
        # cambiar de modelo es el error que este archivo ya cometio dos veces.
        destinos.append((prov_tarea, modelo_tarea or _MODELO_POR_PROVEEDOR.get(prov_tarea, "")))

    if destinos:
        logger.debug(f"Tarea '{tarea}' enrutada a {destinos} en vez de '{provider}'")
    else:
        destinos = [(provider, model_name)]

    # La vision pisa al enrutado por tarea a proposito: con una imagen de por medio, un
    # modelo de texto no sirve por barato que sea. Y con el proveedor cambia el modelo:
    # pedirle "deepseek-chat" a Gemini falla igual que pedirle "gemini-1.5-flash" a
    # DeepSeek.
    if image_path and os.path.exists(image_path) and vision_provider:
        activo, modelo = destinos[0]
        if vision_provider != activo:
            modelo = _MODELO_POR_PROVEEDOR.get(vision_provider, "")
        destinos = [(vision_provider, modelo)]

    return destinos


def generate_response(messages, system_prompt, image_path=None, tools=None, tarea="general",
                       aviso: Optional[dict] = None):
    """`tools` (REQ-007, CA-03): lista opcional de dicts `{name, description,
    parameters_schema}`. Se reenvía al proveedor activo únicamente si soporta tool-calling
    nativo (`_PROVEEDORES_CON_TOOLS`) — con cualquier otro proveedor, se ignora en silencio
    y se responde en modo texto plano, sin lanzar excepción. Retrocompatible: por defecto es
    `None`, ningún caller existente rompe.

    `tarea`: para qué se está pidiendo el modelo ("ligera", "razonamiento", ...). Permite
    mandar el trabajo interno y repetitivo —compactar historial, destilar memoria, resumir
    una búsqueda— a un modelo local o gratuito, y reservar el de pago para lo que de verdad
    lo necesita. El mapeo vive en `task_providers` de config.json y es OPCIONAL: sin él,
    toda tarea usa `ai_provider` y el comportamiento es exactamente el de antes.

    `aviso` (REQ-022, CA-12): dict opcional que el caller pasa VACÍO (`{}`) y que esta
    función RELLENA si el destino final difirió del configurado — por un swap preventivo de
    cooldown o por un respaldo tras un fallo en vivo. Mismo patrón que `estado` en
    `reasoning_loop.py::run()`: por defecto `None`, ningún caller existente cambia de
    comportamiento. Claves cuando hubo cambio: `proveedor_desde`, `modelo_desde`,
    `proveedor_hacia`, `modelo_hacia`. Dict vacío == no hubo cambio.
    """
    provider, vision_provider, fallback_provider, model_name = get_provider_config()
    destinos = _destinos_iniciales(tarea, provider, model_name, vision_provider, image_path)

    if len(destinos) == 1:
        # Un solo destino: el camino de siempre. Cooldown (`ai/provider_health.py`) —
        # empezar por un proveedor que acaba de quedarse sin cuota cuesta su timeout entero
        # antes de caer al respaldo, y lo cuesta en CADA mensaje mientras no se reponga. Se
        # arranca por uno disponible; si ninguno lo esta, se prueba igual en el orden de
        # siempre (el cooldown nunca deja al agente mudo).
        #
        # REQ-022/CA-06: los candidatos ya incluyen el default OpenRouter->Ollama cuando no
        # hay `fallback_provider` explícito (ver `_resolver_cadena_de_respaldo()`), no solo
        # la config explícita — así un proveedor único en cooldown también puede arrancar
        # directo por el default en vez de intentar igual al que se sabe caído. Los
        # candidatos son siempre tuplas `(proveedor, modelo)` — nunca strings sueltos — para
        # que la comparación de más abajo sea siempre `str == str`, nunca `tupla == str`.
        activo, modelo_explicito = destinos[0]
        candidatos = [(activo, modelo_explicito)] + _resolver_cadena_de_respaldo(activo, fallback_provider)
        preferido, modelo_preferido = provider_health.ordenar_por_disponibilidad(candidatos)[0]
        if preferido != activo:
            logger.info(
                f"'{activo}' en cooldown "
                f"({provider_health.segundos_restantes(activo):.0f}s restantes); "
                f"se empieza por '{preferido}'"
            )
            if aviso is not None:
                # REQ-022/CA-12, punto (a) de arquitectura-022.md: el swap preventivo SÍ
                # avisa, con el mismo criterio que un fallo en vivo — el usuario debe
                # enterarse siempre que la respuesta no vino del modelo que configuró.
                aviso["proveedor_desde"] = activo
                aviso["modelo_desde"] = modelo_explicito
                aviso["proveedor_hacia"] = preferido
                aviso["modelo_hacia"] = modelo_preferido
            # Cambiar de proveedor sin cambiar de modelo garantiza el error: misma leccion
            # que la cadena de respaldo y el proveedor de vision.
            destinos = [(preferido, modelo_preferido)]
    else:
        # Varios destinos para la misma tarea: se prueban en orden de disponibilidad. Esta
        # es la rotacion entre modelos gratuitos — el que acaba de contestar 429 va al
        # final, los demas del mismo catalogo siguen sirviendo.
        ordenables = [(p, _modelo_para_cooldown(p, m)) for p, m in destinos]
        preferencia = {d: i for i, d in enumerate(provider_health.ordenar_por_disponibilidad(ordenables))}
        destinos = sorted(destinos, key=lambda d: preferencia[(d[0], _modelo_para_cooldown(d[0], d[1]))])

    ultimo = len(destinos) - 1
    for indice, (activo, modelo) in enumerate(destinos):
        tools_supported = activo in _PROVEEDORES_CON_TOOLS
        effective_tools = tools if (tools and tools_supported) else None

        try:
            if _debe_cachear(effective_tools, messages):
                response = _cached_call(activo, messages, system_prompt, image_path, modelo)
            else:
                # CA-09 de REQ-007 + CA-40 de REQ-027: bypass total de
                # _cached_call()/_response_cache en vez de incorporar un hash del schema de
                # tools a la cache key (ver desarrollo-log-007.md para la justificacion).
                response = _uncached_call(
                    activo, messages, system_prompt, image_path, modelo,
                    tools=effective_tools,
                )
        except Exception as e:
            provider_health.registrar_fallo(activo, e, _modelo_para_cooldown(activo, modelo))
            if indice < ultimo:
                logger.warning(
                    f"'{activo}' ({modelo or 'modelo por defecto'}) fallo ({e}); "
                    f"se prueba el siguiente modelo de la tarea '{tarea}'"
                )
                continue
            return _intentar_respaldos(
                activo, e, messages, system_prompt, image_path, modelo,
                effective_tools, fallback_provider, aviso=aviso,
            )

        if isinstance(response, str) and "Error:" in response:
            # Un "Error: ..." devuelto como texto es un fallo del proveedor igual que una
            # excepcion: cuenta para el cooldown aunque no haya respaldo al que caer. Antes
            # este caso solo se miraba si habia cadena, asi que quedarse sin cuota sin
            # respaldo configurado no dejaba ningun rastro.
            provider_health.registrar_fallo(activo, response, _modelo_para_cooldown(activo, modelo))
            if indice < ultimo:
                logger.warning(
                    f"'{activo}' ({modelo or 'modelo por defecto'}) devolvio un error; "
                    f"se prueba el siguiente modelo de la tarea '{tarea}'"
                )
                continue
            # REQ-022/CA-06/CA-11: antes esta rama solo llamaba a `_intentar_respaldos()`
            # si YA había una cadena explícita (`_cadena_de_respaldo(...)` truthy) — sin
            # `fallback_provider` configurado, el "Error: ..." crudo del proveedor (p. ej.
            # "Error: DEEPSEEK_API_KEY no está configurada.", "Error: Ollama no está
            # ejecutándose...") se devolvía tal cual al usuario. Es exactamente el caso de
            # una instalación nueva sin claves (Casos Borde de SPEC-022.md), así que ahora
            # siempre se delega en `_intentar_respaldos()`: internamente ya resuelve el
            # default OpenRouter->Ollama cuando corresponde, y si de verdad no hay ningún
            # destino devuelve `SIN_PROVEEDOR` — nunca el string crudo.
            return _intentar_respaldos(
                activo, Exception(response), messages, system_prompt, image_path,
                modelo, effective_tools, fallback_provider, aviso=aviso,
            )

        provider_health.registrar_exito(activo, _modelo_para_cooldown(activo, modelo))
        return response


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


def _cadena_de_respaldo_por_defecto(activo: str) -> List[Tuple[str, str]]:
    """REQ-022/CA-06/07/08: OpenRouter (catálogo gratuito) -> Ollama local, cuando no hay
    `fallback_provider` configurado. Nunca ofrece al proveedor que ya está activo.

    CA-07: si no hay `OPENROUTER_API_KEY` (ni en config.json), OpenRouter se omite del
    todo — ni se intenta la llamada ni se registra como fallo en `provider_health`, porque
    no hubo ningún intento real que fallara.
    """
    import config_manager

    cadena: List[Tuple[str, str]] = []
    if activo != "openrouter" and config_manager.get_api_key("openrouter"):
        cadena.append(("openrouter", "openrouter/free"))
    if activo != "ollama":
        cadena.append(("ollama", _MODELO_POR_PROVEEDOR["ollama"]))
    return cadena


def _resolver_cadena_de_respaldo(activo, fallback_config) -> List[Tuple[str, str]]:
    """Destinos `(proveedor, modelo)` a los que caer, ya resueltos.

    Con `fallback_provider` configurado (string o lista), se usa tal cual —
    `_cadena_de_respaldo()` no cambia de firma ni de comportamiento (CA-09). Sin
    configuración explícita, se usa el default de CA-06/07/08.
    """
    if fallback_config:
        return [
            (p, _MODELO_POR_PROVEEDOR.get(p, ""))
            for p in _cadena_de_respaldo(activo, fallback_config)
        ]
    return _cadena_de_respaldo_por_defecto(activo)


def _intentar_respaldos(
    activo, error_original, messages, system_prompt, image_path, model_name,
    tools, fallback_config, aviso: Optional[dict] = None,
):
    """Recorre la cadena de respaldo hasta que alguno responda.

    Diferencias con lo que hacía antes:

    - Recorre una CADENA, no un único respaldo. Si el segundo también está caído, prueba el
      siguiente en vez de rendirse.
    - Conserva las herramientas si el respaldo las soporta. Antes se perdían, así que el
      agente caía a un modo en el que no podía buscar ni consultar nada, justo cuando ya
      estaba teniendo un mal día.
    - El aviso técnico completo va al registro, no a la respuesta cruda. Que el proveedor
      principal fallara es un problema de operación, no algo que el usuario deba leer
      mezclado con lo que preguntó — el usuario sí se entera, pero por el mensaje claro que
      arma `con_aviso_de_cambio()` a partir de `aviso` (REQ-022/CA-12), no por la excepción.
    - Los respaldos en cooldown se prueban al final, no primero (`ai/provider_health.py`).
      Siguen en la cadena: si todos están apartados se los intenta igual.
    - REQ-022/CA-06: sin `fallback_provider` explícito, la cadena ya no está vacía por
      defecto — `_resolver_cadena_de_respaldo()` aporta el default OpenRouter->Ollama.
    - REQ-022/CA-11: sin ningún destino al que caer (cadena vacía incluso con el default,
      o todos los respaldos fallan), la respuesta es siempre `SIN_PROVEEDOR` — nunca el
      texto crudo de la excepción original.
    """
    cadena = provider_health.ordenar_por_disponibilidad(
        _resolver_cadena_de_respaldo(activo, fallback_config)
    )
    if not cadena:
        logger.error(f"Proveedor '{activo}' falló y no hay respaldo configurado: {error_original}")
        return SIN_PROVEEDOR

    logger.warning(f"Proveedor '{activo}' falló ({error_original}); probando respaldos: {cadena}")

    errores = [f"{activo}: {error_original}"]
    for respaldo, modelo in cadena:
        try:
            soporta_tools = respaldo in _PROVEEDORES_CON_TOOLS
            respuesta = _uncached_call(
                respaldo, messages, system_prompt, image_path, modelo,
                tools=tools if (tools and soporta_tools) else None,
            )
            if isinstance(respuesta, str) and respuesta.startswith("Error:"):
                raise Exception(respuesta)
            logger.info(f"Respaldo '{respaldo}' respondió correctamente")
            provider_health.registrar_exito(respaldo, _modelo_para_cooldown(respaldo, modelo))
            if aviso is not None:
                # REQ-022/CA-12: el respaldo exitoso llena `aviso` para que el caller pueda
                # avisarle al usuario dentro del texto de la respuesta.
                aviso["proveedor_desde"] = activo
                aviso["modelo_desde"] = model_name
                aviso["proveedor_hacia"] = respaldo
                aviso["modelo_hacia"] = modelo
            return respuesta
        except Exception as e:
            provider_health.registrar_fallo(respaldo, e, _modelo_para_cooldown(respaldo, modelo))
            logger.warning(f"El respaldo '{respaldo}' también falló: {e}")
            errores.append(f"{respaldo}: {e}")

    logger.error(f"Todos los proveedores fallaron: {errores}")
    return SIN_PROVEEDOR

#: Lo que se responde cuando NINGUN proveedor contesta. Es una constante y no un literal
#: suelto porque hay quien necesita reconocerla: `core/resolution.py` usa este fallo para
#: caer al camino local (sin conexion, "sube el volumen" tiene que seguir funcionando).
SIN_PROVEEDOR = (
    "No consigo comunicarme con ningún proveedor de modelo en este momento. "
    "Revise su conexión y la configuración de claves."
)

#: Fallos que devuelven los `_ask_*()` COMO SI FUERAN una respuesta, en vez de lanzar. Es
#: una lista corta y explicita a proposito: confundir una respuesta legitima con un fallo
#: mandaria al usuario al camino local teniendo modelo disponible.
_MARCAS_DE_FALLO = (
    "no está configurada",
    "no está ejecutándose",
    "Error conectando con",
    "tardó demasiado en responder",
)


def es_respuesta_de_fallo(texto) -> bool:
    """Return True si `texto` es un fallo del proveedor disfrazado de respuesta.

    Hace falta porque `generate_response()` no distingue: cuando un `_ask_*()` no puede
    hablar con su proveedor, algunos lanzan (y hay respaldo) y otros RETORNAN el error como
    si fuera lo que dijo el modelo. Desde afuera, "Error: Ollama no está ejecutándose" y una
    respuesta real son la misma cosa — un `str`.
    """
    if not isinstance(texto, str):
        return False
    if texto == SIN_PROVEEDOR:
        return True
    return texto.startswith("Error") and any(m in texto for m in _MARCAS_DE_FALLO)


# --------------------------------------------------------------------- REQ-022: aviso de cambio

#: Forma corta del aviso de cambio de modelo (CA-16/CA-18) — sin nombres técnicos.
AVISO_CAMBIO_CORTO = "Cambié de modelo."

#: Plantilla de la forma larga (CA-12/CA-17). Un solo lugar arma el texto Y el regex que lo
#: reconoce (`AVISO_CAMBIO_RE`) — evita que se desincronicen si la redacción cambia.
_PLANTILLA_AVISO_LARGO = "Cambié a {hacia} porque {desde} no respondió."

#: Reconoce la forma larga tal como la arma `con_aviso_de_cambio()`, para que
#: `ui/tts_engine.py::prepare_for_speech()` la acorte sin reimplementar la redacción
#: (CA-18). Ancla a fin de texto porque `con_aviso_de_cambio()` siempre la agrega al final.
AVISO_CAMBIO_RE = re.compile(r"\n\nCambié a .+? porque .+? no respondió\.\s*$")


def _etiqueta_destino(proveedor: str, modelo: str) -> str:
    """Nombre para el aviso — deliberadamente simple, sin importar el catálogo de
    etiquetas "bonitas" de `ui/webview/bridge.py::_MODELOS_CONOCIDOS` (capa de UI; este
    módulo no depende de la UI, y CA-17 solo exige nombres de proveedor y modelo, no
    marketing)."""
    return f"{proveedor} ({modelo})" if modelo else proveedor


def texto_aviso_cambio(aviso: Optional[dict], corto: bool = False) -> str:
    """Return la frase de aviso, o `""` si `aviso` no marca ningún cambio."""
    if not aviso or not aviso.get("proveedor_hacia"):
        return ""
    if corto:
        return AVISO_CAMBIO_CORTO
    return _PLANTILLA_AVISO_LARGO.format(
        hacia=_etiqueta_destino(aviso["proveedor_hacia"], aviso["modelo_hacia"]),
        desde=_etiqueta_destino(aviso["proveedor_desde"], aviso["modelo_desde"]),
    )


def con_aviso_de_cambio(texto: str, aviso: Optional[dict], corto: bool = False) -> str:
    """`texto` con la línea de aviso agregada al final (CA-12/14), o `texto` sin tocar si
    no hubo cambio (CA-13)."""
    frase = texto_aviso_cambio(aviso, corto=corto)
    return f"{texto}\n\n{frase}" if frase else texto


def _indice_del_ultimo_plano(messages) -> Optional[int]:
    """Return el índice del último mensaje de TEXTO (no estructurado), o None si no hay.

    Es el mensaje que recibe el trato especial de siempre: la imagen y, en la familia
    `openai`, el `content` como lista de bloques. Sin historial de herramientas el último
    mensaje plano ES el último mensaje, así que los adaptadores producen exactamente la
    misma llamada que antes de REQ-027 (CA-08). Con historial, el último mensaje es el de
    resultados y la imagen no debe pegarse ahí (CA-09).
    """
    for i in range(len(messages) - 1, -1, -1):
        if not tool_history.es_estructurado(messages[i]):
            return i
    return None


def _mensajes_para_anthropic(messages, image_path):
    """Traduce la lista neutral al formato de Anthropic (REQ-027/CA-03).

    - mensaje plano -> `{"role", "content": [{"type": "text", ...}]}` — igual que antes
    - `llamada`     -> bloque `tool_use` dentro de un `assistant`
    - `resultado`   -> bloque `tool_result` dentro de un `user`
    """
    messages = tool_history.con_ids_normalizados(messages)
    indice_plano = _indice_del_ultimo_plano(messages)

    salida = []
    for mensaje in messages:
        if not tool_history.es_estructurado(mensaje):
            salida.append({
                "role": mensaje["role"],
                "content": [{"type": "text", "text": mensaje["content"]}],
            })
            continue

        bloques = []
        for bloque in mensaje["content"]:
            tipo = bloque.get("tipo")
            if tipo == tool_history.TIPO_TEXTO:
                bloques.append({"type": "text", "text": bloque["texto"]})
            elif tipo == tool_history.TIPO_LLAMADA:
                bloques.append({
                    "type": "tool_use",
                    "id": bloque["id"],
                    "name": bloque["nombre"],
                    "input": tool_history.argumentos_para_el_modelo(bloque),
                })
            elif tipo == tool_history.TIPO_RESULTADO:
                bloques.append({
                    "type": "tool_result",
                    "tool_use_id": bloque["id"],
                    "content": bloque["salida"],
                })
        salida.append({"role": mensaje["role"], "content": bloques})

    # CA-09: la imagen va al último mensaje de TEXTO del usuario, nunca a uno que
    # transporta resultados de herramientas.
    if (image_path and os.path.exists(image_path) and indice_plano is not None
            and salida[indice_plano]["role"] == "user"):
        import base64
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")
        salida[indice_plano]["content"].insert(0, {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data},
        })

    return salida


def _mensajes_para_openai(messages, system_prompt, image_path, *, imagen_como_bloque,
                          aviso_sin_vision=""):
    """Traduce la lista neutral al protocolo del SDK `openai` (REQ-027/CA-04).

    Una sola función para `openai`, `deepseek` y `openrouter`: los tres hablan el mismo
    protocolo. La asimetría de `imagen_como_bloque` es fea pero se conserva a propósito —
    CA-08 exige que con el formato viejo la llamada salga byte a byte igual, y hoy DeepSeek
    manda el último mensaje como string plano mientras los otros dos lo mandan como lista
    de bloques.

    - `llamada`   -> `assistant` con `tool_calls`
    - `resultado` -> un `{"role": "tool", "tool_call_id", "content"}` por resultado
    """
    messages = tool_history.con_ids_normalizados(messages)
    indice_plano = _indice_del_ultimo_plano(messages)

    salida = [{"role": "system", "content": system_prompt}]
    for i, mensaje in enumerate(messages):
        if tool_history.es_estructurado(mensaje):
            _agregar_estructurado_openai(salida, mensaje)
        elif i == indice_plano:
            salida.append(_ultimo_mensaje_openai(
                mensaje, image_path, imagen_como_bloque, aviso_sin_vision,
            ))
        else:
            salida.append({"role": mensaje["role"], "content": mensaje["content"]})

    if indice_plano is None and not messages:
        # Sin ningún mensaje, el comportamiento de siempre era mandar un `user` vacío.
        salida.append(_ultimo_mensaje_openai(
            {"role": "user", "content": ""}, image_path, imagen_como_bloque, aviso_sin_vision,
        ))
    return salida


def _agregar_estructurado_openai(salida, mensaje):
    """Vuelca un mensaje neutral con bloques al protocolo del SDK `openai`."""
    textos, tool_calls, resultados = [], [], []
    for bloque in mensaje["content"]:
        tipo = bloque.get("tipo")
        if tipo == tool_history.TIPO_TEXTO:
            textos.append(bloque["texto"])
        elif tipo == tool_history.TIPO_LLAMADA:
            tool_calls.append({
                "id": bloque["id"],
                "type": "function",
                "function": {
                    "name": bloque["nombre"],
                    "arguments": json.dumps(
                        tool_history.argumentos_para_el_modelo(bloque), ensure_ascii=False,
                    ),
                },
            })
        elif tipo == tool_history.TIPO_RESULTADO:
            resultados.append({
                "role": "tool",
                "tool_call_id": bloque["id"],
                "content": bloque["salida"],
            })

    if tool_calls or textos:
        entrada = {"role": mensaje["role"], "content": "\n".join(textos) if textos else None}
        if tool_calls:
            entrada["tool_calls"] = tool_calls
        salida.append(entrada)
    salida.extend(resultados)


def _ultimo_mensaje_openai(mensaje, image_path, imagen_como_bloque, aviso_sin_vision):
    """El último mensaje de texto, con el trato de imagen que cada adaptador ya tenía."""
    texto = mensaje.get("content") or ""
    tiene_imagen = bool(image_path and os.path.exists(image_path))

    if not imagen_como_bloque:
        # DeepSeek: string plano y, si hay imagen, el aviso de que no la puede ver.
        if tiene_imagen:
            texto += aviso_sin_vision
        return {"role": "user", "content": texto}

    contenido = [{"type": "text", "text": texto}]
    if tiene_imagen:
        import base64
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")
        contenido.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
        })
    return {"role": "user", "content": contenido}


def _ask_anthropic(messages, system_prompt, image_path, model_name, tools=None):
    import anthropic
    from config_manager import get_api_key

    api_key = get_api_key("anthropic")
    if not api_key:
        return "Error: ANTHROPIC_API_KEY no está configurada."

    model = model_name if model_name else "claude-3-5-sonnet-20241022"

    # REQ-027/CA-03: la traducción (incluida la imagen) vive en `_mensajes_para_anthropic`.
    anthropic_msgs = _mensajes_para_anthropic(messages, image_path)

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
        max_tokens=MAX_TOKENS_SALIDA,
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
    from config_manager import get_api_key

    api_key = get_api_key("gemini")
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
    from config_manager import get_api_key

    api_key = get_api_key("openai")
    if not api_key:
        return "Error: OPENAI_API_KEY no está configurada."

    client = OpenAI(api_key=api_key)
    model = model_name if model_name else "gpt-4o-mini"

    # REQ-027/CA-04: traducción compartida con `_ask_deepseek`/`_ask_openrouter`.
    openai_msgs = _mensajes_para_openai(
        messages, system_prompt, image_path, imagen_como_bloque=True,
    )

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

    if _puede_stremear(api_tools):
        try:
            texto, llamadas = _llamada_en_streaming(client, model, openai_msgs, api_tools)
            if not api_tools:
                return texto
            return LLMToolResponse(text=texto, tool_calls=llamadas)
        except Exception as e:
            logger.warning(f"streaming de OpenAI fallo ({e}); se reintenta sin streaming")

    kwargs = {"tools": api_tools, "tool_choice": "auto"} if api_tools else {}
    response = client.chat.completions.create(
        model=model,
        messages=openai_msgs,
        max_tokens=MAX_TOKENS_SALIDA,
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

def _ask_openrouter(messages, system_prompt, image_path, model_name, tools=None):
    """Adaptador de OpenRouter: una sola API para cientos de modelos, muchos gratuitos.

    Habla el protocolo de OpenAI, así que reusa su SDK cambiando `base_url` — el mismo
    truco que ya usa `_ask_deepseek` con DeepSeek. Lo que decide si una llamada cuesta o no
    NO es este adaptador sino el ID del modelo: los terminados en `:free` no gastan saldo.

    Aviso sobre tools: OpenRouter soporta tool-calling, pero no todos los modelos que sirve
    lo hacen —varios gratuitos no—. Si el reasoning loop empieza a fallar con un modelo
    gratuito, es esto: hay que elegir uno que las soporte o dejar ese camino en un
    proveedor de pago vía `task_providers`.
    """
    from openai import OpenAI
    from config_manager import get_api_key

    api_key = get_api_key("openrouter")
    if not api_key:
        return "Error: OPENROUTER_API_KEY no está configurada."

    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
    model = model_name if model_name else _MODELO_POR_PROVEEDOR["openrouter"]

    # REQ-027/CA-04: misma traduccion que `_ask_openai` — los tres hablan el protocolo
    # de OpenAI, asi que la construccion de mensajes es una sola.
    openrouter_msgs = _mensajes_para_openai(
        messages, system_prompt, image_path, imagen_como_bloque=True,
    )

    # Mismo formato de tools que `_ask_openai`/`_ask_deepseek`: los tres usan el SDK `openai`.
    api_tools = None
    if tools:
        api_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters_schema"],
                },
            }
            for t in tools
        ]

    kwargs = {"tools": api_tools, "tool_choice": "auto"} if api_tools else {}
    response = client.chat.completions.create(
        model=model,
        messages=openrouter_msgs,
        max_tokens=MAX_TOKENS_SALIDA,
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


def _llamada_en_streaming(client, model, mensajes, api_tools):
    """Pide la respuesta en pedazos y devuelve un mensaje con la misma forma que el normal.

    Se usa cuando hay alguien mirando la pantalla (`core/streaming.hay_sink()`). Los dos
    proveedores que pasan por acá —DeepSeek y OpenAI— hablan el mismo protocolo del SDK
    `openai`, así que la función es una sola.

    Reensamblar las tool calls es la parte fina: llegan partidas en deltas y hay que
    juntarlas por índice (el nombre viene en el primer pedazo, los argumentos van llegando
    de a cachos de JSON). El texto, en cambio, se emite a medida que llega — que es todo el
    punto de esto.
    """
    kwargs = {"tools": api_tools, "tool_choice": "auto"} if api_tools else {}
    stream = client.chat.completions.create(
        model=model, messages=mensajes, max_tokens=MAX_TOKENS_SALIDA, stream=True, **kwargs,
    )

    partes_texto = []
    tool_calls_parciales = {}

    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        texto = getattr(delta, "content", None)
        if texto:
            partes_texto.append(texto)
            streaming.emitir(texto)

        for tc in (getattr(delta, "tool_calls", None) or []):
            acumulado = tool_calls_parciales.setdefault(
                tc.index, {"id": "", "name": "", "arguments": ""}
            )
            if tc.id:
                acumulado["id"] = tc.id
            funcion = getattr(tc, "function", None)
            if funcion is not None:
                if getattr(funcion, "name", None):
                    acumulado["name"] = funcion.name
                if getattr(funcion, "arguments", None):
                    acumulado["arguments"] += funcion.arguments

    texto_final = "".join(partes_texto)
    llamadas = []
    for indice in sorted(tool_calls_parciales):
        crudo = tool_calls_parciales[indice]
        if not crudo["name"]:
            continue
        try:
            argumentos = json.loads(crudo["arguments"]) if crudo["arguments"] else {}
        except (json.JSONDecodeError, TypeError):
            argumentos = {}
        llamadas.append(ToolCallRequest(id=crudo["id"], name=crudo["name"], arguments=argumentos))

    return texto_final, llamadas


def _puede_stremear(api_tools) -> bool:
    """Solo se pide streaming si hay alguien mirando.

    Con herramientas también se puede: el texto que el modelo escriba antes de decidir una
    herramienta se ve igual, y las tool calls se reensamblan. Lo que nunca se hace es pedir
    streaming para llamadas internas (resúmenes, clasificación) que no van a ninguna
    pantalla — ahí no hay sumidero registrado.
    """
    return streaming.hay_sink()


def _ask_deepseek(messages, system_prompt, image_path, model_name, tools=None):
    from openai import OpenAI
    from config_manager import get_deepseek_api_key
    api_key = get_deepseek_api_key()

    if not api_key:
        return "Error: DEEPSEEK_API_KEY no está configurada."

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    model = model_name if model_name else "deepseek-chat"

    # REQ-027/CA-04: misma traduccion que `_ask_openai`, pero con el ultimo mensaje como
    # string plano y con el aviso de que DeepSeek no ve imagenes — exactamente lo de antes.
    deepseek_msgs = _mensajes_para_openai(
        messages, system_prompt, image_path, imagen_como_bloque=False,
        aviso_sin_vision="\n[Aviso: El usuario envió una imagen, pero DeepSeek-Chat actual es de texto. Dile que no puedes ver imágenes por ahora]",
    )

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

    if _puede_stremear(api_tools):
        try:
            texto, llamadas = _llamada_en_streaming(client, model, deepseek_msgs, api_tools)
            if not api_tools:
                return texto
            return LLMToolResponse(text=texto, tool_calls=llamadas)
        except Exception as e:
            # El streaming es una mejora de percepcion, no una dependencia: si falla, se
            # repite la llamada por el camino de siempre y el usuario ve la respuesta
            # completa igual. Lo unico que pierde es el efecto de "se esta escribiendo".
            logger.warning(f"streaming de DeepSeek fallo ({e}); se reintenta sin streaming")

    kwargs = {"tools": api_tools, "tool_choice": "auto"} if api_tools else {}
    response = client.chat.completions.create(
        model=model,
        messages=deepseek_msgs,
        max_tokens=MAX_TOKENS_SALIDA,
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
