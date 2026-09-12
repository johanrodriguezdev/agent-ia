# Contexto REQ-029 — Programar y trabajar con repos completos

## Resumen ejecutivo
El agente sabe hablar de código pero no puede tocarlo: no tiene una sola herramienta para
leer, buscar, escribir ni consultar git. Este REQ le da esas manos, **confinadas a las
carpetas que el humano habilite**, con la escritura en amarillo y la lectura fuera del
alcance de todo canal remoto. Es el punto 2 de las 7 capacidades de nivel agente que Johan
auditó el 2026-09-08; los puntos 1, 3 y 6 los cerró REQ-027.

## Estado actual
- **Estado tracker:** EN_PRUEBAS
- **Último agente:** orion-dev
- **Fecha última actualización:** 2026-09-08 (sesión nocturna, Johan autorizó trabajar y se fue a dormir)
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** CORE
- **Tipo de cambio:** FEATURE_NUEVA + SEGURIDAD

## Origen
Auditoría del 2026-09-08 (ver `REQ-027-context.md`): de las 7 capacidades de nivel agente,
el punto 2 —"programar y trabajar con repos completos"— salió **"No existe"**. Johan
decidió hacer primero el bucle (REQ-027) porque editar un repo son ~20 pasos y antes no
entraban en 4 llamadas al modelo. Con REQ-027 cerrado, el techo dejó de ser el problema:
el modo "codigo" ya tiene `presupuesto=40`.

## Hallazgos de la auditoría de hoy (evidencia para el diseño)

- **19 `ToolSpec` registradas** en `agents/tool_registry.py`. Ninguna toca archivos ni git.
  Lo más cercano es `terminal_run_command` (🟡, REQ-024), que es una shell libre: sirve para
  ejecutar, no para que el modelo lea y edite con precisión.
- **`execute_tool()` (`agents/tool_registry.py:201`)** es el gate único: resuelve la spec y
  llama a `security_manager.require_confirmation()` antes de invocar. No hay que inventar
  nada nuevo para gatear las herramientas nuevas — hay que registrarlas bien.
- **`modify_source_code` YA está registrado como `RiskLevel.RED`**
  (`core/security_manager.py:619`), y `register_action()` rechaza degradar un RED. No es
  solo una línea en `security-levels.md`: está aplicado en código.
- **`CHANNEL_ALLOWED_LEVELS`**: DESKTOP permite verde y amarillo; Telegram, Discord, voz y
  API permiten **verde**; correo, nada. O sea: **una herramienta verde es alcanzable desde
  Telegram**. Esto condiciona el diseño entero (ver decisión 2).
- **`CHANNEL_ACTION_EXCEPTIONS`** (REQ-018) es **aditiva**: habilita una acción amarilla en
  un canal que no la tendría. No existe la operación inversa —restar una acción verde de un
  canal— y este REQ la necesita.
- **`core/security_config.py`** (REQ-019) ya tiene el patrón de persistencia para
  configuración sensible: archivo propio, escritura atómica, y un archivo ausente o corrupto
  se interpreta SIEMPRE como "sin permisos", nunca como "sin restricciones".

## Decisiones tomadas
<!-- FECHA | AGENTE | DECISIÓN | MOTIVO -->
2026-09-08 | conversación principal | Las herramientas operan solo dentro de raíces que el humano habilita, y sin ninguna raíz configurada no hacen nada | Fail-closed, mismo criterio que REQ-005/REQ-019. Una herramienta de archivos sin confinamiento es acceso total al disco
2026-09-08 | conversación principal | El permiso se pide al habilitar la raíz, no por archivo | Precedente explícito de la terminal embebida en `security-levels.md`: "el permiso se pide al abrir, no por comando". 20 confirmaciones para editar un repo no son una decisión, son un obstáculo
2026-09-08 | conversación principal | Lectura y git de consulta 🟢, escritura y edición 🟡 | La escritura es irreversible y merece ver la ruta antes; la lectura dentro de una carpeta ya autorizada no
2026-09-08 | conversación principal | **`DESKTOP_ONLY_ACTIONS` nuevo en `security_manager`**: aunque sean verdes, las herramientas de archivos no existen fuera del escritorio | Sin esto, `file_read` verde deja que un mensaje de Telegram se lleve cualquier archivo del disco. Es la operación inversa de `CHANNEL_ACTION_EXCEPTIONS`, que hoy no existe
2026-09-08 | conversación principal | `git_commit` y `git_push` NO entran | `.claude/rules/git.md`: los commits los hace el humano. Dárselos al agente contradice una regla vigente del proyecto
2026-09-08 | conversación principal | El código de O.R.I.O.N. queda excluido aunque se agregue como raíz | `modify_source_code` es RED y sigue siéndolo. El bloqueo va en código, no en la configuración — mismo criterio con que `_merge_with_override()` bloquea bajar un RED editando el JSON a mano

### Decisiones de orion-dev (2026-09-08)
2026-09-08 | orion-dev | Implementadas las 8 herramientas en 3 módulos nuevos (`core/workspace_config.py`, `core/workspace_files.py`, `core/workspace_git.py`) + `DESKTOP_ONLY_ACTIONS` en `security_manager` | Exactamente lo aprobado en `arquitectura-029.md`. Sin dependencias nuevas: todo biblioteca estándar
2026-09-08 | orion-dev | Las rutas relativas se resuelven contra las RAÍCES habilitadas, nunca contra el directorio de trabajo del proceso | El CWD es el de O.R.I.O.N.: sin esto, `file_read("main.py")` apuntaba al `main.py` del propio agente
2026-09-08 | orion-dev | `file_search` busca texto LITERAL, no expresión regular | Una regex que llega del modelo puede colgar el proceso con backtracking exponencial (ReDoS). Para buscar un nombre de función en un repo, lo literal alcanza
2026-09-08 | orion-dev | Las raíces se pasan por `realpath` también DENTRO de `resolver()`, no solo al cargarlas | Así el confinamiento no depende de que el caller haya normalizado bien; un llamador futuro no puede abrir un agujero por descuido
2026-09-08 | orion-dev | `catalogo_para_modelo()` no ofrece las 8 fuera del escritorio | No es el control de seguridad (ese es `DESKTOP_ONLY_ACTIONS`), es no ofrecer lo que se va a denegar: 6 de las 8 son verdes y el filtro por nivel no las sacaba
2026-09-08 | orion-dev | Agregadas `file_write`/`file_edit` a `core/acciones_legibles.py` — no estaba en la arquitectura | Obligatorio: el test de REQ-023 exige que toda acción amarilla tenga su frase en castellano. Sin eso el modal decía "¿Quiere que ejecute file write?"
2026-09-08 | orion-dev | El contenido a escribir NO entra en `_DETAILS_ALLOWED_KEYS`, solo la ruta | La ruta es lo que hay que ver para autorizar (CA-08); el contenido es largo y puede traer secretos, y `details` se imprime al humano y se persiste en `audit.db`

## Descartado (y por qué)
2026-09-08 | **Bajar `modify_source_code` de 🔴 a 🟢**, pedido explícitamente por Johan la noche del 2026-09-08 ("solo si es para mejorar") | Rechazado por la conversación principal, y queda para su revisión personal. Tres motivos: (1) "solo si es para mejorar" no es verificable por código — no hay condición que un gate pueda evaluar, así que el permiso quedaría sin guarda real; (2) en este sistema verde NO significa "sin confirmación" sino además **"alcanzable desde Telegram, Discord, voz y API"**: un `modify_source_code` verde permite que un mensaje remoto, o una inyección en una página leída durante una investigación, reescriba el código del agente sin nadie despierto; (3) `register_action()` y `_merge_with_override()` bloquean el downgrade a propósito desde REQ-005 — habría que desarmar los dos. **Alternativa ofrecida para cuando Johan esté despierto: 🟡 amarillo y solo escritorio**, con confirmación por escritura mostrando ruta y diff.

## Asumidos pendientes de confirmar
- Qué carpeta habilitar como primera raíz. v1 arranca con la lista vacía: hasta que Johan
  agregue una, las herramientas están registradas pero no operan sobre nada. **Cómo
  habilitarla está documentado al principio de `propuestas/desarrollo-log-029.md`**
  (archivo `code_workspaces.json` en la carpeta de O.R.I.O.N.).
- `code_workspaces.json` NO se agregó a `.gitignore` (tampoco lo está
  `security_overrides.json`, su precedente) y contiene rutas absolutas de la máquina.
  Decisión para Johan: una línea en `.gitignore` lo resuelve si le molesta.
- Si la lista de raíces se edita desde la pantalla "Configuración" (como los overrides de
  REQ-019) o por archivo. v1 hace el archivo; la pantalla puede ser un REQ chico aparte.

## Riesgos activos
- **Es la superficie más peligrosa que se le agregó al agente.** Todo el REQ se juega en el
  confinamiento de rutas: un `..`, un symlink o una ruta absoluta que se escape de la raíz
  convierten esto en acceso libre al disco.
- Leer un archivo significa mandarlo al proveedor del modelo. Por eso el confinamiento y el
  bloqueo por canal importan tanto como el nivel de riesgo.
- Un `file_read` sobre un archivo enorme puede reventar el presupuesto de tokens del turno.

## Log de transiciones
2026-09-08 | — → NUEVO | conversación principal | REQ creado con la auditoría de código ya hecha
2026-09-08 | ARQUITECTURA_APROBADA → EN_PRUEBAS | orion-dev | 17/17 criterios implementados. 3 módulos nuevos + 5 tocados, 237 tests nuevos, suite completa 2143 passed / 0 failed (baseline 1906). Sin dependencias nuevas. NO se ejecutó git commit. Ver `propuestas/desarrollo-log-029.md`
