# Baseline REQ-003

## Estado actual del sistema
O.R.I.O.N. tiene 3 sistemas de memoria paralelos y no coordinados:

### 1. Global (`ai/memory_manager.py` + `ai/semantic_memory.py`)
- `SESSION_MEMORY` — lista en RAM volátil del historial de la sesión actual
- `ai/memory.db` — SQLite global con `user_input`, `jarvis_response`, `timestamp`
- `ai/semantic_memory.db` — SQLite global con `text`, `embedding_json` (384 floats), `timestamp`
- Búsqueda semántica: scan O(n) fila por fila, cosine similarity en Python puro

### 2. Por usuario (`ai/user_manager.py`)
- Cada usuario tiene `users_data/<user_id>/` con `memory.db`, `semantic_memory.db`, `MEMORY.md`, `preferences.json`
- Mismos schemas que los globales — datos duplicados entre global y por usuario

### 3. Claude Brain (`ai/claude_brain.py`)
- Usa MEMORY.md global (raíz del proyecto), NO la del usuario
- Inyecta MEMORY.md completo en el system prompt (crece sin límite)
- `save_memory` append lines a MEMORY.md sin consolidación

### Problemas identificados
| Problema | Impacto |
|----------|---------|
| Dos sistemas paralelos escribiendo a DBs separadas | Datos duplicados, lecturas inconsistentes |
| Búsqueda semántica O(n) fila por fila | Lento con >100 recuerdos |
| MEMORY.md crece sin límite | Consume tokens del system prompt |
| claude_brain usa memoria global, no por usuario | Contexto incorrecto en multiusuario |
| Sin importancia/decaimiento | Memoria irrelevante persiste igual que la importante |

## Archivos que serán modificados (previsión)
- `agente_ia/ai/memory_manager.py` — reemplazar
- `agente_ia/ai/semantic_memory.py` — reemplazar
- `agente_ia/ai/user_manager.py` — adaptar
- `agente_ia/ai/claude_brain.py` — migrar a memoria por usuario
- `agente_ia/executor/handlers.py` — actualizar handle_recall_memory
- `agente_ia/main.py` — inicializar UnifiedMemory

## Tests existentes
- `tests/test_memory.py` — 2 tests (store + retrieve semantic) — PASS

## Fallos pre-existentes
- Ninguno. Todos los tests de memoria pasan.
