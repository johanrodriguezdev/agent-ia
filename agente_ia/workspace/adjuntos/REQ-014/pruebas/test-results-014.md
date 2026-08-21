# Resultados de prueba REQ-014 — Rediseño completo desde cero UI escritorio NODDOO

**Agente:** orion-tester
**Fecha:** 2026-08-19
**Punto de partida:** `desarrollo-log-014.md` (orion-dev) + `SPEC-014.md` (43 CA) +
`arquitectura-014.md` (494 líneas). Verificación realizada de forma **independiente**:
no se dio por buena ninguna cifra reportada por orion-dev sin correrla/recalcularla acá
mismo.

---

## Compilación
- `python -m py_compile main.py ai/memory_manager.py ui/*.py ui/components/*.py
  tests/*.py` (excluyendo `tests/_tmp_manual_verify_012b.py`, script de scratch ya roto
  antes de este REQ): **OK**, sin errores.

## Tests existentes
- Comando: `PYTEST_QT_API=pyqt6 python -m pytest tests/ --tb=short -q` (corrido por este
  agente, no reutilizado del reporte de orion-dev).
- Resultado: **366 passed, 2 failed**.
- Nuevos fallos: **ninguno**. Los 2 fallos (`test_llm_provider.py::test_ca04_ask_anthropic_*`)
  son `ModuleNotFoundError: No module named 'anthropic'` — exactamente los mismos 2
  documentados como pre-existentes en `baseline-014.md` (paquete no instalado en este
  entorno, no atribuible a REQ-014). Verificado que `tests/conftest.py` fija
  `PYTEST_QT_API=pyqt6` (línea 40) — sin esto, la suite da un falso 64/66 fallos por el
  `PySide6` huérfano del entorno (riesgo documentado por `orion-baseline`).

## Verificación estructural del diff (independiente de lo declarado por orion-dev)
`git diff --stat` / `git status --short` contra `HEAD` confirma **exactamente** lo
declarado en `desarrollo-log-014.md`:
- 8 `git rm`: `ui/widgets/{chat_bubble,chat_feed,composer,conversation_list,
  center_panel,header_bar,sidebar,voice_orb}.py`.
- 2 reescritos in-place: `ui/theme.py`, `ui/gui.py`.
- Editados puntualmente: `ai/memory_manager.py`, `main.py`, `requirements.txt`,
  `tests/conftest.py`.
- 12 nuevos: `ui/main_window.py`, `ui/sidebar.py`, `ui/chat_area.py`,
  `ui/message_bubble.py`, `ui/typing_indicator.py`, `ui/input_bar.py`,
  `ui/animations.py`, `ui/workers.py`, `ui/components/{__init__,avatar,code_block,
  markdown_renderer}.py`.
- 5 widgets conservados sin ningún cambio de código (`right_panel.py` + 4 tarjetas) —
  confirmado ausentes del diff.
- Tests: 2 retirados (`test_gui_widgets.py`, `test_chat_widgets.py`), 9 nuevos, 4
  modificados (`test_conversation_memory.py`, `test_main.py`, `test_theme.py`,
  `test_wake_word_gui.py`), 1 sin cambios (`test_config_manager_ui_theme.py`).

## Puntos de máxima atención (verificados por lectura de código real)
| Punto | Verificación | Resultado |
|---|---|---|
| `ui/gui.py` shim | Leído completo (33 líneas): expone únicamente `GLOBAL_STATE`, `WAKE_STATE`, `update_gui_state()`, `update_wake_state()`. `voice/wake_word.py` (líneas 102, 185) y `ui/stt/transcriber.py` siguen importando `update_gui_state` sin error. | OK |
| `ai/memory_manager.py` diff quirúrgico | `git diff` muestra únicamente la adición de `delete_conversation()` (26 líneas insertadas); ninguna otra línea del archivo se tocó. | OK |
| `ui/widgets/voice_orb.py` retirado sin referencias rotas | `grep -ri "voiceorb\|voice_orb"` en todo `*.py`: solo aparece en comentarios/docstrings de `ui/chat_area.py`, `ui/theme.py`, `tests/test_theme.py` documentando el retiro — ningún import ni uso funcional. | OK |

## Verificación independiente de CA-35 (contraste WCAG)
Se escribió un script propio (fórmula de luminancia relativa WCAG 2.1, sanity-check
contra valores conocidos), sin reutilizar el código de `tests/test_theme.py`:
- Los 42 pares × 2 temas (84 combinaciones) declarados como "realmente usados en el
  layout" recalculados de forma independiente: **todos ≥ 4.5:1**.
- Se confirmaron los 3 ajustes de hex reportados por orion-dev: los valores "dados"
  originales SÍ fallaban contra `bg_elevated` (4.48, 4.11, 2.67, 2.61 — y el caso límite
  4.44 de `danger` claro) y los valores ajustados SÍ cumplen (4.84, 4.94, 5.49, 5.60,
  5.77).
- Se hizo además un barrido **propio, más amplio** (todo texto × todo fondo plausible,
  no solo los 42 pares declarados) para buscar combinaciones reales no cubiertas por la
  lista. Aparecieron varias combinaciones que SÍ fallan en abstracto (p. ej.
  `text_disabled`/`bg_elevated` = 4.00, `accent`/`bg_elevated` = 4.31 en claro,
  `on_accent`/`bg_window`, etc.) — se verificó contra el QSS real de `ui/sidebar.py`,
  `ui/input_bar.py`, `ui/main_window.py`, `ui/chat_area.py` y los 5 widgets conservados
  que **ninguna de esas combinaciones fallidas ocurre realmente en el layout**:
  `text_disabled` solo se usa sobre `bg_surface` (nav/footer del sidebar, que sí está en
  la lista y pasa); los 2 casos donde `accent` hubiera quedado sobre `bg_elevated`/
  `bg_hover` en claro (`BubbleMoreButton`, `ThemeToggle:hover`) fueron corregidos por
  orion-dev a usar `bubble_*_fg`/`text_primary` en su lugar (confirmado leyendo
  `ui/chat_area.py:320-324` y `ui/main_window.py:524`); `on_accent` solo aparece emparejado
  con `accent` (Avatar) y `danger` (botón cerrar en hover), ambos en la lista y ambos
  pasan. **Conclusión: CA-35 se sostiene, verificado por una vía independiente.**

## Criterios de la SPEC

| Criterio | Resultado | Nota |
|----------|-----------|------|
| CA-01 (frameless, radius 12px, borde) | PASS | `MainWindow.__init__` + `_QSS_TEMPLATE`; test `test_main_window_frameless_y_translucida` |
| CA-02 (barra de título propia) | PASS | `_TitleBar` con 3 botones funcionales; 3 tests dedicados |
| CA-03 (resize 4 bordes) | PASS | `resize_edge_at()` + `startSystemResize`; 2 tests |
| CA-04 (mover ventana) | PASS | `startSystemMove` desde `_TitleBar`; 1 test |
| CA-05 (sidebar 260↔60px, 200ms) | PASS | `animate_width()`; test `test_sidebar_set_collapsed_anima_ancho` |
| CA-06 (+ Nuevo chat) | PASS | No borra nada, no acuña id hasta el primer turno; 3 tests incl. doble-click |
| CA-07 (título+fecha+eliminar en hover) | PASS | `_ConversationRow`, `_relative_date()`; 5 tests de fechas |
| CA-08 (click carga conversación) | PASS | `get_conversation_turns()` sin modificar; 2 tests |
| CA-09 (eliminar con confirmación) | PASS | `QMessageBox.question` + `delete_conversation()` vía `run_async`; caso borde (conversación activa) cubierto; 6 tests |
| CA-10 (paginación) | PASS | `list_conversations(limit=30, offset=...)`; 3 tests |
| CA-11 (burbujas user/IA distinguibles) | PASS | Roles con QSS distinto, avatar en IA |
| CA-12 (Markdown + código + tablas) | PASS | `render_markdown()` con `fenced_code`+`tables`+`codehilite`, CSS Pygments embebido |
| CA-13 (mensajes de sistema centrados) | PASS | `role="system"`, `QLabel` centrado sin burbuja; test dedicado |
| CA-14 (indicador "escribiendo...") | PASS | `TypingIndicator`, oculto en éxito Y error; tests cruzados con `_on_command_done`/`_on_command_error` |
| CA-15 (autoscroll condicional 40px) | PASS | `_stick_to_bottom` reevaluado en cada `rangeChanged`; 2 tests con `qtbot.waitUntil` real |
| CA-16 (carga diferida lotes de 50) | PASS | `_pending_older_turns` + `_load_older_batch()`; 4 tests incl. orden cronológico |
| CA-17 (colapso >500 chars) | PASS | `_truncate_at_whitespace()`, "Ver más"/"Ver menos" |
| CA-18 (estructura del mensaje) | PASS | Sin cambios de esquema, `MemoryItem`/`store_turn()` ya usan esos 6 campos |
| CA-19 (QTextEdit hasta 5 líneas) | PASS | `_ComposerTextEdit._max_height()` |
| CA-20 (Enter/Shift+Enter) | PASS | `keyPressEvent` override; 2 tests |
| CA-21 (3 botones) | PASS | Adjuntar/voz/enviar presentes |
| CA-22 (drag&drop, allowlist) | PASS | Extensión validada, contenido nunca leído; 3 tests |
| CA-23 (deshabilitado con feedback) | PASS | `set_input_enabled()`; no-regresión condición de carrera REQ-013 verificada con test explícito |
| CA-24 (voz = API pública sin tocar voice/) | PASS | `WakeWordWorker` movido literal; `voice/` ausente del diff (confirmado por `git diff --stat`) |
| CA-25 (`store_turn` sin modificar) | PASS | Confirmado por código y diff de `ai/memory_manager.py` |
| CA-26 (`list_conversations` sin modificar) | PASS | ídem |
| CA-27 (`get_conversation_turns` sin modificar) | PASS | ídem |
| CA-28 (`new_conversation_id` sin modificar) | PASS | `_ensure_conversation_id()` acuña una sola vez; test dedicado |
| CA-29 (sin más cambios a `ai/memory_manager.py`) | PASS | Diff quirúrgico confirmado (ver tabla arriba) |
| CA-30 (`delete_conversation()`) | PASS | Firma exacta, filtrado por `user_id`, no lanza sobre inexistente/ya borrada; 6 tests incl. aislamiento entre usuarios |
| CA-31 (fade-in+slide-up 300ms OutCubic) | PASS | `animate_message_entrance()`; test de duración/easing |
| CA-32 (transición de tema sin flash) | PASS | `fade_theme_transition()` aplicado una vez sobre el widget central; 2 tests |
| CA-33 (hover suave) | PASS | `attach_hover_fade()` en elementos primarios (interpretación acotada, documentada y aprobada en arquitectura); 4 tests |
| CA-34 (2 paletas completas) | PASS | `DARK_PALETTE`/`LIGHT_PALETTE` en `ui/theme.py` |
| CA-35 (contraste WCAG AA) | PASS | Recalculado de forma **independiente** (ver sección dedicada arriba) |
| CA-36 (tema en caliente sin reiniciar) | PASS | `register_themed()`/`theme_changed`; test verifica cambio de stylesheet en 5 bloques |
| CA-37 (persistencia de tema) | PASS | `config_manager.get_ui_theme/set_ui_theme` sin modificar |
| CA-38 (panel derecho se conserva) | PASS | `RightPanel` sin cambios de código, instanciado igual; test dedicado |
| CA-39 (chips mismo contenido/mecanismo) | PASS | `_CHIPS` idéntico a REQ-013 (5 chips, mismos labels/payloads) |
| CA-40 (indicador verde/amarillo/rojo) | PASS | `_risk_color()` vía `classify_action()`, fail-closed a `danger`; test con GREEN/YELLOW/sin-clasificar |
| CA-41 (nunca bypassea `require_confirmation`) | PASS | Chips de acción SIEMPRE vía `run_async(execute_action, ..., channel=DESKTOP)`; test confirma `call_count == 0` de la función directa |
| CA-42 (`py_compile` limpio) | PASS | Verificado de forma independiente (ver "Compilación") |
| CA-43 (suite completa sin regresiones) | PASS | Verificado de forma independiente: 366 passed / 2 failed (pre-existentes) |

**43/43 criterios: PASS**

## Casos borde (SPEC-014, 1ª pasada)
| Caso borde | Verificación |
|---|---|
| Doble click "+ Nuevo chat" no crea huérfanas | `test_doble_nueva_conversacion_no_acuna_ids` — PASS |
| Eliminar conversación activa deja estado consistente | `test_conversation_deleted_activa_dispara_nueva_conversacion` — PASS |
| Cambio de tema con input deshabilitado no interrumpe resolución | `apply_theme()` no toca `_pending_user_text` ni el estado de `run_async` en curso — verificado por lectura de código, riesgo bajo |
| Sidebar con cientos de conversaciones no bloquea arranque | Paginación CA-10 (`limit=30`) cubre esto |
| Filas legacy `conversation_id IS NULL` | Heredado de REQ-013, no tocado en este REQ |
| Reinicio de la app: conversación nueva vacía | `_conversation_id: Optional[str] = None` al construir `MainWindow` |
| Resize de ventana frameless no rompe layout | `resizeEvent()` reajusta `set_available_width()` de cada burbuja |
| Archivo con extensión no soportada rechazado con feedback | `test_input_bar_handle_attachment_extension_invalida_rechaza_con_feedback` — PASS |
| Borrar conversación ya borrada no lanza | `test_delete_conversation_ya_borrada_retorna_false_en_el_segundo_intento` + `test_sidebar_delete_fallido_no_quita_item_ni_emite` — PASS |

## Regresión
| Área revisada | Resultado |
|---------------|-----------|
| Suite completa (366 tests aplicables) | Sin fallos nuevos — 2 pre-existentes documentados |
| `voice/` (prohibido tocar) | Ausente del diff — confirmado |
| `core/`, `intent/`, `skills/`, `agents/`, `channels/` (prohibidos) | Ausentes del diff |
| 5 widgets conservados (`right_panel` + 4 tarjetas) | Sin cambios de código; consumen la paleta nueva automáticamente vía `register_themed()` |
| Condición de carrera REQ-013 (envío concurrente) | No-regresión confirmada con `test_segundo_envio_bloqueado_mientras_resuelve_el_primero` |

## Veredicto (1ª pasada, 43 CA de SPEC-014): ✅ PASS

43/43 criterios de aceptación verificados contra el código real (no solo contra lo
reportado por `orion-dev`). Compilación limpia, suite completa sin regresiones
(verificado de forma independiente), estructura del diff coincide exactamente con lo
declarado, los 3 puntos de máxima atención señalados en el handoff se confirmaron por
lectura directa de código, y CA-35 (contraste WCAG) fue recalculado con una herramienta
propia, incluyendo un barrido más amplio que el de la lista de 42 pares del propio dev,
sin encontrar ninguna combinación real no cubierta.

---

# Resultados de prueba REQ-014 — addendum §7 (2ª pasada)

**Agente:** orion-tester
**Fecha:** 2026-08-19
**Punto de partida:** Johan rechazó la validación manual de la 1ª pasada (43/43 CA, QA
✅ COMPLETADO) por un bug visual real (bleed-through/texto superpuesto en el panel
derecho) + pedido de eliminarlo y refinar la dirección visual — mismo patrón que REQ-013
4ta/5ta pasada. `arquitectura-014.md` §7 (addendum, líneas 498-825) aprobada por Johan
tal cual, con 2 puntos de confirmación explícita (`git rm` de las 5 tarjetas/panel, tema
claro como default). `orion-dev` implementó el addendum completo — ver
`desarrollo-log-014.md` (sección "addendum §7 (2ª pasada)"). Esta sección documenta
**solo** la re-verificación de lo nuevo de esta 2ª pasada — no reescribe nada de la
sección de 1ª pasada de arriba (43 CA ya verificados PASS, sin re-tocar salvo lo que el
addendum señala explícitamente).

Verificación hecha por lectura directa de código real y ejecución propia de comandos —
nada se dio por bueno solo porque `desarrollo-log-014.md` lo reportaba.

## Compilación
- `python -m py_compile main.py ai/memory_manager.py ui/main_window.py ui/chat_area.py
  ui/input_bar.py ui/theme.py ui/sidebar.py ui/components/avatar.py ui/*.py
  config_manager.py`: **OK**, sin errores.

## Tests existentes
- Comando: `PYTEST_QT_API=pyqt6 python -m pytest tests/ --tb=short -q` (corrido por este
  agente sobre el estado actual del working tree, no reutilizado del reporte de
  orion-dev).
- Resultado: **379 passed, 2 failed** — coincide EXACTAMENTE con lo reportado por
  orion-dev. Los 2 fallos siguen siendo `test_llm_provider.py::test_ca04_ask_anthropic_*`
  (`ModuleNotFoundError: anthropic`), los mismos 2 pre-existentes de `baseline-014.md`.
- Aritmética verificada contra el número de referencia de la 1ª pasada (366 passed): -1
  test retirado (`test_right_panel_presente_en_el_layout`, confirmado ausente de
  `tests/test_main_window.py`) + 14 tests nuevos (5 en `tests/test_avatar.py` — nuevo,
  leído completo, aserciones reales no vacuas — + 3 en `test_main_window.py` + 3 en
  `test_input_bar.py` + 3 en `test_theme.py`) = 366 - 1 + 14 = **379**. Coincide. Cero
  regresiones ocultas — no es solo "el número cuadra", se confirmó con una pasada de
  regresión dirigida (ver abajo) que las áreas no tocadas por el addendum siguen en
  verde.

## Punto 1 — §7.1: fix del bug de composición (`WA_StyledBackground`)
- `ui/main_window.py` — confirmado por lectura directa: `root.setAttribute(
  Qt.WidgetAttribute.WA_StyledBackground, True)` inmediatamente después de crear `root`
  (línea 225) y `body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)`
  inmediatamente después de crear `body` (línea 240). Ambos confirmados con grep +
  lectura de contexto (3 líneas antes/después).
- Captura `pruebas/screenshot-addendum7-widget-grab.png` — **abierta y revisada por este
  agente** (no solo leído el reporte de orion-dev que la describe): fondo sólido en toda
  la ventana, sin ninguna zona sin pintar, sin texto superpuesto/ghosting en ningún punto
  visible de la captura. Panel derecho ausente. Tema claro. Saludo "Buenos días, WHOAMI"
  en tipografía grande/bold consistente con 40px/700 (§7.3.2). Input como píldora con
  sombra sutil visible debajo, ícono de adjuntar y micrófono sin caja (quietos), botón de
  enviar como único círculo lleno (azul). Chips con borde fino, menor peso visual, dos de
  ellos con punto de color (badge de riesgo). Cluster superior derecho (luna, píldora "~
  Modo activo", micrófono) de tamaño reducido, sin cajas propias. **Resultado: PASS** —
  la causa raíz reportada (bleed-through/texto superpuesto) no es reproducible en esta
  captura; el fix es consistente con el diagnóstico de `arquitectura-014.md` §7.1.
  Nota: como señala honestamente el propio dev-log, `QWidget.grab()` no reproduce el
  compositor real de Windows (alpha blending contra el escritorio) — la confirmación
  final de que el bleed-through desapareció en la práctica queda, como siempre, para la
  prueba manual de Johan con la app visible en su escritorio real.

## Punto 2 — §7.2: eliminación del panel derecho
- `git status --short` / `git diff --stat HEAD`: los 5 archivos
  (`ui/widgets/right_panel.py`, `system_status_card.py`, `quick_actions_card.py`,
  `recent_activity_card.py`, `weather_card.py`) aparecen con estado `D ` (staged
  deletion, columna de índice) — confirmado `git rm` real, no un borrado suelto en el
  working tree. Junto a los 8 de la 1ª pasada, son 13 archivos `D ` en total.
- `ui/main_window.py` ya no instancia `RightPanel` — confirmado leyendo `_init_ui()`
  completo: sin import, sin `self.right_panel = ...`, sin `addWidget`. `body_layout`
  contiene únicamente `sidebar` + `center_column` (chat_area + input_bar).
- `grep -rn "RightPanel|right_panel|SystemStatusCard|QuickActionsCard|
  RecentActivityCard|WeatherCard" ui/ tests/`: todos los resultados (`ui/theme.py`,
  `ui/main_window.py`, `ui/workers.py`, `tests/test_main_window.py`, `tests/test_theme.py`,
  `tests/test_wake_word_gui.py`) son comentarios/docstrings documentando el retiro —
  confirmado leyendo cada línea con contexto, ninguno es un import ni una referencia
  funcional. Único resultado fuera de comentarios: `tests/_tmp_manual_verify_012.py`
  (`from ui.widgets.weather_card import WeatherCard`) — verificado con `git log`: este
  archivo ya existía tal cual en el commit `eb190b3` (anterior a REQ-014), sin cambios en
  este REQ, y no lo recolecta pytest (no matchea `test_*.py`) — no es una regresión de
  este REQ, mismo patrón que `_tmp_manual_verify_012b.py` ya señalado en la 1ª pasada.
- `ChatArea`/`InputBar` acotados a 760px y centrados — confirmado leyendo el código:
  `ui/chat_area.py` define `_MAX_CONTENT_WIDTH = 760`, `ChatArea.__init__` llama
  `self.setAlignment(Qt.AlignmentFlag.AlignHCenter)` y
  `self._content.setMaximumWidth(_MAX_CONTENT_WIDTH)`; `ui/input_bar.py` define la misma
  constante y `InputBar.__init__` llama `self.setMaximumWidth(_MAX_CONTENT_WIDTH)`;
  `ui/main_window.py` centra `input_bar` en `center_column` con
  `Qt.AlignmentFlag.AlignHCenter` explícito (tercer argumento de `addWidget`). Extensión
  no anticipada por el addendum pero correcta: `ChatArea._bubble_available_width()`
  (usado tanto en `_mount_bubble()` como en `resizeEvent()`) calcula
  `min(width, _MAX_CONTENT_WIDTH) - 32`, evitando que redimensionar la ventana reintroduzca
  el wrap-width incorrecto — consistente con la decisión de implementación #2 documentada
  por orion-dev. **Resultado: PASS.**

## Punto 3 — §7.3: los 7 valores visuales exactos
Verificado leyendo el QSS real (`_QSS_TEMPLATE`/`_TITLEBAR_QSS_TEMPLATE` de
`ui/chat_area.py`, `ui/input_bar.py`, `ui/main_window.py`), no el reporte:

| Valor aprobado en §7.3 | Código real | Resultado |
|---|---|---|
| `#GreetingLabel` 40px/700 | `ui/chat_area.py:330` — `font-size: 40px; font-weight: 700;` | PASS |
| `#GreetingSubtitle` 15px | `ui/chat_area.py:331` — `font-size: 15px;` | PASS |
| `#ComposerTextEdit` padding 16/22, radio 26px | `ui/input_bar.py:387-390` — `padding: 16px 22px; border-radius: 26px;` | PASS |
| `#AttachButton`/`#WakeToggleButton` 36×36px transparentes | `ui/input_bar.py:392-397` — `background-color: transparent; border: none;` + `min/max-width/height: 36px` | PASS |
| `#SendButton` único lleno | `ui/input_bar.py:398-402` — `background-color: $accent; color: $on_accent;` 44×44px, sin borde; ningún otro control del input bar tiene fondo lleno | PASS |
| Sombra `QGraphicsDropShadowEffect` blur 24, offset (0,4) | `ui/input_bar.py:72-73,186-189` — `_SHADOW_BLUR_RADIUS = 24`, `_SHADOW_OFFSET = (0, 4)`, aplicado sobre `_ComposerTextEdit` vía `setGraphicsEffect()` | PASS |
| Márgenes `chat_area`(32,32,32,32) / `input_bar` outer (24,12,24,24) / `_TitleBar` (20,10,16,10) | `ui/chat_area.py:115`, `ui/input_bar.py:156`, `ui/main_window.py:94` — los 3 coinciden exactamente | PASS |
| Chips `border_subtle`/transparente | `ui/input_bar.py:381-384` — `#ComposerChip { background-color: transparent; border: 1px solid $border_subtle; padding: 4px 10px; }` | PASS |
| `#ThemeToggle`/`#WakeIndicator` 28×28px, `#ModePill` padding 4/12 + 11px (§7.3.1, mismo bloque) | `ui/main_window.py:538-547` — coincide exactamente | PASS |

Color de sombra por tema también verificado: `_SHADOW_COLOR_LIGHT = QColor(0,0,0,60)` /
`_SHADOW_COLOR_DARK = QColor(0,0,0,130)` (`ui/input_bar.py:74-75`), aplicado en
`apply_theme()` según `palette.name` — coincide con el addendum. **Sin desviaciones sin
justificar. Resultado: PASS.**

(Desviación ya documentada y evaluada como razonable por `orion-dev`/`orion-architect`:
`#SendButton:hover` se retiró en vez de reusar `$bg_hover` — no rompe ningún CA, el
addendum no especificaba un hover concreto para el botón lleno.)

## Punto 4 — riesgo #17: un solo `QGraphicsEffect` por widget
`grep -rn "attach_hover_fade" ui/`: la única definición vive en `ui/animations.py:144`;
el único otro resultado es el comentario de `ui/input_bar.py:183` que documenta la
verificación — **cero llamadas reales** a `attach_hover_fade(self._input)` ni sobre
`command_row` en ningún punto del código. `_ComposerTextEdit` solo recibe el
`QGraphicsDropShadowEffect` de §7.3.3. **Resultado: PASS**, sin conflicto de efectos.

## Punto 5 — §7.3.4: tema claro default en los 3 lugares
| Archivo | Valor | Resultado |
|---|---|---|
| `ui/theme.py:149` | `DEFAULT_THEME = "light"` | PASS |
| `config_manager.py:21` (`DEFAULT_CONFIG["ui_theme"]`) | `"light"` | PASS |
| `config.json:10` (`"ui_theme"`) | `"light"` | PASS |

Los 3 confirmados con grep + lectura directa del valor. Sin este tercero (`config.json`),
la preferencia ya persistida hubiera pisado el nuevo default — exactamente el error que
el addendum advirtió evitar. **Resultado: PASS.**

## Punto 6 — §7.3.5: avatar sin emoji
`ui/components/avatar.py:24` — `_DEFAULT_TEXT = config_manager.get_agent_name()[:1]
.upper()`, calculada a nivel de módulo. `grep -r "🤖" ui/`: cero resultados. Confirmado
que NO está hardcodeada ("N" fijo): la constante deriva de `get_agent_name()`, verificado
también por `tests/test_avatar.py::test_default_text_es_la_inicial_del_nombre_del_agente`
(leído completo — 5 tests, aserciones reales, no triviales/vacuas). **Resultado: PASS.**

## Punto 7 — suite completa: aritmética del delta
Ver "Tests existentes" arriba — 379 passed/2 failed, delta de +13 tests netos (-1
`test_right_panel_presente_en_el_layout` + 14 nuevos) verificado exactamente contra el
diff real de los archivos de test (`git status --short` confirma `tests/test_avatar.py`,
`tests/test_chat_area.py`, etc. como `??` nuevos junto a los ya existentes de la 1ª
pasada). **Resultado: PASS**, delta explicado por cambios declarados, sin regresión
oculta.

## Punto 8 — regresión dirigida sobre los 43 CA originales (no tocados por el addendum)
Pasada explícita, además de la suite completa, sobre los archivos de las áreas que el
addendum declara "no tocadas" (§7.7 "Qué NO cambia"): sidebar/historial, burbujas/
Markdown, animaciones, `delete_conversation()`, voz.

```
PYTEST_QT_API=pyqt6 python -m pytest tests/test_sidebar.py tests/test_message_bubble.py \
  tests/test_markdown_renderer.py tests/test_animations.py \
  tests/test_conversation_memory.py tests/test_wake_word_gui.py \
  tests/test_input_bar.py tests/test_typing_indicator.py --tb=short -q
→ 101 passed, 0 failed
```

Adicionalmente, `git diff HEAD -- ai/memory_manager.py` confirma que el archivo tiene
**exactamente** las mismas 26 líneas insertadas (`delete_conversation()`) que en la 1ª
pasada — el addendum no lo tocó, coincide con lo declarado en `desarrollo-log-014.md`
("Sin cambios respecto a §4"). CA-35 (contraste WCAG) re-corrido explícitamente
(`test_contrast_helper_matches_known_wcag_values`, `test_palette_contrast_ratios[dark]`,
`test_palette_contrast_ratios[light]`): 3/3 PASS — la paleta no cambió, solo el default.
**Resultado: PASS**, sin regresiones en las áreas no tocadas por el addendum.

## Regresión (addendum §7)
| Área revisada | Resultado |
|---------------|-----------|
| Suite completa (381 tests aplicables) | 379 passed / 2 failed pre-existentes — sin fallos nuevos |
| Sidebar + historial + `delete_conversation()` | 0 fallos (pasada dirigida) |
| Burbujas + Markdown + código resaltado | 0 fallos (pasada dirigida) |
| Animaciones (incl. riesgo #17) | 0 fallos (pasada dirigida) |
| Voz (`test_wake_word_gui.py`) | 0 fallos (pasada dirigida) |
| `ai/memory_manager.py` | Diff idéntico a la 1ª pasada, sin cambios nuevos |
| CA-35 (contraste WCAG) | Re-confirmado, 3/3 tests dedicados PASS |
| `voice/`, `core/`, `intent/`, `skills/`, `agents/`, `channels/` (prohibidos) | Ausentes del diff (confirmado con `git status --short`) |

## Veredicto (addendum §7, 2ª pasada): ✅ PASS

Los 8 puntos de máxima atención señalados en el handoff se verificaron por lectura
directa de código real y ejecución propia de comandos, no por confianza en el reporte de
`orion-dev`: fix de `WA_StyledBackground` presente en `root` y `body` (confirmado también
visualmente abriendo la captura), panel derecho eliminado con `git rm` real (staged
deletion) y sin referencias funcionales rotas, los 7 valores visuales del addendum
coinciden exactamente con el QSS real, sin conflicto de `QGraphicsEffect` (riesgo #17),
tema claro confirmado en los 3 lugares exactos, avatar deriva de `get_agent_name()` sin
emoji hardcodeado, aritmética de la suite (379 passed/2 failed) verificada y explicada, y
una pasada de regresión dirigida (101 tests) sobre las áreas que el addendum declara "no
tocadas" no encontró ninguna regresión oculta. Compilación limpia.

**Siguiente paso:** `orion-qa` re-audita el addendum §7 (seguridad/logging/convenciones
sobre los archivos tocados en esta 2ª pasada), y luego vuelve a Johan para la validación
manual final — misma captura+4 referencias que motivaron el addendum, ahora con la app
visible en un escritorio real (el único punto que `QWidget.grab()` no puede confirmar por
sí solo).

---

# Resultados de prueba REQ-014 — fix bloqueante "no puedo escribir instrucciones" (3ª pasada)

**Agente:** orion-tester
**Fecha:** 2026-08-19
**Punto de partida:** Johan rechazó la 2ª validación manual (addendum §7 ya con QA ✅
COMPLETADO) reportando un bug funcional bloqueante nuevo: "no puedo escribir
instrucciones" en el input bar. `orion-dev` investigó sobre la app real y encontró la
causa raíz — `ui/main_window.py:DEFAULT_WINDOW_SIZE = (1280, 800)` nunca se validaba
contra el área de pantalla realmente disponible; en una pantalla con menos de 800px
lógicos de alto disponibles, la ventana frameless se abre más alta que el área visible e
`InputBar` (pegado al borde inferior) queda fuera del área clickeable. Fix: nuevo método
`MainWindow.fit_size_to_screen()`. Ver `desarrollo-log-014.md`, sección "Fix bloqueante:
input no acepta texto (2026-08-19, 3ª pasada)". Esta sección documenta **solo** la
re-verificación de este fix puntual — no re-toca nada de las secciones anteriores (43 CA
+ addendum §7, ambos con veredicto PASS intacto).

Verificación hecha por lectura directa de código real y ejecución propia de comandos —
nada se dio por bueno solo porque `desarrollo-log-014.md` lo reportaba, y se agregó
evidencia adicional (caso límite nuevo + interactividad real vía `QTest`) más allá de lo
ya cubierto por los tests de `orion-dev`.

## Compilación
- `python -m py_compile ui/main_window.py main.py tests/test_main.py
  tests/test_main_window.py ui/input_bar.py ui/chat_area.py`: **OK**, sin errores.

## Punto 1 — `fit_size_to_screen()` clampea correctamente y `main.py` lo usa antes de `resize()`
- `ui/main_window.py:497-530` — `fit_size_to_screen(self, width, height)` leído completo:
  ```python
  available = self.screen().availableGeometry()
  min_size = self.minimumSize()
  clamped_width = max(min_size.width(), min(width, available.width()))
  clamped_height = max(min_size.height(), min(height, available.height()))
  return clamped_width, clamped_height
  ```
  Clampea contra `screen().availableGeometry()` y nunca baja de `minimumSize()` —
  `MainWindow._init_ui()` línea 223 confirma `self.setMinimumSize(1024, 640)`, sin
  cambios respecto a antes del fix. **Confirmado: PASS.**
- `main.py:190-205` leído completo — `window.resize(*window.fit_size_to_screen(*
  DEFAULT_WINDOW_SIZE))` se ejecuta ANTES de `window.show()`, dentro de la rama
  `if not tray_mode:`. No quedó definido sin usar — el método efectivamente se invoca en
  el único camino real de arranque con ventana visible. `--tray` sin cambios (correcto:
  no llama `resize()`/`show()`, así que el bug geométrico no aplica a ese modo). **PASS.**

## Punto 2 — reproducción realista del escenario reportado (pantalla 1280x672) + caso límite adicional
Script de verificación standalone (`QApplication` real + `unittest.mock.patch` sobre
`screen()`, no solo lectura de código), corrido por este agente:

| Escenario | `fit_size_to_screen(1280, 800)` | Geometría real de `InputBar` tras `resize()` | Resultado |
|---|---|---|---|
| Pantalla 1280x672 disponible (escenario EXACTO reportado por Johan — portátil 1280x720 menos barra de tareas) | `(1280, 672)` | `bottom_right.y()=671` vs `window.height()=672` — dentro del frame | PASS |
| Pantalla 1024x600 (caso límite NUEVO, no cubierto por los 3 tests de `orion-dev`: ancho == `minimumWidth()` exacto, alto por debajo de `minimumHeight()`=640) | `(1024, 640)` — respeta `minimumSize()` tal cual | `bottom_right.y()=639` vs `window.height()=640` — dentro del frame, sin romper el layout | PASS |
| Pantalla 1920x1080 (pantalla grande, caso común) | `(1280, 800)` — sin clamping | No aplica (tamaño default sin cambios) | PASS — no regresión |

La columna "geometría real de `InputBar`" se midió con `ib.mapTo(window,
ib.rect().bottomRight())` sobre el widget REAL dentro de una `MainWindow` real
(`QT_QPA_PLATFORM=offscreen`, sin mockear `InputBar` ni su layout) — confirma que, tras
aplicar el fix, el borde inferior del input bar completo (campo + adjuntar + voz +
enviar) queda dentro del frame de la ventana ya clampeada, no solo que el número
devuelto por `fit_size_to_screen()` es matemáticamente correcto en aislamiento.

Los 3 tests dedicados de `orion-dev` (`tests/test_main_window.py`,
`test_fit_size_to_screen_no_cambia_si_entra_en_pantalla`,
`test_fit_size_to_screen_clampea_cuando_excede_la_pantalla`,
`test_fit_size_to_screen_nunca_baja_del_minimo`) se re-ejecutaron de forma independiente
(ver "Tests existentes" abajo) — los 3 PASS, y cubren exactamente los mismos 3 escenarios
(pantalla grande sin cambio, escenario exacto de Johan 1280x672, piso de
`minimumSize()` con pantalla 800x480). El caso de la tabla de arriba con 1024x600 es una
verificación adicional de este agente sobre un punto límite distinto (ancho exacto al
mínimo, no ambas dimensiones por debajo) — no encontró ninguna desviación.

## Punto 3 — pantalla grande (1920x1080): sin regresión
Cubierto en la tabla del Punto 2 y por `test_fit_size_to_screen_no_cambia_si_entra_en_pantalla`
(pantalla 1920x1080, resultado exacto `(1280, 800)` sin modificar). **PASS**, comportamiento
idéntico al de antes del fix para el caso común.

## Punto 4 — descarte de los 4 sospechosos originales (re-verificado por cuenta propia, no aceptado de plano)
Lectura directa de `ui/input_bar.py`, no solo el resumen del dev-log:

| Sospechoso | Verificación propia | Resultado |
|---|---|---|
| `QGraphicsDropShadowEffect` (§7.3.3) | `ui/input_bar.py:186-189` — `self._input_shadow = QGraphicsDropShadowEffect(self._input)` se aplica sobre `self._input` (`_ComposerTextEdit`, el widget REAL de tipeo), no sobre un contenedor decorativo por encima que pudiera interceptar clicks. Un `QGraphicsEffect` no crea un widget hijo que capture eventos de mouse — solo afecta el render. | Descartado, correcto |
| QSS de `_ComposerTextEdit` | `ui/input_bar.py:107-114` (`keyPressEvent`) — solo intercepta `Qt.Key.Key_Return`/`Key_Enter`; cualquier otra tecla cae en `super().keyPressEvent(event)` sin excepción, no hay ningún filtro de eventos que descarte tipeo normal. Sin `setReadOnly(True)`/`setEnabled(False)` en el QSS ni en `__init__`. | Descartado, correcto |
| `setMaximumWidth`/centrado (§7.2) | `ui/input_bar.py:149` (`setMaximumWidth(_MAX_CONTENT_WIDTH)`, 760px) — es un techo, no fuerza el ancho a 0; `_ComposerTextEdit.sizeHint()` (línea 116-117) devuelve `_max_height()` > 0 independientemente del ancho del contenedor. `AlignHCenter` en `ui/main_window.py:270` centra el widget sin colapsar su tamaño. | Descartado, correcto |
| `set_input_enabled()` inicial | `ui/input_bar.py:292-299` — solo se invoca desde `MainWindow._handle_command()`/`_on_command_done()`/`_on_command_error()` (`ui/main_window.py`), nunca desde `__init__`/`_build_ui()`. `_ComposerTextEdit` hereda el estado `enabled=True` por defecto de `QTextEdit`. | Descartado, correcto |

Ningún factor concurrente encontrado — los 4 quedan descartados por lectura de código
propia, coincidiendo con la investigación de `orion-dev`, no solo por confiar en su
reporte.

## Punto 5 — suite completa + los 3 tests nuevos
- Comando: `PYTEST_QT_API=pyqt6 python -m pytest tests/ --tb=short -q` (corrido por este
  agente).
- Resultado: **382 passed, 2 failed** — coincide EXACTAMENTE con lo reportado por
  `orion-dev`. Los 2 fallos siguen siendo `test_llm_provider.py::test_ca04_ask_anthropic_*`
  (`ModuleNotFoundError: anthropic`), los mismos 2 pre-existentes de `baseline-014.md`.
  Aritmética: 379 (addendum §7, 2ª pasada) + 3 tests nuevos = **382**. Coincide.
- Pasada dirigida adicional (`tests/test_main_window.py tests/test_main.py
  tests/test_input_bar.py tests/test_chat_area.py -v`): **68 passed, 0 failed** —
  incluye los 3 tests nuevos de `fit_size_to_screen()`, más todo `test_main.py` (confirma
  `mock_window.fit_size_to_screen.assert_called_once_with(1280, 800)` seguido de
  `mock_window.resize.assert_called_once_with(1280, 800)` — verifica el orden de llamada
  real, no solo que ambos mocks existan) y toda el área de input/chat sin regresión.
- Los 3 tests nuevos (`test_fit_size_to_screen_no_cambia_si_entra_en_pantalla`,
  `test_fit_size_to_screen_clampea_cuando_excede_la_pantalla`,
  `test_fit_size_to_screen_nunca_baja_del_minimo`) leídos completos
  (`tests/test_main_window.py:212-249`): cubren realmente los 3 casos límite relevantes
  (pantalla grande sin cambio, escenario exacto del bug con pantalla chica, piso de
  `minimumSize()`), con aserciones no triviales (comparación exacta de tupla, no solo
  "no lanza excepción").

## Punto 6 — evidencia adicional de interactividad real (`QTest.mouseClick` + `QTest.keyClicks`)
`pyautogui` resultó poco confiable en este entorno según documentó `orion-dev` (no
reproducido de nuevo por este agente, con buen criterio — coincide con la limitación ya
señalada). Como evidencia más sólida que la del dev, este agente ejecutó `QTest` sobre
la `InputBar` REAL dentro de una `MainWindow` REAL con la geometría de pantalla chica
del escenario de Johan ya aplicada (`fit_size_to_screen(1280,800)` → `(1280,672)` →
`resize()` ya ejecutado antes de la interacción):

1. `window.activateWindow()` + `QTest.qWaitForWindowExposed(window)` — necesario en
   `QT_QPA_PLATFORM=offscreen` para que el foco de ventana se resuelva de forma realista
   (sin esto, `hasFocus()` da un falso negativo aunque el evento se entregue igual —
   detectado y corregido durante esta verificación, documentado por transparencia).
2. `QTest.mouseClick(composer.viewport(), Qt.MouseButton.LeftButton)` sobre el
   `_ComposerTextEdit` real → `composer.hasFocus()` / `composer.viewport().hasFocus()`:
   **True**.
3. `QTest.keyClicks(composer, "hola noddoo, verificacion tester REQ-014")` →
   `composer.toPlainText()` coincide EXACTO con el texto tipeado.
4. `QTest.keyClick(composer, Qt.Key.Key_Return)` → señal `command_submitted` del
   `InputBar` real emite el texto correcto.

**9/9 verificaciones PASS** (3 de geometría/clamping + 3 de la tabla del Punto 2 +
3 de interactividad real). Evidencia consistente con la lectura de código: el fix
resuelve la causa raíz geométrica, y la lógica de tipeo/envío del input (que nunca tuvo
un defecto real, según la propia investigación de `orion-dev`) sigue funcionando
correctamente una vez que el widget queda dentro del área visible/clickeable.

## Regresión (fix bloqueante, 3ª pasada)
| Área revisada | Resultado |
|---------------|-----------|
| Suite completa (384 tests aplicables) | 382 passed / 2 failed pre-existentes — sin fallos nuevos |
| `ui/main_window.py`, `main.py`, `ui/input_bar.py`, `ui/chat_area.py` | Pasada dirigida, 68 passed / 0 failed |
| `ai/memory_manager.py`, `voice/`, `core/`, `intent/`, `skills/`, `agents/`, `channels/` (prohibidos) | Sin cambios en esta pasada (fix acotado a `ui/main_window.py` + `main.py` + tests) |

## Veredicto (fix bloqueante, 3ª pasada): ✅ PASS

Causa raíz geométrica confirmada por lectura de código (no solo aceptada del reporte):
`fit_size_to_screen()` clampea correctamente contra `screen().availableGeometry()` sin
bajar de `minimumSize()`, y `main.py` lo usa efectivamente antes de `resize()`.
Reproducido el escenario exacto reportado por Johan (pantalla 1280x672 disponible) con
medición directa de la geometría real de `InputBar` dentro de una `MainWindow` real —
queda completamente dentro del frame de la ventana clampeada. Agregado un caso límite
nuevo (pantalla 1024x600, ancho exacto al mínimo) no cubierto por los tests de
`orion-dev`, sin encontrar desviaciones. Confirmado sin regresión en pantallas grandes
(1920x1080, comportamiento idéntico al previo). Los 4 sospechosos originales
re-descartados por lectura de código propia. Suite completa 382 passed/2 failed
(aritmética exacta, +3 sobre la pasada anterior), pasada dirigida de 68 tests sin
fallos. Evidencia adicional de interactividad real vía `QTest.mouseClick` +
`QTest.keyClicks` + `QTest.keyClick(Return)` sobre el `InputBar` real con la geometría
de pantalla chica ya aplicada: 9/9 PASS, incluyendo el emisor de `command_submitted` con
el texto correcto.

**Siguiente paso:** `orion-qa` audita este fix puntual (seguridad/logging/convenciones
sobre `ui/main_window.py`/`main.py`/tests), y luego vuelve a Johan para la validación
manual final: que pueda efectivamente escribir y enviar un mensaje en la app real.
