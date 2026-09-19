# Contexto REQ-046 — Agregar un servidor MCP desde la pantalla

## Resumen ejecutivo
Segundo camino para declarar un servidor MCP (el primero sigue siendo pedírselo al agente):
un formulario compacto al final de la tarjeta «Servidores MCP» de Configuración → Conexiones
(nombre, local/HTTP, comando o URL, nombres de variables). Pasa por el **mismo gate** que
`mcp_add_server` — el modal muestra el comando o la URL — y por acá no viaja ningún secreto:
solo el nombre de la variable; el valor se pega después en «Variables».

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Último agente:** conversación principal (sesión autorizada por Johan, 2026-09-19)
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** UI · **Tipo:** MEJORA

## Origen
Uno de los tres "todavía no puede" del informe de la noche del 2026-09-18. Johan pidió que
pudiera hacer todo eso y autorizó en bloque. Nivel de referencia: OpenClaw, Settings → MCP →
Add server (`openclaw-main/docs/tools/mcp.md`).

## Decisiones tomadas
2026-09-19 | conversación principal | El formulario es el segundo camino, no reemplaza al chat; el texto de ayuda sigue empezando por el ejemplo de cómo pedírselo al agente | `feedback_asistente_no_crud` sigue valiendo; lo que cambia es que OpenClaw ofrece las dos vías y Johan pidió la paridad (`feedback_capacidad_completa`).
2026-09-19 | conversación principal | Slot `add_mcp_server(nombre, tipo, destino, variables)` con `require_confirmation("mcp_add_server")` y `command`/`url` en el detalle | Mismo `action_name` que la herramienta: una clasificación, un texto, una entrada de auditoría. El slot es alcanzable desde cualquier script de la página, así que el gate va en el slot.
2026-09-19 | conversación principal | Las variables se piden por NOMBRE y se declaran como `${NOMBRE}` (env en local; la primera como `Authorization` en HTTP) | Por el formulario no viaja ningún valor: el bloque «Variables» los ofrece después con campo tipo password. Un servidor HTTP con varias cabeceras se declara por el chat.
2026-09-19 | conversación principal | Un nombre inválido se rechaza ANTES de confirmar | No tiene sentido pedir permiso para algo que no se va a poder guardar.

## Verificación
- `tests/test_webview_mcp.py`: 4 tests nuevos (gate con el comando, remoto con Authorization, denegado no escribe, nombre inválido no confirma). 25 passed.
- Captura offscreen de la tarjeta con el formulario, tema claro: layout correcto.

## Log de transiciones
2026-09-19 | — → NUEVO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión.
