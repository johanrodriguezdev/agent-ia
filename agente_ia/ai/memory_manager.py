import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.dirname(__file__))
DB_PATH = os.path.join(DB_DIR, "unified_memory.db")

# Columnas leidas por todas las queries que materializan un `MemoryItem`. Se enumeran
# explicitamente (nunca `SELECT *`) para que agregar columnas al esquema no rompa el
# desempaquetado posicional de las filas.
_MEMORY_COLUMNS = (
    "id, user_id, text, importance, category, timestamp, archived, source, "
    "conversation_id, role"
)


@dataclass
class MemoryItem:
    id: int = 0
    user_id: str = "default"
    text: str = ""
    embedding: Optional[list] = None
    importance: float = 0.5
    category: str = "general"
    timestamp: str = ""
    archived: bool = False
    source: str = "conversation"
    # REQ-013: agrupacion conversacional. `None` en toda fila anterior al REQ y en las
    # que escribe `main.py` (canal CLI/voz) - ver arquitectura-013.md 3.2/3.4.
    conversation_id: Optional[str] = None
    role: Optional[str] = None


@dataclass
class ConversationSummary:
    """Fila del listado de conversaciones del sidebar (REQ-013/CA-10)."""

    conversation_id: str
    title: str
    last_activity: str
    turn_count: int


def _row_to_item(row) -> MemoryItem:
    """Materializa una fila de `_MEMORY_COLUMNS` como `MemoryItem`."""
    return MemoryItem(
        id=row[0], user_id=row[1], text=row[2], importance=row[3], category=row[4],
        timestamp=row[5], archived=bool(row[6]), source=row[7],
        conversation_id=row[8], role=row[9],
    )

class UnifiedMemory:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._embeddings: List[np.ndarray] = []
        self._embedding_ids: List[int] = []
        self._embedding_user_ids: List[str] = []
        # REQ-013: las tres listas de arriba se mutan desde varios hilos (main.py, bots y
        # ahora `store_turn()` via `run_async`). Lock DEDICADO: no se reutiliza `_lock`,
        # que es el del singleton (`__new__`).
        self._emb_lock = threading.Lock()
        self._init_db()
        self._load_embeddings()
        self._start_consolidation_thread()

    def _init_db(self):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        text TEXT NOT NULL,
                        embedding_json TEXT,
                        importance REAL DEFAULT 0.5,
                        category TEXT DEFAULT 'general',
                        timestamp TEXT NOT NULL,
                        archived INTEGER DEFAULT 0,
                        source TEXT DEFAULT 'conversation'
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_memories_user
                    ON memories(user_id, archived)
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS summaries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        summary_text TEXT NOT NULL,
                        summary_type TEXT DEFAULT 'partial',
                        msg_count INTEGER DEFAULT 0,
                        timestamp TEXT NOT NULL
                    )
                """)
                self._migrate_schema(conn)
            logger.info(f"Base de datos unificada inicializada: {DB_PATH}")
        except Exception as e:
            logger.error(f"Error inicializando DB: {e}")

    def _migrate_schema(self, conn) -> None:
        """Migracion aditiva e idempotente del esquema de `memories` (REQ-013/CA-12).

        Agrega `conversation_id` y `role` solo si faltan (consultando
        `PRAGMA table_info`). `ADD COLUMN` sin `NOT NULL` ni `DEFAULT` es O(1) en SQLite:
        no reescribe la tabla, no hay `DROP`/`RENAME`/copia, y las filas anteriores al
        REQ quedan con ambas columnas en `NULL` - siguen intactas para `get_recent()`,
        `search_semantic()` y `consolidate()`, y son invisibles para las tres queries
        conversacionales (que filtran `conversation_id IS NOT NULL`).
        """
        try:
            existing = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
            for column in ("conversation_id", "role"):
                if column not in existing:
                    conn.execute(f"ALTER TABLE memories ADD COLUMN {column} TEXT")
                    logger.info(f"Esquema de memorias migrado: columna '{column}' agregada")
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_conversation
                ON memories(user_id, conversation_id, id)
            """)
        except Exception as e:
            logger.error(f"Error migrando esquema de memorias: {e}")

    def _load_embeddings(self):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    "SELECT id, user_id, embedding_json FROM memories WHERE archived=0 AND embedding_json IS NOT NULL"
                ).fetchall()
            # REQ-013: el reemplazo de las tres listas ocurre bajo `_emb_lock` para que un
            # `search_semantic()` concurrente nunca las vea a medio reconstruir.
            with self._emb_lock:
                self._embeddings.clear()
                self._embedding_ids.clear()
                self._embedding_user_ids.clear()
                for row_id, user_id, emb_json in rows:
                    if emb_json:
                        self._embeddings.append(np.array(json.loads(emb_json), dtype=np.float32))
                        self._embedding_ids.append(row_id)
                        self._embedding_user_ids.append(user_id)
                loaded = len(self._embeddings)
            logger.info(f"{loaded} embeddings cargados en RAM")
        except Exception as e:
            logger.warning(f"Error cargando embeddings: {e}")

    def _get_embedding(self, text: str) -> np.ndarray:
        try:
            from ai.embedding_engine import create_embedding
            return np.array(create_embedding(text), dtype=np.float32)
        except Exception as e:
            logger.warning(f"Error generando embedding: {e}")
            return np.zeros(384, dtype=np.float32)

    @staticmethod
    def new_conversation_id() -> str:
        """Acuna un identificador de conversacion nuevo (REQ-013).

        `uuid4` sin PII y no adivinable. El id solo se materializa en la DB al escribir
        la primera fila, asi que una conversacion "vacia" no puede existir en el listado
        (caso borde de SPEC-013).
        """
        return uuid.uuid4().hex

    def store(self, text: str, user_id: str = "default", category: str = "general",
              importance: float = 0.5, source: str = "conversation",
              conversation_id: Optional[str] = None,
              role: Optional[str] = None) -> Optional[int]:
        """Persiste una memoria y devuelve su `id` (o `None` si no se escribio).

        REQ-013: `conversation_id` y `role` son kwargs NUEVOS al final, ambos con default
        `None` - los callers previos al REQ (`main.py` x2, `ui/gui.py`) siguen
        comportandose exactamente igual y sus filas quedan como "no conversacionales".
        """
        if not text:
            return None
        embedding = self._get_embedding(text)
        timestamp = datetime.now().isoformat()
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.execute(
                    """INSERT INTO memories (user_id, text, embedding_json, importance, category,
                                             timestamp, source, conversation_id, role)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, text, json.dumps(embedding.tolist()), importance, category,
                     timestamp, source, conversation_id, role)
                )
                mem_id = cur.lastrowid
            with self._emb_lock:
                self._embeddings.append(embedding)
                self._embedding_ids.append(mem_id)
                self._embedding_user_ids.append(user_id)
            logger.debug(f"Recuerdo guardado: {text[:50]}... (id={mem_id}, user={user_id}, imp={importance})")
            return mem_id
        except Exception as e:
            logger.error(f"Error guardando recuerdo: {e}")
            return None

    def store_turn(self, user_text: str, assistant_text: str, conversation_id: str,
                   user_id: str = "default", matched_by: str = "",
                   importance: float = 0.5) -> None:
        """Persiste un turno completo del canal DESKTOP (REQ-013/CA-09).

        Escribe DOS filas `category="interaction"` con el mismo `conversation_id`: el
        texto original del usuario (`role="user"`) y la respuesta de la IA
        (`role="assistant"`). `matched_by` viaja en la columna `source` de la fila del
        asistente para no perder la trazabilidad que antes vivia dentro del texto
        combinado `f"{matched_by} | {result_text}"`.

        Calcula dos embeddings, asi que NUNCA debe llamarse desde el hilo de la GUI -
        `ui/gui.py` lo invoca via `run_async()`.
        """
        if not conversation_id:
            logger.warning("store_turn() sin conversation_id - turno no persistido")
            return

        if user_text:
            self.store(user_text, user_id=user_id, category="interaction",
                       importance=importance, source="desktop",
                       conversation_id=conversation_id, role="user")
        else:
            logger.warning(f"store_turn(): texto de usuario vacio (conv={conversation_id})")

        if assistant_text:
            self.store(assistant_text, user_id=user_id, category="interaction",
                       importance=importance, source=f"desktop:{matched_by}",
                       conversation_id=conversation_id, role="assistant")
        else:
            logger.warning(f"store_turn(): respuesta vacia (conv={conversation_id})")

    def list_conversations(self, user_id: str = "default", limit: int = 30,
                           offset: int = 0) -> List[ConversationSummary]:
        """Lista las conversaciones de `user_id`, mas reciente primero (REQ-013/CA-05, CA-10).

        Una sola query agregada (sin N+1 ni tabla espejo). `conversation_id IS NOT NULL`
        deja fuera las filas legacy y las de `main.py` (CA-12): siguen intactas en la DB
        y visibles para `get_recent()`/semantica, pero no aparecen como conversaciones.
        """
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    """SELECT  m.conversation_id,
                               MAX(m.timestamp) AS last_activity,
                               COUNT(*)         AS turn_count,
                               (SELECT u.text FROM memories u
                                 WHERE u.conversation_id = m.conversation_id
                                   AND u.role = 'user'
                                 ORDER BY u.id ASC LIMIT 1) AS title_src
                       FROM memories m
                       WHERE m.user_id = ? AND m.archived = 0
                             AND m.conversation_id IS NOT NULL
                       GROUP BY m.conversation_id
                       ORDER BY last_activity DESC
                       LIMIT ? OFFSET ?""",
                    (user_id, limit, offset)
                ).fetchall()
            return [
                ConversationSummary(
                    conversation_id=r[0],
                    last_activity=r[1] or "",
                    turn_count=r[2],
                    title=_derive_title(r[3]),
                )
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Error listando conversaciones: {e}")
            return []

    def get_conversation_turns(self, conversation_id: str, user_id: str = "default",
                               limit: int = 200) -> List[MemoryItem]:
        """Devuelve los turnos de una conversacion en orden cronologico (REQ-013/CA-11).

        Ordena por `id ASC`, no por `timestamp`: el id es monotonico e inmune a dos
        inserciones dentro del mismo segundo (el caso exacto de un turno usuario+IA).
        `limit` acota conversaciones muy largas a los ULTIMOS N turnos, devueltos igual
        en orden ascendente.
        """
        if not conversation_id:
            return []
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    f"""SELECT {_MEMORY_COLUMNS} FROM (
                            SELECT {_MEMORY_COLUMNS} FROM memories
                            WHERE conversation_id = ? AND user_id = ? AND archived = 0
                            ORDER BY id DESC LIMIT ?
                        ) ORDER BY id ASC""",
                    (conversation_id, user_id, limit)
                ).fetchall()
            return [_row_to_item(r) for r in rows]
        except Exception as e:
            logger.error(f"Error obteniendo turnos de conversacion: {e}")
            return []

    def search_semantic(self, query: str, user_id: str = "default",
                        top_k: int = 5, threshold: float = 0.6) -> List[MemoryItem]:
        if not self._embeddings:
            return []
        query_emb = self._get_embedding(query)
        query_norm = query_emb / (np.linalg.norm(query_emb) + 1e-10)
        # REQ-013: se toma una foto coherente de las tres listas bajo `_emb_lock` antes de
        # operar; si un `store()` de otro hilo agrega un embedding en el medio, esta
        # busqueda usa el estado previo completo en vez de un trio desalineado.
        with self._emb_lock:
            if not self._embeddings:
                return []
            all_embs = np.array(self._embeddings, dtype=np.float32)
            embedding_ids = list(self._embedding_ids)
            embedding_user_ids = list(self._embedding_user_ids)
        norms = np.linalg.norm(all_embs, axis=1, keepdims=True) + 1e-10
        all_normed = all_embs / norms
        scores = np.dot(all_normed, query_norm)

        user_mask = np.array([u == user_id for u in embedding_user_ids])
        scores[~user_mask] = -1
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        try:
            with sqlite3.connect(DB_PATH) as conn:
                for idx in top_indices:
                    score = float(scores[idx])
                    if score < threshold:
                        continue
                    mem_id = embedding_ids[idx]
                    row = conn.execute(
                        f"SELECT {_MEMORY_COLUMNS} FROM memories WHERE id=?",
                        (mem_id,)
                    ).fetchone()
                    if row:
                        results.append(_row_to_item(row))
        except Exception as e:
            logger.error(f"Error en búsqueda semántica: {e}")
        return results

    def search_keyword(self, query: str, user_id: str = "default",
                       limit: int = 10) -> List[MemoryItem]:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    f"""SELECT {_MEMORY_COLUMNS}
                        FROM memories WHERE user_id=? AND archived=0 AND
                        (text LIKE ? OR text LIKE ? OR text LIKE ?)
                        ORDER BY importance DESC, timestamp DESC LIMIT ?""",
                    (user_id, f"%{query}%", f"%{query.lower()}%", f"%{query.upper()}%", limit)
                ).fetchall()
            return [_row_to_item(r) for r in rows]
        except Exception as e:
            logger.error(f"Error en búsqueda keyword: {e}")
            return []

    def get_important_memories(self, user_id: str = "default",
                                min_importance: float = 0.6, limit: int = 20) -> List[MemoryItem]:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    f"""SELECT {_MEMORY_COLUMNS}
                        FROM memories WHERE user_id=? AND archived=0 AND importance >= ?
                        ORDER BY importance DESC, timestamp DESC LIMIT ?""",
                    (user_id, min_importance, limit)
                ).fetchall()
            return [_row_to_item(r) for r in rows]
        except Exception as e:
            logger.error(f"Error obteniendo recuerdos importantes: {e}")
            return []

    def get_summary(self, user_id: str = "default") -> str:
        important = self.get_important_memories(user_id, min_importance=0.7, limit=10)
        if not important:
            return "Aún no tengo recuerdos importantes tuyos, Señor."
        lines = ["Esto es lo que recuerdo de ti:\n"]
        for mem in important:
            trunc = mem.text[:120] + "..." if len(mem.text) > 120 else mem.text
            ts = mem.timestamp[:10] if mem.timestamp else ""
            star = "⭐" if mem.importance >= 0.8 else "•"
            lines.append(f"{star} [{mem.category}] {trunc} ({ts})")
        return "\n".join(lines)

    def store_summary(self, user_id: str, summary_text: str,
                      summary_type: str = "partial", msg_count: int = 0):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    """INSERT INTO summaries (user_id, summary_text, summary_type, msg_count, timestamp)
                       VALUES (?, ?, ?, ?, ?)""",
                    (user_id, summary_text, summary_type, msg_count, datetime.now().isoformat())
                )
            importance = 0.7 if summary_type == "partial" else 0.9
            self.store(summary_text, user_id, category="summary", importance=importance,
                      source=f"auto_summary_{summary_type}")
        except Exception as e:
            logger.error(f"Error guardando resumen: {e}")

    def get_recent(self, user_id: str = "default", limit: int = 4,
                    category: str = "interaction",
                    role: Optional[str] = None) -> List[MemoryItem]:
        """Return the `limit` most recent memories for `user_id`, ordered by recency only.

        Sin filtro de query ni umbral de importancia (REQ-008/CA-09) — a diferencia de
        `search_semantic()`/`search_keyword()`/`get_important_memories()`. Filtra por
        `category="interaction"` por defecto para no duplicar la copia `"semantic"` que
        `main.py` guarda del mismo turno (líneas 166-172 de `main.py`).

        REQ-013: `role` es un kwarg NUEVO. Sin el, el comportamiento es identico al previo
        al REQ. Con `role="user"` el predicado es `(role = ? OR role IS NULL)`: devuelve
        una entrada por turno en vez del par usuario/respuesta alternado, y el `OR NULL`
        conserva las filas legacy y las de `main.py`, que no tienen rol (CA-12).
        """
        try:
            sql = (
                f"SELECT {_MEMORY_COLUMNS} FROM memories "
                "WHERE user_id=? AND archived=0 AND category=?"
            )
            params: List[Any] = [user_id, category]
            if role is not None:
                sql += " AND (role = ? OR role IS NULL)"
                params.append(role)
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(sql, tuple(params)).fetchall()
            return [_row_to_item(r) for r in rows]
        except Exception as e:
            logger.error(f"Error obteniendo recuerdos recientes: {e}")
            return []

    def get_recent_summaries(self, user_id: str, limit: int = 3) -> List[str]:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    "SELECT summary_text FROM summaries WHERE user_id=? ORDER BY timestamp DESC LIMIT ?",
                    (user_id, limit)
                ).fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []

    def get_user_profile_text(self, user_id: str, max_chars: int = 2000) -> str:
        parts = []
        important = self.get_important_memories(user_id, min_importance=0.8, limit=5)
        for mem in important:
            parts.append(f"- {mem.text[:150]}")
        summaries = self.get_recent_summaries(user_id, limit=2)
        for s in summaries:
            parts.append(f"[Resumen] {s[:200]}")
        full = "\n".join(parts)
        return full[:max_chars]

    def consolidate(self):
        try:
            cutoff = (datetime.now() - timedelta(days=7)).isoformat()
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    "UPDATE memories SET archived=1 WHERE importance < 0.3 AND timestamp < ? AND archived=0",
                    (cutoff,)
                )
                archived = conn.execute(
                    "SELECT changes()"
                ).fetchone()[0]
            if archived > 0:
                logger.info(f"Consolidación: {archived} recuerdos archivados")
            self._load_embeddings()
        except Exception as e:
            logger.error(f"Error en consolidación: {e}")

    def _start_consolidation_thread(self):
        def run():
            while True:
                time.sleep(86400)
                try:
                    self.consolidate()
                except Exception as e:
                    logger.warning(f"Error en consolidación programada: {e}")
        t = threading.Thread(target=run, daemon=True, name="MemoryConsolidation")
        t.start()
        logger.info("Hilo de consolidación de memoria iniciado (cada 24h)")

    def clear_user_memory(self, user_id: str):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("DELETE FROM memories WHERE user_id=?", (user_id,))
                conn.execute("DELETE FROM summaries WHERE user_id=?", (user_id,))
            self._load_embeddings()
            logger.info(f"Memoria del usuario {user_id} limpiada")
        except Exception as e:
            logger.error(f"Error limpiando memoria: {e}")


_TITLE_MAX_LEN = 60


def _derive_title(first_user_text: Optional[str]) -> str:
    """Titulo de una conversacion: primer mensaje del usuario, recortado (REQ-013/CA-10).

    `None` (conversacion sin ninguna fila `role='user'`) devuelve un texto explicito -
    nunca lanza ni inventa contenido.
    """
    text = (first_user_text or "").replace("\n", " ").strip()
    if not text:
        return "(sin titulo)"
    if len(text) > _TITLE_MAX_LEN:
        return text[:_TITLE_MAX_LEN].rstrip() + "\u2026"
    return text


memory = UnifiedMemory()
