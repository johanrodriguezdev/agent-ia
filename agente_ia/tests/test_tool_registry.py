"""
tests/test_tool_registry.py

REQ-006 — `agents/tool_registry.py` (CA-08, CA-14, CA-15, CA-16, CA-17).

Convenciones (.claude/rules/testing.md): sin red, sin mic/altavoces, `input()` siempre
mockeado cuando aplica.
"""

import dataclasses

import pytest

from agents.tool_registry import (
    ToolSpec,
    execute_tool,
    get_tool,
    has_explicit_task_id,
    register_tool,
)
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


# ─────────────────────────────────────────────
#  REQ-017 — task_complete_all, has_explicit_task_id, regex de ID ampliado
# ─────────────────────────────────────────────

def test_task_complete_all_completa_todas_las_pendientes(monkeypatch):
    """CA-01, CA-02: completa cada tarea pendiente devuelta y el mensaje enumera
    '#id - título' de cada una."""
    from tasks.task_manager import task_manager

    pending = [
        {"id": 1, "title": "lavar el auto"},
        {"id": 2, "title": "pagar la luz"},
    ]
    completed_calls = []

    monkeypatch.setattr(task_manager, "list_tasks", lambda *a, **k: pending)
    monkeypatch.setattr(
        task_manager, "complete_task",
        lambda task_id, user_id: completed_calls.append((task_id, user_id)) or True,
    )

    result = execute_tool(
        "task_complete_all", {"user_id": "_test_user"}, ChannelType.DESKTOP, "_test_user",
    )

    assert completed_calls == [(1, "_test_user"), (2, "_test_user")]
    assert "#1 - lavar el auto" in result
    assert "#2 - pagar la luz" in result
    assert "Completé 2 tareas" in result


def test_task_complete_all_cero_pendientes(monkeypatch):
    """Robustez (no CA literal): sin pendientes, no llama a complete_task y devuelve el
    mismo mensaje que usa hoy _task_complete_invoke() para 0 pendientes."""
    from tasks.task_manager import task_manager

    complete_calls = []
    monkeypatch.setattr(task_manager, "list_tasks", lambda *a, **k: [])
    monkeypatch.setattr(
        task_manager, "complete_task", lambda *a, **k: complete_calls.append(1) or True,
    )

    result = execute_tool(
        "task_complete_all", {"user_id": "_test_user"}, ChannelType.DESKTOP, "_test_user",
    )

    assert complete_calls == []
    assert "No tiene ninguna tarea pendiente" in result


def test_task_complete_all_respeta_limite_20(monkeypatch):
    """Casos borde de SPEC-017.md: list_tasks se llama con limit=20 explícito; con 20
    resultados, el mensaje incluye la nota de 'puede haber más'."""
    from tasks.task_manager import task_manager

    pending = [{"id": i, "title": f"tarea {i}"} for i in range(1, 21)]
    list_calls = []

    def fake_list_tasks(user_id, status="pending", limit=20):
        list_calls.append({"user_id": user_id, "status": status, "limit": limit})
        return pending

    monkeypatch.setattr(task_manager, "list_tasks", fake_list_tasks)
    monkeypatch.setattr(task_manager, "complete_task", lambda *a, **k: True)

    result = execute_tool(
        "task_complete_all", {"user_id": "_test_user"}, ChannelType.DESKTOP, "_test_user",
    )

    assert list_calls == [{"user_id": "_test_user", "status": "pending", "limit": 20}]
    assert "puede haber más" in result or "máximo de 20" in result


def test_task_complete_all_es_green_sin_confirmar(monkeypatch):
    """CA-08: mismo patrón que test_execute_tool_green_ejecuta_sin_confirmar — un tool
    GREEN nunca pide confirmación por input()."""
    from tasks.task_manager import task_manager

    def fail_input(*_a, **_kw):
        raise AssertionError("no debería pedir confirmación para task_complete_all (GREEN)")

    monkeypatch.setattr("builtins.input", fail_input)
    monkeypatch.setattr(task_manager, "list_tasks", lambda *a, **k: [])

    result = execute_tool(
        "task_complete_all", {"user_id": "_test_user"}, ChannelType.TELEGRAM, "_test_user",
    )
    assert isinstance(result, str)


def test_task_complete_all_pasa_por_gate(monkeypatch):
    """CA-07: security_manager.require_confirmation se llama con 'task_complete_all' ANTES
    de que se invoque cualquier task_manager.complete_task."""
    from tasks.task_manager import task_manager

    call_order = []

    original_require_confirmation = security_manager.require_confirmation

    def spy_require_confirmation(action_name, channel, **kwargs):
        call_order.append(("require_confirmation", action_name))
        return original_require_confirmation(action_name, channel, **kwargs)

    monkeypatch.setattr(security_manager, "require_confirmation", spy_require_confirmation)
    monkeypatch.setattr(task_manager, "list_tasks", lambda *a, **k: [{"id": 1, "title": "x"}])
    monkeypatch.setattr(
        task_manager, "complete_task",
        lambda *a, **k: call_order.append(("complete_task", a)) or True,
    )

    execute_tool("task_complete_all", {"user_id": "_test_user"}, ChannelType.DESKTOP, "_test_user")

    assert call_order[0] == ("require_confirmation", "task_complete_all")
    assert call_order[1][0] == "complete_task"


def test_delete_task_yellow_sigue_bloqueado_en_lote():
    """CA-09: regresión — delete_task (YELLOW, ya clasificado en security_manager.py:316)
    sigue bloqueado sin confirmación por un canal sin adaptador (TELEGRAM), exactamente
    igual que antes de REQ-017. No depende de código nuevo de este REQ."""
    allowed = security_manager.require_confirmation("delete_task", ChannelType.TELEGRAM, user_id="_test_user")
    assert allowed is False


def test_has_explicit_task_id_variantes():
    """CA-05, CA-06: has_explicit_task_id() reconoce 'tarea #3', 'numero 3', un '#3'
    suelto, y devuelve False para texto sin ningún ID."""
    assert has_explicit_task_id("completa la tarea #3") is True
    assert has_explicit_task_id("completa la tarea numero 3") is True
    assert has_explicit_task_id("de todas mis tareas, la #3 ya la hice") is True
    assert has_explicit_task_id("completa todas mis tareas pendientes") is False


def test_task_complete_invoke_id_suelto_con_hash(monkeypatch):
    """CA-06: regresión del regex ampliado — un '#3' suelto (sin tarea/numero/id delante)
    extrae task_id=3 correctamente."""
    from agents.tool_registry import _task_complete_invoke
    from tasks.task_manager import task_manager

    calls = []
    monkeypatch.setattr(
        task_manager, "complete_task", lambda task_id, user_id: calls.append((task_id, user_id)) or True,
    )

    result = _task_complete_invoke({"text": "la #3 ya la hice", "user_id": "_test_user"})

    assert calls == [(3, "_test_user")]
    assert "#3" in result


def test_task_complete_invoke_regex_existente_sin_cambios(monkeypatch):
    """CA-05, regresión: 'completa la tarea numero 3' sigue extrayendo task_id=3 (rama del
    regex que ya existía, grupo 1)."""
    from agents.tool_registry import _task_complete_invoke
    from tasks.task_manager import task_manager

    calls = []
    monkeypatch.setattr(
        task_manager, "complete_task", lambda task_id, user_id: calls.append((task_id, user_id)) or True,
    )

    result = _task_complete_invoke({"text": "completa la tarea numero 3", "user_id": "_test_user"})

    assert calls == [(3, "_test_user")]
    assert "#3" in result
