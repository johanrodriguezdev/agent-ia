# REQ-022 — Descripción original del humano

El selector de modelo del chat (botón "model-btn" en el composer) no tiene efecto real en la
respuesta principal: edita `ai_provider`/`ai_model` en config.json, pero `core/reasoning_loop.py`
pide la respuesta con `tarea="razonamiento"`, y `ai/llm_provider.py::_destinos_iniciales()`
prioriza `task_providers["razonamiento"]` sobre el modelo general cuando existe una entrada ahí
(como ya es el caso en instalaciones donde se configuró un modelo por tarea desde Configuración).
Resultado: el usuario cambia de modelo desde el chat, recibe un toast de "Ahora respondo con X"
(falso positivo, ver ui/webview/bridge.py set_model), pero el siguiente mensaje sigue respondiendo
con el modelo fijado en task_providers.razonamiento, sin ningún aviso de por qué.

Además, cuando el proveedor/modelo activo falla (API key ausente, paquete faltante, cuota agotada,
etc.), el sistema ya tiene infraestructura de reintento en cadena (`fallback_provider` en
config.json + `_intentar_respaldos()` en ai/llm_provider.py, y listas de destinos en
`task_providers`), pero NO viene configurada por defecto en una instalación nueva. Sin fallback
configurado, el error interno crudo del proveedor (p. ej. "Error (deepseek): No module named
'openai'") se muestra tal cual al usuario en el chat, en vez de una respuesta que explique que se
cambió a un modelo gratuito disponible.

Se pide:
1. Que el selector de modelo del chat (model-btn) y el sistema de "modelo por tarea"
   (task_providers) queden coherentes entre sí — ya sea que el selector del chat edite también/en
   cambio la tarea "razonamiento", o que dé una señal clara al usuario de que hay un modelo por
   tarea fijado que manda sobre la elección general.
2. Que exista una capacidad de fallback automático a un modelo gratuito cuando el
   proveedor/modelo configurado falla (sin API key, paquete faltante, cuota agotada, timeout,
   etc.), y que el agente informe al usuario en su respuesta que cambió de modelo, en vez de
   mostrar el error interno crudo.

## Contexto de investigación previa (misma conversación)
Se confirmó primero un bug de instalación separado (faltaba el paquete `openai` en
requirements.txt, usado por los adaptadores de DeepSeek/OpenAI/OpenRouter) — ESE ya fue corregido
FUERA de este REQ. Este REQ es solo sobre el comportamiento de selección/fallback de modelos
descrito arriba.
