# Contexto REQ-025 — Fuga de error interno a Discord en discord_bot.py._process_message()

## Resumen ejecutivo
`channels/discord_bot.py::_process_message()` (líneas 56-76) tiene un `except Exception as e:`
(línea 75) que retorna `f"Error procesando su solicitud: {str(e)[:100]}"` (línea 76) directamente
como mensaje visible en el canal de Discord, sin ningún `logger.error()` previo. Es el mismo patrón
de bug que REQ-024 corrigió en `channels/gateway.py`. Objetivo: loguear el error real internamente
(con `exc_info=True` y contexto de usuario) y devolver al canal un mensaje genérico fijo, sin tocar
ningún otro `except Exception` del archivo.

## Estado actual
- **Estado tracker:** SPEC_APROBADO
- **Último agente:** orion-spec
- **Fecha última actualización:** 2026-09-07
- **Rama git:** —
- **Categoría:** SEGURIDAD
- **Tipo de cambio:** SEGURIDAD (bug fix quirúrgico — fuga de información interna a canal externo)

## Decisiones tomadas
2026-09-07 | orion-spec | SPEC-025 redactada — único bloque afectado: `_process_message()` líneas
75-76 de `channels/discord_bot.py` | Se verificaron los 6 `except Exception` restantes del archivo
(líneas 52, 95-96, 135-136, 163-164, 195-198, 239-242) durante la lectura completa; ninguno
comparte el patrón (falta de log + `str(e)` crudo devuelto al canal), así que el alcance quirúrgico
pedido por el humano queda confirmado sin ampliaciones (a diferencia de REQ-024, donde la lectura
sí encontró puntos adicionales).
2026-09-07 | orion-spec | Texto genérico fijado: "Lo siento, he encontrado un inconveniente
inesperado. Intente de nuevo en un momento." | Idéntico al usado en `gateway.py::process()`
(REQ-024) por ser el punto más análogo (entrada general de procesamiento de mensaje).
2026-09-07 | orion-spec | Formato de log fijado: `logger.error(..., exc_info=True)` con
`user_id`/`user_name`/canal="discord" | Mismo formato que gateway.py (REQ-024), usando los
parámetros que `_process_message()` ya recibe.
2026-09-07 | orion-spec | SPEC-025 aprobada bajo autorización nocturna en bloque del 2026-09-06 |
No es revisión interactiva del humano — autoaprobación documentada explícitamente conforme a la
autorización vigente (REQ-025 no abre superficie nueva, es corrección quirúrgica de bug de
seguridad existente, replica patrón ya aprobado en REQ-024).
2026-09-07 | orion-coordinador | REQ creado — categoría=SEGURIDAD | Detección explícita: la descripción
del humano indica categoría SEGURIDAD directamente (fuga de información hacia canal externo, patrón
ya clasificado como bug de seguridad en REQ-024).
2026-09-07 | orion-coordinador | Alcance quirúrgico confirmado — SOLO `_process_message()` líneas
56-76 de `channels/discord_bot.py` | El humano indicó explícitamente no tocar los demás
`except Exception` del archivo (líneas 52, 95-96, 135-136, 163-164, 195-198, 239-242), replicando
el criterio de alcance que usó REQ-024 en `gateway.py`.
2026-09-07 | orion-coordinador | REQ autoaprobable en spec/arquitectura bajo autorización nocturna
2026-09-06 | Corrección quirúrgica de bug de seguridad existente, no abre superficie nueva de
ataque (a diferencia de REQ-023/webhook). Cualquier autoaprobación posterior en este REQ debe
registrarse explícitamente como "aprobada bajo autorización nocturna en bloque del 2026-09-06",
nunca como revisión personal del humano. git commit/push/merge/rebase siguen prohibidos; ninguna
acción 🔴 Rojo se ejecuta.
2026-09-07 | orion-coordinador | Referencia de estilo obligatoria: `channels/gateway.py` (post
REQ-024) | El humano pidió que el mensaje genérico devuelto al canal sea consistente en tono con el
ya aprobado en REQ-024 para gateway.py.
2026-09-07 | orion-architect | Arquitectura redactada en `propuestas/arquitectura-025.md`: fix
acotado a las líneas 75-76 de `_process_message()` — `logger.error(f"Error en
discord_bot._process_message() | usuario={user_id} ({user_name}) | canal=discord: {e}",
exc_info=True)` antes del `return`, y `return` reemplazado por el literal fijo "Lo siento, he
encontrado un inconveniente inesperado. Intente de nuevo en un momento." | Mismo formato de log y
mismo texto genérico que `gateway.py::process()` (REQ-024), tal como fijó SPEC-025; ningún import
nuevo (`logger` ya existe en el archivo, línea 36).
2026-09-07 | orion-architect | Pruebas sugeridas para `tests/test_discord_bot.py` (archivo nuevo):
parcheando `channels.gateway.GlassGateway` (no `channels.discord_bot.GlassGateway`, por ser import
local dentro de `_process_message()`) para forzar la excepción | Necesario documentarlo porque el
import de `GlassGateway` ocurre en tiempo de ejecución dentro de la función, no a nivel de módulo.
2026-09-07 | orion-architect | Arquitectura autoaprobada bajo autorización nocturna en bloque del
2026-09-06, registrada explícitamente como tal (no revisión personal de Johan) | Cambio mecánico
acotado a un bloque, sin superficie nueva, replica patrón ya aprobado en REQ-024 — encaja en el
criterio de la autorización vigente, a diferencia de REQ-023 (excluido por abrir listener HTTP).
2026-09-07 | orion-dev | Implementado el "Paso a paso mecánico" de arquitectura-025.md literalmente
en `channels/discord_bot.py::_process_message()`: `logger.error(..., exc_info=True)` con
usuario/canal antes del `return`, y `return` reemplazado por el texto genérico fijo (idéntico al de
`gateway.py` REQ-024), sin interpolar `str(e)` | Sin ajustes respecto a la propuesta.
2026-09-07 | orion-dev | Creado `tests/test_discord_bot.py` (nuevo, 7 tests) copiando la sección
"Pruebas sugeridas" de arquitectura-025.md tal cual, incluida la nota técnica de parchear
`channels.gateway.GlassGateway` (no `channels.discord_bot.GlassGateway`) por ser import local |
Sin ajustes respecto a la propuesta.
2026-09-07 | orion-dev | Verificación local: `py_compile` limpio; `pytest tests/test_discord_bot.py`
→ 7 passed; suite completa `pytest tests/` → 1795 passed (1788 baseline + 7 nuevos), 0 failed, sin
warnings nuevas respecto a `origen/baseline-025.md` | `git diff` confirmado acotado al bloque
`except` de `_process_message()`, los otros 6 `except Exception` del archivo quedan idénticos.
2026-09-07 | orion-dev | `desarrollo-log-025.md` generado con mensaje de commit sugerido incluido
(no entregado al usuario aún, corresponde al cierre del pipeline completo) | Handoff a
orion-tester.
2026-09-07 | orion-tester | 8/8 criterios PASS — verificación independiente, no se confió en el
reporte de orion-dev | Se releyó `channels/discord_bot.py` directamente y se recreó `git diff`
(hunk acotado a las 5→10 líneas del `except` de `_process_message()`); se contrastaron línea por
línea los otros 6 `except Exception` contra `origen/baseline-025.md`, idénticos. Adicionalmente se
revirtió el fix con `git stash` sobre solo ese archivo y se re-corrió `tests/test_discord_bot.py`:
5/7 tests fallan sin el fix (los ligados a criterios de SPEC), 2/7 pasan en ambos casos (camino
feliz y `_get_agent_name()`, fuera de alcance) — confirma que los tests no son tautológicos.
Restaurado el fix con `git stash pop`. Suite completa `pytest tests/` → 1795 passed, 0 failed, sin
warnings nuevas. Detalle completo en `pruebas/test-results-025.md`. Siguiente: orion-qa.

## Descartado (y por qué)
- Tocar otros `except Exception` de `discord_bot.py`: descartado explícitamente por el humano —
  fuera de alcance de este REQ.

## Asumidos pendientes de confirmar
- Ninguno — resuelto en SPEC-025: el mensaje genérico es textualmente idéntico al usado en
  `gateway.py::process()` tras REQ-024 (ver `spec/SPEC-025.md`).

## Riesgos activos
- Ninguno de seguridad nuevo — el fix reduce superficie de fuga, no la amplía. Único riesgo
  operativo: no tocar por error alguno de los otros 6 `except Exception` de `discord_bot.py`
  (líneas 52, 95-96, 135-136, 163-164, 195-198, 239-242), ya verificados fuera de patrón por
  `orion-baseline` (detalle en `origen/baseline-025.md`).

## Estado actual
- Estado tracker: EN_QA
- Último agente: orion-qa
- Rama git: — (sin rama activa; mismo criterio que REQ-024, cambio quirúrgico de un solo bloque
  sobre `main`, no se asume rama nueva sin preguntar al humano)
- QA segunda vuelta: ✅ COMPLETADO — pendiente prueba manual del humano

## Log de transiciones
2026-09-07 | — → NUEVO | orion-coordinador | REQ creado
2026-09-07 | NUEVO → SPEC_APROBADO | orion-spec | SPEC-025 redactada y autoaprobada bajo
autorización nocturna en bloque del 2026-09-06 | siguiente: orion-baseline
2026-09-07 | SPEC_APROBADO → EN_BASELINE → EN_ARQUITECTURA | orion-baseline | Baseline
documentado en `origen/baseline-025.md`: estado actual de `_process_message()` (líneas 56-76)
transcrito y verificado igual al descrito en SPEC-025; confirmados los otros 6 `except Exception`
del archivo fuera de patrón (sin cambios de alcance); `python -m py_compile` limpio sobre
`discord_bot.py` y `gateway.py`; suite completa `pytest tests/` → 1788 passed, 0 failed, ningún
fallo pre-existente atribuible a este REQ; `tests/test_discord_bot.py` confirmado inexistente hoy
(archivo nuevo a crear, no modificación) | siguiente: orion-architect
2026-09-07 | EN_ARQUITECTURA → ARQUITECTURA_APROBADA | orion-architect | Arquitectura redactada en
`propuestas/arquitectura-025.md` y autoaprobada bajo autorización nocturna en bloque del
2026-09-06 (no revisión personal de Johan) — fix acotado a líneas 75-76 de `_process_message()`,
sin dependencias nuevas, sin superficie nueva | siguiente: orion-dev
2026-09-07 | ARQUITECTURA_APROBADA → EN_DESARROLLO → EN_PRUEBAS | orion-dev | Implementado
literalmente el paso a paso de arquitectura-025.md en `channels/discord_bot.py::_process_message()`
y creado `tests/test_discord_bot.py` (7 tests nuevos); `desarrollo-log-025.md` generado; suite
completa 1795 passed (1788 + 7), 0 failed | siguiente: orion-tester
2026-09-07 | EN_PRUEBAS → EN_QA | orion-tester | Verificación independiente completa: compilación
OK, 8/8 criterios de SPEC-025 PASS, diff acotado confirmado, tests nuevos confirmados no
tautológicos (revert manual del fix → 5/7 fallan como se espera), suite completa 1795 passed, 0
failed | `test-results-025.md` generado | siguiente: orion-qa
2026-09-07 | EN_QA → EN_DESARROLLO | orion-qa | Auditoría de seguridad/logging/alcance: todo correcto (sin fuga de `str(e)`,
`logger.error(..., exc_info=True)` con contexto, sin secretos, alcance acotado verificado,
consistente con `gateway.py` REQ-024) | Un hallazgo de estilo: línea 81 de `channels/discord_bot.py`
(`return` del texto genérico) mide 102 caracteres, excede el límite de 100 de
`.claude/rules/python-style.md`; `gateway.py::process()` (mismo texto, referencia obligatoria de
este REQ) lo parte en dos líneas precisamente por esto y `discord_bot.py` no replicó ese detalle |
Veredicto: ❌ RECHAZADO — `pruebas/qa-audit-025.md` generado con fix sugerido (partir el string en
dos líneas con concatenación implícita, sin tocar contenido/tono/log) | siguiente: orion-dev
2026-09-07 | orion-dev | Segunda vuelta — aplicado el fix exacto sugerido por `qa-audit-025.md`:
`return` de una sola línea (102 caracteres) partido en dos strings con concatenación implícita,
mismo patrón que `gateway.py::process()` (REQ-024) | Motivo único: exceso de 2 caracteres sobre el
límite de 100 de `.claude/rules/python-style.md`; sin tocar contenido, tono, `logger.error(...)` ni
ningún otro `except Exception` del archivo. No se volvió a pasar por `orion-architect` — ajuste de
formato dentro del "Paso a paso mecánico" ya aprobado, tal como indicó `orion-qa`.
2026-09-07 | orion-dev | Verificación local segunda vuelta: `py_compile` limpio; ninguna línea del
bloque modificado supera 100 caracteres (confirmado con script Python línea por línea); 2 líneas
preexistentes fuera de alcance (hoy 236 y 271) que ya excedían 100 caracteres antes de REQ-025,
verificadas contra `HEAD` — no se tocan; `pytest tests/test_discord_bot.py` → 7 passed (sin cambios,
el contenido del string no varió); suite completa `pytest tests/` → 1795 passed, 0 failed, mismas 11
warnings preexistentes | `desarrollo-log-025.md` actualizado con sección "Segunda vuelta — corrección
de formato" (sin sobreescribir la primera). Handoff a orion-tester para re-verificación.
2026-09-07 | EN_DESARROLLO → EN_PRUEBAS | orion-dev | Segunda vuelta: aplicado el único fix pedido
por `qa-audit-025.md` (línea 81 de `discord_bot.py` partida en dos strings por exceder 100
caracteres); verificación local repetida sin regresiones (1795 passed, 0 failed) | siguiente:
orion-tester
2026-09-07 | orion-tester | Segunda vuelta — re-verificación independiente del fix de formato:
`py_compile` OK, ninguna línea del bloque modificado supera 100 caracteres (verificado línea por
línea con script, no visualmente), texto genérico verificado vía AST idéntico carácter por
carácter a la primera vuelta (solo cambió el formato del `return`, ahora en 3 líneas con
concatenación implícita), `logger.error(...)` sin cambios, `git diff` sigue acotado al único bloque
`except` de `_process_message()`, otros 6 `except Exception` del archivo sin tocar |
`tests/test_discord_bot.py` → 7 passed sin necesidad de edición; suite completa `pytest tests/` →
1795 passed, 0 failed, mismas 11 warnings preexistentes | 9/9 criterios PASS (8 de SPEC-025 + el
hallazgo de estilo que motivó el rechazo de QA) | Detalle en sección "Segunda vuelta" de
`pruebas/test-results-025.md` | siguiente: orion-qa
2026-09-07 | EN_PRUEBAS → EN_QA | orion-tester | Segunda vuelta PASS — 9/9 criterios, sin
regresiones, fix de formato verificado independiente | siguiente: orion-qa
2026-09-07 | orion-qa | Segunda vuelta — re-auditoría: hallazgo de la primera vuelta (línea 81 de
`channels/discord_bot.py`, 102 caracteres) verificado como resuelto de forma independiente —
máximo del bloque modificado ahora 91 caracteres (línea 77), medido línea por línea con script
Python, ninguna línea del bloque 75-84 supera 100 caracteres | Contenido/logging/alcance
verificados idénticos a la primera vuelta: `logger.error(..., exc_info=True)` con contexto sin
cambios, texto genérico idéntico carácter por carácter (ahora en 3 líneas con concatenación
implícita), sin `str(e)` en el retorno, `git diff` sigue acotado al único bloque `except` de
`_process_message()`, sin secretos, sin problemas nuevos | `py_compile` OK, `pytest
tests/test_discord_bot.py` → 7 passed, verificados de forma independiente | Veredicto: ✅
COMPLETADO | `pruebas/qa-audit-025.md` actualizado con sección "Segunda vuelta" | Pendiente:
prueba manual del humano antes de `LISTO_PARA_COMMIT` | siguiente: Humano (prueba manual)

2026-09-18 | → LISTO_PARA_COMMIT | conversación principal (sesión nocturna autorizada por Johan) | Sincronización del tracker con `main`: el código de este REQ ya está commiteado y mergeado y la evidencia (QA aprobado y/o suite en verde registrada en este contexto) estaba completa. Solo cambia el estado; no se toca código.
