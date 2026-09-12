# SPEC-032 — Programar de forma avanzada: ejecutar, depurar y ver el proyecto

**Categoría:** CORE | **Tipo:** FEATURE_NUEVA | **Fecha:** 2026-09-09

## Objetivo
Que el agente pueda **cerrar el ciclo de desarrollo**: correr las pruebas, leer el fallo,
corregir el código y volver a correr, sobre un repositorio de verdad, sin salir de la
conversación.

Es el punto 1 de la lista de mejoras de Johan: *"programar de forma avanzada: analizar
proyectos grandes, modificar código, depurar, ejecutar pruebas y trabajar en flujos de
desarrollo complejos"*. Este REQ cubre depurar, ejecutar pruebas y los flujos complejos, y
mejora analizar; el índice de código para proyectos grandes va en REQ-033.

## Decisiones de Johan (2026-09-09)
Elegidas por él sobre tres alternativas, y no son las que la conversación recomendaba:

1. **Cada escritura y cada comando confirman.** No hay permiso por sesión ni por tanda.
2. **Puede ejecutar cualquier comando** dentro de una carpeta habilitada, no una lista
   blanca de comandos de proyecto.
3. El índice persistente entra (REQ-033), no solo mejorar la búsqueda.

**Consecuencia de diseño que se deriva de (1) + (2):** un comando puede escribir archivos
(`echo x > a.py`, `git checkout .`). Si el comando no confirmara, la confirmación por
escritura quedaría decorativa — habría un camino que la rodea. Por eso `project_run` es 🟡 y
confirma **cada llamada** mostrando el comando exacto y la carpeta.

## Criterios de aceptación

### `project_run` — ejecutar y depurar
- [ ] **CA-01** — Ejecuta un comando **dentro** de una carpeta habilitada y devuelve su
  salida. La carpeta se resuelve con `workspace_files.resolver()`: no se puede correr nada
  fuera de las carpetas que el humano habilitó.
- [ ] **CA-02** — Sin ninguna carpeta habilitada no ejecuta nada, y lo dice.
- [ ] **CA-03** — Devuelve **stdout y stderr juntos** y el **código de salida**: depurar sin
  ver el error es adivinar, y el error suele ir por stderr.
- [ ] **CA-04** — La salida se recorta conservando el **final** —donde están los fallos y el
  resumen de pytest—, avisando que se recortó y cuánto.
- [ ] **CA-05** — Timeout con valor por defecto y techo. Al vencer, el proceso se mata y se
  informa: un comando colgado no puede dejar el turno esperando para siempre.
- [ ] **CA-06** — Es 🟡 y **confirma cada llamada** mostrando el comando exacto y la carpeta
  (`command` ya está en `_DETAILS_ALLOWED_KEYS`).
- [ ] **CA-07** — Está en `DESKTOP_ONLY_ACTIONS`: ningún canal remoto ejecuta comandos.
- [ ] **CA-08** — Tiene su frase en castellano en `core/acciones_legibles.py`.
- [ ] **CA-09** — No usa la terminal que el usuario ve en pantalla: es un proceso aparte, sin
  PTY, para no ensuciarle la sesión ni depender de leer una pantalla.

### `project_tree` — ver la forma del proyecto
- [ ] **CA-10** — Devuelve la estructura de una carpeta habilitada con profundidad
  configurable (por defecto 3).
- [ ] **CA-11** — Ignora `node_modules`, `.git`, `__pycache__`, `.venv` y compañía — la misma
  lista que ya usa `buscar()`.
- [ ] **CA-12** — Tiene tope de entradas y avisa cuando recorta: un árbol de 10.000 archivos
  se come el turno entero.
- [ ] **CA-13** — Es 🟢 (es una lectura) y está en `DESKTOP_ONLY_ACTIONS`, como las otras
  herramientas de repositorio.

### El flujo completo
- [ ] **CA-14** — El modo "Código/script" ofrece las dos herramientas nuevas junto a las de
  REQ-029, en el orden en que se usan.
- [ ] **CA-15** — El ciclo *correr → leer el fallo → editar → volver a correr* se puede hacer
  entero con las herramientas registradas, sin salir a la terminal.
  *Verificación:* prueba de integración sobre un repo de mentira en `tmp_path` con un test
  que falla; el ciclo lo arregla y la segunda corrida pasa.

### Pruebas
- [ ] **CA-16** — Ningún test corre nada fuera de `tmp_path`, y los que ejecutan comandos
  usan el intérprete de Python del propio entorno, no herramientas que pueden no estar.
- [ ] **CA-17** — Suite completa sin fallos nuevos.

## Fuera de alcance
- El índice persistente y la búsqueda semántica de código: **REQ-033**.
- Un depurador paso a paso (breakpoints). "Depurar" acá es el ciclo de correr, leer el
  error y corregir, que es como se depura el 95% del tiempo.
- Permisos por sesión: Johan eligió confirmar cada vez.
