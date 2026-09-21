# Contexto REQ-053 — Pasos del turno, sugerencias de arranque y títulos cortos

## Resumen ejecutivo
Tres mejoras de uso diario del chat, elegidas con el mandato abierto de Johan («me gustó
mucho, sigue trabajando en la app, sigue mejorando») después de REQ-052:

1. **Pasos del turno.** Lo que el reportero de progreso ya contaba en la línea de estado
   («Buscando en internet: clima Bogotá») desaparecía al llegar la respuesta. Ahora viaja
   con ella (`pasos` en `message_appended`) y se muestra plegado encima: «3 pasos ·
   Consultando Notion · Leyendo la página · …». Transparencia: se ve qué hizo el agente
   para contestar. Todas las herramientas tienen texto legible, incluidas las remotas
   (`mcp__notion__search` → «Consultando notion: search»).
2. **Sugerencias de arranque.** Con la conversación vacía, cuatro frases de ejemplo al
   azar debajo del cuadro («¿Qué tenés conectado?», «Aprendé el flujo modo trabajo…»,
   «Conectate al servidor MCP de Notion…»). Un click deja la frase escrita —no la manda—
   para ajustarla. Se van con el primer mensaje y se vuelven a sortear en cada chat nuevo.
3. **Título corto automático.** Tras el primer intercambio se le pide al modelo un título
   de 3-6 palabras (`tarea="ligera"`, tope de 24 tokens) y se guarda como título propio
   (`memory.rename_conversation`): «Bibliografía de la tesis» en vez de «Necesito que me
   ayudes a organizar la bibliografía de la te…». Un título puesto a mano nunca se pisa;
   un mensaje corto (< 28 caracteres) no gasta la llamada; un modelo caído deja el
   derivado de siempre.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** UI · **Tipo:** MEJORA

## Origen
Mandato abierto de Johan (2026-09-19): «Me gusto mucho sigue trabajando en la app sigue
mejorando». Elegidas por criterio propio: lo que más se nota en el día a día de un chat
(saber qué hizo, saber qué pedir, encontrar las conversaciones).

## Decisiones tomadas
2026-09-19 | conversación principal | Los pasos se recogen en `Bridge._on_progress` (el mismo reportero de la línea de estado) y NO se persisten: solo el turno en vivo los muestra | Persistirlos exige tocar el esquema de `memories`; el valor está en el momento de la respuesta. Se puede sumar después sin cambiar la interfaz.
2026-09-19 | conversación principal | «Pensando» y «Entendiendo lo que me pides» no son pasos; dos avisos iguales seguidos cuentan una vez; techo de 40 por turno | Son el ritmo del bucle, no algo hecho; el techo protege de un reportero desbocado.
2026-09-19 | conversación principal | Un turno que falla entrega los pasos que alcanzó | Es justo lo que se quiere ver cuando algo salió mal.
2026-09-19 | conversación principal | Las sugerencias llenan el cuadro, no envían | Varias piden datos (el token, el nombre del proyecto); mandarlas tal cual sería mandar un ejemplo.
2026-09-19 | conversación principal | El título se pide DESPUÉS de guardar el turno y de refrescar la barra, en su propio `run_async` | La conversación aparece enseguida con el título derivado y un par de segundos después con el corto; un modelo lento no retrasa la barra.
2026-09-19 | conversación principal | `tarea="ligera"` para el título, como la compactación y los resúmenes de correo | Es trabajo mecánico; si hay un modelo local/gratuito configurado para «ligera», el primer intercambio va a ese proveedor (igual que ya pasa con la compactación). Sin configuración, va al proveedor de siempre, que ya vio el texto.
2026-09-19 | conversación principal | `memory.get_conversation_title()` nuevo (solo lectura) para no pisar títulos propios | `rename_conversation` es la única escritura, igual que al renombrar a mano.

## Archivos
- Nuevos: `core/titulos.py`, `ui/webview/frontend/js/sugerencias.js`, `tests/test_titulos.py`.
- Tocados: `ui/webview/bridge.py` (`_pasos_del_turno`, `_registrar_paso`, `_tomar_pasos`,
  `_primer_turno`, `_titulo_pendiente`, `_titular_si_es_el_primer_turno`),
  `core/progress.py` (textos para ~50 herramientas + remotas), `ai/memory_manager.py`
  (`get_conversation_title`), `js/chat.js` (`buildPasos`), `js/app.js`, `index.html`
  (`#sugerencias`), `css/chat.css`, `css/composer.css`, `tests/test_progress.py`,
  `tests/test_webview_bridge.py`, `tests/test_webview_buttons.py`,
  `tests/test_webview_safe_dom_insertion.py`, `tests/test_wake_word_comando.py` (doble).

## Qué puede hacer ahora
- Después de cada respuesta que usó herramientas: «N pasos · …» plegado encima; click
  para ver la lista numerada con el detalle (la consulta, la URL, el archivo).
- Chat vacío: cuatro ejemplos debajo del cuadro; click → queda escrito para editar.
- Cada conversación nueva con un primer mensaje largo recibe un título corto en la barra
  lateral a los pocos segundos. Renombrar a mano sigue mandando.

## Verificación
- `tests/test_titulos.py`: 16 passed (nuevo). `tests/test_progress.py`: 15 (2 nuevos).
  `tests/test_webview_bridge.py`: 2 nuevos (pasos con la respuesta, pasos de un turno
  fallido). `tests/test_webview_buttons.py`: 2 nuevos (pasos plegados y como texto;
  sugerencias llenan sin enviar y se van con el primer mensaje).
- Capturas offscreen: chat con pasos plegados (oscuro) y abiertos (claro); pantalla vacía
  con las sugerencias.
- Suite completa: ver `pruebas/suite-053.txt`.

## Prueba manual sugerida (Johan)
1. Preguntar algo que use herramientas («¿qué clima hace?», «buscá en internet…»): al
   llegar la respuesta, arriba aparece «N pasos · …»; click para desplegar.
2. Chat nuevo: las sugerencias debajo del cuadro; click en una → queda escrita; Enter.
3. Escribir un primer mensaje largo: la conversación aparece en Recientes con el mensaje
   recortado y, un par de segundos después, con un título corto. Renombrarla a mano y
   comprobar que no cambia más.

## Riesgos activos
- El título es una llamada extra al modelo por conversación nueva (solo si el primer
  mensaje tiene ≥ 28 caracteres). Con `task_providers.ligera` apuntando a Ollama o a un
  modelo gratuito no cuesta cuota.
- Los pasos no sobreviven a recargar la conversación (decisión registrada arriba).

## Log de transiciones
2026-09-19 | — → NUEVO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión.
