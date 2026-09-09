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


# ─────────────────────────────────────────────
#  REQ-030 — habilitar carpetas por instrucción, no editando el JSON a mano
# ─────────────────────────────────────────────

class RaizRechazada(Exception):
    """La carpeta pedida no puede habilitarse. El mensaje explica por qué, en castellano."""


#: Carpetas que no se habilitan **aunque el humano confirme el modal**. Habilitar la raíz de
#: un disco o una carpeta del sistema equivale a no tener confinamiento: bastaría un "sí"
#: distraído para que las 8 herramientas de REQ-029 alcancen el disco entero. Que la decisión
#: pase por una confirmación no alcanza como control cuando el resultado es irreversible en
#: la práctica: quien confirma no ve las consecuencias, ve una ruta.
_NOMBRES_DE_SISTEMA = frozenset({
    "windows", "program files", "program files (x86)", "programdata",
    "system32", "syswow64", "$recycle.bin",
})
#: `appdata` estuvo en esa lista y se sacó: ahí viven las carpetas temporales del sistema
#: (`AppData\\Local\\Temp`), así que bloquearla entera rompía cualquier prueba con `tmp_path`
#: y cualquier proyecto que alguien tenga ahí. Lo que sí se bloquea es la carpeta personal
#: ENTERA (ver `_es_carpeta_personal_entera`), que es el caso realmente peligroso: contiene
#: AppData, `.ssh`, `.aws` y todo lo demás de una sola vez.


def _es_carpeta_de_sistema(real: str) -> bool:
    """Return True si algún segmento de la ruta es una carpeta de sistema conocida."""
    partes = [p for p in os.path.normcase(real).replace("\\", "/").split("/") if p]
    return any(p in _NOMBRES_DE_SISTEMA for p in partes)


def _es_carpeta_personal_entera(real: str) -> bool:
    """Return True si la ruta es la carpeta personal del usuario, o la que las contiene.

    Habilitar `C:\\Users\\alguien` es casi tan amplio como habilitar el disco: adentro están
    `.ssh`, `.aws`, los perfiles del navegador y AppData. Se bloquea la carpeta EN SÍ, no lo
    que hay dentro: `Documents\\repos` sigue siendo perfectamente habilitable.
    """
    try:
        personal = os.path.realpath(os.path.expanduser("~"))
    except (OSError, ValueError) as e:
        logger.warning(f"no se pudo resolver la carpeta personal: {e}")
        return False
    normal = os.path.normcase(real)
    return normal in (os.path.normcase(personal), os.path.normcase(os.path.dirname(personal)))


def _es_raiz_de_unidad(real: str) -> bool:
    """Return True si la ruta es la raíz de un disco (`C:\\`, `/`)."""
    return os.path.dirname(real) == real


def _normalizada(ruta: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.expanduser(str(ruta or "").strip())))


def agregar_raiz(carpeta: str) -> str:
    """Habilita `carpeta` para las herramientas de repositorio. Return la ruta real.

    Levanta `RaizRechazada` con el motivo en castellano si no corresponde habilitarla. Es
    idempotente: pedir una que ya estaba no duplica ni falla.
    """
    texto = str(carpeta or "").strip()
    if not texto:
        raise RaizRechazada("No me dijiste qué carpeta habilitar.")
    try:
        real = os.path.realpath(os.path.expanduser(texto))
    except (OSError, ValueError) as e:
        logger.warning(f"no se pudo resolver la carpeta a habilitar {carpeta!r}: {e}")
        raise RaizRechazada(f"No pude resolver la ruta «{carpeta}».") from e

    if not os.path.isdir(real):
        raise RaizRechazada(f"«{carpeta}» no es una carpeta que exista en este equipo.")
    if _es_raiz_de_unidad(real):
        raise RaizRechazada(
            f"«{real}» es la raíz de un disco entero, y habilitarla dejaría el confinamiento "
            f"sin sentido. Elegí la carpeta del proyecto, no el disco."
        )
    if _es_carpeta_de_sistema(real):
        raise RaizRechazada(
            f"«{real}» está dentro de una carpeta del sistema y no se habilita."
        )
    if _es_carpeta_personal_entera(real):
        raise RaizRechazada(
            f"«{real}» es tu carpeta personal entera, y adentro están tus llaves y perfiles. "
            f"Elegí la carpeta del proyecto: por ejemplo la de Documentos donde tengas el repo."
        )

    from core.workspace_files import es_codigo_de_orion

    if es_codigo_de_orion(real):
        logger.critical(
            f"Intento de habilitar el código de O.R.I.O.N. como carpeta de trabajo: {real!r}. "
            f"Bloqueado en código (REQ-029/CA-03); modify_source_code es 🔴 RED."
        )
        raise RaizRechazada(
            "Esa es la carpeta de mi propio código, y no puedo trabajar sobre ella: "
            "modificarlo es una acción de riesgo alto que no se autoriza por esta vía."
        )

    actuales = cargar_raices()
    if any(os.path.normcase(r) == os.path.normcase(real) for r in actuales):
        logger.info(f"La carpeta ya estaba habilitada, no se duplica: {real}")
        return real

    guardar_raices(actuales + [real])
    logger.warning(f"Carpeta habilitada para las herramientas de repositorio: {real}")
    return real


def quitar_raiz(carpeta: str) -> str:
    """Deshabilita `carpeta`. Return la ruta real quitada.

    Levanta `RaizRechazada` si no estaba habilitada — decirle "listo" a alguien que se
    equivocó de carpeta le haría creer que cerró un acceso que sigue abierto.
    """
    texto = str(carpeta or "").strip()
    if not texto:
        raise RaizRechazada("No me dijiste qué carpeta quitar.")

    objetivo = _normalizada(texto)
    actuales = cargar_raices()
    coincidencias = [r for r in actuales if os.path.normcase(r) == objetivo]
    quedan = [r for r in actuales if os.path.normcase(r) != objetivo]
    if not coincidencias:
        raise RaizRechazada(f"«{carpeta}» no estaba habilitada, así que no hay nada que quitar.")

    guardar_raices(quedan)
    # Se devuelve la ruta TAL COMO estaba guardada, no la normalizada: `normcase()` la pasa a
    # minúsculas en Windows, y esta ruta termina en la frase que lee el usuario.
    real = coincidencias[0]
    logger.warning(f"Carpeta deshabilitada para las herramientas de repositorio: {real}")
    return real
