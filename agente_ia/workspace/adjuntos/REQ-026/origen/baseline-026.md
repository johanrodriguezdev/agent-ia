# Baseline REQ-026 — Modos estratégicos en la barra de chips del composer

## Estado actual del sistema

Hoy el composer tiene una única fila de chips (`#chips-row` en
`ui/webview/frontend/index.html:227`), sin ningún concepto de "modo activo" ni de
ruteo de tarea por chip. Todo turno de chat usa `tarea="razonamiento"` fijo.

### `ui/webview/bridge.py`
- `_CHIPS` (línea 75-82) es una lista plana de 5 dicts `{label, kind, payload}`:
  3 `kind="template"` (Resumen del día, Recuérdame algo, Investigación rápida — prellenan
  el input) y 2 `kind="action"` (📷 Captura de pantalla → `take_screenshot`, 🌐 Abrir
  navegador → `open_browser` — ejecutan directo vía `security_manager.classify_action()`).
  No hay agrupación en "modos" ni "accesos rápidos"; es un solo catálogo.
- `_build_chips_payload()` (línea 1965-1979) itera `_CHIPS` y le agrega `risk_level`
  calculado en el momento para los `kind="action"` (CA-40, nunca hardcodeado). Emite UNA
  sola señal `chips_loaded` (línea 164, `pyqtSignal(str)`) con la lista completa, llamada
  una única vez desde `request_initial_state()` (línea 285) al arrancar. No hay un segundo
  catálogo ni una segunda señal para "accesos rápidos" — hoy es todo un solo payload.
- `send_message()` (línea 298-333) no recibe ni threadea ningún parámetro de "modo": la
  firma del slot es `send_message(self, text: str)`, y llama a
  `resolve(text, ChannelType.DESKTOP, user_id=OWNER_USER_ID)` sin ningún dato de modo/tarea.
- `_build_models_payload()` (línea 1910-1947) ya tiene el patrón de "fijado por tarea"
  (REQ-022): consulta `destinos_de_tarea("razonamiento")` — con la tarea HARDCODEADA a
  `"razonamiento"`, no derivada de ningún modo — y arma `fijado_por_tarea: {"etiqueta": ...}`
  o `None`. Este es el mecanismo que SPEC-026 pide reutilizar/generalizar para la tarea del
  modo activo (CA-05 de REQ-022 ya cubierto: sin fijar = selector habilitado).
- **Nota de working tree:** `ui/webview/bridge.py` tiene cambios sin commitear de otro(s)
  REQ(s) en curso (+28/-0 líneas, ver `git diff --stat`) — no tocan `_CHIPS` ni
  `_build_chips_payload()` ni `send_message()` según lo revisado, pero orion-architect debe
  volver a mirar el archivo en el momento de diseñar, no asumir que sigue igual a este
  snapshot.

### `ui/webview/frontend/js/composer.js`
- `renderChips(chips)` (línea 119-151) recibe la lista plana del payload de arriba, la
  vacía y re-renderiza como botones `.chip`. Un solo bloque de lógica: si `kind==="action"`
  agrega un `chip-risk-dot`; el click hace `input.value = chip.payload` (template) o
  `runChipAction(chip.payload)` (action). No hay estado de "modo activo" en el frontend, ni
  variable ni `data-*` que lo represente — cada click es efímero, no hay toggle.
- No existe ningún llamado a `sendMessage()`/`send_message()` que incluya un modo: el envío
  de texto del composer (fuera de este fragmento leído) no tiene ningún parámetro de modo
  hoy.
- **Nota de working tree:** también tiene cambios sin commitear (+22/-en curso) de otro REQ;
  no tocan `renderChips()` según lo inspeccionado, pero mismo criterio que arriba —
  reconfirmar al momento de la arquitectura.

### `ui/webview/frontend/js/bridge_client.js`
- `onChipsLoaded(cb)` (línea 85) es un wrapper de una línea: `_bridge.chips_loaded.connect(cb)`.
  Un solo canal de señal, sin distinción entre modos y accesos rápidos. Sin cambios
  pendientes en git (working tree limpio para este archivo).

### `ui/webview/frontend/index.html`
- `#chips-row` (línea 227) es un único `<div>` vacío dentro de `#composer-inner`, poblado
  enteramente por JS (`renderChips()` hace `replaceChildren()` y agrega botones). No hay
  subdivisión de contenedor hoy (no hay `#modes-row` / `#quick-actions-row` ni similar).
  Working tree limpio.

### `ui/webview/frontend/css/composer.css`
- Reglas actuales relevantes: `#chips-row` (línea 20), `.chip` (27), `.chip:hover` (40),
  `.chip:focus-visible` (46), `.chip-risk-dot` (51) y sus 3 variantes de color
  `.chip-risk-{green,yellow,red}` (58-60) que consumen `var(--success)`, `var(--warning)`,
  `var(--danger)` de `theme.css`. No existe ninguna regla de estado "activo/toggle" para un
  chip — todo el feedback visual hoy es solo `:hover`/`:focus-visible`. `theme.css` ya
  define los 3 tokens de color de riesgo tanto en tema claro como oscuro (líneas 30-32,
  49-51, 72-74), reutilizables sin drift. Working tree limpio.

### `core/resolution.py`
- `resolve(text, channel, user_id="default", claude_fn=None)` (línea 826-881) es el punto
  único de resolución (CA-01 de REQ-005). Su firma NO tiene ningún parámetro de modo/tarea
  hoy. Camina `RESOLVERS = [("pending_dialog", _try_pending_dialog), ("claude", _try_claude)]`
  — desde REQ-006 el modelo lee primero; las 7 heurísticas legacy quedaron en
  `RESOLVERS_RETIRADOS` y solo corren en el camino "sin modelo". `_try_claude()` (línea
  656-692) llama a `core.reasoning_loop.run(text, channel, user_id, estado=estado)` sin
  pasar ningún dato de modo. No hay ningún mecanismo de "priorizar un resolver/skill" en
  este archivo hoy: el único "resolver" activo en el camino normal es `claude`, así que
  "priorizar" en la práctica tendrá que traducirse a algo que reciba `reasoning_loop.run()`
  (system prompt / catálogo de tools / `tarea`), no a reordenar `RESOLVERS`. Working tree
  limpio (sin cambios pendientes de otros REQs).

### `core/reasoning_loop.py`
- `run(task, channel, user_id="default", agent_name="reasoning_loop", estado=None)` (línea
  209 en adelante) no recibe modo ni tarea variable. La llamada a `generate_response()`
  (línea 252-260) usa `tarea="razonamiento"` como string literal fijo — comentario explícito
  en el código: "quien quiera mandarla a un modelo distinto... lo configura en
  `task_providers` sin tocar el resto del sistema", es decir, hoy `task_providers` solo se
  puede aprovechar para la tarea `"razonamiento"` porque es la única que este módulo emite.
  `_build_tool_list(resolved_channel)` (línea 228) arma el catálogo de tools que se ofrece
  al modelo filtrando solo por canal (vía `agents/tool_registry.catalogo_para_modelo()`),
  sin ningún filtro/priorización por modo.
- **Nota de working tree:** cambios sin commitear de otro REQ (+19/-en curso); no tocan
  `run()` en la porción inspeccionada arriba, pero reconfirmar al arquitecturar.

### `config.json` (`task_providers`)
- Hoy solo tiene UNA clave: `"razonamiento": {"proveedor": "deepseek", "modelo":
  "deepseek-chat"}`. No hay ninguna clave para modos ni para ninguna otra tarea. Cualquier
  clave nueva por modo (p. ej. `"modo_codigo"`, `"modo_investigacion"`) es aditiva —
  `ai/llm_provider.py::destinos_de_tarea(tarea)` ya lee de forma genérica por clave
  (línea 97-131) y tolera ausencia (se comportaría igual que "razonamiento sin fijar" hoy:
  selector habilitado, CA de casos borde de SPEC-026 ya cubierto por diseño existente).
- **Nota de working tree:** `config.json` no aparece en `git status` de este REQ (limpio) —
  pero SÍ aparece `requirements.txt` y `requerimientos.csv` modificados por trabajo previo
  no relacionado; no afecta a este REQ.

### `agents/tool_registry.py`
- `catalogo_para_modelo(channel=None)` (línea 68 en adelante) es el único punto que decide
  qué tools ve el modelo, y hoy filtra EXCLUSIVAMENTE por canal (`security_manager.
  get_allowed_levels(channel)`) — no existe ningún parámetro ni mecanismo de filtrado por
  modo/capacidad priorizada. Las tools de `tasks/task_manager.py` (`task_create`,
  `task_list`, `task_complete`, etc.) ya están registradas y expuestas al modelo sin
  distinción especial. Working tree limpio.

### Skills que los 4 modos van a priorizar (ya existen, confirmado por baseline)
`skills/code_execution_skill.py`, `skills/web_browsing_skill.py`, `skills/info_skill.py`,
`skills/flow_skill.py` y `tasks/task_manager.py` existen hoy en el repo y heredan de
`BaseSkill` (donde aplica) — no hace falta crear ninguno de los 4 para este REQ, tal como
asume la SPEC.

## Archivos que serán modificados (previsión)

- `ui/webview/bridge.py` — reemplazo de `_CHIPS`/`_build_chips_payload()` por catálogo de
  modos + accesos rápidos, threadeo de modo en `send_message()`, generalización de
  `_build_models_payload()`/`fijado_por_tarea` a la tarea del modo activo.
- `ui/webview/frontend/js/composer.js` — split de `renderChips()`, estado de modo activo en
  frontend, inclusión del modo en cada envío.
- `ui/webview/frontend/js/bridge_client.js` — cobertura del nuevo payload (uno o dos
  catálogos) en `onChipsLoaded()` o su reemplazo.
- `ui/webview/frontend/index.html` — reestructuración de `#chips-row` en fila de modos +
  fila/grupo de accesos rápidos.
- `ui/webview/frontend/css/composer.css` — reglas nuevas de estado "modo activo" (toggle
  resaltado) y separación visual modos/accesos rápidos.
- `core/resolution.py` — `resolve()` debe aceptar el modo activo (nuevo parámetro) y
  propagarlo hacia `reasoning_loop.run()`.
- `core/reasoning_loop.py` — `run()` debe poder recibir/derivar una `tarea` distinta de
  `"razonamiento"` según el modo, y ajustar el catálogo de tools/system prompt para
  priorizar la skill del modo.
- `config.json` — nuevas claves opcionales en `task_providers`, una por modo que decida
  fijar `tarea` (sin tocar el motor de `ai/llm_provider.py`).
- `agents/tool_registry.py` — posible ajuste de `catalogo_para_modelo()` (o un punto nuevo)
  para priorizar/reordenar el catálogo cuando el modo Tareas está activo.

No se tocan `tasks/task_manager.py`, `ai/llm_provider.py` (motor), ni `core/
security_manager.py` según el alcance de la SPEC.

## Fallos pre-existentes (no atribuibles a este REQ)

- **pytest:** `python -m pytest tests/ --tb=short -q` → **1795 passed, 0 failed** (102.44s).
  Ninguna falla preexistente en el área. Warnings no bloqueantes: deprecations de
  `speech_recognition` (`aifc`/`audioop`, Python 3.13) y `InconsistentVersionWarning` de
  scikit-learn al des-pickle el clasificador TF-IDF/SVM (versión 1.9.0 vs 1.8.0 instalada)
  — preexistentes, no relacionados con REQ-026.
- **py_compile:** `ui/webview/bridge.py`, `core/resolution.py`, `core/reasoning_loop.py`,
  `agents/tool_registry.py`, `ai/llm_provider.py` → compilan sin error.
- **Working tree con cambios pendientes sin commitear de otros REQs** (no son fallos, pero
  son estado a tener presente porque orion-architect va a diseñar sobre este working tree,
  no sobre el último commit): `ai/llm_provider.py` (+160/-…), `core/reasoning_loop.py`
  (+19/-…), `ui/webview/bridge.py` (+28/-0), `ui/webview/frontend/js/composer.js` (+22/-…).
  Ninguno de esos diffs toca, según lo inspeccionado en esta sesión, las funciones/líneas
  puntuales que SPEC-026 identifica (`_CHIPS`, `_build_chips_payload`, `send_message`,
  `renderChips`, `run()` con `tarea="razonamiento"`) — pero al no estar commiteados, el
  diff exacto puede seguir moviéndose antes de que `orion-dev` implemente.
