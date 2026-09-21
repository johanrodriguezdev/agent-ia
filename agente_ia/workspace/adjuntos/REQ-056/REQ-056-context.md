# Contexto REQ-056 — Exportar una conversación a Markdown

## Resumen ejecutivo
Lo que se conversó con el agente termina muchas veces siendo el borrador de otra cosa; la
única salida era copiar burbuja por burbuja. Ahora la conversación entera sale como un
`.md` legible (título, fecha, cada mensaje con quién lo dijo, los adjuntos como «📎
nombre»), por dos caminos con el mismo gate:

1. **Por instrucción** — «guardá esta conversación en un archivo», «exportá este chat»:
   herramienta `chat_export_current` (🟡 amarilla, solo escritorio; la confirmación
   muestra el nombre y la carpeta). Sin carpeta va al Escritorio; sin nombre se arma
   «AAAA-MM-DD Título.md».
2. **Desde la barra lateral** — «Exportar a Markdown…» al final del menú de cada chat
   (`Bridge.export_conversation`, misma confirmación amarilla).

Lo escribe donde van los demás documentos del agente (`core/documentos.py`:
`carpeta_de_salida` + `ruta_libre`, nunca pisa un archivo).

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** UI (toca CORE: herramienta nueva)
- **Tipo:** MEJORA

## Origen
Plan de la noche del 2026-09-20 («si queda noche: exportar una conversación»), aprobado
en bloque por Johan.

## Decisiones tomadas
2026-09-20 | conversación principal | Primero la herramienta (por instrucción), después el menú | Es un asistente, no una app CRUD: lo que se puede pedir hablando se pide hablando. El menú existe para el chat que no está abierto.
2026-09-20 | conversación principal | 🟡 amarilla, con `nombre`/`carpeta` en la confirmación | Crea un archivo en el equipo: mismo nivel que `document_create` y `file_create`. Solo escritorio (`DESKTOP_ONLY_ACTIONS`): «este chat» solo existe ahí.
2026-09-20 | conversación principal | El contenido sale de la base (`get_conversation_turns` sin tope), no del historial que ve el modelo | El historial del modelo está acotado y compactado; el archivo tiene que ser la conversación completa.
2026-09-20 | conversación principal | Los marcadores de adjunto se vuelven «📎 nombre.ext», sin ruta | La ruta es del equipo del usuario, no del documento que puede compartir.
2026-09-20 | conversación principal | El menú de «Mover a proyecto» gana un separador y la entrada de exportar, en vez de un cuarto icono en la fila | La fila ya tiene tres iconos; ese menú es de hecho el menú del chat.

## Archivos
- Nuevos: `core/exportar_chat.py`, `tests/test_exportar_chat.py`.
- Tocados: `agents/tool_registry.py` (`chat_export_current`), `core/security_manager.py`
  (`DESKTOP_ONLY_ACTIONS`), `ui/webview/bridge.py` (`export_conversation`),
  `js/bridge_client.js`, `js/sidebar_projects.js` (entrada del menú), `css/sidebar.css`,
  `README.md`, tests: `test_webview_bridge.py` (+3), `test_webview_buttons.py` (+1).

## Qué puede hacer ahora
- «Guardá esta conversación en un archivo» → «Conversación guardada en C:\…\Escritorio\
  2026-09-20 Bibliografía de la tesis.md».
- «Exportá este chat a la carpeta Tesis con el nombre entrevista» → `…\Tesis\entrevista.md`.
- Menú de un chat en la barra → «Exportar a Markdown…» → confirmación → aviso con la ruta.

## Qué no hace todavía
- Otros formatos (.docx, .pdf). Si hace falta, `document_create` puede recibir el mismo
  contenido; la conversión directa queda para después.
- Elegir la carpeta con un diálogo desde el menú (desde el menú siempre va al Escritorio;
  por instrucción se puede indicar).

## Verificación
- `tests/test_exportar_chat.py`: 10 passed. Suite completa: ver `pruebas/suite-056.txt`.

## Prueba manual sugerida (Johan)
1. En un chat con varios mensajes: «guardá esta conversación en un archivo» → modal de
   confirmación con el nombre → aviso con la ruta → abrir el `.md` del Escritorio.
2. Barra lateral → icono de carpeta de un chat → «Exportar a Markdown…» → mismo flujo.
3. Cancelar la confirmación: no se escribe nada.

## Log de transiciones
2026-09-20 | — → NUEVO → EN_DESARROLLO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión (pipeline acortado, autorización en bloque).
