"""
tests/test_titulos.py
REQ-053 — el título corto de cada conversación (`core/titulos.py`).

Lo que protege esta suite:
- El primer intercambio de una conversación le pide al modelo un título de 3-6 palabras,
  con `tarea="ligera"` y tope de salida chico, y lo guarda como título propio.
- Un mensaje corto no gasta una llamada: ya es el título.
- Un título puesto a mano (o uno anterior) no se pisa.
- Lo que el modelo devuelve se limpia (comillas, «Título:», punto final, líneas de más).
- Un modelo caído deja el título derivado de siempre y NUNCA lanza.
- El bridge lo dispara solo en el primer turno, después de guardar.

Sin red: `generate_response` sustituido; DB en `tmp_path`.
"""

import json
from unittest.mock import MagicMock

import numpy as np
import pytest

import ai.memory_manager as memory_manager
from ai.memory_manager import memory
from core import titulos
from core.user_identity import OWNER_USER_ID

LARGO = "Necesito que me ayudes a organizar la bibliografía de la tesis sobre agentes"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_manager, "DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setattr(memory, "_get_embedding", lambda text: np.zeros(384, dtype=np.float32))
    memory._init_db()
    yield


@pytest.fixture
def modelo(monkeypatch):
    """`generate_response` falso: registra con qué se lo llamó y contesta lo que se le diga."""
    llamadas = []
    estado = {"respuesta": "Bibliografía de la tesis"}

    def _fake(messages, system_prompt, image_path=None, tools=None, tarea="general", **kw):
        from ai import llm_provider
        llamadas.append({"messages": messages, "system": system_prompt, "tarea": tarea,
                         "tope": llm_provider._max_tokens_salida()})
        if isinstance(estado["respuesta"], Exception):
            raise estado["respuesta"]
        return estado["respuesta"]

    monkeypatch.setattr("ai.llm_provider.generate_response", _fake)
    return llamadas, estado


# ── limpieza ────────────────────────────────────────────────────────

@pytest.mark.parametrize("crudo,esperado", [
    ("Bibliografía de la tesis", "Bibliografía de la tesis"),
    ('"Bibliografía de la tesis."', "Bibliografía de la tesis"),
    ("Título: Bibliografía de la tesis\nOtra línea", "Bibliografía de la tesis"),
    ("«Organizar la bibliografía»", "Organizar la bibliografía"),
    ("uno dos tres cuatro cinco seis siete ocho", "uno dos tres cuatro cinco seis"),
    ("", ""),
    (None, ""),
    ("   \n  ", ""),
])
def test_el_titulo_se_limpia(crudo, esperado):
    assert titulos.limpiar(crudo) == esperado


def test_un_mensaje_corto_no_pide_titulo():
    assert not titulos.hace_falta_titulo("abrí chrome")
    assert titulos.hace_falta_titulo(LARGO)


# ── generar ─────────────────────────────────────────────────────────

def test_generar_usa_la_tarea_ligera_con_tope_chico(modelo):
    llamadas, _ = modelo

    assert titulos.generar(LARGO, "Claro, empecemos por…") == "Bibliografía de la tesis"

    assert len(llamadas) == 1
    assert llamadas[0]["tarea"] == "ligera"
    assert llamadas[0]["tope"] == titulos._TOKENS_DE_SALIDA
    assert LARGO in llamadas[0]["messages"][0]["content"]


def test_un_modelo_caido_no_lanza(modelo):
    _, estado = modelo
    estado["respuesta"] = RuntimeError("sin red")
    assert titulos.generar(LARGO, "…") == ""


# ── titular_si_corresponde ──────────────────────────────────────────

def _con_turno(cid, usuario=LARGO):
    memory.store_turn(usuario, "Claro, empecemos.", cid, user_id=OWNER_USER_ID)


def test_pone_el_titulo_en_la_conversacion(db, modelo):
    _con_turno("c1")

    assert titulos.titular_si_corresponde("c1", LARGO, "Claro", user_id=OWNER_USER_ID)

    filas = memory.list_conversations(user_id=OWNER_USER_ID)
    assert filas[0].title == "Bibliografía de la tesis"
    assert memory.get_conversation_title("c1", user_id=OWNER_USER_ID) == "Bibliografía de la tesis"


def test_no_pisa_un_titulo_puesto_a_mano(db, modelo):
    llamadas, _ = modelo
    _con_turno("c1")
    memory.rename_conversation("c1", "Mi tesis", user_id=OWNER_USER_ID)

    assert not titulos.titular_si_corresponde("c1", LARGO, "Claro", user_id=OWNER_USER_ID)

    assert llamadas == []
    assert memory.get_conversation_title("c1", user_id=OWNER_USER_ID) == "Mi tesis"


def test_con_un_mensaje_corto_no_gasta_la_llamada(db, modelo):
    llamadas, _ = modelo
    _con_turno("c1", "qué hora es")
    assert not titulos.titular_si_corresponde("c1", "qué hora es", "Las 5", user_id=OWNER_USER_ID)
    assert llamadas == []


def test_una_respuesta_inutil_del_modelo_deja_el_titulo_derivado(db, modelo):
    _, estado = modelo
    estado["respuesta"] = '""'
    _con_turno("c1")

    assert not titulos.titular_si_corresponde("c1", LARGO, "Claro", user_id=OWNER_USER_ID)
    assert memory.list_conversations(user_id=OWNER_USER_ID)[0].title.startswith("Necesito que me ayudes")


# ── bridge ──────────────────────────────────────────────────────────

def test_el_bridge_titula_solo_el_primer_turno(qtbot, monkeypatch, db, modelo):
    import ui.webview.bridge as bridge_module
    from types import SimpleNamespace
    from ui.webview.bridge import Bridge

    def _fake_run_async(fn, on_done=None, on_error=None, *args, **kwargs):
        resultado = fn(*args, **kwargs)
        if on_done:
            on_done(resultado)
    monkeypatch.setattr(bridge_module, "run_async", _fake_run_async)
    monkeypatch.setattr("core.resolution.resolve",
                        lambda *a, **k: SimpleNamespace(text="Claro, empecemos.", matched_by="llm"))
    llamadas, estado = modelo
    bridge = Bridge(MagicMock())

    bridge.send_message(LARGO)
    cid = bridge._conversation_id
    assert memory.get_conversation_title(cid, user_id=OWNER_USER_ID) == "Bibliografía de la tesis"
    assert len(llamadas) == 1

    # Segundo turno de la misma conversación: nada que titular.
    estado["respuesta"] = "Otro título"
    bridge.send_message(LARGO + " y también las citas")
    assert len(llamadas) == 1
    assert memory.get_conversation_title(cid, user_id=OWNER_USER_ID) == "Bibliografía de la tesis"


def test_un_error_del_proveedor_no_se_vuelve_titulo(modelo):
    """Revisión de la noche del 2026-09-20: «Error: Ollama no está ejecutándose…» o el
    texto de "sin proveedor" son strings, y `limpiar()` los recortaba a seis palabras como
    título permanente — y como ya había título propio, no se volvía a intentar."""
    from ai.llm_provider import SIN_PROVEEDOR

    _, estado = modelo
    estado["respuesta"] = "Error: Ollama no está ejecutándose. Inícialo con 'ollama serve'."
    assert titulos.generar(LARGO, "…") == ""
    estado["respuesta"] = SIN_PROVEEDOR
    assert titulos.generar(LARGO, "…") == ""
