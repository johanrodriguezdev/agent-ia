# Contexto REQ-003 — Memoria Avanzada

## Resumen ejecutivo
Mejorar el sistema de memoria de O.R.I.O.N. unificando los sistemas paralelos (global y por usuario), implementando RAG con búsqueda vectorial eficiente, ciclo de vida de memoria (importancia, decaimiento, consolidación), auto-resumen de conversaciones, y fijando la inyección de contexto multiusuario.

## Estado actual
- **Estado tracker:** EN_PRUEBAS
- **Último agente:** conversación principal (verificación 2026-09-09)
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

---

## Actualización 2026-09-09 — la verificación que nunca se hizo

El contexto había quedado congelado en el paso del coordinador y el REQ figuraba en
`EN_PRUEBAS` sin una sola evidencia: era el único REQ viejo en esa situación. Se verificó
contra el código y **midiendo**, no leyendo la SPEC. Resultado completo en
`pruebas/test-results-003.md`.

**16 de 20 checks verificados, ninguno fallido, 4 sin verificar.**

Lo implementado está más completo de lo que el tracker sugería: `UnifiedMemory` con los
cinco métodos que pedía CA1, búsqueda vectorizada de verdad, archivado por score con corte
de 7 días exactamente como se especificó, el skill de "qué recuerdas de mí", y la inyección
por usuario en `claude_brain.py`.

**CA2 medido, que era su promesa sin comprobar:** entre 17 y 28 ms de mediana segun la carga del equipo, con 10.000 recuerdos, contra los 50 ms del criterio. El banco de pruebas quedó como
`pruebas/benchmark-ca2.py` para poder repetirlo. Dato que conviene tener a la vista: el
índice ocupa 14,6 MB en RAM con 10.000 recuerdos, así que el límite de 10.000 activos que la
propia SPEC previó no es un detalle sino lo que mantiene esto sano.

**Lo único sin verificar es CA4 (auto-resumen).** No encontré el disparador "cada 10
mensajes", pero sí `core/compaction.py`, que llegó después y resuelve la misma necesidad por
otro camino: destila los turnos viejos en un resumen cuando la conversación crece. Es el
mismo patrón que apareció en REQ-012 y REQ-010 — el problema se resolvió, el criterio quedó
escrito contra un diseño que caducó.

## Decisiones tomadas
2026-09-09 | conversación principal | No se avanza el estado a EN_QA | 4 checks quedaron sin verificar; moverlo diría que se probó todo, y no es cierto
2026-09-09 | conversación principal | No se implementa el disparador "cada 10 mensajes" de CA4 | Antes de escribir código hay que decidir si `compaction.py` ya lo cubre. Implementarlo por cumplir la letra sería agregar un segundo mecanismo que hace casi lo mismo

## Pendiente para Johan
1. ¿CA4 se cierra como superado por `core/compaction.py`, o querés el resumen cada N mensajes además?
2. Falta la auditoría de `orion-qa` y tu prueba manual.

## Log de transiciones
2026-09-09 | (contexto desactualizado) → EN_PRUEBAS documentado | conversación principal | Verificación de 20 criterios + benchmark de CA2
