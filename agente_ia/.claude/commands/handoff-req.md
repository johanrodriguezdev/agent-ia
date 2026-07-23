---
description: Retoma un REQ en curso e invoca al siguiente agente correspondiente
---

# /handoff-req

Retoma un REQ que ya está en curso (por ejemplo, en una sesión nueva) y continúa el flujo desde
donde quedó, sin repetir pasos ya completados.

## Uso
```
/handoff-req REQ-XXX
```

## Argumento recibido
$ARGUMENTS

## Qué hacer

1. Si `$ARGUMENTS` está vacío, pedir el ID del REQ.
2. Leer `requerimientos.csv` para obtener `Estado`, `Aprobacion_SPEC`, `Aprobacion_Arquitectura`.
3. Leer `workspace/adjuntos/REQ-XXX/REQ-XXX-context.md` (obligatorio — ver skill
   `context-manager`) para conocer el último agente que actuó y las decisiones ya tomadas.
4. Determinar el siguiente agente según el `Estado`:

   | Estado en CSV           | Siguiente agente  | Nota |
   |-------------------------|-------------------|------|
   | `NUEVO`                 | `orion-coordinador` | |
   | `EN_SPEC`               | `orion-spec`      | |
   | `SPEC_APROBADO`         | `orion-baseline`  | requiere `Aprobacion_SPEC = APROBADO` |
   | `EN_BASELINE`           | `orion-baseline`  | |
   | `EN_ARQUITECTURA`       | `orion-architect` | |
   | `ARQUITECTURA_APROBADA` | `orion-dev`       | requiere `Aprobacion_Arquitectura = APROBADO` |
   | `EN_DESARROLLO`         | `orion-dev`       | |
   | `EN_PRUEBAS`            | `orion-tester`    | |
   | `EN_QA`                 | `orion-qa`        | |
   | `LISTO_PARA_COMMIT`     | (ninguno)         | ya está listo — entregar mensaje de commit si no se entregó |

5. Si el estado requiere una aprobación humana pendiente (SPEC o Arquitectura) y esa aprobación
   no está registrada como `APROBADO`, **no invocar al siguiente agente** — recordarle al usuario
   que el REQ está ⏸️ esperando su validación, y mostrar el documento pendiente de aprobar.
6. Si todo está en orden, invocar al agente correspondiente pasándole el ID del REQ.

Nunca inventar un estado ni saltar un agente para "avanzar más rápido". Si el CSV y el
`REQ-XXX-context.md` no coinciden, priorizar el contexto y señalar la inconsistencia al humano.
