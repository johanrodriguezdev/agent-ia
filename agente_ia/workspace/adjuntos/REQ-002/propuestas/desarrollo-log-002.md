# Desarrollo REQ-002 — Sistema de Agentes Interno

## Archivos creados
- `agente_ia/core/base_agent.py` — BaseAgent (ABC), AgentTool, DynamicAgentFactory, _DynamicAgentInstance
- `agente_ia/core/agent_context.py` — AgentContextManager, AgentContext (persistencia SQLite)
- `agente_ia/core/orchestrator.py` — AgentOrchestrator con descomposición, cadena de agentes, fallback
- `agente_ia/core/proactive_engine.py` — ProactiveEngine con triggers por horario, startup, hourly

## Archivos modificados
- `agente_ia/core/__init__.py` — exporta orchestrator, base_agent, agent_context, proactive_engine
- `agente_ia/router/dispatcher.py` — añadido dispatch_as_tool() para uso como AgentTool
- `agente_ia/skills/skill_manager.py` — añadido get_agent_tools() que expone skills como AgentTool[]
- `agente_ia/channels/gateway.py` — dispatch directo reemplazado por orchestrator.process_task()
- `agente_ia/main.py` — inicializa orchestrator con tools, dispatcher, classifier; inicia proactive_engine

## Arquitectura implementada
- **Orquestador** recibe task, intenta dispatch rápido (intents conocidos), si no → crea agentes dinámicos
- **Agentes dinámicos** se crean vía DynamicAgentFactory con prompt generado y tools disponibles
- **Comunicación** entre agentes vía orchestrator.forward_result() (mediador síncrono)
- **Proactividad** con engine independiente que verifica triggers cada 60s
- **Contexto** persistido en SQLite (agent_context.db) con 50 entradas máximas por agente/usuario

## Flujo de datos
gateway.process() → orchestrator.process_task() → _try_quick_dispatch() (si intent conocido)
                                                      → _process_with_agents() (si no)
                                                          → _decompose() (multi-paso)
                                                          → _execute_single_agent() o _execute_agent_chain()

## Dependencias agregadas
- Ninguna (usa SQLite stdlib, threading stdlib)

## Decisiones de implementación
- dispatch rápido como primera opción para evitar latencia del LLM en tareas simples
- Agentes en cache por hash de tarea (misma tarea = mismo agente reutilizado)
- ProactiveEngine como hilo separado, no bloquea el event loop principal
- Todas las acciones proactivas pasan por SecurityManager
- Contexto limitado a 50 entradas por agente/usuario para evitar crecimiento infinito
