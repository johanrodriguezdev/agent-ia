# Contexto REQ-048 — Confirmación hablada en el canal VOICE, y MCP por voz

## Resumen ejecutivo
La voz tenía dos caras: en la app con manos libres, un pedido por voz corre como canal
escritorio y ya se confirmaba hablando («…diga: confirmo»); en el modo consola por voz
(`python main.py`, opciones 2/3) corre como canal `VOICE`, que no tenía a quién preguntar
y denegaba toda acción amarilla. Ahora `voice/voice_channel_adapter.py` pregunta por TTS
y escucha una captura; solo «confirmo» autoriza. Con eso, `voice` pasa a ser un canal
habilitable para herramientas MCP.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Último agente:** conversación principal (sesión autorizada por Johan, 2026-09-19)
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** VOZ · **Tipo:** MEJORA + SEGURIDAD

## Decisiones tomadas
2026-09-19 | conversación principal | Se reutiliza `voice_confirmation.evalua_respuesta` y `mensaje_hablado`: mismo criterio («confirmo», fail-closed en todo lo demás) que el manos libres | Un solo criterio de qué autoriza por voz. Un «sí» sigue sin valer: aparece en cualquier conversación de fondo.
2026-09-19 | conversación principal | El adaptador escucha UNA captura con `listen_command()` en el mismo hilo que ejecuta la acción | En la consola ese hilo es el principal, el mismo que entre turnos abre el micrófono: no hay dos lectores a la vez. Sin el bucle de wake word no hay otro hilo que pueda entregar la respuesta.
2026-09-19 | conversación principal | La política general de VOICE sigue en verde; MCP llega por `CHANNEL_ACTION_EXCEPTIONS` cuando el usuario habilita «voz» para ese servidor | Es el mismo mecanismo que Telegram/Discord (REQ-018): excepciones aditivas por acción, nunca abrir el canal entero.
2026-09-19 | conversación principal | `main.py` registra el adaptador para `ChannelType.VOICE` junto al de escritorio | Es el único punto de entrada del modo consola.

## Qué puede hacer ahora
- En consola por voz: *«buscá en Notion las notas de la reunión»* (con `search` habilitado para voz) → el agente pregunta en voz alta «¿Quiere que use la herramienta 'search' del servidor MCP 'notion'? Si está de acuerdo, diga: confirmo» → «confirmo» → ejecuta.
- En la app con manos libres ya funcionaba igual (queda fijado por test).

## Verificación
- `tests/test_voice_channel_adapter.py`: 17 passed (nuevo).
- `tests/test_voice_confirmation.py`, `test_mcp_config.py`, `test_webview_mcp.py`, `test_discord_confirmation_adapter.py`: verdes con `voice` en `CANALES_HABILITABLES`.

## Riesgos activos
- No se probó con micrófono real (tests sin audio por regla). La captura usa `listen_command()` con su timeout de 8 s: si el usuario tarda más en decir «confirmo», deniega.

## Log de transiciones
2026-09-19 | — → NUEVO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión.
