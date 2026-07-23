---
name: context-manager
description: >
  Gestiona el archivo de contexto de REQ (REQ-XXX-context.md). Obliga a leerlo
  al iniciar y actualizarlo al terminar cualquier paso del flujo de agentes.
  Evita repetir decisiones ya tomadas y perder el historial entre sesiones.
---

# Skill: Context Window Manager — O.R.I.O.N.

## Por qué existe
Claude Code no tiene memoria entre sesiones. Cuando un agente retoma un REQ a mitad del flujo
(Spec, Arquitecto, Dev, QA...), no sabe qué decisiones se tomaron, qué se descartó ni por qué si
la sesión anterior se cortó. Este skill obliga a mantener un archivo de contexto vivo que viaja
con el REQ.

## Archivo central
`workspace/adjuntos/REQ-XXX/REQ-XXX-context.md`

Cada agente lo **lee primero** y lo **actualiza al terminar**. Es el único lugar donde
vive el historial de decisiones del REQ.

---

## Cuándo leerlo
SIEMPRE — antes de cualquier acción sobre un REQ existente.
Si no existe todavía (REQ recién creado): crearlo con la plantilla de inicio.

## Cuándo escribirlo
Al terminar cualquier paso que produzca una decisión, un hallazgo o un cambio de estado.

---

## Plantilla inicial

```markdown
# Contexto REQ-XXX — [Descripción corta]

## Resumen ejecutivo
[1-3 líneas: qué es este REQ y cuál es el objetivo central]

## Estado actual
- **Estado tracker:** NUEVO
- **Último agente:** —
- **Fecha última actualización:** YYYY-MM-DD
- **Rama git:** —
- **Categoría:** [CORE | SKILL | VOZ | UI | SEGURIDAD | AUTOMATIZACION | BOT | MEMORIA | INTEGRACION | DOCS]
- **Tipo de cambio:** [FEATURE_NUEVA | MEJORA | BUG_FIX | REFACTOR | SEGURIDAD]

## Decisiones tomadas
<!-- FECHA | AGENTE | DECISIÓN | MOTIVO -->

## Descartado (y por qué)
<!-- Opciones evaluadas y rechazadas — evita repetir el debate -->

## Asumidos pendientes de confirmar
<!-- Cosas asumidas sin confirmación explícita del humano -->

## Riesgos activos
<!-- Riesgos identificados que aún no se han mitigado -->

## Log de transiciones
<!-- FECHA | DE → A | AGENTE | NOTA -->
```

---

## Formato de entrada por agente

### `orion-coordinador` escribe:
```markdown
## Decisiones tomadas
2026-07-20 | orion-coordinador | Categoría detectada: SEGURIDAD | Palabras clave: "shutdown", "confirmación"

## Estado actual
- Estado tracker: NUEVO
- Último agente: orion-coordinador
```

### `orion-spec` escribe:
```markdown
## Decisiones tomadas
2026-07-20 | orion-spec | SPEC aprobada | Aprobado por [nombre]
2026-07-20 | orion-spec | Tipo de cambio: SEGURIDAD | Identificado en la entrevista

## Estado actual
- Estado tracker: SPEC_APROBADO
- Último agente: orion-spec
```

### `orion-baseline` escribe:
```markdown
## Decisiones tomadas
2026-07-20 | orion-baseline | N archivos identificados a modificar | Ver origen/baseline-XXX.md

## Riesgos activos
- Errores preexistentes en tests/ no relacionados con este REQ
```

### `orion-architect` escribe:
```markdown
## Decisiones tomadas
2026-07-20 | orion-architect | Nueva clase SecurityManager en vez de modificar dispatcher | Scope reducido acordado

## Descartado (y por qué)
- Modificar cada handler uno a uno: descartado, se centraliza en SecurityManager

## Estado actual
- Estado tracker: ARQUITECTURA_APROBADA
- Último agente: orion-architect
- Rama git: feature/REQ-XXX-nombre-corto
```

### `orion-security` escribe:
```markdown
## Decisiones tomadas
2026-07-20 | orion-security | Riesgos clasificados: 3 verdes, 2 amarillos, 1 rojo | Ver security-audit-XXX.md

## Riesgos activos
- shutdown_pc() sin confirmación — pasa a Amarillo
```

### `orion-dev` escribe:
```markdown
## Decisiones tomadas
2026-07-20 | orion-dev | SecurityManager implementado con levels verde/amarillo/rojo | Sin desviaciones de la propuesta
```

### `orion-tester` escribe:
```markdown
## Decisiones tomadas
2026-07-20 | orion-tester | 4/4 criterios PASS | Ver test-results-XXX.md
```

### `orion-qa` escribe:
```markdown
## Decisiones tomadas
2026-07-20 | orion-qa | QA aprobado — acciones destructivas ahora piden confirmación | Ver qa-audit-XXX.md

## Log de transiciones
2026-07-20 | EN_QA → LISTO_PARA_COMMIT | orion-qa | Humano aprobó prueba manual
```

---

## Regla de lectura obligatoria
Si el contexto ya muestra que se tomó una decisión:
- **No re-debatirla** — respetar lo registrado.
- **No re-preguntarle** al humano algo que ya está en "Decisiones tomadas".
- Si hay conflicto entre lo que se está por hacer y lo registrado: señalarlo al humano antes de actuar.

## Regla de escritura
Al terminar, el agente **agrega** (nunca sobreescribe):
- En la sección correcta.
- Con fecha y nombre del agente.
- Actualizando "Estado actual" al final.

## Anti-patrones prohibidos
- Actuar sobre un REQ existente sin leer el contexto primero.
- Sobreescribir entradas anteriores — solo agregar.
- Omitir el motivo de una decisión.
- No actualizar "Estado actual" al terminar.
- Re-preguntar algo que ya está registrado en "Decisiones tomadas".
