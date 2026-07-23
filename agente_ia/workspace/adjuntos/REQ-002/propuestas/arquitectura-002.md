# Arquitectura REQ-002 — Sistema de Agentes Interno

## Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| CA1 — AgentOrchestrator | `AgentOrchestrator` en `core/orchestrator.py`: recibe tarea, usa LLM para descomponer, selecciona/crea agentes, ejecuta cadena |
| CA2 — BaseAgent y agentes dinámicos | `BaseAgent` en `core/base_agent.py`: cada agente tiene nombre, prompt, tools, context, execute(). Se crean dinámicamente vía `DynamicAgentFactory` |
| CA3 — Comunicación entre agentes | Agentes se comunican a través del orchestrator (mediador): agente_A → orchestrator.forward_result(resultado, agente_B) |
| CA4 — Proactividad | `ProactiveEngine` en `core/proactive_engine.py` usa task_scheduler existente + registro de triggers por agente |
| CA5 — Integración existente | gateway.py llama orchestrator.process_task(). dispatcher.py y skill_manager.py se exponen como herramientas. Handlers existentes envueltos como AgentTool |
| CA6 — Logging y observabilidad | Cada paso del orchestrator loggea con logger.info() incluyendo duración, agente, tarea |

## Módulos a modificar

- `agente_ia/channels/gateway.py` — reemplazar dispatch directo por `orchestrator.process_task()`
- `agente_ia/router/dispatcher.py` — convertir en `AgentTool` disponible para agentes (sin eliminar ruta legacy)
- `agente_ia/main.py` — inicializar AgentOrchestrator y ProactiveEngine
- `agente_ia/skills/skill_manager.py` — exponer skills como `AgentTool` para que agentes las usen

## Nuevas clases/funciones

### `core/orchestrator.py`
- `class AgentOrchestrator` — singleton central
  - `process_task(text, channel, user_id) → str` — punto de entrada principal
  - `_decompose_task(task) → List[SubTask]` — usa LLM para partir tareas complejas
  - `_select_or_create_agent(sub_task) → BaseAgent` — crea/recupera agente adecuado
  - `_execute_agent_chain(sub_tasks) → str` — ejecuta agentes en cadena pasando resultados
  - `MAX_CHAIN_DEPTH = 5` — límite configurable

### `core/base_agent.py`
- `class BaseAgent(ABC)` — clase base abstracta
  - `name: str`, `description: str`, `system_prompt: str`
  - `tools: List[AgentTool]` — herramientas disponibles
  - `context: AgentContext` — memoria del agente
  - `can_handle(task: str) → float` — confianza 0-1
  - `execute(task: str, context: dict) → str` — ejecuta la tarea
  - `communicate(result: str, target_agent: str) → None` — envía resultado a otro agente

- `class AgentTool` — wrapper para funciones/herramientas
  - `name: str`, `description: str`, `function: Callable`
  - `execute(params: dict) → str` — ejecuta la herramienta

- `class DynamicAgentFactory` — crea agentes dinámicamente
  - `create_agent(task_description: str) → BaseAgent` — usa LLM para generar prompt y seleccionar tools

### `core/agent_context.py`
- `class AgentContextManager`
  - `get_context(agent_name, user_id) → AgentContext`
  - `update_context(agent_name, user_id, entry) → None`
  - `clear_context(agent_name, user_id) → None`
  - Persiste en SQLite (tabla `agent_context`)

- `class AgentContext`
  - `conversation: List[dict]` — historial del agente
  - `metadata: dict` — datos persistentes (preferencias, resultados previos)

### `core/proactive_engine.py`
- `class ProactiveEngine`
  - `register_agent(agent: BaseAgent, schedule: str, trigger: str) → None`
  - `start()` — inicia el scheduler
  - `stop()` — detiene el scheduler
  - `is_active: bool` — control global de proactividad
  - Usa `tasks/task_scheduler.py` como backend
  - Todas las acciones pasan por `SecurityManager` antes de ejecutarse

## Flujo de datos

```
Usuario → gateway.process(msg)
              ↓
  orchestrator.process_task(text, channel, user_id)
              ↓
    LLM: ¿tarea simple o multi-paso?
        ↓
    ┌─── simple: selector/creador de agente
    │       ↓
    │   BaseAgent.execute(task)
    │       ↓
    │   agente usa AgentTool (handler/skill/API)
    │       ↓
    │   resultado → respuesta
    │
    └─── compleja: _decompose_task()
            ↓
        [SubTask1, SubTask2, ...]
            ↓
        para cada sub-tarea:
            _select_or_create_agent(subtask)
                ↓
            agente_1.execute(subtask1)
                ↓
            orchestrator.forward_result(resultado, agente_siguiente)
                ↓
            agente_2.execute(subtask2, resultado_previo)
                ↓
            ... → resultado final → respuesta
```

## Archivos a modificar/crear

| Archivo | Acción |
|---------|--------|
| `agente_ia/core/orchestrator.py` | **CREAR** — AgentOrchestrator |
| `agente_ia/core/base_agent.py` | **CREAR** — BaseAgent, AgentTool, DynamicAgentFactory |
| `agente_ia/core/agent_context.py` | **CREAR** — AgentContextManager, AgentContext |
| `agente_ia/core/proactive_engine.py` | **CREAR** — ProactiveEngine |
| `agente_ia/core/__init__.py` | **MODIFICAR** — exportar nuevas clases |
| `agente_ia/channels/gateway.py` | **MODIFICAR** — integrar orchestrator |
| `agente_ia/router/dispatcher.py` | **MODIFICAR** — exponer como AgentTool |
| `agente_ia/skills/skill_manager.py` | **MODIFICAR** — exponer skills como AgentTool[] |
| `agente_ia/main.py` | **MODIFICAR** — init orchestrator + proactive engine |

## Dependencias nuevas
- Ninguna. Usa LLM existente (Claude/DeepSeek) para descomposición y creación de agentes.

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| LLM usado para descomposición y selección de agente → latencia adicional | Cache de agentes por tipo de tarea; timeout configurable por paso |
| Agentes dinámicos pueden generar prompts inconsistentes | Template validado para system_prompt; el factory usa un schema fijo |
| Comunicación síncrona entre agentes puede bloquear | Timeout por agente (default 30s); fallback a dispatcher legacy si timeout |
| Proactividad puede ejecutar acciones no deseadas | Todas las acciones pasan por SecurityManager; el usuario puede desactivar proactividad globalmente |
| Integración con gateway existente puede romper flujo actual | Modo "paralelo": orchestrator intenta, si falla → dispatcher legacy como fallback |

## Pruebas sugeridas

1. **CA1**: Enviar tarea simple → verificar que se selecciona/crea agente y ejecuta
2. **CA1**: Enviar tarea compleja ("investiga el clima y crea un archivo") → verificar descomposición en 2+ sub-tareas
3. **CA2**: Verificar que DynamicAgentFactory crea agente con prompt y tools adecuados
4. **CA3**: Enviar tarea multi-agente → verificar que resultado del agente_A llega al agente_B
5. **CA4**: Registrar trigger proactivo → verificar que se ejecuta en el horario programado
6. **CA5**: Ejecutar tarea existente (GET_TIME) → verificar que funciona igual que antes (no regression)
7. **CA6**: Verificar que cada acción de agente se registra en los logs
