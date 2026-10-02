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
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from core.security_manager import (ActionDenied, CHANNEL_ACTION_EXCEPTIONS, ChannelType,
                                   DESKTOP_ONLY_ACTIONS, RiskLevel, format_details,
                                   security_manager)
from core.address import vocative, vocative_start
from core.errores import explicar

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


def catalogo_para_modelo(channel=None) -> list:
    """Return lo que se le OFRECE al modelo: {name, description, parameters_schema}.

    Un solo sitio decide qué ve el modelo, porque hay dos motores que se lo muestran
    —`core/reasoning_loop.py` (escritorio y voz) y `ai/claude_brain.py` (Telegram y
    Discord)— y cada uno armaba su lista por su cuenta. El resultado era que la reduccion
    del catalogo aplicaba en un canal y no en el otro: por Telegram seguian apareciendo las
    herramientas agrupadas y las amarillas que ese canal nunca puede ejecutar.

    Se omiten dos cosas, y ninguna es un control de seguridad —el gate real vive en
    `execute_tool()`, que es el que manda—:

    - Lo que el canal no podria ejecutar. Ofrecerle a Telegram `terminal_run_command` solo
      le hace gastar una vuelta en pedir algo que le van a denegar.
    - Lo que ya cubre una herramienta agrupada (`agents/skill_tools.py::INTENTS_OCULTOS`),
      que sigue registrado y ejecutandose igual.
    """
    permitidos = None
    if channel is not None:
        try:
            permitidos = set(security_manager.get_allowed_levels(channel))
        except Exception as e:
            # Sin poder resolver los niveles se ofrece todo, como antes: el gate sigue ahi.
            logger.debug(f"No se pudieron leer los niveles de {channel}: {e}")

    try:
        from agents.skill_tools import INTENTS_OCULTOS

        ocultos = frozenset(INTENTS_OCULTOS)
    except Exception as e:
        logger.debug(f"No se pudo leer la lista de intents ocultos: {e}")
        ocultos = frozenset()

    # REQ-029 — las herramientas de repositorio son de escritorio y punto (CA-06). Fuera
    # de ahí ni se ofrecen: son verdes, así que el filtro por nivel de arriba no las
    # sacaría, y el modelo gastaría una vuelta pidiendo algo que `execute_tool()` va a
    # denegar. Esto NO es el control de seguridad —ese es `DESKTOP_ONLY_ACTIONS` dentro
    # de `is_action_allowed()`—, es no ofrecer lo que no se puede dar.
    solo_escritorio = frozenset()
    if channel is not None and security_manager.resolve_channel(channel) is not ChannelType.DESKTOP:
        solo_escritorio = frozenset(DESKTOP_ONLY_ACTIONS)

    # REQ-049 — lo que el canal tiene habilitado por excepción (REQ-018) también se ofrece:
    # una herramienta MCP amarilla habilitada para Telegram o para correo no está en los
    # niveles del canal y, sin esto, el modelo nunca la veía ahí aunque el gate la dejara
    # pasar. Sigue sin ser un control de seguridad: el gate es `execute_tool()`.
    canal_resuelto = security_manager.resolve_channel(channel) if channel is not None else None
    excepciones = {
        accion for canal_exc, accion in CHANNEL_ACTION_EXCEPTIONS if canal_exc is canal_resuelto
    } if canal_resuelto is not None else set()

    catalogo = []
    for name in list_tool_names():
        spec = get_tool(name)
        if spec is None or name in ocultos:
            continue
        if name in solo_escritorio:
            continue
        if permitidos is not None and spec.risk_level not in permitidos and name not in excepciones:
            continue
        catalogo.append({
            "name": spec.name,
            "description": spec.description,
            "parameters_schema": spec.parameters_schema,
        })
    return catalogo


def register_tool(spec: ToolSpec) -> bool:
    """Registra el tool y, en el mismo paso, su nivel de riesgo en `security_manager`.

    Return True si quedó registrado. Los tools LOCALES siempre lo quedan (comportamiento
    de siempre; los callers existentes ignoran el retorno y no cambian). Un tool con
    `origin` distinto de "local" pasa antes por `_admitir_tool_remoto()` y puede rechazarse.

    Si el registro no llegara a correr por algún motivo, el fail-closed de
    `security_manager.classify_action()` (REQ-005) sigue bloqueando cualquier intento de
    invocar el tool — este registro es una capa adicional, no la única defensa.
    """
    nivel = spec.risk_level
    if spec.origin != "local":
        admitido, nivel = _admitir_tool_remoto(spec)
        if not admitido:
            return False

    security_manager.register_action(spec.name, nivel)
    _REGISTRY[spec.name] = spec
    logger.info(f"Tool registrado: '{spec.name}' (origin={spec.origin}, risk={nivel.value})")
    return True


def _admitir_tool_remoto(spec: ToolSpec) -> tuple:
    """Decide si un tool que no es local entra, y con qué nivel. Return `(admitido, nivel)`.

    Tres controles, en orden, todos fail-closed:

    1. **Nombre calificado.** Tiene que ser `mcp__<servidor>__<tool>`. El nombre del tool
       ES la `action_name` de `security_manager`: sin namespace, un servidor remoto que
       publique `task_create` se registraría encima del local y heredaría su clasificación.
    2. **Allow-list.** El usuario tiene que haber nombrado ese tool de ese servidor en
       `mcp_allowlist.json`. Lo que no está nombrado no entra.
    3. **Nivel de riesgo.** El nivel que DECLARA el servidor nunca puede dejarlo en verde:
       un tercero no decide qué es inofensivo en esta máquina. Verde sube a amarillo (pide
       confirmación); rojo se respeta como rojo. Es el mismo principio de REQ-019 —
       `max(nuestro, ajeno)`, nunca `min`.
    """
    from core.remote_tools_policy import is_tool_allowed, parse_nombre_calificado

    partes = parse_nombre_calificado(spec.name)
    if partes is None:
        logger.error(
            f"Tool remoto '{spec.name}' rechazado: debe llamarse 'mcp__<servidor>__<tool>'. "
            f"Sin namespace podría pisar la clasificación de un tool local."
        )
        return False, spec.risk_level

    servidor, tool = partes
    if not is_tool_allowed(servidor, tool):
        logger.warning(
            f"Tool remoto '{tool}' del servidor '{servidor}' rechazado: no está en "
            f"mcp_allowlist.json. Agregalo ahí si de verdad lo querés habilitar."
        )
        return False, spec.risk_level

    nivel = RiskLevel.YELLOW if spec.risk_level == RiskLevel.GREEN else spec.risk_level
    if nivel != spec.risk_level:
        logger.info(
            f"Tool remoto '{spec.name}' se declaró '{spec.risk_level.value}'; se registra "
            f"como '{nivel.value}': el riesgo de un tool remoto no lo decide el servidor."
        )
    return True, nivel


def unregister_tool(name: str) -> bool:
    """Saca un tool del registro. Return True si estaba. Pensado para la recarga de MCP.

    NO se borra su clasificación de riesgo en `security_manager`, y es deliberado: si el
    mismo nombre vuelve a registrarse más adelante con un nivel más bajo, conservar el
    anterior hace que `register_action()` siga bloqueando la degradación de un ROJO. Un
    tool ausente de `_REGISTRY` ya no se puede ejecutar —`execute_tool()` lo deniega por
    "no registrado"—, así que la clasificación huérfana no habilita nada.
    """
    return _REGISTRY.pop(name, None) is not None


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
        # El motivo se pregunta aparte porque `require_confirmation()` solo devuelve un
        # booleano. Sin esto el usuario recibe "denegado por security_manager", que no
        # distingue "no se puede desde Telegram" de "no llegaste a responder" y no le deja
        # ninguna pista de qué hacer a continuación.
        raise ActionDenied(
            spec.name, channel, security_manager.explain_denial(spec.name, channel)
        )

    # Se anuncia DESPUÉS del gate: si la acción se va a denegar, no tiene sentido decir que
    # se está haciendo. Este es el punto por el que pasan todas las herramientas, así que
    # instrumentarlo aquí evita repartir avisos por cada `invoke`.
    _report_tool_progress(spec.name, params)

    # Quién ejecuta y por dónde lo pone el gate, no el llamador de turno. Son los mismos
    # valores que ya usó `require_confirmation()` arriba, así que una herramienta no puede
    # actuar como un usuario distinto del que acaba de autorizarla.
    #
    # Cierra un agujero real: cinco herramientas (`task_create`, `task_list`,
    # `task_complete`, `task_complete_all`, `intent_list`) leen `params["user_id"]` con
    # corchetes y reventaban con KeyError si el llamador se olvidaba de ponerlo. Hoy lo
    # pone el bucle de razonamiento en cada llamada, pero era una convención sostenida en
    # un solo sitio: cualquier camino nuevo hacia `execute_tool()` heredaba el traceback.
    #
    # **Solo a los tools locales.** Los de origen remoto reciben sus parámetros TAL CUAL:
    # ahí `params` no es un diccionario interno, es la carga que sale por la red hacia un
    # servidor de terceros. Meterle quién es el usuario —que puede ser su correo o su id de
    # Telegram— sería mandar a un tercero un dato que nunca pidió y que su esquema no
    # declara. Lo detectó `test_tool_origen_remoto_mismo_contrato` al cambiar esto.
    parametros = params
    if spec.origin == "local":
        parametros = dict(params)
        parametros["user_id"] = user_id
        parametros["channel"] = getattr(channel, "value", channel)

    return spec.invoke(parametros)


#: De qué parámetro sacar el detalle que acompaña al aviso, por herramienta. Solo se leen
#: campos que el usuario ya escribió o dictó: nunca rutas internas, identificadores ni nada
#: que no tenga sentido para quien mira la pantalla.
_PARAM_DE_DETALLE = {
    "web_search": "query",
    "web_read": "url",
    "wikipedia_search": "query",
    "task_create": "text",
    "terminal_run_command": "command",
    # REQ-029 — qué archivo o qué carpeta se está tocando. Es lo que el usuario necesita
    # ver pasar por pantalla mientras el agente trabaja sobre un repo.
    "file_list": "path",
    "file_read": "path",
    "image_look": "path",   # REQ-062
    "file_search": "query",
    "file_write": "path",
    "file_edit": "path",
    "git_status": "path",
    "git_diff": "path",
    "git_log": "path",
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

def _cerrar_dialogo_de_tarea(params: dict) -> None:
    """Cierra la pregunta pendiente de `task_create`, si quedaba alguna abierta.

    Nunca lanza: la tarea ya se va a crear, y no poder cerrar una pregunta no puede impedirlo.
    """
    try:
        from core import dialog_state
        from core.security_manager import security_manager as _sm

        canal = _sm.resolve_channel(params.get("channel"))
        almacen = dialog_state.dialog_store
        if almacen.get(params.get("user_id", "default"), canal) is not None:
            almacen.cancel(params.get("user_id", "default"), canal)
            logger.info("dialogo de task_create cerrado: la tarea quedo creada")
    except Exception as e:
        logger.debug(f"no se pudo cerrar el dialogo de task_create: {e}")


def _task_create_invoke(params: dict) -> str:
    """Crea una tarea, o PREGUNTA si falta un dato en vez de inventarlo (REQ-021/CA-01).

    El chequeo de slots vivia en `core/resolution.py::_try_task_tool()`, o sea en UN caller.
    Mientras ese resolver era el unico camino a `task_create` alcanzaba; desde que el modelo
    lee primero y llama las herramientas el, dejo de alcanzar: el modelo entraba por aca
    directo y `create_from_natural()` volvia a inventar lo que faltara (titulo "Algo",
    recordatorio a una hora). La guarda pertenece a la accion, no a uno de sus llamadores.

    `scan_task_slots()` corre antes del gate y no lo mueve: es una funcion pura —ni ejecuta,
    ni persiste, ni consulta red—, y para cuando esto se ejecuta `execute_tool()` ya
    confirmo la accion.
    """
    from tasks.task_manager import task_manager
    from tasks.task_slots import scan_task_slots

    texto = params.get("text", "")
    scan = scan_task_slots(texto)
    if scan.missing:
        from core import dialog_state
        from core.dialog_questions import ask_question
        from core.security_manager import security_manager as _sm

        # Por atributo del modulo, no `from ... import dialog_store`: asi apunta siempre al
        # almacen vigente. Con el import directo, esta herramienta se quedaba con la
        # referencia del arranque mientras el resto del sistema usaba otra.
        dialog_store = dialog_state.dialog_store

        pregunta = ask_question("task_create", scan.missing[0], scan.filled)
        # El dialogo queda abierto con el canal y el usuario REALES de la invocacion, nunca
        # con lo que venga en el texto (mismo invariante que el resto del sistema).
        dialog_store.open(
            params["user_id"], _sm.resolve_channel(params.get("channel")),
            action="task_create", slots=scan.filled, missing=scan.missing,
            question=pregunta,
        )
        return pregunta

    # Si habia una pregunta abierta por esta misma accion, ya no tiene sentido: la tarea
    # quedo creada. Sin esto seguia viva y `_append_pending_question()` la colgaba de cada
    # respuesta posterior — "tarea registrada... por cierto, para cuando?" por algo que
    # acababa de quedar agendado. Pasa cuando el modelo llama dos veces: la primera con la
    # frase incompleta (que abre el dialogo) y la segunda ya completa.
    _cerrar_dialogo_de_tarea(params)

    result = task_manager.create_from_natural(
        texto, params["user_id"], params.get("channel", "telegram")
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


# ─────────────────────────────────────────────
#  Intenciones permanentes — recordatorios que se disparan por lo que dices, no por reloj
# ─────────────────────────────────────────────

def _intent_create_invoke(params: dict) -> str:
    from core.standing_intents import extraer_triggers, standing_intents

    descripcion = (params.get("descripcion") or params.get("text") or "").strip()
    if not descripcion:
        return "Necesito saber qué quiere que le recuerde."

    # Los disparadores pueden venir del modelo o deducirse del tema. Que el modelo los
    # proponga suele dar mejor resultado: sabe cuál es el sustantivo importante de la frase.
    crudos = params.get("disparadores") or params.get("triggers") or ""
    if isinstance(crudos, str):
        crudos = [t.strip() for t in crudos.replace(",", " ").split() if t.strip()]
    triggers = extraer_triggers(" ".join(crudos)) if crudos else ()
    if not triggers:
        triggers = extraer_triggers(params.get("tema") or descripcion)

    if not triggers:
        return (
            "No encontré ninguna palabra lo bastante específica para reconocer el momento. "
            "¿Sobre qué tema quiere que se lo recuerde?"
        )

    intent = standing_intents.crear(params["user_id"], descripcion, triggers)
    if intent is None:
        return f"No pude registrar ese recordatorio{vocative()}."

    lista = ", ".join(f"«{t}»" for t in intent.triggers)
    return (
        f"Anotado{vocative()}. Se lo recordaré la próxima vez que hablemos de {lista}: "
        f"{intent.descripcion}"
    )


def _intent_list_invoke(params: dict) -> str:
    from core.standing_intents import standing_intents

    intents = standing_intents.listar(params["user_id"])
    if not intents:
        return f"No tiene recordatorios por tema pendientes{vocative()}."

    lineas = [f"Recordatorios que esperan una ocasión{vocative()}:", ""]
    for i in intents:
        temas = ", ".join(i.triggers)
        lineas.append(f"• #{i.id} — {i.descripcion}  (cuando hable de: {temas})")
    return "\n".join(lineas)


def _intent_cancel_invoke(params: dict) -> str:
    from core.standing_intents import standing_intents

    try:
        intent_id = int(params.get("id") or params.get("intent_id") or 0)
    except (TypeError, ValueError):
        return "Necesito el número del recordatorio que quiere quitar."

    if intent_id <= 0:
        return "Necesito el número del recordatorio que quiere quitar."

    if standing_intents.cancelar(intent_id, params["user_id"]):
        return f"Listo{vocative()}, he quitado el recordatorio #{intent_id}."
    return f"No encontré un recordatorio suyo con el número #{intent_id}{vocative()}."


register_tool(ToolSpec(
    name="intent_create",
    description=(
        "Crea un recordatorio que se dispara cuando el usuario vuelva a mencionar un tema, "
        "en vez de a una hora concreta. Úsala cuando diga cosas como 'cuando hable de X, "
        "recuérdame Y' o 'la próxima vez que mencione X...'. Para recordatorios con fecha u "
        "hora usa 'task_create' en su lugar."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "descripcion": {"type": "string", "description": "Qué recordarle."},
            "tema": {"type": "string", "description": "De qué tiene que hablar para que salte."},
            "disparadores": {
                "type": "string",
                "description": "Palabras clave concretas, separadas por espacios (opcional).",
            },
            "user_id": {"type": "string"},
        },
        "required": ["descripcion", "user_id"],
    },
    # GREEN: no ejecuta nada, solo guarda una nota que se mostrará más adelante. Es el mismo
    # nivel que crear un recordatorio por reloj.
    risk_level=RiskLevel.GREEN,
    invoke=_intent_create_invoke,
))

register_tool(ToolSpec(
    name="intent_list",
    description="Lista los recordatorios por tema que el usuario tiene esperando una ocasión.",
    parameters_schema={
        "type": "object",
        "properties": {"user_id": {"type": "string"}},
        "required": ["user_id"],
    },
    risk_level=RiskLevel.GREEN,
    invoke=_intent_list_invoke,
))

register_tool(ToolSpec(
    name="intent_cancel",
    description="Quita un recordatorio por tema, por su número.",
    parameters_schema={
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "Número del recordatorio."},
            "user_id": {"type": "string"},
        },
        "required": ["id", "user_id"],
    },
    risk_level=RiskLevel.GREEN,
    invoke=_intent_cancel_invoke,
))


# ─────────────────────────────────────────────
#  Control del escritorio como herramientas del modelo
#
#  Escribir y hacer clic existían solo como intents del clasificador, que resuelve UNA
#  acción por mensaje y necesita que la frase se parezca a su entrenamiento. Eso hacía
#  imposible el caso real que las motivó: estar lejos del PC, pedir una captura por
#  Telegram, y a partir de lo que se ve pedir que escriba algo y confirme. Son tres pasos
#  encadenados y con contexto entre ellos — exactamente lo que un modelo con herramientas
#  sabe hacer y un clasificador de intents no.
# ─────────────────────────────────────────────

def _pc_screenshot_invoke(params: dict) -> str:
    """Captura la pantalla y la registra como la vigente para calcular clics."""
    from os_integration.screen_vision import capturar

    captura = capturar()
    if captura is None:
        return "No pude tomar la captura de pantalla."
    return (
        f"Captura tomada ({captura.ancho}x{captura.alto}). "
        f"Identificador: {captura.frame_id}. Archivo: {captura.ruta}"
    )


def _pc_look_invoke(params: dict) -> str:
    """Mira la pantalla y cuenta qué hay, o localiza un elemento concreto."""
    from os_integration.screen_vision import capturar, describir, localizar

    captura = capturar()
    if captura is None:
        return "No pude tomar la captura de pantalla."

    objetivo = (params.get("buscar") or params.get("target") or "").strip()
    if not objetivo:
        return f"[captura {captura.frame_id}] {describir(captura)}"

    coords, motivo = localizar(captura, objetivo)
    if coords is None:
        return motivo
    return (
        f"«{objetivo}» está en x={coords[0]}, y={coords[1]} "
        f"(captura {captura.frame_id}). Usa esas coordenadas y ese identificador para "
        f"hacer clic, sin volver a capturar."
    )


def _pc_type_invoke(params: dict) -> str:
    from automation.pc_controller import type_text

    texto = params.get("text") or params.get("texto") or ""
    if not texto:
        return "Necesito saber qué texto escribir."
    return type_text(str(texto))


def _pc_key_invoke(params: dict) -> str:
    """Pulsa una tecla o combinación: Enter, Escape, ctrl+s..."""
    try:
        import pyautogui
    except ImportError:
        return "No tengo instalado lo necesario para pulsar teclas."

    combo = (params.get("key") or params.get("tecla") or "").strip()
    if not combo:
        return "Necesito saber qué tecla pulsar."

    try:
        partes = [p.strip().lower() for p in combo.replace("+", " ").split() if p.strip()]
        if len(partes) > 1:
            pyautogui.hotkey(*partes)
        else:
            pyautogui.press(partes[0])
        return f"Pulsado: {combo}"
    except Exception as e:
        logger.warning(f"Fallo pulsando '{combo}': {e}")
        return explicar(e, f"pulsar '{combo}'")


def _pc_click_invoke(params: dict) -> str:
    """Hace clic, pero solo con coordenadas de la captura vigente.

    Una coordenada solo significa algo respecto de la captura de la que salió. Si entre
    mirar y pulsar la pantalla cambió, el clic aterriza en otro sitio — y con el ratón eso
    no es un error recuperable, es haber pulsado algo que nadie eligió. Es la comprobación
    que OpenClaw hace atando cada acción al `frameId` de su captura.
    """
    from automation.pc_controller import click_position
    from os_integration.screen_vision import validar_para_clic

    try:
        x = int(params.get("x"))
        y = int(params.get("y"))
    except (TypeError, ValueError):
        return "Necesito las coordenadas x e y del punto donde hacer clic."

    frame_id = str(params.get("frame_id") or params.get("captura") or "").strip()
    valido, motivo = validar_para_clic(frame_id)
    if not valido:
        return motivo

    return click_position(x, y)


register_tool(ToolSpec(
    name="pc_screenshot",
    description=(
        "Toma una captura de la pantalla del PC y devuelve la ruta del archivo. Úsala "
        "cuando el usuario no esté delante del equipo y necesite ver qué hay, o antes de "
        "escribir o hacer clic para saber sobre qué estás actuando."
    ),
    parameters_schema={"type": "object", "properties": {}},
    # GREEN: mira, no toca. Mismo nivel que el intent TAKE_SCREENSHOT que ya existía.
    risk_level=RiskLevel.GREEN,
    invoke=_pc_screenshot_invoke,
))

register_tool(ToolSpec(
    name="pc_type",
    description=(
        "Escribe texto con el teclado en la ventana que tenga el foco en ese momento. "
        "Si el usuario te dice qué escribir, ESCRÍBELO: es él quien sabe qué ventana dejó "
        "abierta, y a menudo te lo pide precisamente porque está lejos del equipo. No hace "
        "falta ver la pantalla antes ni pedir permiso — la confirmación ya la pide el "
        "sistema por su cuenta. Usa 'pc_screenshot' solo si el usuario quiere ver algo."
    ),
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string", "description": "Qué escribir."}},
        "required": ["text"],
    },
    # YELLOW: el efecto depende de qué ventana tenga el foco, y quien da la orden no lo ve.
    risk_level=RiskLevel.YELLOW,
    invoke=_pc_type_invoke,
))

register_tool(ToolSpec(
    name="pc_key",
    description=(
        "Pulsa una tecla o combinación en la ventana con el foco: 'enter', 'escape', "
        "'ctrl+s', 'alt+tab'. Para confirmar un diálogo suele bastar con 'enter'."
    ),
    parameters_schema={
        "type": "object",
        "properties": {"key": {"type": "string", "description": "Tecla o combinación."}},
        "required": ["key"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_pc_key_invoke,
))

register_tool(ToolSpec(
    name="pc_click",
    description=(
        "Hace clic en un punto de la pantalla. Las coordenadas deben venir de 'pc_look' o "
        "'pc_screenshot', y hay que pasar el identificador de esa captura: si la pantalla "
        "cambió entre mirar y pulsar, el clic se rechaza en vez de aterrizar donde no debe."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "Coordenada horizontal en píxeles."},
            "y": {"type": "integer", "description": "Coordenada vertical en píxeles."},
            "frame_id": {
                "type": "string",
                "description": "Identificador de la captura de la que salen las coordenadas.",
            },
        },
        "required": ["x", "y", "frame_id"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_pc_click_invoke,
))


register_tool(ToolSpec(
    name="pc_look",
    description=(
        "Mira la pantalla del usuario y cuenta qué hay. Sin argumentos describe lo que se "
        "ve —qué aplicación está delante, si hay un diálogo esperando respuesta—. Con "
        "'buscar' localiza un elemento concreto ('el botón Aceptar', 'el campo de "
        "búsqueda') y devuelve sus coordenadas para poder pulsarlo con 'pc_click'. "
        "Úsala cuando el usuario no esté delante del equipo y necesites saber qué pasa."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "buscar": {
                "type": "string",
                "description": "Elemento a localizar. Vacío para describir la pantalla entera.",
            },
        },
    },
    # GREEN: observa, no toca. Lo que se hace DESPUÉS con esas coordenadas sí es YELLOW.
    risk_level=RiskLevel.GREEN,
    invoke=_pc_look_invoke,
))


def _pc_find_invoke(params: dict) -> str:
    """Localiza un control preguntándole al sistema, no adivinando sobre una imagen.

    El árbol de accesibilidad da la posición EXACTA y el nombre real del control, en
    milisegundos y sin gastar una llamada al modelo. Cuando la aplicación lo expone, es
    mejor que la visión en todo. Cuando no —Electron y similares—, se dice y se sugiere
    mirar, en vez de devolver unas coordenadas inventadas.
    """
    from os_integration.ui_tree import buscar, describir_ventana_activa, disponible

    if not disponible():
        return (
            "No puedo leer el árbol de accesibilidad en este sistema. Usa 'pc_look' para "
            "mirar la pantalla."
        )

    objetivo = (params.get("buscar") or params.get("target") or "").strip()
    if not objetivo:
        return describir_ventana_activa()

    elemento, candidatos = buscar(objetivo)
    if elemento is None:
        if not candidatos:
            # Sin candidatos no se sabe si el control no está o si la ventana entera está
            # muda. `describir_ventana_activa` ya distingue los dos casos y, si la
            # aplicación tiene el árbol apagado, dice cómo encenderlo.
            return f"No encontré «{objetivo}». {describir_ventana_activa()}"
        nombres = ", ".join(f"«{c.nombre}»" for c in candidatos[:8])
        return (
            f"No encontré «{objetivo}». Lo que sí hay en esta ventana: {nombres}. "
            f"Si ninguno es, usa 'pc_look' para mirar la pantalla."
        )

    aviso = ""
    if len(candidatos) > 1:
        otros = ", ".join(f"«{c.nombre}»" for c in candidatos[1:4])
        aviso = f" (hay más coincidencias: {otros})"

    # Las coordenadas del árbol son exactas y NO dependen de ninguna captura, así que se
    # devuelve el identificador de la vigente —o se toma una— para que `pc_click` las
    # acepte sin obligar al modelo a mirar antes.
    from os_integration.screen_vision import capturar, ultima_captura

    captura = ultima_captura()
    if captura is None or not captura.esta_fresca():
        captura = capturar()
    frame = captura.frame_id if captura else "sin-captura"

    return (
        f"{elemento} — usa x={elemento.x}, y={elemento.y} con frame_id={frame} "
        f"para hacer clic{aviso}."
    )


register_tool(ToolSpec(
    name="pc_find",
    description=(
        "Localiza un control de la ventana activa preguntándole al sistema operativo: "
        "botones, campos, menús, pestañas. Devuelve su posición EXACTA. Es preferible a "
        "'pc_look' siempre que funcione, porque no adivina sobre una imagen ni gasta una "
        "llamada al modelo. Sin argumentos lista los controles disponibles. Si la "
        "aplicación no expone su contenido (VS Code y otras basadas en Electron), lo dice: "
        "en ese caso suele poder arreglarse con 'pc_enable_tree', y mientras tanto sirve "
        "'pc_look'."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "buscar": {
                "type": "string",
                "description": "Nombre del control, p. ej. 'Aceptar'. Vacío para listarlos.",
            },
        },
    },
    # GREEN: consulta el estado de la interfaz, no la modifica.
    risk_level=RiskLevel.GREEN,
    invoke=_pc_find_invoke,
))


def _pc_enable_tree_invoke(params: dict) -> str:
    """Enciende el árbol de accesibilidad de una aplicación Electron.

    Chromium no publica su interfaz salvo que se le pida al arrancar. Dejar el flag escrito
    en la configuración de la aplicación convierte una ventana muda —VS Code daba 7
    elementos— en una legible —221—, y con eso el agente deja de adivinar coordenadas sobre
    una captura para leer la posición exacta de cada control.
    """
    from os_integration.electron_a11y import APPS, activar, detectar_app
    from os_integration.ui_tree import leer_ventana_activa

    app = (params.get("app") or "").strip().lower()
    if not app:
        # Sin indicación explícita, la aplicación es la que se tiene delante: es la que el
        # usuario acaba de intentar manejar y la razón de que se llame a esta herramienta.
        _, titulo = leer_ventana_activa()
        app = detectar_app(titulo) or ""
        if not app:
            conocidas = ", ".join(sorted(APPS))
            return (
                f"No reconozco la aplicación de la ventana activa («{titulo}»), así que no "
                f"sé dónde escribir su configuración. Puedo hacerlo en: {conocidas}."
            )

    _, mensaje = activar(app)
    return mensaje


register_tool(ToolSpec(
    name="pc_enable_tree",
    description=(
        "Último recurso para una aplicación basada en Electron (VS Code, Cursor, Windsurf) "
        "que NO publique su interfaz: escribe una línea en su configuración y hay que "
        "reiniciarla. Úsala solo si 'pc_look' informa de que la ventana no expone sus "
        "controles — y no la ofrezcas por las dudas: medido en esta máquina, VS Code "
        "publica su interfaz entera sin ningún ajuste, así que pedirle al usuario que "
        "cambie su configuración y reinicie el editor suele ser molestarlo para nada."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "app": {
                "type": "string",
                "description": (
                    "Aplicación: 'vscode', 'vscode-insiders', 'cursor' o 'windsurf'. "
                    "Vacío para usar la de la ventana activa."
                ),
            },
        },
    },
    # YELLOW: modifica la configuración de otra aplicación del usuario. Es reversible y se
    # guarda copia, pero cambia algo fuera de O.R.I.O.N. y eso se pregunta antes.
    risk_level=RiskLevel.YELLOW,
    invoke=_pc_enable_tree_invoke,
))


# --------------------------------------------------------------------- terminal embebida

def _terminal_run_command_invoke(params: dict) -> str:
    """Corre un comando en LA terminal del escritorio y devuelve su salida.

    Usa la misma sesión que muestra el panel (`core.terminal_session.terminal_manager`),
    nunca una shell aparte: si el agente ejecutara en una terminal invisible, el usuario
    perdería la única forma de ver qué se corrió en su máquina.

    Llama a `terminal_manager.ensure()` sin pasar por el gate de `terminal_open` a
    propósito: no es un salto, es el mismo permiso pedido una sola vez. Para llegar acá,
    `execute_tool()` ya ejecutó `require_confirmation("terminal_run_command", ...)`, y el
    modal mostró el comando exacto (`command` está en `_DETAILS_ALLOWED_KEYS`). Pedir dos
    confirmaciones seguidas por el mismo "sí" solo entrena a decir que sí sin leer.
    """
    from core.terminal_session import TerminalUnavailable, terminal_manager

    command = str(params.get("command") or "").strip()
    if not command:
        return f"Necesito el comando que quiere que ejecute en la terminal{vocative()}."

    try:
        sesion = terminal_manager.ensure()
        salida = sesion.run_command_capture(command)
    except TerminalUnavailable as e:
        logger.error(f"terminal no disponible para '{command}': {e}")
        return explicar(e, "usar la terminal")

    if not salida:
        return f"Ejecuté `{command}` en la terminal. No devolvió salida."
    return f"Ejecuté `{command}` en la terminal:\n\n{salida}"


register_tool(ToolSpec(
    name="terminal_run_command",
    description=(
        "Ejecuta un comando en la terminal del escritorio (PowerShell) y devuelve su "
        "salida. Úsala cuando el usuario pida correr algo concreto: 'git status', "
        "'pip list', 'ipconfig'. El comando se ejecuta en la misma terminal que el usuario "
        "ve en pantalla, así que puede seguir lo que pasa. No la uses para tareas que ya "
        "tienen herramienta propia (abrir apps, buscar archivos, leer el correo): esas "
        "hacen el trabajo mejor y sin abrir una shell."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "El comando exacto a ejecutar, tal cual se escribiría.",
            },
        },
        "required": ["command"],
    },
    # YELLOW, y por eso mismo queda fuera de voz, Telegram y Discord: `CHANNEL_ALLOWED_LEVELS`
    # solo deja pasar verde en los canales remotos y no hay excepción para esta acción.
    # Ejecutar comandos arbitrarios es lo que `.claude/rules/security-levels.md` clasifica
    # como amarillo ("comandos del sistema con argumentos dinámicos"), y se confirma con el
    # comando a la vista, delante del PC.
    risk_level=RiskLevel.YELLOW,
    invoke=_terminal_run_command_invoke,
))


def _terminal_read_output_invoke(params: dict) -> str:
    """Devuelve lo último que se vio en la terminal, incluido lo que corrió el usuario.

    Sin esto el agente solo conoce la salida de SUS comandos, y no puede contestar "¿por
    qué falló lo que acabo de correr?" — que es media razón de tener una terminal a la
    vista del asistente.
    """
    from core.terminal_session import terminal_manager

    try:
        lineas = int(params.get("lines") or 60)
    except (TypeError, ValueError):
        lineas = 60

    sesion = terminal_manager.active()
    if sesion is None:
        return "No hay ninguna terminal abierta ahora mismo."

    salida = sesion.salida_reciente(lineas)
    if not salida:
        return "La terminal está abierta pero todavía no mostró nada."
    return f"Últimas líneas de la terminal:" + chr(10) + chr(10) + salida


register_tool(ToolSpec(
    name="terminal_read_output",
    description=(
        "Lee lo último que se vio en la terminal del escritorio, incluidos los comandos "
        "que ejecutó el usuario a mano. Úsala cuando te pregunten por algo que pasó ahí: "
        "por qué falló un comando, qué devolvió, qué está corriendo."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "lines": {
                "type": "integer",
                "description": "Cuántas líneas leer hacia atrás (por defecto 60).",
            },
        },
    },
    # YELLOW y no GREEN: en una terminal puede haber quedado impresa una clave, un token o
    # la salida de algo privado, y leerla significa mandarla al proveedor del modelo. Que
    # el usuario lo autorice cada vez es el precio correcto; además, al ser amarilla queda
    # fuera de los canales remotos igual que el resto de la terminal.
    risk_level=RiskLevel.YELLOW,
    invoke=_terminal_read_output_invoke,
))


# ─────────────────────────────────────────────
#  REQ-029 — Manos para trabajar con repos: archivos y git, confinados
#
#  Las 8 son envoltorios finos. Toda la seguridad vive en dos lugares que NO están acá:
#  `core/workspace_files.py::resolver()` (el confinamiento de rutas) y el gate de
#  `execute_tool()` de arriba, que ya corrió `security_manager.require_confirmation()`
#  antes de que cualquiera de estos `invoke` llegue a ejecutarse (CA-09). Ningún camino
#  propio: ninguna de las 8 se invoca por fuera de `execute_tool()`.
#
#  Las 8 están además en `DESKTOP_ONLY_ACTIONS` (`core/security_manager.py`): ni siquiera
#  las verdes son alcanzables desde Telegram, Discord, voz, API o correo (CA-06).
# ─────────────────────────────────────────────

def _con_manejo(nombre: str, operacion: Callable[[], str]) -> str:
    """Corre una operación de archivo devolviendo SIEMPRE texto que el modelo entienda.

    Un escape de confinamiento vuelve como la explicación de `RutaFueraDeRaiz` (que ya
    dice qué pasó y sobre qué carpetas sí puede trabajar); cualquier otro fallo vuelve
    como una frase, nunca como un stacktrace (CA-14). El detalle técnico va al log, que
    es donde sirve, y no a la conversación, donde solo confunde.
    """
    from core.workspace_files import RutaFueraDeRaiz

    try:
        return operacion()
    except RutaFueraDeRaiz as e:
        logger.warning(f"'{nombre}' rechazada por confinamiento de rutas: {e}")
        return str(e)
    except OSError as e:
        logger.error(f"'{nombre}' falló por el sistema de archivos: {e}")
        return (
            f"No pude completar esa operación sobre el archivo: "
            f"{e.strerror or 'error del sistema de archivos'}."
        )
    except Exception as e:
        logger.error(f"'{nombre}' falló inesperadamente: {type(e).__name__}: {e}")
        return "No pude completar esa operación sobre el repositorio."


def _entero(params: dict, clave: str) -> Optional[int]:
    """Return el parámetro como entero, o None si falta o no es un número."""
    valor = params.get(clave)
    if valor is None or valor == "":
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        logger.debug(f"parámetro '{clave}' no numérico, se ignora: {valor!r}")
        return None


def _file_list_invoke(params: dict) -> str:
    from core.workspace_files import listar

    ruta = str(params.get("path") or "")
    return _con_manejo("file_list", lambda: listar(ruta))


register_tool(ToolSpec(
    name="file_list",
    description=(
        "Lista el contenido de una carpeta de un repositorio habilitado. Sin 'path' te "
        "dice cuáles son las carpetas habilitadas, que es por donde conviene empezar. "
        "Solo funciona dentro de esas carpetas: cualquier otra ruta se rechaza."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Carpeta a listar, absoluta o relativa a una carpeta habilitada. "
                    "Vacío para ver cuáles están habilitadas."
                ),
            },
        },
    },
    # GREEN: mirar el índice de una carpeta que el humano ya autorizó no merece una
    # confirmación por uso. El permiso se dio al habilitar la carpeta, igual que la
    # terminal embebida lo pide al abrir y no por comando (security-levels.md).
    risk_level=RiskLevel.GREEN,
    invoke=_file_list_invoke,
))


def _file_read_invoke(params: dict) -> str:
    from core.workspace_files import leer

    ruta = str(params.get("path") or "")
    desde = _entero(params, "desde")
    hasta = _entero(params, "hasta")
    return _con_manejo("file_read", lambda: leer(ruta, desde, hasta))


register_tool(ToolSpec(
    name="file_read",
    description=(
        "Lee un archivo de un repositorio habilitado, con las líneas numeradas. Un archivo "
        "grande vuelve truncado avisando en qué línea se cortó: para seguir, volvé a "
        "llamarla con 'desde' en la línea siguiente. Usala antes de editar, para copiar el "
        "fragmento exacto que vas a reemplazar."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Archivo a leer, absoluto o relativo a una carpeta habilitada.",
            },
            "desde": {
                "type": "integer",
                "description": "Primera línea a leer (1 es la primera). Opcional.",
            },
            "hasta": {
                "type": "integer",
                "description": "Última línea a leer, inclusive. Opcional.",
            },
        },
        "required": ["path"],
    },
    # GREEN por el permiso ya dado al habilitar la carpeta; DESKTOP_ONLY porque leer un
    # archivo es mandárselo al proveedor del modelo, y verde no puede significar acá
    # "alcanzable desde Telegram".
    risk_level=RiskLevel.GREEN,
    invoke=_file_read_invoke,
))


def _file_search_invoke(params: dict) -> str:
    from core.workspace_files import buscar

    texto = str(params.get("query") or "")
    ruta = str(params.get("path") or "")
    return _con_manejo("file_search", lambda: buscar(texto, ruta))


register_tool(ToolSpec(
    name="file_search",
    description=(
        "Busca un texto literal dentro de los repositorios habilitados y devuelve archivo, "
        "línea y el texto de la línea. Es la forma de orientarse en un repo que no conocés: "
        "buscá el nombre de la función o de la constante y después leé el archivo. No es "
        "una expresión regular: se busca el texto tal cual."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Texto literal a buscar.",
            },
            "path": {
                "type": "string",
                "description": "Carpeta donde buscar. Vacío para buscar en todas las habilitadas.",
            },
        },
        "required": ["query"],
    },
    risk_level=RiskLevel.GREEN,
    invoke=_file_search_invoke,
))


def _file_write_invoke(params: dict) -> str:
    from core.workspace_files import escribir

    ruta = str(params.get("path") or "")
    contenido = params.get("content")
    if contenido is None:
        return f"Necesito el contenido a escribir{vocative()}."
    return _con_manejo("file_write", lambda: escribir(ruta, str(contenido)))


register_tool(ToolSpec(
    name="file_write",
    description=(
        "Crea un archivo nuevo o reescribe uno entero dentro de un repositorio habilitado, "
        "creando las carpetas que falten. REESCRIBE TODO el archivo: para cambiar una parte "
        "de un archivo que ya existe usá file_edit, que no pisa el resto."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Archivo a crear o reescribir, dentro de una carpeta habilitada.",
            },
            "content": {
                "type": "string",
                "description": "Contenido completo del archivo.",
            },
        },
        "required": ["path", "content"],
    },
    # YELLOW: escribir es irreversible, y se confirma con la RUTA a la vista — `path` está
    # en `_DETAILS_ALLOWED_KEYS`, así que el modal dice dónde se va a escribir (CA-08).
    # El contenido NO se muestra ni se audita: puede ser largo y puede traer secretos.
    risk_level=RiskLevel.YELLOW,
    invoke=_file_write_invoke,
))


def _file_edit_invoke(params: dict) -> str:
    from core.workspace_files import editar

    ruta = str(params.get("path") or "")
    viejo = params.get("buscar")
    nuevo = params.get("reemplazar")
    if not viejo:
        return f"Necesito el fragmento exacto que hay que reemplazar{vocative()}."
    return _con_manejo("file_edit", lambda: editar(ruta, str(viejo), str(nuevo or "")))


register_tool(ToolSpec(
    name="file_edit",
    description=(
        "Reemplaza un fragmento exacto de un archivo por otro, sin tocar el resto. El "
        "fragmento tiene que aparecer UNA sola vez: si aparece varias, agregá líneas de "
        "contexto alrededor hasta que sea único. Leé el archivo con file_read antes, para "
        "copiar el texto con su indentación exacta."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Archivo a editar, dentro de una carpeta habilitada.",
            },
            "buscar": {
                "type": "string",
                "description": "Fragmento exacto a reemplazar, tal cual está en el archivo.",
            },
            "reemplazar": {
                "type": "string",
                "description": "Texto que lo reemplaza. Vacío para borrar el fragmento.",
            },
        },
        "required": ["path", "buscar"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_file_edit_invoke,
))


def _git_status_invoke(params: dict) -> str:
    from core.workspace_git import estado

    ruta = str(params.get("path") or "")
    return _con_manejo("git_status", lambda: estado(ruta))


register_tool(ToolSpec(
    name="git_status",
    description=(
        "Muestra el estado git de un repositorio habilitado: rama actual y archivos "
        "modificados o sin seguir. Con una sola carpeta habilitada no hace falta 'path'."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Carpeta del repositorio. Opcional si hay una sola habilitada.",
            },
        },
    },
    risk_level=RiskLevel.GREEN,
    invoke=_git_status_invoke,
))


def _git_diff_invoke(params: dict) -> str:
    from core.workspace_git import diff

    ruta = str(params.get("path") or "")
    archivo = str(params.get("archivo") or "")
    return _con_manejo("git_diff", lambda: diff(ruta, archivo))


register_tool(ToolSpec(
    name="git_diff",
    description=(
        "Muestra los cambios sin confirmar de un repositorio habilitado, opcionalmente de "
        "un solo archivo. Usala para ver qué se cambió antes de resumirlo o de proponer un "
        "mensaje de commit."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Carpeta del repositorio. Opcional si hay una sola habilitada.",
            },
            "archivo": {
                "type": "string",
                "description": "Acotar el diff a este archivo. Opcional.",
            },
        },
    },
    risk_level=RiskLevel.GREEN,
    invoke=_git_diff_invoke,
))


def _git_log_invoke(params: dict) -> str:
    from core.workspace_git import log

    ruta = str(params.get("path") or "")
    cantidad = _entero(params, "cantidad")
    return _con_manejo("git_log", lambda: log(ruta, 10 if cantidad is None else cantidad))


register_tool(ToolSpec(
    name="git_log",
    description=(
        "Muestra los últimos commits de un repositorio habilitado, con hash corto, fecha, "
        "autor y título. Usala para saber en qué se viene trabajando."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Carpeta del repositorio. Opcional si hay una sola habilitada.",
            },
            "cantidad": {
                "type": "integer",
                "description": "Cuántos commits mostrar (por defecto 10, máximo 50).",
            },
        },
    },
    risk_level=RiskLevel.GREEN,
    invoke=_git_log_invoke,
))



# ─────────────────────────────────────────────
#  REQ-030 — qué carpetas puede tocar, dicho al agente
# ─────────────────────────────────────────────
#
#  Sin esto, REQ-029 quedaba encendido solo por un JSON escrito a mano. Este proyecto es un
#  asistente, no una app de formularios: la forma natural de darle una carpeta es decírsela.
#  Las dos son YELLOW y solo de escritorio — habilitar una carpeta es decidir hasta dónde
#  llegan las 8 herramientas de repositorio, y esa decisión se toma delante del computador.

def _workspace_add_invoke(params: dict) -> str:
    from core.workspace_config import RaizRechazada, agregar_raiz

    ruta = str(params.get("path") or "")
    try:
        real = agregar_raiz(ruta)
    except RaizRechazada as e:
        logger.warning(f"'workspace_add_folder' rechazada: {e}")
        return str(e)
    except OSError as e:
        logger.error(f"'workspace_add_folder' falló al guardar: {e}")
        return "No pude guardar la carpeta habilitada."
    return (
        f"Listo: ya puedo leer y editar archivos dentro de «{real}». "
        f"Para dejar de tener acceso, pedímelo y la quito."
    )


register_tool(ToolSpec(
    name="workspace_add_folder",
    description=(
        "Habilita una carpeta del computador para que puedas leer, buscar y editar sus "
        "archivos y consultar su git. Usala cuando el usuario te diga que trabajes sobre un "
        "proyecto o repositorio que todavía no tenés habilitado. El permiso queda guardado."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Carpeta a habilitar, con su ruta completa.",
            },
        },
        "required": ["path"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_workspace_add_invoke,
))


def _workspace_remove_invoke(params: dict) -> str:
    from core.workspace_config import RaizRechazada, quitar_raiz

    ruta = str(params.get("path") or "")
    try:
        real = quitar_raiz(ruta)
    except RaizRechazada as e:
        logger.warning(f"'workspace_remove_folder' rechazada: {e}")
        return str(e)
    except OSError as e:
        logger.error(f"'workspace_remove_folder' falló al guardar: {e}")
        return "No pude quitar la carpeta habilitada."
    return f"Listo: ya no tengo acceso a «{real}»."


register_tool(ToolSpec(
    name="workspace_remove_folder",
    description=(
        "Deja de tener acceso a una carpeta habilitada. Usala cuando el usuario te diga que "
        "ya no trabajes sobre ese proyecto."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Carpeta a quitar, con su ruta completa.",
            },
        },
        "required": ["path"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_workspace_remove_invoke,
))


# ─────────────────────────────────────────────
#  REQ-031 — llamar a una API, no solo leer páginas
# ─────────────────────────────────────────────
#
#  `web_read` abre una página y es verde. Esto es lo otro: mandarle datos a un servicio. Es
#  YELLOW porque tiene efectos del otro lado, y porque amarillo además la deja fuera de todos
#  los canales remotos. El destino pasa por `core/http_seguro.py`, igual que la lectura.

#: Cuánto del cuerpo se le devuelve al modelo. El tope de descarga real está en
#: `http_seguro.MAX_BYTES`; esto es lo que entra en la conversación sin comerse el turno.
_MAX_RESPUESTA_HTTP = 8000


def _http_request_invoke(params: dict) -> str:
    import json as _json

    from core.http_seguro import DestinoBloqueado, pedir
    from core.mcp_client import expandir_secreto

    url = str(params.get("url") or "").strip()
    if not url:
        return f"Necesito la dirección a la que querés que llame{vocative()}."

    cabeceras_crudas = params.get("headers") or {}
    if not isinstance(cabeceras_crudas, dict):
        return "Las cabeceras tienen que venir como pares de clave y valor."
    # `${MI_TOKEN}` se resuelve contra el entorno (el mismo mecanismo que ya usan los
    # módulos de correo): así una credencial no viaja literal en la conversación ni queda
    # escrita en el log de auditoría.
    cabeceras = {str(k): str(expandir_secreto(v)) for k, v in cabeceras_crudas.items()}

    cuerpo = params.get("body")
    if isinstance(cuerpo, (dict, list)):
        cuerpo = _json.dumps(cuerpo, ensure_ascii=False)
        cabeceras.setdefault("Content-Type", "application/json")
    elif cuerpo is not None:
        cuerpo = str(cuerpo)

    try:
        # `permitir_interno=True`: esta herramienta es amarilla, solo de escritorio, y
        # confirma cada llamada mostrando la URL. Sin esto, el agente no puede probar el
        # servidor de desarrollo que el mismo acaba de levantar con project_start, que es
        # justo la mitad de un flujo de desarrollo. `web_read` sigue con el bloqueo absoluto.
        respuesta = pedir(url, metodo=str(params.get("method") or "GET"),
                          headers=cabeceras, cuerpo=cuerpo, permitir_interno=True)
    except DestinoBloqueado as e:
        logger.warning(f"'http_request' rechazada: {e}")
        return str(e)
    except OSError as e:
        logger.error(f"'http_request' no pudo conectarse: {e}")
        return f"No pude conectarme a esa dirección: {type(e).__name__}."
    except Exception as e:
        logger.error(f"'http_request' falló: {type(e).__name__}: {e}")
        return "No pude completar esa llamada."

    cuerpo_texto = respuesta.texto[:_MAX_RESPUESTA_HTTP]
    avisos = ""
    if len(respuesta.texto) > _MAX_RESPUESTA_HTTP:
        avisos += f"\n[Respuesta recortada a {_MAX_RESPUESTA_HTTP} caracteres.]"
    if respuesta.truncada:
        avisos += "\n[El servidor mandó más de lo que descargo; se cortó ahí.]"
    return f"HTTP {respuesta.status} desde {respuesta.url_final}\n\n{cuerpo_texto}{avisos}"


register_tool(ToolSpec(
    name="http_request",
    description=(
        "Llama a una API por HTTP: podés elegir el método, mandar cabeceras y un cuerpo. "
        "Usala para servicios que necesitan algo más que abrir una página (para leer una "
        "página está web_read). Si una cabecera lleva credencial, escribí "
        "${NOMBRE_DE_LA_VARIABLE} en vez del token: se resuelve contra el entorno del equipo."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Dirección http(s) del servicio."},
            "method": {
                "type": "string",
                "description": "GET, POST, PUT, PATCH, DELETE o HEAD. Por defecto GET.",
            },
            "headers": {
                "type": "object",
                "description": "Cabeceras. Para credenciales usá ${NOMBRE_DE_LA_VARIABLE}.",
            },
            "body": {
                "type": "string",
                "description": "Cuerpo de la petición. Un objeto se manda como JSON.",
            },
        },
        "required": ["url"],
    },
    # YELLOW: manda datos afuera y tiene efectos del otro lado. La confirmación muestra la
    # URL —`url` ya está en `_DETAILS_ALLOWED_KEYS`—, que es lo que hay que ver para decidir.
    risk_level=RiskLevel.YELLOW,
    invoke=_http_request_invoke,
))


# ─────────────────────────────────────────────
#  REQ-032 — cerrar el ciclo: ver el proyecto, correrlo, leer el fallo
# ─────────────────────────────────────────────

def _project_tree_invoke(params: dict) -> str:
    from core.workspace_files import arbol

    profundidad = _entero(params, "depth")
    return _con_manejo(
        "project_tree",
        lambda: arbol(str(params.get("path") or ""), 3 if profundidad is None else profundidad),
    )


register_tool(ToolSpec(
    name="project_tree",
    description=(
        "Muestra la estructura de un proyecto habilitado: carpetas y archivos con sangría, "
        "hasta la profundidad que pidas. Usala PRIMERO cuando llegues a un repositorio que "
        "no conocés, en vez de ir listando carpeta por carpeta. Salteá node_modules y .git "
        "ya viene hecho."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Carpeta a mostrar. Opcional si hay una sola habilitada.",
            },
            "depth": {
                "type": "integer",
                "description": "Cuántos niveles bajar (por defecto 3, máximo 8).",
            },
        },
    },
    risk_level=RiskLevel.GREEN,
    invoke=_project_tree_invoke,
))


def _project_run_invoke(params: dict) -> str:
    from core.workspace_run import describir, ejecutar

    comando = str(params.get("command") or "").strip()
    if not comando:
        return f"Necesito el comando que querés que corra{vocative()}."
    timeout = _entero(params, "timeout")
    return _con_manejo(
        "project_run",
        lambda: describir(ejecutar(comando, str(params.get("path") or ""), timeout=timeout)),
    )


register_tool(ToolSpec(
    name="project_run",
    description=(
        "Ejecuta un comando DENTRO de la carpeta de un proyecto habilitado y te devuelve su "
        "salida y su código de salida: las pruebas, un build, un linter, un script. Es la "
        "herramienta para COMPROBAR lo que escribiste — corré, leé el error, corregí con "
        "file_edit y volvé a correr. No usa la terminal que el usuario tiene en pantalla."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "El comando exacto, tal cual se escribiría en la consola.",
            },
            "path": {
                "type": "string",
                "description": "Carpeta del proyecto. Opcional si hay una sola habilitada.",
            },
            "timeout": {
                "type": "integer",
                "description": "Segundos antes de cortarlo (por defecto 120, máximo 600).",
            },
        },
        "required": ["command"],
    },
    # YELLOW y confirma CADA llamada mostrando el comando (`command` está en
    # `_DETAILS_ALLOWED_KEYS`). No es cosmético: un comando puede escribir archivos, así que
    # sin esta confirmación la de `file_write` quedaría decorativa — habría un camino que la
    # rodea. Decisión explícita de Johan el 2026-09-09.
    risk_level=RiskLevel.YELLOW,
    invoke=_project_run_invoke,
))


# ─────────────────────────────────────────────
#  REQ-034 — entender un repositorio grande sin leerlo entero
# ─────────────────────────────────────────────

def _code_index_invoke(params: dict) -> str:
    from core.code_index import estado as estado_indice
    from core.code_index import indexar
    from core.workspace_run import carpeta_de_trabajo

    def _correr() -> str:
        carpeta = carpeta_de_trabajo(str(params.get("path") or ""))
        resultado = indexar(carpeta)
        actual = estado_indice(carpeta)

        partes = []
        if resultado.archivos_nuevos:
            partes.append(f"{resultado.archivos_nuevos} archivos nuevos")
        if resultado.archivos_actualizados:
            partes.append(f"{resultado.archivos_actualizados} actualizados")
        if resultado.archivos_borrados:
            partes.append(f"{resultado.archivos_borrados} borrados")
        if resultado.archivos_sin_cambios:
            partes.append(f"{resultado.archivos_sin_cambios} sin cambios")
        detalle = ", ".join(partes) if partes else "no había nada que hacer"

        texto = (f"Índice de «{carpeta}»: {detalle} ({resultado.segundos}s). "
                 f"En total tengo {actual['archivos']} archivos y {actual['fragmentos']} "
                 f"fragmentos indexados.")
        if not resultado.completo:
            texto += (f" Quedan {resultado.pendientes} archivos por indexar: volvé a "
                      f"llamarme para seguir donde quedé.")
        return texto

    return _con_manejo("code_index", _correr)


register_tool(ToolSpec(
    name="code_index",
    description=(
        "Construye o actualiza el índice de un repositorio habilitado para poder buscar por "
        "significado con code_search. Es incremental: la segunda vez solo mira lo que cambió. "
        "Corré esto ANTES de la primera búsqueda en un proyecto, y de nuevo si hiciste muchos "
        "cambios. En un repositorio grande puede tardar y avisarte que quedan archivos: si "
        "pasa, volvé a llamarla."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Carpeta del proyecto. Opcional si hay una sola habilitada.",
            },
        },
    },
    risk_level=RiskLevel.GREEN,
    invoke=_code_index_invoke,
))


def _code_search_invoke(params: dict) -> str:
    from core.code_index import buscar as buscar_semantico
    from core.workspace_run import carpeta_de_trabajo

    consulta = str(params.get("query") or "").strip()
    if not consulta:
        return f"Necesito qué querés buscar{vocative()}."
    cantidad = _entero(params, "top_k")

    def _correr() -> str:
        from core.code_index import indexar

        carpeta = carpeta_de_trabajo(str(params.get("path") or ""))

        # REQ-035 — el índice se mantiene solo. Comprobar que nada cambió cuesta centésimas
        # (medido: 0.07s para 47 archivos), así que pedirle al usuario que se acuerde de
        # reindexar era trasladarle un trabajo que la máquina hace sola. Con un tope corto:
        # si el repositorio es enorme y falta mucho, se busca con lo que hay y se avisa.
        aviso = ""
        try:
            refresco = indexar(carpeta, tope_segundos=20)
            if refresco.archivos_nuevos or refresco.archivos_actualizados or refresco.archivos_borrados:
                aviso = (f"\n\n[Actualicé el índice antes de buscar: "
                         f"{refresco.archivos_nuevos} nuevos, "
                         f"{refresco.archivos_actualizados} cambiados, "
                         f"{refresco.archivos_borrados} borrados.]")
            if not refresco.completo:
                aviso += (f"\n\n[Faltan {refresco.pendientes} archivos por indexar: corré "
                          f"code_index para terminar y volvé a buscar.]")
        except Exception as e:
            logger.warning(f"no se pudo refrescar el índice antes de buscar: {e}")

        resultados = buscar_semantico(consulta, carpeta, top_k=8 if cantidad is None else cantidad)
        if not resultados:
            return (f"No encontré nada parecido a «{consulta}»." + aviso)

        lineas = [f"Lo más parecido a «{consulta}»:"]
        for r in resultados:
            donde = f"{r.ruta}:{r.linea_inicio}-{r.linea_fin}"
            simbolo = f" [{r.simbolo}]" if r.simbolo else ""
            fragmento = r.texto.strip()
            if len(fragmento) > 400:
                fragmento = fragmento[:400] + " ..."
            lineas.append(f"\n{donde}{simbolo} (parecido {r.puntaje:.2f})\n{fragmento}")
        return "\n".join(lineas) + aviso

    return _con_manejo("code_search", _correr)


register_tool(ToolSpec(
    name="code_search",
    description=(
        "Busca en un repositorio POR SIGNIFICADO, no por texto exacto: sirve para preguntas "
        "como «dónde está la lógica de facturación» aunque el código diga «billing» y nunca "
        "la palabra factura. Para buscar una palabra literal —un nombre de función que ya "
        "sabés— usá file_search, que es exacta y no necesita índice. Requiere haber corrido "
        "code_index antes."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Qué buscás, en lenguaje natural.",
            },
            "path": {
                "type": "string",
                "description": "Carpeta del proyecto. Opcional si hay una sola habilitada.",
            },
            "top_k": {
                "type": "integer",
                "description": "Cuántos resultados devolver (por defecto 8).",
            },
        },
        "required": ["query"],
    },
    risk_level=RiskLevel.GREEN,
    invoke=_code_search_invoke,
))


# ─────────────────────────────────────────────
#  REQ-035 — borrar y mover, la parte del refactor que faltaba
# ─────────────────────────────────────────────

def _file_delete_invoke(params: dict) -> str:
    from core.workspace_files import borrar

    ruta = str(params.get("path") or "")
    if not ruta:
        return f"Necesito qué archivo borrar{vocative()}."
    return _con_manejo("file_delete", lambda: borrar(ruta))


register_tool(ToolSpec(
    name="file_delete",
    description=(
        "Borra un archivo de un repositorio habilitado. Usala cuando un archivo quedó sin "
        "uso después de un refactor. Solo archivos sueltos, no carpetas enteras."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Archivo a borrar."},
        },
        "required": ["path"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_file_delete_invoke,
))


def _file_move_invoke(params: dict) -> str:
    from core.workspace_files import mover

    origen = str(params.get("origen") or params.get("from") or "")
    destino = str(params.get("destino") or params.get("to") or "")
    if not origen or not destino:
        return f"Necesito el archivo de origen y a dónde moverlo{vocative()}."
    return _con_manejo("file_move", lambda: mover(origen, destino))


register_tool(ToolSpec(
    name="file_move",
    description=(
        "Mueve o renombra un archivo dentro de un repositorio habilitado. Los dos extremos "
        "tienen que estar en carpetas habilitadas. Usala para renombrar un módulo o "
        "reorganizar carpetas en un refactor."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "origen": {"type": "string", "description": "Archivo que se mueve."},
            "destino": {"type": "string", "description": "Ruta nueva, con el nombre nuevo."},
        },
        "required": ["origen", "destino"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_file_move_invoke,
))


# ─────────────────────────────────────────────
#  REQ-036 — procesos que no terminan: levantar, mirar y bajar
# ─────────────────────────────────────────────

def _project_start_invoke(params: dict) -> str:
    from core.workspace_procesos import describir, iniciar

    comando = str(params.get("command") or "").strip()
    if not comando:
        return f"Necesito qué programa querés dejar corriendo{vocative()}."

    def _correr() -> str:
        import time

        vivo = iniciar(comando, str(params.get("path") or ""))
        # Un segundo de gracia: la mayoría de los servidores fallan al arrancar (puerto
        # ocupado, import roto) y ese error aparece enseguida. Devolverlo en el acto ahorra
        # una vuelta entera de "arrancó bien" seguida de "no, estaba muerto".
        time.sleep(1.0)
        return describir(vivo, ultimas=20)

    return _con_manejo("project_start", _correr)


register_tool(ToolSpec(
    name="project_start",
    description=(
        "Deja un programa corriendo EN SEGUNDO PLANO dentro de un proyecto habilitado: un "
        "servidor de desarrollo, un watcher, una cola. A diferencia de project_run, no espera "
        "a que termine — te devuelve un identificador para mirar su salida con project_output "
        "y bajarlo con project_stop. Usala cuando el comando no termina solo."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "El comando a dejar corriendo."},
            "path": {
                "type": "string",
                "description": "Carpeta del proyecto. Opcional si hay una sola habilitada.",
            },
        },
        "required": ["command"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_project_start_invoke,
))


def _project_output_invoke(params: dict) -> str:
    from core.workspace_procesos import describir, listar, obtener

    identificador = str(params.get("id") or "").strip()
    lineas = _entero(params, "lineas")

    def _correr() -> str:
        if not identificador:
            vivos = listar()
            if not vivos:
                return "No hay ningún proceso corriendo en segundo plano."
            return "\n\n".join(describir(v, ultimas=10) for v in vivos)

        vivo = obtener(identificador)
        if vivo is None:
            return f"No tengo ningún proceso «{identificador}»."
        return describir(vivo, ultimas=40 if lineas is None else lineas)

    return _con_manejo("project_output", _correr)


register_tool(ToolSpec(
    name="project_output",
    description=(
        "Muestra la salida de un programa que dejaste corriendo con project_start, y si "
        "está vivo o ya terminó. Sin identificador, lista todos los que hay corriendo. Usala "
        "para leer el log del servidor después de pegarle."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Identificador que devolvió project_start. Sin él, lista todos.",
            },
            "lineas": {
                "type": "integer",
                "description": "Cuántas líneas del final mostrar (por defecto 40).",
            },
        },
    },
    # GREEN: es la salida de un proceso que el propio agente levantó con un comando ya
    # confirmado. `project_run` devuelve su salida sin pedir un permiso aparte; partir el
    # arranque de la lectura no puede agregar una confirmación que la versión síncrona no
    # tiene.
    risk_level=RiskLevel.GREEN,
    invoke=_project_output_invoke,
))


def _project_stop_invoke(params: dict) -> str:
    from core.workspace_procesos import detener

    identificador = str(params.get("id") or "").strip()
    if not identificador:
        return f"Necesito el identificador del proceso que querés detener{vocative()}."
    return _con_manejo("project_stop", lambda: detener(identificador))


register_tool(ToolSpec(
    name="project_stop",
    description=(
        "Detiene un programa que dejaste corriendo con project_start. Bajá el servidor "
        "cuando terminaste: no queda corriendo solo porque sí."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Identificador del proceso."},
        },
        "required": ["id"],
    },
    # GREEN: solo puede detener procesos que el propio agente levantó, y detenerlos es lo
    # ordenado. Pedir confirmación para limpiar sería premiar dejar basura corriendo.
    risk_level=RiskLevel.GREEN,
    invoke=_project_stop_invoke,
))


# ---------------------------------------------------------------------------
# REQ-038 — el navegador: ver la página y actuar sobre ella por el nombre de
# cada cosa, en vez de estimar coordenadas sobre una captura.
# ---------------------------------------------------------------------------

def _browser_open_invoke(params: dict) -> str:
    from os_integration.navegador import abrir

    url = str(params.get("url") or "").strip()
    if not url:
        return f"Necesito la dirección que querés que abra{vocative()}."
    return _con_manejo("browser_open", lambda: abrir(url))


register_tool(ToolSpec(
    name="browser_open",
    description=(
        "Abre una dirección web en el navegador del usuario y espera a poder LEER la "
        "página. Te dice cuántos elementos quedaron disponibles para actuar; a partir de "
        "ahí usá 'browser_page' para ver qué hay y 'browser_act' para pulsar o escribir. "
        "Es la puerta de entrada a cualquier trámite web de varios pasos."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Dirección a abrir."},
        },
        "required": ["url"],
    },
    # GREEN: abrir una dirección es lo mismo que ya hacen `open_url` y `search_google`, y
    # el usuario ve la página aparecer. Lo que se haga DESPUÉS sobre ella es `browser_act`,
    # que sí es amarillo.
    risk_level=RiskLevel.GREEN,
    invoke=_browser_open_invoke,
))


def _browser_page_invoke(params: dict) -> str:
    from os_integration.navegador import resumen_de_pagina

    try:
        maximo = int(params.get("maximo") or 40)
    except (TypeError, ValueError):
        maximo = 40
    return _con_manejo("browser_page", lambda: resumen_de_pagina(max(1, min(maximo, 200))))


register_tool(ToolSpec(
    name="browser_page",
    description=(
        "Cuenta qué hay en la página que el usuario tiene abierta: enlaces, campos y "
        "botones, con su nombre real. Es lo que te permite decidir el siguiente paso de un "
        "trámite sin adivinar. Si no ves lo que buscás, pedí más elementos con 'maximo' o "
        "desplazá la página antes."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "maximo": {
                "type": "integer",
                "description": "Cuántos elementos listar (por defecto 40).",
            },
        },
    },
    # GREEN: mira, no toca. Mismo criterio que `pc_look`, que ya lee la ventana activa.
    risk_level=RiskLevel.GREEN,
    invoke=_browser_page_invoke,
))


def _browser_act_invoke(params: dict) -> str:
    from os_integration.navegador import accionar

    objetivo = str(params.get("objetivo") or "").strip()
    if not objetivo:
        return f"Necesito el nombre de lo que querés que pulse en la página{vocative()}."
    texto = params.get("texto")
    texto = str(texto) if texto not in (None, "") else None
    return _con_manejo("browser_act", lambda: accionar(objetivo, texto))


register_tool(ToolSpec(
    name="browser_act",
    description=(
        "Hace clic en un elemento de la página POR SU NOMBRE —el que devuelve "
        "'browser_page'—, y si le pasás 'texto', lo escribe ahí. Encadenando llamadas se "
        "completa un formulario o un trámite entero. No uses coordenadas: el nombre se "
        "resuelve contra la página viva en el momento del clic."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "objetivo": {
                "type": "string",
                "description": "Nombre del enlace, botón o campo, tal como lo ves en la página.",
            },
            "texto": {
                "type": "string",
                "description": "Qué escribir ahí. Vacío para solo hacer clic.",
            },
        },
        "required": ["objetivo"],
    },
    # YELLOW: actúa sobre la sesión del usuario, con sus cuentas abiertas. Un clic puede
    # comprar, borrar o enviar. Mismo nivel que `pc_click` y `pc_type`, y la confirmación
    # muestra el objetivo y el texto (`_DETAILS_ALLOWED_KEYS`) para que el sí no sea a ciegas.
    risk_level=RiskLevel.YELLOW,
    invoke=_browser_act_invoke,
))


def _browser_text_invoke(params: dict) -> str:
    from os_integration.navegador import MAX_CARACTERES_DE_TEXTO, texto_de_pagina

    try:
        tope = int(params.get("maximo") or MAX_CARACTERES_DE_TEXTO)
    except (TypeError, ValueError):
        tope = MAX_CARACTERES_DE_TEXTO
    return _con_manejo("browser_text", lambda: texto_de_pagina(tope))


register_tool(ToolSpec(
    name="browser_text",
    description=(
        "Lee el TEXTO de la página abierta, no solo lo que se puede pulsar. Úsala cuando "
        "el usuario pregunte por el contenido: resumir un artículo, buscar un dato dentro "
        "de la página, comparar dos cosas que dice. Sirve también para un PDF abierto en "
        "el navegador. Si querés pulsar algo, esa es 'browser_page' + 'browser_act'."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "maximo": {
                "type": "integer",
                "description": "Tope de caracteres a devolver (por defecto 6000).",
            },
        },
    },
    # GREEN: es leer lo que el usuario ya tiene en pantalla. Mismo criterio que `pc_look`.
    risk_level=RiskLevel.GREEN,
    invoke=_browser_text_invoke,
))


def _browser_tabs_invoke(_params: dict) -> str:
    from os_integration.navegador import listar_pestanas

    return _con_manejo("browser_tabs", listar_pestanas)


register_tool(ToolSpec(
    name="browser_tabs",
    description=(
        "Lista las pestañas abiertas del navegador y marca cuál se está viendo. Úsala "
        "cuando el usuario hable de algo que tiene abierto en otra pestaña, o antes de "
        "cambiarte a una."
    ),
    parameters_schema={"type": "object", "properties": {}},
    # GREEN: mira, no toca.
    risk_level=RiskLevel.GREEN,
    invoke=_browser_tabs_invoke,
))


def _browser_tab_switch_invoke(params: dict) -> str:
    from os_integration.navegador import cambiar_de_pestana

    objetivo = str(params.get("objetivo") or "").strip()
    if not objetivo:
        return f"Necesito el nombre de la pestaña a la que querés ir{vocative()}."
    return _con_manejo("browser_tab_switch", lambda: cambiar_de_pestana(objetivo))


register_tool(ToolSpec(
    name="browser_tab_switch",
    description=(
        "Pone delante una pestaña por su nombre (el que devuelve 'browser_tabs'). Después "
        "de cambiar, 'browser_page' y 'browser_text' leen esa pestaña."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "objetivo": {"type": "string", "description": "Nombre de la pestaña."},
        },
        "required": ["objetivo"],
    },
    # GREEN: cambia lo que se ve, no toca el contenido de ninguna página — y se hace por
    # UI Automation, sin ratón y sin robarle el foco a lo que el usuario esté haciendo.
    risk_level=RiskLevel.GREEN,
    invoke=_browser_tab_switch_invoke,
))


def _browser_tab_close_invoke(params: dict) -> str:
    from os_integration.navegador import cerrar_pestana

    objetivo = str(params.get("objetivo") or "").strip()
    if not objetivo:
        return f"Necesito el nombre de la pestaña que querés cerrar{vocative()}."
    return _con_manejo("browser_tab_close", lambda: cerrar_pestana(objetivo))


register_tool(ToolSpec(
    name="browser_tab_close",
    description=(
        "Cierra una pestaña por su nombre. Cerrá solo lo que el usuario te pida cerrar: "
        "una pestaña puede tener un formulario a medio llenar."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "objetivo": {"type": "string", "description": "Nombre de la pestaña a cerrar."},
        },
        "required": ["objetivo"],
    },
    # YELLOW: lo que se pierde al cerrar no vuelve — un formulario a medio llenar, un
    # borrador. Es el mismo criterio que "cerrar aplicaciones" en las reglas del proyecto, y
    # la confirmación dice qué pestaña es.
    risk_level=RiskLevel.YELLOW,
    invoke=_browser_tab_close_invoke,
))


# ---------------------------------------------------------------------------
# REQ-039 — investigar: varias fuentes a la vez, y con qué sostener cada dato.
# ---------------------------------------------------------------------------

def _research_invoke(params: dict) -> str:
    from core.investigacion import MAX_FUENTES, formatear, investigar

    pregunta = str(params.get("pregunta") or params.get("query") or "").strip()
    if not pregunta:
        return f"Necesito saber qué querés que investigue{vocative()}."

    crudas = params.get("consultas") or []
    if isinstance(crudas, str):
        crudas = [crudas]
    consultas = [str(c).strip() for c in crudas if str(c).strip()]

    try:
        cuantas = int(params.get("max_fuentes") or MAX_FUENTES)
    except (TypeError, ValueError):
        cuantas = MAX_FUENTES

    return _con_manejo(
        "research",
        lambda: formatear(investigar(pregunta, consultas, cuantas)),
    )


register_tool(ToolSpec(
    name="research",
    description=(
        "Investiga una pregunta: busca con varias consultas a la vez, lee las páginas en "
        "paralelo y devuelve un dosier con las fuentes numeradas, su dominio y su fecha. "
        "Marca cuáles repiten el contenido de otra —cinco medios copiando el mismo "
        "teletipo no son cinco confirmaciones— para que no cuentes como respaldo lo que es "
        "una sola fuente.\n"
        "Úsala en vez de encadenar 'web_search' + varios 'web_read' siempre que la "
        "pregunta necesite contrastar: en una llamada hace lo que en esas te cuesta cinco, "
        "y te quedan vueltas para pensar.\n"
        "Pasá en 'consultas' las búsquedas concretas que responden la pregunta —"
        "descomponerla es tuyo, no de la herramienta—. Con la respuesta, cita cada dato "
        "con el número de su fuente y decí en qué no coinciden."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "pregunta": {
                "type": "string",
                "description": "Qué hay que averiguar, tal como lo entendiste.",
            },
            "consultas": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Búsquedas concretas (hasta 4). Si no las pasás, se busca la pregunta "
                    "tal cual, que casi siempre da peores resultados."
                ),
            },
            "max_fuentes": {
                "type": "integer",
                "description": "Cuántas fuentes leer (por defecto 5, máximo 10).",
            },
        },
        "required": ["pregunta"],
    },
    # GREEN: leer información pública, igual que `web_search` y `web_read`, de las que sale
    # todo lo que hace. No escribe nada y las descargas pasan por la misma guarda anti-SSRF.
    risk_level=RiskLevel.GREEN,
    invoke=_research_invoke,
))


def _pc_act_invoke(params: dict) -> str:
    """Pulsa o escribe en un control de la ventana activa por su NOMBRE."""
    from os_integration.ui_tree import operar

    objetivo = str(params.get("objetivo") or "").strip()
    if not objetivo:
        return f"Necesito el nombre de lo que querés que pulse{vocative()}."
    texto = params.get("texto")
    texto = str(texto) if texto not in (None, "") else None
    return _con_manejo("pc_act", lambda: operar(objetivo, texto))


register_tool(ToolSpec(
    name="pc_act",
    description=(
        "Pulsa un botón, una pestaña o un elemento de la ventana que el usuario tiene "
        "delante POR SU NOMBRE —el que devuelve 'pc_look'—, y si le pasás 'texto', lo "
        "escribe ahí. Preferila a 'pc_find' + 'pc_click': el nombre se resuelve contra la "
        "pantalla viva en el momento de pulsar, así que no hay hueco entre mirar y actuar, "
        "y no depende de acertarle a unas coordenadas. Para una página web en el "
        "navegador, usá 'browser_act'."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "objetivo": {
                "type": "string",
                "description": "Nombre del botón, campo o elemento, tal como se ve.",
            },
            "texto": {
                "type": "string",
                "description": "Qué escribir ahí. Vacío para solo pulsar.",
            },
        },
        "required": ["objetivo"],
    },
    # YELLOW: actúa sobre la ventana del usuario, y quien da la orden puede no estar
    # delante. Mismo nivel que `pc_click` y `pc_type`, y la confirmación muestra el
    # objetivo y el texto (`_DETAILS_ALLOWED_KEYS`).
    risk_level=RiskLevel.YELLOW,
    invoke=_pc_act_invoke,
))


def _pc_read_invoke(params: dict) -> str:
    """Lee el texto DIBUJADO en pantalla con el OCR de Windows: local, sin modelo, sin red."""
    from os_integration.ocr import disponible, leer_ventana

    if not disponible():
        return ("Este equipo no tiene el reconocimiento de texto de Windows disponible, así "
                "que no puedo leer lo que hay dibujado. Usá 'pc_look' para mirar la captura.")

    hwnd = None
    if not params.get("toda_la_pantalla"):
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetForegroundWindow() or None
        except Exception as e:
            logger.debug(f"no se pudo tomar la ventana activa para el OCR: {e}")

    texto = _con_manejo("pc_read", lambda: leer_ventana(hwnd))
    if not texto or not texto.strip():
        return ("No reconocí texto en lo que hay en pantalla. Si es una imagen sin letras o "
                "el texto es muy pequeño, 'pc_look' puede describirla.")
    tope = 6000
    if len(texto) > tope:
        texto = texto[:tope] + "\n\n[...cortado]"
    return f"Texto leído de la pantalla (por OCR: puede tener errores de lectura):\n\n{texto}"


register_tool(ToolSpec(
    name="pc_read",
    description=(
        "Lee el texto que hay DIBUJADO en la ventana activa —o en toda la pantalla— con el "
        "reconocimiento de texto de Windows. Úsala cuando 'pc_look' o 'browser_text' no "
        "encuentren controles ni texto: un mapa, un gráfico, un lienzo, un vídeo con "
        "subtítulos, una imagen con texto, un escritorio remoto, un juego. No necesita "
        "modelo con visión ni internet. Lo que devuelve es lo que se ve, con posibles "
        "errores de lectura: no sirve para saber dónde pulsar, sirve para saber qué dice."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "toda_la_pantalla": {
                "type": "boolean",
                "description": "True para leer la pantalla completa en vez de la ventana activa.",
            },
        },
    },
    # GREEN: mira, no toca. Mismo criterio que `pc_look` y `pc_screenshot`. Lo que se lee
    # ya está en la pantalla del usuario; que no salga de ahí depende de a quién se le
    # cuente, y eso lo decide el canal como con cualquier lectura.
    risk_level=RiskLevel.GREEN,
    invoke=_pc_read_invoke,
))


# ---------------------------------------------------------------------------
# REQ-040 — producir documentos de verdad: Word, Excel, PowerPoint, PDF y más.
# ---------------------------------------------------------------------------

def _con_documento(nombre_accion: str, operacion) -> str:
    """Corre una operación de documentos devolviendo SIEMPRE texto que el modelo entienda."""
    from core.documentos import DocumentoRechazado

    try:
        return operacion().describir()
    except DocumentoRechazado as e:
        return str(e)
    except Exception as e:
        logger.error(f"'{nombre_accion}' falló inesperadamente: {type(e).__name__}: {e}")
        return (f"No pude generar el archivo: {type(e).__name__}. Revisá que el contenido "
                f"tenga la forma esperada.")


_INSTRUCCION_CONTENIDO = (
    "El contenido lo escribís VOS, completo: todas las secciones con su texto real, todas "
    "las filas, todas las diapositivas. Nada de «[insertar aquí]», «lorem ipsum» ni "
    "«por definir» — se rechaza. Si te falta información, preguntá antes o investigá; no "
    "dejes huecos."
)


def _document_create_invoke(params: dict) -> str:
    from core.documentos import crear_documento

    nombre = str(params.get("nombre") or "").strip()
    if not nombre:
        return f"Necesito el nombre del archivo, con su extensión{vocative()}."
    return _con_documento("document_create", lambda: crear_documento(
        nombre, params.get("contenido"), plantilla=params.get("plantilla"),
        reemplazos=params.get("reemplazos") or {}, carpeta=params.get("carpeta"),
        estilo=params.get("estilo"),
    ))


register_tool(ToolSpec(
    name="document_create",
    description=(
        "Crea un documento de texto real: .docx (Word), .pdf, .md, .html o .txt, con "
        "título, encabezados, párrafos, listas, tablas, imágenes y citas. Con 'plantilla' "
        "(un .docx del usuario) escribe DENTRO de ella: conserva membrete, pies, márgenes y "
        "estilos; y con 'reemplazos' rellena sus marcadores ({{cliente}}, [FECHA]) "
        "conservando el formato. Antes de usar una plantilla, mirala con 'document_inspect'; "
        "si en ella queda algún marcador sin valor, el documento se rechaza: pedile el dato "
        "al usuario. Con 'estilo' seguís lo que el usuario pida de aspecto sin plantilla "
        "(o encima de ella): fuente, tamaño, color de títulos, márgenes, orientación, "
        "encabezado, pie, logo, número de página. Un .pdf se hace en Word y se convierte, "
        "así que se ve igual que el Word. " + _INSTRUCCION_CONTENIDO
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "nombre": {"type": "string",
                       "description": "Nombre del archivo con extensión: 'informe.docx', 'acta.pdf'."},
            "contenido": {
                "description": (
                    "Objeto con 'titulo', 'subtitulo', 'autor', 'fecha' y 'bloques': lista de "
                    "{tipo: titulo|parrafo|lista|tabla|imagen|cita|salto, ...}. Un 'titulo' "
                    "lleva 'texto' y 'nivel' (1-3); 'parrafo' y 'cita' llevan 'texto'; 'lista' "
                    "lleva 'items' (una lista dentro es un subnivel) y 'numerada'; 'tabla' lleva "
                    "'encabezados', 'filas' y 'titulo'; 'imagen' lleva 'ruta', 'ancho_cm' y "
                    "'pie'. También se acepta un texto en Markdown."
                ),
            },
            "plantilla": {"type": "string",
                          "description": "Ruta a un .docx cuyo formato hay que seguir (opcional)."},
            "reemplazos": {"type": "object",
                           "description": "Marcadores de la plantilla y su valor: {'{{cliente}}': 'Agro SAS'}."},
            "estilo": {
                "type": "object",
                "description": (
                    "Aspecto pedido por el usuario (todo opcional): 'fuente' ('Arial'), 'tamano' "
                    "(11), 'fuente_titulos', 'color_titulos' y 'color_texto' (hex o nombre: "
                    "'azul oscuro', 'verde'), 'margenes_cm' (2 o {superior, inferior, izquierdo, "
                    "derecho}), 'orientacion' ('vertical'|'horizontal'), 'encabezado' y 'pie' "
                    "(texto), 'logo' (ruta de imagen; va en el encabezado, 'logo_posicion' "
                    "izquierda|centro|derecha, 'logo_ancho_cm'), 'numeracion' (true: «Página N "
                    "de M»), 'justificado' (true), 'interlineado' (1.15)."
                ),
            },
            "carpeta": {"type": "string",
                        "description": "Dónde guardarlo. Vacío = el Escritorio."},
        },
        "required": ["nombre", "contenido"],
    },
    # YELLOW: crea un archivo en el equipo del usuario. Mismo nivel que `write_file_direct`
    # y `file_write`; la confirmación muestra el nombre (`nombre` en `_DETAILS_ALLOWED_KEYS`).
    risk_level=RiskLevel.YELLOW,
    invoke=_document_create_invoke,
))


def _spreadsheet_create_invoke(params: dict) -> str:
    from core.documentos import crear_hoja

    nombre = str(params.get("nombre") or "").strip()
    if not nombre:
        return f"Necesito el nombre del archivo, con su extensión{vocative()}."
    return _con_documento("spreadsheet_create", lambda: crear_hoja(
        nombre, params.get("contenido"), plantilla=params.get("plantilla"),
        carpeta=params.get("carpeta"), estilo=params.get("estilo"),
    ))


register_tool(ToolSpec(
    name="spreadsheet_create",
    description=(
        "Crea una hoja de cálculo real: .xlsx (Excel) o .csv. Varias hojas, encabezados con "
        "formato, filas, fórmulas (las celdas que empiezan por '='; podés escribirlas en "
        "español: '=SUMA(B2:B4)', '=SI(B2>5;\"alto\";\"bajo\")', '=B2*0,19'), fila de "
        "totales, formatos de número por columna y un gráfico de barras, líneas o torta. "
        "Los números escritos a la colombiana ('1.250.000', '12,5') se guardan como números. "
        "Con 'plantilla' (un .xlsx del usuario) escribe en sus hojas conservando su formato: "
        "si la hoja ya tiene los encabezados, no los repite y los datos van debajo; el "
        "resultado dice en qué fila empiezan los datos, para que las fórmulas apunten bien. "
        "Con 'estilo' seguís lo que el usuario pida: fuente, tamaño, color del encabezado. "
        + _INSTRUCCION_CONTENIDO
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "nombre": {"type": "string", "description": "'ventas.xlsx' o 'clientes.csv'."},
            "contenido": {
                "description": (
                    "Objeto con 'hojas': lista de {nombre, titulo (fila de título arriba del "
                    "encabezado; entonces el encabezado va en la fila 3 y los datos desde la 4), "
                    "encabezados, filas, totales (bool), formatos ({'B': '#,##0', 'D': '0.0%'}), "
                    "grafico ({tipo: barras|lineas|torta, titulo, columnas (nombres de "
                    "encabezado), categorias}), desde ('C5': la celda donde va la PRIMERA FILA "
                    "DE DATOS en una plantilla)}. También se acepta una lista de filas o una "
                    "lista de registros."
                ),
            },
            "plantilla": {"type": "string", "description": "Ruta a un .xlsx a seguir (opcional)."},
            "estilo": {
                "type": "object",
                "description": (
                    "Aspecto pedido por el usuario (opcional): 'fuente', 'tamano', "
                    "'color_encabezado' y 'color_texto_encabezado' (hex o nombre), "
                    "'color_titulos', 'bordes' (false para quitarlos)."
                ),
            },
            "carpeta": {"type": "string", "description": "Dónde guardarlo. Vacío = el Escritorio."},
        },
        "required": ["nombre", "contenido"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_spreadsheet_create_invoke,
))


def _presentation_create_invoke(params: dict) -> str:
    from core.documentos import crear_presentacion

    nombre = str(params.get("nombre") or "").strip()
    if not nombre:
        return f"Necesito el nombre del archivo, con su extensión{vocative()}."
    return _con_documento("presentation_create", lambda: crear_presentacion(
        nombre, params.get("contenido"), plantilla=params.get("plantilla"),
        reemplazos=params.get("reemplazos") or {}, carpeta=params.get("carpeta"),
        tema=params.get("tema"), estilo=params.get("estilo"),
    ))


register_tool(ToolSpec(
    name="presentation_create",
    description=(
        "Crea una presentación real: .pptx (PowerPoint) o su .pdf. Portada, diapositivas con "
        "viñetas (y subniveles), tablas, imágenes y notas del orador. Sin plantilla aplica un "
        "tema de diseño de Office ('tema': Retrospect, Facet, Ion, Integral, Wisp...). Con "
        "'plantilla' (un .pptx del usuario) usa su tema y sus diseños, y con 'reemplazos' "
        "rellena sus marcadores (si queda alguno sin valor, se rechaza). Con 'estilo' seguís "
        "lo que el usuario pida: fuente, colores, logo en cada diapositiva, pie, número. "
        + _INSTRUCCION_CONTENIDO
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "nombre": {"type": "string", "description": "'resultados.pptx' o 'propuesta.pdf'."},
            "contenido": {
                "description": (
                    "Objeto con 'titulo', 'subtitulo' y 'diapositivas': lista de {titulo, "
                    "puntos (lista; una lista dentro es un subnivel), texto, tabla "
                    "({encabezados, filas}), imagen (ruta), notas}."
                ),
            },
            "plantilla": {"type": "string", "description": "Ruta a un .pptx a seguir (opcional)."},
            "reemplazos": {"type": "object", "description": "Marcadores de la plantilla y su valor."},
            "tema": {"type": "string", "description": "Tema de diseño de Office (sin plantilla)."},
            "estilo": {
                "type": "object",
                "description": (
                    "Aspecto pedido por el usuario (opcional): 'fuente', 'color_titulos', "
                    "'color_texto' (hex o nombre), 'logo' (ruta de imagen, esquina superior "
                    "derecha; 'logo_ancho_cm'), 'pie' (texto abajo), 'numeracion' (true: n / total)."
                ),
            },
            "carpeta": {"type": "string", "description": "Dónde guardarla. Vacío = el Escritorio."},
        },
        "required": ["nombre", "contenido"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_presentation_create_invoke,
))


def _file_create_invoke(params: dict) -> str:
    from core.documentos import crear_archivo

    nombre = str(params.get("nombre") or "").strip()
    if not nombre:
        return f"Necesito el nombre del archivo, con su extensión{vocative()}."
    return _con_documento("file_create", lambda: crear_archivo(
        nombre, params.get("contenido"), carpeta=params.get("carpeta"),
    ))


register_tool(ToolSpec(
    name="file_create",
    description=(
        "Crea un archivo de cualquier otra extensión con el contenido que le pases: .json "
        "(con sangría), .sql, .py, .yaml, .xml, .ini, .bat, lo que sea. Para Word, Excel, "
        "PowerPoint y PDF usá las herramientas específicas. Se guarda en el Escritorio o en "
        "la carpeta que indiques; nunca pisa un archivo existente. " + _INSTRUCCION_CONTENIDO
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "nombre": {"type": "string", "description": "Nombre con extensión."},
            "contenido": {"description": "Texto del archivo, o un objeto si es .json."},
            "carpeta": {"type": "string", "description": "Dónde guardarlo. Vacío = el Escritorio."},
        },
        "required": ["nombre", "contenido"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_file_create_invoke,
))


def _document_inspect_invoke(params: dict) -> str:
    from core.documentos import inspeccionar

    ruta = str(params.get("ruta") or params.get("path") or "").strip()
    if not ruta:
        return f"Necesito la ruta del documento que querés que mire{vocative()}."
    return _con_manejo("document_inspect", lambda: inspeccionar(ruta))


register_tool(ToolSpec(
    name="document_inspect",
    description=(
        "Mira cómo está hecha una plantilla o un documento de Office (.docx, .xlsx, .pptx): "
        "qué estilos usa, qué encabezados y pies tiene, qué hojas o diseños, y qué "
        "marcadores trae para rellenar ({{cliente}}, [FECHA]). Usala ANTES de generar algo "
        "sobre una plantilla, para seguirla bien en vez de adivinar."
    ),
    parameters_schema={
        "type": "object",
        "properties": {"ruta": {"type": "string", "description": "Ruta al archivo."}},
        "required": ["ruta"],
    },
    # GREEN: lee la estructura de un archivo del usuario. Mismo criterio que `file_read`.
    risk_level=RiskLevel.GREEN,
    invoke=_document_inspect_invoke,
))


def _document_to_pdf_invoke(params: dict) -> str:
    from core.documentos import convertir_a_pdf

    ruta = str(params.get("ruta") or params.get("path") or "").strip()
    if not ruta:
        return f"Necesito la ruta del documento que querés convertir{vocative()}."
    return _con_documento("document_to_pdf", lambda: convertir_a_pdf(ruta, params.get("carpeta")))


register_tool(ToolSpec(
    name="document_to_pdf",
    description=(
        "Convierte a PDF un archivo existente de Word, Excel o PowerPoint usando el propio "
        "Office, así que el PDF se ve exactamente igual. El PDF queda junto al original (o "
        "en 'carpeta') y no pisa nada."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "ruta": {"type": "string", "description": "Ruta al .docx, .xlsx o .pptx."},
            "carpeta": {"type": "string", "description": "Dónde dejar el PDF (opcional)."},
        },
        "required": ["ruta"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_document_to_pdf_invoke,
))


def _document_edit_invoke(params: dict) -> str:
    from core.documentos import editar_documento

    ruta = str(params.get("ruta") or params.get("path") or "").strip()
    if not ruta:
        return f"Necesito la ruta del documento que querés editar{vocative()}."
    return _con_documento("document_edit", lambda: editar_documento(
        ruta, params.get("cambios") or {}, en_sitio=bool(params.get("en_sitio")),
        carpeta=params.get("carpeta"), estilo=params.get("estilo"),
    ))


register_tool(ToolSpec(
    name="document_edit",
    description=(
        "Edita un documento de Office que YA existe (.docx, .xlsx, .pptx) sin rehacerlo. "
        "Word: 'reemplazos' {texto: nuevo} conservando el formato, 'agregar' (bloques o "
        "Markdown) con 'despues_de' (texto del párrafo tras el que va), 'quitar' [textos de "
        "párrafos]. Excel: 'celdas' {'Hoja!B4': valor}, 'agregar' {hoja: [filas]}, "
        "'reemplazos'. PowerPoint: 'reemplazos', 'agregar' [diapositivas], 'quitar' "
        "[títulos o números]. Con 'estilo' le cambiás el ASPECTO a lo que ya está escrito "
        "(«ponele el membrete», «pasalo a horizontal con números de página», «letra Arial»): "
        "vale por sí solo, sin tocar el texto. Por defecto deja el original intacto y guarda "
        "una copia editada al lado; con 'en_sitio' sobrescribe el original."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "ruta": {"type": "string", "description": "Ruta al .docx, .xlsx o .pptx."},
            "cambios": {"description": "Objeto con los cambios, según el tipo de archivo."},
            "estilo": {
                "type": "object",
                "description": (
                    "Aspecto nuevo (opcional; solo con esto ya es un cambio válido). Word: "
                    "'fuente', 'tamano', 'fuente_titulos', 'color_titulos', 'color_texto', "
                    "'margenes_cm', 'orientacion', 'encabezado', 'pie', 'logo', 'numeracion', "
                    "'justificado'. Excel: 'fuente', 'tamano' (a lo que ya está escrito, "
                    "conservando negritas) y 'color_encabezado'. PowerPoint: 'fuente', "
                    "'color_titulos', 'color_texto', 'logo', 'pie', 'numeracion' — se aplica "
                    "a todas las diapositivas y no duplica el logo ni el pie si ya los tenía."
                ),
            },
            "en_sitio": {"type": "boolean",
                         "description": "True para sobrescribir el original (sin deshacer)."},
            "carpeta": {"type": "string", "description": "Dónde dejar la copia editada (opcional)."},
        },
        "required": ["ruta"],
    },
    # YELLOW: modifica un documento del usuario. La confirmación muestra la ruta.
    risk_level=RiskLevel.YELLOW,
    invoke=_document_edit_invoke,
))


# ── REQ-043 — servidores MCP desde el chat, sin editar JSON ─────────────────────────────
#
# El soporte MCP existía completo (`core/mcp_manager.py`) pero solo se manejaba editando
# `config.json` y `mcp_allowlist.json` a mano. Estas seis herramientas son la versión
# "decírselo al agente" (mismo criterio que `workspace_add_folder`, REQ-030). La lógica vive
# en `core/mcp_config.py`; acá solo se traduce entre el modelo y ese módulo.
#
# Seguridad: declarar un servidor stdio es habilitar un programa que ejecuta código en la
# máquina. Por eso `mcp_add_server` es AMARILLA con el comando completo a la vista (`command`
# está en `_DETAILS_ALLOWED_KEYS`), igual que `terminal_run_command`; y las seis son solo
# de escritorio (`DESKTOP_ONLY_ACTIONS`): esto se decide delante del computador, nunca por
# un mensaje remoto. Ningún secreto pasa por acá: `env`/`headers` solo aceptan `${VARIABLE}`.

def _mcp_list_invoke(params: dict) -> str:
    from core.mcp_config import listar_servidores

    filas = listar_servidores()
    if not filas:
        return (
            f"No hay ningún servidor MCP declarado{vocative()}. Para agregar uno, decime su "
            f"nombre y el comando que lo arranca (o su URL)."
        )
    lineas = []
    for f in filas:
        if not f["enabled"]:
            estado = "deshabilitado"
        elif not f["conectado"]:
            estado = "desconectado"
        elif not f["herramientas"]:
            estado = "conectado, sin herramientas habilitadas"
        else:
            estado = f"conectado, {len(f['herramientas'])} herramienta(s) habilitada(s)"
        lineas.append(f"- {f['nombre']} ({f['transporte']}: {f['destino']}) — {estado}")
        if f["permitidas"]:
            lineas.append(
                f"    permitidas: {', '.join(f['permitidas'])} | canales: {', '.join(f['canales'])}"
            )
        if f["herramientas"]:
            lineas.append(f"    habilitadas ahora: {', '.join(f['herramientas'])}")
        faltan = [v["nombre"] for v in f["variables"] if not v["origen"]]
        if faltan:
            lineas.append(f"    variables sin definir: {', '.join(faltan)}")
    return "Servidores MCP:\n" + "\n".join(lineas)


register_tool(ToolSpec(
    name="mcp_list_servers",
    description=(
        "Lista los servidores MCP declarados: si están conectados, qué herramientas tienen "
        "habilitadas y qué variables les faltan. Usala cuando el usuario pregunte qué "
        "servidores o conexiones MCP tiene, o antes de agregar uno para no repetirlo."
    ),
    parameters_schema={"type": "object", "properties": {}},
    risk_level=RiskLevel.GREEN,
    invoke=_mcp_list_invoke,
))


def _mcp_probe_invoke(params: dict) -> str:
    from core.mcp_manager import probar_servidor

    nombre = str(params.get("name") or "").strip()
    if not nombre:
        return f"Necesito el nombre del servidor a probar{vocative()}."
    return probar_servidor(nombre)


register_tool(ToolSpec(
    name="mcp_probe_server",
    description=(
        "Prueba un servidor MCP ya declarado: se conecta, dice si respondió y lista TODAS las "
        "herramientas que publica, marcando cuáles están permitidas y cuáles bloqueadas. No "
        "cambia nada. Usala para diagnosticar uno que no anda o para ver qué ofrece antes de "
        "habilitar herramientas."
    ),
    parameters_schema={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Nombre del servidor."}},
        "required": ["name"],
    },
    risk_level=RiskLevel.GREEN,
    invoke=_mcp_probe_invoke,
))


def _mcp_add_invoke(params: dict) -> str:
    from core.mcp_config import MCPConfigRechazada, agregar_servidor, aplicar_y_resumir

    try:
        # Sin `args` aparte, a propósito: el comando va COMPLETO en `command`, que es lo que
        # muestra el modal. Un `args` que el modal no muestra sería confirmar a ciegas.
        agregar_servidor(
            params.get("name"),
            command=params.get("command"),
            url=params.get("url"),
            env=params.get("env"),
            headers=params.get("headers"),
        )
    except MCPConfigRechazada as e:
        logger.warning(f"'mcp_add_server' rechazada: {e}")
        return str(e)
    except OSError as e:
        logger.error(f"'mcp_add_server' falló al guardar: {e}")
        return f"No pude guardar la configuración: {e}"
    return aplicar_y_resumir(params.get("name"))


register_tool(ToolSpec(
    name="mcp_add_server",
    description=(
        "Declara y conecta un servidor MCP nuevo para que sus herramientas queden "
        "disponibles. Un servidor local se define con 'command' (el comando COMPLETO que lo "
        "arranca, por ejemplo 'npx -y @notionhq/notion-mcp-server'); uno remoto con 'url'. "
        "Si necesita un token, ponelo en 'env' (o 'headers') SOLO como referencia "
        "'${NOMBRE_VARIABLE}': nunca pidas ni escribas el valor del secreto, el usuario lo "
        "pega en Configuración → Conexiones. Al terminar te dice qué herramientas publica: "
        "ninguna queda habilitada hasta que el usuario elija cuáles (mcp_allow_tools)."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string",
                     "description": "Nombre corto en minúsculas: 'notion', 'github'."},
            "command": {"type": "string",
                        "description": "Comando completo que arranca el servidor local (stdio)."},
            "url": {"type": "string", "description": "URL del servidor remoto (HTTP)."},
            "env": {"type": "object",
                    "description": ("Variables de entorno para el comando, solo como "
                                    "referencias: {'NOTION_TOKEN': '${NOTION_TOKEN}'}.")},
            "headers": {"type": "object",
                        "description": "Cabeceras HTTP: {'Authorization': '${MI_TOKEN}'}."},
        },
        "required": ["name"],
    },
    # YELLOW: arranca un programa en la máquina del usuario (el servidor stdio). La
    # confirmación muestra `name` y `command`/`url`, que están en `_DETAILS_ALLOWED_KEYS`.
    risk_level=RiskLevel.YELLOW,
    invoke=_mcp_add_invoke,
))


def _mcp_allow_invoke(params: dict) -> str:
    from core.mcp_config import MCPConfigRechazada, aplicar_y_resumir, permitir_herramientas

    try:
        escrito = permitir_herramientas(
            params.get("name"), params.get("herramientas") or [], params.get("canales"),
        )
    except MCPConfigRechazada as e:
        logger.warning(f"'mcp_allow_tools' rechazada: {e}")
        return str(e)
    except OSError as e:
        logger.error(f"'mcp_allow_tools' falló al guardar: {e}")
        return f"No pude guardar la lista de herramientas: {e}"
    aviso = ""
    if "*" in escrito["tools"]:
        aviso = (
            " Ojo: con '*' se acepta CUALQUIER herramienta que el servidor publique, incluidas "
            "las que agregue mañana."
        )
    return aplicar_y_resumir(params.get("name")) + aviso


register_tool(ToolSpec(
    name="mcp_allow_tools",
    description=(
        "Habilita qué herramientas de un servidor MCP puede usar el agente (las que no se "
        "nombran quedan bloqueadas) y desde qué canales. 'herramientas' son nombres tal como "
        "los publica el servidor o patrones ('search', 'read_*'); reemplaza la lista anterior. "
        "'canales' por defecto es solo escritorio; se puede sumar telegram, discord, voice o "
        "email (por correo solo entran las herramientas de solo lectura). "
        "Usala después de mcp_add_server, cuando el usuario haya dicho cuáles quiere."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Nombre del servidor."},
            "herramientas": {"type": "array", "items": {"type": "string"},
                             "description": "Nombres o patrones de herramientas a permitir."},
            "canales": {"type": "array", "items": {"type": "string"},
                        "description": ("Canales: desktop, telegram, discord, voice, email. "
                                        "Vacío = solo escritorio.")},
        },
        "required": ["name", "herramientas"],
    },
    # YELLOW: abre capacidades nuevas al agente. La confirmación muestra `herramientas` y
    # `canales` (en `_DETAILS_ALLOWED_KEYS`): un "sí" sin ver la lista sería a ciegas.
    risk_level=RiskLevel.YELLOW,
    invoke=_mcp_allow_invoke,
))


def _mcp_set_enabled_invoke(params: dict) -> str:
    from core.mcp_config import MCPConfigRechazada, aplicar_y_resumir, habilitar_servidor

    activo = params.get("enabled")
    if not isinstance(activo, bool):
        return (
            f"Necesito saber si el servidor se habilita (true) o se deshabilita "
            f"(false){vocative()}."
        )
    try:
        habilitar_servidor(params.get("name"), activo)
    except MCPConfigRechazada as e:
        logger.warning(f"'mcp_set_server_enabled' rechazada: {e}")
        return str(e)
    except OSError as e:
        logger.error(f"'mcp_set_server_enabled' falló al guardar: {e}")
        return f"No pude guardar la configuración: {e}"
    return aplicar_y_resumir(params.get("name"))


register_tool(ToolSpec(
    name="mcp_set_server_enabled",
    description=(
        "Habilita o deshabilita un servidor MCP sin borrar su configuración. Deshabilitado, "
        "sus herramientas dejan de estar disponibles hasta que se vuelva a habilitar."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Nombre del servidor."},
            "enabled": {"type": "boolean",
                        "description": "true para habilitar, false para deshabilitar."},
        },
        "required": ["name", "enabled"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_mcp_set_enabled_invoke,
))


def _mcp_remove_invoke(params: dict) -> str:
    from core.mcp_config import MCPConfigRechazada, normalizar_nombre, quitar_servidor
    from core.mcp_manager import desregistrar_servidor

    try:
        clave = normalizar_nombre(params.get("name"))
    except MCPConfigRechazada as e:
        return str(e)
    quitadas = desregistrar_servidor(clave)
    try:
        existia = quitar_servidor(clave)
    except OSError as e:
        logger.error(f"'mcp_remove_server' falló al guardar: {e}")
        return f"Desconecté '{clave}' pero no pude borrar su configuración: {e}"
    if not existia:
        return f"No había ningún servidor '{clave}'."
    return (
        f"'{clave}' quitado: {quitadas} herramienta(s) desregistrada(s) y su configuración "
        f"borrada. Sus variables guardadas no se tocan; se quitan desde Configuración si ya "
        f"no hacen falta."
    )


register_tool(ToolSpec(
    name="mcp_remove_server",
    description=(
        "Quita un servidor MCP: lo desconecta, desregistra sus herramientas y borra su "
        "configuración y su lista de herramientas permitidas."
    ),
    parameters_schema={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Nombre del servidor."}},
        "required": ["name"],
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_mcp_remove_invoke,
))


# ── REQ-051 — proyectos de chats, por instrucción ─────────────────────────────────────────
#
# Los proyectos agrupan conversaciones en la barra lateral (REQ-016 los creó; REQ-051 los
# puso donde se buscan). Estas tres herramientas son la versión "decírselo al agente":
# «creá un proyecto Tesis», «guardá este chat en Tesis», «¿qué proyectos tengo?». Son
# verdes —crear una carpeta de chats o mover un chat de una a otra no toca nada fuera del
# historial— y solo de escritorio: los proyectos son de la barra lateral, y «este chat»
# solo tiene sentido ahí (`core/conversacion_activa.py`).

def _proyectos_del_dueno():
    from ai.memory_manager import memory
    from core.user_identity import OWNER_USER_ID

    return memory.list_projects(user_id=OWNER_USER_ID)


def _buscar_proyecto(nombre: str):
    """Return el proyecto cuyo nombre coincide (sin distinguir mayúsculas), o None."""
    objetivo = (nombre or "").strip().lower()
    if not objetivo:
        return None
    for p in _proyectos_del_dueno():
        if p.name.strip().lower() == objetivo:
            return p
    return None


def _chat_project_list_invoke(params: dict) -> str:
    proyectos = _proyectos_del_dueno()
    if not proyectos:
        return f"No hay ningún proyecto todavía{vocative()}. Puedo crear uno si me dice el nombre."
    lineas = [f"- {p.name} ({p.conversation_count} chat{'s' if p.conversation_count != 1 else ''})"
              for p in proyectos]
    return "Proyectos:\n" + "\n".join(lineas)


register_tool(ToolSpec(
    name="chat_project_list",
    description=(
        "Lista los proyectos de la barra lateral (carpetas que agrupan chats) y cuántos "
        "chats tiene cada uno. Usala cuando el usuario pregunte qué proyectos tiene o antes "
        "de mover un chat, para usar el nombre exacto."
    ),
    parameters_schema={"type": "object", "properties": {}},
    risk_level=RiskLevel.GREEN,
    invoke=_chat_project_list_invoke,
))


def _chat_project_create_invoke(params: dict) -> str:
    from ai.memory_manager import memory
    from core.user_identity import OWNER_USER_ID

    nombre = str(params.get("name") or "").strip()
    if not nombre:
        return f"Necesito el nombre del proyecto{vocative()}."
    existente = _buscar_proyecto(nombre)
    if existente is not None:
        return f"Ya hay un proyecto llamado '{existente.name}'."
    nuevo = memory.create_project(user_id=OWNER_USER_ID, name=nombre)
    if nuevo is None:
        return f"No pude crear el proyecto '{nombre}'."
    return f"Proyecto '{nombre}' creado. Ya aparece en la barra lateral."


register_tool(ToolSpec(
    name="chat_project_create",
    description=(
        "Crea un proyecto en la barra lateral: una carpeta para agrupar chats sobre un mismo "
        "tema. Usala cuando el usuario pida crear un proyecto o guardar un chat en uno que "
        "todavía no existe."
    ),
    parameters_schema={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Nombre del proyecto."}},
        "required": ["name"],
    },
    risk_level=RiskLevel.GREEN,
    invoke=_chat_project_create_invoke,
))


def _chat_project_assign_invoke(params: dict) -> str:
    from ai.memory_manager import memory
    from core import conversacion_activa
    from core.user_identity import OWNER_USER_ID

    conversation_id = conversacion_activa.actual()
    if not conversation_id:
        return f"No hay ningún chat abierto que pueda mover{vocative()}."

    nombre = str(params.get("project") or "").strip()
    if not nombre:
        return f"Necesito el nombre del proyecto{vocative()}."
    proyecto = _buscar_proyecto(nombre)
    if proyecto is None:
        if not params.get("create_if_missing"):
            return (
                f"No hay ningún proyecto llamado '{nombre}'. Puedo crearlo y guardar el chat ahí "
                f"si el usuario quiere (create_if_missing)."
            )
        nuevo_id = memory.create_project(user_id=OWNER_USER_ID, name=nombre)
        if nuevo_id is None:
            return f"No pude crear el proyecto '{nombre}'."
        proyecto = next((p for p in _proyectos_del_dueno() if p.id == nuevo_id), None)
        if proyecto is None:
            return f"No pude crear el proyecto '{nombre}'."

    if not memory.assign_conversation_to_project(conversation_id, proyecto.id, user_id=OWNER_USER_ID):
        # Un chat recién empezado todavía no tiene turnos guardados (se guardan al terminar
        # el turno), y `assign` exige que exista. Queda pedido: el bridge lo aplica en
        # cuanto guarde este turno.
        conversacion_activa.pedir_asignacion(conversation_id, proyecto.id)
        return (
            f"Este chat quedará en el proyecto '{proyecto.name}' en cuanto termine este turno."
        )
    return f"Listo: este chat quedó en el proyecto '{proyecto.name}'."


register_tool(ToolSpec(
    name="chat_project_assign_current",
    description=(
        "Guarda el chat ACTUAL (esta conversación) en un proyecto de la barra lateral. Usala "
        "cuando el usuario diga «guardá este chat en X», «mové esta conversación al proyecto "
        "X» o similar. Con create_if_missing el proyecto se crea si no existe."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "project": {"type": "string", "description": "Nombre del proyecto destino."},
            "create_if_missing": {"type": "boolean",
                                  "description": "Crear el proyecto si no existe."},
        },
        "required": ["project"],
    },
    risk_level=RiskLevel.GREEN,
    invoke=_chat_project_assign_invoke,
))


# ── REQ-062 — «mirá esta imagen» ──────────────────────────────────────────────────────────
#
# Con REQ-054 el agente ve lo que se pega en el chat; esto es lo mismo por instrucción:
# «mirá la captura que está en el Escritorio y decime qué error es», «describí
# fotos/gato.jpg». La imagen va al modelo de visión (Configuración → Modelos → «Ver
# imágenes», REQ-061) en una llamada propia, fuera del streaming del turno, igual que el
# análisis de pantalla. GREEN y solo escritorio, por lo mismo que `file_read`: leer un
# archivo es mandárselo al proveedor, y verde no puede significar "alcanzable desde
# Telegram" (por Telegram las fotos se mandan al chat y ya).

_IMAGE_LOOK_SYSTEM = (
    "Sos los ojos de un asistente: describís lo que hay en la imagen con precisión y "
    "transcribís el texto que se lea (mensajes de error, carteles, cifras) tal cual. "
    "Si te hacen una pregunta concreta, respondés eso primero. Sin inventar lo que no se ve."
)


def _image_look_invoke(params: dict) -> str:
    from ai.llm_provider import es_respuesta_de_fallo, generate_response
    from core.imagenes import ImagenRechazada, resolver_para_mirar

    try:
        ruta = resolver_para_mirar(params.get("path"))
    except ImagenRechazada as e:
        return str(e)
    pregunta = " ".join(str(params.get("question") or "").split()) or "¿Qué hay en esta imagen?"
    try:
        respuesta = generate_response(
            [{"role": "user", "content": pregunta}], _IMAGE_LOOK_SYSTEM,
            image_path=ruta, tarea="razonamiento",
        )
    except Exception as e:
        logger.error(f"'image_look' falló: {type(e).__name__}: {e}")
        return "No pude mirar la imagen: el modelo de visión no respondió."
    texto = respuesta if isinstance(respuesta, str) else getattr(respuesta, "text", "")
    if not texto or es_respuesta_de_fallo(texto):
        return ("No pude mirar la imagen: no hay un modelo que vea imágenes disponible. "
                "Se elige en Configuración → Modelos → «Ver imágenes».")
    return f"Imagen «{os.path.basename(ruta)}»:\n{texto.strip()}"


register_tool(ToolSpec(
    name="image_look",
    description=(
        "Mira una imagen que está en el equipo (png, jpg, gif, webp) y describe lo que hay "
        "o responde una pregunta sobre ella: una captura de pantalla con un error, una foto, "
        "un cartel. Usala cuando el usuario nombre un archivo de imagen o diga «mirá la "
        "captura del Escritorio». Solo dentro de su carpeta personal o de un espacio de "
        "trabajo habilitado. Para una imagen que el usuario pegó en el chat no hace falta: "
        "esa ya la ves."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "Ruta de la imagen, absoluta o relativa al Escritorio."},
            "question": {"type": "string",
                         "description": "Qué mirar o qué responder sobre la imagen (opcional)."},
        },
        "required": ["path"],
    },
    risk_level=RiskLevel.GREEN,
    invoke=_image_look_invoke,
))


# ── REQ-056 — «guardá esta conversación en un archivo» ─────────────────────────────────────
#
# La conversación abierta como `.md`, con lo guardado en la base (no con lo que el modelo
# recuerda del historial, que viene acotado): título, fecha y cada turno. Amarillo porque
# crea un archivo en el equipo, como `document_create`; la confirmación muestra el nombre.

def _chat_export_invoke(params: dict) -> str:
    from core import conversacion_activa
    from core.documentos import DocumentoRechazado
    from core.exportar_chat import exportar
    from core.user_identity import OWNER_USER_ID

    conversation_id = conversacion_activa.actual()
    if not conversation_id:
        return f"No hay ningún chat abierto que pueda exportar{vocative()}."
    try:
        ruta = exportar(
            conversation_id, OWNER_USER_ID,
            carpeta=params.get("carpeta"), nombre=params.get("nombre"),
        )
    except DocumentoRechazado as e:
        return str(e)
    except Exception as e:
        logger.error(f"'chat_export_current' falló: {type(e).__name__}: {e}")
        return "No pude escribir el archivo de la conversación."
    return f"Conversación guardada en {ruta}."


register_tool(ToolSpec(
    name="chat_export_current",
    description=(
        "Guarda el chat ACTUAL (esta conversación entera, tal como está guardada) como un "
        "archivo Markdown (.md) en el equipo del usuario. Usala cuando pida «exportá esta "
        "conversación», «guardá este chat en un archivo», «pasame esto a un .md». Sin "
        "carpeta va al Escritorio; sin nombre se arma con la fecha y el título."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "nombre": {"type": "string",
                       "description": "Nombre del archivo (opcional; se le agrega .md)."},
            "carpeta": {"type": "string",
                        "description": "Dónde guardarlo (opcional). Vacío = el Escritorio."},
        },
    },
    risk_level=RiskLevel.YELLOW,
    invoke=_chat_export_invoke,
))


# ── REQ-052 — «¿qué tenés conectado?» ─────────────────────────────────────────────────────
#
# El mismo mapa que dibuja el panel «Mapa» de la barra superior, en texto: con qué modelo
# responde, qué canales están vivos, qué servidores MCP conectaron y qué flujos hay. Es una
# lectura y nunca lleva una credencial (`ui/webview/mapa_conexiones.py`), pero cuenta qué
# hay conectado y con qué: por lo mismo que `mcp_list_servers`, solo delante del computador.

def _connection_map_invoke(params: dict) -> str:
    from core.terminal_session import terminal_manager
    from ui.webview import gui_state, mapa_conexiones

    try:
        sesiones = terminal_manager.listado()
    except Exception as e:
        logger.warning(f"connection_map: sin listado de terminales: {e}")
        sesiones = []
    mapa = mapa_conexiones.construir(gui_state.WAKE_STATE, sesiones)
    return mapa_conexiones.resumen_para_modelo(mapa)


register_tool(ToolSpec(
    name="connection_map",
    description=(
        "Resume qué tiene conectado el agente ahora mismo: con qué modelo responde y qué "
        "proveedores tienen clave, qué canales están activos (escritorio, voz, Telegram, "
        "Discord, correo), qué servidores MCP están conectados y con cuántas herramientas, "
        "y qué flujos existen. Usala cuando el usuario pregunte qué tiene conectado, qué "
        "canales o servidores están activos, o por qué algo no responde. Es lo mismo que "
        "muestra el panel «Mapa» de la barra superior."
    ),
    parameters_schema={"type": "object", "properties": {}},
    risk_level=RiskLevel.GREEN,
    invoke=_connection_map_invoke,
))
