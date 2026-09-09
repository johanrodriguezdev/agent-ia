"""
core/workspace_config.py
REQ-029 — Persistencia de las CARPETAS que el humano habilita para que el agente pueda
leer, buscar, escribir y consultar git dentro de ellas (`code_workspaces.json`).

Calcado de `core/security_config.py` (REQ-019) a propósito, y por el mismo motivo:
archivo propio, separado de `config.json`, con escritura atómica y **fail-closed**. Un
archivo ausente, corrupto, con un JSON que no es una lista, o con una entrada que no es
una carpeta existente, se interpreta SIEMPRE como "sin raíces habilitadas" — nunca como
"sin restricciones" (SPEC-029/CA-02, mismo criterio que REQ-019/CA-06).

El peor caso posible de este módulo es la lista vacía, y la lista vacía significa que el
agente no puede tocar ningún archivo de la máquina. Por eso la feature NACE INERTE: hasta
que alguien agregue una raíz a mano, las 8 herramientas están registradas pero no operan
sobre nada. Es deliberado — ver `desarrollo-log-029.md` para cómo se habilita la primera.

Este módulo NO decide qué rutas son alcanzables: solo dice qué raíces declaró el humano.
El confinamiento real (realpath + comparación por segmentos + exclusión del directorio de
instalación de O.R.I.O.N.) vive en `core/workspace_files.py::resolver()`, que es la única
función que convierte una ruta pedida por el modelo en una ruta real.
"""

import json
import logging
import os
import tempfile
from typing import List

logger = logging.getLogger(__name__)

CODE_WORKSPACES_FILE = os.path.join(os.path.dirname(__file__), "..", "code_workspaces.json")


def cargar_raices() -> List[str]:
    """Devuelve las raíces habilitadas, ya resueltas con `realpath` y deduplicadas.

    Nunca lanza y nunca devuelve algo que no sea una carpeta existente (CA-02). El peor
    caso es `[]`, que significa "el agente no toca nada".
    """
    if not os.path.exists(CODE_WORKSPACES_FILE):
        # No es un error: es el estado de fábrica. La feature nace inerte.
        return []
    try:
        with open(CODE_WORKSPACES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        # `except Exception` amplio por el mismo motivo documentado en
        # `core/security_config.py`: `UnicodeDecodeError` (archivo truncado a mitad de
        # escritura, bytes no-UTF-8) no es ni `OSError` ni `json.JSONDecodeError`. No es
        # un `except: pass` — se loguea y se cae al lado seguro.
        logger.warning(
            f"code_workspaces.json corrupto/ilegible ({type(e).__name__}) — se ignora por "
            f"completo, el agente queda sin carpetas habilitadas: {e}"
        )
        return []

    entradas = _extraer_lista(raw)
    if entradas is None:
        return []

    raices: List[str] = []
    vistas = set()
    for entrada in entradas:
        real = _validar_raiz(entrada)
        if real is None:
            continue
        clave = os.path.normcase(real)
        if clave in vistas:
            continue
        vistas.add(clave)
        raices.append(real)
    return raices


def guardar_raices(raices: List[str]) -> None:
    """Persiste la lista completa de raíces en UNA sola escritura atómica.

    Guarda solo las que pasan la misma validación que `cargar_raices()`: si se escribiera
    una entrada inválida, el archivo quedaría con algo que la carga siguiente descarta,
    y el usuario creería tener habilitada una carpeta que no lo está.
    """
    validas: List[str] = []
    vistas = set()
    for entrada in raices or []:
        real = _validar_raiz(entrada)
        if real is None:
            continue
        clave = os.path.normcase(real)
        if clave in vistas:
            continue
        vistas.add(clave)
        validas.append(real)
    _atomic_write(validas)


def _extraer_lista(raw: object) -> "List[object] | None":
    """Acepta `["ruta", ...]` o `{"raices": ["ruta", ...]}`. Cualquier otra forma es None.

    Las dos formas se admiten porque el archivo lo escribe una persona a mano en v1: la
    lista pelada es lo mínimo, y el objeto con clave deja lugar a agregarle campos más
    adelante sin romper los archivos ya escritos.
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        entradas = raw.get("raices")
        if isinstance(entradas, list):
            return entradas
        logger.warning(
            "code_workspaces.json es un objeto pero no trae una lista en 'raices' — se ignora"
        )
        return None
    logger.warning(
        "code_workspaces.json no es una lista ni un objeto con 'raices' — se ignora por completo"
    )
    return None


def _validar_raiz(entrada: object) -> "str | None":
    """Devuelve el `realpath` de la entrada si es una carpeta existente, o None.

    Descartar y seguir (en vez de invalidar el archivo entero) es deliberado: una raíz que
    quedó apuntando a un disco desconectado no debería dejar sin herramientas a las otras.
    Descartar NUNCA agrega permisos, solo los quita.
    """
    if not isinstance(entrada, str) or not entrada.strip():
        logger.warning(f"Entrada inválida en code_workspaces.json ignorada: {entrada!r}")
        return None
    try:
        real = os.path.realpath(os.path.expanduser(entrada.strip()))
    except (OSError, ValueError) as e:
        logger.warning(f"No se pudo resolver la raíz {entrada!r} de code_workspaces.json: {e}")
        return None
    if not os.path.isdir(real):
        logger.warning(
            f"La raíz {entrada!r} de code_workspaces.json no es una carpeta existente — ignorada"
        )
        return None
    return real


def _atomic_write(raices: List[str]) -> None:
    directory = os.path.dirname(os.path.abspath(CODE_WORKSPACES_FILE)) or "."
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".code_workspaces_", dir=directory)
    except OSError as e:
        logger.error(f"No se pudo crear archivo temporal para guardar code_workspaces.json: {e}")
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(raices, f, indent=2)
        os.replace(tmp_path, CODE_WORKSPACES_FILE)  # atómico en Windows (MoveFileEx) y POSIX
    except OSError as e:
        logger.error(f"No se pudo guardar code_workspaces.json: {e}")
        try:
            os.remove(tmp_path)
        except OSError as e2:
            logger.debug(f"quedó un temporal sin borrar: {e2}")
