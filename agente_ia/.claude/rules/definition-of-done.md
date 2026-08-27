# Regla: Definition of Done — O.R.I.O.N.

Ningún agente cambia el estado del tracker sin completar su DoD.

## DoD por agente

### `orion-coordinador`
```
[ ] Categoría detectada (CORE, SKILL, VOZ, UI, SEGURIDAD, AUTOMATIZACION, BOT, MEMORIA, INTEGRACION, DOCS)
[ ] REQ-XXX-context.md creado con la plantilla inicial
[ ] Carpeta workspace/adjuntos/REQ-XXX/{origen,spec,propuestas,pruebas} creada
[ ] requerimientos.csv actualizado vía update-tracker.mjs (nunca a mano)
[ ] Handoff a orion-spec emitido
```

### `orion-spec`
```
[ ] Contexto leído (si existe) — no repreguntar decisiones ya registradas
[ ] Preguntas de clarificación resueltas con el humano
[ ] SPEC-XXX.md redactado con criterios de aceptación testeables
[ ] Módulos afectados identificados
[ ] Aprobación humana explícita recibida antes de continuar
[ ] Contexto actualizado, CSV actualizado (Estado → SPEC_APROBADO)
```

### `orion-baseline`
```
[ ] Estado actual del sistema documentado (qué existe hoy, antes del cambio)
[ ] Archivos que serán modificados listados
[ ] Fallos pre-existentes registrados (pytest o compilación)
[ ] Contexto actualizado
```

### `orion-architect`
```
[ ] Propuesta referencia cada criterio de la SPEC
[ ] Módulos, clases y funciones especificados
[ ] Flujo de datos documentado
[ ] Dependencias nuevas identificadas
[ ] Riesgos con mitigación documentados
[ ] Pruebas sugeridas listadas
[ ] Aprobación humana explícita recibida antes de continuar
[ ] Contexto actualizado, CSV actualizado (Estado → ARQUITECTURA_APROBADA)
```

### `orion-ui` (solo si aplica)
```
[ ] Referencia visual (mockup/captura/descripción) contrastada contra el sistema de diseño actual
[ ] Tokens de color/tipografía nuevos o reutilizados verificados sin drift entre theme.py y theme.css
[ ] Layout, spacing y estructura de paneles especificados en términos del DOM real (index.html)
[ ] Estados de componentes (hover/focus/active/disabled/loading/error) documentados
[ ] Accesibilidad básica revisada (contraste AA, foco visible, tamaño mínimo de click)
[ ] Elementos de la referencia descartados con motivo explícito
[ ] ui-design-XXX.md generado
[ ] Si es rediseño (no ajuste menor): aprobación humana explícita recibida antes de continuar
```

### `orion-security` (solo si aplica)
```
[ ] Riesgos clasificados en verde/amarillo/rojo
[ ] Secretos auditados (API keys, tokens)
[ ] Confirmaciones en acciones destructivas verificadas
[ ] Validación de inputs revisada
[ ] security-audit-XXX.md generado
```

### `orion-dev`
```
[ ] Solo se implementó lo aprobado en arquitectura
[ ] Sin API keys/tokens hardcodeados
[ ] Sin `except: pass` silencioso
[ ] Sin prints de debug en código final
[ ] Si agregó dependencias: requirements.txt actualizado
[ ] Si tocó skills: hereda de BaseSkill
[ ] Banner mostrado antes de escribir código
[ ] desarrollo-log-XXX.md generado
[ ] NO se ejecutó git commit
[ ] Mensaje de commit sugerido entregado
```

### `orion-tester`
```
[ ] Compilación verificada (python -m py_compile)
[ ] Cada criterio de aceptación de la SPEC probado
[ ] Tests existentes ejecutados sin nuevos fallos
[ ] test-results-XXX.md generado con PASS/FAIL por criterio
[ ] Si FAIL: handoff de vuelta a orion-dev con detalle específico
```

### `orion-qa`
```
[ ] Seguridad revisada (secretos, acciones destructivas, niveles de riesgo)
[ ] Logging verificado (sin except: pass silencioso)
[ ] Convenciones de código respetadas
[ ] qa-audit-XXX.md generado con veredicto explícito
[ ] Si RECHAZADO: handoff a orion-dev con motivo concreto
[ ] Si APROBADO: se solicita prueba manual del humano antes de cerrar
[ ] NO se ejecutó git commit antes de la aprobación del humano
```

## DoD transversal — todos los agentes
```
[ ] Leer REQ-XXX-context.md al iniciar (si existe)
[ ] Actualizar el contexto al terminar, con fecha y nombre del agente — nunca sobreescribir
[ ] Actualizar requerimientos.csv solo vía update-tracker.mjs
[ ] No escribir columnas del tracker que no le correspondan al agente
[ ] Si queda bloqueado: reportar el motivo y esperar al humano, no asumir
```
