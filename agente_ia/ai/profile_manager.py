import json
import logging
import os
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.dirname(__file__))
DB_PATH = os.path.join(DB_DIR, "unified_memory.db")


class ProfileManager:
    def __init__(self):
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS profiles (
                        user_id TEXT PRIMARY KEY,
                        name TEXT DEFAULT '',
                        preferences TEXT DEFAULT '{}',
                        traits TEXT DEFAULT '[]',
                        last_interaction TEXT DEFAULT '',
                        interaction_count INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                """)
        except Exception as e:
            logger.error(f"Error inicializando profiles DB: {e}")

    def get_or_create(self, user_id: str, name: str = "") -> dict:
        try:
            with sqlite3.connect(DB_PATH) as conn:
                row = conn.execute(
                    "SELECT * FROM profiles WHERE user_id=?", (user_id,)
                ).fetchone()
                if row:
                    return {
                        "user_id": row[0],
                        "name": row[1],
                        "preferences": json.loads(row[2]),
                        "traits": json.loads(row[3]),
                        "last_interaction": row[4],
                        "interaction_count": row[5],
                        "created_at": row[6],
                    }
                now = datetime.now().isoformat()
                conn.execute(
                    "INSERT INTO profiles (user_id, name, created_at) VALUES (?, ?, ?)",
                    (user_id, name, now),
                )
                return {
                    "user_id": user_id,
                    "name": name,
                    "preferences": {},
                    "traits": [],
                    "last_interaction": "",
                    "interaction_count": 0,
                    "created_at": now,
                }
        except Exception as e:
            logger.error(f"Error get_or_create profile: {e}")
            return {"user_id": user_id, "name": name, "preferences": {}, "traits": []}

    def set_preference(self, user_id: str, key: str, value):
        profile = self.get_or_create(user_id)
        prefs = profile.get("preferences", {})
        prefs[key] = value
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    "UPDATE profiles SET preferences=? WHERE user_id=?",
                    (json.dumps(prefs), user_id),
                )
        except Exception as e:
            logger.error(f"Error set_preference: {e}")

    def get_preference(self, user_id: str, key: str, default=None):
        profile = self.get_or_create(user_id)
        return profile.get("preferences", {}).get(key, default)

    def add_trait(self, user_id: str, trait: str):
        profile = self.get_or_create(user_id)
        traits = profile.get("traits", [])
        if trait not in traits:
            traits.append(trait)
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute(
                        "UPDATE profiles SET traits=? WHERE user_id=?",
                        (json.dumps(traits), user_id),
                    )
            except Exception as e:
                logger.error(f"Error add_trait: {e}")

    def record_interaction(self, user_id: str):
        try:
            now = datetime.now().isoformat()
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    """UPDATE profiles SET last_interaction=?, interaction_count=interaction_count+1
                       WHERE user_id=?""",
                    (now, user_id),
                )
        except Exception as e:
            logger.error(f"Error record_interaction: {e}")

    def get_profile_text(self, user_id: str) -> str:
        profile = self.get_or_create(user_id)
        parts = []
        if profile.get("name"):
            parts.append(f"Nombre: {profile['name']}")
        if profile.get("preferences"):
            parts.append(f"Preferencias: {json.dumps(profile['preferences'], ensure_ascii=False)}")
        if profile.get("traits"):
            parts.append(f"Rasgos: {', '.join(profile['traits'])}")
        if profile.get("interaction_count", 0) > 0:
            parts.append(f"Interacciones: {profile['interaction_count']}")
        return "\n".join(parts) if parts else ""


profile_manager = ProfileManager()
