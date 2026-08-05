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


class ActionDenied(Exception):
    """Excepción estructurada de denegación (REQ-006, CA-09).

    Reemplaza la detección de denegación por substring (bug H7 de
    `core/base_agent.py:103`: `"Error" not in result[:10]`, que confundía un mensaje de
    denegación —p.ej. `"⛔ Acción no autorizada."`— con un resultado exitoso porque no
    empieza con la palabra "Error"). La levantan los dos únicos puntos de gate del
    sistema, `router/dispatcher.py:dispatch()` y `agents/tool_registry.py:execute_tool()`,
    nunca `security_manager.require_confirmation()` (que sigue devolviendo `bool` para no
    romper los ~40 call-sites y los 49 tests existentes de REQ-005 que ya consumen ese
    contrato).
    """

    def __init__(self, action_name: str, channel=None, reason: str = ""):
        self.action_name = action_name
        self.channel = channel
        self.reason = reason
        message = f"Acción '{action_name}' denegada"
        if channel is not None:
            message += f" (canal={getattr(channel, 'value', channel)})"
        if reason:
            message += f": {reason}"
        super().__init__(message)


class ChannelType(Enum):
    DESKTOP = "desktop"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    VOICE = "voice"
    API = "api"
    UNKNOWN = "unknown"


CHANNEL_ALLOWED_LEVELS: Dict[ChannelType, List[RiskLevel]] = {
    ChannelType.DESKTOP: [RiskLevel.GREEN, RiskLevel.YELLOW],
    ChannelType.TELEGRAM: [RiskLevel.GREEN],
    ChannelType.DISCORD: [RiskLevel.GREEN],
    ChannelType.VOICE: [RiskLevel.GREEN],
    ChannelType.API: [RiskLevel.GREEN],
    ChannelType.UNKNOWN: [RiskLevel.GREEN],
}

_CHANNEL_STR_MAP: Dict[str, ChannelType] = {
    "desktop": ChannelType.DESKTOP,
    "telegram": ChannelType.TELEGRAM,
    "discord": ChannelType.DISCORD,
    "voice": ChannelType.VOICE,
    "api": ChannelType.API,
    "unknown": ChannelType.UNKNOWN,
}

AUDIT_DB = os.path.join(os.path.dirname(__file__), "..", "audit.db")

# Claves de `params` que se muestran en el prompt de confirmación y se guardan en la
# auditoría. Es una ALLOWLIST deliberada, no una denylist: el `details` resultante se
# imprime al humano y se persiste en audit.db, así que nunca se vuelca `params` crudo
# —podría arrastrar credenciales, tokens o contenido de archivo—. `channel` queda fuera
# a propósito: es ruido para el humano y ya se audita en su propia columna.
_DETAILS_ALLOWED_KEYS = (
    "app_name", "app", "task", "raw_text", "skill_name", "name",
    "path", "filename", "folder", "query", "url", "direction",
)

# Un `task`/`raw_text` puede traer código largo: se trunca para que el prompt siga siendo
# legible en consola y para no inundar el log de auditoría.
_DETAILS_MAX_VALUE_LEN = 200


def format_details(prefix: str, params: Optional[Dict] = None) -> str:
    """Return `prefix` plus the identifying params a human needs to judge the action."""
    if not params:
        return prefix

    partes: List[str] = []
    for key in _DETAILS_ALLOWED_KEYS:
        value = params.get(key)
        if value is None or value == "":
            continue
        texto = " ".join(str(value).split())
        if len(texto) > _DETAILS_MAX_VALUE_LEN:
            texto = texto[:_DETAILS_MAX_VALUE_LEN] + "..."
        partes.append(f"{key}={texto}")

    if not partes:
        return prefix
    return f"{prefix} | " + ", ".join(partes)


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

    def resolve_channel(self, channel) -> "ChannelType":
        """Resuelve cualquier valor de canal (ChannelType, str o None) a un ChannelType válido.

        Única función de resolución de canal del sistema. Si `channel` es `None` o no
        coincide con ningún valor conocido, retorna `ChannelType.UNKNOWN` (nivel GREEN-only)
        en vez de `ChannelType.DESKTOP` (el más permisivo). Esto evita que un caller que
        "pierda" el canal real herede por defecto el nivel de confianza más alto del sistema.
        """
        if isinstance(channel, ChannelType):
            return channel
        if channel is None:
            return ChannelType.UNKNOWN
        return _CHANNEL_STR_MAP.get(str(channel).lower(), ChannelType.UNKNOWN)

    def register_action(self, name: str, level: RiskLevel) -> bool:
        """Registra o actualiza la clasificación de riesgo de una acción.

        Rechaza (retorna False) cualquier intento de degradar una acción ya clasificada
        como RiskLevel.RED a un nivel menor. En cualquier otro caso aplica el cambio y
        retorna True.
        """
        current = self._actions.get(name)
        if current == RiskLevel.RED and level != RiskLevel.RED:
            logger.critical(
                f"Intento de reclasificar acción ROJO '{name}' a '{level.value}' bloqueado"
            )
            self._log_audit(name, ChannelType.UNKNOWN, "reclasificacion_bloqueada", details=f"nivel_solicitado={level.value}")
            return False
        self._actions[name] = level
        return True

    def classify_action(self, name: str) -> Optional[RiskLevel]:
        return self._actions.get(name)

    def get_allowed_levels(self, channel: ChannelType) -> List[RiskLevel]:
        return CHANNEL_ALLOWED_LEVELS.get(channel, [RiskLevel.GREEN])

    def check_coverage(self, action_names: List[str]) -> List[str]:
        """Retorna la sublista de `action_names` que no tiene clasificación registrada.

        Utilidad de diagnóstico, no bloquea nada. Pensada para detectar en logs, antes de
        que un usuario lo sufra, un intent/acción nuevo agregado sin clasificar.
        """
        return [name for name in action_names if self.classify_action(name) is None]

    def is_action_allowed(self, action_name: str, channel: ChannelType) -> bool:
        level = self.classify_action(action_name)
        if level is None:
            return False
        allowed = self.get_allowed_levels(channel)
        return level in allowed

    def require_confirmation(self, action_name: str, channel, details: str = "", user_id: str = "default") -> bool:
        """Punto central único de decisión de seguridad para O.R.I.O.N.

        Evalúa el nivel de riesgo de `action_name` y decide si la acción puede ejecutarse,
        aplicando fail-closed (una acción sin clasificar se bloquea), la UX de confirmación
        YELLOW, y la única vía de excepción verificada (PIN maestro) para RED en canal DESKTOP.

        INVARIANTE DE SEGURIDAD — `channel`: el parámetro `channel` debe provenir siempre de
        una fuente controlada por el flujo de invocación (el canal real del mensaje, o
        `'desktop'` fijo en el loop de escritorio) — nunca debe leerse un valor de `channel`
        que haya pasado, sin sobrescritura posterior, por `extract_params()` de una skill,
        porque ese método parsea texto libre del usuario y un usuario podría intentar
        inyectar `channel="desktop"` en el texto para auto-otorgarse el canal más permisivo.
        Cada camino de invocación (orchestrator, dispatcher, main.py) debe reasignar
        `channel` de forma incondicional a partir de su fuente confiable antes de llegar aquí.
        """
        channel = self.resolve_channel(channel)
        level = self.classify_action(action_name)
        if level is None:
            logger.warning(f"Acción '{action_name}' sin clasificación registrada — bloqueada (fail-closed)")
            self._log_audit(action_name, channel, "bloqueada_no_clasificada", user_id, details)
            return False
        if level == RiskLevel.GREEN:
            self._log_audit(action_name, channel, "permitida", user_id, details)
            return True
        if level == RiskLevel.YELLOW:
            if not self.is_action_allowed(action_name, channel):
                logger.warning(f"Acción '{action_name}' no permitida en canal {channel.value}")
                self._log_audit(action_name, channel, "bloqueada_canal", user_id, details)
                return False
            msg = f"¿Estás seguro de que quieres ejecutar '{action_name}'?"
            if details:
                msg += f" ({details})"
            from core.confirmation import get_confirmation_adapter
            adapter = get_confirmation_adapter(channel)
            if adapter is None:
                logger.warning(
                    f"Canal {channel.value} sin adaptador de confirmación — "
                    f"'{action_name}' bloqueada (fail-closed)"
                )
                self._log_audit(action_name, channel, "bloqueada_sin_adaptador", user_id, details)
                return False
            full_msg = f"\n⚠️  {msg}\nEscribe 'sí' para confirmar, o cualquier otra cosa para cancelar: "
            confirmed = adapter(action_name, full_msg)
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
    sm.register_action("chat", RiskLevel.GREEN)
    sm.register_action("open_app", RiskLevel.GREEN)
    sm.register_action("list_files", RiskLevel.GREEN)
    sm.register_action("proactive_trigger", RiskLevel.GREEN)
    # 🔴 Rojo — 4 ya implementadas
    sm.register_action("format_disk", RiskLevel.RED)
    sm.register_action("delete_database", RiskLevel.RED)
    sm.register_action("expose_secrets", RiskLevel.RED)
    sm.register_action("modify_source_code", RiskLevel.RED)
    # 🔴 Rojo — 6 sin implementación hoy, pre-registradas para quedar bloqueadas por defecto
    sm.register_action("send_email_as_user", RiskLevel.RED)
    sm.register_action("post_social_media", RiskLevel.RED)
    sm.register_action("elevated_system_command", RiskLevel.RED)
    sm.register_action("install_uninstall_software", RiskLevel.RED)
    sm.register_action("modify_system_env_vars", RiskLevel.RED)
    sm.register_action("grant_third_party_access", RiskLevel.RED)


def _register_intent_actions():
    """Registra la clasificación de cada Intent real del sistema (usando Intent.value
    como clave, sin renombrar intent/intentions.py), según el inventario de baseline-005.md.
    """
    sm = security_manager
    green_intents = [
        "OPEN_APP", "SEARCH_WEB", "OPEN_FOLDER", "LIST_FILES", "CREATE_FILE", "GET_TIME",
        "TAKE_SCREENSHOT", "WIKIPEDIA_SUMMARY", "RECALL_MEMORY", "TEACH_COMMAND", "PC_CLICK",
        "PC_TYPE", "PC_SCROLL", "SYS_VOL_UP", "SYS_VOL_DOWN", "SYS_MUTE", "AUTOPILOT",
        "CALCULATE", "SEARCH_FILES", "FOLDER_SIZE", "FIND_LARGEST", "SYSTEM_INFO", "CPU_INFO",
        "RAM_INFO", "CHAT", "UNKNOWN", "FILE_ANALYSIS", "PLAY_MUSIC", "ANALYZE_SCREEN",
        "LIST_SKILLS", "GET_WEATHER", "BROWSE_WEB",
    ]
    yellow_intents = [
        "CLOSE_APP", "SYS_POWER_OFF", "EXECUTE_CODE", "CREATE_SKILL", "MODIFY_SKILL",
        "DELETE_SKILL",
    ]
    for name in green_intents:
        sm.register_action(name, RiskLevel.GREEN)
    for name in yellow_intents:
        sm.register_action(name, RiskLevel.YELLOW)


def _register_action_registry_actions():
    """Registra las funciones de agents/action_registry.py con la clave literal usada en
    ACTION_REGISTRY, según el inventario de baseline-005.md.
    """
    sm = security_manager
    green_actions = [
        "open_chrome", "open_notepad", "open_explorer", "open_calculator", "open_browser",
        "open_spotify",
        "close_window", "open_file_in_notepad", "get_active_window_info", "write_text",
        "press_key", "hotkey_action", "take_screenshot", "wait_seconds", "generate_ai_summary",
        "get_current_datetime", "get_disk_info", "open_url", "search_google",
    ]
    yellow_actions = ["write_file_direct", "save_file_desktop"]
    for name in green_actions:
        sm.register_action(name, RiskLevel.GREEN)
    for name in yellow_actions:
        sm.register_action(name, RiskLevel.YELLOW)


_register_default_actions()
_register_intent_actions()
_register_action_registry_actions()
