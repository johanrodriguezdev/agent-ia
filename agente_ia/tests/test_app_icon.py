"""
tests/test_app_icon.py
El icono del agente en la barra de tareas, alt-tab y bandeja del sistema.

REQ-041: la marca pasó del anillo simple + punto azul plano al Concepto A (tres anillos
entrelazados con degradado metálico sobre fondo negro sólido para el icono de app, y una
variante monocroma simplificada — distinta, no el mismo icono reescalado — para la
bandeja). No se comprueba que el dibujo sea bonito —eso no se puede probar— sino lo que
sostiene que se vea bien: que traigan todos los tamaños, que a tamaño chico siga habiendo
figura reconocible y no una mancha ni un vacío, que el fondo del icono de app sea negro
sólido a propósito (ya no transparente), que las esquinas redondeadas sigan dejando alfa 0
fuera del `rect`, y que la bandeja sea realmente una pieza distinta (color plano, fondo
propio) y no el icono de app escalado.
"""

import pytest

pytest.importorskip("PyQt6.QtGui")

from ui.webview.app_icon import (  # noqa: E402
    _TAMANOS,
    _TRAY_STROKE,
    _TRAY_TAMANOS,
    _TRAY_VARIANTS,
    _marca_svg,
    _render_svg,
    app_icon,
    bandeja_icon,
    dibujar_app,
    dibujar_bandeja,
)


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


def test_bandeja_trae_los_dos_tamanos(qapp):
    """La bandeja del sistema solo pide 16 y 24 px — no hace falta cargar el resto de
    `_TAMANOS` en un `QIcon` que Windows nunca va a mostrar a esos tamaños."""
    disponibles = {(s.width(), s.height()) for s in bandeja_icon().availableSizes()}

    for esperado in _TRAY_TAMANOS:
        assert (esperado, esperado) in disponibles, f"falta el tamaño {esperado}"


def test_el_fondo_del_icono_de_app_es_negro_solido(qapp):
    """El Concepto A (REQ-041) fija el fondo del icono de app en negro sólido `#0a0a0b`
    a propósito, a diferencia del diseño anterior que era transparente. Un punto del
    borde (dentro del `rect` redondeado, no en la esquina) tiene que ser ese color con
    alfa completo."""
    imagen = dibujar_app(64).toImage()

    borde = imagen.pixelColor(32, 1)  # (size//2, 1): centro horizontal, borde superior
    assert borde.alpha() == 255, "el fondo del icono de app debería ser opaco"
    assert (borde.red(), borde.green(), borde.blue()) == (0x0A, 0x0A, 0x0B), (
        "el fondo del icono de app debería ser #0a0a0b"
    )


def test_las_esquinas_del_icono_de_app_son_transparentes_por_el_redondeo(qapp):
    """Regresión del caso concreto: un `QPixmap` lleno pinta los 4 vértices. Con el
    Concepto A las esquinas se mantienen transparentes igual que antes, pero por un motivo
    distinto: ya no es que TODO el fondo sea transparente (ahora es negro sólido a
    propósito), sino que el `<rect rx=...>` del icono de app deja las 4 esquinas fuera del
    área redondeada sin pintar. Se usa tamaño 64 (no 16) para tener margen de
    antialiasing."""
    imagen = dibujar_app(64).toImage()
    esquinas = [(0, 0), (63, 0), (0, 63), (63, 63)]

    assert all(imagen.pixelColor(x, y).alpha() == 0 for x, y in esquinas)


def test_a_16_pixeles_todavia_hay_una_figura(qapp):
    """El icono de app a 16 px literales. Con la geometría EXACTA del canvas aprobado
    (trazo de 3.2 sobre un anillo escalado a ~0.9 y luego a 16/240), `orion-architect`
    midió empíricamente que solo ~0.8% de los píxeles se distinguen del fondo negro
    (arquitectura-041.md, sección Riesgos) — muy por debajo del 15%-80% que exigía el
    diseño anterior. No se reinterpreta la geometría (la SPEC lo prohíbe explícitamente),
    así que el umbral de este test se ajusta a ese comportamiento esperado por diseño: solo
    se exige que quede AL MENOS un píxel distinguible del fondo, no una proporción alta.
    Con fondo ahora opaco, se compara color contra `_APP_BG` en vez de usar alfa."""
    imagen = dibujar_app(16).toImage()
    fondo = (0x0A, 0x0A, 0x0B)
    total = 16 * 16
    distintos = sum(
        1
        for y in range(16)
        for x in range(16)
        if (imagen.pixelColor(x, y).red(),
            imagen.pixelColor(x, y).green(),
            imagen.pixelColor(x, y).blue()) != fondo
    )

    assert distintos > 0, "a 16 px el icono de app es indistinguible de un cuadrado negro liso"


def test_bandeja_16_y_24_son_legibles(qapp):
    """La bandeja SÍ necesita leerse a 16-24 px (a diferencia del icono de app, que rara
    vez se ve tan chico en uso real) — por eso usa trazo más grueso y color plano.

    A esos tamaños el trazo nativo (8/10, ver `_TRAY_VARIANTS`) queda por debajo de 1 px
    real una vez escalado (`scale(size/200)`), así que ningún píxel individual llega a
    estar 100% cubierto — lo que sí se sostiene es que una porción reconocible del chip
    se distingue del fondo (ni "casi vacío" ni "mancha sólida"). Medido en este entorno
    (Qt 6.11.0): ~32%-43% de los píxeles difieren del fondo `#1b1b1d` en 16/24 px — más
    alto que la referencia de `arquitectura-041.md` (~19-23%) porque acá se cuenta CUALQUIER
    desviación de color por antialiasing, no solo píxeles con cobertura fuerte; documentado
    como decisión de implementación en `desarrollo-log-041.md`. El margen 15%-60% dado acá
    cubre ese rango real y sigue distinguiendo una regresión real (vacío o mancha)."""
    fondo = (0x1B, 0x1B, 0x1D)

    for size in _TRAY_TAMANOS:
        imagen = dibujar_bandeja(size).toImage()
        total = size * size
        distintos = sum(
            1
            for y in range(size)
            for x in range(size)
            if (imagen.pixelColor(x, y).red(),
                imagen.pixelColor(x, y).green(),
                imagen.pixelColor(x, y).blue()) != fondo
        )

        assert distintos > total * 0.15, f"a {size} px la bandeja casi no se ve"
        assert distintos < total * 0.60, f"a {size} px la bandeja es casi una mancha sólida"


def test_bandeja_usa_color_plano_sin_degradado(qapp):
    """El icono de bandeja es monocromo a propósito (legibilidad a 16-24 px) — dos
    píxeles del mismo trazo tienen que ser EXACTAMENTE el mismo color `#f2f2f3`, no variar
    por posición como pasaría con un degradado (contraste directo con `dibujar_app`, cuyo
    `stroke` es `url(#...)` hacia un `<linearGradient>`).

    A tamaño real de bandeja (16/24 px) el trazo nativo queda por debajo de 1 px una vez
    escalado y NINGÚN píxel llega a cobertura 100% (antialiasing puro, ver
    `test_bandeja_16_y_24_son_legibles`) — comparar colores ahí daría falsos negativos por
    ese artefacto de escala, no por un degradado real. Se verifica la misma geometría
    (`_marca_svg`, la función que también usa `dibujar_bandeja`) al tamaño NATIVO 200 px
    -donde el trazo de 8 px sí tiene sobra para píxeles con cobertura completa- para aislar
    la propiedad real que importa: el color no depende de la posición."""
    variante = _TRAY_VARIANTS[24]
    marca = _marca_svg(
        stroke=_TRAY_STROKE, stroke_width=variante["stroke_width"], node_r=variante["node_r"]
    )
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">{marca}</svg>'
    imagen = _render_svg(svg, 200).toImage()
    blanco_roto = (0xF2, 0xF2, 0xF3)

    exactos = [
        (x, y)
        for y in range(200)
        for x in range(200)
        if (imagen.pixelColor(x, y).red(), imagen.pixelColor(x, y).green(),
            imagen.pixelColor(x, y).blue()) == blanco_roto
        and imagen.pixelColor(x, y).alpha() == 255
    ]

    assert len(exactos) >= 2, "no se encontraron suficientes píxeles de trazo con cobertura completa"
    # Dos puntos espacialmente separados (no adyacentes) del mismo trazo: si hubiera
    # degradado, distintas posiciones del anillo tendrían distinto color: acá, por
    # construcción, todos los píxeles filtrados ya son el mismo color exacto — lo que
    # prueba la ausencia de degradado es precisamente que existan muchos, repartidos por
    # distintas zonas de la marca, no solo en un punto.
    xs = {p[0] for p in exactos}
    ys = {p[1] for p in exactos}
    assert max(xs) - min(xs) > 10 or max(ys) - min(ys) > 10, (
        "los píxeles de trazo con color exacto deberían repartirse por la marca, no "
        "agruparse en un solo punto"
    )


def test_bandeja_no_es_el_icono_de_app_reescalado(qapp):
    """Criterio de aceptación directo de SPEC-041: la bandeja no es el mismo `app_icon()`
    reescalado — tiene su propio fondo (`#1b1b1d`), distinto del fondo del icono de app
    (`#0a0a0b`)."""
    app = dibujar_app(24).toImage()
    bandeja = dibujar_bandeja(24).toImage()

    fondo_app = app.pixelColor(12, 1)
    fondo_bandeja = bandeja.pixelColor(12, 1)

    assert (fondo_app.red(), fondo_app.green(), fondo_app.blue()) != (
        fondo_bandeja.red(), fondo_bandeja.green(), fondo_bandeja.blue()
    )


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
