# Arquitectura REQ-006

> Documento único que cubre REQ-006 [A] (CA-01 a CA-17, alcance de ejecución de este REQ) y
> REQ-007 [B] (CA-18 a CA-24, diseñado aquí pero **no implementado** en este REQ — no debe cerrar
> puertas). Todo lo marcado `[B]` es diseño de referencia para el futuro `orion-architect`/`orion-dev`
> de REQ-007, no trabajo a ejecutar por `orion-dev` de REQ-006.
>
> Redactado leyendo código real (no supuestos): `core/security_manager.py`, `core/base_agent.py`,
> `core/orchestrator.py`, `router/dispatcher.py`, `channels/gateway.py`, `channels/telegram_bot.py`,
> `main.py`, `tasks/task_manager.py`, `ai/claude_brain.py`, `core/agent_context.py`, `ui/cli.py`,
> `ui/gui.py`. Referencias externas: `workspace/referencias/openclaw/01-seguridad-y-aislamiento.md`
> (§2.5 Exec Approvals), `workspace/referencias/openclaw/02-gateway-canales-ruteo.md` (§7 y §8,
> traducción directa a O.R.I.O.N.), `.claude/skills/skill-mcp-sigaind-v01.md` (contrato SIGAIND).

## Pregunta abierta resuelta

**¿`ai/claude_brain.py:ask_claude()` comparte historial con `agent_context_manager`?**

**No. Verificado leyendo ambos archivos completos.** `ask_claude()` mantiene su propio diccionario
módulo-global `_conversation_histories: dict[str, list[dict]]` (`ai/claude_brain.py:10`), en memoria
pura, sin persistencia, indexado solo por `user_id`. `AgentContextManager` (`core/agent_context.py`)
es una clase totalmente distinta, indexada por `(agent_name, user_id)`, con caché + persistencia en
SQLite (`agent_context.db`). No hay ninguna línea de código que conecte ambos. Son dos historiales de
conversación completamente aislados y hoy **ninguno de los dos se entera de lo que pasó en el otro**.

**Recomendación (adoptada por esta arquitectura):** el pipeline único de resolución (ver más abajo)
NO intenta unificar ambos historiales en este REQ — sería un cambio de comportamiento de memoria no
pedido por la SPEC y con riesgo de romper la personalización actual de Claude Brain. En su lugar, el
diseño **hace explícito el límite**: el resolver `claude_fallback` del pipeline sigue llamando a
`ask_claude()` tal cual, con su historial propio, y el pipeline registra el intercambio en
`agent_context_manager` **además** (no en vez de), igual que ya hace `_try_quick_dispatch()` hoy en
`core/orchestrator.py:64-70`. Así el trace unificado (CA-03) sabe que un mensaje fue resuelto por
`claude`, aunque el contenido de esa conversación siga viviendo en el store propio de Claude Brain.
Unificar los dos historiales de verdad es un REQ aparte (fuera de alcance, no forzarlo aquí).

## Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| CA-01 (punto único de resolución) | Nuevo `core/resolution.py:resolve()`. `main.py`, `channels/gateway.py`, `channels/telegram_bot.py` (vía gateway) llaman exclusivamente a esto; ninguno resuelve intent, ejecuta handler ni toca `task_manager` por su cuenta. |
| CA-02 (sin pre-matching de canal) | `channels/gateway.py::_try_create_task/_try_list_tasks/_try_complete_task` y `channels/telegram_bot.py`'s matching de "apaga el pc" (B6) se eliminan; su función pasa a ser un resolver (`task_tool`) dentro de `resolve()`. |
| CA-03 (traza idéntica) | `ResolutionResult.matched_by` + `tool`/`intent` + `params` — mismo resolver, mismo orden, para los tres canales; solo el veredicto del gate puede diferir. |
| CA-04 (mismo verdict path para yellow) | `resolve()` no ejecuta nada por sí mismo: entrega el intent/tool a `router/dispatcher.py:dispatch()` (para intents) o `agents/tool_registry.py:execute_tool()` (para tools), que son los dos únicos lugares que llaman a `security_manager.require_confirmation()`. Idéntico para los tres canales. |
| CA-05 (voice emite VOICE real) | `main.py` calcula `channel` una vez por ciclo de captura (`ChannelType.VOICE` si `choice in ('2','3')`, si no `ChannelType.DESKTOP`) y lo propaga a todas las llamadas del bloque de ejecución, reemplazando los 6 literales `"desktop"` hardcodeados que hoy ignoran el modo de entrada. |
| CA-06 (solo verde ejecuta por voz) | Ya garantizado por `CHANNEL_ALLOWED_LEVELS[ChannelType.VOICE] = [GREEN]` (no se toca) — con CA-05 corregido, ahora sí se aplica de verdad a comandos por voz. |
| CA-07 (fail-closed intacto) | Cero cambios a `CHANNEL_ALLOWED_LEVELS`, `require_confirmation()` sigue fail-closed por defecto. Se agrega tool `task_create`/`task_list`/`task_complete` a `security_manager` con `register_action(...)` — nunca se elimina una clasificación existente. Nuevo test de cobertura (ver Pruebas sugeridas). |
| CA-08 (riesgo no delegado al canal) | El nuevo `ToolSpec.risk_level` (CA-14/15) es **declarativo**, nunca autoritativo — `execute_tool()` sigue llamando a `security_manager.require_confirmation()`, que puede endurecer pero nunca relajar lo declarado. `CHANNEL_ALLOWED_LEVELS` sigue siendo la única fuente de verdad de qué nivel corre en qué canal. |
| CA-09 (denial estructurado, no substring) | Nueva excepción `core/security_manager.py::ActionDenied`. `dispatch()` y `execute_tool()` la levantan en vez de retornar el string `"⛔ Acción no autorizada."`. Cierra el bug H7 de `core/base_agent.py:103` (`"Error" not in result[:10]`) reemplazando ese chequeo por `except ActionDenied: continue`. |
| CA-10 (confirmación agnóstica de canal) | Nuevo `core/confirmation.py` con registro de adaptadores por canal (`register_confirmation_adapter`). `require_confirmation()` deja de llamar a `input()` directo y consulta el adaptador del canal resuelto; canal sin adaptador registrado ⇒ denegado (fail-closed, nunca cuelga). Ver sección dedicada más abajo. |
| CA-11 (core sin async) | Todo lo nuevo (`resolution.py`, `tool_registry.py`, `confirmation.py`, el cambio en `security_manager.py`) es 100% síncrono. Los adaptadores de confirmación de canales async (Telegram/Discord) hacen el puente ellos mismos hacia afuera del core — ver sección dedicada. |
| CA-12 (bug `can_handle()`) | `main.py:34` — un solo `if/else` real en vez de un ternario que retorna `0.0` en ambas ramas. |
| CA-13 (cobertura ejecutable) | `tests/test_classifier.py` y `tests/test_dispatcher.py` (hoy 0 tests) reciben casos reales de recorrido `resolve() → dispatch()/execute_tool()` con `channel` real por caso, no solo clasificación aislada. |
| CA-14 (contrato isomorfo a MCP) | `agents/tool_registry.py::ToolSpec` — `name`, `description` (NL), `parameters_schema` (JSON Schema), `risk_level`, `invoke`, `origin`. Misma clase para tools locales y tools remotos declarados (CA-16). |
| CA-15 (riesgo declarado, no autoritativo) | `ToolSpec.risk_level` es un input a `security_manager.register_action()`; el gate real sigue siendo `require_confirmation()`. Un tool sin `risk_level` no se registra silenciosamente en GREEN — `register_action()` exige el valor y el registro fail-closed de `classify_action()` bloquea si no está. |
| CA-16 (tools remotos, sin cliente real) | `ToolSpec.origin: Literal["local","mcp_remote"]`. `tests/test_tool_registry.py` construye un `ToolSpec` con `origin="mcp_remote"` a partir de un fixture estático que imita la respuesta de discovery de SIGAIND (`.claude/skills/skill-mcp-sigaind-v01.md`) y prueba que `execute_tool()` lo trata igual — sin red, sin cliente MCP. |
| CA-17 (sin modelo multiusuario) | No se diseña ningún campo de usuario/tenant en `ToolSpec` — el `[B]` que consuma tools remotos (REQ futuro de integración SIGAIND) resuelve el `empId` desde el token en el momento de invocar, fuera de este contrato. `ToolSpec` solo necesita poder cargar credenciales por *origen de tool*, no por usuario de O.R.I.O.N. |
| CA-18 a CA-24 `[B]` | Diseñados en la sección `[B] — Diseño de referencia para REQ-007`, al final de este documento. No implementados en REQ-006. |

## Resumen ejecutivo del cambio

Hoy existen **tres motores de resolución divergentes** (`main.py`, `channels/gateway.py`,
`core/orchestrator.py::_try_quick_dispatch`) con órdenes de capas distintos y, en el caso de
`GlassGateway`, con pre-matching de intención propio que nunca pasa por el gate de seguridad
(`_try_create_task` llama a `task_manager` directo). Esta arquitectura los reemplaza por **una sola
función de resolución** (`core/resolution.py:resolve()`) que camina una lista de resolvers — el mismo
patrón de "lista de datos en vez de cascada de `if`" que usa OpenClaw en su ruteo (§7.4.3), adaptado a
las capas que O.R.I.O.N. ya tiene. Todo lo que puede ejecutar algo (intents legacy y tools nuevos como
`task_manager`) pasa por exactamente dos puntos de gate (`dispatch()` y `execute_tool()`), ambos
llamando al mismo `security_manager.require_confirmation()` sin excepción.

## Módulos a modificar

| Módulo | Qué cambia |
|--------|-----------|
| `core/security_manager.py` | Se agrega `class ActionDenied(Exception)` (CA-09). `require_confirmation()` deja de llamar `input()` directo en la rama YELLOW/RED-PIN; consulta `core/confirmation.py` (CA-10). No se toca `CHANNEL_ALLOWED_LEVELS`, `RiskLevel`, `register_action()`, ni el fail-closed de `classify_action()`. |
| `core/base_agent.py` | `_DynamicAgentInstance.execute()` (línea 94-107): el chequeo `if result and "Error" not in result[:10]` se reemplaza por `try/except ActionDenied: continue` alrededor de `tool.execute(...)` (CA-09/H7). **Fuera de alcance de [A] — corregido tras auditoría de orion-security (observación A):** ningún CA-01…CA-17 requiere que `AgentTool` sepa invocar un `ToolSpec`; no se agrega ningún adaptador `AgentTool↔ToolSpec` en este REQ. Ese puente lo construye [B] directamente en `core/reasoning_loop.py`, que ejecuta **exclusivamente vía `execute_tool()`** (nunca `ToolSpec.invoke` directo — ver "Cobertura de criterios [B]", CA-18 a CA-23) y no reutiliza `AgentTool` en absoluto, así que no hace falta que `AgentTool` conozca `ToolSpec` para que [B] funcione. |
| `core/orchestrator.py` | `_try_quick_dispatch()` deja de clasificar por su cuenta — recibe el resultado ya resuelto por `core/resolution.py:resolve()` en vez de volver a llamar al clasificador (cierra B2 de la referencia OpenClaw: doble clasificación por mensaje). `process_task()` pasa a ser un delegado fino de `resolve()`. `_decompose()` **no se toca** en este REQ (bug B1/CA-24 es de [B]). |
| `router/dispatcher.py` | `dispatch()` levanta `ActionDenied` en vez de retornar `"⛔ Acción no autorizada."` (CA-09). El resto de la función (elección skill vs. handler legacy) no cambia — sigue siendo el único punto de ejecución de intents. |
| `main.py` | Se calcula `channel` una sola vez por ciclo de captura (`ChannelType.VOICE` si `choice in ('2','3')`, si no `ChannelType.DESKTOP`) y se usa en vez de los 6 literales `"desktop"` (líneas 40\*, 108, 136, 155, 167, 203 — \*la de `_ProactiveAssistant.execute()` se deja en DESKTOP, ver Riesgos). Se agrega manejo de `ActionDenied` en el bloque de ejecución para mostrar el mensaje al usuario. `_ProactiveAssistant.can_handle()` corregido (CA-12). Las 6 capas en cascada (rutinas → autopilot → aprendidos → capacidades → intent → Claude) se mueven a `core/resolution.py` como resolvers; `main.py` pasa a llamar `resolve()` una vez. |
| `channels/gateway.py` | `GlassGateway.process()` se reduce a: armar `GlassMessage` → llamar `core/resolution.py:resolve()` → convertir el resultado a `GlassResponse`. Se eliminan `_try_create_task`, `_try_list_tasks`, `_try_complete_task` (absorbidos como resolver `task_tool` en `resolution.py`, ejecutando vía `execute_tool()`). `_ask_claude_for_user` se conserva como está y pasa a ser invocado únicamente desde el resolver `claude_fallback`. Los `except Exception: pass` de las líneas 97-100 y 283-289 (B3) se corrigen a `except Exception as e: logger.warning(...)` porque son colaterales directos de tocar ese archivo — no dejar `except: pass` nuevo ni preexistente sin log al modificar la función que lo contiene. |
| `channels/telegram_bot.py` | Se elimina el pre-matching de "apaga el pc"/"reinicia el pc" (líneas ~548-554, 601-608 — B6). `handle_text`/`handle_voice` pasan el texto directo a `resolve()` a través del gateway; `_handle_shutdown`/`_handle_restart` quedan como funciones invocables por el resolver `intent` cuando el intent clasificado sea `SYS_POWER_OFF`/`CLOSE_APP`+contexto reinicio — su llamada a `require_confirmation()` ya es correcta (REQ-005) y no se toca. |
| `agents/action_registry.py` | Sin cambios funcionales; se documenta como fuente de `ToolSpec` locales de bajo nivel (ya clasificados en `security_manager.py`, ver `_register_action_registry_actions()`). |
| `tasks/task_manager.py` | **Sin cambios de código.** Pasa a ser invocado exclusivamente a través del wrapper `ToolSpec` de `agents/tool_registry.py` — nunca importado directo desde un canal. |

## Nuevas clases/funciones

### `core/resolution.py` (nuevo módulo — CA-01, CA-02, CA-03)

```python
@dataclass(frozen=True)
class ResolutionResult:
    text: str                    # respuesta final para el usuario
    matched_by: str              # "routine" | "autopilot" | "learned" | "capability"
                                  # | "task_tool" | "intent:<NOMBRE>" | "claude"
    channel: "ChannelType"
    denied: bool = False         # True si un resolver intentó y el gate denegó

def resolve(text: str, channel: "ChannelType", user_id: str = "default") -> ResolutionResult:
    """Punto único de resolución de O.R.I.O.N. Camina RESOLVERS en orden fijo,
    se detiene en el primero que da un resultado no-None. `channel` ya debe venir
    resuelto por el caller (nunca se infiere de params ni de texto libre)."""
```

`RESOLVERS` es una lista de tuplas `(nombre, función)` — mismo patrón que main.py ya usa como cascada
de `if`, ahora como dato recorrido por un `for`:

```python
RESOLVERS = [
    ("routine",    _try_routine),      # learning/routines_engine.try_routine
    ("autopilot",  _try_autopilot),    # agents/task_planner.py + task_executor.py
    ("learned",    _try_learned),      # learning/command_learning.run_custom_command
    ("task_tool",  _try_task_tool),    # NUEVO — reemplaza _try_create/_list/_complete_task
    ("capability", _try_capability),   # os_integration/capabilities_router.try_capability
    ("intent",     _try_intent),       # classify_command() + router.dispatcher.dispatch()
    ("claude",     _try_claude),       # ai/claude_brain.ask_claude() — último recurso
]
```

Cada función interna captura `ActionDenied` y la traduce a `ResolutionResult(denied=True, ...)` con
un mensaje ya formateado para el canal — así ni `main.py` ni `gateway.py` necesitan saber qué es
`ActionDenied`, solo consumen `ResolutionResult`. Esto preserva CA-11: `resolve()` es 100% síncrono;
si `main.py`/`gateway.py` corren en un hilo async (Telegram), el puente async→sync ya existe en esos
archivos (son ellos los que hacen `await`, `resolve()` no lo sabe ni le importa).

`_try_learned` es un caso particular (ver "Riesgos y mitigación", fila sobre resolvers heredados,
corregida tras auditoría de orion-security): llama a
`learning/command_learning.py:run_custom_command(phrase, execute_callback)` con un `execute_callback`
**fijo y privado de `resolution.py`**, nunca parametrizable desde fuera — ese callback siempre hace
`classify_command() → dispatch()` internamente, así el gate no depende de que un caller futuro sea
disciplinado.

### `agents/tool_registry.py` (nuevo módulo — CA-14, CA-15, CA-16, CA-17)

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str                      # p.ej. "task_create" — también la action_name del security_manager
    description: str               # descripción en lenguaje natural (para el LLM/discovery)
    parameters_schema: dict        # JSON Schema de los parámetros — igual forma que MCP inputSchema
    risk_level: "RiskLevel"        # DECLARADO por el tool, nunca autoritativo (CA-15)
    invoke: Callable[[dict], str]  # función pura que ejecuta el tool ya autorizado
    origin: str = "local"          # "local" | "mcp_remote" (CA-16 — sin cliente real todavía)

_REGISTRY: dict[str, ToolSpec] = {}

def register_tool(spec: ToolSpec) -> None:
    """Registra el tool y, en el mismo paso, su risk_level en security_manager —
    un ToolSpec sin risk_level no compila (campo obligatorio del dataclass), y
    security_manager.classify_action() sigue bloqueando fail-closed si por algún
    motivo el registro no llegó a correr."""
    from core.security_manager import security_manager
    security_manager.register_action(spec.name, spec.risk_level)
    _REGISTRY[spec.name] = spec

def execute_tool(name: str, params: dict, channel: "ChannelType", user_id: str = "default") -> str:
    """Segundo (y único otro) punto de gate del sistema, junto a dispatch().
    Levanta ActionDenied si security_manager deniega — nunca ejecuta invoke() sin pasar antes."""
    from core.security_manager import security_manager, format_details, ActionDenied
    spec = _REGISTRY.get(name)
    if spec is None:
        raise ActionDenied(name, channel, "tool no registrado")
    if not security_manager.require_confirmation(
        spec.name, channel, details=format_details(f"tool:{spec.name}", params), user_id=user_id
    ):
        raise ActionDenied(spec.name, channel, "denegado por security_manager")
    return spec.invoke(params)
```

Wrappers concretos de `task_manager` (los tres que hoy bypassean seguridad en `gateway.py`):

```python
def _task_create_invoke(params: dict) -> str:
    from tasks.task_manager import task_manager
    result = task_manager.create_from_natural(params["text"], params["user_id"], params.get("channel", "telegram"))
    return task_manager.format_task_created(result) if result else "No pude interpretar esa tarea, Señor."

register_tool(ToolSpec(
    name="task_create",
    description="Crea una tarea o recordatorio a partir de una frase en lenguaje natural.",
    parameters_schema={"type": "object", "properties": {
        "text": {"type": "string"}, "user_id": {"type": "string"}, "channel": {"type": "string"}
    }, "required": ["text", "user_id"]},
    risk_level=RiskLevel.GREEN,   # mismo nivel efectivo que tiene hoy sin gate — ver Riesgos
    invoke=_task_create_invoke,
))
# task_list y task_complete: misma forma, mismo risk_level GREEN.
```

**Por qué `GREEN` y no `YELLOW`:** hoy `_try_create_task` ya se ejecuta sin ningún gate en los 4
canales de Telegram — clasificarlo `YELLOW` cambiaría comportamiento visible al usuario sin que la
SPEC lo pida (bloquearía la creación de tareas por Telegram, que es el uso normal). `GREEN` preserva
el comportamiento actual pero ahora **pasa por el gate y queda auditado** — que es exactamente el
hueco de seguridad que hay que cerrar (visibilidad y clasificación explícita, no bloqueo nuevo).

**Invariante de `user_id` (agregado tras auditoría de orion-security, Observación B):** igual que
`security_manager.py:214-221` deja escrito que `channel` nunca se re-infiere de `params` ni de texto
libre, la misma regla aplica a `user_id` en `task_create`/`task_list`/`task_complete` y no estaba
documentada de forma equivalente. Hoy se cumple de hecho (Telegram usa `update.effective_user.id` de
la API, nunca texto parseado del mensaje) pero queda como regla explícita, no solo comportamiento
accidental: el resolver `_try_task_tool` en `core/resolution.py` debe construir `params["user_id"]`
a partir del `user_id` real de la sesión/canal que ya recibe `resolve()` como argumento — nunca
extraerlo de `text`. Relevante para cuando `task_tool` se extienda a más canales (voz, desktop) en
REQ-007 o posterior.

### `core/confirmation.py` (nuevo módulo — CA-10)

```python
ConfirmFn = Callable[[str, str], bool]  # (action_name, mensaje) -> confirmado, SIEMPRE síncrono/bloqueante

_ADAPTERS: dict["ChannelType", ConfirmFn] = {}

def register_confirmation_adapter(channel: "ChannelType", fn: ConfirmFn) -> None:
    _ADAPTERS[channel] = fn

def get_confirmation_adapter(channel: "ChannelType") -> Optional[ConfirmFn]:
    return _ADAPTERS.get(channel)
```

`main.py` registra, al arrancar, el único adaptador real de este REQ:

```python
from core.confirmation import register_confirmation_adapter
from core.security_manager import ChannelType

def _desktop_confirm(action_name: str, msg: str) -> bool:
    response = input(f"\n⚠️  {msg}\nEscribe 'sí' para confirmar, o cualquier otra cosa para cancelar: ")
    return response.strip().lower() in ("sí", "si", "yes", "s")

register_confirmation_adapter(ChannelType.DESKTOP, _desktop_confirm)
```

Telegram/Discord/Voice/API **no registran adaptador** en este REQ — comportamiento idéntico al
actual (YELLOW ya se bloquea ahí por `is_action_allowed()` antes de llegar a preguntar nada; ver
`require_confirmation()` abajo), pero ahora por una única vía en vez de casos especiales dispersos.

### Cambio exacto en `security_manager.require_confirmation()`

La rama YELLOW (líneas 232-248 actuales) cambia de:

```python
response = input(f"\n⚠️  {msg}\nEscribe 'sí'...")
confirmed = response.strip().lower() in ("sí", "si", "yes", "s")
```

a:

```python
from core.confirmation import get_confirmation_adapter
adapter = get_confirmation_adapter(channel)
if adapter is None:
    logger.warning(f"Canal {channel.value} sin adaptador de confirmación — '{action_name}' bloqueada (fail-closed)")
    self._log_audit(action_name, channel, "bloqueada_sin_adaptador", user_id, details)
    return False
confirmed = adapter(action_name, msg)
```

El resto de la función (fail-closed sin clasificación, GREEN directo, RED con PIN en DESKTOP) **no
cambia una sola línea** — CA-07 exige exactamente eso. `ActionDenied` no se levanta *dentro* de
`security_manager` (que sigue devolviendo `bool`, para no romper los ~40 call-sites de REQ-005 que ya
lo consumen así, ni los 49 tests de `test_security_manager.py`) — la excepción se levanta un nivel
arriba, en `dispatch()` y `execute_tool()`, que son los dos lugares que traducen el `bool` a
"ejecutar" o "denegar". Esto mantiene `require_confirmation()` con la misma firma y el mismo
contrato que hoy validan los 49 tests existentes.

## Flujo de datos

**Antes (hoy, tres motores):**
```
Desktop:  main.py → [6 capas if/try] → dispatch()/orchestrator.process_task() → security_manager
Telegram: telegram_bot.py → [matching "apaga el pc"] → GlassGateway.process()
              → [_try_create_task / _try_list_tasks / _try_complete_task → task_manager DIRECTO, sin gate]
              → classify_command() → dispatch() O ask_claude() (UNKNOWN)
Voice:    main.py (mismo camino que Desktop, pero channel="desktop" hardcodeado — H5)
```

**Después (un solo motor, dos puntos de gate):**
```
                      ┌─────────────┐
Desktop (texto/voz) → │              │
Telegram/Discord    → │ resolve()    │──> RESOLVERS (lista, en orden fijo)
API                  → │ core/        │        │
                      │ resolution.py│        ├─ routine/autopilot/capability: ejecutan vía
                      └─────────────┘        │     execute_action()/execute_capability(),
                             │                │     ya gateados hoy (REQ-005), sin cambio
                             │                │
                             │                ├─ learned: ejecuta vía callback → dispatch()
                             │                │     (gate indirecto — ver Riesgos, el
                             │                │     contrato debe preservarse explícito)
                             │                │
                             │                ├─ task_tool ──────> agents/tool_registry.py
                             │                │                     execute_tool()
                             │                │                        │
                             │                ├─ intent ────────> router/dispatcher.py
                             │                │                     dispatch()
                             │                │                        │
                             │                │                        ▼
                             │                │              core/security_manager.py
                             │                │              require_confirmation()
                             │                │                        │
                             │                │              ┌─────────┴─────────┐
                             │                │           permitido           denegado
                             │                │              │                   │
                             │                │           ejecuta          ActionDenied
                             │                │                                   │
                             │                └─ claude ─> ai/claude_brain.ask_claude()
                             │                              (fallback, su propio historial)
                             ▼
                    ResolutionResult(text, matched_by, denied)
                             │
              ┌──────────────┼──────────────┐
         main.py       GlassGateway    (futuro API channel)
         ui.display_output  → GlassResponse
```

El canal (`ChannelType`) se resuelve **una sola vez**, en el punto de entrada real de cada camino
(`main.py` según `choice`; `channels/telegram_bot.py`/`discord_bot.py` con su `ChannelType` fijo), y
viaja como parámetro explícito hasta `require_confirmation()` — nunca se reinfiere de `params` ni de
texto libre (invariante ya documentada en `security_manager.py:214-221`, no se toca, solo se respeta
en el código nuevo).

## Archivos a modificar/crear

**Nuevos:**
- `core/resolution.py`
- `agents/tool_registry.py`
- `core/confirmation.py`
- `tests/test_resolution.py`
- `tests/test_tool_registry.py`
- `tests/test_confirmation.py`

**Modificados:**
- `core/security_manager.py` — `ActionDenied`, cambio de la rama YELLOW de `require_confirmation()`
- `core/base_agent.py` — `_DynamicAgentInstance.execute()` (H7/CA-09)
- `core/orchestrator.py` — `process_task()`/`_try_quick_dispatch()` delegan a `resolve()`
- `router/dispatcher.py` — `dispatch()` levanta `ActionDenied`
- `main.py` — cálculo de `channel` real, registro del adaptador desktop, uso de `resolve()`, CA-12
- `channels/gateway.py` — `process()` delega a `resolve()`, se eliminan los 3 métodos `_try_*_task`
- `channels/telegram_bot.py` — se elimina el pre-matching B6
- `tests/test_classifier.py`, `tests/test_dispatcher.py` — casos ejecutables nuevos (CA-13)

**Sin cambios de código (solo consumidos distinto):**
- `tasks/task_manager.py`
- `ai/claude_brain.py`
- `agents/action_registry.py`

## Dependencias nuevas

Ninguna. Todo lo diseñado usa `dataclasses`, `typing` y `enum` de la librería estándar, ya en uso en
`core/security_manager.py` y `channels/gateway.py`. No se agrega ninguna entrada a `requirements.txt`.

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| `resolve()` mal migrado deja algún resolver sin probar en los tres canales y reintroduce el "comando funciona por consola pero no por Telegram" que señala la referencia OpenClaw §8.1 | CA-13: test ejecutable de `resolve()` con los mismos casos de entrada para `channel=DESKTOP/TELEGRAM/VOICE`, comparando `matched_by` — no solo clasificación. |
| De los 4 resolvers heredados de `main.py`, solo `learned` depende de que su caller lo gatee — **no de `routine`/`autopilot`/`capability` como se afirmó en una versión anterior de esta fila, corregido tras verificar la cadena de llamadas completa, no solo el archivo de primer nivel**: `routine` (`learning/routines_engine.py:try_routine()`) y `autopilot` (`agents/task_executor.py`) ejecutan ambos a través de `agents/action_registry.py:execute_action()`, que en su línea 256 llama `security_manager.require_confirmation()` **incondicionalmente, sea cual sea el caller** — es el mismo punto de entrada gateado de REQ-005 para los dos. `capability` gatea directo dentro de `os_integration/capabilities_router.py:execute_capability()` (línea 59). Los tres están gateados por construcción hoy. `learned` (`learning/command_learning.py:run_custom_command()`) **no llama a `security_manager` en ningún punto de su propio código** — el gate que recibe hoy es un efecto colateral de que su único caller real (`main.py:159`, vía `execute_simulated_action`) pasa un callback que internamente llama `classify_command()` + `dispatch()` (gateado). El contrato de `run_custom_command()` no exige eso: un caller distinto (o un `resolve()` mal migrado) podría pasarle un callback que ejecute directo, sin gate, y nadie lo notaría porque `command_learning.py` no impone nada. | **Corregido tras auditoría de orion-security (Hallazgo 1.7):** la mitigación original (test que verifica que el callback usado hoy llama `dispatch()`) protege contra un cambio accidental del callback actual, pero no impide estructuralmente que aparezca mañana un segundo caller de `run_custom_command()` sin gate — deja el gate en manos de la disciplina del caller, distinto del estándar que exige `security-levels.md` (el gate vive en el punto de entrada real, no en que el caller sea prolijo). Mitigación reforzada: `core/resolution.py::_try_learned` **no acepta ningún callback externo** — la función que ejecuta cada acción aprendida es privada de `resolution.py` (sin parámetro de configuración), y siempre hace `classify_command() → dispatch()` internamente; `run_custom_command(phrase, execute_callback)` se sigue llamando con ese callback fijo, nunca inyectable desde fuera de `resolution.py`. El test original (`test_resolution.py::test_learned_callback_pasa_por_dispatch`) se conserva como red adicional, no como única defensa. `routine`/`autopilot`/`capability` no requieren mitigación adicional — ya están gateados por construcción y la migración a `resolution.py` no cambia esa cadena de llamadas. |
| Canal `desktop` de `_ProactiveAssistant.execute()` (`main.py:40`) queda fijo en `ChannelType.DESKTOP` aunque el trigger dispare sin usuario presente; si CA-12 hace que `can_handle()` deje de ser siempre `0.0`, una acción YELLOW disparada por un trigger proactivo desatendido llamaría al adaptador `_desktop_confirm` (que usa `input()`) y **colgaría** un hilo de fondo esperando stdin que nadie va a escribir | Mitigación de diseño: CA-12 solo corrige el bug del ternario (ambas ramas retornaban `0.0`); esta arquitectura **no** cambia el valor real que retorna `can_handle()` más allá de lo que exige el bugfix, por lo que `_ProactiveAssistant` sigue sin auto-despachar acciones hoy. Se deja documentado como riesgo activo para cuando algún REQ futuro decida darle a `_ProactiveAssistant` un score real: en ese momento, los triggers automáticos deben enrutarse por un canal sin adaptador de confirmación (denegado fail-closed) en vez de `DESKTOP`, o el adaptador desktop necesita un timeout. No se resuelve en REQ-006 porque no hay ejecución automática real que dispare hoy. |
| `ActionDenied` como excepción se "escapa" por un call-site que no la espera y termina mostrándose como traceback crudo al usuario | Se hereda de `Exception`, no de `BaseException` — todos los `try/except Exception` genéricos existentes en `channels/gateway.py`, `channels/telegram_bot.py`, `dispatch_as_tool()` la capturan igual que cualquier otra falla y ya formatean un mensaje al usuario. Se agrega un test específico que verifica que el mensaje de un `ActionDenied` no expone stacktrace ni rutas de archivo (mismo criterio que B4 de la referencia OpenClaw). |
| Migrar `channels/gateway.py` a `resolve()` cambia el orden de resolución que hoy usa Telegram (tareas → listar → completar → screenshot → intents) al orden nuevo (routine → autopilot → learned → task_tool → capability → intent → claude) | Es un cambio de comportamiento deliberado y pedido por la SPEC (CA-03: mismo orden en los tres canales) — no accidental. Riesgo residual: una frase que hoy dispara `_try_create_task` en Telegram podría, con el nuevo orden, ser interceptada antes por `routine`/`learned` si el usuario tiene una rutina con un nombre parecido. Mitigación: test de regresión específico con las frases trigger reales de `_try_create_task`/`_try_list_tasks`/`_try_complete_task` verificando que siguen resolviendo a `task_tool`. |
| `except Exception: pass` corregidos en `channels/gateway.py` (B3) cambian de silencio total a logging — podría exponer en logs contenido de memoria semántica que antes nunca se registraba | Se usa `logger.warning` (no `logger.info`/`print`), con el mensaje de excepción truncado igual que ya hace el resto de `security_manager.py` (`_DETAILS_MAX_VALUE_LEN`). No se loguea el contenido de `text`/`result`, solo el error de la operación de guardado. |
| `[B]` (REQ-007) diseñado aquí queda desalineado si REQ-006 se ajusta en revisión humana | Se marca explícitamente cada pieza `[B]` como diseño de referencia, no contractual; REQ-007 tendrá su propio `orion-architect` que puede confirmar o ajustar contra el código real ya implementado de REQ-006. |

## Pruebas sugeridas

Una por cada criterio de la SPEC ([A], CA-01 a CA-17):

| CA | Test |
|----|------|
| CA-01 | `test_resolution.py::test_resolve_es_el_unico_punto_de_entrada` — `main.py`, `channels/gateway.py` no importan `dispatch()`/`task_manager` directo (grep estructural o `ast`), solo `resolve()`. |
| CA-02 | `test_resolution.py::test_gateway_sin_prematching` — `channels/gateway.py` ya no tiene los métodos `_try_create_task`/`_try_list_tasks`/`_try_complete_task`. |
| CA-03 | `test_resolution.py::test_traza_identica_por_canal` — mismo texto de entrada, `channel` DESKTOP/TELEGRAM/VOICE, mismo `matched_by`/`intent`/`tool` en `ResolutionResult`, solo `denied` puede diferir. |
| CA-04 | `test_resolution.py::test_yellow_mismo_action_name_desktop_vs_voice` — `CLOSE_APP` vía voice y vía desktop llegan a `require_confirmation("close_app", ...)`; en voice queda `denied=True` sin ejecutar la tool, en desktop pide confirmación. |
| CA-05 | `test_main_channel.py::test_voice_input_emite_channel_voice` — con `choice='2'` y `choice='3'`, el `channel` calculado es `ChannelType.VOICE`; con `choice='1'`, `ChannelType.DESKTOP`. |
| CA-06 | `test_resolution.py::test_solo_verde_ejecuta_por_voz` — acción YELLOW vía `ChannelType.VOICE` siempre `denied=True`. |
| CA-07 | `test_security_manager.py` (49 existentes) siguen en verde sin modificar ninguno. Nuevo: `test_security_manager.py::test_cobertura_total_de_tools_y_acciones` — recorre `_REGISTRY` de `tool_registry` + `Intent` + `ACTION_REGISTRY` y falla si `security_manager.classify_action()` devuelve `None` para alguno. |
| CA-08 | `test_tool_registry.py::test_risk_level_declarado_no_es_autoritativo` — un `ToolSpec` con `risk_level=GREEN` registrado, pero `security_manager.register_action(mismo_nombre, RiskLevel.YELLOW)` llamado después, y `require_confirmation()` respeta YELLOW (el último registro gana, como ya hace `register_action()` hoy salvo degradar RED). |
| CA-09 | `test_security_manager.py::test_denial_no_es_substring_de_exito` — `dispatch()`/`execute_tool()` levantan `ActionDenied`, nunca retornan un string con "⛔"; `test_base_agent.py::test_dynamic_agent_no_confunde_denial_con_exito` — reproduce el bug H7 con un mock que hoy fallaría con `"Error" not in result[:10]` y confirma que con `except ActionDenied` no se malinterpreta. |
| CA-10 | `test_confirmation.py::test_canal_sin_adaptador_bloquea_sin_colgar` — llama `require_confirmation()` con un canal sin adaptador registrado, con timeout de test corto, y verifica `False` inmediato (no bloqueo). `test_confirmation.py::test_desktop_adapter_llamado_correctamente` con `input` mockeado. |
| CA-11 | Chequeo estático: `grep -rn "async def" core/ router/ intent/ skills/` en CI/pre-commit del REQ da 0 resultados nuevos respecto al baseline. |
| CA-12 | `test_main.py::test_proactive_assistant_can_handle` — ramas distintas devuelven valores distintos (no ambas `0.0`). |
| CA-13 | `test_classifier.py`/`test_dispatcher.py` dejan de reportar "0 tests collected"; casos con `channel` real y aserciones sobre el resultado ejecutado, no solo sobre el intent clasificado. |
| CA-14 | `test_tool_registry.py::test_toolspec_shape` — un `ToolSpec` tiene `name`/`description`/`parameters_schema`/`risk_level`/`invoke` y `parameters_schema` es JSON Schema válido (`jsonschema.Draft7Validator.check_schema`, ya sin agregar dependencia si se usa una validación manual mínima, o marcar como opcional si se prefiere no agregar `jsonschema`). |
| CA-15 | `test_tool_registry.py::test_tool_sin_risk_level_no_compila` — instanciar `ToolSpec` sin `risk_level` falla en tiempo de construcción (dataclass sin default) — fail-closed por diseño, no por chequeo en runtime. |
| CA-16 | `test_tool_registry.py::test_tool_origen_remoto_mismo_contrato` — `ToolSpec(origin="mcp_remote", ...)` construido desde un fixture estático inspirado en `.claude/skills/skill-mcp-sigaind-v01.md`, pasado a `execute_tool()` sin ninguna rama de código distinta a un tool local. |
| CA-17 | `test_tool_registry.py::test_toolspec_no_tiene_campo_de_usuario` — verificación estructural de que `ToolSpec` no declara ningún campo de identidad de usuario/tenant. |

---

# [B] — Diseño de referencia para REQ-007 (NO implementar en REQ-006)

Cubre CA-18 a CA-24. Se incluye aquí únicamente para que la arquitectura de [A] no cierre puertas —
`orion-dev` de REQ-006 no debe tocar nada de esta sección.

## Cobertura de criterios [B]

| Criterio | Enfoque de diseño |
|----------|--------------------|
| CA-18 a CA-23 (loop de razonamiento real con tools) | Un nuevo `core/reasoning_loop.py` que reemplaza `_DynamicAgentInstance.execute()` (hoy un `for` sin ninguna llamada a LLM, ver `core/base_agent.py:94-107`). El loop llama al LLM (vía `ai/llm_provider.py`, ya existente) con la lista de `ToolSpec` de `agents/tool_registry.py` convertida a su forma de "tools" del proveedor, recibe una decisión de tool-call, y **ejecuta exclusivamente a través de `execute_tool()`** — nunca invoca `ToolSpec.invoke` directo. Esto es lo que hace que el contrato `ToolSpec` diseñado en [A] no sea trabajo desperdiciado: el gate de seguridad ya existe y ya es channel-agnostic antes de que exista el loop que lo va a usar de verdad. |
| CA-24 (`_decompose()` no rompe por la letra "y") | Fix ya transcrito por la referencia OpenClaw (§7.2, B1) — comparación de palabra completa con `\b` en vez de substring, más red de seguridad `all(len(p) > 3 for p in parts)`. Se implementa en REQ-007 sobre `core/orchestrator.py:_decompose()`, no en REQ-006. |

## Patrón recomendado para REQ-007 — pairing-code / desafío antes de procesar

De `workspace/referencias/openclaw/01-seguridad-y-aislamiento.md` §2.3: el flujo de OpenClaw para
remitentes desconocidos hace el desafío de identidad **antes** de decodificar/procesar el mensaje.
Aplicado al loop de razonamiento de REQ-007 con tools remotos (SIGAIND): la resolución de credenciales
por origen de tool (CA-17) debería validarse en el momento de construir la lista de tools disponibles
para el loop, no en el momento de invocar — así un fallo de autenticación no se descubre a mitad de una
cadena de tool-calls ya iniciada frente al usuario.

## Riesgo de arrastre señalado a REQ-007

El modelo de dos ejes de Exec Approvals (`security × ask`, con `allow-always` durable) descartado para
[A] por sobreingeniería debería reconsiderarse en REQ-007: un loop de razonamiento real puede llamar
la misma tool YELLOW varias veces en una sola conversación, y repreguntar cada vez (comportamiento de
[A]) puede ser insoportable para el usuario. `durableApprovalSatisfied` de OpenClaw es la pieza a
evaluar primero si eso ocurre.

