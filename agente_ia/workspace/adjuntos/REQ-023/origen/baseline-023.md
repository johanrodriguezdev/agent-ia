# Baseline REQ-023 — Disparador proactivo por webhook externo

**Agente:** orion-baseline
**Fecha:** 2026-09-07
**Estado tracker de entrada:** SPEC_APROBADO → (este documento deja el REQ listo para `orion-architect`, estado de tracker pasa a EN_ARQUITECTURA)

> ⚠️ RECORDATORIO OBLIGATORIO (propagado desde `REQ-023-context.md` y `SPEC-023.md`, no
> generado por mí): la SPEC de este REQ se autoaprobó bajo la autorización nocturna en
> bloque del 2026-09-06, pero la **arquitectura NO puede autoaprobarse** bajo esa misma
> autorización. `orion-architect` debe dejar su propuesta pausada esperando revisión
> personal explícita de Johan (superficie de red nueva hacia su PC), sin excepción.
> `orion-security` sigue siendo obligatorio en el flujo, no opcional. Yo (orion-baseline)
> no tomo ninguna decisión de diseño en este documento — solo documento el estado actual.

## 1. Qué existe hoy en `core/proactive_engine.py`

Archivo completo leído línea por línea (167 líneas). Contiene:

- **`ProactiveTrigger`** (líneas 15-22): contenedor simple — `agent`, `schedule` (string
  libre), `action` (string), `user_id`, `last_fired`, `active`. No hay ningún campo hoy
  relacionado con autenticación, origen de red, ni identificador de webhook.
- **`ProactiveEngine`** (líneas 25-167):
  - `_triggers: List[ProactiveTrigger]` protegida por `RLock` (comentario explícito en
    línea 32-36 sobre por qué: un flujo puede registrarse en caliente mientras el loop
    itera).
  - `register_trigger(agent, schedule, action, user_id="default")` (línea 41-47): agrega
    un `ProactiveTrigger` a la lista. No valida el valor de `schedule` en el momento del
    registro — la validación de qué significa `schedule` ocurre después, en
    `_should_fire()`.
  - `unregister_trigger(agent_name)` (línea 49-61): da de baja todos los triggers de un
    agente por `agent.name`.
  - `triggers_activos()` (línea 63-66): copia de la lista para iterar sin bloquear.
  - `start()`/`stop()` (línea 68-78): arrancan/paran un hilo daemon (`_run_loop`).
  - `_run_loop()` (línea 89-99): duerme 15s al arrancar, luego cada `CHECK_INTERVAL = 60`
    segundos llama a `_check_triggers()` si `_global_active` es `True`.
  - **`_check_triggers()`** (línea 101-134) — el punto central de disparo:
    1. Itera una copia de los triggers.
    2. Salta los inactivos (`trigger.active == False`).
    3. Pregunta `_should_fire(trigger, now)` — evalúa el `schedule` contra la hora actual.
    4. Anti-rebote: si disparó hace menos de 300s, salta.
    5. **Gate de seguridad, línea 118:**
       ```python
       action_key = "proactive_trigger"
       if not security_manager.is_action_allowed(action_key, ChannelType.DESKTOP):
           logger.warning(f"Acción proactiva bloqueada por seguridad: {action_key}")
           continue
       ```
       **`ChannelType.DESKTOP` está hardcodeado.** No hay ningún parámetro de canal que
       fluya desde `ProactiveTrigger` hasta acá — todo trigger, sin importar cómo se
       registró o qué lo originó, se evalúa como si viniera del escritorio del propio
       Johan (el canal MÁS permisivo del sistema: `CHANNEL_ALLOWED_LEVELS[DESKTOP] =
       [GREEN, YELLOW]`). **Documento esto como hallazgo para `orion-architect`, no lo
       resuelvo yo:** un trigger `schedule="webhook"` que llegue a `_check_triggers()`
       por el mismo camino que hoy usan `startup`/`hourly`/`daily:HH:MM` heredaría ese
       mismo `ChannelType.DESKTOP` a menos que la arquitectura intercale explícitamente
       un canal distinto (p. ej. `ChannelType.EMAIL` o uno nuevo) en el punto de disparo
       específico del webhook. La SPEC (CA de "canal no confiable") ya exige esto; queda
       documentado aquí que el código actual NO lo hace por sí solo — hace falta un
       cambio deliberado en `_check_triggers()` o un camino de disparo separado que no
       reutilice esta línea tal cual.
    6. Si el gate pasa: ejecuta `trigger.agent.execute(trigger.action, {...})` en el
       mismo hilo del loop proactivo (síncrono, sin cola).
  - **`_should_fire()`** (línea 136-164): entiende exactamente 3 valores de `schedule`:
    `"startup"`, `"hourly"`, `"daily:HH:MM"` (con parseo `sched.split(":", 2)`). Cualquier
    otro valor de `schedule` (incluido un futuro `"webhook"` o `"webhook:<id>"`) cae en el
    `return False` final (línea 164) — **hoy un trigger `schedule="webhook"` registrado
    tal cual NUNCA se dispararía por el loop de polling**, porque `_should_fire()` no lo
    reconoce. Esto es coherente con la SPEC: el disparo de un trigger webhook no debe
    depender del polling de 60s del loop, sino de un camino de entrada distinto (el
    listener HTTP llamando directo a algo equivalente a lo que hace
    `_check_triggers()` para ese trigger puntual) — a diseñar en arquitectura.
  - No existe ningún socket, servidor HTTP, ni superficie de red en este archivo. El
    único mecanismo de entrada es la lista `_triggers` en memoria, poblada
    exclusivamente por llamadas Python directas a `register_trigger()`.

## 2. Quién usa `proactive_engine` hoy — registro de triggers

Grep de `proactive_engine|register_trigger` en todo el repo: 35 archivos, de los cuales
los relevantes para el mecanismo de registro (no solo lo referencian, lo llaman) son:

- **`main.py`** (arranque de la app de escritorio):
  - Línea 113: `proactive_engine.set_notify_callback(_avisar_proactivo)`.
  - Línea 175: `proactive_engine.register_trigger(_EmailWatcher(), _horario, "revisar
    correo")` — horario configurable vía `config.json` → `email.check_schedule`
    (default `"hourly"`), condicionado a que `_email_reader.esta_configurado()`.
  - Líneas 195-197: tres triggers fijos de `_proactive_assistant`
    (`_ProactiveAssistant`, clase local en `main.py`) con `schedule` `"startup"`,
    `"hourly"`, `"daily:08:00"`.
  - Línea 208: `proactive_engine.start()` — arranca el hilo del loop.
  - Línea 222: `proactive_engine.stop()` al salir de la app.
  - **Todo este registro ocurre en proceso, en el arranque de `main.py`, con objetos
    Python (`agent` con método `.execute()`) construidos localmente.** No hay ningún
    punto en `main.py` que reciba una entrada de red o de un canal externo para
    registrar o disparar un trigger.

- **`core/flows.py`** (líneas 611-643, sección "Programación"):
  - `programar(flujo)`: da de baja el trigger viejo del flujo
    (`unregister_trigger(nombre_de_agente(flujo.id))`) y registra uno nuevo con
    `proactive_engine.register_trigger(EjecutorProgramado(flujo.id, flujo.user_id),
    flujo.horario, f"flujo {flujo.nombre}", user_id=flujo.user_id)`. `flujo.horario` es
    un string libre guardado en la tabla `flujos` de `flows.db` — hoy solo se le da
    sentido en `_should_fire()` (los 3 formatos ya descritos).
  - `desprogramar(flujo_id)`: da de baja.
  - `programar_todos(user_id)`: reprograma todos los flujos con horario al arrancar.
  - **`EjecutorProgramado`** (línea 565-590): el adaptador entre un flujo y el motor
    proactivo. Su `.execute()` llama a `ejecutar(self._flujo_id, canal=ChannelType.UNKNOWN,
    ...)` — nótese que ACÁ SÍ se usa un canal explícito y restrictivo
    (`ChannelType.UNKNOWN`, solo GREEN permitido) para el gate INTERNO de cada paso del
    flujo (vía `agents/action_registry.execute_action()` dentro de `ejecutar()`), un gate
    completamente separado y posterior al de `_check_triggers()` en
    `proactive_engine.py` (que sigue usando `ChannelType.DESKTOP` para la capa
    `"proactive_trigger"` en sí). Es decir: hoy hay DOS gates en cascada para un flujo
    programado — uno genérico y permisivo (`proactive_trigger` @ DESKTOP, en
    `proactive_engine`) y uno específico y restrictivo por paso (`ChannelType.UNKNOWN`,
    en `flows.ejecutar()`). Un trigger webhook que dispare un flujo heredaría el primero
    tal cual está hoy, y el segundo ya está bien diseñado como patrón a imitar.

- **`skills/flow_skill.py`**:
  - `extraer_horario(texto)` (línea 101+): parsea del texto libre del usuario una
    expresión de horario en español ("todos los días a las 16:00", etc.) y la traduce a
    uno de los 3 formatos que entiende `_should_fire()`. Es la única fuente de `horario`
    que un usuario puede escribir a mano hoy; no reconoce ni genera ningún literal tipo
    `"webhook"`.
  - Líneas 318, 328, 334, 337: usa `flujo.horario` para decidir el mensaje de
    confirmación al usuario ("Ya quedó programado...").

- **Conclusión de esta sección: hoy el proceso es 100% interno.** No existe ningún
  camino, ni directo ni indirecto, por el cual algo externo al proceso Python de la app
  (una petición de red, un proceso separado, otra máquina) pueda registrar o disparar un
  `ProactiveTrigger`. Todo registro ocurre por llamada de función en el mismo proceso, en
  el arranque (`main.py`) o al crear/programar un flujo (`core/flows.py`,
  `skills/flow_skill.py`). El webhook de REQ-023 sería el primer punto de entrada externo
  de todo el sistema proactivo.

## 3. `core/security_manager.py` — `ChannelType` y comentarios sobre webhooks

`ChannelType` (líneas 59-69) tiene hoy exactamente estos valores:

```python
class ChannelType(Enum):
    DESKTOP = "desktop"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    VOICE = "voice"
    API = "api"
    EMAIL = "email"
    UNKNOWN = "unknown"
```

No existe hoy ningún `ChannelType.WEBHOOK` ni equivalente. El comentario que precede a
`EMAIL` (líneas 65-67, cita textual):

> ```
> # Canal de entrada NO CONFIABLE: correo, webhooks, cualquier texto que un tercero
> # pueda originar sin ser un usuario autorizado. Existe para que ese contenido tenga
> # dónde entrar sin llegar nunca al agente que controla el PC. Ver CHANNEL_ALLOWED_LEVELS.
> ```

`CHANNEL_ALLOWED_LEVELS` (líneas 72-98). Cita textual completa del bloque de comentario
sobre `EMAIL` (líneas 78-96), que es donde el código ya anticipa explícitamente el caso
de los webhooks:

> ```
> # EMAIL es el único canal con lista VACÍA, y es deliberado: ni siquiera verde.
> #
> # El resto de los canales los origina un usuario autorizado; el correo (y a futuro los
> # webhooks) los origina cualquiera del planeta. Un texto atacante que llegue acá no
> # puede disparar NINGUNA acción, ni las verdes: `open_app` y `play_media` son verdes y
> # bastarían para abrir una URL elegida por el atacante, y `recall_memory` para sacar
> # información personal por un resumen. El canal sirve para LEER y RESUMIR — producir
> # texto, no ejecutar.
> #
> # Es la traducción del `tools: {profile: "minimal"}` con que OpenClaw aísla su lector
> # de correo (openclaw-main/docs/automation/imap.md). Si algún día una acción concreta
> # tiene que habilitarse acá, va de a una por CHANNEL_ACTION_EXCEPTIONS —
> # `is_action_allowed()` evalúa esa tabla ANTES que esta, así que la lista vacía no
> # impide la excepción quirúrgica; obliga a justificarla caso por caso.
> #
> # Adicionalmente NO se registra adaptador de confirmación para EMAIL
> # (`core/confirmation.py`): sin adaptador, todo YELLOW se deniega por fail-closed. La
> # restricción no está escrita en ningún lado — es que no hay a quién preguntarle.
> ChannelType.EMAIL: [],
> ```

Estado efectivo hoy de `CHANNEL_ALLOWED_LEVELS`:

| Canal | Niveles permitidos |
|---|---|
| DESKTOP | GREEN, YELLOW |
| TELEGRAM | GREEN (+ excepciones puntuales via `CHANNEL_ACTION_EXCEPTIONS`) |
| DISCORD | GREEN |
| VOICE | GREEN |
| API | GREEN |
| **EMAIL** | **[] — vacío, nada, ni verde** |
| UNKNOWN | GREEN |

`CHANNEL_ACTION_EXCEPTIONS` (líneas 107-124) solo tiene hoy 4 entradas, todas para
`ChannelType.TELEGRAM` (`delete_task`, `pc_type`, `pc_key`, `pc_click`). Ninguna para
`EMAIL` ni para ningún canal hipotético de webhook.

`_CHANNEL_STR_MAP` (línea 126-134) — el mapeo string→`ChannelType` usado por
`resolve_channel()` — tampoco tiene ninguna entrada para `"webhook"` hoy; un string
`"webhook"` pasado a `resolve_channel()` caería en `ChannelType.UNKNOWN` (GREEN-only) por
el comportamiento fail-safe ya documentado en la línea 313 de `resolve_channel()`.

`security_manager.is_action_allowed("proactive_trigger", ChannelType.DESKTOP)` (usado
hoy en `proactive_engine._check_triggers()` línea 118) evalúa contra la clasificación
`"proactive_trigger": RiskLevel.GREEN` (registrada en `_register_default_actions()`,
línea 581 de `security_manager.py`). Como GREEN está en `CHANNEL_ALLOWED_LEVELS[DESKTOP]`,
hoy esa llamada siempre pasa — el gate real de cada acción concreta ocurre más abajo,
adentro de `trigger.agent.execute()` (en el caso de un flujo, dentro de
`flows.ejecutar()` → `action_registry.execute_action()`, con su propio canal).

**No hay `require_confirmation()` en el camino de `_check_triggers()`** — solo
`is_action_allowed()` (que no pide confirmación, solo consulta la política de canal).
Esto es coherente con que hoy todo trigger proactivo es interno y ya fue "aprobado" al
registrarse (p. ej. el usuario tecleó el flujo). Para un trigger `webhook`, la SPEC exige
que la ACCIÓN subyacente pase por el mismo gate verde/amarillo/rojo con un canal no
confiable — eso ya lo hace `flows.ejecutar()` (usa `ChannelType.UNKNOWN` internamente
para cada paso), así que reusar ese camino en vez de inventar uno nuevo parece la opción
de menor riesgo, pero **esto es una observación, no una decisión** — corresponde a
`orion-architect`.

## 4. Listener HTTP / servidor de red existente en el proyecto

Búsqueda con grep (case-insensitive) de `http\.server|BaseHTTPRequestHandler|flask|
fastapi|Flask|FastAPI|socketserver|aiohttp|uvicorn|werkzeug` en todo el repo (excluyendo
carpetas de terceros/vendorizadas por defecto de la búsqueda):

- **`core/mcp_oauth.py`** es el ÚNICO archivo del proyecto con un servidor HTTP real
  hoy. Detalle (líneas citadas):
  - Línea 41: `from http.server import BaseHTTPRequestHandler, HTTPServer` (stdlib, sin
    dependencia nueva).
  - Línea 254: `class _RecolectorDeCodigo(BaseHTTPRequestHandler):` — maneja
    `do_GET()` (línea 257).
  - Línea 276 (comentario): silencia el log a stderr de `http.server` para no romper la
    consola — patrón reusable.
  - Línea 287: `servidor = HTTPServer(("127.0.0.1", PUERTO_REDIRECCION),
    _RecolectorDeCodigo)` — **bind explícito a `127.0.0.1`**, ya el mismo criterio que
    exige la SPEC de REQ-023 para el bind por defecto.
  - **Naturaleza distinta:** este listener es para el flujo de callback OAuth (recibir
    el código de autorización que un navegador redirige de vuelta al proceso local
    después de que el USUARIO inició el login) — es de corta vida, arranca bajo demanda,
    y no ejecuta ninguna acción del agente; solo captura un parámetro de la URL y se
    apaga. No es un servidor persistente a lo largo de toda la vida de la app, ni acepta
    peticiones de terceros no iniciadas por el propio usuario. Sirve como **precedente
    de patrón** (stdlib `http.server`, bind localhost) pero no como código a extender
    directamente — la SPEC ya lo señala así.
  - `workspace/adjuntos/REQ-023/spec/SPEC-023.md` (línea 69, ya en el módulo nuevo
    propuesto) también cita este archivo como precedente a evaluar, sin prescribir la
    librería.

- **No se encontró** ningún uso de `flask`, `fastapi`, `aiohttp`, `uvicorn`, `werkzeug`
  ni `socketserver` en ningún archivo del proyecto (fuera de la mención textual dentro
  de `SPEC-023.md`, que es la propia spec citándose).

## 5. `requirements.txt` — librerías HTTP ya presentes

Leído completo (118 líneas). No declara `flask`, `fastapi`, `aiohttp`, `uvicorn`, ni
ningún framework de servidor HTTP. Las únicas dependencias relacionadas con red/HTTP que
sí están declaradas son de CLIENTE, no de servidor: `openai` (SDK, líneas 51-57, usado
para los proveedores DeepSeek/OpenRouter/OpenAI vía API compatible), `wikipedia`,
`ddgs` (búsqueda web, línea 94), `google-generativeai` (línea 100). Ninguna sirve para
levantar un listener entrante.

**Conclusión: si `orion-architect` elige `http.server` (stdlib) siguiendo el precedente
de `core/mcp_oauth.py`, no hace falta agregar ninguna dependencia nueva a
`requirements.txt`.** Si en cambio elige un framework externo (Flask/FastAPI/etc.), sí
sería una dependencia nueva a declarar y justificar — la SPEC ya deja esto abierto a
decisión de arquitectura sin prescribir.

## 6. `config.json` / `config_manager.py` — cómo se leen/escriben flags booleanos hoy

`config_manager.py` (leído completo, 455 líneas) usa un patrón consistente y repetido
para cada flag de configuración:

- `load_config()` (línea 47-73): lee `config.json`, rellena claves faltantes con
  default, devuelve SIEMPRE una copia (no el dict compartido — bug corregido en REQ-008,
  documentado en el propio comentario de la función).
- `save_config(config)` (línea 76-83): sobreescribe el archivo completo con
  `json.dump(..., indent=4, ensure_ascii=False)`.
- **Patrón para un booleano de opt-in/opt-out ya existente y directamente reusable —
  `get_telegram_autostart()` / `set_telegram_autostart()` (líneas 194-212):**
  ```python
  def get_telegram_autostart() -> bool:
      valor = load_config().get("telegram_autostart", True)
      return valor is not False

  def set_telegram_autostart(activo: bool) -> None:
      config = load_config()
      config["telegram_autostart"] = bool(activo)
      save_config(config)
  ```
  Nótese que este caso concreto por defecto es "encendido" (`True`) — lo opuesto de lo
  que pide la restricción de diseño de REQ-023 ("apagado por defecto"). Para el webhook,
  el mismo patrón aplicaría invertido: `load_config().get("webhook_enabled", False)` con
  fail-safe también hacia `False` ante cualquier valor que no sea exactamente `True`
  (fail-closed, coherente con el resto de las reglas de seguridad del proyecto — a
  diferencia de Telegram, que es fail-open a propósito porque ya está acotado por canal).
- **Credenciales/secretos:** el proyecto ya tiene un mecanismo separado y establecido
  para esto — `_ENV_KEY_MAP` (líneas 26-34) mapea una clave lógica (p. ej.
  `"telegram_token"`) a una variable de entorno (`"TELEGRAM_BOT_TOKEN"`), y
  `_get_config_value()` (línea 86-93) siempre prioriza la variable de entorno sobre lo
  guardado en `config.json`. `origen_de_credencial()` (línea 219-231) permite reportar
  al usuario de dónde sale cada credencial. Este es el mecanismo que la SPEC ya asume
  para el secreto HMAC del webhook ("nunca hardcodeado ni en texto plano en
  config.json" — Asumidos, SPEC-023.md línea 144-146): agregar una entrada nueva a
  `_ENV_KEY_MAP` (p. ej. `"webhook_secret": "ORION_WEBHOOK_SECRET"`) seguiría el mismo
  patrón que ya usan Telegram, Discord, y las 5 API keys de proveedores IA.
- **`config.json` actual** (leído completo, 22 líneas) no tiene ninguna clave relacionada
  con webhook, proactividad, ni bind de red. Solo tiene: `agent_name`,
  `agent_pronunciation`, `display_name`, `user_title`, `weather_city`, `ui_theme`,
  `deepseek_api_key` (en texto plano — preexistente, no introducido por este REQ),
  `task_providers`, `window_geometry`.

## 7. Compilación y pytest — estado pre-existente

### `python -m py_compile`

Ejecutado sobre los módulos afectados según SPEC-023 y este baseline:
```
core/proactive_engine.py core/security_manager.py core/flows.py
skills/flow_skill.py config_manager.py main.py core/mcp_oauth.py
```
**Resultado: `COMPILE_OK`, sin errores de sintaxis en ninguno.**

### `pytest tests/ --tb=line -q` (suite completa, 2026-09-06 21:35 aprox.)

**Resultado: `2 failed, 1761 passed, 11 warnings in 86.58s`.**

| Test | Veredicto | Motivo |
|---|---|---|
| `tests/test_task_slots.py::test_la_hora_dicha_se_respeta` | Pre-existente, no relacionado a REQ-023 | Depende de la fecha del sistema (`datetime.date.today()`) — falla comparando `2026-09-07` (hora del test) contra `2026-09-06` (fecha "de hoy" capturada en otro momento). Es el mismo fallo pre-existente ya conocido y documentado en instrucciones previas de baseline de otros REQs de esta sesión (dependiente de la hora del día). |
| `tests/test_webview_buttons.py::test_el_selector_de_modelo_muestra_el_activo_y_lo_cambia` | **Ruido concurrente, NO relacionado a REQ-023** — ver verificación abajo | Falla `assert 0 > 1` sobre `document.querySelectorAll('.model-option').length`, en un test de `ui/webview/bridge.py`. |

**Verificación de la segunda falla contra trabajo concurrente:** `git status --porcelain
-uall` en el momento de este baseline muestra `ui/webview/bridge.py` y
`tests/test_webview_buttons.py` como **modificados sin commitear** (`M`), junto con
`ai/claude_brain.py`, `ai/llm_provider.py`, `core/reasoning_loop.py`, `ui/tts_engine.py`
— exactamente el conjunto de archivos que las instrucciones de esta tarea señalan como
en trabajo activo por el agente `orion-dev` de REQ-022 en paralelo (evidencia adicional:
existen ya `workspace/adjuntos/REQ-022/{REQ-022-context.md, origen/, propuestas/,
spec/}` sin commitear). **Conclusión: esta segunda falla es trabajo de REQ-022 a medio
terminar, no un fallo pre-existente estable ni algo introducido por REQ-023** (REQ-023
no tocó ningún archivo todavía — este baseline es puramente de lectura). No se cuenta
como baseline "limpio" de REQ-023 porque es transitorio: cuando REQ-022 termine su ciclo
dev→tester, debería desaparecer. `orion-architect`/`orion-dev` de REQ-023 no deberían
tocar `ui/webview/bridge.py` de todos modos (fuera del alcance de sus módulos afectados
según SPEC-023), así que no hay solapamiento de archivos entre ambos REQs.

**Comparación contra el baseline histórico conocido** (~1762 passed / 1 failed, el 1
failed siendo `test_la_hora_dicha_se_respeta`): el conteo total de tests
(1761+2=1763 aprox., leve variación esperable por tests parametrizados/nuevos de otros
REQs recientes) es consistente; el único fallo NUEVO respecto del histórico es el de
`test_webview_buttons.py`, y queda explicado arriba como ruido de REQ-022 concurrente,
no como algo que REQ-023 deba investigar ni heredar como "pre-existente propio".

## 8. Archivos que serán modificados por este REQ (según SPEC-023 §"Módulos afectados",
confirmado por lectura directa en este baseline)

- `core/proactive_engine.py` — nuevo tipo de disparador `webhook` en `ProactiveTrigger`/
  `_should_fire()`, y resolución del hallazgo de `ChannelType.DESKTOP` hardcodeado en
  `_check_triggers()` línea 118 (documentado arriba, §1).
- `core/security_manager.py` — posible `ChannelType` nuevo o reuso de `ChannelType.EMAIL`
  en `CHANNEL_ALLOWED_LEVELS`; posible entrada en `_CHANNEL_STR_MAP`.
- `core/flows.py` / `skills/flow_skill.py` — si el registro de un flujo con disparador
  `webhook` reusa el mecanismo declarativo de `horario` que hoy alimenta `schedule`.
- `config.json` (datos) / `config_manager.py` (código) — nueva sección/flag de opt-in
  para el listener, siguiendo el patrón `get_telegram_autostart()`/
  `set_telegram_autostart()` ya existente (invertido a fail-closed); posible entrada
  nueva en `_ENV_KEY_MAP` para el secreto HMAC.
- Módulo nuevo (nombre a definir en arquitectura, ej. `core/webhook_listener.py`) — el
  servidor HTTP en sí. `core/mcp_oauth.py` (líneas 41, 254-287) es el precedente de
  patrón (stdlib `http.server`, bind `127.0.0.1`), no código a extender directamente.
- `requirements.txt` — solo si arquitectura elige un framework externo en vez de stdlib
  `http.server`; con stdlib no hace falta tocarlo.
- `main.py` — punto de arranque/apagado del listener nuevo, siguiendo el patrón ya
  existente de `proactive_engine.start()`/`.stop()` (líneas 208, 222).

## 9. Resumen para `orion-architect`

- El sistema proactivo hoy es 100% interno; el webhook sería el primer punto de entrada
  externo de todo O.R.I.O.N.
- El gate de seguridad de `_check_triggers()` usa `ChannelType.DESKTOP` hardcodeado
  (línea 118) — hay que decidir explícitamente cómo el camino de disparo por webhook
  evita heredar ese canal permisivo, sin tocar el comportamiento de los triggers por
  horario existentes.
- `_should_fire()` no reconoce ningún `schedule` fuera de los 3 formatos actuales — un
  trigger `webhook` necesita su propio camino de disparo, no encajar en el loop de
  polling de 60s (o si encaja, `_should_fire()` necesita una rama nueva que
  deliberadamente nunca dispare por sí sola vía polling).
- `flows.ejecutar()` con `ChannelType.UNKNOWN` ya es un patrón vivo de "canal
  restrictivo para disparo automático" — evaluar si conviene el mismo criterio o algo
  aún más restrictivo (`ChannelType.EMAIL`, lista vacía) para el webhook, tal como pide
  la SPEC.
- `core/mcp_oauth.py` es precedente de implementación (stdlib, bind localhost) sin ser
  código a reusar directamente — es un listener de corta vida para OAuth, no uno
  persistente para acciones del agente.
- `config_manager.py` ya tiene el patrón exacto de flag opt-in/opt-out y de secreto vía
  variable de entorno — replicarlo, no reinventar.
- No hace falta ninguna dependencia nueva en `requirements.txt` si se sigue el
  precedente stdlib.
- Los dos fallos de pytest de esta suite (`test_la_hora_dicha_se_respeta`,
  `test_el_selector_de_modelo_muestra_el_activo_y_lo_cambia`) son ajenos a REQ-023 (el
  primero pre-existente por dependencia horaria, el segundo ruido de REQ-022 en curso) —
  no son parte del estado "roto por este REQ" ni hace falta arreglarlos en este flujo.

## DoD de `orion-baseline` — verificación

```
[x] Estado actual del sistema documentado (qué existe hoy, antes del cambio)
[x] Archivos que serán modificados listados
[x] Fallos pre-existentes registrados (pytest o compilación)
[x] Contexto actualizado (ver REQ-023-context.md, entrada 2026-09-07 orion-baseline)
```
