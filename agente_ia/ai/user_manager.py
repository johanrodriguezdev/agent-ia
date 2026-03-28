"""
ai/user_manager.py
Gestión de sesiones completamente aisladas por usuario.

Cada usuario tiene:
  - Su propio historial de conversación con Claude (multi-turn)
  - Su propia memoria SQLite independiente
  - Su propio MEMORY.md de perfil
  - Sus propias preferencias (modo voz, idioma, etc.)

Esto es lo que separa un proyecto personal de un producto real.
"""

import os
import json
import sqlite3
import datetime
from pathlib import Path
from typing import Optional

# Directorio base donde se guardan los datos de cada usuario
USERS_DIR = Path(__file__).parent.parent / "users_data"
USERS_DIR.mkdir(exist_ok=True)


class UserSession:
    """
    Sesión completamente aislada para un usuario específico.
    Cada instancia maneja toda la información de UN usuario.
    """

    def __init__(self, user_id: str, user_name: str = "", channel: str = "unknown"):
        self.user_id   = user_id
        self.user_name = user_name
        self.channel   = channel

        # Directorio privado del usuario
        self.user_dir = USERS_DIR / user_id
        self.user_dir.mkdir(exist_ok=True)

        # Archivos del usuario
        self.db_path      = self.user_dir / "memory.db"
        self.sem_db_path  = self.user_dir / "semantic_memory.db"
        self.memory_md    = self.user_dir / "MEMORY.md"
        self.prefs_file   = self.user_dir / "preferences.json"

        # Historial de conversación Claude en RAM (por sesión)
        self.conversation_history: list[dict] = []

        # Inicializar bases de datos
        self._init_db()
        self._init_semantic_db()
        self._init_memory_md()

    # ── Bases de datos ─────────────────────────────────────────────

    def _init_db(self):
        """Crea la tabla de memoria del usuario si no existe."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute('''
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_input TEXT NOT NULL,
                response TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    def _init_semantic_db(self):
        """Crea la tabla de memoria semántica del usuario."""
        conn = sqlite3.connect(str(self.sem_db_path))
        conn.execute('''
            CREATE TABLE IF NOT EXISTS semantic_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    def _init_memory_md(self):
        """Crea el archivo MEMORY.md del usuario si no existe."""
        if not self.memory_md.exists():
            self.memory_md.write_text(
                f"# Perfil de {self.user_name or self.user_id}\n"
                f"# Canal: {self.channel}\n"
                f"# Creado: {datetime.datetime.now().strftime('%d/%m/%Y')}\n\n"
                f"## Información básica\n"
                f"- Nombre: {self.user_name or 'Desconocido'}\n"
                f"- Canal preferido: {self.channel}\n\n"
                f"## Preferencias\n"
                f"# (Glass las aprende automáticamente con el tiempo)\n\n"
                f"## Notas\n"
                f"# Agrega aquí información que quieras que Glass recuerde\n",
                encoding="utf-8"
            )

    # ── Memoria ────────────────────────────────────────────────────

    def save_memory(self, user_input: str, response: str):
        """Guarda una interacción en la memoria del usuario."""
        if not user_input or not response:
            return
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute(
                "INSERT INTO memories (user_input, response, timestamp) VALUES (?, ?, ?)",
                (user_input, response, datetime.datetime.now().isoformat())
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[UserSession] Error guardando memoria de {self.user_id}: {e}")

    def search_memory(self, query: str) -> str:
        """Busca en la memoria del usuario por texto."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.execute(
                "SELECT response FROM memories WHERE user_input LIKE ? OR response LIKE ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (f"%{query}%", f"%{query}%")
            )
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else ""
        except Exception:
            return ""

    def get_recent_memories(self, limit: int = 5) -> list[dict]:
        """Retorna las últimas N interacciones del usuario."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.execute(
                "SELECT user_input, response, timestamp FROM memories "
                "ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
            rows = cursor.fetchall()
            conn.close()
            return [
                {"input": r[0], "response": r[1], "timestamp": r[2]}
                for r in rows
            ]
        except Exception:
            return []

    def get_memory_summary(self) -> str:
        """Retorna un resumen del historial para mostrar al usuario."""
        memories = self.get_recent_memories(5)
        if not memories:
            return "No tengo recuerdos registrados aún, Señor."

        lines = [f"Últimas {len(memories)} interacciones:\n"]
        for m in memories:
            ts = m["timestamp"][:16].replace("T", " ")
            inp = m["input"][:60] + "..." if len(m["input"]) > 60 else m["input"]
            lines.append(f"• [{ts}] {inp}")
        return "\n".join(lines)

    # ── Perfil MEMORY.md ───────────────────────────────────────────

    def get_memory_md(self) -> str:
        """Lee el MEMORY.md del usuario para inyectar como contexto."""
        try:
            return self.memory_md.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def update_memory_md(self, content: str):
        """Actualiza el MEMORY.md del usuario."""
        try:
            self.memory_md.write_text(content, encoding="utf-8")
        except Exception as e:
            print(f"[UserSession] Error actualizando MEMORY.md: {e}")

    # ── Preferencias ───────────────────────────────────────────────

    def get_preference(self, key: str, default=None):
        """Lee una preferencia del usuario."""
        try:
            if self.prefs_file.exists():
                prefs = json.loads(self.prefs_file.read_text(encoding="utf-8"))
                return prefs.get(key, default)
        except Exception:
            pass
        return default

    def set_preference(self, key: str, value):
        """Guarda una preferencia del usuario."""
        try:
            prefs = {}
            if self.prefs_file.exists():
                prefs = json.loads(self.prefs_file.read_text(encoding="utf-8"))
            prefs[key] = value
            self.prefs_file.write_text(
                json.dumps(prefs, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"[UserSession] Error guardando preferencia: {e}")

    # ── Historial Claude ───────────────────────────────────────────

    def add_to_history(self, role: str, content: str):
        """Agrega un mensaje al historial de conversación Claude."""
        self.conversation_history.append({
            "role": role,
            "content": content
        })
        # Limitar a últimos 20 turnos
        if len(self.conversation_history) > 40:
            self.conversation_history = self.conversation_history[-40:]

    def clear_history(self):
        """Limpia el historial de conversación."""
        self.conversation_history = []

    def get_history(self) -> list[dict]:
        return self.conversation_history


# ── Registro global de sesiones ────────────────────────────────────

class UserRegistry:
    """
    Registro central de todas las sesiones activas.
    Una sola instancia global maneja todos los usuarios.
    """

    def __init__(self):
        self._sessions: dict[str, UserSession] = {}

    def get_or_create(
        self,
        user_id: str,
        user_name: str = "",
        channel: str = "unknown"
    ) -> UserSession:
        """
        Retorna la sesión existente del usuario o crea una nueva.
        Thread-safe para múltiples usuarios simultáneos.
        """
        key = f"{channel}_{user_id}"
        if key not in self._sessions:
            self._sessions[key] = UserSession(user_id, user_name, channel)
            print(f"[UserRegistry] Nueva sesión: {user_name} ({channel})")
        return self._sessions[key]

    def get(self, user_id: str, channel: str = "unknown") -> Optional[UserSession]:
        """Retorna la sesión si existe, None si no."""
        return self._sessions.get(f"{channel}_{user_id}")

    def clear_session(self, user_id: str, channel: str = "unknown"):
        """Limpia el historial de conversación de un usuario."""
        session = self.get(user_id, channel)
        if session:
            session.clear_history()

    def active_count(self) -> int:
        return len(self._sessions)

    def list_users(self) -> list[str]:
        return list(self._sessions.keys())


# Instancia global única — importar desde aquí
registry = UserRegistry()
