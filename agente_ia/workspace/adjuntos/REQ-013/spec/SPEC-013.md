# SPEC-013 — Rediseño UI escritorio NODDOO estilo chat de IA

**Estado:** ✅ COMPLETADO — Aprobado por Johan (2026-08-17), sin ajustes
**Categoría:** UI
**Tipo:** MEJORA
**Fecha:** 2026-08-17

## Nota para el humano — categoría UI vs MEMORIA
Este REQ toca `ai/memory_manager.py` de forma no trivial: agrupación de interacciones en
conversaciones (`conversation_id`) y persistencia del texto original del usuario (hoy no se
guarda, ver CA-09). Por decisión explícita del humano (2026-08-17) el REQ se mantiene bajo
categoría **UI** y no se abre un REQ-MEMORIA separado. Se deja esta nota para trazabilidad: si a
futuro surgen más REQs sobre historial/memoria conversacional, evaluar si ameritan categoría
MEMORIA propia.

## Objetivo
Migrar el panel de escritorio de NODDOO (PyQt6) del layout actual (sidebar de navegación mayormente
no funcional + indicador circular central + panel derecho de widgets) a un layout tipo chat de IA
moderno (ChatGPT/DeepSeek/Claude, inspirado en la referencia visual "WorkBuddy AI"): sidebar de
historial de conversaciones **funcional**, feed central de burbujas de mensajes, composer inferior
prominente con chips de accesos rápidos/plantillas, selector de tema claro/oscuro — conservando el
panel derecho de widgets de estado como panel lateral coexistente.

## Alcance
- Incluye:
  - Rediseño estructural y visual de `ui/gui.py` y los widgets en `ui/widgets/` para el nuevo layout
    tipo chat (sidebar + feed central + composer), en ambos temas (claro/oscuro).
  - Sidebar de historial de conversaciones funcional: listado real, carga de una conversación pasada
    al hacer click, acción "Nueva conversación".
  - Extensión de `ai/memory_manager.py` para agrupar interacciones en conversaciones (persistir
    también el texto original del usuario, no solo `f"{matched_by} | {result_text}"`).
  - Feed de burbujas de mensajes (usuario/IA) en la sesión activa, reemplazando el label de estado
    truncado a 200 caracteres actual de `CenterPanel.show_response()`.
  - Selector de tema claro/oscuro persistente, aplicado a todo el layout nuevo (sidebar, feed,
    composer, panel derecho).
  - Chips de accesos rápidos/plantillas sobre el composer (propuesta concreta en esta SPEC, sección
    "Propuesta de chips").
  - Conservación del panel derecho (`RightPanel`: estado del sistema, accesos rápidos, actividad
    reciente, clima) como panel lateral, coexistiendo con el nuevo layout.
- No incluye:
  - Empaquetado como instalable (PyInstaller u otro) — se abordará en un REQ aparte.
  - Activar como funcionales los demás ítems del sidebar hoy deshabilitados (Memoria, Tareas,
    Archivos, Aplicaciones, Configuración) — siguen siendo placeholders, salvo "Conversaciones" que
    sí se vuelve funcional en este REQ.
  - Sincronización de historial de conversaciones entre canales (Telegram/Discord) — el historial
    funcional de este REQ es exclusivo del canal DESKTOP.
  - Autenticación/soporte multiusuario real — se sigue usando `user_id="default"` como en el resto
    del sistema.
  - Definir la identidad de marca/branding final de la mascota de Nodo (ver Asumidos).

## Módulos afectados
- `ui/gui.py` — orquestación del nuevo layout (`JarvisMainWindow._init_ui`), wiring de señales del
  nuevo sidebar de historial y del selector de tema.
- `ui/widgets/center_panel.py` — reemplazo sustancial: pasa de "saludo + orb + status label" a
  "feed de burbujas + composer + chips" (o su división en widgets nuevos, ver más abajo).
- `ui/widgets/sidebar.py` — se agrega listado de conversaciones funcional + acción "Nueva
  conversación"; se conservan los ítems placeholder existentes.
- `ui/widgets/right_panel.py`, `system_status_card.py`, `quick_actions_card.py`,
  `recent_activity_card.py`, `weather_card.py` — sin cambios funcionales; ajuste de estilos para
  respetar el tema activo (claro/oscuro).
- `ui/widgets/header_bar.py` — se agrega el control de selector de tema.
- `ui/widgets/voice_orb.py` — se conserva el indicador de estado (IDLE/LISTENING/PROCESSING/
  RESPONDING); reubicación exacta a definir en arquitectura.
- Widgets nuevos a crear en `ui/widgets/` (nombres/división exacta a definir en orion-architect,
  no prescritos aquí): burbuja de mensaje, feed de chat con scroll, composer con chips, listado de
  conversaciones del sidebar.
- `ai/memory_manager.py` — nuevas funciones para: persistir turno completo (texto de usuario +
  respuesta) asociado a un `conversation_id`; listar conversaciones por `user_id` ordenadas por
  última actividad; obtener todos los turnos de una conversación. Posible migración/adaptación de
  esquema en `unified_memory.db` (compatibilidad con filas legacy, ver CA-12).
- `config_manager.py` — nueva preferencia persistida de tema (`get_ui_theme()`/`set_ui_theme()`,
  siguiendo el patrón `get_/set_` existente).
- Tests: `tests/test_gui_widgets.py`, `tests/test_cli_gui_active.py`, `tests/test_wake_word_gui.py`,
  `tests/test_memory_manager_recent.py` (regresión) + tests nuevos para los widgets y funciones
  agregadas.

## Comportamiento actual vs deseado
| Actual | Deseado |
|--------|---------|
| Centro: saludo + orb circular + label de estado (últimos 200 chars de la respuesta) | Centro: feed de burbujas de mensajes (usuario/IA) de la conversación activa |
| Sidebar: 7 ítems, solo "Inicio" funcional | Sidebar: ítems existentes se conservan; "Conversaciones" pasa a ser funcional (listado real, click carga historial) |
| No existe concepto de "conversación" — solo interacciones sueltas en `memory_manager` | Interacciones agrupadas por `conversation_id`, consultables y navegables desde el sidebar |
| `memory_manager` no guarda el texto original del usuario | Se persiste texto de usuario + respuesta de IA por turno |
| Tema único oscuro fijo | Selector de tema claro/oscuro, persistente, aplicado a todo el layout |
| Command bar simple + toggle manos libres + enviar | Composer inferior prominente con los mismos controles + fila de chips de plantillas/accesos directos arriba |
| Panel derecho de widgets de estado | Se conserva igual, coexistiendo como panel lateral |

## Propuesta de chips (composer)
Combinación de plantilla (prellena el composer, no ejecuta nada) y acceso directo (ejecuta una
acción real de `agents/action_registry.py`, igual que `QuickActionsCard`). Propuesta inicial de
orion-spec, sujeta a ajuste en la aprobación:

| Chip | Tipo | Comportamiento |
|------|------|-----------------|
| "Resumen del día" | Plantilla | Prellena el composer: "Dame un resumen de mi actividad reciente y tareas pendientes" |
| "Recuérdame algo" | Plantilla | Prellena el composer: "Recuérdame que..." |
| "Investigación rápida" | Plantilla | Prellena el composer: "Investiga sobre..." |
| "📷 Captura de pantalla" | Acceso directo | Ejecuta `take_screenshot` vía `run_async(execute_action, ...)` (mismo patrón que `QuickActionsCard`) |
| "🌐 Abrir navegador" | Acceso directo | Ejecuta `open_browser` vía `run_async(execute_action, ...)` |

## Criterios de aceptación

### Tema claro/oscuro
- [ ] CA-01: Existe un selector de tema (claro/oscuro) accesible desde el header; el cambio se
      aplica en caliente (sin reiniciar la app) a todos los widgets del layout nuevo (sidebar, feed,
      composer, panel derecho).
- [ ] CA-02: La preferencia de tema persiste entre reinicios de la app (vía `config_manager`,
      patrón `get_ui_theme()`/`set_ui_theme()`).
- [ ] CA-03: Existe una paleta de colores definida para modo claro y otra para modo oscuro, con
      contraste legible entre texto y fondo en ambos modos.
- [ ] CA-04: El panel derecho (`RightPanel` y sus 4 tarjetas) respeta el tema activo igual que el
      resto del layout.

### Sidebar de historial funcional
- [ ] CA-05: El sidebar muestra un listado de conversaciones pasadas del usuario, ordenadas por
      fecha de última actividad (más reciente primero).
- [ ] CA-06: Click en una conversación del listado carga sus turnos completos (mensaje de usuario +
      respuesta de la IA) en el feed central, marcándola como conversación activa.
- [ ] CA-07: Existe una acción "Nueva conversación" que limpia el feed activo y comienza una
      conversación nueva (nuevo `conversation_id`), sin borrar las conversaciones anteriores.
- [ ] CA-08: Los ítems de navegación no funcionales existentes (Memoria, Tareas, Archivos,
      Aplicaciones, Configuración) se conservan como placeholders deshabilitados, igual que hoy.

### Persistencia de conversaciones (`ai/memory_manager.py`)
- [ ] CA-09: Al enviar un mensaje se persiste tanto el texto original del usuario como la respuesta
      de la IA, asociados a un `conversation_id` común.
- [ ] CA-10: Existe una función para listar conversaciones de un `user_id` (id, título/primer
      mensaje derivado, timestamp de última actividad).
- [ ] CA-11: Existe una función para obtener todos los turnos de una conversación dado su
      `conversation_id`, en orden cronológico.
- [ ] CA-12: Las filas existentes en `unified_memory.db` anteriores a este cambio (sin
      `conversation_id`) no rompen el listado ni el arranque de la app.

### Feed de burbujas (sesión activa)
- [ ] CA-13: Cada mensaje enviado por el usuario aparece inmediatamente como una burbuja en el feed,
      visualmente distinguible de las respuestas de la IA.
- [ ] CA-14: Cada respuesta de la IA aparece como una burbuja separada en el feed (reemplaza el
      comportamiento actual de `CenterPanel.show_response()`).
- [ ] CA-15: El feed es scrolleable y se autoscrollea al último mensaje al recibir uno nuevo.
- [ ] CA-16: El indicador de estado (IDLE/LISTENING/PROCESSING/RESPONDING) y el toggle de modo
      manos libres (REQ-009) se mantienen visibles y funcionales en el nuevo layout.

### Composer + chips
- [ ] CA-17: El composer se mantiene funcionalmente equivalente al actual (mismo pipeline
      `command_submitted` → `core/resolution.py:resolve()`), reubicado en la parte inferior central.
- [ ] CA-18: Se muestra la fila de chips definida en "Propuesta de chips": al menos un chip de tipo
      plantilla y al menos un chip de tipo acceso directo.
- [ ] CA-19: Los chips de tipo acceso directo pasan por `run_async(execute_action, ...,
      channel=ChannelType.DESKTOP)`, igual que `QuickActionsCard` — nunca invocan la acción directo.

### Panel derecho (coexistencia)
- [ ] CA-20: El panel derecho (`RightPanel`) se conserva visible simultáneamente con el nuevo layout
      centrado en chat — no se mueve a otra vista ni se elimina.
- [ ] CA-21: El panel derecho respeta el tema activo (ver CA-04).

### Regresión
- [ ] CA-22: Los tests existentes (`test_gui_widgets.py`, `test_cli_gui_active.py`,
      `test_wake_word_gui.py`, `test_memory_manager_recent.py`) siguen pasando, o se actualizan
      explícitamente si su contrato cambió por este REQ, documentando el motivo.

## Casos borde
- Conversación activa sin ningún mensaje enviado todavía: no debe aparecer una entrada vacía en el
  listado del sidebar hasta el primer mensaje enviado.
- Cambio de tema mientras hay una respuesta en curso (estado PROCESSING): no debe interrumpir la
  resolución en curso.
- Historial con muchas conversaciones (cientos): el listado del sidebar debe limitar/paginar (p. ej.
  últimas N) para no degradar el arranque de la app.
- Filas legacy en `unified_memory.db` sin `conversation_id` (ver CA-12) — no deben causar excepción
  ni aparecer mezcladas de forma inconsistente en el listado.
- Doble click rápido en "Nueva conversación" no debe crear `conversation_id` huérfanos vacíos
  duplicados.
- Reinicio de la app en medio de una conversación: al reabrir, el feed arranca vacío (nueva
  conversación), pero la conversación anterior queda accesible desde el sidebar (ya persistida).

## Asumidos
- ASUMIDO: no existe aún un asset gráfico definido para la mascota/avatar de Nodo — se usará un
  ícono/emoji placeholder hasta que exista una identidad visual formal (fuera de alcance de este REQ
  definir el branding final).
- ASUMIDO: el selector de tema se ubica en el header (junto al indicador de modo/manos libres) —
  ubicación exacta a validar con `orion-architect`.
- ASUMIDO: una "conversación" se delimita por sesión de uso continuo iniciada explícita (click en
  "Nueva conversación") o implícitamente (primer mensaje tras abrir la app) — no hay corte
  automático por timeout de inactividad.
- ASUMIDO: la paleta exacta de colores (valores hex concretos) para ambos modos se define en
  `orion-architect`; esta SPEC solo exige que exista y cumpla contraste legible (CA-03).
- ASUMIDO: el mapeo de chips en "Propuesta de chips" es una propuesta inicial de `orion-spec`,
  sujeta a ajuste por el humano antes de aprobar esta SPEC.
- ASUMIDO: la migración de filas legacy de `unified_memory.db` (sin `conversation_id`) se resuelve
  técnicamente en `orion-architect`; esta SPEC solo exige que no rompan el sistema (CA-12).
