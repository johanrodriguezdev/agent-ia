# SPEC-025 — Logging y saneamiento del error filtrado a Discord en `_process_message()`

**Estado:** ✅ COMPLETADO (aprobado bajo autorización nocturna en bloque del 2026-09-06)
**Categoría:** SEGURIDAD
**Tipo:** BUG_FIX
**Fecha:** 2026-09-07

## Objetivo
`channels/discord_bot.py::_process_message()` tiene un `except Exception as e:` que retorna
`f"Error procesando su solicitud: {str(e)[:100]}"` directamente como mensaje visible en el canal
de Discord, sin ningún `logger.error()` previo. Es el mismo patrón de bug que REQ-024 corrigió en
`channels/gateway.py` (tres puntos): pérdida del traceback real (nadie lo registra) y fuga de
detalle interno de la excepción (rutas de archivo, nombres de módulo, mensajes de librerías) hacia
un canal externo. El objetivo es registrar el error completo internamente antes de responder, y
reemplazar lo que se envía a Discord por un texto genérico fijo, sin perder el tono ni la brevedad
del archivo.

## Alcance

### Incluye
- `channels/discord_bot.py::_process_message()` (líneas 56-76 al abrir el REQ) — único bloque
  `except Exception` corregido en este REQ.

### No incluye
- Ningún otro `except Exception` de `discord_bot.py` (líneas 52, 95-96, 135-136, 163-164,
  195-198, 239-242) — descartados explícitamente por el humano en la descripción del REQ.
  Verificados durante la lectura del archivo en este paso:
  - Línea 52 (`_get_agent_name()`): no filtra `str(e)` a ningún canal — retorna un valor de
    configuración por defecto (`"NODDOO"`), no interactúa con Discord.
  - Líneas 95-96 y 135-136 (`_slash_autorizado`, `on_message` avisando a no autorizado): ya
    loguean con `logger.error(...)`; el `except` envuelve el propio `await ... send_message`, no
    filtran la excepción original al usuario.
  - Líneas 163-164 (borrado de temporal de imagen): ya usa `logger.debug(...)`, comportamiento
    intencional documentado en el propio comentario del código, no responde nada al canal.
  - Líneas 195-198 (`slash_limpiar`): ya loguea con `logger.warning(...)`; el mensaje que ve el
    usuario es un texto fijo ("Historial reiniciado...") no derivado de `str(e)`.
  - Líneas 239-242 (dentro de `slash_ayuda` u otro comando slash de solo lectura): sin contacto
    con `_process_message()`, fuera del patrón descrito en el REQ.
  Ninguno de estos comparte el patrón exacto (falta de log + `str(e)` crudo devuelto como
  respuesta al canal), así que no se reabre el alcance — a diferencia de lo que ocurrió en
  REQ-024, aquí la lectura del archivo confirma que el REQ humano ya delimitó el alcance
  correctamente.
- Rediseñar `_process_message()` o el flujo de `GlassGateway` (fuera de alcance, y ya cubierto
  por REQ-024 del lado de `gateway.py`).

## Módulos afectados
- `channels/discord_bot.py` — el bloque `except Exception as e:` de `_process_message()`
  (líneas 75-76 al abrir el REQ).
- `tests/test_discord_bot.py` — nuevo si no existe hoy (a confirmar por `orion-baseline`); si ya
  existe, se le agregan casos para este bloque.

## Comportamiento actual vs deseado

| Punto | Actual | Deseado |
|-------|--------|---------|
| `_process_message()` | Sin log; retorna `f"Error procesando su solicitud: {str(e)[:100]}"` — ese string se usa tal cual como `result` y termina en el `embed.description` que ve el usuario en Discord | `logger.error(..., exc_info=True)` con el error completo y contexto de usuario; retorna `"Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."` |

### Formato del log
Consistente con el formato ya aprobado en `gateway.py` (REQ-024), usando los parámetros que
`_process_message()` ya recibe (`user_id`, `user_name`) en vez de `message.user_id`/`message.channel`
(el canal aquí es siempre `"discord"`, fijo, no aporta como dato variable pero se incluye igual
para mantener el mismo formato de log entre archivos):

```python
except Exception as e:
    logger.error(
        f"Error en discord_bot._process_message() | usuario={user_id} ({user_name}) | "
        f"canal=discord: {e}",
        exc_info=True
    )
    return "Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."
```

El log es interno (vía `logging`, no sale del proceso), así que incluir `user_id`/`user_name` no
reintroduce el riesgo que este REQ corrige.

### Texto genérico exacto
Se fija, por pedido explícito del humano, el mismo texto ya aprobado en `gateway.py::process()`
tras REQ-024 — es el punto de `gateway.py` más análogo a `_process_message()` (entrada general de
procesamiento de un mensaje, no un sub-flujo específico como `_ask_claude_for_user()` o
`_handle_screenshot()`):

> `"Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."`

`orion-architect`/`orion-dev` pueden ajustar redacción menor solo por motivos de longitud/estilo,
siempre que cumpla el criterio duro: ningún fragmento de `str(e)` en el texto devuelto.

## Criterios de aceptación
- [ ] Dado un error interno arbitrario dentro del bloque `try` de `_process_message()`, el log
      contiene el traceback completo (`exc_info=True`) y el mensaje original de la excepción.
- [ ] El log de ese error incluye `user_id` y `user_name` (contexto suficiente para depurar a qué
      usuario/mensaje correspondió el fallo).
- [ ] Dado ese mismo error, el string retornado por `_process_message()` NO contiene ningún
      fragmento de `str(e)` original — solo el texto genérico fijo.
- [ ] El texto genérico devuelto es exactamente
      `"Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."`
      (o un ajuste menor de redacción documentado por `orion-dev`, sin fragmentos de `str(e)`).
- [ ] Ningún otro bloque `except Exception` de `discord_bot.py` (líneas 52, 95-96, 135-136,
      163-164, 195-198, 239-242) queda modificado — criterio de no-regresión / no-alcance.
- [ ] El comportamiento del camino feliz (sin excepción) de `_process_message()` no cambia.
- [ ] `python -m py_compile channels/discord_bot.py` sin errores.
- [ ] Suite `pytest tests/` completa sin nuevos fallos respecto al baseline que documente
      `orion-baseline`.

## Casos borde
- Excepción cuyo `str(e)` esté vacío (p. ej. algunas excepciones de librerías C) — el log debe
  igual mostrar el tipo de excepción vía `exc_info=True`; la respuesta al canal sigue siendo el
  texto genérico, sin depender de que `str(e)` tenga contenido.
- `user_id` o `user_name` con caracteres especiales (p. ej. emojis en el `display_name` de
  Discord) — no requiere manejo adicional, el log usa un f-string estándar que ya tolera Unicode.
- El bloque `try` de `_process_message()` puede fallar antes o después de instanciar `GlassMessage`
  / `GlassGateway` — en ambos casos el `except` ya envuelve todo el cuerpo de la función, así que
  `user_id`/`user_name` (parámetros de la función, no derivados del intento fallido) siguen
  disponibles para el log sin cambios adicionales.

## Asumidos
- Ninguno pendiente — la redacción exacta del texto genérico y el formato del log quedan resueltos
  arriba, tomando como referencia directa `gateway.py::process()` (REQ-024), tal como pidió el
  humano.

## Autoaprobación bajo autorización nocturna
Esta SPEC queda **aprobada bajo autorización nocturna en bloque del 2026-09-06**, sin revisión
interactiva del humano en este paso puntual. Motivo (según autorización vigente y confirmado en
`REQ-025-context.md`): corrección quirúrgica de un bug de seguridad ya existente (reduce una fuga
de información interna ya presente en el sistema), no abre ninguna superficie nueva de ataque, y
replica un patrón de fix ya revisado y aprobado por el humano en REQ-024. No es una revisión
personal de Johan — queda documentado explícitamente como tal.
