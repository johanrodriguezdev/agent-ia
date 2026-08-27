# Desarrollo REQ-020 — Reorganización visual de NODDOO en tres columnas

**Fecha:** 2026-08-25
**Agente:** orion-dev
**Fuente:** `arquitectura-020.md` (aprobada) + `ui-design-020.md` (detalle visual, cero
tokens nuevos) — implementado tal cual, sin desviaciones de alcance.

## Archivos modificados

- `ui/webview/frontend/index.html`
  - Nueva columna `<aside id="side-panel">` (300px) como tercer hijo de `#app-body`, con
    `#monitor-panel-section` (placeholder estático) apilado sobre `#tasks-panel-mount`
    (vacío en el HTML, poblado por `mountTasksPanel()`).
  - Eliminado `<button id="tasks-btn">` completo del sidebar (icono + label) — CA-09.
  - Agregado `<div id="empty-state-chips-slot"></div>` dentro de `#empty-state`, después
    de `#empty-state-subtitle`.
- `ui/webview/frontend/css/layout.css`
  - Nueva regla `#side-panel` (300px, `flex:none`, `bg-secondary`, `border-left`,
    `min-height:0`) + `@media (max-width: 1199px) { #side-panel { display:none } }`.
- `ui/webview/frontend/css/panels.css`
  - Box model de `#monitor-panel-section` (flex:none, padding 16px, border-bottom) y
    `#tasks-panel-mount` (flex:1, min-height:0, column) + regla para que `.panel-header`/
    `.panel-form` de Tareas nunca se compriman.
  - Clases nuevas: `.panel-section-title`, `.panel-header-title-group`, `.panel-list-flex`.
  - Corrección de foco: `.panel-form input:focus, .panel-form select:focus`.
- `ui/webview/frontend/css/settings_panel.css`
  - Corrección de foco: `.settings-row-select:focus`.
- `ui/webview/frontend/css/composer.css`
  - `#chips-row:empty { display: none; }`.
- `ui/webview/frontend/css/chat.css`
  - `#empty-state-chips-slot #chips-row` (margin-bottom:0, `justify-content:center`).
- `ui/webview/frontend/js/tasks_panel.js`
  - Reescrito de modal bajo demanda (`openTasksPanel`/`closeTasksPanel`, guard
    `_panelOpen`, montaje sobre `#panel-modal-root` con overlay/`.modal-box-wide`) a panel
    persistente (`mountTasksPanel()`, guard `_mounted`, montaje directo en
    `#tasks-panel-mount`, sin overlay ni botón de cerrar).
  - Cabecera nueva: `.panel-header-title-group` (ícono 📋 migrado desde el `#tasks-btn`
    eliminado + `.panel-section-title` "Tareas"), sin `.panel-close-btn`.
  - Lista con `class="panel-list panel-list-flex"` (antes solo `"panel-list"`).
  - `buildTaskForm()`/`renderTasks()`/`buildTaskItem()`: sin cambios.
- `ui/webview/frontend/js/app.js`
  - Import cambia de `openTasksPanel` a `mountTasksPanel`.
  - Eliminado el listener `#tasks-btn` → `openTasksPanel` (el botón ya no existe en el DOM).
  - `onTasksLoaded(...)` se registra y luego se llama `mountTasksPanel()` en el mismo punto
    donde antes se cableaba el listener — sin ningún click de por medio (CA-06).
- `ui/webview/frontend/js/composer.js`
  - Nueva función exportada `relocateChipsRow(isEmptyState)` — mueve (no clona)
    `#chips-row` entre `#empty-state-chips-slot` y su posición original en `#composer`
    (antes de `#composer-input-row`).
- `ui/webview/frontend/js/chat.js`
  - Import de `relocateChipsRow` desde `composer.js`.
  - `syncEmptyState()` ahora llama `relocateChipsRow(empty)` además de alternar el
    `display` de `#empty-state`.
- `ui/webview/frontend/js/projects_panel.js`
  - `renderMasterShell()`: cabecera gana `.panel-header-title-group` (ícono 📁 + el
    `.modal-title` "Proyectos" existente), como primer hijo de `.panel-header`;
    `.panel-close-btn` sigue como segundo hijo, sin cambios en sí mismo.
  - `renderDetailShell()`: **sin cambios** — sigue siendo `backBtn` + `title` (nombre del
    proyecto) + `closeBtn`, sin ícono ni grupo (decisión explícita de `ui-design-020.md`:
    el título ahí es un dato del usuario, no la categoría "Proyectos").
- `ui/webview/frontend/js/settings_panel.js`
  - `renderShell()`: mismo patrón que Proyectos — `.panel-header-title-group` con ícono ⚙
    + `.modal-title` "Configuración", `.panel-close-btn` sin cambios.

**No se tocó** (confirmado, cero referencias fuera de comentarios): `ui/webview/bridge.py`,
`ui/webview/theme.py`, `ui/webview/frontend/css/theme.css`, `ui/webview/gui_state.py`,
`ui/webview/main_window.py`, `ui/webview/frontend/js/sidebar.js`.

## Dependencias agregadas

Ninguna. `requirements.txt` sin cambios (cero Python nuevo, cero gestor de paquetes JS en
el proyecto).

## Decisiones de implementación

- **CA-09 (destino final de `#tasks-btn`):** eliminado por completo, tal como definió
  `orion-architect`. Su glyph (`📋`) migra visualmente a la cabecera del panel de Tareas
  vía `.panel-header-title-group` — no queda ningún control "muerto" en el sidebar ni en
  el tab order.
- **CA-22 (qué se replicó en Proyectos/Configuración y qué no):**
  - Replicado: composición de cabecera "ícono + título" (`.panel-header-title-group`),
    igual criterio en las 3 pantallas (Tareas fija, Proyectos y Configuración modales).
  - Replicado también en Configuración: corrección de foco visible, aunque
    `settings_panel.css` es un archivo separado de `panels.css` — se agregó la misma regla
    (`outline:none; border-color:var(--text-accent)`) sobre `.settings-row-select`
    específicamente, porque `<select>` de Configuración no comparte clase con
    `.panel-form select`.
  - NO replicado (documentado explícitamente en `ui-design-020.md`, no es un olvido):
    agrupación por estado (Pendientes/Completadas) — no se introdujo en ningún panel;
    estilizar `.panel-close-btn` hover/focus — carencia preexistente fuera de alcance.
- **Orden de registro en `bootstrap()` (`app.js`):** `onTasksLoaded(...)` se registra
  inmediatamente antes de `mountTasksPanel()` (que dispara `requestTasks()` en su propio
  cuerpo) para no perder la señal `tasks_loaded` si Python respondiera de forma
  extremadamente rápida — mismo patrón de precaución que ya usa el resto de `bootstrap()`
  con `request_initial_state()`.
- Sin desviaciones de alcance respecto a `arquitectura-020.md`/`ui-design-020.md`: todo lo
  implementado corresponde 1:1 a un punto explícito de alguno de los dos documentos.

## Verificación local

```
python -m py_compile main.py                                    → OK (sin errores)
python -m pytest tests/test_webview_safe_dom_insertion.py \
                 tests/test_webview_theme.py --tb=short -q      → 30 passed
python -m pytest tests/ -k "webview" --tb=short -q              → 194 passed, 346 deselected
python -m pytest tests/ --tb=short -q                            → 2 failed, 538 passed
```

Los 2 fallos son exactamente los mismos preexistentes documentados en `baseline-020.md`
(`tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` y
`test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto`, ambos por
`ModuleNotFoundError: No module named 'anthropic'`) — ningún fallo nuevo, ningún archivo de
`ui/webview/` involucrado. Conteo idéntico al baseline: 538 passed / 2 failed, y el subset
`test_webview_*` en 194/194 (igual que antes del cambio).

No hay tests dedicados a REQ-020 todavía (los criterios CA-01..CA-26 de `SPEC-020.md`
quedan para `orion-tester`) — esta verificación local solo confirma no-regresión sobre lo
existente.

## Pendiente para orion-tester

Ver "Pruebas sugeridas" de `arquitectura-020.md` y "Riesgos de regresión visual" de
`ui-design-020.md` para el detalle de qué verificar por criterio, en particular:
- `getComputedStyle(...).maxHeight === "none"` para `.panel-list-flex` dentro de
  `#tasks-panel-mount`.
- Cadena `min-height:0` (`#side-panel` → `#tasks-panel-mount` → `.panel-list-flex`) con una
  lista larga de tareas, sin que el scroll empuje `#monitor-panel-section`.
- `document.getElementById("tasks-btn") === null`.
- Posición de `#chips-row` (`parentElement`) antes/después de simular `isEmpty()`.
