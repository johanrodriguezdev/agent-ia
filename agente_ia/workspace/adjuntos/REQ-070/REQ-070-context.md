# Contexto REQ-070 — El modelo vuelve a ver las imágenes de los turnos anteriores

## Resumen ejecutivo
Una captura pegada solo viajaba en **su** turno. En el mensaje siguiente el modelo ya no la
veía: le quedaba el marcador de texto `[Imagen adjunta: ruta]` y nada más. Así, «¿y qué
dice el botón de abajo?» o «comparala con esta otra» obligaban a volver a pegarla. Estaba
anotado como pendiente en REQ-054 y otra vez en REQ-063. Ahora las imágenes de los mensajes
anteriores vuelven a adjuntarse **en su propio mensaje**, con topes para que el coste no se
dispare.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** INTEGRACION | **Tipo:** MEJORA
- **Fecha:** 2026-10-02

## SPEC — criterios de aceptación
| # | Criterio |
|---|---|
| CA-01 | Una imagen de un turno anterior vuelve a viajar como imagen, no como texto |
| CA-02 | Va en **su** mensaje, no amontonada en el último: el modelo distingue «la primera» de «esta otra» |
| CA-03 | Topes: las últimas 4 imágenes, dentro de una ventana de 12 mensajes |
| CA-04 | Una ruta que ya no está en disco se salta en silencio; el usuario pudo borrarla |
| CA-05 | El último mensaje no entra: sus imágenes ya viajan por `image_path` |
| CA-06 | Un adjunto que no es imagen (un PDF) no se reenvía |
| CA-07 | DeepSeek no las recibe: manda texto plano y no las vería |
| CA-08 | Sin imágenes en el historial, los mensajes salen exactamente como antes |

## Arquitectura
- **`core/imagenes.py::imagenes_del_historial(messages, tope, ventana)`** — lee los
  marcadores que `marcar_adjuntos` dejó en el historial y devuelve
  `{índice de mensaje: rutas}`. Solo mensajes de usuario con contenido de texto; los turnos
  con bloques de herramientas se saltan.
- **`ai/llm_provider.py::bloques_de_imagen(rutas, formato)`** — una sola función arma los
  bloques para Anthropic y para OpenAI. La comparten el turno actual y el historial: así
  ninguna de las dos vías puede quedarse atrás cuando se cambie algo.
- **Anthropic** inserta las imágenes viejas recorriendo los índices **de atrás hacia
  adelante**: insertar corre los índices, y al revés se corrompían.
- **OpenAI/OpenRouter** convierten ese mensaje del historial en multimodal
  (`[imagen…, texto]`).

## Decisiones tomadas
2026-10-02 | conversación principal | Tope de 4 imágenes y ventana de 12 mensajes | Cada imagen se reenvía en CADA vuelta del bucle de razonamiento; sin tope, una conversación larga con capturas multiplicaría el coste sin que nadie lo pidiera.
2026-10-02 | conversación principal | Cada imagen en su mensaje, no todas en el último | Amontonadas, el modelo no puede saber cuál era «la primera».
2026-10-02 | conversación principal | Las imágenes pasan por `preparar_para_el_modelo` | Deja cada una dentro de los topes de la API; antes el camino de Anthropic mandaba el archivo crudo y una captura 4K podía hacer rechazar la llamada entera.
2026-10-02 | conversación principal | Una imagen que no se puede preparar se salta | Una imagen de menos es mucho mejor que una llamada rechazada entera.

## Qué puede hacer ahora
- «Mirá esta captura» → responde → «¿y qué dice el botón de abajo?» → **la sigue viendo**.
- «Comparala con esta otra» pegando solo la segunda: ve las dos.
- Después de 12 mensajes o 5 capturas, las más viejas dejan de viajar (y el marcador de
  texto sigue ahí, como hasta ahora).

## Qué no hace todavía
- Gemini y Ollama solo reciben las del turno actual: su implementación manda las imágenes
  junto al último mensaje y no por mensaje.
- DeepSeek no recibe ninguna (no tiene visión).
- Las imágenes que **genera** el agente no existen todavía como concepto.

## Verificación
- `tests/test_imagenes_historial.py`: 15 tests — recuperación, topes, ventana, archivos
  borrados, y que lleguen de verdad a Anthropic y a OpenAI.
- `pruebas/suite-070.txt`: suite completa.

## Prueba manual sugerida (Johan)
1. Pegá una captura y preguntá algo. Después, **sin volver a pegarla**, preguntá por otro
   detalle de la misma imagen: tiene que contestarlo.
2. Pegá una segunda captura y pedí «compará las dos».

## Log de transiciones
2026-10-02 | NUEVO → LISTO_PARA_COMMIT | conversación principal | Hueco documentado en REQ-054 y REQ-063, cerrado.
