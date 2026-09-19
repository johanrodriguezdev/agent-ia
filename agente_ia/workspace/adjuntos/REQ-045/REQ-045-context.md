# Contexto REQ-045 — Discord con confirmaciones y sin bloquear el bot

## Resumen ejecutivo
Discord no tenía adaptador de confirmación: toda acción amarilla —y toda herramienta MCP—
se denegaba fail-closed por ese canal aunque el usuario estuviera delante. Y el bot
procesaba cada turno del agente **dentro** de la corutina, con el event loop de discord.py
parado (sin heartbeats ni otros mensajes) todo el tiempo que el agente pensara. Ahora
Discord confirma como Telegram (mismo adaptador, otro transporte), el turno corre en un
hilo, y las herramientas MCP se pueden habilitar para Discord.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Último agente:** conversación principal (sesión nocturna autorizada por Johan, 2026-09-19)
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** BOT · **Tipo:** MEJORA + SEGURIDAD

## Origen
Hallazgo 13 de la revisión de código (`/code-review`) de REQ-043: se ofrecían `discord` y
`voice` como canales para herramientas MCP sin adaptador de confirmación. Al mirar
`channels/discord_bot.py` para ponerle uno apareció el bloqueo del event loop. Johan pidió
seguir mejorando solo al terminar las cuatro recomendaciones.

## Qué cambia para el usuario (ejemplos)
- Por Discord, *«@agente cerrá Chrome»* → el bot pregunta «¿Quiere que cierre una
  aplicación: chrome?» y un «sí» (sin mencionarlo) la ejecuta. Antes: «No puedo ejecutar
  esa acción» siempre.
- Habilitar una herramienta MCP para Discord (*«habilitale search para desktop y
  discord»* o la casilla en Configuración) y usarla desde el servidor de Discord con
  confirmación.
- Mientras el agente piensa por Discord, el bot sigue respondiendo (y puede recibir el
  «sí»); antes se quedaba sordo hasta terminar.

## Decisiones tomadas
<!-- FECHA | AGENTE | DECISIÓN | MOTIVO -->
2026-09-19 | conversación principal | `TelegramConfirmationAdapter` pasa a llamarse `ChatConfirmationAdapter` (alias con el nombre viejo conservado) y Discord es una subclase que solo redefine `_send_message` | La reserva por usuario, la espera con timeout, el «sí» y la limpieza son idénticos; copiarlos sería tener dos adaptadores que divergen (el mismo problema que REQ-044 arregló entre bucles). Los 33 tests de Telegram pasan sin cambios. Fijado por test: los únicos miembros propios del de Discord son `_send_message` y `_enviar`.
2026-09-19 | conversación principal | La respuesta «sí» se lee ANTES del filtro de mención en `on_message` | Quien contesta una pregunta no vuelve a mencionar al bot. Solo puede tener una confirmación pendiente quien ya fue atendido (y por tanto autorizado): `resolve()` no crea nada.
2026-09-19 | conversación principal | El turno (mención y `/noddoo`) corre con `asyncio.to_thread`, con reserva especulativa + contexto antes y liberación después | Copia exacta del patrón de `channels/telegram_bot.py::_procesar_con_confirmacion` (REQ-018/021). Sin el hilo, el «sí» no podía llegar nunca: el bot estaba bloqueado esperándolo.
2026-09-19 | conversación principal | `user_id` de la reserva/resolución = `str(message.author.id)`; al gateway sigue viajando `canonical_user_id("discord", …)` | Son dos claves con dos usos: la primera empareja pregunta y respuesta en el adaptador, la segunda identifica al usuario en memoria y auditoría. Igual que Telegram.
2026-09-19 | conversación principal | `CANALES_HABILITABLES = ("desktop", "telegram", "discord")`; `voice` sigue fuera | Voz es solo verde por política (`security-levels.md`): no hay nada que confirmar.
2026-09-19 | conversación principal | Sin botones/reacciones de Discord para confirmar | Un solo criterio de «sí» en todos los canales (CA-06 de REQ-018). Se puede sumar después sin tocar el adaptador.

## Descartado (y por qué)
- Un adaptador de confirmación para voz — la política de voz es solo verde.
- Extraer `on_message` entero a una función testeable — el cambio útil está en los dos
  helpers (`_responder_confirmacion`, `_procesar_con_confirmacion`), que sí se prueban.

## Prueba manual sugerida (para Johan)
1. Con el bot de Discord arrancado, mencionarlo con *«cerrá el bloc de notas»* → debe
   preguntar en el canal y, con un «sí» (sin mención), ejecutar. Con «no», cancelar.
2. Mencionarlo con algo que tarde (*«investigá qué es MCP»*) y, mientras piensa, escribir
   otra cosa: el bot no debe quedar «sin respuesta» ni desconectarse.
3. En Configuración → Conexiones, marcar «Discord» en un servidor MCP y usar la
   herramienta desde Discord: debe confirmar y ejecutar.

## Verificación
- `tests/test_discord_confirmation_adapter.py`: 11 passed (nuevo).
- `tests/test_telegram_confirmation_adapter.py`: 33 passed sin cambios;
  `tests/test_discord_bot.py`: 7 passed.
- Suite completa: ver "Log de transiciones".

## Riesgos activos
- El bot de Discord no se probó contra Discord real esta noche (no hay token en el entorno
  de tests, y no se toca red): la integración de `on_ready`/`on_message` está escrita
  siguiendo la de Telegram y lo testeable está testeado, pero el primer arranque real es
  de Johan.

## Log de transiciones
2026-09-19 | — → NUEVO | conversación principal | REQ creado vía update-tracker.mjs
2026-09-19 | NUEVO → LISTO_PARA_COMMIT | conversación principal (sesión nocturna) | 8 criterios de SPEC-045 cumplidos. Suite completa: **2995 passed, 0 failed** (sin `test_webview_smoke.py`). Prueba manual contra Discord real pendiente de Johan.
