# Contexto REQ-044 — Paridad de canales: Telegram/Discord al bucle nativo, y techo de salida en voz

## Resumen ejecutivo
Cierra las dos deudas que REQ-027 dejó escritas (P-3 y P-4). Telegram y Discord razonan
ahora igual que el escritorio: los resultados de herramientas viajan como historial neutral
(`core/tool_history.py`, traducido a `tool_use`/`tool_result` por cada adaptador), se
ejecutan todas las tool calls de la vuelta, y al agotar el presupuesto o ante una denegación
hay una llamada de cierre sin herramientas que redacta con lo reunido. La voz tiene un techo
de 500 tokens de salida por construcción: una respuesta larga por TTS son minutos que nadie
puede cortar.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Último agente:** conversación principal (sesión nocturna autorizada por Johan, 2026-09-18)
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** CORE · **Tipo:** MEJORA + DEUDA TÉCNICA

## Origen
`REQ-027-context.md`, decisiones del 2026-09-08: *P-3: `ai/claude_brain.py` NO migra a
nativo en este REQ … queda registrado como REQ candidato, con la deuda reconocida: Telegram
sigue razonando peor que el escritorio.* Y *P-4: tope de tokens para voz queda fuera de
alcance … candidato a REQ chico posterior: techo de salida por canal, ~500 tokens en VOICE.*
La revisión del 2026-09-18 lo puso segundo en la lista que Johan aprobó en bloque.

## Qué cambia para el usuario (ejemplos)
- Por Telegram: *«buscá el clima de Villavicencio y decime qué hora es allá»* → el modelo
  pide las dos herramientas en una vuelta y las dos se ejecutan; antes se ejecutaba una,
  y la otra costaba una vuelta más del presupuesto de 5.
- Por Telegram, si pide algo que el canal no permite: antes «No puedo ejecutar esa
  accion: …» a secas; ahora el agente explica qué no puede hacer desde ahí y responde con lo
  que sí averiguó.
- Por voz: la respuesta se corta en ~500 tokens (unos 40 s de lectura) aunque el modelo
  quisiera explayarse. En escritorio y Telegram no cambia nada (4096).

## Qué NO cambia (y por qué)
- El presupuesto remoto sigue en 5 vueltas con herramientas: SPEC-027 lo fijó porque fuera
  del escritorio no hay botón de detener. Ahora es la misma constante
  (`TECHO_CANAL_NO_ESCRITORIO`) en los dos caminos, no dos números que coincidían por
  casualidad.
- Telegram/Discord siguen sin modos del composer (son de escritorio) y sin streaming.

## Decisiones tomadas
<!-- FECHA | AGENTE | DECISIÓN | MOTIVO -->
2026-09-18 | conversación principal | Pipeline acortado; spec en `spec/SPEC-044.md`; sin documento de arquitectura aparte | El diseño es el de REQ-027 (`arquitectura-027.md`) aplicado al segundo camino: no hay decisiones nuevas de estructura, solo reutilización.
2026-09-18 | conversación principal | `_resolver_con_tools()` conserva firma y contrato; `ask_claude()` no cambia | `tests/test_claude_brain.py` (CA-15 de REQ-022) y el gateway la llaman así. La migración es interna al módulo.
2026-09-18 | conversación principal | Se reusa `core/reasoning_loop.ejecutar_vuelta()` (antes `_ejecutar_vuelta`, ahora pública con alias del nombre viejo) en vez de copiar la lógica | D-5, D-6 y CA-25/26/27 de REQ-027 (ids normalizados, resultado sintético para las no ejecutadas, la denegación corta y el fallo no) viven en un solo sitio. Copiarlas sería volver a tener dos bucles que divergen, que es el problema que este REQ arregla.
2026-09-18 | conversación principal | `ejecutar_vuelta(..., cancelable=False)` en el camino remoto | `abortar_si_cancelado()` compara `_turno_cancelado == _turno_actual` a nivel de proceso: un turno de escritorio cancelado y sin turno nuevo abortaría un mensaje de Telegram que corre en otro hilo. Fijado por test (CA-06).
2026-09-18 | conversación principal | El historial por usuario (`_conversation_histories`) sigue guardando solo texto; el historial neutral es del turno | Persistir bloques `tool_use`/`tool_result` entre mensajes obligaría a que CADA turno futuro los mande al proveedor, y `compactar()` no sabe resumirlos. El escritorio hace lo mismo (`prior_turns` son texto).
2026-09-18 | conversación principal | Cierre sin herramientas con las mismas instrucciones del escritorio (`_INSTRUCCION_CIERRE_*`), importadas de `reasoning_loop` | Una sola redacción de "qué hacer cuando se acaba" para los dos caminos. Si el cierre no sirve, queda el texto enlatado de siempre (mismo criterio que CA-31 de REQ-027).
2026-09-18 | conversación principal | `MAX_TOOL_ROUNDS` desaparece; el presupuesto es `TECHO_CANAL_NO_ESCRITORIO` | Dos constantes que coincidían en 5 por casualidad. Fijado por test: `not hasattr(claude_brain, "MAX_TOOL_ROUNDS")`.
2026-09-18 | conversación principal | Techo de voz como context manager thread-local `ai/llm_provider.tope_de_salida(n)` + `_max_tokens_salida()` en los 5 adaptadores, sin tocar la firma de `generate_response()` | Mismo patrón que `core/streaming.permitido()`. Enhebrar `max_tokens` por `generate_response` → `_cached_call` → `_uncached_call` → 5 adaptadores tocaba 8 firmas y la clave de caché para un parámetro que solo importa en un canal. `min()` con `MAX_TOKENS_SALIDA`: ningún caller puede subir el techo general, que protege a los modelos gratuitos.
2026-09-18 | conversación principal | El tope se aplica solo a las llamadas que producen LA respuesta (bucle y cierre de `run()`), no a las herramientas que consulten al modelo por su cuenta | Un resumen interno de una página web cortado a 500 tokens degradaría la respuesta sin que nadie lo vea; el problema de P-4 es lo que se lee en voz alta.
2026-09-18 | conversación principal | `MAX_TOKENS_VOZ = 500` | Lo que SPEC-027/P-4 propuso ("~500"). Unos 40 s de lectura por TTS, que ya es mucho para una conversación hablada. Fijado por test.

## Descartado (y por qué)
- Reusar `reasoning_loop.run()` entero desde `claude_brain` — el contrato remoto tiene
  historial por usuario, imágenes y bloques JSON de aprendizaje que `run()` no maneja;
  meterlos ahí lo complicaría para el escritorio. Se comparte la vuelta, no el bucle.
- Subir el presupuesto remoto — sin botón de detener fuera del escritorio, no.
- Un techo por canal en `CHANNEL_*` de `security_manager` — la longitud de salida no es
  una decisión de seguridad; vive con el proveedor.

## Asumidos pendientes de confirmar
- Que 500 tokens es el techo correcto para voz. Si en la prueba manual las respuestas
  habladas quedan cortas, es una constante (`core/reasoning_loop.MAX_TOKENS_VOZ`).

## Prueba manual sugerida (para Johan)
1. Por Telegram: *«buscá qué es el protocolo MCP y decime la hora»* — debería resolver en
   una o dos vueltas (mirar el log: `Pensando (2)` como máximo) y responder con las dos
   cosas.
2. Por Telegram: pedir algo amarillo (*«apagá el computador»*) — debería explicar que no
   puede hacerlo desde ahí, sin el texto enlatado.
3. Por voz: preguntar algo que invite a una respuesta larga (*«explicame cómo funciona un
   motor eléctrico»*) — debería terminar en menos de un minuto de lectura.

## Verificación
- `tests/test_paridad_canales.py`: 17 passed (nuevo).
- `tests/test_claude_brain.py`, `test_reasoning_loop.py`, `test_llm_provider.py`,
  `test_gateway.py`, `test_resolution.py`: 106 passed sin cambios.
- Suite completa: ver "Log de transiciones".

## Riesgos activos
- Modelos gratuitos de OpenRouter con tool-calling parcial: con el protocolo nativo por
  Telegram ahora reciben bloques `tool_result` en vez de texto. El escritorio los usa así
  desde REQ-027 sin incidentes reportados; si alguno falla, `generate_response()` ya cae
  a la cadena de respaldo (REQ-022).

## Log de transiciones
2026-09-18 | — → NUEVO | conversación principal | REQ creado vía update-tracker.mjs
2026-09-18 | NUEVO → LISTO_PARA_COMMIT | conversación principal (sesión nocturna) | 12 criterios de SPEC-044 cumplidos. Suite completa: **2971 passed, 0 failed** (sin `test_webview_smoke.py`, 9 passed aparte). Durante la corrida apareció un `Windows fatal exception: access violation` dentro de `sentence_transformers` en `test_mejoras_escritorio.py::test_renombrar_gana_sobre_el_titulo_derivado` (dos hilos usando el tokenizer nativo a la vez); el proceso siguió y el test pasó — flake del entorno, no relacionado con este REQ, anotado para vigilar. Prueba manual pendiente de Johan (ver sección).
