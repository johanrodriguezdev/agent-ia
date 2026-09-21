# Contexto REQ-063 — Varias imágenes por mensaje

## Resumen ejecutivo
Lo que REQ-054 dejó como «no hace todavía»: **hasta cuatro adjuntos por mensaje**
(imágenes o archivos). Una fila de chips en el composer —uno por adjunto, con miniatura
si es imagen, quitables uno a uno, y que se vacía al mandar (antes el chip quedaba
colgado después de enviar)—, varias miniaturas en fila en la burbuja, un marcador por
adjunto al final del texto, y **el modelo las ve todas**: `image_path` acepta una ruta o
una lista en todos los proveedores con visión (Anthropic, OpenAI/OpenRouter, Gemini,
Ollama; DeepSeek avisa que no ve). Una imagen sola, sin texto, también es un mensaje.
Regenerar reenvía todas; Editar las devuelve todas al chip.

Además, de paso: **los tests ya no escriben en la base real.** Se descubrió que los tests
del bridge que llegaban a `store_turn()` sin stubear la memoria habían dejado 84
conversaciones de prueba en la barra lateral (y `conv-1`/`conv-9` con cientos de filas),
algunas con llamadas reales al modelo. `ai/unified_memory.db` se respaldó
(`.bak-tests-20260921-090046`) y se limpió; `ORION_MEMORY_DB` apunta la suite a una base
temporal desde `tests/conftest.py`.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** UI (toca INTEGRACION: `llm_provider`)
- **Tipo:** MEJORA

## Origen
Johan, 2026-09-21 por la mañana: «¿Y podemos trabajarle a lo que no hace todavía?».

## Decisiones tomadas
2026-09-21 | conversación principal | Tope de 4 adjuntos por mensaje (`imagenes.MAX_ADJUNTOS`); el quinto avisa y no entra; un repetido tampoco | Cuatro capturas ya son una comparación; más es una galería, y cada imagen cuesta tokens.
2026-09-21 | conversación principal | `image_path` acepta str o lista; una sola sigue viajando como string | Ningún caller existente cambia (Telegram, `image_look`, tests); `llm_provider.rutas_de_imagen()` normaliza en un solo punto y descarta las que ya no están en disco.
2026-09-21 | conversación principal | Un marcador por adjunto, uno por línea, en un bloque al final; `separar_adjuntos` reconoce el bloque entero y `separar_adjunto` (singular) queda como envoltorio | Compatibilidad con lo guardado hasta hoy (un marcador) y con `exportar_chat`.
2026-09-21 | conversación principal | `attachment_preview` pasa a `(ruta, miniatura)` y nace `attachments_cleared` | Con varios chips la miniatura tiene que saber a cuál va; y el chip tiene que irse al mandar (antes no se iba).
2026-09-21 | conversación principal | Una imagen sin texto se manda igual (`send_message("")` con adjuntos) | «¿Qué es esto?» implícito; el modelo recibe el marcador y la imagen.
2026-09-21 | conversación principal | `ORION_MEMORY_DB` como red de abajo para toda la suite, además de stubear `resolve` y `store_turn` en `test_webview_bridge.py` | Un test nuevo que olvide stubear la memoria no puede volver a ensuciar la base del usuario ni a llamar al modelo.

## Archivos
- Tocados: `ai/llm_provider.py` (`rutas_de_imagen`, adaptadores), `core/imagenes.py`
  (`MAX_ADJUNTOS`, `marcar_adjuntos`, `separar_adjuntos`), `ui/webview/bridge.py`
  (`_pending_attachments`, `_con_adjunto`, `_payload_de_usuario` → `adjuntos`,
  `attach_file`, `paste_from_clipboard`, `clear_attachment(path)`), `ai/memory_manager.py`
  (`ORION_MEMORY_DB`), `tests/conftest.py`, `js/composer.js` (fila de chips), `js/chat.js`
  (`.bubble-adjuntos`), `js/bridge_client.js`, `js/app.js`, `index.html`,
  `css/composer.css`, `css/chat.css`, `README.md`.
- Tests: bridge (+7), llm_provider (+4), webview_buttons (+2); los existentes adaptados al
  plural (`_pending_attachments`, `adjuntos`, selectores de chips).

## Qué puede hacer ahora
- Pegar dos capturas (Ctrl+V dos veces) y preguntar «¿qué cambió entre las dos?».
- Copiar tres archivos en el Explorador, Ctrl+V en el chat: tres chips; quitar uno con su ×.
- Mandar una imagen sola, sin escribir nada.

## Qué no hace todavía
- Más de cuatro adjuntos en un mensaje.
- Reenviar al modelo las imágenes de turnos anteriores (solo las del turno actual).

## Verificación
- Suite completa: ver `pruebas/suite-063.txt`.
- Capturas offscreen: `pruebas/chips_dark.png` (dos chips con miniatura esperando),
  `pruebas/burbuja_dark.png` (dos miniaturas en fila en la burbuja y «2 pasos · Mirando la
  imagen · Mirando la imagen»).

## Prueba manual sugerida (Johan)
1. Dos capturas con Win+Shift+S y Ctrl+V cada una: dos chips; «¿qué cambió?» → el agente
   compara. Si dice que no ve imágenes: Configuración → Modelos → «Ver imágenes».
2. Quitar un chip con su × antes de mandar: solo viaja el otro.
3. Pegar una captura y Enter sin texto: se manda sola.
4. La barra lateral ya no tiene conversaciones «hola» / «respuesta de prueba» de los
   tests; si ves alguna que sí era tuya y falta, está en `ai/unified_memory.db.bak-tests-…`.

## Log de transiciones
2026-09-21 | — → NUEVO → EN_DESARROLLO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión (pipeline acortado, mandato de Johan).
