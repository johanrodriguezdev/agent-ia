"""
tests/test_ocr.py
Pruebas de `os_integration/ocr.py` — leer el texto que hay DIBUJADO cuando no hay árbol.

Un mapa, un lienzo, un vídeo con subtítulos, un PDF escaneado: no publican controles, pero
son píxeles con letras. El OCR de Windows las lee sin modelo ni red. Estas pruebas no
llaman al motor de verdad: fijan lo que se hace con lo que devuelve, y dónde se usa.
"""

import os

import pytest

from os_integration import ocr


# ------------------------------------------------------------------- corregir cifras

def test_los_ceros_leidos_como_letra_o_se_corrigen_en_una_cifra():
    """Caso real: "$1.250.000" salió "$1.250.OOO". En un total, eso es otro número."""
    assert ocr.corregir_cifras("Total: $1.250.OOO") == "Total: $1.250.000"


def test_una_fecha_con_letras_confundidas_se_corrige():
    assert ocr.corregir_cifras("ref 2O26-Ol") == "ref 2026-01"


def test_una_palabra_normal_no_se_toca():
    """En "Otoño" la O es una O, y en "Ilíada" la I es una I."""
    assert ocr.corregir_cifras("Otoño en Ilíada") == "Otoño en Ilíada"


def test_sin_ningun_digito_no_hay_cifra_que_corregir():
    assert ocr.corregir_cifras("Ol") == "Ol"


# ------------------------------------------------------------------------ leer imagen

def test_sin_motor_no_se_lee_nada(monkeypatch, tmp_path):
    monkeypatch.setattr(ocr, "disponible", lambda: False)
    imagen = tmp_path / "x.png"
    imagen.write_bytes(b"png")

    assert ocr.leer_imagen(str(imagen)) == ""


def test_una_ruta_que_no_existe_devuelve_vacio(monkeypatch):
    monkeypatch.setattr(ocr, "disponible", lambda: True)
    assert ocr.leer_imagen("C:/no/existe.png") == ""


def test_lo_reconocido_sale_por_lineas_y_con_las_cifras_corregidas(monkeypatch, tmp_path):
    imagen = tmp_path / "factura.png"
    imagen.write_bytes(b"png")
    monkeypatch.setattr(ocr, "disponible", lambda: True)
    monkeypatch.setattr(ocr, "_encoger_si_hace_falta", lambda ruta: ruta)

    async def _falso(_ruta):
        return ["Factura 45l2", "Total $1.250.OOO"]

    monkeypatch.setattr(ocr, "_reconocer", _falso)

    assert ocr.leer_imagen(str(imagen)) == "Factura 4512\nTotal $1.250.000"


def test_si_el_motor_falla_no_revienta(monkeypatch, tmp_path):
    imagen = tmp_path / "x.png"
    imagen.write_bytes(b"png")
    monkeypatch.setattr(ocr, "disponible", lambda: True)
    monkeypatch.setattr(ocr, "_encoger_si_hace_falta", lambda ruta: ruta)

    async def _explota(_ruta):
        raise RuntimeError("el motor no responde")

    monkeypatch.setattr(ocr, "_reconocer", _explota)

    assert ocr.leer_imagen(str(imagen)) == ""


# ----------------------------------------------------------------------- leer ventana

def _grab_falso(monkeypatch, llamadas):
    """Sustituye la captura de Pillow y anota con qué se la llamó."""
    from PIL import ImageGrab

    class _Imagen:
        def save(self, ruta):
            llamadas.append(("guardada", ruta))
            with open(ruta, "wb") as f:
                f.write(b"png")

    def _grab(bbox=None, all_screens=False, **kw):
        llamadas.append(("grab", bbox, all_screens))
        return _Imagen()

    monkeypatch.setattr(ImageGrab, "grab", _grab)


def test_leer_ventana_fotografia_solo_la_ventana_y_borra_la_foto(monkeypatch):
    """La captura puede contener cualquier cosa que hubiera en pantalla: no se deja."""
    llamadas = []
    _grab_falso(monkeypatch, llamadas)
    monkeypatch.setattr(ocr, "disponible", lambda: True)
    monkeypatch.setattr(ocr, "_rectangulo_de", lambda hwnd: (10, 20, 300, 200))
    monkeypatch.setattr(ocr, "leer_imagen", lambda ruta: "texto pintado")

    assert ocr.leer_ventana(1234) == "texto pintado"
    assert ("grab", (10, 20, 310, 220), True) in llamadas
    guardadas = [c[1] for c in llamadas if c[0] == "guardada"]
    assert guardadas and not os.path.exists(guardadas[0])


def test_una_ventana_en_el_segundo_monitor_tambien_se_lee(monkeypatch):
    """Caso real: la ventana estaba en x=2880 y la captura del monitor principal salía negra."""
    llamadas = []
    _grab_falso(monkeypatch, llamadas)
    monkeypatch.setattr(ocr, "disponible", lambda: True)
    monkeypatch.setattr(ocr, "_rectangulo_de", lambda hwnd: (2880, 0, 2400, 1278))
    monkeypatch.setattr(ocr, "leer_imagen", lambda ruta: "segundo monitor")

    assert ocr.leer_ventana(99) == "segundo monitor"
    grab = [c for c in llamadas if c[0] == "grab"][0]
    assert grab[1] == (2880, 0, 5280, 1278)
    assert grab[2] is True                     # all_screens: sin esto no existe x=2880


def test_sin_ventana_se_lee_la_pantalla_entera(monkeypatch):
    llamadas = []
    _grab_falso(monkeypatch, llamadas)
    monkeypatch.setattr(ocr, "disponible", lambda: True)
    monkeypatch.setattr(ocr, "leer_imagen", lambda ruta: "todo")

    assert ocr.leer_ventana(None) == "todo"
    assert ("grab", None, True) in llamadas


# ------------------------------------------------------- dónde se usa: la página del navegador

def test_una_pagina_sin_texto_se_lee_por_ocr(monkeypatch):
    """Un mapa o un lienzo no publican texto, pero sí hay letras pintadas en pantalla."""
    from os_integration import navegador

    monkeypatch.setattr(navegador, "ventana_con_pagina",
                        lambda: (7, "Mapa del predio", "Google Chrome"))
    monkeypatch.setattr(navegador, "documento_de", lambda hwnd: (object(), 40))
    monkeypatch.setattr(navegador, "_patron", lambda c, n: None)
    monkeypatch.setattr(navegador, "elementos_de_pagina", lambda hwnd, **kw: [])
    monkeypatch.setattr(navegador, "_al_frente", lambda hwnd: True)
    monkeypatch.setattr("os_integration.ocr.leer_ventana", lambda hwnd: "Lote 14 - 3,2 ha")

    salida = navegador.texto_de_pagina()

    assert "Lote 14" in salida
    assert "OCR" in salida                     # se avisa de dónde salió


def test_si_tampoco_hay_nada_pintado_se_dice(monkeypatch):
    from os_integration import navegador

    monkeypatch.setattr(navegador, "ventana_con_pagina",
                        lambda: (7, "Vídeo", "Google Chrome"))
    monkeypatch.setattr(navegador, "documento_de", lambda hwnd: (object(), 40))
    monkeypatch.setattr(navegador, "_patron", lambda c, n: None)
    monkeypatch.setattr(navegador, "elementos_de_pagina", lambda hwnd, **kw: [])
    monkeypatch.setattr(navegador, "_al_frente", lambda hwnd: True)
    monkeypatch.setattr("os_integration.ocr.leer_ventana", lambda hwnd: "")

    salida = navegador.texto_de_pagina()

    assert "tampoco hay texto dibujado" in salida


# ------------------------------------------------------------ dónde se usa: PDF escaneado

def test_un_pdf_escaneado_se_reconoce_si_hay_con_que(monkeypatch):
    from os_integration import web_search

    monkeypatch.setattr(web_search, "_ocr_pdf",
                        lambda crudo, max_paginas=5: "INFORME 2025\nTotal 1.850.000")

    class _Lector:
        def __init__(self, _flujo):
            self.pages = [type("P", (), {"extract_text": lambda self: ""})()]
            self.metadata = {}

    import PyPDF2

    monkeypatch.setattr(PyPDF2, "PdfReader", _Lector)

    class _R:
        crudo, truncada, content_type = b"%PDF", False, "application/pdf"

    pagina = web_search._extraer_pdf(_R(), "https://x.com/escaneo.pdf", 5000)

    assert pagina["ok"] is True
    assert "INFORME 2025" in pagina["texto"]
    assert "OCR" in pagina["texto"]            # marcado como reconocido, no extraído


def test_sin_pymupdf_un_escaneo_sigue_declarandose_como_tal(monkeypatch):
    from os_integration import web_search

    import sys

    monkeypatch.setitem(sys.modules, "pymupdf", None)   # como si no estuviera instalado

    assert web_search._ocr_pdf(b"%PDF") == ""


# --------------------------------------------------------------------- la herramienta

def test_pc_read_registrada_y_verde():
    from agents.tool_registry import get_tool
    from core.security_manager import RiskLevel, security_manager

    assert get_tool("pc_read") is not None
    assert security_manager.classify_action("pc_read") == RiskLevel.GREEN


def test_pc_read_sin_motor_lo_dice(monkeypatch):
    from agents.tool_registry import get_tool

    monkeypatch.setattr("os_integration.ocr.disponible", lambda: False)

    salida = get_tool("pc_read").invoke({})

    assert "no puedo leer" in salida.lower()


def test_pc_read_devuelve_el_texto_marcado_como_ocr(monkeypatch):
    from agents.tool_registry import get_tool

    monkeypatch.setattr("os_integration.ocr.disponible", lambda: True)
    monkeypatch.setattr("os_integration.ocr.leer_ventana", lambda hwnd: "Puntaje: 4.520")

    salida = get_tool("pc_read").invoke({})

    assert "Puntaje: 4.520" in salida
    assert "OCR" in salida
