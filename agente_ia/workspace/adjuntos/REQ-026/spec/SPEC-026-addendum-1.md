# SPEC-026 — Addendum 1 (cambio de alcance post-QA, durante prueba manual)

**Estado:** ✅ APROBADO — Johan confirmó sin ajustes (2026-09-07, ver `REQ-026-context.md`)
**Fecha:** 2026-09-07
**Se aplica sobre:** `SPEC-026.md` (aprobada), ya implementada, testeada y auditada
(`EN_QA`, veredicto ✅ COMPLETADO de `orion-qa`, pendiente solo de la prueba manual de Johan).

## Motivo
Durante la prueba manual — viendo la barra del composer ya implementada en la app real,
captura adjunta — Johan pidió un cambio de alcance que **contradice explícitamente** dos
criterios de aceptación ya aprobados en `SPEC-026.md` y el layout ya aprobado en
`propuestas/ui-design-026.md`. Este addendum documenta el cambio, deroga los criterios
afectados y define los nuevos criterios testeables. No se reescribe `SPEC-026.md` desde
cero — todo lo demás de la SPEC original (modos, ruteo por `tarea`, persistencia,
accesibilidad, criterios de Tareas/Investigación/Código/Flujos) sigue vigente sin cambios.

## Pedido textual de Johan
> "quiero que queden solo las opciones de arriba y recuerdame algo pero el recuerdame algo
> con un icono como los otros y el mismo estilo que ocupen todos la misma fila y no quede
> uno en salto, entonces quita Captura de pantalla y abrir el navegador"

("las opciones de arriba" = los 4 `.mode-btn`: Código/script, Investigación, Nodos/flujos,
Tareas, visibles en la captura como fila superior.)

---

## Qué cambia respecto a `SPEC-026.md` aprobada

### 1. Catálogo — se eliminan 2 de los 3 accesos rápidos
`_QUICK_ACTIONS` deja de tener 3 entradas y pasa a tener 0 entradas propias: su única
entrada superviviente ("Recuérdame algo") se fusiona visualmente con la fila de modos (ver
punto 2). "📷 Captura de pantalla" y "🌐 Abrir navegador" se eliminan del composer.

**Aclaración de alcance (interpretación de esta SPEC, no repreguntada a Johan por ser
directa y no ambigua):** esto es exclusivamente sacar el botón/acceso directo de la barra
del composer. NO implica:
- Eliminar las tools `take_screenshot`/`open_browser` de `agents/tool_registry.py` ni su
  clasificación en `security_manager.py` — el agente sigue pudiendo tomar una captura o
  abrir el navegador si el usuario lo pide por texto/voz, exactamente igual que hoy.
- Tocar `run_chip_action()` como mecanismo — solo deja de tener invocantes desde estos 2
  botones específicos del composer (puede quedar sin uso si no lo llama nada más; no es
  este addendum el que decide si se elimina el código muerto o se deja, eso es criterio de
  `orion-architect`/`orion-dev` al implementar).

### 2. Estilo — "Recuérdame algo" dejará de ser un `.chip`
Pasa a compartir el mismo componente visual que los 4 `.mode-btn` (mismo tamaño, mismo
padding, mismo peso tipográfico, mismo tratamiento de borde/fondo/hover/foco, con ícono del
sprite igual que los otros 4 — ver punto 4). Deja de usar la píldora `.chip`
(`--radius-pill`) que usaba hasta ahora.

**Lo que NO cambia de su comportamiento** (es un cambio de estilo, no de función):
sigue siendo `kind="template"`, `payload="Recuérdame que "` — al hacer click sigue
prellenando el input exactamente igual que hoy. NO se convierte en un modo: no tiene
estado activo/toggle, no lleva `aria-pressed`, no queda "resaltado" tras el click, no
prioriza ninguna skill ni fija `tarea`. El REQ-026 original ya distinguía claramente
"modo" (toggle con estado persistente) de "acceso rápido" (acción puntual) — ese contrato
de comportamiento sigue en pie; solo el *contenedor visual* se unifica.

### 3. Layout — una sola fila para los 5 elementos, sin salto de línea
Se elimina la separación en dos filas (`#modes-row` arriba / `#quick-actions-row` abajo)
que definía `ui-design-026.md` (aprobado). Los 5 elementos (4 modos + "Recuérdame algo")
deben quedar en una única fila, todos con el mismo peso visual, sin que ninguno caiga a una
segunda línea por desborde del contenedor.

La solución técnica exacta (un solo contenedor con `flex-wrap: nowrap`, ajuste de
`padding`/`gap`/tamaño de fuente para que 5 elementos entren en `--content-max: 760px`,
o cualquier otro mecanismo) queda para `orion-ui`/`orion-dev` — este addendum fija el
resultado observable, no la implementación. Si técnicamente 5 elementos con el ancho actual
de `.mode-btn` no entran sin salto en 760px de ancho, `orion-ui` debe ajustar
padding/gap/tamaño de fuente del componente compartido hasta que entren — no se acepta
como excepción válida un salto de línea con menos de 5 elementos en la fila visible.

### 4. Ícono para "Recuérdame algo" — abierto para `orion-ui`
Se revisó el sprite de íconos existente (`ui/webview/frontend/index.html`, símbolos
`#ic-*`) buscando uno semánticamente coherente con "recordatorio": no hay ningún ícono de
campana/reloj/nota en el set actual (`ic-terminal`, `ic-tasks`, `ic-flows`, `ic-folder`,
`ic-settings`, `ic-search`, `ic-plus`, `ic-panel-left`, `ic-paperclip`, `ic-mic`, `ic-send`,
`ic-sun`, `ic-moon`, `ic-minimize`, `ic-maximize`, `ic-close`, `ic-play`, `ic-alerta`,
`ic-check`, `ic-info`, `ic-copiar`, `ic-stop`, `ic-lapiz`, `ic-chevron`, `ic-cpu`,
`ic-trash`). `ic-alerta` es un triángulo de advertencia (no una campana) — reusarlo para
"recordatorio" confundiría al usuario haciéndole pensar que es una alerta/advertencia, no
un recordatorio; se descarta explícitamente como opción. No hay ningún ícono existente que
sea un buen fit semántico.

Queda abierto para `orion-ui`: agregar un símbolo nuevo al sprite (p. ej. una campana o un
reloj — coherente con el resto del set, trazo lineal `currentColor`, mismo `viewBox="0 0
24 24"`) es la opción más probable dado que no hay reuso semánticamente correcto
disponible. `orion-ui` decide el símbolo final; no es una asunción de esta SPEC.

---

## Criterios de aceptación — derogados de `SPEC-026.md`

Sección "Catálogo y convivencia" de `SPEC-026.md`, quedan **derogados y reemplazados** por
los criterios nuevos de más abajo:
- ~~"'📷 Captura de pantalla' y '🌐 Abrir navegador' siguen disponibles como accesos
  rápidos fuera de la fila de modos, y su comportamiento... no cambia"~~
- ~~"'Recuérdame algo' sigue disponible como acceso rápido suelto (prellena el input, mismo
  comportamiento `kind="template"` actual)"~~ — se reemplaza por una versión que preserva el
  comportamiento pero no el estilo/contenedor (ver CA nuevo abajo).

El resto de los criterios de `SPEC-026.md` (persistencia/estado de modo, modo Tareas,
ruteo de modelo, casos borde, accesibilidad del estado activo de los modos) **no cambian**
y siguen vigentes tal cual.

## Criterios de aceptación — nuevos (addendum 1)

**Catálogo final**
- [ ] La barra del composer muestra exactamente 5 elementos, ni uno más: los 4 modos
  (Código/script, Investigación, Nodos/flujos, Tareas) + "Recuérdame algo".
- [ ] "📷 Captura de pantalla" y "🌐 Abrir navegador" ya no aparecen en ningún lugar del
  composer (ni fila de modos ni fila de accesos rápidos — la fila de accesos rápidos deja
  de existir como sección visualmente separada).
- [ ] El agente sigue pudiendo ejecutar `take_screenshot` y `open_browser` cuando el
  usuario lo pide por texto o voz (sin regresión de la capacidad, solo del atajo de UI) —
  verificable con las tools de `agents/tool_registry.py` sin cambios de clasificación en
  `security_manager.py`.

**Estilo unificado de "Recuérdame algo"**
- [ ] "Recuérdame algo" usa el mismo componente visual que los 4 `.mode-btn` (mismo
  tamaño, padding, tipografía, tratamiento de borde/fondo en reposo/hover/foco, con ícono a
  la izquierda del label igual que los otros 4).
- [ ] "Recuérdame algo" NO adopta el comportamiento de modo: no tiene estado
  activo/toggle, no lleva `aria-pressed`, no queda resaltado tras hacer click, no prioriza
  ninguna skill ni fija `tarea` para el ruteo de modelo.
- [ ] Click en "Recuérdame algo" prellena el input con el mismo `payload` de siempre
  ("Recuérdame que "), comportamiento `kind="template"` sin cambios.
- [ ] "Recuérdame algo" muestra un ícono del sprite (nuevo o reusado, a definir por
  `orion-ui`) coherente en trazo/estilo con los 4 íconos de modo — no queda sin ícono ni
  con el emoji que tenía antes cualquiera de los 2 accesos eliminados.

**Layout — una sola fila**
- [ ] Los 5 elementos (4 modos + "Recuérdame algo") se renderizan en una única fila
  horizontal, sin que ninguno caiga a una segunda línea por desborde, en el ancho de
  ventana estándar de la app (`--content-max: 760px`).
- [ ] Los 5 elementos tienen el mismo peso visual entre sí (mismo componente, mismo
  tamaño) — no hay jerarquía visual "modos vs. accesos rápidos" como en el diseño anterior,
  porque ya no queda ningún acceso rápido con menos peso.
- [ ] El contenedor `#quick-actions-row` (o su equivalente) deja de existir como fila
  separada; queda un único contenedor para los 5 elementos (el nombre final del/de los
  `id` del contenedor lo decide `orion-architect`/`orion-ui` al implementar, no es materia
  de esta SPEC).

---

## Impacto en trabajo ya hecho (para el resto del pipeline)

- **`propuestas/ui-design-026.md` (orion-ui, aprobado):** su sección "Layout" (contenedor
  dividido en `#modes-row`/`#quick-actions-row`) y su tabla "Qué se adopta / qué se
  descarta" (fila "Accesos rápidos con menos protagonismo") quedan obsoletas por este
  addendum — requiere una revisión de `orion-ui` antes de volver a `orion-dev`, no una
  reescritura completa (los tokens de color/tipografía, el patrón de accesibilidad AA y
  la tabla de íconos de los 4 modos siguen vigentes sin cambios).
- **`propuestas/arquitectura-026.md` (orion-architect, aprobado):** si `_QUICK_ACTIONS`
  desaparece como catálogo con 3 entradas y "Recuérdame algo" pasa a vivir junto a los 4
  modos en el mismo payload/fila, puede haber un ajuste de forma en cómo `bridge.py` arma
  y emite el payload al frontend (p. ej. si "Recuérdame algo" se modela como un 5to ítem
  de un catálogo unificado, o si sigue siendo una entrada de `_QUICK_ACTIONS` con 1 sola
  fila pero renderizada junto a los modos). Ese detalle de modelado de datos queda para
  que `orion-architect` lo confirme o ajuste — no lo decide este addendum.
- **Implementación ya hecha por `orion-dev`, testeada por `orion-tester` y auditada por
  `orion-qa`:** queda con una regresión pendiente conocida y esperada — los 3 tests/CA que
  cubrían el catálogo de 3 accesos rápidos y el layout de 2 filas van a quedar
  desactualizados contra este addendum y deben reescribirse cuando el REQ vuelva a
  `orion-dev`/`orion-tester`, igual que ya pasó una vez en este mismo REQ con
  `test_webview_bridge.py` durante la implementación original.

## Asumidos de este addendum
- ASUMIDO: el orden final de los 5 elementos es Código → Investigación → Nodos/flujos →
  Tareas → Recuérdame algo (mismo orden de los 4 modos ya fijado, con "Recuérdame algo"
  al final) — es la lectura más directa del pedido de Johan ("las opciones de arriba y
  recuérdame algo", en ese orden), pero el orden exacto no es una decisión funcional
  crítica; `orion-ui` puede ajustarlo si hay una razón visual de peso sin que esto
  requiera volver a pasar por aprobación de SPEC.
- ASUMIDO: "el mismo estilo que los otros" se refiere pixel/estilo (tamaño, tipografía,
  tratamiento de estados, forma del contenedor), no a que "Recuérdame algo" se comporte
  como un modo — Johan solo mencionó estilo/ícono/fila en su pedido, no mencionó que deba
  tener estado activo ni priorizar ninguna capacidad. Confirmar explícitamente en la
  pregunta de aprobación de abajo, porque es la única lectura del pedido con algo de
  ambigüedad real.

---

## Pregunta de confirmación

Johan — antes de que el flujo siga (vuelve a `orion-ui` para actualizar el diseño visual y
después a `orion-dev` para el ajuste de implementación), confirmame una sola cosa para no
repreguntarte todo lo demás que ya fue directo y claro:

**"Recuérdame algo" queda con el MISMO estilo visual que los botones de modo (tamaño,
forma, ícono) pero sigue funcionando igual que hoy — un click y prellena el texto, sin
quedar "activado"/resaltado como los modos ni prioritizar ninguna capacidad. ¿Correcto, o
también querés que se comporte como un modo (con estado activo)?**

Responde: **APROBADO** (confirma la lectura de arriba, sin más cambios) / **AJUSTAR**
[qué] / **RECHAZADO** [motivo].

⚠️ El flujo no continúa hasta que apruebes este addendum.

---

## ✅ Aprobación de Johan (2026-09-07)
Johan confirmó: "'Recuérdame algo' queda solo con el mismo estilo visual que los modos,
pero sigue funcionando como acceso rápido simple (prellena texto, sin estado activo ni
prioriza nada) — tal como quedó redactado en el addendum, sin ajustes." APROBADO sin
AJUSTAR ni RECHAZADO. Ver `REQ-026-context.md` para el registro de la decisión.
