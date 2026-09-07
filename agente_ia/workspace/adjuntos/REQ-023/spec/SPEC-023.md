# SPEC-023 — Disparador proactivo por webhook externo

**Estado:** ✅ COMPLETADO (aprobada bajo autorización nocturna en bloque del 2026-09-06)
**Categoría:** SEGURIDAD
**Tipo:** FEATURE_NUEVA + SEGURIDAD
**Fecha:** 2026-09-06

## Objetivo
`core/proactive_engine.py` solo dispara acciones proactivas por horario (`startup`,
`hourly`, `daily:HH:MM`, vía `ProactiveTrigger`/`register_trigger`). No existe forma de que
un evento externo (un servicio de terceros, otra máquina, un CI, un sensor) provoque una
acción proactiva en el momento en que ocurre — solo se puede esperar al siguiente tick del
scheduler. Este REQ agrega un cuarto tipo de disparador, `webhook`, que permite que una
petición HTTP entrante dispare un `ProactiveTrigger` ya registrado, sin reemplazar ni
debilitar los disparadores por horario existentes.

Por ser un listener HTTP nuevo (superficie de red alcanzable por cualquiera que llegue al
puerto, no solo por Johan), este REQ se clasifica y trata como SEGURIDAD de punta a punta,
no como AUTOMATIZACION.

## Alcance
- Incluye:
  - Un nuevo tipo de disparador `webhook` para `ProactiveTrigger` / `proactive_engine`,
    registrable igual que `startup`/`hourly`/`daily:HH:MM` (vía `core/flows.py` /
    `skills/flow_skill.py`, mismo mecanismo de registro existente).
  - Un listener HTTP que recibe la petición externa y, si pasa autenticación, dispara el
    trigger `webhook` correspondiente.
  - Configuración de opt-in en `config.json` para habilitar el listener (apagado por
    defecto).
  - Autenticación obligatoria de cada request entrante (secreto compartido / firma tipo
    HMAC) antes de disparar cualquier acción.
  - Bind por defecto restringido a localhost/127.0.0.1.
  - Que la acción disparada por el webhook pase por `security_manager` (gate
    verde/amarillo/rojo) igual que cualquier otra acción del agente, con el canal
    correspondiente tratado como NO CONFIABLE (mismo criterio que `ChannelType.EMAIL` en
    `core/security_manager.py`, que hoy tiene `CHANNEL_ALLOWED_LEVELS` vacío).
  - Logging de cada request entrante (aceptado o rechazado) y de cada acción disparada,
    siguiendo el patrón de `security_manager.log_action()` / auditoría existente.
- No incluye (queda fuera de v1, a definir en arquitectura si aplica):
  - Exponer el webhook a internet por defecto o con ayuda de túneles/reverse proxy — no es
    responsabilidad de este REQ.
  - Un catálogo abierto de "cualquier acción del agente" disparable por webhook — v1 se
    limita a disparar `ProactiveTrigger`s ya registrados por flujos existentes, igual que
    hoy hace `hourly`/`daily`.
  - UI de configuración gráfica para el webhook (activarlo/generar el secreto vía
    interfaz) — v1 puede ser solo `config.json` + variable de entorno para el secreto.
  - Reintentos, colas o garantías de entrega — si el listener no está corriendo, el evento
    se pierde (igual que un `daily:HH:MM` que ocurre con la app apagada).
  - Definir el mecanismo HTTP concreto (librería, puerto, forma exacta de la firma) — eso
    es diseño de implementación, corresponde a `orion-architect`.

## Módulos afectados
- `core/proactive_engine.py` — nuevo tipo de disparador `webhook` en `ProactiveTrigger`;
  la lógica de disparo por evento externo vive acá o en un módulo nuevo que este archivo
  importa (a decidir en arquitectura).
- `core/security_manager.py` — posible nuevo `ChannelType` (p. ej. `WEBHOOK`) o reuso del
  criterio más restrictivo existente (`ChannelType.EMAIL`) en `CHANNEL_ALLOWED_LEVELS`; el
  gate de `require_confirmation()`/`register_action()` se invoca desde el nuevo camino de
  ejecución igual que en los demás puntos de entrada (ver `security-levels.md`, sección
  REQ-005).
- `core/flows.py` / `skills/flow_skill.py` — si el registro de un flujo con disparador
  `webhook` se hace desde el mismo flujo declarativo que hoy usa `schedule` para
  `startup`/`hourly`/`daily:HH:MM`.
- `config.json` — nueva sección de configuración opt-in para el listener (apagado por
  defecto, bind, y referencia al secreto — el secreto en sí NO va en `config.json` sino en
  variable de entorno / `.env`, igual que las demás API keys del proyecto).
- Módulo nuevo (nombre a definir en arquitectura, ej. `core/webhook_listener.py`) — el
  servidor HTTP en sí. `core/mcp_oauth.py` ya usa `http.server` (stdlib) en este proyecto
  para un listener HTTP local; sirve como precedente a evaluar en arquitectura, sin que
  esta SPEC prescriba la librería.

## Comportamiento actual vs deseado
| Actual | Deseado |
|--------|---------|
| Un `ProactiveTrigger` solo se dispara por `startup`, `hourly` o `daily:HH:MM`, evaluado por el loop interno de `proactive_engine._run_loop()`. | Un `ProactiveTrigger` también puede tener `schedule="webhook"` (o equivalente) y dispararse cuando llega una petición HTTP autenticada dirigida a él, además de por horario. |
| No existe ningún listener HTTP de entrada en el proyecto (fuera de `core/mcp_oauth.py`, que es saliente/callback OAuth, no un endpoint de acción). | Existe un listener HTTP opt-in, apagado por defecto, bind a localhost por defecto, que solo acepta requests autenticados y solo puede disparar `ProactiveTrigger`s ya registrados. |
| No hay concepto de "canal webhook" en `security_manager.py`. | El canal del webhook está clasificado explícitamente en `ChannelType`/`CHANNEL_ALLOWED_LEVELS` como no confiable, con el mismo criterio (o más restrictivo) que `ChannelType.EMAIL`. |

## Criterios de aceptación
- [ ] Con el listener de webhook deshabilitado (default de fábrica, `config.json` sin la
      clave de opt-in o con ella en `false`), el proceso de la app **no abre ningún socket
      de escucha** para esta funcionalidad — verificable con un test que arranca la app con
      config por defecto y comprueba que el puerto no está en escucha.
- [ ] Con el listener habilitado y sin bind explícito distinto en `config.json`, el socket
      **solo escucha en 127.0.0.1/localhost** — una conexión dirigida a una IP de red que no
      sea loopback no llega al listener.
- [ ] Un request entrante **sin firma/autenticación válida es rechazado** (HTTP 401/403, sin
      disparar ningún trigger) y queda registrado en el log de auditoría como rechazado.
- [ ] Un request entrante **con firma/secreto correcto y dirigido a un `ProactiveTrigger`
      registrado con `schedule="webhook"`** dispara ese trigger exactamente una vez.
- [ ] Un request entrante autenticado pero **dirigido a un trigger inexistente o no
      registrado como `webhook`** no dispara ninguna acción y responde con un error claro
      (no 200 silencioso).
- [ ] La acción resultante del disparo **pasa por `security_manager`** (se puede verificar
      con un test que registra la acción disparada y comprueba que quedó sujeta al mismo
      gate verde/amarillo/rojo que si viniera de cualquier otro canal) — un trigger cuya
      acción subyacente sea 🟡 o 🔴 **no se ejecuta sin pasar por el flujo de confirmación
      correspondiente** (o queda bloqueada si el canal webhook no tiene ese nivel permitido,
      igual que hoy ocurre con `ChannelType.EMAIL`).
- [ ] El canal usado para el gate de seguridad en este camino **no es `ChannelType.DESKTOP`
      ni ningún canal con niveles amarillo/rojo permitidos por defecto** — reusa
      `ChannelType.EMAIL` o un `ChannelType` nuevo igual de restrictivo, verificable por
      test unitario sobre `CHANNEL_ALLOWED_LEVELS`.
- [ ] Cada request recibido (aceptado o rechazado) y cada disparo de acción quedan
      **registrados en el log de auditoría** con timestamp, resultado, y sin filtrar el
      secreto/firma en texto plano en el log.
- [ ] Reiniciar la app con el listener habilitado **no duplica** el registro del trigger
      `webhook` ni abre más de un socket de escucha.
- [ ] Existen tests automatizados (`agente_ia/tests/`) que cubren: opt-in apagado por
      defecto, bind a localhost, rechazo sin autenticación, disparo correcto autenticado,
      y paso por `security_manager` — siguiendo `.claude/rules/testing.md` (sin red externa
      real, con mocks/`tmp_path` donde aplique).

## Casos borde
- La app arranca con la clave de opt-in en `config.json` pero **sin secreto configurado**
  (ni en env ni en `.env`): el listener debe negarse a arrancar (o arrancar pero rechazar
  todo) en vez de aceptar requests sin verificar quién los mandó — nunca "modo abierto" por
  falta de configuración.
- Dos triggers distintos registrados con `schedule="webhook"` apuntando al mismo
  identificador de webhook (colisión de nombre): comportamiento a definir en arquitectura,
  pero debe ser determinístico y quedar logueado, no un fallo silencioso.
- Un request llega con la firma correcta pero un **payload corrupto o de tamaño excesivo**:
  debe rechazarse sin intentar ejecutar nada, y sin tumbar el listener para requests
  siguientes.
- El `ProactiveTrigger` disparado por webhook corresponde a una acción **🔴 Rojo**: debe
  bloquearse igual que bloquea hoy `security_manager` para cualquier canal, sin excepción
  ni atajo por venir de un trigger ya "pre-registrado" — el registro previo del trigger no
  es lo mismo que autorización de ejecución en el momento del disparo.
- El listener recibe un **volumen alto de requests inválidos** (posible intento de fuerza
  bruta contra la firma): al menos debe quedar auditado; rate-limiting explícito queda a
  criterio de arquitectura, pero si se descarta debe quedar documentado como decisión, no
  como omisión.
- La app se cierra/reinicia mientras el listener tiene una request en curso: no debe dejar
  el puerto en estado zombie que impida reabrirlo al reiniciar.

## Asumidos
- ASUMIDO: el mecanismo de autenticación es tipo HMAC con secreto compartido (patrón
  webhooks de GitHub) — confirmar el detalle exacto (algoritmo, header, formato) en
  arquitectura.
- ASUMIDO: el catálogo de triggers disparables por webhook en v1 se limita a
  `ProactiveTrigger`s ya registrados explícitamente con `schedule="webhook"` por un flujo
  existente — no un endpoint genérico "ejecutar acción X con estos params" — confirmar en
  arquitectura, en línea con el techo de nivel ofertable de REQ-019.
- ASUMIDO: el secreto de autenticación se lee de variable de entorno / `.env`, nunca
  hardcodeado ni en texto plano en `config.json` — confirmar en arquitectura el nombre
  exacto de la variable.
- ASUMIDO: no es necesario soportar HTTPS/TLS en v1 dado el bind a localhost por defecto —
  si arquitectura decide ofrecer bind no-local, TLS deja de ser opcional y debe quedar
  explícito como requisito adicional en ese escenario.

## Nota de proceso — no discutible, ver contexto del REQ
Esta SPEC fue autoaprobada en nombre de Johan bajo la autorización nocturna en bloque del
2026-09-06 (ver `workspace/adjuntos/REQ-023/REQ-023-context.md` y memoria persistente del
proyecto `project_autorizacion_nocturna_2026-09-06`) — **no fue revisada personalmente por
Johan**. Esa misma autorización **NO aplica a la aprobación de la arquitectura de este REQ**:
`orion-architect` debe dejar la propuesta de arquitectura pausada, esperando revisión
personal explícita de Johan, precisamente por la superficie de red nueva que este REQ abre.
Ningún agente posterior debe saltarse esa pausa ni interpretar la autoaprobación de esta
SPEC como precedente para autoaprobar la arquitectura. `orion-security` es obligatorio en
el flujo de este REQ (no opcional).
