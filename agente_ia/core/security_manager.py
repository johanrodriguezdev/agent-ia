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


# REQ-019/CA-01 — ranking explícito de RiskLevel. `RiskLevel` sigue siendo un Enum plano
# (no IntEnum): convertirlo a IntEnum cambiaría `RiskLevel.GREEN.value` de "green" (string)
# a un entero, rompiendo el contrato ya consumido por
# `ui/webview/frontend/js/composer.js:110` (`chip-risk-${chip.risk_level}`, construido a
# partir de `level.value`). Este dict aparte es la única fuente de verdad del orden
# verde < amarillo < rojo — `ui/webview/bridge.py` lo importa directo, nunca mantiene una
# copia local (arquitectura-019.md §11.2, Hallazgo B).
_RISK_LEVEL_ORDER: Dict[RiskLevel, int] = {
    RiskLevel.GREEN: 0,
    RiskLevel.YELLOW: 1,
    RiskLevel.RED: 2,
}


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
    # Canal de entrada NO CONFIABLE: correo, webhooks, cualquier texto que un tercero
    # pueda originar sin ser un usuario autorizado. Existe para que ese contenido tenga
    # dónde entrar sin llegar nunca al agente que controla el PC. Ver CHANNEL_ALLOWED_LEVELS.
    EMAIL = "email"
    UNKNOWN = "unknown"


CHANNEL_ALLOWED_LEVELS: Dict[ChannelType, List[RiskLevel]] = {
    ChannelType.DESKTOP: [RiskLevel.GREEN, RiskLevel.YELLOW],
    ChannelType.TELEGRAM: [RiskLevel.GREEN],
    ChannelType.DISCORD: [RiskLevel.GREEN],
    ChannelType.VOICE: [RiskLevel.GREEN],
    ChannelType.API: [RiskLevel.GREEN],
    # EMAIL es el único canal con lista VACÍA, y es deliberado: ni siquiera verde.
    #
    # El resto de los canales los origina un usuario autorizado; el correo (y a futuro los
    # webhooks) los origina cualquiera del planeta. Un texto atacante que llegue acá no
    # puede disparar NINGUNA acción, ni las verdes: `open_app` y `play_media` son verdes y
    # bastarían para abrir una URL elegida por el atacante, y `recall_memory` para sacar
    # información personal por un resumen. El canal sirve para LEER y RESUMIR — producir
    # texto, no ejecutar.
    #
    # Es la traducción del `tools: {profile: "minimal"}` con que OpenClaw aísla su lector
    # de correo (openclaw-main/docs/automation/imap.md). Si algún día una acción concreta
    # tiene que habilitarse acá, va de a una por CHANNEL_ACTION_EXCEPTIONS —
    # `is_action_allowed()` evalúa esa tabla ANTES que esta, así que la lista vacía no
    # impide la excepción quirúrgica; obliga a justificarla caso por caso.
    #
    # Adicionalmente NO se registra adaptador de confirmación para EMAIL
    # (`core/confirmation.py`): sin adaptador, todo YELLOW se deniega por fail-closed. La
    # restricción no está escrita en ningún lado — es que no hay a quién preguntarle.
    ChannelType.EMAIL: [],
    ChannelType.UNKNOWN: [RiskLevel.GREEN],
}

# REQ-018/CA-02 — excepción quirúrgica por (canal, acción), evaluada ADEMÁS de
# CHANNEL_ALLOWED_LEVELS, nunca en su reemplazo. CHANNEL_ALLOWED_LEVELS sigue siendo la
# política general por canal (decisión de REQ-006, "capacidad, no autoridad"); esta tabla
# es una lista de excepciones puntuales y aditivas — habilita una acción YELLOW específica
# en un canal que de otro modo no la tendría, sin abrir el resto de las acciones YELLOW de
# ese canal. Cada entrada debe justificarse caso por caso (ver REQ-018,
# arquitectura-018.md §3/§4.1).
CHANNEL_ACTION_EXCEPTIONS: set[tuple[ChannelType, str]] = {
    (ChannelType.TELEGRAM, "delete_task"),
    # Control del escritorio desde Telegram. El caso que lo motiva es concreto: estar lejos
    # del equipo, pedir una captura para ver en qué punto quedó el trabajo, y a partir de
    # eso escribir o confirmar algo. Sin estas excepciones el canal remoto queda limitado a
    # lo verde y ese flujo es imposible.
    #
    # Se habilitan aquí y NO bajando su nivel a verde, que es la diferencia importante:
    # siguen siendo YELLOW, así que cada una pasa por el adaptador de confirmación
    # conversacional de Telegram y pregunta por el chat antes de actuar. El dueño ve qué se
    # va a escribir y dónde antes de que ocurra, que es justo lo que no puede ver estando
    # lejos del PC.
    #
    # `pc_screenshot` no aparece porque es GREEN: mira, no toca.
    (ChannelType.TELEGRAM, "pc_type"),
    (ChannelType.TELEGRAM, "pc_key"),
    (ChannelType.TELEGRAM, "pc_click"),
}

# REQ-029/CA-06, CA-07 — acciones que NO EXISTEN fuera del escritorio, ni siquiera siendo
# verdes. Es la operación INVERSA de `CHANNEL_ACTION_EXCEPTIONS`: aquella suma (habilita
# una acción amarilla en un canal que no la tendría), esta RESTA y nada más.
#
# Hacía falta porque hasta REQ-029 el nivel de riesgo era la única palanca por canal, y
# no alcanza para las herramientas de archivos. `file_read` es verde con razón —leer
# dentro de una carpeta que el humano ya autorizó no merece una confirmación por archivo—,
# pero verde en este sistema no significa solo "sin preguntar": significa además
# "alcanzable desde Telegram, Discord, voz y API". Un `file_read` verde sin esta tabla
# deja que un mensaje de Telegram —o una inyección en una página leída durante una
# investigación— se lleve cualquier archivo de las carpetas habilitadas. Leer un archivo
# es mandarlo al proveedor del modelo, así que el canal importa tanto como el nivel.
#
# La invariante que la mantiene segura está en `is_action_allowed()`: esta tabla SOLO
# puede devolver False. Nunca habilita nada que `CHANNEL_ALLOWED_LEVELS` negara.
DESKTOP_ONLY_ACTIONS: set[str] = {
    "file_list",
    "file_read",
    "file_search",
    "file_write",
    "file_edit",
    "git_status",
    "git_diff",
    "git_log",
    # REQ-030 — habilitar o quitar una carpeta de trabajo es, literalmente, decidir hasta
    # dónde llegan las 8 de arriba. Tiene que pedirse delante del computador, nunca por un
    # mensaje remoto.
    "workspace_add_folder",
    "workspace_remove_folder",
}

_CHANNEL_STR_MAP: Dict[str, ChannelType] = {
    "desktop": ChannelType.DESKTOP,
    "telegram": ChannelType.TELEGRAM,
    "discord": ChannelType.DISCORD,
    "voice": ChannelType.VOICE,
    "api": ChannelType.API,
    "email": ChannelType.EMAIL,
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
    # Enviar correo es ROJO: el prompt del PIN tiene que decir A QUIÉN y con qué asunto,
    # o autorizarlo sería a ciegas. Van también al log de auditoría, que es justo donde
    # se quiere poder reconstruir después qué se mandó y a dónde.
    "destinatario", "asunto",
    # Un comando que el AGENTE quiere correr en la terminal embebida. Mismo motivo que
    # `destinatario`/`asunto`: el "sí" del modal se da sobre el comando exacto o se está
    # autorizando a ciegas. Va también al log de auditoría, que es donde después se
    # reconstruye qué se ejecutó en la máquina.
    "command",
    # REQ-029/CA-08 — dónde se va a escribir. `path` ya estaba; `ruta` se agrega para que
    # una herramienta futura con el parámetro en español no pierda el detalle en silencio.
    # Autorizar un `file_write` sin ver la ruta sería autorizar a ciegas, exactamente el
    # mismo motivo por el que `command` está en esta lista.
    "ruta",
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


def _load_and_parse_overrides() -> Dict[str, "RiskLevel"]:
    """REQ-019/§1.2 — lee `security_overrides.json` (vía `core.security_config`, import
    perezoso, mismo estilo que `from core.confirmation import get_confirmation_adapter`
    dentro de `require_confirmation()`) y convierte cada valor string a `RiskLevel`.

    Segunda capa de defensa (arquitectura-019.md §11.1, Hallazgo A de
    security-audit-019.md): aunque `core.security_config.load_security_overrides()` ya
    garantiza no propagar excepciones, esta función envuelve la llamada en su propio
    `try/except Exception` — se invoca dentro de `SecurityManager.__new__()`, el punto
    más caro para fallar de todo el sistema (tiempo de import de este módulo), así que se
    protege con una capa independiente por si un REQ futuro reintroduce un hueco en
    `security_config.py`.
    """
    from core.security_config import load_security_overrides

    try:
        raw = load_security_overrides()
    except Exception as e:
        logger.warning(
            f"Fallback de emergencia en _load_and_parse_overrides() "
            f"({type(e).__name__}) — se continúa sin overrides: {e}"
        )
        raw = {}

    result: Dict[str, RiskLevel] = {}
    for name, value in raw.items():
        try:
            result[name] = RiskLevel(value)
        except ValueError:
            logger.warning(f"Nivel inválido en override de '{name}': {value!r} — ignorado")
    return result


class SecurityManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._actions: Dict[str, RiskLevel] = {}        # nivel EFECTIVO (código + override, REQ-019)
            cls._instance._base_levels: Dict[str, RiskLevel] = {}    # REQ-019 — nivel puro de código
            cls._instance._config_overrides: Dict[str, RiskLevel] = _load_and_parse_overrides()  # REQ-019
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

    def log_action(self, action: str, channel, result: str, user_id: str = "default",
                   details: str = "") -> None:
        """Registra en la auditoría un hecho consumado, sin evaluar nada.

        `require_confirmation()` audita lo que ella misma decide. Esto es para las
        superficies que ejecutan DENTRO de una sesión ya autorizada, donde el gate corrió
        una vez y los actos siguientes igual tienen que quedar escritos: hoy, cada comando
        que entra a la terminal embebida (`core/terminal_session.py`), venga del teclado
        del usuario o de la herramienta del agente.

        No decide, no bloquea y no reemplaza al gate: quien la llama ya pasó por él.
        """
        self._log_audit(action, self.resolve_channel(channel), result, user_id, details)

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
        """Registra la clasificación de código de una acción y recalcula su nivel
        efectivo (código + override de config, REQ-019/CA-02/CA-03).

        Rechaza (retorna False) cualquier intento de degradar el nivel BASE de una acción
        ya registrada como RiskLevel.RED a un nivel menor — comportamiento idéntico al de
        REQ-005, ahora aplicado sobre el nivel de código (`_base_levels`), no sobre el
        efectivo. En cualquier otro caso aplica el cambio y retorna True.
        """
        current_base = self._base_levels.get(name)
        if current_base == RiskLevel.RED and level != RiskLevel.RED:
            logger.critical(
                f"Intento de reclasificar acción ROJO '{name}' a '{level.value}' bloqueado"
            )
            self._log_audit(name, ChannelType.UNKNOWN, "reclasificacion_bloqueada", details=f"nivel_solicitado={level.value}")
            return False
        self._base_levels[name] = level
        self._actions[name] = self._merge_with_override(name, level)
        return True

    def _merge_with_override(self, name: str, base_level: RiskLevel) -> RiskLevel:
        """REQ-019/CA-02, CA-03 — nivel efectivo = max(base, override), nunca min.

        Un override de config que intente bajar el nivel de código se ignora EN EFECTO
        (se conserva `base_level`) pero queda auditado (CA-04). No se implementa
        llamando recursivamente a `register_action()` con el nivel de override — eso
        reabriría el bug original (`register_action()` solo protegía RED): acá se compara
        el rank de los 3 niveles de forma simétrica, siempre.
        """
        override = self._config_overrides.get(name)
        if override is None:
            return base_level
        if _RISK_LEVEL_ORDER[override] < _RISK_LEVEL_ORDER[base_level]:
            logger.warning(
                f"Override de config para '{name}' ({override.value}) intenta bajar el nivel "
                f"de código ({base_level.value}) — ignorado, se mantiene {base_level.value}"
            )
            self._log_audit(name, ChannelType.UNKNOWN, "override_bajada_ignorada",
                             details=f"nivel_codigo={base_level.value}, nivel_config_ignorado={override.value}")
            return base_level
        return override

    def classify_action(self, name: str) -> Optional[RiskLevel]:
        return self._actions.get(name)

    def classify_action_base(self, name: str) -> Optional[RiskLevel]:
        """REQ-019 — nivel puro de código, sin overrides aplicados. Permite que la UI de
        Configuración muestre 'nivel base' vs. 'nivel efectivo' cuando hace falta."""
        return self._base_levels.get(name)

    def log_override_attempt(self, name: str, requested_level: RiskLevel,
                              current_level: RiskLevel, accepted: bool) -> None:
        """REQ-019/CA-04, CA-21 — auditoría de un intento de GUARDADO desde el bridge
        (distinto de `_merge_with_override()`, que audita al aplicar overrides ya
        persistidos durante el arranque). Público porque `ui/webview/bridge.py` es quien
        conoce el intento crudo en el momento en que ocurre."""
        result = "override_guardado" if accepted else "override_guardado_rechazado_bajada"
        self._log_audit(name, ChannelType.DESKTOP, result,
                         details=f"nivel_actual={current_level.value}, nivel_solicitado={requested_level.value}")

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
        # REQ-029/CA-06, CA-07 — se evalúa PRIMERO, antes que la excepción quirúrgica de
        # REQ-018 y antes que `CHANNEL_ALLOWED_LEVELS`, y su único resultado posible es
        # `False`: no puede habilitar nada, solo quitar. Ese orden es lo que impide que
        # una entrada en `CHANNEL_ACTION_EXCEPTIONS` reabra por Telegram una herramienta
        # de archivos, y que la propia tabla se use algún día para sumar permisos.
        #
        # La comparación es contra `ChannelType.DESKTOP` exacto, no contra "todo lo que se
        # parezca al escritorio": un canal sin resolver, desconocido o `None` cae del lado
        # restrictivo, que es el mismo criterio fail-closed de `resolve_channel()`.
        if action_name in DESKTOP_ONLY_ACTIONS and channel is not ChannelType.DESKTOP:
            return False
        # REQ-018/CA-02 — excepción quirúrgica evaluada antes que la política general de canal.
        if (channel, action_name) in CHANNEL_ACTION_EXCEPTIONS:
            return True
        allowed = self.get_allowed_levels(channel)
        return level in allowed

    def explain_denial(self, action_name: str, channel) -> str:
        """Return en una frase por qué se denegó una acción, para decírselo al usuario.

        `require_confirmation()` solo devuelve un booleano, así que quien la llama no puede
        distinguir "esto no se puede desde aquí" de "no llegaste a confirmar" — y acaba
        enseñando un "denegado por security_manager" que no le dice nada a nadie. Esto lo
        reconstruye leyendo la misma clasificación, sin ejecutar ni auditar nada: solo se
        invoca después de una denegación, para explicarla.

        No revela más de lo que el usuario ya sabe al ver la denegación: qué acción era y
        por qué no salió. Nunca los parámetros ni el estado interno.
        """
        channel = self.resolve_channel(channel)
        level = self.classify_action(action_name)
        canal = channel.value

        if level is None:
            return f"«{action_name}» no está clasificada, y lo que no está clasificado no se ejecuta."
        # REQ-029/CA-06 — antes que cualquier explicación por nivel: si la acción es de
        # escritorio y el canal no lo es, ese ES el motivo, y decir "ese canal solo lee y
        # resume" (la explicación de EMAIL) sería contar otra cosa.
        if action_name in DESKTOP_ONLY_ACTIONS and channel is not ChannelType.DESKTOP:
            return (
                f"«{action_name}» solo funciona delante del computador: las herramientas "
                f"de archivos y de git no están disponibles desde {canal}."
            )
        if level == RiskLevel.RED:
            return f"«{action_name}» es una acción de riesgo alto y no se ejecuta desde {canal}."
        if level == RiskLevel.YELLOW:
            if not self.is_action_allowed(action_name, channel):
                return (
                    f"«{action_name}» necesita confirmación y no está habilitada desde "
                    f"{canal}."
                )
            from core.confirmation import get_confirmation_adapter

            if get_confirmation_adapter(channel) is None:
                return (
                    f"«{action_name}» necesita confirmación, pero por {canal} no hay forma "
                    f"de pedírtela ahora mismo."
                )
            # Estaba habilitada y había cómo preguntar: o se respondió que no, o se agotó
            # el tiempo de espera sin respuesta.
            return f"no se confirmó «{action_name}»."
        if level == RiskLevel.GREEN and not self.is_action_allowed(action_name, channel):
            # Solo puede pasar en un canal de entrada no confiable (EMAIL), que no ejecuta
            # ninguna acción por inofensiva que sea.
            return (
                f"«{action_name}» no se ejecuta desde {canal}: ese canal solo lee y resume, "
                f"no actúa."
            )
        return f"«{action_name}» no se pudo ejecutar desde {canal}."

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
            # El verde también consulta la política de canal. Hasta acá no hacía falta:
            # TODOS los canales tenían GREEN en `CHANNEL_ALLOWED_LEVELS` (y el default de
            # `get_allowed_levels()` también es GREEN), así que el chequeo habría sido
            # siempre cierto y se omitió. `ChannelType.EMAIL` es el primer canal con lista
            # VACÍA —entrada no confiable, no ejecuta nada— y sin este chequeo su
            # restricción no existiría: las acciones verdes seguirían pasando.
            #
            # Para los canales que ya existían el resultado es idéntico (verde sigue
            # estando en sus listas), así que esto no relaja ni endurece nada previo.
            if not self.is_action_allowed(action_name, channel):
                logger.warning(
                    f"Acción verde '{action_name}' no permitida en canal {channel.value}"
                )
                self._log_audit(action_name, channel, "bloqueada_canal", user_id, details)
                return False
            self._log_audit(action_name, channel, "permitida", user_id, details)
            return True
        if level == RiskLevel.YELLOW:
            if not self.is_action_allowed(action_name, channel):
                logger.warning(f"Acción '{action_name}' no permitida en canal {channel.value}")
                self._log_audit(action_name, channel, "bloqueada_canal", user_id, details)
                return False
            # En español llano, no con el nombre interno de la función. Pedirle permiso a
            # alguien en un idioma que no habla no es pedirle permiso: o dice que sí a
            # ciegas, o dice que no por las dudas. El DETALLE concreto sigue yendo —es lo
            # que liga el permiso a la acción puntual—, solo cambia cómo se nombra.
            from core.acciones_legibles import pregunta as _pregunta_legible

            msg = _pregunta_legible(action_name, details)
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
                from core.acciones_legibles import pregunta as _pregunta_roja

                if self.require_pin(
                    f"⛔ {_pregunta_roja(action_name, details)}\n"
                    f"Es una acción de alto riesgo. Ingrese su PIN maestro para "
                    f"autorizarla: "
                ):
                    self._log_audit(action_name, channel, "autorizada_rojo", user_id, details)
                    logger.info(f"Acción roja '{action_name}' autorizada por PIN maestro")
                    return True
            from core.acciones_legibles import describir as _describir_roja

            msg = (f"⛔ No puedo {_describir_roja(action_name)}: es una acción de alto "
                   f"riesgo y no está autorizada.")
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
    # REQ-015/§10.2 (Hallazgo C de security-audit-015.md): `Bridge.request_delete_conversation()`
    # es un @pyqtSlot invocable desde cualquier script que corra en la página del WebView
    # — a diferencia de REQ-014 (borrado solo alcanzable vía un QPushButton nativo), acá
    # el modal JS ya no es una barrera real. Mismo patrón que delete_file/delete_folder.
    sm.register_action("delete_conversation", RiskLevel.YELLOW)
    # REQ-016/CA-08, CA-18, CA-33 — mismo patrón que delete_conversation: son @pyqtSlot
    # invocables desde cualquier script que corra en la página del WebView, no solo desde
    # el botón visible; se clasifican YELLOW y pasan por el mismo
    # `security_manager.require_confirmation()` antes de ejecutarse.
    sm.register_action("delete_task", RiskLevel.YELLOW)
    sm.register_action("delete_project", RiskLevel.YELLOW)
    # `MemoryDigestSkill` reescribe MEMORY.md, un archivo del proyecto, con contenido que
    # produce el LLM: entra en "modificar archivos existentes" de security-levels.md. Solo
    # toca el bloque entre marcadores y deja copia en MEMORY.md.bak, pero eso acota el daño
    # posible, no elimina la necesidad de confirmar. Como YELLOW no se puede lanzar por voz
    # (CHANNEL_ALLOWED_LEVELS), que es lo deseable: es mantenimiento, no conversación.
    sm.register_action("UPDATE_MEMORY_FILE", RiskLevel.YELLOW)
    sm.register_action("execute_code", RiskLevel.YELLOW)
    # Terminal embebida (`core/terminal_session.py`). Lo que se gatea es ABRIR la sesión,
    # no cada tecla: una terminal que pide confirmación por comando no es una terminal.
    # Amarillo, así que queda fuera de voz y de los canales remotos por
    # CHANNEL_ALLOWED_LEVELS — se abre frente al PC o no se abre. `Bridge.terminal_open()`
    # es un @pyqtSlot alcanzable desde cualquier script de la página (mismo criterio que
    # `delete_conversation`, REQ-015/§10.2), y este es justamente el punto donde eso se
    # detiene: sin confirmación humana no hay shell. Cada línea que después entre a la
    # sesión queda auditada aparte, vía `log_action("terminal_command", ...)`.
    sm.register_action("terminal_open", RiskLevel.YELLOW)
    # REQ-029 — herramientas de repositorio, confinadas a las carpetas que el humano
    # habilita en `code_workspaces.json` (`core/workspace_config.py`). Se registran ACÁ
    # además de en `agents/tool_registry.py`, y a propósito: si un día alguien registrara
    # una de ellas con un nivel distinto, el desacuerdo entre los dos lugares queda fijado
    # por test (`tests/test_workspace_tools_seguridad.py`) en vez de pasar inadvertido.
    #
    # Leer y consultar es verde: el permiso ya se dio al habilitar la carpeta, y pedir
    # confirmación por archivo en un repo de mil archivos no es una decisión, es un
    # obstáculo (mismo criterio que la terminal embebida, `security-levels.md`). Escribir
    # y editar es amarillo: es irreversible y se confirma con la ruta a la vista (CA-08).
    #
    # Que sean verdes NO las hace alcanzables desde Telegram, Discord, voz o API: las 8
    # están en `DESKTOP_ONLY_ACTIONS`, que se evalúa antes que todo lo demás.
    sm.register_action("file_list", RiskLevel.GREEN)
    sm.register_action("file_read", RiskLevel.GREEN)
    sm.register_action("file_search", RiskLevel.GREEN)
    sm.register_action("file_write", RiskLevel.YELLOW)
    sm.register_action("file_edit", RiskLevel.YELLOW)
    sm.register_action("git_status", RiskLevel.GREEN)
    sm.register_action("git_diff", RiskLevel.GREEN)
    sm.register_action("git_log", RiskLevel.GREEN)
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
    # Revisar el correo propio y pedir un resumen es lectura: verde, como `system_info`.
    # Que sea verde NO relaja nada del lado del correo — lo que llega por IMAP entra por
    # `ChannelType.EMAIL`, cuya política sigue vacía. Esto solo habilita que el DUEÑO
    # pregunte "¿tengo correos?" desde escritorio, Telegram o voz.
    sm.register_action("CHECK_EMAIL", RiskLevel.GREEN)
    # Descargar un adjunto SÍ escribe en el disco un archivo que eligió un desconocido:
    # amarillo, con confirmación en cada uso. El nombre del archivo llega al texto de
    # confirmación porque `filename` está en `_DETAILS_ALLOWED_KEYS`, así que el "sí" se da
    # sabiendo qué se guarda. Y no se habilita en ningún canal remoto: se confirma frente
    # al PC (no hay entrada en CHANNEL_ACTION_EXCEPTIONS para esta acción).
    sm.register_action("SAVE_EMAIL_ATTACHMENT", RiskLevel.YELLOW)
    # Marcar como leído modifica la bandeja del usuario: amarillo, confirma cada vez.
    sm.register_action("MARK_EMAIL_READ", RiskLevel.YELLOW)
    # Enviar correo en nombre del usuario es 🔴 ROJO por `.claude/rules/security-levels.md`,
    # y ya está registrado así arriba como `send_email_as_user`. El intent de la skill se
    # registra con el MISMO nivel a propósito: si algún día alguien intentara bajarlo,
    # `register_action()` lo bloquea igual que a cualquier otro rojo. Además hace falta
    # encender la capacidad a mano en la pantalla "Configuración"
    # (`core/email_capabilities.py`) — el nivel de riesgo y el interruptor son cosas
    # distintas y las dos tienen que dar permiso.
    sm.register_action("SEND_EMAIL", RiskLevel.RED)

    # Flujos durables (`core/flows.py`). Ejecutar, listar, retomar y cancelar son VERDES
    # por el mismo motivo que la acción `dispatcher`: el gate real ocurre paso a paso
    # dentro del flujo, en `action_registry.execute_action()`. Un flujo no puede hacer
    # nada que el usuario no pudiera pedir de a un paso.
    # Crear sí es amarillo: deja escrito algo que va a ejecutarse después, quizá sin nadie
    # mirando, así que se confirma en el momento de guardarlo.
    sm.register_action("RUN_FLOW", RiskLevel.GREEN)
    sm.register_action("LIST_FLOWS", RiskLevel.GREEN)
    sm.register_action("RESUME_FLOW", RiskLevel.GREEN)
    sm.register_action("CANCEL_FLOW", RiskLevel.GREEN)
    sm.register_action("CREATE_FLOW", RiskLevel.YELLOW)
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
        "TAKE_SCREENSHOT", "WIKIPEDIA_SUMMARY", "RECALL_MEMORY", "TEACH_COMMAND",
        "SYS_VOL_UP", "SYS_VOL_DOWN", "SYS_MUTE", "AUTOPILOT",
        "CALCULATE", "SEARCH_FILES", "FOLDER_SIZE", "FIND_LARGEST", "SYSTEM_INFO", "CPU_INFO",
        "RAM_INFO", "CHAT", "UNKNOWN", "FILE_ANALYSIS", "PLAY_MUSIC", "ANALYZE_SCREEN",
        "LIST_SKILLS", "GET_WEATHER", "BROWSE_WEB",
    ]
    yellow_intents = [
        "CLOSE_APP", "SYS_POWER_OFF", "EXECUTE_CODE", "CREATE_SKILL", "MODIFY_SKILL",
        "DELETE_SKILL",
        # Entrada sintética de teclado y ratón. Estaban en verde —se ejecutaban sin
        # preguntar— y eso no encaja con lo que de verdad hacen: `PC_TYPE` es un
        # `pyautogui.write()` sobre la ventana que tenga el foco EN ESE MOMENTO, y quien
        # ordena la acción no sabe cuál es. El mismo comando puede rellenar un buscador o
        # escribir dentro de un documento que el usuario estaba editando. `PC_CLICK` y
        # `PC_SCROLL` tienen el mismo problema: actúan sobre lo que haya delante.
        #
        # Al pasar a amarillo quedan además bloqueadas en los canales remotos por
        # CHANNEL_ALLOWED_LEVELS, que es lo prudente para una acción cuyo efecto depende de
        # algo que no se ve desde el otro lado.
        "PC_CLICK", "PC_TYPE", "PC_SCROLL",
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
