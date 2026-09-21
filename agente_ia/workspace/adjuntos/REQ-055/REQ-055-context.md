# Contexto REQ-055 — Regenerar y editar en el chat

## Resumen ejecutivo
Las dos acciones que toda app de chat tiene y aquí faltaban (la única acción por mensaje
era «Copiar», y solo en las respuestas):

1. **Regenerar** — en la última respuesta del agente. Borra el último intercambio de la
   conversación guardada y vuelve a mandar el mismo mensaje del usuario (con su imagen,
   si la tenía). La respuesta que no convenció desaparece y llega otra en su lugar; la
   conversación no acumula las dos.
2. **Editar** — en el último mensaje del usuario. Quita el par de la conversación, deja
   el texto escrito en el cuadro (sin el marcador del adjunto) y devuelve el adjunto al
   chip. No manda nada solo: el usuario corrige y envía.
3. **Copiar** también en los mensajes del usuario.

Ambas solo se ven en el último intercambio y nunca mientras el agente responde.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** UI (toca MEMORIA: `memory.delete_last_turn`)
- **Tipo:** MEJORA

## Origen
Plan de la noche del 2026-09-20, aprobado en bloque por Johan («te apruebo todo lo que
necesites para seguir trabajando toda la noche»).

## Decisiones tomadas
2026-09-20 | conversación principal | Regenerar/Editar solo en el último intercambio (`marcarUltimos()` + clase `es-ultimo`) | Regenerar una respuesta del medio dejaría la conversación contando otra historia a partir de ahí; editar un mensaje viejo, lo mismo.
2026-09-20 | conversación principal | El borrado del par va por `memory.delete_last_turn()`, que solo borra si las dos últimas filas son `user`+`assistant` del mismo usuario, y saca sus embeddings de la RAM sin recargar toda la base | Es la única escritura nueva; acotada a propósito. `delete_conversation` recarga todo porque borra mucho; acá son dos filas.
2026-09-20 | conversación principal | No pide confirmación (a diferencia de borrar la conversación, 🟡) | Es una acción de edición del propio chat, iniciada con un click en el mensaje, y el usuario ve el efecto en el acto (las dos burbujas se van y llega la nueva o el texto vuelve al cuadro). Queda en el log a nivel info.
2026-09-20 | conversación principal | Si «Regenerar»/«Editar» llegan mientras `store_turn` sigue escribiendo el turno recién terminado, la acción se encola y corre en `_tras_guardar_turno()` | `store_turn` calcula embeddings en otro hilo y tarda; borrar "el último par" en ese instante borraría el ANTERIOR. Es la carrera más probable: el usuario hace click apenas ve la respuesta.
2026-09-20 | conversación principal | `send_message` se partió en `send_message` (consume el adjunto pendiente) + `_iniciar_turno` (el cuerpo) | Regenerar reenvía el texto guardado, que ya trae el marcador; pasar por `_con_adjunto` consumiría un adjunto pendiente ajeno.
2026-09-20 | conversación principal | Editar devuelve el adjunto al chip con `attach_file(ruta)` si el archivo sigue existiendo | El mensaje corregido viaja con la misma imagen sin buscarla otra vez.

## Archivos
- Tocados: `ai/memory_manager.py` (`delete_last_turn`, `_olvidar_embeddings`),
  `ui/webview/bridge.py` (`regenerate_last`, `edit_last`, `_iniciar_turno`, cola
  `_accion_tras_guardar`, señales `last_turn_removed`/`composer_text_requested`),
  `js/chat.js` (`accionesDelUsuario`, `marcarUltimos`, `removeLastTurn`), `js/composer.js`
  (`setComposerText`, clase `turno-en-curso`), `js/bridge_client.js`, `js/app.js`,
  `index.html` (icono `ic-refresh`), `css/chat.css`.
- Tests: `tests/test_memory_manager_delete_last_turn.py` (4, nuevo),
  `test_webview_bridge.py` (+8), `test_webview_buttons.py` (+2).

## Qué puede hacer ahora
- Pasar el mouse por la última respuesta → «Regenerar»: la respuesta se va y llega otra.
- Pasar el mouse por tu último mensaje → «Editar»: vuelve al cuadro para corregirlo (con
  su imagen o archivo en el chip) y Enter lo manda de nuevo.
- «Copiar» en cualquier mensaje tuyo.

## Qué no hace todavía
- Editar o regenerar un mensaje del medio de la conversación.
- Historial de versiones de una respuesta (ver la anterior después de regenerar).

## Verificación
- Suite completa: ver `pruebas/suite-055.txt`.
- Capturas offscreen: `pruebas/acciones_dark.png`, `pruebas/acciones_light.png` (acciones
  forzadas visibles: Copiar en todos; Editar solo en el último mensaje del usuario;
  Regenerar solo en la última respuesta). Sin errores de JS.

## Prueba manual sugerida (Johan)
1. Preguntar algo; sobre la respuesta, click en «Regenerar» apenas aparezca: la
   respuesta se va, tu pregunta queda y llega otra respuesta. En Recientes la
   conversación sigue siendo una sola.
2. Click en «Editar» sobre tu último mensaje: desaparecen tu mensaje y la respuesta, el
   texto queda en el cuadro con el cursor al final; corregir y Enter.
3. Con una imagen pegada: «Editar» devuelve la imagen al chip; «Regenerar» vuelve a
   mandarla (el agente la ve otra vez).
4. Mientras el agente responde, ni «Regenerar» ni «Editar» aparecen.

## Log de transiciones
2026-09-20 | — → NUEVO → EN_DESARROLLO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión (pipeline acortado, autorización en bloque).
