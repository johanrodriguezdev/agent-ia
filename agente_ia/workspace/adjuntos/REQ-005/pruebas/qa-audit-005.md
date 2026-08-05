# Auditoría QA REQ-005 — Deny-list central de acciones Rojo aplicada en código

**Agente:** orion-qa
**Fecha:** 2026-08-01
**Categoría:** SEGURIDAD
**Versión auditada:** Iteraciones 1+2+3+4 (versión final, la que verificó orion-tester en su
"Re-verificación final" con PASS 13/13)

**Estado de redacción: COMPLETO.**

---

## 0. Método

No repito la verificación funcional de `orion-tester` (13/13 criterios, 54 tests, reinyección de 6
fallos para probar que los tests no son vacuos). La revisé, es rigurosa y la doy por válida. Confirmé
por mi cuenta solo los puntos que sostienen mi propio veredicto, y dediqué el resto del esfuerzo a
lo que un tester no cubre: **superficie de datos, invariantes no verificables, y consistencia**.

Leí completo el código real de: `core/security_manager.py`, `router/dispatcher.py`,
`skills/skill_manager.py`, `core/base_agent.py`, `agents/action_registry.py`,
`os_integration/capabilities_router.py`, `os_integration/system_ctrl.py`,
`channels/telegram_bot.py` (rutas de apagado), `channels/api_channel.py`, `core/proactive_engine.py`,
`main.py` (puntos de inyección de canal) y `.gitignore`.

---

## 1. Seguridad

### 1.1 Secretos hardcodeados — sin hallazgos

- Ningún API key, token o PIN literal en el código nuevo. `ORION_AUTH_PIN` se lee siempre de
  entorno (`core/security_manager.py:11,136,141`).
- El PIN nunca se escribe en logs ni en `audit.db`: `require_pin()` lo lee con `getpass.getpass()`
  (no eco en consola), lo compara y lo descarta. Los `logger.warning("PIN incorrecto")` y las filas
  de auditoría `autorizada_rojo` / `intento_rojo` registran la acción y el canal, **nunca el valor
  del PIN**. Verificado línea por línea en `core/security_manager.py:144-153, 249-259`.
- `*.db` está en `.gitignore` (línea 17): `audit.db` no se versiona. Correcto.

### 1.2 🔴 HALLAZGO PROPIO — `audit.db` pasó de log de seguridad a log de actividad del usuario, y hay un endpoint HTTP sin autenticación que lo sirve en `0.0.0.0`

Este es el hallazgo central de mi auditoría y **no aparece en ninguno de los documentos previos**.
Se compone de tres hechos verificados, cada uno inocuo por separado:

1. **`require_confirmation()` audita también el nivel GREEN.** `core/security_manager.py:229-231`
   escribe una fila `"permitida"` para toda acción Verde. Antes de REQ-005, `require_confirmation()`
   era opt-in y lo llamaban ~6 sitios, así que `audit.db` crecía solo con acciones sensibles.
   Después de REQ-005 el gate está en el punto de entrada de **todos** los caminos: cada comando
   del usuario —incluido `CHAT` y `UNKNOWN`— escribe una fila.
2. **`details` ahora lleva texto libre del usuario.** `format_details()` (Iteración 3, OBS-1) es
   correcto en lo que se propuso resolver, pero su allowlist incluye `raw_text`, `task`, `query`,
   `url`, `path` y `filename`. `task` es literalmente el texto de la tarea del usuario en el camino
   de agentes (`core/base_agent.py:98-102`) y en `dispatch_as_tool()`; `raw_text` es el texto
   completo del usuario en `SkillCreatorSkill.extract_params()`
   (`skills/skill_creator_skill.py:99`). Ese texto se persiste.
3. **`channels/api_channel.py` expone `GET /audit`** (líneas 55-58) devolviendo las últimas 50
   filas **sin ninguna autenticación**, con `Access-Control-Allow-Origin: *` (línea 19), sobre un
   servidor que hace `HTTPServer(("0.0.0.0", 8723))` (línea 107) — es decir, **escuchando en todas
   las interfaces de red, no en localhost**.

**Composición:** cualquiera en la misma red (o en el mismo navegador, vía CORS abierto) puede leer
un registro rodante de lo que el usuario le pidió a O.R.I.O.N.

**Atribución honesta:** los tres elementos son **pre-existentes** en su forma individual — REQ-005
no creó el endpoint ni el bind a `0.0.0.0` ni el CORS. Lo que REQ-005 hace es **cambiar
materialmente el valor del objetivo**: convirtió un log casi vacío en un registro completo de
actividad con texto libre. Eso lo hace un hallazgo de este REQ aunque el defecto de exposición sea
heredado.

**Confirmación desde el propio material del proyecto:** `workspace/referencias/openclaw/01-seguridad-y-aislamiento.md:1444`
ya lo anticipa textualmente — *"Metadata-only por defecto, contenido opt-in. Si `audit.db` guarda el
contenido de todos los mensajes de Telegram, `audit.db` se convierte en el archivo más sensible del
sistema."* REQ-005 acaba de dar ese paso sin declararlo.

### 1.3 Retención de la auditoría — no existe

No hay purga, rotación ni límite de filas en ninguna parte del código (`grep` sobre `audit_log`:
solo `CREATE TABLE`, un `INSERT` y un `SELECT ... LIMIT`). Con una fila por comando y sin retención,
`audit.db` crece de forma monótona e indefinida. No es un riesgo de seguridad inmediato, pero es la
otra mitad del punto anterior: un archivo que crece sin límite y contiene texto libre del usuario.

### 1.4 Truncado a 200 caracteres — suficiente para su propósito, irrelevante para este riesgo

`_DETAILS_MAX_VALUE_LEN = 200` cumple lo que se diseñó: que el prompt no rompa la consola y que un
`EXECUTE_CODE` con código largo no inunde el log. **No es una medida de privacidad** y no debe
leerse como tal: 200 caracteres alcanzan de sobra para reconstruir qué pidió el usuario. El
problema no es el largo, es que el campo se persista y se sirva por HTTP sin auth.

### 1.5 Acciones destructivas — confirmación verificada

Verificado directamente en el código, no por reporte de terceros:

| Camino | Gate | Ubicación |
|---|---|---|
| `dispatch()` (skill moderna + handler legacy) | `require_confirmation()` antes de bifurcar | `router/dispatcher.py:56-61` |
| `get_agent_tools()` (AgentTool individual) | `_make_gated_tool_fn()` | `skills/skill_manager.py:100-110` |
| `agents/action_registry.execute_action()` | gate antes de `fn(**params)` | `agents/action_registry.py:256-265` |
| `os_integration/capabilities_router.execute_capability()` | gate antes del `importlib` | `os_integration/capabilities_router.py:59-62` |
| Telegram `_handle_shutdown` / `_handle_restart` | `require_confirmation()` con canal fijo | `channels/telegram_bot.py:629-637, 659-667` |

En los 5 puntos el gate está **antes** de cualquier efecto y con retorno temprano. En Telegram el
canal es `ChannelType.TELEGRAM` **hardcodeado**, no leído de `params` — confirmo que no es
falsificable desde el mensaje.

## 2. Niveles de riesgo

Todo lo de esta sección lo **ejecuté yo** contra el código real (script en scratchpad, `AUDIT_DB`
redirigida a un temporal, sin tocar el `audit.db` del proyecto). No es lectura del informe del tester.

### 2.1 🔴 Rojo — cobertura una por una de las 10 categorías de `security-levels.md`

| # | Categoría de `security-levels.md` | Clave registrada | Nivel real |
|---|---|---|---|
| 1 | Formatear discos o particiones | `format_disk` | ✅ RED |
| 2 | Borrar bases de datos (`memory.db`, `semantic_memory.db`, `tasks.db`) | `delete_database` | ✅ RED |
| 3 | Modificar/borrar el propio código de O.R.I.O.N. | `modify_source_code` | ✅ RED |
| 4 | Exponer API keys, tokens o credenciales | `expose_secrets` | ✅ RED |
| 5 | Enviar correos como si fuera el usuario | `send_email_as_user` | ✅ RED |
| 6 | Publicar en redes sociales | `post_social_media` | ✅ RED |
| 7 | Ejecutar comandos con privilegios elevados | `elevated_system_command` | ✅ RED |
| 8 | Instalar o desinstalar software | `install_uninstall_software` | ✅ RED |
| 9 | Modificar variables de entorno del sistema | `modify_system_env_vars` | ✅ RED |
| 10 | Dar acceso a terceros a sistemas internos | `grant_third_party_access` | ✅ RED |

Además verifiqué el conjunto completo: `_actions` contiene **exactamente 10** entradas RED, ni una
menos ni una de más. **Ninguna categoría quedó fuera y no hay RED espurias.**

**Reclasificación:** `register_action("format_disk", GREEN)` → `False`, sigue RED.
`register_action("format_disk", YELLOW)` → `False`, sigue RED. Correcto.
Confirmo también el límite conocido y ya aceptado: `register_action("shutdown", GREEN)` → `True`,
la degradación YELLOW→GREEN **no** está protegida. Es una exclusión explícita de la SPEC y de
`arquitectura-005.md`, aceptada como riesgo residual. La registro para que no se pierda, no como
hallazgo nuevo.

### 2.2 🟡 Amarillo — se implementaron confirmaciones

`shutdown`, `restart`, `close_app`, `delete_file`, `delete_folder`, `execute_code`, `create_skill`,
`modify_skill`, `delete_skill`, `send_message`, `write_file_direct`, `save_file_desktop` y los 6
intents `CLOSE_APP`/`SYS_POWER_OFF`/`EXECUTE_CODE`/`CREATE_SKILL`/`MODIFY_SKILL`/`DELETE_SKILL`.
Confirmación implementada: **sí**, un solo prompt por acción, en el punto de entrada de cada camino.

### 2.3 🟢 Verde

32 intents + 18 acciones de `ACTION_REGISTRY` + `proactive_trigger`. Se ejecutan sin fricción.
Se auditan igual (ver hallazgo 1.2).

### 2.4 Fail-closed — verificado de verdad, no por reporte

| Prueba | Resultado |
|---|---|
| `require_confirmation("__no_existe_xyz__", "desktop")` | `False` + fila `bloqueada_no_clasificada` |
| `require_confirmation("__no_existe_xyz__", None)` | `False` |
| `is_action_allowed("__no_existe_xyz__", DESKTOP)` | `False` |
| `resolve_channel(None)` | `UNKNOWN` ✅ (no DESKTOP) |
| `resolve_channel("basura")` | `UNKNOWN` ✅ |
| `resolve_channel("")` | `UNKNOWN` ✅ |
| `resolve_channel(0)` / `resolve_channel(False)` | `UNKNOWN` ✅ — probé los *falsy* a propósito, porque son el caso donde un `or` mal escrito suele colar un default |
| `get_allowed_levels(UNKNOWN)` | `[GREEN]` — solo Verde |
| `is_action_allowed("shutdown", UNKNOWN)` | `False` |

**Fail-closed confirmado en los dos ejes: acción no clasificada y canal no determinable.**

### 2.5 PIN maestro — verificado

| Prueba | Resultado |
|---|---|
| RED en DESKTOP **sin** `ORION_AUTH_PIN` | `False` — bloqueada, sin excepción posible ✅ |
| RED en DESKTOP con PIN correcto | `True` ✅ |
| RED en DESKTOP con PIN incorrecto (3 intentos) | `False` ✅ |
| RED en `telegram` / `discord` / `voice` / `api` / `unknown` / `None`, **con PIN correcto** | `False` en los 6 ✅ |

La excepción Roja es **solo DESKTOP**, tal como exige la SPEC. Sin PIN hardcodeado, sin PIN en
logs, sin PIN en `audit.db`, leído con `getpass` (sin eco).

### 2.6 ⚠️ Observación — `verify_pin()` y `require_pin()` devuelven `True` cuando no hay PIN configurado

`core/security_manager.py:138-153`: si `ORION_AUTH_PIN` no está seteada, `verify_pin("cualquier
cosa")` → `True` y `require_pin()` → `True` sin preguntar nada. **Hoy no es explotable**: verifiqué
por grep que ninguno de los dos métodos tiene llamadores fuera de `security_manager.py`, y el único
call site real (`:252`) exige `has_pin()` **antes** de invocar `require_pin()`, así que la rama
insegura es inalcanzable.

Lo registro igual porque es una trampa latente de forma peligrosa: la única primitiva de
autenticación del sistema es **fail-open por defecto**, en un REQ cuya tesis es exactamente lo
contrario. El día que alguien escriba `if security_manager.verify_pin(x):` en un módulo nuevo, va a
obtener un `True` gratis en cualquier instalación sin PIN. Pre-existente, no introducido por
REQ-005. **No bloqueante** — condición para REQ futuro, ver sección 7.

---

## 3. Logging

- **Cero `except: pass` o `except Exception: pass` silencioso en el código nuevo.** Revisé el
  `git diff HEAD` completo de los 14 módulos tocados: el REQ agrega **un solo** bloque `except`
  (`router/dispatcher.py:74`), y captura como `except Exception as e:` con `logger.error()` que
  incluye la acción y la excepción.
- REQ-005 además **mejora** el logging existente: reemplaza
  `print(f"[Dispatcher] Error ejecutando skill modular: {e}")` por `logger.error(...)`. Va en la
  dirección de `.claude/rules/python-style.md` ("usar `logging`, no `print()`").
- Las acciones sensibles quedan registradas como exige `security-levels.md`:
  `logger.warning` en YELLOW bloqueado por canal y en intento RED (`:234`, `:251`),
  `logger.critical` en intento de reclasificación de una RED (`:178`), `logger.info` en
  confirmación/cancelación YELLOW y en autorización RED por PIN.
- La auditoría cubre el vocabulario completo de resultados: `permitida`, `confirmada`, `cancelada`,
  `bloqueada_canal`, `bloqueada_no_clasificada`, `intento_rojo`, `autorizada_rojo`,
  `reclasificacion_bloqueada`.

**Observación menor (pre-existente, no bloqueante):** `get_audit_log()`
(`core/security_manager.py:132-133`) hace `except Exception: return []` **sin logging**. Es
precisamente el patrón que la regla prohíbe, y está dentro del módulo de seguridad: si la lectura de
la auditoría falla, el sistema devuelve "no hay nada" en vez de "no pude leer". No fue introducido
por REQ-005 y no afecta ninguna decisión de bloqueo. Corrección de una línea, recomendada para el
REQ que atienda el hallazgo 1.2.

---

## 4. Consistencia de código

- **Convenciones (`.claude/rules/python-style.md`):** `snake_case`/`PascalCase`/`UPPER_CASE`
  respetados; type hints presentes en todas las funciones nuevas (`format_details`,
  `resolve_channel`, `register_action`, `check_coverage`, `execute_action`,
  `_make_gated_tool_fn`); imports agrupados y ordenados; líneas dentro de 100 caracteres;
  docstrings en imperativo o descriptivos, presentes en todo lo público nuevo.
- **Sin dead code introducido.** `_make_gated_tool_fn()` reemplaza correctamente una lambda inline;
  los imports de `security_manager`/`ChannelType` se eliminaron de los 3 archivos que perdieron su
  gate interno, sin referencias residuales.
- **Sin prints de debug.** Los únicos `print()` que quedan en el camino nuevo son de UI destinada al
  usuario final (mensaje de acción no autorizada, carga de skills), no trazas de desarrollo.
- **Comentarios de diseño en el lugar correcto.** El comentario de `router/dispatcher.py:52-55` y
  el de `:75-78` explican *por qué* el gate está antes de la bifurcación y *por qué* el fallback no
  re-pregunta. Es exactamente el tipo de comentario que evita que un refactor futuro rompa la
  invariante sin darse cuenta. Buen trabajo.

**Observación menor (no bloqueante, pre-existente):** ni `main.py` ni ningún módulo reconfiguran la
codificación de `stdout`, y `core/security_manager.py:240,253,257-258` emite emoji (`⚠️`, `⛔`) por
`print()`/`input()`. Con un terminal interactivo de Windows funciona; con `stdout` **redirigido**
(a un archivo, a un pipe, o corriendo como servicio) la codificación cae a `cp1252` y la línea 258
lanza `UnicodeEncodeError` — lo reproduje al ejecutar mis pruebas con la salida canalizada. El modo
de fallo es *seguro* (la excepción interrumpe antes de ejecutar nada, y en los caminos de
`AgentTool`/`dispatch_as_tool` queda capturada), pero convierte una denegación limpia en un
error críptico. Es un patrón general del proyecto, no una regresión de REQ-005.

## 5. Dictámenes sobre los puntos elevados

### 5.1 `format_details()` y `audit.db` — la allowlist es correcta; el problema está en otro lado

**Dictamen: la allowlist está bien construida y NO debe tocarse. El riesgo real no se arregla ahí.**

La allowlist hace exactamente lo que se diseñó: bloquea por defecto toda clave no prevista
(verifiqué el criterio de diseño en `core/security_manager.py:50-57`, y el tester lo comprobó con
`api_key`, `password`, `token`, `file_content`, `secret`, `pin` y una clave inventada). Elegir
allowlist sobre denylist fue la decisión correcta.

Pero la pregunta que se me hizo es distinta: **¿alguna clave *permitida* arrastra datos sensibles?**
Sí. `raw_text` es el texto completo del usuario (`skills/skill_creator_skill.py:99`), y `task`,
`query`, `url`, `path` y `filename` son entrada del usuario. Están ahí a propósito y son
*necesarios*: son precisamente lo que OBS-1 pidió recuperar para que la confirmación sea consentimiento
informado y no un reflejo. Quitarlos reabriría la regresión que el humano decidió explícitamente
cerrar.

**De ahí el dictamen: no se arregla estrechando la allowlist — se arregla en el destino.** El
problema no es que el humano vea "cierra chrome" en el prompt; es que ese dato se **persista sin
retención** y se **sirva por HTTP sin autenticación en `0.0.0.0`** (hallazgo 1.2). Las dos
correcciones correctas, en orden de urgencia:

1. **`GET /audit` de `channels/api_channel.py` debe exigir autenticación, y el servidor debe
   escuchar en `127.0.0.1`, no en `0.0.0.0`.** Es el cambio que más riesgo elimina por menos código.
2. **Política de retención en `audit_log`** (purga por antigüedad o tope de filas). Hoy no existe
   ninguna: el archivo crece de forma monótona para siempre.

Sobre el truncado a 200 caracteres: **alcanza para lo que fue diseñado** (que el prompt no rompa la
consola y que `EXECUTE_CODE` no inunde el log) y **no alcanza —ni pretende— como control de
privacidad**. 200 caracteres bastan para reconstruir qué pidió el usuario. No pedir que se cambie
el número: pedir que se proteja el destino.

**Bloqueante: NO.** El vector de exposición es pre-existente y no es un bypass del deny-list —
ninguna acción se ejecuta de más. Pero es la condición #1 para el próximo REQ de seguridad, y debe
quedar registrada como tal, no como "mejora deseable".

### 5.2 La invariante no verificable de `SkillManager.execute()`

**Dictamen: el docstring es necesario pero NO es suficiente. Falta un test estructural. No bloquea
REQ-005.**

No me convence el docstring como única defensa, y la razón es la tesis del propio REQ: REQ-005
existe porque *"cada skill debe decidir por su cuenta llamar a `require_confirmation()`"* era un
modelo frágil. Cerrar el REQ dejando la seguridad de `skill_manager.execute()` sostenida por una
frase en prosa reintroduce, un nivel más arriba, exactamente el patrón que el REQ vino a eliminar:
una protección que depende de que el próximo humano lea y obedezca.

Hoy la invariante es cierta —lo confirmo: un único llamador, `router/dispatcher.py:73`— y ningún
test falla si mañana deja de serlo. Ese es el defecto: es silencioso.

**La corrección que dictamino es una sola, concreta:** un test estructural en
`tests/test_security_manager.py` que recorra los `.py` del proyecto y afirme que
`skill_manager.execute(` tiene exactamente un call site, en `router/dispatcher.py`. Diez líneas, sin
costo en runtime, y falla ruidosamente en el momento exacto en que alguien agrega el segundo
llamador — que es cuando hay que enterarse.

**Descarto explícitamente** la alternativa de un token/flag de "ya gateado" pasado por el llamador:
introduce en la firma justo el tipo de estado "esta invocación ya fue confirmada" que `orion-dev`
descartó con buen criterio en la Iteración 2, y no aporta nada que el test no dé más barato.

**Bloqueante: NO** — la invariante se cumple hoy y está verificada por dos agentes de forma
independiente. Es condición nombrada para el próximo REQ de seguridad, no un pendiente difuso.

### 5.3 El fallback por excepción de `dispatch()` (OBS-5)

**Dictamen: aceptable en un REQ de seguridad. No es una puerta abierta.**

La puerta que habría importado —que el gate **deniegue** y la acción se ejecute igual por el camino
legacy— está cerrada y verificada empíricamente (casos E2 y E3 del tester: 0 ejecuciones, y en
Telegram 0 prompts). La frontera de autorización, que es lo que un REQ de seguridad posee, está
intacta: en el caso E1 el gate **autorizó**, y lo que se ejecuta después es la misma acción que el
usuario confirmó, por otro camino.

Lo que queda no es un problema de autorización sino de **idempotencia**: si la skill falló *después*
de producir efectos parciales, el handler legacy repite la operación. Para `CLOSE_APP` es inocuo;
para una futura acción YELLOW que escriba o borre, no lo sería. Ese es el riesgo real, y es
pre-existente, está comentado en el código y es deliberado.

No lo cierro dentro de REQ-005 porque cerrarlo bien no es acotar el `try/except` —es decidir la
semántica de reintento de una acción con efectos parciales—, y eso es diseño, no una corrección de
QA. Recomendación para el REQ futuro: acotar el `except` al `import` y a `handles_intent()`, y que
`skill_manager.execute()` propague su propio error en vez de disparar el fallback.

### 5.4 Parámetros `channel` muertos en `shutdown_pc()` / `close_app()` (OBS-6)

**Dictamen: sí, hay riesgo real de que alguien los crea vivos. Deben eliminarse. No bloquea.**

Es peor de lo que sugería la observación del tester, y lo verifiqué por grep: no son defaults
inertes, son **cañería activa que no desemboca en nada**. Tres call sites cargan el valor y lo pasan:

```
executor/handlers.py:39   system_ctrl.close_app(app_name, params.get("channel"))
executor/handlers.py:78   system_ctrl.shutdown_pc(params.get("channel"))
skills/system_control_skill.py:57   system_ctrl.shutdown_pc(channel)
```

Quien trace el recorrido del canal por el código lo ve entrar a `shutdown_pc` y concluye,
razonablemente, que ahí se usa. Un parámetro que no hace nada y que se llama igual que la variable
más crítica del sistema es peor que no tener parámetro.

Lo que reduce la severidad —y por lo que no bloqueo— es que el docstring inmediatamente encima dice
lo contrario en términos explícitos ("esta función NO se auto-protege"). La documentación salva la
situación; la firma la contradice.

**Corrección: eliminar el parámetro `channel` de ambas funciones y los 3 argumentos de los call
sites.** Cuatro líneas. Condición para el próximo REQ.

### 5.5 Las 3 condiciones obligatorias de `security-audit-005.md` — verificadas por mi cuenta

| Condición | Verificación propia | Estado |
|---|---|---|
| Inyección de `channel` en `main.py` como asignación **incondicional** | `main.py:155` → `act_params["channel"] = "desktop"`; `main.py:203` → `params["channel"] = "desktop"`. Ambas asignación directa post-`classify_command()`. Grep de `setdefault("channel"` en todo el repo: **cero resultados** | ✅ IMPLEMENTADA |
| Test `test_extract_params_channel_key_ignored_by_gate` | Presente en `tests/test_security_manager.py:326`, pasando | ✅ IMPLEMENTADA |
| Docstring de invariante de `channel` en `require_confirmation()` | `core/security_manager.py:214-221`, texto completo y correcto | ✅ IMPLEMENTADA |

---

## 6. Dictamen de proceso — `desarrollo-log-005.md` incompleto (OBS-4)

**Los hechos, confirmados:** `propuestas/desarrollo-log-005.md` termina en la Iteración 3. La
Iteración 4 —que cerró OBS-2 y OBS-3 moviendo el gate dentro de `dispatch()`, tocando
`router/dispatcher.py`, `skills/skill_manager.py`, `channels/telegram_bot.py` y los tests— no está
documentada. Y hasta esta auditoría, `REQ-005-context.md` seguía declarando OBS-2 y OBS-3
**ABIERTAS** cuando el código ya las había cerrado. Es un hueco de DoD de `orion-dev`
(`definition-of-done.md`: "desarrollo-log-XXX.md generado").

**Dictamen: NO es bloqueante. Y tampoco lo doy por subsanado escribiéndolo yo.**

Las tres razones, en orden:

1. **El hueco es documental, no funcional.** El código de la Iteración 4 no llegó sin verificar:
   `orion-tester` re-ejecutó los 13 criterios **desde cero** sobre esa versión —explícitamente sin
   dar por válidos los PASS anteriores, porque el gate había cambiado de lugar— más 8 reinyecciones
   de fallos para probar que ningún test crítico es vacuo. Yo verifiqué por mi cuenta los puntos que
   sostienen mi veredicto. Lo que falta es el relato del autor, no la evidencia.

2. **Devolverlo a `orion-dev` produciría un documento peor que el hueco.** Un dev-log de la
   Iteración 4 escrito hoy sería una reconstrucción retrospectiva armada a partir del informe de
   *otro* agente. Tendría la forma de un registro en primera persona sin la sustancia de uno. Para
   la traza de un REQ de SEGURIDAD, un hueco honesto acompañado de verificación independiente vale
   más que un relato plausible escrito después de los hechos.

3. **Pero no me corresponde a mí escribirlo.** No soy el implementador y no voy a redactar el
   registro de decisiones de alguien más: sería el mismo defecto, con mi firma. Lo que sí hago, y
   es lo que cierra el hueco a efectos de traza, es tres cosas concretas: (a) dejar acá constancia
   explícita de qué cambió la Iteración 4 y con qué evidencia quedó verificada; (b) **corregir el
   estado obsoleto de OBS-2/OBS-3 en `REQ-005-context.md`**, que es el error que activamente
   confunde; (c) dejar la redacción del dev-log como **deuda documental nombrada y obligatoria** de
   `orion-dev` — tarea de documentación pura, sin cambio de código y sin volver a entrar al pipeline
   de desarrollo/pruebas.

**Consecuencia práctica:** el REQ avanza a la prueba manual del humano. La deuda documental queda
registrada acá con nombre y responsable, no perdonada.

## 7. Condiciones y recomendaciones para REQs futuros

Ninguna bloquea REQ-005. Las ordeno por riesgo real, no por esfuerzo.

| # | Condición | Origen | Prioridad |
|---|---|---|---|
| C1 | **Autenticar `GET /audit` y bindear el servidor HTTP a `127.0.0.1` en vez de `0.0.0.0`** (`channels/api_channel.py:55-58, 107`) | Hallazgo propio 1.2 | 🔴 Alta |
| C2 | **Política de retención/purga en `audit_log`** — hoy crece sin límite, una fila por comando | Hallazgo propio 1.3 | 🟠 Media |
| C3 | **Test estructural que afirme el único llamador de `skill_manager.execute()`** | Dictamen 5.2 | 🟠 Media |
| C4 | **Eliminar el parámetro muerto `channel` de `shutdown_pc()`/`close_app()` y sus 3 argumentos** | Dictamen 5.4 | 🟠 Media |
| C5 | **Hacer `verify_pin()`/`require_pin()` fail-closed cuando no hay PIN configurado**, o marcarlas privadas | Observación 2.6 | 🟡 Baja (latente) |
| C6 | Acotar el `try/except` de `router/dispatcher.py:71-82` y decidir la semántica de reintento con efectos parciales | Dictamen 5.3 | 🟡 Baja |
| C7 | Extender el `parametrize` de `test_yellow_action_prompts_exactly_once_via_dispatch` a los 6 intents YELLOW (hoy cubre 2) | OBS-7 de `orion-tester` | 🟡 Baja |
| C8 | Agregar logging al `except Exception: return []` de `get_audit_log()` | Observación sección 3 | 🟡 Baja |
| C9 | Sanitizar `filename` contra path traversal en `write_file_direct()`/`save_file_desktop()` | `security-audit-005.md` H2 | 🟡 Baja |
| C10 | Proteger la degradación YELLOW→GREEN en `register_action()` (hoy solo RED está protegida) | Riesgo residual ya aceptado en SPEC | 🟡 Baja |

**Deuda documental nombrada (no es una condición técnica):** `orion-dev` debe agregar la sección
"Iteración 4" a `propuestas/desarrollo-log-005.md`. Tarea de documentación pura, sin cambio de
código y sin reingreso al pipeline de desarrollo/pruebas. Ver dictamen 6.

---

## Veredicto: ✅ APROBADO

REQ-005 cumple lo que se propuso y lo cumple donde importa: el bloqueo del nivel 🔴 Rojo dejó de
depender de que cada skill se autorregule y pasó a ser una decisión central, evaluada en el punto de
entrada de los 5 caminos de ejecución reales, antes de cualquier efecto.

Lo que verifiqué yo, no lo que me reportaron:

- **10 de 10 categorías Rojo** de `security-levels.md` registradas como `RiskLevel.RED` — exactamente
  10, ninguna faltante y ninguna espuria.
- **Fail-closed real en los dos ejes**: acción no clasificada → bloqueada; canal indeterminable
  (`None`, basura, `""`, `0`, `False`) → `UNKNOWN`, que solo admite Verde. Nunca cae a `DESKTOP`.
- **PIN maestro**: única vía de excepción Roja, solo en DESKTOP, bloqueada sin PIN configurado y
  bloqueada con PIN correcto en los otros 6 canales. Sin PIN hardcodeado, sin PIN en logs ni en
  `audit.db`, leído con `getpass`.
- **Reclasificación de una RED**: rechazada a GREEN y a YELLOW.
- **Las 3 condiciones obligatorias** de `security-audit-005.md`: implementadas, no solo declaradas.
- **Cero `except: pass` silencioso en el código nuevo** — el REQ agrega un único `except`, con
  `as e` y `logger.error()`, y de paso reemplaza un `print()` heredado por logging.
- **54/54 tests**, corrida propia.

Apruebo con un hallazgo que quiero dejar dicho sin suavizar, porque no aparece en ningún documento
previo del REQ: al mover el gate al punto de entrada de todos los caminos, `audit.db` dejó de ser un
log de eventos de seguridad y pasó a ser un **registro completo de la actividad del usuario con su
texto libre**, sin retención, servido por un endpoint HTTP **sin autenticación** en `0.0.0.0`. Los
tres componentes son pre-existentes por separado; lo que REQ-005 cambió es el valor de lo que hay
detrás de la puerta. No lo convierto en RECHAZO porque no es un bypass del deny-list —ninguna acción
se ejecuta de más y la frontera de autorización está intacta— pero es la condición C1 y no debería
quedar abierta mucho tiempo.

**Los dos dictámenes que dejo firmados:** el docstring de `SkillManager.execute()` es necesario pero
insuficiente y necesita un test estructural (C3); y los parámetros `channel` muertos de
`shutdown_pc()`/`close_app()` deben desaparecer, porque hoy hay tres call sites que cargan y
transportan el valor más crítico del sistema hacia una firma que lo ignora (C4).

El hueco de la Iteración 4 en `desarrollo-log-005.md` **no bloquea**: es documental, la evidencia
existe verificada de forma independiente, y reconstruirlo hoy produciría un relato en primera
persona sin sustancia. Queda como deuda nombrada de `orion-dev`, y corregí en
`REQ-005-context.md` el estado obsoleto de OBS-2/OBS-3, que era lo que activamente confundía.

**No se ejecutó `git commit`, `add`, `push`, `merge` ni `rebase`.** El REQ **no queda cerrado**:
pasa a la prueba manual del humano antes de entregar el mensaje de commit.
