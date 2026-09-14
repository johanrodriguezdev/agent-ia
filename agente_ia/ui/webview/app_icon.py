"""
ui/webview/app_icon.py
El icono del agente: barra de tareas, alt-tab y bandeja del sistema.

REQ-041: la marca pasó de un anillo simple + un punto en azul plano ("mascota con
auriculares") al Concepto A ya aprobado por el humano en un canvas de diseño —tres
anillos entrelazados con degradado metálico blanco-gris alrededor de un nodo central,
sobre fondo negro sólido para el icono de app, y una variante monocroma simplificada
para la bandeja del sistema.

Se sigue generando en tiempo de ejecución (no hay ningún `.ico`/`.png`/`.svg` en el
repo) por el mismo motivo de antes: Windows pide cada tamaño distinto según dónde
pinte el icono (16 px en la bandeja, 32 en la barra, 256 en el alt-tab grande), y
dibujar en cada tamaño evita el escalado borroso de un asset único.

Lo que cambió es CÓMO se genera: la geometría exacta del canvas aprobado (círculos con
`stroke-dasharray`/`stroke-dashoffset`, degradado lineal `userSpaceOnUse`) se arma como
strings SVG desde constantes Python y se rasteriza con `QSvgRenderer`
(`PyQt6.QtSvg`, ya incluido en el `PyQt6` instalado — sin dependencias nuevas) en vez de
reconstruir arcos y gradientes a mano con `QPainter`. Así los números del canvas se
pegan tal cual, sin conversión manual que se pueda desviar del diseño aprobado.

El icono de bandeja usa una pieza DISTINTA (`bandeja_icon()`/`dibujar_bandeja()`), no el
icono de app reescalado: mismo trazo grueso y color plano `#f2f2f3` sin degradado, para
que se siga leyendo como los tres anillos a 16-24 px en vez de fundirse en una mancha
(ver `workspace/adjuntos/REQ-041/propuestas/arquitectura-041.md`, sección Riesgos).
"""

import logging
import os

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- geometría
# La "familia" de marca: los tres anillos entrelazados + el nodo central, en su espacio
# nativo 200×200 tal como los da el canvas aprobado (SPEC-041, sección "Especificación
# exacta del diseño aprobado"). Compartida entre el icono de app y el de bandeja para que
# un ajuste futuro de geometría no pueda quedar desincronizado entre ambos.
_RINGS = (
    (100.0, 76.0, 0),      # anillo 1: centro, stroke-dashoffset
    (120.8, 112.0, 96),    # anillo 2
    (79.2, 112.0, 192),    # anillo 3
)
_RING_R = 46.0
_RING_DASHARRAY = "180 30"
_NODE_CENTER = (100.0, 100.0)

_GRADIENT_ID = "orionMetalGradient"
_GRADIENT_DEF = (
    f'<linearGradient id="{_GRADIENT_ID}" x1="20" y1="10" x2="180" y2="190" '
    f'gradientUnits="userSpaceOnUse">'
    f'<stop offset="0%" stop-color="#ffffff"/>'
    f'<stop offset="50%" stop-color="#b7b8bd"/>'
    f'<stop offset="100%" stop-color="#5c5d63"/>'
    f"</linearGradient>"
)

# --------------------------------------------------------------------------- icono de app
_APP_BG = "#0a0a0b"
_APP_CANVAS = 240
_APP_BG_RX = 54
_APP_MARCA_SCALE = 0.9  # = 180/200, la marca (200x200 nativo) ocupa 180x180 = 75% de 240
_APP_MARCA_OFFSET = 30  # = (240 - 180) / 2, margen uniforme por lado
_APP_RING_STROKE_WIDTH = 3.2
_APP_NODE_R = 8.5

#: Tamaños que Windows pide según dónde dibuje el icono de app.
_TAMANOS = (16, 24, 32, 48, 64, 128, 256)

# --------------------------------------------------------------------------- icono de bandeja
_TRAY_BG = "#1b1b1d"
_TRAY_STROKE = "#f2f2f3"
_TRAY_VARIANTS = {
    24: {"corner_rx": 5, "stroke_width": 8, "node_r": 10},
    16: {"corner_rx": 4, "stroke_width": 10, "node_r": 12},
}
_TRAY_TAMANOS = (16, 24)


def _marca_svg(*, stroke: str, stroke_width: float, node_r: float) -> str:
    """Return los 3 anillos + el nodo central, en el viewBox nativo 200x200 de `_RINGS`.

    Único lugar que conoce la geometría de los anillos — la comparte el icono de app
    (con degradado, `stroke='url(#...)'`) y el de bandeja (color plano). `stroke` acepta
    tanto un color plano como una referencia `url(#id)` a un `<linearGradient>`.
    """
    circulos = "".join(
        f'<circle cx="{cx}" cy="{cy}" r="{_RING_R}" fill="none" stroke="{stroke}" '
        f'stroke-width="{stroke_width}" stroke-linecap="round" '
        f'stroke-dasharray="{_RING_DASHARRAY}" stroke-dashoffset="{offset}"/>'
        for cx, cy, offset in _RINGS
    )
    nx, ny = _NODE_CENTER
    nodo = f'<circle cx="{nx}" cy="{ny}" r="{node_r}" fill="{stroke}"/>'
    return circulos + nodo


def _app_icon_svg() -> str:
    """Return el SVG completo del icono de app: fondo negro + marca con degradado."""
    marca = _marca_svg(
        stroke=f"url(#{_GRADIENT_ID})",
        stroke_width=_APP_RING_STROKE_WIDTH,
        node_r=_APP_NODE_R,
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_APP_CANVAS} {_APP_CANVAS}">'
        f"<defs>{_GRADIENT_DEF}</defs>"
        f'<rect x="0" y="0" width="{_APP_CANVAS}" height="{_APP_CANVAS}" '
        f'rx="{_APP_BG_RX}" fill="{_APP_BG}"/>'
        f'<g transform="translate({_APP_MARCA_OFFSET},{_APP_MARCA_OFFSET}) '
        f'scale({_APP_MARCA_SCALE})">{marca}</g>'
        f"</svg>"
    )


def _tray_icon_svg(size: int) -> str:
    """Return el SVG del icono de bandeja para `size` (16 o 24, únicos que pide la SPEC).

    Dos sistemas de coordenadas dentro del mismo SVG: el `<rect>` de fondo vive en el
    espacio final en píxeles (`viewBox` del propio `size`, `rx` literal sin escalar), y la
    marca vive en su espacio nativo 200x200 dentro de un `<g transform="scale(...)">` que
    la lleva al tamaño final — así el trazo/nodo grueso de la SPEC (8/10/10/12) se
    respeta literal en su espacio nativo antes de escalar, sin perder precisión a un
    tamaño tan chico.

    Lanza `KeyError` si `size` no es 16 ni 24: no hay ningún tamaño de bandeja
    "razonable por defecto", solo los dos que pide la SPEC — un tamaño fuera de esos dos
    es un error de programación, no una entrada de usuario a validar.
    """
    variante = _TRAY_VARIANTS[size]
    marca = _marca_svg(
        stroke=_TRAY_STROKE,
        stroke_width=variante["stroke_width"],
        node_r=variante["node_r"],
    )
    escala = size / 200.0
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">'
        f'<rect x="0" y="0" width="{size}" height="{size}" '
        f'rx="{variante["corner_rx"]}" fill="{_TRAY_BG}"/>'
        f'<g transform="scale({escala})">{marca}</g>'
        f"</svg>"
    )


def _render_svg(svg: str, size: int) -> QPixmap:
    """Return el `svg` rasterizado a un `QPixmap` cuadrado de `size` píxeles.

    Fondo inicial transparente: relevante solo para las esquinas fuera del `rx` del
    `<rect>` redondeado, que el SVG deja sin pintar a propósito.
    """
    renderer = QSvgRenderer(svg.encode("utf-8"))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
    finally:
        # Sin esto, el `QPixmap` queda con el painter activo y Qt avisa por consola en
        # cada arranque; peor, el icono puede pintarse a medias.
        painter.end()

    return pixmap


def dibujar_app(size: int) -> QPixmap:
    """Return el icono de app (Concepto A, degradado metálico) a `size` píxeles."""
    return _render_svg(_app_icon_svg(), size)


def dibujar_bandeja(size: int) -> QPixmap:
    """Return el icono de bandeja (monocromo, sin degradado) a `size` píxeles.

    `size` debe ser 16 o 24 (ver `_tray_icon_svg`).
    """
    return _render_svg(_tray_icon_svg(size), size)


def app_icon() -> QIcon:
    """Return el icono de app con TODOS los tamaños de `_TAMANOS` dentro.

    Un `QIcon` con varias resoluciones deja que Windows elija la que necesita en cada
    sitio en vez de escalar una sola y dejarla borrosa en el resto.
    """
    icono = QIcon()
    for size in _TAMANOS:
        icono.addPixmap(dibujar_app(size))
    return icono


def bandeja_icon() -> QIcon:
    """Return el icono de bandeja del sistema, con los tamaños de `_TRAY_TAMANOS`.

    Nombrada así y no `tray_icon()` a propósito: `main_window.py` ya tiene el atributo
    de instancia `self.tray_icon` (el `QSystemTrayIcon`); usar el mismo nombre para la
    función sería confuso de leer al lado de `self.tray_icon.setIcon(bandeja_icon())`.
    """
    icono = QIcon()
    for size in _TRAY_TAMANOS:
        icono.addPixmap(dibujar_bandeja(size))
    return icono


#: Identidad del proceso ante la barra de tareas de Windows. La cadena da igual mientras
#: sea propia y estable: lo que importa es que NO sea la de `python.exe`.
_APP_ID = "orion.agente.escritorio"


def fijar_identidad_en_windows() -> None:
    """Le dice a Windows que este proceso es una aplicacion propia, no el intérprete.

    La barra de tareas agrupa las ventanas por AppUserModelID y toma de ahí el icono. Un
    script de Python no declara ninguno, así que hereda el de `python.exe` — y en la barra
    aparece el logo del lenguaje aunque la ventana ya tenga su propio icono puesto con
    `setWindowIcon()`. Son dos cosas distintas: una pinta la ventana, la otra dice qué
    aplicación es.

    Tiene que llamarse ANTES de crear la primera ventana; después, Windows ya agrupó.

    No hace nada fuera de Windows, y un fallo acá no puede impedir que la app arranque: lo
    peor que pasa es que se siga viendo el icono de Python.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_ID)
    except Exception as e:
        logger.warning(f"no se pudo fijar la identidad de la app en Windows: {e}")
