# REQ-020 — Referencia visual "JARVIS-OS" (descripción textual)

No hay archivo de imagen guardado. El humano compartió una captura de pantalla de una
interfaz de referencia (estilo "JARVIS-OS") durante la conversación; Claude analizó la
captura y produjo la siguiente descripción textual, que queda registrada aquí como única
evidencia de origen de este REQ.

## Descripción de la referencia

- **Barra superior**: marca + título del agente a la izquierda; al centro-derecha un
  clúster de estado del sistema (indicador "núcleo en línea", "red estable", contador de
  "amenazas"); a la derecha reloj/fecha en vivo.
- **Layout de tres columnas persistentes** (no modales):
  1. **Columna izquierda "Monitor de sistema"**: métricas (CPU, memoria, red) cada una
     con valor %, barra de progreso y mini-sparkline; debajo, grid 2x2 de stats (uptime,
     núcleos activos, temperatura, latencia).
  2. **Columna central**: el chat en sí — encabezado con nombre del agente y estado
     online, saludo centrado con orbe/avatar, subtítulo, chips de acciones sugeridas, y
     el composer de mensajes abajo.
  3. **Columna derecha** con dos paneles apilados: "Tareas/Registros" (tabs, contador
     tipo "3/4", lista de tareas con badge de estado y barra de progreso) y
     "Memoria/Conocimiento" (buscador + tarjetas de nodos de memoria con ícono, título,
     categoría y descripción).
- **Estética**: tema claro, acento cian/azul, bordes finos de 1px, pequeños detalles
  decorativos tipo HUD (esquinas tipo bracket) en cada panel, tipografía técnica para
  labels/números, mucho whitespace, badges/pills redondeados para estados.

## Objetivo del REQ frente a esta referencia

Esto **no es una orden de clonar literalmente** la referencia — NODDOO tiene su propia
identidad de marca ya establecida (ver `ui/webview/theme.py` +
`ui/webview/frontend/css/theme.css`, temas oscuro/claro de REQ-008/013/014/015/016). Es
inspiración para **mejorar la organización de la información** de la interfaz actual.

`orion-spec` debe explorar con el humano, entre otros puntos:

- Si el panel de "Tareas" (hoy modal, `tasks_panel.js`) debería pasar a panel persistente.
- Si conviene agregar un panel de estado/monitor del sistema visible de forma permanente.
- Cómo mejorar la jerarquía visual del estado vacío del chat (saludo + accesos rápidos).
- Qué partes de la estética de la referencia (colores, densidad, decoración tipo HUD)
  aplican o no a la identidad visual ya establecida de NODDOO.

## Estado actual real de NODDOO (relevado, no re-investigar desde cero)

- Layout de dos zonas: sidebar (con botones "Tareas" y "Proyectos" que abren paneles
  modales sobre `#panel-modal-root`, no paneles persistentes) + columna principal
  (`#main-column`: chat + composer).
- Ya existen `ui/webview/frontend/js/tasks_panel.js` y `projects_panel.js` (modales), y un
  sistema de tokens de diseño de doble fuente sincronizada (`ui/webview/theme.py` +
  `ui/webview/frontend/css/theme.css`, con test de drift `tests/test_webview_theme.py`),
  con temas oscuro/claro ya establecidos en REQ-008/013/014/015/016.
- El agente `orion-ui` (nuevo, recién agregado a `.claude/agents/`) debe participar en
  este REQ antes de `orion-dev`, ya que la categoría es UI y hay referencia visual.
