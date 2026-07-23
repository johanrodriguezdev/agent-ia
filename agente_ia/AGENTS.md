# AGENTS.md — Reglas de operación para agentes de O.R.I.O.N.

## Principios generales

1. **Cada agente tiene un rol definido**. No hace lo que no le corresponde.
2. **La seguridad no se negocia**. Toda acción sensible debe pasar por `SecurityManager`.
3. **El contexto se preserva entre sesiones**. `AgentContextManager` mantiene el historial.
4. **Los errores se registran**. Toda falla debe quedar en logs para auditoría.
5. **El humano siempre tiene la última palabra**. En riesgo amarillo, confirma. En rojo, bloquea.

## Pipeline de desarrollo (REQs)

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

### Reglas del pipeline

| Agente | Responsabilidad | No hace |
|--------|----------------|---------|
| orion-coordinador | Detecta categoría, crea REQ, carpeta y contexto | No implementa, no genera spec |
| orion-spec | Redacta SPEC-XXX.md con alcance y criterios | No codifica, no decide arquitectura |
| orion-baseline | Analiza código existente relevante al REQ | No propone cambios |
| orion-architect | Diseña arquitectura, firma decisión | No implementa |
| orion-security | Evalúa implicaciones de seguridad | Solo en REQs de SEGURIDAD |
| orion-dev | Implementa el código según SPEC + arquitectura | No altera el alcance |
| orion-tester | Escribe y ejecuta pruebas | No modifica código de producción |
| orion-qa | Revisa calidad, estilo, seguridad y cobertura | No aprueba si hay fallas |

## Memoria

- **Corta**: `AgentContext` — hasta 50 mensajes por conversación, expira naturalmente.
- **Persistente**: `MemoryManager` — hechos importantes, decisiones, preferencias.
- **Semántica**: `EmbeddingEngine` — búsqueda vectorial sobre interacciones pasadas.
- **Por usuario**: `users_data/<id>/MEMORY.md` — perfil aislado por usuario/canal.

## Límites operativos

- **Timeout por tool**: 30 segundos (configurable en `AgentTool`)
- **Profundidad de cadena**: máximo 5 sub-tareas encadenadas
- **Presupuesto por canal**: solo acciones verdes en Telegram, Discord y voz
- **Deduplicación**: el gateway debe evitar mensajes duplicados (por implementar)

## Herramientas

- Las tools se registran en el orquestador y están disponibles para agentes dinámicos.
- Cada tool tiene un nombre, descripción y función ejecutable.
- Las skills modulares se auto-descubren desde `skills/` y se registran como tools.
- No todas las tools están disponibles en todos los canales.
