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

    try:
        respuesta = pedir(url, timeout=TIMEOUT)
    except DestinoBloqueado as e:
        logger.info(f"lectura de página rechazada por destino no permitido: {e}")
        vacio["error"] = str(e)
        return vacio
    except Exception as e:
        logger.warning(f"No se pudo descargar '{url[:80]}': {e}")
        vacio["error"] = f"No pude abrir esa página: {type(e).__name__}."
        return vacio

    if respuesta.status >= 400:
        vacio["error"] = f"Esa página respondió con un error {respuesta.status}."
        return vacio

    tipo = respuesta.content_type
    if "html" not in tipo and "text" not in tipo:
        vacio["error"] = (f"Esa dirección no es una página de texto "
                          f"(es {tipo or 'de tipo desconocido'}).")
        return vacio

    try:
        sopa = BeautifulSoup(respuesta.texto, "html.parser")
        titulo = (sopa.title.get_text().strip() if sopa.title else "")
        fecha = _fecha_publicada(sopa)
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
