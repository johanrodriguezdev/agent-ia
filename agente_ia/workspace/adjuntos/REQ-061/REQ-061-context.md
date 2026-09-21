# Contexto REQ-061 — «Ver imágenes» como tarea configurable

## Resumen ejecutivo
Con REQ-054 el agente ve las imágenes del chat, pero el modelo que las mira se elegía
solo en `config.json` (`vision_provider`, un proveedor a secas). Ahora **Configuración →
Modelos** tiene la fila «Ver imágenes», como las otras tres tareas: se eligen uno o
varios modelos (con rotación) y con una imagen de por medio el turno va a ellos. Sin
nada elegido, vale `vision_provider` como hasta ahora; sin ninguno de los dos, el modelo
general (que puede no ver la imagen: DeepSeek avisa).

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** INTEGRACION
- **Tipo:** MEJORA

## Origen
Noche del 2026-09-20, aprobación en bloque de Johan; hueco detectado al cerrar REQ-054
(el `vision_provider` de este equipo es `gemini` y exige `GEMINI_API_KEY`).

## Decisiones tomadas
2026-09-20 | conversación principal | `task_providers.vision` manda sobre `vision_provider`, y `vision_provider` sobre el modelo general | Lo que el usuario eligió en la pantalla es lo más reciente y explícito; la clave vieja de config.json sigue valiendo para no romper instalaciones.
2026-09-20 | conversación principal | La tarea se resuelve en `_destinos_iniciales` (cuando hay imagen), no como `tarea="vision"` de `generate_response` | La imagen viaja en un turno de «razonamiento»; la tarea no cambia, cambia el destino. El test que exige que cada tarea de la pantalla se use en el código acepta también `destinos_de_tarea("vision")`.
2026-09-20 | conversación principal | Sin modelo explícito en la fila, el del proveedor por defecto (`_MODELO_POR_PROVEEDOR`) | Mismo criterio que las demás tareas: cambiar de proveedor sin cambiar de modelo es el error que este archivo ya cometió dos veces.

## Archivos
- Tocados: `ai/llm_provider.py` (`_destinos_iniciales`), `ui/webview/bridge.py`
  (`_TAREAS_ENRUTABLES`), `README.md`, `tests/test_mejoras_escritorio.py` (criterio del
  test de tareas usadas), `tests/test_llm_provider.py` (+4).

## Qué puede hacer ahora
- Configuración → Modelos → «Ver imágenes» → elegir Gemini/Claude/GPT-4o; pegar una
  captura y preguntar. Si el modelo elegido se queda sin cuota, pasa al siguiente de la
  lista.

## Verificación
- Suite completa: ver `pruebas/suite-061.txt`.

## Prueba manual sugerida (Johan)
1. Configuración → Modelos: la fila «Ver imágenes» aparece debajo de «Trabajo mecánico».
2. Elegir un modelo que vea imágenes; pegar una captura y preguntar: responde sobre la
   imagen. Quitarlo: vuelve a `vision_provider` (gemini).

## Log de transiciones
2026-09-20 | — → NUEVO → EN_DESARROLLO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión (pipeline acortado, autorización en bloque).
