"""
tests/test_aviso_respuesta_lista.py
REQ-057 — aviso del sistema cuando la respuesta llega y la ventana no está al frente
(`Bridge._avisar_si_no_esta_mirando`).
"""

from unittest.mock import MagicMock

import pytest

import ui.webview.bridge as bridge_module
from core import notificaciones
from ui.webview.bridge import Bridge


@pytest.fixture
def bridge(qtbot):
    b = Bridge(MagicMock())
    return b


@pytest.fixture
def avisos(monkeypatch):
    recibidos = []
    monkeypatch.setattr(notificaciones, "notificar",
                        lambda titulo, mensaje="", nivel="info": recibidos.append((titulo, mensaje, nivel)))
    return recibidos


def _ventana(bridge, visible=True, minimizada=False, activa=True):
    bridge._main_window.isVisible.return_value = visible
    bridge._main_window.isMinimized.return_value = minimizada
    bridge._main_window.isActiveWindow.return_value = activa


def test_avisa_si_tardo_y_la_ventana_no_esta_activa(bridge, avisos, monkeypatch):
    _ventana(bridge, activa=False)
    bridge._turno_inicio = 100.0
    monkeypatch.setattr(bridge_module.time, "monotonic", lambda: 100.0 + 20)

    bridge._avisar_si_no_esta_mirando("Listo: el informe   quedó en el Escritorio.\nSegunda línea.")

    assert avisos == [("Respuesta lista", "Listo: el informe quedó en el Escritorio. Segunda línea.", "ok")]


def test_no_avisa_si_la_ventana_esta_a_la_vista(bridge, avisos, monkeypatch):
    _ventana(bridge, activa=True)
    bridge._turno_inicio = 100.0
    monkeypatch.setattr(bridge_module.time, "monotonic", lambda: 100.0 + 20)

    bridge._avisar_si_no_esta_mirando("hola")

    assert avisos == []


def test_no_avisa_por_una_respuesta_rapida(bridge, avisos, monkeypatch):
    _ventana(bridge, activa=False)
    bridge._turno_inicio = 100.0
    monkeypatch.setattr(bridge_module.time, "monotonic", lambda: 100.0 + 3)

    bridge._avisar_si_no_esta_mirando("hola")

    assert avisos == []


def test_minimizada_u_oculta_cuenta_como_no_mirando(bridge, avisos, monkeypatch):
    bridge._turno_inicio = 0.0
    monkeypatch.setattr(bridge_module.time, "monotonic", lambda: 60.0)

    _ventana(bridge, minimizada=True, activa=True)
    bridge._avisar_si_no_esta_mirando("uno")
    _ventana(bridge, visible=False, activa=True)
    bridge._avisar_si_no_esta_mirando("dos")

    assert [a[1] for a in avisos] == ["uno", "dos"]


def test_el_mensaje_largo_se_recorta(bridge, avisos, monkeypatch):
    _ventana(bridge, activa=False)
    bridge._turno_inicio = 0.0
    monkeypatch.setattr(bridge_module.time, "monotonic", lambda: 60.0)

    bridge._avisar_si_no_esta_mirando("x" * 500)

    assert len(avisos[0][1]) == 141 and avisos[0][1].endswith("…")


def test_sin_turno_iniciado_no_avisa(bridge, avisos):
    _ventana(bridge, activa=False)
    bridge._turno_inicio = None
    bridge._avisar_si_no_esta_mirando("hola")
    assert avisos == []
