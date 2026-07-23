# Baseline REQ-004 — Capa de Identidad de O.R.I.O.N.

## Estado actual del sistema
Funcionalidad nueva — no hay baseline previo. Los archivos de identidad no existen actualmente. Existen archivos relacionados:

| Archivo existente | Contenido actual |
|------------------|------------------|
| `MEMORY.md` | Perfil de usuario mezclado con contexto del proyecto (14 líneas) |
| `CLAUDE.md` | Descripción del pipeline de agentes de desarrollo |
| `.claude/rules/security-levels.md` | Niveles verde/amarillo/rojo para el pipeline de desarrollo |
| `ui/personality.py` | Personalidad del asistente (formal, "Señor", saludos) |
| `config.json` | Nombre del agente: O.R.I.O.N. |
| `config_manager.py` | Funciones para obtener nombre, pronunciación, wake words |

## Archivos que serán creados (previsión)
- `agente_ia/SOUL.md` — personalidad, criterio y forma de colaborar
- `agente_ia/IDENTITY.md` — nombre, rol y vibra
- `agente_ia/USER.md` — perfil de Johan
- `agente_ia/AGENTS.md` — reglas de trabajo del pipeline de agentes
- `agente_ia/OPERATING_AGREEMENT.md` — niveles de riesgo y autonomía

## Archivos que serán modificados (previsión)
- `agente_ia/MEMORY.md` — alinear con USER.md, eliminar duplicación de perfil

## Fallos pre-existentes (no atribuibles a este REQ)
- Ninguno. No hay tests ni código que estos archivos de identidad afecten directamente.

## Riesgos activos
- Los archivos nuevos deben ser coherentes entre sí y con la personalidad existente en `personality.py`
- `MEMORY.md` actualmente lo lee Orion al inicio de cada sesión — la transición debe ser limpia
