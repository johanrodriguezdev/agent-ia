# Contexto REQ-041 — Rediseño de icono de app y bandeja del sistema

## Resumen ejecutivo
Reemplazar el icono actual (círculo grueso tipo mascota con auriculares) por el Concepto A ya
aprobado por el usuario en un canvas de diseño: una marca geométrica de líneas finas con
degradado metálico blanco-gris sobre fondo negro sólido, formada por tres anillos entrelazados
alrededor de un nodo central. Sin texto, sin auriculares, sin cubo. Aplica al icono de la app de
escritorio y al icono de la bandeja del sistema de Windows (incluyendo la vista "mostrar iconos
ocultos").

## Estado actual
- **Estado tracker:** NUEVO
- **Último agente:** orion-coordinador
- **Fecha última actualización:** 2026-09-12
- **Rama git:** —
- **Categoría:** UI
- **Tipo de cambio:** MEJORA

## Decisiones tomadas
2026-09-12 | orion-coordinador | REQ creado — categoría=UI | Detección por palabras clave: "icono de la app", "bandeja del sistema", "GUI" → coincide con categoría UI (iconografía de la app de escritorio PyQt6).
2026-09-12 | orion-coordinador | Diseño ya está pre-aprobado por el humano, no es un rediseño abierto | El canvas https://claude.ai/code/artifact/972fea5e-64f0-4598-acee-cb5c6b00136b ya fue aprobado; orion-spec/orion-ui deben tomar el artboard "Main.dc.html" (Concepto A) como la fuente de verdad del icono de app, y "Contexto.dc.html" como referencia de la versión simplificada/monocromo a 16px y 24px para bandeja del sistema.
2026-09-12 | orion-coordinador | Este REQ NO depende de la decisión pendiente sobre el nombre de la app | El usuario está reconsiderando el nombre "Noddoo" (ver memoria del proyecto, rename 2026-08-05) pero el diseño elegido no lleva texto ni nombre incrustado — no bloquear ni esperar por esa decisión.

## Descartado (y por qué)
- Icono actual (círculo grueso tipo mascota con auriculares): descartado por el humano, reemplazado por el Concepto A.
- Referencia de cubo usada durante la exploración de estilo: descartada como forma final — era solo inspiración del lenguaje visual, la forma final son los tres anillos entrelazados, no un cubo.

## Asumidos pendientes de confirmar
- Formatos de archivo exactos a generar (.ico multi-resolución para Windows, tamaños específicos: 16/24/32/48/256px, más posible .png para otros usos) — a confirmar en spec.
- Ubicación de los archivos de icono actuales en el repo (a identificar en baseline) para saber qué reemplazar exactamente (icono de ventana PyQt6 vs. icono de bandeja/system tray).

## Riesgos activos
- Ninguno identificado aún — pendiente de baseline/arquitectura.

## Decisiones tomadas (orion-spec)
2026-09-12 | orion-spec | Geometría/colores exactos extraídos del canvas | Leído el `appifact-doc` del artifact 972fea5e directamente (el `action: read` normal solo trae el head del editor, no el contenido de los artboards): degradado metálico `#ffffff → #b7b8bd → #5c5d63`, tres círculos `r=46` con `stroke-dasharray="180 30"` y offsets `0/96/192` sobre viewBox 200×200, nodo central `r=8.5`, fondo `#0a0a0b`. Bandeja: versión monocroma `#f2f2f3` sobre chip `#1b1b1d`, sin degradado, trazo más grueso (8 a 24px / 10 a 16px) y nodo más grande (r=10/r=12).
2026-09-12 | orion-spec | Baseline de código relevado (sin esperar a orion-baseline) | El icono NO existe como archivo `.ico`/`.png` — se genera 100% por código en `ui/webview/app_icon.py::dibujar()` con `QPainter` (anillo + punto, tinte plano `#58a6ff`, fondo transparente, tamaños `(16,24,32,48,64,128,256)`). `main_window.py` usa exactamente el mismo `app_icon()` tanto para `setWindowIcon()` (~L72-76) como para `tray_icon.setIcon()` (~L221-237) — hoy son el mismo objeto reescalado, no dos diseños distintos. Tests actuales en `tests/test_app_icon.py` verifican esa forma vieja (anillo+punto, transparencia total, "no es el cuadrado azul de antes") y deberán reescribirse, no solo borrarse.
2026-09-12 | orion-spec | SPEC-041.md redactada, contiene 4 ASUMIDOs pendientes de confirmación humana explícita antes de aprobar (variante distinta para bandeja vs. icono de app, mecanismo de implementación abierto a orion-architect, futuro del parámetro de tinte dinámico, no bloqueo por el nombre "Noddoo"). | Ver `workspace/adjuntos/REQ-041/spec/SPEC-041.md`.

2026-09-12 | orion-spec | SPEC aprobada | Aprobado por el humano (vía orion-coordinador), sin pedir ajustes.
2026-09-12 | orion-spec | Tipo de cambio: MEJORA | Identificado en el REQ inicial, confirmado en la SPEC.
2026-09-12 | orion-spec | Respuestas a los 4 ASUMIDOs de SPEC-041 | (1) La bandeja usa variante monocroma DISTINTA del icono de app con degradado — confirmado. (2) Mecanismo de implementación (QPainter procedural vs. asset estático/vectorial) queda abierto, lo decide orion-architect — confirmado. (3) El parámetro `color` de `dibujar()` no tiene planes de theming/color dinámico a futuro que dependan de él; si orion-dev lo elimina, no es problema. (4) No se bloquea por la decisión pendiente del nombre "Noddoo" — confirmado.
2026-09-12 | orion-spec | Caso borde del chip de bandeja en tema claro de Windows resuelto | Aceptable tal cual, fijo en `#1b1b1d` sin variante clara — el humano indicó que no hace falta que orion-ui lo revise aparte.

## Estado actual (actualizado por orion-spec)
- Estado tracker: SPEC_APROBADO
- Último agente: orion-spec

## Decisiones tomadas (orion-baseline)
2026-09-12 | orion-baseline | Confirmado en código: `app_icon()` es literalmente el mismo objeto para ventana y bandeja hoy | `main_window.py` L72-76 usa `app_icon()` para `setWindowIcon()`/`QApplication`, y L221-237 (`_setup_tray_icon()`) llama a `app_icon()` de nuevo en L227 — misma función, sin ninguna rama de código distinta para bandeja. El REQ-041 introduce esa bifurcación por primera vez.
2026-09-12 | orion-baseline | `tests/test_app_icon.py` ejecutado tal cual: 6/6 PASSED sobre el diseño viejo | De los 6, 2 quedan obsoletos por el fondo negro sólido nuevo (`test_el_fondo_es_transparente`, `test_no_es_el_cuadrado_liso_de_antes`), 1 necesita adaptar su técnica de conteo (`test_a_16_pixeles_todavia_hay_una_figura`, hoy cuenta por alpha y con fondo opaco eso deja de servir), y 2 no dependen del diseño visual y no deberían tocarse (`AppUserModelID` y orden de arranque en `main.py`). Detalle completo en `baseline-041.md`.
2026-09-12 | orion-baseline | `python -m py_compile` limpio en los 4 archivos afectados | Sin errores de sintaxis/import en `ui/webview/app_icon.py`, `ui/webview/main_window.py`, `tests/test_app_icon.py`, `main.py`.
2026-09-12 | orion-baseline | Suite completa registrada como referencia (185.6s): 42 failed, 2725 passed, 1 skipped, 4 errors | Todos los fallos son por dependencias opcionales ausentes en este entorno (`docx` en `test_documentos.py`, `uiautomation` en `test_ui_tree.py`) o un flaky de orden de tests (`test_code_index.py::test_el_indexado_se_puede_cortar_y_continuar`, pasa aislado). Ninguno toca los archivos de este REQ — no confundir con regresiones de REQ-041 si siguen apareciendo después.

## Riesgos activos
- Ninguno propio de REQ-041 en las zonas que toca (icono/tray/main_window están limpias hoy). Los 42 fallos pre-existentes de la suite completa están en áreas no relacionadas (`test_documentos.py`, `test_ui_tree.py`) y no deben bloquear ni confundirse con este REQ.

## Decisiones tomadas (orion-architect)
2026-09-14 | orion-architect | Mecanismo elegido: SVG embebido como strings Python + `QSvgRenderer` (no `.ico`/`.png` en el repo, no dibujo procedural con `QPainter`/arcos manuales) | `stroke-dasharray="180 30"` sobre cada anillo se reduce matemáticamente a un solo arco con un solo hueco por anillo, así que reconstruirlo a mano con `drawArc` era viable — pero el degradado lineal + el offset de rotación por anillo se habrían tenido que recalcular a mano con riesgo real de desviarse del canvas aprobado. Con SVG se pegan los números del canvas tal cual, sin conversión. Validado empíricamente en el entorno real del proyecto (PyQt6 6.11.0/Qt 6.11.0): gradiente, dasharray/dashoffset y esquinas redondeadas se renderizan correctamente en los 7 tamaños de app y los 2 de bandeja.
2026-09-14 | orion-architect | Sin dependencias nuevas | `PyQt6.QtSvg.QSvgRenderer` ya está disponible con el `PyQt6` instalado hoy (verificado con `python -c "from PyQt6.QtSvg import QSvgRenderer"` en el venv del proyecto) — no se toca `requirements.txt`.
2026-09-14 | orion-architect | Nueva función pública se llama `bandeja_icon()`, no `tray_icon()` | `main_window.py` ya tiene el atributo de instancia `self.tray_icon` (el `QSystemTrayIcon`); evitar la colisión de nombres aunque no rompería nada en tiempo de ejecución.
2026-09-14 | orion-architect | `_ACENTO` y el parámetro `color` de la vieja `dibujar()` se eliminan sin reemplazo | Confirmado aceptable en ASUMIDO 3 de SPEC-041 (aprobado por el humano).
2026-09-14 | orion-architect | Riesgo detectado y NO resuelto por reinterpretación: el icono de app a 16 px, con la geometría exacta del canvas, deja solo ≈0.8% de píxeles distinguibles del fondo (medido con un render de prueba real) — muy por debajo del umbral 15%–80% del test viejo | No se ajusta la forma (la SPEC lo prohíbe explícitamente); se ajusta el UMBRAL NUMÉRICO del test adaptado y se recomienda que el humano/`orion-ui` confirme visualmente un PNG real de `dibujar_app(16)` antes de cerrar el REQ. Detalle completo en `arquitectura-041.md`, sección Riesgos.
2026-09-14 | orion-architect | Ambigüedad de SPEC resuelta con dos sistemas de coordenadas en el mismo SVG de bandeja, no adivinando una sola lectura | El `<rect>` de fondo del chip usa el espacio final (`rx` literal 5/4 sin escalar) y la marca vive dentro de `<g transform="scale(size/200)">` en su espacio nativo 200×200 (`stroke-width`/`node_r` literales de la SPEC) — satisface ambas lecturas posibles del texto de SPEC-041 a la vez, sin inventar ningún número. Validado con render de prueba.
2026-09-14 | orion-architect | Propuesta técnica redactada — `workspace/adjuntos/REQ-041/propuestas/arquitectura-041.md` | Pendiente de aprobación humana explícita antes de continuar a `orion-dev` (categoría UI, pero sin referencia visual nueva que amerite un paso `orion-ui` adicional — ver nota de handoff en la propuesta).

## Decisiones tomadas (orion-architect, cierre)
2026-09-14 | orion-architect | Arquitectura aprobada por el humano tal cual fue presentada, sin ajustes | Aprobación explícita recibida sobre `arquitectura-041.md` (mecanismo SVG embebido + `QSvgRenderer`, sin dependencias nuevas, geometría exacta del canvas). El riesgo de legibilidad del icono de app a 16px queda documentado en la propuesta y aceptado como riesgo conocido — no bloquea el avance a `orion-ui`.

## Estado actual (actualizado por orion-baseline)
- Estado tracker: EN_ARQUITECTURA
- Último agente: orion-baseline

## Estado actual (actualizado por orion-architect, cierre)
- Estado tracker: ARQUITECTURA_APROBADA
- Último agente: orion-architect
- Rama git: feature/REQ-041-icono-app

## Log de transiciones
2026-09-12 | — → NUEVO | orion-coordinador | REQ creado
2026-09-12 | NUEVO → EN_SPEC → SPEC_APROBADO | orion-spec | SPEC-041 redactada y aprobada por el humano sin ajustes
2026-09-12 | SPEC_APROBADO → EN_BASELINE → EN_ARQUITECTURA | orion-baseline | Baseline de código y tests documentado, sin fallos preexistentes en el área del REQ
2026-09-14 | EN_ARQUITECTURA (sin cambio de estado) | orion-architect | Propuesta técnica redactada, pendiente de aprobación humana — el estado pasa a ARQUITECTURA_APROBADA recién cuando el humano confirme
2026-09-14 | EN_ARQUITECTURA → ARQUITECTURA_APROBADA | orion-architect | Aprobación humana explícita recibida sobre `arquitectura-041.md` sin pedir ajustes — siguiente paso `orion-ui` (categoría UI con referencia visual: canvas de diseño aprobado)

## Decisiones tomadas (orion-ui)
2026-09-14 | orion-ui | Contraste contra el sistema de diseño actual: sin drift | El negro `#0a0a0b` (icono de app) y `#1b1b1d` (chip de bandeja) son coherentes en valor con `--bg-primary`/`--bg-hover` del tema oscuro (`#0c0d0f`/`#1f2226`) — mismo rango tonal, sin tinte nuevo. El degradado metálico (`#ffffff`/`#b7b8bd`/`#5c5d63`) es gris sin tinte, coherente con la filosofía ya declarada en `theme.css` ("paleta neutra a propósito... grises sin tinte, un único acento azul").
2026-09-14 | orion-ui | Decisión de encuadre de tokens: NINGÚN color de este REQ se agrega a `theme.py`/`theme.css` | Esos dos archivos son la fuente de verdad de la paleta del webview (con `data-theme` consultable en tiempo real); el icono de app/bandeja lo pinta Windows FUERA de la ventana, sin tema que consultar — mismo criterio que ya usaba la constante `_ACENTO` del código viejo (declarada aparte, no importada de `theme.py`). Los 6 colores nuevos (`_APP_BG`, 3 paradas del gradiente, `_TRAY_BG`, `_TRAY_STROKE`) quedan como literales Python en `ui/webview/app_icon.py`, ya previsto así por `orion-architect`. No aplica el test de drift `tests/test_webview_theme.py` — no toca esos archivos.
2026-09-14 | orion-ui | Estados de componente: ambas piezas son iconos ESTÁTICOS de sistema, sin set de estados interactivos | Documentado explícitamente en `ui-design-041.md` que hover/focus/active/disabled/loading/error del icono de app y de bandeja NO APLICAN — los pinta el shell de Windows, la app no tiene gancho para dibujarlos distinto. Único matiz real: el icono de bandeja se ve sobre dos fondos de contexto distintos controlados por Windows (bandeja principal vs. flyout "iconos ocultos", `#141416`/`#242426` del mockup) — mismo pixmap en los dos casos, verificado en accesibilidad que el contraste se sostiene en ambos.
2026-09-14 | orion-ui | Accesibilidad revisada (WCAG 1.4.11, contraste no-textual 3:1) | Trazo de bandeja `#f2f2f3` sobre `#1b1b1d` ≈15.4:1 y sobre `#141416` (mockup) ≈16.4:1 — amplio margen. Icono de app: parada clara del degradado ≈20:1, parada media ≈10:1, ambas sin riesgo. **Hallazgo no bloqueante**: la parada oscura del degradado (`#5c5d63`) sobre el fondo `#0a0a0b` da ≈3.0:1 — pasa el umbral 3:1 pero por muy poco, es el punto más débil de la marca (coincide con el extremo del mismo trazo que ya arquitectura documentó como casi ilegible a 16px). No se ajusta el color (geometría/color ya aprobados en SPEC) — queda documentado para que el humano/`orion-qa` lo tengan presente en la prueba manual.
2026-09-14 | orion-ui | Descarte del cubo "Mindcube" documentado con motivo explícito | Se adoptó el LENGUAJE VISUAL de la referencia que inspiró la exploración de estilo (trazo fino, degradado metálico, fondo negro sólido) — se descartó la GEOMETRÍA de cubo porque los tres anillos entrelazados ya eran la forma final aprobada como Concepto A antes de que este paso entrara al flujo (decisión ya registrada por `orion-coordinador` el 2026-09-12); los anillos comunican mejor la idea de "conexión/agente" que una caja cerrada.
2026-09-14 | orion-ui | `ui-design-041.md` generado, sin tocar módulos/clases/flujo de datos (ya cerrados por arquitectura) | `workspace/adjuntos/REQ-041/propuestas/ui-design-041.md`.
2026-09-14 | orion-ui | Conclusión propia de DoD: ESTO ES UN REDISEÑO, no un ajuste menor — requiere aprobación humana explícita separada | Reemplaza por completo la identidad visual de la app en todos los lugares donde Windows la muestra (ventana/taskbar/alt-tab/bandeja/iconos ocultos). Aunque la geometría ya viene aprobada del canvas, el contraste contra el sistema de diseño vivo, la decisión de encuadre de tokens, los estados (su ausencia justificada) y el hallazgo de accesibilidad no estaban cerrados todavía — el REQ queda ESPERANDO esa aprobación, no avanza solo a `orion-dev`.

## Estado actual (actualizado por orion-ui)
- Estado tracker: ARQUITECTURA_APROBADA (sin cambio — orion-ui no tiene columna propia en el tracker; el REQ queda pausado esperando aprobación humana de `ui-design-041.md` antes de pasar a `orion-dev`)
- Último agente: orion-ui
- Rama git: feature/REQ-041-icono-app (sin cambio)

## Decisiones tomadas (orion-ui, cierre)
2026-09-14 | orion-ui | Diseño UI aprobado por el humano tal cual fue presentado, sin ajustes | Aprobación explícita recibida sobre `ui-design-041.md` completo: contraste contra el sistema de diseño actual, decisión de no agregar tokens a `theme.py`/`theme.css` (colores nuevos quedan como literales en `app_icon.py`), estados documentados como no aplicables (iconos estáticos de sistema), hallazgo de accesibilidad de la parada oscura del degradado (~3.0:1, no bloqueante) y el motivo de descarte del cubo "Mindcube". Sin columna propia en `requerimientos.csv` para registrar esta aprobación (las columnas existentes son `ID, Descripcion, Categoria, Estado, Tipo_Cambio, Aprobacion_SPEC, Aprobacion_Arquitectura, Rama` — ninguna corresponde a diseño UI); verificado con `node .claude/scripts/update-tracker.mjs --lista` antes de concluir que no aplica ninguna escritura al CSV. Queda registrada acá, en el contexto, como única fuente de verdad de esta aprobación.
2026-09-14 | orion-ui | DoD de `orion-ui` cerrado — siguiente paso `orion-dev` | Con arquitectura (`propuestas/arquitectura-041.md`) y diseño UI (`propuestas/ui-design-041.md`) ambos aprobados por el humano, el REQ queda listo para implementación. `orion-dev` implementa exactamente lo que definen esos dos documentos: mecanismo SVG embebido + `QSvgRenderer` en `ui/webview/app_icon.py` (reescritura completa), el cambio de `~L227` en `ui/webview/main_window.py`, y la reescritura parcial de `tests/test_app_icon.py` — sin reabrir geometría, colores ni la decisión de no tocar `theme.py`/`theme.css`.

## Estado actual (actualizado por orion-ui, cierre)
- Estado tracker: ARQUITECTURA_APROBADA (sin cambio de estado — el tracker no tiene una columna ni un estado intermedio para "diseño UI aprobado"; la transición formal de estado ARQUITECTURA_APROBADA → EN_DESARROLLO le corresponde a `orion-dev` al iniciar su trabajo, según `TRANSICIONES` de `update-tracker.mjs`)
- Último agente: orion-ui
- Rama git: feature/REQ-041-icono-app (sin cambio)
- Siguiente paso: @orion-dev, con `propuestas/arquitectura-041.md` y `propuestas/ui-design-041.md` ya aprobados por el humano

## Decisiones tomadas (orion-dev)
2026-09-14 | orion-dev | `ui/webview/app_icon.py` reescrito completo, tal cual `arquitectura-041.md` | SVG embebido como strings Python (`_marca_svg`, `_app_icon_svg`, `_tray_icon_svg`) renderizado con `QSvgRenderer` a `QPixmap` vía `_render_svg`. `dibujar()`/`_ACENTO`/parámetro `color` eliminados sin reemplazo (confirmado en ASUMIDO 3 de SPEC-041). Funciones públicas nuevas: `dibujar_app(size)`, `dibujar_bandeja(size)`, `app_icon()` (sin `color`), `bandeja_icon()` — mismos nombres que especificó la arquitectura, sin inventar ninguno. `fijar_identidad_en_windows()`/`_APP_ID` sin cambios.
2026-09-14 | orion-dev | `ui/webview/main_window.py` actualizado en el único punto que señaló la arquitectura | Import agrega `bandeja_icon`; `_setup_tray_icon()` (~L227) usa `self.tray_icon.setIcon(bandeja_icon())` en vez de `app_icon()`. `setWindowIcon()`/`QApplication.setWindowIcon()` (~L72-76) sin diff real, tal como anticipó la arquitectura.
2026-09-14 | orion-dev | `tests/test_app_icon.py` reescrito según la lista exacta de `arquitectura-041.md` (10 tests: 3 sin cambios, 2 reescritos, 1 adaptado, 4 nuevos) | `python -m pytest tests/test_app_icon.py --tb=short -v` → 10/10 PASSED.
2026-09-14 | orion-dev | Ajuste de umbral numérico en `test_bandeja_16_y_24_son_legibles`, distinto del valor de referencia de arquitectura (~19-23%) | Medido en este entorno: ~32%/43% (24/16px) usando "cualquier píxel que difiere del fondo" en vez del criterio de cobertura fuerte que aparentemente usó el render de prueba de `orion-architect` — el trazo nativo de 8/10 queda por debajo de 1px real una vez escalado, así que ningún píxel individual llega a cobertura 100%. Sin cambio de geometría/color; solo diferencia de metodología de conteo. Margen ajustado a 15%-60%. Detalle completo en `desarrollo-log-041.md`.
2026-09-14 | orion-dev | `test_bandeja_usa_color_plano_sin_degradado` verifica la propiedad renderizando `_marca_svg` a tamaño nativo 200px, no el bitmap final de 16/24px | A los tamaños reales de bandeja ningún píxel alcanza cobertura 100% (mismo motivo del punto anterior), así que comparar contra `#f2f2f3` exacto ahí daría un falso negativo permanente por antialiasing, no por degradado. Se sigue verificando por render de píxeles (no se parsea el SVG como string), solo que a una resolución donde el resultado es determinista. Detalle en `desarrollo-log-041.md`.
2026-09-14 | orion-dev | Suite completa ejecutada y comparada contra `baseline-041.md` | `python -m pytest tests/ --tb=short -q` → 41 failed, 2730 passed, 1 skipped, 4 errors (baseline: 42 failed, 2725 passed, 1 skipped, 4 errors). Sin fallos nuevos fuera de las áreas ya documentadas como pre-existentes (`test_documentos.py`, `test_ui_tree.py`); la baja de 42→41 coincide con el flaky de orden ya señalado en `test_code_index.py`, no es una regresión de este REQ.
2026-09-14 | orion-dev | Sin dependencias nuevas, sin API keys/tokens, sin `except: pass` silencioso, sin prints de debug | `PyQt6.QtSvg.QSvgRenderer` ya estaba disponible; `requirements.txt` no se tocó. No se ejecutó `git commit`.
2026-09-14 | orion-dev | Pendiente para el humano/orion-tester: confirmación visual de `dibujar_app(16)` | `arquitectura-041.md` recomendó verificar con una imagen real el riesgo ya conocido y aceptado (icono de app casi indistinguible del fondo a 16px, ~0.8% de píxeles). No bloquea el avance a `orion-tester`; queda documentado en `desarrollo-log-041.md`.

## Estado actual (actualizado por orion-dev)
- Estado tracker: EN_PRUEBAS
- Último agente: orion-dev
- Rama git: feature/REQ-041-icono-app (sin cambio)
- Siguiente paso: @orion-tester, con `propuestas/desarrollo-log-041.md` y `spec/SPEC-041.md`

## Log de transiciones
2026-09-14 | ARQUITECTURA_APROBADA → EN_DESARROLLO → EN_PRUEBAS | orion-dev | Implementación completa de `app_icon.py`/`main_window.py`/`test_app_icon.py` según arquitectura y diseño UI aprobados; 10/10 tests propios en verde, sin regresiones en la suite completa frente al baseline

## Decisiones tomadas (orion-tester)
2026-09-14 | orion-tester | Compilación verificada de forma independiente | `python -m py_compile ui/webview/app_icon.py ui/webview/main_window.py tests/test_app_icon.py main.py` → sin errores.
2026-09-14 | orion-tester | `tests/test_app_icon.py` re-ejecutado de forma independiente (no se confió solo en el reporte de `orion-dev`) | 10/10 PASSED, idéntico a lo reportado.
2026-09-14 | orion-tester | 9/9 criterios de SPEC-041 verificados contra código real y, para los criterios visuales (1, 2, 4), contra renders reales de `dibujar_app`/`dibujar_bandeja` (no solo lectura de código) | Detalle completo en `pruebas/test-results-041.md`. Incluye verificación por `grep` de que `_ACENTO`/`#58a6ff` no queda como color del icono (criterio 9) — la única coincidencia en el repo es `theme.py:32` (`text_accent`), un token del webview ajeno al icono.
2026-09-14 | orion-tester | Suite completa re-ejecutada de forma independiente | `python -m pytest tests/ --tb=short -q` → 41 failed, 2730 passed, 1 skipped, 4 errors — coincide EXACTO con lo reportado por `orion-dev` y con las áreas pre-existentes del baseline (`test_documentos.py` por `docx` ausente, `test_ui_tree.py` por `uiautomation` ausente). Sin fallos nuevos atribuibles a este REQ. No existe ningún test dedicado que ejercite `main_window.py` directamente (el cambio de `~L227-228` solo se cubre por `test_app_icon.py` + revisión manual de código) — no es un gap introducido por este REQ.
2026-09-14 | orion-tester | Verificación visual directa (cierra el pendiente que dejó `desarrollo-log-041.md`) | Se renderizaron y se inspeccionaron `dibujar_app(256)`, `dibujar_app(16)`, `dibujar_bandeja(16)` y `dibujar_bandeja(24)`. `dibujar_app(256)` muestra el Concepto A completo y fiel al canvas. `dibujar_bandeja(16/24)` se reconoce con claridad como los 3 anillos + nodo (criterio 4 satisfecho sin ambigüedad). **Hallazgo confirmado, no bloqueante:** `dibujar_app(16)` es casi indistinguible de un cuadrado negro liso — coincide exactamente con el ~0.8% ya medido y aceptado por `orion-architect`; no viola ningún criterio escrito de la SPEC (la legibilidad a tamaño chico solo se exige explícitamente para la bandeja), pero se recomienda que el humano lo tenga presente en la prueba manual final.
2026-09-14 | orion-tester | Dos desviaciones de `desarrollo-log-041.md` revisadas (umbral de `test_bandeja_16_y_24_son_legibles` y método de `test_bandeja_usa_color_plano_sin_degradado` a 200px nativos) | Ambas son ajustes de METODOLOGÍA de test (conteo de antialiasing / resolución de verificación), no cambios de geometría ni color. No rompen ningún criterio de aceptación de SPEC-041 — confirmado independientemente vía inspección visual y por código. Detalle en `pruebas/test-results-041.md`.
2026-09-14 | orion-tester | Veredicto: PASS — 9/9 criterios, 10/10 tests propios, sin regresiones nuevas | Siguiente paso `orion-qa`. `pruebas/test-results-041.md` generado.

## Estado actual (actualizado por orion-tester)
- Estado tracker: EN_QA
- Último agente: orion-tester
- Rama git: feature/REQ-041-icono-app (sin cambio)
- Siguiente paso: @orion-qa, con `pruebas/test-results-041.md`

## Log de transiciones
2026-09-14 | EN_PRUEBAS → EN_QA | orion-tester | 9/9 criterios de SPEC-041 en PASS, 10/10 tests propios verificados de forma independiente, sin regresiones nuevas en la suite completa; hallazgo no bloqueante documentado (legibilidad del icono de app a 16px)

## Decisiones tomadas (orion-qa)
2026-09-14 | orion-qa | Auditoría de seguridad: sin superficie de seguridad, confirmado explícitamente y no asumido | REQ puramente visual (SVG embebido → `QSvgRenderer` → `QPixmap`), sin input de usuario, sin red, sin filesystem, sin `os.system()`/`subprocess`. Único efecto lateral fuera de dibujar píxeles es `fijar_identidad_en_windows()` (sin cambios de este REQ), que no es destructivo. Ningún caso de `security-levels.md` (verde/amarillo/rojo) aplica a generar/mostrar un icono.
2026-09-14 | orion-qa | Sin secretos ni referencias al diseño viejo | `grep` de `_ACENTO`/`58a6ff` en todo el repo: única coincidencia `ui/webview/theme.py:32` (`text_accent`), token del webview ajeno al icono, no un residuo del diseño anterior.
2026-09-14 | orion-qa | Logging correcto, sin `except: pass` silencioso ni `print()` de depuración | Único `except` en el código tocado por este REQ (`fijar_identidad_en_windows()`, sin cambios) registra con `logger.warning(...)` antes de continuar. `_render_svg()` usa `try/finally` (no `except`) solo para garantizar `painter.end()`. Verificado por grep en `app_icon.py`, diff de `main_window.py` y `tests/test_app_icon.py`.
2026-09-14 | orion-qa | Diff real de `main_window.py` auditado con `git diff HEAD`, no solo lo reportado | Confirmado: solo 2 hunks (agregar `bandeja_icon` al import existente, y `self.tray_icon.setIcon(bandeja_icon())` en `_setup_tray_icon()`). El orden de imports "raro" de ese archivo (local en medio de third-party) es preexistente al REQ, no una regresión introducida ahora — no bloquea.
2026-09-14 | orion-qa | Dos hallazgos menores no bloqueantes, solo en `tests/test_app_icon.py` | (1) Línea 180 excede el límite de 100 caracteres de `python-style.md` por 2 caracteres. (2) Línea 106, dentro de `test_a_16_pixeles_todavia_hay_una_figura`: variable `total = 16 * 16` calculada pero nunca usada (residual de una versión anterior del test). Sin impacto de seguridad ni funcional, no afectan el resultado de los 10/10 tests en verde — documentados para que `orion-dev` los limpie en la próxima oportunidad de tocar el archivo, no ameritan rechazo.
2026-09-14 | orion-qa | Veredicto: ✅ COMPLETADO | `workspace/adjuntos/REQ-041/qa-audit-041.md` generado. Hallazgos ya conocidos y aceptados en etapas previas (legibilidad a 16px, contraste ≈3.0:1 del extremo oscuro del degradado) se dan por vigentes, no se reabren acá — quedan para la prueba manual del humano.

## Estado actual (actualizado por orion-qa)
- Estado tracker: EN_QA (sin cambio de estado aún — pendiente prueba manual del humano antes de pasar a LISTO_PARA_COMMIT)
- Último agente: orion-qa
- Rama git: feature/REQ-041-icono-app (sin cambio)
- Siguiente paso: prueba manual del humano (ver mensaje de handoff), luego `orion-qa` cierra con `LISTO_PARA_COMMIT` y entrega el mensaje de commit sugerido

## Cierre — prueba manual del humano
2026-09-14 | (sesión principal, cierre del gate de `orion-qa`) | Prueba manual final confirmada por el humano | El humano confirmó explícitamente el resultado de la checklist de prueba manual entregada por `orion-qa` (barra de tareas, Alt-Tab, bandeja del sistema, "mostrar iconos ocultos") sin reportar fallas, y pidió subir los cambios. Nota: el agente `orion-qa` que generó `qa-audit-041.md` ya no estaba alcanzable (`ListAgents` sin agentes activos) para cerrar su propio DoD, así que este cierre se registra desde la sesión principal, respetando igual la regla de no ejecutar `git commit`/`push` — solo se entrega el mensaje de commit sugerido para que el humano lo corra manualmente.

## Estado actual (cierre final)
- Estado tracker: LISTO_PARA_COMMIT
- Último agente: orion-qa (cierre registrado por sesión principal, agente original no alcanzable)
- Rama git: feature/REQ-041-icono-app (sin cambio)
- Siguiente paso: el humano ejecuta manualmente `git add`/`commit`/`push` con el mensaje sugerido entregado

## Log de transiciones
2026-09-14 | EN_QA → LISTO_PARA_COMMIT | (cierre de orion-qa) | Prueba manual del humano confirmada sin fallas reportadas
