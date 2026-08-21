# SPEC-016 — Sidebar tipo DeepSeek + Tareas programadas + Proyectos + tipografía Inter

**Estado:** ✅ COMPLETADO — Aprobado por Johan (2026-08-20), tal cual, sin ajustes (incluidos todos
los puntos marcados ASUMIDO: ubicación de los botones "Tareas"/"Proyectos" en el cuerpo del
sidebar, un proyecto por conversación a la vez, `delete_project` con confirmación YELLOW, sin
límite de cantidad de proyectos/conversaciones, Cascadia Code sin cambios en bloques de código,
búsqueda acotada a lo ya cargado en el sidebar, y el fix de `task_scheduler.start()` en el arranque
de escritorio)
**Categoría:** UI
**Tipo:** MEJORA + FEATURE_NUEVA
**Fecha:** 2026-08-20

## Nota para el humano — hallazgo de investigación que amplía el alcance mínimo necesario

Para que "programar tareas" (opción (a) que confirmaste) funcione de punta a punta como pediste
(no placeholder), se necesita un cambio que no estaba en tu pedido original ni en las preguntas que
te hicimos, pero es indispensable: **hoy `tasks/task_scheduler.py` (el hilo que revisa cada 60s si
hay recordatorios vencidos y los notifica por voz + Toast de Windows) nunca arranca cuando solo se
usa la app de escritorio** — solo se inicia desde `channels/telegram_bot.py` cuando el bot de
Telegram está configurado y corriendo. Verificado en `main.py`/`ui/webview/main_window.py`: ninguno
de los dos llama `task_scheduler.start()`. Si no se corrige, podrías crear y ver tareas desde el
escritorio, pero nunca recibirías el recordatorio si Telegram no está activo — la función quedaría
rota en la práctica. Esta SPEC incluye el fix (CA-10) como parte necesaria del criterio "ver/marcar
hechas" que aprobaste, no como alcance nuevo que decidí agregar por mi cuenta.

También recuperá el contexto de `workspace/adjuntos/REQ-016/REQ-016-context.md` — ahí está el
detalle completo de la investigación de código previa (qué ya existe de tareas/scheduler, qué NO
existe de "nodos" tipo flujo visual, la CSP actual, la tipografía actual) que sustenta las
decisiones de esta SPEC.

## Objetivo
Rediseñar el menú/sidebar de la app de escritorio acercándolo a la referencia visual de DeepSeek
(icon-pill unificado, colapso más pulido) con tipografía Inter en toda la app, y agregar dos
secciones funcionales nuevas al menú: **Tareas** (exponiendo en el escritorio el backend de
tareas/recordatorios que hoy solo usan Telegram/Discord) y **Proyectos** (agrupador simple de
conversaciones existentes, sin datos propios más allá del nombre) — ambas funcionando de punta a
punta con persistencia real, según confirmó Johan.

## Alcance
- Incluye:
  - Header del sidebar reagrupado en un contenedor tipo píldora único (fondo, borde sutil, sombra
    leve) con 3 controles: colapsar/expandir, búsqueda (nueva), nuevo chat — reemplazando el header
    actual (logo + toggle) y el botón "+ Nuevo chat" de ancho completo actual.
  - Búsqueda: filtra la lista de conversaciones ya cargada en el sidebar (cliente, por coincidencia
    de título) — ver ASUMIDO sobre el alcance exacto.
  - Colapso del sidebar más pulido: iconos centrados, tooltips nativos, sin recortes bruscos.
  - Tipografía Inter empaquetada localmente (archivos `.woff2` dentro del repo), aplicada a toda la
    app, respetando la CSP actual sin modificarla.
  - Sección **Tareas**: crear, listar (pendientes y completadas), marcar como completada y eliminar
    tareas desde el escritorio, reutilizando `tasks/task_manager.py` ya existente (sin necesidad de
    modificarlo — ya acepta `channel="desktop"`).
  - Que los recordatorios de tareas creadas desde el escritorio realmente se notifiquen (arrancar
    `task_scheduler` también desde el boot de la app de escritorio, no solo desde Telegram).
  - Sección **Proyectos**: crear proyecto (nombre), listar proyectos, asignar/desasignar
    conversaciones existentes a un proyecto, ver conversaciones agrupadas por proyecto, eliminar un
    proyecto (sin borrar las conversaciones que agrupaba). Requiere modelo de datos nuevo en/junto a
    `ai/memory_manager.py` — diseño exacto del esquema a cargo de `orion-architect`.
  - Nuevos `pyqtSlot`/señales en `ui/webview/bridge.py` para exponer lo anterior a JS, documentados
    explícitamente en su docstring (mismo patrón de whitelisting ya usado, CA-42 de SPEC-015).
  - Registrar `delete_task` y `delete_project` en `core/security_manager.py` como `RiskLevel.YELLOW`
    (mismo criterio ya usado para `delete_conversation`), con confirmación antes de ejecutarse.
- No incluye:
  - Editor visual de flujos/nodos conectables tipo n8n — Johan confirmó que "Nodos" se refería a
    exponer el backend de tareas ya existente (opción (a)), no a un editor de flujos nuevo.
  - Búsqueda de texto completo sobre todo el historial de conversaciones (más allá de lo ya cargado
    en la página actual del sidebar) — ver ASUMIDO.
  - Pertenencia de una conversación a más de un proyecto a la vez.
  - Edición de una tarea ya creada (cambiar título/fecha/prioridad) — `task_manager.py` no tiene
    `update_task()` hoy; ni Telegram lo expone. Fuera de alcance, igual que en el resto del proyecto.
  - Notificación in-app (dentro de la ventana, tipo badge/toast propio) de un recordatorio vencido —
    se mantiene el mecanismo ya existente (voz + Toast nativo de Windows).
  - Réplica de las secciones "Tareas"/"Proyectos" en los menús de Telegram/Discord (siguen con sus
    comandos actuales, sin cambios).
  - Cambiar la CSP (`ui/webview/frontend/index.html`) para permitir fuentes externas — Inter se
    empaqueta localmente, la CSP no se toca.
  - Panel derecho, autenticación multiusuario real, empaquetado como instalable — fuera de alcance,
    heredado sin cambios de REQ-015.
  - Cualquier modificación al diff de REQ-015 (todavía `EN_QA`, sin commitear) que no sea
    estrictamente necesaria para este REQ.

## Módulos afectados
- `ui/webview/frontend/index.html`, `css/sidebar.css`, `css/theme.css`, `css/reset.css`,
  `js/sidebar.js`, `js/app.js` — nuevo header en píldora, búsqueda, colapso pulido, tipografía Inter,
  2 secciones nuevas de menú.
- `ui/webview/frontend/fonts/` (carpeta nueva) — archivos `.woff2` de Inter (mínimo regular 400,
  medium 500, bold 700) empaquetados en el repo.
- `ui/webview/bridge.py` — nuevos `pyqtSlot`/`pyqtSignal` para tareas y proyectos, agregados a la
  lista explícita ya documentada en el docstring del módulo (§ whitelisting, CA-42 de SPEC-015). No
  se elimina ni modifica ningún slot existente de conversaciones.
- `tasks/task_manager.py` — **sin modificar**: ya expone `create_task()`, `list_all_tasks()`,
  `complete_task()`, `delete_task()` con todo lo necesario (`channel` ya acepta cualquier string,
  incluido `"desktop"`).
- `tasks/task_scheduler.py` — **sin modificar**: `_send_notification()` ya tiene la rama
  `channel == "desktop"` que dispara `_notify_local()` (TTS + Toast); solo falta que el hilo arranque.
- `main.py` — agregar `task_scheduler.start()` en `main()`, junto al `proactive_engine.start()` ya
  existente (línea ~104), para que el scheduler corra también cuando no hay bot de Telegram activo.
- `ai/memory_manager.py` — nuevo modelo de datos para "proyectos" (agrupador de conversaciones).
  Diseño exacto (tabla nueva vs. columna nueva, nombres de función) a cargo de `orion-architect`;
  esta SPEC exige que **no** se modifique el comportamiento de `new_conversation_id()`,
  `store_turn()`, `list_conversations()`, `get_conversation_turns()`, `delete_conversation()` ya
  existentes y ya consumidas por el bridge (no-regresión, mismo criterio que CA-30 de SPEC-015).
- `core/security_manager.py` — `_register_default_actions()`: agregar `delete_task` y
  `delete_project` como `RiskLevel.YELLOW`. No se reclasifica ninguna acción existente.
- Tests: nuevos tests para los slots de tareas/proyectos del bridge, el nuevo esquema de proyectos,
  y no-regresión del sidebar de conversaciones existente (CA-06..CA-11 de SPEC-015).

## Comportamiento actual vs deseado
| Actual | Deseado |
|---|---|
| Header del sidebar: logo + botón toggle sueltos; "+ Nuevo chat" es un botón de ancho completo aparte | Header en una sola píldora con 3 controles: toggle, búsqueda (nueva), nuevo chat |
| No existe búsqueda de conversaciones | Búsqueda filtra la lista ya cargada en el sidebar, por título |
| Colapsado (60px): iconos sueltos, sin tooltip, recorte de contenido | Colapsado: iconos centrados, con tooltip, sin recortes bruscos |
| Tipografía: stack de sistema (`-apple-system, Segoe UI, Roboto...`) | Inter (empaquetada localmente) como fuente principal, mismo stack de sistema como fallback |
| Backend de tareas (`tasks/task_manager.py`) solo alcanzable desde Telegram/Discord | Sección "Tareas" en el escritorio: crear, ver, completar, eliminar |
| `task_scheduler` solo arranca si el bot de Telegram está corriendo | `task_scheduler` arranca también con la app de escritorio — recordatorios se notifican siempre |
| No existe concepto de "proyecto" en los datos | Sección "Proyectos": crear, listar, agrupar/desagrupar conversaciones existentes, eliminar |

## Criterios de aceptación

### Header del sidebar — icon-pill unificado
- [ ] CA-01: Los controles de colapsar/expandir, búsqueda y "nuevo chat" quedan agrupados dentro de
      un único contenedor visual tipo píldora (fondo, borde sutil, sombra leve) — no como 3
      elementos sueltos ni el botón de ancho completo actual.
- [ ] CA-02: Cada uno de los 3 controles tiene su propio estado hover/activo distinguible dentro de
      la píldora.
- [ ] CA-03: El control de búsqueda, al usarse, filtra en tiempo real la lista de conversaciones ya
      cargada en el sidebar por coincidencia de texto en el título (ver ASUMIDO — alcance acotado a
      lo ya cargado, no a todo el historial).
- [ ] CA-04: "Nuevo chat" (ahora ícono dentro de la píldora) conserva exactamente el comportamiento
      ya validado en CA-07 de SPEC-015 (crea `conversation_id` nuevo, limpia el chat activo, no
      borra conversaciones anteriores).

### Tareas (sección nueva del menú)
- [ ] CA-05: Existe una entrada "Tareas" en el sidebar (ubicación — ver ASUMIDO) que abre una
      vista listando las tareas del usuario (`user_id="default"`, compartidas con lo que ya haya
      creado por Telegram/Discord — mismo `user_id`, sin separación por canal).
- [ ] CA-06: Se puede crear una tarea nueva desde un formulario (título obligatorio; fecha/hora,
      descripción y prioridad opcionales) — usa `task_manager.create_task(..., channel="desktop")`
      sin modificar la función.
- [ ] CA-07: Se puede marcar una tarea como completada (`task_manager.complete_task()`), y la vista
      distingue visualmente pendientes de completadas.
- [ ] CA-08: Se puede eliminar una tarea (`task_manager.delete_task()`), solo tras confirmación
      YELLOW vía `security_manager.require_confirmation("delete_task", ...)` — mismo patrón que
      `Bridge._delete_conversation_flow()` para conversaciones.
- [ ] CA-09: Las tareas se listan ordenadas igual que ya hace `list_all_tasks()` (pendientes
      primero, luego por fecha) — sin reimplementar el ordenamiento en JS.
- [ ] CA-10: `task_scheduler.start()` se invoca durante el arranque de la app de escritorio
      (`main.py`, junto a `proactive_engine.start()`), de forma que una tarea creada desde el
      escritorio se notifique (voz + Toast de Windows) aunque el bot de Telegram no esté
      configurado ni corriendo.
- [ ] CA-11: Crear/completar/eliminar una tarea desde el escritorio no rompe ni duplica el
      comportamiento ya existente de esas mismas tareas si además se gestionan desde Telegram
      (`user_id` compartido, sin tabla ni escritura paralela).
- [ ] CA-12: La vista de tareas no se activa/carga hasta que el usuario abre esa sección (no agrega
      trabajo al arranque de la app fuera de lo estrictamente necesario para CA-10).

### Proyectos (sección nueva del menú)
- [ ] CA-13: Existe una entrada "Proyectos" en el sidebar (ubicación — ver ASUMIDO).
- [ ] CA-14: Se puede crear un proyecto nuevo con un nombre no vacío.
- [ ] CA-15: Se listan los proyectos existentes del usuario.
- [ ] CA-16: Se puede asignar una conversación ya existente (del listado del sidebar) a un proyecto.
- [ ] CA-17: Existe una forma de ver las conversaciones agrupadas por proyecto (filtro o vista
      dedicada — mecanismo visual a decisión de `orion-architect`/`orion-dev`).
- [ ] CA-18: Se puede eliminar un proyecto, solo tras confirmación YELLOW vía
      `security_manager.require_confirmation("delete_project", ...)` — ver ASUMIDO sobre por qué se
      exige confirmación aunque no borre datos de conversación.
- [ ] CA-19: Eliminar un proyecto **no** borra ninguna de las conversaciones que agrupaba — quedan
      intactas y visibles en el listado general del sidebar, solo pierden la agrupación.
- [ ] CA-20: Una conversación pertenece a lo sumo a un proyecto a la vez (ver ASUMIDO); asignarla a
      un proyecto nuevo la reasigna, nunca queda en dos proyectos simultáneamente.
- [ ] CA-21: El nuevo modelo de datos de proyectos no modifica el comportamiento de
      `new_conversation_id()`, `store_turn()`, `list_conversations()`, `get_conversation_turns()` ni
      `delete_conversation()` ya existentes (no-regresión); y borrar una conversación
      (`delete_conversation()`, ya existente) que pertenece a un proyecto la remueve también de esa
      agrupación, sin dejar referencias huérfanas.

### Colapso del sidebar — pulido visual
- [ ] CA-22: En estado colapsado, todos los iconos (incluidos "Tareas" y "Proyectos") quedan
      centrados horizontalmente dentro del ancho de 60px — no pegados a un borde.
- [ ] CA-23: Cada ítem colapsado muestra un tooltip nativo (`title`) con su label completo al pasar
      el mouse.
- [ ] CA-24: La transición de colapso/expansión (200ms ya existente, CA-06 de SPEC-015) no recorta
      contenido de forma abrupta a mitad de la animación.
- [ ] CA-25 (no-regresión): El comportamiento de colapso/expansión ya validado en CA-06..CA-11 de
      SPEC-015 para el listado de conversaciones sigue funcionando igual.

### Tipografía Inter
- [ ] CA-26: Inter se agrega como archivo(s) `.woff2` locales dentro de `ui/webview/frontend/`
      (nueva carpeta), referenciados vía `@font-face` con ruta relativa — sin ningún `<link>` ni
      `@import` a un CDN externo (Google Fonts u otro), y sin modificar la CSP actual de
      `index.html`.
- [ ] CA-27: `font-family` del `body`/reset pasa a `Inter` primero, conservando
      `-apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif` como fallback si el
      archivo de fuente no carga.
- [ ] CA-28: Se incluyen al menos los pesos regular (400), medium (500) y bold (700) de Inter —
      encabezados en bold, cuerpo en regular/medium.
- [ ] CA-29: Los bloques de código siguen usando `"Cascadia Code", Consolas, "Courier New",
      monospace` sin cambios — Inter no reemplaza la fuente monoespaciada de código (ver ASUMIDO).
- [ ] CA-30 (no-regresión): Todo par texto/fondo sigue cumpliendo contraste WCAG AA (CA-36 de
      SPEC-015) con la tipografía nueva — el cambio de fuente no degrada el contraste ya validado.

### Seguridad y regresión general
- [ ] CA-31: `python -m py_compile` sobre todos los módulos Python nuevos/modificados no arroja
      errores.
- [ ] CA-32: La suite de tests completa sigue pasando (el conteo exacto de baseline lo documenta
      `orion-baseline`); cualquier cambio de contrato en un test existente se documenta
      explícitamente con el motivo.
- [ ] CA-33: Ni `delete_task` ni `delete_project` se ejecutan desde la UI sin pasar antes por
      `security_manager.require_confirmation()` (mismo criterio que CA-41 de SPEC-015) — ni JS ni el
      bridge auto-confirman ni bypassean el gate.
- [ ] CA-34: Los nuevos slots del bridge para tareas/proyectos quedan documentados explícitamente en
      el docstring de `ui/webview/bridge.py` (mismo patrón de whitelisting que CA-42 de SPEC-015);
      JS no invoca `tasks/task_manager.py` ni el nuevo código de proyectos de `ai/memory_manager.py`
      directamente, solo a través del bridge.

## Casos borde
- Crear una tarea sin fecha/hora especificada: usa el default ya existente de
  `task_manager.create_task()` (vence en 1 hora) — sin romper ni duplicar esa lógica en JS.
- Marcar como completada o eliminar una tarea que ya no existe (doble click, ya borrada): no lanza
  una excepción no controlada (`complete_task()`/`delete_task()` ya retornan `bool`).
- Crear un proyecto con nombre vacío: se rechaza con feedback claro, no se crea un proyecto sin
  nombre.
- Crear dos proyectos con el mismo nombre: se permite (sin unicidad forzada) — es solo una etiqueta
  visual, no un identificador.
- Asignar una conversación que ya pertenece a otro proyecto: se reasigna al nuevo proyecto (CA-20),
  nunca queda duplicada en dos proyectos.
- Eliminar un proyecto con conversaciones asignadas: las conversaciones no se borran (CA-19), quedan
  visibles sin agrupación.
- Sidebar colapsado con las 2 entradas nuevas: siguen mostrando ícono + tooltip sin desbordar el
  ancho de 60px ni forzar scroll horizontal.
- Un recordatorio vence mientras la app de escritorio está cerrada: no se notifica retroactivamente
  al reabrir la app fuera del ciclo normal — se notifica en el primer chequeo de 60s tras el
  arranque si `remind_at` ya pasó (comportamiento ya existente de `get_due_reminders()`, sin
  cambios).
- Doble click rápido en "Tareas" o "Proyectos" no abre paneles duplicados ni dispara dos cargas
  concurrentes del mismo listado.
- El archivo de fuente Inter no carga (falta, corrupto, bloqueado): el fallback del stack de sistema
  sigue siendo legible, la app no rompe visualmente ni deja texto invisible.
- Buscar con el término vacío en el nuevo control de búsqueda: muestra la lista completa ya cargada,
  sin filtrar nada.

## Asumidos
- ASUMIDO: la ubicación de "Tareas" y "Proyectos" en el sidebar — como dos botones nuevos en el
  cuerpo del sidebar, debajo de la píldora del header y arriba del listado de conversaciones (mismo
  estilo visual que ya usa `.sidebar-action-btn`), cada uno abre su propio panel/modal. Johan no fue
  consultado puntualmente sobre esto — a ajustar en el gate de aprobación si prefiere otra ubicación
  (p. ej. un menú desplegable nuevo).
- ASUMIDO: el detalle de "colapso más profesional" = iconos centrados + tooltip nativo + transición
  sin recortes bruscos (CA-22..CA-24) — sin más detalle específico de Johan más allá de eso.
- ASUMIDO: los bloques de código mantienen `Cascadia Code` sin cambios (CA-29); Inter no los
  reemplaza salvo que Johan indique lo contrario en el gate.
- ASUMIDO: el ícono de búsqueda de la píldora (parte de la referencia visual de DeepSeek) solo
  filtra la lista de conversaciones ya cargada en el sidebar (cliente, por título) — no implementa
  búsqueda de texto completo sobre todo el historial (eso requeriría backend nuevo sobre
  `ai/memory_manager.py`, fuera de lo que se preguntó). Si Johan quiere búsqueda completa, es
  alcance adicional a confirmar en el gate.
- ASUMIDO: una conversación pertenece a un único proyecto a la vez (CA-20) — Johan dijo "agrupador
  simple... conversaciones existentes", sin especificar pertenencia múltiple.
- ASUMIDO: eliminar un proyecto (`delete_project`) requiere confirmación YELLOW igual que
  `delete_conversation`/`delete_task` (CA-18), aunque no borra conversaciones — mismo criterio
  conservador que ya usa el proyecto para cualquier acción de "eliminar" sobre datos del usuario.
- ASUMIDO: no hay límite de cantidad de proyectos ni de conversaciones por proyecto en esta primera
  versión.
- ASUMIDO: las secciones "Tareas"/"Proyectos" no se replican en los menús de Telegram/Discord —
  alcance exclusivo de `ui/webview/frontend/`, igual que el resto de REQ-015.
- ASUMIDO: `task_scheduler.start()` se agrega al arranque de la app de escritorio (CA-10) — gap
  detectado en la investigación de este REQ (ver "Nota para el humano" arriba), necesario para que
  "ver/marcar hechas" tenga sentido funcional, aunque Johan no lo pidió explícitamente por no
  conocer el detalle interno.
- ASUMIDO: notificar un recordatorio vencido mientras la app de escritorio está abierta sigue usando
  el mecanismo ya existente (voz + Toast de Windows, `_notify_local()`) — no se agrega un evento
  nuevo del bridge para reflejarlo dentro de la ventana (badge, toast propio). Fuera de alcance salvo
  que Johan lo pida en el gate.
- ASUMIDO: el esquema exacto de datos para "proyectos" (tabla nueva vs. columna nueva en `memories`,
  nombres de función) queda a criterio técnico de `orion-architect`, siempre que cumpla CA-13..CA-21
  y no rompa CA-21 (no-regresión de las funciones ya existentes de `ai/memory_manager.py`).
