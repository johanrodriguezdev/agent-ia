"""
tests/test_base_agent.py

REQ-006/CA-09 — regresión del bug H7 (`core/base_agent.py:103`), documentado en el
docstring original de este archivo.

REQ-007/CA-01 — el for-loop dumb que probaba tools en orden fijo (semántica que motivaba
los 3 tests originales `test_dynamic_agent_*`) se elimina de
`_DynamicAgentInstance.execute()`: ahora delega a `core/reasoning_loop.py::run()`. Esos 3
tests se reemplazan por un test de delegación (mockeando `core.reasoning_loop.run`) — la
cobertura de la lógica interna del loop (denials, reintentos, límite de llamadas) vive
ahora en `tests/test_reasoning_loop.py`.

`test_agent_tool_execute_no_propaga_excepcion_a_llamador` prueba `AgentTool.execute()` en
sí (no `_DynamicAgentInstance.execute()`), que no cambia en este REQ — se mantiene tal cual
(ver "Disposición de tests/test_base_agent.py" en arquitectura-007.md).
"""
from unittest.mock import patch

from core.base_agent import AgentTool, _DynamicAgentInstance
from core.security_manager import ActionDenied


def test_dynamic_agent_execute_delega_a_reasoning_loop():
    """CA-01: `_DynamicAgentInstance.execute()` ya no itera `self.tools` — delega a
    `core.reasoning_loop.run(task, channel, user_id)` y retorna su resultado tal cual."""
    agent = _DynamicAgentInstance("Agent_test", "desc", "prompt", [])

    with patch("core.reasoning_loop.run", return_value="resultado del loop") as mock_run:
        result = agent.execute(
            "cierra chrome", context={"channel": "telegram", "user_id": "u1"}
        )

    mock_run.assert_called_once_with("cierra chrome", "telegram", "u1")
    assert result == "resultado del loop"


def test_dynamic_agent_execute_usa_defaults_sin_context():
    """Sin `context` (o sin claves), `channel`/`user_id` caen a `None`/`"default"`."""
    agent = _DynamicAgentInstance("Agent_test", "desc", "prompt", [])

    with patch("core.reasoning_loop.run", return_value="ok") as mock_run:
        result = agent.execute("tarea cualquiera")

    mock_run.assert_called_once_with("tarea cualquiera", None, "default")
    assert result == "ok"


def test_agent_tool_execute_no_propaga_excepcion_a_llamador():
    """`AgentTool.execute()` sigue sin tocarse en este REQ (Observación A de
    orion-security): ante cualquier excepción de `function`, sigue devolviendo un
    string de error en vez de propagar — comportamiento legado, no cubierto por CA-09."""
    def _raises(params):
        raise ActionDenied("x", "desktop", "motivo")

    tool = AgentTool("legacy_tool", "desc", _raises)
    result = tool.execute({})

    assert isinstance(result, str)
    assert "Error en herramienta" in result
