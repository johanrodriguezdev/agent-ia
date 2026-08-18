# Baseline REQ-013 — Rediseño UI escritorio NODDOO estilo chat de IA

**Fecha:** 2026-08-17
**Agente:** orion-baseline

## Estado actual del sistema

### `ui/gui.py` — `JarvisMainWindow`
Ventana principal `QMainWindow` (REQ-008), layout horizontal fijo de 3 columnas:
`Sidebar` (250px) — columna central (`HeaderBar` + `CenterPanel`, stretch=1) — `RightPanel`
(350px). No hay concepto de "vista"/routing: `Sidebar.nav_selected` solo lo emite el ítem
"Inicio" (los otros 6 están `setEnabled(False)`, sin handler conectado — ver `sidebar.py`).
Un único `QTimer` de 100ms (`_poll_state`) sincroniza `GLOBAL_STATE`/`WAKE_STATE` (variables
de módulo hilo-seguras) hacia `CenterPanel`/`HeaderBar`.

`_handle_command(text)` es el único punto de entrada del pipeline de comandos: llama
`core/resolution.py:resolve()` vía `run_async()` (nunca directo desde el hilo GUI).
`_on_command_done(resolution)` hace dos cosas:
1. `self.center_panel.show_response(result_text)` — pasa el texto de respuesta al panel central.
2. `memory.store(f"{resolution.matched_by} | {result_text}", category="interaction")` — persiste
   **solo** un string combinado `matched_by | result_text` en `ai/memory_manager.py`. **El texto
   original escrito/hablado por el usuario nunca se guarda** (confirma la premisa de CA-09: hoy
   no existe persistencia del turno de usuario).

No existe ningún estado de "conversación activa" ni `conversation_id` en ninguna parte del
código de `ui/` — cada envío de comando es una interacción suelta sin agrupación.

### `ui/widgets/center_panel.py` — `CenterPanel`
Zona central actual: saludo dinámico (`get_time_based_greeting`, refresco cada 60s),
subtítulo fijo, `VoiceOrb` centrado, un `QLabel` de estado (`_status_label`) que:
- En reposo muestra texto fijo por estado (`_STATE_STATUS_TEXT`: "En espera...",
  "Escuchando...", etc.)
- Al recibir respuesta (`show_response(text)`), **trunca a 200 caracteres** (`text[:200]`) y
  reemplaza el texto — no hay historial visual de turnos anteriores, cada respuesta pisa a la
  anterior.

Barra de comando inferior: `QLineEdit` (`_command_input`) + toggle de manos libres
(`_wake_toggle`, REQ-009) + botón enviar (`send_btn`). Señales `command_submitted(str)` y
`hands_free_toggled(bool)`. No hay chips, no hay composer separado del input.

Estilo: QSS hardcodeado de tema oscuro único (`_CENTER_QSS`, colores fijos tipo `#10182a`,
`#ffffff`, `#4fc3ff`). No existe ningún mecanismo de tema claro/oscuro ni switch — el color de
fondo de toda la ventana también está hardcodeado en `ui/gui.py` (`#070b14`,
`self.setStyleSheet("QMainWindow { background-color: #070b14; }")`).

### `ui/widgets/sidebar.py` — `Sidebar`
Ancho fijo 250px, `QVBoxLayout`. Logo (nombre de agente dinámico vía `get_agent_name()`) + 7
ítems de navegación (`_NAV_ITEMS`), de los cuales **solo "Inicio" está habilitado**; el ítem
"conversaciones" existe visualmente (`💬 Conversaciones`) pero está deshabilitado
(`enabled=False`), sin listado, sin lógica de carga de historial, sin acción "Nueva
conversación". Termina con indicador estático "● Sistema activo". QSS de tema oscuro fijo
(`_SIDEBAR_QSS`).

### `ui/widgets/right_panel.py` — `RightPanel`
Ancho fijo 350px, `QScrollArea` con 4 tarjetas autocontenidas (`SystemStatusCard`,
`QuickActionsCard`, `RecentActivityCard`, `WeatherCard`), cada una con su propio QSS/tema
oscuro fijo (`objectName("Card")` por tarjeta, sin frame compartido). Se puebla una sola vez en
`__init__`; cada tarjeta gestiona sus propios timers/llamadas async. No tiene ningún mecanismo
de tema — cambiar a claro/oscuro requeriría tocar el QSS de cada tarjeta individualmente
(`system_status_card.py`, `quick_actions_card.py`, `recent_activity_card.py`,
`weather_card.py`), no solo `right_panel.py`.

### `ui/widgets/header_bar.py` — `HeaderBar`
Barra superior con píldora de modo (`_mode_pill`, refleja los 4 estados IDLE/LISTENING/
PROCESSING/RESPONDING), indicador de manos libres (`_wake_indicator`, REQ-009, 3 estados) y
campana de notificación decorativa sin handler. No existe ningún control de selector de tema
todavía — el "Asumido" de SPEC-013 (ubicarlo aquí, junto al indicador de manos libres) es
sobre un espacio que hoy no tiene ese control.

### `ui/widgets/voice_orb.py` — `VoiceOrb`
Widget fijo 220x220px, `paintEvent` custom (anillo + núcleo + pulso), dirigido por
`set_state()` sobre los mismos 4 estados. Colores por estado hardcodeados en
`_STATE_COLORS` (tuplas RGB/RGBA fijas) — no hay indirección de tema. Es un widget
autocontenido, no depende de QSS externo, por lo que un cambio de tema requeriría
parametrizar `_STATE_COLORS` o inyectar una paleta.

### `ai/memory_manager.py` — `UnifiedMemory` (singleton `memory`)
Tabla `memories` en `unified_memory.db` (SQLite): columnas `id, user_id, text,
embedding_json, importance, category, timestamp, archived, source`. **No existe columna
`conversation_id` ni ningún concepto de agrupación de turnos.** Cada fila es una entrada
suelta. Funciones existentes relevantes:
- `store(text, user_id, category, importance, source)` — inserta una fila. Hoy se llama desde
  `gui.py` con el string combinado `matched_by | result_text`, no con el texto real del
  usuario.
- `get_recent(user_id, limit, category="interaction")` — usada hoy para consultas de
  "actividad reciente" (`RecentActivityCard`), sin noción de conversación.
- `search_semantic`, `search_keyword`, `get_important_memories`, `get_summary`,
  `store_summary`, `get_recent_summaries`, `get_user_profile_text`, `consolidate`,
  `clear_user_memory` — ninguna referencia conversaciones agrupadas.

No hay ninguna función `list_conversations()` ni `get_conversation_turns()` — deben crearse
desde cero (CA-10, CA-11). La migración de filas legacy sin `conversation_id` (CA-12) parte de
una tabla que **nunca tuvo esa columna**, no de una migración de un esquema previo con la
columna opcionalmente vacía en algunas filas — es una columna completamente nueva.

### `config_manager.py`
Patrón `get_/set_` confirmado y consistente para preferencias simples persistidas en
`config.json` (ver `get_weather_city`/`set_weather_city` líneas 102-116,
`get_display_name`/`set_display_name` líneas 86-99): función `get_X()` lee `load_config()` y
devuelve con default; `set_X(value)` lee, muta la clave y llama `save_config(config)`. No
existe hoy ninguna clave `ui_theme` en `DEFAULT_CONFIG` ni en `CONFIG_FILE` — `get_ui_theme()`/
`set_ui_theme()` deben agregarse siguiendo exactamente ese patrón (incluyendo el fallback en
`load_config()` para configs antiguos sin la clave, como se hace con `weather_city` en las
líneas 49-50).

## Archivos que serán modificados (previsión)

- `ui/gui.py` — reescritura de `_init_ui` (nuevo layout), `_on_command_done` (dejar de
  truncar/pisar y alimentar el feed de burbujas en vez de `show_response`), wiring de señales
  del nuevo sidebar de historial y del selector de tema.
- `ui/widgets/center_panel.py` — reemplazo sustancial (feed de burbujas + composer + chips en
  vez de saludo + orb + status label truncado), o división en widgets nuevos.
- `ui/widgets/sidebar.py` — nuevo listado de conversaciones funcional + acción "Nueva
  conversación", conservando los 7 ítems existentes (activando "Conversaciones").
- `ui/widgets/right_panel.py` — sin cambio funcional, solo ajuste de estilos para tema.
- `ui/widgets/system_status_card.py`, `quick_actions_card.py`, `recent_activity_card.py`,
  `weather_card.py` — ajuste de QSS para respetar tema activo (cada uno tiene su propio QSS
  hardcodeado hoy).
- `ui/widgets/header_bar.py` — agregar control de selector de tema.
- `ui/widgets/voice_orb.py` — parametrizar colores por tema si aplica (hoy hardcodeados en
  `_STATE_COLORS`); reubicación a definir en arquitectura.
- Widgets nuevos en `ui/widgets/` (burbuja de mensaje, feed de chat scrolleable, composer con
  chips, listado de conversaciones del sidebar) — nombres/división a definir en
  `orion-architect`.
- `ai/memory_manager.py` — agregar columna `conversation_id` a `memories` (o tabla nueva),
  función de persistencia de turno completo (usuario + IA), `list_conversations(user_id)`,
  `get_conversation_turns(conversation_id)`. Requiere estrategia de migración para las filas
  existentes sin `conversation_id` (CA-12) — hoy la tabla no tiene esa columna en absoluto.
  **Nota:** `main.py` también llama a `memory.store()` de forma independiente (línea ~166-172,
  ver comentario en `get_recent()`) — verificar en arquitectura si ese segundo call queda
  afectado por el cambio de esquema.
- `config_manager.py` — agregar `ui_theme` a `DEFAULT_CONFIG`, `get_ui_theme()`/
  `set_ui_theme()`, y el fallback correspondiente en `load_config()`.
- Tests a actualizar/crear: `tests/test_gui_widgets.py`, `tests/test_cli_gui_active.py`,
  `tests/test_wake_word_gui.py`, `tests/test_memory_manager_recent.py` (regresión, existen y
  pasan hoy) + tests nuevos para widgets y funciones agregadas.

## Fallos pre-existentes (no atribuibles a este REQ)

Ninguno. Suite completa ejecutada sobre el working tree actual (que ya incluye cambios sin
commitear de REQs previos — `config_manager.py`, `main.py`, `ui/widgets/center_panel.py`,
`ui/widgets/weather_card.py`, `tests/test_gui_widgets.py`, `tests/test_main.py`, ver
`git status`):

```
226 passed, 3 warnings in 10.14s
```

Los 3 warnings son benignos y no relacionados con REQ-013:
- 2x `DeprecationWarning` de la librería `speech_recognition` (`aifc`, `audioop` deprecados
  en Python 3.13) — dependencia de terceros, no código propio.
- 1x `PytestReturnNotNoneWarning` en `tests/test_agents.py::test_ca1_orchestrator` (el test
  retorna un valor en vez de solo usar `assert`) — preexistente, no relacionado con UI/memoria.

`python -m py_compile` verificado sin errores sobre los 8 módulos previstos como afectados
(`ui/gui.py`, `ui/widgets/center_panel.py`, `ui/widgets/sidebar.py`,
`ui/widgets/right_panel.py`, `ui/widgets/header_bar.py`, `ui/widgets/voice_orb.py`,
`ai/memory_manager.py`, `config_manager.py`).

Los 4 archivos de test de regresión mencionados en SPEC-013 (CA-22) existen y están incluidos
en el run anterior, todos en verde: `test_gui_widgets.py`, `test_cli_gui_active.py`,
`test_wake_word_gui.py`, `test_memory_manager_recent.py`.
