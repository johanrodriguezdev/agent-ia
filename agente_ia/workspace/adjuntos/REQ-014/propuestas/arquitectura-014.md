# Arquitectura REQ-014 — Rediseño completo desde cero UI escritorio NODDOO

**Agente:** orion-architect
**Fecha:** 2026-08-18
**Punto de partida verificado:** HEAD `eb190b3`, working tree limpio (`git status --short` solo
muestra `requerimientos.csv` del tracker y la carpeta nueva `workspace/adjuntos/REQ-014/`;
`stash@{0}` presente, no aplicado). Confirmado independientemente en este paso, coincide con
`baseline-014.md`.

---

## 0. Resolución explícita de los 4 puntos señalados por `orion-baseline`

### 0.1 — `ui/widgets/sidebar.py` (nav lateral) vs. nuevo `ui/sidebar.py` (historial colapsable)

**Decisión: FUSIÓN. El nuevo `ui/sidebar.py` (top-level, no en `ui/widgets/`) absorbe por completo
al `Sidebar` actual — no son dos componentes distintos, es un único widget.**

Motivo: `ui/widgets/sidebar.py` de hoy ya combina nav (7 ítems, 5 deshabilitados) +
`ConversationList` embebida — es conceptualmente el mismo widget que pide SPEC-014, solo que
sin colapsar y sin borrado. Mantener dos sidebars sería una regresión de UX (¿cuál nav queda?) y
SPEC-014 confirma explícitamente que los 5 ítems deshabilitados siguen sin activarse ("No
incluye": no se activan Memoria/Tareas/Archivos/Aplicaciones/Configuración). El nuevo
`ui/sidebar.py`:
- Es la ÚNICA barra lateral. `ui/widgets/sidebar.py` y `ui/widgets/conversation_list.py` se
  `git rm`.
- Contiene un riel de navegación compacto (7 iconos; solo "Inicio" y "Conversaciones"
  habilitados, idéntico set/semántica al actual) que colapsa a solo-ícono en 60px y muestra
  ícono+etiqueta en 260px — el colapso de la sidebar completa (CA-05) anima también el riel, sin
  lógica nueva.
- Contiene el listado de conversaciones con historial funcional + borrado (CA-06 a CA-10),
  reemplazando `ConversationList` con una clase auxiliar `_ConversationHistoryList` definida en
  el MISMO archivo (permitido por `.claude/rules/python-style.md`: "clases auxiliares pequeñas
  permitidas en el mismo archivo").
- Contiene el footer de configuración/perfil como placeholder deshabilitado (ver §0.4).

### 0.2 — `ui/widgets/voice_orb.py`

**Decisión: SE RETIRA. No se conserva, ni siquiera en el estado vacío.**

Motivo: (a) No aparece en ningún criterio de aceptación de SPEC-014 ni en el prompt detallado del
humano (confirmado por SPEC: "no mencionado"). (b) Es un remanente visual del HUD "JARVIS"
original (REQ-008); un orbe animado circular no aparece en ninguna referencia de "nivel
ChatGPT/Claude/DeepSeek/WorkBuddy" — el objetivo explícito de este REQ. (c) La única función que
cumplía (indicar estado de voz) se cubre mejor con el botón de voz del `InputBar` (CA-21/CA-24),
que ya refleja el estado del modo manos libres sin necesitar un widget de 220px con `QTimer` de
33ms por instancia. (d) Retirarlo reduce superficie de prueba sin perder ningún CA.
`ui/widgets/voice_orb.py` se `git rm`. El estado vacío del área de chat (`ChatArea`) pasa a ser un
saludo centrado (texto + subtítulo, portado de `CenterPanel._build_empty_state()`) sin
visualización animada. **Esta decisión queda marcada para confirmación explícita del humano en el
mensaje de aprobación** (no es un ajuste menor — cambia una pieza visual visible).

### 0.3 — Reemplazo de contenido ya committeado (`git rm` explícito)

Ver tabla completa en §4 "Archivos a modificar/crear". Resumen: **8 archivos se borran con
`git rm`** (contenido de `eb190b3`, no working tree sucio), **2 se reescriben in-place** con
contenido nuevo bajo el mismo nombre (`ui/theme.py`, `ui/gui.py` — este último reducido a un
shim, ver §0.5), **1 se edita puntualmente** (`ai/memory_manager.py`, solo agrega
`delete_conversation()`), **5 se mantienen sin tocar** (`right_panel.py` + 4 tarjetas), y se crean
**12 archivos nuevos**.

### 0.4 — `delete_conversation()`

Firma definitiva, agregada a la clase `UnifiedMemory` de `ai/memory_manager.py`:

```python
def delete_conversation(self, conversation_id: str, user_id: str = "default") -> bool:
    """Borra todas las filas de una conversación (REQ-014/CA-30).

    DELETE real (no soft-delete, confirmado por el humano). Restringido por `user_id`
    en el WHERE — nunca borra conversaciones de otro usuario aunque `conversation_id`
    coincida (imposible de adivinar por ser uuid4, pero el filtro es defensivo).
    No lanza si la conversación no existe o ya fue borrada (caso borde de SPEC-014):
    retorna False sin efecto, en vez de una excepción no controlada.
    """
    if not conversation_id:
        return False
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute(
                "DELETE FROM memories WHERE conversation_id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
            deleted = cur.rowcount
        if deleted:
            self._load_embeddings()  # mismo patrón que consolidate()/clear_user_memory()
            logger.info(f"Conversación eliminada: {conversation_id} (user={user_id}, filas={deleted})")
        return bool(deleted)
    except Exception as e:
        logger.error(f"Error eliminando conversación {conversation_id}: {e}")
        return False
```

- Se llama SIEMPRE vía `run_async()` desde `ui/sidebar.py` (nunca bloquea el hilo de Qt).
- Antes de invocarla, `ui/sidebar.py` pide confirmación con `QMessageBox.question` (estilizado con
  la paleta activa vía `setStyleSheet(_qss(palette))`) — CA-09 exige "una confirmación que evite
  borrados accidentales"; no se introduce un componente de diálogo nuevo, se reutiliza el
  mecanismo estándar de Qt para no inflar el alcance.
- Si la conversación borrada es la activa (`conversation_id == self._conversation_id` en
  `MainWindow`), se dispara el mismo camino que "+ Nuevo chat" (`_on_new_conversation()`), dejando
  el chat en un estado consistente (caso borde de SPEC-014).
- No se persiste `role` sobre `user_id`, se filtra por `user_id="default"` como en toda la app hoy
  (sin autenticación multiusuario, fuera de alcance).

### 0.5 — Hallazgo nuevo no señalado por baseline/spec: `ui/gui.py` NO puede eliminarse por completo

Investigando el impacto real de borrar `ui/gui.py`, encontré que **`voice/wake_word.py`** (que
está en la lista de directorios PROHIBIDOS de tocar) hace `from ui.gui import update_gui_state`
en dos puntos (líneas 102 y 185), y `ui/stt/transcriber.py` hace lo mismo. Si `ui/gui.py`
desaparece como pide el "Módulos afectados" original de SPEC-014, `voice/wake_word.py` deja de
poder importar — rompe el modo manos libres, y no puedo arreglarlo tocando `voice/`.

**Decisión: `ui/gui.py` NO se `git rm` — se reescribe in-place, reducido a un shim de
compatibilidad de ~15 líneas** que conserva únicamente `GLOBAL_STATE`, `WAKE_STATE`,
`update_gui_state()`, `update_wake_state()` (el bridge de estado hilo-seguro consumido desde
fuera de `ui/`). `ui/main_window.py` importa y LEE ese estado desde `ui.gui` (`import ui.gui as
gui_state`, no `from ui.gui import GLOBAL_STATE` — así siempre lee el valor mutado en vivo, mismo
patrón que ya usan `tests/test_autostart.py`/`test_gui_widgets.py` con `import ui.gui as
gui_module`). Esto es una desviación explícita del "se elimina" que dice SPEC-014 §Módulos
afectados — documentada acá porque `voice/` no puede tocarse y la única alternativa (mover
`GLOBAL_STATE`/`update_gui_state` a otro módulo) rompería igual el import de `voice/wake_word.py`
al cambiar el import path. Se solicita confirmación del humano en el mensaje de aprobación.

Consecuencia en `main.py`: la línea 192 hoy hace
`from ui.gui import QApplication, JarvisMainWindow` — con el shim reducido, `QApplication`/
`JarvisMainWindow` ya no viven en `ui.gui`. `main.py` (no está prohibido) se actualiza a:
```python
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow
...
window = MainWindow()
```
`main.py:154` (`from ui.gui import update_gui_state`) **NO cambia** — sigue funcionando porque el
shim conserva esa función.

---

## 1. Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| CA-01 | `MainWindow` (`ui/main_window.py`) setea `Qt.WindowType.FramelessWindowHint` + `Qt.WidgetAttribute.WA_TranslucentBackground`; el QSS del contenedor central aplica `border-radius: 12px` y `border: 1px solid $border`. |
| CA-02 | Clase auxiliar `_TitleBar(QFrame)` dentro de `ui/main_window.py` — reemplaza y absorbe `HeaderBar`: logo, theme toggle, mode pill, wake indicator, y 3 botones minimizar/maximizar/cerrar conectados a `showMinimized()`/`showNormal()`↔`showMaximized()`/`close()`. |
| CA-03 | `_TitleBar`/`MainWindow` usan la API nativa de Qt `self.windowHandle().startSystemResize(edge)` (confirmado disponible: PyQt6 6.11.0 instalado en este entorno) detectando el borde por posición del cursor en un margen de 8px, en vez de tracking manual de geometría. |
| CA-04 | Arrastre de `_TitleBar` vía `self.windowHandle().startSystemMove()` en `mousePressEvent`, misma API nativa que CA-03. |
| CA-05 | `Sidebar.set_collapsed(bool)` anima `minimumWidth`/`maximumWidth` 260↔60 con `ui/animations.py:animate_width()` (`QPropertyAnimation`, 200ms). |
| CA-06 | Botón "+ Nuevo chat" en `Sidebar` emite `new_conversation_requested`; `MainWindow._on_new_conversation()` (portado de `JarvisMainWindow`) limpia `_conversation_id` a `None` y vacía `ChatArea` sin borrar nada — idéntico a hoy. |
| CA-07 | `_ConversationHistoryList` (en `ui/sidebar.py`) renderiza título (`_derive_title()`, ya existe en `ai/memory_manager.py`, sin tocar) + fecha relativa (función nueva `_relative_date()` en `ui/sidebar.py`, stdlib `datetime`, sin dependencia nueva) + ícono eliminar visible solo en `enterEvent`/`leaveEvent` del ítem. |
| CA-08 | Click en un ítem emite `conversation_selected(conversation_id)`; `MainWindow` llama `run_async(memory.get_conversation_turns, ...)` (sin modificar) y carga en `ChatArea`, igual que hoy. |
| CA-09 | Ícono eliminar → `QMessageBox.question` de confirmación → `run_async(memory.delete_conversation, ...)` (ver §0.4) → al confirmar éxito, remueve el ítem de la lista sin recargar toda la página (evita parpadeo) y sin afectar las demás filas. |
| CA-10 | `Sidebar` conserva el mismo mecanismo de paginación por `offset`/"Ver más" que `ConversationList` ya tenía, llamando `list_conversations(limit=30, offset=...)` (sin modificar, ya pagina). |
| CA-11 | `MessageBubble(role=...)` con `QHBoxLayout` + stretch como hoy: `role="user"` alineado a la derecha (`border-radius: 18px`), `role="assistant"` a la izquierda con `ui/components/avatar.py:Avatar` junto a la burbuja. |
| CA-12 | `role="assistant"` renderiza con `QTextBrowser` (no `QLabel`: soporta HTML de tablas/código sin perder selección de texto) cargado con `ui/components/markdown_renderer.py:render_markdown()` (librería `markdown`, extensiones `fenced_code`+`tables`+`codehilite`) + CSS de Pygments inyectado desde `ui/components/code_block.py`. |
| CA-13 | Nuevo rol `role="system"` en `MessageBubble`: `QLabel` centrado, `objectName="SystemMessage"`, QSS visualmente distinto (fondo transparente, texto `$text_muted`, sin burbuja). |
| CA-14 | `TypingIndicator` (`ui/typing_indicator.py`): 3 `QLabel` de punto animados con `QPropertyAnimation` en `QGraphicsOpacityEffect`, ciclo desfasado; `ChatArea.show_typing()`/`hide_typing()` lo monta/desmonta; se oculta en `_on_command_done`/`_on_command_error` (ambos casos, éxito y fallo). |
| CA-15 | `ChatArea` reutiliza el mismo patrón de `ChatFeed._is_near_bottom()`/`_on_range_changed` (umbral 40px), portado sin cambios de comportamiento. |
| CA-16 | Ver §3 "Carga diferida de mensajes" — batching client-side de a 50 sobre el resultado ya traído por `get_conversation_turns()` (sin tocar su firma, CA-29). |
| CA-17 | `MessageBubble` trunca a 500 caracteres + botón "Ver más" que expande (`set_collapsed(bool)`); el truncado busca el espacio en blanco más cercano ≤500 para minimizar Markdown roto a mitad de bloque (ver riesgo #10). |
| CA-18 | `MemoryItem`/`store_turn()` ya usan exactamente esos 6 campos (`id, conversation_id, role, content→text, timestamp, metadata→category/source/importance`); sin cambios de esquema más allá de CA-30. |
| CA-19 | `InputBar._input` es `QTextEdit` (no `QLineEdit` como hoy); `setMaximumHeight` calculado a partir de `fontMetrics().lineSpacing() * 5 + márgenes`, con scroll interno vía `QTextEdit.setVerticalScrollBarPolicy(ScrollBarAsNeeded)` al superarlo. |
| CA-20 | `InputBar` instala un filtro (`eventFilter`/override de `keyPressEvent` en una subclase `_ComposerTextEdit(QTextEdit)`) que intercepta `Qt.Key.Key_Return`/`Key_Enter`: sin `ShiftModifier` → emite y limpia; con `ShiftModifier` → deja pasar el evento (nueva línea). |
| CA-21 | `InputBar` agrega 3 `QPushButton`: adjuntar (📎), voz (🎙, reutiliza el toggle de manos libres existente — ver CA-24), enviar (➤, portado de `Composer`). |
| CA-22 | `InputBar.dragEnterEvent`/`dropEvent` override; valida extensión contra un allowlist (`.png .jpg .jpeg .gif .webp .pdf .txt .md .docx`), agrega un chip de adjunto visual con el nombre; **el contenido del archivo NO se lee ni procesa** (sin CA en SPEC-014 que lo requiera — ver riesgo #12). |
| CA-23 | `InputBar.set_enabled(bool)` — port 1:1 del fix de condición de carrera de REQ-013 (3ra pasada): deshabilita `_input`+`_send_button`, cambia placeholder a "Noddoo está pensando...", reactivado solo en `_on_command_done`/`_on_command_error`. |
| CA-24 | El botón de voz de `InputBar` ES el mismo toggle de modo manos libres que hoy vive en `Composer` (`_wake_toggle`), reutilizando `WakeWordWorker` (movido a `ui/workers.py`) y `voice.wake_word.listen_for_wake_word()` sin ninguna modificación a `voice/`. No se inventa una función STT nueva. |
| CA-25 | `MainWindow._on_command_done()` llama `run_async(memory.store_turn, ...)` sin modificar, portado de `JarvisMainWindow`. |
| CA-26 | `Sidebar`/`MainWindow` llaman `memory.list_conversations()` sin modificar. |
| CA-27 | `MainWindow._on_conversation_selected()` llama `memory.get_conversation_turns()` sin modificar. |
| CA-28 | `MainWindow._ensure_conversation_id()` llama `memory.new_conversation_id()` sin modificar. |
| CA-29 | Único cambio a `ai/memory_manager.py` es la adición descrita en §0.4 — ninguna función existente se edita, ningún `ALTER TABLE` nuevo. |
| CA-30 | Ver firma completa en §0.4. |
| CA-31 | `ui/animations.py:animate_message_entrance(widget)` — `QPropertyAnimation` combinada sobre `QGraphicsOpacityEffect.opacity` (0→1) y `geometry`/`pos` (offset Y +12px → 0), 300ms, `QEasingCurve.Type.OutCubic`; llamada desde `ChatArea.add_message()` tras montar la burbuja. |
| CA-32 | `ui/animations.py:fade_theme_transition(widget)` aplicado UNA vez sobre el widget central de `MainWindow` en `apply_theme()` (crossfade de opacidad ~200ms) — evita instrumentar los 15+ widgets hijos individualmente. |
| CA-33 | Ver riesgo #6 — Qt Style Sheets no soporta `transition:` CSS. Se interpreta como: elementos primarios (chips, botón enviar, botón "+ Nuevo chat", ítems de sidebar) reciben `ui/animations.py:attach_hover_fade()` (`QGraphicsOpacityEffect` + `QPropertyAnimation` en `enterEvent`/`leaveEvent`); el resto conserva el `:hover` instantáneo de QSS ya existente en toda la app. |
| CA-34 | Paletas nuevas completas en `ui/theme.py` — ver tabla de valores en §3. |
| CA-35 | Todos los tokens NO entregados por el humano (`text_muted`, `text_disabled`, `accent_soft`, `on_accent`, `bubble_user_fg`, `bubble_ai_fg`) fueron verificados con cálculo real de contraste WCAG (relative luminance, fórmula oficial) contra los fondos donde se usan — ver tabla y notas en §3. Los tokens SÍ entregados por el humano (`text_secondary` en ambos temas, entre otros) se marcan para reverificación en desarrollo/testing, igual que hizo REQ-013. |
| CA-36 | `ThemeManager.theme_changed` (sin cambios de API) sigue notificando a todo widget registrado con `register_themed()`; los 5 widgets conservados (`right_panel` + 4 tarjetas) ya están registrados y no requieren tocar código. |
| CA-37 | `ThemeManager.load_from_config()`/`set_theme()` siguen usando `config_manager.get_ui_theme()`/`set_ui_theme()` sin modificar. |
| CA-38 | `RightPanel` se instancia sin cambios en `MainWindow._init_ui()`, mismo lugar en el layout (columna derecha, 350px fijo). |
| CA-39 | `InputBar` porta los 5 chips de `Composer._CHIPS` sin cambiar contenido/payload/mecanismo (`run_async(execute_action, ..., channel=ChannelType.DESKTOP)`). |
| CA-40 | `InputBar` agrega una franja/punto de color por chip de tipo `action`, calculado con `security_manager.classify_action(payload)` → `RiskLevel` → token de paleta (`success`/`warning`/`danger`); los chips `template` no llevan badge (no ejecutan ninguna acción). |
| CA-41 | Sin cambios de comportamiento: los chips de acción siguen pasando exclusivamente por `run_async(execute_action, ..., channel=ChannelType.DESKTOP)`, nunca se invoca la función subyacente directo — mismo patrón ya presente en `Composer`/`QuickActionsCard`, portado literal. |
| CA-42 | Todos los módulos nuevos/reescritos listados en §4 se validan con `python -m py_compile` antes de handoff a `orion-tester` (responsabilidad de `orion-dev`, ya en su DoD). |
| CA-43 | Ver §5 "Pruebas sugeridas" + riesgo #8 (`PYTEST_QT_API`) para que el conteo de referencia sea el real (2 failed/305 passed) y no el falso (66/241). |

---

## 2. Módulos a modificar

- `ui/gui.py` — **reescrito in-place, reducido a shim de compatibilidad** (§0.5). NO se elimina.
- `ui/theme.py` — **reescrito por completo**: mismas 4 funciones públicas (`qss_tokens()`,
  `resolve_theme_name()`, `register_themed()`, clase `ThemeManager`) y mismos NOMBRES de campo en
  `Palette` (constraint dura: los 5 widgets conservados dependen de esos nombres exactos en su
  QSS `Template`), valores hex nuevos. Se agregan 2 campos nuevos: `code_bg` (fondo de bloques de
  código, nuevo en REQ-014).
- `ai/memory_manager.py` — **única modificación**: agregar `delete_conversation()` (§0.4). Nada
  más se toca (CA-29).
- `main.py` — **edición puntual**: líneas 190-199, actualizar el import de `ui.gui` a
  `ui.main_window` (§0.5). Sin relación con CA-41/confirmaciones amarillas — los chips heredados
  siguen siendo todos GREEN, así que `_desktop_confirm` no se toca (confirma el "Asumido" de
  SPEC-014: no hay acción no-GREEN nueva expuesta desde la UI en este REQ).
- `requirements.txt` — agregar `markdown`, `Pygments`.
- `tests/conftest.py` — agregar `os.environ.setdefault("PYTEST_QT_API", "pyqt6")` junto a la línea
  31 existente (`QT_QPA_PLATFORM`) — mitigación autorizada del riesgo de `orion-baseline` (§ riesgo
  #8), no es parte de ningún CA pero es necesaria para que CA-43 sea medible correctamente.

---

## 3. Nuevas clases/funciones — arquitectura de archivos

### `ui/main_window.py` (nuevo — reemplaza `ui/gui.py` como punto de entrada de la ventana)
- `class MainWindow(QMainWindow)` — orquestador principal. Métodos portados 1:1 de
  `JarvisMainWindow` (mismo comportamiento, mismo nombre donde no hay razón para cambiarlo):
  `_handle_command`, `_on_command_done`, `_on_command_error`, `_ensure_conversation_id`,
  `_reload_conversations`, `_on_conversations_loaded/error`, `_on_more_conversations`,
  `_on_conversation_selected`, `_on_turns_loaded/error`, `_on_new_conversation`,
  `_on_conversation_deleted` (NUEVO, CA-09), `apply_theme`, `_setup_tray_icon`,
  `_toggle_visible`, `_on_tray_activated`, `closeEvent`, `_on_hands_free_toggled`,
  `_stop_wake_word_worker`. Lee `GLOBAL_STATE`/`WAKE_STATE` vía `import ui.gui as gui_state`
  (§0.5), NO redefine esas variables.
- `class _TitleBar(QFrame)` (auxiliar, mismo archivo) — reemplaza `HeaderBar`: logo/nombre del
  agente, theme toggle, mode pill, wake indicator, 3 botones de ventana. Métodos:
  `set_state(state)`, `set_wake_state(state)`, `apply_theme(palette)` (mismos nombres/contrato que
  `HeaderBar` tenía, para minimizar el diff conceptual en tests).

### `ui/sidebar.py` (nuevo, top-level — ver §0.1)
- `class Sidebar(QFrame)` — señales: `nav_selected`, `conversation_selected`,
  `new_conversation_requested`, `conversation_deleted` (nueva), `more_requested`. Métodos:
  `set_collapsed(bool)`, `is_collapsed() -> bool`, `set_conversations(items, append=False)`,
  `set_active_conversation(id)`, `set_has_more(bool)`, `conversation_count()`, `apply_theme()`.
- `class _ConversationHistoryList(QWidget)` (auxiliar) — reemplaza `ConversationList`: agrega
  fecha relativa e ícono eliminar en hover.
- `def _relative_date(timestamp: str) -> str` — función privada, stdlib `datetime`, sin
  dependencia nueva (p. ej. "hace 2h", "ayer", "12 jul").

### `ui/chat_area.py` (nuevo — reemplaza `ChatFeed`, absorbe la mitad de `CenterPanel`)
- `class ChatArea(QScrollArea)` — API: `add_message(text, role) -> MessageBubble`,
  `load_turns(turns)`, `clear_messages()`, `is_empty()`, `show_typing()`, `hide_typing()`,
  `message_count()`, `apply_theme()`. Internamente: `_mounted_count`, `_pending_older_turns:
  List[MemoryItem]` para la carga diferida (ver abajo).
- `class _EmptyState(QWidget)` (auxiliar) — saludo + subtítulo, portado de
  `CenterPanel._build_empty_state()` SIN el `VoiceOrb` (§0.2). Reutiliza
  `ui.personality.get_time_based_greeting()` y `config_manager.get_display_name()` sin cambios.

**Carga diferida de mensajes (CA-16) sin tocar `ai/memory_manager.py` más allá de CA-30:**
`get_conversation_turns(conversation_id, user_id)` sigue devolviendo hasta 200 turnos en una sola
llamada (firma sin cambios, CA-29). `ChatArea.load_turns(turns)` NO monta los 200 widgets de
golpe: monta solo los ÚLTIMOS 50 (`QTextBrowser`/`QLabel` reales), y guarda el resto en
`_pending_older_turns`. Al conectar `verticalScrollBar().valueChanged` y detectar que el usuario
se acerca al TOPE (`value() <= _NEAR_TOP_PX`), monta el siguiente lote de 50 más antiguos e
inserta al principio del layout, preservando la posición de scroll (ajuste de `setValue()` por la
diferencia de `maximum()` antes/después, técnica estándar para "infinite scroll hacia arriba").
Esto resuelve el costo real de CA-16 (evitar montar 200 widgets pesados de una vez al abrir una
conversación larga) sin requerir paginación a nivel SQL.

### `ui/message_bubble.py` (nuevo — reemplaza `ChatBubble`)
- `class MessageBubble(QFrame)` — `role ∈ {"user", "assistant", "system"}` (nuevo: "system").
  `role="assistant"` usa `QTextBrowser` (rich text, solo lectura, selección habilitada,
  `setOpenExternalLinks(False)` — nunca navega, evita que un link en una respuesta abra el
  navegador sin pasar por el gate de seguridad) con el HTML de `render_markdown()`. `role="user"`
  usa `QLabel` selectable (sin markdown, texto plano, igual que hoy). `role="system"` usa `QLabel`
  centrado sin burbuja. Métodos: `set_collapsed(bool)` (CA-17, con botón "Ver más" interno),
  `set_available_width(int)` (portado igual).

### `ui/typing_indicator.py` (nuevo)
- `class TypingIndicator(QWidget)` — 3 puntos, animación de opacidad desfasada por punto vía
  `QPropertyAnimation` sobre `QGraphicsOpacityEffect`, loop infinito mientras esté visible;
  `start()`/`stop()`.

### `ui/input_bar.py` (nuevo — reemplaza `Composer`)
- `class InputBar(QFrame)` — señales: `command_submitted`, `hands_free_toggled`,
  `file_attached(str)` (nueva). Métodos portados: `text()`, `set_text()`, `clear()`,
  `set_wake_state()`, `apply_theme()`, `set_input_enabled()`/`set_enabled()` (mismo contrato que
  `Composer.set_input_enabled`, CA-23).
- `class _ComposerTextEdit(QTextEdit)` (auxiliar) — override de `keyPressEvent` para Enter/
  Shift+Enter (CA-20) y `sizeHint()` acotado a 5 líneas (CA-19).
- `def _risk_color(action_name: str, palette: Palette) -> str` (privada) — mapea
  `security_manager.classify_action(action_name)` a un token de color de la paleta para CA-40.

### `ui/animations.py` (nuevo)
- `def animate_message_entrance(widget: QWidget, duration_ms: int = 300) -> QPropertyAnimation`
- `def animate_width(widget: QWidget, start: int, end: int, duration_ms: int = 200) -> QPropertyAnimation`
- `def fade_theme_transition(widget: QWidget, duration_ms: int = 200) -> None`
- `def attach_hover_fade(widget: QWidget, palette: Palette) -> None`

Funciones puras reutilizables (no clases) — consistente con `python-style.md` (type hints en
todo, sin estado oculto).

### `ui/workers.py` (nuevo)
- `class WakeWordWorker(QRunnable)` — movido literal desde `ui/gui.py` (mismo código, mismo
  `stop_event`, mismo manejo de excepción con `logger.error`). `ui/gui_workers.py`
  (`CallableWorker`/`run_async`) **NO se toca ni se renombra** — lo siguen usando `right_panel.py`
  y las 4 tarjetas conservadas, y `tests/test_gui_workers.py` (no está en la lista de tests a
  reescribir de SPEC-014). Fusionarlo habría sido churn innecesario fuera de alcance.

### `ui/components/__init__.py` (nuevo, vacío — mismo criterio que `ui/widgets/__init__.py`)

### `ui/components/avatar.py` (nuevo)
- `class Avatar(QWidget)` — círculo con emoji/inicial, reemplaza el `QLabel(_AVATAR_TEXT)` inline
  de `CenterPanel`, ahora reutilizable junto a cada burbuja de IA (CA-11) y en el saludo vacío.

### `ui/components/code_block.py` (nuevo)
- `def pygments_css(theme_name: str) -> str` — `HtmlFormatter(style=..., cssclass="codehilite").get_style_defs()`;
  `"monokai"` para tema oscuro, `"default"` para tema claro (estilos incluidos en el paquete
  `Pygments`, sin dependencia extra). Cacheado por nombre de tema (2 entradas posibles).

### `ui/components/markdown_renderer.py` (nuevo)
- `def render_markdown(text: str, palette: Palette) -> str` — `markdown.markdown(text,
  extensions=["fenced_code", "tables", "codehilite"], extension_configs={"codehilite":
  {"css_class": "codehilite", "guess_lang": False}})`, envuelto en un `<div>` con estilos inline
  mínimos derivados de `palette` (color de texto, color de links = `accent`) + el CSS de
  `code_block.pygments_css()` en un `<style>` embebido (QTextBrowser soporta `<style>` inline).
  `guess_lang=False` evita adivinar lenguaje sobre texto plano sin fence (evita falsos positivos
  de resaltado).

**No se crea `ui/components/search_bar.py` ni `ui/styles/{base,dark,light}.qss`** — ver
justificación en riesgos #13 y #14 respectivamente (ningún CA de SPEC-014 los requiere / entran en
conflicto con la arquitectura de QSS ya vigente en `ui/theme.py`).

### Valores de paleta nuevos (`ui/theme.py`)

Los hex de partida del humano (contexto REQ-014) se mapean a los NOMBRES de campo existentes en
`Palette` (constraint de compatibilidad con los 5 widgets conservados). Los tokens que el humano
NO especificó se derivaron y se **verificaron con cálculo real de contraste WCAG** (fórmula de
luminancia relativa oficial, no estimación visual):

**Oscura:**
| Campo | Hex | Origen |
|---|---|---|
| bg_window | `#0d1117` | dado (bg_primary) |
| bg_surface | `#161b22` | dado (bg_secondary) |
| bg_elevated | `#2d2d2d` | dado (bubble_agent, reutilizado — mismo patrón que REQ-013, donde `bg_elevated == bubble_ai_bg`) |
| bg_input | `#1c2333` | dado |
| bg_hover | `#252d3f` | dado |
| border / border_subtle | `#30363d` | dado (un solo hex, sin variante "subtle" separada) |
| text_primary | `#e6edf3` | dado |
| text_secondary | `#8b949e` | dado — **reverificar en CA-35**, no recalculado acá |
| text_muted | `#909aab` | derivado — 6.09:1 vs bg_surface, 4.85:1 vs bg_elevated, 6.67:1 vs bg_window |
| text_disabled | `#818b9a` | derivado — 5.02:1 vs bg_surface (uso real: nav deshabilitado); 4.0:1 vs bg_elevated (si se usa ahí, reverificar) |
| accent | `#58a6ff` | dado (text_accent) |
| accent_soft | `#163150` | derivado — accent sobre este fondo: 5.23:1 |
| on_accent | `#06121f` | derivado — sobre accent: 7.46:1 |
| success/warning/danger | `#3fb950`/`#d29922`/`#f85149` | dados |
| bubble_user_bg | `#1f77b4` | dado |
| bubble_user_fg | `#ffffff` | derivado — 4.82:1 sobre bubble_user_bg |
| bubble_ai_bg | `#2d2d2d` | dado (bubble_agent) |
| bubble_ai_fg | `#e6edf3` | = text_primary — 11.66:1 sobre bubble_ai_bg |
| scroll_handle | `#3a4150` | derivado, decorativo (sin par de texto) |
| code_bg (NUEVO) | `#161b22` | = bg_surface, para el fondo de bloques `<pre>` |

**Clara:**
| Campo | Hex | Origen |
|---|---|---|
| bg_window | `#ffffff` | dado |
| bg_surface | `#f6f8fa` | dado |
| bg_elevated | `#e8eaed` | dado (bubble_agent) |
| bg_input | `#f0f2f5` | dado |
| bg_hover | `#e8eaed` | dado |
| border / border_subtle | `#d0d7de` | dado |
| text_primary | `#24292f` | dado |
| text_secondary | `#57606a` | dado — reverificar en CA-35 |
| text_muted | `#5c6672` | derivado — 5.48:1 vs bg_surface, 5.84:1 vs bg_window |
| text_disabled | `#66707c` | derivado — 4.73:1 vs bg_surface, 5.03:1 vs bg_window |
| accent | `#0969da` | dado |
| accent_soft | `#e6f0fc` | derivado — accent sobre este fondo: 4.51:1 |
| on_accent | `#ffffff` | derivado — sobre accent: 5.19:1 |
| success/warning/danger | `#2da44e`/`#bf8700`/`#cf222e` | dados |
| bubble_user_bg | `#d1e5ff` | dado |
| bubble_user_fg | `#24292f` | = text_primary — 11.42:1 sobre bubble_user_bg |
| bubble_ai_bg | `#e8eaed` | dado |
| bubble_ai_fg | `#24292f` | = text_primary — 12.16:1 sobre bubble_ai_bg |
| scroll_handle | `#c7cdd6` | derivado, decorativo |
| code_bg (NUEVO) | `#f6f8fa` | = bg_surface |

`orion-dev` debe correr el test de contraste automatizado de CA-35 (mismo criterio/herramienta que
CA-03 de REQ-013) sobre **todos** los pares, incluidos los dados por el humano — si algo falla, se
ajusta y se documenta la desviación, igual que las 2 correcciones de REQ-013.

---

## 4. Archivos a modificar/crear

**Se borran con `git rm` (contenido trackeado en `eb190b3`, no working tree sucio):**
- `ui/widgets/chat_bubble.py`
- `ui/widgets/chat_feed.py`
- `ui/widgets/composer.py`
- `ui/widgets/conversation_list.py`
- `ui/widgets/center_panel.py`
- `ui/widgets/header_bar.py`
- `ui/widgets/sidebar.py`
- `ui/widgets/voice_orb.py`

**Se reescriben in-place (mismo path, contenido nuevo):**
- `ui/theme.py`
- `ui/gui.py` (reducido a shim, §0.5 — desviación del "se elimina" original de SPEC)

**Se editan puntualmente:**
- `ai/memory_manager.py` (+`delete_conversation()`, único cambio)
- `main.py` (líneas 190-199, import path)
- `requirements.txt` (+`markdown`, +`Pygments`)
- `tests/conftest.py` (+`PYTEST_QT_API=pyqt6`)

**Se crean nuevos:**
- `ui/main_window.py`
- `ui/sidebar.py`
- `ui/chat_area.py`
- `ui/message_bubble.py`
- `ui/typing_indicator.py`
- `ui/input_bar.py`
- `ui/animations.py`
- `ui/workers.py`
- `ui/components/__init__.py`
- `ui/components/avatar.py`
- `ui/components/code_block.py`
- `ui/components/markdown_renderer.py`

**Se mantienen SIN NINGÚN cambio de código** (solo consumen los nuevos valores de `Palette`
automáticamente, vía `register_themed()`):
- `ui/widgets/right_panel.py`
- `ui/widgets/system_status_card.py`
- `ui/widgets/quick_actions_card.py`
- `ui/widgets/recent_activity_card.py`
- `ui/widgets/weather_card.py`
- `ui/gui_workers.py`
- `ui/personality.py`, `ui/cli.py`, `ui/tts_engine.py`, `ui/stt/transcriber.py`

---

## 5. Riesgos y mitigación

| # | Riesgo | Mitigación |
|---|--------|-----------|
| 1 | `voice/wake_word.py` (prohibido tocar) importa `from ui.gui import update_gui_state` — borrar `ui/gui.py` rompe el modo manos libres. | `ui/gui.py` se conserva como shim de compatibilidad (§0.5), no se borra. |
| 2 | `main.py:192` importa `QApplication, JarvisMainWindow` desde `ui.gui`; con el shim reducido, rompe. | `main.py` se actualiza (permitido) a importar desde `ui.main_window` + `PyQt6.QtWidgets` directo; `tests/test_main.py` (parchea `sys.modules["ui.gui"]`) debe actualizarse a parchear `ui.main_window` — agregado a la lista de tests a tocar, más allá del listado original de SPEC-014. |
| 3 | Ventana frameless + `WA_TranslucentBackground` + `showMaximized()` al arrancar puede generar artefactos visuales (esquinas/sombra rotas al maximizar) — limitación conocida de Qt en Windows. | `main.py` NO llama `showMaximized()` en el arranque normal (sí en `--tray`, sin cambios ahí); abre en tamaño ventana grande (ej. 1280x800). `MainWindow` ajusta `border-radius` a 0 dinámicamente cuando `isMaximized()` vía `changeEvent`. |
| 4 | `startSystemResize`/`startSystemMove` dependen de la versión de Qt. | Confirmado disponible en este entorno (PyQt6 6.11.0, verificado con `hasattr`). Si `orion-dev` encuentra un entorno sin soporte, fallback documentado: tracking manual de geometría en `mousePressEvent`/`mouseMoveEvent`. |
| 5 | CA-16 (lotes de 50) no puede paginarse a nivel SQL sin tocar `ai/memory_manager.py` más allá de CA-29. | Batching client-side sobre el resultado ya traído por `get_conversation_turns()` sin cambiar su firma — ver §3. |
| 6 | CA-33 "hover suave": Qt Style Sheets no soporta `transition:` CSS. | Interpretación acotada: `QPropertyAnimation`/`QGraphicsOpacityEffect` solo en elementos primarios (`ui/animations.py:attach_hover_fade()`); el resto usa `:hover` instantáneo de QSS (patrón ya vigente). A validar con el humano si se espera cobertura 100%. |
| 7 | Tokens de paleta no entregados por el humano fueron derivados por este agente. | Verificados con cálculo real de contraste WCAG (no estimación) — ver tabla en §3. `orion-dev` corre igual el test automatizado de CA-35 sobre el set completo (dados + derivados) antes de cerrar. |
| 8 | `PYTEST_QT_API` no fijado en el entorno → 64 fallos falsos (documentado por `orion-baseline`). | Autorizado en esta arquitectura: agregar `PYTEST_QT_API=pyqt6` a `tests/conftest.py` (§2). Baseline real: 2 failed/305 passed. |
| 9 | Reescritura de contenido trackeado (8 `git rm` + 2 reescrituras in-place). | `orion-dev` documenta explícitamente en el mensaje de commit final qué se borró (`git rm`) vs. qué se creó/reescribió, como exige SPEC-014. |
| 10 | Truncado de Markdown crudo a 500 caracteres (CA-17) puede cortar una construcción a mitad (ej. bloque de código sin cerrar), generando un render roto en el estado colapsado. | Truncar en el espacio en blanco más cercano ≤500; severidad baja y cosmética — se resuelve al expandir ("Ver más" siempre re-renderiza el texto completo). |
| 11 | No-regresión de la condición de carrera CA-09/REQ-013 (`_pending_user_text`). | Se porta el mismo patrón exacto (deshabilitar input hasta resolución) a `InputBar`/`MainWindow`, ya validado en producción (qa-audit-013.md). |
| 12 | CA-22 (drag&drop) sin backend de procesamiento de archivos ni dependencia de parsing nueva. | Alcance acotado explícitamente a metadata (nombre + validación de extensión); no se lee contenido del archivo desde la UI — evita inflar el alcance sin CA que lo respalde. |
| 13 | `ui/components/search_bar.py` (propuesto por el humano en el punto de partida) no tiene ningún CA en SPEC-014 que lo requiera. | No se crea. Si el humano lo quiere, requiere un CA nuevo — no corresponde inventarlo en arquitectura. |
| 14 | `ui/styles/{base,dark,light}.qss` (propuesto por el humano) entra en conflicto con la regla ya vigente en el docstring de `ui/theme.py` ("QSS con `string.Template` por widget, NUNCA archivos externos sin volver a arquitectura"). | No se crean. Se mantiene el patrón `_QSS_TEMPLATE` por widget ya usado por los 5 widgets conservados — evita dos sistemas de estilos coexistiendo. |
| 15 | Retiro de `voice_orb.py` (§0.2) es un cambio visual visible no pedido explícitamente por el humano. | Señalado explícitamente para confirmación en la aprobación de esta arquitectura. |

---

## 6. Pruebas sugeridas

Una por criterio, agrupadas por archivo de test nuevo/reescrito (todas deben excluir red/mic real,
usar `tmp_path`/mocks según `.claude/rules/testing.md`, y correr con `PYTEST_QT_API=pyqt6`):

| Archivo | CAs cubiertos | Enfoque |
|---|---|---|
| `tests/test_main_window.py` (nuevo, reemplaza gran parte de `test_gui_widgets.py`) | CA-01..CA-04, CA-25..CA-28, CA-42 | Frameless flags, `_TitleBar` min/max/close, `startSystemMove/Resize` invocado (mock de `windowHandle()`), delegación a `memory.*` sin modificar. |
| `tests/test_sidebar.py` (nuevo) | CA-05..CA-10 | `set_collapsed` anima ancho, `_relative_date()` con timestamps fijos, hover muestra ícono eliminar, confirmación antes de `delete_conversation`, paginación offset. |
| `tests/test_chat_area.py` (nuevo) | CA-11, CA-13, CA-14, CA-15, CA-16 | Roles distintos visualmente, `TypingIndicator` show/hide, autoscroll condicional (umbral 40px), batching de 50 al hacer scroll al tope. |
| `tests/test_message_bubble.py` (nuevo) | CA-12, CA-17 | `render_markdown()` con negritas/listas/código/tablas de muestra; colapso >500 chars y expansión. |
| `tests/test_markdown_renderer.py` / `tests/test_code_block.py` (nuevos) | CA-12 | Fixtures de Markdown → HTML esperado; CSS de Pygments generado por tema. |
| `tests/test_input_bar.py` (nuevo, reemplaza `Composer` de `test_gui_widgets.py`) | CA-19..CA-24, CA-39, CA-40, CA-41 | Enter vs Shift+Enter, expansión a 5 líneas, drag&drop con extensión válida/inválida, `set_enabled` bloquea input, chips ejecutan solo vía `run_async(execute_action, ...)`, badge de color por `RiskLevel`. |
| `tests/test_typing_indicator.py` (nuevo) | CA-14 | Animación arranca/para con `start()`/`stop()`. |
| `tests/test_animations.py` (nuevo) | CA-31, CA-32, CA-33 | Duración/easing de cada helper, `attach_hover_fade` no lanza sobre widgets sin efecto previo. |
| `tests/test_theme.py` (reescrito) | CA-34, CA-35, CA-36, CA-37 | Nueva tabla de pares texto/fondo (incluye `code_bg`, `bubble_*_fg`); persistencia de preferencia sin tocar `config_manager`. |
| `tests/test_conversation_memory.py` (extendido, no reescrito completo) | CA-18, CA-29, CA-30 | `delete_conversation()`: borra solo lo del `user_id` correcto, no lanza sobre id inexistente/ya borrado, no afecta otras conversaciones; resto de funciones (`store_turn`, `list_conversations`, `get_conversation_turns`) SIN cambios de comportamiento (regresión). |
| `tests/test_main.py` (actualizado) | CA-42 (indirecto) | Parchear `sys.modules["ui.main_window"]` en vez de `ui.gui"`; mock de `QApplication` desde `PyQt6.QtWidgets` directo. |
| `tests/test_wake_word_gui.py` (reescrito, import paths) | CA-24 | `WakeWordWorker` importado desde `ui.workers`; `MainWindow` desde `ui.main_window`; comportamiento de toggle sin cambios. |
| `tests/test_gui_widgets.py` | — | Retirado / dividido en los archivos de arriba (arquitectura de archivos nueva invalida el original). |
| `tests/test_chat_widgets.py` | — | Retirado / dividido en `test_chat_area.py` + `test_message_bubble.py` + `test_typing_indicator.py`. |
| `tests/test_config_manager_ui_theme.py` | CA-37 | **Sin cambios** — `config_manager.get_ui_theme`/`set_ui_theme` no se tocan en este REQ. |
| Suite completa | CA-43 | `PYTEST_QT_API=pyqt6 python -m pytest tests/ --tb=short -q` → objetivo: mismo 2 failed (anthropic, no atribuible) + 0 fallos nuevos. |

---

## Resumen para el humano

- **`ui/sidebar.py` fusiona** el nav lateral actual + el historial de conversaciones — un solo
  componente, no dos.
- **`ui/widgets/voice_orb.py` se retira** (no se conserva ni en estado vacío) — pendiente de tu
  confirmación explícita.
- **`ui/gui.py` NO se borra del todo**: se reduce a un shim de ~15 líneas porque
  `voice/wake_word.py` (prohibido tocar) depende de su import path — desviación del "se elimina"
  original de SPEC-014, necesaria para no romper el modo manos libres.
- **`delete_conversation()`** queda con la firma y comportamiento de §0.4 (DELETE real, filtrado
  por `user_id`, no lanza sobre conversación inexistente).
- 8 archivos se `git rm`, 2 se reescriben in-place, 12 se crean nuevos, 5 quedan intactos.
- Dependencias nuevas: `markdown`, `Pygments` (sin `qasync`, confirmado).
- Paleta nueva completa, con los tokens no entregados por vos derivados y verificados por cálculo
  real de contraste WCAG — sujeta a la verificación automatizada de CA-35 en desarrollo/testing.

⚠️ El flujo no continúa hasta que apruebes esta arquitectura.
Responde: APROBADO / AJUSTAR [qué] / RECHAZADO [motivo]

---

## 7. ADDENDUM (2026-08-19) — Rechazo de prueba manual: bug real + eliminación panel derecho + refinamiento visual

**Motivo:** Johan rechazó la validación manual (REQ-014 había llegado a QA ✅ COMPLETADO,
`pruebas/qa-audit-014.md`) mostrando una captura real de la app corriendo + 4 capturas de
referencia (WorkBuddy AI, DeepSeek, ChatGPT, Claude). No se reescribe nada de lo ya
aprobado arriba (§0-§6) — esta sección es una extensión, mismo patrón que las reaperturas
de REQ-013 (4ta/5ta pasada, ver `REQ-013-context.md`).

Leído completo antes de proponer: código real de `ui/main_window.py`,
`ui/widgets/right_panel.py`, `ui/widgets/system_status_card.py`,
`ui/widgets/quick_actions_card.py`, `ui/input_bar.py`, `ui/chat_area.py`,
`ui/components/avatar.py`, `ui/theme.py`, `ui/sidebar.py`, `config_manager.py`,
`config.json`, y los tests que referencian `RightPanel`/las tarjetas
(`tests/test_main_window.py`, `tests/test_theme.py`, `tests/test_wake_word_gui.py`).

### 7.1 Causa raíz del bug visual del panel derecho (verificada, no especulada)

**Diagnóstico:** `ui/main_window.py:MainWindow._init_ui()` crea `root = QWidget()`
(línea 214), `objectName("WindowRoot")`, y le aplica vía `apply_theme()` un QSS
(`_QSS_TEMPLATE`, líneas 508-514) que declara `background-color: $bg_window; border: 1px
solid $border; border-radius: ${radius};`. **`root` es un `QWidget` plano, no un
`QFrame`.** Un `QWidget` base NO pinta `background-color`/`border`/`border-radius`
declarados por QSS a menos que se le fije explícitamente
`Qt.WidgetAttribute.WA_StyledBackground = True` — comportamiento documentado de Qt (solo
los widgets cuyo `paintEvent` nativo pasa por `QStyle` — `QFrame`, `QLabel`,
`QPushButton`, etc. — honran esas propiedades sin ese atributo). Confirmado con
`grep -rn "WA_StyledBackground" ui/` → **cero resultados en todo el paquete `ui/`**.

Combinado con `self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)` sobre la
`MainWindow` (línea 192), la superficie ENTERA de la ventana queda compuesta con alpha
por el SO, y el único widget pensado para pintar el fondo opaco real de la app
(`WindowRoot`) **nunca lo hace**. Consecuencias, ambas verificables en el código:

1. **Bleed-through del escritorio ("contenido ajeno... editor de código/terminal" en la
   esquina inferior derecha):** cualquier zona no cubierta por un `QFrame` que se pinte a
   sí mismo (los 4 `#Card` de `RightPanel`, `Sidebar`, `InputBar` sí son `QFrame` y sí
   pintan) queda sin nada debajo. `ui/widgets/right_panel.py:64`
   (`layout.addStretch(1)` tras `WeatherCard`, la última tarjeta) + `#RightPanel {
   background-color: transparent; }` (línea 76 del mismo archivo) es exactamente la
   esquina inferior derecha del panel — la zona reportada. Ahí no hay nada opaco pintado
   en ningún nivel de la jerarquía (`RightPanel` transparente → `WindowBody` transparente
   → `WindowRoot` que declara color pero no lo pinta), así que la ventana translúcida deja
   ver literalmente lo que hay detrás en el escritorio.
2. **Texto superpuesto/ilegible ("Estado del sistema" tapa "CPU 42%", filas que se
   cortan y se pisan):** al no pintarse nunca un fondo opaco de base para toda la
   ventana, los repintados parciales (el `QTimer` de 2000ms de
   `SystemStatusCard._refresh()` actualizando las 4 filas CPU/RAM/Disco/Red, el `QTimer`
   de estado de `_TitleBar`, etc.) no tienen garantía de partir de un lienzo limpio —
   producen el efecto de "ghosting"/doble exposición reportado.

**Factor secundario, encontrado durante la investigación (irrelevante para este REQ
porque el widget se elimina en §7.2, pero documentado para no repetir el patrón):**
`ui/widgets/system_status_card.py:CircularProgress.paintEvent()` (líneas 47-64) nunca
limpia/rellena su propio rect antes de dibujar el arco + el texto `"{percent}%"` — sin
`painter.fillRect(...)` inicial. En un widget que se repinta cada 2000ms, es una segunda
fuente independiente de dígitos superpuestos dentro del propio anillo.

**Fix (aplicar SIEMPRE, panel derecho aparte — el bug es de la ventana completa, no de
`RightPanel`, y puede reaparecer en cualquier hueco del layout nuevo de 2 columnas si no
se corrige acá):**
1. `ui/main_window.py` — inmediatamente después de crear `root`, agregar
   `root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)`. Con esto
   `WindowRoot` pasa a pintar de verdad `$bg_window` + borde + radio como un fondo opaco
   real, eliminando el bleed-through y dándole a cada repintado parcial posterior un
   lienzo limpio de base (se acaba el ghosting).
2. Mismo `setAttribute` en `body = QWidget()` (`WindowBody`, línea 225) — hoy su QSS es
   `background-color: transparent`, así que no es un bug visible ACTUALMENTE, pero es el
   mismo widget-clase con el mismo defecto latente: si mañana alguien le pone un color de
   fondo no transparente ahí (p. ej. para un nuevo estado), reintroduce este bug sin
   ningún aviso. Corregirlo ahora es una línea, cero riesgo, y cierra la clase de bug
   completa en vez de solo el síntoma puntual reportado.
3. `orion-dev` debe correr la app real (no solo `pytest`) para confirmar visualmente que
   el bleed-through desaparece — este es un bug de composición/rendering que
   `python -m py_compile` y la suite de tests headless (`QT_QPA_PLATFORM=offscreen`) NO
   pueden detectar por definición (no hay compositor real en modo offscreen). Documentarlo
   como verificación manual explícita en `desarrollo-log-014.md`.

### 7.2 Eliminación completa del panel derecho

**Decisión de Johan, ya tomada — este apartado define el CÓMO, no si se hace.**

**Se `git rm` (código muerto tras este cambio, cero consumidores):**
- `ui/widgets/right_panel.py`
- `ui/widgets/system_status_card.py`
- `ui/widgets/quick_actions_card.py`
- `ui/widgets/recent_activity_card.py`
- `ui/widgets/weather_card.py`

**Recomendación explícita (Johan planteó la alternativa de dejarlos huérfanos con nota —
esta es la evaluación pedida):** borrar, no dejar huérfanos. Razones: (a) nada queda
importándolos tras este cambio — sería código muerto puro, y tanto
`.claude/rules/python-style.md` como el propio `qa-audit-014.md` (§"Consistencia de
código" — "Dead code: sin hallazgos") tratan la ausencia de código muerto como una
convención activa del proyecto, no un detalle cosmético; (b) **nada se pierde de verdad**
— los 5 archivos ya están commiteados en el historial de `main` (`eb190b3` y anteriores,
REQ-008), recuperables en cualquier momento futuro con `git log --all --
ui/widgets/right_panel.py` / `git show <commit>:ui/widgets/right_panel.py`, exactamente
el mismo argumento que ya se usó en esta misma arquitectura (§0.3) para justificar el
`git rm` de los 8 archivos de REQ-013; (c) las funciones de datos subyacentes que las
tarjetas consumían (`system_actions/system_info.py`, `ai/memory_manager.py:
get_recent_summaries`) **no se tocan** — siguen cubiertas por
`tests/test_system_info_numeric.py` y `tests/test_memory_manager_recent.py`
respectivamente (ninguno de los dos importa las tarjetas, confirmado con grep), así que
si un REQ futuro quiere reactivar un panel de estado del sistema, la capa de datos sigue
intacta y probada — solo habría que reescribir la capa visual, que de todos modos iba a
rehacerse para encajar en la nueva dirección visual. **Queda para tu confirmación
explícita en la aprobación**, igual que el retiro de `voice_orb.py` en la primera pasada.

**Tests a actualizar (sin ellos, la suite falla tras el `git rm` — tests reales
verificados, no una lista genérica):**
- `tests/test_main_window.py` — quitar `test_right_panel_presente_en_el_layout` y la
  entrada `"right_panel": window.right_panel.styleSheet()` del test de re-tematizado
  (ambos referencian `window.right_panel`, que deja de existir).
- `tests/test_theme.py` (líneas 174-180) — quitar `ui.widgets.right_panel` del sweep de
  módulos que audita `test_palette_contrast_ratios`.
- `tests/test_wake_word_gui.py` — quitar el import de `RightPanel` (línea 25) y de
  `recent_activity_card`/`weather_card` (líneas 21-22) y el fixture `no_external_io` que
  los mockea (líneas 30-34) si queda sin otro uso tras el resto de los cambios.

**Chips del composer (CA-39) — confirmado, sin relación con el panel:** leído
`ui/input_bar.py` real — `InputBar._build_chips_row()` (línea 182) vive enteramente
dentro de `InputBar`, sin ningún import ni referencia a `RightPanel` o a las tarjetas.
Los 5 chips (3 `template` + 2 `action`) siguen exactamente igual, mismo mecanismo
(`run_async(execute_action, ..., channel=ChannelType.DESKTOP)`, CA-41 sin cambios). **No
requiere ningún cambio de código** por la eliminación del panel.

**Redistribución del espacio — columna centrada con `max-width`, NO edge-to-edge (como
piden las 4 referencias):**
- `ui/main_window.py:_init_ui()` — se quita la instanciación de `self.right_panel` y las
  2 líneas que lo agregan a `body_layout` (líneas 42, 252-253). El `center_column`
  (chat + input) pasa a ser el único contenido de la columna derecha del `body_layout`,
  pero **no se estira a todo el ancho ganado** — las 4 referencias (WorkBuddy/DeepSeek/
  ChatGPT/Claude) dejan aire a los costados, no usan el 100% del ancho para el chat.
- `ui/chat_area.py` — nueva constante `_MAX_CONTENT_WIDTH = 760` (px). `ChatArea` (ya es
  un `QScrollArea`) agrega `self.setAlignment(Qt.AlignmentFlag.AlignHCenter)` y
  `self._content.setMaximumWidth(_MAX_CONTENT_WIDTH)` en `__init__` — Qt centra
  automáticamente un widget-contenido más angosto que el viewport dentro de un
  `QScrollArea` cuando se fija esa alineación, sin lógica manual nueva. Ajuste
  correlacionado necesario: `_mount_bubble()` (línea 218) pasa hoy
  `self.viewport().width()` a `bubble.set_available_width(...)` — debe pasar
  `min(self.viewport().width(), _MAX_CONTENT_WIDTH) - 32` (descontando los márgenes del
  `_content`, ver §7.3.6) para que el ajuste de línea de las burbujas coincida con el
  ancho realmente visible de la columna, no con el ancho total de la ventana.
- `ui/input_bar.py` — misma constante local `_MAX_CONTENT_WIDTH = 760`. `InputBar`
  agrega `self.setMaximumWidth(_MAX_CONTENT_WIDTH)` en `_build_ui()`.
  `ui/main_window.py` cambia `center_column.addWidget(self.input_bar)` →
  `center_column.addWidget(self.input_bar, 0, Qt.AlignmentFlag.AlignHCenter)` (tercer
  argumento de alineación de `QVBoxLayout.addWidget`, soporte nativo de Qt — sin esto, un
  widget con `maximumWidth` fijado en un `QVBoxLayout` queda pegado a la izquierda en vez
  de centrado).
- Duplicar la constante `_MAX_CONTENT_WIDTH` en los 2 archivos (en vez de un módulo de
  constantes compartido nuevo) es una duplicación menor aceptada a propósito — Johan pidió
  explícitamente priorizar velocidad sobre exhaustividad en esta pasada.

### 7.3 Refinamiento visual — especificaciones concretas y medibles

Brief de Johan (vía Claude Code) punto por punto, con valores nuevos concretos —
ninguno queda en "se ve mejor".

**7.3.1 — Densidad/foco: bajar de jerarquía visual el cluster derecho de la barra
superior.** `ui/main_window.py:_TITLEBAR_QSS_TEMPLATE` (líneas 516-546): `#ThemeToggle` y
`#WakeIndicator` pasan de 32×32px con fondo+borde propios a **28×28px, `background-color:
transparent; border: none;`**, mostrando fondo solo en `:hover` (`$bg_hover`) — mismo
patrón "ícono quieto" que se aplica a `InputBar` en §7.3.3, para que dejen de competir en
peso visual con el chat/input. `#ModePill` reduce `padding: 6px 16px` → `4px 12px` y
`font-size: 12px` → `11px`. El riel de navegación de `Sidebar` (7 íconos, solo 2
habilitados) **no cambia de código** en esta pasada — Johan no lo señaló como punto propio
con valores concretos, solo como parte del listado de elementos que compiten; `orion-dev`
verifica que los 5 ítems deshabilitados ya usan `text_disabled` (no `text_primary`/
`text_secondary`) y lo corrige si encuentra lo contrario, sin agregar alcance nuevo.

**7.3.2 — Escala tipográfica del estado vacío.** `ui/chat_area.py:_QSS_TEMPLATE`
(líneas 303-331): `#GreetingLabel` pasa de `font-size: 28px; font-weight: 300;` a
**`font-size: 40px; font-weight: 700;`** (el peso 300/thin sobre 28px es exactamente lo
opuesto al "dominante, 700-800" que piden las 4 referencias). `#GreetingSubtitle` pasa de
`font-size: 14px` a **`15px`**, se mantiene `color: $text_secondary` — el contraste de
escala pasa de 2:1 (28/14) a ~2.7:1 (40/15), más cercano al rango 32-56px/14-16px medido
por Johan sobre las referencias.

**7.3.3 — Input como "píldora".** `ui/input_bar.py:_QSS_TEMPLATE` (líneas 347-374):
- `#ComposerTextEdit`: `padding: 8px 14px` → **`padding: 16px 22px`**;
  `border-radius: 18px` → **`26px`** (a la altura típica de 1 línea del control esto lee
  como píldora completa; al expandirse a varias líneas se vuelve rectángulo redondeado,
  comportamiento esperado en cualquier input expandible de las 4 referencias).
- `#AttachButton`, `#WakeToggleButton`: dejan de tener `background-color: $bg_input;
  border: 1px solid $border` — pasan a **`background-color: transparent; border: none;`**,
  36×36px (antes 44×44px), mostrando `$bg_hover` circular solo en `:hover`. Se
  convierten en íconos quietos, no en 3 botones en caja del mismo peso.
- `#SendButton`: **se mantiene como el único control "lleno"** —
  `background-color: $accent; color: $on_accent;`, 44×44px, sin borde — es la única
  acción primaria (CTA), consistente con que las 4 referencias tienen "solo 2-3 controles
  discretos, no una fila de botones pegados": ahora hay 2 íconos quietos (adjuntar, voz) +
  1 CTA llena (enviar), no 3 cajas idénticas.
- Sombra suave (pedida explícitamente): `InputBar` agrega un
  `QGraphicsDropShadowEffect` (Qt nativo, sin dependencia nueva) sobre el widget
  `command_row`/`_ComposerTextEdit` — `blurRadius=24`, `offset=(0, 4)`,
  `color=QColor(0, 0, 0, 60)` en tema claro / `QColor(0, 0, 0, 130)` en tema oscuro
  (ajustado en `apply_theme()` según `palette.name`). **Riesgo a mitigar:** Qt solo
  permite UN `QGraphicsEffect` por widget — confirmar que `_ComposerTextEdit`/
  `command_row` no reciben también `attach_hover_fade()` de `ui/animations.py` (hoy no lo
  reciben, verificado; documentar la restricción para que no se rompa en un REQ futuro).

**7.3.4 — Paleta: tema claro pasa a ser el default.** `ui/theme.py`: `DEFAULT_THEME =
"dark"` → **`"light"`** (línea 144) — con esto un usuario/entorno SIN preferencia
persistida arranca en claro. **Aclaración importante para que el cambio sea visible en
la práctica:** `config_manager.py:DEFAULT_CONFIG["ui_theme"]` también dice `"dark"` (línea
~20) y — más importante todavía — **el `config.json` real del repo ya tiene
`"ui_theme": "dark"` persistido** (por eso la captura de Johan se ve en oscuro: no es que
el default de código nunca se haya aplicado, es que ya hay una preferencia guardada que
lo pisa). Cambiar solo `ui/theme.py:DEFAULT_THEME` NO alcanza para que Johan vea claro en
su próxima corrida. Se autoriza puntualmente en esta arquitectura (justificación acotada,
permitido por SPEC-014 "sin modificar salvo necesidad puntual justificada"): (1)
`config_manager.py:DEFAULT_CONFIG["ui_theme"]` → `"light"` (1 línea, mismo valor que
`ui/theme.py`, no toca `get_ui_theme()`/`set_ui_theme()` ni su lógica — CA-37 sigue
intacto); (2) el `config.json` del repo se actualiza a `"ui_theme": "light"` — reversible
en un clic con el toggle de tema que ya existe en `_TitleBar` (CA-36/CA-37 sin cambios).
No se modifica ninguna otra clave de `config.json`/`config_manager.py`.

**7.3.5 — Avatar sin emoji.** `ui/components/avatar.py`: `_DEFAULT_TEXT = "🤖"` se
reemplaza por la inicial del agente — `config_manager.get_agent_name()[:1].upper()`
(hoy resuelve a `"N"` para `"noddoo"`), calculada una vez a nivel de módulo (mismo costo
que la constante actual, `config_manager.load_config()` ya cachea). Cero assets/fuentes
nuevas, cero dependencia nueva — coincide con ninguna de las 4 referencias usando emoji.
El círculo (`#Avatar { background-color: $accent; border-radius: 999px; }`, ya definido
en `ui/chat_area.py:_QSS_TEMPLATE`) no cambia de estilo, solo el contenido de texto.

**7.3.6 — Espaciado general.** Auditado contra las 4 referencias:
- `ui/chat_area.py` — `self._layout.setContentsMargins(16, 16, 16, 16)` →
  **`(32, 32, 32, 32)`** (con la columna ya acotada a 760px por §7.2, más aire interno no
  reduce el ancho de lectura de forma perceptible).
- `ui/input_bar.py` — `outer.setContentsMargins(24, 8, 24, 16)` →
  **`(24, 12, 24, 24)`** (más aire respecto al borde inferior de la ventana).
- `ui/main_window.py:_TitleBar._build_ui()` — `layout.setContentsMargins(16, 8, 12, 8)` →
  **`(20, 10, 16, 10)`**.
- `ui/sidebar.py` — sin cambios de márgenes (no señalado por Johan con valores propios;
  ya tiene aire razonable: filas 8/6/4/6, footer 12/20/12/16).

**7.3.7 — Chips: bajan de peso visual** (parte de §7.3.1, densidad). `#ComposerChip` en
`ui/input_bar.py:_QSS_TEMPLATE`: `background-color: $bg_elevated; border: 1px solid
$border` → **`background-color: transparent; border: 1px solid $border_subtle`**, y
`padding: 5px 12px` → **`4px 10px`**. Mismo contenido/mecanismo (CA-39 intacto), solo
quedan visualmente por debajo del input pill en vez de compitiendo con el mismo peso.

### 7.4 Archivos a modificar/crear (addendum — se suma a §4, no la reemplaza)

**Se `git rm` (nuevo, sobre lo ya aprobado en §4):**
- `ui/widgets/right_panel.py`, `system_status_card.py`, `quick_actions_card.py`,
  `recent_activity_card.py`, `weather_card.py`

**Se editan puntualmente (nuevo):**
- `ui/main_window.py` — `WA_StyledBackground` en `root`/`body` (§7.1); quita
  `RightPanel` (import + instanciación + `addWidget`); centra `input_bar` en
  `center_column`; reduce cluster de `_TitleBar` (§7.3.1); márgenes de `_TitleBar`
  (§7.3.6).
- `ui/chat_area.py` — `_MAX_CONTENT_WIDTH` + alineación centrada del `QScrollArea`
  (§7.2); `_mount_bubble()` ajusta el ancho pasado a `set_available_width()`; tipografía
  de `_EmptyState` (§7.3.2); márgenes de `_layout` (§7.3.6).
- `ui/input_bar.py` — `_MAX_CONTENT_WIDTH` + `setMaximumWidth()` (§7.2); QSS de píldora +
  botones quietos + sombra (§7.3.3); QSS de chips (§7.3.7); márgenes de `outer` (§7.3.6).
- `ui/components/avatar.py` — inicial en vez de emoji (§7.3.5).
- `ui/theme.py` — `DEFAULT_THEME = "light"` (§7.3.4).
- `config_manager.py` — `DEFAULT_CONFIG["ui_theme"] = "light"` (§7.3.4, única línea
  tocada, sin cambiar lógica de `get_ui_theme()`/`set_ui_theme()`).
- `config.json` — `"ui_theme": "light"` (§7.3.4).
- `tests/test_main_window.py`, `tests/test_theme.py`, `tests/test_wake_word_gui.py` —
  ver §7.2 "Tests a actualizar".

**Sin cambios respecto a §4:** todo lo demás (12 archivos nuevos de la primera pasada,
`ai/memory_manager.py`, `main.py`, `ui/sidebar.py` salvo lo ya cubierto, etc.).

### 7.5 Riesgos y mitigación (addendum)

| # | Riesgo | Mitigación |
|---|--------|-----------|
| 16 | El fix de `WA_StyledBackground` (§7.1) es un bug de composición/rendering — `pytest`/`py_compile` no lo detectan (headless, sin compositor real). | `orion-dev` corre la app real (`run`) y confirma visualmente antes de handoff; documentado como verificación manual explícita en `desarrollo-log-014.md`, no solo "suite verde". |
| 17 | `QGraphicsDropShadowEffect` (§7.3.3) es el mismo tipo de mecanismo que `attach_hover_fade()` (`QGraphicsEffect`, uno por widget en Qt). | Verificado: `_ComposerTextEdit`/`command_row` no reciben `attach_hover_fade()` hoy. Si un REQ futuro quiere agregarlo ahí, tiene que elegir uno de los dos efectos, no ambos. |
| 18 | Borrar las 5 tarjetas + `right_panel.py` es irreversible en el working tree (aunque recuperable vía git). | Mismo argumento ya aceptado en §0.3 para los 8 archivos de REQ-013: recuperable con `git log --all -- <path>` en cualquier momento futuro. Señalado para confirmación explícita de Johan (no asumido). |
| 19 | `_MAX_CONTENT_WIDTH` duplicado en 2 archivos (`chat_area.py`, `input_bar.py`) en vez de una constante compartida. | Duplicación menor aceptada a propósito por velocidad (pedido explícito de Johan); si diverge en un REQ futuro, unificar entonces. |
| 20 | Cambiar `config.json` (`"ui_theme": "light"`) es tocar un archivo de datos/runtime, no solo código — ya aparece con cambios sin commitear en `git status` de este REQ. | Es exactamente el mecanismo que `set_ui_theme()`/CA-37 ya usa para persistir preferencia — no se inventa un canal nuevo, se fija el valor inicial una vez. Reversible con un clic en el toggle existente. |

### 7.6 Pruebas sugeridas (addendum)

| Área | Enfoque |
|---|---|
| `WA_StyledBackground` (§7.1) | Test headless: `root.testAttribute(Qt.WidgetAttribute.WA_StyledBackground) is True` sobre `MainWindow` instanciada — no reemplaza la verificación visual manual, la complementa. |
| Ausencia de `RightPanel` | `tests/test_main_window.py` — `hasattr(window, "right_panel")` es `False`; `body_layout` solo contiene `sidebar` + `center_column`. |
| Columna centrada (§7.2) | `tests/test_chat_area.py`/`test_input_bar.py` — `chat_area._content.maximumWidth() == 760`, `input_bar.maximumWidth() == 760`; `chat_area.alignment()` incluye `AlignHCenter`. |
| Tipografía estado vacío (§7.3.2) | Extensión de `tests/test_theme.py` — el QSS generado contiene `font-size: 40px` y `font-weight: 700` para `#GreetingLabel`. |
| Avatar sin emoji (§7.3.5) | `tests/test_gui_widgets.py`/equivalente — `Avatar().text() == "N"` con `get_agent_name()` mockeado a `"noddoo"`; ningún emoji en el texto por defecto. |
| Tema claro default (§7.3.4) | `tests/test_config_manager_ui_theme.py` — `DEFAULT_CONFIG["ui_theme"] == "light"`; `tests/test_theme.py` — `DEFAULT_THEME == "light"`. CA-35 (contraste WCAG) se re-corre sin cambios de tokens — la paleta clara ya estaba verificada, solo cambia cuál es la default. |
| Regresión CA-39/CA-40/CA-41 | Sin cambios de comportamiento esperados — la suite existente de `test_input_bar.py` debe seguir en verde tal cual, solo cambia QSS (no hay test que dependa de valores exactos de padding/radius salvo que ya existiera uno — verificar). |
| Suite completa | `PYTEST_QT_API=pyqt6 python -m pytest tests/ --tb=short -q` → mismo criterio de siempre: 0 regresiones nuevas sobre el número de referencia post primera pasada (366 passed/2 failed pre-existentes), ajustado por los tests quitados/agregados de este addendum. |

### 7.7 Qué NO cambia (ratificación explícita del handoff de Johan)

Ventana frameless, resize/move nativo (§CA-01..04, sin tocar salvo el `WA_StyledBackground`
de §7.1 que no altera su comportamiento funcional), sidebar con historial+borrado
(CA-05..10), Markdown+código resaltado (CA-11..18), animaciones (CA-31..33, salvo el
riesgo #17 de convivencia con la sombra nueva), `delete_conversation()` (CA-25..30),
integración de voz (CA-19..24), gate de seguridad de los chips (CA-39..41) — nada de eso
se toca. Esta pasada es puntual: bug de composición de la ventana (§7.1), eliminación del
panel derecho (§7.2), refinamiento visual acotado y medible del resto (§7.3).

---

## Resumen para el humano — ADDENDUM

- **Causa raíz del bug encontrada y verificada en código** (no es una hipótesis): `root`
  (`WindowRoot`) es un `QWidget` plano que declara un fondo por QSS pero nunca lo pinta
  porque falta `WA_StyledBackground` — combinado con la ventana translúcida, eso es lo
  que deja ver el escritorio detrás y produce el texto superpuesto. Fix de 2 líneas,
  aplicado a `WindowRoot` y `WindowBody`.
- **Panel derecho: recomiendo `git rm` de los 5 archivos** (no dejarlos huérfanos) —
  recuperables por git en cualquier momento, cero pérdida real. Necesito tu confirmación
  explícita en la aprobación, igual que con `voice_orb.py` en la primera pasada.
- **Chips del composer confirmados sin relación con el panel** — cero cambio de código
  por la eliminación.
- **Layout pasa a 2 columnas** con la columna de chat/input **centrada y acotada a
  760px** (no edge-to-edge), como las 4 referencias.
- **6 especificaciones visuales concretas** con valores nuevos: jerarquía del cluster
  superior derecho, tipografía del saludo (40px/700 vs 15px), input como píldora real
  (padding 16/22, radio 26px, sombra, botones quietos + 1 CTA llena), tema claro como
  default (con la aclaración de que hace falta tocar `config.json`, no solo
  `ui/theme.py`), avatar con inicial en vez de emoji, espaciado general aumentado.

⚠️ El flujo no continúa hasta que apruebes este addendum.
Responde: APROBADO / AJUSTAR [qué] / RECHAZADO [motivo]
