"""
tests/test_tool_registry.py

REQ-006 — `agents/tool_registry.py` (CA-08, CA-14, CA-15, CA-16, CA-17).

Convenciones (.claude/rules/testing.md): sin red, sin mic/altavoces, `input()` siempre
mockeado cuando aplica.
"""

import dataclasses

import pytest

from agents.tool_registry import ToolSpec, execute_tool, get_tool, register_tool
from core.security_manager import ActionDenied, ChannelType, RiskLevel, security_manager


def test_toolspec_shape():
    """CA-14: `ToolSpec` es isomorfo a un tool de MCP — name/description/parameters_schema
    (JSON Schema)/risk_level/invoke, con `origin` local por default."""
    spec = get_tool("task_create")
    assert spec is not None
    assert isinstance(spec.name, str) and spec.name
    assert isinstance(spec.description, str) and spec.description
    assert isinstance(spec.parameters_schema, dict)
    assert spec.parameters_schema.get("type") == "object"
    assert "properties" in spec.parameters_schema
    assert isinstance(spec.risk_level, RiskLevel)
    assert callable(spec.invoke)
    assert spec.origin == "local"


def test_tool_sin_risk_level_no_compila():
    """CA-15: `risk_level` es un campo sin default de un dataclass frozen — instanciar un
    `ToolSpec` sin él falla en tiempo de construcción, fail-closed por diseño."""
    with pytest.raises(TypeError):
        ToolSpec(
            name="sin_riesgo",
            description="tool de prueba sin risk_level",
            parameters_schema={"type": "object", "properties": {}},
            invoke=lambda params: "ok",
        )


def test_toolspec_no_tiene_campo_de_usuario():
    """CA-17: `ToolSpec` no declara ningún campo de identidad de usuario/tenant — la
    resolución de credenciales por origen de tool queda fuera de este contrato."""
    field_names = {f.name for f in dataclasses.fields(ToolSpec)}
    prohibited = {"user_id", "tenant", "tenant_id", "empid", "emp_id", "owner"}
    assert not (field_names & prohibited), f"campos de usuario filtrados: {field_names & prohibited}"


def test_tool_origen_remoto_mismo_contrato():
    """CA-16: un `ToolSpec` con `origin='mcp_remote'` (sin cliente MCP real, fixture
    estático) pasa por `execute_tool()` sin ninguna rama de código distinta a un tool
    local."""
    calls = []

    def _remote_invoke(params: dict) -> str:
        calls.append(params)
        return "resultado remoto simulado"

    register_tool(ToolSpec(
        name="_test_remote_tool",
        description="Tool remoto simulado (fixture SIGAIND)",
        parameters_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        risk_level=RiskLevel.GREEN,
        invoke=_remote_invoke,
        origin="mcp_remote",
    ))

    result = execute_tool("_test_remote_tool", {"q": "hola"}, ChannelType.DESKTOP, "default")
    assert result == "resultado remoto simulado"
    assert calls == [{"q": "hola"}]


def test_risk_level_declarado_no_es_autoritativo():
    """CA-08: `risk_level` es un input a `security_manager.register_action()`, no el
    veredicto final — si `security_manager` reclasifica la acción después del registro
    del tool, `require_confirmation()`/`execute_tool()` respetan la reclasificación."""
    register_tool(ToolSpec(
        name="_test_reclassified_tool",
        description="Tool de prueba para verificar que el riesgo declarado no es autoritativo",
        parameters_schema={"type": "object", "properties": {}},
        risk_level=RiskLevel.GREEN,
        invoke=lambda params: "no debería ejecutar",
    ))
    # Reclasificación posterior a YELLOW, fuera del registro del tool.
    security_manager.register_action("_test_reclassified_tool", RiskLevel.YELLOW)

    # DISCORD no admite YELLOW y no tiene adaptador de confirmación: denegado, fail-closed.
    with pytest.raises(ActionDenied):
        execute_tool("_test_reclassified_tool", {}, ChannelType.DISCORD, "default")


def test_execute_tool_no_registrado_deniega():
    with pytest.raises(ActionDenied):
        execute_tool("_tool_que_no_existe_jamas", {}, ChannelType.DESKTOP, "default")


def test_execute_tool_green_ejecuta_sin_confirmar(monkeypatch):
    def fail_input(*_a, **_kw):
        raise AssertionError("no debería pedir confirmación para un tool GREEN")

    monkeypatch.setattr("builtins.input", fail_input)

    result = execute_tool("task_list", {"user_id": "_test_user"}, ChannelType.TELEGRAM, "_test_user")
    assert isinstance(result, str)
