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

from agents.tool_registry import execute_tool, get_tool, list_tool_names
from ai.llm_provider import LLMToolResponse, generate_response
from core.agent_context import agent_context_manager
from core.security_manager import ActionDenied, security_manager

logger = logging.getLogger(__name__)

MAX_LLM_CALLS = 5

_SYSTEM_PROMPT = (
    "Eres el núcleo de razonamiento de Noddoo, un asistente con personalidad estilo "
    "JARVIS: educado, directo, se dirige al usuario como 'Señor'. Tienes acceso a "
    "herramientas para ejecutar acciones reales en el sistema del usuario. Usa una "
    "herramienta solo si el pedido la requiere de verdad; si puedes responder "
    "directamente con lo que ya sabes, hazlo sin llamar a ninguna herramienta. Si el "
    "resultado de una herramienta indica que la acción fue denegada, no la reintentes ni "
    "intentes una alternativa — infórmalo y detente."
)


def _build_tool_list() -> list[dict]:
    """CA-02: convierte el catálogo de `tool_registry` a un formato genérico
    {name, description, parameters_schema}, sin filtrar por canal (CA-11) — el filtro real
    ocurre después, dentro de `execute_tool()`."""
    tools = []
    for name in list_tool_names():
        spec = get_tool(name)
        if spec is None:
            continue
        tools.append({
            "name": spec.name,
            "description": spec.description,
            "parameters_schema": spec.parameters_schema,
        })
    return tools


def _build_prompt(task: str, history: list[dict]) -> str:
    """Cada llamada al LLM dentro del loop es un mensaje único y autocontenido (no se
    mantiene una conversación multi-turno nativa del proveedor) — decisión de
    arquitectura-007.md, sección 'Riesgos y mitigación', para evitar mantener 3 protocolos
    de continuación (tool_use/tool_result de Anthropic, role='tool' de OpenAI/DeepSeek) sin
    cobertura de test previa."""
    if not history:
        return task
    lines = [f"Tarea original del usuario: {task}", "", "Acciones ya ejecutadas en este intento:"]
    for i, h in enumerate(history, 1):
        lines.append(f"{i}. {h['tool']}({h['params']}) -> {h['result']}")
    lines.append("")
    lines.append(
        "Continúa resolviendo la tarea con esta información. Si ya puedes responder, "
        "hazlo directamente sin usar más herramientas."
    )
    return "\n".join(lines)


def run(task: str, channel, user_id: str = "default", agent_name: str = "reasoning_loop") -> str:
    """Punto de entrada del bucle de razonamiento.

    INVARIANTE DE SEGURIDAD: `channel`/`user_id` son SIEMPRE los que pasa el caller
    confiable (nunca argumentos que el LLM decidió) — mismo invariante que
    `security_manager.py:239-246` y el patrón de `core/resolution.py::_try_intent()`. Los
    argumentos de un tool call que el LLM proponga para `channel`/`user_id` (si los
    propusiera) se descartan siempre a favor de estos dos parámetros.
    """
    resolved_channel = security_manager.resolve_channel(channel)
    tools = _build_tool_list()

    history: list[dict] = []
    final_text: Optional[str] = None

    for call_number in range(1, MAX_LLM_CALLS + 1):
        prompt = _build_prompt(task, history)
        response = generate_response(
            [{"role": "user", "content": prompt}], _SYSTEM_PROMPT, tools=tools
        )

        if not isinstance(response, LLMToolResponse):
            # CONFIRMADO 1: degradación silenciosa (proveedor sin tool-calling) — texto
            # plano, se acepta como respuesta final.
            final_text = response
            break

        if not response.tool_calls:
            # El LLM respondió sin pedir ninguna tool: se acepta como final (caso borde de
            # SPEC — no confundir "no quiso usar herramientas" con "hay que insistir").
            final_text = response.text or "No obtuve una respuesta útil del modelo, Señor."
            break

        # Un tool call por iteración (decide -> ejecuta -> evalúa, CA-07). Si el modelo
        # pidiera varias en el mismo turno, solo se ejecuta la primera en este ciclo; las
        # demás quedan implícitas para que el modelo las vuelva a pedir en la siguiente
        # iteración si aún hacen falta, dentro del límite de 5.
        call = response.tool_calls[0]
        params = dict(call.arguments or {})
        params["channel"] = resolved_channel.value
        params["user_id"] = user_id

        try:
            result = execute_tool(call.name, params, resolved_channel, user_id)
        except ActionDenied as e:
            # CA-08: corta de inmediato. No reintenta, no prueba otra tool, no llama de
            # nuevo al LLM.
            final_text = f"⛔ No puedo ejecutar esa acción, Señor: {e.reason or 'denegada'}."
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
            "No pude completar la tarea en el número de intentos disponibles, Señor. "
            "¿Quiere que lo intente de otra forma?"
        )

    # CA-10: un solo par user/assistant por invocación completa del loop, sin importar
    # cuántas iteraciones internas hubo.
    agent_context_manager.update_context(agent_name, user_id, {"role": "user", "content": task})
    agent_context_manager.update_context(
        agent_name, user_id, {"role": "assistant", "content": final_text[:200]}
    )

    return final_text
