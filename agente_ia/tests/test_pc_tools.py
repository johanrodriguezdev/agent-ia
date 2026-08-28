"""
tests/test_pc_tools.py
Pruebas de las herramientas de control del escritorio.

Nacen de un caso real: estar lejos del PC, pedir una captura por Telegram para ver en qué
punto quedó el trabajo, y a partir de eso escribir algo y confirmarlo. Eran tres pasos
encadenados con contexto entre ellos — algo que un modelo con herramientas sabe hacer y un
clasificador de intents, que resuelve una acción por mensaje, no.

Lo que protege esta suite: que estén disponibles donde hacen falta, que **sigan pidiendo
confirmación** allí, y que no se filtren a canales donde nadie las autorizó.

Ningún test mueve el ratón ni escribe de verdad: `pyautogui` va simulado.
"""

import pytest

import agents.tool_registry as tr
from core.security_manager import ChannelType, RiskLevel, security_manager


# ── Clasificación ───────────────────────────────────────────────────

def test_mirar_es_verde_y_actuar_es_amarillo():
    """Una captura observa; escribir y hacer clic cambian el estado de la máquina."""
    assert security_manager._actions["pc_screenshot"] == RiskLevel.GREEN
    assert security_manager._actions["pc_type"] == RiskLevel.YELLOW
    assert security_manager._actions["pc_key"] == RiskLevel.YELLOW
    assert security_manager._actions["pc_click"] == RiskLevel.YELLOW


def test_estan_disponibles_desde_telegram():
    """El caso de uso completo: sin esto, el flujo desde el móvil es imposible."""
    for accion in ("pc_screenshot", "pc_type", "pc_key", "pc_click"):
        assert security_manager.is_action_allowed(accion, ChannelType.TELEGRAM), accion


def test_siguen_siendo_amarillas_en_telegram():
    """Habilitadas NO significa rebajadas: cada una pregunta por el chat antes de actuar."""
    assert security_manager._actions["pc_type"] == RiskLevel.YELLOW


def test_no_se_filtran_a_discord():
    """La excepción se declaró para Telegram; otro canal no la hereda."""
    assert not security_manager.is_action_allowed("pc_type", ChannelType.DISCORD)
    assert not security_manager.is_action_allowed("pc_click", ChannelType.DISCORD)


def test_no_se_filtran_a_la_voz():
    """Por voz no se ve la pantalla ni se puede comprobar sobre qué se escribe."""
    assert not security_manager.is_action_allowed("pc_type", ChannelType.VOICE)


# ── Comportamiento ──────────────────────────────────────────────────

def test_escribir_sin_texto_avisa_en_vez_de_escribir_vacio():
    assert "qué texto" in tr._pc_type_invoke({})


def test_pulsar_sin_tecla_avisa():
    assert "qué tecla" in tr._pc_key_invoke({})


def test_hacer_clic_sin_coordenadas_avisa():
    assert "coordenadas" in tr._pc_click_invoke({})
    assert "coordenadas" in tr._pc_click_invoke({"x": "no es un numero", "y": 5})


def test_escribir_llega_al_teclado(monkeypatch):
    escrito = {}
    monkeypatch.setattr(
        "automation.pc_controller.type_text",
        lambda t: escrito.setdefault("texto", t) or "ok",
    )

    tr._pc_type_invoke({"text": "continúa"})

    assert escrito["texto"] == "continúa"


def test_una_combinacion_se_manda_como_combinacion(monkeypatch):
    import sys
    from unittest.mock import MagicMock

    fake = MagicMock()
    monkeypatch.setitem(sys.modules, "pyautogui", fake)

    tr._pc_key_invoke({"key": "ctrl+s"})

    fake.hotkey.assert_called_once_with("ctrl", "s")


def test_una_tecla_suelta_se_manda_como_tecla(monkeypatch):
    import sys
    from unittest.mock import MagicMock

    fake = MagicMock()
    monkeypatch.setitem(sys.modules, "pyautogui", fake)

    tr._pc_key_invoke({"key": "enter"})

    fake.press.assert_called_once_with("enter")


def test_un_fallo_del_teclado_no_propaga(monkeypatch):
    import sys
    from unittest.mock import MagicMock

    fake = MagicMock()
    fake.press.side_effect = RuntimeError("sin permisos")
    monkeypatch.setitem(sys.modules, "pyautogui", fake)

    resultado = tr._pc_key_invoke({"key": "enter"})

    assert "No pude pulsar" in resultado


# ── El modelo puede encadenarlas ────────────────────────────────────

def test_el_modelo_ve_las_cuatro_herramientas():
    """Sin estar registradas como tools, el modelo no podía usarlas: solo existían como
    intents, y el clasificador resuelve UNA acción por mensaje."""
    nombres = tr.list_tool_names()

    for esperada in ("pc_screenshot", "pc_type", "pc_key", "pc_click"):
        assert esperada in nombres


def test_la_descripcion_avisa_de_mirar_antes_de_escribir():
    """El modelo tiene que saber que el texto va a donde esté el foco, no a un sitio fijo."""
    spec = tr.get_tool("pc_type")

    assert "foco" in spec.description
    assert "pc_screenshot" in spec.description
