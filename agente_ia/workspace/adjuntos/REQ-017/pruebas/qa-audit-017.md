# Auditoría QA REQ-017 — Completar/listar/crear tareas en lote sin trabarse por falta de ID exacto

**Agente:** orion-qa
**Fecha:** 2026-08-20
**Fuentes leídas:** `REQ-017-context.md` (completo), `spec/SPEC-017.md`,
`propuestas/arquitectura-017.md`, `propuestas/desarrollo-log-017.md`,
`pruebas/test-results-017.md` (veredicto orion-tester: 12/12 PASS).

**Metodología:** no se confió en los reportes de `orion-dev`/`orion-tester`. Se corrió
`git diff` real sobre `core/resolution.py`, `agents/tool_registry.py`,
`core/security_manager.py`, `requirements.txt`, `tests/test_resolution.py`,
`tests/test_tool_registry.py` y se comparó el diff efectivo contra lo que ambos reportes
afirman, línea por línea.

## Seguridad

- **Sin API keys/tokens/secretos hardcodeados.** `git diff` de `core/resolution.py` y
  `agents/tool_registry.py` no introduce ningún literal de credencial. Confirmado también
  con grep dirigido (`API_KEY`, `token =`, `password`) sobre el diff: sin hallazgos.
- **Sin `eval`/`exec`/`os.system`/`subprocess`** en el regex/lógica nueva de "todas". El
  diff completo de ambos archivos fue inspeccionado con grep dirigido: sin hallazgos.
  `_is_bulk_complete_phrase()` y `has_explicit_task_id()` son comparaciones de substring y
  un `re.search` compilado a nivel de módulo, sin interpolación de `text` en nada
  ejecutable — el string de usuario solo se usa como argumento de datos
  (`params={"text": text, "user_id": user_id}`), nunca como código ni como comando de
  shell. No aplica un DOM en este REQ (correcto, es lógica de backend/CLI, no webview).
- **`task_complete_all` (nuevo) sigue clasificado GREEN**, verificado en el `ToolSpec` real
  (`agents/tool_registry.py`, `register_tool(ToolSpec(name="task_complete_all", ...,
  risk_level=RiskLevel.GREEN, ...))`), mismo nivel que `task_complete` individual. No hay
  ningún camino que pida confirmación de forma distinta a como ya funciona `task_complete`
  hoy: ambos tools pasan una sola vez por `execute_tool()` → `security_manager.require_
  confirmation()` (GREEN nunca bloquea), y dentro de `_task_complete_all_invoke()` el
  bucle sobre `task_manager.complete_task()` ocurre DESPUÉS del gate, no antes ni en
  paralelo a él — no hay bypass de gate por tarea individual dentro del lote (correcto:
  la SPEC pide gate una vez por invocación de lote, no N veces por tarea, y así está
  implementado). Confirmado también por el test `test_task_complete_all_pasa_por_gate`,
  que espía la función real `security_manager.require_confirmation` (envolviéndola, no
  mockeándola ciegamente) y verifica el orden de llamadas.
- **Ninguna acción destructiva nueva.** `task_complete_all` marca tareas como completadas,
  no las borra ni modifica datos de forma irreversible en un sentido que amerite escalar
  su nivel de riesgo — consistente con que `task_complete` individual ya es GREEN hoy y la
  SPEC lo declara explícitamente como restricción NO NEGOCIABLE (sección "Restricción de
  seguridad" de `SPEC-017.md`).
- **`git diff -- core/security_manager.py` re-confirmado de forma independiente:** el
  único diff presente en el archivo son 3 líneas de `register_action()`
  (`delete_conversation`, `delete_task`, `delete_project`, las 3 YELLOW) con comentarios
  explícitos que las atribuyen a REQ-015/REQ-016, no a REQ-017. Ninguna línea del diff
  toca `_register_default_actions()` de forma relacionada con `task_complete`/
  `task_complete_all`, ni cambia `require_confirmation()`, `classify_action()` ni el
  deny-list fail-closed de REQ-005. **Confirmado: `delete_task` sigue YELLOW, sin
  modificación de comportamiento por REQ-017**, y el resto de la clasificación de riesgo
  existente (verde/amarillo/rojo) queda intacta.
- **Verificación adicional del punto de intercepción:** el bloque nuevo en
  `_try_task_tool()` vive dentro del mismo `try/except ActionDenied` preexistente de la
  función (no se agregó ningún `try` nuevo ni se removió el manejo de denegación) — si
  `execute_tool("task_complete_all", ...)` levantara `ActionDenied` (p. ej. si en el
  futuro se reclasifica el tool), el flujo cae en el mismo `except ActionDenied as e`
  que ya devuelve `_denied_message(e)` sin excepciones no controladas.

## Niveles de riesgo

- **Verde (puede actuar):** `task_complete` (existente, sin cambios), `task_complete_all`
  (nuevo, mismo nivel).
- **Amarillo (debe confirmar):** `delete_task`, `delete_conversation`, `delete_project`,
  `close_app`, `delete_file`, `delete_folder`, `execute_code`, `create_skill`,
  `modify_skill` y el resto del set YELLOW existente — **sin cambios de REQ-017**
  (confirmado por `git diff` sobre `core/security_manager.py`).
- **Rojo (no ejecuta):** deny-list fail-closed de REQ-005 — sin cambios de REQ-017.
- **Se implementaron confirmaciones nuevas:** No aplica — este REQ no introduce ninguna
  acción que requiera confirmación nueva. `task_complete_all` es GREEN por diseño
  aprobado explícitamente por Johan (SPEC-017.md, "Restricción de seguridad"), y esa
  decisión de UX está documentada como no negociable en cuanto a que NO diluye la
  confirmación de Amarillo/Rojo existente para ninguna otra acción.

## Logging

- No se detectó ningún `except: pass` ni `except Exception: pass` silencioso en el diff
  de `core/resolution.py` ni `agents/tool_registry.py` (grep dirigido sin hallazgos). El
  único `except` tocado indirectamente (por estar en la misma función donde se insertó
  código nuevo) es el `except ActionDenied as e:` preexistente de `_try_task_tool()`, que
  ya maneja el error devolviendo un mensaje al usuario — no lo traga en silencio.
- `_task_complete_all_invoke()` no usa `try/except` propio; si `task_manager.complete_task()`
  devuelve `False` para alguna tarea, esa tarea simplemente no entra en la lista `completed`
  (comprehension con filtro), sin excepción no controlada ni pérdida silenciosa de un error
  real — consistente con el contrato existente de `complete_task()` (devuelve bool, no
  lanza). `register_tool()` (sin tocar por este REQ) ya registra vía `logger.info` cada
  tool registrado, incluido `task_complete_all` al arrancar el proceso.
- No se agregó ninguna operación nueva que amerite logging de nivel WARNING/CRITICAL
  (esas categorías son para acciones Amarillo/Rojo — este REQ no introduce ninguna).

## Consistencia de código

- Convenciones de `.claude/rules/python-style.md`: `snake_case` en funciones/variables
  nuevas (`_is_bulk_complete_phrase`, `has_explicit_task_id`, `_task_complete_all_invoke`,
  `_TASK_BULK_ALL_RE`, `_TASK_COMPLETE_ALL_LIMIT`), type hints presentes en las funciones
  públicas/nuevas (`has_explicit_task_id(text: str) -> bool`,
  `_is_bulk_complete_phrase(text_lower: str) -> bool`), imports en orden (stdlib `re`
  antes que imports locales), sin imports sueltos dentro de función que ya se movieron a
  nivel de módulo (el propio REQ corrige uno preexistente: `import re` local de
  `_task_complete_invoke()` ahora es de módulo).
- **Hallazgo menor, no bloqueante:** `agents/tool_registry.py:225` —
  `pending_tasks = task_manager.list_tasks(user_id, status="pending", limit=_TASK_COMPLETE_ALL_LIMIT)`
  mide 102 caracteres, 2 por encima del límite de 100 de `python-style.md`. Es la única
  línea nueva de este REQ que excede el límite (verificado con conteo de longitud sobre
  todo el diff de ambos archivos). Sin impacto funcional ni de seguridad — es puramente
  estético. No amerita por sí solo un ciclo completo de vuelta a `orion-dev`; se deja
  registrado para que se corrija en la próxima edición de ese archivo (partirla en dos
  líneas). No bloquea el veredicto.
- Sin dead code ni prints de debug: grep dirigido (`print(`) sobre el diff sin hallazgos;
  no quedaron ramas muertas del código anterior (el flujo `create → bulk/list → complete`
  es secuencial con `return` temprano, sin código inalcanzable).
- `requirements.txt`: diff re-confirmado como perteneciente enteramente a REQ-015
  (`PyQt6-WebEngine`, `markdown`, `Pygments`, `bleach`, con comentario explícito
  "REQ-015" en el propio diff) — cero líneas de REQ-017, consistente con "Ninguna"
  dependencia nueva declarada en `arquitectura-017.md` §4.
- Tests nuevos (`tests/test_resolution.py` +175 líneas, `tests/test_tool_registry.py`
  +175 líneas) inspeccionados directamente, no solo por el conteo que reportan los
  agentes previos: son tests reales y específicos, no placeholders — `test_task_complete_
  all_pasa_por_gate` envuelve la función real de `security_manager` (no un mock ciego que
  siempre devuelva `True`), `test_task_complete_all_es_green_sin_confirmar` usa una trampa
  de `AssertionError` sobre `input()` en vez de solo verificar el tipo de retorno, y
  `test_mismo_texto_bulk_en_3_canales` ejercita `resolve()` real con los 3 `user_id`
  distintos por canal, no un solo canal repetido 3 veces.
- No se tocó ningún archivo fuera de lo previsto por `arquitectura-017.md`: confirmado con
  `git diff --stat` sobre `tests/test_reasoning_loop.py`, `channels/`,
  `tasks/task_manager.py`, `core/reasoning_loop.py`, `intent/intentions.py` → sin salida
  (cero diff) en los 6.

## Veredicto: ✅ COMPLETADO

Los 12/12 criterios de aceptación reportados PASS por `orion-tester` se sostienen bajo
revisión independiente. No hay hallazgos de seguridad: `task_complete_all` es GREEN sin
ningún camino de bypass de confirmación, la clasificación de riesgo existente
(`delete_task` YELLOW y el resto) no fue tocada por este REQ (confirmado por `git diff`
propio sobre `core/security_manager.py`), no hay secretos hardcodeados, no hay
`eval`/`exec`/`os.system`/`subprocess`, y no hay `except: pass` silencioso. Único hallazgo
es cosmético (una línea de 102 caracteres) y no bloquea la aprobación.

Corresponde solicitar la prueba manual final a Johan antes de entregar el mensaje de
commit sugerido.
