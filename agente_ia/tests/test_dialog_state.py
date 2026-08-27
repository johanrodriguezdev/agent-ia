"""
tests/test_dialog_state.py

REQ-021 — `core/dialog_state.py`: ciclo de vida, expiración con reloj inyectado y
aislamiento por `(user_id, canal)`.

El reloj SIEMPRE se inyecta: ni un solo `sleep` real (.claude/rules/testing.md).
"""

import pytest

from core.dialog_questions import FALLBACK_QUESTIONS, ask_question, fallback_question
from core.dialog_state import DIALOG_TTL_SECONDS, DialogStore, PendingDialog
from core.security_manager import ChannelType


class FakeClock:
    """Reloj monotónico controlado por el test."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _store(clock=None) -> DialogStore:
    return DialogStore(clock=clock or FakeClock())


def _open(store: DialogStore, user_id="u1", channel=ChannelType.DESKTOP, **kwargs):
    params = {
        "action": "task_create",
        "slots": {},
        "missing": ("que", "cuando"),
        "question": "¿Qué quiere que le recuerde?",
    }
    params.update(kwargs)
    return store.open(user_id, channel, **params)


# ─────────────────────────────────────────────
#  Ciclo de vida (CA-06)
# ─────────────────────────────────────────────

def test_open_get_fill_cancel():
    store = _store()

    abierto = _open(store)
    assert abierto.action == "task_create"
    assert abierto.missing == ("que", "cuando")
    assert abierto.next_slot == "que"

    assert store.get("u1", ChannelType.DESKTOP) is abierto

    tras_que = store.fill("u1", ChannelType.DESKTOP, "que", "llamar al contador")
    assert tras_que.slots == {"que": "llamar al contador"}
    assert tras_que.missing == ("cuando",)
    assert tras_que.next_slot == "cuando"

    tras_cuando = store.fill("u1", ChannelType.DESKTOP, "cuando", "mañana a las 9")
    assert tras_cuando.missing == ()
    assert tras_cuando.next_slot is None

    store.cancel("u1", ChannelType.DESKTOP)
    assert store.get("u1", ChannelType.DESKTOP) is None


def test_fill_sin_dialogo_abierto_devuelve_none():
    store = _store()
    assert store.fill("u1", ChannelType.DESKTOP, "que", "algo") is None


def test_clear_all():
    store = _store()
    _open(store, user_id="a")
    _open(store, user_id="b")

    store.clear_all()

    assert store.get("a", ChannelType.DESKTOP) is None
    assert store.get("b", ChannelType.DESKTOP) is None


# ─────────────────────────────────────────────
#  CA-19 — la acción destino no se puede cambiar
# ─────────────────────────────────────────────

def test_ca19_la_accion_destino_no_tiene_setter():
    store = _store()
    dialog = _open(store)

    with pytest.raises(Exception):
        dialog.action = "shutdown_pc"        # frozen dataclass -> FrozenInstanceError

    tras_llenar = store.fill("u1", ChannelType.DESKTOP, "que", "apaga el pc")
    assert tras_llenar.action == "task_create"
    assert store.get("u1", ChannelType.DESKTOP).action == "task_create"


# ─────────────────────────────────────────────
#  CA-07 — expiración silenciosa, con reloj inyectado
# ─────────────────────────────────────────────

def test_ca07_expira_al_leer_sin_hilo_de_fondo():
    clock = FakeClock()
    store = DialogStore(ttl_seconds=180.0, clock=clock)
    _open(store)

    clock.advance(179)
    assert store.get("u1", ChannelType.DESKTOP) is not None

    clock.advance(2)                          # 181 s > TTL
    assert store.get("u1", ChannelType.DESKTOP) is None
    # Y se purgó de verdad: no reaparece si el reloj retrocediera.
    assert store.get("u1", ChannelType.DESKTOP) is None


def test_ca07_el_ttl_por_defecto_son_tres_minutos():
    assert DIALOG_TTL_SECONDS == 180.0


def test_ca07_fill_reinicia_la_cuenta():
    clock = FakeClock()
    store = DialogStore(ttl_seconds=180.0, clock=clock)
    _open(store)

    clock.advance(170)
    store.fill("u1", ChannelType.DESKTOP, "que", "llamar al contador")
    clock.advance(170)                        # 340 s desde open, 170 desde el avance

    assert store.get("u1", ChannelType.DESKTOP) is not None


# ─────────────────────────────────────────────
#  CA-32 — un desvío no compra tiempo
# ─────────────────────────────────────────────

def test_ca32_touch_question_no_mueve_el_reloj():
    clock = FakeClock()
    store = DialogStore(ttl_seconds=180.0, clock=clock)
    abierto = _open(store)

    clock.advance(100)
    store.touch_question("u1", ChannelType.DESKTOP, "Por cierto, ¿para cuándo?")
    tras_touch = store.get("u1", ChannelType.DESKTOP)
    assert tras_touch.last_progress_at == abierto.last_progress_at
    assert tras_touch.question == "Por cierto, ¿para cuándo?"

    clock.advance(81)                         # 181 s desde el ÚLTIMO AVANCE real
    assert store.get("u1", ChannelType.DESKTOP) is None


def test_ca32_fill_si_mueve_el_reloj():
    clock = FakeClock()
    store = DialogStore(ttl_seconds=180.0, clock=clock)
    abierto = _open(store)

    clock.advance(100)
    tras_fill = store.fill("u1", ChannelType.DESKTOP, "que", "llamar al contador")

    assert tras_fill.last_progress_at > abierto.last_progress_at


# ─────────────────────────────────────────────
#  CA-08 / H6 — aislamiento por (user_id, canal)
# ─────────────────────────────────────────────

def test_ca08_aislamiento_entre_usuarios_del_mismo_canal():
    store = _store()
    _open(store, user_id="A", channel=ChannelType.TELEGRAM, question="pregunta de A")

    assert store.get("B", ChannelType.TELEGRAM) is None
    assert store.get("A", ChannelType.TELEGRAM).question == "pregunta de A"

    store.cancel("B", ChannelType.TELEGRAM)
    assert store.get("A", ChannelType.TELEGRAM) is not None, "cancelar B no puede tocar A"


def test_ca08_aislamiento_entre_canales_del_mismo_usuario():
    store = _store()
    _open(store, user_id="A", channel=ChannelType.TELEGRAM, question="por telegram")
    _open(store, user_id="A", channel=ChannelType.DESKTOP, question="por escritorio")

    assert store.get("A", ChannelType.TELEGRAM).question == "por telegram"
    assert store.get("A", ChannelType.DESKTOP).question == "por escritorio"

    store.cancel("A", ChannelType.TELEGRAM)
    assert store.get("A", ChannelType.TELEGRAM) is None
    assert store.get("A", ChannelType.DESKTOP) is not None


def test_h3_open_rechaza_user_id_vacio():
    """H3 de la auditoría: un diálogo sin dueño se compartiría entre todos los usuarios
    del canal. Es la única vía de fuga entre usuarios que tenía el diseño."""
    store = _store()

    for user_id in ("", None):
        with pytest.raises(ValueError):
            _open(store, user_id=user_id)

    assert store.get("", ChannelType.TELEGRAM) is None


def test_open_rechaza_accion_vacia():
    store = _store()
    with pytest.raises(ValueError):
        _open(store, action="")


# ─────────────────────────────────────────────
#  CA-20 / CA-21 — la repregunta
# ─────────────────────────────────────────────

def test_ca20_respaldo_cuando_el_llm_falla(monkeypatch):
    def explotar(*a, **k):
        raise RuntimeError("proveedor caído")

    monkeypatch.setattr("ai.llm_provider.generate_response", explotar)

    assert ask_question("task_create", "que", {}) == FALLBACK_QUESTIONS["que"]
    assert ask_question("task_create", "cuando", {}) == FALLBACK_QUESTIONS["cuando"]


@pytest.mark.parametrize("respuesta", ["", "   ", None, 12345, "x" * 201, ["no", "str"]])
def test_ca20_respuestas_inservibles_caen_al_respaldo(monkeypatch, respuesta):
    monkeypatch.setattr(
        "ai.llm_provider.generate_response", lambda *a, **k: respuesta
    )
    assert ask_question("task_create", "que", {}) == FALLBACK_QUESTIONS["que"]


def test_ca20_usa_la_frase_del_llm_cuando_es_valida(monkeypatch):
    monkeypatch.setattr(
        "ai.llm_provider.generate_response",
        lambda *a, **k: '  "¿Y qué le recuerdo exactamente?"\n',
    )
    assert ask_question("task_create", "que", {}) == "¿Y qué le recuerdo exactamente?"


def test_las_frases_de_respaldo_suenan_a_persona():
    """CA-20: el respaldo no puede ser una etiqueta de formulario."""
    for slot, frase in FALLBACK_QUESTIONS.items():
        assert frase.startswith("¿") and frase.endswith("?"), slot
        assert "campo" not in frase.lower() and "requerido" not in frase.lower()
    assert fallback_question("slot_inexistente").endswith("?")


def test_pending_dialog_es_inmutable():
    dialog = PendingDialog(
        action="task_create", slots={}, missing=("que",), question="?",
        user_id="u1", channel_value="desktop", last_progress_at=0.0,
    )
    with pytest.raises(Exception):
        dialog.missing = ()
