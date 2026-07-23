# Arquitectura REQ-003 — Memoria Avanzada

## Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| CA1 — Unificación | `UnifiedMemory` singleton reemplaza memory_manager + semantic_memory + user_manager. Un solo punto de entrada |
| CA2 — Búsqueda vectorial | `numpy` array en RAM con todos los embeddings. Cosine similarity vectorizada con `np.dot` |
| CA3 — Ciclo de vida | `importance_score` en cada recuerdo. Archivero diario que mueve recuerdos caducos a `_archive` |
| CA4 — Auto-resumen | `SummarizationEngine`: cada 10 mensajes genera resumen parcial; al salir genera resumen final |
| CA5 — Consulta | `get_memory_summary()` consolida recuerdos importantes + perfil + últimos resúmenes |
| CA6 — Contexto multiusuario | `claude_brain.py` recibe `user_id` y usa `UnifiedMemory.for_user(user_id)` |

## Módulos a modificar

| Archivo | Acción |
|---------|--------|
| `agente_ia/ai/memory_manager.py` | **REEMPLAZAR** — ahora es UnifiedMemory |
| `agente_ia/ai/semantic_memory.py` | **ELIMINAR** — funcionalidad integrada en UnifiedMemory |
| `agente_ia/ai/user_manager.py` | **ADAPTAR** — delegar a UnifiedMemory en lugar de DB propia |
| `agente_ia/ai/claude_brain.py` | **MODIFICAR** — aceptar user_id, usar UnifiedMemory |
| `agente_ia/executor/handlers.py` | **MODIFICAR** — handle_recall_memory usa UnifiedMemory |
| `agente_ia/main.py` | **MODIFICAR** — inicializar UnifiedMemory |

## Nuevas clases/funciones

### `ai/memory_manager.py` (reemplazo completo)

- `class MemoryItem` — dataclass con: text, embedding, importance (0-1), timestamp, category, user_id, archived
- `class UnifiedMemory` — singleton, punto de entrada único
  - `for_user(user_id) → UserMemoryView` — vista aislada por usuario
  - `store(text, category, importance, user_id)` — guarda recuerdo + embedding
  - `search_semantic(query, user_id, top_k=5, threshold=0.7) → List[MemoryItem]`
  - `search_keyword(query, user_id) → List[MemoryItem]`
  - `get_important_memories(user_id, min_score=0.7) → List[MemoryItem]`
  - `get_summary(user_id) → str` — síntesis de recuerdos importantes
  - `consolidate()` — archiva recuerdos caducos, fusiona duplicados
  - `_load_embeddings()` — carga numpy array desde SQLite al inicio
  - `_rebuild_index()` — reconstruye numpy array desde DB
- `class UserMemoryView` — vista de memoria para un usuario específico
  - `store(text, category, importance)`
  - `search(query)`, `get_summary()`, `get_profile()`
  - `update_profile(key, value)`

### `ai/summary_engine.py` (nuevo)

- `class SummaryEngine`
  - `should_summarize(session_msg_count) → bool` — cada 10 mensajes
  - `generate_partial_summary(conversation_history) → str` — resume últimos mensajes
  - `generate_final_summary(session_history) → str` — resume toda la sesión
  - `_call_llm(prompt) → str` — usa el LLM configurado

### `ai/profile_manager.py` (nuevo)

- `class ProfileManager`
  - `get_profile_text(user_id, max_tokens=2000) → str` — perfil truncado por tokens
  - `update_profile(user_id, key, value)` — agrega/cambia info del perfil
  - `_count_tokens(text) → int` — estimación simple de tokens

## Flujo de datos

```
store():
  texto → embedding (embedding_engine) → MemoryItem
    → SQLite (persistente)
    → numpy array (RAM para búsqueda)

search_semantic():
  query → embedding
    → np.dot(normalized_query, normalized_embeddings.T) → scores
    → argsort → top_k resultados
    → filtrar por threshold + user_id
    → devolver MemoryItems

summarize():
  cada 10 mensajes →
    SummaryEngine.generate_partial_summary(últimos 10 mensajes)
    → UnifiedMemory.store(resumen, category="summary", importance=0.7)
  
  al salir →
    SummaryEngine.generate_final_summary(sesión completa)
    → UnifiedMemory.store(resumen, category="final_summary", importance=0.9)
```

## Dependencias nuevas
- Ninguna (numpy ya es dependencia transitiva de sentence-transformers)

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| Carga de embeddings al inicio lenta con muchos recuerdos | Carga lazy: solo los embeddings de los últimos N días; el resto se carga bajo demanda |
| numpy array en RAM consume memoria con 100k+ recuerdos | 100k × 384 floats × 4 bytes ≈ 150 MB — aceptable para una app de escritorio |
| Resumen con LLM puede fallar sin API key | SummaryEngine detecta si LLM está disponible; si no, omite resumen |
| Migración de datos existentes puede perder información | Script de migración: lee DBs existentes y las importa al nuevo formato |

## Pruebas sugeridas
1. Almacenar 100 recuerdos → buscar semánticamente → verificar tiempo < 50ms
2. Almacenar recuerdo con importance=0.2, esperar consolidación → verificar que se archiva
3. Enviar 12 mensajes → verificar que se genera resumen parcial en el mensaje 10
4. Llamar a "qué recuerdas de mí" → verificar respuesta estructurada
5. Usar dos user_ids diferentes → verificar que las búsquedas no se mezclan
