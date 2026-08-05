"""
tests/test_reasoning_loop.py

Cobertura de `core/reasoning_loop.py` (REQ-007, CA-02, CA-06 a CA-11, CA-13).

Convenciones (.claude/rules/testing.md): sin red, sin tocar la DB real de contexto
(`agent_context_manager` siempre mockeado o con `update_context` interceptado),
`generate_response`/`execute_tool` siempre mockeados — este módulo nunca debe golpear un
proveedor LLM real ni ejecutar un tool real en tests.
"""
from pathlib import Path
from unittest.mock import patch

from agents.tool_registry import ToolSpec, register_tool
from ai.llm_provider import LLMToolResponse, ToolCallRequest
from core import reasoning_loop
from core.security_manager import ActionDenied, RiskLevel


def test_build_tool_list_expone_parameters_schema_sin_modificar():
    """CA-02: un ToolSpec registrado aparece en `_build_tool_list()` con su
    `parameters_schema` intacto."""
    schema = {
        "type": "object",
        "properties": {"foo": {"type": "string"}},
        "required": ["foo"],
    }
    register_tool(ToolSpec(
        name="test_ca02_tool",
        description="tool de prueba CA-02",
        parameters_schema=schema,
        risk_level=RiskLevel.GREEN,
        invoke=lambda params: "ok",
    ))

    tools = reasoning_loop._build_tool_list()
    entry = next(t for t in tools if t["name"] == "test_ca02_tool")

    assert entry["description"] == "tool de prueba CA-02"
    assert entry["parameters_schema"] == schema


def test_build_tool_list_no_filtra_por_channel():
    """CA-11: `_build_tool_list()` no recibe ni consulta `channel` — ofrece siempre el
    catálogo completo, sin importar risk_level."""
    register_tool(ToolSpec(
        name="test_ca11_yellow",
        description="tool amarillo",
        parameters_schema={"type": "object", "properties": {}},
        risk_level=RiskLevel.YELLOW,
        invoke=lambda params: "ok",
    ))
    register_tool(ToolSpec(
        name="test_ca11_green",
        description="tool verde",
        parameters_schema={"type": "object", "properties": {}},
        risk_level=RiskLevel.GREEN,
        invoke=lambda params: "ok",
    ))

    import inspect
    assert "channel" not in inspect.signature(reasoning_loop._build_tool_list).parameters

    names = {t["name"] for t in reasoning_loop._build_tool_list()}
    assert "test_ca11_yellow" in names
    assert "test_ca11_green" in names


def test_ca06_reasoning_loop_nunca_llama_invoke_directo():
    """CA-06: verificable por grep estático — `core/reasoning_loop.py` nunca llama
    `.invoke(` directo, todo tool se ejecuta vía `execute_tool()`."""
    source = Path(reasoning_loop.__file__).read_text(encoding="utf-8")
    assert ".invoke(" not in source


def test_ca07_agota_5_llamadas_sin_una_sexta():
    """Si el LLM nunca da una respuesta final (siempre pide una tool), `run()` hace
    exactamente MAX_LLM_CALLS llamadas y retorna el mensaje de límite, nunca una 6ª."""
    always_tool_call = LLMToolResponse(
        text=None,
        tool_calls=[ToolCallRequest(id="1", name="test_ca02_tool", arguments={})],
    )

    with patch("core.reasoning_loop.generate_response", return_value=always_tool_call) as mock_gen, \
         patch("core.reasoning_loop.execute_tool", return_value="resultado parcial"), \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("tarea sin fin", "desktop", "u1")

    assert mock_gen.call_count == reasoning_loop.MAX_LLM_CALLS
    assert "no pude completar la tarea" in result.lower()


def test_ca08_action_denied_corta_de_inmediato():
    """CA-08: ante ActionDenied, el loop corta sin reintentar — `generate_response` se
    llamó solo 1 vez."""
    tool_call_response = LLMToolResponse(
        text=None,
        tool_calls=[ToolCallRequest(id="1", name="algo_denegado", arguments={})],
    )

    with patch("core.reasoning_loop.generate_response", return_value=tool_call_response) as mock_gen, \
         patch("core.reasoning_loop.execute_tool",
               side_effect=ActionDenied("algo_denegado", "desktop", "denegado por security_manager")), \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("haz algo prohibido", "desktop", "u1")

    assert mock_gen.call_count == 1
    assert "no puedo ejecutar esa acción" in result.lower()


def test_ca10_update_context_se_llama_exactamente_dos_veces():
    """CA-10: sin importar cuántas iteraciones internas hubo (3 tool-calls simuladas acá),
    `agent_context_manager.update_context()` se llama exactamente 2 veces en total."""
    tool_call_response = LLMToolResponse(
        text=None,
        tool_calls=[ToolCallRequest(id="1", name="test_ca02_tool", arguments={})],
    )
    final_response = LLMToolResponse(text="tarea completada", tool_calls=[])

    with patch("core.reasoning_loop.generate_response",
               side_effect=[tool_call_response, tool_call_response, final_response]), \
         patch("core.reasoning_loop.execute_tool", return_value="resultado ok"), \
         patch("core.reasoning_loop.agent_context_manager") as mock_ctx:
        reasoning_loop.run("tarea con 3 iteraciones", "desktop", "u1")

    assert mock_ctx.update_context.call_count == 2
    roles = [call.args[2]["role"] for call in mock_ctx.update_context.call_args_list]
    assert roles == ["user", "assistant"]


def test_ca13_exception_generica_no_crashea_y_sigue_el_loop():
    """CA-13: si `execute_tool` levanta una excepción genérica (no ActionDenied), el loop
    no crashea — se registra como resultado fallido y continúa a la siguiente iteración."""
    tool_call_response = LLMToolResponse(
        text=None,
        tool_calls=[ToolCallRequest(id="1", name="test_ca02_tool", arguments={})],
    )
    final_response = LLMToolResponse(text="me recuperé del error", tool_calls=[])

    with patch("core.reasoning_loop.generate_response",
               side_effect=[tool_call_response, final_response]), \
         patch("core.reasoning_loop.execute_tool", side_effect=KeyError("boom")), \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("tarea con error interno", "desktop", "u1")

    assert result == "me recuperé del error"


def test_run_responde_directo_sin_tool_calls():
    """Caso borde de SPEC: el LLM responde sin pedir ninguna herramienta — se acepta como
    respuesta final sin insistir."""
    direct_response = LLMToolResponse(text="la respuesta es 42", tool_calls=[])

    with patch("core.reasoning_loop.generate_response", return_value=direct_response) as mock_gen, \
         patch("core.reasoning_loop.execute_tool") as mock_exec, \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("cuánto es 6x7", "desktop", "u1")

    assert result == "la respuesta es 42"
    assert mock_gen.call_count == 1
    mock_exec.assert_not_called()


def test_confirmado1_proveedor_sin_tool_calling_degrada_a_texto_plano():
    """CONFIRMADO 1: si `generate_response()` retorna un `str` plano (proveedor sin
    soporte de tool-calling), el loop lo acepta directamente como respuesta final."""
    with patch("core.reasoning_loop.generate_response", return_value="respuesta en texto plano") as mock_gen, \
         patch("core.reasoning_loop.execute_tool") as mock_exec, \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("tarea con proveedor sin tools", "desktop", "u1")

    assert result == "respuesta en texto plano"
    assert mock_gen.call_count == 1
    mock_exec.assert_not_called()
