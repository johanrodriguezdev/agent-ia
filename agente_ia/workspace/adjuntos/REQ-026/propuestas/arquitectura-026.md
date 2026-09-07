# Arquitectura REQ-026 — Modos estratégicos en la barra de chips del composer

## Resolución de los 4 puntos que SPEC-026 dejó a criterio de orion-architect

Antes de la propuesta en sí, esto es lo que SPEC-026 pidió explícitamente confirmar o
ajustar (sección "Asumidos"). Johan debe leer esto con atención porque el punto 1
**corrige** una premisa de la SPEC, no solo la confirma.

### 1. Mapeo modo → skill/capacidad (CORRECCIÓN, no confirmación)

La SPEC asume `Investigación → web_browsing_skill/info_skill`. Revisé `skills/info_skill.py`
(`get_intents()` → `SYSTEM_INFO`, `CPU_INFO`, `RAM_INFO`) y **no tiene nada que ver con
investigar información**: son diagnósticos de hardware/SO locales (CPU, RAM, sistema).
Incluirlo en el modo Investigación priorizaría la herramienta equivocada cuando el usuario
pide, por ejemplo, "investigá qué es el protocolo MCP".

Mapeo corregido, a nivel de **tools** (no de skill completa, porque varias skills exponen
más de un intent y `agents/skill_tools.py` ya agrupa intents en tools — el mapeo fino real
pasa por ahí, no por la clase de skill):

| Modo | Tools priorizadas | Origen |
|------|--------------------|--------|
| Código/script | `EXECUTE_CODE` | `skills/code_execution_skill.py` (único intent) |
| Investigación | `web_search`, `web_read`, `wikipedia_search`, `BROWSE_WEB` | tools standalone de `agents/tool_registry.py` (`web_search`/`web_read`/`wikipedia_search`, líneas 502-578) + `web_browsing_skill.py` (`BROWSE_WEB`) |
| Nodos/flujos | `flujo` (family tool: listar/ejecutar/reanudar/cancelar), `CREATE_FLOW` | `skills/flow_skill.py`, ya agrupado por `agents/skill_tools.py::_FAMILIAS["flujo"]` |
| Tareas | `task_create`, `task_list`, `task_complete`, `task_complete_all` | tools standalone de `agents/tool_registry.py` (376-471), envoltorio de `tasks/task_manager.py` |

`info_skill.py` queda **fuera** de los 4 modos. No hace falta tocarlo ni crear nada nuevo
para cubrir su ausencia — el modelo sigue pudiendo usarlo libremente fuera de cualquier
modo, como hoy (nada se filtra, solo se reordena — ver punto 2).

### 2. Mecanismo exacto de "priorizar" sin bloquear

Confirmado que **no puede ser reordenar `RESOLVERS`**: desde REQ-006 el único resolver
activo en el camino normal es `("claude", _try_claude)` (`pending_dialog` es un caso
aparte, sin relación con los modos). Las 7 heurísticas legacy en `RESOLVERS_RETIRADOS`
solo corren en el camino "sin modelo" y no tienen ninguna noción de modo — no se tocan.

El mecanismo real vive un nivel más abajo, dentro de `core/reasoning_loop.py::run()`, con
dos palancas que se combinan (una sola no alcanza con todos los proveedores):

1. **Reordenar (nunca filtrar) el catálogo de tools.** `_build_tool_list()` hoy solo filtra
   por canal. Se le agrega un parámetro opcional `modo_def` que mueve las tools de
   `modo_def.tool_names` al frente de la lista que ya devuelve `catalogo_para_modelo()`,
   preservando el resto tal cual. Como es reorden y no filtro, cualquier otra tool sigue
   presente y disponible — satisface el caso borde de SPEC ("no debe bloquear una
   respuesta normal si el modelo decide que no hace falta usar esa capacidad").
2. **Una frase en el system prompt.** El reorden solo es una señal débil para varios
   proveedores (no todos respetan el orden de la lista de tools para decidir). Se agrega el
   `prompt_hint` del modo activo al final de `_build_system_prompt()` — con la misma
   redacción defensiva en las 4 frases ("si el pedido no tiene que ver con esto, respondé
   con normalidad"), para que el modelo no interprete el modo como una orden ciega.

Ninguna de las dos palancas toca `agents/tool_registry.py`: **decisión explícita de no
tocar ese archivo**. `catalogo_para_modelo()` es compartido con `ai/claude_brain.py`
(Telegram/Discord), que no tiene concepto de "modo" — filtrar/reordenar ahí arriesgaría
filtrar semántica de UI de escritorio hacia canales que no la tienen. El reorden vive
exclusivamente en `core/reasoning_loop.py`, aguas abajo de `catalogo_para_modelo()`, así
que Telegram/Discord quedan completamente afuera del cambio (ver Riesgos).

### 3. ¿Los 4 modos fijan `tarea`?

**No, solo 2.** Código (`tarea="modo_codigo"`) e Investigación (`tarea="modo_investigacion"`)
fijan tarea — son los casos donde tiene sentido rutear a un modelo especializado o más
barato (generación de código, resumen/búsqueda), en línea con el propósito original de
`task_providers` (rotar modelos gratis/baratos por tipo de tarea, ver REQ memoria de
proyecto). Nodos/flujos y Tareas **no** fijan tarea: ambos necesitan tool-calling multi-paso
con el modelo de razonamiento principal (crear un flujo, encadenar pasos, completar una
tarea con slot-filling) — rutearlos a un modelo alternativo sin verificar que soporte tools
igual de bien sería un riesgo funcional que la SPEC no pidió asumir. Ambos modos siguen
usando `tarea="razonamiento"` (el mismo criterio que hoy, sin modo activo).

Esto es una decisión de criterio técnico, no una imposición de la SPEC (que lo dejó
abierto). Johan puede ajustarla en la respuesta de aprobación si prefiere que los 4 fijen
tarea o que ninguno lo haga.

Las claves `modo_codigo`/`modo_investigacion` en `task_providers` son **opcionales y
aditivas**: si no existen en `config.json`, `destinos_de_tarea()` devuelve `[]` igual que
hoy para cualquier tarea sin configurar — el modo prioriza skill/prompt pero no fija
modelo, exactamente el comportamiento que pide el caso borde de config ausente. Este REQ
no necesita popular esas claves en `config.json` (SPEC explícita: "sin tocar el motor").

### 4. Dónde vive el estado de "modo activo"

Confirmado: **el frontend (`composer.js`) es la única fuente de verdad**, como asume la
SPEC — una variable de módulo, sin persistencia en `agent_context` ni DB, se resetea a
"sin modo" en cada conversación nueva o al cambiar de conversación.

Con un agregado no cubierto por la SPEC literal, que documento porque me pareció necesario
técnicamente: `Bridge` mantiene un **espejo efímero en memoria** (`self._modo_activo`,
atributo de instancia, nunca persistido a disco) — no como fuente de verdad, sino porque
`_build_models_payload()` (el patrón "fijado por tarea" de REQ-022) se invoca desde
`request_models()` de forma **desacoplada** de `send_message()` (al abrir el menú de
modelos — `composer.js:172` — y al arrancar la app — `app.js:204`). Sin ese espejo, el
selector de modelo no podría reflejar "fijado por el modo" hasta el próximo mensaje
enviado, violando CA de la sección "Ruteo de modelo por modo". El espejo:
- Se actualiza solo vía un slot nuevo (`set_active_mode`) que el frontend llama en el
  mismo click que activa/desactiva un modo — nunca se infiere ni se adivina server-side.
- **Nunca se usa para decidir el ruteo real de un turno** — `send_message(text, modo)`
  usa el argumento `modo` explícito de esa llamada, no el espejo. Si el espejo llegara a
  desincronizarse (p. ej. un fallo puntual de QWebChannel), el peor caso es una etiqueta
  del selector desactualizada, nunca una tarea mal ruteada.

---

## Cobertura de criterios de la SPEC

| Criterio (resumen) | Cómo lo satisface esta propuesta |
|---|---|
| Fila muestra exactamente 4 modos | `core/composer_modes.py::_MODOS` (4 entradas), consumido por `_build_modes_payload()` en bridge.py |
| Captura/Navegador siguen como accesos rápidos sin cambio de comportamiento | `_QUICK_ACTIONS` nuevo (reemplaza los 2 chips `kind="action"` de `_CHIPS`), `run_chip_action()` **no se toca** |
| "Recuérdame algo" sigue como acceso rápido | Pasa a `_QUICK_ACTIONS` como `kind="template"`, mismo comportamiento |
| "Resumen del día" desaparece | No se migra a ningún catálogo nuevo — se elimina al borrar `_CHIPS` |
| "Investigación rápida" ya no existe suelta | No se migra — su función la cubre el modo Investigación |
| Click activa/resalta un modo (toggle) | Estado `_activeModeId` en `composer.js`, clase `.mode-btn--active` (o equivalente que defina orion-ui) vía `aria-pressed` |
| Modo activo persiste a través de múltiples mensajes | Estado de módulo en JS, no se resetea entre envíos — solo por acción explícita del usuario o cambio de conversación |
| Click en modo activo lo desactiva | Toggle: mismo id → `null` |
| Click en otro modo lo reemplaza (nunca 2 activos) | Un único `_activeModeId`, no un Set/array |
| Estado por conversación, resetea en nueva/otra conversación | `resetActiveMode()` exportado, invocado desde `app.js` en `onConversationCleared` y dentro de `onTurnsLoaded` |
| Sin modo activo, comportamiento igual que hoy | `modo=""` → `get_mode(None)` → `None` → mismo `tarea="razonamiento"`, mismo catálogo sin reordenar, mismo prompt sin frase agregada |
| Modo Tareas usa tools existentes de `task_manager.py` sin ampliarlo | `tool_names=("task_create","task_list","task_complete","task_complete_all")`, cero cambios en `tasks/task_manager.py` |
| `task_manager.py` sin cambios de funcionalidad | Confirmado, no está en la lista de archivos a modificar |
| Cada modo puede declarar `tarea` opcional | `ModoComposer.tarea: Optional[str]`, solo 2 de 4 la declaran (ver punto 3 arriba) |
| Selector deshabilitado si `task_providers` fija destino para la tarea del modo | `_build_models_payload(tarea=...)` generalizado + `set_active_mode()` re-emite `models_loaded` al togglear |
| Modo activo gana sobre selección manual previa | Mismo mecanismo ya existente de REQ-022 (`_destinos_iniciales()` prioriza `task_providers` sobre `ai_provider`/`ai_model` de config) — no requiere código nuevo, solo que `tarea` ya no sea la constante `"razonamiento"` |
| Tarea sin destino fijado → selector elegible igual que hoy | `destinos_de_tarea(tarea)` devuelve `[]` → `fijado_por_tarea=None`, sin cambios en esa función |
| Desactivar modo restaura selector/ruteo previo | `set_active_mode("")` → tarea vuelve a `"razonamiento"` en el siguiente cálculo |
| Tokens de `theme.css`, sin sistema paralelo; estado activo no depende solo de color | Responsabilidad de `orion-ui` (ver handoff) — esta propuesta fija el contrato de datos/clase CSS, no los valores visuales |
| Modo activo + mensaje no relacionado no bloquea respuesta normal | Reorden (no filtro) de tools + frase defensiva en el prompt (ver punto 2) |
| Cancelar turno no desactiva el modo | `stopResolution()` no toca `_activeModeId` — módulos independientes |
| Adjunto viaja igual con modo activo | `_con_adjunto()` es un parámetro independiente de `modo` en `send_message()`, sin interacción |
| `task_providers` mal configurado/ausente no rompe el turno | Reutiliza `destinos_de_tarea()` tal cual, ya es tolerante a ausencia/error (confirmado en baseline) |
| Cambio de modo a mitad de streaming no afecta el turno en curso | `modo` se captura como argumento posicional al inicio de `send_message()`/`resolve()`/`run()` — el turno en vuelo usa el valor capturado, cambios posteriores de `_activeModeId` solo aplican al próximo `send_message()` |

---

## Módulos a modificar

- `ui/webview/bridge.py` — catálogo `_MODES`→`_QUICK_ACTIONS`, `send_message()`,
  `_build_models_payload()`, nuevo slot `set_active_mode()`.
- `ui/webview/frontend/js/composer.js` — split de `renderChips()`, estado de modo activo,
  reset exportado.
- `ui/webview/frontend/js/bridge_client.js` — wrappers `sendMessage(text, modo)`,
  `setActiveMode(modoId)`.
- `ui/webview/frontend/js/app.js` — parseo del nuevo payload de `chips_loaded`, hooks de
  reset en `onConversationCleared`/`onTurnsLoaded`.
- `ui/webview/frontend/index.html` — split de `#chips-row`.
- `ui/webview/frontend/css/composer.css` — estado visual "modo activo" (detalle: orion-ui).
- `core/resolution.py` — `resolve()` y `_try_claude()` aceptan `modo` opcional.
- `core/reasoning_loop.py` — `run()`, `_build_tool_list()`, `_build_system_prompt()` aceptan
  `modo`/`modo_def` opcional.

## Nuevas clases/funciones

- `ModoComposer` (dataclass, `core/composer_modes.py`, **archivo nuevo**) — `id, label,
  tool_names, tarea, prompt_hint`.
- `listar_modos()` en `core/composer_modes.py` — devuelve los 4 modos, en orden de UI.
- `get_mode(modo_id)` en `core/composer_modes.py` — resuelve id→definición, `None` si
  vacío/desconocido (fail-safe, nunca lanza).
- `Bridge.set_active_mode(self, modo_id: str) -> None` en `bridge.py` — nuevo `@pyqtSlot(str)`,
  actualiza el espejo `self._modo_activo` y re-emite `models_loaded`.
- `Bridge._tarea_activa(self) -> str` en `bridge.py` — helper privado, evita duplicar la
  lógica "modo activo con tarea fijada, si no `razonamiento`" en `request_models()` y
  `set_active_mode()`.
- `_build_modes_payload()` y `_build_quick_actions_payload()` en `bridge.py` — reemplazan
  `_build_chips_payload()`.
- `_reordenar_priorizando(catalogo, tool_names)` en `core/reasoning_loop.py` — helper puro,
  mueve al frente las tools cuyo `name` está en `tool_names`, preserva el resto.
- `composer.js::renderModes(modes)` / `renderQuickActions(items)` — reemplazan `renderChips()`.
- `composer.js::resetActiveMode()` — exportada, limpia `_activeModeId` y notifica al bridge.

## Flujo de datos

**Carga inicial / cambio de conversación:**
`request_initial_state()` (sin cambios en el disparador) → `_build_modes_payload()` +
`_build_quick_actions_payload()` → `chips_loaded.emit(json)` con forma
`{"modes": [...], "quick_actions": [...]}` → `app.js::onChipsLoaded` → `renderModes()` +
`renderQuickActions()`. Al crear conversación nueva (`conversation_cleared`) o cambiar a
una existente (`turns_loaded`), `app.js` llama `resetActiveMode()` antes/junto con el
render de turnos → `composer.js` limpia `_activeModeId` y llama `setActiveMode("")` →
`Bridge.set_active_mode("")` limpia el espejo y re-emite `models_loaded` con
`tarea="razonamiento"`.

**Click en un modo:**
`composer.js` toggle de `_activeModeId` → actualiza clase visual → `setActiveMode(id)` →
`Bridge.set_active_mode(id)` → valida con `get_mode()` → guarda espejo → recalcula
`_tarea_activa()` → `_build_models_payload(tarea=...)` → `models_loaded.emit(json)` →
`composer.js::renderModels()` (sin cambios) refleja "Fijado: ..." o selector habilitado,
según corresponda.

**Envío de un mensaje:**
`doSend()` → `sendMessage(text, _activeModeId || "")` → `Bridge.send_message(text, modo)`
→ `resolve(text, ChannelType.DESKTOP, user_id=OWNER_USER_ID, modo=(modo or None))` →
(camino `claude`) `_try_claude(text, channel, user_id, claude_fn=None, modo=modo)` →
`reasoning_loop.run(text, channel, user_id, estado=estado, modo=modo)` → dentro de `run()`:
`modo_def = get_mode(modo)` → `tools = _build_tool_list(resolved_channel, modo_def)`
(reorden, no filtro) → `system_prompt = _build_system_prompt(modo_def)` (agrega
`prompt_hint` al final) → `tarea = modo_def.tarea if modo_def and modo_def.tarea else
"razonamiento"` → `generate_response(..., tools=tools, tarea=tarea, ...)`.

Los canales que usan `claude_fn` (Telegram/Discord vía `channels/gateway.py`) siguen
llamando a `resolve()`/`_try_claude()` sin pasar `modo` — el parámetro por defecto es
`None`, cero cambio de comportamiento, ese branch de `_try_claude()` ni siquiera lee
`modo`.

## Archivos a modificar/crear

- `core/composer_modes.py` — **nuevo**.
- `ui/webview/bridge.py`
- `ui/webview/frontend/js/composer.js`
- `ui/webview/frontend/js/bridge_client.js`
- `ui/webview/frontend/js/app.js`
- `ui/webview/frontend/index.html`
- `ui/webview/frontend/css/composer.css`
- `core/resolution.py`
- `core/reasoning_loop.py`

No se toca `agents/tool_registry.py`, `tasks/task_manager.py`, `ai/llm_provider.py`
(motor), `core/security_manager.py`, ni `config.json` (las 2 claves nuevas de
`task_providers` quedan documentadas como opcionales, no es necesario crearlas para que el
REQ funcione).

## Dependencias nuevas

Ninguna. Confirmado: todo se apoya en módulos/capacidades ya existentes (`BaseSkill`,
`agents/tool_registry.py`, `ai/llm_provider.py::destinos_de_tarea()`, patrón REQ-022).

## Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| Agregar la frase del modo activo en medio del system prompt rompe el prefix-caching que hoy protege colocando fecha/hora al final | El `prompt_hint` se agrega también al final, inmediatamente antes del bloque de fecha/hora — el prefijo solo cambia cuando el usuario **cambia de modo**, no en cada mensaje dentro del mismo modo |
| El reorden de tools es una señal débil para proveedores que no respetan el orden de la lista al elegir tool | Se combina con la frase del prompt (palanca 2), redundante a propósito |
| `modo_id` desconocido/obsoleto llega desde un frontend cacheado tras cambiar el catálogo | `get_mode()` devuelve `None` sin lanzar — se trata como "sin modo", igual que el patrón ya usado para `task_providers` ausente |
| `send_message(self, text: str)` → `send_message(self, text: str, modo: str)` es un cambio de firma del slot Qt (rompe cualquier caller viejo) | Grep confirma un único call site (`composer.js::doSend()`); se actualiza en el mismo cambio. `tests/test_webview_bridge.py` y `tests/test_webview_buttons.py` quedan marcados como "requieren actualización" para orion-tester |
| Espejo `self._modo_activo` en `Bridge` podría desincronizarse del estado real en JS | Nunca se usa para decidir ruteo (`send_message` usa el argumento explícito de esa llamada) — el peor caso es una etiqueta de selector desactualizada hasta el próximo toggle/carga, nunca un turno mal ruteado |
| Reemplazar `_CHIPS` por dos catálogos nuevos rompe algo que dependía del payload plano de `chips_loaded` | Grep en `tests/` confirma que solo `tests/test_webview_bridge.py` referencia `chips_loaded` — impacto acotado y conocido de antemano |
| `EXECUTE_CODE` sigue siendo 🟡 amarillo (confirmado en `core/security_manager.py`) — priorizarlo desde el modo Código no debe saltarse la confirmación existente | No se toca `security_manager.py` ni el gate de `execute_tool()`; priorizar solo cambia qué tool ve primero el modelo, no el nivel de riesgo ni el flujo de confirmación |
| Dos REQs con cambios sin commitear tocan estos mismos archivos (bridge.py, reasoning_loop.py, composer.js, llm_provider.py) | orion-dev debe re-diffear el working tree exacto al implementar, no asumir los números de línea de este documento — señalado también por orion-baseline |

## Pruebas sugeridas (una por criterio, para orion-tester)

**Catálogo y convivencia**
- `chips_loaded` emite exactamente 4 entradas en `modes` con los ids/labels esperados.
- `quick_actions` contiene captura, navegador y "recuérdame algo"; no contiene "resumen del
  día" ni "investigación rápida".
- `run_chip_action("take_screenshot")`/`("open_browser")` se comportan igual que antes del
  cambio (test de regresión, no nuevo).

**Persistencia y estado visual**
- Click en modo inactivo → queda con clase/atributo "activo" (`aria-pressed="true"` o
  equivalente).
- Enviar 2 mensajes seguidos con el mismo modo activo → sigue activo después del segundo.
- Click en modo activo → vuelve a "sin modo" (`_activeModeId === null`).
- Click en modo A estando activo modo B → solo A queda activo.
- Simular `conversation_cleared` y `turns_loaded` con un modo activo → `_activeModeId` vuelve
  a `null` en ambos casos.
- Enviar mensaje sin modo activo (`modo=""`) → `resolve()`/`run()` reciben `modo=None`,
  comportamiento idéntico al pre-REQ-026 (test de no regresión).

**Modo Tareas**
- Con modo Tareas activo, pedir crear una tarea → el tool-call resultante es `task_create`
  (o uno de los 4 tools del modo), sin tocar `tasks/task_manager.py`.
- `tasks/task_manager.py` no cambia de comportamiento fuera del contexto de este REQ (test
  de regresión sobre los tests ya existentes de ese módulo).

**Ruteo de modelo por modo**
- Con `task_providers["modo_codigo"]` configurado y modo Código activo →
  `_build_models_payload()` devuelve `fijado_por_tarea` no nulo, selector deshabilitado.
- Con un modelo elegido manualmente ANTES de activar un modo con tarea fijada → al activar,
  el destino fijado por el modo gana (mismo criterio que REQ-022, test de integración).
- Con la tarea del modo activo SIN entrada en `task_providers` → selector elegible, igual
  que hoy sin modo.
- Desactivar el modo → `_build_models_payload()` vuelve a usar `tarea="razonamiento"`.
- `task_providers` con una entrada malformada para la tarea de un modo → no lanza excepción,
  se comporta como "sin fijar" (reusa test existente de `destinos_de_tarea()` con un caso
  nuevo de clave).

**Casos borde**
- Modo Código activo, mensaje "qué hora es" → el modelo responde con normalidad, sin forzar
  `EXECUTE_CODE` (verificar que la tool sigue disponible pero no se usa si no aplica).
- Cancelar un turno (`stopResolution()`) con un modo activo → `_activeModeId` no cambia.
- Adjuntar archivo con un modo activo → el adjunto viaja igual, sin interferencia del modo
  (test de regresión sobre `_con_adjunto()`).
- Cambiar `_activeModeId` mientras hay un streaming en curso → el turno en vuelo terminó
  usando el `modo`/`tarea` capturado al inicio, no el nuevo.

**Compilación/regresión**
- `python -m py_compile` sobre los 4 módulos Python modificados + el nuevo
  `core/composer_modes.py`.
- Suite completa de `pytest` sin nuevos fallos respecto del baseline (1795 passed).

---

## Recomendación explícita sobre `orion-ui`

**Sí, corresponde pasar por `orion-ui` antes de `orion-dev`.** Esta arquitectura fija el
contrato de datos (payload `{modes, quick_actions}`), la estructura del DOM (`#modes-row` +
`#quick-actions-row` reemplazando `#chips-row`) y el mecanismo de estado (clase/atributo
"activo" en el botón), pero **no** define tokens de color, tipografía, spacing, iconografía
por modo, ni el detalle de contraste AA que el criterio de rediseño visual exige
explícitamente verificar. Ese es trabajo de `orion-ui`, no de arquitectura — corresponde
tanto por categoría del REQ (UI) como porque hay un rediseño visual real pedido por Johan,
no solo un ajuste menor de estilos existentes.

---

## Estado del working tree al momento de diseñar

Reconfirmado antes de escribir esta propuesta que ninguno de los cambios sin commitear de
otros REQs en `ui/webview/bridge.py`, `core/reasoning_loop.py`, `ai/llm_provider.py` y
`composer.js` toca las funciones/líneas específicas que este documento modifica — mismo
hallazgo que reportó `orion-baseline`. orion-dev debe re-verificar el diff exacto al
implementar, ya que esos otros REQs siguen en curso y el working tree puede seguir
moviéndose.
