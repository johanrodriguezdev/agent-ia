"""
tests/test_conversation_memory.py
REQ-013/CA-05, CA-09, CA-10, CA-11, CA-12 — capa conversacional de `ai/memory_manager.py`.

`DB_PATH` se redirige a `tmp_path` y `_get_embedding` se mockea con un vector constante:
sin red, sin modelo de embeddings y sin tocar `ai/unified_memory.db`
(`.claude/rules/testing.md`).
"""

import sqlite3

import numpy as np
import pytest

import ai.memory_manager as memory_manager
from ai.memory_manager import MemoryItem, memory

# Esquema de `memories` ANTERIOR a REQ-013 (sin `conversation_id` ni `role`). Se usa para
# probar que la migración aditiva funciona sobre una base ya existente en disco (CA-12).
_LEGACY_SCHEMA = """
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        text TEXT NOT NULL,
        embedding_json TEXT,
        importance REAL DEFAULT 0.5,
        category TEXT DEFAULT 'general',
        timestamp TEXT NOT NULL,
        archived INTEGER DEFAULT 0,
        source TEXT DEFAULT 'conversation'
    )
"""


@pytest.fixture
def isolated_memory_db(tmp_path, monkeypatch):
    """DB temporal + embeddings mockeados. Devuelve la ruta de la DB."""
    db_path = tmp_path / "test_conversations.db"
    monkeypatch.setattr(memory_manager, "DB_PATH", str(db_path))
    monkeypatch.setattr(
        memory, "_get_embedding", lambda text: np.zeros(384, dtype=np.float32)
    )
    memory._init_db()
    return str(db_path)


def _columns(db_path: str) -> set:
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(memories)")}


def _insert_raw(db_path, text, *, user_id="default", category="interaction",
                timestamp="2026-01-01T10:00:00", conversation_id=None, role=None,
                archived=0):
    """Inserta una fila directo por SQL (sin pasar por `store()`)."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO memories (user_id, text, importance, category, timestamp,
                                     archived, source, conversation_id, role)
               VALUES (?, ?, 0.5, ?, ?, ?, 'conversation', ?, ?)""",
            (user_id, text, category, timestamp, archived, conversation_id, role),
        )


# ---------------------------------------------------------------------------
# CA-12 — migración de esquema
# ---------------------------------------------------------------------------

def test_migracion_agrega_columnas_y_es_idempotente(tmp_path, monkeypatch):
    """CA-12 — la DB vieja se migra en caliente y `_init_db()` puede correr N veces."""
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(_LEGACY_SCHEMA)
        conn.execute(
            """INSERT INTO memories (user_id, text, importance, category, timestamp)
               VALUES ('default', 'recuerdo viejo', 0.9, 'interaction', '2025-01-01T09:00:00')"""
        )

    monkeypatch.setattr(memory_manager, "DB_PATH", str(db_path))
    assert "conversation_id" not in _columns(str(db_path))

    memory._init_db()
    memory._init_db()  # idempotente: no debe lanzar ni duplicar columnas

    columns = _columns(str(db_path))
    assert "conversation_id" in columns
    assert "role" in columns

    # La fila anterior sobrevive intacta, con las columnas nuevas en NULL.
    items = memory.get_recent(user_id="default", limit=10)
    assert [item.text for item in items] == ["recuerdo viejo"]
    assert items[0].conversation_id is None
    assert items[0].role is None


def test_filas_legacy_no_aparecen_en_list_conversations(isolated_memory_db):
    """CA-12 — lo que escribe `main.py` (sin conversation_id) no ensucia el listado."""
    _insert_raw(isolated_memory_db, "turno por voz desde main.py")
    _insert_raw(isolated_memory_db, "otro turno legacy", category="semantic")
    _insert_raw(isolated_memory_db, "hola", conversation_id="conv-a", role="user")
    _insert_raw(isolated_memory_db, "hola, ¿en qué te ayudo?",
                conversation_id="conv-a", role="assistant")

    conversations = memory.list_conversations(user_id="default")

    assert len(conversations) == 1
    assert conversations[0].conversation_id == "conv-a"
    assert conversations[0].turn_count == 2


# ---------------------------------------------------------------------------
# CA-09 — store_turn
# ---------------------------------------------------------------------------

def test_store_turn_escribe_dos_filas_mismo_conversation_id(isolated_memory_db):
    """CA-09 — un turno = fila de usuario + fila de asistente, agrupadas."""
    conversation_id = memory.new_conversation_id()

    memory.store_turn("¿qué hora es?", "Son las 10:00.", conversation_id,
                      matched_by="skill:hora")

    turns = memory.get_conversation_turns(conversation_id)
    assert len(turns) == 2
    assert [t.role for t in turns] == ["user", "assistant"]
    assert [t.text for t in turns] == ["¿qué hora es?", "Son las 10:00."]
    assert all(t.conversation_id == conversation_id for t in turns)
    assert all(t.category == "interaction" for t in turns)
    # `matched_by` viaja en `source`, no dentro del texto mostrado al usuario.
    assert turns[1].source == "desktop:skill:hora"
    assert "skill:hora" not in turns[1].text


def test_store_turn_sin_conversation_id_no_escribe_nada(isolated_memory_db):
    memory.store_turn("hola", "hola", "", matched_by="chat")

    assert memory.list_conversations(user_id="default") == []
    assert memory.get_recent(user_id="default", limit=10) == []


def test_new_conversation_id_es_unico(isolated_memory_db):
    ids = {memory.new_conversation_id() for _ in range(50)}
    assert len(ids) == 50


# ---------------------------------------------------------------------------
# CA-05, CA-10 — listado
# ---------------------------------------------------------------------------

def test_list_conversations_ordena_por_ultima_actividad_desc(isolated_memory_db):
    """CA-05, CA-10 — la conversación tocada más recientemente va primero."""
    _insert_raw(isolated_memory_db, "vieja", conversation_id="conv-vieja", role="user",
                timestamp="2026-01-01T08:00:00")
    _insert_raw(isolated_memory_db, "media", conversation_id="conv-media", role="user",
                timestamp="2026-01-01T12:00:00")
    _insert_raw(isolated_memory_db, "nueva", conversation_id="conv-nueva", role="user",
                timestamp="2026-01-01T18:00:00")
    # Un mensaje tardío en la conversación vieja la debe empujar al tope.
    _insert_raw(isolated_memory_db, "retomo esto", conversation_id="conv-vieja",
                role="user", timestamp="2026-01-01T20:00:00")

    ids = [c.conversation_id for c in memory.list_conversations(user_id="default")]

    assert ids == ["conv-vieja", "conv-nueva", "conv-media"]


def test_list_conversations_titulo_es_primer_mensaje_de_usuario_truncado(isolated_memory_db):
    """CA-10 — el título sale del PRIMER mensaje del usuario, recortado."""
    largo = "necesito que me expliques con lujo de detalle cómo funciona el pipeline completo"
    _insert_raw(isolated_memory_db, largo, conversation_id="conv-a", role="user",
                timestamp="2026-01-01T10:00:00")
    _insert_raw(isolated_memory_db, "respuesta larga del asistente", conversation_id="conv-a",
                role="assistant", timestamp="2026-01-01T10:00:01")
    _insert_raw(isolated_memory_db, "segundo mensaje del usuario", conversation_id="conv-a",
                role="user", timestamp="2026-01-01T10:05:00")

    summary = memory.list_conversations(user_id="default")[0]

    assert summary.title.startswith("necesito que me expliques")
    assert summary.title.endswith("…")
    assert len(summary.title) <= 61  # 60 caracteres + la elipsis
    assert summary.turn_count == 3


def test_list_conversations_titulo_ignora_mensajes_del_asistente(isolated_memory_db):
    _insert_raw(isolated_memory_db, "respuesta del bot", conversation_id="conv-a",
                role="assistant", timestamp="2026-01-01T10:00:00")
    _insert_raw(isolated_memory_db, "pregunta del humano", conversation_id="conv-a",
                role="user", timestamp="2026-01-01T10:00:01")

    assert memory.list_conversations(user_id="default")[0].title == "pregunta del humano"


def test_list_conversations_pagina_con_limit_offset(isolated_memory_db):
    for i in range(35):
        _insert_raw(isolated_memory_db, f"mensaje {i}", conversation_id=f"conv-{i:02d}",
                    role="user", timestamp=f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00")

    primera = memory.list_conversations(user_id="default", limit=30)
    segunda = memory.list_conversations(user_id="default", limit=30, offset=30)

    assert len(primera) == 30
    assert len(segunda) == 5
    assert not {c.conversation_id for c in primera} & {c.conversation_id for c in segunda}


def test_list_conversations_no_mezcla_usuarios(isolated_memory_db):
    _insert_raw(isolated_memory_db, "mia", conversation_id="conv-a", role="user")
    _insert_raw(isolated_memory_db, "ajena", conversation_id="conv-b", role="user",
                user_id="otro")

    ids = [c.conversation_id for c in memory.list_conversations(user_id="default")]
    assert ids == ["conv-a"]


def test_conversacion_sin_mensajes_no_existe_en_el_listado(isolated_memory_db):
    """Caso borde de SPEC-013: un id acuñado pero nunca usado no crea filas."""
    memory.new_conversation_id()

    assert memory.list_conversations(user_id="default") == []


# ---------------------------------------------------------------------------
# CA-11 — turnos de una conversación
# ---------------------------------------------------------------------------

def test_get_conversation_turns_orden_cronologico_por_id(isolated_memory_db):
    """CA-11 — con timestamps idénticos manda el orden de inserción, no el timestamp."""
    mismo_instante = "2026-01-01T10:00:00"
    _insert_raw(isolated_memory_db, "pregunta", conversation_id="conv-a", role="user",
                timestamp=mismo_instante)
    _insert_raw(isolated_memory_db, "respuesta", conversation_id="conv-a", role="assistant",
                timestamp=mismo_instante)

    turns = memory.get_conversation_turns("conv-a")

    assert [t.text for t in turns] == ["pregunta", "respuesta"]
    assert isinstance(turns[0], MemoryItem)


def test_get_conversation_turns_limit_devuelve_los_ultimos_en_orden_ascendente(isolated_memory_db):
    for i in range(10):
        _insert_raw(isolated_memory_db, f"mensaje {i}", conversation_id="conv-a", role="user",
                    timestamp=f"2026-01-01T10:{i:02d}:00")

    turns = memory.get_conversation_turns("conv-a", limit=3)

    assert [t.text for t in turns] == ["mensaje 7", "mensaje 8", "mensaje 9"]


def test_get_conversation_turns_id_inexistente_o_vacio(isolated_memory_db):
    _insert_raw(isolated_memory_db, "hola", conversation_id="conv-a", role="user")

    assert memory.get_conversation_turns("conv-inexistente") == []
    assert memory.get_conversation_turns("") == []


# ---------------------------------------------------------------------------
# §3.4 — compatibilidad de get_recent()
# ---------------------------------------------------------------------------

def test_get_recent_sin_role_devuelve_todo_como_antes(isolated_memory_db):
    """Regresión: el comportamiento por defecto no cambia con REQ-013."""
    _insert_raw(isolated_memory_db, "legacy", timestamp="2026-01-01T10:00:00")
    _insert_raw(isolated_memory_db, "pregunta", conversation_id="conv-a", role="user",
                timestamp="2026-01-01T11:00:00")
    _insert_raw(isolated_memory_db, "respuesta", conversation_id="conv-a", role="assistant",
                timestamp="2026-01-01T12:00:00")

    items = memory.get_recent(user_id="default", limit=10)

    assert [i.text for i in items] == ["respuesta", "pregunta", "legacy"]


def test_get_recent_role_user_incluye_filas_legacy_con_role_null(isolated_memory_db):
    """§3.4 — `role="user"` filtra las respuestas del asistente pero conserva lo legacy."""
    _insert_raw(isolated_memory_db, "legacy", timestamp="2026-01-01T10:00:00")
    _insert_raw(isolated_memory_db, "pregunta", conversation_id="conv-a", role="user",
                timestamp="2026-01-01T11:00:00")
    _insert_raw(isolated_memory_db, "respuesta", conversation_id="conv-a", role="assistant",
                timestamp="2026-01-01T12:00:00")

    items = memory.get_recent(user_id="default", limit=10, role="user")

    assert [i.text for i in items] == ["pregunta", "legacy"]
