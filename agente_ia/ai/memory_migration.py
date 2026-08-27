"""
ai/memory_migration.py
Consolida en `ai/unified_memory.db` las memorias que quedaron dispersas en bases anteriores.

Al unificar la identidad del dueño entre canales apareció el problema de fondo: había 220
registros repartidos en cinco bases, y la que el agente consulta hoy —la que se llama
*unified*— solo tenía 6. Las otras 214 estaban en sistemas que ningún camino de ejecución
abre ya:

- `ai/memory.db`                    — pares (user_input, jarvis_response), esquema antiguo
- `ai/semantic_memory.db`           — texto + embedding, esquema antiguo
- `users_data/<id>/memory.db`       — pares (user_input, response) del canal remoto
- `users_data/<id>/semantic_memory.db` — texto + embedding del canal remoto

Garantías de esta migración:

- **No borra nada.** Las bases de origen quedan intactas y sirven de respaldo natural.
- **Es idempotente.** Cada origen se marca en la columna `source`; si ya hay filas con esa
  marca, ese origen se salta. Ejecutarla dos veces no duplica.
- **Conserva los embeddings.** Los tres almacenes usan vectores de 384 dimensiones, así que
  las memorias semánticas siguen siendo buscables sin recalcular nada. Un vector con otra
  dimensión se copia como texto sin embedding en vez de corromper la búsqueda.
- **Solo migra lo del dueño.** Las carpetas de `users_data/` que no correspondan a una
  identidad autorizada se ignoran: son de terceros y no deben acabar en su memoria.
"""

import json
import logging
import os
import sqlite3
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UNIFIED_DB = os.path.join(_PROJECT_ROOT, "ai", "unified_memory.db")
USERS_DIR = os.path.join(_PROJECT_ROOT, "users_data")

#: Dimensión de los vectores del almacén actual. Un embedding de otro tamaño no se puede
#: comparar con los existentes y se descarta (la fila se migra igual, sin vector).
EMBEDDING_DIMS = 384

#: Prefijo de la marca de origen. Es lo que hace idempotente la migración.
SOURCE_PREFIX = "migracion:"


def _source_tag(nombre: str) -> str:
    return f"{SOURCE_PREFIX}{nombre}"


def _ya_migrado(conn: sqlite3.Connection, source: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE source = ?", (source,)
    ).fetchone()
    return bool(row and row[0])


def _embedding_valido(raw: Optional[str]) -> Optional[str]:
    """Return el embedding si es utilizable con el almacén actual, o `None`."""
    if not raw:
        return None
    try:
        vector = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMS:
        return None
    return raw


def _leer_pares(db_path: str, columna_respuesta: str) -> List[Tuple[str, str, str]]:
    """Return los pares (entrada, respuesta, timestamp) de una base de conversación."""
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        filas = conn.execute(
            f"SELECT user_input, {columna_respuesta}, timestamp FROM memories ORDER BY id"
        ).fetchall()
        conn.close()
        return [(a or "", b or "", c or "") for a, b, c in filas]
    except sqlite3.Error as e:
        logger.warning(f"No se pudo leer '{db_path}': {e}")
        return []


def _leer_semanticas(db_path: str) -> List[Tuple[str, str, str]]:
    """Return las tuplas (texto, embedding, timestamp) de una base semántica."""
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        filas = conn.execute(
            "SELECT text, embedding_json, timestamp FROM semantic_memories ORDER BY id"
        ).fetchall()
        conn.close()
        return [(a or "", b or "", c or "") for a, b, c in filas]
    except sqlite3.Error as e:
        logger.warning(f"No se pudo leer '{db_path}': {e}")
        return []


def _insertar(conn: sqlite3.Connection, filas: List[dict]) -> int:
    conn.executemany(
        """INSERT INTO memories
           (user_id, text, embedding_json, importance, category, timestamp,
            archived, source, conversation_id, role)
           VALUES (:user_id, :text, :embedding_json, :importance, :category, :timestamp,
                   0, :source, :conversation_id, :role)""",
        filas,
    )
    return len(filas)


def _preparar_pares(
    pares: List[Tuple[str, str, str]], owner: str, source: str, origen: str
) -> List[dict]:
    """Convierte pares de conversación en filas del almacén unificado.

    Cada par produce DOS filas —una por turno— que comparten `conversation_id`. Guardarlo
    como un único bloque "usuario: X / asistente: Y" haría que la búsqueda semántica
    devolviera siempre las dos mitades juntas aunque solo una fuera relevante.
    """
    filas: List[dict] = []
    for i, (entrada, respuesta, ts) in enumerate(pares):
        conversation_id = f"{origen}#{i + 1}"
        for role, texto in (("user", entrada), ("assistant", respuesta)):
            if not texto.strip():
                continue
            filas.append({
                "user_id": owner,
                "text": texto,
                "embedding_json": None,
                # Importancia baja: es historial en crudo, no un hecho destilado. Que no
                # desplace a las memorias que sí se guardaron a propósito.
                "importance": 0.3,
                "category": "interaction",
                "timestamp": ts,
                "source": source,
                "conversation_id": conversation_id,
                "role": role,
            })
    return filas


def _preparar_semanticas(
    semanticas: List[Tuple[str, str, str]], owner: str, source: str
) -> Tuple[List[dict], int]:
    """Return las filas listas y cuántos embeddings se descartaron por dimensión."""
    filas: List[dict] = []
    descartados = 0
    for texto, embedding, ts in semanticas:
        if not texto.strip():
            continue
        valido = _embedding_valido(embedding)
        if embedding and valido is None:
            descartados += 1
        filas.append({
            "user_id": owner,
            "text": texto,
            "embedding_json": valido,
            "importance": 0.5,
            "category": "general",
            "timestamp": ts,
            "source": source,
            "conversation_id": None,
            "role": None,
        })
    return filas, descartados


def _carpetas_del_dueno() -> List[str]:
    """Return las carpetas de `users_data/` que pertenecen a identidades autorizadas."""
    from core.authorized_users import REMOTE_CHANNELS, list_authorized
    from core.user_identity import owner_legacy_ids

    autorizadas = {c: list_authorized(c) for c in REMOTE_CHANNELS}
    legacy = owner_legacy_ids(autorizadas)

    if not os.path.isdir(USERS_DIR):
        return []

    carpetas = []
    for nombre in sorted(os.listdir(USERS_DIR)):
        ruta = os.path.join(USERS_DIR, nombre)
        if not os.path.isdir(ruta):
            continue
        if nombre not in legacy:
            logger.info(f"users_data/{nombre}: no es una identidad autorizada, se omite")
            continue
        carpetas.append(nombre)
    return carpetas


def migrate(dry_run: bool = False) -> Dict[str, object]:
    """Consolida las memorias dispersas en `unified_memory.db`.

    Con `dry_run=True` no escribe nada y devuelve el mismo informe, para poder revisar qué
    haría antes de dejarla actuar sobre datos reales.
    """
    from core.user_identity import LEGACY_DESKTOP_USER_ID, OWNER_USER_ID

    informe: Dict[str, object] = {
        "dry_run": dry_run, "origenes": {}, "total_insertado": 0,
        "embeddings_descartados": 0, "reasignadas_del_escritorio": 0, "omitidos": [],
    }

    if not os.path.exists(UNIFIED_DB):
        logger.error(f"No existe el almacén destino: {UNIFIED_DB}")
        informe["error"] = "destino_inexistente"
        return informe

    conn = sqlite3.connect(UNIFIED_DB)
    try:
        pendientes: List[Tuple[str, List[dict]]] = []

        # ── Bases antiguas de `ai/` ──────────────────────────────────
        for nombre, archivo, columna in (
            ("ai_memory", os.path.join(_PROJECT_ROOT, "ai", "memory.db"), "jarvis_response"),
        ):
            source = _source_tag(nombre)
            if _ya_migrado(conn, source):
                informe["omitidos"].append(nombre)
                continue
            filas = _preparar_pares(
                _leer_pares(archivo, columna), OWNER_USER_ID, source, nombre
            )
            pendientes.append((nombre, filas))

        source = _source_tag("ai_semantic")
        if _ya_migrado(conn, source):
            informe["omitidos"].append("ai_semantic")
        else:
            filas, descartados = _preparar_semanticas(
                _leer_semanticas(os.path.join(_PROJECT_ROOT, "ai", "semantic_memory.db")),
                OWNER_USER_ID, source,
            )
            informe["embeddings_descartados"] += descartados
            pendientes.append(("ai_semantic", filas))

        # ── Carpetas por usuario del dueño ───────────────────────────
        for carpeta in _carpetas_del_dueno():
            base = os.path.join(USERS_DIR, carpeta)

            nombre = f"users_{carpeta}_memory"
            source = _source_tag(nombre)
            if _ya_migrado(conn, source):
                informe["omitidos"].append(nombre)
            else:
                filas = _preparar_pares(
                    _leer_pares(os.path.join(base, "memory.db"), "response"),
                    OWNER_USER_ID, source, nombre,
                )
                pendientes.append((nombre, filas))

            nombre = f"users_{carpeta}_semantic"
            source = _source_tag(nombre)
            if _ya_migrado(conn, source):
                informe["omitidos"].append(nombre)
            else:
                filas, descartados = _preparar_semanticas(
                    _leer_semanticas(os.path.join(base, "semantic_memory.db")),
                    OWNER_USER_ID, source,
                )
                informe["embeddings_descartados"] += descartados
                pendientes.append((nombre, filas))

        # ── Escritura ────────────────────────────────────────────────
        for nombre, filas in pendientes:
            informe["origenes"][nombre] = len(filas)
            if filas and not dry_run:
                informe["total_insertado"] += _insertar(conn, filas)
            elif filas:
                informe["total_insertado"] += len(filas)

        # Las filas que el escritorio ya había guardado bajo el `user_id` antiguo pasan al
        # canónico: si no, quedarían huérfanas justo después de unificar la identidad.
        fila = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE user_id = ?", (LEGACY_DESKTOP_USER_ID,)
        ).fetchone()
        reasignables = fila[0] if fila else 0
        informe["reasignadas_del_escritorio"] = reasignables
        if reasignables and not dry_run:
            conn.execute(
                "UPDATE memories SET user_id = ? WHERE user_id = ?",
                (OWNER_USER_ID, LEGACY_DESKTOP_USER_ID),
            )

        if not dry_run:
            conn.commit()
    finally:
        conn.close()

    return informe
