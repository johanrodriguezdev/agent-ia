"""
tests/test_image_look.py
REQ-062 — la herramienta `image_look`: mirar una imagen del disco por instrucción.
"""

import pytest

from agents import tool_registry as registry
from core.security_manager import DESKTOP_ONLY_ACTIONS, ChannelType, RiskLevel, security_manager

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


@pytest.fixture
def captura(tmp_path, monkeypatch):
    from core import imagenes

    import core.documentos as documentos

    monkeypatch.setattr(imagenes, "_raices_para_mirar", lambda: [str(tmp_path)])
    monkeypatch.setattr(documentos, "CARPETAS_VEDADAS", frozenset())   # tmp_path vive bajo AppData
    ruta = tmp_path / "error.png"
    Image.new("RGB", (8, 8), (255, 0, 0)).save(ruta)
    return str(ruta)


def test_es_verde_y_solo_de_escritorio():
    spec = registry.get_tool("image_look")
    assert spec.risk_level is RiskLevel.GREEN
    assert "image_look" in DESKTOP_ONLY_ACTIONS
    assert not security_manager.is_action_allowed("image_look", ChannelType.TELEGRAM)


def test_manda_la_imagen_al_modelo_con_la_pregunta_y_devuelve_lo_que_vio(captura, monkeypatch):
    import agents.tool_registry as tr

    llamadas = []

    def _fake(messages, system_prompt, image_path=None, tools=None, tarea="general", **kw):
        llamadas.append({"messages": messages, "image_path": image_path, "tarea": tarea})
        return "Un ModuleNotFoundError: falta 'anthropic'."

    monkeypatch.setattr("ai.llm_provider.generate_response", _fake)

    resultado = tr.get_tool("image_look").invoke({"path": captura, "question": "¿qué error es?"})

    assert llamadas[0]["image_path"] == captura
    assert llamadas[0]["messages"][0]["content"] == "¿qué error es?"
    assert resultado.startswith("Imagen «error.png»:")
    assert "ModuleNotFoundError" in resultado


def test_sin_pregunta_describe_la_imagen(captura, monkeypatch):
    preguntas = []
    monkeypatch.setattr("ai.llm_provider.generate_response",
                        lambda messages, *a, **k: preguntas.append(messages[0]["content"]) or "Un cuadro rojo.")
    registry.get_tool("image_look").invoke({"path": captura})
    assert preguntas == ["¿Qué hay en esta imagen?"]


def test_una_ruta_rechazada_vuelve_como_texto(captura, tmp_path):
    resultado = registry.get_tool("image_look").invoke({"path": str(tmp_path / "no-esta.png")})
    assert "No encuentro" in resultado


def test_sin_modelo_de_vision_lo_dice_y_apunta_a_configuracion(captura, monkeypatch):
    from ai.llm_provider import SIN_PROVEEDOR

    monkeypatch.setattr("ai.llm_provider.generate_response", lambda *a, **k: SIN_PROVEEDOR)
    resultado = registry.get_tool("image_look").invoke({"path": captura})
    assert "Ver imágenes" in resultado

    def _explota(*a, **k):
        raise RuntimeError("sin red")

    monkeypatch.setattr("ai.llm_provider.generate_response", _explota)
    assert "no respondió" in registry.get_tool("image_look").invoke({"path": captura})
