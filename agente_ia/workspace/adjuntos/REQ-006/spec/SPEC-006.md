# SPEC-006 — Pipeline único de resolución con paridad de canales + bucle de agente con herramientas

**Estado:** ⏸️ ESPERANDO VALIDACIÓN
**Categoría:** CORE
**Tipo:** REFACTOR + FEATURE_NUEVA
**Fecha:** 2026-08-01

> ⛔ **Bloqueo de secuencia vigente.** Este REQ avanza solo hasta arquitectura. Ningún `.py` se
> modifica hasta que el humano cierre REQ-005 (prueba manual OK + commit). Esta SPEC es un
> documento; no toca código.

> 🔀 **Partición aprobada por el humano (2026-08-01).** El trabajo se ejecuta en **dos REQ**, pero
> se diseña **una sola vez**:
> - **REQ-006 = criterios [A]** — pipeline único de resolución con paridad de canales.
> - **REQ-007 = criterios [B]** — bucle de razonamiento con herramientas.
>
> **`orion-architect` produce UNA SOLA ARQUITECTURA compartida** que cubre pipeline, contrato de
> canal, registro de herramientas y bucle. **Quien retome REQ-007 NO debe rediseñar nada**: hereda
> el mismo documento de arquitectura y solo ejecuta los criterios [B]. Se parte la ejecución, nunca
> el diseño — precisamente para que ninguna decisión tomada en [A] cierre puertas a [B].

> 🔗 **El MCP dejó de estar diferido (2026-08-01).** El humano levantó el aplazamiento: *"si quiero
> que trabajes para que el agente tenga todo lo necesario y las herramientas disponibles para que
> trabaje con MCP, ya que me están solicitando la conexión del agente con SIGAIND"*. **El cliente
> MCP NO se implementa en REQ-006 ni en REQ-007** — va en un REQ propio de categoría INTEGRACION,
> posterior a ambos. Lo que sí cambia acá es el **peso** del registro de herramientas: pasa de
> mejora interna a **camino crítico de un compromiso externo con terceros que ya están esperando**.
> Ver "Decisión 6" y los criterios CA-14 a CA-17.

---

## Objetivo

O.R.I.O.N. resuelve la misma petición de forma distinta según el canal por el que entre, y su
motor de resolución es un clasificador cerrado con handlers terminales en vez de un bucle de
agente. Este REQ establece **un único pipeline de resolución** compartido por consola, GUI,
Telegram y voz, y —en su continuación REQ-007— **construye** un bucle en el que el agente razona,
elige una herramienta, observa el resultado y reacciona, sin debilitar el gate fail-closed de
REQ-005.

**Por qué ahora y no después.** Hasta hoy este REQ se justificaba por deuda interna: capacidades
inalcanzables, canales divergentes, un clasificador que se degrada al crecer. Con el levantamiento
del aplazamiento del MCP, el **registro de herramientas que [A] define** se vuelve la pieza sobre
la que se apoya una integración comprometida con un tercero (SIGAIND). El contrato de herramienta
que se fije en la arquitectura no es un detalle interno reversible: **es la superficie sobre la que
se conectará el MCP**. Diseñarlo mal obliga a escribir un traductor; diseñarlo bien reduce la
conexión a "leer el discovery y registrar".

---

## Hallazgos que fundamentan la SPEC

Los cuatro primeros vienen del diagnóstico ya verificado por `orion-coordinador` (no se
re-descubren). Los cuatro últimos son **nuevos**, verificados durante esta SPEC y **confirmados de
primera mano por el humano** (H5 y H7).

### Heredados del contexto (H1–H4)

| # | Hallazgo | Evidencia |
|---|----------|-----------|
| H1 | El clasificador cortocircuita al agente: si el intent no es `UNKNOWN`, se ejecuta el handler legacy y se retorna de inmediato. La capa inteligente es el último recurso. | `core/orchestrator.py:39-49`, `:60-71` |
| H2 | Los handlers son terminales: su string de retorno *es* la respuesta final. Sin escalado ni reacción al fracaso. | `router/dispatcher.py` (~26 intents fijos) |
| H3 | `tasks/task_manager.py` es un subsistema completo e inalcanzable: no existe `Intent` de recordatorio, ni skill, ni `AgentTool`. Solo lo consumen Telegram y el gateway. | `channels/gateway.py:110-147`, `:149-163`, `:165-223` |
| H4 | Pipelines divergentes por canal; Telegram hace matching propio de frases antes de entregar al gateway. | `main.py:105-204`, `channels/gateway.py:56-102`, `channels/telegram_bot.py:548`, `:602` |

### Nuevos — verificados en esta SPEC (H5–H8)

**H5 — El canal `voice` no se emite nunca. La restricción de voz de `security-levels.md` es
letra muerta.** *(Confirmado por el humano.)* `ChannelType.VOICE` existe y está correctamente limitado a
`[RiskLevel.GREEN]` en `core/security_manager.py:29-36`, pero **ninguna ruta del sistema pasa
`"voice"`**. En `main.py`, las entradas por micrófono (`choice == '2'` y `choice == '3'`,
líneas 80-97) desembocan en el mismo bloque de ejecución que el texto, y las seis rutas de
despacho hardcodean `channel="desktop"` (`main.py:40, 108, 136, 155, 167, 203`). Consecuencia
real: **una orden dictada por micrófono se evalúa hoy como DESKTOP y por lo tanto puede ejecutar
acciones AMARILLAS** —cerrar aplicaciones, borrar archivos, apagar el PC— que la regla prohíbe
expresamente por voz. Esto no es una discusión de redacción: es un agujero abierto, y es
precisamente lo que la Decisión 1 (abajo) cierra.

> **Riesgo residual mientras el bloqueo de secuencia siga vigente.** El defecto permanece abierto
> hasta que se ejecute [A]. Su explotación **requiere acceso físico al micrófono del equipo**: no
> es alcanzable de forma remota, ningún canal externo (Telegram, Discord, API) puede provocarlo, y
> los canales remotos siguen correctamente limitados a verde por `CHANNEL_ALLOWED_LEVELS`. El
> escenario realista no es un atacante sino un **falso positivo de STT del propio usuario**. Con
> ese perfil de riesgo acotado, el humano decidió **no adelantar el parche** (Decisión 4).

**H6 — El clasificador usa un modelo persistido obsoleto; el training data de las skills es
código muerto.** `intent/ai_classifier.py:_load_or_train()` carga `intent/saved_model.pkl` si
existe y solo entrena cuando falta. El `.pkl` en el árbol es del **25 de abril**, mientras que
`ai_classifier.py` —que contiene las ~254 frases de `_get_training_data()`— se modificó por
última vez el **7 de junio**. El modelo en uso lleva seis semanas sin reflejar su propio dataset.
Y como `get_all_training_data()` de las skills solo se consulta **dentro de `_train()`**, una
skill nueva **jamás entra al clasificador** mientras el `.pkl` siga en disco: se registra su
intent en `_intent_to_skill`, pero el modelo nunca aprende a predecirlo. Es la explicación
mecánica de por qué "agregar capacidades no sirve de nada".

**H7 — No existe ningún bucle de agente. Lo que hay es un `for` sobre una lista.** *(Verificado
por el humano en `core/base_agent.py:94-107`.)* Precisión deliberada de redacción, porque
condiciona el tipo de trabajo:

> `_DynamicAgentInstance.execute()` **no es un bucle agéntico degradado ni una versión incompleta
> de uno**. Es un `for` sobre `self.tools` que devuelve la primera herramienta cuyo `result[:10]`
> no contenga la subcadena `"Error"`. **No hay LLM en ninguna parte del camino.** El
> `system_prompt` se construye en `DynamicAgentFactory._generate_prompt()` y nunca se usa;
> `DynamicAgentFactory._llm` se recibe en `__init__` y nunca se lee.

En consecuencia, **[B] es construcción desde cero**. Esta SPEC no dice en ningún punto "reparar",
"mejorar" ni "arreglar" el bucle: no hay nada que reparar. Efectos secundarios verificados:

- `main.py:16-20` registra `dispatcher` como **primera** herramienta, de modo que el agente siempre
  intenta el dispatcher legacy antes que cualquier skill.
- **Defecto de seguridad, no solo de diseño:** `"⛔ Acción no autorizada."` —el string que devuelve
  `_make_gated_tool_fn` cuando el gate deniega— **no contiene `"Error"` en sus primeros 10
  caracteres**. Por lo tanto el `for` lo interpreta como **éxito**, corta el recorrido de
  herramientas y **devuelve la denegación al usuario como si fuera la respuesta**. Una acción
  bloqueada por el gate es hoy indistinguible de una acción resuelta. Ver **CA-09**.

**H8 — Cero cobertura de pruebas sobre clasificación de intents y sobre el dispatcher.** `pytest`
colecta 54 tests, de los cuales **49 provienen de `tests/test_security_manager.py`** (REQ-005) y 5
de `tests/test_agents.py`. `tests/test_classifier.py`, `tests/test_dispatcher.py`,
`tests/test_autopilot.py` y `tests/test_memory.py` **colectan 0 tests cada uno**: son scripts con
`run_tests()` e impresiones por pantalla, sin `assert` y sin funciones `test_*`. Hoy **una
regresión de clasificación o de ruteo es completamente silenciosa**.

**H9 — El mecanismo de confirmación está atado a la consola, y eso es lo que hace inútil el nivel
amarillo fuera del escritorio.** *(Verificado por el humano.)* En
`core/security_manager.py:240`, dentro de `require_confirmation()`:

```python
response = input(f"\n⚠️  {msg}\nEscribe 'sí' para confirmar, ...")
```

`input()` lee del **stdin del proceso**. Un usuario de Telegram, de la GUI o de voz no tiene forma
de responder eso. La consecuencia se ve en `CHANNEL_ALLOWED_LEVELS` (`:30-36`): `TELEGRAM`,
`DISCORD`, `VOICE` y `API` están limitados a **solo GREEN**, y en `:233` el amarillo se descarta
por canal **antes** de llegar al `input()`.

> El bloqueo del amarillo en canales remotos **no es una decisión de política de riesgo: es una
> consecuencia técnica** de que la confirmación solo sabe hablar por consola.

Además **contradice `.claude/rules/security-levels.md`**, que prescribe: *"Telegram/Discord:
Amarillo siempre requiere confirmación explícita, Rojo bloqueado"*. El código **no confirma:
bloquea**. Es más estricto que la regla —no hay agujero de seguridad— pero incumple la regla
escrita y niega la funcionalidad que el humano quiere (*"que el bot de Telegram sea muy
funcional"*).

**Fragilidad que esto elimina de paso:** hoy, si alguna ruta futura llevara una acción amarilla
hasta la línea 240 desde un contexto **sin stdin interactivo** —el scheduler de tareas, el canal
`API`, un hilo de fondo—, el proceso **se colgaría** esperando una respuesta que nadie puede dar.
Lo único que lo evita hoy es el chequeo de canal previo de `:233`. Es una protección incidental,
no un diseño. Ver **CA-10**.

### El costo que el REQ debe eliminar

`intent/ai_classifier.py` usa `TfidfVectorizer(ngram_range=(1,3))` + `LinearSVC(C=1.5)` sobre
~254 frases y 28 intents. `LinearSVC` es multiclase **one-vs-rest**: cada intent nuevo redibuja
las fronteras de decisión de todos los demás. Sumar una capacidad puede degradar otra ya
existente, y —por H8— degradarla sin que nadie se entere. Ése es el impuesto que este REQ elimina:
**agregar una capacidad debe dejar de ser un evento de riesgo global.**

---

## Decisiones cerradas del humano (no se re-preguntan)

### Decisión 1 — Paridad significa misma inteligencia, no misma autoridad

> Todos los canales razonan, encadenan herramientas y reaccionan **igual**. Lo que **no** se iguala
> son los permisos.

La restricción de `.claude/rules/security-levels.md` sobre voz (**solo acciones verdes**) **se
mantiene y, por H5, pasa a aplicarse de verdad por primera vez**. El motivo es explícito: el
micrófono no autentica a nadie y un error de STT puede disparar una acción destructiva.

Formulación normativa, para que QA no lo lea como incumplimiento:

> **La paridad de REQ-006 es de _capacidad de razonamiento_, no de _autoridad_.** Ante la misma
> petición, todos los canales recorren el mismo pipeline, construyen el mismo plan, consideran el
> mismo conjunto de herramientas y llegan al mismo punto de decisión. Lo único que puede diferir
> entre canales es **el veredicto de `security_manager.require_confirmation()`** y, en
> consecuencia, la respuesta al usuario. Un canal nunca resuelve *distinto*; a lo sumo se le
> *deniega* lo mismo que otro tiene permitido.

Corolario de diseño: el nivel de riesgo sigue viviendo en `security_manager`, no se delega al
canal. El canal solo declara sus capacidades (por ejemplo, si soporta confirmaciones
interactivas). Ver CA-04, CA-05, CA-06 y CA-08.

### Decisión 2 — Alcance de bugs: solo los 2 del orquestador, uno por mitad

**Entran**, porque viven en el código que este trabajo reescribe. Cada bug viaja con el código que
lo reescribe:

| Bug | Va a | Motivo |
|-----|------|--------|
| `main.py:34` — `return 0.0 if "briefing" in task.lower() or "recordatorio" in task.lower() else 0.0`: ambas ramas del ternario devuelven `0.0`, así que `_ProactiveAssistant` nunca se activa. | **[A] / REQ-006** (CA-12) | `_ProactiveAssistant` es un caller del pipeline, y [A] redefine el punto de entrada. |
| `core/orchestrator.py:87-98` — `_decompose()` compara por subcadena y parte por la **letra** "y": `"ayúdame con el proyecto"` → `["a", "údame con el pro", "ecto"]`, cada fragmento a un agente distinto. | **[B] / REQ-007** (CA-24) | `_decompose()` probablemente **desaparezca** al construir el bucle real; arreglarlo en [A] sería trabajo tirado dos veces. |

**Quedan explícitamente fuera** y salen como fix independiente. **Nadie los toca ni en REQ-006 ni
en REQ-007:**

- `skills/skill_manager.py:32` — `exec_module()` fuera de todo `try`: un `SyntaxError` en cualquier
  skill aborta la carga completa.
- `skills/skill_manager.py:46` — `register_skill()` pisa intents en silencio.
- `ai/llm_provider.py:27` — `_cached_call()` cachea los errores y descarta al proveedor primario
  hasta reiniciar.

### Decisión 3 — Partición aceptada: dos REQ, una arquitectura

Ver el recuadro del encabezado. `orion-architect` diseña una sola vez; la ejecución se parte en
REQ-006 [A] y REQ-007 [B]. Motivos registrados: el riesgo de regresión es de naturaleza distinta en
cada mitad ([A] determinista, [B] no determinista con LLM) y en un solo commit una regresión no se
podría atribuir; [A] toca el gate de seguridad (H5, H9) y debe auditarse sin el ruido de un bucle
de LLM; [A] entrega valor observable por sí sola; y la dependencia es unidireccional.

### Decisión 4 — H5 se cierra dentro de [A], sin adelantar

El bloqueo de secuencia se mantiene: **ningún `.py` se toca hasta que el humano cierre REQ-005**.
El agujero de voz se cierra como parte del pipeline único, que es exactamente el punto donde el
canal deja de estar hardcodeado — parchearlo antes exigiría tocar `main.py` ahora y duplicar el
mismo cambio después. Riesgo residual documentado en H5: requiere acceso físico al micrófono, no
es explotable remotamente.

### Decisión 5 — Cobertura ejecutable: reconocimiento **y** ruteo

`tests/test_autopilot.py`, `tests/test_dispatcher.py` y `tests/test_memory.py` quedan como **deuda
registrada**, no se convierten a `pytest` en este trabajo. Pero la cobertura que sí se exige **no
puede limitarse a la clasificación**: [A] reescribe también el camino de despacho, de modo que un
corpus que solo verifique el intent dejaría invisible una regresión de ruteo — justo el riesgo que
motivó el criterio. La cobertura abarca **reconocimiento de intent + ruteo hasta la herramienta
correcta**, medida antes y después del cambio. Ver **CA-13**.

### Decisión 6 — El contrato de herramienta debe ser isomorfo a una tool MCP

El cliente MCP **no se implementa** en REQ-006 ni en REQ-007. Pero el **contrato interno de
herramienta** que define [A] sí debe quedar diseñado de forma que un servidor MCP pueda aparecer
después como una fuente más de herramientas **sin tocar el core y sin escribir un traductor**.

Justificación concreta, no hipotética: SIGAIND ya expone `GET /mcp/agro-bi` con **discovery +
esquema de parámetros** y `POST /mcp/agro-bi/invoke` para ejecutar (ver
`.claude/skills/skill-mcp-sigaind-v01.md`, §2). Si el contrato interno coincide en forma, conectarlo
se reduce a **"leer el discovery y registrar"**. Si diverge, hay que escribir y mantener una capa de
adaptación. Requisitos que [A] debe satisfacer:

1. **Isomorfismo estructural.** El contrato expresa, como mínimo: nombre, descripción en lenguaje
   natural, **esquema de parámetros (JSON Schema)** e invocación. Una tool declarada localmente y
   una tool descrita por un discovery MCP deben representarse con **la misma estructura interna,
   sin campos de adaptación**. Ver CA-14.
2. **Nivel de riesgo declarable por la herramienta.** Entre las tools de SIGAIND hay **escritura y
   aprobación de órdenes de agronomía** (`agro_crear_orden`, `agro_aprobar_orden`,
   `agro_crear_lote`, `agro_editar_lote`, …), no solo consultas. Consulta = verde; escritura y
   aprobación = amarillo o rojo con confirmación. El contrato debe poder **transportar ese nivel
   declarado**. Añadirlo después obligaría a rediseñar el contrato. Ver CA-15.
3. **La herramienta declara; `security_manager` decide.** El nivel que viene con la tool es una
   **declaración de origen, no una autorización**. `security_manager` sigue siendo el único árbitro
   y sigue siendo **fail-closed**: una tool remota que declare "verde" no se auto-autoriza, y una
   tool sin nivel declarado **se bloquea**, no se permite. Ver CA-15.
4. **Origen remoto descubierto en runtime.** El registro debe admitir herramientas provenientes de
   una fuente descubierta en tiempo de ejecución, no solo declaradas en código. **No se implementa
   nada de eso acá**: solo se exige que el contrato no lo impida. Ver CA-16.

**O.R.I.O.N. no necesita volverse multi-usuario.** SIGAIND resuelve empresa y permisos **a partir
del usuario asociado al token** (`skill-mcp-sigaind-v01.md` §3.2 y §3.3: *"la empresa se toma
siempre del token, nunca de lo que pida el agente"*). O.R.I.O.N. solo debe **portar el token
correcto**; el control de acceso de negocio vive en el servidor. Queda asentado para evitar un
rediseño innecesario más adelante. Ver CA-17.

### Decisión 7 — La confirmación se vuelve agnóstica del canal (H9)

[A] debe entregar la **capacidad técnica** de pedir confirmación por cualquier canal: botones
inline en Telegram, diálogo en la GUI PyQt6, prompt en consola, y en voz según la política que
quede. Encaja exactamente con el contrato de canal que [A] ya introduce: el canal deja de ser solo
una etiqueta de riesgo y pasa a ser también **el medio por el que se pide la confirmación**.

Límites explícitos de esta decisión — para que nadie la lea como algo que no es:

- **No relaja la seguridad.** La decisión de permitir/bloquear sigue siendo de `security_manager` y
  sigue siendo fail-closed. Lo único que cambia es **quién le hace la pregunta al humano**.
- **`CHANNEL_ALLOWED_LEVELS` NO se modifica en este REQ.** Habilitar amarillo en Telegram es una
  decisión de **política** que le corresponde al humano y probablemente a `orion-security`, no a
  esta SPEC. [A] entrega la capacidad; **abrir la matriz es un paso posterior y explícito**.
- **RED no se toca.** Sigue bloqueado en todos los canales, con la única excepción del PIN maestro
  en `DESKTOP` que ya existe.

Ver **CA-10**.

---

## Alcance

### REQ-006 [A] — incluye

1. **Punto único de resolución.** Una sola función de entrada —`resolve(text, channel, user_id)` o
   equivalente que fije `orion-architect`— por la que pasan consola, GUI, Telegram y voz. Los
   canales dejan de decidir *cómo* se resuelve; solo aportan el mensaje, su identidad de canal y
   sus capacidades.
2. **Eliminación del pre-matching por canal.** El matching de frases de `channels/telegram_bot.py`
   (apagado/reinicio, líneas 548 y 602) y los pre-chequeos de tareas de `channels/gateway.py`
   (`_try_create_task`, `_try_list_tasks`, `_try_complete_task`) dejan de ser rutas propias del
   canal y se convierten en herramientas del pipeline común.
3. **Emisión correcta del canal, incluida `voice` (H5).** La entrada por micrófono se identifica
   como `voice` y deja de heredar los permisos de `desktop`.
4. **Contrato de resultado de herramienta con denegación distinguible** (defecto de seguridad de H7).
5. **Confirmación agnóstica del canal** (H9), sin modificar `CHANNEL_ALLOWED_LEVELS`.
6. **Contrato de herramienta isomorfo a una tool MCP**, con nivel de riesgo declarable y origen
   remoto admisible (Decisión 6). **Solo el contrato: ningún cliente MCP.**
7. **`task_manager` expuesto como herramienta gateada (H3).** Cierra el caso concreto que reportó
   el humano: pedir un recordatorio por escritorio y que no pase nada.
8. **Bug `main.py:34`.**
9. **Cobertura ejecutable de reconocimiento y ruteo (H8), medida antes y después.**

### REQ-007 [B] — incluye

10. **Construcción del bucle de agente con herramientas (H7).** El agente propone una herramienta,
    la ejecuta, **observa el resultado** y decide el paso siguiente, con tope de iteraciones y
    criterio de terminación explícito. El resultado de un handler deja de ser automáticamente la
    respuesta final.
11. **Registro de herramientas que no exija reentrenar el clasificador.** Agregar una capacidad se
    vuelve un alta declarativa en el registro, no una modificación del dataset de `LinearSVC`.
12. **Corrección del modelo obsoleto / training data muerto (H6).**
13. **Bug `_decompose()`.**

### No incluye (ninguna de las dos mitades)

- **El cliente MCP.** El aplazamiento se levantó, pero la **implementación** va en un REQ propio de
  categoría INTEGRACION, posterior a [A] y [B]. Acá solo se fija el **contrato** para que conectarlo
  después sea "leer el discovery y registrar" (Decisión 6). No se escribe transporte HTTP, ni
  manejo de token, ni parsing de discovery, ni las 31 tools de SIGAIND.
- **Abrir `CHANNEL_ALLOWED_LEVELS` a amarillo en Telegram/Discord/voz.** [A] entrega la capacidad
  técnica de confirmar por cualquier canal (Decisión 7); **cambiar la política de la matriz es una
  decisión posterior y explícita** del humano, con participación de `orion-security`.
- **Los 3 bugs de `skill_manager.py` y `llm_provider.py`** (Decisión 2).
- **Fusionar el proceso de escritorio con el de bots.** PyQt6 necesita el hilo principal.
  `start_bots.py` ya es un anfitrión persistente multi-canal con supervisión: la unificación es un
  **refactor del pipeline de resolución**, no una fusión de procesos.
- **Convertir el core a `async`.** Descartado de entrada (ver CA-11).
- **Convertir `test_autopilot.py`, `test_dispatcher.py` y `test_memory.py` a `pytest`**
  (Decisión 5). Deuda registrada.
- **Volver a O.R.I.O.N. multi-usuario.** SIGAIND resuelve permisos por el usuario del token
  (Decisión 6). No hace falta.

---

## Módulos afectados

| Módulo | Mitad | Qué cambia |
|--------|-------|-----------|
| `main.py` | [A] | Deja de ser un pipeline propio: delega en el punto único. Emite `voice` en las entradas por micrófono (H5). Corrige `can_handle()` en `:34`. |
| `channels/gateway.py` | [A] | Deja de pre-resolver tareas; delega en el pipeline común. Sigue siendo dueño del aislamiento por usuario y del formato de respuesta. |
| `channels/telegram_bot.py` | [A] | Elimina el matching propio de frases (`:548`, `:602`). Declara sus capacidades de canal e **implementa el pedido de confirmación** (botones inline) según el contrato de H9. |
| `ui/` (GUI PyQt6, CLI) | [A] | Implementan el pedido de confirmación de su canal: diálogo modal y prompt de consola respectivamente (H9). |
| `core/security_manager.py` | [A] | **No se relaja y `CHANNEL_ALLOWED_LEVELS` no se modifica.** Sigue siendo el único dueño del nivel de riesgo y el único árbitro. Cambia únicamente **cómo obtiene la respuesta**: el `input()` de `:240` deja de ser la única vía y se delega al adaptador del canal (H9). Puede requerir altas de clasificación para herramientas nuevas. |
| `core/base_agent.py` (`AgentTool`) | [A] y [B] | En [A] el contrato de herramienta gana esquema de parámetros, nivel de riesgo declarable y resultado estructurado con denegación distinguible (Decisión 6, H7). En [B] se **construye el bucle desde cero**: `_DynamicAgentInstance.execute()` deja de ser un `for` sobre `self.tools` y se resuelven el `system_prompt` y `_llm` muertos. |
| `skills/skill_manager.py` | [A] y [B] | Fuente de herramientas del registro; se adapta al contrato nuevo. `_make_gated_tool_fn` es el patrón a extender. **Sus 2 bugs quedan fuera** (Decisión 2). |
| `router/dispatcher.py` | [A] y [B] | En [A] se integra al pipeline único conservando el gate central de REQ-005 en `dispatch()`. En [B] los handlers dejan de ser terminales: pasan a ser herramientas invocables cuyo resultado el agente puede observar (H2). |
| `core/orchestrator.py` | [A] y [B] | En [A] deja de ser un punto de entrada divergente. En [B] desaparece el cortocircuito `_try_quick_dispatch` → retorno inmediato (H1) y se corrige o elimina `_decompose()`. |
| `tasks/task_manager.py` | [A] | No cambia su lógica; se envuelve como herramienta gateada (H3). |
| `intent/ai_classifier.py`, `intent/classifier.py` | [B] | El clasificador deja de ser el árbitro único. Se corrige la carga de modelo obsoleto (H6). |
| `tests/` | [A] y [B] | Tests `pytest` nuevos para los criterios de cada mitad (H8). |

---

## Comportamiento actual vs deseado

| Actual | Deseado | Mitad |
|--------|---------|-------|
| Telegram matchea "apaga el pc" antes del gateway; consola y gateway resuelven en órdenes distintos. | Un único pipeline; el canal aporta identidad y capacidades, no lógica de resolución. | [A] |
| Una orden por micrófono se evalúa como `desktop` y puede ejecutar acciones amarillas (H5). | La entrada por micrófono se evalúa como `voice`: mismo pipeline, mismo plan, solo acciones verdes autorizadas. | [A] |
| Una acción denegada por el gate se devuelve al usuario como si fuera la respuesta correcta (H7). | La denegación es un resultado estructurado, distinguible del éxito sin comparar subcadenas. | [A] |
| La confirmación solo sabe hablar por consola (`input()`), así que el amarillo se bloquea por canal en vez de confirmarse (H9). | La confirmación se pide por el canal de origen: botones inline, diálogo o prompt. `security_manager` sigue decidiendo. | [A] |
| Pedir un recordatorio por escritorio no hace nada: no hay ruta a `task_manager`. | `task_manager` es una herramienta gateada, alcanzable desde cualquier canal. | [A] |
| El contrato de `AgentTool` es nombre + descripción + función: no hay esquema de parámetros ni nivel de riesgo declarable. | Contrato isomorfo a una tool MCP, con JSON Schema y nivel declarado; conectar SIGAIND será "leer el discovery y registrar". | [A] |
| Una regresión de clasificación **o de ruteo** es silenciosa: 0 tests colectados (H8). | Reconocimiento y ruteo tienen tests `pytest` que fallan en rojo si se rompen. | [A] |
| El clasificador acierta un intent y el handler responde: el agente nunca se entera. | El agente es el árbitro; el clasificador es una señal más, no un cortocircuito. | [B] |
| `handle_wikipedia_summary` devuelve "no encontré" y ahí muere. | El agente observa el fracaso y escala a otra herramienta o lo reporta explicándolo. | [B] |
| No hay agente: hay un `for` que devuelve la primera herramienta que no falle, sin LLM (H7). | Existe un bucle que consulta al LLM, elige, observa y reacciona, con tope de iteraciones. | [B] |
| Agregar una capacidad exige tocar el dataset de `LinearSVC` y puede degradar otros 27 intents. | Agregar una capacidad es un alta en el registro de herramientas; el clasificador no se reentrena. | [B] |

---

## Criterios de aceptación

Todos verificables por `pytest`, salvo donde se indica inspección manual.

### REQ-006 [A] — Pipeline único de resolución con paridad de canales

- [ ] **CA-01 — Punto único de resolución.** Existe una única función de entrada al pipeline.
  Un test verifica que `main.py` (consola y voz), `channels/gateway.py` y `channels/telegram_bot.py`
  la invocan y que **ninguno** resuelve un intent, ejecuta un handler ni consulta `task_manager`
  por su cuenta antes de llamarla.
- [ ] **CA-02 — Sin pre-matching por canal.** Un test verifica que `channels/telegram_bot.py`
  ya no contiene matching de frases de apagado/reinicio previo a la entrega al pipeline, y que
  `channels/gateway.py` ya no resuelve tareas antes de clasificar. La entrada `"apaga el pc"` por
  Telegram y por consola recorre exactamente las mismas llamadas hasta el gate.
- [ ] **CA-03 — Igualdad de resolución entre canales.** Para un conjunto de peticiones
  representativas (una verde, una amarilla, una desconocida, una multi-paso), la traza de
  resolución —herramienta elegida y parámetros extraídos— es **idéntica** en `desktop`, `telegram`
  y `voice`. Solo puede diferir el veredicto del gate.
- [ ] **CA-04 — Misma petición por voz y por escritorio, mismo pipeline, mismo punto de
  decisión.** Un test ejecuta la **misma** petición amarilla (p. ej. `CLOSE_APP`) con
  `channel="voice"` y con `channel="desktop"` y verifica que: (a) ambas recorren la misma secuencia
  de llamadas y seleccionan la misma herramienta con los mismos parámetros; (b) ambas llegan a
  `security_manager.require_confirmation()` con la misma `action_name`; (c) **lo único que difiere
  es el veredicto** — `voice` deniega, `desktop` pide confirmación; (d) en `voice` la herramienta
  **no se ejecuta**.
- [ ] **CA-05 — El canal `voice` se emite de verdad (cierra H5).** Un test verifica que la
  entrada por micrófono llega a `require_confirmation()` con `ChannelType.VOICE` y **nunca** con
  `ChannelType.DESKTOP`. Complemento negativo: ninguna ruta de despacho alcanzable desde el
  micrófono hardcodea `channel="desktop"`. Cubre también el wake word que entrega texto ya
  capturado (`main.py:89`).
- [ ] **CA-06 — Solo verde por voz.** Para cada acción clasificada AMARILLA o ROJA, invocarla
  con `channel="voice"` es denegada y queda registrada en el audit log. Para las verdes, se ejecuta
  igual que en `desktop`.
- [ ] **CA-07 — El gate fail-closed de REQ-005 no se relaja.** Los 49 tests de
  `tests/test_security_manager.py` siguen pasando **sin modificación**. **Toda herramienta invocable
  por el agente está clasificada** en `security_manager`: un test recorre el registro completo de
  herramientas y falla si alguna no tiene nivel asignado. Una acción no clasificada se bloquea.
- [ ] **CA-08 — El nivel de riesgo no se delega al canal.** Ningún canal declara, sobrescribe
  ni deduce niveles de riesgo. El canal solo declara capacidades (p. ej. si soporta confirmaciones
  interactivas). Verificable por inspección + test de que `CHANNEL_ALLOWED_LEVELS` es la única
  fuente. **La matriz no se modifica en este REQ.**
- [ ] **CA-09 — La denegación del gate es un resultado distinguible del éxito (cierra el defecto
  de seguridad de H7).** La invocación de una herramienta devuelve un **resultado estructurado** que
  expresa el desenlace —autorizado y ejecutado / denegado por el gate / fallo de ejecución— como un
  valor propio, **no como una cadena de texto que haya que comparar por subcadena**. Tests: (a) una
  herramienta denegada por el gate produce un desenlace de denegación explícito y ninguna capa
  posterior lo confunde con éxito; (b) un test falla si el código clasifica el desenlace buscando
  `"Error"`, `"⛔"` o cualquier subcadena equivalente; (c) una herramienta cuyo texto de éxito
  *contenga* la palabra "Error" sigue tratándose como éxito, y una denegación cuyo texto no la
  contenga sigue tratándose como denegación.
- [ ] **CA-10 — La confirmación es agnóstica del canal (cierra H9).** `require_confirmation()`
  deja de depender de `input()` sobre el stdin del proceso: obtiene la respuesta del humano
  **a través del adaptador del canal que originó la petición**. Tests: (a) una acción amarilla
  originada en Telegram solicita la confirmación por Telegram y no invoca `input()`; (b) lo mismo
  para GUI y consola; (c) **`security_manager` sigue siendo el único que decide** — el canal
  entrega la respuesta del humano, nunca el veredicto; (d) un canal que **no** declara capacidad de
  confirmación interactiva produce **denegación**, no auto-confirmación ni bloqueo del proceso;
  (e) una acción amarilla ejecutada desde un contexto sin stdin interactivo (scheduler, hilo de
  fondo, canal `API`) **no cuelga el proceso**; (f) `CHANNEL_ALLOWED_LEVELS` permanece **sin
  cambios** respecto al baseline, y RED sigue bloqueado en todos los canales salvo el PIN maestro
  en `DESKTOP`.
- [ ] **CA-11 — El core no se vuelve `async`.** Un test verifica que los módulos del core
  (`core/`, `router/`, `intent/`, `skills/`) **no incorporan ni un `async def` nuevo** respecto al
  baseline. Los canales asíncronos siguen siendo asíncronos en su borde. Aplica también al camino
  de confirmación de CA-10: pedirle la respuesta a un canal asíncrono no debe volver `async` al
  `security_manager`.
- [ ] **CA-12 — `_ProactiveAssistant.can_handle()` corregido (Decisión 2).** `main.py:34`
  devuelve un valor distinto de `0.0` para tareas de briefing/recordatorio. Test que verifica que
  el trigger proactivo efectivamente se activa.
- [ ] **CA-13 — Cobertura ejecutable de reconocimiento *y* ruteo (cierra H8; Decisión 5).**
  Existe un test `pytest` real —con `assert`, colectable— que fija, para un corpus representativo de
  los 28 intents, **dos cosas por cada entrada**: (a) el intent reconocido y (b) **la herramienta
  concreta a la que se rutea, con sus parámetros extraídos**. El corpus se captura como línea base
  **antes** del cambio y se vuelve a medir **después**: cualquier diferencia en reconocimiento o en
  ruteo falla el test y exige decisión explícita. Un criterio que solo cubriera clasificación
  dejaría invisible una regresión de ruteo, que es precisamente lo que [A] reescribe.
  `tests/test_classifier.py` deja de colectar 0 tests.
- [ ] **CA-14 — El contrato de herramienta es isomorfo a una tool MCP (Decisión 6).** El contrato
  interno expresa como mínimo: **nombre, descripción en lenguaje natural, esquema de parámetros en
  JSON Schema e invocación**. Test: dada la descripción de una tool tal como la devolvería el
  discovery de SIGAIND (`GET /mcp/agro-bi`) y la declaración local de una skill equivalente, ambas
  se representan con **la misma estructura interna, sin campos de adaptación ni ramas
  condicionales por origen**. Se verifica con un fixture estático que imita el discovery; **no se
  hace ninguna llamada de red**.
- [ ] **CA-15 — La herramienta declara su nivel de riesgo; `security_manager` decide (Decisión 6).**
  El contrato transporta un nivel de riesgo **declarado por la herramienta**. Tests: (a) una tool de
  consulta declarada verde y una de escritura/aprobación declarada amarilla o roja se registran
  correctamente con su nivel; (b) el nivel declarado es una **entrada** a la decisión, nunca la
  decisión: `security_manager` sigue siendo el único árbitro y puede endurecerlo; (c) una tool que
  declara "verde" **no se auto-autoriza**; (d) **una tool sin nivel declarado se bloquea**
  (fail-closed), no se permite por omisión.
- [ ] **CA-16 — El registro admite herramientas de origen remoto descubierto en runtime
  (Decisión 6).** Registrar una herramienta no exige que esté declarada en código: el registro
  acepta un alta en tiempo de ejecución con la misma estructura de CA-14 y la misma clasificación
  de CA-15. **No se implementa ningún cliente, transporte ni discovery real** — el test usa una
  fuente ficticia en memoria y solo demuestra que el contrato no lo impide.
- [ ] **CA-17 — La integración no exige volver multi-usuario a O.R.I.O.N. (Decisión 6).** Queda
  documentado y verificado por inspección que el control de acceso de negocio lo resuelve el
  servidor a partir del usuario asociado al token (`skill-mcp-sigaind-v01.md` §3.2-§3.3), de modo
  que el contrato solo necesita poder **portar credenciales por fuente de herramientas**. No se
  introduce ningún modelo de identidad nuevo en el core.

### REQ-007 [B] — Bucle de razonamiento con herramientas

> Estos criterios **no se ejecutan en REQ-006**. Se listan aquí porque comparten la arquitectura y
> porque el corte tiene que quedar trazado. REQ-007 hereda esta SPEC y el documento de arquitectura
> **sin rediseñar**.

- [ ] **CA-18 — El clasificador deja de cortocircuitar (cierra H1).** Un intent conocido y de
  alta confianza **no** retorna la respuesta del handler sin pasar por el agente. Un test verifica
  que el camino de resolución del agente se ejecuta también cuando el intent **no** es `UNKNOWN`.
- [ ] **CA-19 — Los handlers dejan de ser terminales (cierra H2).** Cuando una herramienta
  devuelve un resultado de fracaso (p. ej. Wikipedia sin resultados), el agente **realiza al menos
  un paso adicional** —otra herramienta o una respuesta que explica el fracaso—, en vez de devolver
  el string del handler tal cual.
- [ ] **CA-20 — Existe un bucle de razonamiento, construido desde cero (cierra H7).** Un test con
  el LLM mockeado verifica que: (a) se consulta al proveedor para elegir herramienta; (b) el
  resultado de la herramienta se **reinyecta** en la siguiente decisión; (c) **no** se itera sobre
  `self.tools` devolviendo la primera que no falle; (d) el bucle honra el contrato de resultado de
  CA-09 — una denegación del gate se trata como denegación y no interrumpe el razonamiento
  haciéndose pasar por respuesta.
- [ ] **CA-21 — Terminación acotada.** El bucle tiene tope máximo de iteraciones y criterio de
  parada explícito. Un test con un LLM mockeado que nunca concluye verifica que el bucle termina y
  devuelve un mensaje útil, sin recursión infinita ni consumo ilimitado de tokens.
- [ ] **CA-22 — Agregar una capacidad no reentrena ni degrada el clasificador.** Registrar una
  herramienta nueva **no** requiere modificar `_get_training_data()`, **no** dispara reentrenamiento
  de `LinearSVC` y **no** altera la predicción de los 28 intents existentes. Un test da de alta una
  herramienta ficticia, verifica que es invocable por el agente y comprueba que la línea base de
  CA-13 permanece **idéntica** antes y después del alta.
- [ ] **CA-23 — El modelo obsoleto deja de ser un riesgo silencioso (cierra H6).** El sistema
  detecta que `saved_model.pkl` está desactualizado respecto de su dataset y reentrena o avisa; no
  se sirve en silencio un modelo de seis semanas atrás. Un test verifica que el training data de
  una skill registrada es alcanzable por la predicción, o —si el diseño elimina la dependencia del
  clasificador para las herramientas nuevas (CA-22)— que la degradación queda registrada de forma
  explícita en vez de silenciosa.
- [ ] **CA-24 — `_decompose()` corregido o eliminado (Decisión 2).** `"ayúdame con el proyecto"`
  produce **una** sola tarea, no `["a", "údame con el pro", "ecto"]`. La partición usa límites de
  palabra o desaparece en favor del bucle. Test con casos que contienen la letra "y" dentro de
  palabras.

---

## Casos borde

**[A]**
- **Petición amarilla por voz que el usuario espera que funcione.** Debe denegarse con un mensaje
  que explique *por qué* y sugiera el canal adecuado, no con un error genérico. Es el punto donde
  el usuario percibe la falta de paridad: la respuesta tiene que hacerla comprensible.
- **STT devuelve texto parcial o mal transcrito.** Con `voice` restringido a verde, el peor caso
  es una acción verde equivocada. Es exactamente el motivo de la Decisión 1 y el escenario realista
  de H5.
- **Wake word que entrega texto ya capturado** (`main.py:89`, `wake_result` como string): debe
  emitir `voice`, igual que la captura por micrófono explícita.
- **Herramienta cuyo texto de éxito contiene la palabra "Error"** (p. ej. un log que se está
  leyendo): no debe clasificarse como fallo. Cubierto por CA-09(c).
- **Confirmación amarilla en un canal sin confirmación interactiva.** El canal declara la
  capacidad; el gate decide. **Se deniega**; nunca se auto-confirma ni se cuelga el proceso
  (CA-10 d, e).
- **El usuario nunca responde la confirmación** (cierra Telegram, ignora el diálogo): debe existir
  un desenlace de expiración que resuelva en **denegación**, no una espera indefinida.
- **Confirmación pedida desde un contexto sin stdin** (scheduler de tareas, hilo de fondo, canal
  `API`): hoy colgaría el proceso si llegara a `:240`; con CA-10 debe resolverse sin bloquear.
- **Dos canales con el mismo `user_id`.** El aislamiento por usuario de `gateway.py` no debe
  romperse al unificar el pipeline.
- **Tool remota que declara un nivel más permisivo del que le corresponde.** El nivel declarado es
  entrada, no autorización: `security_manager` puede endurecerlo y una tool sin nivel se bloquea
  (CA-15 c, d).

**[B]**
- **Herramienta denegada a mitad de una cadena multi-paso.** El agente debe distinguir "denegado"
  de "falló" (CA-09) y no reintentar indefinidamente ni tratarlo como éxito.
- **Petición que dispara varias herramientas cuyo orden importa.** El resultado de la primera debe
  alimentar la segunda; hoy `_execute_agent_chain` pasa `previous_result` como texto plano
  concatenado.
- **Skill que declara un intent que el clasificador nunca predice** (H6): con CA-22 la herramienta
  debe seguir siendo invocable por el agente aunque el clasificador la ignore.
- **El LLM no está disponible.** El pipeline debe degradar a un camino determinista sin colgarse ni
  perder el gate.

---

## Riesgos

| Riesgo | Mitigación | Estado |
|--------|-----------|--------|
| Regresión del gate fail-closed de REQ-005 al dar libertad de elección de herramientas. | CA-07: toda herramienta clasificada; los 49 tests de REQ-005 siguen en verde sin modificarse. | Mitigado por criterio |
| **Denegación del gate indistinguible del éxito** (H7). Defecto activo hoy. | CA-09: resultado estructurado, prohibida la comparación por subcadena. | Mitigado por criterio |
| **Agujero de permisos por voz** (H5). Defecto activo hoy. | CA-05/CA-06. Riesgo residual acotado: requiere acceso físico al micrófono, no explotable remotamente, ningún canal externo puede provocarlo. | Aceptado hasta [A] |
| **Cuelgue por `input()` sin stdin interactivo** (H9). Hoy solo lo evita el chequeo de canal previo. | CA-10(e): la confirmación deja de depender del stdin del proceso. | Mitigado por criterio |
| Que CA-10 se interprete como permiso para abrir el amarillo en Telegram. | Decisión 7 y CA-08/CA-10(f): `CHANNEL_ALLOWED_LEVELS` **no se modifica**; abrir la matriz es un paso posterior con `orion-security`. | Mitigado por redacción |
| Contagio de `async` al core al unificar canales, incluida la confirmación por canal asíncrono. | CA-11 como criterio duro, con mención explícita al camino de confirmación. | Mitigado por criterio |
| **Contrato de herramienta que obligue a escribir un traductor MCP**, con un compromiso externo ya asumido. | CA-14/CA-15/CA-16: isomorfismo con el discovery de SIGAIND, nivel declarable y origen remoto admisible. | Mitigado por criterio |
| Que el REQ de MCP arrastre un rediseño multi-usuario innecesario. | CA-17: SIGAIND resuelve permisos por el usuario del token; solo hay que portar el token. | Mitigado por documentación |
| Regresión silenciosa de clasificación **o de ruteo** (H8). | CA-13 captura la línea base **antes** de tocar nada. | Mitigado por criterio |
| Que REQ-007 rediseñe por su cuenta y diverja del pipeline de [A]. | Arquitectura única y compartida, declarada en el encabezado. | Mitigado por proceso |
| Alcance excesivo para un solo REQ. | Partición aprobada: REQ-006 [A] + REQ-007 [B]. | Resuelto |
| Contaminación con REQ-005 sin commitear. | Bloqueo de secuencia vigente: ningún `.py` se toca. | Mitigado por proceso |
| El bucle del agente consume tokens sin control. | CA-21: tope de iteraciones y criterio de parada. | Mitigado por criterio |
| Cambiar el pipeline rompe el aislamiento por usuario del gateway. | Caso borde explícito; `gateway.py` conserva la propiedad del aislamiento. | Mitigado por diseño |

---

## Decisión de alcance — resuelta

**Pregunta que se planteó:** ¿REQ-006 va entero, o se parte en (A) pipeline único con paridad de
canales y (B) bucle de razonamiento con herramientas?

**Respuesta del humano: se parte. Aprobado.** REQ-006 ejecuta los criterios **[A]**; REQ-007 ejecuta
los criterios **[B]**. `orion-architect` produce **una sola arquitectura compartida** que cubre
pipeline, contrato de canal, registro de herramientas y bucle; se parte **solo la ejecución**.

⚠️ **Para quien lea REQ-007:** no rediseñes. El diseño de [B] ya está en el mismo documento de
arquitectura que el de [A]. Divergir de él rompe el punto único de resolución que [A] construye.

Los motivos que sostuvieron la recomendación quedan registrados porque siguen gobernando el orden
de ejecución:

1. **El riesgo de regresión es de naturaleza distinta en cada mitad.** (A) es un refactor de rutas
   sobre código existente, determinista y verificable exactamente: mismo input → mismo pipeline →
   mismo gate. (B) introduce un bucle **no determinista con LLM** cuyo criterio de terminación hay
   que ajustar empíricamente. En un solo commit, una regresión no se puede atribuir: no se sabría
   si vino del re-ruteo o del razonamiento.
2. **(A) toca el gate de seguridad y debe poder auditarse en aislamiento.** H5 y H9 convierten a (A)
   en un cambio de seguridad real, no en un refactor cosmético. Merece pasar por `orion-security` y
   por los 49 tests de REQ-005 **sin el ruido** de un bucle de LLM en el mismo diff.
3. **(A) entrega valor observable por sí sola.** Cierra el agujero de permisos por voz, hace que el
   mismo comando funcione igual por Telegram y consola, vuelve alcanzable `task_manager` desde
   escritorio, y desata la confirmación de la consola —lo que hace al bot de Telegram realmente
   funcional—.
4. **La dependencia es unidireccional.** (B) necesita que exista un punto único donde el canal se
   conoce y el gate se aplica; (A) no necesita nada de (B). Ese orden no genera trabajo tirado,
   siempre que la arquitectura se diseñe una sola vez.

**Reparto de los 2 bugs — aprobado.** `main.py:34` (`can_handle()`) queda en **[A]** (CA-12);
`core/orchestrator.py:87-98` (`_decompose()`) queda en **[B]** (CA-24), porque `_decompose()`
probablemente desaparezca al construir el bucle. Ninguno de los dos se difiere ni se pierde. Los
otros 3 bugs del diagnóstico (`skills/skill_manager.py:32`, `:46`, `ai/llm_provider.py:27`) quedan
**fuera**: nadie los toca en REQ-006 ni en REQ-007.

---

## Preguntas abiertas

**Ninguna.** Las 5 preguntas que esta SPEC planteó fueron respondidas por el humano y están
incorporadas como Decisiones 1–7 y como criterios:

| Pregunta original | Respuesta | Dónde quedó |
|-------------------|-----------|-------------|
| ¿Partición? | Sí, con arquitectura única | Decisión 3 |
| ¿Reparto de los 2 bugs? | Sí: `can_handle` → [A], `_decompose()` → [B] | CA-12, CA-24 |
| ¿H5 dentro del REQ o hotfix adelantado? | Dentro de [A], sin adelanto; riesgo residual registrado | Decisión 4, CA-05/CA-06 |
| ¿H6 dentro o separado? | Dentro | Decisión 6, CA-23 |
| ¿H8 solo corpus o convertir los 4 archivos? | Solo la línea base, ampliada a **ruteo** además de reconocimiento | Decisión 7, CA-13 |

Se agregaron después, sin necesidad de consulta previa porque el humano las trajo cerradas:
MCP deja de estar diferido (Decisión 5, CA-14–CA-17) y H9 entra como criterio nuevo de [A]
(Decisión 7 bis, CA-10).

---

## Asumidos

- **ASUMIDO:** el punto único de resolución es **síncrono** y los canales asíncronos lo invocan
  desde su propio borde (CA-11). Confirmar con `orion-architect`.
- **ASUMIDO:** el mecanismo de confirmación agnóstica de CA-10 también respeta esa frontera: el
  core no se vuelve `async` para poder preguntar por Telegram. Confirmar con `orion-architect` —
  es la decisión de diseño más delicada de [A].
- **ASUMIDO:** la GUI PyQt6 entra al pipeline como canal `desktop`, no como un `ChannelType`
  propio. Confirmar antes de implementar.
- **ASUMIDO:** `ChannelType.API` y `ChannelType.DISCORD` quedan sin cambios de permisos en este REQ.
- **ASUMIDO:** el corpus de línea base de CA-13 se construye a partir de las ~254 frases actuales de
  `_get_training_data()` y de la predicción **actual** del modelo, congelada como línea base — no
  como "clasificación correcta", sino como "clasificación que no debe cambiar sin decisión
  explícita".
- **ASUMIDO:** el contrato de herramienta de CA-14 se valida contra el discovery de
  `.claude/skills/skill-mcp-sigaind-v01.md` **en papel**, comparando formas; no se implementa ni se
  invoca ningún cliente MCP en este REQ.

---

## Trazabilidad hallazgo → criterio

| Hallazgo | Mitad | Criterios que lo cierran |
|----------|-------|--------------------------|
| H1 — clasificador cortocircuita | [B] | CA-18 |
| H2 — handlers terminales | [B] | CA-19 |
| H3 — `task_manager` inalcanzable | [A] | CA-03 |
| H4 — pipelines divergentes | [A] | CA-01, CA-02, CA-03 |
| H5 — canal `voice` no se emite | [A] | CA-04, CA-05, CA-06 |
| H6 — modelo obsoleto / training data muerto | [B] | CA-22, CA-23 |
| H7 — el agente no razona; denegación leída como éxito | [A] + [B] | CA-09 (denegación, en [A]), CA-20, CA-21 |
| H8 — cobertura cero de clasificación y ruteo | [A] | CA-13 |
| H9 — confirmación atada a la consola | [A] | CA-10 |
| Bug `can_handle()` (`main.py:34`) | [A] | CA-12 |
| Bug `_decompose()` (`core/orchestrator.py:87-98`) | [B] | CA-24 |
| Restricción REQ-005 (fail-closed, nivel no delegable) | [A] | CA-07, CA-08 |
| Restricción sin `async` en el core | [A] | CA-11 |
| Preparación para MCP / SIGAIND | [A] | CA-14, CA-15, CA-16, CA-17 |

---

## Material de referencia obligatorio para `orion-architect`

- `workspace/referencias/openclaw/02-gateway-canales-ruteo.md` — contrato de canal. **§7 y §8**
  traen veredictos directos, incluido que `start_bots.py` **ya es** un anfitrión persistente
  multi-canal con supervisión → la unificación es un **refactor**, no una construcción desde cero.
- `workspace/referencias/openclaw/04-skills-y-proveedores.md` — registro de herramientas y
  proveedores.
- `workspace/referencias/openclaw/01-seguridad-y-aislamiento.md` — aislamiento.
- `.claude/skills/skill-mcp-sigaind-v01.md` — **obligatorio para CA-14–CA-17.** El contrato de
  herramienta debe poder describir sus 31 tools sin traductor: discovery `GET /mcp/agro-bi`, invoke
  `POST /mcp/agro-bi/invoke`, parámetros en JSON Schema, autenticación Bearer, `empId` siempre
  derivado del token.
- `.claude/rules/security-levels.md` — matriz verde/amarillo/rojo y la sección "REQ-005 — deny-list
  Rojo aplicada en código", que fija los invariantes que CA-07/CA-08/CA-10 no pueden romper.

---

## Pendiente

**Solo la aprobación humana de esta SPEC.**

Todo lo demás está cerrado: las 5 preguntas abiertas fueron respondidas, las 7 decisiones están
incorporadas, los 24 criterios están redactados y trazados a un hallazgo, y la partición
REQ-006 [A] / REQ-007 [B] está aprobada con arquitectura única.

No se modificó ningún archivo `.py`: el bloqueo de secuencia por REQ-005 sin commitear sigue
vigente y este REQ llega hasta arquitectura.

```
Resumen: unificar la resolución de comandos en un punto único con paridad de capacidad
         entre canales, emitir el canal real (incluida voz), desatar la confirmación de
         la consola y dejar el contrato de herramienta listo para MCP/SIGAIND.
Categoría: CORE | Tipo: REFACTOR + FEATURE_NUEVA
Módulos afectados: main.py, core/orchestrator.py, core/base_agent.py, core/security_manager.py,
         router/dispatcher.py, channels/gateway.py, channels/telegram_bot.py,
         voice/*, intent/*, tests/
Asumidos: 6 — listados arriba, requieren confirmación de orion-architect antes de implementar
Ejecución: REQ-006 = criterios [A] (CA-01…CA-17) | REQ-007 = criterios [B] (CA-18…CA-24)
```

⚠️ El flujo no continúa hasta que apruebes esta SPEC.
Responde: **APROBADO** / **AJUSTAR [qué]** / **RECHAZADO [motivo]**
