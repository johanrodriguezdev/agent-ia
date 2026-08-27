# SPEC-020 — Reorganización visual de NODDOO en tres columnas (inspirada en "JARVIS-OS")

**Estado:** ✅ COMPLETADO — Aprobado por el humano (2026-08-25), TAL CUAL, incluyendo los 4
ASUMIDOs señalados abajo (ubicación espacial de la columna derecha, exclusión del panel
"Memoria/Conocimiento", exclusión de la pestaña "Registros", e interpretación de "adaptar"
Proyectos/Configuración) — aprobación trasladada por `orion-coordinador`
**Categoría:** UI
**Tipo:** MEJORA
**Fecha:** 2026-08-25

## Nota para el humano — puntos que requerían aprobación explícita (RESUELTO — los 4 ✅ APROBADOS)

Las 4 preguntas de alcance que planteó `orion-coordinador` ya las respondiste (ver
`REQ-020-context.md`, volcadas ahí como decisiones). Al redactar los criterios de
aceptación aparecieron **4 puntos nuevos**, no cubiertos por esas 4 preguntas, que confirmaste
explícitamente en el gate (mismo patrón que SPEC-019), uno por uno:

1. **✅ APROBADO — ubicación espacial:** la referencia pone "Monitor de sistema" en la columna
   izquierda y "Tareas" en la derecha, pero NODDOO ya usa la columna izquierda para el
   sidebar de conversaciones (navegación core, nada que ver con monitor de sistema). Queda
   confirmado: **no se toca el sidebar izquierdo existente**, la tercera columna nueva se
   agrega a la **derecha** del chat, apilando "Monitor de sistema" (arriba) + "Tareas"
   (abajo) — 4 franjas horizontales en total: sidebar | chat | monitor+tareas.
2. **✅ APROBADO — panel "Memoria/Conocimiento" de la referencia:** queda **completamente
   fuera de alcance de REQ-020** — NODDOO no tiene hoy ningún endpoint que exponga
   `memory.db`/`semantic_memory.db` como lista navegable, y construir eso es una feature
   nueva (categoría MEMORIA/INTEGRACION), no una reorganización visual. Candidato a REQ
   futuro aparte.
3. **✅ APROBADO — alcance de "Registros" de la referencia:** el panel persistente es solo
   "Tareas" (sin pestaña de Registros) — NODDOO no tiene visor de logs para el usuario final,
   mismo criterio que el punto 2.
4. **✅ APROBADO — qué significa "adaptar" Proyectos/Configuración (respuesta 4C):** Proyectos
   y Configuración siguen siendo modales (no pasan a columna persistente — eso solo aplica a
   Tareas, respuesta 1A); "mismo criterio de layout/organización" significa: mismo lenguaje
   visual de cabecera/tarjeta ya usado en `panels.css`, sin agregar tokens ni colores nuevos,
   y con cualquier mejora de jerarquía de información que se defina para el panel de Tareas
   replicada ahí donde aplique (ej. si Tareas gana agrupación por estado, Proyectos podría
   agrupar igual). No implica volverlos persistentes ni cambiar su contrato con el bridge.

Ningún punto de esta SPEC queda abierto — las 4 preguntas originales y los 4 ASUMIDOs nuevos
están aprobados. `orion-baseline` puede proceder.

## Objetivo
Reorganizar la disposición visual de la ventana principal de NODDOO (hoy: sidebar de
conversaciones + columna de chat, con Tareas/Proyectos/Configuración como modales) hacia un
layout que mejore la jerarquía y accesibilidad de la información — tomando como inspiración
(no como plantilla a clonar) el layout de tres columnas persistentes de la referencia
"JARVIS-OS" — sin modificar la identidad visual (paleta, temas oscuro/claro) ya establecida
en REQ-008/010/013/014/015/016.

## Alcance
- Incluye:
  - Nueva columna persistente a la derecha del chat con dos zonas apiladas:
    - **"Tareas"**: contenido migrado de `tasks_panel.js` (hoy modal) a un panel siempre
      visible en esta columna — crear, listar, completar y eliminar tareas, misma
      funcionalidad de hoy, sin cambios de contrato con `ui/webview/bridge.py`.
    - **"Monitor de sistema"**: panel nuevo, **sin datos reales** — solo la estructura visual
      (título, área de contenido) con un estado vacío/placeholder explícito (ej. "Métricas del
      sistema — próximamente"), dejando el espacio reservado en el layout para una futura
      conexión de datos reales (REQ futuro, fuera de esta categoría UI).
  - Reorganización de la jerarquía visual del estado vacío del chat (`#empty-state`): evaluar
    acercar los chips de acciones sugeridas (`chips-row`, hoy en el composer) al saludo/orbe
    del estado vacío, para mejorar el acceso rápido — reutilizando el mecanismo de datos ya
    existente (`onChipsLoaded`/`renderChips`), sin nuevo endpoint del bridge.
  - Ajuste del lenguaje visual de `panels.css` (cabeceras, tarjetas, agrupación) aplicado de
    forma consistente a los modales existentes de **Proyectos** (`projects_panel.js`) y
    **Configuración** (`settings_panel.js`) — ver ASUMIDO 4 arriba —, sin volverlos paneles
    persistentes ni tocar su contrato con el bridge.
  - Todo cambio de layout/densidad usa exclusivamente las variables ya definidas en
    `ui/webview/theme.py` / `ui/webview/frontend/css/theme.css` — cero valores hex nuevos,
    cero color nuevo, cero tema adicional.
- No incluye:
  - Ningún dato real de CPU, memoria, red, temperatura, uptime ni latencia del equipo del
    usuario — el panel "Monitor de sistema" es 100% placeholder visual en este REQ. Conectar
    telemetría real del host es explícitamente **fuera de alcance**, candidato a REQ futuro de
    categoría CORE/INTEGRACION (requeriría IPC nuevo, no es trabajo de UI).
  - Panel de "Memoria/Conocimiento" de la referencia (búsqueda + tarjetas de nodos de
    memoria) — ver ASUMIDO 2.
  - Pestaña/vista de "Registros" dentro del panel de Tareas — ver ASUMIDO 3.
  - Adopción del tema claro + acento cian de la referencia, o de cualquier color/token nuevo.
  - Decoración estética nueva tipo HUD (esquinas bracket, iconografía técnica, sparklines
    reales) — la reorganización es estructural/de layout, no un rediseño estético. Si el
    "Monitor de sistema" necesita algún elemento visual mínimo (ej. barra de progreso vacía a
    modo de placeholder), usa exclusivamente componentes/tokens ya existentes en el proyecto.
  - Convertir Proyectos o Configuración en paneles persistentes — siguen siendo modales.
  - Cualquier cambio a `core/security_manager.py`, `agents/`, o a la lógica de negocio de
    tareas/proyectos en el backend — este REQ es puramente de reorganización visual del
    frontend, reutilizando los slots/señales del bridge que ya existen hoy
    (`request_tasks`, `tasks_loaded`, etc.).
  - Responsive/adaptación a ventanas angostas más allá de lo que ya soporta el sidebar
    colapsable hoy — el comportamiento de la nueva columna derecha en ventanas muy angostas
    (ej. ocultarse/colapsar) queda a criterio de `orion-architect`, documentado como decisión
    suya si aplica.

## Módulos afectados
- `ui/webview/frontend/index.html`:
  - Nueva estructura de columna derecha (contenedor persistente, no modal), con dos
    subsecciones: monitor de sistema (placeholder) y tareas.
  - `tasks_panel.js` deja de montarse sobre `#panel-modal-root`.
- `ui/webview/frontend/css/layout.css`:
  - Pasa de 2 zonas (`#sidebar` + `#main-column`) a 3: `#sidebar` + `#main-column` +
    nueva columna derecha (ancho fijo, mismo criterio que `#sidebar` en `sidebar.css`).
- `ui/webview/frontend/css/panels.css`:
  - Se reutiliza para el contenido de la nueva columna persistente (ya no solo para
    contenido de modal) — puede requerir clases nuevas para el contexto "panel fijo" vs.
    "panel dentro de modal", sin romper el uso actual en Proyectos/Configuración.
  - Ajustes de jerarquía visual (agrupación, cabeceras) que después se replican en
    Proyectos/Configuración (ver ASUMIDO 4).
- `ui/webview/frontend/js/tasks_panel.js`:
  - Cambia de "abrir/cerrar modal bajo demanda" (`openTasksPanel`/`closeTasksPanel`,
    guard `_panelOpen`) a "montar una vez en la columna persistente al bootstrap". Esto
    **revierte el criterio de carga perezosa** que fijó SPEC-016 (CA-12 equivalente) para
    Tareas específicamente — ahora `request_tasks()` se llama en `bootstrap()`
    (`app.js`), no al hacer click. Proyectos y Configuración mantienen su carga perezosa
    actual (siguen siendo modales bajo demanda).
- `ui/webview/frontend/js/app.js`:
  - Quitar el listener `tasks-btn` → `openTasksPanel()` (ya no hay botón que abra/cierre
    nada — el panel ya está siempre visible), o redefinir su rol (ver Casos borde sobre qué
    pasa con el botón "Tareas" del sidebar).
  - Llamar `requestTasks()` en `bootstrap()` en vez de en el click handler.
- `ui/webview/frontend/js/sidebar.js` / `index.html`:
  - El botón `#tasks-btn` del sidebar pierde su función actual de abrir modal — a decidir
    con `orion-architect` si se elimina, se re-etiqueta (ej. "ir a / hacer foco en Tareas") o
    se reemplaza por otra acción, dado que el panel ya no es modal.
- `ui/webview/frontend/js/projects_panel.js`, `ui/webview/frontend/js/settings_panel.js`:
  - Ajustes de clases/estructura interna para alinear con el lenguaje visual definido para el
    panel de Tareas (ASUMIDO 4) — sin cambiar su naturaleza de modal ni su contrato con el
    bridge.
- `ui/webview/frontend/js/chat.js` / `composer.js`:
  - Posible movimiento de `chips-row` (o una copia de su renderizado) hacia `#empty-state`
    para la mejora de jerarquía visual del estado vacío.
- **No se modifica:** `ui/webview/bridge.py`, `ui/webview/theme.py`,
  `ui/webview/frontend/css/theme.css` (ningún token nuevo), `core/`, `agents/`,
  `task_manager` (backend) — este REQ no toca contratos Python↔JS ni lógica de negocio.
- `tests/test_webview_safe_dom_insertion.py`: sigue cubriendo `tasks_panel.js` (ya lo hace)
  y debe seguir pasando tras el cambio de modal a panel persistente sin modificar su regla
  (`textContent`/`setAttribute`, nunca `innerHTML`).
- `tests/test_webview_theme.py`: no debería verse afectado (cero tokens nuevos), pero se
  ejecuta igual como no-regresión.

## Comportamiento actual vs deseado
| Actual | Deseado |
|---|---|
| Layout de 2 zonas: sidebar (conversaciones) + columna principal (chat) | Layout de 3 zonas: sidebar (sin cambios) + columna principal (chat, sin cambios funcionales) + nueva columna derecha persistente (Monitor de sistema + Tareas) |
| "Tareas" es un modal que se abre con el botón del sidebar y se cierra con overlay/✕ | "Tareas" es un panel siempre visible en la columna derecha, sin botón de apertura/cierre |
| `request_tasks()` se llama recién al abrir el modal (carga perezosa) | `request_tasks()` se llama en el bootstrap de la app (el panel ya está visible desde el inicio) |
| No existe ningún panel de "Monitor de sistema" | Existe el espacio/estructura visual del panel, con estado vacío/placeholder explícito — sin datos reales |
| Los chips de acciones sugeridas viven en el composer, no en el estado vacío del chat | Los chips se acercan visualmente al saludo del estado vacío para mejorar el acceso rápido |
| Proyectos/Configuración son modales con su propio lenguaje visual de tarjeta | Proyectos/Configuración siguen siendo modales, pero comparten el lenguaje visual afinado del panel de Tareas (cabeceras, agrupación) |
| Paleta/tokens: `theme.py` + `theme.css`, temas oscuro/claro únicos | Sin cambios — mismos tokens, mismos temas, cero color nuevo |

## Criterios de aceptación

### Layout de tres columnas
- [ ] CA-01: La ventana principal muestra 3 zonas horizontales simultáneamente y sin
      superposición: sidebar de conversaciones (sin cambios de ancho/comportamiento respecto
      a hoy), columna de chat, y una columna nueva a la derecha — verificable inspeccionando
      el DOM/CSS resultante (no depende de una captura de pantalla).
- [ ] CA-02: La columna derecha nueva tiene ancho fijo (mismo criterio que `#sidebar` en
      `sidebar.css`, valor exacto a definir por `orion-architect`) y no se superpone ni oculta
      el área de mensajes ni el composer del chat en ninguna resolución soportada hoy por la
      ventana (`ui/webview/main_window.py`, tamaño mínimo actual).
- [ ] CA-03: El sidebar izquierdo (conversaciones) no pierde ninguna funcionalidad existente
      (colapsar, buscar, nuevo chat, lista, footer con toggle de tema) — no-regresión total.
- [ ] CA-04: El área de chat (mensajes + composer) no pierde ninguna funcionalidad existente
      (envío, adjuntos, wake toggle, chips, indicador de escritura) — no-regresión total.

### Panel de Tareas — de modal a persistente
- [ ] CA-05: El contenido de Tareas (formulario de alta + lista pendientes/completadas) está
      visible en la columna derecha desde que la app termina de cargar, sin necesidad de click
      en ningún botón.
- [ ] CA-06: `request_tasks()` se invoca durante `bootstrap()` de `app.js`, no como reacción a
      un click — verificable leyendo el código (no hay ningún listener de click que dispare la
      primera carga de tareas).
- [ ] CA-07: Crear, completar y eliminar una tarea desde el panel persistente sigue
      funcionando exactamente igual que en el modal actual (mismos slots del bridge,
      `create_task`/`complete_task`/`request_delete_task`, sin cambios de firma).
- [ ] CA-08: Eliminar una tarea sigue disparando el flujo de confirmación Amarillo existente
      (`requestDeleteTask` → confirmación) — no-regresión de seguridad.
- [ ] CA-09: El botón `#tasks-btn` del sidebar deja de abrir/cerrar un modal (ya no hay modal
      de Tareas); su comportamiento final (eliminado, re-etiquetado, o con otra función) queda
      documentado explícitamente en `desarrollo-log-020.md` por `orion-dev`, siguiendo lo que
      defina `orion-architect`.
- [ ] CA-10: `tests/test_webview_safe_dom_insertion.py` sigue cubriendo `tasks_panel.js` tras
      el cambio y sigue pasando (ninguna inserción vía `innerHTML`/`insertAdjacentHTML`).

### Panel de Monitor de sistema (placeholder)
- [ ] CA-11: Existe un panel visualmente delimitado con un título identificable (ej.
      "Monitor de sistema") en la columna derecha, por encima o debajo del panel de Tareas
      según lo que confirme el humano (ver ASUMIDO 1).
- [ ] CA-12: El panel no realiza ninguna llamada al bridge ni a ninguna fuente de datos del
      sistema operativo — es contenido 100% estático en el frontend en este REQ.
- [ ] CA-13: El panel comunica visualmente que es un placeholder (ej. texto tipo "Métricas del
      sistema — próximamente" o equivalente), no una sección vacía sin explicación ni un dato
      inventado/hardcodeado que aparente ser real.
- [ ] CA-14: El placeholder usa exclusivamente estilos ya existentes en `panels.css`/
      `theme.css` (reutiliza, por ejemplo, el patrón de `.panel-empty`) — cero CSS con colores
      o valores nuevos fuera del sistema de tokens.

### Identidad visual — cero tokens nuevos
- [ ] CA-15: `ui/webview/frontend/css/theme.css` no tiene ninguna variable, color o token
      agregado/modificado respecto a la versión anterior a este REQ.
- [ ] CA-16: `ui/webview/theme.py` no tiene ningún cambio — `tests/test_webview_theme.py`
      (test de drift entre ambas fuentes) sigue pasando sin modificación.
- [ ] CA-17: Ningún archivo CSS nuevo o modificado por este REQ introduce un valor de color en
      hexadecimal/rgb/hsl fuera de `var(--...)` — verificable por revisión de diff (no hay
      test automático dedicado; `orion-qa` lo revisa explícitamente en su auditoría).
- [ ] CA-18: El comportamiento de cambio de tema oscuro/claro (`theme.js`, `set_theme()` del
      bridge) sigue funcionando igual en las 3 columnas, incluida la nueva — ninguna columna
      queda "pegada" a un tema fijo.

### Estado vacío del chat
- [ ] CA-19: Los chips de acciones sugeridas son visibles/accesibles desde el estado vacío del
      chat (`#empty-state`) sin necesidad de que el usuario escriba nada antes — ya sea
      moviendo `chips-row` ahí o renderizando una copia sincronizada, a criterio de
      `orion-architect`.
- [ ] CA-20: Los chips siguen funcionando igual que hoy una vez que hay una conversación en
      curso (no-regresión del comportamiento actual de `renderChips`/`onChipsLoaded`).

### Proyectos y Configuración — mismo lenguaje visual
- [ ] CA-21: `projects_panel.js` y `settings_panel.js` siguen siendo modales (se abren/cierran
      igual que hoy, mismo punto de entrada, mismo overlay) — no se convierten en paneles
      persistentes.
- [ ] CA-22: Los ajustes de jerarquía visual definidos para el panel de Tareas que sean
      aplicables (cabeceras, agrupación, spacing de `panels.css`) se reflejan también en
      Proyectos y Configuración, documentados en `desarrollo-log-020.md` con el detalle
      concreto de qué se replicó y qué no aplicaba.
- [ ] CA-23: Ningún cambio en Proyectos o Configuración modifica su contrato con
      `ui/webview/bridge.py` (mismos slots, misma firma).

### No regresión general
- [ ] CA-24: `python -m py_compile` sobre cualquier módulo Python tocado (si lo hay) no arroja
      errores — se espera que este REQ no toque Python en absoluto (ver Módulos afectados).
- [ ] CA-25: La suite de tests completa sigue pasando sin nuevos fallos (el conteo exacto de
      baseline lo documenta `orion-baseline`).
- [ ] CA-26: No se hardcodea ningún dato que aparente ser telemetría real del sistema (CPU,
      memoria, red, temperatura) en ningún archivo JS/HTML — verificado por `orion-qa`.

## Casos borde
- Ventana redimensionada a un ancho muy angosto: con 3 columnas fijas (sidebar + chat +
  columna derecha) el chat podría quedar demasiado angosto. `orion-architect` debe definir un
  comportamiento (ej. colapsar la columna derecha automáticamente por debajo de cierto ancho,
  mismo criterio que ya existe para el sidebar) — no puede dejar el chat inutilizable.
- Usuario con muchas tareas pendientes: la lista de tareas en el panel persistente necesita
  scroll propio (`max-height` + `overflow-y`, mismo patrón que `.panel-list` hoy) sin empujar
  ni recortar el panel de Monitor de sistema.
- Doble carga de tareas: si `bootstrap()` llama `requestTasks()` y en el futuro algo más
  también lo dispara, no debe haber duplicación de la lista renderizada — `renderTasks()` ya
  hace `replaceChildren()`, hay que confirmar que sigue siendo así tras el cambio.
- Botón `#tasks-btn` del sidebar sin función clara tras el cambio: no debe quedar un botón
  "muerto" que no haga nada al hacer click y no dé ninguna señal — cualquiera sea la decisión
  final (CA-09), debe tener un comportamiento explícito, no ausencia de comportamiento.
- Tema oscuro/claro cambiado con el panel de Monitor de sistema visible: el placeholder debe
  verse correctamente en ambos temas (mismo `var(--text-secondary)`/`var(--bg-secondary)` que
  ya usa `.panel-empty`), sin quedar ilegible en ninguno de los dos.

## Asumidos
Ver "Nota para el humano" arriba — los 4 puntos (ASUMIDO 1 a 4) son las decisiones nuevas que
requieren tu confirmación explícita en este gate, además de tus 4 respuestas ya cerradas:
1A (Tareas persistente), 2B (Monitor de sistema sin datos reales, placeholder), 3A (cero
tokens/colores nuevos, sin adoptar tema claro+cian ni decoración HUD), 4C (adaptar también
Proyectos/Configuración al mismo criterio visual, sin volverlos persistentes).
