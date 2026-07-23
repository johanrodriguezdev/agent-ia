# Contexto REQ-004 — Capa de Identidad de O.R.I.O.N.

## Descripción
Implementar la capa de identidad del asistente O.R.I.O.N. siguiendo la arquitectura del documento de referencia "Cómo armé mi propio JARVIS". Crear los archivos fundacionales que definen quién es Orion, cómo opera, quién es su usuario y cuáles son sus límites.

## Archivos a crear
| Archivo | Propósito |
|---------|-----------|
| `SOUL.md` | Personalidad, criterio y forma de colaborar |
| `IDENTITY.md` | Nombre, rol y vibra |
| `USER.md` | Quién es Johan, cómo hablarle, contexto humano |
| `AGENTS.md` | Reglas de trabajo, memoria, límites y operación |
| `OPERATING_AGREEMENT.md` | Niveles de riesgo (verde/amarillo/rojo) y autonomía |

## Archivos a actualizar
| Archivo | Cambio |
|---------|--------|
| `MEMORY.md` | Alinear con USER.md — perfil de usuario más completo |

## Dependencias
- Ninguna. Es la capa base del sistema.

## Criterios de éxito
- [x] Orion tiene una identidad definida y coherente en todos los archivos
- [x] Johan tiene un perfil de usuario completo que Orion puede leer
- [x] Hay reglas claras de autonomía y límites de seguridad
- [x] Los agentes del pipeline tienen reglas de operación documentadas
- [x] MEMORY.md está alineado con USER.md sin duplicación

## Referencias
- Documento base: `"Cómo armé mi propio JARVIS"` (entregado por Johan)
- `CLAUDE.md` existente: pipeline de agentes de desarrollo
- `.claude/rules/security-levels.md`: niveles de seguridad existentes
- `config.json`: nombre del agente (O.R.I.O.N.)
- `security_manager.py`: implementación de niveles verde/amarillo/rojo

## Decisiones tomadas
2026-07-20 | orion-coordinador | REQ-004 creado — categoría CORE | Capa base de identidad del sistema
2026-07-20 | orion-spec | SPEC-004.md redactada | 6 criterios de aceptación definidos
2026-07-20 | orion-baseline | Baseline completado | Funcionalidad nueva — no hay baseline previo
2026-07-20 | orion-architect | Arquitectura diseñada | 5 archivos nuevos + 1 modificación, sin dependencias
2026-07-20 | orion-dev | Archivos creados: SOUL.md, IDENTITY.md, USER.md, AGENTS.md, OPERATING_AGREEMENT.md | MEMORY.md actualizado
2026-07-20 | orion-tester | Pruebas: 6/6 criterios PASS | Sin fallos de regresión
2026-07-20 | orion-qa | QA: COMPLETADO — sin hallazgos de seguridad | Pendiente prueba manual humana

## Log de transiciones
2026-07-20 | — → NUEVO | orion-coordinador | REQ-004 creado
2026-07-20 | NUEVO → EN_SPEC | orion-coordinador | Iniciando especificación
2026-07-20 | EN_SPEC → SPEC_APROBADO | humano | Spec aprobada
2026-07-20 | SPEC_APROBADO → EN_BASELINE | orion-coordinador | Iniciando baseline
2026-07-20 | EN_BASELINE → EN_ARQUITECTURA | orion-baseline | Baseline completado
2026-07-20 | EN_ARQUITECTURA → ARQUITECTURA_APROBADA | humano | Arquitectura aprobada
2026-07-20 | ARQUITECTURA_APROBADA → EN_DESARROLLO | orion-coordinador | Iniciando desarrollo
2026-07-20 | EN_DESARROLLO → EN_PRUEBAS | orion-dev | Desarrollo completado
2026-07-20 | EN_PRUEBAS → EN_QA | orion-tester | 6/6 criterios PASS
2026-07-20 | EN_QA → LISTO_PARA_COMMIT | orion-qa | QA COMPLETADO

## Artefactos generados
- `workspace/adjuntos/REQ-004/REQ-004-context.md`
- `workspace/adjuntos/REQ-004/spec/SPEC-004.md`
- `workspace/adjuntos/REQ-004/origen/baseline-004.md`
- `workspace/adjuntos/REQ-004/propuestas/arquitectura-004.md`
- `workspace/adjuntos/REQ-004/propuestas/desarrollo-log-004.md`
- `workspace/adjuntos/REQ-004/pruebas/test-results-004.md`
- `workspace/adjuntos/REQ-004/pruebas/qa-audit-004.md`
