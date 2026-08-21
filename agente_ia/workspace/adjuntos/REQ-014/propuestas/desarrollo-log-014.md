# Desarrollo REQ-014 — Rediseño completo desde cero UI escritorio NODDOO

**Agente:** orion-dev
**Fecha:** 2026-08-18
**Punto de partida:** `arquitectura-014.md` aprobada tal cual por Johan, con los 3 puntos
pendientes confirmados explícitamente (retiro de `voice_orb.py`, `ui/gui.py` como shim,
rama `feature/REQ-014-rediseno-ui-escritorio` ya creada por el humano).

---

## Archivos modificados

### Borrados con `git rm` (contenido trackeado en `eb190b3`, no working tree sucio)
- `ui/widgets/chat_bubble.py`
- `ui/widgets/chat_feed.py`
- `ui/widgets/composer.py`
- `ui/widgets/conversation_list.py`
- `ui/widgets/center_panel.py`
- `ui/widgets/header_bar.py`
- `ui/widgets/sidebar.py`
- `ui/widgets/voice_orb.py`

### Reescritos in-place (mismo path, contenido nuevo)
- `ui/theme.py` — paleta oscura/clara nueva completa, `Palette` agrega `code_bg` y retira
  `orb_colors` (sin consumidores tras el retiro de `voice_orb.py`). Misma API pública
  (`qss_tokens()`, `resolve_theme_name()`, `register_themed()`, `ThemeManager`).
- `ui/gui.py` — reducido a shim de compatibilidad (~30 líneas con docstring):
  `GLOBAL_STATE`, `WAKE_STATE`, `update_gui_state()`, `update_wake_state()`. `JarvisMainWindow`
  y `WakeWordWorker` se retiraron de este módulo (ver "nuevos" abajo). NO se `git rm` —
  `voice/wake_word.py` (prohibido tocar) y `ui/stt/transcriber.py` siguen importando
  `update_gui_state` desde acá (§0.5 de la arquitectura).

### Editados puntualmente
- `ai/memory_manager.py` — única modificación: se agregó `delete_conversation(conversation_id,
  user_id="default") -> bool` como método de `UnifiedMemory` (firma y comportamiento exactos
  de §0.4 de la arquitectura). Ninguna otra función ni el esquema existente se tocó (CA-29).
- `main.py` — líneas ~190-207: el import `from ui.gui import QApplication, JarvisMainWindow`
  se reemplazó por `from PyQt6.QtWidgets import QApplication` + `from ui.main_window import
  DEFAULT_WINDOW_SIZE, MainWindow`; el arranque sin `--tray` pasó de `window.showMaximized()`
  a `window.resize(*DEFAULT_WINDOW_SIZE); window.show()` (riesgo #3 de la arquitectura —
  artefactos visuales conocidos de Qt al maximizar una ventana frameless con
  `WA_TranslucentBackground`). La línea `from ui.gui import update_gui_state` (dentro de
  `main()`, no del bloque `__main__`) **no cambió** — el shim la sigue exponiendo.
- `requirements.txt` — se agregaron `markdown` y `Pygments`.
- `tests/conftest.py` — se agregó `os.environ.setdefault("PYTEST_QT_API", "pyqt6")` junto a
  `QT_QPA_PLATFORM` (mitigación del riesgo de `orion-baseline`: sin esto, `pytest-qt`
  autodetecta el `PySide6` huérfano del entorno y toda la suite da un falso 66 failed/241
  passed).

### Nuevos
- `ui/main_window.py` — `MainWindow(QMainWindow)` (reemplaza `JarvisMainWindow`) + `_TitleBar`
  auxiliar (reemplaza `HeaderBar`, agrega los 3 botones de ventana). Ventana frameless
  (`FramelessWindowHint` + `WA_TranslucentBackground`), resize desde los 4 bordes/esquinas
  vía `startSystemResize()` (método `resize_edge_at()` extraído para ser testeable sin
  simular un click real), arrastre vía `startSystemMove()` desde `_TitleBar`. `changeEvent()`
  quita el `border-radius` al maximizar (riesgo #3). Lee `GLOBAL_STATE`/`WAKE_STATE` con
  `import ui.gui as gui_state` (nunca `from ui.gui import GLOBAL_STATE`).
- `ui/sidebar.py` — `Sidebar` (fusiona nav + historial, arquitectura §0.1) + auxiliares
  `_ConversationHistoryList` y `_ConversationRow` + función privada `_relative_date()`.
  Colapso animado 260↔60px. El borrado de conversación (CA-09) vive acá: `_confirm_delete()`
  (aislado para poder mockearse en tests sin levantar un `QMessageBox` modal real) +
  `run_async(memory.delete_conversation, ...)`.
- `ui/chat_area.py` — `ChatArea(QScrollArea)` (reemplaza `ChatFeed`, absorbe la mitad de
  `CenterPanel`) + `_EmptyState` auxiliar (saludo + subtítulo, SIN `VoiceOrb`, conserva el
  refresco periódico del saludo de REQ-012). Autoscroll "pegado al fondo" reevaluado en cada
  `rangeChanged` (no un flag consumido una sola vez — ver "Decisiones de implementación").
  Carga diferida en lotes de 50 con reinserción al principio preservando la posición de scroll.
- `ui/message_bubble.py` — `MessageBubble(QFrame)`, roles `user`/`assistant`/`system`.
  `assistant` usa `QTextBrowser` + `render_markdown()`; colapso/expansión CA-17 con corte en
  el espacio en blanco más cercano ≤500 caracteres.
- `ui/typing_indicator.py` — `TypingIndicator`, 3 puntos con animación de opacidad desfasada.
- `ui/input_bar.py` — `InputBar` (reemplaza `Composer`) + `_ComposerTextEdit` auxiliar
  (Enter/Shift+Enter, expansión a 5 líneas) + `_risk_color()` privada (CA-40).
- `ui/animations.py` — `animate_message_entrance()`, `animate_width()`,
  `fade_theme_transition()`, `attach_hover_fade()` + `_HoverFadeFilter` auxiliar.
- `ui/workers.py` — `WakeWordWorker`, movido literal desde `ui/gui.py`.
- `ui/components/__init__.py`, `ui/components/avatar.py` (`Avatar`),
  `ui/components/code_block.py` (`pygments_css()`),
  `ui/components/markdown_renderer.py` (`render_markdown()`).

### Sin ningún cambio de código (confirmado con `git status --short`)
`ui/widgets/right_panel.py`, `system_status_card.py`, `quick_actions_card.py`,
`recent_activity_card.py`, `weather_card.py`, `ui/gui_workers.py`, `ui/personality.py`,
`ui/cli.py`, `ui/tts_engine.py`, `ui/stt/transcriber.py`.

### Tests — nuevos
`tests/test_main_window.py`, `test_sidebar.py`, `test_chat_area.py`, `test_message_bubble.py`,
`test_markdown_renderer.py`, `test_code_block.py`, `test_input_bar.py`,
`test_typing_indicator.py`, `test_animations.py`.

### Tests — reescritos/extendidos
- `tests/test_theme.py` — reescrito: pairs de contraste auditados contra el QSS REAL de los
  módulos nuevos (no una lista genérica heredada), `Palette` sin `orb_colors`, sweep de
  `_QSS_TEMPLATE`/`_qss` sobre los módulos nuevos + las dos plantillas de `ui/main_window.py`.
- `tests/test_conversation_memory.py` — extendido (no reescrito) con 6 tests de
  `delete_conversation()` (CA-30): borra todo, filtra por `user_id`, no lanza sobre
  inexistente/ya borrada, no afecta otras conversaciones. El resto de la API queda con los
  tests preexistentes de REQ-013 sin tocar (regresión, CA-29).
- `tests/test_main.py` — actualizado: parchea `sys.modules["ui.main_window"]` y
  `PyQt6.QtWidgets.QApplication` en vez de `sys.modules["ui.gui"]`; el test de arranque sin
  `--tray` verifica `resize(1280, 800)` + `show()` en vez de `showMaximized()`.
- `tests/test_wake_word_gui.py` — actualizado: `WakeWordWorker` desde `ui.workers`,
  `MainWindow` desde `ui.main_window`; `ui.gui` solo como fuente de
  `GLOBAL_STATE`/`WAKE_STATE`. Mismo comportamiento cubierto (CA-03, CA-05, CA-08, CA-09,
  CA-10, doble clic).

### Tests — retirados (`git rm`, arquitectura de archivos nueva los invalida)
`tests/test_gui_widgets.py`, `tests/test_chat_widgets.py` — divididos entre
`test_main_window.py`, `test_sidebar.py`, `test_chat_area.py`, `test_message_bubble.py`,
`test_input_bar.py`.

### Sin cambios
`tests/test_config_manager_ui_theme.py` — `config_manager.get_ui_theme`/`set_ui_theme` no se
tocaron en este REQ (confirmado en §6 de la arquitectura).

## Dependencias agregadas
- `requirements.txt` — `markdown` (sin pin de versión, igual que el resto del archivo),
  `Pygments` (ya estaba instalado en el entorno vía otra dependencia transitiva; agregado
  igual como dependencia directa explícita porque el código la importa directamente).

## Decisiones de implementación

1. **Autoscroll "pegado al fondo" reevaluado en cada `rangeChanged`, no un flag consumido una
   sola vez.** El diseño inicial (portado literal del patrón `_autoscroll_pending` de
   `ChatFeed` de REQ-013) causaba que el scroll se quedara a mitad de camino al agregar
   ráfagas de mensajes de IA: `MessageBubble` usa `QTextBrowser` para `role="assistant"`, cuyo
   layout de texto enriquecido se asienta en varias vueltas del loop de eventos (a diferencia
   del `QLabel` estático de `ChatBubble` en REQ-013). Un flag que se consume en el primer
   `rangeChanged` capturaba un `maximum()` todavía parcial. Se cambió a un estado persistente
   `_stick_to_bottom` (ver `ui/chat_area.py`) que se reevalúa en cada disparo de
   `rangeChanged`/`valueChanged` mientras el usuario no suba manualmente — comportamiento
   equivalente al pedido por CA-15, pero robusto al layout asíncrono de `QTextBrowser`.
   Verificado con `tests/test_chat_area.py` (incluye un helper `_wait_layout_settled()` para
   no depender de que `maximum() > 0` sea señal suficiente de "ya terminó de crecer").

2. **`fade_theme_transition()` no limpia el `QGraphicsEffect` al terminar la animación.**
   La primera versión conectaba `anim.finished` a un `lambda: widget.setGraphicsEffect(None)`.
   Un lambda de Python que captura un widget no queda atado al ciclo de vida de ese `QObject`
   en el tracking de conexiones de PyQt6 (a diferencia de un slot que es un bound method) —
   si la animación seguía "viva" cuando la ventana se cerraba entre tests, el lambda intentaba
   tocar un widget ya destruido en el lado C++ y producía un `access violation` real
   (reproducido corriendo `tests/test_main_window.py`, no solo una hipótesis teórica). Se
   quitó la limpieza: dejar el efecto en opacidad 1.0 al terminar es visualmente idéntico a no
   tener ningún efecto, así que no hacía falta. Documentado en el docstring de
   `fade_theme_transition()`.

3. **Tres hex de la paleta ajustados respecto a los "dados" por el humano en el contexto**,
   siguiendo el mismo patrón de REQ-013 (2 hex ajustados ahí). Motivo común: `bg_elevated` en
   REQ-014 se reutiliza como fondo de la burbuja del asistente (`bubble_ai_bg`) — un gris medio
   (`#2d2d2d` oscuro / `#e8eaed` claro), no el casi-negro/casi-blanco que tenía REQ-013 — lo
   que bajaba el contraste real de algunos tokens por debajo de 4.5:1 contra ESE fondo
   concreto, usado en producción por `ui/widgets/system_status_card.py:SystemStatusRow` y los
   chips del input bar:
   - `text_secondary` (oscuro): `#8b949e` → `#909aa8` (4.48:1 → 4.84:1 contra `bg_elevated`).
   - `danger` (oscuro): `#f85149` → `#ff6b64` (4.11:1 → 4.94:1 contra `bg_elevated`).
   - `success`/`warning`/`danger` (claro): `#2da44e`/`#bf8700`/`#cf222e` →
     `#166b2e`/`#7d5300`/`#b3121c` (2.67/2.61/4.44:1 → 5.49/5.60/5.77:1 contra `bg_elevated`).
   Además se ajustaron 2 combinaciones de QSS que hubieran quedado con `accent` (sin cambiar
   su hex) sobre `bg_elevated`/`bg_hover` en modo claro (4.31:1, por debajo de AA):
   `#BubbleMoreButton` pasó de usar `$accent` a usar `$bubble_ai_fg`/`$bubble_user_fg` según el
   rol (subrayado en vez de color de acento); `#ThemeToggle:hover` pasó de `$accent` a
   `$text_primary`. El test de contraste automatizado de `tests/test_theme.py`
   (`test_palette_contrast_ratios`, CA-35) audita 42 pares × 2 temas = 84 combinaciones reales
   del layout, todas ≥4.5:1.
4. **`ui/sidebar.py` posee memoria directamente (desviación documentada de REQ-013).**
   `_on_delete_requested()` importa `ai.memory_manager.memory` y llama
   `run_async(memory.delete_conversation, ...)` — a diferencia de `ConversationList` en
   REQ-013, que era presentación pura. Autorizado explícitamente por §0.4 de la arquitectura;
   `_confirm_delete()` se aisló en su propio método para que los tests puedan reemplazarlo sin
   levantar un `QMessageBox.exec()` modal real (bloquearía la suite).
5. **`InputBar._on_attach_clicked()` abre un `QFileDialog`, no solo acepta drag&drop.** La
   arquitectura solo detalla el mecanismo de drag&drop (CA-22) y menciona "3 botones" sin
   precisar el comportamiento del botón de adjuntar (CA-21). Se conectó a un selector de
   archivo nativo con el mismo allowlist de extensiones y el mismo camino de validación
   (`_handle_attachment()`) que el drop — un botón "adjuntar" sin ninguna acción al hacer clic
   hubiera sido una regresión de usabilidad no pedida por nadie. El contenido del archivo
   sigue sin leerse en ningún camino (riesgo #12 de la arquitectura).
6. **`_risk_color()` (CA-40) trata una acción sin clasificar como `danger` (fail-closed)**,
   nunca verde por defecto — consistente con el resto del sistema (`security_manager.
   require_confirmation()` también fail-closed ante una acción no registrada).

## Verificación local
```
python -m py_compile main.py ai/memory_manager.py ui/*.py ui/components/*.py ui/widgets/*.py tests/*.py
→ sin errores (excluyendo tests/_tmp_manual_verify_012b.py, script de scratch preexistente
  y ya roto antes de este REQ, no es un archivo `test_*.py` recolectado por pytest)

PYTEST_QT_API=pyqt6 python -m pytest tests/ --tb=short -q
→ 366 passed, 2 failed (test_llm_provider.py — ModuleNotFoundError: anthropic)
```
Los 2 fallos son EXACTAMENTE los documentados como pre-existentes en `baseline-014.md`
(paquete `anthropic` no instalado en este entorno, no atribuible a REQ-014). Cero fallos
nuevos. El conteo de 305 passed del baseline no aplica directo como comparación porque este
REQ agrega ~85 tests nuevos y retira 2 archivos completos de tests obsoletos — la comparación
válida es "0 regresiones", no el número absoluto.

## CA-35 — verificación de contraste WCAG
Corrida sobre el set completo (42 pares × 2 temas = 84 combinaciones), incluidos los tokens
dados directamente por el humano (no solo los derivados por `orion-architect`). 3 ajustes de
hex documentados arriba en "Decisiones de implementación". Test:
`tests/test_theme.py::test_palette_contrast_ratios`.

---

# Desarrollo REQ-014 — addendum §7 (2ª pasada)

**Agente:** orion-dev
**Fecha:** 2026-08-19
**Punto de partida:** Johan rechazó la validación manual de la 1ª pasada (43/43 CA, QA
✅ COMPLETADO) mostrando una captura real con bleed-through/texto superpuesto en el panel
derecho + 4 referencias (WorkBuddy AI, DeepSeek, ChatGPT, Claude). `orion-architect`
redactó el addendum §7 de `arquitectura-014.md` (líneas 498-825), aprobado por Johan tal
cual, con 2 puntos de confirmación explícita: `git rm` de las 5 tarjetas/panel (no
huérfanas) y tema claro como nuevo default. Esta sección documenta SOLO lo nuevo de esta
2ª pasada — no reescribe nada de la sección de arriba (43 CA de la 1ª pasada, ya
implementados y sin re-tocar salvo lo que el addendum señala explícitamente).

## Archivos modificados (addendum §7)

### Borrados con `git rm` (§7.2, confirmado explícitamente por Johan — no huérfanos)
- `ui/widgets/right_panel.py`
- `ui/widgets/system_status_card.py`
- `ui/widgets/quick_actions_card.py`
- `ui/widgets/recent_activity_card.py`
- `ui/widgets/weather_card.py`

### Editados puntualmente
- `ui/main_window.py` — §7.1: `root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,
  True)` justo después de crear `root` (`WindowRoot`), mismo `setAttribute` en `body`
  (`WindowBody`). §7.2: se quitó el import de `RightPanel`, su instanciación y el
  `addWidget` en `body_layout`; `input_bar` se agrega a `center_column` con
  `Qt.AlignmentFlag.AlignHCenter` (necesario porque `input_bar` ahora tiene
  `maximumWidth` fijo — sin la alineación un `QVBoxLayout` lo deja pegado a la
  izquierda). §7.3.1: `_TITLEBAR_QSS_TEMPLATE` — `#ThemeToggle`/`#WakeIndicator` de
  32×32px con fondo+borde a 28×28px transparentes con `$bg_hover` solo en `:hover`;
  `#ModePill` padding 6/16→4/12, font-size 12→11px. §7.3.6: márgenes de `_TitleBar`
  (16,8,12,8)→(20,10,16,10). Verificado (§7.3.1): los 5 ítems deshabilitados del riel de
  `Sidebar` ya usaban `text_disabled` — no hizo falta corrección.
- `ui/chat_area.py` — §7.2: nueva constante `_MAX_CONTENT_WIDTH = 760`;
  `ChatArea.__init__` agrega `setAlignment(Qt.AlignmentFlag.AlignHCenter)` +
  `self._content.setMaximumWidth(_MAX_CONTENT_WIDTH)`. §7.3.2: `#GreetingLabel`
  28px/300→40px/700, `#GreetingSubtitle` 14→15px. §7.3.6: márgenes de `_layout`
  (16,16,16,16)→(32,32,32,32).
- `ui/input_bar.py` — §7.2: misma constante `_MAX_CONTENT_WIDTH = 760`,
  `InputBar.setMaximumWidth(_MAX_CONTENT_WIDTH)` en `__init__`. §7.3.3: `#ComposerTextEdit`
  padding 8/14→16/22, radio 18→26px; `#AttachButton`/`#WakeToggleButton` pierden
  fondo/borde propios (transparentes, 44→36px, `$bg_hover` circular solo en hover);
  `#SendButton` se mantiene como único control lleno (`$accent`/`$on_accent`, 44px, sin
  borde) — quedó con su propio bloque QSS en vez de compartido con Attach/Wake.
  `QGraphicsDropShadowEffect` (`blurRadius=24, offset=(0,4)`) agregado sobre
  `_ComposerTextEdit` (ver "Decisiones de implementación" #1), color ajustado por tema en
  `apply_theme()`. §7.3.6: márgenes de `outer` (24,8,24,16)→(24,12,24,24). §7.3.7:
  `#ComposerChip` fondo `$bg_elevated`→transparente, borde `$border`→`$border_subtle`,
  padding 5/12→4/10.
- `ui/theme.py` — §7.3.4: `DEFAULT_THEME = "dark"` → `"light"`.
- `config_manager.py` — §7.3.4: `DEFAULT_CONFIG["ui_theme"]` `"dark"` → `"light"` (única
  línea tocada; `get_ui_theme()`/`set_ui_theme()` sin cambios).
- `config.json` — §7.3.4: `"ui_theme": "dark"` → `"light"` (los 3 puntos de §7.3.4
  tocados, confirmado por Johan — sin los 3 no era visible en la práctica).
- `ui/components/avatar.py` — §7.3.5: `_DEFAULT_TEXT = "🤖"` →
  `config_manager.get_agent_name()[:1].upper()` (resuelve a `"N"` con la config real del
  repo), calculada una vez a nivel de módulo.

### Tests actualizados (`ui.widgets.right_panel`/tarjetas ya no existen)
- `tests/test_main_window.py` — quitado `test_right_panel_presente_en_el_layout` y la
  entrada `"right_panel"` de `test_toggle_tema_cambia_stylesheet_de_los_bloques_principales`;
  simplificado `no_external_io` (ya no mockea `weather_card_module`/
  `recent_activity_module`, solo `memory_module.memory.list_conversations`); quitados los
  imports de `RightPanel`/`recent_activity_card`/`weather_card`. Agregados: verificación
  de `WA_StyledBackground` sobre `root`/`body` (§7.1), ausencia de `right_panel` (§7.2),
  anchos máximos de 760px + `AlignHCenter` de `chat_area`/`input_bar` (§7.2).
- `tests/test_theme.py` — quitado `ui.widgets.right_panel` (y las 4 tarjetas) del sweep de
  `test_qss_templates_sustituyen_sin_keyerror`. Reescritos los 3 tests de `ThemeManager`
  que asumían `DEFAULT_THEME == "dark"` (`test_theme_manager_toggle_alterna_y_emite`,
  `test_theme_manager_set_theme_mismo_valor_no_emite`,
  `test_register_themed_aplica_y_suscribe`) para el nuevo default `"light"`. Agregados:
  contenido QSS de `#GreetingLabel`/`#GreetingSubtitle` (§7.3.2), `#ComposerTextEdit`
  como píldora (§7.3.3), `#ComposerChip` de menor peso (§7.3.7).
- `tests/test_wake_word_gui.py` — mismo ajuste de `no_external_io` que
  `test_main_window.py` (quitados los imports/mocks de `recent_activity_card`/
  `weather_card`, que ya no aplican tras la eliminación del panel derecho).
- `tests/test_config_manager_ui_theme.py` — 3 tests que esperaban `"dark"` como default
  (`test_get_ui_theme_default_dark_sin_archivo`/`_sin_clave`,
  `test_load_config_completa_ui_theme_en_config_antiguo`) actualizados a `"light"`
  (§7.3.4); los 2 primeros renombrados a `..._default_light_...`.
- `tests/test_input_bar.py` — agregados: `InputBar.maximumWidth() == 760` (§7.2),
  presencia/identidad del único `QGraphicsDropShadowEffect` sobre `_ComposerTextEdit` sin
  pisar otro efecto (§7.3.3, riesgo #17), color de la sombra por tema (alpha 60 claro/130
  oscuro).
- `tests/test_avatar.py` (nuevo) — `_DEFAULT_TEXT` coincide con
  `config_manager.get_agent_name()[:1].upper()`, no contiene el emoji retirado,
  `Avatar()`/`set_text()`/texto explícito (§7.3.5, §7.6 de la arquitectura).

## Dependencias agregadas
Ninguna — `QGraphicsDropShadowEffect`/`Qt.WidgetAttribute.WA_StyledBackground` son API de
PyQt6 ya presente en `requirements.txt`.

## Decisiones de implementación (addendum §7)

1. **`QGraphicsDropShadowEffect` (§7.3.3) se aplicó sobre `_ComposerTextEdit`, no sobre
   `command_row`.** El addendum dice "sobre el widget `command_row`/`_ComposerTextEdit`",
   pero `command_row` es un `QHBoxLayout` (`ui/input_bar.py:_build_ui()`), no un
   `QWidget` — Qt solo admite `QGraphicsEffect` sobre widgets, no sobre layouts. Se aplicó
   sobre `_ComposerTextEdit`, el widget real de la píldora, que es la interpretación
   consistente con el resto de §7.3.3 ("sombra suave... sobre el input"). Verificado antes
   de aplicarlo (riesgo #17 de la arquitectura): `_ComposerTextEdit` no recibía
   `attach_hover_fade()` en ningún punto del código — confirmado con grep dirigido, cero
   coincidencias fuera de `ui/animations.py`/`tests/test_animations.py`.
2. **`ChatArea.resizeEvent()` también se actualizó al mismo cálculo de ancho que
   `_mount_bubble()`, aunque el addendum solo detalla el ajuste en `_mount_bubble()`.**
   Extraído a un método común `_bubble_available_width()`. Motivo: `resizeEvent()` pasaba
   el ancho completo del viewport (no acotado a `_MAX_CONTENT_WIDTH`) a
   `bubble.set_available_width()` en cada resize de ventana — sin este ajuste, las
   burbujas ya montadas hubieran vuelto a envolver texto al ancho de la ventana completa
   apenas el usuario redimensionara, reintroduciendo visualmente el mismo problema que
   `_mount_bubble()` corrige al montar. Mismo cálculo, un solo lugar, cero duplicación de
   lógica (`min(width, _MAX_CONTENT_WIDTH) - 32`).
3. **`#SendButton:hover` se retiró en vez de reusar `$bg_hover`.** El botón de enviar pasó
   de fondo `$bg_input` (neutro) a `$accent` (lleno, §7.3.3 — "único control lleno"); un
   `:hover` con `$bg_hover` encima de un fondo `$accent` se vería como un parche gris
   opaco sobre el color de marca (no hay token `accent` oscurecido/aclarado en la
   paleta). Se dejó sin regla de `:hover` propia — el addendum no especificó un
   comportamiento de hover concreto para el botón lleno, y no se agregó ningún token
   nuevo a `Palette` sin volver a arquitectura.
4. **Verificación manual del bug de composición (§7.1, riesgo #16) hecha con
   `QWidget.grab()` sobre `MainWindow` real (plataforma Windows, sin
   `QT_QPA_PLATFORM=offscreen`), no con una captura de pantalla del sistema operativo.**
   Un primer intento con una captura de pantalla real (`PIL.ImageGrab.grab()`) capturó
   por accidente el escritorio real del usuario en ese momento — una videollamada en
   curso con contenido de trabajo ajeno a este REQ — en vez de (o además de) la ventana
   de la app. Ese archivo se borró de inmediato sin distribuirlo. Se repitió la
   verificación con `window.grab()`, que renderiza SOLO el árbol de widgets de
   `MainWindow` a través del pipeline de pintado de Qt (respeta QSS/`WA_StyledBackground`
   igual que un render real) sin tocar la pantalla del sistema en ningún momento. La
   imagen resultante (`pruebas/screenshot-addendum7-widget-grab.png`) confirma: fondo
   sólido sin zonas sin pintar ni texto superpuesto, panel derecho ausente, tema claro por
   defecto, tipografía del saludo 40px/700, input como píldora con botones quietos e ícono
   de envío lleno, chips de menor peso visual. Esta captura no reproduce el mecanismo
   exacto de composición del compositor de Windows (alpha blending contra el escritorio
   real) que causaba el bleed-through original — eso solo es observable con una app
   visible en un escritorio real — pero sí confirma la causa raíz específica señalada por
   la arquitectura: `WindowRoot` ahora pinta su `background-color`/`border`/`border-radius`
   de verdad (`testAttribute(WA_StyledBackground) is True`, verificado programáticamente
   en el mismo script), cerrando exactamente el defecto diagnosticado en §7.1.

## Verificación local (addendum §7)
```
python -m py_compile ui/main_window.py ui/chat_area.py ui/input_bar.py ui/theme.py \
  ui/components/avatar.py config_manager.py tests/test_main_window.py tests/test_theme.py \
  tests/test_wake_word_gui.py tests/test_config_manager_ui_theme.py tests/test_avatar.py \
  tests/test_input_bar.py
→ sin errores

PYTEST_QT_API=pyqt6 python -m pytest tests/ --tb=short -q
→ 379 passed, 2 failed (test_llm_provider.py — ModuleNotFoundError: anthropic, mismos 2
  pre-existentes de baseline-014.md)
```
Aritmética exacta respecto a la 1ª pasada (366 passed): -1 test retirado
(`test_right_panel_presente_en_el_layout`) + 14 tests nuevos (5 en `test_avatar.py`, 3 en
`test_main_window.py`, 3 en `test_input_bar.py`, 3 en `test_theme.py`) = 366 - 1 + 14 =
379. Cero regresiones nuevas.

**Verificación visual manual (§7.1, obligatoria — no reemplazable por la suite headless):**
`MainWindow` corrida con la plataforma Qt real de Windows (no `offscreen`) vía
`window.grab()`. Confirmado programáticamente en la misma corrida:
`root.testAttribute(Qt.WidgetAttribute.WA_StyledBackground) is True`,
`hasattr(window, "right_panel") is False`, `theme_manager.current_name() == "light"`,
`chat_area._content.maximumWidth() == input_bar.maximumWidth() == 760`. Captura guardada en
`pruebas/screenshot-addendum7-widget-grab.png` (ver "Decisiones de implementación" #4 para
el porqué de `window.grab()` en vez de una captura de pantalla del sistema operativo).

## Fix bloqueante: input no acepta texto (2026-08-19, 3ª pasada)

Johan hizo la 2ª prueba manual (addendum §7 ya con veredicto ✅ QA) y reportó un bug
funcional bloqueante, sin más detalle que la frase: **"no puedo escribir instrucciones"**
— el campo de texto del input bar no acepta escritura. No se recibió más detalle previo
(no se sabía si el cursor no aparecía al click, si escribía sin verse el texto, o si el
campo no reaccionaba en absoluto), así que la investigación arrancó reproduciendo
directamente sobre la app real en vez de esperar más detalle de Johan.

### Investigación (descartes documentados, no solo el hallazgo final)

1. **Revisión estática de `ui/input_bar.py`/`_ComposerTextEdit`** (los 4 sospechosos
   señalados en el handoff, en orden): `QGraphicsDropShadowEffect` aplicado
   correctamente sobre `_ComposerTextEdit` (el widget real, no un contenedor decorativo
   encima); `keyPressEvent` de Enter/Shift+Enter intacto, no absorbe texto normal;
   `setMaximumWidth(760)` + `AlignHCenter` no colapsan el widget (`sizeHint()` > 0);
   `set_input_enabled()` nunca se llama con `False` en el arranque (`GLOBAL_STATE` de
   `ui/gui.py` arranca en `"IDLE"`, `_poll_state()` no lo toca). Sin hallazgos.
2. **Simulación con `QTest`** (inyección de eventos directo en la cola de Qt, sobre la
   `MainWindow` real, plataforma Windows real — no `offscreen`): click en
   `_input.viewport()` → foco correcto; `QTest.keyClicks()` → texto aceptado
   correctamente; `Qt.Key.Key_Return` → `command_submitted` emite el texto correcto. La
   lógica del widget en sí **no tiene ningún defecto** — confirmado también por
   `QApplication.widgetAt()` sobre la jerarquía real: el punto donde debería estar el
   input resuelve limpiamente a `qt_scrollarea_viewport` → `_ComposerTextEdit` →
   `InputBar`, sin ningún widget decorativo superpuesto tapando el click (descarta
   definitivamente el sospechoso #1 del handoff).
3. **Clicks reales a nivel de sistema operativo (`pyautogui`, no `QTest`)** sobre la
   `MainWindow` real mostrada en pantalla: en varias corridas, el foco terminaba en
   widgets ajenos al input (`ThemeToggle` de la barra de título, botones vecinos) en vez
   de en `_ComposerTextEdit`, de forma inconsistente entre corridas. Se investigó a
   fondo (DPI awareness del proceso, `devicePixelRatio`, orden de import de
   `pyautogui`/Qt) sin encontrar una causa de coordenadas consistente — una prueba de
   control con una ventana Qt trivial (un solo `QLineEdit`, sin nada del código de la
   app) mostró que el click SÍ enfocaba el campo pero el tipeo posterior con
   `pyautogui.typewrite()` tampoco llegaba a registrarse. Conclusión: la inyección de
   input real a nivel de sistema operativo (`pyautogui`) **no es confiable en este
   entorno de ejecución** (probablemente una sesión sin foco de escritorio interactivo
   real) — no se usó como evidencia del bug ni de su fix, para no reportar una causa
   raíz falsa. Documentado por transparencia, no como hallazgo del bug.
4. **Medición directa de geometría (Win32 + Qt, sin `pyautogui`, 100% determinística)**:
   se midió `screen().availableGeometry()` vs. la geometría real de `InputBar` en la
   `MainWindow` real. Hallazgo confirmado, reproducido 100% de las veces: en una
   pantalla de 1280x720 lógico (1920x1080 físico, escalado de Windows 150% — resolución
   efectiva muy común en portátiles, incluso a mayor resolución física, con el
   escalado activado), el área disponible es de solo 1280x672 lógico (menos la barra de
   tareas). `DEFAULT_WINDOW_SIZE = (1280, 800)` (`ui/main_window.py`) es un tamaño FIJO
   que nunca se validó contra la pantalla real — la ventana se abre 128px lógicos más
   alta que el área visible. Como la ventana es **frameless**
   (`Qt.WindowType.FramelessWindowHint`, sin la barra de título nativa que Windows
   usaría para reposicionar/ajustar una ventana que no entra en pantalla) y `InputBar`
   es el último widget de `center_column` (pegado al borde inferior), su borde inferior
   (`Y=799` lógico) queda 128px por debajo del área disponible (`Y=671` lógico) —
   **el input bar completo (campo de texto + adjuntar + voz + enviar) se renderiza
   detrás de la barra de tareas / fuera de la pantalla, inalcanzable con el mouse.**
   Esto explica exactamente el síntoma reportado ("no puedo escribir") sin contradecir
   que Johan sí veía la mejora visual (chat area, sidebar, barra de título — todo lo que
   entra en los 672px superiores — se ve normal; solo la franja inferior es
   inalcanzable). También explica por qué no se detectó en la 1ª validación de esta
   pasada: Johan la rechazó al ver el bug de bleed-through/panel derecho (mucho más
   obvio a simple vista) antes de llegar a intentar escribir.

### Causa raíz

`ui/main_window.py:DEFAULT_WINDOW_SIZE = (1280, 800)` es un tamaño de apertura fijo que
nunca se valida contra el área de pantalla realmente disponible. En cualquier pantalla
con menos de 800px lógicos de alto disponibles (portátiles 1280x720/1366x768, o
cualquier pantalla con escalado de Windows que reduzca la resolución lógica efectiva por
debajo de ese umbral — una combinación nada rara), la ventana frameless se abre más alta
que el área visible, y `InputBar` (el último widget de la columna central, pegado al
borde inferior) queda parcial o totalmente fuera del área clickeable — sin foco posible,
sin poder escribir. No es un bug de foco/teclado ni del widget del input; es puramente
geométrico.

### Fix implementado

- **`ui/main_window.py`** — nuevo método `MainWindow.fit_size_to_screen(width, height) ->
  tuple[int, int]`: clampea el tamaño solicitado contra `self.screen().availableGeometry()`,
  sin bajar nunca de `minimumSize()` (1024x640, ya vigente, sin cambios). Docstring con
  el detalle completo de la causa raíz y de la investigación (para que un REQ futuro no
  la repita). `DEFAULT_WINDOW_SIZE` se documenta ahora como tamaño *deseado*, no
  garantizado.
- **`main.py`** (líneas ~196-201) — `window.resize(*DEFAULT_WINDOW_SIZE)` →
  `window.resize(*window.fit_size_to_screen(*DEFAULT_WINDOW_SIZE))`. Único cambio de
  comportamiento: el tamaño de apertura ahora respeta la pantalla real. `--tray` sin
  cambios (sigue sin llamar `resize()`/`show()`).

### Verificación

- Geometría verificada en la app real (Windows, plataforma real, no `offscreen`):
  `fit_size_to_screen(1280, 800)` devuelve `(1280, 672)` en una pantalla de
  1280x720 lógico con barra de tareas — el borde inferior de `InputBar` queda
  exactamente dentro del área disponible (`Y=671` vs. límite `671`), en vez de 128px
  por fuera.
- `QTest` (click + tipeo + Enter sobre la `MainWindow` real con el fix aplicado):
  mismo resultado limpio que el punto 2 de la investigación — foco, tipeo y
  `command_submitted` funcionan correctamente. La lógica del widget nunca fue el
  problema; el fix resuelve el único defecto real encontrado (geometría de apertura).
- `python -m py_compile ui/main_window.py main.py tests/test_main.py
  tests/test_main_window.py`: OK.
- 3 tests nuevos en `tests/test_main_window.py`
  (`test_fit_size_to_screen_no_cambia_si_entra_en_pantalla`,
  `test_fit_size_to_screen_clampea_cuando_excede_la_pantalla` — reproduce el escenario
  exacto del bug, 1280x800 vs. pantalla 1280x672 disponible —,
  `test_fit_size_to_screen_nunca_baja_del_minimo`). `tests/test_main.py` actualizado
  (`mock_window.fit_size_to_screen.return_value`) para la nueva llamada intermedia.
- Suite completa: `PYTEST_QT_API=pyqt6 python -m pytest tests/` → **382 passed, 2
  failed** (mismos 2 pre-existentes de `anthropic`, ver `baseline-014.md`). Aritmética
  exacta respecto a la pasada anterior (379 passed): +3 tests nuevos = 382. Cero
  regresiones nuevas.

### Pendiente — no resuelto por este agente

La inyección de input real a nivel de sistema operativo (`pyautogui`) no funcionó de
forma confiable en este entorno de ejecución (punto 3 de la investigación), así que
**no se pudo confirmar con un click+tipeo real de mouse/teclado físico** que el bug esté
100% resuelto — solo con medición de geometría (determinística) y `QTest` (simulación
de eventos Qt, no del sistema operativo). Se recomienda que la validación manual de
Johan sobre la app real sea la confirmación final, como ya es el proceso estándar de
este REQ. **Si el bug persistiera tras este fix**, el dato más útil que puede aportar
Johan es la resolución de pantalla y el porcentaje de escalado de Windows que está
usando (Configuración → Sistema → Pantalla) — permitiría reproducir con el mismo
`fit_size_to_screen()` exacto y descartar (o confirmar) una causa distinta.
