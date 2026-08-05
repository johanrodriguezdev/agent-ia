# Baseline REQ-006 — Pipeline único de resolución con paridad de canales [A]

**Agente:** orion-baseline
**Fecha:** 2026-08-02
**Alcance:** SOLO REQ-006 [A] (CA-01…CA-17). REQ-007 [B] no se toca acá.
**Nota de proceso:** Documento en redacción incremental — se guarda a medida que se verifica cada
archivo en código, para no perder trabajo si la sesión se corta. NO se modificó ningún `.py`
(bloqueo de secuencia por REQ-005 sin commitear, vigente).

---

## Estado actual del sistema (antes del cambio)

### 1. `main.py` — pipeline propio, hardcodeo de canal, bug del ternario

Confirmado leyendo el archivo completo (266 líneas):

- **Registro de herramientas (líneas 16-23):** `orchestrator.register_tool()` registra primero
  `dispatcher` (línea 16-20, wrapping de `dispatch_as_tool`) y luego, en un `for`, las tools de
  `skill_manager.get_agent_tools()` (línea 22-23). Confirma H7(a) de la SPEC: el legacy siempre es
  la primera opción que ve `_DynamicAgentInstance.execute()`.
- **Bug `can_handle()` confirmado línea por línea — línea 34:**
  ```python
  def can_handle(self, task: str) -> float:
      return 0.0 if "briefing" in task.lower() or "recordatorio" in task.lower() else 0.0
  ```
  Las dos ramas del ternario devuelven `0.0`. `_ProactiveAssistant` (líneas 28-47) nunca se activa
  vía este método. Es exactamente CA-12.
- **Loop principal `main()` (líneas 54-224):** un único `while True` que mezcla captura de input,
  ejecución de rutinas, autopilot, comandos aprendidos, capacidades del SO, clasificación y
  despacho — todo inline, sin pasar por un punto único de resolución.
- **Hardcodeo de `channel="desktop"` confirmado en las 6 líneas exactas que cita la SPEC:**
  - Línea 40: dentro de `_ProactiveAssistant.execute()`, llamando a `orchestrator.process_task(...,
    channel="desktop", ...)`.
  - Línea 108: dentro del bloque de rutinas directas, `try_routine(command, channel="desktop")`.
  - Línea 136: dentro del bloque autopilot, `executor.execute(plan, ..., channel="desktop")`.
  - Línea 155: dentro de `execute_simulated_action()` (comandos aprendidos), `act_params["channel"]
    = "desktop"`.
  - Línea 167: capacidades directas del SO, `try_capability(command, channel="desktop")`.
  - Línea 203: bloque final de despacho normal, `params["channel"] = "desktop"` justo antes de
    `dispatch(intent, params)`.
- **Confirmado H5 (canal `voice` nunca se emite):** `choice == '2'` (línea 80-82, micrófono directo)
  y `choice == '3'` (línea 83-97, wake word) ambos terminan escribiendo `command` como string y
  cayendo en el **mismo** bloque de ejecución que `choice == '1'` (texto), que es el que contiene
  las 6 líneas de arriba. No existe ninguna bifurcación por `choice` en el bloque de ejecución
  (línea 102 en adelante) que distinga voz de texto. El wake word que entrega texto ya capturado
  (línea 89, `wake_result` como string) tampoco se distingue — cae en el mismo camino.
- **No hay un punto único de resolución.** Antes de llegar a `classify_command` (línea 184) hay
  cuatro caminos de salida temprana con `continue`/`break` propios: rutinas directas (105-117),
  autopilot (119-147), comandos aprendidos (149-162), capacidades del SO (164-176). Cada uno decide
  por su cuenta si "resolvió" la tarea, sin pasar por el orquestador ni por el dispatcher.
- **`TEACH_COMMAND` (líneas 186-201)** es otro camino de captura interactiva de voz/texto
  (`ui.get_voice_command()` / `ui.get_text_command()`) que tampoco emite canal — mismo patrón.

### 2. `router/dispatcher.py` — intents fijos y gate de seguridad

Confirmado leyendo el archivo completo (100 líneas):

- **`dispatch(intent, params)` (líneas 20-85)** mapea **26 valores de `Intent`** (diccionario
  `routes`, líneas 21-48) a handlers de `executor.handlers` / `executor.system_action_handlers`.
  Confirma el número exacto ("~26 intents fijos") de la SPEC y el contexto.
- **El gate de seguridad de REQ-005 ya está integrado acá, antes de elegir camino** (líneas 52-61):
  ```python
  if not security_manager.require_confirmation(
      action_name, params.get("channel"),
      details=format_details(f"dispatch:{action_name}", params),
  ):
      return "⛔ Acción no autorizada."
  ```
  Es el **único** punto de gate para los dos caminos de ejecución (skill moderna vía
  `skill_manager.execute()`, líneas 70-73, y handler legacy vía `routes.get()`, línea 84-85). El
  comentario del propio código (líneas 52-55) documenta la intención: "su decisión es la
  autoridad. Ninguna ruta... puede ejecutar nada si acá se denegó". Este gate **ya es fail-closed**
  y es el que REQ-005 dejó funcionando — CA-07 debe preservarlo intacto.
- **Confirma el defecto de H7(b) exacto** en la línea 61: la denegación es el string literal
  `"⛔ Acción no autorizada."` — es justamente lo que `_DynamicAgentInstance.execute()` (ver más
  abajo) NO reconoce como fallo porque no empieza con `"Error"`.
- **`dispatch_as_tool(params)` (líneas 88-99)** es el wrapper que `main.py:16-20` registra como
  primera `AgentTool` (`name="dispatcher"`). Clasifica el texto con `classify_command` y llama a
  `dispatch()` — es decir, cualquier tarea que pase por el bucle agéntico intenta primero
  re-clasificar y re-despachar como si fuera un comando directo, antes de llegar a cualquier skill
  registrada después en el `for` de `main.py:22-23`.
- **Handling de excepción de skill (líneas 70-82):** si `skill_manager.execute()` lanza, se hace
  fallback silencioso (solo `logger.error`) al handler legacy — **sin volver a pedir confirmación**,
  documentado explícitamente en el comentario (línea 77-78) como decisión deliberada porque el gate
  ya se evaluó arriba, una sola vez, para la invocación completa.
- **No hay ningún `async def`** en este archivo — línea base 0 para CA-11.

### 3. `channels/gateway.py` y `channels/telegram_bot.py` — pre-matching por canal (H4)

Confirmado, complementa el diagnóstico ya verificado (no se re-descubre, solo se fija línea base
exacta para REQ-006):

- **`channels/gateway.py`** tiene tres métodos de pre-resolución de tareas **antes** de que el
  mensaje llegue al pipeline de clasificación general:
  - `_try_create_task()` (línea 110-148): detecta por triggers de texto si el mensaje es una
    solicitud de tarea/recordatorio y, si sí, crea la tarea directamente y devuelve una respuesta,
    sin pasar por `orchestrator` ni por `dispatcher`.
  - `_try_list_tasks()` (línea 149-164): igual, para listar tareas (`triggers` de línea 152).
  - `_try_complete_task()` (línea 165-173+): igual, para marcar tareas completas.
  Los tres retornan `None` si no matchean (dejando continuar el flujo normal) o una
  `GlassResponse` propia si sí — confirma H4 y H3 combinados: es la única ruta de acceso a
  `tasks/task_manager.py` hoy, y vive fuera del pipeline común.
- **`channels/telegram_bot.py`** tiene matching de frases de apagado/reinicio en **dos puntos**
  (confirmados, no en las mismas líneas exactas que cita la SPEC —548/602 coinciden en el archivo
  actual sin commitear— pero mismo patrón en ambos):
  - Línea 548-553: bloque de voz (`voice_mode`), matchea `"apaga el pc"` / `"apagar el pc"` /
    `"apaga la pc"` / `"apagar la computadora"` → `_handle_shutdown()`; y `"reinicia el pc"` /
    variantes → `_handle_restart()`.
  - Línea 602-607: bloque equivalente para texto normal, mismos triggers reducidos.
  - **Dato nuevo no anticipado por la SPEC textual:** `_handle_shutdown()` (línea 622+) y
    `_handle_restart()` (línea 655+) **ya llaman a `security_manager.require_confirmation()`**
    (líneas 628-632 y 658-662) con el comentario explícito `# REQ-005: mismo criterio que
    _handle_shutdown() — gate central, no pre-chequeo.` Es decir: el **matching de frases** (qué
    intención es) sigue siendo propio de Telegram y ocurre antes del pipeline común (H4 vigente),
    pero la **autorización** de la acción ya pasa por el gate central de REQ-005. CA-02 debe
    eliminar el matching de frases (la detección de intención), no el gate — que ya está correcto
    y debe preservarse.

**Hallazgo aportado por orion-coordinador durante este baseline, verificado en código — un
TERCER motor de resolución, no solo dos.** No son dos pipelines con distinto orden (main.py vs.
dispatcher/orchestrator): son **tres motores de resolución completos y dos "cerebros" de respaldo
distintos**. `telegram_bot.py` **nunca** llama a `orchestrator.process_task()` ni a `dispatch()`
directamente desde sus handlers — `handle_text`, `handle_voice`, `handle_photo` y
`handle_document` (líneas 562, 616, 711, 759) llaman **todos** a `GlassGateway().process(msg)`
(`channels/gateway.py:42-108`), que es su propio pipeline con su propio orden interno: (1)
`_try_create_task()` / `_try_list_tasks()` / `_try_complete_task()` (líneas 58-70) — matching de
substrings sobre texto crudo, antes de cualquier clasificación, mismo patrón de riesgo que el bug
de `_decompose()`; **dato adicional verificado:** `_try_create_task()` llama a
`task_manager.create_from_natural()` (línea 133) **sin pasar por
`security_manager.require_confirmation()`** en ningún punto del método, a diferencia del gate ya
integrado en `_handle_shutdown`/`_handle_restart` de Telegram — riesgo a resolver en arquitectura,
no corregido acá; (2) si ninguno matchea, recién ahí `classify_command(text)` (línea 77) — la
**misma** función que usan `main.py` y `core/orchestrator.py`: el mismo texto puede clasificarse
hasta tres veces por tres caminos distintos según el canal; (3) si `intent == Intent.UNKNOWN` o el
mensaje es imagen (línea 84): `_ask_claude_for_user()` → `ai/claude_brain.py:ask_claude()` (línea
228) — un **segundo cerebro conversacional**, distinto por completo del "agente" de
`core/orchestrator.py`/`core/base_agent.py` (que, como se documenta abajo, ni siquiera consulta un
LLM). **No verificado en este baseline** si `ask_claude()` comparte historial de conversación con
`agent_context_manager` — queda como pregunta abierta explícita para `orion-architect`; (4) si el
intent es conocido y no es imagen (línea 86-92): recién ahí llama a `orchestrator.process_task()`.
`main.py` (escritorio), en cambio, no pasa por `GlassGateway` en absoluto — su bloque final de
despacho (línea 184-204) clasifica y llama `dispatch()` directo, sin pasar siquiera por
`orchestrator.process_task()`. **Dimensión para `orion-architect`:** hoy hay tres superficies de
resolución con capacidades distintas — (a) `main.py`: clasificador → `dispatch()` directo, sin
`task_manager`, sin `GlassGateway`, sin agente; (b) `GlassGateway.process()` (Telegram y cualquier
canal que lo reutilice): pre-matching de tareas propio → clasificador → `orchestrator.process_task()`
**o** `ask_claude()` como fallback de `UNKNOWN`; (c) el "agente" interno de
`core/orchestrator.py`/`core/base_agent.py`, que en teoría es el cerebro pero hoy es un `for` sin
LLM. Explica de forma mecánica y completa por qué Telegram alcanza `task_manager` y escritorio no:
no le falta una ruta puntual a escritorio, corre por un sistema de resolución completo y distinto,
con su propio fallback de IA. El punto único de resolución que exige CA-01 debe absorber los tres,
no solo main.py y dispatcher.

### 4. `core/orchestrator.py` — el cortocircuito clasificador→agente

Confirmado leyendo el archivo completo (162 líneas):

- **`process_task()` (líneas 35-49) es el punto de entrada actual**, pero no es único: `main.py` no
  lo usa como entrada obligatoria salvo en el camino de `_ProactiveAssistant` (línea 38) y en el
  fallback final del `while` (implícito vía `dispatch()` directo, línea 204 — **ni siquiera pasa
  por `orchestrator.process_task()`**, llama a `classify_command` y `dispatch` directamente).
  Confirma H1 y H4 combinados: no solo el orquestador cortocircuita, sino que `main.py` ni siquiera
  entra siempre por el orquestador.
- **El cortocircuito de H1, confirmado exacto (líneas 39-43):**
  ```python
  quick_result = self._try_quick_dispatch(text, channel, user_id)
  if quick_result is not None:
      ...
      return quick_result
  result = self._process_with_agents(text, channel, user_id)
  ```
  `_process_with_agents` (el camino "inteligente") solo se alcanza si `_try_quick_dispatch`
  devuelve `None`.
- **`_try_quick_dispatch()` (líneas 51-74):** clasifica con `self._classifier(text)`; si
  `intent == Intent.UNKNOWN` devuelve `None` (línea 60-61, único caso que deja pasar al agente);
  si no, ejecuta `self._legacy_dispatcher(intent, params)` y **retorna de inmediato** el string del
  handler (línea 63, 71). Nótese: cualquier excepción interna también devuelve `None` (línea
  72-74, `except Exception` con `logger.debug` — silencioso a nivel INFO, pero sí registrado).
- **Bug `_decompose()` confirmado exacto (líneas 87-98)** — reparto ya decidido a [B]/CA-24, se
  documenta acá solo como evidencia de baseline:
  ```python
  simple_triggers = ["y", "luego", "después", "además", "también", "al mismo tiempo", "mientras", "and", "then"]
  for trigger in simple_triggers:
      if trigger in text.lower():
          parts = [p.strip() for p in text.split(trigger) if p.strip()]
  ```
  `"y"` como trigger de un `.split()` de Python parte por la **subcadena** "y" en cualquier
  posición, no por palabra completa — confirma el ejemplo de la SPEC (`"ayúdame..."` →
  fragmentado). No se toca en REQ-006.
- **`_execute_agent_chain()` (líneas 118-149):** confirma el caso borde de la SPEC — el resultado
  previo se pasa como texto plano concatenado en `enriched_task` (línea 123-125:
  `f"{subtask}\n\nResultado previo: {previous_result}"`), no como estructura.
- **No hay ningún `async def` en este archivo** — relevante para CA-11 (línea base: 0 `async` en
  `core/orchestrator.py` hoy).

### 5. `core/base_agent.py` — el bucle que no es un bucle

Confirmado leyendo el archivo completo (108 líneas). Coincide exactamente con H7 de la SPEC, sin
matices adicionales:

- **`AgentTool` (líneas 7-20):** contrato hoy es solo `name`, `description`, `function`. Sin
  esquema de parámetros, sin nivel de riesgo declarable, sin resultado estructurado. `execute()`
  (línea 13-20) captura excepciones y devuelve `f"Error en herramienta '{self.name}': {str(e)[:100]}"`
  — nótese que **este** es el único camino que sí antepone la palabra `"Error"`; la denegación del
  gate (`"⛔ Acción no autorizada."`, ver dispatcher arriba) no pasa por acá, es un `str` de retorno
  normal de `self.function(params)`, así que no lleva el prefijo `"Error"`. Confirma exactamente
  el mecanismo del defecto CA-09 debe cerrar.
- **`_DynamicAgentInstance.execute()` (líneas 94-107) — el corazón de H7, confirmado línea por
  línea:**
  ```python
  def execute(self, task: str, context: dict = None) -> str:
      logger.info(...)
      for tool in self.tools:
          try:
              result = tool.execute({...})
              if result and "Error" not in result[:10]:
                  return result
          except Exception as e:
              logger.debug(...)
      return f"No pude completar la tarea '{task[:60]}' con las herramientas disponibles."
  ```
  Confirmado exacto: **no hay ninguna llamada a un LLM en todo el archivo**. `self.system_prompt`
  se recibe en `__init__` (heredado de `BaseAgent`, línea 24-28) y no se lee en ningún punto de
  `execute()`. El heurístico de "éxito" es `"Error" not in result[:10]` — comparación de subcadena
  sobre los primeros 10 caracteres, exactamente como describe H7(b) y CA-09(b).
- **`DynamicAgentFactory` (líneas 49-83):** recibe `llm_provider` en `__init__` (línea 50, guardado
  en `self._llm`) y **`self._llm` no se lee en ningún otro punto del archivo** — confirmado con
  lectura completa, no hay ninguna otra referencia a `self._llm`. `_generate_prompt()` (línea
  70-78) construye un prompt completo con la lista de herramientas y nunca se pasa a nada que
  consulte un LLM — se usa únicamente como el `system_prompt` que `_DynamicAgentInstance` guarda y
  no lee.
- **Cache de agentes por hash de tarea** (líneas 54-59, 65-66): mismo texto de tarea siempre
  reutiliza el mismo agente — nota de diseño relevante para [B], no bloqueante para [A].
- **No hay ningún `async def`** en este archivo — línea base 0 para CA-11.

### 6. `core/security_manager.py` — `require_confirmation()`, `input()` bloqueante, `CHANNEL_ALLOWED_LEVELS`

Confirmado leyendo el archivo completo (342 líneas). Nota importante: **este archivo ya tiene
trabajo de REQ-005 sin commitear** (fail-closed, `resolve_channel()`, deny-list roja completa,
`_DETAILS_ALLOWED_KEYS` como allowlist) — coincide con el estado que describe
`.claude/rules/security-levels.md` bajo "REQ-005 — deny-list Rojo aplicada en código". REQ-006 debe
construir sobre esto, no reintroducirlo.

- **`CHANNEL_ALLOWED_LEVELS` confirmado exacto (líneas 29-36):**
  ```python
  ChannelType.DESKTOP: [RiskLevel.GREEN, RiskLevel.YELLOW],
  ChannelType.TELEGRAM: [RiskLevel.GREEN],
  ChannelType.DISCORD: [RiskLevel.GREEN],
  ChannelType.VOICE: [RiskLevel.GREEN],
  ChannelType.API: [RiskLevel.GREEN],
  ChannelType.UNKNOWN: [RiskLevel.GREEN],
  ```
  `VOICE` ya está correctamente limitado a solo verde — el problema no es esta matriz (que **no se
  toca** en este REQ, confirmado), es que ningún caller emite `ChannelType.VOICE` (ver hallazgo de
  `main.py` arriba). La matriz es la línea base exacta que CA-08(f)/CA-10(f) exige preservar
  **sin cambios**.
- **`resolve_channel()` (líneas 155-167):** ya existe y ya resuelve `None` o valores desconocidos a
  `ChannelType.UNKNOWN` (GREEN-only) en vez de a `DESKTOP` — es decir, el fail-closed de canal
  **ya está implementado** de REQ-005. El defecto de H5 no es que falte esta función: es que
  `main.py` nunca le pasa `"voice"`, siempre `"desktop"` explícito.
- **`require_confirmation()` confirmado línea por línea (líneas 207-260) — el corazón de H9:**
  - Línea 223: `channel = self.resolve_channel(channel)` — se resuelve primero.
  - Líneas 224-228: `level is None` → **bloqueado fail-closed**, ya implementado (REQ-005).
  - Líneas 229-231: `GREEN` → permitida directo.
  - **Líneas 232-248 — el bloque YELLOW, foco exacto de H9/CA-10:**
    ```python
    if level == RiskLevel.YELLOW:
        if not self.is_action_allowed(action_name, channel):
            ...
            return False
        msg = f"¿Estás seguro de que quieres ejecutar '{action_name}'?"
        ...
        response = input(f"\n⚠️  {msg}\nEscribe 'sí' para confirmar, o cualquier otra cosa para cancelar: ")
        confirmed = response.strip().lower() in ("sí", "si", "yes", "s")
        ...
        return confirmed
    ```
    Confirmado exacto: `input()` está en la línea 240 tal como cita la SPEC. **Antes** de llegar
    ahí, `is_action_allowed()` (línea 233, que internamente usa `CHANNEL_ALLOWED_LEVELS`) ya
    descartó el canal si no admite YELLOW — es el chequeo de canal previo que la SPEC describe como
    "lo único que evita hoy el cuelgue": para `TELEGRAM`, `DISCORD`, `VOICE`, `API`, `YELLOW` nunca
    está en `get_allowed_levels()`, así que `require_confirmation()` **nunca llega** a la línea
    240 desde esos canales hoy. Solo `DESKTOP` puede llegar al `input()`.
  - **Líneas 249-259 — bloque RED:** confirma que RED **nunca** se auto-autoriza salvo
    `channel == ChannelType.DESKTOP and self.has_pin()` (línea 252) con PIN maestro verificado por
    `require_pin()` (que a su vez usa `getpass.getpass`, bloqueante igual que `input()` pero solo
    alcanzable desde DESKTOP). Confirma el límite textual de la SPEC: "ROJO no se toca... con la
    excepción del PIN maestro solo en DESKTOP".
- **Registro de acciones (líneas 266-341):** `_register_default_actions()`,
  `_register_intent_actions()` (28 intents, líneas 303-318 — coincide con "28 intents" citado en
  toda la SPEC) y `_register_action_registry_actions()` se ejecutan **a nivel de módulo** al
  importar (líneas 339-341), fuera de cualquier función. Confirma que hoy la clasificación de
  riesgo es estática y cargada una sola vez al arrancar — relevante para CA-07 (recorrer "el
  registro completo de herramientas") y para CA-15 (nivel declarable por herramienta remota, que
  hoy no existe ningún mecanismo para).
- **No hay ningún `async def`** en este archivo — línea base 0 para CA-11. Confirmación explícita
  también relevante porque es el archivo que CA-10 va a tocar para desacoplar `input()`: la línea
  base de "0 async" debe mantenerse incluso después de introducir el adaptador de confirmación por
  canal.

---

## Archivos que serán modificados (previsión, según SPEC-006 §"Módulos afectados" y verificación
propia en código)

| Archivo | Por qué (evidencia verificada en este baseline) |
|---|---|
| `main.py` | Deja de ser un pipeline propio con 4 salidas tempranas (rutinas, autopilot, comandos aprendidos, capacidades SO) y 6 líneas hardcodeadas de `channel="desktop"` (40, 108, 136, 155, 167, 203). Debe emitir `voice` real desde `choice == '2'`/`'3'` y desde el wake word (línea 89). Fix de `can_handle()` en línea 34 (CA-12). |
| `core/orchestrator.py` | `process_task()` deja de ser opcional para `main.py` (hoy el bloque final del loop, línea 204, llama `dispatch()` directo sin pasar por el orquestador). El cortocircuito `_try_quick_dispatch` → retorno inmediato (líneas 39-43) es de [B], pero el punto de entrada mismo se toca en [A] para volverse el único. |
| `core/base_agent.py` (`AgentTool`) | Contrato hoy es solo `name`/`description`/`function` (líneas 7-20). [A] le agrega esquema de parámetros JSON Schema, nivel de riesgo declarable y resultado estructurado con denegación distinguible (CA-09, CA-14, CA-15). |
| `core/security_manager.py` | `require_confirmation()` (líneas 207-260) desacopla el `input()` de la línea 240 del stdin del proceso, delegando al adaptador del canal (CA-10). `CHANNEL_ALLOWED_LEVELS` (líneas 29-36) **no se toca** — confirmado como límite explícito de la SPEC. |
| `router/dispatcher.py` | Se integra al pipeline único (CA-01) conservando intacto el gate ya fail-closed de líneas 52-61 — es el que ya cumple REQ-005 y no debe reintroducirse ni debilitarse. |
| `channels/gateway.py` | `GlassGateway.process()` (líneas 42-108) es hoy un tercer motor de resolución completo (pre-matching de tareas → clasificador propio → `orchestrator.process_task()` o `ask_claude()`), no solo un pre-chequeo puntual. `_try_create_task()`/`_try_list_tasks()`/`_try_complete_task()` (líneas 110-173+) dejan de pre-resolver tareas fuera del pipeline y se convierten en herramientas gateadas de `task_manager` (H3, punto 7 de Alcance [A]). **Riesgo nuevo verificado:** `_try_create_task()` invoca `task_manager.create_from_natural()` sin pasar por `security_manager.require_confirmation()` — hoy no gateado. Conserva el aislamiento por usuario (caso borde explícito de la SPEC). |
| `ai/claude_brain.py` | Segundo "cerebro" de respaldo, distinto del agente de `core/base_agent.py`. `GlassGateway.process()` lo invoca como fallback de `Intent.UNKNOWN` o de mensajes con imagen (`_ask_claude_for_user()`). No leído en detalle en este baseline; `orion-architect` debe confirmar si comparte historial con `agent_context_manager` antes de decidir cómo el punto único de resolución absorbe este fallback. |
| `channels/telegram_bot.py` | Elimina el matching de frases de apagado/reinicio (líneas 548-553, 602-607) que decide la *intención* antes del pipeline común (CA-02). El gate que ya llaman `_handle_shutdown()`/`_handle_restart()` (líneas 628-632, 658-662) se conserva — no es lo que hay que eliminar. Implementa el pedido de confirmación por botones inline (H9/CA-10/Decisión 7). |
| `ui/` (GUI PyQt6, CLI) | Implementan el pedido de confirmación de su canal: diálogo modal y prompt de consola (H9). No leído en detalle en este baseline — `orion-architect` debe inspeccionarlo antes de diseñar el adaptador. |
| `tasks/task_manager.py` | No cambia su lógica (confirmado por la SPEC); se envuelve como herramienta gateada. No leído en detalle — su superficie pública debe inspeccionarse en arquitectura para definir el wrapper de `AgentTool`. |
| `tests/` | Tests nuevos para CA-01 a CA-17. `tests/test_classifier.py` deja de colectar 0 (CA-13) — ver línea base exacta abajo. |

**Nota de alcance:** no se leyeron en este baseline `ui/gui.py`, `ui/cli.py`, ni la superficie
pública completa de `tasks/task_manager.py` — la SPEC los menciona como afectados pero el diagnóstico
de código ya verificado (contexto + SPEC) no trae hallazgos línea-por-línea de ellos como sí trae de
los 5 archivos núcleo de arriba. `orion-architect` debe leerlos antes de diseñar el contrato de
confirmación por canal y el wrapper de `task_manager`.

---

## Fallos pre-existentes (no atribuibles a este REQ)

Comando ejecutado: `cd agente_ia && python -m pytest tests/ --tb=short`

```
collected 54 items
tests/test_agents.py .....                                    [  9%]
tests/test_security_manager.py ......................................... [ 85%]
........                                                       [100%]
54 passed, 1 warning in 5.97s
```

**Ninguna falla.** Los 54 tests que sí colectan (49 de `tests/test_security_manager.py`, herencia de
REQ-005, y 5 de `tests/test_agents.py`) pasan todos en verde hoy, antes de que REQ-006 toque nada.
Este es el número exacto que CA-07 exige preservar sin modificación.

Único warning, no bloqueante: `tests/test_agents.py::test_ca1_orchestrator` devuelve
`AgentOrchestrator` en vez de `None` (`PytestReturnNotNoneWarning`) — cosmético, no afecta el
resultado, no se toca en este REQ.

**Confirmado el hallazgo H8 de la SPEC, no asumido:** se corrió explícitamente
`pytest tests/test_classifier.py tests/test_dispatcher.py tests/test_autopilot.py
tests/test_memory.py --collect-only`:

```
collected 0 items
no tests collected in 1.60s
```

Los 4 archivos existen en `tests/` pero **no aportan ni un solo test colectable** — confirma
exactamente lo que dice la SPEC (scripts con `run_tests()`/`print`, sin `assert` ni funciones
`test_*`). Esta es la línea base **cero** que CA-13 debe convertir en cobertura real para
`test_classifier.py` (reconocimiento + ruteo). Los otros tres quedan como deuda registrada, fuera de
alcance de este REQ (Decisión 5 de la SPEC).

**No hay ningún fallo de compilación ni error de import** detectado en los 5 archivos núcleo leídos
para este baseline (`main.py`, `core/orchestrator.py`, `core/base_agent.py`,
`core/security_manager.py`, `router/dispatcher.py`) — se importan y ejecutan correctamente, como lo
demuestra que `pytest tests/` corrió sin errores de colección sobre el árbol completo.

---

## Cierre

Baseline completo para REQ-006 [A]. Los 5 archivos núcleo señalados en el handoff
(`main.py`, `core/orchestrator.py`, `router/dispatcher.py`, `core/base_agent.py`,
`core/security_manager.py`) fueron leídos en su totalidad y verificados línea por línea contra los
hallazgos H1-H9 de SPEC-006 — sin discrepancias encontradas entre lo documentado en la SPEC y el
código real. Se sumó verificación de `channels/gateway.py` y `channels/telegram_bot.py` (pre-matching
de H4) con un dato nuevo no anticipado textualmente por la SPEC: el gate de confirmación de
`_handle_shutdown()`/`_handle_restart()` en Telegram **ya está integrado** (trabajo de REQ-005 sin
commitear) — CA-02 debe eliminar el matching de frases (detección de intención), no ese gate.

**Ampliación del baseline (aportada por orion-coordinador, verificada en código antes de cerrar
este documento):** el sistema no tiene dos motores de resolución (main.py vs.
dispatcher/orchestrator) sino **tres** — `GlassGateway.process()` (`channels/gateway.py:42-108`,
usado por los cuatro handlers de `telegram_bot.py`) es un pipeline propio completo, con su propio
pre-matching de tareas (uno de ellos, `_try_create_task()`, sin gate de seguridad — riesgo nuevo) y
su propio fallback a un segundo cerebro conversacional, `ai/claude_brain.py:ask_claude()`, distinto
del agente falso de `core/base_agent.py`. Ver sección 3 arriba para el detalle completo. El punto
único de resolución que CA-01 exige debe absorber los tres motores, no solo dos.

No se modificó ningún archivo `.py`. Bloqueo de secuencia respetado en su totalidad.

