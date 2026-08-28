"""
tests/test_screen_vision.py
Pruebas de `os_integration/screen_vision.py` — mirar la pantalla y actuar sobre ella.

El invariante que sostiene todo esto: **una coordenada solo vale para la captura de la que
salió**. Si entre mirar y pulsar la pantalla cambió, ese clic aterriza en otro sitio, y con
el ratón eso no es un error recuperable: es haber pulsado algo que nadie eligió. Es la
comprobación que OpenClaw hace atando cada acción al identificador de su captura, y la
razón de que la mitad de esta suite sea sobre rechazar clics.

Ningún test toma capturas reales ni llama a un modelo con visión.
"""

import time

import pytest

from os_integration import screen_vision as sv


@pytest.fixture(autouse=True)
def _sin_captura_previa():
    sv._ultima = None
    yield
    sv._ultima = None


def _captura_falsa(frame_id="f000001", edad=0.0, ancho=1920, alto=1080):
    captura = sv.Captura(
        frame_id=frame_id, ruta="/tmp/x.png", ancho=ancho, alto=alto,
        tomada_en=time.monotonic() - edad,
    )
    sv._ultima = captura
    return captura


# ── Rechazar clics que no se pueden justificar ──────────────────────

def test_sin_ninguna_captura_no_se_hace_clic():
    valido, motivo = sv.validar_para_clic("f000001")

    assert valido is False
    assert "No hay ninguna captura" in motivo


def test_sin_identificador_no_se_hace_clic():
    """Unas coordenadas sueltas no dicen respecto a qué pantalla se midieron."""
    _captura_falsa()

    valido, motivo = sv.validar_para_clic("")

    assert valido is False
    assert "Falta indicar" in motivo


def test_las_coordenadas_de_una_captura_vieja_se_rechazan():
    """El caso que de verdad importa: se miró, la pantalla cambió, y se iba a pulsar igual."""
    _captura_falsa(frame_id="f000002")

    valido, motivo = sv.validar_para_clic("f000001")

    assert valido is False
    assert "pudo cambiar" in motivo


def test_una_captura_caducada_se_rechaza():
    _captura_falsa(frame_id="f000001", edad=sv.FRESCURA_SEGUNDOS + 5)

    valido, motivo = sv.validar_para_clic("f000001")

    assert valido is False
    assert "segundos" in motivo


def test_con_la_captura_vigente_y_fresca_se_permite():
    _captura_falsa(frame_id="f000001", edad=1.0)

    valido, motivo = sv.validar_para_clic("f000001")

    assert valido is True
    assert motivo == ""


def test_el_plazo_de_frescura_esta_fijado():
    """Alargarlo aumenta la ventana en que la pantalla pudo cambiar bajo los pies."""
    assert sv.FRESCURA_SEGUNDOS == 30.0


# ── Localizar sin visión configurada ────────────────────────────────

def test_sin_proveedor_de_vision_se_dice_claramente(monkeypatch):
    """Degradar con un mensaje entendible, no fallar ni fingir que se vio algo."""
    monkeypatch.setattr(sv, "_hay_vision", lambda: False)
    captura = _captura_falsa()

    coords, motivo = sv.localizar(captura, "el botón Aceptar")

    assert coords is None
    assert "visión" in motivo


def test_describir_sin_vision_avisa(monkeypatch):
    monkeypatch.setattr(sv, "_hay_vision", lambda: False)

    texto = sv.describir(_captura_falsa())

    assert "visión" in texto


# ── Localizar con visión ────────────────────────────────────────────

def _mock_vision(monkeypatch, respuesta):
    monkeypatch.setattr(sv, "_hay_vision", lambda: True)
    monkeypatch.setattr(
        "ai.llm_provider.generate_response",
        lambda *a, **k: respuesta,
    )


def test_se_extraen_las_coordenadas(monkeypatch):
    _mock_vision(monkeypatch, "ENCONTRADO 640,360")
    captura = _captura_falsa()

    coords, motivo = sv.localizar(captura, "el botón Aceptar")

    assert coords == (640, 360)
    assert motivo == ""


def test_si_el_modelo_no_lo_ve_no_se_inventan_coordenadas(monkeypatch):
    """Es preferible decir que no se ve a hacer clic en el sitio equivocado."""
    _mock_vision(monkeypatch, "NO ENCONTRADO")
    captura = _captura_falsa()

    coords, motivo = sv.localizar(captura, "el botón Aceptar")

    assert coords is None
    assert "No encontré" in motivo


def test_unas_coordenadas_fuera_de_pantalla_se_rechazan(monkeypatch):
    """Un modelo puede alucinar dos números, y un clic inventado no se distingue de uno real."""
    _mock_vision(monkeypatch, "ENCONTRADO 9999,8888")
    captura = _captura_falsa(ancho=1920, alto=1080)

    coords, motivo = sv.localizar(captura, "algo")

    assert coords is None
    assert "fuera de la pantalla" in motivo


def test_una_respuesta_sin_coordenadas_no_rompe(monkeypatch):
    _mock_vision(monkeypatch, "Pues creo que está por ahí arriba a la izquierda")
    captura = _captura_falsa()

    coords, motivo = sv.localizar(captura, "algo")

    assert coords is None
    assert "No pude determinar" in motivo


def test_un_fallo_del_modelo_no_propaga(monkeypatch):
    monkeypatch.setattr(sv, "_hay_vision", lambda: True)
    monkeypatch.setattr(
        "ai.llm_provider.generate_response",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sin conexión")),
    )
    captura = _captura_falsa()

    coords, motivo = sv.localizar(captura, "algo")

    assert coords is None
    assert "No pude analizar" in motivo


# ── Integración con la herramienta de clic ──────────────────────────

def test_la_herramienta_de_clic_respeta_la_validacion(monkeypatch):
    import agents.tool_registry as tr

    _captura_falsa(frame_id="f000002")
    hecho = []
    monkeypatch.setattr(
        "automation.pc_controller.click_position",
        lambda x, y: hecho.append((x, y)) or "clic hecho",
    )

    # Coordenadas de una captura que ya no es la vigente.
    resultado = tr._pc_click_invoke({"x": 100, "y": 200, "frame_id": "f000001"})

    assert hecho == []
    assert "pudo cambiar" in resultado


def test_la_herramienta_de_clic_funciona_con_la_captura_vigente(monkeypatch):
    import agents.tool_registry as tr

    _captura_falsa(frame_id="f000001", edad=1.0)
    hecho = []
    monkeypatch.setattr(
        "automation.pc_controller.click_position",
        lambda x, y: hecho.append((x, y)) or "clic hecho",
    )

    tr._pc_click_invoke({"x": 100, "y": 200, "frame_id": "f000001"})

    assert hecho == [(100, 200)]


def test_mirar_es_verde_porque_solo_observa():
    from core.security_manager import RiskLevel, security_manager

    assert security_manager._actions["pc_look"] == RiskLevel.GREEN
