"""
tests/test_memory_manager_delete_last_turn.py
REQ-055 — `ai/memory_manager.py::UnifiedMemory.delete_last_turn()`: lo que hay detrás de
«Regenerar» y «Editar» en el chat.

Mismo patrón que `tests/test_memory_manager_delete_conversation.py`: `DB_PATH` a
`tmp_path`, embedding constante, sin red.
"""

import sqlite3

import numpy as np
import pytest

import ai.memory_manager as memory_manager
from ai.memory_manager import memory


@pytest.fixture
def isolated_memory_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_delete_last_turn.db"
    monkeypatch.setattr(memory_manager, "DB_PATH", str(db_path))
    monkeypatch.setattr(memory, "_get_embedding", lambda text: np.zeros(384, dtype=np.float32))
    memory._init_db()
    memory._load_embeddings()
    return str(db_path)


def _textos(db_path, conversation_id):
    with sqlite3.connect(db_path) as conn:
        return [r[0] for r in conn.execute(
            "SELECT text FROM memories WHERE conversation_id = ? ORDER BY id", (conversation_id,)
        ).fetchall()]


def test_borra_el_ultimo_par_y_devuelve_el_mensaje_del_usuario(isolated_memory_db):
    memory.store_turn("hola", "hola, ¿qué tal?", "conv-1")
    memory.store_turn("¿qué hora es?", "Son las 10.", "conv-1")

    usuario = memory.delete_last_turn("conv-1", user_id="default")

    assert usuario is not None
    assert usuario.text == "¿qué hora es?"
    assert usuario.role == "user"
    assert _textos(isolated_memory_db, "conv-1") == ["hola", "hola, ¿qué tal?"]


def test_saca_los_embeddings_borrados_de_la_ram_sin_recargar_todo(isolated_memory_db, monkeypatch):
    memory.store_turn("hola", "hola", "conv-1")
    memory.store_turn("dos", "dos", "conv-1")
    antes = len(memory._embedding_ids)
    monkeypatch.setattr(memory, "_load_embeddings", lambda: pytest.fail("no debe recargar todo"))

    memory.delete_last_turn("conv-1")

    assert len(memory._embedding_ids) == antes - 2
    assert len(memory._embeddings) == len(memory._embedding_ids) == len(memory._embedding_user_ids)


def test_con_una_sola_fila_o_sin_par_completo_no_toca_nada(isolated_memory_db):
    with sqlite3.connect(isolated_memory_db) as conn:
        conn.execute(
            """INSERT INTO memories (user_id, text, importance, category, timestamp, archived,
                                     source, conversation_id, role)
               VALUES ('default', 'suelta', 0.5, 'interaction', '2026-01-01', 0, 'desktop',
                       'conv-2', 'user')""",
        )
    assert memory.delete_last_turn("conv-2") is None
    assert _textos(isolated_memory_db, "conv-2") == ["suelta"]

    # Dos filas pero en el orden equivocado (assistant, user): tampoco.
    with sqlite3.connect(isolated_memory_db) as conn:
        for texto, rol in (("respuesta", "assistant"), ("pregunta", "user")):
            conn.execute(
                """INSERT INTO memories (user_id, text, importance, category, timestamp, archived,
                                         source, conversation_id, role)
                   VALUES ('default', ?, 0.5, 'interaction', '2026-01-01', 0, 'desktop',
                           'conv-3', ?)""", (texto, rol),
            )
    assert memory.delete_last_turn("conv-3") is None
    assert _textos(isolated_memory_db, "conv-3") == ["respuesta", "pregunta"]


def test_no_borra_de_otro_usuario_ni_con_id_vacio(isolated_memory_db):
    memory.store_turn("hola", "hola", "conv-4", user_id="alice")

    assert memory.delete_last_turn("conv-4", user_id="bob") is None
    assert _textos(isolated_memory_db, "conv-4") == ["hola", "hola"]
    assert memory.delete_last_turn("", user_id="alice") is None
