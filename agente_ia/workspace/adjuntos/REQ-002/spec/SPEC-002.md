# SPEC-002 — Sistema de Agentes Interno

**Estado:** ⏸️ ESPERANDO VALIDACIÓN
**Categoría:** CORE
**Tipo:** FEATURE_NUEVA
**Fecha:** 2026-07-20

## Objetivo
Reemplazar el dispatch plano actual por un **orquestador central de agentes** que cree dinámicamente sub-agentes especializados según la tarea, les asigne contexto propio, permita comunicación directa entre ellos para tareas multi-paso, y habilite comportamiento proactivo (agentes que actúan sin orden directa basados en horario/eventos).

## Alcance
- Incluye:
  - `AgentOrchestrator` — recibe tareas, las descompone, selecciona/crea agentes
  - `BaseAgent` — clase base con contexto propio, prompt, herramientas, capacidad de comunicación
  - Agentes dinámicos (se crean según la tarea, no hay lista fija)
  - Sistema de comunicación entre agentes (mensajes con resultados)
  - `ProactiveEngine` — scheduler que activa agentes por horario o eventos
  - `AgentContextManager` — persistencia de contexto por agente entre sesiones
  - Integración con el gateway existente (reemplazar dispatch donde corresponda)
- No incluye:
  - UI visual para gestionar agentes (sería REQ de UI)
  - Agentes con acceso a internet propio (usan los canales ya existentes)
  - Sistema de plugins de terceros para agentes

## Módulos afectados
- `agente_ia/core/orchestrator.py` — nuevo: AgentOrchestrator
- `agente_ia/core/base_agent.py` — nuevo: BaseAgent
- `agente_ia/core/agent_context.py` — nuevo: AgentContextManager
- `agente_ia/core/proactive_engine.py` — nuevo: ProactiveEngine
- `agente_ia/agents/` — nuevo: agentes especializados (los que el orquestador decida crear)
- `agente_ia/channels/gateway.py` — integrar con orquestador
- `agente_ia/router/dispatcher.py` — wrapper o reemplazo por orquestador
- `agente_ia/main.py` — inicializar orquestador y proactive engine
- `agente_ia/skills/skill_manager.py` — posible integración (skills como herramientas de agentes)

## Comportamiento actual vs deseado

| Actual | Deseado |
|--------|---------|
| Dispatch plano: intent → handler único | Orquestador que decide qué agente(s) ejecutan la tarea |
| Sin contexto por sub-sistema | Cada agente tiene contexto propio y persistente |
| Sin comunicación entre handlers | Agentes se pasan resultados directamente |
| Solo reactivo (responde comandos) | Agentes pueden actuar proactivamente |
| Skills como funciones sin estado | Skills/herramientas como capacidades de los agentes |

## Criterios de aceptación

### CA1 — AgentOrchestrator
- [ ] `AgentOrchestrator` recibe una tarea y la descompone en sub-tareas
- [ ] Selecciona o crea dinámicamente el agente especializado para cada sub-tarea
- [ ] Si la tarea es simple (un solo dominio), la delega directamente sin descomposición
- [ ] Retorna error claro si no puede resolver la tarea

### CA2 — BaseAgent y agentes especializados
- [ ] `BaseAgent` tiene: nombre, contexto propio, prompt, herramientas, método `execute(task)` y `communicate(message)`
- [ ] Los agentes se crean dinámicamente según la tarea (no hay lista fija en código)
- [ ] Cada agente puede acceder a herramientas del sistema (skills, handlers existentes)

### CA3 — Comunicación entre agentes
- [ ] Un agente puede enviar un mensaje con resultado a otro agente
- [ ] El agente receptor puede usar ese resultado como entrada para su tarea
- [ ] El orquestador recibe el resultado final después de la cadena de agentes
- [ ] Timeout configurable para comunicación entre agentes

### CA4 — Proactividad
- [ ] `ProactiveEngine` tiene un scheduler que activa agentes en horarios definidos
- [ ] Los agentes pueden registrar triggers proactivos (horario, evento del sistema)
- [ ] Las acciones proactivas pasan por SecurityManager (niveles verde/amarillo/rojo)
- [ ] El usuario puede desactivar la proactividad globalmente

### CA5 — Integración con sistema existente
- [ ] gateway.py usa el orquestador en lugar del dispatch directo
- [ ] Los handlers y skills existentes funcionan como herramientas de los agentes
- [ ] Todas las funciones actuales siguen operativas (no hay regression)
- [ ] La memoria y contexto de agentes persiste entre sesiones

### CA6 — Logging y observabilidad
- [ ] Cada acción de agente se registra con `logger.info()` incluyendo agente, tarea, duración
- [ ] El orquestador registla la cadena de agentes utilizada para cada tarea
- [ ] Errores de agentes se registran sin silenciar excepciones

## Casos borde
- ¿Qué pasa si un agente no puede completar su tarea? → Retorna error al orquestador, que intenta agente alternativo o devuelve error al usuario
- ¿Qué pasa si la comunicación entre agentes falla (timeout)? → El orquestador reintenta una vez, luego falla con mensaje claro
- ¿Qué pasa si no hay agente adecuado para la tarea? → Orquestador usa Claude Brain como fallback
- ¿Qué pasa si el usuario pide algo que requiere 5+ agentes en cadena? → Límite configurable de profundidad (default 5)
- ¿Proactividad en Telegram/Discord? → Solo notificaciones, nunca acciones destructivas sin confirmación

## Asumidos
- ASUMIDO: Los agentes NO tienen hilos/processos propios — ejecutan en el event loop principal
- ASUMIDO: La comunicación entre agentes es síncrona dentro de una tarea (no mensajería asíncrona)
- ASUMIDO: Los agentes se crean en memoria (no se guardan como archivos .py) — son instancias dinámicas
- ASUMIDO: La proactividad usa el scheduler existente (`tasks/task_scheduler.py`) como base
