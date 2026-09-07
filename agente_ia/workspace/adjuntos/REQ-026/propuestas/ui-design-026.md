# Diseño UI REQ-026 — Modos estratégicos en la barra del composer

**Estado:** ⏸️ ESPERANDO VALIDACIÓN (rediseño visual real, no ajuste menor)
**Agente:** orion-ui
**Fecha:** 2026-09-07
**Insumos leídos:** `SPEC-026.md`, `propuestas/arquitectura-026.md`, `REQ-026-context.md`,
`ui/webview/theme.py`, `ui/webview/frontend/css/theme.css`, `composer.css`, `icons.css`,
`sidebar.css`, `fonts.css`, `index.html`, `composer.js`, `tests/test_webview_contrast.py`.

---

## Referencia analizada

No hay mockup/captura adjunta en `origen/` — la referencia es la descripción textual de
Johan (recogida en el encargo a este agente): la fila de chips actual (5 botones de texto
simples, todos con el mismo peso visual) se reemplaza por **4 "modos"** con más peso
estratégico — Código/script, Investigación, Nodos/flujos, Tareas — que al activarse quedan
resaltados (toggle) y especializan el chat. Se conservan, con **menos protagonismo**, 3
accesos rápidos sueltos: Captura de pantalla, Abrir navegador, Recuérdame algo. Pedido
explícito: "que se vean mejor visualmente" que los chips actuales.

Contraste con el sistema actual (`_CHIPS` en `bridge.py`, `.chip` en `composer.css`): hoy
los 5 chips son idénticos entre sí (misma píldora, mismo borde, mismo texto secundario) —
no hay jerarquía visual entre "prellenar texto" y "ejecutar una acción", y no existe ningún
concepto de estado persistente/activo. Eso es exactamente lo que el rediseño tiene que
introducir: dos niveles de peso visual (modos vs. accesos rápidos) y un estado "activo" que
se lea sin ambigüedad.

---

## Qué se adopta / qué se descarta

| Elemento de la referencia (pedido de Johan) | Se adopta | Motivo |
|---|---|---|
| 4 modos con más peso visual que los chips actuales | Sí | Pedido explícito; se resuelve con un componente `.mode-btn` nuevo, más grande y con relleno en estado activo, distinto del `.chip` existente |
| Accesos rápidos con menos protagonismo | Sí | Se reutiliza `.chip` (la píldora ya existente) tal cual — ya es visualmente más liviana que cualquier propuesta nueva para modos, así que "menos protagonismo" sale gratis de no tocarla |
| Estado activo distinguible sin depender solo de color | Sí (obligatorio por SPEC) | Relleno de fondo (forma) + ícono de check adicional (forma/ícono) + `aria-pressed`, no solo cambio de color de texto |
| Un ícono nuevo por modo, dibujado ad-hoc | No | Ya existen en el sprite de `index.html` iconos con el significado exacto que necesita cada modo (`ic-terminal`, `ic-search`, `ic-flows`, `ic-tasks`) — crear íconos nuevos duplicaría significado y rompería la consistencia con los botones de sidebar (Terminal, Tareas, Flujos) que ya usan esos mismos símbolos para lo mismo |
| Colores nuevos para diferenciar cada modo (p. ej. un color por modo) | No | El sistema de diseño (`theme.css`) es deliberadamente neutro: el color se reserva para acento de acción + 3 niveles de riesgo (ver comentario en `theme.css:10-12`). Cuatro colores nuevos por modo romperían esa regla y no aportan nada que el ícono + label no den ya — se descarta explícitamente |
| Emoji en los accesos rápidos (📷/🌐 ya vienen en el `label` de `_CHIPS`) | Se mantiene sin tocar, marcado como fuera de alcance | El propio sistema de iconos (`icons.css:6-9`) documenta que el resto de la interfaz abandonó los emoji a favor de SVG en `currentColor` — los 2 accesos rápidos con emoji quedaron como inconsistencia heredada. Corregirla requeriría agregar un campo `icon` al payload de `_QUICK_ACTIONS` que la arquitectura no definió (solo trae `{label, kind, payload, risk_level}`) — es un cambio de contrato de datos, no de CSS/iconografía pura, y no me corresponde decidirlo unilateralmente. Ver "Fuera de alcance visual" |

---

## Tokens (todos reutilizados — cero tokens nuevos)

No hace falta ningún color/tipografía nuevo en `theme.css`/`theme.py`. Todo el rediseño se
resuelve con tokens ya existentes:

| Variable CSS | Uso en este REQ | Archivo(s) | Nuevo/Existente |
|---|---|---|---|
| `--bg-secondary` | Fondo de `.mode-btn` en reposo | `theme.css` | Existente |
| `--bg-hover` | Fondo de `.mode-btn`/`.chip` en `:hover` | `theme.css` | Existente |
| `--border` | Borde de `.mode-btn` en reposo | `theme.css` | Existente |
| `--text-secondary` | Color de ícono+label de `.mode-btn` en reposo | `theme.css` | Existente |
| `--text-primary` | Color de ícono+label de `.mode-btn` en `:hover` | `theme.css` | Existente |
| `--text-accent` | Fondo de `.mode-btn--active` (relleno) | `theme.css` | Existente |
| `--bg-primary` | Color de ícono+label sobre `.mode-btn--active` en tema oscuro (mismo patrón que `.composer-send-btn`, CA-36) | `theme.css` | Existente |
| `#ffffff` (hardcodeado, mismo patrón ya usado por `.composer-send-btn`) | Color de ícono+label sobre `.mode-btn--active` en tema claro | `composer.css` | Existente (patrón ya en uso, líneas 117-136) |
| `--radius-md` (10px) | Forma de `.mode-btn` (rectangular, no píldora) | `theme.css` | Existente |
| `--radius-pill` | Forma de `.chip` (accesos rápidos, sin cambios) | `theme.css` | Existente |
| `--icon` (16px) | Tamaño de ícono dentro de `.mode-btn` | `theme.css` | Existente |
| Inter, weight 500 ("Medium") | Label de `.mode-btn` (más peso tipográfico que el `.chip`, que queda en 400 regular heredado) | `fonts.css` | Existente (ya vendorizada, no hace falta cargar nada nuevo) |
| `--text-accent` (foco) | `outline` de `:focus-visible` en `.mode-btn` y `.chip`, mismo patrón que el resto de la app | `theme.css` | Existente |

**Íconos reutilizados del sprite (`index.html:34-` en adelante) — ninguno nuevo:**

| Modo | Ícono | Ya usado hoy para | Coherencia semántica |
|---|---|---|---|
| Código/script | `#ic-terminal` | Botón "Terminal (PowerShell)" del header | Mismo símbolo = misma idea (ejecutar código/comandos) en toda la app |
| Investigación | `#ic-search` | Campo "Buscar conversaciones" del header | Mismo símbolo = buscar/investigar, reconocible de inmediato |
| Nodos/flujos | `#ic-flows` | Botón "Flujos" del header | Coincidencia literal 1:1 con el panel que este modo prioriza |
| Tareas | `#ic-tasks` | Botón "Tareas" del header | Coincidencia literal 1:1 con el panel que este modo prioriza |

Reusar exactamente estos 4 símbolos (en vez de dibujar 4 nuevos) es una decisión de diseño
deliberada: el usuario ya aprendió qué significa cada ícono en el header, así que verlos de
nuevo en el composer refuerza la asociación en lugar de introducir un segundo vocabulario
visual.

---

## Layout

Reemplaza el contenedor único `#chips-row` (definido por la arquitectura como
`#modes-row` + `#quick-actions-row`) sin mover nada del resto del composer — misma posición
en el DOM, antes de `#composer-input-row`, dentro de `#composer-inner`:

```html
<div id="composer-inner" class="content-col">
  <div id="modes-row"></div>
  <div id="quick-actions-row"></div>

  <div id="composer-input-row"> ... </div>   <!-- sin cambios -->
  <div id="attachment-chip" hidden> ... </div>  <!-- sin cambios -->
</div>
```

- **`#modes-row`** (arriba, más peso): `display:flex; flex-wrap:wrap; gap:8px;
  margin-bottom:6px`. Contiene los 4 `.mode-btn` en el orden fijo Código → Investigación →
  Flujos → Tareas (mismo orden que `listar_modos()` define en la arquitectura).
- **`#quick-actions-row`** (abajo, pegada al input, menos peso): `display:flex;
  flex-wrap:wrap; gap:6px; margin-bottom:10px` (mismo `margin-bottom` que tenía
  `#chips-row` hoy, para no correr el input de lugar). Contiene los 3 `.chip` de siempre
  (Captura, Navegador, Recuérdame algo), sin cambios de comportamiento.
- Sin breakpoints nuevos: la ventana es de escritorio con `--content-max: 760px` fijo (no
  hay modo responsive de ancho variable en esta app) — `flex-wrap: wrap` alcanza si algún
  día se angosta la ventana, mismo criterio que ya usaba `#chips-row`.
- El orden (modos arriba, accesos rápidos abajo, pegados al input) es intencional: los
  accesos rápidos son las acciones que el usuario dispara "de paso" mientras escribe —
  quedan más cerca físicamente del campo de texto. Los modos, al ser una decisión que se
  sostiene durante toda la conversación, quedan arriba, con más aire.

---

## Componentes

### `.mode-btn` (nuevo — los 4 botones de `#modes-row`)

Estructura por botón (el `id`/`data-mode-id` exacto lo define `core/composer_modes.py`,
acá van solo sugerencias de valor para no dejarlo abierto):

```html
<button type="button" class="mode-btn" data-mode-id="codigo" aria-pressed="false"
        title="Prioriza generación y ejecución de código">
  <svg class="ic" aria-hidden="true"><use href="#ic-terminal"/></svg>
  <span class="mode-btn-label">Código</span>
</button>
```

Labels sugeridos (cortos, el detalle va en `title`): **Código**, **Investigación**,
**Flujos**, **Tareas**. El mapeo ícono↔modo es una tabla estática en `composer.js` (por
`id` del modo), no un campo nuevo del payload — no hace falta volver a `orion-architect`
por esto, es una decisión puramente de presentación en el frontend.

Forma: rectangular con esquinas redondeadas (`--radius-md`, 10px) — deliberadamente
**distinta** de la píldora (`--radius-pill`) que usan los accesos rápidos, para que la
diferencia de "peso estratégico" también se lea en la silueta, no solo en tamaño/color.

| Estado | Fondo | Borde | Color ícono+label | Otro |
|---|---|---|---|---|
| Normal | `--bg-secondary` | `1px solid var(--border)` | `--text-secondary` | padding `8px 14px`, gap ícono-label `7px`, font 13px/500 |
| `:hover` | `--bg-hover` | `1px solid var(--text-secondary)` | `--text-primary` | mismo patrón de transición que `.chip:hover` (140ms) |
| `:focus-visible` | (sin cambio de fondo) | — | — | `outline: 2px solid var(--text-accent); outline-offset: 1px` — igual que el resto de los controles interactivos de la app |
| **Activo** (`aria-pressed="true"`, clase `.mode-btn--active`) | `--text-accent` (relleno sólido) | `1px solid transparent` | `--bg-primary` en tema oscuro / `#ffffff` en tema claro (mismo override que `.composer-send-btn`, CA-36) | Se agrega un ícono de check (`#ic-check`, 14px, `ic-sm`) después del label — ver justificación de accesibilidad abajo |
| `:disabled` | — | — | — | **No aplica.** `setComposerEnabled()` hoy no alcanza a `#chips-row` (solo deshabilita `#composer-input` y alterna enviar/detener) y el caso borde de SPEC-026 exige que el modo se pueda togglear con un streaming en curso — `.mode-btn` nunca debe quedar `disabled` |
| Loading / Error | — | — | — | No aplica — el toggle de modo es instantáneo (estado local en JS), no dispara ninguna llamada async que pueda quedar "cargando" o fallar visiblemente |

**Por qué el check y no solo el relleno de color:** SPEC-026 pide explícitamente que el
estado activo "sea distinguible sin depender solo de color". El relleno sólido ya es un
cambio de *forma* (superficie llena vs. contorno), pero se refuerza con un tercer elemento
no cromático — un ícono adicional (`#ic-check`, ya existe en el sprite, mismo símbolo que
usa el resto de la app para "confirmado/aplicado") — así el estado se lee incluso en
escala de grises o para alguien con deficiencia de percepción de color. El `aria-pressed`
cubre el canal semántico para lectores de pantalla (no depende de nada visual).

### `.chip` (accesos rápidos de `#quick-actions-row` — sin cambios de estilo)

Se reutiliza tal cual el `.chip` que ya existe en `composer.css` (líneas 27-49): mismo
padding, misma píldora, mismo `.chip-risk-dot` para "Captura de pantalla"/"Abrir navegador"
(kind `action`, con punto de color por nivel de riesgo — sin tocar esa lógica). Único
cambio: la fila contenedora pasa de `#chips-row` a `#quick-actions-row`, cero cambio de
selector CSS necesario (`.chip` sigue siendo `.chip`).

| Estado | Igual que hoy |
|---|---|
| Normal | `--bg-secondary`/`--border`/`--text-secondary` |
| `:hover` | `--bg-hover`/`--text-secondary` (borde)/`--text-primary` |
| `:focus-visible` | `outline: 2px solid var(--text-accent)` |
| Activo persistente | No aplica — ninguno de los 3 accesos rápidos es un toggle (2 ejecutan una acción puntual, 1 prellena el input) |
| `:disabled` | No aplica, igual que hoy |

---

## Accesibilidad

- **Contraste verificado (AA):**
  - Modo inactivo: `--text-secondary` sobre `--bg-secondary` — mismo par ya cubierto por
    `tests/test_webview_contrast.py::_NORMAL_TEXT_PAIRS` (`text_secondary/bg_secondary`),
    pasa AA en ambos temas.
  - Modo activo (relleno `--text-accent`): oscuro `--bg-primary` sobre `--text-accent` =
    **7.70:1**; claro `#ffffff` sobre `--text-accent` = **5.19:1**. Ambos superan el umbral
    de 4.5:1 (texto normal) y el de 3:1 (componente UI no textual), calculado con el mismo
    algoritmo WCAG que usa `test_webview_contrast.py`. Es el mismo par que ya usa
    `.composer-send-btn` (CA-36) — no es una combinación nueva sin probar, es la reutilización
    exacta de un patrón ya validado en producción.
  - **Pendiente para `orion-tester`/`orion-dev`:** este par (`--text-accent` como fondo +
    `--bg-primary`/`#ffffff` como contenido) no está listado explícitamente en
    `_NORMAL_TEXT_PAIRS` de `test_webview_contrast.py` — igual que `.composer-send-btn` no lo
    está. Señalo que sería bueno agregarlo como caso explícito la próxima vez que se toque ese
    archivo, pero no lo agrego yo (no me corresponde escribir tests).
- **Foco visible:** sí, `:focus-visible` con el mismo outline de 2px en `--text-accent` que
  usa el resto de los controles interactivos de la app (`.chip`, `.icon-btn`, `.model-btn`) —
  ningún patrón nuevo, mismo lenguaje de foco en toda la interfaz.
- **Tamaño mínimo de click:** `.mode-btn` con padding `8px 14px` + ícono 16px + línea de
  texto ≈ 34-36px de alto total, por encima del mínimo de 24×24px de WCAG 2.5.5 y en línea
  con `--icon-btn` (30px), el token que ya usa el resto de los botones de icono de la app.
- **Estado activo por canal no visual:** `aria-pressed="true"/"false"` en cada `.mode-btn`
  (mecanismo ya fijado por la arquitectura) es lo que un lector de pantalla anuncia — el
  relleno + check son el refuerzo visual, `aria-pressed` es el refuerzo semántico. Ningún
  canal depende únicamente del otro.

---

## Fuera de alcance visual

- **No** se resuelve la inconsistencia de los emoji (📷/🌐) embebidos en el `label` de los
  2 accesos rápidos tipo `action`. El sistema de iconos de la app abandonó los emoji a favor
  de SVG en `currentColor` (ver comentario en `icons.css:6-9`), pero corregir esto acá
  requeriría que `_QUICK_ACTIONS` en `bridge.py` exponga un campo `icon` (id de símbolo del
  sprite) que la arquitectura de este REQ no definió — es un cambio de contrato de datos, así
  que lo señalo como riesgo/deuda visual heredada, no lo decido yo.
- **No** se define el `id` interno final de cada modo en `core/composer_modes.py` — las
  sugerencias de esta propuesta (`codigo`, `investigacion`, `flujos`, `tareas`) son solo eso,
  sugerencias para que el mapeo ícono↔modo en `composer.js` tenga algo concreto de qué
  colgarse; el valor final lo fija quien escriba ese módulo.
- **No** se toca la lógica de `.chip-risk-dot` (verde/amarillo/rojo) de los accesos rápidos
  tipo `action` — sigue exactamente igual que hoy.
- **No** se propone ningún breakpoint/layout responsive nuevo — la ventana de escritorio no
  lo necesita, mismo criterio que ya regía `#chips-row`.
- **No** se decide si `.mode-btn` debe quedar deshabilitado en algún escenario futuro no
  cubierto por SPEC-026 (p. ej. si más adelante se agrega un modo que sí dispara una llamada
  async al togglearse) — con el mecanismo actual (estado 100% local en JS) no hace falta, y
  esta propuesta no inventa ese caso.

---

## Riesgos de regresión visual

| Riesgo | Mitigación |
|---|---|
| `.mode-btn--active` con relleno sólido de `--text-accent` podría verse "más grande"/desalineado si el ícono de check se agrega sin reservar espacio, corriendo el layout al togglear | El check ocupa espacio siempre reservado (usar `visibility:hidden` en vez de agregar/quitar el nodo, o un `min-width` fijo en el botón) — detalle de implementación para `orion-dev`, señalado acá para que no lo resuelva agregando/quitando el ícono del DOM y generando salto de layout |
| Reusar `#ic-terminal` para el modo Código puede confundirse con el botón "Terminal (PowerShell)" del header (mismo ícono, significado relacionado pero no idéntico — uno abre una shell real, el otro prioriza `EXECUTE_CODE`) | Aceptado a propósito (ver tabla de íconos): el usuario ya asocia ese símbolo a "código/ejecución", el matiz de que uno abre una terminal interactiva y el otro prioriza una tool de IA es un detalle de comportamiento, no de iconografía — `title` de cada botón aclara el detalle exacto |
| El nuevo peso visual de `.mode-btn` (más grande que `.chip`) puede hacer que la fila de modos se envuelva a dos líneas en ventanas angostas, empujando el input hacia abajo | Ya cubierto por `flex-wrap: wrap` + `gap` — mismo comportamiento de reflow que ya tenía `#chips-row` con 5 chips, no es una regresión nueva |
| Los 4 labels ("Código", "Investigación", "Flujos", "Tareas") no coinciden literalmente con los nombres completos de SPEC-026 ("Código/script", "Nodos/flujos") | Intencional — versión corta para el botón, versión completa en `title`. Si Johan prefiere el texto literal de la SPEC en el botón, es un ajuste de una palabra por modo, sin impacto en el resto del diseño |

---

## Nota para `orion-dev` (no vinculante, informativa)

Fragmento CSS ilustrativo de `.mode-btn` (no es el código final, orion-dev decide el
archivo/organización exacta dentro de `composer.css`):

```css
.mode-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--border);
  background-color: var(--bg-secondary);
  color: var(--text-secondary);
  border-radius: var(--radius-md);
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 500;
  transition: background-color 140ms, border-color 140ms, color 140ms;
}

.mode-btn:hover {
  background-color: var(--bg-hover);
  border-color: var(--text-secondary);
  color: var(--text-primary);
}

.mode-btn:focus-visible {
  outline: 2px solid var(--text-accent);
  outline-offset: 1px;
}

.mode-btn--active {
  background-color: var(--text-accent);
  border-color: transparent;
  color: #ffffff;
}

:root[data-theme="dark"] .mode-btn--active {
  color: var(--bg-primary);
}
```

---

## Estado: ⏸️ ESPERANDO VALIDACIÓN

Este es un rediseño visual real (pedido explícito de Johan, "que se vean mejor
visualmente"), no un ajuste menor de estilos existentes — según el DoD de `orion-ui`
requiere aprobación humana explícita antes de continuar a `orion-dev`.

**Resumen para la aprobación:**
- 4 botones de modo nuevos (`.mode-btn`), más grandes y con más peso visual que los chips
  actuales, con íconos ya existentes en la app (Terminal/Buscar/Flujos/Tareas) — cero
  íconos nuevos.
- Estado activo: relleno sólido con el color de acento + ícono de check + `aria-pressed` —
  se lee sin depender solo de color, contraste AA verificado en ambos temas (7.70:1 oscuro,
  5.19:1 claro).
- Accesos rápidos (Captura, Navegador, Recuérdame algo) quedan visualmente igual que hoy,
  solo se mueven a su propia fila debajo de los modos.
- Cero tokens de color/tipografía nuevos — todo sale de `theme.css` ya existente.
- Queda señalado (no resuelto) que los 2 accesos rápidos con emoji siguen sin alinearse al
  sistema de iconos SVG del resto de la app — corregirlo necesitaría un cambio de payload
  que esta propuesta no está autorizada a decidir.

⚠️ El flujo no continúa hasta que apruebes este diseño.
Responde: **APROBADO** / **AJUSTAR** [qué] / **RECHAZADO** [motivo]
