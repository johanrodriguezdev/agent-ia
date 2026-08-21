# Baseline REQ-015 — Migrar panel de escritorio NODDOO a WebView (HTML/CSS/JS)

**Rama:** `feature/REQ-015-webview-ui` — **HEAD verificado:** `eb190b3` (confirmado con
`git branch --show-current` + `git log -1 --oneline` en esta sesión, coincide con lo indicado en el
handoff de `orion-spec`).

## Estado actual del sistema

El working tree de `feature/REQ-015-webview-ui` en `eb190b3` es, verificado directamente (no
asumido), la **arquitectura de REQ-013**, no la de REQ-014. Ningún commit de REQ-014 llegó a `main`
ni a esta rama.

### `ui/` en disco hoy (arquitectura REQ-013, `QWidget` + QSS)
```
ui/__init__.py
ui/cli.py
ui/gui.py                          ← ventana principal (QMainWindow, JarvisMainWindow)
ui/gui_workers.py
ui/personality.py
ui/theme.py                        ← DEFAULT_THEME = "dark" (confirmado línea 160)
ui/tts_engine.py
ui/stt/__init__.py
ui/stt/transcriber.py              ← módulo prohibido de tocar (SPEC-015)
ui/widgets/__init__.py
ui/widgets/center_panel.py
ui/widgets/chat_bubble.py
ui/widgets/chat_feed.py
ui/widgets/composer.py
ui/widgets/conversation_list.py
ui/widgets/header_bar.py
ui/widgets/right_panel.py          ← + 4 tarjetas (panel derecho, a eliminar sin migrar)
ui/widgets/system_status_card.py
ui/widgets/quick_actions_card.py
ui/widgets/recent_activity_card.py
ui/widgets/weather_card.py
ui/widgets/sidebar.py              ← nav lateral SIN historial de conversaciones colapsable
ui/widgets/voice_orb.py
```
`main.py` instancia esta UI hoy vía `from ui.gui import QApplication, JarvisMainWindow` (línea 192)
y `window = JarvisMainWindow()` (línea 194); también importa `ui.cli.CLI`, `ui.personality`, y usa
`from ui.gui import update_gui_state` para reflejar estado (wake word, etc.) en la GUI (línea 154).
Este es el punto de instanciación que `orion-architect` tendrá que reemplazar por el WebView.

### `ai/memory_manager.py` en disco hoy
Confirmado con `grep -n "def "` sobre el archivo real (no el del stash):
- `new_conversation_id()` — presente (línea 179)
- `store_turn()` — presente (línea 222)
- `list_conversations()` — presente (línea 254)
- `get_conversation_turns()` — presente (línea 293)
- `delete_conversation()` — **AUSENTE**. `grep -n "def delete_conversation" ai/memory_manager.py`
  devuelve exit code 1 (sin coincidencias). Confirma exactamente lo que reportaron `orion-spec` y el
  handoff: la función no existe en el working tree actual, solo en `stash@{0}`.

### `config_manager.py` / `ui/theme.py`
`get_ui_theme()` (línea 122) y `set_ui_theme()` (línea 134) ya existen en `config_manager.py` — se
consumen sin modificar, tal como indica la SPEC. `ui/theme.py` fija `DEFAULT_THEME = "dark"` (línea
160) — el REQ-015 debe cambiarlo a claro por defecto (CA-38), heredando la decisión ya validada en
REQ-014 addendum §7.

### `requirements.txt` en disco hoy
No incluye `markdown` ni `Pygments` (dependencias que REQ-014 agregó para resaltado de código
server-side) — confirmado con diff contra la versión del stash. Tampoco incluye ninguna dependencia
de WebView (`PyQt6-WebEngine` / `pywebview`), como es esperable en un REQ nuevo.

## Archivos que serán modificados / eliminados (previsión, según SPEC-015 §"Módulos afectados")

**A eliminar por completo (`git rm` de contenido trackeado — arquitectura REQ-013):**
- `ui/gui.py`
- `ui/theme.py`
- `ui/widgets/center_panel.py`
- `ui/widgets/chat_bubble.py`
- `ui/widgets/chat_feed.py`
- `ui/widgets/composer.py`
- `ui/widgets/conversation_list.py`
- `ui/widgets/header_bar.py`
- `ui/widgets/right_panel.py`
- `ui/widgets/system_status_card.py`
- `ui/widgets/quick_actions_card.py`
- `ui/widgets/recent_activity_card.py`
- `ui/widgets/weather_card.py`
- `ui/widgets/sidebar.py`
- `ui/widgets/voice_orb.py`

(13 archivos de `ui/widgets/` + `ui/gui.py` + `ui/theme.py` = 15 archivos trackeados a eliminar,
todos confirmados presentes en disco en esta sesión.)

**No se tocan (explícitamente fuera de alcance / prohibidos):** `ui/cli.py`, `ui/personality.py`,
`ui/tts_engine.py`, `ui/gui_workers.py`, `ui/stt/transcriber.py`, `voice/wake_word.py`.
`orion-architect` deberá confirmar en su propuesta si `ui/gui_workers.py` sigue siendo necesario
según el candidato técnico elegido (no está en la lista de `git rm` de la SPEC, pero tampoco se
menciona su rol en la arquitectura nueva).

**A crear (arquitectura completamente nueva, sin archivos previos en disco a reutilizar):** backend
Python del WebView + assets HTML/CSS/JS — estructura exacta a definir por `orion-architect`.

**A modificar (excepción acotada):**
- `ai/memory_manager.py` — únicamente agregar `delete_conversation(conversation_id, user_id="default")`.
  El resto de la API no se toca (CA-30).
- `main.py` — reemplazar la instanciación de `JarvisMainWindow` (línea 194) por el WebView nuevo.
- `requirements.txt` — agregar la dependencia del candidato técnico (`PyQt6-WebEngine` o
  `pywebview`) y, si aplica, `markdown`/`Pygments`.
- `tests/conftest.py` — candidato a fijar `PYTEST_QT_API=pyqt6` (ver "Riesgos" abajo), decisión de
  arquitectura/dev, no de baseline.

## Fallos pre-existentes (no atribuibles a este REQ)

Suite completa ejecutada en el estado actual de `feature/REQ-015-webview-ui` (`eb190b3`), sin aplicar
el stash, con `PYTEST_QT_API=pyqt6` fijado manualmente (mitigación documentada en `baseline-014.md`
para el conflicto de `isinstance()` entre PyQt6 y PySide6 dentro de `qtbot.addWidget()` — ver
"Riesgos" abajo, esta variable **no** está fijada en `tests/conftest.py` de esta rama):

```
PYTEST_QT_API=pyqt6 python -m pytest tests/ --tb=line -q
→ 2 failed, 305 passed, 11 warnings in 17.48s
```

Los 2 fallos:
- `tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse`
- `tests/test_llm_provider.py::test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto`

Ambos con `ModuleNotFoundError: No module named 'anthropic'` (el paquete `anthropic` está comentado
como dependencia opcional en `requirements.txt`, no instalado en este entorno) — **ambientales, no
atribuibles a REQ-015**. Coincide exactamente con el conteo de referencia ya documentado en
`baseline-014.md` para el mismo HEAD (`eb190b3`): "2 failed, 305 passed" con la variable fijada.

Este número (**2 failed, 305 passed** con `PYTEST_QT_API=pyqt6`) es el que `orion-tester` debe usar
como referencia de no-regresión para CA-48.

### Verificación adicional del riesgo de entorno (confirmado, no solo heredado del contexto)
Corriendo la misma suite **sin** `PYTEST_QT_API=pyqt6`:
```
python -m pytest tests/ --tb=no -q
→ 66 failed, 241 passed, 11 warnings in 18.49s
```
Confirma en esta sesión, sobre esta rama, exactamente el mismo patrón que documentó
`baseline-014.md` (mismo conteo: 66 failed / 241 passed sin el fix, 2 failed / 305 passed con él).
El entorno de esta sesión tiene tanto `PyQt6==6.11.0` como `PySide6==6.11.1` instalados
simultáneamente (`pip show`), que es la condición exacta que dispara el conflicto de `isinstance()`
en `qtbot.addWidget()` descrito en `baseline-014.md`.

**Confirmado:** `tests/conftest.py` en esta rama (`feature/REQ-015-webview-ui`) fija
`QT_QPA_PLATFORM=offscreen` (línea 31, mitigación de REQ-008) pero **NO** fija `PYTEST_QT_API` — el
fix que sí llegó a fijarse en `tests/conftest.py` durante REQ-014 (`os.environ.setdefault
("PYTEST_QT_API", "pyqt6")`, confirmado con `git show stash@{0}:agente_ia/tests/conftest.py`) vive
solo en `stash@{0}`, no en disco. Como anticipaba el handoff: al venir esta rama de REQ-013/`main` y
no de REQ-014, esa mitigación no está presente. Se traslada como riesgo activo (ver abajo) — no lo
corrige `orion-baseline`, es decisión de `orion-architect`/`orion-dev` si se vuelve a fijar en
`tests/conftest.py`.

## `python -m py_compile` — módulos relevantes

```
python -m py_compile ui/gui.py ui/theme.py ui/gui_workers.py ui/cli.py ui/personality.py \
  ui/tts_engine.py ui/widgets/center_panel.py ui/widgets/chat_bubble.py ui/widgets/chat_feed.py \
  ui/widgets/composer.py ui/widgets/conversation_list.py ui/widgets/header_bar.py \
  ui/widgets/right_panel.py ui/widgets/sidebar.py ui/widgets/system_status_card.py \
  ui/widgets/quick_actions_card.py ui/widgets/recent_activity_card.py ui/widgets/weather_card.py \
  ui/widgets/voice_orb.py ai/memory_manager.py config_manager.py main.py
```
Resultado: **exit 0, sin errores** — todos los módulos listados compilan limpio en HEAD `eb190b3`
de esta rama.

## Referencia disponible en `stash@{0}` (NO aplicado — solo consultado con `git show`/`git ls-tree`)

`stash@{0}` = `"On feature/REQ-014-rediseno-ui-escritorio: REQ-014 (EN_QA, sin commitear)..."`.
Es un stash con 3 padres (creado con `git stash -u`): `^1` = base (`eb190b3`), `^2` = índice,
`^3` = archivos no trackeados. **No se aplicó ni se hizo `pop` en esta sesión** — solo inspección de
solo lectura.

### `delete_conversation()` — confirmado presente y completo en el stash
```
git show stash@{0}:agente_ia/ai/memory_manager.py | grep -n -A 25 "def delete_conversation"
```
Devuelve la función completa (líneas 502-526 del archivo en el stash):
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
Cumple exactamente el comportamiento que exige CA-31 de SPEC-015 (DELETE real, restringida por
`user_id`, no lanza sobre conversación inexistente/ya borrada → retorna `False`). Disponible para que
`orion-architect` decida recuperarla puntualmente (copiar tal cual) o reimplementarla desde cero con
este mismo comportamiento como referencia — ambas opciones quedan abiertas por la SPEC.

### Archivos de UI de REQ-014 disponibles como referencia de diseño (NO como código a portar — la
SPEC ya aclara que la tecnología es distinta, esto es solo lo que existe si se necesita consultar)

Confirmado con `git ls-tree -r --name-only stash@{0}^3` (árbol de no-trackeados del stash):
```
ui/animations.py
ui/chat_area.py
ui/components/__init__.py
ui/components/avatar.py
ui/components/code_block.py
ui/components/markdown_renderer.py
ui/input_bar.py
ui/main_window.py
ui/message_bubble.py
ui/sidebar.py                      ← distinto de ui/widgets/sidebar.py (REQ-013, en disco hoy)
ui/typing_indicator.py
ui/workers.py
```
Más los tests correspondientes (`tests/test_animations.py`, `tests/test_avatar.py`,
`tests/test_chat_area.py`, `tests/test_code_block.py`, `tests/test_input_bar.py`,
`tests/test_main_window.py`, `tests/test_markdown_renderer.py`, `tests/test_message_bubble.py`,
`tests/test_sidebar.py`, `tests/test_typing_indicator.py`) y `workspace/adjuntos/REQ-014/` completa
(spec, arquitectura, qa-audit, test-results, desarrollo-log, captura addendum §7 — ya restaurada al
disco por `orion-spec` en la sesión anterior, no-trackeada, intacta).

Todos estos archivos están escritos en `QWidget`/QSS (PyQt6 nativo), no en HTML/CSS/JS — la SPEC ya
deja asentado (§Asumidos) que no aplican como código a portar a la arquitectura WebView, solo como
referencia del nivel de detalle/comportamiento ya validado (útil sobre todo para: la firma y
comportamiento exacto de `delete_conversation()`, ya mostrado arriba; los valores hex de paleta
oscura/clara ya validados, referenciados en `REQ-014-context.md`; y el comportamiento funcional
exacto de sidebar/chat/input que la nueva UI debe igualar).

`stash@{1}` (`"On main: REQ-013 (LISTO_PARA_COMMIT, sin commitear)..."`) también existe pero no fue
necesario inspeccionarlo — es anterior a REQ-014 y su contenido relevante ya está presente en disco
(`eb190b3` es su punto de partida commiteado).

## Resumen para orion-architect
- Punto de partida real: arquitectura REQ-013 completa en `ui/`, sin `delete_conversation()`, tema
  oscuro por defecto, panel derecho presente. 15 archivos trackeados a `git rm`.
- `ai/memory_manager.py` expone hoy `new_conversation_id`, `store_turn`, `list_conversations`,
  `get_conversation_turns` — listos para consumir sin tocar. `delete_conversation()` debe agregarse
  (recuperar del stash o reimplementar; referencia completa arriba).
- 2 fallos pre-existentes ambientales (`anthropic` no instalado), no atribuibles a REQ-015.
  Referencia de no-regresión para CA-48: **2 failed, 305 passed** (con `PYTEST_QT_API=pyqt6`).
- Riesgo de entorno confirmado y aún sin corregir en disco: sin `PYTEST_QT_API=pyqt6` en
  `tests/conftest.py`, la suite muestra 66 fallos falsos (widgets PyQt6 vs PySide6). Recomendado
  (no decidido acá) que `orion-architect`/`orion-dev` vuelvan a fijarlo en `tests/conftest.py` como
  ya se hizo en el stash de REQ-014.
- `py_compile` limpio en todos los módulos relevantes de `ui/` y `ai/memory_manager.py`.
