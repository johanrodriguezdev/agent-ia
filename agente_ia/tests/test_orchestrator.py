"""
tests/test_orchestrator.py

Cobertura de `core/orchestrator.py::_decompose()` (REQ-007, CA-12) — fix del bug de
substring (p.ej. "y" matcheando dentro de "hoy") vía `\\b` word boundary + safety net de
longitud mínima por parte.

También cubre CA-17: `AgentOrchestrator` ya no tiene `register_tool()`/`self._tools` tras
la migración a `agents/tool_registry.py` (ver `agents/skill_tools.py`).
"""
from core.orchestrator import AgentOrchestrator


def test_ca12_no_descompone_cuando_el_trigger_es_substring():
    """"y" no debe matchear dentro de "Yolanda" — antes del fix, `"y" in text.lower()`
    partía "me llamo Yolanda" en fragmentos sin sentido."""
    orch = AgentOrchestrator()
    result = orch._decompose("me llamo Yolanda")
    assert result == ["me llamo Yolanda"]


def test_ca12_descompone_con_trigger_como_palabra_completa():
    orch = AgentOrchestrator()
    result = orch._decompose("compra pan y luego café")
    # El trigger "y" está primero en `_DECOMPOSE_TRIGGERS` y ya matchea (\by\b) antes de
    # llegar a "luego" — el split ocurre en el primer trigger que produce un resultado
    # válido, no necesariamente el "más específico".
    assert len(result) == 2
    assert result[0] == "compra pan"
    assert result[1] == "luego café"


def test_ca12_red_de_seguridad_descarta_partes_triviales():
    """"él y tú vamos" matchea `\\by\\b` pero produce partes de 2-3 caracteres — el safety
    net `all(len(p) > 3 for p in parts)` descarta el split y retorna el texto completo."""
    orch = AgentOrchestrator()
    result = orch._decompose("él y tú vamos")
    assert result == ["él y tú vamos"]


def test_ca17_orchestrator_ya_no_tiene_register_tool():
    """CA-17: `register_tool()`/`self._tools` se eliminan de `AgentOrchestrator` — el
    catálogo de tools ahora vive únicamente en `agents/tool_registry.py`."""
    orch = AgentOrchestrator()
    assert not hasattr(orch, "register_tool")
    assert not hasattr(orch, "_tools")
