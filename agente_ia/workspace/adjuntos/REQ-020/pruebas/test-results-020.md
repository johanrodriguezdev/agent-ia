# Resultados de prueba REQ-020 — Reorganización visual de NODDOO en tres columnas

**Fecha:** 2026-08-25
**Agente:** orion-tester
**Fuente:** `SPEC-020.md` (26 criterios) + `desarrollo-log-020.md` + `baseline-020.md`

## Metodología

No se probó solo por revisión de código. Además de leer `index.html`/`layout.css`/
`panels.css`/`composer.css`/`chat.css`/`settings_panel.css` y los `.js` tocados, se levantó
la app real en un `QWebEngineView` offscreen (mismo mecanismo que
`tests/test_webview_smoke.py`, `PyQt6.QtWebEngineWidgets`, `QT_QPA_PLATFORM=offscreen`) con
`window.show()` + `qtbot.waitExposed()` para tener layout real, se esperó
`window.__ORION_APP_READY__`, y se corrieron aserciones vía `page().runJavaScript()` sobre
el DOM/CSS ya cargado y renderizado (no simulado). Se emitieron señales reales del bridge
(`tasks_loaded`, `message_appended`, `conversation_cleared`) y se redimensionó la ventana de
verdad (1024×640 y 1400×800) para validar el colapso responsivo. El script ad-hoc
(`tests/test_req020_manual_verification.py`, 10/10 verde) se usó solo como arnés de prueba
temporal y se borró al terminar — no queda en el repo ni es parte de la suite permanente.

## Compilación
- `python -m py_compile main.py`: **OK** (sin errores)

## Tests existentes
- Suite completa (`pytest tests/ --tb=short -q`): **538 passed / 2 failed**
- Fallos: `tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse`
  y `test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto` — **idénticos a los 2
  preexistentes documentados en `baseline-020.md`** (`ModuleNotFoundError: No module named
  'anthropic'`, falta el paquete en el entorno local), sin relación con `ui/webview/`.
- **Nuevos fallos: ninguno.**
- Subset `pytest tests/ -k "webview"`: 194 passed / 346 deselected (igual al baseline).
- `tests/test_webview_safe_dom_insertion.py` + `tests/test_webview_theme.py`: 30/30 passed.

## Criterios de la SPEC

| Criterio | Resultado | Nota |
|----------|-----------|------|
| CA-01 | PASS | Verificado en DOM real: `#app-body` tiene exactamente 3 hijos flex en este orden — `sidebar`, `main-column`, `side-panel`. Ninguno usa `position:absolute/fixed`. |
| CA-02 | PASS | `#side-panel` computa `width:300px`, `flex:none`. A 1024×640 (mínimo soportado) queda oculto por la media query y `#main-column` recupera el ancho (verificado `getBoundingClientRect().width > 300` en vivo); a 1400×800 el chat sigue con espacio (`#main-column flexGrow:1`). Sin superposición en ningún caso. |
| CA-03 | PASS | `sidebar.js`/`sidebar.css` sin diff — colapsar, buscar, nuevo chat, lista, footer con toggle de tema intactos. Único cambio dentro de `#sidebar` es la eliminación de `#tasks-btn` (cubierto por CA-09), sin tocar el resto de sus hijos/listeners. |
| CA-04 | PASS | `chat.js`/`composer.js` conservan envío, adjuntos, wake toggle, indicador de escritura; único agregado es `relocateChipsRow()` (cubierto por CA-19/20) sin recrear nodos ni desregistrar listeners — confirmado en vivo (`test_webview_smoke.py` sigue en verde: fondo no transparente, input con borde/fondo/placeholder). |
| CA-05 | PASS | En DOM real, inmediatamente tras `__ORION_APP_READY__` (sin ningún click simulado), `#tasks-panel-mount` ya tiene hijos (cabecera + formulario + lista). |
| CA-06 | PASS | Lectura de código (`app.js`/`tasks_panel.js`): `mountTasksPanel()` se llama en `bootstrap()`, sin listener de click en el camino; `requestTasks()` vive en el cuerpo de `mountTasksPanel()`. Confirmado además indirectamente en vivo: el panel ya tiene contenido sin haber simulado ningún click. |
| CA-07 | PASS | `buildTaskForm()`/`buildTaskItem()` sin cambios; `createTask`/`completeTask`/`requestDeleteTask` mismas firmas de `bridge_client.js` (archivo sin diff). Verificado en vivo con `tasks_loaded` real (40 tareas) renderizando `.task-item` correctamente. |
| CA-08 | PASS | `requestDeleteTask(task.id)` sigue siendo el único disparador del botón ✕ (sin cambios respecto al modal); `confirm_modal.js`/`app.js::onConfirmationRequested` sin diff — mismo camino `confirmation_requested → showConfirmModal` sobre `#confirm-modal-root`, independiente de `#tasks-panel-mount`. No-regresión de seguridad confirmada por ausencia de diff en la cadena completa. |
| CA-09 | PASS | `document.getElementById("tasks-btn")` devuelve `null` en el DOM real. Decisión (eliminación completa) documentada en `desarrollo-log-020.md`, consistente con `arquitectura-020.md`. Sin listener huérfano en `app.js` (grep confirma cero referencias a `tasks-btn`/`openTasksPanel`/`closeTasksPanel` en todo `ui/webview/`). |
| CA-10 | PASS | `tests/test_webview_safe_dom_insertion.py` — 14/14 tests del archivo en verde, incluye `tasks_panel.js` por nombre explícito y el test estructural que barre todo `frontend/js/*.js`. |
| CA-11 | PASS | En DOM real, `#side-panel` tiene como hijos, en orden, `#monitor-panel-section` (con título "Monitor de sistema") y luego `#tasks-panel-mount` — coincide con ASUMIDO 1 aprobado. |
| CA-12 | PASS | Verificado en vivo: `#monitor-panel-section` no contiene ningún `script/button/input/select/a` (0 elementos interactivos), consistente con "cero JS, cero llamada al bridge". |
| CA-13 | PASS | Texto exacto "Métricas del sistema — próximamente" presente y visible en `#monitor-panel-section` (confirmado por `textContent` en DOM real). |
| CA-14 | PASS | El placeholder usa `.panel-empty` sin CSS nuevo propio; `#monitor-panel-section` solo agrega box-model (`flex/padding/border-bottom`), sin color ni token nuevo. |
| CA-15 | PASS | `git diff` sobre `ui/webview/frontend/css/theme.css`: sin cambios. |
| CA-16 | PASS | `git diff` sobre `ui/webview/theme.py`: sin cambios. `tests/test_webview_theme.py` 12/12 passed (incluye el test de drift). |
| CA-17 | PASS | Revisado el diff completo de los 5 archivos CSS tocados (`layout.css`, `panels.css`, `settings_panel.css`, `composer.css`, `chat.css`): ninguna línea agregada introduce hex/rgb/hsl — todo color viene de `var(--...)` ya existente. Los `#ffffff`/`rgba(...)` que aparecen en esos archivos son preexistentes (no forman parte del diff de este REQ). |
| CA-18 | PASS | `theme.js` sin diff; `#side-panel` no fija ningún `data-theme` propio, hereda tokens del `:root`/`[data-theme]` global igual que `#sidebar`/`#main-column`. Confirmado indirectamente por `tests/test_webview_smoke.py` (fondo no transparente en ambos temas) sin regresión. |
| CA-19 | PASS | Verificado en vivo: en el estado inicial (sin mensajes), `document.getElementById("chips-row").parentElement.id === "empty-state-chips-slot"` — los chips ya están dentro de `#empty-state` desde el arranque, sin que el usuario escriba nada. |
| CA-20 | PASS | Verificado en vivo: al emitir `message_appended` (simulando una conversación en curso), `#chips-row` se reubica a `parentElement.id === "composer"`; al limpiar la conversación (`conversation_cleared`), vuelve a `"empty-state-chips-slot"`. `renderChips()`/`onChipsLoaded` sin cambios de comportamiento. |
| CA-21 | PASS | Verificado en vivo: click real en `#projects-btn` sigue montando un `.modal-overlay` dentro de `#panel-modal-root` (antes vacío) — mismo punto de entrada y mismo overlay que hoy. `projects_panel.js`/`settings_panel.js` conservan `_panelOpen`, `open*Panel()`/`close*Panel()`, montaje sobre `#panel-modal-root`. |
| CA-22 | PASS | `desarrollo-log-020.md` documenta explícitamente qué se replicó (composición de cabecera ícono+título vía `.panel-header-title-group`, corrección de foco en `.panel-form`/`.settings-row-select`) y qué no (agrupación por estado, hover/focus de `.panel-close-btn`), con motivo en ambos casos. Confirmado contra el código real de `projects_panel.js::renderMasterShell()` y `settings_panel.js::renderShell()`. |
| CA-23 | PASS | `projects_panel.js`/`settings_panel.js` importan exactamente las mismas funciones de `bridge_client.js` que antes (`requestProjects`, `createProject`, `requestSecurityOverrides`, `saveSecurityOverride`, etc.) — `bridge_client.js` y `bridge.py` sin diff. |
| CA-24 | PASS | `python -m py_compile main.py` sin errores; ningún archivo `.py` figura en el diff de este REQ (`git diff --stat` sobre `ui/webview/*.py` vacío). |
| CA-25 | PASS | Suite completa: 538 passed / 2 failed — mismo conteo y mismos 2 tests que `baseline-020.md`. Sin fallos nuevos. |
| CA-26 | PASS | Grep sobre `frontend/` por patrones de telemetría (CPU/memoria/RAM/red/uptime/temperatura/latencia/núcleo): sin coincidencias reales (único match fue un falso positivo de `requestAnimationFrame` conteniendo la subcadena "ram"). `#monitor-panel-section` es 100% texto estático sin ningún número/gauge. |

**26/26 PASS**

## Regresión

| Área revisada | Resultado |
|---------------|-----------|
| Sidebar de conversaciones (colapsar/buscar/nuevo chat/lista/footer) | Sin regresión — `sidebar.js`/`sidebar.css` sin diff |
| Chat (envío, adjuntos, wake toggle, indicador de escritura, XSS §10.1) | Sin regresión — `tests/test_webview_smoke.py` en verde (3 casos adversariales XSS + bleed-through + input visible) |
| Tareas — crear/completar/eliminar + confirmación amarilla de borrado | Sin regresión — mismas firmas de bridge, mismo flujo de confirmación, verificado en vivo con 40 tareas simuladas |
| Proyectos (modal, maestro/detalle, picker de asignación) | Sin regresión — mismo ciclo de vida modal, verificado apertura real en vivo |
| Configuración (modal, fila de seguridad con `<select>`) | Sin regresión — `settings_panel.js` sin cambios de lógica, solo cabecera |
| Cambio de tema oscuro/claro | Sin regresión — `theme.py`/`theme.css`/`theme.js` sin diff |
| `tests/test_webview_safe_dom_insertion.py` (sin innerHTML fuera de `chat.js`) | 14/14 passed |
| `tests/test_webview_theme.py` (drift Python↔CSS) | 12/12 passed |
| `tests/test_webview_smoke.py` (QWebEngineView real offscreen) | Passed dentro del subset `webview` (194/194) |
| Suite completa de regresión | 538 passed / 2 failed (idéntico a baseline, 2 fallos ajenos por falta de paquete `anthropic`) |

## Riesgos de `ui-design-020.md` verificados explícitamente (no solo código)

- `getComputedStyle(#tasks-panel-list).maxHeight === "none"` dentro de `#tasks-panel-mount`:
  **confirmado en vivo** (clase `panel-list panel-list-flex` aplicada correctamente).
- Cadena `min-height:0` (`#side-panel` → `#tasks-panel-mount` → `.panel-list-flex`):
  **confirmada en vivo** (`0px` en los 3 niveles vía `getComputedStyle`).
- Lista larga de tareas (40 ítems) sin empujar `#monitor-panel-section`: **confirmado en
  vivo** — `monitorHeight > 0` se mantiene, `#side-panel.scrollHeight` no excede su propia
  altura visible (el scroll queda contenido en `.panel-list-flex`, no en el `<aside>`).
- `document.getElementById("tasks-btn") === null`: **confirmado en vivo**.
- Posición de `#chips-row` antes/después de simular `isEmpty()`: **confirmado en vivo** con
  señales reales del bridge (`message_appended`, `conversation_cleared`).

## Veredicto: PASS

26/26 criterios de aceptación de SPEC-020 en PASS, verificados tanto por revisión de código
como por ejecución real en `QWebEngineView` offscreen (DOM/CSS/JS resultante, no solo
inspección estática). Cero fallos nuevos en la suite de regresión. Compilación limpia.
