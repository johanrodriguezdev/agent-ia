# Desarrollo REQ-013 — Rediseño UI escritorio NODDOO estilo chat de IA

**Agente:** orion-dev · **Fecha:** 2026-08-17
**Fuente de verdad:** `workspace/adjuntos/REQ-013/propuestas/arquitectura-013.md` (✅ aprobada por
Johan, sin ajustes) · **SPEC:** `workspace/adjuntos/REQ-013/spec/SPEC-013.md` (CA-01..CA-22)
**Baseline de partida:** working tree sucio con los cambios sin commitear de REQ-007 y REQ-012 —
226 passed, 0 fallos preexistentes (`origen/baseline-013.md`). No se hizo `stash`/`reset`/`checkout`.

---

## Archivos creados

| Archivo | Contenido |
|---------|-----------|
| `agente_ia/ui/theme.py` | `Palette` (dataclass congelada, 23 tokens + `orb_colors`), `DARK_PALETTE`, `LIGHT_PALETTE`, `THEMES`, `qss_tokens()`, `resolve_theme_name()`, `ThemeManager` (singleton `theme_manager`, señal `theme_changed`), `register_themed()` |
| `agente_ia/ui/widgets/chat_bubble.py` | `ChatBubble(QFrame)` — propiedad dinámica `role`, texto seleccionable, ancho máximo 72% del feed |
| `agente_ia/ui/widgets/chat_feed.py` | `ChatFeed(QScrollArea)` — `add_message`, `load_turns`, `clear_messages`, autoscroll condicional vía `rangeChanged` |
| `agente_ia/ui/widgets/composer.py` | `Composer(QFrame)` — chips (3 plantilla + 2 acción), input, toggle manos libres, enviar |
| `agente_ia/ui/widgets/conversation_list.py` | `ConversationList(QWidget)` — "Nueva conversación" + lista + "Ver más"; presentación pura, sin SQLite |
| `agente_ia/tests/test_theme.py` | 23 tests — contraste WCAG, paridad de tokens, normalización, sustitución de plantillas |
| `agente_ia/tests/test_config_manager_ui_theme.py` | 6 tests — `get_ui_theme`/`set_ui_theme` |
| `agente_ia/tests/test_conversation_memory.py` | 16 tests — migración, `store_turn`, listado, turnos, filas legacy |
| `agente_ia/tests/test_chat_widgets.py` | 20 tests — `ChatBubble`, `ChatFeed`, `Composer`, `ConversationList` |

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `agente_ia/config_manager.py` | `"ui_theme": "dark"` en `DEFAULT_CONFIG` + fallback en `load_config()`, `get_ui_theme()`, `set_ui_theme()` |
| `agente_ia/ai/memory_manager.py` | `_migrate_schema()` idempotente (`conversation_id`, `role`), `_emb_lock`, `new_conversation_id()`, `store_turn()`, `list_conversations()`, `get_conversation_turns()`, `get_recent(role=...)`, `ConversationSummary`, `_derive_title()` |
| `agente_ia/ui/gui.py` | `theme_manager.load_from_config()` antes de `_init_ui()`, `register_themed(self)` + `apply_theme()`, estado `_conversation_id`/`_pending_user_text`, flujos A–E (`_handle_command`, `_on_command_done`, `_on_command_error`, `_ensure_conversation_id`, `_reload_conversations`, `_on_conversation_selected`, `_on_turns_loaded`, `_on_new_conversation`, `_on_more_conversations`) |
| `agente_ia/ui/widgets/center_panel.py` | Reescritura interna como compositor `[empty_state][ChatFeed][Composer]`; API pública intacta |
| `agente_ia/ui/widgets/sidebar.py` | 250 → 280 px, "Conversaciones" habilitado, separador, `ConversationList` embebida, señales re-emitidas |
| `agente_ia/ui/widgets/header_bar.py` | Selector de tema (`#ThemeToggle`) a la izquierda de `_mode_pill` |
| `agente_ia/ui/widgets/right_panel.py`, `system_status_card.py`, `quick_actions_card.py`, `recent_activity_card.py`, `weather_card.py`, `voice_orb.py` | QSS migrado a `string.Template` + `apply_theme()` + `register_themed()` |
| `agente_ia/tests/test_gui_widgets.py` | Fixture `no_external_io` extendida, fixture `theme_sandbox` nueva, 14 tests de integración, 1 test actualizado |
| `agente_ia/tests/test_wake_word_gui.py` | Fixture `no_external_io` extendida, 2 tests actualizados |

## Dependencias agregadas

**Ninguna.** `requirements.txt` NO se tocó — todo es PyQt6 (ya presente) + stdlib (`uuid`,
`sqlite3`, `string`, `dataclasses`, `threading`), tal como anticipó la arquitectura.

## Archivos deliberadamente NO tocados

- `agente_ia/main.py` — decisión de arquitectura: sus dos `memory.store()` (CLI/voz) siguen con
  `conversation_id=NULL` y no aparecen en el sidebar. Su `except Exception: pass` de ~línea 173 es
  **preexistente y fuera de alcance**; no se corrigió (nota para `orion-qa`: no atribuirlo a este REQ).

---

## Decisiones de implementación

Todas son ajustes menores dentro de lo aprobado; ninguna contradice la arquitectura.

### 1. Dos hex de paleta corregidos para cumplir CA-03
La arquitectura fijaba los tokens `dark` reproduciendo los hex actuales del código. Al escribir
`test_palette_contrast_ratios` (el criterio objetivo de CA-03) dos valores quedaban por debajo del
umbral, así que se ajustaron y quedó anotado inline en `ui/theme.py`:

- `DARK_PALETTE.text_muted`: `#5a6478` → `#808a9c` (2.92:1 → **4.99:1** sobre `bg_elevated`).
- `LIGHT_PALETTE.text_muted`: `#6d7889` → `#636d7d` (4.47:1 → **5.23:1** sobre blanco).

**Motivo:** CA-03 exige 4.5:1; reproducir el hex actual habría dejado el criterio fallando por
construcción. Es la única desviación respecto de "los tokens dark reproducen exactamente los hex
de hoy", y es visualmente imperceptible (texto auxiliar levemente más legible).

### 2. `CircularProgress.set_colors()` en `system_status_card.py`
El anillo de progreso no se estiliza por QSS: se dibuja a mano en `paintEvent()` con colores
literales. Se agregó `set_colors(track, arc, text)` y `apply_theme()` lo llama con
`palette.border` / `palette.accent` / `palette.text_primary`.

**Motivo:** sin esto el anillo quedaba con colores de tema oscuro sobre fondo claro — un agujero de
CA-01 que la arquitectura no había detallado porque no es QSS.

### 3. Dos literales del `HeaderBar` que no estaban mapeados
`#121a2b` → `$bg_elevated` y `#00e08a` → `$success`. Eran hex sueltos del QSS previo sin token
asignado en la tabla de la arquitectura.

### 4. `CenterPanel._wake_toggle` expuesto como `@property`
El toggle de manos libres se mudó al `Composer` (CA-16), pero los tres tests de REQ-009 acceden a
`panel._wake_toggle`. Se expone como property que delega en `self._composer._wake_toggle`: es el
**mismo objeto**, no un espejo, así que `click()`, `isChecked()` y `property("wakeState")` siguen
funcionando sin tocar esos tests.

### 5. `_pending_conversation_offset` en `JarvisMainWindow`
`_reload_conversations(offset)` corre asíncrono, así que el callback necesita saber si su resultado
reemplaza el listado o lo agrega al final ("Ver más"). Se guarda el offset en vuelo como atributo de
instancia. Es la mecánica concreta de la paginación de 30 que la arquitectura describe en §4.3.

### 6. `ChatFeed.load_turns()` — turno sin rol se muestra como del asistente
Coherente con la decisión de no inventar estructura: una fila con `role IS NULL` se muestra, nunca
se descarta ni se atribuye falsamente al usuario.

### 7. `UnifiedMemory.store()` ahora devuelve `Optional[int]`
Cambio aditivo (antes no devolvía nada): `store_turn()` necesita el `lastrowid`. Ningún llamador
existente usa el retorno.

### 8. Chips de acción: canal real explícito
`Composer._on_chip_clicked()` pasa por `run_async(execute_action, ..., channel=ChannelType.DESKTOP,
user_id="default")`. La acción **nunca** se importa ni se invoca directo, de modo que el gate
fail-closed de `core/security_manager.py` se ejecuta igual que en cualquier otro canal
(CA-19, `.claude/rules/security-levels.md`). Cubierto por
`test_composer_chip_accion_llama_execute_action_con_channel_desktop`, que además verifica que la
función mockeada tiene `call_count == 0`.

---

## Tests existentes actualizados (CA-22)

Tres tests rompieron por **cambio de contrato**, no por regresión. Los tres se actualizaron con el
motivo documentado en un comentario dentro del propio test:

| Test | Antes | Ahora | Motivo |
|------|-------|-------|--------|
| `test_sidebar_inicio_emits_nav_selected` | 1 botón habilitado / 6 deshabilitados sobre **todos** los `QPushButton` del sidebar | 2 habilitados / 5 deshabilitados, acotado a `objectName == "SidebarNavButton"` | CA-08 habilita "Conversaciones"; además el sidebar ahora contiene los botones de `ConversationList`, que no son navegación |
| `test_toggle_on_starts_worker_without_blocking` | `len(no_real_threadpool) == 1` | filtra por `isinstance(w, WakeWordWorker)` | `__init__` agenda además un `CallableWorker` con el listado de conversaciones |
| `test_double_click_toggle_does_not_start_two_workers` | ídem | ídem | ídem |

Además, las fixtures `no_external_io` de `test_gui_widgets.py` y `test_wake_word_gui.py` ahora
neutralizan `memory.list_conversations` — sin eso la suite leería la base de datos real al construir
`JarvisMainWindow` (`.claude/rules/testing.md`). Y se agregó la fixture `theme_sandbox`, que aísla
el `theme_manager` (singleton de módulo) del `config.json` real: `set_theme()` escribiría la
preferencia del usuario y `load_from_config()` haría que el resultado dependiera de ella.

`test_recent_activity_card_*` **no** necesitó cambios pese al nuevo `role="user"`: su fixture mockea
`get_recent` con `lambda **kwargs: []`, que absorbe el kwarg nuevo.

---

## Verificación local

```
python -m py_compile main.py ui/gui.py ui/theme.py ai/memory_manager.py config_manager.py ui/widgets/*.py
→ COMPILA TODO

python -m pytest tests/ --tb=short -q
→ 305 passed, 3 warnings in 7.30s
```

- **Baseline:** 226 passed, 0 fallos → **ahora:** 305 passed, **0 fallos**. Sin regresiones.
- **+79 tests:** 23 (`test_theme`) + 6 (`test_config_manager_ui_theme`) + 16
  (`test_conversation_memory`) + 20 (`test_chat_widgets`) + 14 (integración en `test_gui_widgets`).
- Suite corrida **tres veces** (una con `-p no:randomly`, dos con orden aleatorio): 305 passed en
  las tres. El singleton `theme_manager` no filtra estado entre tests.
- Los 3 warnings son preexistentes (`aifc`/`audioop` deprecados en `speech_recognition`,
  `PytestReturnNotNoneWarning` en `test_agents.py`), idénticos a la baseline.

## Checklist DoD

- [x] Solo se implementó lo aprobado en `arquitectura-013.md`
- [x] Sin API keys/tokens hardcodeados (verificado; los colores nunca vienen de `config.json` — solo el nombre del tema, normalizado por `resolve_theme_name()`)
- [x] Sin `except: pass` silencioso en código nuevo (`grep` limpio en los 15 archivos tocados)
- [x] Sin prints de debug (`grep` limpio; todo por `logging`)
- [x] Dependencias nuevas: ninguna → `requirements.txt` no se tocó
- [x] Skills: este REQ no crea ni modifica skills
- [x] Banner de orion-dev mostrado antes de escribir código
- [x] `desarrollo-log-013.md` generado (este archivo)
- [x] **NO se ejecutó `git commit`, `git add` ni `git push`**
- [x] Mensaje de commit sugerido entregado (no ejecutado)

## Pendiente de verificación manual (para `orion-tester` / Johan)

1. **Regresión visual en tema oscuro** — riesgo señalado por la arquitectura: fuera de la columna
   central rediseñada no debería haber diferencia perceptible respecto de antes del REQ. Los dos
   `text_muted` ajustados (decisión 1) son la única diferencia intencional.
2. **`ALTER TABLE` sobre la base real** — `_migrate_schema()` es idempotente y `ADD COLUMN` nullable
   es O(1), pero conviene copiar `ai/unified_memory.db` antes del primer arranque post-cambio.
3. **Avatar de Nodo** — hoy es un `QLabel` con emoji `🤖` a 56px, declarado como placeholder en el
   docstring de `center_panel.py` con la ruta de sustitución indicada. No se agregó ningún binario.

---

## 2da pasada — fix CA-03 (FAIL de orion-tester)

**Agente:** orion-dev · **Fecha:** 2026-08-17
**Origen:** `workspace/adjuntos/REQ-013/pruebas/test-results-013.md` — veredicto FAIL, 19/22 PASS,
CA-03 con 2 hallazgos (uno bloqueante, uno menor). Detalle completo de los hallazgos en ese archivo.

### Hallazgo 1 (bloqueante) — `text_disabled` sin cobertura y contraste real insuficiente

`text_disabled` no estaba en `_PAIRS_NORMAL_TEXT` de `tests/test_theme.py`, pese a usarse en
`#SidebarNavButton:disabled { color: $text_disabled; }` (`ui/widgets/sidebar.py:126`) contra
`#Sidebar { background-color: $bg_surface; }` — los 5 ítems deshabilitados del sidebar
("Memoria", "Tareas", "Archivos", "Aplicaciones", "Configuración"). Ratio real: 2.909:1 (oscuro) /
2.191:1 (claro), muy por debajo de 4.5:1.

**Fix aplicado en `ui/theme.py`:**
- `DARK_PALETTE.text_disabled`: `#555f73` → `#717e99` (2.909:1 → **4.58:1** sobre `bg_surface`).
- `LIGHT_PALETTE.text_disabled`: `#a6b0bf` → `#6f7680` (2.191:1 → **4.59:1** sobre `bg_surface`).

Verificado con `grep -rn text_disabled` que el token solo se usa en ese único selector de
`sidebar.py`, así que el ajuste no afecta ningún otro par. Ambos hex mantienen la jerarquía visual
(en ambos temas el disabled sigue siendo más tenue que `text_muted` y `text_secondary`, ahora con
margen suficiente sobre el piso AA en vez de por debajo de él).

**Fix aplicado en `tests/test_theme.py`:** se agregó `("text_disabled", "bg_surface")` a
`_PAIRS_NORMAL_TEXT`, con comentario explicando el hallazgo, para que quede cubierto en
`test_palette_contrast_ratios` y no se repita.

### Hallazgo 2 (menor) — `accent`/`accent_soft` testeado bajo el umbral incorrecto

Verificado el QSS real de los 3 selectores señalados por el tester antes de decidir: `#ModePill`
(`ui/widgets/header_bar.py:129`, `font-size: 12px`), `#NewConversationButton`
(`ui/widgets/conversation_list.py:144`, `font-size: 12px`) y
`#WakeIndicator[wakeState="LISTENING_WAKE"]` (`ui/widgets/header_bar.py:142`, `font-size: 14px`).
Ninguno llega a 18.66px negrita ni a 24px normal — no califica como "texto grande" WCAG, así que el
umbral correcto es 4.5:1, no 3.0:1. En modo claro medía 4.494:1 (falla por 0.006); en oscuro
7.397:1 (pasaba igual con cualquiera de los dos umbrales).

**Fix aplicado en `ui/theme.py`:** `LIGHT_PALETTE.accent`: `#0b6fbf` → `#0a68b3`
(4.494:1 → **4.98:1** contra `accent_soft`). Verificado que no rompe ningún otro par existente que
use `accent` — al oscurecerlo, todos mejoran (`bg_window` 4.80→5.33, `bg_surface`/`bg_elevated`/
`bg_input` 5.20→5.66, `on_accent` 5.20→5.76). Único archivo con el hex anterior hardcodeado fuera
de `theme.py` era `arquitectura-013.md` (documento histórico de la propuesta, no se toca).

**Fix aplicado en `tests/test_theme.py`:** el par `("accent", "accent_soft")` se movió de
`_PAIRS_LARGE_TEXT` a `_PAIRS_NORMAL_TEXT`, con comentario explicando por qué (uso real en texto de
12-14px). `_PAIRS_LARGE_TEXT` queda como lista vacía tipada (`list = []`), con comentario, para el
día que un par real proteja texto ≥24px o ≥18.66px negrita — no se borró la infraestructura
(`_AA_LARGE`, el segundo `for` de `test_palette_contrast_ratios`) porque sigue siendo válida.

### Verificación local (2da pasada)

```
python -m py_compile ui/theme.py tests/test_theme.py
→ COMPILA TODO

python -m pytest tests/test_theme.py --tb=short -q
→ 23 passed in 0.45s

python -m pytest tests/ --tb=short -q
→ 305 passed, 3 warnings in 6.96s
```

- Mismo conteo que antes del fix (305): los pares nuevos/movidos viven **dentro** de
  `test_palette_contrast_ratios` (parametrizado solo por paleta, dark/light), no generan casos de
  test adicionales — evalúan más pares dentro de la misma función.
- 0 fallos nuevos, 0 regresiones. Los 3 warnings son los mismos preexistentes de siempre.

### Checklist DoD (2da pasada)

- [x] Solo se corrigió lo señalado por `orion-tester` en CA-03 — ningún otro cambio
- [x] Sin API keys/tokens hardcodeados
- [x] Sin `except: pass` silencioso
- [x] Sin prints de debug
- [x] Sin dependencias nuevas → `requirements.txt` no se tocó
- [x] Banner de orion-dev mostrado antes de escribir código
- [x] `desarrollo-log-013.md` actualizado (esta sección, anexada — no se sobreescribió lo previo)
- [x] **NO se ejecutó `git commit`, `git add` ni `git push`**
- [x] Mensaje de commit sugerido entregado (no ejecutado)

---

## 3ra pasada — fix condición de carrera (RECHAZADO de orion-qa)

**Agente:** orion-dev · **Fecha:** 2026-08-17
**Origen:** `workspace/adjuntos/REQ-013/pruebas/qa-audit-013.md` — veredicto ❌ RECHAZADO. Los 22
CA pasan y la auditoría de seguridad/secretos/niveles de riesgo no encuentra hallazgos, pero
`orion-qa` detectó una condición de carrera real y reproducible en la persistencia asíncrona del
turno (CA-09), no cubierta por ningún test.

### Hallazgo bloqueante — `_pending_user_text` como slot único compartido

`ui/gui.py:111` introduce `self._pending_user_text` para pasarle a `memory.store_turn()` el texto
del usuario cuando llega la respuesta async de `resolve()`. Nada impedía que el usuario enviara un
segundo comando mientras el primero seguía resolviéndose (`resolve()` puede tardar segundos reales
por la llamada de red a `ai/claude_brain.ask_claude()`): el composer nunca deshabilitaba `_input`/
`_send_button` durante PROCESSING. Secuencia concreta:

1. Usuario envía "A" → `_pending_user_text = "A"`, arranca `resolve("A")` en background.
2. Antes de que resuelva, usuario envía "B" → `_pending_user_text = "B"` **pisa** el valor de "A".
3. Resuelve "A" → `_on_command_done` persiste `store_turn(self._pending_user_text, ...)`, pero para
   ese momento `_pending_user_text` ya vale "B" → **se guarda `user_text="B"` con la respuesta real
   de "A"**.
4. Resuelve "B" → `_pending_user_text` ya está en `""` → entra al branch de `store_turn()` que loguea
   `logger.warning` y **no escribe la fila `role="user"`**, pero sí la fila `role="assistant"` →
   **fila huérfana**.

Resultado: `ai/unified_memory.db` queda corrompido en silencio bajo un patrón de uso normal de
chat (dos mensajes seguidos), violando la garantía implícita de CA-09.

### Decisión técnica: bloquear el composer, no correlacionar por id

Se evaluaron las dos alternativas que planteó `orion-qa`:

1. **Deshabilitar el composer mientras hay una resolución en curso** (sugerencia de QA).
2. **Correlacionar cada `resolve()` con su propio texto de usuario** vía closure/`functools.partial`
   en vez de depender de un slot único.

Se descartó la opción 2: `ui/gui_workers.py` documenta explícitamente que los callbacks `on_done`/
`on_error` de `run_async()` deben ser **bound methods de un `QObject`** para que Qt resuelva el hilo
de entrega correctamente (conexión "Auto" → "Queued" cuando el receptor vive en otro hilo). Un
`functools.partial(self._on_command_done, texto)` no expone `__self__` como un bound method normal,
así que PyQt no puede garantizar la misma resolución de hilo — cambiar ese mecanismo requeriría
volver a `orion-architect`, como ya señaló QA. Se implementó la opción 1, que además resuelve por
construcción el caso borde ya documentado en SPEC-013 ("cambio de tema durante una respuesta en
curso no debe interrumpir la resolución") sin tocar `run_async`/`gui_workers.py`.

### Fix aplicado

- **`ui/widgets/composer.py`** — nuevo método `Composer.set_input_enabled(enabled: bool)`:
  deshabilita `_input` y `_send_button` (Qt no entrega `returnPressed` ni `clicked` a un widget
  deshabilitado — la condición de carrera queda eliminada por construcción, no oculta tras un guard
  que se pueda olvidar en otro punto de entrada) y cambia el placeholder del input entre
  `"Escribe un comando o habla con Noddoo..."` (idle) y `"Noddoo está pensando..."` (busy), para dar
  feedback visual explícito de que el bloqueo es intencional y no un cuelgue de la app (CA-16).
- **`ui/widgets/center_panel.py`** — `CenterPanel.set_input_enabled(enabled)` delega en el
  `Composer`, siguiendo el mismo patrón de "compositor delgado" del resto de la clase.
- **`ui/gui.py`**:
  - `_handle_command()`: llama `self.center_panel.set_input_enabled(False)` justo después de fijar
    `_pending_user_text`, antes de `run_async(resolve, ...)`.
  - `_on_command_done()`: reactiva con `set_input_enabled(True)` después de leer
    `_pending_user_text` para `store_turn()` y limpiarlo — por ser todo código síncrono dentro del
    mismo handler (el hilo de la GUI es cooperativo: ningún click puede procesarse hasta que el
    handler retorna), el orden exacto dentro de la función no afecta la corrección, pero se dejó
    junto al `_pending_user_text = ""` para que quede claro que ambos cierran el ciclo del turno.
  - `_on_command_error()`: también reactiva el composer — sin esto, un error de red dejaría el
    input bloqueado para siempre.
- Único punto de entrada a `_handle_command()` es `Composer._emit_command()` (verificado con
  `grep -rn "command_submitted\|_handle_command"`): no hay otro camino (voz, tray, atajos) que
  pueda disparar un segundo comando sorteando el bloqueo del composer.

### Tests de regresión agregados

- `tests/test_chat_widgets.py::test_composer_set_input_enabled_bloquea_envio_y_cambia_placeholder`
  — a nivel de widget: con `set_input_enabled(False)`, un `_send_button.click()` no emite
  `command_submitted`; con `set_input_enabled(True)` sí. Verifica también el cambio de placeholder.
- `tests/test_gui_widgets.py::test_main_window_segundo_envio_bloqueado_mientras_resuelve_el_primero`
  — a nivel de ventana, reproduce el escenario exacto del hallazgo: envía "A" (dispara `resolve`,
  deshabilita el composer), intenta enviar "B" mientras "A" sigue en vuelo (se descarta — el
  registro de `run_async` no crece), resuelve "A" (`store_turn` recibe `user_text="A"`, nunca "B";
  el composer se reactiva) y recién entonces envía "B" con éxito.
- `tests/test_gui_widgets.py::test_main_window_on_command_error_no_persiste_turno` — se le agregó
  una aserción de que el composer queda reactivado tras un error.

### Verificación local (3ra pasada)

```
python -m py_compile ui/gui.py ui/widgets/composer.py ui/widgets/center_panel.py \
    tests/test_gui_widgets.py tests/test_chat_widgets.py
→ COMPILA TODO

python -m pytest tests/test_gui_widgets.py tests/test_chat_widgets.py --tb=short -q
→ 52 passed

python -m pytest tests/ --tb=short -q
→ 307 passed, 3 warnings in 11.06s
```

- Antes de este fix: 305 passed (ver 2da pasada). Ahora: 307 passed — los 2 tests nuevos, 0 fallos,
  0 regresiones.
- Los 3 warnings son los mismos preexistentes de siempre (`aifc`/`audioop` deprecados,
  `PytestReturnNotNoneWarning` en `test_agents.py`).
- CA-16 (indicador IDLE/LISTENING/PROCESSING/RESPONDING) no se tocó: `HeaderBar`/`VoiceOrb` siguen
  reflejando `GLOBAL_STATE` vía `_poll_state()`, sin relación con `set_input_enabled()`. El
  placeholder del composer es un feedback adicional, no un reemplazo del indicador de estado.
- Modo manos libres: el toggle de voz (`_wake_toggle`) NO se deshabilita — sigue viviendo en el
  mismo `Composer` pero no pasa por `set_input_enabled()`; encender/apagar el modo manos libres
  durante una resolución en curso sigue funcionando igual que antes de este fix.

### Checklist DoD (3ra pasada)

- [x] Solo se corrigió lo señalado por `orion-qa` en la condición de carrera de CA-09 — ningún otro
      cambio
- [x] Sin API keys/tokens hardcodeados
- [x] Sin `except: pass` silencioso
- [x] Sin prints de debug
- [x] Sin dependencias nuevas → `requirements.txt` no se tocó
- [x] Banner de orion-dev mostrado antes de escribir código
- [x] `desarrollo-log-013.md` actualizado (esta sección, anexada — no se sobreescribió lo previo)
- [x] **NO se ejecutó `git commit`, `git add` ni `git push`**
- [x] Mensaje de commit sugerido entregado (no ejecutado)
