# Auditoría de seguridad REQ-005 — Deny-list central de acciones Rojo aplicada en código

**Agente:** orion-security
**Fecha:** 2026-07-31
**Entrada auditada:** `propuestas/arquitectura-005.md` (APROBADA por johanrodriguezdev, sin ajustes) +
código real del repo (no solo el diseño en papel).
**Nota de continuidad:** un intento previo de esta auditoría se cortó por una falla de conexión de
infraestructura a mitad de respuesta, sin llegar a escribir ningún archivo ni tocar contexto/CSV.
Esta ejecución arranca desde cero, no revierte nada.

---

## 0. Método

No repito el trabajo ya hecho por `orion-baseline`/`orion-architect` (inventario de 23+30 acciones,
mapa de 7 caminos de ejecución, flujo de datos) — lo doy por válido porque lo verifiqué contra el
código real en los puntos que más importan para seguridad:

- `core/security_manager.py` (estado actual, pre-implementación) — confirmado línea por línea contra
  lo descrito en `baseline-005.md`.
- `router/dispatcher.py`, `skills/skill_manager.py`, `intent/classifier.py`, `core/orchestrator.py`,
  `core/base_agent.py`, `channels/gateway.py` — trazado manual del flujo completo de `params`/`channel`
  desde la entrada del usuario hasta el punto donde el gate futuro leerá `params.get("channel")`.
- `os_integration/system_ctrl.py`, `core/proactive_engine.py`, `agents/action_registry.py`,
  `config_manager.py`, `channels/telegram_bot.py` — verificación puntual de los hallazgos de baseline
  y de manejo de secretos.

---

## 1. Clasificación de riesgos implementados (diseño aprobado)

| Acción / categoría | Nivel | ¿Confirmación diseñada? | Estado |
|---|---|---|---|
| `format_disk`, `delete_database`, `expose_secrets`, `modify_source_code` (4 RED ya en código) | 🔴 Rojo | Sí — PIN maestro, solo DESKTOP | ✅ Ya correcto hoy en `require_confirmation()`; sin cambios de lógica RED. |
| `send_email_as_user`, `post_social_media`, `elevated_system_command`, `install_uninstall_software`, `modify_system_env_vars`, `grant_third_party_access` (6 RED sin implementar) | 🔴 Rojo | Sí — mismo mecanismo, pre-registro preventivo | ✅ Diseño correcto (`_register_default_actions()` ampliada). Pendiente de que `orion-dev` las agregue literalmente. |
| `shutdown`, `close_app`, `execute_code`, `create_skill`, `modify_skill`, `delete_skill` (YELLOW ya protegidas) | 🟡 Amarillo | Sí, ya funciona hoy | ✅ Diseño preserva la UX intacta (verificado: ninguna de las 6 líneas de `require_confirmation()` existentes cambia). |
| `restart`, `delete_file`, `delete_folder`, `send_message` (YELLOW pre-registradas, sin implementación real) | 🟡 Amarillo | N/A — no ejecutable hoy | ✅ Deuda documentada, no oculta; consistente con el mismo criterio usado para las 6 RED sin implementar. |
| Acciones GREEN reales (intents + `action_registry.py`) | 🟢 Verde | No | ✅ Inventario completo usado como fuente de verdad para fail-closed sin romper regresión — cobertura verificada contra `intent/intentions.py` y `get_intents()` de cada skill cargada. |
| Acción sin clasificar (nombre inventado, típico de una skill nueva o de un intent futuro no registrado) | — | Se **bloquea** por defecto | ✅ Cierra el fail-open real que hoy existe en `require_confirmation()` (línea 126: `if level is None or level == RiskLevel.GREEN` → hoy permite) y en `is_action_allowed()` (línea 119: `if level is None: return True` → hoy permite). Ambos confirmados en código. |
| `register_action()` — reclasificación de RED a un nivel menor | — | Se **bloquea** | ✅ Confirmado en código que hoy (`core/security_manager.py:108`) es público y sin ninguna protección — cualquier import puede degradar `format_disk` a GREEN. El diseño lo cierra correctamente para RED (fuera de alcance: YELLOW→GREEN, documentado como riesgo residual aceptado, coincide con el criterio literal de la SPEC). |
| `SYS_VOL_UP/DOWN/MUTE`, `PC_CLICK/TYPE/SCROLL` | 🟢 Verde (decisión humana ya cerrada) | No | ✅ No se reabre — aprobado explícitamente por el humano. Fuera del alcance de esta auditoría por instrucción directa. |
| `write_file_direct`, `save_file_desktop` | 🟡 Amarillo (decisión humana ya cerrada) | Sí | ✅ No se reabre. Ver hallazgo H3 (no bloqueante) sobre calidad de la confirmación. |

**Veredicto de este punto: ✅ Diseño correcto y completo para las 10 categorías RED de
`security-levels.md`.** Los 7 caminos de ejecución verificados en código (no solo los 3 de la SPEC)
quedan cubiertos por el mapa de inserción de gates de `arquitectura-005.md`. Todo lo anterior es
**diseño aprobado, aún no implementado** — la implementación es tarea de `orion-dev`; este veredicto
certifica que el diseño es correcto, no que el código ya lo cumple.

---

## 2. Secretos

- `config_manager.py` prioriza variables de entorno (`_ENV_KEY_MAP`: `DEEPSEEK_API_KEY`,
  `TELEGRAM_BOT_TOKEN`, `DISCORD_BOT_TOKEN`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `GEMINI_API_KEY`) sobre `config.json`. Verificado en código (`_get_config_value()`).
- `config.json` **sí está trackeado en git** (`git ls-files` lo confirma), pero su contenido actual
  no tiene ningún secreto — solo `agent_name`, `agent_pronunciation`, `ai_provider`, `ai_model`,
  `vision_provider`, `fallback_provider`. Verificado leyendo el archivo real.
- `.env` está en `.gitignore` (confirmado: `git check-ignore -v .env` → `agente_ia/.gitignore:4:.env`).
- Búsqueda de patrones de secretos hardcodeados (`sk-...`, `AIza...`, `xox[baprs]-...`, claves
  privadas PEM) en todo `*.py` del proyecto: **sin coincidencias**.
- `ORION_AUTH_PIN` se lee de entorno (`os.environ.get`), nunca hardcodeado; `verify_pin()` acepta
  tanto el valor plano como su hash SHA-256 — aceptable para un PIN local, no es la superficie que
  toca REQ-005.

**Hallazgo no bloqueante (H1, fuera de alcance de REQ-005):** `_get_config_value()` cae a
`config.get(key, default)` si la variable de entorno no está seteada — es decir, `config.json`
(trackeado en git) es un lugar técnicamente válido para persistir un secreto si algún flujo futuro
(ej. una UI de configuración) llamara `save_config()` con una API key dentro. Hoy no ocurre —
verificado que el único código que llama `save_config()` es `config_manager.py` mismo, con
`DEFAULT_CONFIG` o para cambiar `agent_name`. No es un hallazgo de REQ-005 (no toca esta ruta), se
documenta como recomendación de higiene general para un REQ futuro de configuración/secretos.

**Veredicto de este punto: ✅ Sin secretos expuestos hoy. Sin cambios necesarios para REQ-005.**

---

## 3. Confirmaciones en acciones destructivas

Confirmado en código real (`core/security_manager.py`, `os_integration/system_ctrl.py`,
`core/proactive_engine.py`) que **hoy** el bloqueo es 100% opt-in: `shutdown_pc()`, `close_app()`,
`CodeExecutionSkill`, `SkillCreatorSkill` llaman `require_confirmation()` por su cuenta; nada los
obliga. `dispatch()`, `skill_manager.execute()`, `get_agent_tools()`, `execute_action()` (no existe
aún), `execute_capability()` (no existe aún) no invocan seguridad en absoluto hoy.

El diseño aprobado mueve el gate **fuera** del cuerpo de cada skill/handler hacia el punto de entrada
de cada uno de los 7 caminos verificados, de forma que ninguno puede saltárselo por bug u omisión —
verificado que el mapa de inserción de `arquitectura-005.md` cubre efectivamente los 7 caminos que
`baseline-005.md` identificó en código (no solo los 3 de la SPEC).

**Veredicto de este punto: ✅ Diseño correcto.** Pendiente de implementación real por `orion-dev`
— el DoD de `orion-tester` debe verificar que el gate quedó puesto en los 7 puntos exactos, no solo
en los 3 originales de la SPEC.

---

## 4. Validación de inputs

- `write_file_direct(text, filename)` y `save_file_desktop(filename)` en `agents/action_registry.py`
  (líneas 38-48, 122-132) construyen la ruta como `Path.home() / "OneDrive" / "Desktop" / filename`
  **sin sanitizar `filename`** — un `filename` con componentes `..` podría escribir fuera del
  Escritorio. Verificado en código, no es un hallazgo de baseline/architect.
- El gate propuesto para `execute_action()` (`arquitectura-005.md`, `agents/action_registry.py`)
  pasa `details=f"action_registry:{name}"` a `require_confirmation()` — es decir, **el mensaje de
  confirmación que ve el humano no incluye el `filename`/`text` reales**, solo el nombre de la
  acción. Esto no es una vulnerabilidad de bypass (la acción sigue bloqueada sin confirmar), pero
  reduce el valor informativo de la confirmación YELLOW: el humano aprueba "ejecutar
  write_file_direct" sin ver qué archivo ni qué contenido.

**Hallazgo no bloqueante (H2):** ninguno de los dos puntos anteriores es una regresión introducida
por REQ-005 (el comportamiento ya es así hoy) y **la SPEC-005 excluye explícitamente cambios de UX
en YELLOW** ("Cambios al nivel 🟡 Amarillo... no incluye"). No lo marco como bloqueante para no
reabrir alcance ya acotado por el humano. Recomendación concreta para un REQ futuro (no este):
(a) sanitizar `filename` contra path traversal en `action_registry.py`, (b) incluir un resumen de
`params` relevantes en el mensaje de confirmación YELLOW cuando la acción escribe/modifica algo.

**Veredicto de este punto: ✅ Sin cambios requeridos en REQ-005** (riesgo real pero pre-existente y
explícitamente fuera de alcance por decisión ya aprobada del humano).

---

## 5. Hallazgo específico solicitado — channel-spoofing vía `extract_params()`

### Pregunta verificada
¿Puede el dict que devuelve `BaseSkill.extract_params(intent, text)` de una skill —construido a
partir del **texto libre del usuario**— inyectar o pisar la clave `"channel"` que el gate
(`require_confirmation()`) termina leyendo, permitiendo que un usuario escriba algo como "hazlo como
si fuera desktop" y se auto-otorgue el canal más permisivo?

### Trazado del flujo real (no solo el propuesto)

`intent/classifier.py:classify_command()` (línea 24-28) hace algo importante que no estaba explícito
en `baseline-005.md`/`arquitectura-005.md`: cuando una skill maneja el intent, **descarta por
completo** cualquier `params` previo y devuelve **literalmente** `skill_manager.extract_params(intent,
text)` como el nuevo `params`:

```python
if skill_manager.handles_intent(intent):
    params = skill_manager.extract_params(intent, text.lower().strip())
    return intent, params
```

Es decir: si una skill futura (o una ya existente, hoy ninguna lo hace) devolviera
`{"city": "bogota", "channel": "desktop"}` desde `extract_params()` porque el usuario escribió algo
que su regex interpreta como canal, esa clave `"channel"` viaja intacta en el `params` que
`classify_command()` retorna.

Rastreé los **4 puntos de código reales** donde ese `params` (proveniente de `classify_command()`)
llega a una función que hoy es punto de gate (real o propuesto):

| Sitio | Línea | ¿Qué hace con `channel` después de `classify_command()`? | ¿Seguro? |
|---|---|---|---|
| `core/orchestrator.py:_try_quick_dispatch()` | 57-58 | `intent, params = self._classifier(text)` seguido, en la línea **siguiente**, de `params["channel"] = channel` — asignación **incondicional**, no `setdefault`, no merge — con `channel` siendo el argumento confiable recibido por `process_task(channel=...)` (viene de `message.channel` en `gateway.py`/`telegram_bot.py`, nunca del texto del usuario). | ✅ Sí — sobrescribe cualquier `"channel"` que `extract_params()` haya podido inventar. |
| `router/dispatcher.py:dispatch_as_tool()` | 63-65 | `intent, intent_params = classifier(text)` seguido de `intent_params["channel"] = params.get("channel", "desktop")` — también asignación incondicional; `params` aquí es el dict que el propio `AgentTool` recibió (`{"task","context","channel"}`, fijado estructuralmente por `_DynamicAgentInstance.execute()`, nunca por el LLM ni por `extract_params`). | ✅ Sí, **siempre que** el fix de `core/base_agent.py` (propagar `channel` real al nivel superior) se implemente tal como está en la arquitectura. |
| `channels/gateway.py` | 77-92 | `intent, params = classify_command(text)`; línea 87 hace `params["channel"] = message.channel`, pero ese `params` **nunca se usa** — el resultado real viene de `orchestrator.process_task(text=text, channel=message.channel, ...)` en la línea siguiente, que re-clasifica todo internamente vía `_try_quick_dispatch`. | ✅ Inofensivo (código muerto), pero confuso — ver H4. |
| `main.py` (loop desktop) | ~155, ~202 | `dispatch(act_intent, act_params)` / `dispatch(intent, params)` — **hoy sin ninguna inyección de `channel`** (bug ya documentado por `orion-architect` como "hallazgo propio #2"). El fix propuesto es agregar `params["channel"] = "desktop"` **después** de `classify_command()` y **antes** de `dispatch()`. | ⚠️ Seguro **solo si** se implementa como asignación incondicional (no `params.setdefault("channel", "desktop")`, que sí respetaría un `"channel"` inventado por `extract_params()`). Aún no implementado — es código pendiente, no una brecha ya cerrada. |

`skill_manager.execute()` (el único otro punto de gate) solo tiene **un** llamador en todo el
código (`router/dispatcher.py:48`), y ese llamador es `dispatch()`, cuyo `params` ya pasó por una de
las reasignaciones seguras de arriba antes de llegar ahí — no hay una ruta alterna que lo invoque con
un `params` no verificado.

### Conclusión del hallazgo

**El vector que describís es real como categoría de riesgo, pero no está abierto en el diseño
aprobado tal como está especificado — está cerrado por una convención de "reasignar `channel` de
forma incondicional inmediatamente después de `classify_command()`" que el código (y la propuesta de
`orion-architect`) ya sigue en 3 de los 4 puntos verificados.** El cuarto punto (`main.py`) es
trabajo pendiente de implementación, no una brecha ya cerrada.

El problema real no es de diseño sino de **que esta invariante nunca quedó escrita como regla
explícita** en `arquitectura-005.md`, y **ningún test de los 17 sugeridos la verifica
directamente**. El test 4 (`test_prompt_injection_fake_pin_ignored`) cubre `pin`/`confirmed` falsos
dentro de `params`, pero no cubre específicamente una clave `"channel"` falsa devuelta por
`extract_params()`. El test 13 (`test_agent_chain_propagates_real_channel`) verifica que el canal
real se propaga, pero no verifica que un canal **falso inyectado por el texto del usuario a través
de una skill** sea ignorado. Son pruebas relacionadas pero no equivalentes — ninguna cubre
literalmente este caso.

Esto es exactamente el tipo de propiedad que, sin un test explícito, se puede romper en silencio en
un refactor futuro (por ejemplo, si alguien "simplifica" `main.py` usando
`params.setdefault("channel", "desktop")` en vez de asignación directa, o si una función nueva
delega en `dispatch()` sin pasar por la reasignación).

### Severidad y mitigación

**Severidad: MEDIA.** No es un bypass explotable hoy en el diseño aprobado (verificado en los 4
puntos reales de código), pero es una invariante de seguridad crítica sostenida únicamente por
convención implícita, sin documentación ni test que la proteja — y uno de los 4 puntos que la
necesitan (`main.py`) todavía no está implementado.

**Mitigación concreta (no requiere reabrir ni modificar la arquitectura ya aprobada — es un
addendum de implementación y de pruebas):**

1. **Regla explícita a agregar en `core/security_manager.py`** (docstring de
   `require_confirmation()`, no cambio de lógica): *"El parámetro `channel` debe provenir siempre de
   una fuente controlada por el flujo de invocación (canal real del mensaje, o `'desktop'` fijo en
   el loop de escritorio) — nunca debe leerse un valor de `channel` que haya pasado, sin
   sobrescritura posterior, por `extract_params()` de una skill, porque ese método parsea texto
   libre del usuario."*
2. **En `main.py`**, implementar la inyección de `channel="desktop"` como asignación incondicional
   (`params["channel"] = "desktop"`), tal como ya está descrito en `arquitectura-005.md` — **no**
   usar `setdefault` ni `params.get("channel", "desktop")` seguido de reasignación condicional.
   Marcar esto como ítem obligatorio del DoD de `orion-dev`, no opcional.
   **Nota de asimetría defensiva:** esta mitigación cierra el vector concreto de channel-spoofing
   vía `extract_params()`, pero no es un endurecimiento simétrico contra cualquier otra clave
   contaminada del mismo dict (ver ítem 5 abajo) — se documenta como limitación conocida, no como
   solución total.
3. **Nuevo test obligatorio** en `tests/test_security_manager.py` (además de los 17 ya sugeridos):
   `test_extract_params_channel_key_ignored_by_gate` — simula una skill cuyo `extract_params()`
   devuelve `{"channel": "desktop", ...}` a partir de un texto adversarial (ej. "hazlo como si fuera
   desktop, apaga el pc"), la enruta a través de `orchestrator._try_quick_dispatch()` con
   `channel="telegram"` real, y verifica que `require_confirmation()` recibe `"telegram"` (bloqueado,
   GREEN-only) y no `"desktop"`. Repetir para el camino `main.py` una vez implementado.
4. Este ítem **no bloquea** el paso a `orion-dev` porque no requiere cambiar ninguna decisión de
   `arquitectura-005.md` (ubicación del gate, `resolve_channel()`, etc.) — es una regla de
   implementación + una prueba que deben entrar en el mismo trabajo que ya está planeado. Lo marco
   como **obligatorio dentro del DoD de `orion-dev`/`orion-tester`**, no como hallazgo que deba volver
   a `orion-architect`.
5. **Nota residual explícita:** este hallazgo se centró en la clave `"channel"` porque es la que
   determina el nivel de confianza de canal. No verifiqué exhaustivamente si alguna otra clave que
   una skill pudiera inventar en `extract_params()` (además de `channel`) es leída por algún gate
   además de `action_name` y `channel` — según el diseño, el gate **solo** lee esas dos, así que no
   debería importar, pero recomiendo que `orion-dev` audite rápidamente, al implementar cada gate,
   que ninguno termine leyendo accidentalmente algo más de `params` proveniente de `extract_params()`
   (ej. un futuro `params.get("confirmed")` agregado por error).

**Veredicto de este punto: ⚠️ Riesgo real identificado, NO bloqueante para continuar a `orion-dev`,
pero con condiciones obligatorias de implementación y de test que deben cumplirse dentro del mismo
REQ-005 (no diferirse).**

---

## 6. Hallazgo adicional menor (no bloqueante)

**H4 — código muerto/confuso en `channels/gateway.py`:** líneas 77-92. `params["channel"] =
message.channel` (línea 87) se ejecuta sobre un `params` que nunca se usa (el resultado real viene
de `orchestrator.process_task(...)`, que re-clasifica todo). No es un riesgo de seguridad (el dato
correcto sí llega por la otra vía), pero es ruido que puede confundir a un futuro desarrollador
haciéndole pensar que ese `params` alimenta el `dispatch()` real. No está en el alcance de módulos a
modificar de `arquitectura-005.md` — lo señalo como observación de calidad de código para
`orion-dev`, sin bloquear nada.

---

## Resumen de veredictos por punto del DoD

| Ítem del DoD de `orion-security` | Veredicto |
|---|---|
| Riesgos clasificados en verde/amarillo/rojo | ✅ Completo — 10/10 categorías RED, cobertura de los 7 caminos de ejecución reales |
| Secretos auditados (API keys, tokens) | ✅ Sin hallazgos — ninguno hardcodeado, `.env` ignorado por git, `config.json` sin secretos hoy |
| Confirmaciones en acciones destructivas verificadas | ✅ Diseño correcto para cerrar el opt-in/fail-open actual, verificado en código real |
| Validación de inputs revisada | ✅ Revisada — 1 hallazgo no bloqueante (path traversal en `action_registry.py`, fuera de alcance por decisión ya aprobada) |
| security-audit-005.md generado | ✅ Este documento |

## Veredicto final: ✅ APROBADO

Con **una condición obligatoria no opcional** que debe incorporarse al trabajo de `orion-dev` y
`orion-tester` dentro de este mismo REQ-005 (no es un hallazgo que regrese a `orion-architect`, no
cambia ninguna decisión de la arquitectura ya aprobada por el humano):

1. Implementar la inyección de `channel` en `main.py` como asignación incondicional (no
   `setdefault`/merge), exactamente como ya lo describe `arquitectura-005.md`.
2. Agregar el test `test_extract_params_channel_key_ignored_by_gate` (sección 5 de este documento) a
   `tests/test_security_manager.py`, además de los 17 ya sugeridos por `orion-architect`.
3. Agregar la nota de invariante de diseño (sección 5, ítem 1) como docstring en
   `require_confirmation()`.

El flujo puede continuar a `orion-dev` con estas tres condiciones incorporadas a su alcance de
trabajo.
