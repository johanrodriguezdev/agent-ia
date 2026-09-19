# Contexto REQ-051 — Proyectos en la barra lateral

## Resumen ejecutivo
Por debajo ya existían (REQ-016: crear proyectos, asignar chats), pero solo se veían en un
panel aparte. Ahora están donde uno los busca, como en ChatGPT/Claude: sección «Proyectos»
arriba de «Recientes», cada proyecto desplegable con sus chats, «Nuevo chat aquí», «+» para
crear uno, y en cada chat un menú «Mover a proyecto» (o «Sacar del proyecto»). Un chat que
está en un proyecto no se repite en Recientes. Y por instrucción: *«creá un proyecto
Tesis»*, *«guardá este chat en Tesis»*, *«¿qué proyectos tengo?»*.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** UI · **Tipo:** MEJORA

## Origen
Pedido de Johan (2026-09-19): «quiero que los proyectos se agrupen en los chats también
como funcionan en los modelos de IA comunes». Boceto aprobado en la misma conversación.

## Decisiones tomadas
2026-09-19 | conversación principal | `list_conversations(sin_proyecto=True)`: Recientes excluye lo que está en `project_conversations`; sin el parámetro, la consulta es la de siempre | CA-21 de REQ-016 protege `list_conversations()`; el parámetro es opcional y por defecto no cambia nada. Fijado por test.
2026-09-19 | conversación principal | «Nuevo chat aquí» y «guardá este chat» usan una **asignación pendiente** (`core/conversacion_activa.pedir_asignacion`) que el bridge aplica en `_tras_guardar_turno()` | `assign_conversation_to_project` exige que el chat tenga turnos guardados, y eso pasa al terminar el turno. Antes el bridge recién creaba el id al terminar; ahora lo crea al empezar (`conversacion_activa.fijar`) para que una herramienta pueda referirse a «este chat».
2026-09-19 | conversación principal | Módulo nuevo `sidebar_projects.js`; `sidebar.js` solo expone `buildConversationItem`, `getActiveConversationId` y un gancho `setConversationMenuBuilder` | Evita el ciclo de imports y deja `sidebar.js` casi intacto. El panel «Proyectos» de la barra superior sigue para flujos y módulos.
2026-09-19 | conversación principal | El nombre del proyecto nuevo se pide con una entrada inline (también desde el menú «Nuevo proyecto…»), no con `prompt()` | Sin diálogos nativos en una ventana sin marco; misma interacción que renombrar un chat.
2026-09-19 | conversación principal | Herramientas `chat_project_*` verdes y solo escritorio | Tocan solo el historial; «este chat» solo existe en el escritorio.
2026-09-19 | conversación principal | Nombres `chat_project_*` y no `project_*` | `project_run`/`project_tree`/`project_start` ya son las herramientas de proyectos de CÓDIGO (REQ-032/036); mezclarlos confundiría al modelo.

## Qué puede hacer ahora
- Barra lateral: desplegar «Tesis», ver sus chats, «Nuevo chat aquí»; en cualquier chat de
  Recientes, icono de carpeta → «Mover a proyecto ▸ Tesis / Casa / Nuevo proyecto…»; en un
  chat de un proyecto, «Sacar del proyecto». Eliminar un proyecto devuelve sus chats a
  Recientes (pide confirmación, como antes).
- Chat: *«guardá este chat en el proyecto Tesis»* (si no existe, el agente ofrece crearlo o
  lo crea con `create_if_missing`), *«creá un proyecto Casa»*, *«¿qué proyectos tengo?»*.

## Verificación
- `tests/test_proyectos_sidebar.py`: 12 passed (nuevo). `test_webview_bridge.py`,
  `test_memory_manager_projects.py`, `test_workspace_tools_seguridad.py`: verdes.
- Capturas offscreen de la barra (oscuro; claro con el menú abierto).

## Riesgos activos
- La barra ahora carga los proyectos al arrancar (`requestProjects`) además de Recientes:
  una consulta más, pequeña.

## Log de transiciones
2026-09-19 | — → NUEVO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión.
