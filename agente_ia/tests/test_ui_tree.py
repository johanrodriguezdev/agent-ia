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


# ═════════════════════════════════════════════════════════════════════════
#  Preguntar de una vez en vez de recorrer a mano
# ═════════════════════════════════════════════════════════════════════════
#
# El recorrido a mano baja hijo por hijo y se detiene en MAX_PROFUNDIDAD. Alcanza para un
# diálogo y no alcanza para nada más: medido sobre una ventana de Chrome con una página
# cargada, devolvía 44 elementos de 3.467 —el 1,3 %— porque el contenido cuelga más abajo de
# doce niveles. Y no se cortaba por tiempo, así que no había ningún aviso de que faltaba
# algo: simplemente el agente decía que no encontraba lo que tenía delante.

class _RectCache:
    def __init__(self, x, y, ancho=80, alto=20):
        self.left, self.top = x, y
        self.right, self.bottom = x + ancho, y + alto


class _ElementoCache:
    def __init__(self, nombre, tipo_id, x=10, y=10, ancho=80, alto=20):
        self.CachedName = nombre
        self.CachedControlType = tipo_id
        self.CachedBoundingRectangle = _RectCache(x, y, ancho, alto)


class _Array:
    def __init__(self, elementos):
        self._e = elementos
        self.Length = len(elementos)

    def GetElement(self, i):
        return self._e[i]


class _Condicion:
    pass


class _ClienteFalso:
    def CreatePropertyCondition(self, *a):
        return _Condicion()

    def CreateOrCondition(self, a, b):
        return _Condicion()

    def CreateCacheRequest(self):
        class _C:
            def AddProperty(self, _p):
                pass
        return _C()


class _VentanaFalsa:
    def __init__(self, elementos):
        padre = self

        class _El:
            def FindAllBuildCache(self, _ambito, _cond, _cache):
                return _Array(padre._elementos)
        self._elementos = elementos
        self.Element = _El()
        self.Name = "Ventana de prueba"


def _montar_rapido(monkeypatch, elementos):
    """Deja el camino rápido operativo con un cliente y unos elementos simulados."""
    import uiautomation as auto

    monkeypatch.setattr(ui_tree, "cliente_uia", lambda: _ClienteFalso())
    # Los ids de tipo se leen de la librería real, así que el mapeo que se prueba es el bueno.
    return auto.ControlType


def test_se_ven_los_controles_aunque_cuelguen_muy_hondo(monkeypatch):
    """El caso que se rompía: lo que está a más de doce niveles de profundidad."""
    tipos = _montar_rapido(monkeypatch, None)
    ventana = _VentanaFalsa([
        _ElementoCache("Aceptar", tipos.ButtonControl, 10, 40),
        _ElementoCache("Historia de Python", tipos.HyperlinkControl, 30, 900),
    ])

    elementos = ui_tree._preguntar_de_una_vez(ventana, "Ventana")

    assert [e.nombre for e in elementos] == ["Aceptar", "Historia de Python"]
    assert elementos[0].tipo == "ButtonControl"


def test_lo_invisible_no_entra(monkeypatch):
    """Un control sin área no se puede pulsar, y el modelo podría intentarlo igual."""
    tipos = _montar_rapido(monkeypatch, None)
    ventana = _VentanaFalsa([
        _ElementoCache("Oculto", tipos.ButtonControl, 0, 0, ancho=0, alto=0),
        _ElementoCache("Visible", tipos.ButtonControl, 5, 5),
    ])

    elementos = ui_tree._preguntar_de_una_vez(ventana, "Ventana")

    assert [e.nombre for e in elementos] == ["Visible"]


def test_lo_que_no_tiene_nombre_tampoco(monkeypatch):
    tipos = _montar_rapido(monkeypatch, None)
    ventana = _VentanaFalsa([
        _ElementoCache("   ", tipos.ButtonControl, 5, 5),
        _ElementoCache("Guardar", tipos.ButtonControl, 9, 9),
    ])

    assert [e.nombre for e in ui_tree._preguntar_de_una_vez(ventana, "V")] == ["Guardar"]


def test_una_hoja_de_calculo_no_devuelve_mil_celdas(monkeypatch):
    """Hay tope por tipo: miles de celdas iguales no ayudan a decidir nada."""
    tipos = _montar_rapido(monkeypatch, None)
    ventana = _VentanaFalsa(
        [_ElementoCache(f"Celda {i}", tipos.EditControl, 10, i) for i in range(500)]
    )

    elementos = ui_tree._preguntar_de_una_vez(ventana, "Excel")

    assert len(elementos) == ui_tree._MAX_POR_TIPO


def test_el_mismo_control_no_se_lista_dos_veces(monkeypatch):
    tipos = _montar_rapido(monkeypatch, None)
    ventana = _VentanaFalsa([
        _ElementoCache("Buscar", tipos.ButtonControl, 10, 10),
        _ElementoCache("Buscar", tipos.ButtonControl, 10, 10),
    ])

    assert len(ui_tree._preguntar_de_una_vez(ventana, "V")) == 1


def test_los_controles_salen_en_orden_de_lectura(monkeypatch):
    tipos = _montar_rapido(monkeypatch, None)
    ventana = _VentanaFalsa([
        _ElementoCache("Abajo", tipos.ButtonControl, 10, 500),
        _ElementoCache("Arriba", tipos.ButtonControl, 10, 20),
    ])

    assert [e.nombre for e in ui_tree._preguntar_de_una_vez(ventana, "V")] == \
        ["Arriba", "Abajo"]


def test_sin_cliente_nativo_se_recorre_a_mano(monkeypatch):
    """Si una versión de la librería mueve la API privada, esto sigue funcionando."""
    monkeypatch.setattr(ui_tree, "cliente_uia", lambda: None)

    assert ui_tree._preguntar_de_una_vez(_VentanaFalsa([]), "V") == []


def test_leer_ventana_activa_cae_al_recorrido_si_no_hay_nada(monkeypatch):
    """El respaldo tiene que usarse de verdad, no quedar de adorno."""
    recorrido = {"n": 0}

    def _falso_recorrer(control, elementos, ventana, limite, profundidad=0):
        recorrido["n"] += 1
        elementos.append(ui_tree.Elemento(nombre="Del recorrido", tipo="ButtonControl", x=1, y=1))

    monkeypatch.setattr(ui_tree, "disponible", lambda: True)
    monkeypatch.setattr(ui_tree, "_preguntar_de_una_vez", lambda v, t: [])
    monkeypatch.setattr(ui_tree, "_recorrer", _falso_recorrer)

    import uiautomation as auto

    monkeypatch.setattr(auto, "GetForegroundControl", lambda: _VentanaFalsa([]))

    elementos, _titulo = ui_tree.leer_ventana_activa()

    assert recorrido["n"] == 1
    assert [e.nombre for e in elementos] == ["Del recorrido"]


def test_leer_ventana_activa_no_recorre_si_ya_tiene_lo_que_hace_falta(monkeypatch):
    recorrido = {"n": 0}
    monkeypatch.setattr(ui_tree, "disponible", lambda: True)
    monkeypatch.setattr(ui_tree, "_preguntar_de_una_vez",
                        lambda v, t: [ui_tree.Elemento(nombre="Rápido", tipo="ButtonControl", x=1, y=1)])
    monkeypatch.setattr(ui_tree, "_recorrer",
                        lambda *a, **k: recorrido.update(n=recorrido["n"] + 1))

    import uiautomation as auto

    monkeypatch.setattr(auto, "GetForegroundControl", lambda: _VentanaFalsa([]))

    elementos, _titulo = ui_tree.leer_ventana_activa()

    assert recorrido["n"] == 0
    assert [e.nombre for e in elementos] == ["Rápido"]


def test_una_libreria_distinta_no_rompe_la_lectura_de_pantalla(monkeypatch):
    """Si `uiautomation` no es como se espera, se recorre a mano en vez de reventar.

    Pasó en la propia suite: los tests inyectan un módulo simulado sin `ControlType`, y la
    primera versión leía ese atributo fuera del `try`. Un cambio de versión de la librería
    habría dejado al agente sin ver la pantalla, con un AttributeError.
    """
    class _Roto:
        pass

    monkeypatch.setattr(ui_tree, "cliente_uia", lambda: _ClienteFalso())
    monkeypatch.setitem(__import__("sys").modules, "uiautomation", _Roto)

    assert ui_tree._preguntar_de_una_vez(_VentanaFalsa([]), "V") == []
