# Arquitectura REQ-007 — Bucle de razonamiento real con LLM

**Estado: ✅ APROBADA por el humano** (incluye respuesta explícita a las 2 preguntas de diseño
de abajo — Opción A para la Pregunta 1, mitigación aceptada para la Pregunta 2). Se conserva el
texto original de ambas preguntas tal cual se presentaron, seguido de la resolución de cada una,
para que quede registro de qué se preguntó y qué se decidió.

## Preguntas de diseño para el humano — RESUELTAS

Estas dos preguntas no estaban resueltas por SPEC-007 ni por baseline-007.md. Las descubrí
verificando el código real (no solo lo documentado) y afectan directamente si este REQ cumple
su propósito declarado. No las decidí unilateralmente.

### Pregunta 1 (bloqueante para el propósito del REQ): ¿dónde se cablea el loop a producción?

**Hallazgo:** `_DynamicAgentInstance.execute()` — el método que CA-01 exige modificar — hoy
**no es alcanzable por ningún usuario real**. Verificado leyendo `main.py`, `core/orchestrator.py`
y `core/resolution.py` completos:

- `main.py` llama a `resolve(command, channel)` directamente (línea 162).
- `resolve()` recorre una lista fija `RESOLVERS` (`routine → autopilot → learned → task_tool →
  capability → intent → claude`) — ninguno de los 7 resolvers llama a
  `_process_with_agents()`/`_execute_single_agent()`/`_DynamicAgentInstance`.
- `AgentOrchestrator.process_task()` (que sí llamaría a `_process_with_agents`) no lo invoca
  nadie en producción — su propio docstring (REQ-006) dice explícitamente que
  `_process_with_agents`/`_execute_single_agent`/`_execute_agent_chain` "quedan disponibles
  para uso directo por quien los necesite explícitamente", es decir, se dejaron ahí a propósito
  pero sin cablear.

Si solo satisfago la letra de CA-01 (reemplazar el for-loop dentro de `execute()`), el bucle de
razonamiento nuevo queda **construido pero inalcanzable** — exactamente el mismo problema que
tiene hoy el sistema, solo que con código mejor. Eso no cumple el objetivo declarado del REQ
("O.R.I.O.N. hoy no razona... reemplaza ese loop por un bucle de razonamiento real").

**SPEC-007 no lista `core/resolution.py` en "Módulos afectados"**, así que cablear ahí es una
desviación del alcance literal, aunque sea un cambio pequeño (una función).

**Opción A (recomendada):** en `core/resolution.py`, la resolución `"claude"` (hoy
`_try_claude()`, que llama a `ai/claude_brain.py::ask_claude()`) pasa a intentar primero
`core/reasoning_loop.run(text, channel, user_id)`. Esto hace que el bucle nuevo sea el fallback
real del sistema — reemplaza al bucle "tonto" que nunca se ejecutaba con uno real que sí se
ejecuta. Costo: un archivo más en "Módulos afectados" (una función de ~10 líneas), y decidir qué
pasa con la personalidad/memoria de `ask_claude()` (ver Pregunta 2).

**Opción B (alcance literal):** satisfacer CA-01 a CA-17 tal como están escritos, dejar
`core/reasoning_loop.py` construido, probado y invocable directamente
(`core.reasoning_loop.run(...)`, o vía `_DynamicAgentInstance` si alguien lo instancia a mano),
pero **no tocar `core/resolution.py`**. El cableado a producción queda para un REQ futuro. Nada
en SPEC-007 se incumple; el REQ entrega infraestructura correcta pero todavía no conectada a un
usuario real.

**No voy a decidir esto por mi cuenta** porque cambia si REQ-007 tiene efecto observable para el
usuario o no. Responder junto con la aprobación de esta arquitectura: **A o B**.

> **✅ RESUELTO por el humano: Opción A.** `core/resolution.py::_try_claude()` cae en
> `core/reasoning_loop.run()` en vez de llamar directo a `ask_claude()` — pero solo en el
> caso default (sin `claude_fn` inyectado). Ver diseño concreto en "Nuevas clases/funciones
> — `core/resolution.py`" más abajo.

### Pregunta 2 (solo si se elige A): ¿el loop preserva la personalidad/memoria de `ask_claude()`?

`ai/claude_brain.py::ask_claude()` no es solo una llamada a `generate_response()`: arma el
system prompt de personalidad JARVIS, mantiene `_conversation_histories` por usuario, inyecta
memoria semántica y texto de perfil, y parsea un canal lateral de JSON (`learn_command`,
`save_memory`) del texto de respuesta. SPEC-007 dice explícitamente que unificar
`_conversation_histories` con `agent_context_manager` sigue fuera de alcance — pero **no dice
qué pasa con el resto de ese comportamiento** si el catch-all pasa a ser el loop.

Además, CONFIRMADO 2 fija un límite dostrict de "hasta 5 llamadas al LLM en total, incluida la
llamada final que da la respuesta" — esto implica que la respuesta final en texto plano tiene
que salir de **dentro** del propio loop (una de las 5 llamadas), no de una llamada adicional a
`ask_claude()` después (sería una 6ª llamada, violando CONFIRMADO 2). Por diseño (ver sección
"Nuevas clases/funciones"), `reasoning_loop.py` no puede delegar la respuesta final a
`ask_claude()` sin romper el presupuesto de 5 llamadas.

**Consecuencia si se elige Opción A:** las conversaciones que hoy caen al fallback de Claude
Brain (personalidad JARVIS completa, memoria semántica, aprendizaje de comandos) perderían ese
enriquecimiento cuando el bucle de razonamiento decide responder en texto plano sin tools —
responderían con un system prompt propio de `reasoning_loop.py`, más simple, sin memoria
semántica ni side-channel de aprendizaje.

**Mitigación que propongo si se aprueba Opción A:** el system prompt propio de
`reasoning_loop.py` mantiene el tono JARVIS (texto fijo, sin acoplarse a
`claude_brain._build_system_prompt()` para no crear una dependencia entre módulos que SPEC no
pidió tocar), pero **no** replica memoria semántica ni el side-channel de aprendizaje — eso
queda fuera de alcance de este REQ tal como SPEC ya lo declaró para la unificación de
historiales. Es una regresión de UX menor y acotada (tono se mantiene, memoria/aprendizaje no),
que documento aquí para que el humano decida si es aceptable o si prefiere Opción B.

> **✅ RESUELTO por el humano: mitigación aceptada tal cual.** El loop resuelve por sí mismo
> (tono JARVIS, sin memoria semántica ni aprendizaje) cuando no hay `claude_fn` inyectado.
> Queda registrada como deuda explícita para un REQ futuro (posible integración de memoria
> semántica de `claude_brain`/`agent_context_manager` dentro del loop) — no se resuelve en
> REQ-007.

---

## Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| CA-01 | `core/reasoning_loop.py::run()` nuevo; `_DynamicAgentInstance.execute()` cambia su cuerpo (no su firma) para delegar a `run()`. El for-loop dumb se elimina. |
| CA-02 | `_build_tool_list()` en `reasoning_loop.py` lee `agents/tool_registry.py::list_tool_names()`/`get_tool()` y pasa `parameters_schema` sin reescritura manual — formato genérico `{name, description, parameters_schema}`. |
| CA-03 | `ai/llm_provider.py::generate_response(..., tools=None)` — parámetro nuevo, `None` por defecto, no rompe ningún caller existente (todos los actuales llaman sin `tools=`). |
| CA-04 | `_ask_anthropic()` recibe `tools=`, arma `input_schema` desde `parameters_schema`, parsea bloques `tool_use` de `response.content` en `LLMToolResponse`. |
| CA-05 | `_ask_openai()`/`_ask_deepseek()` reciben `tools=`, arman formato `{"type":"function","function":{...}}`, parsean `message.tool_calls` en `LLMToolResponse` (código compartido porque ambos ya usan el SDK `openai`). |
| CONFIRMADO 1 | `generate_response()` calcula `tools_supported = active_provider in ("anthropic","deepseek","openai")`; si `False`, `effective_tools=None` y se llama sin tools — degradación silenciosa, sin excepción, sin aviso al usuario. |
| CA-06 | Todo tool en `reasoning_loop.py` se ejecuta solo vía `agents/tool_registry.py::execute_tool()`. Nunca se importa ni se llama `ToolSpec.invoke` directo — verificable por grep (ver Pruebas sugeridas). |
| CA-07 | `MAX_LLM_CALLS = 5`, `for call_number in range(1, MAX_LLM_CALLS + 1)`. Si el LLM no da respuesta final antes de agotar el rango, el loop cierra con mensaje de límite — sin una 6ª llamada. |
| CA-08 | `except ActionDenied as e: final_text = ...; break` — corta el loop de inmediato, no reintenta, no llama al LLM de nuevo. |
| CA-09 | Cuando `tools` está presente, `generate_response()` usa `_uncached_call()` en vez de `_cached_call()` — nunca se cachea una decisión de tool-calling (ver "Riesgos y mitigación" para la justificación completa). |
| CA-10 | `run()` llama a `agent_context_manager.update_context()` exactamente 2 veces (un `user` y un `assistant`) al final de toda la invocación, nunca dentro del `for` de iteraciones. |
| CA-11 | `_build_tool_list()` no recibe ni consulta `channel` — ofrece siempre el catálogo completo de `list_tool_names()`. El único filtro de canal/riesgo sigue siendo `execute_tool()` → `security_manager.require_confirmation()`. |
| CA-12 | `core/orchestrator.py::_decompose()` cambia a `re.search(r'\b' + re.escape(trigger) + r'\b', ...)` + `all(len(p) > 3 for p in parts)`. `MAX_CHAIN_DEPTH`/`_execute_agent_chain()` no se tocan (CONFIRMADO 3). |
| CA-13 | Casos borde de malformación (JSON de argumentos inválido, tool inexistente) atrapados por `except Exception` genérico dentro del loop — no crashea, se informa como resultado de iteración fallido y el LLM puede reintentar dentro del límite de 5. |
| CA-14 | `agents/skill_tools.py` nuevo — `register_dispatcher_tool()` + `register_skill_tools()` reemplazan el bloque de `main.py` que construía `AgentTool`. |
| CA-15 | `register_skill_tools()` usa `security_manager.classify_action(intent)` (ya poblado por REQ-005 `_register_intent_actions()`) — nunca inventa un `risk_level`. Si algún intent no tiene clasificación, `RuntimeError` explícito en el arranque en vez de asumir un nivel. |
| CA-16 | `_make_skill_invoke()` llama `skill.extract_params(intent, text)` → `skill.execute(intent, exec_params)`, sin ningún `require_confirmation()` propio — el gate ya ocurrió en `execute_tool()` antes de invocar esto. |
| CA-17 | Ver sección "Decisión CA-17" más abajo — `AgentTool` se mantiene (dependencia dura de `skill_manager.py`, no modificable), `AgentOrchestrator.register_tool()`/`self._tools` se eliminan (sin lectores tras la migración). |
| CONFIRMADO 4 | Cada `ToolSpec.name` de skill-intent es el `Intent` crudo (`"OPEN_FOLDER"`, `"SYS_POWER_OFF"`, etc.), nunca `skill_<intent_lower>`. |
| CONFIRMADO 5 | `"dispatcher"` se registra con `risk_level=RiskLevel.GREEN`. |
| CONFIRMADO 6 | Ver "Decisión CA-17". |

## Módulos a modificar

- `core/base_agent.py` — `_DynamicAgentInstance.execute()`: cambia el cuerpo (no la firma del
  constructor ni la de `execute()`) para delegar a `core/reasoning_loop.py::run()`.
- `core/orchestrator.py` — `_decompose()` (fix CA-12); `_execute_single_agent()`/
  `_execute_agent_chain()` pasan `[]` en vez de `self._tools` a `create_agent()`;
  `AgentOrchestrator.__init__`/`register_tool()` pierden `self._tools`/`register_tool()`.
- `ai/llm_provider.py` — `generate_response()` gana `tools=None`; `_cached_call()`/
  `_uncached_call()` ganan threading de `tools`; `_ask_anthropic()`/`_ask_openai()`/
  `_ask_deepseek()` ganan parseo de tool-calling; `_ask_gemini()`/`_ask_ollama()` sin cambios.
- `main.py` — reemplaza el bloque de registro de `AgentTool` (líneas 8, 31-38) por llamadas a
  `agents/skill_tools.py`.

## Nuevas clases/funciones

### `core/reasoning_loop.py` (nuevo módulo)

```python
"""
core/reasoning_loop.py
Bucle de razonamiento real con LLM (REQ-007, CA-01 a CA-13).

Reemplaza el for-loop de `_DynamicAgentInstance.execute()` (que probaba tools en orden fijo
sin ningún criterio) por un ciclo decide→ejecuta→evalúa dirigido por el LLM, con un
presupuesto duro de 5 llamadas totales (CONFIRMADO 2) y ejecución de tools EXCLUSIVAMENTE vía
`agents/tool_registry.py::execute_tool()` (CA-06) — nunca `ToolSpec.invoke` directo.
"""
import logging
from typing import Optional

from agents.tool_registry import execute_tool, get_tool, list_tool_names
from ai.llm_provider import LLMToolResponse, generate_response
from core.agent_context import agent_context_manager
from core.security_manager import ActionDenied, security_manager

logger = logging.getLogger(__name__)

MAX_LLM_CALLS = 5

_SYSTEM_PROMPT = (
    "Eres el núcleo de razonamiento de O.R.I.O.N., un asistente con personalidad estilo "
    "JARVIS: educado, directo, se dirige al usuario como 'Señor'. Tienes acceso a "
    "herramientas para ejecutar acciones reales en el sistema del usuario. Usa una "
    "herramienta solo si el pedido la requiere de verdad; si puedes responder "
    "directamente con lo que ya sabes, hazlo sin llamar a ninguna herramienta. Si el "
    "resultado de una herramienta indica que la acción fue denegada, no la reintentes ni "
    "intentes una alternativa — infórmalo y detente."
)


def _build_tool_list() -> list[dict]:
    """CA-02: convierte el catálogo de `tool_registry` a un formato genérico
    {name, description, parameters_schema}, sin filtrar por canal (CA-11) — el filtro real
    ocurre después, dentro de `execute_tool()`."""
    tools = []
    for name in list_tool_names():
        spec = get_tool(name)
        if spec is None:
            continue
        tools.append({
            "name": spec.name,
            "description": spec.description,
            "parameters_schema": spec.parameters_schema,
        })
    return tools


def _build_prompt(task: str, history: list[dict]) -> str:
    """Cada llamada al LLM dentro del loop es un mensaje único y autocontenido (no se
    mantiene una conversación multi-turno nativa del proveedor) — ver Riesgos y mitigación,
    'Por qué un prompt plano y no tool_use/tool_result nativos', para la justificación."""
    if not history:
        return task
    lines = [f"Tarea original del usuario: {task}", "", "Acciones ya ejecutadas en este intento:"]
    for i, h in enumerate(history, 1):
        lines.append(f"{i}. {h['tool']}({h['params']}) -> {h['result']}")
    lines.append("")
    lines.append(
        "Continúa resolviendo la tarea con esta información. Si ya puedes responder, "
        "hazlo directamente sin usar más herramientas."
    )
    return "\n".join(lines)


def run(task: str, channel, user_id: str = "default", agent_name: str = "reasoning_loop") -> str:
    """Punto de entrada del bucle de razonamiento.

    INVARIANTE DE SEGURIDAD: `channel`/`user_id` son SIEMPRE los que pasa el caller
    confiable (nunca argumentos que el LLM decidió) — mismo invariante que
    `security_manager.py:239-246` y el patrón de `core/resolution.py::_try_intent()`. Los
    argumentos de un tool call que el LLM proponga para `channel`/`user_id` (si los
    propusiera) se descartan siempre a favor de estos dos parámetros.
    """
    resolved_channel = security_manager.resolve_channel(channel)
    tools = _build_tool_list()

    history: list[dict] = []
    final_text: Optional[str] = None

    for call_number in range(1, MAX_LLM_CALLS + 1):
        prompt = _build_prompt(task, history)
        response = generate_response([{"role": "user", "content": prompt}], _SYSTEM_PROMPT, tools=tools)

        if not isinstance(response, LLMToolResponse):
            # CONFIRMADO 1: degradación silenciosa (proveedor sin tool-calling) — texto
            # plano, se acepta como respuesta final.
            final_text = response
            break

        if not response.tool_calls:
            # El LLM respondió sin pedir ninguna tool: se acepta como final (caso borde de
            # SPEC — no confundir "no quiso usar herramientas" con "hay que insistir").
            final_text = response.text or "No obtuve una respuesta útil del modelo, Señor."
            break

        # Un tool call por iteración (decide -> ejecuta -> evalúa, CA-07). Si el modelo
        # pidiera varias en el mismo turno, solo se ejecuta la primera en este ciclo; las
        # demás quedan implícitas para que el modelo las vuelva a pedir en la siguiente
        # iteración si aún hacen falta, dentro del límite de 5.
        call = response.tool_calls[0]
        params = dict(call.arguments or {})
        params["channel"] = resolved_channel.value
        params["user_id"] = user_id

        try:
            result = execute_tool(call.name, params, resolved_channel, user_id)
        except ActionDenied as e:
            # CA-08: corta de inmediato. No reintenta, no prueba otra tool, no llama de
            # nuevo al LLM.
            final_text = f"⛔ No puedo ejecutar esa acción, Señor: {e.reason or 'denegada'}."
            break
        except Exception as e:
            # CA-13: tool call malformado / invoke interno falla — no crashea, se informa
            # como resultado fallido de esta iteración y el LLM puede reintentar.
            logger.warning(f"Tool '{call.name}' falló en iteración {call_number}: {e}")
            result = f"Error ejecutando '{call.name}': {e}"

        history.append({"tool": call.name, "params": params, "result": result})

    if final_text is None:
        # CA-07: se agotaron las 5 llamadas sin una respuesta final del LLM.
        final_text = (
            "No pude completar la tarea en el número de intentos disponibles, Señor. "
            "¿Quiere que lo intente de otra forma?"
        )

    # CA-10: un solo par user/assistant por invocación completa del loop, sin importar
    # cuántas iteraciones internas hubo.
    agent_context_manager.update_context(agent_name, user_id, {"role": "user", "content": task})
    agent_context_manager.update_context(
        agent_name, user_id, {"role": "assistant", "content": final_text[:200]}
    )

    return final_text
```

### `ai/llm_provider.py` — extensión de tool-calling

Nuevos dataclasses (junto a las funciones existentes, arriba de `generate_response()`):

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class LLMToolResponse:
    text: Optional[str]
    tool_calls: list  # list[ToolCallRequest]
```

`generate_response()` — firma nueva y lógica de bypass de cache (CA-09):

```python
def generate_response(messages, system_prompt, image_path=None, tools=None):
    provider, vision_provider, fallback_provider, model_name = get_provider_config()

    active_provider = provider
    if image_path and os.path.exists(image_path):
        if vision_provider:
            active_provider = vision_provider

    tools_supported = active_provider in ("anthropic", "deepseek", "openai")
    effective_tools = tools if (tools and tools_supported) else None

    try:
        if effective_tools:
            # CA-09: nunca se cachea una llamada con tools — ver Riesgos y mitigación.
            response = _uncached_call(active_provider, messages, system_prompt, image_path, model_name, tools=effective_tools)
        else:
            response = _cached_call(active_provider, messages, system_prompt, image_path, model_name)
        if isinstance(response, str) and "Error:" in response and fallback_provider and fallback_provider != active_provider:
            raise Exception(response)
        return response
    except Exception as e:
        if fallback_provider and fallback_provider != active_provider:
            try:
                if fallback_provider == "ollama":
                    fallback_resp = _ask_ollama(messages, system_prompt, image_path, "qwen3:8b")
                else:
                    fallback_resp = _uncached_call(fallback_provider, messages, system_prompt, image_path, model_name)
                return f"[Fallback activado. Proveedor original falló por: {str(e)}]\n{fallback_resp}"
            except Exception as e2:
                return f"Error en proveedor principal ({str(e)}) y también en el de emergencia ({str(e2)})."
        return f"Error ({active_provider}): {str(e)}"
```

Nota sobre el fallback: nunca recibe `tools` (ni siquiera si el proveedor de fallback los
soportaría) — mantiene el comportamiento de fallback simple y evita que `reasoning_loop.py`
tenga que manejar un `LLMToolResponse` inesperado viniendo de una ruta de emergencia no
presupuestada en el diseño original del fallback.

`_uncached_call()`/`_cached_call()` ganan un parámetro `tools=None` que solo threadea hacia
`_ask_anthropic`/`_ask_openai`/`_ask_deepseek` (gemini/ollama no lo reciben, sin cambios en su
firma ni body):

```python
def _cached_call(prov_name, messages, system_prompt, image_path, model_name):
    # sin cambios — solo se usa cuando tools es None
    ...

def _uncached_call(prov_name, messages, system_prompt, image_path, model_name, tools=None):
    if prov_name == "gemini":
        return _ask_gemini(messages, system_prompt, image_path, model_name)
    elif prov_name == "ollama":
        return _ask_ollama(messages, system_prompt, image_path, model_name)
    elif prov_name == "openai":
        return _ask_openai(messages, system_prompt, image_path, model_name, tools=tools)
    elif prov_name == "deepseek":
        return _ask_deepseek(messages, system_prompt, image_path, model_name, tools=tools)
    else:
        return _ask_anthropic(messages, system_prompt, image_path, model_name, tools=tools)
```

`_ask_anthropic()` (CA-04) — agrega `tools=None`, arma `input_schema`, parsea bloques
`tool_use`:

```python
def _ask_anthropic(messages, system_prompt, image_path, model_name, tools=None):
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "Error: ANTHROPIC_API_KEY no está configurada."

    model = model_name if model_name else "claude-3-5-sonnet-20241022"
    anthropic_msgs = []
    for m in messages:
        anthropic_msgs.append({"role": m["role"], "content": [{"type": "text", "text": m["content"]}]})

    if image_path and os.path.exists(image_path) and anthropic_msgs and anthropic_msgs[-1]["role"] == "user":
        import base64
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")
        anthropic_msgs[-1]["content"].insert(0, {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}
        })

    api_tools = None
    if tools:
        api_tools = [
            {"name": t["name"], "description": t["description"], "input_schema": t["parameters_schema"]}
            for t in tools
        ]

    client = anthropic.Anthropic(api_key=api_key)
    kwargs = {"tools": api_tools} if api_tools else {}
    response = client.messages.create(
        model=model, max_tokens=1500, system=system_prompt, messages=anthropic_msgs, **kwargs
    )

    if not api_tools:
        return response.content[0].text

    text_parts, tool_calls = [], []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCallRequest(id=block.id, name=block.name, arguments=block.input))
    return LLMToolResponse(text="\n".join(text_parts) if text_parts else None, tool_calls=tool_calls)
```

`_ask_openai()`/`_ask_deepseek()` (CA-05) — mismo patrón, formato OpenAI-SDK compartido:

```python
def _ask_openai(messages, system_prompt, image_path, model_name, tools=None):
    from openai import OpenAI
    api_key = os.environ.get("OPENAI_API_KEY", "")
    try:
        config_path = Path(__file__).parent.parent / "config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            api_key = cfg.get("openai_api_key", api_key)
    except Exception as e:
        logger.debug(f"No se pudo leer openai_api_key de config.json: {e}")
    if not api_key:
        return "Error: OPENAI_API_KEY no está configurada."

    client = OpenAI(api_key=api_key)
    model = model_name if model_name else "gpt-4o-mini"

    openai_msgs = [{"role": "system", "content": system_prompt}]
    for m in messages[:-1]:
        openai_msgs.append({"role": m["role"], "content": m["content"]})

    last_msg = {"role": "user", "content": []}
    last_text = messages[-1]["content"] if messages else ""
    last_msg["content"].append({"type": "text", "text": last_text})
    if image_path and os.path.exists(image_path):
        import base64
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")
        last_msg["content"].append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}})
    openai_msgs.append(last_msg)

    api_tools = None
    if tools:
        api_tools = [
            {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters_schema"]}}
            for t in tools
        ]

    kwargs = {"tools": api_tools, "tool_choice": "auto"} if api_tools else {}
    response = client.chat.completions.create(model=model, messages=openai_msgs, max_tokens=1500, **kwargs)
    msg = response.choices[0].message

    if not api_tools:
        return msg.content

    tool_calls = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_calls.append(ToolCallRequest(id=tc.id, name=tc.function.name, arguments=args))
    return LLMToolResponse(text=msg.content, tool_calls=tool_calls)
```

`_ask_deepseek()` recibe el mismo tratamiento (mismo bloque `api_tools`/parseo, adaptado a su
construcción de mensajes actual — sin bloques de imagen, ya que DeepSeek no soporta visión hoy).

### `agents/skill_tools.py` (nuevo módulo — CA-14 a CA-17)

```python
"""
agents/skill_tools.py
Migración de AgentTool (main.py + skill_manager.get_agent_tools()) a ToolSpec (REQ-007,
CA-14 a CA-17). No modifica agents/tool_registry.py ni skills/skill_manager.py — construye
ToolSpec nuevos desde afuera, reutilizando register_tool().
"""
import logging
from typing import Any, Dict

from agents.tool_registry import ToolSpec, register_tool
from core.security_manager import RiskLevel, security_manager
from router.dispatcher import dispatch_as_tool
from skills.base_skill import BaseSkill
from skills.skill_manager import SkillManager

logger = logging.getLogger(__name__)


def register_dispatcher_tool() -> None:
    """CONFIRMADO 5: catch-all, GREEN — el gate real por acción ocurre dentro de
    dispatch() según lo que resuelva classify_command()."""
    register_tool(ToolSpec(
        name="dispatcher",
        description=(
            "Ejecuta comandos directos del sistema cuando ninguna otra herramienta "
            "encaja mejor: abrir apps, controlar volumen, hora, etc."
        ),
        parameters_schema={
            "type": "object",
            "properties": {"task": {"type": "string", "description": "El comando en lenguaje natural."}},
            "required": ["task"],
        },
        risk_level=RiskLevel.GREEN,
        invoke=dispatch_as_tool,
    ))


def _make_skill_invoke(skill: BaseSkill, intent: str):
    def _invoke(params: Dict[str, Any]) -> str:
        # CA-16: sin auto-gate acá — execute_tool() ya confirmó antes de llegar a esto.
        text = params.get("text", "")
        exec_params = dict(skill.extract_params(intent, text) or {})
        exec_params["channel"] = params.get("channel")
        exec_params["user_id"] = params.get("user_id")
        exec_params["text"] = text
        return skill.execute(intent, exec_params)
    return _invoke


def register_skill_tools(manager: SkillManager) -> None:
    """CA-14/CA-15/CA-16: un ToolSpec por intent de cada skill cargada. Nombre = Intent
    crudo (CONFIRMADO 4). risk_level derivado de security_manager.classify_action(intent),
    ya poblado por REQ-005 (CA-15) — nunca inventado."""
    count = 0
    for skill in manager.get_all_skills():
        for intent in skill.get_intents():
            risk_level = security_manager.classify_action(intent)
            if risk_level is None:
                # Fail-closed en el arranque: mejor romper visible que registrar un tool
                # con un nivel de riesgo inventado.
                raise RuntimeError(
                    f"Intent '{intent}' de la skill '{skill.name}' no tiene risk_level "
                    f"registrado en security_manager — no se migra sin clasificación explícita."
                )
            register_tool(ToolSpec(
                name=intent,
                description=f"{skill.name}: {skill.description}",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Frase del usuario; se usa para extraer los parámetros reales.",
                        },
                    },
                    "required": ["text"],
                },
                risk_level=risk_level,
                invoke=_make_skill_invoke(skill, intent),
            ))
            count += 1
    logger.info(f"{count} intents de skills migrados a ToolSpec")
```

`main.py` — reemplazo del bloque de registro (líneas 8, 31-38):

```python
# antes:
# from core.base_agent import AgentTool
# ...
# orchestrator.register_tool(AgentTool(name="dispatcher", ..., function=dispatch_as_tool))
# for tool in skill_manager.get_agent_tools():
#     orchestrator.register_tool(tool)

# después:
from agents.skill_tools import register_dispatcher_tool, register_skill_tools
...
register_dispatcher_tool()
register_skill_tools(skill_manager)
```

### `core/resolution.py::_try_claude()` (cableado a producción — Pregunta 1, Opción A aprobada)

Único cambio en este archivo. `claude_fn`, cuando SÍ se inyecta (p.ej.
`channels/gateway.py::_ask_claude_for_user()`, que da soporte de imágenes e historial de sesión
propio), se sigue honrando tal cual — `channels/gateway.py` no está en el alcance de SPEC-007 y
no se lo obliga a pasar por el loop nuevo en este REQ. El cambio de comportamiento aplica al
caso default (sin `claude_fn`), que es exactamente el camino que usa `main.py` (el único caller
de producción confirmado en el baseline) y el que hacía inalcanzable a
`_DynamicAgentInstance.execute()`/`reasoning_loop.py` antes de este REQ:

```python
def _try_claude(
    text: str, channel: "ChannelType", user_id: str,
    claude_fn: Optional[Callable[[str], str]] = None,
) -> ResolutionResult:
    """Último recurso — siempre responde algo, nunca retorna `None`.

    REQ-007 (Pregunta 1, Opción A aprobada por el humano): el caso default (sin `claude_fn`
    inyectado) ya no llama directo a `ai/claude_brain.ask_claude()` — cae en
    `core/reasoning_loop.run()`, el bucle real de razonamiento con tools (CA-01). Esto es lo
    que hace alcanzable en producción al loop nuevo, ya que `main.py` (único caller real
    confirmado por baseline-007.md) invoca `resolve()` sin `claude_fn`.

    `claude_fn`, cuando SÍ se inyecta, se sigue honrando exactamente igual que antes de este
    REQ (p.ej. `channels/gateway.py::_ask_claude_for_user()` — historial de sesión propio,
    soporte de imágenes). `channels/gateway.py` no está en el alcance de SPEC-007 — no se
    fuerza a los canales que ya inyectan su propio `claude_fn` a pasar por el loop nuevo en
    este REQ (deuda documentada para un REQ futuro, ver Pregunta 2).
    """
    if claude_fn is not None:
        result = claude_fn(text)
        return ResolutionResult(text=result, matched_by="claude", channel=channel)

    from core.reasoning_loop import run as reasoning_run

    result = reasoning_run(text, channel, user_id)
    return ResolutionResult(text=result, matched_by="claude", channel=channel)
```

### `core/orchestrator.py::_decompose()` (CA-12)

```python
import re

_DECOMPOSE_TRIGGERS = [
    "y", "luego", "después", "además", "también",
    "al mismo tiempo", "mientras", "and", "then",
]

def _decompose(self, text: str) -> List[str]:
    for trigger in _DECOMPOSE_TRIGGERS:
        pattern = r'\b' + re.escape(trigger) + r'\b'
        if re.search(pattern, text, re.IGNORECASE):
            parts = [p.strip() for p in re.split(pattern, text, flags=re.IGNORECASE) if p.strip()]
            if len(parts) >= 2 and all(len(p) > 3 for p in parts):
                logger.info(f"Tarea descompuesta en {len(parts)} sub-tareas vía '{trigger}'")
                return parts
    return [text]
```

`MAX_CHAIN_DEPTH`/`_execute_agent_chain()` no cambian (CONFIRMADO 3). Único cambio adicional en
este archivo: `_execute_single_agent()`/`_execute_agent_chain()` pasan `[]` en vez de
`self._tools` a `self._factory.create_agent(...)` (ver "Decisión CA-17").

## Decisión CA-17 — qué se elimina y qué se mantiene, y por qué

CONFIRMADO 6 exige decidir explícitamente, no dejarlo ambiguo. Encontré una restricción dura que
SPEC/baseline no mencionan: **`skills/skill_manager.py` importa `AgentTool` y lo sigue
construyendo dentro de `get_agent_tools()`**, y SPEC-007 no autoriza tocar `skill_manager.py`.
Eso fija el resultado:

| Pieza | Decisión | Motivo |
|-------|----------|--------|
| `AgentTool` (clase) | **Se mantiene** | Dependencia dura no removible: `skill_manager.py::get_agent_tools()` sigue construyéndolo. Se documenta con un comentario que ya no se usa para despacho real — solo queda como oráculo de conteo para el test de deriva (ver Pruebas sugeridas) y para no romper `tests/test_agents.py` (CA-2/CA-3 de REQ-002, que construyen `AgentTool` y `factory.create_agent(task, [tool])` directamente). |
| `BaseAgent.tools`/`add_tool()` | **Se mantiene sin cambios** | `tests/test_agents.py::test_ca2_base_agent` verifica `len(agent.tools) == 1` tras `create_agent()` — cambiar esto rompe una regresión de REQ-002 que no está en el alcance de este REQ. |
| `DynamicAgentFactory.create_agent(task, available_tools)` | **Se mantiene la firma sin cambios** | Mismo motivo — `tests/test_agents.py` la llama con `[tool]` directamente. |
| `_DynamicAgentInstance.execute()` | **Cambia el cuerpo** (CA-01) | Ya no itera `self.tools` — delega a `reasoning_loop.run()`. `self.tools` queda como atributo estructural sin uso funcional en `execute()`, pero no se retira (mismo motivo de arriba). |
| `AgentOrchestrator.register_tool()` / `self._tools` | **Se eliminan en este REQ** | Verificado (`tests/test_agents.py::test_ca1_orchestrator`) que ningún test llama `register_tool()` ni inspecciona `self._tools`. Tras quitar el bloque de `main.py` que los alimentaba (CA-14), quedan sin ningún escritor ni lector real. `_execute_single_agent()`/`_execute_agent_chain()` pasan `[]` en su lugar — el contenido de esa lista ya no importa porque `execute()` no la usa. |
| `_process_with_agents()` / `_execute_single_agent()` / `_execute_agent_chain()` | **Se mantienen, sin retirar** | El propio docstring de REQ-006 en `core/orchestrator.py::process_task()` los declara infraestructura preservada a propósito ("quedan disponibles para uso directo"), no código muerto accidental. Retirarlos sería una decisión de otro REQ, no de este. Efecto colateral positivo: como ahora delegan en `reasoning_loop.py` vía `_DynamicAgentInstance`, un futuro caller de `_execute_agent_chain()` obtendría razonamiento real por sub-tarea en vez del for-loop dumb de antes. |
| `tests/test_base_agent.py` (4 tests) | **Se reemplazan 3 de 4** | Ver sección siguiente. |

### Disposición de `tests/test_base_agent.py`

De los 4 tests actuales:
- `test_dynamic_agent_no_confunde_denial_con_exito`, `test_dynamic_agent_prueba_siguiente_tool_tras_denial`,
  `test_dynamic_agent_execute_devuelve_resultado_exitoso` prueban la semántica exacta del
  for-loop que CA-01 ordena eliminar (probar tools en orden, caer al siguiente ante denial).
  Esa semántica deja de existir — **se eliminan y se reemplazan** por tests nuevos contra
  `core/reasoning_loop.py` (ver Pruebas sugeridas) más un test de que
  `_DynamicAgentInstance.execute()` delega correctamente.
- `test_agent_tool_execute_no_propaga_excepcion_a_llamador` prueba `AgentTool.execute()` en sí
  (no `_DynamicAgentInstance.execute()`), que **no cambia** en este REQ — se mantiene tal cual.

## Flujo de datos

```
Usuario (cualquier canal)
   │
   ▼
core/resolution.py::resolve() → resolver "claude" (_try_claude, último recurso)
   │
   ├─ claude_fn inyectado (p.ej. channels/gateway.py) → comportamiento sin cambios (ask_claude())
   └─ sin claude_fn (p.ej. main.py, único caller de producción confirmado) →
   ▼
core/reasoning_loop.py::run(task, channel, user_id)
   │
   ├─ security_manager.resolve_channel(channel)   ← única fuente de verdad de canal
   ├─ _build_tool_list()                          ← catálogo completo de tool_registry, sin filtrar
   │
   ▼
 loop (máx. 5 iteraciones):
   ├─ _build_prompt(task, history)                ← un mensaje plano, autocontenido
   ├─ ai/llm_provider.py::generate_response(msgs, system_prompt, tools=tools)
   │     ├─ proveedor soportado (anthropic/deepseek/openai) → LLMToolResponse
   │     └─ proveedor no soportado (gemini/ollama/otro)    → str plano (degradación silenciosa)
   │
   ├─ si no hay tool_calls → responde final, rompe el loop
   ├─ si hay tool_call →
   │     ├─ params["channel"]/["user_id"] reasignados desde el caller confiable (NUNCA del LLM)
   │     ├─ agents/tool_registry.py::execute_tool(name, params, channel, user_id)
   │     │     ├─ ActionDenied → mensaje de denegación, rompe el loop (CA-08)
   │     │     └─ éxito/Exception → resultado se agrega a `history`, sigue el loop
   │     └─ (el invoke real de la tool nunca se llama directo — solo vía execute_tool)
   │
   ▼
 tras el loop (o al agotar las 5 llamadas):
   agent_context_manager.update_context() × 2  (1 user + 1 assistant, CA-10)
   return final_text
```

## Archivos a modificar/crear

- `core/reasoning_loop.py` — **nuevo**.
- `agents/skill_tools.py` — **nuevo**.
- `core/base_agent.py` — modificar `_DynamicAgentInstance.execute()`.
- `core/orchestrator.py` — modificar `_decompose()`; modificar `_execute_single_agent()`/
  `_execute_agent_chain()`; eliminar `register_tool()`/`self._tools` de `AgentOrchestrator`.
- `ai/llm_provider.py` — agregar `ToolCallRequest`/`LLMToolResponse`; modificar
  `generate_response()`, `_cached_call()`/`_uncached_call()`, `_ask_anthropic()`,
  `_ask_openai()`, `_ask_deepseek()`.
- `main.py` — reemplazar bloque de registro de tools (líneas 8, 31-38).
- `tests/test_base_agent.py` — reemplazar 3 de 4 tests (ver "Disposición" arriba).
- `tests/test_reasoning_loop.py` — **nuevo**.
- `tests/test_llm_provider.py` — **nuevo** (no existe hoy, per baseline).
- `core/resolution.py` — modificar `_try_claude()` (aprobado — Opción A, Pregunta 1).

## Dependencias nuevas

Ninguna. Anthropic SDK (`tool_use`/`tools=`) y OpenAI SDK (`tools=`/`tool_calls`) ya están
instalados y en uso por `ai/llm_provider.py` — el tool-calling es parte de las mismas versiones
de API que ya se consumen, no requiere upgrade de paquete. No se agrega nada a
`requirements.txt`.

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| Colisión de cache: dos llamadas con mismo texto pero distinta disponibilidad de tools podrían compartir `_cache_key()` (que no incluye `tools`). | **No se agrega `tools` a `_cache_key()`** — en vez de eso, `generate_response()` bypassa `_cached_call()`/`_response_cache` por completo cuando `tools` está presente y el proveedor lo soporta (`_uncached_call()` directo). Es más simple que hashear el schema completo de tools en cada llamada y elimina la colisión de raíz en vez de mitigarla parcialmente. Costo: las llamadas del loop nunca se benefician de cache — aceptable porque son inherentemente conversacionales/con estado (cada iteración depende del resultado de la anterior), no son candidatas naturales a cache de todos modos. |
| Multi-turno nativo de tool-calling (bloques `tool_use`/`tool_result` de Anthropic, mensajes `role="tool"` de OpenAI) es un protocolo distinto por SDK y frágil de mantener correctamente en los 3 proveedores a la vez, con cero cobertura de test existente hoy (`tests/test_llm_provider.py` no existe). | Se elige **no** mantener el protocolo nativo de continuación de tool-calling. Cada iteración del loop es una llamada de un solo turno (`messages=[{"role":"user","content": prompt}]`), con el historial de tools ya ejecutadas aplanado como texto dentro del propio prompt (`_build_prompt()`). Evita el riesgo de errores 400 por bloques `tool_use` sin su `tool_result` correspondiente, y hace que `generate_response()` sea trivialmente mockeable en tests (se mockea el valor de retorno, no la forma exacta de un objeto de respuesta del SDK). Trade-off: se pierde algo de eficiencia de contexto nativo del proveedor — aceptable dado el límite de 5 llamadas y que ninguna SPEC exige continuidad nativa. |
| `_DynamicAgentInstance.execute()` queda con `self.tools` sin uso funcional real (solo estructural) — puede confundir a quien lea el código pensando que todavía se usa. | Se documenta explícitamente con un comentario en el cuerpo de `execute()` explicando que `self.tools` ya no se consulta — la fuente de tools ahora es siempre `agents/tool_registry.py` vía `reasoning_loop.run()`. |
| Reachability (resuelto — Pregunta 1, Opción A aprobada): sin cablear, el bucle de razonamiento quedaba sin ningún camino de producción que lo invocara. | `core/resolution.py::_try_claude()` cae en `reasoning_loop.run()` cuando no hay `claude_fn` inyectado — camino que usa `main.py`, único caller de producción confirmado por baseline. |
| Pérdida de personalidad/memoria de `ask_claude()` en el fallback conversacional sin `claude_fn` (resuelto — Pregunta 2, mitigación aceptada). | System prompt propio de `reasoning_loop.py` mantiene tono JARVIS; memoria semántica y side-channel de aprendizaje quedan fuera de alcance, documentados como deuda para un REQ futuro (no se resuelven en REQ-007). |
| `channels/gateway.py` (Telegram/Discord vía `claude_fn` inyectado) no pasa por el loop nuevo en este REQ — solo el camino sin `claude_fn` (`main.py`) lo usa. | Decisión deliberada de alcance: `channels/gateway.py` no está en la lista de módulos de SPEC-007, no se analizó su comportamiento (imágenes, sesión por usuario) en este REQ. Cablearlo también queda para un REQ futuro si se decide extender el loop a esos canales. |
| Latencia: hasta 5 llamadas secuenciales al LLM en el peor caso, sin budget de tiempo definido por SPEC. | Riesgo heredado y aceptado explícitamente por SPEC-007 (no se pidió un límite de tiempo) — no se agrega uno por iniciativa propia para no introducir comportamiento no pedido; se deja registrado para que `orion-qa`/el humano lo evalúen en la prueba manual. |
| `register_skill_tools()` podría fallar el arranque completo de O.R.I.O.N. si un intent nuevo se agrega a una skill sin clasificar su riesgo en `security_manager`. | Comportamiento intencional (fail-closed en el arranque, no en runtime) — mejor un crash visible al iniciar que un tool silenciosamente inalcanzable o, peor, mal clasificado. Coherente con el principio fail-closed de REQ-005. |

## Pruebas sugeridas

Por cada criterio de la SPEC:

- **CA-01**: test que crea `_DynamicAgentInstance` y mockea `core.reasoning_loop.run`,
  verificando que `execute()` lo invoca con `(task, channel, user_id)` correctos y retorna su
  resultado tal cual.
- **CA-02**: test de `_build_tool_list()` — dado un `ToolSpec` registrado en `tool_registry`
  con un `parameters_schema` conocido, verificar que aparece sin modificaciones en la lista
  generada.
- **CA-03**: test de `generate_response()` sin `tools=` — debe comportarse exactamente igual
  que antes de este REQ (regresión, usar los tests ya existentes de `ai/claude_brain.py` como
  referencia de comportamiento no roto).
- **CA-04**: test de `_ask_anthropic(..., tools=[...])` mockeando `anthropic.Anthropic` para que
  devuelva un `response.content` con un bloque `tool_use` — verificar que se parsea en
  `LLMToolResponse` con el `ToolCallRequest` correcto.
- **CA-05**: mismo test para `_ask_openai`/`_ask_deepseek`, mockeando `client.chat.completions.create`
  para devolver `message.tool_calls`.
- **CONFIRMADO 1**: test de `generate_response()` con `active_provider="gemini"` y `tools=[...]`
  — verificar que llega a `_ask_gemini()` sin `tools` y retorna `str`, nunca `LLMToolResponse`.
- **CA-06**: test estático — `assert ".invoke(" not in Path("core/reasoning_loop.py").read_text()`.
- **CA-07**: test con `generate_response` mockeado para devolver siempre un `tool_call` válido
  (nunca texto final) — verificar que `run()` hace exactamente 5 llamadas y retorna el mensaje
  de límite, no una 6ª llamada.
- **CA-08**: test con `execute_tool` mockeado para levantar `ActionDenied` en la primera
  iteración — verificar que `generate_response` se llamó solo 1 vez (no reintenta).
- **CA-09**: test que llama `generate_response(msgs, prompt, tools=[...])` dos veces con el
  mismo `messages`/`system_prompt` y mockea `_uncached_call`/`_cached_call` — verificar que se
  llamó `_uncached_call` ambas veces (nunca `_cached_call` cuando hay tools).
- **CA-10**: test que corre `run()` con 3 iteraciones de tool-calling simuladas — verificar
  `agent_context_manager.update_context` se llamó exactamente 2 veces en total.
- **CA-11**: test que registra tools con distintos `risk_level` y verifica que
  `_build_tool_list()` los incluye todos sin importar `channel` (no recibe `channel` como
  argumento siquiera).
- **CA-12**: casos "me llamo Yolanda" (no debe descomponer), "compra pan y luego café" (debe
  descomponer en 2), "él y tú vamos" (match de `\by\b` pero partes ≤3 chars → red de seguridad
  descarta el split, retorna texto completo).
- **CA-13**: test con `execute_tool` mockeado para levantar `KeyError`/`Exception` genérica —
  verificar que el loop no crashea y continúa a la siguiente iteración.
- **CA-14/CONFIRMADO 4**: test que corre `register_skill_tools()` sobre un `SkillManager` real
  y verifica `get_tool("OPEN_FOLDER")` existe (nombre = Intent crudo, no `skill_open_folder`).
- **CA-15**: test con intents reales ya clasificados — `get_tool("GET_TIME").risk_level ==
  RiskLevel.GREEN`, `get_tool("SYS_POWER_OFF").risk_level == RiskLevel.YELLOW`.
- **CA-16**: test que mockea `skill.extract_params`/`skill.execute` y verifica que el `invoke`
  generado los llama en ese orden, y que nunca llama `security_manager.require_confirmation`.
- **CONFIRMADO 5**: `get_tool("dispatcher").risk_level == RiskLevel.GREEN`.
- **Test de deriva** (sugerido, no ligado a un CA puntual): `len(skill_manager.get_agent_tools())
  == len(list_tool_names()) - 1` (menos 1 por `"dispatcher"`) tras `register_skill_tools()` —
  detecta si se agrega una skill nueva y alguien olvida que ya no hace falta tocar
  `main.py` (se migra sola) pero si el conteo de intents diverge, algo se rompió.
- Regresión completa: `pytest tests/ --tb=short -v` — los 95 tests que pasan hoy (baseline)
  deben seguir pasando, salvo los 3 de `test_base_agent.py` reemplazados a propósito (documentado
  arriba, no es una regresión real).
- **Cableado (Pregunta 1, Opción A)**: test de `core/resolution.py::_try_claude()` — sin
  `claude_fn`, mockear `core.reasoning_loop.run` y verificar que se llama con
  `(text, channel, user_id)` y que su resultado se propaga en `ResolutionResult.text`; con
  `claude_fn` inyectado, verificar que `reasoning_loop.run` NO se llama y el comportamiento es
  idéntico al de antes de este REQ (se sigue llamando `claude_fn(text)`).
