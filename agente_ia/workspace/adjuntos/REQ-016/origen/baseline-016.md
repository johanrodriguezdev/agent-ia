# Baseline REQ-016

**Agente:** orion-baseline
**Fecha:** 2026-08-20
**Rama git verificada:** `feature/REQ-015-webview-ui` (sigue siendo la rama activa del working
tree; REQ-016 no tiene rama propia todavía — pendiente de decisión del humano, igual que registró
`orion-spec` en el contexto).

## Nota de working tree — precedencia sobre REQ-015

Se verificó `git status --short` de forma independiente antes de tocar nada:
- El diff completo de REQ-015 (migración `ui/gui.py` + `ui/widgets/*` → `ui/webview/`) sigue sin
  commitear: 12 archivos `D` (widgets/gui/theme viejos), varios `M` (`main.py`,
  `ai/memory_manager.py`, `core/security_manager.py`, `ui/gui_workers.py`, `tests/conftest.py`,
  `tests/test_autostart.py`, `tests/test_main.py`, `requerimientos.csv`, `requirements.txt`,
  `tasks/tasks.db`), y `ui/webview/` completo + varios `tests/test_webview_*.py` sin trackear (`??`).
- Esto confirma exactamente lo que ya documentó `baseline-015.md`: no hay nada que "revertir" ni
  reconciliar — es el mismo estado de REQ-015 EN_QA, sin cambios de otra sesión encima. El punto de
  partida real de REQ-016 **es** el diff no commiteado de REQ-015, no un `main`/`HEAD` limpio.
- Consecuencia práctica: todo lo que este baseline describe como "estado actual" ya incluye la capa
  visual/funcional de REQ-015 (WebView, bridge, sidebar de conversaciones), no el estado anterior a
  REQ-015. Los archivos que REQ-016 tocará son en su mayoría los mismos que REQ-015 dejó modificados
  sin commitear — coordinar con Johan el orden de commits antes de mezclar diffs (ya señalado como
  riesgo activo en el contexto).

## Estado actual del sistema

### Backend de tareas — confirmado independientemente (no se asumió el hallazgo de orion-spec)

`tasks/task_manager.py` — clase `TaskManager`, instancia global `task_manager` (línea 579).
Firmas confirmadas leyendo el archivo completo:
- `create_task(self, user_id, title, channel="telegram", description="", due_date=None, remind_at=None, recurrence=None, priority="normal") -> int` (línea 300) — `channel` es un `str` libre, sin validación de valores permitidos, así que `channel="desktop"` ya funciona hoy sin tocar la función.
- `list_all_tasks(self, user_id, limit=15) -> list[dict]` (línea 372) — `ORDER BY CASE WHEN status='pending' THEN 0 ELSE 1 END, due_date ASC` (pendientes primero, luego por fecha) ya implementado en SQL, tal como asume CA-09 de la SPEC.
- `complete_task(self, task_id, user_id) -> bool` (línea 403) — `UPDATE ... WHERE id=? AND user_id=?`, retorna `bool` según `rowcount`.
- `delete_task(self, task_id, user_id) -> bool` (línea 416) — `DELETE ... WHERE id=? AND user_id=?`, retorna `bool`.
- Las 4 funciones existen con las firmas que la SPEC asume. Ninguna requiere modificación para CA-06..CA-09.

`tasks/task_scheduler.py` — clase `TaskScheduler`, instancia global `task_scheduler` (línea 207).
- `start()` (línea 48): arranca un hilo `daemon=True` que corre `_run_loop()`, revisa cada 60s (`CHECK_INTERVAL`). Idempotente (`if self._running: return`).
- `_send_notification()` (línea 111): confirmado en el código — línea 151, `if channel == "desktop" or channel == "telegram": self._notify_local(title, task_id)`. La rama `"desktop"` ya existe y ya dispara `_notify_local()` (TTS vía `ui/tts_engine.speak()` + Toast nativo de Windows vía PowerShell), sin necesidad de tocar este archivo.
- Ninguna de las dos funciones necesita modificarse para que CA-10 funcione — solo falta que algo llame `task_scheduler.start()`.

**Gap de arranque confirmado de forma independiente (no se confió en el hallazgo de `orion-spec`):**
- `grep "task_scheduler|proactive_engine" main.py` → solo aparecen matches de `proactive_engine`
  (import línea 36, `proactive_engine.start()` en línea 104 dentro de `main()`, `proactive_engine.stop()`
  en línea 117). **Cero matches de `task_scheduler` en todo `main.py`.**
- `grep "task_scheduler|proactive_engine" ui/webview/main_window.py` → **cero matches de ambos.**
  `MainWindow.__init__()` no arranca ni el proactive engine ni el scheduler de tareas — depende
  enteramente de que `main.py::main()` los arranque antes de instanciar la ventana.
- `grep -r "task_scheduler" .` en todo el proyecto (excluyendo `workspace/adjuntos/`) → solo dos
  archivos: `tasks/task_scheduler.py` (la propia definición) y `channels/telegram_bot.py` líneas
  834-836 (`task_scheduler.set_telegram_app(app); task_scheduler.start()`, dentro del arranque del
  bot de Telegram).
- Confirmado: **`task_scheduler.start()` NO se llama desde ningún camino de arranque de la app de
  escritorio** (ni `main.py`, ni `ui/webview/main_window.py`). Es exclusivo del bot de Telegram. El
  hallazgo de `orion-spec` (base de CA-10) es correcto, verificado de forma independiente leyendo
  el código, no solo confiando en el reporte.
- `main.py::main()` (línea 100) es el único punto de entrada real: instancia `CLI`, llama
  `proactive_engine.start()` (línea 104), y más abajo (línea ~221-224, dentro del branch GUI) crea
  `QApplication` + `MainWindow`. Es decir: el mismo lugar donde ya vive `proactive_engine.start()`
  es el punto natural para agregar `task_scheduler.start()` (coincide con lo que la SPEC ya
  específica como ubicación, "línea ~104").

### Memoria/conversaciones — confirmado independientemente para no romper CA-21

`ai/memory_manager.py` — clase `UnifiedMemory` (singleton), instancia global `memory`, DB en
`ai/unified_memory.db`, tabla única `memories` (sin tabla de proyectos, carpetas ni tags). Funciones
que CA-21 exige no romper, confirmadas leyendo el archivo completo:
- `new_conversation_id()` (línea 179, `@staticmethod`) — `uuid.uuid4().hex`, sin persistencia hasta
  el primer `store()`.
- `store_turn(self, user_text, assistant_text, conversation_id, user_id="default", matched_by="", importance=0.5) -> None` (línea 222) — escribe 2 filas (`role="user"`/`role="assistant"`, `category="interaction"`) vía `store()`. Calcula embeddings, no debe llamarse desde el hilo de GUI (ya lo respeta `run_async()` en el bridge).
- `list_conversations(self, user_id="default", limit=30, offset=0) -> List[ConversationSummary]` (línea 254) — 1 query agregada por `conversation_id`, filtra `archived=0 AND conversation_id IS NOT NULL`.
- `get_conversation_turns(self, conversation_id, user_id="default", limit=200) -> List[MemoryItem]` (línea 293) — ordena por `id ASC` (no timestamp).
- `delete_conversation(self, conversation_id, user_id="default") -> bool` (línea 502) — `DELETE FROM memories WHERE conversation_id=? AND user_id=?` (hard delete real, no soft-delete), retorna `bool` según `rowcount`, dispara `_load_embeddings()` si borró algo. **Importante para el diseño de `orion-architect`:** si el esquema nuevo de "proyectos" guarda una referencia a `conversation_id`, esta función no la conoce ni la limpia — el diseño de proyectos debe encargarse explícitamente de que borrar una conversación no deje referencias huérfanas en la tabla de proyectos (exigido literal por CA-21).
- Las 5 funciones existen tal cual las asume la SPEC. No hay ningún campo ni tabla de "proyecto" hoy — el único candidato parecido es `category` en `memories` (valores `general`/`interaction`/`summary`), que es una clasificación de memoria semántica, no un agrupador de conversaciones (confirmado, coincide con el hallazgo de `orion-spec`).

### Seguridad — confirmado

`core/security_manager.py::_register_default_actions()` (línea 300): `delete_conversation` ya está
registrada como `RiskLevel.YELLOW` (línea 311). `delete_task` y `delete_project` **no existen
todavía** en el registro — confirmado por grep, ningún match de ninguna de las dos cadenas en el
archivo. `CHANNEL_ALLOWED_LEVELS[ChannelType.DESKTOP] = [GREEN, YELLOW]` (línea 55) ya permite
YELLOW en el canal desktop, así que registrar las 2 acciones nuevas como YELLOW es suficiente sin
tocar la matriz de canales.

### Bridge — confirmado el patrón de whitelisting y confirmación

`ui/webview/bridge.py` — docstring del módulo (líneas 1-27) ya enumera explícitamente las 5
funciones de `memory_manager` que usa y advierte que ningún slot debe importar módulos fuera de esa
lista concreta — el patrón a replicar para los slots nuevos de tareas/proyectos. El flujo de
confirmación ya existe y es reutilizable: `request_delete_conversation()` (línea 241, `@pyqtSlot(str)`)
despacha vía `run_async()` a `_delete_conversation_flow()` (línea 248), que llama
`security_manager.require_confirmation("delete_conversation", ChannelType.DESKTOP, details=..., user_id="default")`
antes de tocar `memory.delete_conversation()`. Mismo patrón exacto a replicar para
`delete_task`/`delete_project`.

### Frontend — confirmado

- `ui/webview/frontend/index.html` línea 5-6: CSP confirmada tal cual la reportó `orion-spec`:
  `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self';`
  — sin `font-src`, cae en `default-src 'self'`. No existe carpeta `fonts/` (confirmado por `Glob`
  sobre todo `ui/webview/frontend/**/*` — no aparece ningún `.woff2` ni carpeta `fonts/`).
- `css/reset.css` línea 18: `font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;` en `body` — confirmado, es el único lugar donde se define la tipografía general hoy.
- `css/sidebar.css`: `#sidebar.collapsed` (líneas 17-19) reduce a 60px y oculta `.label`,
  `#conversation-list`, `#sidebar-footer`, `.sidebar-load-more` (líneas 21-26) — confirmado el rango
  de líneas que reportó `orion-spec`. **No hay ninguna regla que centre los íconos cuando el sidebar
  está colapsado** (`.sidebar-action-btn` no tiene una variante `.collapsed` — confirma el gap de
  CA-22). Tampoco hay atributo `title` en los botones existentes del sidebar en `index.html` (ni
  `#new-conversation-btn` ni `#sidebar-collapse-toggle` lo tienen) — confirma el gap de CA-23.
- `index.html`: header actual del sidebar = `#sidebar-header` (logo + botón `«` de colapso,
  líneas 38-41) + `#new-conversation-btn` como botón `.sidebar-action-btn` de ancho completo
  **separado**, debajo del header (líneas 42-45) — confirmado, coincide exactamente con la columna
  "Actual" de la tabla comportamiento actual/deseado de la SPEC. No existe ningún control de
  búsqueda, ni overflow menu, ni entradas de "Tareas"/"Proyectos".
- `.sidebar-action-btn` (css/sidebar.css línea 59-76) es el estilo reutilizable que el ASUMIDO de
  la SPEC propone para los 2 botones nuevos — confirmado que existe y es el único patrón de botón de
  acción ya usado en el sidebar (`#new-conversation-btn`, `#load-more-btn`).

## Archivos que serán modificados (previsión)

Basado en la sección "Módulos afectados" de SPEC-016.md, ya verificada contra el código real:

- `ui/webview/frontend/index.html` — nuevo header en píldora (colapso + búsqueda + nuevo chat),
  entradas "Tareas"/"Proyectos", posible `<link rel="preload">`/`@font-face` de Inter.
- `ui/webview/frontend/css/sidebar.css` — píldora del header, estados hover/activo de los 3
  controles, centrado de íconos en colapsado (gap CA-22 confirmado), estilos de las 2 secciones
  nuevas.
- `ui/webview/frontend/css/theme.css` — posibles tokens nuevos de color para la píldora/acento.
- `ui/webview/frontend/css/reset.css` — `font-family` del `body` pasa a Inter con el fallback actual.
- `ui/webview/frontend/js/sidebar.js` — lógica de búsqueda (filtro cliente), apertura de paneles de
  Tareas/Proyectos, tooltips nativos.
- `ui/webview/frontend/js/app.js` — posible wiring de nuevas señales del bridge.
- `ui/webview/frontend/fonts/` (carpeta nueva) — `.woff2` de Inter (400/500/700), no existe hoy.
- `ui/webview/bridge.py` — nuevos `pyqtSlot`/`pyqtSignal` para tareas y proyectos, agregados al
  docstring de whitelisting (líneas 1-27), reusando el patrón de `request_delete_conversation()`/
  `_delete_conversation_flow()` (líneas 241-268).
- `ai/memory_manager.py` — nuevo modelo de datos de "proyectos" (diseño a cargo de
  `orion-architect`); no debe tocar el comportamiento de las 5 funciones confirmadas arriba
  (`new_conversation_id`, `store_turn`, `list_conversations`, `get_conversation_turns`,
  `delete_conversation`).
- `main.py` — agregar `task_scheduler.start()` junto a `proactive_engine.start()` (línea 104),
  gap confirmado de forma independiente arriba.
- `core/security_manager.py::_register_default_actions()` (línea ~300-322) — agregar
  `sm.register_action("delete_task", RiskLevel.YELLOW)` y
  `sm.register_action("delete_project", RiskLevel.YELLOW)`.
- `tasks/task_manager.py`, `tasks/task_scheduler.py` — **confirmado sin necesidad de modificar**
  (ver verificación arriba); se mantienen como dice la SPEC.
- Tests nuevos: slots de tareas/proyectos del bridge, esquema nuevo de proyectos, no-regresión del
  sidebar de conversaciones (equivalentes a los que ya existen para REQ-015:
  `tests/test_webview_bridge.py`, `tests/test_memory_manager_delete_conversation.py`, etc. — mismo
  patrón de archivo por área).

## Fallos pre-existentes (no atribuibles a este REQ)

Ejecutado `python -m pytest tests/ --tb=short -q` sobre el working tree tal cual está hoy (con el
diff de REQ-015 sin commitear encima):

```
2 failed, 365 passed, 11 warnings in 43.89s
```

- `tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` — FAIL,
  `ModuleNotFoundError: No module named 'anthropic'`.
- `tests/test_llm_provider.py::test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto` — FAIL,
  mismo `ModuleNotFoundError: No module named 'anthropic'`.
- Causa: dependencia del SDK `anthropic` no instalada en el entorno actual (falta en
  `requirements.txt` o no instalada en el venv activo) — no relacionado con UI, sidebar, tareas,
  proyectos, memoria ni seguridad. No toca ningún archivo que este REQ vaya a modificar.
- Ambos fallos son pre-existentes al REQ-016 y no deben atribuirse al trabajo de este flujo.

`python -m py_compile` sobre los módulos Python que la SPEC lista como afectados
(`main.py`, `ai/memory_manager.py`, `core/security_manager.py`, `tasks/task_manager.py`,
`tasks/task_scheduler.py`, `ui/webview/bridge.py`, `ui/webview/main_window.py`) — sin errores,
compilan limpio tal como están hoy.

`tests/conftest.py` línea 38: `os.environ.setdefault("PYTEST_QT_API", "pyqt6")` — confirmado que el
fix documentado en `baseline-015.md` sigue aplicado en disco, no se perdió entre sesiones.

## Riesgos activos identificados en esta sesión

- Working tree compartido con el diff de REQ-015 sin commitear (mismo riesgo ya registrado en el
  contexto) — cualquier `git diff`/`git status` durante REQ-016 va a mezclar ambos REQs hasta que
  Johan decida el orden de commits.
- El esquema nuevo de "proyectos" en `ai/memory_manager.py` debe manejar explícitamente la limpieza
  de referencias cuando `delete_conversation()` borra una conversación que pertenece a un proyecto
  — `delete_conversation()` no lo hace por sí sola (confirmado arriba), así que si `orion-architect`
  no lo diseña explícitamente, CA-21 (segunda mitad: "sin dejar referencias huérfanas") queda roto.
- Los 2 fallos pre-existentes de `test_llm_provider.py` (`ModuleNotFoundError: anthropic`) seguirán
  apareciendo en la corrida de `orion-tester` — deben documentarse como ya presentes, no como
  regresión introducida por REQ-016.
