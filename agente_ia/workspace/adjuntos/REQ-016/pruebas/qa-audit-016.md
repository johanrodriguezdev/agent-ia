# Auditoría QA REQ-016 — Sidebar tipo DeepSeek + Tareas + Proyectos + tipografía Inter

**Agente:** orion-qa
**Fecha:** 2026-08-20
**Contexto especial:** `orion-security` no corrió como paso dedicado en este REQ (decisión explícita
de Johan, §11 de `arquitectura-016.md`) — esta auditoría es el único gate de seguridad antes de la
prueba manual del humano. Se prestó atención puntual reforzada a los 3 puntos que §11 dejó a cargo de
`orion-qa`, además del checklist estándar completo.

**Fuentes leídas:** `REQ-016-context.md` (íntegro), `spec/SPEC-016.md` (34 CA), `propuestas/
arquitectura-016.md` (15 secciones íntegras, incluidas §9-§15), `propuestas/desarrollo-log-016.md`,
`pruebas/test-results-016.md` (veredicto 34/34 PASS). Toda verificación de código de esta auditoría
es **lectura directa del código real y ejecución independiente de tests** — no se dio por bueno lo
reportado por `orion-dev`/`orion-tester` sin comprobarlo.

---

## Punto 1 (reforzado) — `delete_task`/`delete_project` YELLOW, gate real no bypasseable

**Clasificación de riesgo — confirmada por lectura directa de `core/security_manager.py`:**
- Líneas 316-317: `sm.register_action("delete_task", RiskLevel.YELLOW)` /
  `sm.register_action("delete_project", RiskLevel.YELLOW)`, en el mismo bloque y con el mismo
  comentario de justificación que `delete_conversation` (línea 311, ya auditado en
  `qa-audit-015.md`/Hallazgo C).
- `git diff HEAD -- core/security_manager.py` confirma que el único cambio del archivo respecto al
  último commit es exactamente esas 2 líneas + su comentario — nada más se tocó (`CHANNEL_ALLOWED_LEVELS`,
  `_DETAILS_ALLOWED_KEYS`, `require_confirmation()` en sí: intactos).

**El gate es real, no un adorno visual — verificado en 3 capas:**
1. **Lectura del bridge** (`ui/webview/bridge.py`): `_delete_task_flow()` (líneas 369-381) y
   `_delete_project_flow()` (líneas 468-482) llaman `security_manager.require_confirmation("delete_task"/
   "delete_project", ChannelType.DESKTOP, ...)` y hacen `if not confirmed: return` **antes** de tocar
   `task_manager.delete_task()`/`memory.delete_project()`. No hay ninguna rama que ejecute la acción
   destructiva sin haber pasado por esa línea.
2. **No hay bypass posible desde JS por diseño**: `_delete_task_flow`/`_delete_project_flow` son
   métodos privados (prefijo `_`, sin decorador `@pyqtSlot`) — `QWebChannel` solo expone a JS los
   métodos marcados `@pyqtSlot`. Los únicos slots públicos son `request_delete_task(task_id)` y
   `request_delete_project(project_id)`, que únicamente despachan esos flujos privados vía
   `run_async()`. Confirmé además en `ui/webview/frontend/js/bridge_client.js` y en
   `tasks_panel.js`/`projects_panel.js` que el único camino JS hacia el borrado es
   `requestDeleteTask()`/`requestDeleteProject()` → `_bridge.request_delete_task/request_delete_project`
   — ningún otro wrapper ni ruta alternativa existe en el frontend.
3. **Verificado en runtime, no solo por lectura**: corrí independientemente
   `tests/test_webview_bridge.py::test_request_delete_task_pide_confirmacion_antes_de_delete_task` y
   `test_request_delete_project_pide_confirmacion_antes_de_delete_project` (mockean
   `require_confirmation` devolviendo `False` primero) — confirmado que `task_manager.delete_task`/
   `memory.delete_project` **nunca se invocan** en ese caso (`delete_calls == []`), y sí se invocan al
   mockear `True`. `complete_task()` (no destructivo) confirmado que NO pide confirmación
   (`test_complete_task_no_pide_confirmacion`, con un `require_confirmation` que lanza `AssertionError`
   si se llegara a invocar). Los 3 tests PASS en corrida propia.

**Veredicto: PASS.** Clasificación correcta, gate centralizado y real, sin superficie de bypass desde JS.

---

## Punto 2 (reforzado) — Cero SQL sin parametrizar en `ai/memory_manager.py` (proyectos)

Leí íntegras las 6 funciones nuevas (`create_project`, `list_projects`,
`assign_conversation_to_project`, `unassign_conversation_from_project`,
`list_conversations_by_project`, `delete_project`) y el bloque de creación de esquema
(`CREATE TABLE projects` / `CREATE TABLE project_conversations` / 2 índices) dentro de `_init_db()`.

**Confirmado, sin excepción:** las 8 queries nuevas (2 `CREATE TABLE`, 2 `CREATE INDEX`, 2 `SELECT`,
1 `INSERT`/`INSERT OR REPLACE`, 2 `DELETE`) usan exclusivamente placeholders `?` con la tupla de
parámetros pasada aparte a `conn.execute(sql, params)` — cero f-strings, cero `.format()`, cero
concatenación (`+`) de valores dentro del literal SQL. Ni siquiera `project_id`/`conversation_id`
(que sí viajan como parte de la lógica de negocio) se interpolan directo en el string.

`git diff HEAD -- ai/memory_manager.py` confirma que estas son las únicas adiciones al archivo salvo
`ProjectSummary` (dataclass) — las 5 funciones protegidas por CA-21 (`new_conversation_id`, `store`,
`store_turn`, `list_conversations`, `get_conversation_turns`, `delete_conversation`) no aparecen en el
diff en absoluto, confirmando la no-regresión (ver también Punto de regresión REQ-015 más abajo).

Defensa en profundidad ya presente y verificada: `assign_conversation_to_project()` valida
`user_id` tanto del proyecto como de la conversación antes de escribir (dos `SELECT` de verificación
antes del `INSERT OR REPLACE`); `delete_project()`/`unassign_conversation_from_project()` filtran por
`user_id` en el `WHERE` — mismo patrón que ya usa `delete_conversation()`.

**Veredicto: PASS.** Cero superficie de inyección SQL nueva.

---

## Punto 3 (reforzado) — `tasks_panel.js`/`projects_panel.js`: inserción segura en el DOM

Grep estructural propio (`\.innerHTML\s*=|insertAdjacentHTML\s*\(|eval\(|document\.write`) sobre
ambos archivos: **cero coincidencias de código real** — las únicas ocurrencias de la palabra
"innerHTML" en los archivos son comentarios que documentan la regla ("nunca innerHTML"), no código.

Leí `tasks_panel.js` completo (162 líneas): todo texto no confiable (`task.title`, `task.due_date`)
se inserta vía `textContent` sobre un nodo creado con `document.createElement`, nunca interpolado en
un template de `innerHTML`. Confirmé el mismo patrón por lectura puntual de los 4 puntos de inserción
de `projects_panel.js` (`project.name`, `conv.title` ×2 más en el picker/detalle) — todos vía
`textContent`.

`tests/test_webview_safe_dom_insertion.py::_MUST_NOT_USE_INNERHTML` confirmado extendido con
`"tasks_panel.js", "projects_panel.js"` (línea 31). Corrí el archivo completo de forma independiente:
**12 tests, 12 passed** (incluye `test_ningun_otro_archivo_js_del_frontend_usa_innerhtml` — red de
seguridad adicional sobre todo `ui/webview/frontend/js/*.js`, y `test_chat_js_es_la_unica_excepcion_documentada`,
que confirma que la única excepción real —`chat.js`, campo `html` pre-sanitizado— sigue siendo la
única).

**Veredicto: PASS.**

---

## Checklist estándar de seguridad

- **Secretos/API keys hardcodeados:** ninguno. Grep de patrones de credencial
  (`api_key=`, `token=`, `password=`, `sk-`, `AIza`) sobre los 4 módulos Python y los 2 JS/2 CSS
  nuevos de este REQ: sin resultados reales (solo falsos positivos de nombres de clase CSS).
- **Acciones destructivas piden confirmación:** cubierto arriba (Punto 1). El resto de acciones
  YELLOW/RED preexistentes no se tocó (confirmado por `git diff` acotado a los 4 archivos Python).
- **Niveles verde/amarillo/rojo respetados:** `ChannelType.DESKTOP` sigue permitiendo
  `[GREEN, YELLOW]` sin cambios; `RiskLevel.RED` (deny-list de REQ-005) intacto.
- **`except: pass` silencioso:** **ninguno agregado por este REQ.** Verifiqué con `git diff HEAD` de
  los 4 archivos Python tocados (`ai/memory_manager.py`, `ui/webview/bridge.py`,
  `core/security_manager.py`, `main.py`) que cada bloque `except` nuevo introducido por REQ-016 usa
  `except Exception as e: logger.error(...)` — sin excepción. Sí existen algunos `except Exception:`
  sin log explícito en esos mismos archivos (p. ej. `ai/memory_manager.py:499`,
  `core/security_manager.py:157`, `main.py:205`) pero **confirmé con `git diff HEAD` que ninguno de
  esos bloques aparece en el diff de este REQ** — son código preexistente, ajeno al alcance de
  REQ-016 (mismo criterio que la arquitectura ya aplicó en §12 para el `except Exception: pass`
  preexistente de `tasks/task_scheduler.py::_notify_local()`, fuera de alcance porque SPEC-016 exige
  no modificar ese archivo). No corresponde rechazar el REQ por deuda técnica que no le pertenece,
  pero queda documentado acá para un REQ futuro de limpieza si Johan lo considera.
- **Validación de inputs:** `create_task()`/`create_project()` validan título/nombre no vacío tanto en
  JS (guard de formulario) como en el bridge (defensa en profundidad, mismo criterio que
  `send_message()`); `assign_conversation_to_project()` valida pertenencia de ambos IDs antes de
  escribir.
- **Dead code / prints de debug:** grep de `print(`/`console.log`/`debugger;` sobre los 4 archivos
  Python y los 5 archivos JS tocados/nuevos: sin resultados nuevos (los `print()` preexistentes de
  `main.py` — bloque `__main__`, manejo de `KeyboardInterrupt`/errores fatales — no forman parte del
  diff de este REQ). Leí `tasks_panel.js` completo: sin código muerto, sin funciones sin usar.
- **`requirements.txt`:** confirmado **sin cambios de REQ-016** — `git diff requirements.txt` muestra
  únicamente el bloque ya etiquetado `# --- Interfaz gráfica WebView (REQ-015) ---`
  (`PyQt6-WebEngine`, `markdown`, `Pygments`, `bleach`), cero líneas nuevas atribuibles a REQ-016,
  consistente con §13 de la arquitectura (Inter es un asset estático vendorizado, no una dependencia
  pip).

---

## Logging

- Las 6 funciones nuevas de `ai/memory_manager.py` registran `logger.error(...)` en su except antes
  de devolver `None`/`False`/`[]` — sin excepción tragada en silencio.
- `_on_task_error()`/`_on_project_error()` en `bridge.py` registran `logger.error(...)` y además
  re-emiten `error_occurred` hacia la UI — el error no se pierde ni queda solo en el log.
- Confirmación YELLOW de `delete_task`/`delete_project` queda trazada en `audit.db` vía
  `_log_audit()` (mismo mecanismo centralizado de `require_confirmation()`, sin cambios).

---

## Consistencia de código

- Type hints presentes en las 6 funciones nuevas de `memory_manager.py` y en los 10 slots nuevos de
  `bridge.py`. Docstrings en modo imperativo, con referencia explícita al CA que satisfacen.
- `snake_case`/`PascalCase` respetados (`ProjectSummary` como dataclass, métodos en snake_case).
- Imports ordenados stdlib → third-party → locales en los módulos tocados.
- JS: `tasks_panel.js` (162 líneas, leído completo) y los 4 puntos de inserción de
  `projects_panel.js` revisados — sin código muerto, guards contra doble click (`_panelOpen`)
  documentados y correctos.
- Sintaxis verificada de forma independiente: `python -m py_compile` sobre los 4 módulos Python — sin
  errores. `node --input-type=module --check` sobre los 5 `.js` (`sidebar.js`, `app.js`,
  `bridge_client.js`, `tasks_panel.js`, `projects_panel.js`) — sin errores, corrida propia.

---

## No-regresión de las garantías ya auditadas en `qa-audit-015.md`

- **15 `@pyqtSlot` originales de REQ-015:** confirmado por grep propio de `@pyqtSlot` sobre
  `ui/webview/bridge.py` completo — los 15 (`request_initial_state`, `send_message`,
  `new_conversation`, `select_conversation`, `request_delete_conversation`,
  `load_more_conversations`, `run_chip_action`, `set_theme`, `toggle_wake_word`, `confirm_response`,
  `start_resize`, `start_move`, `window_minimize`, `window_toggle_maximize`, `window_close`) siguen
  presentes con la misma firma. Se agregaron exactamente 10 nuevos (5 tareas + 5 proyectos) — total
  25, ninguno eliminado ni modificado.
- **Sanitización Markdown/XSS:** `ui/webview/markdown_render.py` **no aparece en el diff de REQ-016**
  (confirmado por `git diff HEAD` acotado) — `render_markdown()` sigue aplicando
  `markdown.markdown()` + `bleach.clean()` con el mismo `ALLOWED_TAGS`/`ALLOWED_ATTRS`/
  `ALLOWED_PROTOCOLS = ["http", "https"]` de siempre. `chat.js` sigue siendo el único archivo con
  `innerHTML` real (confirmado por el mismo test extendido de §10).
- **Timeout de confirmación fail-closed:** `ui/webview/confirmation_adapter.py` **tampoco aparece en
  el diff de REQ-016** — `CONFIRM_TIMEOUT_SECONDS = 120`, `event.wait(timeout=...)` seguido de
  `confirmed = False` si no respondió a tiempo, limpieza de `self._pending` incondicional. Reutilizado
  tal cual por `delete_task`/`delete_project` (mismo adaptador registrado para `ChannelType.DESKTOP`,
  sin un segundo mecanismo de confirmación nuevo).
- **CSP sin cambios:** `ui/webview/frontend/index.html` línea 5-6 verificada carácter por carácter —
  `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;
  connect-src 'self';`, idéntica a la que documentó `orion-spec`. `css/fonts.css` usa rutas relativas
  locales (`../fonts/Inter-*.woff2`), consistente con `default-src 'self'` sin necesidad de
  `font-src` adicional.

---

## Compilación y suite completa — verificación independiente

- `python -m py_compile ai/memory_manager.py ui/webview/bridge.py core/security_manager.py main.py`
  → **OK**, corrida propia, sin errores.
- `node --input-type=module --check` sobre los 5 `.js` → **OK**, corrida propia.
- `python -m pytest tests/ --tb=short -q` (suite completa) → **420 passed, 2 failed**, corrida propia
  desde cero. Los 2 `FAILED` son exactamente
  `tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` y
  `test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto` (`ModuleNotFoundError: No module named
  'anthropic'`) — idénticos a los pre-existentes de `baseline-016.md`. **Cero fallos nuevos.**
- `python -m pytest tests/test_security_manager.py tests/test_memory_manager_projects.py
  tests/test_webview_safe_dom_insertion.py -q` → **84 passed**, corrida aislada propia.
- `python -m pytest tests/test_webview_bridge.py -q -k "task or project"` → **29 passed**, corrida
  aislada propia.
- Leí el código fuente real de los 3 tests de confirmación mockeada (`test_request_delete_task_pide_
  confirmacion_antes_de_delete_task`, `test_request_delete_project_pide_confirmacion_antes_de_delete_project`,
  `test_complete_task_no_pide_confirmacion`) para confirmar que sus asserts prueban lo que dicen
  probar (no un `assert True` disfrazado) — confirmado, los 3 son pruebas genuinas.

---

## Veredicto: ✅ COMPLETADO

Los 3 puntos reforzados que `arquitectura-016.md` §11 dejó a cargo de `orion-qa` (clasificación YELLOW
+ gate real de `delete_task`/`delete_project`, SQL parametrizado en las queries nuevas de proyectos,
inserción segura en el DOM de los 2 JS nuevos) se verificaron con lectura directa del código real y
ejecución independiente de tests — no por confianza en lo reportado por `orion-dev`/`orion-tester`.
El checklist estándar de seguridad, logging y consistencia de código no encontró hallazgos. Las
garantías de `qa-audit-015.md` (15 slots originales, sanitización Markdown/XSS, timeout fail-closed de
confirmación, CSP) siguen intactas — confirmado por `git diff` acotado que ninguno de esos 3 archivos
(`markdown_render.py`, `confirmation_adapter.py`) aparece en el diff de REQ-016. `requirements.txt`
confirmado sin cambios atribuibles a este REQ. Suite completa sin regresiones nuevas (420 passed/2
failed, ambos pre-existentes y no atribuibles).

No se encontró ningún motivo de rechazo. **APROBADO.**

Siguiente paso: prueba manual de Johan (a solicitar por el orquestador — REQ-016 y REQ-015 quedan
para la misma sesión de prueba, dado que Johan decidió no separar los commits) antes de entregar el
mensaje de commit sugerido.
