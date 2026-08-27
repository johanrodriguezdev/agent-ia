# Arquitectura REQ-020 — Reorganización visual de NODDOO en tres columnas

**Fecha:** 2026-08-25
**Agente:** orion-architect
**Estado:** ⏸️ ESPERANDO APROBACIÓN HUMANA — no se actualiza tracker/contexto ni se hace
handoff hasta recibir APROBADO / AJUSTAR / RECHAZADO.

## Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| CA-01 | `#app-body` pasa de 2 a 3 hijos flex (`#sidebar` + `#main-column` + `#side-panel` nuevo), todos en el mismo `display:flex` de `layout.css` — sin superposición porque cada uno usa `flex:none` (ancho fijo) o `flex:1` (chat), nunca `position:absolute`. |
| CA-02 | `#side-panel` con ancho fijo `300px` (`flex: none`), definido en `layout.css`. No se superpone: es un hijo flex más, no un overlay. Ver "Casos borde — ventana angosta" para la resolución con `main_window.py:69` (mínimo 1024×640). |
| CA-03 | Cero cambios a `#sidebar`/`sidebar.js`/`sidebar.css` — el nuevo `#side-panel` es hermano, no reemplaza ni envuelve al sidebar existente. |
| CA-04 | `#main-column`/`chat.js`/`composer.js` mantienen toda su función; el único ajuste (reubicación de `#chips-row`) mueve un nodo existente sin recrearlo ni desregistrar sus listeners (ver "Flujo de datos"). |
| CA-05 | `tasks_panel.js` monta su shell una única vez en `#tasks-panel-mount` (dentro de `#side-panel`) durante `bootstrap()`, no bajo demanda — visible desde que la app termina de cargar. |
| CA-06 | `mountTasksPanel()` (nueva, reemplaza `openTasksPanel()`) se llama directamente desde `app.js::bootstrap()`, y llama a `requestTasks()` en su propio cuerpo — no hay ningún listener de click en el camino. |
| CA-07 | `createTask`/`completeTask`/`requestDeleteTask` — mismas funciones de `bridge_client.js`, mismas firmas, sin tocar `buildTaskForm()`/`buildTaskItem()`. |
| CA-08 | `requestDeleteTask()` sigue dispatchando por el mismo camino (`confirmation_requested` → `showConfirmModal` sobre `#confirm-modal-root`, sin relación con `#panel-modal-root`/`#tasks-panel-mount`) — cero cambios. |
| CA-09 | Decisión explícita (ver más abajo): se **elimina** `#tasks-btn` del sidebar. Documentado como decisión de arquitectura, no ausencia de decisión. |
| CA-10 | `tasks_panel.js` sigue sin usar `innerHTML`/`insertAdjacentHTML` en ningún punto nuevo o modificado — mismo patrón `textContent`/`createElement` de hoy. |
| CA-11 | Orden fijo en el HTML: `#monitor-panel-section` (arriba) antes de `#tasks-panel-mount` (abajo) dentro de `#side-panel`, según ASUMIDO 1 ya aprobado. |
| CA-12 | El bloque de Monitor de sistema es marcado estático en `index.html`: cero `<script>`, cero import, cero llamada a `bridge_client.js`. |
| CA-13 | Texto placeholder explícito embebido en el HTML (ej. "Métricas del sistema — próximamente"), usando el patrón `.panel-empty` ya existente. |
| CA-14 | Reutiliza `.panel-empty` de `panels.css` tal cual (mismos tokens ya en uso) — cero clase/color nuevo para este bloque. |
| CA-15 | Ningún archivo de esta propuesta toca `theme.css`. |
| CA-16 | Ningún archivo de esta propuesta toca `theme.py`. |
| CA-17 | Todos los valores nuevos en CSS (300px, 1200px de breakpoint, etc.) son dimensiones/anchos, no colores — cero hex/rgb/hsl nuevo, todo color sigue viniendo de `var(--...)` ya existentes. |
| CA-18 | Ningún archivo tocado fija `data-theme` ni un tema por columna — `#side-panel` hereda tokens del `:root`/`[data-theme]` global igual que `#sidebar`/`#main-column` hoy. |
| CA-19 | `relocateChipsRow(isEmptyState)` (nueva, en `composer.js`) mueve el nodo `#chips-row` a un slot dentro de `#empty-state` cuando `isEmpty()` es verdadero — sin nuevo endpoint, reutilizando `onChipsLoaded`/`renderChips` tal cual. |
| CA-20 | La misma función devuelve `#chips-row` a su posición original dentro de `#composer` cuando `isEmpty()` es falso — `renderChips()` no cambia una sola línea, repinta el contenido del nodo esté donde esté. |
| CA-21 | `projects_panel.js`/`settings_panel.js` no cambian su ciclo de vida (`_panelOpen`, `open*Panel()`/`close*Panel()`, montaje sobre `#panel-modal-root`) — solo ajustes internos de clases/estructura para el lenguaje visual (a cargo de `orion-ui`). |
| CA-22 | Delegado a `orion-ui`: qué ajustes concretos de jerarquía (cabeceras/agrupación) se replican. Esta arquitectura deja el punto de enganche (mismas funciones `renderProjects`/`renderSecurityOverrides`/`buildProjectForm`, etc.) intacto para que `orion-ui` indique qué clases tocar sin reescribir lógica. |
| CA-23 | Cero cambios a imports de `bridge_client.js` ni a las funciones que `projects_panel.js`/`settings_panel.js` invocan — mismos slots, misma firma. |
| CA-24 | No se toca ningún archivo `.py` en esta propuesta — `py_compile` no aplica. |
| CA-25 | Ver "Pruebas sugeridas" — se ejecuta la suite completa además de los subsets `test_webview_*`. |
| CA-26 | El bloque de Monitor de sistema no contiene ningún número/gauge que simule CPU/RAM/red — solo texto de placeholder. |

## Módulos a modificar

- `ui/webview/frontend/index.html` — nueva estructura de columna derecha persistente
  (`#side-panel`), eliminación del botón `#tasks-btn`, nuevo slot `#empty-state-chips-slot`
  dentro de `#empty-state`.
- `ui/webview/frontend/css/layout.css` — `#app-body` pasa a 3 hijos; nueva regla de caja
  para `#side-panel` (ancho fijo, `display:flex; flex-direction:column`) + media query de
  colapso en ventana angosta.
- `ui/webview/frontend/css/panels.css` — adapta `.panel-list`/`.panel-header` para
  funcionar tanto en contexto modal (Proyectos/Configuración, sin cambios de compor-
  tamiento) como en contexto de panel fijo (Tareas, necesita `flex:1` + scroll propio en
  vez de `max-height` fija). Detalle de selectores exactos: `orion-ui`.
- `ui/webview/frontend/js/tasks_panel.js` — de "modal bajo demanda" a "montaje único en
  bootstrap"; se elimina `closeTasksPanel()`.
- `ui/webview/frontend/js/app.js` — cambia el import de `tasks_panel.js`, quita el
  listener de `#tasks-btn` (ya no existe el botón), llama `mountTasksPanel()` en
  `bootstrap()`.
- `ui/webview/frontend/js/chat.js` — `syncEmptyState()` gana una llamada a
  `relocateChipsRow(isEmpty())`.
- `ui/webview/frontend/js/composer.js` — nueva función exportada `relocateChipsRow()`.
- `ui/webview/frontend/js/projects_panel.js`, `ui/webview/frontend/js/settings_panel.js`
  — ajustes de clases/estructura interna (contenido exacto: `orion-ui`), sin tocar imports
  de `bridge_client.js` ni el ciclo `_panelOpen`/`open*Panel()`/`close*Panel()`.

**No se modifican (confirmado):** `ui/webview/bridge.py`, `ui/webview/theme.py`,
`ui/webview/frontend/css/theme.css`, `ui/webview/gui_state.py`, `ui/webview/main_window.py`,
`ui/webview/frontend/js/sidebar.js`, `core/`, `agents/`, `task_manager` (backend).

### Por qué `bridge.py` no necesita ningún cambio

El único comportamiento nuevo relacionado con el bridge es **cuándo** se llama
`requestTasks()` (antes: click; ahora: `bootstrap()`) y **dónde** aterriza el DOM que
pinta la respuesta (antes: overlay modal; ahora: contenedor fijo). Ninguna de las dos
cosas es un cambio de contrato: `request_tasks()`, `create_task()`, `complete_task()`,
`request_delete_task()` y la señal `tasks_loaded` se siguen invocando con exactamente la
misma firma, desde el mismo módulo (`tasks_panel.js`), sólo que antes bajo un guard de
click y ahora bajo un guard de "ya se montó una vez" (`_mounted`, ver abajo). `bridge.py`
no distingue ni necesita distinguir si quien lo llama es un modal o un panel persistente.

### Por qué `gui_state.py` no necesita ningún cambio

`gui_state.py` gestiona `GLOBAL_STATE` (IDLE/LISTENING/PROCESSING/RESPONDING) y
`WAKE_STATE` — ambos relacionados con el flujo de voz/conversación, sin ninguna relación
con la disposición de columnas del layout. El colapso de `#side-panel` en ventana angosta
es un estado 100% visual, resuelto con una media query de CSS que reacciona en vivo al
ancho de la ventana sin que ningún hilo Python necesite saberlo ni persistirlo.

## Nuevas clases/funciones

- `mountTasksPanel()` en `tasks_panel.js` — reemplaza a `openTasksPanel()`. Guard `_mounted`
  (booleano, reemplaza a `_panelOpen`) para evitar doble montaje si `bootstrap()` se
  llamara más de una vez (no ocurre hoy, pero es la misma defensa barata que ya existía).
  Construye el shell (cabecera con título, sin botón de cerrar, formulario, lista) una
  única vez dentro de `#tasks-panel-mount` y dispara `requestTasks()`.
- `relocateChipsRow(isEmptyState: boolean)` en `composer.js` — nueva función exportada.
  Mueve (no clona) el nodo `#chips-row` entre `#empty-state-chips-slot` (cuando
  `isEmptyState === true`) y su posición original dentro de `#composer`, antes de
  `#composer-input-row` (cuando es `false`). Como es el mismo nodo DOM, conserva sus
  listeners de click ya cableados por `renderChips()` — no hay que volver a registrar nada.
- **Eliminadas:** `openTasksPanel()`, `closeTasksPanel()` (ya no hay apertura/cierre que
  gestionar).

No hay clases ni funciones Python nuevas — este REQ es 100% frontend.

## Decisión explícita — botón `#tasks-btn` del sidebar (CA-09)

Se **elimina** el botón `#tasks-btn` de `index.html` (y su listener en `app.js`). Motivo:
su única función hoy es abrir el modal de Tareas; una vez que Tareas es un panel siempre
visible en la columna derecha, no hay ninguna acción que ese botón pueda disparar de forma
no redundante — el destino ya está a la vista permanentemente. Alternativas consideradas y
descartadas:
- **Re-etiquetar como "ir a/hacer foco en Tareas"**: solo tendría sentido si `#side-panel`
  pudiera estar colapsado y el usuario necesitara una forma de traerlo de vuelta. Se
  descartó porque el colapso propuesto (ver casos borde) es automático por ancho de
  ventana, sin un mecanismo de colapso manual — agregar un botón que solo sirve en el caso
  borde de ventana angosta es una pieza de UI para un escenario secundario, no justifica
  mantener el botón activo el 100% del tiempo en el caso normal.
- **Reemplazar por otra acción**: no hay ninguna acción nueva aprobada en la SPEC para ese
  espacio del sidebar.

Esta es la pieza de la propuesta que más cambia la UI visible hoy (un botón menos en el
sidebar) — se señala explícitamente en el resumen para el humano más abajo, aunque la
SPEC ya delegó la decisión final a `orion-architect`.

## Flujo de datos

1. **Bootstrap de Tareas** — `app.js::bootstrap()` registra `onTasksLoaded(...)` (sin
   cambios) y luego llama `mountTasksPanel()` (nuevo, en el punto exacto donde antes se
   cableaba el listener de `#tasks-btn`). `mountTasksPanel()` construye el DOM fijo dentro
   de `#tasks-panel-mount` y llama `requestTasks()` en el mismo tick. Python responde de
   forma asíncrona (como siempre) con la señal `tasks_loaded(json)`; `onTasksLoaded` invoca
   `renderTasks(JSON.parse(json))`, que sigue pintando `#tasks-panel-list` exactamente
   igual que hoy (incluyendo el `replaceChildren()` que ya evita duplicados).
2. **CRUD de tareas** — sin cambios: `buildTaskForm()`/`buildTaskItem()` llaman a
   `createTask`/`completeTask`/`requestDeleteTask` de `bridge_client.js`, mismas firmas. El
   borrado sigue dependiendo de `confirmation_requested` → `showConfirmModal` sobre
   `#confirm-modal-root`, un árbol de DOM totalmente independiente de `#tasks-panel-mount`.
3. **Chips del estado vacío** — `chat.js::syncEmptyState()` (invocado desde `initChat()`,
   `renderTurns()`, `appendMessage()`, `clearMessages()`, sin nuevos call-sites) ahora
   también llama `relocateChipsRow(isEmpty())` (importado de `composer.js`). Esta función
   mueve el nodo `#chips-row` al slot `#empty-state-chips-slot` o de vuelta a `#composer`
   según corresponda. La señal `onChipsLoaded` y la función `renderChips()` no cambian: 
   siguen repintando el contenido de `#chips-row` sin que les importe en qué contenedor
   está montado en ese momento.
4. **Monitor de sistema** — sin flujo de datos: bloque estático servido con el resto de
   `index.html`, sin JS ni bridge asociado.
5. **Proyectos/Configuración** — sin cambios de flujo: `requestProjects()`/
   `requestSecurityOverrides()` se siguen disparando de forma perezosa al hacer click en
   `#projects-btn`/`#settings-btn` (ambos botones se mantienen en el sidebar, sin cambios).
6. **Colapso de `#side-panel` en ventana angosta** — resuelto 100% en `layout.css` vía
   media query; no hay flujo de datos, no hay evento, no hay estado que sincronizar entre
   JS y Python.

## Estructura DOM nueva (`index.html`)

Dentro de `#app-body`, como tercer hijo flex después de `#sidebar` y `#main-column`:

```
<aside id="side-panel">
  <section id="monitor-panel-section">
    <div class="panel-header"><div class="panel-section-title">Monitor de sistema</div></div>
    <div class="panel-empty">Métricas del sistema — próximamente</div>
  </section>
  <section id="tasks-panel-mount"></section>
</aside>
```

- `#monitor-panel-section` es 100% estático, incluido tal cual en `index.html` (no lo
  genera ningún `.js`).
- `#tasks-panel-mount` arranca vacío en el HTML; `mountTasksPanel()` lo puebla en
  `bootstrap()` (cabecera + formulario + `#tasks-panel-list`).
- El nombre exacto de la clase de título (`panel-section-title` arriba es solo indicativo)
  y cualquier clase adicional de agrupación/spacing quedan a definición de `orion-ui` — no
  se fija aquí para no invadir su alcance.

Dentro de `#empty-state` (nuevo hijo, después de `#empty-state-subtitle`):

```
<div id="empty-state-chips-slot"></div>
```

Vacío en el HTML; `relocateChipsRow(true)` lo puebla moviendo `#chips-row` ahí cuando el
chat está vacío.

**Eliminado de `index.html`:** el `<button id="tasks-btn">` completo (icono + label) del
sidebar.

## Ancho fijo y colapso de `#side-panel` (CA-02 y caso borde de ventana angosta)

- Ancho fijo: **300px** (`flex: none`), mismo criterio de caja que `#sidebar` (`flex: none`
  + ancho literal en el CSS de layout, sin variable en `theme.css`, ver CA-15/17). Un poco
  más ancho que el sidebar (260px) porque aloja dos secciones con formulario + lista, no
  solo íconos y texto corto.
- Colapso: `@media (max-width: 1199px) { #side-panel { display: none; } }` en `layout.css`.
  Verificado contra `main_window.py:69` (`setMinimumSize(1024, 640)`): en el ancho mínimo
  soportado (1024px), `#side-panel` ya está oculto por la media query, y `#main-column`
  (que ya tiene `flex:1; min-width:0`) recupera automáticamente todo el espacio liberado —
  sin necesidad de ningún JS ni de un `min-width` adicional en `#main-column`. Por encima
  de 1200px, el peor caso realista (sidebar expandido a 260px + `#side-panel` a 300px dentro
  de una ventana de exactamente 1200px) deja 640px para el chat, cómodo. No hay estado
  intermedio "colapsado a ícono" para `#side-panel` (a diferencia de `#sidebar`) — es
  mostrado completo o completamente oculto, porque no tiene una representación útil
  reducida a solo íconos (a diferencia de los 3 botones de acción del sidebar).
- Esto responde directamente el caso borde de SPEC-020 ("no puede dejar el chat
  inutilizable"): por diseño, el ancho de ventana en el que `#side-panel` se oculta es
  menor que aquel en el que empezaría a apretar al chat.

## Ajuste a `panels.css` — panel fijo vs. panel en modal

`.panel-list` hoy tiene `max-height: 320px` (pensado para caber dentro de un
`.modal-box-wide` de altura acotada). Dentro de `#tasks-panel-mount`, la lista debe ocupar
el espacio vertical restante de `#side-panel` (bajo el bloque de Monitor de sistema) con
scroll propio, sin un tope fijo en píxeles — mismo criterio que ya pide el caso borde de la
SPEC ("necesita scroll propio... sin empujar ni recortar el panel de Monitor"). Esto
requiere que `.panel-list` tenga dos variantes de alto según el contexto (fijo → `flex: 1;
min-height: 0; overflow-y: auto`; modal → se mantiene el `max-height: 320px` actual para no
romper Proyectos/Configuración). La forma exacta de distinguir ambos contextos (selector
por ancestro `#tasks-panel-mount .panel-list`, o una clase modificadora nueva tipo
`.panel-list--flex`) y cualquier otro ajuste de spacing/cabecera queda a criterio de
`orion-ui` — esta arquitectura solo fija que la distinción es necesaria y por qué.

De la misma forma, `.panel-header` en contexto de panel fijo no lleva `.panel-close-btn`
(no hay nada que cerrar); en contexto modal sigue llevándolo. Ningún cambio de token o
color en ningún caso — solo estructura/flex.

## Dependencias nuevas

Ninguna. No se toca `requirements.txt` (cero cambios Python) ni se agrega ninguna
dependencia de frontend (no hay gestor de paquetes JS en este proyecto — los módulos son
ES modules servidos tal cual).

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| Mover `#chips-row` en vivo entre dos contenedores podría verse afectado por CSS anidado que dependa de su padre exacto. | Verificado en el código real: `#chips-row`, `.chip`, `.chip-risk-*` en `composer.css` son todos selectores por ID/clase propios, ninguno anidado bajo `#composer` — moverlo de padre no cambia qué reglas aplican. |
| `#chips-row` centrado en `#composer` (alineado a la izquierda, `justify-content` por defecto) puede no verse bien centrado dentro de `#empty-state` (que sí centra su contenido). | Ajuste de `justify-content`/spacing puntual para el contexto de `#empty-state-chips-slot` — detalle visual, a cargo de `orion-ui`, no bloquea la arquitectura. |
| Eliminar `#tasks-btn` es un cambio de UI visible (un botón menos) más allá de "reorganizar", podría no ser lo que el humano visualizaba. | Señalado explícitamente en el resumen de aprobación — si el humano prefiere otra opción (re-etiquetar, ocultar solo si `#side-panel` está colapsado), se ajusta antes de tocar código. |
| `.panel-list` con dos variantes de alto (fija vs. modal) si no se separa bien podría romper el `max-height` de Proyectos/Configuración. | La regla actual de `.panel-list` no se modifica in-place; se añade una regla más específica solo para el contexto de `#tasks-panel-mount`, que gana por especificidad de selector sin tocar el comportamiento base usado por Proyectos/Configuración. `orion-tester` debe verificar visualmente (o con test de regresión existente) que el modal de Proyectos conserva su `max-height`. |
| Breakpoint de 1200px es una elección de esta arquitectura, no un valor pedido explícitamente por el humano. | Documentado con el cálculo que lo respalda (peor caso a 1200px deja 640px de chat). Es ajustable sin tocar tokens ni arquitectura si `orion-ui`/QA lo consideran necesario — se documentaría como decisión de `orion-dev` en `desarrollo-log-020.md` si cambia. |
| Cambio de comportamiento de carga de Tareas (perezosa → bootstrap) aumenta el trabajo en el arranque de la app. | Ya identificado y aceptado explícitamente en `REQ-020-context.md`/SPEC-020 como reversión intencional del criterio de SPEC-016 — no es una regresión no documentada. |

## Pruebas sugeridas

- CA-01/CA-02/CA-03/CA-04: test de estructura DOM (inspección de `#app-body` con 3 hijos
  flex, anchos computados de `#sidebar`/`#side-panel`, `#main-column` con `flex:1`) —
  extensión de los tests `test_webview_*` existentes o uno nuevo dedicado al layout de 3
  columnas.
- CA-05/CA-06: test que verifique que `#tasks-panel-mount` tiene contenido inmediatamente
  después de `bootstrap()` sin simular ningún click, y que `request_tasks` se invocó (mock
  del bridge) sin que medie un evento de click.
- CA-07/CA-08: reutilizar/adaptar los tests existentes de creación/completado/borrado de
  tareas, apuntando al nuevo contenedor en vez de `#panel-modal-root`.
- CA-09: test que confirme que `#tasks-btn` no existe en el DOM (`document.getElementById`
  devuelve `null`).
- CA-10: `tests/test_webview_safe_dom_insertion.py` ya cubre `tasks_panel.js` por nombre
  explícito — solo hay que confirmar que sigue en verde tras el cambio, sin tocar el test.
- CA-11/CA-12/CA-13/CA-14: test que localice `#monitor-panel-section`, confirme el texto de
  placeholder, y confirme ausencia de cualquier llamada a `bridge_client.js` en ese bloque
  (revisión de código, no hay mock que llamar porque no hay llamada).
- CA-15/CA-16: `tests/test_webview_theme.py` sin modificar, ejecutado como no-regresión.
- CA-17: revisión de diff por `orion-qa` (no hay test automático dedicado, según la propia
  SPEC).
- CA-18: prueba manual de cambio de tema con `#side-panel` visible en ambos modos.
- CA-19/CA-20: test que verifique la posición de `#chips-row` (su `parentElement`) antes y
  después de simular `isEmpty()` true/false, y que `renderChips()` sigue funcionando en
  ambas ubicaciones.
- CA-21/CA-23: tests existentes de Proyectos/Configuración (apertura/cierre de modal,
  slots del bridge) sin cambios de expectativa.
- CA-22: verificación manual/QA de que los ajustes de `orion-ui` para Tareas se reflejaron
  también en Proyectos/Configuración donde aplica.
- CA-24/CA-25/CA-26: `python -m py_compile` (no debería tocar ningún `.py`), suite completa
  de `pytest`, y revisión de que ningún archivo JS/HTML nuevo contiene un valor que
  simule CPU/RAM/red.
- No-regresión general: correr el subset `test_webview_*` completo (194 tests hoy) más
  `test_webview_safe_dom_insertion.py`/`test_webview_theme.py` (30 tests), igual que hizo
  `orion-baseline`, para comparar contra el baseline 194/30 en verde.
