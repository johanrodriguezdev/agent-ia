"""
core/tool_history.py
Formato NEUTRAL del historial de herramientas de un turno (REQ-027).

Lo escribe `core/reasoning_loop.py` y lo traducen los adaptadores de `ai/llm_provider.py`.
Módulo hoja a propósito: no importa nada del proyecto, así que los dos lados pueden
depender de él sin crear un ciclo.

Por qué existe un formato propio en vez de usar directamente el de un proveedor:
`ai/llm_provider.py::generate_response()` puede cambiar de proveedor A MITAD DE TURNO por
cooldown o por la cadena de respaldo (REQ-022). Si el bucle guardara el historial ya
traducido a bloques de Anthropic, la vuelta siguiente —servida por DeepSeek— recibiría un
formato que no entiende. El bucle habla neutral y cada adaptador traduce al vuelo.
"""
from typing import Any, Dict, List, Optional

#: Tipos de bloque. Un mensaje "estructurado" es el que lleva `content` como lista de estos.
TIPO_TEXTO = "texto"
TIPO_LLAMADA = "llamada"
TIPO_RESULTADO = "resultado"

#: Lo que `reasoning_loop.run()` inyecta en los params de toda herramienta (invariante de
#: seguridad de REQ-005: el canal y el usuario los pone el caller, nunca el modelo). Se
#: guarda en el bloque —el aplanado de CA-07 necesita el dict completo para salir byte a
#: byte igual que antes— pero NO se reenvía al modelo: `texto_original` es el mensaje
#: entero del usuario y, con presupuesto 40 y varias herramientas por vuelta, se repetiría
#: más de cien veces en el prompt.
CLAVES_INYECTADAS: tuple[str, ...] = ("channel", "user_id", "texto_original")

#: `execute_tool()` puede devolver "" o None, y un bloque de contenido vacío lo rechaza la
#: API de Anthropic. Nunca se manda un resultado vacío.
SIN_SALIDA = "(sin salida)"

#: Cierre del bloque de historial en el aplanado. Movido verbatim desde
#: `reasoning_loop._append_history_lines()` — esta es la ÚNICA copia, para que el texto no
#: pueda derivar entre el camino nativo y el aplanado.
_INSTRUCCION_CONTINUAR = (
    "Continúa resolviendo la tarea con esta información. Si ya puedes responder, "
    "hazlo directamente sin usar más herramientas."
)


# ─────────────────────────────────────────────
#  Construcción de bloques
# ─────────────────────────────────────────────

def bloque_texto(texto: str) -> Dict[str, Any]:
    """Return un bloque de texto suelto (el razonamiento intermedio del modelo)."""
    return {"tipo": TIPO_TEXTO, "texto": texto}


def bloque_llamada(id_llamada: str, nombre: str, argumentos: Dict[str, Any]) -> Dict[str, Any]:
    """Return el bloque de una herramienta pedida por el modelo.

    `argumentos` es el dict EJECUTADO completo, con las claves inyectadas por el caller
    incluidas: el aplanado de CA-07 tiene que imprimir el mismo `repr` de dict que antes
    de REQ-027. Lo que se le devuelve al modelo pasa antes por
    `argumentos_para_el_modelo()`.
    """
    return {
        "tipo": TIPO_LLAMADA,
        "id": id_llamada,
        "nombre": nombre,
        "argumentos": argumentos,
    }


def bloque_resultado(id_llamada: str, nombre: str, salida: Any) -> Dict[str, Any]:
    """Return el bloque del resultado de una herramienta, con la salida normalizada a str.

    Una salida vacía se reemplaza por `SIN_SALIDA`: Anthropic rechaza un bloque de
    contenido vacío, y `execute_tool()` puede devolver "" o None sin que eso sea un error.
    """
    texto = str(salida) if salida else SIN_SALIDA
    return {
        "tipo": TIPO_RESULTADO,
        "id": id_llamada,
        "nombre": nombre,
        "salida": texto,
    }


def mensaje_de_llamadas(texto: Optional[str], llamadas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return el mensaje `assistant` de una vuelta: razonamiento (si lo hubo) + llamadas."""
    content: List[Dict[str, Any]] = []
    if texto:
        content.append(bloque_texto(texto))
    content.extend(llamadas)
    return {"role": "assistant", "content": content}


def mensaje_de_resultados(resultados: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return el mensaje `user` con los resultados de esa misma vuelta."""
    return {"role": "user", "content": list(resultados)}


def con_texto_agregado(mensaje: Dict[str, Any], texto: str) -> Dict[str, Any]:
    """Return una COPIA de `mensaje` con un bloque de texto al final.

    Se usa para colgar la instrucción de cierre del último mensaje de resultados: Anthropic
    exige alternancia estricta de roles, así que la instrucción no puede viajar como un
    `user` aparte detrás de otro `user`.
    """
    content = list(mensaje.get("content") or [])
    content.append(bloque_texto(texto))
    return {**mensaje, "content": content}


# ─────────────────────────────────────────────
#  Inspección
# ─────────────────────────────────────────────

def es_estructurado(mensaje: Any) -> bool:
    """Return True si `mensaje` transporta bloques neutrales en vez de texto plano."""
    if not isinstance(mensaje, dict):
        return False
    content = mensaje.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(b, dict) and "tipo" in b for b in content)


def tiene_historial_de_herramientas(messages: Any) -> bool:
    """Return True si algún mensaje de la lista lleva bloques neutrales."""
    if not isinstance(messages, list):
        return False
    return any(es_estructurado(m) for m in messages)


def argumentos_para_el_modelo(bloque: Dict[str, Any]) -> Dict[str, Any]:
    """Return los `argumentos` de un bloque `llamada` sin las claves que inyecta el caller.

    El modelo ve de vuelta lo que él pidió, no lo que el bucle le pisó encima.
    """
    argumentos = bloque.get("argumentos") or {}
    if not isinstance(argumentos, dict):
        return {}
    return {k: v for k, v in argumentos.items() if k not in CLAVES_INYECTADAS}


def con_ids_normalizados(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return `messages` con todo `id` de llamada/resultado no vacío (respaldo de D-5).

    `reasoning_loop` ya asigna un id estable (`tc_<vuelta>_<i>`) precisamente para que la
    correlación sobreviva a un cambio de proveedor a mitad de turno, así que por el camino
    normal esta función no cambia nada. Existe para un historial armado a mano o venido de
    otro caller: los adaptadores no pueden mandar un `tool_use_id` vacío, y si cada uno se
    inventara el suyo no tendría con qué emparejar la llamada con su resultado.

    Los vacíos se numeran por ORDEN de aparición, y llamadas y resultados se numeran por
    separado: es el mismo orden en que los emite el bucle, así que se emparejan igual.
    """
    if not tiene_historial_de_herramientas(messages):
        return messages

    contadores = {TIPO_LLAMADA: 0, TIPO_RESULTADO: 0}
    salida: List[Dict[str, Any]] = []
    for mensaje in messages:
        if not es_estructurado(mensaje):
            salida.append(mensaje)
            continue
        bloques = []
        for bloque in mensaje["content"]:
            tipo = bloque.get("tipo") if isinstance(bloque, dict) else None
            if tipo in contadores:
                if not bloque.get("id"):
                    bloque = {**bloque, "id": f"tc_auto_{contadores[tipo]}"}
                contadores[tipo] += 1
            bloques.append(bloque)
        salida.append({**mensaje, "content": bloques})
    return salida


def pares_de(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return `[{"tool", "params", "result"}]` — la MISMA forma que consumía el historial
    de `_build_prompt()` antes de REQ-027.

    Correlaciona llamada y resultado por `id`. Una llamada sin resultado no debería existir
    (`reasoning_loop._ejecutar_vuelta()` garantiza el par, ver D-6 de arquitectura-027.md),
    pero si llega un historial armado a mano se rinde con resultado vacío en vez de romper.
    """
    salidas: Dict[str, str] = {}
    for mensaje in messages:
        if not es_estructurado(mensaje):
            continue
        for bloque in mensaje["content"]:
            if isinstance(bloque, dict) and bloque.get("tipo") == TIPO_RESULTADO:
                salidas[bloque.get("id", "")] = bloque.get("salida", "")

    pares: List[Dict[str, Any]] = []
    for mensaje in messages:
        if not es_estructurado(mensaje):
            continue
        for bloque in mensaje["content"]:
            if isinstance(bloque, dict) and bloque.get("tipo") == TIPO_LLAMADA:
                pares.append({
                    "tool": bloque.get("nombre", ""),
                    "params": bloque.get("argumentos", {}),
                    "result": salidas.get(bloque.get("id", ""), ""),
                })
    return pares


# ─────────────────────────────────────────────
#  Aplanado a texto (proveedores sin tool-calling y llamada de cierre)
# ─────────────────────────────────────────────

def lineas_de_historial(lines: List[str], pares: List[Dict[str, Any]]) -> None:
    """Añade a `lines` el detalle de las tools ejecutadas y la instrucción de cierre.

    Movido verbatim desde `reasoning_loop._append_history_lines()`.
    """
    for i, h in enumerate(pares, 1):
        lines.append(f"{i}. {h['tool']}({h['params']}) -> {h['result']}")
    lines.append("")
    lines.append(_INSTRUCCION_CONTINUAR)


def aplanar(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return `messages` con todo `content` como `str` (CA-07).

    Sin bloques estructurados devuelve `messages` TAL CUAL —la misma lista, sin copiar—:
    es lo que garantiza que un caller de hoy produzca la misma llamada byte a byte que
    antes de REQ-027 (CA-08), sin depender de que la reconstrucción sea perfecta.

    Con historial, funde los pares llamada/resultado en el último mensaje `user` de texto
    anterior a ellos. Uno solo, y no un `user` nuevo detrás: dos `user` seguidos los
    rechaza Gemini, que es justamente uno de los proveedores que llega por acá.

    Los bloques de texto de rol `assistant` (el razonamiento intermedio del modelo) se
    descartan: no viajaban antes de REQ-027 e incluirlos rompería la byte-identidad.
    """
    if not tiene_historial_de_herramientas(messages):
        return messages

    pares = pares_de(messages)
    planos = [m for m in messages if not es_estructurado(m)]

    if not pares:
        return planos

    indice_destino = None
    for i in range(len(planos) - 1, -1, -1):
        if planos[i].get("role") == "user":
            indice_destino = i
            break

    lines: List[str] = []
    lineas_de_historial(lines, pares)
    bloque_texto_historial = "\n".join(lines)

    if indice_destino is None:
        # No hay ningún `user` de texto donde fundirlo. No pasa por el camino de
        # `reasoning_loop`, pero un caller externo podría; mejor un `user` nuevo que
        # perder el historial.
        return planos + [{"role": "user", "content": bloque_texto_historial}]

    fundido = list(planos)
    destino = fundido[indice_destino]
    contenido = destino.get("content") or ""
    fundido[indice_destino] = {
        **destino,
        "content": f"{contenido}\n{bloque_texto_historial}" if contenido else bloque_texto_historial,
    }
    return fundido
