"""
tests/test_exportar_chat.py
REQ-056 — `core/exportar_chat.py` (una conversación como .md), la herramienta
`chat_export_current` y el slot `Bridge.export_conversation`.
"""

from datetime import datetime
from types import SimpleNamespace

import pytest

from core import exportar_chat


# --------------------------------------------------------------------------- nombre

def test_el_nombre_lleva_fecha_titulo_y_sin_caracteres_prohibidos():
    cuando = datetime(2026, 9, 20, 1, 15)
    assert exportar_chat.nombre_de_archivo("Bibliografía de la tesis", cuando) == \
        "2026-09-20 Bibliografía de la tesis.md"
    assert exportar_chat.nombre_de_archivo('¿qué es "esto"? C:\\x/y|z', cuando) == \
        "2026-09-20 ¿qué es esto C x y z.md"
    assert exportar_chat.nombre_de_archivo("", cuando) == "2026-09-20 Conversación.md"
    largo = exportar_chat.nombre_de_archivo("a" * 200, cuando)
    assert len(largo) <= len("2026-09-20 ") + exportar_chat._MAX_NOMBRE + len(".md")


# --------------------------------------------------------------------------- markdown

def _turno(rol, texto, ts="2026-09-20T01:15:00"):
    return SimpleNamespace(role=rol, text=texto, timestamp=ts)


def test_el_markdown_lleva_titulo_fecha_y_cada_turno_con_quien_hablo():
    turnos = [
        _turno("user", "¿qué es un webhook?"),
        _turno("assistant", "Una URL a la que otro sistema **avisa**.", "2026-09-20T01:16:30"),
    ]
    md = exportar_chat.conversacion_a_markdown(turnos, "Webhooks", quien_usuario="Johan",
                                               quien_agente="Orion")
    assert md.startswith("# Webhooks\n")
    assert "_20 de septiembre de 2026, 01:15 — 20 de septiembre de 2026, 01:16_" in md
    assert "2 mensajes." in md
    assert "**Johan:**\n\n¿qué es un webhook?" in md
    assert "**Orion:**\n\nUna URL a la que otro sistema **avisa**." in md
    assert md.endswith("---\n")


def test_los_adjuntos_van_como_nombre_de_archivo_no_como_ruta():
    turnos = [_turno("user", "mirá esto\n\n[Imagen adjunta: C:\\Users\\j\\captura.png]"),
              _turno("assistant", "Es un error 404.")]
    md = exportar_chat.conversacion_a_markdown(turnos, "Error")
    assert "📎 captura.png" in md
    assert "C:\\Users" not in md
    assert "[Imagen adjunta" not in md


def test_filas_que_no_son_turnos_se_ignoran_y_un_texto_vacio_se_marca():
    turnos = [_turno("system", "x"), _turno("user", ""), _turno("assistant", "ok")]
    md = exportar_chat.conversacion_a_markdown(turnos, "T")
    assert "2 mensajes." in md
    assert "_(sin texto)_" in md


# --------------------------------------------------------------------------- exportar

@pytest.fixture
def memoria_falsa(monkeypatch):
    from ai.memory_manager import memory

    estado = {"turnos": [_turno("user", "hola, ¿me ayudás con la tesis?"),
                         _turno("assistant", "Claro.")], "titulo": ""}
    monkeypatch.setattr(memory, "get_conversation_turns",
                        lambda cid, user_id="default", limit=200: estado["turnos"] if cid == "conv-1" else [])
    monkeypatch.setattr(memory, "get_conversation_title",
                        lambda cid, user_id="default": estado["titulo"])
    return estado


def test_exportar_escribe_el_md_en_la_carpeta_pedida_con_titulo_derivado(memoria_falsa, tmp_path, monkeypatch):
    import core.documentos as documentos

    monkeypatch.setattr(documentos, "_bases_permitidas", lambda: [tmp_path])
    monkeypatch.setattr(documentos, "CARPETAS_VEDADAS", frozenset())

    ruta = exportar_chat.exportar("conv-1", "owner", carpeta=str(tmp_path))

    assert ruta.startswith(str(tmp_path))
    assert ruta.endswith("hola, ¿me ayudás con la tesis.md")
    contenido = open(ruta, encoding="utf-8").read()
    assert contenido.startswith("# hola, ¿me ayudás con la tesis?")


def test_exportar_usa_el_titulo_propio_y_el_nombre_pedido(memoria_falsa, tmp_path, monkeypatch):
    import core.documentos as documentos

    monkeypatch.setattr(documentos, "_bases_permitidas", lambda: [tmp_path])
    monkeypatch.setattr(documentos, "CARPETAS_VEDADAS", frozenset())
    memoria_falsa["titulo"] = "Tesis: bibliografía"

    ruta = exportar_chat.exportar("conv-1", "owner", carpeta=str(tmp_path), nombre="tesis")

    assert ruta.endswith("tesis.md")
    assert open(ruta, encoding="utf-8").read().startswith("# Tesis: bibliografía")
    # Nunca se pisa: la segunda vez sale «tesis (2).md».
    otra = exportar_chat.exportar("conv-1", "owner", carpeta=str(tmp_path), nombre="tesis")
    assert otra.endswith("tesis (2).md")


def test_exportar_una_conversacion_sin_turnos_se_rechaza(memoria_falsa, tmp_path, monkeypatch):
    from core.documentos import DocumentoRechazado

    with pytest.raises(DocumentoRechazado):
        exportar_chat.exportar("no-existe", "owner", carpeta=str(tmp_path))


# --------------------------------------------------------------------------- herramienta

def test_la_herramienta_es_amarilla_y_solo_de_escritorio():
    from agents import tool_registry as registry
    from core.security_manager import DESKTOP_ONLY_ACTIONS, ChannelType, RiskLevel, security_manager

    spec = registry.get_tool("chat_export_current")
    assert spec.risk_level is RiskLevel.YELLOW
    assert "chat_export_current" in DESKTOP_ONLY_ACTIONS
    assert not security_manager.is_action_allowed("chat_export_current", ChannelType.TELEGRAM)


def test_la_herramienta_exporta_el_chat_abierto_y_avisa_si_no_hay(memoria_falsa, tmp_path, monkeypatch):
    from agents import tool_registry as registry
    from core import conversacion_activa
    import core.documentos as documentos

    monkeypatch.setattr(documentos, "_bases_permitidas", lambda: [tmp_path])
    monkeypatch.setattr(documentos, "CARPETAS_VEDADAS", frozenset())
    invoke = registry.get_tool("chat_export_current").invoke

    conversacion_activa.fijar(None)
    assert "No hay ningún chat abierto" in invoke({})

    conversacion_activa.fijar("conv-1")
    try:
        resultado = invoke({"carpeta": str(tmp_path), "nombre": "charla"})
    finally:
        conversacion_activa.fijar(None)
    assert resultado.startswith("Conversación guardada en ")
    assert resultado.rstrip(".").endswith("charla.md")


def test_la_herramienta_devuelve_el_rechazo_como_texto(memoria_falsa, monkeypatch):
    from agents import tool_registry as registry
    from core import conversacion_activa

    conversacion_activa.fijar("conv-1")
    try:
        resultado = registry.get_tool("chat_export_current").invoke({"carpeta": "C:\\Windows\\System32"})
    finally:
        conversacion_activa.fijar(None)
    assert "No creo archivos" in resultado or "no es" in resultado
