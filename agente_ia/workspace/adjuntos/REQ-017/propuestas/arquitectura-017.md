# Arquitectura REQ-017 — Completar/listar/crear tareas en lote sin trabarse por falta de ID exacto

**Agente:** orion-architect
**Fecha:** 2026-08-20
**Estado:** ✅ APROBADA por Johan (2026-08-20), con 2 ajustes menores respecto al texto original de
esta propuesta — ver "Ajustes de Johan" abajo. Handoff emitido a `orion-dev`.

## Ajustes de Johan (respuesta a §10 de la versión original de este documento)

1. **Pregunta 1 (bug preexistente "completa la tarea #3"/"completa mi tarea", §0):** NO se arregla
   en este REQ. Johan decidió dejarlo fuera de alcance explícitamente y que se abra como REQ aparte
   en el futuro (no lo abre este flujo ahora) — ver "Descartado del alcance" en
   `REQ-017-context.md`. El resto de §0 sigue tal cual: el hallazgo queda documentado para que no se
   pierda, pero no cambia ningún CA ni ninguna línea de código de esta propuesta.
2. **Pregunta 2 ("todo" singular como disparador de "todas", §2.1/§7):** Johan pidió sacarlo. Esto
   es un **ajuste menor respecto al texto literal de SPEC-017.md** (cuyo ASUMIDO final decía
   "palabras clave: todas/todos/todo" — Johan lo había aprobado así originalmente, y ahora lo acota
   explícitamente a solo "todas"/"todos" al ver el riesgo de falso positivo documentado en §7).
   Motivo dado: "todo" es la palabra de mayor riesgo de falso positivo del set (aparece en frases
   sin relación a tareas, ej. "todo bien", "eso es todo"), y las otras dos palabras ("todas"/"todos")
   ya cubren los 3 ejemplos literales de la SPEC sin necesitarla. Aplicado en §2.1 y §7 abajo
   (mismo criterio de documentar "ajustes menores respecto a la propuesta, con motivo" que usó
   `orion-dev` en REQ-015/REQ-016).

---

## 0. Hallazgo adicional (verificado contra código real, no cubierto por SPEC ni baseline)

Antes de diseñar, verifiqué con ejecución real (no asumida) el comportamiento actual para los
ejemplos de la fila "sin cambios" de la tabla de SPEC-017.md que **baseline no probó** (baseline
solo ejecutó los 8 textos de la tabla de "todas"/"0 pendientes"; no probó "completa la tarea #3" ni
"completa mi tarea", que son los ejemplos de las filas "ID explícito" y "1 sola pendiente"):

```python
_is_task_complete_phrase("completa la tarea #3")   # -> False
_is_task_complete_phrase("completa mi tarea")       # -> False
```

**Ninguno de los dos matchea ningún trigger hoy** (`create=False`, `list=False`,
`complete_phrase=False` para ambos) — `_try_task_tool()` devuelve `None` y ambos caen a
`capability`/`intent`/`claude`, exactamente igual que el caso ya documentado por baseline para
"todas". La causa: `mentions_done` en `_is_task_complete_phrase()` solo reconoce el participio
(`"completad"`/`"terminad"`), no el imperativo/presente (`"completa"`, `"termina"`). La SPEC
describe estas dos filas como comportamiento actual = "completa solo la tarea #3" / "auto-completa
la única pendiente" — **esto no es exacto**, igual que ya pasó con la fila de "todas" que corrigió
baseline. No cambia los criterios de aceptación (redactados en términos de comportamiento deseado),
pero cambia qué texto de prueba hay que usar para CA-03/CA-05 (ver sección 5) y aclara el alcance
real de lo que hay que tocar (ver sección 2.3, "Por qué amplío la detección de ID explícito").

Verifiqué también, por ser condición necesaria para CA-05/CA-06 (ID gana sobre "todas"), que el
regex que hoy usa `_task_complete_invoke()` (`(?:tarea|numero|número|id)\s*#?(\d+)`) **no matchea**
el propio ejemplo de casos borde de la SPEC (`"de todas mis tareas, la #3 ya la hice"`), porque el
`#3` no está precedido inmediatamente por `tarea`/`numero`/`id`:

```python
re.search(r"(?:tarea|numero|número|id)\s*#?(\d+)", "de todas mis tareas, la #3 ya la hice")
# -> None
```

Esto obliga a ampliar ese regex (ver 2.2) — sin ampliarlo, CA-06 sería literalmente imposible de
cumplir con el propio ejemplo que la SPEC usa para especificarlo.

---

## 1. Cobertura de criterios de la SPEC

SPEC-017.md tiene **12 checkboxes** en "Criterios de aceptación" (el handoff decía 11; recuento
directo del archivo da 12 — no bloquea nada, lo señalo para que quede registrado). Los numero CA-01
a CA-12 en el orden en que aparecen.

| CA | Criterio (resumen) | Cómo lo satisface esta propuesta |
|----|---------------------|-----------------------------------|
| CA-01 | 2+ pendientes, texto "completar todas" → completa todas, sin aclaración ni solo-listado | `_is_bulk_complete_phrase()` nuevo en `core/resolution.py`, evaluado **antes** de `_TASK_LIST_TRIGGERS` (§2.1) → tool nuevo `task_complete_all` (§2.2) que completa todas las pendientes vía `list_tasks()`+`complete_task()` en bucle |
| CA-02 | Mensaje confirma cuántas se completaron, con títulos/IDs, no genérico "listo" | `_task_complete_all_invoke()` arma el mensaje enumerando `#id - título` de cada tarea completada (§2.2) |
| CA-03 | 1 pendiente, sin ID → sin cambios | Rama existente de `_task_complete_invoke()` (auto-completar única pendiente) **no se toca**; el texto de prueba debe ser uno que YA matchea `_is_task_complete_phrase()` hoy (ej. `"ya completé mi tarea"`), no `"completa mi tarea"` (ver §0 y §5) |
| CA-04 | 0 pendientes → sin cambios | Rama existente de `_task_complete_invoke()` (mensaje fijo) **no se toca**; además el tool nuevo `task_complete_all` maneja su propio caso de 0 pendientes con el mismo mensaje, por robustez (no es un CA literal pero evita que el tool nuevo rompa con 0 tareas) |
| CA-05 | ID explícito → sin cambios, completa solo esa, incluso con "todas" en otro sentido | El chequeo de ID explícito (§2.1, `has_explicit_task_id()`) se evalúa **antes** de decidir entre "todas" y "listar" — si hay ID, gana siempre, exactamente igual sin importar si "todas" está presente |
| CA-06 | Mismo texto → mismo resultado en Desktop/Telegram/Discord | Ningún cambio depende de `channel` ni de `claude_fn`; los 3 canales llaman a `resolve()` → mismo `RESOLVERS` → mismo `_try_task_tool()` (confirmado por baseline/spec, sin tocar `gateway.py` ni los bots) — ver pruebas §5 (un test por canal) |
| CA-07 | Cada tarea completada pasa por `execute_tool()` (gate real) | `task_complete_all` es un `ToolSpec` registrado normal; su `invoke` (`_task_complete_all_invoke`) es la ÚNICA función que llama a `task_manager.complete_task()` en bucle, y solo se ejecuta después de que `execute_tool()` ya corrió `security_manager.require_confirmation("task_complete_all", ...)` — mismo patrón que ya usa hoy `_task_complete_invoke()` para el caso "auto-completar única pendiente" (llama `task_manager.complete_task()` directo desde adentro de un invoke ya gateado). No se agrega ningún camino que llame a `task_manager.complete_task()` sin pasar por `execute_tool()` primero (ver §6, justificación explícita) |
| CA-08 | Sin confirmación adicional (GREEN se mantiene) | `task_complete_all` se registra con `risk_level=RiskLevel.GREEN`, igual que `task_complete`/`task_list`/`task_create`; `core/security_manager.py` no se toca |
| CA-09 | `delete_task`/🟡/🔴 sin cambios, test de regresión | No se toca `core/security_manager.py` ni se registra ningún `ToolSpec` de `delete_task`; test de regresión explícito (§5) verifica que `delete_task` (YELLOW, ya clasificado en `security_manager.py:316`) sigue bloqueado sin confirmación |
| CA-10 | `/completar [id]` de Telegram sin cambios | `channels/telegram_bot.py` no se toca (confirmado en "Archivos a modificar", §3) |
| CA-11 | `reasoning_loop`/`RESOLVERS` sin cambios de comportamiento | `core/reasoning_loop.py` no se toca; `RESOLVERS` (lista y orden) no se toca — solo se modifica el CUERPO de `_try_task_tool()`, que ya es uno de los resolvers existentes |
| CA-12 | Suite pytest completa sigue pasando sin nuevos fallos | Cambios acotados a 2 archivos, sin tocar firmas de `tasks/task_manager.py`; pruebas nuevas no dependen de red/mic (§5) |

---

## 2. Diseño detallado

### 2.1 `core/resolution.py` — punto de intercepción de "todas" (el hallazgo crítico de baseline)

El hallazgo de baseline es correcto y es la restricción de diseño más importante: el chequeo de
"todas" debe evaluarse **antes** de `_TASK_LIST_TRIGGERS`, no solo antes de
`_is_task_complete_phrase()`. Mi diseño va un paso más allá: también evalúa la prioridad de "ID
explícito" en el mismo punto, porque —como muestra §0— el regex de ID explícito necesita
intervenir exactamente donde hoy colisiona con `list`, y aislarlo ahí (en vez de tocar
`_is_task_complete_phrase()`) es lo que mantiene el resto de la cadena intacta.

**Nuevas constantes y funciones** (agregadas después de `_TASK_COMPLETE_TRIGGERS`, antes de
`_is_task_complete_phrase()`):

```python
import re  # nuevo import a nivel de módulo (no existía)

# CA-01/CA-02: palabras clave de alcance "todas" — amplias pero determinísticas, sin LLM.
# AJUSTE respecto al ASUMIDO original de SPEC-017.md (que decía "todas/todos/todo"): Johan pidió
# sacar "todo" (singular) del set — es la palabra de mayor riesgo de falso positivo (aparece en
# frases sin relación a tareas, ej. "todo bien", "eso es todo"), y los 3 ejemplos literales de la
# SPEC ("completa todas...", "ya completé todas...", "termina todas mis tareas") ya matchean con
# "todas" solo. Ver arquitectura-017.md, "Ajustes de Johan", punto 2.
_TASK_BULK_ALL_RE = re.compile(r"\b(?:todas|todos)\b")

# Verbos de "completar" en cualquier conjugación común (imperativo/presente/pretérito/participio):
# completa/completé/completo/completando/completado -> "complet"; termina/terminé/terminado ->
# "termin"; marca/marcar/marqué -> "marc". Mismo criterio que sugiere SPEC-017.md en "Casos
# borde" ("la presencia de un verbo de completar — 'completa', 'termina', 'marca', 'ya
# completé' — antes de evaluar el trigger de listado puro").
_TASK_BULK_COMPLETE_VERB_STEMS = ("complet", "termin", "marc")


def _is_bulk_complete_phrase(text_lower: str) -> bool:
    """Detecta intención de completar TODAS las tareas pendientes (CA-01, CA-02).

    Requiere un verbo de completar Y la palabra todas/todos — cualquiera de las dos condiciones
    sola es demasiado ambigua (un verbo de completar solo no implica lote; "todas"/"todos" solas
    pueden aparecer en frases sin relación con tareas). Debe evaluarse antes de
    `_TASK_LIST_TRIGGERS` en `_try_task_tool()` (hallazgo de orion-baseline: la mayoría de las
    frases reales de "completar todas" contienen substrings de `_TASK_LIST_TRIGGERS` como
    "tareas pendientes"/"mis tareas" y hoy se resuelven como listado antes de llegar a evaluar
    completar).
    """
    if not _TASK_BULK_ALL_RE.search(text_lower):
        return False
    return any(stem in text_lower for stem in _TASK_BULK_COMPLETE_VERB_STEMS)
```

**Modificación de `_try_task_tool()`** — se inserta un bloque nuevo entre el chequeo de `create` y
el de `list` (create conserva su prioridad, sin cambios):

```python
def _try_task_tool(text: str, channel: "ChannelType", user_id: str) -> Optional[ResolutionResult]:
    from agents.tool_registry import execute_tool, has_explicit_task_id

    text_lower = text.lower().strip()
    try:
        if any(t in text_lower for t in _TASK_CREATE_TRIGGERS):
            result = execute_tool(
                "task_create", {"text": text, "user_id": user_id, "channel": channel.value},
                channel, user_id,
            )
            return ResolutionResult(text=result, matched_by="task_tool", channel=channel)

        # NUEVO (CA-01, CA-02, CA-05, CA-06 desambiguación) — evaluado ANTES de
        # _TASK_LIST_TRIGGERS, hallazgo crítico de orion-baseline.
        bulk_all = _is_bulk_complete_phrase(text_lower)
        list_trigger = any(t in text_lower for t in _TASK_LIST_TRIGGERS)

        if bulk_all or list_trigger:
            # CA-05/CA-06: un ID explícito en el texto gana siempre sobre "todas" y sobre
            # "listar" — se resuelve como completar UNA tarea (comportamiento existente de
            # _task_complete_invoke, sin cambios en su rama de ID explícito).
            if has_explicit_task_id(text):
                result = execute_tool(
                    "task_complete", {"text": text, "user_id": user_id}, channel, user_id,
                )
                return ResolutionResult(text=result, matched_by="task_tool", channel=channel)

            if bulk_all:
                result = execute_tool(
                    "task_complete_all", {"text": text, "user_id": user_id}, channel, user_id,
                )
                return ResolutionResult(text=result, matched_by="task_tool", channel=channel)

            # Solo list_trigger, sin "todas" y sin ID explícito -> comportamiento sin cambios.
            result = execute_tool("task_list", {"user_id": user_id}, channel, user_id)
            return ResolutionResult(text=result, matched_by="task_tool", channel=channel)

        if _is_task_complete_phrase(text_lower):
            result = execute_tool(
                "task_complete", {"text": text, "user_id": user_id}, channel, user_id,
            )
            return ResolutionResult(text=result, matched_by="task_tool", channel=channel)
    except ActionDenied as e:
        return ResolutionResult(
            text=_denied_message(e), matched_by="task_tool", channel=channel, denied=True,
        )

    return None
```

**Por qué el chequeo de ID explícito está condicionado a `bulk_all or list_trigger`, y no es un
chequeo independiente de más arriba:** decidí NO convertir "hay un ID explícito en el texto" en un
gate de nivel superior que dispare para cualquier texto (ej. "completa la tarea #3" sola, sin
"todas" ni colisión con `list`). Si lo hiciera, textos con un `#N` suelto en cualquier contexto no
relacionado a tareas (ej. referencias a un ranking, una edición de revista) empezarían a
interceptarse por `_try_task_tool()` antes de llegar a `capability`/`intent`/`claude` — un cambio de
comportamiento nuevo, no pedido, con superficie de riesgo mayor a lo que amerita este REQ. Al
condicionarlo a que YA exista una señal de "todas" o "listar", el chequeo de ID solo actúa como
**desempate** exactamente en los casos que la SPEC pide desambiguar (CA-05, CA-06) — y para el caso
"ID explícito solo, sin todas ni listado" (ej. `"completa la tarea #3"`), el comportamiento queda
literalmente sin cambios (ver §0: hoy tampoco llega a `task_complete`, y seguirá sin llegar). Esto
es una decisión de diseño explícita que dejo para que Johan la vea: prioricé no ampliar la
superficie de intercepción más allá de lo necesario para cumplir la SPEC, aceptando que el ejemplo
literal de la fila "ID explícito" de la tabla de SPEC-017.md no queda arreglado por este REQ (ya
estaba así, ver §0) — si Johan prefiere que SÍ se arregle en general (no solo en colisión con
"todas"), lo marco como ampliación de alcance a decidir explícitamente, no lo asumo.

### 2.2 `agents/tool_registry.py` — tool nuevo `task_complete_all` + regex de ID ampliado

**Regex de ID explícito ampliado** (mueve `import re` a nivel de módulo, ya no local a la función;
agrega la alternativa de `#N` suelto, necesaria para CA-06 — ver §0):

```python
import re  # se mueve de dentro de _task_complete_invoke() a nivel de módulo

# Reconoce "tarea 3"/"tarea #3"/"numero 3"/"id 3" (comportamiento existente, grupo 1) y también
# un "#3" suelto sin palabra clave delante (grupo 2) — necesario para que la desambiguación
# ID-vs-todas (CA-05, CA-06) funcione con frases como "de todas mis tareas, la #3 ya la hice",
# donde el número no está precedido por tarea/numero/id.
_TASK_ID_RE = re.compile(r"(?:tarea|numero|número|id)\s*#?(\d+)|#(\d+)")


def has_explicit_task_id(text: str) -> bool:
    """Detecta si el texto menciona un ID de tarea explícito (mismo criterio que usa
    _task_complete_invoke() para extraerlo). Expuesta para que core/resolution.py decida
    prioridad "ID explícito gana sobre todas/listar" (SPEC-017 CA-05, CA-06) sin duplicar el
    regex en dos módulos."""
    return bool(_TASK_ID_RE.search(text.lower()))
```

**`_task_complete_invoke()` — solo cambia la línea de extracción del ID** (el resto de la función,
íntegro, sin cambios):

```python
def _task_complete_invoke(params: dict) -> str:
    from tasks.task_manager import task_manager

    text = params.get("text", "")
    user_id = params["user_id"]
    text_lower = text.lower()

    match = _TASK_ID_RE.search(text_lower)
    task_id = int(match.group(1) or match.group(2)) if match else None

    # ... resto de la función sin cambios (líneas 124-149 actuales, intactas)
```

**Tool nuevo — `_task_complete_all_invoke()` + `ToolSpec`:**

```python
_TASK_COMPLETE_ALL_LIMIT = 20  # alineado con el default de list_tasks() (SPEC-017.md, "Casos borde")


def _task_complete_all_invoke(params: dict) -> str:
    """Completa todas las tareas pendientes del usuario en una sola invocación (CA-01, CA-02).

    Cada llamada a task_manager.complete_task() ocurre DENTRO de este invoke, que solo se
    ejecuta después de que execute_tool() ya corrió security_manager.require_confirmation()
    para la acción 'task_complete_all' — mismo patrón que ya usa _task_complete_invoke() para
    su rama de auto-completar la única tarea pendiente (CA-07, ver arquitectura-017.md §6).
    """
    from tasks.task_manager import task_manager

    user_id = params["user_id"]
    pending_tasks = task_manager.list_tasks(user_id, status="pending", limit=_TASK_COMPLETE_ALL_LIMIT)

    if not pending_tasks:
        return "No tiene ninguna tarea pendiente en este momento, Señor."

    completed = [t for t in pending_tasks if task_manager.complete_task(t["id"], user_id)]

    if not completed:
        return "No pude completar ninguna tarea, Señor. Intente nuevamente."

    n = len(completed)
    lines = "\n".join(f"• #{t['id']} - {t['title']}" for t in completed)
    header = f"☑️ *¡Trabajo terminado!* Completé {n} tarea{'s' if n != 1 else ''}, Señor:\n"

    footer = ""
    if len(pending_tasks) >= _TASK_COMPLETE_ALL_LIMIT:
        footer = (
            f"\n\n(Procesé el máximo de {_TASK_COMPLETE_ALL_LIMIT} tareas por vez. Si tiene "
            f"más pendientes, puede pedírmelo de nuevo.)"
        )
    return header + lines + footer


register_tool(ToolSpec(
    name="task_complete_all",
    description="Completa todas las tareas pendientes del usuario en un solo lote.",
    parameters_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}, "user_id": {"type": "string"}},
        "required": ["user_id"],
    },
    # GREEN: misma clasificación que task_complete — SPEC-017.md es NO NEGOCIABLE en que
    # completar (individual o en lote) sigue sin pedir confirmación (decisión de UX de Johan).
    risk_level=RiskLevel.GREEN,
    invoke=_task_complete_all_invoke,
))
```

**Por qué un `ToolSpec` nuevo (`task_complete_all`) y no extender `_task_complete_invoke()`
in-place:** la SPEC deja ambas opciones abiertas. Elijo el tool nuevo porque (a) mantiene
`_task_complete_invoke()` con una sola responsabilidad (una tarea, por ID o por deducción) sin
condicionales adicionales; (b) el nombre de acción distinto (`task_complete_all` vs `task_complete`)
queda registrado por separado en `security_manager` y en los logs — más trazable si en el futuro se
quisiera reclasificar el riesgo de completar en lote de forma independiente a completar una sola
tarea, sin tener que craftear ese caso dentro de un `if`/`else` de la función existente; (c) evita
tocar una función que ya tiene cobertura de comportamiento acordado ("sin cambios" en 3 de los 12
CA) — menor superficie de riesgo de regresión accidental.

### 2.3 Flujo de datos

```
texto usuario (Desktop/Telegram/Discord/Voice)
  -> resolve(text, channel, user_id)                         [core/resolution.py]
    -> RESOLVERS: routine -> autopilot -> learned -> task_tool -> ...   [sin cambios de orden]
      -> _try_task_tool(text, channel, user_id)
        1. _TASK_CREATE_TRIGGERS?           -> task_create                 [sin cambios]
        2. bulk_all = _is_bulk_complete_phrase(text)   [NUEVO]
           list_trigger = _TASK_LIST_TRIGGERS match     [sin cambios, solo se reubica]
           si bulk_all OR list_trigger:
             a. has_explicit_task_id(text)?  [NUEVO, agents/tool_registry.py]
                -> task_complete (ID gana, completa 1 sola)             [CA-05, CA-06]
             b. elif bulk_all:
                -> task_complete_all (NUEVO tool)                        [CA-01, CA-02]
             c. else (solo list_trigger):
                -> task_list                                             [sin cambios]
        3. _is_task_complete_phrase(text)?  -> task_complete             [sin cambios]
        4. ninguno matchea -> None -> sigue a capability/intent/claude   [sin cambios]
      -> execute_tool(tool_name, params, channel, user_id)     [agents/tool_registry.py]
        -> security_manager.require_confirmation(tool_name, channel, ...)  [gate, sin cambios]
        -> spec.invoke(params)
           - _task_complete_all_invoke: list_tasks(status="pending", limit=20)
                                         -> complete_task() en bucle
                                         -> mensaje con #id-título de cada una
```

### 2.4 Tope de tareas por invocación de lote

`_TASK_COMPLETE_ALL_LIMIT = 20`, alineado con el `limit=20` por defecto de
`task_manager.list_tasks()` (sugerencia de SPEC-017.md, adoptada tal cual). Si hay 20 o más
pendientes: se completan las primeras 20 (orden `ORDER BY due_date ASC`, mismo criterio que ya usa
`list_tasks()`) y se agrega una nota indicando que puede haber más — **sin pedir confirmación**,
consistente con la decisión de UX de Johan (completar y avisar después, no preguntar antes). No se
implementa paginación ni segunda pasada automática; si el usuario tiene más de 20 pendientes, debe
repetir el pedido.

---

## 3. Archivos a modificar/crear

- `core/resolution.py` — agrega `import re`, `_TASK_BULK_ALL_RE`, `_TASK_BULK_COMPLETE_VERB_STEMS`,
  `_is_bulk_complete_phrase()`; modifica el cuerpo de `_try_task_tool()` (inserta el bloque de
  desambiguación entre `create` y `list`). `_TASK_CREATE_TRIGGERS`, `_TASK_LIST_TRIGGERS`,
  `_TASK_COMPLETE_TRIGGERS`, `_is_task_complete_phrase()` **no se tocan**.
- `agents/tool_registry.py` — mueve `import re` a nivel de módulo; agrega `_TASK_ID_RE`,
  `has_explicit_task_id()`, `_TASK_COMPLETE_ALL_LIMIT`, `_task_complete_all_invoke()`, y el
  `register_tool(ToolSpec(name="task_complete_all", ...))`; modifica una sola línea de
  `_task_complete_invoke()` (la extracción del `match`/`task_id`) — el resto de esa función queda
  intacto.
- **Sin cambios** (confirmado por baseline, no se toca en esta propuesta): `tasks/task_manager.py`,
  `core/reasoning_loop.py`, `agents/skill_tools.py`, `channels/gateway.py`,
  `channels/telegram_bot.py`, `channels/discord_bot.py`, `core/security_manager.py`,
  `intent/intentions.py`, `RESOLVERS` (lista y orden en `core/resolution.py`).
- `tests/test_resolution.py` — se extiende (no se reemplaza) con tests nuevos.
- `tests/test_tool_registry.py` — se extiende (no se reemplaza) con tests nuevos.

## 4. Dependencias nuevas

Ninguna. Todo el diseño usa `re` (ya en la stdlib, ya importado en `agents/tool_registry.py` aunque
local a una función) y las funciones ya existentes de `tasks/task_manager.py`
(`list_tasks`/`complete_task`), sin cambios de firma.

---

## 5. Pruebas sugeridas

No existe `tests/test_task_manager.py` y no lo creo en esta propuesta: `tasks/task_manager.py` no
cambia de firma ni de comportamiento en este REQ (confirmado por baseline), así que crear ese
archivo sería cobertura de deuda técnica preexistente, no de este REQ — lo señalo como oportunidad
aparte, no lo asumo como parte del alcance. La cobertura de los 12 CA se concentra en
`tests/test_resolution.py` (comportamiento de `_try_task_tool()`/`resolve()` end-to-end) y
`tests/test_tool_registry.py` (comportamiento del tool nuevo y del regex ampliado), monkeypacheando
`tasks.task_manager.task_manager` en vez de tocar `tasks/tasks.db` real — mismo patrón que ya usa
`tests/test_webview_bridge.py` (`monkeypatch.setattr(task_manager, "list_all_tasks", ...)`).

**`tests/test_resolution.py` (nuevos):**

| Test | CA | Qué verifica |
|------|----|----|
| `test_bulk_complete_prioriza_sobre_list_trigger` | CA-01 | `"completa todas las tareas pendientes"` con 2+ pendientes (mockeadas) resuelve `matched_by="task_tool"` vía `execute_tool("task_complete_all", ...)`, NO vía `task_list` — spy sobre `execute_tool` |
| `test_bulk_complete_variantes_sin_palabra_tarea` | CA-01 | `"ya completé todas las pendientes"` y `"marca todas como completadas"` (sin la palabra "tarea") también disparan `task_complete_all` — cubre el gap que señaló baseline |
| `test_mensaje_bulk_lista_ids_y_titulos` | CA-02 | El texto de respuesta contiene cada `#id - título` de las tareas completadas, no un genérico "listo" |
| `test_un_pendiente_sin_id_sin_cambios` | CA-03 | Con texto que YA matchea `_is_task_complete_phrase()` hoy (ej. `"ya completé mi tarea"`, no `"completa mi tarea"` — ver §0) y 1 sola pendiente: resuelve vía `task_complete` (no `task_complete_all`), mismo mensaje que antes de este REQ |
| `test_cero_pendientes_sin_cambios` | CA-04 | Texto que matchea `_TASK_LIST_TRIGGERS` con 0 pendientes: mensaje sin cambios (reutiliza el hallazgo de baseline sobre el mensaje real de `get_task_summary`) |
| `test_id_explicito_gana_sobre_todas` | CA-05, CA-06 | `"de todas mis tareas, la #3 ya la hice"` y `"de todas mis tareas, completa la #3"` (ejemplos literales de SPEC-017.md) resuelven `task_complete` con `task_id=3`, NO `task_complete_all` ni `task_list` — spy sobre `execute_tool` verificando `name="task_complete"` y el texto pasado |
| `test_mismo_texto_bulk_en_3_canales` | CA-06 | `"completa todas las tareas pendientes"` vía `resolve()` con DESKTOP (`user_id="default"`), TELEGRAM (`user_id="123"`) y DISCORD (`user_id="discord_456"`), cada uno con sus propias pendientes mockeadas — mismo `matched_by`, cada canal completa SOLO las suyas (partición por `user_id`, documentada como preexistente) |
| `test_bulk_no_intercepta_create` | regresión | `"recuérdame completar todas mis tareas mañana"` sigue resolviendo `task_create` (create mantiene prioridad, sin cambios) |

**`tests/test_tool_registry.py` (nuevos):**

| Test | CA | Qué verifica |
|------|----|----|
| `test_task_complete_all_completa_todas_las_pendientes` | CA-01, CA-02 | `execute_tool("task_complete_all", {"user_id": "u"}, ChannelType.DESKTOP, "u")` con `list_tasks`/`complete_task` mockeados: completa cada una devuelta, mensaje enumera `#id-título` |
| `test_task_complete_all_cero_pendientes` | robustez (no CA literal) | `list_tasks` mockeado devolviendo `[]` -> mensaje "No tiene ninguna tarea pendiente..." sin llamar `complete_task` |
| `test_task_complete_all_respeta_limite_20` | Casos borde SPEC | `list_tasks` mockeado con `limit=20` pasado explícitamente; con 20 resultados, el mensaje incluye la nota de "puede haber más" |
| `test_task_complete_all_es_green_sin_confirmar` | CA-08 | Igual que `test_execute_tool_green_ejecuta_sin_confirmar` existente: `monkeypatch` de `input` que falla si se llama; `execute_tool("task_complete_all", ...)` no lo dispara |
| `test_task_complete_all_pasa_por_gate` | CA-07 | Spy/mock sobre `security_manager.require_confirmation` confirma que se llama con `"task_complete_all"` ANTES de que se invoque cualquier `task_manager.complete_task` (mockeado con spy propio) |
| `test_delete_task_yellow_sigue_bloqueado_en_lote` | CA-09 | Regresión: `security_manager.require_confirmation("delete_task", ChannelType.TELEGRAM, ...)` (sin adaptador) deniega, igual que antes de REQ-017 — no depende de código nuevo, documenta que nada de esta propuesta afecta la clasificación YELLOW existente |
| `test_has_explicit_task_id_variantes` | CA-05, CA-06 | `has_explicit_task_id()` devuelve `True` para `"tarea #3"`, `"numero 3"`, `"#3"` sueltos; `False` para texto sin ningún ID |
| `test_task_complete_invoke_id_suelto_con_hash` | CA-06 | `_task_complete_invoke({"text": "la #3 ya la hice", "user_id": "u"})` con `complete_task` mockeado: extrae `task_id=3` correctamente (regresión del regex ampliado) |
| `test_task_complete_invoke_regex_existente_sin_cambios` | CA-05, regresión | `"completa la tarea numero 3"` sigue extrayendo `task_id=3` (rama del regex que ya existía, grupo 1) |

**Regresión obligatoria (CA-11, CA-12):** correr `tests/test_resolution.py`,
`tests/test_reasoning_loop.py` y la suite completa (`pytest tests/ --tb=short -q`) sin nuevos
fallos más allá de los 2 preexistentes de `test_llm_provider.py` (`ModuleNotFoundError: anthropic`,
documentados por baseline, no relacionados).

---

## 6. Justificación de CA-07 (gate real) en detalle

CA-07 exige: *"Cada tarea completada en el lote sigue pasando por
`agents/tool_registry.py::execute_tool()`... no se agrega ningún camino que llame
`task_manager.complete_task()` sin pasar por ese punto."*

Interpretación: el objetivo es que **ninguna** llamada a `task_manager.complete_task()` ocurra sin
que `security_manager.require_confirmation()` se haya evaluado antes para la acción que la origina
— evitar un bypass como el ya documentado (fuera de alcance) en `/eliminar` de Telegram. Mi diseño
cumple esto con **una** llamada a `execute_tool("task_complete_all", ...)` por invocación de lote
(no N llamadas, una por tarea): `_task_complete_all_invoke()` —que es quien itera y llama
`task_manager.complete_task()` N veces— solo se ejecuta si `execute_tool()` ya pasó el gate. Esto es
exactamente el mismo patrón que ya usa hoy `_task_complete_invoke()` en su rama de auto-completar la
única tarea pendiente (llama `task_manager.complete_task()` directo, adentro de un invoke ya
gateado, sin una segunda llamada a `execute_tool()` por tarea). No hay diferencia de riesgo entre
gatear una vez por lote o N veces por tarea individual, porque `task_complete`/`task_complete_all`
no tienen variación de riesgo por tarea específica (a diferencia de, por ejemplo, "cerrar una
aplicación", donde la app importa). La SPEC ya ofrece este diseño como opción explícitamente viable
("`orion-architect` decide si esto vive dentro de `_task_complete_invoke()` o en un `ToolSpec` nuevo
(ej. `task_complete_all`)").

---

## 7. Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| `_is_bulk_complete_phrase()` requiere verbo + "todas/todos" — combinada casualmente con un verbo "complet"/"termin"/"marc" en la misma oración sin relación a tareas | Riesgo bajo en la práctica (requiere AMBAS condiciones a la vez) y consistente con el patrón ya existente en el módulo (todos los triggers de `_TASK_*` son substrings baratos, sin NLU, con el mismo tipo de riesgo aceptado desde REQ-006). Johan ya redujo este riesgo un escalón más al sacar "todo" (singular) del set — la palabra de mayor riesgo de falso positivo (ver "Ajustes de Johan", punto 2) — quedando solo "todas"/"todos", que en la práctica solo aparecen en contexto de enumeración/plural. SPEC-017.md anticipa el resto del trade-off en su ASUMIDO final ("si en QA se encuentra una redacción común que no dispara ninguna variante cubierta, se ajustan los triggers, no se agrega dependencia de LLM") |
| Ampliar `_TASK_ID_RE` para aceptar `#N` suelto (sin `tarea`/`numero`/`id` delante) podría, en textos que YA matchean `_is_task_complete_phrase()` por otra razón (ej. "ya completé la tarea, ref #45 del proyecto"), cambiar de "auto-deducir entre pendientes" a "completar específicamente #45" | Cambio de comportamiento aceptado y de bajo impacto: en la práctica reduce ambigüedad (respeta una referencia explícita que el usuario escribió) en vez de introducirla; further, solo aplica dentro de textos que YA disparaban completar una tarea |
| El chequeo de ID explícito solo actúa como desempate condicionado a `bulk_all or list_trigger` (§2.1) — decisión deliberada de no ampliarlo a un gate independiente de nivel superior | Documentado explícitamente como decisión de diseño en §2.1, con la consecuencia declarada (el ejemplo "completa la tarea #3" sin colisión con "todas"/"listar" queda sin cambios, ver §0) — pendiente de que Johan confirme si ese alcance más chico es aceptable o si prefiere ampliarlo |
| `_TASK_COMPLETE_ALL_LIMIT=20` es un valor fijo en código, no configurable | Igual a como ya funciona `list_tasks(limit=20)` por defecto — consistencia con el resto del sistema; si Johan quiere que sea configurable, es una extensión menor a futuro, no bloqueante |
| Canal VOICE hereda el comportamiento nuevo como efecto colateral (ya documentado por SPEC como esperado, no objetivo de este REQ) | `CHANNEL_ALLOWED_LEVELS[VOICE]` ya permite GREEN — sin cambio de riesgo real, `task_complete_all` es GREEN igual que `task_complete` |
| Partición preexistente por `user_id`/canal (Telegram/Discord/Desktop no comparten tareas) sigue aplicando también a "completar todas" | Ya documentada como limitación conocida en SPEC-017.md y en el contexto — no se introduce ni se resuelve en este REQ, mismo comportamiento que `task_list` hoy |

---

## 8. ¿Corresponde `orion-security`?

**No.** Mismo criterio que usé en REQ-016 §11, aplicado a un caso todavía más mecánico: este REQ no
toca `core/security_manager.py`, no registra ninguna acción nueva en un nivel distinto de GREEN, no
introduce ningún camino de ejecución que evite `execute_tool()`/`require_confirmation()` (al
contrario: la única llamada nueva a `task_manager.complete_task()` en bucle vive estrictamente
detrás del mismo gate ya auditado en REQ-005/REQ-006, ver §6), no maneja secretos, no ejecuta
`os.system()`/`subprocess`, y no clasifica ni reclasifica riesgo de ninguna acción. El único
"riesgo" real de este REQ es de precisión de matching léxico (falsos positivos/negativos de
detección de intención), no de seguridad — cubierto en §7 con mitigación y transparencia hacia
Johan, no con una auditoría de `orion-security`.

---

## 9. Rama de trabajo

Confirmar con Johan: la rama activa del repo (`feature/REQ-015-webview-ui`) pertenece a otro REQ en
curso. Propongo `feature/REQ-017-completar-tareas-lote` como rama nueva para este REQ — **no la creo
sin que Johan lo confirme** (regla de `git.md`: nunca crear una rama sin preguntar antes).

---

## 10. Preguntas resueltas por Johan (2026-08-20)

1. **"Completa la tarea #3"/"completa mi tarea" (§0) queda sin cambios en este REQ** — Johan
   confirmó explícitamente que NO se arregla acá. Se registra formalmente como hallazgo
   **descartado del alcance de REQ-017, pendiente de un REQ futuro** (no se abre desde este flujo;
   ver `REQ-017-context.md`, sección "Descartado"). Ningún CA ni ninguna línea de código de esta
   propuesta cambia por esto — sigue siendo, después de este REQ, exactamente el mismo
   comportamiento que tiene hoy (cae a `capability`/`intent`/`claude`, no completa la tarea vía
   `task_tool`).
2. **"Todo" (singular) se saca del set de palabras clave de "todas"** — aplicado en §2.1 y §7.
   Documentado como ajuste menor respecto al ASUMIDO original de SPEC-017.md, con motivo, en
   "Ajustes de Johan" al inicio de este documento.

Con esto, `arquitectura-017.md` queda **APROBADA**. Handoff emitido a `orion-dev`.
