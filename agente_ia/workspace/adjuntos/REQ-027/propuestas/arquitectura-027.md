# Arquitectura REQ-027 — Bucle de razonamiento de nivel agente

**Estado:** ⏸️ ESPERANDO APROBACIÓN DE JOHAN
**Categoría:** CORE · **Tipo:** MEJORA · **Fecha:** 2026-09-08
**Entradas:** `REQ-027-context.md`, `spec/SPEC-027.md` (45 CA, aprobada sin ajustes),
`origen/baseline-027.md`

---

## 0. Baseline (resumen — detalle en `origen/baseline-027.md`)

```
Rama      : feature/mcp-correo-flujos   HEAD: d75008a (REQ-026)
git status: solo requerimientos.csv modificado + carpeta REQ-027 sin trackear
            → working tree LIMPIO en todo lo que este REQ toca
pytest    : 1828 passed, 0 failed, 11 warnings, 214.41s  (exit 0)
```

**Cero fallos preexistentes.** Todo test rojo después de este REQ es de este REQ. Es la
referencia de **CA-44**.

---

## 1. La idea en cinco líneas

El bucle deja de mandar un mensaje `user` autocontenido por vuelta y pasa a mantener **una
conversación**: `[user(tarea)] + [assistant(llamadas), user(resultados)]*`. Esa conversación se
escribe en un **formato neutral propio** (`core/tool_history.py`), no en el de ningún proveedor,
y son los adaptadores de `ai/llm_provider.py` los que la traducen a `tool_use`/`tool_result` o a
`tool_calls`/`role="tool"` en el momento de hablar. El presupuesto de vueltas sale del modo del
composer con techo por canal. Cada vuelta ejecuta **todas** las herramientas que el modelo pidió,
en secuencia, cada una por `execute_tool()`. Y cuando se acaba el presupuesto o hay una
denegación, se gasta **una** llamada más sin herramientas para que el modelo redacte con lo que
ya reunió.

---

## 2. Decisiones de diseño

Las cuatro primeras resuelven los `ASUMIDO` que la SPEC dejó abiertos (§Asumidos).

### D-1 — La representación neutral vive dentro de `messages`, en un módulo propio: `core/tool_history.py`

**Confirma el ASUMIDO 1.** La firma de `generate_response()` **no cambia**. El historial viaja
como mensajes normales de la lista `messages` cuyo `content`, en vez de un `str`, es una lista de
bloques neutrales.

Formato (tres tipos de bloque, claves en español — ver D-2):

```python
{"role": "assistant", "content": [
    {"tipo": "texto",   "texto": "voy a mirar dos fuentes"},          # opcional
    {"tipo": "llamada", "id": "tc_1", "nombre": "web_search",
                        "argumentos": {...}},
]}
{"role": "user", "content": [
    {"tipo": "resultado", "id": "tc_1", "nombre": "web_search",
                          "salida": "..."},
    {"tipo": "texto", "texto": "<instrucción de cierre>"},            # solo en el cierre
]}
```

**Por qué un módulo nuevo y no dentro de `reasoning_loop.py`:** el formato lo *escribe*
`core/reasoning_loop.py` y lo *lee* `ai/llm_provider.py`. `reasoning_loop` ya importa
`llm_provider` en el nivel de módulo, así que la dirección inversa es un ciclo de importación. Un
módulo hoja del que dependan los dos (`core/tool_history.py`, que no importa nada del proyecto)
lo evita y además deja el formato con un dueño único en vez de repartido entre dos capas — que es
exactamente el argumento con el que `core/composer_modes.py` existe.

**Por qué neutral y no nativo:** `generate_response()` puede cambiar de proveedor **a mitad de
turno** (cooldown preventivo y cadena de respaldo, REQ-022 — ver `ai/llm_provider.py:265-295` y
`_intentar_respaldos()`). Si el bucle emitiera bloques `tool_use` de Anthropic y el respaldo
fuera DeepSeek, el respaldo recibiría un historial que no entiende y el turno se caería justo
cuando ya venía teniendo un mal día. La traducción ocurre en el adaptador que **efectivamente**
atiende, así que sobrevive al swap sin que el bucle se entere (CA-02, CA-42).

### D-2 — Las claves neutrales son palabras en español, a propósito

`tipo`, `texto`, `llamada`, `nombre`, `argumentos`, `resultado`, `salida`. No es estética: hace
que **CA-02 sea verificable con un grep trivial** sobre `json.dumps(messages)` — ninguna de las
cadenas prohibidas (`tool_use`, `tool_result`, `input_schema`, `tool_calls`, `tool_call_id`,
`"role": "tool"`) puede aparecer por accidente. Con claves en inglés (`tool_name`, `call_id`) el
test sería una lista de excepciones.

> ⚠️ **Aviso para quien implemente el test de CA-02:** el grep de CA-02 va sobre los `messages`
> capturados, **no sobre el archivo fuente**. `core/reasoning_loop.py` contiene y va a seguir
> conteniendo la cadena `tool_calls` porque `LLMToolResponse.tool_calls` es un atributo que hay
> que leer (`response.tool_calls`). Un grep del archivo daría un falso rojo. El grep estático del
> archivo sí puede hacerse contra `tool_result`, `tool_call_id` e `input_schema`, que nunca
> aparecen legítimamente ahí.

### D-3 — Regla única de aplanado: **si la llamada no lleva herramientas, el historial se aplana a texto**

**Confirma el ASUMIDO 2 y lo ubica.** El aplanado vive en `core/tool_history.py::aplanar()` y se
aplica en un único punto: `ai/llm_provider.py::_uncached_call()`, que es el embudo por el que
pasan `generate_response()`, `_cached_call()` **y** `_intentar_respaldos()`.

```python
def _uncached_call(prov_name, messages, system_prompt, image_path, model_name, tools=None):
    if not tools:
        messages = tool_history.aplanar(messages)     # REQ-027/CA-07
    ...
```

Una sola línea cubre tres casos distintos que si no serían tres parches:

1. **`gemini` / `ollama`** nunca reciben `tools` (`_PROVEEDORES_CON_TOOLS` los excluye), así que
   siempre ven el historial aplanado (CA-07), venga por el camino normal o por la cadena de
   respaldo.
2. **La llamada de cierre** (CA-28/29) va con `tools=None` a *cualquier* proveedor. Esto no es un
   detalle de comodidad: **la API de Anthropic rechaza una petición que contiene bloques
   `tool_use`/`tool_result` si la petición no declara `tools`**, y varios modelos servidos por
   OpenRouter hacen lo mismo con `role="tool"`. Sin esta regla, CA-28 y CA-29 estarían
   "implementadas" y fallarían siempre en la app real, cayendo silenciosamente al texto enlatado
   de CA-31 — el peor modo de fallo posible: verde en los tests, muerto en producción.
3. **Cualquier caller interno** de `generate_response()` (compactación, resúmenes) que algún día
   reciba un historial estructurado queda cubierto sin saberlo.

Coste asumido: la respuesta de cierre se redacta sobre el historial en texto y no en nativo.
Es exactamente lo que `ai/claude_brain.py:206-212` ya hace hoy para su propio cierre, y es la
única forma garantizada de funcionar en los 5 adaptadores y en toda la cadena de respaldo.

**Byte-identidad (CA-07/CA-08):** `aplanar()` devuelve `messages` **tal cual, sin copiar**, si no
hay ningún mensaje estructurado. Con eso, todo caller de hoy produce la misma llamada que antes
de REQ-027, sin depender de que la reconstrucción sea perfecta.

### D-4 — La caché nunca ve un historial de herramientas

CA-40 dice que una llamada **con** `tools` no pasa por `_cached_call()`. Se generaliza:

```python
def _debe_cachear(tools, messages) -> bool:
    return not tools and not tool_history.tiene_historial_de_herramientas(messages)
```

Motivo: la llamada de cierre va con `tools=None` y **sí** entraría a la caché hoy. Cachear el
cierre de un turno de investigación es un error de dos filos — devolvería una respuesta vieja
ante un historial idéntico, y expone `_cache_key()` (que hace `json.dumps` de `messages`) a
contenido estructurado que podría no serializar, con la consecuencia perversa de que un
`TypeError` de serialización se registraría como **fallo del proveedor** y lo mandaría a cooldown.
Con esta regla `_cache_key()` no necesita ni una línea de cambio.

### D-5 — El `id` sintético se normaliza en el bucle, no en el adaptador

CA-05 dice "el adaptador genera uno sintético y estable". Se **refina**: lo genera
`core/reasoning_loop.py` al construir el bloque, con la forma `f"tc_{vuelta}_{i}"`, y los
traductores llevan además un respaldo defensivo por si les llega un historial armado a mano.

Motivo: si el `id` llega vacío desde el modelo (pasa con modelos gratuitos de OpenRouter) y cada
adaptador lo inventara por su cuenta, **el adaptador no tendría con qué correlacionar** la llamada
con su resultado — los dos bloques tendrían el id vacío y sería imposible saber cuál va con cuál.
Normalizándolo en el bucle, el mismo id viaja a los dos bloques y **sobrevive a un cambio de
proveedor a mitad de turno**, que es justo lo que D-1 existe para proteger. La verificación
literal de CA-05 ("ni `tool_use_id` ni `tool_call_id` viajan vacíos") se cumple igual.

### D-6 — Cada `tool_use` tiene SIEMPRE su `tool_result`, aunque la secuencia se haya cortado

**Es el punto más importante de todo el diseño y la SPEC no lo menciona.** Anthropic y el SDK
`openai` **rechazan con 400** un turno en el que un `tool_use` / `tool_calls[i]` se queda sin su
`tool_result` / mensaje `role="tool"` correspondiente.

Con CA-25 (una denegación corta la secuencia y las restantes no se ejecutan) más CA-29 (después
hay una llamada de cierre que recibe el historial), se produce exactamente esa situación: el
mensaje `assistant` declara N llamadas y solo hay k resultados.

Solución: `_ejecutar_vuelta()` devuelve **siempre** `len(llamadas) == len(resultados)`. A las que
no llegaron a ejecutarse se les registra un resultado sintético:

```python
NO_EJECUTADA = "No ejecutada: la secuencia se cortó por una acción denegada."
```

No es cortesía con el modelo: es un requisito del protocolo. Sin esto, CA-29 pasaría los tests con
mocks y fallaría siempre contra un proveedor real.

**Corolario del mismo problema:** `execute_tool()` puede devolver `""` o `None`, y Anthropic
rechaza un bloque de contenido vacío. `bloque_resultado()` normaliza: `str(salida) if salida else
"(sin salida)"`.

### D-7 — En el historial nativo, los `argumentos` van sin las claves que inyecta el caller

`run()` inyecta `channel`, `user_id` y `texto_original` en los params de cada llamada (CA-22, y
es un invariante de seguridad de REQ-005). El bloque `llamada` guarda el dict **ejecutado
completo** — no hay negociación posible ahí, porque CA-07 exige que el aplanado imprima
`f"{i}. {tool}({params}) -> {result}"` con exactamente el mismo `repr` de dict que hoy.

Pero lo que se **manda al proveedor** en `tool_use.input` / `function.arguments` pasa por
`tool_history.argumentos_para_el_modelo(bloque)`, que quita las tres claves inyectadas. Motivo:
`texto_original` es el mensaje entero del usuario, y con presupuesto 40 y 3 herramientas por
vuelta se repetiría **120 veces** en el prompt. La constante `CLAVES_INYECTADAS` vive en
`core/tool_history.py` —el módulo que sabe qué mete el bucle—, no en `llm_provider`, para no
meterle a la capa de proveedores conocimiento del modelo de seguridad.

Efecto secundario deseable: el modelo ve de vuelta lo que él pidió, no lo que el caller le pisó.

### D-8 — `_build_prompt()` se parte en dos y sobrevive como envoltorio

CA-10 exige que los `test_ca22_*` sigan pasando **sin cambio de expectativa**, y esos tests llaman
`reasoning_loop._build_prompt()` directo. Se conserva con firma y salida idénticas, reimplementado
sobre dos piezas:

- `_encabezado_de_tarea(task, prior_turns, con_historial)` — la parte de arriba del prompt. Es lo
  que `run()` usa ahora para el primer mensaje.
- `tool_history.lineas_de_historial(lines, pares)` — el bloque "Acciones ya ejecutadas…", movido
  verbatim desde `_append_history_lines()`.

El parámetro `con_historial` es lo que hace que **el aplanado salga byte a byte igual al de hoy**
sin una sola operación de string surgery: hoy `_build_prompt()` escribe `"Mensaje actual del
usuario:"` cuando no hay historial y `"Tarea original del usuario:"` cuando lo hay, y `run()`
ahora sabe cuál corresponde porque sabe si `historial` está vacío. Verificación:

| Caso | Hoy (`_build_prompt`) | Nuevo (encabezado + `aplanar`) |
|---|---|---|
| sin turnos, sin historial | `"{task}"` | `"{task}"` ✔ |
| sin turnos, con historial | `"Tarea original del usuario: {task}\n\nAcciones…\n1. …\n\nContinúa…"` | idéntico ✔ |
| con turnos, sin historial | `"Turnos anteriores…\n\nMensaje actual del usuario: {task}"` | idéntico ✔ |
| con turnos, con historial | `"Turnos anteriores…\n\nTarea original del usuario: {task}\n\nAcciones…"` | idéntico ✔ |

`aplanar()` **descarta los bloques `texto` de rol `assistant`** (el razonamiento intermedio del
modelo): hoy tampoco viajaban, e incluirlos rompería CA-07. Sí renderiza los `texto` de rol
`user`, que son solo la instrucción de cierre.

`_build_prompt()` queda sin llamadores de producción. Se conserva porque CA-10 lo exige; su
limpieza es candidata a un REQ posterior, no a este.

### D-9 — `presupuesto` es un campo obligatorio de `ModoComposer`, sin default

**Confirma el ASUMIDO 3** (entero, en el catálogo, no en `config.json`) y agrega una decisión: sin
valor por defecto. Un modo nuevo que se olvide de declararlo tiene que explotar con `TypeError` al
importar, no heredar 8 en silencio — el presupuesto es la mitad del sentido de un modo. El default
(8) es de `core/reasoning_loop.py`, que es quien sabe qué pasa "sin modo".

### D-10 — El system prompt se calcula UNA vez por turno, no una por vuelta

Hoy `_build_system_prompt(modo_def)` se llama dentro del `for`. Con 5 vueltas era irrelevante; con
40 son 40 lecturas de rutinas y comandos aprendidos desde disco, y —peor— **40 prefijos distintos**
porque el bloque de fecha/hora cambia al minuto, lo que anula el cacheo de prefijo de los
proveedores que lo soportan justo en el turno más caro. Se saca del bucle. Que el reloj avance a
mitad de turno no le importa a nadie.

### D-11 — `ai/claude_brain.py` recibe `MAX_TOOL_ROUNDS = 3 → 5` y nada más

Decisión de Johan (P-3). No conoce modos, no los recibe, no importa `composer_modes`, sigue
re-serializando resultados como texto en su propio bucle (**confirma el ASUMIDO 4**). Es un cambio
de un dígito.

---

## 3. Cobertura de criterios de la SPEC (trazabilidad CA → dónde se implementa)

### A. Protocolo nativo

| CA | Cómo lo satisface esta propuesta | Dónde |
|---|---|---|
| **CA-01** | `run()` arma `[user(encabezado)] + historial` en cada vuelta; el historial es un par `assistant(llamadas)` / `user(resultados)` con el mismo `id` | `core/reasoning_loop.py::_mensajes_del_turno()` |
| **CA-02** | Bloques con claves en español (D-2); ninguna clave nativa se construye fuera de `ai/llm_provider.py` | `core/tool_history.py` |
| **CA-03** | Traductor a bloques `tool_use` / `tool_result` | `ai/llm_provider.py::_mensajes_para_anthropic()` |
| **CA-04** | Un solo traductor a protocolo del SDK `openai`, usado por los 3 adaptadores | `ai/llm_provider.py::_mensajes_para_openai()` |
| **CA-05** | `id` sintético `tc_{vuelta}_{i}` normalizado en el bucle (D-5) + respaldo en los traductores | `_ejecutar_vuelta()` + traductores |
| **CA-06** | Los adaptadores arman la lista de mensajes **antes** de la bifurcación de streaming; `_llamada_en_streaming()` recibe la misma lista | `_ask_openai`, `_ask_deepseek` |
| **CA-07** | `aplanar()` aplicado en `_uncached_call()` cuando `not tools` (D-3); byte-identidad garantizada por D-8 | `core/tool_history.py::aplanar()` |
| **CA-08** | `aplanar()` es no-op sin bloques estructurados; los traductores reproducen el camino plano actual línea por línea, incluida la diferencia de DeepSeek (string) vs OpenAI/OpenRouter (lista de bloques) | `ai/llm_provider.py` |
| **CA-09** | Ambos traductores adjuntan la imagen al **último mensaje `user` de contenido de texto** (`_indice_de_ultimo_user_de_texto()`), nunca al de resultados | `ai/llm_provider.py` |
| **CA-10** | `_build_prompt()` conserva firma y salida (D-8) | `core/reasoning_loop.py` |

### B. Presupuesto

| CA | Cómo lo satisface | Dónde |
|---|---|---|
| **CA-11** | `MAX_LLM_CALLS = 8` (mismo símbolo de hoy, para que `test_ca07_*` lo siga leyendo) | `core/reasoning_loop.py:29` |
| **CA-12** | `ModoComposer.presupuesto`: 40 / 25 / 12 / 10 | `core/composer_modes.py` |
| **CA-13** | `_presupuesto_de_llamadas(modo_def, canal)` alimenta el `range()` del bucle | `core/reasoning_loop.py` |
| **CA-14** | `get_mode()` ya es fail-safe (devuelve `None` ante id vacío/desconocido) → `_presupuesto_de_llamadas` cae en `MAX_LLM_CALLS`. **Sin cambios en `get_mode()`** | `core/composer_modes.py:104` |
| **CA-15** | `if canal is not ChannelType.DESKTOP: return min(TECHO_CANAL_NO_ESCRITORIO, presupuesto)`. Escrito como "todo lo que no sea DESKTOP" → `API`/`EMAIL`/`UNKNOWN` heredan 5 por construcción | `core/reasoning_loop.py` |
| **CA-16** | `MAX_TOOL_ROUNDS = 5`; sin `modo`, sin import de `composer_modes` | `ai/claude_brain.py:118` |
| **CA-17** | La firma de `run()` no se toca. El presupuesto se deriva de `modo` y `channel`, que ya son parámetros | `core/reasoning_loop.py:241` |
| **CA-18** | El `break` por respuesta final está antes de cualquier ejecución; el presupuesto es solo el tope del `range()` | `run()` |
| **CA-19** | `_reordenar_priorizando()` y la resolución de `tarea` no cambian | `run()`, `_build_tool_list()` |

### C. Todas las tool calls de la vuelta

| CA | Cómo lo satisface | Dónde |
|---|---|---|
| **CA-20** | `for i, call in enumerate(response.tool_calls, 1)` — se acabó `tool_calls[0]` | `_ejecutar_vuelta()` |
| **CA-21** | Una llamada a `execute_tool()` por herramienta, dentro del `for`. No hay ninguna forma de agrupar | `_ejecutar_vuelta()` |
| **CA-22** | Las tres inyecciones (`channel`, `user_id`, `texto_original`) están **dentro** del `for`, después de `dict(call.arguments)` y pisando lo que haya | `_ejecutar_vuelta()` |
| **CA-23** | Un solo `mensaje_de_resultados(resultados)` por vuelta, con los N bloques | `run()` |
| **CA-24** | El `for` del presupuesto envuelve la llamada al modelo; `_ejecutar_vuelta()` es un bucle interno que no lo consume | `run()` |
| **CA-25** | En cuanto `motivo is not None`, las restantes se saltan (con resultado sintético, D-6) sin llamar a `execute_tool` | `_ejecutar_vuelta()` |
| **CA-26** | `except Exception` registra `f"Error ejecutando '{call.name}': {e}"` como resultado y **no** corta | `_ejecutar_vuelta()` |
| **CA-27** | `abortar_si_cancelado()` antes de **cada** `execute_tool()`, además del de inicio de vuelta | `_ejecutar_vuelta()` |

### D. Llamada de cierre

| CA | Cómo lo satisface | Dónde |
|---|---|---|
| **CA-28** | Al salir del `for` con `final_text is None`, una sola llamada con `tools=None` y el historial completo | `_llamada_de_cierre()` |
| **CA-29** | La denegación hace `break` con `denegacion = motivo`; la misma llamada de cierre atiende ambos casos, cambiando solo la instrucción | `run()` + `_llamada_de_cierre()` |
| **CA-30** | Está **fuera** del `for`, sin bucle propio, y se ejecuta como máximo una vez porque solo hay un camino que llega ahí | `run()` |
| **CA-31** | `_llamada_de_cierre()` devuelve `Optional[str]`: `None` si el proveedor falló (`es_respuesta_de_fallo`), si el texto vino vacío, o si la respuesta fue un `LLMToolResponse` sin `text`. Con `None`, el texto es el enlatado de hoy, literal | `run()` |
| **CA-32** | `estado["denied"] = True` se escribe **antes** del cierre, en el mismo `break`. `core/resolution.py` no se toca | `run()` |

### E. `max_tokens`

| CA | Cómo lo satisface | Dónde |
|---|---|---|
| **CA-33** | `MAX_TOKENS_SALIDA = 4096`, usada en los 5 puntos (`:595`, `:756`, `:834`, `:867`, `:974`) | `ai/llm_provider.py` |
| **CA-34** | Constante de módulo. Sin parámetro nuevo en `generate_response()`, sin clave en `config.json`, sin tabla por tarea | `ai/llm_provider.py` |
| **CA-35** | Prueba manual (§8) | — |

### F. No regresión

| CA | Cómo lo satisface | Dónde |
|---|---|---|
| **CA-36** | `.invoke(` no aparece; toda ejecución sigue siendo `execute_tool()` | `_ejecutar_vuelta()` |
| **CA-37** | El gate por canal está dentro de `execute_tool()`, intacto | `agents/tool_registry.py` (sin cambios) |
| **CA-38** | La rama `not isinstance(response, LLMToolResponse) → final_text` se conserva textual | `run()` |
| **CA-39** | Dos puntos de corte: inicio de vuelta (existente) + antes de cada herramienta (CA-27) + antes del cierre | `run()`, `_ejecutar_vuelta()` |
| **CA-40** | `_debe_cachear()` (D-4) es más estricto que hoy, nunca menos | `ai/llm_provider.py` |
| **CA-41** | Las dos `update_context()` siguen fuera del bucle, al final de `run()` | `run()` |
| **CA-42** | `ultimo_aviso` guarda el último aviso no vacío del turno; el cierre usa el suyo y, si vino vacío, hereda ese | `run()` |
| **CA-43** | `tests/modelo_falso.py` y `core/resolution.py` no aparecen en `git diff --stat` (consecuencia de CA-17) | — |
| **CA-44** | Baseline: **1828 passed / 0 failed** | `origen/baseline-027.md` |
| **CA-45** | Prueba manual (§8) | — |

---

## 4. Módulos a modificar

| Módulo | Qué cambia |
|---|---|
| **`core/tool_history.py`** ⭐ NUEVO | Dueño del formato neutral: constructores, predicados, aplanado y el renderizado de líneas que antes vivía en `_append_history_lines()`. No importa nada del proyecto (módulo hoja) |
| `core/reasoning_loop.py` | `MAX_LLM_CALLS` 5 → 8; `_presupuesto_de_llamadas()`; `_encabezado_de_tarea()`; `_build_prompt()` reimplementado como envoltorio; `_ejecutar_vuelta()` nueva; `run()` reestructurado (historial neutral, todas las tool calls, llamada de cierre); system prompt hoisted (D-10) |
| `ai/llm_provider.py` | `MAX_TOKENS_SALIDA = 4096` en 5 puntos; `_mensajes_para_anthropic()` y `_mensajes_para_openai()` nuevos; `_ask_anthropic`/`_ask_openai`/`_ask_openrouter`/`_ask_deepseek` pasan a delegar en ellos; `_uncached_call()` aplana si `not tools`; `_debe_cachear()` en `generate_response()` |
| `core/composer_modes.py` | `ModoComposer` gana `presupuesto: int` (obligatorio); los 4 modos lo declaran |
| `ai/claude_brain.py` | `MAX_TOOL_ROUNDS = 5`. Una línea |
| `tests/test_reasoning_loop.py` | Cobertura nueva de B/C/D; 2 tests cambian de expectativa (§7) |
| `tests/test_llm_provider.py` | Cobertura nueva de A/E; los que fijen `max_tokens=1500` se actualizan |
| `tests/test_composer_modes.py` | CA-12 |
| `tests/test_claude_brain.py` | CA-16 |
| **`tests/test_tool_history.py`** ⭐ NUEVO | El formato neutral y el aplanado, aislados |

**No se tocan** (y es CA-43 / §Módulos que este REQ NO debe tocar): `core/resolution.py`,
`ui/webview/bridge.py`, `tests/modelo_falso.py`, `agents/tool_registry.py`,
`core/security_manager.py`, `core/cancelacion.py`.

---

## 5. Nuevas clases y funciones — firmas exactas

### 5.1 `core/tool_history.py` (nuevo)

```python
"""core/tool_history.py — REQ-027.

Formato NEUTRAL del historial de herramientas de un turno. Lo escribe
`core/reasoning_loop.py` y lo traducen los adaptadores de `ai/llm_provider.py`.
Módulo hoja a propósito: no importa nada del proyecto, así que los dos lados pueden
depender de él sin ciclo.
"""

TIPO_TEXTO     = "texto"
TIPO_LLAMADA   = "llamada"
TIPO_RESULTADO = "resultado"

#: Lo que `reasoning_loop.run()` inyecta en los params de toda herramienta (invariante de
#: seguridad REQ-005). Se guarda en el bloque —el aplanado de CA-07 lo necesita— pero NO se
#: reenvía al modelo: `texto_original` es el mensaje entero del usuario y con presupuesto 40
#: se repetiría más de cien veces en el prompt.
CLAVES_INYECTADAS: tuple[str, ...] = ("channel", "user_id", "texto_original")

SIN_SALIDA = "(sin salida)"

def bloque_texto(texto: str) -> dict: ...
def bloque_llamada(id_llamada: str, nombre: str, argumentos: dict) -> dict: ...
def bloque_resultado(id_llamada: str, nombre: str, salida) -> dict:
    """Normaliza `salida` a un str no vacío: un bloque de contenido vacío lo rechaza
    la API de Anthropic, y `execute_tool()` puede devolver "" o None."""

def mensaje_de_llamadas(texto: Optional[str], llamadas: list[dict]) -> dict:
    """Return el mensaje `assistant` de una vuelta: el texto de razonamiento (si lo hubo)
    seguido de un bloque `llamada` por herramienta pedida."""

def mensaje_de_resultados(resultados: list[dict]) -> dict:
    """Return el mensaje `user` con los resultados de esa misma vuelta."""

def con_texto_agregado(mensaje: dict, texto: str) -> dict:
    """Return una COPIA de `mensaje` con un bloque de texto al final. Se usa para colgar
    la instrucción de cierre del último mensaje de resultados: Anthropic exige alternancia
    estricta de roles, así que no puede ir como un `user` aparte."""

def es_estructurado(mensaje: dict) -> bool: ...
def tiene_historial_de_herramientas(messages) -> bool: ...

def argumentos_para_el_modelo(bloque: dict) -> dict:
    """Return los `argumentos` de un bloque `llamada` sin `CLAVES_INYECTADAS` (D-7)."""

def pares_de(messages: list[dict]) -> list[dict]:
    """Return `[{"tool","params","result"}]` — la MISMA forma que consumía
    `_build_prompt()` antes de REQ-027. Correlaciona por `id`; una llamada sin resultado
    (no debería existir, ver D-6) se rinde como resultado vacío."""

def lineas_de_historial(lines: list[str], pares: list[dict]) -> None:
    """Añade a `lines` el detalle de las tools ejecutadas y la instrucción de cierre.
    Movido verbatim desde `reasoning_loop._append_history_lines()` — es la única copia,
    para que el texto no pueda derivar entre el camino nativo y el aplanado."""

def aplanar(messages: list[dict]) -> list[dict]:
    """Return `messages` con todo `content` como `str` (CA-07).

    Sin bloques estructurados devuelve `messages` TAL CUAL (misma lista, sin copiar):
    es lo que garantiza que un caller de hoy produzca la misma llamada byte a byte (CA-08).
    Con historial, funde los pares llamada/resultado en el último mensaje `user` de texto
    anterior a ellos —uno solo, para no dejar dos `user` seguidos, que Gemini rechaza—
    usando `lineas_de_historial()`. Los bloques de texto de rol `assistant` (el
    razonamiento intermedio del modelo) se descartan: no viajaban antes de REQ-027 e
    incluirlos rompería la byte-identidad de CA-07.
    """
```

### 5.2 `core/composer_modes.py`

```python
@dataclass(frozen=True)
class ModoComposer:
    id: str
    label: str
    tool_names: Tuple[str, ...]
    presupuesto: int          # REQ-027/CA-12 — llamadas al modelo, no herramientas
    tarea: Optional[str]
    prompt_hint: str
```

| Modo | `presupuesto` |
|---|---|
| `codigo` | **40** |
| `investigacion` | **25** |
| `flujos` | **12** |
| `tareas` | **10** |

Sin default (D-9). `listar_modos()` y `get_mode()` no cambian.

### 5.3 `core/reasoning_loop.py`

```python
MAX_LLM_CALLS = 8                      # CA-11 — sin modo, escritorio
TECHO_CANAL_NO_ESCRITORIO = 5          # CA-15 — el valor de hoy: cero regresión

_INSTRUCCION_CIERRE_PRESUPUESTO = (
    "Se agotaron los intentos disponibles. Responde ahora al usuario con la mejor "
    "respuesta posible a partir de lo que ya averiguaste, sin usar más herramientas. "
    "Si quedó algo sin resolver, dilo con claridad."
)
_INSTRUCCION_CIERRE_DENEGACION = (
    "La acción fue denegada y la secuencia se detuvo. Informa al usuario de que no "
    "puedes ejecutarla y por qué, con lo que ya averiguaste. No la reintentes ni "
    "propongas un rodeo para conseguir lo mismo."
)
_NO_EJECUTADA = "No ejecutada: la secuencia se cortó por una acción denegada."


def _presupuesto_de_llamadas(modo_def: Optional[ModoComposer], canal: ChannelType) -> int:
    """Return cuántas llamadas al modelo puede gastar este turno (CA-13/14/15).

    `presupuesto = min(techo_del_canal, presupuesto_del_modo_o_default)`. Escrito como
    "todo lo que no sea DESKTOP tiene techo" y no como una lista de canales remotos: así
    un canal en el que nadie pensó (`API`, `EMAIL`, `UNKNOWN`) hereda el comportamiento de
    hoy y nunca el 40. Fail-closed por construcción, no por mantenimiento.
    """


def _encabezado_de_tarea(task: str, prior_turns: Optional[list[dict]],
                         con_historial: bool) -> str:
    """La parte del prompt anterior al historial de herramientas (REQ-021/CA-22).

    `con_historial` decide entre "Mensaje actual del usuario:" y "Tarea original del
    usuario:" — es la misma distinción que hacía `_build_prompt()` y es lo que permite que
    el aplanado de CA-07 salga byte a byte igual al de hoy sin retocar strings.
    """


def _build_prompt(task, history, prior_turns=None) -> str:
    """Envoltorio de compatibilidad: firma y salida idénticas a las de antes de REQ-027.
    Ya no lo usa `run()` (el historial viaja nativo); existe porque CA-10 exige que los
    `test_ca22_*` sigan pasando sin cambio de expectativa."""


def _mensajes_del_turno(task: str, prior_turns: list[dict],
                        historial: list[dict]) -> list[dict]:
    """Return lo que se le manda a `generate_response()` en esta vuelta: el encabezado
    como único mensaje plano, seguido del historial neutral (CA-01)."""


def _ejecutar_vuelta(tool_calls: list, numero_de_vuelta: int, canal: ChannelType,
                     user_id: str, task: str) -> tuple[list[dict], list[dict], Optional[str]]:
    """Ejecuta EN SECUENCIA todas las tool calls de una vuelta (CA-20 a CA-27).

    Return `(llamadas, resultados, motivo_de_denegacion)`.

    `llamadas` y `resultados` tienen SIEMPRE la misma longitud y los mismos ids, incluso
    cuando la secuencia se cortó: las que no llegaron a ejecutarse llevan un resultado
    sintético. No es cortesía con el modelo — Anthropic y el SDK `openai` rechazan con 400
    un turno donde un `tool_use` se queda sin su `tool_result` (D-6).

    Nunca ejecuta en paralelo: una confirmación humana concurrente con otra ejecución es
    exactamente lo que el gate de REQ-005 no debe permitir.
    """


def _llamada_de_cierre(task: str, prior_turns: list[dict], historial: list[dict],
                       instruccion: str, modo_def: Optional[ModoComposer],
                       system_prompt: str, tarea: str, aviso: dict) -> Optional[str]:
    """Una última llamada al modelo SIN herramientas para que redacte con lo que reunió.

    Return el texto, o `None` si no sirve —proveedor caído (`es_respuesta_de_fallo`),
    texto vacío, o una respuesta que igual trajo tool calls—, en cuyo caso el caller usa
    el mensaje enlatado de siempre (CA-31).

    Va con `tools=None` a propósito y no por ahorro: sin herramientas, la garantía de "no
    reintenta la acción denegada" es estructural y no depende de que el modelo obedezca
    una frase del prompt (CA-29). Está FUERA del presupuesto y es como máximo una por
    turno (CA-30).
    """
```

`run()` — firma **sin cambios** (CA-17):

```python
def run(task: str, channel, user_id: str = "default", agent_name: str = "reasoning_loop",
        estado: Optional[dict] = None, modo: Optional[str] = None) -> str:
```

Esqueleto del cuerpo:

```python
modo_def = get_mode(modo)
resolved_channel = security_manager.resolve_channel(channel)
tools = _build_tool_list(resolved_channel, modo_def)
presupuesto = _presupuesto_de_llamadas(modo_def, resolved_channel)
system_prompt = _build_system_prompt(modo_def)          # D-10: una vez por turno
tarea = modo_def.tarea if modo_def and modo_def.tarea else "razonamiento"

prior_turns = _load_prior_turns(agent_name, user_id)
historial: list[dict] = []          # mensajes NEUTRALES, pares assistant/user
final_text: Optional[str] = None
aviso_final: dict = {}
ultimo_aviso: dict = {}             # CA-42
denegacion: Optional[str] = None

for call_number in range(1, presupuesto + 1):
    abortar_si_cancelado(f"reasoning_loop, vuelta {call_number}")
    progress_report("Pensando" if call_number == 1 else f"Pensando ({call_number})")

    aviso_cambio: dict = {}
    with streaming.permitido():
        response = generate_response(
            _mensajes_del_turno(task, prior_turns, historial), system_prompt,
            tools=tools, tarea=tarea, aviso=aviso_cambio,
        )
    if aviso_cambio:
        ultimo_aviso = aviso_cambio

    if not isinstance(response, LLMToolResponse):      # CA-38
        final_text, aviso_final = response, aviso_cambio
        break
    if not response.tool_calls:                        # CA-18
        final_text = response.text or f"No obtuve una respuesta útil del modelo{vocative()}."
        aviso_final = aviso_cambio
        break

    llamadas, resultados, denegacion = _ejecutar_vuelta(
        response.tool_calls, call_number, resolved_channel, user_id, task,
    )
    historial.append(tool_history.mensaje_de_llamadas(response.text, llamadas))
    historial.append(tool_history.mensaje_de_resultados(resultados))   # CA-23

    if denegacion is not None:
        if estado is not None:
            estado["denied"] = True                    # CA-32, ANTES del cierre
        break

if final_text is None:                                  # CA-28 / CA-29
    aviso_cierre: dict = {}
    cierre = _llamada_de_cierre(
        task, prior_turns, historial,
        _INSTRUCCION_CIERRE_DENEGACION if denegacion is not None
        else _INSTRUCCION_CIERRE_PRESUPUESTO,
        modo_def, system_prompt, tarea, aviso_cierre,
    )
    if cierre:
        final_text = cierre
        aviso_final = aviso_cierre or ultimo_aviso      # CA-42
    elif denegacion is not None:                        # CA-31, texto literal de hoy
        final_text = f"⛔ No puedo ejecutar esa acción{vocative()}: {denegacion}."
    else:
        final_text = (f"No pude completar la tarea en el número de intentos "
                      f"disponibles{vocative()}. ¿Quiere que lo intente de otra forma?")

# ... desde acá, IDÉNTICO a hoy: es_respuesta_de_fallo, con_aviso_de_cambio,
#     las dos update_context (CA-41) y el return.
```

### 5.4 `ai/llm_provider.py`

```python
#: REQ-027/CA-33 — tope de tokens de salida, único para los 5 adaptadores. Es un TECHO, no
#: un objetivo: subirlo no encarece una respuesta corta. 4096 y no 8192 porque varios
#: modelos gratuitos de OpenRouter tienen un tope de salida menor y rechazan la petición
#: con error duro — sería una regresión justo en los modelos que se usan por ser gratis.
MAX_TOKENS_SALIDA = 4096


def _mensajes_para_anthropic(messages: list[dict], image_path: Optional[str]) -> list[dict]:
    """Traduce la lista neutral al formato de Anthropic (CA-03).

    - mensaje plano  -> `{"role", "content":[{"type":"text","text":...}]}`  (lo de hoy, igual)
    - `llamada`      -> `{"type":"tool_use","id","name","input"}` en un `assistant`
    - `resultado`    -> `{"type":"tool_result","tool_use_id","content"}` en un `user`
    - la imagen se inserta en la posición 0 del último `user` de TEXTO (CA-09), nunca de
      uno que transporta resultados
    """


def _mensajes_para_openai(messages: list[dict], system_prompt: str,
                          image_path: Optional[str], *, imagen_como_bloque: bool,
                          aviso_sin_vision: str = "") -> list[dict]:
    """Traduce la lista neutral al protocolo del SDK `openai` (CA-04). Una sola función
    para `openai`, `deepseek` y `openrouter`: los tres hablan el mismo protocolo.

    - `llamada`   -> `assistant` con `tool_calls=[{"id","type":"function",
                     "function":{"name","arguments": json.dumps(...)}}]`
    - `resultado` -> un `{"role":"tool","tool_call_id","content"}` por resultado
    - `imagen_como_bloque=True`  (openai/openrouter): último `user` con `content` como lista
      de bloques y la imagen como `image_url` AL FINAL — exactamente lo de hoy.
    - `imagen_como_bloque=False` (deepseek): último `user` con `content` como string plano y
      `aviso_sin_vision` concatenado si hay imagen — exactamente lo de hoy.

    Esa asimetría entre los tres adaptadores es fea pero se conserva a propósito: CA-08
    exige que con el formato viejo la llamada al proveedor salga byte a byte igual.
    """


def _debe_cachear(tools, messages) -> bool:
    """CA-40, generalizado (D-4): la caché no ve ni una llamada con herramientas ni un
    historial de herramientas — la llamada de cierre va sin `tools` y cachear el cierre de
    un turno de investigación sería devolver mañana la respuesta de hoy."""
    return not tools and not tool_history.tiene_historial_de_herramientas(messages)
```

Cambios de una línea en los adaptadores:

| Adaptador | Antes | Después |
|---|---|---|
| `_ask_anthropic` | bucle que envuelve todo como `{"type":"text"}` | `anthropic_msgs = _mensajes_para_anthropic(messages, image_path)` |
| `_ask_openai` | armado manual de `openai_msgs` | `openai_msgs = _mensajes_para_openai(messages, system_prompt, image_path, imagen_como_bloque=True)` |
| `_ask_openrouter` | ídem | ídem |
| `_ask_deepseek` | armado manual con string en el último | `_mensajes_para_openai(..., imagen_como_bloque=False, aviso_sin_vision=_AVISO_DEEPSEEK_SIN_VISION)` |
| `_uncached_call` | — | `if not tools: messages = tool_history.aplanar(messages)` |
| `generate_response` | `if effective_tools: ... else: _cached_call(...)` | `if _debe_cachear(effective_tools, messages): _cached_call(...) else: _uncached_call(...)` |

Los 5 `max_tokens=1500` → `max_tokens=MAX_TOKENS_SALIDA`.

---

## 6. Flujo de datos

### 6.1 Turno normal (escritorio, modo Investigación, presupuesto 25)

```
Bridge.send_message(texto, modo="investigacion")
  → core/resolution.py::_try_claude()  [sin cambios]
      → reasoning_loop.run(task, "desktop", user_id, estado={}, modo="investigacion")

          presupuesto = _presupuesto_de_llamadas(modo_investigacion, DESKTOP) = 25
          system_prompt = _build_system_prompt(modo_def)          # una vez (D-10)
          historial = []

          ── vuelta 1 ─────────────────────────────────────────────────────
          messages = [ {user: "buscá X y comparalo con Y"} ]
          generate_response(messages, tools=44 tools, tarea="modo_investigacion")
              └ ai/llm_provider.py
                  _debe_cachear(tools, messages) = False  → _uncached_call(tools=...)
                  → _ask_anthropic → _mensajes_para_anthropic(messages, None)
                                      = [{"role":"user","content":[{"type":"text",...}]}]
          ← LLMToolResponse(text="voy a mirar dos fuentes",
                            tool_calls=[web_search(tc_a), web_search(tc_b)])

          _ejecutar_vuelta([tc_a, tc_b], 1, DESKTOP, user_id, task):
              i=1 → abortar_si_cancelado  → params+inyección → execute_tool(...)  [gate]
              i=2 → abortar_si_cancelado  → params+inyección → execute_tool(...)  [gate]
          historial += [ assistant[texto, llamada(tc_1_1), llamada(tc_1_2)],
                         user[resultado(tc_1_1), resultado(tc_1_2)] ]

          ── vuelta 2 ─────────────────────────────────────────────────────
          messages = [ {user: "Tarea original del usuario: ..."} ] + historial   ← CA-01
          generate_response(...)
              └ _ask_anthropic → _mensajes_para_anthropic:
                  [ user(text),
                    assistant([text, tool_use tc_1_1, tool_use tc_1_2]),
                    user([tool_result tc_1_1, tool_result tc_1_2]) ]              ← CA-03
          ← LLMToolResponse(text="según las dos fuentes...", tool_calls=[])
          → final_text, break                                                     ← CA-18

          update_context ×2  (CA-41)  →  return final_text
```

### 6.2 Cambio de proveedor a mitad de turno (REQ-022)

En la vuelta 3 Anthropic devuelve 429. `generate_response()` cae a DeepSeek por la cadena de
respaldo. **El `historial` no cambia**: sigue siendo neutral. `_ask_deepseek` lo traduce a
`assistant`+`tool_calls` / `role="tool"` con los mismos ids. El turno continúa. Ese es el motivo
entero de D-1, y es lo que verifica CA-42.

### 6.3 Denegación en la 2ª de 3 herramientas (CA-25 / CA-29 / CA-31 / CA-32)

```
_ejecutar_vuelta([a, b, c], n, ...):
    a → execute_tool → "ok"
    b → execute_tool → ActionDenied("no se puede desde voz")
          motivo = "no se puede desde voz"; resultado = "Acción denegada: ..."
    c → NO se ejecuta            ← CA-25
          resultado = "No ejecutada: la secuencia se cortó..."   ← D-6, obligatorio

  → historial += [ assistant[3 llamadas], user[3 resultados] ]     3 == 3, siempre
  → estado["denied"] = True                                        ← CA-32
  → break

_llamada_de_cierre(..., _INSTRUCCION_CIERRE_DENEGACION):
    mensajes = _mensajes_del_turno(task, prior_turns,
                                   historial con la instrucción colgada del último `user`)
    generate_response(mensajes, system_prompt, tools=None, ...)     ← CA-29
        └ _uncached_call(tools=None) → tool_history.aplanar(messages)   ← D-3
             el modelo recibe el historial COMO TEXTO, que es la única forma que Anthropic
             acepta sin `tools` declaradas
    ← "No pude apagar el equipo porque desde voz no está permitido. Sí conseguí ..."

  → generate_response.call_count == 2, no hay una 3ª                ← CA-29/CA-30
  Si el cierre falla o vuelve vacío → "⛔ No puedo ejecutar esa acción...: {motivo}."  ← CA-31
```

### 6.4 Proveedor sin tool-calling (CA-07 / CA-38)

`gemini` y `ollama` nunca reciben `tools`, así que `_uncached_call()` siempre les aplana el
historial y ven **un solo mensaje `user`** con el texto de siempre. Si `generate_response()`
devuelve un `str` en vez de un `LLMToolResponse`, `run()` lo acepta como respuesta final, igual
que hoy.

---

## 7. Impacto en tests existentes

Tres cambios de expectativa, todos previstos por la SPEC (§Impacto en tests existentes):

1. **`test_ca07_agota_5_llamadas_sin_una_sexta`** — el conteo pasa a `MAX_LLM_CALLS + 1` (la
   llamada de cierre, CA-28/CA-30). El segundo assert (`"no pude completar la tarea"`) **sigue
   pasando sin tocarlo**: el mock devuelve siempre un `LLMToolResponse` con `text=None`, y
   `_llamada_de_cierre()` lo descarta por no traer texto → cae al enlatado (CA-31). Conviene
   renombrarlo, su nombre ya miente hoy.
2. **`test_ca08_action_denied_corta_de_inmediato`** — `call_count` de `1` a `2`, más el assert de
   `tools=None` en la segunda. **Es el único test de un camino de seguridad que este REQ relaja**,
   está aprobado explícitamente por Johan (P-1) y lo que CA-08 protegía —"no reintenta, no prueba
   otra tool"— queda garantizado por construcción: sin herramientas no hay nada que reintentar.
3. Cualquier test que fije `max_tokens=1500` en `tests/test_llm_provider.py`.

### ⚠️ Corrección de los conteos escritos en la SPEC

La SPEC redactó los conteos de la sección B **antes** de que Johan aprobara P-2, y quedaron
inconsistentes con CA-30 ("la llamada de cierre está fuera del presupuesto"). Un test escrito con
el número literal de la SPEC fallaría. La lectura correcta —y la que manda, porque es la que CA-30
fija— es que el presupuesto cuenta **las vueltas con herramientas**, y el cierre va aparte:

| CA | Número literal en la SPEC | Valor correcto con CA-28/CA-30 |
|---|---|---|
| CA-13 | `call_count == 25` / `== 40` | **26** / **41** (o: llamadas con `tools` no nulo == 25 / 40) |
| CA-14 | `8 llamadas` | **9** |
| CA-15 | `call_count == 5` | **6** |
| CA-24 | `call_count == MAX_LLM_CALLS` | **`MAX_LLM_CALLS + 1`** |

Recomendación para los tests: aseverar sobre **las llamadas que llevaron `tools`**
(`len([c for c in mock.call_args_list if c.kwargs.get("tools")]) == 25`) en vez del total. Expresa
la intención del CA —"como máximo el presupuesto de ese modo"— y no se rompe si mañana cambia el
mecanismo de cierre. No es un cambio de diseño: es la aritmética que la propia SPEC implica.

---

## 8. Pruebas sugeridas — una por criterio

### `tests/test_tool_history.py` (nuevo)

| Test | CA |
|---|---|
| `test_bloques_no_llevan_ninguna_clave_nativa_de_proveedor` — `json.dumps` de un historial completo no contiene `tool_use`, `tool_result`, `tool_calls`, `tool_call_id`, `input_schema` | CA-02 |
| `test_aplanar_sin_historial_devuelve_los_mismos_mensajes` (identidad, `is`) | CA-08 |
| `test_aplanar_produce_el_texto_identico_a_build_prompt` — parametrizado sobre las 4 combinaciones de `prior_turns` × `historial` de D-8 | CA-07 |
| `test_aplanar_deja_todo_content_como_str` | CA-07 |
| `test_aplanar_no_deja_dos_mensajes_user_seguidos` | CA-07 |
| `test_bloque_resultado_normaliza_salida_vacia` (`""`/`None` → `"(sin salida)"`) | D-6 |
| `test_argumentos_para_el_modelo_quita_las_claves_inyectadas` | D-7 |

### `tests/test_llm_provider.py`

| Test | CA |
|---|---|
| `test_ca03_anthropic_traduce_a_tool_use_y_tool_result` — cliente mockeado, assert sobre `messages=` de `client.messages.create` | CA-03 |
| `test_ca04_familia_openai_traduce_a_tool_calls_y_role_tool` — parametrizado sobre `_ask_openai`/`_ask_deepseek`/`_ask_openrouter` | CA-04 |
| `test_ca05_id_vacio_no_viaja_vacio_al_proveedor` — `ToolCallRequest(id="")` en los 4 adaptadores | CA-05 |
| `test_ca06_streaming_y_no_streaming_mandan_los_mismos_mensajes` | CA-06 |
| `test_ca07_gemini_y_ollama_reciben_todo_content_como_str` | CA-07 |
| `test_ca08_formato_viejo_produce_la_misma_llamada_que_antes` — los 5 adaptadores, con y sin imagen | CA-08 |
| `test_ca09_la_imagen_no_se_pega_al_mensaje_de_resultados` | CA-09 |
| `test_ca33_una_sola_constante_de_max_tokens_con_5_usos` — grep de `max_tokens=1500` ausente + `MAX_TOKENS_SALIDA == 4096` | CA-33 |
| `test_ca34_generate_response_no_gana_parametros` — `inspect.signature` + grep de `max_tokens` en `config.json` | CA-34 |
| `test_ca40_ni_tools_ni_historial_pasan_por_la_cache` | CA-40 |

### `tests/test_composer_modes.py`

| Test | CA |
|---|---|
| `test_ca12_cada_modo_declara_su_presupuesto` — 40/25/12/10 sobre `listar_modos()` | CA-12 |
| `test_ca12_el_presupuesto_no_vive_en_ninguna_tabla_paralela` — grep de los 4 números en `core/reasoning_loop.py` y `ui/webview/bridge.py` | CA-12 |

### `tests/test_reasoning_loop.py`

| Test | CA |
|---|---|
| `test_ca01_la_vuelta_siguiente_lleva_llamadas_y_resultados_correlacionados` | CA-01 |
| `test_ca02_el_historial_que_emite_el_bucle_es_neutral` | CA-02 |
| `test_ca11_el_presupuesto_por_defecto_es_8` | CA-11 |
| `test_ca13_con_modo_el_presupuesto_es_el_del_modo` (investigación 25, código 40) | CA-13 |
| `test_ca14_modo_vacio_o_desconocido_cae_en_el_default` | CA-14 |
| `test_ca15_todo_canal_que_no_sea_escritorio_tiene_techo_5` — parametrizado `voice`/`telegram`/`email`/`unknown` | CA-15 |
| `test_ca17_la_firma_de_run_no_cambio` — `inspect.signature` literal | CA-17 |
| `test_ca18_una_vuelta_es_una_llamada_aunque_el_presupuesto_sea_40` | CA-18 |
| `test_ca20_se_ejecutan_las_n_tool_calls_en_orden` | CA-20 |
| `test_ca21_cada_tool_pasa_por_execute_tool_por_separado` | CA-21 |
| `test_ca22_el_canal_y_el_usuario_se_inyectan_en_las_n` — una tool con `user_id="atacante"` | CA-22 |
| `test_ca23_los_n_resultados_vuelven_en_una_sola_vuelta` | CA-23 |
| `test_ca24_una_vuelta_con_n_tools_consume_una_unidad` | CA-24 |
| `test_ca25_una_denegacion_corta_la_secuencia_de_la_vuelta` | CA-25 |
| `test_ca25_las_no_ejecutadas_igual_tienen_resultado` — `len(llamadas) == len(resultados)` (D-6) | CA-25/D-6 |
| `test_ca26_una_excepcion_no_corta_la_secuencia` | CA-26 |
| `test_ca27_la_cancelacion_se_evalua_entre_herramientas` | CA-27 |
| `test_ca28_agotado_el_presupuesto_hay_una_llamada_de_cierre_sin_tools` | CA-28 |
| `test_ca29_tras_una_denegacion_hay_cierre_y_no_hay_tercera` | CA-29 |
| `test_ca30_el_cierre_no_encadena` | CA-30 |
| `test_ca31_si_el_cierre_falla_vuelve_el_texto_enlatado` — dos casos (`SIN_PROVEEDOR` y `""`) × dos situaciones | CA-31 |
| `test_ca32_denied_queda_en_true_haya_o_no_cierre` | CA-32 |
| `test_ca42_el_aviso_de_cambio_sobrevive_al_cierre` | CA-42 |
| `test_ca36/37/38/39/41` — **existentes, sin cambios** | — |

### Prueba manual (CA-35 / CA-45) — la hace Johan

1. Un turno real por cada proveedor configurado en `config.json`, sin error de API con
   `max_tokens=4096` (CA-35).
2. (a) "hola" responde en una vuelta; (b) con modo Investigación, una pregunta multi-fuente
   encadena más de 4 herramientas y cita lo leído; (c) el botón de detener corta a mitad de una
   vuelta con varias herramientas; (d) una acción amarilla dentro de una vuelta de varias
   herramientas sigue mostrando su modal (CA-45).

---

## 9. Dependencias nuevas

**Ninguna.** No se agrega ni una línea a `requirements.txt`. Todo el REQ se hace con lo que ya
está: `anthropic`, `openai` y `json` de la biblioteca estándar.

---

## 10. Riesgos y mitigación

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Un `tool_use` sin su `tool_result` → 400 del proveedor.** Es lo que produce naturalmente CA-25 (denegación corta la secuencia) seguida de CA-29 (cierre con el historial) | Alto. Fallaría **siempre** en la app real y **nunca** en los tests con mocks | D-6: `_ejecutar_vuelta()` garantiza `len(llamadas) == len(resultados)` con resultados sintéticos. Test explícito de la igualdad |
| **Anthropic rechaza bloques `tool_use`/`tool_result` si la petición no declara `tools`** — justo lo que hace la llamada de cierre | Alto. CA-28/29 quedarían muertas y caerían en silencio al texto enlatado de CA-31 | D-3: `_uncached_call()` aplana cuando `not tools`. Es además la forma que ya usa `claude_brain` para su cierre |
| **Ventana de contexto con presupuesto 40** y resultados largos de `web_read` | Medio. El historial puede exceder la ventana | Fuera de alcance resolverlo (no hay compactación en este REQ). El fallo llega como error de proveedor y lo maneja la cadena de respaldo de REQ-022; nunca crashea el turno. D-7 baja el consumo quitando `texto_original` de cada eco. **Candidato claro a REQ posterior: compactación del historial de herramientas** |
| **Byte-identidad del aplanado (CA-07/CA-08)** se rompe por un espacio | Medio. Regresión silenciosa en `gemini`/`ollama` | Una sola copia del renderizado (`lineas_de_historial()`), `aplanar()` no-op sin historial, y `_encabezado_de_tarea(con_historial=...)` en vez de retoque de strings (D-8). Test parametrizado sobre las 4 combinaciones |
| **El grep de CA-02 sobre el archivo fuente da falso rojo** por `response.tool_calls` | Bajo, pero quema una tarde | Avisado en D-2: el grep va sobre `json.dumps(messages)` capturado |
| **Los conteos literales de CA-13/14/15/24 contradicen CA-30** | Medio. Tests escritos al pie de la letra fallan | §7: corrección explícita y recomendación de aseverar sobre las llamadas *con* `tools` |
| **Sin tope de tool calls por vuelta** (Johan lo descartó): un modelo confundido puede pedir 50 | Medio | Lo acotan el gate por herramienta (cada amarilla pide su modal), `abortar_si_cancelado()` entre herramientas (CA-27) y el presupuesto de vueltas. Es la decisión registrada, no se reabre |
| **Dos mensajes `user` seguidos** en el aplanado (Gemini los rechaza) | Medio | `aplanar()` funde el historial **dentro** del último `user` de texto, no como mensaje aparte |
| **Anthropic exige alternancia estricta de roles**, y la instrucción de cierre es un `user` extra | Medio | `con_texto_agregado()`: la instrucción va como bloque dentro del mensaje de resultados, nunca como mensaje nuevo |
| **`dict(call.arguments)` explota si el modelo devuelve una lista** en vez de un objeto | Bajo (preexistente, hoy también crashea el turno) | Se envuelve en `try/except (TypeError, ValueError) → {}` dentro de `_ejecutar_vuelta()`. Es código que este REQ reescribe igual |
| **`execute_tool()` devuelve `""`/`None`** y Anthropic rechaza contenido vacío | Bajo | `bloque_resultado()` normaliza a `"(sin salida)"` |
| **40 vueltas × `_build_system_prompt()`** = 40 lecturas de disco y 40 prefijos distintos | Bajo (coste, no corrección) | D-10: se calcula una vez por turno |
| **Voz + `max_tokens` 4096**: una respuesta larga por TTS son minutos incortables | Medio | Condición **preexistente** (con 1500 ya son minutos). Johan la dejó fuera de alcance (P-4) como REQ chico posterior: techo de salida por canal, ~500 en `VOICE` |
| **Telegram sigue razonando peor que el escritorio** | Bajo | Deuda reconocida y aceptada (P-3). Candidato REQ-028 |

---

## 11. Orden de implementación sugerido

Cada paso deja la suite en verde por sí solo, así que se puede parar en cualquiera.

1. **`core/tool_history.py` + `tests/test_tool_history.py`.** Módulo hoja, sin dependencias, sin
   integración. Es donde vive la byte-identidad, así que conviene tenerla clavada antes de tocar
   nada más.
2. **`ai/llm_provider.py`: `MAX_TOKENS_SALIDA`** (CA-33/34). Cambio mecánico, aislado.
3. **`ai/llm_provider.py`: traductores + aplanado en `_uncached_call()` + `_debe_cachear()`**
   (CA-03 a CA-09, CA-40). Con el paso 1 hecho, la byte-identidad de CA-08 es lo primero que hay
   que verificar acá.
4. **`core/composer_modes.py`: `presupuesto`** (CA-12) y **`ai/claude_brain.py`:
   `MAX_TOOL_ROUNDS = 5`** (CA-16). Dos cambios de un dígito.
5. **`core/reasoning_loop.py`: `_encabezado_de_tarea`, `_build_prompt` envoltorio,
   `_presupuesto_de_llamadas`, `MAX_LLM_CALLS = 8`** (CA-10, CA-11, CA-13 a CA-15, CA-17).
6. **`core/reasoning_loop.py`: `_ejecutar_vuelta()` + historial neutral en `run()`**
   (CA-01/02, CA-20 a CA-27).
7. **`core/reasoning_loop.py`: `_llamada_de_cierre()`** (CA-28 a CA-32) y actualización de
   `test_ca07_*` / `test_ca08_*`.
8. **Suite completa contra el baseline** (CA-44: 1828 → 1828 + los nuevos, 0 fallos) y prueba
   manual de Johan (CA-35, CA-45).

---

## 12. PENDIENTE DE JOHAN

**Ningún bloqueante.** Los 4 `ASUMIDO` de la SPEC quedaron resueltos en D-1, D-3, D-8, D-9 y D-11,
y los 5 puntos P-1 a P-5 ya los respondiste. Dos avisos, por no asumir nada en silencio:

**A-1. La llamada de cierre le llega al modelo con el historial en TEXTO, no en nativo (D-3).**
No es una preferencia: la API de Anthropic rechaza una petición con bloques `tool_use` /
`tool_result` si esa misma petición no declara `tools`, y `tools=None` es justamente lo que hace
que la garantía de CA-29 ("no reintenta la acción denegada") sea estructural. Es el mismo
mecanismo que `ai/claude_brain.py` ya usa para su cierre desde siempre. Si algún día se quiere el
cierre en nativo, la única alternativa sería mandar el catálogo con `tool_choice="none"`, que
devuelve la garantía a una frase del prompt — no lo recomiendo.

**A-2. Los conteos de CA-13, CA-14, CA-15 y CA-24 están escritos con un número que contradice
CA-30** (§7). Los corrijo por aritmética, no por criterio: la SPEC redactó esa sección antes de
que aprobaras P-2 y no reajustó los números. Si preferís que el presupuesto incluya la llamada de
cierre (o sea, 25 vueltas totales de las cuales una es el cierre), decilo y cambio
`_presupuesto_de_llamadas()` en una línea — pero entonces se cae CA-30 tal como está escrita.

---

## 13. Estado

- Propuesta lista para revisión. **No se movió el tracker**: sigue en `SPEC_APROBADO`, la
  aprobación de arquitectura la gestiona la conversación principal.
- Sin código escrito. Sin `git commit`, sin `git push`, sin rama nueva (P-5 sigue abierto y no
  afecta a este diseño).
