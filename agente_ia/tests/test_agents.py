import sys
sys.path.insert(0, ".")

def test_ca1_orchestrator():
    from core.orchestrator import AgentOrchestrator
    orch = AgentOrchestrator()
    assert orch is not None
    print("[PASS] CA1: AgentOrchestrator creado")
    assert hasattr(orch, "process_task")
    print("[PASS] CA1: process_task existe")
    assert hasattr(orch, "_decompose")
    print("[PASS] CA1: _decompose existe")
    assert hasattr(orch, "_execute_agent_chain")
    print("[PASS] CA1: _execute_agent_chain existe")
    return orch

def test_ca2_base_agent():
    from core.base_agent import BaseAgent, AgentTool, DynamicAgentFactory
    from abc import ABC
    assert issubclass(BaseAgent, ABC)
    print("[PASS] CA2: BaseAgent es ABC")
    tool = AgentTool("test_tool", "una herramienta de prueba", lambda p: "ok")
    assert tool.name == "test_tool"
    assert tool.description == "una herramienta de prueba"
    print("[PASS] CA2: AgentTool creado correctamente")
    factory = DynamicAgentFactory()
    agent = factory.create_agent("calcular 2+2", [tool])
    assert agent is not None
    assert agent.name.startswith("Agent_")
    assert len(agent.tools) == 1
    print(f"[PASS] CA2: Agente dinamico creado: {agent.name}")
    score = agent.can_handle("test")
    assert score == 0.8
    print("[PASS] CA2: can_handle retorna confianza")

def test_ca3_comunicacion():
    from core.base_agent import AgentTool, DynamicAgentFactory
    tool = AgentTool("calc", "calcula", lambda p: "42")
    factory = DynamicAgentFactory()
    a1 = factory.create_agent("calcular", [tool])
    a2 = factory.create_agent("formatear", [tool])
    msg = a1.communicate("resultado: 42", a2.name)
    assert msg["from"] == a1.name
    assert msg["to"] == a2.name
    assert msg["result"] == "resultado: 42"
    print("[PASS] CA3: Comunicacion entre agentes funciona")

def test_ca4_proactividad():
    from core.proactive_engine import ProactiveEngine, ProactiveTrigger
    from core.base_agent import DynamicAgentFactory, AgentTool
    pe = ProactiveEngine()
    assert pe.is_active == True
    print("[PASS] CA4: ProactiveEngine creado, activo por defecto")
    pe.is_active = False
    assert pe.is_active == False
    print("[PASS] CA4: Proactividad desactivada globalmente")
    pe.is_active = True
    assert pe._should_fire is not None
    print("[PASS] CA4: Metodo _should_fire existe")

def test_ca5_contexto():
    from core.agent_context import AgentContextManager
    cm = AgentContextManager()
    ctx = cm.get_context("test_agent", "user1")
    assert ctx.agent_name == "test_agent"
    assert ctx.user_id == "user1"
    print("[PASS] CA5: Contexto creado correctamente")
    cm.update_context("test_agent", "user1", {"role": "user", "content": "hola"})
    ctx2 = cm.get_context("test_agent", "user1")
    assert len(ctx2.conversation) >= 1
    print(f"[PASS] CA5: Contexto guarda historial ({len(ctx2.conversation)} entries)")
    cm.clear_context("test_agent", "user1")
    ctx3 = cm.get_context("test_agent", "user1")
    assert len(ctx3.conversation) == 0
    print("[PASS] CA5: Contexto limpiado correctamente")

if __name__ == "__main__":
    print("=== Testing REQ-002: Sistema de Agentes ===\n")
    test_ca1_orchestrator()
    test_ca2_base_agent()
    test_ca3_comunicacion()
    test_ca4_proactividad()
    test_ca5_contexto()
    print("\n=== 5/5 CRITERIOS ESTRUCTURALES PASS ===")
