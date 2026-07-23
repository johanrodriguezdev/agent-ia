# SPEC-003 — Memoria Avanzada

**Estado:** ⏸️ ESPERANDO VALIDACIÓN
**Categoría:** MEMORIA
**Tipo:** MEJORA
**Fecha:** 2026-07-20

## Objetivo
Transformar el sistema de memoria actual en un sistema unificado, eficiente e inteligente con RAG (Retrieval-Augmented Generation), ciclo de vida de recuerdos, auto-resumen de conversaciones y contexto multiusuario correcto.

## Alcance
- Incluye:
  - Unificar `memory_manager.py` + `semantic_memory.py` + `user_manager.py` en un solo `UnifiedMemory` con interface única
  - Migrar `claude_brain.py` para usar memoria por usuario en lugar de global
  - Búsqueda semántica vectorizada con numpy (cargar embeddings en RAM, cosine similarity vectorizada)
  - Ciclo de vida: importancia (score 0-1), decaimiento (TTL por nivel de importancia), consolidación
  - Auto-resumen parcial cada 10 mensajes y resumen final al cerrar sesión
  - Comando "qué recuerdas de mí" con respuesta estructurada
- No incluye:
  - FAISS/ChromaDB como dependencia (se usa numpy para vectorización)
  - Cifrado de la base de datos
  - Interfaz gráfica para gestionar memoria

## Módulos afectados
- `agente_ia/ai/memory_manager.py` — reemplazar por nuevo `UnifiedMemory`
- `agente_ia/ai/semantic_memory.py` — reemplazar por nuevo sistema vectorial
- `agente_ia/ai/user_manager.py` — adaptar para usar UnifiedMemory
- `agente_ia/ai/claude_brain.py` — migrar a memoria por usuario
- `agente_ia/core/agent_context.py` — integrar con UnifiedMemory (opcional)
- `agente_ia/executor/handlers.py` — actualizar handle_recall_memory
- `agente_ia/main.py` — inicializar UnifiedMemory

## Comportamiento actual vs deseado

| Actual | Deseado |
|--------|---------|
| Dos sistemas paralelos (global + por usuario) sin coordinación | Sistema unificado `UnifiedMemory` con almacén por usuario y fallback a global |
| Búsqueda semántica O(n) scan completo de SQLite fila por fila | Carga de embeddings en numpy array al inicio, cosine similarity vectorizada O(n) pero 100x más rápida |
| MEMORY.md crece sin límite, se inyecta completo en cada prompt | MEMORY.md con límite de tamaño, solo las N líneas más relevantes se inyectan |
| Sin importancia ni decaimiento — todos los recuerdos pesan igual | Cada recuerdo con score 0-1, los de baja importancia se archivan automáticamente |
| Sin resúmenes automáticos | Resumen parcial cada 10 mensajes + resumen final al cerrar sesión |
| Sin comando de consulta de memoria | "Qué recuerdas de mí" devuelve resumen estructurado de los recuerdos más importantes |

## Criterios de aceptación

### CA1 — Unificación
- [ ] `UnifiedMemory` singleton con métodos: `store`, `search_semantic`, `search_keyword`, `get_summary`, `get_important_memories`
- [ ] Cada usuario tiene su propio namespace de memoria (aislamiento)
- [ ] Los módulos existentes migran a UnifiedMemory sin duplicación de datos

### CA2 — Búsqueda vectorial optimizada
- [ ] Los embeddings se cargan en un numpy array al iniciar el sistema
- [ ] La búsqueda semántica usa cosine similarity vectorizada (numpy, no loop Python)
- [ ] Tiempo de búsqueda < 50ms incluso con 10,000+ recuerdos
- [ ] Los nuevos embeddings se agregan al array en memoria y se persisten a SQLite

### CA3 — Ciclo de vida
- [ ] Cada recuerdo tiene `importance_score` (0.0 - 1.0)
- [ ] Recuerdos con score < 0.3 se archivan después de 7 días
- [ ] Recuerdos con score > 0.8 se marcan como "importantes" y no se archivan
- [ ] Existe un mecanismo de consolidación que fusiona recuerdos duplicados o muy similares

### CA4 — Auto-resumen
- [ ] Cada 10 mensajes en una sesión, se genera un resumen parcial automático
- [ ] Al salir (Ctrl+C o comando "salir"), se genera un resumen de toda la sesión
- [ ] Los resúmenes se almacenan como recuerdos con importance_score ≥ 0.7
- [ ] Los resúmenes son inyectados en el prompt del sistema de Claude como contexto relevante

### CA5 — Consulta de memoria
- [ ] El comando "qué recuerdas de mí" o "háblame de mí" responde con una síntesis de los recuerdos más importantes del usuario
- [ ] La respuesta incluye: nombre, preferencias, datos personales (no sensibles), eventos importantes, últimos resúmenes
- [ ] Si no hay recuerdos, responde "aún no tengo recuerdos tuyos"

### CA6 — Inyección de contexto multiusuario
- [ ] `claude_brain.py` usa la memoria del usuario actual, no la global
- [ ] El perfil de usuario (MEMORY.md per-user) se inyecta en el prompt del sistema
- [ ] El contexto inyectado no excede 2000 tokens (se trunca por relevancia)

## Casos borde
- ¿Qué pasa si el usuario habla en múltiples canales (Telegram + CLI)? → Misma memoria por user_id
- ¿Qué pasa si hay 100,000 recuerdos? → Límite de 10,000 recuerdos activos, los más antiguos se archivan
- ¿Qué pasa si el resumen falla (sin API key)? → Se omite el resumen, la memoria sigue funcionando sin él
- ¿Qué pasa si dos recuerdos tienen el mismo embedding? → Se fusionan en uno solo con score combinado

## Asumidos
- ASUMIDO: Se usa `numpy` para vectorización (ya disponible como dependencia transitiva)
- ASUMIDO: El embedding model `all-MiniLM-L6-v2` ya está cargado en `embedding_engine.py`
- ASUMIDO: Los resúmenes usan el LLM configurado (Claude/DeepSeek) — si no hay LLM, se omite el resumen
