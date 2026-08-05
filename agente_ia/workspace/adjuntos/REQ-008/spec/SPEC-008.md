# SPEC-008 — Rediseño GUI de escritorio estilo "JARVIS" a pantalla completa

**Estado:** ⏸️ ESPERANDO VALIDACIÓN
**Categoría:** UI
**Tipo:** FEATURE_NUEVA
**Fecha:** 2026-08-04

## Objetivo
Reemplazar el HUD flotante actual de escritorio (`ui/gui.py`, 400x400 sin bordes) por una interfaz
de escritorio maximizada con sidebar de navegación, saludo dinámico, indicador de estado de voz,
panel de estado del sistema, accesos rápidos a acciones ya existentes, actividad reciente real y
clima real — siguiendo la descripción del mockup transcrita en `REQ-008-context.md`, priorizando
datos reales sobre datos simulados salvo en los dos puntos donde el humano aprobó explícitamente
un placeholder (actividad de audio en vivo y, transitoriamente, nada más).

## Alcance

**Incluye:**
- Nueva ventana principal PyQt6 **maximizada** (no modo kiosco), con barra de título estándar y
  controles minimizar/maximizar/cerrar visibles y funcionales, tal como muestra el mockup.
- Layout de 3 zonas — sidebar izquierdo, centro, panel derecho — según la transcripción exhaustiva
  del mockup en `REQ-008-context.md`.
- **Sidebar**: logo + nombre de agente dinámico (`config_manager.get_agent_name()`, nunca "JARVIS"
  hardcodeado), navegación de 7 ítems donde solo "Inicio" tiene vista real; los otros 6
  (Conversaciones, Memoria, Tareas, Archivos, Aplicaciones, Configuración) son placeholders
  visibles sin acción real. Indicador "Sistema activo" en la parte inferior.
- **Header**: píldora "Modo activo" reflejando el mismo estado de 4 valores ya existente
  (IDLE/LISTENING/PROCESSING/RESPONDING) + icono de notificaciones (decorativo en este REQ, ver
  Asumidos).
- **Centro**: saludo dinámico por hora del día + nombre de usuario, visualizador circular dirigido
  por los 4 estados existentes (sin audio real — aprobado como simulado en P4), barra de comando
  (texto) conectada al mismo pipeline de resolución que ya usa `ui/cli.py`.
- **Panel derecho**, 4 tarjetas:
  1. Estado del sistema — datos reales de `psutil` (CPU/RAM/Disco/Red).
  2. Accesos rápidos — Explorador/Navegador/Notas/Calculadora/Captura (ya existentes) + Spotify
     (nuevo, mínimo viable), todos vía `execute_action()`.
  3. Actividad reciente — datos reales de `ai/memory_manager.py` (nuevo método de recencia).
  4. Clima — datos reales de wttr.in, estructurados (no la frase de texto de la skill
     conversacional).
- Comportamiento de cierre: el botón "×" minimiza a la bandeja del sistema, preservando la
  conducta actual de `ui/gui.py` (el proceso no termina).
- Reutilización estricta del gate de seguridad existente (`execute_action()` →
  `security_manager.require_confirmation()`) para toda acción de "Accesos rápidos" — cero caminos
  nuevos sin gate.

**No incluye (fuera de alcance de este REQ):**
- Vistas funcionales reales para Conversaciones/Memoria/Tareas/Archivos/Aplicaciones/Configuración
  del sidebar — solo placeholders de navegación.
- Visualizador de audio en vivo con amplitud/volumen real — queda simulado por estado (aprobado en
  P4).
- Integración real de Spotify (login, control de reproducción, API) — solo abrir la app o el sitio
  web (aprobado en P5).
- Sistema de notificaciones real para el icono de campana del header.
- Cambios a `ui/cli.py` o al modo `--headless` (deben seguir funcionando exactamente igual).
- `orion-security` como paso adicional del pipeline para este REQ (descartado explícitamente por
  el humano en P7 — "Accesos rápidos" reutiliza el gate existente sin acciones nuevas de riesgo
  amarillo/rojo).

## Módulos afectados
- `ui/gui.py` — **reemplazo completo**: nueva clase de ventana principal maximizada con
  sidebar/centro/panel derecho mediante layouts Qt (`QHBoxLayout`/`QVBoxLayout`/`QGridLayout`), en
  vez del único `QWidget` de 400x400 con `paintEvent` custom actual. Mantiene
  `update_gui_state()`/`GLOBAL_STATE` (o su evolución equivalente) como mecanismo de alimentación
  cross-thread, y el patrón de `QSystemTrayIcon` + `closeEvent` que oculta en vez de cerrar.
- `main.py` — punto de construcción de la ventana (bloque `if not headless`, líneas ~188-197)
  actualizado a la nueva clase. Se preserva la restricción de hilo: GUI construida y ejecutada en
  el hilo principal (`app.exec()`), lógica del asistente en el hilo daemon (`jarvis_runner`).
- `system_actions/system_info.py` — nuevas funciones que devuelven valores numéricos (no strings
  formateados para voz) de CPU/RAM/Disco/Red, para consumo directo del widget "Estado del
  sistema".
- `skills/weather_skill.py` y/o módulo nuevo (p. ej. `os_integration/weather_data.py`) — nueva
  función que consulta wttr.in en formato JSON (`format=j1`) y devuelve campos estructurados
  (temperatura, condición, ciudad, hora, fecha), sin duplicar ni romper la skill conversacional
  existente (`GET_WEATHER` sigue devolviendo la frase de texto de siempre).
- `ai/memory_manager.py` — nuevo método (p. ej. `get_recent(user_id, limit)`) que devuelve las N
  interacciones más recientes del usuario sin filtro de query ni umbral de importancia, para la
  tarjeta "Actividad reciente".
- `agents/action_registry.py` — nueva acción `open_spotify` (busca el ejecutable de escritorio en
  rutas conocidas de instalación; si no existe, abre `https://open.spotify.com` con
  `webbrowser.open`), registrada en `ACTION_REGISTRY` con el mismo patrón GREEN + gate que las
  demás acciones de apertura de apps (`open_notepad`, `open_explorer`, etc.).
- `ui/personality.py` — nueva función de saludo dinámico por hora del día (Buenos
  días/tardes/noches + nombre), separada de `get_random_greeting()` (que se conserva intacta para
  el flujo de voz/CLI existente).
- `config_manager.py` — posible nueva entrada de configuración para el nombre de usuario mostrado
  en el saludo central (p. ej. `display_name`) — la fuente exacta (config, `.env`, u otra) queda
  delegada a `orion-architect` (ver Asumidos); el humano confirmó explícitamente que no debe
  hardcodearse "Johan" en el código.

## Comportamiento actual vs deseado
| Actual | Deseado |
|--------|---------|
| `ui/gui.py` es un widget flotante 400x400 sin bordes, siempre encima, con un núcleo de energía animado | Ventana principal maximizada con barra de título estándar (min/max/cerrar) y layout sidebar + centro + panel derecho |
| El estado del sistema (CPU/RAM/Disco/Red) solo es accesible por voz/texto vía `system_actions` | Tarjeta "Estado del sistema" en la GUI con valores numéricos reales, refrescados periódicamente |
| No hay accesos directos en la GUI a abrir aplicaciones | Grid de 6 accesos rápidos que ejecutan acciones reales gateadas (5 existentes + Spotify nuevo) |
| No existe ningún feed de actividad reciente visible en la GUI | Tarjeta "Actividad reciente" alimentada por un método nuevo de `memory_manager` con las últimas interacciones reales |
| El saludo (`get_random_greeting()`) es una frase fija aleatoria, sin relación con la hora | Saludo dinámico "Buenos días/tardes/noches, [nombre]" calculado según la hora del sistema al abrir la ventana |
| El clima no tiene ninguna representación visual en la GUI (solo respuesta de texto por voz/chat) | Tarjeta de clima con datos reales de wttr.in, estructurados en temperatura/condición/ciudad/hora/fecha |
| Cerrar la ventana la oculta en la bandeja del sistema (comportamiento ya existente en `closeEvent`) | Se preserva exactamente: el botón "×" de la nueva ventana también minimiza a bandeja, no termina el proceso |

## Criterios de aceptación
- [ ] CA-01: Al lanzar `main.py` sin `--headless`, se abre una única ventana PyQt6 **maximizada**
      (no modo kiosco) con barra de título visible y controles minimizar/maximizar/cerrar
      funcionales.
- [ ] CA-02: La ventana muestra las 3 zonas del mockup — sidebar izquierdo (~250px) con logo +
      nombre de agente dinámico + navegación de 7 ítems + indicador "Sistema activo"; zona central
      con saludo, visualizador de estado y barra de comando; panel derecho (~350px) con las 4
      tarjetas (Estado del sistema, Accesos rápidos, Actividad reciente, Clima).
- [ ] CA-03: El saludo central cambia según la hora del sistema en el momento de abrir la ventana:
      "Buenos días" (antes de 12:00), "Buenas tardes" (12:00–18:59), "Buenas noches"
      (19:00–04:59) — verificable con un test que mockee `datetime.now()`.
- [ ] CA-04: El nombre mostrado en el saludo proviene de la fuente de configuración que defina
      `orion-architect` — en ningún caso el string "Johan" queda hardcodeado en el código fuente.
- [ ] CA-05: De los 7 ítems del sidebar, únicamente "Inicio" navega a contenido real; los otros 6
      son visibles pero no ejecutan ninguna acción real (deshabilitados o sin handler conectado).
- [ ] CA-06: La tarjeta "Estado del sistema" muestra porcentajes numéricos reales de CPU, RAM,
      Disco y Red obtenidos vía `psutil` (nunca valores de ejemplo fijos) y se refresca sin
      bloquear el hilo de eventos de la GUI (uso de `QTimer`; ninguna llamada bloqueante de
      `psutil`/red directamente sobre el hilo principal sin mitigación).
- [ ] CA-07: Cada uno de los 6 botones de "Accesos rápidos" (Explorador, Navegador, Notas,
      Calculadora, Captura, Spotify), al pulsarse, invoca la acción correspondiente
      **exclusivamente** a través de `agents/action_registry.py:execute_action()` (nunca llamando
      la función subyacente directo), pasando `channel=ChannelType.DESKTOP`.
- [ ] CA-08: El botón "Spotify" abre la aplicación de escritorio si el ejecutable existe en las
      rutas conocidas de instalación; si no, abre `https://open.spotify.com` en el navegador por
      defecto. Ninguna otra funcionalidad de Spotify (login, control de reproducción) está en
      alcance de este REQ.
- [ ] CA-09: La tarjeta "Actividad reciente" muestra como mínimo las últimas 4 interacciones
      reales del usuario activo (texto + hora), obtenidas de `ai/memory_manager.py` vía un método
      nuevo que ordena solo por recencia (sin filtro de query ni umbral de importancia). Si no hay
      interacciones registradas todavía, la tarjeta muestra un estado vacío explícito, no datos
      inventados ni una lista vacía silenciosa.
- [ ] CA-10: La tarjeta de clima muestra temperatura, condición, ciudad y hora/fecha obtenidos de
      una fuente real (wttr.in), sin usar valores de ejemplo fijos como "24°C" o "Bogotá, CO"
      salvo que sean el resultado real de la consulta en el momento de la prueba.
- [ ] CA-11: El visualizador circular central cambia su animación/color según los 4 estados
      existentes del sistema (IDLE/LISTENING/PROCESSING/RESPONDING), replicando la lógica que ya
      tenía `ui/gui.py`; no se implementa ningún análisis de amplitud/volumen de audio real en
      este REQ (aprobado como simulado en P4).
- [ ] CA-12: La barra de comando central (campo de texto) envía el texto ingresado al mismo
      pipeline de resolución que usa `ui/cli.py` hoy (`core/resolution.py:resolve()`), con
      `channel=ChannelType.DESKTOP`, y muestra la respuesta en la interfaz.
- [ ] CA-13: Pulsar el botón "×" de la ventana oculta la ventana a la bandeja del sistema
      (comportamiento preservado del `closeEvent` actual) — el proceso del asistente sigue
      corriendo; no existe manera de terminar el proceso completo desde ese botón (se mantiene el
      menú de bandeja → "Salir" ya implementado).
- [ ] CA-14: La construcción de la ventana sigue ocurriendo en el hilo principal (`main.py`,
      dentro del bloque `if not headless`) y la lógica del asistente sigue en el hilo daemon
      separado — ningún widget Qt se instancia ni actualiza directamente desde el hilo de trabajo
      (solo vía el mecanismo de polling/cola ya establecido o su evolución).
- [ ] CA-15: El modo `--headless` sigue funcionando sin ningún cambio de comportamiento (no se
      construye ninguna ventana; el loop de `main()` corre igual que hoy).
- [ ] CA-16: Ninguna acción de "Accesos rápidos" introduce un nivel de riesgo AMARILLO o ROJO
      nuevo — todas quedan registradas como GREEN en `security_manager`, igual que las acciones
      equivalentes ya existentes, y el REQ no pasa por `orion-security` (confirmado explícitamente
      por el humano en P7).
- [ ] CA-17: `python -m py_compile` pasa sin errores en todos los módulos modificados, y
      `pytest tests/` no introduce ningún fallo nuevo respecto al baseline que documente
      `orion-baseline`.

## Casos borde
- `psutil` falla o no está disponible (ya contemplado por `_has_psutil()` en `system_info.py`) →
  la tarjeta de Estado del sistema degrada a "N/D" por métrica, sin crashear la GUI.
- wttr.in no responde o hay timeout (ya capturado con `except Exception` en `weather_skill.py`) →
  la tarjeta de clima muestra un estado de error/"no disponible"; la llamada de red no puede
  bloquear el hilo de la GUI (asíncrona o con timeout corto).
- No hay interacciones registradas todavía en `memory_manager` para el usuario activo →
  "Actividad reciente" muestra un mensaje de estado vacío explícito.
- Spotify no está instalado y el navegador por defecto tampoco puede abrirse → el botón no
  crashea la app; devuelve/muestra un mensaje de error igual que las demás acciones fallidas de
  `action_registry.py` (patrón `try/except` + string de error).
- El usuario intenta terminar el proceso por completo (no solo minimizar) → se mantiene el
  mecanismo existente (menú de la bandeja del sistema → "Salir"), el mockup no define un botón
  para esto.
- Multi-monitor: si el sistema tiene más de un monitor, la ventana maximizada se abre en el
  monitor primario (ver Asumidos).
- Cambio de hora del sistema mientras la app está abierta (p. ej. de tarde a noche) → el saludo se
  calcula una sola vez al abrir la ventana; no se recalcula en vivo salvo que `orion-architect`
  decida lo contrario explícitamente.

## Asumidos
- ASUMIDO: La ventana maximizada se abre en el monitor primario del sistema en configuraciones
  multi-monitor — confirmar antes de implementar si el humano usa más de un monitor.
- ASUMIDO: La fuente del nombre de usuario para el saludo ("Johan" en el mockup) se resuelve como
  una nueva entrada de configuración a definir por `orion-architect` (p. ej. `config_manager` o
  `.env`) — el humano confirmó explícitamente en P8 que no debe hardcodearse y que, si no existe
  fuente hoy, es una decisión de arquitectura, no de spec.
- ASUMIDO: El icono de notificaciones del header es decorativo en este REQ (no hay sistema de
  notificaciones real que alimentarlo) — a confirmar con el humano en la aprobación de esta SPEC
  si se espera que dispare algo real (p. ej. tareas pendientes) o si debe quedar puramente visual.
- ASUMIDO: "Modo activo" en el header refleja el mismo estado de 4 valores
  (IDLE/LISTENING/PROCESSING/RESPONDING) que ya existe, no un concepto nuevo de "modos" del
  asistente.
- ASUMIDO — proceso, no diseño: las respuestas a P3 (literalidad del mockup) y P7 (no se requiere
  `orion-security`) llegaron por relevo del coordinador tras un fallo técnico (timeout) del flujo
  de aprobación de UI directa con el humano, quien autorizó explícitamente proceder con las
  opciones recomendadas. Quedan documentadas tal cual en esta SPEC para que el humano las revise y
  corrija explícitamente en la aprobación de este documento si algo no refleja su intención real.

## Riesgos activos (heredados del contexto, no resueltos por esta SPEC)
- `ui/gui.py` actual depende de comportamientos específicos (bandeja del sistema, arrastre manual
  de ventana sin barra de título) que este REQ reemplaza deliberadamente por controles de ventana
  estándar — riesgo de regresión de UX si el usuario esperaba el comportamiento de "orbe flotante
  siempre encima" para otro propósito no mencionado en el pedido original.
- Spotify y "actividad reciente" con datos reales no tenían fuente antes de este REQ; ambos
  agregan alcance de backend concreto (nuevo método de memoria, nueva acción de apertura de app)
  que `orion-architect` debe dimensionar con cuidado dentro del mismo REQ.
