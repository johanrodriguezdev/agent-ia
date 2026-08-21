"""
tests/test_memory_manager_projects.py
REQ-016/CA-14..CA-21 — esquema y CRUD de "proyectos" (agrupador de conversaciones) en
`ai/memory_manager.py::UnifiedMemory`.

Mismo patrón exacto de fixture que `tests/test_memory_manager_delete_conversation.py`
(`isolated_memory_db`: `DB_PATH` redirigido a `tmp_path`, `_get_embedding` mockeado, sin
red) — sin tocar `ai/unified_memory.db` real (`.claude/rules/testing.md`).

La prueba más importante de este archivo es la no-regresión de CA-21: agregar el esquema
de proyectos (2 tablas nuevas) no debe alterar ni un resultado de las 5 funciones que la
SPEC protege explícitamente.
"""

import sqlite3

import numpy as np
import pytest

import ai.memory_manager as memory_manager
from ai.memory_manager import ConversationSummary, memory


@pytest.fixture
def isolated_memory_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_projects.db"
    monkeypatch.setattr(memory_manager, "DB_PATH", str(db_path))
    monkeypatch.setattr(memory, "_get_embedding", lambda text: np.zeros(384, dtype=np.float32))
    memory._init_db()
    return str(db_path)


def _insert_raw(db_path, text, *, user_id="default", conversation_id, role):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO memories (user_id, text, importance, category, timestamp,
                                     archived, source, conversation_id, role)
               VALUES (?, ?, 0.5, 'interaction', '2026-01-01T10:00:00', 0, 'desktop', ?, ?)""",
            (user_id, text, conversation_id, role),
        )


def _insert_orphan_project_conversation(db_path, *, conversation_id, project_id, user_id="default"):
    """Inserta directamente una fila en `project_conversations` sin fila correspondiente en
    `memories` — simula el caso "huérfano" que la defensa pasiva de §4.2/§4.3 debe excluir."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO project_conversations (conversation_id, project_id, user_id, assigned_at)
               VALUES (?, ?, ?, '2026-01-01T10:00:00')""",
            (conversation_id, project_id, user_id),
        )


# ---------------------------------------------------------------------------
# CA-14, CA-15: crear y listar proyectos
# ---------------------------------------------------------------------------

def test_create_project_devuelve_id_y_lo_lista(isolated_memory_db):
    project_id = memory.create_project(user_id="default", name="Mi proyecto")

    assert isinstance(project_id, int)
    projects = memory.list_projects(user_id="default")
    assert len(projects) == 1
    assert projects[0].id == project_id
    assert projects[0].name == "Mi proyecto"
    assert projects[0].conversation_count == 0


def test_create_project_rechaza_nombre_vacio_o_solo_espacios(isolated_memory_db):
    assert memory.create_project(user_id="default", name="") is None
    assert memory.create_project(user_id="default", name="   ") is None
    assert memory.list_projects(user_id="default") == []


def test_create_project_permite_nombres_duplicados(isolated_memory_db):
    """Caso borde explícito de SPEC-016: "es solo una etiqueta visual, no un identificador"."""
    id1 = memory.create_project(user_id="default", name="Trabajo")
    id2 = memory.create_project(user_id="default", name="Trabajo")

    assert id1 != id2
    projects = memory.list_projects(user_id="default")
    assert len(projects) == 2


# ---------------------------------------------------------------------------
# CA-16, CA-20: asignar/reasignar conversación a proyecto
# ---------------------------------------------------------------------------

def test_assign_conversation_to_project_reasigna_sin_duplicar(isolated_memory_db):
    _insert_raw(isolated_memory_db, "hola", conversation_id="conv-1", role="user")
    proj_a = memory.create_project(user_id="default", name="A")
    proj_b = memory.create_project(user_id="default", name="B")

    assert memory.assign_conversation_to_project("conv-1", proj_a, user_id="default") is True
    assert memory.assign_conversation_to_project("conv-1", proj_b, user_id="default") is True

    projects = {p.id: p.conversation_count for p in memory.list_projects(user_id="default")}
    assert projects[proj_a] == 0
    assert projects[proj_b] == 1


def test_assign_conversation_to_project_rechaza_project_id_de_otro_user_id(isolated_memory_db):
    _insert_raw(isolated_memory_db, "hola", user_id="alice", conversation_id="conv-2", role="user")
    proj_bob = memory.create_project(user_id="bob", name="Proyecto de Bob")

    result = memory.assign_conversation_to_project("conv-2", proj_bob, user_id="alice")

    assert result is False


def test_assign_conversation_to_project_rechaza_conversation_id_inexistente(isolated_memory_db):
    proj = memory.create_project(user_id="default", name="A")

    result = memory.assign_conversation_to_project("no-existe", proj, user_id="default")

    assert result is False


def test_assign_conversation_to_project_con_conversation_id_vacio_no_lanza(isolated_memory_db):
    proj = memory.create_project(user_id="default", name="A")
    assert memory.assign_conversation_to_project("", proj, user_id="default") is False
    assert memory.assign_conversation_to_project(None, proj, user_id="default") is False


# ---------------------------------------------------------------------------
# CA-16 (desasignar) / CA-21 (limpieza de huérfanos, reutilizada por el bridge)
# ---------------------------------------------------------------------------

def test_unassign_conversation_from_project_es_idempotente(isolated_memory_db):
    _insert_raw(isolated_memory_db, "hola", conversation_id="conv-3", role="user")
    proj = memory.create_project(user_id="default", name="A")
    memory.assign_conversation_to_project("conv-3", proj, user_id="default")

    first = memory.unassign_conversation_from_project("conv-3", user_id="default")
    second = memory.unassign_conversation_from_project("conv-3", user_id="default")

    assert first is True
    assert second is False  # ya no había fila — no lanza, retorna False


def test_unassign_conversation_from_project_sobre_conversacion_sin_proyecto_no_lanza(isolated_memory_db):
    assert memory.unassign_conversation_from_project("nunca-asignada", user_id="default") is False


# ---------------------------------------------------------------------------
# CA-17: vista de detalle + defensa pasiva contra huérfanos (INNER JOIN)
# ---------------------------------------------------------------------------

def test_list_conversations_by_project_devuelve_conversaciones_asignadas(isolated_memory_db):
    _insert_raw(isolated_memory_db, "hola", conversation_id="conv-4", role="user")
    proj = memory.create_project(user_id="default", name="A")
    memory.assign_conversation_to_project("conv-4", proj, user_id="default")

    result = memory.list_conversations_by_project(proj, user_id="default")

    assert len(result) == 1
    assert isinstance(result[0], ConversationSummary)
    assert result[0].conversation_id == "conv-4"


def test_list_conversations_by_project_excluye_huerfanos_via_inner_join(isolated_memory_db):
    proj = memory.create_project(user_id="default", name="A")
    # Fila cruda en project_conversations SIN fila correspondiente en `memories`.
    _insert_orphan_project_conversation(isolated_memory_db, conversation_id="fantasma", project_id=proj)

    result = memory.list_conversations_by_project(proj, user_id="default")

    assert result == []


# ---------------------------------------------------------------------------
# CA-18, CA-19: eliminar proyecto sin borrar conversaciones
# ---------------------------------------------------------------------------

def test_delete_project_no_borra_conversaciones(isolated_memory_db):
    _insert_raw(isolated_memory_db, "hola", conversation_id="conv-5", role="user")
    _insert_raw(isolated_memory_db, "hola, en qué ayudo", conversation_id="conv-5", role="assistant")
    proj = memory.create_project(user_id="default", name="A")
    memory.assign_conversation_to_project("conv-5", proj, user_id="default")

    result = memory.delete_project(proj, user_id="default")

    assert result is True
    with sqlite3.connect(isolated_memory_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE conversation_id = ?", ("conv-5",)
        ).fetchone()[0]
    assert count == 2  # las conversaciones quedan intactas (CA-19)


def test_delete_project_borra_sus_asignaciones(isolated_memory_db):
    _insert_raw(isolated_memory_db, "hola", conversation_id="conv-6", role="user")
    proj = memory.create_project(user_id="default", name="A")
    memory.assign_conversation_to_project("conv-6", proj, user_id="default")

    memory.delete_project(proj, user_id="default")

    with sqlite3.connect(isolated_memory_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM project_conversations WHERE project_id = ?", (proj,)
        ).fetchone()[0]
    assert count == 0


def test_delete_project_retorna_false_sobre_id_inexistente(isolated_memory_db):
    assert memory.delete_project(999999, user_id="default") is False


def test_delete_project_no_borra_de_otro_user_id(isolated_memory_db):
    proj = memory.create_project(user_id="alice", name="Proyecto de alice")

    result = memory.delete_project(proj, user_id="bob")

    assert result is False
    assert len(memory.list_projects(user_id="alice")) == 1


# ---------------------------------------------------------------------------
# CA-21 — no-regresión: las 5 funciones protegidas siguen funcionando exactamente igual
# ---------------------------------------------------------------------------

def test_new_conversation_id_store_turn_list_conversations_get_conversation_turns_delete_conversation_sin_cambios(
    isolated_memory_db,
):
    """Ejecuta las 5 funciones protegidas por CA-21 en secuencia — agregar el esquema de
    proyectos no debe alterar ningún resultado de ninguna de ellas."""
    conv_id = memory.new_conversation_id()
    assert isinstance(conv_id, str) and conv_id

    memory.store_turn("hola", "hola, en qué ayudo", conv_id, user_id="default")

    conversations = memory.list_conversations(user_id="default")
    assert len(conversations) == 1
    assert conversations[0].conversation_id == conv_id
    assert conversations[0].turn_count == 2

    turns = memory.get_conversation_turns(conv_id, user_id="default")
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[1].role == "assistant"

    deleted = memory.delete_conversation(conv_id, user_id="default")
    assert deleted is True
    assert memory.list_conversations(user_id="default") == []


def test_delete_conversation_no_limpia_project_conversations_por_si_sola(isolated_memory_db):
    """Confirma explícitamente que `ai/memory_manager.py::delete_conversation()` NO toca
    `project_conversations` — la limpieza vive en `Bridge._delete_conversation_flow()`
    (arquitectura-016.md §4.3), no acá. Evita que un futuro refactor mueva silenciosamente
    esa responsabilidad sin que un test lo note."""
    _insert_raw(isolated_memory_db, "hola", conversation_id="conv-7", role="user")
    proj = memory.create_project(user_id="default", name="A")
    memory.assign_conversation_to_project("conv-7", proj, user_id="default")

    memory.delete_conversation("conv-7", user_id="default")

    with sqlite3.connect(isolated_memory_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM project_conversations WHERE conversation_id = ?", ("conv-7",)
        ).fetchone()[0]
    # la fila de asignación SIGUE ahí — delete_conversation() no la limpió por sí sola.
    assert count == 1
    # y la defensa pasiva de list_conversations_by_project() la excluye igual (huérfana).
    assert memory.list_conversations_by_project(proj, user_id="default") == []
