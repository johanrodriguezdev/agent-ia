# Baseline REQ-014 — Rediseño completo desde cero UI escritorio NODDOO

**Agente:** orion-baseline
**Fecha:** 2026-08-18
**HEAD verificado:** `eb190b3` ("Fix mejora interfaz visual Agente IA"), working tree limpio
(`git status --short` sin salida salvo `requerimientos.csv` modificado por el tracker y la
carpeta nueva `workspace/adjuntos/REQ-014/`). `stash@{0}` presente y NO aplicado — confirmado con
`git stash list`, no se tocó.

## ⚠️ Advertencia — este NO es un baseline de código limpio

El commit `eb190b3` ya contiene **committeada en `main`** la 1ra pasada completa de REQ-013 (no
solo resguardada en el stash). Este documento describe el estado REAL de HEAD hoy, que es el
punto de partida real de REQ-014, tal como pidió el handoff. El stash `stash@{0}` (2da-3ra-4ta-5ta
pasada de refinamiento de REQ-013 — fix contraste CA-03, fix condición de carrera del composer,
panel derecho colapsable, tema claro por defecto) es historial descartado, documentado abajo solo
como referencia — **no aplicado, no debe aplicarse**.

## Estado actual del sistema (HEAD `eb190b3`)

### `ui/` — inventario completo
```
ui/__init__.py
ui/cli.py
ui/gui.py                          390 líneas — JarvisMainWindow (QMainWindow)
ui/gui_workers.py                  CallableWorker (QThread) — usado por wake word y comandos
ui/personality.py
ui/theme.py                        240 líneas — Palette, ThemeManager(QObject), qss_tokens(),
                                    resolve_theme_name(), register_themed()  [NUEVO en eb190b3]
ui/tts_engine.py
ui/stt/__init__.py
ui/stt/transcriber.py
ui/widgets/__init__.py
ui/widgets/center_panel.py         197 líneas — CenterPanel (saludo, empty state, wake toggle)
ui/widgets/chat_bubble.py           56 líneas — ChatBubble                    [NUEVO en eb190b3]
ui/widgets/chat_feed.py            155 líneas — ChatFeed (autoscroll condicional) [NUEVO]
ui/widgets/composer.py             268 líneas — Composer (input, chips, wake toggle) [NUEVO]
ui/widgets/conversation_list.py    167 líneas — ConversationList (sidebar historial) [NUEVO]
ui/widgets/header_bar.py           148 líneas — HeaderBar
ui/widgets/quick_actions_card.py    94 líneas — RightPanel: accesos rápidos
ui/widgets/recent_activity_card.py 102 líneas — RightPanel: actividad reciente
ui/widgets/right_panel.py           86 líneas — RightPanel (contenedor de las 4 tarjetas)
ui/widgets/sidebar.py              134 líneas — Sidebar (nav Inicio/Conversaciones/Memoria/...)
ui/widgets/system_status_card.py   154 líneas — RightPanel: estado del sistema
ui/widgets/voice_orb.py            130 líneas — indicador visual de voz (estado vacío)
ui/widgets/weather_card.py          99 líneas — RightPanel: clima
```
Total `ui/`: 2420 líneas en `ui/widgets/` + `ui/gui.py` (390) + `ui/theme.py` (240).

`git show --name-status eb190b3 -- ui/` confirma con precisión qué es NUEVO (`A`) y qué es
MODIFICACIÓN sobre código preexistente (`M`) dentro del mismo commit:
- **Nuevos (A):** `ui/theme.py`, `ui/widgets/chat_bubble.py`, `chat_feed.py`, `composer.py`,
  `conversation_list.py`.
- **Modificados sobre código anterior a REQ-013 (M):** `ui/gui.py`, `ui/widgets/center_panel.py`,
  `header_bar.py`, `quick_actions_card.py`, `recent_activity_card.py`, `right_panel.py`,
  `sidebar.py`, `system_status_card.py`, `voice_orb.py`, `weather_card.py`.

`ui/widgets/sidebar.py` y `ui/widgets/right_panel.py` (+ sus 4 tarjetas) **preexistían a REQ-013**
y solo recibieron ajustes — dato relevante porque SPEC-014 no los lista explícitamente entre "se
elimina/reescribe", y `sidebar.py` en particular queda ambiguo entre el `Sidebar` actual (nav
lateral con ítems Inicio/Conversaciones/Memoria/Tareas/Archivos/Aplicaciones/Configuración) y el
nuevo `ui/sidebar.py` que propone la arquitectura de archivos del prompt del humano (colapsable
260↔60px con listado de conversaciones). Son conceptualmente distintos aunque compartan nombre de
archivo — a resolver explícitamente en `orion-architect`.

### API de `ai/memory_manager.py` (313 líneas agregadas en `eb190b3`, ya committeadas)
Clase `MemoryManager` (singleton `__new__`), funciones relevantes para REQ-014 ya existentes y
**a consumir sin modificar** (salvo CA-30):
- `MemoryManager.new_conversation_id() -> str` (`@staticmethod`) — `uuid.uuid4().hex`.
- `store_turn(self, user_text, assistant_text, conversation_id, user_id="default", matched_by="", importance=0.5) -> None`
  — persiste 2 filas (`role="user"` / `role="assistant"`, `category="interaction"`). Calcula
  embeddings → **debe llamarse fuera del hilo de GUI** (ya lo hace `ui/gui.py` vía `run_async()`).
- `list_conversations(self, user_id="default", limit=30, offset=0) -> List[ConversationSummary]`
  — 1 query agregada, ya pagina (`LIMIT`/`OFFSET`), excluye filas con `conversation_id IS NULL`
  (legacy/otros canales).
- `get_conversation_turns(self, conversation_id, user_id="default", limit=200) -> List[MemoryItem]`
  — orden cronológico por `id ASC`, acota a los últimos N turnos.
- `store(...)` de bajo nivel — acepta `conversation_id`/`role` opcionales (ambos `None` por
  default, no rompe callers previos).
- **No existe** `delete_conversation()` / `remove_conversation()` / `rename_conversation()` —
  verificado con `grep -n "^def \|^    def " ai/memory_manager.py` sobre las 23 funciones/métodos
  del archivo. Confirma el hallazgo de `orion-spec`: es la única función nueva autorizada por
  SPEC-014 (CA-30/CA-31).

### `config_manager.py`
`get_ui_theme()` (línea 122) y `set_ui_theme()` (línea 134) ya existen — SPEC-014 los reutiliza
tal cual para persistir la preferencia de tema (CA-37).

### `main.py` — confirmación de acciones amarillas/rojas
`_desktop_confirm(action_name, message)` (líneas 20-26) es un `input()` de consola bloqueante,
registrado vía `register_confirmation_adapter(ChannelType.DESKTOP, _desktop_confirm)` en import
time. Confirma el "Asumido" de SPEC-014: si `orion-architect` decide exponer una acción
no-GREEN desde un chip nuevo de la UI, este adaptador no es viable desde un hilo de Qt y
requeriría reemplazo — hoy no es un requisito activo porque los chips heredados de REQ-013
(CA-39) son todos GREEN.

## Archivos que serán modificados (previsión, según SPEC-014 §Módulos afectados)

**Se eliminan (reemplazados por la nueva arquitectura de archivos):**
- `ui/gui.py` → `ui/main_window.py`
- `ui/widgets/chat_bubble.py`, `chat_feed.py` → `ui/chat_area.py`, `ui/message_bubble.py`,
  `ui/typing_indicator.py`
- `ui/widgets/composer.py` → `ui/input_bar.py`
- `ui/widgets/conversation_list.py` → `ui/sidebar.py` (nuevo, con historial funcional)
- `ui/widgets/center_panel.py`, `header_bar.py` → absorbidos/redistribuidos en
  `ui/main_window.py`/`ui/chat_area.py` (división exacta a confirmar en `orion-architect`)

**Se reescribe por completo (mismo nombre, contenido nuevo):**
- `ui/theme.py` — nuevas paletas (hex del contexto) + `ThemeManager` nuevo; el actual
  (`Palette`/`ThemeManager`/`qss_tokens`/`resolve_theme_name`/`register_themed`, 240 líneas de
  `eb190b3`) se descarta íntegramente.

**Se conservan, solo ajuste de estilos/QSS:**
- `ui/widgets/right_panel.py`, `system_status_card.py`, `quick_actions_card.py`,
  `recent_activity_card.py`, `weather_card.py` (86+154+94+102+99 = 535 líneas que NO se tocan
  estructuralmente).

**A decidir en `orion-architect` (no resuelto por SPEC-014):**
- `ui/widgets/voice_orb.py` (130 líneas, estado vacío) — conservar o retirar.
- `ui/widgets/sidebar.py` (134 líneas, nav lateral preexistente) — su relación con el nuevo
  `ui/sidebar.py` propuesto (mismo nombre de archivo, propósito distinto/superpuesto) necesita
  resolución explícita: ¿se fusiona, se renombra el nav actual, o el nuevo `sidebar.py`
  reemplaza directamente su contenido absorbiendo la navegación?
- Footer de configuración/perfil del nuevo sidebar — alcance funcional sin definir (placeholder
  probable).

**Se modifica puntualmente (excepción acotada):**
- `ai/memory_manager.py` — agregar únicamente `delete_conversation(conversation_id, user_id="default")`
  (CA-30). Las 313 líneas restantes (esquema + 4 funciones de historial) no se tocan.
- `main.py` — candidato condicional, solo si `orion-architect` agrega una acción no-GREEN nueva
  desde un chip (ver arriba). No es un requisito activo hoy.
- `requirements.txt` — agregar `markdown`, `Pygments`.

**Tests que se reescriben/crean (arquitectura de archivos nueva invalida los actuales):**
`tests/test_gui_widgets.py` (435 líneas de REQ-013), `tests/test_chat_widgets.py` (364 líneas,
100% nuevo de REQ-013), `tests/test_theme.py` (268 líneas, 100% nuevo), `tests/test_wake_word_gui.py`,
`tests/test_config_manager_ui_theme.py`, `tests/test_conversation_memory.py` (284 líneas, cubre
`store_turn`/`list_conversations`/`get_conversation_turns` — probablemente se mantiene en gran
parte ya que esa API no cambia, solo se le agregan tests de `delete_conversation()`).

## Referencia histórica — `stash@{0}` (NO aplicado, NO usado en REQ-014)
`git stash show -p stash@{0}` (2da-3ra-4ta-5ta pasada de REQ-013, ~1968 líneas de diff sobre
`eb190b3`) contiene: fix de contraste CA-03 (2 hex de `text_disabled`/`accent` en `ui/theme.py`),
fix de condición de carrera de `set_input_enabled` en `ui/widgets/composer.py`, panel derecho
colapsable, tema claro por defecto, y actualizaciones de los docs de `workspace/adjuntos/REQ-013/`.
Queda documentado como antecedente de bugs ya encontrados y corregidos (ver "Riesgos activos" en
el contexto — no-regresión, especialmente la condición de carrera del input, CA-23 de SPEC-014).
No se aplica ni se referencia como código a reutilizar.

## Fallos pre-existentes (no atribuibles a REQ-014)

Suite completa ejecutada sobre HEAD `eb190b3` tal cual, sin el stash aplicado:
`cd agente_ia && python -m pytest tests/ --tb=short -q`

### Ejecución tal cual (sin variables de entorno especiales)
**66 failed, 241 passed** — a primera vista parece mucho más que los "2 fallos ambientales"
anticipados en el handoff, pero **64 de los 66 son un único problema de entorno, no de código**:

1. **2 fallos — falta el paquete `anthropic`** (los anticipados en el handoff, siguen siendo los
   mismos):
   - `tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse`
   - `tests/test_llm_provider.py::test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto`
   - Causa: `ModuleNotFoundError: No module named 'anthropic'` — paquete no instalado en este
     entorno. No relacionado con UI/REQ-014.

2. **64 fallos — ambigüedad de binding Qt entre `PyQt6` y `PySide6` en `pytest-qt`** (hallazgo
   NUEVO de este baseline, no mencionado en el handoff):
   - Afecta TODOS los tests que instancian un widget real y lo pasan a `qtbot.addWidget(...)`:
     los 8 tests de `tests/test_chat_widgets.py`, 36 de `tests/test_gui_widgets.py`, 10 de
     `tests/test_wake_word_gui.py`, y más.
   - Síntoma: `TypeError: Need to pass a QWidget to addWidget: <ui.widgets.sidebar.Sidebar ...>`.
   - Causa raíz confirmada: el entorno tiene **tanto `PyQt6` como `PySide6` instalados**
     (`PySide6` no se usa en ningún módulo del proyecto ni figura en `requirements.txt` — es un
     paquete huérfano). `pytest-qt` (v4.5.0) auto-detecta el binding a usar para el fixture
     `qtbot` y, sin configuración explícita, elige `PySide6`; el código de producción
     (`ui/gui.py`, `ui/widgets/*.py`) importa y construye widgets con `PyQt6`. El `isinstance()`
     interno de `qtbot.addWidget()` compara contra la clase `QWidget` de `PySide6`, que no es la
     misma clase que la de `PyQt6` → falla siempre.
   - **Workaround verificado:** fijar la variable de entorno `PYTEST_QT_API=pyqt6` antes de
     correr pytest resuelve el 100% de estos 64 fallos:
     `PYTEST_QT_API=pyqt6 python -m pytest tests/ --tb=line -q` → **2 failed, 305 passed** (solo
     quedan los 2 de `anthropic`, coincide exactamente con lo que anticipaba el handoff).
   - Esto NO está fijado hoy en ningún lado del repo: no hay `pytest.ini`/`pyproject.toml`/
     `setup.cfg`, y `tests/conftest.py` solo fija `QT_QPA_PLATFORM=offscreen` (línea 31), no
     `PYTEST_QT_API`.
   - **Riesgo activo para el resto del pipeline de REQ-014**: si `orion-tester`/`orion-dev`
     corren `pytest` sin `PYTEST_QT_API=pyqt6` seteado, van a ver decenas de fallos falsos en
     widgets que sí funcionan, y podrían confundirlos con regresiones reales introducidas por
     REQ-014. Se traslada este hallazgo a "Riesgos activos" del contexto para que el resto del
     flujo lo tenga presente. **orion-baseline no lo corrige** (no le corresponde — ver DoD), solo
     lo documenta.

### Conteo de referencia para `orion-tester` (CA-43 de SPEC-014)
Baseline real de pre-existentes, **corriendo con `PYTEST_QT_API=pyqt6` fijado**:
**2 failed, 305 passed** (los 2 de `anthropic`, ambientales, no atribuibles a REQ-014).
Sin ese fix de entorno, el número de referencia sería incorrectamente 66 failed / 241 passed.

## `python -m py_compile` — módulos relevantes

```
python -m py_compile ui/gui.py ui/theme.py ui/gui_workers.py ui/cli.py ui/personality.py \
  ui/tts_engine.py ui/widgets/center_panel.py ui/widgets/chat_bubble.py ui/widgets/chat_feed.py \
  ui/widgets/composer.py ui/widgets/conversation_list.py ui/widgets/header_bar.py \
  ui/widgets/right_panel.py ui/widgets/sidebar.py ui/widgets/system_status_card.py \
  ui/widgets/quick_actions_card.py ui/widgets/recent_activity_card.py ui/widgets/weather_card.py \
  ui/widgets/voice_orb.py ai/memory_manager.py config_manager.py main.py
```
Resultado: **sin errores** — todos los módulos listados compilan limpio en HEAD `eb190b3`.

## Resumen para `orion-architect`
- Punto de partida: HEAD `eb190b3`, no working tree sucio — el reemplazo de `ui/` requiere
  `git rm`/reescritura de contenido trackeado, confirmado.
- 2 fallos pre-existentes reales, ambientales (`anthropic` no instalado) — no bloquean, no se
  corrigen en REQ-014.
- 1 riesgo de entorno nuevo y no trivial: `PYTEST_QT_API=pyqt6` debe fijarse (recomendado: en
  `tests/conftest.py`, junto a `QT_QPA_PLATFORM`) para que la suite de tests de UI sea confiable
  durante todo REQ-014 — se dejó como riesgo activo en el contexto, no corregido acá porque
  excede el alcance de `orion-baseline` (no es un fallo atribuible al código, y tocar
  `tests/conftest.py` es una decisión de arquitectura/dev, no de baseline).
- Ambigüedad sin resolver: `ui/widgets/sidebar.py` (nav lateral preexistente) vs. el nuevo
  `ui/sidebar.py` (historial de conversaciones colapsable) — mismo nombre de archivo propuesto,
  propósito distinto. Necesita decisión explícita en la propuesta de arquitectura.
