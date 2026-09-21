"""
core/imagenes.py
REQ-054 — imágenes en el chat de escritorio: lo que hay que saber de un archivo de imagen
antes de mostrarlo en una burbuja o de mandárselo al modelo.

Por Telegram y Discord el agente ya VE las fotos que le mandan (`image_path` hasta
`generate_response`). En el escritorio una imagen adjunta le llegaba solo como una ruta
escrita en el texto: el modelo no la veía. Este módulo reúne lo que ese camino
necesitaba y que estaba repartido o no existía:

- el tipo real del archivo por sus primeros bytes (`media_type`), porque la API de
  Anthropic rechaza una imagen declarada como JPEG que en realidad es PNG —y una captura
  pegada es casi siempre PNG—;
- una miniatura como `data:` URL (`miniatura_data_url`) para la burbuja del usuario y el
  chip del adjunto, sin que la página tenga que leer archivos locales;
- una copia reducida para el modelo (`preparar_para_el_modelo`) cuando la imagen supera lo
  que los proveedores aceptan;
- la carpeta y el nombre de una imagen pegada del portapapeles (`ruta_para_imagen_pegada`);
- el marcador con el que el adjunto viaja dentro del texto del mensaje (`marcar_adjunto`,
  `separar_adjunto`).

Solo stdlib y Pillow (que ya es dependencia por `pyautogui`). Nada acá conoce a Qt.
"""

import base64
import logging
import os
import re
import tempfile
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: Las mismas extensiones de imagen que acepta `ui/webview/file_drop.py`.
EXTENSIONES_DE_IMAGEN = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})

_MEDIA_TYPE_POR_EXTENSION = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

#: Lado máximo de la miniatura que va a la burbuja. Es una vista previa: la imagen entera
#: sigue en disco y el modelo recibe la suya aparte.
LADO_MINIATURA = 360
#: Lo que pide el visor a tamaño completo. Más que esto no cabe en la ventana y solo
#: engorda el `data:` URL que cruza el canal.
LADO_VISOR = 1600

#: Lo que el modelo recibe. 1568 px es el lado largo que recomienda Anthropic (más grande
#: se reduce del lado del servidor igual, pagando la subida); 4 MB deja margen bajo el
#: tope de 5 MB por imagen. Gemini y OpenAI aceptan más, pero mandar menos no les quita
#: nada y una captura de pantalla de 4K entra cómoda.
LADO_MAXIMO_PARA_EL_MODELO = 1568
BYTES_MAXIMOS_PARA_EL_MODELO = 4 * 1024 * 1024

_MARCADOR_ARCHIVO = "[Archivo adjunto: {ruta}]"
_MARCADOR_IMAGEN = "[Imagen adjunta: {ruta}]"
#: El marcador va SIEMPRE al final del mensaje, en su propio párrafo (`Bridge._con_adjunto`).
_RE_MARCADOR = re.compile(
    r"(?:\n\n|^)\[(?:Archivo adjunto|Imagen adjunta): (?P<ruta>[^\]\n]+)\]\s*$"
)

#: Copias reducidas ya hechas en este proceso: `(ruta, tamaño, mtime) -> ruta reducida`.
#: El bucle de razonamiento llama a `generate_response` una vez por vuelta con la misma
#: imagen, y reducirla en cada vuelta sería trabajo repetido.
_reducidas: Dict[Tuple[str, int, float], str] = {}


def es_imagen(ruta: Optional[str]) -> bool:
    """Return si la ruta tiene extensión de imagen (no mira el contenido)."""
    if not ruta:
        return False
    return os.path.splitext(ruta)[1].lower() in EXTENSIONES_DE_IMAGEN


def _tipo_por_firma(ruta: str) -> Optional[str]:
    """Return el tipo MIME según los primeros bytes del archivo, o None si no es una de
    las cuatro firmas conocidas (o no se puede leer)."""
    try:
        with open(ruta, "rb") as f:
            cabecera = f.read(12)
    except OSError as e:
        logger.warning(f"no se pudo leer la cabecera de la imagen '{ruta}': {e}")
        return None
    if cabecera.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if cabecera.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if cabecera.startswith(b"GIF87a") or cabecera.startswith(b"GIF89a"):
        return "image/gif"
    if cabecera[:4] == b"RIFF" and cabecera[8:12] == b"WEBP":
        return "image/webp"
    return None


def media_type(ruta: str) -> str:
    """Return el tipo MIME real de la imagen, por sus primeros bytes.

    Si no se reconoce la firma se cae a la extensión, y si tampoco, a `image/jpeg`, que es
    lo que se asumía siempre antes de este módulo.
    """
    return (_tipo_por_firma(ruta)
            or _MEDIA_TYPE_POR_EXTENSION.get(os.path.splitext(ruta)[1].lower(), "image/jpeg"))


def _abrir(ruta: str):
    """Abre la imagen con Pillow. Return None si no se puede (y lo deja en el log)."""
    try:
        from PIL import Image

        imagen = Image.open(ruta)
        imagen.load()
        return imagen
    except Exception as e:
        logger.warning(f"no se pudo abrir la imagen '{ruta}': {e}")
        return None


def _tiene_transparencia(imagen) -> bool:
    return imagen.mode in ("RGBA", "LA", "P") and (
        imagen.mode != "P" or "transparency" in imagen.info
    )


def _codificar(imagen, *, con_alfa: bool, calidad: int = 82) -> Tuple[bytes, str]:
    """Return `(bytes, media_type)`: PNG si hay transparencia, JPEG si no."""
    import io

    salida = io.BytesIO()
    if con_alfa:
        imagen.convert("RGBA").save(salida, format="PNG", optimize=True)
        return salida.getvalue(), "image/png"
    imagen.convert("RGB").save(salida, format="JPEG", quality=calidad, optimize=True)
    return salida.getvalue(), "image/jpeg"


def miniatura_data_url(ruta: Optional[str], lado: int = LADO_MINIATURA) -> str:
    """Return la imagen reducida a `lado` px como `data:` URL, o "" si no se pudo.

    Sirve para la burbuja del usuario y el chip del adjunto: la página no puede leer
    `file://` (CSP `img-src 'self' data:`), y así tampoco hace falta que pueda.
    """
    if not ruta or not os.path.isfile(ruta):
        return ""
    imagen = _abrir(ruta)
    if imagen is None:
        return ""
    try:
        con_alfa = _tiene_transparencia(imagen)
        imagen.thumbnail((lado, lado))
        datos, tipo = _codificar(imagen, con_alfa=con_alfa)
        return f"data:{tipo};base64," + base64.standard_b64encode(datos).decode("ascii")
    except Exception as e:
        logger.warning(f"no se pudo hacer la miniatura de '{ruta}': {e}")
        return ""


def preparar_para_el_modelo(ruta: Optional[str]) -> Optional[str]:
    """Return la ruta a mandar al modelo: la misma si entra en los límites, o una copia
    reducida en la carpeta temporal si no. Nunca lanza: ante cualquier fallo, la original.
    """
    if not ruta or not os.path.isfile(ruta):
        return ruta
    try:
        stat = os.stat(ruta)
    except OSError:
        return ruta
    clave = (os.path.abspath(ruta), stat.st_size, stat.st_mtime)
    reducida = _reducidas.get(clave)
    if reducida and os.path.isfile(reducida):
        return reducida

    imagen = _abrir(ruta)
    if imagen is None:
        return ruta
    try:
        lado_largo = max(imagen.size)
        if lado_largo <= LADO_MAXIMO_PARA_EL_MODELO and stat.st_size <= BYTES_MAXIMOS_PARA_EL_MODELO:
            return ruta

        # Los GIF animados van como su primer cuadro: ningún proveedor mira la animación.
        con_alfa = _tiene_transparencia(imagen)
        imagen.thumbnail((LADO_MAXIMO_PARA_EL_MODELO, LADO_MAXIMO_PARA_EL_MODELO))
        datos, tipo = _codificar(imagen, con_alfa=con_alfa)
        # Una captura con transparencia y muy pesada aún en PNG: se sacrifica el canal alfa
        # antes que fallar la subida.
        if len(datos) > BYTES_MAXIMOS_PARA_EL_MODELO:
            datos, tipo = _codificar(imagen, con_alfa=False, calidad=75)

        carpeta = os.path.join(tempfile.gettempdir(), "orion_imagenes")
        os.makedirs(carpeta, exist_ok=True)
        extension = ".png" if tipo == "image/png" else ".jpg"
        destino = os.path.join(
            carpeta, f"{os.path.splitext(os.path.basename(ruta))[0]}_{int(time.time())}{extension}",
        )
        with open(destino, "wb") as f:
            f.write(datos)
        _reducidas[clave] = destino
        logger.info(
            f"imagen reducida para el modelo: {ruta} ({lado_largo}px, {stat.st_size} B) -> "
            f"{destino} ({len(datos)} B)"
        )
        return destino
    except Exception as e:
        logger.warning(f"no se pudo reducir la imagen '{ruta}', va la original: {e}")
        return ruta


def carpeta_de_imagenes_pegadas(user_id: str = "owner") -> str:
    """Return la carpeta donde se guardan las imágenes pegadas del portapapeles.

    Van junto a los demás datos del usuario (`users_data/<id>/`, donde ya viven su memoria
    y su perfil), y no en la carpeta temporal: la burbuja las muestra cada vez que se
    reabre la conversación, así que tienen que durar lo que dura la conversación.
    """
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    carpeta = os.path.join(raiz, "users_data", user_id, "imagenes")
    os.makedirs(carpeta, exist_ok=True)
    return carpeta


def ruta_para_imagen_pegada(user_id: str = "owner", extension: str = ".png") -> str:
    """Return una ruta nueva y única para guardar una imagen pegada."""
    carpeta = carpeta_de_imagenes_pegadas(user_id)
    base = time.strftime("pegada_%Y%m%d_%H%M%S")
    ruta = os.path.join(carpeta, f"{base}{extension}")
    contador = 1
    while os.path.exists(ruta):
        ruta = os.path.join(carpeta, f"{base}_{contador}{extension}")
        contador += 1
    return ruta


class ImagenRechazada(Exception):
    """La ruta no es una imagen que el agente pueda mirar; el motivo se le puede decir al
    modelo tal cual."""


def _raices_para_mirar() -> list:
    """Return dónde puede haber imágenes que el agente mire por instrucción: la carpeta
    personal del usuario, los espacios de trabajo habilitados y las imágenes pegadas."""
    raices = [os.path.expanduser("~")]
    try:
        from core.workspace_config import cargar_raices

        raices += list(cargar_raices())
    except Exception as e:
        logger.debug(f"no se pudieron leer los espacios de trabajo: {e}")
    raiz_app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raices.append(os.path.join(raiz_app, "users_data"))
    return raices


def resolver_para_mirar(ruta: Optional[str]) -> str:
    """Return la ruta real de una imagen que el agente puede mirar (REQ-062).

    Levanta `ImagenRechazada` si no hay ruta, el archivo no existe, no es una imagen (por
    extensión Y por firma), o está fuera de la carpeta personal, de los espacios de
    trabajo habilitados y de las imágenes pegadas; y siempre si cae en una carpeta de
    configuración (`.ssh`, `AppData`, …). Es el mismo criterio que `core/documentos.py`
    para escribir, aplicado a leer: mirar una imagen es mandársela al proveedor del modelo.
    """
    from core.documentos import CARPETAS_VEDADAS

    texto = str(ruta or "").strip().strip('"')
    if not texto:
        raise ImagenRechazada("Necesito la ruta de la imagen.")
    candidata = os.path.expanduser(texto)
    if not os.path.isabs(candidata):
        # Relativa: al Escritorio, que es donde suele estar lo que se acaba de guardar.
        from core.documentos import _escritorio

        candidata = os.path.join(str(_escritorio()), candidata)
    real = os.path.realpath(candidata)

    # Primero el confinamiento, SIN tocar el disco (mismo orden que
    # `core/workspace_files.resolver`): una ruta fuera de las raíces o en una carpeta de
    # configuración se rechaza con el mismo mensaje exista o no, así el modelo no puede
    # sondear qué hay en el resto del disco a base de mensajes distintos.
    real_bajo = real.lower()
    for base in _raices_para_mirar():
        base_real = os.path.realpath(base).lower()
        try:
            if os.path.commonpath([real_bajo, base_real]) == base_real:
                break
        except ValueError:
            continue
    else:
        raise ImagenRechazada(
            "Solo miro imágenes de tu carpeta personal o de un espacio de trabajo habilitado."
        )
    partes = {p.lower() for p in real.split(os.sep)}
    if partes & CARPETAS_VEDADAS:
        raise ImagenRechazada(
            "Solo miro imágenes de tu carpeta personal o de un espacio de trabajo habilitado."
        )

    if not os.path.isfile(real):
        raise ImagenRechazada(f"No encuentro ninguna imagen en «{texto}».")
    if not es_imagen(real):
        raise ImagenRechazada(f"«{os.path.basename(real)}» no es una imagen (png, jpg, gif o webp).")
    if _tipo_por_firma(real) is None:
        raise ImagenRechazada(f"«{os.path.basename(real)}» tiene extensión de imagen pero no lo es.")
    return real


def marcar_adjunto(texto: str, ruta: str) -> str:
    """Return el texto con el marcador del adjunto al final.

    Para una imagen dice «Imagen adjunta»: el modelo la recibe como imagen en ese mismo
    turno, y en los turnos siguientes —donde ya no viaja— el marcador le recuerda que la
    hubo y dónde está.
    """
    plantilla = _MARCADOR_IMAGEN if es_imagen(ruta) else _MARCADOR_ARCHIVO
    return f"{texto}\n\n{plantilla.format(ruta=ruta)}"


def separar_adjunto(texto: Optional[str]) -> Tuple[str, Optional[str]]:
    """Return `(texto sin el marcador, ruta del adjunto o None)`.

    Es lo que usa la burbuja del usuario para mostrar una miniatura o un chip con el nombre
    en vez de la ruta cruda entre corchetes. Solo reconoce el marcador al final del mensaje,
    que es donde `marcar_adjunto` lo pone.
    """
    if not texto:
        return "", None
    coincidencia = _RE_MARCADOR.search(texto)
    if not coincidencia:
        return texto, None
    ruta = coincidencia.group("ruta").strip()
    return texto[:coincidencia.start()].rstrip(), ruta or None
