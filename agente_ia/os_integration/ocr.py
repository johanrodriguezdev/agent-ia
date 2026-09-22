"""
os_integration/ocr.py
Leer el texto que hay DIBUJADO en pantalla, cuando no hay árbol de accesibilidad que leer.

El árbol de accesibilidad (`ui_tree`, `navegador`) resuelve casi todo: botones, campos,
enlaces, el texto de una página. Pero hay cosas que no publican nada porque no son
controles, son píxeles: un mapa, un gráfico, un lienzo de dibujo, un vídeo con subtítulos,
un PDF escaneado, una imagen con texto, un escritorio remoto entero. Ahí el agente decía
"puedo mirarla con una captura" — y mirar con una captura exige un proveedor de modelo con
visión configurado, que cuesta una llamada y no siempre está.

Windows trae su propio motor de reconocimiento de texto (`Windows.Media.Ocr`), local, sin
red y sin modelo. Es lo que usa la propia herramienta de recortes del sistema para "copiar
texto de una imagen". Este módulo lo expone: dale una imagen o una ventana y devuelve el
texto que hay pintado en ella, con sus líneas.

**Lo que es y lo que no.** Es reconocimiento óptico: lee lo que se VE. Una letra pequeña,
un contraste malo o una fuente rara salen con errores, y por eso todo lo que sale de aquí
se entrega marcado como leído por OCR. No sabe qué es un botón ni dónde se pulsa — para eso
está el árbol; esto es para cuando el árbol no tiene nada que decir.

Idiomas: los que Windows tenga instalados para OCR. En esta máquina, español (es-ES y
es-MX). Con el español instalado lee también texto en inglés —mismo alfabeto—, solo que
sin las pistas de diccionario que tendría con el paquete de inglés.
"""

import asyncio
import ctypes
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

#: `Windows.Media.Ocr` rechaza imágenes por encima de este lado (lo publica el motor como
#: `max_image_dimension`, típicamente 2600). Una pantalla 4K lo supera: se reduce antes.
_LADO_MAXIMO_POR_DEFECTO = 2600


def _tesseract() -> Optional[str]:
    """Return la ruta de Tesseract, el motor de OCR de Linux, o None (REQ-068)."""
    import shutil

    return shutil.which("tesseract")


def disponible() -> bool:
    """Return True si hay un motor de OCR utilizable en este equipo.

    En Windows es `Windows.Media.Ocr`, que viene con el sistema. Fuera de Windows es
    Tesseract, que hay que instalar (`apt install tesseract-ocr tesseract-ocr-spa`) y que
    ya viene en la imagen de Docker del proyecto.
    """
    if os.name != "nt":
        return _tesseract() is not None
    try:
        from winsdk.windows.media.ocr import OcrEngine  # noqa: F401

        return bool(list(OcrEngine.available_recognizer_languages))
    except Exception as e:
        logger.debug(f"OCR de Windows no disponible: {e}")
        return False


def idiomas() -> List[str]:
    """Return las etiquetas de idioma que el motor de OCR tiene instaladas."""
    if os.name != "nt":
        return _idiomas_de_tesseract()
    try:
        from winsdk.windows.media.ocr import OcrEngine

        return [lang.language_tag for lang in OcrEngine.available_recognizer_languages]
    except Exception:
        return []


def _idiomas_de_tesseract() -> List[str]:
    import subprocess

    binario = _tesseract()
    if not binario:
        return []
    try:
        salida = subprocess.run([binario, "--list-langs"], capture_output=True,
                                text=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.debug(f"no se pudieron listar los idiomas de Tesseract: {e}")
        return []
    # La primera línea es un encabezado («List of available languages...»).
    return [l.strip() for l in salida.stdout.splitlines()[1:] if l.strip()]


def _leer_con_tesseract(ruta: str) -> str:
    """Return el texto que Tesseract encuentra en una imagen. Es el OCR fuera de Windows.

    Se le pasan los idiomas que tenga instalados, con el español primero si está: el mismo
    criterio que en Windows, donde el motor usa los idiomas del sistema.
    """
    import subprocess

    binario = _tesseract()
    if not binario:
        return ""
    disponibles = _idiomas_de_tesseract()
    preferidos = [i for i in ("spa", "eng") if i in disponibles] or disponibles[:1]
    orden = ["-l", "+".join(preferidos)] if preferidos else []
    try:
        # `stdout` como destino: así no hay que limpiar un archivo temporal.
        salida = subprocess.run([binario, ruta, "stdout", *orden],
                                capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning(f"Tesseract no pudo leer {ruta!r}: {e}")
        return ""
    if salida.returncode != 0:
        logger.warning(f"Tesseract falló ({salida.returncode}): "
                       f"{(salida.stderr or '').strip()[:150]}")
        return ""
    return salida.stdout


async def _reconocer(ruta: str) -> List[str]:
    """Return las líneas de texto reconocidas en la imagen de `ruta`."""
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.storage import FileAccessMode, StorageFile

    archivo = await StorageFile.get_file_from_path_async(os.path.abspath(ruta))
    flujo = await archivo.open_async(FileAccessMode.READ)
    try:
        decodificador = await BitmapDecoder.create_async(flujo)
        mapa = await decodificador.get_software_bitmap_async()
    finally:
        flujo.close()

    motor = OcrEngine.try_create_from_user_profile_languages()
    if motor is None:
        raise RuntimeError("Windows no tiene ningún idioma de OCR instalado")

    resultado = await motor.recognize_async(mapa)
    return [linea.text for linea in resultado.lines if linea.text]


def _encoger_si_hace_falta(ruta: str) -> str:
    """Return una ruta a la imagen ya dentro del tamaño que el motor admite."""
    try:
        from PIL import Image
    except ImportError:
        return ruta

    lado = _LADO_MAXIMO_POR_DEFECTO
    try:
        from winsdk.windows.media.ocr import OcrEngine

        lado = int(OcrEngine.max_image_dimension) or lado
    except Exception as e:
        # Sin winsdk (o con una versión que no expone el límite) se usa el tope por
        # defecto. No es un error, pero se deja dicho: si el OCR recorta imágenes de más,
        # acá está el porqué.
        logger.debug(f"no se pudo leer el tamaño máximo del motor OCR, se usa {lado}: {e}")

    try:
        with Image.open(ruta) as imagen:
            if max(imagen.size) <= lado:
                return ruta
            factor = lado / max(imagen.size)
            reducida = imagen.resize((int(imagen.width * factor), int(imagen.height * factor)))
            destino = ruta.rsplit(".", 1)[0] + "_ocr.png"
            reducida.save(destino)
            return destino
    except Exception as e:
        logger.debug(f"no se pudo reducir la imagen para el OCR: {e}")
        return ruta


#: Una palabra que es "casi un número": dígitos, separadores de miles y de decimales, signo
#: de moneda, y las letras con las que el OCR confunde a los dígitos. Solo dentro de estas
#: palabras se corrige; en una palabra normal una O es una O.
_CASI_NUMERO = __import__("re").compile(r"^[$€%+\-.,:/\dOoIl]+$")
_CONFUSIONES = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"})


def corregir_cifras(texto: str) -> str:
    """Return el texto con las confusiones típicas del OCR corregidas SOLO dentro de cifras.

    Probado sobre una imagen limpia: "$1.250.000" salió "$1.250.OOO". En un total de una
    factura eso no es un error de lectura, es otro número. Se corrige únicamente en palabras
    que ya son casi un número —tienen algún dígito y nada que no sea dígito, separador o
    una de las letras confundibles—, para no tocar "Otoño" ni "Ilíada".
    """
    import re

    salida = []
    # Se parte por CUALQUIER blanco y se conserva: partiendo solo por espacios, la última
    # palabra de cada línea arrastraba el salto y nunca se corregía.
    for trozo in re.split(r"(\s+)", texto):
        if (any(c.isdigit() for c in trozo) and _CASI_NUMERO.match(trozo)
                and any(c in "OoIl" for c in trozo)):
            salida.append(trozo.translate(_CONFUSIONES))
        else:
            salida.append(trozo)
    return "".join(salida)


def leer_imagen(ruta: str) -> str:
    """Return el texto que hay en una imagen (PNG, JPG...), línea a línea. Vacío si nada."""
    if not disponible():
        return ""
    if not ruta or not os.path.isfile(ruta):
        return ""

    if os.name != "nt":
        return corregir_cifras(_leer_con_tesseract(ruta)).strip()

    preparada = _encoger_si_hace_falta(ruta)
    try:
        lineas = asyncio.run(_reconocer(preparada))
    except Exception as e:
        logger.warning(f"el OCR no pudo leer {ruta!r}: {e}")
        return ""
    finally:
        if preparada != ruta:
            try:
                os.remove(preparada)
            except OSError:
                pass
    return corregir_cifras("\n".join(lineas)).strip()


def _rectangulo_de(hwnd: int):
    """Return `(x, y, ancho, alto)` de una ventana, o None."""
    import ctypes.wintypes as wt

    rect = wt.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    ancho, alto = rect.right - rect.left, rect.bottom - rect.top
    if ancho <= 0 or alto <= 0:
        return None
    return rect.left, rect.top, ancho, alto


def leer_ventana(hwnd: Optional[int] = None) -> str:
    """Return el texto pintado en una ventana (o en la pantalla entera si no se da ninguna).

    Se fotografía la región de la ventana tal como se ve: si otra ventana la tapa, se lee
    lo que tapa. Quien llama decide si la trae al frente antes; este módulo no toca el
    foco, porque leer no debería mover nada.
    """
    if not disponible():
        return ""
    try:
        from PIL import ImageGrab
    except ImportError:
        logger.error("Pillow no está instalado: no se puede capturar la pantalla")
        return ""

    region = _rectangulo_de(hwnd) if hwnd else None
    if hwnd and region is None:
        logger.warning(f"no se pudo medir la ventana {hwnd} para leerla")
        return ""

    import tempfile

    carpeta = os.path.join(tempfile.gettempdir(), "orion_capturas")
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, "ocr_ventana.png")
    try:
        # `all_screens=True` porque hay más de un monitor. La primera versión capturaba
        # con pyautogui, que solo ve el principal: la ventana estaba en el segundo
        # (x=2880) y el OCR leía cero caracteres de una captura en negro.
        if region:
            x, y, ancho, alto = region
            imagen = ImageGrab.grab(bbox=(x, y, x + ancho, y + alto), all_screens=True)
        else:
            imagen = ImageGrab.grab(all_screens=True)
        imagen.save(ruta)
    except Exception as e:
        logger.warning(f"no se pudo capturar para el OCR: {e}")
        return ""

    texto = leer_imagen(ruta)
    try:
        os.remove(ruta)              # puede contener cualquier cosa que hubiera en pantalla
    except OSError:
        pass
    return texto
