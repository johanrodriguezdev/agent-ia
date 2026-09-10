"""
core/workspace_files.py
REQ-029 — El confinamiento de rutas y las operaciones de archivo del agente.

Todo el REQ se juega en una sola función: `resolver()`. Convierte una ruta pedida por el
modelo en una ruta REAL dentro de una raíz habilitada, o falla. Si es correcta, las 5
herramientas de archivo son envoltorios finos; si tiene un agujero, el resto no importa.
Por eso vive sola, es pura (recibe las raíces, no las busca), y se testea aparte.

Tres invariantes, y ninguno es opcional:

1. **`realpath` ANTES de comparar** (CA-01, CA-04). `..` y symlinks se resuelven primero:
   un enlace dentro de la raíz que apunte a `C:\\Windows` se compara ya resuelto y cae
   afuera. Comparar antes de resolver sería comparar el disfraz, no la ruta.
2. **Comparación por SEGMENTOS, nunca por prefijo de string** (CA-04). Con `startswith`,
   `/home/proyecto-malo` "está dentro" de `/home/proyecto`; con `os.path.commonpath` no.
   En Windows además se normaliza con `os.path.normcase` en los DOS lados, porque el
   sistema de archivos es case-insensitive y `commonpath` no lo es por su cuenta.
3. **El directorio de instalación de O.R.I.O.N. está excluido en CÓDIGO** (CA-03), aunque
   alguien lo agregue como raíz en `code_workspaces.json`. `modify_source_code` es 🔴 RED
   en `core/security_manager.py` y lo sigue siendo; esto es esa clasificación aplicada
   donde se puede aplicar. Mismo criterio con que `_merge_with_override()` (REQ-019)
   bloquea bajar un RED aunque se edite el JSON a mano: la configuración no puede
   habilitar lo que el código prohíbe.

Límite conocido y aceptado en v1 (documentado en `desarrollo-log-029.md`): entre el
`realpath` y el `open()` hay una ventana TOCTOU teórica —alguien con acceso al disco podría
cambiar un symlink en el medio—. Quien pueda hacer eso ya tiene acceso de escritura a la
máquina, así que no es el vector que este REQ existe para cerrar.
"""

import fnmatch
import logging
import os
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class RutaFueraDeRaiz(Exception):
    """La ruta pedida no cae dentro de ninguna carpeta habilitada.

    Es una denegación de confinamiento, no un error de I/O: se levanta ANTES de tocar el
    disco. Las herramientas la traducen a texto para el modelo; los tests la esperan como
    excepción para que un escape no pueda confundirse con "el archivo no existía".
    """


#: Directorio de instalación de O.R.I.O.N. (`agente_ia/`, el padre de `core/`). Se lee
#: como atributo de módulo en cada llamada —no se congela en una constante normalizada—
#: para que los tests puedan sustituirlo por una carpeta de `tmp_path` sin tocar el real.
_INSTALACION = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

#: Un archivo más grande que esto ni se abre: se explica y se sugiere `file_search`.
_MAX_BYTES_ARCHIVO = 20 * 1024 * 1024
#: Topes de lo que vuelve al modelo en una lectura. Se trunca AVISANDO y diciendo en qué
#: línea se cortó (CA-10), nunca en silencio.
_MAX_CARACTERES = 40_000
_MAX_LINEAS = 2_000
#: Tope de entradas de un listado y de resultados de una búsqueda.
_MAX_ENTRADAS = 300
_MAX_RESULTADOS = 100
#: En una búsqueda, un archivo más grande que esto se saltea (suele ser un binario o un
#: volcado, no código), y se deja de recorrer después de este número de archivos.
_MAX_BYTES_ESCANEO = 2 * 1024 * 1024
_MAX_ARCHIVOS_ESCANEADOS = 20_000

#: Carpetas que no se recorren en `buscar()`. No es seguridad —lo que está dentro sigue
#: siendo legible con `file_read`—, es que llenar la respuesta con `node_modules` o con los
#: objetos de `.git` desperdicia el turno del modelo.
_DIRS_IGNORADOS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".idea", ".vscode",
    "dist", "build", "site-packages", ".next", ".gradle", "target",
})


# ─────────────────────────────────────────────
#  El corazón: confinamiento
# ─────────────────────────────────────────────

def _dentro_de(candidata_norm: str, contenedor: str) -> bool:
    """Return True si `candidata_norm` es el contenedor o cae dentro de él, por SEGMENTOS.

    Nunca `startswith`: `/home/proyecto-malo` no puede pasar por estar dentro de
    `/home/proyecto`. `commonpath` compara componente a componente, que es justamente la
    diferencia. Los dos lados llegan ya pasados por `normcase` porque en Windows el
    sistema de archivos es case-insensitive y `commonpath` no lo es.
    """
    contenedor_norm = os.path.normcase(contenedor)
    if candidata_norm == contenedor_norm:
        return True
    try:
        return os.path.commonpath([candidata_norm, contenedor_norm]) == contenedor_norm
    except ValueError:
        # Unidades distintas en Windows (C: vs D:), o rutas no comparables. No están
        # dentro: cualquier duda se resuelve del lado restrictivo.
        return False


def _es_instalacion(candidata_norm: str) -> bool:
    """Return True si la ruta cae dentro del directorio de instalación de O.R.I.O.N."""
    return _dentro_de(candidata_norm, os.path.realpath(_INSTALACION))


def es_codigo_de_orion(ruta: str) -> bool:
    """Return True si `ruta` cae dentro del directorio de instalación de O.R.I.O.N.

    Pública para que `workspace_config.agregar_raiz()` pueda rechazar la carpeta del propio
    agente ANTES de escribirla en la configuración, en vez de habilitarla y que después
    cada operación falle una por una.
    """
    try:
        return _es_instalacion(os.path.normcase(os.path.realpath(ruta)))
    except (OSError, ValueError) as e:
        logger.warning(f"no se pudo resolver {ruta!r} para compararla con la instalación: {e}")
        return True  # ante la duda, se trata como código propio: es el lado restrictivo


#: Nombres que no se abren durante una búsqueda amplia (REQ-030, hallazgo C de
#: `security-audit-029.md`). Leer un archivo significa mandarlo al proveedor del modelo, y
#: que una clave privada aparezca sola porque alguien buscó una palabra que estaba adentro
#: no es una decisión de nadie. `file_read` los sigue leyendo si se los pide por su nombre:
#: eso sí es una decisión.
_ARCHIVOS_DE_SECRETOS = (
    ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12", "*.ppk", "*.jks",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", "credentials.json",
    "service-account*.json", "*.keystore",
)


def _es_archivo_de_secretos(nombre: str) -> bool:
    minuscula = nombre.lower()
    return any(fnmatch.fnmatch(minuscula, patron) for patron in _ARCHIVOS_DE_SECRETOS)


def _autonomia_total() -> bool:
    """Return True si el humano encendió el nivel total del modo autonomía (REQ-033).

    Es lo único que abre la carpeta de O.R.I.O.N., que en cualquier otro caso se rechaza en
    código. Se consulta acá y no se cachea: apagar el modo tiene que tener efecto en la
    siguiente operación, no en el siguiente arranque.
    """
    try:
        from core.autonomy import puede_tocar_su_propio_codigo

        return puede_tocar_su_propio_codigo()
    except Exception as e:  # ante cualquier duda, el lado restrictivo
        logger.warning(f"no se pudo leer el modo autonomía, se asume apagado: {e}")
        return False


def _confinado(ruta: str, raices: List[str]) -> bool:
    """Return True si `ruta` sigue cayendo dentro de alguna raíz, resolviéndola antes.

    `resolver()` protege la ruta que PIDE el modelo. Esto protege las que aparecen solas
    durante un recorrido de directorios, que nadie pidió y por eso nunca pasaron por
    `resolver()`.

    Hace falta por Windows: `os.walk()` no desciende por symlinks, pero **una junction no
    es un symlink para Python** (`os.path.islink()` devuelve False), así que el recorrido
    entraba igual y `buscar()` devolvía el contenido de archivos de afuera de la raíz.
    Encontrado auditando REQ-029 con una junction real, no en teoría: `resolver()` y
    `listar()` bloqueaban ese mismo enlace y `buscar()` lo atravesaba.
    """
    try:
        real_norm = os.path.normcase(os.path.realpath(ruta))
    except (OSError, ValueError) as e:
        logger.debug(f"no se pudo resolver {ruta!r} durante el recorrido: {e}")
        return False
    if _es_instalacion(real_norm) and not _autonomia_total():
        return False
    return any(_dentro_de(real_norm, os.path.realpath(raiz)) for raiz in raices)


def _candidatas(ruta: str, raices: List[str]) -> List[str]:
    """Return las rutas a probar para `ruta`, sin resolver todavía.

    Una ruta absoluta se prueba tal cual. Una relativa se interpreta contra cada raíz —
    nunca contra el directorio de trabajo del proceso, que es el de O.R.I.O.N. y no tiene
    nada que ver con el repo del usuario. Con varias raíces gana la primera donde la ruta
    ya existe; si no existe en ninguna (caso de `file_write` creando un archivo nuevo), se
    usa la primera raíz. En todos los casos el resultado pasa igual por el chequeo de
    confinamiento: esta función elige candidata, no otorga permiso.
    """
    if os.path.isabs(ruta):
        return [ruta]
    unidas = [os.path.join(raiz, ruta) for raiz in raices]
    existentes = [c for c in unidas if os.path.exists(c)]
    return existentes + [c for c in unidas if c not in existentes]


def resolver(ruta: str, raices: List[str]) -> str:
    """Return la ruta REAL de `ruta` si cae dentro de alguna raíz habilitada.

    Levanta `RutaFueraDeRaiz` en todos los demás casos, SIN tocar el disco: ruta vacía,
    ninguna raíz configurada, ruta absoluta fuera de toda raíz, `..` que se escapa,
    symlink cuyo destino real cae afuera, y el directorio de instalación de O.R.I.O.N.
    aunque esté habilitado como raíz.
    """
    texto = str(ruta or "").strip()
    if not texto:
        raise RutaFueraDeRaiz(
            "No me dijiste qué ruta. Necesito una ruta dentro de una de las carpetas "
            "habilitadas."
        )
    if not raices:
        raise RutaFueraDeRaiz(
            "No hay ninguna carpeta habilitada para trabajar con archivos, así que no "
            "puedo leer ni escribir nada. El usuario tiene que habilitar una carpeta en "
            "code_workspaces.json antes de que yo pueda tocar un repositorio."
        )

    texto = os.path.expanduser(texto)
    # Las raíces también se pasan por `realpath` acá, no solo al cargarlas de la
    # configuración: así el confinamiento no depende de que el CALLER haya normalizado
    # bien. Un llamador futuro que pase una raíz cruda —con un symlink en el medio, o con
    # un `..`— no puede abrir un agujero por descuido.
    raices = [os.path.realpath(r) for r in raices]
    ultima_real: Optional[str] = None
    for candidata in _candidatas(texto, raices):
        try:
            real = os.path.realpath(candidata)
        except (OSError, ValueError) as e:
            logger.warning(f"No se pudo resolver la ruta pedida ({type(e).__name__}): {e}")
            continue
        real_norm = os.path.normcase(real)
        ultima_real = real

        # Primero la instalación: un intento de tocar el código de O.R.I.O.N. se registra
        # SIEMPRE, esté o no dentro de una raíz habilitada.
        if _es_instalacion(real_norm) and _autonomia_total():
            # REQ-033 — el humano encendió el nivel total con el PIN maestro y hay rama de
            # git. Se registra SIEMPRE con `critical`: que el agente toque su propio código
            # tiene que quedar en el log aunque esté autorizado.
            logger.critical(
                f"Acceso al código de O.R.I.O.N. PERMITIDO por el modo autonomía total: {ruta!r}"
            )
            return real
        if _es_instalacion(real_norm):
            logger.critical(
                f"Intento de acceso al código de O.R.I.O.N. bloqueado: {ruta!r}. "
                f"El directorio de instalación está excluido en código (REQ-029/CA-03) "
                f"aunque se agregue como carpeta habilitada; modify_source_code es 🔴 RED."
            )
            raise RutaFueraDeRaiz(
                "Esa ruta está dentro de mi propio código, y no puedo tocarlo: "
                "modificarlo es una acción de riesgo alto que no se autoriza por esta vía."
            )

        for raiz in raices:
            if _dentro_de(real_norm, raiz):
                return real

    logger.warning(
        f"Ruta fuera de las carpetas habilitadas, rechazada sin tocar el disco: {ruta!r}"
        + (f" (real: {ultima_real!r})" if ultima_real else "")
    )
    raise RutaFueraDeRaiz(
        f"«{ruta}» queda fuera de las carpetas habilitadas y no puedo tocarla. "
        f"Puedo trabajar dentro de: {_nombres_de_raices(raices)}."
    )


def _nombres_de_raices(raices: List[str]) -> str:
    return ", ".join(raices) if raices else "(ninguna)"


def raices_efectivas(raices: Optional[List[str]]) -> List[str]:
    """Return las raíces recibidas, o las del archivo de configuración si no se pasaron.

    Pública porque `core/workspace_git.py` resuelve las mismas raíces que las operaciones
    de archivo: una sola fuente para "sobre qué carpetas puede trabajar el agente".
    """
    if raices is not None:
        return raices
    from core.workspace_config import cargar_raices

    return cargar_raices()


def _relativa(real: str, raices: List[str]) -> str:
    """Return la ruta relativa a su raíz, para que la salida se lea como en un repo."""
    real_norm = os.path.normcase(real)
    for raiz in (os.path.realpath(r) for r in raices):
        if _dentro_de(real_norm, raiz):
            try:
                rel = os.path.relpath(real, raiz)
            except ValueError:
                return real
            return real if rel == "." else rel
    return real


# ─────────────────────────────────────────────
#  Operaciones
# ─────────────────────────────────────────────

def listar(ruta: str = "", raices: Optional[List[str]] = None) -> str:
    """Lista un directorio de una raíz habilitada. Sin ruta, lista las raíces mismas."""
    activas = raices_efectivas(raices)
    if not activas:
        return (
            "No hay ninguna carpeta habilitada para trabajar con archivos. El usuario "
            "tiene que habilitar una en code_workspaces.json antes de que yo pueda mirar "
            "un repositorio."
        )
    if not str(ruta or "").strip():
        lineas = [f"  {raiz}" for raiz in activas]
        return "Carpetas habilitadas para trabajar:\n" + "\n".join(lineas)

    real = resolver(ruta, activas)
    if not os.path.isdir(real):
        if os.path.isfile(real):
            return f"«{ruta}» es un archivo, no una carpeta. Para verlo, usá file_read."
        return f"No existe la carpeta «{ruta}»."

    try:
        entradas = sorted(os.listdir(real), key=str.lower)
    except OSError as e:
        logger.error(f"No se pudo listar {real!r}: {e}")
        return f"No pude listar «{ruta}»: {e.strerror or 'error del sistema de archivos'}."

    if not entradas:
        return f"La carpeta «{_relativa(real, activas)}» está vacía."

    lineas: List[str] = []
    for nombre in entradas[:_MAX_ENTRADAS]:
        completo = os.path.join(real, nombre)
        if os.path.isdir(completo):
            lineas.append(f"  {nombre}/")
            continue
        try:
            tamano = os.path.getsize(completo)
            lineas.append(f"  {nombre} ({tamano} bytes)")
        except OSError as e:
            logger.debug(f"no se pudo medir {completo!r}: {e}")
            lineas.append(f"  {nombre}")

    cabecera = f"Contenido de «{_relativa(real, activas)}» ({len(entradas)} entradas):"
    if len(entradas) > _MAX_ENTRADAS:
        lineas.append(
            f"  ... y {len(entradas) - _MAX_ENTRADAS} entradas más (listado recortado en "
            f"{_MAX_ENTRADAS})."
        )
    return cabecera + "\n" + "\n".join(lineas)


def leer(ruta: str, desde: Optional[int] = None, hasta: Optional[int] = None,
         raices: Optional[List[str]] = None) -> str:
    """Lee un archivo con numeración de líneas, tope de tamaño y truncado explícito.

    `desde`/`hasta` son números de línea 1-based e inclusivos, para poder leer un archivo
    grande de a pedazos en vez de gastar el turno entero en una lectura (CA-10).
    """
    activas = raices_efectivas(raices)
    real = resolver(ruta, activas)

    if os.path.isdir(real):
        return f"«{ruta}» es una carpeta, no un archivo. Para ver qué tiene, usá file_list."
    if not os.path.isfile(real):
        return f"No existe el archivo «{ruta}»."

    try:
        tamano = os.path.getsize(real)
    except OSError as e:
        logger.error(f"No se pudo medir {real!r}: {e}")
        return f"No pude abrir «{ruta}»: {e.strerror or 'error del sistema de archivos'}."
    if tamano > _MAX_BYTES_ARCHIVO:
        return (
            f"«{ruta}» pesa {tamano} bytes y es demasiado grande para leerlo entero "
            f"(el tope son {_MAX_BYTES_ARCHIVO} bytes). Buscá dentro con file_search y "
            f"después leé el rango de líneas que te interese."
        )
    if _parece_binario(real):
        return f"«{ruta}» parece un archivo binario, no texto. No tiene sentido leerlo."

    try:
        with open(real, "r", encoding="utf-8", errors="replace") as f:
            lineas = f.read().splitlines()
    except OSError as e:
        logger.error(f"No se pudo leer {real!r}: {e}")
        return f"No pude leer «{ruta}»: {e.strerror or 'error del sistema de archivos'}."

    total = len(lineas)
    inicio, fin, error_rango = _rango(desde, hasta, total)
    if error_rango:
        return error_rango

    seleccion = lineas[inicio - 1:fin]
    cuerpo, ultima, truncado = _formatear_lineas(seleccion, inicio)

    cabecera = f"{_relativa(real, activas)} ({total} líneas"
    cabecera += ")" if (inicio == 1 and fin == total) else f", mostrando {inicio}-{fin})"
    if truncado:
        cabecera += (
            f"\n[TRUNCADO: la salida se cortó en la línea {ultima} de {total}. "
            f"Pedí el rango siguiente con desde={ultima + 1} para seguir leyendo.]"
        )
    return cabecera + "\n" + cuerpo


def _rango(desde: Optional[int], hasta: Optional[int], total: int) -> Tuple[int, int, str]:
    """Return `(inicio, fin, error)` 1-based inclusivo, validado contra `total` líneas."""
    try:
        inicio = 1 if desde is None else int(desde)
        fin = total if hasta is None else int(hasta)
    except (TypeError, ValueError):
        return 1, total, "El rango de líneas tiene que ser numérico (desde/hasta)."
    if total == 0:
        return 1, 0, ""
    inicio = max(1, inicio)
    fin = min(total, fin)
    if inicio > total:
        return 1, total, f"El archivo tiene {total} líneas y pediste desde la {inicio}."
    if fin < inicio:
        return 1, total, f"El rango pedido está al revés: desde={inicio}, hasta={fin}."
    return inicio, fin, ""


def _formatear_lineas(seleccion: List[str], inicio: int) -> Tuple[str, int, bool]:
    """Return `(texto_numerado, ultima_linea_incluida, se_truncó)` respetando los topes."""
    partes: List[str] = []
    caracteres = 0
    ultima = inicio - 1
    truncado = False
    for offset, linea in enumerate(seleccion):
        numero = inicio + offset
        if offset >= _MAX_LINEAS or caracteres >= _MAX_CARACTERES:
            truncado = True
            break
        texto = f"{numero:>6}\t{linea}"
        partes.append(texto)
        caracteres += len(texto) + 1
        ultima = numero
    return "\n".join(partes), max(ultima, inicio - 1), truncado


def _parece_binario(real: str) -> bool:
    """Return True si el archivo tiene un byte nulo en su primer bloque."""
    try:
        with open(real, "rb") as f:
            return b"\x00" in f.read(4096)
    except OSError as e:
        logger.debug(f"no se pudo inspeccionar {real!r}: {e}")
        return False


def buscar(patron: str, ruta: str = "", raices: Optional[List[str]] = None,
           max_resultados: int = _MAX_RESULTADOS) -> str:
    """Busca un texto literal dentro de las carpetas habilitadas.

    El patrón se busca como TEXTO LITERAL, no como expresión regular, y es deliberado: una
    expresión que llega del modelo puede colgar el proceso con backtracking exponencial
    (ReDoS), y para encontrar un nombre de función o una constante en un repo la búsqueda
    literal alcanza.
    """
    activas = raices_efectivas(raices)
    aguja = str(patron or "")
    if not aguja.strip():
        return "Necesito el texto a buscar."
    if not activas:
        return (
            "No hay ninguna carpeta habilitada para buscar. El usuario tiene que habilitar "
            "una en code_workspaces.json."
        )

    if str(ruta or "").strip():
        base = resolver(ruta, activas)
        if not os.path.isdir(base):
            base = os.path.dirname(base)
        bases = [base]
    else:
        bases = list(activas)

    try:
        tope = max(1, min(int(max_resultados), _MAX_RESULTADOS))
    except (TypeError, ValueError):
        tope = _MAX_RESULTADOS

    resultados: List[str] = []
    archivos_vistos = 0
    secretos_salteados = 0
    corte = False
    for base in bases:
        for carpeta, subdirs, archivos in os.walk(base):
            subdirs[:] = [
                d for d in subdirs
                if d not in _DIRS_IGNORADOS
                and _confinado(os.path.join(carpeta, d), activas)
            ]
            for nombre in sorted(archivos):
                if archivos_vistos >= _MAX_ARCHIVOS_ESCANEADOS or len(resultados) >= tope:
                    corte = True
                    break
                if _es_archivo_de_secretos(nombre):
                    secretos_salteados += 1
                    logger.debug(f"búsqueda: salteado por ser archivo de credenciales: {nombre}")
                    continue
                completo = os.path.join(carpeta, nombre)
                archivos_vistos += 1
                resultados.extend(
                    _coincidencias(completo, aguja, activas, tope - len(resultados))
                )
            if corte:
                break
        if corte:
            break

    aviso_secretos = ""
    if secretos_salteados:
        aviso_secretos = (
            f"\n[{secretos_salteados} archivo(s) de credenciales no se leyeron: .env, claves "
            f"privadas y similares. Si de verdad necesitás uno, pedilo por su nombre.]"
        )
    if not resultados:
        return (
            f"No encontré «{aguja}» en ninguna de las carpetas habilitadas." + aviso_secretos
        )
    salida = f"Coincidencias de «{aguja}» ({len(resultados)}):\n" + "\n".join(resultados)
    salida += aviso_secretos
    if corte:
        salida += f"\n[Búsqueda recortada en {tope} resultados. Acotá el texto o la ruta.]"
    return salida


def _coincidencias(completo: str, aguja: str, raices: List[str], restantes: int) -> List[str]:
    """Return las líneas de un archivo que contienen `aguja`, como `ruta:línea: texto`."""
    if restantes <= 0:
        return []
    # Segunda barrera, a nivel de archivo: la poda de `buscar()` corta las CARPETAS que se
    # escapan, y esto corta un archivo suelto que sea un enlace a algo de afuera. Las dos
    # hacen falta — la primera evita recorrer de más, esta evita leer de más.
    if not _confinado(completo, raices):
        logger.warning(
            f"Archivo fuera de las carpetas habilitadas, salteado durante la búsqueda: "
            f"{completo!r}"
        )
        return []
    try:
        if os.path.getsize(completo) > _MAX_BYTES_ESCANEO:
            return []
    except OSError as e:
        logger.debug(f"no se pudo medir {completo!r}: {e}")
        return []
    if _parece_binario(completo):
        return []

    encontrados: List[str] = []
    try:
        with open(completo, "r", encoding="utf-8", errors="replace") as f:
            for numero, linea in enumerate(f, start=1):
                if aguja in linea:
                    texto = linea.rstrip("\r\n")[:300]
                    encontrados.append(f"  {_relativa(completo, raices)}:{numero}: {texto}")
                    if len(encontrados) >= restantes:
                        break
    except OSError as e:
        logger.debug(f"no se pudo leer {completo!r} durante la búsqueda: {e}")
        return encontrados
    return encontrados


def escribir(ruta: str, contenido: str, raices: Optional[List[str]] = None) -> str:
    """Crea o reescribe un archivo, creando los directorios intermedios DENTRO de la raíz."""
    activas = raices_efectivas(raices)
    real = resolver(ruta, activas)

    if os.path.isdir(real):
        return f"«{ruta}» es una carpeta: no puedo reescribirla como si fuera un archivo."

    padre = os.path.dirname(real)
    if padre and not os.path.isdir(padre):
        # Segundo chequeo explícito (CA-12): el directorio que se va a crear vuelve a
        # pasar por `resolver()`. Por construcción ya está dentro —el hijo lo está—, y
        # justamente por eso el chequeo es barato y deja el invariante escrito en el
        # código, no solo en un comentario.
        resolver(padre, activas)
        try:
            os.makedirs(padre, exist_ok=True)
        except OSError as e:
            logger.error(f"No se pudieron crear los directorios de {real!r}: {e}")
            return f"No pude crear las carpetas para «{ruta}»: {e.strerror or 'error'}."

    texto = "" if contenido is None else str(contenido)
    existia = os.path.isfile(real)
    try:
        with open(real, "w", encoding="utf-8", newline="") as f:
            f.write(texto)
    except OSError as e:
        logger.error(f"No se pudo escribir {real!r}: {e}")
        return f"No pude escribir «{ruta}»: {e.strerror or 'error del sistema de archivos'}."

    verbo = "Reescribí" if existia else "Creé"
    logger.info(f"{verbo} {real!r} ({len(texto)} caracteres)")
    return (
        f"{verbo} {_relativa(real, activas)} ({len(texto)} caracteres, "
        f"{len(texto.splitlines())} líneas)."
    )


def editar(ruta: str, buscar_texto: str, reemplazar_texto: str,
           raices: Optional[List[str]] = None) -> str:
    """Reemplaza un fragmento exacto por otro. Exige que aparezca UNA sola vez (CA-11)."""
    activas = raices_efectivas(raices)
    real = resolver(ruta, activas)

    if not buscar_texto:
        return "Necesito el fragmento exacto que querés reemplazar."
    if os.path.isdir(real):
        return f"«{ruta}» es una carpeta, no un archivo."
    if not os.path.isfile(real):
        return f"No existe el archivo «{ruta}». Si querés crearlo, usá file_write."
    if _parece_binario(real):
        return f"«{ruta}» parece un archivo binario: no lo edito por texto."

    try:
        with open(real, "r", encoding="utf-8", errors="strict") as f:
            contenido = f.read()
    except (OSError, UnicodeDecodeError) as e:
        logger.error(f"No se pudo leer {real!r} para editarlo: {e}")
        return (
            f"No pude leer «{ruta}» para editarlo: no es texto UTF-8 válido o el sistema "
            f"de archivos devolvió un error."
        )

    apariciones = contenido.count(buscar_texto)
    if apariciones == 0:
        return (
            f"No encontré ese fragmento en «{ruta}», así que no toqué el archivo. "
            f"Leelo con file_read y copiá el texto exacto, con su indentación."
        )
    if apariciones > 1:
        return (
            f"Ese fragmento aparece {apariciones} veces en «{ruta}», así que no toqué el "
            f"archivo: no sé cuál de las {apariciones} querías. Agregá líneas de contexto "
            f"alrededor hasta que el fragmento sea único."
        )

    reemplazo = "" if reemplazar_texto is None else str(reemplazar_texto)
    nuevo = contenido.replace(buscar_texto, reemplazo, 1)
    try:
        with open(real, "w", encoding="utf-8", newline="") as f:
            f.write(nuevo)
    except OSError as e:
        logger.error(f"No se pudo escribir {real!r} tras editarlo: {e}")
        return f"No pude guardar «{ruta}»: {e.strerror or 'error del sistema de archivos'}."

    logger.info(f"Edité {real!r}: 1 reemplazo")
    return f"Edité {_relativa(real, activas)}: reemplacé la única coincidencia."


#: Profundidad por defecto del árbol. Tres niveles alcanzan para entender la forma de un
#: proyecto (raíz, paquetes, módulos) sin traerse el contenido entero.
_PROFUNDIDAD_ARBOL = 3
#: Tope de líneas del árbol. Un repo grande tiene decenas de miles de archivos y volcarlos
#: se come el turno del modelo sin decirle nada que no sepa.
_MAX_LINEAS_ARBOL = 400


def arbol(ruta: str = "", profundidad: int = _PROFUNDIDAD_ARBOL,
          raices: Optional[List[str]] = None) -> str:
    """Devuelve la estructura de una carpeta habilitada, con sangría, hasta `profundidad`.

    Sirve para orientarse en un repositorio ajeno sin gastar veinte llamadas listando
    carpeta por carpeta, que es lo que había que hacer antes con `listar()`. Se saltean las
    mismas carpetas de ruido que en `buscar()` (`node_modules`, `.git`, `__pycache__`...):
    no es seguridad, es no llenar la respuesta con dependencias de terceros.
    """
    activas = raices_efectivas(raices)
    if not activas:
        return (
            "No hay ninguna carpeta habilitada para trabajar con archivos. El usuario tiene "
            "que habilitar una antes de que yo pueda mirar un proyecto."
        )

    try:
        niveles = max(1, min(int(profundidad), 8))
    except (TypeError, ValueError):
        niveles = _PROFUNDIDAD_ARBOL

    base = resolver(ruta, activas) if str(ruta or "").strip() else activas[0]
    if not os.path.isdir(base):
        base = os.path.dirname(base)

    lineas: List[str] = [f"{base}"]
    recortado = _recorrer_arbol(base, "", niveles, lineas, activas)

    if recortado:
        lineas.append(f"  ... (árbol recortado en {_MAX_LINEAS_ARBOL} líneas; pedí una "
                      f"subcarpeta o menos profundidad)")
    return "\n".join(lineas)


def _recorrer_arbol(carpeta: str, sangria: str, niveles: int, lineas: List[str],
                    raices: List[str]) -> bool:
    """Llena `lineas` recursivamente. Return True si se llegó al tope."""
    if niveles <= 0:
        return False
    try:
        entradas = sorted(os.scandir(carpeta), key=lambda e: (not e.is_dir(), e.name.lower()))
    except OSError as e:
        logger.debug(f"no se pudo listar {carpeta!r} para el árbol: {e}")
        return False

    for entrada in entradas:
        if len(lineas) >= _MAX_LINEAS_ARBOL:
            return True
        if entrada.name in _DIRS_IGNORADOS or entrada.name.startswith("."):
            continue
        # Un enlace que sale de la raíz no se recorre, por lo mismo que en `buscar()`: el
        # árbol visita rutas que nadie pidió.
        if entrada.is_dir() and not _confinado(entrada.path, raices):
            continue
        if entrada.is_dir():
            lineas.append(f"{sangria}  {entrada.name}/")
            if _recorrer_arbol(entrada.path, sangria + "  ", niveles - 1, lineas, raices):
                return True
        else:
            lineas.append(f"{sangria}  {entrada.name}")
    return False


# ─────────────────────────────────────────────
#  REQ-035 — borrar y mover: la parte del refactor que faltaba
# ─────────────────────────────────────────────
#
#  Renombrar un módulo, partir un archivo en dos, sacar el que quedó sin uso: eso es
#  refactorizar, y sin estas dos el agente podía escribir código nuevo pero no reorganizar
#  el que ya estaba. Las dos son 🟡 y —a diferencia de escribir y editar— **quedan fuera de
#  la lista blanca del modo autonomía**: se pueden deshacer con git solo si el archivo
#  estaba versionado, y eso no lo sabe nadie a las 3 de la mañana.

def borrar(ruta: str, raices: Optional[List[str]] = None) -> str:
    """Borra un archivo de una carpeta habilitada. Return qué pasó, en una frase.

    Solo archivos: una carpeta entera es un riesgo de otra magnitud y no entra por acá.
    """
    activas = raices_efectivas(raices)
    real = resolver(ruta, activas)

    if os.path.isdir(real):
        return (f"«{ruta}» es una carpeta, y no borro carpetas enteras por esta vía: "
                f"pedímelo archivo por archivo si es lo que querés.")
    if not os.path.exists(real):
        return f"«{ruta}» no existe, así que no hay nada que borrar."

    try:
        os.remove(real)
    except OSError as e:
        logger.error(f"no se pudo borrar {real!r}: {e}")
        return f"No pude borrar «{ruta}»: {e.strerror or 'error del sistema de archivos'}."

    logger.warning(f"Archivo borrado por el agente: {real}")
    return f"Borré {_relativa(real, activas)}."


def mover(origen: str, destino: str, raices: Optional[List[str]] = None) -> str:
    """Mueve o renombra un archivo. Los DOS extremos tienen que estar habilitados.

    Validar solo el origen dejaría mover un archivo fuera de las carpetas permitidas, que es
    una forma elegante de sacar algo de donde estaba protegido.
    """
    activas = raices_efectivas(raices)
    real_origen = resolver(origen, activas)
    real_destino = resolver(destino, activas)

    if not os.path.exists(real_origen):
        return f"«{origen}» no existe."
    if os.path.isdir(real_origen):
        return f"«{origen}» es una carpeta, y por esta vía muevo archivos, no carpetas."
    if os.path.exists(real_destino):
        return (f"«{destino}» ya existe. Elegí otro nombre o borralo antes, para que no se "
                f"pierda algo sin querer.")

    padre = os.path.dirname(real_destino)
    if padre and not os.path.isdir(padre):
        resolver(padre, activas)   # el destino tiene que caer dentro igual que el origen
        try:
            os.makedirs(padre, exist_ok=True)
        except OSError as e:
            logger.error(f"no se pudo crear {padre!r}: {e}")
            return f"No pude crear la carpeta de destino: {e.strerror or 'error'}."

    try:
        os.replace(real_origen, real_destino)
    except OSError as e:
        logger.error(f"no se pudo mover {real_origen!r} a {real_destino!r}: {e}")
        return f"No pude mover «{origen}»: {e.strerror or 'error del sistema de archivos'}."

    logger.warning(f"Archivo movido por el agente: {real_origen} -> {real_destino}")
    return f"Moví {_relativa(real_origen, activas)} a {_relativa(real_destino, activas)}."
