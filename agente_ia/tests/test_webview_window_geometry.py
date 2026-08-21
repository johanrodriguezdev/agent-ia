"""
tests/test_webview_window_geometry.py
REQ-015/CA-04 — `ui/webview/window_geometry.py::fit_size_to_screen()`.

Función pura, sin Qt en su firma — mismo espíritu que el fix ya validado en el stash de
REQ-014 para el bug #2 (ventana más alta que el área disponible), ahora testeado desde
cero acá (arquitectura-015.md §1, fila CA-04).
"""

import pytest

from ui.webview.window_geometry import fit_size_to_screen


def test_pantalla_normal_1920x1080():
    width, height, x, y = fit_size_to_screen((0, 0, 1920, 1080))
    assert width <= 1920
    assert height <= 1080
    assert x >= 0
    assert y >= 0
    assert x + width <= 1920
    assert y + height <= 1080


def test_resultado_es_fraction_del_area_disponible():
    width, height, _x, _y = fit_size_to_screen((0, 0, 2000, 1000), minimum=(100, 100), fraction=0.85)
    assert width == int(2000 * 0.85)
    assert height == int(1000 * 0.85)


def test_pantalla_menor_al_minimo_usa_area_completa_sin_desbordar():
    """CA-04 — nunca debe exceder la pantalla, ni siquiera cuando `minimum` es mayor que
    el área disponible (caso borde explícito de la SPEC)."""
    width, height, x, y = fit_size_to_screen((0, 0, 800, 500), minimum=(1024, 640))
    assert width <= 800
    assert height <= 500
    assert x >= 0
    assert y >= 0
    assert x + width <= 800
    assert y + height <= 500


def test_ventana_queda_centrada():
    width, height, x, y = fit_size_to_screen((0, 0, 1920, 1080), minimum=(1024, 640), fraction=0.5)
    assert x == (1920 - width) // 2
    assert y == (1080 - height) // 2


def test_respeta_el_origen_de_pantalla_no_primaria():
    """Multi-monitor: la pantalla secundaria puede tener origen != (0, 0) — el resultado
    debe quedar dentro de SU área, no de (0, 0)."""
    width, height, x, y = fit_size_to_screen((1920, 0, 1920, 1080))
    assert x >= 1920
    assert x + width <= 1920 + 1920
    assert y >= 0
    assert y + height <= 1080


@pytest.mark.parametrize("scale_area", [
    (0, 0, 1366, 768),   # portátil típico, escala 100%
    (0, 0, 2560, 1440),  # monitor 1440p
    (0, 0, 3840, 2160),  # 4K
    (0, 0, 1024, 640),   # exactamente el mínimo
])
def test_nunca_excede_el_area_disponible(scale_area):
    width, height, x, y = fit_size_to_screen(scale_area)
    screen_x, screen_y, screen_w, screen_h = scale_area
    assert x >= screen_x
    assert y >= screen_y
    assert x + width <= screen_x + screen_w
    assert y + height <= screen_y + screen_h


def test_minimum_por_defecto_es_1024x640():
    width, height, _x, _y = fit_size_to_screen((0, 0, 100, 100))
    # área disponible menor que el mínimo por defecto -> usa el área completa (100x100)
    assert width == 100
    assert height == 100
