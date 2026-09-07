# Auditoría QA REQ-024 — Logging y saneamiento de errores filtrados al canal externo en `channels/gateway.py`

**Agente:** orion-qa
**Fecha:** 2026-09-07

## Metodología
No se confió en los reportes de `orion-dev`/`orion-tester` como fuente única. Se leyeron
completos: `REQ-024-context.md`, `SPEC-024.md`, `arquitectura-024.md`, `desarrollo-log-024.md`,
`test-results-024.md`, y luego se releyó directamente el código real:
`channels/gateway.py` (192 líneas) y `tests/test_gateway.py` (125 líneas). Se re-ejecutaron de
forma independiente:
- `python -m py_compile channels/gateway.py tests/test_gateway.py` → sin errores.
- `python -m pytest tests/test_gateway.py --tb=short -q` → **9 passed**.
- `python -m pytest tests/ --tb=short -q` (suite completa) → **1788 passed, 0 failed**, 11
  warnings (los mismos `InconsistentVersionWarning` de sklearn ya documentados por
  `orion-baseline`/`orion-tester`, no relacionados con este REQ).
- `grep` de `except\s*:` / `except\s+Exception\s*:` (sin capturar la excepción) sobre
  `channels/gateway.py` → sin coincidencias, ningún `except` silencioso.
- `grep` de todas las apariciones de `{e}` y `except Exception as e` en el archivo → las 4
  ocurrencias de `{e}` (líneas 108, 144, 177, 191) están **exclusivamente** dentro de llamadas a
  `logger.error(...)`/`logger.warning(...)`, nunca en un valor de retorno (`GlassResponse.text`
  ni el `str` que retorna `_ask_claude_for_user()`).

## Seguridad

**Fuga de `str(e)` al canal externo — verificada punto por punto:**

| Punto | Antes | Ahora (verificado en código real) |
|---|---|---|
| `process()` (líneas 105-115) | `f"...: {str(e)[:80]}"` en `GlassResponse.text` | `logger.error(..., exc_info=True)` primero; `GlassResponse.text` es el literal fijo "Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento." — sin `e` interpolada |
| `_ask_claude_for_user()` (líneas 141-149) | `f"Error en inteligencia conversacional: {str(e)}"` retornado sin truncar | `logger.error(..., exc_info=True)` primero, guarda del `pop()` preservada sin cambios, retorno literal fijo "Lo siento, no pude procesar esa solicitud en este momento. Intente de nuevo." |
| `_handle_screenshot()` (líneas 174-183) | `f"...: {str(e)[:60]}"` en `GlassResponse.text` | `logger.error(..., exc_info=True)` primero; `GlassResponse.text` es `f"No pude tomar la captura{vocative()}. Intente de nuevo en un momento."` — conserva `vocative()`, sin `str(e)` |

Ningún fragmento de `str(e)` llega a un valor consumido por un canal externo en ninguno de los
tres puntos. Los 9 tests de `tests/test_gateway.py` inyectan marcadores distintivos
(`"fuga-interna-marca-XYZ"`, `"/ruta/absoluta/secreta/del/disco"`, `"marca-ABC"`,
`"dato-interno-123"`, `"marca-DEF"`, `"/tmp/ruta-secreta"`) y assertan explícitamente su ausencia
en la respuesta — no son asserts débiles (`is not None`), comparan contra el texto literal exacto
esperado.

**Logs internos (usuario/canal) — no reintroducen el riesgo:** los `logger.error(...)` incluyen
`usuario={message.user_id}`/`canal={message.channel}` (o `session.user_id`/`session.channel` en
`_handle_screenshot()`). Este contenido va exclusivamente al logger del proceso (nunca a
`GlassResponse`, nunca al `return` de `_ask_claude_for_user()`, nunca a ningún canal). Consistente
con el criterio ya fijado en `SPEC-024.md` y confirmado por `grep`: cero apariciones de estas
variables fuera de las llamadas a `logger.*`.

**Secretos:** sin API keys, tokens ni credenciales en texto plano en el diff de este REQ (los
tres bloques `except` no tocan configuración ni credenciales).

**Acciones destructivas:** este REQ no introduce ni modifica ninguna acción destructiva
(borrado, apagado, envío externo autónomo). No aplica confirmación amarilla/roja nueva.

**`except` silenciosos:** ninguno. Los cuatro `except Exception as e` de `channels/gateway.py`
(los tres del alcance de este REQ + `_save_semantic()` sin tocar) todos registran con `logger`
antes de retornar/continuar.

## Niveles de riesgo (`.claude/rules/security-levels.md`)
- **Verde (puede actuar):** no aplica — este REQ no agrega ni modifica acciones de este nivel.
- **Amarillo (debe confirmar):** no aplica — no hay acciones destructivas nuevas ni tocadas.
- **Rojo (no ejecuta):** no aplica — confirmado que el REQ **reduce** superficie de fuga de
  información existente (dato interno → canal externo), no abre ninguna acción de nivel rojo.
- **Se implementaron confirmaciones:** no aplica a este REQ (no hay acción amarilla/roja
  involucrada) — es exclusivamente saneamiento de mensajes de error y logging.

## Logging
- Los tres puntos nuevos usan `logger.error(..., exc_info=True)` — traceback completo preservado,
  verificado tanto por lectura del código como por los 6 tests de `caplog` que assertan
  `r.exc_info` truthy.
- `_save_semantic()` (fuera de alcance, no tocado) sigue usando `logger.warning(f"...: {e}")` —
  correcto: ese log nunca sale del proceso, no comparte el bug de este REQ.
- Sin `except: pass` ni `except Exception: pass` en ningún punto del archivo.

## Consistencia de código
- Los tres bloques `except` modificados siguen la convención de line-length (`.claude/rules/python-style.md`,
  máx. 100 caracteres) — se verificó por lectura, ninguna línea nueva excede el límite.
- Naming, estructura de archivo (una clase principal, `GlassGateway`) y uso de `logging` en vez
  de `print()` se respetan — sin `print()` de debug introducido.
- Cambio estrictamente mecánico y acotado: no se modificó ninguna firma de método, import, ni
  línea fuera de los tres bloques `except` señalados — confirmado por diff visual contra lo
  documentado en `arquitectura-024.md`/`baseline-024.md` (líneas 66-104, 119-139, 153-173 de los
  `try` idénticas a lo preexistente).
- Los 9 tests nuevos (`tests/test_gateway.py`) ejercitan el código de producto real dentro de los
  bloques `try` bajo prueba (mocks en `core.resolution.resolve`, `ai.claude_brain.ask_claude`,
  `pyautogui.screenshot`, `ai.memory_manager.memory.store`) — no son mocks vacíos ni interceptan
  fuera del `except` que dicen cubrir. Cumple `.claude/rules/testing.md` (sin red, sin
  micrófono/altavoz, sin tocar disco real).

## Veredicto: ✅ APROBADO

Los tres puntos de fuga descritos en el REQ están corregidos y verificados de forma independiente
(no solo por lectura de reportes de agentes previos, sino releyendo el código real y
re-ejecutando compilación + suite completa). Sin secretos expuestos, sin `except` silenciosos,
sin acciones destructivas nuevas, logging interno completo y correctamente acotado al proceso.
Compilación limpia, 1788/1788 tests pasando sin regresiones.

**Este veredicto es juicio técnico propio de `orion-qa` — no una autoaprobación en nombre del
usuario.** La autorización nocturna en bloque del 2026-09-06 cubre a `orion-spec`/`orion-architect`,
no a QA. La prueba manual final del humano sigue siendo obligatoria antes de considerar el REQ
`LISTO_PARA_COMMIT` real, conforme a `.claude/rules/git.md`.
