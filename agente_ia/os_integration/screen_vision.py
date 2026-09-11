"""
os_integration/screen_vision.py
Mirar la pantalla y entender lo que hay, para poder actuar sobre ello.

Las herramientas de escritorio que ya existen saben escribir y hacer clic, pero a ciegas:
hay que darles las coordenadas exactas. Eso sirve cuando el usuario está delante y las
conoce; no sirve para el caso que las motivó, que es justo el contrario — estar lejos del
equipo y pedirle al agente que mire y decida.

Este módulo cierra ese hueco: captura la pantalla, se la enseña a un modelo con visión, y
devuelve lo que hay o dónde está algo concreto.

La lección que se toma de OpenClaw, y que no es evidente hasta que muerde:

> *"A token is not a freshness guarantee: apps can change pixels on the same display after
> capture, so take a new screenshot whenever the scene may have changed."*

Una coordenada solo significa algo respecto de la captura de la que salió. Si entre mirar y
hacer clic la pantalla cambió —apareció un diálogo, se movió una ventana, cambió de
pestaña— ese clic aterriza en otro sitio, y con el ratón eso no es un error recuperable:
es haber pulsado algo que nadie eligió. Por eso cada captura lleva un identificador, y
`pc_click` exige el de la última: las coordenadas viejas se rechazan en vez de ejecutarse.
"""

import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

#: Segundos tras los cuales una captura deja de servir para calcular un clic. Medio minuto
#: es de sobra para que el modelo la mire y responda, y poco para que la pantalla haya
#: cambiado sin que nadie se entere.
FRESCURA_SEGUNDOS = 30.0

#: Dónde se guardan las capturas. Directorio temporal del sistema: son efímeras y pueden
#: contener cualquier cosa que hubiera en pantalla.
_DIR_CAPTURAS = os.path.join(tempfile.gettempdir(), "orion_capturas")


@dataclass(frozen=True)
class Captura:
    """Una foto de la pantalla, con lo necesario para saber si sigue siendo válida."""

    frame_id: str
    ruta: str
    ancho: int
    alto: int
    tomada_en: float
    #: Dónde cae el píxel (0, 0) de la imagen dentro del escritorio. Con un solo monitor es
    #: (0, 0); con dos, el segundo puede empezar en x=2880, y un clic calculado sobre su
    #: captura sin este desplazamiento aterriza en el monitor equivocado.
    origen_x: int = 0
    origen_y: int = 0

    def esta_fresca(self, ahora: Optional[float] = None) -> bool:
        t = ahora if ahora is not None else time.monotonic()
        return (t - self.tomada_en) <= FRESCURA_SEGUNDOS


_ultima: Optional[Captura] = None
_lock = threading.Lock()


def ultima_captura() -> Optional[Captura]:
    with _lock:
        return _ultima


def _capturar_monitor_activo():
    """Return `(imagen, (x, y))` del monitor donde está la ventana activa, o `(None, (0, 0))`.

    `pyautogui.screenshot()` fotografía solo el monitor principal. Con dos monitores, todo
    lo que el usuario tenga en el segundo es invisible para el agente: `pc_look` lo
    describía como si no existiera, y se descubrió porque el OCR de una ventana en x=2880
    devolvía cero caracteres de una captura en negro.

    Se captura el monitor de la ventana activa, no el escritorio entero: dos pantallas
    pegadas son una imagen enorme que el modelo con visión reduce, y con eso pierde la
    precisión para localizar un botón. Y se devuelve el origen, porque las coordenadas de
    la imagen solo valen para hacer clic si se les suma dónde empieza ese monitor.
    """
    if os.name != "nt":
        return None, (0, 0)
    try:
        import ctypes
        import ctypes.wintypes as wt

        from PIL import ImageGrab

        class _INFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                        ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

        u32 = ctypes.windll.user32
        hwnd = u32.GetForegroundWindow()
        monitor = u32.MonitorFromWindow(hwnd, 2)          # MONITOR_DEFAULTTONEAREST
        info = _INFO(cbSize=ctypes.sizeof(_INFO))
        if not monitor or not u32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None, (0, 0)
        r = info.rcMonitor
        imagen = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
        return imagen, (r.left, r.top)
    except Exception as e:
        logger.debug(f"no se pudo capturar el monitor activo, se usa el principal: {e}")
        return None, (0, 0)


def capturar() -> Optional[Captura]:
    """Toma una captura y la registra como la vigente. Return `None` si no se pudo."""
    global _ultima

    try:
        import pyautogui
    except ImportError:
        logger.error("pyautogui no está instalado: no se puede capturar la pantalla")
        return None

    origen = (0, 0)
    try:
        os.makedirs(_DIR_CAPTURAS, exist_ok=True)
        imagen, origen = _capturar_monitor_activo()
        if imagen is None:
            imagen = pyautogui.screenshot()
            origen = (0, 0)
        frame_id = f"f{int(time.time() * 1000) % 1_000_000:06d}"
        ruta = os.path.join(_DIR_CAPTURAS, f"{frame_id}.png")
        imagen.save(ruta)
    except Exception as e:
        logger.warning(f"No se pudo capturar la pantalla: {e}")
        return None

    captura = Captura(
        frame_id=frame_id, ruta=ruta,
        ancho=imagen.width, alto=imagen.height, tomada_en=time.monotonic(),
        origen_x=origen[0], origen_y=origen[1],
    )
    with _lock:
        _ultima = captura
    logger.info(f"[Pantalla] captura {frame_id} ({imagen.width}x{imagen.height})")
    return captura


def validar_para_clic(frame_id: str) -> Tuple[bool, str]:
    """Return si se puede hacer clic con coordenadas de esa captura, y por qué no si no.

    Tres cosas distintas que fallan distinto, y por eso se distinguen en el mensaje: no hay
    ninguna captura, hay otra más nueva, o la que se cita ya caducó.
    """
    actual = ultima_captura()
    if actual is None:
        return False, "No hay ninguna captura reciente. Toma una antes de calcular el clic."
    if not frame_id:
        return False, f"Falta indicar de qué captura salen las coordenadas (la última es {actual.frame_id})."
    if frame_id != actual.frame_id:
        return False, (
            f"Esas coordenadas son de la captura {frame_id}, pero la última es "
            f"{actual.frame_id}. La pantalla pudo cambiar: toma una nueva."
        )
    if not actual.esta_fresca():
        return False, (
            f"La captura {frame_id} tiene más de {FRESCURA_SEGUNDOS:.0f} segundos. "
            f"Toma una nueva antes de hacer clic."
        )
    return True, ""


_PROMPT_DESCRIBIR = (
    "Estás mirando una captura de la pantalla del ordenador del usuario, que no está "
    "delante del equipo. Describe qué hay: qué aplicación está en primer plano, qué se ve "
    "en ella, y si hay algo que requiera su atención (un diálogo abierto, una pregunta "
    "esperando respuesta, un error). Sé concreto y breve. Si hay texto relevante, cítalo."
)

_PROMPT_LOCALIZAR = (
    "Estás mirando una captura de pantalla de {ancho}x{alto} píxeles. Localiza este "
    "elemento: «{objetivo}».\n\n"
    "Responde EXACTAMENTE en este formato y nada más:\n"
    "ENCONTRADO x,y\n"
    "donde x e y son las coordenadas en píxeles del CENTRO del elemento.\n\n"
    "Si no lo ves con seguridad, responde exactamente:\n"
    "NO ENCONTRADO\n\n"
    "No inventes coordenadas: es preferible decir que no lo ves a hacer clic en el sitio "
    "equivocado."
)


def _hay_vision() -> bool:
    from ai.llm_provider import get_provider_config

    _, vision_provider, _, _ = get_provider_config()
    return bool(vision_provider)


def describir(captura: Captura) -> str:
    """Return una descripción de lo que se ve, o un aviso si no hay visión configurada."""
    if not _hay_vision():
        return (
            "No tengo configurado ningún proveedor con visión, así que no puedo interpretar "
            "la captura. La imagen está tomada, pero no puedo decirle qué hay en ella."
        )

    from ai.llm_provider import generate_response

    try:
        respuesta = generate_response(
            [{"role": "user", "content": _PROMPT_DESCRIBIR}],
            "Describes capturas de pantalla con precisión y brevedad.",
            image_path=captura.ruta,
        )
    except Exception as e:
        logger.warning(f"Fallo describiendo la captura: {e}")
        return f"Tomé la captura pero no pude interpretarla: {e}"

    return respuesta if isinstance(respuesta, str) else str(respuesta)


def localizar(captura: Captura, objetivo: str) -> Tuple[Optional[Tuple[int, int]], str]:
    """Return las coordenadas del elemento buscado, o `None` y el motivo.

    Se valida que lo devuelto caiga dentro de la pantalla: un modelo puede alucinar un par
    de números, y un clic en una coordenada inventada es indistinguible de uno deliberado.
    """
    if not _hay_vision():
        return None, "No tengo configurado ningún proveedor con visión para mirar la pantalla."

    from ai.llm_provider import generate_response

    prompt = _PROMPT_LOCALIZAR.format(
        ancho=captura.ancho, alto=captura.alto, objetivo=objetivo,
    )
    try:
        respuesta = generate_response(
            [{"role": "user", "content": prompt}],
            "Localizas elementos en capturas de pantalla. Respondes solo con el formato pedido.",
            image_path=captura.ruta,
        )
    except Exception as e:
        logger.warning(f"Fallo localizando '{objetivo}': {e}")
        return None, f"No pude analizar la captura: {e}"

    texto = (respuesta if isinstance(respuesta, str) else str(respuesta)).strip()
    if "NO ENCONTRADO" in texto.upper():
        return None, f"No encontré «{objetivo}» en la pantalla."

    import re

    match = re.search(r"(\d{1,5})\s*,\s*(\d{1,5})", texto)
    if not match:
        logger.info(f"Respuesta de localización sin coordenadas: {texto[:80]}")
        return None, f"No pude determinar dónde está «{objetivo}»."

    x, y = int(match.group(1)), int(match.group(2))
    if not (0 <= x < captura.ancho and 0 <= y < captura.alto):
        logger.warning(f"Coordenadas fuera de pantalla para '{objetivo}': ({x},{y})")
        return None, (
            f"Las coordenadas que obtuve para «{objetivo}» ({x},{y}) caen fuera de la "
            f"pantalla de {captura.ancho}x{captura.alto}. No hago clic a ciegas."
        )

    # Se devuelven en coordenadas del escritorio, no de la imagen: si la captura es del
    # segundo monitor, el clic tiene que sumarle dónde empieza ese monitor.
    return (x + captura.origen_x, y + captura.origen_y), ""
