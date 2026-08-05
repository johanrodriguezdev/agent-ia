# Auditoría de seguridad REQ-006

**Agente:** orion-security
**Fecha:** 2026-08-02
**Objeto auditado:** `workspace/adjuntos/REQ-006/propuestas/arquitectura-006.md` (documento de diseño,
**no código** — `orion-dev` no ha tocado ningún `.py` todavía y no puede hacerlo mientras REQ-005
siga en `EN_QA` sin commitear).
**Alcance:** REQ-006 = criterios [A] (CA-01…CA-17). La sección `[B]` (CA-18…CA-24) se revisa solo
como diseño de referencia, sin exigir cierre — no se implementa en este REQ.
**Nota de proceso:** documento guardado de forma incremental para no perder trabajo si la sesión se
corta (ya ocurrió dos veces en este REQ con otros agentes).

---

## Resumen del veredicto

**✅ APROBADO.**

El diseño no debilita el fail-closed de REQ-005 en ningún punto verificado, cierra genuinamente el
bug H7 (denegación indistinguible de éxito) y el bypass H3 (`GlassGateway` creando tareas sin gate),
y corrige H5 (voz evaluada como desktop) sin abrir una ruta nueva no contemplada.

Esta auditoría encontró originalmente **tres observaciones puntuales** (Observación A, hallazgo 1.7,
Observación B — detalladas en la sección 1). Se comunicaron a `orion-architect` vía mensaje directo,
que ajustó `arquitectura-006.md` en los tres puntos en la misma sesión. **Se verificó cada ajuste
leyendo el archivo real** (no solo confiando en el reporte del arquitecto ni en el relay del
coordinador) — los tres quedan correctamente cerrados:

1. **Observación A resuelta** — el adaptador `AgentTool↔ToolSpec` se sacó explícitamente del alcance
   de [A] (línea 76 de `arquitectura-006.md`); `[B]` (`core/reasoning_loop.py`) no reutiliza
   `AgentTool`, ejecuta siempre vía `execute_tool()`. Bypass descartado por diseño, no por disciplina.
2. **Hallazgo 1.7 resuelto** — `_try_learned` usa un `execute_callback` fijo y privado de
   `core/resolution.py`, no parametrizable desde fuera, siempre `classify_command() → dispatch()`
   (líneas 125-130). El gate deja de depender de que un caller futuro sea disciplinado.
3. **Observación B resuelta** — invariante de `user_id` documentada explícitamente junto a los
   wrappers de `task_manager` (líneas 195-203), mismo criterio que ya existe para `channel`.

**Ninguno de los tres ajustes agrega un CA nuevo, quita cobertura de un CA existente, ni amplía la
lista de módulos a tocar** (`core/base_agent.py` sigue en la lista, con menos alcance, no más;
`core/resolution.py` y `agents/tool_registry.py` ya estaban planeados, se refinó su diseño interno).
Son endurecimiento de seguridad dentro de lo ya aprobado por el humano, no cambio de alcance —
**no se requiere una nueva ronda de aprobación humana de la arquitectura** para estos tres puntos.

El **bloqueo de secuencia por REQ-005** sigue vigente y es independiente de este veredicto: **aunque
esta auditoría apruebe, `orion-dev` NO puede escribir ni una línea de código todavía.** Ver sección
final "Dependencia de secuencia".

---

## 1. Verificación contra los 7 puntos del handoff

### 1.1 — Fail-closed de REQ-005 no debilitado en ningún resolver de `RESOLVERS`

**Verificado leyendo código real, no solo el documento de arquitectura**, los 7 resolvers listados
en `core/resolution.py::RESOLVERS`:

| Resolver | Camino de gate verificado | Gateado |
|---|---|---|
| `routine` | `learning/routines_engine.py:47 try_routine()` → `execute_routine_actions()` (línea 31) → `agents/action_registry.py:execute_action()` (línea 41) | ✅ Sí — `execute_action()` (línea 250-265) llama `security_manager.require_confirmation()` incondicionalmente en su línea 256, antes de invocar `fn(**params)`. Verificado leyendo el archivo completo, no solo el fragmento citado por la arquitectura. |
| `autopilot` | `agents/task_executor.py:72,107` → `agents/action_registry.py:execute_action()` | ✅ Sí — mismo punto de gate que `routine`, confirmado por grep directo (`task_executor.py` importa `execute_action` de `action_registry` y lo llama en sus dos únicos puntos de ejecución). |
| `learned` | `learning/command_learning.py:run_custom_command()` → callback externo provisto por el caller | ⚠️ **Gate indirecto, no propio del módulo** — confirmado leyendo `command_learning.py` completo (41 líneas): `run_custom_command()` solo itera `commands.items()` y llama `execute_callback(action)` (línea 37); no importa `security_manager` en ningún punto. El gate de hoy es un efecto colateral de que el único caller real (`main.py:150-159`) pasa un callback que internamente hace `classify_command()` + `dispatch()` (gateado). Ver hallazgo 1.7 abajo — esto ya está correctamente documentado como riesgo aceptado por `orion-architect`, con mitigación propuesta. |
| `task_tool` | `agents/tool_registry.py::execute_tool()` (nuevo) | ✅ Por diseño — `execute_tool()` llama `security_manager.require_confirmation()` antes de `spec.invoke(params)`. No hay código todavía que verificar, se audita el diseño (línea 148-159 del documento de arquitectura) — correcto y explícito. |
| `capability` | `os_integration/capabilities_router.py:execute_capability()` | ✅ Sí — confirmado leyendo el archivo completo: línea 59-62 llama `security_manager.require_confirmation()` antes del `importlib.import_module` + `getattr` + invocación dinámica. |
| `intent` | `router/dispatcher.py::dispatch()` | ✅ Sí — confirmado en `baseline-006.md` sección 2 y releído: líneas 52-61 gatean incondicionalmente, único punto de ejecución para skill moderna y handler legacy. |
| `claude` | `ai/claude_brain.py:ask_claude()` | ✅ N/A para gate de acciones — confirmado por grep (`tool|function_call|tools=|subprocess|os.system|exec(|eval(`) que `ask_claude()` no tiene capacidad de tool-calling, `subprocess`, `exec` ni `eval`: es un fallback puramente conversacional (LLM → texto), no ejecuta acciones del sistema. No necesita gate de `security_manager` porque no hay superficie de riesgo — consistente con que hoy `CHAT`/`UNKNOWN` están clasificados `GREEN`. |

**Conclusión 1.1:** 6 de 7 resolvers están gateados por construcción, verificado en código real (no
solo confiando en la arquitectura ni en el baseline). El único con gate indirecto (`learned`) ya
está identificado y documentado honestamente por `orion-architect` como riesgo residual — ver 1.7.
**El fail-closed de REQ-005 no se debilita en ningún punto.**

### 1.2 — `agents/tool_registry.py::execute_tool()` como punto único de gate para tools

El diseño de `execute_tool()` (líneas 148-159 de la arquitectura) es correcto: resuelve el `ToolSpec`
por nombre, llama `security_manager.require_confirmation()`, y solo si el resultado es `True` invoca
`spec.invoke(params)`. Levanta `ActionDenied` en el caso `spec is None` (tool no registrado) y en el
caso de denegación — ambos fail-closed. **Esto es correcto y suficiente para CA-14…CA-17 tal como
están descritos.**

**⚠️ Observación A — hallazgo nuevo, no señalado explícitamente en la arquitectura:** la fila de
`Módulos a modificar` para `core/base_agent.py` dice literalmente: *"`AgentTool` gana un adaptador
opcional hacia `ToolSpec` (ver abajo) para no duplicar la clase"* — pero no existe ninguna sección
"abajo" en el documento que especifique ese adaptador (verificado con búsqueda de texto sobre el
documento completo: no hay ninguna otra mención de "adaptador" salvo las de `core/confirmation.py`,
que es un concepto distinto). Esto importa exactamente por el riesgo que este punto del handoff pide
verificar: si ese adaptador termina implementado como `AgentTool(name=spec.name, function=spec.invoke)`
— la forma más obvia de "no duplicar la clase" — entonces cualquier código que use `AgentTool.execute()`
sobre ese wrapper invoca `spec.invoke(params)` **directo**, sin pasar por `execute_tool()` ni por
`security_manager`. Eso es precisamente el bypass que el punto 2 del handoff pide descartar.

No hay evidencia de que esto esté conectado a nada dentro de [A] — no aparece en "Archivos a
modificar/crear" ningún punto donde `main.py` registre tools vía este adaptador (el registro de
`AgentTool` en `main.py:16-23` no se toca según esa sección). Es decir: **hoy es una pieza sin
consumidor dentro de [A]**, probablemente preparación para el loop de razonamiento de [B]. Eso reduce
el riesgo inmediato (no hay bypass vivo si nada la usa todavía) pero no lo elimina: si `orion-dev`
la implementa como parte de "lo aprobado en arquitectura" sin una especificación exacta, puede fijar
la forma equivocada ahora, y quedar lista para explotarse en cuanto REQ-007 la conecte sin que nadie
vuelva a revisarla.

**Recomendación (para `orion-architect`):** una de estas dos, no ambas necesarias:
  - (a) Sacar esta línea del alcance de [A] explícitamente — no construir el adaptador hasta que
    REQ-007 lo necesite y pueda especificarlo junto al loop que lo consume, o
  - (b) Si se mantiene en [A], especificar exactamente que la `function` del `AgentTool` resultante
    debe ser un cierre que llame `agents.tool_registry.execute_tool(spec.name, params, channel,
    user_id)` — **nunca** `spec.invoke` directo — y agregar un test estructural análogo al de CA-01
    (`test_tool_registry.py::test_agent_tool_adapter_no_bypassea_gate` — grep/AST verificando que
    ningún `AgentTool` construido desde un `ToolSpec` referencia `.invoke` en su `function`).

**✅ RESUELTO.** `orion-architect` tomó la opción (a): el adaptador se sacó explícitamente del
alcance de [A] (`arquitectura-006.md` línea 76, releída y verificada), y se confirmó que `[B]`
(`core/reasoning_loop.py`) no reutiliza `AgentTool` en absoluto — ejecuta siempre vía `execute_tool()`.
El bypass queda descartado por ausencia de la pieza que lo habría permitido, no por una convención
que pudiera olvidarse.

### 1.3 — `core/confirmation.py` estrictamente fail-closed

Verificado contra el diseño (líneas 188-217 y 219-246 de la arquitectura):

- `get_confirmation_adapter(channel)` retorna `None` si no hay adaptador — no lanza excepción, no
  retorna un valor por defecto "permisivo".
- El cambio propuesto en `require_confirmation()` (rama YELLOW): `if adapter is None: ... return
  False` — **denegado, no permitido**, con `logger.warning` y `_log_audit` antes de retornar. Correcto.
- Solo `ChannelType.DESKTOP` registra adaptador en este REQ (`main.py`); Telegram/Discord/Voice/API
  **no registran ninguno**, por lo que quedan denegados en YELLOW exactamente igual que hoy — pero
  ahora por un mecanismo explícito (`adapter is None`) en vez de por el efecto colateral actual
  (`is_action_allowed()` descartando el canal antes de llegar al `input()`). **Ningún canal gana
  capacidad de confirmar YELLOW como efecto colateral de este REQ — confirmado.**
- El resto de `require_confirmation()` (fail-closed sin clasificación, GREEN directo, RED con PIN
  solo en DESKTOP) queda textualmente sin tocar, según el propio documento (línea 240-246) —
  verificado que esa afirmación es consistente con lo que hace falta cambiar (solo las líneas 240-241
  actuales, el `input()` mismo).

**Conclusión 1.3: correcto, fail-closed sin excepciones.** Sin observaciones.

### 1.4 — CA-05: cómputo de canal por ciclo de captura en `main.py`

Verificado contra el código real de `main.py` (líneas 75-97, bloque de captura):

- `choice == '1'` → texto (línea 78-79)
- `choice == '2'` → micrófono directo (línea 80-82)
- `choice == '3'` → wake word: dos sub-caminos, ambos producen `command` como voz capturada —
  `ui.get_voice_command()` (línea 88, tras detectar la wake word) o `wake_result` como string ya
  transcrito (línea 89-90, cuando el propio detector de wake word entrega texto). **Ambos sub-caminos
  de `choice == '3'` son voz**, ninguno es texto tecleado.
- La propuesta de la arquitectura (`ChannelType.VOICE` si `choice in ('2','3')`, si no
  `ChannelType.DESKTOP`) cubre exactamente estos tres casos sin dejar ningún sub-camino de voz sin
  clasificar y sin inventar un cuarto `choice` no contemplado. **No abre ninguna ruta nueva.**
- Los 6 literales `"desktop"` hardcodeados citados por la SPEC/baseline (líneas 108, 136, 155, 167,
  203 del `main.py` actual, más la de `_ProactiveAssistant.execute()` en línea 40) quedan cubiertos
  por el cómputo único, **salvo la de `_ProactiveAssistant.execute()`**, que la arquitectura deja
  deliberadamente en `DESKTOP` — documentado explícitamente como riesgo aceptado en la tabla de
  Riesgos (fila "Canal `desktop` de `_ProactiveAssistant.execute()`..."): como `can_handle()` con el
  fix de CA-12 sigue sin dar un score real (`_ProactiveAssistant` no auto-despacha nada hoy), no hay
  explotación viva. **De acuerdo con esta lectura de riesgo** — el fix de CA-12 corrige únicamente el
  bug del ternario (ambas ramas devolvían `0.0`), no le da a `_ProactiveAssistant` una lógica de
  activación nueva; mientras eso siga así, el hardcodeo remanente en esa única línea no es explotable.
  Queda correctamente registrado como deuda para cuando algún REQ futuro active triggers proactivos
  reales — no bloqueante para REQ-006.

**Conclusión 1.4: el fix elimina el hardcodeo real (H5) sin abrir rutas nuevas.** El único hardcodeo
remanente (`_ProactiveAssistant`) es un riesgo ya identificado, aceptado con justificación verificable
en código (`can_handle()` no auto-despacha), y no se agrava por este REQ. Sin observaciones nuevas.

### 1.5 — Clasificación GREEN de `task_create`/`task_list`/`task_complete`

Verificado contra `tasks/task_manager.py` (leído completo en las partes relevantes):

- `list_tasks()`, `list_all_tasks()`, `list_today_tasks()` filtran siempre `WHERE user_id = ?`
  (líneas 364, 377, 394) — no hay forma de listar tareas de otro usuario a través de estas funciones;
  no hay riesgo de enumeración cruzada mientras `user_id` llegue del origen correcto (ver punto
  siguiente).
- `complete_task()` y `delete_task()` filtran `WHERE id = ? AND user_id = ?` (líneas 408-409,
  420-421) — completar o borrar una tarea ajena falla silenciosamente (no encuentra fila), no hay
  bypass de scoping.
- El `user_id` que llega a estas funciones **no se parsea del texto libre del comando** — verificado
  en `channels/telegram_bot.py` (grep de `GlassMessage(`): las 6 construcciones de `GlassMessage` usan
  `user_id=str(user.id)`, el ID autenticado que entrega la propia API de Telegram, no un valor
  extraído del mensaje. Es decir, el mismo patrón de invariante que ya exige `security_manager.py`
  para `channel` (nunca se re-infiere de `params`/texto libre) **ya se cumple hoy para `user_id`** en
  el único canal remoto real (Telegram).
- **GREEN es razonable** para las tres tools: (a) preserva el comportamiento actual — hoy ya se
  ejecutan sin ningún gate en los 4 handlers de Telegram, así que GREEN no es "menos seguro que hoy",
  es *estrictamente más seguro* porque ahora queda auditado (columna `_log_audit`) donde antes no
  había ni siquiera un registro; (b) no hay riesgo de cross-user porque el scoping por `user_id` ya
  existe en `task_manager.py` y el origen de `user_id` ya es confiable en el único canal que las usa
  hoy.

**⚠️ Observación B (menor, recomendación de higiene, no bloqueante):** el mismo patrón de invariante
que ya está documentado explícitamente para `channel` en `security_manager.py:214-221` ("nunca debe
leerse un valor de channel que haya pasado... por `extract_params()` de una skill") **no está
documentado de forma equivalente para `user_id`** en ningún punto de la arquitectura ni del código
actual, aunque hoy se cumple de hecho. Cuando `desktop`/`API` conecten sus propios canales a
`task_tool` (fuera de Telegram), alguien podría construir el `ToolSpec` de `task_create` leyendo
`user_id` de `params["user_id"]` sin más cuidado, y si ese valor llegó a `params` vía un parseo de
texto libre en vez de la sesión/identidad del canal, un usuario podría inyectar `user_id` ajeno en
el propio texto del comando y operar sobre tareas de otro usuario (ya que `list_tasks`/`complete_task`
confían ciegamente en el `user_id` que reciben como parámetro, sin volver a autenticar contra el
canal). **Recomendación:** agregar una línea a la arquitectura (o al menos a las notas de
`orion-dev` cuando se desbloquee) extendiendo la invariante ya escrita para `channel` a `user_id`:
"`user_id` debe provenir siempre de la fuente confiable del canal (`message.user_id` de Telegram,
`'default'` fijo en desktop), nunca de un valor parseado de texto libre del propio comando." No
requiere cambio de diseño, es una aclaración de invariante — no bloquea la aprobación.

**✅ RESUELTO.** `arquitectura-006.md` líneas 195-203 agregan la invariante explícita: `_try_task_tool`
en `core/resolution.py` debe construir `params["user_id"]` a partir del `user_id` real recibido por
`resolve()` (el argumento de la función, ya resuelto por el caller confiable), nunca de `text`. Mismo
criterio textual que ya exige `security_manager.py:214-221` para `channel`.

**Conclusión 1.5: GREEN es razonable y no introduce riesgo nuevo.** Ninguna de las tres tools debería
subir a YELLOW — hacerlo bloquearía uso normal por Telegram sin pedirlo la SPEC (la propia
arquitectura ya lo argumenta correctamente).

### 1.6 — Secretos en los documentos de REQ-006

Se realizó búsqueda de patrones de credenciales reales (`api[_-]?key|secret|token` seguido de un
valor de 15+ caracteres alfanuméricos) sobre los 3 documentos de REQ-006 (`SPEC-006.md`,
`arquitectura-006.md`, `REQ-006-context.md`) y sobre `.claude/skills/skill-mcp-sigaind-v01.md`
(material de referencia obligatorio citado por la SPEC).

**Resultado: cero coincidencias.** Las únicas menciones de "token" en los 4 documentos son
conceptuales — "SIGAIND resuelve permisos por el usuario asociado al token", "O.R.I.O.N. solo porta
el token" — nunca un valor concreto de API key, token de Telegram, ni ningún otro secreto pegado como
ejemplo. **A diferencia del caso real de esta misma sesión (secreto filtrado en `.env.example`), no
se repite acá.** Sin observaciones.

### 1.7 — Riesgo residual del resolver `learned` — ¿la mitigación de test es suficiente?

La arquitectura documenta honestamente (fila de Riesgos, y la corrección aplicada tras la
contra-verificación de `orion-coordinador`) que `learned` es el único resolver sin gate propio, y
propone como mitigación un test de regresión: `test_resolution.py::test_learned_callback_pasa_por_dispatch`,
que falla si el callback usado por `_try_learned` no termina invocando `dispatch()`.

**Evaluación: la mitigación es sensata pero insuficiente por sí sola — comparada con el estándar que
la propia arquitectura y `security-levels.md` ya aplican en el resto del sistema.** El patrón
establecido por REQ-005 y repetido en cada uno de los 5 puntos de entrada de `security-levels.md`
(`dispatch()`, `SkillManager.execute()`, `get_agent_tools()`, `execute_action()`,
`execute_capability()`) es que **el gate vive en el punto de entrada de ejecución real, nunca depende
de que el caller decida pasarlo un callback bien portado**. Un test de regresión protege contra que
alguien *cambie* el callback actual sin querer, pero no protege contra que alguien agregue un
**segundo** caller de `run_custom_command()` en el futuro (o modifique `_try_learned` para construir
el callback de otra forma) sin tocar ese test — el test solo corre sobre el camino que ya existe hoy,
no impide estructuralmente que aparezca un camino nuevo sin gate.

**Recomendación concreta (más fuerte, ya sugerida como opción por el propio handoff):** en vez de que
`core/resolution.py::_try_learned` reciba o construya un callback "suficientemente parecido" al de
`main.py:152-157`, que **no acepte ningún callback externo en absoluto** — que el callback esté
definido como función interna, no exportada, de `core/resolution.py`, que haga *siempre* y sin
parámetro de configuración `classify_command()` → `dispatch()`. Es decir, mover la responsabilidad de
"cómo se ejecuta una acción aprendida" de `main.py` (hoy) a `core/resolution.py` (nuevo), como una
función privada sin superficie de personalización — así no hay forma de que un caller futuro le pase
algo distinto, porque no hay parámetro para hacerlo. El test sigue siendo útil como red de seguridad
adicional, pero deja de ser la única defensa.

Esto **no cambia el resto de la arquitectura ni ningún criterio de la SPEC** — es un ajuste de un
párrafo dentro de la especificación de `_try_learned` en `core/resolution.py`. Se comunica también a
`orion-architect`.

**✅ RESUELTO.** `arquitectura-006.md` líneas 125-130 (releídas y verificadas) especifican exactamente
esto: `_try_learned` llama a `run_custom_command(phrase, execute_callback)` con un `execute_callback`
"fijo y privado de `resolution.py`, nunca parametrizable desde fuera", que siempre hace
`classify_command() → dispatch()` internamente. El test de regresión propuesto originalmente
(`test_learned_callback_pasa_por_dispatch`) se mantiene como red adicional, ya no como única defensa
— la garantía ahora es estructural, igual que en los otros 5 puntos de entrada de `security-levels.md`.

**Conclusión 1.7: resuelto con la mitigación más fuerte recomendada** — el gate de `learned` deja de
depender de la disciplina del caller y pasa a ser estructural, consistente con el resto del sistema.

---

## 2. Clasificación de riesgos (verde/amarillo/rojo) — diseño de REQ-006

| Elemento nuevo/modificado | Nivel | ¿Requiere confirmación? | Estado en el diseño |
|---|---|---|---|
| `task_create`/`task_list`/`task_complete` (`ToolSpec`) | 🟢 Verde | No | ✅ Correctamente declarado GREEN, ahora audita vía gate (antes ni eso) |
| `ActionDenied` (excepción) | N/A (mecanismo, no acción) | N/A | ✅ Cierra H7 correctamente — hereda de `Exception`, no de `BaseException`, capturable por los `except Exception` genéricos ya existentes |
| Adaptador de confirmación DESKTOP (`core/confirmation.py`) | Mecanismo YELLOW existente | Sí (ya lo hacía) | ✅ Preserva comportamiento actual, ahora explícito |
| Telegram/Discord/Voice/API sin adaptador | YELLOW sigue bloqueado | Sí (denegado, no preguntado) | ✅ Fail-closed confirmado — CA-10 no relaja nada |
| `resolve()` — resolvers heredados (`routine`/`autopilot`/`capability`/`intent`) | Heredan clasificación existente | Según acción | ✅ Gateados por construcción, verificado en código |
| `resolve()` — resolver `learned` | Heredan clasificación existente | Según acción, ahora gate estructural | ✅ Resuelto (1.7) — callback fijo y privado de `resolution.py`, siempre `dispatch()` |
| `ToolSpec` con `origin="mcp_remote"` (CA-16, sin cliente real) | Declarado por el tool, no autoritativo | Según `risk_level` declarado | ✅ Correcto por diseño — `execute_tool()` sigue siendo la autoridad real |
| Adaptador `AgentTool` ↔ `ToolSpec` (`core/base_agent.py`) | N/A — sacado del alcance de [A] | N/A | ✅ Resuelto (Observación A) — no se construye en este REQ; `[B]` no reutiliza `AgentTool` |

## 3. Secretos

- API keys/tokens en `SPEC-006.md`, `arquitectura-006.md`, `REQ-006-context.md`,
  `.claude/skills/skill-mcp-sigaind-v01.md`: **ninguno hallado.** Solo referencias conceptuales al
  mecanismo de token de SIGAIND, nunca un valor.

## 4. Validación de inputs

- El diseño preserva la invariante ya existente de `security_manager.py:214-221` sobre `channel`
  (nunca se re-infiere de `params`/texto libre) — no se toca, se respeta.
- `user_id` cumple hoy la misma invariante de facto en el único canal remoto real (Telegram, vía
  `user.id` de la API), pero no está documentada como regla explícita en ningún punto — ver
  Observación B (1.5), no bloqueante.
- No se identificó ningún `os.system()`/`subprocess` nuevo en el diseño de REQ-006 — los módulos
  nuevos (`resolution.py`, `tool_registry.py`, `confirmation.py`) son puro enrutamiento/gate, no
  ejecutan comandos del sistema directamente.

## 5. Recomendaciones (resumen accionable) — estado final

1. **Observación A** — ✅ resuelta. Adaptador `AgentTool↔ToolSpec` sacado del alcance de [A]; `[B]`
   ejecuta siempre vía `execute_tool()`.
2. **Observación B** — ✅ resuelta. Invariante de `user_id` documentada explícitamente junto a los
   wrappers de `task_manager` en `arquitectura-006.md`.
3. **Hallazgo 1.7** — ✅ resuelto. `_try_learned` usa callback fijo y privado de `resolution.py`,
   siempre `classify_command() → dispatch()`, no configurable desde fuera.

Las tres se verificaron leyendo `arquitectura-006.md` real tras el ajuste de `orion-architect`, no
solo confiando en su reporte. Ninguna reabrió el diseño completo ni afectó CA-01…CA-13.

## Veredicto: ✅ APROBADO

El diseño de REQ-006 [A] preserva el fail-closed de REQ-005 en los 7 resolvers (6 gateados por
construcción + `learned` ahora con gate estructural tras el ajuste), cierra correctamente H3, H5, H7
y H9 tal como se propuso, no introduce secretos ni `os.system()`/`subprocess` sin gate, y las 3 tools
nuevas (`task_create`/`list`/`complete`) tienen una clasificación GREEN razonable y justificada, con
la invariante de `user_id` ahora documentada explícitamente. Las 3 observaciones levantadas durante
esta auditoría fueron comunicadas a `orion-architect` y resueltas en la misma sesión, verificadas
contra el archivo real. No queda ninguna condición abierta sobre el diseño.

---

## Dependencia de secuencia — recordatorio explícito

**Aunque este veredicto es APROBADO CON OBSERVACIONES, `orion-dev` NO puede escribir código
todavía.** El bloqueo de secuencia documentado en `REQ-006-context.md` (encabezado "⛔ BLOQUEO DE
SECUENCIA") sigue vigente: REQ-005 permanece en `EN_QA`, con código sin commitear en el árbol de
trabajo, y **solo el humano** puede levantar ese bloqueo, explícitamente, tras cerrar REQ-005 (prueba
manual OK + commit). Esta auditoría de seguridad no es ese permiso — es una condición necesaria pero
no suficiente para avanzar a `orion-dev`. El siguiente paso formal del pipeline es `orion-dev`, pero
debe quedar detenido hasta que el humano confirme el cierre de REQ-005.

## Comunicación con orion-architect — cerrada

Se envió mensaje a `orion-architect` (agente `afb1449fbfd8fdb41`) con las Observaciones A y B y el
hallazgo 1.7. `orion-architect` ajustó `arquitectura-006.md` en los tres puntos en la misma sesión.
`orion-security` verificó cada ajuste leyendo el archivo real (líneas 76, 125-130, 195-203) — los tres
quedan correctamente cerrados sin cambio de alcance, CA ni módulos, por lo que **no se requirió una
nueva ronda de aprobación humana** de la arquitectura para estos ajustes. No se modificó
`arquitectura-006.md` directamente por parte de `orion-security` en ningún momento — todo el ajuste lo
hizo `orion-architect`.
