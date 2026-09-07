# Desarrollo REQ-026 — Modos estratégicos en la barra del composer

## Archivos modificados
- `core/composer_modes.py` — **NUEVO**. Catálogo único `ModoComposer` (dataclass frozen) +
  `listar_modos()`/`get_mode(modo_id)`. Los 4 modos: `codigo` (tool `EXECUTE_CODE`,
  `tarea="modo_codigo"`), `investigacion` (tools `web_search`/`web_read`/`wikipedia_search`/
  `BROWSE_WEB`, `tarea="modo_investigacion"`), `flujos` (tools `flujo`/`CREATE_FLOW`,
  `tarea=None`), `tareas` (tools `task_create`/`task_list`/`task_complete`/
  `task_complete_all`, `tarea=None`). Vive en `core/` porque lo consumen dos capas sin
  relación entre sí (`ui/webview/bridge.py` y `core/reasoning_loop.py`), evitando duplicar
  el mapeo modo→capacidad.
- `ui/webview/bridge.py` —
  - `_CHIPS` (5 chips) reemplazado por `_QUICK_ACTIONS` (3: "Recuérdame algo",
    "📷 Captura de pantalla", "🌐 Abrir navegador"; se descartan "Resumen del día" e
    "Investigación rápida", ahora cubiertos por los modos Tareas/Investigación).
  - `_build_chips_payload()` reemplazado por `_build_modes_payload()` (id/label de
    `listar_modos()`) y `_build_quick_actions_payload()` (misma lógica de risk-level que
    antes, iterando `_QUICK_ACTIONS`).
  - `request_initial_state()` ahora emite `{"modes": [...], "quick_actions": [...]}` por
    `chips_loaded` (mismo signal, payload nuevo).
  - `Bridge.send_message(self, text: str, modo: str = "")` — firma rota deliberadamente
    (arquitectura-026.md), único call site es `composer.js::doSend()`. Pasa
    `modo=(modo or None)` a `resolve()`.
  - Nuevo `self._modo_activo: Optional[str] = None` (espejo efímero, nunca persistido, solo
    para que `_build_models_payload()` refleje "fijado por el modo" cuando `request_models()`
    se llama desacoplado de `send_message()`).
  - Nuevo slot `set_active_mode(self, modo_id: str)` y helper `_tarea_activa()`.
  - `_build_models_payload()` parametrizado (`tarea: str = "razonamiento"`) — `set_model()`
    queda sin tocar (hardcodea `"razonamiento"`, decisión explícita de arquitectura).
  - `run_chip_action()` sin cambios.
- `core/resolution.py` —
  - `_try_claude(..., modo: Optional[str] = None)` y `resolve(..., modo: Optional[str] = None)`.
  - Dentro de `_try_claude()`, `reasoning_run()` se llama pasando `modo=modo` **solo si
    `modo is not None`** (ver "Decisiones de implementación" — desviación respecto al
    documento de arquitectura, que no especificaba esta condicionalidad).
- `core/reasoning_loop.py` —
  - Import de `core.composer_modes` (`ModoComposer`, `get_mode`).
  - `_build_system_prompt(modo_def=None)` agrega `modo_def.prompt_hint` al final de
    `operating_rules`, antes del bloque de fecha/hora (preserva el prefix-caching).
  - Nuevo helper `_reordenar_priorizando(catalogo, tool_names)` — reordena, nunca filtra.
  - `_build_tool_list(channel=None, modo_def=None)` reordena el catálogo de
    `catalogo_para_modelo(channel)` cuando hay modo activo con `tool_names`.
  - `run(..., modo: Optional[str] = None)` — resuelve `modo_def = get_mode(modo)`, arma
    `tools` con `_build_tool_list(resolved_channel, modo_def)`, y `tarea` para
    `generate_response()` (`modo_def.tarea` si está seteado, si no `"razonamiento"`).
- `ui/webview/frontend/index.html` — `#chips-row` reemplazado por `#modes-row` +
  `#quick-actions-row`.
- `ui/webview/frontend/js/composer.js` —
  - `renderChips()` removido; nuevos `renderModes(modes)`, `renderQuickActions(items)`
    (mismo cuerpo que el viejo `renderChips`, apuntando a `#quick-actions-row`),
    `toggleMode(modoId)`, `resetActiveMode()`, `_applyActiveModeVisuals()`.
  - Estado de módulo `_activeModeId`; `doSend()` ahora llama
    `sendMessage(text, _activeModeId || "")`.
  - `_MODE_ICONS` mapea cada modo a un ícono ya existente en el sprite
    (`terminal`/`search`/`flows`/`tasks`).
- `ui/webview/frontend/js/bridge_client.js` —
  - `sendMessage(text, modo)` ahora manda el segundo argumento.
  - Nuevo `setActiveMode(modoId)` → `_bridge.set_active_mode(modoId || "")`.
- `ui/webview/frontend/js/app.js` —
  - Import actualizado (`renderModes`, `renderQuickActions`, `resetActiveMode` en vez de
    `renderChips`).
  - `onChipsLoaded` parsea `{modes, quick_actions}` y llama a ambos renders.
  - `resetActiveMode()` se dispara en `onConversationCleared` y `onTurnsLoaded` (el modo no
    sobrevive a limpiar/cambiar de conversación, según SPEC-026).
- `ui/webview/frontend/css/composer.css` — `#chips-row` dividido en `#modes-row` /
  `#quick-actions-row` (mismo `margin-bottom` en el segundo para no mover el input). Nuevas
  reglas `.mode-btn`, `.mode-btn:hover`, `.mode-btn:focus-visible`, `.mode-btn-check`,
  `.mode-btn--active` + override CA-36 en tema oscuro (`:root[data-theme="dark"]
  .mode-btn--active`), todo con los tokens de `ui-design-026.md` verificados AA.

## Dependencias agregadas
Ninguna. `requirements.txt` no se tocó.

## Decisiones de implementación

### `modo` se pasa condicionalmente en `_try_claude()` (desviación respecto a arquitectura)
`arquitectura-026.md` especifica `_try_claude(..., modo=None)` llamando a
`reasoning_run(text, channel, user_id, estado=estado, modo=modo)` sin condicionar. Implementar
eso literalmente rompió 58 tests que no tienen nada que ver con REQ-026: varios archivos de
test (`tests/modelo_falso.py::run()`/`_sin_proveedor()`, usados vía fixture autouse en
`test_resolution.py`/`test_dialog_resolution.py`/`test_classifier.py`, más un doble local en
`test_orchestrator.py`) reemplazan `core.reasoning_loop.run` con una función plana que
conserva la firma **anterior** a este REQ (sin `modo`). A diferencia de
`unittest.mock.patch()` (que crea un `MagicMock`, tolerante a kwargs desconocidos), estas son
funciones de Python normales — un kwarg que no esperan es `TypeError` directo, no algo que la
arquitectura pudiera haber anticipado sin conocer el detalle interno de esos dobles de test.

Se resolvió pasando `modo=modo` a `reasoning_run()` únicamente cuando `modo is not None`,
preservando la firma exacta de la llamada para cualquier camino que no use el modo activo
(que es exactamente todo lo que esos dobles ejercitan — ninguno de ellos simula la
funcionalidad nueva). El camino real de REQ-026 (`Bridge.send_message(text, modo)` con un
modo activo) sigue threading `modo` de punta a punta sin cambios: `resolve()` →
`_try_claude()` → `reasoning_loop.run()`.

Confirmado con la suite completa: antes del fix, 58 failed / 1737 passed; después, solo
quedan las 2 fallas de `tests/test_webview_bridge.py` ya anticipadas explícitamente por
arquitectura como responsabilidad de `orion-tester` (esperan el payload viejo de 5 chips
planos, ahora es `{modes, quick_actions}`) — 1793 passed / 2 failed, total 1795 tests, sin
ningún fallo nuevo fuera de lo previsto.

Sin otras desviaciones — el resto de la implementación sigue `arquitectura-026.md` y
`ui-design-026.md` al pie de la letra, incluido dejar explícitamente fuera de alcance el
arreglo del emoji 📷/🌐 en los accesos rápidos.

## Verificación local
- `python -m py_compile` OK en los 5 módulos Python tocados/nuevos
  (`core/composer_modes.py`, `ui/webview/bridge.py`, `core/resolution.py`,
  `core/reasoning_loop.py`) más `python -c "import core.reasoning_loop"`.
- `node --check` OK en los 3 módulos JS tocados (`composer.js`, `bridge_client.js`,
  `app.js`).
- `python -m pytest tests/ --tb=short -q`: **1793 passed, 2 failed** (las 2 esperadas de
  `test_webview_bridge.py`, fuera del alcance de `orion-dev` según DoD — las actualiza
  `orion-tester`). Sin fallos preexistentes según `origen/baseline-026.md` (1795 passed, 0
  failed) más allá de estos 2, previstos por arquitectura.

---

# Addendum 1 — ajuste de alcance post-prueba-manual de Johan (2026-09-07)

REQ-026 ya había pasado `orion-tester`/`orion-qa` (veredicto ✅ COMPLETADO en
`pruebas/qa-audit-026.md`) y estaba esperando solo la prueba manual de Johan cuando esa
prueba encontró un ajuste de alcance. Quedó formalizado y **aprobado sin ajustes** en
`spec/SPEC-026-addendum-1.md` y `propuestas/ui-design-026-addendum-1.md`. Esta sección
documenta la segunda pasada de `orion-dev` sobre ese addendum — no reimplementa nada de la
entrada anterior, la actualiza.

## Resumen del cambio
- Los 2 accesos rápidos de tipo `action` ("📷 Captura de pantalla", "🌐 Abrir navegador")
  desaparecen como botón del composer. **La capacidad del agente (`take_screenshot`/
  `open_browser`, incl. `run_chip_action()` como mecanismo) no se toca** — solo se retira su
  acceso directo desde esta barra.
- "Recuérdame algo" deja de ser un `.chip` en píldora aparte: pasa a compartir el
  componente `.mode-btn` con los 4 modos (mismo tamaño/forma/ícono), pero **sin**
  `aria-pressed`, **sin** `.mode-btn--active` y **sin** nodo de check — sigue siendo
  `kind="template"` (solo prellena `#composer-input`), nunca participa del toggle de modo.
- Los 5 elementos (4 modos + "Recuérdame algo") ahora viven en una única fila
  (`#actions-row`, `flex-wrap: nowrap`) — se elimina la división en `#modes-row` +
  `#quick-actions-row`.
- Nuevo ícono de sprite `#ic-bell` en `index.html` (ninguno de los existentes encajaba
  semánticamente con "recordatorio").

## Archivos modificados (addendum 1)
- `ui/webview/bridge.py` —
  - `_QUICK_ACTIONS` reducido de 3 a 1 entrada (solo "Recuérdame algo"); se agrega la clave
    `"icon": "bell"` (no existía antes — la necesita el frontend para renderizar el ícono
    del único acceso rápido que queda).
  - Docstring de `_build_quick_actions_payload()` actualizado: la rama `kind == "action"`
    queda como código muerto (ningún elemento de `_QUICK_ACTIONS` la ejercita ya) pero se
    deja sin retirar — ver "Decisiones de implementación" más abajo.
  - Docstring de `_build_modes_payload()` actualizado para referenciar `#actions-row` en vez
    del ya inexistente `#modes-row`.
  - `run_chip_action()` **sin cambios** — sigue siendo el único camino de ejecución real,
    invocable aunque ya no tenga botón propio en la UI (lo sigue ejercitando
    `test_run_chip_action_*` en `test_webview_bridge.py`, que no requiere actualización).
- `ui/webview/frontend/index.html` —
  - Nuevo `<symbol id="ic-bell">` en el sprite, con el path exacto de
    `ui-design-026-addendum-1.md` §4.
  - `#modes-row` + `#quick-actions-row` reemplazados por un único `<div id="actions-row">`.
- `ui/webview/frontend/js/composer.js` —
  - `_applyActiveModeVisuals()` apunta a `#actions-row` y agrega un guard
    `if (!btn.dataset.modeId) continue;` al iterar — crítico: sin este guard, la fila
    compartida aplicaría `aria-pressed`/`--active`/check al botón de "Recuérdame algo",
    violando el requisito explícito del addendum de que nunca tenga estado activo.
  - `renderModes(modes)` sigue limpiando `#actions-row` y pintando los 4 modos.
  - `renderQuickActions(items)` reescrito: ya no dibuja `.chip`/`.chip-risk-dot`, dibuja
    `.mode-btn` (mismo markup que un modo, sin `aria-pressed`/check) y **agrega al final de
    la fila sin limpiarla** — depende de que `renderModes()` se haya llamado antes en el
    mismo ciclo. Se preserva la rama `else { runChipAction(...) }` del click handler para
    paridad con el `kind == "action"` que el backend mantiene como código muerto.
- `ui/webview/frontend/js/app.js` — sin cambio funcional; se agregó un comentario en
  `onChipsLoaded()` documentando la dependencia de orden `renderModes()` →
  `renderQuickActions()` sobre la fila compartida.
- `ui/webview/frontend/css/composer.css` —
  - `#modes-row`/`#quick-actions-row` reemplazados por `#actions-row` (`flex`,
    `flex-wrap: nowrap`, `gap: 6px`, `margin-bottom: 10px`).
  - `.mode-btn` reducido de `padding: 8px 14px` / `font-size: 13px` / `gap: 7px` a
    `padding: 8px 12px` / `font-size: 12.5px` / `gap: 6px`, para que 5 elementos (antes 4)
    entren sin salto de línea en `--content-max: 760px` (estimado con ~13% de margen según
    `ui-design-026-addendum-1.md` §3, sin medición real en navegador).
  - `.chip`/`.chip:hover`/`.chip:focus-visible`/`.chip-risk-dot`/`.chip-risk-green|yellow|red`
    **se dejan en el CSS, sin retirar** — quedan sin consumidor en el composer tras este
    addendum, ver "Decisiones de implementación".

## Dependencias agregadas
Ninguna.

## Decisiones de implementación

### `_QUICK_ACTIONS` se mantiene como catálogo aparte (no se fusiona con `listar_modos()`)
El addendum deja explícitamente abierta esta decisión de flujo de datos ("Nota de
frontera", fuera de alcance visual). Se optó por la opción más simple: mantener
`_QUICK_ACTIONS` en `bridge.py` con una sola entrada en vez de agregar "Recuérdame algo" al
catálogo de `core/composer_modes.py::listar_modos()`. Motivo: "Recuérdame algo" no tiene
`tool_names`/`tarea`/`prompt_hint` y nunca se comporta como un modo real (no threading hacia
`reasoning_loop.run()`); forzarlo dentro de `ModoComposer` habría requerido volver esos 3
campos opcionales solo para un caso que no los usa, ensuciando el contrato que consume
`core/reasoning_loop.py`.

### `.chip`/`.chip-risk-dot` y la rama `kind == "action"` se dejan como código muerto
El addendum deja explícitamente a criterio de `orion-dev` si retirar el CSS/código ahora
sin consumidor. Se optó por no retirarlo en esta pasada: `run_chip_action()` y la rama
`action` de `_build_quick_actions_payload()` siguen siendo el mecanismo real por el que el
agente ejecuta `take_screenshot`/`open_browser` bajo otras superficies (ninguna referencia
lo prueba directamente todavía, pero la SPEC del addendum es explícita en que esa capacidad
no se toca) — retirarlas habría sido un cambio de alcance no pedido. `.chip*` en CSS queda
igual de inerte y de bajo riesgo.

### `white-space: nowrap` agregado a `.mode-btn` (detalle no listado en la tabla de tamaños del addendum)
La tabla de `ui-design-026-addendum-1.md` §3 solo especifica `padding`/`font-size`/`gap`.
Se agregó además `white-space: nowrap` en `.mode-btn` como resguardo propio (no pedido
explícitamente): sin esto, si el cálculo de ancho del addendum resulta más ajustado de lo
estimado en el ancho real de ventana, el label de un botón individual podría partirse en dos
líneas en vez de forzar el `flex-wrap: nowrap` de la fila a manifestarse de otra forma
(botones empujándose fuera del contenedor visible). Es un cambio de bajo riesgo y reversible
si `orion-tester`/Johan lo consideran innecesario.

### Ajuste de 5 elementos en una sola fila: estimado, no verificado en navegador real
Tal como el propio addendum aclara, el cálculo de `ui-design-026-addendum-1.md` §3 es una
estimación por conteo de caracteres (~13% de margen), no una medición en un navegador real.
No se corrigió el tamaño una segunda vez (instrucción explícita del addendum: si no entra,
el fallback es acortar el label a "Recordar", no volver a tocar `padding`/`font-size`).
**Queda pendiente de confirmación visual real** — recomendado que `orion-tester` lo
verifique al correr `test_webview_smoke.py`/`test_webview_buttons.py` con la ventana real
(`QWebEngineView` offscreen), donde si el layout rompiera el `nowrap` sería visible en el
DOM renderizado.

## Tests impactados — señalado para `orion-tester`, NO corregidos en esta pasada

Instrucción explícita del coordinador: los tests son propiedad de `orion-tester`, así que se
señalan acá en vez de editarlos en silencio. Se corrió la suite completa después de todos
los cambios de código de este addendum:

`python -m pytest tests/ --tb=line -q` → **4 failed, 1822 passed** (contra 1793 passed/2
failed de la entrega anterior — el resto del delta son los tests que `orion-tester` agregó
en su pasada previa, incluido `tests/test_composer_modes.py`, que no se ve afectado por este
addendum porque cubre `core/composer_modes.py`, un módulo que el addendum no toca).

Los 4 tests que fallan, y por qué:

1. **`tests/test_webview_bridge.py::test_request_initial_state_emite_chips_theme_y_conversaciones`**
   (línea ~112) — asume `len(payload["quick_actions"]) == 3` con las etiquetas
   `{"Recuérdame algo", "📷 Captura de pantalla", "🌐 Abrir navegador"}`. Con el addendum,
   `quick_actions` tiene 1 solo elemento.
2. **`tests/test_webview_bridge.py::test_build_quick_actions_payload_consulta_risk_level_en_el_momento`**
   (línea ~372) — asume 2 `action_chips` + 1 `template_chip` = 3 total. Con el addendum,
   `_QUICK_ACTIONS` no tiene ningún elemento `kind == "action"` (0 action_chips, 1
   template_chip).
3. **`tests/test_webview_buttons.py::test_un_chip_de_plantilla_prellena_el_campo`** (línea
   ~376) — hace `document.querySelectorAll('.chip')[0]` para ubicar "Recuérdame algo".
   Con el addendum ya no se renderiza ningún `.chip` en el composer (ahora es `.mode-btn`),
   así que el selector devuelve una NodeList vacía y `[0]` es `undefined` — el `.click()`
   revienta.
4. **`tests/test_webview_buttons.py::test_un_chip_de_accion_ejecuta_su_accion`** (línea
   ~386) — busca `.chip` con `.chip-risk-dot` para disparar `take_screenshot` desde la UI.
   Con el addendum no queda ningún acceso rápido de tipo `action` en el composer (la
   capacidad sigue viva en `run_chip_action()`, pero sin botón), así que no hay ningún
   `.chip` que encontrar.

Los 4 necesitan reescritura de `orion-tester` acorde al nuevo catálogo/DOM (1 quick action,
`#actions-row` con `.mode-btn` para "Recuérdame algo", sin `.chip` vivo en el composer) — no
son regresiones de comportamiento, son aserciones que describen la forma **anterior** al
addendum.

## Verificación local (addendum 1)
- `python -m py_compile ui/webview/bridge.py` → OK.
- `node --check` OK en `composer.js`, `app.js` (no se tocó `bridge_client.js` en este
  addendum).
- HTML/CSS sin herramienta de lint dedicada en este pipeline — verificado por lectura y por
  el hecho de que `test_webview_smoke.py` (que sí renderiza `index.html`/`composer.css` en
  un `QWebEngineView` real) sigue pasando.
- `python -m pytest tests/ --tb=line -q`: **1822 passed, 4 failed** — los 4 detallados
  arriba, todos preexistentes a esta pasada en el sentido de que ya estaban desactualizados
  respecto al nuevo catálogo, no causados por un bug nuevo. Ningún test que pasaba antes de
  este addendum se rompió.
- Verificado con `grep` que no queda ninguna referencia viva (fuera de comentarios
  explicativos) a `#modes-row`/`#quick-actions-row` en `ui/`.
