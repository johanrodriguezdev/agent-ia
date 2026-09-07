"""
tests/test_webview_bridge.py
REQ-015/CA-07..CA-11, CA-20..CA-25, CA-39, CA-40, CA-42 — `ui/webview/bridge.py::Bridge`.

`pytest-qt` instancia un `Bridge` (QObject headless, sin `QWebEngineView` real) con
`memory`/`execute_action`/`resolve`/`security_manager` mockeados. `run_async()` se
reemplaza por una versión síncrona (`fake_run_async`): ejecuta `fn()` en el mismo hilo y
llama `on_done`/`on_error` de inmediato — sin `QThreadPool` real, determinístico.

Verifica que cada slot llama exactamente a la función esperada con los parámetros
esperados, que `run_chip_action` nunca ejecuta la acción "directo" (siempre vía
`execute_action()`), y que `toggle_wake_word` nunca arranca un `QRunnable` real (evita
tocar `sr.Microphone()`, `.claude/rules/testing.md`).
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import ui.webview.bridge as bridge_module
from ui.webview.bridge import Bridge
from ui.webview.wake_word_worker import WakeWordWorker


@pytest.fixture
def fake_run_async(monkeypatch):
    """`run_async(fn, on_done, on_error, *args, **kwargs)` síncrono, sin `QThreadPool`."""
    calls = []

    def _fake_run_async(fn, on_done=None, on_error=None, *args, **kwargs):
        calls.append({"fn": fn, "args": args, "kwargs": kwargs})
        try:
            result = fn(*args, **kwargs)
        except Exception as e:  # pragma: no cover - camino defensivo
            if on_error:
                on_error(str(e))
            return None
        if on_done:
            on_done(result)
        return result

    monkeypatch.setattr(bridge_module, "run_async", _fake_run_async)
    return calls


@pytest.fixture
def no_real_threadpool(monkeypatch):
    """Evita que `toggle_wake_word(True)` arranque un `QRunnable` real (tocaría
    `sr.Microphone()`) — mismo patrón que `tests/test_wake_word_gui.py` (REQ-009)."""
    started = []
    fake_pool = MagicMock()
    fake_pool.start = lambda worker: started.append(worker)
    monkeypatch.setattr(bridge_module.QThreadPool, "globalInstance", staticmethod(lambda: fake_pool))
    return started


@pytest.fixture
def bridge(qtbot, fake_run_async):
    main_window = MagicMock()
    b = Bridge(main_window)
    return b


# ---------------------------------------------------------------------------
# CA-07: nueva conversación
# ---------------------------------------------------------------------------

def test_new_conversation_limpia_id_y_emite_conversation_cleared(bridge, qtbot):
    bridge._conversation_id = "abc"
    with qtbot.waitSignal(bridge.conversation_cleared, timeout=1000):
        bridge.new_conversation()
    assert bridge._conversation_id is None


# ---------------------------------------------------------------------------
# CA-09: seleccionar conversación existente
# ---------------------------------------------------------------------------

def test_select_conversation_llama_get_conversation_turns_y_emite_turns_loaded(bridge, monkeypatch):
    from ai.memory_manager import memory

    fake_turns = [SimpleNamespace(id=1, role="user", text="hola", timestamp="t1")]
    monkeypatch.setattr(memory, "get_conversation_turns", lambda conversation_id, user_id="default": fake_turns)

    received = []
    bridge.turns_loaded.connect(lambda j: received.append(json.loads(j)))

    bridge.select_conversation("conv-1")

    assert bridge._conversation_id == "conv-1"
    assert received[0][0]["role"] == "user"
    assert received[0][0]["id"] == 1


# ---------------------------------------------------------------------------
# CA-11: paginación "Ver más"
# ---------------------------------------------------------------------------

def test_load_more_conversations_pasa_el_offset_recibido(bridge, monkeypatch):
    from ai.memory_manager import memory

    calls = []
    monkeypatch.setattr(memory, "list_conversations", lambda **kwargs: calls.append(kwargs) or [])

    bridge.load_more_conversations(30)

    assert calls[0]["offset"] == 30


def test_request_initial_state_emite_chips_theme_y_conversaciones(bridge, monkeypatch):
    """REQ-026 addendum 1: `chips_loaded` sigue emitiendo `{"modes": [...], "quick_actions":
    [...]}` (CA-39, portados de REQ-015), pero `quick_actions` se redujo de 3 a 1 entrada —
    "📷 Captura de pantalla" y "🌐 Abrir navegador" se eliminaron del composer
    (SPEC-026-addendum-1.md, "Catálogo final"); su capacidad de agente no se toca, solo el
    atajo de UI, y por eso no forman parte de este payload nunca más."""
    from ai.memory_manager import memory
    import config_manager

    monkeypatch.setattr(memory, "list_conversations", lambda **kwargs: [])
    monkeypatch.setattr(config_manager, "get_ui_theme", lambda: "dark")

    chips_received, theme_received, conv_received = [], [], []
    bridge.chips_loaded.connect(lambda j: chips_received.append(json.loads(j)))
    bridge.theme_changed.connect(theme_received.append)
    bridge.conversation_list_updated.connect(lambda j: conv_received.append(json.loads(j)))

    bridge.request_initial_state()

    payload = chips_received[0]
    assert len(payload["modes"]) == 4
    assert {m["id"] for m in payload["modes"]} == {"codigo", "investigacion", "flujos", "tareas"}
    assert len(payload["quick_actions"]) == 1
    etiquetas = {c["label"] for c in payload["quick_actions"]}
    assert etiquetas == {"Recuérdame algo"}
    # "📷 Captura de pantalla" y "🌐 Abrir navegador" (addendum 1) y "Resumen del día" /
    # "Investigación rápida" (REQ-026 original) ya no aparecen en ningún catálogo.
    assert "📷 Captura de pantalla" not in etiquetas
    assert "🌐 Abrir navegador" not in etiquetas
    assert "Resumen del día" not in etiquetas
    assert "Investigación rápida" not in etiquetas
    # Campo nuevo del addendum 1: el frontend necesita el ícono para renderizar "Recuérdame
    # algo" con el mismo componente que los 4 modos (`#ic-bell`, ver ui-design-026-addendum-1.md §4).
    assert next(iter(payload["quick_actions"]))["icon"] == "bell"
    assert theme_received == ["dark"]
    assert conv_received == [[]]


# ---------------------------------------------------------------------------
# CA-10, §10.2: borrado de conversación pasa por confirmación YELLOW
# ---------------------------------------------------------------------------

def test_request_delete_conversation_pide_confirmacion_y_borra_si_se_confirma(bridge, monkeypatch):
    from ai.memory_manager import memory
    from core.security_manager import security_manager

    confirm_calls = []

    def fake_require_confirmation(action_name, channel, details="", user_id="default"):
        confirm_calls.append((action_name, details))
        return True

    monkeypatch.setattr(security_manager, "require_confirmation", fake_require_confirmation)

    delete_calls = []
    monkeypatch.setattr(
        memory, "delete_conversation",
        lambda conversation_id, user_id="default": delete_calls.append(conversation_id) or True,
    )

    received = []
    bridge.conversation_removed.connect(received.append)

    bridge.request_delete_conversation("conv-xyz")

    assert confirm_calls[0][0] == "delete_conversation"
    assert "conv-xyz" in confirm_calls[0][1]  # §10.2: details incluye el id (clave "name")
    assert delete_calls == ["conv-xyz"]
    assert received == ["conv-xyz"]


def test_request_delete_conversation_no_borra_si_se_cancela(bridge, monkeypatch):
    from ai.memory_manager import memory
    from core.security_manager import security_manager

    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **k: False)
    delete_calls = []
    monkeypatch.setattr(memory, "delete_conversation", lambda *a, **k: delete_calls.append(1))

    received = []
    bridge.conversation_removed.connect(received.append)

    bridge.request_delete_conversation("conv-xyz")

    assert delete_calls == []
    assert received == []


def test_request_delete_conversation_no_emite_removed_si_delete_devuelve_false(bridge, monkeypatch):
    from ai.memory_manager import memory
    from core.security_manager import security_manager

    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **k: True)
    monkeypatch.setattr(memory, "delete_conversation", lambda *a, **k: False)

    received = []
    bridge.conversation_removed.connect(received.append)

    bridge.request_delete_conversation("conv-ya-no-existe")

    assert received == []


# ---------------------------------------------------------------------------
# CA-20..CA-24: mensajes, guard server-side
# ---------------------------------------------------------------------------

def test_send_message_emite_eco_del_usuario_typing_y_resuelve(bridge, monkeypatch):
    from ai.memory_manager import memory

    monkeypatch.setattr("core.resolution.resolve", lambda *a, **k: SimpleNamespace(text="respuesta", matched_by="dispatcher"))
    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: None)
    monkeypatch.setattr(memory, "new_conversation_id", lambda: "new-id")
    monkeypatch.setattr(memory, "list_conversations", lambda **k: [])

    messages = []
    typing_events = []
    bridge.message_appended.connect(lambda j: messages.append(json.loads(j)))
    bridge.typing_started.connect(lambda: typing_events.append("started"))
    bridge.typing_stopped.connect(lambda: typing_events.append("stopped"))

    bridge.send_message("hola")

    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert "respuesta" in messages[1]["html"]
    assert typing_events == ["started", "stopped"]
    assert bridge._resolution_in_flight is False


def test_send_message_ignora_llamada_concurrente_ca24(bridge, monkeypatch):
    """CA-24 — guard server-side estricto: el bridge es invocable desde JS sin pasar por
    el estado `disabled` del DOM, a diferencia de un `QWidget` deshabilitado."""
    calls = []

    def fake_run_async_que_no_resuelve(fn, on_done=None, on_error=None, *args, **kwargs):
        calls.append(1)
        # deliberadamente no llama on_done/on_error: simula una resolución en curso

    monkeypatch.setattr(bridge_module, "run_async", fake_run_async_que_no_resuelve)

    bridge.send_message("primero")
    assert bridge._resolution_in_flight is True
    assert len(calls) == 1

    bridge.send_message("segundo")  # debe ser ignorado, no debe llamar run_async otra vez
    assert len(calls) == 1


def test_send_message_con_texto_vacio_no_hace_nada(bridge, monkeypatch):
    calls = []
    monkeypatch.setattr(bridge_module, "run_async", lambda *a, **k: calls.append(1))
    bridge.send_message("")
    assert calls == []
    assert bridge._resolution_in_flight is False


# ---------------------------------------------------------------------------
# REQ-026 — `send_message(text, modo)` threadea el modo activo del composer hasta
# `resolve()`. `test-results-026.md` (orion-tester): la firma nueva no tenía ningún test
# que la ejercitara (ningún test de este archivo pasaba un segundo argumento antes de
# estos dos), así que el cambio de contrato (`_try_claude`/`resolve(modo=...)`,
# desarrollo-log-026.md "Decisiones de implementación") quedaba sin cubrir end-to-end
# desde el único call site real (`composer.js::doSend()`).
# ---------------------------------------------------------------------------

def test_send_message_con_modo_lo_pasa_a_resolve_como_kwarg(bridge, monkeypatch):
    from ai.memory_manager import memory

    recibido = {}

    def fake_resolve(*args, **kwargs):
        recibido.update(kwargs)
        return SimpleNamespace(text="respuesta", matched_by="dispatcher")

    monkeypatch.setattr("core.resolution.resolve", fake_resolve)
    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: None)
    monkeypatch.setattr(memory, "new_conversation_id", lambda: "new-id")
    monkeypatch.setattr(memory, "list_conversations", lambda **k: [])

    bridge.send_message("ejecuta un script", "codigo")

    assert recibido["modo"] == "codigo"


def test_send_message_sin_modo_manda_none_no_string_vacio(bridge, monkeypatch):
    """`modo=""` (default del slot, o el frontend sin ningún modo activo) debe llegar a
    `resolve()` como `None` — `get_mode(None)` y `get_mode("")` son equivalentes
    (`test_composer_modes.py`), pero `resolve()`/`_try_claude()` distinguen `is not None`
    para decidir si pasan el kwarg `modo` a `reasoning_loop.run()`, así que el bridge debe
    normalizar antes de llamar."""
    from ai.memory_manager import memory

    recibido = {}

    def fake_resolve(*args, **kwargs):
        recibido.update(kwargs)
        return SimpleNamespace(text="respuesta", matched_by="dispatcher")

    monkeypatch.setattr("core.resolution.resolve", fake_resolve)
    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: None)
    monkeypatch.setattr(memory, "new_conversation_id", lambda: "new-id")
    monkeypatch.setattr(memory, "list_conversations", lambda **k: [])

    bridge.send_message("hola")  # sin segundo argumento -> default ""

    assert recibido["modo"] is None


def test_on_resolve_error_no_persiste_turno(bridge, monkeypatch):
    from ai.memory_manager import memory

    store_calls = []
    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: store_calls.append(1))

    messages = []
    bridge.message_appended.connect(lambda j: messages.append(json.loads(j)))

    bridge._pending_user_text = "hola"
    bridge._resolution_in_flight = True
    bridge._on_resolve_error("boom")

    assert store_calls == []  # un error no es una respuesta de la IA — no se persiste
    assert messages[-1]["role"] == "assistant"
    assert "Error" in messages[-1]["html"]
    assert bridge._resolution_in_flight is False


# ---------------------------------------------------------------------------
# CA-39, CA-40: chips
# ---------------------------------------------------------------------------

def test_run_chip_action_siempre_pasa_por_execute_action(bridge, monkeypatch):
    import agents.action_registry as action_registry_module

    calls = []
    monkeypatch.setattr(
        action_registry_module, "execute_action",
        lambda name, channel=None, user_id="default": calls.append((name, channel)) or "Captura guardada.",
    )

    received = []
    bridge.message_appended.connect(lambda j: received.append(json.loads(j)))

    bridge.run_chip_action("take_screenshot")

    assert calls[0][0] == "take_screenshot"
    assert received[0]["role"] == "system"  # CA-14: no se persiste, no es un turno
    assert "Captura guardada" in received[0]["html"]


def test_run_chip_action_error_se_reporta_como_mensaje_system(bridge, monkeypatch):
    import agents.action_registry as action_registry_module

    def boom(name, channel=None, user_id="default"):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(action_registry_module, "execute_action", boom)

    received = []
    bridge.message_appended.connect(lambda j: received.append(json.loads(j)))

    bridge.run_chip_action("take_screenshot")

    assert received[0]["role"] == "system"
    assert "Error" in received[0]["html"]


def test_build_quick_actions_payload_consulta_risk_level_en_el_momento(monkeypatch):
    """REQ-026 addendum 1: `_QUICK_ACTIONS` se redujo de 3 entradas (1 template + 2 action)
    a 1 sola entrada `template` ("Recuérdame algo") — "📷 Captura de pantalla" y
    "🌐 Abrir navegador" (los 2 `kind == "action"`) se eliminaron del catálogo. La rama
    `kind == "action"` de `_build_quick_actions_payload()` (CA-40, risk_level consultado en
    el momento) queda sin ningún elemento que la ejercite desde este catálogo — se deja sin
    retirar (ver docstring de la función), así que se verifica acá que sigue sin romper nada
    aunque no tenga consumidor: cero action_chips, `classify_action()` nunca se llama."""
    from core.security_manager import RiskLevel, security_manager

    calls = []
    monkeypatch.setattr(
        security_manager, "classify_action",
        lambda name: calls.append(name) or RiskLevel.YELLOW,
    )

    payload = bridge_module._build_quick_actions_payload()

    action_chips = [c for c in payload if c["kind"] == "action"]
    template_chips = [c for c in payload if c["kind"] == "template"]
    assert len(action_chips) == 0
    assert len(template_chips) == 1
    assert template_chips[0]["risk_level"] is None
    assert template_chips[0]["icon"] == "bell"
    assert calls == []


def test_build_modes_payload_devuelve_4_modos_id_y_label_sin_detalle_interno():
    """REQ-026: el frontend recibe solo `{id, label}` por modo — `tool_names`/`tarea`/
    `prompt_hint` son detalle interno del backend, `composer.js::renderModes()` no lo
    necesita."""
    payload = bridge_module._build_modes_payload()

    assert len(payload) == 4
    for entry in payload:
        assert set(entry.keys()) == {"id", "label"}
    assert [e["id"] for e in payload] == ["codigo", "investigacion", "flujos", "tareas"]


# ---------------------------------------------------------------------------
# REQ-026 — `set_active_mode()` / `_tarea_activa()`: el espejo efímero `_modo_activo` que
# permite a `request_models()` (menú de modelos, disparado desacoplado de `send_message()`)
# reflejar "fijado por el modo" sin esperar al próximo mensaje. `test-results-026.md`
# (orion-tester): sin cobertura previa — ningún test ejercitaba este slot ni `_tarea_activa`.
# ---------------------------------------------------------------------------

def test_set_active_mode_actualiza_el_espejo_y_reemite_models_loaded_con_su_tarea(bridge, monkeypatch):
    tareas_consultadas = []
    monkeypatch.setattr(
        bridge_module, "_build_models_payload",
        lambda tarea="razonamiento": tareas_consultadas.append(tarea) or {"tarea": tarea},
    )

    recibidos = []
    bridge.models_loaded.connect(lambda j: recibidos.append(json.loads(j)))

    bridge.set_active_mode("codigo")

    assert bridge._modo_activo == "codigo"
    assert tareas_consultadas == ["modo_codigo"]
    assert recibidos[-1] == {"tarea": "modo_codigo"}


def test_set_active_mode_con_modo_sin_tarea_fijada_usa_razonamiento(bridge, monkeypatch):
    """`flujos`/`tareas` (arquitectura-026.md §3) no fijan `tarea` — el modo queda activo
    en el espejo, pero el selector de modelo sigue ruteando como siempre."""
    tareas_consultadas = []
    monkeypatch.setattr(
        bridge_module, "_build_models_payload",
        lambda tarea="razonamiento": tareas_consultadas.append(tarea) or {},
    )

    bridge.set_active_mode("flujos")

    assert bridge._modo_activo == "flujos"
    assert tareas_consultadas == ["razonamiento"]


def test_set_active_mode_vacio_limpia_el_espejo_ca_toggle_off(bridge, monkeypatch):
    """SPEC-026: togglear el mismo modo activo lo desactiva — el frontend manda `""`."""
    monkeypatch.setattr(bridge_module, "_build_models_payload", lambda tarea="razonamiento": {})

    bridge.set_active_mode("codigo")
    assert bridge._modo_activo == "codigo"

    bridge.set_active_mode("")

    assert bridge._modo_activo is None


def test_set_active_mode_id_desconocido_es_fail_safe_no_lanza(bridge, monkeypatch):
    """Un `modo_id` inválido/obsoleto (frontend con catálogo cacheado) se trata como 'sin
    modo' — nunca rompe el slot (`get_mode()` es fail-safe, `test_composer_modes.py`)."""
    monkeypatch.setattr(bridge_module, "_build_models_payload", lambda tarea="razonamiento": {})

    bridge.set_active_mode("modo_que_no_existe")

    assert bridge._modo_activo is None


def test_request_models_refleja_la_tarea_del_modo_activo_via_el_espejo(bridge, monkeypatch):
    """`request_models()` (abrir el menú de modelos) está desacoplado de `send_message()` —
    debe usar `_modo_activo` (seteado por un `set_active_mode()` previo), no depender de
    que se haya enviado ya un mensaje con ese modo."""
    tareas_consultadas = []
    monkeypatch.setattr(
        bridge_module, "_build_models_payload",
        lambda tarea="razonamiento": tareas_consultadas.append(tarea) or {},
    )

    bridge._modo_activo = "investigacion"
    bridge.request_models()

    assert tareas_consultadas == ["modo_investigacion"]


def test_request_models_sin_modo_activo_usa_razonamiento(bridge, monkeypatch):
    tareas_consultadas = []
    monkeypatch.setattr(
        bridge_module, "_build_models_payload",
        lambda tarea="razonamiento": tareas_consultadas.append(tarea) or {},
    )

    bridge.request_models()

    assert tareas_consultadas == ["razonamiento"]


# ---------------------------------------------------------------------------
# CA-37: tema
# ---------------------------------------------------------------------------

def test_set_theme_persiste_y_emite(bridge, monkeypatch):
    import config_manager

    persisted = []
    monkeypatch.setattr(config_manager, "set_ui_theme", persisted.append)

    received = []
    bridge.theme_changed.connect(received.append)

    bridge.set_theme("dark")

    assert persisted == ["dark"]
    assert received == ["dark"]


def test_set_theme_normaliza_valor_invalido_ca38(bridge, monkeypatch):
    import config_manager

    persisted = []
    monkeypatch.setattr(config_manager, "set_ui_theme", persisted.append)

    bridge.set_theme("no-existe-este-tema")

    assert persisted == ["light"]  # DEFAULT_THEME


# ---------------------------------------------------------------------------
# CA-25: toggle de modo manos libres — nunca toca sr.Microphone() en tests
# ---------------------------------------------------------------------------

def test_toggle_wake_word_on_arranca_un_worker(bridge, no_real_threadpool):
    bridge.toggle_wake_word(True)

    wake_workers = [w for w in no_real_threadpool if isinstance(w, WakeWordWorker)]
    assert len(wake_workers) == 1
    assert bridge._wake_worker is wake_workers[0]


def test_toggle_wake_word_doble_on_no_arranca_dos_workers(bridge, no_real_threadpool):
    bridge.toggle_wake_word(True)
    bridge.toggle_wake_word(True)

    wake_workers = [w for w in no_real_threadpool if isinstance(w, WakeWordWorker)]
    assert len(wake_workers) == 1


def test_toggle_wake_word_off_setea_stop_event(bridge, no_real_threadpool):
    bridge.toggle_wake_word(True)
    worker = bridge._wake_worker
    assert worker.stop_event.is_set() is False

    bridge.toggle_wake_word(False)

    assert worker.stop_event.is_set() is True


# ---------------------------------------------------------------------------
# §4.3: confirmación YELLOW — confirm_response delega en el adaptador
# ---------------------------------------------------------------------------

def test_confirm_response_delega_en_el_adaptador_registrado(bridge):
    adapter = MagicMock()
    bridge.set_confirmation_adapter(adapter)

    bridge.confirm_response("req-1", True)

    adapter.confirm_response.assert_called_once_with("req-1", True)


def test_confirm_response_sin_adaptador_no_lanza(bridge, caplog):
    bridge.confirm_response("req-1", True)  # sin adaptador registrado — no debe lanzar
    assert any("adaptador" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# CA-01, CA-02: chrome de ventana
# ---------------------------------------------------------------------------

def test_start_resize_llama_startsystemresize_con_edge_valido(bridge):
    handle = MagicMock()
    bridge._main_window.windowHandle.return_value = handle

    bridge.start_resize("se")

    handle.startSystemResize.assert_called_once()


def test_start_resize_edge_desconocido_no_lanza_ni_llama_qt(bridge):
    handle = MagicMock()
    bridge._main_window.windowHandle.return_value = handle

    bridge.start_resize("zz")  # edge inválido

    handle.startSystemResize.assert_not_called()


def test_start_move_llama_startsystemmove(bridge):
    handle = MagicMock()
    bridge._main_window.windowHandle.return_value = handle

    bridge.start_move()

    handle.startSystemMove.assert_called_once()


def test_window_close_delega_en_main_window(bridge):
    bridge.window_close()
    bridge._main_window.close.assert_called_once()


def test_window_minimize_delega_en_main_window(bridge):
    bridge.window_minimize()
    bridge._main_window.showMinimized.assert_called_once()


def test_window_toggle_maximize_alterna_segun_estado_actual(bridge):
    bridge._main_window.isMaximized.return_value = False
    bridge.window_toggle_maximize()
    bridge._main_window.showMaximized.assert_called_once()

    bridge._main_window.isMaximized.return_value = True
    bridge.window_toggle_maximize()
    bridge._main_window.showNormal.assert_called_once()


# ---------------------------------------------------------------------------
# REQ-016/CA-05..CA-12: tareas
# ---------------------------------------------------------------------------

def test_request_tasks_llama_list_all_tasks_y_emite_tasks_loaded(bridge, monkeypatch):
    from tasks.task_manager import task_manager

    fake_tasks = [{"id": 1, "title": "a"}, {"id": 2, "title": "b"}]
    calls = []
    monkeypatch.setattr(
        task_manager, "list_all_tasks",
        lambda user_id="default": calls.append(user_id) or fake_tasks,
    )

    received = []
    bridge.tasks_loaded.connect(lambda j: received.append(json.loads(j)))

    bridge.request_tasks()

    # Se asevera contra la constante, no contra el literal: el escritorio dejó de usar
    # "default" al unificarse la identidad del dueño entre canales, y fijar el texto aquí
    # solo obligaría a volver a tocar el test la próxima vez que cambie.
    from core.user_identity import OWNER_USER_ID

    assert calls == [OWNER_USER_ID]
    assert received == [fake_tasks]  # CA-09: orden intacto, se serializa tal cual


def test_request_tasks_no_se_llama_en_request_initial_state(bridge, monkeypatch):
    from ai.memory_manager import memory
    from tasks.task_manager import task_manager
    import config_manager

    monkeypatch.setattr(memory, "list_conversations", lambda **kwargs: [])
    monkeypatch.setattr(config_manager, "get_ui_theme", lambda: "dark")

    calls = []
    monkeypatch.setattr(task_manager, "list_all_tasks", lambda **k: calls.append(1) or [])

    bridge.request_initial_state()

    assert calls == []  # CA-12: request_tasks() nunca se dispara desde el arranque


def test_create_task_con_titulo_vacio_no_llama_a_task_manager(bridge, monkeypatch):
    from tasks.task_manager import task_manager

    calls = []
    monkeypatch.setattr(task_manager, "create_task", lambda **k: calls.append(1))

    bridge.create_task("   ", "", "", "")

    assert calls == []


def test_create_task_pasa_channel_desktop_sin_modificar_create_task(bridge, monkeypatch):
    from tasks.task_manager import task_manager

    calls = []
    monkeypatch.setattr(task_manager, "create_task", lambda **k: calls.append(k) or 1)
    monkeypatch.setattr(task_manager, "list_all_tasks", lambda **k: [])

    bridge.create_task("Comprar leche", "desc", "", "")

    assert calls[0]["channel"] == "desktop"
    assert calls[0]["title"] == "Comprar leche"


def test_complete_task_no_pide_confirmacion(bridge, monkeypatch):
    from tasks.task_manager import task_manager
    from core.security_manager import security_manager

    def fail_confirm(*a, **k):
        raise AssertionError("complete_task no debe pedir confirmación (a diferencia de delete_task)")

    monkeypatch.setattr(security_manager, "require_confirmation", fail_confirm)
    monkeypatch.setattr(task_manager, "complete_task", lambda *a, **k: True)
    monkeypatch.setattr(task_manager, "list_all_tasks", lambda **k: [])

    bridge.complete_task(1)  # no debe lanzar


def test_request_delete_task_pide_confirmacion_antes_de_delete_task(bridge, monkeypatch):
    from tasks.task_manager import task_manager
    from core.security_manager import security_manager

    confirm_calls = []

    def fake_require_confirmation(action_name, channel, details="", user_id="default"):
        confirm_calls.append(action_name)
        return False

    monkeypatch.setattr(security_manager, "require_confirmation", fake_require_confirmation)
    delete_calls = []
    monkeypatch.setattr(task_manager, "delete_task", lambda *a, **k: delete_calls.append(1) or True)

    bridge.request_delete_task(42)

    assert confirm_calls == ["delete_task"]
    assert delete_calls == []  # cancelado: nunca se llama a task_manager.delete_task

    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **k: True)
    monkeypatch.setattr(task_manager, "list_all_tasks", lambda **k: [])

    bridge.request_delete_task(42)

    assert delete_calls == [1]  # confirmado: ahora sí se llama


def test_request_delete_task_usa_action_name_delete_task(bridge, monkeypatch):
    from tasks.task_manager import task_manager
    from core.security_manager import security_manager

    captured = []

    def fake_require_confirmation(action_name, channel, details="", user_id="default"):
        captured.append((action_name, details))
        return False

    monkeypatch.setattr(security_manager, "require_confirmation", fake_require_confirmation)
    monkeypatch.setattr(task_manager, "delete_task", lambda *a, **k: True)

    bridge.request_delete_task(7)

    assert captured[0][0] == "delete_task"
    assert "7" in captured[0][1]


# ---------------------------------------------------------------------------
# REQ-016/CA-13..CA-21: proyectos
# ---------------------------------------------------------------------------

def test_request_projects_llama_list_projects_y_emite_projects_loaded(bridge, monkeypatch):
    from ai.memory_manager import memory, ProjectSummary

    fake_projects = [ProjectSummary(id=1, name="A", created_at="t", conversation_count=2)]
    monkeypatch.setattr(memory, "list_projects", lambda user_id="default": fake_projects)

    received = []
    bridge.projects_loaded.connect(lambda j: received.append(json.loads(j)))

    bridge.request_projects()

    assert received == [[{"id": 1, "name": "A", "created_at": "t", "conversation_count": 2}]]


def test_create_project_con_nombre_vacio_no_llama_a_memory(bridge, monkeypatch):
    from ai.memory_manager import memory

    calls = []
    monkeypatch.setattr(memory, "create_project", lambda **k: calls.append(1))

    bridge.create_project("   ")

    assert calls == []


def test_create_project_con_nombre_valido_llama_a_memory(bridge, monkeypatch):
    from ai.memory_manager import memory

    calls = []
    monkeypatch.setattr(memory, "create_project", lambda **k: calls.append(k) or 1)
    monkeypatch.setattr(memory, "list_projects", lambda **k: [])

    bridge.create_project("Mi proyecto")

    assert calls[0]["name"] == "Mi proyecto"


def test_assign_conversation_to_project_llama_a_memory(bridge, monkeypatch):
    from ai.memory_manager import memory

    calls = []
    monkeypatch.setattr(
        memory, "assign_conversation_to_project",
        lambda conversation_id, project_id, user_id="default": calls.append((conversation_id, project_id)) or True,
    )
    monkeypatch.setattr(memory, "list_projects", lambda **k: [])

    bridge.assign_conversation_to_project("conv-1", 5)

    assert calls == [("conv-1", 5)]


def test_unassign_conversation_from_project_llama_a_memory(bridge, monkeypatch):
    from ai.memory_manager import memory

    calls = []
    monkeypatch.setattr(
        memory, "unassign_conversation_from_project",
        lambda conversation_id, user_id="default": calls.append(conversation_id) or True,
    )
    monkeypatch.setattr(memory, "list_projects", lambda **k: [])

    bridge.unassign_conversation_from_project("conv-1")

    assert calls == ["conv-1"]


def test_request_project_conversations_incluye_project_id_en_la_señal(bridge, monkeypatch):
    from ai.memory_manager import memory, ConversationSummary

    fake_convs = [ConversationSummary(conversation_id="conv-1", title="t", last_activity="a", turn_count=1)]
    monkeypatch.setattr(
        memory, "list_conversations_by_project",
        lambda project_id, user_id="default": fake_convs,
    )

    received = []
    bridge.project_conversations_loaded.connect(lambda j, pid: received.append((json.loads(j), pid)))

    bridge.request_project_conversations(9)

    assert received[0][1] == 9
    assert received[0][0][0]["conversation_id"] == "conv-1"


def test_request_delete_project_pide_confirmacion_antes_de_delete_project(bridge, monkeypatch):
    from ai.memory_manager import memory
    from core.security_manager import security_manager

    confirm_calls = []

    def fake_require_confirmation(action_name, channel, details="", user_id="default"):
        confirm_calls.append(action_name)
        return False

    monkeypatch.setattr(security_manager, "require_confirmation", fake_require_confirmation)
    delete_calls = []
    monkeypatch.setattr(memory, "delete_project", lambda *a, **k: delete_calls.append(1) or True)

    bridge.request_delete_project(3)

    assert confirm_calls == ["delete_project"]
    assert delete_calls == []


def test_request_delete_project_emite_project_removed_solo_si_delete_project_devuelve_true(bridge, monkeypatch):
    from ai.memory_manager import memory
    from core.security_manager import security_manager

    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **k: True)
    monkeypatch.setattr(memory, "delete_project", lambda *a, **k: False)
    monkeypatch.setattr(memory, "list_projects", lambda **k: [])

    removed = []
    bridge.project_removed.connect(removed.append)

    bridge.request_delete_project(3)
    assert removed == []  # delete_project() devolvió False — no se emite

    monkeypatch.setattr(memory, "delete_project", lambda *a, **k: True)
    bridge.request_delete_project(3)
    assert removed == [3]


# ---------------------------------------------------------------------------
# REQ-022/CA-03, CA-04: set_model() no debe tener efecto real cuando hay un destino
# fijado por tarea para "razonamiento" — ni escribir config.json ni emitir el toast.
#
# `test-results-022.md` (hallazgo de orion-tester): el test de GUI más cercano
# (`test_webview_buttons.py::...se_deshabilita_si_esta_fijado_por_tarea`) prueba CA-02 (el
# menú no se abre) pero, justo porque el menú no se abre, nunca llega a invocar el slot
# `set_model()` — así que el gate real del lado servidor (línea 1067 de `bridge.py`, el que
# importa porque el slot es alcanzable desde cualquier script de la página, no solo desde
# el botón) nunca se ejercitaba en ningún test. Estos dos tests lo invocan directo.
# ---------------------------------------------------------------------------

def test_ca03_set_model_no_escribe_config_si_hay_destino_fijado_por_tarea(bridge, monkeypatch):
    import ai.llm_provider as llm_provider_module

    monkeypatch.setattr(
        llm_provider_module, "destinos_de_tarea",
        lambda tarea: [("openai", "gpt-4o-mini")] if tarea == "razonamiento" else [],
    )
    escrituras = []
    monkeypatch.setattr(
        bridge_module.config_manager, "set_ai_provider_and_model",
        lambda *a, **k: escrituras.append((a, k)),
    )

    bridge.set_model("deepseek", "deepseek-chat")

    assert escrituras == []


def test_ca04_set_model_no_emite_notice_si_hay_destino_fijado_por_tarea(bridge, monkeypatch):
    import ai.llm_provider as llm_provider_module

    monkeypatch.setattr(
        llm_provider_module, "destinos_de_tarea",
        lambda tarea: [("openai", "gpt-4o-mini")] if tarea == "razonamiento" else [],
    )
    notices = []
    bridge.notice_shown.connect(lambda nivel, msg: notices.append((nivel, msg)))

    bridge.set_model("deepseek", "deepseek-chat")

    assert notices == []


def test_ca05_set_model_sin_destino_fijado_escribe_config_y_avisa(bridge, monkeypatch):
    """Regresión — sin destino fijado por tarea, el comportamiento pre-REQ-022 sigue
    intacto: `set_model()` SÍ escribe `config.json` y SÍ emite el toast de confirmación."""
    import ai.llm_provider as llm_provider_module

    monkeypatch.setattr(llm_provider_module, "destinos_de_tarea", lambda tarea: [])
    escrituras = []
    monkeypatch.setattr(
        bridge_module.config_manager, "set_ai_provider_and_model",
        lambda *a, **k: escrituras.append((a, k)),
    )
    monkeypatch.setattr(bridge_module, "_build_models_payload", lambda: {})
    notices = []
    bridge.notice_shown.connect(lambda nivel, msg: notices.append((nivel, msg)))

    bridge.set_model("deepseek", "deepseek-chat")

    assert escrituras == [(("deepseek", "deepseek-chat"), {})]
    assert notices and notices[0][0] == "ok"


# ---------------------------------------------------------------------------
# REQ-019/CA-05, CA-08, CA-16, CA-19, CA-21: sección "Seguridad" de Configuración
# ---------------------------------------------------------------------------

# Mismas 10 claves RED de REQ-005 (core/security_manager.py:_register_default_actions) —
# CA-08: ninguna fila del catálogo v1 puede coincidir con ellas.
_RED_CATEGORIES = [
    "format_disk", "delete_database", "expose_secrets", "modify_source_code",
    "send_email_as_user", "post_social_media", "elevated_system_command",
    "install_uninstall_software", "modify_system_env_vars", "grant_third_party_access",
]


def test_ca08_catalogo_v1_nunca_incluye_ninguna_clave_red():
    all_keys = [key for row in bridge_module._SECURITY_ROWS_V1 for key in row["keys"]]
    assert not (set(all_keys) & set(_RED_CATEGORIES))


def test_ca19_request_security_overrides_no_se_llama_en_request_initial_state(bridge, monkeypatch):
    from ai.memory_manager import memory
    import config_manager

    monkeypatch.setattr(memory, "list_conversations", lambda **kwargs: [])
    monkeypatch.setattr(config_manager, "get_ui_theme", lambda: "dark")

    received = []
    bridge.security_overrides_loaded.connect(lambda j: received.append(j))

    bridge.request_initial_state()

    assert received == []  # CA-19: carga perezosa, nunca desde el arranque


def test_request_security_overrides_emite_las_8_filas_del_catalogo_v1(bridge, monkeypatch):
    from core.security_manager import RiskLevel, security_manager

    monkeypatch.setattr(security_manager, "classify_action", lambda name: RiskLevel.GREEN)
    monkeypatch.setattr(security_manager, "classify_action_base", lambda name: RiskLevel.GREEN)

    received = []
    bridge.security_overrides_loaded.connect(lambda j: received.append(json.loads(j)))

    bridge.request_security_overrides()

    assert len(received[0]) == 8
    assert all(row["options"] == ["green", "yellow"] for row in received[0])  # CA-16: techo v1


def test_ca16_fila_con_effective_level_yellow_solo_ofrece_yellow(monkeypatch):
    """Nota no bloqueante (3) del handoff de orion-security: la sección 'Pruebas
    sugeridas' pre-addendum de arquitectura-019.md decía `["yellow", "red"]` para este
    caso — ese valor quedó obsoleto con el techo v1 de §11.3. El resultado correcto es
    `["yellow"]` (sin "red")."""
    from core.security_manager import RiskLevel, security_manager

    monkeypatch.setattr(security_manager, "classify_action", lambda name: RiskLevel.YELLOW)
    monkeypatch.setattr(security_manager, "classify_action_base", lambda name: RiskLevel.YELLOW)

    payload = bridge_module._build_security_overrides_payload()
    row = next(r for r in payload if r["row_id"] == "open_chrome")
    assert row["options"] == ["yellow"]


def test_build_security_overrides_payload_omite_fila_con_clave_sin_clasificar(monkeypatch):
    from core.security_manager import RiskLevel, security_manager

    def fake_classify(name):
        return None if name in ("open_app", "OPEN_APP") else RiskLevel.GREEN

    monkeypatch.setattr(security_manager, "classify_action", fake_classify)
    monkeypatch.setattr(security_manager, "classify_action_base", fake_classify)

    payload = bridge_module._build_security_overrides_payload()
    assert "open_app" not in [row["row_id"] for row in payload]
    assert len(payload) == 7


def test_save_security_override_row_con_clave_sin_clasificar_se_rechaza(bridge, monkeypatch):
    """CA-05 — una clave del catálogo que dejó de estar registrada en código nunca se
    persiste, y la fila se rechaza completa."""
    from core.security_manager import RiskLevel, security_manager

    def fake_classify(name):
        return None if name == "OPEN_APP" else RiskLevel.GREEN

    monkeypatch.setattr(security_manager, "classify_action", fake_classify)
    save_calls = []
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: save_calls.append(d))

    rejected = []
    bridge.security_override_save_rejected.connect(rejected.append)

    bridge.save_security_override("open_app", "yellow")

    assert save_calls == []
    assert rejected == ["open_app"]


def test_ca21_save_security_override_rechaza_intento_de_bajada(bridge, monkeypatch):
    """CA-21 — defensa en profundidad: un intento directo al slot (sin pasar por el
    <select> de JS) con un nivel inferior al vigente se rechaza igual."""
    from core.security_manager import RiskLevel, security_manager

    monkeypatch.setattr(security_manager, "classify_action", lambda name: RiskLevel.YELLOW)
    save_calls = []
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: save_calls.append(d))

    rejected = []
    bridge.security_override_save_rejected.connect(rejected.append)

    bridge.save_security_override("open_chrome", "green")

    assert save_calls == []
    assert rejected == ["open_chrome"]


def test_save_security_override_rechaza_nivel_por_encima_del_techo_v1(bridge, monkeypatch):
    """§11.3 — el catálogo v1 nunca acepta 'red', ni siquiera invocando el slot directo."""
    from core.security_manager import RiskLevel, security_manager

    monkeypatch.setattr(security_manager, "classify_action", lambda name: RiskLevel.GREEN)
    save_calls = []
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: save_calls.append(d))

    rejected = []
    bridge.security_override_save_rejected.connect(rejected.append)

    bridge.save_security_override("open_chrome", "red")

    assert save_calls == []
    assert rejected == ["open_chrome"]


def test_save_security_override_con_row_id_desconocido_se_rechaza(bridge, monkeypatch):
    save_calls = []
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: save_calls.append(d))

    rejected = []
    bridge.security_override_save_rejected.connect(rejected.append)

    bridge.save_security_override("__row_id_inexistente__", "yellow")

    assert save_calls == []
    assert rejected == ["__row_id_inexistente__"]


def test_save_security_override_con_nivel_invalido_se_rechaza(bridge, monkeypatch):
    save_calls = []
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: save_calls.append(d))

    rejected = []
    bridge.security_override_save_rejected.connect(rejected.append)

    bridge.save_security_override("open_chrome", "purple")

    assert save_calls == []
    assert rejected == ["open_chrome"]


def test_save_security_override_persiste_todas_las_claves_de_la_fila_en_una_sola_llamada(bridge, monkeypatch):
    """Atomicidad de fila (arquitectura-019.md §2, riesgo dedicado en la tabla de
    mitigación): `open_app` cubre 2 claves internas (`open_app` + `OPEN_APP`) — deben
    persistirse juntas en una única llamada, nunca en dos separadas."""
    from core.security_manager import RiskLevel, security_manager

    monkeypatch.setattr(security_manager, "classify_action", lambda name: RiskLevel.GREEN)
    save_calls = []
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: save_calls.append(d))

    saved = []
    bridge.security_override_saved.connect(lambda row_id, level: saved.append((row_id, level)))

    bridge.save_security_override("open_app", "yellow")

    assert len(save_calls) == 1
    assert save_calls[0] == {"open_app": "yellow", "OPEN_APP": "yellow"}
    assert saved == [("open_app", "yellow")]


def test_save_security_override_exitoso_emite_security_override_saved(bridge, monkeypatch):
    from core.security_manager import RiskLevel, security_manager

    monkeypatch.setattr(security_manager, "classify_action", lambda name: RiskLevel.GREEN)
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: None)

    saved = []
    rejected = []
    bridge.security_override_saved.connect(lambda row_id, level: saved.append((row_id, level)))
    bridge.security_override_save_rejected.connect(rejected.append)

    bridge.save_security_override("open_chrome", "yellow")

    assert saved == [("open_chrome", "yellow")]
    assert rejected == []


# ---------------------------------------------------------------------------
# CA-42: superficie del contrato — nada oculto, nada de más
# ---------------------------------------------------------------------------

_EXPECTED_SLOTS = [
    "request_initial_state", "send_message", "new_conversation", "select_conversation",
    "request_delete_conversation", "load_more_conversations", "run_chip_action",
    "set_theme", "toggle_wake_word", "confirm_response", "start_resize", "start_move",
    "window_minimize", "window_toggle_maximize", "window_close",
    # REQ-016
    "request_tasks", "create_task", "complete_task", "request_delete_task",
    "request_projects", "create_project", "assign_conversation_to_project",
    "unassign_conversation_from_project", "request_project_conversations",
    "request_delete_project",
    # REQ-019
    "request_security_overrides", "save_security_override",
]

_EXPECTED_SIGNALS = [
    "conversation_list_updated", "conversation_cleared", "conversation_removed",
    "turns_loaded", "message_appended", "typing_started", "typing_stopped",
    "gui_state_changed", "wake_state_changed", "theme_changed",
    "confirmation_requested", "file_attached", "chips_loaded", "error_occurred",
    # REQ-016
    "tasks_loaded", "projects_loaded", "project_conversations_loaded", "project_removed",
    # REQ-019
    "security_overrides_loaded", "security_override_saved", "security_override_save_rejected",
]


@pytest.mark.parametrize("slot_name", _EXPECTED_SLOTS)
def test_bridge_expone_cada_comando_del_contrato(bridge, slot_name):
    assert callable(getattr(bridge, slot_name, None)), f"falta el slot '{slot_name}'"


@pytest.mark.parametrize("signal_name", _EXPECTED_SIGNALS)
def test_bridge_expone_cada_evento_del_contrato(bridge, signal_name):
    assert hasattr(bridge, signal_name), f"falta la señal '{signal_name}'"
