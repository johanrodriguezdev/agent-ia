"""
tests/test_task_slots.py

REQ-021 — detección de slots obligatorios de `task_create` (`tasks/task_slots.py`) y
FIJACIÓN del comportamiento actual de `tasks/task_manager.py::parse_natural_task`, que
llegó a este REQ con CERO tests (baseline-021.md §3).

Los tests de la sección "fijación" pintan el comportamiento que REQ-021 decide NO cambiar
(arquitectura-021.md §3.4): si alguien toca el fallback de `parse_natural_task` en el
futuro, saltan acá y no en producción.

Sin red, sin micrófono, sin `sleep` real (.claude/rules/testing.md).
"""

import datetime

import pytest

from tasks.task_manager import parse_natural_task


def _manana_a_las(hour: int) -> datetime.datetime:
    base = datetime.datetime.now() + datetime.timedelta(days=1)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0)


# ─────────────────────────────────────────────
#  Fijación del comportamiento ACTUAL de parse_natural_task (NO cambia en REQ-021)
# ─────────────────────────────────────────────

def test_fijacion_fallback_de_titulo_sin_contenido():
    """`task_manager.py:262` (`if not title or len(title) < 3: title = text.strip()`) es
    la línea que borra la señal de "falta el qué". REQ-021 la deja INTACTA a propósito
    (arquitectura-021.md §3.4): tiene cero tests, la usan 4 canales, y el camino
    conversacional nuevo ya no la alcanza con un título vacío."""
    assert parse_natural_task("ponme un recordatorio", "default")["title"] == (
        "Ponme un recordatorio"
    )
    assert parse_natural_task("recuérdame", "default")["title"] == "Recuérdame"
    assert parse_natural_task("recuérdame algo", "default")["title"] == "Algo"
    assert parse_natural_task("recuérdame una cosa", "default")["title"] == "Una cosa"
    assert parse_natural_task("recuérdame mañana a las 9", "default")["title"] == (
        "Recuérdame mañana a las 9"
    )


def test_fijacion_fecha_inventada_cuando_no_hay_fecha():
    """La otra mitad del problema: sin fecha, `parse_natural_task` inventa `now()+1h`.
    Se fija el comportamiento; REQ-021 lo evita NO llegando hasta acá con frases
    incompletas, no modificando la función."""
    antes = datetime.datetime.now()
    info = parse_natural_task("recuérdame algo", "default")
    despues = datetime.datetime.now()

    remind_at = datetime.datetime.fromisoformat(info["remind_at"])
    assert antes + datetime.timedelta(minutes=59) <= remind_at
    assert remind_at <= despues + datetime.timedelta(hours=1, minutes=1)


def test_fijacion_frase_completa_de_un_solo_tiro():
    """CA-03 — valor de referencia medido por orion-baseline (§4.1). La frase completa
    tiene que seguir dando exactamente esto después de REQ-021."""
    info = parse_natural_task("recuérdame llamar al contador mañana a las 9", "default")

    assert info["title"] == "Llamar al contador"
    assert info["remind_at"] == _manana_a_las(9).isoformat()
    assert info["due_date"] == info["remind_at"]
    assert info["recurrence"] is None
    assert info["priority"] == "normal"


def test_fijacion_texto_sin_trigger_no_es_tarea():
    assert parse_natural_task("hola, cómo estás", "default") is None


# ─────────────────────────────────────────────
#  scan_task_slots() — las 8 filas de arquitectura-021.md §3.3
# ─────────────────────────────────────────────

@pytest.mark.parametrize(
    "texto,missing_esperado",
    [
        ("recuérdame algo", ("que", "cuando")),
        ("recuérdame", ("que", "cuando")),
        ("recuérdame una cosa", ("que", "cuando")),
        ("ponme un recordatorio", ("que", "cuando")),
        ("recuérdame mañana a las 9", ("que",)),
        ("recuérdame llamar al contador", ("cuando",)),
        ("recuérdame llamar al contador mañana a las 9", ()),
        # Preserva `test_resolution.py::test_bulk_no_intercepta_create`.
        ("recuérdame completar todas mis tareas mañana", ()),
    ],
)
def test_scan_task_slots_tabla(texto, missing_esperado):
    from tasks.task_slots import scan_task_slots

    scan = scan_task_slots(texto)

    assert scan.missing == missing_esperado, (texto, scan.filled)
    assert scan.action == "task_create"
    assert scan.is_complete is (missing_esperado == ())
    for slot in scan.filled:
        assert slot not in scan.missing, (texto, scan.filled)


def test_scan_task_slots_es_puro(monkeypatch):
    """CA-21: detectar qué falta no consume LLM, no toca la DB y no ejecuta nada."""
    import ai.llm_provider as llm
    import tasks.task_manager as tm
    from tasks.task_slots import scan_task_slots

    def explotar(*a, **k):  # pragma: no cover - debe no invocarse nunca
        raise AssertionError("scan_task_slots() no puede llamar acá")

    monkeypatch.setattr(llm, "generate_response", explotar)
    monkeypatch.setattr(tm, "_get_conn", explotar)

    scan_task_slots("recuérdame algo")
    scan_task_slots("recuérdame llamar al contador mañana a las 9")


def test_scan_extrae_el_fragmento_de_fecha_para_recomponer():
    from tasks.task_slots import scan_task_slots

    scan = scan_task_slots("recuérdame mañana a las 9")

    assert scan.filled["cuando"] == "mañana a las 9"


def test_scan_pasado_manana_no_deja_pasado_como_contenido():
    """La alternancia de `TASK_DATE_PATTERNS` matchea "mañana" dentro de "pasado mañana"
    y dejaría "pasado" suelto pareciendo un título."""
    from tasks.task_slots import scan_task_slots

    scan = scan_task_slots("recuérdame pasado mañana")

    assert scan.missing == ("que",)
    assert "pasado" in scan.filled["cuando"]


# ─────────────────────────────────────────────
#  compose_task_sentence() + parse_natural_task() — la cadena de CA-02
# ─────────────────────────────────────────────

def test_ca02_cadena_compose_mas_parse_da_la_tarea_correcta():
    """CA-02: tras completar el caso de referencia por diálogo, la tarea queda con título
    "Llamar al contador" y `remind_at` de mañana 09:00 — nunca "Algo", nunca `now()+1h`.
    El diálogo ejerce EXACTAMENTE el mismo `parse_natural_task` del camino de un tiro."""
    from tasks.task_slots import compose_task_sentence

    frase = compose_task_sentence({"que": "llamar al contador", "cuando": "mañana a las 9"})
    info = parse_natural_task(frase, "default")

    assert info["title"] == "Llamar al contador"
    assert info["remind_at"] == _manana_a_las(9).isoformat()


def test_compose_con_un_solo_slot_sigue_siendo_reconocible_como_tarea():
    from tasks.task_slots import compose_task_sentence

    frase = compose_task_sentence({"que": "llamar al contador"})

    assert frase == "recuérdame llamar al contador"
    assert parse_natural_task(frase, "default") is not None


def test_compose_no_inventa_recurrencia_ni_prioridad():
    """CA-19/ASUMIDO de la SPEC: prioridad y recurrencia se siguen infiriendo del texto,
    nunca se repreguntan ni se inventan."""
    from tasks.task_slots import compose_task_sentence

    info = parse_natural_task(
        compose_task_sentence({"que": "llamar al contador", "cuando": "mañana a las 9"}),
        "default",
    )
    assert info["recurrence"] is None
    assert info["priority"] == "normal"

    info_recurrente = parse_natural_task(
        compose_task_sentence({"que": "tomar agua", "cuando": "todos los días a las 9"}),
        "default",
    )
    assert info_recurrente["recurrence"] == "daily"


# ─────────────────────────────────────────────
#  Decisión (d) — las dos listas de triggers NO se unifican, pero no pueden invertirse
# ─────────────────────────────────────────────

def test_triggers_de_resolution_son_subconjunto_de_task_manager():
    """arquitectura-021.md §3.5: la divergencia entre `_TASK_CREATE_TRIGGERS` (12) y
    `TASK_TRIGGERS` (14) es deliberada, pero solo es inofensiva en una dirección: toda
    frase que `_try_task_tool` acepta, `parse_natural_task` también la reconoce. Si
    alguien invierte la relación, esto salta."""
    from core.resolution import _TASK_CREATE_TRIGGERS
    from tasks.task_manager import TASK_TRIGGERS

    for trigger in _TASK_CREATE_TRIGGERS:
        assert any(trigger.startswith(t) or t == trigger for t in TASK_TRIGGERS), (
            f"'{trigger}' de resolution.py no lo reconoce task_manager.py"
        )


def test_has_content_tokens():
    """El mismo criterio de "contenido" que usa `_answers_slot("que", ...)`."""
    from tasks.task_slots import has_content_tokens

    assert has_content_tokens("llamar al contador") is True
    assert has_content_tokens("algo") is False
    assert has_content_tokens("una cosa") is False
    assert has_content_tokens("") is False
    assert has_content_tokens("   ") is False
