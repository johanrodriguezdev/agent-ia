"""
core/resolution.py
Punto único de resolución de O.R.I.O.N. (REQ-006, CA-01, CA-02, CA-03).

Reemplaza los tres motores de resolución divergentes que existían antes de este REQ
(`main.py`, `channels/gateway.py`, `core/orchestrator.py::_try_quick_dispatch`) por una
sola función, `resolve()`, que camina una lista fija de resolvers — mismo orden para
cualquier canal (desktop, voz, Telegram, Discord, API futura).

Todo lo que puede ejecutar algo pasa, en última instancia, por exactamente dos puntos de
gate: `router/dispatcher.py:dispatch()` y `agents/tool_registry.py:execute_tool()`, ambos
llamando a `security_manager.require_confirmation()`. `routine`/`autopilot`/`capability`
ya están gateados por construcción desde REQ-005 (ver `agents/action_registry.py` y
`os_integration/capabilities_router.py`) y no necesitan manejo de `ActionDenied` acá.

`channel` SIEMPRE debe llegar ya resuelto por el caller (nunca se infiere de `params` ni
de texto libre) — mismo invariante documentado en `security_manager.py:214-221`.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from core.security_manager import ActionDenied, ChannelType, security_manager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolutionResult:
    text: str                    # respuesta final para el usuario
    matched_by: str              # "routine" | "autopilot" | "learned" | "capability"
                                  # | "task_tool" | "intent:<NOMBRE>" | "claude"
    channel: "ChannelType"
    denied: bool = False         # True si un resolver intentó y el gate denegó


def _denied_message(exc: ActionDenied) -> str:
    """Mensaje para el usuario sin stacktrace ni rutas de archivo (mismo criterio que B4
    de la referencia OpenClaw citada en arquitectura-006.md)."""
    return f"⛔ Acción '{exc.action_name}' no autorizada."


# ─────────────────────────────────────────────
#  Resolvers — cada uno recibe (text, channel, user_id) y retorna
#  Optional[ResolutionResult]. None significa "no aplica, seguir probando".
# ─────────────────────────────────────────────

def _try_routine(text: str, channel: "ChannelType", user_id: str) -> Optional[ResolutionResult]:
    """`learning/routines_engine.py:try_routine()` — ya gateado por construcción vía
    `agents/action_registry.py:execute_action()` (línea 256, incondicional)."""
    from learning.routines_engine import try_routine

    result = try_routine(text, channel=channel.value)
    if result is None:
        return None
    return ResolutionResult(text=result, matched_by="routine", channel=channel)


_AUTOPILOT_TRIGGERS = ("autopilot", "ejecuta tarea", "crea un", "redacta", "haz un")


def _try_autopilot(text: str, channel: "ChannelType", user_id: str) -> Optional[ResolutionResult]:
    """`agents/task_planner.py` + `agents/task_executor.py` — ya gateado por construcción
    vía `execute_action()` (misma cadena que `routine`)."""
    if not any(t in text.strip().lower() for t in _AUTOPILOT_TRIGGERS):
        return None

    from agents.task_executor import TaskExecutor
    from agents.task_planner import TaskPlanner

    plan = TaskPlanner().generate_plan(text)
    if not plan:
        return None

    summary = TaskExecutor().execute(plan, channel=channel.value)
    return ResolutionResult(text=summary, matched_by="autopilot", channel=channel)


def _try_learned(text: str, channel: "ChannelType", user_id: str) -> Optional[ResolutionResult]:
    """`learning/command_learning.py:run_custom_command()` — mitigación reforzada tras
    Hallazgo 1.7 de orion-security: el callback que ejecuta cada acción aprendida es
    PRIVADO de este módulo, nunca parametrizable desde fuera, y siempre hace
    `classify_command() -> dispatch()` internamente. Así el gate no depende de que un
    caller futuro de `run_custom_command()` sea disciplinado."""
    from learning.command_learning import run_custom_command

    outcome = {"ran_any": False, "denied": False, "chunks": []}

    def _execute_learned_action(action_text: str) -> None:
        from intent.classifier import classify_command
        from router.dispatcher import dispatch

        intent, params = classify_command(action_text)
        params["channel"] = channel.value
        try:
            result = dispatch(intent, params)
            outcome["ran_any"] = True
            outcome["chunks"].append(result)
        except ActionDenied as e:
            outcome["denied"] = True
            outcome["chunks"].append(_denied_message(e))

    matched = run_custom_command(text, _execute_learned_action)
    if not matched:
        return None

    final_text = "\n".join(outcome["chunks"]).strip() or "Rutina completada perfectamente."
    return ResolutionResult(
        text=final_text, matched_by="learned", channel=channel, denied=outcome["denied"],
    )


# Mismos triggers que `channels/gateway.py::_try_create_task/_try_list_tasks/_try_complete_task`
# tenían antes de REQ-006 (H3: se ejecutaban sin gate) — ahora resuelven via `execute_tool()`.
_TASK_CREATE_TRIGGERS = (
    "recuérdame", "recuerdame", "recordarme", "recordatorio",
    "agrega tarea", "agregar tarea", "nueva tarea", "crear tarea",
    "no olvidar", "no olvides", "pendiente:", "tarea:",
)
_TASK_LIST_TRIGGERS = (
    "mis tareas", "tareas pendientes", "tareas programadas", "listado de tareas",
    "lista de tareas", "ver tareas", "qué tareas", "que tareas", "dime mis tareas",
    "cuáles son mis tareas", "cuales son mis tareas",
)
_TASK_COMPLETE_TRIGGERS = (
    "ya complete la tarea", "ya completé la tarea", "tarea terminada", "tarea completada",
    "marcar tarea", "ya termine la tarea", "ya terminé la tarea", "listo complete la tarea",
    "listo termine la tarea",
)


def _is_task_complete_phrase(text_lower: str) -> bool:
    if any(t in text_lower for t in _TASK_COMPLETE_TRIGGERS):
        return True
    mentions_task = "tarea" in text_lower or "recordatorio" in text_lower
    mentions_done = (
        "listo" in text_lower or "hecho" in text_lower
        or "completad" in text_lower or "terminad" in text_lower
    )
    return mentions_task and mentions_done


def _try_task_tool(text: str, channel: "ChannelType", user_id: str) -> Optional[ResolutionResult]:
    """Reemplaza `channels/gateway.py::_try_create_task/_try_list_tasks/_try_complete_task`
    (H3: antes llamaban a `tasks/task_manager.py` directo, sin gate). Ahora resuelve
    siempre vía `agents/tool_registry.py:execute_tool()` — segundo (y único otro) punto
    de gate del sistema. `user_id` viene del `resolve()` que recibió este resolver como
    argumento, nunca del texto libre (Observación B de orion-security)."""
    from agents.tool_registry import execute_tool

    text_lower = text.lower().strip()
    try:
        if any(t in text_lower for t in _TASK_CREATE_TRIGGERS):
            result = execute_tool(
                "task_create", {"text": text, "user_id": user_id, "channel": channel.value},
                channel, user_id,
            )
            return ResolutionResult(text=result, matched_by="task_tool", channel=channel)

        if any(t in text_lower for t in _TASK_LIST_TRIGGERS):
            result = execute_tool("task_list", {"user_id": user_id}, channel, user_id)
            return ResolutionResult(text=result, matched_by="task_tool", channel=channel)

        if _is_task_complete_phrase(text_lower):
            result = execute_tool(
                "task_complete", {"text": text, "user_id": user_id}, channel, user_id,
            )
            return ResolutionResult(text=result, matched_by="task_tool", channel=channel)
    except ActionDenied as e:
        return ResolutionResult(
            text=_denied_message(e), matched_by="task_tool", channel=channel, denied=True,
        )

    return None


def _try_capability(text: str, channel: "ChannelType", user_id: str) -> Optional[ResolutionResult]:
    """`os_integration/capabilities_router.py:try_capability()` — ya gatea directo dentro
    de `execute_capability()` (línea 59), sin levantar `ActionDenied` (retorna el string de
    denegación, sin cambios funcionales en este REQ)."""
    from os_integration.capabilities_router import try_capability

    result = try_capability(text, channel=channel.value)
    if result is None:
        return None
    return ResolutionResult(text=result, matched_by="capability", channel=channel)


def _try_intent(text: str, channel: "ChannelType", user_id: str) -> Optional[ResolutionResult]:
    """`intent/classifier.py:classify_command()` + `router/dispatcher.py:dispatch()` —
    único punto de ejecución de intents legacy y skills modernas. `channel` se reasigna de
    forma incondicional a `params["channel"]` DESPUÉS de clasificar, para que un intento de
    inyección de canal vía texto libre (`extract_params()`) nunca llegue al gate."""
    from intent.classifier import classify_command
    from intent.intentions import Intent

    intent, params = classify_command(text)
    if intent == Intent.UNKNOWN:
        return None

    # `classify_command()` puede devolver un `str` plano en vez de un miembro de `Intent`
    # (ver `intent/ai_classifier.py::predict()` -> `return str(prediction)`); mismo patrón
    # defensivo que ya usa `router/dispatcher.py:dispatch()`.
    intent_name = intent.value if hasattr(intent, "value") else str(intent)

    params["channel"] = channel.value
    from router.dispatcher import dispatch

    try:
        result = dispatch(intent, params)
        return ResolutionResult(text=result, matched_by=f"intent:{intent_name}", channel=channel)
    except ActionDenied as e:
        return ResolutionResult(
            text=_denied_message(e), matched_by=f"intent:{intent_name}", channel=channel,
            denied=True,
        )


def _try_claude(
    text: str, channel: "ChannelType", user_id: str,
    claude_fn: Optional[Callable[[str], str]] = None,
) -> ResolutionResult:
    """Último recurso — siempre responde algo, nunca retorna `None`.

    `claude_fn`, si se pasa, reemplaza la llamada plana a `ai/claude_brain.ask_claude()`.
    Existe para que `channels/gateway.py` pueda seguir usando su
    `_ask_claude_for_user()` (historial de sesión por usuario, soporte de imágenes) sin
    que `resolution.py` tenga que conocer `GlassMessage`/sesiones de usuario — el ORDEN de
    resolución (CA-03) es idéntico en los tres canales, solo el detalle de implementación
    de este último paso puede variar por canal, igual que ya variaba antes de este REQ.
    """
    if claude_fn is not None:
        result = claude_fn(text)
        return ResolutionResult(text=result, matched_by="claude", channel=channel)

    from core.reasoning_loop import run as reasoning_run

    result = reasoning_run(text, channel, user_id)
    return ResolutionResult(text=result, matched_by="claude", channel=channel)


RESOLVERS = [
    ("routine", _try_routine),
    ("autopilot", _try_autopilot),
    ("learned", _try_learned),
    ("task_tool", _try_task_tool),
    ("capability", _try_capability),
    ("intent", _try_intent),
    ("claude", _try_claude),
]


def resolve(
    text: str, channel, user_id: str = "default",
    claude_fn: Optional[Callable[[str], str]] = None,
) -> ResolutionResult:
    """Punto único de resolución de O.R.I.O.N. (CA-01).

    Camina `RESOLVERS` en orden fijo y se detiene en el primero que retorna un resultado
    no-`None`. `claude` es el último recurso y siempre retorna algo, así que `resolve()`
    siempre termina con un `ResolutionResult`.

    `channel` puede venir como `ChannelType` o como `str` — se resuelve una sola vez acá
    con `security_manager.resolve_channel()`, la única función de resolución de canal del
    sistema (REQ-005), y viaja ya resuelto a cada resolver. Nunca se infiere de `params`
    ni de texto libre (mismo invariante de `security_manager.py:214-221`).
    """
    resolved_channel = security_manager.resolve_channel(channel)
    logger.info(f"resolve() canal={resolved_channel.value} user={user_id}: {text[:80]}")

    for name, fn in RESOLVERS:
        try:
            if name == "claude":
                result = fn(text, resolved_channel, user_id, claude_fn=claude_fn)
            else:
                result = fn(text, resolved_channel, user_id)
        except ActionDenied as e:
            # Red de seguridad adicional: cada resolver ya captura su propio
            # ActionDenied, pero si alguno se agrega en el futuro sin hacerlo, esto
            # evita que la excepción se escape sin formatear hasta el caller.
            logger.warning(f"ActionDenied no capturado por el resolver '{name}': {e}")
            return ResolutionResult(
                text=_denied_message(e), matched_by=name, channel=resolved_channel, denied=True,
            )

        if result is not None:
            logger.info(f"resolve() resuelto por '{result.matched_by}'")
            return result

    # Inalcanzable en la práctica: "claude" siempre retorna un ResolutionResult.
    return ResolutionResult(
        text=f"No pude procesar: '{text[:60]}'.", matched_by="none", channel=resolved_channel,
    )
