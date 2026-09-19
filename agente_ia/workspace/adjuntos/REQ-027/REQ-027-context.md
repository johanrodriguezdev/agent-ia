# Contexto REQ-027 — Bucle de razonamiento de nivel agente

## Resumen ejecutivo
Elevar `core/reasoning_loop.py` de "encadenador de herramientas con techo bajo" a un bucle
de agente real. Tres cambios que atacan la MISMA causa raíz detrás de tres carencias
distintas (razonamiento complejo, investigación multi-fuente, autonomía multi-paso):

1. **Protocolo nativo `tool_use`/`tool_result`** en los 4 proveedores con tool-calling.
2. **Presupuesto de llamadas variable** según el modo estratégico activo (REQ-026), en
   lugar del `MAX_LLM_CALLS = 5` fijo.
3. **Ejecutar TODAS las tool calls** que el modelo pida en una vuelta (hoy se ejecuta la
   primera y el resto se descarta).

Más un ajuste transversal: subir el `max_tokens=1500` de los adaptadores de proveedor.

## Estado actual
- **Estado tracker (CSV):** EN_QA — implementado y con la suite en verde; falta la prueba manual de Johan
- **Último agente:** conversación principal (implementación) → siguiente: prueba manual de Johan
- **Fecha última actualización:** 2026-09-08
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`, creada desde `feature/mcp-correo-flujos` (= `main` + REQ-026). SIN COMMITEAR.
- **Categoría:** CORE
- **Tipo de cambio:** MEJORA

## Origen del REQ
Johan preguntó si el agente ya podía hacer 7 cosas de nivel agente: (1) razonamiento
complejo, (2) programar y trabajar con repos completos, (3) investigar y sintetizar,
(4) usar computadoras y software, (5) usar herramientas y APIs, (6) tareas multi-paso
autónomas, (7) dominios diversos.

Auditoría del código (2026-09-08, conversación principal). Veredicto:

| # | Capacidad | Estado hoy |
|---|---|---|
| 1 | Razonamiento complejo | A medias — hay bucle, techo de 5 llamadas |
| 2 | Programar / repos completos | **No existe** — sin leer/editar/buscar archivos ni git |
| 3 | Investigar y sintetizar | Busca, pero no investiga |
| 4 | Usar computadoras y software | **Sí** — lo más sólido del sistema |
| 5 | Herramientas y APIs | Construido (MCP) pero apagado; sin HTTP genérico |
| 6 | Multi-paso autónomo | A medias — mismo techo del punto 1 |
| 7 | Dominios diversos | Ancho pero poco profundo |

Datos medidos: 55 tools registradas en runtime, 44 visibles para el modelo en canal
desktop (`catalogo_para_modelo(None)`).

**Los puntos 1, 3 y 6 fallan por la misma causa** — de ahí este REQ. El punto 2 se
trabajará como REQ aparte, después de este (decisión de Johan: primero el bucle, porque
editar un repo son ~20 pasos y hoy no entran en 4).

## Hallazgos técnicos de la auditoría (evidencia para spec y arquitectura)

### Lo que YA está hecho (no rehacer)
- Los 4 proveedores de `_PROVEEDORES_CON_TOOLS` (`anthropic`, `deepseek`, `openai`,
  `openrouter`, `ai/llm_provider.py:209`) ya **parsean** la respuesta con tool calls y
  devuelven `LLMToolResponse` con una lista de `ToolCallRequest` **que ya incluye el `id`**
  (`ai/llm_provider.py:610-612` para Anthropic, `:765-771` para OpenAI, `:843-849` para
  OpenRouter). El camino de IDA está resuelto.
- `anthropic` ya acumula VARIOS bloques `tool_use` en la misma respuesta (loop en
  `_ask_anthropic`), así que el dato para el cambio 3 ya llega — hoy se descarta en
  `core/reasoning_loop.py:317` (`call = response.tool_calls[0]`).
- `core/composer_modes.py` (REQ-026, recién commiteado en `d75008a`) ya da el catálogo de
  modos con `id`/`tool_names`/`tarea` — es donde colgar el presupuesto por modo.
- `core/cancelacion.py::abortar_si_cancelado()` ya corta el bucle en cada vuelta; el botón
  de detener sigue siendo la red de seguridad contra un turno largo.

### Lo que bloquea hoy (el trabajo real)
- `_ask_anthropic` (`ai/llm_provider.py:568-570`) envuelve **todo** mensaje como
  `{"role": m["role"], "content": [{"type": "text", "text": m["content"]}]}`. Con esa
  línea es imposible mandar bloques `tool_use`/`tool_result` estructurados.
- `_ask_openai` (`ai/llm_provider.py:711-713`) pasa `m["content"]` crudo y no contempla
  mensajes con `role="tool"` ni un `assistant` con `tool_calls`.
- **`openai`, `deepseek` y `openrouter` comparten el SDK de OpenAI** → son **2 adaptadores
  reales**, no 4. Esto es lo que hace viable el cambio que REQ-007 había descartado.
- `core/reasoning_loop.py::_build_prompt()` (`:192`) re-serializa el historial de tools
  como texto plano en un único mensaje `user` autocontenido. Decisión explícita de
  `arquitectura-007.md` ("Riesgos y mitigación") tomada por falta de cobertura de test
  previa — es exactamente lo que este REQ viene a revertir.
- `MAX_LLM_CALLS = 5` (`core/reasoning_loop.py:31`) cuenta **la respuesta final incluida**
  → máximo 4 herramientas por turno.
- `max_tokens=1500` fijo en los adaptadores de proveedor.

## Decisiones tomadas
2026-09-08 | conversación principal (Johan) | Orden de trabajo: bucle PRIMERO, repos después | Los puntos 1, 3 y 6 de las 7 capacidades comparten causa raíz (el bucle). El punto 2 (repos) es una capacidad nueva e independiente, pero sin bucle largo se queda sin aire al cuarto paso. Arreglar el bucle destraba tres de siete de una sola vez.
2026-09-08 | conversación principal (Johan) | Proceso acortado: spec + arquitectura con agentes, después dev directo | Johan usa `orion-spec` y `orion-architect` (donde el pipeline da más valor), aprueba, y la implementación la hace la conversación principal sin las etapas de baseline/dev/tester/qa como subagentes. Motivo: el pipeline de 8 agentes es lento y costoso, y la dirección de diseño ya quedó validada en la auditoría.
2026-09-08 | conversación principal (Johan) | **Protocolo nativo: SÍ, en los 4 proveedores** | Opción recomendada y elegida. Son 2 adaptadores reales (Anthropic + familia SDK openai). Descartadas: "solo Anthropic" (dejaría dos comportamientos de razonamiento distintos según el proveedor, y Johan usa modelos gratuitos por tarea vía `task_providers`) y "seguir con texto" (no arregla el problema de fondo).
2026-09-08 | conversación principal (Johan) | **Presupuesto: variable según el modo activo** | Orden de magnitud propuesto en la conversación: chat normal ~8, Investigación ~25, Código ~40 — los números exactos los fija la SPEC. Reusa `core/composer_modes.py` de REQ-026. Descartadas: número alto y fijo para todo (un "hola" habilitado a gastar 25 llamadas) y corte por costo/tiempo real (más piezas nuevas de las necesarias; el botón de detener ya cubre la fuga).
2026-09-08 | conversación principal (Johan) | **Ejecutar todas las tool calls de la vuelta, en secuencia** | Cada una sigue pasando por `execute_tool()` individualmente, con su propio nivel de riesgo y su propia confirmación — el modelo de seguridad de REQ-005 NO se toca. Si una es denegada, se corta la secuencia ahí y se le informa al modelo. Descartado el tope por vuelta y el statu quo de una-por-vuelta.
2026-09-08 | conversación principal (Johan) | `max_tokens=1500` se sube en este REQ | Ajuste transversal a los adaptadores de proveedor. Con 1500 tokens, razonar sobre código se corta a la mitad. El valor exacto lo fija la SPEC.
2026-09-08 | orion-spec | Presupuestos fijados: sin modo 8, Tareas 10, Nodos/flujos 12, Investigación 25, Código/script 40 | Sin modo 8 porque la cadena típica "buscá → leé → resumí → respondé" ya son 4 herramientas y hoy no queda margen para un solo callejón sin salida. Investigación 25 porque leer 6-10 fuentes más reformular la búsqueda llega a ~20, y por encima de ~30 la ventana de contexto se llena antes que el presupuesto. Código 40 porque un ciclo escribir→ejecutar→leer error→corregir son 3+ herramientas y 40 son ~13 iteraciones; es además el presupuesto que va a heredar el REQ posterior de repositorios. Flujos 12 y Tareas 10 son subidas modestas sobre el default: activar el modo señala más de una operación seguida, pero ninguno es una búsqueda abierta.
2026-09-08 | orion-spec | Techo de 5 llamadas en todo canal que no sea DESKTOP; `claude_brain.MAX_TOOL_ROUNDS` 3 → 5 | 5 es el valor de hoy: cero regresión donde no hay forma de cortar un turno largo (el botón de detener es de escritorio) y donde `CHANNEL_ALLOWED_LEVELS` solo deja verdes. Es además fail-closed: un canal en el que nadie pensó (`API`, `EMAIL`, `UNKNOWN`) hereda el comportamiento actual y nunca el 40. Telegram/Discord tienen bucle y constante propios y suben 3 → 5 por el mismo criterio.
2026-09-08 | orion-spec | El presupuesto cuenta llamadas al modelo, no herramientas: una vuelta con N tools consume 1 | Es lo que ya significa la constante; el costo y la latencia los pone la llamada al modelo, no la tool local; y contar herramientas castigaría exactamente la conducta que premia el cambio 3 — un modelo que pide 4 lecturas juntas gastaría lo mismo que uno que las pide de a una, pero con 4 vueltas de latencia. Incentivo al revés.
2026-09-08 | orion-spec | Sin cambio de firma de `run()`: el presupuesto se deriva de `modo` y `channel`, que ya son parámetros | Elimina de raíz el riesgo de `tests/modelo_falso.py` (función plana, no MagicMock: un kwarg nuevo explota con TypeError en 58 tests ajenos, como pasó en REQ-026) en vez de mitigarlo con el patrón condicional de `core/resolution.py:696`. Fijado como CA-17, verificable con `inspect.signature`.
2026-09-08 | orion-spec | Historial de herramientas en formato NEUTRAL en `reasoning_loop`; la traducción a nativo vive solo en los adaptadores | `generate_response()` puede cambiar de proveedor a mitad de turno (cooldown + cadena de respaldo, REQ-022). Si el bucle emitiera forma nativa de un proveedor, el respaldo recibiría un historial que no entiende. También es lo que permite que `gemini`/`ollama` reciban el mismo historial aplanado a texto sin romperse.
2026-09-08 | orion-spec | El formato nuevo de mensajes es ADITIVO: `[{"role": str, "content": str}]` sigue produciendo la misma llamada byte a byte | Es lo único que protege a `ai/claude_brain.py`, `core/compaction.py` y todo caller interno de `generate_response()` de quedar rotos por este REQ.
2026-09-08 | orion-spec | `max_tokens`: constante única de 4096, no valor por tarea | Es un techo, no un objetivo: subirlo no encarece una respuesta corta. 8192 lo descarté porque varios modelos gratuitos de OpenRouter tienen tope de salida menor y rechazan la petición con error duro — sería una regresión justo en los modelos que Johan usa por ser gratis. Una tabla por tarea sería una segunda estructura de ruteo al lado de `task_providers` para un parámetro que solo muerde en una dirección.
2026-09-08 | orion-spec | `abortar_si_cancelado()` pasa a evaluarse también ENTRE herramientas de la misma vuelta | Con el cambio 3 una sola vuelta puede ejecutar N herramientas y volverse larga; el botón de detener no puede quedar esperando a que termine la vuelta entera.
2026-09-08 | orion-spec | Agregado un cambio 4 no pedido: llamada de cierre sin herramientas al agotar el presupuesto | Consecuencia directa del cambio 2: agotar 40 vueltas y devolver el enlatado "No pude completar la tarea" tira a la basura 39 vueltas de trabajo pagado. Es el mismo mecanismo que ya usa `ai/claude_brain.py:207-212`, no una pieza nueva. Queda marcado en `## PENDIENTE DE JOHAN` (P-2) porque no estaba en el encargo.
2026-09-08 | orion-spec | La denegación pasa a informar al modelo con `tools=None` — refina REQ-007/CA-08 | La decisión de Johan dice "se corta la secuencia y se le informa al modelo", pero no decía si esa llamada lleva herramientas. Con `tools=None` la garantía de "no reintenta, no prueba otra tool" queda por construcción y no apoyada en una frase del prompt. Consecuencia explícita: `test_ca08_action_denied_corta_de_inmediato` pasa de `call_count == 1` a `== 2`. Es el ÚNICO test de un camino de seguridad que este REQ modifica, y por eso queda escrito en la SPEC (§Impacto en tests existentes) y en `## PENDIENTE DE JOHAN` (P-1).
2026-09-08 | orion-spec | Fuera de alcance explícito: herramientas de repositorio/código, MCP, HTTP genérico, migrar `claude_brain` a nativo, ejecución en paralelo, corte por costo/tiempo | Los tres primeros son la capacidad 2 y 5 de la auditoría y van en REQs posteriores. El paralelo se descarta porque una confirmación humana concurrente con otra ejecución es justo lo que el gate no debe permitir. El corte por costo/tiempo ya lo había descartado Johan.

2026-09-08 | conversacion principal (Johan) | **P-1 y P-2 APROBADOS: llamada de cierre sin herramientas en AMBOS casos** | Tanto tras una denegacion como al agotar el presupuesto, el bucle hace una llamada final con `tools=None` para redactar la respuesta con lo que ya averiguo. Motivo aceptado: la garantia de "no reintenta la accion denegada" queda estructural y no apoyada en el prompt, y un turno de investigacion que agota 25 vueltas devuelve lo leido en vez del texto enlatado. Se acepta explicitamente la consecuencia: `test_ca08_action_denied_corta_de_inmediato` pasa de `call_count == 1` a `== 2`. CA-28 a CA-32 quedan EN alcance.
2026-09-08 | conversacion principal (Johan) | **P-3: `ai/claude_brain.py` NO migra a nativo en este REQ** | Telegram/Discord reciben solo `MAX_TOOL_ROUNDS` 3 -> 5 (CA-16). Migrar su bucle duplicaria el REQ sin destrabar ninguna de las 3 capacidades que lo motivan, todas de escritorio. Queda registrado como REQ-028 candidato, con la deuda reconocida: Telegram sigue razonando peor que el escritorio.
2026-09-08 | conversacion principal (Johan) | **P-4: tope de tokens para voz queda fuera de alcance** | Es una condicion preexistente (una respuesta larga por TTS ya hoy son minutos incortables), no algo que introduzca REQ-027. Candidato a REQ chico posterior: techo de salida por canal, ~500 tokens en `VOICE`.
2026-09-08 | conversacion principal (Johan) | **SPEC-027 APROBADA sin ajustes** | Johan aprobo `spec/SPEC-027.md` tal como quedo redactada, con las respuestas a P-1/P-2/P-3/P-4 arriba. Tracker a SPEC_APROBADO. Pasa a `orion-architect`.
2026-09-08 | conversacion principal | **P-5 (rama): la opcion elegida por Johan resulto inviable tal cual — verificado en git** | Johan eligio "rama nueva desde `main`", pero `main` esta en `b6b3cd6` y NO contiene REQ-026: `git cat-file -e main:core/composer_modes.py` falla. Ese archivo es donde CA-12 cuelga los presupuestos por modo, asi que una rama desde `main` nace sin la dependencia. Dato relevante: `feature/mcp-correo-flujos` esta exactamente 1 commit adelante de `main`, y ese commit es `d75008a` (REQ-026) — o sea que hoy equivale a `main + REQ-026` pese al nombre. Decision final pendiente de Johan en la conversacion principal.
2026-09-08 | orion-architect | Baseline corto levantado por el arquitecto (el pipeline se acorto, no se omitio): working tree LIMPIO en todo lo que el REQ toca y `pytest tests/` = **1828 passed, 0 failed, 11 warnings** en 214s | Sin este numero la implementacion no puede distinguir un fallo nuevo de uno preexistente (CA-44). Verificado sobre el working tree y no sobre el ultimo commit, que es donde REQ-026 se quemo. Detalle en `origen/baseline-027.md`.
2026-09-08 | orion-architect | **D-1: la representacion neutral vive en `core/tool_history.py`, un modulo hoja nuevo, y viaja dentro de la lista `messages`** | Confirma el ASUMIDO 1 de la SPEC: la firma de `generate_response()` no cambia. Modulo aparte y no dentro de `reasoning_loop.py` porque el formato lo escribe `core/reasoning_loop.py` y lo lee `ai/llm_provider.py`, y `reasoning_loop` ya importa `llm_provider` a nivel de modulo — la dependencia inversa seria un ciclo de importacion. Descartado: un parametro nuevo en `generate_response()` (tocaria a todos los callers y a `_cached_call`).
2026-09-08 | orion-architect | **D-2: las claves neutrales son palabras en espanol** (`tipo`, `llamada`, `nombre`, `argumentos`, `resultado`, `salida`) | Hace que CA-02 sea verificable con un grep trivial sobre `json.dumps(messages)`: ninguna cadena prohibida puede aparecer por accidente. Con claves en ingles el test seria una lista de excepciones. Aviso registrado: el grep de CA-02 NO puede ir sobre el archivo fuente, porque `response.tool_calls` es un atributo que `reasoning_loop.py` tiene que seguir leyendo.
2026-09-08 | orion-architect | **D-3: regla unica de aplanado — si la llamada no lleva `tools`, el historial se aplana a texto**, aplicada en `ai/llm_provider.py::_uncached_call()` | Confirma y ubica el ASUMIDO 2. Una sola linea cubre `gemini`/`ollama` (CA-07), la llamada de cierre de CA-28/29 y cualquier caller interno futuro. Motivo duro: la API de Anthropic **rechaza** una peticion con bloques `tool_use`/`tool_result` si esa peticion no declara `tools`. Sin esta regla, CA-28 y CA-29 pasarian los tests con mocks y fallarian SIEMPRE en la app real, cayendo en silencio al texto enlatado de CA-31.
2026-09-08 | orion-architect | **D-6: cada `tool_use` viaja SIEMPRE con su `tool_result`, aunque la secuencia se haya cortado** | Es el punto mas importante del diseno y la SPEC no lo menciona. Anthropic y el SDK `openai` devuelven 400 si una tool call se queda sin resultado — que es exactamente lo que produce CA-25 (denegacion corta la secuencia) seguida de CA-29 (cierre con el historial). `_ejecutar_vuelta()` garantiza `len(llamadas) == len(resultados)` con un resultado sintetico para las no ejecutadas. No es cortesia con el modelo: es requisito del protocolo.
2026-09-08 | orion-architect | **D-8: `_build_prompt()` se parte en `_encabezado_de_tarea(task, prior_turns, con_historial)` + `lineas_de_historial()`, y sobrevive como envoltorio** | El flag `con_historial` es lo que hace que el aplanado de CA-07 salga byte a byte igual al de hoy sin una sola operacion de string surgery (hoy `_build_prompt` escribe "Mensaje actual del usuario:" sin historial y "Tarea original del usuario:" con historial). El envoltorio se conserva porque CA-10 exige que los `test_ca22_*` sigan pasando sin cambio de expectativa; queda sin llamadores de produccion y su limpieza es candidata a un REQ posterior.
2026-09-08 | orion-architect | **D-5: el `id` sintetico de CA-05 se normaliza en el bucle (`tc_{vuelta}_{i}`), no en el adaptador** | Refina CA-05 sin contradecir su verificacion. Si cada adaptador lo inventara por su cuenta no tendria con que correlacionar la llamada con su resultado (los dos bloques llegarian con el id vacio). Normalizado en el bucle, el mismo id sobrevive a un cambio de proveedor a mitad de turno, que es el motivo entero de D-1.
2026-09-08 | orion-architect | **D-7: en el historial nativo los `argumentos` viajan sin `channel`/`user_id`/`texto_original`** | El bloque guarda el dict ejecutado completo porque CA-07 exige el mismo `repr` de dict que hoy, pero lo que se manda al proveedor pasa por `argumentos_para_el_modelo()`. Con presupuesto 40 y 3 herramientas por vuelta, `texto_original` (el mensaje entero del usuario) se repetiria mas de 100 veces en el prompt. La constante vive en `core/tool_history.py`, no en `llm_provider`, para no meterle a la capa de proveedores conocimiento del modelo de seguridad.
2026-09-08 | orion-architect | **D-4: la cache tampoco ve un historial de herramientas** (generaliza CA-40) | La llamada de cierre va con `tools=None` y hoy SI entraria a `_cached_call()`. Cachear el cierre de un turno de investigacion devolveria manana la respuesta de hoy, y expone `_cache_key()` a contenido estructurado — con la consecuencia perversa de que un fallo de serializacion se registraria como fallo del proveedor y lo mandaria a cooldown. Con la regla, `_cache_key()` no necesita ni una linea de cambio.
2026-09-08 | orion-architect | **D-9: `ModoComposer.presupuesto` es obligatorio, sin default; D-10: el system prompt se calcula una vez por turno; D-11: `claude_brain` solo sube `MAX_TOOL_ROUNDS`** | D-9 confirma el ASUMIDO 3 y agrega que un modo nuevo que olvide declararlo debe explotar al importar, no heredar 8 en silencio. D-10 evita 40 lecturas de disco y 40 prefijos distintos por turno (el bloque de fecha/hora cambia al minuto y anula el cacheo de prefijo justo en el turno mas caro). D-11 confirma el ASUMIDO 4 y la decision P-3 de Johan.
2026-09-08 | orion-architect | **Correccion de aritmetica: los conteos literales de CA-13, CA-14, CA-15 y CA-24 contradicen CA-30** | La SPEC redacto la seccion B antes de que Johan aprobara P-2 y no reajusto los numeros: con la llamada de cierre fuera del presupuesto, `call_count` es 26/41 (CA-13), 9 (CA-14), 6 (CA-15) y `MAX_LLM_CALLS + 1` (CA-24). Se corrige por aritmetica, no por criterio, y se recomienda que los tests aseveren sobre las llamadas CON `tools` en vez del total. Registrado en `arquitectura-027.md` §7 y como aviso A-2.
2026-09-08 | orion-architect | Propuesta entregada: `propuestas/arquitectura-027.md`. **Tracker NO movido** — sigue en SPEC_APROBADO | El arquitecto corre como subagente y no puede recibir aprobacion humana; la aprobacion y el cambio de estado los gestiona la conversacion principal. Sin codigo escrito, sin commit, sin rama nueva.

2026-09-08 | conversacion principal (Johan) | **P-5 resuelto: rama desde `feature/mcp-correo-flujos`** | Creada `feature/REQ-027-reasoning-loop-nativo` desde ahi y no desde `main`, porque `main` no contiene REQ-026 (`core/composer_modes.py` no existe alli) y CA-12 cuelga los presupuestos de ese archivo. La rama de origen estaba exactamente 1 commit por delante de `main` y ese commit es REQ-026, asi que el resultado equivale a "main + la dependencia".
2026-09-08 | conversacion principal (Johan) | **A-2 resuelto: el cierre va FUERA del presupuesto** | Investigacion = 25 vueltas CON herramientas mas 1 llamada de cierre. El numero que Johan eligio sigue significando lo mismo que cuando lo eligio: vueltas utiles de trabajo. Los tests aseveran sobre las llamadas que llevaron `tools`, no sobre el total, asi que no se rompen si cambia el mecanismo de cierre. A-1 (el cierre recibe el historial en texto por restriccion de la API de Anthropic) se acepto sin cambios.
2026-09-08 | conversacion principal (Johan) | **arquitectura-027.md APROBADA sin ajustes** | Tracker a ARQUITECTURA_APROBADA. Implementacion en la conversacion principal, sin `orion-dev` como subagente (pipeline acortado).
2026-09-08 | implementacion | Los 8 pasos de `arquitectura-027.md` §11 aplicados | 2 archivos nuevos (`core/tool_history.py`, `tests/test_tool_history.py`) y 5 modificados (`ai/llm_provider.py`, `core/reasoning_loop.py`, `core/composer_modes.py`, `ai/claude_brain.py`, mas 2 de tests). Sin dependencias nuevas. Detalle en `propuestas/desarrollo-log-027.md`.
2026-09-08 | implementacion | Desviacion 1: `_llamada_de_cierre()` no recibe `modo_def` | La arquitectura lo listaba en la firma pero quedaba sin uso: lo unico que el modo aporta a esa llamada es `system_prompt` y `tarea`, y las dos llegan ya resueltas desde `run()` (se calculan una vez por turno, D-10). Se omitio en vez de arrastrar un parametro muerto. Helper privado, sin callers externos ni tests que lo referencien.
2026-09-08 | implementacion | Desviacion 2: el respaldo defensivo de ids vive en `core/tool_history.py`, no duplicado en cada traductor | D-5 pedia "respaldo defensivo en los traductores". Se implemento como `con_ids_normalizados()`, una sola funcion que ambos llaman al entrar. Si cada traductor numerara por su cuenta, dos proveedores podrian asignar ids distintos al mismo historial — que es exactamente el problema que D-5 quiere evitar. El modulo neutral es el que sabe como se emparejan llamada y resultado.
2026-09-08 | implementacion | **Fallo real encontrado por la suite: un test de seguridad que ya no protegia nada** | `tests/test_skill_tools.py::test_el_texto_original_lo_pone_el_bucle_no_el_modelo` hacia grep sobre el fuente de `run()` buscando `params["texto_original"] = task`; REQ-027 movio esa linea a `_ejecutar_vuelta()`. El invariante seguia intacto (y ahora se aplica a las N herramientas de la vuelta, no a una), pero el test miraba una funcion donde el dato ya no estaba. Corregido apuntandolo a `_ejecutar_vuelta()` y agregandole una verificacion de COMPORTAMIENTO —un `texto_original` propuesto por el modelo tiene que quedar pisado, en todas las llamadas de la vuelta— que no depende de donde este escrita la linea.
2026-09-08 | implementacion | Suite completa: **1875 passed, 0 failed** (baseline 1828) | +47 tests, cero regresiones. Los 11 warnings son los mismos del baseline. Tracker a EN_QA: falta unicamente la prueba manual de Johan (CA-35 y CA-45).

## Invariantes que este REQ NO puede romper
- **Gate de seguridad REQ-005/REQ-006:** toda ejecución sigue siendo por
  `agents/tool_registry.py::execute_tool()`, nunca por `ToolSpec.invoke` directo.
- **`channel`/`user_id` los pone el caller confiable, nunca el LLM**
  (`core/reasoning_loop.py::run()`, docstring "INVARIANTE DE SEGURIDAD").
- **Degradación con proveedor sin tool-calling:** si `generate_response()` devuelve texto
  plano en vez de `LLMToolResponse`, se acepta como respuesta final (CONFIRMADO 1 de
  REQ-007). El camino nativo no puede romper a `gemini`/`ollama`.
- **`core/cancelacion.py`:** el corte por vuelta se mantiene y pasa a ser más importante
  cuanto más alto sea el presupuesto.
- **`ai/claude_brain.py`** (Telegram/Discord) comparte `catalogo_para_modelo()` y no tiene
  noción de modo — no puede quedar roto ni obligado a conocer el presupuesto por modo.

## Riesgo conocido a vigilar
`tests/modelo_falso.py` reemplaza `core.reasoning_loop.run` con una **función plana**
(no `MagicMock`) vía fixture autouse en varios tests. Un kwarg nuevo en la firma explota
con `TypeError` en 58 tests ajenos — pasó exactamente eso en REQ-026 (ver
`REQ-026-context.md`, entrada de `orion-dev`). Cualquier cambio de firma de `run()` tiene
que contemplarlo desde el diseño, no descubrirlo en la implementación.

**Cerrado por SPEC-027/CA-17:** el presupuesto se deriva de `modo` y `channel`, que ya son
parámetros de `run()`. La firma NO cambia, así que `tests/modelo_falso.py` no se toca
(CA-43) y el riesgo desaparece en vez de mitigarse.

## Riesgos nuevos que abre este REQ (para orion-architect)
- **Ventana de contexto con presupuesto alto.** Con 40 vueltas y resultados largos de
  `web_read`, el historial nativo puede exceder la ventana del modelo. No hay compactación
  del historial de herramientas en este REQ (fuera de alcance); el fallo debe manejarse
  como cualquier error de proveedor —cadena de respaldo, aviso, respuesta al usuario— y
  nunca como crash del turno (SPEC-027, casos borde).
- **Sin tope de tool calls por vuelta** (Johan lo descartó). Lo que acota una vuelta con 50
  llamadas es el gate por herramienta, la cancelación entre herramientas (CA-27) y el
  presupuesto de vueltas — nada más.
- **Voz + `max_tokens` 4096.** Condición preexistente que este REQ agrava: una respuesta
  larga leída por TTS son varios minutos que nadie puede cortar. Queda como P-4.

## Pendiente
- ✅ SPEC-027 redactada: `workspace/adjuntos/REQ-027/spec/SPEC-027.md` (45 CA en 6 secciones)
- ⏸️ Aprobación de Johan de SPEC-027 — incluye responder P-1 a P-5 de
  `## PENDIENTE DE JOHAN` (denegación con `tools=None`; si entra la llamada de cierre por
  presupuesto agotado; si `claude_brain` migra a nativo; tope de tokens para voz; rama git)
- ✅ baseline-027.md: `workspace/adjuntos/REQ-027/origen/baseline-027.md` (1828 passed, 0 failed)
- ✅ arquitectura-027.md redactada: `workspace/adjuntos/REQ-027/propuestas/arquitectura-027.md`
  (11 decisiones de diseño D-1 a D-11, trazabilidad de los 45 CA, 2 avisos no bloqueantes)
- ⏸️ Aprobación de Johan de arquitectura-027.md — incluye leer los avisos A-1 (el cierre va con
  el historial en texto, no en nativo, porque Anthropic rechaza `tool_use` sin `tools`) y A-2
  (los conteos de CA-13/14/15/24 corregidos por aritmética contra CA-30)
- Implementación (conversación principal)
- Definir rama git con Johan antes de tocar código (P-5)

2026-09-18 | → LISTO_PARA_COMMIT | conversación principal (sesión nocturna autorizada por Johan) | Sincronización del tracker con `main`: el código de este REQ ya está commiteado y mergeado y la evidencia (QA aprobado y/o suite en verde registrada en este contexto) estaba completa. Solo cambia el estado; no se toca código.
