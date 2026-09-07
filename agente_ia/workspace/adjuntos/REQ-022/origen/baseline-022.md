# Baseline REQ-022 — Selector de modelo sin efecto real + fallback automático ausente

**Fecha:** 2026-09-06
**Agente:** orion-baseline

---

## Estado actual del sistema

### 1. Selector de modelo del chat vs. `task_providers` (Decisión 1)

- `ui/webview/bridge.py::set_model()` (línea 1059-1077): valida `provider`/`model` contra
  `_MODELOS_CONOCIDOS`, llama `config_manager.set_ai_provider_and_model()` y **siempre**
  emite `notice_shown("ok", f"Ahora respondo con {label}.")` — sin mirar en ningún momento
  si `task_providers.razonamiento` tiene un destino fijado que va a ignorar ese cambio. El
  toast es hoy un falso positivo incondicional cuando ese destino existe.
- `ui/webview/bridge.py::_build_models_payload()` (línea 1896-1919): arma
  `{"proveedores": [...], "activo": {...}}` a partir de `_MODELOS_CONOCIDOS` +
  `config_manager.get_ai_provider()`/`get_ai_model()`. **No incluye ningún campo** sobre si
  hay un destino fijado por tarea — no existe hoy noción de "fijado por tarea" en este
  payload (esa noción sí existe, pero en un payload distinto: `_build_task_models_payload()`,
  línea 1834-1868, que alimenta la pantalla de Configuración, no el selector del chat).
- `_destino_legible()` (línea 1811-1813) ya existe y es reutilizable tal como asume la SPEC:
  `f"{etiqueta} · {modelo}"`.
- `ai/llm_provider.py::destinos_de_tarea("razonamiento")` (línea 96 en adelante) ya
  devuelve la lista de destinos fijados para esa tarea, vacía si no hay ninguno — es la
  fuente de verdad que `_build_models_payload()` tendría que consultar.
- `ui/webview/frontend/js/composer.js` — el `model-btn` (línea 80-83) siempre abre un menú
  clickeable (`alternarMenuDeModelos()`, línea 163-208) que llama `setModel(proveedor.id,
  modelo)` (línea 196) al elegir cualquier opción, sin ninguna condición. `renderModels()`
  (línea 210-223) solo actualiza la etiqueta y el título del botón desde `payload.activo`;
  no hay hoy ningún estado "deshabilitado" ni texto "Fijado desde Configuración" — esa UI
  no existe todavía en absoluto.
- `ui/webview/frontend/js/app.js` (línea 149): `onModelsLoaded((json) =>
  renderModels(JSON.parse(json)))` es el único consumidor del payload — puente directo,
  sin lógica propia que adaptar más allá de lo que ya hace `renderModels()`.

### 2. Fallback por defecto OpenRouter → Ollama (Decisión 2)

- `config_manager.py::DEFAULT_CONFIG` (línea 17-24) **no incluye** `fallback_provider` ni
  `task_providers` — confirmado. Son claves opcionales que solo existen si el usuario (o el
  código) las escribe en `config.json`.
- `ai/llm_provider.py::get_provider_config()` (línea 69-82) lee
  `config.get("fallback_provider", "").lower()` — hoy, sin la clave, `fallback_provider`
  vale `""`, y `""` es "falsy" tanto en Python como en `_cadena_de_respaldo()`.
- `ai/llm_provider.py::_cadena_de_respaldo(activo, fallback_config)` (línea 336-354): si
  `fallback_config` es falsy, retorna `[]` de inmediato (línea 342-343) — **no hay ningún
  default hoy**, ni de OpenRouter ni de ningún otro proveedor. Acepta string (separado por
  comas/espacios) o lista, sin repetir el proveedor activo ni duplicados.
- `ai/llm_provider.py::_intentar_respaldos()` (línea 357-404): si la cadena resultante está
  vacía (línea 378), **hoy devuelve el error crudo**:
  `f"Error ({activo}): {error_original}"` (línea 380) — confirma el bug del punto 2 de la
  SPEC tal cual está descrito. Es exactamente la línea que CA-11 pide corregir.
- `_MODELO_POR_PROVEEDOR["ollama"]` = `"qwen3:8b"` (línea 178) — confirma el ASUMIDO de la
  SPEC/contexto sobre el modelo Ollama de respaldo por defecto: ya existe, no hace falta
  agregarlo.
- `_MODELOS_CONOCIDOS["openrouter"]["modelos"]` (línea 1657-1679) ya incluye el comodín
  `"openrouter/free"` en la última posición de la lista (línea 1678) — confirmado tal como
  la SPEC lo referencia en CA-06.
- `config_manager.get_api_key("openrouter")` existe (línea 272, ya usado en otras partes de
  `bridge.py` como `_avisos_de_claves()`) — es el punto correcto para CA-07 (omitir
  OpenRouter sin credencial).
- `generate_response()` (línea 241-333) ya tiene un camino de "cambio preventivo por
  cooldown" (línea 257-275): con un único destino, si `provider_health` indica que el
  activo está en cooldown, arranca directamente por otro de la cadena
  `[activo] + _cadena_de_respaldo(...)` **sin intentar el original ni lanzar ninguna
  excepción** — es decir, este camino nunca pasa por `_intentar_respaldos()` ni por el
  bloque `except` de la línea 300-311; ocurre ANTES del primer intento real. Confirmado el
  punto que el contexto/SPEC deja explícitamente abierto para `orion-architect`: hoy este
  camino no tiene ningún mecanismo de aviso al usuario (ni toast, ni texto en la respuesta,
  ni marca alguna que un caller pueda inspeccionar) — hay que decidir si se le agrega uno.
- No existe hoy ningún mecanismo por el cual `generate_response()` le diga al caller "hubo
  un respaldo, contra el destino X" — ni valor de retorno, ni excepción con atributo, ni
  estado compartido. `run()` en `reasoning_loop.py` y `_resolver_con_tools()` en
  `claude_brain.py` reciben únicamente el texto (o `LLMToolResponse`) final. Esto es
  relevante para CA-12/CA-14/CA-15: hoy no hay ningún canal de datos para que esos dos
  puntos de ensamblado sepan que hubo un cambio de modelo — es una pieza de diseño que le
  queda a `orion-architect`, no algo que ya exista y solo haya que conectar.
- Test existente `tests/test_provider_fallback.py` (188 líneas, 14 tests, todos PASS)
  cubre hoy: cadena vacía sin config, un respaldo suelto, cadena de varios, no repetir el
  que ya falló, no duplicar respaldos, uso de tools en el respaldo, modelo propio por
  respaldo, y el mensaje sin tecnicismos cuando **sí hay** cadena y todos fallan
  (`test_si_todos_fallan_se_avisa_sin_tecnicismos`) — pero el caso de la SPEC (cadena VACÍA,
  sin fallback_provider) devuelve hoy el error crudo sin test que lo cubra como regresión
  deliberada; hay que revisar si ese test existente asume cadena no vacía.

### 3. Aviso del cambio dentro de la respuesta (Decisión 3) y versión corta para voz (Decisión 4)

- `core/reasoning_loop.py::run()` (línea 207-320): arma `final_text` en 3 puntos posibles
  (línea 260, 266, 288, más el fallback de la línea 300-305) y calcula
  `resolved_channel = security_manager.resolve_channel(channel)` en la línea 225 — antes de
  la primera llamada a `generate_response()`. Es, tal como dice la SPEC, el lugar natural
  para insertar el aviso y decidir la forma corta si `resolved_channel ==
  ChannelType.VOICE`. Hoy no hay ningún aviso de este tipo en ningún punto de la función.
- `ai/claude_brain.py::_resolver_con_tools()` (línea 121-194): arma la respuesta final en 2
  puntos (línea 165, 167, más el cierre de la línea 192-194) — usado por Telegram/Discord
  vía `ask_claude()`. Tampoco tiene hoy ningún aviso de cambio de modelo. No recibe
  `resolved_channel` como tal fuera de la variable local `canal` (línea 139); Telegram y
  Discord llegan aquí, nunca `ChannelType.VOICE`.
- `core/security_manager.py::ChannelType` (línea 59-65): `DESKTOP`, `TELEGRAM`, `DISCORD`,
  `VOICE`, `API`, más un canal no confiable adicional. `resolve_channel()` (línea 302-…) es
  la única función de resolución de canal del sistema, confirmado.
- `ui/webview/bridge.py::_on_voice_command()` (línea 1566-1577): confirma el riesgo P2
  heredado de REQ-021 mencionado en la SPEC — llama `self.send_message(text)` sin pasar
  ningún canal `VOICE` explícito, así que el manos libres del webview resuelve como
  `DESKTOP` en la práctica, no `VOICE`. Confirmado por lectura directa del código, no solo
  por lo heredado del contexto.
- `ui/tts_engine.py::prepare_for_speech()` (línea 79-…, con constantes y regexes de
  limpieza desde la línea 32): es hoy el ÚNICO lugar del sistema donde se decide "qué se
  pronuncia" (comentario explícito en el código, línea 24: "Único lugar del sistema donde
  se decide QUÉ se pronuncia (CA-27)"), consumido por `ui/cli.py::display_output` y
  `ui/webview/bridge.py::_speak_response`. Es el candidato natural para CA-18: acortar el
  aviso justo antes de que se lea en voz alta, sin depender de si el canal resuelto fue
  `VOICE` o `DESKTOP` — ya que ese único punto se ejecuta para ambos casos del manos libres
  del webview y de `ui/cli.py` en modo voz. No existe hoy ningún reconocimiento de "esto es
  un aviso de cambio de modelo" dentro de esta función — habría que decidir un marcador
  (texto fijo reconocible, o llamar a esta función con un flag) que la arquitectura debe
  definir.

---

## Archivos que serán modificados (previsión, confirmada contra el código real)

- `ui/webview/bridge.py` — `set_model()` (línea 1059), `_build_models_payload()` (línea
  1896). Confirmado: ambos existen tal como los describe la SPEC, con los números de línea
  correctos verificados hoy.
- `ui/webview/frontend/js/composer.js` — `alternarMenuDeModelos()` (línea 163) y
  `renderModels()` (línea 210). Confirmado: hoy no hay ningún estado deshabilitado, hay que
  agregarlo desde cero, no ajustar uno existente.
- `ui/webview/frontend/js/app.js` — `onModelsLoaded()` (línea 149). Confirmado: solo un
  puente sin lógica propia; el cambio real, si lo necesita, vive más bien en
  `renderModels()` de `composer.js`.
- `ai/llm_provider.py` — `_cadena_de_respaldo()` (línea 336), `_intentar_respaldos()`
  (línea 357-404, específicamente la rama de la línea 378-380), y posiblemente
  `generate_response()` (línea 241-333) si `orion-architect` decide que el aviso de
  Decisión 3 necesita que esta función exponga de algún modo que hubo un respaldo (hoy no
  lo expone de ninguna forma — ver más arriba). Confirmado como el módulo con más cambios.
- `config_manager.py` — sin cambios de esquema obligatorios, confirmado: `DEFAULT_CONFIG`
  no tiene `fallback_provider` hoy, y el REQ puede aplicar el default en tiempo de lectura
  (`get_provider_config()` o `_cadena_de_respaldo()`) sin escribir la clave.
- `core/reasoning_loop.py` — `run()` (línea 207-320), específicamente entre la línea 225
  (`resolved_channel`) y donde se arma `final_text` (líneas 260/266/288/300-305).
  Confirmado.
- `ai/claude_brain.py` — `_resolver_con_tools()` (línea 121-194). Confirmado.
- `ui/tts_engine.py` — `prepare_for_speech()` (línea 79 en adelante), como candidato para
  CA-18 según lo que decida `orion-architect`. `ui/cli.py` no fue necesario modificarlo
  para llegar a esta conclusión — es solo consumidor de `prepare_for_speech()`.
- `tests/` — nuevos tests para los 18 criterios; `tests/test_provider_fallback.py` es el
  archivo existente más cercano al punto 2 y probablemente el que se extienda en vez de
  crear uno nuevo, a criterio de `orion-dev`.

**Nota:** ningún archivo de esta lista difiere de lo que ya intuyó `orion-spec` en
SPEC-022.md — la lectura de código confirma nombres de función y números de línea, no
corrige ninguno.

---

## Fallos pre-existentes (no atribuibles a este REQ)

- **Compilación:** `python -m py_compile` sobre los 7 módulos Python afectados
  (`ui/webview/bridge.py`, `ai/llm_provider.py`, `config_manager.py`,
  `core/reasoning_loop.py`, `ai/claude_brain.py`, `ui/tts_engine.py`, `ui/cli.py`) —
  **sin errores**.
- **Suite completa** (`python -m pytest tests/ --tb=short -v`, 1763 tests): **1 fallo
  pre-existente, no relacionado con este REQ**:
  - `tests/test_task_slots.py::test_la_hora_dicha_se_respeta` — falla por
    `datetime.date(2026, 9, 7) == datetime.date(2026, 9, 6)`: el test calcula una fecha
    relativa a "ahora" y compara contra `datetime.date.today()` en dos momentos distintos
    de la ejecución, cruzando la medianoche del entorno de CI/test (el resultado trae
    `datetime.datetime(2026, 9, 7, 17, 0)`, no una medianoche real — sugiere una zona
    horaria o reloj del entorno de test corrido varias horas respecto al del sistema, no
    un bug de lógica). No tiene relación alguna con selección de modelo, fallback de
    proveedores, ni con ningún módulo de este REQ (`tests/test_task_slots.py` cubre
    interpretación de horarios dichos en lenguaje natural). **No atribuir este fallo a
    REQ-022** si reaparece después de implementar.
  - Los tests específicos de los módulos afectados por este REQ —
    `tests/test_provider_fallback.py` (14 tests), `tests/test_llm_provider.py` (8 tests),
    `tests/test_reasoning_loop.py` (15 tests), `tests/test_provider_health.py` (22
    tests) — **pasan los 65 sin excepción**. Ninguno de estos archivos tiene fallos
    pre-existentes que deban documentarse como riesgo.
  - Warnings no relacionados (no son fallos): `DeprecationWarning` de `aifc`/`audioop` en
    `speech_recognition` (Python 3.13 deprecará esos módulos), `PytestReturnNotNoneWarning`
    en `tests/test_agents.py::test_ca1_orchestrator`, e `InconsistentVersionWarning` de
    scikit-learn (modelo entrenado con una versión distinta de la instalada). Preexistentes,
    no bloqueantes, no relacionados con REQ-022.

---

## Nota sobre el punto explícitamente abierto (no resuelto acá)

El "cambio preventivo por cooldown" de `generate_response()` (línea 257-275) existe y
funciona hoy tal como lo describe el contexto: cambia de proveedor ANTES de intentar el
original, sin ningún aviso de ningún tipo. Esta observación es una confirmación de hecho
(el código se comporta así), **no una resolución** de si ese camino debe disparar el
aviso de la Decisión 3 — esa decisión sigue abierta para `orion-architect`, como ya
señalaba el contexto y la SPEC.
