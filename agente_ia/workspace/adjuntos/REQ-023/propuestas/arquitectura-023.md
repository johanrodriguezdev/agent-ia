# Arquitectura REQ-023 — Disparador proactivo por webhook externo

**Agente:** orion-architect
**Fecha:** 2026-09-07
**Estado de esta propuesta:** ⏸️ **PENDIENTE DE APROBACIÓN PERSONAL DE JOHAN — NO autoaprobada**

> ⚠️ Este documento **no se autoaprueba bajo la autorización nocturna en bloque del
> 2026-09-06**, aunque el resto del pipeline de esta sesión sí opera bajo esa autorización.
> El motivo, ya fijado desde `orion-coordinador` y reiterado por `orion-spec` y
> `orion-baseline` en `REQ-023-context.md`: este REQ abre el primer listener HTTP entrante
> persistente de todo O.R.I.O.N., una superficie de red nueva hacia el PC de Johan. Es una
> decisión que él tiene que mirar con sus propios ojos, despierto, no delegar a otro agente
> en su nombre. El estado del tracker permanece en `EN_ARQUITECTURA` y
> `Aprobacion_Arquitectura` permanece sin aprobar hasta que Johan responda explícitamente
> `APROBADO` / `AJUSTAR [qué]` / `RECHAZADO [motivo]` sobre este documento en concreto.

## En español llano — qué va a poder hacer Johan y qué gana con esto

Hoy O.R.I.O.N. solo se activa solo (sin que Johan escriba nada) por horario: al arrancar la
app, cada hora, o a una hora fija del día. No hay forma de que algo que pasa **afuera** —un
servicio externo, un script de CI, un sensor, una automatización de otra máquina— le avise a
O.R.I.O.N. en el momento exacto en que ocurre. Con este cambio, Johan podrá crear un flujo
(como ya crea flujos programados hoy) y decirle "disparate cuando llegue este webhook", y
desde ese momento un `curl`/petición HTTP firmada correctamente hacia su propio PC hará que
ese flujo se ejecute al instante, sin esperar al siguiente ciclo de 60 segundos ni a que
llegue la hora programada. Ejemplo concreto: un pipeline de CI que, al terminar un deploy,
le avisa a O.R.I.O.N. para que revise logs o mande un resumen — hoy eso es imposible sin
tocar código; con REQ-023 es crear un flujo y apuntar el webhook a él.

El beneficio se acompaña de un candado deliberadamente estricto, porque es la primera puerta
de red que se abre en el proyecto: apagada por defecto, solo escucha en su propia máquina
(nadie desde internet puede tocarla salvo que Johan decida explícitamente lo contrario y
entienda el riesgo), cada petición tiene que venir firmada con un secreto que solo Johan
tiene, y lo que dispare pasa exactamente por el mismo sistema de permisos verde/amarillo/rojo
que cualquier otra acción del agente — un webhook nunca podrá saltarse esa capa aunque logre
autenticarse.

## Cobertura de criterios de la SPEC

| # | Criterio (SPEC-023) | Cómo lo satisface esta propuesta |
|---|----------------------|-----------------------------------|
| CA-1 | Listener deshabilitado por defecto → ningún socket abierto | `WebhookListener.start()` (nuevo, `core/webhook_listener.py`) lee `config_manager.get_webhook_config()["enabled"]`; si es `False` (default de fábrica, clave ausente o cualquier valor que no sea literalmente `True`), retorna sin construir ningún `HTTPServer`. Test: arrancar con `config.json` por defecto y verificar que `socket.connect_ex(("127.0.0.1", PUERTO))` no conecta. |
| CA-2 | Habilitado + sin bind explícito → solo escucha en 127.0.0.1 | `get_webhook_config()["bind_host"]` defaultea a `"127.0.0.1"` y se pasa literal al constructor de `ThreadingHTTPServer((bind_host, port), ...)`. Test unitario: instanciar `WebhookListener` con config por defecto y aserción sobre `server.server_address[0] == "127.0.0.1"` (no se simula ataque de red real — inviable en CI de un solo NIC — pero se verifica que el valor que se le pasa al socket es el loopback, que es la garantía real). |
| CA-3 | Request sin firma válida → 401/403, no dispara nada, queda en auditoría | `_WebhookHandler._verificar_firma()` calcula HMAC-SHA256 sobre el cuerpo crudo con `config_manager.get_webhook_secret()` y compara con `hmac.compare_digest()` contra el header `X-Webhook-Signature-256`. Si falla o falta: responde 401, llama `proactive_engine.fire_webhook()` **nunca**, y audita `security_manager.log_action("webhook_request", ChannelType.WEBHOOK, "rechazada_firma_invalida", ...)`. |
| CA-4 | Request autenticado + dirigido a trigger `webhook:<id>` registrado → dispara exactamente una vez | `ProactiveEngine.fire_webhook(webhook_id)` (nuevo método) busca triggers activos con `schedule == f"webhook:{id}"`, aplica el mismo anti-rebote de 300s que `_check_triggers()`, y llama `trigger.agent.execute(...)` una vez por match no debounced. |
| CA-5 | Autenticado pero trigger inexistente/no-webhook → no dispara nada, error claro (no 200 silencioso) | `fire_webhook()` retorna `disparados=0, motivo="no_registrado"` si no hay match; el handler traduce eso a HTTP 404 con cuerpo JSON `{"error": "trigger no registrado"}`. |
| CA-6 | La acción disparada pasa por `security_manager` con el mismo gate verde/amarillo/rojo; amarillo/rojo no se ejecuta sin confirmación o queda bloqueado si el canal no lo permite | Dos capas, ambas activas: (a) el propio `fire_webhook()` re-evalúa `security_manager.is_action_allowed("proactive_trigger", ChannelType.WEBHOOK)` antes de tocar cualquier trigger — con `CHANNEL_ALLOWED_LEVELS[WEBHOOK] = []` esto solo pasa por la excepción quirúrgica nueva (ver CA-7); (b) para el único tipo de trigger disparable en v1 (`EjecutorProgramado`, de un flujo), `EjecutorProgramado.execute()` ya invoca `flows.ejecutar(canal=ChannelType.UNKNOWN, ...)` **sin cambios** — `ChannelType.UNKNOWN` solo permite GREEN, así que cualquier paso amarillo/rojo del flujo se bloquea exactamente igual que hoy con un flujo disparado por `daily:HH:MM`. No hay atajo nuevo: el webhook hereda el mismo gate por paso que ya existe. |
| CA-7 | El canal no es `ChannelType.DESKTOP` ni ninguno con amarillo/rojo permitido por defecto | Nuevo `ChannelType.WEBHOOK` con `CHANNEL_ALLOWED_LEVELS[ChannelType.WEBHOOK] = []` (idéntico a `EMAIL`: ni siquiera verde por defecto). Verificable por test unitario directo sobre el dict, igual que pide la SPEC. `_check_triggers()` (el loop de `startup`/`hourly`/`daily`) **no se toca** — sigue usando `ChannelType.DESKTOP` exactamente como hoy, porque un trigger `webhook:<id>` nunca entra a ese camino (ver Flujo de datos, `_should_fire()`). |
| CA-8 | Cada request (aceptado o rechazado) y cada disparo quedan auditados, sin filtrar el secreto/firma | Todo paso por el handler termina en exactamente una llamada a `security_manager.log_action("webhook_request", ChannelType.WEBHOOK, resultado, user_id="webhook", details=...)`, con `details` construido por una función dedicada (`_detalles_seguros()`) que **solo** interpola `webhook_id` y el resultado — nunca el header de firma, el secreto, ni el cuerpo crudo del request. |
| CA-9 | Reiniciar la app no duplica el trigger ni abre más de un socket | Heredado sin cambios: `programar_todos()` (`core/flows.py`) llama `programar()` por cada flujo al arrancar, que ya hace `unregister_trigger()` antes de `register_trigger()` (líneas 622-626 de `core/flows.py`, sin modificar). Para el socket: `WebhookListener.start()` es idempotente igual que `ProactiveEngine.start()` (`if self._running: return`). |
| CA-10 | Tests automatizados que cubren opt-in apagado, bind localhost, rechazo sin auth, disparo correcto, paso por `security_manager` | Ver sección "Pruebas sugeridas" — un archivo nuevo `tests/test_webhook_listener.py` + adiciones a `tests/test_proactive_engine.py` y `tests/test_security_manager.py` (o los que ya existan con esos nombres; confirmar en baseline/al implementar). |

## Módulos a modificar

- `core/security_manager.py` — nuevo `ChannelType.WEBHOOK`, entrada en `CHANNEL_ALLOWED_LEVELS`
  (vacía), entrada en `_CHANNEL_STR_MAP`, y una excepción quirúrgica nueva en
  `CHANNEL_ACTION_EXCEPTIONS`.
- `core/proactive_engine.py` — nueva rama en `_should_fire()` para el prefijo `webhook:`, y
  nuevo método público `fire_webhook()`.
- `core/flows.py` — sin cambios de código (el mecanismo `programar()`/`horario` ya reenvía
  cualquier string, incluido `webhook:<id>`, sin modificación). Se documenta como decisión,
  no como cambio.
- `skills/flow_skill.py` — extensión acotada de `extraer_horario()` para reconocer una frase
  explícita tipo "por webhook `<id>`" y producir `f"webhook:{id}"`.
- `config_manager.py` — nuevas funciones `get_webhook_config()` y `get_webhook_secret()`.
- `config.json` (datos, no código) — nueva sección opt-in `"webhook"`, apagada por defecto.
- Módulo nuevo: `core/webhook_listener.py` — el servidor HTTP en sí.
- `main.py` — arranque/apagado del listener, siguiendo el patrón ya existente de
  `proactive_engine.start()`/`.stop()`.
- `requirements.txt` — **sin cambios** (stdlib `http.server`, mismo precedente que
  `core/mcp_oauth.py`).

## Nuevas clases/funciones

### `core/security_manager.py`

- **`ChannelType.WEBHOOK = "webhook"`** (nuevo miembro del enum) — comentario análogo al de
  `EMAIL`: canal de entrada NO CONFIABLE, origina cualquiera que alcance el puerto y sepa
  fabricar la firma correcta, no solo Johan.
- **`CHANNEL_ALLOWED_LEVELS[ChannelType.WEBHOOK] = []`** — mismo criterio que `EMAIL`: ni
  siquiera GREEN por defecto. Se elige un `ChannelType` propio (no reusar `EMAIL` literal)
  para que la auditoría (`audit.db`, columna `channel`) distinga sin ambigüedad un intento de
  webhook de un evento de correo — son superficies de ataque distintas y el forense posterior
  lo agradece.
- **`CHANNEL_ACTION_EXCEPTIONS.add((ChannelType.WEBHOOK, "proactive_trigger"))`** — excepción
  quirúrgica única, mismo patrón que las 4 de Telegram (REQ-018). Sin esta línea, el webhook
  no podría disparar *nada*, ni siquiera pasar el gate exterior del propio
  `proactive_engine`, porque `proactive_trigger` es GREEN y `WEBHOOK` no tiene ningún nivel
  permitido. La excepción habilita **solo** esa acción-contenedora (`"proactive_trigger"`),
  no ninguna acción concreta — el gate real y específico de cada acción sigue ocurriendo más
  abajo, sin tocar, dentro de `trigger.agent.execute()` (ver CA-6). Comentario en código debe
  dejar esto explícito para que un futuro agente no lo lea como "webhook ya puede todo".
- **`_CHANNEL_STR_MAP["webhook"] = ChannelType.WEBHOOK`** — para que `resolve_channel("webhook")`
  no caiga en `UNKNOWN` por accidente si algún día se serializa el canal como string.

### `core/proactive_engine.py`

- **`_should_fire()`** — nueva rama, antes del `return False` final:
  ```python
  if sched.startswith("webhook:"):
      return False  # nunca por el loop de 60s — solo por fire_webhook()
  ```
  Esto preserva sin tocar el comportamiento de `startup`/`hourly`/`daily:HH:MM`: un trigger
  webhook simplemente nunca es elegible para el polling, así que `_check_triggers()` (y su
  uso hoy vigente de `ChannelType.DESKTOP`) queda **exactamente igual que hoy**, sin
  bifurcaciones de canal dentro de esa función. El hallazgo de `orion-baseline` sobre el
  hardcodeo de `ChannelType.DESKTOP` se resuelve por *exclusión* (el webhook nunca pasa por
  ahí), no por *parchear* esa línea — riesgo de regresión mínimo sobre triggers existentes.

- **`fire_webhook(self, webhook_id: str, user_id: str = "default") -> WebhookFireResult`**
  (nuevo método público, el único punto de entrada que `core/webhook_listener.py` invoca
  después de autenticar un request):
  ```python
  def fire_webhook(self, webhook_id: str, user_id: str = "default") -> "WebhookFireResult":
      """Dispara los ProactiveTrigger registrados con schedule=f"webhook:{webhook_id}".

      Camino de entrada separado de _check_triggers()/_should_fire(): no depende del loop
      de polling de 60s, lo invoca directo core/webhook_listener.py tras validar la firma
      HMAC del request. Usa ChannelType.WEBHOOK (no confiable, CHANNEL_ALLOWED_LEVELS
      vacío + excepción quirúrgica para "proactive_trigger") — nunca ChannelType.DESKTOP.
      """
      now = datetime.now()
      objetivo = f"webhook:{webhook_id}".lower()
      matches = [t for t in self.triggers_activos()
                 if t.active and t.schedule.strip().lower() == objetivo]

      if not matches:
          security_manager.log_action("webhook_request", ChannelType.WEBHOOK,
                                       "no_registrado", user_id, details=f"webhook_id={webhook_id}")
          return WebhookFireResult(disparados=0, motivo="no_registrado")

      if len(matches) > 1:
          logger.warning(
              f"Colisión de webhook_id '{webhook_id}': {len(matches)} triggers "
              f"coinciden ({[t.agent.name for t in matches]}) — se disparan todos"
          )

      action_key = "proactive_trigger"
      if not security_manager.is_action_allowed(action_key, ChannelType.WEBHOOK):
          logger.warning(f"Disparo por webhook bloqueado por seguridad: {action_key}")
          security_manager.log_action(action_key, ChannelType.WEBHOOK, "bloqueada_canal",
                                       user_id, details=f"webhook_id={webhook_id}")
          return WebhookFireResult(disparados=0, motivo="bloqueado_canal")

      disparados = 0
      for trigger in matches:
          if trigger.last_fired and (now - trigger.last_fired).total_seconds() < 300:
              continue  # mismo anti-rebote de 300s que _check_triggers()
          try:
              result = trigger.agent.execute(trigger.action, {
                  "proactive": True, "webhook": True, "user_id": trigger.user_id,
              })
              if self._notify_callback:
                  self._notify_callback(result)
              trigger.last_fired = now
              disparados += 1
              logger.info(f"Trigger webhook disparado: {trigger.agent.name} ({webhook_id})")
          except Exception as e:
              logger.error(f"Error en acción disparada por webhook '{webhook_id}': {e}")

      security_manager.log_action(action_key, ChannelType.WEBHOOK, "disparado",
                                   user_id, details=f"webhook_id={webhook_id}, disparados={disparados}")
      return WebhookFireResult(disparados=disparados, motivo="ok" if disparados else "debounced")
  ```
  Nota de diseño sobre colisiones (caso borde de la SPEC): se elige **disparar todos** los
  triggers que coincidan con el mismo `webhook_id`, nunca uno solo silenciosamente — es
  determinístico y queda logueado (`logger.warning`), cumpliendo "debe ser determinístico y
  quedar logueado, no un fallo silencioso". Alternativa descartada: rechazar el registro del
  segundo trigger con el mismo id — se descarta por requerir validación cruzada en el momento
  de `programar()` que no tiene hoy visibilidad de qué otros flujos existen sin una consulta
  extra a `flow_store`; la opción "fire-all + warning" no necesita ese acoplamiento nuevo.

- **`WebhookFireResult`** (nuevo, dataclass simple o `NamedTuple` en el mismo archivo):
  ```python
  @dataclass
  class WebhookFireResult:
      disparados: int
      motivo: str  # "ok" | "no_registrado" | "bloqueado_canal" | "debounced"
  ```
  El `motivo` es lo que `core/webhook_listener.py` traduce a código HTTP (ver abajo).

### `core/webhook_listener.py` (módulo nuevo)

- **`WEBHOOK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")`** — único validador de formato de
  `webhook_id`, importado también por `skills/flow_skill.py` para que un flujo nunca pueda
  registrarse con un id que el listener luego no sepa enrutar (o peor, que contenga
  caracteres que compliquen el parseo del path). Rechaza cualquier cosa fuera de ese charset
  tanto al crear el flujo como al recibir el request.

- **`class _WebhookHandler(BaseHTTPRequestHandler)`**:
  - `do_POST(self)`:
    1. Valida `Content-Length` contra un tope (`MAX_BODY_BYTES = 16 * 1024`) **antes** de leer
       el cuerpo — si excede, responde 413 sin leer el body y audita `"rechazada_payload_grande"`.
    2. Extrae `webhook_id` del path (`/webhook/<id>`) con `WEBHOOK_ID_RE`; si no matchea,
       responde 400 y audita `"rechazada_id_invalido"` sin tocar `fire_webhook()`.
    3. Lee el cuerpo (ya acotado por el paso 1), envuelto en `try/except` — un cuerpo
       corrupto/no-UTF8 responde 400 y audita `"rechazada_payload_corrupto"`, sin tumbar el
       hilo del listener (satisface el caso borde de la SPEC).
    4. Verifica la firma: header `X-Webhook-Signature-256: sha256=<hex>` (mismo formato que
       GitHub) contra `hmac.new(secret.encode(), cuerpo_crudo, hashlib.sha256).hexdigest()`,
       comparación con `hmac.compare_digest()` (tiempo constante, evita timing attack). Falla
       → 401, audita `"rechazada_firma_invalida"`, **nunca** se llama `fire_webhook()`.
    5. Firma válida → `resultado = proactive_engine.fire_webhook(webhook_id)`, y traduce:
       `disparados > 0` → 200 `{"disparados": N}`; `motivo == "no_registrado"` → 404
       `{"error": "trigger no registrado"}`; `motivo == "bloqueado_canal"` → 403
       `{"error": "bloqueado por política de seguridad"}`; `motivo == "debounced"` → 200
       `{"disparados": 0, "motivo": "debounced"}` (no es un error — el trigger existe y está
       autenticado, solo está en la ventana anti-rebote).
    6. Cada rama termina en exactamente una auditoría (vía `fire_webhook()` para las
       autenticadas, vía el propio handler para las rechazadas antes de llegar ahí).
  - `log_message()` — silenciado igual que en `core/mcp_oauth.py` (no ensuciar la consola),
    delega a `logger.debug()`.
  - **Nunca** se registra `do_GET` — el listener solo acepta `POST`, cualquier otro verbo
    responde 405 (defensa adicional, no hay lectura de estado vía este endpoint).

- **`class WebhookListener`** (singleton `webhook_listener = WebhookListener()`, mismo
  patrón que `proactive_engine`):
  - `start(self)`:
    1. `cfg = config_manager.get_webhook_config()`. Si `not cfg["enabled"]` → log info
       ("webhook deshabilitado, no se abre listener") y `return` — **ningún socket** (CA-1).
    2. `secret = config_manager.get_webhook_secret()`. Si está vacío → **no arranca**, log
       de error explícito ("webhook habilitado pero sin `ORION_WEBHOOK_SECRET` — listener no
       se abre, nunca modo abierto por falta de configuración") — resuelve el caso borde de
       la SPEC (fail-closed, nunca "modo abierto").
    3. Si `cfg["bind_host"]` no es loopback (`"127.0.0.1"`/`"localhost"`) → `logger.warning`
       explícito: *"webhook bind configurado fuera de localhost — superficie expuesta a la
       red, sin TLS en v1, asegúrese de entender el riesgo antes de continuar"*. No bloquea
       el arranque (es una decisión que la SPEC permite ofrecer, "si se ofrece, debe ir
       marcado como decisión que requiere entender el riesgo") pero lo deja gritado en el
       log, no silencioso.
    4. Construye `ThreadingHTTPServer((cfg["bind_host"], cfg["port"]), _WebhookHandler)`
       (stdlib, `http.server.ThreadingHTTPServer` — variante de `HTTPServer` que atiende cada
       request en su propio hilo, para que una conexión lenta no bloquee a las demás; mismo
       módulo stdlib que ya usa `core/mcp_oauth.py`, sin dependencia nueva).
    5. Arranca un hilo daemon con `server.serve_forever()`, mismo patrón que
       `ProactiveEngine.start()` (`threading.Thread(..., daemon=True)`).
    6. Idempotente: si ya está corriendo, `return` sin hacer nada (evita doble bind en un
       segundo `start()` accidental).
  - `stop(self)`: `server.shutdown()` + `server.join(timeout=5)` + `server.server_close()` —
    libera el socket explícitamente para que un reinicio inmediato no choque con el puerto en
    estado `TIME_WAIT` ni quede zombie (caso borde de la SPEC: "no debe dejar el puerto en
    estado zombie que impida reabrirlo al reiniciar").

## Flujo de datos

```
[servicio externo] --POST /webhook/<id>--> [core/webhook_listener.py: _WebhookHandler]
                                                  │
                                     1. tamaño OK? (si no: 413, fin)
                                     2. <id> válido (regex)? (si no: 400, fin)
                                     3. cuerpo legible? (si no: 400, fin)
                                     4. firma HMAC válida? (si no: 401, audita, fin)
                                                  │ sí
                                                  ▼
                              proactive_engine.fire_webhook(webhook_id)
                                                  │
                          busca ProactiveTrigger con schedule == "webhook:<id>"
                                                  │
                     is_action_allowed("proactive_trigger", ChannelType.WEBHOOK)?
                     (pasa SOLO por la excepción quirúrgica nueva en
                      CHANNEL_ACTION_EXCEPTIONS — CHANNEL_ALLOWED_LEVELS[WEBHOOK] está vacío)
                                                  │ sí
                                                  ▼
                          trigger.agent.execute(trigger.action, {...})
                                                  │
                    (en v1, trigger.agent es SIEMPRE un EjecutorProgramado de un flujo)
                                                  ▼
                          flows.ejecutar(flujo_id, canal=ChannelType.UNKNOWN, ...)
                                                  │
                     por cada paso del flujo: action_registry.execute_action(...)
                     con el gate real verde/amarillo/rojo — UNKNOWN solo permite
                     GREEN, así que un paso amarillo/rojo se bloquea igual que hoy
                     bloquea un flujo disparado por daily:HH:MM
                                                  │
                                                  ▼
                            resultado → security_manager.log_action(...) auditado
                                        en audit.db (webhook_request + cada paso)
```

Dos caminos de disparo quedan completamente separados y sin interferencia:
- `startup`/`hourly`/`daily:HH:MM` → `_run_loop()` → `_check_triggers()` →
  `ChannelType.DESKTOP` (sin cambios, ni un carácter tocado en esa función).
- `webhook:<id>` → `fire_webhook()` (nuevo, invocado solo por el listener HTTP) →
  `ChannelType.WEBHOOK` (nuevo canal, vacío + excepción quirúrgica).

Un trigger `webhook:<id>` nunca es alcanzado por `_check_triggers()` (por CA en
`_should_fire()`), y ningún trigger `startup`/`hourly`/`daily` es alcanzable por
`fire_webhook()` (porque su `schedule` nunca empieza con `"webhook:"`). Cero superposición.

## Archivos a modificar/crear

- `core/security_manager.py` (modificar)
- `core/proactive_engine.py` (modificar)
- `core/webhook_listener.py` (crear)
- `config_manager.py` (modificar)
- `config.json` (dato — sin escribir nada hasta que Johan active el opt-in; `orion-dev` solo
  debe asegurar que `get_webhook_config()` funcione con la clave ausente)
- `skills/flow_skill.py` (modificar — extensión acotada de `extraer_horario()`)
- `main.py` (modificar — arranque/apagado de `webhook_listener`)
- `.env.example` (si existe en el repo — agregar `ORION_WEBHOOK_SECRET=` documentado; a
  confirmar existencia del archivo al implementar)
- `tests/test_webhook_listener.py` (crear)
- Ampliaciones en el/los archivos de test existentes de `proactive_engine` y
  `security_manager` (nombre exacto a confirmar al implementar — no se listó ninguno
  explícito en baseline-023.md).

## Dependencias nuevas

Ninguna. Se sigue el precedente de `core/mcp_oauth.py`: `http.server` (stdlib) es suficiente,
con `ThreadingHTTPServer` (también stdlib, mismo módulo) en vez de `HTTPServer` simple para
no bloquear requests concurrentes. `requirements.txt` no se toca.

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| Fuerza bruta contra la firma HMAC (intentos repetidos de adivinar/probar firmas) | Cada intento —válido o no— queda auditado en `audit.db` con timestamp, así que un patrón de abuso es detectable después. **Rate-limiting explícito se descarta deliberadamente para v1** (no una omisión: la SPEC lo permite dejar fuera si queda documentado) porque el bind por defecto a localhost ya reduce la superficie a "alguien con acceso al propio PC", y `hmac.compare_digest()` hace la comparación en tiempo constante, cerrando el vector de timing attack más barato. Si Johan habilita bind no-local, este riesgo sube de categoría — ver fila siguiente. |
| Bind fuera de localhost expone el listener a la red sin TLS (v1 no soporta HTTPS) | `WebhookListener.start()` emite un `logger.warning` explícito y no silencioso cuando `bind_host` no es loopback, tal como exige la restricción de diseño del REQ. Se documenta expresamente: si Johan alguna vez saca el bind de localhost, TLS deja de ser opcional — v1 no lo implementa, así que esa combinación (bind no-local sin TLS) queda fuera de lo que este REQ considera seguro; cualquier REQ futuro que habilite bind no-local debe traer TLS junto. |
| Payload corrupto o de tamaño excesivo cuelga o crashea el listener | `Content-Length` se valida antes de leer el cuerpo (tope 16 KB, responde 413 sin leerlo); parseo del cuerpo envuelto en `try/except` con respuesta 400 sin propagar la excepción al hilo del servidor. `ThreadingHTTPServer` aísla cada request en su propio hilo — un cuerpo problemático en una conexión no bloquea ni tumba las demás. |
| Puerto queda en estado zombie tras un cierre abrupto o reinicio | `WebhookListener.stop()` llama `server.shutdown()` + `server.join()` + `server.server_close()` explícitamente, invocado desde el mismo punto de salida (`main.py`, opción `'q'`) donde ya se detiene `proactive_engine`/`task_scheduler`. |
| Colisión de `webhook_id` entre dos flujos | Determinístico por diseño: se disparan todos los triggers que matchean, nunca se descarta uno en silencio; cada colisión queda además logueada con `logger.warning` listando los agentes involucrados. |
| El canal `WEBHOOK` termina habilitando de más por un futuro descuido en `CHANNEL_ACTION_EXCEPTIONS` | La excepción agregada es de una sola acción (`"proactive_trigger"`), con un comentario en código que deja explícito que NO habilita ninguna acción concreta — el gate real sigue siendo el de cada paso de flujo, sin tocar. Cubierto además por el mismo test que ya existe (o debería existir) sobre `CHANNEL_ALLOWED_LEVELS`/`CHANNEL_ACTION_EXCEPTIONS` para verificar que la lista de excepciones no crece sin ser advertida. |
| Secreto HMAC filtrado en logs o auditoría | El secreto solo se lee de `ORION_WEBHOOK_SECRET` (variable de entorno), nunca se persiste en `config.json` ni se agrega a `_ENV_KEY_MAP` con fallback a archivo (deliberadamente distinto del patrón de las demás API keys, más estricto). `_detalles_seguros()` construye el `details` de auditoría con una allowlist explícita (`webhook_id`, resultado) que nunca incluye el header de firma ni el cuerpo del request. |
| Un flujo con `horario="webhook:<id>"` mal formado (id con caracteres raros) rompe el enrutamiento del path HTTP | `WEBHOOK_ID_RE` es la única fuente de verdad del formato válido, compartida entre `skills/flow_skill.py` (al crear el flujo) y `core/webhook_listener.py` (al recibir el request) — un id inválido nunca llega a registrarse como trigger. |
| Primer punto de entrada externo de todo el sistema proactivo — superficie nueva en sí misma | Es precisamente el motivo por el que esta arquitectura queda pendiente de aprobación personal de Johan (no autoaprobable) y por el que `orion-security` es parada obligatoria antes de `orion-dev`, según lo fijado desde `orion-coordinador`. |

## Pruebas sugeridas

Una por cada criterio de aceptación de SPEC-023 (siguiendo `.claude/rules/testing.md`: sin
red externa real, `tmp_path`/mocks donde aplique):

1. **CA-1** — `config.json` sin la clave `webhook` (o con `enabled: false`) → `WebhookListener().start()` no crea ningún `HTTPServer` (mock/spy sobre el constructor, o verificación de que `socket.connect_ex` al puerto configurado falla).
2. **CA-2** — Con `enabled: true` y sin `bind_host` explícito, el `WebhookListener` construido usa `("127.0.0.1", <puerto>)` como `server_address` (assert directo, sin depender de red real).
3. **CA-3** — Request `POST` con firma ausente o incorrecta contra un handler de prueba → responde 401, `proactive_engine.fire_webhook` (mockeado) **no** se llama, y `security_manager.get_audit_log()` registra `"rechazada_firma_invalida"`.
4. **CA-4** — Trigger registrado con `schedule="webhook:deploy-ok"`, request firmado correctamente hacia `/webhook/deploy-ok` → `fire_webhook` retorna `disparados=1`, `trigger.agent.execute` se llama exactamente una vez, `trigger.last_fired` se actualiza.
5. **CA-5** — Request firmado correctamente hacia `/webhook/no-existe` → `fire_webhook` retorna `motivo="no_registrado"`, handler responde 404, sin `agent.execute` llamado.
6. **CA-6** — Trigger de un flujo con un paso clasificado `YELLOW`/`RED` disparado vía `fire_webhook()` → el paso no se ejecuta sin confirmación (verificable interceptando `action_registry.execute_action`/`security_manager.require_confirmation` y comprobando que se evalúa con `ChannelType.UNKNOWN`, igual que un disparo por `daily:HH:MM`).
7. **CA-7** — Test unitario directo: `CHANNEL_ALLOWED_LEVELS[ChannelType.WEBHOOK] == []` y `(ChannelType.WEBHOOK, "proactive_trigger") in CHANNEL_ACTION_EXCEPTIONS`, y ningún otro `(ChannelType.WEBHOOK, *)` presente.
8. **CA-8** — Cada rama (401, 404, 200, 413, 400) deja exactamente una fila nueva en `audit_log` cuyo campo `details` no contiene el valor del header de firma usado en el request de prueba (aserción `not in`).
9. **CA-9** — Registrar el mismo flujo dos veces vía `programar()` (simulando reinicio) → `proactive_engine.triggers_activos()` contiene un solo trigger con ese `schedule`; `WebhookListener.start()` llamado dos veces seguidas no intenta un segundo bind (mock del constructor de `ThreadingHTTPServer`, verificar una sola llamada).
10. **CA-10** — Suite completa de este documento cumple la cobertura pedida; correr `pytest tests/ --tb=short -v` completo al final y confirmar que no se introducen fallos nuevos respecto del baseline (`2 failed` ya documentados en `baseline-023.md`, ambos ajenos a este REQ).

Casos borde adicionales (de la sección "Casos borde" de SPEC-023, no listados como CA
numerado pero exigidos):
- Opt-in activo sin `ORION_WEBHOOK_SECRET` configurado → `start()` no abre el listener (log de error), test dedicado.
- Payload > 16 KB → 413 sin leer el cuerpo.
- Payload con bytes no-UTF8/corrupto → 400, listener sigue sirviendo el siguiente request (test con dos requests consecutivos, el segundo válido, sobre el mismo servidor).
- Dos triggers con el mismo `webhook_id` → ambos se disparan, `logger.warning` emitido (capturable con `caplog`).

## Decisiones que quedan explícitamente abiertas para `orion-security`

No las resuelve esta arquitectura — se listan para que `orion-security` (parada obligatoria
siguiente, no opcional) las audite con foco de seguridad, no de diseño funcional:

1. ¿16 KB es un tope de payload razonable, o debería ser configurable/menor?
2. ¿El formato de firma `X-Webhook-Signature-256: sha256=<hex>` (calco literal del de
   GitHub) es el más adecuado, o conviene un esquema propio con nonce/timestamp para cerrar
   ataques de replay (un request capturado y reenviado tal cual sigue siendo válido hoy —
   HMAC sobre el cuerpo no incluye protección temporal)?
3. ¿Debe el listener, además del log de auditoría, notificar activamente a Johan (Telegram/
   notificación de escritorio) ante N rechazos consecutivos por firma inválida, como señal
   temprana de un intento de ataque?
4. Confirmar que `ThreadingHTTPServer` (un hilo por request, sin límite superior) no abre una
   vía de agotamiento de recursos si alguien manda muchas conexiones simultáneas — evaluar si
   hace falta un límite explícito de hilos/conexiones concurrentes en v1.

## DoD de `orion-architect` — verificación

```
[x] Propuesta referencia cada criterio de la SPEC (tabla "Cobertura de criterios")
[x] Módulos, clases y funciones especificados
[x] Flujo de datos documentado
[x] Dependencias nuevas identificadas (ninguna)
[x] Riesgos con mitigación documentados
[x] Pruebas sugeridas listadas (una por CA + casos borde)
[ ] Aprobación humana explícita recibida antes de continuar — PENDIENTE, no autoaprobable
    bajo la autorización nocturna del 2026-09-06 (ver nota al inicio de este documento)
[ ] Contexto actualizado, CSV actualizado (Estado → ARQUITECTURA_APROBADA) — NO SE HACE EN
    ESTE PASO. Estado permanece en EN_ARQUITECTURA hasta la aprobación personal de Johan.
```
