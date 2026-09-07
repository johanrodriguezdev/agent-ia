# Baseline REQ-024

## Estado actual del sistema
`channels/gateway.py::GlassGateway` es el punto único de entrada compartido por los tres
canales externos (Telegram, Discord, y el `resolve()` usado también por `main.py`/
`core/orchestrator.py` — ver comentario CA-01/CA-02 en el docstring de `process()`, línea 47).
Tiene tres bloques `try/except Exception` que hoy comparten el mismo patrón de bug: ninguno
llama a `logger.error(...)`, y los tres devuelven `str(e)` (completo o truncado) empaquetado en
el texto que termina enviado tal cual al canal externo. Se leyó el archivo completo
(176 líneas) directamente, sin apoyarse en resúmenes previos del contexto/SPEC, para confirmar
número de línea exacto y contenido literal de cada punto.

El resto de `GlassGateway` (armado de sesión, preclasificación de screenshot, delegación a
`core/resolution.py::resolve()`, guardado de memoria) no se toca — el REQ es puramente sobre
manejo de excepción en los tres bloques `except` listados abajo, más `_save_semantic()` que ya
está bien (confirmado, ver criterio de no-regresión abajo).

## Los tres puntos afectados — código exacto y líneas actuales

### 1. `GlassGateway.process()` — líneas 105-109
```python
        except Exception as e:
            return GlassResponse(
                text=f"Lo siento, he encontrado un inconveniente: {str(e)[:80]}",
                speak=True
            )
```
Este `except` envuelve el `try` que arranca en la línea 66 (clasificación + `resolve()` +
guardado de memoria). `message.user_id` y `message.channel` están disponibles en este scope
(son atributos de `message`, parámetro del método) para el log que pide la SPEC.

### 2. `GlassGateway._ask_claude_for_user()` — líneas 135-138
```python
        except Exception as e:
            if session.conversation_history and session.conversation_history[-1]["role"] == "user":
                session.conversation_history.pop()
            return f"Error en inteligencia conversacional: {str(e)}"
```
Envuelve el `try` que arranca en la línea 113 (llamada a `ask_claude()`). La guarda del `if` en
la línea 136 (pop del último turno "user" del historial si la llamada falló) NO se toca — la
SPEC es explícita en que solo cambia el `return` final. `message.user_id` y `message.channel`
están disponibles (parámetro `message` del método) para el log.

Este es el peor de los tres en el estado actual: `str(e)` va **sin truncar** (a diferencia de
los otros dos que usan `[:80]` y `[:60]`).

### 3. `GlassGateway._handle_screenshot()` — líneas 163-167
```python
        except Exception as e:
            return GlassResponse(
                text=f"No pude tomar la captura{vocative()}: {str(e)[:60]}",
                speak=True
            )
```
Envuelve el `try` que arranca en la línea 142 (captura con `pyautogui`, guardado a archivo
temporal con `tempfile`). El log que pide la SPEC usa `session.user_id`/`session.channel` (el
método recibe `session`, no `message` — no tiene acceso directo a un objeto `message`, la SPEC
ya lo anticipa así en su ejemplo de log). `vocative()` se preserva en el texto de reemplazo, tal
como fija la SPEC.

## Confirmado: `_save_semantic()` no comparte el bug (no está en alcance)
Líneas 169-175. Ya usa `logger.warning(f"Error guardando memoria semántica: {e}")` en el
`except`, y ese método no tiene valor de retorno consumido por ningún canal — se llama en la
línea 101 de `process()` sin capturar el resultado. Confirmado por lectura directa: no se toca.

## Archivos que serán modificados (previsión)
- `channels/gateway.py` — los tres bloques `except Exception` descritos arriba. Único archivo
  de producción en el alcance de este REQ.
- `tests/test_gateway.py` — no existe hoy (verificado con `ls tests/`). `orion-dev`/
  `orion-tester` tendrán que crearlo desde cero para cubrir los criterios de aceptación de la
  SPEC (log con `exc_info=True`, ausencia de fragmentos de `str(e)` en la respuesta, no-regresión
  del camino feliz).

## Otros archivos que llaman a los métodos afectados — verificación de impacto

Búsqueda (`grep -rn` sobre todo el repo) de `_ask_claude_for_user`, `_handle_screenshot`,
`GlassGateway`, `.process(`:

- **`channels/discord_bot.py:73`** — `response = gateway.process(msg); return response.text`.
  Consume `GlassResponse.text` sin parsear ni depender de su contenido — solo lo retorna. No se
  ve afectado por el cambio de texto.
  - Hallazgo colateral (fuera de alcance de este REQ, documentado para referencia futura):
    `discord_bot.py::_process_message()` (líneas 56-75) tiene **su propio** `except Exception as
    e: return f"Error procesando su solicitud: {str(e)[:100]}"` (línea 74) — mismo patrón de bug
    (sin `logger.error`, fuga de `str(e)` a Discord), pero es un bloque `except` de
    `discord_bot.py`, no de `channels/gateway.py`. La SPEC-024 excluye explícitamente cualquier
    archivo fuera de `channels/gateway.py`. Se deja constancia acá para un REQ futuro; no se
    toca en este.
- **`channels/telegram_bot.py`** — múltiples puntos (líneas 739-964) importan `GlassGateway` y
  llaman `.process()`, siempre a través de `asyncio.to_thread(GlassGateway().process, msg)` o
  equivalente, consumiendo `.text` del `GlassResponse`. Ninguno parsea el contenido del mensaje
  de error — no se ve afectado.
- **`channels/telegram_confirmation_adapter.py:194`** — comentario que menciona el flujo de
  `GlassGateway().process()` en el contexto de confirmaciones pendientes; no depende del texto
  de error.
- **`core/resolution.py:664`** — comentario que referencia `_ask_claude_for_user()` como ejemplo
  de resolver con historial de sesión; no es una llamada real, es documentación en docstring.
- **`core/authorized_users.py:9`** — comentario que menciona `_handle_screenshot` en un docstring
  sobre autorización; no es una llamada ni depende del texto de error.
- **`tests/test_resolution.py:66-69`** — usa `GlassGateway` solo para verificar con `hasattr()`
  que ciertos métodos legacy (`_try_create_task`, etc., no relacionados con este REQ) fueron
  eliminados. No toca los tres métodos de este REQ.
- **`tests/test_telegram_bot.py`** (líneas 585, 609, 621, 636, 664, 684) — usa
  `monkeypatch.setattr("channels.gateway.GlassGateway.process", ...)` para **reemplazar por
  completo** `.process()` con un `fake_process`/`_explota` en cada test. Ninguno ejecuta el
  código real de `process()` ni de los otros dos métodos, así que ninguno depende del texto
  exacto de los mensajes de error actuales. Confirmado leyendo el contexto de cada monkeypatch
  (líneas 580-660): los asserts son sobre threading, reservas de confirmación pendientes
  (`has_pending`), y propagación de excepciones — nunca sobre el contenido de `response.text` en
  el camino de error.

**Conclusión de la verificación de impacto**: ningún otro módulo ni test depende del formato o
contenido literal de los tres mensajes de error que este REQ va a cambiar. El cambio queda
contenido a `channels/gateway.py` sin efectos colaterales conocidos en el resto del código.

## Fallos pre-existentes (no atribuibles a este REQ)
- **Ninguno.** `python -m py_compile channels/gateway.py` compila sin errores. La suite completa
  `pytest tests/ --tb=line -q` corrió **1779 passed, 0 failed** (102.85s), solo con warnings no
  relacionados (deprecaciones de `aifc`/`audioop` en `speech_recognition`, un
  `PytestReturnNotNoneWarning` en `test_agents.py::test_ca1_orchestrator`, y
  `InconsistentVersionWarning` de sklearn por versión de pickle del clasificador — ninguno
  vinculado a `channels/gateway.py` ni al área de este REQ).
- No existe `tests/test_gateway.py` hoy, por lo que no hay tests previos sobre
  `GlassGateway.process()`/`_ask_claude_for_user()`/`_handle_screenshot()` en sí mismos (los
  tests existentes en `test_telegram_bot.py` mockean `.process()` completo, no ejercitan su
  cuerpo real) — cualquier fallo que aparezca en esos tres métodos durante `orion-tester` será
  atribuible al cambio de este REQ, no preexistente.

## Nota para orion-architect
Los tres puntos son mecánicamente equivalentes: agregar `logger.error(...)` con
`exc_info=True` justo antes de construir la respuesta, y reemplazar el texto que hoy incluye
`str(e)` por el texto genérico fijado en la SPEC. La única variación entre los tres es de dónde
sale `user_id`/`channel` para el log (`message.*` en los dos primeros, `session.*` en el
tercero) y el tipo de retorno (`GlassResponse` en `process()`/`_handle_screenshot()`, `str` en
`_ask_claude_for_user()`). No se identificó ninguna dependencia oculta ni necesidad de tocar
otro archivo de producción.
