# O.R.I.O.N. — Sistema de Agentes de Desarrollo

Este proyecto usa un flujo pipeline de agentes para gestionar requerimientos (REQs).

## Pipeline completo

```
orion-coordinador
  → orion-spec (⏸️ pausa: aprobación humana)
    → orion-baseline
      → orion-architect (⏸️ pausa: aprobación humana)
        → orion-security? (solo si aplica — REQ de SEGURIDAD)
          → orion-dev
            → orion-tester (↩️ orion-dev si FAIL)
              → orion-qa (↩️ orion-dev si RECHAZADO)
                → Humano (prueba manual)
                  → Mensaje de commit sugerido
```

## Comandos disponibles

| Comando | Descripción |
|---------|-------------|
| `/nuevo-req [descripción]` | Inicia un REQ nuevo desde cero |
| `/estado-req [REQ-XXX]` | Consulta el estado de uno o todos los REQs |
| `/handoff-req REQ-XXX` | Retoma un REQ en curso en una sesión nueva |

## Categorías de REQ

- **CORE**: main loop, dispatcher, classifier, router, handlers, NLP, config
- **SKILL**: sistema de habilidades modular (BaseSkill, skill_manager)
- **VOZ**: STT, TTS, wake word, barge-in, transcripción
- **UI**: GUI PyQt6, CLI, personality, formato de salida
- **SEGURIDAD**: auth, niveles verde/amarillo/rojo, confirmaciones, logging, secretos
- **AUTOMATIZACION**: rituales proactivos, scheduler, briefing
- **BOT**: Telegram, Discord, gateway, nuevos canales
- **MEMORIA**: SQLite, vectores semánticos, embeddings, history
- **INTEGRACION**: proveedores LLM, APIs externas, fallback
- **DOCS**: documentación, configuración, setup, .env

## Estados del tracker

`NUEVO → EN_SPEC → SPEC_APROBADO → EN_BASELINE → EN_ARQUITECTURA → ARQUITECTURA_APROBADA → EN_DESARROLLO → EN_PRUEBAS → EN_QA → LISTO_PARA_COMMIT`

## Reglas obligatorias

- `.claude/rules/definition-of-done.md` — DoD por agente
- `.claude/rules/git.md` — commits manuales
- `.claude/rules/python-style.md` — convenciones Python
- `.claude/rules/skills.md` — creación de skills
- `.claude/rules/security-levels.md` — niveles verde/amarillo/rojo
- `.claude/rules/testing.md` — pytest y estructura de tests

## Skills del workspace

- `.claude/skills/context-manager/SKILL.md` — gestión de contexto entre sesiones
- `.claude/skills/skill-scaffold/SKILL.md` — generación de boilerplate de skills

## Scripts

- `node .claude/scripts/update-tracker.mjs` — único punto de escritura del CSV
- `node .claude/scripts/guard-git-commit.mjs` — bloquea git commit/push (hook PreToolUse)
- `node .claude/scripts/remind-rules.mjs` — recuerda reglas al editar (hook PostToolUse)
