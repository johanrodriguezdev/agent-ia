# Baseline REQ-020 — Reorganización visual de NODDOO en tres columnas

**Fecha:** 2026-08-25
**Agente:** orion-baseline
**Rama git:** `feature/REQ-015-webview-ui` (sin rama propia para REQ-020 — se sigue trabajando
sobre la misma rama de la base webview, mismo criterio que REQ-016/018/019)

## Estado actual del sistema

### Layout de la ventana principal (`index.html` + `layout.css`)
Hoy `#app-body` es un flex container con **2 zonas**:
- `#sidebar` (`sidebar.css`): 260px fijo, colapsable a 60px con transición de 200ms
  (`#sidebar.collapsed`). Contiene header/logo, toolbar en píldora (colapsar/buscar/nuevo
  chat), 3 botones de acción (`#tasks-btn`, `#projects-btn`, `#settings-btn`), lista de
  conversaciones (`#conversation-list`), botón "Ver más" y footer con toggle de tema.
- `#main-column` (`flex:1; min-width:0`): columna única que contiene `#chat-area`
  (`#empty-state` + `#messages` + `#typing-indicator`) y `#composer` (chips-row, input row,
  chip de adjunto).

No existe ninguna tercera columna. No existe ningún nodo `#monitor-panel` ni equivalente en
el DOM. El único CSS de layout de alto nivel vive en `layout.css` (`#app-shell` → `#app-body`
→ `#sidebar` + `#main-column`).

### Panel de Tareas (`tasks_panel.js`) — hoy modal
- `openTasksPanel()` es un guard (`_panelOpen`) invocado por click en `#tasks-btn`
  (listener cableado en `app.js:111`). Monta el modal completo (overlay + `.modal-box-wide`
  + header con botón cerrar + formulario + lista) sobre `#panel-modal-root` en cada apertura,
  y llama `requestTasks()` **recién ahí** — carga perezosa (comentario explícito en el código:
  "CA-12: carga perezosa, solo acá", criterio fijado por SPEC-016).
- `closeTasksPanel()` vacía `#panel-modal-root` y resetea el guard.
- `renderTasks(tasks)` hace `replaceChildren()` antes de repintar — no hay riesgo de
  duplicación por doble carga en el estado actual.
- Acciones: completar (`completeTask`), eliminar (`requestDeleteTask` → dispara confirmación
  Amarillo, ver `confirm_modal.js`), crear (formulario con título obligatorio, fecha,
  prioridad, descripción opcional).
- Todo el texto no confiable (título de tarea, fecha) se inserta con `textContent`, nunca
  `innerHTML` — cubierto por `tests/test_webview_safe_dom_insertion.py`.

### Proyectos (`projects_panel.js`) y Configuración (`settings_panel.js`) — hoy modales
- Mismo patrón que Tareas: guard `_panelOpen`, `open*Panel()` monta sobre
  `#panel-modal-root`, carga perezosa del bridge (`requestProjects()` /
  `requestSecurityOverrides()`), `close*Panel()` limpia el root.
- `projects_panel.js` tiene además vista maestro/detalle (`_detailProjectId`).
- `settings_panel.js` tiene navegación lateral por secciones (v1: solo "Seguridad" poblada),
  con `<select>` por fila que aplica al elegir (sin botón "Guardar" separado).
- Ambos comparten `panels.css` (`.panel-header`, `.panel-form`, `.panel-list`, `.panel-item`,
  `.panel-empty`, etc.) y `modal.css` (`.modal-overlay`, `.modal-box`, `.modal-box-wide`).

### Estado vacío del chat (`#empty-state`) y chips
- `#empty-state` vive dentro de `#chat-area` (avatar + saludo dinámico por hora + subtítulo
  fijo). `chat.js` alterna su visibilidad (`display: flex|none`) según `isEmpty()`.
- `#chips-row` vive dentro de `#composer` (fuera de `#chat-area`), poblado por
  `renderChips()` en `composer.js` a partir de la señal `onChipsLoaded` (JSON del bridge).
  Hoy los chips son visibles siempre que el composer está visible, independientemente de si
  el chat está vacío o no — no están anclados al estado vacío.

### Identidad visual / tokens
- Única fuente de estilos de color: `ui/webview/frontend/css/theme.css` (variables) +
  `ui/webview/theme.py` (Python, generador/espejo). `tests/test_webview_theme.py` (30 tests,
  todos pasando) es el test de drift entre ambas fuentes — no se toca en este REQ.
- `panels.css` ya expone un patrón `.panel-empty` (texto centrado, `var(--text-secondary)`)
  reutilizable tal cual para el placeholder de "Monitor de sistema" sin CSS nuevo.

### Ventana / tamaño mínimo
- `ui/webview/main_window.py:69` — `self.setMinimumSize(1024, 640)`. Es la referencia
  concreta que `orion-architect` necesita para decidir el punto de colapso de la nueva
  columna derecha (CA-02 / caso borde de ventana angosta).

## Archivos que serán modificados (previsión)

Basado en la sección "Módulos afectados" de SPEC-020, confirmado contra el código real:

- `ui/webview/frontend/index.html` — agregar contenedor de columna derecha persistente
  (monitor + tareas) dentro de `#app-body`; migrar el markup de Tareas fuera de
  `#panel-modal-root` (mount point nuevo, dejar de depender de `openTasksPanel()` para
  construir el DOM).
- `ui/webview/frontend/css/layout.css` — pasar `#app-body` de 2 a 3 hijos flex; nueva regla
  para la columna derecha (ancho fijo, mismo criterio que `#sidebar` en `sidebar.css`).
- `ui/webview/frontend/css/panels.css` — clases nuevas o adaptadas para "panel fijo" vs.
  "panel en modal" sin romper Proyectos/Configuración; placeholder de Monitor reutilizando
  `.panel-empty`.
- `ui/webview/frontend/js/tasks_panel.js` — de "montar bajo demanda + guard `_panelOpen`" a
  "montar una vez en bootstrap"; quitar `closeTasksPanel()` o dejarlo sin uso según decida
  `orion-architect`; mover `requestTasks()` fuera del click handler.
- `ui/webview/frontend/js/app.js` — quitar/redefinir el listener `tasks-btn` → `openTasksPanel`
  (línea 111 actual); llamar a la función de carga de tareas en `bootstrap()`.
- `ui/webview/frontend/js/sidebar.js` o `index.html` — decisión sobre el botón `#tasks-btn`
  (eliminar / re-etiquetar / nueva función) — hoy es un `<button>` simple sin lógica propia
  en `sidebar.js` (el listener vive en `app.js`).
- `ui/webview/frontend/js/projects_panel.js`, `ui/webview/frontend/js/settings_panel.js` —
  ajustes de clases/estructura interna para alinear lenguaje visual (cabeceras/agrupación),
  sin tocar su naturaleza modal ni imports del bridge.
- `ui/webview/frontend/js/chat.js` y/o `ui/webview/frontend/js/composer.js` — posible
  movimiento/duplicación de `chips-row` hacia `#empty-state` (hoy `chips-row` es propiedad de
  `composer.js`, `#empty-state` es propiedad de `chat.js` — el acoplamiento entre ambos
  módulos es nuevo, a diseñar por `orion-architect`).
- Posible archivo nuevo: un módulo JS para el panel "Monitor de sistema" (no existe hoy
  ningún archivo `monitor_panel.js` ni equivalente). **Importante para `orion-architect`**:
  si se crea un archivo `.js` nuevo, cae automáticamente bajo
  `tests/test_webview_safe_dom_insertion.py::test_ningun_otro_archivo_js_del_frontend_usa_innerhtml`
  (hace `glob("*.js")` sobre todo `frontend/js/`, excepto `chat.js`) — no necesita
  agregarse a ninguna lista, pero si inserta cualquier texto debe hacerlo con `textContent`,
  nunca `innerHTML`/`insertAdjacentHTML`, o ese test existente lo va a romper.
- **No se tocan** (confirmado, cero referencias a modificarlos en SPEC-020 y `py_compile`
  limpio hoy): `ui/webview/bridge.py`, `ui/webview/theme.py`,
  `ui/webview/frontend/css/theme.css`, `core/`, `agents/`, `task_manager` (backend).

## Fallos pre-existentes (no atribuibles a este REQ)

Suite completa ejecutada (`python -m pytest tests/ --tb=short`, 540 tests recolectados):

```
2 failed, 538 passed, 11 warnings
FAILED tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse
FAILED tests/test_llm_provider.py::test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto
```

Causa raíz de ambos: `ModuleNotFoundError: No module named 'anthropic'` — falta el paquete
`anthropic` en el entorno Python local (`pip`), no un fallo de lógica. **No tiene ninguna
relación con REQ-020** (categoría UI, frontend puro) ni con el árbol `ui/webview/`.

Subset específico de la zona que este REQ va a tocar, ejecutado aparte para aislar la señal:

```
tests/test_webview_*.py → 194 passed, 346 deselected (0 fallos)
tests/test_webview_safe_dom_insertion.py + tests/test_webview_theme.py → 30 passed
```

`python -m py_compile ui/webview/bridge.py ui/webview/theme.py ui/webview/main_window.py`
→ sin errores (exit 0). No hay ningún fallo de compilación ni de test en el árbol
`ui/webview/` antes de tocar nada.

### Nota sobre el working tree — otros REQs sin commitear en la misma rama
Esta rama (`feature/REQ-015-webview-ui`) tiene evidencia de trabajo en curso de REQ-007
(EN_QA), REQ-012 (EN_PRUEBAS), REQ-013 (EN_QA), REQ-014 (EN_QA), REQ-016 (EN_QA), REQ-017
(EN_QA), REQ-018 (EN_PRUEBAS) y REQ-019 (EN_QA) — ninguno commiteado según
`requerimientos.csv`. `git status` al momento de este baseline muestra como únicos cambios
sin commitear: `requerimientos.csv`, `.claude/agents/orion-architect.md`,
`.claude/agents/orion-coordinador.md`, `.claude/commands/nuevo-req.md`,
`.claude/rules/definition-of-done.md`, `CLAUDE.md`, contextos de REQ-018/REQ-019, y
`.claude/agents/orion-ui.md` (nuevo, agente aún no usado) — **ningún archivo bajo
`ui/webview/` aparece modificado en el working tree**, así que el código de
`ui/webview/frontend/` leído para este baseline es exactamente el que ya está commiteado
(commit `9f4235f`), no hay trabajo a medias de otro REQ superpuesto en esos archivos
específicos. Si en una sesión futura `git status` muestra cambios en `ui/webview/` que no
correspondan a REQ-020, hay que revisar de qué REQ son antes de asumir que son fallos de
este trabajo.

## Comportamiento actual documentado — resumen para orion-architect

| Elemento | Hoy |
|---|---|
| Zonas del layout | 2 (`#sidebar` + `#main-column`) |
| Tareas | Modal, carga perezosa al click, guard `_panelOpen` |
| Proyectos / Configuración | Modales, carga perezosa, maestro/detalle (Proyectos) y secciones (Configuración) |
| Monitor de sistema | No existe |
| Chips de acciones | En `#composer`, siempre visibles junto al input, no ligados a `#empty-state` |
| `#tasks-btn` | Único punto que abre/cierra el modal de Tareas (listener en `app.js:111`) |
| Ventana mínima | 1024×640 (`main_window.py:69`) |
| Tokens de color | `theme.css` + `theme.py`, sin drift (`test_webview_theme.py` en verde) |
