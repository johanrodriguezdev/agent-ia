# OpenClaw — Gateway persistente, contrato de canales y ruteo multi-agente

> **Aviso de terceros.** Los fragmentos de código transcritos en este documento pertenecen a
> [OpenClaw](https://github.com/openclaw/openclaw), Copyright (c) 2026 OpenClaw Foundation,
> licencia MIT. Se reproducen con fines de estudio; el aviso de permiso completo está en
> `THIRD_PARTY_NOTICES.md`. Ningún archivo de código de este proyecto copia ni traduce ese
> código.

**Documento de referencia autosuficiente**
Fecha de análisis: 2026-08-01
Repo analizado: `openclaw-main` (TypeScript/Node, monorepo pnpm, ~24k archivos `.ts`) — *la carpeta se conserva en el proyecto por ahora, pero este documento está escrito para ser autosuficiente: todo el código relevante está transcrito literalmente acá, de modo que si mañana desaparece no se pierde nada.*
Objetivo: entender el modelo de **gateway único persistente**, el **contrato que todo canal debe cumplir** y el **ruteo multi-agente**, con el código transcrito literalmente, para poder reimplementar los patrones útiles en O.R.I.O.N. (Python) sin volver a mirar el original.

> **Convención de este documento**
> - Todo el código está **transcrito literalmente** del repo original. La ruta original se cita como referencia histórica.
> - Se distingue explícitamente entre **[VERIFICADO EN CÓDIGO]** y **[AFIRMACIÓN DE DOCUMENTACIÓN]**.
> - Los hallazgos negativos ("busqué X y no existe") están marcados como tales y son parte del valor del documento.

> **Estado de redacción:** documento **completo**. Se escribió de forma incremental, sección por
> sección, guardando cada una apenas se resolvía. La sección 1 se redactó al final, con el resto ya
> verificado.

---

## Índice

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Protocolo del gateway](#2-protocolo-del-gateway)
3. [Contrato de canal](#3-contrato-de-canal)
4. [Arquitectura del daemon](#4-arquitectura-del-daemon)
5. [Ruteo multi-agente](#5-ruteo-multi-agente)
6. [Límites y debilidades reales](#6-límites-y-debilidades-reales)
7. [Traducción a O.R.I.O.N.](#7-traducción-a-orion)
8. [Alimentación a REQs futuros](#8-alimentación-a-reqs-futuros)

---

## 1. Resumen ejecutivo

### 1.1. El modelo mental en una idea

La diferencia entre OpenClaw y "un bot por canal" no es de tamaño, es de **dirección de la
dependencia**.

En el modelo "un bot por canal" —que es el de O.R.I.O.N. hoy— cada bot **contiene** al asistente: el
handler de Telegram importa el cerebro, lo invoca, y devuelve la respuesta. El asistente es una
biblioteca que los bots usan. Si hay tres bots, hay tres copias del flujo, tres lugares donde
arreglar un bug, y tres órdenes de resolución que pueden divergir sin que nadie lo note (**y en
O.R.I.O.N. ya divergieron** — ver §7.4, punto 3).

En OpenClaw es al revés: **el asistente es un proceso que corre solo, y los canales son enchufes que
se conectan a él.** El canal de Telegram no sabe qué es un LLM. Recibe un mensaje, lo pone en un
sobre, se lo entrega al gateway, y espera. Todo lo que necesita para funcionar se lo da el gateway a
través de una superficie compartida (`channelRuntime`), que incluye responder, rutear, manejar
sesiones, media, comandos y aprobaciones — **pero no incluye llamar al modelo**. Esa es la línea
divisoria del diseño, y está sostenida en el código: revisé el contrato completo y ningún canal tiene
acceso al LLM.

La consecuencia práctica: **agregar un canal nuevo a OpenClaw no toca el núcleo.** Se declara un
objeto con sus capacidades y se registra. Los 19+ canales que existen (Telegram, Discord, Slack, IRC,
Matrix, Signal, iMessage, Google Chat, Nostr, Twitch...) son todos el mismo objeto rellenado
distinto — desde `extensions/raft/src/channel.ts`, que son 102 líneas, hasta los que tienen 350.

### 1.2. Las tres piezas y para qué sirve cada una

| Pieza | Qué resuelve | Cómo |
|---|---|---|
| **Gateway persistente** (§4) | Que exista un solo lugar donde vive el estado y donde se toman las decisiones | Un proceso, un lock de 3 capas, arranque en 5 fases, apagado en 20 pasos que nunca bloquea |
| **Contrato de canal** (§3) | Que agregar un canal no sea modificar el núcleo | `ChannelPlugin`: 31 campos, solo 4 obligatorios. **Composición declarada, no herencia** |
| **Ruteo multi-agente** (§5) | Que un mensaje sepa a qué agente pertenece, con qué contexto y en qué carpeta | 8 tiers de precedencia **como lista de datos**, clave de sesión con el agente como primer segmento |

### 1.3. Las cinco ideas que valen más que su implementación

Si de todo el documento hubiera que quedarse con cinco cosas, son estas — y ninguna requiere copiar
código:

1. **El transporte no es confiable y no pretende serlo; la durabilidad se compra aparte, en SQLite,
   solo donde importa.** Cuando el socket se cae, *todas* las requests en vuelo se rechazan y no se
   reintentan — hay un test cuyo nombre lo dice: `"rejects an unbounded request, reconnects, and does
   not replay it"`. La entrega garantizada existe únicamente para el camino "respuesta del agente →
   usuario", con una cola SQLite donde **la deduplicación vive en la elección de la clave primaria**
   (`entry_id = sha256(idempotency_key)`), no en un `SELECT` previo. Separación limpia entre "rápido"
   y "confiable". Es la lección más transferible del repo. (§4.12, §6.2)

2. **La precedencia de ruteo es una lista de datos, no una cadena de `if/else`.** Los 8 tiers son un
   array recorrido por un loop de 15 líneas. Agregar un criterio es agregar un elemento. Y el
   resultado incluye `matchedBy`: **el ruteo explica por qué eligió lo que eligió**. (§5.3)

3. **Composición declarada en vez de herencia.** `ChannelPlugin` es un objeto con capacidades y
   callables opcionales. Una clase base abstracta obligaría a cada canal a implementar `send_voice()`
   aunque no tenga voz; el objeto deja preguntar `if plugin.health:`. (§3.1)

4. **El estado no se replica, se re-consulta.** No hay buffer de eventos ni replay: hay contadores
   monótonos por dominio (`stateVersion: {presence, health}`) y, si cambiaron, el cliente pide el
   snapshot de nuevo. Evita buffers que crecen sin límite. (§4.7, §6.1b)

5. **`bind` es una política con nombre (`loopback|lan|tailnet|auto`), no un host crudo.** Exponerse a
   la red es una decisión explícita y auditable, no un `"0.0.0.0"` heredado. Este documento encontró
   exactamente ese literal enterrado en `channels/api_channel.py` de O.R.I.O.N. (§4.3, §7.2 B5)

### 1.4. Qué encontré que la documentación no dice

Tres correcciones importantes, todas verificadas:

- **Yo mismo escribí un hallazgo negativo falso en la primera versión de este documento** (§4.5):
  afirmé que no había lock de instancia. Sí lo hay — 550 líneas, con reclamación por start-time de
  PID para resistir el reuso de PID, canonicalización de rutas para que dos symlinks compartan un
  solo lock, y cooperación con systemd vía exit code 78. **Estaba una capa más arriba de donde
  busqué.** La corrección quedó escrita en el documento en vez de borrada, porque la lección vale.
- **"Un contrato de canal" son en realidad ~27 contratos opcionales**, y el modelo de estado no es
  uniforme: los canales webhook necesitan su propio constructor de estado
  (`buildPassiveProbedChannelStatusSummary`), lo cual delata una costura en la abstracción. (§6.3)
- **Un apagado "limpio" no es una garantía.** Cada paso del cierre tiene timeout y degrada a warning
  en vez de bloquear, así que "shutdown completado" significa "mejor esfuerzo, con log". Es la
  decisión correcta, pero no es lo que la palabra sugiere. (§6.4)

### 1.5. La conclusión para O.R.I.O.N., sin adornos

De las tres áreas analizadas:

- **El contrato de canal (§3) es directamente aplicable** y es el mejor REQ de los tres pendientes.
  ~40 líneas de contrato, migración mecánica canal por canal, y desbloquea confirmaciones por
  Telegram sin debilitar la seguridad. **Hacerlo primero.**
- **El gateway persistente (§4) es aplicable solo si se le baja el alcance.** Y hay un dato que
  cambia el planteo: **`start_bots.py` ya es un anfitrión persistente multi-canal con loop de
  supervisión** — que detecta canales caídos y solo los imprime. El REQ no es construir un daemon, es
  terminar el que ya está a medias y unificar el pipeline de resolución que hoy diverge entre
  `main.py` y `channels/gateway.py`.
- **El ruteo multi-agente (§5) no aplica.** Con un usuario y agentes efímeros sin memoria propia, 7
  de los 8 tiers nunca se evaluarían. Lo único rescatable es `identityLinks` —que el mismo humano en
  Telegram y en Discord comparta sesión— y eso es un dict en la config, no un sistema de ruteo.

Y de paso, leyendo el código de O.R.I.O.N. para poder recomendar con fundamento, aparecieron **seis
bugs concretos** (§7.2), incluido uno serio: `_decompose()` en `core/orchestrator.py` parte las
frases por la **letra** "y", de modo que `"ayúdame con el proyecto"` se descompone en
`["a", "údame con el pro", "ecto"]` y cada pedazo se manda a un agente distinto.

**El resumen del resumen**: OpenClaw resuelve problemas de escala, multi-cliente y operación
desatendida. O.R.I.O.N. tiene un usuario, un proceso principal y un humano mirando la pantalla. La
mayor parte de lo que hace robusto a OpenClaw sería, acá, complejidad sin contrapartida. La §7.5
lista pieza por pieza qué **no** copiar y por qué.

---

## 2. Protocolo del gateway

Todo lo de esta sección está **[VERIFICADO EN CÓDIGO]** salvo donde se indique lo contrario.

### 2.1. Dónde vive y cómo está empaquetado

El protocolo NO vive en el servidor: vive en un paquete npm independiente y publicable,
`@openclaw/gateway-protocol` (`packages/gateway-protocol/`). Ese paquete contiene **solo esquemas,
tipos y validadores** — cero lógica de negocio, cero dependencia del core. Servidor, CLI, UI web,
apps nativas y el SDK de plugins consumen el mismo paquete.

Decisión de diseño relevante: el paquete tiene **entry points separados según si necesitás o no el
motor de validación** (TypeBox). Del `README.md` del paquete:

- `@openclaw/gateway-protocol` — validadores runtime, esquemas seleccionados, formateo de errores. Requiere TypeBox.
- `@openclaw/gateway-protocol/schema` — grafo completo de esquemas TypeBox + registro `ProtocolSchemas` para generadores.
- `@openclaw/gateway-protocol/frame-guards` — **guards estructurales sin dependencias** para envelopes.
- `@openclaw/gateway-protocol/client-info` — registros de client id / mode / capabilities + normalizadores.
- `@openclaw/gateway-protocol/connect-error-details` — lectores de errores de conexión estructurados.
- `@openclaw/gateway-protocol/version` — versiones de protocolo actual y mínima aceptada.

> "The `frame-guards`, `client-info`, `connect-error-details`, `gateway-error-details`,
> `startup-unavailable`, and `version` entry points are TypeBox-free. Prefer them when a browser
> bundle only needs envelope dispatch, handshake constants, or reconnect policy."
> — `packages/gateway-protocol/README.md` [AFIRMACIÓN DE DOCUMENTACIÓN, coherente con el código verificado]

**Lección transferible**: separar "lo que necesito para despachar un frame" de "lo que necesito para
validar un payload completo". Un cliente ligero solo necesita lo primero.

### 2.2. Versionado del protocolo

Archivo completo `packages/gateway-protocol/src/version.ts` [VERIFICADO EN CÓDIGO]:

```ts
/** Current gateway protocol version emitted by modern clients and servers. */
export const PROTOCOL_VERSION = 4 as const;
/** Lowest general client protocol version accepted by the gateway. */
export const MIN_CLIENT_PROTOCOL_VERSION = 4 as const;
/** Lowest authenticated node protocol version accepted by the gateway. */
export const MIN_NODE_PROTOCOL_VERSION = 3 as const;
/** Lowest lightweight probe protocol version accepted by the gateway. */
export const MIN_PROBE_PROTOCOL_VERSION = 3 as const;
```

Puntos clave del diseño de versionado:

1. **El número de protocolo del cable es un entero, separado de la versión del paquete npm.** La
   versión npm sigue el tren de releases `YYYY.M.PATCH`; identifica el release fuente, no el
   protocolo.
2. **Ventana de compatibilidad diferenciada por clase de cliente.** Los clientes generales deben
   estar en v4 exacta; los *nodes* autenticados y los *probes* livianos aceptan N-1 (v3) para
   permitir upgrades rolling. Esto es explícito en el código, no una convención.
3. **Los cambios son aditivos primero.** Un cambio incompatible requiere una decisión explícita de
   número de protocolo. En los esquemas se ve el marcador de esa política: campos comentados como
   `// Additive: ...` en `HelloOkSchema`.

### 2.3. El envelope: tres tipos de frame y nada más

Archivo `packages/gateway-protocol/src/schema/frames.ts`, transcrito literalmente (partes centrales)
[VERIFICADO EN CÓDIGO — archivo leído completo, 204 líneas]:

```ts
/** Standard structured error shape used in response frames and connect failures. */
export const ErrorShapeSchema = closedObject({
  code: NonEmptyString,
  message: NonEmptyString,
  details: Type.Optional(Type.Unknown()),
  retryable: Type.Optional(Type.Boolean()),
  retryAfterMs: Type.Optional(Type.Integer({ minimum: 0 })),
});

/** Client request frame envelope; `method` selects the payload validator. */
export const RequestFrameSchema = closedObject({
  type: Type.Literal("req"),
  id: NonEmptyString,
  method: NonEmptyString,
  params: Type.Optional(Type.Unknown()),
  traceparent: Type.Optional(Type.String({ maxLength: 128 })),
});

/** Server response frame envelope paired with a prior request id. */
export const ResponseFrameSchema = closedObject({
  type: Type.Literal("res"),
  id: NonEmptyString,
  ok: Type.Boolean(),
  payload: Type.Optional(Type.Unknown()),
  error: Type.Optional(ErrorShapeSchema),
});

/** Server event frame envelope; `event` selects the payload validator. */
export const EventFrameSchema = closedObject({
  type: Type.Literal("event"),
  event: NonEmptyString,
  payload: Type.Optional(Type.Unknown()),
  seq: Type.Optional(Type.Integer({ minimum: 0 })),
  stateVersion: Type.Optional(StateVersionSchema),
});

// Discriminated union of all top-level frames. Using a discriminator makes
// downstream codegen (quicktype) produce tighter types instead of all-optional
// blobs.
export const GatewayFrameSchema = Type.Union(
  [RequestFrameSchema, ResponseFrameSchema, EventFrameSchema],
  { discriminator: "type" },
);
```

Y el helper que define la estrictez, `packages/gateway-protocol/src/schema/closed-object.ts` (archivo
completo, 5 líneas):

```ts
import { Type, type TProperties } from "typebox";

export function closedObject<Properties extends TProperties>(properties: Properties) {
  return Type.Object(properties, { additionalProperties: false });
}
```

**Explicación de cada tipo de mensaje:**

| `type` | Dirección | Semántica | Correlación |
|---|---|---|---|
| `"req"` | cliente → servidor | RPC. `method` es un string que selecciona el handler **y** el validador de `params`. | `id` (string no vacío), elegido por el cliente |
| `"res"` | servidor → cliente | Respuesta a un `req`. `ok: boolean` decide si se lee `payload` o `error`. | mismo `id` que el `req` |
| `"event"` | servidor → cliente | Push no solicitado. `event` es un string que selecciona el validador del payload. | ninguna — no responde a nada |

Detalles que importan y que se pierden si uno lo mira por encima:

- **Solo tres tipos.** No hay `"notification"` cliente→servidor, no hay streaming de frames parciales
  a nivel envelope. El streaming (tokens del LLM, salida de terminal) va **como eventos** con `seq`.
- **`ok` es un booleano separado de la presencia de `error`.** Es redundante a propósito: permite
  despachar sin inspeccionar el contenido.
- **`error.retryable` y `error.retryAfterMs` son parte del contrato de error**, no una convención de
  la aplicación. El cliente puede decidir reintentar sin conocer el `code`.
- **`traceparent` (máx. 128 chars)** en el request: soporte de trazas distribuidas W3C incrustado en
  el protocolo.
- **`seq` en eventos** es opcional y monótono; sirve para detectar huecos. **`stateVersion`** permite
  al cliente saber si su snapshot quedó viejo.
- **`params`, `payload` y `error.details` son `Type.Unknown()` a propósito.** El README lo declara:
  el envelope es abierto en esos tres puntos porque el `method`/`event`/`code` elegido es el dueño de
  la forma concreta. Todo lo demás es `additionalProperties: false`.

Los tipos TS derivan de los esquemas (no se escriben a mano):

```ts
export type ConnectParams = Static<typeof ConnectParamsSchema>;
export type HelloOk = Static<typeof HelloOkSchema>;
export type ErrorShape = Static<typeof ErrorShapeSchema>;
export type RequestFrame = Static<typeof RequestFrameSchema>;
export type ResponseFrame = Static<typeof ResponseFrameSchema>;
export type EventFrame = Static<typeof EventFrameSchema>;
export type GatewayFrame = Static<typeof GatewayFrameSchema>;
export type TickEvent = Static<typeof TickEventSchema>;
export type ShutdownEvent = Static<typeof ShutdownEventSchema>;
```

### 2.4. Guards livianos: despachar sin validar

Archivo completo `packages/gateway-protocol/src/frame-guards.ts` [VERIFICADO EN CÓDIGO]:

```ts
function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isGatewayErrorShape(value: unknown): boolean {
  if (!isRecord(value)) {
    return false;
  }
  if (!isNonEmptyString(value.code) || !isNonEmptyString(value.message)) {
    return false;
  }
  if (value.retryable !== undefined && typeof value.retryable !== "boolean") {
    return false;
  }
  return value.retryAfterMs === undefined || isNonNegativeInteger(value.retryAfterMs);
}

// These lightweight guards validate dispatch-critical envelope fields without
// compiling the full schemas or rejecting additive payload fields.
export function isGatewayEventFrame(value: unknown): value is EventFrame {
  if (!isRecord(value) || value.type !== "event" || !isNonEmptyString(value.event)) {
    return false;
  }
  return value.seq === undefined || isNonNegativeInteger(value.seq);
}

export function isGatewayResponseFrame(value: unknown): value is ResponseFrame {
  if (
    !isRecord(value) ||
    value.type !== "res" ||
    !isNonEmptyString(value.id) ||
    typeof value.ok !== "boolean"
  ) {
    return false;
  }
  return value.error === undefined || isGatewayErrorShape(value.error);
}
```

El comentario en el código es la tesis: *"validate dispatch-critical envelope fields without
compiling the full schemas or rejecting additive payload fields"*. El guard mira **solo los campos
que deciden a dónde va el frame** y deja pasar campos aditivos. Esto es lo que hace posible que un
cliente viejo no explote cuando el servidor agrega un campo.

### 2.5. Handshake: `connect` → `hello-ok`

El handshake NO es un frame `req`/`res` normal. Es un intercambio especial que ocurre **antes** de
que el gateway acepte frames. Esquema completo `ConnectParamsSchema`, transcrito literalmente
[VERIFICADO EN CÓDIGO]:

```ts
/** Initial client hello/connect payload sent before the gateway accepts frames. */
export const ConnectParamsSchema = closedObject({
  minProtocol: Type.Integer({ minimum: 1 }),
  maxProtocol: Type.Integer({ minimum: 1 }),
  client: closedObject({
    id: GatewayClientIdSchema,
    displayName: Type.Optional(NonEmptyString),
    version: NonEmptyString,
    platform: NonEmptyString,
    deviceFamily: Type.Optional(NonEmptyString),
    modelIdentifier: Type.Optional(NonEmptyString),
    mode: GatewayClientModeSchema,
    instanceId: Type.Optional(NonEmptyString),
  }),
  caps: Type.Optional(Type.Array(NonEmptyString, { default: [] })),
  commands: Type.Optional(Type.Array(NonEmptyString)),
  permissions: Type.Optional(Type.Record(NonEmptyString, Type.Boolean())),
  pathEnv: Type.Optional(Type.String()),
  role: Type.Optional(NonEmptyString),
  scopes: Type.Optional(Type.Array(NonEmptyString)),
  device: Type.Optional(
    closedObject({
      id: NonEmptyString,
      publicKey: NonEmptyString,
      signature: NonEmptyString,
      signedAt: Type.Integer({ minimum: 0 }),
      nonce: NonEmptyString,
    }),
  ),
  auth: Type.Optional(
    closedObject({
      token: Type.Optional(Type.String()),
      bootstrapToken: Type.Optional(Type.String()),
      deviceToken: Type.Optional(Type.String()),
      password: Type.Optional(Type.String()),
      approvalRuntimeToken: Type.Optional(Type.String()),
      agentRuntimeIdentityToken: Type.Optional(Type.String()),
    }),
  ),
  locale: Type.Optional(Type.String()),
  userAgent: Type.Optional(Type.String()),
});
```

Lo que negocia el cliente en una sola ida:

- **Rango de protocolo** (`minProtocol`/`maxProtocol`) — no una versión sola. El servidor elige.
- **Identidad del producto** (`client.id` de un registro cerrado, `client.mode` de un registro
  cerrado) — usado para política, no solo diagnóstico.
- **Capacidades opcionales** (`caps`) — "yo sé manejar eventos de herramientas", "yo sé mostrar
  aprobaciones".
- **Cinco vías de autenticación simultáneas** en `auth` (token compartido, bootstrap token, device
  token, password, tokens de runtime) más un bloque `device` de firma criptográfica separado.

Respuesta del servidor, `HelloOkSchema` (transcripción de los campos estructurales; se omiten los
bloques de UI de plugins por ser específicos de OpenClaw) [VERIFICADO EN CÓDIGO]:

```ts
export const HelloOkSchema = closedObject({
  type: Type.Literal("hello-ok"),
  protocol: Type.Integer({ minimum: 1 }),
  server: closedObject({
    version: NonEmptyString,
    connId: NonEmptyString,
  }),
  features: closedObject({
    methods: Type.Array(NonEmptyString),
    events: Type.Array(NonEmptyString),
    capabilities: Type.Optional(Type.Array(NonEmptyString)),
  }),
  snapshot: SnapshotSchema,
  // ... controlUiTabs / controlUiWidgetKinds / pluginSurfaceUrls (específicos de la UI de OpenClaw)
  deviceAuthMigration: Type.Optional(closedObject({ pending: Type.Literal(true) })),
  auth: closedObject({
    deviceToken: Type.Optional(NonEmptyString),
    role: NonEmptyString,
    scopes: Type.Array(NonEmptyString),
    issuedAtMs: Type.Optional(Type.Integer({ minimum: 0 })),
    deviceTokens: Type.Optional(
      Type.Array(
        closedObject({
          deviceToken: NonEmptyString,
          role: NonEmptyString,
          scopes: Type.Array(NonEmptyString),
          issuedAtMs: Type.Integer({ minimum: 0 }),
        }),
      ),
    ),
  }),
  policy: closedObject({
    maxPayload: Type.Integer({ minimum: 1 }),
    maxBufferedBytes: Type.Integer({ minimum: 1 }),
    tickIntervalMs: Type.Integer({ minimum: 1 }),
    allowedSessionVisibilities: Type.Optional(Type.Array(SessionVisibilitySchema)),
    hasMultipleSessionSharingIdentities: Type.Optional(Type.Boolean()),
  }),
});
```

Esto es lo más denso e imitable del protocolo. El `hello-ok` entrega **cuatro cosas en un solo
frame**:

1. **`protocol`** — la versión negociada efectiva.
2. **`features.methods` / `features.events`** — *descubrimiento de superficie*. El cliente sabe qué
   puede llamar sin documentación.
   > ⚠️ **Advertencia explícita del README**: *"The `hello-ok.features.methods` list is conservative
   > discovery, not a complete enumeration of every callable method... Clients should use discovery
   > to enable optional UI, not to reject an otherwise documented method contract."* Es decir, la
   > lista puede tener falsos negativos por diseño. **No es un contrato de autorización.**
3. **`snapshot`** — el **estado completo inicial** del servidor en el mismo frame del handshake. Esto
   elimina la carrera clásica "me conecté, ahora tengo que pedir el estado y mientras tanto pueden
   llegar eventos". El cliente arranca con estado consistente y a partir de ahí solo aplica deltas.
4. **`policy`** — **límites operativos entregados por el servidor**, no configurados en el cliente:
   `maxPayload`, `maxBufferedBytes`, `tickIntervalMs`. El cliente aprende cuánto puede mandar y cada
   cuánto esperar heartbeat. Si el servidor cambia sus límites, no hay que redeployar clientes.

Además, `auth.deviceToken` en la respuesta: el servidor puede **emitir credenciales durante el
handshake** (device token nuevo tras un pairing aprobado), evitando un flujo aparte.

### 2.6. Eventos de infraestructura: `tick` y `shutdown`

```ts
/** Periodic server heartbeat event payload. */
export const TickEventSchema = closedObject({
  ts: Type.Integer({ minimum: 0 }),
});

/** Server shutdown notice event payload. */
export const ShutdownEventSchema = closedObject({
  reason: NonEmptyString,
  restartExpectedMs: Type.Optional(Type.Integer({ minimum: 0 })),
});
```

`ShutdownEvent` es sutil y muy transferible: cuando el gateway se va a bajar, avisa **con un motivo y
una estimación de cuánto va a tardar en volver**. El cliente puede distinguir "se cayó, reintentá
con backoff agresivo" de "reinicio planificado, esperá 3 segundos y reconectá". Es la diferencia
entre una UI que parpadea "DESCONECTADO" en rojo y una que dice "reiniciando…".

### 2.7. Identidad de cliente: registros cerrados

Archivo `packages/gateway-protocol/src/client-info.ts` [VERIFICADO EN CÓDIGO — archivo leído completo]:

```ts
/** Canonical client ids accepted in gateway hello/connect payloads. */
export const GATEWAY_CLIENT_IDS = {
  WEBCHAT_UI: "webchat-ui",
  CONTROL_UI: "openclaw-control-ui",
  BROWSER_COPILOT: "openclaw-browser-copilot",
  TUI: "openclaw-tui",
  WEBCHAT: "webchat",
  CLI: "cli",
  GATEWAY_CLIENT: "gateway-client",
  MACOS_APP: "openclaw-macos",
  // Native Linux UI uses the same trusted-client admission class as the macOS app.
  LINUX_APP: "openclaw-linux",
  IOS_APP: "openclaw-ios",
  WATCHOS_APP: "openclaw-watchos",
  ANDROID_APP: "openclaw-android",
  NODE_HOST: "node-host",
  WORKER: "openclaw-worker",
  TEST: "test",
  FINGERPRINT: "fingerprint",
  PROBE: "openclaw-probe",
} as const;

/** Coarse modes let policy group clients without matching every product id. */
export const GATEWAY_CLIENT_MODES = {
  WEBCHAT: "webchat",
  CLI: "cli",
  UI: "ui",
  BACKEND: "backend",
  NODE: "node",
  WORKER: "worker",
  PROBE: "probe",
  TEST: "test",
} as const;

/** Capability flags a client may advertise during the gateway handshake. */
export const GATEWAY_CLIENT_CAPS = {
  AGENT_KIND: "agent-kind",
  APPROVALS: "approvals",
  EXEC_APPROVALS: "exec-approvals",
  INLINE_WIDGETS: "inline-widgets",
  RUN_TOOL_BINDINGS: "run-tool-bindings",
  SESSION_SCOPED_EVENTS: "session-scoped-events",
  PLUGIN_APPROVALS: "plugin-approvals",
  TASK_SUGGESTIONS: "task-suggestions",
  TERMINAL_OFFSET_SEQ: "terminal-offset-seq",
  TOOL_EVENTS: "tool-events",
  UI_COMMANDS: "ui-commands",
} as const;
```

Y los normalizadores, que definen el comportamiento frente a input desconocido:

```ts
/** Normalizes untrusted client ids and rejects unknown values. */
export function normalizeGatewayClientId(raw?: string | null): GatewayClientId | undefined {
  // Handshake input is intentionally case-insensitive, but policy decisions use
  // the canonical lowercase ids from the closed registry above.
  const normalized = normalizeOptionalLowercaseString(raw);
  if (!normalized) {
    return undefined;
  }
  return GATEWAY_CLIENT_ID_SET.has(normalized as GatewayClientId)
    ? (normalized as GatewayClientId)
    : undefined;
}

/** Checks a client-advertised capability list without treating missing caps as errors. */
export function hasGatewayClientCap(
  caps: string[] | null | undefined,
  cap: GatewayClientCap,
): boolean {
  if (!Array.isArray(caps)) {
    return false;
  }
  return caps.includes(cap);
}
```

Tres decisiones a copiar:

- **`id` (producto específico) vs `mode` (categoría gruesa) separados.** La política se escribe contra
  `mode` ("todos los clientes `ui`"), el diagnóstico contra `id`. Sin esto, cada regla de política
  tendría que enumerar productos.
- **Registros cerrados con normalización tolerante en entrada, canónica en política.** El handshake
  acepta mayúsculas/minúsculas; las decisiones usan siempre el valor canónico.
- **La documentación del `README` marca el límite**: *"A capability advertises client support; it does
  not grant authorization."* Un `cap` dice "sé recibir esto", **nunca** "tengo permiso para esto".

### 2.8. Métodos: tabla de política, no diccionario de handlers

Esto es, para mí, el hallazgo estructural más fuerte del gateway. `src/gateway/methods/descriptor.ts`
(archivo completo, 55 líneas) [VERIFICADO EN CÓDIGO]:

```ts
/** Scope marker for methods that only authenticated node clients may call. */
export const NODE_GATEWAY_METHOD_SCOPE = "node" as const;
/** Scope marker for methods whose handler derives the required operator scope at runtime. */
export const DYNAMIC_GATEWAY_METHOD_SCOPE = "dynamic" as const;

/** Authorization scope attached to a gateway method descriptor. */
export type GatewayMethodScope =
  | OperatorScope
  | typeof NODE_GATEWAY_METHOD_SCOPE
  | typeof DYNAMIC_GATEWAY_METHOD_SCOPE;

/** Owner metadata used to keep core, plugin, channel, and auxiliary methods distinguishable. */
export type GatewayMethodOwner =
  | { kind: "core"; area: string }
  | { kind: "plugin"; pluginId: string }
  | { kind: "channel"; channelId: string }
  | { kind: "aux"; area: string };

/** Startup availability flag exposed to clients as retryable startup-unavailable errors. */
type GatewayMethodStartupAvailability = "available" | "unavailable-until-sidecars";

export type GatewayMethodHandler = (opts: never) => unknown;

/** Complete metadata for one dispatchable gateway method. */
export type GatewayMethodDescriptor = {
  name: string;
  handler: GatewayMethodHandler;
  scope: GatewayMethodScope;
  owner: GatewayMethodOwner;
  since?: string;
  startup?: GatewayMethodStartupAvailability;
  controlPlaneWrite?: boolean;
  advertise?: boolean;
  description?: string;
};

/** Read-only method registry view used by request dispatch and method listing. */
export type GatewayMethodRegistryView = {
  getHandler: (name: string) => GatewayMethodHandler | undefined;
  listMethods: () => string[];
  listAdvertisedMethods: () => string[];
  getScope: (name: string) => GatewayMethodScope | undefined;
  isStartupUnavailable: (name: string) => boolean;
  isControlPlaneWrite: (name: string) => boolean;
  descriptors: () => readonly GatewayMethodDescriptor[];
};
```

Campo por campo, y por qué está:

| Campo | Para qué sirve |
|---|---|
| `handler` | la función. Es **un campo más**, no la esencia del registro. |
| `scope` | permiso requerido. `"dynamic"` = el handler lo deriva de los params (ej. `talk.config` pide más si se piden secretos). `"node"` = solo clientes node autenticados. |
| `owner` | de dónde vino: core / plugin / **channel** / aux. Un canal puede registrar métodos del gateway. |
| `since` | versión en que apareció. Alimenta el descubrimiento y la compatibilidad. |
| `startup` | `"unavailable-until-sidecars"`: el método existe pero todavía no funciona → error **retryable** en vez de "método desconocido". |
| `controlPlaneWrite` | marca escrituras del plano de control para **throttling compartido** (presupuesto de escrituras). |
| `advertise` | si `false`, el método existe y es llamable pero **no aparece** en `hello-ok.features.methods`. |

El registro (`src/gateway/methods/registry.ts`) hace cumplir dos invariantes duras
[VERIFICADO EN CÓDIGO]:

```ts
for (const descriptor of descriptors) {
  // Duplicate method names would make authorization and handler dispatch disagree about the
  // owner/scope, so reject them before exposing any registry view.
  if (byName.has(descriptor.name)) {
    throw new Error(`gateway method already registered: ${descriptor.name}`);
  }
  byName.set(descriptor.name, descriptor);
}
```

y, para plugins, que **no puedan auto-asignarse un scope permisivo** en nombres que parecen del core:

```ts
const normalizedScope =
  input.scope === NODE_GATEWAY_METHOD_SCOPE || input.scope === DYNAMIC_GATEWAY_METHOD_SCOPE
    ? input.scope
    : input.owner.kind === "plugin"
      ? normalizePluginGatewayMethodScope(name, input.scope).scope
      : input.scope;
if (!normalizedScope) {
  throw new Error(`gateway method descriptor is missing a scope: ${name}`);
}
```

Y para registros de plugin legacy que solo traían handlers sin metadata, el fallback es **el scope
más restrictivo**, no el más permisivo:

```ts
// Older plugin registries only carried handlers, so keep them callable but assign admin scope
// until the plugin can provide explicit descriptor metadata.
return createGatewayMethodDescriptorsFromHandlers({
  handlers: registry.gatewayHandlers,
  owner: { kind: "plugin", pluginId: "unknown" },
  defaultScope: ADMIN_SCOPE,
});
```

Esto es *fail-closed* — la misma disciplina que O.R.I.O.N. adoptó en REQ-005.

### 2.9. Scopes de operador (conjunto cerrado)

`src/gateway/operator-scopes.ts` [VERIFICADO EN CÓDIGO — archivo leído completo]:

```ts
export const ADMIN_SCOPE = "operator.admin" as const;
export const READ_SCOPE = "operator.read" as const;
export const WRITE_SCOPE = "operator.write" as const;
export const APPROVALS_SCOPE = "operator.approvals" as const;
export const QUESTIONS_SCOPE = "operator.questions" as const;
export const PAIRING_SCOPE = "operator.pairing" as const;
export const TALK_SCOPE = "operator.talk" as const;
export const TALK_SECRETS_SCOPE = "operator.talk.secrets" as const;

/** Narrows untrusted auth-token scope entries to the gateway's closed scope set. */
export function isOperatorScope(value: unknown): value is OperatorScope {
  return typeof value === "string" && KNOWN_OPERATOR_SCOPES.has(value as OperatorScope);
}

/** Filters unknown strings down to unique operator scopes; undefined stays undefined. */
export function normalizeOperatorScopeList(
  scopes: string[] | undefined,
): OperatorScope[] | undefined {
  if (!Array.isArray(scopes)) {
    return undefined;
  }
  const normalized: OperatorScope[] = [];
  for (const scope of scopes) {
    if (isOperatorScope(scope) && !normalized.includes(scope)) {
      normalized.push(scope);
    }
  }
  return normalized;
}
```

Solo **8 scopes** para ~350 métodos. La granularidad no está en el scope sino en el mapeo
método→scope. Notar que `read`/`write`/`admin` es el eje principal y los otros cinco son ejes
transversales de funcionalidad sensible (aprobaciones, preguntas al humano, pairing de dispositivos,
voz, secretos de voz).

### 2.10. La tabla canónica de métodos

`src/gateway/methods/core-descriptors.ts` (581 líneas) contiene un único array
`CORE_GATEWAY_METHOD_SPECS` con el comentario que declara la regla:

```ts
// This is the canonical core method policy table: every core handler must appear here so
// listing, authorization, startup availability, and write throttling stay in sync.
const CORE_GATEWAY_METHOD_SPECS: readonly CoreGatewayMethodSpec[] = [
  { name: "health", scope: "operator.read", since: "<=2026.7" },
  { name: "logs.tail", scope: "operator.read", since: "<=2026.7" },
  { name: "channels.status", scope: "operator.read", since: "<=2026.7" },
  { name: "channels.start", scope: "operator.admin", since: "<=2026.7" },
  { name: "channels.stop", scope: "operator.admin", since: "<=2026.7" },
  { name: "channels.logout", scope: "operator.admin", since: "<=2026.7" },
  { name: "config.get", scope: "operator.read", since: "<=2026.7" },
  { name: "config.set", scope: "operator.admin", since: "<=2026.7" },
  { name: "config.apply", scope: "operator.admin", since: "<=2026.7", controlPlaneWrite: true },
  { name: "config.patch", scope: "operator.admin", since: "<=2026.7", controlPlaneWrite: true },
  { name: "exec.approval.request", scope: "operator.approvals", since: "<=2026.7" },
  { name: "exec.approval.waitDecision", scope: "operator.approvals", since: "<=2026.7" },
  { name: "exec.approval.resolve", scope: "operator.approvals", since: "<=2026.7" },
  { name: "question.request", scope: "operator.questions", since: "2026.7" },
  { name: "question.waitAnswer", scope: "operator.questions", since: "2026.7" },
  // ... (~350 entradas en total)
];
```

Los grupos funcionales completos, extraídos del archivo [VERIFICADO EN CÓDIGO — extracción mecánica
de los ~350 pares `name`/`scope`]:

- **Salud/diagnóstico**: `health`, `status`, `diagnostics.stability`, `doctor.memory.*`, `logs.tail`, `system.info` — casi todos `operator.read`.
- **Canales**: `channels.status` (read), `channels.start` / `channels.stop` / `channels.logout` (admin), `channels.pairing.list` (pairing), `channels.pairing.approve` (**dynamic**), `channels.pairing.dismiss` (pairing).
- **Configuración**: `config.get` (read), `config.set` / `config.schema` / `config.openFile` (admin), `config.apply` / `config.patch` (admin + `controlPlaneWrite`), `config.schema.lookup` (read).
- **Sesiones (el grupo más grande)**: `sessions.list`, `sessions.get`, `sessions.resolve`, `sessions.preview`, `sessions.describe`, `sessions.subscribe`/`unsubscribe`, `sessions.messages.subscribe`/`unsubscribe`, `sessions.usage`, `sessions.diff`, `sessions.branches.list` (read); `sessions.send`, `sessions.abort`, `sessions.fork`, `sessions.steer`, `sessions.compaction.branch`, `sessions.groups.*` (write); `sessions.create`, `sessions.patch`, `sessions.delete` (**dynamic**); `sessions.reset`, `sessions.cleanup`, `sessions.compact`, `sessions.rewind`, `sessions.branches.switch`, `sessions.pluginPatch`, `sessions.files.set` (admin).
- **Chat**: `chat.history`, `chat.startup`, `chat.metadata`, `chat.message.get` (read); `chat.send`, `chat.abort`, `chat.toolTitles` (write); `chat.inject` (admin).
- **Agentes**: `agents.list` (read), `agents.create`/`update`/`delete` (admin), `agents.files.*`, `agents.workspace.list`/`get` (read), `agent` (**dynamic**), `agent.wait` (write), `agent.identity.get` (read).
- **Aprobaciones y preguntas**: `exec.approval.*` y `plugin.approval.*` (`operator.approvals`), `question.*` (`operator.questions`), `exec.approvals.get`/`set` y `.node.get`/`.node.set` (admin).
- **Herramientas**: `tools.catalog`, `tools.effective` (read), `tools.invoke` (write).
- **Nodos y pairing**: `node.list`, `node.describe` (read); `node.pair.*`, `device.pair.*`, `device.token.rotate`/`revoke`, `node.rename` (`operator.pairing`); `node.pending.drain`/`pull`/`ack`, `node.invoke.progress`/`result`, `node.event`, `node.skills.update`, `node.pluginTools.update`, `skills.bins` (**scope `node`**); `node.invoke` (**dynamic**).
- **Cron/automatizaciones**: `cron.get`/`list`/`status`/`runs` (read), `cron.add`/`update`/`remove`/`run`/`scratch.*` (admin).
- **Skills**: `skills.status`/`search`/`detail`/`securityVerdicts`/`skillCard` (read), `skills.install`/`update`/`upload.*`/`curator.*`/`proposals.*` (admin).
- **Terminal**: `terminal.open`/`input`/`resize`/`close`/`attach`/`list`/`text` (todos admin).
- **Voz (`talk.*`)**: `talk.catalog` (read), `talk.config` (**dynamic** — "reading redacted config needs read; includeSecrets also needs talk secrets"), el resto `operator.talk`.
- **Conversaciones externas**: `conversations.send`, `conversations.turn`, `conversations.turn.cancel` (**admin** — usan credenciales del operador), `send` (write), `message.action` (write).
- **Push/notificaciones**: `push.test`, `push.web.*` (write).
- **Gateway mismo**: `gateway.identity.get` (read), `gateway.restart.preflight` (read), `gateway.suspend.status` (read), `gateway.suspend.resume` (admin).

**Observación escéptica**: hay ~350 métodos en un solo namespace plano con separador `.`. No hay
versionado por método (solo `since`), no hay deprecación en el descriptor. La ausencia de un campo
`deprecated`/`removedIn` significa que **la única forma de retirar un método es un bump de protocolo
o romper clientes**. Para un sistema del tamaño de O.R.I.O.N. esto no importa, pero es una deuda
real del diseño.

### 2.11. Errores de conexión estructurados

`packages/gateway-protocol/src/connect-error-details.ts` define códigos de error de **conexión**
separados de los errores de método [VERIFICADO EN CÓDIGO — archivo leído completo, 529 líneas]:

```ts
/** Structured connect-error codes carried in gateway error `details.code`. */
export const ConnectErrorDetailCodes = {
  AUTH_REQUIRED: "AUTH_REQUIRED",
  AUTH_UNAUTHORIZED: "AUTH_UNAUTHORIZED",
  AUTH_TOKEN_MISSING: "AUTH_TOKEN_MISSING",
  AUTH_TOKEN_MISMATCH: "AUTH_TOKEN_MISMATCH",
  AUTH_TOKEN_NOT_CONFIGURED: "AUTH_TOKEN_NOT_CONFIGURED",
  AUTH_PASSWORD_MISSING: "AUTH_PASSWORD_MISSING",
  AUTH_PASSWORD_MISMATCH: "AUTH_PASSWORD_MISMATCH",
  AUTH_PASSWORD_NOT_CONFIGURED: "AUTH_PASSWORD_NOT_CONFIGURED",
  AUTH_BOOTSTRAP_TOKEN_INVALID: "AUTH_BOOTSTRAP_TOKEN_INVALID",
  AUTH_DEVICE_TOKEN_MISMATCH: "AUTH_DEVICE_TOKEN_MISMATCH",
  AUTH_SCOPE_MISMATCH: "AUTH_SCOPE_MISMATCH",
  AUTH_RATE_LIMITED: "AUTH_RATE_LIMITED",
  AUTH_TAILSCALE_IDENTITY_MISSING: "AUTH_TAILSCALE_IDENTITY_MISSING",
  AUTH_TAILSCALE_PROXY_MISSING: "AUTH_TAILSCALE_PROXY_MISSING",
  AUTH_TAILSCALE_WHOIS_FAILED: "AUTH_TAILSCALE_WHOIS_FAILED",
  AUTH_TAILSCALE_IDENTITY_MISMATCH: "AUTH_TAILSCALE_IDENTITY_MISMATCH",
  CONTROL_UI_ORIGIN_NOT_ALLOWED: "CONTROL_UI_ORIGIN_NOT_ALLOWED",
  PROTOCOL_MISMATCH: "PROTOCOL_MISMATCH",
  CONTROL_UI_DEVICE_IDENTITY_REQUIRED: "CONTROL_UI_DEVICE_IDENTITY_REQUIRED",
  DEVICE_IDENTITY_REQUIRED: "DEVICE_IDENTITY_REQUIRED",
  DEVICE_AUTH_INVALID: "DEVICE_AUTH_INVALID",
  DEVICE_AUTH_DEVICE_ID_MISMATCH: "DEVICE_AUTH_DEVICE_ID_MISMATCH",
  DEVICE_AUTH_SIGNATURE_EXPIRED: "DEVICE_AUTH_SIGNATURE_EXPIRED",
  DEVICE_AUTH_NONCE_REQUIRED: "DEVICE_AUTH_NONCE_REQUIRED",
  DEVICE_AUTH_NONCE_MISMATCH: "DEVICE_AUTH_NONCE_MISMATCH",
  DEVICE_AUTH_SIGNATURE_INVALID: "DEVICE_AUTH_SIGNATURE_INVALID",
  DEVICE_AUTH_PUBLIC_KEY_INVALID: "DEVICE_AUTH_PUBLIC_KEY_INVALID",
  PAIRING_REQUIRED: "PAIRING_REQUIRED",
  CLIENT_VERSION_MISMATCH: "CLIENT_VERSION_MISMATCH",
} as const;
```

Y — esto es lo bueno — cada error de conexión lleva **consejo de recuperación accionable por
máquina**, no solo un mensaje:

```ts
/** Suggested client-side recovery action for structured connect errors. */
type ConnectRecoveryNextStep =
  | "retry_with_device_token"
  | "update_auth_configuration"
  | "update_auth_credentials"
  | "wait_then_retry"
  | "review_auth_configuration";

/** Optional retry guidance extracted from gateway connect-error details. */
type ConnectErrorRecoveryAdvice = {
  canRetryWithDeviceToken?: boolean;
  recommendedNextStep?: ConnectRecoveryNextStep;
};

/** Full structured details for pairing-required connect failures. */
type PairingConnectErrorDetails = {
  code: typeof ConnectErrorDetailCodes.PAIRING_REQUIRED;
  reason?: ConnectPairingRequiredReason;   // "not-paired" | "role-upgrade" | "scope-upgrade" | "metadata-upgrade"
  requestId?: string;
  remediationHint?: string;
  recommendedNextStep?: ConnectRecoveryNextStep;
  retryable?: boolean;
  pauseReconnect?: boolean;
  deviceId?: string;
  requestedRole?: string;
  requestedScopes?: string[];
  approvedRoles?: string[];
  approvedScopes?: string[];
};
```

Notar `pauseReconnect?: boolean`. El servidor puede decirle al cliente **"dejá de reintentar"** — sin
eso, un cliente con backoff exponencial martillaría el gateway indefinidamente mientras el humano no
aprueba el pairing.

Y la defensa contra input no confiable: todo lo que llega en `details` pasa por normalizadores.
Ejemplo del patrón, con un comentario que vale la pena leer:

```ts
function normalizeArrayBackedTrimmedStringList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) {
    return undefined;
  }
  const values = value
    .map((entry) => normalizeOptionalString(entry))
    .filter((entry): entry is string => Boolean(entry));
  // Pairing details omit absent lists. Emitting empty arrays makes clients think
  // the gateway intentionally supplied scope/role context when it did not.
  return values.length > 0 ? values : undefined;
}
```

Además hay un parser de retrocompatibilidad, `readConnectPairingRequiredMessage()`, que reconstruye
detalles estructurados a partir de **mensajes de error viejos en texto plano** (`"pairing required
(requestId: abc)"`), incluyendo una regex `/\(requestId:\s*([^\s)]+)\)/i`. Es deuda técnica visible:
el protocolo empezó devolviendo strings y tuvo que retrofittear estructura.

### 2.12. Campos abiertos: hallazgo honesto

El README admite algo que casi ninguna documentación admite [AFIRMACIÓN DE DOCUMENTACIÓN, pero
consistente con el código: `Type.Unknown()` aparece en los tres campos del envelope]:

> "The schema graph is strict by default, but roughly 60 fields intentionally use `Type.Unknown()`
> passthroughs. The main clusters are transport-owned channel payloads, logs-chat message and
> attachment passthrough, worker and node tool arguments/results, and the dynamic `config.schema`
> response... Do not treat these fields as validated domain objects. Narrow them at their owner
> boundary before reading nested values."

Es decir: **el protocolo es estricto en el envelope y deliberadamente laxo en las cargas de los
canales**. Los payloads de canal son "transport-owned" — el gateway los transporta sin entenderlos.
Eso es lo que permite agregar canales sin tocar el protocolo, y es exactamente el trade-off que
O.R.I.O.N. va a tener que hacer.

### 2.13. Confusión de identificadores de sesión (documentada por ellos mismos)

El README dedica una sección entera a explicar por qué hay tres nombres para cosas parecidas
[AFIRMACIÓN DE DOCUMENTACIÓN]:

- **`key`** — el selector lógico de sesión establecido; lo usan la mayoría de los métodos `sessions.*`.
- **`sessionKey`** — la misma identidad lógica de ruteo, escrita así donde el contrato necesita
  explicitarlo: `chat.*`, APIs de archivos/diff, branch/rewind/fork, eventos de agente y **payloads
  de entrega de canal**.
- **`sessionId`** — el ID opaco del transcript almacenado o de la instancia runtime. Talk, terminal,
  worker y algunos protocolos de canal lo usan para sus propias sesiones concretas.

> "Follow each method schema rather than converting fields based on their spelling."

Traducción: **se les escapó**. Tres nombres para dos conceptos y medio, y la mitigación es
documentación. Para O.R.I.O.N.: elegir **un** nombre para la identidad lógica de sesión y **otro**
claramente distinto para el id de almacenamiento, desde el día cero.

---

## 3. Contrato de canal

### 3.0. Hallazgo negativo importante sobre la ubicación

**El contrato NO vive en `src/channels/`.** Busqué `ChannelPlugin` y `createChatChannelPlugin` en
todo el repo [VERIFICADO EN CÓDIGO]:

- El **tipo raíz** `ChannelPlugin` vive en `src/channels/plugins/types.plugin.ts`.
- Las **piezas del tipo** están repartidas en `types.core.ts` (835 líneas), `types.adapters.ts` (844
  líneas), `types.config.ts`, `outbound.types.ts`, `message/types.ts`.
- La **fábrica pública** `createChatChannelPlugin()` vive en `src/plugin-sdk/core.ts` (línea 825) y se
  reexporta por `src/plugin-sdk/channel-core.ts`.
- Las **implementaciones concretas** NO están en `src/channels/`: están en `extensions/<canal>/src/channel.ts`.
  Hay **19 canales de chat** con ese archivo: buzz, clickclack, discord, feishu, googlechat, imessage,
  irc, line, matrix, mattermost, msteams, nextcloud-talk, nostr, qa-channel, y (por el listado de
  tamaños) raft, tlon, zalouser, zalo, whatsapp, sms, synology-chat, qqbot, reef, signal, slack, telegram.

`src/channels/` contiene la **maquinaria compartida** (bindings, sesiones, threading, allowlists,
streaming, typing, debounce, targets), no los canales.

### 3.1. El tipo raíz, transcrito completo

`src/channels/plugins/types.plugin.ts` (archivo completo, 118 líneas)
[VERIFICADO EN CÓDIGO]:

```ts
/** Full capability contract for a native channel plugin. */
type ChannelPluginSetupWizard = ChannelSetupWizard | ChannelSetupWizardAdapter;

type ChannelGatewayMethodDescriptor = {
  name: string;
  scope?: OperatorScope;
  description?: string;
};

// Omitted generic means "plugin with some account shape"; using unknown makes
// callback parameters contravariant and rejects concrete plugin implementations.
export type ChannelPlugin<ResolvedAccount = any, Probe = unknown, Audit = unknown> = {
  id: ChannelId;
  meta: ChannelMeta;
  capabilities: ChannelCapabilities;
  defaults?: {
    queue?: {
      debounceMs?: number;
    };
  };
  reload?: {
    configPrefixes: string[];
    noopPrefixes?: string[];
    /**
     * Opt into restarting only the changed non-default named account.
     * Set only when sibling account resolution and lifecycle state are isolated and
     * account stop fully settles owned work. Shared, default, removed, or unresolved
     * account changes still restart the whole channel.
     */
    accountScopedRestart?: boolean;
  };
  setupWizard?: ChannelPluginSetupWizard;
  config: ChannelConfigAdapter<ResolvedAccount>;
  configSchema?: ChannelConfigSchema;
  /** Channel-owned typed setup contract. Preferred over the legacy shared input adapter. */
  setupContract?: ChannelOwnedSetupContract;
  /** @deprecated Use setupContract for new plugins. */
  setup?: ChannelSetupAdapter;
  pairing?: ChannelPairingAdapter;
  security?: ChannelSecurityAdapter<ResolvedAccount>;
  groups?: ChannelGroupAdapter;
  mentions?: ChannelMentionAdapter;
  outbound?: ChannelOutboundAdapter;
  status?: ChannelStatusAdapter<ResolvedAccount, Probe, Audit>;
  gatewayMethods?: string[];
  gatewayMethodDescriptors?: ChannelGatewayMethodDescriptor[];
  gateway?: ChannelGatewayAdapter<ResolvedAccount>;
  // Login/logout and channel-auth only. Approval auth lives on approvalCapability.
  auth?: ChannelAuthAdapter;
  approvalCapability?: ChannelApprovalCapability;
  elevated?: ChannelElevatedAdapter;
  commands?: ChannelCommandAdapter;
  lifecycle?: ChannelLifecycleAdapter;
  secrets?: ChannelSecretsAdapter;
  allowlist?: ChannelAllowlistAdapter;
  doctor?: ChannelDoctorAdapter;
  bindings?: ChannelConfiguredBindingProvider;
  conversationBindings?: ChannelConversationBindingSupport;
  streaming?: ChannelStreamingAdapter;
  threading?: ChannelThreadingAdapter;
  message?: ChannelMessageAdapterShape;
  messaging?: ChannelMessagingAdapter;
  agentPrompt?: ChannelAgentPromptAdapter;
  directory?: ChannelDirectoryAdapter;
  resolver?: ChannelResolverAdapter;
  actions?: ChannelMessageActionAdapter;
  heartbeat?: ChannelHeartbeatAdapter;
  // Channel-owned agent tools (login flows, etc.).
  agentTools?: ChannelAgentToolFactory | ChannelAgentTool[];
};
```

**Lo estructural**: de **31 campos, solo 4 son obligatorios** — `id`, `meta`, `capabilities`,
`config`. Todo lo demás son *adapters* opcionales. El contrato NO es una interfaz que hay que
implementar entera: es una **bolsa de puntos de extensión donde el canal aporta solo lo que sabe
hacer**. El core tiene un comportamiento por defecto para todo lo que falte.

Esa es la diferencia con el patrón "clase base abstracta con métodos abstractos" (que es lo que usa
hoy `BaseSkill` en O.R.I.O.N.): acá no hay herencia, hay **composición de capacidades declaradas**.

### 3.2. Campo por campo

#### `id: ChannelId` (obligatorio)
Identificador canónico del canal (`"irc"`, `"discord"`, `"googlechat"`). Es la clave de registro y el
prefijo de todo lo demás.

#### `meta: ChannelMeta` (obligatorio)
Metadata orientada a **humanos y superficies de selección**, no a runtime.
`src/channels/plugins/types.core.ts` [VERIFICADO EN CÓDIGO]:

```ts
/** User-facing metadata used in docs, pickers, and setup surfaces. */
export type ChannelMeta = {
  id: ChannelId;
  label: string;
  selectionLabel: string;
  docsPath: string;
  docsLabel?: string;
  blurb: string;
  order?: number;
  aliases?: readonly string[];
  selectionDocsPrefix?: string;
  selectionDocsOmitLabel?: boolean;
  selectionExtras?: readonly string[];
  detailLabel?: string;
  systemImage?: string;
  markdownCapable?: boolean;
  exposure?: ChannelExposure;   // { configured?, setup?, docs? }
  quickstartAllowFrom?: boolean;
  forceAccountBinding?: boolean;
  preferSessionLookupForAnnounceTarget?: boolean;
  preferOver?: readonly string[];
};
```

Notable: `docsPath` es **obligatorio**. No podés registrar un canal sin apuntar a su documentación.
`aliases` permite que el usuario escriba `gchat` y llegue a `googlechat`. `preferOver` resuelve
ambigüedades cuando dos canales podrían atender el mismo target.

#### `capabilities: ChannelCapabilities` (obligatorio)
Declaración de **qué sabe hacer el transporte**. Es corta y es la pieza más copiable del contrato:

```ts
export type ChannelCapabilities = {
  chatTypes: Array<ChatType | "thread">;
  polls?: boolean;
  reactions?: boolean;
  edit?: boolean;
  unsend?: boolean;
  reply?: boolean;
  effects?: boolean;
  groupManagement?: boolean;
  threads?: boolean;
  media?: boolean;
  tts?: {
    voice?: ChannelTtsVoiceDeliveryCapabilities;
  };
  nativeCommands?: boolean;
  blockStreaming?: boolean;
};
```

Solo `chatTypes` es obligatorio. El resto son *opt-in*: **ausente significa "no lo soporta"**. El core
usa esto para decidir si intenta editar un mensaje (streaming de tokens vía edición) o si lo manda
por chunks; si ofrece encuestas al modelo; si adapta una presentación rica a texto plano.

#### `config: ChannelConfigAdapter<ResolvedAccount>` (obligatorio)
El adaptador de configuración y **multi-cuenta**. `src/channels/plugins/types.adapters.ts`
[VERIFICADO EN CÓDIGO — transcripción completa del tipo]:

```ts
export type ChannelConfigAdapter<ResolvedAccount> = {
  listAccountIds: (cfg: OpenClawConfig) => string[];
  resolveAccount: (cfg: OpenClawConfig, accountId?: string | null) => ResolvedAccount;
  inspectAccount?: (cfg: OpenClawConfig, accountId?: string | null) => unknown;
  defaultAccountId?: (cfg: OpenClawConfig) => string;
  setAccountEnabled?: (params: {
    cfg: OpenClawConfig;
    accountId: string;
    enabled: boolean;
  }) => OpenClawConfig;
  deleteAccount?: (params: { cfg: OpenClawConfig; accountId: string }) => OpenClawConfig;
  isEnabled?: (account: ResolvedAccount, cfg: OpenClawConfig) => boolean;
  disabledReason?: (account: ResolvedAccount, cfg: OpenClawConfig) => string;
  isConfigured?: (account: ResolvedAccount, cfg: OpenClawConfig) => boolean | Promise<boolean>;
  isLinked?: (
    account: ResolvedAccount,
    cfg: OpenClawConfig,
  ) => ChannelAccountLinkState | Promise<ChannelAccountLinkState>;
  unconfiguredReason?: (account: ResolvedAccount, cfg: OpenClawConfig) => string;
  unlinkedReason?: (account: ResolvedAccount, cfg: OpenClawConfig) => string;
  describeAccount?: (account: ResolvedAccount, cfg: OpenClawConfig) => ChannelAccountSnapshot;
  resolveAllowFrom?: (params: {
    cfg: OpenClawConfig;
    accountId?: string | null;
  }) => Array<string | number> | undefined;
  formatAllowFrom?: (params: {
    cfg: OpenClawConfig;
    accountId?: string | null;
    allowFrom: Array<string | number>;
  }) => string[];
  hasConfiguredState?: (params: { cfg: OpenClawConfig; env?: NodeJS.ProcessEnv }) => boolean;
  hasPersistedAuthState?: (params: { cfg: OpenClawConfig; env?: NodeJS.ProcessEnv }) => boolean;
  resolveDefaultTo?: (params: {
    cfg: OpenClawConfig;
    accountId?: string | null;
  }) => string | undefined;
};
```

Solo dos métodos obligatorios: `listAccountIds` y `resolveAccount`. **La multi-cuenta está en el
contrato desde el diseño**, no bolteada después: un canal puede tener N cuentas configuradas (dos
bots de Telegram, tres servidores IRC) y todo el resto del sistema pasa `accountId` a través.

Y notar la distinción de **cuatro estados diferentes**, que la mayoría de los sistemas confunden en
un booleano:
- `isEnabled` — el usuario lo prendió.
- `isConfigured` — tiene la config mínima (token, host).
- `isLinked` — la credencial fue aceptada por el proveedor (`"linked" | "not-linked" | "unknown"`).
- `hasPersistedAuthState` — hay estado de sesión en disco (ej. WhatsApp Web).

Cada uno tiene su `*Reason` para poder decirle al humano *por qué* no anda.

#### `gateway?: ChannelGatewayAdapter` — el ciclo de vida real
Este es el que arranca y para el canal. `src/channels/plugins/types.adapters.ts` [VERIFICADO EN CÓDIGO]:

```ts
export type ChannelGatewayAdapter<ResolvedAccount = unknown> = {
  startAccount?: (ctx: ChannelGatewayContext<ResolvedAccount>) => Promise<unknown>;
  stopAccount?: (ctx: ChannelGatewayContext<ResolvedAccount>) => Promise<void>;
  /** Keep gateway auth bypass resolution mirrored through a lightweight top-level `gateway-auth-api.ts` artifact. */
  resolveGatewayAuthBypassPaths?: (params: { cfg: OpenClawConfig }) => string[];
  loginWithQrStart?: (params: {
    accountId?: string;
    force?: boolean;
    timeoutMs?: number;
    verbose?: boolean;
  }) => Promise<ChannelLoginWithQrStartResult>;
  loginWithQrWait?: (params: {
    accountId?: string;
    timeoutMs?: number;
    currentQrDataUrl?: string;
  }) => Promise<ChannelLoginWithQrWaitResult>;
  logoutAccount?: (ctx: ChannelLogoutContext<ResolvedAccount>) => Promise<ChannelLogoutResult>;
};
```

Y el contexto que recibe — **esto es el corazón del contrato** [VERIFICADO EN CÓDIGO]:

```ts
export type ChannelGatewayContext<ResolvedAccount = unknown> = {
  cfg: OpenClawConfig;
  accountId: string;
  account: ResolvedAccount;
  runtime: RuntimeEnv;
  abortSignal: AbortSignal;
  log?: ChannelLogSink;
  getStatus: () => ChannelAccountSnapshot;
  setStatus: (next: ChannelAccountSnapshot) => void;
  channelRuntime?: ChannelRuntimeSurface;
};
```

Siete cosas que el canal recibe y no tiene que resolver por su cuenta:

1. **`cfg`** — la config completa ya resuelta.
2. **`accountId` + `account`** — su cuenta, ya resuelta y tipada.
3. **`runtime`** — el entorno (logging, paths, etc.).
4. **`abortSignal`** — ⭐ **la señal de parada es un `AbortSignal` estándar.** El canal no implementa
   su propio protocolo de shutdown: escucha la señal. Esto es lo que hace que `stopAccount` sea
   opcional.
5. **`log`** — sink de logging con prefijo de canal ya puesto.
6. **`getStatus` / `setStatus`** — ⭐ **el canal no es dueño de su estado; lo publica.** El gateway lo
   guarda, lo expone por `channels.status`, lo usa para health monitoring. El canal solo hace
   `setStatus({...})` cuando se conecta o se cae.
7. **`channelRuntime`** — la superficie compartida (reply, routing, text, session, media, commands,
   groups, pairing). El comentario del código lo documenta explícitamente:

   > "- **reply**: AI response dispatching, formatting, and delivery
   > - **routing**: Agent route resolution and matching
   > - **text**: Text chunking, markdown processing, and control command detection
   > - **session**: Session management and metadata tracking
   > - **media**: Remote media fetching and buffer saving
   > - **commands**: Command authorization and control command handling
   > - **groups**: Group policy resolution and mention requirements
   > - **pairing**: Channel pairing and allow-from management"

   Es decir: **el canal no llama al LLM.** Recibe un mensaje del transporte, y le pide al
   `channelRuntime` que lo despache. Toda la lógica de agente, ruteo, sesión y política vive del lado
   del core.

   ⚠️ Es **opcional** (`channelRuntime?`), con nota de compatibilidad: *"External plugins should check
   for undefined before using"*, `@since Plugin SDK 2026.2.19`. Esto es deuda de compatibilidad
   visible: hay canales viejos que arrancan sin él.

#### `outbound?: ChannelOutboundAdapter` — la salida
`src/channels/plugins/outbound.types.ts`, campos centrales [VERIFICADO EN CÓDIGO]:

```ts
export type ChannelOutboundAdapter = {
  deliveryMode: "direct" | "gateway" | "hybrid";
  chunker?: ((text: string, limit: number, ctx?: ChannelOutboundChunkContext) => string[]) | null;
  chunkerMode?: "text" | "markdown";
  textChunkLimit?: number;
  extractMarkdownImages?: boolean;
  preserveMarkdownDetails?: (params: { cfg: OpenClawConfig; accountId?: string | null }) => boolean;
  sanitizeText?: (params: {
    text: string;
    payload: ReplyPayload;
    cfg?: OpenClawConfig;
    accountId?: string;
  }) => string;
  pollMaxOptions?: number;
  supportsPollDurationSeconds?: boolean;
  supportsAnonymousPolls?: boolean;
  normalizePayload?: (params: ChannelOutboundNormalizePayloadParams) => ReplyPayload | null;
  /** Normalize an ordered batch in place. Return one entry per input; null suppresses that send. */
  normalizePayloadBatch?: (
    params: ChannelOutboundNormalizePayloadBatchParams,
  ) => ReadonlyArray<ReplyPayload | null>;
  resolveEffectiveTextChunkLimit?: (params: {
    cfg: OpenClawConfig;
    accountId?: string | null;
    fallbackLimit?: number;
  }) => number | undefined;
  beforeDeliverPayload?: (params: {
    cfg: OpenClawConfig;
    target: ChannelOutboundTargetRef;
    payload: ReplyPayload;
    hint?: ChannelOutboundPayloadHint;
  }) => Promise<void> | void;
  afterDeliverPayload?: (params: {
    cfg: OpenClawConfig;
    target: ChannelOutboundTargetRef;
    payload: ReplyPayload;
    results: readonly OutboundDeliveryResult[];
  }) => Promise<void> | void;
  /** Channel-advertised presentation features and limits used by core adaptation. */
  presentationCapabilities?: ChannelPresentationCapabilities;
  deliveryCapabilities?: ChannelDeliveryCapabilities;
  /** Render an adapted portable presentation into channel-native payload data. */
  renderPresentation?: (params: {
    payload: ReplyPayload;
    presentation: MessagePresentation;
    ctx: ChannelOutboundPayloadContext;
  }) => Promise<ReplyPayload | null> | ReplyPayload | null;
  resolveTarget?: (params: {
    cfg?: OpenClawConfig;
    to?: string;
    allowFrom?: string[];
    accountId?: string | null;
    mode?: ChannelOutboundTargetMode;   // "explicit" | "implicit" | "heartbeat"
  }) => { ok: true; to: string } | { ok: false; error: Error };
  sendPayload?: (ctx: ChannelOutboundPayloadContext) => Promise<OutboundDeliveryResult>;
  sendFormattedText?: (ctx: ChannelOutboundFormattedContext) => Promise<OutboundDeliveryResult[]>;
  sendFormattedMedia?: (
    ctx: ChannelOutboundFormattedContext & { mediaUrl: string },
  ) => Promise<OutboundDeliveryResult>;
  sendText?: (ctx: ChannelOutboundContext) => Promise<OutboundDeliveryResult>;
  sendMedia?: (ctx: ChannelOutboundContext) => Promise<OutboundDeliveryResult>;
  sendPoll?: (ctx: ChannelPollContext) => Promise<ChannelPollResult>;
};
```

Lo importante:

- **`deliveryMode: "direct" | "gateway" | "hybrid"` es el único campo obligatorio.** Define si el
  mensaje sale directo desde el proceso del canal, si tiene que pasar por el gateway, o ambos. Este
  campo es el que permite que exista un daemon central sin obligar a todos los canales a rutear por él.
- **Hay cinco niveles de `send*`** con granularidad creciente de "el core ya hizo el trabajo":
  `sendText` (el core chunkeó y formateó) → `sendFormattedText` (el core formateó, el canal chunkea)
  → `sendPayload` (el canal hace todo). El canal implementa el nivel que le conviene.
- **`chunker` + `textChunkLimit` + `resolveEffectiveTextChunkLimit`**: el límite de caracteres por
  mensaje es parte del contrato, y puede ser dinámico por cuenta (un servidor IRC vs otro).
- **`presentationCapabilities` + `renderPresentation`**: el core produce una "presentación portable"
  (botones, tarjetas) y el canal la baja a su formato nativo. Si el canal no puede, el core degrada a
  texto. Esto es el patrón adaptador de UI multi-transporte bien hecho.
- **`beforeDeliverPayload` / `afterDeliverPayload`**: hooks para efectos secundarios (marcar leído,
  limpiar el indicador de "escribiendo").

#### `lifecycle?: ChannelLifecycleAdapter` — reacción a cambios de config
[VERIFICADO EN CÓDIGO]:

```ts
export type ChannelLifecycleAdapter = {
  onAccountConfigChanged?: (params: {
    prevCfg: OpenClawConfig;
    nextCfg: OpenClawConfig;
    accountId: string;
    runtime: RuntimeEnv;
  }) => Promise<void> | void;
  onAccountRemoved?: (params: {
    prevCfg: OpenClawConfig;
    accountId: string;
    runtime: RuntimeEnv;
  }) => Promise<void> | void;
  runStartupMaintenance?: (params: {
    cfg: OpenClawConfig;
    env?: NodeJS.ProcessEnv;
    log: { info?: (message: string) => void; warn?: (message: string) => void };
    trigger?: string;
    logPrefix?: string;
  }) => Promise<void> | void;
  detectLegacyStateMigrations?: (params: {
    cfg: OpenClawConfig;
    env: NodeJS.ProcessEnv;
    stateDir: string;
    oauthDir: string;
  }) => ChannelLegacyStateMigrationPlan[] | Promise<ChannelLegacyStateMigrationPlan[]>;
};
```

Notar que `onAccountConfigChanged` recibe **`prevCfg` y `nextCfg`**, no solo la nueva. El canal puede
decidir si el cambio amerita reconectar.

#### `reload` — hot-reload de configuración con granularidad declarada
```ts
reload?: {
  configPrefixes: string[];
  noopPrefixes?: string[];
  accountScopedRestart?: boolean;
};
```
El canal declara **qué prefijos de config le importan** (`["channels.irc"]`). Cuando el usuario cambia
la config, el core mira los prefijos y decide a quién reiniciar. `noopPrefixes` marca sub-rutas que
cambian pero no requieren reinicio. El comentario de `accountScopedRestart` es una advertencia
honesta sobre las condiciones para poder reiniciar una sola cuenta:

> "Set only when sibling account resolution and lifecycle state are isolated and account stop fully
> settles owned work. Shared, default, removed, or unresolved account changes still restart the whole
> channel."

#### `status?: ChannelStatusAdapter` — observabilidad
Cinco funciones opcionales: `probeAccount` (ping activo al proveedor, con `timeoutMs`),
`auditAccount`, `buildAccountSnapshot`, `buildChannelSummary`, `collectStatusIssues`.

`collectStatusIssues` devuelve un tipo con **remediación incorporada** [VERIFICADO EN CÓDIGO]:

```ts
export type ChannelStatusIssue = {
  channel: ChannelId;
  accountId: string;
  kind: "intent" | "permissions" | "config" | "auth" | "runtime";
  message: string;
  fix?: string;   // texto accionable: "Set channels.raft.profile or RAFT_PROFILE."
};
```

Y el snapshot que el canal publica (`ChannelAccountSnapshot`) tiene ~50 campos de telemetría.
Fragmento relevante, con un comentario que muestra pensamiento cuidadoso sobre los tri-estados
[VERIFICADO EN CÓDIGO]:

```ts
export type ChannelAccountSnapshot = {
  accountId: string;
  enabled?: boolean;
  configured?: boolean;
  linked?: boolean;
  running?: boolean;
  connected?: boolean;
  restartPending?: boolean;
  reconnectAttempts?: number;
  lastConnectedAt?: number | null;
  lastDisconnect?:
    | string
    | { at: number; status?: number; error?: string; loggedOut?: boolean }
    | null;
  lastMessageAt?: number | null;
  lastTransportActivityAt?: number | null;
  stateReason?: string;
  lastError?: string | null;
  healthState?: string;
  /**
   * Inbound admission, which is a different failure domain from `connected`.
   * Optional-`true` on purpose: there is no `false` to mistake for "unknown",
   * so the 20+ channels that never report ingress at all stay unaffected.
   */
  ingressUnavailable?: true;
  terminalDisconnect?: boolean;
  lastInboundAt?: number | null;
  lastOutboundAt?: number | null;
  busy?: boolean;
  activeRuns?: number;
  // ... + fuentes/estados de token: tokenSource, botTokenSource, tokenStatus, ...
};
```

⭐ **`ingressUnavailable?: true` — el patrón "optional-true" en vez de booleano.** El comentario
explica el razonamiento: con `boolean` opcional, `false` y `undefined` se confunden ("no puede
recibir" vs "no reporta"). Con `?: true`, ausente = desconocido, presente = problema. Es una decisión
de tipos de una sutileza que vale la pena robar.

Y `connected` vs `ingressUnavailable` son **dominios de falla distintos**: el socket puede estar vivo
y el canal no poder recibir mensajes (permisos, intents de Discord no habilitados).

#### `gatewayMethods` / `gatewayMethodDescriptors` — el canal extiende el protocolo
```ts
type ChannelGatewayMethodDescriptor = {
  name: string;
  scope?: OperatorScope;
  description?: string;
};
```
Un canal puede **registrar métodos propios en el gateway** (recordar `GatewayMethodOwner` con
`{ kind: "channel"; channelId: string }` de la sección 2.8). El protocolo es extensible por canal, con
scope declarado.

#### El resto (resumen)
`pairing`, `security` (política de DM: quién puede escribir), `allowlist`, `groups` (menciones y
política de herramientas por grupo), `mentions` (cómo quitar el `@bot` del texto), `threading`,
`streaming`, `messaging` (normalización de targets), `message` (adaptador de envío nativo),
`resolver`/`directory` (resolver nombres → ids), `actions` (acciones sobre mensajes: reaccionar,
editar, pinear), `commands`, `doctor` (chequeos de salud de config), `heartbeat` (typing indicators),
`secrets`, `agentTools`, `agentPrompt`, `elevated`, `approvalCapability`, `bindings` /
`conversationBindings` (ver sección 5).

### 3.3. `createChatChannelPlugin()` — la fábrica

`src/plugin-sdk/core.ts:825` [VERIFICADO EN CÓDIGO — función completa transcrita]:

```ts
/**
 * Build a chat-style channel plugin by composing common security, pairing,
 * threading, and outbound adapters around a channel-specific base.
 */
export function createChatChannelPlugin<
  TResolvedAccount extends { accountId?: string | null },
  Probe = unknown,
  Audit = unknown,
>(params: {
  base: ChatChannelPluginBase<TResolvedAccount, Probe, Audit>;
  security?:
    | ChannelSecurityAdapter<TResolvedAccount>
    | ChatChannelSecurityOptions<TResolvedAccount>;
  pairing?: ChannelPairingAdapter | ChatChannelPairingOptions;
  threading?: ChannelThreadingAdapter | ChatChannelThreadingOptions<TResolvedAccount>;
  outbound?: ChannelOutboundAdapter | ChatChannelAttachedOutboundOptions;
}): ChannelPlugin<TResolvedAccount, Probe, Audit> {
  return {
    ...params.base,
    conversationBindings: {
      supportsCurrentConversationBinding: true,
      ...params.base.conversationBindings,
    },
    ...(params.security ? { security: resolveChatChannelSecurity(params.security) } : {}),
    ...(params.pairing ? { pairing: resolveChatChannelPairing(params.pairing) } : {}),
    ...(params.threading ? { threading: resolveChatChannelThreading(params.threading) } : {}),
    ...(params.outbound ? { outbound: resolveChatChannelOutbound(params.outbound) } : {}),
  } as ChannelPlugin<TResolvedAccount, Probe, Audit>;
}
```

La fábrica hace **exactamente dos cosas**:

1. **Pone un default**: `conversationBindings.supportsCurrentConversationBinding: true` — todo canal
   de chat soporta "atarse a la conversación actual" salvo que diga lo contrario.
2. **Acepta forma corta o forma completa en 4 adapters.** Cada `resolveChatChannel*` mira si le
   pasaron el adapter completo o la opción declarativa, y expande la declarativa. Ejemplo verificado
   (`resolveChatChannelSecurity`): si el objeto no tiene la propiedad `dm`, se asume que ya es un
   adapter completo y se pasa tal cual; si la tiene, se construye el adapter llamando a
   `buildAccountScopedDmSecurityPolicy(...)`.

```ts
function resolveChatChannelSecurity<TResolvedAccount extends { accountId?: string | null }>(
  security: ChannelSecurityAdapter<TResolvedAccount> | ChatChannelSecurityOptions<TResolvedAccount> | undefined,
): ChannelSecurityAdapter<TResolvedAccount> | undefined {
  if (!security) {
    return undefined;
  }
  if (!("dm" in security)) {
    return security;   // ya es el adapter completo
  }
  return {
    resolveDmPolicy: ({ cfg, accountId, account }) =>
      buildAccountScopedDmSecurityPolicy({ /* ...expansión declarativa... */ }),
    // ...
  };
}
```

**El patrón general**: la fábrica es *azúcar declarativa opcional*, no una capa obligatoria. Un canal
puede construir el objeto `ChannelPlugin` a mano. Esto evita el problema clásico de "el framework me
obliga a pasar por su fábrica y no puedo hacer lo que necesito".

Hay una segunda fábrica, `createChannelPluginBase()`, que rellena la `meta` con defaults resueltos por
id (`resolveSdkChatChannelMeta(params.id)`) y copia campos solo si están presentes.

Nota: hay un test de forma (`src/channels/plugins/bundled.shape-guard.test.ts:1173`) que verifica
literalmente `source.includes("createChatChannelPlugin")` — es decir, **está testeado que los canales
bundled usen la fábrica**. Es una convención impuesta por CI, no solo documental.

### 3.4. Ejemplo mínimo real: `raft` (102 líneas)

`extensions/raft/src/channel.ts` — archivo completo [VERIFICADO EN CÓDIGO]. Este es el piso: **lo
mínimo que hace falta para tener un canal funcionando**.

```ts
// Raft channel plugin wires the wake bridge into the canonical channel runtime.
import { describeAccountSnapshot } from "openclaw/plugin-sdk/account-helpers";
import { createChatChannelPlugin, type ChannelPlugin } from "openclaw/plugin-sdk/channel-core";
import type { OpenClawConfig } from "openclaw/plugin-sdk/config-contracts";
import { detectBinary } from "openclaw/plugin-sdk/setup-tools";
import {
  buildBaseChannelStatusSummary,
  createComputedAccountStatusAdapter,
  createDefaultChannelRuntimeState,
} from "openclaw/plugin-sdk/status-helpers";
import {
  listRaftAccountIds, RAFT_CHANNEL_ID, resolveDefaultRaftAccountId,
  resolveRaftAccount, type ResolvedRaftAccount,
} from "./accounts.js";
import { raftChannelConfigSchema } from "./config-schema.js";
import { startRaftGatewayAccount } from "./gateway.js";
import { raftSetupPlugin } from "./setup.js";

type RaftProbe = { cliFound: boolean };

export const raftPlugin: ChannelPlugin<ResolvedRaftAccount, RaftProbe> = createChatChannelPlugin({
  base: {
    id: RAFT_CHANNEL_ID,
    meta: {
      id: RAFT_CHANNEL_ID,
      label: "Raft",
      selectionLabel: "Raft (CLI wake bridge)",
      docsPath: "/channels/raft",
      docsLabel: "raft",
      blurb: "Raft CLI wake bridge for human and agent collaboration.",
      order: 72,
    },
    capabilities: {
      chatTypes: ["direct"],
    },
    setupContract: raftSetupPlugin.setupContract,
    setupWizard: raftSetupPlugin.setupWizard,
    reload: { configPrefixes: ["channels.raft"] },
    configSchema: raftChannelConfigSchema,
    config: {
      listAccountIds: listRaftAccountIds,
      resolveAccount: (cfg: OpenClawConfig, accountId?: string | null) =>
        resolveRaftAccount({ cfg, accountId }),
      defaultAccountId: resolveDefaultRaftAccountId,
      isConfigured: (account) => account.configured,
      isEnabled: (account) => account.enabled,
      describeAccount: (account) =>
        describeAccountSnapshot({
          account,
          configured: account.configured,
          extra: { profile: account.profile },
        }),
    },
    status: createComputedAccountStatusAdapter<ResolvedRaftAccount, RaftProbe>({
      defaultRuntime: createDefaultChannelRuntimeState("default"),
      buildChannelSummary: ({ snapshot }) => buildBaseChannelStatusSummary(snapshot),
      probeAccount: async () => ({ cliFound: await detectBinary("raft") }),
      formatCapabilitiesProbe: ({ probe }) => [
        {
          text: `Raft CLI: ${probe.cliFound ? "found" : "missing"}`,
          ...(probe.cliFound ? {} : { tone: "error" as const }),
        },
      ],
      collectStatusIssues: (accounts) =>
        accounts.flatMap((account) => {
          if (!account.configured) {
            return [
              {
                channel: RAFT_CHANNEL_ID,
                accountId: account.accountId,
                kind: "config",
                message: "Raft account is missing a CLI profile",
                fix: "Set channels.raft.profile or RAFT_PROFILE.",
              },
            ];
          }
          return [];
        }),
      resolveAccountSnapshot: ({ account }) => ({
        accountId: account.accountId,
        name: account.name ?? undefined,
        enabled: account.enabled,
        configured: account.configured,
        extra: { profile: account.profile },
      }),
    }),
    gateway: {
      startAccount: async (ctx) => await startRaftGatewayAccount(ctx),
    },
  },
});
```

**Un canal completo son ~100 líneas** porque no declara `outbound`, `security`, `pairing`,
`threading`, `messaging`, `resolver`, `directory`, `groups`, `doctor`, `actions`. Toda la lógica real
está detrás de `startAccount`, en `./gateway.js`. **Ese es el nivel de piso que hay que apuntar.**

### 3.5. Ejemplo medio: `irc` (348 líneas)

`extensions/irc/src/channel.ts` [VERIFICADO EN CÓDIGO]. Muestra qué se agrega cuando el canal tiene
identidad de red, grupos, y política de DM. Fragmentos representativos:

```ts
export const ircPlugin: ChannelPlugin<ResolvedIrcAccount, IrcProbe> = createChatChannelPlugin({
  base: {
    id: "irc",
    meta: { ...meta, quickstartAllowFrom: true },
    setupContract: ircSetupContract,
    setupWizard: ircSetupWizard,
    capabilities: {
      chatTypes: ["direct", "group"],
      media: true,
      blockStreaming: true,
    },
    reload: { configPrefixes: ["channels.irc"] },
    configSchema: IrcChannelConfigSchema,
    config: {
      ...ircConfigAdapter,
      hasConfiguredState: ({ env }) =>
        typeof env?.IRC_HOST === "string" && env.IRC_HOST.trim().length > 0 &&
        typeof env?.IRC_NICK === "string" && env.IRC_NICK.trim().length > 0,
      isConfigured: (account) => account.configured,
      describeAccount: (account) => describeAccountSnapshot({ /* ... */ }),
    },
    secrets: { secretTargetRegistryEntries, collectRuntimeConfigAssignments },
    doctor: {
      groupAllowFromFallbackToAllowFrom: false,
      collectMutableAllowlistWarnings: collectIrcMutableAllowlistWarnings,
    },
    groups: {
      resolveRequireMention: ({ cfg, accountId, groupId }) => {
        const account = resolveIrcAccount({ cfg: cfg as CoreConfig, accountId });
        if (!groupId) { return true; }
        return resolveIrcGroupRequireMention({ groups: account.config.groups, target: groupId });
      },
      resolveToolPolicy: ({ cfg, accountId, groupId }) => { /* ... */ },
    },
    messaging: {
      targetPrefixes: ["irc"],
      normalizeTarget: normalizeIrcMessagingTarget,
      resolveOutboundSessionRoute: (params) => resolveIrcOutboundSessionRoute(params),
      targetResolver: { looksLikeId: looksLikeIrcTargetId, hint: "<#channel|nick>" },
    },
    message: ircMessageAdapter,
    resolver: { resolveTargets: async ({ inputs, kind }) => { /* # = grupo, resto = usuario */ } },
    directory: createChannelDirectoryAdapter({ listPeers: /*...*/, listGroups: /*...*/ }),
    status: createComputedAccountStatusAdapter<ResolvedIrcAccount, IrcProbe>({ /* ... */ }),
    gateway: {
      startAccount: async (ctx) =>
        await startIrcGatewayAccount({ ...ctx, cfg: ctx.cfg as CoreConfig }),
    },
  },
  pairing: {
    text: {
      idLabel: "ircUser",
      message: PAIRING_APPROVED_MESSAGE,
      normalizeAllowEntry: (entry) => normalizeIrcAllowEntry(entry),
      notify: async ({ cfg, id, message }) => {
        const target = normalizePairingTarget(id);
        if (!target) { throw new Error(`invalid IRC pairing id: ${id}`); }
        const { sendMessageIrc } = await loadIrcChannelRuntime();
        await sendMessageIrc(target, message, { cfg: cfg as CoreConfig });
      },
    },
  },
  security: { resolveDmPolicy: resolveIrcDmPolicy, collectWarnings: collectIrcSecurityWarnings },
  outbound: {
    base: ircOutboundBaseAdapter,
    attachedResults: {
      channel: "irc",
      sendText: ({ onDeliveryResult: _onDeliveryResult, ...ctx }) => ircMessageAdapter.send.text(ctx),
      sendMedia: ({ onDeliveryResult: _onDeliveryResult, mediaUrl, ...ctx }) =>
        ircMessageAdapter.send.media({ ...ctx, mediaUrl: mediaUrl ?? "" }),
    },
  },
});
```

Cosas a robar de acá:

- **`createLazyRuntimeModule(() => import("./channel-runtime.js"))`** — el runtime pesado del canal se
  carga **perezosamente**. El archivo `channel.ts` solo declara; nada del cliente IRC se importa hasta
  que hace falta. Con 25+ canales bundled, esto es lo que evita que el arranque cargue todos los SDKs.
- **Los warnings de seguridad son parte del canal**, escritos como texto accionable:
  ```ts
  (account) => !account.config.tls &&
    "- IRC TLS is disabled (channels.irc.tls=false); traffic and credentials are plaintext.",
  (account) => account.config.nickserv?.register &&
    '- IRC NickServ registration is enabled ...; this sends "REGISTER" on every connect. Disable after first successful registration.',
  ```
  El canal conoce sus propias trampas y las reporta. El core no sabe nada de NickServ.
- **`capabilities.blockStreaming: true`** — IRC no puede editar mensajes, así que el streaming se hace
  por bloques completos, no token a token. Una línea de declaración cambia el comportamiento de
  entrega del core.

### 3.6. Ejemplo distinto: `googlechat` (webhook, 200 líneas)

`extensions/googlechat/src/channel.ts` [VERIFICADO EN CÓDIGO]. Es el contraste útil: **no mantiene
conexión persistente**, recibe por webhook HTTP. Fragmentos:

```ts
export const googlechatPlugin = createChatChannelPlugin({
  base: {
    ...createGoogleChatPluginBase({
      configSchema: buildChannelConfigSchema(GoogleChatConfigSchema),
    }),
    approvalCapability: googleChatApprovalCapability,
    secrets: { secretTargetRegistryEntries, collectRuntimeConfigAssignments },
    groups: googlechatGroupsAdapter,
    messaging: {
      targetPrefixes: ["googlechat", "google-chat", "gchat"],
      targetIdComparison: "case-sensitive",
      normalizeTarget: normalizeGoogleChatTarget,
      resolveOutboundSessionRoute: (params) => resolveGoogleChatOutboundSessionRoute(params),
      targetResolver: {
        looksLikeId: (raw, normalized) => {
          const value = normalized ?? raw.trim();
          return isGoogleChatSpaceTarget(value) || isGoogleChatUserTarget(value);
        },
        hint: "<spaces/{space}|users/{user}>",
      },
    },
    doctor: {
      dmAllowFromMode: "topOnly",
      groupModel: "route",
      groupAllowFromFallbackToAllowFrom: false,
      warnOnEmptyGroupSenderAllowlist: false,
      legacyConfigRules: GOOGLECHAT_LEGACY_CONFIG_RULES,
      normalizeCompatibilityConfig: normalizeGoogleChatCompatibilityConfig,
      collectMutableAllowlistWarnings: collectGoogleChatMutableAllowlistWarnings,
    },
    status: createComputedAccountStatusAdapter<ResolvedGoogleChatAccount>({
      defaultRuntime: createDefaultChannelRuntimeState(DEFAULT_ACCOUNT_ID),
      collectStatusIssues: (accounts): ChannelStatusIssue[] =>
        accounts.flatMap((entry) => {
          const accountId = entry.accountId ?? DEFAULT_ACCOUNT_ID;
          if (entry.enabled === false || entry.configured !== true) { return []; }
          const issues: ChannelStatusIssue[] = [];
          if (!entry.audience) {
            issues.push({
              channel: GOOGLECHAT_CHANNEL_ID, accountId, kind: "config",
              message: "Google Chat audience is missing (set channels.googlechat.audience).",
              fix: "Set channels.googlechat.audienceType and channels.googlechat.audience.",
            });
          }
          // ... idem audienceType
          return issues;
        }),
      buildChannelSummary: ({ snapshot }) =>
        buildPassiveProbedChannelStatusSummary(snapshot, {
          credentialSource: snapshot.credentialSource ?? "none",
          audienceType: snapshot.audienceType ?? null,
          audience: snapshot.audience ?? null,
          webhookPath: snapshot.webhookPath ?? null,
          webhookUrl: snapshot.webhookUrl ?? null,
        }),
      probeAccount: async ({ account }) =>
        (await loadGoogleChatChannelRuntime()).probeGoogleChat(account),
      resolveAccountSnapshot: ({ account }) => ({ /* ... */ }),
    }),
    gateway: { startAccount: startGoogleChatGatewayAccount },
  },
  pairing: { text: googlechatPairingTextAdapter },
  security: googlechatSecurityAdapter,
  threading: googlechatThreadingAdapter,
  outbound: {
    ...googlechatOutboundAdapter,
    base: {
      ...googlechatOutboundAdapter.base,
      shouldSuppressLocalPayloadPrompt: ({ cfg, accountId, payload, hint }) =>
        shouldSuppressLocalGoogleChatExecApprovalPrompt({ cfg, accountId, payload, hint }),
    },
  },
});
```

Lo comparativo interesante:

- **El mismo `gateway.startAccount` sirve para un canal de webhook.** Lo que arranca no es un socket:
  es el registro de la ruta HTTP en el servidor del gateway. El contrato no distingue "canal push" de
  "canal pull" — es responsabilidad del `startAccount`, no del tipo.
- **`buildPassiveProbedChannelStatusSummary`** vs el `buildBaseChannelStatusSummary` de raft: hay un
  helper distinto para canales que no mantienen conexión, porque `connected` no significa nada ahí.
  Es decir: **el modelo de estado tuvo que bifurcarse** para acomodar el caso pasivo. Señal de que la
  abstracción no es tan uniforme como parece.
- **`targetIdComparison: "case-sensitive"`** — un detalle que casi nadie modela y que rompe cosas
  (`spaces/AAQ...` de Google Chat es case-sensitive; los nicks de IRC no).
- **`approvalCapability`** — el canal puede servir como superficie para aprobaciones de ejecución
  (el humano aprueba un `exec` desde Google Chat). Esto conecta el contrato de canal con el sistema de
  exec approvals descrito en `01-seguridad-y-aislamiento.md`.

### 3.7. Registro y resolución de canales

`src/channels/plugins/registry.ts` [VERIFICADO EN CÓDIGO]:

```ts
/**
 * Resolves the active channel implementation together with host-owned provenance.
 */
export function resolveChannelPluginRegistration(
  id: ChannelId,
): { plugin: ChannelPlugin; origin?: string } | undefined {
  const resolvedId = normalizeOptionalString(id) ?? "";
  if (!resolvedId) {
    return undefined;
  }
  // Resolve implementation and provenance together. Loaded overrides win and
  // must never borrow bundled authority from the fallback with the same id.
  const loadedEntry = getLoadedChannelPluginEntryById(resolvedId);
  if (loadedEntry) {
    const origin = normalizeOptionalString(loadedEntry.origin) ?? undefined;
    return {
      plugin: loadedEntry.plugin as ChannelPlugin,
      ...(origin ? { origin } : {}),
    };
  }
  const plugin = getBundledChannelPlugin(resolvedId);
  return plugin ? { plugin, origin: "bundled" } : undefined;
}
```

El comentario declara una invariante de seguridad concreta: un plugin cargado externamente que
comparte id con uno bundled **gana la resolución pero NO hereda la autoridad de "bundled"** — el
`origin` viaja con el plugin. Es la defensa contra el ataque "publico un paquete llamado `telegram` y
heredo los privilegios del canal oficial". La procedencia se resuelve **junto con** la implementación,
en la misma función, para que no puedan desincronizarse.

---

## 4. Arquitectura del daemon

### 4.1. Escala real (para calibrar expectativas)

Antes de nada, el tamaño honesto de lo que se está describiendo [VERIFICADO EN CÓDIGO — conteo de
archivos]:

- `src/gateway/` tiene **~850 archivos**.
- Solo en la raíz de `src/gateway/` hay **~190 archivos `server-*.ts`**.
- `src/gateway/server/` (la capa de transporte) tiene ~35 archivos.
- `src/gateway/server/ws-connection/` (solo el handshake y dispatch de una conexión) tiene 36 archivos.
- `src/daemon/` (supervisión de proceso: launchd, systemd, servicio de Windows) tiene ~50 archivos.

Esto **no es un patrón para copiar entero**. Lo valioso es el esqueleto de arranque y el orden de
apagado, que son ~200 líneas conceptuales enterradas bajo 850 archivos de casos borde.

### 4.2. Punto de entrada y carga perezosa

`src/gateway/server.ts` (archivo completo, 42 líneas) [VERIFICADO EN CÓDIGO]:

```ts
/**
 * Lazy public entrypoint for the gateway server implementation.
 *
 * Keeping `server.impl` behind dynamic import lets light-weight callers import
 * server types and helpers without paying the full startup dependency graph.
 */
export { truncateCloseReason } from "./server/close-reason.js";
export type { GatewayServer, GatewayServerOptions } from "./server.impl.js";

async function emitStartupTrace(name: string, durationMs: number, totalMs: number): Promise<void> {
  if (!process.env.OPENCLAW_GATEWAY_STARTUP_TRACE) {
    return;
  }
  const { formatConsoleDiagnosticLine } = await import("../logging/json-console-line.js");
  const message = `[gateway] startup trace: ${name} ${durationMs.toFixed(1)}ms total=${totalMs.toFixed(1)}ms`;
  process.stderr.write(`${formatConsoleDiagnosticLine({ level: "info", message })}\n`);
}

async function loadServerImpl() {
  const startupStartedAt = performance.now();
  const before = performance.now();
  try {
    return await import("./server.impl.js");
  } finally {
    const now = performance.now();
    await emitStartupTrace("gateway.server-impl-import", now - before, now - startupStartedAt);
  }
}

/** Starts the gateway server after lazily loading the full server implementation. */
export async function startGatewayServer(
  ...args: Parameters<typeof import("./server.impl.js").startGatewayServer>
): ReturnType<typeof import("./server.impl.js").startGatewayServer> {
  const mod = await loadServerImpl();
  return await mod.startGatewayServer(...args);
}
```

Tres decisiones a notar:

1. **El módulo público solo tiene tipos y un `import()` dinámico.** Cualquiera que quiera hablar del
   gateway (CLI, tests, otro proceso) importa tipos sin pagar el grafo de dependencias completo.
2. **Trazado de arranque bajo variable de entorno** (`OPENCLAW_GATEWAY_STARTUP_TRACE`), instrumentando
   el import mismo. El arranque es lo bastante caro como para medirlo.
3. Ni siquiera el logger se importa eagermente: `formatConsoleDiagnosticLine` se importa dentro de la
   función de traza.

### 4.3. El contrato público del servidor

`src/gateway/server-public.ts` [VERIFICADO EN CÓDIGO — transcripción literal]:

```ts
export type GatewayCloseOptions = {
  reason?: string;
  restartExpectedMs?: number | null;
  drainTimeoutMs?: number | null;
};

export type GatewayServer = {
  close: (opts?: GatewayCloseOptions) => Promise<void>;
};

export type GatewayServerOptions = {
  /**
   * Bind address policy for the Gateway WebSocket/HTTP server.
   * - loopback: 127.0.0.1
   * - lan: 0.0.0.0
   * - tailnet: bind to the Tailscale IPv4 address (100.64.0.0/10) and local 127.0.0.1
   * - auto: prefer loopback, else LAN
   */
  bind?: GatewayBindMode;
  /**
   * Advanced override for the bind host, bypassing bind resolution.
   * Prefer `bind` unless you really need a specific address.
   */
  host?: string;
  /**
   * If false, do not serve the browser Control UI.
   * Default: config `gateway.controlUi.enabled` (or true when absent).
   */
  controlUiEnabled?: boolean;
  /**
   * If false, do not serve `POST /v1/chat/completions`.
   * Default: config `gateway.http.endpoints.chatCompletions.enabled` (or false when absent).
   */
  openAiChatCompletionsEnabled?: boolean;
  /**
   * If false, do not serve `POST /v1/responses` (OpenResponses API).
   */
  openResponsesEnabled?: boolean;
  /** Override gateway auth configuration (merges with config). */
  auth?: GatewayAuthConfig;
  /** Override gateway Tailscale exposure configuration (merges with config). */
  tailscale?: GatewayTailscaleConfig;
  /** Test-only: override the setup wizard runner. */
  wizardRunner?: SetupWizardRunner;
  /** Test-only: override the channel-setup wizard runner (wizard.start flow "channels"). */
  channelWizardRunner?: ChannelSetupWizardRunner;
  sidecarStartup?: GatewaySidecarStartupMode;
  channelAutostartSuppression?: ChannelAutostartSuppression;
  ambientEnvTriggers?: AmbientEnvTriggerPolicy;
  /** Optional startup timestamp used for concise readiness logging. */
  startupStartedAt?: number;
  /**
   * Config snapshot already read by the CLI gateway preflight. Passing it avoids
   * reparsing openclaw.json during server startup.
   */
  startupConfigSnapshotRead?: ReadConfigFileSnapshotWithPluginMetadataResult;
  /** Restart request override; direct servers fail closed on restart-required reloads. */
  hotReloadRecovery?: GatewayRestartEmitter;
};
```

⭐ **`GatewayServer` es un objeto con UN método: `close()`.** Todo lo demás se accede por el protocolo
WebSocket. El handle de proceso no expone `send()`, ni `getState()`, ni nada. **La única API del
gateway es el protocolo**, incluso para quien lo arrancó en su mismo proceso.

⭐ **`bind` es una política con nombre, no un host.** `loopback | lan | tailnet | auto`. El caso
inseguro (`0.0.0.0`) requiere escribir la palabra `lan` explícitamente. Esto es el patrón
"configuración por intención, no por valor" — copiable directamente.

### 4.4. La secuencia de arranque

`src/gateway/server-start.ts:startGatewayServer()` [VERIFICADO EN CÓDIGO — función completa]:

```ts
export async function startGatewayServer(
  port = 18789,
  opts: GatewayServerOptions = {},
): Promise<GatewayServer> {
  const bootstrap = await prepareGatewayServerBootstrap({
    port, opts, log, logSecrets,
    loadWorkerEnvironmentStartupModule,
    formatRuntimeGatewayAuthTokenWarning,
  });
  const runtime = await prepareGatewayRuntimeState({
    bootstrap, port, opts, log, logChannels, logHooks, logPlugins, gatewayRuntime,
    resolveChannelRuntime: getChannelRuntime,
    loadWorkerEnvironmentStartupModule,
    loadWorkerPlacementStartupModule,
  });
  const lifecycleRuntime = await prepareGatewayLifecycle({
    runtime, port, log, logCron,
    diagnosticsEnabled: bootstrap.diagnosticsEnabled,
    loadGatewayCloseModule,
    closeMcpLoopbackServerOnDemand,
    stopTaskRegistryMaintenanceOnDemand,
  });
  const {
    beginClosePrelude,
    clearFallbackGatewayContextForServer,
    closeOnStartupFailure,
    createCloseHandler,
    runClosePrelude,
    stopRegisteredGatewayLifetimeSidecars,
    stopRegisteredPostReadySidecars,
    terminalSessions,
  } = lifecycleRuntime;
  try {
    const coreRuntime = await startGatewayCoreRuntime({
      lifecycleRuntime, port, log, logDiscovery, logHealth, logChannels,
      loadGatewayStartupEarlyModule,
      loadGatewayPluginBootstrapModule,
      loadGatewayModelCatalog,
      loadGatewayModelCatalogSnapshot,
    });
    await finishGatewayStartup({
      coreRuntime, port, opts, log, logHealth, logWsControl, logHooks,
      logChannels, logCron, logReload, logTailscale,
      loadGatewayStartupPostAttachModule,
    });
  } catch (err) {
    await closeOnStartupFailure();
    throw err;
  }

  const close = createCloseHandler();

  return {
    close: async (optsLocal) => {
      try {
        await beginClosePrelude();
        // Kill any live operator shells before the socket layer tears down.
        terminalSessions.disposeAll();
        await stopRegisteredGatewayLifetimeSidecars();
        await stopRegisteredPostReadySidecars();
        // Run gateway_stop plugin hook before shutdown
        const { runGlobalGatewayStopSafely } = await import("../plugins/hook-runner-global.js");
        await runGlobalGatewayStopSafely({
          event: { reason: optsLocal?.reason ?? "gateway stopping" },
          ctx: { port },
          onError: (err) => log.warn(`gateway_stop hook failed: ${String(err)}`),
        });
        await runClosePrelude();
        await close(optsLocal);
      } finally {
        clearFallbackGatewayContextForServer.get()();
      }
    },
  };
}
```

**Cinco fases, en orden, y esto es lo copiable:**

| # | Fase | Qué hace |
|---|---|---|
| 1 | `prepareGatewayServerBootstrap` | Lee config, resuelve auth/secretos. **Todavía no hay socket.** |
| 2 | `prepareGatewayRuntimeState` | Construye el estado en memoria: canales, plugins, hooks, workers. |
| 3 | `prepareGatewayLifecycle` | ⭐ **Construye el handler de CIERRE antes de abrir nada.** |
| 4 | `startGatewayCoreRuntime` | Abre el socket, arranca discovery/health/canales. |
| 5 | `finishGatewayStartup` | Post-attach: cron, hot-reload, tailscale, sidecars post-ready. |

⭐⭐ **La fase 3 es la lección central.** El camino de apagado (`closeOnStartupFailure`) se construye
**antes** de que exista algo que apagar. Por eso el `try/catch` de las fases 4-5 puede hacer
`await closeOnStartupFailure()` y limpiar correctamente **un arranque a medias**. La mayoría de los
daemons hechos a mano fallan justo acá: si el arranque revienta en el paso 7 de 9, quedan colgados
timers, sockets y procesos hijo porque el teardown se escribió asumiendo un arranque completo.

Segunda lección: **el `close()` devuelto es un envoltorio, no el close crudo.** Envuelve el cierre en
un orden explícito: prelude → matar shells de operador → sidecars de vida-del-gateway → sidecars
post-ready → hook de plugins `gateway_stop` → prelude de cierre → cierre real, y en `finally` limpia
el contexto global. El `finally` garantiza que **un cierre fallido no deja un gateway fantasma
registrado**.

### 4.5. Puerto, bind y colisión de instancias

`src/config/paths.ts:344` [VERIFICADO EN CÓDIGO]:

```ts
export const DEFAULT_GATEWAY_PORT = 18789;
```

> ⚠️ **CORRECCIÓN DE UNA VERSIÓN ANTERIOR DE ESTE DOCUMENTO.** En un primer pase escribí acá un
> "hallazgo negativo" afirmando que no existía lockfile ni pidfile y que el bind TCP era el único
> mecanismo de exclusión mutua. **Era falso.** Busqué solo en `src/gateway/` y `src/daemon/`, y el
> lock vive **una capa más arriba** (`src/infra/gateway-lock.ts`, 550 líneas, invocado desde
> `src/cli/gateway-cli/run.ts`). Lección metodológica que vale para todo el documento: cuando algo
> no aparece donde uno lo espera, subir o bajar una capa antes de concluir que no existe.

#### Exclusión mutua real: tres capas [VERIFICADO EN CÓDIGO]

`docs/gateway/gateway-lock.md` lo describe y el código lo respalda. El arranque impone la propiedad
en tres pasos, **en orden**:

| # | Capa | Qué protege | Dónde |
|---|------|-------------|-------|
| 1 | **State ownership lock** | El *state directory* canónico. Lo toman **todos** los gateways, incluso los que corren con `OPENCLAW_ALLOW_MULTI_GATEWAY=1`, para que el mantenimiento destructivo de SQLite no pueda correr contra un dueño vivo. | `src/infra/gateway-lock.ts` |
| 2 | **Config lock** | El par (config, puerto). Es el singleton histórico. **Multi-gateway lo saltea**, pero conserva el lock de estado. | `src/infra/gateway-lock.ts` |
| 3 | **Socket bind** | El listener HTTP/WS exclusivo (`ws://127.0.0.1:18789` por defecto). | `src/gateway/server/http-listen.ts` |

Cada capa falla de forma independiente y lanza su propio `GatewayLockError`.

**El payload del lock** — esto es lo que hay que copiar, porque la gracia del diseño está acá
(`src/infra/gateway-lock.ts:30-50`) [VERIFICADO EN CÓDIGO]:

```ts
type LockPayload = {
  pid: number;
  ownerId?: string;
  createdAt: string;
  configPath: string;
  port?: number;
  role?: GatewayLockRole;
  stateDir?: string;
  startTime?: number;
};

const LockPayloadSchema = z.object({
  pid: z.number(),
  ownerId: z.string().min(1).optional(),
  createdAt: z.string(),
  configPath: z.string(),
  port: z.number().int().min(1).max(65_535).optional(),
  role: z.enum(["gateway", "skill-workshop-apply", "sqlite-maintenance"]).optional(),
  stateDir: z.string().optional(),
  startTime: z.number().optional(),
}) as z.ZodType<LockPayload>;

type GatewayLockHandle = {
  lockPath: string;
  stateLockPath: string;
  configPath: string;
  release: () => Promise<void>;
};

type GatewayLockRole = "gateway" | "skill-workshop-apply" | "sqlite-maintenance";
```

Puntos no obvios:

- **`role` convierte el lock en un lock multipropósito.** No es solo "hay un gateway": también lo
  toman `skill-workshop-apply` y `sqlite-maintenance`. Un lector de lock que busca el gateway
  descarta explícitamente los otros roles (`if (payload.role && payload.role !== "gateway") return undefined`).
- **`startTime` es lo que hace el lock resistente a reuso de PID.** Un PID vivo no prueba que sea
  *el mismo* proceso; el start-time del proceso sí.
- **`ownerId` (un `randomUUID()`)** permite comparar identidad de dueño sin depender de PID.
- **El puerto se guarda dentro del lock**, así que `readActiveGatewayLockPort()` es cómo el resto
  del sistema descubre en qué puerto está el gateway vivo sin escanear.

Constantes (`src/infra/gateway-lock.ts:25-28`):

```ts
const DEFAULT_TIMEOUT_MS = 5000;
const DEFAULT_POLL_INTERVAL_MS = 100;
const DEFAULT_STALE_MS = 30_000;
const GATEWAY_LOCKS = createFileLockManager("openclaw.gateway-lock");
```

**Rutas del lock** — derivadas por hash, no por nombre fijo (`resolveGatewayLockPaths`):

```ts
const configHash = sha256HexPrefix(configPath, 8);
const stateHash = sha256HexPrefix(stateDir, 8);
return {
  configLockPath: path.join(lockDir, `gateway.${configHash}.lock`),
  configPath,
  stateDir,
  stateLockPath: path.join(lockDir, `gateway.state.${stateHash}.lock`),
};
```

Y `canonicalizeStateDir()` resuelve `realpath` **caminando hacia arriba si el directorio todavía no
existe**, con este comentario textual: `// Keep walking so aliases in an existing ancestor still share one lock.`
O sea: dos rutas distintas que apuntan al mismo directorio real (symlinks, `/var` vs `/private/var`
en macOS) comparten **un solo** lock. Es el bug clásico de los locks por ruta, y acá está resuelto.

**Detección de lock rancio** — `src/infra/stale-lock-file.ts` [VERIFICADO EN CÓDIGO], con el
comentario que explica la decisión de diseño:

```ts
export function isLockOwnerDefinitelyStale(params: {...}): boolean {
  const payload = readLockFileOwnerPayload(params.payload);
  if (payload?.pid) {
    // Timestamp age alone cannot prove the owner stopped writing. Only a
    // mismatched process start time proves PID reuse while the PID is alive.
    ...
  }
  // The sidecar is created before its owner payload is written. Without a PID,
  // age cannot distinguish a crashed writer from a suspended live writer.
  return false;
}
```

Traducido: **la antigüedad de un lock nunca alcanza para declararlo muerto.** Solo se lo reclama si
el PID está definitivamente muerto o si el start-time no coincide (reuso de PID). Un proceso
suspendido (`SIGSTOP`, laptop dormida) no pierde su lock por viejo. Esto es exactamente lo contrario
de lo que hace la implementación ingenua de "si el lockfile tiene más de N minutos, borralo".

**Capa 3, el bind, con reintento de TIME_WAIT** — `src/gateway/server/http-listen.ts` (74 líneas,
archivo completo transcrito) [VERIFICADO EN CÓDIGO]:

```ts
// Gateway HTTP server listen helper with retry and lock-aware errors.
const EADDRINUSE_MAX_RETRIES = 20;
const EADDRINUSE_RETRY_INTERVAL_MS = 500;

/** Listen on the configured gateway host/port, retrying transient EADDRINUSE windows. */
export async function listenGatewayHttpServer(params: {
  httpServer: HttpServer;
  bindHost: string;
  port: number;
  retryEaddrinuse?: boolean;
  serviceName?: string;
  endpointScheme?: "http" | "https" | "ws" | "wss";
}) {
  const { httpServer, bindHost, port, retryEaddrinuse = true,
          serviceName = "gateway", endpointScheme = "ws" } = params;
  const maxRetries = retryEaddrinuse ? EADDRINUSE_MAX_RETRIES : 0;

  for (const attempt of Array.from({ length: maxRetries + 1 }, (_, index) => index)) {
    try {
      await new Promise<void>((resolve, reject) => {
        const onError = (err: NodeJS.ErrnoException) => {
          httpServer.off("listening", onListening);
          reject(err);
        };
        const onListening = () => {
          httpServer.off("error", onError);
          resolve();
        };
        httpServer.once("error", onError);
        httpServer.once("listening", onListening);
        httpServer.listen(port, bindHost);
      });
      return; // bound successfully
    } catch (err) {
      const code = (err as NodeJS.ErrnoException).code;
      if (code === "EADDRINUSE" && attempt < maxRetries) {
        // Port may still be in TIME_WAIT after a recent process exit; retry.
        await closeServerQuietly(httpServer);
        await sleep(EADDRINUSE_RETRY_INTERVAL_MS);
        continue;
      }
      if (code === "EADDRINUSE") {
        throw new GatewayLockError(
          `another ${serviceName} instance is already listening on ${endpointScheme}://${bindHost}:${port}`, err);
      }
      throw new GatewayLockError(
        `failed to bind ${serviceName} socket on ${endpointScheme}://${bindHost}:${port}: ${String(err)}`, err);
    }
  }
}
```

20 intentos × 500 ms ≈ 10 s de tolerancia al TIME_WAIT. **Esto invalida la advertencia que yo mismo
había escrito** sobre que "el rearranque falla temporalmente y lo tiene que manejar el supervisor":
lo maneja el propio proceso.

#### Interacción con el supervisor (systemd/launchd) [VERIFICADO EN CÓDIGO]

`src/cli/gateway-cli/run.ts` [VERIFICADO EN CÓDIGO]:

```ts
/**
 * EX_CONFIG (78) from sysexits.h — used for configuration errors so systemd
 * (via RestartPreventExitStatus=78) stops restarting instead of entering a
 * ...
 */
const EXIT_CONFIG_ERROR = 78;

class SupervisedGatewayLockError extends GatewayLockError { ... }
```

El flujo cuando arranca un segundo gateway **bajo supervisor**: antes de fallar por el lock, sondea
`/healthz` del proceso existente.

- Si el existente está sano y el supervisor es `systemd` → sale con **78**, y
  `RestartPreventExitStatus=78` corta el loop de `Restart=always`.
- Si es otro supervisor → `"gateway already running under <supervisor>; existing gateway is healthy, leaving it in control"`.
- Si el existente **nunca** se pone sano → el reintento tiene tope temporal y entonces sí falla con
  el error de lock, en vez de girar para siempre.

Este es el detalle de ingeniería más caro de descubrir por uno mismo: **un lock sin cooperación con
el supervisor produce loops de reinicio infinitos.** Acá está resuelto con un exit code dedicado.

---

Además, el CLI tiene su propio sondeo previo de puerto en `src/cli/ports.ts` [VERIFICADO EN CÓDIGO]:

```ts
/**
 * Attempt a real TCP bind to verify the port is available at the OS level.
 * Catches TIME_WAIT / kernel-level holds that lsof won't show.
 *
 * Resolves false only for EADDRINUSE — a genuinely transient condition
 * (port still in TIME_WAIT after a --force kill) that the caller should retry.
 *
 * All other errors are non-retryable and are rejected immediately:
 * - EADDRNOTAVAIL: the host address doesn't exist on any local interface
 *   (hard misconfiguration, not a transient kernel hold).
 * - EACCES: bind to a privileged port as non-root.
 * - EINVAL, etc.: other unrecoverable OS errors.
 */
function probePortFree(port: number, host = "0.0.0.0"): Promise<boolean> {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.unref();
    srv.once("error", (err: NodeJS.ErrnoException) => {
      srv.close();
      if (err.code === "EADDRINUSE") {
        // Genuinely transient — port still in use or TIME_WAIT after a --force kill.
        resolve(false);
      } else {
        reject(err);
      }
    });
    srv.listen(port, host, () => {
      srv.close(() => resolve(true));
    });
  });
}
```

Nota de calidad: **distingue `EADDRINUSE` (reintentar) de todo lo demás (fallar ya)**. Es el matiz que
casi nadie implementa y que hace que un `--force` funcione sin loops infinitos contra un
`EADDRNOTAVAIL`.

**Resumen de 4.5 para reimplementar**: el single-instance de OpenClaw no es una cosa, son cuatro
mecanismos apilados — lock de estado (siempre), lock de config (salteable), bind exclusivo con
reintento de TIME_WAIT, y cooperación con el supervisor vía exit code 78. Cada uno cubre un modo de
falla distinto: corrupción de estado compartido, doble gateway sobre la misma config, rearranque
rápido, y loop de reinicio.

### 4.6. Readiness: qué significa "el gateway está listo"

`src/gateway/server/readiness.ts` [VERIFICADO EN CÓDIGO — transcripción del contrato y la lógica de
decisión]:

```ts
/** Snapshot returned by the gateway readiness probe. */
type ReadinessResult = {
  ready: boolean;
  failing: string[];
  suppressed?: string[];
  uptimeMs: number;
  eventLoop?: GatewayEventLoopHealth;
};

export type ReadinessChecker = () => ReadinessResult;

const DEFAULT_READINESS_CACHE_TTL_MS = 1_000;

export function createReadinessChecker(deps: {
  channelManager: ChannelManager;
  startedAt: number;
  getStartupPending?: () => boolean;
  getStartupPendingReason?: () => string | undefined;
  getGatewayDraining?: () => boolean;
  getEventLoopHealth?: () => GatewayEventLoopHealth | undefined;
  shouldSkipChannelReadiness?: () => boolean;
  cacheTtlMs?: number;
}): ReadinessChecker {
  // ... orden de decisión:
  //  1. startup pendiente        -> not ready, failing: [reason]
  //  2. gateway drenando         -> not ready, failing: ["gateway-draining"]
  //  3. readiness de canal skip  -> ready
  //  4. cache < 1s               -> resultado cacheado
  //  5. evaluar salud de cada cuenta de cada canal
}
```

Y la regla más interesante — **cuándo un canal enfermo NO cuenta como fallo**
[VERIFICADO EN CÓDIGO, comentario original incluido]:

```ts
function shouldIgnoreReadinessFailure(
  accountSnapshot: ChannelAccountSnapshot,
  health: ChannelHealthEvaluation,
  autostartSuppressed: boolean,
): boolean {
  if (health.reason === "unmanaged" || health.reason === "stale-socket") {
    return true;
  }
  if (autostartSuppressed && health.reason === "not-running") {
    return true;
  }
  // Channel restarts spend time in backoff with running=false before the next
  // lifecycle re-enters startup grace. Keep readiness green during that handoff
  // window, but still surface hard failures once restart attempts are exhausted.
  // A failed ingress start lands in the same backoff window, so it gets the same
  // grace: the next start re-proves ingress, and once the ladder stops setting
  // restartPending the account stays red instead of hiding dead inbound.
  const restartableReason =
    health.reason === "not-running" || health.reason === "ingress-unavailable";
  const inRestartHandoff =
    accountSnapshot.restartPending === true && accountSnapshot.running !== true;
  return restartableReason && inRestartHandoff;
}
```

**El readiness del gateway es la conjunción de la salud de todas las cuentas de todos los canales,
menos las que están en ventana de reintento.** El diseño clave: `restartPending === true &&
running !== true` = "está en handoff de reinicio, no lo cuentes como caído todavía". Cuando la
escalera de reintentos se agota y deja de poner `restartPending`, la cuenta **se queda en rojo** en
vez de esconder un inbound muerto. Fail-visible, no fail-silent.

Estados posibles de readiness, en orden de precedencia:
`startup-sidecars` → `gateway-draining` → `<channelId>` fallando → `ready`.

### 4.7. Salud, versionado de estado y broadcast

`src/gateway/server/health-state.ts` [VERIFICADO EN CÓDIGO]:

```ts
let presenceVersion = 1;
let healthVersion = 1;
let healthCache: HealthSummary | null = null;
let broadcastHealthUpdate: ((snap: HealthSummary) => void) | null = null;

export function buildGatewaySnapshot(opts?: { includeSensitive?: boolean }): Snapshot {
  const cfg = getRuntimeConfig();
  const snapshot: Snapshot = {
    presence: listSystemPresence(),
    health: {},                     // el caller lo reemplaza con el snapshot recolectado
    stateVersion: { presence: presenceVersion, health: healthVersion },
    uptimeMs: Math.round(process.uptime() * 1000),
    appliedConfigHash: getRuntimeConfigAppliedHash(),
    sessionDefaults: {
      defaultAgentId: resolveDefaultAgentId(cfg),
      mainKey: normalizeMainKey(cfg.session?.mainKey),
      mainSessionKey: resolveMainSessionKey(cfg),
      scope: cfg.session?.scope ?? "per-sender",
    },
    updateAvailable: getUpdateAvailable() ?? undefined,
  };
  if (opts?.includeSensitive === true) {
    const auth = resolveGatewayAuth({ authConfig: cfg.gateway?.auth, env: process.env });
    // Surface resolved paths only to admin callers that already have broader gateway access.
    snapshot.configPath = createConfigIO().configPath;
    snapshot.stateDir = STATE_DIR;
    snapshot.authMode = auth.mode;
  }
  return snapshot;
}
```

⭐ **`stateVersion: { presence, health }`** — cada dominio de estado tiene su propio contador
monótono. Un cliente que reconecta compara sus versiones con las del `hello-ok` y sabe **qué
resincronizar**, sin volver a pedir todo. Esto es lo que hace que reconectar sea barato.

⭐ **`appliedConfigHash`** — el cliente puede detectar que la config cambió mientras estaba
desconectado.

⭐ **`includeSensitive` decide si se exponen rutas** (`configPath`, `stateDir`) y el modo de auth. El
mismo builder, dos audiencias.

El refresco de salud tiene un mecanismo de **generaciones** para evitar que un refresco lento
sobreescriba a uno más nuevo [VERIFICADO EN CÓDIGO, comentarios originales]:

```ts
type HealthAudience = "public" | "admin";
type HealthRefreshStrength = "passive" | "probe";

// Passive callers can reuse a stronger probe, but an explicit probe must not
// inherit a passive refresh that deliberately skipped live channel checks.
const existing =
  strength === "passive"
    ? (state.inFlight.probe ?? state.inFlight.passive)
    : state.inFlight.probe;
if (existing) {
  return existing.promise;
}
// ...
// Concurrent passive/probe refreshes can finish out of order. Only a
// generation newer than the published cache may advance version/broadcast.
if (!includeSensitive && generation > state.committedGeneration) {
  state.committedGeneration = generation;
  healthCache = snap;
  healthVersion += 1;
  if (broadcastHealthUpdate) {
    broadcastHealthUpdate(snap);
  }
}
```

Dos ideas: **coalescing de refrescos concurrentes** (un solo probe real sirve a N llamadores) y
**barrera de generación** (un resultado viejo que llega tarde no pisa uno nuevo). Ambos son problemas
que aparecen en cuanto hay más de un cliente pidiendo estado.

### 4.8. Presupuesto de conexiones pre-auth

`src/gateway/server/preauth-connection-budget.ts` (archivo completo) [VERIFICADO EN CÓDIGO]:

```ts
const DEFAULT_MAX_PREAUTH_CONNECTIONS_PER_IP = 32;
const UNKNOWN_CLIENT_IP_BUDGET_KEY = "__openclaw_unknown_client_ip__";

export type PreauthConnectionBudget = {
  acquire(clientIp: string | undefined): boolean;
  release(clientIp: string | undefined): void;
};

export function createPreauthConnectionBudget(
  limit = getMaxPreauthConnectionsPerIpFromEnv(),
): PreauthConnectionBudget {
  const maxConnectionsPerIp = resolveIntegerOption(limit, getMaxPreauthConnectionsPerIpFromEnv(), {
    min: 1,
  });
  const counts = new Map<string, number>();
  const normalizeBudgetKey = (clientIp: string | undefined) => {
    const ip = clientIp?.trim();
    // Trusted-proxy mode can intentionally leave client IP unresolved when
    // forwarded headers are missing or invalid; keep those upgrades capped
    // under a shared fallback bucket instead of failing open.
    return ip || UNKNOWN_CLIENT_IP_BUDGET_KEY;
  };

  return {
    acquire(clientIp) {
      const ip = normalizeBudgetKey(clientIp);
      const next = (counts.get(ip) ?? 0) + 1;
      if (next > maxConnectionsPerIp) {
        return false;
      }
      counts.set(ip, next);
      return true;
    },
    release(clientIp) {
      const ip = normalizeBudgetKey(clientIp);
      const current = counts.get(ip);
      if (current === undefined) { return; }
      if (current <= 1) { counts.delete(ip); return; }
      counts.set(ip, current - 1);
    },
  };
}
```

**Un socket abierto que todavía no se autenticó consume recursos.** 32 por IP, y las IPs
desconocidas comparten un balde en lugar de escapar del límite (`|| UNKNOWN_CLIENT_IP_BUDGET_KEY`).
Esa es la línea que convierte un límite decorativo en uno real.

Ventana de handshake pre-auth: **15 segundos** (`DEFAULT_PREAUTH_HANDSHAKE_TIMEOUT_MS = 15_000`,
`packages/gateway-client/src/timeouts.ts`). Y el watchdog del cliente **nunca puede dispararse antes
que el timeout del servidor** [comentario original]: *"The client watchdog must never fire before the
server-side preauth timeout."*

Otros timeouts del cliente [VERIFICADO EN CÓDIGO]:
```ts
export const MAX_SAFE_TIMEOUT_DELAY_MS = 2_147_483_647;
export const DEFAULT_PREAUTH_HANDSHAKE_TIMEOUT_MS = 15_000;
export const DEFAULT_GATEWAY_REQUEST_TIMEOUT_MS = 30_000;
export const MIN_CONNECT_CHALLENGE_TIMEOUT_MS = 250;
export const MAX_CONNECT_CHALLENGE_TIMEOUT_MS = DEFAULT_PREAUTH_HANDSHAKE_TIMEOUT_MS;
```

### 4.9. Apagado ordenado: la secuencia completa

`src/gateway/server-close.ts` (1087 líneas) construye el handler de cierre. La secuencia
[VERIFICADO EN CÓDIGO — orden real de las llamadas]:

```
 1. clearSessionSuspensionTimers()        // ANTES del primer await
 2. configReloader.stop()
 3. hook  gateway:shutdown                (timeout: GATEWAY_SHUTDOWN_HOOK_TIMEOUT_MS)
 4. hook  gateway:pre-restart             (solo si restartExpectedMs !== null)
 5. drainRestartPendingRepliesForShutdown (solo si restart + hay respuestas pendientes)
 6. drainActiveSessionsForShutdown        (timeout: ACTIVE_SESSIONS_SHUTDOWN_DRAIN_TIMEOUT_MS)
 7. bonjourStop / tailscaleCleanup
 8. post-ready sidecars (uno por uno, en orden)
 9. plugin services       (con "shutdown grace" — un plugin colgado no bloquea el resto)
10. agent harnesses
11. bundle runtimes: MCP + LSP en paralelo, cada uno con grace
12. plugin state store, gmail watcher
13. cron.stopAndDrain() ?? cron.stop()
14. heartbeat runner, task registry maintenance, update check
15. clear de todos los timers de presencia de nodos
16. broadcast("shutdown", { reason, restartExpectedMs })   <-- AVISO A LOS CLIENTES
17. clearInterval de tick / health / dedupe / media / worktree
18. unsubs: agent, heartbeat, transcript, lifecycle, task
19. chatRunState.clear()
20. socket.close(1012, "service restart" | "gateway-shutdown")  por cada cliente
```

Fragmentos literales de los puntos clave:

```ts
// Fence lane auto-resume timers before the first awaited shutdown step;
// later teardown can stall long enough for a TTL callback to mutate queues.
clearSessionSuspensionTimers();
```

```ts
params.broadcast("shutdown", {
  reason,
  restartExpectedMs,
});
```

```ts
let clientCloseFailures = 0;
for (const c of params.clients) {
  try {
    c.socket.close(
      1012,
      c.connectionKind === "worker" ? "gateway-shutdown" : "service restart",
    );
  } catch {
    clientCloseFailures++;
  }
}
if (clientCloseFailures > 0) {
  shutdownLog.warn(`failed to close ${clientCloseFailures} WebSocket client(s)`);
}
```

**Cuatro cosas para robar:**

1. **Se apagan los timers ANTES del primer `await`.** El comentario lo explica: durante el teardown
   (que puede tardar segundos) un callback de TTL podría mutar colas que ya se están drenando. Este es
   un bug real que casi nadie previene.
2. **Todo paso de apagado tiene timeout y produce un `warning`, nunca bloquea.** `shutdownStep(name,
   fn, warnings)` y `disposeRuntimeWithShutdownGrace({ label, dispose, graceMs, warnings })`. Comentario
   original: *"A stalled plugin must not prevent later runtime and child-process cleanup."* El apagado
   **siempre termina**, degradado si hace falta.
3. **Se avisa por el protocolo (`broadcast("shutdown", ...)`) ANTES de cerrar el socket.** Y el evento
   lleva `restartExpectedMs`, así que el cliente sabe si esperar y reconectar o rendirse. Ver
   `ShutdownEventSchema` en la sección 2.6.
4. **Close code 1012** (WebSocket "Service Restart", estándar RFC 6455), con razón distinta para
   workers (`"gateway-shutdown"`) y clientes normales (`"service restart"`).

`GatewayCloseOptions.restartExpectedMs` es lo que distingue **apagado** de **reinicio**: si es `null`
no se corre el hook `gateway:pre-restart` ni el drenaje de respuestas pendientes; se apaga y ya.

### 4.10. Múltiples clientes y broadcast

El estado del servidor mantiene `clients: Set<GatewayWsClient>` (`src/gateway/server-close.ts:154`) y
`broadcast(eventName, payload)` los alcanza a todos. Las suscripciones por conexión viven en
`src/gateway/server-node-subscriptions.ts` y `server-runtime-subscriptions.ts`.

**Múltiples clientes simultáneos son de primera clase**, no un accidente: hay `connectionKind:
"gateway" | "worker"`, presencia de nodos con timers propios por nodo (`nodePresenceTimers`), y
suscripciones a sesiones por nodo (`server-node-session-runtime.ts`). El daemon es genuinamente
multi-cliente: CLI, Control UI del navegador, apps móviles y nodos remotos hablan al mismo proceso.

### 4.11. Qué pasa cuando el daemon muere — lado cliente

`packages/gateway-client/src/protocol-client.ts` [VERIFICADO EN CÓDIGO]:

```ts
private flushRequests(error: Error): void {
  for (const [id, pending] of this.pending) {
    this.finishRequestTiming(id, pending, false, "CLIENT_CLOSED");
    pending.cleanup?.();
    pending.reject(error);
  }
  this.pending.clear();
}
```

y en el manejo del cierre:

```ts
const decision = this.opts.resolveClose(context);
this.flushRequests(
  decision.pendingError ??
    context.connectFailure?.error ??
    new Error(`gateway closed (${code}): ${reason}`),
);
this.invoke("close", () => this.opts.onClose?.(context, decision));
if (decision.retry && !this.stopped) {
  this.scheduleReconnect(decision.reconnectDelayMs ?? context.connectFailure?.reconnectDelayMs);
}
```

⚠️ **Conclusión dura, y es la respuesta a "qué pasa con los mensajes en vuelo":**
**TODA petición en vuelo se rechaza con `CLIENT_CLOSED`. No hay reintento automático de requests.**
El cliente reconecta el socket, pero **las peticiones que estaban esperando respuesta se pierden como
peticiones** — quien llamó recibe un error, y decide.

La política de reconexión (`packages/gateway-client/src/reconnect-policy.ts`, archivo completo)
[VERIFICADO EN CÓDIGO]:

```ts
const NON_RECOVERABLE_AUTH_ERRORS = new Set<string>([
  ConnectErrorDetailCodes.AUTH_TOKEN_MISSING,
  ConnectErrorDetailCodes.AUTH_BOOTSTRAP_TOKEN_INVALID,
  ConnectErrorDetailCodes.AUTH_PASSWORD_MISSING,
  ConnectErrorDetailCodes.AUTH_PASSWORD_MISMATCH,
  ConnectErrorDetailCodes.AUTH_RATE_LIMITED,
  ConnectErrorDetailCodes.AUTH_DEVICE_TOKEN_MISMATCH,
  ConnectErrorDetailCodes.AUTH_SCOPE_MISMATCH,
  ConnectErrorDetailCodes.PAIRING_REQUIRED,
  ConnectErrorDetailCodes.CONTROL_UI_DEVICE_IDENTITY_REQUIRED,
  ConnectErrorDetailCodes.DEVICE_IDENTITY_REQUIRED,
]);

export function shouldPauseGatewayReconnect(params: {
  details?: unknown;
  deviceTokenRetryPending?: boolean;
  tokenMismatchIsTerminal?: boolean;
  protocolMismatchIsTerminal?: boolean;
  clientVersionMismatchIsTerminal?: boolean;
}): boolean {
  const code = readConnectErrorDetailCode(params.details);
  if (!code) {
    return false;
  }
  const pairing = readPairingConnectErrorDetails(params.details);
  if (
    code === ConnectErrorDetailCodes.PAIRING_REQUIRED &&
    (pairing?.pauseReconnect === false || pairing?.recommendedNextStep === "wait_then_retry")
  ) {
    return false;
  }
  if (code === ConnectErrorDetailCodes.AUTH_TOKEN_MISMATCH) {
    return params.tokenMismatchIsTerminal === true && !params.deviceTokenRetryPending;
  }
  return (
    NON_RECOVERABLE_AUTH_ERRORS.has(code) ||
    (params.protocolMismatchIsTerminal === true &&
      code === ConnectErrorDetailCodes.PROTOCOL_MISMATCH) ||
    (params.clientVersionMismatchIsTerminal === true &&
      code === ConnectErrorDetailCodes.CLIENT_VERSION_MISMATCH)
  );
}
```

⭐ **La regla es: reconectar SIEMPRE, salvo que el error diga que reconectar no va a servir.**
Sin código de error → reconecta (el daemon se cayó, va a volver). Con `AUTH_PASSWORD_MISMATCH` →
pausa (martillar el servidor no arregla una contraseña mala). Y el servidor puede **anular la pausa**
desde su respuesta: `pairing.pauseReconnect === false` o
`recommendedNextStep === "wait_then_retry"` fuerzan el reintento. **El servidor le dice al cliente
cómo comportarse en el reintento.** Ese es el patrón que vale la pena, no la lista de códigos.

### 4.12. Qué SÍ sobrevive a la muerte del daemon: la cola durable

Acá está la pieza que compensa el "todo en vuelo se pierde" de la sección anterior.
`src/infra/session-delivery-queue-storage.ts` [VERIFICADO EN CÓDIGO]:

```ts
// Session delivery queue persists session-scoped messages until channel
// delivery acknowledges them or recovery exhausts retry policy.
const QUEUE_NAME = "session";

type SessionDeliveryRetryPolicy = {
  maxRetries?: number;
  /** Retain terminal ownership when the durable producer can replay forever. */
  completionRetention?: DeliveryQueueCompletionRetention;
};

export type SessionDeliveryRoute = {
  channel: string;
  to: string;
  accountId?: string;
  replyToId?: string;
  threadId?: string;
  chatType: ChatType;
};

export type SessionDeliverySettledOutcome = "recovered" | "moved-to-failed";

/** Payload variants that can be replayed by session delivery recovery. */
export type QueuedSessionDeliveryPayload =
  | ({
      kind: "systemEvent";
      sessionKey: string;
      text: string;
      deliveryContext?: SessionDeliveryContext;
      idempotencyKey?: string;
    } & SessionDeliveryRetryPolicy)
  | ({
      kind: "agentTurn";
      sessionKey: string;
      message: string;
      messageId: string;
      expectedSessionId?: string;
      route?: SessionDeliveryRoute;
      deliveryContext?: SessionDeliveryContext;
      inputProvenance?: InputProvenance;
      sourceReplyDeliveryMode?: SourceReplyDeliveryMode;
      expectedMediaUrls?: string[];
      suppressTextDelivery?: true;
      idempotencyKey?: string;
    } & SessionDeliveryRetryPolicy);

export type QueuedSessionDelivery = QueuedSessionDeliveryPayload & {
  id: string;
  enqueuedAt: number;
  agentRunAttempt?: number;
  lastChargedAgentRunAttempt?: number;
  retryCount: number;
  lastAttemptAt?: number;
  lastError?: string;
  deliveryStartedAt?: number;
  acknowledgedAt?: number;
  settlementOutcome?: SessionDeliverySettledOutcome;
  availableAt?: number;
};

export class SessionDeliveryDeferredError extends Error { override name = "SessionDeliveryDeferredError"; }
/** Signals that retry budget was already persisted before a later transition failed. */
export class SessionDeliveryRetryChargedError extends Error { override name = "SessionDeliveryRetryChargedError"; }
/** Signals that durable pre-delivery ownership could not be established. */
export class SessionDeliveryAttemptStartError extends Error { override name = "SessionDeliveryAttemptStartError"; }
/** Signals that delivery proved no external or transcript side effect committed. */
export class SessionDeliverySafeRetryError extends Error { override name = "SessionDeliverySafeRetryError"; }
/** Signals that recovery must settle this pending row as failed without replaying delivery. */
export class SessionDeliveryDeadLetteredError extends Error { override name = "SessionDeliveryDeadLetteredError"; }

function buildEntryId(idempotencyKey?: string): string {
  if (!idempotencyKey) {
    return generateSecureUuid();
  }
  return sha256Hex(idempotencyKey);
}
```

⭐⭐ **El id de la entrada ES el hash de la clave de idempotencia.** Encolar dos veces el mismo mensaje
lógico produce el mismo id y el `upsert` colapsa el duplicado. **La deduplicación no es una tabla
aparte ni un check previo: está en la elección del primary key.** Es el truco más copiable de todo el
documento.

⭐ **Las cinco clases de error son la máquina de estados de la cola.** No es "falló / no falló":
- `Deferred` — todavía no toca, reintentar después.
- `RetryCharged` — ya se gastó un intento antes de que fallara una transición posterior. Evita
  cobrar dos veces el mismo reintento.
- `AttemptStartError` — no se pudo tomar la propiedad durable de la fila. Otro proceso la tiene.
- `SafeRetryError` — ⭐ **se probó que no hubo efecto externo ni en el transcript**; es seguro
  reintentar sin duplicar. La distinción entre "falló" y "falló *sin efectos*" es lo que permite
  reintentar sin miedo.
- `DeadLettered` — no reintentar; marcar la fila como fallida y seguir.

El API completo, del facade `src/infra/session-delivery-queue.ts` [VERIFICADO EN CÓDIGO]:

```ts
export {
  advanceSessionDeliveryAgentRun,
  deferSessionDelivery,
  enqueueClaimedSessionDelivery,
  enqueueSessionDelivery,
  failSessionDelivery,
  loadPendingSessionDeliveries,
  loadPendingSessionDelivery,
  markSessionDeliveryAttemptStarted,
  markSessionDeliverySettlement,
  releaseSessionDeliveryClaim,
  // ...errores
} from "./session-delivery-queue-storage.js";
export {
  drainPendingSessionDeliveries,
  recoverPendingSessionDeliveries,
} from "./session-delivery-queue-recovery.js";
```

El ciclo es **claim → attempt-started → settle**, con `releaseSessionDeliveryClaim` para soltar la
propiedad si el proceso muere. El backend es SQLite (`./delivery-queue-sqlite.js`).

Y el mecanismo que corre esto al arrancar: `src/gateway/server-restart-sentinel.ts` — *"Gateway
restart sentinel recovery. Resumes pending restart continuations and outbound delivery after process
restart."* Constantes relevantes [VERIFICADO EN CÓDIGO]:

```ts
const RESTART_CONTINUATION_BUSY_RETRY_DELAY_MS = process.env.VITEST ? 1 : 6_000;
const RESTART_CONTINUATION_BUSY_MAX_ATTEMPTS = 20;
const CONTROL_PLANE_UPDATE_PENDING_RETRY_DELAY_MS = process.env.VITEST ? 1 : 2_000;
const CONTROL_PLANE_UPDATE_PENDING_MAX_ATTEMPTS = 900;
```

**Resumen de la garantía real de entrega**, que es lo que el usuario preguntó explícitamente:

| Cosa | ¿Sobrevive a la muerte del daemon? |
|---|---|
| Requests RPC en vuelo (`req`/`res`) | ❌ No. Se rechazan con `CLIENT_CLOSED`. Sin reintento. |
| Suscripciones a eventos | ❌ No. Se rearman al reconectar (con `stateVersion` para resincronizar). |
| Eventos emitidos durante la caída | ❌ No. No hay buffer ni replay de eventos. |
| Respuestas del agente pendientes de entregar a un canal | ✅ **Sí**, vía `session-delivery-queue` (SQLite, idempotente, con dead-letter). |
| Continuaciones de un turno interrumpido por reinicio | ✅ **Sí**, vía restart sentinel, con 20 reintentos cada 6s. |
| Sesiones y transcripts | ✅ Sí, están en el store en disco. |

⭐ **La lección arquitectónica: el protocolo WebSocket es best-effort y la durabilidad vive en otra
capa.** No intentaron hacer confiable el transporte; pusieron una cola SQLite idempotente exactamente
en el punto donde la pérdida sería visible para el usuario final (la respuesta que nunca llegó al
canal). Todo lo demás se deja caer a propósito.

### 4.13. Hallazgo lateral: `BOOT.md` por workspace

`src/gateway/boot.ts` [VERIFICADO EN CÓDIGO] — no es el boot del servidor, es un mecanismo distinto y
vale la pena registrarlo: al arrancar el gateway corre, **por workspace**, un archivo `BOOT.md` como
prompt en una sesión aislada.

```ts
function resolveBootSessionKey(sessionKey: string): string {
  const agentId = resolveAgentIdFromSessionKey(sessionKey);
  return `agent:${agentId}:boot`;
}

function buildBootPrompt(content: string) {
  const safeContent = escapeInternalRuntimeContextDelimiters(content);
  return [
    "You are running a boot check. Follow BOOT.md instructions exactly.",
    "",
    INTERNAL_RUNTIME_CONTEXT_BEGIN,
    OPENCLAW_RUNTIME_CONTEXT_NOTICE,
    "",
    "BOOT.md:",
    safeContent,
    INTERNAL_RUNTIME_CONTEXT_END,
    "",
    "If BOOT.md asks you to send a message, use the message tool (action=send with channel + target).",
    "Use the `target` field (not `to`) for message tool destinations.",
    `After sending with the message tool, reply with ONLY: ${SILENT_REPLY_TOKEN}.`,
    `If nothing needs attention, reply with ONLY: ${SILENT_REPLY_TOKEN}.`,
  ].join("\n");
}

type BootRunResult =
  | { status: "skipped"; reason: "missing" | "empty" }
  | { status: "ran" }
  | { status: "failed"; reason: string };
```

Detalles de robustez: sesión de boot desechable (`agent:<id>:boot` con id
`boot-<timestamp>-<uuid8>`), `deliver: false` y `suppressPromptPersistence: true` (no ensucia el
historial), el mapeo de sesión se **preserva y se restaura** alrededor de la corrida
(`preserveTemporarySessionMapping`), límite de 16 MB al archivo, `fs.realpath` para permitir symlink,
y un "echo guard" para que el modelo no repita el contenido de `BOOT.md` al usuario. Si el archivo no
existe se salta silenciosamente.

Es un patrón de "ritual de arranque declarativo" barato y directamente traducible a O.R.I.O.N. (que
ya tiene `core/proactive_engine.py` y `learning/routines_engine.py`).

---

## 5. Ruteo multi-agente

Esta es, con diferencia, **la zona más limpia y más copiable de todo el repo**. A diferencia del
gateway (850 archivos) y del contrato de canal (31 adapters), el ruteo entero vive en
`src/routing/` — **11 archivos, ~1.900 líneas**, y el motor central es una sola función.

```
src/routing/
  account-id.ts                 (78)   normalización de accountId
  account-lookup.ts             (51)
  binding-scope.ts             (130)   normalización y matching de scopes
  bindings.ts                   (87)   listado/agregación de bindings
  bound-account-read.ts        (143)
  channel-route-targets.ts     (100)
  conversation-ref.ts           (37)
  default-account-warnings.ts   (21)
  peer-kind-match.ts            (14)
  resolve-route.ts             (819)   ⭐ el motor
  session-key.ts               (351)   ⭐ construcción de claves de sesión
```

`src/bindings/` existe pero solo tiene `records.ts` — **hallazgo negativo**: el `cfg.bindings` que la
tarea mencionaba no vive en `src/bindings/`, vive en `src/config/types.agents.ts` (el tipo) y se lee
desde `src/routing/bindings.ts` vía `listRouteBindings(cfg)` de `src/config/bindings.ts`.

### 5.1. La configuración de bindings, transcrita

`src/config/types.agents.ts` [VERIFICADO EN CÓDIGO — transcripción literal]:

```ts
export type AgentBindingMatch = {
  channel: string;
  /**
   * Channel account to match.
   * - Omitted/empty: matches only the channel default account.
   * - "*": matches every account on the channel.
   * - Any other string: matches that specific account id.
   */
  accountId?: string;
  peer?: { kind: ChatType; id: string };
  guildId?: string;
  teamId?: string;
  /** Discord role IDs used for role-based routing. */
  roles?: string[];
};

export type AgentRouteBinding = {
  /** Missing type is interpreted as route for backward compatibility. */
  type?: "route";
  agentId: string;
  comment?: string;
  match: AgentBindingMatch;
  session?: {
    /** Optional session scoping override for conversations matched by this binding. */
    dmScope?: DmScope;
  };
};

export type AgentAcpBinding = {
  type: "acp";
  agentId: string;
  comment?: string;
  match: AgentBindingMatch;
  acp?: {
    mode?: "persistent" | "oneshot";
    label?: string;
    cwd?: string;
    backend?: string;
  };
};

export type AgentBinding = AgentRouteBinding | AgentAcpBinding;
```

**Eso es todo el modelo de configuración de ruteo.** Un array de reglas `{ agentId, match }`. En JSON
se ve así (forma reconstruida a partir del tipo):

```jsonc
{
  "bindings": [
    {
      "agentId": "soporte",
      "comment": "El grupo de soporte va al agente de soporte",
      "match": { "channel": "telegram", "peer": { "kind": "group", "id": "-100123456" } }
    },
    {
      "agentId": "dev",
      "match": { "channel": "discord", "guildId": "987654", "roles": ["rol-devs"] }
    },
    {
      "agentId": "personal",
      "match": { "channel": "telegram", "accountId": "*", "peer": { "kind": "direct", "id": "*" } },
      "session": { "dmScope": "per-peer" }
    }
  ]
}
```

Tres detalles del modelo que valen:

- **`accountId` tiene tres semánticas distintas por valor**: ausente = solo la cuenta por defecto;
  `"*"` = todas; cualquier otra cosa = esa cuenta. Documentado en el propio tipo.
- **`peer.id` admite `"*"`** = "cualquier peer de este `kind`". Es un tier de precedencia propio
  (`binding.peer.wildcard`), inferior al peer exacto.
- **`session.dmScope`** deja que un binding **cambie cómo se aíslan las sesiones** solo para las
  conversaciones que él matchea. La política de aislamiento es por regla, no global.

### 5.2. El resultado de resolver una ruta

`src/routing/resolve-route.ts` [VERIFICADO EN CÓDIGO — transcripción literal]:

```ts
export type RoutePeer = {
  kind: ChatType;
  id: string;
};

export type ResolveAgentRouteInput = {
  cfg: OpenClawConfig;
  channel: string;
  accountId?: string | null;
  peer?: RoutePeer | null;
  dmScope?: "main" | "per-peer" | "per-channel-peer" | "per-account-channel-peer";
  /** Parent peer for threads — used for binding inheritance when peer doesn't match directly. */
  parentPeer?: RoutePeer | null;
  guildId?: string | null;
  teamId?: string | null;
  /** Discord member role IDs — used for role-based agent routing. */
  memberRoleIds?: string[];
};

export type ResolvedAgentRoute = {
  agentId: string;
  channel: string;
  accountId: string;
  /** Effective direct-message scope after a matching binding override. */
  dmScope?: "main" | "per-peer" | "per-channel-peer" | "per-account-channel-peer";
  /** Internal session key used for persistence + concurrency. */
  sessionKey: string;
  /** Convenience alias for direct-chat collapse. */
  mainSessionKey: string;
  /** Which session should receive inbound last-route updates. */
  lastRoutePolicy: "main" | "session";
  /** Match description for debugging/logging. */
  matchedBy:
    | "binding.peer"
    | "binding.peer.parent"
    | "binding.peer.wildcard"
    | "binding.guild+roles"
    | "binding.guild"
    | "binding.team"
    | "binding.account"
    | "binding.channel"
    | "default";
};
```

⭐⭐ **`matchedBy` es la mejor idea de esta zona entera.** La resolución de rutas devuelve
**por qué** eligió lo que eligió, como un valor de dominio (no un log). Con 8 tiers de precedencia,
"¿por qué este mensaje fue al agente equivocado?" es una pregunta que se responde mirando un campo,
no leyendo el código. **Esto es gratis de implementar y ahorra horas de depuración.**

Y `lastRoutePolicy` resuelve un problema sutil:

```ts
export function deriveLastRoutePolicy(params: {
  sessionKey: string;
  mainSessionKey: string;
}): ResolvedAgentRoute["lastRoutePolicy"] {
  return params.sessionKey === params.mainSessionKey ? "main" : "session";
}

export function resolveInboundLastRouteSessionKey(params: {
  route: Pick<ResolvedAgentRoute, "lastRoutePolicy" | "mainSessionKey">;
  sessionKey: string;
}): string {
  return params.route.lastRoutePolicy === "main" ? params.route.mainSessionKey : params.sessionKey;
}
```

Es decir: cuando la sesión colapsa a la principal, el "última ruta usada" (para saber a dónde
responder proactivamente) se guarda en la principal; si no, en la sesión específica.

### 5.3. Los 8 tiers de precedencia, transcritos

El corazón de `resolveAgentRoute()` [VERIFICADO EN CÓDIGO — transcripción literal de la tabla de
tiers]:

```ts
const tiers: Array<{
  matchedBy: Exclude<ResolvedAgentRoute["matchedBy"], "default">;
  enabled: boolean;
  scopePeer: RoutePeer | null;
  candidates: EvaluatedBinding[];
  predicate: (candidate: EvaluatedBinding) => boolean;
}> = [
  {
    matchedBy: "binding.peer",
    enabled: Boolean(peer),
    scopePeer: peer,
    candidates: collectPeerIndexedBindings(bindingsIndex, peer),
    predicate: (candidate) => candidate.match.peer.state === "valid",
  },
  {
    matchedBy: "binding.peer.parent",
    enabled: Boolean(parentPeer && parentPeer.id),
    scopePeer: parentPeer && parentPeer.id ? parentPeer : null,
    candidates: collectPeerIndexedBindings(bindingsIndex, parentPeer),
    predicate: (candidate) => candidate.match.peer.state === "valid",
  },
  {
    matchedBy: "binding.peer.wildcard",
    enabled: Boolean(peer),
    scopePeer: peer,
    candidates: bindingsIndex.byPeerWildcard,
    predicate: (candidate) => candidate.match.peer.state === "wildcard-kind",
  },
  {
    matchedBy: "binding.guild+roles",
    enabled: Boolean(guildId && memberRoleIds.length > 0),
    scopePeer: peer,
    candidates: guildId ? (bindingsIndex.byGuildWithRoles.get(guildId) ?? []) : [],
    predicate: (candidate) =>
      hasGuildConstraint(candidate.match) && hasRolesConstraint(candidate.match),
  },
  {
    matchedBy: "binding.guild",
    enabled: Boolean(guildId),
    scopePeer: peer,
    candidates: guildId ? (bindingsIndex.byGuild.get(guildId) ?? []) : [],
    predicate: (candidate) =>
      hasGuildConstraint(candidate.match) && !hasRolesConstraint(candidate.match),
  },
  {
    matchedBy: "binding.team",
    enabled: Boolean(teamId),
    scopePeer: peer,
    candidates: teamId ? (bindingsIndex.byTeam.get(teamId) ?? []) : [],
    predicate: (candidate) => hasTeamConstraint(candidate.match),
  },
  {
    matchedBy: "binding.account",
    enabled: true,
    scopePeer: peer,
    candidates: bindingsIndex.byAccount,
    predicate: (candidate) => candidate.match.accountPattern !== "*",
  },
  {
    matchedBy: "binding.channel",
    enabled: true,
    scopePeer: peer,
    candidates: bindingsIndex.byChannel,
    predicate: (candidate) => candidate.match.accountPattern === "*",
  },
];

for (const tier of tiers) {
  if (!tier.enabled) {
    continue;
  }
  const matched = tier.candidates.find(
    (candidate) =>
      tier.predicate(candidate) &&
      matchesBindingScope(candidate.match, {
        ...baseScope,
        peer: tier.scopePeer,
      }),
  );
  if (matched) {
    if (shouldLogDebug) {
      logDebug(`[routing] match: matchedBy=${tier.matchedBy} agentId=${matched.binding.agentId}`);
    }
    return choose(matched.binding.agentId, tier.matchedBy, matched.binding.session);
  }
}

return choose(resolveDefaultAgentId(input.cfg), "default");
```

⭐⭐ **La precedencia es una LISTA DE DATOS, no una cadena de `if/else`.** Cada tier es un objeto con
`{ nombre, habilitado, candidatos, predicado }`, y el motor es un `for` de 15 líneas. Agregar un tier
nuevo es agregar un elemento al array. Esta es una técnica directamente aplicable a cualquier sistema
de reglas con precedencia, en cualquier lenguaje.

**El orden de precedencia, de más específico a más general:**

| # | Tier | Cuándo aplica | Qué matchea |
|---|------|---------------|-------------|
| 1 | `binding.peer` | hay peer | conversación exacta (`peer.kind` + `peer.id`) |
| 2 | `binding.peer.parent` | hay parentPeer | ⭐ el hilo hereda el binding del canal padre |
| 3 | `binding.peer.wildcard` | hay peer | `peer.id === "*"` — cualquier peer de ese kind |
| 4 | `binding.guild+roles` | guildId + roles del miembro | servidor Discord + rol |
| 5 | `binding.guild` | hay guildId | servidor Discord entero |
| 6 | `binding.team` | hay teamId | workspace de Slack/Teams |
| 7 | `binding.account` | siempre | cuenta concreta del canal |
| 8 | `binding.channel` | siempre | `accountId === "*"` — el canal entero |
| — | `default` | fallback | `resolveDefaultAgentId(cfg)` |

⭐ **El tier 2 (`binding.peer.parent`) es la joya escondida.** Comentario original:
*"Thread parent inheritance: if peer (thread) didn't match, check parent peer binding."* Un hilo nuevo
dentro de un canal ya ruteado hereda el agente del canal padre, **sin tener que crear un binding por
hilo**. Sin esto, cada hilo nuevo caería al agente por defecto y el usuario tendría que configurarlo
a mano. Es un caso que se descubre en producción, no en la pizarra.

**Dentro de un tier, gana el primero en orden de la config** (`order` incremental asignado al
construir el índice), no el más específico. La especificidad la da el tier; el orden en el array
desempata.

### 5.4. Matching de scope y normalización

`src/routing/binding-scope.ts` [VERIFICADO EN CÓDIGO — transcripción literal]:

```ts
export function routeBindingScopeMatches(
  constraint: RouteBindingScopeConstraint,
  scope: RouteBindingScope,
): boolean {
  const guildId = normalizeRouteBindingId(scope.guildId);
  const teamId = normalizeRouteBindingId(scope.teamId);
  const groupSpace = normalizeRouteBindingId(scope.groupSpace);
  if (!scopeIdMatches({ constraint: constraint.guildId, exact: guildId, groupSpace })) {
    return false;
  }
  if (!scopeIdMatches({ constraint: constraint.teamId, exact: teamId, groupSpace })) {
    return false;
  }

  const roles = normalizeRouteBindingRoles(constraint.roles);
  if (!roles) {
    return true;
  }
  return hasAnyRouteBindingRole(roles, scope.memberRoleIds);
}

function scopeIdMatches(params: {
  constraint: string | null | undefined;
  exact: string;
  groupSpace: string;
}): boolean {
  if (!params.constraint) {
    return true;      // ⭐ restricción ausente = matchea todo
  }
  return params.constraint === params.exact || params.constraint === params.groupSpace;
}
```

⭐ **`if (!constraint) return true`** — una restricción ausente **no restringe**. Es la semántica
correcta y la que la gente implementa mal la mitad de las veces (haciendo que ausente = no matchea).

Y el matching de peer, que tolera la ambigüedad group/channel entre plataformas
[VERIFICADO EN CÓDIGO]:

```ts
function peerLookupKeys(kind: ChatType, id: string): string[] {
  if (kind === "group") {
    return [`group:${id}`, `channel:${id}`];
  }
  if (kind === "channel") {
    return [`channel:${id}`, `group:${id}`];
  }
  return [`${kind}:${id}`];
}
```

Un binding escrito como `group:X` también matchea un peer entrante `channel:X` y viceversa: Discord
dice "channel", Telegram dice "group", y el usuario no debería tener que saberlo.

El estado del peer en el binding es un **tri-estado explícito**, no un opcional
[VERIFICADO EN CÓDIGO]:

```ts
type NormalizedPeerConstraint =
  | { state: "none" }
  | { state: "invalid" }
  | { state: "wildcard-kind"; kind: ChatType }
  | { state: "valid"; kind: ChatType; id: string };
```

Y `matchesBindingScope` empieza con `if (match.peer.state === "invalid") return false;` — **un
binding mal escrito no matchea nada**, en vez de degradar silenciosamente a "matchea todo". Fail-closed.

### 5.5. Claves de sesión: el mecanismo de aislamiento

`src/routing/session-key.ts` [VERIFICADO EN CÓDIGO — transcripción literal de los constructores]:

```ts
export const LEGACY_IMPLICIT_AGENT_ID = "main";
export const DEFAULT_MAIN_KEY = "main";

export function buildAgentMainSessionKey(params: {
  agentId: string;
  mainKey?: string | undefined;
}): string {
  const agentId = normalizeAgentId(params.agentId);
  const mainKey = normalizeMainKey(params.mainKey);
  return `agent:${agentId}:${mainKey}`;
}

export function buildAgentPeerSessionKey(params: {
  agentId: string;
  mainKey?: string | undefined;
  channel: string;
  accountId?: string | null;
  peerKind?: ChatType | null;
  peerId?: string | null;
  identityLinks?: Record<string, string[]>;
  /** DM session scope. */
  dmScope?: "main" | "per-peer" | "per-channel-peer" | "per-account-channel-peer";
}): string {
  const peerKind = params.peerKind ?? "direct";
  if (peerKind === "direct") {
    const dmScope = params.dmScope ?? "main";
    let peerId = (params.peerId ?? "").trim();
    const linkedPeerId =
      dmScope === "main"
        ? null
        : resolveLinkedPeerId({
            identityLinks: params.identityLinks,
            channel: params.channel,
            peerId,
          });
    if (linkedPeerId) {
      peerId = linkedPeerId;
    }
    peerId = normalizeLowercaseStringOrEmpty(peerId);
    if (dmScope === "per-account-channel-peer" && peerId) {
      const channel = normalizeLowercaseStringOrEmpty(params.channel) || "unknown";
      const accountId = normalizeAccountId(params.accountId);
      return `agent:${normalizeAgentId(params.agentId)}:${channel}:${accountId}:direct:${peerId}`;
    }
    if (dmScope === "per-channel-peer" && peerId) {
      const channel = normalizeLowercaseStringOrEmpty(params.channel) || "unknown";
      return `agent:${normalizeAgentId(params.agentId)}:${channel}:direct:${peerId}`;
    }
    if (dmScope === "per-peer" && peerId) {
      return `agent:${normalizeAgentId(params.agentId)}:direct:${peerId}`;
    }
    return buildAgentMainSessionKey({
      agentId: params.agentId,
      mainKey: params.mainKey,
    });
  }
  const channel = normalizeLowercaseStringOrEmpty(params.channel) || "unknown";
  const peerId =
    normalizeSessionPeerId({
      channel: params.channel,
      peerKind,
      peerId: params.peerId,
    }) || "unknown";
  return `agent:${normalizeAgentId(params.agentId)}:${channel}:${peerKind}:${peerId}`;
}
```

**El namespacing de sesiones es una convención de string, y es toda la historia:**

```
agent:<agentId>:main                                    <- dmScope "main" (todo colapsa)
agent:<agentId>:direct:<peerId>                         <- dmScope "per-peer"
agent:<agentId>:<channel>:direct:<peerId>               <- dmScope "per-channel-peer"
agent:<agentId>:<channel>:<accountId>:direct:<peerId>   <- dmScope "per-account-channel-peer"
agent:<agentId>:<channel>:<peerKind>:<peerId>           <- grupos/canales (siempre aislados)
```

⭐ **`agentId` es SIEMPRE el primer segmento.** El aislamiento entre agentes es una propiedad
estructural de la clave: no hay forma de que un agente vea la sesión de otro por accidente, porque
toda operación de store se hace por prefijo de clave.

⭐ **Los 4 `dmScope` son 4 respuestas a "¿cuánto contexto comparte el usuario consigo mismo?"**:
- `main` — todo lo directo va a la misma conversación. Un solo hilo con el asistente.
- `per-peer` — una sesión por persona, sin importar por qué canal escriba.
- `per-channel-peer` — una sesión por (persona, canal).
- `per-account-channel-peer` — una por (persona, canal, cuenta del bot).

⭐ **`identityLinks: Record<string, string[]>`** — mapea "esta persona en Telegram y esta en Discord
son la misma". Cuando `dmScope !== "main"`, el peerId se reemplaza por el canónico antes de construir
la clave, así que **la misma persona en dos canales cae en la misma sesión**. Notar que se salta
deliberadamente en `dmScope === "main"` (ahí ya colapsa todo, no hace falta).

Y la clasificación de claves, con fail-closed [VERIFICADO EN CÓDIGO]:

```ts
type SessionKeyShape = "missing" | "agent" | "legacy_or_alias" | "malformed_agent";

export function classifySessionKeyShape(sessionKey: string | undefined | null): SessionKeyShape {
  const raw = (sessionKey ?? "").trim();
  if (!raw) {
    return "missing";
  }
  if (parseAgentSessionKey(raw)) {
    return "agent";
  }
  return normalizeLowercaseStringOrEmpty(raw).startsWith("agent:")
    ? "malformed_agent"
    : "legacy_or_alias";
}

export function resolveAgentIdFromSessionKey(
  sessionKey: string | undefined | null,
  configuredDefaultAgentId?: string,
): string {
  const parsed = parseAgentSessionKey(sessionKey);
  if (parsed?.agentId) {
    return normalizeAgentId(parsed.agentId);
  }
  if (classifySessionKeyShape(sessionKey) === "malformed_agent") {
    throw new Error("Malformed agent session key; refusing default-agent resolution.");
  }
  // ...
}
```

⭐ **Una clave que *parece* de agente pero está mal formada LANZA**, en vez de caer al agente por
defecto. Porque caer al default significaría **volcar la conversación de un agente en otro** — un
fallo de aislamiento silencioso. La distinción entre "no es una clave de agente" (aceptable, legacy) y
"pretende ser una clave de agente y está rota" (inaceptable) es exactamente el tipo de rigor que
separa un sistema multi-agente real de uno de juguete.

### 5.6. Aislamiento de workspace por agente

`src/agents/agent-scope-config.ts:263` [VERIFICADO EN CÓDIGO — función completa]:

```ts
export function resolveAgentWorkspaceDir(
  cfg: OpenClawConfig,
  agentId: string,
  env: NodeJS.ProcessEnv = process.env,
) {
  const id = normalizeAgentId(agentId);
  const configured = resolveAgentConfig(cfg, id)?.workspace?.trim();
  if (configured) {
    return stripNullBytes(resolveUserPath(configured, env));
  }
  const defaultAgentId = resolveDefaultAgentId(cfg);
  const fallback = cfg.agents?.defaults?.workspace?.trim();
  if (id === defaultAgentId) {
    if (fallback) {
      return stripNullBytes(resolveUserPath(fallback, env));
    }
    return stripNullBytes(resolveDefaultAgentWorkspaceDir(env));
  }
  if (fallback) {
    return stripNullBytes(path.join(resolveUserPath(fallback, env), id));
  }
  const stateDir = resolveStateDir(env);
  return stripNullBytes(path.join(stateDir, `workspace-${id}`));
}
```

Y el default [VERIFICADO EN CÓDIGO, archivo completo `src/agents/workspace-default.ts`]:

```ts
/** Resolve the default agent workspace directory from env/profile/home state. */
export function resolveDefaultAgentWorkspaceDir(
  env: NodeJS.ProcessEnv = process.env,
  homedir: () => string = os.homedir,
): string {
  const workspaceDir = env.OPENCLAW_WORKSPACE_DIR?.trim();
  if (workspaceDir) {
    return path.resolve(workspaceDir);
  }
  const home = resolveRequiredHomeDir(env, homedir);
  const profile = env.OPENCLAW_PROFILE?.trim();
  if (profile && normalizeOptionalLowercaseString(profile) !== "default") {
    return path.join(home, ".openclaw", `workspace-${profile}`);
  }
  return path.join(home, ".openclaw", "workspace");
}
```

**Precedencia del workspace de un agente:**
1. `agents.<id>.workspace` explícito.
2. Si es el agente por defecto: `agents.defaults.workspace`, si no `$OPENCLAW_WORKSPACE_DIR` /
   `~/.openclaw/workspace[-<profile>]`.
3. Si NO es el agente por defecto: `<agents.defaults.workspace>/<id>`.
4. Último recurso: `<stateDir>/workspace-<id>`.

⭐ **Cada agente no-default recibe automáticamente un subdirectorio propio con su id.** No hay forma
de que dos agentes compartan workspace por accidente; hay que escribirlo explícitamente. Y
`stripNullBytes()` en cada retorno — defensa contra null-byte injection en rutas, aplicada
consistentemente.

`AgentConfig` (`src/config/types.agents.ts`) tiene además `agentDir`, `model`, `utilityModel`,
`models`, `modelPolicy`, `thinkingDefault`, `verboseDefault`, `reasoningDefault`, `fastModeDefault`,
`contextInjection`, `bootstrapMaxChars`, `bootstrapTotalMaxChars`, `experimental`, `skills`,
`memory` — es decir, **un agente es un perfil completo**: workspace, modelo, política de modelos,
skills permitidas y memoria, no solo un prompt distinto. Nota del propio tipo sobre `skills`:
*"omitting it inherits agents.defaults.skills when set, and an explicit list replaces defaults instead
of merging"* — reemplaza, no mergea. Decisión explícita y documentada.

### 5.7. Caché: tres niveles, todos invalidados por identidad de referencia

Este detalle es de implementación pero es el que hace viable resolver rutas en el camino caliente de
cada mensaje [VERIFICADO EN CÓDIGO]:

```ts
const agentLookupCacheByCfg = new WeakMap<OpenClawConfig, AgentLookupCache>();
const evaluatedBindingsCacheByCfg = new WeakMap<OpenClawConfig, EvaluatedBindingsCache>();
const MAX_EVALUATED_BINDINGS_CACHE_KEYS = 2000;
const resolvedRouteCacheByCfg = new WeakMap<OpenClawConfig, { /* ... */ }>();
const MAX_RESOLVED_ROUTE_CACHE_KEYS = 4000;
```

Tres cachés, todas `WeakMap` **cuya clave es el objeto de configuración**. La invalidación se hace
comparando identidades de referencia:

```ts
function resolveRouteCacheForConfig(cfg: OpenClawConfig): Map<string, ResolvedAgentRoute> {
  const existing = resolvedRouteCacheByCfg.get(cfg);
  if (
    existing &&
    existing.bindingsRef === cfg.bindings &&
    existing.agentsRef === cfg.agents &&
    existing.sessionRef === cfg.session
  ) {
    return existing.byKey;
  }
  // ... reconstruir
}
```

⭐ **No hay TTL ni invalidación manual: si `cfg.bindings` es el mismo objeto, la caché vale.** Un
hot-reload produce objetos nuevos y la caché se descarta sola. Con `WeakMap`, las configs viejas se
recolectan solas. Es la forma más simple de cachear correctamente algo derivado de configuración.

Y el desbordamiento se maneja con **clear total, no LRU**:
```ts
if (routeCache.size > MAX_RESOLVED_ROUTE_CACHE_KEYS) {
  routeCache.clear();
  routeCache.set(routeCacheKey, route);
}
```
Elección deliberada de simplicidad sobre optimalidad: un LRU real requiere estructura extra y bugs; un
clear ocasional cuesta unas resoluciones recalculadas.

⚠️ **La caché se desactiva** cuando hay logging verbose o `identityLinks`:
```ts
const routeCache = !shouldLogDebug && !identityLinks ? resolveRouteCacheForConfig(input.cfg) : null;
```
(Con verbose hay que emitir los logs de diagnóstico en cada resolución; con `identityLinks` la clave
de caché no captura el mapeo de identidades.)

### 5.8. Índices: de O(n) por mensaje a O(1)

Los bindings se pre-indexan una vez por (canal, cuenta) [VERIFICADO EN CÓDIGO]:

```ts
type EvaluatedBindingsIndex = {
  byPeer: Map<string, EvaluatedBinding[]>;
  byPeerWildcard: EvaluatedBinding[];
  byGuildWithRoles: Map<string, EvaluatedBinding[]>;
  byGuild: Map<string, EvaluatedBinding[]>;
  byTeam: Map<string, EvaluatedBinding[]>;
  byAccount: EvaluatedBinding[];
  byChannel: EvaluatedBinding[];
};
```

**Hay un bucket por tier de precedencia.** Cada tier consulta solo su bucket, ya filtrado. Y el orden
de la config se preserva al mezclar bindings de cuenta específica con los de `"*"`
(`mergeEvaluatedBindingsInSourceOrder`, una fusión tipo merge-sort sobre el campo `order`).

⚠️ **Nota de escala honesta**: todo este aparato (3 cachés, 7 índices, merge en orden de fuente, ~500
de las 819 líneas del archivo) existe para un problema que empieza a importar con **cientos de
bindings y miles de mensajes por minuto**. Para un usuario único con 3 bindings, un `for` lineal sobre
la lista tiene el mismo comportamiento observable. **Lo que hay que copiar son los 8 tiers, el
`matchedBy` y el formato de la clave de sesión — no las cachés.**

---

## 6. Límites y debilidades reales

Esta sección es deliberadamente escéptica. Su regla: **nada se afirma sin evidencia en código**, y
cuando la documentación promete algo que el código no respalda —o lo respalda con letra chica— se
dice explícitamente.

Antes de empezar, una advertencia sobre este mismo documento: **ya me equivoqué una vez acá** (ver la
corrección al principio de §4.5, donde afirmé que no existía lock de instancia y existe, 550 líneas,
una capa más arriba de donde busqué). Los "hallazgos negativos" de esta sección están acotados a
búsquedas que sí verifiqué en varias capas, y lo digo caso por caso.

### 6.1. Qué se rompe exactamente cuando el daemon muere

La pregunta hay que partirla en tres, porque las respuestas son distintas.

#### (a) Requests RPC en vuelo: **se pierden todos, sin reintento** [VERIFICADO EN CÓDIGO]

Cuando el socket se cae, el cliente rechaza **todas** las requests pendientes. De
`packages/gateway-client/src/protocol-client.ts`:

```ts
private flushRequests(err: Error) {
  const pending = [...this.pending.values()];
  this.pending.clear();
  for (const entry of pending) {
    entry.reject(err);
  }
}
```

y en el handler de cierre se llama con `CLIENT_CLOSED`. No hay cola de reintento, no hay
"re-enviar al reconectar". **Y esto es intencional, no un olvido**: hay un test cuyo nombre lo dice
literalmente (`packages/gateway-client/src/client.watchdog.test.ts:641`):

```ts
test("rejects an unbounded request, reconnects, and does not replay it", async () => {
```

Es la decisión correcta —reenviar ciegamente una request no idempotente después de un corte es cómo
se duplican mensajes— pero **traslada la responsabilidad al llamador**, que tiene que decidir si
reintenta. Ninguna capa lo hace por él.

#### (b) Eventos emitidos mientras el cliente estaba desconectado: **se pierden** [VERIFICADO EN CÓDIGO]

Busqué en `src/gateway/` un buffer de eventos, un ring buffer, un `replayEvents`, un `missedEvents` o
cualquier estructura que retenga eventos por cliente desconectado. **No existe.** `broadcast()`
escribe a los sockets abiertos en ese instante y nada más. El único `replay` que existe en el cliente
es `approvalReplay` en `session-subscriptions.ts`, que **no es replay de eventos**: es un snapshot que
el servidor devuelve *dentro de la respuesta al subscribe*.

El patrón real de recuperación de OpenClaw es, entonces:

> **No hay replay de eventos. Hay re-snapshot en la resuscripción.**

Y por eso existen `stateVersion: { presence, health }` y `appliedConfigHash` (§4.7): el cliente que
reconecta compara contadores y **si cambió, pide el estado completo de nuevo**. Es un diseño
sólido —evita el crecimiento no acotado de buffers— pero tiene una consecuencia que la documentación
no destaca: **cualquier evento que no tenga un snapshot equivalente del lado servidor se pierde de
verdad.** Los eventos de progreso incremental de un turno son el caso: si el cliente estaba
desconectado durante el streaming, ese streaming no vuelve; a lo sumo vuelve el mensaje final
persistido en el transcript.

#### (c) Estado persistido: **sobrevive**, y esto sí está bien resuelto [VERIFICADO EN CÓDIGO + DOCS]

`docs/gateway/restart-recovery.md` promete que "restarting the gateway does not lose agent state" y
lo respalda. La contrastación con el código:

| Afirmación del doc | Verificación |
|---|---|
| "Queued outbound deliveries → SQLite delivery queue → drained after restart" | ✅ Verificado: `src/infra/session-delivery-queue-storage.ts` (§4.12), con `entryId = sha256Hex(idempotencyKey)` y dead-letter. |
| "Restart continuation → SQLite restart sentinel → one-shot follow-up" | ✅ Verificado: constantes de restart sentinel en §4.12 (20 intentos × 6 s). |
| "Interrupted main-session turn → automatically resumed" | ✅ Verificado: `src/agents/main-session-recovery-state.ts`. |
| "Repeatedly failing recovery is bounded and may quarantine one session" | ✅ Verificado literalmente: `const MAIN_RESTART_RECOVERY_MAX_AUTOMATIC_ATTEMPTS = 3;` más `isMainSessionRecoveryExhausted()` y el mensaje `"main-session restart recovery blocked after N charged automatic resume attempts"`. |
| "Graceful restarts drain first (5 minutes por defecto)" | ⚠️ **Parcialmente verificado.** El drenaje existe (§4.9, pasos 5 y siguientes de `server-close.ts`), pero no encontré una constante única llamada "drain budget = 300000" en `src/gateway/`; los `300_000` que aparecen ahí son de `auth-rate-limit` y de tests de health. El presupuesto de drenaje puede estar parametrizado desde config. **No lo afirmo.** |

**El punto honesto**: la durabilidad de OpenClaw no vive en el gateway. Vive en SQLite. El gateway es
deliberadamente un proceso **sin estado propio que valga la pena preservar**. Es la razón por la que
puede morir y volver: no porque el daemon sea robusto, sino porque *no guarda nada que importe*.

### 6.2. Garantías de entrega: qué hay y qué no

Consolidando §4.12 con lo anterior:

| Camino | Garantía real | Evidencia |
|---|---|---|
| Request RPC cliente → gateway | **Como mucho una vez, sin confirmación.** Si se corta, error `CLIENT_CLOSED` y punto. | `flushRequests` + test "does not replay it" |
| Evento gateway → cliente | **Best effort, sin garantía.** Sin buffer, sin ack, sin secuencia recuperable. | Ausencia verificada de buffer en `src/gateway/` |
| Estado (presence/health/config) | **Convergencia eventual** vía `stateVersion` + re-snapshot. | §4.7 |
| Respuesta del agente → canal | **Al menos una vez, con deduplicación por idempotency key.** | `buildEntryId = sha256Hex(idempotencyKey)`, `session-delivery-queue` |
| Continuación tras restart | **Exactamente una vez, con tope de reintentos.** | restart sentinel, 20 × 6 s |
| Turno interrumpido | **Reanudación automática con cuarentena a los 3 intentos.** | `MAIN_RESTART_RECOVERY_MAX_AUTOMATIC_ATTEMPTS = 3` |

**Lo que esto significa en una frase**: el protocolo del gateway es explícitamente **no confiable**;
la confiabilidad se compra por separado, en SQLite, solo para los caminos donde importa (entregar la
respuesta del agente al usuario). Es una separación limpia y es probablemente la lección de diseño
más transferible de todo el repo.

**Lo que NO hay, verificado**: no hay ack a nivel de aplicación en el protocolo (el frame `res` es la
respuesta a un `req`, no un ack de un `event`); no hay numeración de secuencia reanudable (el `seq`
del envelope es por conexión, se reinicia); no hay backpressure explícito hacia el emisor de eventos.

### 6.3. "Un contrato de canal" es en realidad 27 contratos opcionales

`ChannelPlugin` tiene **31 campos y solo 4 son obligatorios** (`id`, `meta`, `capabilities`,
`config`). Los otros ~27 son superficies de adaptador opcionales (§3.1-3.2). Esto se vende como
composición flexible, y lo es, pero el costo real:

1. **No hay ningún punto donde el compilador te diga si tu canal está completo.** Un canal que
   compila puede no arrancar nunca porque le falta `gateway`.
2. **`channelRuntime?` es opcional** en `ChannelGatewayContext`. Es decir: existen canales legacy que
   no lo reciben, y todo consumidor tiene que manejar el caso `undefined`. La superficie compartida
   —la parte más valiosa del diseño— **no es obligatoria**.
3. **El modelo de estado no es uniforme.** La existencia de `buildPassiveProbedChannelStatusSummary`
   *además de* `buildBaseChannelStatusSummary` (§3.6) prueba que los canales webhook no encajan en el
   modelo de estado de los canales con conexión persistente. La abstracción tiene una costura visible.
4. **~350 métodos de gateway** en la tabla canónica (§2.9). Un "contrato de canal" cuya superficie de
   invocación tiene 350 entradas no es un contrato, es un sistema operativo.

**Evidencia de que los propios autores lo saben**: `src/plugin-sdk/core.ts` termina con
`/* oxlint-disable max-lines -- TODO: split this grandfathered oversized file. */`. Lo mismo
`src/routing/resolve-route.ts`. Ese marcador aparece en **decenas** de archivos del repo (lo verifiqué:
`src/acp/translator.ts`, `src/agents/agent-tools.ts`, `src/agents/auth-profiles/store.ts`, etc.), lo
cual dice algo estructural: el proyecto creció más rápido que su capacidad de refactor, y el linter
está configurado para tolerarlo caso por caso en vez de exigirlo.

### 6.4. Puntos donde el diseño se auto-contradice o esconde complejidad

**Confusión de identificadores de sesión.** Ya documentada en §2.13: conviven `key`, `sessionKey` y
`sessionId` en el protocolo, con significados que se solapan. Es deuda de nomenclatura en el
contrato público, es decir el peor lugar donde tenerla.

**`ingressUnavailable?: true` — el tri-estado por omisión.** Es un patrón inteligente (§3.2): usar
`true | undefined` en vez de `boolean` para que "no lo sé" y "no, está disponible" no colapsen en
`false`. Pero es un patrón que solo funciona si *todos* lo respetan, y no hay nada en el tipo que lo
obligue más allá del literal `true`.

**Cuatro estados de cuenta con cuatro razones.** `isEnabled` / `isConfigured` / `isLinked` /
`hasPersistedAuthState`, cada uno con su `*Reason`. Son ocho campos para responder "¿este canal
anda?". Es preciso, y es exactamente la clase de precisión que un sistema de un solo usuario no
necesita.

**Readiness con caché.** El readiness tiene TTL (§4.6). Un canal que oscila más rápido que el TTL se
reporta estable cuando no lo está. Es un compromiso razonable —sin caché, cada consulta de readiness
sondearía todos los canales— pero es una ventana de mentira que existe por diseño.

**El apagado "limpio" puede no serlo.** En §4.9 quedó documentado que cada paso del shutdown tiene
timeout y **degrada a warning en vez de bloquear**. Consecuencia real: un apagado que reporta éxito
puede haber dejado plugins corriendo, timers vivos o conexiones a medio cerrar. Es la decisión
correcta (un shutdown que se cuelga es peor que uno incompleto), pero significa que **"shutdown
completado" no es una garantía, es un mejor esfuerzo con log**.

**El presupuesto de conexiones pre-auth mete IPs desconocidas en un bucket común** (§4.8): 32 sockets
por IP, y todo lo no identificable comparte cubeta. Es fail-closed y está bien, pero detrás de un
proxy mal configurado —donde todas las IPs reales colapsan a una— el límite se vuelve global y un
solo cliente puede negar el servicio a los demás. `docs/gateway/trusted-proxy-auth.md` existe
precisamente por esto.

### 6.5. Lo que este diseño asume y que no siempre es cierto

- **Asume múltiples clientes concurrentes.** Todo el aparato de broadcast, `stateVersion`,
  `connectionKind`, presupuesto por IP y scopes de operador existe porque se espera más de un
  consumidor. Con un solo cliente, la mitad es infraestructura sin carga.
- **Asume que el gateway y los canales pueden fallar por separado.** De ahí los cuatro estados de
  cuenta, el health con generaciones y coalescing, el readiness como conjunción. Si todos los canales
  viven en el mismo proceso y mueren juntos, ese modelo se colapsa a un booleano.
- **Asume operación desatendida.** El sentinel de restart, la cuarentena a los 3 intentos, el exit
  code 78 para systemd, el dead-letter — todo eso existe para que nadie tenga que mirar. Si hay un
  humano que ve el error y reinicia, buena parte se puede reemplazar por un log claro.
- **Asume multi-tenant / multi-agente real.** Los 8 tiers de precedencia de ruteo (§5.3) y el
  namespacing de sesiones por agente (§5.5) son la respuesta a "muchos agentes, muchos peers, muchas
  cuentas". Con un agente, el tier 1 resuelve todo y los otros 7 nunca se evalúan.

Esta lista es la bisagra hacia la sección 7: **cada supuesto que no se cumple en O.R.I.O.N. es una
pieza que no hay que copiar.**

---

## 7. Traducción a O.R.I.O.N.

Esta sección se escribió **después de leer el código real de O.R.I.O.N.**, no desde supuestos.
Archivos leídos completos: `channels/gateway.py` (289 líneas), `core/orchestrator.py` (161),
`channels/api_channel.py` (119), `main.py` (266); leídos parcialmente: `channels/telegram_bot.py`
(856), `channels/discord_bot.py` (216), `core/security_manager.py` (341).

### 7.1. Qué es hoy `GlassGateway`, de verdad

**No es un gateway.** Es una función de despacho sin estado, instanciada de nuevo en cada mensaje.
Verificado: `GlassGateway()` se construye en **6 lugares distintos**, siempre dentro del handler:

| Archivo | Líneas | Contexto |
|---|---|---|
| `channels/telegram_bot.py` | 562, 616, 711, 759 | `handle_text`, `handle_voice`, y dos handlers más |
| `channels/discord_bot.py` | 68 | handler de mensaje |
| `channels/api_channel.py` | 78 | `POST /chat` |

Como `GlassGateway` no tiene `__init__` ni atributos de instancia, esto **funciona**. Pero es una
trampa cargada: el día que alguien le agregue un caché, un pool de conexiones o un contador, se va a
reinicializar en cada mensaje y el bug va a ser invisible.

**La comparación honesta con OpenClaw**:

| Dimensión | OpenClaw | O.R.I.O.N. hoy |
|---|---|---|
| Proceso | Un daemon persistente, único, con lock de 3 capas | Ninguno; cada bot es su propio proceso |
| Contrato de canal | `ChannelPlugin`, 31 campos, 4 obligatorios | Ninguno formal; cada bot llama a `GlassGateway().process()` a mano |
| Transporte interno | WebSocket con protocolo versionado | Llamada de función Python directa |
| Estado compartido | SQLite + snapshots + `stateVersion` | SQLite (memoria/tareas), sin coordinación entre canales |
| Ruteo | 8 tiers de precedencia, `matchedBy` | `classify_command()` + `if/elif` en el gateway |
| Aislamiento por usuario | Namespacing de clave de sesión por agente | `registry.get_or_create(user_id, ...)` — **esto sí existe y está bien** |
| Seguridad por canal | Scopes de operador + presupuesto pre-auth | `CHANNEL_ALLOWED_LEVELS` (REQ-005) — **conceptualmente equivalente y más simple** |

Dos cosas que O.R.I.O.N. ya hace bien y no hay que tocar: **el aislamiento de sesión por usuario**
(`ai/user_manager.registry`) y **la clasificación de riesgo por canal** de REQ-005. La tabla
`CHANNEL_ALLOWED_LEVELS` que restringe Telegram/Discord/API/Voz a `GREEN` y deja `YELLOW` solo en
Desktop es, para un sistema de un usuario, **mejor** que los 8 scopes de operador de OpenClaw:
resuelve el mismo problema con una tabla de 6 líneas.

### 7.2. Bugs concretos encontrados al leer el código

Encontrados de paso mientras investigaba para esta sección. Todos verificados en el código actual.

#### 🔴 B1 — `_decompose()` parte las frases por la letra "y" (`core/orchestrator.py:87-98`)

```python
def _decompose(self, text: str) -> List[str]:
    simple_triggers = [
        "y", "luego", "después", "además", "también",
        "al mismo tiempo", "mientras", "and", "then",
    ]
    for trigger in simple_triggers:
        if trigger in text.lower():
            parts = [p.strip() for p in text.split(trigger) if p.strip()]
            if len(parts) >= 2:
                logger.info(f"Tarea descompuesta en {len(parts)} sub-tareas vía '{trigger}'")
                return parts
    return [text]
```

`"y"` es el **primer** trigger y la comparación es de subcadena, no de palabra. Consecuencia:

- `"¿qué hora es hoy?"` → contiene `"y"` → `split("y")` → `["¿qué hora es ho", "?"]` → 2 subtareas.
- `"ayúdame con el proyecto"` → `["a", "údame con el pro", "ecto"]` → 3 subtareas.
- `"muy bien"`, `"ya está"`, `"apoyo"`, `"leyendo"` — todas se rompen.

Cada fragmento basura se manda a `_execute_agent_chain()`, que crea un agente por fragmento y
encadena resultados. **Casi cualquier frase en español con una letra "y" dispara ejecución
multi-agente sobre pedazos de palabra.**

Arreglo mínimo — comparar palabras completas y sacar `"y"` sola del arranque de la lista:

```python
import re

_DECOMPOSE_TRIGGERS = ["luego", "después", "además", "también",
                       "al mismo tiempo", "mientras", "then", "y"]

def _decompose(self, text: str) -> List[str]:
    lowered = text.lower()
    for trigger in _DECOMPOSE_TRIGGERS:
        pattern = rf"\b{re.escape(trigger)}\b"
        if not re.search(pattern, lowered):
            continue
        parts = [p.strip() for p in re.split(pattern, text, flags=re.IGNORECASE) if p.strip()]
        if len(parts) >= 2 and all(len(p) > 3 for p in parts):
            logger.info("Tarea descompuesta en %d sub-tareas vía '%s'", len(parts), trigger)
            return parts
    return [text]
```

El `all(len(p) > 3 ...)` es la red de seguridad barata: si algún fragmento es un pedazo de palabra,
no se descompone.

> **Atenuante**: `_decompose()` solo se alcanza si `_try_quick_dispatch()` devolvió `None`, y en el
> camino de Telegram el intent `UNKNOWN` se desvía antes hacia `_ask_claude_for_user`. O sea que el
> bug está parcialmente tapado por el flujo. Sigue siendo alcanzable (canal desktop vía
> `proactive_engine`, y cualquier caso donde el clasificador no esté registrado) y es una bomba con
> temporizador.

#### 🟡 B2 — Doble clasificación por mensaje (`channels/gateway.py:77-92` + `core/orchestrator.py:57`)

En `gateway.py`:

```python
intent, params = classify_command(text)          # ← clasificación #1
...
else:
    params["channel"] = message.channel          # ← params se muta...
    result = orchestrator.process_task(
        text=text,
        channel=message.channel,
        user_id=message.user_id
    )                                            # ← ...y NO se pasa
```

`process_task()` llama a `_try_quick_dispatch()`, que hace `intent, params = self._classifier(text)`
otra vez. Resultado: **cada mensaje pasa dos veces por el clasificador TF-IDF+SVM**, y los `params`
extraídos en el gateway (con el `channel` ya inyectado) se descartan silenciosamente. La línea
`params["channel"] = message.channel` es código muerto que *parece* hacer algo.

Arreglo: o bien `process_task()` acepta `intent`/`params` opcionales precomputados, o bien el gateway
no clasifica y delega todo. La segunda es más limpia, pero el gateway necesita el intent para el caso
`TAKE_SCREENSHOT`; entonces la opción realista es pasarlos:

```python
result = orchestrator.process_task(
    text=text, channel=message.channel, user_id=message.user_id,
    precomputed=(intent, params),
)
```

#### 🟡 B3 — `except Exception: pass` silencioso, en violación de la regla del propio proyecto

`.claude/rules/python-style.md` dice literalmente: *"**Nunca** usar `except: pass` o
`except Exception: pass` sin logging."* Ocurrencias verificadas:

| Archivo | Líneas | Qué se traga |
|---|---|---|
| `channels/gateway.py` | 99-100 | La llamada a `_save_semantic` |
| `channels/gateway.py` | 288-289 | El `memory.store()` **dentro** de `_save_semantic` |
| `main.py` | 175-176 | Toda falla de `try_capability()` |
| `main.py` | 217-218 | El guardado de embedding semántico |

Las dos de `gateway.py` son **doblemente silenciosas**: el `try/except: pass` de la línea 99 envuelve
una función que ya tiene su propio `try/except: pass`. Si la memoria semántica deja de funcionar,
no hay absolutamente ninguna señal en ningún log.

#### 🟡 B4 — El `except` general del gateway no loguea y filtra la excepción al canal

`channels/gateway.py:104-108`:

```python
except Exception as e:
    return GlassResponse(
        text=f"Lo siento, he encontrado un inconveniente: {str(e)[:80]}",
        speak=True
    )
```

Dos problemas: (a) **no hay `logger.error`**, así que el traceback se pierde para siempre; (b) los
primeros 80 caracteres de la excepción se envían al canal — a Telegram, a Discord, a la API. Un
`FileNotFoundError` o un error de una librería pueden incluir rutas absolutas del disco del usuario.

#### 🟠 B5 — La API REST escucha en `0.0.0.0`, sin autenticación, con CORS abierto, y expone el log de auditoría (bomba **desarmada**, ver la nota al final)

`channels/api_channel.py`:

```python
API_PORT = 8723
...
self.send_header("Access-Control-Allow-Origin", "*")     # línea 19
...
self._server = HTTPServer(("0.0.0.0", self.port), _APIHandler)   # línea 107
```

Y los endpoints:

```python
elif parsed.path == "/audit":
    from core.security_manager import security_manager
    log = security_manager.get_audit_log(50)
    self._send_json({"audit_log": log})
```

No hay token, no hay allowlist de IP, no hay ninguna verificación de identidad en ningún punto del
archivo (lo verifiqué leyéndolo completo, 119 líneas). En una red WiFi compartida, cualquiera que
sepa el puerto puede:

- `GET /audit` → leer el registro de seguridad completo,
- `GET /memory?user_id=default` → leer la memoria personal del usuario,
- `POST /chat` → **ejecutar comandos** contra el PC vía `GlassGateway`.

El único freno es `CHANNEL_ALLOWED_LEVELS[ChannelType.API] = [GREEN]` de REQ-005, que impide las
acciones amarillas. **Pero los tres GET no pasan por el security manager en absoluto**: llaman
directo a `task_manager`, `memory` y `security_manager.get_audit_log()`. La lectura de datos
personales no está clasificada como acción y por lo tanto no está protegida.

Esto es exactamente el problema que OpenClaw resuelve con `bind: "loopback" | "lan" | "tailnet" | "auto"`
(§4.3): **la superficie de red es una decisión explícita y con nombre, no un literal `"0.0.0.0"`
enterrado en un constructor.**

Arreglo mínimo, y es de tres líneas:

```python
API_BIND = os.getenv("ORION_API_BIND", "127.0.0.1")   # loopback por defecto
API_TOKEN = os.getenv("ORION_API_TOKEN", "")
```

...más un chequeo de `Authorization: Bearer` al principio de `do_GET`/`do_POST`, y cambiar
`Access-Control-Allow-Origin: *` por el origen concreto que se necesite. **Recomendación fuerte: que
el default sea `127.0.0.1` y que abrir a la LAN requiera poner la variable de entorno a mano.**

> ✅ **Atenuante decisivo, verificado**: busqué `api_server` en todo el proyecto
> (`grep -rn "api_server" --include=*.py .`) y **fuera de su propio archivo no aparece en ningún
> lado**. `channels/api_channel.py:119` crea la instancia a nivel de módulo, pero **nadie llama a
> `.start()`** — ni `main.py`, ni `start_bots.py`, ni `start_jarvis.py`. La API REST es **código
> muerto que hoy no escucha en ningún puerto**.
>
> Eso baja la severidad de 🔴 a 🟠, pero **no la elimina**: el día que alguien agregue
> `api_server.start()` a `start_bots.py` —que es exactamente lo que se necesitaría para el REQ-008—
> el agujero se abre completo y en silencio, porque el `0.0.0.0` y el CORS `*` ya están escritos.
> **Arreglarlo ahora cuesta 5 líneas; arreglarlo después de exponerlo cuesta un incidente.**

#### 🟢 B6 — El canal decide el ruteo (`channels/telegram_bot.py:~545-555`)

```python
text_lower = text.lower()
if any(w in text_lower for w in ["apaga el pc", "apagar el pc", "apaga la pc", "apagar la computadora"]):
    await _handle_shutdown(update, context, voice_mode)
    return
```

El canal hace *matching de intención* antes de entregar el mensaje al gateway. Es la violación
exacta del principio del contrato de OpenClaw: **el canal transporta, no decide**. Consecuencias
reales: esa lógica está solo en Telegram (Discord y la API no la tienen), y cualquier frase nueva hay
que agregarla en el canal en vez de en el clasificador. No es urgente —funciona— pero es el tipo de
duplicación que se multiplica con cada canal nuevo.

### 7.3. Qué adoptar de OpenClaw

Ordenado por relación valor/costo para O.R.I.O.N., de mayor a menor.

#### ⭐ 1. El dataclass de contrato de canal, sin herencia (barato, alto valor)

O.R.I.O.N. ya tiene `GlassMessage`/`GlassResponse`, que son **la mitad buena** del contrato. Lo que
falta es el otro lado: qué debe proveer un canal. La lección de OpenClaw es que **no debe ser una
clase base con métodos abstractos, sino un objeto de capacidades declaradas** (§3.1).

Traducción directa y proporcionada a Python:

```python
# channels/contract.py
from dataclasses import dataclass, field
from typing import Callable, Optional, Awaitable

@dataclass(frozen=True)
class ChannelCapabilities:
    """Lo que este canal PUEDE hacer. El core consulta esto, no adivina."""
    text: bool = True
    voice: bool = False
    images: bool = False
    files: bool = False
    confirmations: bool = False   # ¿puede pedir confirmación interactiva?

@dataclass
class ChannelPlugin:
    id: str                                   # "telegram", "discord", "api", "desktop"
    capabilities: ChannelCapabilities
    max_risk_level: "RiskLevel"               # reemplaza CHANNEL_ALLOWED_LEVELS
    send: Callable[[str, "GlassResponse"], None]
    start: Optional[Callable[[], None]] = None
    stop: Optional[Callable[[], None]] = None
    health: Optional[Callable[[], "ChannelHealth"]] = None
```

**Por qué esta forma y no una clase base**: en OpenClaw, de 31 campos solo 4 son obligatorios, y la
razón es que los canales son *muy* distintos entre sí (webhook vs conexión persistente vs polling).
Una `BaseChannel(ABC)` con `@abstractmethod` obliga a cada canal a implementar `send_voice()` aunque
no tenga voz. El dataclass con `Optional[Callable]` deja que el core pregunte
`if plugin.health: ...`. **Adoptar: la forma. No adoptar: los 27 campos.** Con 6 alcanza.

Ganancia inmediata y concreta: `capabilities.confirmations` resuelve un problema que O.R.I.O.N. tiene
hoy — las acciones `YELLOW` están bloqueadas en Telegram no porque sean peligrosas ahí, sino porque
**no hay forma de pedir confirmación**. Con el campo declarado, un canal que sí sepa hacerlo
(botones inline de Telegram) puede habilitar amarillo sin cambiar el security manager.

#### ⭐ 2. El registro de canales con un solo punto de entrada (barato, alto valor)

Hoy cada bot importa y construye `GlassGateway` por su cuenta. Reemplazarlo por un registro:

```python
# channels/registry.py
_CHANNELS: dict[str, ChannelPlugin] = {}

def register_channel(plugin: ChannelPlugin) -> None:
    if plugin.id in _CHANNELS:
        logger.warning("Canal %s ya registrado; se reemplaza", plugin.id)
    _CHANNELS[plugin.id] = plugin

def get_channel(channel_id: str) -> Optional[ChannelPlugin]:
    return _CHANNELS.get(channel_id)
```

Esto arregla B5 y B6 de raíz: el nivel de riesgo pasa a ser un dato del canal registrado, no un
`dict` global, y el core puede rechazar un canal desconocido en vez de caer a `ChannelType.UNKNOWN`.

#### ⭐ 3. `matchedBy` — que el ruteo explique por qué eligió (muy barato, alto valor de depuración)

De §5.2, el campo más transferible de todo el módulo de ruteo. En O.R.I.O.N.:

```python
@dataclass
class DispatchDecision:
    result: str
    matched_by: str        # "routine" | "autopilot" | "capability" | "intent:OPEN_APP" | "claude_fallback"
    intent: Optional[str] = None
    elapsed_ms: float = 0.0
```

`main.py` tiene hoy **seis** capas de decisión en cascada (rutinas → autopilot → comandos aprendidos →
capacidades → intents → Claude), cada una con su `if ... : break`. Cuando algo se resuelve mal, no hay
forma de saber cuál capa lo agarró sin leer los logs línea por línea. Un `matched_by` en la respuesta
lo convierte en un dato. **Esto es lo más barato de toda la lista y lo que más tiempo de depuración
ahorra.**

#### 4. La distinción "durabilidad en SQLite, transporte no confiable" (conceptual, gratis)

La lección de §6.2, aplicada: **no intentar que el canal garantice entrega**. Si O.R.I.O.N. alguna vez
necesita que una respuesta llegue sí o sí (por ejemplo, un recordatorio programado a las 8:00 cuando
Telegram está caído), la solución no es reintentar en el bot: es una tabla en SQLite con
`idempotency_key` como clave primaria. Y O.R.I.O.N. **ya tiene** `tasks.db` y `task_manager`; el
patrón es el mismo, cambiando `task` por `pending_delivery`.

El truco de OpenClaw que vale copiar textualmente: **la deduplicación vive en la elección de la clave
primaria** (`entry_id = sha256(idempotency_key)`), no en una consulta de "¿ya existe?". Un `INSERT OR
IGNORE` hace todo el trabajo, sin race conditions.

#### 5. `bind` como política con nombre en vez de host crudo (barato, arregla B5)

```python
BIND_POLICIES = {
    "loopback": "127.0.0.1",
    "lan": "0.0.0.0",
}
API_BIND = BIND_POLICIES.get(os.getenv("ORION_API_BIND", "loopback"), "127.0.0.1")
```

Cinco líneas, default seguro, y el que quiera exponerlo a la red tiene que escribir la palabra `lan`
—lo cual es una decisión consciente y auditable— en vez de heredar un `0.0.0.0` que nadie eligió.

### 7.4. Qué hacer distinto y mejor que OpenClaw

**1. Un `matched_by` que también explique lo que NO matcheó.** OpenClaw devuelve por qué eligió.
O.R.I.O.N., con seis capas en cascada y un solo usuario, puede permitirse devolver la traza completa
en modo debug: `["routine: no match", "autopilot: no trigger", "capability: no match", "intent: OPEN_APP (0.87)"]`.
Con miles de mensajes por minuto eso sería inaceptable; con veinte por día es el mejor log posible.

**2. Confirmaciones nativas por canal en vez de bloqueo por canal.** REQ-005 bloquea `YELLOW` en
Telegram. Es correcto **hoy**, porque no hay mecanismo de confirmación. Pero es más restrictivo de lo
necesario: Telegram tiene botones inline, que son un mecanismo de confirmación *mejor* que el prompt
de consola del desktop (queda registro, es explícito, no se puede confirmar por accidente con un
Enter). El diseño superior es `capabilities.confirmations = True` + el security manager preguntando
por ese canal, en lugar de una tabla estática.

**3. Un solo lugar de clasificación, no seis capas en cascada.** OpenClaw resuelve el ruteo con una
**lista de datos** de 8 tiers recorrida por un loop de 15 líneas (§5.3). O.R.I.O.N. tiene la misma
idea implementada como seis bloques `if/try/break` de ~15 líneas cada uno en `main.py`, más el
`if/elif` de `gateway.py`, más `_try_quick_dispatch`. La mejora no es agregar tiers, es **convertir
las capas que ya existen en una lista**:

```python
RESOLVERS = [
    ("routine",    try_routine),
    ("autopilot",  try_autopilot),
    ("learned",    try_learned_command),
    ("capability", try_capability),
    ("intent",     try_intent_dispatch),
    ("claude",     ask_claude_fallback),
]

for name, resolver in RESOLVERS:
    result = resolver(text, channel=channel, user_id=user_id)
    if result is not None:
        return DispatchDecision(result=result, matched_by=name)
```

Esto elimina de un saque la divergencia entre `main.py` (desktop) y `gateway.py` (bots), que hoy
tienen **órdenes de resolución distintos** — desktop prueba rutinas y autopilot, el gateway no. Ese
es un bug latente de comportamiento inconsistente entre canales que ningún test va a detectar.

**4. Un `logger.error` obligatorio en el `except` de más arriba.** OpenClaw degrada a warning y sigue
(§6.4), que es correcto para un daemon desatendido. O.R.I.O.N. tiene un humano mirando: el `except`
general debe **loguear el traceback completo** y devolver al canal un mensaje genérico *sin* el texto
de la excepción (arregla B4).

### 7.5. Qué sería sobreingeniería para O.R.I.O.N.

Sin rodeos. Lo siguiente **no hay que copiarlo**, y el motivo en cada caso:

| Pieza de OpenClaw | Veredicto | Por qué |
|---|---|---|
| **Protocolo WebSocket versionado con 3 frames y ~350 métodos** | ❌ No | Existe para que clientes de terceros (apps móviles, la CLI, el bridge) hablen con el daemon por red. O.R.I.O.N. tiene todo en un proceso Python: una llamada de función es más rápida, más simple y más fácil de depurar que serializar JSON contra localhost. |
| **`stateVersion` + resync por reconexión** | ❌ No | Resuelve "cliente se desconectó y perdió eventos". Sin protocolo de red, no hay desconexión que resolver. |
| **Presupuesto de conexiones pre-auth (32/IP)** | ❌ No | Protege contra ataques de agotamiento de conexión. La respuesta correcta para un usuario único es `bind=127.0.0.1` (§7.3.5), que hace el problema inexistente en vez de acotado. |
| **Lock de instancia de 3 capas + reclamación por start-time de PID** | ⚠️ Solo la capa 3 | Las 550 líneas de `gateway-lock.ts` existen porque el gateway puede correr bajo systemd, launchd, en Docker y en modo multi-tenant. Si O.R.I.O.N. alguna vez necesita instancia única: un `socket.bind(("127.0.0.1", puerto))` que falle con `EADDRINUSE` resuelve el 95%, en 4 líneas. La detección de lock rancio por start-time es genuinamente ingeniosa, pero es una solución a un problema que un usuario que ve el error y mata el proceso no tiene. |
| **8 tiers de precedencia de ruteo** | ❌ No (ver §8, REQ-014) | Existen para desambiguar entre muchos agentes, muchos peers y muchas cuentas. Con un agente, el tier 1 resuelve el 100%. |
| **Cachés WeakMap indexadas por identidad del objeto de config** | ❌ No | §5.7 y §5.8 ya lo dicen: es optimización para cientos de bindings y miles de mensajes por minuto. Un `for` lineal sobre 3 elementos tiene el mismo comportamiento observable. |
| **Cuatro estados de cuenta (`isEnabled`/`isConfigured`/`isLinked`/`hasPersistedAuthState`) con sus 4 razones** | ❌ No | Ocho campos para responder "¿el canal anda?". Para O.R.I.O.N.: `health() -> tuple[bool, str]`. Un booleano y un motivo. |
| **Health con generaciones, coalescing y fuerza passive/probe** | ❌ No | Resuelve carreras entre sondeos concurrentes de decenas de canales. Con 3 canales, un sondeo secuencial cada N segundos es correcto y cabe en 20 líneas. |
| **Readiness como conjunción de todas las cuentas, con TTL** | ❌ No | Y encima el TTL introduce la ventana de mentira de §6.4. |
| **Cola de entrega durable con 5 clases de error y dead-letter** | ⚠️ La idea sí, las 5 clases no | Adoptar: tabla SQLite con `idempotency_key` como PK, un contador de intentos y un tope. No adoptar: la máquina de estados de `Deferred`/`RetryCharged`/`AttemptStart`/`SafeRetry`/`DeadLettered`, que distingue casos que solo importan con volumen. |
| **Sentinel de restart + recuperación de turnos interrumpidos con cuarentena a los 3 intentos** | ❌ No, por ahora | Es infraestructura para operación desatendida. Si O.R.I.O.N. se cae a mitad de una respuesta, el usuario la vuelve a pedir. El costo de implementarlo bien (transacción de admisión, marcadores de recuperación, escaneo al arranque, fail-closed con hooks) es de varios días; el beneficio es evitar que el usuario reescriba una frase. |
| **`deliveryMode: direct \| gateway \| hybrid`** | ❌ No | Solo tiene sentido si existen los dos caminos. En O.R.I.O.N. hay uno. |

**La síntesis en una frase**: de las tres áreas analizadas, **el contrato de canal es lo único que
O.R.I.O.N. necesita de verdad hoy**. El gateway persistente resuelve un problema que O.R.I.O.N. no
tiene (múltiples procesos que necesitan coordinarse), y el ruteo multi-agente resuelve un problema
que O.R.I.O.N. no tiene todavía (múltiples agentes con identidad y workspace propios).

---

## 8. Alimentación a REQs futuros

El roadmap ubica REQ-008 (gateway único persistente) y REQ-009 (contrato común de canal) en la Fase 1
(CORE), y REQ-014 (ruteo multi-agente config-driven) en la Fase 4, marcado como opcional. Esta
sección da, para cada uno, el patrón aplicable, las decisiones abiertas, los riesgos y **un veredicto
honesto de si vale la pena para un sistema de un solo usuario**.

### 8.0. Un dato que cambia el planteo de REQ-008

Antes de evaluar nada: **el "gateway persistente" ya existe a medias en O.R.I.O.N. y nadie lo llama
así.** Es `start_bots.py` [VERIFICADO EN CÓDIGO]:

```python
if run_telegram_flag:
    if _has_token("TELEGRAM_BOT_TOKEN", "telegram_token"):
        t = threading.Thread(target=run_telegram, daemon=True, name="TelegramBot")
        t.start()
        threads.append(("Telegram", t))
...
try:
    while True:
        time.sleep(5)
        # Verificar que los hilos siguen vivos
        for name, thread in threads:
            if not thread.is_alive():
                print(f"  [Aviso] El canal {name} se detuvo inesperadamente.")
except KeyboardInterrupt:
    ...
```

Es decir: **un proceso persistente, que aloja varios canales en hilos, con un loop de supervisión de
5 segundos.** Estructuralmente, eso *es* el gateway. Lo que le falta no es arquitectura, son cuatro
cosas concretas:

| Falta | Evidencia | Costo de arreglarlo |
|---|---|---|
| El loop de supervisión detecta el hilo muerto pero **solo imprime** — nunca reinicia | `start_bots.py:110-112` | ~15 líneas (relanzar el hilo con backoff) |
| Usa `print()` en vez del logger, violando `python-style.md` | `start_bots.py:82, 84, 112, 114` | trivial |
| No hospeda ni el canal desktop (`main.py`) ni la API | dos procesos separados | medio |
| El `loop = asyncio.new_event_loop()` de `run_telegram()` se crea, se setea y **no se usa** — `run_telegram_bot()` levanta el suyo | `start_bots.py:39-41` | 2 líneas |

**Consecuencia para el REQ-008**: el requerimiento no debería redactarse como "construir un gateway
persistente" (suena a proyecto grande) sino como **"unificar `main.py` y `start_bots.py` en un solo
anfitrión de canales con supervisión real"**. Es el mismo resultado, con un alcance honesto.

---

### 8.1. REQ-008 — Gateway único persistente

**Patrón aplicable de OpenClaw**: el arranque en fases con el handler de cierre construido *antes* de
abrir nada (§4.4, fase 3), y el `GatewayServer` cuya API pública es **un solo método `close()`**
(§4.3). Esa segunda idea es la más valiosa y la más barata: el anfitrión no expone nada más que su
propio apagado; todo lo demás pasa por los canales registrados.

**Traducción mínima a Python**:

```python
# core/channel_host.py
@dataclass
class ChannelHost:
    _plugins: list[ChannelPlugin] = field(default_factory=list)
    _threads: dict[str, threading.Thread] = field(default_factory=dict)
    _stopping: threading.Event = field(default_factory=threading.Event)

    def start(self) -> None:
        # Fase 1: validar config de todos los canales (antes de abrir nada)
        # Fase 2: registrar el handler de señales / cierre  ← ANTES de arrancar
        # Fase 3: arrancar cada canal en su hilo
        # Fase 4: loop de supervisión con reinicio y backoff
        ...

    def close(self, timeout: float = 10.0) -> None:
        """Único método público además de start(). Nunca bloquea más de `timeout`."""
        self._stopping.set()
        for plugin in self._plugins:
            if plugin.stop:
                try:
                    plugin.stop()
                except Exception as exc:
                    logger.warning("canal %s falló al detenerse: %s", plugin.id, exc)
        ...
```

Los dos detalles de OpenClaw que **sí** hay que copiar textualmente:

1. **Registrar el cierre antes de abrir** (§4.4). Si el canal 2 falla al arrancar, el canal 1 ya está
   corriendo y hay que poder cerrarlo. Es el error clásico y OpenClaw lo resuelve invirtiendo el orden.
2. **Cada paso del cierre con timeout, degradando a warning** (§4.9). Un `close()` que se cuelga
   porque un bot no responde es peor que uno incompleto que loguea.

**Decisiones abiertas**:

- **¿Un proceso o dos?** Hoy `main.py` (desktop, con GUI PyQt6 y micrófono) y `start_bots.py` (bots)
  son procesos separados, y hay un motivo real: PyQt6 quiere el hilo principal, y el wake word bloquea.
  Unificar significa meter la GUI en el mismo proceso que los bots. **Recomendación: no unificar.**
  Dejar dos procesos y darles el mismo `ChannelHost` como anfitrión interno. Se gana la consistencia
  de código sin pelear con el event loop de Qt.
- **¿Estado compartido entre los dos procesos?** Hoy comparten SQLite y eso alcanza. No hace falta IPC.
- **¿Instancia única?** Si se decide, ver §7.5: `socket.bind(("127.0.0.1", puerto))` y listo. No copiar
  las 550 líneas de `gateway-lock.ts`.

**Riesgos**:

- 🔴 **Riesgo alto y concreto**: si el REQ-008 arranca la API REST dentro del host (que es lo natural),
  se activa B5 — `0.0.0.0`, sin auth, con `/audit` y `/memory` expuestos. **El REQ-008 debe incluir el
  arreglo de B5 como criterio de aceptación bloqueante, o no debe tocar la API.**
- 🟡 Meter la GUI y los bots en un proceso puede romper el wake word o la GUI de formas difíciles de
  depurar. Mitigación: la recomendación de arriba (no unificar procesos).
- 🟡 El reinicio automático de un canal caído puede entrar en loop si el token es inválido. Mitigación:
  backoff exponencial con tope y **rendirse tras N intentos**, como el `MAX_AUTOMATIC_ATTEMPTS = 3` de
  OpenClaw (§6.1c). Ese número sí vale copiarlo.

#### ⚖️ Veredicto honesto sobre REQ-008

**Vale la pena, pero NO como "gateway persistente con protocolo". Vale la pena como refactor.**

Lo que un usuario único gana de verdad:

- ✅ **Un solo orden de resolución.** Hoy `main.py` prueba rutinas → autopilot → aprendidos →
  capacidades → intents, y `gateway.py` prueba tareas → listar → completar → screenshot → intents.
  **Son distintos.** Un comando que funciona por consola puede no funcionar por Telegram, y viceversa,
  y nadie lo va a notar hasta que pase. Esto es un bug de comportamiento, no una preferencia estética.
- ✅ **Supervisión que supervise** (hoy solo imprime).
- ✅ **Un lugar donde poner el `logger.error` que falta** (B4).

Lo que **no** gana y que la palabra "gateway" sugiere que ganaría:

- ❌ Protocolo, versionado, handshake, reconexión, broadcast, `stateVersion`. Nada de eso resuelve
  ningún problema que O.R.I.O.N. tenga. Es §7.5 completo.
- ❌ Multi-cliente. Hay un usuario.

**Estimación honesta de alcance**: si el REQ-008 se redacta como "unificar el pipeline de resolución
en un módulo y darle supervisión real al anfitrión de canales", es un REQ de tamaño medio con
beneficio inmediato y medible. Si se redacta como "daemon persistente con protocolo", es semanas de
trabajo para reimplementar lo que una llamada de función ya hace mejor. **La diferencia entre los dos
REQs es una frase en la SPEC**, y es la decisión más importante de toda esta sección.

---

### 8.2. REQ-009 — Contrato común de canal

**Patrón aplicable**: §3.1-3.2 completos, pero reducidos. La forma (dataclass con capacidades
declaradas y callables opcionales, no herencia) es lo que se copia; los 31 campos, no.

Estructura propuesta, ya justificada en §7.3.1:

```python
@dataclass(frozen=True)
class ChannelCapabilities:
    text: bool = True
    voice: bool = False
    images: bool = False
    files: bool = False
    confirmations: bool = False

@dataclass
class ChannelPlugin:
    id: str
    capabilities: ChannelCapabilities
    max_risk_level: RiskLevel
    send: Callable[[str, GlassResponse], None]
    start: Optional[Callable[[], None]] = None
    stop: Optional[Callable[[], None]] = None
    health: Optional[Callable[[], tuple[bool, str]]] = None
```

**Decisiones abiertas**:

1. **¿`max_risk_level` en el plugin o sigue `CHANNEL_ALLOWED_LEVELS` en `security_manager.py`?**
   Argumento a favor de moverlo al plugin: es un dato del canal. Argumento en contra, y es fuerte:
   **REQ-005 hizo que la clasificación de riesgo fuera fail-closed y centralizada a propósito.** Si
   cada canal declara su propio nivel máximo, un canal nuevo mal escrito puede declararse `YELLOW`
   y saltarse la revisión. **Recomendación: dejar la tabla donde está y que el plugin solo *declare*
   `capabilities.confirmations`.** El security manager sigue teniendo la última palabra. Esto es
   O.R.I.O.N. haciéndolo mejor que OpenClaw, no peor.
2. **¿Se migran los 3 canales de una o uno por vez?** Uno por vez, empezando por Discord (216 líneas,
   el más chico). Telegram tiene 856 líneas y lógica de ruteo propia (B6) que hay que desarmar con
   cuidado.
3. **¿`send` sincrónico o async?** Telegram y Discord son async; el desktop y la API son síncronos.
   OpenClaw resuelve esto porque todo Node es async. En Python hay que elegir. **Recomendación:
   `send` sincrónico en el contrato, y que el canal async haga el puente internamente**
   (`asyncio.run_coroutine_threadsafe`). Meter `async` en el contrato contagia async a todo el core,
   que hoy es síncrono. Ese contagio es el riesgo técnico más grande de este REQ.

**Riesgos**:

- 🔴 **Contagio de async.** Ver punto 3. Si el contrato es async, `dispatch()`, los skills y el
  security manager terminan teniendo que ser async. Es un refactor de todo el proyecto disfrazado de
  REQ de canales. **Criterio de aceptación sugerido: el core no incorpora ni un `async def` nuevo.**
- 🟡 Al desarmar B6 (el matching de "apaga el pc" en Telegram), esa funcionalidad tiene que seguir
  andando por el clasificador. Necesita test de regresión específico.
- 🟢 Bajo riesgo en lo demás: es aditivo, los canales pueden migrarse de a uno y convivir.

#### ⚖️ Veredicto honesto sobre REQ-009

**Sí, hacerlo. Es el mejor REQ de los tres, y por bastante margen.**

Motivos, todos verificables en el código actual:

- Hoy hay **6 sitios** que construyen `GlassGateway()` a mano; agregar un canal significa copiar ese
  patrón por séptima vez.
- La lógica de ruteo se está filtrando hacia los canales (B6) y solo va a empeorar.
- `capabilities.confirmations` desbloquea acciones amarillas por Telegram **sin debilitar la
  seguridad** — hoy están bloqueadas por una limitación técnica, no por una decisión de riesgo.
- Es barato: el contrato son ~40 líneas y la migración de cada canal es mecánica.

**Es el único de los tres que recomendaría hacer sin condiciones.** Y conviene hacerlo **antes** del
REQ-008: el contrato de canal es lo que le da al anfitrión algo que hospedar. Al revés, el REQ-008
tendría que inventar un contrato ad-hoc y después rehacerlo.

> **Sugerencia de orden**: REQ-009 (contrato) → REQ-008 (anfitrión unificado). El roadmap los pone
> juntos en Fase 1; esta es la dependencia interna.

---

### 8.3. REQ-014 — Ruteo multi-agente config-driven

**Patrón aplicable**: §5.1-5.6. Los bindings declarativos, los 8 tiers de precedencia como lista de
datos, el `matchedBy`, el namespacing de clave de sesión (`agent:<agentId>:...`), los 4 modos de
`dmScope`, `identityLinks`, y el aislamiento de workspace por agente.

Configuración equivalente en O.R.I.O.N. sería algo así:

```json
{
  "agents": {
    "default":  { "workspace": "workspace/default" },
    "trabajo":  { "workspace": "workspace/trabajo" },
    "personal": { "workspace": "workspace/personal" }
  },
  "bindings": [
    { "channel": "telegram", "peer": "123456789", "agent": "personal" },
    { "channel": "discord",  "guild": "mi-servidor", "agent": "trabajo" },
    { "channel": "*",        "agent": "default" }
  ]
}
```

**Decisiones abiertas**: cuántos tiers (OpenClaw usa 8; O.R.I.O.N. necesitaría 3: peer específico →
canal → default), si la clave de sesión lleva el agente como primer segmento (sí, si se hace: es lo
que impide el cruce de contextos), y si el workspace por agente es un directorio real o solo un
namespace en SQLite.

**Riesgos**:

- 🔴 **Aislamiento roto por clave de sesión mal formada.** OpenClaw resuelve esto **lanzando
  excepción** en vez de caer al agente por defecto (§5.5) — porque caer al default significa que la
  conversación privada del agente "personal" aterriza en el contexto de "trabajo". Si este REQ se
  hace, **esa decisión de fail-closed es obligatoria**, no opcional.
- 🟡 Interacción con el aislamiento por usuario que ya existe (`registry.get_or_create`). Habría dos
  ejes de partición (usuario × agente) y hay que definir cuál manda.

#### ⚖️ Veredicto honesto sobre REQ-014

**No. Para un sistema de un solo usuario, esto es sobreingeniería.**

Lo digo con la evidencia en la mano:

1. **Los 8 tiers existen para desambiguar.** Con un usuario y un agente, el tier de fallback (`"*"`)
   resuelve el 100% de los mensajes y los otros 7 nunca se evalúan. Se estaría escribiendo y
   testeando código muerto.
2. **El namespacing de sesión por agente resuelve fugas de contexto entre agentes.** O.R.I.O.N. no
   tiene múltiples agentes con identidad persistente: tiene un `DynamicAgentFactory` que **crea un
   agente efímero por tarea** (`core/orchestrator.py:101, 127`). Esos agentes no tienen memoria propia
   ni workspace; el contexto vive en `agent_context_manager`, indexado por `(agent.name, user_id)`.
   No hay nada que aislar todavía.
3. **El aislamiento de workspace por agente resuelve que un agente lea archivos de otro.** Un solo
   usuario dueño de todos los archivos no tiene ese problema.
4. **`identityLinks` (misma persona en varios canales → misma sesión)** es la única pieza con valor
   plausible: hoy el mismo humano tiene un `user_id` distinto en Telegram (`str(user.id)`) que en
   Discord, así que **son dos sesiones y dos memorias**. Eso sí es una molestia real. Pero se
   resuelve con **un dict en la config**, no con un sistema de ruteo:

   ```json
   { "identity_links": { "johan": ["telegram:123456789", "discord:98765", "desktop:default"] } }
   ```

   Diez líneas en `registry.get_or_create()` para normalizar el `user_id` antes de buscar la sesión.
   **Esa es la mejora de valor. El resto del REQ-014 no.**

**Recomendación concreta**: cerrar REQ-014 como "no se hace", y extraer de él **un micro-REQ de
unificación de identidad entre canales** (el punto 4), que cabe en una tarde y arregla un problema
que el usuario probablemente ya notó.

**Cuándo reconsiderarlo**: si algún día O.R.I.O.N. tiene agentes con personalidad y memoria
persistentes y separadas (un "asistente de trabajo" que no debe ver la conversación personal), el
patrón de §5.5 —clave de sesión con el agente como primer segmento, y excepción si está mal formada—
es exactamente la solución correcta, y está transcrito acá para cuando haga falta. **Hoy no hace
falta.**

---

### 8.4. Tabla resumen de veredictos

| REQ | Veredicto | Condición | Prioridad |
|---|---|---|---|
| **REQ-009** — contrato de canal | ✅ **Hacer** | Que el contrato sea síncrono (no contagiar async) y que el nivel de riesgo siga en `security_manager` | **Alta — primero** |
| **REQ-008** — anfitrión unificado | ✅ **Hacer, redactado como refactor** | Que la SPEC diga "unificar el pipeline de resolución y supervisar canales", no "daemon con protocolo". Arreglar B5 si toca la API. Después de REQ-009 | Media |
| **REQ-014** — ruteo multi-agente | ❌ **No hacer** | Extraer solo la unificación de identidad entre canales como micro-REQ | Baja / descartar |
| *(nuevo)* — bugs B1-B6 | ✅ **Hacer ya** | B1 y B5 son los urgentes; B3 viola una regla escrita del proyecto | **Alta — independiente** |

**La conclusión general**, dicha sin adorno: de las tres áreas que este documento analizó, **una es
directamente aplicable (el contrato de canal), una es aplicable solo si se le baja el alcance (el
gateway), y una no aplica (el ruteo multi-agente)**. OpenClaw resuelve problemas de escala,
multi-cliente y operación desatendida. O.R.I.O.N. tiene un usuario, un proceso principal y un humano
mirando la pantalla. La mayor parte de lo que hace robusto a OpenClaw es, acá, complejidad sin
contrapartida — y decirlo es el resultado más útil de todo el análisis.
