# Contexto REQ-002 — Sistema de Agentes Interno

## Resumen ejecutivo
Implementar un sistema de agentes internos en O.R.I.O.N. que reemplace el dispatcher plano actual por un orquestador central capaz de delegar tareas a sub-agentes especializados con contexto propio, permitir colaboración multi-paso entre agentes, y habilitar comportamiento proactivo.

## Estado actual
- **Estado tracker:** EN_DESARROLLO
- **Último agente:** orion-dev
- **Fecha última actualización:** 2026-07-20
- **Rama git:** feature/REQ-002-sistema-agentes
- **Categoría:** CORE
- **Tipo de cambio:** FEATURE_NUEVA

## Decisiones tomadas
2026-07-20 | orion-coordinador | REQ creado — categoría=CORE | Elección humana: CORE
2026-07-20 | orion-spec | SPEC aprobada | Aprobado por johanrodriguezdev
2026-07-20 | orion-spec | Tipo de cambio: FEATURE_NUEVA | Identificado en la entrevista
2026-07-20 | orion-spec | Agents: dinámicos, comunicación directa, proactivos | Clarificación con humano
2026-07-20 | orion-baseline | Baseline documentado — 4 archivos modificados, 4 nuevos | Ver origen/baseline-002.md
2026-07-20 | orion-architect | Arquitectura diseñada: AgentOrchestrator + BaseAgent + ProactiveEngine | Ver propuestas/arquitectura-002.md
2026-07-20 | orion-architect | Arquitectura aprobada | Aprobado por johanrodriguezdev
2026-07-20 | orion-dev | Implementación completa: 4 archivos nuevos, 5 modificados | Ver propuestas/desarrollo-log-002.md

## Descartado (y por qué)
- Agentes como procesos separados (hilos/threads): descartado, ejecutan en event loop principal
- Comunicación asíncrona entre agentes: descartado, comunicación síncrona vía orchestrator
- Agentes como archivos .py persistentes: descartado, son instancias en memoria creadas dinámicamente

## Log de transiciones
2026-07-20 | — → NUEVO | orion-coordinador | REQ creado
2026-07-20 | NUEVO → EN_SPEC | orion-spec | Inicio de spec
2026-07-20 | EN_SPEC → SPEC_APROBADO | orion-spec | SPEC aprobada por humano
2026-07-20 | SPEC_APROBADO → EN_BASELINE | orion-baseline | Baseline iniciado
2026-07-20 | EN_BASELINE → EN_ARQUITECTURA | orion-baseline | Baseline completado
2026-07-20 | EN_ARQUITECTURA → ARQUITECTURA_APROBADA | orion-architect | Arquitectura aprobada por humano
2026-07-20 | ARQUITECTURA_APROBADA → EN_DESARROLLO | orion-dev | Implementación completada
