# Contexto REQ-003 — Memoria Avanzada

## Resumen ejecutivo
Mejorar el sistema de memoria de O.R.I.O.N. unificando los sistemas paralelos (global y por usuario), implementando RAG con búsqueda vectorial eficiente, ciclo de vida de memoria (importancia, decaimiento, consolidación), auto-resumen de conversaciones, y fijando la inyección de contexto multiusuario.

## Estado actual
- **Estado tracker:** NUEVO
- **Último agente:** orion-coordinador
- **Fecha última actualización:** 2026-07-20
- **Rama git:** (pendiente)
- **Categoría:** MEMORIA
- **Tipo de cambio:** MEJORA

## Decisiones tomadas
2026-07-20 | orion-coordinador | REQ creado — categoría=MEMORIA | Elección humana: Memoria Avanzada
2026-07-20 | orion-spec | SPEC aprobada | Aprobado por johanrodriguezdev
2026-07-20 | orion-spec | Tipo de cambio: MEJORA | Identificado en la entrevista
2026-07-20 | orion-spec | Vector search: numpy vectorizado (no FAISS), resumenes: parcial + final | Clarificación con humano
2026-07-20 | orion-baseline | Baseline documentado — 3 sistemas paralelos identificados | Ver origen/baseline-003.md

## Log de transiciones
2026-07-20 | — → NUEVO | orion-coordinador | REQ creado
2026-07-20 | NUEVO → EN_SPEC | orion-spec | Inicio de spec
2026-07-20 | EN_SPEC → SPEC_APROBADO | orion-spec | SPEC aprobada por humano
