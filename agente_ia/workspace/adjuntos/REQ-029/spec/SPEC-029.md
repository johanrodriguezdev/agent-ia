# SPEC-029 — Manos para trabajar con repos: archivos y git, confinados

**Categoría:** CORE | **Tipo:** FEATURE_NUEVA + SEGURIDAD | **Fecha:** 2026-09-08

## Objetivo
Que el agente pueda leer, buscar, escribir y editar archivos de un repo, y consultar su
estado en git, **dentro de las carpetas que el humano habilite y en ningún otro lado**.

## Herramientas de v1

| Tool | Nivel | Qué hace |
|---|---|---|
| `file_list` | 🟢 | Lista un directorio de una raíz habilitada |
| `file_read` | 🟢 | Lee un archivo, con tope de tamaño y truncado explícito |
| `file_search` | 🟢 | Busca un patrón en la raíz y devuelve `archivo:línea` con la coincidencia |
| `file_write` | 🟡 | Crea o reescribe un archivo |
| `file_edit` | 🟡 | Reemplaza un fragmento exacto por otro |
| `git_status` | 🟢 | Estado del repo de esa raíz |
| `git_diff` | 🟢 | Diff (opcionalmente de un archivo) |
| `git_log` | 🟢 | Últimos commits |

**Fuera de v1, deliberado:** `git_commit` y `git_push` (los hace el humano,
`.claude/rules/git.md`), borrar archivos, mover/renombrar, y escribir sobre el código de
O.R.I.O.N. (sigue siendo 🔴 `modify_source_code`).

## Criterios de aceptación

### Confinamiento — el corazón del REQ
- [ ] **CA-01** — Ninguna herramienta opera fuera de las raíces habilitadas. Se rechazan,
  con un mensaje que el modelo entiende y sin tocar el disco: ruta absoluta fuera de toda
  raíz, `..` que se escapa, y symlink cuyo destino real cae afuera.
  *Verificación:* pytest con `tmp_path`, incluido un symlink real.
- [ ] **CA-02** — Sin raíces configuradas —archivo ausente, corrupto, JSON inválido, o una
  entrada que no es una carpeta existente— **ninguna herramienta opera**. Un archivo roto
  jamás se interpreta como "sin restricciones" (mismo criterio que REQ-019/CA-06).
- [ ] **CA-03** — El directorio de instalación de O.R.I.O.N. queda excluido **aunque
  alguien lo agregue como raíz** en el archivo de configuración. El bloqueo vive en código,
  no en la configuración, y el intento se loguea con `logger.critical`.
- [ ] **CA-04** — La resolución de rutas se hace con la ruta REAL (`os.path.realpath`) antes
  de comparar, y la comparación es por segmentos de ruta, no por prefijo de string:
  `/home/proyecto-malo` no puede pasar por estar dentro de `/home/proyecto`.

### Niveles y canales
- [ ] **CA-05** — `file_read`, `file_list`, `file_search`, `git_status`, `git_diff` y
  `git_log` se registran 🟢; `file_write` y `file_edit`, 🟡.
- [ ] **CA-06** — **Ninguna de las 8 es alcanzable fuera del escritorio**, ni siquiera las
  verdes: se agrega `DESKTOP_ONLY_ACTIONS` a `core/security_manager.py`, evaluado antes que
  `CHANNEL_ALLOWED_LEVELS`. Sin esto, un `file_read` verde deja que un mensaje de Telegram
  se lleve cualquier archivo del disco. *Verificación:* pytest recorriendo los 7 canales
  para las 8 herramientas.
- [ ] **CA-07** — `DESKTOP_ONLY_ACTIONS` es **restrictivo y nunca permisivo**: no puede
  habilitar nada que la política de canal ya negara. Es la operación inversa de
  `CHANNEL_ACTION_EXCEPTIONS` (REQ-018), que es aditiva.
- [ ] **CA-08** — La confirmación de `file_write`/`file_edit` muestra **la ruta exacta**
  (vía `format_details`, como `terminal_run_command` muestra el comando). Autorizar una
  escritura sin ver dónde sería autorizar a ciegas.
- [ ] **CA-09** — Cada herramienta pasa por `agents/tool_registry.py::execute_tool()`, con
  su gate de REQ-005. Ninguna se invoca por un camino propio.

### Comportamiento útil
- [ ] **CA-10** — `file_read` tiene tope de tamaño: un archivo grande se devuelve truncado
  **avisando explícitamente que se truncó y en qué línea**, nunca revienta el turno ni se
  corta en silencio. Acepta rango de líneas para leer de a pedazos.
- [ ] **CA-11** — `file_edit` exige que el fragmento a reemplazar aparezca **exactamente una
  vez**. Con 0 o más de 1 coincidencias no escribe nada y explica cuál de los dos casos fue.
- [ ] **CA-12** — `file_write` crea los directorios intermedios que falten **dentro** de la
  raíz, y nunca fuera.
- [ ] **CA-13** — Las herramientas de git corren con `subprocess` **sin shell** y con una
  lista blanca de subcomandos (`status`, `diff`, `log`). No existe forma de colar otro
  subcomando ni argumentos arbitrarios.
- [ ] **CA-14** — Los errores vuelven como texto explicativo para el modelo (qué pasó y qué
  puede hacer), nunca como stacktrace ni como ruta absoluta del disco en un canal externo.
- [ ] **CA-15** — El modo estratégico "codigo" (REQ-026) ofrece estas herramientas primero
  y conserva su `presupuesto=40` de REQ-027.

### Pruebas
- [ ] **CA-16** — Ningún test toca archivos reales fuera de `tmp_path` (regla de
  `.claude/rules/testing.md`), y ninguno ejecuta git contra el repo del proyecto.
- [ ] **CA-17** — La suite completa sigue sin fallos nuevos respecto del baseline.
