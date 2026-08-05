import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.dirname(__file__))
DB_PATH = os.path.join(DB_DIR, "unified_memory.db")

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
            logger.info(f"Base de datos unificada inicializada: {DB_PATH}")
        except Exception as e:
            logger.error(f"Error inicializando DB: {e}")

    def _load_embeddings(self):
        self._embeddings.clear()
        self._embedding_ids.clear()
        self._embedding_user_ids.clear()
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    "SELECT id, user_id, embedding_json FROM memories WHERE archived=0 AND embedding_json IS NOT NULL"
                ).fetchall()
            for row_id, user_id, emb_json in rows:
                if emb_json:
                    self._embeddings.append(np.array(json.loads(emb_json), dtype=np.float32))
                    self._embedding_ids.append(row_id)
                    self._embedding_user_ids.append(user_id)
            logger.info(f"{len(self._embeddings)} embeddings cargados en RAM")
        except Exception as e:
            logger.warning(f"Error cargando embeddings: {e}")

    def _get_embedding(self, text: str) -> np.ndarray:
        try:
            from ai.embedding_engine import create_embedding
            return np.array(create_embedding(text), dtype=np.float32)
        except Exception as e:
            logger.warning(f"Error generando embedding: {e}")
            return np.zeros(384, dtype=np.float32)

    def store(self, text: str, user_id: str = "default", category: str = "general",
              importance: float = 0.5, source: str = "conversation"):
        if not text:
            return
        embedding = self._get_embedding(text)
        timestamp = datetime.now().isoformat()
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.execute(
                    """INSERT INTO memories (user_id, text, embedding_json, importance, category, timestamp, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, text, json.dumps(embedding.tolist()), importance, category, timestamp, source)
                )
                mem_id = cur.lastrowid
            self._embeddings.append(embedding)
            self._embedding_ids.append(mem_id)
            self._embedding_user_ids.append(user_id)
            logger.debug(f"Recuerdo guardado: {text[:50]}... (id={mem_id}, user={user_id}, imp={importance})")
        except Exception as e:
            logger.error(f"Error guardando recuerdo: {e}")

    def search_semantic(self, query: str, user_id: str = "default",
                        top_k: int = 5, threshold: float = 0.6) -> List[MemoryItem]:
        if not self._embeddings:
            return []
        query_emb = self._get_embedding(query)
        query_norm = query_emb / (np.linalg.norm(query_emb) + 1e-10)
        all_embs = np.array(self._embeddings, dtype=np.float32)
        norms = np.linalg.norm(all_embs, axis=1, keepdims=True) + 1e-10
        all_normed = all_embs / norms
        scores = np.dot(all_normed, query_norm)

        user_mask = np.array([u == user_id for u in self._embedding_user_ids])
        scores[~user_mask] = -1
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        try:
            with sqlite3.connect(DB_PATH) as conn:
                for idx in top_indices:
                    score = float(scores[idx])
                    if score < threshold:
                        continue
                    mem_id = self._embedding_ids[idx]
                    row = conn.execute(
                        "SELECT id, user_id, text, importance, category, timestamp, archived, source FROM memories WHERE id=?",
                        (mem_id,)
                    ).fetchone()
                    if row:
                        item = MemoryItem(
                            id=row[0], user_id=row[1], text=row[2],
                            importance=row[3], category=row[4],
                            timestamp=row[5], archived=bool(row[6]), source=row[7]
                        )
                        results.append(item)
        except Exception as e:
            logger.error(f"Error en búsqueda semántica: {e}")
        return results

    def search_keyword(self, query: str, user_id: str = "default",
                       limit: int = 10) -> List[MemoryItem]:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    """SELECT id, user_id, text, importance, category, timestamp, archived, source
                       FROM memories WHERE user_id=? AND archived=0 AND
                       (text LIKE ? OR text LIKE ? OR text LIKE ?)
                       ORDER BY importance DESC, timestamp DESC LIMIT ?""",
                    (user_id, f"%{query}%", f"%{query.lower()}%", f"%{query.upper()}%", limit)
                ).fetchall()
            return [MemoryItem(id=r[0], user_id=r[1], text=r[2], importance=r[3],
                               category=r[4], timestamp=r[5], archived=bool(r[6]), source=r[7])
                    for r in rows]
        except Exception as e:
            logger.error(f"Error en búsqueda keyword: {e}")
            return []

    def get_important_memories(self, user_id: str = "default",
                                min_importance: float = 0.6, limit: int = 20) -> List[MemoryItem]:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    """SELECT id, user_id, text, importance, category, timestamp, archived, source
                       FROM memories WHERE user_id=? AND archived=0 AND importance >= ?
                       ORDER BY importance DESC, timestamp DESC LIMIT ?""",
                    (user_id, min_importance, limit)
                ).fetchall()
            return [MemoryItem(id=r[0], user_id=r[1], text=r[2], importance=r[3],
                               category=r[4], timestamp=r[5], archived=bool(r[6]), source=r[7])
                    for r in rows]
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
                    category: str = "interaction") -> List[MemoryItem]:
        """Return the `limit` most recent memories for `user_id`, ordered by recency only.

        Sin filtro de query ni umbral de importancia (REQ-008/CA-09) — a diferencia de
        `search_semantic()`/`search_keyword()`/`get_important_memories()`. Filtra por
        `category="interaction"` por defecto para no duplicar la copia `"semantic"` que
        `main.py` guarda del mismo turno (líneas 166-172 de `main.py`).
        """
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    """SELECT id, user_id, text, importance, category, timestamp, archived, source
                       FROM memories WHERE user_id=? AND archived=0 AND category=?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (user_id, category, limit)
                ).fetchall()
            return [MemoryItem(id=r[0], user_id=r[1], text=r[2], importance=r[3],
                               category=r[4], timestamp=r[5], archived=bool(r[6]), source=r[7])
                    for r in rows]
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


memory = UnifiedMemory()
