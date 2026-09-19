# OpenClaw — Seguridad y Aislamiento

> **Aviso de terceros.** Los fragmentos de código transcritos en este documento pertenecen a
> [OpenClaw](https://github.com/openclaw/openclaw), Copyright (c) 2026 OpenClaw Foundation,
> licencia MIT. Se reproducen con fines de estudio; el aviso de permiso completo está en
> `THIRD_PARTY_NOTICES.md`. Ningún archivo de código de este proyecto copia ni traduce ese
> código.

**Documento de referencia autosuficiente**
Fecha de análisis: 2026-07-31 / 2026-08-01
Repo analizado: `openclaw-main` (TypeScript/Node, monorepo pnpm) — *esta carpeta será borrada del proyecto; este documento es la única traza que queda.*
Objetivo: entender los mecanismos reales, con el código transcrito literalmente, para poder reimplementar los patrones útiles en O.R.I.O.N. (Python) sin volver a mirar el original.

> **Convención de este documento**
> - Todo el código está **transcrito literalmente** del repo original. La ruta original se cita como referencia histórica.
> - Se distingue explícitamente entre **[VERIFICADO EN CÓDIGO]** y **[AFIRMACIÓN DE DOCUMENTACIÓN]**.
> - Los hallazgos negativos ("busqué X y no existe") están marcados como tales.

---

## 1. Resumen ejecutivo

OpenClaw es un gateway de agentes que ejecuta un LLM con herramientas de alto poder (ejecución de comandos, escritura de archivos, control de escritorio, envío de mensajes por Telegram/WhatsApp/Discord) en la máquina del operador. Su modelo de seguridad **no** intenta ser una frontera multi-tenant: parte del supuesto de un solo dueño ("one-user trust model") y su seguridad se orienta a **reducir el radio de daño de un modelo que se equivoca o es manipulado por prompt-injection**, no a resistir a un usuario local adversario.

Sobre esa base construye siete mecanismos que vale la pena entender:

1. **Deny-list de herramientas por superficie** (`DEFAULT_GATEWAY_HTTP_TOOL_DENY`): la superficie HTTP del gateway pierde por defecto las 19 herramientas de mayor riesgo (exec, shell, fs_write, terminal, sessions_spawn, conversations_*, gateway, nodes, computer, mobile_ui…). Es deny-list, no allow-list, y **es levantable por configuración** — un hallazgo importante contra la narrativa de "bloqueo incondicional".
2. **Owner-only gating** (`GATEWAY_OWNER_ONLY_CORE_TOOLS`): un segundo conjunto que solo se entrega si el emisor es el dueño verificado. Cubre las herramientas que usan *credenciales del servidor* (enviar mensajes por canales del operador, control del escritorio).
3. **Pipeline de políticas de herramientas multicapa** con una regla invariable: **`deny` siempre gana sobre `allow`**, y una capa nunca puede reabrir lo que otra cerró.
4. **Pairing-code para remitentes desconocidos**: `dmPolicy=pairing` por defecto. Un desconocido que escribe no llega al agente: recibe un código de 8 caracteres, se crea una solicitud pendiente con TTL de 1 hora y tope de 3 pendientes por cuenta, y el humano aprueba desde la CLI. El challenge se emite **antes de descifrar el payload del DM**.
5. **Sandbox por backend registrable** (`docker`, `podman`, `ssh`) con hardening Docker agresivo por defecto: `--read-only`, `--cap-drop ALL`, `--network none`, `--security-opt no-new-privileges` incondicional, tmpfs, límites de pids/memoria/cpu. Más un validador que rechaza bind-mounts peligrosos con **doble pasada anti-symlink**.
6. **Exec approvals**: modelo de confirmación humana con dos ejes ortogonales (`security` × `ask`) que derivan un `mode`, y decisiones `allow-once | allow-always | deny`. Es la pieza **más transferible a O.R.I.O.N.** — es literalmente una generalización del esquema verde/amarillo/rojo.
7. **Defensas transversales**: sentinels de secretos (AES-256-GCM proceso-local para que el LLM nunca vea el valor real), net-policy anti-SSRF con DNS pineado, y un audit ledger *metadata-only* encendido por defecto.

**La conclusión más útil para O.R.I.O.N.**: el valor de OpenClaw no está en el sandbox de Docker (eso es infraestructura estándar), está en **la disciplina de que el permiso se resuelve por superficie y por identidad del emisor, no por herramienta en abstracto**, y en que **el deny siempre gana**. Eso se puede copiar en Python en un par de días. El resto — registry de backends, sentinels criptográficos, pinned dispatchers — es sobre-ingeniería para el tamaño de O.R.I.O.N. hoy.

**Y la advertencia más importante**: varias de las protecciones tienen agujeros reales documentados en la sección 4. Si O.R.I.O.N. copia el patrón sin copiar los agujeros, sale ganando.

---

## 2. Inventario de mecanismos

### 2.1. Deny-list de herramientas por superficie HTTP

**Qué hace.** Define, en un único archivo compartido, qué herramientas son demasiado peligrosas para exponerse por la API HTTP del gateway (`POST /tools/invoke`). El comentario de cabecera explica la razón de centralizarlo: evitar que las restricciones del gateway y las auditorías de seguridad se "desincronicen" (*drift*).

**Dónde vivía.** `src/security/dangerous-tools.ts` (archivo completo, 72 líneas).

**Código transcrito literalmente** [VERIFICADO EN CÓDIGO — archivo leído completo]:

```ts
// Shared tool-risk constants.
// Keep these centralized so gateway HTTP restrictions and security audits don't drift.
import { AUTOMATIONS_TOOL_NAME } from "../agents/tools/automations-tool-name.js";

/**
 * Tools denied via Gateway HTTP `POST /tools/invoke` by default.
 * These are high-risk because they enable session orchestration, control-plane actions,
 * or interactive flows that don't make sense over a non-interactive HTTP surface.
 */
export const DEFAULT_GATEWAY_HTTP_TOOL_DENY = [
  // Direct command execution — immediate RCE surface
  "exec",
  // Arbitrary child process creation — immediate RCE surface
  "spawn",
  // Shell command execution — immediate RCE surface
  "shell",
  // Arbitrary file mutation on the host
  "fs_write",
  // Arbitrary file deletion on the host
  "fs_delete",
  // Arbitrary file move/rename on the host
  "fs_move",
  // Patch application can rewrite arbitrary files
  "apply_patch",
  // Agent-owned host terminal — interactive RCE surface
  "terminal",
  // Session orchestration — spawning agents remotely is RCE
  "sessions_spawn",
  // Cross-session injection — message injection across sessions
  "sessions_send",
  // External conversation discovery and delivery use server-held channel credentials
  "conversations_list",
  "conversations_send",
  "conversations_turn",
  // Persistent automation control plane — can create/update/remove scheduled runs
  AUTOMATIONS_TOOL_NAME,
  // Gateway config can expose secrets and host topology
  "gateway",
  // Node command relay can reach system.run on paired hosts
  "nodes",
  // Desktop control on a paired Mac (pointer/keyboard) and screen reads
  "computer",
  // Android AccessibilityService reads and cross-app UI control
  "mobile_ui",
  "openclaw",
] as const;

/**
 * Sensitive control-plane tools. `automations` can persist scheduled runs; `gateway`
 * exposes configuration and schema details even though its agent actions are read-only.
 */
export const GATEWAY_CONTROL_PLANE_TOOLS = [AUTOMATIONS_TOOL_NAME, "gateway"] as const;

/**
 * Core tools that require sender owner identity on Gateway-scoped surfaces.
 * `gateway.tools.allow` can remove the default HTTP deny only for owner/trusted-operator
 * callers; non-owner identity-bearing callers must not receive server-credential wrappers.
 */
export const GATEWAY_OWNER_ONLY_CORE_TOOLS = [
  ...GATEWAY_CONTROL_PLANE_TOOLS,
  "sessions",
  "screen",
  "terminal",
  "conversations_list",
  "conversations_send",
  "conversations_turn",
  "nodes",
  "computer",
  "mobile_ui",
  "openclaw",
] as const;
```

Nota: `AUTOMATIONS_TOOL_NAME` es una constante importada de `src/agents/tools/automations-tool-name.js`; su valor efectivo es `"automations"` (el código del gateway normaliza además el nombre legacy `"cron"`).

**Cómo se integraba — el mecanismo de aplicación exacto.** El archivo anterior solo declara constantes. La aplicación real está en `src/gateway/tool-resolution.ts` (505 líneas). Fragmentos clave [VERIFICADO EN CÓDIGO]:

```ts
type GatewayScopedToolSurface = "http" | "loopback";
```

```ts
const gatewayToolsCfg = params.cfg.gateway?.tools;
const defaultGatewayDeny =
  surface === "http"
    ? DEFAULT_GATEWAY_HTTP_TOOL_DENY.filter(
        // Config allow entries may use legacy tool names (e.g. "cron");
        // normalize both sides so they still lift the matching default deny.
        (name) =>
          !gatewayToolsCfg?.allow?.some(
            (allowed) => normalizeToolName(allowed) === normalizeToolName(name),
          ),
      )
    : [];
const ownerOnlyGatewayDeny =
  params.senderIsOwner === false || (surface === "http" && params.senderIsOwner !== true)
    ? [...GATEWAY_OWNER_ONLY_CORE_TOOLS]
    : [];
```

```ts
const gatewayDenySet = new Set([
  ...defaultGatewayDeny,
  ...ownerOnlyGatewayDeny,
  ...(Array.isArray(gatewayToolsCfg?.deny) ? gatewayToolsCfg.deny : []),
  ...excludedToolNames,
]);
const tools = policyFiltered.filter((tool) => !gatewayDenySet.has(tool.name));
```

Y una defensa adicional específica para la superficie de ejecución en nodos remotos:

```ts
const baseTools = nodeExecSurface
  ? openClawTools.filter((tool) => tool.name.trim().toLowerCase() !== "exec")
  : openClawTools;
```

**Puntos de lectura importantes de este mecanismo:**

- El deny por defecto **solo aplica cuando `surface === "http"`**. En `loopback` la lista es vacía: la premisa es que quien ya está en el loopback del host tiene, de hecho, el host.
- El filtro de `defaultGatewayDeny` **elimina de la deny-list toda herramienta que aparezca en `gateway.tools.allow`**. Es decir: la deny-list por defecto **no es incondicional**, es un default levantable por config. Ver sección 4.1.
- El `ownerOnlyGatewayDeny` es el que sí es duro sobre HTTP: sobre HTTP, si `senderIsOwner` no es exactamente `true`, se deniegan todas las owner-only. Pero ver sección 4.2 sobre quién cuenta como owner.

**Consumidores verificados de estas constantes** (búsqueda por grep, resultados literales):

- `src/agents/agent-tools.ts:833` — `options?.senderIsOwner === false ? [...GATEWAY_OWNER_ONLY_CORE_TOOLS] : []`
- `src/skills/runtime/tool-dispatch.ts:123` — `? { deny: [...GATEWAY_OWNER_ONLY_CORE_TOOLS] }`
- `src/security/audit-gateway-config.ts:100` — `const reenabledOverHttp = DEFAULT_GATEWAY_HTTP_TOOL_DENY.filter(...)` → hay un **auditor de configuración** que detecta y reporta cuándo el operador levantó denies por defecto. Buen patrón: si permitís que se relaje una defensa, al menos avisá que se relajó.
- `src/security/audit-extra.sync.ts:555`

---

### 2.2. Perfiles de herramientas y matcher de políticas

**Qué hace.** Agrupa las herramientas del core en cuatro perfiles nombrados que el operador elige desde la config/UI, y provee el matcher que decide si una herramienta concreta está permitida dado un conjunto de políticas.

**Dónde vivía.** `src/agents/tool-catalog.ts` y `src/agents/tool-policy-match.ts`. El tipo también está duplicado en `src/config/types.tools.ts:158`.

**Código transcrito** [VERIFICADO EN CÓDIGO]:

```ts
/** Built-in tool profile ids exposed in config and UI. */
export type ToolProfileId = "minimal" | "coding" | "messaging" | "full";

/** Allow/deny policy generated from a built-in tool profile. */
type ToolProfilePolicy = {
  allow?: string[];
  deny?: string[];
};

type CoreToolDefinition = {
  id: string;
  label: string;
  description: string;
  sectionId: string;
  profiles: ToolProfileId[];
  includeInOpenClawGroup?: boolean;
};

const CORE_TOOL_SECTION_ORDER: Array<{ id: string; label: string }> = [
  { id: "fs", label: "Files" },
  { id: "runtime", label: "Runtime" },
  { id: "web", label: "Web" },
  { id: "memory", label: "Memory" },
  { id: "sessions", label: "Sessions" },
  { id: "ui", label: "UI" },
  { id: "messaging", label: "Messaging" },
  { id: "automation", label: "Automation" },
  { id: "nodes", label: "Nodes" },
  { id: "agents", label: "Agents" },
  { id: "media", label: "Media" },
];

function listCoreToolIdsForProfile(profile: ToolProfileId): string[] {
  return CORE_TOOL_DEFINITIONS.filter((tool) => tool.profiles.includes(profile)).map(
    (tool) => tool.id,
  );
}

const CORE_TOOL_PROFILES: Record<ToolProfileId, ToolProfilePolicy> = {
  minimal: {
    allow: listCoreToolIdsForProfile("minimal"),
  },
  coding: {
    allow: [...listCoreToolIdsForProfile("coding"), "bundle-mcp"],
  },
  messaging: {
    allow: [...listCoreToolIdsForProfile("messaging"), "bundle-mcp"],
  },
  full: {
    allow: ["*"],
  },
};
```

El diseño relevante: **el perfil no es una lista escrita a mano**, se *deriva* de un catálogo donde cada herramienta declara a qué perfiles pertenece. Ejemplo del catálogo:

```ts
const CORE_TOOL_DEFINITIONS: CoreToolDefinition[] = [
  { id: "read",  label: "read",  description: "Read file contents",   sectionId: "fs",      profiles: ["coding"] },
  { id: "write", label: "write", description: "Create or overwrite files", sectionId: "fs", profiles: ["coding"] },
  { id: "edit",  label: "edit",  description: "Make precise edits",    sectionId: "fs",      profiles: ["coding"] },
  { id: "apply_patch", label: "apply_patch", description: "Patch files", sectionId: "fs",    profiles: ["coding"] },
  { id: "exec",  label: "exec",  description: EXEC_TOOL_DISPLAY_SUMMARY, sectionId: "runtime", profiles: ["coding"] },
  { id: "process", label: "process", description: PROCESS_TOOL_DISPLAY_SUMMARY, sectionId: "runtime", profiles: ["coding"] },
  { id: "code_execution", label: "code_execution", description: "Run sandboxed remote analysis",
    sectionId: "runtime", profiles: ["coding"], includeInOpenClawGroup: true },
  // ... (catálogo completo, ~40 herramientas)
];
```

Esto significa que **agregar una herramienta nueva obliga a decidir en qué perfiles entra**, en el mismo lugar donde se la declara. No hay forma de agregar una herramienta y "olvidarse" de clasificarla — quedaría fuera de todos los perfiles excepto `full`. Es un patrón *fail-closed* por construcción del catálogo, y es directamente aplicable a O.R.I.O.N.

**Nota sobre `full`.** `full: { allow: ["*"] }` — el perfil `full` es un comodín total. No hay perfil que sea "todo menos lo destructivo"; esa granularidad se delega a las capas de deny.

**El matcher** — `src/agents/tool-policy-match.ts` [VERIFICADO EN CÓDIGO]. Reglas efectivas:

- `deny` gana siempre sobre `allow`.
- `allow` vacío/ausente significa "permitir todo lo que no esté denegado" (no es fail-closed a nivel de matcher).
- Soporta patrones glob (`fs_*`, `*`).
- Caso especial: `apply_patch` queda cubierto por una política sobre `write` (para que denegar escritura no se pueda esquivar aplicando un patch).

---

### 2.3. Pairing-code para remitentes desconocidos

**Qué hace.** Cuando un número/usuario no reconocido escribe al bot (Telegram, WhatsApp, Discord…), el mensaje **no llega al agente**. En su lugar el sistema genera un código de 8 caracteres, registra una solicitud pendiente, y responde al desconocido con instrucciones. El dueño aprueba desde la CLI. Recién ahí el remitente entra en la allowlist persistente y sus mensajes se procesan.

**Dónde vivía.** `src/pairing/pairing-store.ts`, `src/pairing/pairing-challenge.ts`, `src/pairing/pairing-messages.ts`, `src/pairing/pairing-store.types.ts`, `src/security/dm-policy-shared.ts`, `src/channels/direct-dm-access.ts`.

#### 2.3.1. La decisión de admisión

`src/security/dm-policy-shared.ts` [VERIFICADO EN CÓDIGO — archivo leído completo]:

```ts
/** Admission decision returned by legacy DM/group access helpers. */
export type DmGroupAccessDecision = "allow" | "block" | "pairing";

/** Stable reason codes used by channel plugins, command auth, and diagnostics. */
export const DM_GROUP_ACCESS_REASON = {
  GROUP_POLICY_ALLOWED: "group_policy_allowed",
  GROUP_POLICY_DISABLED: "group_policy_disabled",
  GROUP_POLICY_EMPTY_ALLOWLIST: "group_policy_empty_allowlist",
  GROUP_POLICY_NOT_ALLOWLISTED: "group_policy_not_allowlisted",
  DM_POLICY_OPEN: "dm_policy_open",
  DM_POLICY_DISABLED: "dm_policy_disabled",
  DM_POLICY_ALLOWLISTED: "dm_policy_allowlisted",
  DM_POLICY_PAIRING_REQUIRED: "dm_policy_pairing_required",
  DM_POLICY_NOT_ALLOWLISTED: "dm_policy_not_allowlisted",
} as const;

type DmGroupAccessResult = {
  decision: DmGroupAccessDecision;
  reasonCode: DmGroupAccessReasonCode;
  reason: string;
};
```

La máquina de decisión (transcripción literal del núcleo):

```ts
function resolveLegacyDmGroupAccessDecision(params: {
  isGroup: boolean;
  dmPolicy?: string | null;
  groupPolicy?: string | null;
  effectiveAllowFrom: Array<string | number>;
  effectiveGroupAllowFrom: Array<string | number>;
  isSenderAllowed: (allowFrom: string[]) => boolean;
}): DmGroupAccessResult {
  const dmPolicy = params.dmPolicy ?? "pairing";
  const groupPolicy: GroupPolicy =
    params.groupPolicy === "open" || params.groupPolicy === "disabled"
      ? params.groupPolicy
      : "allowlist";
  const effectiveAllowFrom = normalizeStringEntries(params.effectiveAllowFrom);
  const effectiveGroupAllowFrom = normalizeStringEntries(params.effectiveGroupAllowFrom);

  if (params.isGroup) {
    const groupAccess = evaluateMatchedGroupAccessForPolicy({
      groupPolicy,
      allowlistConfigured: effectiveGroupAllowFrom.length > 0,
      allowlistMatched: params.isSenderAllowed(effectiveGroupAllowFrom),
    });
    if (groupAccess.allowed) {
      return dmGroupAccess("allow", DM_GROUP_ACCESS_REASON.GROUP_POLICY_ALLOWED,
        `groupPolicy=${groupPolicy}`);
    }
    switch (groupAccess.reason) {
      case "disabled":
      case "empty_allowlist":
      case "missing_match_input":
      case "not_allowlisted":
        return GROUP_ACCESS_RESULT[groupAccess.reason];
      case "allowed":
        return dmGroupAccess("allow", DM_GROUP_ACCESS_REASON.GROUP_POLICY_ALLOWED,
          `groupPolicy=${groupPolicy}`);
    }
  }

  if (dmPolicy === "disabled") {
    return dmGroupAccess("block", DM_GROUP_ACCESS_REASON.DM_POLICY_DISABLED, "dmPolicy=disabled");
  }
  if (dmPolicy === "open") {
    return resolveOpenDmAllowlistAccess({
      effectiveAllowFrom,
      isSenderAllowed: params.isSenderAllowed,
    });
  }
  return params.isSenderAllowed(effectiveAllowFrom)
    ? dmGroupAccess("allow", DM_GROUP_ACCESS_REASON.DM_POLICY_ALLOWLISTED,
        `dmPolicy=${dmPolicy} (allowlisted)`)
    : dmPolicy === "pairing"
      ? dmGroupAccess("pairing", DM_GROUP_ACCESS_REASON.DM_POLICY_PAIRING_REQUIRED,
          "dmPolicy=pairing (not allowlisted)")
      : dmGroupAccess("block", DM_GROUP_ACCESS_REASON.DM_POLICY_NOT_ALLOWLISTED,
          `dmPolicy=${dmPolicy} (not allowlisted)`);
}
```

Tres detalles de diseño que importan:

1. **El default es `"pairing"`**, no `"open"` ni `"disabled"`: `const dmPolicy = params.dmPolicy ?? "pairing";`. Fail-closed pero usable.
2. **Los grupos son más estrictos que los DMs**: el default de `groupPolicy` es `"allowlist"` y **no existe la decisión `pairing` para grupos** — un grupo no listado se bloquea, punto. Pairing es solo para DMs 1:1.
3. **Cada decisión lleva un `reasonCode` estable y legible por máquina.** No es solo "bloqueado": es `dm_policy_pairing_required` vs `group_policy_empty_allowlist`. Esto hace que los logs y los diagnósticos sean accionables sin leer código.

#### 2.3.2. Generación y almacenamiento de códigos

`src/pairing/pairing-store.ts` [VERIFICADO EN CÓDIGO — archivo leído completo]:

```ts
const PAIRING_CODE_LENGTH = 8;
const PAIRING_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const PAIRING_CODE_MAX_ATTEMPTS = 500;

export const CHANNEL_PAIRING_PENDING_TTL_MS = 60 * 60 * 1000;
export const CHANNEL_PAIRING_PENDING_MAX = 3;

export type PairingRequest = {
  id: string;
  code: string;
  createdAt: string;
  lastSeenAt: string;
  meta?: Record<string, string>;
};

function randomCode(): string {
  // Human-friendly: 8 chars, upper, no ambiguous chars (0O1I).
  let out = "";
  for (let i = 0; i < PAIRING_CODE_LENGTH; i++) {
    out += PAIRING_CODE_ALPHABET[crypto.randomInt(0, PAIRING_CODE_ALPHABET.length)];
  }
  return out;
}

function isExpired(entry: PairingRequest, nowMs: number): boolean {
  const createdAt = parseTimestamp(entry.createdAt);
  return createdAt === null || nowMs - createdAt > CHANNEL_PAIRING_PENDING_TTL_MS;
}

export function resolveChannelPairingRequestId(
  channel: PairingChannel,
  request: PairingRequest,
): string {
  const accountId = resolvePairingRequestAccountId(request);
  return crypto
    .createHash("sha256")
    .update(`${channel}\0${accountId}\0${request.id}\0${request.createdAt}`)
    .digest("base64url")
    .slice(0, 32);
}
```

Decisiones criptográficas y de UX relevantes:

- **Alfabeto sin caracteres ambiguos**: `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` — no hay `0`, `O`, `1`, `I`. 32 símbolos × 8 posiciones = 2^40 ≈ 1.1×10^12 combinaciones. Suficiente contra fuerza bruta *dado que* el TTL es 1 hora y hay tope de pendientes.
- **`crypto.randomInt`**, no `Math.random()`. Aleatoriedad criptográfica.
- **`parseTimestamp(...) === null` cuenta como expirado**: si el timestamp está corrupto o ausente, la entrada se considera vencida. Fail-closed correcto.
- **El `id` público de una solicitud es un hash truncado** (`sha256(channel\0accountId\0id\0createdAt)` → base64url, 32 chars). No se expone el identificador real del remitente en el flujo de aprobación por id.
- **`parseTimestamp` es defensivo por diseño**: la ausencia de dato no equivale a "válido".

**Contratos de tipos del store** — `src/pairing/pairing-store.types.ts` [VERIFICADO EN CÓDIGO, archivo completo]:

```ts
export type PairingChannel = ChannelId;

export type PairingRequestRecord = {
  id: string;
  code: string;
  createdAt: string;
  lastSeenAt: string;
  meta?: Record<string, string>;
};

/** Reads approved ids from a channel/account allowFrom store. */
export type ReadChannelAllowFromStoreForAccount = (params: {
  channel: PairingChannel;
  accountId: string;
  env?: NodeJS.ProcessEnv;
}) => Promise<string[]>;

/** Deletes one approved id from a channel/account allowFrom store. */
export type RemoveChannelAllowFromStoreEntryForAccount = (params: {
  channel: PairingChannel;
  entry: string | number;
  accountId: string;
  env?: NodeJS.ProcessEnv;
  pairingAdapter?: ChannelPairingAdapter;
}) => Promise<{ changed: boolean; allowFrom: string[] }>;

/** Creates or reuses a pending pairing request for one channel account. */
export type UpsertChannelPairingRequestForAccount = (params: {
  channel: PairingChannel;
  id: string | number;
  accountId: string;
  meta?: Record<string, string | undefined | null>;
  env?: NodeJS.ProcessEnv;
  pairingAdapter?: ChannelPairingAdapter;
}) => Promise<{ code: string; created: boolean }>;
```

**API pública del store** (funciones exportadas, verificadas):

| Función | Comportamiento clave |
|---|---|
| `readChannelAllowFromStore` | lee la allowlist persistente por canal+cuenta |
| `addChannelAllowFromStoreEntry` | agrega un remitente aprobado |
| `removeChannelAllowFromStoreEntry` | revoca |
| `listChannelPairingRequests` | lista pendientes no expiradas |
| `upsertChannelPairingRequest` | devuelve `{ code, created }`; **devuelve `{ code: "", created: false }` cuando se alcanzó `CHANNEL_PAIRING_PENDING_MAX`** |
| `approveChannelPairingCode` | compara `request.code.toUpperCase() === code` |
| `approveChannelPairingRequest` | aprueba por id opaco |
| `dismissChannelPairingRequest` | descarta sin aprobar |

Todo se ejecuta dentro de `runOpenClawStateWriteTransaction` sobre SQLite compartido — es decir, **las mutaciones del store son transaccionales**, no hay carrera entre dos mensajes simultáneos del mismo desconocido.

#### 2.3.3. Emisión del challenge

`src/pairing/pairing-challenge.ts` [VERIFICADO EN CÓDIGO — archivo completo]. Comportamiento:

- Llama a `upsertPairingRequest`.
- Si `!created` → retorna `{ created: false }` **y no vuelve a mandar el código**. Es decir: **un desconocido que insiste no recibe el código repetido**. Esto evita usar el bot como oráculo/amplificador de spam.
- Dispara el hook `channel_pairing_requested` de forma no bloqueante (para notificar al dueño).
- Envía la respuesta al remitente.

`src/pairing/pairing-messages.ts` — la respuesta que ve el desconocido:

```
OpenClaw: access not configured.
<idLine>
<code>
openclaw pairing approve <channel> <code>
```

Nótese que **el texto le dice al desconocido cuál es el comando exacto que el dueño debe ejecutar**. Es una decisión de UX deliberada: el desconocido reenvía ese mensaje al dueño y el dueño copia y pega.

#### 2.3.4. El detalle más importante: el challenge ocurre antes de descifrar

`src/channels/direct-dm-access.ts` — `createPreCryptoDirectDmAuthorizer`. Comentario literal del código [VERIFICADO EN CÓDIGO]:

```ts
// Pairing challenges happen before decrypting the DM payload; keep this branch
// side-effect free apart from the explicit reply hook.
```

Traducción del impacto: **el contenido del mensaje de un desconocido nunca se descifra, nunca se parsea, nunca toca el pipeline del agente, nunca entra al contexto del LLM.** La decisión de admisión se toma sobre metadatos de transporte (identidad del remitente), antes de tocar el payload. Esto es una frontera de confianza real y bien colocada — el prompt-injection de un desconocido no tiene superficie porque su texto nunca se lee.

Ese es el patrón más valioso de toda la sección de pairing y es el que O.R.I.O.N. debería copiar textualmente en REQ-007.

---

### 2.4. Sandboxing: registry de backends y hardening

#### 2.4.1. El registry

**Qué hace.** Permite registrar backends de sandbox en un registro **proceso-global** compartido vía `Symbol.for`, de modo que plugins cargados en el mismo proceso puedan aportar backends sin que el core los conozca.

**Dónde vivía.** `src/agents/sandbox/backend.ts` [VERIFICADO EN CÓDIGO]:

```ts
const SANDBOX_BACKEND_FACTORIES_STATE_KEY = Symbol.for("openclaw.sandboxBackendFactories");

export function registerSandboxBackend(
  id: string,
  registration: SandboxBackendRegistration,
): () => void { /* devuelve una función de des-registro */ }

export function getSandboxBackendFactory(id: string): SandboxBackendFactory | null
export function getSandboxBackendManager(id: string): SandboxBackendManager | null
export function requireSandboxBackendFactory(id: string): SandboxBackendFactory
// requireSandboxBackendFactory lanza un error con hint de configuración si el id no existe

registerSandboxBackend("docker", {
  factory: createDockerSandboxBackend,
  manager: dockerSandboxBackendManager,
  resolveWorkdir: ({ cfg }) => cfg.docker.workdir,
});
registerSandboxBackend("podman", {
  factory: createPodmanSandboxBackend,
  manager: podmanSandboxBackendManager,
  resolveWorkdir: ({ cfg }) => cfg.docker.workdir,
});
registerSandboxBackend("ssh", {
  factory: createSshSandboxBackend,
  manager: sshSandboxBackendManager,
  resolveWorkdir: ({ cfg, scopeKey }) =>
    resolveSshRuntimePaths(cfg.ssh.workspaceRoot, scopeKey).remoteWorkspaceDir,
});
```

> **HALLAZGO NEGATIVO.** Se pidió analizar backends "OpenShell" y "NVIDIA". **No existen en este repo.** Los únicos backends registrados en el core son `docker`, `podman` y `ssh`. Lo más cercano a NVIDIA es el paso del flag `--gpus` en `buildSandboxCreateArgs` (ver 2.4.3), que simplemente reenvía el valor configurado a Docker. Si existieron backends con esos nombres, fue en otra versión o como plugins externos no presentes aquí.

**Interfaces del backend** — `src/agents/sandbox/backend.types.ts` y `backend-handle.types.ts` [VERIFICADO EN CÓDIGO]:

```ts
type SandboxBackendManager = {
  describeRuntime(...): ...;
  removeRuntime(...): ...;
};

type CreateSandboxBackendParams = { /* cfg, scopeKey, workdir, ... */ };

type SandboxBackendHandle = {
  buildExecSpec(...): SandboxBackendExecSpec;
  runShellCommand(...): ...;
  createFsBridge(...): ...;
  validateWorkdir(...): ...;
  capabilities: { browser: boolean };
};

type SandboxBackendExecSpec = {
  argv: string[];
  env: Record<string, string>;
  stdinMode: ...;
  finalizeToken: ...;
};
```

El punto de diseño: **el backend no ejecuta, construye una `ExecSpec`**. La ejecución la hace el runtime genérico. Eso permite testear el hardening sin levantar Docker — los tests verifican el `argv` producido.

#### 2.4.2. Defaults de configuración del sandbox

`src/agents/sandbox/config.ts` [VERIFICADO EN CÓDIGO — estos son los defaults reales]:

```ts
readOnlyRoot: agentDocker?.readOnlyRoot ?? globalDocker?.readOnlyRoot ?? true,
tmpfs:        agentDocker?.tmpfs        ?? globalDocker?.tmpfs        ?? ["/tmp", "/var/tmp", "/run"],
network:      agentDocker?.network      ?? globalDocker?.network      ?? "none",
capDrop:      agentDocker?.capDrop      ?? globalDocker?.capDrop      ?? ["ALL"],
...
mode:            agentSandbox?.mode            ?? agent?.mode            ?? "off",
backend:         agentSandbox?.backend?.trim() || agent?.backend?.trim() || "docker",
workspaceAccess: agentSandbox?.workspaceAccess ?? agent?.workspaceAccess ?? "none",
```

Y la lista de banderas explícitamente marcadas como peligrosas:

```ts
export const DANGEROUS_SANDBOX_DOCKER_BOOLEAN_KEYS = [
  "dangerouslyAllowReservedContainerTargets",
  "dangerouslyAllowExternalBindSources",
  "dangerouslyAllowContainerNamespaceJoin",
] as const;
```

**Observación crítica**: `mode` por defecto es **`"off"`**. Los defaults de hardening (read-only, cap-drop ALL, network none) son excelentes **pero solo se aplican si alguien encendió el sandbox**. Ver sección 4.4.

El prefijo `dangerously` en los nombres de config es un buen patrón: hace imposible activar una degradación de seguridad sin escribir literalmente la palabra "dangerously" en el archivo de configuración. Es documentación forzada en el punto de uso.

#### 2.4.3. Hardening Docker — el `argv` real

`src/agents/sandbox/docker.ts`, función `buildSandboxCreateArgs` (líneas ~319–443) [VERIFICADO EN CÓDIGO]. Flags emitidos, en orden:

| Flag | Propósito |
|---|---|
| `--init` | reap de procesos zombie; PID 1 correcto |
| `--label openclaw.sandbox=1` | identificación para limpieza |
| `--label openclaw.sessionKey=...` | scoping por sesión |
| `--label openclaw.createdAtMs=...` | GC por edad |
| `--label openclaw.mountFormatVersion=...` | invalidación cuando cambia el formato de mounts |
| `--label openclaw.createArgsEpoch=...` | invalidación cuando cambia el builder de args |
| `--label openclaw.configHash=...` | recrear contenedor si cambió la config |
| `--read-only` | root filesystem inmutable |
| `--tmpfs <path>` | escritura efímera solo en `/tmp`, `/var/tmp`, `/run` |
| `--network <mode>` | por defecto `none` |
| `--user <uid:gid>` | no-root dentro del contenedor |
| `--env K=V` | tras `sanitizeExplicitSandboxEnvVars` + `markOpenClawExecEnv` |
| `--cap-drop ALL` | sin capabilities de Linux |
| `--security-opt no-new-privileges` | **incondicional** |
| `--security-opt seccomp=<perfil>` | perfil validado |
| `--security-opt apparmor=<perfil>` | perfil validado |
| `--dns`, `--add-host` | resolución controlada |
| `--pids-limit` | anti fork-bomb |
| `--memory`, `--memory-swap` | límite de RAM |
| `--cpus` | límite de CPU |
| `--gpus` | passthrough opcional de GPU |
| `--ulimit` | límites por proceso |
| `-v src:dst[:ro]` | bind mounts, ya validados |

Línea literal del único flag verdaderamente incondicional:

```ts
args.push("--security-opt", "no-new-privileges");
```

Y antes de construir nada, la función invoca `validateSandboxSecurity({...})` — **el hardening no es "los defaults son buenos", es "la validación corre siempre, aun con config custom"**. Esa es la diferencia entre un default seguro y una garantía.

Los labels de invalidación (`createArgsEpoch`, `configHash`, `mountFormatVersion`) merecen una mención aparte: resuelven un problema real y poco obvio — si cambiás el hardening en el código pero el contenedor ya existe, un contenedor viejo con hardening viejo seguiría corriendo. Los labels fuerzan la recreación.

#### 2.4.4. Validación de bind mounts, red y perfiles

`src/agents/sandbox/validate-sandbox-security.ts` [VERIFICADO EN CÓDIGO — archivo completo]:

```ts
const BLOCKED_HOST_PATHS = [
  "/etc",
  "/private/etc",
  "/proc",
  "/sys",
  "/dev",
  "/root",
  "/boot",
  "/run",
  "/var/run",
  "/private/var/run",
  "/var/run/docker.sock",
  "/private/var/run/docker.sock",
  "/run/docker.sock",
];

const BLOCKED_HOME_SUBPATHS = [
  ".aws",
  ".cargo",
  ".config",
  ".docker",
  ".gnupg",
  ".netrc",
  ".npm",
  ".ssh",
] as const;

const BLOCKED_SECCOMP_PROFILES = new Set(["unconfined"]);
const BLOCKED_APPARMOR_PROFILES = new Set(["unconfined"]);

const RESERVED_CONTAINER_TARGET_PATHS = ["/workspace", SANDBOX_AGENT_WORKSPACE_MOUNT];
```

`validateSandboxSecurity` compone cuatro validaciones: `validateBindMounts` + `validateNetworkMode` + `validateSeccompProfile` + `validateApparmorProfile`.

**El detalle técnico más fino de todo el subsistema — la doble pasada anti-symlink.** `validateBindMounts` evalúa cada bind **dos veces**:

1. **Pasada textual**: la ruta fuente tal cual está escrita, contra la denylist.
2. **Pasada por `realpath`**: resuelve symlinks **por ancestro existente** (porque la ruta completa puede no existir todavía) y vuelve a evaluar.

Sin la segunda pasada, un atacante (o un modelo confundido) podría crear `~/inocente -> /etc` y montar `~/inocente`, pasando la validación textual. La resolución por ancestro existente es necesaria porque `realpath` sobre una ruta inexistente falla; hay que subir hasta el ancestro que sí existe, resolverlo, y recomponer.

Además la validación:
- **Rechaza fuentes relativas** (no se puede montar `./algo`, la ambigüedad de cwd es una vulnerabilidad).
- **Rechaza montajes que *cubren* rutas bloqueadas**, no solo los que son exactamente una ruta bloqueada (montar `/` estaría cubriendo `/etc`).
- **Rechaza targets reservados dentro del contenedor** (`/workspace` y el mount del workspace del agente), salvo `dangerouslyAllowReservedContainerTargets`. Motivo: si el operador monta algo sobre `/workspace`, tapa el workspace real del agente y rompe las suposiciones del resto del sistema.

`src/agents/sandbox/network-mode.ts` [VERIFICADO EN CÓDIGO]: bloquea `host` **siempre** (compartir el namespace de red del host anula todo el aislamiento de red) y bloquea `container:*` salvo que esté `dangerouslyAllowContainerNamespaceJoin`.

#### 2.4.5. Sanitización de variables de entorno

`src/agents/sandbox/sanitize-env-vars.ts` [VERIFICADO EN CÓDIGO — archivo completo]:

```ts
const BLOCKED_ENV_VAR_PATTERNS = [
  // ... patrones específicos por proveedor ...
  /_?(API_KEY|TOKEN|PASSWORD|PRIVATE_KEY|SECRET)$/i,   // catch-all por sufijo
];

const ALLOWED_ENV_VAR_PATTERNS = [
  /^LANG$/,
  /^LC_/,
  /^PATH$/,
  /^HOME$/,
  /^USER$/,
  /^SHELL$/,
  /^TERM$/,
  /^TZ$/,
  /^NODE_ENV$/,
];

const MAX_ENV_VAR_VALUE_BYTES = 32768;
```

`validateEnvVarValue` rechaza: null bytes, valores que exceden `MAX_ENV_VAR_VALUE_BYTES`, y aplica una **heurística de detección de secretos por forma del valor**:

```ts
/^[A-Za-z0-9+/=]{80,}$/   // blob base64 largo → probable secreto, se bloquea
```

Es decir: **hay dos ejes de bloqueo — por nombre de la variable y por forma del valor**. Una variable llamada `MI_COSA` cuyo valor es un blob base64 de 200 caracteres se bloquea igual, porque el nombre no siempre delata al secreto.

> **ASIMETRÍA CRÍTICA [VERIFICADO EN CÓDIGO]** — ver sección 4.3. Hay dos funciones distintas:
> - `sanitizeEnvVars` — aplica bloqueo **por nombre Y por valor**. Se usa para la propagación *automática* del entorno del host.
> - `sanitizeExplicitSandboxEnvVars` — **solo valida el valor, NO aplica el bloqueo por nombre**. Y es la que usa `buildSandboxCreateArgs` para las variables puestas explícitamente en `sandbox.docker.env`.
>
> Consecuencia: poner `OPENAI_API_KEY` en `sandbox.docker.env` **la mete al contenedor**, aunque el patrón de nombre esté en la denylist. La decisión es defendible (el operador lo pidió explícitamente) pero no está documentada como tal y contradice la lectura ingenua de "hay una denylist de nombres".

#### 2.4.6. Credenciales SSH: cómo entran al sandbox remoto

`src/config/types.sandbox.ts` declara las credenciales como `SecretInput` (o sea, resolubles desde env/file/exec, no texto plano obligatorio):

```ts
identityData?: SecretInput;
certificateData?: SecretInput;
knownHostsData?: SecretInput;
```

`src/agents/sandbox/config.ts:220-226` las normaliza:

```ts
identityData: normalizeSecretInputString(agentSsh?.identityData ?? globalSsh?.identityData),
certificateData: normalizeSecretInputString(
  agentSsh?.certificateData ?? globalSsh?.certificateData,
),
knownHostsData: normalizeSecretInputString(
  agentSsh?.knownHostsData ?? globalSsh?.knownHostsData,
),
```

`src/agents/sandbox/secret-owner.ts:14` las marca como secretos para redacción:

```ts
const SSH_SECRET_KEYS = ["identityData", "certificateData", "knownHostsData"] as const;
```

Y `src/agents/sandbox/ssh.ts` las materializa en disco con permisos restrictivos antes de usarlas [VERIFICADO EN CÓDIGO]:

```ts
async function writeSecretMaterial(
  dir: string,
  filename: string,
  contents: string,
): Promise<string> {
  const pathname = path.join(dir, filename);
  await fs.writeFile(pathname, normalizeInlineSshMaterial(contents, filename), {
    encoding: "utf8",
    mode: 0o600,
  });
  await fs.chmod(pathname, 0o600);
  return pathname;
}
```

```ts
const materializedIdentity = settings.identityData
  ? await writeSecretMaterial(configDir, "identity", settings.identityData)
  : undefined;
const materializedCertificate = settings.certificateData
  ? await writeSecretMaterial(configDir, "certificate.pub", settings.certificateData)
  : undefined;
const materializedKnownHosts = settings.knownHostsData
  ? await writeSecretMaterial(configDir, "known_hosts", settings.knownHostsData)
  : undefined;
const identityFile = materializedIdentity ?? resolveOptionalLocalPath(settings.identityFile);
const certificateFile =
  materializedCertificate ?? resolveOptionalLocalPath(settings.certificateFile);
const knownHostsFile =
  materializedKnownHosts ?? resolveOptionalLocalPath(settings.knownHostsFile);
assertSshConfigLineValue(identityFile, "identityFile");
assertSshConfigLineValue(certificateFile, "certificateFile");
assertSshConfigLineValue(knownHostsFile, "knownHostsFile");
```

Y el archivo de config SSH generado:

```ts
const hostAlias = "openclaw-sandbox";
const configPath = path.join(configDir, "config");
const lines = [
  `Host ${hostAlias}`,
  `  HostName ${parsed.host}`,
  `  Port ${parsed.port}`,
  "  BatchMode yes",
  "  ConnectTimeout 5",
  "  ServerAliveInterval 15",
  "  ServerAliveCountMax 3",
  `  StrictHostKeyChecking ${settings.strictHostKeyChecking ? "yes" : "no"}`,
  // ...
];
```

Tres cosas dignas de copiar: `mode: 0o600` **más** un `chmod` explícito después (defensa contra umask raro); `BatchMode yes` (nunca pedir password interactivamente, falla en vez de colgarse); y `assertSshConfigLineValue` — **validación anti-inyección en el archivo de config SSH**, porque un valor con un salto de línea podría inyectar directivas SSH arbitrarias.

**Qué NO aísla el sandbox** [inferido del código, no de documentación]:
- No aísla al **gateway mismo**: `exec` con `host: "gateway"` corre fuera del sandbox por diseño.
- No aísla la **red del host cuando `network` no es `none`**: si el operador pone `bridge`, el contenedor tiene salida a internet y a la LAN del host.
- No aísla el **contenido del contexto del LLM**: el sandbox limita lo que el código puede hacer, no lo que el modelo puede leer del historial.
- No hay **límite de tiempo de ejecución** en el hardening del contenedor en sí (los timeouts viven en la capa de exec, no en el `argv` de Docker).

---

### 2.5. Exec approvals — el modelo de confirmación humana

**Qué hace.** Decide, para cada intento de ejecutar un comando, si se ejecuta, se bloquea, o se le pregunta al humano. Es el mecanismo más directamente transferible a O.R.I.O.N.

**Dónde vivía.** `src/infra/exec-approvals-core.ts` y `src/infra/exec-approvals-policy.ts`.

**Código transcrito** [VERIFICADO EN CÓDIGO]:

```ts
export type ExecHost = "sandbox" | "gateway" | "node";
export type ExecTarget = "auto" | ExecHost;

export type ExecSecurity = "deny" | "allowlist" | "full";
export type ExecAsk = "off" | "on-miss" | "always";
export type ExecMode = "deny" | "allowlist" | "ask" | "auto" | "full";

export type ExecApprovalDecision = "allow-once" | "allow-always" | "deny";

export function resolveExecModeFromPolicy(params: {
  security: ExecSecurity;
  ask: ExecAsk;
}): ExecMode { /* ... */ }

export function resolveExecPolicyForMode(mode: ExecMode): {
  security: ExecSecurity;
  ask: ExecAsk;
  autoReview: boolean;
} {
  // deny      → { security: "deny",      ask: "off",     autoReview: false }
  // allowlist → { security: "allowlist", ask: "off",     autoReview: false }
  // ask       → { security: "allowlist", ask: "on-miss", autoReview: false }
  // auto      → { security: "allowlist", ask: "on-miss", autoReview: true  }
  // full      → { security: "full",      ask: "off",     autoReview: false }
}
```

`src/infra/exec-approvals-policy.ts`:

```ts
export function requiresExecApproval(params: {
  ask: ExecAsk;
  security: ExecSecurity;
  analysisOk: boolean;
  allowlistSatisfied: boolean;
  durableApprovalSatisfied?: boolean;
}): boolean {
  if (params.ask === "always") return true;
  if (params.durableApprovalSatisfied === true) return false;
  return (
    params.ask === "on-miss" &&
    params.security === "allowlist" &&
    (!params.analysisOk || !params.allowlistSatisfied)
  );
}

export function minSecurity(a: ExecSecurity, b: ExecSecurity): ExecSecurity {
  const order = { deny: 0, allowlist: 1, full: 2 };
  // devuelve el más restrictivo de los dos
}
```

**Por qué este diseño es bueno y por qué importa para O.R.I.O.N.**

El insight central es que **"¿está permitido?" y "¿hay que preguntar?" son dos preguntas ortogonales**, no una escala. OpenClaw las separa en dos ejes (`security` × `ask`) y luego *deriva* un `mode` nombrado para la UI. Esto evita el error clásico de modelar la seguridad como una sola escala lineal donde "medio permitido" es ambiguo.

Comparado con verde/amarillo/rojo de O.R.I.O.N.:

| O.R.I.O.N. hoy | Equivalente en el modelo de dos ejes |
|---|---|
| verde | `security: full, ask: off` |
| amarillo | `security: allowlist, ask: on-miss` |
| rojo | `security: deny, ask: off` |

Pero el modelo de dos ejes permite expresar cosas que verde/amarillo/rojo no puede:
- **"Permitido pero siempre preguntame"** (`security: full, ask: always`) — para acciones que son legítimas pero querés ver pasar.
- **"Denegado sin excepción"** vs **"denegado salvo allowlist"** — hoy en O.R.I.O.N. ambos son "rojo".
- **`allow-always`** — la aprobación *durable*: el humano dice que sí una vez y no le vuelven a preguntar por ese comando. `durableApprovalSatisfied` corta el flujo de pregunta. Esto es lo que hace que un sistema con confirmaciones sea usable en vez de insoportable.
- **`minSecurity`** — cuando varias capas opinan, se toma la **más restrictiva**. Misma filosofía que "deny gana".

Nótese también `ExecHost = "sandbox" | "gateway" | "node"`: el permiso depende de **dónde** se ejecuta, no solo de **qué** se ejecuta. `exec` en el sandbox y `exec` en el host son la misma herramienta con riesgos completamente distintos.

**Detección de "drift" de política** — `src/security/exec-filesystem-policy.ts` [VERIFICADO EN CÓDIGO, archivo completo leído]:

```ts
const MUTATING_FS_TOOLS = ["write", "edit", "apply_patch"] as const;
const RUNTIME_TOOLS = ["exec", "process"] as const;

type ExecFilesystemPolicyDriftHit = {
  scopeLabel: string;
  runtimeTools: string[];
  disabledFilesystemTools: string[];
  sandboxMode: "off" | "non-main" | "all";
  sandboxWorkspaceAccess: "none" | "ro" | "rw";
  execHost: NonNullable<ExecToolConfig["host"]>;
};

function isExecFilesystemConstrained(params: {
  sandboxMode: "off" | "non-main" | "all";
  sandboxWorkspaceAccess: "none" | "ro" | "rw";
  execHost: NonNullable<ExecToolConfig["host"]>;
}): boolean {
  if (params.sandboxMode !== "all") {
    return false;
  }
  if (params.execHost === "gateway" || params.execHost === "node") {
    return false;
  }
  return params.sandboxWorkspaceAccess !== "rw";
}
```

Y el corazón del detector:

```ts
// Drift means every explicit mutating filesystem tool is disabled while a
// runtime path that can still mutate files remains allowed.
const disabledFilesystemTools = MUTATING_FS_TOOLS.filter(
  (tool) => !isToolAllowedByPolicies(tool, policies),
);
if (disabledFilesystemTools.length !== MUTATING_FS_TOOLS.length) {
  continue;
}
```

**Este es el mecanismo conceptualmente más interesante del repo entero**, y no tiene nada que ver con Docker ni con criptografía. Detecta **seguridad ilusoria**: el operador deshabilitó `write`, `edit` y `apply_patch` creyendo que el agente ya no puede modificar archivos — pero dejó `exec` habilitado, y `exec` puede hacer `echo x > archivo`. La política *parece* segura y no lo es.

El validador reconoce además la excepción legítima: si el sandbox está en modo `all`, el `exec` es local (no gateway/node), y el workspace no es de escritura, entonces deshabilitar las fs tools **sí** significa algo y no hay drift.

O.R.I.O.N. debería tener el equivalente: **un auditor que detecta cuando dos reglas de seguridad se contradicen en la práctica**. Es más valioso que agregar una regla más.

---

### 2.6. Secretos: sentinels y referencias

#### 2.6.1. Secret sentinels

**Qué hace.** Reemplaza los valores reales de los secretos por tokens opacos antes de que nada salga hacia el LLM o hacia logs. Solo el proceso que los generó puede resolverlos de vuelta, y solo en el momento de usarlos.

**Dónde vivía.** `src/secrets/sentinel.ts` [VERIFICADO EN CÓDIGO — archivo completo].

Estructura del token:

```
oc-sent-v2.<base64url(scope || nonce || ciphertext || tag)>.end
```

Parámetros criptográficos verificados:

| Elemento | Valor |
|---|---|
| Prefijo | `SECRET_SENTINEL_PREFIX = "oc-sent-v2."` |
| Sufijo | `.end` |
| Cifrado | `aes-256-gcm` |
| Nonce | 12 bytes, **derivado por HMAC** (no aleatorio) |
| Scope | 8 bytes = `sha256(label)` truncado |
| Tag GCM | 16 bytes |
| Clave | proceso-local, efímera |
| Kill switch | `OPENCLAW_SECRET_SENTINELS=off\|0\|false` |

Funciones exportadas:

```ts
mintSecretSentinel(...)        // valor real → token
resolveSecretSentinel(...)     // token → valor real (solo mismo proceso)
swapSecretSentinelsInText(...) // reemplaza todos los tokens de un texto por sus valores
```

**Por qué el nonce es derivado por HMAC y no aleatorio.** Es la decisión no obvia. Con nonce aleatorio, el mismo secreto cifrado dos veces daría dos tokens distintos, y el prompt del LLM tendría dos strings diferentes para la misma cosa — el modelo no podría razonar sobre "la API key" como una entidad estable, y el caché de prompts se rompería. Con nonce derivado determinísticamente, **el mismo secreto siempre produce el mismo sentinel dentro del proceso**.

El costo: se sacrifica la propiedad IND-CPA (un observador puede saber que dos sentinels iguales representan el mismo secreto). Es un trade-off aceptable **porque la clave es proceso-local y efímera** — el sentinel no es un mecanismo de almacenamiento, es un mecanismo de *no-exposición al modelo*. Fuera del proceso el token no vale nada.

**La propiedad real que da esto**: si el LLM alucina, si un log se filtra, si el historial de la conversación se persiste, o si el modelo intenta exfiltrar la key en su respuesta — lo que sale es `oc-sent-v2.xxxx.end`, inútil fuera del proceso vivo. La clave real solo existe en memoria y solo se sustituye en el último momento, justo antes de la llamada real.

#### 2.6.2. Gramática de SecretRef

`src/secrets/ref-contract.ts` [VERIFICADO EN CÓDIGO]:

```ts
export const SECRET_PROVIDER_ALIAS_PATTERN = /^[a-z][a-z0-9_-]{0,63}$/;
export const EXEC_SECRET_REF_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,255}$/;
export const SINGLE_VALUE_FILE_REF_ID = "value";
```

Fuentes soportadas: `env` (variable de entorno), `file` (archivo, con ids tipo JSON-pointer para extraer un campo de un JSON), `exec` (ejecutar un comando y tomar stdout — para integrar con `pass`, `1password`, `vault`, etc.).

El patrón útil: **la config nunca contiene el secreto, contiene una referencia declarativa a dónde está**. Ambos patrones son regex anclados con longitud máxima — validación estricta, no permisiva.

---

### 2.7. net-policy: defensa anti-SSRF

**Qué hace.** Impide que el agente (o una herramienta de fetch web manipulada por prompt-injection) alcance servicios internos: `localhost`, la red privada, y sobre todo los **endpoints de metadata de las nubes**, que entregan credenciales IAM a quien los consulte sin autenticación.

**Dónde vivía.** `packages/net-policy/src/ip.ts` (el paquete de reglas) y `src/infra/net/ssrf.ts` (786 líneas, el enforcement).

**Constantes transcritas** [VERIFICADO EN CÓDIGO]:

```ts
const BLOCKED_IPV4_SPECIAL_USE_RANGES = [
  // unspecified, broadcast, multicast, linkLocal, loopback,
  // carrierGradeNat, private, reserved
];

const BLOCKED_IPV6_SPECIAL_USE_RANGES = [
  // unspecified, loopback, linkLocal, uniqueLocal, multicast,
  // reserved, benchmarking, discard, orchid2
];

const CLOUD_METADATA_IP_ADDRESSES = new Set([
  "100.100.100.200",   // Alibaba Cloud metadata
  "fd00:ec2::254",     // AWS EC2 IMDS sobre IPv6
]);

const RFC2544_BENCHMARK_PREFIX = /* 198.18.0.0/15 */;
```

Funciones de parseo:

```ts
parseCanonicalIpAddress(...)     // rechaza formas IPv4 legacy: octal, hexadecimal, decimal-entero
extractEmbeddedIpv4FromIpv6(...) // detecta 169.254.169.254 escondido en ::ffff:169.254.169.254
isIpInCidr(...)
```

**Los tres detalles que separan una defensa SSRF real de una de juguete:**

1. **`parseCanonicalIpAddress` rechaza formas no canónicas.** `http://0177.0.0.1/` (octal), `http://0x7f000001/` (hex) y `http://2130706433/` (entero) son todos `127.0.0.1` para el resolver del sistema operativo pero no matchean un chequeo textual ingenuo. Rechazar en vez de normalizar es la decisión correcta: normalizar es un juego de whack-a-mole.

2. **`extractEmbeddedIpv4FromIpv6`.** IPv6 puede embeber IPv4 (`::ffff:a9fe:a9fe`). Sin esta función, la denylist IPv4 se esquiva escribiendo la dirección en formato IPv6.

3. **Pinned DNS + pinned dispatcher** — `createPinnedLookup` y `createPinnedDispatcher` en `src/infra/net/ssrf.ts`. Esta es la defensa contra **DNS rebinding**, el ataque que rompe casi todas las implementaciones de SSRF filtering: el atacante controla un dominio cuyo DNS devuelve una IP pública en la primera consulta (pasa la validación) y `169.254.169.254` en la segunda (la que hace la conexión real). La ventana entre "validar" y "conectar" es el agujero — TOCTOU clásico.

   La solución: resolver el DNS **una sola vez**, validar esa IP concreta, y **forzar a que la conexión use exactamente esa IP** (el dispatcher pineado), en vez de dejar que la librería HTTP resuelva de nuevo.

También expone `SsrFPolicy`, `assertHostnameAllowedWithPolicy` y `BLOCKED_HOSTNAMES`, más utilidades de **redacción de URLs sensibles** para que las URLs con tokens en el query-string no terminen en los logs.

---

### 2.8. Audit ledger

**Qué hace.** Registro append-only de qué corrió, quién lo pidió, y cómo terminó. **Metadata-only por contrato** — no guarda contenido de mensajes ni salidas de comandos por defecto.

**Dónde vivía.** `src/audit/audit-event-types.ts` y `src/audit/audit-config.ts`.

**Código transcrito** [VERIFICADO EN CÓDIGO]:

```ts
export const AUDIT_EVENT_SCHEMA_VERSION = 1;

export type AuditEventKind = "agent_run" | "tool_action" | "message";

export type AuditEventStatus =
  | "started"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "timed_out"
  | "blocked"
  | "unknown";
```

Campos de atribución: `actorType`, `actorId`, `agentId`, `sessionKey`, `runId`.

`src/audit/audit-config.ts` — el ledger está **encendido por defecto**, con este comentario literal en el código que justifica la decisión:

```
an audit trail enabled only after an incident cannot explain the incident
```

Y el modo de auditoría de contenido de mensajes es **opt-in separado**:

```ts
resolveAuditMessageMode(...) → "off" | "direct" | "all"
```

**Tres decisiones que O.R.I.O.N. debería copiar tal cual:**

1. **On por defecto.** La razón está en el comentario: una auditoría que se enciende después del incidente no puede explicar el incidente. El costo de tenerla siempre encendida es trivial; el costo de no tenerla el día que pasa algo es total.
2. **`"blocked"` es un estado de primera clase**, al mismo nivel que `succeeded` y `failed`. Sin esto no se puede responder la pregunta más importante de un sistema de permisos: *¿cuántas veces la política evitó algo?* Un sistema que solo audita lo que pasó no puede demostrar su propio valor ni detectar que alguien está sondeando los límites.
3. **Metadata-only por contrato, contenido opt-in.** Auditar el contenido de todos los mensajes convierte el log de auditoría en la base de datos más sensible del sistema — el auditor se vuelve el objetivo. Separar los dos ejes permite tener trazabilidad completa sin crear ese riesgo.

`AUDIT_EVENT_SCHEMA_VERSION = 1` versionado desde el día uno también es correcto: los eventos de auditoría sobreviven a varias versiones del código y hay que poder leer los viejos.

---

## 3. Decisiones de diseño deliberadas y por qué

### 3.1. Deny-list en vez de allow-list para la superficie HTTP

Parece contraintuitivo (la doctrina dice allow-list), pero es coherente si se lee bien el contexto:

- **Las herramientas del core son un conjunto conocido y cerrado**, no arbitrario. La deny-list se escribe una vez y se mantiene junto al catálogo.
- **La allow-list existe igual, en otra capa**: los perfiles (`minimal`/`coding`/`messaging`) son allow-lists. La deny-list HTTP es una capa *adicional* que aplica encima. No es "en vez de", es "además de".
- El problema real de la deny-list — que una herramienta nueva entra permitida por omisión — está mitigado por el auditor de `src/security/audit-gateway-config.ts` y por el hecho de que agregar una herramienta al catálogo obliga a clasificarla en perfiles.

**Sigue siendo una decisión discutible**, y el propio código lo sabe: por eso el comentario de cabecera insiste en centralizar las constantes "para que las restricciones del gateway y las auditorías no se desincronicen". Están gestionando un riesgo conocido, no negándolo.

### 3.2. Por qué el bloqueo es duro en algunas superficies y blando en otras

`defaultGatewayDeny` solo aplica a `surface === "http"`; en `loopback` es lista vacía. El razonamiento implícito: **quien puede hablar por el loopback del host ya está dentro del host**. Bloquearle `exec` sería teatro de seguridad — puede abrir una terminal.

Es honesto. La alternativa (bloquear en loopback también) daría una falsa sensación de frontera donde no hay ninguna.

En cambio `no-new-privileges` sí es incondicional, sin flag para desactivarlo, ni siquiera un `dangerously*`. Distinción correcta: se puede relajar lo que el operador podría lograr igual por otros medios; no se puede relajar lo que rompería la invariante fundamental del contenedor.

### 3.3. Pairing antes de descifrar

Ya explicado en 2.3.4, pero merece figurar como decisión de diseño explícita: **la frontera de confianza está antes del parser**, no después.

La mayoría de los sistemas ponen la autorización después de haber parseado el mensaje, porque necesitan saber qué pide para saber si puede. OpenClaw invierte eso: la identidad del remitente basta para decidir, y el contenido nunca se toca. Toda la superficie de ataque de parseo (deserialización, prompt-injection, bombas de descompresión) desaparece para remitentes no autorizados.

### 3.4. `deny` gana siempre, y `minSecurity` toma el mínimo

Aparece en tres lugares distintos con la misma filosofía: el matcher (`tool-policy-match.ts`), el pipeline de capas, y `minSecurity` en exec approvals.

La regla es: **ninguna capa puede reabrir lo que otra cerró**. Esto hace que agregar capas sea monotónicamente seguro — una capa nueva solo puede restringir, nunca ampliar. Sin esta invariante, un sistema de políticas multicapa se vuelve imposible de razonar: habría que conocer el orden exacto de aplicación para saber qué está permitido.

### 3.5. Prefijo `dangerously` en la config

`dangerouslyAllowReservedContainerTargets`, `dangerouslyAllowExternalBindSources`, `dangerouslyAllowContainerNamespaceJoin`.

No se puede degradar la seguridad sin escribir la palabra en el archivo de configuración. Es documentación forzada, imposible de hacer por accidente, y trivialmente greppeable en una auditoría (`grep -r dangerously config/`).

### 3.6. Defaults seguros pero sandbox apagado

`readOnlyRoot: true`, `network: "none"`, `capDrop: ["ALL"]` — pero `mode: "off"`.

La lectura caritativa: el sandbox requiere Docker instalado y funcionando; encenderlo por defecto rompería la instalación de la mayoría de los usuarios, que abandonarían. La postura es "si lo encendés, es seguro" en vez de "es seguro por defecto".

La lectura crítica está en 4.4.

---

## 4. Límites y debilidades reales

Esta sección es deliberadamente escéptica. Todo lo que sigue está verificado en código, con la evidencia citada.

### 4.1. La deny-list por defecto NO es incondicional — la config la levanta

**Afirmación implícita** (por el nombre `DEFAULT_GATEWAY_HTTP_TOOL_DENY` y el comentario "high-risk because they enable ... immediate RCE surface"): estas herramientas están bloqueadas sobre HTTP.

**Evidencia contraria** en `src/gateway/tool-resolution.ts`:

```ts
const defaultGatewayDeny =
  surface === "http"
    ? DEFAULT_GATEWAY_HTTP_TOOL_DENY.filter(
        (name) =>
          !gatewayToolsCfg?.allow?.some(
            (allowed) => normalizeToolName(allowed) === normalizeToolName(name),
          ),
      )
    : [];
```

Poner `gateway.tools.allow: ["exec"]` en la configuración **saca `exec` de la deny-list por defecto**. Es un default, no una garantía.

Esto está reconocido en el propio comentario de `GATEWAY_OWNER_ONLY_CORE_TOOLS` (`"gateway.tools.allow can remove the default HTTP deny only for owner/trusted-operator callers"`), y existe un auditor que lo reporta (`audit-gateway-config.ts:100`). Pero el nombre de la constante y sus comentarios ("immediate RCE surface") sugieren una dureza que el código no tiene. **Un lector apurado creería que `exec` no se puede exponer por HTTP. Se puede, con una línea de config.**

### 4.2. Los callers autenticados de `/tools/invoke` se tratan como owner — lo que neutraliza el owner-only deny

**[AFIRMACIÓN DE DOCUMENTACIÓN — `SECURITY.md`, sección "Operator Trust Model"]**: los callers autenticados de `POST /tools/invoke` **se tratan como owner senders**.

Esto significa que `ownerOnlyGatewayDeny`:

```ts
const ownerOnlyGatewayDeny =
  params.senderIsOwner === false || (surface === "http" && params.senderIsOwner !== true)
    ? [...GATEWAY_OWNER_ONLY_CORE_TOOLS]
    : [];
```

...**no se activa** para el caso que más importa, porque `senderIsOwner` es `true` para cualquiera que tenga el shared secret del gateway.

Consecuencia práctica: **quien tiene el token del gateway tiene `computer`, `nodes`, `conversations_send` y `gateway`** — o sea control del escritorio, relay de comandos a hosts pareados, envío de mensajes con las credenciales del operador, y lectura de la configuración. `GATEWAY_OWNER_ONLY_CORE_TOOLS` protege contra remitentes no-owner de *canales* (Telegram, etc.), no contra portadores del token HTTP.

`SECURITY.md` lo declara abiertamente (*"OpenClaw does not model one gateway as a multi-tenant, adversarial user boundary"*), así que no es un engaño — pero **la lista se llama "owner only" y sobre HTTP no filtra a nadie que esté autenticado**. El nombre promete más que el comportamiento.

### 4.3. `sanitizeExplicitSandboxEnvVars` no filtra por nombre

Verificado en 2.4.5. `BLOCKED_ENV_VAR_PATTERNS` incluye el catch-all `/_?(API_KEY|TOKEN|PASSWORD|PRIVATE_KEY|SECRET)$/i`, pero la función que usa `buildSandboxCreateArgs` para las env vars explícitas **solo valida el valor** (null bytes, longitud, heurística base64), no el nombre.

Poner `ANTHROPIC_API_KEY: "sk-ant-..."` en `sandbox.docker.env` la inyecta en el contenedor. La heurística de base64 podría atraparla si el valor es un blob largo de `[A-Za-z0-9+/=]{80,}`, pero una key con guiones o prefijos (`sk-ant-...`) **no matchea ese patrón** y pasa limpia.

Defendible como "el operador lo pidió explícitamente", pero la existencia de una denylist de nombres induce a creer que aplica en todos los caminos. No aplica.

### 4.4. `sandbox.mode` por defecto es `"off"` — no hay aislamiento por defecto

```ts
mode: agentSandbox?.mode ?? agent?.mode ?? "off",
```

Todo el hardening de la sección 2.4 — read-only root, cap-drop ALL, network none, validación de binds, doble pasada anti-symlink — **es código muerto en una instalación por defecto**. El agente ejecuta `exec` directamente en el host.

Un lector de `SECURITY.md` que ve la sección "Docker Security" con su lista de flags puede razonablemente concluir que su instalación está sandboxeada. No lo está salvo que lo haya encendido explícitamente.

### 4.5. El filtro final compara `tool.name` sin normalizar

```ts
const gatewayDenySet = new Set([...]);
const tools = policyFiltered.filter((tool) => !gatewayDenySet.has(tool.name));
```

El código se toma el trabajo de normalizar nombres al construir `defaultGatewayDeny` (`normalizeToolName(allowed) === normalizeToolName(name)`) — reconociendo explícitamente que los nombres tienen variantes legacy — pero **el filtro final usa `tool.name` crudo contra el set**.

Si alguna herramienta se registra con un nombre que difiere del canónico en mayúsculas, espacios o alias legacy, **no matchea el set y pasa el filtro**. No encontré una herramienta concreta que explote esto hoy, así que es un riesgo latente y no una vulnerabilidad demostrada — pero es exactamente el tipo de inconsistencia que se convierte en bug cuando alguien agrega un alias. La asimetría entre las dos comparaciones es la evidencia: si normalizar hacía falta arriba, hace falta abajo.

### 4.6. `allow` vacío significa "permitir todo lo no denegado"

En `tool-policy-match.ts`, una política sin `allow` no restringe nada. Esto significa que **el fail-safe del matcher es abierto, no cerrado**. La seguridad real depende de que alguna capa aporte un `deny` explícito o de que un perfil aporte el `allow`.

Es una elección de usabilidad razonable (si no, cada capa tendría que re-declarar todo lo permitido), pero implica que **un bug que haga que las políticas lleguen vacías resulta en "todo permitido"**, no en "nada permitido". La dirección del fallo es la peligrosa.

### 4.7. Lo que `SECURITY.md` declara explícitamente fuera de alcance

**[AFIRMACIÓN DE DOCUMENTACIÓN — leído en `SECURITY.md`]**. Citas literales relevantes:

- *"OpenClaw does not model one gateway as a multi-tenant, adversarial user boundary."*
- Sobre plugins: los plugins in-process **son parte de la TCB** (trusted computing base). Un plugin malicioso tiene todo.
- Sobre allowlists: *"allowlists primarily gate triggering... They do not guarantee universal supplemental-context redaction across every channel/surface."* → **las allowlists controlan quién dispara al agente, no garantizan que el contexto no se filtre.**
- Sobre el modelo: *"The model/agent is not a trusted principal."*
- Sobre exec approvals: *"Exec approvals ... are operator guardrails to reduce accidental command execution, not a multi-tenant authorization boundary."*
- Prompt-injection **sin cruce de frontera** está fuera de alcance.

Esto último es lo más importante para calibrar todo el documento: **el propio proyecto declara que los exec approvals son guardarraíles contra accidentes, no una frontera de autorización.** Cualquier lectura que los trate como control de seguridad contra un adversario está sobreinterpretando.

### 4.8. La brecha entre la narrativa y el código

Resumiendo el patrón que se repite en 4.1–4.5: **OpenClaw tiene buenos mecanismos con nombres que prometen más dureza de la que entregan.** `DEFAULT_GATEWAY_HTTP_TOOL_DENY` es levantable. `GATEWAY_OWNER_ONLY_CORE_TOOLS` no filtra al portador del token HTTP. La denylist de nombres de env no aplica en el camino explícito. El hardening de Docker no corre por defecto.

Ninguna de esas cosas es una mentira — `SECURITY.md` es notablemente honesto y su sección "Out of Scope" es larga y específica, lo cual habla bien del proyecto. Pero **los nombres de las constantes comunican certeza y el código entrega defaults**. Para O.R.I.O.N. la lección es directa: si una constante se llama `DENY`, que deniegue; si es un default levantable, que se llame `DEFAULT_..._RECOMMENDED` o que el mecanismo de levantarlo exija la palabra `dangerously`.

---

## 5. Traducción a O.R.I.O.N.

Contexto de O.R.I.O.N. para esta sección: proyecto Python en `c:\Users\johan\Documentos\Apps\Agent IA\agente_ia\`, con `core/security_manager.py` (niveles verde/amarillo/rojo, `require_confirmation()`, `audit.db`), skills que heredan de `skills/base_skill.py:BaseSkill`, y canales Telegram / Discord / Desktop. El objetivo declarado es **no copiar OpenClaw sino construir algo mejor**.

### 5.1. Modelo de permisos por acción → ADOPTAR con mejoras

**Qué adoptar:** la separación en dos ejes ortogonales de `exec-approvals-core.ts`.

Hoy O.R.I.O.N. tiene una escala lineal (verde/amarillo/rojo) que confunde dos preguntas distintas. Propuesta en Python:

```python
# core/security_manager.py
from enum import Enum

class Permiso(str, Enum):
    """¿Está permitido? — eje de autorización."""
    DENEGADO   = "denegado"     # nunca, sin excepción
    ALLOWLIST  = "allowlist"    # solo si matchea la allowlist
    PERMITIDO  = "permitido"    # siempre

class Confirmacion(str, Enum):
    """¿Hay que preguntarle al humano? — eje de interacción."""
    NUNCA       = "nunca"
    SI_NO_MATCH = "si_no_match"  # preguntar solo si no matchea la allowlist
    SIEMPRE     = "siempre"

class Decision(str, Enum):
    PERMITIR_UNA_VEZ  = "permitir_una_vez"
    PERMITIR_SIEMPRE  = "permitir_siempre"   # aprobación durable
    DENEGAR           = "denegar"
```

**Qué hacer DIFERENTE Y MEJOR que OpenClaw:**

1. **Aprobación durable desde el día uno.** OpenClaw tiene `allow-always` / `durableApprovalSatisfied`. O.R.I.O.N. hoy pregunta cada vez. Un sistema que pregunta siempre entrena al usuario a decir "sí" sin leer — la confirmación se vuelve ruido y deja de ser una defensa. `PERMITIR_SIEMPRE` debe persistir en `audit.db` con scope explícito (por skill + por firma normalizada de parámetros, nunca "para todo").

2. **El nivel debe depender del canal, no solo de la acción.** OpenClaw ya modela esto con `ExecHost` y `GatewayScopedToolSurface`, y las reglas de O.R.I.O.N. (`security-levels.md`) ya lo describen en prosa ("Voz: solo acciones Verdes"; "Telegram/Discord: Rojo bloqueado"). **Falta implementarlo como dato, no como prosa.** La resolución debe ser una tabla:

```python
# La misma acción tiene distinto nivel según por dónde entra.
MATRIZ_CANAL = {
    ("borrar_archivo", "desktop"):  (Permiso.ALLOWLIST, Confirmacion.SI_NO_MATCH),
    ("borrar_archivo", "telegram"): (Permiso.ALLOWLIST, Confirmacion.SIEMPRE),
    ("borrar_archivo", "voz"):      (Permiso.DENEGADO,  Confirmacion.NUNCA),
}
```

3. **`min_permiso()` — el mínimo gana, siempre.** Copiar `minSecurity` literalmente. Cuando varias capas opinan (global, por skill, por canal, por usuario), se toma la más restrictiva. Nunca la última que habló.

4. **Evitar el agujero 4.6: `allow` vacío debe ser fail-closed en O.R.I.O.N.** Si la resolución de política devuelve vacío o falla, el resultado es `DENEGADO`, no "permitido". Esto es una mejora directa sobre OpenClaw y cuesta una línea:

```python
def resolver_permiso(accion: str, canal: str) -> tuple[Permiso, Confirmacion]:
    """Resolver el permiso efectivo. Fail-closed: lo desconocido se deniega."""
    try:
        return MATRIZ_CANAL[(accion, canal)]
    except KeyError:
        logger.warning(f"accion sin clasificar: {accion} via {canal} — denegando")
        return (Permiso.DENEGADO, Confirmacion.NUNCA)
```

**Qué sería sobre-ingeniería copiar:** el `ExecMode` derivado (`deny|allowlist|ask|auto|full`). Es azúcar de UI para una config compleja; O.R.I.O.N. con los dos ejes directos y tres canales no lo necesita. Tampoco copiar `autoReview` (revisión automática del comando por otro LLM antes de ejecutar) — es caro, lento, y agrega una dependencia de red en el camino crítico de la seguridad.

### 5.2. Clasificación obligatoria en el catálogo → ADOPTAR, es la mejora de mayor ROI

El patrón de `CORE_TOOL_DEFINITIONS`, donde cada herramienta declara sus perfiles **en el mismo lugar donde se la define**, es directamente aplicable a `BaseSkill` y es probablemente el cambio más barato con más impacto.

**Qué hacer diferente y mejor:** OpenClaw lo hace con una lista central que hay que editar. O.R.I.O.N. puede hacerlo **obligatorio por el contrato de la clase base**, lo que es estructuralmente superior — es imposible olvidarse:

```python
# skills/base_skill.py
class BaseSkill(ABC):
    @property
    @abstractmethod
    def nivel_riesgo(self) -> Permiso:
        """Nivel de riesgo base de esta skill. Obligatorio."""
        ...

    @property
    def acciones_riesgosas(self) -> dict[str, Permiso]:
        """Override por acción cuando la skill hace cosas de distinto riesgo."""
        return {}
```

Con `@abstractmethod`, una skill nueva que no declara su nivel **no instancia**. Falla al arrancar, no en producción. OpenClaw no puede hacer esto porque su catálogo es una lista de datos; O.R.I.O.N. sí porque ya tiene una clase base con descubrimiento automático vía `skill_manager.py`.

Como este cambio rompe todas las skills existentes de golpe, conviene hacerlo con un período de gracia: `nivel_riesgo` con default `Permiso.DENEGADO` y un warning fuerte al cargar una skill sin declararlo, y recién después volverlo abstracto. Fail-closed durante la transición.

### 5.3. Detección de contradicciones de política → ADOPTAR el concepto, es lo más original del repo

`collectExecFilesystemPolicyDriftHits` es el mecanismo conceptualmente más valioso de OpenClaw y el que menos se parece a lo que la gente ya hace. Detecta **seguridad ilusoria**: reglas que parecen restringir y no restringen porque otra ruta las esquiva.

Para O.R.I.O.N., el drift equivalente y obvio:

> Si `code_execution_skill` está habilitada, **cualquier otra restricción sobre acciones de archivos es decorativa**, porque el código generado por la IA puede hacer `open(path, "w")` directamente.

Esto se debe implementar como un chequeo al arrancar, no como documentación:

```python
def auditar_contradicciones(config) -> list[str]:
    """Detectar reglas de seguridad que otra ruta vuelve inefectivas."""
    hallazgos = []
    if skill_habilitada("code_execution") and not sandbox_activo():
        restringidas = [s for s in skills_de_archivos() if not skill_habilitada(s)]
        if restringidas:
            hallazgos.append(
                f"code_execution sin sandbox anula la restriccion sobre {restringidas}"
            )
    return hallazgos
```

Y que O.R.I.O.N. lo **imprima al arrancar**, no que lo guarde en un log que nadie lee.

**Mejor que OpenClaw:** OpenClaw solo detecta un tipo de drift (fs vs exec) y lo hace en un auditor separado que hay que correr. O.R.I.O.N. debería correrlo en el arranque y hacerlo extensible (una lista de reglas de contradicción).

### 5.4. Pairing para remitentes desconocidos → ADOPTAR, simplificado

Ver sección 6.2 (REQ-007) para el detalle.

**Qué adoptar sin cambios:** la decisión ternaria `allow | block | pairing`; el default `pairing`; alfabeto sin caracteres ambiguos; `secrets.choice` (equivalente Python de `crypto.randomInt`); TTL; tope de pendientes; **no reenviar el código a quien insiste**; y sobre todo **decidir antes de procesar el contenido del mensaje**.

**Qué hacer diferente y mejor:**
- **Notificación push al dueño.** OpenClaw dispara un hook y espera que el dueño mire la CLI. O.R.I.O.N. ya tiene el canal Telegram del dueño abierto: mandarle el pedido de aprobación **con botones inline** (aprobar/rechazar) es estrictamente mejor UX y no cuesta casi nada.
- **Comparación en tiempo constante.** OpenClaw usa `request.code.toUpperCase() === code`. En Python usar `hmac.compare_digest` — es gratis y elimina la clase de timing attacks. (Con TTL de 1h y tope de 3 pendientes el riesgo real es bajo, pero el costo de hacerlo bien es cero.)
- **Registrar los rechazos en `audit.db`.** Saber que alguien intentó 40 veces es información de seguridad.

**Qué sería sobre-ingeniería:** el `resolveChannelPairingRequestId` con hash SHA-256 truncado a base64url. Es para no exponer el id real del remitente en una CLI multi-tenant. O.R.I.O.N. tiene un solo dueño que ya conoce a quién está aprobando — un id incremental alcanza.

### 5.5. Sandbox → ADOPTAR el concepto, NO el registry

Ver sección 6.1 (REQ-006).

**Qué adoptar:** el `argv` de hardening de Docker es la parte reusable. Es conocimiento operativo destilado que no hay que redescubrir:

```python
DOCKER_ARGS_SEGUROS = [
    "--init",
    "--read-only",
    "--network", "none",
    "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges",
    "--tmpfs", "/tmp",
    "--pids-limit", "128",
    "--memory", "512m",
    "--cpus", "1",
    "--user", "1000:1000",
]
```

Y las validaciones: denylist de rutas host, **doble pasada anti-symlink**, rechazo de fuentes relativas.

**Qué hacer diferente y mejor:**
1. **Encendido por defecto** — corrige directamente la debilidad 4.4. Si Docker no está disponible, `code_execution_skill` debe **fallar cerrada** con un mensaje claro ("instalá Docker o activá explícitamente el modo sin sandbox"), no degradar silenciosamente a ejecución en el host. Esta es la diferencia más importante entre O.R.I.O.N. y OpenClaw en materia de seguridad.
2. **Timeout de pared en el contenedor**, no solo en el subprocess. OpenClaw no pone límite de tiempo en el `argv` de Docker.
3. **Sanitizar env por nombre Y por valor en todos los caminos** — corrige 4.3. Una sola función, sin la asimetría explícita/automático.

**Qué sería sobre-ingeniería:**
- **El registry de backends con `Symbol.for`.** O.R.I.O.N. necesita **un** backend (Docker) y un fallback explícito. Un registro global de factories para tres backends es arquitectura para un problema que O.R.I.O.N. no tiene. Si algún día hace falta, un `dict[str, Callable]` a nivel de módulo alcanza.
- **El backend SSH.** No hay caso de uso.
- **Los labels de invalidación** (`configHash`, `createArgsEpoch`). Solo importan si se reusan contenedores entre ejecuciones. O.R.I.O.N. debería crear el contenedor, ejecutar, y destruirlo (`--rm`) — más simple y más seguro.
- **`podman`.** Un backend menos.

### 5.6. Audit ledger → ADOPTAR las tres decisiones

O.R.I.O.N. ya tiene `audit.db`. Las mejoras que vienen de OpenClaw:

1. **`bloqueado` como estado de primera clase.** Sin esto no se puede responder "¿cuántas veces la política me salvó?" ni detectar sondeo.
2. **Encendido por defecto**, con el argumento literal: una auditoría encendida después del incidente no puede explicar el incidente.
3. **Metadata-only por defecto, contenido opt-in.** Si `audit.db` guarda el contenido de todos los mensajes de Telegram, `audit.db` se convierte en el archivo más sensible del sistema.
4. **Versionar el esquema desde el día uno** (`AUDIT_EVENT_SCHEMA_VERSION = 1`).

Esquema sugerido, alineado con lo que ya existe:

```python
# Estados de un evento auditado.
ESTADOS = ("iniciado", "exitoso", "fallido", "cancelado", "timeout", "bloqueado")

# Campos de atribución mínimos.
# quien (usuario), canal, skill, accion, nivel_resuelto,
# confirmacion_pedida, decision_humana, estado, timestamp
```

### 5.7. Secretos → ADOPTAR el concepto de sentinel, MUY simplificado

**El problema es real y O.R.I.O.N. lo tiene hoy:** si una skill lee una API key y la devuelve en su output, esa key entra en el contexto del LLM y queda en el historial.

**Qué hacer diferente y mucho más simple:** OpenClaw usa AES-256-GCM con nonce derivado por HMAC. Para O.R.I.O.N. eso es sobre-ingeniería total. La propiedad que hace falta — "el LLM nunca ve el valor real" — se obtiene con un diccionario en memoria:

```python
# core/secretos.py
import secrets as _secrets

_TOKENS: dict[str, str] = {}          # token -> valor real
_INVERSO: dict[str, str] = {}         # valor real -> token (para estabilidad)

def enmascarar(valor: str) -> str:
    """Devolver un token opaco estable para un secreto."""
    if valor in _INVERSO:
        return _INVERSO[valor]        # mismo secreto -> mismo token (como el nonce HMAC)
    token = f"orion-sec-{_secrets.token_urlsafe(12)}"
    _TOKENS[token] = valor
    _INVERSO[valor] = token
    return token

def revelar(texto: str) -> str:
    """Sustituir tokens por valores reales. Solo en el borde, justo antes de usar."""
    for token, valor in _TOKENS.items():
        texto = texto.replace(token, valor)
    return texto
```

Esto da la misma propiedad de seguridad (el valor real no está en lo que ve el modelo, y el token no vale nada fuera del proceso) sin criptografía. La clave de OpenClaw también es proceso-local y efímera — el AES no aporta nada que el diccionario no aporte. **La ganancia de seguridad del cifrado ahí es cero; la complejidad es alta.** Es un buen ejemplo de dónde no copiar.

**Qué sí adoptar de la parte de secretos:** la gramática de `SecretRef` — que la config nunca contenga el secreto sino una referencia (`env:MI_KEY`, `file:/ruta#campo`). O.R.I.O.N. ya usa `.env`, así que está a mitad de camino.

### 5.8. net-policy / SSRF → ADOPTAR solo si hay fetch de URLs arbitrarias

**Aplica únicamente si alguna skill hace fetch de una URL que el LLM o el usuario proveen.** Si O.R.I.O.N. solo llama a APIs con URL fija (Claude, DeepSeek, clima), esto es innecesario.

Si aplica, los tres puntos que importan y que casi todas las implementaciones caseras erran:
1. **Rechazar formas de IP no canónicas** (octal, hex, decimal-entero), no normalizarlas.
2. **Detectar IPv4 embebido en IPv6.**
3. **Resolver DNS una vez y conectar a esa IP** (anti DNS-rebinding). En Python: resolver con `socket.getaddrinfo`, validar, y conectar por IP con el `Host` header correcto.

Bloquear como mínimo: `127.0.0.0/8`, `10/8`, `172.16/12`, `192.168/16`, `169.254/16` (¡metadata!), `::1`, `fd00::/8`.

**Sobre-ingeniería a evitar:** el `createPinnedDispatcher` completo con todo el manejo de undici. En Python, si hace falta, es un `HTTPAdapter` custom de `requests` de ~20 líneas.

### 5.9. Tabla resumen de decisiones

| Mecanismo OpenClaw | O.R.I.O.N. | Prioridad |
|---|---|---|
| Dos ejes `security` × `ask` | **Adoptar**, reemplaza verde/amarillo/rojo lineal | Alta |
| Aprobación durable (`allow-always`) | **Adoptar** — sin esto las confirmaciones se vuelven ruido | Alta |
| Permiso resuelto por canal | **Adoptar** — ya está en las reglas, falta implementarlo como dato | Alta |
| `nivel_riesgo` obligatorio en `BaseSkill` | **Adoptar y mejorar** con `@abstractmethod` | Alta |
| Fail-closed en política vacía | **Mejorar sobre OpenClaw** (ellos fallan abierto) | Alta |
| Detección de contradicciones de política | **Adoptar el concepto** — lo más original del repo | Alta |
| Audit con estado `bloqueado`, on por defecto | **Adoptar** | Alta |
| Pairing ternario `allow/block/pairing` | **Adoptar** simplificado | Alta (REQ-007) |
| Decidir antes de procesar el contenido | **Adoptar** — frontera de confianza correcta | Alta (REQ-007) |
| Hardening Docker (`argv`) | **Adoptar**, encendido por defecto | Alta (REQ-006) |
| Validación de binds con doble pasada symlink | **Adoptar** si hay binds | Media (REQ-006) |
| Sanitizar env por nombre y valor | **Adoptar sin la asimetría** de OpenClaw | Media |
| Prefijo `dangerously` en config | **Adoptar** — documentación forzada gratis | Media |
| Sentinels de secretos | **Adoptar el concepto**, sin AES | Media |
| SecretRef declarativo | Parcial (ya hay `.env`) | Baja |
| net-policy / SSRF | Solo si hay fetch de URLs arbitrarias | Condicional |
| Registry de backends (`Symbol.for`) | **NO copiar** — sobre-ingeniería | — |
| Backend SSH / podman | **NO copiar** | — |
| Labels de invalidación de contenedor | **NO copiar** — usar `--rm` | — |
| AES-256-GCM en sentinels | **NO copiar** — dict en memoria da lo mismo | — |
| `ExecMode` derivado de 5 valores | **NO copiar** — azúcar de UI | — |
| `autoReview` con LLM | **NO copiar** — caro, lento, en camino crítico | — |

---

## 6. Alimentación concreta de REQs futuros

### 6.1. REQ-006 — Sandboxing real para `skills/code_execution_skill.py`

**Estado actual del problema.** `code_execution_skill.py` ejecuta código generado por IA en un subprocess **sin aislamiento alguno**. El código tiene acceso completo al filesystem del usuario, a la red, a las variables de entorno del proceso (incluidas las API keys), y puede iniciar procesos arbitrarios. Según `security-levels.md`, "ejecutar código generado por IA" ya está clasificado como 🟡 Amarillo (requiere confirmación) — pero **la confirmación protege contra la ejecución accidental, no contra lo que el código hace una vez que corre**. Son defensas para problemas distintos y hoy solo existe una.

**Qué patrón de OpenClaw aplica.**

1. **El `argv` de hardening** de `buildSandboxCreateArgs` (sección 2.4.3). Es la parte directamente copiable — conocimiento operativo destilado sobre qué flags de Docker importan.
2. **El patrón "construir spec, no ejecutar"** de `SandboxBackendExecSpec`. Permite testear el hardening sin Docker: el test verifica el `argv` producido. Muy valioso para pytest, porque las reglas de testing de O.R.I.O.N. prohíben tests que dependan de infraestructura externa.
3. **`validateSandboxSecurity` corriendo siempre**, no solo con la config por defecto (sección 2.4.4).
4. **`sanitize_env`** — que la API key de Claude no entre al contenedor (sección 2.4.5), corrigiendo la asimetría de 4.3.

**Qué hay que decidir.**

| Decisión | Opciones | Recomendación |
|---|---|---|
| ¿Docker obligatorio? | (a) requerir Docker, fallar cerrado sin él; (b) degradar a subprocess con warning; (c) `RestrictedPython` como fallback | **(a)**. La opción (b) es la debilidad 4.4 de OpenClaw reproducida. Si no hay aislamiento, no hay ejecución de código. |
| ¿Red en el contenedor? | `none` / `bridge` | `none` por defecto. Si una skill necesita red, que se pida explícitamente y suba a Rojo. |
| ¿Cómo entra y sale el código? | bind mount de un dir temporal / stdin / `docker cp` | **stdin + stdout**, sin bind mounts. Elimina de un plumazo toda la superficie de validación de binds (2.4.4) — la parte más difícil de hacer bien. |
| ¿Persistencia entre ejecuciones? | contenedor reusado / `--rm` | `--rm`. Sin estado no hay escalada entre ejecuciones ni necesidad de labels de invalidación. |
| ¿Timeout? | subprocess timeout / `--stop-timeout` / ambos | Ambos. Timeout de pared en el runner Python **y** límite en el contenedor. |
| ¿Qué imagen base? | `python:3.12-slim` / imagen propia mínima | `python:3.12-slim` fijada por **digest**, no por tag (un tag es mutable). |
| ¿Qué pasa con Windows? | Docker Desktop / WSL2 | Verificar temprano. O.R.I.O.N. corre en Windows 11; Docker Desktop funciona pero los bind mounts de rutas Windows tienen semántica propia — otra razón para elegir stdin/stdout. |

**Riesgos.**

- **Riesgo alto — degradación silenciosa.** Si el sandbox falla al iniciar (Docker parado, imagen no bajada) y el código cae al camino viejo sin aislamiento, el REQ **empeora** la seguridad: el usuario cree que está protegido y no lo está. **Requisito de QA: el fallo del sandbox debe ser fatal para la skill, y debe haber un test que lo verifique.**
- **Riesgo medio — fuga de env.** El contenedor no debe heredar el entorno del proceso padre. Docker no lo hereda por defecto, pero cualquier `--env-file` o pasaje explícito lo rompe. Test explícito: ejecutar código que imprima `os.environ` y verificar que no aparece ninguna key.
- **Riesgo medio — DoS local.** Sin `--pids-limit` y `--memory` una fork-bomb generada por la IA cuelga la máquina del usuario. Estos flags no son opcionales.
- **Riesgo medio — falsa sensación de aislamiento total.** El sandbox no protege contra un código que exfiltra por stdout algo que el modelo después usa. El aislamiento es de *ejecución*, no de *información*.
- **Riesgo bajo — primer arranque lento.** La primera ejecución baja la imagen (~50MB). Precalentar o avisar.

**Criterio de aceptación sugerido (testeable, en línea con `testing.md`):**
- Código que intenta `open("C:/Users/johan/...", "w")` falla.
- Código que intenta `socket.create_connection(("1.1.1.1", 80))` falla.
- Código que imprime `os.environ` no muestra ninguna variable cuyo nombre matchee la denylist.
- Un `while True: pass` termina por timeout y no cuelga a O.R.I.O.N.
- Un `os.fork()` en bucle no cuelga la máquina.
- Con Docker no disponible, la skill devuelve error explícito y **no ejecuta nada**.
- El builder del `argv` es una función pura testeable sin Docker (patrón `ExecSpec`).

### 6.2. REQ-007 — Pairing-code para remitentes desconocidos

**Estado actual del problema.** Los bots de Telegram/Discord de O.R.I.O.N. reciben mensajes de cualquiera que conozca el handle del bot. Sin allowlist con pairing, un desconocido puede interactuar con el agente — y aunque las acciones Amarillas pidan confirmación, **el mensaje del desconocido ya entró al contexto del LLM**, que es exactamente la superficie de prompt-injection.

**Qué patrón de OpenClaw aplica.**

1. **La decisión ternaria `allow | block | pairing`** con `reasonCode` estable (sección 2.3.1). El `reasonCode` no es cosmético: hace los logs accionables sin leer código.
2. **El default `pairing`** — fail-closed pero usable, en vez de `open` (inseguro) o `disabled` (inútil).
3. **Grupos ≠ DMs**: pairing solo para DMs 1:1; en grupos, allowlist estricta sin pairing.
4. **`{ code: "", created: false }` cuando se alcanza el tope**, y **no reenviar el código a quien insiste** (sección 2.3.3). Evita usar el bot como amplificador de spam.
5. **[EL MÁS IMPORTANTE] Decidir antes de procesar el contenido** (sección 2.3.4). El mensaje del desconocido nunca debe llegar al clasificador de intents, al `dispatcher`, ni a la memoria semántica.

**Diseño concreto sugerido para O.R.I.O.N.:**

```python
# core/pairing.py
import hmac, secrets
from datetime import datetime, timedelta

ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sin 0 O 1 I
LARGO_CODIGO = 8
TTL = timedelta(hours=1)
MAX_PENDIENTES = 3

def generar_codigo() -> str:
    """Generar un codigo de pairing legible por humanos."""
    return "".join(secrets.choice(ALFABETO) for _ in range(LARGO_CODIGO))

def verificar_codigo(esperado: str, recibido: str) -> bool:
    """Comparar codigos en tiempo constante."""
    return hmac.compare_digest(esperado.upper(), recibido.strip().upper())
```

Y el punto de integración crítico, **antes del dispatcher**:

```python
# En el handler del canal, ANTES de tocar el texto del mensaje.
decision = resolver_acceso(canal, remitente_id)
if decision == "pairing":
    codigo, creado = upsert_solicitud(canal, remitente_id)
    if creado:
        notificar_al_dueno(canal, remitente_id, codigo)   # push a Telegram del dueño
        responder(mensaje_pairing(codigo))
    return          # el texto del mensaje NUNCA se lee
if decision == "block":
    registrar_auditoria("bloqueado", canal, remitente_id)
    return
# solo acá se procesa el contenido
```

**Qué hay que decidir.**

| Decisión | Opciones | Recomendación |
|---|---|---|
| ¿Dónde se guarda la allowlist? | `memory.db` / `audit.db` / tabla nueva | Tabla nueva en la DB de config. **No** en `memory.db` — la allowlist no es memoria conversacional. |
| ¿Cómo aprueba el dueño? | CLI / botón inline en Telegram / ambos | **Botón inline en Telegram** como principal (mejor que OpenClaw), CLI como respaldo. |
| ¿El dueño puede iniciarse solo? | bootstrap por `.env` / primer mensaje gana | **`.env`**. "Primer mensaje gana" es una carrera explotable si el bot arranca antes de que el dueño escriba. |
| ¿Discord y Telegram comparten allowlist? | sí / no | **No.** El id de Telegram y el de Discord son espacios distintos; mezclarlos permite escalada cruzada. |
| ¿Qué le decimos al desconocido? | mensaje completo con el comando / mensaje mínimo | **Mensaje mínimo** con el código. OpenClaw le dice al desconocido el comando exacto de aprobación, lo cual filtra que existe una CLI. Con aprobación por botón, no hace falta. |
| ¿Rate limit? | por remitente / global | Ambos. `MAX_PENDIENTES` es por remitente; conviene además un tope global de solicitudes por hora. |
| ¿Se revoca? | comando `/revocar` | Sí, desde el arranque. Agregar sin poder quitar es una trampa. |

**Riesgos.**

- **Riesgo alto — el pairing se aplica después de procesar el mensaje.** Es el error de implementación más probable y anula el 90% del beneficio: si el texto ya pasó por el clasificador o quedó en la memoria semántica, el prompt-injection ya ocurrió. **Requisito de QA: un test que verifique que un mensaje de un remitente desconocido no genera ninguna entrada en `memory.db` ni invoca al dispatcher.**
- **Riesgo medio — lockout del dueño.** Si el bootstrap desde `.env` falla (id mal escrito, cambio de cuenta), el dueño queda afuera de su propio bot. Debe haber una salida por CLI local que no dependa del canal.
- **Riesgo medio — enumeración.** Un atacante que prueba códigos. Mitigado por el espacio de 32^8 y el TTL, pero **hay que auditar los intentos fallidos** — 40 intentos en un minuto es una señal.
- **Riesgo bajo — spam de solicitudes pendientes.** Mitigado por `MAX_PENDIENTES = 3` y por no reenviar el código.
- **Riesgo bajo — fricción.** El dueño puede querer que un amigo pruebe el bot. El flujo de aprobación tiene que ser de dos clicks, no de leer documentación.

---

## Apéndice A — Índice de rutas originales citadas

Todas dentro de `openclaw-main/` (carpeta ya eliminada; se listan como referencia histórica).

| Ruta original | Contenido relevante |
|---|---|
| `src/security/dangerous-tools.ts` | `DEFAULT_GATEWAY_HTTP_TOOL_DENY`, `GATEWAY_CONTROL_PLANE_TOOLS`, `GATEWAY_OWNER_ONLY_CORE_TOOLS` |
| `src/gateway/tool-resolution.ts` | aplicación del deny por superficie, `gatewayDenySet` |
| `src/security/audit-gateway-config.ts` | auditor que reporta denies levantados |
| `src/security/audit-extra.sync.ts` | consumidor adicional del deny list |
| `src/security/dm-policy-shared.ts` | `DmGroupAccessDecision`, `DM_GROUP_ACCESS_REASON` |
| `src/security/exec-filesystem-policy.ts` | detección de drift fs/exec |
| `src/pairing/pairing-store.ts` | códigos, TTL, tope, store SQLite |
| `src/pairing/pairing-store.types.ts` | contratos de tipos del store |
| `src/pairing/pairing-challenge.ts` | emisión del challenge |
| `src/pairing/pairing-messages.ts` | texto de respuesta al desconocido |
| `src/channels/direct-dm-access.ts` | `createPreCryptoDirectDmAuthorizer` |
| `src/agents/tool-catalog.ts` | `ToolProfileId`, `CORE_TOOL_DEFINITIONS`, `CORE_TOOL_PROFILES` |
| `src/agents/tool-policy-match.ts` | matcher, deny gana |
| `src/agents/agent-tools.ts` | owner-only en la capa de agente |
| `src/skills/runtime/tool-dispatch.ts` | owner-only en skills |
| `src/agents/sandbox/backend.ts` | registry, `registerSandboxBackend` |
| `src/agents/sandbox/backend.types.ts` | `SandboxBackendManager`, `CreateSandboxBackendParams` |
| `src/agents/sandbox/backend-handle.types.ts` | `SandboxBackendHandle`, `SandboxBackendExecSpec` |
| `src/agents/sandbox/config.ts` | defaults, `DANGEROUS_SANDBOX_DOCKER_BOOLEAN_KEYS` |
| `src/agents/sandbox/docker.ts` | `buildSandboxCreateArgs` |
| `src/agents/sandbox/validate-sandbox-security.ts` | denylists de rutas, doble pasada symlink |
| `src/agents/sandbox/network-mode.ts` | bloqueo de `host` y `container:*` |
| `src/agents/sandbox/sanitize-env-vars.ts` | denylist de nombres, heurística de valores |
| `src/agents/sandbox/ssh.ts` | `writeSecretMaterial`, config SSH generada |
| `src/agents/sandbox/secret-owner.ts` | `SSH_SECRET_KEYS` |
| `src/config/types.sandbox.ts` | `identityData`/`certificateData`/`knownHostsData` como `SecretInput` |
| `src/infra/exec-approvals-core.ts` | `ExecSecurity`, `ExecAsk`, `ExecMode`, decisiones |
| `src/infra/exec-approvals-policy.ts` | `requiresExecApproval`, `minSecurity` |
| `src/secrets/sentinel.ts` | AES-256-GCM, `oc-sent-v2.` |
| `src/secrets/ref-contract.ts` | gramática de SecretRef |
| `packages/net-policy/src/ip.ts` | rangos bloqueados, IPs de metadata, parseo canónico |
| `src/infra/net/ssrf.ts` | `createPinnedLookup`, `createPinnedDispatcher` |
| `src/audit/audit-event-types.ts` | esquema de eventos |
| `src/audit/audit-config.ts` | ledger on por defecto |
| `SECURITY.md` | modelo de confianza, out of scope |
| `security/README.md` | rulepack OpenGrep |

## Apéndice B — Hallazgos negativos

Cosas que se buscaron y **no existen** en el repo:

1. **Backends de sandbox "OpenShell" y "NVIDIA".** No existen. Solo `docker`, `podman` y `ssh` en `src/agents/sandbox/backend.ts`. Lo más cercano a NVIDIA es el paso del flag `--gpus` en `buildSandboxCreateArgs`.
2. **Un modelo de permisos en `src/tools/**`.** `src/tools/` contiene **únicamente `types.ts`**. El modelo real de permisos vive disperso en `src/agents/tool-policy-match.ts`, `src/agents/tool-catalog.ts`, `src/agents/tool-policy-pipeline.ts` y `src/gateway/tool-resolution.ts`. Buscar "el módulo de permisos" lleva a un archivo casi vacío.
3. **Un perfil de herramientas "seguro" intermedio.** No hay perfil "todo menos lo destructivo". `full` es literalmente `allow: ["*"]`. La granularidad fina se delega enteramente a las capas de deny.
4. **Límite de tiempo de ejecución en el `argv` de Docker.** Los timeouts viven en la capa de exec, no en la creación del contenedor.
5. **Una única función de sanitización de env.** Hay dos con comportamiento distinto (`sanitizeEnvVars` y `sanitizeExplicitSandboxEnvVars`), y la asimetría no está documentada — es la debilidad 4.3.
