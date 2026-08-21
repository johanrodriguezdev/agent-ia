# Resultados de prueba REQ-016 — Sidebar tipo DeepSeek + Tareas + Proyectos + tipografía Inter

**Agente:** orion-tester
**Fecha:** 2026-08-20
**Método:** verificación por lectura directa del código real implementado (no por confianza en lo
reportado por `orion-dev`) + ejecución independiente de compilación y suite completa de tests +
ejecución aislada de subconjuntos de tests críticos + una verificación física a nivel SQLite (CA-20)
+ comparación de `mtime` de archivos para corroborar qué se tocó realmente en esta sesión vs. qué
viene intacto de REQ-015.

## Compilación

- `python -m py_compile ai/memory_manager.py ui/webview/bridge.py core/security_manager.py main.py`
  → **OK**, sin errores (confirmado independientemente).
- `node --input-type=module --check` sobre los 5 `.js` nuevos/modificados (`sidebar.js`, `app.js`,
  `bridge_client.js`, `tasks_panel.js`, `projects_panel.js`) → **OK**, sin errores de sintaxis
  (confirmado independientemente; `node --check` sin `--input-type=module` falla en los 5 porque el
  repo no tiene `package.json` con `"type":"module"` — mismo método que usó `orion-dev`, verificado
  que produce el mismo resultado).

## Tests existentes (suite completa, corrida independiente)

- **420 passed, 2 failed** — conteo confirmado de forma independiente, no tomado del reporte de
  `orion-dev` (que reportó el mismo número).
- Los 2 `FAILED` son exactamente:
  - `tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse`
  - `tests/test_llm_provider.py::test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto`
  - Ambos por `ModuleNotFoundError: No module named 'anthropic'` — idénticos a los 2 fallos
    pre-existentes documentados en `baseline-016.md` (dependencia de entorno no instalada, sin
    relación con UI/tareas/proyectos). **Nuevos fallos: ninguno.**
- Diferencia vs. baseline (365 passed) = +55 tests nuevos de este REQ, tal como reportó `orion-dev`:
  17 en `test_memory_manager_projects.py`, 17 nuevos en `test_webview_bridge.py`, 6 nuevos en
  `test_security_manager.py`, + extensión paramétrica de `test_webview_safe_dom_insertion.py` sobre
  los 2 JS nuevos.

## Criterios de la SPEC (34 CA)

| CA | Resultado | Nota |
|----|-----------|------|
| CA-01 | PASS | `index.html` L43-50: `#sidebar-toolbar.icon-pill` agrupa colapsar+búsqueda+nuevo chat en un único contenedor con fondo/borde/sombra (`sidebar.css` L48-58). Reemplaza el header+botón sueltos anteriores. |
| CA-02 | PASS | `.pill-btn:hover`/`.pill-btn.active` definidos (`sidebar.css` L75-83), estados distinguibles por control. |
| CA-03 | PASS (verificación por lectura de código, no automatizable en este repo) | `applySearchFilter()` en `sidebar.js` filtra `.conv-item` por `textContent` de `.conv-title`; listeners de `sidebar-search-toggle`/`sidebar-search-input` en `initSidebar()`; se reaplica al final de `renderConversationList()`. Sin round-trip al bridge. |
| CA-04 | PASS | `#new-conversation-btn` conserva el mismo `id`; listener en `sidebar.js` L95-97 idéntico a REQ-015 (`newConversation()`), solo cambió el contenedor padre en el DOM. |
| CA-05 | PASS | `#tasks-btn` en `index.html` L55-58; `openTasksPanel()` llama `requestTasks()` → `Bridge.request_tasks()` → `task_manager.list_all_tasks(user_id="default")`, sin filtro de canal (verificado en `bridge.py`). |
| CA-06 | PASS | `_create_task_flow()` en `bridge.py` L342-348 llama `task_manager.create_task(..., channel="desktop")` sin modificar la función; guard de título vacío en `create_task()` (bridge) y en `buildTaskForm()` (JS). |
| CA-07 | PASS | `_complete_task_flow()` llama `task_manager.complete_task()`; `.task-item.completed` en `panels.css` da distinción visual (`text-decoration: line-through`). Test `test_complete_task_no_pide_confirmacion` PASS (corrida aislada). |
| CA-08 | PASS — verificado con confirmación mockeada en `False` | `_delete_task_flow()` (`bridge.py` L369-381): `if not confirmed: return` ANTES de `task_manager.delete_task()`. Test `test_request_delete_task_pide_confirmacion_antes_de_delete_task` corrido en aislamiento: con `require_confirmation` devolviendo `False`, `delete_calls == []` — `task_manager.delete_task` **nunca** se invoca. PASS. |
| CA-09 | PASS | `task_manager.list_all_tasks()` (`tasks/task_manager.py` L372-384, archivo confirmado sin modificar por `mtime` Aug-18) ya ordena `CASE WHEN status='pending' THEN 0 ELSE 1 END, due_date ASC` en SQL; `_on_tasks_loaded()`/`renderTasks()` serializan tal cual, sin `.sort()` en JS (grep confirmado: cero ocurrencias). |
| CA-10 | PASS — verificado en el flujo real de arranque, no solo la línea en el archivo | `main.py` L106: `task_scheduler.start()` es la primera línea ejecutable dentro de `def main()`, inmediatamente después de `proactive_engine.start()` (L105) — no comentada, no en rama muerta. Confirmado además que `main()` SÍ se invoca en el flujo real de escritorio: `if __name__ == "__main__":` (L214+) crea `MainWindow()` (la ventana WebView) y, en paralelo, siempre arranca `jarvis_runner()` en un hilo (`threading.Thread`, L260-261) que llama `main(gui_active=...)` — mismo patrón ya usado por `proactive_engine.start()` para llegar al modo escritorio. `task_scheduler.stop()` simétrico en el cierre (L120). |
| CA-11 | PASS | `tasks/task_manager.py` sin modificar (confirmado por `mtime` Aug-18, anterior incluso a REQ-015) — mismo `tasks.db`, mismo `user_id="default"`, sin tabla nueva ni escritura paralela. |
| CA-12 | PASS | `request_initial_state()` (`bridge.py` L157-161) solo emite `chips_loaded`/`theme_changed`/`_load_conversations` — cero llamada a `request_tasks`/`list_all_tasks`. Test `test_request_tasks_no_se_llama_en_request_initial_state` PASS (corrida aislada). |
| CA-13 | PASS | `#projects-btn` en `index.html` L59-62; `openProjectsPanel()` → `requestProjects()` → `memory.list_projects()`. |
| CA-14 | PASS | `create_project()` (`ai/memory_manager.py` L575-592) valida `name.strip()` no vacío server-side, retorna `None` si vacío; `Bridge.create_project()` valida también antes de despachar. Test `test_create_project_rechaza_nombre_vacio_o_solo_espacios` PASS (corrida aislada). |
| CA-15 | PASS | `list_projects()` — una sola query agregada con subquery de conteo, `ORDER BY created_at DESC`. |
| CA-16 | PASS | Picker en `projects_panel.js` (`openAssignPicker()`) alimentado por `getLoadedConversations()` de `sidebar.js` → `Bridge.assign_conversation_to_project()` → `memory.assign_conversation_to_project()` (verifica `user_id` de ambos lados antes de escribir). |
| CA-17 | PASS | `request_project_conversations()` → `memory.list_conversations_by_project()` (INNER JOIN contra `memories`) → señal `project_conversations_loaded(json, project_id)`; `renderProjectConversations()` descarta respuesta si `project_id` no coincide con la vista activa (caso borde de doble click). |
| CA-18 | PASS — verificado con confirmación mockeada en `False` | `_delete_project_flow()` (`bridge.py` L468-482): mismo gate `if not confirmed: return` antes de `memory.delete_project()`. Test `test_request_delete_project_pide_confirmacion_antes_de_delete_project` corrido en aislamiento: `delete_calls == []` cuando la confirmación es `False`. PASS. |
| CA-19 | PASS | `delete_project()` (`ai/memory_manager.py` L704+) solo hace `DELETE` sobre `projects`/`project_conversations`, nunca sobre `memories`. Test dedicado `test_delete_project_no_borra_conversaciones` PASS (corrida aislada). |
| CA-20 | PASS — verificado físicamente a nivel SQLite, no solo por diseño de código | `project_conversations.conversation_id TEXT PRIMARY KEY` confirmado en el schema real (`ai/memory_manager.py` L148-153). Prueba dedicada en este REQ-tester (SQLite standalone): un `INSERT` crudo duplicado sobre la misma `conversation_id` es rechazado por SQLite con `IntegrityError: UNIQUE constraint failed`; `INSERT OR REPLACE` reasigna sin duplicar (1 sola fila tras reasignar). Es físicamente imposible una asignación doble a nivel de esquema, no solo por evitarlo en el código Python. |
| CA-21 | PASS — no-regresión confirmada por lectura directa, no por el reporte de orion-dev | Las 5 funciones protegidas (`new_conversation_id` L219, `store_turn` L262, `list_conversations` L294, `get_conversation_turns` L333, `delete_conversation` L542 de `ai/memory_manager.py`) leídas íntegras: ninguna referencia a `projects`/`project_conversations`, cuerpo idéntico al documentado por `orion-baseline`. La limpieza de huérfanos vive en `Bridge._delete_conversation_flow()` (`ui/webview/bridge.py` L260-277): `memory.unassign_conversation_from_project(...)` se llama DESPUÉS de `memory.delete_conversation()`, nunca dentro de ella — confirmado que `delete_conversation()` no la conoce. Tests dedicados corridos en aislamiento: `test_new_conversation_id_store_turn_list_conversations_get_conversation_turns_delete_conversation_sin_cambios` PASS y `test_delete_conversation_no_limpia_project_conversations_por_si_sola` PASS (este último confirma explícitamente, con una fila real en la tabla, que `delete_conversation()` NO limpia `project_conversations` por sí sola — la limpieza es responsabilidad exclusiva del bridge). |
| CA-22 | PASS | `sidebar.css` L227-230: `#sidebar.collapsed .sidebar-action-btn, #sidebar.collapsed .pill-btn { justify-content: center; }` — cubre íconos existentes y los 2 nuevos (Tareas/Proyectos). |
| CA-23 | PASS | Los 5 controles del sidebar (colapsar, búsqueda, nuevo chat, Tareas, Proyectos) tienen `title="..."` en `index.html` (grep confirmado, L45/47/49/55/59). |
| CA-24 | PASS | Única regla de transición de layout (`#sidebar { transition: width 200ms ease; }`) sin tocar; las reglas nuevas de CA-22 (`justify-content`, `flex-direction`, `border-radius`, `display:none`) no están en ninguna lista de `transition-property`, no introducen un segundo timing. |
| CA-25 | PASS — no-regresión confirmada por lectura íntegra del archivo | `sidebar.js` leído completo: `buildConversationItem()`, `setActiveConversationId()`, `removeConversationFromList()` sin cambios de cuerpo respecto a lo esperado de REQ-015. Único código nuevo: 2 listeners de búsqueda en `initSidebar()`, acumulación en `renderConversationList()`, `getLoadedConversations()` nueva. Corroborado por `mtime`: comparado con archivos hermanos intactos de REQ-015 (`chat.js`, `composer.js`, etc., todos Aug-19) — `sidebar.js` sí tiene mtime Aug-20 (tocado hoy), consistente con las adiciones documentadas, no con un reemplazo mayor. Suite `tests/test_webview_smoke.py`/`test_webview_contrast.py`/`test_webview_gui_state.py`/`test_webview_window_geometry.py`/`test_webview_theme.py` (48 tests, cobertura de regresión REQ-015) corrida en aislamiento: 48 passed. |
| CA-26 | PASS | `ui/webview/frontend/fonts/` contiene `Inter-Regular.woff2` (111.268 B), `Inter-Medium.woff2` (114.348 B), `Inter-Bold.woff2` (114.840 B) — verificados con lectura binaria de los primeros 4 bytes: magic `wOF2` (0x774f4632) en los 3, confirmando WOFF2 real (no placeholder/HTML de error). `css/fonts.css` usa `url("../fonts/Inter-*.woff2")` (ruta relativa local). CSP de `index.html` L5-6 confirmada **sin cambios** respecto a lo documentado por `orion-spec` en el contexto (`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self';`). |
| CA-27 | PASS | `css/reset.css` L20: `font-family: "Inter", -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;` — Inter primero, fallback de sistema intacto. |
| CA-28 | PASS | 3 pesos confirmados como binarios reales: 400 (`Inter-Regular.woff2`), 500 (`Inter-Medium.woff2`), 700 (`Inter-Bold.woff2`), cada uno con su bloque `@font-face` correspondiente en `fonts.css`. |
| CA-29 | PASS | `css/chat.css` L133: `font-family: "Cascadia Code", Consolas, "Courier New", monospace;` sin cambios. Archivo con `mtime` Aug-19 (no tocado en esta sesión). |
| CA-30 | PASS | `css/theme.css` con `mtime` Aug-19 (no tocado en esta sesión, cero cambios de color). Suite `test_webview_contrast.py` (11 tests, valida pares WCAG AA con los tokens reales de `theme.css`) corrida en aislamiento: 11 passed — el contraste ya auditado en REQ-015/CA-36 sigue intacto. |
| CA-31 | PASS | Ver sección "Compilación" arriba — confirmado independientemente. |
| CA-32 | PASS | Ver sección "Tests existentes" arriba — 420 passed/2 failed confirmado independientemente, mismos 2 fallos pre-existentes, cero fallos nuevos. |
| CA-33 | PASS — verificado con confirmación mockeada en `False`, no solo por lectura del código | Ver CA-08/CA-18 arriba: ambos flujos (`delete_task`, `delete_project`) verificados con test que mockea `security_manager.require_confirmation` devolviendo `False` y confirma que la función destructiva subyacente (`task_manager.delete_task`/`memory.delete_project`) nunca se invoca. Corridos en aislamiento, ambos PASS. |
| CA-34 | PASS | Docstring de `bridge.py` (L1-15) enumera explícitamente las 4 funciones de `task_manager.py` y las 6 nuevas de `memory_manager.py`. Grep de `task_manager\|memory_manager\|from ai\.\|from tasks\.` sobre `ui/webview/frontend/js/`: cero resultados — ningún JS importa los módulos Python directo. |

**Resultado: 34/34 PASS.**

## Regresión

| Área revisada | Resultado |
|---------------|-----------|
| Suite completa (`pytest tests/`) | 420 passed, 2 failed (pre-existentes, no atribuibles) |
| `tests/test_webview_bridge.py` completo (85 tests) | 85 passed (corrida aislada) |
| `tests/test_security_manager.py` completo (55 tests) | 55 passed (corrida aislada, incluye los 10 tests originales de REQ-005/deny-list Rojo) |
| `tests/test_memory_manager_delete_conversation.py` (REQ-015, no-regresión dedicada) | 7 passed (corrida aislada) |
| `tests/test_memory_manager_projects.py` (nuevo, 17 tests) | 17 passed (corrida aislada) |
| `tests/test_webview_contrast.py`, `test_webview_smoke.py`, `test_webview_gui_state.py`, `test_webview_window_geometry.py`, `test_webview_theme.py` (regresión visual/REQ-015) | 48 passed (corrida aislada) |
| `tasks/task_manager.py`, `tasks/task_scheduler.py`, `ui/webview/confirmation_adapter.py`, `chat.js`/`composer.js`/`confirm_modal.js`/`window_chrome.js`/`theme.js`, `theme.css`/`chat.css`/`composer.css`/`layout.css`/`animations.css` | Confirmado sin modificar — `mtime` de sistema de archivos anterior a esta sesión (Aug-18/Aug-19), consistente con "sin modificar" declarado en arquitectura y dev-log |
| Desviación 1 — retiro del bloque CSS `#sidebar-collapse-toggle` preexistente | Justificada: conflicto real de especificidad CSS (selector de ID vs. `.pill-btn`) confirmado leyendo el CSS actual — no queda ningún bloque `#sidebar-collapse-toggle {}` residual; el comportamiento (listener de colapso) sigue intacto en `sidebar.js`, sin cambios. No rompe CA-06..CA-11 de SPEC-015 (confirmado por los 48 tests de regresión visual arriba). |
| Desviación 2 — `handleProjectRemoved()` como función real en vez del comentario-placeholder | Justificada y verificada: función exportada real en `projects_panel.js` L247+, wireada en `app.js` L111 (`onProjectRemoved((projectId) => handleProjectRemoved(projectId))`), comportamiento consistente con lo descrito en §0.4/§8.4 de la arquitectura (vuelve a vista maestro si el proyecto borrado era el que estaba en detalle). |

## Veredicto: PASS

Los 34 criterios de aceptación de SPEC-016 se verificaron por lectura directa del código real
(no por el reporte de `orion-dev`), con ejecución independiente de compilación, suite completa de
tests, subconjuntos aislados de los tests más críticos, una verificación física a nivel SQLite
(CA-20) y comparación de `mtime` de archivos para corroborar qué se tocó realmente. Cero
regresiones nuevas — los 2 únicos `FAILED` de la suite son pre-existentes y no atribuibles a este
REQ. Las 2 desviaciones menores reportadas por `orion-dev` están bien justificadas, verificadas y no
rompen ningún criterio de SPEC-015 (CA-06..CA-11) ya validado.
