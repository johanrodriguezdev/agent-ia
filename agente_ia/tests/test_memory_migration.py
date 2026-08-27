"""
tests/test_memory_migration.py
Pruebas de `ai/memory_migration.py` — consolidación de las memorias dispersas.

Dos invariantes que no pueden romperse, porque opera sobre datos reales del usuario:
**no borra ningún origen** y **no duplica al repetirse**. El resto de la suite cubre que
solo se migre lo del dueño y que la búsqueda semántica sobreviva.
"""

import json
import os
import sqlite3

import pytest

from ai import memory_migration as mm

ESQUEMA_UNIFIED = """
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    embedding_json TEXT,
    importance REAL DEFAULT 0.5,
    category TEXT DEFAULT 'general',
    timestamp TEXT NOT NULL,
    archived INTEGER DEFAULT 0,
    source TEXT DEFAULT 'conversation',
    conversation_id TEXT,
    role TEXT
)
"""


def _crear_unified(path):
    conn = sqlite3.connect(path)
    conn.execute(ESQUEMA_UNIFIED)
    conn.commit()
    conn.close()


def _crear_pares(path, columna, filas):
    conn = sqlite3.connect(path)
    conn.execute(
        f"CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        f"user_input TEXT NOT NULL, {columna} TEXT NOT NULL, timestamp DATETIME)"
    )
    conn.executemany(
        f"INSERT INTO memories (user_input, {columna}, timestamp) VALUES (?,?,?)", filas
    )
    conn.commit()
    conn.close()


def _crear_semanticas(path, filas):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE semantic_memories (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "text TEXT NOT NULL, embedding_json TEXT NOT NULL, timestamp DATETIME)"
    )
    conn.executemany(
        "INSERT INTO semantic_memories (text, embedding_json, timestamp) VALUES (?,?,?)",
        filas,
    )
    conn.commit()
    conn.close()


def _vector(dims=mm.EMBEDDING_DIMS):
    return json.dumps([0.1] * dims)


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Monta un proyecto de mentira con el destino y los cuatro orígenes."""
    raiz = tmp_path
    (raiz / "ai").mkdir()
    users = raiz / "users_data"
    users.mkdir()
    (users / "111").mkdir()
    (users / "intruso").mkdir()

    unified = str(raiz / "ai" / "unified_memory.db")
    _crear_unified(unified)

    _crear_pares(str(raiz / "ai" / "memory.db"), "jarvis_response",
                 [("hola", "buenas", "2026-01-01")])
    _crear_semanticas(str(raiz / "ai" / "semantic_memory.db"),
                      [("dato viejo", _vector(), "2026-01-01")])
    _crear_pares(str(users / "111" / "memory.db"), "response",
                 [("pregunta", "respuesta", "2026-02-01")])
    _crear_semanticas(str(users / "111" / "semantic_memory.db"),
                      [("dato de telegram", _vector(), "2026-02-01")])
    # Carpeta de alguien que no está autorizado: no debe migrarse nada suyo.
    _crear_semanticas(str(users / "intruso" / "semantic_memory.db"),
                      [("SECRETO_DEL_INTRUSO", _vector(), "2026-02-01")])

    monkeypatch.setattr(mm, "_PROJECT_ROOT", str(raiz))
    monkeypatch.setattr(mm, "UNIFIED_DB", unified)
    monkeypatch.setattr(mm, "USERS_DIR", str(users))
    monkeypatch.setattr(mm, "_carpetas_del_dueno", lambda: ["111"])
    return {"raiz": raiz, "unified": unified, "users": users}


def _filas(unified):
    conn = sqlite3.connect(unified)
    filas = conn.execute(
        "SELECT user_id, text, embedding_json, category, source, conversation_id, role "
        "FROM memories"
    ).fetchall()
    conn.close()
    return filas


# ── Lo que no puede fallar ──────────────────────────────────────────

def test_no_duplica_al_repetirse(entorno):
    primera = mm.migrate()
    total_tras_primera = len(_filas(entorno["unified"]))

    segunda = mm.migrate()

    assert primera["total_insertado"] > 0
    assert segunda["total_insertado"] == 0
    assert len(_filas(entorno["unified"])) == total_tras_primera
    assert len(segunda["omitidos"]) == 4


def test_no_borra_ni_modifica_los_origenes(entorno):
    origenes = [
        entorno["raiz"] / "ai" / "memory.db",
        entorno["raiz"] / "ai" / "semantic_memory.db",
        entorno["users"] / "111" / "memory.db",
        entorno["users"] / "111" / "semantic_memory.db",
    ]
    antes = {str(p): p.stat().st_size for p in origenes}

    mm.migrate()

    for p in origenes:
        assert p.exists(), f"{p} fue borrado"
        assert p.stat().st_size == antes[str(p)], f"{p} fue modificado"


def test_no_migra_carpetas_de_terceros(entorno, monkeypatch):
    """La carpeta de una identidad no autorizada no puede acabar en la memoria del dueño."""
    monkeypatch.setattr(mm, "_carpetas_del_dueno", lambda: ["111"])

    mm.migrate()

    textos = [f[1] for f in _filas(entorno["unified"])]
    assert not any("SECRETO_DEL_INTRUSO" in t for t in textos)


def test_el_simulacro_no_escribe_nada(entorno):
    informe = mm.migrate(dry_run=True)

    assert informe["total_insertado"] > 0    # informa lo que haría
    assert _filas(entorno["unified"]) == []  # pero no escribió


# ── Fidelidad de los datos ──────────────────────────────────────────

def test_todo_queda_bajo_el_usuario_canonico(entorno):
    from core.user_identity import OWNER_USER_ID

    mm.migrate()

    assert {f[0] for f in _filas(entorno["unified"])} == {OWNER_USER_ID}


def test_un_par_de_conversacion_produce_dos_turnos_enlazados(entorno):
    mm.migrate()

    pares = [f for f in _filas(entorno["unified"]) if f[6] in ("user", "assistant")]
    del_ai = [f for f in pares if f[4] == "migracion:ai_memory"]

    assert len(del_ai) == 2
    assert {f[6] for f in del_ai} == {"user", "assistant"}
    # Comparten conversation_id: son el mismo intercambio.
    assert len({f[5] for f in del_ai}) == 1
    assert {f[3] for f in del_ai} == {"interaction"}


def test_los_embeddings_validos_se_conservan(entorno):
    mm.migrate()

    semanticas = [f for f in _filas(entorno["unified"]) if f[4].endswith("semantic")]

    assert len(semanticas) == 2
    for fila in semanticas:
        assert fila[2] is not None
        assert len(json.loads(fila[2])) == mm.EMBEDDING_DIMS


def test_un_embedding_de_otra_dimension_no_corrompe_la_busqueda(entorno):
    """La fila se migra igual, pero sin vector: mejor sin buscar que buscando mal."""
    _crear_semanticas(
        str(entorno["raiz"] / "ai" / "semantic_memory_raro.db"),
        [("texto raro", _vector(dims=99), "2026-01-01")],
    )
    filas = mm._leer_semanticas(str(entorno["raiz"] / "ai" / "semantic_memory_raro.db"))

    preparadas, descartados = mm._preparar_semanticas(filas, "owner", "x")

    assert descartados == 1
    assert preparadas[0]["embedding_json"] is None
    assert preparadas[0]["text"] == "texto raro"


def test_las_filas_del_escritorio_pasan_al_usuario_canonico(entorno):
    from core.user_identity import LEGACY_DESKTOP_USER_ID, OWNER_USER_ID

    conn = sqlite3.connect(entorno["unified"])
    conn.execute(
        "INSERT INTO memories (user_id, text, timestamp, source) VALUES (?,?,?,?)",
        (LEGACY_DESKTOP_USER_ID, "recuerdo del escritorio", "2026-03-01", "desktop"),
    )
    conn.commit()
    conn.close()

    informe = mm.migrate()

    assert informe["reasignadas_del_escritorio"] == 1
    assert {f[0] for f in _filas(entorno["unified"])} == {OWNER_USER_ID}


def test_el_historial_pesa_menos_que_una_memoria_deliberada(entorno):
    """El historial en crudo no debe desplazar a lo que se guardó a propósito."""
    mm.migrate()

    conn = sqlite3.connect(entorno["unified"])
    interaccion = conn.execute(
        "SELECT importance FROM memories WHERE category='interaction' LIMIT 1"
    ).fetchone()[0]
    semantica = conn.execute(
        "SELECT importance FROM memories WHERE category='general' LIMIT 1"
    ).fetchone()[0]
    conn.close()

    assert interaccion < semantica


# ── Degradación ─────────────────────────────────────────────────────

def test_un_origen_ausente_no_rompe_la_migracion(entorno):
    os.unlink(str(entorno["raiz"] / "ai" / "memory.db"))

    informe = mm.migrate()

    assert informe["origenes"]["ai_memory"] == 0
    assert informe["total_insertado"] > 0     # el resto sí se migró


def test_un_origen_corrupto_no_rompe_la_migracion(entorno):
    with open(str(entorno["raiz"] / "ai" / "semantic_memory.db"), "wb") as f:
        f.write(b"esto no es una base de datos")

    informe = mm.migrate()

    assert informe["origenes"]["ai_semantic"] == 0
    assert informe["total_insertado"] > 0


def test_sin_destino_no_hace_nada(entorno, monkeypatch):
    monkeypatch.setattr(mm, "UNIFIED_DB", str(entorno["raiz"] / "no_existe.db"))

    informe = mm.migrate()

    assert informe["error"] == "destino_inexistente"
    assert informe["total_insertado"] == 0
