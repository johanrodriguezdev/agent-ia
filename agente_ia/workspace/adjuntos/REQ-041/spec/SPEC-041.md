# SPEC-041 — Rediseño del icono de app y del icono de bandeja del sistema (Concepto A)

**Estado:** ✅ COMPLETADO (aprobada por el humano, 2026-09-12)
**Categoría:** UI
**Tipo:** MEJORA
**Fecha:** 2026-09-12

## Objetivo
Reemplazar el icono actual —generado por código con `QPainter`: un anillo grueso con un punto
centrado, en un único azul plano, apodado "mascota con auriculares"— por la marca ya aprobada
por el usuario en el canvas de diseño (Concepto A): tres anillos entrelazados de líneas finas
con degradado metálico blanco-gris alrededor de un nodo central, sobre fondo negro sólido. Aplica
al icono de la app de escritorio PyQt6 (ventana, barra de tareas, alt-tab) y al icono de la
bandeja del sistema de Windows, incluida la vista "mostrar iconos ocultos".

Beneficio para el usuario: la app deja de mostrar un icono genérico/infantil en todos los
lugares donde Windows la representa (barra de tareas, alt-tab, bandeja, "iconos ocultos") y pasa
a mostrar la identidad visual ya elegida — sin depender de texto ni del nombre actual de la app.

## Alcance
- Incluye:
  - El icono de la app en TODOS los tamaños que Windows pide hoy: 16/24/32/48/64/128/256 px
    (ventana, barra de tareas, alt-tab).
  - El icono de la bandeja del sistema (`QSystemTrayIcon`), incluida la vista "mostrar iconos
    ocultos", en la versión simplificada/monocroma de la referencia (16 y 24 px).
  - La geometría, colores y proporciones exactos extraídos del canvas aprobado (detallados
    abajo) — no hay margen de reinterpretación de la forma.
- No incluye:
  - Cambiar el nombre de la app ("Noddoo") ni ningún texto — el diseño aprobado no lleva texto
    ni logotipo tipográfico, así que este REQ no depende de esa decisión pendiente.
  - Rediseñar otros iconos de la interfaz (botones del webview, favicon interno, etc.) — solo el
    icono de app y el de bandeja de Windows.
  - Decidir el mecanismo de implementación (mantener el dibujo procedural con `QPainter` vs.
    pasar a un asset estático/vectorial). Es una decisión de `orion-architect`, no de esta SPEC.

## Especificación exacta del diseño aprobado
Fuente: canvas de diseño (`https://claude.ai/code/artifact/972fea5e-64f0-4598-acee-cb5c6b00136b`),
artboards `Main.dc.html` (Concepto A, ya aprobado) y `Contexto.dc.html` (referencia de la versión
de bandeja). Los valores son los del SVG real del canvas, no una reinterpretación.

### Icono de app (ventana / barra de tareas / alt-tab) — todos los tamaños
- Fondo: cuadrado de esquinas redondeadas, negro sólido `#0a0a0b`, radio de esquina proporcional
  (referencia del canvas: 54 px de radio sobre un lienzo de 240 px, ≈22.5% del lado).
- Marca: sobre `viewBox="0 0 200 200"`, centrada, ocupando ≈75% del lienzo del icono.
- Degradado metálico (`linearGradient`, `x1=20 y1=10 x2=180 y2=190`, `gradientUnits=userSpaceOnUse`):
  - 0% → `#ffffff`
  - 50% → `#b7b8bd`
  - 100% → `#5c5d63`
- Tres anillos, cada uno un círculo de radio `r=46` sobre el viewBox 200×200, trazo con el
  degradado anterior, `stroke-width=3.2`, `stroke-linecap=round`, dibujado como arco parcial
  (`stroke-dasharray="180 30"`) para lograr el efecto de anillos entrelazados:
  - Anillo 1: centro `(100, 76)`, `stroke-dashoffset=0`
  - Anillo 2: centro `(120.8, 112)`, `stroke-dashoffset=96`
  - Anillo 3: centro `(79.2, 112)`, `stroke-dashoffset=192`
  - Los tres centros forman un triángulo alrededor del centro del icono; el offset escalonado
    en 96 es lo que crea la sensación de anillos que se tejen entre sí (no son tres círculos
    completos superpuestos: cada uno es un arco con hueco).
- Nodo central: círculo RELLENO (no solo trazo) en `(100, 100)`, radio `r=8.5`, relleno con el
  mismo degradado metálico.
- Sin texto, sin logotipo tipográfico, sin forma de cubo, sin auriculares — el cubo que circuló
  durante la exploración de estilo fue solo referencia visual, nunca la forma final.

### Icono de bandeja del sistema (`QSystemTrayIcon`, incluida "mostrar iconos ocultos") — 16 y 24 px
Es una versión deliberadamente SIMPLIFICADA y MONOCROMA de la misma marca (no lleva el degradado
metálico), pensada para legibilidad al tamaño real de bandeja:
- Misma geometría de los tres anillos + nodo central (mismos centros/radios relativos al viewBox
  200×200), pero:
  - Trazo en color sólido `#f2f2f3` (blanco roto) — SIN degradado.
  - `stroke-width` más grueso en proporción al tamaño, para que no se pierda: `8` a 24 px, `10`
    a 16 px (sobre el mismo viewBox 200×200).
  - Nodo central proporcionalmente más grande: `r=10` a 24 px, `r=12` a 16 px.
  - Fondo: chip cuadrado de esquinas redondeadas, en un negro ligeramente más claro que el fondo
    del icono de app — `#1b1b1d` —, radio de esquina `5px` a 24px / `4px` a 16px.

## Comportamiento actual vs deseado
| Actual | Deseado |
|--------|---------|
| El icono se genera 100% por código con `QPainter` en `ui/webview/app_icon.py::dibujar()`. No existe ningún `.ico`/`.png` de icono en el repo. | El resultado visual debe ser exactamente el Concepto A (ver especificación exacta arriba). El mecanismo (mantener `QPainter` o pasar a asset estático/vectorial) lo decide `orion-architect`. |
| Diseño actual: un anillo simple + un punto centrado, sin degradado, color de acento plano `#58a6ff` (azul), sobre fondo TRANSPARENTE. | Tres anillos entrelazados con degradado metálico blanco-gris + nodo central, sobre fondo NEGRO SÓLIDO en el icono de app (ver especificación exacta). |
| El icono de la ventana/taskbar/alt-tab y el de la bandeja del sistema son literalmente el mismo objeto (`app_icon()` reutilizado en `main_window.py` para `setWindowIcon()` y para `tray_icon.setIcon()`). | El icono de bandeja usa la variante simplificada/monocroma (ver arriba), distinta del icono de app grande — deja de ser el mismo objeto reescalado. |
| El color se puede tintar por parámetro (`dibujar(size, color)`), pensado para que el nombre del agente cambiara sin recompilar. | El nuevo diseño no depende del nombre del agente (no lleva texto); ese parámetro deja de tener el propósito original. |
| `_TAMANOS = (16, 24, 32, 48, 64, 128, 256)` para todo. | Se mantienen esos tamaños para el icono de app; el de bandeja solo necesita 16 y 24 (los que Windows usa ahí). |

## Módulos afectados (identificados en el código actual)
- `ui/webview/app_icon.py` — único punto donde se genera el icono hoy: `dibujar()`, `app_icon()`,
  `_ACENTO`, `_TAMANOS`, `fijar_identidad_en_windows()`.
- `ui/webview/main_window.py`:
  - `~L72-76` — `setWindowIcon()` de la ventana principal y de `QApplication`.
  - `~L221-237` (`_setup_tray_icon()`) — construcción y `setIcon()` del `QSystemTrayIcon`.
- `tests/test_app_icon.py` — suite de regresión sobre el diseño ACTUAL (anillo+punto,
  transparencia, tamaños, "no es el cuadrado azul de antes"); varios casos describen la forma
  vieja y deben reescribirse para la forma nueva, no solo borrarse.
- `main.py` — orden de `fijar_identidad_en_windows()` antes de `QApplication(sys.argv)` (no se
  espera que cambie, pero está acoplado al mismo archivo y un test ya lo verifica).
- No existen hoy archivos `.ico`/`.png` de icono en el repo. Si `orion-architect` decide usar
  assets estáticos en vez de dibujo procedural, esos archivos serían nuevos, no reemplazos.

## Criterios de aceptación
- [ ] El icono de la ventana principal, la barra de tareas y el alt-tab de Windows muestran la
      marca del Concepto A (tres anillos entrelazados + nodo central, degradado metálico
      blanco-gris, fondo negro sólido) en todos los tamaños que usa Windows hoy
      (16/24/32/48/64/128/256 px), sin recortes ni deformación del aspecto 1:1.
- [ ] A ningún tamaño el icono de app muestra el diseño anterior (anillo simple + punto azul
      plano) ni ningún resto de auriculares/mascota.
- [ ] El icono de la bandeja del sistema usa la versión simplificada/monocroma de la marca
      (trazo sólido `#f2f2f3` sin degradado, sobre chip `#1b1b1d`) a 16 y 24 px — no es el mismo
      icono de app reescalado.
- [ ] En la vista "mostrar iconos ocultos" de Windows, la marca de bandeja se sigue reconociendo
      como los tres anillos + nodo, no como una mancha.
- [ ] El tooltip del icono de bandeja (`"{nombre del agente} — Panel de control"`) sigue
      funcionando sin cambios — este REQ no toca el nombre del agente ni el texto del tooltip.
- [ ] `fijar_identidad_en_windows()` se sigue ejecutando antes de crear la `QApplication` (sin
      regresión del agrupado en la barra de tareas de Windows).
- [ ] `tests/test_app_icon.py` se actualiza para describir y verificar la forma NUEVA: se
      conservan en espíritu las verificaciones que siguen aplicando (todos los tamaños
      presentes, legibilidad a 16 px — ni mancha ni casi vacío) y se corrige/quita la aserción
      de "fondo transparente" para el icono de APP (su fondo ahora es negro sólido a propósito);
      si la transparencia sigue aplicando en algún borde del chip de bandeja, debe decirlo
      explícitamente el test.
- [ ] `python -m pytest tests/test_app_icon.py --tb=short -v` pasa completo tras el cambio.
- [ ] No quedan referencias al color anterior (`_ACENTO = "#58a6ff"`) como color final del icono,
      salvo que `orion-architect` justifique reutilizarlo para otro propósito distinto al icono.

## Casos borde
- Barra de tareas de Windows en tema CLARO (no todos los usuarios usan tema oscuro): el chip
  oscuro del icono de bandeja (`#1b1b1d`) debe seguir siendo legible sobre un fondo claro. El
  canvas ya asume esta combinación (chip oscuro fijo, sin variante clara) — se confirma con el
  humano en la aprobación de esta SPEC si eso es aceptable tal cual o si se quiere que
  `orion-ui` revise ese caso antes de implementar.
- Modo alto contraste / accesibilidad de Windows: fuera de alcance de este REQ. Si `orion-qa`
  detecta que el icono se vuelve invisible en alto contraste, se reporta como hallazgo aparte,
  no bloquea este REQ.
- Multi-monitor con distinto DPI: los tamaños ya cubiertos (16 a 256) son los que Windows pide
  según escala; si el mecanismo elegido no es vectorial, verificar que no aparezcan tamaños
  intermedios borrosos.

## Asumidos (requieren confirmación explícita antes de aprobar)
- **ASUMIDO 1 — bandeja con variante propia:** el icono de bandeja (16/24 px) usa el diseño
  monocromo simplificado de la referencia (trazo plano `#f2f2f3` sobre chip `#1b1b1d`), DISTINTO
  del icono de app con degradado — no el mismo `app_icon()` reescalado, como es hoy. Es un
  cambio de comportamiento respecto al código actual (donde ambos son literalmente el mismo
  objeto). ¿Se confirma este criterio?
- **ASUMIDO 2 — mecanismo abierto:** esta SPEC no define si se mantiene el dibujo procedural con
  `QPainter` (redibujando arcos con degradado y patrón de guiones) o si se pasa a un asset
  vectorial/estático (SVG renderizado, o `.ico`/`.png` pre-generados desde el canvas). Queda
  para `orion-architect`. ¿Se confirma que esa decisión se deja abierta a arquitectura?
- **ASUMIDO 3 — parámetro de tinte dinámico:** el parámetro `color` de `dibujar()` (pensado
  originalmente para que el icono cambiara de color si cambiaba el nombre del agente) deja de
  tener el propósito original porque el nuevo diseño no depende del nombre ni lleva texto. No
  se exige eliminarlo como criterio de aceptación, pero si `orion-architect`/`orion-dev` lo
  eliminan no se considera fuera de alcance. ¿Hay planes de theming/color dinámico del icono a
  futuro que dependan de este parámetro y deban preservarse?
- **ASUMIDO 4 (heredado de `orion-coordinador`):** este REQ no se bloquea por la decisión
  pendiente sobre el nombre "Noddoo" — el diseño aprobado no lleva texto, así que aplica igual
  sin importar el nombre final del agente.
