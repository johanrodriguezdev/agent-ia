"""
core/resolution.py
Punto único de resolución de O.R.I.O.N. (REQ-006, CA-01, CA-02, CA-03).

Reemplaza los tres motores de resolución divergentes que existían antes de este REQ
(`main.py`, `channels/gateway.py`, `core/orchestrator.py::_try_quick_dispatch`) por una
sola función, `resolve()`, que camina una lista fija de resolvers — mismo orden para
cualquier canal (desktop, voz, Telegram, Discord, API futura).

Esa lista es hoy `[pending_dialog, claude]`: el modelo lee primero y decide él qué
herramienta usar. Antes había siete heurísticas por delante y cualquiera podía quedarse con
el mensaje sin que el modelo llegara a verlo — ver el comentario de `RESOLVERS` para el
caso que lo decidió y para dónde quedó cada una de las siete.

Todo lo que puede ejecutar algo pasa, en última instancia, por exactamente dos puntos de
gate: `router/dispatcher.py:dispatch()` y `agents/tool_registry.py:execute_tool()`, ambos
llamando a `security_manager.require_confirmation()`. `routine`/`autopilot`/`capability`
ya están gateados por construcción desde REQ-005 (ver `agents/action_registry.py` y
`os_integration/capabilities_router.py`) y no necesitan manejo de `ActionDenied` acá.

`channel` SIEMPRE debe llegar ya resuelto por el caller (nunca se infiere de `params` ni
de texto libre) — mismo invariante documentado en `security_manager.py:214-221`.
"""

import logging
import re
from dataclasses import dataclass, replace
from typing import Callable, Optional

from core.address import vocative
from core.cancelacion import abortar_si_cancelado
from core.dialog_state import PendingDialog, dialog_store
from core.progress import report as progress_report
from core.security_manager import ActionDenied, ChannelType, security_manager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolutionResult:
    text: str                    # respuesta final para el usuario
    matched_by: str              # "pending_dialog" | "pending_dialog:cancel" | "claude"
                                  # Tras la inversión solo quedan esos: lo que antes
                                  # llegaba como "intent:<X>" o "task_tool" ahora llega
                                  # como "claude", porque lo resolvió el modelo llamando
                                  # a la herramienta correspondiente.
    channel: "ChannelType"
    denied: bool = False         # True si un resolver intentó y el gate denegó
    expects_reply: bool = False  # REQ-021: quedó una pregunta en el aire

    # REQ-021/CA-10: `expects_reply` se agrega ÚLTIMO y con default, así los 4 consumidores
    # de `resolve()` (main.py, channels/gateway.py, core/orchestrator.py,
    # ui/webview/bridge.py) siguen funcionando sin leerlo. Y al ser `frozen`, ningún
    # resolver muta un resultado: se construye uno nuevo. El único `dataclasses.replace()`
    # de todo el REQ está en `_append_pending_question()`.


def _denied_message(exc: ActionDenied) -> str:
    """Mensaje para el usuario sin stacktrace ni rutas de archivo (mismo criterio que B4
    de la referencia OpenClaw citada en arquitectura-006.md)."""
    return f"⛔ Acción '{exc.action_name}' no autorizada."


# ─────────────────────────────────────────────
#  Resolvers — cada uno recibe (text, channel, user_id) y retorna
#  Optional[ResolutionResult]. None significa "no aplica, seguir probando".
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
#  REQ-021 — diálogo pendiente (resolver en posición 0 de RESOLVERS)
#
#  Con un diálogo abierto, la frase entrante se lee como la RESPUESTA al dato que faltaba,
#  no como un comando nuevo. Con el estado vacío retorna `None` en su primera línea, así
#  que en un turno normal no cuesta nada.
#
#  Es el ÚNICO resolver que quedó delante del modelo tras la inversión, y no por
#  rendimiento: cuando el agente acaba de preguntar "¿a quién le envío el correo?", la
#  respuesta "a Juan" es el dato que falta, no un mensaje nuevo. Mandarla al modelo
#  rompería todos los diálogos de varios turnos.
# ─────────────────────────────────────────────

_MATCHED_BY_DIALOG = "pending_dialog"
_MATCHED_BY_DIALOG_CANCEL = "pending_dialog:cancel"
_MATCHED_BY_DIALOG_OPEN = "task_tool:dialog_open"
_MATCHED_BY_STANDING_INTENT = "standing_intent"

#: Cancelación explícita (CA-06). Se exige coincidencia EXACTA de la frase normalizada:
#: "cancela la reunión del lunes" es contenido de un slot, no una cancelación.
_CANCEL_PHRASES = frozenset({
    "olvídalo", "olvidalo", "olvídate", "olvidate", "olvida", "olvidalo ya",
    "cancela", "cancelar", "cancélalo", "cancelalo",
    "déjalo", "dejalo", "déjalo así", "dejalo asi",
    "nada", "no importa", "ya no", "nada más", "nada mas",
})

#: Señal fuerte de que la frase no responde al slot "qué", sino que cambia de tema
#: (CA-30). El caso borde literal de la SPEC es "qué hora es" con el "qué" pendiente.
_QUESTION_STARTERS = (
    "qué ", "que ", "cuál", "cual ", "cómo ", "como ", "cuándo", "cuando ",
    "dónde", "donde ", "quién", "quien ", "por qué", "por que", "para qué",
    "para que", "cuánto", "cuanto ",
)

_PHRASE_EDGE_PUNCT = " \t\r\n.,;:!¡?¿\"'"

_DIALOG_CLOSING = "¿Algo más?"


def _normalize_phrase(text: str) -> str:
    return text.strip().strip(_PHRASE_EDGE_PUNCT).lower().strip()


def _is_cancel_phrase(text: str) -> bool:
    return _normalize_phrase(text) in _CANCEL_PHRASES


def _is_question_phrase(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith("¿") or stripped.endswith("?"):
        return True
    return any(f"{_normalize_phrase(stripped)} ".startswith(q) for q in _QUESTION_STARTERS)


def _answers_slot(slot: str, text: str) -> bool:
    """Return True si `text` puede leerse como la respuesta a `slot`.

    Asimétrico A PROPÓSITO, y esa asimetría es la que decide qué gana entre CA-18 y CA-30
    (ver hallazgo H1 de `propuestas/security-audit-021.md`):

    - `cuando`: hay un parser duro (`_parse_natural_date`), así que se puede exigir match
      positivo. Una frase que no parsea como fecha se desvía al camino normal — donde el
      gate `require_confirmation()` se evalúa con el canal real, exactamente igual que si
      no hubiera ningún diálogo abierto.
    - `que`: es texto libre, así que solo se puede rechazar ante una señal fuerte (forma
      interrogativa). Una frase no interrogativa se guarda como título y NO se ejecuta:
      *fail-safe* deliberado, no defecto.
    """
    from tasks.task_manager import _parse_natural_date
    from tasks.task_slots import SLOT_WHAT, SLOT_WHEN, has_content_tokens

    if slot == SLOT_WHEN:
        return _parse_natural_date(text) is not None
    if slot == SLOT_WHAT:
        if _is_question_phrase(text):
            return False
        return has_content_tokens(text)
    logger.warning(f"[Diálogo] slot desconocido '{slot}': la frase se resuelve como comando nuevo")
    return False


def _try_pending_dialog(
    text: str, channel: "ChannelType", user_id: str,
) -> Optional[ResolutionResult]:
    """Lee la frase entrante como respuesta al dato que faltaba (CA-04, CA-05, CA-06).

    INVARIANTE DE SEGURIDAD: la acción que se ejecuta al completar el diálogo es siempre
    `dialog.action`, fijada al abrirlo — nunca una derivada del contenido de un slot
    (CA-19). Y se ejecuta por el mismo `execute_tool()` de siempre, con el `channel` que
    recibió este resolver, así que el gate no se mueve ni se salta (CA-17).
    """
    dialog = dialog_store.get(user_id, channel)      # purga los expirados (CA-07)
    if dialog is None:
        return None                                   # camino de coste ~0 (CA-09)

    stripped = text.strip()
    if not stripped:
        return None          # STT vacío: no cuenta como turno, ni avanza ni cierra nada

    if _is_cancel_phrase(stripped):                   # CA-06
        dialog_store.cancel(user_id, channel)
        logger.info(f"[Diálogo] cancelado por el usuario user={user_id}")
        return ResolutionResult(
            text=f"De acuerdo{vocative()}, lo descarto.",
            matched_by=_MATCHED_BY_DIALOG_CANCEL, channel=channel,
        )

    slot = dialog.next_slot
    if slot is None:
        # Defensivo: un diálogo sin slots pendientes no debería existir (se cierra al
        # completarse). Se descarta en vez de dejarlo trabado.
        dialog_store.cancel(user_id, channel)
        return None

    if not _answers_slot(slot, stripped):             # CA-30: desvío de tema
        return None                                   # el diálogo sigue VIVO

    updated = dialog_store.fill(user_id, channel, slot, stripped)   # mueve el reloj (CA-32)
    if updated is None:                               # expiró entre el get y el fill
        return None

    if updated.missing:
        from core.dialog_questions import ask_question

        question = ask_question(updated.action, updated.missing[0], updated.slots)
        dialog_store.touch_question(user_id, channel, question)
        return ResolutionResult(
            text=question, matched_by=_MATCHED_BY_DIALOG, channel=channel,
            expects_reply=True,
        )

    return _execute_completed_dialog(updated, channel, user_id)


def _execute_completed_dialog(
    dialog: PendingDialog, channel: "ChannelType", user_id: str,
) -> Optional[ResolutionResult]:
    """Ejecuta la acción del diálogo ya completo, por el camino de ejecución de siempre."""
    from agents.tool_registry import execute_tool
    from tasks.task_slots import TASK_CREATE_ACTION, compose_task_sentence

    if dialog.action != TASK_CREATE_ACTION:
        # v1 solo cablea `task_create` (SPEC-021, alcance). Cualquier otra acción sería
        # un diálogo que nadie sabe ejecutar: se descarta en vez de improvisar.
        logger.warning(f"[Diálogo] acción '{dialog.action}' no cableada en v1; se descarta")
        dialog_store.cancel(user_id, channel)
        return None

    composed = compose_task_sentence(dialog.slots)
    try:
        result = execute_tool(
            dialog.action,
            {"text": composed, "user_id": user_id, "channel": channel.value},
            channel, user_id,
        )
    except ActionDenied as e:
        dialog_store.cancel(user_id, channel)
        return ResolutionResult(
            text=_denied_message(e), matched_by=_MATCHED_BY_DIALOG, channel=channel,
            denied=True,
        )

    dialog_store.cancel(user_id, channel)             # completado -> cerrado
    return ResolutionResult(
        text=f"{result}\n\n{_DIALOG_CLOSING}", matched_by=_MATCHED_BY_DIALOG, channel=channel,
    )



def _append_standing_intents(
    result: ResolutionResult, text: str, user_id: str,
) -> ResolutionResult:
    """Cuelga a la respuesta los recordatorios que la frase del usuario haya disparado.

    Se comprueba sobre lo que dijo el USUARIO, no sobre la respuesta del agente: una
    intención tiene que dispararse cuando *tú* mencionas el tema, no cuando el agente lo
    menciona al responderte —eso haría que se disparase a sí misma.

    Igual que la repregunta pendiente, no se pega a un resultado denegado: mezclar un aviso
    de seguridad con un recordatorio conversacional degrada el aviso.
    """
    if result.denied or not text.strip():
        return result

    # La frase que CREA una intención contiene, por fuerza, el tema que la dispara: sin
    # esta salida, pedir "cuando hable del contador recuérdame X" respondía confirmando la
    # anotación y, acto seguido, recordándola. Absurdo, y además gastaba un disparo.
    if result.matched_by == _MATCHED_BY_STANDING_INTENT:
        return result

    try:
        from core.standing_intents import formatear_aviso, standing_intents

        disparadas = standing_intents.comprobar(text, user_id)
    except Exception as e:
        # Un recordatorio que falla no puede impedir que llegue la respuesta.
        logger.warning(f"Fallo comprobando intenciones permanentes: {e}")
        return result

    if not disparadas:
        return result

    logger.info(f"[Intenciones] {len(disparadas)} disparada(s) por la frase del usuario")
    return replace(result, text=f"{result.text}\n\n{formatear_aviso(disparadas)}")

def _append_pending_question(
    result: ResolutionResult, user_id: str, channel: "ChannelType",
) -> ResolutionResult:
    """CA-31 — cuelga la pregunta pendiente a la respuesta de un desvío de tema.

    Así la pregunta pendiente es siempre lo último que se preguntó, y la frase siguiente se
    lee sin ambigüedad como su respuesta. Determinista, sin LLM: reusa la pregunta que ya
    se redactó. NO mueve `last_progress_at` — un desvío no compra tiempo (CA-32).

    NO se pega a un resultado denegado (hallazgo H2 de la auditoría de seguridad): mezclar
    "⛔ Acción no autorizada" con "Por cierto, ¿para cuándo?" degrada el aviso de seguridad
    y lo convierte en parte de una charla. El diálogo NO se cancela por eso — la repregunta
    simplemente reaparece en el turno siguiente.
    """
    if result.denied:
        return result
    if result.matched_by.startswith(_MATCHED_BY_DIALOG) \
            or result.matched_by == _MATCHED_BY_DIALOG_OPEN:
        return result

    dialog = dialog_store.get(user_id, channel)
    if dialog is None or not dialog.question:
        return result

    # El turno que ABRE el diálogo ya no se distingue por su etiqueta: desde que el modelo
    # lee primero, la pregunta puede venir de `task_create` llamada por él, y el resultado
    # sale etiquetado "claude" como cualquier otro. Sin este chequeo la pregunta se colgaba
    # de sí misma — "¿Qué desea que le recuerde? / Por cierto, ¿qué desea que le
    # recuerde?". Se mira el TEXTO, que es lo que de verdad separa "esta respuesta ES la
    # pregunta" de "esta respuesta es otra cosa y la pregunta sigue viva".
    if dialog.question.strip() and dialog.question.strip() in result.text:
        return replace(result, expects_reply=True)

    return replace(
        result,
        text=f"{result.text}\n\nPor cierto, {_as_inline_question(dialog.question)}",
        expects_reply=True,
    )


def _as_inline_question(question: str) -> str:
    """Return la pregunta lista para ir después de "Por cierto, " (minúscula inicial)."""
    if question.startswith("¿") and len(question) > 1:
        return "¿" + question[1].lower() + question[2:]
    return question[:1].lower() + question[1:] if question else question


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


# REQ-017 (CA-01/CA-02): palabras clave de alcance "todas" — amplias pero determinísticas,
# sin LLM. AJUSTE respecto al ASUMIDO original de SPEC-017.md (que decía "todas/todos/todo"):
# Johan pidió sacar "todo" (singular) del set — es la palabra de mayor riesgo de falso
# positivo (aparece en frases sin relación a tareas, ej. "todo bien", "eso es todo"), y los
# 3 ejemplos literales de la SPEC ("completa todas...", "ya completé todas...", "termina
# todas mis tareas") ya matchean con "todas" solo. Ver arquitectura-017.md, "Ajustes de
# Johan", punto 2.
_TASK_BULK_ALL_RE = re.compile(r"\b(?:todas|todos)\b")

# Verbos de "completar" en cualquier conjugación común (imperativo/presente/pretérito/
# participio): completa/completé/completo/completando/completado -> "complet";
# termina/terminé/terminado -> "termin"; marca/marcar/marqué -> "marc". Mismo criterio que
# sugiere SPEC-017.md en "Casos borde" ("la presencia de un verbo de completar — 'completa',
# 'termina', 'marca', 'ya completé' — antes de evaluar el trigger de listado puro").
_TASK_BULK_COMPLETE_VERB_STEMS = ("complet", "termin", "marc")


def _is_bulk_complete_phrase(text_lower: str) -> bool:
    """Detecta intención de completar TODAS las tareas pendientes (CA-01, CA-02).

    Requiere un verbo de completar Y la palabra todas/todos — cualquiera de las dos
    condiciones sola es demasiado ambigua (un verbo de completar solo no implica lote;
    "todas"/"todos" solas pueden aparecer en frases sin relación con tareas). Debe
    evaluarse antes de `_TASK_LIST_TRIGGERS` en `_try_task_tool()` (hallazgo de
    orion-baseline: la mayoría de las frases reales de "completar todas" contienen
    substrings de `_TASK_LIST_TRIGGERS` como "tareas pendientes"/"mis tareas" y hoy se
    resuelven como listado antes de llegar a evaluar completar)."""
    if not _TASK_BULK_ALL_RE.search(text_lower):
        return False
    return any(stem in text_lower for stem in _TASK_BULK_COMPLETE_VERB_STEMS)


def _try_task_tool(text: str, channel: "ChannelType", user_id: str) -> Optional[ResolutionResult]:
    """Reemplaza `channels/gateway.py::_try_create_task/_try_list_tasks/_try_complete_task`
    (H3: antes llamaban a `tasks/task_manager.py` directo, sin gate). Ahora resuelve
    siempre vía `agents/tool_registry.py:execute_tool()` — segundo (y único otro) punto
    de gate del sistema. `user_id` viene del `resolve()` que recibió este resolver como
    argumento, nunca del texto libre (Observación B de orion-security)."""
    from agents.tool_registry import execute_tool, has_explicit_task_id

    text_lower = text.lower().strip()
    try:
        if any(t in text_lower for t in _TASK_CREATE_TRIGGERS):
            # REQ-021/CA-01: antes se disparaba `task_create` a ciegas y `parse_natural_task`
            # inventaba el dato que faltara (título "Algo", recordatorio a 1 hora). Ahora se
            # revisa primero qué falta y, si falta algo, se PREGUNTA.
            #
            # `scan_task_slots()` corre fuera del gate a propósito: es una función pura (ni
            # ejecuta, ni persiste, ni consulta red), así que el gate sigue exactamente donde
            # estaba, dentro de `execute_tool()`.
            # El chequeo de slots se mudo DENTRO de `task_create` (REQ-021/CA-01 vive
            # ahora en `agents/tool_registry.py::_task_create_invoke`), para que valga
            # tambien cuando quien llama es el modelo y no este resolver.
            from tasks.task_slots import scan_task_slots

            faltaba = bool(scan_task_slots(text).missing)
            result = execute_tool(
                "task_create", {"text": text, "user_id": user_id, "channel": channel.value},
                channel, user_id,
            )
            if faltaba:
                return ResolutionResult(
                    text=result, matched_by=_MATCHED_BY_DIALOG_OPEN, channel=channel,
                    expects_reply=True,
                )
            return ResolutionResult(text=result, matched_by="task_tool", channel=channel)

        # REQ-017 (CA-01, CA-02, CA-05, CA-06 desambiguación) — evaluado ANTES de
        # _TASK_LIST_TRIGGERS, hallazgo crítico de orion-baseline.
        bulk_all = _is_bulk_complete_phrase(text_lower)
        list_trigger = any(t in text_lower for t in _TASK_LIST_TRIGGERS)

        if bulk_all or list_trigger:
            # CA-05/CA-06: un ID explícito en el texto gana siempre sobre "todas" y sobre
            # "listar" — se resuelve como completar UNA tarea (comportamiento existente de
            # _task_complete_invoke, sin cambios en su rama de ID explícito).
            if has_explicit_task_id(text):
                result = execute_tool(
                    "task_complete", {"text": text, "user_id": user_id}, channel, user_id,
                )
                return ResolutionResult(text=result, matched_by="task_tool", channel=channel)

            if bulk_all:
                result = execute_tool(
                    "task_complete_all", {"text": text, "user_id": user_id}, channel, user_id,
                )
                return ResolutionResult(text=result, matched_by="task_tool", channel=channel)

            # Solo list_trigger, sin "todas" y sin ID explícito -> comportamiento sin cambios.
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


# ─────────────────────────────────────────────
#  Intenciones permanentes — "cuando vuelva a hablar de X, recuérdame Y"
#
#  Va ANTES de `_try_task_tool` a propósito. Estas frases contienen "recuérdame", que es
#  disparador de `task_create`, así que sin este resolver la petición se leía como un
#  recordatorio por reloj y el agente preguntaba "¿para cuándo?" — justo el dato que esta
#  clase de recordatorio no tiene, porque no depende del reloj sino de la ocasión.
# ─────────────────────────────────────────────

#: Grupo 1 = la condición ("vuelva a hablar del contador"), grupo 2 = qué recordar.
#: Se exige la estructura completa —condición temporal + verbo de recordar— para no capturar
#: un "recuérdame llamar al contador mañana", que sí es por reloj y debe seguir su camino.
_STANDING_INTENT_RE = re.compile(
    r"\b(?:cuando|cuándo|la\s+pr[oó]xima\s+vez\s+que|cada\s+vez\s+que|si\s+(?:vuelvo|vuelva|menciono|hablo))"
    r"(?P<condicion>.{3,90}?)"
    r"\b(?:recu[eé]rdame|recordarme|acu[eé]rdame|av[ií]same|no\s+me\s+dejes\s+olvidar)\b"
    r"(?P<accion>.{3,160})",
    re.IGNORECASE | re.DOTALL,
)


def _try_standing_intent(
    text: str, channel: "ChannelType", user_id: str,
) -> Optional[ResolutionResult]:
    """Crea un recordatorio condicionado a que vuelva a aparecer un tema."""
    match = _STANDING_INTENT_RE.search(text)
    if match is None:
        return None

    from core.standing_intents import extraer_triggers, standing_intents

    condicion = match.group("condicion").strip()
    accion = match.group("accion").strip(" .,;:")
    if not accion:
        return None

    triggers = extraer_triggers(condicion)
    if not triggers:
        # La condición no tiene ninguna palabra específica ("cuando quieras", "cuando
        # puedas"). No hay forma de reconocer el momento, así que se deja seguir: el resto
        # de resolvers lo tratarán como lo que parezca.
        logger.info(f"[Intención] sin disparadores utilizables en: '{condicion[:40]}'")
        return None

    intent = standing_intents.crear(user_id, accion, triggers)
    if intent is None:
        return None

    temas = ", ".join(f"«{t}»" for t in intent.triggers)
    return ResolutionResult(
        text=(
            f"Anotado{vocative()}. Se lo recordaré la próxima vez que hablemos de "
            f"{temas}: {intent.descripcion}"
        ),
        matched_by=_MATCHED_BY_STANDING_INTENT,
        channel=channel,
    )


def _try_capability(text: str, channel: "ChannelType", user_id: str) -> Optional[ResolutionResult]:
    """`os_integration/capabilities_router.py:try_capability()` — ya gatea directo dentro
    de `execute_capability()` (línea 59), sin levantar `ActionDenied` (retorna el string de
    denegación, sin cambios funcionales en este REQ)."""
    from os_integration.capabilities_router import try_capability

    result = try_capability(text, channel=channel.value)
    if result is None:
        return None
    return ResolutionResult(text=result, matched_by="capability", channel=channel)



# Intents que YA NO se ejecutan directamente: ceden el turno al LLM, que decide con qué
# herramienta responder (`wikipedia_search`, `web_search`, `web_read`) o si le basta con lo
# que ya sabe.
#
# El motivo, con el caso que lo destapó: "que es un bot" se clasificaba como
# WIKIPEDIA_SUMMARY con un margen de 1.35 —alta confianza, no es un fallo del clasificador—
# y se respondía con el resumen de Wikipedia sin que el modelo llegara a verlo nunca. Para
# el usuario eso se siente como un agente que "solo sabe buscar en Wikipedia", porque
# literalmente es lo único que ese camino puede hacer.
#
# Ceder no es perder la capacidad: Wikipedia sigue disponible como herramienta, y ahora
# convive con la búsqueda web. Lo que cambia es quién decide.
#
# Coste consciente: estas frases pasan a costar una llamada al LLM. Solo se ceden intents
# de CONSULTA DE CONOCIMIENTO, nunca los de acción — abrir una aplicación o apagar el PC
# siguen resolviéndose en local, sin coste y sin latencia.
#
# SEARCH_WEB entra por el mismo motivo, y con un agravante: su handler es
# `os_integration/browser.py::search_google()`, que se limita a ABRIR el navegador y
# responder "Búsqueda lanzada". Nunca lee los resultados. Pedirle "busca en internet la
# última versión de Python" abría una pestaña en vez de contestar. Ahora que existe la
# herramienta `web_search`, que busca y lee de verdad, el atajo es peor que el camino largo.
_INTENTS_QUE_CEDEN_AL_LLM = frozenset({"WIKIPEDIA_SUMMARY", "SEARCH_WEB"})

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

    intent_name_raw = intent.value if hasattr(intent, "value") else str(intent)
    if intent_name_raw in _INTENTS_QUE_CEDEN_AL_LLM:
        logger.info(
            f"Intent '{intent_name_raw}' cede al LLM: es una consulta de conocimiento, "
            f"no una acción"
        )
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
    from ai.llm_provider import es_respuesta_de_fallo

    if claude_fn is not None:
        result = claude_fn(text)
        if es_respuesta_de_fallo(result):
            local = _resolver_sin_modelo(text, channel, user_id)
            if local is not None:
                return local
        return ResolutionResult(text=result, matched_by="claude", channel=channel)

    from core.reasoning_loop import run as reasoning_run

    estado: dict = {}
    result = reasoning_run(text, channel, user_id, estado=estado)

    if estado.get("sin_modelo"):
        local = _resolver_sin_modelo(text, channel, user_id)
        if local is not None:
            return local

    return ResolutionResult(
        text=result, matched_by="claude", channel=channel,
        denied=bool(estado.get("denied")),
    )


#: Lo que se antepone a una respuesta resuelta en local por falta de modelo. Corto a
#: proposito: por voz se escucha entero, y lo importante es que el usuario sepa POR QUE la
#: respuesta es mas seca de lo habitual, no recibir una disculpa larga.
_AVISO_SIN_MODELO = "Sin conexión con el modelo, pero esto sí puedo hacerlo."


def _resolver_sin_modelo(
    text: str, channel: "ChannelType", user_id: str,
) -> Optional[ResolutionResult]:
    """Intenta resolver en LOCAL cuando no se pudo hablar con ningun proveedor.

    Recorre los resolvers retirados en su orden de siempre. No reintroduce el problema que
    la inversion vino a resolver, y la diferencia es toda de ORDEN: estas heuristicas ya no
    pueden quedarse con un mensaje que el modelo habria contestado, porque solo corren
    cuando el modelo NO contesto. Lo que antes era un filtro delante, ahora es una red
    debajo.

    Sin esto, quedarse sin internet dejaba al agente sin poder ni subir el volumen — una
    orden que sabe ejecutar sola, sin consultarle nada a nadie. Contestar "no consigo
    comunicarme con ningun proveedor" a "sube el volumen" es peor que intentarlo.

    Return `None` si ninguno reconoce la frase: ahi la respuesta honesta es el fallo del
    proveedor, no una accion inventada.
    """
    for nombre, fn in RESOLVERS_RETIRADOS:
        abortar_si_cancelado(f"resolve sin modelo, antes de '{nombre}'")
        try:
            resultado = fn(text, channel, user_id)
        except ActionDenied as e:
            return ResolutionResult(
                text=_denied_message(e), matched_by=f"{nombre}:sin_modelo",
                channel=channel, denied=True,
            )
        except Exception as e:
            # Un resolver roto no puede tumbar el turno: ya se venia de un fallo.
            logger.warning(f"el resolver '{nombre}' falló en el camino sin modelo: {e}")
            continue

        if resultado is not None:
            logger.info(f"sin modelo: '{nombre}' resolvió el turno en local")
            return replace(
                resultado,
                text=f"{_AVISO_SIN_MODELO}\n\n{resultado.text}",
                matched_by=f"{resultado.matched_by}:sin_modelo",
            )
    return None


#: El modelo lee PRIMERO. Antes de él solo queda el diálogo pendiente.
#:
#: Hasta ahora había siete heurísticas por delante, y cada una podía quedarse con el
#: mensaje sin que el modelo llegara a verlo nunca. El caso que lo decidió: un JSON de
#: rangos de colores para ciclos de cosecha, pidiendo mejorar la paleta, se contestó con
#: "0 x 12 = 0" — `classify_command()` lo leyó como CALCULATE y un extractor tomó los dos
#: primeros números que encontró. No era un fallo del modelo: el modelo nunca vio el
#: mensaje.
#:
#: Se midió con 20 pedidos de análisis reales (mejorar un JSON, resumir una reunión,
#: comparar alternativas, revisar código). Antes de invertir, 5 de los 20 se resolvían sin
#: llegar al modelo, y el peor no era el clasificador sino `_try_autopilot`, que disparaba
#: por subcadena — "redacta", "crea un", "haz un"— sin ninguna medida de confianza:
#: "haz un resumen de esta reunión" se iba al planificador de tareas.
#:
#: Ninguna capacidad se pierde, porque ninguna de las siete se borró: todas siguen
#: alcanzables como herramientas, y ahora es el modelo el que elige cuál usar.
#:
#:     routine        -> `routine_run` / `routine_list`      (agents/user_defined_tools.py)
#:     autopilot      -> `autopilot_run`                     (idem)
#:     learned        -> `learned_command_run` / `_list`     (idem)
#:     capability     -> `capability_run`, solo si hay capacidades declaradas (idem)
#:     standing_intent-> `intent_create` / `intent_list` / `intent_cancel`
#:     task_tool      -> `task_create` / `task_list` / `task_complete`
#:     intent         -> `dispatcher`, y además un tool por cada intent de cada skill
#:
#: Además, `core/reasoning_loop.py::_bloque_de_lo_definido_por_el_usuario()` le nombra al
#: modelo las rutinas y los comandos aprendidos que existan, para que "modo trabajo" se
#: resuelva en la primera llamada y no gaste una vuelta en descubrirlos.
#:
#: COSTE, asumido a conciencia: una orden simple ("sube el volumen") pasa de resolverse en
#: local en milisegundos a costar una llamada al modelo, y sin conexión el agente deja de
#: poder ejecutarla. Se eligió igual, en todos los canales: una heurística que responde
#: rápido lo que no le preguntaron es peor que una respuesta que tarda un segundo.
#:
#: `pending_dialog` es la ÚNICA excepción, y no por rendimiento: cuando el agente acaba de
#: preguntar "¿a quién le envío el correo?", la respuesta "a Juan" es el dato que falta, no
#: un mensaje nuevo. Mandarla al modelo rompería todos los diálogos de varios turnos. Con
#: el estado de diálogo vacío retorna `None` en su primera línea, así que en un turno
#: normal no cuesta nada.
RESOLVERS = [
    ("pending_dialog", _try_pending_dialog),
    ("claude", _try_claude),
]

#: Los resolvers que dejaron de estar en el camino automático. No se borran: siguen siendo
#: el cuerpo de las herramientas de arriba, y `tests/test_resolution.py` verifica que cada
#: uno tenga su tool, para que nadie los pierda de vista.
RESOLVERS_RETIRADOS = [
    ("routine", _try_routine),
    ("autopilot", _try_autopilot),
    ("learned", _try_learned),
    ("standing_intent", _try_standing_intent),
    ("task_tool", _try_task_tool),
    ("capability", _try_capability),
    ("intent", _try_intent),
]


def _marcar_si_quedo_pregunta(
    result: ResolutionResult, user_id: str, channel: "ChannelType",
) -> ResolutionResult:
    """Marca `expects_reply` si el turno dejo un dialogo abierto.

    Antes lo ponia el resolver que abria el dialogo, porque era el mismo que respondia.
    Ahora el dialogo lo puede abrir la herramienta `task_create` desde dentro del bucle del
    modelo, varias vueltas antes de la respuesta final: quien contesta ya no es quien
    pregunto. Sin esto, la voz cerraria el microfono justo despues de preguntar "para
    cuando?" y el usuario hablaria solo.
    """
    if result.expects_reply or result.denied:
        return result
    try:
        from core.dialog_state import dialog_store

        if dialog_store.get(user_id, channel) is None:
            return result
    except Exception as e:
        logger.debug(f"No se pudo consultar el dialogo pendiente: {e}")
        return result
    return replace(result, expects_reply=True)


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
    progress_report("Entendiendo lo que me pides")

    for name, fn in RESOLVERS:
        # Punto de corte del boton de detener: entre un resolver y el siguiente. Cada
        # resolver es indivisible (puede haber ejecutado una accion ya confirmada), asi
        # que cortar aca es lo mas fino que se puede sin dejar nada a medio hacer.
        abortar_si_cancelado(f"resolve, antes de '{name}'")
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
            # REQ-021/CA-31: si el turno fue un desvío de tema y quedó un diálogo abierto,
            # la respuesta lleva colgada la pregunta pendiente. Vive acá y no dentro de un
            # resolver porque el desvío lo puede resolver cualquiera de los 7.
            result = _append_pending_question(result, user_id, resolved_channel)
            # Y por el mismo motivo, acá: una intención permanente puede dispararse diga lo
            # que diga el usuario, así que el sitio es después de resolver, no dentro de un
            # resolver concreto. Va DESPUÉS de la repregunta para que el recordatorio quede
            # al final, que es donde se lee.
            result = _append_standing_intents(result, text, user_id)
            result = _marcar_si_quedo_pregunta(result, user_id, resolved_channel)
            logger.info(f"resolve() resuelto por '{result.matched_by}'")
            return result

    # Inalcanzable en la práctica: "claude" siempre retorna un ResolutionResult.
    return ResolutionResult(
        text=f"No pude procesar: '{text[:60]}'.", matched_by="none", channel=resolved_channel,
    )
