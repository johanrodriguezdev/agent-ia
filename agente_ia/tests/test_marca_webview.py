"""
tests/test_marca_webview.py
REQ-052 — la marca dentro de la interfaz (`ui/webview/frontend/js/marca.js`).

La geometría de los tres anillos vive dos veces: en Python (`ui/webview/app_icon.py`, que
pinta el icono de la app y la bandeja) y en JS (`marca.js`, que la pinta en la barra, en
la pantalla vacía y en el Mapa). Este test parsea el JS y lo compara con las constantes de
Python, igual que `tests/test_webview_theme.py` hace con la paleta: si alguien ajusta la
marca en un lado y no en el otro, acá se nota.

También fija que los tokens del degradado (`--marca-1/2/3`) existen en los dos temas y
que en oscuro son exactamente los del icono de app, para que la marca de la ventana y la
de la barra de tareas sean la misma.
"""

import re
from pathlib import Path

from ui.webview import app_icon
from ui.webview.theme import DARK_TOKENS, LIGHT_TOKENS

_FRONTEND = Path(__file__).resolve().parent.parent / "ui" / "webview" / "frontend"
_MARCA_JS = _FRONTEND / "js" / "marca.js"


def _js():
    return _MARCA_JS.read_text(encoding="utf-8")


def _numeros(texto: str):
    return [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", texto)]


def test_los_anillos_del_js_son_los_del_icono():
    bloque = re.search(r"export const ANILLOS = \[(.*?)\];", _js(), re.S).group(1)
    filas = re.findall(r"\[([^\]]+)\]", bloque)
    anillos = [tuple(_numeros(f)) for f in filas]
    assert anillos == [tuple(float(v) for v in r) for r in app_icon._RINGS]


def test_radio_dasharray_y_nodo_coinciden():
    js = _js()
    radio = float(re.search(r"export const RADIO_ANILLO = ([\d.]+);", js).group(1))
    dasharray = re.search(r'export const DASHARRAY = "([^"]+)";', js).group(1)
    nodo = tuple(_numeros(re.search(r"export const NODO = \[([^\]]+)\];", js).group(1)))

    assert radio == app_icon._RING_R
    assert dasharray == app_icon._RING_DASHARRAY
    assert nodo == tuple(float(v) for v in app_icon._NODE_CENTER)


def test_el_degradado_tiene_los_mismos_puntos_que_el_icono():
    js = _js()
    puntos = dict(re.findall(r"(x1|y1|x2|y2): (\d+)", re.search(r"const DEGRADADO = \{([^}]+)\}", js).group(1)))
    for clave in ("x1", "y1", "x2", "y2"):
        esperado = re.search(rf'{clave}="(\d+)"', app_icon._GRADIENT_DEF).group(1)
        assert puntos[clave] == esperado, clave


def test_los_tokens_de_la_marca_existen_y_en_oscuro_son_los_del_icono():
    for tokens in (DARK_TOKENS, LIGHT_TOKENS):
        for n in (1, 2, 3):
            assert f"marca_{n}" in tokens
    paradas = re.findall(r'stop-color="(#[0-9a-fA-F]{6})"', app_icon._GRADIENT_DEF)
    assert [DARK_TOKENS["marca_1"], DARK_TOKENS["marca_2"], DARK_TOKENS["marca_3"]] == paradas


def test_la_marca_se_arma_con_createelementns_y_sin_innerhtml():
    """marca.js no inserta texto (no entra en test_webview_safe_dom_insertion.py, que exige
    un textContent), pero la regla de §10.1 le aplica igual."""
    js = _js()
    assert "createElementNS" in js
    assert not re.search(r"\.innerHTML\s*=|insertAdjacentHTML\s*\(", js)


def test_la_pagina_carga_las_hojas_nuevas_y_el_boton_del_mapa():
    html = (_FRONTEND / "index.html").read_text(encoding="utf-8")
    for hoja in ("css/controles.css", "css/marca.css", "css/map_panel.css"):
        assert f'href="{hoja}"' in html, hoja
    assert 'id="map-btn"' in html
    assert 'id="brand-mark"' in html
    for simbolo in ("ic-map", "ic-monitor", "ic-mail", "ic-message", "ic-plug"):
        assert f'<symbol id="{simbolo}"' in html, simbolo
