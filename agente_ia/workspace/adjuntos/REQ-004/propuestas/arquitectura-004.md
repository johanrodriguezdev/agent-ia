# Arquitectura REQ-004 — Capa de Identidad de O.R.I.O.N.

## Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| SOUL.md define personalidad, valores y criterio | Archivo independiente con esencia, personalidad, valores y criterio de Orion |
| IDENTITY.md define nombre, rol, estilo y límites | Archivo con nombre oficial, pronunciación, rol, capacidades y límites |
| USER.md contiene perfil completo de Johan | Archivo derivado de MEMORY.md existente, expandido con preferencias detalladas |
| AGENTS.md documenta pipeline y reglas | Archivo que formaliza el pipeline ya descrito en CLAUDE.md con reglas por agente |
| OPERATING_AGREEMENT.md define niveles por canal | Archivo que consolida lo que hoy está en `security_manager.py` y `.claude/rules/security-levels.md` |
| MEMORY.md actualizado sin duplicar USER.md | MEMORY.md se simplifica a contexto activo: proyecto, decisiones, estado del sistema |

## Módulos a modificar
Ninguno. Son archivos de configuración/identidad markdown, no código Python.

## Nuevos archivos
| Archivo | Responsabilidad |
|---------|----------------|
| `SOUL.md` | Define la personalidad, valores y criterio de Orion (esencia del asistente) |
| `IDENTITY.md` | Define nombre, rol, estilo, capacidades y límites (ficha técnica) |
| `USER.md` | Perfil completo de Johan: información, preferencias, contexto técnico |
| `AGENTS.md` | Reglas de operación del pipeline: roles, memoria, herramientas, límites |
| `OPERATING_AGREEMENT.md` | Acuerdo operativo: verde/amarillo/rojo, permisos por canal, modos |

## Archivos a modificar
| Archivo | Cambio |
|---------|--------|
| `MEMORY.md` | Perfil de usuario delegado a USER.md; ahora solo decisiones activas y contexto del proyecto |

## Flujo de datos
```
Orion inicia sesión
  → Lee SOUL.md (personalidad)
  → Lee IDENTITY.md (quién es)
  → Lee USER.md (quién es Johan)
  → Lee MEMORY.md (contexto activo)
  → Lee AGENTS.md (cómo operar)
  → Lee OPERATING_AGREEMENT.md (límites)
  → Responde con identidad + contexto + límites
```

## Dependencias nuevas
Ninguna. Solo archivos markdown.

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| Incoherencia entre archivos | Revisión cruzada al final — unificar tono, estilo y datos |
| MEMORY.md pierde info al migrar | USER.md contiene TODA la info de perfil, MEMORY.md gana foco |
| Archivos no se leen automáticamente | Se requiere un REQ futuro para que Orion cargue estos archivos al inicio |

## Pruebas sugeridas
1. Verificar que cada archivo existe y tiene contenido sustancial
2. Verificar que no hay contradicciones entre archivos (ej: nombre del agente, tratamiento)
3. Verificar que USER.md contiene al menos la misma información que el MEMORY.md anterior
4. Verificar que OPERATING_AGREEMENT.md es coherente con `security_manager.py`
