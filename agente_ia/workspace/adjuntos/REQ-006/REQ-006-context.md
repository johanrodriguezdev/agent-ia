# Contexto REQ-006 — Pipeline único de resolución + bucle de agente con herramientas

## ✅ BLOQUEO DE SECUENCIA — LEVANTADO POR EL HUMANO (2026-08-04)

**Histórico (ya no aplica):** este REQ estuvo topado hasta spec+arquitectura porque REQ-005 tenía
código sin commitear y mezclar ediciones hacía imposible aislar qué rompió qué.

- **Estado real de REQ-005 al momento de levantar el bloqueo:** `LISTO_PARA_COMMIT`. La prueba
  manual del humano ya se hizo y quedó registrada (2026-08-02, `REQ-005-context.md`); QA aprobó
  (`qa-audit-005.md`, veredicto ✅). Lo único pendiente era el `git commit` en sí.
- **Decisión explícita del humano (2026-08-04):** "Empieza no voy a realizar commits por si hay
  que modificar algo" — instrucción directa de proceder con `orion-dev` en REQ-006 **sin esperar**
  el commit de REQ-005. Motivo dado: puede necesitar seguir modificando antes de commitear, y
  prefiere un solo commit combinado más adelante en vez de bloquear REQ-006 hasta entonces.
- **Consecuencia aceptada por el humano:** el árbol de trabajo mezclará cambios sin commitear de
  REQ-005 (ya completos, solo pendientes de `git commit`) con los nuevos de REQ-006. Si algo falla,
  aislar la causa exacta por archivo/línea (no por REQ) hasta que se separen con commits.
- Quien retome este REQ en otra sesión: el bloqueo **no se reactiva** solo porque `git status` siga
  mostrando cambios sin commitear — esa condición ya fue evaluada y aceptada explícitamente arriba.

Alcance ahora permitido: `orion-dev` puede escribir código para REQ-006 [A] (CA-01…CA-17), siguiendo
`propuestas/arquitectura-006.md` tal como quedó aprobada (incluidas las 3 correcciones de
`orion-security`).

---

## Resumen ejecutivo
Hoy el comportamiento de O.R.I.O.N. depende del canal por el que se entre y el motor de resolución
es un clasificador cerrado con handlers terminales, no un bucle de agente. Este REQ busca un
pipeline único de resolución con paridad entre canales (consola, GUI, Telegram, voz) y un bucle en
el que el agente razone, elija herramientas, vea el resultado y reaccione, en vez de quedarse con
la primera respuesta del handler.

## Estado actual
- **Estado tracker:** ARQUITECTURA_APROBADA
- **Último agente:** orion-architect
- **Fecha última actualización:** 2026-08-02
- **Rama git:** `feature/REQ-006-pipeline-unico-resolucion` (confirmada al aprobarse la arquitectura)
- **Categoría:** CORE
- **Tipo de cambio:** REFACTOR + FEATURE_NUEVA
- **SPEC:** `workspace/adjuntos/REQ-006/spec/SPEC-006.md` — ✅ APROBADA por el humano (2026-08-02)
- **Arquitectura:** `workspace/adjuntos/REQ-006/propuestas/arquitectura-006.md` — ✅ **APROBADA por el
  humano (2026-08-02)**, incluida la corrección final sobre el hueco real de gating (`learned`, no
  "routine y learned")
- **Ejecución:** REQ-006 = criterios **[A]** (CA-01…CA-17) | REQ-007 = criterios **[B]** (CA-18…CA-24),
  con **una sola arquitectura compartida**. REQ-007 no arranca hasta que [A] avance.
- **Siguiente agente:** `orion-security` (no `orion-dev` directo) — la arquitectura toca
  `core/security_manager.py` (reemplaza `input()` por adaptadores, agrega `ActionDenied`) y cierra
  un bypass real de seguridad (`GlassGateway` invocando `task_manager` sin gate). Ruteo decidido por
  orion-coordinador.
- **NO se modificó ningún `.py`** — bloqueo de secuencia respetado (ver arriba); el REQ-005 sigue en
  `EN_QA` sin commitear.

## Petición original del humano
> "Quiero que O.R.I.O.N. funcione igual en todos los canales, es decir desde cualquier chat o desde
> la interfaz visual, por audio o texto. Y quiero que razone, elija herramientas, vea el resultado y
> reaccione, en vez de quedarse solo con lo que tiene."

Son dos caras del mismo problema: paridad de canales y motor de resolución agéntico.

## Diagnóstico ya verificado en código (NO re-descubrir)
Confirmado leyendo los archivos. `orion-spec` y `orion-architect` arrancan de acá.

1. **El clasificador cortocircuita al agente.** En `core/orchestrator.py:process_task()`,
   `_try_quick_dispatch()` clasifica y, si el intent es conocido, ejecuta el handler legacy y
   **retorna de inmediato**. `_process_with_agents` solo corre si el intent es `UNKNOWN`. La capa
   inteligente es el último recurso, no el cerebro: una clasificación segura pero equivocada
   bloquea al agente de forma permanente.
2. **Los handlers son terminales.** `router/dispatcher.py` mapea ~26 intents fijos a handlers cuyo
   string de retorno *es* la respuesta final. `handle_wikipedia_summary` devuelve "no encontré" y ahí
   muere: no hay escalado a otra herramienta ni reacción del agente al fracaso. Este es el síntoma
   que el humano reporta como "se queda ahí".
3. **Capacidad construida e inalcanzable.** `tasks/task_manager.py` es un subsistema completo
   (fechas naturales, recurrencias) con `tasks/task_scheduler.py` disparando avisos, pero solo lo
   consumen `channels/telegram_bot.py` y `channels/gateway.py`. **No existe ningún `Intent` de
   recordatorio, ninguna skill que lo envuelva, ni ninguna `AgentTool` registrada.** Por eso el
   humano pidió un recordatorio por escritorio y no pasó nada: no había ruta.
4. **Pipelines divergentes por canal.** `main.py` y `channels/gateway.py` resuelven en órdenes
   distintos, y `channels/telegram_bot.py` hace matching propio de frases (ej. apagado) ANTES de
   entregar al gateway. El mismo comando puede funcionar por consola y fallar por Telegram. Causa
   raíz de la falta de paridad.
5. **Bugs relacionados ya verificados** — algunos ya están en cola para arreglo aparte.
   **La spec decide si entran en este REQ o quedan fuera:**
   - `main.py:34` — `return 0.0 if "briefing" in task.lower() or "recordatorio" in task.lower() else 0.0`:
     las dos ramas devuelven `0.0`, así que `_ProactiveAssistant` nunca se activa.
   - `core/orchestrator.py:87-98` — `_decompose()` compara por subcadena y parte por la **letra** "y":
     `"ayúdame con el proyecto"` → `["a", "údame con el pro", "ecto"]`, cada fragmento a un agente distinto.
   - `skills/skill_manager.py:32` — `exec_module()` fuera de todo `try`: un `SyntaxError` en cualquier
     skill aborta la carga completa.
   - `skills/skill_manager.py:46` — `register_skill()` pisa intents en silencio.
   - `ai/llm_provider.py:27` — `_cached_call()` cachea los errores, descartando al proveedor primario
     hasta reiniciar.

## Restricciones que la spec debe respetar
- **No romper REQ-005.** El gate de `security_manager.require_confirmation()` es fail-closed y debe
  seguir siéndolo. Si el agente gana libertad para elegir herramientas, **cada herramienta debe entrar
  clasificada y gateada** — hoy las de skills ya lo hacen vía `_make_gated_tool_fn` en
  `skills/skill_manager.py`. Más capacidad NO significa menos control: significa más acciones
  correctamente clasificadas.
- **El core no debe volverse `async`.** Señalado como el riesgo principal de unificar canales: un
  contrato `async` contagia async a todo el core. Criterio de aceptación sugerido: *el core no
  incorpora ni un `async def` nuevo*.
- **PyQt6 necesita el hilo principal** → no fusionar los procesos de escritorio y bots.
- **El nivel de riesgo se queda en `security_manager`**, no se delega al canal. El canal solo declara
  sus capacidades (por ejemplo, si soporta confirmaciones interactivas).

## Material de referencia obligatorio (spec y arquitectura)
Ya está escrito y es autosuficiente:
- `workspace/referencias/openclaw/02-gateway-canales-ruteo.md` — contrato de canal. Sus **§7 y §8**
  traen veredictos directos sobre esto, incluido que `start_bots.py` **ya es** un anfitrión persistente
  multi-canal con supervisión → la unificación es un **refactor**, no una construcción desde cero.
- `workspace/referencias/openclaw/04-skills-y-proveedores.md` — registro de herramientas y proveedores.
- `workspace/referencias/openclaw/01-seguridad-y-aislamiento.md` — aislamiento.

## Decisión de alcance — RESUELTA 2026-08-02
El humano **aprobó partir el REQ**:
- **REQ-006 = criterios [A]** — pipeline único de resolución con paridad de canales.
- **REQ-007 = criterios [B]** — bucle de razonamiento con herramientas.
- **UNA SOLA ARQUITECTURA compartida.** `orion-architect` diseña ambas mitades en un único
  documento; se parte **solo la ejecución**. ⚠️ Quien tome REQ-007 **no rediseña**: sigue esa
  arquitectura.

Reparto de los 2 bugs aprobado: `main.py:34` (`can_handle()`) → **[A]** (CA-12);
`core/orchestrator.py:87-98` (`_decompose()`) → **[B]** (CA-24).

## Fuera de alcance
- **Implementación del cliente MCP.** Ver el cambio de postura abajo: MCP **ya no está diferido**,
  pero el cliente se implementa en su propio REQ de categoría **INTEGRACION**. REQ-006 solo fija el
  **contrato** de herramienta (CA-14 a CA-17).
- **Convertir a `pytest` los 4 archivos de test que colectan 0** (`test_classifier.py`,
  `test_dispatcher.py`, `test_autopilot.py`, `test_memory.py`). Solo se construye la línea base de
  clasificación y ruteo (CA-13). El resto queda como deuda registrada.
- **Los otros 3 bugs del diagnóstico** (`skills/skill_manager.py:32`, `:46`,
  `ai/llm_provider.py:27`): fix independiente, nadie los toca acá.
- **Convertir O.R.I.O.N. en multi-usuario.** Confirmado por el humano: no hace falta. SIGAIND
  resuelve permisos por el usuario asociado al token; O.R.I.O.N. solo porta el token (CA-17).
- **Modificar la matriz `CHANNEL_ALLOWED_LEVELS`.** Explícitamente prohibido en esta SPEC. Abrir el
  amarillo en canales remotos es una decisión posterior, con `orion-security`.

## Decisiones tomadas
<!-- FECHA | AGENTE | DECISIÓN | MOTIVO -->
2026-08-01 | orion-coordinador | REQ creado — categoría=CORE | Detección por palabras clave: "main loop", "dispatcher", "classifier", "router", "handlers", "orchestrator". El corazón del cambio es el motor de resolución (`core/orchestrator.py`, `router/dispatcher.py`), no un canal concreto.
2026-08-01 | orion-coordinador | Cross-cut reconocido con BOT y SKILL | Toca `channels/telegram_bot.py`, `channels/gateway.py` y el registro de herramientas de `skills/skill_manager.py`, pero se clasifica CORE porque la causa raíz y el diseño viven en el core.
2026-08-01 | orion-coordinador | Avance limitado a spec + baseline + arquitectura | REQ-005 en EN_QA con código sin commitear en el árbol de trabajo — ver bloqueo de secuencia arriba.
2026-08-01 | orion-spec | Tipo de cambio: REFACTOR + FEATURE_NUEVA | Refactor del pipeline de resolución existente + construcción de un bucle agéntico que hoy no existe (ver H7).
2026-08-01 | orion-spec | Paridad = misma inteligencia, permisos por canal | Decisión del humano. La restricción de voz (solo verde) de `.claude/rules/security-levels.md` SE MANTIENE: el micrófono no autentica y un error de STT puede disparar una acción destructiva. La paridad es de *capacidad de razonamiento*, no de *autoridad*: mismo pipeline, mismo plan, mismo punto de decisión; solo difiere el veredicto del gate. Redactado como norma en SPEC-006 (CA-04/05/06) para que QA no lo lea como incumplimiento.
2026-08-01 | orion-spec | Alcance de bugs: solo los 2 del orquestador | Decisión del humano. ENTRAN `core/orchestrator.py:87-98` (`_decompose()`) y `main.py:34` (`can_handle()`) porque viven en el código que este REQ reescribe. QUEDAN FUERA `skills/skill_manager.py:32`, `:46` y `ai/llm_provider.py:27` → fix independiente. Nadie los toca en REQ-006.
2026-08-01 | orion-spec | SPEC-006.md redactado con 19 criterios de aceptación testeables | Etiquetados [A] (pipeline/paridad) y [B] (bucle de razonamiento) para que el corte de la partición ya esté trazado. Estado: ⏸️ ESPERANDO VALIDACIÓN.
2026-08-01 | orion-spec | Recomendación de partición: DOS REQ de implementación, UNA sola arquitectura | Motivos: (1) el riesgo de regresión es de naturaleza distinta —[A] determinista, [B] no determinista con LLM— y en un solo commit una regresión no se puede atribuir; (2) [A] toca el gate de seguridad (H5) y debe auditarse sin el ruido de un bucle de LLM; (3) [A] entrega valor observable sola (cierra el agujero de voz, da paridad Telegram/consola, vuelve alcanzable `task_manager`); (4) la dependencia es unidireccional —[B] necesita [A], no al revés—.
2026-08-02 | orion-spec | **PARTICIÓN APROBADA por el humano** — REQ-006 = [A], REQ-007 = [B], arquitectura ÚNICA compartida | Se parte solo la ejecución, no el diseño. `orion-architect` produce un único documento que cubre pipeline, contrato de canal, registro de herramientas y bucle, para no tomar en [A] ninguna decisión que cierre puertas a [B]. Quien ejecute REQ-007 NO rediseña.
2026-08-02 | orion-spec | **Reparto de bugs aprobado** — `main.py:34` (`can_handle()`) → [A]/CA-12; `core/orchestrator.py:87-98` (`_decompose()`) → [B]/CA-24 | Cada bug viaja con el código que lo reescribe. `_decompose()` probablemente desaparezca al construir el bucle. Ninguno se difiere ni se pierde.
2026-08-02 | orion-spec | **H5 se cierra dentro de [A], sin hotfix adelantado** | Decisión del humano. El bloqueo de secuencia se mantiene: no se parchea `main.py` ahora. Riesgo residual ACEPTADO y registrado: explotarlo requiere acceso físico al micrófono, no es explotable remotamente y ningún canal externo puede provocarlo.
2026-08-02 | orion-spec | **H7 se redacta como CONSTRUCCIÓN, no como reparación** | Decisión del humano. El bucle agéntico no existe: `_DynamicAgentInstance.execute()` nunca consulta un LLM. Prohibido en la SPEC el lenguaje de "mejorar/reparar el bucle". Se suma CA-09: la denegación del gate debe ser distinguible del éxito mediante un resultado estructurado, **nunca** por comparación de subcadena (hoy `"⛔ Acción no autorizada."` se lee como éxito porque `result[:10]` no contiene `"Error"`).
2026-08-02 | orion-spec | **H6 entra al REQ** como CA-23 | Decisión del humano. Se ataca como consecuencia de que agregar capacidades deje de depender del clasificador.
2026-08-02 | orion-spec | **Criterio de cobertura (H8) ampliado** a reconocimiento de intent **Y** ruteo a la herramienta correcta, medido antes/después | Decisión del humano. Congelar solo la predicción del clasificador no detecta la regresión que importa: que el intent se reconozca bien pero termine en la herramienta equivocada. CA-13.
2026-08-02 | orion-spec | **MCP DEJA DE ESTAR DIFERIDO** — cambio de postura del humano | Motivo: *"me están solicitando la conexión del agente con SIGAIND"*. El **cliente** MCP va en su propio REQ de categoría INTEGRACION. REQ-006 solo fija el CONTRATO: (a) isomorfo a una tool MCP —nombre, descripción, parámetros en JSON Schema, resultado— de modo que las 31 tools de SIGAIND se describan sin traductor (CA-14); (b) nivel de riesgo **declarable** por la herramienta, como entrada al gate y no como autorización (CA-15); (c) admite fuentes remotas descubiertas en runtime, sin recompilar ni tocar el core (CA-16); (d) no exige multi-usuario: `empId` y permisos salen del token de SIGAIND (CA-17). Referencia obligatoria: `.claude/skills/skill-mcp-sigaind-v01.md`.
2026-08-02 | orion-spec | **H9 entra como criterio nuevo de [A]** — confirmación agnóstica del canal (CA-10) | Aportado por el humano. Hoy `require_confirmation()` pide la confirmación con `input()` en `core/security_manager.py:240`, atada al stdin de la consola; que el amarillo esté bloqueado en canales remotos es una **consecuencia técnica**, no una política, y contradice `.claude/rules/security-levels.md`, que dice que en Telegram/Discord el amarillo "siempre requiere confirmación explícita". LÍMITES ESTRICTOS, textuales del humano: esto **no relaja la seguridad**; **no se modifica `CHANNEL_ALLOWED_LEVELS`** en esta SPEC; **ROJO no se toca** —sigue bloqueado en todos los canales, con la excepción del PIN maestro solo en DESKTOP—. Motivación de negocio: que el bot de Telegram sea realmente funcional.
2026-08-02 | orion-spec | SPEC-006.md cerrada con **24 criterios** (CA-01…CA-17 = [A], CA-18…CA-24 = [B]) | Cero preguntas abiertas. Estado: ⏸️ ESPERANDO VALIDACIÓN HUMANA de la SPEC. No se avanzó a SPEC_APROBADO, no se emitió handoff, no se modificó ningún `.py`.
2026-08-02 | orion-spec | **SPEC-006 APROBADA por el humano** — mensaje directo "Apruebo", relayado por orion-coordinador | Aprobación humana genuina y explícita (no notificación de sistema). Aplica a la SPEC completa: los 24 criterios CA-01 a CA-24 y la partición REQ-006 [A] / REQ-007 [B] con arquitectura única. Tracker actualizado a SPEC_APROBADO vía `update-tracker.mjs`. Handoff emitido a `orion-baseline` para REQ-006. REQ-007 NO arranca todavía — su baseline/arquitectura llega después de que [A] avance.
2026-08-02 | orion-baseline | Confirmado H8 con `pytest --collect-only`, no asumido | `tests/test_classifier.py`, `test_dispatcher.py`, `test_autopilot.py`, `test_memory.py` colectan 0 tests cada uno. `pytest tests/` corre 54/54 en verde (49 de `test_security_manager.py` + 5 de `test_agents.py`) — cero fallos pre-existentes. Línea base exacta para CA-07 y CA-13.
2026-08-02 | orion-baseline | **Hallazgo nuevo — TERCER motor de resolución, no solo dos (aportado por orion-coordinador, verificado en código)** | `channels/gateway.py:GlassGateway.process()` (líneas 42-108), usado por los 4 handlers de `telegram_bot.py`, es un pipeline propio completo con su propio pre-matching de tareas (`_try_create_task/_try_list_tasks/_try_complete_task`) y su propio fallback de IA a `ai/claude_brain.py:ask_claude()` — distinto del agente de `core/base_agent.py`. `main.py` no pasa por `GlassGateway` en absoluto. Son 3 superficies de resolución con capacidades distintas, no 2. Ver `baseline-006.md` sección 3. CA-01 (punto único de resolución) debe absorber los tres.
2026-08-02 | orion-baseline | **Riesgo nuevo verificado — `_try_create_task()` de `GlassGateway` crea tareas sin pasar por el gate** | `channels/gateway.py:110-148` llama `task_manager.create_from_natural()` sin invocar `security_manager.require_confirmation()` en ningún punto del método — a diferencia de `_handle_shutdown`/`_handle_restart` de Telegram, que sí ya gatean (trabajo de REQ-005 sin commitear). Queda para que `orion-architect` lo cierre al envolver `task_manager` como herramienta gateada (H3, CA-07).
2026-08-02 | orion-baseline | **Pregunta abierta para orion-architect (no bloqueante, no requiere al humano)** | No se verificó si `ai/claude_brain.py:ask_claude()` comparte historial de conversación con `agent_context_manager` (el que usa `core/orchestrator.py`). Confirmar antes de diseñar cómo el punto único de resolución absorbe el fallback de Claude Brain de `GlassGateway`.

## Hallazgos nuevos verificados por orion-spec (NO re-descubrir)
Se suman a los 4 del diagnóstico del coordinador. Todos verificados en código durante la SPEC.

- **H5 — El canal `voice` NUNCA se emite; la restricción de voz es letra muerta.** `ChannelType.VOICE`
  existe y está limitado a `[RiskLevel.GREEN]` en `core/security_manager.py:29-36`, pero ninguna ruta
  pasa `"voice"`. Las entradas por micrófono de `main.py` (`choice == '2'` y `'3'`, líneas 80-97)
  caen en el mismo bloque que el texto, y las seis rutas de despacho hardcodean `channel="desktop"`
  (`main.py:40, 108, 136, 155, 167, 203`). **Hoy una orden dictada por micrófono se evalúa como
  DESKTOP y puede ejecutar acciones AMARILLAS.** Agujero de seguridad real, no discusión de redacción.
- **H6 — Modelo persistido obsoleto; el training data de las skills es código muerto.**
  `_load_or_train()` carga `intent/saved_model.pkl` (25-abr) y solo entrena si falta;
  `intent/ai_classifier.py` con las ~254 frases se modificó el 7-jun. El modelo en uso lleva seis
  semanas sin reflejar su propio dataset. Como `get_all_training_data()` de las skills solo se
  consulta **dentro de `_train()`**, una skill nueva jamás entra al clasificador mientras el `.pkl`
  siga en disco. Explicación mecánica de por qué "agregar capacidades no sirve de nada".
- **H7 — El "bucle de agente" no razona.** `core/base_agent.py:_DynamicAgentInstance.execute()` itera
  `self.tools` y devuelve la primera cuyo `result[:10]` no contenga `"Error"`. **No se consulta ningún
  LLM**: el `system_prompt` de `_generate_prompt()` nunca se usa y `DynamicAgentFactory._llm` nunca se
  lee. Además (a) `main.py:16-20` registra `dispatcher` como primera herramienta, así que el legacy
  siempre gana; (b) el heurístico trata `"⛔ Acción no autorizada."` como **éxito** y corta la cadena.
  El bucle agéntico hay que **construirlo**, no repararlo.
- **H8 — Cero cobertura de tests sobre clasificación y dispatcher.** `pytest` colecta 54 tests: 49 de
  `tests/test_security_manager.py` (REQ-005) y 5 de `tests/test_agents.py`. `test_classifier.py`,
  `test_dispatcher.py`, `test_autopilot.py` y `test_memory.py` colectan **0 cada uno** (scripts con
  `run_tests()` y `print`, sin `assert`). Hoy una regresión de clasificación es **silenciosa**.
- **H9 — La confirmación está atada a la consola.** `core/security_manager.py:233` descarta el
  amarillo **por canal** antes de que la línea `:240` llegue a pedir `input(...)`. Es decir: el único
  motivo por el que el proceso no se cuelga esperando un stdin inexistente es ese chequeo previo. El
  amarillo bloqueado en Telegram/Discord es una **consecuencia técnica del mecanismo**, no una
  política deliberada — y contradice `.claude/rules/security-levels.md`, que dice que en esos canales
  el amarillo "siempre requiere confirmación explícita". Aportado por el humano; cerrado por CA-10.
  **Límites innegociables:** no relaja la seguridad, `CHANNEL_ALLOWED_LEVELS` **no se modifica** en
  este REQ, y ROJO no se toca.
- **Costo a eliminar:** `TfidfVectorizer(1,3)` + `LinearSVC(C=1.5)` sobre ~254 frases y 28 intents.
  `LinearSVC` es multiclase one-vs-rest → cada intent nuevo redibuja las fronteras de todos los demás.
  Sumar una capacidad puede degradar otra, y por H8 degradarla sin que nadie se entere.

## Descartado (y por qué)
<!-- Opciones evaluadas y rechazadas — evita repetir el debate -->
- **Categoría BOT:** descartada. La falta de paridad es un síntoma; la causa raíz es que cada canal
  resuelve con su propio pipeline. El diseño se corrige en el core.
- ~~**Implementar MCP en este REQ:** descartado por indicación explícita del humano~~ →
  **REVERTIDO 2026-08-02.** El humano cambió de postura por una solicitud externa de conectar el
  agente con SIGAIND. MCP ya no está diferido: el **cliente** va en un REQ propio de categoría
  INTEGRACION, y REQ-006 fija el **contrato** de herramienta (CA-14…CA-17). Ver "Decisiones tomadas".
- **Rediseñar O.R.I.O.N. como multi-usuario para soportar MCP:** descartado. SIGAIND deriva `empId`
  y los permisos del token; basta con portar el token.
- **Abrir el amarillo en Telegram modificando `CHANNEL_ALLOWED_LEVELS`:** descartado en este REQ.
  CA-10 desacopla el *mecanismo* de confirmación del stdin; la *política* de qué nivel admite cada
  canal no se toca.
- **Convertir el core a `async` para unificar canales:** descartado de entrada como riesgo principal
  (contagia async a todo el core).

## Asumidos pendientes de confirmar
- ~~Que los 5 bugs del punto 5 entran en este REQ~~ → **RESUELTO 2026-08-01**: solo los 2 del
  orquestador. Ver "Decisiones tomadas".
- ~~Que la paridad incluye el canal de voz con las mismas capacidades~~ → **RESUELTO 2026-08-01**:
  paridad de razonamiento, no de autoridad. Voz sigue restringida a verde. Ver "Decisiones tomadas".
- ~~Que el REQ va entero vs. partido en dos~~ → **RESUELTO 2026-08-02**: partido, con arquitectura
  única. Ver "Decisión de alcance — RESUELTA".
- **ASUMIDO** (confirmar con `orion-architect`): el punto único de resolución es **síncrono** y los
  canales asíncronos lo invocan desde su borde (CA-11).
- **ASUMIDO** (confirmar con `orion-architect`): el mecanismo de confirmación agnóstica de CA-10
  respeta esa misma frontera — el core **no** se vuelve `async` para poder preguntar por Telegram.
  Es la decisión de diseño más delicada de [A].
- **ASUMIDO** (confirmar antes de implementar): la GUI PyQt6 entra al pipeline como canal `desktop`,
  no como un `ChannelType` propio.
- **ASUMIDO**: `ChannelType.API` y `ChannelType.DISCORD` quedan sin cambios de permisos en este REQ.
- **ASUMIDO**: la línea base de CA-13 congela la predicción **actual** del modelo y el ruteo actual
  — no como "clasificación correcta", sino como "comportamiento que no debe cambiar sin decisión
  explícita".
- **ASUMIDO**: el contrato de herramienta de CA-14 se valida contra el discovery de
  `.claude/skills/skill-mcp-sigaind-v01.md` **en papel**, comparando formas. No se implementa ni se
  invoca ningún cliente MCP en este REQ.

## Preguntas abiertas para el humano
**Ninguna.** Las 5 preguntas que bloqueaban el avance fueron respondidas el 2026-08-02 y están
incorporadas en "Decisiones tomadas" y como criterios de SPEC-006:

| Pregunta | Respuesta | Dónde quedó |
|----------|-----------|-------------|
| ¿Partición? | Sí, con arquitectura única | REQ-006 [A] / REQ-007 [B] |
| ¿Reparto de los 2 bugs? | Sí: `can_handle` → [A], `_decompose()` → [B] | CA-12, CA-24 |
| ¿H5 dentro o hotfix adelantado? | Dentro de [A]; riesgo residual aceptado | CA-05, CA-06 |
| ¿H6 dentro o separado? | Dentro | CA-23 |
| ¿H8 solo corpus o convertir los 4 archivos? | Solo la línea base, ampliada a **ruteo** | CA-13 |

Lo único pendiente es la **aprobación humana de SPEC-006**.

## Riesgos activos
- **Contaminación con REQ-005 sin commitear** — mitigado por el bloqueo de secuencia de arriba.
- **Regresión del gate fail-closed de REQ-005** si el agente gana libertad para elegir herramientas
  sin que cada herramienta esté clasificada. Mitigación: toda herramienta nueva pasa por
  `security_manager` antes de ser invocable.
- **Contagio de `async` al core** al unificar canales, incluido el camino nuevo de confirmación por
  canal asíncrono (CA-10). Mitigación: CA-11 como criterio duro, con mención explícita a ese camino.
- ~~**Alcance excesivo para un solo REQ**~~ → **RESUELTO 2026-08-02**: partición aprobada.
- ~~**Paridad de canales vs. restricción de voz**~~ → **RESUELTO 2026-08-01** por decisión del humano:
  paridad de razonamiento, no de autoridad. Ya no es tensión, es norma escrita en SPEC-006.
- **[NUEVO — orion-spec] Agujero de permisos por voz en producción (H5).** No es un riesgo futuro:
  el micrófono de escritorio ejecuta hoy con permisos `desktop` y puede disparar acciones amarillas.
  Mitigación: CA-05/CA-06. Mientras el bloqueo de secuencia esté vigente **no se puede parchear**.
- **[NUEVO — orion-spec] Regresión de clasificación silenciosa (H8).** Cero tests colectados sobre
  clasificación y dispatcher. Cualquier cambio al clasificador es hoy invisible hasta que un humano
  lo note en uso. Mitigación: CA-16 debe construirse **antes** de tocar el clasificador.
- **[NUEVO — orion-spec] El bucle agéntico no existe (H7).** El REQ es más construcción que refactor
  en su mitad [B]. Impacta la estimación y sostuvo la decisión de partir.
- **[NUEVO — orion-spec] Denegación del gate indistinguible del éxito (H7, parte b).** Defecto activo
  hoy: `_DynamicAgentInstance.execute()` acepta `"⛔ Acción no autorizada."` como resultado válido
  porque `result[:10]` no contiene `"Error"`, y corta la cadena ahí. Mitigación: CA-09, resultado
  estructurado y prohibición de comparar por subcadena.
- **[NUEVO — orion-spec] Cuelgue por `input()` sin stdin interactivo (H9).** Hoy el único motivo por
  el que no ocurre es el chequeo de canal previo en `core/security_manager.py:233`. Cualquier ruta
  que llegue a `:240` desde un scheduler, un hilo de fondo o el canal `API` bloquea el proceso.
  Mitigación: CA-10(e).
- **[NUEVO — orion-spec] Que CA-10 se lea como permiso para abrir el amarillo en Telegram.**
  Mitigación: la SPEC lo prohíbe explícitamente — `CHANNEL_ALLOWED_LEVELS` no se modifica, ROJO no se
  toca. CA-10 desacopla el mecanismo, no la política.
- **[NUEVO — orion-spec] Compromiso externo ya asumido con SIGAIND.** Si el contrato de herramienta
  no queda isomorfo a una tool MCP, el REQ de INTEGRACION posterior obligará a escribir un traductor
  o a rehacer el contrato. Mitigación: CA-14…CA-17, validadas en papel contra
  `.claude/skills/skill-mcp-sigaind-v01.md`.
- **[NUEVO — orion-spec] Que REQ-007 rediseñe por su cuenta y diverja de [A].** Mitigación: una sola
  arquitectura compartida, declarada en el encabezado de SPEC-006.
- **[NUEVO — orion-baseline] Tercer motor de resolución no contemplado en el diagnóstico original
  (`GlassGateway.process()`).** No es solo main.py vs. dispatcher/orchestrator: Telegram entero pasa
  por un tercer pipeline con su propio pre-matching de tareas y su propio fallback a
  `ai/claude_brain.py`. Mitigación: CA-01 debe diseñarse para absorber los tres motores — señalado
  explícitamente a `orion-architect`. Ver `baseline-006.md` sección 3.
- **[NUEVO — orion-baseline] `_try_create_task()` de `GlassGateway` crea tareas sin gate de
  seguridad.** A diferencia de `_handle_shutdown`/`_handle_restart` de Telegram (ya gateados),
  `channels/gateway.py:110-148` invoca `task_manager.create_from_natural()` sin pasar por
  `security_manager.require_confirmation()`. Mitigación: cerrar al envolver `task_manager` como
  herramienta gateada en [A] (H3, CA-07).

## Log de transiciones
<!-- FECHA | DE → A | AGENTE | NOTA -->
2026-08-01 | — → NUEVO | orion-coordinador | REQ creado. Handoff a orion-spec. Avance topado en arquitectura hasta que se cierre REQ-005.
2026-08-01 | NUEVO → EN_SPEC | orion-spec | SPEC-006.md redactado con 19 CA testeables + 4 hallazgos nuevos (H5-H8). NO se modificó ningún .py — bloqueo de secuencia respetado. ⏸️ Esperando aprobación humana de la SPEC y de la decisión de partición. NO avanzar a orion-baseline sin ella.
2026-08-02 | EN_SPEC → EN_SPEC | orion-spec | SPEC-006.md cerrada con **24 CA** (CA-01…CA-17 = [A] → REQ-006; CA-18…CA-24 = [B] → REQ-007) + H9 como hallazgo nuevo. Incorporadas las 7 decisiones del humano: partición aprobada con arquitectura única, reparto de bugs, H5 dentro sin hotfix, H7 como construcción + denegación distinguible, H6 dentro, cobertura ampliada a ruteo, MCP ya no diferido, confirmación agnóstica del canal. **Cero preguntas abiertas.** NO se modificó ningún .py. Estado del tracker se mantiene en EN_SPEC y `Aprobacion_SPEC` vacío a propósito. ⏸️ Esperando aprobación humana de la SPEC. NO avanzar a SPEC_APROBADO ni a orion-baseline, NO emitir handoff, sin ella.
2026-08-02 | EN_SPEC → SPEC_APROBADO | orion-spec | Humano respondió "Apruebo" (mensaje directo, relayado por orion-coordinador). SPEC-006 completa aprobada: 24 criterios + partición [A]/[B] con arquitectura única. Handoff emitido a `orion-baseline` para REQ-006. REQ-007 queda en espera — no arranca hasta que [A] avance.
2026-08-02 | SPEC_APROBADO → EN_BASELINE | orion-baseline | Baseline de REQ-006 [A] completado. Los 5 archivos núcleo (`main.py`, `core/orchestrator.py`, `router/dispatcher.py`, `core/base_agent.py`, `core/security_manager.py`) leídos completos y verificados línea por línea contra H1-H9 de SPEC-006 — sin discrepancias. Se sumó verificación de `channels/gateway.py` y `channels/telegram_bot.py` (H4). Ver `workspace/adjuntos/REQ-006/origen/baseline-006.md`. NO se modificó ningún `.py` — bloqueo de secuencia respetado.
2026-08-02 | EN_BASELINE → EN_BASELINE | orion-architect | Arquitectura de REQ-006 (única, cubre [A] CA-01…CA-17 a ejecutar y [B] CA-18…CA-24 como diseño de referencia) redactada en `workspace/adjuntos/REQ-006/propuestas/arquitectura-006.md`, escrita de forma incremental (4 tandas guardadas a medida que se completaban las secciones). Pregunta abierta de baseline sobre `ask_claude()`/`agent_context_manager` resuelta explícitamente (no comparten historial, no se unifican). NO se modificó ningún `.py`. ⏸️ Esperando aprobación humana explícita de la arquitectura. NO avanzar el Estado tracker a `ARQUITECTURA_APROBADA`, NO tocar el CSV, NO emitir handoff a `orion-dev` sin ella.
2026-08-02 | EN_BASELINE → EN_BASELINE | orion-architect | Antes de la aprobación, orion-coordinador reportó una revisión propia de la fila de riesgo sobre resolvers heredados sin gate, con una corrección parcialmente incorrecta (afirmaba que `routine` no estaba gateado). orion-architect re-verificó leyendo `learning/routines_engine.py`, `learning/command_learning.py` y `agents/action_registry.py` completos: `routine` SÍ está gateado por construcción (mismo camino que `autopilot`, vía `execute_action()`), el hueco real es solo `learned` (gateado hoy solo de forma incidental vía el callback que le pasa `main.py`). Documento corregido (fila de riesgo + diagrama de flujo de datos) y un bug de formato de tabla markdown detectado de paso (fila sin `\|` inicial). Contra-corrección reportada a orion-coordinador vía SendMessage antes de que este presentara la arquitectura al humano.
2026-08-02 | EN_BASELINE → ARQUITECTURA_APROBADA | orion-architect | Humano respondió "APROBADO" (mensaje directo, relayado por orion-coordinador) — aplica a `arquitectura-006.md` completa, incluida la corrección final sobre el hueco real de gating (`learned`, no "routine y learned"). Rama `feature/REQ-006-pipeline-unico-resolucion` confirmada. CSV actualizado vía `update-tracker.mjs`. Por indicación de orion-coordinador, el siguiente paso del pipeline es `orion-security` (no `orion-dev` directo) — la arquitectura toca `core/security_manager.py` y cierra un bypass de seguridad real (H3, `GlassGateway._try_create_task` sin gate). Handoff emitido a `@orion-security`.
2026-08-02 | ARQUITECTURA_APROBADA → ARQUITECTURA_APROBADA | orion-architect | orion-security auditó `arquitectura-006.md` — veredicto APROBADO CON OBSERVACIONES (no reabre CA-01..CA-13 ni [B]) y señaló 3 hallazgos puntuales, los 3 corregidos en el documento (no dejados como restricción documentada, se optó por ajustar): (1) Observación A — la referencia a un adaptador `AgentTool↔ToolSpec` "ver abajo" en `core/base_agent.py` no tenía sección real; sin consumidor vivo en [A] pero riesgo de fijar la forma insegura (`AgentTool(function=spec.invoke)`, bypass de `execute_tool()`) si `orion-dev` lo implementaba a ciegas. Resuelto sacándolo explícitamente del alcance de [A] — ningún CA-01..CA-17 lo requiere, [B] (`core/reasoning_loop.py`) no reutiliza `AgentTool` y ejecuta siempre vía `execute_tool()`. (2) Hallazgo 1.7 — la mitigación de `learned` (test de regresión sobre el callback actual) no impedía estructuralmente un futuro segundo caller sin gate. Reforzada: `_try_learned` no acepta callback externo, la función que ejecuta acciones aprendidas es privada de `resolution.py` y siempre hace `classify_command() → dispatch()`; el test queda como red adicional. (3) Observación B (menor, no bloqueante) — la invariante de `channel` (nunca se re-infiere de params/texto libre, ya escrita en `security_manager.py:214-221`) no tenía equivalente documentado para `user_id` en `task_create/list/complete`; agregada como regla explícita. Los 3 ajustes están en `arquitectura-006.md`. No se re-solicitó aprobación humana (no cambian alcance, CA cubiertos, ni módulos a tocar — son precisión/cierre de ambigüedad sobre lo ya aprobado). Ofrecida re-auditoría a orion-security antes de continuar a `orion-dev`.

## Decisiones tomadas
2026-08-02 | orion-architect | Pregunta abierta resuelta: `ask_claude()` NO comparte historial con `agent_context_manager` | Verificado leyendo ambos archivos completos — `ai/claude_brain.py:10` usa un dict módulo-global en memoria, indexado solo por `user_id`; `core/agent_context.py` es otra clase, indexada por `(agent_name,user_id)`, persistida en SQLite. Cero conexión entre ambos hoy.
2026-08-02 | orion-architect | No se unifican ambos historiales de conversación en este REQ | Cambiar el comportamiento de memoria de Claude Brain no está en la SPEC y agrega riesgo no pedido. El pipeline único registra el intercambio en `agent_context_manager` (para trazabilidad, CA-03) pero deja que `ask_claude()` siga usando su propio historial para personalización.
2026-08-02 | orion-architect | Un único punto de resolución (`core/resolution.py:resolve()`) reemplaza los 3 motores divergentes (`main.py`, `channels/gateway.py`, `core/orchestrator.py::_try_quick_dispatch`) | CA-01/02/03. Patrón "lista de resolvers" en vez de cascada de `if`, tomado de OpenClaw §7.4.3 pero reducido a las capas que O.R.I.O.N. ya tiene (sin los 8 tiers de precedencia — sobreingeniería para un solo usuario, ver §7.5 de la referencia).
2026-08-02 | orion-architect | `task_manager` se envuelve como `ToolSpec` gateado (`agents/tool_registry.py::execute_tool()`) en vez de seguir siendo llamado directo desde `GlassGateway._try_create_task/_try_list_tasks/_try_complete_task` | Cierra el hallazgo de baseline: creación de tareas sin paso por `security_manager.require_confirmation()`. Mismo mecanismo sirve para cualquier tool futuro (REQ-007).
2026-08-02 | orion-architect | Denegación del gate pasa a ser una excepción (`ActionDenied`) en vez de un string `"⛔..."` | CA-09. Cierra H7 (`core/base_agent.py:103` interpretaba la negación como éxito por comparación de subcadena). `except ActionDenied` reemplaza `"Error" not in result[:10]`.
2026-08-02 | orion-architect | Confirmación por canal vía registro de adaptadores (`core/confirmation.py`), no vía `input()` hardcodeado | CA-10. Canal sin adaptador registrado = denegado, nunca cuelga. Modelo de dos ejes (permitido × hay que preguntar) de OpenClaw Exec Approvals (§2.5) considerado y descartado como demasiado — ver "Descartado".
2026-08-02 | orion-architect | `CHANNEL_ALLOWED_LEVELS` NO se modifica; Telegram/Discord/Voice/API siguen sin adaptador de confirmación real, por lo tanto YELLOW sigue bloqueado ahí exactamente igual que hoy | Decisión humana explícita en SPEC-006 (paridad = capacidad, no autoridad). CA-10 desacopla el mecanismo de pedir confirmación, no relaja la política de quién puede confirmar qué.
2026-08-02 | orion-architect | Corrección de precisión en la fila de riesgo sobre resolvers heredados sin gate — solicitada por orion-coordinador tras verificación propia, y re-verificada por orion-architect antes de aplicarla porque la corrección del coordinador también tenía un error | El coordinador señaló correctamente que `capability` y `autopilot` sí están gateados (`execute_capability()` y `agents/action_registry.py:execute_action()` respectivamente), pero afirmó que `routine` estaba "genuinamente sin gate". Verificado leyendo `learning/routines_engine.py` completo: `try_routine()` → `execute_routine_actions()` (línea 41) → llama a **la misma** `agents/action_registry.py:execute_action()` que usa `autopilot`, que gatea incondicionalmente en su línea 256. `routine` SÍ está gateado por construcción, igual que `autopilot`/`capability`. El único genuinamente sin gate propio es `learned` (`learning/command_learning.py:run_custom_command()`), y su gate actual es un efecto colateral de que su único caller hoy (`main.py:159`) pasa un callback que llama `dispatch()` — no una garantía del propio módulo. Documento corregido con esta precisión exacta; mitigación agregada: preservar explícitamente `callback → dispatch()` al migrar `learned` a `core/resolution.py`, con test dedicado.

## Descartado (y por qué)
2026-08-02 | orion-architect | Modelo de dos ejes completo de OpenClaw Exec Approvals (`security × ask` con `allow-always` durable) para CA-10 | Resuelve problemas que O.R.I.O.N. no tiene todavía (aprobaciones durables, múltiples modos nombrados). El registro de adaptadores por canal + fail-closed sin adaptador cubre los 24 CA con una fracción del código. Revisar si REQ-007 necesita `allow-always` cuando el loop de razonamiento haga llamadas repetidas a la misma tool.
2026-08-02 | orion-architect | Contrato de canal completo estilo `ChannelPlugin` de 31 campos | Sobreingeniería para 4 canales reales (§7.3.1 de la referencia). Este REQ no introduce `ChannelPlugin` — eso es REQ-009 del roadmap, fuera de alcance. Solo se introduce lo mínimo: el registro de adaptadores de confirmación.
2026-08-02 | orion-architect | Unificar `main.py` (desktop) y `start_bots.py` (canales) en un solo proceso/host (REQ-008 del roadmap) | Fuera de alcance de REQ-006; `resolve()` se diseña para que ambos procesos lo importen y llamen igual, sin necesitar que compartan proceso.

## Decisiones tomadas
2026-08-02 | orion-security | Auditoría de `arquitectura-006.md` completada — veredicto **APROBADO CON OBSERVACIONES** | Verificado en código real (no solo en el documento) que 6 de los 7 resolvers de `RESOLVERS` (`routine`, `autopilot`, `capability`, `intent`, `task_tool`, `claude`) están gateados por construcción o no tienen superficie de riesgo (`claude` no tiene tool-calling, confirmado por grep de `subprocess|exec|eval|tools=`); el séptimo (`learned`) tiene gate indirecto, ya documentado honestamente por `orion-architect`. `core/confirmation.py` es fail-closed sin excepciones (`adapter is None` → `return False`). El fix de CA-05 (voz real) cubre los 3 sub-caminos de captura sin abrir ruta nueva. `task_create`/`task_list`/`task_complete` en GREEN es razonable — scoping por `user_id` ya existe en `task_manager.py` y el origen de `user_id` ya es confiable en Telegram (viene de `user.id` de la API, no de texto parseado). Cero secretos hallados en `SPEC-006.md`, `arquitectura-006.md`, `REQ-006-context.md` ni `.claude/skills/skill-mcp-sigaind-v01.md`. Documento completo: `workspace/adjuntos/REQ-006/pruebas/security-audit-006.md`.
2026-08-02 | orion-security | **Observación A — adaptador `AgentTool`↔`ToolSpec` sin especificar en `core/base_agent.py`** | La arquitectura dice "AgentTool gana un adaptador opcional hacia ToolSpec (ver abajo)" pero no hay ninguna sección que lo especifique. Riesgo: si se implementa como `AgentTool(function=spec.invoke)`, cualquier `AgentTool.execute()` sobre ese wrapper invoca `spec.invoke()` directo sin pasar por `execute_tool()`/`security_manager` — el bypass exacto que el handoff pedía descartar. Hoy sin consumidor dentro de [A] (no hay bypass vivo), pero si `orion-dev` lo implementa sin spec exacta puede fijar la forma equivocada. Comunicado a `orion-architect` vía SendMessage con dos salidas propuestas: sacarlo de [A], o especificar que su `function` debe llamar `execute_tool()` con test estructural dedicado.
2026-08-02 | orion-security | **Hallazgo 1.7 — mitigación de `learned` sensata pero recomendable de fortalecer** | El test propuesto (`test_learned_callback_pasa_por_dispatch`) protege contra que cambie el callback actual, no contra un segundo caller futuro sin gate. Recomendación comunicada a `orion-architect`: que `_try_learned` en `core/resolution.py` no acepte callback externo — función privada, sin parámetro de configuración, siempre `classify_command()` → `dispatch()`. El test queda como red adicional, no como única defensa.
2026-08-02 | orion-security | **Observación B (menor, no bloqueante) — invariante de `user_id` no documentada explícitamente** | Igual que `channel` en `security_manager.py:214-221`, `user_id` debería documentarse como "siempre de la fuente confiable del canal, nunca de texto libre parseado" para cuando `task_tool` se extienda más allá de Telegram. Se cumple de hecho hoy, no se cumple como regla escrita. No bloquea la aprobación.
2026-08-02 | orion-security | Mensaje enviado a `orion-architect` (agente `afb1449fbfd8fdb41`) con las 3 observaciones de arriba | No se modificó `arquitectura-006.md` directamente — corresponde solo a `orion-architect` decidir si ajusta el documento o las deja como restricción vinculante documentada para `orion-dev`.
2026-08-02 | orion-security | **Recordatorio explícito: el bloqueo de secuencia por REQ-005 sigue vigente pese a la aprobación de esta auditoría** | `orion-dev` NO puede escribir código todavía — REQ-005 sigue en `EN_QA` sin commitear. Esta auditoría es condición necesaria pero no suficiente para avanzar a `orion-dev`; falta el cierre manual del humano sobre REQ-005. NO se modificó ningún `.py` en este paso — solo se leyó código existente para verificar las afirmaciones de la arquitectura.

## Decisiones tomadas
2026-08-02 | orion-security | **Las 3 observaciones de la auditoría quedaron RESUELTAS por `orion-architect` en la misma sesión — verificado leyendo `arquitectura-006.md` real, no solo el reporte** | (1) Observación A: adaptador `AgentTool`↔`ToolSpec` sacado explícitamente del alcance de [A] (línea 76) — `[B]`/`core/reasoning_loop.py` no reutiliza `AgentTool`, ejecuta siempre vía `execute_tool()`. (2) Hallazgo 1.7: `_try_learned` usa `execute_callback` fijo y privado de `core/resolution.py` (líneas 125-130), no parametrizable desde fuera, siempre `classify_command() → dispatch()` — gate deja de depender de la disciplina del caller. (3) Observación B: invariante de `user_id` documentada explícitamente junto a los wrappers de `task_manager` (líneas 195-203), mismo criterio que ya existía para `channel`. Ninguno de los tres ajustes agrega CA, quita cobertura ni amplía módulos a tocar — **no se requirió nueva ronda de aprobación humana**. Veredicto final de la auditoría actualizado de "APROBADO CON OBSERVACIONES" a **APROBADO** en `workspace/adjuntos/REQ-006/pruebas/security-audit-006.md`.
2026-08-02 | orion-security | Auditoría de seguridad de REQ-006 [A] cerrada — 0 condiciones abiertas sobre el diseño | Riesgos clasificados (verde/amarillo/rojo), secretos auditados (ninguno hallado), confirmaciones de acciones destructivas verificadas (fail-closed intacto en los 7 resolvers, `core/confirmation.py` sin excepciones), validación de inputs revisada (invariante de `channel` y ahora `user_id` documentadas). DoD de `orion-security` completo.

## Riesgos activos
- Ninguno nuevo abierto por `orion-security`. Las 3 observaciones de la auditoría (adaptador `AgentTool`↔`ToolSpec`, mitigación de `learned`, invariante de `user_id`) quedaron resueltas en `arquitectura-006.md` — ver Decisiones tomadas arriba.
- Se mantienen los riesgos ya aceptados y documentados por `orion-architect` sin cambios (canal `desktop` hardcodeado en `_ProactiveAssistant.execute()`, no explotable mientras `can_handle()` no auto-despache; `[B]` como diseño de referencia a re-confirmar por su propio `orion-architect`).

## Estado actual
- **Estado tracker:** EN_DESARROLLO
- **Último agente:** orion-tester
- **Fecha última actualización:** 2026-08-04

## Decisiones tomadas
2026-08-04 | orion-dev | Implementado REQ-006 [A] completo (CA-01 a CA-17) siguiendo `propuestas/arquitectura-006.md` al pie de la letra | Nuevo `core/resolution.py::resolve()` como punto único de resolución (CA-01/02/03); `ActionDenied` en `core/security_manager.py`, levantada por `dispatch()` y `execute_tool()` (CA-09); `core/confirmation.py` ya existía completo y se reutilizó sin cambios (CA-10); `main.py` calcula `channel` real por ciclo de captura y registra el único adaptador de confirmación real (DESKTOP) (CA-05); `_ProactiveAssistant.can_handle()` corregido (CA-12); `channels/gateway.py` elimina el pre-matching sin gate de tareas (CA-02, cierra H3); `channels/telegram_bot.py` elimina el pre-matching de apagado/reinicio (B6). Detalle completo, incluidas 7 decisiones de implementación con justificación, en `propuestas/desarrollo-log-006.md`.
2026-08-04 | orion-dev | Bug no anticipado por la arquitectura, encontrado y corregido: `core/resolution.py::_try_intent` asumía que `classify_command()` siempre devuelve un miembro de `Intent`, pero `intent/ai_classifier.py::predict()` devuelve un `str` plano — `intent.value` rompía con `AttributeError` en cualquier resolución real por el resolver `intent` | Corregido replicando el mismo patrón defensivo que ya usaba `router/dispatcher.py:dispatch()` (`intent.value if hasattr(intent, "value") else str(intent)`). Verificado con `tests/test_classifier.py::test_classify_then_resolve_desktop_executes_green_intent`.
2026-08-04 | orion-dev | Verificación local completa: `python -m py_compile` sin errores en los 9 archivos tocados; `pytest tests/` = 92 passed (54 pre-existentes de baseline-006.md + 38 nuevos cubriendo CA-01 a CA-17), 0 fallos, 3 warnings pre-existentes sin relación con este REQ | Cero regresiones sobre la línea base documentada en `origen/baseline-006.md`.
2026-08-04 | orion-dev | NO se ejecutó `git commit`. Mensaje de commit sugerido entregado al humano/orquestador, no ejecutado | Regla de `.claude/rules/git.md` — el commit real llega después de `orion-tester` + `orion-qa` + validación manual del humano.

## Log de transiciones
2026-08-04 | ARQUITECTURA_APROBADA → EN_PRUEBAS | orion-dev | REQ-006 [A] (CA-01 a CA-17) implementado completo. 5 archivos nuevos de código/test de infraestructura (`core/resolution.py`, `tests/conftest.py`) + 6 archivos nuevos de test (`test_resolution.py`, `test_tool_registry.py`, `test_confirmation.py`, `test_base_agent.py`, `test_main.py`, `test_main_channel.py`) + 9 archivos modificados. `pytest tests/` en verde (92/92). Handoff emitido a `orion-tester`.

## Decisiones tomadas
2026-08-04 | orion-tester | Verificación independiente de compilación y suite completa — ambas reclamaciones de `orion-dev` confirmadas exactas | `python -m py_compile` sobre los 9 módulos → 0 errores. `pytest tests/ --tb=short -v` → 92 passed, 0 failed, 3 warnings (recuento manual línea por línea del output verboso, no solo confianza en el resumen de `orion-dev`: `test_agents.py`=5, `test_base_agent.py`=4, `test_classifier.py`=8, `test_confirmation.py`=4, `test_dispatcher.py`=5, `test_main.py`=3, `test_main_channel.py`=1, `test_resolution.py`=6, `test_security_manager.py`=49, `test_tool_registry.py`=7; suma=92). `grep -rn "async def" core/ router/ intent/ skills/` → 0 resultados, igual que baseline (CA-11). Cero regresiones sobre los 54 tests preexistentes de `origen/baseline-006.md`.
2026-08-04 | orion-tester | 16 de 17 criterios (CA-01, CA-02, CA-04 a CA-17) verificados PASS contra la tabla "Pruebas sugeridas" de `arquitectura-006.md`, confirmando en cada caso que el test existente realmente ejerce el criterio (no solo que el nombre suene relacionado) — incluye lectura completa de código fuente real para CA-01, CA-02, CA-05, CA-09, CA-10, CA-12 (no solo del test) | Hallazgo destacado en CA-09: el chequeo por substring `"Error" not in result[:10]` en `core/base_agent.py` fue eliminado por completo (no parcheado), lo que satisface por construcción el caso borde de un texto de éxito que contuviera la palabra "Error". Detalle test por test en `pruebas/test-results-006.md`.
2026-08-04 | orion-tester | **CA-03 (traza idéntica por canal) — FAIL parcial: cobertura de test incompleta frente al texto explícito de SPEC-006.md** | SPEC-006 exige traza idéntica en desktop/telegram/voice para 4 categorías (verde, amarilla, desconocida, multi-paso). El test implementado (`tests/test_resolution.py::test_traza_identica_por_canal`) solo cubre la categoría verde en los 3 canales. La categoría amarilla (`test_yellow_mismo_action_name_desktop_vs_voice`) solo compara DESKTOP vs VOICE, nunca TELEGRAM. Las categorías desconocida y multi-paso no tienen ningún test que compare la traza de `resolve()` entre canales — confirmado con `grep -rln "resolve(" tests/`: solo `test_classifier.py`, `test_main_channel.py` y `test_resolution.py` invocan `resolve()`, ninguno cubre esas dos categorías cruzando canales. Por inspección de código, `resolve()` camina la misma lista `RESOLVERS` en el mismo orden sin importar `channel`, por lo que es razonable esperar comportamiento correcto — pero la SPEC pide una prueba ejecutable que lo confirme para las 4 categorías, y no existe para 3 de las 4. Nota aparte: la tabla "Pruebas sugeridas" de `arquitectura-006.md` describe el test de CA-03 de forma más estrecha que el texto de la SPEC aprobada — discrepancia entre ambos documentos que conviene resolver al cerrar este punto. Detalle completo en `pruebas/test-results-006.md`.
2026-08-04 | orion-tester | Veredicto: **FAIL** — único bloqueante CA-03. Devuelto a `orion-dev` con el detalle específico de qué casos de prueba faltan (no se tocó ningún archivo de código ni de test). | `pruebas/test-results-006.md` generado con PASS/FAIL explícito por CA-01 a CA-17, sección de compilación, tests existentes y regresión.

## Log de transiciones
2026-08-04 | EN_PRUEBAS → EN_DESARROLLO | orion-tester | CA-03 con cobertura de test incompleta (falta amarilla-vía-TELEGRAM, desconocida y multi-paso en la comparación de traza entre canales). Los 16 criterios restantes PASS, 0 regresiones sobre los 54 tests preexistentes, compilación limpia en los 9 módulos. Handoff devuelto a `orion-dev` con el detalle específico. Ver `pruebas/test-results-006.md`.

## Estado actual
- **Estado tracker:** EN_PRUEBAS
- **Último agente:** orion-dev
- **Fecha última actualización:** 2026-08-04

## Decisiones tomadas
2026-08-04 | orion-dev | Corregida la cobertura de test de CA-03 (traza idéntica por canal) señalada por `orion-tester` en `pruebas/test-results-006.md` — alcance estrictamente limitado a `tests/test_resolution.py`, sin tocar `core/resolution.py` ni ningún otro archivo de producción, tal como pidió explícitamente el humano/orquestador ("No se requiere cambio de comportamiento en core/resolution.py") | Se agregaron 3 tests nuevos, uno por categoría faltante, dejando intactos `test_traza_identica_por_canal` (verde, ya PASS) y `test_yellow_mismo_action_name_desktop_vs_voice` (CA-04, DESKTOP/VOICE únicamente por texto propio de ese criterio — no se tocó para no conflar CA-03 con CA-04): (1) `test_traza_identica_por_canal_categoria_amarilla` — mismo texto "cierra chrome" resuelto en DESKTOP/TELEGRAM/VOICE, confirma `matched_by="intent:CLOSE_APP"` idéntico y `denied=True` en los 3, con `input()` mockeado y conteo de llamadas por canal (1 en DESKTOP, 0 en TELEGRAM y VOICE) para probar que solo cambia el veredicto del gate, no la traza; (2) `test_traza_identica_por_canal_categoria_desconocida` — `ai_system.predict` mockeado a `"UNKNOWN"` (mismo patrón que `test_classifier.py`) y `resolve(..., claude_fn=...)` para evitar red real, confirma `matched_by="claude"` idéntico en los 3 canales sin denegar nada; (3) `test_traza_identica_por_canal_categoria_multi_paso` — texto "haz un modo trabajo" con `ACTION_REGISTRY["open_chrome"]["fn"]`/`["open_notepad"]["fn"]` monkeypatcheados (sin lanzar procesos reales) y `time.sleep` parcheado a no-op, confirma `matched_by="routine"` idéntico (la rutina intercepta antes que `autopilot`, ver `RESOLVERS`) y la misma secuencia exacta de acciones/parámetros `[("open_chrome", {}), ("open_notepad", {})]` en los 3 canales.
2026-08-04 | orion-dev | Ajuste menor durante la escritura del test de multi-paso: la primera versión comparaba las secuencias de llamadas metiéndolas en un `set`, y falló con `TypeError: unhashable type: 'dict'` porque cada llamada es una tupla `(nombre, params_dict)` y los `dict` no son hasheables | Corregido comparando cada secuencia por canal contra una tupla esperada con `==` en vez de igualdad de conjuntos — mismo nivel de rigor (falla si difiere el orden, la acción o los parámetros en cualquier canal), sin cambiar la intención del test.
2026-08-04 | orion-dev | Verificación local: `python -m pytest tests/ --tb=short -q` → **95 passed, 0 failed, 3 warnings** (92 preexistentes de la implementación completa de REQ-006 [A] + 3 nuevos de este fix). Warnings idénticos a los ya documentados por `orion-tester` (2 `DeprecationWarning` de `speech_recognition`, 1 `PytestReturnNotNoneWarning` preexistente en `test_agents.py`), ninguno nuevo | Cero regresiones. No fue necesario `python -m py_compile` porque no se tocó ningún `.py` de producción, solo `tests/test_resolution.py`.
2026-08-04 | orion-dev | NO se ejecutó `git commit`. Mensaje de commit sugerido re-entregado (sin cambios de fondo respecto al de la implementación original, solo se documenta que ahora incluye la cobertura completa de CA-03) | Regla de `.claude/rules/git.md` — el commit real llega después de `orion-tester` (re-verificación) + `orion-qa` + validación manual del humano.

## Log de transiciones
2026-08-04 | EN_DESARROLLO → EN_PRUEBAS | orion-dev | Fix de cobertura de CA-03 completo: 3 tests nuevos en `tests/test_resolution.py` (amarilla vía 3 canales, desconocida vía 3 canales, multi-paso vía 3 canales), ningún archivo de producción tocado. `pytest tests/` en verde (95/95, 92 preexistentes + 3 nuevos), 0 regresiones. Handoff emitido a `orion-tester` para re-verificación.

## Estado actual
- **Estado tracker:** EN_QA
- **Último agente:** orion-tester
- **Fecha última actualización:** 2026-08-04

## Decisiones tomadas
2026-08-04 | orion-tester | Re-verificación independiente (ronda 2) del fix de CA-03 — no se confió en el reporte de `orion-dev`, se corrió la suite propia y se leyó el contenido real de los 3 tests nuevos | `pytest tests/ --tb=short -v` → **95 passed, 0 failed, 3 warnings**, recontado manualmente línea por línea (coincide exacto con lo reportado). Lectura completa de `tests/test_resolution.py` (líneas 68-165): los 3 tests nuevos (`_categoria_amarilla`, `_categoria_desconocida`, `_categoria_multi_paso`) genuinamente comparan `matched_by` — y en el caso multi-paso la secuencia exacta de llamadas con sus parámetros — entre `ChannelType.DESKTOP`/`TELEGRAM`/`VOICE`, tal como exige el texto literal de `SPEC-006.md` para CA-03 (no solo nombres de test relacionados). `find . -newer <test-results-006.md de ronda 1>` confirma que el único archivo de código/test modificado fue `tests/test_resolution.py` — ningún archivo de producción tocado, tal como reportó `orion-dev`.
2026-08-04 | orion-tester | Veredicto final: **PASS, 17/17** | Los 17 criterios (CA-01 a CA-17) verificados con test genuino que ejerce cada uno. Cero regresiones sobre los 54 tests preexistentes de `origen/baseline-006.md` ni entre la ronda 1 (92 tests) y la ronda 2 (95 tests) de este REQ. Compilación limpia en los 9 módulos (sin cambios desde la ronda 1, ningún `.py` de producción tocado en el fix). `pruebas/test-results-006.md` actualizado con la sección "Re-verificación CA-03" y el veredicto final. Handoff emitido a `orion-qa`.

## Log de transiciones
2026-08-04 | EN_PRUEBAS → EN_QA | orion-tester | REQ-006 [A] (CA-01 a CA-17) verificado PASS 17/17 tras el fix de cobertura de CA-03. 95/95 tests en verde, 0 regresiones, compilación limpia en los 9 módulos. Handoff emitido a `orion-qa` con `pruebas/test-results-006.md`.

## Estado actual
- **Estado tracker:** EN_QA (sin cambio — es el estado que representa "QA aprobó, esperando prueba manual del humano")
- **Último agente:** orion-qa
- **Fecha última actualización:** 2026-08-04

## Decisiones tomadas
2026-08-04 | orion-qa | Auditoría de seguridad/calidad completa sobre los 10 archivos señalados (`core/resolution.py`, `core/security_manager.py`, `core/base_agent.py`, `core/orchestrator.py`, `router/dispatcher.py`, `main.py`, `channels/gateway.py`, `channels/telegram_bot.py`, `agents/tool_registry.py`, `core/confirmation.py`) — lectura completa de código fuente más `git diff` dirigido por archivo para separar líneas nuevas/modificadas de REQ-006 de líneas preexistentes (relevante porque REQ-005 sigue sin commitear, así que el diff de working tree mezcla ambos REQ) | Sin secretos hardcodeados (grep dirigido, 0 coincidencias). `ActionDenied` no filtra stacktrace ni rutas — mensaje construido solo con `action_name`/`channel.value`/`reason` corto, y `_denied_message()` en `resolution.py` solo expone el nombre de la acción al usuario final. `CHANNEL_ALLOWED_LEVELS` intacto para los 4 canales existentes (confirmado por diff), solo se agregaron `API`/`UNKNOWN` como `[GREEN]` aditivo. Deny-list RED de REQ-005 (10 categorías) intacta.
2026-08-04 | orion-qa | Verificación de niveles de riesgo | `task_create`/`task_list`/`task_complete` registrados GREEN en `agents/tool_registry.py`, ahora gateados vía `execute_tool()` (cierra H3 — antes `channels/gateway.py::_try_create_task/_try_list_tasks/_try_complete_task` llamaban a `task_manager` sin gate; esos 3 métodos fueron eliminados, confirmado por diff). Ningún canal remoto ganó capacidad YELLOW/RED — solo DESKTOP tiene adaptador de confirmación real registrado (`main.py::_desktop_confirm`), los demás caen en `"bloqueada_sin_adaptador"` fail-closed. Hallazgo menor no bloqueante: `desarrollo-log-006.md` dice que `_handle_shutdown`/`_handle_restart` de `telegram_bot.py` quedaron "sin cambios", pero el diff muestra que pasaron de `is_action_allowed()` a `require_confirmation()` (mismo resultado denegado en Telegram, pero ahora con auditoría en `audit.db` — mejora real, no regresión). Recomendado corregir la nota del log, no amerita volver a `orion-dev`.
2026-08-04 | orion-qa | Verificación de logging | Los dos `except Exception: pass` de `channels/gateway.py` señalados en el encargo (envoltorio de `_save_semantic()` en `process()`, y el `except: pass` interno de `_save_semantic()`) están corregidos a `logger.warning(...)` sin loguear `text`/`result` del usuario, confirmado por diff. Ningún `except: pass` nuevo introducido por REQ-006 en los 10 archivos. Los `except: pass` preexistentes de `channels/telegram_bot.py` (limpieza de temporales, best-effort de UI) no fueron tocados por este REQ y son de bajo riesgo — se dejan como nota de deuda técnica, no bloquean.
2026-08-04 | orion-qa | Verificación de consistencia de código y arquitectura | Type hints presentes en los 3 módulos nuevos. Sin `print()` de debug nuevo (el único `print(msg)` remanente en la rama RED de `security_manager.py` está fuera del rango tocado por el diff de REQ-006, confirmado). Algunas líneas superan 100 caracteres (comentarios decorativos y un par de `logger.info` de una línea) — cosmético, no bloqueante. Sin scope creep: no existe `core/reasoning_loop.py` ni ningún archivo de la sección `[B]` (CA-18 a CA-24). El fix de `_try_intent` (`intent.value` sobre `str` plano) replica exactamente el patrón defensivo preexistente de `router/dispatcher.py:50`, consistente, sin riesgo nuevo.
2026-08-04 | orion-qa | Observación no bloqueante documentada para REQ-007 | `AgentTool.execute()` en `core/base_agent.py` sigue envolviendo `self.function(params)` en un `except Exception` genérico que convierte `ActionDenied` en string en vez de propagarla — el fix de CA-09 en `_DynamicAgentInstance.execute()` (`except ActionDenied: continue`) por lo tanto no se dispara para instancias reales de `AgentTool`, solo para dobles de test. Investigado y confirmado que **no es una brecha viva**: `core/orchestrator.py::process_task()` delega 100% a `resolve()`, y `_process_with_agents`/`_execute_single_agent`/`_execute_agent_chain`/`_DynamicAgentInstance` no tienen invocador vivo en REQ-006 (solo compatibilidad estructural con `tests/test_agents.py`). Recomendado que el baseline de REQ-007 registre este punto explícitamente si esa iniciativa reactiva el camino de agente con herramientas.
2026-08-04 | orion-qa | Veredicto: **✅ COMPLETADO** — ver `pruebas/qa-audit-006.md` para el detalle completo | Ningún hallazgo es bloqueante. Falta la prueba manual del humano antes de `LISTO_PARA_COMMIT`. NO se ejecutó ni se generó ningún `git commit`.

## Log de transiciones
2026-08-04 | EN_QA → EN_QA (sin cambio de estado tracker) | orion-qa | Auditoría QA completa, veredicto ✅ COMPLETADO (`pruebas/qa-audit-006.md`). El estado tracker permanece `EN_QA` porque en la lista de Estados de O.R.I.O.N. no existe un estado intermedio "QA aprobado, esperando humano" — `EN_QA` ya representa correctamente esa espera; el siguiente cambio de estado (`LISTO_PARA_COMMIT`) solo ocurre tras el OK explícito del humano en la prueba manual. Solicitud de prueba manual emitida al humano.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Último agente:** orion-qa
- **Fecha última actualización:** 2026-08-04

## Decisiones tomadas
2026-08-04 | orion-qa | Prueba manual del humano confirmada OK, transmitida por el coordinador: "el humano ya hizo la prueba manual final de REQ-006 y confirmó que todo funciona correctamente (escritorio, Telegram, y paridad de reconocimiento entre canales para CA-03)" — cubre los 3 pasos solicitados en la nota de QA (acción GREEN/YELLOW en escritorio con confirmación real, creación/listado de tareas y bloqueo de apagado por Telegram, y paridad de reconocimiento CA-03 entre canales) | Cierre del gate `Humano (prueba manual)` del pipeline. Con esto quedan satisfechos los 3 requisitos del checklist de `.claude/rules/git.md` antes de entregar el mensaje de commit: QA aprobó (`pruebas/qa-audit-006.md` ✅ COMPLETADO), el humano hizo la prueba manual y dio OK, y no hay `requirements.txt` que actualizar (REQ-006 no agregó dependencias nuevas, confirmado en `propuestas/desarrollo-log-006.md`).
2026-08-04 | orion-qa | REQ-006 [A] (CA-01 a CA-17) cerrado — mensaje de commit sugerido entregado al humano para ejecución manual | NO se ejecutó `git commit` en ningún momento del pipeline, por regla `.claude/rules/git.md`. El commit real queda a cargo exclusivo del humano.

## Log de transiciones
2026-08-04 | EN_QA → LISTO_PARA_COMMIT | orion-qa | Prueba manual del humano confirmada OK (transmitida por el coordinador). REQ-006 [A] cierra el pipeline `orion-tester → orion-qa → Humano → mensaje de commit`. Mensaje de commit sugerido entregado, ningún `git commit` ejecutado por ningún agente.
