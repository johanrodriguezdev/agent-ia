# Diseño UI REQ-041 — Icono de app y de bandeja del sistema (Concepto A)

**Estado:** ⏸️ ESPERANDO APROBACIÓN HUMANA (rediseño visual completo, no ajuste menor)
**Agente:** orion-ui
**Fecha:** 2026-09-14
**Insumos leídos:** `REQ-041-context.md`, `SPEC-041.md`, `propuestas/arquitectura-041.md`,
`ui/webview/theme.py`, `ui/webview/frontend/css/theme.css`, `ui/webview/frontend/css/icons.css`,
`ui/webview/app_icon.py`. No hay archivos en `origen/`: la referencia visual vive en el canvas
de diseño ya aprobado (`Main.dc.html` / `Contexto.dc.html`, artifact `972fea5e-...`), cuya
geometría exacta quedó transcrita literalmente en `SPEC-041.md`.

---

## Referencia analizada

Tres piezas, todas ya aprobadas por el humano en el canvas, ninguna abierta a reinterpretación
de forma:

1. **Icono de app (256 px, ventana/taskbar/alt-tab):** `viewBox 0 0 200 200`, tres anillos
   (`circle r=46`, `stroke-width=3.2`, `stroke-dasharray="180 30"`) centrados en `(100,76)` /
   `(120.8,112)` / `(79.2,112)` con `stroke-dashoffset` 0/96/192, trazados con un degradado
   metálico lineal (`#ffffff → #b7b8bd → #5c5d63`), más un nodo central relleno (`r=8.5`, mismo
   degradado). Contenedor: cuadrado `border-radius:54px` (sobre lienzo 240) fondo `#0a0a0b`.
2. **Icono de bandeja monocromático (16 y 24 px):** misma geometría angular de los tres
   anillos + nodo, pero trazo sólido `#f2f2f3` (sin degradado), más grueso (10 a 16px / 8 a
   24px) y nodo más grande (`r=12`/`r=10`), sobre chip `#1b1b1d` con esquinas redondeadas
   (`rx` 4/5).
3. **Mockup en contexto real:** chip de 20px sobre fondo `#141416` dentro de un flyout
   `#242426` ("mostrar iconos ocultos" de Windows), junto a la etiqueta de texto del nombre de
   la app. El nombre mostrado en el mockup ("Noddoo") es solo texto de ejemplo — esa decisión
   está en reconsideración aparte y no es parte de este diseño (el icono no lleva texto
   incrustado, así que no depende de ella).

Este documento no reabre ninguno de esos tres números: solo los contrasta contra el sistema de
diseño vivo del proyecto y especifica lo que la SPEC/arquitectura dejaron para `orion-ui`
(tokens, estados, accesibilidad, encuadre del descarte del cubo).

---

## Qué se adopta / qué se descarta

| Elemento de la referencia | Se adopta | Motivo |
|---|---|---|
| Geometría exacta de los 3 anillos + nodo (centros, radios, dasharray/dashoffset) | Sí, literal | Ya aprobada por el humano en el canvas y transcrita sin aritmética en `SPEC-041.md`/`arquitectura-041.md`; no hay margen de reinterpretación de forma |
| Degradado metálico `#ffffff → #b7b8bd → #5c5d63` en el icono de app | Sí | Coherente con la filosofía ya declarada del sistema de diseño (`theme.css`: "paleta neutra... grises sin tinte") — es una familia de grises, no introduce un tinte nuevo |
| Fondo negro sólido `#0a0a0b` en el icono de app | Sí | Ver "Tokens" — es una constante nueva, deliberadamente por fuera de `theme.py`/`theme.css` (ver justificación), pero coherente en valor con `--bg-primary` del tema oscuro (`#0c0d0f`) |
| Variante monocromática obligatoria para bandeja (`#f2f2f3` sólido, sin degradado) | Sí | Requisito técnico de legibilidad a 16-24px ya fijado en la SPEC — un degradado a ese tamaño se percibe como mancha, no como marca |
| Geometría del logo "Mindcube" que inspiró la exploración de estilo (forma de cubo) | **No** | Nunca fue la forma final — fue solo la referencia que inspiró el *lenguaje visual* (trazo fino, degradado metálico, fondo negro sólido). La forma final —tres anillos entrelazados— ya estaba decidida y aprobada antes de que este agente entrara al flujo (ver contexto, decisión de `orion-coordinador` del 2026-09-12). Se documenta acá para que quede explícito el motivo, no solo el hecho: se adoptó el tratamiento de superficie (metal pulido sobre negro, líneas finas con `round cap`), se descartó la geometría cúbica porque los anillos entrelazados comunican mejor la idea de "conexión"/"agente" que una caja cerrada, y porque ya había pasado por aprobación humana como Concepto A independiente |
| Nombre de la app como parte del icono | No | El diseño aprobado no lleva texto ni logotipo tipográfico; el nombre ("Noddoo", en reconsideración) es contenido de la etiqueta junto al icono en el flyout de Windows, no del icono mismo — fuera de alcance de este REQ por diseño, no por omisión |
| Riesgo de legibilidad a 16px del icono de APP (con degradado) ya documentado por arquitectura | Se documenta como estado/contexto, no se replantea | El humano ya aprobó la arquitectura con este riesgo conocido (~0.8% de píxeles distinguibles del fondo a 16px literales) — no es una pregunta abierta para este agente. Se retoma en "Accesibilidad" solo para completar la revisión de contraste que corresponde a este paso, no para bloquear |

---

## Tokens (nuevos y reutilizados)

**Decisión de encuadre, antes de la tabla:** estos colores **no se agregan a `theme.py` /
`theme.css`**. Esos dos archivos son la fuente de verdad de la paleta del *webview* — el
contenido HTML/CSS que corre dentro de la ventana, donde sí existe un `data-theme` claro/oscuro
consultable en tiempo real. El icono de app y el de bandeja los pinta **Windows**, fuera de la
ventana (barra de tareas, alt-tab, bandeja, flyout de "iconos ocultos"), en un contexto que no
tiene tema claro/oscuro que consultar — exactamente la misma razón por la que el código actual
ya declara `_ACENTO = "#58a6ff"` como constante propia en `app_icon.py` en vez de importarlo de
`theme.py` (ver docstring actual del archivo). La arquitectura aprobada mantiene ese mismo
patrón: las nuevas constantes de color viven como literales Python dentro de
`ui/webview/app_icon.py` (`_APP_BG`, `_TRAY_BG`, `_TRAY_STROKE`, paradas del gradiente), no
como CSS. Por lo tanto **no aplica** el chequeo de drift `theme.py`↔`theme.css` a estos colores
— ese test (`tests/test_webview_theme.py`) cubre la paleta del webview, no la del icono de
sistema, y este REQ no lo toca.

Dicho esto, sí importa que no introduzcan una paleta desconectada del resto de la app — la
tabla siguiente contrasta cada color nuevo contra el token del webview más cercano, para dejar
constancia de que la decisión es coherente, no accidental:

| Color (constante en `app_icon.py`, no CSS) | Valor | Uso | Token de webview más cercano | ¿Drift? |
|---|---|---|---|---|
| `_APP_BG` (nuevo) | `#0a0a0b` | Fondo del icono de app | `--bg-primary` (dark) = `#0c0d0f` | No — mismo rango tonal (negro casi puro), deliberadamente un poco más oscuro para que la marca "flote" sobre cualquier taskbar real, que rara vez es tan oscura como `--bg-primary` |
| `_TRAY_BG` (nuevo) | `#1b1b1d` | Fondo del chip de bandeja | `--bg-hover` (dark) = `#1f2226` | No — mismo rango tonal, ligeramente más oscuro; ya está fijado y aceptado por SPEC-041 ("caso borde... aceptable tal cual, fijo en `#1b1b1d`") |
| `_TRAY_STROKE` (nuevo) | `#f2f2f3` | Trazo/nodo del icono de bandeja | `--text-primary` (dark) = `#e8eaed` | No — mismo rol (texto/marca sobre fondo oscuro), un punto más claro por necesidad de legibilidad a 16px, no por inconsistencia |
| Gradiente metálico — parada 0% (nuevo) | `#ffffff` | Icono de app | `--bg-primary` (light) = `#ffffff` | No — mismo valor exacto, casualidad de paleta neutra, no un préstamo funcional |
| Gradiente metálico — parada 50% (nuevo) | `#b7b8bd` | Icono de app | Sin equivalente directo en `theme.css` (la paleta del webview no tiene un gris medio ahí) | No — es gris sin tinte, coherente con "paleta neutra a propósito" que ya declara `theme.css` en su comentario de cabecera |
| Gradiente metálico — parada 100% (nuevo) | `#5c5d63` | Icono de app | Sin equivalente directo | No — mismo criterio que la parada anterior; ver "Accesibilidad" para el contraste de este extremo, que es el punto más débil de la marca |
| Mockup de contexto — fondo del flyout `#242426` / chip visible `#141416` | — | Solo referencia, no se implementa | — | **No aplica a este REQ**: el flyout "mostrar iconos ocultos" lo dibuja Windows, no la app — se documenta acá únicamente para que quede constancia de que el chip `#1b1b1d` se verificó contra ese contexto real (ver Accesibilidad), no para que `orion-dev` intente estilizar el flyout del sistema operativo, algo que no es controlable desde `QSystemTrayIcon` |
| Color anterior `_ACENTO = "#58a6ff"` | — | Eliminado | `--text-accent` (dark) | Se descarta sin reemplazo — ya confirmado en ASUMIDO 3 de `SPEC-041.md`, aprobado por el humano |

**Cero tokens nuevos en `theme.py`/`theme.css`.** Todos los colores de este REQ son literales
propios de `app_icon.py`, tal como decidió `orion-architect`. No hay ninguna acción pendiente
para `orion-dev` sobre esos dos archivos del sistema de diseño del webview.

---

## Layout

No aplica layout en el sentido de columnas/paneles (no es una pantalla) — lo que sí corresponde
especificar acá es el encuadre geométrico de cada pieza, en términos del propio SVG que arma
`arquitectura-041.md`, para que `orion-dev` no tenga que interpretar proporciones:

- **Icono de app:** lienzo cuadrado 1:1 en todos los tamaños de `_TAMANOS` (16 a 256). La marca
  (viewBox nativo 200×200) se centra y escala al 90% del lienzo (`scale(0.9)` + `translate(30,30)`
  sobre un lienzo de 240), dejando un margen uniforme de ~5% por lado antes del `border-radius`
  de la esquina — ya definido en la arquitectura, no se ajusta acá.
- **Icono de bandeja:** lienzo cuadrado 1:1 en 16 y 24 px. El chip de fondo usa el espacio final
  en píxeles (`rx` 4 a 16px, `rx` 5 a 24px, literal, sin escalar); la marca vive en su espacio
  nativo 200×200 escalado a `size/200` — mismo doble sistema de coordenadas que ya resolvió
  `orion-architect` para no perder precisión en un tamaño tan chico. No hay margen adicional que
  especificar: la marca ocupa el 100% del espacio nativo dentro del chip, tal como la aprobó el
  humano en el canvas (a diferencia del icono de app, la versión de bandeja no deja aire extra
  porque a 16-24px cada píxel de trazo cuenta para la legibilidad).
- **Sin breakpoints.** Ninguna de las dos piezas es responsive — Windows pide un tamaño fijo
  discreto de una lista cerrada (`_TAMANOS` / `_TRAY_TAMANOS`), no hay ventana que redimensionar.

---

## Componentes

### Icono de app (`dibujar_app(size)` → `app_icon()`)

Es un icono **estático de sistema**, no un control interactivo — Windows lo pinta en la barra
de tareas, alt-tab y la ventana. No hay ningún estado que la app controle o dibuje distinto:

| Estado | ¿Aplica? | Nota |
|---|---|---|
| Default (único estado real) | Sí | Degradado metálico + 3 anillos + nodo sobre fondo `#0a0a0b`, en todos los tamaños de `_TAMANOS` |
| Hover / focus / active | No aplica | Windows puede dibujar un realce de fondo alrededor del botón de la taskbar al pasar el mouse, pero ese realce lo pinta el shell del sistema operativo, no el `QIcon` — la app no tiene ningún gancho para cambiar el dibujo del icono en ese momento, y no debe intentarlo |
| Disabled | No aplica | No existe un estado "deshabilitado" para el icono de una ventana |
| Loading | No aplica | El icono se genera una sola vez al construir el `QIcon` (todos los tamaños de una vez); no hay una version "cargando" intermedia visible al usuario |
| Error | No aplica en el sentido de UI (ver "Riesgos de regresión visual" para el caso de fallo de renderizado SVG, que es un problema de arquitectura/dev, no un estado de diseño) | — |

Archivo: no hay CSS — vive como string SVG embebido en `ui/webview/app_icon.py`
(`_app_icon_svg()`), fuera del árbol `ui/webview/frontend/css/`.

### Icono de bandeja (`dibujar_bandeja(size)` → `bandeja_icon()`)

También estático, con una particularidad: tiene que verse igual de reconocible en **dos
contextos de fondo distintos** que Windows controla, no la app — la bandeja visible
(generalmente sobre la barra de tareas) y el flyout "mostrar iconos ocultos" (`#242426` en el
mockup de referencia). No es un estado que la app dibuje: es el mismo pixmap mostrado por
Windows sobre dos fondos distintos.

| Estado | ¿Aplica? | Nota |
|---|---|---|
| Default (único estado real, monocromo) | Sí | Trazo sólido `#f2f2f3` sin degradado + nodo, sobre chip `#1b1b1d`, a 16 y 24 px — es la ÚNICA variante que existe, no hay una "versión con degradado" de bandeja |
| Visible en bandeja principal vs. en flyout "iconos ocultos" | Aplica como contexto de fondo, no como variante de dibujo | Mismo pixmap exacto en ambos casos (`bandeja_icon()` no sabe ni le importa en cuál de los dos lo está mostrando Windows) — verificado en "Accesibilidad" que el contraste se sostiene en los dos fondos reales del mockup (`#1b1b1d` propio del chip y `#141416`/`#242426` del entorno) |
| Hover / focus / active | No aplica | Mismo motivo que el icono de app: el realce al pasar el mouse sobre la bandeja lo pinta el shell de Windows, no `QSystemTrayIcon` |
| Disabled | No aplica | Un icono de bandeja no tiene estado deshabilitado — si la app no quiere mostrarlo, lo quita (`hide()`), no lo atenúa |
| Loading / Error | No aplica | Mismo criterio que el icono de app — generación única, sin estado intermedio visible |

Archivo: tampoco hay CSS — vive como string SVG embebido en `ui/webview/app_icon.py`
(`_tray_icon_svg(size)`).

**Conclusión de esta sección, explícita porque el DoD la pide:** ninguno de los dos componentes
tiene el set completo de estados interactivos (hover/focus/active/disabled/loading/error) que sí
aplican a los controles del webview (ver `icons.css` → `.icon-btn:hover/:active/:focus-visible/
:disabled`). Es correcto que no los tengan: son iconos de sistema operativo, no botones de la
interfaz. Inventar esos estados sería documentar algo que Windows no permite controlar.

---

## Accesibilidad

Revisión de contraste WCAG (criterio 1.4.11, *Non-text Contrast* — 3:1 mínimo para objetos
gráficos/marca, no el 4.5:1 de texto, porque ninguna de las dos piezas es texto):

| Par | Contraste calculado | ¿Pasa 3:1? | Nota |
|---|---|---|---|
| Trazo bandeja `#f2f2f3` sobre chip `#1b1b1d` (16-24px) | **≈15.4:1** | Sí, con amplio margen | Muy por encima incluso del 4.5:1 de texto — el trazo grueso (8-10) más el color casi blanco puro lo garantizan |
| Trazo bandeja `#f2f2f3` sobre fondo de contexto `#141416` (mockup, bandeja principal) | **≈16.4:1** | Sí, con amplio margen | Verificado también contra el fondo real del mockup, no solo el chip propio |
| Icono de app, parada más clara del degradado `#ffffff` sobre fondo `#0a0a0b` | Contraste muy alto (~20:1) | Sí | Sin riesgo |
| Icono de app, parada intermedia `#b7b8bd` sobre fondo `#0a0a0b` | **≈10:1** | Sí | Sin riesgo |
| Icono de app, parada más oscura del degradado `#5c5d63` sobre fondo `#0a0a0b` | **≈3.0:1** | **Al límite, pasa por muy poco** | Es el punto más débil de la marca: donde el degradado toca su extremo oscuro, el trazo (3.2px de ancho, más fino que el de bandeja) queda casi en el piso del umbral no-textual. No se ajusta el color — la SPEC fija el degradado exacto y ya fue aprobado — se deja documentado como hallazgo, junto al riesgo ya conocido de arquitectura (legibilidad a 16px), porque ambos apuntan al mismo punto de fragilidad: el extremo oscuro del degradado en el icono de app es la zona más comprometida de todo el diseño, no una preocupación nueva |

**Foco visible por teclado:** no aplica — ninguna de las dos piezas es un control enfocable; son
representaciones pasivas que Windows dibuja (icono de ventana, icono de bandeja). No hay
`:focus-visible` que especificar.

**Tamaño mínimo de área clicable:** no aplica al dibujo del icono en sí (lo controla el área del
botón de bandeja/taskbar, que ya cumple los mínimos de Windows por ser un componente nativo del
shell) — fuera del alcance de este REQ, que solo reemplaza el contenido visual, no el contenedor
interactivo.

**Conclusión de accesibilidad:** ambas piezas pasan el umbral de contraste no-textual en todos
los pares relevantes. El único punto señalado (extremo oscuro del degradado del icono de app,
≈3.0:1) es aceptable porque pasa el umbral aplicable, pero queda documentado explícitamente para
que `orion-qa`/el humano lo tengan presente junto con el riesgo de legibilidad a 16px ya conocido
— no se traduce en un bloqueo ni en un ajuste de color no autorizado.

---

## Fuera de alcance visual

- Geometría del cubo "Mindcube": no se retoma ni se documenta como alternativa — fue descartada
  antes de este paso, se deja constancia en "Qué se adopta/descarta" solo por completitud del
  historial.
- Estilizar el flyout "mostrar iconos ocultos" de Windows (`#242426` del mockup) o el fondo de
  bandeja real (`#141416`): son chrome del sistema operativo, no de la app — no hay ningún
  archivo del proyecto que los controle.
- Cualquier variante de tema claro para el chip de bandeja (`#1b1b1d` fijo): ya resuelto como
  caso borde aceptado en `SPEC-041.md`, no se reabre acá.
- Texto/etiqueta del nombre de la app junto al icono en el flyout de bandeja: es contenido de
  Windows (la etiqueta que el propio sistema operativo pinta al lado del icono en "iconos
  ocultos"), no un elemento que este REQ dibuje o pueda estilizar.
- Modo alto contraste / accesibilidad extendida de Windows: ya marcado fuera de alcance en
  `SPEC-041.md` ("Casos borde"), no se reabre.
- Cualquier ajuste de color a las tres paradas del degradado o al trazo/nodo de bandeja para
  mejorar el contraste del hallazgo de accesibilidad arriba: la geometría y color son de la SPEC
  aprobada, ajustarlos no es una decisión de `orion-ui`.

---

## Riesgos de regresión visual

| Riesgo | Mitigación |
|---|---|
| El extremo oscuro del degradado (`#5c5d63`) queda al límite del contraste no-textual (≈3.0:1) sobre el fondo del icono de app | Documentado arriba; no se ajusta el color (fuera de la autoridad de este paso). Si `orion-qa`/el humano lo consideran insuficiente en la prueba manual final, vuelve como ajuste de color a una nueva ronda de SPEC/arquitectura, no se resuelve en `orion-dev` por su cuenta |
| A 16px literales, el icono de APP (con degradado, trazo 3.2) es casi indistinguible del fondo negro (~0.8% de píxeles distintos, ya medido por `orion-architect`) | Ya aceptado como riesgo conocido por el humano al aprobar la arquitectura; se repite acá solo como contexto de por qué el icono de bandeja (que sí necesita leerse a 16-24px) usa la variante monocroma de trazo más grueso en vez de reutilizar el dibujo de app escalado — es precisamente la razón de diseño detrás de tener dos piezas distintas |
| Si `QSvgRenderer` no soporta bien `stroke-dasharray`/gradientes en algún entorno de build distinto al validado (Qt 6.11.0) | Ya señalado por `orion-architect` como riesgo de arquitectura, no de diseño — se mantiene la recomendación de que `orion-dev` repita la verificación empírica si el entorno de distribución final usa otra versión de Qt |
| El chip de bandeja (`#1b1b1d`) es fijo, sin variante para taskbar en tema claro de Windows | Ya aceptado como caso borde resuelto en `SPEC-041.md` — el trazo `#f2f2f3` sobre `#1b1b1d` mantiene su propio contraste alto (≈15.4:1) independientemente del tema de Windows alrededor, así que el chip se sigue viendo bien incluso si el entorno cambia; el riesgo real sería solo estético (un chip oscuro "flotando" sobre una taskbar clara), no de legibilidad |
| Confusión visual entre el nuevo icono y el anterior (anillo simple + punto azul) durante la transición si algún caché de Windows conserva el icono viejo | Riesgo operativo, no de diseño — corresponde a `orion-tester`/`orion-qa` verificar que Windows no esté mostrando un icono cacheado tras el cambio, no a este documento |

---

## Conclusión: esto es un rediseño, no un ajuste menor

Aunque la geometría y los colores ya vienen aprobados literalmente desde el canvas, este REQ
reemplaza **por completo** la marca visual de la app en cada lugar donde Windows la muestra
(ventana, taskbar, alt-tab, bandeja, iconos ocultos) — de un anillo simple azul plano a una
marca de tres anillos entrelazados con degradado metálico sobre negro. Es un cambio de
identidad de marca completo, no un ajuste de spacing/color puntual sobre un componente
existente. Por DoD de `orion-ui`, esto **requiere aprobación humana explícita separada** antes
de continuar a `orion-dev`, aunque la geometría en sí ya haya sido aprobada en el canvas — la
aprobación de este documento es sobre el contraste contra el sistema de diseño vivo, los tokens
(o su ausencia deliberada), los estados (o su ausencia justificada) y el hallazgo de
accesibilidad del extremo oscuro del degradado, ninguno de los cuales estaba cerrado todavía.

**El REQ queda esperando esa aprobación — no avanza a `orion-dev` por su cuenta.**

Resumen para la aprobación:
- Qué cambia visualmente: el icono de la app (ventana/taskbar/alt-tab) y el de la bandeja del
  sistema pasan del anillo azul plano actual al Concepto A ya visto en el canvas — tres anillos
  entrelazados con degradado metálico sobre negro (icono de app) y su variante monocroma
  simplificada (icono de bandeja).
- Tokens nuevos: 0 en `theme.py`/`theme.css` (por diseño — son constantes propias de
  `app_icon.py`, fuera del sistema de tema del webview, con la misma razón que ya usaba
  `_ACENTO`); 6 colores nuevos como literales Python (`_APP_BG`, 3 paradas del gradiente,
  `_TRAY_BG`, `_TRAY_STROKE`).
- Componentes afectados: 2 (icono de app, icono de bandeja), ambos estáticos, sin estados
  interactivos aplicables.
- Hallazgo de accesibilidad a tener presente (no bloqueante): el extremo oscuro del degradado
  del icono de app pasa el umbral de contraste no-textual por muy poco (~3.0:1 sobre 3:1
  mínimo).
