# Resultados de prueba REQ-013

## Compilación
- `python -m py_compile` de los 17 módulos tocados (ui/theme.py, ui/widgets/sidebar.py,
  ui/widgets/center_panel.py, ui/widgets/composer.py, ui/widgets/chat_bubble.py,
  ui/widgets/chat_feed.py, ui/widgets/header_bar.py, ui/widgets/right_panel.py,
  ui/widgets/conversation_list.py, ui/widgets/quick_actions_card.py,
  ui/widgets/system_status_card.py, ui/widgets/recent_activity_card.py,
  ui/widgets/weather_card.py, ui/widgets/voice_orb.py, ui/gui.py, config_manager.py,
  ai/memory_manager.py): **OK**, exit code 0.

## Tests existentes
- Pasados: **305/305** (0 fallos, 3 warnings pre-existentes/benignos — `aifc`/`audioop`
  deprecados de `speech_recognition` y un `PytestReturnNotNoneWarning` en
  `test_agents.py::test_ca1_orchestrator`, ninguno introducido por REQ-013).
- Baseline (`origen/baseline-013.md`): 226 tests, 0 fallos pre-existentes.
- Nuevos fallos: **ninguno**. El conteo 305 coincide exactamente con lo declarado por
  orion-dev en `desarrollo-log-013.md`.

## Criterios de la SPEC

| Criterio | Resultado | Nota |
|----------|-----------|------|
| CA-01 | PASS | `HeaderBar._on_theme_toggle_clicked` → `theme_manager.toggle()` → `_apply()` emite `theme_changed(Palette)`; `register_themed()` conecta la señal a `apply_theme()` de cada widget (sidebar, feed/center_panel, composer, right_panel). Cambio en caliente confirmado, sin reinicio. |
| CA-02 | PASS | `config_manager.py`: `DEFAULT_CONFIG["ui_theme"]="dark"`, `get_ui_theme()`/`set_ui_theme()` siguen el patrón existente. `ThemeManager._apply(..., persist=True)` llama `config_manager.set_ui_theme(name)`; `load_from_config()` se invoca en `gui.py:115` antes de construir los widgets (evita flash del tema anterior). |
| CA-03 | **PASS** (2da pasada) | Ver "2da pasada — re-verificación CA-03" al final del documento. Ambos hallazgos corregidos y re-verificados contra el código real, no solo contra el reporte de `orion-dev`. |
| CA-04 | PASS | `right_panel.py` llama `register_themed(self)` y define `apply_theme(palette)`; se suscribe igual que el resto del layout. |
| CA-05 | PASS | `Sidebar` delega en `ConversationList`; `gui.py:_reload_conversations()` llama `memory.list_conversations` vía `run_async` y `_on_conversations_loaded` pasa el resultado a `sidebar.set_conversations()`. `list_conversations()` en `ai/memory_manager.py` ordena por última actividad. |
| CA-06 | PASS | `sidebar.conversation_selected` → `gui.py:_on_conversation_selected()` → `memory.get_conversation_turns` (async) → `center_panel.load_turns(turns)` + `sidebar.set_active_conversation()`. |
| CA-07 | PASS | `sidebar.new_conversation_requested` → `gui.py:_on_new_conversation()`: resetea `_conversation_id=None`, `center_panel.clear_feed()`, `sidebar.set_active_conversation(None)` — no borra conversaciones previas (solo limpia el feed local). |
| CA-08 | PASS | `sidebar.py:_NAV_ITEMS` — 5 ítems (`memoria`, `tareas`, `archivos`, `aplicaciones`, `configuracion`) con `enabled=False`, `setEnabled(enabled)`, sin `clicked.connect` cuando `enabled=False`. |
| CA-09 | PASS | `gui.py:_handle_command()` (línea ~227) llama `memory.store_turn` vía `run_async` con `conversation_id`, texto de usuario y respuesta. `_ensure_conversation_id()` genera uno nuevo si no existe. |
| CA-10 | PASS | `ai/memory_manager.py:list_conversations()` — confirmado en lectura completa del módulo (id, título derivado, timestamp última actividad). |
| CA-11 | PASS | `ai/memory_manager.py:get_conversation_turns()` — turnos en orden cronológico, confirmado en lectura completa. |
| CA-12 | PASS | `_migrate_schema()` usa `ALTER TABLE ADD COLUMN` idempotente vía `PRAGMA table_info`. `tests/test_conversation_memory.py::test_migracion_agrega_columnas_y_es_idempotente` crea una BD SQLite real con el esquema legacy (`_LEGACY_SCHEMA`, sin `conversation_id`/`role`) y verifica que la migración corre sin excepción y es idempotente — prueba real, no teórica. |
| CA-13 | PASS | `center_panel.add_user_message()` agrega burbuja `"user"` de inmediato al feed, antes de resolver. |
| CA-14 | PASS | `center_panel.show_response()` agrega burbuja `"assistant"` vía `chat_feed.add_message()`, reemplaza el label truncado a 200 chars. |
| CA-15 | PASS | `chat_feed.py` implementa autoscroll vía `rangeChanged` + heurística "cerca del fondo" (40px), confirmado en lectura completa. |
| CA-16 | PASS | Indicador de estado: `HeaderBar._wake_indicator`/`set_wake_state()`. Toggle manos libres: movido a `Composer._wake_toggle`, expuesto en `CenterPanel._wake_toggle` (property) para no romper el contrato de REQ-009. Ambos funcionales. |
| CA-17 | PASS | `Composer.command_submitted` → `CenterPanel.command_submitted` (re-emitido) → `gui.py:148` conecta a `_handle_command()`, que importa y llama `core/resolution.py:resolve()` (línea 207) — mismo pipeline. |
| CA-18 | PASS | `composer.py:_CHIPS` — 3 chips `kind="template"` ("Resumen del día", "Recuérdame algo", "Investigación rápida") y 2 `kind="action"` ("📷 Captura de pantalla" → `take_screenshot`, "🌐 Abrir navegador" → `open_browser`). Cumple "al menos uno de cada tipo". |
| CA-19 | PASS | `composer.py:_on_chip_clicked()` para chips de acción llama exclusivamente `run_async(execute_action, self._on_action_done, self._on_action_error, chip["payload"], channel=ChannelType.DESKTOP, user_id="default")` — nunca importa ni invoca la acción directo. Confirmado además con test real: `tests/test_chat_widgets.py::test_composer_chip_accion_llama_execute_action_con_channel_desktop` — mockea `execute_action` y `run_async`, verifica `kwargs["channel"] is ChannelType.DESKTOP`, `user_id == "default"` y **`accion_falsa.call_count == 0`** (nunca se llama directo). |
| CA-20 | PASS | `RightPanel` sigue instanciado y visible en `gui.py` junto al nuevo layout — no se movió ni se eliminó (confirmado por lectura de `right_panel.py` y su registro en el layout principal). |
| CA-21 | PASS | Igual que CA-04 — `right_panel.py` se suscribe a `theme_changed` vía `register_themed()`. |
| CA-22 | PASS (con nota) | Los 3 tests modificados (`test_sidebar_inicio_emits_nav_selected`, `test_toggle_on_starts_worker_without_blocking`, `test_double_click_toggle_does_not_start_two_workers`) fueron revisados: filtran por `objectName`/`isinstance` de forma precisa, reflejan cambios de contrato legítimos (ancho de sidebar 250→280px, reubicación del wake toggle a `Composer`) y no ocultan ninguna regresión real — confirmado leyendo el código de producción correspondiente, no solo el test. |

## Regresión

| Área revisada | Resultado |
|----------------|-----------|
| `tests/test_theme.py` (paleta/contraste) | PASS de ejecución, pero **cobertura incompleta** (ver CA-03) |
| `tests/test_conversation_memory.py` (migración legacy) | PASS, prueba real con BD en disco |
| `tests/test_chat_widgets.py` (composer, chips, gate de seguridad) | PASS |
| `tests/test_gui_widgets.py`, `test_cli_gui_active.py`, `test_wake_word_gui.py`, `test_memory_manager_recent.py` | PASS, sin fallos nuevos |
| Suite completa | 305/305 PASS, 0 regresiones frente al baseline de 226 |

## Detalle del hallazgo CA-03 (bloqueante)

**Hallazgo 1 — `text_disabled` sin cobertura de test, contraste real insuficiente.**
`tests/test_theme.py` define `_PAIRS_NORMAL_TEXT` (26 pares a 4.5:1) y `_PAIRS_LARGE_TEXT`
(1 par, `accent`/`accent_soft`, a 3.0:1). El token `text_disabled` no aparece en ninguna de
las dos listas. Sin embargo se usa en producción en `ui/widgets/sidebar.py:126`:
```
#SidebarNavButton:disabled { color: $text_disabled; }
```
contra el fondo `#Sidebar { background-color: $bg_surface; }` (línea 119) — es decir, el
texto de los 5 ítems de navegación deshabilitados ("Memoria", "Tareas", "Archivos",
"Aplicaciones", "Configuración"). Calculando el ratio real con el propio helper
`_contrast_ratio()` del test:
- Modo oscuro: `text_disabled` (`#555f73`) sobre `bg_surface` → **2.909:1**
- Modo claro: `text_disabled` (`#a6b0bf`) sobre `bg_surface` → **2.191:1**

Ambos valores están muy por debajo del umbral de 4.5:1 exigido por CA-03 para texto normal,
y por debajo incluso del piso de 3.0:1 usado para texto grande/componentes UI en este mismo
proyecto. Es un defecto real y visible: los 5 ítems deshabilitados del sidebar son difíciles
de leer en ambos temas, y el test que se supone garantiza CA-03 no lo habría detectado.

**Hallazgo 2 — `accent`/`accent_soft` testeado bajo el umbral equivocado.**
El único par en `_PAIRS_LARGE_TEXT` (umbral 3.0:1) es `accent`/`accent_soft`. En el código
real este par se usa en texto de tamaño normal, no grande (≥24px):
- `#ModePill` (`header_bar.py:129`) — `font-size: 12px`
- `#NewConversationButton` (`conversation_list.py:144`) — `font-size: 12px`
- `#WakeIndicator[wakeState="LISTENING_WAKE"]` (`header_bar.py:142`) — `font-size: 14px`

Ninguno de estos tres usos califica como "texto grande" según WCAG (≥24px normal o ≥18.66px
negrita), por lo que el par debería evaluarse contra el umbral de 4.5:1, no 3.0:1. El ratio
real calculado con `_contrast_ratio()`:
- Modo oscuro: **7.397:1** — pasa igual con cualquiera de los dos umbrales.
- Modo claro: **4.494:1** — pasa el umbral de 3.0:1 usado hoy por el test, pero **no llega**
  al umbral correcto de 4.5:1 para texto normal (falla por 0.006).

Es un margen muy estrecho, pero confirma que la categorización del test no representa el uso
real del token: si se corrige el hex para llegar a 4.5:1, o se reclasifica el par bajo
`_PAIRS_NORMAL_TEXT` documentando por qué el margen actual es aceptable, cualquiera de las
dos rutas es válida — lo que no puede quedar así es un par etiquetado "texto grande" que en
realidad protege texto de 12-14px.

## Veredicto (1ra pasada): **FAIL**

19/22 criterios PASS, **CA-03 FAIL** (2 hallazgos: uno bloqueante — `text_disabled` sin
cobertura y con contraste real muy por debajo de AA en ambos temas —, otro menor — par
`accent`/`accent_soft` testeado bajo el umbral incorrecto, falla por margen mínimo en modo
claro). El resto de los criterios (CA-01, CA-02, CA-04 a CA-22) pasan con evidencia directa
contra el código real, no solo contra los tests existentes.

---

## 2da pasada — re-verificación CA-03

**Agente:** orion-tester · **Fecha:** 2026-08-17
**Origen:** fix de `orion-dev` en `desarrollo-log-013.md`, sección "2da pasada — fix CA-03".

Re-verificado contra el código real (`ui/theme.py`, `tests/test_theme.py`), no solo contra el
reporte de `orion-dev`.

### 1. Cobertura del test

`python -m pytest tests/test_theme.py -v --tb=short` → **23 passed**. Confirmado en el propio
archivo:
- `tests/test_theme.py:71` — `("text_disabled", "bg_surface")` agregado a `_PAIRS_NORMAL_TEXT`
  (umbral 4.5:1), con comentario que referencia el hallazgo de la 1ra pasada.
- `tests/test_theme.py:58` — `("accent", "accent_soft")` movido de `_PAIRS_LARGE_TEXT` a
  `_PAIRS_NORMAL_TEXT`. `_PAIRS_LARGE_TEXT` queda como `list = []` (línea 78), tipada y
  documentada, sin borrar la infraestructura del umbral 3.0:1 (`_AA_LARGE`, segundo `for` en
  `test_palette_contrast_ratios`).

### 2. Verificación independiente de contraste (no solo el helper del test)

Se recalcularon los 3 ratios con un script Python aislado (misma fórmula WCAG 2.1, implementada
de forma independiente al helper `_contrast_ratio()` de `tests/test_theme.py`, para no confiar
en que el propio test no tenga un bug compartido):

| Par | Hex nuevo | Fondo | Ratio calculado | Umbral | Resultado |
|-----|-----------|-------|------------------|--------|-----------|
| `DARK_PALETTE.text_disabled` / `bg_surface` | `#717e99` | `#0d1220` | **4.577:1** | 4.5:1 | PASS |
| `LIGHT_PALETTE.text_disabled` / `bg_surface` | `#6f7680` | `#ffffff` | **4.586:1** | 4.5:1 | PASS |
| `LIGHT_PALETTE.accent` / `accent_soft` | `#0a68b3` | `#e4f0fb` | **4.982:1** | 4.5:1 | PASS |

Los tres pares cumplen el umbral AA de 4.5:1 para texto normal, confirmando el cálculo de
`orion-dev` con una implementación independiente del helper de contraste.

### 3. Uso real en producción (sin otros pares rotos)

```
grep -rn "text_disabled" ui/widgets/*.py ui/*.py
→ único uso: ui/widgets/sidebar.py:126 (#SidebarNavButton:disabled)

grep -rn '\$accent\b' ui/widgets/*.py ui/*.py
→ composer.py (hover/focus/border, no texto plano contra accent_soft)
→ conversation_list.py:144 ($accent sobre $accent_soft) — cubierto
→ header_bar.py:129,142 ($accent sobre $accent_soft) — cubierto
```

Confirma lo declarado por `orion-dev`: `text_disabled` solo se usa en ese selector de
`sidebar.py`, y los 3 usos reales de `accent` contra `accent_soft` (`#ModePill`,
`#NewConversationButton`, `#WakeIndicator`, todos texto de 12-14px) quedan cubiertos por el par
ahora en `_PAIRS_NORMAL_TEXT`. No se detectaron otros pares con `text_disabled` o `accent`/
`accent_soft` fuera del alcance de los hallazgos originales.

### 4. Regresión — suite completa

```
python -m py_compile ui/theme.py tests/test_theme.py
→ COMPILA (exit 0)

python -m pytest tests/ --tb=short -q
→ 305 passed, 3 warnings in 7.11s
```

**305/305**, mismo conteo que la 1ra pasada y que lo declarado por `orion-dev`. 0 fallos nuevos,
0 regresiones. Los 3 warnings son los mismos pre-existentes (`aifc`/`audioop` deprecados de
`speech_recognition`, `PytestReturnNotNoneWarning` en `test_agents.py::test_ca1_orchestrator`).

### Tabla de criterios — actualización final

Todos los criterios CA-01 a CA-22 evaluados en la 1ra pasada mantienen su veredicto PASS (ver
tabla arriba); **CA-03 pasa de FAIL a PASS** en esta 2da pasada.

**22/22 criterios PASS.**

## Veredicto (2da pasada): **PASS**

Los 22 criterios de aceptación de SPEC-013 pasan. El fix de `orion-dev` para CA-03 fue
re-verificado de forma independiente (cálculo de contraste propio, no solo lectura del reporte)
y no introdujo regresiones (305/305 tests, mismo conteo que antes del fix). REQ-013 avanza a
`orion-qa`.

---

## 3ra pasada — re-verificación fix condición de carrera (RECHAZADO de orion-qa)

**Agente:** orion-tester · **Fecha:** 2026-08-17
**Origen:** `pruebas/qa-audit-013.md` — veredicto ❌ RECHAZADO. Hallazgo bloqueante: condición de
carrera real en `_pending_user_text` (slot único compartido en `ui/gui.py`) que corrompía la
atribución user/assistant en `ai/unified_memory.db` si el usuario enviaba un segundo comando
antes de que el primero resolviera. Fix de `orion-dev` documentado en `desarrollo-log-013.md`,
sección "3ra pasada — fix condición de carrera". Re-verificado contra el código real, no solo
contra el reporte de `orion-dev`.

### 1. El fix cierra la carrera por construcción, no con un guard lógico saltable

Leído `ui/widgets/composer.py:178-189` (`Composer.set_input_enabled`):
```python
def set_input_enabled(self, enabled: bool) -> None:
    self._input.setEnabled(enabled)
    self._send_button.setEnabled(enabled)
    self._input.setPlaceholderText(_PLACEHOLDER_IDLE if enabled else _PLACEHOLDER_BUSY)
```
Con `QWidget.setEnabled(False)`, Qt deja de entregar eventos de input (mouse/teclado) al widget:
un `QPushButton` deshabilitado no emite `clicked` al clickearlo, y un `QLineEdit` deshabilitado
no procesa `Enter` (no emite `returnPressed`). No es un `if` que dependa de que el código de
`_emit_command()` lo consulte — es el propio widget el que nunca recibe el evento, así que no
hay ningún segundo punto de entrada capaz de saltarse el bloqueo mientras el widget siga
deshabilitado. Confirmado además que `_emit_command()` es el único productor de la señal
`command_submitted` (`grep -rn "command_submitted.emit"` → un solo resultado) y que
`Composer._emit_command()` es el único camino hacia `_handle_command()`
(`grep -rn "command_submitted\|_handle_command"` sin otro emisor: ni voz, ni tray, ni atajos
disparan un comando por otra vía). Verificado también que `_wake_toggle` (modo manos libres) es
un widget distinto, no tocado por `set_input_enabled()` — confirma el punto 4 más abajo.

`ui/gui.py:199-260` (`_handle_command`/`_on_command_done`/`_on_command_error`) confirma el orden:
`_handle_command()` fija `_pending_user_text` y llama `set_input_enabled(False)` ANTES de lanzar
`run_async(resolve, ...)`; `_on_command_done()` lee `_pending_user_text` para `store_turn()`,
lo limpia, y recién después llama `set_input_enabled(True)`. Mientras el composer esté
deshabilitado no puede existir un segundo `_handle_command()` en vuelo, así que
`_pending_user_text` nunca puede ser pisado entre que se fija y que se lee.

**Veredicto punto 1: el fix es estructural (Qt no entrega el evento), no un guard lógico
independiente que otro punto de entrada pudiera esquivar.**

### 2. Fidelidad del test de regresión al hallazgo original

`tests/test_gui_widgets.py::test_main_window_segundo_envio_bloqueado_mientras_resuelve_el_primero`
(línea 434) reproduce el escenario exacto de `qa-audit-013.md`:
1. Envía "A" → dispara `resolve("A")`, `_pending_user_text == "A"`, composer deshabilitado.
2. Intenta enviar "B" **antes** de que "A" resuelva (clickea `_send_button` con el composer
   deshabilitado) → verifica que `_pending_user_text` sigue siendo `"A"` y que no se lanzó un
   segundo `resolve` (`len(resueltos) == 1`).
3. Resuelve "A" (`window._on_command_done(resolution_a)`) → verifica que `store_turn` recibe
   `("A", "respuesta A")` — nunca `"B"` — y que el composer vuelve a habilitarse.
4. Solo entonces "B" se envía con éxito (segundo `resolve` recién ahí).

Verificación de que el test detectaría una reversión del fix (revisando la lógica, sin revertir
código real): si `_handle_command()` no llamara `set_input_enabled(False)`, el `_send_button.click()`
del paso 2 SÍ emitiría `command_submitted` (el botón seguiría habilitado) → `_pending_user_text`
pasaría a `"B"` y `resueltos` crecería a 2 en ese punto → las aserciones `assert
window._pending_user_text == "A"` y `assert len(resueltos) == 1` (líneas 468-469) fallarían
inmediatamente, antes de llegar siquiera a verificar `store_turn`. El test también fallaría si
`_on_command_done` no reactivara el composer (paso 3, línea 481) o si `_on_command_error` no lo
hiciera (test separado, ver punto 3). Confirmado además con ejecución real:
`pytest tests/test_gui_widgets.py::test_main_window_segundo_envio_bloqueado_mientras_resuelve_el_primero`
→ **1 passed**.

**Veredicto punto 2: reproduce fielmente el escenario del hallazgo (segundo envío antes de que
resuelva el primero) y es sensible a una reversión del fix por construcción de sus aserciones.**

### 3. `_on_command_error()` reactiva el composer

Confirmado en `ui/gui.py:253-260`:
```python
def _on_command_error(self, message: str) -> None:
    self.center_panel.show_response(f"Error: {message}")
    self._pending_user_text = ""
    self.center_panel.set_input_enabled(True)
```
Cubierto por `tests/test_gui_widgets.py::test_main_window_on_command_error_no_persiste_turno`
(línea 412), con la aserción agregada en esta pasada:
`assert window.center_panel._composer._input.isEnabled() is True` tras `_on_command_error`.
Ejecución real: **1 passed**. Sin este reactivado, un timeout de red dejaría el composer
bloqueado indefinidamente — confirmado que no es el caso.

### 4. CA-16 y modo manos libres sin cambios de contrato

- Indicador IDLE/LISTENING/PROCESSING/RESPONDING: `HeaderBar._wake_indicator`/`set_wake_state()`
  sigue reflejando `GLOBAL_STATE` vía `_poll_state()` — `set_input_enabled()` no toca
  `HeaderBar` ni el polling de estado. Sin relación entre ambos mecanismos.
- Modo manos libres: `Composer._wake_toggle` (línea 101 de `composer.py`) es un `QPushButton`
  independiente de `_input`/`_send_button`; `set_input_enabled()` solo referencia esos dos
  atributos (confirmado por lectura completa del método, línea 178-189). El toggle sigue
  operable durante una resolución en curso, igual que antes del fix.
- `tests/test_gui_widgets.py` (tests de REQ-009 sobre `_wake_toggle`) y los tests de `HeaderBar`
  en `test_gui_widgets.py`/`test_wake_word_gui.py` no requirieron ningún cambio en esta pasada —
  confirmado que ninguno de los dos archivos fue tocado para el fix de la 3ra pasada más allá de
  los 2 tests nuevos de regresión (`git diff --stat` sobre `tests/test_gui_widgets.py` muestra
  solo adiciones).

**Veredicto punto 4: CA-16 y manos libres intactos, sin cambio de contrato.**

### 5. Suite completa

```
python -m py_compile main.py ui/gui.py ui/widgets/composer.py ui/widgets/center_panel.py
→ COMPILA (exit 0)

python -m pytest tests/test_gui_widgets.py::test_main_window_segundo_envio_bloqueado_mientras_resuelve_el_primero \
    tests/test_gui_widgets.py::test_main_window_on_command_error_no_persiste_turno \
    tests/test_chat_widgets.py::test_composer_set_input_enabled_bloquea_envio_y_cambia_placeholder \
    -v --tb=short
→ 3 passed

python -m pytest tests/ --tb=short
→ 307 passed, 3 warnings in 7.61s
```

**307/307**, +2 respecto de la 2da pasada (305) por los 2 tests nuevos de regresión de esta
pasada (`test_main_window_segundo_envio_bloqueado_mientras_resuelve_el_primero` es nuevo;
`test_main_window_on_command_error_no_persiste_turno` ya existía y se le agregó una aserción, no
suma al conteo). 0 fallos, 0 regresiones. Los 3 warnings son los mismos pre-existentes de
siempre (`aifc`/`audioop` deprecados de `speech_recognition`, `PytestReturnNotNoneWarning` en
`test_agents.py::test_ca1_orchestrator`).

### Tabla de criterios — actualización final (3ra pasada)

Todos los criterios CA-01 a CA-22 mantienen su veredicto PASS de la 2da pasada. CA-09 y CA-16
quedan re-confirmados específicamente en esta pasada con el fix de la condición de carrera
verificado contra el código real (no solo contra el reporte de `orion-dev`).

**22/22 criterios PASS.**

## Veredicto final (3ra pasada): **PASS**

El hallazgo bloqueante de `qa-audit-013.md` (condición de carrera en `_pending_user_text`) está
cerrado por construcción: `Composer.set_input_enabled(False)` aprovecha que Qt no entrega
eventos de input a un widget deshabilitado, eliminando la ventana de carrera sin depender de un
guard lógico paralelo. El test de regresión reproduce fielmente el escenario original del
hallazgo y es sensible a una reversión del fix. `_on_command_error()` también reactiva el
composer, evitando que un error de red deje la UI bloqueada. CA-16 y el modo manos libres no
cambiaron de contrato. Suite completa: 307/307 passed, sin regresiones. REQ-013 avanza
nuevamente a `orion-qa` para que confirme el cierre del hallazgo que motivó el rechazo.
