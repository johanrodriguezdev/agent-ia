# Contexto REQ-059 — Los pasos del turno se guardan con la respuesta

## Resumen ejecutivo
REQ-053 dejó dicho: «los pasos no se persisten: solo el turno en vivo los muestra. Se
puede sumar después sin cambiar la interfaz». Es esto. Los pasos («Buscando en internet:
…», «Mirando la imagen: …») se guardan junto a la respuesta del agente y vuelven al
reabrir la conversación, plegados encima de cada respuesta igual que en vivo. La
transparencia de qué hizo el agente ya no dura solo mientras la ventana está abierta.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** MEMORIA
- **Tipo:** MEJORA

## Origen
Noche del 2026-09-20, aprobación en bloque de Johan; pendiente explícito de REQ-053.

## Decisiones tomadas
2026-09-20 | conversación principal | Columna `pasos_json TEXT` en `memories`, agregada por la misma migración aditiva de REQ-013 (`_migrate_schema`, `ADD COLUMN` sin reescribir la tabla) | Es lo más chico que resuelve el problema: nada de tablas nuevas ni de tocar `store()`, que usan main.py y los canales.
2026-09-20 | conversación principal | `store_turn(pasos=...)` guarda el JSON con un `UPDATE` sobre la fila `assistant` recién creada, y solo si hay pasos | La firma de `store()` no cambia; un fallo al guardar pasos se registra y no tumba el turno, que ya está guardado.
2026-09-20 | conversación principal | `MemoryItem.pasos` (lista, vacía por defecto) y `_MEMORY_COLUMNS` con la columna nueva; JSON corrupto o con elementos que no son texto se lee como lista vacía / filtrada | Una base vieja o una fila tocada a mano no pueden romper la carga de una conversación.
2026-09-20 | conversación principal | Tope de 40 pasos guardados (el mismo techo por turno de REQ-053) | Protege de un reportero desbocado.
2026-09-20 | conversación principal | El bridge manda `pasos` en `turns_loaded` solo cuando hay, y a `store_turn` solo cuando hay | Los dobles de test con la firma vieja no conocen el kwarg (mismo patrón que `modo`, `prior_turns`, `image_path`).

## Archivos
- Tocados: `ai/memory_manager.py` (`pasos_json`, `MemoryItem.pasos`, `_pasos_de`,
  `store_turn(pasos=)`, `_guardar_pasos`), `ui/webview/bridge.py` (`_on_resolve_done`,
  `_on_turns_loaded`), `js/chat.js` (comentario).
- Tests: `tests/test_pasos_persistidos.py` (7, nuevo).

## Qué puede hacer ahora
- Reabrir una conversación de ayer y ver, encima de cada respuesta, «2 pasos · Buscando
  en internet · Leyendo la página», como cuando llegó.

## Verificación
- Suite completa: ver `pruebas/suite-059.txt`.

## Prueba manual sugerida (Johan)
1. Preguntar algo que use herramientas; cerrar la conversación (Nuevo chat) y volver a
   abrirla desde Recientes: los pasos siguen ahí.
2. Conversaciones anteriores a esta noche: sin pasos (no se inventan).

## Log de transiciones
2026-09-20 | — → NUEVO → EN_DESARROLLO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión (pipeline acortado, autorización en bloque).
