"""
tests/test_cancelacion_remota.py
REQ-047 — `/detener` en Telegram y Discord: cada usuario frena SU turno, y el presupuesto
remoto sube al del escritorio porque ya hay forma de parar.

Lo que protege esta suite:
- Los turnos remotos se identifican por `canal:usuario`; un stop solo afecta al turno en
  curso de esa clave, nunca al de otro usuario, al del escritorio ni al siguiente.
- `claude_brain` frena en el próximo punto seguro (antes de otra llamada al modelo o de
  otra herramienta) y responde «Detenido» sin dejar el mensaje en el historial.
- Presupuestos: Telegram/Discord = 8 (`TECHO_CANAL_REMOTO_CON_STOP`); voz/API/correo = 5.
- Los comandos de los bots resuelven la misma clave que `ask_claude()`.

Sin red: `generate_response` y `execute_tool` se reemplazan.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai import claude_brain
from ai.llm_provider import LLMToolResponse, ToolCallRequest
from core import cancelacion, reasoning_loop
from core.security_manager import ChannelType

CATALOGO = [{"name": "web_search", "description": "busca", "parameters_schema": {}}]


@pytest.fixture(autouse=True)
def _sin_turnos_remotos():
    cancelacion._remotos_en_curso.clear()
    cancelacion._remotos_cancelados.clear()
    yield
    cancelacion._remotos_en_curso.clear()
    cancelacion._remotos_cancelados.clear()


# ── el registro de turnos remotos ───────────────────────────────────

def test_la_clave_es_canal_y_usuario_y_acepta_enum_o_texto():
    assert cancelacion.clave_remota("telegram", "u1") == "telegram:u1"
    assert cancelacion.clave_remota(ChannelType.DISCORD, " u2 ") == "discord:u2"


def test_cancelar_sin_turno_en_curso_devuelve_false():
    assert cancelacion.cancelar_remoto("telegram:u1") is False


def test_un_stop_frena_solo_el_turno_de_esa_clave():
    t1 = cancelacion.abrir_turno_remoto("telegram:u1")
    t2 = cancelacion.abrir_turno_remoto("telegram:u2")

    assert cancelacion.cancelar_remoto("telegram:u1") is True

    assert cancelacion.esta_cancelado_remoto(t1) is True
    assert cancelacion.esta_cancelado_remoto(t2) is False
    with pytest.raises(cancelacion.TurnoCancelado):
        cancelacion.abortar_si_cancelado_remoto(t1, "prueba")
    cancelacion.abortar_si_cancelado_remoto(t2)          # no lanza


def test_un_stop_tardio_no_se_lleva_puesto_al_turno_siguiente():
    t1 = cancelacion.abrir_turno_remoto("telegram:u1")
    cancelacion.cerrar_turno_remoto("telegram:u1", t1)
    assert cancelacion.cancelar_remoto("telegram:u1") is False

    t2 = cancelacion.abrir_turno_remoto("telegram:u1")
    assert cancelacion.esta_cancelado_remoto(t1) is False
    assert cancelacion.esta_cancelado_remoto(t2) is False


def test_los_turnos_remotos_no_tocan_el_del_escritorio():
    escritorio = cancelacion.nuevo_turno()
    try:
        remoto = cancelacion.abrir_turno_remoto("discord:u1")
        cancelacion.cancelar_remoto("discord:u1")

        assert cancelacion.esta_cancelado() is False          # el del escritorio sigue
        cancelacion.abortar_si_cancelado()                    # no lanza
        assert cancelacion.esta_cancelado_remoto(remoto) is True
    finally:
        cancelacion.cerrar_turno(escritorio)


# ── claude_brain frena en el punto seguro ───────────────────────────

def _ask(respuestas, ejecutar):
    llamadas = []

    def fake_generate(messages, system_prompt, image_path=None, tools=None, tarea="general",
                      aviso=None):
        llamadas.append(tools)
        return respuestas[min(len(llamadas) - 1, len(respuestas) - 1)]

    with patch("ai.llm_provider.generate_response", side_effect=fake_generate), \
         patch("core.reasoning_loop.generate_response", side_effect=fake_generate), \
         patch("agents.tool_registry.catalogo_para_modelo", return_value=CATALOGO), \
         patch("core.reasoning_loop.execute_tool", side_effect=ejecutar), \
         patch("ai.claude_brain.compactar", create=True, side_effect=lambda h: h):
        texto = claude_brain.ask_claude("buscá algo", user_id="tg-1", channel="telegram")
    return texto, llamadas


def test_detener_entre_herramientas_responde_detenido_y_no_deja_rastro():
    pide_dos = LLMToolResponse(text=None, tool_calls=[
        ToolCallRequest(id="a", name="web_search", arguments={}),
        ToolCallRequest(id="b", name="web_search", arguments={}),
    ])
    ejecuciones = []

    def ejecutar(nombre, params, canal, user_id):
        ejecuciones.append(nombre)
        # El usuario manda /detener mientras corre la primera herramienta.
        cancelacion.cancelar_remoto(cancelacion.clave_remota("telegram", "tg-1"))
        return "ok"

    claude_brain.clear_conversation("tg-1")
    texto, llamadas = _ask([pide_dos, LLMToolResponse(text="no debería", tool_calls=[])], ejecutar)

    assert texto.startswith("Detenido")
    assert ejecuciones == ["web_search"]                     # la segunda no se ejecuta
    assert len(llamadas) == 1                                # ni hay otra vuelta ni cierre
    assert claude_brain._conversation_histories.get("tg-1", []) == []
    assert cancelacion._remotos_en_curso == {}               # el turno quedó cerrado


def test_sin_detener_el_turno_termina_normal_y_cierra_su_registro():
    claude_brain.clear_conversation("tg-1")
    texto, _ = _ask([LLMToolResponse(text="listo", tool_calls=[])], lambda *a: "ok")

    assert texto == "listo"
    assert cancelacion._remotos_en_curso == {}


# ── presupuestos ────────────────────────────────────────────────────

def test_telegram_y_discord_suben_al_presupuesto_del_escritorio():
    assert reasoning_loop.TECHO_CANAL_REMOTO_CON_STOP == reasoning_loop.MAX_LLM_CALLS == 8
    assert reasoning_loop._presupuesto_de_llamadas(None, ChannelType.TELEGRAM) == 8
    assert reasoning_loop._presupuesto_de_llamadas(None, ChannelType.DISCORD) == 8


@pytest.mark.parametrize("canal", [ChannelType.VOICE, ChannelType.API, ChannelType.EMAIL, ChannelType.UNKNOWN])
def test_los_canales_sin_forma_de_parar_siguen_en_cinco(canal):
    assert reasoning_loop._presupuesto_de_llamadas(None, canal) == reasoning_loop.TECHO_CANAL_NO_ESCRITORIO == 5


# ── los comandos de los bots ────────────────────────────────────────

def test_cmd_detener_de_telegram_frena_la_misma_clave_que_ask_claude():
    from channels import telegram_bot
    from core.user_identity import canonical_user_id

    update = MagicMock()
    update.effective_user.id = 111
    update.message.reply_text = AsyncMock()
    clave = cancelacion.clave_remota("telegram", canonical_user_id("telegram", 111))
    turno = cancelacion.abrir_turno_remoto(clave)

    asyncio.run(telegram_bot.cmd_detener(update, MagicMock()))

    assert "Deteniendo" in update.message.reply_text.call_args_list[-1][0][0]
    assert cancelacion.esta_cancelado_remoto(turno)

    cancelacion.cerrar_turno_remoto(clave, turno)
    asyncio.run(telegram_bot.cmd_detener(update, MagicMock()))
    assert "No hay nada" in update.message.reply_text.call_args_list[-1][0][0]


def test_detener_de_discord_frena_la_misma_clave_que_el_gateway():
    from channels import discord_bot
    from core.user_identity import canonical_user_id

    clave = cancelacion.clave_remota("discord", canonical_user_id("discord", 999))
    turno = cancelacion.abrir_turno_remoto(clave)

    assert "Deteniendo" in discord_bot._detener_turno(999)
    assert cancelacion.esta_cancelado_remoto(turno)
    cancelacion.cerrar_turno_remoto(clave, turno)
    assert "No hay nada" in discord_bot._detener_turno(999)
