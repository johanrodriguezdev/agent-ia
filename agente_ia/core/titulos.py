"""
core/titulos.py
REQ-053 — un título corto para cada conversación, como en las apps de chat.

Hasta acá el título de una conversación en la barra lateral era su primer mensaje,
recortado («abre la calculadora», «mira en la configuración no se ve amigable y no se
puede hac…»). Sirve, pero con veinte chats la lista se vuelve ilegible. Después del
primer intercambio se le pide al modelo un título de tres a seis palabras y se guarda
como título propio (`memory.rename_conversation`), que es lo mismo que hace el usuario
al renombrar a mano: si después lo cambia, lo suyo manda.

Va con `tarea="ligera"`: es trabajo mecánico que conviene mandar a un modelo local o
gratuito si hay uno configurado, y con un tope de salida chico. Cualquier fallo deja el
título derivado de siempre; nunca lanza hacia el bridge.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

MAX_PALABRAS = 6
MAX_CARACTERES = 48
#: Con menos que esto del lado del usuario no hay nada que resumir: el mensaje ya es el
#: título («abrí chrome», «qué hora es»).
MIN_CARACTERES_PARA_PEDIRLO = 28
_TOKENS_DE_SALIDA = 24

_SYSTEM = (
    "Pones títulos a conversaciones. Respondes SOLO con el título: de 3 a 6 palabras, en el "
    "idioma de la conversación, sin comillas, sin punto final, sin emojis, sin explicar nada."
)
_PROMPT = (
    "Conversación:\n\nUsuario: {usuario}\n\nAsistente: {asistente}\n\n"
    "Título (3 a 6 palabras):"
)


def hace_falta_titulo(texto_usuario: str) -> bool:
    """Return si vale la pena pedirle un título al modelo para este primer mensaje."""
    return len(" ".join((texto_usuario or "").split())) >= MIN_CARACTERES_PARA_PEDIRLO


def limpiar(crudo: Optional[str]) -> str:
    """Return el título saneado, o "" si lo que vino no sirve.

    El modelo a veces contesta con comillas, con «Título:» delante, con punto final o con
    dos líneas. Se toma la primera línea, se sacan adornos y se recorta a `MAX_PALABRAS`.
    """
    if not isinstance(crudo, str):
        return ""
    linea = crudo.strip().splitlines()[0] if crudo.strip() else ""
    linea = re.sub(r"^\s*(t[íi]tulo|title)\s*[:：-]\s*", "", linea, flags=re.IGNORECASE)
    linea = linea.strip().strip("\"'«»“”‘’`*_ ").rstrip(".").strip()
    palabras = linea.split()
    if not palabras:
        return ""
    titulo = " ".join(palabras[:MAX_PALABRAS])
    if len(titulo) > MAX_CARACTERES:
        titulo = titulo[:MAX_CARACTERES].rstrip()
    return titulo


def generar(texto_usuario: str, texto_asistente: str) -> str:
    """Pide el título al modelo. Return "" si no se pudo (nunca lanza)."""
    from ai.llm_provider import es_respuesta_de_fallo, generate_response, tope_de_salida

    usuario = " ".join((texto_usuario or "").split())[:600]
    asistente = " ".join((texto_asistente or "").split())[:600]
    if not usuario:
        return ""
    try:
        with tope_de_salida(_TOKENS_DE_SALIDA):
            respuesta = generate_response(
                [{"role": "user", "content": _PROMPT.format(usuario=usuario, asistente=asistente)}],
                _SYSTEM,
                tarea="ligera",
            )
    except Exception as e:
        logger.info(f"Sin título automático: {e}")
        return ""
    texto = respuesta if isinstance(respuesta, str) else getattr(respuesta, "text", "")
    # Un «Error: Ollama no está ejecutándose…» o el texto de "sin proveedor" también son
    # strings: sin esto quedaban recortados a seis palabras como título permanente, y
    # como ya habría título propio no se volvería a intentar.
    if not isinstance(texto, str) or es_respuesta_de_fallo(texto):
        logger.info("Sin título automático: el modelo no contestó")
        return ""
    return limpiar(texto)


def titular_si_corresponde(conversation_id: str, texto_usuario: str, texto_asistente: str,
                           user_id: str) -> bool:
    """Genera y guarda el título de una conversación recién empezada. Return si lo puso.

    Solo si la conversación todavía no tiene título propio: uno puesto a mano (o por una
    pasada anterior) no se pisa.
    """
    from ai.memory_manager import memory

    if not conversation_id or not hace_falta_titulo(texto_usuario):
        return False
    try:
        if memory.get_conversation_title(conversation_id, user_id=user_id):
            return False
    except Exception as e:
        logger.info(f"Sin título automático (no se pudo consultar el actual): {e}")
        return False

    titulo = generar(texto_usuario, texto_asistente)
    if not titulo:
        return False
    try:
        return bool(memory.rename_conversation(conversation_id, titulo, user_id=user_id))
    except Exception as e:
        logger.info(f"Sin título automático (no se pudo guardar): {e}")
        return False
