---
description: Muestra el estado actual de un REQ o de todos los REQs en curso
---

# /estado-req

Consulta rápida del estado de uno o varios REQs, sin invocar ningún agente del flujo.

## Uso
```
/estado-req            → lista todos los REQs con Estado distinto de LISTO_PARA_COMMIT
/estado-req REQ-XXX    → detalle de un REQ específico
```

## Argumento recibido
$ARGUMENTS

## Qué hacer

### Sin argumento
1. Leer `requerimientos.csv`.
2. Mostrar una tabla con `ID | Categoria | Estado | Aprobacion_SPEC | Aprobacion_Arquitectura | Rama`,
   filtrando los que **no** estén en `LISTO_PARA_COMMIT`.
3. Ordenar por `ID` descendente (los más recientes primero).

### Con un ID (`REQ-XXX`)
1. Leer la fila correspondiente en `requerimientos.csv`.
2. Leer `workspace/adjuntos/REQ-XXX/REQ-XXX-context.md` si existe, y mostrar:
   - Estado actual y último agente que actuó
   - Próximo agente en el flujo (según la posición en el pipeline)
   - Si hay una pausa pendiente de aprobación humana (SPEC o Arquitectura), señalarlo con ⏸️
3. Si el REQ no existe en el CSV ni en `workspace/adjuntos/`, decirlo explícitamente — no inventar
   datos.

No modificar ningún archivo. Este comando es de solo lectura.
