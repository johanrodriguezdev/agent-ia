# Contexto REQ-030 — Decirle al agente sobre qué carpetas puede trabajar

## Resumen ejecutivo
REQ-029 le dio manos al agente para leer y editar repos, pero solo se encendían escribiendo
`code_workspaces.json` a mano. Este REQ cierra los **dos pendientes que dejó**: habilitar una
carpeta diciéndoselo al agente, y que la búsqueda deje de abrir archivos de credenciales
(hallazgo C de `security-audit-029.md`).

## Estado actual
- **Estado tracker:** EN_PRUEBAS
- **Último agente:** conversación principal (spec, arquitectura e implementación)
- **Fecha última actualización:** 2026-09-09
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** CORE
- **Tipo de cambio:** MEJORA + SEGURIDAD

## Origen
Johan, 2026-09-09: *"quiero que termines los puntos pendientes, vale que todo esté funcional
y completo, quiero que el agente cada vez sea capaz de hacer y ejecutar tareas"*.

REQ-029 estaba completo en código pero **inerte**: sin `code_workspaces.json` las 8
herramientas no operaban sobre nada, y crear ese archivo a mano es justo lo que este
proyecto no quiere ser. `MEMORY.md`: *"Es un asistente, no una app CRUD — nunca formularios
manuales para lo que el agente puede hacer por voz/instrucción"*.

## Qué se hizo

### 1. Dos herramientas nuevas
| Tool | Nivel | Qué hace |
|---|---|---|
| `workspace_add_folder` | 🟡 | Habilita una carpeta para las 8 herramientas de repositorio |
| `workspace_remove_folder` | 🟡 | Le quita el acceso a una carpeta |

Las dos entran en `DESKTOP_ONLY_ACTIONS`: habilitar una carpeta es decidir **hasta dónde
llegan** las 8 de REQ-029, y esa decisión no se toma por un mensaje remoto.

Ahora alcanza con decirle *"trabajá sobre C:\\Users\\...\\mi-proyecto"* y confirmar el modal.

### 2. Guardas sobre qué carpeta se puede habilitar
Que la decisión pase por una confirmación **no alcanza** cuando el resultado es
irreversible en la práctica: quien confirma no ve las consecuencias, ve una ruta. Por eso se
rechazan en código, aunque el humano confirme:

- la raíz de un disco (`C:\\`),
- carpetas del sistema (`Windows`, `Program Files`, `ProgramData`, `System32`…),
- **la carpeta personal entera** (`C:\\Users\\alguien`), que contiene `.ssh`, `.aws`, los
  perfiles del navegador y AppData de una sola vez,
- el código de O.R.I.O.N., que ya estaba bloqueado en REQ-029 y ahora se rechaza **antes**
  de escribirlo en la configuración.

### 3. La búsqueda ya no abre archivos de credenciales
`buscar()` saltea `.env`, `*.pem`, `*.key`, `id_rsa` y similares, **avisando cuántos salteó**
—saltearlos en silencio dejaría al modelo concluyendo que el dato no existe—. `file_read`
los sigue leyendo si se los piden por su nombre: eso sí es la decisión de alguien.

## Decisiones tomadas
2026-09-09 | conversación principal | Herramienta, no pantalla de configuración | `MEMORY.md`: es un asistente, no una app CRUD. La forma natural de dar una carpeta es decirla
2026-09-09 | conversación principal | 🟡 amarillo y solo escritorio, no verde | Habilitar una carpeta amplía el alcance de 8 herramientas a la vez; es más parecido a `terminal_open` que a una lectura
2026-09-09 | conversación principal | Guardas en código además del modal | Un "sí" distraído no puede terminar habilitando el disco entero. Mismo criterio que `_merge_with_override()` con los RED
2026-09-09 | conversación principal | Se bloquea la carpeta personal EN SÍ, no lo que hay dentro | `Documentos/repos` tiene que poder habilitarse; lo peligroso es la carpeta que las contiene a todas
2026-09-09 | conversación principal | `appdata` se sacó de la lista de carpetas de sistema | Ahí viven las carpetas temporales, así que bloquearla rompía `tmp_path` y cualquier proyecto que alguien tenga ahí. Lo peligroso de AppData queda cubierto por la guarda de la carpeta personal
2026-09-09 | conversación principal | La búsqueda avisa cuántos secretos salteó | Saltearlos en silencio le haría concluir al modelo que el dato no existe
2026-09-09 | conversación principal | Las 2 nuevas NO se agregaron a los `tool_names` del modo "codigo" | Se usan una vez, al empezar a trabajar sobre un repo; el modo prioriza lo que se usa a cada paso

## Descartado (y por qué)
2026-09-09 | Una pantalla en "Configuración" para editar la lista de carpetas | Es el formulario que `MEMORY.md` pide no hacer. Si más adelante se quiere ver la lista, `file_list` sin ruta ya la muestra
2026-09-09 | Que `workspace_add_folder` fuera verde | Verde significa además "alcanzable desde Telegram": un mensaje remoto podría ampliar el alcance del agente sobre el disco

## Riesgos activos
- **Es una herramienta que amplía los permisos del propio agente.** Mitigado con: amarillo
  (confirmación con la ruta a la vista), solo escritorio, guardas en código, y auditoría.
- Un `.env` **dentro** de una carpeta habilitada sigue siendo legible con `file_read` por su
  nombre. Es deliberado y quedó documentado en `security-audit-029.md` (riesgo C).

## Log de transiciones
2026-09-09 | — → EN_PRUEBAS | conversación principal | Spec, arquitectura e implementación en una pasada, bajo la autorización de Johan de trabajar los pendientes
