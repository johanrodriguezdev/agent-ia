# Contexto REQ-058 — Buscar dentro de la conversación (Ctrl+F)

## Resumen ejecutivo
Ctrl+K encuentra conversaciones; faltaba encontrar un texto DENTRO de la que está abierta.
Ctrl+F abre una barra flotante arriba del chat (`js/buscar_en_chat.js`): los hallazgos
se resaltan, el contador dice «2 de 5», Enter/↓ va al siguiente, Shift+Enter/↑ al
anterior, Escape cierra y devuelve el foco al cuadro. Ignora mayúsculas y acentos
(«cafe» encuentra «Café»). Si el hallazgo está dentro de una respuesta plegada («Ver
más»), la despliega. Se rehace sola cuando llegan mensajes y se cierra al cambiar de
conversación.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** UI
- **Tipo:** MEJORA

## Origen
Noche del 2026-09-20, aprobación en bloque de Johan.

## Decisiones tomadas
2026-09-20 | conversación principal | El resaltado parte nodos de texto y envuelve el trozo en `<mark>` con `Range.surroundContents`; al cerrar se deshace y se normalizan los nodos | Nunca innerHTML (§10.1 de REQ-015): el HTML de las burbujas ya está saneado y no se vuelve a interpretar. El DOM queda como estaba.
2026-09-20 | conversación principal | La comparación pliega unidad a unidad (UTF-16) —acento fuera, minúscula— conservando la longitud | Las posiciones del texto plegado tienen que ser las del nodo real; un emoji ocupa dos unidades y `indexOf` cuenta unidades.
2026-09-20 | conversación principal | La barra es hermana de `#chat-area` (no hija) y flota sobre `#main-column` | Así no se desplaza con el scroll ni la recorta el `overflow` del chat. Con la barra abierta el chat baja 62 px para que no tape el primer mensaje.
2026-09-20 | conversación principal | Un `MutationObserver` rehace la búsqueda cuando cambia el chat, descartando las mutaciones que provoca la propia búsqueda (`takeRecords()`) | Sin eso cada búsqueda disparaba otra, sin fin (se vio en la primera versión).
2026-09-20 | conversación principal | Ctrl+F también con el foco en el cuadro de escribir; no con el foco en la terminal | Es una combinación, no una tecla suelta (regla de shortcuts.js); en la terminal Ctrl+F es del shell.
2026-09-20 | conversación principal | No busca dentro de los pasos plegados ni en los botones | Son controles, no contenido.

## Archivos
- Nuevos: `ui/webview/frontend/js/buscar_en_chat.js`.
- Tocados: `index.html` (barra `#buscar-en-chat`), `js/app.js` (init y cierre al limpiar),
  `css/chat.css` (barra, marcas, `body.buscando-en-chat`), `css/layout.css`
  (`#main-column { position: relative }`).
- Tests: `test_webview_buttons.py` (+2, e inventario de botones).

## Qué puede hacer ahora
- Ctrl+F, escribir, Enter para saltar entre hallazgos; Escape para cerrar.

## Qué no hace todavía
- Buscar en todas las conversaciones a la vez (eso es Ctrl+K, que ya busca en el
  historial completo).
- Expresiones regulares o «solo palabra completa».

## Verificación
- Suite completa: ver `pruebas/suite-058.txt`.
- Capturas offscreen: `pruebas/buscar_dark.png`, `pruebas/buscar_light.png` («webhook»,
  2 de 5, el actual con borde).

## Prueba manual sugerida (Johan)
1. En una conversación larga: Ctrl+F, escribir una palabra; ver el contador y los
   resaltados; Enter varias veces (el chat se desplaza al hallazgo); Escape.
2. Escribir con acento o sin él: mismo resultado.
3. Con la barra abierta, mandar un mensaje que contenga la palabra: el contador sube.

## Log de transiciones
2026-09-20 | — → NUEVO → EN_DESARROLLO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión (pipeline acortado, autorización en bloque).
