# Contexto REQ-024 — Bug: GlassGateway.process() no loguea excepciones y filtra str(e) crudo al canal externo

## Resumen ejecutivo
En `channels/gateway.py::GlassGateway.process()`, el `except Exception` general no registra el
error con `logger.error` (se pierde el traceback) y envía los primeros 80 caracteres del mensaje
crudo de la excepción (`str(e)[:80]`) directamente al canal externo (Telegram/Discord), pudiendo
filtrar rutas absolutas u otros detalles internos del disco del usuario. Objetivo: loguear
completo antes de responder, y responder con un mensaje genérico y seguro sin perder tono ni
brevedad.

## Estado actual
- **Estado tracker:** EN_PRUEBAS
- **Último agente:** orion-dev
- **Fecha última actualización:** 2026-09-07
- **Rama git:** —
- **Categoría:** SEGURIDAD
- **Tipo de cambio:** BUG_FIX

## Decisiones tomadas
2026-09-07 | orion-coordinador | REQ creado — categoría=SEGURIDAD | El bug tiene dos facetas: (1)
ausencia de `logger.error` en manejo de excepción (regla transversal de `.claude/rules/python-style.md`,
aplicable a cualquier categoría), y (2) fuga de contenido interno crudo (`str(e)[:80]`, potenciales
rutas absolutas del disco del usuario) hacia un canal EXTERNO (Telegram/Discord). El punto (2) es
el que define la categoría: `.claude/rules/security-levels.md` regula explícitamente qué puede
salir de canal a canal y exige logging obligatorio para acciones sensibles; este es un caso de
fuga de información interna a un canal externo, que es exactamente el tipo de riesgo que ese
documento cubre. Se descarta CORE porque el bug no es de enrutamiento/lógica de negocio del
gateway — `resolve()` y el flujo de comandos siguen funcionando igual; es puramente manejo de
errores con implicación de seguridad/privacidad.

2026-09-07 | orion-coordinador | Verificación directa del código | Se releyó
`channels/gateway.py` líneas 80-119 y se confirmó que el bug descrito por el humano sigue
presente en las líneas 105-109 tal cual se reportó, sin desviación respecto a la descripción de
origen.

2026-09-07 | orion-coordinador | REQ NO amerita excepción a la autorización nocturna en bloque
del 2026-09-06 | Es una corrección acotada de manejo de errores que **reduce** superficie de
fuga de información (no abre superficie nueva, a diferencia de REQ-023 que abrió un listener de
red). Encaja en el criterio de "autoaprobable" descrito en esa autorización: orion-spec y
orion-architect pueden autoaprobarse en nombre del usuario durante esta ventana, documentando
cada aprobación como "aprobado bajo autorización nocturna en bloque del 2026-09-06" — nunca como
revisión real del usuario. Los límites duros (sin git commit/push/merge/rebase, sin acciones
🔴 Rojo) siguen aplicando sin excepción.

2026-09-07 | orion-spec | SPEC redactada y aprobada | aprobado bajo autorización nocturna en
bloque del 2026-09-06 — no es revisión en vivo del usuario. SPEC completa en
`spec/SPEC-024.md`.

2026-09-07 | orion-spec | Tipo de cambio: BUG_FIX | Confirmado sin cambios respecto a lo
identificado por orion-coordinador al redactar la SPEC.

2026-09-07 | orion-spec | Ampliación de alcance justificada — `_ask_claude_for_user()` confirmado
con el mismo bug | Al leer `channels/gateway.py` completo se confirmó que el `except` de
`_ask_claude_for_user()` (líneas ~135-138) comparte exactamente el mismo bug: sin `logger.error`
y con `str(e)` completo (sin truncar) filtrado al canal externo vía el valor de retorno que
`process()` reenvía como `GlassResponse.text`. Se decide incluirlo en el mismo REQ en vez de abrir
uno aparte — mismo archivo, mismo patrón de una línea, misma solución. Detalle completo en
SPEC-024.md, sección "Hallazgos durante la redacción de la SPEC".

2026-09-07 | orion-spec | Hallazgo nuevo no anticipado — `_handle_screenshot()` tiene el mismo bug
| Durante la lectura completa del archivo (no parte del alcance original ni de la condición sobre
`_ask_claude_for_user()`) se encontró que `_handle_screenshot()` (líneas ~163-167) también carece
de `logger.error` y filtra `str(e)[:60]` crudo al canal externo. Se incluye en el mismo REQ por la
misma razón que el punto anterior. Detalle completo en SPEC-024.md.

2026-09-07 | orion-spec | Asumidos pendientes del contexto resueltos | (1) Formato del log: se fija
incluir `usuario` y `canal` en cada `logger.error(..., exc_info=True)` — es información interna,
nunca sale del proceso, no reintroduce el riesgo del REQ. (2) Los tres textos genéricos de
reemplazo quedan fijados textualmente en SPEC-024.md, conservando tono de "usted" y brevedad ya
presentes en el archivo.

2026-09-07 | orion-baseline | Baseline documentado — sin fallos preexistentes | Se leyó
`channels/gateway.py` completo (176 líneas) directamente y se confirmó el código exacto de los
tres puntos (líneas 105-109, 135-138, 163-167 — sin desviación respecto a lo reportado por
orion-coordinador/orion-spec). `python -m py_compile channels/gateway.py` compila sin errores.
`pytest tests/` completo: **1779 passed, 0 failed** — ningún fallo preexistente en el área. No
existe `tests/test_gateway.py` hoy (lo crea el flujo posterior). Verificación de impacto con
`grep` sobre todo el repo: `discord_bot.py`, `telegram_bot.py` y los tests que mockean
`GlassGateway.process()` consumen `.text`/`response` sin depender del contenido literal de los
mensajes de error — ningún archivo fuera de `channels/gateway.py` necesita cambios. Hallazgo
colateral fuera de alcance: `discord_bot.py::_process_message()` (línea 74) tiene el mismo patrón
de bug en su propio `except`, pero es un archivo distinto y la SPEC-024 lo excluye
explícitamente — queda documentado en `baseline-024.md` para un REQ futuro. Detalle completo en
`origen/baseline-024.md`.

2026-09-07 | orion-architect | Código de `channels/gateway.py` releído completo antes de
diseñar | Se confirmó línea por línea que el contenido de los tres bloques `except` coincide
exactamente con lo documentado por orion-baseline (líneas 105-109, 135-138, 163-167), sin
desviación. `logger`/`logging` ya están importados e instanciados (líneas 6 y 13) y en uso por
`_save_semantic()` — los tres puntos nuevos reutilizan el mismo logger, sin import nuevo.

2026-09-07 | orion-architect | Propuesta técnica redactada — cambio mecánico, sin clases ni
funciones nuevas | Los tres puntos se resuelven con el mismo patrón: `logger.error(f"... |
usuario=... | canal=...: {e}", exc_info=True)` como primera línea de cada `except`, seguido del
literal fijo de la SPEC en el `return`/`GlassResponse.text` (sin interpolar `e`). En
`_ask_claude_for_user()` se preserva sin cambios la guarda existente del `pop()` del historial.
En `_handle_screenshot()` se preserva `vocative()` en el texto. Ningún import, firma de método,
ni línea fuera de los tres `except` se modifica. Detalle completo en
`propuestas/arquitectura-024.md`.

2026-09-07 | orion-architect | Diseño de `tests/test_gateway.py` (no existe hoy) | Se especifica
su creación con una prueba por criterio de aceptación de la SPEC (log con `exc_info=True` +
usuario/canal en los tres puntos, ausencia de fragmentos de `str(e)` en la respuesta en los tres
puntos, no-regresión del `pop()` de historial, no-regresión de `_save_semantic()` con
`logger.warning`, camino feliz de `process()` sin cambios) usando `unittest.mock.patch` sobre los
imports locales de cada método (`ai.user_manager.registry`, `ai.claude_brain.ask_claude`,
`pyautogui.screenshot`, `ai.memory_manager.memory.store`) — sin red, sin micrófono/altavoz, sin
tocar disco real, conforme a `.claude/rules/testing.md`.

2026-09-07 | orion-architect | Arquitectura aprobada | aprobado bajo autorización nocturna en
bloque del 2026-09-06 — no es revisión en vivo del usuario. Encaja en el criterio de esa
autorización: cambio mecánico acotado a un archivo, reduce superficie de fuga existente, sin
dependencias nuevas, sin nivel 🔴 Rojo. Propuesta completa en `propuestas/arquitectura-024.md`.

## Descartado (y por qué)
- Categoría CORE: descartada — el bug no toca el enrutamiento/dispatch/lógica de negocio del
  gateway, solo el manejo de excepción y qué se filtra a canales externos. Encaja mejor en
  SEGURIDAD según la propia definición de `.claude/rules/security-levels.md`.
- `_save_semantic()` (líneas ~169-175): descartado del alcance — ya usa `logger.warning(...)` y
  ese log nunca llega a un canal externo. No comparte el bug (confirmado por orion-spec al leer
  el código).

## Asumidos pendientes de confirmar
- Ninguno — resueltos por orion-spec en SPEC-024.md (ver "Decisiones tomadas" arriba).

## Riesgos activos
- Ninguno nuevo introducido por este REQ — el cambio reduce riesgo existente (fuga de
  información interna), no abre superficie nueva. La ampliación de alcance a
  `_ask_claude_for_user()` y `_handle_screenshot()` sigue el mismo criterio: cierra la misma
  clase de fuga en dos puntos adicionales, no abre nada nuevo.

## Log de transiciones
2026-09-07 | — → NUEVO | orion-coordinador | REQ creado
2026-09-07 | NUEVO → SPEC_APROBADO | orion-spec | SPEC-024.md redactada y aprobada bajo
autorización nocturna en bloque del 2026-09-06; alcance ampliado (justificado) a
`_ask_claude_for_user()` y `_handle_screenshot()`
2026-09-07 | SPEC_APROBADO → EN_ARQUITECTURA | orion-baseline | baseline-024.md redactado, sin
fallos preexistentes (1779 passed, 0 failed), sin archivos adicionales a modificar
2026-09-07 | EN_ARQUITECTURA → ARQUITECTURA_APROBADA | orion-architect | arquitectura-024.md
redactada y aprobada bajo autorización nocturna en bloque del 2026-09-06; sin clases/funciones
nuevas, sin dependencias nuevas; especifica creación de `tests/test_gateway.py`
2026-09-07 | ARQUITECTURA_APROBADA → EN_DESARROLLO → EN_PRUEBAS | orion-dev | los tres bloques
`except` de `channels/gateway.py` implementados según arquitectura; `tests/test_gateway.py`
creado (9 tests, 3 ajustados respecto al contenido sugerido); suite completa 1788 passed, 0
failed, sin regresiones respecto al baseline (1779 passed)
2026-09-07 | EN_PRUEBAS → EN_QA | orion-tester | 10/10 criterios de SPEC-024 verificados
directamente (código + tests + ejecución), 1788/1788 passed, 0 failed; test-results-024.md
redactado
2026-09-07 | EN_QA → EN_QA (aprobado, pendiente prueba manual) | orion-qa | qa-audit-024.md
redactado con veredicto ✅ APROBADO; se solicita prueba manual del humano antes de
LISTO_PARA_COMMIT

2026-09-07 | orion-dev | Implementación de los tres bloques `except` de `channels/gateway.py`
| Se aplicó tal cual el "Paso a paso mecánico" de `arquitectura-024.md`, sin desviación: los
tres `except` de `process()`, `_ask_claude_for_user()` y `_handle_screenshot()` ahora llaman a
`logger.error(..., exc_info=True)` con `usuario`/`canal` antes de construir la respuesta, y los
tres textos genéricos fijados en SPEC-024.md reemplazan la interpolación de `str(e)`. Ningún
otro método, import ni línea del archivo cambió; `_save_semantic()` intacto.

2026-09-07 | orion-dev | `tests/test_gateway.py` creado — 9 tests, todos pasan | Se usó como
base el contenido íntegro sugerido en `arquitectura-024.md`. Tres tests fallaban al ejecutarlos
y se ajustaron (detalle completo en `propuestas/desarrollo-log-024.md`, sección "Decisiones de
implementación"): (1-2) dos tests de `process()` mockeaban `ai.user_manager.registry.get_or_create`,
que se invoca fuera del bloque `try`/`except` bajo prueba — se cambió el punto de inyección de
la excepción a `core.resolution.resolve` (dentro del `try`); (3) un test de no-regresión del
`pop()` de historial llamaba `assert_called_once()` sobre una lista real (no un `Mock`) — se
reemplazó por verificar el efecto observable (`conversation_history == []`). Ningún criterio de
aceptación cambió de alcance, solo el mecanismo de la prueba.

2026-09-07 | orion-dev | Verificación completa sin regresiones | `python -m py_compile
channels/gateway.py tests/test_gateway.py` sin errores. `pytest tests/test_gateway.py -v`: 9
passed, 0 failed. `pytest tests/` completo: **1788 passed, 0 failed** (1779 baseline + 9 nuevos
de este REQ) — mismos warnings no relacionados que ya documentó `orion-baseline`, sin fallos
nuevos.

2026-09-07 | orion-dev | Implementación completada, lista para orion-tester | DoD de
`orion-dev` cumplido (ver checklist en `propuestas/desarrollo-log-024.md`). No se ejecutó
`git commit`. Mensaje de commit sugerido entregado en el handoff.

2026-09-07 | orion-tester | Verificación independiente completa — 10/10 criterios PASS | Se
releyeron SPEC-024.md, arquitectura-024.md y desarrollo-log-024.md completos, y se leyó
`channels/gateway.py` (192 líneas) y `tests/test_gateway.py` (125 líneas) directamente, sin
confiar en el reporte de `orion-dev`. Confirmado: los tres bloques `except` de `process()`
(105-115), `_ask_claude_for_user()` (141-149) y `_handle_screenshot()` (174-183) coinciden
exactamente con el "Paso a paso mecánico" de la arquitectura — `logger.error(..., exc_info=True)`
con usuario/canal como primera línea, seguido de literal fijo sin interpolar `str(e)`;
`_handle_screenshot()` conserva `vocative()`; `_save_semantic()` intacto; los bloques `try` de
los tres métodos son idénticos a los documentados en baseline (camino feliz sin cambios). Los 9
tests de `tests/test_gateway.py` se leyeron completos: inyectan la excepción dentro del `try`
real bajo prueba (`core.resolution.resolve`, `ai.claude_brain.ask_claude`,
`pyautogui.screenshot` — no mocks vacíos ni fuera de alcance), y cada uno verifica ambas mitades
del criterio de seguridad (logging con `exc_info=True` + usuario/canal, Y ausencia del fragmento
distintivo de `str(e)` en la respuesta). El ajuste de 3 tests que documentó `orion-dev` (cambio
de punto de inyección a `core.resolution.resolve`, verificación de efecto observable en vez de
`assert_called_once()` sobre lista real) se confirmó correcto y necesario, no un debilitamiento
del test.

`python -m py_compile channels/gateway.py tests/test_gateway.py`: sin errores.
`pytest tests/test_gateway.py -v`: 9 passed, 0 failed.
`pytest tests/ --tb=short -q` completo: **1788 passed, 0 failed** — mismos warnings no
relacionados que documentó `orion-baseline`, sin fallos nuevos.

**Veredicto: PASS (10/10 criterios).** Detalle completo en `pruebas/test-results-024.md`.

2026-09-07 | orion-tester | Handoff a orion-qa | Estado avanzado a EN_QA vía
`update-tracker.mjs`. Se intentó encadenar directamente al agente `orion-qa` en background con
instrucciones equivalentes a REQ-022; ver resultado del intento en el mensaje de cierre de esta
sesión.

2026-09-07 | orion-qa | Auditoría de seguridad y calidad completada — APROBADO | Verificación
independiente, sin confiar en los reportes previos: se releyó `channels/gateway.py` (192 líneas)
y `tests/test_gateway.py` (125 líneas) directamente, se re-ejecutó
`python -m py_compile channels/gateway.py tests/test_gateway.py` (sin errores),
`pytest tests/test_gateway.py -q` (9 passed) y `pytest tests/ -q` completo (**1788 passed, 0
failed**, mismos warnings no relacionados de sklearn). Se confirmó por `grep` que las 4 únicas
apariciones de `{e}` en el archivo (líneas 108, 144, 177, 191) están exclusivamente dentro de
`logger.error`/`logger.warning`, nunca en un valor retornado a un canal externo — ningún
fragmento de `str(e)` se filtra en los tres puntos corregidos. Sin `except` silenciosos (grep sin
coincidencias), sin API keys/tokens hardcodeados, sin acciones destructivas nuevas (no aplica
clasificación amarilla/roja — el REQ reduce superficie de fuga existente sin abrir ninguna nueva).
Logging interno con `exc_info=True` + usuario/canal correctamente acotado al proceso, no
reintroduce el riesgo. Convenciones de código respetadas (line-length, naming, sin `print()` de
debug). Veredicto explícito en `pruebas/qa-audit-024.md`.

**Este veredicto es juicio técnico propio de `orion-qa`, no una autoaprobación en nombre del
usuario** — la autorización nocturna en bloque del 2026-09-06 no alcanza a QA. Se solicita al
humano la prueba manual final antes de avanzar a `LISTO_PARA_COMMIT` real.
