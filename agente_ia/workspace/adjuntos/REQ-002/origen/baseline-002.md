# Baseline REQ-002

## Estado actual del sistema
- O.R.I.O.N. usa un dispatch plano (`router/dispatcher.py`) que mapea intents directamente a handlers o skills
- No existe orquestador ni concepto de agente especializado
- No hay contexto persistente por sub-sistema
- No hay capacidad proactiva (solo reactivo)
- La comunicación entre handlers/skills es inexistente (cada uno opera independientemente)

## Archivos que serán modificados (previsión)
- `agente_ia/router/dispatcher.py` — será wrapper del orquestador o reemplazado
- `agente_ia/channels/gateway.py` — integrar orquestador en el flujo de procesamiento
- `agente_ia/main.py` — inicializar AgentOrchestrator y ProactiveEngine
- `agente_ia/skills/skill_manager.py` — exponer skills como herramientas para agentes

## Archivos nuevos (previsión)
- `agente_ia/core/orchestrator.py` — AgentOrchestrator
- `agente_ia/core/base_agent.py` — BaseAgent
- `agente_ia/core/agent_context.py` — AgentContextManager
- `agente_ia/core/proactive_engine.py` — ProactiveEngine

## Tests existentes
- `tests/test_dispatcher.py` — 3 tests (CALCULATE, GET_TIME, SYSTEM_INFO) — todos PASS
- `tests/test_classifier.py` — 6 tests — todos PASS
- `tests/test_memory.py` — 2 tests — todos PASS
- `tests/test_autopilot.py` — 1 test — PASS

## Fallos pre-existentes (no atribuibles a este REQ)
- `pytest` no detecta tests legacy (usan `if __name__ == "__main__"` en vez de funciones `test_*`)
- Ningún fallo de compilación en los módulos afectados

## Decisiones de baseline
- Los handlers existentes se mantendrán como herramientas de los agentes (no se eliminan)
- El dispatch plano seguirá funcionando como fallback si el orquestador no puede resolver la tarea
- La integración será progresiva: primero orquestador + agente conversacional, luego más agentes
