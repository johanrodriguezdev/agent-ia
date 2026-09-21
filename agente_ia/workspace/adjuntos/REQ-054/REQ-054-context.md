# Contexto REQ-054 — Imágenes en el chat de escritorio

## Resumen ejecutivo
Paridad con Telegram y Discord: por esos canales el agente **ve** las fotos que le mandan
(`image_path` hasta `generate_response`), pero en el escritorio una imagen adjunta le llegaba
solo como una ruta escrita en el texto (`[Archivo adjunto: C:\…\captura.png]`) y el modelo
no la veía. Ahora:

1. **Pegar con Ctrl+V** una captura (Win+Shift+S, «Copiar imagen» del navegador) o un
   archivo copiado del Explorador; arrastrarla o adjuntarla con el clip sigue igual.
2. **Miniatura en la burbuja** del usuario (también al reabrir la conversación); click →
   visor a tamaño completo con fondo oscurecido, Escape o click fuera cierra. Un adjunto
   que no es imagen (PDF, .py) se ve como un chip con el clip y el nombre, en vez de la
   ruta cruda.
3. **El modelo la ve**: `image_path` viaja `Bridge.send_message` → `resolve()` →
   `reasoning_loop.run()` → `generate_response` en cada vuelta y en el cierre, con el
   `vision_provider` que ya existía. Queda como paso del turno («1 paso · Mirando la
   imagen», REQ-053).
4. **Tipo MIME real** por firma del archivo: antes los adaptadores declaraban siempre
   `image/jpeg`; las fotos de Telegram (JPEG) pasaban, una captura pegada (PNG) la API de
   Anthropic la habría rechazado.
5. **Copia reducida para el modelo** si la imagen supera 1568 px de lado o 4 MB
   (`core/imagenes.preparar_para_el_modelo`, en `generate_response`, para todos los
   canales).

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** UI (toca CORE e INTEGRACION: `resolution`, `reasoning_loop`, `llm_provider`)
- **Tipo:** MEJORA

## Origen
Mandato abierto de Johan (2026-09-20, antes de dormir): «sigue mejorando… ya sabés lo que
quiero», con aprobación en bloque para trabajar toda la noche. Elegido por ser una brecha
real de paridad entre canales, detectada al revisar el código: `reasoning_loop.run()` no
tenía `image_path` y ningún caller del escritorio lo pasaba.

## Decisiones tomadas
2026-09-20 | conversación principal | El pegado lo resuelve Python leyendo `QApplication.clipboard()`; la página solo avisa (`paste_from_clipboard`) | Chromium no expone rutas de archivo y mandar la imagen en base64 por QWebChannel es lento. Con texto en el portapapeles gana el texto (pegar un párrafo copiado de una web con su imagen sigue pegando el párrafo).
2026-09-20 | conversación principal | Las imágenes pegadas se guardan en `users_data/<usuario>/imagenes/`, no en temporal | La burbuja las muestra cada vez que se reabre la conversación: tienen que durar lo que dura la conversación.
2026-09-20 | conversación principal | La miniatura y la imagen del visor viajan como `data:` URL que arma Python; la página nunca lee `file://` | CSP `img-src 'self' data:` se mantiene; `src` se asigna por propiedad, nunca innerHTML (§10.1).
2026-09-20 | conversación principal | `request_image` (imagen entera para el visor) solo sirve rutas que la sesión ya mostró en una burbuja (`_imagenes_mostradas`) | El slot es alcanzable desde cualquier script de la página (§10.2): no tiene por qué leer archivos arbitrarios.
2026-09-20 | conversación principal | El marcador pasa a «[Imagen adjunta: ruta]» para imágenes; «[Archivo adjunto: ruta]» se mantiene para lo demás | El modelo ve la imagen en ese turno; en los siguientes el marcador le recuerda que la hubo y dónde está. `file_analysis_skill` reconoce cualquier ruta absoluta, no el texto del marcador.
2026-09-20 | conversación principal | Solo la imagen del turno actual llega al modelo; las de turnos anteriores no se reenvían | Mismo contrato que Telegram; reenviar todas engordaría cada llamada. Se puede sumar después sin cambiar la interfaz.
2026-09-20 | conversación principal | `image_path` en `resolve()`/`run()` se pasa solo si hay imagen (`extra`), como `modo` y `prior_turns` | Los dobles de test con la firma vieja son funciones planas y explotarían con un kwarg nuevo.
2026-09-20 | conversación principal | La reducción para el modelo va dentro de `generate_response`, con caché por `(ruta, tamaño, mtime)` | Cubre todos los canales y todas las vueltas del bucle sin repetir trabajo.

## Archivos
- Nuevos: `core/imagenes.py`, `ui/webview/frontend/js/visor_imagen.js`, `tests/test_imagenes.py`.
- Tocados: `ui/webview/bridge.py` (`_con_adjunto` → `(texto, imagen)`, `_payload_de_usuario`,
  `paste_from_clipboard`, `request_image`, señales `attachment_preview`/`image_loaded`,
  `_on_turns_loaded`), `core/resolution.py` (`resolve(image_path=)`), `core/reasoning_loop.py`
  (`run(image_path=)`, paso «Mirando la imagen»), `ai/llm_provider.py` (media type real,
  `preparar_para_el_modelo`), `js/composer.js` (paste, miniatura del chip), `js/chat.js`
  (`buildAdjunto`), `js/bridge_client.js`, `js/app.js`, `index.html` (chip), `css/chat.css`
  (miniatura, chip, visor), `css/composer.css`, `README.md`, tests: `test_webview_bridge.py`
  (+8), `test_mejoras_escritorio.py` (+2, 4 ajustados), `test_reasoning_loop.py` (+2, firma),
  `test_resolution.py` (+1), `test_llm_provider.py` (+3), `test_webview_buttons.py` (+3).

## Qué puede hacer ahora
- Pegar una captura y preguntar «¿qué error es este?»: el modelo la ve y contesta.
- Arrastrar o adjuntar un .png/.jpg/.gif/.webp: igual.
- Copiar un archivo en el Explorador y pegarlo en el chat: queda adjunto por su ruta.
- Ver la imagen en la burbuja, y a tamaño completo con un click.
- Un PDF adjunto se ve como chip con su nombre (antes: la ruta entre corchetes).

## Qué no hace todavía
- Varias imágenes en un mismo mensaje (se adjunta una; al pegar varias, la primera).
- Reenviar al modelo las imágenes de turnos anteriores.
- Imágenes generadas por el agente dentro de la burbuja de respuesta.

## Verificación
- `tests/test_imagenes.py`: 22 passed (nuevo).
- Suite completa: ver `pruebas/suite-054.txt`.
- Capturas offscreen (`pruebas/`): `chat_dark.png`, `chat_light.png` (miniatura + chip de
  PDF + paso «Mirando la imagen»), `visor_dark.png` (imagen entera), `chip_dark.png`
  (adjunto pendiente con miniatura). Sin errores de JS.

## Prueba manual sugerida (Johan)
1. Win+Shift+S sobre cualquier cosa, Ctrl+V en el cuadro: aparece el chip con la
   miniatura; escribir «¿qué dice?» y Enter → tu burbuja muestra la imagen y el agente la
   describe. Arriba de la respuesta: «1 paso · Mirando la imagen».
2. Click en la miniatura → visor a tamaño completo; Escape cierra.
3. Cerrar y reabrir la conversación desde Recientes: la miniatura sigue ahí.
4. Copiar un PDF en el Explorador y Ctrl+V en el chat: chip con el nombre; enviar «resumí
   esto» → la burbuja muestra el chip, no la ruta.
5. Pegar texto normal: se pega como siempre.
6. Si el modelo dice que no ve imágenes: revisar `vision_provider` en `config.json` (hoy:
   `gemini`; necesita `GEMINI_API_KEY`).

## Riesgos activos
- `vision_provider=gemini` no tiene tool-calling: un turno con imagen se responde sin
  herramientas (igual que por Telegram hoy). Con `anthropic` como `vision_provider` tendría
  las dos cosas.
- `paste_from_clipboard` es un slot alcanzable desde la página: lee el portapapeles y deja
  el archivo como adjunto visible en el chip; nada viaja sin que el usuario mande el mensaje.

## Log de transiciones
2026-09-20 | — → NUEVO → EN_DESARROLLO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión (pipeline acortado, autorización en bloque).
