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
import types

import pytest

from tasks import task_manager
from tasks.task_manager import _parse_natural_date, parse_natural_task
from tasks.task_slots import SLOT_WHEN, scan_task_slots


def _manana_a_las(hour: int) -> datetime.datetime:
    base = datetime.datetime.now() + datetime.timedelta(days=1)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0)


@pytest.fixture
def reloj(monkeypatch):
    """Congela la hora que ve `tasks/task_manager.py`. Devuelve la funcion que la fija.

    `_parse_natural_date()` lee el reloj dos veces —el `RELATIVE_BASE` de dateparser y el
    `_al_futuro()` que empuja al dia siguiente lo que ya paso—, asi que un test sobre "hoy
    a las 5" daba un resultado distinto segun la hora a la que se corriera la suite: hasta
    las 17:00 era hoy, despues era manana. Y lo de despues es lo CORRECTO en produccion
    (ver `_MARGEN_PASADO`): el que estaba mal era el test, que solo pasaba media jornada.

    Se sustituye el nombre `datetime` DENTRO del modulo, no el modulo real de la libreria
    estandar: el resto de la suite sigue viendo la hora de verdad.
    """
    def _fijar(momento: datetime.datetime) -> None:
        congelado = type("_DatetimeCongelado", (datetime.datetime,), {
            "now": classmethod(lambda cls, tz=None: momento),
        })
        monkeypatch.setattr(task_manager, "datetime", types.SimpleNamespace(
            datetime=congelado, timedelta=datetime.timedelta, date=datetime.date,
        ))

    return _fijar



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


# ─────────────────────────────────────────────
#  Decir el día tiene que contar como decir cuándo
# ─────────────────────────────────────────────

@pytest.mark.parametrize("frase", [
    "recuerdame llamar al banco hoy",
    "recuérdame llamar al banco hoy",
    "recuerdame llamar al banco manana",
    "recuerdame llamar al banco mañana",
    "recuerdame llamar al banco pasado manana",
    "recuerdame llamar al banco el lunes",
    "recuerdame llamar al banco hoy a las 5",
    "recuerdame llamar al banco en 2 horas",
])
def test_una_fecha_dentro_de_la_frase_cuenta_como_cuando(frase):
    """El caso que lo destapó.

    `scan_task_slots()` decide si hay que preguntar "¿para cuándo?", y consultaba a
    `_parse_natural_date()`, cuya rama de "hoy" solo devolvía algo si además había una
    hora: entraba en el `if`, no encontraba hora, y se caía sin retornar. Decir "hoy"
    equivalía a no decir nada — la tarea se creaba igual (con la fecha inventada por
    `parse_natural_task()`) y el agente seguía preguntando por una fecha que ya le habían
    dado.
    """
    scan = scan_task_slots(frase)

    assert SLOT_WHEN not in scan.missing, f"'{frase}' dice cuándo y no se reconoció"
    assert scan.filled.get(SLOT_WHEN)


@pytest.mark.parametrize("frase", [
    "recuerdame comprar pan",
    "recuerdame revisar el informe trimestral",
    "recuerdame llamar al contador",
])
def test_sin_fecha_se_sigue_preguntando(frase):
    """La otra mitad: aflojar la detección no puede hacer que se invente una fecha. Que
    `parse_natural_task()` tape la ausencia con `now()+1h` es justo lo que este chequeo
    existe para impedir."""
    assert SLOT_WHEN in scan_task_slots(frase).missing


# ─────────────────────────────────────────────
#  Y tiene que caer en el día correcto
# ─────────────────────────────────────────────

def test_hoy_cae_hoy():
    """Decía "hoy" y el recordatorio quedaba para MAÑANA.

    `dateparser` devuelve el instante actual para "hoy"; al compararlo ya quedaba unos
    microsegundos en el pasado, y la corrección "si ya pasó, muévelo al día siguiente" lo
    empujaba un día entero.
    """
    fecha = _parse_natural_date("recuerdame llamar al banco hoy")

    assert fecha is not None
    assert fecha.date() == datetime.date.today()


def test_manana_cae_manana_con_o_sin_ene():
    """El reconocedor de voz pierde la eñe a menudo, y mucha gente escribe sin acentos.
    "manana" no era ninguna fecha: ni la rama de mañana la reconocía."""
    hoy = datetime.date.today()
    esperado = hoy + datetime.timedelta(days=1)

    assert _parse_natural_date("recuerdame llamar al banco mañana").date() == esperado
    assert _parse_natural_date("recuerdame llamar al banco manana").date() == esperado


def test_pasado_manana_no_cae_en_manana():
    """"pasado mañana" contiene "mañana", y la rama de mañana estaba PRIMERO: se lo llevaba
    siempre, y la de pasado mañana era inalcanzable."""
    esperado = datetime.date.today() + datetime.timedelta(days=2)

    assert _parse_natural_date("recuerdame llamar al banco pasado mañana").date() == esperado
    assert _parse_natural_date("recuerdame llamar al banco pasado manana").date() == esperado


def test_la_hora_dicha_se_respeta(reloj):
    """Decir el día no puede borrar la hora."""
    reloj(datetime.datetime(2026, 3, 10, 9, 0))

    fecha = _parse_natural_date("recuerdame llamar al banco hoy a las 5")

    assert fecha.date() == datetime.date(2026, 3, 10)
    assert fecha.hour == 17, "las 5 de la tarde"


def test_una_hora_de_hoy_que_ya_paso_se_va_a_manana(reloj):
    """La otra mitad de la regla, la que hacia fallar al test anterior media jornada.

    "hoy a las 5" dicho a las seis de la tarde es un recordatorio para las 5 de MANANA: un
    aviso en el pasado no le sirve a nadie. Estaba sin fijar por test justamente porque el
    reloj real no dejaba probar las dos mitades en la misma corrida."""
    reloj(datetime.datetime(2026, 3, 10, 18, 0))

    fecha = _parse_natural_date("recuerdame llamar al banco hoy a las 5")

    assert fecha.date() == datetime.date(2026, 3, 11)
    assert fecha.hour == 17, "las 5 de la tarde, pero de manana"


def test_manana_a_las_9_es_manana_y_no_hoy():
    """Con "manana" sin eñe sin reconocer, esta frase caía en la rama genérica de la hora y
    programaba el recordatorio para HOY a las 9 — el día equivocado."""
    fecha = _parse_natural_date("recuerdame llamar al banco manana a las 9")

    assert fecha.date() == datetime.date.today() + datetime.timedelta(days=1)
    assert fecha.hour == 9


def test_hoy_no_se_sale_de_hoy_ni_a_las_once_de_la_noche():
    """A las 23:04, "hoy" devolvía mañana a las 00:04: `ahora + 1 hora` cruzaba medianoche."""
    from tasks.task_manager import _hoy_sin_hora

    noche = datetime.datetime(2026, 9, 10, 23, 4, 39)
    assert _hoy_sin_hora(noche).date() == noche.date()

    manana_temprano = datetime.datetime(2026, 9, 10, 7, 0)
    assert _hoy_sin_hora(manana_temprano).hour == 9        # la hora por defecto

    media_tarde = datetime.datetime(2026, 9, 10, 15, 0)
    assert _hoy_sin_hora(media_tarde) == datetime.datetime(2026, 9, 10, 16, 0)
