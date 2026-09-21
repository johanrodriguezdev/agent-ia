# Contexto REQ-064 — Regenerar y Editar desde cualquier punto de la conversación

## Resumen ejecutivo
REQ-055 solo permitía regenerar la última respuesta o editar el último mensaje. Ahora
**cualquier** mensaje guardado ofrece «Editar» (los tuyos) y «Regenerar» (las
respuestas). Sobre uno del medio, la conversación **vuelve a ese mensaje** y lo que vino
después se descarta —con una confirmación que dice cuántos mensajes se van («4 mensajes
posteriores»)—; en el último par no hay nada después y no se pregunta. Sin ramas: hacer
ramas como ChatGPT sería otro proyecto, y Johan aprobó esta forma al pedir la mejora.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** UI (toca MEMORIA)
- **Tipo:** MEJORA

## Origen
Johan, 2026-09-21 por la mañana: «¿Y podemos trabajarle a lo que no hace todavía?». Se le
avisó que el camino sería truncar con confirmación (no ramas) y siguió adelante.

## Decisiones tomadas
2026-09-21 | conversación principal | Truncar con confirmación, no ramas | Es lo que hacen las apps sin ramas; las ramas exigirían otro modelo de datos y otra barra lateral.
2026-09-21 | conversación principal | La confirmación es la acción 🟡 `chat_rewind` (misma familia que `delete_conversation`), con «N mensajes posteriores» en el detalle; sin mensajes posteriores no se pregunta | Borrar lo que vino después es destructivo; el último par ya era el caso sin confirmación de REQ-055.
2026-09-21 | conversación principal | Las burbujas llevan el id de su fila (`dataset.id`): las del historial desde `turns_loaded`, las del turno en vivo cuando `store_turn` termina (`turn_ids_assigned`) | Mapear por posición fallaba con un par que terminó en error (se ve, no se guarda). Un mensaje sin id no ofrece los botones salvo que sea el último par (camino de REQ-055).
2026-09-21 | conversación principal | `store_turn` devuelve `(id user, id assistant)`; `delete_turns_from` exige que el id sea una fila `user` de esa conversación y de ese usuario | Un id de otra conversación o de una respuesta no puede borrar nada.
2026-09-21 | conversación principal | El flujo (contar posteriores → confirmar → borrar) corre en el worker con el turno reservado, y al volver comprueba que la conversación siga siendo la misma | Igual que Regenerar/Editar del último par tras las revisiones de la noche.

## Archivos
- Tocados: `ai/memory_manager.py` (`store_turn` → ids, `turnos_posteriores`,
  `delete_turns_from`), `ui/webview/bridge.py` (`regenerate_from`, `edit_from`,
  `_rebobinar*`, señales `turn_ids_assigned`/`turns_removed_from`),
  `core/security_manager.py` (`chat_rewind` 🟡), `core/acciones_legibles.py`, `js/chat.js`
  (`preguntaDe`, `marcarUltimos` con `con-id`, `assignTurnIds`, `removeTurnsFrom`),
  `js/bridge_client.js`, `js/app.js`, `css/chat.css`.
- Tests: memoria (+4), bridge (+6), webview_buttons (+1).

## Qué puede hacer ahora
- Pasar el mouse por cualquier respuesta vieja → «Regenerar» → modal «¿Confirmás que
  vuelva la conversación a un mensaje anterior y borre lo que vino después? … 4 mensajes
  posteriores» → la conversación queda hasta esa pregunta y llega la respuesta nueva.
- «Editar» sobre un mensaje tuyo del medio → misma confirmación → el texto vuelve al
  cuadro (con sus adjuntos) y lo posterior desaparece.

## Qué no hace todavía
- Ramas (conservar las dos versiones).
- Deshacer un rebobinado (lo borrado se va; el modal es la última defensa).

## Verificación
- Suite completa: ver `pruebas/suite-064.txt`.
- Captura offscreen: `pruebas/medio_dark.png` (Editar/Regenerar visibles en un par del medio).

## Prueba manual sugerida (Johan)
1. En una conversación de 3 o más intercambios, «Regenerar» en la primera respuesta:
   aparece el modal con la cantidad; confirmar → quedan la primera pregunta y una
   respuesta nueva; Recientes sigue con una sola conversación.
2. Cancelar el modal: no cambia nada.
3. «Editar» en un mensaje tuyo del medio: vuelve al cuadro; corregir y Enter.
4. En el último par, ni Regenerar ni Editar preguntan (como hasta ahora).

## Log de transiciones
2026-09-21 | — → NUEVO → EN_DESARROLLO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión (pipeline acortado, pedido de Johan).
