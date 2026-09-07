# Contexto REQ-023 — Disparador proactivo por webhook externo en core/proactive_engine.py

## Resumen ejecutivo
Agregar un disparador proactivo por webhook externo a `core/proactive_engine.py`: que un
servicio externo (vía una petición HTTP) pueda disparar una acción proactiva del agente,
complementando los triggers programados por horario que ya existen (`startup`/`hourly`/
`daily:HH:MM`). Es la mitad que falta del heartbeat de la Fase 2 del roadmap inspirado en
OpenClaw — la otra mitad (triggers por horario) ya existe y está en producción, usada por
`core/flows.py` y `skills/flow_skill.py`.

## Estado actual
- **Estado tracker:** NUEVO
- **Último agente:** orion-coordinador
- **Fecha última actualización:** 2026-09-06
- **Rama git:** —
- **Categoría:** SEGURIDAD
- **Tipo de cambio:** FEATURE_NUEVA + SEGURIDAD

## Decisiones tomadas
2026-09-06 | orion-coordinador | REQ creado — categoría=SEGURIDAD (no AUTOMATIZACION) | Un
webhook es un listener HTTP: superficie de red nueva, alcanzable potencialmente por
cualquiera, no solo por Johan. El propio código del proyecto ya clasifica los webhooks como
"canal de entrada NO CONFIABLE" en los comentarios de `core/security_manager.py` (líneas
~65 y ~81), en la misma categoría que el correo: "origina cualquiera del planeta". Por eso
este REQ se categoriza como SEGURIDAD desde el arranque, aunque la funcionalidad de fondo
(disparar una acción proactiva) es de naturaleza AUTOMATIZACION.

2026-09-06 | orion-coordinador | REQ creado bajo autorización nocturna en bloque del
2026-09-06 | Documentada en memoria persistente del proyecto
(`project_autorizacion_nocturna_2026-09-06`). Johan autorizó seguir el pipeline sin pausas
de aprobación y abrir REQs nuevos sin preguntar mientras duerme. Límites duros que esa
autorización NO toca y siguen vigentes sin excepción: nunca `git commit`/`push`/`merge`/
`rebase`/crear rama, nunca acciones 🔴 Rojo. Cualquier aprobación de spec/arquitectura
autoaprobada en nombre de Johan bajo esta autorización debe quedar documentada
explícitamente como "aprobada bajo autorización nocturna en bloque del 2026-09-06" — nunca
como si él la hubiera revisado personalmente.

## Restricción de diseño obligatoria (impuesta desde el arranque de este REQ — no discutible en spec/arquitectura)

Por ser un listener HTTP nuevo, la spec y la arquitectura de este REQ DEBEN exigir, como
mínimo y sin excepción:

- **Apagado por defecto**: opt-in explícito en `config.json`, nunca activo out-of-the-box.
- **Bind solo a localhost/127.0.0.1 por defecto** — nunca expuesto a la red externa sin que
  el usuario lo saque explícitamente de ese default (y eso, si se ofrece, debe ir marcado
  como decisión que requiere entender el riesgo).
- **Autenticación obligatoria de cada request entrante** (secreto compartido / firma HMAC
  tipo lo que usa GitHub para sus webhooks) — nunca un endpoint que ejecute una acción con
  un payload sin verificar quién lo mandó.
- **La acción que el webhook puede disparar debe pasar por el mismo gate de seguridad
  verde/amarillo/rojo** que cualquier otra acción (nunca un atajo que se salte
  `security_manager`), y el canal efectivo para ese gate debe tratarse como no confiable
  (ver `CHANNEL_ALLOWED_LEVELS`/`ChannelType` en `core/security_manager.py` — probablemente
  necesite su propio `ChannelType` o reusar el criterio más restrictivo existente).
- **`orion-security` es OBLIGATORIO en el flujo de este REQ** (no opcional). Ningún agente
  posterior debe saltarlo.

## INSTRUCCIÓN ESPECIAL — leer antes de avanzar arquitectura (verbatim, no parafrasear)

> Aunque este REQ corre bajo la autorización nocturna en bloque del 2026-09-06 (que permite
> autoaprobar spec/arquitectura en nombre de Johan mientras duerme), **la aprobación de la
> ARQUITECTURA de este REQ específico NO debe autoaprobarse bajo esa autorización** — debe
> quedar pausada esperando la revisión personal de Johan, precisamente porque abre una
> superficie de red nueva hacia su PC y es una decisión que él debería mirar con sus propios
> ojos, no delegar. La SPEC sí puede seguir el flujo normal de autoaprobación nocturna
> (definir CA testeables, alcance, sin tomar decisiones de seguridad de fondo todavía).

**Para quien retome este REQ** (el coordinador mismo más tarde, orion-spec, orion-architect,
o Johan al despertar): `orion-spec` puede autoaprobar la SPEC bajo la autorización nocturna
normalmente. Pero cuando el flujo llegue a `orion-architect` y la propuesta de arquitectura
esté lista, **el REQ se detiene ahí en estado ARQUITECTURA propuesta pero NO aprobada**,
esperando que Johan la revise personalmente y dé el OK explícito. No autoaprobar ese paso
bajo ningún argumento de la autorización nocturna.

## Descartado (y por qué)
<!-- Opciones evaluadas y rechazadas — evita repetir el debate -->

## Asumidos pendientes de confirmar
- Que el mecanismo de autenticación preferido sea HMAC tipo GitHub (secreto compartido +
  firma de payload) — a confirmar/detallar en spec.
- Que el catálogo de acciones disparables por webhook en v1 sea acotado (no "cualquier
  acción del agente"), en línea con el criterio de REQ-019 (techo de nivel ofertable) — a
  definir en spec/arquitectura.

## Riesgos activos
- Superficie de red nueva expuesta hacia el PC de Johan si el bind/autenticación se
  implementan mal — por eso `orion-security` es obligatorio y la arquitectura requiere
  aprobación humana personal (ver instrucción especial arriba).
- Posible confusión de flujo: la SPEC sí se autoaprueba bajo autorización nocturna, pero la
  ARQUITECTURA no — cualquier agente que retome debe respetar esa asimetría explícitamente.

2026-09-06 | orion-spec | SPEC redactada — SPEC-023.md | Alcance: nuevo tipo de disparador
`webhook` en `ProactiveTrigger`/`proactive_engine`, listener HTTP opt-in, autenticación
obligatoria, bind localhost por defecto, gate de `security_manager` con canal no confiable.
v1 acotado a triggers ya registrados (no "cualquier acción"), sin UI de configuración, sin
reintentos/colas. Detalle completo en
`workspace/adjuntos/REQ-023/spec/SPEC-023.md`.

2026-09-06 | orion-spec | SPEC aprobada bajo autorización nocturna en bloque del 2026-09-06
| Aprobada en nombre de Johan según `project_autorizacion_nocturna_2026-09-06` (memoria
persistente) — **no fue revisada personalmente por Johan**. Esta autoaprobación cubre
únicamente la SPEC, no la arquitectura de este REQ (ver instrucción especial ya registrada
más arriba en este contexto, reiterada abajo).

2026-09-06 | orion-spec | Tipo de cambio: FEATURE_NUEVA + SEGURIDAD | Identificado en la
entrevista/contexto — nuevo disparador (funcionalidad) sobre una superficie de red nueva
(seguridad), consistente con lo que ya había anotado orion-coordinador.

2026-09-06 | orion-spec | Recordatorio explícito para orion-baseline/orion-architect | La
autorización nocturna del 2026-09-06 permitió autoaprobar esta SPEC, pero **NO cubre la
aprobación de la arquitectura de este REQ**. `orion-architect` debe dejar su propuesta en
estado pausado esperando revisión personal explícita de Johan (por la superficie de red
nueva), sin excepción ni atajo. `orion-security` sigue siendo obligatorio en el flujo, no
opcional.

## Estado actual (actualización orion-spec)
- Estado tracker: SPEC_APROBADO
- Último agente: orion-spec
- SPEC: `workspace/adjuntos/REQ-023/spec/SPEC-023.md` (✅ COMPLETADO, aprobada bajo
  autorización nocturna, no por revisión personal de Johan)
- Próxima pausa obligatoria de revisión humana real: al final de `orion-architect` en este
  mismo REQ — no antes, no la SPEC.

## Log de transiciones
2026-09-06 | — → NUEVO | orion-coordinador | REQ creado, categoría SEGURIDAD, delegado a orion-spec
2026-09-06 | NUEVO → SPEC_APROBADO | orion-spec | SPEC-023.md redactada y autoaprobada bajo
autorización nocturna en bloque del 2026-09-06 (no revisión personal de Johan). Handoff a
orion-baseline, con recordatorio explícito de la pausa obligatoria de arquitectura.

2026-09-07 | orion-baseline | Baseline documentado — `workspace/adjuntos/REQ-023/origen/baseline-023.md`
| Estado actual leído línea por línea de `core/proactive_engine.py`,
`core/security_manager.py`, `core/flows.py`, `skills/flow_skill.py`, `config_manager.py`,
`main.py`, `core/mcp_oauth.py`. Hallazgos clave para `orion-architect` (documentados, no
resueltos por mí):
- `proactive_engine._check_triggers()` línea 118 usa `ChannelType.DESKTOP` HARDCODEADO
  para el gate de `"proactive_trigger"` — el canal más permisivo del sistema. Ningún
  trigger hoy (interno) lo evita, pero un trigger `webhook` heredaría ese mismo canal
  permisivo si se dispara por el mismo camino sin un cambio deliberado. La arquitectura
  tiene que decidir cómo el disparo por webhook usa un canal no confiable en ese punto
  (o en uno nuevo), sin afectar a `startup`/`hourly`/`daily:HH:MM` existentes.
- `_should_fire()` no reconoce ningún `schedule` fuera de `startup`/`hourly`/
  `daily:HH:MM` — un trigger `schedule="webhook"` no se dispararía nunca por el loop de
  polling de 60s tal cual está hoy; necesita su propio camino de disparo (el listener
  HTTP llamando algo equivalente a lo que hace `_check_triggers()` para ese trigger
  puntual).
- El proceso proactivo es HOY 100% interno: `main.py` (triggers fijos + email watcher) y
  `core/flows.py`/`skills/flow_skill.py` (triggers de flujos programados) son los únicos
  que llaman `register_trigger()`, siempre en el mismo proceso Python. El webhook sería
  el primer punto de entrada externo de todo el sistema proactivo.
- `ChannelType` (core/security_manager.py líneas 59-69) NO tiene hoy ningún valor para
  webhook. El comentario de la línea 65-67 ya anticipa el caso textualmente: "Canal de
  entrada NO CONFIABLE: correo, webhooks, cualquier texto que un tercero pueda originar
  sin ser un usuario autorizado." `CHANNEL_ALLOWED_LEVELS[ChannelType.EMAIL] = []` (línea
  96) es hoy el único canal con lista vacía — candidato directo a reusar o a imitar con
  un `ChannelType` nuevo igual de restrictivo, tal como pide SPEC-023.
- `core/mcp_oauth.py` (líneas 41, 254-287) es el ÚNICO listener HTTP existente en el
  proyecto hoy: stdlib `http.server.HTTPServer` bind a `127.0.0.1` — precedente de
  patrón (no de código a reusar directo: es un callback OAuth de corta vida, no un
  listener persistente de acciones). No hay Flask/FastAPI/aiohttp/uvicorn en
  `requirements.txt` ni en ningún import del repo — si arquitectura elige stdlib, no
  hace falta dependencia nueva.
- `config_manager.py` ya tiene el patrón exacto reusable: `get_telegram_autostart()`/
  `set_telegram_autostart()` (opt-in/out booleano en `config.json`, líneas 194-212;
  fail-open a propósito por estar ya acotado por canal — para el webhook el mismo patrón
  aplicaría invertido, fail-closed por defecto) y `_ENV_KEY_MAP` (líneas 26-34, patrón ya
  usado por Telegram/Discord/API keys) para el secreto HMAC, nunca en `config.json` en
  texto plano.
- `python -m py_compile` sobre los 7 módulos afectados: OK, sin errores.
- `pytest tests/ --tb=line -q`: **2 failed, 1761 passed**. Ambos fallos son AJENOS a
  REQ-023: (1) `test_task_slots.py::test_la_hora_dicha_se_respeta` — pre-existente,
  dependiente de la hora del sistema. (2)
  `test_webview_buttons.py::test_el_selector_de_modelo_muestra_el_activo_y_lo_cambia` —
  ruido de REQ-022 en curso en paralelo: verificado con `git status -uall`, que muestra
  `ui/webview/bridge.py` y ese mismo archivo de test modificados sin commitear
  (trabajo activo del `orion-dev` de REQ-022 sobre `ai/llm_provider.py`,
  `core/reasoning_loop.py`, `ui/tts_engine.py`, `ui/webview/bridge.py`). REQ-023 no toca
  ninguno de esos archivos, así que no hay solapamiento real.
- Archivos que este REQ modificará (confirmado por lectura directa, coincide con
  SPEC-023 §"Módulos afectados"): `core/proactive_engine.py`, `core/security_manager.py`,
  `core/flows.py`/`skills/flow_skill.py` (si aplica), `config.json`/`config_manager.py`,
  módulo nuevo (listener HTTP), `main.py` (arranque/apagado del listener),
  `requirements.txt` (solo si se elige un framework externo en vez de stdlib).

⚠️ RECORDATORIO PROPAGADO (no generado por mí, ya estaba en este contexto y en
SPEC-023.md — lo repito para que `orion-architect` no lo pierda): la aprobación de la
ARQUITECTURA de este REQ específico **NO se autoaprueba bajo la autorización nocturna del
2026-09-06**. Debe quedar pausada esperando revisión personal explícita de Johan, por la
superficie de red nueva hacia su PC. `orion-security` sigue siendo obligatorio en el
flujo, no opcional. Yo (orion-baseline) no tomé ninguna decisión de diseño ni de
seguridad en este documento — solo documenté el estado actual del sistema.

Handoff a `orion-architect`.

## Estado actual (actualización orion-baseline)
- Estado tracker: EN_ARQUITECTURA
- Último agente: orion-baseline
- Baseline: `workspace/adjuntos/REQ-023/origen/baseline-023.md` (✅ COMPLETADO)
- Próxima pausa obligatoria de revisión humana real: al final de `orion-architect` en
  este mismo REQ — sigue vigente, no se resuelve ni se salta en este paso.

## Decisiones tomadas (orion-architect)
2026-09-07 | orion-architect | Nuevo `ChannelType.WEBHOOK` propio (no reusar `EMAIL`
literal) con `CHANNEL_ALLOWED_LEVELS` vacío, igual de restrictivo que `EMAIL` | Permite que
`audit.db` distinga forense un intento de webhook de un evento de correo — son superficies
de ataque distintas aunque ambas "no confiables". Cumple el CA de la SPEC que exige "reusa
EMAIL o un ChannelType nuevo igual de restrictivo".

2026-09-07 | orion-architect | Excepción quirúrgica única `(ChannelType.WEBHOOK,
"proactive_trigger")` en `CHANNEL_ACTION_EXCEPTIONS`, mismo patrón que las 4 de REQ-018 |
Sin ella el webhook no podría disparar nada (proactive_trigger es GREEN, WEBHOOK no permite
ningún nivel). La excepción habilita solo esa acción-contenedora; el gate real de cada
acción concreta sigue sin tocar, más abajo, en `flows.ejecutar(canal=ChannelType.UNKNOWN)`.

2026-09-07 | orion-architect | `_should_fire()` gana una rama `webhook:` que retorna
`False` siempre, y el disparo real ocurre por un método nuevo y separado
`ProactiveEngine.fire_webhook()`, sin tocar ni una línea de `_check_triggers()` | Resuelve
el hallazgo de `orion-baseline` (ChannelType.DESKTOP hardcodeado en `_check_triggers()`
línea 118) por exclusión — un trigger webhook nunca entra a ese camino — en vez de parchear
la función existente. Riesgo de regresión mínimo sobre `startup`/`hourly`/`daily:HH:MM`.

2026-09-07 | orion-architect | stdlib `http.server.ThreadingHTTPServer`, sin dependencia
nueva, mismo precedente que `core/mcp_oauth.py` | `ThreadingHTTPServer` en vez de
`HTTPServer` simple para que una conexión lenta/corrupta no bloquee otras — costo cero,
sigue siendo stdlib.

2026-09-07 | orion-architect | Secreto (`ORION_WEBHOOK_SECRET`) leído SOLO de variable de
entorno, deliberadamente sin agregarlo a `_ENV_KEY_MAP` (que sí cae a `config.json` como
fallback para las demás API keys) | Más estricto que el patrón existente: garantiza que el
secreto del webhook nunca pueda terminar en `config.json` en texto plano ni por accidente,
ni siquiera como fallback.

2026-09-07 | orion-architect | Colisión de `webhook_id` entre dos triggers: se disparan
TODOS los que coincidan, nunca se descarta uno en silencio; se loguea `WARNING` con la
lista de agentes involucrados | Determinístico, cumple el caso borde de la SPEC sin acoplar
`programar()` a una consulta cruzada de otros flujos en el momento del registro.

## Descartado (y por qué)
2026-09-07 | orion-architect | Rechazar en el registro un segundo trigger con el mismo
`webhook_id` (en vez de disparar todos) | Requeriría que `core/flows.py::programar()`
consulte `flow_store` completo buscando colisiones en el momento de programar cada flujo —
acoplamiento nuevo no justificado quedando "fire-all + warning" igual de determinístico y
mucho más simple.

2026-09-07 | orion-architect | Parchear directamente la línea 118 de
`_check_triggers()` para que reciba un canal dinámico según el trigger | Se descarta a
favor de mantener `_check_triggers()` intocado y desviar los triggers webhook a un método
nuevo (`fire_webhook()`) desde `_should_fire()`: menor superficie de cambio sobre código que
hoy funciona correctamente para `startup`/`hourly`/`daily:HH:MM`.

## Cierre de este paso — orion-architect (2026-09-07)

**Arquitectura redactada y lista, PENDIENTE de aprobación humana personal de Johan — NO
autoaprobada bajo autorización nocturna, por abrir superficie de red nueva.**

Documento completo: `workspace/adjuntos/REQ-023/propuestas/arquitectura-023.md`. Cumple el
DoD de `orion-architect` en su totalidad salvo, deliberadamente, el punto de aprobación
humana: cubre cada criterio de aceptación de SPEC-023 uno por uno, especifica módulos/
clases/funciones (incluyendo el `ChannelType.WEBHOOK` nuevo, `ProactiveEngine.fire_webhook()`,
y el módulo nuevo `core/webhook_listener.py`), documenta el flujo de datos completo, confirma
que no hace falta ninguna dependencia nueva (`http.server`/`ThreadingHTTPServer`, stdlib),
lista riesgos con mitigación, y deja pruebas sugeridas una por cada CA.

Aunque el resto de esta sesión corre bajo la autorización nocturna en bloque del
2026-09-06 (que permite autoaprobar spec/arquitectura en nombre de Johan mientras duerme),
**esta arquitectura específica NO se autoaprueba bajo esa autorización**. El motivo, ya
fijado desde `orion-coordinador` y repetido por `orion-spec` y `orion-baseline`: este REQ
abre el primer listener HTTP entrante persistente de todo O.R.I.O.N., una superficie de red
nueva hacia el PC de Johan — es una decisión que él debe revisar personalmente, despierto,
con sus propios ojos, no delegar a otro agente en su nombre bajo un bloque de autorización
pensado para decisiones de menor calado.

**Quien retome este REQ debe entender lo siguiente sin ambigüedad:**
- El siguiente paso NO es `orion-security` ni `orion-dev` todavía. El siguiente paso es que
  **Johan lea `arquitectura-023.md` personalmente** y responda de forma explícita
  `APROBADO` / `AJUSTAR [qué]` / `RECHAZADO [motivo]`.
- Solo después de esa respuesta explícita y personal, el flujo continúa a `orion-security`
  (parada obligatoria, no opcional, ya fijada desde el arranque de este REQ) y luego a
  `orion-dev`.
- Ningún otro agente de este pipeline —ni siquiera bajo la autorización nocturna— está
  autorizado a marcar `Aprobacion_Arquitectura` como `APROBADO` en el CSV para este REQ en
  nombre de Johan. Si algún agente futuro se siente tentado a "destrabar" el REQ porque
  lleva tiempo esperando, debe releer esta entrada y la nota al inicio de
  `arquitectura-023.md` antes de hacer nada.

## Estado actual (actualización orion-architect)
- Estado tracker: **EN_ARQUITECTURA** (sin avanzar — no pasa a ARQUITECTURA_APROBADA)
- Último agente: orion-architect
- Arquitectura: `workspace/adjuntos/REQ-023/propuestas/arquitectura-023.md` (documento
  completo, ⏸️ PENDIENTE de aprobación personal de Johan)
- Aprobación de arquitectura: PENDIENTE — no autoaprobada, no autoaprobable bajo
  autorización nocturna del 2026-09-06
- Próxima acción: esperar respuesta explícita de Johan sobre `arquitectura-023.md`.
  Después: `orion-security` (obligatorio) → `orion-dev`.
- Rama git: — (sin asignar; no corresponde crearla hasta que arquitectura esté aprobada)
