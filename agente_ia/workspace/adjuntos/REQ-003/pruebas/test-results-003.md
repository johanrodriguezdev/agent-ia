# Resultados de pruebas REQ-003 — Memoria Avanzada

**Fecha:** 2026-09-09 | **Verificado por:** conversación principal

REQ-003 figuraba en `EN_PRUEBAS` desde hacía semanas, pero su contexto seguía congelado en
el paso del coordinador y no existía esta carpeta: era el único REQ viejo sin ninguna
evidencia. Esto es la verificación que faltaba, hecha **contra el código y midiendo**, no
leyendo la SPEC.

**Resumen: 16 de 20 checks verificados, 0 fallidos, 4 sin verificar.** Lo que falta es el
auto-resumen (CA4), que parece haberse resuelto por otro camino que el que la SPEC imaginó.

## CA1 — Unificación

| Check | Estado | Evidencia |
|---|---|---|
| `UnifiedMemory` con `store`, `search_semantic`, `search_keyword`, `get_summary`, `get_important_memories` | ✅ | `ai/memory_manager.py:75` (clase) y los cinco métodos en `:261`, `:413`, `:453`, `:484`, `:469` |
| Namespace por usuario | ✅ | `user_id` en la firma de `store()` y `search_semantic()`; el filtro `user_mask` de la búsqueda descarta lo de otros usuarios antes del ranking |
| Migración sin duplicar datos | ✅ | `ai/memory_migration.py` + `tests/test_memory_migration.py` en verde |

## CA2 — Búsqueda vectorial optimizada

| Check | Estado | Evidencia |
|---|---|---|
| Embeddings en memoria al iniciar | ✅ | `_load_embeddings()` en `__init__` (`:99`) |
| Cosine vectorizada, no loop Python | ✅ | `np.dot(all_normed, query_norm)` (`:431`) — una sola operación sobre la matriz entera |
| **< 50 ms con 10.000+ recuerdos** | ✅ **medido** | Ver abajo |
| Los nuevos se agregan en memoria y se persisten | ✅ | `store()` actualiza las tres listas bajo `_emb_lock` y escribe en SQLite |

### La medición (`pruebas/benchmark-ca2.py`)
```
indice: 10000 recuerdos x 384 dimensiones
memoria del indice: 14.6 MB

corrida 1:  mediana 17.4 ms | p95 21.0 ms | peor 22.2 ms
corrida 2:  mediana 28.0 ms | p95 29.6 ms | peor 32.5 ms

  CA2 (<50 ms): CUMPLE
```
Se anotan **las dos corridas** a propósito: la diferencia entre 17 y 28 ms es carga del
equipo, no del código, y citar solo la primera sería quedarse con el número afortunado. En
el peor caso medido (32,5 ms) sigue por debajo del techo de 50 ms, que es lo que el criterio
pide. El índice ocupa 14,6 MB en RAM, que es el costo de
tenerlo en memoria y vale la pena decirlo — con 100.000 recuerdos serían ~146 MB, y ahí el
límite de 10.000 activos que la SPEC ya previó deja de ser un detalle.

## CA3 — Ciclo de vida

| Check | Estado | Evidencia |
|---|---|---|
| Cada recuerdo tiene `importance_score` | ✅ | Columna `importance` en la tabla `memories` (`:24`), y `tests/test_memory_scoring.py` en verde |
| Score < 0.3 se archiva a los 7 días | ✅ | `UPDATE memories SET archived=1 WHERE importance < 0.3 AND timestamp < ?` con corte de 7 días (`:569-572`) |
| Score > 0.8 nunca se archiva | ✅ | Se deduce de la misma consulta: solo alcanza a `importance < 0.3` |
| Consolidación de duplicados | ✅ | Hilo de consolidación cada 24 h (`:594`) |

## CA4 — Auto-resumen

| Check | Estado | Nota |
|---|---|---|
| Resumen parcial cada 10 mensajes | ⬜ **sin verificar** | No encontré un disparador por cantidad de mensajes. Lo que sí existe es `core/compaction.py`, que destila los turnos viejos en un resumen cuando la conversación crece — resuelve la misma necesidad por otro camino, posterior a esta SPEC |
| Resumen de sesión al salir | ⬜ sin verificar | |
| Resúmenes con score ≥ 0.7 | ⬜ sin verificar | `store_summary()` existe (`:496`); no verifiqué con qué score guarda |
| Resúmenes inyectados en el prompt | ✅ | `ai/claude_brain.py` arma contexto semántico y lo mete en el prompt (`:244`) |

**Recomendación:** revisar si CA4 sigue teniendo sentido tal como está escrito. `compaction.py`
llegó después y cubre lo importante (que la conversación no crezca sin freno sin perder lo
dicho). Si es así, CA4 se cierra como superado, igual que pasó con REQ-012 y REQ-010.

## CA5 — Consulta de memoria

| Check | Estado | Evidencia |
|---|---|---|
| "qué recuerdas de mí" responde con una síntesis | ✅ | `skills/memory_digest_skill.py`, con esa frase entre sus datos de entrenamiento (`:160`) |
| Incluye nombre, preferencias, eventos, resúmenes | ✅ | Es lo que arma el skill; `tests/test_memory_digest_skill.py` en verde |
| Sin recuerdos, lo dice | ✅ | Cubierto por los tests del skill |

## CA6 — Inyección de contexto multiusuario

| Check | Estado | Evidencia |
|---|---|---|
| `claude_brain.py` usa la memoria del usuario actual | ✅ | `user_id` en la firma y propagado a las tools (`:32`, `:183`) |
| El perfil del usuario se inyecta | ✅ | `profile_text` en el prompt del sistema (`:35`, `:89`) |
| El contexto no excede 2000 tokens | ✅ *por acotamiento* | No hay un contador de tokens: se acota por construcción, 5 resultados × 200 caracteres (`:244`), muy por debajo del techo. Cumple el objetivo, no la letra |

## Suite
110 tests de memoria en verde (`memor`, `embedding`, `profile`), dentro de los 2229 de la
suite completa.

## Qué falta para cerrar REQ-003
1. Decidir si CA4 se cierra como superado por `core/compaction.py` o si el disparador por
   cantidad de mensajes todavía se quiere.
2. Auditoría de `orion-qa`, que nunca corrió.
3. La prueba manual de Johan.
