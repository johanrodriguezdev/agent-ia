import hashlib
import logging
import os
import sqlite3
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)

AUTH_PIN_ENV = "ORION_AUTH_PIN"


class RiskLevel(Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class ChannelType(Enum):
    DESKTOP = "desktop"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    VOICE = "voice"


CHANNEL_ALLOWED_LEVELS: Dict[ChannelType, List[RiskLevel]] = {
    ChannelType.DESKTOP: [RiskLevel.GREEN, RiskLevel.YELLOW],
    ChannelType.TELEGRAM: [RiskLevel.GREEN],
    ChannelType.DISCORD: [RiskLevel.GREEN],
    ChannelType.VOICE: [RiskLevel.GREEN],
}

AUDIT_DB = os.path.join(os.path.dirname(__file__), "..", "audit.db")


class SecurityManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._actions: Dict[str, RiskLevel] = {}
            cls._instance._init_audit()
        return cls._instance

    def _init_audit(self):
        try:
            with sqlite3.connect(AUDIT_DB) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        action TEXT NOT NULL,
                        channel TEXT NOT NULL,
                        user_id TEXT DEFAULT 'default',
                        result TEXT NOT NULL,
                        details TEXT DEFAULT ''
                    )
                """)
        except Exception as e:
            logger.warning(f"No se pudo inicializar auditoría: {e}")

    def _log_audit(self, action: str, channel: ChannelType, result: str, user_id: str = "default", details: str = ""):
        try:
            with sqlite3.connect(AUDIT_DB) as conn:
                conn.execute(
                    "INSERT INTO audit_log (timestamp, action, channel, user_id, result, details) VALUES (?, ?, ?, ?, ?, ?)",
                    (datetime.now().isoformat(), action, channel.value, user_id, result, details)
                )
        except Exception as e:
            logger.warning(f"Error registrando auditoría: {e}")

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        try:
            with sqlite3.connect(AUDIT_DB) as conn:
                rows = conn.execute(
                    "SELECT timestamp, action, channel, user_id, result, details FROM audit_log ORDER BY id DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return [
                {"timestamp": r[0], "action": r[1], "channel": r[2], "user_id": r[3], "result": r[4], "details": r[5]}
                for r in rows
            ]
        except Exception:
            return []

    def has_pin(self) -> bool:
        return bool(os.environ.get(AUTH_PIN_ENV, ""))

    def verify_pin(self, pin: str) -> bool:
        if not self.has_pin():
            return True
        stored = os.environ.get(AUTH_PIN_ENV, "")
        return pin == stored or hashlib.sha256(pin.encode()).hexdigest() == stored

    def require_pin(self, prompt: str = "Ingrese su PIN de seguridad: ") -> bool:
        if not self.has_pin():
            return True
        import getpass
        for _ in range(3):
            pin = getpass.getpass(prompt)
            if self.verify_pin(pin):
                return True
            logger.warning("PIN incorrecto")
        return False

    def register_action(self, name: str, level: RiskLevel):
        self._actions[name] = level

    def classify_action(self, name: str) -> Optional[RiskLevel]:
        return self._actions.get(name)

    def get_allowed_levels(self, channel: ChannelType) -> List[RiskLevel]:
        return CHANNEL_ALLOWED_LEVELS.get(channel, [RiskLevel.GREEN])

    def is_action_allowed(self, action_name: str, channel: ChannelType) -> bool:
        level = self.classify_action(action_name)
        if level is None:
            return True
        allowed = self.get_allowed_levels(channel)
        return level in allowed

    def require_confirmation(self, action_name: str, channel: ChannelType, details: str = "", user_id: str = "default") -> bool:
        level = self.classify_action(action_name)
        if level is None or level == RiskLevel.GREEN:
            self._log_audit(action_name, channel, "permitida", user_id, details)
            return True
        if not self.is_action_allowed(action_name, channel):
            logger.warning(f"Acción '{action_name}' no permitida en canal {channel.value}")
            self._log_audit(action_name, channel, "bloqueada_canal", user_id, details)
            return False
        if level == RiskLevel.YELLOW:
            msg = f"¿Estás seguro de que quieres ejecutar '{action_name}'?"
            if details:
                msg += f" ({details})"
            response = input(f"\n⚠️  {msg}\nEscribe 'sí' para confirmar, o cualquier otra cosa para cancelar: ")
            confirmed = response.strip().lower() in ("sí", "si", "yes", "s")
            result = "confirmada" if confirmed else "cancelada"
            self._log_audit(action_name, channel, result, user_id, details)
            if confirmed:
                logger.info(f"Acción amarilla '{action_name}' confirmada por usuario en {channel.value}")
            else:
                logger.info(f"Acción amarilla '{action_name}' cancelada por usuario en {channel.value}")
            return confirmed
        if level == RiskLevel.RED:
            self._log_audit(action_name, channel, "intento_rojo", user_id, details)
            logger.warning(f"Intento de acción roja '{action_name}' desde {channel.value}")
            if channel == ChannelType.DESKTOP and self.has_pin():
                if self.require_pin(f"⛔ Acción ROJO '{action_name}'. {details}\nIngrese su PIN maestro para autorizar: "):
                    self._log_audit(action_name, channel, "autorizada_rojo", user_id, details)
                    logger.info(f"Acción roja '{action_name}' autorizada por PIN maestro")
                    return True
            msg = f"⛔ Acción '{action_name}' clasificada como ROJO. No autorizada."
            print(msg)
            return False
        return True


security_manager = SecurityManager()


def _register_default_actions():
    sm = security_manager
    sm.register_action("shutdown", RiskLevel.YELLOW)
    sm.register_action("restart", RiskLevel.YELLOW)
    sm.register_action("close_app", RiskLevel.YELLOW)
    sm.register_action("delete_file", RiskLevel.YELLOW)
    sm.register_action("delete_folder", RiskLevel.YELLOW)
    sm.register_action("execute_code", RiskLevel.YELLOW)
    sm.register_action("create_skill", RiskLevel.YELLOW)
    sm.register_action("modify_skill", RiskLevel.YELLOW)
    sm.register_action("delete_skill", RiskLevel.YELLOW)
    sm.register_action("send_message", RiskLevel.YELLOW)
    sm.register_action("system_info", RiskLevel.GREEN)
    sm.register_action("search_files", RiskLevel.GREEN)
    sm.register_action("web_search", RiskLevel.GREEN)
    sm.register_action("chat", RiskLevel.GREEN)
    sm.register_action("open_app", RiskLevel.GREEN)
    sm.register_action("play_media", RiskLevel.GREEN)
    sm.register_action("screenshot", RiskLevel.GREEN)
    sm.register_action("weather", RiskLevel.GREEN)
    sm.register_action("list_files", RiskLevel.GREEN)
    sm.register_action("format_disk", RiskLevel.RED)
    sm.register_action("delete_database", RiskLevel.RED)
    sm.register_action("expose_secrets", RiskLevel.RED)
    sm.register_action("modify_source_code", RiskLevel.RED)


_register_default_actions()
