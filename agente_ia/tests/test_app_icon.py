"""
tests/test_app_icon.py
El icono del agente en la barra de tareas y en la bandeja del sistema.

Antes no había ninguno: la ventana heredaba el icono de Python y la bandeja mostraba un
cuadrado azul liso de 16x16, indistinguible del resto entre los iconos ocultos de Windows.

No se comprueba que el dibujo sea bonito —eso no se puede probar— sino las tres cosas de
las que depende que se vea bien: que traiga todos los tamaños, que a 16 px siga habiendo
una figura reconocible (y no una mancha), y que el fondo sea transparente.
"""

import pytest

pytest.importorskip("PyQt6.QtGui")

from ui.webview.app_icon import _TAMANOS, app_icon, dibujar  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    """Qt necesita una `QApplication` viva para pintar, aunque sea sin pantalla.

    `offscreen` deja que el test corra en cualquier maquina y en CI: se dibuja de verdad,
    en memoria, sin abrir ninguna ventana.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_trae_todos_los_tamanos(qapp):
    """Windows pide 16 px en la bandeja, 32 en la barra y 256 en el alt-tab grande. Con un
    solo tamaño dentro, los demás salen del escalado y se ven borrosos."""
    disponibles = {(s.width(), s.height()) for s in app_icon().availableSizes()}

    for esperado in _TAMANOS:
        assert (esperado, esperado) in disponibles, f"falta el tamaño {esperado}"


def test_el_fondo_es_transparente(qapp):
    """La bandeja y la barra de tareas pintan sobre su propio fondo: un icono con fondo
    opaco se ve como un recuadro pegado encima."""
    imagen = dibujar(64).toImage()

    # `pixelColor()` y no `pixel()`: el segundo devuelve un QRgb sin alfa, así que el
    # test pasaría a decir que nada es transparente jamás.
    assert imagen.pixelColor(0, 0).alpha() == 0, "la esquina debería ser transparente"


def test_a_16_pixeles_todavia_hay_una_figura(qapp):
    """El tamaño que importa. A 16 px un diseño con detalle se convierte en una mancha:
    esto verifica que quede tanto tinta como hueco — o sea, que el anillo se distinga del
    punto en vez de fundirse en un disco lleno."""
    imagen = dibujar(16).toImage()
    total = 16 * 16
    pintados = sum(
        1
        for y in range(16)
        for x in range(16)
        if imagen.pixelColor(x, y).alpha() > 40
    )

    assert pintados > total * 0.15, "casi no se ve nada a 16 px"
    assert pintados < total * 0.80, "a 16 px es casi un cuadrado lleno, como el que había"


def test_no_es_el_cuadrado_liso_de_antes(qapp):
    """Regresión del caso concreto: un `QPixmap(16,16).fill(azul)` pinta los 256 píxeles."""
    imagen = dibujar(16).toImage()
    esquinas = [(0, 0), (15, 0), (0, 15), (15, 15)]

    assert all(imagen.pixelColor(x, y).alpha() == 0 for x, y in esquinas)


def test_la_app_declara_su_propia_identidad_en_windows():
    """La barra de tareas seguía mostrando el logo de Python con el icono ya puesto.

    Windows agrupa las ventanas por AppUserModelID y saca el icono de ahí; un script de
    Python no declara ninguno y hereda el de `python.exe`. `setWindowIcon()` no alcanza:
    una cosa pinta la ventana, la otra le dice al sistema qué aplicación es.
    """
    import os

    from ui.webview.app_icon import _APP_ID, fijar_identidad_en_windows

    fijar_identidad_en_windows()   # fuera de Windows es un no-op y no debe lanzar

    if os.name != "nt":
        pytest.skip("AppUserModelID solo existe en Windows")

    import ctypes

    buf = ctypes.c_wchar_p()
    ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(buf))
    assert buf.value == _APP_ID


def test_se_declara_antes_de_crear_la_ventana():
    """El orden importa: después de que Windows agrupe, cambiarlo ya no surte efecto."""
    from pathlib import Path

    fuente = Path(__file__).resolve().parent.parent / "main.py"
    texto = fuente.read_text(encoding="utf-8")

    assert texto.index("fijar_identidad_en_windows()") < texto.index("QApplication(sys.argv)")
