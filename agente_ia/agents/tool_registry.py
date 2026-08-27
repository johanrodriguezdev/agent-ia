"""
agents/tool_registry.py
Registro de tools con contrato isomorfo a MCP (REQ-006, CA-14 a CA-17).

`ToolSpec` es la unidad de tool tanto para herramientas locales (task_manager, etc.)
como para tools remotos declarados a futuro (`origin="mcp_remote"`, CA-16 — sin cliente
real todavía). `execute_tool()` es, junto a `router/dispatcher.py:dispatch()`, uno de
los DOS únicos puntos de gate del sistema: nunca se debe invocar `ToolSpec.invoke`
directo sin pasar antes por acá.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from core.security_manager import ActionDenied, RiskLevel, format_details, security_manager
from core.address import vocative, vocative_start

logger = logging.getLogger(__name__)

# REQ-017 — Reconoce "tarea 3"/"tarea #3"/"numero 3"/"id 3" (comportamiento existente,
# grupo 1) y también un "#3" suelto sin palabra clave delante (grupo 2) — necesario para
# que la desambiguación ID-vs-todas (CA-05, CA-06) funcione con frases como "de todas mis
# tareas, la #3 ya la hice", donde el número no está precedido por tarea/numero/id.
_TASK_ID_RE = re.compile(r"(?:tarea|numero|número|id)\s*#?(\d+)|#(\d+)")


def has_explicit_task_id(text: str) -> bool:
    """Detecta si el texto menciona un ID de tarea explícito (mismo criterio que usa
    _task_complete_invoke() para extraerlo). Expuesta para que core/resolution.py decida
    prioridad "ID explícito gana sobre todas/listar" (SPEC-017 CA-05, CA-06) sin duplicar
    el regex en dos módulos."""
    return bool(_TASK_ID_RE.search(text.lower()))


@dataclass(frozen=True)
class ToolSpec:
    """Contrato de tool isomorfo a un tool de MCP.

    - `name`: también es la `action_name` usada por `security_manager` — un solo
      namespace de clasificación de riesgo para todo el sistema.
    - `parameters_schema`: JSON Schema de los parámetros (misma forma que `inputSchema`
      de MCP), para que un futuro loop de razonamiento (REQ-007) o un discovery remoto
      (SIGAIND) puedan describir el tool sin código adicional.
    - `risk_level`: DECLARADO por quien registra el tool. Nunca es autoritativo por sí
      mismo (CA-15) — `register_tool()` lo pasa a `security_manager.register_action()`,
      que es quien de verdad decide, y `execute_tool()` sigue llamando siempre a
      `security_manager.require_confirmation()`. Al ser un campo sin default de un
      dataclass, un `ToolSpec` sin `risk_level` no compila: fail-closed por diseño, no
      por chequeo en runtime.
    - `origin`: "local" (default) o "mcp_remote" (CA-16). No implica ningún cliente MCP
      real en este REQ; solo documenta que el tool podría, en el futuro, resolverse vía
      discovery remoto en vez de estar cableado en este módulo.
    """

    name: str
    description: str
    parameters_schema: dict
    risk_level: RiskLevel
    invoke: Callable[[dict], str]
    origin: str = "local"


_REGISTRY: Dict[str, ToolSpec] = {}


def register_tool(spec: ToolSpec) -> None:
    """Registra el tool y, en el mismo paso, su nivel de riesgo declarado en
    `security_manager`. Si el registro no llegara a correr por algún motivo, el
    fail-closed de `security_manager.classify_action()` (REQ-005) sigue bloqueando
    cualquier intento de invocar el tool — este registro es una capa adicional, no la
    única defensa."""
    security_manager.register_action(spec.name, spec.risk_level)
    _REGISTRY[spec.name] = spec
    logger.info(f"Tool registrado: '{spec.name}' (origin={spec.origin}, risk={spec.risk_level.value})")


def get_tool(name: str) -> Optional[ToolSpec]:
    return _REGISTRY.get(name)


def list_tool_names() -> list[str]:
    return list(_REGISTRY.keys())


def execute_tool(name: str, params: dict, channel, user_id: str = "default") -> str:
    """Segundo (y único otro, junto a `dispatch()`) punto de gate del sistema.

    Levanta `ActionDenied` si el tool no está registrado o si `security_manager`
    deniega — nunca invoca `spec.invoke()` sin haber pasado antes por el gate.
    """
    spec = _REGISTRY.get(name)
    if spec is None:
        raise ActionDenied(name, channel, "tool no registrado")
    if not security_manager.require_confirmation(
        spec.name, channel, details=format_details(f"tool:{spec.name}", params), user_id=user_id
    ):
        raise ActionDenied(spec.name, channel, "denegado por security_manager")

    # Se anuncia DESPUÉS del gate: si la acción se va a denegar, no tiene sentido decir que
    # se está haciendo. Este es el punto por el que pasan todas las herramientas, así que
    # instrumentarlo aquí evita repartir avisos por cada `invoke`.
    _report_tool_progress(spec.name, params)

    return spec.invoke(params)


#: De qué parámetro sacar el detalle que acompaña al aviso, por herramienta. Solo se leen
#: campos que el usuario ya escribió o dictó: nunca rutas internas, identificadores ni nada
#: que no tenga sentido para quien mira la pantalla.
_PARAM_DE_DETALLE = {
    "web_search": "query",
    "web_read": "url",
    "wikipedia_search": "query",
    "task_create": "text",
}


def _report_tool_progress(nombre: str, params: dict) -> None:
    """Cuenta a la interfaz qué herramienta se va a usar. Nunca interrumpe la ejecución."""
    try:
        from core.progress import report_tool

        clave = _PARAM_DE_DETALLE.get(nombre)
        detalle = str(params.get(clave) or "") if clave else ""
        report_tool(nombre, detalle)
    except Exception as e:
        logger.debug(f"No se pudo reportar el progreso de '{nombre}': {e}")


# ─────────────────────────────────────────────
#  Wrappers de tasks/task_manager.py (REQ-006 — H3: antes se invocaba sin gate desde
#  channels/gateway.py::_try_create_task/_try_list_tasks/_try_complete_task)
# ─────────────────────────────────────────────

def _task_create_invoke(params: dict) -> str:
    from tasks.task_manager import task_manager

    result = task_manager.create_from_natural(
        params["text"], params["user_id"], params.get("channel", "telegram")
    )
    if result:
        return task_manager.format_task_created(result)
    return f"No pude interpretar esa tarea{vocative()}."


def _task_list_invoke(params: dict) -> str:
    from tasks.task_manager import task_manager

    return task_manager.get_task_summary(params["user_id"])


def _task_complete_invoke(params: dict) -> str:
    """Misma lógica que `channels/gateway.py::_try_complete_task` tenía antes de
    REQ-006 (detección de ID explícito, auto-completar si solo hay una pendiente, o
    pedir aclaración si hay varias), ahora detrás del gate."""
    from tasks.task_manager import task_manager

    text = params.get("text", "")
    user_id = params["user_id"]
    text_lower = text.lower()

    match = _TASK_ID_RE.search(text_lower)
    task_id = int(match.group(1) or match.group(2)) if match else None

    if task_id is not None:
        success = task_manager.complete_task(task_id, user_id)
        if success:
            return f"☑️ *Excelente{vocative()}.* He marcado la tarea #{task_id} como completada."
        return f"No encontré ninguna tarea pendiente con el ID #{task_id}{vocative()}."

    pending_tasks = task_manager.list_tasks(user_id, status="pending")

    if not pending_tasks:
        return f"No tiene ninguna tarea pendiente en este momento{vocative()}."

    if len(pending_tasks) == 1:
        task = pending_tasks[0]
        task_manager.complete_task(task["id"], user_id)
        return (
            f"☑️ *¡Trabajo terminado!* He deducido que se refería a la tarea "
            f"*'{task['title']}'* y la he marcado como completada."
        )

    resp = (
        f"He notado que tiene varias tareas pendientes{vocative()}. ¿Podría indicarme el "
        "número de la tarea que completó? (Ej: 'listo tarea 2')\n\nSus tareas pendientes:\n"
    )
    for t in pending_tasks:
        resp += f"• #{t['id']} - {t['title']}\n"
    return resp


register_tool(ToolSpec(
    name="task_create",
    description="Crea una tarea o recordatorio a partir de una frase en lenguaje natural.",
    parameters_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "user_id": {"type": "string"},
            "channel": {"type": "string"},
        },
        "required": ["text", "user_id"],
    },
    # GREEN: preserva el comportamiento actual (sin gate visible al usuario en los 4
    # canales de Telegram) pero ahora pasa por el gate y queda auditado — clasificarlo
    # YELLOW bloquearía la creación de tareas por Telegram, cambio de comportamiento no
    # pedido por la SPEC. Ver arquitectura-006.md, sección "Por qué GREEN y no YELLOW".
    risk_level=RiskLevel.GREEN,
    invoke=_task_create_invoke,
))

register_tool(ToolSpec(
    name="task_list",
    description="Lista las tareas pendientes y completadas del usuario.",
    parameters_schema={
        "type": "object",
        "properties": {"user_id": {"type": "string"}},
        "required": ["user_id"],
    },
    risk_level=RiskLevel.GREEN,
    invoke=_task_list_invoke,
))

register_tool(ToolSpec(
    name="task_complete",
    description="Marca una tarea como completada, por ID explícito o por deducción si solo hay una pendiente.",
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}, "user_id": {"type": "string"}},
        "required": ["user_id"],
    },
    risk_level=RiskLevel.GREEN,
    invoke=_task_complete_invoke,
))


# REQ-017 — alineado con el default de list_tasks() (SPEC-017.md, "Casos borde").
_TASK_COMPLETE_ALL_LIMIT = 20


def _task_complete_all_invoke(params: dict) -> str:
    """Completa todas las tareas pendientes del usuario en una sola invocación (CA-01, CA-02).

    Cada llamada a task_manager.complete_task() ocurre DENTRO de este invoke, que solo se
    ejecuta después de que execute_tool() ya corrió security_manager.require_confirmation()
    para la acción 'task_complete_all' — mismo patrón que ya usa _task_complete_invoke() para
    su rama de auto-completar la única tarea pendiente (CA-07, ver arquitectura-017.md §6).
    """
    from tasks.task_manager import task_manager

    user_id = params["user_id"]
    pending_tasks = task_manager.list_tasks(user_id, status="pending", limit=_TASK_COMPLETE_ALL_LIMIT)

    if not pending_tasks:
        return f"No tiene ninguna tarea pendiente en este momento{vocative()}."

    completed = [t for t in pending_tasks if task_manager.complete_task(t["id"], user_id)]

    if not completed:
        return f"No pude completar ninguna tarea{vocative()}. Intente nuevamente."

    n = len(completed)
    lines = "\n".join(f"• #{t['id']} - {t['title']}" for t in completed)
    header = f"☑️ *¡Trabajo terminado!* Completé {n} tarea{'s' if n != 1 else ''}{vocative()}:\n"

    footer = ""
    if len(pending_tasks) >= _TASK_COMPLETE_ALL_LIMIT:
        footer = (
            f"\n\n(Procesé el máximo de {_TASK_COMPLETE_ALL_LIMIT} tareas por vez. Si tiene "
            f"más pendientes, puede pedírmelo de nuevo.)"
        )
    return header + lines + footer


register_tool(ToolSpec(
    name="task_complete_all",
    description="Completa todas las tareas pendientes del usuario en un solo lote.",
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}, "user_id": {"type": "string"}},
        "required": ["user_id"],
    },
    # GREEN: misma clasificación que task_complete — SPEC-017.md es NO NEGOCIABLE en que
    # completar (individual o en lote) sigue sin pedir confirmación (decisión de UX de Johan).
    risk_level=RiskLevel.GREEN,
    invoke=_task_complete_all_invoke,
))


# ─────────────────────────────────────────────
#  Acceso a internet — el agente pasa de "solo Wikipedia" a poder consultar y leer la web
# ─────────────────────────────────────────────

def _web_search_invoke(params: dict) -> str:
    from os_integration.web_search import MAX_RESULTADOS, buscar, formatear_resultados

    consulta = (params.get("query") or params.get("text") or "").strip()
    if not consulta:
        return "Necesito saber qué buscar."

    try:
        maximo = int(params.get("max_results") or MAX_RESULTADOS)
    except (TypeError, ValueError):
        maximo = MAX_RESULTADOS

    return formatear_resultados(buscar(consulta, maximo), consulta)


def _web_read_invoke(params: dict) -> str:
    from os_integration.web_search import leer_pagina

    url = (params.get("url") or "").strip()
    if not url:
        return "Necesito la dirección de la página que quieres que lea."
    return leer_pagina(url)


register_tool(ToolSpec(
    name="web_search",
    description=(
        "Busca información actualizada en internet y devuelve los resultados con su fuente. "
        "Úsala cuando la pregunta requiera datos que no conoces, información posterior a tu "
        "entrenamiento, o cuando necesites verificar algo. Devuelve títulos, extractos y "
        "enlaces; si necesitas el contenido completo de uno, usa 'web_read' con su enlace."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Qué buscar, en lenguaje natural."},
            "max_results": {"type": "integer", "description": "Cuántos resultados (1-10)."},
        },
        "required": ["query"],
    },
    # GREEN: leer información pública es lo mismo que buscar en Wikipedia, que ya lo es
    # (`.claude/rules/security-levels.md`, "Buscar en Wikipedia o web"). No escribe nada,
    # no toca el sistema y no envía datos del usuario más allá de la propia consulta.
    risk_level=RiskLevel.GREEN,
    invoke=_web_search_invoke,
))

register_tool(ToolSpec(
    name="web_read",
    description=(
        "Abre una página web y devuelve su texto para poder leerla. Úsala después de "
        "'web_search' cuando un resultado prometa la respuesta y necesites el detalle."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Dirección http(s) de la página."},
        },
        "required": ["url"],
    },
    risk_level=RiskLevel.GREEN,
    invoke=_web_read_invoke,
))


def _wikipedia_invoke(params: dict) -> str:
    """Wikipedia como herramienta, no como destino.

    Antes, `WIKIPEDIA_SUMMARY` era un intent: cualquier pregunta que se le pareciera se
    resolvía ahí y nunca llegaba al modelo. Ahora es una opción más que el modelo elige
    cuando le conviene, junto a `web_search` y a su propio conocimiento.
    """
    from os_integration import wiki_api

    consulta = (params.get("query") or params.get("text") or "").strip()
    if not consulta:
        return "Necesito saber sobre qué buscar en Wikipedia."
    try:
        return wiki_api.get_wikipedia_summary(consulta)
    except Exception as e:
        logger.warning(f"Wikipedia falló para '{consulta[:50]}': {e}")
        return f"No pude consultar Wikipedia sobre «{consulta}»."


register_tool(ToolSpec(
    name="wikipedia_search",
    description=(
        "Consulta el resumen de Wikipedia sobre un tema. Útil para conceptos establecidos, "
        "historia, ciencia y biografías. Para información reciente o que cambia, usa "
        "'web_search' en su lugar."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Tema a consultar."},
        },
        "required": ["query"],
    },
    risk_level=RiskLevel.GREEN,
    invoke=_wikipedia_invoke,
))
