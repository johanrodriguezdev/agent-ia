"""
ui/webview/app_icon.py
El icono del agente: barra de tareas, alt-tab y bandeja del sistema.

Hasta ahora no había ninguno. La ventana heredaba el de Python —el logo del lenguaje en la
barra de tareas de alguien que abrió su asistente— y la bandeja mostraba un cuadrado azul
liso de 16×16, que entre los iconos ocultos de Windows es indistinguible de cualquier otra
cosa.

Se dibuja con `QPainter` en vez de cargar un `.ico`, por dos motivos:

- **El nombre del agente es del usuario.** Hoy se llama VIERNES, ayer ORION. Un archivo
  binario con un logo fijo envejece mal; una marca abstracta no depende del nombre, y si
  algún día se quiere la inicial, sale de `get_agent_name()` sin recompilar nada.
- **Windows elige el tamaño según dónde lo pinte** (16 px en la bandeja, 32 en la barra,
  256 en el alt-tab grande). Dibujando se genera cada tamaño nítido, sin el escalado
  borroso de un PNG único.

El diseño es deliberadamente simple porque tiene que leerse a 16 píxeles: un anillo con un
punto centrado. A ese tamaño los detalles desaparecen —un degradado se ve como una mancha,
una letra fina como un borrón— y lo único que sobrevive es la silueta. Un anillo se
reconoce de un vistazo incluso entre veinte iconos apilados.
"""

import logging
import os
from typing import Optional

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

logger = logging.getLogger(__name__)

#: El azul de acento del tema oscuro (`ui/webview/theme.py::text_accent`). Se repite acá y
#: no se importa a propósito: el icono lo pinta Windows fuera de la app —en la bandeja, en
#: la barra de tareas—, donde no hay tema claro ni oscuro que consultar. Es un color fijo
#: que tiene que verse sobre cualquier fondo del escritorio.
_ACENTO = "#58a6ff"

#: Tamaños que Windows pide según dónde dibuje el icono.
_TAMANOS = (16, 24, 32, 48, 64, 128, 256)


def dibujar(size: int, color: Optional[str] = None) -> QPixmap:
    """Return el icono dibujado a `size` píxeles, con fondo transparente."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tinte = QColor(color or _ACENTO)

        # El grosor del anillo y el radio del punto van en proporción al tamaño: a 16 px un
        # trazo fijo de 2 px se come el hueco y el anillo se ve como un disco.
        grosor = max(1.5, size * 0.11)
        margen = grosor / 2 + size * 0.06

        painter.setPen(QPen(tinte, grosor, cap=Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(
            QRectF(margen, margen, size - margen * 2, size - margen * 2)
        )

        radio_punto = size * 0.17
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tinte)
        painter.drawEllipse(
            QRectF(size / 2 - radio_punto, size / 2 - radio_punto,
                   radio_punto * 2, radio_punto * 2)
        )
    finally:
        # Sin esto, el `QPixmap` queda con el painter activo y Qt avisa por consola en cada
        # arranque; peor, el icono puede pintarse a medias.
        painter.end()

    return pixmap


def app_icon(color: Optional[str] = None) -> QIcon:
    """Return el icono con TODOS los tamaños dentro.

    Un `QIcon` con varias resoluciones deja que Windows elija la que necesita en cada sitio
    en vez de escalar una sola y dejarla borrosa en el resto.
    """
    icono = QIcon()
    for size in _TAMANOS:
        icono.addPixmap(dibujar(size, color))
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
