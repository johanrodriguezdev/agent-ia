"""
tests/test_pasos_persistidos.py
REQ-059 — los pasos del turno (REQ-053) se guardan con la respuesta y vuelven al reabrir
la conversación: `store_turn(pasos=...)`, `MemoryItem.pasos`, y el bridge que los manda en
`turns_loaded`.
"""

import json
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest

import ai.memory_manager as memory_manager
from ai.memory_manager import memory


@pytest.fixture
def isolated_memory_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_pasos.db"
    monkeypatch.setattr(memory_manager, "DB_PATH", str(db_path))
    monkeypatch.setattr(memory, "_get_embedding", lambda text: np.zeros(384, dtype=np.float32))
    memory._init_db()
    return str(db_path)


def test_store_turn_guarda_los_pasos_en_la_respuesta_y_vuelven_al_leer(isolated_memory_db):
    memory.store_turn("¿qué clima hace?", "Soleado, 24°.", "conv-1",
                      pasos=["Consultando el clima: Bogotá", "Leyendo la página: ejemplo.com"])

    turnos = memory.get_conversation_turns("conv-1")
    assert [t.role for t in turnos] == ["user", "assistant"]
    assert turnos[0].pasos == []
    assert turnos[1].pasos == ["Consultando el clima: Bogotá", "Leyendo la página: ejemplo.com"]


def test_sin_pasos_la_columna_queda_vacia_y_la_firma_vieja_sigue_valiendo(isolated_memory_db):
    memory.store_turn("hola", "hola", "conv-2")
    with sqlite3.connect(isolated_memory_db) as conn:
        filas = conn.execute("SELECT pasos_json FROM memories WHERE conversation_id = 'conv-2'").fetchall()
    assert filas == [(None,), (None,)]
    assert all(t.pasos == [] for t in memory.get_conversation_turns("conv-2"))


def test_la_migracion_agrega_la_columna_a_una_base_vieja(tmp_path, monkeypatch):
    db_path = tmp_path / "vieja.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, text TEXT NOT NULL,
            embedding_json TEXT, importance REAL DEFAULT 0.5, category TEXT DEFAULT 'general',
            timestamp TEXT NOT NULL, archived INTEGER DEFAULT 0, source TEXT DEFAULT 'conversation',
            conversation_id TEXT, role TEXT)""")
        conn.execute("""INSERT INTO memories (user_id, text, timestamp, conversation_id, role)
                        VALUES ('default', 'vieja', '2026-01-01', 'c', 'assistant')""")
    monkeypatch.setattr(memory_manager, "DB_PATH", str(db_path))
    monkeypatch.setattr(memory, "_get_embedding", lambda text: np.zeros(384, dtype=np.float32))

    memory._init_db()

    with sqlite3.connect(db_path) as conn:
        columnas = {r[1] for r in conn.execute("PRAGMA table_info(memories)")}
    assert "pasos_json" in columnas
    assert memory.get_conversation_turns("c")[0].pasos == []


def test_pasos_corruptos_o_con_basura_no_rompen_la_lectura(isolated_memory_db):
    memory.store_turn("a", "b", "conv-3")
    with sqlite3.connect(isolated_memory_db) as conn:
        conn.execute("UPDATE memories SET pasos_json = '{no es json' WHERE role = 'assistant'")
    assert memory.get_conversation_turns("conv-3")[1].pasos == []
    with sqlite3.connect(isolated_memory_db) as conn:
        conn.execute("""UPDATE memories SET pasos_json = '["ok", 3, null, "dos"]' WHERE role = 'assistant'""")
    assert memory.get_conversation_turns("conv-3")[1].pasos == ["ok", "dos"]


def test_se_guardan_como_maximo_cuarenta_pasos(isolated_memory_db):
    memory.store_turn("a", "b", "conv-4", pasos=[f"paso {i}" for i in range(60)])
    assert len(memory.get_conversation_turns("conv-4")[1].pasos) == 40


# --------------------------------------------------------------------------- bridge

@pytest.fixture
def bridge(qtbot, monkeypatch):
    import ui.webview.bridge as bridge_module
    from ui.webview.bridge import Bridge

    def _fake_run_async(fn, on_done=None, on_error=None, *args, **kwargs):
        result = fn(*args, **kwargs)
        if on_done:
            on_done(result)
        return result

    monkeypatch.setattr(bridge_module, "run_async", _fake_run_async)
    from unittest.mock import MagicMock

    return Bridge(MagicMock())


def test_al_reabrir_la_conversacion_las_respuestas_traen_sus_pasos(bridge, monkeypatch):
    turnos = [
        SimpleNamespace(id=1, role="user", text="¿clima?", timestamp="t1", pasos=[]),
        SimpleNamespace(id=2, role="assistant", text="Soleado.", timestamp="t2",
                        pasos=["Consultando el clima: Bogotá"]),
        SimpleNamespace(id=3, role="assistant", text="Sin pasos.", timestamp="t3", pasos=[]),
    ]
    monkeypatch.setattr(memory, "get_conversation_turns", lambda *a, **k: turnos)
    recibidos = []
    bridge.turns_loaded.connect(lambda payload: recibidos.append(json.loads(payload)))

    bridge.select_conversation("conv-1")

    cargados = recibidos[0]
    assert "pasos" not in cargados[0]
    assert cargados[1]["pasos"] == ["Consultando el clima: Bogotá"]
    assert "pasos" not in cargados[2]


def test_el_turno_se_guarda_con_sus_pasos_y_sin_ellos_no_se_manda_el_kwarg(bridge, monkeypatch):
    guardados = []
    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: guardados.append(k))
    monkeypatch.setattr(memory, "list_conversations", lambda **k: [])
    monkeypatch.setattr(memory, "get_conversation_title", lambda *a, **k: "x")
    bridge._conversation_id = "conv-1"
    bridge._pending_user_text = "¿clima?"
    bridge._resolution_in_flight = True
    bridge._pasos_del_turno = ["Consultando el clima: Bogotá"]

    bridge._on_resolve_done(SimpleNamespace(text="Soleado.", matched_by="claude"))
    assert guardados[-1]["pasos"] == ["Consultando el clima: Bogotá"]

    bridge._pending_user_text = "hola"
    bridge._resolution_in_flight = True
    bridge._pasos_del_turno = []
    bridge._on_resolve_done(SimpleNamespace(text="Hola.", matched_by="claude"))
    assert "pasos" not in guardados[-1]
