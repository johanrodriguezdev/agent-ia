"""
os_integration/web_search.py
Búsqueda en internet y lectura de páginas, para que el agente pueda responder con
información que no tenía.

Hasta aquí, lo único parecido a "buscar" era `os_integration/browser.py::search_google()`,
que **abre el navegador** con la consulta y devuelve "Búsqueda lanzada": no lee los
resultados, así que el agente nunca se enteraba de nada. Lo único que sí podía consultar
era Wikipedia. De ahí que cualquier pregunta acabara en un resumen enciclopédico o en nada.

Este módulo hace lo otro: consulta un buscador, trae los resultados como texto, y puede
abrir una página concreta y extraer su contenido legible. Lo que el modelo haga con eso
—responder, contrastar dos fuentes, decir que no encontró nada— ya es decisión suya.

Proveedor: DuckDuckGo, elegido por Johan porque no necesita clave ni registro. El módulo
está escrito para que añadir Brave o Tavily después sea sumar una función y una entrada en
`_PROVEEDORES`, sin tocar a los llamadores.

Todo lo que sale de aquí es **contenido no confiable**: lo escribe cualquiera en internet.
Se entrega siempre como texto plano etiquetado con su fuente, nunca como instrucciones, y
nunca se ejecuta nada de lo que venga dentro.
"""

import logging
import re
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Resultados que se piden por defecto. Suficiente para contrastar sin inflar el prompt.
MAX_RESULTADOS = 5

#: Tope de caracteres del texto extraído de una página. Una página larga puede tener cientos
#: de miles y no caben en el contexto del modelo.
MAX_CHARS_PAGINA = 6000

#: Segundos de espera. Corto a propósito: es mejor decir "no pude buscar" que dejar al
#: usuario esperando delante de un micrófono abierto.
TIMEOUT = 12

_ESPACIOS_RE = re.compile(r"[ \t\r\f\v]+")
_SALTOS_RE = re.compile(r"\n{3,}")


def _buscar_duckduckgo(consulta: str, max_resultados: int) -> List[Dict[str, str]]:
    """Return los resultados de DuckDuckGo. No necesita clave de API."""
    from ddgs import DDGS

    with DDGS(timeout=TIMEOUT) as ddgs:
        crudos = list(ddgs.text(consulta, max_results=max_resultados))

    resultados = []
    for r in crudos:
        titulo = (r.get("title") or "").strip()
        extracto = (r.get("body") or "").strip()
        url = (r.get("href") or r.get("url") or "").strip()
        if titulo or extracto:
            resultados.append({"titulo": titulo, "extracto": extracto, "url": url})
    return resultados


#: Proveedores disponibles. Añadir uno nuevo es sumar una función con esta misma firma.
_PROVEEDORES: Dict[str, Callable[[str, int], List[Dict[str, str]]]] = {
    "duckduckgo": _buscar_duckduckgo,
}

PROVEEDOR_POR_DEFECTO = "duckduckgo"


def buscar(consulta: str, max_resultados: int = MAX_RESULTADOS,
           proveedor: Optional[str] = None) -> List[Dict[str, str]]:
    """Return una lista de resultados, o vacía si la búsqueda no se pudo hacer.

    Nunca lanza: un fallo de red no debe tumbar el turno del usuario.
    """
    consulta = (consulta or "").strip()
    if not consulta:
        return []

    nombre = (proveedor or PROVEEDOR_POR_DEFECTO).lower()
    fn = _PROVEEDORES.get(nombre)
    if fn is None:
        logger.warning(f"Proveedor de búsqueda desconocido: '{nombre}'")
        return []

    try:
        return fn(consulta, max(1, min(int(max_resultados), 10)))
    except ImportError as e:
        logger.error(f"Falta la dependencia del buscador '{nombre}': {e}")
        return []
    except Exception as e:
        logger.warning(f"La búsqueda de '{consulta[:60]}' falló: {e}")
        return []


def formatear_resultados(resultados: List[Dict[str, str]], consulta: str) -> str:
    """Return los resultados como texto plano, con su fuente visible.

    El formato es deliberadamente sobrio y numerado: el modelo tiene que poder citar de
    dónde sacó cada dato, y el usuario tiene que poder comprobarlo.
    """
    if not resultados:
        return f"No encontré resultados en internet para «{consulta}»."

    lineas = [f"Resultados de búsqueda para «{consulta}»:", ""]
    for i, r in enumerate(resultados, 1):
        lineas.append(f"{i}. {r['titulo']}")
        if r["extracto"]:
            lineas.append(f"   {r['extracto']}")
        if r["url"]:
            lineas.append(f"   Fuente: {r['url']}")
        lineas.append("")
    return "\n".join(lineas).strip()


#: Páginas de un PDF que se leen. Un informe oficial puede tener doscientas y no caben; las
#: primeras traen el resumen ejecutivo, que es donde está la respuesta casi siempre.
MAX_PAGINAS_PDF = 15

#: Cuánto se deja descargar de un PDF. El tope general de `http_seguro` son 2 MB, pensado
#: para páginas web, y con un PDF no sirve de nada quedarse a medias: el índice que dice
#: dónde empieza cada página va **al final** del archivo, así que un PDF cortado no es un
#: PDF incompleto, es un PDF ilegible. Probado contra informes reales de Fedepalma y de la
#: Universidad Nacional: los dos fallaban con 2 MB.
#:
#: Sigue siendo un tope, que es lo que importa: la guarda existe para que una respuesta de
#: gigabytes no se coma la memoria, no para que sean exactamente dos megas.
MAX_BYTES_PDF = 8 * 1024 * 1024


#: Páginas de un PDF escaneado que se reconocen. Cada una es dibujarla y pasarla por el
#: OCR —alrededor de un segundo—, y en un escaneo el resumen también está al principio.
MAX_PAGINAS_OCR = 5


def _ocr_pdf(crudo: bytes, max_paginas: int = MAX_PAGINAS_OCR) -> str:
    """Return el texto reconocido en las primeras páginas de un PDF sin texto, o vacío.

    Hace falta dibujar cada página como imagen (PyMuPDF) y reconocerla (el OCR de
    Windows). Si falta cualquiera de las dos cosas se devuelve vacío y el llamador lo
    cuenta como escaneo ilegible, que es la verdad en ese equipo.
    """
    try:
        import pymupdf
    except ImportError:
        logger.info("PyMuPDF no está instalado: un PDF escaneado no se puede reconocer")
        return ""
    from os_integration.ocr import disponible, leer_imagen

    if not disponible():
        return ""

    import os
    import tempfile

    trozos = []
    try:
        documento = pymupdf.open(stream=crudo, filetype="pdf")
    except Exception as e:
        logger.debug(f"PyMuPDF no pudo abrir el PDF para reconocerlo: {e}")
        return ""
    try:
        for numero, pagina in enumerate(documento):
            if numero >= max_paginas:
                break
            ruta = os.path.join(tempfile.gettempdir(), f"orion_ocr_pdf_{numero}.png")
            try:
                pagina.get_pixmap(dpi=150).save(ruta)
                leido = leer_imagen(ruta)
            finally:
                try:
                    os.remove(ruta)
                except OSError:
                    pass
            if leido:
                trozos.append(leido)
    except Exception as e:
        logger.warning(f"el reconocimiento del PDF se cortó: {e}")
    finally:
        documento.close()
    return "\n\n".join(trozos)


def _extraer_pdf(respuesta, url: str, max_chars: int) -> Dict[str, str]:
    """Return el texto de un PDF descargado. Mismo formato que el resto de páginas.

    Media fuente autorizada vive en PDF —informes de un ministerio, papers, circulares— y
    hasta acá se descartaban por no ser HTML: el agente veía el enlace en los resultados y
    no podía abrirlo.

    Un PDF escaneado no tiene texto, solo imágenes, y eso no se puede arreglar leyendo: se
    dice, en vez de devolver una página en blanco como si no hubiera nada que contar.
    """
    vacio = {"ok": False, "url": url, "titulo": "", "fecha": "", "texto": "", "error": ""}
    try:
        from PyPDF2 import PdfReader
    except ImportError as e:
        logger.warning(f"no hay con qué leer PDFs: {e}")
        vacio["error"] = "No tengo instalado lo necesario para leer archivos PDF."
        return vacio

    import io as _io

    try:
        lector = PdfReader(_io.BytesIO(respuesta.crudo))
        paginas = [(p.extract_text() or "") for p in lector.pages[:MAX_PAGINAS_PDF]]
    except Exception as e:
        logger.warning(f"no se pudo leer el PDF '{url[:70]}': {e}")
        if getattr(respuesta, "truncada", False):
            # El indice de un PDF va al final: cortado por tamano no es incompleto, es
            # ilegible. Decirlo asi permite al modelo buscar otra fuente en vez de insistir.
            vacio["error"] = (f"Ese PDF pesa mas de {MAX_BYTES_PDF // (1024 * 1024)} MB y "
                              f"solo pude descargar el principio, con lo que no se puede "
                              f"abrir. Haria falta otra fuente.")
        else:
            vacio["error"] = "Pude descargar el PDF pero no entender su contenido."
        return vacio

    texto = "\n".join(p.strip() for p in paginas if p.strip())
    texto = _ESPACIOS_RE.sub(" ", texto)
    texto = "\n".join(linea.strip() for linea in texto.splitlines() if linea.strip())
    texto = _SALTOS_RE.sub("\n\n", texto).strip()

    escaneado = False
    if not texto:
        # Un escaneo son imágenes: no hay texto que extraer, pero sí que RECONOCER. Se
        # dibujan las primeras páginas y se pasan por el OCR de Windows. Sale marcado como
        # leído por OCR porque puede traer errores; es incomparablemente mejor que "no se
        # puede", que era lo que había.
        texto = _ocr_pdf(respuesta.crudo)
        escaneado = bool(texto)
        if not texto:
            vacio["error"] = ("Ese PDF no trae texto: es un escaneo o son imágenes, y el "
                              "reconocimiento de texto tampoco sacó nada legible.")
            return vacio

    titulo, fecha = "", ""
    try:
        datos = lector.metadata or {}
        titulo = (datos.get("/Title") or "").strip()
        fecha = (datos.get("/CreationDate") or "")[2:10]   # D:20260910... -> 20260910
    except Exception as e:
        logger.debug(f"el PDF no declara título ni fecha: {e}")

    if escaneado:
        texto = ("[Texto reconocido por OCR de un PDF escaneado: puede tener errores de "
                 "lectura]\n" + texto)
    if respuesta.truncada:
        texto += "\n\n[...el PDF era grande y se descargó solo el principio...]"
    if len(texto) > max_chars:
        texto = texto[:max_chars].rsplit(" ", 1)[0] + "\n\n[...contenido truncado...]"

    return {"ok": True, "url": url, "titulo": titulo, "fecha": fecha,
            "texto": texto, "error": ""}


#: Lo que se le dice al modelo cuando una página no se puede leer sin sesión. Importa que
#: nombre el camino: el navegador del usuario YA tiene la sesión iniciada, y `browser_text`
#: lee lo que se ve en él. Sin esto, "no pude leerla" se quedaba en un callejón.
_AVISO_DE_SESION = (
    "Esa página pide iniciar sesión ({motivo}) y por acá entro sin credenciales. Si la "
    "abrís en tu navegador —donde ya tenés la sesión— la leo con 'browser_text', o "
    "decime que la abra yo con 'browser_open'."
)

#: Con menos texto que esto, un formulario de acceso ES la página. Con más, es una página
#: normal que además tiene un cuadro de "iniciar sesión" en la esquina, como casi todas.
_POCO_TEXTO_PARA_SER_MURO = 700

#: Trozos de dirección que delatan una pantalla de acceso, cuando la página redirige a una.
_RUTAS_DE_ACCESO = ("login", "signin", "sign-in", "iniciar-sesion", "acceder", "/auth",
                    "account/login", "sesion")


def _pide_sesion(sopa, url_final: str) -> bool:
    """Return True si lo descargado parece un muro de acceso y no el contenido.

    Dos señales, y hace falta cualquiera: un campo de contraseña en la página, o que la
    dirección FINAL —tras las redirecciones— sea la de una pantalla de acceso. El llamador
    exige además que haya poco texto, porque un campo de contraseña en una esquina lo tiene
    media internet.
    """
    try:
        if sopa.find("input", attrs={"type": "password"}) is not None:
            return True
    except Exception as e:
        # Una sopa rota o que no es una sopa: se decide solo por la dirección. Se registra
        # porque un muro de acceso que no se detecta acaba como "página sin contenido".
        logger.debug(f"no se pudo buscar el campo de contraseña en la página: {e}")
    camino = (url_final or "").lower()
    return any(marca in camino for marca in _RUTAS_DE_ACCESO)


def extraer_pagina(url: str, max_chars: int = MAX_CHARS_PAGINA) -> Dict[str, str]:
    """Return `{ok, url, titulo, fecha, texto, error}` de una página.

    Es el trabajo real de `leer_pagina`, separado para que una investigación pueda leer
    varias páginas a la vez y quedarse además con el título y la fecha — que a la hora de
    contrastar fuentes importan tanto como el texto. `leer_pagina` no cambió: sigue
    devolviendo el mismo texto, y los mismos mensajes cuando algo falla.
    """
    vacio = {"ok": False, "url": url, "titulo": "", "fecha": "", "texto": "", "error": ""}

    url = (url or "").strip()
    vacio["url"] = url
    if not url.startswith(("http://", "https://")):
        vacio["error"] = "Solo puedo leer direcciones que empiecen por http:// o https://."
        return vacio

    try:
        import requests  # noqa: F401 — lo usa `core.http_seguro`; se chequea acá para el aviso claro
        from bs4 import BeautifulSoup
    except ImportError as e:
        logger.error(f"Falta una dependencia para leer páginas: {e}")
        vacio["error"] = "No tengo instalado lo necesario para leer páginas web."
        return vacio

    # REQ-031 — el destino se valida antes de conectarse, y en cada redirección. Antes acá
    # había un `requests.get()` pelado: alcanzaba con pedir `http://127.0.0.1:3000` o
    # `http://192.168.1.1` para que el agente leyera un servicio interno y devolviera el
    # contenido al chat. Y como `web_read` es verde, eso era alcanzable desde Telegram.
    from core.http_seguro import DestinoBloqueado, pedir

    # El tope se decide ANTES de pedir, y lo unico que se sabe antes es la direccion.
    # Un PDF servido sin ".pdf" en la URL se descarga con el tope normal y, si se corta,
    # se vuelve a pedir con el grande: una peticion de mas solo en ese caso.
    tope = MAX_BYTES_PDF if url.lower().endswith(".pdf") else None

    try:
        respuesta = pedir(url, timeout=TIMEOUT, **({"max_bytes": tope} if tope else {}))
        if (respuesta.truncada and tope is None
                and "pdf" in (respuesta.content_type or "").lower()):
            logger.info(f"'{url[:60]}' era un PDF cortado: se vuelve a pedir entero")
            respuesta = pedir(url, timeout=TIMEOUT, max_bytes=MAX_BYTES_PDF)
    except DestinoBloqueado as e:
        logger.info(f"lectura de página rechazada por destino no permitido: {e}")
        vacio["error"] = str(e)
        return vacio
    except Exception as e:
        logger.warning(f"No se pudo descargar '{url[:80]}': {e}")
        vacio["error"] = f"No pude abrir esa página: {type(e).__name__}."
        return vacio

    if respuesta.status in (401, 403):
        # No es un error de la página: es que no deja entrar sin credenciales, o bloquea
        # lecturas automáticas. En el navegador del usuario la sesión ya está iniciada, y
        # `browser_text` lee lo que se ve: ese es el camino, y hay que decirlo.
        vacio["error"] = _AVISO_DE_SESION.format(motivo=f"respondió {respuesta.status}")
        vacio["sesion"] = True
        return vacio
    if respuesta.status >= 400:
        vacio["error"] = f"Esa página respondió con un error {respuesta.status}."
        return vacio

    tipo = respuesta.content_type
    if "pdf" in tipo.lower() or url.lower().endswith(".pdf"):
        return _extraer_pdf(respuesta, url, max_chars)

    if "html" not in tipo and "text" not in tipo:
        vacio["error"] = (f"Esa dirección no es una página de texto "
                          f"(es {tipo or 'de tipo desconocido'}).")
        return vacio

    try:
        sopa = BeautifulSoup(respuesta.texto, "html.parser")
        titulo = (sopa.title.get_text().strip() if sopa.title else "")
        fecha = _fecha_publicada(sopa)
        # Se mira ANTES de quitar los formularios: el campo de contraseña vive en uno.
        muro = _pide_sesion(sopa, getattr(respuesta, "url_final", "") or url)
        for etiqueta in sopa(["script", "style", "nav", "footer", "header", "aside", "form"]):
            etiqueta.decompose()
        texto = sopa.get_text("\n")
    except Exception as e:
        logger.warning(f"No se pudo extraer el texto de '{url[:80]}': {e}")
        vacio["error"] = "Pude descargar la página pero no entender su contenido."
        return vacio

    texto = _ESPACIOS_RE.sub(" ", texto)
    texto = "\n".join(linea.strip() for linea in texto.splitlines() if linea.strip())
    texto = _SALTOS_RE.sub("\n\n", texto).strip()

    if muro and len(texto) < _POCO_TEXTO_PARA_SER_MURO:
        vacio["error"] = _AVISO_DE_SESION.format(motivo="muestra un formulario de acceso")
        vacio["sesion"] = True
        return vacio

    if not texto:
        vacio["error"] = "Esa página no tiene texto legible."
        return vacio

    if len(texto) > max_chars:
        texto = texto[:max_chars].rsplit(" ", 1)[0] + "\n\n[...contenido truncado...]"

    return {"ok": True, "url": url, "titulo": titulo, "fecha": fecha,
            "texto": texto, "error": ""}


#: De dónde se saca la fecha de publicación, en orden de fiabilidad. Ninguna es obligatoria:
#: media web no la publica, y para contrastar fuentes es mejor "sin fecha" que una inventada.
_METAS_DE_FECHA = (
    ("meta", {"property": "article:published_time"}, "content"),
    ("meta", {"name": "date"}, "content"),
    ("meta", {"name": "pubdate"}, "content"),
    ("meta", {"itemprop": "datePublished"}, "content"),
    ("time", {"datetime": True}, "datetime"),
)


def _fecha_publicada(sopa) -> str:
    """Return la fecha de publicación declarada por la página, o cadena vacía.

    Importa para investigar: dos fuentes que dicen cosas distintas pueden no estar en
    desacuerdo, sino separadas por dos años.
    """
    for etiqueta, atributos, campo in _METAS_DE_FECHA:
        try:
            hallado = sopa.find(etiqueta, attrs=atributos)
        except Exception:
            continue
        if hallado:
            valor = (hallado.get(campo) or "").strip()
            if valor:
                return valor[:10]            # basta el día: 2026-09-10
    return ""


def leer_pagina(url: str, max_chars: int = MAX_CHARS_PAGINA) -> str:
    """Return el texto legible de una página, o un mensaje de error.

    Se descartan `script`, `style`, navegación y pies: lo que interesa es la prosa. Sin una
    librería de extracción dedicada esto no es perfecto, pero es suficiente para que el
    modelo lea un artículo y responda con él.
    """
    pagina = extraer_pagina(url, max_chars)
    if not pagina["ok"]:
        return pagina["error"]
    return f"Contenido de {pagina['url']}:\n\n{pagina['texto']}"
