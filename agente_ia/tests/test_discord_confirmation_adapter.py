"""
tests/test_discord_confirmation_adapter.py
REQ-045 — Discord puede confirmar acciones amarillas y el bot no se bloquea mientras el
agente piensa.

Lo que protege esta suite:
- `DiscordConfirmationAdapter` manda la pregunta por el canal correcto y lee el «sí» con
  el mismo criterio que Telegram; un envío que falla expira fail-closed (CA-01, CA-02).
- `_responder_confirmacion()` consume la respuesta aunque no mencione al bot, y solo si
  había una pendiente (CA-04).
- `_procesar_con_confirmacion()` reserva antes del hilo, pone el contexto, corre el
  turno fuera del event loop y libera después (CA-05, CA-06).
- Los canales MCP habilitables incluyen Discord y siguen sin incluir voz (CA-07).

Sin discord real: un bot falso con `get_channel()` y un loop en un hilo aparte, igual que
`tests/test_telegram_confirmation_adapter.py`.
"""

import asyncio
import contextvars
import threading
import time
from unittest.mock import patch

import pytest

import channels.telegram_confirmation_adapter as base_mod
from channels import discord_bot
from channels.discord_confirmation_adapter import DiscordConfirmationAdapter
from channels.telegram_confirmation_adapter import ChatConfirmationAdapter


class _CanalFalso:
    def __init__(self, canal_id):
        self.id = canal_id
        self.enviados = []

    async def send(self, text):
        self.enviados.append(text)


class _BotFalso:
    def __init__(self):
        self.canales = {}
        self.pedidos_a_la_api = []

    def get_channel(self, canal_id):
        return self.canales.get(canal_id)

    async def fetch_channel(self, canal_id):
        self.pedidos_a_la_api.append(canal_id)
        canal = _CanalFalso(canal_id)
        self.canales[canal_id] = canal
        return canal


def _adapter_con_loop():
    loop = asyncio.new_event_loop()
    hilo = threading.Thread(target=loop.run_forever, daemon=True)
    hilo.start()
    bot = _BotFalso()
    adapter = DiscordConfirmationAdapter()
    adapter.bind(bot, loop)
    return adapter, bot, loop, hilo


def _parar(loop, hilo):
    loop.call_soon_threadsafe(loop.stop)
    hilo.join(timeout=5)
    loop.close()


@pytest.fixture(autouse=True)
def _contexto_limpio():
    base_mod._request_ctx.set(None)
    yield
    base_mod._request_ctx.set(None)


# ── el adaptador ────────────────────────────────────────────────────

def test_es_el_mismo_adaptador_que_telegram_con_otro_transporte():
    assert issubclass(DiscordConfirmationAdapter, ChatConfirmationAdapter)
    # Solo el envío es propio: la reserva, la espera y el «sí» son los de REQ-018.
    propios = {n for n in vars(DiscordConfirmationAdapter) if not n.startswith("__")}
    assert propios == {"_send_message", "_enviar"}


def test_envia_la_pregunta_por_el_canal_y_lee_el_si():
    adapter, bot, loop, hilo = _adapter_con_loop()
    try:
        canal = _CanalFalso(777)
        bot.canales[777] = canal
        assert adapter.reserve_pending("u1")
        adapter.set_request_context("u1", 777)

        resultado = {}

        def worker():
            resultado["ok"] = adapter.confirm("mcp__notion__search", "¿Quiere que use search?")

        # Como `asyncio.to_thread`: el hilo recibe una copia del contexto (el ContextVar
        # del request). Un `Thread` crudo no lo hereda y `confirm()` denegaría fail-closed.
        t = threading.Thread(target=contextvars.copy_context().run, args=(worker,))
        t.start()
        for _ in range(100):
            if canal.enviados:
                break
            time.sleep(0.02)
        assert canal.enviados == ["¿Quiere que use search?"]

        assert adapter.resolve("u1", "sí") is True
        t.join(timeout=5)
        assert resultado["ok"] is True
        assert not adapter.has_pending("u1")
    finally:
        _parar(loop, hilo)


def test_un_canal_que_no_esta_en_cache_se_pide_a_la_api():
    adapter, bot, loop, hilo = _adapter_con_loop()
    try:
        adapter._send_message(555, "hola")
        assert bot.pedidos_a_la_api == [555]
        assert bot.canales[555].enviados == ["hola"]
    finally:
        _parar(loop, hilo)


def test_un_envio_que_falla_no_se_convierte_en_si(monkeypatch):
    adapter, bot, loop, hilo = _adapter_con_loop()
    try:
        async def explota(canal_id, texto):
            raise RuntimeError("sin permisos en el canal")

        monkeypatch.setattr(adapter, "_enviar", explota)
        monkeypatch.setattr(base_mod, "CONFIRM_TIMEOUT_SECONDS", 0.2)
        assert adapter.reserve_pending("u1")
        adapter.set_request_context("u1", 1)

        assert adapter.confirm("accion", "¿?") is False
        assert not adapter.has_pending("u1")
    finally:
        _parar(loop, hilo)


def test_sin_bind_no_lanza_y_expira_fail_closed(monkeypatch):
    adapter = DiscordConfirmationAdapter()
    monkeypatch.setattr(base_mod, "CONFIRM_TIMEOUT_SECONDS", 0.1)
    assert adapter.reserve_pending("u1")
    adapter.set_request_context("u1", 1)

    assert adapter.confirm("accion", "¿?") is False


# ── integración en el bot ───────────────────────────────────────────

@pytest.fixture
def adaptador_del_bot(monkeypatch):
    """El adaptador global del bot, limpio, con un `_send_message` que no manda nada."""
    from channels import discord_confirmation_adapter as mod

    adapter = DiscordConfirmationAdapter()
    monkeypatch.setattr(adapter, "_send_message", lambda chat_id, text: None)
    monkeypatch.setattr(mod, "discord_confirmation_adapter", adapter)
    return adapter


def test_una_respuesta_sin_pendiente_no_se_consume(adaptador_del_bot):
    assert discord_bot._responder_confirmacion("u1", "sí") is False
    assert discord_bot._responder_confirmacion("u1", "") is False


def test_la_respuesta_se_consume_aunque_no_mencione_al_bot(adaptador_del_bot):
    adaptador_del_bot.reserve_pending("u1")            # comprometida: ya se preguntó
    assert discord_bot._responder_confirmacion("u1", "si") is True
    assert not adaptador_del_bot.has_pending("u1")


def test_el_turno_corre_en_otro_hilo_con_reserva_y_contexto(adaptador_del_bot):
    visto = {}

    def proceso_falso(user_id, user_name, text, image_path=None):
        visto["hilo"] = threading.current_thread().name
        visto["reservado"] = adaptador_del_bot.has_pending("autor-1")
        visto["contexto"] = base_mod._request_ctx.get()
        visto["args"] = (user_id, user_name, text, image_path)
        return "respuesta"

    with patch.object(discord_bot, "_process_message", side_effect=proceso_falso):
        resultado = asyncio.run(discord_bot._procesar_con_confirmacion(
            "autor-1", 4242, "discord:autor-1", "Johan", "hola", image_path=None,
        ))

    assert resultado == "respuesta"
    assert visto["hilo"] != threading.main_thread().name       # no bloquea el event loop
    assert visto["reservado"] is True
    assert visto["contexto"] == ("autor-1", 4242)
    assert visto["args"] == ("discord:autor-1", "Johan", "hola", None)
    assert not adaptador_del_bot.has_pending("autor-1")         # liberada al terminar


def test_la_reserva_se_libera_aunque_el_turno_explote(adaptador_del_bot):
    with patch.object(discord_bot, "_process_message", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            asyncio.run(discord_bot._procesar_con_confirmacion("autor-1", 1, "d:1", "J", "x"))

    assert not adaptador_del_bot.has_pending("autor-1")


def test_con_otra_confirmacion_en_curso_se_procesa_sin_contexto(adaptador_del_bot):
    """Una acción amarilla que aparezca se deniega en vez de colarse en la espera ajena."""
    adaptador_del_bot.reserve_pending("autor-1")            # la que ya está esperando
    visto = {}

    def proceso_falso(*args, **kwargs):
        visto["contexto"] = base_mod._request_ctx.get()
        return "ok"

    with patch.object(discord_bot, "_process_message", side_effect=proceso_falso):
        asyncio.run(discord_bot._procesar_con_confirmacion("autor-1", 1, "d:1", "J", "x"))

    assert visto["contexto"] is None
    assert adaptador_del_bot.has_pending("autor-1")         # la original sigue viva


# ── canales MCP ─────────────────────────────────────────────────────

def test_discord_es_habilitable_para_mcp_y_voz_no():
    from core.mcp_config import CANALES_HABILITABLES

    assert "discord" in CANALES_HABILITABLES
    assert "voice" not in CANALES_HABILITABLES
