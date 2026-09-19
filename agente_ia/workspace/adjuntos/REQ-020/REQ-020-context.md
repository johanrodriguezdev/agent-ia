# Contexto REQ-020 — Reorganización visual de NODDOO inspirada en referencia "JARVIS-OS"

## Resumen ejecutivo
Reorganizar y mejorar la disposición visual de la interfaz de escritorio NODDOO
(`ui/webview/frontend/`, base de REQ-015/016), tomando como inspiración —no como plantilla
a clonar— una referencia visual tipo "JARVIS-OS" (descrita en texto, sin archivo de
imagen) de layout en tres columnas persistentes con panel de monitor de sistema, chat
central y panel de tareas/memoria.

## Estado actual
- **Estado tracker:** EN_QA
- **Último agente:** orion-qa
- **Fecha última actualización:** 2026-08-25
- **Rama git:** feature/REQ-015-webview-ui (sin rama propia, se sigue trabajando sobre la base webview, mismo criterio que REQ-016/018/019)
- **Categoría:** UI
- **Tipo de cambio:** MEJORA

## Decisiones tomadas
2026-08-25 | orion-coordinador | REQ creado — categoría=UI | Detección por palabras clave: "interfaz", "GUI"/UI explícitas en la descripción del humano, referencia visual de layout/estética
2026-08-25 | orion-coordinador | Descripción de la referencia visual "JARVIS-OS" guardada en `workspace/adjuntos/REQ-020/origen/referencia-visual-jarvis-os.md` (no existe archivo de imagen, solo el análisis textual de la captura que compartió el humano) | Es la única evidencia de origen disponible
2026-08-25 | orion-coordinador | Objetivo fijado como "inspiración para mejorar organización de información", explícitamente NO clonar la referencia literal | NODDOO tiene identidad de marca propia ya establecida (REQ-008/010/013/014/015/016)
2026-08-25 | orion-coordinador | `orion-ui` (agente nuevo) debe participar en este REQ antes de `orion-dev` | Categoría UI con referencia visual a interpretar — corresponde a su rol
2026-08-25 | orion-spec | Pregunta 1 (Tareas modal vs. persistente) resuelta: pasa a panel persistente en la columna derecha | Respuesta explícita del humano, opción A
2026-08-25 | orion-spec | Pregunta 2 (monitor de sistema) resuelta: se incluye el panel en el layout pero SIN datos reales de CPU/memoria/red — placeholder/estado vacío explícito | El humano delegó la decisión ("Decide"); conectar métricas reales del host queda fuera de alcance (candidato a REQ futuro CORE/INTEGRACION) para no meter una fuente de datos/IPC nueva en un REQ de UI
2026-08-25 | orion-spec | Pregunta 3 (fidelidad estética) resuelta: cero tokens/colores nuevos, se mantiene 100% la paleta y los temas oscuro/claro actuales — no se adopta el tema claro+cian de la referencia ni decoración tipo HUD | Respuesta explícita del humano, opción A: solo reorganizar información/layout
2026-08-25 | orion-spec | Pregunta 4 (alcance) resuelta: además de la ventana principal, también se adaptan `projects_panel.js` y `settings_panel.js` al mismo criterio de layout/organización (sin volverlos persistentes) | Respuesta explícita del humano, opción C
2026-08-25 | orion-spec | SPEC-020.md redactada en `workspace/adjuntos/REQ-020/spec/SPEC-020.md`, con 4 ASUMIDOs nuevos (ubicación espacial de la columna derecha, exclusión del panel "Memoria/Conocimiento", exclusión de "Registros", alcance concreto de "adaptar" Proyectos/Configuración) pendientes de confirmación explícita del humano en el mismo gate | Surgieron al redactar criterios de aceptación testeables, no estaban cubiertos por las 4 preguntas originales de `orion-coordinador`
2026-08-25 | orion-spec | SPEC-020 APROBADA por el humano, TAL CUAL, incluyendo los 4 ASUMIDOs nuevos (columna derecha con Monitor de sistema + Tareas, sin tocar sidebar izquierdo; panel "Memoria/Conocimiento" fuera de alcance; pestaña "Registros" fuera de alcance; "adaptar" Proyectos/Configuración = mismo lenguaje visual de cabecera/tarjeta sin volverlos persistentes ni tocar bridge.py) | Aprobación explícita trasladada por `orion-coordinador` en nombre del humano
2026-08-25 | orion-spec | Tipo de cambio: MEJORA | Identificado en la entrevista original con `orion-coordinador`, sin cambios tras la SPEC
2026-08-25 | orion-baseline | Baseline redactado en `workspace/adjuntos/REQ-020/origen/baseline-020.md`: layout actual documentado (2 zonas, Tareas/Proyectos/Configuración modales), 9 archivos previstos a modificar confirmados contra código real, suite completa ejecutada (2 fallos preexistentes en `tests/test_llm_provider.py` por `ModuleNotFoundError: No module named 'anthropic'`, sin relación con UI/webview) | Subset `test_webview_*` (194 tests) y los dos tests explícitos de SPEC-020 (`test_webview_safe_dom_insertion.py`, `test_webview_theme.py`, 30 tests) pasan 100% antes del cambio
2026-08-25 | orion-baseline | Detectado: `tests/test_webview_safe_dom_insertion.py::test_ningun_otro_archivo_js_del_frontend_usa_innerhtml` hace glob sobre TODO `frontend/js/*.js` (excepto `chat.js`) — cualquier archivo JS nuevo que cree `orion-dev` para "Monitor de sistema" queda cubierto automáticamente por esa regla, sin necesidad de tocar la lista `_MUST_NOT_USE_INNERHTML` | Relevante para `orion-architect` al diseñar el módulo nuevo del placeholder
2026-08-25 | orion-architect | Arquitectura redactada en `workspace/adjuntos/REQ-020/propuestas/arquitectura-020.md`: `#app-body` pasa a 3 columnas flex (`#sidebar` + `#main-column` + `#side-panel` nuevo, 300px fijo); `#side-panel` apila `#monitor-panel-section` (100% estático, sin JS ni bridge) + `#tasks-panel-mount` (poblado una sola vez por `mountTasksPanel()` en `bootstrap()`, reemplaza `openTasksPanel()`/`closeTasksPanel()`) | Satisface CA-01/02/05/06/11/12/13 de SPEC-020 reutilizando el patrón de caja ya validado en `#sidebar`
2026-08-25 | orion-architect | Decisión: se **elimina** el botón `#tasks-btn` del sidebar (CA-09) en vez de re-etiquetarlo o reemplazarlo | Su única función (abrir el modal) queda redundante al ser Tareas un panel siempre visible; no hay colapso manual de `#side-panel` que justifique mantenerlo como atajo
2026-08-25 | orion-architect | Colapso de `#side-panel` en ventana angosta resuelto 100% en CSS (`layout.css`, `@media (max-width: 1199px) { display:none }`), sin JS ni estado nuevo en `gui_state.py` | Verificado contra `main_window.py:69` (mínimo 1024×640): a ese ancho la columna ya está oculta antes de apretar el chat, sin necesitar `min-width` adicional en `#main-column`
2026-08-25 | orion-architect | Nueva función `relocateChipsRow(isEmptyState)` en `composer.js`, invocada desde `chat.js::syncEmptyState()` — mueve (no clona) el nodo `#chips-row` entre `#composer` y un slot nuevo `#empty-state-chips-slot` dentro de `#empty-state` | Satisface CA-19/CA-20 reutilizando `onChipsLoaded`/`renderChips()` sin cambios y sin nuevo endpoint del bridge
2026-08-25 | orion-architect | Confirmado: `bridge.py` y `gui_state.py` no requieren ningún cambio | `bridge.py`: mismas firmas de `request_tasks`/`create_task`/`complete_task`/`request_delete_task`, solo cambia cuándo/dónde se invocan desde JS. `gui_state.py`: gestiona `GLOBAL_STATE`/`WAKE_STATE` (voz), sin relación con el layout
2026-08-25 | orion-architect | Propuesta técnica trasladada al humano para aprobación — APROBADA en su totalidad, sin ajustes, incluyendo la eliminación de `#tasks-btn` (opción recomendada, confirmada explícitamente) | Aprobación trasladada por `orion-coordinador`
2026-08-25 | orion-ui | Diseño visual redactado en `ui-design-020.md` sobre la arquitectura ya aprobada, sin contradecirla: mapeo de tokens 100% reutilizados (cero color nuevo), box model exacto de `#side-panel` (300px, `bg-secondary`, `border-left`, `min-height:0` en toda la cadena hasta `.panel-list-flex` para que el scroll interno funcione), y 3 clases CSS nuevas (`panel-section-title`, `panel-header-title-group`, `panel-list-flex`) | Ninguna clase nueva requiere token/color nuevo — todas reutilizan `var(--text-primary)`/`var(--text-secondary)`/`var(--border)` ya existentes
2026-08-25 | orion-ui | Monitor de sistema: título sin ícono decorativo (a diferencia de Tareas/Proyectos/Configuración) | Decisión deliberada — es el único panel totalmente nuevo sin ícono ya establecido en el sidebar para reutilizar, y la referencia JARVIS-OS es explícita en decoración tipo HUD por panel; se prioriza el criterio más conservador en el componente que SPEC-020 trata con más cautela
2026-08-25 | orion-ui | Ícono de la cabecera de Tareas (`&#128203;`), Proyectos (`&#128193;`) y Configuración (`&#9881;`) reutiliza exactamente el glyph que ya tenían sus botones en el sidebar (el de Tareas migra desde `#tasks-btn`, que se elimina) | Da continuidad visual sin introducir iconografía nueva; `projects_panel.js::renderDetailShell()` (vista de un proyecto puntual) queda sin ícono porque el título ahí es el nombre del proyecto, no la categoría "Proyectos"
2026-08-25 | orion-ui | Agrupación por estado (Pendientes/Completadas) en la lista de Tareas: NO se adopta en este REQ | `arquitectura-020.md` la dejó condicionada ("si Tareas gana agrupación, Proyectos podría agrupar igual"); implementarla requeriría cambiar la estructura de renderizado de `renderTasks()` (sub-listas con encabezado de grupo), no solo estilo — decisión de `orion-architect` si se quiere a futuro, no de `orion-ui`
2026-08-25 | orion-ui | Corrección de accesibilidad agregada al alcance: `.panel-form input/select` y `.settings-row-select` ganan `:focus { outline:none; border-color:var(--text-accent) }` | Unifica con el patrón ya establecido en `#composer-input-row`/`#sidebar-search-input` — eran la única excepción de todo el sistema de inputs sin foco temátizado; beneficia a Tareas (fija) y Proyectos (modal) por igual al compartir `.panel-form`, responde directamente a CA-22 (jerarquía/spacing aplicable a ambas pantallas)
2026-08-25 | orion-ui | `.panel-close-btn` sin `:hover`/`:focus` temáticos propios (carencia preexistente, no causada por este REQ): NO se corrige en este REQ | Para no ampliar el diff aprobado más allá de lo que arquitectura delegó; queda documentado en "Fuera de alcance visual" de `ui-design-020.md` como hallazgo de la revisión de accesibilidad, no como pendiente bloqueante
2026-08-25 | orion-ui | Ningún punto de la arquitectura aprobada requirió token/color no existente ni contradijo la estructura fijada — no hubo necesidad de devolver nada al humano en este paso | Verificado explícitamente contra `theme.py`/`theme.css` variable por variable antes de redactar `ui-design-020.md`

2026-08-25 | orion-dev | Implementado tal cual arquitectura-020.md + ui-design-020.md, sin desviaciones de alcance: index.html (columna #side-panel de 3 hijos flex, eliminación de #tasks-btn, #empty-state-chips-slot), layout.css (#side-panel 300px + colapso <1200px), panels.css (box model de #monitor-panel-section/#tasks-panel-mount + clases .panel-section-title/.panel-header-title-group/.panel-list-flex + foco de .panel-form), settings_panel.css (foco de .settings-row-select), composer.css (#chips-row:empty), chat.css (#empty-state-chips-slot #chips-row), tasks_panel.js (mountTasksPanel() reemplaza openTasksPanel/closeTasksPanel), app.js (bootstrap llama mountTasksPanel() en vez de cablear el click de #tasks-btn), composer.js (relocateChipsRow nueva), chat.js (syncEmptyState llama relocateChipsRow), projects_panel.js/settings_panel.js (cabecera con .panel-header-title-group, renderDetailShell de Proyectos sin cambios) | Ver desarrollo-log-020.md para el detalle completo por archivo
2026-08-25 | orion-dev | Verificación local: py_compile OK, test_webview_safe_dom_insertion+test_webview_theme 30/30, subset test_webview_* 194/194, suite completa 538 passed/2 failed (los mismos 2 fallos preexistentes de baseline-020.md, ninguno nuevo) | Sin regresiones detectadas
2026-08-25 | orion-dev | Ningún punto de arquitectura-020.md o ui-design-020.md resultó imposible de implementar tal cual — no hubo que reportar contradicción ni improvisar cambio de alcance | Verificado archivo por archivo antes de escribir código
2026-08-25 | orion-tester | 26/26 criterios PASS | Ver test-results-020.md. Verificación no solo por código: se levantó la app real en QWebEngineView offscreen (mismo mecanismo de tests/test_webview_smoke.py) con window.show()+waitExposed, se emitieron señales reales del bridge (tasks_loaded con 40 tareas, message_appended, conversation_cleared) y se redimensionó la ventana real (1024×640 y 1400×800) para confirmar en DOM/CSS vivo: 3 columnas sin superposición, #side-panel 300px y su colapso a display:none bajo 1200px, #tasks-btn===null, panel de Tareas con contenido sin click, orden Monitor→Tareas, monitor sin elementos interactivos, .panel-list-flex con max-height:none, cadena min-height:0 en los 3 niveles, lista larga sin empujar el monitor, reubicación real de #chips-row entre composer y empty-state, y apertura real del modal de Proyectos. Script ad-hoc (tests/test_req020_manual_verification.py) usado solo como arnés temporal y borrado al terminar, no queda en el repo.
2026-08-25 | orion-tester | Suite completa 538 passed/2 failed, idéntico a baseline-020.md (mismos 2 fallos de test_llm_provider.py por ModuleNotFoundError: anthropic) | Sin regresiones nuevas; subset test_webview_* 194/194, test_webview_safe_dom_insertion+test_webview_theme 30/30, ambos igual al baseline
2026-08-25 | orion-qa | QA APROBADO, sin hallazgos de seguridad/logging/consistencia | Ver qa-audit-020.md para el detalle completo; humano debe hacer la prueba manual final antes de LISTO_PARA_COMMIT

## Descartado (y por qué)
- Clonar literalmente el layout/estética de la referencia "JARVIS-OS": descartado por el
  propio humano al plantear el REQ — NODDOO tiene otra identidad visual ya establecida.
- Conectar datos reales de CPU/memoria/red al panel de Monitor de sistema dentro de este REQ:
  descartado por decisión del humano (pregunta 2) — se resuelve como REQ futuro de categoría
  CORE/INTEGRACION para no mezclar telemetría del sistema operativo con un REQ de
  reorganización visual.
- Adoptar el tema claro + acento cian de la referencia, o cualquier decoración tipo HUD que
  implique tokens nuevos: descartado por decisión del humano (pregunta 3) — se mantiene 100%
  la paleta/tokens actuales de NODDOO.
- (orion-ui) Barras de progreso, mini-sparklines y grid de stats (uptime/núcleos/temperatura/
  latencia) para el panel de Monitor de sistema: descartado — es exactamente la decoración
  "tipo HUD con datos simulados" que SPEC-020 excluye explícitamente; el placeholder queda
  100% texto estático (`.panel-empty` reutilizado tal cual).
- (orion-ui) Ícono decorativo para el título de "Monitor de sistema": descartado, a diferencia
  de Tareas/Proyectos/Configuración que sí ganan ícono de cabecera — ver Decisiones tomadas.
- (orion-ui) Agrupación por estado (Pendientes/Completadas) en la lista de Tareas replicada a
  Proyectos: descartado en este REQ — ver Decisiones tomadas, requiere decisión de
  `orion-architect` si se retoma a futuro.
- (orion-ui) Corregir el hover/focus temático de `.panel-close-btn` en Proyectos/Configuración:
  descartado para este REQ — es una carencia preexistente no causada por REQ-020, corregirla
  ampliaría el alcance aprobado sin necesidad.

## Asumidos pendientes de confirmar
- (RESUELTO — ver Decisiones tomadas) Si el panel de "Tareas" pasa a panel persistente.
- (RESUELTO — ver Decisiones tomadas) Si conviene un panel de monitor de sistema y con qué
  alcance de datos.
- (RESUELTO — ver Decisiones tomadas) Alcance del panel de "Proyectos"/"Configuración".
- (RESUELTO — ver Decisiones tomadas) Qué elementos estéticos de la referencia se adoptan.
- (RESUELTO — ✅ APROBADO 2026-08-25) Ubicación espacial de la columna derecha: se agrega a
  la derecha del chat (sidebar izquierdo intacto), apilando Monitor de sistema + Tareas, en
  vez de replicar literalmente "monitor a la izquierda" de la referencia (chocaría con el
  sidebar de conversaciones ya existente). Ver SPEC-020.md, ASUMIDO 1.
- (RESUELTO — ✅ APROBADO 2026-08-25) El panel "Memoria/Conocimiento" de la referencia queda
  fuera de alcance de REQ-020 (no hay backend hoy que exponga `memory.db`/
  `semantic_memory.db` como lista navegable). Ver SPEC-020.md, ASUMIDO 2.
- (RESUELTO — ✅ APROBADO 2026-08-25) La pestaña "Registros" del panel de Tareas/Registros de
  la referencia queda fuera de alcance (NODDOO no tiene visor de logs para el usuario final).
  Ver SPEC-020.md, ASUMIDO 3.
- (RESUELTO — ✅ APROBADO 2026-08-25) Interpretación concreta de "adaptar Proyectos/
  Configuración al mismo criterio" (mismo lenguaje visual de cabecera/tarjeta, sin volverlos
  persistentes ni tocar su contrato con el bridge). Ver SPEC-020.md, ASUMIDO 4.

Ningún asumido queda pendiente — los 8 (4 preguntas originales + 4 ASUMIDOs nuevos) están
aprobados. Los que persisten en esta sección quedan documentados solo como referencia
histórica de qué se decidió y por qué, no como huecos abiertos.

## Riesgos activos
- Riesgo de scope creep: la referencia visual tiene mucho contenido (monitor de sistema,
  memoria/conocimiento, tareas/registros) — `orion-spec` acotó en SPEC-020.md qué entra en
  este REQ (monitor placeholder + tareas persistentes) y qué queda para REQs futuros (memoria/
  conocimiento, registros, telemetría real).
- Sistema de tokens de doble fuente (`theme.py` / `theme.css`) tiene test de drift
  (`tests/test_webview_theme.py`) — SPEC-020.md fija como criterio de aceptación (CA-15/CA-16)
  que este REQ no toca ninguna de las dos fuentes, así que el riesgo de drift queda mitigado
  por diseño en el alcance, no solo por disciplina de implementación.
- Cambio de comportamiento de carga: `tasks_panel.js` pasa de carga perezosa (al abrir el
  modal) a carga en `bootstrap()` — revierte el criterio de SPEC-016 (CA-12 equivalente) para
  Tareas específicamente. Documentado explícitamente en SPEC-020.md para que `orion-tester`
  no lo confunda con una regresión.
- (orion-baseline) Ningún archivo de `ui/webview/` está modificado en el working tree hoy —
  el código leído para el baseline es exactamente el del commit `9f4235f`. Los REQ-007/012/
  013/014/016/017/018/019, todos EN_QA/EN_PRUEBAS sin commitear según `requerimientos.csv`, no
  tienen huella en `ui/webview/frontend/` en este momento, así que no hay riesgo de confundir
  trabajo ajeno con el de REQ-020 en esa carpeta — pero si en una sesión futura aparecen
  cambios ahí sin atribución clara, revisar de qué REQ son antes de tocarlos u atribuírselos a
  este REQ.
- (orion-baseline) `tests/test_llm_provider.py` tiene 2 fallos preexistentes por
  `ModuleNotFoundError: No module named 'anthropic'` (falta el paquete en el entorno local) —
  no atribuibles a REQ-020, no tocan `ui/webview/`. Ver `baseline-020.md` para el detalle
  completo.
- (orion-ui) Cadena de `min-height:0` (`#side-panel` → `#tasks-panel-mount` →
  `.panel-list-flex`) es imprescindible para que el scroll interno de la lista de tareas
  funcione sin empujar `#monitor-panel-section` — un bug clásico de flexbox si `orion-dev`
  omite alguno de los tres niveles al implementar. Ver `ui-design-020.md`, tabla "Riesgos de
  regresión visual", para el detalle y cómo verificarlo.
- (orion-ui) `.panel-list-flex` requiere que `tasks_panel.js` arme la lista con AMBAS clases
  (`"panel-list panel-list-flex"`), no solo `"panel-list"` — si se omite, la lista de tareas
  fija hereda el `max-height:320px` pensado para el modal y no ocupa el espacio disponible de
  `#tasks-panel-mount`. `orion-tester` debe verificar `getComputedStyle(...).maxHeight` sea
  `"none"` dentro de `#tasks-panel-mount`.

## Log de transiciones
2026-08-25 | — → NUEVO | orion-coordinador | REQ creado
2026-08-25 | NUEVO → NUEVO (sin cambio de estado tracker) | orion-spec | Preguntas de clarificación 1-4 resueltas con el humano y SPEC-020.md redactada; queda ⏸️ ESPERANDO VALIDACIÓN — no se avanza a SPEC_APROBADO hasta que el humano confirme también los 4 ASUMIDOs nuevos señalados en la SPEC
2026-08-25 | NUEVO → SPEC_APROBADO | orion-spec | Humano aprobó SPEC-020 completa (4 preguntas originales + 4 ASUMIDOs nuevos), aprobación trasladada por `orion-coordinador`; handoff emitido a `orion-baseline`
2026-08-25 | SPEC_APROBADO → EN_ARQUITECTURA | orion-baseline | Baseline documentado en `baseline-020.md` (9 archivos previstos, layout actual de 2 zonas, 2 fallos preexistentes ajenos a este REQ); handoff emitido a `orion-architect`, quien debe delegar a `orion-ui` antes de `orion-dev` por ser REQ de categoría UI con referencia visual
2026-08-25 | EN_ARQUITECTURA → ARQUITECTURA_APROBADA | orion-architect | Arquitectura redactada en `arquitectura-020.md` (3 columnas flex, `#side-panel` 300px con colapso CSS a <1200px, `#tasks-btn` eliminado, `relocateChipsRow()` para los chips del estado vacío, cero cambios a `bridge.py`/`theme.py`/`gui_state.py`) y aprobada por el humano en su totalidad, sin ajustes, aprobación trasladada por `orion-coordinador`; handoff emitido a `orion-ui` (no a `orion-dev` directamente — categoría UI con referencia visual)
2026-08-25 | ARQUITECTURA_APROBADA → ARQUITECTURA_APROBADA (sin cambio de estado tracker) | orion-ui | Diseño visual detallado en `ui-design-020.md` sobre la arquitectura ya aprobada (tokens 100% reutilizados, box model exacto de `#side-panel`/`#monitor-panel-section`/`#tasks-panel-mount`, 3 clases CSS nuevas sin color nuevo, estados por componente, accesibilidad básica revisada con una corrección concreta de foco visible). Ningún punto contradijo o requirió algo no cubierto por la arquitectura — no hubo que devolver nada al humano. Ajuste de layout ya aprobado, no rediseño — no requiere nueva aprobación humana; handoff emitido directo a `orion-dev` (`orion-security` no aplica a este REQ)
2026-08-25 | ARQUITECTURA_APROBADA → EN_PRUEBAS | orion-dev | Implementación completa de arquitectura-020.md + ui-design-020.md sin desviaciones de alcance (ver desarrollo-log-020.md); verificación local sin regresiones (py_compile OK, 538 passed/2 failed igual al baseline, subset test_webview_* 194/194); handoff emitido a `orion-tester`
2026-08-25 | EN_PRUEBAS → EN_QA | orion-tester | 26/26 criterios de SPEC-020 en PASS, verificados en DOM/CSS/JS real (QWebEngineView offscreen) además de código; suite completa 538 passed/2 failed idéntico a baseline, cero fallos nuevos (ver test-results-020.md); handoff emitido a `orion-qa`
2026-08-25 | EN_QA → EN_QA (sin cambio de estado tracker) | orion-qa | QA APROBADO — auditoría de seguridad sin hallazgos (sin secretos, sin `innerHTML` nuevo fuera del preexistente y ya cubierto de `chat.js`, flujo de confirmación amarilla de `requestDeleteTask` verificado intacto tras el paso de modal a panel persistente, cero tokens/colores nuevos), logging sin regresión (sin código nuevo propenso a error, cero Python tocado), código consistente sin dead code ni prints de debug. Verificación propia además del reporte de `orion-tester`: `git diff` completo de los 12 archivos frontend, re-ejecución independiente de `python -m py_compile main.py` (OK) y `pytest tests/test_webview_safe_dom_insertion.py tests/test_webview_theme.py` (30/30). Ver `qa-audit-020.md`. Queda pendiente la prueba manual final del humano antes de pasar a `LISTO_PARA_COMMIT` — no se entrega mensaje de commit todavía

2026-09-18 | → LISTO_PARA_COMMIT | conversación principal (sesión nocturna autorizada por Johan) | Sincronización del tracker con `main`: el código de este REQ ya está commiteado y mergeado y la evidencia (QA aprobado y/o suite en verde registrada en este contexto) estaba completa. Solo cambia el estado; no se toca código.
