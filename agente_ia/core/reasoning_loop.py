"""
core/reasoning_loop.py
Bucle de razonamiento real con LLM (REQ-007, CA-01 a CA-13).

Reemplaza el for-loop de `_DynamicAgentInstance.execute()` (que probaba tools en orden fijo
sin ningún criterio) por un ciclo decide->ejecuta->evalúa dirigido por el LLM, con un
presupuesto duro de 5 llamadas totales (CONFIRMADO 2) y ejecución de tools EXCLUSIVAMENTE vía
`agents/tool_registry.py::execute_tool()` (CA-06) — nunca `ToolSpec.invoke` directo.
"""
import logging
from typing import Optional

from agents.tool_registry import execute_tool
from core import streaming
from core.cancelacion import abortar_si_cancelado
from ai.llm_provider import (
    LLMToolResponse, con_aviso_de_cambio, es_respuesta_de_fallo, generate_response,
)
from config_manager import get_agent_name, get_display_name, get_user_title
from core.agent_context import agent_context_manager
from core.security_manager import ActionDenied, ChannelType, security_manager
from core.address import momento_actual, vocative, vocative_start
from core.composer_modes import ModoComposer, get_mode
from core.progress import report as progress_report
from core.identity import build_identity_block

logger = logging.getLogger(__name__)

MAX_LLM_CALLS = 5

#: REQ-021/CA-22 — turnos previos de `agent_context` que ve el LLM. Alineado con el corte
#: que ya usa `core/orchestrator.py` (`conversation[-5:]`).
CONTEXT_TURNS = 5


def _addressing_clause() -> str:
    """Describe al LLM cómo debe dirigirse al usuario, según lo configurado."""
    parts = []
    title = get_user_title().strip()
    if title:
        parts.append(f"se dirige al usuario como '{title}'")
    full_name = get_display_name().strip()
    if full_name:
        parts.append(f"el nombre completo del usuario es {full_name}")
    return f", {', '.join(parts)}" if parts else ""


def _bloque_de_lo_definido_por_el_usuario() -> str:
    """Rutinas y comandos aprendidos, nombrados en el prompt de sistema.

    Sin esto, el modelo tendria que adivinar que existen o gastar una vuelta entera en
    `routine_list`/`learned_command_list` antes de poder usarlos. Nombrarlos cuesta unas
    pocas decenas de tokens y hace que "modo trabajo" se resuelva en la PRIMERA llamada.

    Se arma en cada turno, no una vez al importar: una rutina creada hace un minuto tiene
    que estar disponible en el turno siguiente, sin reiniciar.
    """
    partes = []
    try:
        from learning.routines_engine import list_routine_names

        nombres = [n for n in list_routine_names() if n][:20]
        if nombres:
            partes.append("Rutinas que el usuario definio: " + ", ".join(nombres)
                          + ". Para ejecutar una, usa `routine_run`.")
    except Exception as e:
        logger.debug(f"No se pudieron leer las rutinas para el prompt: {e}")

    try:
        from learning.command_learning import get_custom_commands

        frases = [f for f in get_custom_commands() if f][:20]
        if frases:
            partes.append("Comandos que el usuario enseño: " + ", ".join(frases)
                          + ". Para ejecutar uno, usa `learned_command_run`.")
    except Exception as e:
        logger.debug(f"No se pudieron leer los comandos aprendidos para el prompt: {e}")

    return ("\n\n" + "\n".join(partes)) if partes else ""


def _build_system_prompt(modo_def: Optional[ModoComposer] = None) -> str:
    """Arma el prompt de sistema con el nombre configurado del agente.

    Se resuelve en cada llamada (no una vez al importar) para que renombrar al agente o
    cambiar el tratamiento en la pantalla de Configuración tenga efecto inmediato, sin
    reiniciar el proceso ni dejar al agente presentándose con el nombre viejo.

    `modo_def` (REQ-026): si el composer tiene un modo estratégico activo, su
    `prompt_hint` se agrega SIEMPRE al final, justo antes del bloque de fecha/hora — nunca
    en medio del prompt — para no romper el cacheo de prefijo de los proveedores que lo
    soportan salvo cuando el usuario realmente cambia de modo (mismo criterio que ya
    aplica el bloque de fecha/hora unas líneas más abajo).
    """
    agent_name = get_agent_name()

    # La personalidad ya no se describe acá. Antes, este prompt decía solo
    # "personalidad estilo JARVIS: educado, directo", mientras que `ai/claude_brain.py`
    # (Telegram/Discord) traía 40 líneas de carácter: el mismo agente sonaba distinto según
    # el canal, y el canal más usado —escritorio y voz— era el que menos personalidad
    # tenía. Ahora ambos leen los mismos documentos.
    identity_block = build_identity_block(agent_name)

    operating_rules = (
        "Tienes acceso a herramientas para ejecutar acciones reales en el sistema del "
        "usuario. Usa una herramienta solo si el pedido la requiere de verdad; si puedes "
        "responder directamente con lo que ya sabes, hazlo sin llamar a ninguna "
        "herramienta. Si el resultado de una herramienta indica que la acción fue "
        "denegada, no la reintentes ni intentes una alternativa — infórmalo y detente."
    ) + _bloque_de_lo_definido_por_el_usuario()

    # REQ-026: la pista del modo activo va al final de las reglas, DESPUÉS del bloque de
    # rutinas/comandos aprendidos y ANTES del de fecha/hora — mismo motivo de caché que
    # `momento` un poco más abajo.
    if modo_def is not None and modo_def.prompt_hint:
        operating_rules += f"\n\n{modo_def.prompt_hint}"

    # La fecha y hora va AL FINAL, nunca en el cuerpo — mismo criterio que
    # `ai/claude_brain.py`: los proveedores con caché de prefijo solo reutilizan lo que no
    # cambia desde el principio, y con la hora al minuto en medio se recalcularía todo lo
    # que viene detrás cada 60 segundos.
    #
    # Sin esta línea el modelo no sabe qué hora es y lo resuelve como puede: a las 23:30
    # saludaba con "buenos días" mientras la pantalla —que sí mira el reloj— decía "buenas
    # noches". `claude_brain` ya se lo decía a Telegram; el escritorio y la voz, que son
    # los canales más usados, eran justo los que no.
    momento = f"\n\nFecha y hora actual: {momento_actual()}"

    if identity_block:
        return (
            f"Eres el núcleo de razonamiento de {agent_name}{_addressing_clause()}."
            f"{identity_block}\n\n{operating_rules}{momento}"
        )

    # Sin documentos de identidad, el prompt queda igual que antes de este cambio.
    return (
        f"Eres el núcleo de razonamiento de {agent_name}, un asistente con "
        f"personalidad estilo JARVIS: educado, directo{_addressing_clause()}. "
        f"{operating_rules}{momento}"
    )


def _reordenar_priorizando(catalogo: list[dict], tool_names: tuple) -> list[dict]:
    """REQ-026 — mueve al frente de `catalogo` las entradas cuyo `"name"` está en
    `tool_names`, preservando el orden relativo dentro de cada grupo. NUNCA filtra: el
    catálogo completo se conserva, solo cambia el orden. Es intencional (arquitectura-026,
    riesgo "reordenar, no filtrar") — un mensaje que llega con un modo activo pero que no
    tiene nada que ver con él tiene que seguir pudiendo usar cualquier otra tool.
    """
    priorizadas = [t for t in catalogo if t.get("name") in tool_names]
    resto = [t for t in catalogo if t.get("name") not in tool_names]
    return priorizadas + resto


def _build_tool_list(channel=None, modo_def: Optional[ModoComposer] = None) -> list[dict]:
    """CA-02 — lo que se le ofrece al modelo, ya filtrado por canal.

    La lista la arma `agents/tool_registry.py::catalogo_para_modelo()`, que es de donde la
    lee tambien `ai/claude_brain.py`: con una copia por motor, la reduccion del catalogo
    aplicaba en escritorio y no en Telegram. El filtro NO es el control de seguridad — ese
    sigue dentro de `execute_tool()` (CA-11).

    `modo_def` (REQ-026): si hay un modo estratégico activo, sus `tool_names` se
    priorizan (reordenan al frente) vía `_reordenar_priorizando()` — nunca se filtra el
    resto del catálogo.
    """
    from agents.tool_registry import catalogo_para_modelo

    catalogo = catalogo_para_modelo(channel)
    if modo_def is not None and modo_def.tool_names:
        catalogo = _reordenar_priorizando(catalogo, modo_def.tool_names)
    return catalogo


def _load_prior_turns(agent_name: str, user_id: str) -> list[dict]:
    """Return los últimos `CONTEXT_TURNS` turnos ya cerrados de `agent_context` (CA-22).

    Se lee UNA sola vez, antes del bucle: las dos escrituras de contexto ocurren al final
    de `run()`, así que lo leído es estrictamente anterior al turno en curso. Un fallo de
    la DB de contexto no puede tumbar el loop — se sigue sin historial.
    """
    try:
        context = agent_context_manager.get_context(agent_name, user_id)
        conversation = getattr(context, "conversation", None)
        if not isinstance(conversation, list):
            return []
        return [t for t in conversation[-CONTEXT_TURNS:] if isinstance(t, dict)]
    except Exception as e:
        logger.warning(f"No se pudo leer el contexto previo de {agent_name}/{user_id}: {e}")
        return []


def _build_prompt(
    task: str, history: list[dict], prior_turns: Optional[list[dict]] = None,
) -> str:
    """Cada llamada al LLM dentro del loop es un mensaje único y autocontenido (no se
    mantiene una conversación multi-turno nativa del proveedor) — decisión de
    arquitectura-007.md, sección 'Riesgos y mitigación', para evitar mantener 3 protocolos
    de continuación (tool_use/tool_result de Anthropic, role='tool' de OpenAI/DeepSeek) sin
    cobertura de test previa.

    REQ-021/CA-22: `prior_turns` son los últimos turnos ya cerrados de `agent_context`
    (que hasta ahora se escribían y nunca se releían), para que el LLM pueda sostener el
    hilo. Sin historial de tools y sin turnos previos, el prompt sigue siendo el de antes
    de REQ-021 byte a byte.
    """
    if not history and not prior_turns:
        return task

    if prior_turns:
        lines = ["Turnos anteriores de esta conversación:"]
        for turn in prior_turns:
            role = "Usuario" if turn.get("role") == "user" else "Asistente"
            lines.append(f"- {role}: {turn.get('content', '')}")
        lines.append("")
        if not history:
            lines.append(f"Mensaje actual del usuario: {task}")
            return "\n".join(lines)
        lines.append(f"Tarea original del usuario: {task}")
        lines.append("")
        lines.append("Acciones ya ejecutadas en este intento:")
        _append_history_lines(lines, history)
        return "\n".join(lines)

    lines = [f"Tarea original del usuario: {task}", "", "Acciones ya ejecutadas en este intento:"]
    _append_history_lines(lines, history)
    return "\n".join(lines)


def _append_history_lines(lines: list[str], history: list[dict]) -> None:
    """Añade a `lines` el detalle de las tools ya ejecutadas y la instrucción de cierre."""
    for i, h in enumerate(history, 1):
        lines.append(f"{i}. {h['tool']}({h['params']}) -> {h['result']}")
    lines.append("")
    lines.append(
        "Continúa resolviendo la tarea con esta información. Si ya puedes responder, "
        "hazlo directamente sin usar más herramientas."
    )


def run(task: str, channel, user_id: str = "default", agent_name: str = "reasoning_loop",
        estado: Optional[dict] = None, modo: Optional[str] = None) -> str:
    """Punto de entrada del bucle de razonamiento.

    `estado`, si se pasa, es un dict que el bucle RELLENA: `{"denied": True}` cuando corto
    por una accion denegada, y `{"sin_modelo": True}` cuando no consiguio hablar con ningun
    proveedor. Lo que retorna sigue siendo el texto de siempre
    (CA-08), asi que ningun caller existente cambia; existe porque desde que el modelo lee
    primero, una denegacion llega por aca y no por el resolver que la ejecutaba, y
    `core/resolution.py` necesita saberlo para no colgarle recordatorios ni repreguntas a
    un mensaje de denegacion.

    INVARIANTE DE SEGURIDAD: `channel`/`user_id` son SIEMPRE los que pasa el caller
    confiable (nunca argumentos que el LLM decidió) — mismo invariante que
    `security_manager.py:239-246` y el patrón de `core/resolution.py::_try_intent()`. Los
    argumentos de un tool call que el LLM proponga para `channel`/`user_id` (si los
    propusiera) se descartan siempre a favor de estos dos parámetros.

    `modo` (REQ-026): id del modo estratégico activo del composer de escritorio, o `None`.
    Se resuelve acá mismo con `get_mode()` (fail-safe: un id vacío o desconocido equivale
    a "sin modo") y de ahí salen tanto el catálogo priorizado como la `tarea` que rutea
    esta llamada.
    """
    modo_def = get_mode(modo)
    resolved_channel = security_manager.resolve_channel(channel)
    tools = _build_tool_list(resolved_channel, modo_def)

    history: list[dict] = []
    final_text: Optional[str] = None
    aviso_final: dict = {}   # REQ-022/CA-12 — se "fija" solo en la vuelta que gana
    prior_turns = _load_prior_turns(agent_name, user_id)   # REQ-021/CA-22

    for call_number in range(1, MAX_LLM_CALLS + 1):
        # Punto de corte del boton de detener: antes de gastar otra llamada al modelo o
        # ejecutar otra herramienta. Es donde parar es seguro — no deja nada a medias.
        abortar_si_cancelado(f"reasoning_loop, vuelta {call_number}")

        # El silencio entre que el usuario pregunta y llega la respuesta era indistinguible
        # de un cuelgue. A partir de la segunda vuelta se numera: si el modelo encadena
        # herramientas, se ve que avanza en vez de parecer que se repite.
        progress_report("Pensando" if call_number == 1 else f"Pensando ({call_number})")

        prompt = _build_prompt(task, history, prior_turns)
        aviso_cambio: dict = {}   # REQ-022/CA-12 — vacío otra vez en cada vuelta
        # `permitido()`: lo que salga de ESTA llamada es la respuesta al usuario y se
        # muestra mientras se escribe. Las herramientas que se ejecuten despues pueden
        # consultar al modelo por su cuenta (resumir un correo, leer una captura) y eso NO
        # tiene que aparecer en la burbuja del chat: quedan fuera del bloque.
        # `tarea`: por defecto "razonamiento" —es LA respuesta al usuario, con herramientas
        # y varias vueltas—, salvo que el modo activo fije la suya (REQ-026, solo Código e
        # Investigación lo hacen; Flujos y Tareas necesitan el modelo general de varias
        # vueltas). Quien quiera mandarla a un modelo distinto del general —uno gratuito
        # con tool-calling, por ejemplo— lo configura en `task_providers` sin tocar el
        # resto del sistema.
        tarea = modo_def.tarea if modo_def and modo_def.tarea else "razonamiento"
        with streaming.permitido():
            response = generate_response(
                [{"role": "user", "content": prompt}], _build_system_prompt(modo_def),
                tools=tools,
                tarea=tarea,
                aviso=aviso_cambio,   # REQ-022/CA-12
            )

        if not isinstance(response, LLMToolResponse):
            # CONFIRMADO 1: degradación silenciosa (proveedor sin tool-calling) — texto
            # plano, se acepta como respuesta final.
            final_text = response
            aviso_final = aviso_cambio
            break

        if not response.tool_calls:
            # El LLM respondió sin pedir ninguna tool: se acepta como final (caso borde de
            # SPEC — no confundir "no quiso usar herramientas" con "hay que insistir").
            final_text = response.text or f"No obtuve una respuesta útil del modelo{vocative()}."
            aviso_final = aviso_cambio
            break

        # Un tool call por iteración (decide -> ejecuta -> evalúa, CA-07). Si el modelo
        # pidiera varias en el mismo turno, solo se ejecuta la primera en este ciclo; las
        # demás quedan implícitas para que el modelo las vuelva a pedir en la siguiente
        # iteración si aún hacen falta, dentro del límite de 5.
        call = response.tool_calls[0]
        params = dict(call.arguments or {})
        params["channel"] = resolved_channel.value
        params["user_id"] = user_id
        # Lo que dijo el humano, TAL CUAL. Igual que `channel` y `user_id`, lo pone el
        # caller y no el modelo: es un dato de la invocacion, no un argumento negociable.
        # `dispatcher` lo usa como segundo intento cuando el modelo reformula la orden y la
        # reformulacion no la reconoce el clasificador — ver `router/dispatcher.py`.
        params["texto_original"] = task

        try:
            result = execute_tool(call.name, params, resolved_channel, user_id)
        except ActionDenied as e:
            # CA-08: corta de inmediato. No reintenta, no prueba otra tool, no llama de
            # nuevo al LLM.
            final_text = f"⛔ No puedo ejecutar esa acción{vocative()}: {e.reason or 'denegada'}."
            if estado is not None:
                estado["denied"] = True
            break
        except Exception as e:
            # CA-13: tool call malformado / invoke interno falla — no crashea, se informa
            # como resultado fallido de esta iteración y el LLM puede reintentar.
            logger.warning(f"Tool '{call.name}' falló en iteración {call_number}: {e}")
            result = f"Error ejecutando '{call.name}': {e}"

        history.append({"tool": call.name, "params": params, "result": result})

    if final_text is None:
        # CA-07: se agotaron las 5 llamadas sin una respuesta final del LLM.
        final_text = (
            f"No pude completar la tarea en el número de intentos disponibles{vocative()}. "
            "¿Quiere que lo intente de otra forma?"
        )

    # Sin proveedor no hubo razonamiento, hubo un error de red o de configuración. Se
    # avisa para que `core/resolution.py` pueda intentar el camino local: sin conexión,
    # "sube el volumen" tiene que seguir funcionando.
    if estado is not None and es_respuesta_de_fallo(final_text):
        estado["sin_modelo"] = True

    # REQ-022/CA-12/13/14/16/17: se evalúa DESPUÉS de `es_respuesta_de_fallo()` — cuando
    # hubo un swap exitoso, `final_text` ya es una respuesta real (nunca `SIN_PROVEEDOR`),
    # así que el orden no cambia ese chequeo en ningún caso. Forma corta en VOICE, larga
    # (con proveedor y modelo) en cualquier otro canal.
    final_text = con_aviso_de_cambio(
        final_text, aviso_final, corto=(resolved_channel == ChannelType.VOICE),
    )

    # CA-10: un solo par user/assistant por invocación completa del loop, sin importar
    # cuántas iteraciones internas hubo.
    agent_context_manager.update_context(agent_name, user_id, {"role": "user", "content": task})
    agent_context_manager.update_context(
        agent_name, user_id, {"role": "assistant", "content": final_text[:200]}
    )

    return final_text
