"""
tests/test_memory_manager_recent.py
Pruebas de `ai/memory_manager.py:UnifiedMemory.get_recent()` (REQ-008/CA-09), usado por
`ui/widgets/recent_activity_card.py`.

`memory` es un singleton que abre `ai/unified_memory.db` en producción — estos tests
redirigen `ai.memory_manager.DB_PATH` a un archivo temporal (`tmp_path`) antes de cada
prueba, para no tocar la base de datos real (.claude/rules/testing.md). `get_recent()`
solo hace un SELECT, así que las filas se insertan directo por SQL (sin pasar por
`store()`, que dispararía carga del modelo de embeddings — innecesario para esta prueba
y fuera de alcance de CA-09).
"""

import sqlite3

import pytest

import ai.memory_manager as memory_manager
from ai.memory_manager import MemoryItem, memory


@pytest.fixture
def isolated_memory_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_unified_memory.db"
    monkeypatch.setattr(memory_manager, "DB_PATH", str(db_path))
    memory._init_db()
    return str(db_path)


def _insert_row(db_path, user_id, text, category, timestamp, archived=0):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO memories (user_id, text, importance, category, timestamp, archived, source)
               VALUES (?, ?, 0.5, ?, ?, ?, 'conversation')""",
            (user_id, text, category, timestamp, archived),
        )


def test_get_recent_returns_items_ordered_by_recency(isolated_memory_db):
    _insert_row(isolated_memory_db, "default", "primera interacción", "interaction", "2026-01-01T10:00:00")
    _insert_row(isolated_memory_db, "default", "segunda interacción", "interaction", "2026-01-01T12:00:00")

    items = memory.get_recent(user_id="default", limit=4)

    assert len(items) == 2
    assert isinstance(items[0], MemoryItem)
    assert items[0].text == "segunda interacción"
    assert items[1].text == "primera interacción"


def test_get_recent_respects_limit(isolated_memory_db):
    for i in range(6):
        _insert_row(isolated_memory_db, "default", f"item {i}", "interaction", f"2026-01-01T10:0{i}:00")

    items = memory.get_recent(user_id="default", limit=4)
    assert len(items) == 4


def test_get_recent_filters_by_category(isolated_memory_db):
    _insert_row(isolated_memory_db, "default", "interaccion real", "interaction", "2026-01-01T10:00:00")
    _insert_row(isolated_memory_db, "default", "copia semantica", "semantic", "2026-01-01T10:01:00")

    items = memory.get_recent(user_id="default", limit=4)
    assert len(items) == 1
    assert items[0].text == "interaccion real"


def test_get_recent_filters_by_user(isolated_memory_db):
    _insert_row(isolated_memory_db, "user_a", "de user_a", "interaction", "2026-01-01T10:00:00")
    _insert_row(isolated_memory_db, "user_b", "de user_b", "interaction", "2026-01-01T10:01:00")

    items = memory.get_recent(user_id="user_a", limit=4)
    assert len(items) == 1
    assert items[0].text == "de user_a"


def test_get_recent_excludes_archived(isolated_memory_db):
    _insert_row(isolated_memory_db, "default", "archivado", "interaction", "2026-01-01T10:00:00", archived=1)

    items = memory.get_recent(user_id="default", limit=4)
    assert items == []


def test_get_recent_empty_state_returns_empty_list(isolated_memory_db):
    items = memory.get_recent(user_id="default", limit=4)
    assert items == []
