---
description: Inicia un REQ nuevo — activa el flujo completo de agentes desde orion-coordinador
---

# /nuevo-req

Arranca el flujo obligatorio de agentes para un requerimiento nuevo. Equivale a que el usuario
escriba "Nuevo REQ, [descripción]" — es un atajo, no un flujo distinto.

## Uso
```
/nuevo-req [descripción del requerimiento]
```

## Descripción recibida
$ARGUMENTS

## Qué hacer

1. Si `$ARGUMENTS` está vacío, pedir la descripción antes de continuar.
2. Invocar al agente `orion-coordinador` con la descripción como entrada. Él se encarga de:
   - Detectar la categoría (CORE, SKILL, VOZ, UI, SEGURIDAD, AUTOMATIZACION, BOT, MEMORIA,
     INTEGRACION, DOCS) y confirmar con el usuario si hay ambigüedad
   - Obtener el siguiente ID de REQ (`node .claude/scripts/update-tracker.mjs --siguiente-id`)
   - Crear `workspace/adjuntos/REQ-XXX/` con sus subdirectorios (`origen/`, `spec/`, `propuestas/`,
     `pruebas/`) y el archivo `REQ-XXX-context.md` inicial
   - Registrar la fila nueva en `requerimientos.csv`
     (`node .claude/scripts/update-tracker.mjs --crear ...`)
   - Entregar el REQ a `orion-spec`
3. A partir de ahí, el flujo sigue en orden estricto:
   `orion-coordinador → orion-spec (⏸️ pausa) → orion-baseline → orion-architect (⏸️ pausa)
    → orion-ui? (si es categoría UI o hay referencia visual) → orion-security? (si aplica)
    → orion-dev → orion-tester → orion-qa → humano (prueba manual) → mensaje de commit`
4. Nunca saltar agentes ni escribir código antes de que `orion-dev` tenga luz verde.
