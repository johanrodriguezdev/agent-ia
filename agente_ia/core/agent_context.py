import json
import logging
import sqlite3
import os
from typing import Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agent_context.db")


class AgentContext:
    def __init__(self, agent_name: str, user_id: str):
        self.agent_name = agent_name
        self.user_id = user_id
        self.conversation: List[dict] = []
        self.metadata: dict = {}


class AgentContextManager:
    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._cache: Dict[str, AgentContext] = {}
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS agent_context (
                        agent_name TEXT,
                        user_id TEXT,
                        context_json TEXT,
                        updated_at TEXT,
                        PRIMARY KEY (agent_name, user_id)
                    )
                """)
            logger.info(f"Base de datos de contexto de agentes inicializada: {self._db_path}")
        except Exception as e:
            logger.warning(f"No se pudo inicializar DB de contexto: {e}")

    def _cache_key(self, agent_name: str, user_id: str) -> str:
        return f"{agent_name}:{user_id}"

    def get_context(self, agent_name: str, user_id: str) -> AgentContext:
        key = self._cache_key(agent_name, user_id)
        if key in self._cache:
            return self._cache[key]

        context = AgentContext(agent_name, user_id)
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT context_json FROM agent_context WHERE agent_name=? AND user_id=?",
                    (agent_name, user_id)
                ).fetchone()
                if row:
                    data = json.loads(row[0])
                    context.conversation = data.get("conversation", [])
                    context.metadata = data.get("metadata", {})
        except Exception as e:
            logger.debug(f"Error cargando contexto para {agent_name}/{user_id}: {e}")

        self._cache[key] = context
        return context

    def update_context(self, agent_name: str, user_id: str, entry: dict):
        context = self.get_context(agent_name, user_id)
        context.conversation.append({
            **entry,
            "timestamp": datetime.now().isoformat()
        })
        if len(context.conversation) > 50:
            context.conversation = context.conversation[-50:]

        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO agent_context (agent_name, user_id, context_json, updated_at)
                       VALUES (?, ?, ?, ?)""",
                    (agent_name, user_id, json.dumps({
                        "conversation": context.conversation,
                        "metadata": context.metadata
                    }), datetime.now().isoformat())
                )
        except Exception as e:
            logger.warning(f"Error guardando contexto para {agent_name}/{user_id}: {e}")

    def clear_context(self, agent_name: str, user_id: str):
        key = self._cache_key(agent_name, user_id)
        self._cache.pop(key, None)
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "DELETE FROM agent_context WHERE agent_name=? AND user_id=?",
                    (agent_name, user_id)
                )
        except Exception as e:
            logger.warning(f"Error limpiando contexto: {e}")

    def set_metadata(self, agent_name: str, user_id: str, key: str, value: any):
        context = self.get_context(agent_name, user_id)
        context.metadata[key] = value
        self.update_context(agent_name, user_id, {"type": "metadata_update"})


agent_context_manager = AgentContextManager()
