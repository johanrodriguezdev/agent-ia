"""
tasks/task_slots.py
Detección de los datos obligatorios ("slots") de `task_create` — REQ-021.

Existe porque `parse_natural_task()` **nunca reporta la ausencia de un dato**: su fallback
(`if not title or len(title) < 3: title = text.strip()`, `task_manager.py`) convierte
"ponme un recordatorio" en un título que *parece* válido, y la falta de fecha se tapa con
`now() + 1h`. Antes de REQ-021 no había ninguna señal que consultar, así que la detección
tiene que ser una función nueva y explícita (baseline-021.md §4.2, arquitectura-021.md §3).

Contrato:
- `scan_task_slots()` es **pura y determinista**: solo `re` y `_parse_natural_date()`.
  Nunca consulta el LLM, nunca toca la base de datos, nunca ejecuta nada (CA-21). Por eso
  puede llamarse desde `core/resolution.py` FUERA del gate de seguridad, sin moverlo.
- `compose_task_sentence()` recompone una frase natural con los slots ya llenos, para que
  el diálogo termine ejerciendo EXACTAMENTE el mismo `parse_natural_task()` que el camino
  de un solo tiro. Así la detección y la creación no pueden contradecirse (CA-02), y la
  recurrencia y la prioridad se siguen infiriendo del texto sin repreguntarse (CA-19).

`tasks/task_manager.py` nunca importa este módulo: la dependencia va en un solo sentido.
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from tasks.task_manager import TASK_DATE_PATTERNS, TASK_TRIGGERS, _parse_natural_date

logger = logging.getLogger(__name__)

SLOT_WHAT = "que"
SLOT_WHEN = "cuando"

#: Orden normativo de repregunta: primero el "qué", que es como habla una persona y es el
#: orden del caso de referencia de la SPEC.
REQUIRED_TASK_SLOTS: Tuple[str, ...] = (SLOT_WHAT, SLOT_WHEN)

TASK_CREATE_ACTION = "task_create"

#: Verbo de creación con el que se recompone la frase canónica. Está en `TASK_TRIGGERS`,
#: así que la frase recompuesta siempre vuelve a ser reconocida como tarea.
_CANONICAL_TRIGGER = "recuérdame"

# La alternancia `(?:mañana|pasado mañana|hoy)` de `TASK_DATE_PATTERNS` matchea "mañana"
# dentro de "pasado mañana" y deja "pasado" suelto, que parecería contenido. Se quita el
# compuesto primero. No modifica `TASK_DATE_PATTERNS`: es un paso previo de este módulo.
_COMPOUND_DATE_PATTERNS = (r'\bpasado\s+ma[ñn]ana\b',)

# Tokens que NO cuentan como contenido del "qué": artículos, preposiciones, pronombres,
# verbos imperativos de creación, sustantivos-cáscara y sustantivos de la propia acción.
# Los tokens de menos de 3 caracteres se descartan aparte, así que "el"/"la"/"un"/"de"
# no hace falta listarlos.
_NON_CONTENT_TOKENS = frozenset({
    # artículos y determinantes
    "una", "unos", "unas", "los", "las", "del", "esta", "este", "esa", "ese",
    # preposiciones y conjunciones
    "por", "para", "con", "sin", "sobre", "que", "como", "pero",
    # pronombres y posesivos
    "mis", "tus", "sus", "eso", "esto", "aquello", "les",
    # verbos imperativos de creación
    "ponme", "pon", "poner", "agenda", "agendar", "anota", "anotar", "apunta",
    "apuntar", "crea", "crear", "créame", "creame", "hazme", "haz", "añade",
    "añadir", "agrega", "agregar", "mete", "meter", "guarda", "guardar",
    # sustantivos-cáscara
    "algo", "cosa", "cosas", "vaina", "nada", "asunto",
    # sustantivos de la propia acción
    "tarea", "tareas", "recordatorio", "recordatorios", "pendiente", "pendientes",
})

_MIN_CONTENT_TOKEN_CHARS = 3

_TOKEN_SPLIT_RE = re.compile(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]+", re.UNICODE)
_SPACES_RE = re.compile(r"\s+")
_EDGE_PUNCT = " \t\r\n.,;:!¡?¿-—…\"'"


@dataclass(frozen=True)
class SlotScan:
    """Qué slots obligatorios de `task_create` trae una frase y cuáles le faltan."""

    action: str
    filled: Dict[str, str]
    missing: Tuple[str, ...]
    source_text: str

    @property
    def is_complete(self) -> bool:
        """Return True si no falta ningún dato obligatorio."""
        return not self.missing


def _trigger_pattern() -> str:
    """Return la alternancia de todos los triggers, con límites de palabra."""
    ordenados = sorted(TASK_TRIGGERS, key=len, reverse=True)
    return r"\b(?:" + "|".join(re.escape(t.strip()) for t in ordenados) + r")\b:?"


_TRIGGERS_RE = re.compile(_trigger_pattern(), re.IGNORECASE)


def _strip_triggers(text: str) -> str:
    """Quitar TODAS las apariciones de un trigger, no solo la del inicio.

    `parse_natural_task()` solo recorta el trigger cuando la frase EMPIEZA con él
    (`text_lower.startswith(trigger)`), y por eso "ponme un recordatorio" conserva el
    trigger en el título. Acá se corrige sin tocar aquella función.
    """
    return _TRIGGERS_RE.sub(" ", text)


def _strip_date_expressions(text: str) -> str:
    """Quitar las expresiones de fecha con la MISMA lista que usa `parse_natural_task`."""
    clean = text
    for pattern in _COMPOUND_DATE_PATTERNS:
        clean = re.sub(pattern, " ", clean, flags=re.IGNORECASE)
    for pattern in TASK_DATE_PATTERNS:
        clean = re.sub(pattern, " ", clean, flags=re.IGNORECASE)
    return clean


def _extract_date_fragment(text: str) -> str:
    """Return el trozo de `text` que expresa la fecha, para poder recomponer la frase."""
    fragmentos: List[Tuple[int, str]] = []
    for pattern in _COMPOUND_DATE_PATTERNS + tuple(TASK_DATE_PATTERNS):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            fragmentos.append((match.start(), match.group(0).strip()))
    if not fragmentos:
        return ""

    fragmentos.sort(key=lambda f: f[0])
    vistos: List[str] = []
    for _, fragmento in fragmentos:
        if any(fragmento in previo for previo in vistos):
            continue
        vistos.append(fragmento)
    return _normalize_spaces(" ".join(vistos))


def _normalize_spaces(text: str) -> str:
    return _SPACES_RE.sub(" ", text).strip(_EDGE_PUNCT)


def _content_tokens(text: str) -> List[str]:
    """Return los tokens de `text` que cuentan como contenido real."""
    tokens = [t for t in _TOKEN_SPLIT_RE.split(text.lower()) if t]
    return [
        t for t in tokens
        if len(t) >= _MIN_CONTENT_TOKEN_CHARS and t not in _NON_CONTENT_TOKENS
    ]


def has_content_tokens(text: str) -> bool:
    """Return True si `text` tiene al menos un token de contenido real.

    Lo usa también `core/resolution.py::_answers_slot()` para el slot "qué": la misma
    definición de "contenido" en los dos lados, sin copiar la lista de tokens.
    """
    if not text:
        return False
    return bool(_content_tokens(_strip_date_expressions(_strip_triggers(text))))


def scan_task_slots(text: str) -> SlotScan:
    """Return qué slots obligatorios de `task_create` trae `text` y cuáles faltan.

    Determinista y pura: solo `re` y `_parse_natural_date()`. Nunca consulta el LLM,
    nunca toca la base de datos, nunca ejecuta nada (CA-21).
    """
    source = text or ""
    filled: Dict[str, str] = {}
    missing: List[str] = []

    sin_triggers = _strip_triggers(source)

    # ── el "qué" ──────────────────────────────────────────────
    resto = _normalize_spaces(_strip_date_expressions(sin_triggers))
    if _content_tokens(resto):
        filled[SLOT_WHAT] = resto
    else:
        missing.append(SLOT_WHAT)

    # ── el "cuándo" ───────────────────────────────────────────
    # Esta señal ya es honesta hoy: la ausencia de fecha se ve porque
    # `_parse_natural_date()` retorna None. Quien la borra es el `if remind_at is None`
    # de `parse_natural_task()`, no el parser. Se consulta la función real, no una copia.
    if _parse_natural_date(source) is not None:
        fragmento = _extract_date_fragment(sin_triggers) or _normalize_spaces(sin_triggers)
        filled[SLOT_WHEN] = fragmento
    else:
        missing.append(SLOT_WHEN)

    return SlotScan(
        action=TASK_CREATE_ACTION,
        filled=filled,
        missing=tuple(missing),
        source_text=source,
    )


def compose_task_sentence(slots: Dict[str, str]) -> str:
    """Return una frase canónica de creación a partir de los slots llenos.

    `{"que": "llamar al contador", "cuando": "mañana a las 9"}`
      -> `"recuérdame llamar al contador mañana a las 9"`

    Es la ÚNICA forma en que el diálogo llega a `task_create`: se reusa entero el parseo
    de hoy (título, fecha, recurrencia, prioridad) en vez de construir el dict a mano.
    """
    partes = [_CANONICAL_TRIGGER]
    for slot in REQUIRED_TASK_SLOTS:
        valor = (slots.get(slot) or "").strip(_EDGE_PUNCT)
        if valor:
            partes.append(valor)
    return _normalize_spaces(" ".join(partes))
