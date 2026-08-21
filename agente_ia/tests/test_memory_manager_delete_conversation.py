"""
tests/test_memory_manager_delete_conversation.py
REQ-015/CA-31 — `ai/memory_manager.py::UnifiedMemory.delete_conversation()`.

`DB_PATH` se redirige a `tmp_path` y `_get_embedding` se mockea con un vector constante:
sin red, sin modelo de embeddings y sin tocar `ai/unified_memory.db` real (mismo patrón
de `tests/test_conversation_memory.py`, REQ-013 — `.claude/rules/testing.md`).
"""

import sqlite3

import numpy as np
import pytest

import ai.memory_manager as memory_manager
from ai.memory_manager import memory


@pytest.fixture
def isolated_memory_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_delete_conversation.db"
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


def _row_count(db_path, conversation_id):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM memories WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()[0]


def test_delete_conversation_borra_filas_propias(isolated_memory_db):
    _insert_raw(isolated_memory_db, "hola", conversation_id="conv-1", role="user")
    _insert_raw(isolated_memory_db, "hola, en qué ayudo", conversation_id="conv-1", role="assistant")

    result = memory.delete_conversation("conv-1", user_id="default")

    assert result is True
    assert _row_count(isolated_memory_db, "conv-1") == 0


def test_delete_conversation_no_borra_de_otro_user_id(isolated_memory_db):
    _insert_raw(isolated_memory_db, "hola", user_id="alice", conversation_id="conv-2", role="user")

    result = memory.delete_conversation("conv-2", user_id="bob")

    assert result is False
    assert _row_count(isolated_memory_db, "conv-2") == 1


def test_delete_conversation_retorna_false_sobre_id_inexistente(isolated_memory_db):
    result = memory.delete_conversation("no-existe", user_id="default")
    assert result is False


def test_delete_conversation_retorna_false_sobre_id_vacio(isolated_memory_db):
    assert memory.delete_conversation("", user_id="default") is False
    assert memory.delete_conversation(None, user_id="default") is False


def test_delete_conversation_no_lanza_sobre_conversacion_ya_borrada(isolated_memory_db):
    _insert_raw(isolated_memory_db, "hola", conversation_id="conv-3", role="user")

    first = memory.delete_conversation("conv-3", user_id="default")
    second = memory.delete_conversation("conv-3", user_id="default")

    assert first is True
    assert second is False  # ya no quedan filas — no lanza, retorna False


def test_delete_conversation_solo_borra_la_conversacion_pedida(isolated_memory_db):
    _insert_raw(isolated_memory_db, "conv A", conversation_id="conv-a", role="user")
    _insert_raw(isolated_memory_db, "conv B", conversation_id="conv-b", role="user")

    memory.delete_conversation("conv-a", user_id="default")

    assert _row_count(isolated_memory_db, "conv-a") == 0
    assert _row_count(isolated_memory_db, "conv-b") == 1


def test_delete_conversation_recarga_embeddings_solo_si_borro_algo(isolated_memory_db, monkeypatch):
    calls = []
    monkeypatch.setattr(memory, "_load_embeddings", lambda: calls.append(1))

    memory.delete_conversation("no-existe", user_id="default")
    assert calls == []

    _insert_raw(isolated_memory_db, "hola", conversation_id="conv-4", role="user")
    memory.delete_conversation("conv-4", user_id="default")
    assert calls == [1]
