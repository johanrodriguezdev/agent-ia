# Desarrollo REQ-016 — Sidebar tipo DeepSeek + Tareas programadas + Proyectos + tipografía Inter

**Agente:** orion-dev
**Fecha:** 2026-08-20
**Fuente de verdad técnica:** `workspace/adjuntos/REQ-016/propuestas/arquitectura-016.md` (15
secciones, ✅ APROBADA) — implementado exactamente lo especificado ahí, sin reinterpretar ni
rediseñar. `orion-security` no se invocó en este REQ (decisión explícita de Johan, confirmada en §11
de la arquitectura).

## Archivos modificados

- `ai/memory_manager.py` — 2 tablas nuevas (`projects`, `project_conversations`) dentro de
  `_init_db()`, `ProjectSummary` (dataclass) y 6 métodos nuevos de `UnifiedMemory`
  (`create_project`, `list_projects`, `assign_conversation_to_project`,
  `unassign_conversation_from_project`, `list_conversations_by_project`, `delete_project`). **Cero
  líneas modificadas** en `new_conversation_id()`, `store_turn()`, `list_conversations()`,
  `get_conversation_turns()`, `delete_conversation()` (CA-21, verificado con test de no-regresión
  dedicado).
- `ui/webview/bridge.py` — docstring del módulo extendido (CA-34, whitelisting), 4 `pyqtSignal`
  nuevas (`tasks_loaded`, `projects_loaded`, `project_conversations_loaded`, `project_removed`), 10
  `@pyqtSlot` nuevos (5 tareas: `request_tasks`, `create_task`, `complete_task`,
  `request_delete_task`; 5 proyectos: `request_projects`, `create_project`,
  `assign_conversation_to_project`, `unassign_conversation_from_project`,
  `request_project_conversations`, `request_delete_project`) + sus helpers `_fetch_*`/`_emit_*`/
  `_on_*_error`. `_delete_conversation_flow()` extendida con una línea
  (`memory.unassign_conversation_from_project(...)` tras un borrado exitoso, CA-21 segunda mitad) —
  el resto de la función queda idéntica a REQ-015.
- `core/security_manager.py::_register_default_actions()` — 2 líneas nuevas: `delete_task` y
  `delete_project` como `RiskLevel.YELLOW`, mismo comentario/criterio que `delete_conversation`.
  Nada más se tocó en el archivo.
- `main.py` — import de `tasks.task_scheduler.task_scheduler` + `task_scheduler.start()` junto a
  `proactive_engine.start()` (CA-10) + `task_scheduler.stop()` junto a `proactive_engine.stop()`
  (simetría, no exigido literal por CA-10 pero mismo criterio que ya usa el archivo).
- `ui/webview/frontend/index.html` — `#sidebar-toolbar.icon-pill` (colapsar + búsqueda + nuevo chat
  agrupados), `#sidebar-search-row`, botones `#tasks-btn`/`#projects-btn`, `#panel-modal-root`
  (raíz separada de `#confirm-modal-root`), `title=""` en los 5 controles del sidebar,
  `<link>` a `css/fonts.css` y `css/panels.css`.
- `ui/webview/frontend/css/sidebar.css` — bloque `.icon-pill`/`.pill-btn` (CA-01, CA-02),
  `#sidebar-search-row`/`#sidebar-search-input`, centrado de íconos en `.collapsed` (CA-22), y
  eliminación del bloque `#sidebar-collapse-toggle`/`#sidebar-collapse-toggle:hover` — ver
  "Decisiones de implementación" abajo (desviación menor respecto al texto literal de la
  arquitectura, con motivo).
- `ui/webview/frontend/css/reset.css` — 1 línea: `font-family` del `body` pasa a `"Inter", ...`
  (fallback de sistema intacto, CA-27).
- `ui/webview/frontend/js/sidebar.js` — 1 función nueva exportada (`getLoadedConversations()`),
  filtro de búsqueda client-side (`applySearchFilter()`, listeners de
  `sidebar-search-toggle`/`sidebar-search-input` dentro de `initSidebar()`), acumulación de
  `_loadedConversations` dentro de `renderConversationList()`. **Cero** cambios en
  `buildConversationItem()`, `setActiveConversationId()`, `removeConversationFromList()` (CA-25).
- `ui/webview/frontend/js/app.js` — imports y wiring aditivo de `tasks_panel.js`/`projects_panel.js`
  (botones `tasks-btn`/`projects-btn`, señales `tasks_loaded`/`projects_loaded`/
  `project_conversations_loaded`/`project_removed`) dentro de `bootstrap()`. Ninguna línea previa
  modificada.
- `ui/webview/frontend/js/bridge_client.js` — 10 wrappers JS→Python + 4 `on*` Python→JS nuevos,
  mismo patrón 1:1 que el resto del archivo.
- `tests/test_webview_safe_dom_insertion.py` — `_MUST_NOT_USE_INNERHTML` extendida con
  `tasks_panel.js` y `projects_panel.js` (§10).
- `tests/test_webview_bridge.py` — 17 tests nuevos (tareas + proyectos) + `_EXPECTED_SLOTS`/
  `_EXPECTED_SIGNALS` extendidas con los 10 slots y 4 señales nuevos.
- `tests/test_security_manager.py` — 6 tests nuevos: clasificación YELLOW de `delete_task`/
  `delete_project`, confirmación en canal desktop, y guard de `check_coverage()`.

## Archivos nuevos

- `ui/webview/frontend/css/fonts.css` — 3 bloques `@font-face` de Inter (400/500/700,
  `font-display: swap`), rutas relativas, sin CDN (CA-26, CA-28).
- `ui/webview/frontend/css/panels.css` — estilos de contenido de los modales de Tareas/Proyectos
  (reutiliza `.modal-overlay`/`.modal-box` de `modal.css`).
- `ui/webview/frontend/js/tasks_panel.js` — modal de Tareas completo (CA-05..CA-12).
- `ui/webview/frontend/js/projects_panel.js` — modal de Proyectos, maestro/detalle + picker de
  asignación (CA-13..CA-21).
- `ui/webview/frontend/fonts/Inter-Regular.woff2`, `Inter-Medium.woff2`, `Inter-Bold.woff2`,
  `LICENSE-OFL.txt` — vendorizados desde el release oficial `rsms/inter` v4.1 (ver sección
  "Tipografía Inter" abajo).
- `tests/test_memory_manager_projects.py` — 17 tests: esquema y CRUD de proyectos, no-regresión de
  las 5 funciones protegidas por CA-21, defensa pasiva contra huérfanos (INNER JOIN).

## Sin modificar (confirmado)

`tasks/task_manager.py`, `tasks/task_scheduler.py`, `ui/webview/confirmation_adapter.py`,
`ui/webview/frontend/js/{chat,composer,confirm_modal,window_chrome,theme}.js`,
`ui/webview/frontend/css/{composer,chat,layout,animations}.css` — tal como especifica §2 de la
arquitectura.

## Dependencias agregadas

**Ninguna.** `requirements.txt` no se tocó — confirmado contra §13 de la arquitectura (todo lo usado
ya está importado: `sqlite3`, `json`, `dataclasses`, `PyQt6.QtCore`). Inter (`.woff2`) es un asset
estático vendorizado en el repo, no una dependencia de `pip`.

## Tipografía Inter — cómo se obtuvo (§9 de la arquitectura)

Este entorno de `orion-dev` **sí tuvo acceso de red** al momento de implementar. Se siguió el
procedimiento de §9.1 al pie de la letra:

1. Descargado `https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip` (33.707.794
   bytes — coincide con el tamaño documentado en la arquitectura, 33.7 MB).
2. Extraído; localizados los 3 archivos por nombre exacto. El zip trae **dos** copias de cada
   peso (`extras/woff-hinted/` y `web/`) — se usó la carpeta `web/` (la que usa el propio sitio
   oficial `rsms.me/inter/inter.css`, la misma hoja de estilos que la arquitectura citó como fuente
   de los nombres de archivo verificados en §9.1).
3. Verificados como binarios WOFF2 reales antes de copiar (`file *.woff2` → "Web Open Font Format
   (Version 2), TrueType... version 4.66", no HTML de una página de error): `Inter-Regular.woff2`
   (111.268 bytes), `Inter-Medium.woff2` (114.348 bytes), `Inter-Bold.woff2` (114.840 bytes).
4. Copiados sin renombrar a `ui/webview/frontend/fonts/`, junto con `LICENSE.txt` del zip
   renombrado a `LICENSE-OFL.txt` (SIL OFL 1.1).

CA-26..CA-28 quedan cumplidos con archivos reales, no un placeholder — no aplicó el camino
alternativo de §9.1 (documentar como hallazgo y dejar el fallback de sistema intacto sin tocar
`font-family`), porque la descarga funcionó.

## Decisiones de implementación (ajustes menores respecto al texto literal de la arquitectura, con motivo)

1. **Se eliminó el bloque CSS `#sidebar-collapse-toggle`/`#sidebar-collapse-toggle:hover`
   preexistente en `sidebar.css`**, en vez de dejarlo intacto como sugiere la lectura literal de
   §8.1 (que solo agrega bloques nuevos). Motivo: el botón de colapso ahora vive dentro de la
   píldora con la clase `.pill-btn`, pero seguía teniendo también su `id="sidebar-collapse-toggle"`
   original. Por especificidad CSS, un selector de ID (`#sidebar-collapse-toggle`, especificidad
   100) gana sobre un selector de clase (`.pill-btn`, especificidad 10) en cualquier propiedad en
   conflicto — `width: 24px`/`height: 24px`/`border-radius: 6px`/`flex: none` del bloque viejo
   habrían pisado `flex: 1`/`height: 32px`/`border-radius: 999px` del bloque nuevo, dejando el botón
   de colapso visualmente distinto de los otros 2 controles de la píldora (rompiendo la unificación
   visual que exige CA-01 y el "hover/activo distinguible" de CA-02). Se retiró el bloque viejo; el
   comportamiento (`border:none`, `background:transparent`, hover con `--bg-hover`) lo sigue dando
   `.pill-btn`/`.pill-btn:hover`, sin pérdida de funcionalidad.
2. **`onProjectRemoved(...)` en `app.js` invoca una función real (`handleProjectRemoved`,
   exportada de `projects_panel.js`)**, no el comentario-placeholder que trae el snippet de §8.4 de
   la arquitectura (`/* si es el proyecto en vista detalle, projects_panel.js vuelve al maestro */`).
   Un comentario no es código ejecutable — se implementó la función descrita por ese comentario:
   si `_detailProjectId` coincide con el proyecto borrado, vuelve a la vista maestro y recarga
   `requestProjects()`. Mismo comportamiento que describe §0.4 de la arquitectura para la señal
   "targeted" `project_removed`.
3. **Vista de detalle de un proyecto sin conversaciones** (`renderProjectConversations([], id)`)
   muestra el mismo patrón `.panel-empty` ("Este proyecto no tiene conversaciones todavía.") que ya
   usan `renderTasks([])`/`renderProjects([])` — el snippet de §8.4 no cubre ese caso explícitamente
   (el loop `for (const conv of conversations)` sobre un array vacío simplemente no agrega nada), se
   agregó el estado vacío por consistencia de UX con el resto de los paneles nuevos, sin cambiar
   ningún contrato de datos.
4. **El picker de asignación (`openAssignPicker()`) cierra con click fuera del `.modal-box`**
   (mismo patrón que ya usan `renderShell()`/`renderMasterShell()`/`renderDetailShell()` para sus
   propios overlays) y muestra un `.panel-empty` si `getLoadedConversations()` está vacío — ninguno
   de los dos detalles está en el snippet literal de §8.4, agregados por consistencia con el resto
   del archivo.

Ningún ajuste cambia el esquema de datos, el contrato del bridge, ni el mecanismo de seguridad
aprobados en la arquitectura.

## Verificación local

- `python -m py_compile ai/memory_manager.py ui/webview/bridge.py core/security_manager.py main.py`
  — sin errores (CA-31).
- Los 5 archivos `.js` nuevos/modificados verificados con `node --check` (como módulo ES) — sin
  errores de sintaxis.
- `python -m pytest tests/ --tb=short -q` — **420 passed, 2 failed**. Los 2 fallos son
  `tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` y
  `test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto` (`ModuleNotFoundError: No module named
  'anthropic'`) — **idénticos a los 2 fallos pre-existentes documentados en `baseline-016.md`**, no
  atribuibles a REQ-016. Baseline reportó 365 passed/2 failed; la diferencia (420 vs 365 = +55
  tests) son los tests nuevos de este REQ (17 en `test_memory_manager_projects.py`, 17 nuevos en
  `test_webview_bridge.py`, 6 nuevos en `test_security_manager.py`, más los tests de
  `test_webview_safe_dom_insertion.py` que ahora corren también sobre los 2 archivos JS nuevos vía
  parametrización existente — sin escribir tests nuevos ahí, tal como especifica §14).

## Notas de seguridad (para el DoD de orion-qa, §11 de la arquitectura)

- `delete_task`/`delete_project` pasan siempre por `security_manager.require_confirmation()` antes
  de tocar `task_manager`/`memory` — verificado con test dedicado (cancelar → no se ejecuta;
  confirmar → sí se ejecuta), mismo flujo que `delete_conversation`.
- Ninguna query SQL nueva usa f-string/concatenación — todas parametrizadas (`?`).
- Los 2 archivos JS nuevos (`tasks_panel.js`, `projects_panel.js`) insertan todo texto no confiable
  (título de tarea, nombre de proyecto, título de conversación reutilizado en el picker)
  exclusivamente vía `textContent`/`setAttribute` — verificado por el grep estructural extendido de
  `tests/test_webview_safe_dom_insertion.py`.
- Sin API keys/tokens hardcodeados, sin `except: pass` silencioso, sin `print()` de debug en el
  código nuevo.

## Addendum — 2026-08-20 | orion-dev | 2 bugs cosméticos corregidos, hallados fuera del flujo del tracker

**Origen del hallazgo:** no proviene de `orion-tester` ni `orion-qa` (ambos ya cerraron REQ-016 con
veredicto PASS/APROBADO — ver `pruebas/test-results-016.md` y `pruebas/qa-audit-016.md`). El
orquestador levantó la app real (`ui.webview.main_window.MainWindow`, no offscreen) para
recorrerla con capturas de pantalla reales antes de pedirle a Johan su prueba manual final, y
encontró 2 bugs visuales menores. Johan pidió corregirlos ahora, antes de su prueba, en vez de
esperar a que los encuentre él. Por instrucción explícita del orquestador: **el Estado del tracker
se mantiene en `EN_QA`** — no se reabre la máquina de estados (no vuelve a `orion-tester`/
`orion-qa`) porque el cambio es CSS puro, sin tocar Python ni el contrato del bridge. CSV no
tocado.

### Fix 1 — `#attachment-chip` siempre visible pese al atributo `hidden`

**Archivo:** `ui/webview/frontend/css/composer.css` (bloque `#attachment-chip`, ahora línea 144).

**Bug:** el chip de archivo adjunto se veía siempre visible (vacío, sin nombre de archivo) aunque
`index.html` línea 97 lo declara con el atributo `hidden` por defecto. Causa: `#attachment-chip {
display: flex; ... }` es un selector de ID, que le gana en especificidad a la regla `[hidden] {
display: none }` del user-agent stylesheet.

**Es el mismo bug, exactamente, que ya se diagnosticó y corrigió para `#typing-indicator` en
REQ-015/CA-15** (ver `ui/webview/frontend/css/chat.css` líneas 176-193 y el addendum equivalente en
`desarrollo-log-015.md`). Mismo remedio aplicado acá: se agregó `#attachment-chip[hidden] {
display: none; }` a continuación del bloque `#attachment-chip` existente (que no se tocó), con un
selector ID+atributo de mayor especificidad real que restaura el comportamiento de `hidden`.

**Verificación:** por lectura de la cascada CSS (no hay entorno gráfico interactivo disponible en
esta sesión de `orion-dev` para una captura nueva) — especificidad de `#attachment-chip[hidden]`
(1 ID + 1 atributo) es estrictamente mayor que `#attachment-chip` (1 ID) y que `[hidden]` del
user-agent (1 atributo), así que la nueva regla gana en cualquier caso. Confirmado además que
`composer.js` (`showAttachment()` línea 92, listener de `attachment-chip-remove` línea 60-62) solo
manipula el atributo `hidden` del elemento, nunca su `display` inline — no hay conflicto adicional
de especificidad a considerar.

### Fix 2 — logo "NODDOO" recortado e ilegible en sidebar colapsado

**Archivo:** `ui/webview/frontend/css/sidebar.css` (bloque `#sidebar.collapsed`, ahora línea 36).

**Bug:** con `#sidebar.collapsed` (ancho 60px), el texto "NODDOO" de `#sidebar-logo`
(`font-size:13px; font-weight:700; letter-spacing:2px; white-space:nowrap; overflow:hidden`) se
recorta a mitad de un carácter y queda ilegible (captura real del orquestador: se ve algo parecido
a "NOI"). Contradice directamente el pedido original de Johan de que "la barra se vea más
profesional al contraerse" (REQ-016, ver petición verbatim en `REQ-016-context.md`).

**Fix aplicado:** `#sidebar.collapsed #sidebar-logo { display: none; }`, agregado como bloque
propio inmediatamente después del grupo de selectores que ya oculta `.label`/`#conversation-list`/
`#sidebar-footer`/`.sidebar-load-more` en `.collapsed` (línea ~21-26 original) — mismo criterio ya
establecido en ese archivo (ocultar por completo lo que no cabe/no tiene sentido a 60px), en vez de
sumarlo directamente a esa lista de selectores para no interrumpir con un comentario largo la
lectura de un selector list ya existente. Se descartó recortar el logo a una sola letra sin
overflow feo (alternativa más elaborada, no pedida por Johan): el toolbar en píldora con sus 3
iconos (CA-01/CA-22 de REQ-016) ya se ve bien colapsado sin el logo, y ocultarlo del todo es
consistente con el mismo criterio que ya aplica esta hoja de estilos para `.label`. No se agregó
ningún ícono de reemplazo — hubiera sido alcance no aprobado en `arquitectura-016.md`.

**Verificación:** por lectura de la cascada CSS — `#sidebar.collapsed #sidebar-logo` (2 IDs, uno
compuesto con clase) es una regla de contexto específico que no compite con ninguna otra regla de
`#sidebar-logo` fuera de `.collapsed` (el bloque base de `#sidebar-logo`, línea 34-41, sigue
aplicando sin cambios cuando el sidebar no está colapsado).

### Verificación local

- `python -m py_compile ai/memory_manager.py ui/webview/bridge.py core/security_manager.py
  main.py` — sin errores (cambio es 100% CSS, corrido de todos modos por consistencia con el resto
  del REQ).
- `python -m pytest tests/ --tb=short -q` — **420 passed, 2 failed**, idéntico al resultado ya
  documentado arriba (mismos 2 fallos pre-existentes de `test_llm_provider.py`,
  `ModuleNotFoundError: No module named 'anthropic'`). Cero fallos nuevos, cero tests afectados por
  este cambio (no existe ningún test que dependa de `getComputedStyle()` sobre `#attachment-chip` o
  `#sidebar-logo` hoy).

### Archivos modificados (addendum)

- `ui/webview/frontend/css/composer.css`
- `ui/webview/frontend/css/sidebar.css`

### Dependencias agregadas (addendum)

Ninguna.

### NO se ejecutó git commit.
