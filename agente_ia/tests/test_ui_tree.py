"""
tests/test_ui_tree.py
Pruebas de `os_integration/ui_tree.py` — leer el árbol de accesibilidad de Windows.

Localizar un botón mirando una captura es adivinar: el modelo estima coordenadas a ojo y
puede errar por veinte píxeles, que con el ratón es la diferencia entre "Aceptar" y
"Cancelar". El sistema ya sabe dónde está cada control; esta suite protege que se lo
preguntemos bien y que, cuando no pueda responder, se diga en vez de inventar.

Ningún test depende de las ventanas que haya abiertas: el árbol va simulado.
"""

import pytest

from os_integration import ui_tree


class _Rect:
    def __init__(self, x, y, w=100, h=30):
        self._x, self._y, self._w, self._h = x, y, w, h

    def width(self):
        return self._w

    def height(self):
        return self._h

    def xcenter(self):
        return self._x

    def ycenter(self):
        return self._y


class _Control:
    """Un control simulado del árbol de Windows."""

    def __init__(self, nombre, tipo="ButtonControl", x=100, y=100, hijos=None,
                 ancho=100, alto=30):
        self.Name = nombre
        self.ControlTypeName = tipo
        self.BoundingRectangle = _Rect(x, y, ancho, alto)
        self._hijos = hijos or []

    def GetChildren(self):
        return self._hijos


def _montar_ventana(monkeypatch, raiz):
    monkeypatch.setattr(ui_tree, "disponible", lambda: True)

    class _Auto:
        @staticmethod
        def GetForegroundControl():
            return raiz

    import sys

    monkeypatch.setitem(sys.modules, "uiautomation", _Auto)


# ── Leer la ventana ─────────────────────────────────────────────────

def test_se_leen_los_controles_con_su_posicion(monkeypatch):
    ventana = _Control("Mi App", "WindowControl", hijos=[
        _Control("Aceptar", "ButtonControl", x=500, y=400),
        _Control("Cancelar", "ButtonControl", x=600, y=400),
    ])
    _montar_ventana(monkeypatch, ventana)

    elementos, titulo = ui_tree.leer_ventana_activa()

    assert titulo == "Mi App"
    nombres = {e.nombre: (e.x, e.y) for e in elementos}
    assert nombres["Aceptar"] == (500, 400)
    assert nombres["Cancelar"] == (600, 400)


def test_los_controles_sin_nombre_no_estorban(monkeypatch):
    ventana = _Control("App", "WindowControl", hijos=[
        _Control("", "PaneControl"),
        _Control("Guardar", "ButtonControl"),
    ])
    _montar_ventana(monkeypatch, ventana)

    elementos, _ = ui_tree.leer_ventana_activa()

    assert [e.nombre for e in elementos] == ["Guardar"]


def test_un_control_invisible_se_descarta(monkeypatch):
    """Sin área no se puede pulsar: si aparece, el modelo podría intentar hacerle clic."""
    ventana = _Control("App", "WindowControl", hijos=[
        _Control("Oculto", "ButtonControl", ancho=0, alto=0),
        _Control("Visible", "ButtonControl"),
    ])
    _montar_ventana(monkeypatch, ventana)

    elementos, _ = ui_tree.leer_ventana_activa()

    assert [e.nombre for e in elementos] == ["Visible"]


def test_se_recorre_en_profundidad(monkeypatch):
    ventana = _Control("App", "WindowControl", hijos=[
        _Control("Panel", "PaneControl", hijos=[
            _Control("Interior", "PaneControl", hijos=[
                _Control("Enterrado", "ButtonControl", x=10, y=20),
            ]),
        ]),
    ])
    _montar_ventana(monkeypatch, ventana)

    elementos, _ = ui_tree.leer_ventana_activa()

    assert any(e.nombre == "Enterrado" for e in elementos)


# ── Buscar ──────────────────────────────────────────────────────────

def test_la_coincidencia_exacta_gana(monkeypatch):
    """En una interfaz hay nombres parecidos; el literal casi siempre es el buscado."""
    ventana = _Control("App", "WindowControl", hijos=[
        _Control("Guardar como...", "ButtonControl", x=100, y=100),
        _Control("Guardar", "ButtonControl", x=200, y=200),
    ])
    _montar_ventana(monkeypatch, ventana)

    elemento, _ = ui_tree.buscar("Guardar")

    assert (elemento.x, elemento.y) == (200, 200)


def test_se_encuentra_por_prefijo(monkeypatch):
    ventana = _Control("App", "WindowControl", hijos=[
        _Control("Aceptar y continuar", "ButtonControl", x=300, y=300),
    ])
    _montar_ventana(monkeypatch, ventana)

    elemento, _ = ui_tree.buscar("Aceptar")

    assert elemento is not None and elemento.x == 300


def test_los_acentos_no_impiden_encontrarlo(monkeypatch):
    ventana = _Control("App", "WindowControl", hijos=[
        _Control("Añadir sesión", "ButtonControl", x=50, y=60),
    ])
    _montar_ventana(monkeypatch, ventana)

    elemento, _ = ui_tree.buscar("anadir sesion")

    assert elemento is not None


def test_se_prefieren_los_controles_pulsables(monkeypatch):
    """Un texto que dice "Aceptar" no es el botón Aceptar."""
    ventana = _Control("App", "WindowControl", hijos=[
        _Control("Aceptar", "TextControl", x=100, y=100),
        _Control("Aceptar", "ButtonControl", x=500, y=500),
    ])
    _montar_ventana(monkeypatch, ventana)

    elemento, _ = ui_tree.buscar("Aceptar")

    assert elemento.tipo == "ButtonControl"
    assert (elemento.x, elemento.y) == (500, 500)


def test_si_no_esta_se_devuelven_los_candidatos(monkeypatch):
    """Decir qué SÍ hay es más útil que un "no encontrado" a secas."""
    ventana = _Control("App", "WindowControl", hijos=[
        _Control("Guardar", "ButtonControl"),
        _Control("Salir", "ButtonControl"),
    ])
    _montar_ventana(monkeypatch, ventana)

    elemento, candidatos = ui_tree.buscar("Imprimir")

    assert elemento is None
    assert {c.nombre for c in candidatos} == {"Guardar", "Salir"}


# ── Límites: no colgarse ni ahogarse ────────────────────────────────

def test_el_recorrido_se_corta_por_cantidad(monkeypatch):
    """Una hoja de cálculo tiene miles de celdas y ninguna suele ser lo que se busca."""
    muchos = [_Control(f"Celda {i}", "ListItemControl") for i in range(600)]
    _montar_ventana(monkeypatch, _Control("Excel", "WindowControl", hijos=muchos))

    elementos, _ = ui_tree.leer_ventana_activa()

    assert len(elementos) <= ui_tree.MAX_ELEMENTOS


def test_los_limites_estan_fijados():
    """Subirlos hace que una app lenta deje al usuario esperando sin saber por qué."""
    assert ui_tree.TIMEOUT_SEGUNDOS == 3.0
    assert ui_tree.MAX_ELEMENTOS == 400


# ── Cuando la aplicación no colabora ────────────────────────────────

def test_una_ventana_que_no_expone_nada_lo_dice(monkeypatch):
    """Es el caso de VS Code y las aplicaciones Electron: 7 elementos y ninguno útil."""
    _montar_ventana(monkeypatch, _Control("VS Code", "WindowControl", hijos=[]))

    texto = ui_tree.describir_ventana_activa()

    assert "no expone" in texto.lower()
    assert "pc_look" in texto        # dice qué hacer en su lugar


def test_sin_la_libreria_se_degrada(monkeypatch):
    monkeypatch.setattr(ui_tree, "disponible", lambda: False)

    elementos, titulo = ui_tree.leer_ventana_activa()

    assert elementos == []
    assert titulo == ""


def test_un_control_que_falla_no_tumba_el_recorrido(monkeypatch):
    """Un control puede desaparecer mientras se recorre: la ventana está viva."""
    class _Roto:
        Name = "Roto"
        ControlTypeName = "ButtonControl"

        @property
        def BoundingRectangle(self):
            raise RuntimeError("el control ya no existe")

        def GetChildren(self):
            return []

    ventana = _Control("App", "WindowControl", hijos=[
        _Roto(), _Control("Bueno", "ButtonControl"),
    ])
    _montar_ventana(monkeypatch, ventana)

    elementos, _ = ui_tree.leer_ventana_activa()

    assert [e.nombre for e in elementos] == ["Bueno"]
