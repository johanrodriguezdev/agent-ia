# Auditoría de seguridad REQ-018 — Confirmación conversacional para `/eliminar` en Telegram

**Estado:** ✅ APROBADO tras re-chequeo (2026-08-20) — el veredicto original de este documento
(❌ REQUIERE CAMBIOS, más abajo, sin modificar) quedó resuelto por el fix de Hallazgo A aplicado en
`arquitectura-018.md` §15. Ver sección "Re-chequeo (2026-08-20)" al final de este archivo para el
veredicto vigente y 1 hallazgo nuevo no bloqueante (E) encontrado durante el re-chequeo. El cuerpo
original de la auditoría (Resumen ejecutivo, Hallazgos A-D, Veredicto original) se conserva sin
cambios como registro histórico.
**Agente:** orion-security
**Fecha:** 2026-08-20 (auditoría original) / 2026-08-20 (re-chequeo)
**Entrada auditada:** `workspace/adjuntos/REQ-018/propuestas/arquitectura-018.md` (964 líneas, ✅
APROBADA por Johan) + `SPEC-018.md` (14 CA) + `origen/baseline-018.md` + `REQ-018-context.md`
completo + código real de `core/security_manager.py`, `channels/telegram_bot.py` (líneas
416-528, 773-841), `core/confirmation.py`, y verificación directa del paquete instalado
`python-telegram-bot==20.7` (`telegram/ext/_application.py`, `telegram/ext/_baseupdateprocessor.py`,
`telegram/ext/_applicationbuilder.py`). También se leyó `workspace/adjuntos/REQ-019/` completo
(context + arquitectura-019.md) para verificar el punto 1 del encargo (cruce con el mecanismo de
override de configuración que REQ-019 diseña en paralelo).

## Resumen ejecutivo

El diseño central de este REQ es sólido en tres de los cuatro focos de riesgo que introduce: el
mecanismo de excepción granular `CHANNEL_ACTION_EXCEPTIONS` (CA-02) es una tabla estática en
código, aditiva, sin ninguna vía de influencia por input de usuario ni cruce con el mecanismo de
override que `REQ-019` está diseñando en paralelo (son dos estructuras de datos completamente
distintas, verificado punto por punto — ver Hallazgo D, verificado sin hallazgo). La correlación
usuario↔confirmación (CA-05, CA-09) se hace estrictamente por `user_id` obtenido de
`update.effective_user`/`update.effective_chat` (fuente confiable de la API de Telegram, no de
texto libre parseado) — no hay vector de que un usuario reciba o influya la respuesta de otro. La
auditoría (CA-14) reutiliza `_log_audit()` sin tabla paralela.

Sin embargo, la auditoría encontró **un hallazgo bloqueante que invalida la premisa central de
CA-08** ("no bloquea el loop de `asyncio` para otros usuarios") — verificado directamente contra
el código fuente del paquete `python-telegram-bot==20.7` instalado, no solo contra el razonamiento
de la propuesta — y dos hallazgos no bloqueantes pero de corrección obligatoria antes de que
`orion-tester` pueda declarar CA-07/CA-08/CA-09/CA-14 y CA-03 verdaderamente cubiertos. Ninguno de
los tres exige rediseñar el mecanismo de excepción (CA-02) ni el patrón general del adaptador —
son correcciones acotadas sobre el mismo diseño ya aprobado, en la línea de lo que
`security-audit-015.md` resolvió con sus Hallazgos A/C (cambio real, pero no un rediseño).

## Clasificación de riesgos implementados

| Punto auditado | Nivel | ¿Confirmación? | Estado |
|---|---|---|---|
| 1. `CHANNEL_ACTION_EXCEPTIONS` — tabla estática, sin input de usuario, sin cruce con REQ-019 | 🟡 Amarillo (mecanismo de gate) | No aplica — es código, no dato de usuario | ✅ verificado, sin hallazgo |
| 1b. `user_id`/`chat_id` del flujo nuevo vienen de `update.effective_user`/`update.effective_chat` | 🟡 Amarillo | No aplica | ✅ verificado contra §5.1, §6.1, §6.3 |
| 2. Fail-closed del timeout bajo condiciones de carrera (`_pending`, `threading.Event`+`Lock`) | 🟡 Amarillo | Sí, con timeout 120s | ⚠️ diseño base correcto para la carrera timeout↔respuesta, pero **falta manejo de excepción en el envío del mensaje** — ver Hallazgo B |
| 3. CA-03 — regresión de las 19 YELLOW restantes | 🟢 Verde (test de regresión) | No aplica | ❌ REQUIERE CAMBIO — ver Hallazgo C (lista hardcodeada, no derivada del registro real) |
| 4. Correlación cruzada entre usuarios en `_intercept_confirmacion_pendiente`/`resolve()` | 🟡 Amarillo | No aplica — correlación, no confirmación | ✅ verificado, sin hallazgo — clave siempre `str(update.effective_user.id)` |
| 5. Auditoría (CA-14) — mismo `_log_audit()`, sin tabla paralela | 🟢 Verde | No aplica | ✅ verificado, con la salvedad de que el Hallazgo B también deja sin auditar su propio camino de excepción |
| 6a. Secretos — token de Telegram | 🟢 Verde | No aplica | ✅ vía `config_manager.get_telegram_token()`, sin cambios de este REQ, sin hardcodeo |
| 6b. `except: pass` silencioso en código nuevo diseñado | 🟢 Verde | No aplica | ✅ sin hallazgos — todos los `except Exception as e` capturados en el diseño registran `logger.error`/`logger.warning` |
| 6c. Validación de inputs (`task_id`, tokens de confirmación) | 🟢 Verde | No aplica | ✅ `int(context.args[0])` con `try/except ValueError`; criterio de "sí" es allowlist exacta (CA-06) |
| 7. **CA-08 — "no bloquea el loop para otros usuarios"** | 🔴 Rojo (invalida un CA explícito y testeado) | — | ❌ **REQUIERE CAMBIO — ver Hallazgo A, bloqueante** |

## Hallazgo A (bloqueante) — `Application.builder()` no habilita `concurrent_updates`: CA-08 no se cumple, y el bot completo queda bloqueado para TODOS los usuarios mientras hay una confirmación pendiente

La arquitectura (§4.3, §5.1, §7.1, §10) argumenta que `cmd_eliminar()` invoca
`security_manager.require_confirmation()` vía `await asyncio.to_thread(...)` precisamente para que
el hilo del event loop de `python-telegram-bot` **no** se bloquee mientras espera hasta 120s la
respuesta del usuario — y que por eso "otros usuarios del bot pueden seguir interactuando con
normalidad" (CA-08). Ese razonamiento es correcto **en el nivel del hilo del sistema operativo**:
`asyncio.to_thread()` efectivamente delega el bloqueo síncrono a un hilo del executor, sin
congelar el event loop.

Pero no es suficiente, y verificado directamente contra el código fuente instalado de
`python-telegram-bot==20.7` (no contra el razonamiento de la propuesta), el resultado observable
es el opuesto al que exige CA-08:

- `channels/telegram_bot.py:804` (código real actual) y el snippet de la propuesta (§4.3)
  construyen la `Application` así: `Application.builder().token(token).post_init(...).build()` —
  **sin llamar `.concurrent_updates(...)` en ningún punto del diseño** (grep exhaustivo sobre
  `arquitectura-018.md`, `baseline-018.md`, `REQ-018-context.md`: cero resultados de
  `concurrent_updates`).
- `telegram/ext/_applicationbuilder.py:214-215` — sin esa llamada, el builder usa el valor por
  defecto: `self._update_processor = SimpleUpdateProcessor(max_concurrent_updates=1)`.
- `telegram/ext/_application.py:1145-1170` (`_update_fetcher()`, el único consumidor de
  `self.update_queue`) — con `max_concurrent_updates == 1`, la rama ejecutada es
  `else: await self.__process_update_wrapper(update)` (línea 1170), **no**
  `self.create_task(...)` (línea 1164-1168, solo si `max_concurrent_updates > 1`). Es decir, el
  propio bucle que fetchea updates de la cola interna es **un único `asyncio.Task`** que espera
  (`await`) a que cada update termine de procesarse por completo — incluidos todos sus `await`
  internos — antes de poder tomar el siguiente update de la cola.
- `telegram/ext/_baseupdateprocessor.py:154-176`
  (`SimpleUpdateProcessor.do_process_update()`, docstring textual: *"Instance... that immediately
  awaits the coroutine, i.e. does not apply any additional processing"*) — confirma que no hay
  ningún mecanismo adicional de paralelismo por debajo; `await coroutine` es literal y directo.

**Consecuencia real:** mientras `cmd_eliminar()` de un usuario A está suspendido dentro de
`await asyncio.to_thread(require_confirmation, ...)` (hasta 120s, CA-07), el propio
`_update_fetcher()` — que es quien debe leer el próximo update de la cola y despacharlo a
cualquier handler, para cualquier usuario — está también suspendido en ese mismo `await`
(la suspensión se propaga hacia arriba por toda la cadena de corutinas: `cmd_eliminar()` →
`process_update()` → `__process_update_wrapper()` → `_update_fetcher()`, todo dentro de la misma
Task). Los mensajes de un usuario B **sí siguen llegando** de Telegram y quedan encolados en
`self.update_queue` (el fetcher de red es un mecanismo aparte), pero **no se despachan a ningún
handler hasta que termine el procesamiento completo del update de A** — es decir, hasta que la
confirmación de A se resuelva (por respuesta o por los 120s de timeout).

Esto es exactamente lo opuesto a lo que exige CA-08 ("otros usuarios del bot pueden seguir
interactuando con normalidad... sin demora perceptible"). El "puente async→sync" mueve
correctamente el bloqueo del hilo del SO a un hilo worker, pero **no mueve el bloqueo del
dispatcher de updates de PTB**, que sigue siendo estrictamente secuencial por configuración por
defecto. El resultado no es "sin demora perceptible" — es una demora de **hasta 120 segundos para
absolutamente todos los usuarios del bot**, cada vez que cualquiera de ellos (a propósito o por
descuido) deja una confirmación de `/eliminar` sin responder.

**Implicación de seguridad, no solo de rendimiento:** esto convierte el propio mecanismo que
cierra el bypass de seguridad en un vector de denegación de servicio trivial y no privilegiado —
cualquier usuario de Telegram con acceso al bot puede escribir `/eliminar 1` y no responder nada,
bloqueando el bot completo para todos los demás usuarios durante 120 segundos, repetible sin
límite (CA-09 impide que el MISMO usuario apile una segunda confirmación propia, pero no impide
que, tras el timeout de la primera, dispare inmediatamente una segunda ronda de bloqueo global).
No hace falta ningún privilegio ni conocimiento técnico — es el uso normal del comando que este
mismo REQ habilita.

**Por qué el test de CA-08 propuesto en §11 no lo habría detectado:** el test sugerido
(*"`confirm()` ejecutado en un hilo real (`threading.Thread`) mientras el hilo de test sigue
respondiendo — verificar que el hilo de test nunca se bloquea"*) prueba el adaptador
`TelegramConfirmationAdapter.confirm()` **aislado**, con un `threading.Thread` genérico — nunca
instancia una `Application` real de `python-telegram-bot` ni verifica su configuración de
`concurrent_updates`. Es una prueba válida de que el hilo worker no bloquea al hilo que lo llama,
pero no ejerce en absoluto el punto donde vive el bug real (la configuración del `Application` en
`run_telegram_bot()`). Da falsa confianza sobre CA-08.

**Corrección requerida (acotada, no cambia el resto del diseño):**
1. `Application.builder().token(token).concurrent_updates(True).post_init(...).build()` (o un
   entero explícito, p. ej. `.concurrent_updates(8)`, si se prefiere acotar el paralelismo) dentro
   de `run_telegram_bot()` — un cambio de una línea, pero indispensable para que CA-08 sea cierto.
2. Con `concurrent_updates` habilitado, `telegram/ext/_application.py:1162-1168` pasa a despachar
   cada update como una `asyncio.Task` independiente (`self.create_task(...)`) — en ese régimen,
   la premisa de aislamiento por `contextvars.ContextVar` que usa `set_request_context()`/
   `_request_ctx` (§5.1) **sí** empieza a ser necesaria de verdad (cada Task copia su propio
   contexto al crearse, vía `contextvars.copy_context()` interno de `asyncio.create_task()`) — el
   diseño de `contextvars` en sí es correcto, pero hasta corregir este hallazgo estaba protegiendo
   contra una concurrencia que, tal como está construido el `Application`, nunca llegaba a ocurrir.
3. Revisitar §10 ("Agotamiento del thread pool por defecto de `asyncio.to_thread()`") una vez
   aplicado el fix — el riesgo ahí documentado pasa de ser hipotético a real (con concurrencia
   habilitada, múltiples `/eliminar` simultáneos sí retienen hilos del executor en paralelo). La
   mitigación que ya propone la arquitectura (pool por defecto de Python,
   `min(32, os.cpu_count() + 4)`, suficiente para el volumen esperado) sigue siendo razonable — no
   hace falta más que confirmarla explícitamente contra el escenario real.
4. Agregar al menos un test de integración (no solo el test aislado del adaptador) que construya
   una `Application` real con la configuración de `run_telegram_bot()` y verifique
   `app.concurrent_updates > 1` (o equivalente), para que una regresión futura de este mismo punto
   (alguien quita `.concurrent_updates(...)` sin darse cuenta de por qué estaba) se detecte en CI,
   no solo se documente en un comentario.

## Hallazgo B (no bloqueante, corrección obligatoria para `orion-dev`) — `confirm()` no garantiza limpieza de `_pending` ni resultado `False` si `_send_message()` falla al *programar* el envío

El diseño de la carrera timeout↔respuesta (`threading.Event` + `threading.Lock` sobre `_pending`)
está bien resuelto: `Event.wait(timeout)`/`Event.set()` usan un `Condition` interno con su propio
lock, así que no hay una ventana real de ambigüedad entre "expiró" y "llegó la respuesta" —
exactamente uno de los dos caminos gana la carrera por el candado (`self._lock`) que protege
`_pending`, y el otro es un no-op seguro (`resolve()` retorna `False` si ya no está;
`_pending.pop(user_id, None)` en `confirm()` es idempotente si `resolve()` ya sacó la entrada).
Ese razonamiento de §7.2 es correcto y está bien probado.

Lo que no está cubierto es una salida de excepción **antes** de llegar a `pending.event.wait(...)`.
En §5.2, `confirm()` hace, en este orden:
```python
with self._lock:
    ...
    self._pending[user_id] = pending
self._send_message(chat_id, message)          # (1)
answered_in_time = pending.event.wait(timeout=CONFIRM_TIMEOUT_SECONDS)   # (2)
with self._lock:
    ...
    self._pending.pop(user_id, None)            # (3) limpieza
```
Dentro de `_send_message()`, el `try/except` solo envuelve `future.result(timeout=10)` — **no**
envuelve la línea anterior, `future = asyncio.run_coroutine_threadsafe(coro, self._loop)`. Esa
llamada puede lanzar de forma síncrona (por ejemplo `RuntimeError` si `self._loop` ya no está
corriendo — caso de borde de apagado/reinicio del bot mientras el adaptador sigue con una
referencia al loop anterior). Si eso ocurre:

- La excepción se propaga fuera de `_send_message()`, fuera de `confirm()` (que no tiene su propio
  `try/except` alrededor de la llamada), fuera de `require_confirmation()` (tampoco envuelve la
  llamada al adaptador en un `try/except`), hasta `await asyncio.to_thread(...)` en `cmd_eliminar()`
  (que tampoco la captura en el diseño de §6.1) — termina en el manejador de errores global de PTB.
- El paso (3) — la limpieza de `_pending[user_id]` — **nunca se ejecuta**, porque el flujo nunca
  llega ahí. La entrada queda huérfana en el diccionario **para siempre** (no hay timeout que la
  limpie, porque el timeout vive en el paso (2), que tampoco se alcanzó).
- Consecuencia doble: (a) fuga de memoria de un `_PendingConfirmation` por incidente — menor en
  magnitud, pero (b) mucho más relevante: `has_pending(user_id)`/el chequeo atómico dentro de
  `confirm()` verán ese `user_id` como "con confirmación pendiente" **de forma permanente** —
  ese usuario queda inhabilitado para volver a usar `/eliminar` (siempre recibirá "Ya tenés una
  confirmación pendiente...") hasta que el proceso del bot se reinicie. Es un fallo de
  disponibilidad dirigido a un usuario específico, no solo una fuga de memoria abstracta.
- Y no queda auditado: como la excepción escapa antes de que `require_confirmation()` llegue a
  `result = "confirmada" if confirmed else "cancelada"; self._log_audit(...)`, este camino de
  fallo no genera ninguna fila en `audit.db` — contradice el espíritu de CA-14 (que si bien no
  exige explícitamente cubrir excepciones, sí exige que toda resolución de una confirmación quede
  trazada, y este camino ni siquiera "resuelve": deja el estado indefinido).

No es una vía para que la confirmación se resuelva incorrectamente a `True` — en ese sentido el
fail-closed nominal ("nunca `True` por defecto") se sostiene. Pero sí es una vía real donde
"nunca queda un estado de espera vivo para una respuesta que ya no puede llegar" (CA-07, texto
literal de la SPEC) **se rompe**: el estado queda vivo indefinidamente, sin que ninguna respuesta
futura pueda limpiarlo tampoco (`resolve()` seguiría encontrando la entrada y "consumiéndola" con
cualquier texto que el usuario mande después, incluso aunque el usuario nunca pidió esa
confirmación en el sentido de la sesión actual — es una entrada zombi que absorbe silenciosamente
el próximo mensaje de ese usuario como si fuera una respuesta a algo que technically ya no está
esperando nadie en un `event.wait()` porque ese hilo worker ya murió con la excepción).

**Corrección requerida (no cambia el diseño, lo completa — mismo criterio que el Hallazgo B de
`security-audit-015.md` para `WebViewConfirmationAdapter`):** envolver desde la inserción en
`_pending` hasta el `wait()` en un `try/finally` (o extender el `try/except` de `_send_message()`
para cubrir también `asyncio.run_coroutine_threadsafe(...)`, no solo `future.result(...)`) de modo
que, sin importar qué excepción ocurra al intentar enviar el mensaje, `confirm()` siempre termine
limpiando `_pending[user_id]` y devolviendo `False` (nunca dejando la excepción escapar sin
limpieza, y siempre generando el log de auditoría correspondiente vía el flujo normal de
`require_confirmation()`). Agregar un test explícito a
`tests/test_telegram_confirmation_adapter.py` que mockee `asyncio.run_coroutine_threadsafe` para
que lance `RuntimeError` y verifique que `confirm()` retorna `False` y que `_pending` queda vacío
después. Puede resolverse directo en `orion-dev`, sin volver a `orion-architect` — es la misma
categoría de ajuste que el Hallazgo B de REQ-015 (precisar limpieza y manejo de una salida no
feliz de un diseño ya aprobado).

## Hallazgo C (no bloqueante, corrección obligatoria para `orion-dev`) — El test de CA-03 (§11) usa una lista de 19 acciones copiada a mano, no derivada del registro real

Tal como está especificado en `arquitectura-018.md` §11, el test de regresión de CA-03 es
"parametrizado sobre las 19 acciones YELLOW restantes" listando los 19 nombres literalmente
(`shutdown`, `restart`, `close_app`, ..., `save_file_desktop`). Es exactamente el patrón contra el
que advirtió el encargo de esta auditoría: si en el futuro se registra una acción YELLOW nueva
(por ejemplo, exactamente el escenario que `REQ-019` habilita — un override de configuración que
suba una acción de GREEN a YELLOW) y nadie actualiza manualmente esta lista de 19 en el test, el
test **seguiría pasando en verde** sin haber verificado nada sobre la acción nueva — no porque el
mecanismo de seguridad real falle (`CHANNEL_ACTION_EXCEPTIONS` solo tiene la entrada de
`delete_task`, así que la acción nueva seguiría bloqueada correctamente en Telegram por el camino
normal de `CHANNEL_ALLOWED_LEVELS`), sino porque el test dejó de ser una prueba de "todas las
YELLOW menos `delete_task`" para convertirse silenciosamente en una prueba de "estas 19 YELLOW de
agosto de 2026 menos `delete_task`" — pierde su valor de guardrail exactamente en el momento en
que más importaría (cuando aparece una acción nueva).

No es un hallazgo de que el mecanismo de seguridad tenga un agujero hoy — es un hallazgo de que la
red de regresión que debería detectar un agujero *futuro* (alguien agrega mal una segunda entrada
a `CHANNEL_ACTION_EXCEPTIONS`, o clasifica mal una acción nueva) se degrada con el tiempo sin dar
ninguna señal de que se degradó.

**Corrección requerida:** el test debe derivar la lista de acciones YELLOW dinámicamente del
registro real en el momento de ejecutarse — por ejemplo:
```python
todas_las_yellow = [
    name for name, level in security_manager._actions.items()
    if level == RiskLevel.YELLOW
]
yellow_a_verificar = [n for n in todas_las_yellow if n != "delete_task"]
```
(o exponiendo un método público en `SecurityManager` si se prefiere no tocar `_actions`
directamente desde el test, p. ej. `security_manager.actions_by_level(RiskLevel.YELLOW)` —
cualquiera de las dos formas cumple el objetivo: que el test compare siempre contra el estado real
del registro, no contra una copia congelada en el momento de escribir el test). Con esto, si
mañana se registra una acción YELLOW nueva sin agregarla a `CHANNEL_ACTION_EXCEPTIONS`, el test la
incluye automáticamente en la verificación y sigue protegiendo correctamente; si alguien agrega
una entrada nueva a `CHANNEL_ACTION_EXCEPTIONS` sin la justificación exigida por el comentario de
§4.1, el test la detecta y falla, tal como ya promete (pero no cumple del todo) el propio texto de
mitigación de riesgos en §10 de la arquitectura ("el test de regresión de CA-03 falla
automáticamente si una entrada nueva no documentada abre una acción YELLOW no esperada — actúa
como guardrail estructural"). Puede resolverse directo en `orion-dev`, sin volver a
`orion-architect` — no cambia el mecanismo, solo la forma de probarlo.

## Hallazgo D (verificado, sin hallazgo) — Aislamiento entre `CHANNEL_ACTION_EXCEPTIONS` (REQ-018) y el override de configuración de `REQ-019`

Punto 1 del encargo. Verificado con lectura completa de `workspace/adjuntos/REQ-019/
propuestas/arquitectura-019.md` (28 CA) y `REQ-019-context.md`:

- **Son dos ejes ortogonales del mismo pipeline, sin punto de contacto en el código.**
  `CHANNEL_ACTION_EXCEPTIONS` (REQ-018) es un `set[tuple[ChannelType, str]]` consultado
  únicamente dentro de `is_action_allowed()` — decide **si una acción YELLOW puede pedir
  confirmación en un canal dado**. El mecanismo de REQ-019 (`_merge_with_override()`, invocado
  desde dentro de `register_action()`) decide **qué nivel (`RiskLevel`) tiene una acción**,
  guardando el resultado en `self._actions[name]` (lo que `classify_action()` expone) — nunca lee
  ni escribe `CHANNEL_ACTION_EXCEPTIONS`, nunca recibe `channel` como parámetro
  (`arquitectura-019.md`, CA-07, texto literal: *"`_merge_with_override()` no recibe ni consulta
  `channel` en ningún punto... `CHANNEL_ALLOWED_LEVELS` no se toca"*). `arquitectura-019.md`
  declara explícitamente (línea ~703) que `classify_action()` y `require_confirmation()` quedan
  "sin cambios de código" — es decir, REQ-019 ni siquiera toca la función donde vive la lógica de
  CA-02 de REQ-018.
- **`security_overrides.json` (REQ-019) no puede alcanzar `CHANNEL_ACTION_EXCEPTIONS`.** El
  archivo de overrides solo admite pares `{clave_interna: "green"|"yellow"|"red"}` (CA-26 de
  SPEC-019/arquitectura-019: "ninguna estructura nueva admite texto libre, tokens ni paths") — no
  hay ningún campo de canal en ese esquema, y `CHANNEL_ACTION_EXCEPTIONS` sigue siendo,
  exactamente como dice `arquitectura-018.md` §4.1, un `set` literal en código Python
  (`core/security_manager.py`), sin ningún punto de carga desde disco, config ni entrada de
  usuario — grep confirmado: ninguna referencia a `CHANNEL_ACTION_EXCEPTIONS` existe en todo
  `workspace/adjuntos/REQ-019/`.
- **Escenario límite considerado y descartado como riesgo real:** si en el futuro un override de
  REQ-019 subiera `delete_task` de YELLOW a RED (nunca al revés, por el propio piso de REQ-019),
  el efecto sería que `require_confirmation("delete_task", TELEGRAM, ...)` entraría a la rama
  `RiskLevel.RED` de `require_confirmation()` (línea 283 de `security_manager.py`) en vez de la
  rama YELLOW — esa rama **no consulta `is_action_allowed()`/`CHANNEL_ACTION_EXCEPTIONS` en
  absoluto**, solo permite RED en `ChannelType.DESKTOP` con PIN. El efecto neto sería que
  `/eliminar` en Telegram pasaría de "pide confirmación conversacional" a "bloqueado
  incondicionalmente" — más restrictivo, no menos. No hay ningún camino, ni siquiera hipotético,
  en el que la combinación de ambos mecanismos termine siendo **más permisiva** de lo que cada uno
  es por separado. Sin hallazgo — ambos REQs pueden aprobarse e implementarse de forma
  independiente sin coordinación adicional entre sí en este punto.

## Secretos

- Token de Telegram: `channels/telegram_bot.py::_get_token()` → `config_manager.get_telegram_token()`
  — sin cambios de este REQ, sin hardcodeo, patrón ya auditado en REQs previos.
- El adaptador nuevo (`channels/telegram_confirmation_adapter.py`) no maneja ningún secreto —
  opera sobre `bot`/`loop` ya autenticados que le pasa `bind()`.
- Ningún dato sensible se agrega a `details`/`format_details()` más allá de `task_id` (entero) y
  `user_id` (ya usado hoy en el resto del sistema) — dentro de la allowlist ya existente de
  `_DETAILS_ALLOWED_KEYS`.
- Sin hallazgos de secretos expuestos.

## Validación de inputs

- `task_id = int(context.args[0])` con `try/except ValueError` explícito en los tres comandos
  (`/eliminar`, `/completar`) — correcto, mismo patrón que el código actual sin cambios.
- Criterio de "sí" (CA-06) es una allowlist exacta (`("sí", "si", "yes", "s")`), no una heurística
  ni una negación — cualquier cosa fuera de esa lista, incluida ambigüedad, cuenta como
  cancelación. Correcto y fail-closed por diseño.
- El mensaje que se envía por Telegram (`full_msg`) se manda con `parse_mode` **omitido**
  (texto plano) a propósito, según el propio diseño (§5.1) — evita que el parser de Markdown de
  Telegram interprete caracteres de `details`/`task_id` de forma inesperada. Correcto.
- `set_request_context()`/`_request_ctx` reciben `user_id`/`chat_id` exclusivamente de
  `update.effective_user.id`/`update.effective_chat.id` — objetos poblados por
  `python-telegram-bot` a partir de la respuesta autenticada de la API de Telegram, no
  derivables ni falsificables desde el texto del mensaje del cliente. Verificado en los tres
  puntos de uso (`cmd_eliminar()`, `_intercept_confirmacion_pendiente()`) — ninguno lee `channel`,
  `user_id` ni `chat_id` de `context.args`/`message.text`.
- Sin `except: pass` silencioso en ningún bloque nuevo diseñado — los tres `try/except` del
  adaptador (`_send_message`, con la salvedad del Hallazgo B) y el de `cmd_completar`/`cmd_eliminar`
  (`ValueError` de `int()`) todos responden al usuario o registran log.

## Recomendaciones (resumen)

1. **[Bloqueante — Hallazgo A]** Agregar `.concurrent_updates(True)` (o un entero explícito) a la
   construcción de `Application` en `run_telegram_bot()` — sin esto, CA-08 no se cumple y el bot
   completo queda bloqueado hasta 120s para todos los usuarios ante cualquier `/eliminar` sin
   responder. Agregar también un test de integración que verifique la configuración real del
   `Application`, no solo el comportamiento aislado del adaptador.
2. **[No bloqueante, corrección obligatoria — Hallazgo B]** Envolver el ciclo de vida de
   `_pending[user_id]` dentro de `confirm()` en un `try/finally` (o extender el `try/except` de
   `_send_message()` a `asyncio.run_coroutine_threadsafe(...)`) para que cualquier excepción en el
   envío del mensaje limpie el estado pendiente y resuelva a `False`, en vez de dejar una entrada
   huérfana permanente. Agregar test con `asyncio.run_coroutine_threadsafe` mockeado para lanzar.
3. **[No bloqueante, corrección obligatoria — Hallazgo C]** El test de CA-03 debe derivar la lista
   de acciones YELLOW dinámicamente de `security_manager` en el momento de ejecutarse, no copiarla
   a mano — ver snippet propuesto arriba.
4. [No bloqueante] Una vez aplicado el Hallazgo A, revalidar explícitamente contra el escenario
   real (concurrencia habilitada) la discusión de agotamiento del thread pool de §10 — la
   mitigación documentada sigue pareciendo razonable, solo pasa de hipotética a real.
5. [No bloqueante] Considerar, para una iteración futura (fuera de alcance de REQ-018), si CA-09
   debería además limitar cuántas confirmaciones *distintas* pueden estar pendientes
   simultáneamente en todo el bot (no solo una por usuario) — dado el Hallazgo A, una vez corregido
   con `concurrent_updates`, el propio thread pool sigue siendo un límite natural, pero no está de
   más que quede documentado como un límite conocido y no un descuido.

## Veredicto: ❌ REQUIERE CAMBIOS

El Hallazgo A es bloqueante: invalida, verificado contra el código fuente real de
`python-telegram-bot==20.7` (no solo contra el razonamiento de la propuesta), el cumplimiento de
CA-08 — uno de los dos focos de riesgo que motivaron que este REQ pasara por `orion-security` como
paso dedicado (arquitectura-018.md §12, punto 2: "primer adaptador de confirmación real para un
canal async y multiusuario"). La corrección es acotada (una línea en la construcción del
`Application`, más un test de integración) y no cuestiona ninguna de las decisiones técnicas
centrales ya aprobadas por Johan (CA-02/`CHANNEL_ACTION_EXCEPTIONS`, la decisión de CA-10, el
patrón general del adaptador) — no se recomienda rediseñar nada, se recomienda que
`orion-architect` incorpore el Hallazgo A (y de paso B y C, que son del mismo tamaño que los
Hallazgos B de `security-audit-015.md`) a `arquitectura-018.md` antes de pasar a `orion-dev`.

Los mecanismos verificados sin hallazgo — aislamiento de `CHANNEL_ACTION_EXCEPTIONS` frente a
input de usuario y frente al override de REQ-019 (punto 1 del encargo), correlación estrictamente
por `user_id` de Telegram sin cruce entre usuarios (punto 4), y auditoría sin tabla paralela
(punto 5) — quedan confirmados y no requieren ningún cambio.

---

## Re-chequeo (2026-08-20) — respuesta a `arquitectura-018.md` §15 (addendum post-auditoría)

**Entrada auditada en este re-chequeo:** `arquitectura-018.md` §15 completo (15.1 a 15.5, líneas
968-1150), sin reabrir §1-§14 (confirmado que no fueron reescritas — diff mental contra la versión
citada en la auditoría original, mismo contenido). Verificación adicional directa contra el código
fuente instalado de `python-telegram-bot==20.7` (no solo contra el texto del addendum) y contra el
estado real de `channels/telegram_bot.py` en el repo (confirmado sin el fix todavía aplicado —
`grep -n "concurrent_updates" channels/telegram_bot.py` → 0 resultados, `run_telegram_bot()` línea
804 sigue con `Application.builder().token(token).build()` tal cual antes de la auditoría; correcto
y esperado, `orion-dev` todavía no corrió sobre este REQ, el addendum es diseño, no código).

### Hallazgo A (bloqueante) — RESUELTO, verificado

El fix propuesto en §15.1 (`.concurrent_updates(True)` en el builder de `run_telegram_bot()`) se
verificó **ejecutando código real** contra el paquete instalado, no solo leyendo el razonamiento
del addendum:

```
>>> from telegram.ext import Application
>>> app = Application.builder().token("123456:FAKE...").build()
>>> app.concurrent_updates
1
>>> app = Application.builder().token("123456:FAKE...").concurrent_updates(True).build()
>>> app.concurrent_updates
256
```

Confirmado además contra el código fuente de la propiedad (`telegram/ext/_application.py`,
`Application.concurrent_updates`): `return self._update_processor.max_concurrent_updates` — es un
atajo directo al procesador de updates real, no un valor cacheado ni derivado indirectamente; leer
`app.concurrent_updates > 1` después de construir la `Application` es una verificación estructural
genuina de la configuración efectiva, no un proxy indirecto que podría dar falsos positivos.

**El nuevo test de integración (`test_run_telegram_bot_concurrent_updates_habilitado`, §15.1)
cierra exactamente el gap que dejaba pasar el bug original:**
- Construye una `Application` **real** con `Application.builder().token(...).concurrent_updates(True).build()`
  — no el adaptador `TelegramConfirmationAdapter` aislado con un `threading.Thread` genérico, que
  era literalmente la causa por la que el test original de CA-08 (arquitectura §11, pre-addendum)
  no detectó el Hallazgo A: probaba que un hilo worker no bloquea al hilo que lo llama, pero nunca
  instanciaba el objeto `Application` cuya configuración por defecto era la fuente real del bug.
- No requiere red (verificado: `.build()` no dispara ninguna llamada HTTP; solo
  `initialize()`/`run_polling()` lo harían) — el test es rápido y determinístico, apto para CI.
- **Verificado que el test detecta la regresión que dice detectar:** ejecuté la misma aserción
  (`assert app.concurrent_updates > 1`) contra una `Application` construida SIN
  `.concurrent_updates(True)` (simulando que alguien revierte el fix por error) — el resultado es
  `app.concurrent_updates == 1`, y la aserción falla como se espera. El test no es un placebo que
  siempre pasa independientemente del código: efectivamente distingue el estado correcto del
  incorrecto.
- Confirmado también contra el código fuente de `ApplicationBuilder.concurrent_updates()`
  (`telegram/ext/_applicationbuilder.py`): pasar `True` habilita `SimpleUpdateProcessor(256)`
  exactamente como documenta el addendum — no hay discrepancia entre lo que el addendum afirma y
  lo que el paquete instalado realmente hace.

**Verificación adicional (no pedida explícitamente, pero relevante para no introducir un hallazgo
nuevo con el propio fix):** `channels/telegram_bot.py` no registra ningún `ConversationHandler` —
grep confirmado (`ConversationHandler` no aparece en el archivo) — así que la advertencia propia de
la librería sobre `concurrent_updates` ("no recomendado con handlers con estado como
`ConversationHandler`") no aplica a este código. `.concurrent_updates(True)` no introduce un riesgo
nuevo de ese tipo.

**Veredicto de este punto: ✅ RESUELTO.** El fix es correcto, verificado contra el código fuente
real de la dependencia (no solo contra el razonamiento), y el test de integración nuevo cierra
efectivamente el gap de cobertura que dejaba pasar el hallazgo original — construye una `Application`
real, no el adaptador aislado, y se confirmó experimentalmente que falla ante la regresión que dice
prevenir.

### Punto 2 del encargo — nota propia del arquitecto (§15.1, "Nota adicional") — nuevo hallazgo, NO BLOQUEANTE

**Hallazgo E (no bloqueante, corrección recomendada) — ventana de correlación entre dos mensajes
casi simultáneos del MISMO usuario cuando el segundo llega antes de que `confirm()` alcance a
insertar en `_pending`**

La nota es correcta y describe un riesgo real, distinto del ya documentado y aceptado en §10 fila 1
de `arquitectura-018.md` (que es sobre dos invocaciones de `/eliminar` compitiendo en el chequeo
rápido `has_pending()` — ese caso sí queda cerrado por la verificación atómica dentro de `confirm()`,
sin ambigüedad posible sobre CA-09). El caso nuevo es distinto: **la inserción real en
`_pending[user_id]` no ocurre de forma síncrona dentro de `cmd_eliminar()` (el Task que procesa el
update de `/eliminar`), sino dentro de `confirm()`, que corre recién cuando el hilo worker de
`asyncio.to_thread()` efectivamente arranca** — entre el momento en que `cmd_eliminar()` hace
`await asyncio.to_thread(...)` (que cede el control al loop de inmediato) y el momento en que ese
hilo worker llega a `with self._lock: self._pending[user_id] = pending`, existe una ventana real,
angosta pero no nula, en la que un segundo update del mismo usuario — si ya estaba encolado en
`update_queue` por llegar casi al mismo tiempo — puede despacharse como una `asyncio.Task`
independiente (correcto, es justamente lo que `.concurrent_updates(True)` habilita) y llegar a
`_intercept_confirmacion_pendiente()` → `resolve(user_id, texto)` **antes** de que la entrada
exista. `resolve()` no encuentra nada que consumir, retorna `False` sin lanzar
`ApplicationHandlerStop`, y ese segundo mensaje sigue su camino normal de procesamiento en vez de
correlacionarse con la confirmación que, technically, ya estaba en curso desde la perspectiva del
usuario (aunque no desde la perspectiva del diccionario `_pending` todavía).

**Evalué el impacto de seguridad concreto, no solo la existencia de la ventana — conclusión: no
compromete la garantía de CA-06/CA-09, por eso no es bloqueante:**

1. **No puede producir una confirmación afirmativa no intencionada.** `resolve()` solo consume un
   mensaje como "sí" cuando `_pending[user_id]` **ya existe** — si la ventana hace que no exista
   todavía, el resultado es que el mensaje **no se intercepta en absoluto** (cae al procesamiento
   normal), nunca que se interprete erróneamente como confirmación de algo que el usuario no
   confirmó. No hay ningún camino en el código, con o sin esta ventana, en el que un texto llegue a
   `pending.result = True` sin que exista una entrada real en `_pending` para ese `user_id`.
2. **No puede producir dos confirmaciones pendientes simultáneas para el mismo usuario.** La
   verificación atómica bajo `self._lock` dentro de `confirm()` (línea ~364-371 del adaptador, §5.2)
   sigue intacta — sigue siendo imposible que existan dos `_PendingConfirmation` vivos para el mismo
   `user_id` a la vez, sin importar el orden de llegada de los mensajes. El invariante literal de
   CA-09 ("una sola confirmación pendiente por usuario") no se rompe.
3. **El sistema permanece fail-closed en el peor caso.** Si el segundo mensaje "se pierde" como
   respuesta (cae a procesamiento normal en vez de resolver la confirmación), la confirmación de
   `/eliminar` original sigue viva y sigue esperando — expira a los 120s y se cancela sola (CA-07).
   No hay ningún escenario derivado de esta ventana en el que una tarea se borre sin que el usuario
   haya efectivamente enviado un "sí" que sí fue correlacionado con éxito.
4. **La ventana requiere un patrón de uso casi imposible para un humano real.** El propio texto del
   arquitecto lo señala: "sin que medie el tiempo real que toma que el usuario vea el prompt de
   confirmación y responda" — es decir, el segundo mensaje tendría que llegar a los servidores de
   Telegram y quedar ya encolado en `update_queue` **antes** de que el hilo worker recién lanzado
   alcance una única línea de código (`self._pending[user_id] = pending`, sin ningún `await` de por
   medio en ese tramo). En la práctica esto es alcanzable solo por un cliente automatizado que
   dispare mensajes en ráfaga, no por interacción humana normal.

**No es "el diseño ya lo cubre adecuadamente" tampoco — es un hallazgo real, solo que de impacto
acotado a UX/correlación, no a autorización.** El `threading.Lock` del adaptador protege la
consistencia interna de `_pending`, pero no puede cerrar una ventana que depende del *orden de
scheduling* entre dos `asyncio.Task` distintas — eso solo se cierra moviendo el punto de inserción,
no agregando más sincronización dentro del adaptador.

**Corrección recomendada (mismo tratamiento que Hallazgos B/C — resoluble directo en `orion-dev`,
sin volver a `orion-architect`; el propio addendum ya esboza la dirección correcta en su última
frase):** mover la reserva de `_pending[user_id]` a una llamada **síncrona**, dentro del mismo Task
que procesa `/eliminar`, **antes** del primer `await`:

1. Agregar `TelegramConfirmationAdapter.reserve_pending(user_id: str) -> bool` — hace exactamente
   el `with self._lock: if user_id in self._pending: return False; self._pending[user_id] =
   _PendingConfirmation(); return True` que hoy vive al principio de `confirm()` (§5.2), pero
   invocable de forma independiente.
2. `cmd_eliminar()` (§6.1) llama `telegram_confirmation_adapter.reserve_pending(user_id)`
   **síncronamente**, inmediatamente después del chequeo rápido `has_pending()` y **antes** de
   `await asyncio.to_thread(...)`. Si retorna `False` (ya había una reservada — mismo caso que hoy
   cubre `has_pending()`, ahora atómico también en este punto), responder el mensaje de
   "confirmación pendiente" existente y `return`, sin llegar a lanzar el hilo worker.
3. `confirm()` deja de crear una `_PendingConfirmation` nueva — usa la que `cmd_eliminar()` ya
   reservó (`pending = self._pending[user_id]`, se garantiza presente porque el paso 2 corrió en el
   mismo Task antes de que `confirm()` pudiera ejecutarse) y continúa directo a `_send_message()` +
   `event.wait()`.
4. Efecto colateral positivo, no solo el cierre de esta ventana: la reserva síncrona en el mismo
   Task, antes de cualquier `await`, también convierte en garantía dura (en vez de "límite conocido
   aceptado") la carrera ya documentada en §10 fila 1 de `arquitectura-018.md` (dos `/eliminar`
   casi simultáneos del mismo usuario) — dejaría de depender de que el segundo request pierda la
   carrera dentro de `confirm()` para en cambio nunca llegar a lanzar un segundo hilo worker.
5. Test nuevo sugerido para `tests/test_telegram_bot.py`: simular dos updates del mismo `user_id`
   despachados como dos `asyncio.Task` concurrentes — uno `/eliminar 5` y, sin dar tiempo a que su
   Task complete el primer `await`, un segundo mensaje de texto cualquiera — y verificar que
   `_intercept_confirmacion_pendiente()` para el segundo encuentra `_pending[user_id]` ya reservado
   (usando `reserve_pending()` con un mock que fuerza el orden de ejecución, o inspeccionando
   `_pending` directamente después de que `cmd_eliminar()` alcanza el punto de la reserva pero antes
   de que el `to_thread` interno complete).

No cambia el contrato de `core/confirmation.py` (`ConfirmFn` sigue siendo `(action_name, mensaje) ->
bool`, sin tocar) ni el patrón general del adaptador — es una redistribución de 3-4 líneas entre
`cmd_eliminar()` y el adaptador, del mismo tamaño y naturaleza que la corrección ya aceptada como no
bloqueante para el Hallazgo B.

### Hallazgos B y C — confirmados correctamente documentados para `orion-dev`

Verificado `arquitectura-018.md` §15.2 y §15.3: ambos remiten explícitamente a las secciones
"Hallazgo B"/"Hallazgo C" de este mismo archivo (`security-audit-018.md`) para el detalle completo
de la corrección, y ambos incluyen la instrucción explícita "`orion-dev` la implementa directo, sin
volver a pasar por `orion-architect`". La tabla de riesgos del addendum (§15.4) los referencia de
nuevo de forma consistente. No hace falta ninguna corrección adicional de mi parte — ambos quedan
listos tal como están, sin reabrir.

### Clasificación de riesgos — actualización de este re-chequeo

| Punto auditado | Nivel | ¿Confirmación? | Estado |
|---|---|---|---|
| Hallazgo A — `.concurrent_updates(True)` en `run_telegram_bot()` + test de integración real | 🔴 Rojo (era) | — | ✅ RESUELTO, verificado contra código fuente real de PTB 20.7 y ejecución de prueba |
| Hallazgo B — limpieza de `_pending` si falla el envío | 🟡 Amarillo | No aplica (mecanismo) | ✅ documentado, correcto para `orion-dev` |
| Hallazgo C — test de CA-03 derivado del registro real | 🟢 Verde (test) | No aplica | ✅ documentado, correcto para `orion-dev` |
| Hallazgo E (nuevo) — ventana de correlación mismo-usuario, mensajes casi simultáneos | 🟡 Amarillo (UX/correlación, no autorización) | No aplica | ⚠️ NO BLOQUEANTE — corrección recomendada, documentada para `orion-dev` |

### Veredicto del re-chequeo: ✅ APROBADO

El Hallazgo A bloqueante está resuelto y verificado con evidencia experimental directa (no solo
lectura del addendum) — CA-08 pasa a ser cierto con el fix aplicado, y el test de integración nuevo
efectivamente lo protege contra regresión futura (confirmado que falla sin el fix). Los Hallazgos B
y C quedan correctamente documentados para que `orion-dev` los resuelva sin otra vuelta a
`orion-architect`. El Hallazgo E (nuevo, encontrado durante este re-chequeo a partir de la nota
propia del arquitecto en §15.1) es real pero **no bloqueante**: no compromete la garantía de "una
sola confirmación pendiente por usuario, sin ambigüedad" de CA-09 (la verificación atómica se
sostiene siempre), no puede producir una confirmación afirmativa no intencionada, y el sistema
permanece fail-closed en el peor caso (la confirmación original expira sola a los 120s). Su impacto
es acotado a una pérdida de correlación UX en una ventana de tiempo solo alcanzable en la práctica
por un cliente automatizado, no por uso humano normal — se documenta con corrección recomendada
(mover la reserva de `_pending` a una llamada síncrona antes del `await`, mismo criterio que
Hallazgos B/C) para que `orion-dev` la resuelva directo, sin necesidad de otra vuelta a
`orion-architect` ni a `orion-security`.

**El REQ puede avanzar a `orion-dev`** con 3 correcciones no bloqueantes pendientes de implementar
en esta misma etapa de desarrollo (Hallazgos B, C, E) — ninguna requiere rediseño ni otra
aprobación humana de arquitectura.
