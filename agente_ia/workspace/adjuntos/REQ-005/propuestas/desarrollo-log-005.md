# Desarrollo REQ-005

Deny-list central de acciones Rojo aplicada en código. Implementación literal de
`arquitectura-005.md`, incorporando las 3 condiciones obligatorias de
`security-audit-005.md`.

## Archivos modificados

- `agente_ia/core/security_manager.py` — núcleo de la decisión de seguridad:
  - `ChannelType.API`/`ChannelType.UNKNOWN` (nuevos), `CHANNEL_ALLOWED_LEVELS` extendido,
    `_CHANNEL_STR_MAP` para resolución de canal desde string.
  - `resolve_channel()` — nueva, única función de resolución de canal (None/desconocido → `UNKNOWN`, nunca `DESKTOP`).
  - `register_action()` — ahora retorna `bool`; bloquea degradar una acción RED.
  - `check_coverage()` — nueva, utilidad de diagnóstico de clasificación faltante.
  - `is_action_allowed()` — fail-closed (`None` → `False`).
  - `require_confirmation()` — fail-closed (`None` → bloquear + auditar
    `"bloqueada_no_clasificada"`), docstring con el invariante de seguridad de `channel`
    (condición b del security-audit), y `is_action_allowed()` movido a la rama YELLOW
    exclusivamente (ver "Decisiones de implementación").
  - `_register_default_actions()` — se quitan `web_search`/`play_media`/`screenshot`/`weather`
    (no correspondían a ningún intent real); se agregan las 6 categorías RED nuevas
    (`send_email_as_user`, `post_social_media`, `elevated_system_command`,
    `install_uninstall_software`, `modify_system_env_vars`, `grant_third_party_access`) y
    `proactive_trigger` (GREEN).
  - `_register_intent_actions()` — nueva; clasifica los 28 `Intent` reales del sistema
    (32 GREEN + 6 YELLOW) según el inventario de `baseline-005.md`.
  - `_register_action_registry_actions()` — nueva; clasifica las claves de
    `ACTION_REGISTRY` (17 GREEN, `write_file_direct`/`save_file_desktop` YELLOW).
- `agente_ia/router/dispatcher.py` — gate en `dispatch()` antes de la rama de handlers
  legacy; se quita el default duro `"desktop"` en `dispatch_as_tool()`.
- `agente_ia/skills/skill_manager.py` — gate en `execute()`; lambda inline de
  `get_agent_tools()` reemplazada por `_make_gated_tool_fn()` (nombrada y gateada).
- `agente_ia/core/base_agent.py` — `_DynamicAgentInstance.execute()` propaga
  `"channel": (context or {}).get("channel")` al dict que recibe `AgentTool.execute()`.
- `agente_ia/os_integration/system_ctrl.py` — se elimina `_resolve_channel()` local; se usa
  `security_manager.resolve_channel()`.
- `agente_ia/skills/code_execution_skill.py`, `agente_ia/skills/skill_creator_skill.py` — se
  quita el default `ChannelType.DESKTOP` al leer `params.get("channel")`.
- `agente_ia/agents/action_registry.py` — nueva `execute_action()`, único punto de ejecución
  gateado del registro.
- `agente_ia/agents/task_executor.py` — `execute()`/`execute_single()` aceptan `channel` y
  delegan en `execute_action()` en vez de invocar `fn` directo.
- `agente_ia/learning/routines_engine.py` — `execute_routine_actions()`/`try_routine()`
  aceptan `channel` y delegan en `agents.action_registry.execute_action()`.
- `agente_ia/os_integration/capabilities_router.py` — gate en `execute_capability()` usando
  `f"{modulo}.{funcion}"` como nombre de acción; `try_capability()` propaga `channel`.
- `agente_ia/core/proactive_engine.py` — `action_key` estable `"proactive_trigger"` (antes
  `f"proactive_{trigger.agent.name}"`, nunca pre-registrado).
- `agente_ia/main.py` — inyección incondicional de `channel="desktop"` en los 4 puntos que
  llaman `dispatch()`/`try_routine()`/`executor.execute()`/`try_capability()` sin canal.
- `agente_ia/.claude/rules/security-levels.md` — nota documental: RED aplicado en código desde REQ-005.
- `agente_ia/tests/test_security_manager.py` — nuevo, 37 tests reales (`test_*`), cubre las
  17 pruebas sugeridas por arquitectura-005.md más la prueba mandatoria del security-audit.

## Dependencias agregadas

Ninguna. Solo se usan `enum`, `sqlite3`, `logging`, `getpass` (ya en uso en el proyecto).

## Decisiones de implementación

1. **Bug encontrado y corregido durante la implementación (no estaba en la arquitectura
   aprobada, pero era necesario para que el PIN maestro de RED en DESKTOP funcionara como
   documenta el propio flujo de datos de `arquitectura-005.md`, líneas 341-352):**
   El primer borrador de `require_confirmation()` dejaba la verificación
   `is_action_allowed(action_name, channel)` **antes** de bifurcar entre YELLOW y RED. Como
   `CHANNEL_ALLOWED_LEVELS[ChannelType.DESKTOP] == [GREEN, YELLOW]` (RED nunca figura ahí a
   propósito, porque su única vía de excepción es el PIN maestro dentro de la rama RED), esa
   verificación bloqueaba **cualquier** acción RED —incluso en DESKTOP con PIN configurado y
   correcto— antes de llegar a evaluar el PIN. Esto habría vuelto inalcanzable la "única vía
   de excepción" que la SPEC y la arquitectura exigen explícitamente. Se corrigió moviendo el
   `is_action_allowed()` **dentro** de la rama `if level == RiskLevel.YELLOW`, dejando la
   rama RED con su lógica propia e independiente (`channel == DESKTOP and has_pin()`), tal
   como está documentado en el diagrama de flujo de la arquitectura. Detectado por el test
   `test_red_action_authorized_via_pin_desktop_only` (ítem 8 de las pruebas sugeridas), que
   falló contra el primer borrador y pasó tras la corrección.
2. **Doble gate potencial en 6 acciones YELLOW** — ⚠️ *riesgo confirmado empíricamente por
   `orion-tester` (criterio 11 = FAIL) y **corregido en la Iteración 2**; ver la sección
   "Iteración 2" al final de este documento. Se conserva el texto original como registro de
   por qué no se resolvió en la primera pasada:* `SYS_POWER_OFF`, `CLOSE_APP`,
   `EXECUTE_CODE`, `CREATE_SKILL`, `MODIFY_SKILL` y `DELETE_SKILL` tienen, además del gate
   nuevo en `SkillManager.execute()`/`dispatch()`, un gate propio preexistente dentro de la
   skill/función que las implementa (`system_ctrl.shutdown_pc()`, `system_ctrl.close_app()`,
   `CodeExecutionSkill.execute()`, `SkillCreatorSkill.execute()`), que ya llamaba
   `require_confirmation()` con el mismo nombre de acción antes de REQ-005. El diseño de "un
   solo gate por acción" de la arquitectura no cubre explícitamente este solape — asume que
   el gate se agrega solo a caminos sin protección propia, pero estas 6 acciones ya tenían la
   suya. Efecto observado: en un flujo real (no cubierto por los tests, que verifican
   `require_confirmation()` de forma aislada o con tools sintéticos) el usuario vería **dos**
   prompts de confirmación `input()` seguidos para una misma acción YELLOW en vez de uno. No
   se modificó ningún archivo para resolverlo porque implicaría remover uno de los dos gates
   —una decisión de diseño que no está en `arquitectura-005.md`— y el mandato explícito de
   `orion-dev` es implementar exactamente lo aprobado, sin rediseñar. Se señala aquí para que
   `orion-tester`/`orion-qa`/el humano decidan si amerita un ajuste antes de cerrar el REQ o
   un REQ de seguimiento.
3. Se preservó `is_action_allowed()` como función pública sin cambiar su firma (además del
   fix fail-closed `None → False`), porque tiene 2 llamadores externos documentados en la
   arquitectura (`channels/telegram_bot.py`, `core/proactive_engine.py`).
4. No se protegió la degradación YELLOW→GREEN en `register_action()` (solo RED está
   protegido) — coincide literalmente con el alcance de la SPEC; riesgo residual aceptado y
   documentado también en la arquitectura.
5. El bloque opcional-no-bloqueante de `main.py` (llamar `security_manager.check_coverage(...)`
   al arrancar y loggear huecos) no se implementó — la arquitectura lo marca explícitamente
   como "opcional recomendado, no bloqueante" y no forma parte del alcance obligatorio.

## Verificación local

```
cd agente_ia && python -m py_compile main.py core/security_manager.py router/dispatcher.py \
  skills/skill_manager.py core/base_agent.py os_integration/system_ctrl.py \
  skills/code_execution_skill.py skills/skill_creator_skill.py agents/action_registry.py \
  agents/task_executor.py learning/routines_engine.py os_integration/capabilities_router.py \
  core/proactive_engine.py tests/test_security_manager.py
→ OK, sin errores.

cd agente_ia && python -m pytest tests/ --tb=short -q
→ 42 passed, 1 warning in 2.27s
  (baseline-005.md: 5 passed → sin regresiones; +37 tests nuevos en test_security_manager.py,
   todos test_* reales y colectados por pytest)
```

---

# Iteración 2 — corrección del FAIL de orion-tester (criterio 11)

`test-results-005.md` devolvió **FAIL** con 12/13 criterios PASS. El único fallo es el
criterio 11 ("las acciones YELLOW existentes mantienen su comportamiento de confirmación sin
cambios de UX"): `dispatch()` invocaba `input()` **dos veces** para `SYS_POWER_OFF` y
`CLOSE_APP`, y por el mismo mecanismo estructural para `EXECUTE_CODE`, `CREATE_SKILL`,
`MODIFY_SKILL` y `DELETE_SKILL`. Es exactamente el riesgo #2 documentado arriba, ahora
confirmado empíricamente.

## Evidencia de grep — ¿existen callers directos?

La pregunta de seguridad previa a elegir el arreglo era: si se quita el gate interno, ¿queda
alguna función desprotegida ante un caller que la invoque sin pasar por
`dispatch()`/`skill_manager`? Resultado del rastreo sobre el código real:

| Símbolo | Callers encontrados | ¿Pasa por el gate central? |
|---|---|---|
| `system_ctrl.shutdown_pc` | `executor/handlers.py:78`, `skills/system_control_skill.py:57` | Sí — `dispatch()` y `SkillManager.execute()` respectivamente |
| `system_ctrl.close_app` | `executor/handlers.py:39` | Sí — `dispatch()` |
| `CodeExecutionSkill.execute` / `SkillCreatorSkill.execute` | `skills/skill_manager.py:71` y `:100` (únicos) | Sí — ambos ya gateados en Iteración 1 |
| Instanciación de esas skills fuera de `skill_manager` | ninguna | — |
| `channels/telegram_bot.py:624,647` | usa `is_action_allowed("shutdown"/"restart", ChannelType.TELEGRAM)` | No aplica: es un **pre-chequeo** de UI, no un gate de ejecución; no invoca `shutdown_pc` |

**Conclusión: cero callers directos.** Todo camino de ejecución real de las 6 acciones pasa
hoy por `dispatch()` o por `SkillManager.execute()`, ambos gateados.

## Opción elegida: A — eliminar el gate interno redundante

Según el criterio del propio coordinador ("si NO hay callers directos y el único camino real
es dispatch/skill_manager: quitar el gate interno es correcto y suficiente"). Razones
adicionales para preferirla sobre la opción B (idempotencia del gate):

- **No introduce estado.** La opción B exigía recordar "esta acción ya fue confirmada en esta
  cadena de invocación", y ese estado es precisamente el que puede "quedar pegado" y
  auto-aprobar en silencio una invocación posterior distinta. Al eliminar el gate duplicado,
  ese modo de fallo no se mitiga: deja de ser representable.
- **Mantiene el criterio 4 de la SPEC a máxima fuerza.** La resistencia a una skill que no se
  auto-regula sigue intacta para estas 6 acciones, porque el gate que se conserva es el
  **central** (el que la skill no controla), no el interno.
- **Coincide con el principio "un solo gate por acción"** ya presente en `arquitectura-005.md`;
  no reabre arquitectura.

## Cambios de la Iteración 2

- `agente_ia/os_integration/system_ctrl.py` — eliminados los gates internos de `shutdown_pc()`
  y `close_app()`; eliminado el import ya no usado de `security_manager`/`ChannelType`.
- `agente_ia/skills/code_execution_skill.py` — eliminado el gate interno de `execute()`
  (`require_confirmation("execute_code", ...)`) y su import.
- `agente_ia/skills/skill_creator_skill.py` — eliminados los 3 gates internos
  (`create_skill`/`modify_skill`/`delete_skill`), la variable `channel` y el import.
- `agente_ia/tests/test_security_manager.py` — nuevo test de regresión (ver abajo).

### Invariante documentado

Cada una de las 4 funciones/métodos afectados lleva ahora en su docstring, de forma explícita,
el invariante que las deja seguras:

> INVARIANTE DE SEGURIDAD (REQ-005): esta función NO se auto-protege. Asume estar gateada por
> el punto central (`security_manager.require_confirmation()`) … No invocarla directamente
> desde código nuevo sin pasar por ese camino: quedaría sin confirmación.

## Test de regresión nuevo

`test_yellow_action_prompts_exactly_once_via_dispatch` (parametrizado: `SYS_POWER_OFF` vía
`SkillManager.execute()`, `CLOSE_APP` vía handler legacy) recorre el camino **completo** de
`dispatch()` contando invocaciones reales de `input()` y exige exactamente 1. La arquitectura
ya lo anticipaba en su tabla de riesgos ("test dedicado cuenta invocaciones de
require_confirmation/input") pero no se había implementado.

**Sobre la sensibilidad del test — un falso PASS detectado y corregido:** el primer borrador
respondía `"no"` al prompt para evitar efectos reales. Eso hacía el test **vacuo**: al
cancelar en el primer gate, `dispatch()` retorna `"⛔ Acción no autorizada."` sin llegar nunca
a invocar el handler, de modo que el segundo gate jamás se alcanzaba y el test pasaba
*también con el bug presente*. Se rediseñó para responder `"si"` —atravesando así toda la
cadena— con los efectos reales del SO neutralizados vía mocks de `os.system` y
`subprocess.run`. Verificación de sensibilidad reinyectando artificialmente el gate interno:

```
PRE-fix (gate interno reinyectado):  SYS_POWER_OFF -> 2   CLOSE_APP -> 2
POST-fix (estado real actual):       SYS_POWER_OFF -> 1   CLOSE_APP -> 1
```

El test ahora sí falla si el doble gate vuelve.

## Efecto colateral señalado para QA/humano

Al quedar únicamente el gate central, el **texto del prompt** de estas 6 acciones cambia:
antes decía `'close_app'` con detalle `(cerrar chrome (chrome.exe))`; ahora dice `'CLOSE_APP'`
con detalle `(dispatch:CLOSE_APP)`. La cantidad de prompts y la semántica de la confirmación
son idénticas; solo cambia la redacción.

> **CORRECCIÓN (post re-verificación de orion-tester, OBS-1) — este párrafo original estaba
> equivocado y se rectifica:** afirmé acá que restaurar el texto literal "exigiría separar
> `details` en detalle-de-auditoría vs detalle-de-prompt, alterando la firma de
> `require_confirmation()` — fuera de la arquitectura aprobada". **Es falso.** Como verificó
> orion-tester, basta componer un `details` que sirva a la vez para prompt y auditoría
> (ej. `details=f"dispatch:{action_name} | {params}"`): ~2 líneas, sin cambio de firma y sin
> reabrir arquitectura. Además el impacto real es mayor de lo que estimé: en 2 de las 6
> acciones se pierde información de **consentimiento informado** — `CLOSE_APP` ya no dice
> *qué app* va a cerrar y `EXECUTE_CODE` ya no dice *qué tarea* va a ejecutar, de modo que el
> usuario confirma sin ver sobre qué. No lo implementé por cuenta propia porque el REQ ya
> pasó el handoff a `orion-qa` con veredicto PASS y OBS-1 quedó explícitamente elevada como
> decisión de QA/humano; queda listo para aplicarse en cuanto lo aprueben.

Se deja como *trade-off* consciente y reversible, para que `orion-qa` o el humano decidan si
amerita el ajuste de 2 líneas antes de cerrar o un REQ de seguimiento.

> **RESUELTO** — el humano decidió cerrarlo dentro de REQ-005. Ver "Iteración 3" al final.

## Verificación local — Iteración 2

```
cd agente_ia && python -m py_compile main.py os_integration/system_ctrl.py \
  skills/code_execution_skill.py skills/skill_creator_skill.py router/dispatcher.py \
  skills/skill_manager.py core/security_manager.py tests/test_security_manager.py
→ OK, sin errores.

cd agente_ia && python -m pytest tests/ --tb=short -v
→ 44 passed, 1 warning in 2.13s
  (42 de la Iteración 1 + 2 casos del test de regresión nuevo; sin regresiones)
```

---

# Iteración 3 — OBS-1 cerrada por decisión humana explícita

`orion-tester` re-verificó la Iteración 2 con veredicto **PASS 13/13** y elevó OBS-1 como
observación no bloqueante. **El humano decidió arreglarla dentro de REQ-005, no diferirla.**

Razón registrada de la decisión: *una confirmación sin contexto es casi una confirmación
automática* — si el prompt solo dice `'CLOSE_APP'` sin decir qué app, el humano pierde la
capacidad real de evaluar lo que aprueba, que es justamente el propósito del nivel YELLOW.
Además es una regresión **introducida por este REQ**, no preexistente.

## Cambio implementado

Nuevo helper en `agente_ia/core/security_manager.py`:

```python
def format_details(prefix: str, params: Optional[Dict] = None) -> str:
    """Return `prefix` plus the identifying params a human needs to judge the action."""
```

No cambia la firma de `require_confirmation()`: solo compone un `details` más informativo,
que sirve a la vez para el prompt y para el registro de auditoría.

### Tres recaudos aplicados al componer `details`

1. **Secretos / contenido sensible.** `details` se imprime al humano **y** se persiste en
   `audit.db`, así que **nunca** se vuelca `params` crudo. Se usa una **allowlist**
   deliberada (`_DETAILS_ALLOWED_KEYS`: `app_name`, `app`, `task`, `raw_text`, `skill_name`,
   `name`, `path`, `filename`, `folder`, `query`, `url`, `direction`) en vez de una denylist:
   una clave nueva que aparezca en el futuro queda fuera por defecto en vez de filtrarse.
   Verificado por test: `api_key`, `password` y `file_content` no llegan al `details`.
2. **Longitud.** `_DETAILS_MAX_VALUE_LEN = 200` por valor, con elipsis `...`. `EXECUTE_CODE`
   puede traer código largo; así el prompt sigue legible en consola y el log de auditoría no
   se inunda. Los saltos de línea se colapsan a espacios (`" ".join(str(v).split())`) para
   que el prompt no se rompa en varias líneas.
3. **`channel` excluida** del texto mostrado — es ruido para el humano y ya queda registrada
   en su propia columna de la auditoría.

### Puntos de gate actualizados (los 5, no solo las 6 acciones YELLOW)

Como pidió el coordinador, el contexto sirve igual para el registro de auditoría de una
acción RED bloqueada, así que se aplicó en todos los puntos donde hay params disponibles:

- `agente_ia/router/dispatcher.py` — `dispatch()` (handlers legacy)
- `agente_ia/skills/skill_manager.py` — `execute()` y `_make_gated_tool_fn()` (`get_agent_tools`)
- `agente_ia/agents/action_registry.py` — `execute_action()`
- `agente_ia/os_integration/capabilities_router.py` — `execute_capability()`

Resultado observado en los 4 casos representativos:

```
'dispatch:CLOSE_APP | app_name=chrome'
'skill:CodeExecutionSkill:EXECUTE_CODE | task=borra los logs viejos de la carpeta temp'
'skill:SkillCreatorSkill:DELETE_SKILL | raw_text=borra la skill de clima'
'action_registry:write_file_direct | path=C:/x/y.txt'      ← api_key filtrada, no aparece
```

## Tests agregados (5 nuevos)

- `test_yellow_prompt_includes_identifying_param` — end-to-end por `dispatch()`: confirmar
  `CLOSE_APP` con `{"app_name": "chrome"}` produce un prompt que **contiene "chrome"**. Es el
  test que pidió el coordinador y el que falla si OBS-1 reaparece.
- `test_details_includes_allowed_keys_and_omits_channel` — incluye el identificador, excluye
  `channel`.
- `test_details_omits_non_allowlisted_keys` — `api_key`/`password`/`file_content` nunca
  llegan al prompt ni a la auditoría.
- `test_details_truncates_long_values` — truncado a 200 caracteres + elipsis.
- `test_details_without_params_is_just_prefix` — sin params útiles no queda un sufijo vacío
  colgando.

## Verificación local — Iteración 3

```
cd agente_ia && python -m py_compile core/security_manager.py router/dispatcher.py \
  skills/skill_manager.py agents/action_registry.py os_integration/capabilities_router.py \
  tests/test_security_manager.py
→ OK, sin errores.

cd agente_ia && python -m pytest tests/ --tb=short -v
→ 49 passed, 1 warning in 1.28s
  (44 de la Iteración 2 + 5 tests nuevos; sin regresiones; el test de doble gate
   test_yellow_action_prompts_exactly_once_via_dispatch sigue en 1 prompt por acción)
```

## Pendiente de decisión (no tocado en esta iteración)

`OBS-2` (doble prompt residual en el camino de *excepción* de `dispatch()`,
`router/dispatcher.py:46-51`, donde además la acción se ejecuta igual tras el segundo prompt
— lo segundo es preexistente) y `OBS-3` (nombre `'Intent.SYS_POWER_OFF'` latente, no
alcanzable en producción) siguen abiertas como observaciones de `orion-tester`. No se
tocaron: la decisión humana recibida cubre únicamente OBS-1.
