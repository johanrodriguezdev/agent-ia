# Contexto REQ-032 — Cerrar el ciclo de desarrollo

## Resumen ejecutivo
El agente podía escribir código pero no enterarse de si funciona. Este REQ le da las dos
piezas que faltaban para programar de verdad: **correr el proyecto** (`project_run`) y **ver
su forma** (`project_tree`). Con eso el ciclo *correr → leer el fallo → corregir → volver a
correr* se cierra sin salir de la conversación.

## Estado actual
- **Estado tracker:** EN_PRUEBAS
- **Último agente:** conversación principal
- **Fecha última actualización:** 2026-09-09
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** CORE
- **Tipo de cambio:** FEATURE_NUEVA

## Origen
Punto 1 de la lista de mejoras de Johan: *"programar de forma avanzada: analizar proyectos
grandes, modificar código, depurar, ejecutar pruebas y trabajar en flujos de desarrollo
complejos"*.

Estado de esos cinco verbos antes de este REQ: modificar ✅ (REQ-029/030), analizar a medias,
y **depurar, ejecutar pruebas y flujos complejos no existían**. El índice para proyectos
grandes va en REQ-033.

## Decisiones de Johan
Se le ofrecieron tres alternativas por decisión y eligió las tres **contra** la
recomendación de la conversación, con el criterio de máximo control y máxima potencia:

1. **Cada escritura y cada comando confirman** (se descartó el permiso por sesión).
2. **Cualquier comando** dentro de la carpeta, no una lista blanca de comandos de proyecto.
3. **Índice persistente** para el análisis (REQ-033), no solo mejorar la búsqueda.

**Consecuencia de diseño que se deriva de (1)+(2), y que Johan aceptó:** un comando puede
escribir archivos (`echo x > a.py`, `git checkout .`). Si el comando no confirmara, la
confirmación por escritura quedaría decorativa — habría un camino que la rodea. Por eso
`project_run` confirma **cada llamada**, mostrando el comando exacto y la carpeta.

## Decisiones tomadas
2026-09-09 | conversación principal | `project_run` es un proceso aparte, sin PTY, y no usa la terminal que el usuario ve | Depurar es leer la salida, no mirar una pantalla. Además, el agente corriendo la suite no puede ensuciarle la sesión al usuario
2026-09-09 | conversación principal | Se devuelven stdout y stderr JUNTOS | El error va por stderr; separarlos obliga al modelo a reconstruir a mano qué pasó antes de qué
2026-09-09 | conversación principal | El recorte de salida conserva el FINAL | Ahí están los fallos y el resumen de pytest. Recortar por el principio dejaría justo lo que no sirve
2026-09-09 | conversación principal | `project_tree` es 🟢 y `project_run` 🟡 | Mirar la forma de un proyecto es una lectura; ejecutar tiene efectos
2026-09-09 | conversación principal | En el modo "Código" el orden es árbol → buscar/leer → editar → correr | Es el orden de un trabajo real, y el orden de la tupla es el que ve el modelo

## Dos defectos que aparecieron al probar, no al diseñar

Los dos son de Windows y los dos habrían llegado a producción sin los tests:

1. **PowerShell no ejecuta un comando que empieza con una ruta entre comillas.** Lo trata
   como una cadena y devuelve `ParserError: UnexpectedToken`. Hay que anteponer el operador
   de llamada `&`. No es un caso raro: `"C:/.../python.exe" script.py` es exactamente lo que
   escribe cualquiera cuando la ruta del intérprete tiene espacios.
2. **`powershell -Command` aplasta el código de salida a 0 o 1.** Con eso "¿pasaron las
   pruebas?" queda sin respuesta: pytest devuelve 1 si fallaron, 2 si se interrumpió y 5 si
   no encontró ninguna, y las tres llegaban como el mismo 1. Se resuelve con un epílogo que
   propaga `$LASTEXITCODE`, capturando `$?` **antes** porque la propia asignación lo pisa.

## Riesgos activos
- **Es la superficie más potente que tiene el agente**: un comando libre puede hacer
  cualquier cosa que pueda hacer el usuario, dentro de la carpeta desde donde corre. El
  control es la confirmación por llamada y el `cwd` acotado, no el contenido del comando.
  Es la decisión que tomó Johan sabiéndolo.
- El timeout mata el proceso, pero un comando que dejó hijos vivos (un servidor lanzado en
  segundo plano) puede sobrevivir. No se persiguen los hijos: anotado.

## Log de transiciones
2026-09-09 | — → EN_PRUEBAS | conversación principal | Spec, implementación y 20 tests nuevos, incluido el ciclo completo de desarrollo

2026-09-18 | → LISTO_PARA_COMMIT | conversación principal (sesión nocturna autorizada por Johan) | Sincronización del tracker con `main`: el código de este REQ ya está commiteado y mergeado y la evidencia (QA aprobado y/o suite en verde registrada en este contexto) estaba completa. Solo cambia el estado; no se toca código.
