# SPEC-004 — Capa de Identidad de O.R.I.O.N.

## Objetivo
Crear la capa fundacional de identidad del asistente O.R.I.O.N. siguiendo la arquitectura por capas del documento "Cómo armé mi propio JARVIS". Esta capa es prerrequisito para todas las demás.

## Archivos creados

| Archivo | Ruta | Propósito |
|---------|------|-----------|
| `SOUL.md` | `agente_ia/SOUL.md` | Personalidad, criterio y forma de colaborar |
| `IDENTITY.md` | `agente_ia/IDENTITY.md` | Nombre, rol, capacidades y límites |
| `USER.md` | `agente_ia/USER.md` | Perfil completo de Johan |
| `AGENTS.md` | `agente_ia/AGENTS.md` | Reglas de operación del pipeline de agentes |
| `OPERATING_AGREEMENT.md` | `agente_ia/OPERATING_AGREEMENT.md` | Niveles de riesgo y autonomía por canal |

## Archivos actualizados

| Archivo | Cambio |
|---------|--------|
| `MEMORY.md` | Refactorizado: perfil de usuario delegado a USER.md, ahora enfocado en decisiones activas, contexto del proyecto y estado del sistema |

## Criterios de aceptación

- [x] SOUL.md define personalidad, valores y criterio de Orion
- [x] IDENTITY.md define nombre, rol, estilo, capacidades y límites
- [x] USER.md contiene perfil completo de Johan
- [x] AGENTS.md documenta el pipeline y reglas de cada agente
- [x] OPERATING_AGREEMENT.md define verde/amarillo/rojo por canal
- [x] MEMORY.md actualizado sin duplicar USER.md
- [x] Todos los archivos están en `agente_ia/` junto a MEMORY.md y CLAUDE.md
- [x] Los archivos son coherentes entre sí (no hay contradicciones)

## Verificación

- [ ] Orion lee SOUL.md + IDENTITY.md al inicio para establecer personalidad
- [ ] Orion lee USER.md para conocer a Johan
- [ ] Orion respeta los niveles de riesgo definidos en OPERATING_AGREEMENT.md
- [ ] Los agentes del pipeline siguen las reglas de AGENTS.md
