"""
core/dialog_questions.py
Redacción de la repregunta de un diálogo pendiente — REQ-021 (motor híbrido).

El reparto de trabajo es la decisión cerrada con Johan: **las reglas deterministas
detectan qué dato falta** (`tasks/task_slots.py`, sin LLM, sin costo ni latencia) y **el
LLM solo redacta la frase** para que suene a persona y no a formulario (CA-20).

Esta función NUNCA decide SI falta un dato — cuando se la llama, esa decisión ya está
tomada (CA-21). Y nunca lanza: si el proveedor falla, tarda o devuelve basura, se usa la
frase de respaldo, que también es una frase natural, y el flujo continúa igual.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

#: Respaldo fijo por slot. Frases naturales, no etiquetas de formulario (CA-20).
FALLBACK_QUESTIONS: Dict[str, str] = {
    "que": "¿Qué quiere que le recuerde?",
    "cuando": "¿Para cuándo se lo recuerdo?",
}

_GENERIC_FALLBACK = "¿Me da ese dato, por favor?"
_MAX_QUESTION_CHARS = 200

_SLOT_DESCRIPTIONS: Dict[str, str] = {
    "que": "qué cosa quiere que le recuerde",
    "cuando": "para cuándo quiere el recordatorio",
}

_SYSTEM_PROMPT = (
    "Eres un asistente personal educado y natural, estilo JARVIS. Te falta un dato para "
    "completar lo que el usuario te pidió. Devuelve UNA sola pregunta corta, en español, "
    "para pedirle ese dato. Suena a persona, nunca a formulario. No expliques nada, no "
    "uses viñetas ni comillas: devuelve solo la pregunta."
)


def fallback_question(slot: str) -> str:
    """Return la repregunta de respaldo para `slot`, sin consultar al LLM."""
    return FALLBACK_QUESTIONS.get(slot, _GENERIC_FALLBACK)


def _sanitize(raw: object) -> Optional[str]:
    """Return la pregunta usable, o None si la respuesta del LLM no sirve."""
    if not isinstance(raw, str):
        return None
    question = " ".join(raw.split())          # colapsa saltos de línea y espacios
    question = question.strip().strip('"').strip()
    if not question or len(question) > _MAX_QUESTION_CHARS:
        return None
    return question


def ask_question(action: str, slot: str, slots: Dict[str, str]) -> str:
    """Return la repregunta redactada por el LLM, o la de respaldo si falla (CA-20)."""
    respaldo = fallback_question(slot)
    descripcion = _SLOT_DESCRIPTIONS.get(slot, f"el dato '{slot}'")

    contexto = ""
    if slots:
        ya_dicho = "; ".join(f"{k}: {v}" for k, v in slots.items() if v)
        if ya_dicho:
            contexto = f" Ya sabes esto del pedido: {ya_dicho}."

    prompt = (
        f"El usuario pidió '{action}' pero falta un dato: {descripcion}.{contexto} "
        f"Escribe la pregunta para pedírselo."
    )

    try:
        from ai.llm_provider import generate_response

        raw = generate_response([{"role": "user", "content": prompt}], _SYSTEM_PROMPT)
    except Exception as e:
        logger.warning(f"[Diálogo] el LLM no pudo redactar la repregunta ({e}); uso el respaldo")
        return respaldo

    question = _sanitize(raw)
    if question is None:
        logger.info("[Diálogo] respuesta del LLM inservible para la repregunta; uso el respaldo")
        return respaldo
    return question
