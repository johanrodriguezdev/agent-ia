# SPEC-024 — Logging y saneamiento de errores filtrados al canal externo en `channels/gateway.py`

**Estado:** ✅ COMPLETADO (aprobado bajo autorización nocturna en bloque del 2026-09-06)
**Categoría:** SEGURIDAD
**Tipo:** BUG_FIX
**Fecha:** 2026-09-07

## Objetivo
`GlassGateway` tiene tres puntos de manejo de excepción que (a) no registran el error con
`logger.error` — el traceback se pierde para siempre — y (b) devuelven el mensaje crudo de la
excepción (`str(e)`, completo o truncado) directo al canal externo (Telegram/Discord/cualquiera
que use `process()`), pudiendo filtrar rutas absolutas del disco u otros detalles internos del
usuario. El objetivo es registrar el error completo antes de responder, y reemplazar lo que se
envía al canal por un texto genérico y seguro, sin perder el tono conversacional ni la brevedad
actuales.

## Alcance

### Incluye
- `GlassGateway.process()` (líneas ~105-109 al abrir el REQ) — punto original reportado.
- `GlassGateway._ask_claude_for_user()` (líneas ~135-138) — **ampliación de alcance**, ver
  "Hallazgos durante la redacción de la SPEC" abajo.
- `GlassGateway._handle_screenshot()` (líneas ~163-167) — **ampliación de alcance**, ver
  mismo apartado.

### No incluye
- Rediseñar `GlassGateway` a un gateway persistente (roadmap Fase 1, iniciativa más grande e
  independiente de este bug fix).
- `GlassGateway._save_semantic()` (líneas ~169-175) — ya usa `logger.warning(...)` con el
  mensaje de la excepción, y ese log nunca sale del proceso ni llega a un canal externo (el
  método no tiene valor de retorno consumido por el canal). No comparte el bug.
- Cualquier otro archivo fuera de `channels/gateway.py` (p. ej. `ai/user_manager.py`, que tiene
  su propio `print()` de debug en un método no relacionado — no forma parte de esta corrección
  porque no es una fuga hacia un canal externo ni el bug descrito en el REQ).

## Hallazgos durante la redacción de la SPEC (ampliación de alcance justificada)

El REQ-024 original (`origen/descripcion-original.md`) dejaba condicionado el alcance de
`_ask_claude_for_user()` a que, al leer el código, se confirmara que comparte el mismo bug
exacto. Se leyó el código completo de `channels/gateway.py` y se confirma:

1. **`_ask_claude_for_user()` (líneas 135-138) comparte el bug exacto — confirmado.**
   ```python
   except Exception as e:
       if session.conversation_history and session.conversation_history[-1]["role"] == "user":
           session.conversation_history.pop()
       return f"Error en inteligencia conversacional: {str(e)}"
   ```
   No hay `logger.error`, y el `str(e)` **completo** (sin truncar, peor que el caso original de
   80 caracteres) se devuelve como si fuera una respuesta normal. Ese valor de retorno se usa
   como `result` en `process()` (línea 78, camino de `MessageType.IMAGE`, y también alcanzable
   vía el `claude_fn` que `resolve()` puede invocar en la línea 95) y termina enviado tal cual
   al canal externo mediante `GlassResponse(text=result, speak=True)` en la línea 103. Es la
   misma fuga que motivó el REQ, solo que el error se traga internamente en vez de propagarse al
   `except` de `process()`.

2. **`_handle_screenshot()` (líneas 163-167) — hallazgo nuevo, no anticipado por el REQ
   original.** Durante la lectura completa del archivo (regla: solo se reabre el alcance ante un
   hallazgo real al leer el código) se encontró el mismo patrón:
   ```python
   except Exception as e:
       return GlassResponse(
           text=f"No pude tomar la captura{vocative()}: {str(e)[:60]}",
           speak=True
       )
   ```
   Sin `logger.error`, y `str(e)[:60]` crudo directo al canal externo (misma clase de riesgo:
   `pyautogui`/`tempfile` pueden filtrar rutas absolutas del disco en el mensaje de excepción).

**Decisión:** se incluyen ambos en el alcance de este mismo REQ, en vez de abrir REQs
independientes. Motivo: es el mismo archivo, el mismo patrón de una línea (falta de
`logger.error` + fuga de `str(e)` al canal externo), y la misma solución mecánica en los tres
puntos. Corregir solo `process()` y dejar los otros dos intactos habría dejado el objetivo de
seguridad del REQ incompleto — un usuario que dispare un error en el camino de imagen o de
captura de pantalla seguiría recibiendo detalles internos crudos por Telegram/Discord. Encaja en
el criterio de "autoaprobable" de la autorización nocturna: reduce superficie de fuga existente,
no abre superficie nueva, y no es un rediseño.

## Módulos afectados
- `channels/gateway.py` — los tres bloques `except Exception` descritos arriba.
- `tests/test_gateway.py` — nuevo (no existe test de gateway hoy).

## Comportamiento actual vs deseado

| Punto | Actual | Deseado |
|-------|--------|---------|
| `process()` | Sin log; responde `f"Lo siento, he encontrado un inconveniente: {str(e)[:80]}"` | `logger.error(..., exc_info=True)` con el error completo; responde `"Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."` |
| `_ask_claude_for_user()` | Sin log; retorna `f"Error en inteligencia conversacional: {str(e)}"` (texto que luego se envía al canal como respuesta normal) | `logger.error(..., exc_info=True)` con el error completo; retorna `"Lo siento, no pude procesar esa solicitud en este momento. Intente de nuevo."` |
| `_handle_screenshot()` | Sin log; responde `f"No pude tomar la captura{vocative()}: {str(e)[:60]}"` | `logger.error(..., exc_info=True)` con el error completo; responde `f"No pude tomar la captura{vocative()}. Intente de nuevo en un momento."` (conserva `vocative()`) |

### Formato del log (resuelve el "asumido pendiente" del contexto del REQ)
Se decide incluir usuario y canal en cada log, para que sea accionable en debugging:
```python
logger.error(f"Error en GlassGateway.process() | usuario={message.user_id} | canal={message.channel}: {e}", exc_info=True)
logger.error(f"Error en GlassGateway._ask_claude_for_user() | usuario={message.user_id} | canal={message.channel}: {e}", exc_info=True)
logger.error(f"Error en GlassGateway._handle_screenshot() | usuario={session.user_id} | canal={session.channel}: {e}", exc_info=True)
```
El log es interno (no sale del proceso), así que incluir `user_id`/`channel` no reintroduce el
riesgo que este REQ corrige.

### Textos genéricos exactos (resuelve el otro "asumido pendiente")
Se fijan como texto exacto a implementar, en el mismo tono de "usted" ya usado en el archivo:
- `process()`: `"Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."`
- `_ask_claude_for_user()`: `"Lo siento, no pude procesar esa solicitud en este momento. Intente de nuevo."`
- `_handle_screenshot()`: `f"No pude tomar la captura{vocative()}. Intente de nuevo en un momento."`

`orion-architect`/`orion-dev` pueden ajustar redacción menor si hace falta por longibilidad, pero
el criterio de aceptación duro es: **ningún fragmento de `str(e)` en el texto enviado al canal**,
tono conversacional y brevedad preservados.

## Criterios de aceptación
- [ ] Dado un error interno arbitrario dentro del bloque `try` de `process()`, el log contiene el
      traceback completo (`exc_info=True`) y el mensaje original de la excepción.
- [ ] Dado ese mismo error, el `GlassResponse.text` devuelto por `process()` NO contiene ningún
      fragmento de `str(e)` original — solo el texto genérico aprobado.
- [ ] Dado un error interno arbitrario dentro de `_ask_claude_for_user()`, el log contiene el
      traceback completo (`exc_info=True`) y el mensaje original de la excepción.
- [ ] Dado ese mismo error, el string retornado por `_ask_claude_for_user()` NO contiene ningún
      fragmento de `str(e)` original.
- [ ] Dado un error interno arbitrario dentro de `_handle_screenshot()`, el log contiene el
      traceback completo (`exc_info=True`) y el mensaje original de la excepción.
- [ ] Dado ese mismo error, el `GlassResponse.text` devuelto por `_handle_screenshot()` NO
      contiene ningún fragmento de `str(e)` original, y sí conserva `vocative()`.
- [ ] `_save_semantic()` queda intacto (sigue usando `logger.warning`, sin cambios de
      comportamiento) — criterio de no-regresión.
- [ ] El comportamiento del camino feliz (sin excepción) de `process()`, `_ask_claude_for_user()`
      y `_handle_screenshot()` no cambia.
- [ ] `python -m py_compile channels/gateway.py` sin errores.
- [ ] Suite `pytest tests/` completa sin nuevos fallos respecto al baseline que documente
      `orion-baseline`.

## Casos borde
- Excepción cuyo `str(e)` esté vacío (p. ej. algunas excepciones de librerías C) — el log debe
  igual mostrar el tipo de excepción vía `exc_info=True`; la respuesta al canal sigue siendo el
  texto genérico, sin depender de que `str(e)` tenga contenido.
- Excepción durante `session.conversation_history.pop()` dentro de `_ask_claude_for_user()` (lista
  vacía o clave inexistente) — ya está protegido por el `if` existente en la línea 136, no se
  modifica esa guarda, solo el `except` que la envuelve.
- Mensaje sin `message.user_id` o `message.channel` poblados (no debería ocurrir dado que
  `GlassMessage` los declara obligatorios sin default) — no se agrega manejo adicional, se asume
  que el dataclass ya garantiza su presencia.

## Asumidos
- Ninguno pendiente — los dos "asumidos" que dejó `orion-coordinador` en el contexto (formato del
  log y si incluir usuario/canal) quedan resueltos explícitamente arriba.
- ASUMIDO: la redacción exacta de los tres textos genéricos es la propuesta en esta SPEC;
  `orion-dev` puede ajustarla por motivos de longitud/estilo siempre que cumpla el criterio duro
  (sin fragmentos de `str(e)`, tono conversacional, brevedad) — no requiere volver a pasar por
  aprobación humana en vivo dado el alcance acotado de este REQ.
