# Diseño UI REQ-026 — Addendum 1 (revisión post `SPEC-026-addendum-1.md`)

**Estado:** ✅ APROBADO — Johan confirmó sin ajustes (2026-09-07, ver `REQ-026-context.md`)
**Agente:** orion-ui
**Fecha:** 2026-09-07
**Se aplica sobre:** `propuestas/ui-design-026.md` (aprobado, ya implementado). No se
reescribe desde cero — este addendum documenta solo lo que cambia. Todo lo no mencionado
acá (tokens de color/tipografía, patrón de accesibilidad AA, estados de `.mode-btn` que no
sean tamaño, comportamiento de los 4 modos) sigue vigente tal cual del diseño original.
**Insumos releídos para este addendum:** `spec/SPEC-026-addendum-1.md` (aprobado sin
ajustes por Johan), `REQ-026-context.md`, `ui/webview/frontend/index.html` (sprite
completo de símbolos + estructura DOM real de `#composer-inner`), `ui/webview/frontend/css/composer.css`
(valores reales ya implementados de `.mode-btn`/`.chip`/`#modes-row`/`#quick-actions-row`),
`ui/webview/frontend/css/layout.css` y `theme.css` (`--content-max: 760px`),
`ui/webview/frontend/js/composer.js` (`renderModes()`/`renderQuickActions()` reales).

---

## Motivo (resumen del addendum de SPEC)

Johan, viendo la barra ya implementada en la app real: "quiero que queden solo las
opciones de arriba y recuérdame algo pero el recuérdame algo con un icono como los otros
y el mismo estilo que ocupen todos la misma fila y no quede uno en salto, entonces quita
Captura de pantalla y abrir el navegador". Aprobado sin ajustes en
`spec/SPEC-026-addendum-1.md`, incluida la confirmación explícita de que "Recuérdame algo"
**no** se comporta como modo (sin `aria-pressed`, sin estado activo, sin priorizar
capacidad) — solo comparte estilo visual.

Este addendum resuelve 3 cosas que la SPEC dejó abiertas para `orion-ui`: (1) el layout de
una sola fila, (2) el ícono de "Recuérdame algo", (3) el ajuste de tamaño para que 5
elementos entren sin salto en `--content-max: 760px`.

---

## 1. Layout — de 2 filas a 1 fila, se elimina `#quick-actions-row`

**Diseño anterior (obsoleto):** `#modes-row` (4 modos, arriba) + `#quick-actions-row` (3
accesos rápidos, abajo) — dos contenedores con distinto peso visual.

**Diseño nuevo:** un único contenedor con los 5 elementos, mismo peso visual entre sí (ya
no hay jerarquía "modos vs. accesos rápidos" porque solo sobrevive un acceso rápido y pasa
a compartir componente con los modos):

```html
<div id="composer-inner" class="content-col">
  <div id="actions-row"></div>

  <div id="composer-input-row"> ... </div>   <!-- sin cambios -->
  <div id="attachment-chip" hidden> ... </div>  <!-- sin cambios -->
</div>
```

- Se elimina `#quick-actions-row` del DOM y de `composer.css` por completo (deja de
  existir como contenedor, no solo se vacía).
- `#modes-row` se renombra a `#actions-row` (sugerencia de nombre, no vinculante — ver nota
  de frontera abajo) para reflejar que ya no es "solo modos": contiene los 4 `.mode-btn`
  + "Recuérdame algo" con el mismo componente visual.
- `display: flex; flex-wrap: nowrap` (cambia de `wrap` a `nowrap` — la SPEC exige
  explícitamente que nunca haya salto de línea con los 5 elementos visibles; ya no se acepta
  el reflow que sí era válido en el diseño de 2 filas).
- `gap: 6px` (antes 8px en `#modes-row` / 6px en `#quick-actions-row` — ver cálculo de
  ajuste de tamaño en la sección 3, este valor es parte de ese ajuste, no un cambio
  aislado).
- Orden: Código → Investigación → Flujos → Tareas → Recuérdame algo (mismo orden ya fijado
  para los 4 modos, con "Recuérdame algo" al final — así lo asume `SPEC-026-addendum-1.md`
  como lectura directa del pedido de Johan).

**Nota de frontera con `orion-architect` (no es esta propuesta la que lo decide):** cómo
"Recuérdame algo" llega a poblar `#actions-row` en JS — si se funde con el catálogo de
`renderModes()` en un solo arreglo de 5 ítems, o si `renderQuickActions()` sigue existiendo
con 1 sola entrada pero renderiza dentro del mismo contenedor — es una decisión de flujo de
datos entre `bridge.py` y `composer.js` que el propio `SPEC-026-addendum-1.md` (sección
"Impacto en trabajo ya hecho") deja explícitamente para `orion-architect`/`orion-dev`. Esta
propuesta fija el resultado visual (un contenedor, cinco elementos con el mismo componente,
sin salto), no el mecanismo de renderizado.

---

## 2. Componente — "Recuérdame algo" deja `.chip` y pasa a `.mode-btn` (variante sin toggle)

**Diseño anterior (obsoleto):** "Recuérdame algo" era un `.chip` más (píldora,
`--radius-pill`, padding `6px 13px`, font-size 12.5px, sin ícono, con emoji-less label de
texto plano) — visualmente idéntico a "Captura de pantalla"/"Abrir navegador".

**Diseño nuevo:** comparte el componente `.mode-btn` con los 4 modos: mismo `border-radius`
(`--radius-md`), mismo tratamiento de borde/fondo en reposo/hover/foco, mismo peso
tipográfico (Inter 500), mismo ícono a la izquierda del label. **Diferencia deliberada
respecto a los 4 modos** (por instrucción explícita del addendum de SPEC — no es un modo):

| | 4 `.mode-btn` (Código/Investigación/Flujos/Tareas) | "Recuérdame algo" (`.mode-btn` variante) |
|---|---|---|
| `aria-pressed` | Sí (`"true"`/`"false"`, togglea) | **No lo lleva** — no es un control toggle |
| Clase de estado activo `.mode-btn--active` | Sí, al togglear | **Nunca se aplica** — no hay estado "activo" para este botón |
| Ícono de check reservado (`.mode-btn-check`) | Sí, siempre presente en el DOM (oculto con `visibility` cuando inactivo) | **No se renderiza el nodo** — no tiene estado que confirmar, así que no hace falta reservarle espacio |
| `title` | Nombre completo del modo | Recomendado: `"Prellena el mensaje con un recordatorio"` (mismo patrón de `title` descriptivo que los otros 4, no vinculante) |
| Click | Togglea `aria-pressed`, llama `setActiveMode(id)`, reordena tools/refuerza system prompt | **Sin cambios de comportamiento**: prellena `#composer-input` con `"Recuérdame que "` (`kind="template"`), foco al final del texto — idéntico a como funciona hoy como `.chip` |
| Ícono | `#ic-terminal` / `#ic-search` / `#ic-flows` / `#ic-tasks` (reusados) | `#ic-bell` (nuevo — ver sección 4, no hay reuso semánticamente válido) |

No quitar el ícono de check reservado en esta variante no es un descuido — es intencional:
como este botón nunca activa `.mode-btn--active`, reservar 14px+gap para un check que jamás
aparece sería desperdiciar espacio justo en el elemento donde más se necesita ese espacio
para que la fila entre sin saltar (ver sección 3).

```html
<button type="button" class="mode-btn" data-chip-kind="template"
        title="Prellena el mensaje con un recordatorio">
  <svg class="ic" aria-hidden="true"><use href="#ic-bell"/></svg>
  <span class="mode-btn-label">Recuérdame algo</span>
</button>
```

(Sin `aria-pressed`, sin nodo de check — a diferencia del markup de los 4 modos en
`ui-design-026.md` original.)

`.chip` como clase/componente **no se elimina** del CSS — simplemente deja de tener ningún
elemento del composer que la use, porque los 3 accesos rápidos que la usaban desaparecen o
cambian de componente. Si `.chip` queda sin ningún consumidor real en el DOM tras este
cambio, es una decisión de `orion-dev` si conviene retirarla del CSS o dejarla (mismo
criterio que el addendum de SPEC aplica a `run_chip_action()` en JS — código potencialmente
muerto, no lo decide `orion-ui`).

---

## 3. Ajuste de tamaño — que los 5 elementos entren en 760px sin salto

**Verificación pedida por el addendum de SPEC:** con el tamaño actual de `.mode-btn`
(padding `8px 14px`, font-size 13px, ícono 16px, gap 7px, más el check de 14px siempre
reservado en los 4 modos), ¿entran 5 elementos —4 modos + "Recuérdame algo"— en 760px sin
salto?

**Cálculo (estimación de ancho de texto Inter Medium ~13px, no pixel-exacto — ver nota de
verificación abajo):**

Con el tamaño **actual sin tocar** (padding 14px horizontal, font 13px, gap 7px, check
reservado en los 4 modos, gap de fila 8px):

| Elemento | Ancho estimado |
|---|---|
| Código | ~118px |
| Investigación | ~169px |
| Flujos | ~118px |
| Tareas | ~118px |
| Recuérdame algo (sin check, con ícono) | ~163px |
| 4 gaps de fila (8px) | 32px |
| **Total** | **~718px** |

Con `--content-max: 760px` disponible, el margen es de solo ~42px (~6%) — demasiado
ajustado para confiar en una estimación de fuente sin verificación real en navegador. Un
`aria-live`/idioma con más acentos, un ancho de fuente real levemente distinto, o el propio
`box-sizing`/line-height pueden hacerlo saltar. **No es seguro dejarlo con el tamaño
actual.**

**Ajuste propuesto (aplica a `.mode-btn` como componente compartido — afecta a los 5, no
solo a "Recuérdame algo", tal como habilita explícitamente el addendum de SPEC):**

| Propiedad | Valor actual | Valor propuesto |
|---|---|---|
| `padding` | `8px 14px` | `8px 12px` |
| `font-size` | `13px` | `12.5px` (mismo tamaño que ya usaba `.chip` — no es un valor nuevo en el sistema) |
| `gap` (ícono↔label) | `7px` | `6px` |
| `gap` de `#actions-row` (fila) | `8px` (`#modes-row`) | `6px` |

Con este ajuste, el mismo cálculo da:

| Elemento | Ancho estimado |
|---|---|
| Código | ~109px |
| Investigación | ~158px |
| Flujos | ~109px |
| Tareas | ~109px |
| Recuérdame algo | ~152px |
| 4 gaps de fila (6px) | 24px |
| **Total** | **~661px** |

Margen resultante: ~99px (~13%) sobre 760px — un colchón razonable para absorber la
imprecisión de una estimación de métricas de fuente sin renderizar. El peso tipográfico
(Inter 500) y todos los colores/bordes/radios se mantienen sin cambios; el ajuste es
puramente de tamaño.

**Fallback documentado si aun así no alcanza (verificación real en navegador, no a
cargo de esta propuesta):** acortar el label de "Recuérdame algo" a **"Recordar"** —
ahorra ~7 caracteres (~48px adicionales de margen) sin perder claridad semántica del botón
(el `title` puede seguir diciendo la frase completa). Queda como ajuste puntual de reserva
para `orion-dev`/`orion-tester` si el render real en Chromium/Qt WebEngine resulta más
ancho que esta estimación — no se adopta como valor por defecto porque el cálculo con el
label completo ya deja margen cómodo.

**Nota de verificación (transparencia sobre el método):** este cálculo es una estimación
por conteo de caracteres × ancho promedio de Inter Medium a ese tamaño, no una medición
real en el motor de render de la app (no hay harness de navegador en este pipeline, mismo
límite que ya declaraba `ui-design-026.md` original para el contraste). `orion-dev` debe
confirmar visualmente que los 5 elementos entran sin salto con estos valores antes de dar
por cerrado el criterio de aceptación correspondiente de `SPEC-026-addendum-1.md`; si no
alcanza, aplicar el fallback de label corto antes de tocar de nuevo el padding/font-size
(cambiar el tamaño una segunda vez degradaría más la legibilidad que acortar un label).

---

## 4. Ícono para "Recuérdame algo" — `#ic-bell` (nuevo)

**Confirmo la conclusión de `orion-spec`:** repasé el sprite completo de
`ui/webview/frontend/index.html` (26 símbolos: `ic-terminal`, `ic-tasks`, `ic-flows`,
`ic-folder`, `ic-settings`, `ic-search`, `ic-plus`, `ic-panel-left`, `ic-paperclip`,
`ic-mic`, `ic-send`, `ic-sun`, `ic-moon`, `ic-minimize`, `ic-maximize`, `ic-close`,
`ic-play`, `ic-alerta`, `ic-check`, `ic-info`, `ic-copiar`, `ic-stop`, `ic-lapiz`,
`ic-chevron`, `ic-cpu`, `ic-trash`). Ninguno es una campana, reloj o nota — coincido en que
`ic-alerta` (triángulo de advertencia con `!`) es semánticamente incorrecto para
"recordatorio" y confundiría al usuario con una alerta/advertencia. No hay ningún ícono
reutilizable con el significado correcto. Hace falta un símbolo nuevo.

**Propuesta: `#ic-bell`** — campana simple, coherente con el estilo geométrico del resto
del set (comparar con `ic-mic`: cuerpo principal + un segundo trazo de detalle, sin relleno,
mismo `viewBox="0 0 24 24"`). El grosor de trazo (`stroke-width: 1.75`), `currentColor`,
`stroke-linecap`/`stroke-linejoin: round` los hereda automáticamente de `.ic` en
`icons.css` — el símbolo en sí no lleva ningún atributo de presentación, igual que los 26
existentes.

**Fragmento SVG ilustrativo (no implementar — para que `orion-dev` lo agregue al sprite
de `index.html` junto a los demás `<symbol>`):**

```html
<symbol id="ic-bell" viewBox="0 0 24 24">
  <path d="M6.5 10a5.5 5.5 0 0 1 11 0c0 5 2 6.5 2 6.5h-15s2-1.5 2-6.5z"/>
  <path d="M10 19.5a2 2 0 0 0 4 0"/>
</symbol>
```

Uso en el botón (ver markup completo en sección 2):
`<svg class="ic" aria-hidden="true"><use href="#ic-bell"/></svg>`.

Dos trazos, mismo espíritu que `ic-mic` (cuerpo + accesorio): el primer `path` dibuja el
cuerpo de la campana (domo + base ensanchada, sin badajo dibujado como parte del cuerpo), el
segundo dibuja el pequeño arco del badajo/badge inferior — evita que se lea como una
"D" o una "gota" al reducir la campana a un solo trazo cerrado. Cabe cómodo en el
`viewBox 0 0 24 24` con el mismo margen visual que usan `ic-mic`/`ic-search`
(aprox. 2-3px de aire en cada borde), así que a 16px (`--icon`, tamaño real dentro de
`.mode-btn`) mantiene la misma densidad óptica que los otros 4 íconos del set, sin verse
más pesado ni más liviano.

---

## Tabla "Qué se adopta / qué se descarta" — actualización respecto a `ui-design-026.md`

| Elemento del diseño original | Sigue vigente | Motivo |
|---|---|---|
| 4 `.mode-btn` con relleno sólido + check + `aria-pressed` en estado activo | Sí, sin cambios de comportamiento (solo tamaño, ver sección 3) | El addendum de SPEC no toca la sección "persistencia/estado de modo" — sigue vigente tal cual |
| Íconos reusados del sprite para los 4 modos (`ic-terminal`/`ic-search`/`ic-flows`/`ic-tasks`) | Sí, sin cambios | No afectado por el addendum |
| `#quick-actions-row` como fila separada, con menos peso visual | **No** — se elimina | Johan pidió explícitamente sacar "Captura de pantalla"/"Abrir navegador"; al quedar un solo acceso rápido y pasar a compartir componente con los modos, ya no hay "menos protagonismo" que aplicar — la fila separada pierde su razón de ser |
| "Recuérdame algo" como `.chip` (píldora, sin ícono) | **No** — se reemplaza por `.mode-btn` variante sin toggle | Pedido explícito de Johan, aprobado sin ajustes en `SPEC-026-addendum-1.md` |
| "Captura de pantalla"/"Abrir navegador" como accesos rápidos visibles | **No** — se eliminan del composer | Pedido explícito de Johan. La capacidad del agente (`take_screenshot`/`open_browser` por texto/voz) no se toca — solo el atajo de UI, según aclaración de alcance del propio addendum de SPEC |
| Deuda visual heredada del emoji (📷/🌐) señalada como fuera de alcance | **Queda resuelta por eliminación**, no por corrección | Al desaparecer los 2 chips con emoji del composer, el problema que `ui-design-026.md` señalaba como "fuera de alcance" deja de existir en esta pantalla — no hizo falta decidir sobre el campo `icon` de `_QUICK_ACTIONS` que se mencionaba ahí |

---

## Accesibilidad — sin cambios de fondo, una verificación nueva

- **Contraste (AA):** sin cambios — los 4 modos siguen usando el mismo par ya verificado
  (7.70:1 oscuro / 5.19:1 claro para `.mode-btn--active`). "Recuérdame algo" nunca alcanza
  ese estado (no tiene variante activa), así que solo lo alcanza el par ya cubierto por
  `tests/test_webview_contrast.py` (`text_secondary/bg_secondary`) para su estado en reposo
  — sin combinación nueva que verificar.
- **Foco visible:** sin cambios — mismo `outline: 2px solid var(--text-accent)` en
  `:focus-visible` para los 5 elementos (heredado de `.mode-btn`).
- **Tamaño mínimo de click:** con el ajuste de la sección 3 (padding `8px 12px`, font
  12.5px, ícono 16px), el alto total del botón queda en ~32-34px (dominado por el ícono +
  padding vertical, que no cambia) — sigue por encima del mínimo de 24×24px de WCAG 2.5.5.
  El ancho mínimo (el botón más angosto sigue siendo "Código"/"Flujos"/"Tareas", ~41-42px de
  label + 26px de ícono/gaps/padding ≈ 67-70px) también queda cómodo por encima del mínimo.
- **Estado no-toggle de "Recuérdame algo" por canal semántico:** al no llevar
  `aria-pressed`, un lector de pantalla lo anuncia como botón simple (no como control de
  estado) — coherente con que no es un toggle. No hace falta ningún atributo ARIA adicional
  para comunicar "esto no es un modo": la ausencia de `aria-pressed` ya es la señal correcta
  (agregar `aria-pressed="false"` fijo, sin nunca pasar a `"true"`, sería confuso — implicaría
  falsamente que el botón admite dos estados).

---

## Fuera de alcance visual (sin cambios respecto al original, salvo lo ya señalado arriba)

- No se define el `id`/estructura de datos final de cómo "Recuérdame algo" se modela en el
  payload que arma `bridge.py` (si se funde en el catálogo de modos o sigue siendo
  `_QUICK_ACTIONS` con 1 entrada) — es de `orion-architect`, señalado en la sección 1.
- No se decide si `.chip` se retira del CSS al quedar sin consumidores en el composer — de
  `orion-dev`, mismo criterio que el código potencialmente muerto de `run_chip_action()`.
- No se agrega el símbolo `#ic-bell` al sprite — es fragmento ilustrativo para `orion-dev`.
- No se verifica el ancho real en navegador (sección 3) — estimación por cálculo, pendiente
  de confirmación visual real por `orion-dev`/`orion-tester`.

---

## Riesgos de regresión visual (nuevos o actualizados de este addendum)

| Riesgo | Mitigación |
|---|---|
| La estimación de ancho de la sección 3 está basada en conteo de caracteres, no en render real — puede quedar más ajustada o más floja de lo calculado | Margen de ~13% dejado a propósito + fallback documentado (acortar label a "Recordar") sin tener que volver a tocar padding/font-size de los 5 botones |
| Reducir `font-size` de 13px a 12.5px en los 4 `.mode-btn` ya implementados es un cambio visible, no solo en "Recuérdame algo" — podría leerse como una regresión menor de legibilidad si se compara pixel a pixel con la versión que Johan ya vio en la prueba manual | Es la misma diferencia que ya existe hoy entre `.mode-btn` (13px) y `.chip` (12.5px) — no es un tamaño nuevo en el sistema, es el tamaño que ya usaba el componente que se está retirando; visualmente coherente, no un tamaño improvisado |
| El ícono `#ic-bell` es un símbolo nuevo sin precedente visual en la app — puede no calzar perfectamente en densidad óptica con el resto a primera vista | Diseñado deliberadamente con la misma lógica de trazo que `ic-mic` (cuerpo + detalle, mismo aire en el `viewBox`) — mismo criterio de consistencia que ya se siguió al elegir los otros 4 íconos reusados |
| Al quedar `#quick-actions-row` eliminado, cualquier CSS que dependiera de su `margin-bottom: 10px` para el espaciado antes de `#composer-input-row` pierde esa referencia | `#actions-row` (contenedor único) hereda el `margin-bottom: 10px` que tenía `#quick-actions-row` (el más cercano al input) — así el input no se corre de lugar, mismo criterio que ya se aplicó al fusionar `#chips-row` en 2 filas en el diseño original |

---

## Estado: ⏸️ ESPERANDO VALIDACIÓN

Este addendum sigue siendo un rediseño visual real (elimina elementos del composer, cambia
el componente de "Recuérdame algo", ajusta el tamaño de un componente ya en producción) —
según el DoD de `orion-ui` requiere aprobación humana explícita antes de continuar a
`orion-dev`.

**Resumen para la aprobación:**
- Se elimina `#quick-actions-row` y los accesos "Captura de pantalla"/"Abrir navegador"
  desaparecen del composer (la capacidad del agente no se toca, solo el atajo de UI).
- "Recuérdame algo" deja de ser `.chip` y pasa a usar el mismo componente `.mode-btn` que
  los 4 modos (mismo tamaño/forma/tratamiento de ícono), pero sin `aria-pressed` ni estado
  activo — sigue siendo un click que prellena el texto, nada más.
- Los 5 elementos quedan en una sola fila (`flex-wrap: nowrap`), con un ajuste de tamaño
  (padding, font-size, gaps) que aplica a los 5 por igual — estimado con margen cómodo
  (~13%) dentro de los 760px del composer, pendiente de confirmación visual real.
- Ícono nuevo propuesto para "Recuérdame algo": `#ic-bell`, campana de trazo simple
  coherente con el resto del sprite — no hay ningún ícono existente reutilizable.
- Cero tokens de color nuevos — mismo sistema de diseño, ajuste puramente de tamaño y de
  un símbolo nuevo.

⚠️ El flujo no continúa hasta que Johan apruebe este addendum de diseño.
Responde: **APROBADO** / **AJUSTAR** [qué] / **RECHAZADO** [motivo]

---

## ✅ Aprobación de Johan (2026-09-07)
Johan aprobó este addendum tal como quedó redactado, sin AJUSTAR ni RECHAZADO. Ver
`REQ-026-context.md` para el registro de la decisión. Listo para `orion-dev` — el
coordinador lo lanza manualmente desde la conversación principal, sin auto-encadenar.
