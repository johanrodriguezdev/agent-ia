# Baseline REQ-007 — Bucle de razonamiento real con LLM

**Fecha:** 2026-08-04
**Agente:** orion-baseline
**SPEC de referencia:** `workspace/adjuntos/REQ-007/spec/SPEC-007.md` (✅ APROBADA, 17 CA)

## Estado actual del sistema

### 1. `core/base_agent.py` — `_DynamicAgentInstance.execute()` (líneas 87-118)
No existe razonamiento con LLM. `execute()` (líneas 96-118) itera `self.tools: List[AgentTool]`
en un `for` de orden fijo:
```python
def execute(self, task: str, context: dict = None) -> str:
    for tool in self.tools:
        try:
            result = tool.execute({...})
        except ActionDenied:
            continue   # REQ-006/CA-09/H7 — ya corregido, no confunde denegación con éxito
        except Exception:
            continue
        if result:
            return result
    return f"No pude completar la tarea '{task[:60]}' con las herramientas disponibles."
```
- El fix de REQ-006 (CA-09/H7) ya está aplicado: una `ActionDenied` hace `continue` a la
  siguiente tool en vez de tratar el string de denegación como resultado exitoso. Sigue
  siendo el comportamiento correcto a preservar en `CA-08` de REQ-007 salvo que ahora, según
  SPEC-007, una `ActionDenied` debe **parar el loop de inmediato** en vez de probar otra
  tool — es un cambio de comportamiento deliberado, no una regresión.
- No hay ninguna llamada a `ai/llm_provider.py` ni a ningún LLM dentro de este método. La
  "elección" de herramienta es puramente el orden de `self.tools`.
- La clase `AgentTool` (líneas 9-22) es un wrapper simple: `name`, `description`, `function`,
  y `execute(params)` que atrapa cualquier excepción no-`ActionDenied` y la convierte en un
  string de error (nunca la relanza) — este es el contrato que CA-17 debe reemplazar por
  `ToolSpec`.
- `BaseAgent.add_tool()`/`self.tools` (líneas 30, 40-41) y `DynamicAgentFactory` (líneas
  51-84) no llaman a ningún LLM tampoco — `_generate_prompt()` (líneas 72-80) arma un texto
  de prompt pero nada lo envía a `ai/llm_provider.py`; es texto muerto (nunca se usa desde
  `execute()`).

### 2. `ai/llm_provider.py`
`generate_response(messages, system_prompt, image_path=None)` (línea 60) es la única
función pública. **Cero soporte de tool-calling nativo hoy**, confirmado por lectura
completa:
- Ningún `_ask_*` acepta ni envía un parámetro `tools=`.
- `_ask_anthropic()` (línea 85): `return response.content[0].text` — asume que el primer
  bloque de contenido es siempre texto. Si la API devolviera un bloque `tool_use` en la
  posición 0 (lo haría si se le pasaran tools y el modelo decidiera usarlas), esta línea
  lanzaría `AttributeError` (un bloque `tool_use` no tiene atributo `.text`) o devolvería
  contenido incorrecto — confirma el hallazgo de `orion-spec` en el contexto de REQ-007.
- `_ask_deepseek()`/`_ask_openai()` (líneas 207, 249) usan el SDK `openai` (`client.chat.completions.create`)
  pero no pasan `tools=`/`tool_choice`, y no parsean `response.choices[0].message.tool_calls`.
  Como ambos ya usan el SDK `openai`, son los candidatos naturales para CA-05 (mismo
  formato de tools, comparten código de parseo).
- `_ask_gemini()`/`_ask_ollama()` (líneas 116, 151): sin tool-calling, y SPEC-007 los deja
  fuera de alcance explícitamente (no se tocan).
- Proveedores soportados hoy (`_uncached_call`, línea 33): `gemini`, `ollama`, `openai`,
  `deepseek`, y default `anthropic` (si `prov_name` no matchea ninguno de los anteriores).
  Los 3 del alcance de REQ-007 (`anthropic`, `deepseek`, `openai`) ya están representados.
- `get_provider_config()` (línea 45) lee `config.json`: `ai_provider` activo hoy es
  `"deepseek"`, `ai_model="deepseek-chat"` — confirmado también por `orion-spec` en el
  contexto. Está dentro del alcance de tool-calling nativo de REQ-007.
- Existe caché de respuestas por hash de `(messages, system_prompt, image_path, provider)`
  (`_cached_call`, línea 19) — un parámetro nuevo de `tools` que no entre en la cache key
  produciría collisiones de caché (una respuesta con tools cacheada se devolvería para una
  llamada sin tools con el mismo texto, o viceversa) si `orion-architect` no lo contempla
  explícitamente al extender la firma de `generate_response()`. Se deja como nota para
  arquitectura, no estaba en el alcance de este baseline decidir la solución.
- Ningún vestigio de tool-calling: confirmado, coincide con el hallazgo ya registrado por
  `orion-spec` en `REQ-007-context.md` (2026-08-04, "Hallazgo NO documentado en el diseño [B]").

### 3. `agents/tool_registry.py`
Contrato `ToolSpec` (dataclass frozen, línea 22: `name`, `description`, `parameters_schema`,
`risk_level`, `invoke`, `origin="local"`) y funciones `register_tool()`, `get_tool()`,
`list_tool_names()`, `execute_tool()` — todo construido en REQ-006, **sin cambios
previstos por SPEC-007** (confirmado: "Sin cambios de código" en la tabla de módulos
afectados).

Hoy solo hay **3 `ToolSpec` registrados** (líneas 152-194), los 3 `risk_level=GREEN`:
- `task_create` — wrapea `tasks.task_manager.task_manager.create_from_natural()`.
- `task_list` — wrapea `task_manager.get_task_summary()`.
- `task_complete` — wrapea lógica de completado por ID o auto-detección si hay una sola
  tarea pendiente.

`execute_tool(name, params, channel, user_id)` (línea 71) es el único punto de gate real
para `ToolSpec`: si `get_tool(name)` es `None` levanta `ActionDenied("tool no registrado")`;
si `security_manager.require_confirmation()` deniega, levanta `ActionDenied("denegado por
security_manager")`; solo si ambos pasan invoca `spec.invoke(params)`. Este es el único
punto que `core/reasoning_loop.py` debe usar (CA-06) — nunca `ToolSpec.invoke` directo.

### 4. `core/orchestrator.py` — `_decompose()` (líneas 91-102) y registro `AgentTool`
Bug confirmado tal cual lo describe la SPEC (CA-12/CA-24 de `[B]`):
```python
simple_triggers = ["y", "luego", "después", "además", "también", ...]
for trigger in simple_triggers:
    if trigger in text.lower():
        parts = [p.strip() for p in text.split(trigger) if p.strip()]
```
`"y" in text.lower()` es un chequeo de substring, no de palabra completa — cualquier texto
con "hoy", "voy", "muy", etc. dispara la descomposición y `text.split("y")` corta la
palabra por dentro, generando sub-tareas espurias. No hay ningún `\b`/regex de palabra
completa hoy. Sin red de seguridad de longitud mínima (`all(len(p) > 3 for p in parts)`)
tampoco existe actualmente.

`AgentOrchestrator.__init__` (línea 16): `self._tools: List[AgentTool] = []`.
`register_tool(tool: AgentTool)` (línea 21) solo hace `self._tools.append(tool)` +
log — sin ningún gate de seguridad propio (el gate ocurre dentro de cada `AgentTool.execute()`
según cómo esté construida la `function` que envuelve, no en el registro). `self._tools`
se pasa tal cual a `DynamicAgentFactory.create_agent()` en `_execute_single_agent()` (línea
105) y `_execute_agent_chain()` (línea 131) — es el mismo `List[AgentTool]` que termina en
`_DynamicAgentInstance.tools`, el `for` que CA-01 debe eliminar.

`MAX_CHAIN_DEPTH = 5` (línea 9) — confirmado sin relación con el límite de 5 iteraciones del
loop de razonamiento (son contadores independientes, CONFIRMADO 3 de la SPEC ya lo aclara).

### 5. `main.py` — registro de `AgentTool` (líneas 31-38)
Confirmado el "dispatcher" catch-all tal cual lo describe la SPEC:
```python
orchestrator.register_tool(AgentTool(
    name="dispatcher",
    description="Ejecuta comandos directos del sistema: abrir apps, controlar volumen, hora, etc.",
    function=dispatch_as_tool
))

for tool in skill_manager.get_agent_tools():
    orchestrator.register_tool(tool)
```
`dispatch_as_tool` viene de `router/dispatcher.py` (no auditado línea por línea en este
baseline porque SPEC-007 no lo lista como módulo afectado — solo se referencia como origen
de la función que envuelve el `AgentTool "dispatcher"`).

Este es el único punto de wiring real de `AgentTool` en toda la aplicación — no hay otro
sitio en el código que llame a `orchestrator.register_tool()`.

### 6. `skills/skill_manager.py` — `get_agent_tools()` (líneas 87-97) y `_make_gated_tool_fn()` (líneas 100-110)
Confirmado el patrón exacto que CA-16 dice que NO debe repetirse:
```python
def get_agent_tools(self) -> List[AgentTool]:
    tools = []
    for skill in self.skills:
        for intent in skill.get_intents():
            tool = AgentTool(
                name=f"skill_{intent.lower()}",
                description=f"{skill.name}: {skill.description}",
                function=_make_gated_tool_fn(skill, intent)
            )
            tools.append(tool)
    return tools

def _make_gated_tool_fn(skill, intent):
    def _run(params: dict) -> str:
        channel = params.get("channel") or (params.get("context") or {}).get("channel")
        if not security_manager.require_confirmation(intent, channel, ...):
            return "⛔ Acción no autorizada."
        return skill.execute(intent, params)
    return _run
```
Dos hallazgos confirmados, ambos ya anticipados textualmente por SPEC-007/CA-16:
- **Nunca llama a `skill.extract_params(intent, text)`** — pasa `params` (el dict crudo
  recibido, que trae `task`/`context`/`channel` desde `_DynamicAgentInstance.execute()`,
  no los parámetros extraídos de la skill) directo a `skill.execute(intent, params)`. Los
  `ToolSpec` migrados en CA-16 deben llamar `extract_params()` antes de `execute()`, algo
  que este código actual no hace.
- **Auto-gate duplicado**: `_run()` llama `security_manager.require_confirmation()`
  directamente dentro de `invoke`/`function`, y si deniega devuelve el string `"⛔ Acción
  no autorizada."` como si fuera una respuesta normal — no lanza `ActionDenied`. Esto es
  exactamente el "mismo bug de forma que CA-09/H7 ya corrigió para el resto del sistema"
  que menciona la SPEC: en el `for` actual de `_DynamicAgentInstance.execute()`, si esta
  función devuelve ese string de denegación, `if result: return result` lo trata como
  resultado válido y lo devuelve al usuario como si la acción se hubiera ejecutado con
  éxito. `AgentTool.execute()` (en `core/base_agent.py`) no distingue este string de un
  resultado exitoso real.
- `name=f"skill_{intent.lower()}"` — confirma el prefijo que CONFIRMADO 4 de la SPEC dice
  que el `ToolSpec` migrado NO debe reusar (el nuevo debe usar el `Intent` tal cual, ej.
  `"OPEN_APP"`, sin prefijo `skill_` ni lowercase).
- `load_all_skills()` (línea 16) descubre dinámicamente cualquier `.py` en `skills/` que
  herede de `BaseSkill` — confirma el riesgo de drift que la SPEC ya señala (una skill
  nueva agregada después de la migración no tendría `ToolSpec` a menos que se re-ejecute
  la migración).

**Inventario real de skills/intents hoy** (10 archivos de skill, confirmado por lectura de
`get_intents()` de cada uno — total 22 intents + el `"dispatcher"` catch-all = **23
`AgentTool` en total** que `main.py` registra hoy vía el `for` de la línea 37-38 más el
registro manual de la línea 31):

| Skill | Intents | Cantidad |
|---|---|---|
| `code_execution_skill.py` | `EXECUTE_CODE` | 1 |
| `info_skill.py` | `SYSTEM_INFO`, `CPU_INFO`, `RAM_INFO` | 3 |
| `screen_analysis_skill.py` | `ANALYZE_SCREEN` | 1 |
| `file_system_skill.py` | `OPEN_FOLDER`, `LIST_FILES`, `CREATE_FILE` | 3 |
| `media_skill.py` | `PLAY_MUSIC` | 1 |
| `system_control_skill.py` | `SYS_VOL_UP`, `SYS_VOL_DOWN`, `SYS_MUTE`, `TAKE_SCREENSHOT`, `SYS_POWER_OFF`, `GET_TIME` | 6 |
| `web_browsing_skill.py` | `BROWSE_WEB` | 1 |
| `skill_creator_skill.py` | `CREATE_SKILL`, `MODIFY_SKILL`, `LIST_SKILLS`, `DELETE_SKILL` | 4 |
| `weather_skill.py` | `GET_WEATHER` | 1 |
| `file_analysis_skill.py` | `FILE_ANALYSIS` | 1 |
| **Total intents de skills** | | **22** |
| `+1` catch-all `"dispatcher"` (`main.py:31-35`) | | **23** |

Este número (22, sin el `+1`) es exactamente el que SPEC-007 sugiere usar como test de
drift ("`len(skill_manager.get_agent_tools())` + el `+1` del dispatcher") — confirmado
como línea base útil para `orion-tester`.

Nota sobre `risk_level` a migrar (relevante para CA-15): este baseline no vuelca aquí la
clasificación completa de `security_manager` para los 22 intents — queda para
`orion-architect`/`orion-dev`, que deben leer `classify_action(intent)` para cada uno.
`core/security_manager.py` expone `classify_action()` (línea 211) y `register_action()`
(línea 194), y `CHANNEL_ALLOWED_LEVELS` (línea 54) sigue vigente sin cambios previstos.

## Archivos que serán modificados (previsión, según SPEC-007 "Módulos afectados")
- `core/reasoning_loop.py` — **nuevo**. No existe hoy (confirmado — falla `py_compile`
  con `FileNotFoundError` al día de este baseline). Bucle de razonamiento completo.
- `core/base_agent.py` — elimina el `for` de `_DynamicAgentInstance.execute()`, delega a
  `reasoning_loop.py`. Posible eliminación o marcado de `AgentTool` como obsoleto (CA-17,
  decisión de `orion-architect`, a documentar explícitamente cualquiera sea la opción).
- `ai/llm_provider.py` — `generate_response()` gana parámetro opcional de tools;
  `_ask_anthropic()`, `_ask_deepseek()`, `_ask_openai()` ganan soporte de tool-calling y
  parseo de `tool_use`/`tool_calls`. `_ask_gemini()`/`_ask_ollama()` no se tocan.
- `core/orchestrator.py` — fix de `_decompose()` (word boundary `\b` + red de seguridad de
  longitud). Posible eliminación/marcado obsoleto de `register_tool()`/`self._tools`
  (misma decisión CA-17 que en `base_agent.py`).
- `main.py` — el registro de `AgentTool` (líneas 31-38) se reemplaza por construcción de
  `ToolSpec` vía `agents/tool_registry.py::register_tool()`.
- `agents/tool_registry.py` — **sin cambios de código** (solo se consume `register_tool()`
  desde fuera).
- `skills/skill_manager.py` — **sin cambios de código** (solo se consume `get_agent_tools()`
  y/o `get_all_skills()`+`get_intents()`/`extract_params()` desde fuera).
- Tests nuevos (ubicación esperada `tests/test_reasoning_loop.py` o similar, y ampliación de
  `tests/test_agents.py`/`tests/test_llm_provider.py` si existe) — a definir por
  `orion-architect`/`orion-dev`, no hay archivo de test para estos módulos todavía (ver
  siguiente sección).

## Fallos pre-existentes (no atribuibles a este REQ)
Ninguno.

- `python -m pytest tests/ --tb=short -q` → **95 passed, 0 failed** (3 warnings no
  relacionados: `DeprecationWarning` de `aifc`/`audioop` en la librería `speech_recognition`
  de terceros, y un `PytestReturnNotNoneWarning` en `tests/test_agents.py::test_ca1_orchestrator`
  que retorna un valor en vez de solo usar `assert` — preexistente, cosmético, no es un
  fallo). Confirma lo que el contexto de REQ-006 ya declaraba (95 tests en verde) — verificado
  aquí de nuevo por `orion-baseline`, no asumido.
- `python -m py_compile` limpio en los módulos que SPEC-007 identifica como afectados y que
  ya existen hoy: `core/base_agent.py`, `core/orchestrator.py`, `ai/llm_provider.py`,
  `agents/tool_registry.py`, `main.py`, `skills/skill_manager.py`. También se verificó
  `core/security_manager.py`, `core/confirmation.py`, `core/resolution.py` (dependencias
  directas del gate que el loop debe seguir usando) — sin errores de compilación.
- `core/reasoning_loop.py` no existe todavía — confirmado (no es un fallo, es el módulo que
  este REQ crea).
- Cobertura de test existente relevante a los módulos que REQ-007 va a modificar (confirmado
  leyendo `tests/`, 13 archivos de test en total): `tests/test_base_agent.py` (4 tests,
  específicamente el fix H7/CA-09 de REQ-006 sobre `_DynamicAgentInstance.execute()` — el
  `for` que CA-01 de REQ-007 elimina; `orion-dev` debe revisar si estos tests siguen
  aplicando tal cual, se adaptan al nuevo `reasoning_loop.py`, o quedan como regresión del
  comportamiento legado si `AgentTool`/`_DynamicAgentInstance` se retiran por CA-17) y
  `tests/test_tool_registry.py` (7 tests sobre `ToolSpec`/`register_tool`/`execute_tool`,
  sin relación con `_DynamicAgentInstance`, no deberían verse afectados por CA-01 pero sí
  son la base de regresión de `execute_tool()` que CA-06 exige seguir usando). No hay
  ningún archivo de test dedicado a `ai/llm_provider.py` hoy (confirmado — no existe
  `tests/test_llm_provider.py` ni equivalente); `orion-tester` no tiene base de regresión
  previa para tool-calling en ese módulo, todos los tests de CA-03/CA-04/CA-05 serán
  nuevos. `tests/test_agents.py` cubre `core/orchestrator.py` (incluye
  `test_ca1_orchestrator`, ver warning cosmético arriba) pero no prueba `_decompose()`
  específicamente con casos de la letra "y" — tampoco hay hoy un test que reproduzca el
  bug CA-24/CA-12 antes del fix, por lo que ese test también será nuevo en REQ-007.
