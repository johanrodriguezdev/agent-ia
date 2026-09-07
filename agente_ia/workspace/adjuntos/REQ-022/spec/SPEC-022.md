# SPEC-022 — Selector de modelo sin efecto real + fallback automático ausente

**Estado:** ✅ COMPLETADO — aprobada por Johan en bloque ("Si apruebo todo") el 2026-09-06
**Categoría:** INTEGRACION
**Tipo:** BUG_FIX
**Fecha:** 2026-09-06

---

## Objetivo

Dos problemas relacionados con qué modelo de IA responde de verdad:

1. El selector de modelo del chat (`model-btn`) deja creer al usuario que cambió el modelo
   activo cuando en realidad no tiene efecto, porque existe un modelo fijado por tarea
   (`task_providers.razonamiento`) que manda por encima de `ai_provider`/`ai_model`.
2. Cuando el proveedor/modelo activo falla (sin API key, paquete faltante, cuota agotada,
   timeout), no hay ningún respaldo gratuito activado por defecto: el error crudo del
   proveedor llega tal cual al chat, sin explicación ni alternativa.

Este REQ corrige ambos, con las 4 decisiones ya tomadas por Johan (ver contexto):
coherencia selector-vs-configuración, cadena de respaldo por defecto OpenRouter→Ollama,
aviso del cambio dentro del texto de la respuesta (no un toast), y una versión corta de
ese aviso cuando la respuesta se lee en voz alta.

## Alcance

**Incluye**
- Deshabilitar/reetiquetar el selector de modelo del chat (`model-btn`) cuando
  `task_providers.razonamiento` tiene un destino fijado, y eliminar el toast falso positivo
  en ese caso.
- Cadena de respaldo por defecto (OpenRouter → Ollama) activa en una instalación nueva,
  sin que el usuario tenga que configurar `fallback_provider` a mano, respetando lo que el
  usuario SÍ haya configurado explícitamente.
- Reemplazar el mensaje de error crudo del proveedor (cuando no hay a dónde más caer) por
  un texto claro, no técnico.
- Aviso del cambio de modelo **dentro del texto de la respuesta del agente**, visible en
  Desktop, Telegram y Discord.
- Versión corta del aviso para lo que se lee en voz alta (CLI en modo voz y manos libres
  del webview), sin nombres técnicos de proveedor/modelo.

**No incluye**
- El bug de instalación del paquete `openai` faltante — ya corregido fuera de este REQ.
- Agregar más proveedores gratuitos al catálogo (`_MODELOS_CONOCIDOS`) más allá de lo que
  ya existe.
- Cambiar el mecanismo de reintento en cadena en sí (`_intentar_respaldos`,
  `_cadena_de_respaldo`) más allá de lo necesario para activar el default y limpiar el
  mensaje de fallo total.
- Corregir que el camino de voz del webview (`_on_voice_command`) resuelva como `DESKTOP`
  y no como `VOICE` — brecha preexistente, documentada como riesgo aceptado en REQ-021
  (P2). Ver "Casos borde" más abajo para cómo este REQ convive con ella.
- Rediseño visual del selector de modelo o de la pantalla de Configuración más allá de lo
  que exige mostrar el estado "fijado desde Configuración".

---

## Módulos afectados

| Módulo | Qué cambia |
|--------|------------|
| `ui/webview/bridge.py` | `set_model()` (línea 1059) deja de aplicar el cambio y de emitir `notice_shown("ok", "Ahora respondo con...")` cuando `task_providers.razonamiento` tiene un destino fijado. `_build_models_payload()` (línea 1896) agrega la información de "fijado por tarea" (destino + etiqueta legible, reutilizando `_destino_legible()` de la línea 1811) para que el frontend renderice el estado. |
| `ui/webview/frontend/js/composer.js` | `requestModels()`/`renderModels()`/`setModel()`: el selector se muestra deshabilitado con el texto "Fijado desde Configuración: [label]" cuando el payload trae ese estado, en vez de una lista clickeable que no tiene efecto. |
| `ui/webview/frontend/js/app.js` | `onModelsLoaded()`: consume el campo nuevo del payload sin romper el caso sin fijar (regresión). |
| `ai/llm_provider.py` | `_cadena_de_respaldo()` (línea 336) gana el default OpenRouter→Ollama cuando `fallback_provider` no está configurado. `_intentar_respaldos()` (línea 357): la rama sin cadena (línea 378-380, hoy devuelve `f"Error ({activo}): {error_original}"` crudo) deja de exponer el error interno del proveedor. `generate_response()` (línea 241) es el único punto de llamada de ambas, no debería necesitar cambios de firma. |
| `config_manager.py` | Sin cambios de esquema obligatorios — `fallback_provider` ya es una clave opcional de `config.json` (no está en `DEFAULT_CONFIG`, líneas 17-24) y el default de este REQ se aplica cuando la clave está ausente, no escribiéndola. A confirmar en arquitectura si conviene documentarla en `DEFAULT_CONFIG` con un comentario en vez de escribirla de verdad (ver "Asumidos"). |
| `core/reasoning_loop.py` | `run()` (línea 207): punto donde se arma `final_text` y se conoce `resolved_channel` (línea 225) — es el lugar natural para inyectar el aviso de cambio de modelo en el camino de Desktop/webview/CLI, con la versión corta cuando `resolved_channel == ChannelType.VOICE`. |
| `ai/claude_brain.py` | `_resolver_con_tools()` (línea 121): segundo punto que arma la respuesta final del agente, usado por Telegram y Discord. Necesita el mismo aviso que `reasoning_loop.run()` para que el REQ cumpla "llega igual a los 4 canales". |
| `ui/tts_engine.py` / `ui/cli.py` | Pipeline de preparación de texto para voz introducido en REQ-021 (CA-24/CA-27) — candidato a ser el lugar donde se acorta el aviso para lo que efectivamente se lee en voz alta, incluyendo el caso del manos libres del webview (que resuelve como `DESKTOP`, no `VOICE` — ver "Casos borde"). Mecanismo exacto a definir por `orion-architect`. |
| `tests/` | Tests nuevos: coherencia selector/`task_providers`, cadena de respaldo por defecto (con y sin `OPENROUTER_API_KEY`), no exposición de error crudo, presencia/ausencia del aviso en el texto de respuesta por canal, y forma corta del aviso en `ChannelType.VOICE`. |

---

## Comportamiento actual vs deseado

| Actual | Deseado |
|--------|---------|
| Con `task_providers.razonamiento` fijado, elegir un modelo en `model-btn` guarda `ai_provider`/`ai_model` pero no tiene ningún efecto en la respuesta real. | El selector muestra que hay un modelo fijado desde Configuración y no deja elegir uno que no vaya a aplicar. |
| `set_model()` siempre emite `"Ahora respondo con X."`, sin importar si `task_providers.razonamiento` va a ignorar ese cambio. | El toast solo se emite cuando el cambio va a tener efecto real. |
| Sin `fallback_provider` configurado, un fallo del proveedor activo devuelve `"Error (deepseek): No module named 'openai'"` tal cual al chat. | Sin `fallback_provider` ni lista explícita, se intenta automáticamente OpenRouter (gratis) y luego Ollama local antes de rendirse. |
| Si todos los respaldos fallan o no hay ninguno configurado, el mensaje final puede ser el string crudo de la excepción de Python. | El mensaje final siempre es un texto claro y accionable, nunca una excepción cruda. |
| Un cambio de proveedor por fallo (respaldo) queda solo en el log (`logger.warning`); el usuario no se entera. | El texto de la respuesta menciona el cambio: "Cambié a [modelo] porque [proveedor] no respondió." |
| No existe distinción por canal para ese aviso. | En voz (CLI modo voz, manos libres del webview) el aviso es corto ("Cambié de modelo."), sin nombres técnicos. |

---

## Criterios de aceptación

### Selector de chat vs. `task_providers` (Decisión 1)

- [ ] **CA-01** — Con `task_providers.razonamiento` conteniendo al menos un destino
      (`ai.llm_provider.destinos_de_tarea("razonamiento")` no vacío), el payload que arma
      `_build_models_payload()` incluye que hay un destino fijado por tarea y su etiqueta
      legible (ej. "DeepSeek · deepseek-chat"), usando el mismo criterio de
      `_destino_legible()`.
- [ ] **CA-02** — En ese mismo estado, el `model-btn` del composer se muestra deshabilitado
      con un texto equivalente a "Fijado desde Configuración: DeepSeek — deepseek-chat", y
      no ofrece una lista de modelos clickeable.
- [ ] **CA-03** — Invocar el slot `set_model()` directamente mientras
      `task_providers.razonamiento` tiene un destino fijado **no** modifica
      `ai_provider`/`ai_model` en `config.json` (o, si el diseño de arquitectura elige
      aplicar el cambio igual mientras avisa que no tendrá efecto, el resultado neto es
      verificable: la siguiente llamada a `generate_response(tarea="razonamiento")` sigue
      yendo al destino de `task_providers`, no al que acaba de elegir el selector).
- [ ] **CA-04** — En ese mismo estado, `set_model()` **no** emite
      `notice_shown("ok", "Ahora respondo con ...")`. El falso positivo queda eliminado.
- [ ] **CA-05** — Sin ningún destino fijado en `task_providers.razonamiento` (estado de hoy
      en una instalación nueva), el selector se comporta exactamente igual que antes de
      este REQ: elegible, con efecto real y con su aviso de confirmación. Test de
      no-regresión explícito.

### Fallback por defecto OpenRouter → Ollama (Decisión 2)

- [ ] **CA-06** — Sin la clave `fallback_provider` en `config.json` y sin una lista
      explícita de destinos para la tarea que falló en `task_providers`, cuando el
      proveedor/modelo activo falla, el sistema intenta automáticamente OpenRouter con el
      catálogo gratuito (`"openrouter/free"` — el comodín ya existente en
      `_MODELOS_CONOCIDOS["openrouter"]["modelos"]`, línea 1678) y, si eso también falla o
      no hay `OPENROUTER_API_KEY`, intenta Ollama local.
- [ ] **CA-07** — Si no hay `OPENROUTER_API_KEY` configurada (`config_manager.get_api_key("openrouter")`
      vacío), el paso de OpenRouter se **omite** (no se intenta una llamada condenada a
      fallar por falta de credencial) y se pasa directo a Ollama.
- [ ] **CA-08** — Si el usuario **sí** configuró `fallback_provider` (string o lista) de
      forma explícita, esa configuración se respeta tal cual — el default OpenRouter→Ollama
      no se agrega por encima ni la reemplaza.
- [ ] **CA-09** — Configuraciones existentes de `fallback_provider` (anteriores a este REQ)
      siguen funcionando exactamente igual. Test de no-regresión.
- [ ] **CA-10** — Si tanto OpenRouter como Ollama fallan (o ninguno está disponible), el
      comportamiento cae al camino ya existente de fallo total (ver CA-11), no a una
      excepción sin manejar.
- [ ] **CA-11** — Cuando no queda ningún destino al que caer (cadena de respaldo vacía o
      agotada, con o sin el default de este REQ), el mensaje final al usuario **nunca**
      contiene el texto crudo de una excepción de Python (p. ej. no debe contener
      `"No module named"`, `"Traceback"`, ni el `repr` de una excepción) — usa siempre un
      texto claro, en el estilo de la constante `SIN_PROVEEDOR` ya existente
      (`ai/llm_provider.py:409`). Este criterio corrige puntualmente la rama de
      `_intentar_respaldos()` (línea 378-380) que hoy devuelve
      `f"Error ({activo}): {error_original}"` sin filtrar.

### Aviso del cambio dentro de la respuesta (Decisión 3)

- [ ] **CA-12** — Cuando la respuesta final al usuario provino de un destino distinto al
      configurado originalmente para la tarea (es decir, hubo un respaldo exitoso —
      explícito o el default de CA-06), el texto de esa respuesta incluye una línea que
      menciona el cambio, con el patrón "Cambié a [modelo] porque [proveedor] no
      respondió." (o equivalente). Verificado en los dos puntos donde se arma la respuesta
      final: `core/reasoning_loop.py::run()` (Desktop/webview/CLI texto) y
      `ai/claude_brain.py::_resolver_con_tools()` (Telegram/Discord).
- [ ] **CA-13** — Cuando el proveedor/modelo activo responde a la primera (sin necesidad de
      respaldo), el texto de la respuesta **no** trae ningún aviso de cambio.
- [ ] **CA-14** — El aviso es parte del contenido real del mensaje (lo que se guarda en
      `agent_context`/historial y se muestra en pantalla), no un `notice_shown` (toast) ni
      solo una línea de log. Un test que solo mockee `notice_shown`/logging sin inspeccionar
      el texto de la respuesta no alcanza para verificar este criterio.
- [ ] **CA-15** — Telegram y Discord reciben el mismo aviso que Desktop cuando ocurre un
      respaldo en una conversación por esos canales — mismo mecanismo, sin lógica
      duplicada por canal más allá de lo que ya distingue a
      `_resolver_con_tools()` de `reasoning_loop.run()`.

### Versión corta para voz (Decisión 4)

- [ ] **CA-16** — Cuando `core/reasoning_loop.py::run()` resuelve con
      `resolved_channel == ChannelType.VOICE` (modo voz de `main.py`, opciones '2'/'3') y
      hubo un respaldo, el aviso insertado en el texto usa la forma corta ("Cambié de
      modelo.") sin nombrar proveedor ni modelo.
- [ ] **CA-17** — En cualquier otro canal (Desktop texto, Telegram, Discord), el aviso usa
      la forma completa de CA-12, con nombres de proveedor y modelo.
- [ ] **CA-18** — Toda respuesta que efectivamente se lee en voz alta por el pipeline de TTS
      introducido en REQ-021 (`ui/tts_engine.py`, consumido por el manos libres del webview
      y por `ui/cli.py`) suena con la forma corta del aviso cuando hubo respaldo, **incluso
      cuando el canal resuelto no es `ChannelType.VOICE`** — caso del manos libres del
      webview, que resuelve como `DESKTOP` (riesgo P2 de REQ-021, ver "Casos borde"). El
      texto en pantalla del webview puede seguir mostrando la forma completa; lo que no
      puede pasar es que el TTS lea nombres técnicos de proveedor/modelo en voz alta.
      **Nota para `orion-architect`:** el mecanismo (decidir la forma corta en el punto de
      generación según canal, o reconocer y acortar el aviso dentro del pipeline de
      preparación de texto para voz de REQ-021) no está prescrito por esta SPEC — se deja a
      diseño, con la condición de que no se dupliquen dos lugares que decidan de forma
      independiente "cuándo es voz".

---

## Casos borde

- `task_providers.razonamiento` con una **lista** de varios destinos (rotación entre
  modelos gratuitos, no un único destino fijo): cuenta igual como "fijado por tarea" para
  CA-01/CA-02 — el selector de chat tampoco tiene efecto sobre una lista.
- Agotar una lista explícita de `task_providers` para la tarea que falló y, después, caer
  además en la cadena de respaldo por defecto (`fallback_provider` ausente): hoy el código
  ya encadena ambos mecanismos (`generate_response()` cae a `_intentar_respaldos()` tras
  agotar los destinos de la tarea). Si esto contradice la letra de la Decisión 2 ("no hay
  ... lista de destinos configurada explícitamente"), **queda como decisión de diseño de
  `orion-architect`** — no asumida acá. Documentar la resolución elegida en la
  arquitectura.
- El "cambio preventivo" que ya existe en `generate_response()` (línea 264-275): si el
  proveedor configurado está en cooldown por fallos recientes, arranca directamente por
  otro sin siquiera intentar el original. **ASUMIDO pendiente de confirmar**: si esto
  también dispara el aviso de la Decisión 3, o si el aviso queda reservado solo para un
  fallo en vivo dentro del turno actual — ver "Asumidos".
- Instalación nueva sin ninguna API key configurada (ni siquiera `OPENROUTER_API_KEY`): el
  fallback por defecto llega hasta Ollama; si tampoco está instalado/corriendo, el
  resultado es el mensaje claro de CA-11 (no un error crudo), consistente con el bug
  original que motivó este REQ.
- Vision (`vision_provider`, imagen adjunta): `_destinos_iniciales()` ya prioriza el
  proveedor de visión por encima del enrutado por tarea (línea 228-236). Este REQ no
  cambia esa prioridad; el aviso de cambio de modelo (Decisión 3) puede seguir aplicando si
  el proveedor de visión también falla y hay respaldo.
- Falta de credencial de OpenRouter (CA-07) no debe registrarse como un "fallo" del
  proveedor en `ai/provider_health.py` (no se intentó la llamada) — evitar que un cooldown
  se dispare por una credencial ausente en vez de por una llamada real fallida.

---

## Asumidos

- **ASUMIDO** — El "cambio preventivo por cooldown" (ver Casos borde) también dispara el
  aviso de la Decisión 3, con el mismo criterio que un fallo en vivo: el usuario debe
  enterarse siempre que la respuesta no vino del modelo que configuró, sin importar si el
  sistema ni siquiera intentó el original. A confirmar antes de implementar — si Johan
  prefiere que el aviso quede reservado solo para un fallo real durante el turno, CA-12
  se acota a ese caso.
- **ASUMIDO** — El modelo Ollama por defecto de la cadena de respaldo es el que ya existe
  en `_MODELO_POR_PROVEEDOR["ollama"]` (`"qwen3:8b"`), sin agregar un mecanismo nuevo de
  selección. Si el usuario no tiene ese modelo descargado localmente, el fallo se trata
  como "Ollama no disponible" (cae al mensaje de CA-11), no como un caso especial nuevo.
- **ASUMIDO** — "no hay lista de destinos configurada explícitamente" (Decisión 2) se
  interpreta a nivel de la tarea que falló, no de forma global: una tarea distinta con una
  lista propia en `task_providers` no impide que el default OpenRouter→Ollama aplique a
  otra tarea (o a la general) que no tiene ninguna lista.
- **ASUMIDO** — La forma corta del aviso de voz (Decisión 4) es literalmente "Cambié de
  modelo." (u otra frase igual de breve y sin tecnicismos) — el texto exacto queda a
  criterio de `orion-architect`/`orion-dev`, esta SPEC solo exige la ausencia de nombres de
  proveedor/modelo y el tono natural.

---

## Riesgo aceptado heredado de REQ-021 (P2)

El manos libres del webview resuelve el canal como `ChannelType.DESKTOP`, no `VOICE`
(`ui/webview/bridge.py::_on_voice_command`). Este REQ no lo corrige — sigue fuera de
alcance, igual que en REQ-021 — pero CA-18 obliga a que la forma corta del aviso llegue
igual a lo que se lee en voz alta en ese camino, aunque el canal técnico no sea `VOICE`.
