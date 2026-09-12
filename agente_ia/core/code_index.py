"""
core/code_index.py
REQ-034 — Índice semántico de código: entender un repositorio grande sin leerlo entero.

`file_search` busca texto literal: sirve cuando sabés la palabra exacta. Esto es lo otro —
preguntar *"¿dónde está la lógica de facturación?"* en un repositorio de miles de archivos
donde nadie escribió nunca la palabra "facturación", porque el módulo se llama `billing`.

Cuatro decisiones que hacen la diferencia entre esto y un índice de juguete:

1. **Incremental de verdad.** Cada archivo guarda su `mtime`, su tamaño y el hash de su
   contenido. Reindexar un repositorio donde no cambió nada no calcula ni un embedding, y
   un archivo borrado desaparece del índice con sus fragmentos. Sin esto, "actualizar el
   índice" costaría lo mismo que crearlo y nadie lo haría nunca.
2. **El troceado respeta el código.** En Python se usa `ast` para cortar por función y por
   clase: un fragmento es una unidad que significa algo, no 40 líneas que empiezan a mitad
   de un `if`. Si el archivo no parsea —cosa que pasa, y justo cuando lo estás arreglando—
   cae a ventanas deslizantes con solape.
3. **Los fragmentos entran en el modelo.** `all-MiniLM` trunca a 256 word-pieces: un
   fragmento de 200 líneas se indexa por sus primeras 20 y el resto es invisible. Se corta
   a un tamaño que el modelo pueda ver entero.
4. **Se puede cortar y seguir.** Indexar un repositorio grande lleva minutos; hacerlo en una
   sola llamada bloquearía el turno. Cada llamada trabaja hasta un tope de tiempo y devuelve
   cuánto falta — el estado vive en SQLite, así que continuar es volver a llamar.

Los archivos de credenciales NO se indexan (misma lista que `workspace_files.buscar()`):
meter un `.env` en un índice semántico es dejar la clave a un `code_search` de distancia.
"""

import ast
import hashlib
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "code_index.db")

#: Cuántas líneas entran en un fragmento cuando hay que cortar a ciegas, y cuántas se
#: repiten entre uno y el siguiente. El solape existe para que una función que cae justo en
#: el borde no quede partida en dos mitades que no significan nada por separado.
_LINEAS_POR_FRAGMENTO = 30
_LINEAS_DE_SOLAPE = 8

#: Tope de caracteres por fragmento. `all-MiniLM` trunca a 256 word-pieces (~1000-1200
#: caracteres de código): pasarse no da error, da un embedding que ignora el final.
_MAX_CARACTERES_FRAGMENTO = 1200

#: Archivos que no se indexan por tamaño: un `.min.js` o un volcado no aportan nada y
#: llenan el índice.
_MAX_BYTES_ARCHIVO = 400_000

#: Extensiones que se indexan. Lista blanca a propósito: indexar binarios, imágenes o
#: `.lock` es gastar tiempo de CPU en ruido.
EXTENSIONES = frozenset({
    ".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".java", ".cs", ".go", ".rs", ".rb",
    ".php", ".c", ".h", ".cpp", ".hpp", ".css", ".scss", ".html", ".sql", ".sh", ".ps1",
    ".md", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
})

#: Segundos que puede durar una llamada a `indexar()` antes de devolver el control.
TOPE_SEGUNDOS_POR_LLAMADA = 60

#: Cuántos fragmentos se le pasan al modelo de una vez. Medido en este proyecto: embebiendo
#: archivo por archivo (lotes de ~15) el ritmo era de 8 fragmentos/s; juntando fragmentos de
#: varios archivos hasta llenar un lote grande, el modelo aprovecha la vectorización. Es la
#: diferencia entre indexar un repositorio de mil archivos en media hora o en minutos.
_FRAGMENTOS_POR_LOTE = 256

#: Cuántos fragmentos del MISMO archivo pueden aparecer en un resultado de búsqueda. Sin
#: este tope, un archivo con un docstring largo se lleva los ocho lugares y esconde a los
#: otros diez archivos que también tenían algo que decir. Medido: en las primeras pruebas,
#: tres de cada cuatro consultas devolvían el encabezado de módulo en los tres primeros
#: puestos.
_MAX_POR_ARCHIVO = 2


@dataclass
class Fragmento:
    """Un pedazo de código con significado propio y su lugar exacto en el archivo."""

    texto: str
    linea_inicio: int
    linea_fin: int
    simbolo: str = ""

    def para_embeber(self, ruta: str) -> str:
        """Return el texto con su ubicación adelante, que es lo que se embebe.

        El nombre del archivo y el del símbolo son parte de lo que alguien busca: quien
        pregunta "el confinamiento de rutas" tiene más chance de dar con
        `workspace_files.py :: resolver` si esas palabras están EN el texto embebido y no
        solo en la fila de la base.
        """
        cabecera = os.path.basename(ruta)
        if self.simbolo:
            cabecera = f"{cabecera} :: {self.simbolo}"
        return f"{cabecera}\n{self.texto}"


@dataclass
class Coincidencia:
    ruta: str
    linea_inicio: int
    linea_fin: int
    texto: str
    simbolo: str
    puntaje: float


@dataclass
class ResultadoIndexado:
    """Lo que devuelve una pasada de indexado."""

    archivos_nuevos: int = 0
    archivos_actualizados: int = 0
    archivos_borrados: int = 0
    archivos_sin_cambios: int = 0
    fragmentos: int = 0
    pendientes: int = 0
    segundos: float = 0.0

    @property
    def completo(self) -> bool:
        return self.pendientes == 0


# ─────────────────────────────────────────────
#  Base de datos
# ─────────────────────────────────────────────

def _conexion() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _crear_esquema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS archivos (
            id INTEGER PRIMARY KEY,
            raiz TEXT NOT NULL,
            ruta TEXT NOT NULL UNIQUE,
            mtime REAL NOT NULL,
            tamano INTEGER NOT NULL,
            hash TEXT NOT NULL,
            indexado_en TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fragmentos (
            id INTEGER PRIMARY KEY,
            archivo_id INTEGER NOT NULL REFERENCES archivos(id) ON DELETE CASCADE,
            linea_inicio INTEGER NOT NULL,
            linea_fin INTEGER NOT NULL,
            simbolo TEXT NOT NULL DEFAULT '',
            texto TEXT NOT NULL,
            embedding BLOB NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_archivos_raiz ON archivos(raiz)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fragmentos_archivo ON fragmentos(archivo_id)")
    conn.commit()


def _normalizar(ruta: str) -> str:
    return os.path.normcase(os.path.realpath(ruta))


# ─────────────────────────────────────────────
#  Troceado
# ─────────────────────────────────────────────

def _recortar(texto: str) -> str:
    return texto if len(texto) <= _MAX_CARACTERES_FRAGMENTO else texto[:_MAX_CARACTERES_FRAGMENTO]


def _fragmentos_por_ventana(lineas: Sequence[str], desde: int = 1) -> List[Fragmento]:
    """Corta a ciegas, con solape. El plan B cuando no se puede entender la estructura."""
    fragmentos: List[Fragmento] = []
    paso = max(1, _LINEAS_POR_FRAGMENTO - _LINEAS_DE_SOLAPE)
    for inicio in range(0, len(lineas), paso):
        trozo = lineas[inicio:inicio + _LINEAS_POR_FRAGMENTO]
        if not any(linea.strip() for linea in trozo):
            continue
        fragmentos.append(Fragmento(
            texto=_recortar("".join(trozo)),
            linea_inicio=desde + inicio,
            linea_fin=desde + inicio + len(trozo) - 1,
        ))
        if inicio + _LINEAS_POR_FRAGMENTO >= len(lineas):
            break
    return fragmentos


def _fragmentos_de_python(contenido: str) -> Optional[List[Fragmento]]:
    """Corta un archivo Python por funciones y clases. Return None si no parsea.

    Un fragmento que es una función entera se puede buscar por lo que HACE. Uno que empieza
    a mitad de un `for` y termina a mitad de un `try` no significa nada, y su embedding
    tampoco.
    """
    try:
        arbol = ast.parse(contenido)
    except (SyntaxError, ValueError) as e:
        logger.debug(f"no parsea como Python, se trocea por ventanas: {e}")
        return None

    lineas = contenido.splitlines(keepends=True)
    fragmentos: List[Fragmento] = []
    cubiertas: set = set()

    for nodo in ast.walk(arbol):
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        fin = getattr(nodo, "end_lineno", None) or nodo.lineno
        # Una clase larga se indexa entera Y por método: buscar "cómo se valida el token"
        # tiene que poder caer en el método, no solo en la clase de 300 líneas.
        texto = "".join(lineas[nodo.lineno - 1:fin])
        if not texto.strip():
            continue
        fragmentos.append(Fragmento(
            texto=_recortar(texto),
            linea_inicio=nodo.lineno,
            linea_fin=fin,
            simbolo=nodo.name,
        ))
        cubiertas.update(range(nodo.lineno, fin + 1))

    # Lo que quedó fuera de toda función o clase (imports, constantes, código a nivel de
    # módulo) también se indexa: ahí suele estar la configuración que alguien busca.
    sueltas = [i for i in range(1, len(lineas) + 1) if i not in cubiertas]
    if sueltas:
        bloque: List[int] = []
        for numero in sueltas + [None]:
            if bloque and (numero is None or numero != bloque[-1] + 1):
                trozo = lineas[bloque[0] - 1:bloque[-1]]
                if any(l.strip() for l in trozo):
                    fragmentos.extend(_fragmentos_por_ventana(trozo, desde=bloque[0]))
                bloque = []
            if numero is not None:
                bloque.append(numero)

    return fragmentos or None


def trocear(ruta: str, contenido: str) -> List[Fragmento]:
    """Return los fragmentos indexables de un archivo."""
    if ruta.lower().endswith(".py"):
        porPython = _fragmentos_de_python(contenido)
        if porPython:
            return porPython
    return _fragmentos_por_ventana(contenido.splitlines(keepends=True))


# ─────────────────────────────────────────────
#  Indexado
# ─────────────────────────────────────────────

def _debe_indexarse(nombre: str) -> bool:
    from core.workspace_files import _es_archivo_de_secretos

    if _es_archivo_de_secretos(nombre):
        return False
    return os.path.splitext(nombre)[1].lower() in EXTENSIONES


def _archivos_del_repo(raiz: str) -> List[str]:
    """Return los archivos indexables de `raiz`, salteando el ruido de dependencias."""
    from core.workspace_files import _DIRS_IGNORADOS, _confinado

    encontrados: List[str] = []
    for carpeta, subdirs, archivos in os.walk(raiz):
        subdirs[:] = [
            d for d in subdirs
            if d not in _DIRS_IGNORADOS
            and not d.startswith(".")
            and _confinado(os.path.join(carpeta, d), [raiz])
        ]
        for nombre in archivos:
            if not _debe_indexarse(nombre):
                continue
            completo = os.path.join(carpeta, nombre)
            try:
                if os.path.getsize(completo) > _MAX_BYTES_ARCHIVO:
                    continue
            except OSError:
                continue
            encontrados.append(completo)
    return encontrados


def _huella(ruta: str) -> Optional[Tuple[float, int, str]]:
    """Return `(mtime, tamaño, hash)` del archivo, o None si no se puede leer."""
    try:
        info = os.stat(ruta)
        with open(ruta, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
    except OSError as e:
        logger.debug(f"no se pudo leer {ruta!r} para indexar: {e}")
        return None
    return info.st_mtime, info.st_size, digest


def indexar(
    raiz: str,
    embebedor: Optional[Callable[[List[str]], List[List[float]]]] = None,
    tope_segundos: int = TOPE_SEGUNDOS_POR_LLAMADA,
) -> ResultadoIndexado:
    """Construye o actualiza el índice de `raiz`. Return qué hizo y cuánto falta.

    `embebedor` se puede inyectar para las pruebas: así los tests no cargan el modelo real
    ni dependen de que esté descargado.
    """
    if embebedor is None:
        from ai.embedding_engine import create_embeddings as embebedor  # noqa: N806

    raiz_real = _normalizar(raiz)
    comenzo = time.monotonic()
    resultado = ResultadoIndexado()

    conn = _conexion()
    try:
        _crear_esquema(conn)
        en_disco = {_normalizar(r): r for r in _archivos_del_repo(raiz_real)}

        indexados = {
            fila[0]: (fila[1], fila[2], fila[3], fila[4])
            for fila in conn.execute(
                "SELECT ruta, id, mtime, tamano, hash FROM archivos WHERE raiz = ?",
                (raiz_real,),
            )
        }

        # 1. Lo que ya no está en disco sale del índice, con sus fragmentos (ON DELETE CASCADE).
        for ruta in set(indexados) - set(en_disco):
            conn.execute("DELETE FROM archivos WHERE id = ?", (indexados[ruta][0],))
            resultado.archivos_borrados += 1
        if resultado.archivos_borrados:
            conn.commit()

        # 2. Lo que cambió (o es nuevo) se vuelve a trocear; lo demás no cuesta nada.
        pendientes: List[Tuple[str, str, Tuple[float, int, str]]] = []
        for clave, ruta in en_disco.items():
            huella = _huella(ruta)
            if huella is None:
                continue
            previo = indexados.get(clave)
            if previo and previo[1] == huella[0] and previo[2] == huella[1] and previo[3] == huella[2]:
                resultado.archivos_sin_cambios += 1
                continue
            pendientes.append((clave, ruta, huella))

        # Se acumulan fragmentos de VARIOS archivos hasta llenar un lote y recién ahí se
        # llama al modelo: es lo que separa 8 fragmentos/s de un ritmo usable.
        lote: List[Tuple[str, str, Tuple, List[Fragmento]]] = []
        fragmentos_en_lote = 0
        procesados = 0

        for indice, (clave, ruta, huella) in enumerate(pendientes):
            if time.monotonic() - comenzo > tope_segundos:
                resultado.pendientes = len(pendientes) - procesados
                break

            fragmentos = _leer_y_trocear(ruta)
            if fragmentos:
                lote.append((clave, ruta, huella, fragmentos))
                fragmentos_en_lote += len(fragmentos)
            procesados += 1

            ultimo = indice == len(pendientes) - 1
            if fragmentos_en_lote >= _FRAGMENTOS_POR_LOTE or (ultimo and lote):
                _guardar_lote(conn, raiz_real, lote, indexados, embebedor, resultado)
                conn.commit()
                lote, fragmentos_en_lote = [], 0

        if lote:
            _guardar_lote(conn, raiz_real, lote, indexados, embebedor, resultado)

        conn.commit()
    finally:
        conn.close()

    resultado.segundos = round(time.monotonic() - comenzo, 1)
    _invalidar_cache(raiz_real)
    logger.info(
        f"Índice de '{raiz_real}': {resultado.archivos_nuevos} nuevos, "
        f"{resultado.archivos_actualizados} actualizados, {resultado.archivos_borrados} borrados, "
        f"{resultado.archivos_sin_cambios} sin cambios, {resultado.fragmentos} fragmentos, "
        f"{resultado.pendientes} pendientes, {resultado.segundos}s"
    )
    return resultado


def _leer_y_trocear(ruta: str) -> List[Fragmento]:
    """Return los fragmentos de un archivo, o lista vacía si no se puede leer."""
    try:
        with open(ruta, "r", encoding="utf-8", errors="replace") as f:
            contenido = f.read()
    except OSError as e:
        logger.debug(f"no se pudo abrir {ruta!r}: {e}")
        return []
    return trocear(ruta, contenido)


def _guardar_lote(conn, raiz: str, lote, indexados, embebedor,
                  resultado: ResultadoIndexado) -> None:
    """Calcula los embeddings de todo el lote de una vez y escribe sus filas."""
    from datetime import datetime

    textos: List[str] = []
    for _clave, ruta, _huella, fragmentos in lote:
        textos.extend(f.para_embeber(ruta) for f in fragmentos)

    try:
        vectores = embebedor(textos)
    except Exception as e:
        logger.error(f"no se pudieron calcular los embeddings del lote: {e}")
        return
    if len(vectores) != len(textos):
        logger.error(f"el embebedor devolvió {len(vectores)} vectores para {len(textos)} textos")
        return

    ahora = datetime.now().isoformat(timespec="seconds")
    posicion = 0
    for clave, ruta, huella, fragmentos in lote:
        es_nuevo = clave not in indexados
        conn.execute("DELETE FROM archivos WHERE ruta = ?", (clave,))
        cursor = conn.execute(
            "INSERT INTO archivos (raiz, ruta, mtime, tamano, hash, indexado_en) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (raiz, clave, huella[0], huella[1], huella[2], ahora),
        )
        archivo_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO fragmentos (archivo_id, linea_inicio, linea_fin, simbolo, texto, "
            "embedding) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (archivo_id, f.linea_inicio, f.linea_fin, f.simbolo, f.texto,
                 np.asarray(vectores[posicion + i], dtype=np.float32).tobytes())
                for i, f in enumerate(fragmentos)
            ],
        )
        posicion += len(fragmentos)
        resultado.fragmentos += len(fragmentos)
        if es_nuevo:
            resultado.archivos_nuevos += 1
        else:
            resultado.archivos_actualizados += 1


# ─────────────────────────────────────────────
#  Búsqueda
# ─────────────────────────────────────────────

#: Matriz de embeddings por raíz, construida en la primera búsqueda. Se invalida cuando el
#: índice cambia: sin esto, cada búsqueda leería miles de BLOBs de SQLite y los convertiría
#: de nuevo, que es justo el trabajo que el índice existe para no repetir.
_CACHE: Dict[str, Tuple[np.ndarray, List[Tuple]]] = {}


def _invalidar_cache(raiz: str = "") -> None:
    if raiz:
        _CACHE.pop(raiz, None)
    else:
        _CACHE.clear()


def _matriz_de(raiz: str) -> Tuple[np.ndarray, List[Tuple]]:
    if raiz in _CACHE:
        return _CACHE[raiz]

    conn = _conexion()
    try:
        _crear_esquema(conn)
        filas = list(conn.execute(
            "SELECT a.ruta, f.linea_inicio, f.linea_fin, f.simbolo, f.texto, f.embedding "
            "FROM fragmentos f JOIN archivos a ON a.id = f.archivo_id WHERE a.raiz = ?",
            (raiz,),
        ))
    finally:
        conn.close()

    if not filas:
        vacio = (np.zeros((0, 1), dtype=np.float32), [])
        _CACHE[raiz] = vacio
        return vacio

    matriz = np.vstack([np.frombuffer(f[5], dtype=np.float32) for f in filas])
    datos = [(f[0], f[1], f[2], f[3], f[4]) for f in filas]
    _CACHE[raiz] = (matriz, datos)
    return _CACHE[raiz]


def buscar(
    consulta: str,
    raiz: str,
    top_k: int = 8,
    umbral: float = 0.15,
    embebedor: Optional[Callable[[List[str]], List[List[float]]]] = None,
) -> List[Coincidencia]:
    """Return los fragmentos más parecidos a `consulta`, ordenados por puntaje.

    El umbral es bajo a propósito: en código, la consulta y el fragmento están escritos en
    idiomas distintos —la pregunta en castellano, el código en inglés— así que los puntajes
    son más bajos que en texto y un umbral alto devolvería siempre vacío.
    """
    texto = str(consulta or "").strip()
    if not texto:
        return []
    if embebedor is None:
        from ai.embedding_engine import create_embeddings as embebedor  # noqa: N806

    matriz, datos = _matriz_de(_normalizar(raiz))
    if not datos:
        return []

    vector = np.asarray(embebedor([texto])[0], dtype=np.float32)
    normas = np.linalg.norm(matriz, axis=1) + 1e-10
    puntajes = (matriz @ vector) / (normas * (np.linalg.norm(vector) + 1e-10))

    coincidencias: List[Coincidencia] = []
    por_archivo: Dict[str, int] = {}
    for i in np.argsort(puntajes)[::-1]:
        puntaje = float(puntajes[i])
        if puntaje < umbral:
            break
        ruta_i = datos[i][0]
        # Un archivo con un encabezado largo se llevaba los ocho lugares y escondía a los
        # otros diez que también tenían algo que decir.
        if por_archivo.get(ruta_i, 0) >= _MAX_POR_ARCHIVO:
            continue
        por_archivo[ruta_i] = por_archivo.get(ruta_i, 0) + 1
        coincidencias.append(Coincidencia(
            ruta=ruta_i, linea_inicio=datos[i][1], linea_fin=datos[i][2],
            simbolo=datos[i][3], texto=datos[i][4], puntaje=puntaje,
        ))
        if len(coincidencias) >= max(1, top_k):
            break
    return coincidencias


def estado(raiz: str) -> Dict[str, int]:
    """Return cuántos archivos y fragmentos tiene indexados esa carpeta."""
    raiz_real = _normalizar(raiz)
    conn = _conexion()
    try:
        _crear_esquema(conn)
        archivos = conn.execute(
            "SELECT COUNT(*) FROM archivos WHERE raiz = ?", (raiz_real,)
        ).fetchone()[0]
        fragmentos = conn.execute(
            "SELECT COUNT(*) FROM fragmentos f JOIN archivos a ON a.id = f.archivo_id "
            "WHERE a.raiz = ?", (raiz_real,)
        ).fetchone()[0]
    finally:
        conn.close()
    return {"archivos": archivos, "fragmentos": fragmentos}
