"""
tests/test_telegram_confirmation_adapter.py

Suite de tests para TelegramConfirmationAdapter (REQ-018) — adaptador de confirmación
conversacional para ChannelType.TELEGRAM. Cobertura de CA-04 a CA-09 de SPEC-018.md, más
los Hallazgos B y E de `pruebas/security-audit-018.md` (re-chequeo, 2026-08-20).

Convenciones (.claude/rules/testing.md):
- Sin red real: `bot.send_message()` es una corutina falsa que solo registra lo enviado.
- Hilos reales (`threading.Thread`) para ejercer de verdad el puente async→sync (CA-08) —
  se levanta un event loop real en un hilo aparte, equivalente al loop de python-telegram-bot.
- `set_request_context()` se llama SIEMPRE dentro del hilo worker que invoca `confirm()`
  (nunca en el hilo principal del test) — reproduce cómo `asyncio.to_thread()` propaga el
  `contextvars.Context` vigente al hilo nuevo en producción; un `threading.Thread` crudo no
  hereda contextvars automáticamente, a diferencia de `asyncio.to_thread()`.
"""

import asyncio
import threading
import time

import pytest

import channels.telegram_confirmation_adapter as mod
from channels.telegram_confirmation_adapter import TelegramConfirmationAdapter


class _FakeBot:
    """Bot falso: send_message es una corutina real que registra lo enviado, sin red."""

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


def _make_adapter_with_loop():
    """Levanta un event loop real en un hilo aparte (equivalente al loop de python-
    telegram-bot) y liga un TelegramConfirmationAdapter nuevo a él con un bot falso."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    bot = _FakeBot()
    adapter = TelegramConfirmationAdapter()
    adapter.bind(bot, loop)
    return adapter, bot, loop, thread


def _stop_loop(loop, thread):
    def _cancel_pending_tasks():
        for task in asyncio.all_tasks(loop=loop):
            task.cancel()

    loop.call_soon_threadsafe(_cancel_pending_tasks)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


@pytest.fixture(autouse=True)
def _reset_request_context():
    """`_request_ctx` es un ContextVar a nivel de módulo. Un `threading.Thread` crudo
    arranca con su propio Context aislado (no hereda nada), pero una llamada directa a
    `set_request_context()` en el hilo PRINCIPAL de pytest sí persiste en el Context
    ambiente de ese hilo entre tests — sin este reset, un test que setea el contexto en el
    hilo principal (p. ej. para probar Hallazgo B) deja un valor filtrado que el siguiente
    test que espera `ctx is None` nunca ve, y termina esperando el timeout real completo
    (120s) en vez de fallar cerrado de inmediato por falta de contexto."""
    mod._request_ctx.set(None)
    yield
    mod._request_ctx.set(None)


def _confirm_in_new_thread(adapter, user_id, chat_id, action_name, message, result_holder, key):
    """Corre confirm() en un hilo nuevo, seteando el contexto de request DENTRO de ese
    hilo (ver docstring del módulo) — equivalente a lo que asyncio.to_thread() logra
    automáticamente en producción."""

    def _target():
        adapter.set_request_context(user_id, chat_id)
        result_holder[key] = adapter.confirm(action_name, message)

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    return t


# --- CA-04 — mensaje enviado tal cual, sin reformular ------------------------------------


def test_ca04_confirm_envia_mensaje_exacto_sin_reformular():
    adapter, bot, loop, thread = _make_adapter_with_loop()
    try:
        assert adapter.reserve_pending("123") is True
        result_holder = {}
        _confirm_in_new_thread(adapter, "123", 999, "delete_task", "¿confirmás? sí/no", result_holder, "r")

        time.sleep(0.1)
        assert adapter.resolve("123", "sí") is True

        # Espera activa corta a que el hilo worker termine de escribir el resultado.
        for _ in range(50):
            if "r" in result_holder:
                break
            time.sleep(0.02)

        assert result_holder["r"] is True
        assert bot.sent == [(999, "¿confirmás? sí/no")]
    finally:
        _stop_loop(loop, thread)


def test_confirm_sin_bind_previo_no_lanza_y_sigue_esperando_respuesta():
    """Si bind() nunca se llamó, _send_message() loguea y no envía nada — pero confirm()
    sigue esperando la respuesta con normalidad (fail-closed solo por timeout, nunca por
    excepción)."""
    adapter = TelegramConfirmationAdapter()
    adapter.reserve_pending("123")
    result_holder = {}
    _confirm_in_new_thread(adapter, "123", 999, "delete_task", "mensaje", result_holder, "r")

    time.sleep(0.05)
    adapter.resolve("123", "si")

    for _ in range(50):
        if "r" in result_holder:
            break
        time.sleep(0.02)
    assert result_holder["r"] is True


# --- CA-05/CA-06 — criterio exacto de confirmación, allowlist estricta -------------------


@pytest.mark.parametrize("texto", ["sí", "Si", "  SI  ", "yes", "YES", "s", " S "])
def test_ca06_tokens_afirmativos_confirman(texto):
    adapter, bot, loop, thread = _make_adapter_with_loop()
    try:
        adapter.reserve_pending("u1")
        result_holder = {}
        _confirm_in_new_thread(adapter, "u1", 1, "delete_task", "msg", result_holder, "r")
        time.sleep(0.05)
        adapter.resolve("u1", texto)
        for _ in range(50):
            if "r" in result_holder:
                break
            time.sleep(0.02)
        assert result_holder["r"] is True
    finally:
        _stop_loop(loop, thread)


@pytest.mark.parametrize("texto", ["tal vez", "sip", "dale", "no", "/tareas", "", "   "])
def test_ca06_tokens_ambiguos_o_negativos_cancelan_fail_closed(texto):
    adapter, bot, loop, thread = _make_adapter_with_loop()
    try:
        adapter.reserve_pending("u1")
        result_holder = {}
        _confirm_in_new_thread(adapter, "u1", 1, "delete_task", "msg", result_holder, "r")
        time.sleep(0.05)
        adapter.resolve("u1", texto)
        for _ in range(50):
            if "r" in result_holder:
                break
            time.sleep(0.02)
        assert result_holder["r"] is False
    finally:
        _stop_loop(loop, thread)


def test_resolve_sin_pendiente_retorna_false_sin_lanzar():
    adapter = TelegramConfirmationAdapter()
    assert adapter.resolve("nadie_esperando", "sí") is False


# --- CA-07 — timeout fail-closed, limpieza incondicional de _pending ---------------------


def test_ca07_timeout_resuelve_false_y_limpia_pending(monkeypatch):
    monkeypatch.setattr(mod, "CONFIRM_TIMEOUT_SECONDS", 0.2)
    adapter, bot, loop, thread = _make_adapter_with_loop()
    try:
        adapter.reserve_pending("u1")
        adapter.set_request_context("u1", 1)
        result = adapter.confirm("delete_task", "msg")
        assert result is False
        assert adapter.has_pending("u1") is False
    finally:
        _stop_loop(loop, thread)


# --- CA-08 — el hilo que invoca confirm() (equivalente al loop de PTB) no se bloquea -----


def test_ca08_confirm_corre_en_hilo_aparte_sin_bloquear_al_hilo_que_lo_lanza():
    """confirm() se ejecuta en un hilo real; el hilo "principal" (equivalente al loop de
    PTB atendiendo a otros usuarios) sigue haciendo trabajo mientras confirm() espera —
    verifica la premisa de CA-08 a nivel del adaptador."""
    adapter, bot, loop, thread = _make_adapter_with_loop()
    try:
        adapter.reserve_pending("u1")
        result_holder = {}
        worker = _confirm_in_new_thread(adapter, "u1", 1, "delete_task", "msg", result_holder, "r")

        # El hilo "principal" sigue "atendiendo a otro usuario" sin bloquearse mientras el
        # worker de u1 está suspendido en pending.event.wait().
        marker = []
        for _ in range(5):
            marker.append("trabajo")
            time.sleep(0.01)
        assert marker == ["trabajo"] * 5
        assert "r" not in result_holder  # el worker sigue esperando, todavía no resolvió

        adapter.resolve("u1", "sí")
        worker.join(timeout=5)
        assert result_holder["r"] is True
    finally:
        _stop_loop(loop, thread)


def test_contextvar_no_se_cruza_entre_dos_usuarios_concurrentes():
    """Dos usuarios piden confirmación "al mismo tiempo" — cada hilo worker debe ver su
    propio chat_id/resultado, sin cruzarse (aislamiento de contextvars entre hilos)."""
    adapter, bot, loop, thread = _make_adapter_with_loop()
    try:
        adapter.reserve_pending("userA")
        adapter.reserve_pending("userB")

        result_holder = {}
        ta = _confirm_in_new_thread(adapter, "userA", 111, "delete_task", "msg-A", result_holder, "a")
        tb = _confirm_in_new_thread(adapter, "userB", 222, "delete_task", "msg-B", result_holder, "b")

        time.sleep(0.1)
        adapter.resolve("userA", "sí")
        adapter.resolve("userB", "no")
        ta.join(timeout=5)
        tb.join(timeout=5)

        assert result_holder["a"] is True
        assert result_holder["b"] is False
        assert (111, "msg-A") in bot.sent
        assert (222, "msg-B") in bot.sent
    finally:
        _stop_loop(loop, thread)


# --- CA-09 / Hallazgo E — reserve_pending() es la verificación atómica y autoritativa ----


def test_ca09_reserve_pending_niega_segunda_reserva_para_mismo_usuario():
    adapter = TelegramConfirmationAdapter()
    assert adapter.reserve_pending("u1") is True
    assert adapter.reserve_pending("u1") is False  # segunda reserva denegada de inmediato


def test_ca09_reserve_pending_permite_reservar_de_nuevo_tras_resolucion():
    adapter = TelegramConfirmationAdapter()
    assert adapter.reserve_pending("u1") is True
    adapter.resolve("u1", "sí")
    assert adapter.reserve_pending("u1") is True


def test_ca09_reserve_pending_no_interfiere_entre_usuarios_distintos():
    adapter = TelegramConfirmationAdapter()
    assert adapter.reserve_pending("u1") is True
    assert adapter.reserve_pending("u2") is True


def test_confirm_sin_reserva_previa_deniega_fail_closed_sin_crear_entrada():
    """REQ-018/Hallazgo E — confirm() ya no crea su propia entrada; si se invoca sin que
    reserve_pending() haya corrido antes (violación del contrato interno), debe fallar
    cerrado en vez de crear una entrada nueva por su cuenta."""
    adapter = TelegramConfirmationAdapter()
    adapter.set_request_context("u1", 1)
    assert adapter.confirm("delete_task", "msg") is False
    assert adapter.has_pending("u1") is False


def test_confirm_sin_contexto_de_request_deniega_fail_closed():
    adapter = TelegramConfirmationAdapter()
    adapter.reserve_pending("u1")
    # set_request_context() nunca se llamó en este hilo — ctx queda en el default (None).
    assert adapter.confirm("delete_task", "msg") is False


# --- Hallazgo B — limpieza incondicional de _pending si el envío del mensaje lanza -------


def test_hallazgo_b_excepcion_en_run_coroutine_threadsafe_limpia_pending_y_retorna_false(
    monkeypatch,
):
    """REQ-018/Hallazgo B (security-audit-018.md) — si asyncio.run_coroutine_threadsafe()
    lanza de forma síncrona (p. ej. RuntimeError porque el loop ya no está corriendo, caso
    de borde de apagado/reinicio), confirm() no debe dejar una entrada huérfana en
    _pending ni la excepción debe escapar sin resolver — se resuelve a False."""
    adapter, bot, loop, thread = _make_adapter_with_loop()
    try:
        adapter.reserve_pending("u1")
        adapter.set_request_context("u1", 1)

        def boom(coro, _loop):
            coro.close()  # evita "coroutine was never awaited" — no se llegó a programar
            raise RuntimeError("loop cerrado (simulado, reinicio en curso)")

        monkeypatch.setattr(mod.asyncio, "run_coroutine_threadsafe", boom)

        result = adapter.confirm("delete_task", "msg")

        assert result is False
        assert adapter.has_pending("u1") is False
    finally:
        _stop_loop(loop, thread)


def test_send_message_future_result_timeout_no_impide_seguir_esperando_respuesta(monkeypatch):
    """Si el envío del mensaje tarda más que _SEND_TIMEOUT_SECONDS (mockeado a un valor
    chico), _send_message() lo loguea y retorna sin lanzar — confirm() sigue esperando la
    respuesta con normalidad en vez de fallar."""
    adapter, bot, loop, thread = _make_adapter_with_loop()
    try:
        adapter.reserve_pending("u1")

        async def _slow_send_message(chat_id, text):
            await asyncio.sleep(1)

        bot.send_message = _slow_send_message
        monkeypatch.setattr(mod, "_SEND_TIMEOUT_SECONDS", 0.05)

        result_holder = {}
        worker = _confirm_in_new_thread(adapter, "u1", 1, "delete_task", "msg", result_holder, "r")
        time.sleep(0.3)
        adapter.resolve("u1", "sí")
        worker.join(timeout=5)
        assert result_holder["r"] is True
    finally:
        _stop_loop(loop, thread)
