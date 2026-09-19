"""
tests/test_proyectos_sidebar.py
REQ-051 — los proyectos en la barra lateral: Recientes sin los chats que ya están en un
proyecto, «Nuevo chat aquí», y las herramientas para hacerlo por instrucción.

Lo que protege esta suite:
- `list_conversations(sin_proyecto=True)` deja fuera lo que está en un proyecto y no
  cambia nada cuando no se pide (CA-21 de REQ-016 sigue en pie).
- El bridge lista Recientes sin proyecto; `new_conversation_in_project` deja el chat que
  nace con el primer mensaje dentro del proyecto; mover/sacar refrescan Recientes.
- `chat_project_*`: verdes, solo escritorio; «este chat» sale de `core/conversacion_activa`;
  si el chat todavía no tiene turnos, la asignación queda pendiente y el bridge la aplica
  al guardar el turno.

Sin red ni DB real: `DB_PATH` en `tmp_path`, embeddings falsos.
"""

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import agents.tool_registry as registry
import ai.memory_manager as memory_manager
import ui.webview.bridge as bridge_module
from ai.memory_manager import memory
from core import conversacion_activa
from core.security_manager import DESKTOP_ONLY_ACTIONS, ChannelType, RiskLevel, security_manager
from core.user_identity import OWNER_USER_ID
from ui.webview.bridge import Bridge


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_manager, "DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setattr(memory, "_get_embedding", lambda text: np.zeros(384, dtype=np.float32))
    memory._init_db()
    conversacion_activa.fijar(None)
    conversacion_activa.tomar_asignacion_pendiente()
    yield
    conversacion_activa.fijar(None)
    conversacion_activa.tomar_asignacion_pendiente()


def _con_turnos(conversation_id, texto="hola", user_id=OWNER_USER_ID):
    memory.store(texto, user_id=user_id, conversation_id=conversation_id, role="user",
                 category="interaction")
    memory.store("respuesta", user_id=user_id, conversation_id=conversation_id, role="assistant",
                 category="interaction")


# ── modelo ──────────────────────────────────────────────────────────

def test_recientes_sin_proyecto_excluye_lo_que_ya_esta_en_uno(db):
    _con_turnos("libre")
    _con_turnos("en-tesis")
    tesis = memory.create_project(user_id=OWNER_USER_ID, name="Tesis")
    assert memory.assign_conversation_to_project("en-tesis", tesis, user_id=OWNER_USER_ID)

    todas = {c.conversation_id for c in memory.list_conversations(user_id=OWNER_USER_ID)}
    sueltas = {c.conversation_id for c in memory.list_conversations(user_id=OWNER_USER_ID, sin_proyecto=True)}
    del_proyecto = {c.conversation_id for c in memory.list_conversations_by_project(tesis, user_id=OWNER_USER_ID)}

    assert todas == {"libre", "en-tesis"}          # sin pedirlo, nada cambia (CA-21)
    assert sueltas == {"libre"}
    assert del_proyecto == {"en-tesis"}


def test_al_sacar_del_proyecto_vuelve_a_recientes(db):
    _con_turnos("c")
    p = memory.create_project(user_id=OWNER_USER_ID, name="P")
    memory.assign_conversation_to_project("c", p, user_id=OWNER_USER_ID)
    memory.unassign_conversation_from_project("c", user_id=OWNER_USER_ID)

    assert {c.conversation_id for c in memory.list_conversations(user_id=OWNER_USER_ID, sin_proyecto=True)} == {"c"}


# ── bridge ──────────────────────────────────────────────────────────

@pytest.fixture
def fake_run_async(monkeypatch):
    def _fake(fn, on_done=None, on_error=None, *args, **kwargs):
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            if on_error:
                on_error(str(e))
            return None
        if on_done:
            on_done(result)
        return result

    monkeypatch.setattr(bridge_module, "run_async", _fake)


@pytest.fixture
def bridge(qtbot, db, fake_run_async):
    return Bridge(MagicMock())


def test_recientes_del_bridge_no_trae_chats_de_proyectos(bridge, qtbot):
    _con_turnos("libre")
    _con_turnos("en-p")
    p = memory.create_project(user_id=OWNER_USER_ID, name="P")
    memory.assign_conversation_to_project("en-p", p, user_id=OWNER_USER_ID)

    with qtbot.waitSignal(bridge.conversation_list_updated, timeout=1000) as blocker:
        bridge._load_conversations(0)

    assert [c["conversation_id"] for c in json.loads(blocker.args[0])] == ["libre"]


def test_nuevo_chat_aqui_nace_dentro_del_proyecto(bridge, qtbot):
    p = memory.create_project(user_id=OWNER_USER_ID, name="P")

    bridge.new_conversation_in_project(p)
    conversation_id = bridge._ensure_conversation_id()       # lo que hace el primer mensaje
    _con_turnos(conversation_id)                             # el turno se guarda al terminar…
    bridge._tras_guardar_turno(None)                         # …y ahí se aplica la asignación

    assert {c.conversation_id for c in memory.list_conversations_by_project(p, user_id=OWNER_USER_ID)} == {conversation_id}
    assert bridge._pending_project_id is None
    # Un «Nuevo chat» normal después no arrastra el proyecto.
    bridge.new_conversation()
    otro = bridge._ensure_conversation_id()
    _con_turnos(otro)
    bridge._tras_guardar_turno(None)
    assert otro not in {c.conversation_id for c in memory.list_conversations_by_project(p, user_id=OWNER_USER_ID)}


def test_mover_y_sacar_refrescan_recientes(bridge, qtbot):
    _con_turnos("c")
    p = memory.create_project(user_id=OWNER_USER_ID, name="P")

    with qtbot.waitSignal(bridge.conversation_list_updated, timeout=1000) as blocker:
        bridge.assign_conversation_to_project("c", p)
    assert json.loads(blocker.args[0]) == []

    with qtbot.waitSignal(bridge.conversation_list_updated, timeout=1000) as blocker:
        bridge.unassign_conversation_from_project("c")
    assert [c["conversation_id"] for c in json.loads(blocker.args[0])] == ["c"]


def test_al_guardar_el_turno_se_aplica_la_asignacion_pendiente(bridge, qtbot):
    p = memory.create_project(user_id=OWNER_USER_ID, name="P")
    bridge.new_conversation()
    cid = bridge._ensure_conversation_id()
    conversacion_activa.pedir_asignacion(cid, p)          # lo que hace el tool en el primer turno
    _con_turnos(cid)                                      # el turno ya está guardado

    with qtbot.waitSignal(bridge.projects_loaded, timeout=1000):
        bridge._tras_guardar_turno(None)

    assert {c.conversation_id for c in memory.list_conversations_by_project(p, user_id=OWNER_USER_ID)} == {cid}
    assert conversacion_activa.tomar_asignacion_pendiente() is None


# ── herramientas del agente ─────────────────────────────────────────

HERRAMIENTAS = ("chat_project_list", "chat_project_create", "chat_project_assign_current")


def _invoke(nombre):
    return registry.get_tool(nombre).invoke


def test_las_tres_son_verdes_y_solo_de_escritorio():
    for nombre in HERRAMIENTAS:
        assert registry.get_tool(nombre).risk_level is RiskLevel.GREEN, nombre
        assert nombre in DESKTOP_ONLY_ACTIONS, nombre
        assert not security_manager.is_action_allowed(nombre, ChannelType.TELEGRAM), nombre


def test_listar_crear_y_repetido(db):
    assert "No hay ningún proyecto" in _invoke("chat_project_list")({})
    assert "creado" in _invoke("chat_project_create")({"name": "Tesis"})
    assert "Ya hay un proyecto" in _invoke("chat_project_create")({"name": "tesis"})
    assert "Tesis (0 chats)" in _invoke("chat_project_list")({})


def test_guardar_este_chat_en_un_proyecto_existente(db):
    _con_turnos("actual")
    conversacion_activa.fijar("actual")
    _invoke("chat_project_create")({"name": "Tesis"})

    resultado = _invoke("chat_project_assign_current")({"project": "tesis"})

    assert "quedó en el proyecto 'Tesis'" in resultado
    p = memory.list_projects(user_id=OWNER_USER_ID)[0]
    assert {c.conversation_id for c in memory.list_conversations_by_project(p.id, user_id=OWNER_USER_ID)} == {"actual"}


def test_sin_chat_abierto_no_hay_nada_que_mover(db):
    conversacion_activa.fijar(None)
    assert "No hay ningún chat abierto" in _invoke("chat_project_assign_current")({"project": "x"})


def test_proyecto_inexistente_se_ofrece_crear_o_se_crea_si_se_pide(db):
    _con_turnos("actual")
    conversacion_activa.fijar("actual")

    assert "No hay ningún proyecto llamado 'Casa'" in _invoke("chat_project_assign_current")({"project": "Casa"})
    assert memory.list_projects(user_id=OWNER_USER_ID) == []

    resultado = _invoke("chat_project_assign_current")({"project": "Casa", "create_if_missing": True})
    assert "quedó en el proyecto 'Casa'" in resultado
    assert [p.name for p in memory.list_projects(user_id=OWNER_USER_ID)] == ["Casa"]


def test_en_el_primer_turno_la_asignacion_queda_pendiente(db):
    """El chat recién empezado no tiene turnos guardados todavía: `assign` lo rechaza, así
    que queda pedido para cuando el bridge guarde el turno."""
    conversacion_activa.fijar("recien-nacido")
    _invoke("chat_project_create")({"name": "Tesis"})

    resultado = _invoke("chat_project_assign_current")({"project": "Tesis"})

    assert "en cuanto termine este turno" in resultado
    p = memory.list_projects(user_id=OWNER_USER_ID)[0]
    assert conversacion_activa.tomar_asignacion_pendiente() == ("recien-nacido", p.id)
