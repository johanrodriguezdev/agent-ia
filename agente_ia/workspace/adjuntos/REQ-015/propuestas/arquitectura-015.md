# Arquitectura REQ-015 — Migrar panel de escritorio NODDOO a WebView (HTML/CSS/JS real)

**Estado:** PROPUESTA — pendiente de aprobación humana (Johan)
**Agente:** orion-architect
**Fecha:** 2026-08-19

---

## 0. Decisiones técnicas centrales (los 4 puntos sin preferencia previa del humano)

### 0.1 Candidato técnico: `QWebEngineView` (PyQt6-WebEngine) — no `pywebview`

**Decisión: `QWebEngineView`.**

Justificación concreta, no moneda al aire:

| Eje | `QWebEngineView` | `pywebview` |
|---|---|---|
| Integración con `QMainWindow` ya existente | Es un `QWidget` más — se embebe como `centralWidget()` exactamente igual que `CenterPanel` hoy | Administra su propia ventana/loop nativo (WebView2 de Windows) — requeriría re-arquitecturar cómo coexisten ventana y GUI |
| Tray (`QSystemTrayIcon`) | Reutilizable sin cambios — vive en el mismo `QMainWindow` | Necesitaría puentear un `QSystemTrayIcon` de PyQt6 corriendo en paralelo al loop propio de `pywebview` — dos loops de eventos nativos coexistiendo es una fuente de bugs de foco/cierre difíciles de depurar |
| `WakeWordWorker` (`QRunnable` + `QThreadPool`) | Reutilizable sin cambios — mismo hilo de señales Qt | Igual necesitaría convivir con el loop de `pywebview`, sin garantía de que las señales Qt se entreguen de forma predecible si el loop principal no es el de Qt |
| `run_async()`/`ui/gui_workers.py` (`QThreadPool`+`pyqtSignal`) | Reutilizable **sin tocar una línea** | Mismo problema de loop dual |
| Autostart (REQ-011, `setup_autostart.py`) | Cero cambios — invoca `main.py --tray`, agnóstico de la tecnología interna | Cero cambios (mismo motivo) |
| `startSystemMove()`/`startSystemResize()` (Qt 5.15+) para ventana frameless (CA-01, CA-02) | Disponibles directo sobre `QWindow` | No aplica — `pywebview` no expone `QWindow` |
| Costo | ~150-200MB de Chromium embebido (Qt WebEngine) | Usa WebView2 nativo de Windows (más liviano, pero requiere WebView2 Runtime instalado — en Windows 11 viene preinstalado, en versiones más viejas de Windows 10 no) |
| Esfuerzo de reescritura del shell (tray/autostart/threading) | Ninguno — se preserva el 95% de `ui/gui.py` a nivel de infraestructura (todo excepto el `centralWidget()`) | Alto — reescribir tray, threading, ciclo de vida de ventana |

El único costo real de `QWebEngineView` es el tamaño en disco (~150-200MB), que es un costo de instalación **una sola vez**, no un riesgo de ejecución. El costo de `pywebview` es reescribir y volver a probar manualmente infraestructura ya validada en REQ-008/REQ-009/REQ-011 (tray, wake word, autostart) — exactamente el tipo de riesgo que este REQ busca reducir, no aumentar. Con 3 ciclos de QA manual ya gastados en REQ-014 por bugs de composición, no se justifica apostar la infraestructura ya probada a una reescritura completa del shell.

### 0.2 Framework frontend: vanilla HTML/CSS/JS (ES6 modules) — no React/Vue

**Decisión: vanilla, sin build step, sin `npm`/bundler.**

Justificación (criterio explícito del handoff: quién mantiene el código — un agente IA, no un equipo humano con convenciones de industria):
- El proyecto no tiene hoy ninguna dependencia de Node.js/npm. Introducir React/Vue implica: `package.json`, `node_modules`, un bundler (Vite/webpack), y un paso de build que debe ejecutarse antes de que `QWebEngineView` tenga algo que cargar. Cada uno de esos componentes es una superficie nueva de fallos de build que `orion-dev`/`orion-tester` tendrían que diagnosticar sin tooling de JS existente en el repo.
- La superficie de la UI es acotada y bien definida (sidebar, chat area, composer, modal de confirmación) — no justifica gestión de estado reactivo de un framework de componentes. Con el bridge Python↔JS haciendo de única fuente de verdad para los datos (conversaciones, turnos, tema, estado de voz), el DOM del lado JS es mayormente proyección directa de eventos, no estado derivado complejo.
- Cargar React/Vue sin build (vía `<script>` UMD) evitaría el bundler pero añadiría ~130KB+ de librería vendida localmente (no hay CDN disponible/confiable para un WebView de escritorio sin conexión garantizada) por un beneficio marginal frente a DOM manipulation directo bien organizado en módulos.
- Menos piezas móviles = menos bugs para un mantenedor que no es humano. Vanilla JS con `type="module"` (imports ES6 nativos, sin bundler) da organización de código comparable a componentes sin la complejidad de un framework.

### 0.3 Resaltado de código: Pygments **server-side** (Python) — no librería JS client-side

**Decisión: `markdown` (Python) + extensión `codehilite` (Pygments) + sanitización server-side con `bleach`.**

Justificación:
- Las respuestas del asistente llegan a Python como texto completo (`resolve()` no hace streaming de tokens — devuelve `resolution.text` de una sola vez, confirmado en `ui/gui.py::_handle_command`/`_on_command_done` actual). No hay razón para parsear Markdown en el cliente cuando el texto completo ya está en Python antes de llegar al WebView.
- Con resaltado client-side (p. ej. `highlight.js`), el JS necesitaría: vendorizar la librería + sus temas CSS, parsear Markdown en JS (otra librería más, p. ej. `marked`), y sanitizar el HTML resultante en JS (una tercera librería, p. ej. `DOMPurify`) — tres dependencias JS nuevas vendorizadas a mano, sin `npm` para gestionar versiones/actualizaciones de seguridad.
- Server-side, es **una sola responsabilidad Python** (`ui/webview/markdown_render.py`) con dos librerías bien establecidas (`markdown`, `Pygments`) más `bleach` para sanitizar — las tres testeables con `pytest` puro, sin ningún test que dependa de un motor JS.
- Reduce directamente la superficie de la parte más sensible del bridge: JS nunca ejecuta lógica de parsing/sanitización, solo hace `element.innerHTML = html_ya_sanitizado`. Menos lógica en JS es directamente menos superficie de XSS.

### 0.4 Mecanismo de reflejo de estado de voz (`voice/wake_word.py`) — diseño nuevo, sin `ui/gui.py`

Investigado en disco (no asumido) cómo `voice/wake_word.py` y `ui/stt/transcriber.py` (ambos prohibidos) dependen hoy de `ui/gui.py`:

- **`voice/wake_word.py::listen_for_wake_word(stop_event=None, wake_state_callback=None)`** — el import `from ui.gui import update_gui_state` (líneas 102, 185) **solo se ejecuta cuando `wake_state_callback is None`**, envuelto en `try/except: pass`. La GUI de hoy (`ui/gui.py::WakeWordWorker.run()`) **siempre** pasa `wake_state_callback=update_wake_state` (su propia función de módulo) — por lo tanto ese import nunca se ejecuta cuando hay GUI activa. Solo se alcanza desde el loop de consola pura de `main.py` (opción `3` del menú CLI, `wake_result = listen_for_wake_word()` **sin** kwargs) — y `ui/cli.py` ya oculta esa opción cuando `gui_active=True` (comentario REQ-009 en `main.py:206-208`). Es decir: es una ruta 100% headless-sin-GUI, ya diseñada defensivamente para degradar en silencio si `ui.gui` no existe.
- **`ui/stt/transcriber.py::listen_command()`** — su import es `try: from ui.gui import update_gui_state / except ImportError: update_gui_state = lambda x: None` (ya con fallback no-op incorporado). Grep confirma que **el único consumidor de `listen_command()` en todo el repo es `ui/cli.py`** — la GUI actual **nunca** lo llama (usa su propio `WakeWordWorker` sobre `voice/wake_word.py` para el toggle de manos libres). Es decir: irrelevante para la UI, es exclusivamente un helper de la CLI de texto/voz síncrona.

**Conclusión:** ninguno de los dos módulos prohibidos necesita que exista un archivo llamado `ui/gui.py` para funcionar correctamente en modo headless (ambos ya degradan solos), y ninguno de los dos es parte del camino real de "reflejar estado en la GUI" cuando la GUI está activa — ese camino es enteramente interno a la GUI (`WakeWordWorker` + polling), que sí voy a rediseñar.

**Mecanismo nuevo (diseñado desde cero, sin heredar el shim de REQ-014):**
- `ui/webview/gui_state.py` — módulo Python puro (**cero imports de PyQt/Qt**), con la misma forma que el estado de hoy: `GLOBAL_STATE` (`"IDLE"|"LISTENING"|"PROCESSING"|"RESPONDING"`), `WAKE_STATE` (`"INACTIVE"|"LISTENING_WAKE"|"AWAKE"`), `update_gui_state(new_state)`, `update_wake_state(new_state)`. Deliberadamente en un **path nuevo** (no `ui/gui.py`, que la SPEC exige eliminar por completo) — ver "Riesgos" para el efecto exacto y acotado sobre la rama headless de `voice/wake_word.py`.
- `ui/webview/wake_word_worker.py` — `WakeWordWorker(QRunnable)`, **mismo diseño exacto** que el `WakeWordWorker` de `ui/gui.py` hoy (mismo `stop_event`, mismo `try/finally` con `update_wake_state("INACTIVE")`), pero llamando a `listen_for_wake_word(stop_event=self.stop_event, wake_state_callback=update_wake_state)` importado de `ui.webview.gui_state`. **Cero cambios de comportamiento observable** respecto al mecanismo actual.
- `ui/webview/main_window.py::MainWindow` — mismo patrón de **polling con `QTimer` cada 100ms** que `JarvisMainWindow._poll_state()` hoy (no hay alternativa mejor: `listen_for_wake_word()` corre en un hilo `QRunnable` fuera del control de señales Qt, exactamente igual que hoy — no cambia el motivo original de por qué se pollea). En cada cambio, en vez de empujarlo a widgets Qt, lo emite por el bridge (`gui_state_changed`/`wake_state_changed`, ver contrato del bridge en §4) para que JS actualice el DOM.
- `main.py:154` se actualiza de `from ui.gui import update_gui_state` a `from ui.webview.gui_state import update_gui_state`, envuelto en el mismo `try/except Exception: logger.debug(...)` que ya existe — preserva el reflejo de `PROCESSING` para comandos tipeados por consola mientras la GUI está activa (ambos corren en paralelo hoy, ver `main.py::main()` vs `jarvis_runner` thread).

---

## 1. Cobertura de criterios de la SPEC (48 CA)

### Ventana / shell de la app

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-01 | `MainWindow(QMainWindow)` con `Qt.WindowType.FramelessWindowHint` + `WA_TranslucentBackground` en la ventana top-level; `centralWidget()` es **un único `QWebEngineView` a pantalla completa de la ventana**, sin ninguna capa `QWidget` intermedia con fondo propio. Esquinas redondeadas, sombra, y los 3 controles (min/max/cerrar) se dibujan **enteramente en CSS/HTML** dentro del WebView — nunca en Qt. Ver §5.1 para el detalle de por qué esto es la pieza clave de la no-regresión de CA-03. |
| CA-02 | Resize: JS detecta el cursor a ≤6px de cualquier borde/esquina (`mousemove`) y en `mousedown` llama al bridge `start_resize(edge)` → Python invoca `self.windowHandle().startSystemResize(edge)` (API nativa de `QWindow`, Qt 5.15+, sin mouse-tracking manual). Move: JS detecta `mousedown` en la franja de "barra de título" CSS y llama `start_move()` → `self.windowHandle().startSystemMove()`. Ambas son APIs del sistema operativo (mismo mecanismo que usa una ventana con marco nativo), no una reimplementación manual propensa a bugs. |
| CA-03 | Ver §5.1 — no-regresión estructural: no existe ningún `QWidget` en el árbol de widgets visible que necesite `WA_StyledBackground`; el único widget es el `QWebEngineView` a pantalla completa, cuyo contenido es HTML/CSS estándar (el modelo de caja CSS pinta el `background-color` de todo elemento por defecto, no es opt-in como en Qt). |
| CA-04 | Ver §5.1 — **esto NO es una consecuencia automática de usar WebView** (ver honestidad de la explicación abajo). Se implementa `ui/webview/window_geometry.py::fit_size_to_screen(screen_available, minimum=(1024, 640), fraction=0.85) -> (w, h, x, y)` — función pura, sin dependencia de Qt en su firma (recibe el rect ya como tupla), testeable con `pytest` puro contra casos borde (pantalla más chica que `minimum`, distintos factores de escala). `MainWindow.__init__` la llama contra `QApplication.primaryScreen().availableGeometry()` (excluye la barra de tareas) ANTES de `show()`, nunca `showMaximized()` (ver §5.1 para por qué se evita maximizado con frameless). |
| CA-05 | Ver §5.1 — el input (`<textarea>`/`contenteditable`, CA-20) declara `border`, `background-color` y `::placeholder` en **una única regla CSS co-localizada** en `composer.css`, sin cascada QSS de múltiples selectores por `objectName` como hoy. Test de regresión automatizado en §8 lee `getComputedStyle()` del elemento vía `page().runJavaScript()` y falla si borde/fondo son transparentes o el placeholder está vacío. |

### Sidebar

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-06 | `#sidebar { width: 260px; transition: width 200ms ease; }` + clase `.collapsed { width: 60px; }` alternada por JS (`sidebar.js`), consistente con el `200ms` ya validado en REQ-013/014 (no CSS `QPropertyAnimation`). |
| CA-07 | Botón "+ Nuevo chat" → bridge `new_conversation()` → `Bridge.new_conversation()` limpia `self._conversation_id = None` (mismo patrón que `JarvisMainWindow._on_new_conversation()` hoy) y emite `conversation_cleared()`; el id real se acuña recién en el primer `send_message()` exitoso (idéntico a `_ensure_conversation_id()` de hoy, evita conversaciones huérfanas — caso borde de doble clic). |
| CA-08 | `Bridge.get_conversations()`/evento `conversation_list_updated` entrega `[{conversation_id, title, last_activity, turn_count}]` (mapeo directo de `ConversationSummary`, sin tocar `list_conversations()`); JS renderiza título + fecha relativa (`Intl.RelativeTimeFormat`, sin librería nueva) + botón eliminar visible solo en `:hover`. |
| CA-09 | Click en un ítem → bridge `select_conversation(conversation_id)` → `Bridge` llama `memory.get_conversation_turns(conversation_id, user_id="default")` vía `run_async()` → evento `turns_loaded(json)` con el contenido ya renderizado a HTML sanitizado (§0.3) → JS reemplaza el feed y marca el ítem activo. |
| CA-10 | Confirmación **a nivel UI** (modal JS propio, no `security_manager.require_confirmation()` — ver justificación en §4.3, mismo criterio ya aceptado en REQ-013/REQ-014, donde `qa-audit-014.md` documentó como observación no bloqueante que `delete_conversation()` es 🟢 con mitigación de UI). Al confirmar, bridge `request_delete_conversation(conversation_id)` → `memory.delete_conversation(conversation_id, user_id="default")` (CA-31) vía `run_async()` → si `True`, evento `conversation_removed(conversation_id)` saca el ítem del DOM sin recargar todo el listado. |
| CA-11 | `Bridge.load_more_conversations()` llama `list_conversations(limit=30, offset=N)` (firma existente, sin tocar) — mismo patrón "Ver más" que `Sidebar.more_requested`/`_on_more_conversations()` hoy, sin `LIMIT` infinito. |

### Chat area — burbujas, Markdown, código

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-12 | CSS: burbujas de usuario alineadas a la derecha con `bubble_user_bg`/sin avatar; burbujas de IA a la izquierda con avatar (inicial del agente, CA-46) y `bubble_ai_bg`. Clases `.msg-user`/`.msg-assistant` distintas. |
| CA-13 | Ver §0.3 — `markdown` (extensiones `fenced_code`, `tables`, `codehilite`) + `Pygments` + sanitización `bleach` en `ui/webview/markdown_render.py::render_markdown(text) -> str`, ejecutado en Python antes de que el HTML llegue a JS. |
| CA-14 | Rol `"system"` (nuevo valor posible, ya cabe en el esquema `{role}` de `MemoryItem`/CA-19 sin migración) renderiza con clase `.msg-system`, centrado, sin avatar ni burbuja lateral. |
| CA-15 | `Bridge` emite `typing_started()` inmediatamente después de despachar `resolve()` vía `run_async()`, y `typing_stopped()` en el callback `on_done`/`on_error` (ambos siempre se ejecutan — ver `CallableWorker.run()` en `ui/gui_workers.py`, no tocado). JS anima 3 puntos vía CSS `@keyframes`. |
| CA-16 | JS puro: antes de insertar un mensaje nuevo, se mide `chatArea.scrollHeight - chatArea.scrollTop - chatArea.clientHeight`; si es `> 40`, no se hace `scrollIntoView()` automático. |
| CA-17 | `get_conversation_turns(conversation_id, user_id, limit=200)` se llama **sin tocar su firma** (respeta CA-30). La "carga en lotes de 50" se interpreta como **inserción diferida en el DOM** (evita el trabajo real que causaba jank: parseo/pintado sincrónico de todo el HTML de una vez) — JS inserta los turnos recibidos en tandas de 50 vía `requestAnimationFrame`, no en una sola pasada. Documentado explícitamente como interpretación deliberada — no hay paginación real a nivel de query porque `ai/memory_manager.py` no se modifica más allá de CA-31. |
| CA-18 | JS: si `content.length > 500`, el bloque se renderiza con `max-height` + gradiente de recorte y un botón "Ver más" que remueve el límite — el contenido completo ya está en el DOM (ya sanitizado), no requiere una segunda llamada al bridge. |
| CA-19 | Sin cambios al esquema — se sigue usando `MemoryItem{id, conversation_id, role, text, timestamp, ...}` tal cual lo devuelve `get_conversation_turns()`/`store_turn()` hoy. |

### Input bar + voz

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-20 | `<textarea id="composer-input">` con `field-sizing`/JS que ajusta `rows` hasta 5 y luego scrollea internamente (`overflow-y: auto` tras el máximo). |
| CA-21 | JS: `keydown` con `key === "Enter" && !shiftKey"` → `preventDefault()` + enviar; `Shift+Enter` deja el `\n` por defecto del textarea. |
| CA-22 | Fila de composer con 3 controles: adjuntar (dispara el flujo de drag&drop/selección, §5.3), voz (toggle manos libres, ver CA-25), enviar. |
| CA-23 | **A nivel Qt, no del DOM** — ver §5.3: el navegador (Chromium embebido) no expone la ruta absoluta de un archivo soltado vía la API estándar `File` (restricción de seguridad del propio motor, no una limitación nuestra). `MainWindow.setAcceptDrops(True)` + `dragEnterEvent`/`dropEvent` a nivel de `QMainWindow` (con un `eventFilter` sobre el `QWebEngineView` para interceptar antes de que Chromium consuma el evento) extraen la ruta real vía `QDropEvent.mimeData().urls()`, la validan contra una allowlist de extensiones (`ui/webview/file_drop.py`), y empujan el resultado a JS vía el evento `file_attached(path, name, accepted, reason)` para que el composer muestre el chip de adjunto o el rechazo. |
| CA-24 | Doble guardia: (1) JS deshabilita visualmente el textarea/botón enviar mientras `typing_started()`…`typing_stopped()` está activo (paridad UX con hoy); (2) **nuevo, más estricto que hoy** — `Bridge.send_message()` mantiene un flag `self._resolution_in_flight: bool` server-side y rechaza (`return`, log de advertencia) cualquier llamada mientras ya hay una resolución en curso, **porque el bridge es invocable desde JS sin pasar por el estado `disabled` del DOM** (a diferencia de Qt, donde un widget deshabilitado no entrega señales — esa garantía "gratis" no existe en un bridge JS→Python). Documentado explícitamente en §7 como una guarda nueva, no solo portada. |
| CA-25 | El botón de voz del composer reutiliza **exactamente** el mecanismo de manos libres ya existente (`voice/wake_word.py::listen_for_wake_word()`, vía el `WakeWordWorker` de §0.4) — es la única API pública de `voice/` que la GUI actual consume hoy (`ui/stt/transcriber.py::listen_command()` es exclusivo de la CLI de texto, confirmado por grep, no se toca ni se reutiliza acá). Cero modificaciones a `voice/`. |

### Persistencia de conversaciones

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-26 | `_on_command_done` (equivalente en `Bridge`) llama `memory.store_turn(...)` vía `run_async()`, firma sin tocar. |
| CA-27 | `Bridge.get_conversations()`/`load_more_conversations()` llaman `list_conversations()` sin tocar. |
| CA-28 | `Bridge.select_conversation()` llama `get_conversation_turns()` sin tocar. |
| CA-29 | `Bridge._ensure_conversation_id()` llama `new_conversation_id()` sin tocar (mismo patrón lazy que hoy). |
| CA-30 | Confirmado — el único cambio a `ai/memory_manager.py` en todo este REQ es agregar `delete_conversation()` (CA-31). Ninguna función existente cambia de firma ni de comportamiento. |
| CA-31 | Se **reimplementa desde cero** (no `git checkout` del stash) el método documentado en `baseline-015.md` líneas 176-200, con comportamiento idéntico verificado: DELETE real vía `DELETE FROM memories WHERE conversation_id = ? AND user_id = ?`, retorna `False` sin excepción si `conversation_id` es falsy o si `cur.rowcount == 0`, recarga `_load_embeddings()` solo si `deleted > 0` (mismo patrón que `consolidate()`/`clear_user_memory()` ya existentes en el archivo). Se reimplementa en vez de recuperar del stash para no arrastrar sin querer otros cambios del addendum de REQ-014 que pudieran estar mezclados en ese archivo del stash (riesgo señalado explícitamente por `orion-baseline`). |

### Animaciones

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-32 | CSS `@keyframes fadeSlideIn { from { opacity:0; transform: translateY(8px);} to {opacity:1; transform:none;} }` aplicado a cada `.message` nuevo insertado, `animation-duration: 300ms`. Cero `QPropertyAnimation`. |
| CA-33 | Cambio de tema: JS alterna `document.documentElement.dataset.theme` y CSS declara `transition: background-color 200ms, color 200ms, border-color 200ms` en los selectores relevantes de `theme.css` — nunca un cambio instantáneo. |
| CA-34 | `:hover`/`:focus-visible` con `transition: background-color 150ms, border-color 150ms` en botones, ítems de sidebar y chips. |

### Temas claro/oscuro

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-35 | Paletas completas definidas como **fuente única de verdad en Python** (`ui/webview/theme.py::DARK_TOKENS`/`LIGHT_TOKENS`), partiendo literalmente de los hex ya validados y documentados en `REQ-014-context.md` (dark: `bg_primary #0d1117`, `bg_secondary #161b22`, `bg_input #1c2333`, `bg_hover #252d3f`, `border #30363d`, `text_primary #e6edf3`, `text_secondary #8b949e`, `text_accent #58a6ff`, `bubble_user #1f77b4`, `bubble_agent #2d2d2d`, `success #3fb950`, `warning #d29922`, `danger #f85149`; light: `bg_primary #ffffff`, `bg_secondary #f6f8fa`, `bg_input #f0f2f5`, `bg_hover #e8eaed`, `border #d0d7de`, `text_primary #24292f`, `text_secondary #57606a`, `text_accent #0969da`, `bubble_user #d1e5ff`, `bubble_agent #e8eaed`, `success #2da44e`, `warning #bf8700`, `danger #cf222e`). Los mismos valores se declaran como CSS custom properties estáticas en `ui/webview/frontend/css/theme.css` (`:root[data-theme="dark"] { --bg-primary: #0d1117; ... }`). Un test (§8) parsea el `.css` y compara contra el dict Python para detectar drift entre ambas copias. |
| CA-36 | `ui/webview/theme.py` expone los mismos tokens que consume un test de contraste automatizado (mismo algoritmo WCAG de luminancia relativa ya usado en REQ-013, ahora contra los hex de REQ-014) — ver §8. |
| CA-37 | `set_theme(name)` en el bridge persiste (`config_manager.set_ui_theme()`) y emite `theme_changed(name)`; JS solo cambia el atributo `data-theme` del `<html>` — no hay recarga de página ni reinicio. |
| CA-38 | `ui/webview/theme.py::DEFAULT_THEME = "light"` (cambia del `"dark"` de REQ-013, ya validado en REQ-014 addendum §7) + `resolve_theme_name()` portado tal cual (mismo allowlist defensivo: cualquier valor fuera de `{"dark","light"}` cae a `DEFAULT_THEME` con warning, nunca deja pasar un string arbitrario). Se sigue leyendo/escribiendo con `config_manager.get_ui_theme()`/`set_ui_theme()` sin modificarlos. |

### Chips + seguridad

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-39 | Los 5 chips (`_CHIPS` de `ui/widgets/composer.py` hoy) se portan **con el mismo contenido literal** a `ui/webview/bridge.py` (misma lista de `{label, kind, payload}`). Los de tipo `"action"` **nunca** se resuelven en JS: `Bridge.run_chip_action(action_name)` es el único camino, y llama `execute_action(action_name, channel=ChannelType.DESKTOP, user_id="default")` vía `run_async()` — idéntico a `Composer._on_chip_clicked()` hoy, mismo `agents/action_registry.py::execute_action()` sin tocar. |
| CA-40 | Cada chip de tipo `"action"` incluye en su payload hacia JS un campo `risk_level` obtenido de `security_manager.classify_action(action_name)` (consultado en el momento, no hardcodeado) — JS pinta un punto/ícono verde/amarillo/rojo junto al chip según ese valor. Si la clasificación de una acción cambia en el futuro, el color se actualiza solo, sin tocar el frontend. |
| CA-41 | Ver §4.3 — se registra un **nuevo adaptador de confirmación** para `ChannelType.DESKTOP` (reemplaza en runtime al `_desktop_confirm` basado en consola de `main.py`, sin tocar `core/security_manager.py` ni `core/confirmation.py`) que muestra un modal en el WebView y bloquea el hilo llamador (worker de `QThreadPool`, nunca el hilo de la GUI) hasta que el usuario responde. El gate real (clasificación GREEN/YELLOW/RED, fail-closed sobre acciones sin clasificar) sigue viviendo intacto en `core/security_manager.py::require_confirmation()` — el bridge JS nunca decide por sí mismo si algo se ejecuta, solo provee la UI de la confirmación YELLOW. RED sigue con el flujo de PIN por consola (`getpass`, `security_manager.require_pin()`) sin cambios — ninguna CA de esta SPEC pide un modal para RED. |
| CA-42 | Ver §4 — `Bridge(QObject)` es la **única** superficie expuesta a JS vía `QWebChannel`. Cada método es un `@pyqtSlot` con tipos declarados explícitamente; ninguno ejecuta `eval`/código arbitrario ni importa módulos de `core/`, `intent/`, `ai/`, `skills/`, `agents/`, `voice/`, `channels/` fuera de las funciones concretas listadas en el contrato de §4 (`resolve()`, `execute_action()`, 5 funciones de `ai/memory_manager.py`, `listen_for_wake_word()`). Todo payload JSON recibido desde JS se parsea con `json.loads()` envuelto en `try/except`, se descarta con `logger.warning(...)` si es malformado — nunca se usa `eval()`/`exec()` sobre contenido de JS. |

### Integración con infraestructura existente

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-43 | `MainWindow._setup_tray_icon()` — **portado casi textual** desde `JarvisMainWindow._setup_tray_icon()` de hoy (`QSystemTrayIcon`, menú Mostrar/Ocultar + Salir, `closeEvent` que minimiza a bandeja en vez de cerrar) — es independiente del tipo de `centralWidget()`, no requiere cambios de diseño. |
| CA-44 | Ver §0.4 — `WakeWordWorker` nuevo sobre `voice/wake_word.py` sin modificarlo, con el mismo mecanismo de `stop_event`/callback. |
| CA-45 | Cero cambios a `setup_autostart.py` — sigue invocando `pythonw.exe main.py --tray`; `main.py` mantiene la variable `tray_mode` y la usa para decidir `window.show()` vs no mostrar, exactamente como hoy decide `showMaximized()` vs no. |

### Fidelidad visual

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-46 | Brief de REQ-014 aplicado como CSS real: saludo vacío `font-size: 40px; font-weight: 700;`, avatar = círculo con la inicial de `get_agent_name()` (sin emoji en ningún string de UI), input píldora (`border-radius: 22px`), paleta restringida a los tokens de `theme.css` (nunca un color hardcodeado fuera de esos custom properties), espaciado generoso (`--space-*` tokens). Verificación cualitativa la hace el humano contra las 4 referencias, como pide la SPEC — no es automatizable. |

### Regresión

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-47 | `python -m py_compile` sobre todos los `.py` nuevos/modificados de `ui/webview/`, `ai/memory_manager.py`, `main.py` — mismo comando que ya usa `orion-baseline`/`orion-tester`. |
| CA-48 | Referencia de no-regresión: **2 failed, 305 passed** con `PYTEST_QT_API=pyqt6` (documentado por `orion-baseline`). Se fija esa variable en `tests/conftest.py` (ver §6) para que `orion-tester` no confunda los 66 falsos fallos ambientales con regresiones reales. Los tests que importan módulos eliminados (`ui.theme`, `ui.widgets.*`, `ui.gui`) se reemplazan 1:1 por los nuevos listados en §8. |

---

## 2. Módulos a modificar / crear

### A eliminar (`git rm`, ya confirmado en baseline — sin cambios respecto a lo previsto)
`ui/gui.py`, `ui/theme.py`, `ui/widgets/{center_panel, chat_bubble, chat_feed, composer, conversation_list, header_bar, right_panel, system_status_card, quick_actions_card, recent_activity_card, weather_card, sidebar, voice_orb}.py` (15 archivos).

### Se conservan sin ningún cambio
`ui/cli.py`, `ui/personality.py`, `ui/tts_engine.py`, `ui/stt/transcriber.py` (prohibido), `voice/wake_word.py` (prohibido), `config_manager.py`.

### Se conserva con un cambio menor de comentario (sin lógica)
`ui/gui_workers.py` — se reutiliza **tal cual** (`run_async`, `CallableWorker`, `WorkerSignals` sin tocar una línea de código). Su docstring (línea 5-6) referencia `ui/gui.py` como dueño del polling de `GLOBAL_STATE` — se actualiza esa mención a `ui/webview/gui_state.py` para no dejar un comentario que apunte a un archivo eliminado. Es el único motivo por el que este archivo aparece en "a modificar".

### Nuevos — backend Python (`ui/webview/`)

| Archivo | Responsabilidad |
|---|---|
| `ui/webview/__init__.py` | Vacío, solo exports si hicieran falta. |
| `ui/webview/main_window.py` | `MainWindow(QMainWindow)` — shell frameless, `QWebEngineView` a pantalla completa, tray, drag&drop nativo, `fit_size_to_screen()` en construcción, registro del `Bridge` en el `QWebChannel`. |
| `ui/webview/bridge.py` | `Bridge(QObject)` — única superficie `@pyqtSlot`/`pyqtSignal` expuesta a JS. Ver contrato completo en §4. |
| `ui/webview/gui_state.py` | Estado puro `GLOBAL_STATE`/`WAKE_STATE` + `update_gui_state()`/`update_wake_state()` (ver §0.4). |
| `ui/webview/wake_word_worker.py` | `WakeWordWorker(QRunnable)` — ver §0.4. |
| `ui/webview/theme.py` | `DARK_TOKENS`/`LIGHT_TOKENS` (dicts planos `{token: hex}`), `resolve_theme_name()`, `DEFAULT_THEME = "light"`. Sin `QObject`/señales — la notificación de cambio de tema va por el bridge, no por un `pyqtSignal` interno como el `ThemeManager` de hoy. |
| `ui/webview/markdown_render.py` | `render_markdown(text: str) -> str` — `markdown` (`fenced_code`, `tables`, `codehilite`) + sanitización `bleach` con allowlist de tags/atributos. Ver §0.3 y §5.2. |
| `ui/webview/file_drop.py` | `validate_dropped_file(path: str) -> tuple[bool, str]` — allowlist de extensiones/tamaño máximo, sin dependencias nuevas (`os.path`, stdlib). |
| `ui/webview/confirmation_adapter.py` | Adaptador YELLOW basado en modal WebView + `threading.Event` (ver §4.3). |
| `ui/webview/window_geometry.py` | `fit_size_to_screen()` — función pura (ver CA-04). |
| `ui/webview/pygments_style.py` | Constante con el CSS de Pygments pre-generado para los estilos dark/light elegidos (ver §5.2) — generado una vez, no en cada arranque. |

### Nuevos — frontend estático (`ui/webview/frontend/`)

```
frontend/
  index.html
  vendor/qwebchannel.js          (copia local del archivo que ships PyQt6-WebEngine — nunca CDN)
  css/
    reset.css
    theme.css                    (custom properties dark/light — fuente #2 de verdad, ver CA-35)
    layout.css                   (grid sidebar/chat/composer)
    sidebar.css
    chat.css
    composer.css
    modal.css                    (confirmación YELLOW + confirmación de borrado)
    animations.css
    pygments-dark.css / pygments-light.css   (generados desde ui/webview/pygments_style.py)
  js/
    app.js                       (bootstrap: conecta QWebChannel, wire de listeners)
    bridge_client.js             (wrapper delgado sobre `window.bridge`, un método JS por comando del §4)
    sidebar.js
    chat.js
    composer.js
    theme.js
    confirm_modal.js
    window_chrome.js             (resize/move/min/max/close vía bridge)
  error.html                     (fallback si `loadFinished(False)`, ver §5.4)
```

### Modificados

| Archivo | Cambio |
|---|---|
| `ai/memory_manager.py` | Agrega `delete_conversation(conversation_id, user_id="default") -> bool` (CA-31). Nada más. |
| `main.py` | Línea 154: import de `update_gui_state` apunta a `ui.webview.gui_state`. Bloque `if __name__ == "__main__":` (líneas 190-202): reemplaza `from ui.gui import QApplication, JarvisMainWindow` / `JarvisMainWindow()` / `showMaximized()` por `from PyQt6.QtWidgets import QApplication` + `from ui.webview.main_window import MainWindow` + `window = MainWindow()` + `window.show()` (tamaño ya resuelto por `fit_size_to_screen()` dentro del constructor, sin maximizar — ver §5.1). Resto del archivo (loop de consola, `_desktop_confirm`, registro de triggers proactivos) **sin cambios**. |
| `requirements.txt` | Ver §3. |
| `tests/conftest.py` | Se agrega `os.environ.setdefault("PYTEST_QT_API", "pyqt6")` (una línea, fix ya probado en el stash de REQ-014, ver §6). |

---

## 3. Dependencias nuevas (`requirements.txt`)

```
# --- Interfaz gráfica WebView (REQ-015) ---
PyQt6-WebEngine
markdown
Pygments
bleach
```

- `PyQt6-WebEngine` — candidato técnico elegido (§0.1).
- `markdown` + `Pygments` — resaltado/Markdown server-side (§0.3), mismas librerías que ya estaban confirmadas para REQ-014 (nunca instaladas porque REQ-014 no llegó a commitearse).
- `bleach` — sanitización de HTML antes de insertarlo en el WebView (mitigación central de XSS, ver §5.2). No estaba en el alcance original del prompt del humano para REQ-014 porque esa versión no tenía bridge JS↔Python con superficie de riesgo equivalente — acá es una dependencia nueva, justificada por el diseño del bridge.

---

## 4. Flujo de datos — contrato exacto del bridge Python↔JS

Mecanismo: `QWebChannel` (Qt), objeto único registrado como `window.bridge` en JS (`new QWebChannel(qt.webChannelTransport, channel => window.bridge = channel.objects.bridge)`, patrón estándar documentado de PyQt6-WebEngine).

**Regla general para todo slot nuevo:** recibe únicamente tipos primitivos (`str`, `bool`, `int`) o un `str` JSON parseado con `json.loads()` dentro de un `try/except` que descarta y loguea si es inválido — nunca se confía en la forma del payload sin validar.

### 4.1 JS → Python (`@pyqtSlot` en `Bridge`)

| Comando | Firma | Efecto |
|---|---|---|
| `send_message` | `(text: str)` | Guarda `text` como pendiente, deshabilita envío (guard server-side, CA-24), `run_async(resolve, ..., text, ChannelType.DESKTOP, user_id="default")`. |
| `new_conversation` | `()` | Limpia `_conversation_id`, emite `conversation_cleared`. |
| `select_conversation` | `(conversation_id: str)` | `run_async(memory.get_conversation_turns, ...)`. |
| `request_delete_conversation` | `(conversation_id: str)` | JS ya mostró su modal de confirmación de borrado antes de llamar esto — `run_async(memory.delete_conversation, ...)`. |
| `load_more_conversations` | `(offset: int)` | `run_async(memory.list_conversations, ..., offset=offset)`. |
| `run_chip_action` | `(action_name: str)` | `run_async(execute_action, ..., action_name, channel=ChannelType.DESKTOP, user_id="default")` (CA-39). |
| `set_theme` | `(name: str)` | `resolve_theme_name(name)` + `config_manager.set_ui_theme()` + emite `theme_changed`. |
| `toggle_wake_word` | `(enabled: bool)` | Arranca/detiene `WakeWordWorker` (§0.4). |
| `confirm_response` | `(request_id: str, confirmed: bool)` | Resuelve el `threading.Event` pendiente de una confirmación YELLOW (§4.3). |
| `start_resize` | `(edge: str)` | `self.windowHandle().startSystemResize(...)` (CA-02). |
| `start_move` | `()` | `self.windowHandle().startSystemMove()` (CA-02). |
| `window_minimize` / `window_toggle_maximize` / `window_close` | `()` | Controles propios de la barra de título CSS (CA-01). `window_close` dispara el mismo `closeEvent` que minimiza a bandeja. |

### 4.2 Python → JS (`pyqtSignal` en `Bridge`, JS se suscribe una vez en `app.js`)

| Evento | Payload | Cuándo |
|---|---|---|
| `conversation_list_updated` | `json: [{conversation_id, title, last_activity, turn_count}]` | Tras `list_conversations()`/`load_more_conversations()`. |
| `conversation_cleared` | — | Tras `new_conversation()`. |
| `conversation_removed` | `conversation_id: str` | Tras un `delete_conversation()` exitoso. |
| `turns_loaded` | `json: [{id, role, html, timestamp}]` | Tras `select_conversation()` — `html` ya viene de `render_markdown()`, sanitizado. |
| `message_appended` | `json: {role, html, timestamp}` | Tras cada turno nuevo (eco del usuario + respuesta de IA), uno por uno. |
| `typing_started` / `typing_stopped` | — | Antes/después de cada `resolve()` (CA-15). |
| `gui_state_changed` | `state: str` | Cambios de `GLOBAL_STATE` detectados por el `QTimer` de polling. |
| `wake_state_changed` | `state: str` | Cambios de `WAKE_STATE`. |
| `theme_changed` | `name: str` | Tras `set_theme()`. |
| `confirmation_requested` | `request_id, action_name, message` | Cuando el nuevo adaptador YELLOW necesita mostrar un modal (§4.3). |
| `file_attached` | `path, name, accepted, reason` | Tras validar un drop nativo (§5.3). |
| `chips_loaded` | `json: [{label, kind, payload, risk_level}]` | Al arrancar (CA-39/CA-40). |
| `error_occurred` | `message: str` | JS sin capturar, o error de un `run_async` sin callback específico. |

### 4.3 Confirmación YELLOW — el punto más delicado del diseño

Hoy, `core/security_manager.py::require_confirmation()` (rama YELLOW, línea 265-282) llama de forma **síncrona y bloqueante** al adaptador registrado para el canal. En consola eso es `input()`. En una GUI con WebView no puede seguir siendo `input()` (mostraría el prompt en una consola que probablemente ni está visible) — pero tampoco puede ser una llamada síncrona directa a JS, porque JS vive en el hilo de la GUI y la respuesta del usuario llega de forma asíncrona (un clic).

Diseño: `ui/webview/confirmation_adapter.py::WebViewConfirmationAdapter`:
1. `MainWindow.__init__` construye el `Bridge`, y **recién en ese momento** (no a nivel de módulo como hace `main.py` hoy) llama `register_confirmation_adapter(ChannelType.DESKTOP, adapter.confirm)`, **sobreescribiendo** el adaptador de consola que `main.py` registró al importar (comportamiento de `register_confirmation_adapter()` confirmado en `core/confirmation.py:28-31`: siempre reemplaza). Si la construcción de `MainWindow` falla (modo headless, `main.py` línea 200-202), el adaptador de consola registrado al importar sigue siendo el activo — **sin cambio de comportamiento en headless**.
2. `adapter.confirm(action_name, message)` — se ejecuta en el **hilo worker de `QThreadPool`** que corre la acción vía `run_async(execute_action, ...)` (nunca en el hilo de la GUI, exactamente como corre hoy `require_confirmation()` dentro de `action_registry.execute_action()`). Genera un `request_id` (`uuid4`), crea un `threading.Event`, lo guarda en un dict `self._pending[request_id]`, emite `confirmation_requested(request_id, action_name, message)` (la señal SÍ se entrega de forma segura entre hilos — Qt encola la entrega en el hilo de la GUI automáticamente), y hace `event.wait(timeout=120)`.
3. JS muestra el modal y, al responder, llama `confirm_response(request_id, confirmed)` — este slot corre en el hilo de la GUI, busca `self._pending[request_id]`, guarda el resultado, y hace `event.set()`.
4. El hilo worker, desbloqueado, retorna `confirmed`. Si el `timeout` se agota (usuario cerró la ventana sin responder, o un bug en JS), retorna `False` (fail-closed, nunca `True` por defecto).
5. El gate de clasificación de riesgo (`RiskLevel`, fail-closed sobre acciones sin registrar) **no se toca** — sigue viviendo entero en `core/security_manager.py`. Este adaptador solo reemplaza el mecanismo de UI de la confirmación YELLOW, nunca decide si algo requiere confirmación.

---

## 5. Notas de diseño detalladas

### 5.1 Por qué CA-03/CA-05 quedan estructuralmente cerrados y por qué CA-04 NO es automático (honestidad para el humano)

El handoff pidió explicar por qué estos 3 bugs no se repiten — la respuesta honesta no es uniforme para los 3:

- **Bug #1 (bleed-through, CA-03) — sí queda cerrado por construcción.** La causa raíz documentada fue un `QWidget` plano que necesitaba el flag `WA_StyledBackground` para que Qt decidiera pintar su `background-color` de QSS — un flag *opt-in* fácil de olvidar en cualquiera de los ~15 widgets de la jerarquía anterior. En esta arquitectura, el árbol de widgets Qt visible se reduce a **uno solo**: la ventana top-level frameless con un único `QWebEngineView` a pantalla completa. Dentro del WebView, el modelo de caja CSS pinta el `background-color` de *todo* elemento por defecto — no existe un equivalente a "olvidarse de activar el pintado de fondo" en CSS. No hay ningún otro `QWidget` con estilo propio en el medio que pueda repetir el bug.
- **Bug #3 (input invisible, CA-05) — mitigado, no matemáticamente imposible.** La causa no fue diagnosticada en su momento (era un fallo de selector/cascada QSS distinto del bug #1). En CSS, el input declara `border`/`background`/`::placeholder` en una única regla no sobreescrita en cascada por objectName como hoy — reduce la clase de bug (cascada QSS multi-archivo) pero un bug distinto (una clase JS que oculte el elemento, una regla CSS con mayor especificidad mal escrita) sigue siendo posible en teoría. Por eso se agrega el test automatizado de `getComputedStyle()` en §8 como red de seguridad de regresión, no como sustituto de la inspección visual real que pide CA-05.
- **Bug #2 (ventana excede pantalla, CA-04) — NO es una consecuencia de cambiar a WebView.** La causa fue aritmética de geometría de ventana Qt (`setMinimumSize`/`showMaximized`/cálculo de tamaño frameless) sin clamp contra `availableGeometry()` — un bug en el **shell Qt que envuelve el contenido**, completamente independiente de si el contenido es `QWidget` o `QWebEngineView`. El WebView no toca ni sabe nada de la geometría de la ventana top-level. La mitigación real es la misma que ya se probó y funcionó en REQ-014: una función pura y testeada (`fit_size_to_screen()`) que clampea siempre contra el área de trabajo disponible, llamada antes de `show()`. Se decide además **no usar `showMaximized()`** (a diferencia de hoy) — una ventana frameless maximizada tiene sus propios problemas conocidos de composición en Windows (DWM añade márgenes extra en maximizado+frameless que hay que compensar manualmente) — evitar maximizado por defecto es una simplificación deliberada que reduce aún más el riesgo de este bug específico, no solo lo parchea.

### 5.2 Sanitización de Markdown → HTML (mitigación central de XSS)

`render_markdown(text)`:
1. `markdown.markdown(text, extensions=["fenced_code", "tables", "codehilite"], extension_configs={"codehilite": {"guess_lang": False}})` → HTML con clases `.codehilite`/tokens de Pygments.
2. `bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, protocols=["http", "https"], strip=True)` — `ALLOWED_TAGS` cubre exactamente lo que pide CA-13 (`p, br, strong, em, b, i, ul, ol, li, code, pre, span, div, table, thead, tbody, tr, th, td, a, blockquote, h1-h6`), `ALLOWED_ATTRS` limitado a `class` (para los tokens de Pygments) y `href` (solo `http`/`https`, nunca `javascript:` — `bleach` bloquea esquemas fuera de `protocols` por diseño).
3. Resultado va directo a `element.innerHTML` en JS — JS **nunca** parsea Markdown ni sanitiza, solo inserta HTML ya confiable.

`guess_lang=False` es deliberado: sin esto, `codehilite` intenta adivinar el lenguaje de bloques sin fence explícito, lo que puede producir resultados erráticos; forzar que solo bloques con \`\`\`lang tengan resaltado es más predecible y más fácil de testear.

Estilos de Pygments: se generan **una sola vez** (no en cada arranque) vía `pygments.formatters.HtmlFormatter(style="monokai").get_style_defs(".codehilite")` para dark y `HtmlFormatter(style="default").get_style_defs(".codehilite")` para light, y se commitean como CSS estático (`pygments-dark.css`/`pygments-light.css`, cargados condicionalmente según `data-theme`). `orion-dev` genera estos dos archivos una vez con un script chico y los deja como assets estáticos — no hay generación de CSS en runtime.

### 5.3 Drag & drop de archivos (CA-23) — por qué no se resuelve con la API `File` del navegador

Chromium (y por lo tanto `QWebEngineView`) **no expone la ruta absoluta del sistema de archivos** de un objeto `File` soltado vía la API web estándar (`file.path` no es parte del estándar `File`, es una extensión no estándar de Electron que QtWebEngine no implementa) — es una restricción de seguridad del propio motor de navegador, no evitable desde JS. Por eso el drop se captura **a nivel de `QMainWindow`**: `setAcceptDrops(True)` + `dragEnterEvent`/`dropEvent` sobre la ventana, con un `eventFilter` instalado sobre el `QWebEngineView` para asegurar que el evento nativo llegue al `MainWindow` antes de que Chromium intente manejarlo internamente (a verificar empíricamente por `orion-dev` — comportamiento exacto documentado como riesgo en §7). `QDropEvent.mimeData().urls()` sí entrega rutas absolutas reales (`QUrl.toLocalFile()`), que `ui/webview/file_drop.py::validate_dropped_file()` valida contra una allowlist de extensiones antes de aceptar. El resultado (aceptado/rechazado + motivo) se empuja a JS vía `file_attached` para actualizar el composer.

### 5.4 Degradación si el WebView falla al cargar

`MainWindow` conecta `web_view.loadFinished(bool ok)`: si `ok=False`, carga `error.html` (asset local estático, sin JS que pueda fallar en cascada) con un botón "Reintentar" (recarga `index.html`) — nunca deja la ventana en blanco. `web_view.page().renderProcessTerminated` (el proceso de renderizado de Chromium es un proceso separado del proceso Python — un crash ahí **no puede tumbar el proceso Python**) se conecta a un handler que loguea y ofrece recargar. Errores de JS no capturados se capturan vía `page().javaScriptConsoleMessage` override (logueo, no acción).

---

## 6. `tests/conftest.py`

Se agrega la línea ya probada en el stash de REQ-014, en el mismo lugar donde hoy se fija `QT_QPA_PLATFORM`:
```python
os.environ.setdefault("PYTEST_QT_API", "pyqt6")
```
Corrige el conflicto `PyQt6`/`PySide6` documentado por `orion-baseline` (66 fallos falsos → 2 fallos reales ambientales). Sin este fix, `orion-tester` no podría distinguir una regresión real de REQ-015 de este ruido de entorno.

---

## 7. Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| Chromium embebido (~150-200MB) infla el tamaño de instalación | Aceptado explícitamente en §0.1 — costo de disco único, no de ejecución; empaquetado (PyInstaller) sigue fuera de alcance en este REQ. |
| Bridge JS→Python es superficie nueva de seguridad | Contrato cerrado y tipado (§4.1), cada slot valida su input, ningún slot ejecuta código arbitrario ni importa módulos fuera de la lista explícita del §4. Recomendado pase de `orion-security` antes de `orion-dev` (ver §9). |
| XSS vía contenido Markdown de la IA insertado como HTML | Sanitización server-side con `bleach` + allowlist estricta (§5.2) antes de que el HTML exista en JS — nunca se inserta HTML sin sanitizar. |
| Confirmación YELLOW (nuevo mecanismo, reemplaza `input()`) podría quedar mal cableada y volverse fail-open | Diseño explícito fail-closed: timeout de 120s retorna `False`, no `True`; el gate de clasificación de riesgo no se toca, solo la UI de la confirmación. Test dedicado en §8 verifica ambos caminos (confirmar / timeout). |
| `MainWindow` sobreescribe el adaptador de confirmación DESKTOP registrado por `main.py` — si la GUI se cae después de registrar pero el hilo worker ya esperaba respuesta, podría quedar colgado | `event.wait(timeout=120)` acota el bloqueo incluso si la ventana se cierra sin responder — nunca cuelga indefinidamente. |
| Interceptar el drop nativo antes de que Chromium lo consuma internamente (§5.3) no está garantizado por documentación oficial — riesgo de que el evento no llegue a `dropEvent` de `QMainWindow` | Riesgo técnico explícito a validar empíricamente por `orion-dev` en la implementación; si el `eventFilter` no alcanza, alternativa de respaldo: deshabilitar el drag&drop nativo de `QWebEngineSettings` (`DragDropEnabled=False`) para forzar que todo drop llegue al padre. |
| `voice/wake_word.py`'s fallback `from ui.gui import update_gui_state` (solo alcanzable en CLI headless pura + wake word, sin GUI) dejará de encontrar el módulo tras el `git rm` | Alcance del efecto: cero. Esa rama solo se ejecuta cuando `wake_state_callback is None`, y `ui/cli.py` ya oculta la opción de wake word cuando hay GUI activa — ya está envuelta en `try/except: pass`. Nada lee `GLOBAL_STATE` sin una GUI activa. Documentado como efecto secundario aceptado, no un bug nuevo. |
| Repetir el patrón de REQ-014 (suite headless en verde, bug real solo en prueba manual) si la nueva suite tampoco cubre renderizado real | Ver §8 — smoke tests con `QWebEngineView` offscreen sobre CA-03/CA-05 como red de regresión automatizada, **sin reemplazar** la inspección visual real en Windows que las 3 CA de no-regresión exigen explícitamente. |
| `QWebEngineView` offscreen en CI/Windows puede ser lento o inestable (dependiente de GPU/sandbox del entorno) | Los smoke tests de §8 que instancian `QWebEngineView` real se marcan aparte (`@pytest.mark.webview_smoke` o similar) para que `orion-tester` pueda correrlos por separado y no bloqueen el resto de la suite si el entorno no los soporta bien — a decidir/confirmar en la fase de dev/test. |

---

## 8. Pruebas sugeridas (una por criterio relevante, agrupadas por archivo)

| Archivo de test | Cubre | Notas |
|---|---|---|
| `tests/test_memory_manager_delete_conversation.py` | CA-31 | DB temporal (monkeypatch `DB_PATH`), casos: borra filas propias, no borra de otro `user_id`, retorna `False` sobre id inexistente/vacío, no lanza excepción. |
| `tests/test_webview_gui_state.py` | CA-44 (base) | Funciones puras `update_gui_state`/`update_wake_state`, sin Qt. |
| `tests/test_webview_theme.py` | CA-35, CA-38 | `resolve_theme_name()` allowlist (mismo patrón que REQ-013); test de drift que parsea `theme.css` y compara valores contra `DARK_TOKENS`/`LIGHT_TOKENS`. |
| `tests/test_webview_contrast.py` | CA-36 | Reemplaza `tests/test_theme.py` — mismo algoritmo WCAG de luminancia relativa, ahora contra los hex de REQ-014. |
| `tests/test_webview_markdown_render.py` | CA-13 | Casos: negrita/cursiva/listas/tablas/código con lenguaje, y **casos adversariales**: `<script>alert(1)</script>`, `<img onerror=alert(1)>`, `[link](javascript:alert(1))` — deben salir sanitizados/neutralizados. |
| `tests/test_webview_file_drop.py` | CA-23 | Extensión permitida/no permitida, tamaño límite, ruta inexistente. |
| `tests/test_webview_window_geometry.py` | CA-04 | `fit_size_to_screen()` puro: pantalla normal, pantalla menor al mínimo, distintos factores de escala — mismo espíritu que el fix ya validado en el stash de REQ-014, ahora testeado desde cero acá. |
| `tests/test_webview_confirmation_adapter.py` | CA-41 | `pytest-qt`: confirmar responde `True`/`False` correctamente vía `confirm_response()` simulado desde otro hilo; timeout retorna `False` (fail-closed) sin `confirm_response()`. |
| `tests/test_webview_bridge.py` | CA-07..CA-11, CA-20..CA-25, CA-39, CA-40, CA-42 | `pytest-qt` instanciando `Bridge` (QObject headless, sin `QWebEngineView` real) con `memory`/`execute_action`/`resolve` mockeados — verifica que cada slot llama exactamente a la función esperada con los parámetros esperados, que `run_chip_action` nunca ejecuta la acción directo (siempre vía `execute_action`), y que payloads JSON malformados se descartan sin excepción. |
| `tests/test_webview_smoke.py` | CA-03, CA-05, CA-42 (integración) | `QWebEngineView` real en modo offscreen (`QT_QPA_PLATFORM=offscreen` ya fijado): carga `index.html`, espera `loadFinished`, y vía `page().runJavaScript()` verifica `getComputedStyle(document.body).backgroundColor` no transparente en ambos temas (CA-03) y que el input tiene borde/fondo/placeholder no vacíos (CA-05). Marcado aparte para no bloquear el resto de la suite si el entorno de CI no soporta bien `QWebEngineView` offscreen (ver riesgo en §7). |
| Tests existentes eliminados | — | `tests/test_theme.py` (reemplazado por `test_webview_theme.py`/`test_webview_contrast.py`), `tests/test_gui_widgets.py` (importa `ui/widgets/*` eliminados) — `orion-dev` confirma la lista exacta contra lo que realmente falla al compilar tras el `git rm`. |
| Tests existentes sin cambios | — | `tests/test_gui_workers.py` (módulo no tocado), `tests/test_config_manager_ui_theme.py` (testea `config_manager.py`, no tocado). |

Verificación cualitativa no automatizable (a cargo del humano, según pide explícitamente la SPEC): CA-03, CA-04, CA-05 (inspección visual real en Windows, con especial atención a un factor de escala distinto de 100%) y CA-46 (fidelidad visual contra las 4 referencias).

---

## 9. Recomendación de siguiente paso

Este REQ introduce superficie de seguridad genuinamente nueva respecto a REQ-013/REQ-014 (ambos 🟢 Verde completo): un bridge JS↔Python invocable desde contenido web, un mecanismo de confirmación YELLOW nuevo que reemplaza `input()` por un modal + bloqueo entre hilos, y lectura de rutas de archivo del sistema operativo desde un evento de drop. Se recomienda que **`orion-security` audite esta arquitectura antes de `orion-dev`** — en particular el contrato del bridge (§4.1), la sanitización de Markdown (§5.2) y el diseño de la confirmación YELLOW (§4.3) — en vez de dejarlo para la auditoría estándar de `orion-qa` al final del ciclo.

---

⚠️ El flujo no continúa hasta que apruebes esta arquitectura.
Responde: **APROBADO** / **AJUSTAR [qué]** / **RECHAZADO [motivo]**

---

## 10. Ajustes de seguridad post-auditoría (2026-08-19) — respuesta a `security-audit-015.md`

**Motivo:** `orion-security` auditó esta arquitectura (`pruebas/security-audit-015.md`, veredicto
❌ REQUIERE CAMBIOS) y devolvió 2 hallazgos bloqueantes (A y C) más 1 no bloqueante (B, ya asignado
directo a `orion-dev`, sin acción de arquitectura requerida). No se reescribe nada de lo ya aprobado
en §0-§9 — esta sección es una extensión, mismo patrón que el addendum §7 de `arquitectura-014.md`.

Leído completo antes de proponer: `pruebas/security-audit-015.md` íntegro, `REQ-015-context.md`
(sección "Riesgos activos", actualizada por `orion-security`), y el código real de
`core/security_manager.py` (`RiskLevel`, `require_confirmation()` líneas 232-294,
`_register_default_actions()` líneas 300-329/374, `format_details()` líneas 89-106) y
`agents/action_registry.py::execute_action()` (líneas 277-289) — para confirmar contra el código,
no asumir, tanto el patrón exacto de registro de acciones YELLOW como el punto de entrada único que
ya usa el resto del sistema.

Ninguna de las 4 decisiones técnicas centrales (§0.1-§0.4) ni el diseño general del bridge se
reabren — son 2 ajustes acotados, tal como calificó la propia auditoría.

### 10.1 Hallazgo A (bloqueante) — Regla general de inserción segura en el DOM

**Ampliación de §4 (no reemplaza el contrato de datos de §4.1/§4.2, que no cambia — agrega una
regla de consumo del lado JS sobre los mismos campos ya definidos):**

> **Regla general para todo consumidor JS de eventos del bridge:** cualquier campo recibido desde
> Python que NO esté explícitamente documentado en §4.2 como `html` (ya sanitizado por
> `render_markdown()` + `bleach`, ver §5.2) se inserta en el DOM **exclusivamente** vía
> `element.textContent = valor` (contenido de texto) o `element.setAttribute(nombre, valor)`
> (atributos) — **nunca** `innerHTML`, `insertAdjacentHTML`, ni interpolación en un template string
> que luego se asigna a `innerHTML`. Sin excepciones.

Puntos concretos donde esta regla aplica (los 3 archivos JS identificados por `orion-security` como
no cubiertos por sanitización server-side — ya estaban planificados en la lista de §2, esto es una
restricción de implementación sobre ellos, no un archivo nuevo):

- **`js/sidebar.js`** — al recibir `conversation_list_updated` (§4.2), el título de cada ítem
  (`title`, derivado de los primeros 30 caracteres del primer mensaje del usuario — CA-08, texto no
  confiable) se asigna con `titleElement.textContent = conv.title` sobre un nodo dedicado (p. ej.
  `<span class="conv-title">` creado con `document.createElement`), nunca interpolado en una
  plantilla de string que luego se asigne a `innerHTML` del `<li>` completo. El resto de la fila
  (ícono de borrar, fecha relativa) se construye como nodos DOM separados, no como HTML del título.
- **`js/composer.js`** — al recibir `file_attached` (§4.2), el nombre del archivo (`name`, tomado
  de `QDropEvent.mimeData().urls()` — puede no ser texto que el propio usuario escribió, señalado
  explícitamente por `orion-security` como el caso más peligroso de los tres, ver Hallazgo A del
  audit) se asigna al chip de adjunto con `chipNameElement.textContent = payload.name`, mismo
  criterio que el título — nunca `innerHTML` del chip completo.
- **`js/confirm_modal.js`** — al recibir `confirmation_requested` (§4.2), tanto `action_name` como
  `message` (que incluye `details`, construido con `format_details()` a partir de `params` de un
  intent parseado por NLP — no garantizado 100% de confianza) se asignan con `.textContent` sobre
  los nodos del modal (título de la pregunta, cuerpo del mensaje) — el modal deja de construir su
  HTML interpolando estos valores en un string.

`js/chat.js` queda explícitamente fuera de esta regla para el campo `html` de `turns_loaded`/
`message_appended` — ese campo sigue siendo el único insertado vía `innerHTML`, porque ya viene
sanitizado server-side (§5.2, sin cambios).

**Prueba adversarial nueva (extiende §8):**

| Archivo de test | Cubre | Notas |
|---|---|---|
| `tests/test_webview_safe_dom_insertion.py` (nuevo) | Hallazgo A — capa 1, estática | Grep estructural sobre el código fuente de `ui/webview/frontend/js/{sidebar,composer,confirm_modal}.js`: falla si aparece `.innerHTML` o `insertAdjacentHTML` en cualquiera de los 3 archivos (a diferencia de `chat.js`, ninguno de los 3 necesita insertar HTML real). No sustituye la prueba runtime siguiente — un grep no detecta, por ejemplo, un `textContent` correcto combinado con un atributo `href` mal filtrado en un `<a>` creado dinámicamente — pero sí detecta con certeza el vector principal señalado por la auditoría. |
| `tests/test_webview_smoke.py` (extiende el ya planificado en §8) | Hallazgo A — capa 2, runtime real | Caso nuevo `test_conversation_title_xss_does_not_execute` (y sus 2 análogos para `file_attached.name` y `confirmation_requested.message`/`action_name`): con `QWebEngineView` offscreen (misma infraestructura que CA-03/CA-05), se dispara desde Python el evento correspondiente del bridge con el campo igual a `"<img src=x onerror=window.__xss_fired=true>"`, se espera a que el DOM se actualice, y vía `page().runJavaScript(...)` se verifica (1) que `window.__xss_fired` sigue `undefined`/falsy, y (2) que el nodo de destino (`.conv-title` / chip del composer / cuerpo del modal) tiene `textContent` igual al string literal completo, incluidos los caracteres `<`/`>` sin interpretar — confirma que se insertó como texto plano, no como HTML ejecutado. |

**Recomendación no bloqueante ya presente en la auditoría (CSP, ítem 4 de "Recomendaciones" de
`security-audit-015.md`):** queda fuera del alcance de este ajuste — no es requisito para pasar a
`orion-dev`. `orion-dev` puede incorporar un `<meta http-equiv="Content-Security-Policy">` a
`index.html` como defensa en profundidad adicional si el tiempo lo permite, sin que afecte la
aprobación de esta arquitectura.

### 10.2 Hallazgo C (bloqueante) — `delete_conversation()` reclasificada a `RiskLevel.YELLOW`

**Confirmado contra el código real (no asumido) el patrón de registro de acciones YELLOW:**
`core/security_manager.py::_register_default_actions()` (líneas 300-329, invocada a nivel de módulo
en la línea 374) registra cada acción con `sm.register_action(nombre, RiskLevel)` — p. ej.
`sm.register_action("delete_file", RiskLevel.YELLOW)`, `sm.register_action("delete_folder",
RiskLevel.YELLOW)` (líneas 305-306), `sm.register_action("send_message", RiskLevel.YELLOW)` (línea
311). Se agrega una línea nueva al mismo bloque YELLOW:

```python
sm.register_action("delete_conversation", RiskLevel.YELLOW)
```

**Cambia el diseño de `Bridge.request_delete_conversation(conversation_id: str)` — reemplaza la
descripción de §4.1, fila `request_delete_conversation` (ya no aplica "JS ya mostró su modal de
confirmación de borrado antes de llamar esto"):**

1. El slot despacha, vía `run_async()` (mismo `QThreadPool` worker que el resto de comandos que
   tocan `memory`/`execute_action` — nunca el hilo de la GUI, porque el paso 2 puede bloquear hasta
   120s), un callable que ejecuta los pasos 2-5.
2. Llama `security_manager.require_confirmation("delete_conversation", ChannelType.DESKTOP,
   details=format_details("webview:delete_conversation", {"name": conversation_id}),
   user_id="default")` — el mismo punto de entrada único (`core/security_manager.py:232`) que ya
   usa `agents/action_registry.py::execute_action()` (línea 283) para el resto de acciones
   amarillas, sin bifurcar en un segundo gate. Como el nivel es YELLOW y el canal es `DESKTOP`
   (permitido según `CHANNEL_ALLOWED_LEVELS`), esto invoca `get_confirmation_adapter(
   ChannelType.DESKTOP)` — el `WebViewConfirmationAdapter` ya construido y registrado en
   `MainWindow.__init__` para CA-41 (§4.3), **sin registrar un segundo adaptador**: emite
   `confirmation_requested(request_id, "delete_conversation", message)` y bloquea el hilo worker con
   `threading.Event(timeout=120)`, fail-closed idéntico a cualquier otra acción amarilla.
3. `confirm_modal.js` (mismo modal genérico de CA-41, ver también §10.1 para su regla de inserción
   segura) muestra la pregunta — deja de existir cualquier modal/lógica de confirmación específica
   de borrado en JS.
4. Si `require_confirmation()` retorna `False` (cancelado por el usuario, canal no permitido, o
   timeout): se retorna sin llamar a `memory.delete_conversation()` y sin emitir ningún evento — la
   conversación permanece en la lista tal como está, mismo resultado observable que "cancelar" en el
   modal anterior.
5. Si retorna `True`: se llama `memory.delete_conversation(conversation_id, user_id="default")`
   (CA-31, sin cambios de firma ni comportamiento) y, solo si el resultado es `True`, se emite
   `conversation_removed(conversation_id)` (§4.2, evento sin cambios de forma).

**Nota sobre `details` — por qué se usa la clave `"name"` y no `conversation_id` tal cual:**
`format_details()` (`core/security_manager.py:89-106`) solo produce texto para las claves listadas
en `_DETAILS_ALLOWED_KEYS` (`app_name, app, task, raw_text, skill_name, name, path, filename,
folder, query, url, direction` — líneas 79-82); `conversation_id` no es una de ellas. Pasar
`{"conversation_id": conversation_id}` tal cual produciría silenciosamente solo el prefijo
(`"webview:delete_conversation"`, sin identificar cuál conversación) tanto en el mensaje del modal
como en el log de auditoría — un bug de trazabilidad silencioso, no un error visible. Se usa
deliberadamente la clave genérica `"name"` (ya reservada para identificar el objetivo de una acción)
para que tanto el mensaje que ve el humano como `_log_audit()` incluyan el id real de la conversación
a borrar. Este valor pasa por la regla de §10.1 igual que cualquier otro campo del modal (`message`
se inserta vía `textContent`), así que no reabre el Hallazgo A.

**Trazabilidad (cierra la brecha señalada por `orion-security`):** cada intento de borrado —
confirmado, cancelado, bloqueado por canal, bloqueado por falta de adaptador, o timeout— queda
registrado por `_log_audit()` (`core/security_manager.py:136`), exactamente igual que
`delete_file`/`delete_folder`/cualquier otra acción amarilla del sistema. Antes de este ajuste, un
borrado de conversación no dejaba ningún rastro en el log de auditoría.

**Actualización de la tabla de CA-10 (§1) — el siguiente texto reemplaza la descripción de esa fila,
sin reabrir el resto de la tabla:**

> CA-10 | Confirmación vía `security_manager.require_confirmation()`, con `delete_conversation`
> registrada como `RiskLevel.YELLOW` (ver §10.2) — reutiliza el mismo `WebViewConfirmationAdapter`/
> modal genérico que CA-41, ya no un modal JS con lógica propia de borrado. Al confirmar,
> `Bridge.request_delete_conversation(conversation_id)` llama `memory.delete_conversation(
> conversation_id, user_id="default")` (CA-31) vía `run_async()` — si `True`, evento
> `conversation_removed(conversation_id)` saca el ítem del DOM sin recargar todo el listado.
> Reemplaza la descripción original de §1 ("Confirmación a nivel UI... mismo criterio ya aceptado en
> REQ-013/REQ-014") — ese criterio ya no aplica, ver `security-audit-015.md` Hallazgo C.

**Actualización de §4.1 (tabla JS→Python) — el siguiente texto reemplaza la fila
`request_delete_conversation`:**

> `request_delete_conversation` | `(conversation_id: str)` | Ya NO asume que JS mostró su propio
> modal — dispara internamente el flujo de confirmación YELLOW descrito en §10.2 (pasos 1-5) antes
> de tocar `memory.delete_conversation()`.

### 10.3 Referencia cruzada — Hallazgo B (no bloqueante, sin cambios de arquitectura)

`orion-security` documentó directamente para `orion-dev` (sin necesidad de pasar por
`orion-architect`) la limpieza de `self._pending[request_id]` tras resolución y el manejo defensivo
de un `request_id` desconocido en `confirmation_adapter.py::confirm_response()` — ver
`security-audit-015.md` sección "Hallazgo B" y §4.3 de esta arquitectura (diseño base, sin cambios).
Con el ajuste de §10.2, ese mismo comportamiento (limpieza + manejo defensivo) también debe cubrir
las solicitudes generadas por `delete_conversation`, porque ahora comparten el mismo `self._pending`
que CA-41 — no es una responsabilidad separada, es la misma pieza ya señalada por el hallazgo, ahora
con un segundo emisor de solicitudes.

### 10.4 Riesgos y mitigación (addendum)

| # | Riesgo | Mitigación |
|---|--------|-----------|
| 21 | La regla de §10.1 (`textContent`/`setAttribute`, nunca `innerHTML`) depende de que `orion-dev` la respete al escribir `sidebar.js`/`composer.js`/`confirm_modal.js` por primera vez — no hay código previo que migrar, así que el riesgo es de omisión, no de regresión. | Prueba estructural (`test_webview_safe_dom_insertion.py`, grep de `.innerHTML`/`insertAdjacentHTML`) + prueba runtime adversarial (`test_webview_smoke.py`) en §10.1 — ambas bloquean la suite si la regla no se respeta, no dependen de que `orion-dev` se acuerde de aplicarla sin verificación. |
| 22 | `require_confirmation()` para `delete_conversation` puede bloquear el hilo worker hasta 120s (§10.2, paso 2) — si `Bridge.request_delete_conversation()` no se despacha vía `run_async()` y en cambio corre en el hilo de la GUI, la ventana quedaría congelada. | Mismo patrón ya validado para CA-41/`execute_action()` (siempre en `QThreadPool`, nunca en el hilo de la GUI) — explícito en el paso 1 de §10.2, no es un mecanismo nuevo a inventar. |
| 23 | La clave `"name"` en `format_details({"name": conversation_id})` (§10.2) es una reutilización de una clave genérica ya usada para otros objetivos (p. ej. `delete_skill`) — riesgo de ambigüedad si un log de auditoría mezcla borrados de conversación con otras acciones que también usan `"name"`. | Aceptado: `_log_audit()` ya registra `action_name` (`"delete_conversation"`) en su propia columna — el prefijo `"webview:delete_conversation"` de `format_details()` más esa columna dejan la fila del log inequívoca sin necesitar una clave nueva en `_DETAILS_ALLOWED_KEYS`. |

### 10.5 Qué NO cambia

Las 4 decisiones técnicas centrales (§0.1-§0.4), el resto del contrato del bridge (§4.1/§4.2, salvo
la única fila `request_delete_conversation` de §10.2), la sanitización de Markdown (§5.2 — sigue
siendo el único campo insertado vía `innerHTML`, ya sanitizado), el mecanismo de confirmación YELLOW
en sí (§4.3 — sin cambios de diseño, solo un segundo emisor de solicitudes), y el resto de las 48 CA
de la SPEC no mencionadas acá. Este ajuste es puntual: una regla de inserción segura en el DOM
(Hallazgo A) + reclasificación de una acción a un gate ya existente en el diseño (Hallazgo C).

---

## Resumen para el humano — AJUSTES DE SEGURIDAD (§10)

- **Hallazgo A (bloqueante):** regla explícita nueva — todo campo del bridge que no sea `html`
  pre-sanitizado se inserta en el DOM solo con `textContent`/`setAttribute`, nunca `innerHTML`.
  Aplica a título de conversación (`sidebar.js`), nombre de archivo soltado (`composer.js`) y
  mensaje/acción del modal de confirmación (`confirm_modal.js`). Pruebas nuevas: un grep estructural
  (`test_webview_safe_dom_insertion.py`) + 3 casos runtime reales con `QWebEngineView` offscreen que
  confirman que un título malicioso (`<img src=x onerror=...>`) no ejecuta nada al renderizarse.
- **Hallazgo C (bloqueante):** `delete_conversation` pasa a ser una acción `RiskLevel.YELLOW`
  registrada en `core/security_manager.py` (mismo patrón verificado contra el código real que
  `delete_file`/`delete_folder`). `Bridge.request_delete_conversation()` ahora pasa por
  `security_manager.require_confirmation()`, reutilizando el mismo `WebViewConfirmationAdapter`/
  modal ya construido para CA-41 — no se inventa un segundo mecanismo. Además, el borrado queda con
  trazabilidad en el log de auditoría, algo que no tenía antes.
- **Hallazgo B (no bloqueante):** sin cambios de arquitectura — ya documentado directo para
  `orion-dev` por `orion-security`; se deja una referencia cruzada notando que ahora también cubre
  las solicitudes de `delete_conversation`.
- Ninguna de las 4 decisiones técnicas centrales ni el resto del diseño del bridge cambian.

⚠️ El flujo no continúa hasta que apruebes este ajuste.
Responde: **APROBADO** / **AJUSTAR [qué]** / **RECHAZADO [motivo]**
