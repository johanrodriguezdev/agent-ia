# SPEC-044 — Paridad de canales: Telegram/Discord al bucle nativo, y techo de salida en voz

**Categoría:** CORE · **Tipo:** MEJORA + DEUDA TÉCNICA · **Fecha:** 2026-09-18
**Origen:** deudas P-3 y P-4 reconocidas al cerrar REQ-027 (2026-09-08). Recomendación
aprobada en bloque por Johan la noche del 2026-09-18 ("paridad de canales va segundo
porque es deuda de diseño, no feature").

## Problema

Desde REQ-027 el escritorio razona con el protocolo nativo de herramientas: los
`tool_use`/`tool_result` viajan estructurados (`core/tool_history.py`), el modelo puede
pedir varias herramientas en una vuelta y se ejecutan todas, y al agotar el presupuesto o
ante una denegación hay una llamada de cierre sin herramientas que redacta con lo reunido.

Telegram y Discord llegan por otro camino: `channels/gateway.py` →
`core/resolution.resolve(claude_fn=…)` → `ai/claude_brain.ask_claude()` →
`_resolver_con_tools()`, que quedó en la versión de REQ-007:

- el resultado de cada herramienta se re-serializa como **texto** en un mensaje `user`
  («[Resultado de X] … Responde al usuario con esta informacion»): los modelos con
  tool-calling nativo razonan peor sobre eso que sobre bloques `tool_result`;
- se ejecuta **solo `tool_calls[0]`** y se descarta el resto: si el modelo pide dos
  lecturas juntas, gasta otra vuelta entera del presupuesto por la segunda;
- una denegación corta con un texto enlatado, sin cierre que aproveche lo averiguado;
- el presupuesto es una constante propia (`MAX_TOOL_ROUNDS = 5`) separada de la del
  escritorio (`TECHO_CANAL_NO_ESCRITORIO = 5`): hoy coinciden por casualidad.

Y en voz (P-4): la respuesta sale por TTS sin ningún techo de longitud. Una respuesta de
4.000 tokens leída en voz alta son minutos que no se pueden cortar.

## Lo que el usuario va a notar

- Por Telegram/Discord, el agente resuelve en menos vueltas lo que necesita varias
  herramientas («buscá X y leé la primera página») y contesta con lo que averiguó aunque
  una acción se le deniegue o se le acabe el presupuesto.
- Por voz, las respuestas son cortas por construcción, no solo por pedido del prompt.

## Criterios de aceptación

### A. Bucle nativo en `ai/claude_brain.py`

| # | Criterio |
|---|---|
| CA-01 | `_resolver_con_tools()` conserva su firma (`history, system_prompt, image_path, channel, user_id`) y su contrato: devuelve el texto final; `ask_claude()` no cambia. |
| CA-02 | Los resultados de herramientas viajan al modelo como historial **neutral** de `core/tool_history.py` (`mensaje_de_llamadas` + `mensaje_de_resultados`), nunca como texto «[Resultado de …]». Verificable: el segundo `generate_response` recibe mensajes con `tool_history.es_estructurado()` verdadero. |
| CA-03 | Se ejecutan **todas** las tool calls de la vuelta, en secuencia, cada una por `execute_tool()` con el canal y el usuario del caller (reusa `core/reasoning_loop.ejecutar_vuelta()`); una denegación corta la secuencia y las no ejecutadas llevan resultado sintético (D-6 de REQ-027). |
| CA-04 | El presupuesto es `core/reasoning_loop.TECHO_CANAL_NO_ESCRITORIO` (una sola constante para todo lo que no es escritorio); `MAX_TOOL_ROUNDS` desaparece. Cuenta llamadas al modelo **con** herramientas. |
| CA-05 | Al agotar el presupuesto o ante una denegación hay **una** llamada de cierre con `tools=None`, con la misma instrucción que el escritorio (`_INSTRUCCION_CIERRE_PRESUPUESTO` / `_INSTRUCCION_CIERRE_DENEGACION`), fuera del presupuesto. Si el cierre no sirve, se usa el texto enlatado de siempre. |
| CA-06 | El camino remoto **no** consulta el botón de detener del escritorio (`abortar_si_cancelado`): `ejecutar_vuelta(..., cancelable=False)`. Un turno de escritorio cancelado no puede abortar un mensaje de Telegram en otro hilo. |
| CA-07 | El historial por usuario (`_conversation_histories`) sigue guardando solo texto (`user`/`assistant`): los bloques de herramientas son del turno y no persisten. |
| CA-08 | Se conserva: `streaming.permitido()` alrededor de la llamada al modelo, `catalogo_para_modelo(canal)`, el aviso de cambio de proveedor (`con_aviso_de_cambio`), el soporte de imagen, y la degradación a texto plano con proveedores sin tool-calling. |

### B. Techo de salida en voz

| # | Criterio |
|---|---|
| CA-09 | `ai/llm_provider.py` expone `tope_de_salida(n)` (context manager, thread-local) y los cinco adaptadores usan `_max_tokens_salida()` en vez de la constante directa. Fuera del bloque, `MAX_TOKENS_SALIDA` (4096) como hoy. |
| CA-10 | `core/reasoning_loop.run()` aplica `tope_de_salida(MAX_TOKENS_VOZ)` (500) a las llamadas que producen la respuesta al usuario cuando el canal es `VOICE` — la del bucle y la de cierre —, no a las herramientas que consulten al modelo por su cuenta. |
| CA-11 | En cualquier otro canal el tope no se toca (verificable: el adaptador ve 4096). |

### C. Regresión

| # | Criterio |
|---|---|
| CA-12 | Suite completa sin fallos nuevos; `tests/test_claude_brain.py` (CA-15 de REQ-022) sigue pasando sin cambios. |

## Fuera de alcance

- Subir el techo de 5 para canales remotos: SPEC-027 lo fijó en 5 porque no hay botón de
  detener fuera del escritorio; nada cambió.
- Modos del composer en Telegram/Discord.
- Streaming de respuesta hacia Telegram (el bot manda el mensaje entero).
