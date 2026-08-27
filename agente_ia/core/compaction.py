"""
core/compaction.py
Resume las conversaciones largas para que no se pierda el hilo ni desborde el contexto.

Hasta aquí la conversación con el agente crecía sin freno y, al pasar de un tope, se
cortaba por la mitad más antigua. Cortar es la peor forma de olvidar: lo que se va no es lo
menos importante, es lo más viejo — y en una conversación de trabajo lo más viejo suele ser
justo la decisión que explica todo lo demás.

Compactar es lo contrario: los turnos antiguos se destilan en un resumen que ocupa una
fracción y conserva lo que importa; los recientes se quedan intactos, palabra por palabra.

Dos reglas que no se pueden romper:

- **Nunca partir un intercambio.** Si el punto de corte cae entre una pregunta y su
  respuesta, se mueve hasta que el par quede junto. Media conversación descolgada confunde
  al modelo más que no tenerla.
- **Ante la duda, no tocar.** Si el resumen falla o sale vacío, se devuelve el historial
  tal cual. Un historial largo funciona; uno mutilado, no.
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

#: A partir de cuántos mensajes se compacta. Por debajo no compensa: el resumen costaría
#: una llamada al modelo para ahorrar unas pocas líneas.
UMBRAL_MENSAJES = 40

#: Cuántos mensajes recientes se conservan literales. Son los que sostienen el hilo de lo
#: que se está hablando ahora; resumirlos haría perder el detalle justo donde más se nota.
MENSAJES_RECIENTES = 16

#: Tope del resumen. Si el modelo se extiende, se recorta: el objetivo es ocupar menos, y un
#: resumen de mil palabras no ahorra nada.
MAX_CHARS_RESUMEN = 1500

#: Marca del mensaje que contiene el resumen, para reconocerlo y no volver a resumirlo como
#: si fuera conversación.
MARCA_RESUMEN = "[RESUMEN DE LA CONVERSACIÓN ANTERIOR]"

_PROMPT = (
    "Resume esta parte antigua de una conversación entre un usuario y su asistente "
    "personal. El resumen sustituirá a los mensajes originales, así que debe conservar todo "
    "lo que haga falta para seguir la conversación.\n\n"
    "Conserva sí o sí:\n"
    "- Decisiones que se tomaron y por qué.\n"
    "- Datos concretos que el usuario dio (nombres, fechas, cifras, rutas).\n"
    "- Tareas o compromisos que quedaron abiertos.\n"
    "- Correcciones que el usuario hizo al asistente.\n\n"
    "Descarta: saludos, confirmaciones, cortesías y todo lo que ya se resolvió y cerró.\n\n"
    "Escribe en español, en pasado, en tercera persona, sin encabezados ni preámbulo.\n\n"
    "Conversación:\n{conversacion}"
)


def _es_resumen(mensaje: Dict) -> bool:
    return MARCA_RESUMEN in str(mensaje.get("content", ""))


def _punto_de_corte(historial: List[Dict], recientes: int) -> int:
    """Return el índice a partir del cual se conservan los mensajes literales.

    Se ajusta hacia atrás hasta que el corte caiga justo antes de un mensaje del usuario:
    así la parte conservada empieza por una pregunta y no por una respuesta huérfana.
    """
    corte = max(0, len(historial) - recientes)

    while corte > 0 and historial[corte].get("role") != "user":
        corte -= 1
    return corte


def _formatear(mensajes: List[Dict]) -> str:
    lineas = []
    for m in mensajes:
        quien = "Usuario" if m.get("role") == "user" else "Asistente"
        contenido = str(m.get("content", "")).strip()
        if contenido:
            lineas.append(f"{quien}: {contenido}")
    return "\n".join(lineas)


def compactar(
    historial: List[Dict],
    umbral: int = UMBRAL_MENSAJES,
    recientes: int = MENSAJES_RECIENTES,
    resumir_fn=None,
) -> List[Dict]:
    """Return el historial compactado, o el mismo de entrada si no procede o falla.

    `resumir_fn` permite inyectar el resumidor en los tests; por defecto usa el modelo.
    """
    if not historial or len(historial) <= umbral:
        return historial

    corte = _punto_de_corte(historial, recientes)
    if corte <= 0:
        return historial            # todo es "reciente": no hay nada que resumir

    antiguos = historial[:corte]
    conservados = historial[corte:]

    # Un resumen previo se incorpora al nuevo en vez de acumularse: si no, cada compactación
    # dejaría un resumen más y volveríamos a crecer sin freno, que es el problema original.
    texto_previo = "\n".join(
        str(m.get("content", "")).replace(MARCA_RESUMEN, "").strip()
        for m in antiguos if _es_resumen(m)
    )
    conversacion = _formatear([m for m in antiguos if not _es_resumen(m)])
    if texto_previo:
        conversacion = f"(Resumen anterior)\n{texto_previo}\n\n{conversacion}"

    if not conversacion.strip():
        return historial

    try:
        resumen = (resumir_fn or _resumir_con_modelo)(conversacion)
    except Exception as e:
        logger.warning(f"No se pudo compactar la conversación: {e}")
        return historial

    if not resumen or not resumen.strip():
        logger.info("El resumen salió vacío: se conserva el historial sin compactar")
        return historial

    resumen = resumen.strip()
    if len(resumen) > MAX_CHARS_RESUMEN:
        resumen = resumen[:MAX_CHARS_RESUMEN].rsplit(" ", 1)[0] + "…"

    logger.info(
        f"[Compactación] {len(antiguos)} mensajes -> 1 resumen "
        f"({len(conversacion)} -> {len(resumen)} caracteres); "
        f"{len(conservados)} conservados literales"
    )
    return [{"role": "user", "content": f"{MARCA_RESUMEN}\n{resumen}"}] + conservados


def _resumir_con_modelo(conversacion: str) -> Optional[str]:
    from ai.llm_provider import generate_response

    respuesta = generate_response(
        [{"role": "user", "content": _PROMPT.format(conversacion=conversacion)}],
        "Eres un resumidor de conversaciones. Respondes solo con el resumen pedido.",
    )
    return respuesta if isinstance(respuesta, str) else getattr(respuesta, "text", None)
