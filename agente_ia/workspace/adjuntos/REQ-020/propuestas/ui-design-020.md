# Diseño UI REQ-020 — Reorganización visual de NODDOO en tres columnas

**Fecha:** 2026-08-25
**Agente:** orion-ui
**Estado:** Detalle visual sobre arquitectura ya APROBADA (`arquitectura-020.md`) — ajuste de
layout, no rediseño. No requiere una nueva aprobación humana del diseño en sí (ver
`.claude/agents/orion-ui.md`, "No hace"); se procede directo a handoff salvo los puntos
señalados en "Fuera de alcance visual" que si el humano quiere ampliar, son decisión suya.

Esta propuesta **no contradice ni reabre** ninguna decisión de `arquitectura-020.md` — toma
como fijos: la estructura de 3 columnas flex, `#side-panel` de 300px con
`#monitor-panel-section` arriba + `#tasks-panel-mount` abajo, el colapso por media query a
`max-width:1199px`, la eliminación de `#tasks-btn`, `mountTasksPanel()`/`relocateChipsRow()`,
y que Proyectos/Configuración siguen siendo modales. Todo lo de acá abajo es **cómo se ve y
se comporta** ese esqueleto, con nombres de clase exactos para que `orion-dev` implemente sin
ambigüedad.

## Referencia analizada

La referencia "JARVIS-OS" (descripción textual en
`workspace/adjuntos/REQ-020/origen/referencia-visual-jarvis-os.md`, sin archivo de imagen)
mostraba: barra superior con clúster de estado del sistema en vivo; layout de 3 columnas
persistentes (Monitor de sistema con métricas/barras de progreso/mini-sparklines a la
izquierda, chat al centro, Tareas/Registros + Memoria/Conocimiento a la derecha); estética de
tema claro con acento cian, bordes finos, decoración tipo HUD (esquinas bracket), tipografía
técnica y badges/pills redondeados.

`orion-spec`/`orion-architect` ya acotaron el alcance real (ver SPEC-020 y
`arquitectura-020.md`): de toda esa referencia, este REQ solo toma la **idea estructural** de
tener información persistente junto al chat (Tareas + un espacio reservado para Monitor de
sistema), reubicada a la derecha del chat en vez de a ambos lados. Mi trabajo acá es traducir
esa estructura ya aprobada en tokens/clases/estados reales del sistema de diseño de NODDOO,
sin acercarme a la estética JARVIS-OS.

## Qué se adopta / qué se descarta

| Elemento de la referencia | Se adopta | Motivo |
|---|---|---|
| Existencia de un panel de "Monitor de sistema" junto al chat | Sí (estructura) | Ya decidido en SPEC-020/arquitectura-020 — placeholder sin datos |
| Métricas con % + barra de progreso + mini-sparkline en Monitor | No | CA-12/CA-26: cero datos reales; SPEC-020 prohíbe explícitamente "sparklines reales" y cualquier dato que aparente ser telemetría |
| Columna derecha con Tareas siempre visible | Sí | Ya decidido (Tareas pasa de modal a panel persistente) |
| Tabs "Tareas/Registros" con contador tipo "3/4" | No (solo Tareas) | "Registros" fuera de alcance (ASUMIDO 3 de SPEC-020); no se agregan tabs para un contenido único |
| Panel "Memoria/Conocimiento" con buscador y tarjetas de nodos | No | Fuera de alcance (ASUMIDO 2 de SPEC-020) — no hay backend que lo respalde |
| Barra superior con clúster de estado ("núcleo en línea", "red estable") | No | Sería telemetría simulada — mismo motivo que se excluyen las métricas del Monitor |
| Tema claro + acento cian | No | Cero tokens nuevos (CA-15/16/17); se mantienen los temas oscuro/claro actuales de `theme.py`/`theme.css` sin cambios |
| Decoración tipo HUD (esquinas bracket, tipografía técnica) | No | Excluido explícitamente por SPEC-020 ("No incluye") y por el propio análisis de la referencia |
| Badges/pills redondeados de estado en tareas | No | El sistema actual ya distingue pendiente/completada con `.task-item.completed` (tachado); agregar un pill nuevo sería decoración adicional no pedida |
| Reorganizar el estado vacío del chat acercando los chips al saludo | Sí | Ya decidido (CA-19/20, `relocateChipsRow()`) |
| Mucho whitespace / agrupación clara | Parcial | Se reutiliza el ritmo de spacing ya existente en `panels.css`/`sidebar.css` (múltiplos de 4: 8/12/14/16px), no se inventa un sistema de densidad nuevo |

## Tokens (nuevos o reutilizados)

**Cero tokens nuevos.** Todo color reutiliza exactamente las variables ya definidas en
`ui/webview/theme.py` (`DARK_TOKENS`/`LIGHT_TOKENS`) y
`ui/webview/frontend/css/theme.css`. Mapeo explícito de qué token existente cubre cada
necesidad visual de esta propuesta:

| Necesidad visual | Variable CSS reutilizada | Ya usada hoy en |
|---|---|---|
| Fondo de `#side-panel` (columna de chrome, no de contenido primario) | `var(--bg-secondary)` | `#sidebar`, `.modal-box`, `.panel-item` |
| Separador vertical `#side-panel` / `#main-column` | `var(--border)` | `#sidebar` (`border-right`), `.settings-row` |
| Separador horizontal Monitor / Tareas dentro de `#side-panel` | `var(--border)` | `#sidebar-footer` (`border-top`) |
| Título de sección (Monitor, Tareas, Proyectos, Configuración) | `var(--text-primary)` | `.modal-title`, `#sidebar-logo` |
| Icono decorativo de cabecera (Tareas/Proyectos/Configuración) | *(glyph de texto, no color propio — hereda `var(--text-primary)` de `.panel-header-title-group`)* | mismo glyph ya usado en `.sidebar-action-btn .icon` |
| Placeholder de Monitor / listas vacías | `var(--text-secondary)` | `.panel-empty` (sin cambios, reutilizado tal cual) |
| Foco visible en `.panel-form input/select` y `.settings-row-select` | `var(--text-accent)` | `#composer-input-row:focus-within`, `#sidebar-search-input:focus` |
| Fondo de inputs/selects sin cambios | `var(--bg-input)` | `.panel-form input/select`, `.settings-row-select` (sin cambios) |

No hay ninguna fila "Nuevo" en esta tabla — todas las variables ya existen en ambos archivos
de hoy antes de este REQ.

## Layout

### `#side-panel` (columna nueva, ya fijada por arquitectura en 300px / `flex:none`)

Box model exacto (mismo criterio de caja que `#sidebar`, espejado al lado derecho):

```css
#side-panel {
  width: 300px;
  flex: none;
  min-height: 0;               /* necesario para que #tasks-panel-mount pueda hacer scroll interno */
  display: flex;
  flex-direction: column;
  background-color: var(--bg-secondary);
  border-left: 1px solid var(--border);   /* #sidebar usa border-right — mismo grosor/color, lado opuesto */
  overflow: hidden;
}

@media (max-width: 1199px) {
  #side-panel { display: none; }
}
```

Archivo: `ui/webview/frontend/css/layout.css` (mismo archivo donde vive `#sidebar`... en
realidad `#sidebar` vive en `sidebar.css`; `#side-panel` va en `layout.css` porque es el nivel
de columna de más alto orden dentro de `#app-body`, igual que `#main-column` — ver
`arquitectura-020.md`, sección "Módulos a modificar").

### Apilado interno: dos secciones, sin scroll compartido

```
#side-panel  (flex-column, min-height:0)
├── #monitor-panel-section   (flex: none — alto fijo por contenido, nunca se comprime)
└── #tasks-panel-mount       (flex: 1; min-height: 0 — ocupa el resto, scroll propio en su lista)
```

```css
/* archivo: ui/webview/frontend/css/panels.css */

#monitor-panel-section {
  flex: none;
  padding: 16px;
  border-bottom: 1px solid var(--border);
}

#tasks-panel-mount {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 16px;
}

/* header y form nunca se comprimen aunque la lista de tareas sea larga */
#tasks-panel-mount > .panel-header,
#tasks-panel-mount > .panel-form {
  flex: none;
}
```

Esto resuelve el caso borde de SPEC-020 ("la lista de tareas necesita scroll propio... sin
empujar ni recortar el panel de Monitor"): `#monitor-panel-section` tiene `flex:none` (alto
fijo por su propio contenido, nunca se achica), `#tasks-panel-mount` absorbe el resto del alto
de `#side-panel`, y dentro de él solo `.panel-list-flex` (ver "Componentes") crece/scrollea —
header y form del formulario de alta quedan siempre fijos y visibles.

Padding uniforme de `16px` en ambas secciones — mismo valor ya usado en `#sidebar-header`
(`padding: 16px`), no es un valor nuevo en el sistema (los valores de spacing en este proyecto
no están tokenizados como color, se repiten literalmente por archivo; `16px`/`12px`/`14px` ya
aparecen en `sidebar.css`/`panels.css` hoy).

### Breakpoint de colapso

Sin cambios respecto a `arquitectura-020.md`: `max-width: 1199px` oculta `#side-panel` por
completo (`display:none`). No hay estado "colapsado a iconos" intermedio (a diferencia de
`#sidebar`) — confirmado por la arquitectura, no hay nada nuevo que decidir acá a nivel
visual. `display:none` también saca `#side-panel` del árbol de accesibilidad automáticamente
(ver "Accesibilidad").

## Componentes

### 1. Monitor de sistema (placeholder) — `#monitor-panel-section`

Estructura:
```
#monitor-panel-section
├── .panel-header
│     └── .panel-section-title  "Monitor de sistema"
└── .panel-empty                "Métricas del sistema — próximamente"
```

- **`.panel-section-title`** (clase nueva, panels.css) — título de sección para contextos NO
  envueltos en `.modal-box` (Monitor y Tareas fijo). Tipografía idéntica a `.modal-title` para
  cumplir "mismo lenguaje visual de cabecera" (ASUMIDO 4): `font-size:15px; font-weight:600;
  color:var(--text-primary);`.
- **Sin ícono.** A diferencia de Tareas/Proyectos/Configuración (ver componente 5), el título
  de Monitor va sin glyph decorativo. Decisión deliberada: Monitor es el único componente
  totalmente nuevo sin ícono ya establecido en el sidebar para reutilizar, y
  `referencia-visual-jarvis-os.md` es explícito en que la referencia mete "detalles
  decorativos tipo HUD" en cada panel — evito agregar cualquier elemento visual que no sea
  estrictamente necesario en la única sección de esta propuesta que SPEC-020 trata con más
  cautela ("usa exclusivamente componentes/tokens ya existentes... si necesita algún elemento
  visual mínimo").
- **Cuerpo:** reutiliza `.panel-empty` tal cual (cero CSS nuevo) — `padding:24px 0;
  text-align:center; font-size:13px; color:var(--text-secondary);`.
- **Texto exacto:** "Métricas del sistema — próximamente" (mismo texto propuesto en SPEC-020,
  cumple CA-13: comunica explícitamente que es un placeholder, no una sección vacía sin
  explicar ni un dato inventado).

**Estados:** este componente es 100% estático (CA-12: cero llamadas al bridge, cero JS). No
tiene hover/focus/active/disabled/loading/error — no hay nada interactivo ni asíncrono que
gestionar. Su único "estado" es el vacío/placeholder, y es permanente en este REQ (no
transiciona a otro estado hasta que un REQ futuro conecte datos reales). Documentado así para
que `orion-tester`/`orion-qa` no esperen encontrar más estados que verificar acá.

### 2. Tareas — panel fijo (antes modal) — `#tasks-panel-mount`

Estructura (poblada una sola vez por `mountTasksPanel()`, directamente dentro de
`#tasks-panel-mount`, sin `.modal-overlay`/`.modal-box` — ya no hay nada que "flote" sobre la
app):

```
#tasks-panel-mount
├── .panel-header
│     └── .panel-header-title-group
│           ├── span.icon[aria-hidden="true"]   &#128203;  (mismo glyph que #tasks-btn de hoy)
│           └── .panel-section-title             "Tareas"
├── .panel-form                (SIN CAMBIOS: título/fecha/prioridad/descripción/Agregar)
└── .panel-list.panel-list-flex   id="tasks-panel-list"
      ├── .panel-item.task-item[.completed]   (uno por tarea, SIN CAMBIOS de estructura interna)
      └── .panel-empty  "No hay tareas todavía."   (si la lista viene vacía)
```

- **Sin `.panel-close-btn`.** No hay nada que cerrar (CA-09/arquitectura: el panel ya no es
  modal). `.panel-header` queda con un solo hijo (`.panel-header-title-group`) —
  `justify-content:space-between` no tiene efecto visible con un solo hijo, no requiere ningún
  ajuste adicional.
- **`.panel-header-title-group`** (clase nueva, panels.css): agrupa ícono + título para que
  sigan viéndose como una unidad aunque en Proyectos/Configuración conviva con
  `.panel-close-btn` como segundo hijo del `.panel-header`. `display:flex; align-items:center;
  gap:8px; min-width:0;`.
- **Ícono reutilizado, no nuevo:** el mismo glyph que hoy tiene `#tasks-btn` en el sidebar
  (`&#128203;`, 📋) — se elimina el botón (CA-09) pero su ícono "migra" a la cabecera del
  panel que lo reemplaza, dando continuidad visual de que "esto es lo mismo que antes abría el
  botón". Usa la misma convención ya existente (`class="icon" aria-hidden="true"`, sin CSS
  propio, hereda tipografía/color del padre) — no se crea una clase de ícono nueva.
- **`.panel-item.task-item`, `.task-item.completed`, `buildTaskForm()`, `buildTaskItem()`:**
  cero cambios (ya cubierto por `arquitectura-020.md`: CA-07 mismas firmas del bridge).

**Estados de la fila de tarea (`.panel-item.task-item`) — sin cambios respecto a hoy, se
listan para dejar constancia de que se auditaron:**
| Estado | Definido en | Cambia con REQ-020 |
|---|---|---|
| Default (pendiente) | `.panel-item` | No |
| Completada | `.task-item.completed .panel-item-title` (tachado + `var(--text-secondary)`) | No |
| Hover en botón completar/eliminar | `.panel-item-btn:hover` (`var(--bg-hover)`) | No |
| Hover en botón eliminar (peligro) | `.panel-item-btn-danger:hover` (`var(--danger)`, texto blanco) | No |
| Vacío (0 tareas) | `.panel-empty` "No hay tareas todavía." | No |
| Foco por teclado en botones (✓/✕) | anillo nativo del navegador (sin `outline:none` en `.panel-item-btn`) | No |
| Loading | No existe hoy (crear/completar/eliminar no muestran spinner, la UI se actualiza cuando llega la señal) | No — fuera de alcance de este REQ, no introducido |
| Error | No existe estado de error visual dedicado hoy (si `create_task` fallara, no hay banner) | No — mismo comportamiento que hoy, no es una regresión de REQ-020, es preexistente |

**Estados nuevos por el cambio de contexto (modal → fijo):**
- **Visible permanentemente** (antes: oculto hasta abrir modal) — no es un "estado" de
  componente sino el cambio de CA-05, ya cubierto por arquitectura.
- **Formulario de alta (`.panel-form input/select`) — foco por teclado:** hoy NO tiene
  `:focus` propio (se queda con el outline nativo del navegador, sin themear). Al volverse
  parte de la vista permanente de la app (no algo que se abre bajo demanda), unifico con el
  patrón ya establecido en `#composer-input-row`/`#sidebar-search-input` (ver Accesibilidad) —
  única corrección de foco que propongo en este REQ, y se aplica también a Proyectos porque
  comparte la misma clase `.panel-form` (ver componente 4).

### 3. `.panel-list-flex` — variante no-modal de `.panel-list`

La arquitectura señaló explícitamente que hace falta distinguir "panel-list dentro de modal"
(altura acotada) de "panel-list en columna fija" (altura flexible con scroll propio), y dejó
la forma exacta a mi criterio. Decisión: **clase modificadora**, no selector por ancestro —
más explícito, no depende de dónde esté anidado el nodo, sigue el patrón ya usado en el
proyecto (`.modal-box-wide`, `.panel-item-btn-danger`, `.settings-banner-error`: modificador
sufijo sobre la clase base, no BEM con `--`).

```css
/* archivo: panels.css — la regla base .panel-list NO se toca, esto solo la extiende */
.panel-list-flex {
  max-height: none;   /* anula el tope de 320px pensado para el modal */
  flex: 1;
  min-height: 0;      /* imprescindible para que overflow-y:auto funcione dentro de flex */
}
```

Uso: `tasks_panel.js` arma el elemento de la lista con `list.className = "panel-list
panel-list-flex"` (ambas clases) en vez de solo `"panel-list"`. `overflow-y:auto`,
`display:flex; flex-direction:column; gap:6px` los sigue dando la regla base `.panel-list`
sin cambios — `.panel-list-flex` únicamente pisa `max-height` y agrega el comportamiento de
crecer dentro del flex-column de `#tasks-panel-mount`.

**Proyectos y Configuración no usan `.panel-list-flex`** — su `.panel-list` sigue con
`max-height:320px` sin ningún cambio (siguen siendo modales de altura acotada, CA-21/23 no se
tocan).

**Estados:** hereda los de `.panel-list` base (scroll con `overflow-y:auto`, scrollbar ya
estilizada globalmente en `reset.css`). Vacío: mismo `.panel-empty` dentro de la lista, sin
cambios. No aplica hover/focus/disabled a nivel de contenedor de lista (son propiedad de cada
`.panel-item` dentro, ya cubiertos en el componente 2).

### 4. Retoque de cabecera — Proyectos y Configuración (ASUMIDO 4)

Alcance real de "mismo lenguaje visual de cabecera/tarjeta" tras bajar al detalle:

- **Tarjeta (`.panel-item`, `.panel-form`, `.panel-empty`):** ya son compartidas hoy por
  Tareas/Proyectos — **no cambian**. La consistencia de "tarjeta" ya existe porque las tres
  pantallas usan literalmente las mismas clases de `panels.css`; no hay nada que replicar acá,
  documentado así explícitamente para que `orion-dev` no busque un cambio que no existe.
- **Cabecera — sí cambia:** se agrega `.panel-header-title-group` (icono + `.modal-title`)
  como primer hijo de `.panel-header`, igual que en Tareas, para que las tres cabeceras
  (Tareas fija, Proyectos modal, Configuración modal) compartan la misma composición visual
  "ícono + título", en vez de que solo Tareas la tenga:
  - `projects_panel.js::renderMasterShell()` — ícono `&#128193;` (📁, el mismo que
    `#projects-btn` en el sidebar) + `.modal-title` "Proyectos", seguido de
    `.panel-close-btn` como segundo hijo de `.panel-header` (sin cambios en el botón de
    cerrar en sí).
  - `settings_panel.js::renderShell()` — ícono `&#9881;` (⚙️, el mismo que `#settings-btn`) +
    `.modal-title` "Configuración", + `.panel-close-btn`.
  - **`projects_panel.js::renderDetailShell()` (vista de detalle de un proyecto) — SIN
    ícono.** El título ahí es el *nombre del proyecto* (dato del usuario, ej. "Rediseño Q3"),
    no la palabra "Proyectos" — anteponer el ícono de la categoría "Proyectos" a un nombre
    específico sería una asociación visual incorrecta. Se deja exactamente como está hoy
    (`backBtn` + `title` + `closeBtn`, 3 hijos, sin grupo).
- **Agrupación (ej. "Pendientes"/"Completadas" dentro de la lista de Tareas):** **no se
  adopta en este REQ.** El comentario de `arquitectura-020.md` la deja condicionada ("si
  Tareas gana agrupación, Proyectos podría agrupar igual") — decido no introducirla porque
  requeriría dividir `renderTasks()` en sub-listas con encabezados de grupo nuevos, un cambio
  de estructura de datos/renderizado (no solo de estilo) que SPEC-020 no pidió explícitamente
  y que le corresponde decidir a `orion-architect` si se quiere en un REQ futuro. Lo señalo acá
  para que `orion-dev` no lo dé por hecho y `orion-qa` no lo marque como faltante.

**Estados de `.panel-close-btn`:** sin cambios (sigue sin `:hover`/`:focus` temáticos propios,
mismo comportamiento preexistente que ya tenía antes de REQ-020). Lo señalo en "Fuera de
alcance visual" — es una carencia real que noté en la revisión de accesibilidad, pero
corregirla no es necesaria para ningún criterio de SPEC-020 y el ícono/cabecera nuevo no la
empeora, así que no la incluyo en este REQ para no ampliar el diff más de lo aprobado.

### 5. Chips reubicados en el estado vacío — `#empty-state-chips-slot`

La arquitectura ya fija el mecanismo (`relocateChipsRow()` mueve el nodo, no lo clona). El
detalle visual que falta:

```css
/* archivo: composer.css — junto a la regla existente de #chips-row */
#chips-row:empty {
  display: none;
}
```
Sin esto, un `#chips-row` con 0 chips (antes de que lleguen del bridge, o si la respuesta
viniera vacía) seguiría ocupando su lugar en el `gap:12px` de `#empty-state`, dejando un hueco
en blanco debajo del subtítulo. Con `:empty`, un `#chips-row` sin hijos deja de generar caja
visible en cualquiera de sus dos ubicaciones (composer o estado vacío) — mejora también el
comportamiento ya existente en el composer, no solo el nuevo.

```css
/* archivo: chat.css — junto a las reglas existentes de #empty-state */
#empty-state-chips-slot #chips-row {
  margin-bottom: 0;      /* el margin-bottom:10px de composer.css era para separarlo del
                             input row; acá el gap:12px de #empty-state ya da esa separación */
  justify-content: center;  /* centra el wrap de chips igual que el resto de #empty-state
                                (que ya usa align-items:center) */
}
```

**Estados:** el propio `.chip` no cambia (mismo `.chip:hover`, mismo `.chip-risk-dot`/
`chip-risk-green|yellow|red`) — moverlo de contenedor no le agrega ni le quita estados, solo
cambia su posición en el DOM y su alineación visual dentro del nuevo contenedor. Vacío: cubierto
arriba con `:empty`.

## Accesibilidad

- **Contraste de texto:** todas las combinaciones color+fondo usadas en esta propuesta son
  pares ya validados en REQs anteriores (comentarios CA-36 en `chat.css`/`sidebar.css`), no se
  introduce ninguna combinación nueva:
  - `var(--text-primary)` sobre `var(--bg-secondary)` — ya usado en `#sidebar-logo`,
    `.modal-title` dentro de `.modal-box` (mismo fondo).
  - `var(--text-secondary)` sobre `var(--bg-secondary)` — ya usado en `.panel-item-meta`,
    `.conv-meta`, `.settings-row-desc`.
  - `#side-panel` reutiliza exactamente el mismo fondo que `#sidebar` (`--bg-secondary`), así
    que hereda la misma validación de contraste ya hecha para esa columna, en ambos temas.
  - Nota (no es un defecto): `.panel-item` (fondo `--bg-secondary`) queda sobre un contenedor
    que también es `--bg-secondary` (antes `.modal-box`, ahora `#tasks-panel-mount`/
    `#side-panel`) — mismo comportamiento que ya existe hoy en los modales de Tareas/
    Proyectos (la separación entre tarjetas viene del `gap:6px` de `.panel-list`, no de
    contraste de fondo). No es una regresión de este REQ.
- **Foco visible por teclado:**
  - Todos los `<button>` nuevos o reubicados (`.panel-item-btn`, `.panel-submit-btn`, íconos
    de cabecera que no son interactivos) conservan el anillo de foco nativo del navegador —
    `reset.css` no suprime `outline` para `<button>`, solo los inputs que ya definen su propio
    `:focus` con `border-color`.
  - **Corrección que agrego:** `.panel-form input`, `.panel-form select` y
    `.settings-row-select` hoy NO tienen `:focus` propio (dependen del outline nativo sin
    themear) — son la única excepción en todo el sistema de inputs de NODDOO
    (`#composer-input-row`, `#sidebar-search-input` ya usan `outline:none; border-color:
    var(--text-accent)`). Unifico con ese patrón ya establecido:
    ```css
    /* panels.css */
    .panel-form input:focus,
    .panel-form select:focus {
      outline: none;
      border-color: var(--text-accent);
    }
    ```
    ```css
    /* settings_panel.css */
    .settings-row-select:focus {
      outline: none;
      border-color: var(--text-accent);
    }
    ```
    Esto beneficia a Tareas (fija) y Proyectos (modal) por igual, ya que ambas comparten
    `.panel-form` — es la corrección concreta de "spacing/jerarquía" de CA-22 que sí aplica a
    ambas pantallas, sin tocar ningún dato ni contrato del bridge.
  - `#side-panel` oculto por `display:none` en `max-width:1199px` queda automáticamente fuera
    del árbol de accesibilidad (equivalente a `aria-hidden`) — no hace falta ningún atributo
    ARIA adicional ni lógica JS para anunciar el colapso.
  - Los íconos de cabecera nuevos (`.icon` en Tareas/Proyectos/Configuración) llevan
    `aria-hidden="true"`, igual que los íconos ya existentes en `.sidebar-action-btn` — el
    título de texto de al lado (`Tareas`/`Proyectos`/`Configuración`) ya transmite el
    significado, evita duplicar/confundir a lectores de pantalla.
  - Eliminar `#tasks-btn` no deja ningún elemento "muerto" en el tab order — se saca
    completamente del DOM, el foco simplemente salta al siguiente control (mismo criterio que
    ya validó `arquitectura-020.md` para CA-09).
- **Tamaño mínimo de click:** `.panel-item-btn` (26×26px) y `.panel-submit-btn` (padding
  7×14px, alto ~30px) ya cumplen el mínimo de 24×24px recomendado — sin cambios. `.panel-
  close-btn` (24×24px, en el límite) se mantiene sin cambios en Proyectos/Configuración — no
  se reduce en ningún punto de esta propuesta.

## Fuera de alcance visual

- Cualquier dato real de CPU/memoria/red/uptime en el panel de Monitor de sistema (ya excluido
  por SPEC-020, confirmado acá: el placeholder es 100% texto estático).
- Barras de progreso, mini-sparklines, grid de stats (uptime/núcleos/temperatura/latencia) —
  parte de la referencia JARVIS-OS explícitamente descartada.
- Panel "Memoria/Conocimiento" y pestaña "Registros" — ya excluidos por SPEC-020.
- Agrupación por estado (Pendientes/Completadas) dentro de la lista de Tareas o de Proyectos —
  ver componente 4, requiere decisión de `orion-architect` si se quiere a futuro.
- Estilizar el hover/focus de `.panel-close-btn` (Proyectos/Configuración) — carencia
  preexistente detectada en la revisión de accesibilidad, no corregida en este REQ para no
  ampliar el alcance aprobado.
- Estados de "loading"/"error" visual dedicados para crear/completar/eliminar tarea o proyecto
  (spinners, banners de error) — no existen hoy, este REQ no los introduce.
- Cualquier toggle manual de colapso de `#side-panel` — el colapso es 100% automático por
  ancho de ventana (ya decidido por arquitectura), no hay una versión "colapsada a íconos"
  como la que sí tiene `#sidebar`.
- Tocar `#tasks-btn`'s reemplazo por otra función — ya decidido (se elimina, no se re-etiqueta).

## Riesgos de regresión visual

| Riesgo | Mitigación |
|---|---|
| `.panel-list-flex` (nueva) podría no aplicar si `tasks_panel.js` arma la lista con una sola clase en vez de las dos (`"panel-list panel-list-flex"`) | Documentado explícitamente el `className` exacto a usar en el componente 3; `orion-tester` puede verificar con `getComputedStyle` que `max-height` es `none` dentro de `#tasks-panel-mount` |
| Agregar `.panel-header-title-group` a Proyectos/Configuración podría desalinear el `.panel-close-btn` si `justify-content:space-between` deja de tener exactamente 2 hijos | Verificado: en ambos casos (`renderMasterShell` de Proyectos, `renderShell` de Configuración) el resultado sigue siendo exactamente 2 hijos de `.panel-header` (grupo + close-btn) — mismo comportamiento de `space-between` que hoy |
| `#chips-row:empty { display:none }` podría ocultar el composer's chips-row en un momento en que antes se veía vacío pero "reservando espacio" | Revisado: hoy un `#chips-row` sin hijos ya mide 0px de alto (flex sin contenido); la única diferencia es que ya no arrastra su `margin-bottom:10px` cuando está vacío — cambio a favor, no regresión |
| `min-height:0` faltante en algún nivel de la cadena `#side-panel` → `#tasks-panel-mount` → `.panel-list-flex` rompería el scroll interno silenciosamente (bug clásico de flexbox) | Especificado explícitamente en los tres niveles en este documento — `orion-tester` debe verificar con una lista larga de tareas que el scroll queda contenido dentro de `#tasks-panel-mount` sin empujar `#monitor-panel-section` |
| El ícono `.icon` migrado de `#tasks-btn` a la cabecera de Tareas podría interpretarse como que hay que mantener también el botón del sidebar | Aclarado explícitamente: `#tasks-btn` se elimina por completo (CA-09/arquitectura), el ícono solo se reutiliza visualmente en el nuevo destino, no hay dos copias del control |

## DoD check (`.claude/rules/definition-of-done.md` — sección `orion-ui`)

```
[x] Contexto leído (REQ-020-context.md, SPEC-020.md, baseline-020.md, arquitectura-020.md)
[x] Sistema de diseño actual releído (theme.py/theme.css, layout.css, sidebar.css, chat.css,
    composer.css, panels.css, settings_panel.css, modal.css, animations.css, fonts.css,
    reset.css, index.html) antes de proponer clases/tokens
[x] Referencia visual (origen/referencia-visual-jarvis-os.md) analizada y contrastada
[x] Cero tokens/colores nuevos — verificado variable por variable contra theme.py/theme.css
[x] Estructura de layout no contradice arquitectura-020.md (misma jerarquía DOM, mismos IDs)
[x] Cada componente nuevo/modificado con sus estados (o "no aplica" explícito, justificado)
[x] Accesibilidad básica revisada: contraste (pares ya validados, ninguno nuevo), foco visible
    (corrección concreta en .panel-form input/select y .settings-row-select), tamaño de click
[x] Fuera de alcance visual documentado explícitamente
[x] Riesgos de regresión visual con mitigación
[x] No es rediseño sustancial — no requiere nueva aprobación humana (ver "Estado" arriba)
[x] No se encontró ningún punto que contradiga o requiera algo no cubierto por la arquitectura
    aprobada (ver mensaje de cierre al humano)
```

## Handoff

`orion-security` no aplica a este REQ (no toca secretos, autenticación ni acciones
destructivas nuevas — el flujo de borrado de tareas ya usa la confirmación Amarillo existente,
sin cambios).

```
@orion-dev REQ-020 | ui-design=workspace/adjuntos/REQ-020/propuestas/ui-design-020.md
```
