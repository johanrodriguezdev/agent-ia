# Contexto REQ-016 — Mejora visual de menú/sidebar + tipografía + nodos/tareas + proyectos

## Resumen ejecutivo
Sobre la base visual construida en REQ-015 (`ui/webview/frontend/`, WebView embebido), rediseñar
el menú/sidebar acercándolo a una referencia visual tipo DeepSeek (barra superior de iconos
agrupados en píldora, colapso más profesional), adoptar la tipografía sans-serif redondeada de
esa referencia en toda la app, y agregar dos opciones nuevas al menú — "programar Nodos o tareas"
y "crear proyectos" — cuyo alcance exacto debe clarificarse con Johan antes de definir criterios
de aceptación.

## Estado actual
- **Estado tracker:** SPEC_APROBADO (sin cambio — la transición a EN_ARQUITECTURA le corresponde a
  `orion-architect` al aprobar su propuesta, no a `orion-baseline`; CSV no tocado en esta sesión)
- **Último agente:** orion-baseline
- **Fecha última actualización:** 2026-08-20 (baseline-016.md completado — ver
  `workspace/adjuntos/REQ-016/origen/baseline-016.md`)
- **Rama git:** feature/REQ-015-webview-ui (confirmado por `git branch --show-current`; sigue siendo
  la rama activa del working tree — REQ-016 todavía no tiene rama propia, a definir con el humano)
- **Categoría:** UI
- **Tipo de cambio:** MEJORA + FEATURE_NUEVA (mezcla: mejora visual sobre lo existente + dos
  funcionalidades de menú aún no definidas)

## Petición original de Johan (verbatim)
> "Bueno Sigue mejorando la interfaz de escritorio para que el menu se vea así, adicional de que
> en el menu tenga una opción de programar Nodos o tareas, crear proyectos, y que la barra se vea
> más profesional al contraerse, además quiero que utilicemos la tipografía de la imagen de
> referencia."

Johan adjuntó una imagen de referencia (captura de la app "DeepSeek", pantalla de inicio de chat).
Descripción íntegra de la imagen (transcrita por el orquestador, que sí pudo verla):

## Descripción de la imagen de referencia (íntegra)
- Tema claro, fondo blanco, estética minimalista tipo DeepSeek/ChatGPT.
- Esquina superior izquierda: logo pequeño de la app (marca abstracta azul, forma tipo
  ballena/delfín) junto a una barra de herramientas en forma de píldora redondeada (fondo blanco,
  borde sutil, sombra leve) que agrupa 3 iconos: (1) toggle de sidebar (icono de dos rectángulos
  verticales/panel lateral), (2) búsqueda (lupa), (3) nuevo chat/item (círculo con "+"). Los 3
  iconos están dentro de UN SOLO contenedor píldora unificado, no botones sueltos.
- Centro de la pantalla (aprox. tercio superior del área de contenido): logo + encabezado grande
  en negrita "Start chatting with Instant", tipografía sans-serif redondeada, texto casi negro.
- Debajo del encabezado: un control segmentado en forma de píldora con 3 pestañas: "⚡ Instant"
  (activa — fondo lavanda/azul claro, texto azul, negrita), "🛡 Expert" (icono + label, inactiva,
  blanco/gris), "🖼 Vision" (icono + label, inactiva). Todo el control es una sola píldora con
  borde fino.
- Debajo: un input de mensaje muy grande, rectángulo con esquinas MUY redondeadas (~24px),
  placeholder gris "Message DeepSeek", padding generoso.
- Dentro del input, parte inferior: a la izquierda dos botones píldora — "⊗ DeepThink" y
  "🌐 Search" (Search está activo/resaltado en azul claro con texto azul) — a la derecha un icono
  de clip (adjuntar) y un botón circular sólido azul con flecha hacia arriba blanca (enviar).
- Estética general: mucho espacio en blanco, esquinas redondeadas en todos lados (12-24px), acento
  azul tipo periwinkle (~#4F6BFF), sombras muy sutiles, cero clutter visual, sin emojis reales
  (son iconos de línea).
- Tipografía: sans-serif geométrica/redondeada tipo Inter / Plus Jakarta Sans / General Sans /
  SF Pro Rounded — bold en encabezados, regular/medium en cuerpo, muy legible, look moderno y
  "friendly". Johan pide EXPLÍCITAMENTE adoptar esta tipografía para la app (hoy la app usa la
  fuente por defecto del sistema — revisar `ui/webview/frontend/css/theme.css` para confirmar qué
  se usa hoy).

## Pedido concreto desglosado (para que orion-spec lo convierta en criterios de aceptación)
1. Rediseñar visualmente el menú/sidebar (`ui/webview/frontend/*sidebar*`) para acercarse a la
   referencia: especialmente el agrupamiento de iconos de la barra superior en un contenedor tipo
   píldora unificado, y el pulido general (esquinas redondeadas, espaciado, acento de color).
2. Agregar al menú una opción nueva para "programar Nodos o tareas" — Johan no especificó el
   mecanismo exacto (¿scheduler visual, lista de tareas programadas, o conecta con algo de
   AUTOMATIZACION/rituales proactivos ya existente en el proyecto?). **Ambiguo — orion-spec DEBE
   preguntarle a Johan** qué significa "Nodos" en este contexto (¿nodos de un flujo/pipeline
   visual? ¿tareas programadas del scheduler existente? ¿algo nuevo?) antes de escribir la SPEC.
   Investigar primero si ya existe algo de "scheduler"/"rituales" en el backend (grep en el
   proyecto) para no proponer duplicar algo que ya existe.
3. Agregar al menú una opción nueva para "crear proyectos" — el concepto de "proyecto" no existe
   hoy en el modelo de datos (`ai/memory_manager.py` solo tiene conversaciones). **orion-spec debe
   preguntar a Johan** qué es un "proyecto" en este contexto (¿agrupador de conversaciones, tipo
   carpetas? ¿algo más?) antes de definir criterios de aceptación.
4. Que la barra lateral (sidebar) se vea "más profesional" al contraerse/colapsar — hoy el colapso
   solo oculta labels y deja iconos sueltos a 60px (ver `ui/webview/frontend/css/sidebar.css`
   líneas 17-26), sin el pulido de la referencia. Pedir a Johan o inferir del criterio de diseño
   qué "profesional" significa acá si no es obvio (probablemente: iconos centrados, tooltips, sin
   recortes bruscos, transición más suave).
5. Adoptar la tipografía de la imagen de referencia en toda la app (no solo el sidebar) — cambio
   de `ui/webview/frontend/css/theme.css` (o donde esté definida la fuente hoy) que afecta toda la
   superficie visual, no solo el menú.

## Decisiones tomadas
2026-08-20 | orion-coordinador | Categoría detectada: UI | Palabras clave: "interfaz", "menu",
"barra", "tipografía" — pedido es primariamente visual/UI. Overlap posible con AUTOMATIZACION por
"programar Nodos o tareas" (scheduler/rituales existentes) queda para que orion-spec lo determine
con más detalle tras clarificar con Johan qué significa "Nodos".
2026-08-20 | orion-coordinador | REQ abierto como REQ-016 nuevo, no como addendum de REQ-015 |
El alcance original de REQ-015 (migración QWidget → QWebEngineView, sin tocar funcionalidad) no
incluye mejoras visuales nuevas ni features nuevas (nodos/tareas, proyectos). Mismo criterio ya
usado en el proyecto para no mezclar alcances (REQ-014 y REQ-015 se mantuvieron separados).
2026-08-20 | orion-spec | Investigación de código previa a las preguntas de clarificación (para no
preguntar algo que el código ya responde) | Ver hallazgos detallados abajo.
2026-08-20 | orion-spec | Hallazgo — SÍ existe backend de tareas/scheduler, NO expuesto en la
UI de escritorio | `tasks/task_manager.py` (CRUD SQLite completo de tareas/recordatorios por
`user_id`: título, descripción, `due_date`, `remind_at`, `recurrence`, `status`, `priority`,
`channel` con parseo de fecha en lenguaje natural español vía `dateparser`) +
`tasks/task_scheduler.py` (`TaskScheduler`, hilo background, revisa tareas vencidas cada 60s y
notifica — hoy el canal de notificación es Telegram vía `set_telegram_app()`) +
`core/proactive_engine.py` (`ProactiveEngine`/`ProactiveTrigger`, triggers proactivos por
agente+horario+acción, concepto de "rituales" separado de las tareas del punto anterior). Ninguno
de los tres módulos tiene hoy ningún punto de entrada desde `ui/webview/frontend/` — solo se
alcanzan vía los bots de Telegram/Discord. Sirve como base real reutilizable para la parte
"tareas" del pedido de Johan.
2026-08-20 | orion-spec | Hallazgo — NO existe ningún concepto de "nodos" tipo flujo/pipeline
visual (n8n-style) en el código | Grep de "nodo/node/flow/pipeline visual/n8n" en todo el proyecto
no devolvió ningún módulo de flujos visuales ni de nodos conectables. Los únicos matches de "nodo"
son ruido: (a) `config.json`/`IDENTITY.md` — `"agent_name": "Noddoo"`, `"agent_pronunciation":
"Nodo"` (así se pronuncia el nombre del propio agente, sin ninguna relación con el pedido de
Johan — ver "Descartado" abajo), y (b) referencias genéricas a "node"/nodo DOM en JS/config sin
relación con el pedido.
2026-08-20 | orion-spec | Hallazgo — CSP del WebView no permite fuentes externas hoy |
`ui/webview/frontend/index.html` línea 5-6: `default-src 'self'; script-src 'self'; style-src
'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self';`. No hay directiva `font-src`
(cae en `default-src 'self'`), así que un `@font-face` apuntando a Google Fonts u otro CDN externo
sería bloqueado tanto para la hoja de estilos como para el archivo de fuente en sí. No hay
`@font-face` ni carpeta de fuentes locales en el proyecto hoy (confirmado — no hay `.woff*` bajo
`ui/webview/frontend/`).
2026-08-20 | orion-spec | Hallazgo — tipografía actual confirmada | `ui/webview/frontend/css/
reset.css` línea 18: `font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial,
sans-serif;` (system font stack, sin webfont propio) aplicado a toda la app vía `body`/reset.
`ui/webview/frontend/css/chat.css` línea 133 usa `"Cascadia Code", Consolas, "Courier New",
monospace` pero solo para bloques de código — no forma parte de la tipografía general.
2026-08-20 | orion-spec | Hallazgo — no existe ningún menú/dropdown/panel de configuración hoy en
el frontend | Revisado `ui/webview/frontend/js/` completo: la única estructura de navegación del
sidebar es header (logo + toggle colapso) → botón "Nuevo chat" → lista de conversaciones → "Ver
más" → footer (toggle de tema). No hay overflow menu, dropdown ni panel de settings donde las 2
opciones nuevas ("Nodos o tareas", "crear proyectos") tengan un lugar obvio por convención
existente — su ubicación debe decidirse explícitamente, no se puede inferir del código actual ni
de la referencia de DeepSeek (esa app tampoco tiene esas dos opciones).
2026-08-20 | orion-spec | Hallazgo — confirmado que no existe concepto de "proyecto" en el modelo
de datos | Revisado `ai/memory_manager.py` completo: el único campo parecido es `category` en la
tabla `memories` (valores como `general`/`interaction`/`summary`), que es una clasificación de
memoria semántica, no un agrupador de conversaciones. No hay tabla de proyectos, carpetas ni tags
sobre conversaciones.

2026-08-20 | orion-spec | Johan respondió las 4 preguntas de clarificación (traídas por el
orquestador) | Ver "Respuestas de Johan" abajo — quedaron como base directa de SPEC-016.md.
2026-08-20 | orion-spec | SPEC-016.md redactada completa (34 criterios de aceptación en 6 bloques:
header píldora, tareas, proyectos, colapso, tipografía, seguridad/regresión) | Ver
`workspace/adjuntos/REQ-016/spec/SPEC-016.md`. Estado: ⏸️ ESPERANDO VALIDACIÓN — el humano (Johan)
todavía no dio APROBADO/AJUSTAR/RECHAZADO explícito, así que el tracker (CSV) sigue en NUEVO, no se
avanza a SPEC_APROBADO hasta recibir esa aprobación.
2026-08-20 | orion-spec | Hallazgo nuevo durante la redacción — `task_scheduler` no arranca con la
app de escritorio | `tasks/task_scheduler.py` (revisión cada 60s + notificación voz/Toast) solo se
inicia hoy desde `channels/telegram_bot.py`; ni `main.py` ni `ui/webview/main_window.py` lo llaman.
Sin corregirlo, las tareas creadas desde el escritorio nunca notificarían si Telegram no está
activo — se agregó como CA-10 de SPEC-016 (llamar `task_scheduler.start()` en `main.py` junto a
`proactive_engine.start()`), documentado explícitamente como hallazgo no pedido por Johan pero
necesario para que "ver/marcar hechas" funcione de verdad — ver "Nota para el humano" al inicio de
SPEC-016.md.

## Respuestas de Johan (traídas por el orquestador, 2026-08-20)
1. "Nodos/tareas" → opción (a): exponer en el escritorio las tareas/recordatorios que ya existen en
   el backend (crear, ver, marcar hechas) — hoy solo usadas desde Telegram/Discord.
2. "Proyectos" → agrupador simple de conversaciones (carpetas): un proyecto agrupa conversaciones
   existentes, sin datos propios más allá del nombre y qué conversaciones contiene.
3. Alcance → funcional completo de punta a punta en este mismo REQ-016 (guardado real de datos), no
   placeholder.
4. Tipografía → Inter, empaquetada localmente (no CDN externo, respeta la CSP actual).
- Johan NO fue consultado puntualmente sobre: ubicación exacta de los 2 botones nuevos en el
  sidebar, y el detalle fino de "colapso más profesional" — quedan como ASUMIDO en SPEC-016.md
  (mismo patrón que los 7 ASUMIDO de SPEC-015), a confirmar/ajustar en el gate de aprobación.

2026-08-20 | orion-spec | SPEC aprobada | Aprobado por Johan, tal cual, sin ajustes — incluidos
todos los puntos marcados ASUMIDO en SPEC-016.md (ubicación de "Tareas"/"Proyectos" en el cuerpo
del sidebar, un proyecto por conversación a la vez, `delete_project` con confirmación YELLOW, sin
límite de proyectos/conversaciones, Cascadia Code sin cambios, búsqueda acotada a lo ya cargado, y
el fix de `task_scheduler.start()` en el arranque de escritorio).
2026-08-20 | orion-spec | Tipo de cambio: MEJORA + FEATURE_NUEVA | Identificado en la entrevista —
mezcla de mejora visual (header píldora, colapso, tipografía) con dos funcionalidades nuevas
(Tareas, Proyectos) confirmadas como full end-to-end por Johan, no placeholders.

## Descartado (y por qué)
- Tratar este pedido como addendum de REQ-015: descartado, REQ-015 sigue EN_QA esperando
  únicamente la prueba manual de Johan y no debe reabrirse ni mezclarse con este alcance nuevo.
- Interpretar "Nodos" como relacionado a `"agent_pronunciation": "Nodo"` (config.json/IDENTITY.md,
  la forma en que se pronuncia el nombre del agente "Noddoo"): descartado, es una coincidencia de
  palabra sin relación con el pedido de Johan de programar "Nodos o tareas" en el menú — se deja
  registrado acá para que ningún agente futuro lo confunda.
- Editor visual de flujos/nodos conectables tipo n8n para "Nodos": descartado, Johan confirmó
  opción (a) — exponer el backend de tareas ya existente, no una feature de flujos nueva.

## Asumidos pendientes de confirmar
- Qué significa exactamente "Nodos" en "programar Nodos o tareas" (ver punto 2 arriba) — sin
  confirmar, pendiente de que orion-spec pregunte a Johan. Ya investigado: no hay nada de "flujo
  visual" en el código; sí hay backend de tareas/scheduler y de triggers proactivos reutilizable
  (ver hallazgos arriba) — la pregunta a Johan ahora puede ser más específica/acotada a 3-4
  opciones concretas en vez de abierta.
- Qué es un "proyecto" en el contexto de este REQ (ver punto 3 arriba) — sin confirmar, pendiente
  de que orion-spec pregunte a Johan. Confirmado que hoy no existe nada parecido en el modelo de
  datos (ver hallazgo arriba).
- Qué significa "más profesional" para el colapso del sidebar más allá de lo inferido en el punto 4
  — a validar con Johan o con criterio de diseño si él no da más detalle.
- Si "programar Nodos o tareas" y "crear proyectos" deben quedar funcionando de punta a punta en
  este REQ-016 (con persistencia real) o si alcanza con agregar las entradas de menú + una
  pantalla/modal placeholder, dejando la funcionalidad completa (posible modelo de datos nuevo)
  para un REQ posterior de otra categoría (CORE/MEMORIA/AUTOMATIZACION). Depende de las respuestas
  anteriores — afecta si este REQ pasa por orion-architect con diseño de datos nuevo o si es un
  cambio puramente visual.
- Dónde deben ubicarse visualmente las 2 opciones nuevas dentro del menú/sidebar, dado que no hay
  overflow menu ni panel de settings existente hoy, y la referencia de DeepSeek tampoco las tiene
  (ver hallazgo arriba) — no hay de dónde inferir la ubicación.
- Si la tipografía nueva se trae como archivo de fuente empaquetado localmente en el repo (compatible
  con la CSP actual, sin tocarla) o si se prefiere evaluar abrir la CSP para permitir un CDN externo
  tipo Google Fonts (cambio de política de seguridad, no solo visual). Y si el monoespaciado de los
  bloques de código (`Cascadia Code`) se mantiene igual o también debe cambiar.

## Riesgos activos
- Este REQ toca los mismos archivos base que dejó REQ-015 (`ui/webview/frontend/`), que todavía no
  fue commiteado (REQ-015 EN_QA, pendiente de prueba manual). Hay que coordinar con Johan el orden
  de commits para no mezclar el diff de REQ-015 con el de REQ-016 en el working tree.
- "Programar Nodos o tareas" podría solaparse con funcionalidad de AUTOMATIZACION ya existente en
  el backend (rituales/scheduler) — evaluar antes de proponer algo nuevo, para no duplicar.
- 2026-08-20 | orion-baseline | Working tree compartido con el diff de REQ-015 sin commitear
  confirmado vigente (`git status --short` propio, mismos 12 `D`/varios `M`/`??` que
  `baseline-015.md`) — cualquier `git status`/`git diff` durante REQ-016 mezcla ambos REQs hasta que
  Johan decida el orden de commits.
- 2026-08-20 | orion-baseline | Diseño de "proyectos" en `ai/memory_manager.py` debe limpiar
  explícitamente referencias huérfanas al borrar una conversación — `delete_conversation()`
  (línea 502) hace `DELETE FROM memories WHERE conversation_id=? AND user_id=?` y no conoce ninguna
  tabla de proyectos; si el esquema nuevo guarda `conversation_id`, la limpieza debe diseñarla
  `orion-architect` explícitamente para no romper la segunda mitad de CA-21.
- 2026-08-20 | orion-baseline | Los 2 fallos pre-existentes de `tests/test_llm_provider.py`
  (`ModuleNotFoundError: No module named 'anthropic'`) reaparecerán en la corrida de `orion-tester`
  — ya documentados como no atribuibles a REQ-016 (dependencia del entorno, no relacionada con
  UI/tareas/proyectos), no deben generar un handoff de vuelta a `orion-dev`.

## Log de transiciones
2026-08-20 | — → NUEVO | orion-coordinador | REQ-016 creado a partir de pedido de mejora visual +
features nuevas de menú sobre la base de REQ-015. No toca ni cierra REQ-015.
2026-08-20 | NUEVO → NUEVO (sin cambio) | orion-spec | Sesión de investigación de código previa a
las preguntas de clarificación con Johan (ver hallazgos en "Decisiones tomadas" y preguntas
nuevas/refinadas en "Asumidos pendientes de confirmar"). Johan no estaba presente en esta sesión —
el estado tracker NO avanza todavía, sigue NUEVO, CSV sin tocar. La SPEC-016.md se redacta recién
en la próxima sesión, una vez que el orquestador traiga las respuestas de Johan.
2026-08-20 | NUEVO → NUEVO (sin cambio) | orion-spec | El orquestador trajo las respuestas de Johan
a las 4 preguntas críticas (ver "Respuestas de Johan"). SPEC-016.md redactada completa y entregada
para aprobación. El tracker sigue en NUEVO — todavía NO pasa a SPEC_APROBADO porque falta la
aprobación humana explícita (APROBADO/AJUSTAR/RECHAZADO) sobre la SPEC en sí, especialmente sobre
los puntos marcados ASUMIDO (ubicación de los 2 botones nuevos, detalle del colapso "profesional").
2026-08-20 | NUEVO → SPEC_APROBADO | orion-spec | Johan aprobó SPEC-016.md tal cual, sin ajustes,
incluidos todos los puntos ASUMIDO. SPEC-016.md marcada ✅ COMPLETADO. CSV actualizado vía
`update-tracker.mjs` (Estado=SPEC_APROBADO, Aprobacion_SPEC=APROBADO, Tipo_Cambio="MEJORA +
FEATURE_NUEVA"). Nota mecánica: `update-tracker.mjs` no permite saltar de NUEVO directo a
SPEC_APROBADO (máquina de estados exige el intermedio EN_SPEC) — orion-coordinador nunca había
escrito EN_SPEC al hacer el handoff original, así que este cierre aplicó NUEVO→EN_SPEC→SPEC_APROBADO
en dos llamadas consecutivas dentro de esta misma sesión de orion-spec, no como una fase separada.
Handoff emitido a `orion-baseline`.
2026-08-20 | SPEC_APROBADO → SPEC_APROBADO (sin cambio) | orion-baseline | Baseline completado:
estado actual del sistema documentado, 13 archivos previstos a modificar, 2 fallos pre-existentes
registrados (no atribuibles a este REQ). El tracker NO avanza — la transición a EN_ARQUITECTURA le
corresponde a `orion-architect` al aprobar su propuesta, no a `orion-baseline` (DoD de
`.claude/rules/definition-of-done.md` no incluye transición de estado para este agente). CSV sin
tocar. Ver `workspace/adjuntos/REQ-016/origen/baseline-016.md`. Handoff emitido a `orion-architect`.

2026-08-20 | orion-baseline | 13 archivos identificados a modificar (previsión) | Ver
`workspace/adjuntos/REQ-016/origen/baseline-016.md` — desglose completo por archivo.
2026-08-20 | orion-baseline | Verificación independiente del hallazgo de orion-spec sobre
`task_scheduler.start()` — CONFIRMADO, no se dio por bueno el reporte sin comprobarlo | Grep propio
de `task_scheduler`/`proactive_engine` en `main.py` y `ui/webview/main_window.py`: `main.py` solo
llama `proactive_engine.start()` (línea 104), cero matches de `task_scheduler` en ese archivo ni en
`main_window.py`. El único lugar del proyecto que llama `task_scheduler.start()` es
`channels/telegram_bot.py` líneas 834-836. El gap es real.
2026-08-20 | orion-baseline | Firmas de `tasks/task_manager.py` confirmadas contra el código, no
contra la SPEC | `create_task()`, `list_all_tasks()`, `complete_task()`, `delete_task()` existen tal
cual las asume SPEC-016 (líneas 300/372/403/416). `channel` es `str` libre — `"desktop"` ya funciona
sin modificar la función. `list_all_tasks()` ya ordena pendientes-primero-luego-fecha en SQL (CA-09
no requiere reimplementar el orden en JS).
2026-08-20 | orion-baseline | `_send_notification()` de `tasks/task_scheduler.py` confirmado — ya
tiene la rama `channel == "desktop"` (línea 151) que dispara `_notify_local()` (TTS + Toast) | No
requiere modificación, solo falta que el hilo arranque (ver hallazgo de arriba).
2026-08-20 | orion-baseline | Las 5 funciones de `ai/memory_manager.py` que CA-21 exige no romper
confirmadas con línea exacta | `new_conversation_id()` L179, `store_turn()` L222,
`list_conversations()` L254, `get_conversation_turns()` L293, `delete_conversation()` L502. Ningún
campo/tabla de "proyecto" existe hoy — único candidato parecido es `category` en `memories`
(clasificación de memoria semántica, no agrupador de conversaciones).
2026-08-20 | orion-baseline | Riesgo de diseño para orion-architect — `delete_conversation()` NO
limpia referencias externas | La función hace `DELETE FROM memories WHERE conversation_id=? AND
user_id=?` y no conoce ninguna tabla de proyectos. Si el esquema nuevo de proyectos guarda
`conversation_id`, el diseño de `orion-architect` debe encargarse explícitamente de no dejar
referencias huérfanas al borrar una conversación (exigido literal por la segunda mitad de CA-21) —
`delete_conversation()` no lo hace por sí sola.
2026-08-20 | orion-baseline | `delete_task`/`delete_project` NO están registradas en
`core/security_manager.py::_register_default_actions()` | Confirmado por grep — ningún match de
ninguna de las dos cadenas. `delete_conversation` sí está como `RiskLevel.YELLOW` (línea 311),
mismo patrón a replicar. `ChannelType.DESKTOP` ya permite `YELLOW` (línea 55), no requiere tocar la
matriz de canales.
2026-08-20 | orion-baseline | Gaps visuales de CA-22/CA-23 confirmados en el CSS/HTML actual, no
solo inferidos | `css/sidebar.css` no tiene ninguna regla que centre íconos de `.sidebar-action-btn`
en estado `.collapsed` (CA-22 es un gap real, no solo estético a mejorar). Ningún botón del sidebar
en `index.html` tiene atributo `title` hoy (CA-23 también es un gap real, no hay tooltips que
"mejorar", hay que agregarlos desde cero).
2026-08-20 | orion-baseline | Fallos pre-existentes registrados: 2 FAIL, no atribuibles a REQ-016 |
`tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` y
`test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto` — ambos `ModuleNotFoundError: No module
named 'anthropic'` (dependencia no instalada en el entorno, no relacionado con UI/tareas/proyectos).
365 passed, 2 failed en la corrida completa. `python -m py_compile` sobre los 7 módulos Python
afectados: sin errores. `tests/conftest.py` línea 38 — fix de `PYTEST_QT_API=pyqt6` (de REQ-015)
sigue aplicado en disco.
2026-08-20 | orion-baseline | Working tree confirmado — REQ-015 sigue sin commitear encima de esta
sesión, mismo estado que describe `baseline-015.md` | `git status --short` propio: mismos 12
archivos `D`, mismos `M`/`??` que ya documentó `orion-spec`. Rama activa: `feature/REQ-015-webview-ui`.
No hay nada que reconciliar de una sesión intermedia — el punto de partida real de REQ-016 es el
diff no commiteado de REQ-015, no `HEAD` limpio.

2026-08-20 | orion-architect | Propuesta técnica redactada completa (34 CA de SPEC-016 cubiertos,
§0-§15) | Ver `workspace/adjuntos/REQ-016/propuestas/arquitectura-016.md`. Sesión cortada dos veces
por error de API durante la redacción — retomada sin repetir la investigación ya hecha, escrita en
tramos con `Edit` para minimizar pérdida ante un tercer corte. Decisiones técnicas centrales (§0,
sin preferencia previa del humano):
- Esquema de "proyectos": 2 tablas nuevas (`projects`, `project_conversations`) en la misma DB
  (`ai/unified_memory.db`) — cero columnas nuevas en `memories`, cero líneas modificadas en las 5
  funciones que CA-21 protege (`new_conversation_id`, `store_turn`, `list_conversations`,
  `get_conversation_turns`, `delete_conversation`). `project_conversations.conversation_id` es
  `PRIMARY KEY` — CA-20 (una conversación, un proyecto a la vez) queda garantizado por el esquema,
  no por lógica de Python.
- Limpieza de huérfanos (segunda mitad de CA-21): se agrega en `Bridge._delete_conversation_flow()`
  (único call-site real de `memory.delete_conversation()` en todo el proyecto, confirmado por grep),
  no dentro de `delete_conversation()` en sí — esa función queda con cero líneas tocadas.
- Asignar conversación a proyecto (CA-16): desde un picker dentro del panel de Proyectos, alimentado
  por el estado ya cargado en `sidebar.js` — no un ícono nuevo por fila en `.conv-item` (evita tocar
  código de conversaciones ya validado por REQ-015 y protegido por CA-25).
- Tareas/Proyectos: modales con raíz propia (`#panel-modal-root`), separada de `#confirm-modal-root`
  — para que confirmar un borrado (`delete_task`/`delete_project`) no haga desaparecer el panel
  abierto detrás.
- `delete_task`/`delete_project` registradas `RiskLevel.YELLOW`, reutilizando exactamente el mismo
  `WebViewConfirmationAdapter`/modal genérico ya auditado para `delete_conversation` en REQ-015 —
  sin mecanismo de confirmación nuevo.
- Tipografía Inter: verificado en vivo (no asumido) contra la API real de GitHub — release `v4.1` de
  `rsms/inter` (SIL OFL 1.1), asset `Inter-4.1.zip`, nombres de archivo exactos de los 3 pesos
  (`Inter-Regular.woff2`, `Inter-Medium.woff2`, `Inter-Bold.woff2`) confirmados contra la hoja de
  estilos real del sitio oficial de Inter — descarga puntual de build-time, no CDN en runtime, CSP
  sin tocar.
- Evaluación de `orion-security` (§11): recomendación de NO invocarlo como paso dedicado — los 2
  puntos de seguridad de este REQ (2 acciones YELLOW nuevas, datos de proyecto sin secretos) son
  réplica mecánica de un patrón ya auditado en REQ-015 (`security-audit-015.md` Hallazgo C), no una
  decisión de política nueva. Recomendación aceptada por Johan en el gate de aprobación.

2026-08-20 | orion-architect | Descartado (y por qué) | Columna `project_id` nueva en `memories` (en
vez de tablas separadas): descartada — cada conversación tiene múltiples filas en `memories` (una por
turno), así que una columna ahí obligaría a un `UPDATE` sobre N filas por cada asignación/reasignación
y reabriría el riesgo de tocar la tabla que CA-21 protege. Ícono de asignación a proyecto por fila en
`.conv-item`: descartado — tocaría `sidebar.js::buildConversationItem()`, código ya validado por
REQ-015/CA-06..CA-11 y protegido por CA-25 de SPEC-016; el picker dentro del panel de Proyectos logra
lo mismo sin tocarlo. Panel de Tareas/Proyectos embebido en el cuerpo del sidebar (en vez de modal):
descartado — reestructuraría el layout del sidebar ya aprobado en REQ-015 sin necesidad. Compartir
`#confirm-modal-root` para los paneles nuevos: descartado — `root.replaceChildren()` del modal de
confirmación borraría el panel de Tareas/Proyectos abierto detrás.

2026-08-20 | orion-architect | Arquitectura aprobada | Aprobado por Johan, tal cual, sin ajustes —
incluidas todas las decisiones de §0 y la recomendación de §11 (no pasa por `orion-security`
dedicado). `arquitectura-016.md` marcada ✅ APROBADA.

## Estado actual
- Estado tracker: ARQUITECTURA_APROBADA
- Último agente: orion-architect
- Rama git: feature/REQ-015-webview-ui (sin cambio — REQ-016 sigue sin rama propia; ninguna instrucción
  de este gate de aprobación pidió asignarle una, sigue pendiente de decisión explícita del humano
  sobre el orden de commits respecto a REQ-015, mismo riesgo activo ya registrado por `orion-baseline`)

## Log de transiciones
2026-08-20 | SPEC_APROBADO → EN_BASELINE → EN_ARQUITECTURA → ARQUITECTURA_APROBADA | orion-architect |
`arquitectura-016.md` completa y aprobada por Johan. CSV actualizado vía `update-tracker.mjs`
(Estado=ARQUITECTURA_APROBADA, Aprobacion_Arquitectura=APROBADO). Nota mecánica (mismo patrón ya
documentado por `orion-spec` en este REQ): `update-tracker.mjs` no permite saltar directo de
SPEC_APROBADO a ARQUITECTURA_APROBADA (la máquina de estados exige los intermedios EN_BASELINE/
EN_ARQUITECTURA, que ni `orion-baseline` ni el handoff original escribieron) — se aplicaron las 3
transiciones en llamadas consecutivas dentro de esta misma sesión, no como fases separadas reales.
`orion-security` NO se invoca (Johan confirmó la recomendación de §11). Handoff emitido directo a
`orion-dev`.

2026-08-20 | orion-dev | Implementación completa de las 34 CA de SPEC-016 exactamente según
arquitectura-016.md (§1-§14), sin desviaciones de esquema/contrato/seguridad | Ver
`workspace/adjuntos/REQ-016/propuestas/desarrollo-log-016.md` para el detalle completo por archivo.
Resumen: 2 tablas nuevas (`projects`, `project_conversations`) en `ai/unified_memory.db` con 6
métodos nuevos en `UnifiedMemory`, cero líneas tocadas en las 5 funciones protegidas por CA-21
(verificado con test de no-regresión dedicado); 10 `pyqtSlot`/4 `pyqtSignal` nuevos en
`ui/webview/bridge.py` + docstring extendido (CA-34); `delete_task`/`delete_project` registradas
`RiskLevel.YELLOW` en `core/security_manager.py`, reutilizando `WebViewConfirmationAdapter` ya
existente; `task_scheduler.start()`/`stop()` agregados a `main.py` junto a `proactive_engine`
(CA-10); header en píldora + búsqueda client-side + colapso pulido + tipografía Inter en el
frontend; 2 módulos JS nuevos (`tasks_panel.js`, `projects_panel.js`) con modales sobre
`#panel-modal-root` (raíz separada de `#confirm-modal-root`, §0.3), insertando todo texto no
confiable solo vía `textContent`/`setAttribute`.
2026-08-20 | orion-dev | Tipografía Inter — descarga real exitosa, no se necesitó el camino
alternativo de §9.1 | Este entorno sí tuvo acceso de red al momento de implementar: se descargó
`Inter-4.1.zip` (33.707.794 bytes, coincide con el tamaño documentado en la arquitectura) desde
`https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip`, se verificaron los 3 `.woff2`
como binarios WOFF2 reales (`file` reporta "Web Open Font Format (Version 2)... version 4.66", no
HTML de error) antes de vendorizarlos en `ui/webview/frontend/fonts/` junto con
`LICENSE-OFL.txt` (SIL OFL 1.1). No aplicó el escenario "sin acceso a internet" que preveía la
arquitectura — se documenta acá solo para que quede registrado que se verificó en vivo, no asumido.
2026-08-20 | orion-dev | 4 ajustes menores de implementación respecto al texto literal de la
arquitectura, ninguno cambia esquema/contrato/seguridad | Ver "Decisiones de implementación" en
`desarrollo-log-016.md` para el detalle completo con motivo de cada uno: (1) se retiró el bloque CSS
`#sidebar-collapse-toggle` preexistente en `sidebar.css` — su especificidad de ID pisaba el
`.pill-btn` nuevo y rompía la unificación visual de CA-01/CA-02, el comportamiento lo sigue dando
`.pill-btn`; (2) `onProjectRemoved` en `app.js` invoca una función real
(`handleProjectRemoved`, exportada de `projects_panel.js`) en vez del comentario-placeholder del
snippet de §8.4; (3) estado vacío (`.panel-empty`) agregado a la vista de detalle de un proyecto sin
conversaciones, por consistencia con `renderTasks([])`/`renderProjects([])`; (4) el picker de
asignación cierra con click fuera del modal, mismo patrón que los otros 3 overlays del archivo.
2026-08-20 | orion-dev | Verificación local completa, sin regresiones | `python -m py_compile` sobre
los 4 módulos Python tocados sin errores (CA-31); los 5 `.js` nuevos/modificados verificados con
`node --check` como módulo ES sin errores de sintaxis; `python -m pytest tests/ --tb=short -q` →
420 passed, 2 failed — los 2 fallos son exactamente los mismos pre-existentes de
`tests/test_llm_provider.py` (`ModuleNotFoundError: No module named 'anthropic'`) documentados en
`baseline-016.md`, no atribuibles a este REQ. Los +55 tests nuevos (17 en
`test_memory_manager_projects.py`, 17 nuevos en `test_webview_bridge.py`, 6 nuevos en
`test_security_manager.py`, extensión paramétrica de `test_webview_safe_dom_insertion.py` sobre los
2 archivos JS nuevos) pasan todos.

2026-08-20 | orion-dev | CSV actualizado vía `update-tracker.mjs` (Estado=EN_PRUEBAS) | Nota
mecánica (mismo patrón ya documentado por `orion-spec`/`orion-architect` en este REQ):
`update-tracker.mjs` no permite saltar directo de ARQUITECTURA_APROBADA a EN_PRUEBAS (la máquina de
estados exige el intermedio EN_DESARROLLO) — se aplicaron ambas transiciones en llamadas
consecutivas dentro de esta misma sesión. Handoff emitido a `orion-tester`.

## Estado actual
- Estado tracker: EN_PRUEBAS
- Último agente: orion-dev
- Rama git: feature/REQ-015-webview-ui (sin cambio — sigue sin commitear nada de REQ-015 ni REQ-016,
  tal como decidió Johan explícitamente; orion-dev no ejecutó git add/commit en ningún momento)

2026-08-20 | orion-tester | 34/34 criterios PASS, verificados por lectura directa del código real
(no por confianza en lo reportado por orion-dev) | Ver
`workspace/adjuntos/REQ-016/pruebas/test-results-016.md` para el detalle completo por CA. Resumen de
lo verificado independientemente (no solo revalidado el reporte de orion-dev):
- Compilación: `python -m py_compile` sobre los 4 módulos Python — OK, corrido de forma
  independiente. `node --input-type=module --check` sobre los 5 `.js` — OK (nota: `node --check`
  plano falla en los 5 porque el repo no tiene `package.json` con `"type":"module"`; se necesita
  `--input-type=module` — mismo resultado que reportó orion-dev, confirmado que usa el mismo método).
- Suite completa: **420 passed, 2 failed**, corrida propia — conteo idéntico al reportado por
  orion-dev, no dado por bueno sin correrlo. Los 2 fallos son exactamente
  `test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` y
  `test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto` (`ModuleNotFoundError: No module named
  'anthropic'`), idénticos a los pre-existentes de `baseline-016.md`. Cero fallos nuevos.
- CA-21 (no-regresión): leídas íntegras las 5 funciones protegidas de `ai/memory_manager.py`
  (`new_conversation_id` L219, `store_turn` L262, `list_conversations` L294, `get_conversation_turns`
  L333, `delete_conversation` L542) — cero referencias a `projects`/`project_conversations`, cuerpo
  igual al documentado por orion-baseline. Confirmado que la limpieza de huérfanos vive en
  `Bridge._delete_conversation_flow()` (`ui/webview/bridge.py` L260-277,
  `memory.unassign_conversation_from_project()` llamado DESPUÉS de `delete_conversation()`, nunca
  dentro). Tests dedicados corridos en aislamiento (no solo mirados): test de no-regresión de las 5
  funciones PASS, y `test_delete_conversation_no_limpia_project_conversations_por_si_sola` PASS
  (confirma con una fila real que `delete_conversation()` no limpia `project_conversations` por sí
  sola).
- CA-08/CA-18/CA-33: corridos en aislamiento los tests que mockean
  `security_manager.require_confirmation` devolviendo `False` — confirmado que
  `task_manager.delete_task`/`memory.delete_project` **nunca** se invocan en ese caso (no solo que el
  código "parece" tener el guard, sino que el test lo prueba en runtime). Ambos PASS.
- CA-20: verificación física adicional a nivel SQLite (no solo lectura del schema) — script standalone
  confirma que un `INSERT` crudo duplicado sobre la misma `conversation_id` en `project_conversations`
  es rechazado por SQLite con `IntegrityError: UNIQUE constraint failed` (la `PRIMARY KEY` hace la
  doble asignación físicamente imposible, no solo evitada por lógica Python), y que `INSERT OR
  REPLACE` reasigna sin duplicar filas.
- §10 (DOM seguro): grep de `innerHTML|insertAdjacentHTML|eval\(|document\.write` sobre
  `tasks_panel.js`/`projects_panel.js` — cero resultados reales (solo menciones en comentarios).
  `_MUST_NOT_USE_INNERHTML` de `test_webview_safe_dom_insertion.py` confirmado extendido con los 2
  archivos nuevos.
- CA-26..CA-30 (Inter): los 3 `.woff2` verificados con lectura binaria de los primeros 4 bytes — magic
  `wOF2` (0x774f4632) real en los 3 (tamaños 111.268/114.348/114.840 B, coinciden con lo reportado),
  no placeholders ni HTML de error. `@font-face` usa rutas relativas locales
  (`url("../fonts/Inter-*.woff2")`). CSP de `index.html` confirmada carácter por carácter idéntica a
  la que documentó orion-spec en este mismo contexto — sin cambios.
- CA-10: confirmado que `task_scheduler.start()` (main.py L106) está en el flujo real de arranque, no
  solo presente en el archivo — `if __name__ == "__main__":` siempre lanza `jarvis_runner()` en un
  hilo que llama `main(gui_active=...)`, tanto en modo GUI (WebView) como headless; no hay rama que la
  salte.
- Desviaciones de orion-dev (retiro de `#sidebar-collapse-toggle` CSS, `handleProjectRemoved()` real):
  ambas verificadas — justificación de especificidad CSS confirmada leyendo el CSS actual (no queda
  bloque `#sidebar-collapse-toggle {}` residual, el listener de colapso sigue intacto en
  `sidebar.js`); `handleProjectRemoved()` confirmada como función real exportada y wireada en
  `app.js`. Ninguna rompe SPEC-015/CA-06..CA-11 — confirmado corriendo en aislamiento los 48 tests de
  regresión visual (`test_webview_contrast.py`, `test_webview_smoke.py`, `test_webview_gui_state.py`,
  `test_webview_window_geometry.py`, `test_webview_theme.py`): 48 passed.
- Corroboración adicional no pedida explícitamente pero útil: comparación de `mtime` de archivos
  confirma qué se tocó realmente hoy (REQ-016, Aug-20) vs. qué viene intacto de REQ-015 (Aug-19) o de
  antes (Aug-18, caso de `tasks/task_manager.py`/`tasks/task_scheduler.py`) — corrobora
  independientemente (sin depender solo de `git diff`, contaminado por el diff de REQ-015 sin
  commitear) la lista de "sin modificar" que declaran arquitectura y desarrollo-log.

Veredicto: **34/34 criterios PASS**. Ver `test-results-016.md` para la tabla completa por CA.

## Log de transiciones
2026-08-20 | EN_PRUEBAS → EN_QA | orion-tester | 34/34 CA de SPEC-016 verificados PASS por lectura
directa del código, suite completa confirmada sin regresiones nuevas (420 passed/2 failed
pre-existentes). CSV actualizado vía `update-tracker.mjs` (Estado=EN_QA). Handoff emitido a
`orion-qa`.

## Estado actual
- Estado tracker: EN_QA
- Último agente: orion-tester
- Rama git: feature/REQ-015-webview-ui (sin cambio)

2026-08-20 | orion-qa | Auditoría de seguridad y calidad completada — APROBADO | Ver
`workspace/adjuntos/REQ-016/pruebas/qa-audit-016.md` para el detalle completo. `orion-security` no
corrió como paso dedicado en este REQ (decisión de Johan, §11 de `arquitectura-016.md`) — esta
auditoría fue el único gate de seguridad, con verificación reforzada de los 3 puntos que §11 dejó a
cargo de `orion-qa`, todos por lectura directa del código real y ejecución independiente de tests (no
por confianza en lo reportado por `orion-dev`/`orion-tester`):
- **`delete_task`/`delete_project` YELLOW y gate real:** confirmado en `core/security_manager.py`
  líneas 316-317; `_delete_task_flow()`/`_delete_project_flow()` de `bridge.py` llaman
  `require_confirmation()` antes de la acción destructiva; sin bypass posible desde JS (métodos
  privados sin `@pyqtSlot`, JS solo alcanza `request_delete_task`/`request_delete_project`).
  Verificado además en runtime: tests con `require_confirmation` mockeado en `False` confirman que
  `task_manager.delete_task`/`memory.delete_project` nunca se invocan — corridos en aislamiento, PASS.
- **SQL parametrizado:** las 6 funciones nuevas + 2 tablas de `ai/memory_manager.py` leídas íntegras
  — 8 queries nuevas, todas con placeholders `?`, cero f-string/concatenación.
- **DOM seguro:** `tasks_panel.js`/`projects_panel.js` leídos — cero `innerHTML`/`insertAdjacentHTML`
  reales, todo vía `textContent`. Test extendido de `test_webview_safe_dom_insertion.py` corrido en
  aislamiento (12 tests) — PASS.
- **No-regresión de `qa-audit-015.md`:** confirmado por `git diff HEAD` que
  `ui/webview/markdown_render.py` y `ui/webview/confirmation_adapter.py` no aparecen en el diff de
  REQ-016 (sanitización Markdown/XSS y timeout fail-closed de confirmación intactos); los 15
  `@pyqtSlot` originales de `bridge.py` siguen presentes sin cambios (+10 nuevos, total 25); CSP de
  `index.html` verificada carácter por carácter idéntica.
- **Checklist estándar:** sin secretos hardcodeados, sin `except: pass` silencioso agregado por este
  REQ (los pocos `except Exception:` sin log explícito hallados en los 4 archivos Python tocados son
  código preexistente ajeno al diff de REQ-016, confirmado con `git diff HEAD` acotado — mismo
  criterio que la arquitectura ya aplicó para el `except: pass` preexistente de
  `tasks/task_scheduler.py`), sin dead code, sin prints de debug nuevos, `requirements.txt` confirmado
  sin cambios atribuibles a REQ-016 (`git diff requirements.txt` solo muestra el bloque ya etiquetado
  REQ-015).
- **Compilación y suite, corridas propias independientes:** `py_compile` OK sobre los 4 módulos
  Python; `node --check` OK sobre los 5 `.js`; suite completa **420 passed, 2 failed** (mismos 2
  fallos pre-existentes de `test_llm_provider.py`, `anthropic` no instalado — cero fallos nuevos);
  subconjuntos aislados de seguridad (`test_security_manager.py` + `test_memory_manager_projects.py` +
  `test_webview_safe_dom_insertion.py` = 84 passed; subset tareas/proyectos de
  `test_webview_bridge.py` = 29 passed).

CSV actualizado vía `update-tracker.mjs` (Estado se mantiene en `EN_QA` — no se avanza a
`LISTO_PARA_COMMIT` hasta recibir el OK explícito de Johan tras la prueba manual, mismo criterio ya
usado en REQ-015). No se pidió la prueba manual directamente al humano desde este agente — por
instrucción explícita del orquestador, el resumen y la solicitud de prueba manual (REQ-016 junto con
REQ-015, misma sesión, ya que Johan decidió no separar los commits) los entrega el orquestador.

## Log de transiciones
2026-08-20 | EN_QA → EN_QA (sin cambio) | orion-qa | Auditoría de seguridad y calidad APROBADA — ver
`qa-audit-016.md`. Estado del tracker se mantiene en `EN_QA` a propósito (no hay columna `Aprobacion_QA`
en `requerimientos.csv`; la transición a `LISTO_PARA_COMMIT` queda pendiente del OK humano tras la
prueba manual). Handoff devuelto al orquestador (no a `orion-dev`, no directo a Johan).

## Estado actual
- Estado tracker: EN_QA
- Último agente: orion-qa
- Rama git: feature/REQ-015-webview-ui (sin cambio — sigue pendiente la decisión de Johan sobre el
  orden de commits respecto a REQ-015, ambos EN_QA a la espera de la misma sesión de prueba manual)

2026-08-20 | orion-dev | Addendum fuera de la máquina de estados del tracker — 2 bugs cosméticos
corregidos, hallados por el orquestador en verificación visual pre-prueba-manual (no por
orion-tester/orion-qa, ambos ya cerraron este REQ) | Ver "Addendum — 2026-08-20" en
`workspace/adjuntos/REQ-016/propuestas/desarrollo-log-016.md` para el detalle completo. Resumen:
(1) `#attachment-chip` quedaba siempre visible pese al atributo `hidden` de `index.html` — mismo
bug de especificidad CSS ya diagnosticado/corregido para `#typing-indicator` en REQ-015/CA-15
(selector de ID le gana a `[hidden]` del user-agent stylesheet); fix idéntico: se agregó
`#attachment-chip[hidden] { display: none; }` en `ui/webview/frontend/css/composer.css`, sin tocar
la regla `#attachment-chip{...}` existente. (2) El logo "NODDOO" de `#sidebar-logo` se recortaba a
mitad de carácter e ilegible en `#sidebar.collapsed` (60px) — contradice el pedido explícito de
Johan de que el colapso se vea "más profesional"; se agregó
`#sidebar.collapsed #sidebar-logo { display: none; }` en `ui/webview/frontend/css/sidebar.css`,
junto al bloque existente que ya oculta `.label`/`#conversation-list`/`#sidebar-footer`/
`.sidebar-load-more` en `.collapsed` (mismo criterio, sin reemplazar el logo por un ícono nuevo —
alcance no aprobado en arquitectura-016.md). Cambio 100% CSS, sin tocar Python ni el contrato del
bridge. `python -m py_compile` sobre los 4 módulos Python de REQ-016 sin errores; suite completa
`python -m pytest tests/` → **420 passed, 2 failed**, idéntico al resultado ya documentado por
orion-tester/orion-qa (mismos 2 fallos pre-existentes de `test_llm_provider.py`, `anthropic` no
instalado) — cero regresiones nuevas. Por instrucción explícita del orquestador: **Estado tracker
se mantiene en `EN_QA`** (CSV no tocado, `update-tracker.mjs` no invocado) — no se reabre el
pipeline hacia `orion-tester`/`orion-qa` porque el cambio es puramente cosmético/CSS. NO se ejecutó
git commit. Handoff devuelto al orquestador (Johan queda listo para su prueba manual, sin pasos
adicionales pendientes de este agente).

## Estado actual
- Estado tracker: EN_QA (sin cambio)
- Último agente: orion-dev (addendum cosmético, fuera de la máquina de estados del tracker)
- Rama git: feature/REQ-015-webview-ui (sin cambio)

2026-09-18 | → LISTO_PARA_COMMIT | conversación principal (sesión nocturna autorizada por Johan) | Sincronización del tracker con `main`: el código de este REQ ya está commiteado y mergeado y la evidencia (QA aprobado y/o suite en verde registrada en este contexto) estaba completa. Solo cambia el estado; no se toca código.
