"""
tests/test_telegram_bot.py

Suite de tests para channels/telegram_bot.py (REQ-018) — primera suite de tests que existe
para este módulo (`baseline-018.md` confirmó cero cobertura previa). Cubre CA-01, CA-05
(casos borde), CA-08 (Hallazgo A), CA-09 (Hallazgo E), CA-10, CA-13, CA-14 de SPEC-018.md.

Convenciones (.claude/rules/testing.md): `update`/`context` mockeados con MagicMock/
AsyncMock, sin red real, corutinas ejecutadas vía asyncio.run(). AUDIT_DB redirigida a
tmp_path cuando se inspecciona auditoría.
"""

import asyncio
import inspect
import sqlite3
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

import channels.telegram_bot as telegram_bot
from channels.telegram_confirmation_adapter import telegram_confirmation_adapter
from core.confirmation import get_confirmation_adapter, register_confirmation_adapter
from core.security_manager import ChannelType, security_manager

confirmation_module = sys.modules["core.confirmation"]

sm_module = sys.modules["core.security_manager"]


@pytest.fixture(autouse=True)
def _tratamiento_fijo(monkeypatch):
    """Fija el tratamiento en "Señor" para toda la suite.

    Desde que el usuario puede elegirlo en Configuración, el texto de las respuestas sale
    de `config.json`; sin esto los asserts literales dependerían del `config.json` real de
    quien corre los tests (`.claude/rules/testing.md`: un test no lee configuración real).
    """
    import core.address as address
    monkeypatch.setattr(address, "get_user_title", lambda: "Señor")


def _make_update(user_id=111, chat_id=222, text=None, args=None):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.first_name = "Johan"
    update.effective_chat.id = chat_id
    update.message.text = text
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.args = args or []
    return update, context


def _last_reply(update) -> str:
    return update.message.reply_text.call_args_list[-1][0][0]


@pytest.fixture(autouse=True)
def _limpiar_pending_del_adapter():
    """`telegram_confirmation_adapter` es un singleton de módulo — se limpia `_pending`
    antes/después de cada test para que ningún test deje un user_id "reservado" que
    contamine al siguiente."""
    telegram_confirmation_adapter._pending.clear()
    yield
    telegram_confirmation_adapter._pending.clear()


@pytest.fixture
def isolated_audit_db(monkeypatch, tmp_path):
    """Redirige AUDIT_DB a un archivo temporal (mismo patrón que
    tests/test_security_manager.py) para poder inspeccionar auditoría sin tocar el
    audit.db real del proyecto."""
    db_path = str(tmp_path / "audit_test_telegram.db")
    monkeypatch.setattr(sm_module, "AUDIT_DB", db_path)
    security_manager._init_audit()
    return db_path


def _read_audit_rows(db_path: str) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT action, channel, user_id, result FROM audit_log ORDER BY id ASC"
        ).fetchall()


# --- CA-01 — /eliminar gateado vía security_manager.require_confirmation() --------------


def test_ca01_cmd_eliminar_confirmado_borra_tarea(monkeypatch):
    update, context = _make_update(user_id=111, args=["5"])
    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **kw: True)

    import tasks.task_manager as tm_module
    deleted = {}

    def fake_delete(task_id, user_id):
        deleted["args"] = (task_id, user_id)
        return True

    monkeypatch.setattr(tm_module.task_manager, "delete_task", fake_delete)

    asyncio.run(telegram_bot.cmd_eliminar(update, context))

    assert deleted["args"] == (5, "111")
    assert "eliminada" in _last_reply(update).lower()


def test_ca01_cmd_eliminar_cancelado_no_borra_tarea(monkeypatch):
    update, context = _make_update(user_id=112, args=["5"])
    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **kw: False)

    import tasks.task_manager as tm_module
    called = {"flag": False}

    def fake_delete(*_a, **_kw):
        called["flag"] = True
        return True

    monkeypatch.setattr(tm_module.task_manager, "delete_task", fake_delete)

    asyncio.run(telegram_bot.cmd_eliminar(update, context))

    assert called["flag"] is False
    assert "cancelada" in _last_reply(update).lower()


def test_cmd_eliminar_no_encontrada_responde_mensaje_especifico(monkeypatch):
    update, context = _make_update(user_id=112, args=["999"])
    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **kw: True)

    import tasks.task_manager as tm_module
    monkeypatch.setattr(tm_module.task_manager, "delete_task", lambda *a, **kw: False)

    asyncio.run(telegram_bot.cmd_eliminar(update, context))

    assert _last_reply(update) == "No encontré la tarea #999 en su lista, Señor."


def test_cmd_eliminar_sin_args_pide_id():
    update, context = _make_update(args=[])
    asyncio.run(telegram_bot.cmd_eliminar(update, context))
    assert "Indique el número" in _last_reply(update)


def test_cmd_eliminar_id_no_numerico():
    update, context = _make_update(args=["abc"])
    asyncio.run(telegram_bot.cmd_eliminar(update, context))
    assert "número" in _last_reply(update).lower()


# --- CA-09/Hallazgo E — reserve_pending() bloquea una segunda confirmación en -----------
# --- cmd_eliminar() ANTES de disparar el hilo worker -------------------------------------


def test_ca09_segunda_confirmacion_pendiente_no_llama_require_confirmation(monkeypatch):
    update, context = _make_update(user_id=113, args=["9"])
    telegram_confirmation_adapter.reserve_pending("113")  # simula confirmación ya en curso

    called = {"flag": False}

    def fake_require(*_a, **_kw):
        called["flag"] = True
        return True

    monkeypatch.setattr(security_manager, "require_confirmation", fake_require)

    asyncio.run(telegram_bot.cmd_eliminar(update, context))

    assert called["flag"] is False
    assert "confirmación pendiente" in _last_reply(update).lower()


def test_cmd_eliminar_reserva_pending_para_el_usuario_antes_de_esperar(monkeypatch):
    """cmd_eliminar() debe reservar en _pending ANTES de que require_confirmation()
    resuelva — verificado con un require_confirmation que, mientras "espera", chequea que
    la reserva ya existe."""
    update, context = _make_update(user_id=114, args=["1"])
    visto_reservado = {}

    def fake_require(*_a, **_kw):
        visto_reservado["valor"] = telegram_confirmation_adapter.has_pending("114")
        return True

    monkeypatch.setattr(security_manager, "require_confirmation", fake_require)
    import tasks.task_manager as tm_module
    monkeypatch.setattr(tm_module.task_manager, "delete_task", lambda *a, **kw: True)

    asyncio.run(telegram_bot.cmd_eliminar(update, context))

    assert visto_reservado["valor"] is True


# --- CA-05 — intercepción de la próxima respuesta, casos borde de SPEC-018.md ------------


def test_ca05_intercept_confirmacion_pendiente_consume_comando_y_corta_propagacion():
    from telegram.ext import ApplicationHandlerStop

    telegram_confirmation_adapter.reserve_pending("115")
    update, context = _make_update(user_id=115, text="/tareas")

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot._intercept_confirmacion_pendiente(update, context))

    # "/tareas" no es un token afirmativo (CA-06) — cuenta como cancelación, pero el
    # mensaje SÍ se consumió como respuesta (ya no queda pendiente).
    assert telegram_confirmation_adapter.has_pending("115") is False


def test_intercept_confirmacion_pendiente_sin_pendiente_no_lanza():
    update, context = _make_update(user_id=116, text="hola")
    # No debe lanzar ApplicationHandlerStop — no había ninguna confirmación pendiente
    # para 116, el mensaje debe poder seguir su camino normal por group=0.
    asyncio.run(telegram_bot._intercept_confirmacion_pendiente(update, context))


def test_intercept_confirmacion_pendiente_ignora_mensajes_sin_texto():
    telegram_confirmation_adapter.reserve_pending("117")
    update, context = _make_update(user_id=117, text=None)
    # No debe lanzar ni consumir la confirmación pendiente (no es un mensaje de texto).
    asyncio.run(telegram_bot._intercept_confirmacion_pendiente(update, context))
    assert telegram_confirmation_adapter.has_pending("117") is True


def test_voz_mientras_hay_confirmacion_pendiente_no_la_afecta(monkeypatch):
    """Casos borde de SPEC-018.md: un mensaje de voz mientras hay una confirmación
    pendiente no cuenta como respuesta — handle_voice() no consulta ni afecta
    telegram_confirmation_adapter en absoluto."""
    telegram_confirmation_adapter.reserve_pending("118")

    update, context = _make_update(user_id=118)
    update.message.voice.file_id = "fake-file-id"
    context.bot.get_file = AsyncMock(return_value=MagicMock(download_to_drive=AsyncMock()))
    context.bot.send_chat_action = AsyncMock()

    monkeypatch.setattr(telegram_bot, "_transcribe_audio", lambda _path: "")

    asyncio.run(telegram_bot.handle_voice(update, context))

    assert telegram_confirmation_adapter.has_pending("118") is True


# --- CA-10 — /tareas, /nueva, /completar auditados, comportamiento observable idéntico ---


def test_ca10_cmd_tareas_usa_execute_tool(monkeypatch):
    update, context = _make_update(user_id=119)
    llamada = {}

    def fake_execute_tool(name, params, channel, user_id="default"):
        llamada["args"] = (name, params, channel, user_id)
        return "resumen de tareas"

    import agents.tool_registry as tool_registry_module
    monkeypatch.setattr(tool_registry_module, "execute_tool", fake_execute_tool)

    asyncio.run(telegram_bot.cmd_tareas(update, context))

    assert llamada["args"] == ("task_list", {"user_id": "119"}, ChannelType.TELEGRAM, "119")
    assert _last_reply(update) == "resumen de tareas"


def test_ca10_cmd_nueva_camino_feliz_ausita_y_preserva_mensaje(monkeypatch):
    update, context = _make_update(user_id=120, args=["recuérdame", "mañana"])

    import tasks.task_manager as tm_module
    monkeypatch.setattr(
        tm_module.task_manager, "create_from_natural",
        lambda text, user_id, channel: {"title": text}
    )
    monkeypatch.setattr(tm_module.task_manager, "format_task_created", lambda result: "tarea creada ok")

    gate_calls = []

    def fake_require(name, channel, details="", user_id="default"):
        gate_calls.append((name, channel))
        return True

    monkeypatch.setattr(security_manager, "require_confirmation", fake_require)

    asyncio.run(telegram_bot.cmd_nueva(update, context))

    assert gate_calls == [("task_create", ChannelType.TELEGRAM)]
    assert _last_reply(update) == "tarea creada ok"


def test_ca10_cmd_nueva_fallback_tarea_simple_preservado(monkeypatch):
    """Regresión explícita del fallback de 'tarea simple' (arquitectura-018.md §3) —
    agents/tool_registry.py::_task_create_invoke() no lo replica, por eso /nueva NO se
    conecta a execute_tool()."""
    update, context = _make_update(user_id=121, args=["texto", "no", "parseable"])

    import tasks.task_manager as tm_module
    monkeypatch.setattr(tm_module.task_manager, "create_from_natural", lambda *a, **kw: None)
    created = {}

    def fake_create_task(**kwargs):
        created.update(kwargs)
        return 42

    monkeypatch.setattr(tm_module.task_manager, "create_task", fake_create_task)
    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **kw: True)

    asyncio.run(telegram_bot.cmd_nueva(update, context))

    assert created["user_id"] == "121"
    reply = _last_reply(update)
    assert "Tarea registrada" in reply
    assert "1 hora" in reply


def test_cmd_nueva_sin_texto_pide_descripcion():
    update, context = _make_update(args=[])
    asyncio.run(telegram_bot.cmd_nueva(update, context))
    assert "¿Qué tarea desea agregar" in _last_reply(update)


def test_ca10_cmd_completar_exito_audita_y_preserva_mensaje(monkeypatch):
    update, context = _make_update(user_id=122, args=["7"])

    import tasks.task_manager as tm_module
    monkeypatch.setattr(tm_module.task_manager, "complete_task", lambda task_id, user_id: True)

    gate_calls = []

    def fake_require(name, channel, details="", user_id="default"):
        gate_calls.append((name, channel))
        return True

    monkeypatch.setattr(security_manager, "require_confirmation", fake_require)

    asyncio.run(telegram_bot.cmd_completar(update, context))

    assert gate_calls == [("task_complete", ChannelType.TELEGRAM)]
    assert "completada" in _last_reply(update).lower()


def test_ca10_cmd_completar_no_encontrada_mensaje_especifico_preservado(monkeypatch):
    """Regresión del mensaje de error específico de /completar — distinto del que usa el
    tool task_complete ('No encontré ninguna tarea pendiente con el ID #{id}, Señor.') —
    ver arquitectura-018.md §3."""
    update, context = _make_update(user_id=123, args=["999"])

    import tasks.task_manager as tm_module
    monkeypatch.setattr(tm_module.task_manager, "complete_task", lambda task_id, user_id: False)
    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **kw: True)

    asyncio.run(telegram_bot.cmd_completar(update, context))

    assert _last_reply(update) == "No encontré la tarea #999 en sus pendientes, Señor."


def test_cmd_completar_sin_args_pide_id():
    update, context = _make_update(args=[])
    asyncio.run(telegram_bot.cmd_completar(update, context))
    assert "Indique el número" in _last_reply(update)


def test_cmd_completar_id_no_numerico():
    update, context = _make_update(args=["xx"])
    asyncio.run(telegram_bot.cmd_completar(update, context))
    assert "número" in _last_reply(update).lower()


# --- CA-13 — Discord sin cambios ----------------------------------------------------------


def test_ca13_discord_bot_no_tocado_por_este_req():
    """Marcador explícito de 'no tocado' — este REQ no modifica channels/discord_bot.py."""
    import channels.discord_bot  # noqa: F401


# --- CA-14 — auditoría sin caminos paralelos, mismo _log_audit() -------------------------


def test_ca14_eliminar_confirmado_queda_en_audit_db(isolated_audit_db, monkeypatch):
    update, context = _make_update(user_id=124, args=["3"])

    import tasks.task_manager as tm_module
    monkeypatch.setattr(tm_module.task_manager, "delete_task", lambda *a, **kw: True)

    original_adapter = get_confirmation_adapter(ChannelType.TELEGRAM)
    register_confirmation_adapter(ChannelType.TELEGRAM, lambda action, msg: True)
    try:
        asyncio.run(telegram_bot.cmd_eliminar(update, context))
    finally:
        # register_confirmation_adapter() no tiene "unregister" — si no había adaptador
        # TELEGRAM antes de este test (caso esperado: ninguno de producción se registra en
        # el proceso de pytest), hay que sacar la entrada del dict directamente, no solo
        # "restaurar None" (que dejaría el adaptador de este test filtrado a los tests
        # siguientes, p. ej. tests/test_tool_registry.py::
        # test_delete_task_yellow_sigue_bloqueado_en_lote, que asume sin adaptador).
        if original_adapter is not None:
            register_confirmation_adapter(ChannelType.TELEGRAM, original_adapter)
        else:
            confirmation_module._ADAPTERS.pop(ChannelType.TELEGRAM, None)

    rows = _read_audit_rows(isolated_audit_db)
    assert ("delete_task", "telegram", "124", "confirmada") in rows


def test_ca14_nueva_y_completar_quedan_permitida_en_audit_db(isolated_audit_db, monkeypatch):
    update, context = _make_update(user_id=125, args=["hola", "mundo"])

    import tasks.task_manager as tm_module
    monkeypatch.setattr(tm_module.task_manager, "create_from_natural", lambda *a, **kw: {"title": "x"})
    monkeypatch.setattr(tm_module.task_manager, "format_task_created", lambda r: "ok")

    asyncio.run(telegram_bot.cmd_nueva(update, context))

    rows = _read_audit_rows(isolated_audit_db)
    assert ("task_create", "telegram", "125", "permitida") in rows


# --- CA-08 / Hallazgo A — concurrent_updates(True) real, no solo el adaptador aislado -----


def test_hallazgo_a_application_con_concurrent_updates_habilitado():
    """REQ-018/Hallazgo A (security-audit-018.md) — construye una Application real con el
    mismo builder que run_telegram_bot() (no el adaptador aislado, que era exactamente el
    gap por el que no se detectó el hallazgo original) y verifica la configuración
    efectiva. Sin red: .build() no dispara ninguna llamada HTTP."""
    from telegram.ext import Application

    app = (
        Application.builder()
        .token("123456:FAKE-TOKEN-SOLO-PARA-CONSTRUIR-EL-OBJETO-SIN-RED")
        .concurrent_updates(True)
        .build()
    )
    assert app.concurrent_updates > 1


def test_run_telegram_bot_source_incluye_concurrent_updates_true():
    """Guardrail estructural adicional sobre el código real (no una copia): si alguien
    revierte el fix quitando .concurrent_updates(True) de run_telegram_bot(), este test
    falla en CI en vez de convertirse en un DoS silencioso en producción."""
    source = inspect.getsource(telegram_bot.run_telegram_bot)
    assert ".concurrent_updates(True)" in source
    assert ".post_init(_post_init_telegram)" in source


# ══════════════════════════════════════════════════════════════════════
#  Control de acceso por identidad — `_intercept_no_autorizado`
#
#  Es el primer handler de la cadena (group=-2). Si deja pasar a alguien que no debía,
#  ese alguien queda con la autoridad de herramientas del agente: las acciones verdes se
#  ejecutan sin confirmar, y "tomar captura de pantalla" es una de ellas.
# ══════════════════════════════════════════════════════════════════════

def _update_de(user_id, username="alguien"):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.effective_chat.id = 555
    return update


def _context_con_bot():
    context = MagicMock()
    context.bot.send_message = AsyncMock()
    return context


def test_acceso_un_autorizado_pasa_sin_ser_interrumpido(monkeypatch):
    monkeypatch.setattr(
        "core.authorized_users.is_authorized", lambda channel, uid: True
    )
    context = _context_con_bot()

    # No lanzar ApplicationHandlerStop es lo que deja continuar la cadena de handlers.
    asyncio.run(telegram_bot._intercept_no_autorizado(_update_de("1578909994"), context))

    context.bot.send_message.assert_not_called()


def test_acceso_un_desconocido_corta_la_cadena(monkeypatch):
    from telegram.ext import ApplicationHandlerStop

    monkeypatch.setattr(
        "core.authorized_users.is_authorized", lambda channel, uid: False
    )
    context = _context_con_bot()

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot._intercept_no_autorizado(_update_de("999999"), context))


def test_acceso_al_desconocido_se_le_responde_algo_neutro(monkeypatch):
    from telegram.ext import ApplicationHandlerStop

    from core.authorized_users import UNAUTHORIZED_MESSAGE

    monkeypatch.setattr(
        "core.authorized_users.is_authorized", lambda channel, uid: False
    )
    context = _context_con_bot()

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot._intercept_no_autorizado(_update_de("999999"), context))

    context.bot.send_message.assert_awaited_once()
    enviado = context.bot.send_message.await_args.kwargs["text"]
    assert enviado == UNAUTHORIZED_MESSAGE
    # El mensaje no debe delatar de quién es el bot ni qué sabe hacer.
    assert "O.R.I.O.N" not in enviado and "Johan" not in enviado


def test_acceso_un_update_sin_remitente_se_deniega(monkeypatch):
    """Fail-closed: sin identidad no hay forma de comprobar quién escribe."""
    from telegram.ext import ApplicationHandlerStop

    monkeypatch.setattr(
        "core.authorized_users.is_authorized",
        lambda channel, uid: uid not in ("", "None"),
    )
    update = MagicMock()
    update.effective_user = None
    update.effective_chat.id = 555

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot._intercept_no_autorizado(update, _context_con_bot()))


def test_acceso_si_falla_el_aviso_igual_se_corta(monkeypatch):
    """Que no se pueda avisar al remitente no puede convertirse en dejarlo pasar."""
    from telegram.ext import ApplicationHandlerStop

    monkeypatch.setattr(
        "core.authorized_users.is_authorized", lambda channel, uid: False
    )
    context = MagicMock()
    context.bot.send_message = AsyncMock(side_effect=RuntimeError("sin red"))

    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(telegram_bot._intercept_no_autorizado(_update_de("999999"), context))


def test_acceso_el_canal_consultado_es_siempre_telegram(monkeypatch):
    """Nunca se deduce del texto ni del update: es el canal real del handler."""
    vistos = []

    def _spy(channel, uid):
        vistos.append(channel)
        return True

    monkeypatch.setattr("core.authorized_users.is_authorized", _spy)

    asyncio.run(telegram_bot._intercept_no_autorizado(_update_de("111"), _context_con_bot()))

    assert vistos == ["telegram"]


# --- REQ-021 — el agente con herramientas puede confirmar por el chat --------------------
#
# Bug real: pedirle a O.R.I.O.N. por Telegram que escribiera en otra aplicación devolvía
# "denegado por security_manager". `pc_type` estaba habilitada para Telegram por excepción
# de canal, pero el adaptador de confirmación solo lo cableaba `cmd_eliminar()`: nadie
# decía a qué chat preguntar, así que `confirm()` fallaba cerrado por falta de contexto.
# El agente nunca llegó a preguntar nada; la acción moría antes.


def _mensaje_falso():
    from channels.gateway import GlassMessage, MessageType
    return GlassMessage(
        user_id="owner", user_name="Johan", text="escribe hola en el bloc",
        channel="telegram", msg_type=MessageType.TEXT,
    )


def test_req021_procesar_deja_el_contexto_para_que_el_agente_pueda_preguntar(monkeypatch):
    """Es la línea exacta que faltaba: sin contexto, toda acción amarilla se denegaba."""
    import channels.telegram_confirmation_adapter as adapter_mod

    update, _ = _make_update(user_id=300, chat_id=777)
    visto = {}

    def fake_process(_msg):
        visto["ctx"] = adapter_mod._request_ctx.get()
        visto["reservado"] = telegram_confirmation_adapter.has_pending("300")
        return MagicMock(text="ok")

    monkeypatch.setattr("channels.gateway.GlassGateway.process", staticmethod(fake_process))

    asyncio.run(telegram_bot._procesar(update, _mensaje_falso()))

    assert visto["ctx"] == ("300", 777)
    assert visto["reservado"] is True


def test_req021_procesar_no_corre_en_el_hilo_del_event_loop(monkeypatch):
    """Si corriera ahí, esperar la confirmación dejaría al bot sordo y el "sí" del usuario
    no podría llegar nunca: un bloqueo mutuo hasta el timeout."""
    import threading

    update, _ = _make_update(user_id=301)
    visto = {}

    async def _correr():
        visto["loop"] = threading.current_thread().ident
        return await telegram_bot._procesar(update, _mensaje_falso())

    def fake_process(_msg):
        visto["worker"] = threading.current_thread().ident
        return MagicMock(text="ok")

    monkeypatch.setattr("channels.gateway.GlassGateway.process", staticmethod(fake_process))

    asyncio.run(_correr())

    assert visto["worker"] != visto["loop"]


def test_req021_una_conversacion_normal_no_deja_reserva_colgando(monkeypatch):
    """La mayoría de los mensajes no confirman nada; si la reserva no se soltara, la
    siguiente confirmación de verdad quedaría bloqueada."""
    update, _ = _make_update(user_id=302)
    monkeypatch.setattr(
        "channels.gateway.GlassGateway.process",
        staticmethod(lambda _msg: MagicMock(text="son las tres")),
    )

    asyncio.run(telegram_bot._procesar(update, _mensaje_falso()))

    assert telegram_confirmation_adapter.has_pending("302") is False


def test_req021_si_process_revienta_tampoco_queda_reserva(monkeypatch):
    update, _ = _make_update(user_id=303)

    def _explota(_msg):
        raise RuntimeError("sin conexión")

    monkeypatch.setattr("channels.gateway.GlassGateway.process", staticmethod(_explota))

    with pytest.raises(RuntimeError):
        asyncio.run(telegram_bot._procesar(update, _mensaje_falso()))

    assert telegram_confirmation_adapter.has_pending("303") is False


def test_req021_pc_type_desde_telegram_llega_a_preguntar(monkeypatch):
    """El caso completo, de punta a punta: la acción amarilla ya no muere en el gate, sino
    que llega a preguntar por el chat."""
    update, _ = _make_update(user_id=304, chat_id=888)
    preguntas = []

    def fake_confirm(action_name, mensaje):
        preguntas.append((action_name, mensaje))
        return True

    monkeypatch.setitem(
        confirmation_module._ADAPTERS, ChannelType.TELEGRAM, fake_confirm
    )

    def fake_process(_msg):
        permitido = security_manager.require_confirmation(
            "pc_type", ChannelType.TELEGRAM, details="tool:pc_type", user_id="304",
        )
        return MagicMock(text="escrito" if permitido else "denegado")

    monkeypatch.setattr("channels.gateway.GlassGateway.process", staticmethod(fake_process))

    respuesta = asyncio.run(telegram_bot._procesar(update, _mensaje_falso()))

    assert preguntas, "pc_type debía preguntar por el chat, no morir en el gate"
    assert preguntas[0][0] == "pc_type"
    assert respuesta.text == "escrito"


def test_req021_un_segundo_mensaje_mientras_piensa_no_se_pierde(monkeypatch):
    """Con la reserva tomada pero sin preguntar todavía, lo que el usuario escriba es
    conversación, no una respuesta: consumirlo lo haría desaparecer en silencio."""
    update, _ = _make_update(user_id=305)
    visto = {}

    def fake_process(_msg):
        # El agente sigue pensando; el usuario escribe otra cosa.
        visto["consumido"] = telegram_confirmation_adapter.resolve("305", "y también esto")
        return MagicMock(text="ok")

    monkeypatch.setattr("channels.gateway.GlassGateway.process", staticmethod(fake_process))

    asyncio.run(telegram_bot._procesar(update, _mensaje_falso()))

    assert visto["consumido"] is False
