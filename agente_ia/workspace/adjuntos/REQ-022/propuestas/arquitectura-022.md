# Arquitectura REQ-022 — Selector de modelo sin efecto real + fallback automático ausente

**Agente:** orion-architect
**Fecha:** 2026-09-06
**Entradas:** `SPEC-022.md` (18 CA, aprobada en bloque por Johan) + `baseline-022.md`
(estado actual confirmado por lectura directa de código, sin discrepancias con la SPEC)
**Estado:** propuesta — pendiente de aprobación humana explícita antes de continuar

---

## 0. Resolución de los 3 puntos que la SPEC dejó abiertos para este agente

### (a) ¿El "cambio preventivo por cooldown" también dispara el aviso de la Decisión 3?

**Decisión: SÍ, con el mismo criterio que un fallo en vivo.**

Justificación:
1. Desde la posición del usuario no hay diferencia entre "el modelo falló este turno" y
   "el sistema ni lo intentó porque está en cooldown por fallos recientes": en ambos casos
   la respuesta que está leyendo no vino del destino que configuró. El motivo de fondo de
   la Decisión 3 ("el usuario debe enterarse siempre que la respuesta no vino del modelo
   que configuró", `REQ-022-context.md`) aplica igual a los dos casos.
2. La propia SPEC ya venía inclinada en este sentido — el "ASUMIDO" que quedó sin
   confirmar puntual dice literalmente "también dispara el aviso... con el mismo criterio
   que un fallo en vivo". La aprobación en bloque de Johan no lo contradijo ni lo tocó
   aparte; confirmarlo tal como estaba escrito es la resolución de menor riesgo y la que
   menos sorprende, no un cambio de rumbo.
3. Si NO se incluyera, quedaría un hueco silencioso: un proveedor en cooldown (p. ej.
   DeepSeek sin crédito) haría que **todas** las respuestas de los próximos minutos vengan
   de otro modelo sin ningún indicio, turno tras turno — exactamente el modo de falla
   silenciosa que este REQ existe para cerrar.

**Explícitamente descartado:** deduplicar o silenciar el aviso en turnos consecutivos
mientras el cooldown sigue activo (avisar "una sola vez"). Ninguna CA lo pide, y agregar
estado de sesión para eso es complejidad nueva sin requisito que la sostenga. Cada
respuesta que salió de un destino distinto al configurado lo dice, siempre — así lo pide
literalmente CA-12 ("cuando la respuesta final... provino de un destino distinto").

### (b) ¿Cómo convive el default OpenRouter→Ollama con una lista `task_providers` ya agotada?

**Decisión: el default es una red de seguridad final que aplica siempre que la clave
global `fallback_provider` esté ausente — sin importar si la tarea que falló tenía su
propia lista en `task_providers`.**

Justificación:
1. Es el comportamiento MECÁNICO que el código ya tiene hoy, confirmado por
   `orion-baseline`: agotada la lista de `destinos` (de una sola entrada o de varias por
   `task_providers`), `generate_response()` cae siempre al mismo punto —
   `_intentar_respaldos(activo, e, ..., fallback_provider)` (línea 308-311) — usando la
   clave `fallback_provider`, que es GLOBAL, no por tarea. No hay que agregar ningún
   `if` nuevo para que esto pase; ya pasa. Tocarlo para que NO pase sería el cambio real,
   y no hay ningún CA que lo pida.
2. `task_providers` y `fallback_provider` son mecanismos ortogonales por diseño ya
   existente: uno rota entre destinos ya elegidos para una tarea (catálogo gratuito),
   el otro es el salvavidas cuando se acabaron las opciones. Que el primero se agote no
   dice nada sobre si el segundo debe existir.
3. Beneficio directo para el propio bug que motiva este REQ: agotar una lista de rotación
   gratuita es justo el escenario donde caer en un error crudo sería peor. Tener la red de
   seguridad ahí también es lo que un usuario esperaría.
4. `_cadena_de_respaldo_por_defecto()` (ver §2) siempre excluye al proveedor que ya está
   activo (`activo != "openrouter"` / `activo != "ollama"`), así que si la tarea agotada
   YA terminó en OpenRouter u Ollama, el default no los vuelve a ofrecer sobre sí mismos.

### (c) Mecanismo para que el manos libres del webview (canal `DESKTOP`, no `VOICE`) reciba la forma corta

**Decisión: se reconoce y acorta el aviso dentro de `ui/tts_engine.py::prepare_for_speech()`
— el único punto del sistema que decide qué se pronuncia — en vez de decidir la forma
corta en el punto de generación según canal.**

Justificación:
1. `prepare_for_speech()` ya es, por comentario explícito del propio código (línea 24,
   "Único lugar del sistema donde se decide QUÉ se pronuncia — CA-27"), el punto de
   convergencia de las dos superficies que hablan: `ui/cli.py::display_output` y
   `ui/webview/bridge.py::_speak_response`. Enganchar ahí cubre AMBAS sin condicionar por
   `resolved_channel`, que es justo el dato que en el manos libres del webview está mal
   (resuelve `DESKTOP`, riesgo P2 heredado de REQ-021).
2. Evita duplicar "cuándo es voz": la única decisión de canal que sigue existiendo vive en
   `core/reasoning_loop.py::run()` (`resolved_channel == ChannelType.VOICE`), y solo se usa
   para decidir la forma **larga o corta que queda escrita en el texto de Desktop/CLI**
   (CA-16/17). `prepare_for_speech()` no vuelve a preguntarse "¿es voz?" — cualquier texto
   que llega ahí, por definición, está a punto de leerse en voz alta, sea cual sea el
   canal que lo produjo. Es una regla distinta y más simple: "esto se va a hablar", no
   "el canal es VOICE".
3. Cubre además un caso que apareció al leer `main.py`/`ui/cli.py`: en modo voz de CLI el
   texto se lee en voz alta con `speak(prepare_for_speech(formal_text))` sin
   `solo_voz=True`, y `main.py` llama `ui.display_output(result, read_aloud=True)` **sin
   condicionar por `choice`** — o sea, hasta una respuesta de canal `DESKTOP` tecleada en la
   consola se lee en voz alta si el modo de arranque fue voz. Decidir la forma corta en el
   punto de generación (por `resolved_channel`) NO cubriría ese caso; engancharlo en
   `prepare_for_speech()` sí, porque ese es exactamente el punto por el que pasa.
4. Mecanismo concreto: `ai/llm_provider.py` es la única fuente de verdad de la redacción
   del aviso (forma larga y forma corta). `prepare_for_speech()` importa desde ahí una
   constante de la forma corta y un regex que reconoce la forma larga tal como la arma
   `con_aviso_de_cambio()`, y sustituye una por otra como primer paso, antes de cualquier
   otra limpieza. Se descartó marcar el aviso con caracteres de control invisibles
   (`\x02...\x03`) para luego recortarlos: hubiera obligado a recordar pelarlos en cada
   otro lugar que renderiza el mismo texto (pantalla del webview, Telegram, Discord) — más
   acoplamiento que la fragilidad, ya mitigada, de reconocer una redacción literal que sale
   de una sola función.

---

## 1. Cobertura de criterios de la SPEC

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-01 | `_build_models_payload()` agrega `fijado_por_tarea` leyendo `destinos_de_tarea("razonamiento")` — `None` si vacío, un dict con `etiqueta` (vía `_destino_legible()`) si no. |
| CA-02 | `composer.js::renderModels()` deshabilita `model-btn` y cambia su texto a "Fijado: …" cuando `payload.fijado_por_tarea` no es `None`; no arma el menú clickeable. |
| CA-03 | `bridge.py::set_model()` hace un chequeo temprano de `destinos_de_tarea("razonamiento")`: si hay algo fijado, retorna sin llamar `config_manager.set_ai_provider_and_model()` — el REQ elige la opción "no modifica" de las dos que la CA permitía, es la más simple y la más difícil de malinterpretar. |
| CA-04 | Mismo chequeo temprano de `set_model()`: si hay algo fijado, retorna antes de emitir `notice_shown`. |
| CA-05 | El chequeo de `set_model()`/`_build_models_payload()` es simétrico: `destinos_de_tarea("razonamiento") == []` dispara el camino de siempre, sin ningún cambio de código en ese ramal — es la rama ya existente, intacta. Test de no-regresión explícito en `tests/test_webview_buttons.py`. |
| CA-06 | `_cadena_de_respaldo_por_defecto(activo)`, nueva función: `[("openrouter", "openrouter/free"), ("ollama", "qwen3:8b")]` (menos el que ya sea `activo`), usada por `_resolver_cadena_de_respaldo()` cuando `fallback_config` es falsy. |
| CA-07 | `_cadena_de_respaldo_por_defecto()` solo agrega `"openrouter"` si `config_manager.get_api_key("openrouter")` no está vacío — si no hay clave, la llamada nunca se intenta (ni se registra como fallo en `provider_health`). |
| CA-08 | `_resolver_cadena_de_respaldo()` usa el default SOLO cuando `fallback_config` es falsy; con cualquier `fallback_provider` explícito, `_cadena_de_respaldo()` (sin tocar) sigue siendo la única fuente — el default nunca se agrega por encima. |
| CA-09 | `_cadena_de_respaldo()` NO cambia de firma ni de tipo de retorno — los 14 tests existentes de `tests/test_provider_fallback.py` seguirán pasando sin editarlos. El camino explícito de `_intentar_respaldos()` para cada proveedor de la cadena sigue resolviendo el modelo con `_MODELO_POR_PROVEEDOR.get(p, "")`, idéntico a hoy. |
| CA-10 | Cadena vacía (ni default aplicable ni config explícita) → mensaje de CA-11, nunca una excepción sin manejar; ya es así estructuralmente (bloque `try/except` intacto) y se mantiene. |
| CA-11 | `_intentar_respaldos()`, rama `if not cadena` (hoy línea 378-380): cambia `return f"Error ({activo}): {error_original}"` por `return SIN_PROVEEDOR` — la constante ya existente, ya usada por `core/resolution.py` para decidir el camino local. |
| CA-12 | `generate_response()` gana un parámetro `aviso: Optional[dict] = None` que llena en los dos puntos donde hoy cambia de destino (swap preventivo y `_intentar_respaldos()` exitoso). `core/reasoning_loop.py::run()` y `ai/claude_brain.py::_resolver_con_tools()` lo pasan y envuelven `final_text`/su valor de retorno con `con_aviso_de_cambio()`. |
| CA-13 | `con_aviso_de_cambio()` es un no-op (devuelve el texto sin tocar) si el dict `aviso` está vacío — que es lo que queda cuando el proveedor activo respondió a la primera. |
| CA-14 | El aviso se concatena al `final_text`/texto de retorno ANTES de que se guarde en `agent_context_manager`/se muestre en pantalla — es contenido real del mensaje, no un `notice_shown` ni una línea de log. |
| CA-15 | `ai/claude_brain.py::_resolver_con_tools()` usa la MISMA función `con_aviso_de_cambio()` que `reasoning_loop.py`, importada de `ai/llm_provider.py` — no hay una segunda implementación por canal, solo un valor distinto del argumento `corto` (que en `_resolver_con_tools()` ni se pasa: usa el default `False`, porque ese camino nunca es `VOICE`). |
| CA-16 | `reasoning_loop.py::run()` llama `con_aviso_de_cambio(final_text, aviso_final, corto=(resolved_channel == ChannelType.VOICE))` — con canal `VOICE`, forma corta. |
| CA-17 | Con cualquier otro canal, `corto=False` → forma larga con proveedor y modelo, vía `texto_aviso_cambio()`. |
| CA-18 | `ui/tts_engine.py::prepare_for_speech()` reconoce y acorta el aviso largo de forma incondicional (regex + constante importados de `ai/llm_provider.py`) como primer paso, antes de cualquier otra limpieza — corre para el manos libres del webview y para `ui/cli.py` en modo voz por igual, sin mirar `resolved_channel`. El texto en pantalla del webview NO se toca (usa `render_markdown(result_text)` sobre el texto crudo, antes de que `_speak_response()` llame `prepare_for_speech()` sobre su propia copia — confirmado en baseline: son dos copias independientes). |

---

## 2. `ai/llm_provider.py` — módulo con más cambios

### 2.1 Cadena de respaldo por defecto (CA-06/07/08/09)

```python
import re   # nuevo import de stdlib — no hay dependencia nueva

def _cadena_de_respaldo_por_defecto(activo: str) -> List[Tuple[str, str]]:
    """CA-06/07/08: OpenRouter (catálogo gratuito) -> Ollama local, cuando no hay
    `fallback_provider` configurado. Nunca ofrece al proveedor que ya está activo.

    CA-07: si no hay `OPENROUTER_API_KEY` (ni en config.json), OpenRouter se omite del
    todo — ni se intenta la llamada ni se registra como fallo en `provider_health`, porque
    no hubo ningún intento real que fallara.
    """
    import config_manager

    cadena: List[Tuple[str, str]] = []
    if activo != "openrouter" and config_manager.get_api_key("openrouter"):
        cadena.append(("openrouter", "openrouter/free"))
    if activo != "ollama":
        cadena.append(("ollama", _MODELO_POR_PROVEEDOR["ollama"]))
    return cadena


def _resolver_cadena_de_respaldo(activo: str, fallback_config) -> List[Tuple[str, str]]:
    """Destinos `(proveedor, modelo)` a los que caer, ya resueltos.

    Con `fallback_provider` configurado (string o lista), se usa tal cual —
    `_cadena_de_respaldo()` no cambia de firma ni de comportamiento (CA-09). Sin
    configuración explícita, se usa el default de CA-06/07/08.
    """
    if fallback_config:
        return [(p, _MODELO_POR_PROVEEDOR.get(p, "")) for p in _cadena_de_respaldo(activo, fallback_config)]
    return _cadena_de_respaldo_por_defecto(activo)
```

`_cadena_de_respaldo()` (línea 336-354 hoy) **no se toca**: mismo cuerpo, misma firma,
mismo tipo de retorno (`List[str]`). Es la pieza que hace que los 14 tests de
`tests/test_provider_fallback.py` sigan pasando sin editarlos — CA-09 verificado por
construcción, no por revisión posterior.

### 2.2 `_intentar_respaldos()` — usa la cadena resuelta, corrige CA-11, llena `aviso`

```python
def _intentar_respaldos(
    activo, error_original, messages, system_prompt, image_path, model_name,
    tools, fallback_config, aviso: Optional[dict] = None,
):
    cadena = provider_health.ordenar_por_disponibilidad(
        _resolver_cadena_de_respaldo(activo, fallback_config)
    )
    if not cadena:
        logger.error(f"Proveedor '{activo}' falló y no hay respaldo configurado: {error_original}")
        return SIN_PROVEEDOR                          # CA-11: ya no expone la excepción cruda

    logger.warning(f"Proveedor '{activo}' falló ({error_original}); probando respaldos: {cadena}")

    errores = [f"{activo}: {error_original}"]
    for respaldo, modelo in cadena:                    # antes: `for respaldo in cadena`, `modelo` se
                                                         # recalculaba adentro — ahora ya viene resuelto
        try:
            soporta_tools = respaldo in _PROVEEDORES_CON_TOOLS
            respuesta = _uncached_call(
                respaldo, messages, system_prompt, image_path, modelo,
                tools=tools if (tools and soporta_tools) else None,
            )
            if isinstance(respuesta, str) and respuesta.startswith("Error:"):
                raise Exception(respuesta)
            logger.info(f"Respaldo '{respaldo}' respondió correctamente")
            provider_health.registrar_exito(respaldo, _modelo_para_cooldown(respaldo, modelo))
            if aviso is not None:                       # CA-12
                aviso["proveedor_desde"] = activo
                aviso["modelo_desde"] = model_name
                aviso["proveedor_hacia"] = respaldo
                aviso["modelo_hacia"] = modelo
            return respuesta
        except Exception as e:
            provider_health.registrar_fallo(respaldo, e, _modelo_para_cooldown(respaldo, modelo))
            logger.warning(f"El respaldo '{respaldo}' también falló: {e}")
            errores.append(f"{respaldo}: {e}")

    logger.error(f"Todos los proveedores fallaron: {errores}")
    return SIN_PROVEEDOR
```

Los 8 tests existentes que llaman `_intentar_respaldos()` directamente (líneas 46-188 de
`tests/test_provider_fallback.py`) siguen pasando sin editar: para cualquier
`fallback_config` truthy, `_resolver_cadena_de_respaldo()` reduce exactamente al mismo
`(respaldo, _MODELO_POR_PROVEEDOR.get(respaldo, model_name))` que el código de hoy
calculaba en el cuerpo del bucle — solo cambió DÓNDE se calcula, no el resultado. El único
test que necesita actualizarse es `test_sin_respaldo_se_devuelve_el_error_del_principal`
(línea 97-104): hoy espera `"deepseek" in resultado and "sin credito" in resultado`, y con
CA-11 el resultado pasa a ser `SIN_PROVEEDOR` — este test documentaba exactamente el bug
que CA-11 corrige, así que su aserción cambia a propósito (ver §6, pruebas sugeridas).

### 2.3 `generate_response()` — parámetro `aviso`, swap preventivo corregido y avisado

```python
def generate_response(messages, system_prompt, image_path=None, tools=None, tarea="general",
                       aviso: Optional[dict] = None):
    """... (docstring existente sin cambios, se agrega:)

    `aviso`: dict opcional que el caller pasa VACÍO (`{}`) y que esta función RELLENA si el
    destino final difirió del configurado — por un swap preventivo de cooldown o por un
    respaldo tras un fallo en vivo (CA-12). Mismo patrón que `estado` en
    `reasoning_loop.py::run()`: por defecto `None`, ningún caller existente cambia de
    comportamiento. Claves cuando hubo cambio: `proveedor_desde`, `modelo_desde`,
    `proveedor_hacia`, `modelo_hacia`. Dict vacío == no hubo cambio; no hay un flag booleano
    aparte para no tener dos formas de decir "no cambió nada" que puedan desincronizarse.
    """
    provider, vision_provider, fallback_provider, model_name = get_provider_config()
    destinos = _destinos_iniciales(tarea, provider, model_name, vision_provider, image_path)

    if len(destinos) == 1:
        activo, modelo_explicito = destinos[0]
        # CA-06 aplicado también acá: la cadena candidata para reordenar por disponibilidad
        # ahora incluye el default (openrouter/ollama) cuando no hay `fallback_provider`
        # explícito, no solo la config explícita — así un proveedor único en cooldown
        # también puede arrancar directo por el default en vez de intentar igual al que se
        # sabe caído.
        candidatos = [(activo, modelo_explicito)] + _resolver_cadena_de_respaldo(activo, fallback_provider)
        preferido, modelo_preferido = provider_health.ordenar_por_disponibilidad(candidatos)[0]
        if preferido != activo:
            logger.info(
                f"'{activo}' en cooldown "
                f"({provider_health.segundos_restantes(activo):.0f}s restantes); "
                f"se empieza por '{preferido}'"
            )
            if aviso is not None:                       # CA-12, punto (a) — swap preventivo SÍ avisa
                aviso["proveedor_desde"] = activo
                aviso["modelo_desde"] = modelo_explicito
                aviso["proveedor_hacia"] = preferido
                aviso["modelo_hacia"] = modelo_preferido
            destinos = [(preferido, modelo_preferido)]
    else:
        ... # rama de varios destinos por tarea — SIN CAMBIOS, sigue sin generar aviso (ver
            # nota de alcance más abajo)

    ultimo = len(destinos) - 1
    for indice, (activo, modelo) in enumerate(destinos):
        ...
        except Exception as e:
            provider_health.registrar_fallo(...)
            if indice < ultimo:
                ...
                continue
            return _intentar_respaldos(
                activo, e, messages, system_prompt, image_path, modelo,
                effective_tools, fallback_provider, aviso=aviso,   # NUEVO: se propaga
            )
        ...
```

**Nota de alcance, explícita para `orion-dev`:** la rama de "varios destinos" (rotación
entre modelos de una lista de `task_providers`) **no** llena `aviso` cuando reordena entre
esos destinos — CA-12 habla de "un destino distinto al **configurado**", y una lista es en
sí misma la configuración; rotar dentro de ella no es "cambiar de lo configurado", es
usarlo como está pensado. Si esa rotación agota la lista y cae a `_intentar_respaldos()`
(línea `return _intentar_respaldos(...)` del bloque `for`), ahí sí se llena `aviso`, porque
eso ya es "salir de lo configurado".

**Corrección de un bug latente que este mismo cambio evitaba introducir:** el código de
hoy compara `if preferido != activo:` mezclando un `str` (`activo`) con lo que
`ordenar_por_disponibilidad()` devolvía (antes, siempre bare strings). Al pasar los
candidatos a tuplas `(proveedor, modelo)` de forma homogénea —tanto el destino original
como cada candidato de `_resolver_cadena_de_respaldo()`— y desempaquetar
`preferido, modelo_preferido = ...[0]`, la comparación vuelve a ser `str == str` en todos
los casos, sin ninguna rama donde una tupla se compare contra un string. Documentado acá
para que `orion-dev` no lo reintroduzca simplificando el desempaquetado.

### 2.4 Redacción del aviso — única fuente de verdad

```python
#: Forma corta del aviso de cambio de modelo (CA-16/CA-18) — sin nombres técnicos.
AVISO_CAMBIO_CORTO = "Cambié de modelo."

#: Plantilla de la forma larga (CA-12/CA-17). Un solo lugar arma el texto Y el regex que lo
#: reconoce (`AVISO_CAMBIO_RE`) — evita que se desincronicen si la redacción cambia.
_PLANTILLA_AVISO_LARGO = "Cambié a {hacia} porque {desde} no respondió."

#: Reconoce la forma larga tal como la arma `con_aviso_de_cambio()`, para que
#: `ui/tts_engine.py::prepare_for_speech()` la acorte sin reimplementar la redacción
#: (CA-18). Ancla a fin de texto porque `con_aviso_de_cambio()` siempre la agrega al final.
AVISO_CAMBIO_RE = re.compile(r"\n\nCambié a .+? porque .+? no respondió\.\s*$")


def _etiqueta_destino(proveedor: str, modelo: str) -> str:
    """Nombre para el aviso — deliberadamente simple, sin importar el catálogo de
    etiquetas "bonitas" de `ui/webview/bridge.py::_MODELOS_CONOCIDOS` (capa de UI; este
    módulo no depende de la UI, y CA-17 solo exige nombres de proveedor y modelo, no
    marketing)."""
    return f"{proveedor} ({modelo})" if modelo else proveedor


def texto_aviso_cambio(aviso: Optional[dict], corto: bool = False) -> str:
    """Return la frase de aviso, o `""` si `aviso` no marca ningún cambio."""
    if not aviso or not aviso.get("proveedor_hacia"):
        return ""
    if corto:
        return AVISO_CAMBIO_CORTO
    return _PLANTILLA_AVISO_LARGO.format(
        hacia=_etiqueta_destino(aviso["proveedor_hacia"], aviso["modelo_hacia"]),
        desde=_etiqueta_destino(aviso["proveedor_desde"], aviso["modelo_desde"]),
    )


def con_aviso_de_cambio(texto: str, aviso: Optional[dict], corto: bool = False) -> str:
    """`texto` con la línea de aviso agregada al final (CA-12/14), o `texto` sin tocar si
    no hubo cambio (CA-13)."""
    frase = texto_aviso_cambio(aviso, corto=corto)
    return f"{texto}\n\n{frase}" if frase else texto
```

`AVISO_CAMBIO_RE` queda anclado a un `\n\n` + la plantilla larga exacta con `.+?` no
codicioso en los dos huecos — coincide siempre y únicamente con lo que
`con_aviso_de_cambio(..., corto=False)` produce. Riesgo de fragilidad (coincidir con
texto real del modelo que por casualidad tenga esa forma) se documenta y mitiga en §7.

---

## 3. `core/reasoning_loop.py::run()` — Desktop/webview/CLI

```python
def run(task, channel, user_id="default", agent_name="reasoning_loop", estado=None) -> str:
    resolved_channel = security_manager.resolve_channel(channel)
    tools = _build_tool_list(resolved_channel)

    history: list[dict] = []
    final_text: Optional[str] = None
    aviso_final: dict = {}                                         # NUEVO
    prior_turns = _load_prior_turns(agent_name, user_id)

    for call_number in range(1, MAX_LLM_CALLS + 1):
        abortar_si_cancelado(...)
        progress_report(...)
        prompt = _build_prompt(task, history, prior_turns)

        aviso_cambio: dict = {}                                    # NUEVO — por vuelta
        with streaming.permitido():
            response = generate_response(
                [{"role": "user", "content": prompt}], _build_system_prompt(), tools=tools,
                tarea="razonamiento",
                aviso=aviso_cambio,                                 # NUEVO
            )

        if not isinstance(response, LLMToolResponse):
            final_text = response
            aviso_final = aviso_cambio                              # NUEVO
            break

        if not response.tool_calls:
            final_text = response.text or f"No obtuve una respuesta útil del modelo{vocative()}."
            aviso_final = aviso_cambio                              # NUEVO
            break

        # ... resto del bloque de tool calls: SIN CAMBIOS (incluida la rama ActionDenied,
        # que a propósito NO pasa por aviso_final — una denegación no es "la respuesta")

    if final_text is None:
        final_text = (...)                                          # SIN CAMBIOS — no hubo
                                                                      # generate_response() que
                                                                      # llenar; aviso_final sigue {}

    if estado is not None and es_respuesta_de_fallo(final_text):
        estado["sin_modelo"] = True

    final_text = con_aviso_de_cambio(                                # NUEVO — CA-12/13/14/16/17
        final_text, aviso_final, corto=(resolved_channel == ChannelType.VOICE),
    )

    agent_context_manager.update_context(agent_name, user_id, {"role": "user", "content": task})
    agent_context_manager.update_context(
        agent_name, user_id, {"role": "assistant", "content": final_text[:200]}
    )
    return final_text
```

`aviso_final` se recrea vacío en cada vuelta del `for` (`aviso_cambio`) y solo se "fija" en
`aviso_final` en los dos puntos donde `final_text` se decide de verdad (líneas 260/266 de
hoy) — así, si el swap ocurrió en una vuelta intermedia que terminó pidiendo una
herramienta (no la que dio la respuesta final), no se avisa por algo que no forma parte de
lo que el usuario lee como respuesta. Es la misma lógica de alcance que ya aplica hoy
`final_text = response`/`break`: solo la vuelta que gana cuenta.

`es_respuesta_de_fallo(final_text)` se evalúa ANTES de `con_aviso_de_cambio()`, sobre el
texto crudo: cuando hubo un swap exitoso `final_text` es una respuesta real (nunca
`SIN_PROVEEDOR`), así que el orden no cambia el resultado de ese chequeo en ningún caso —
se mantiene así por ser el orden más simple de razonar (avisar-de-cambio solo maquilla una
respuesta que ya se sabe válida).

Import nuevo en la cabecera del archivo: `from ai.llm_provider import con_aviso_de_cambio`
(ya importa `generate_response`, `es_respuesta_de_fallo`, `LLMToolResponse` del mismo
módulo — se agrega al mismo import existente, no una línea nueva).

---

## 4. `ai/claude_brain.py::_resolver_con_tools()` — Telegram/Discord

```python
def _resolver_con_tools(history, system_prompt, image_path, channel, user_id):
    from agents.tool_registry import catalogo_para_modelo, execute_tool
    from ai.llm_provider import LLMToolResponse, generate_response, con_aviso_de_cambio  # +import
    from core.security_manager import ActionDenied, security_manager

    canal = security_manager.resolve_channel(channel)
    herramientas = catalogo_para_modelo(canal)

    mensajes = list(history)
    for ronda in range(1, MAX_TOOL_ROUNDS + 1):
        progress_report(...)
        aviso_cambio: dict = {}                                     # NUEVO
        with streaming.permitido():
            respuesta = generate_response(
                messages=mensajes, system_prompt=system_prompt, image_path=image_path or None,
                tools=herramientas or None, tarea="razonamiento",
                aviso=aviso_cambio,                                  # NUEVO
            )

        if not isinstance(respuesta, LLMToolResponse):
            return con_aviso_de_cambio(respuesta, aviso_cambio)      # NUEVO — CA-12/15/17, forma larga (default `corto=False`)
        if not respuesta.tool_calls:
            return con_aviso_de_cambio(respuesta.text or "", aviso_cambio)  # NUEVO

        # ... tool call, ActionDenied, Exception: SIN CAMBIOS (mismo criterio de alcance
        # que reasoning_loop.py — una denegación o un error de tool no es "la respuesta")

    aviso_cambio_final: dict = {}                                    # NUEVO
    ultimo = generate_response(messages=mensajes, system_prompt=system_prompt,
                                aviso=aviso_cambio_final)             # NUEVO
    texto = ultimo if isinstance(ultimo, str) else getattr(ultimo, "text", "") or ""
    return con_aviso_de_cambio(texto, aviso_cambio_final)             # NUEVO
```

`corto` nunca se pasa acá (queda en su default `False`): este camino, confirmado por
baseline, nunca resuelve `ChannelType.VOICE` — es exactamente el motivo por el que CA-15
pide "mismo mecanismo, sin lógica duplicada": la única diferencia entre este punto y
`reasoning_loop.py` es un argumento, no una segunda implementación de
`con_aviso_de_cambio()`/`texto_aviso_cambio()`.

---

## 5. `ui/tts_engine.py::prepare_for_speech()` — forma corta para todo lo que se habla (CA-18)

```python
def prepare_for_speech(text: str, solo_voz: bool = False) -> str:
    if not text:
        return ""

    # 0. CA-18: si `text` trae el aviso largo de cambio de modelo (REQ-022), se acorta acá
    #    ANTES de cualquier otra limpieza — todo lo que llega a esta función está a punto
    #    de leerse en voz alta, sea cual sea el canal que lo produjo (cubre el manos libres
    #    del webview, que resuelve DESKTOP y no VOICE — riesgo P2 heredado de REQ-021—, y
    #    el modo voz de `ui/cli.py`, que lee en voz alta hasta texto de canal DESKTOP).
    #    Fuente única de la redacción y del regex que la reconoce: `ai/llm_provider.py`
    #    — acá NO se decide de nuevo "cuándo es voz", solo se reconoce una frase conocida.
    from ai.llm_provider import AVISO_CAMBIO_CORTO, AVISO_CAMBIO_RE
    text = AVISO_CAMBIO_RE.sub(f"\n\n{AVISO_CAMBIO_CORTO}", text)

    # 1. Marcado: ... (resto de la función, SIN CAMBIOS)
```

El texto en pantalla nunca pasa por acá: `ui/webview/bridge.py::_on_resolve_done()`
renderiza `result_text` crudo con `render_markdown()` ANTES de que `_speak_response()`
llame `prepare_for_speech()` sobre su propia copia del mismo texto (confirmado en
baseline) — son dos copias independientes, así que "pantalla completa, voz corta" no
requiere ninguna rama nueva, ya es la forma en que está separado el código.

---

## 6. `ui/webview/bridge.py` — selector del chat vs. `task_providers` (CA-01..05)

```python
@pyqtSlot(str, str)
def set_model(self, provider: str, model: str) -> None:
    from ai.llm_provider import destinos_de_tarea                   # NUEVO

    if destinos_de_tarea("razonamiento"):                            # NUEVO — CA-03/CA-04
        # Hay un destino fijado por tarea para "razonamiento": cambiar acá no tendría
        # efecto real en la próxima respuesta (`_destinos_iniciales()` lo prioriza por
        # encima de `ai_provider`/`ai_model`). Se ignora sin tocar `config.json` y sin
        # avisar — el frontend ya debería mostrar el botón deshabilitado (CA-02), esto es
        # el gate real del lado servidor para cuando la invocación igual llega (mismo
        # criterio que el resto de `bridge.py`: la UI deshabilitada es cosmética, el gate
        # que importa vive acá, porque los slots son invocables desde cualquier script de
        # la página).
        logger.info("set_model ignorado: 'razonamiento' tiene un destino fijado por tarea")
        return

    if provider not in _MODELOS_CONOCIDOS:
        ...  # resto SIN CAMBIOS
```

```python
def _build_models_payload() -> Dict[str, Any]:
    from ai.llm_provider import destinos_de_tarea                   # NUEVO

    activo_proveedor = config_manager.get_ai_provider()
    activo_modelo = config_manager.get_ai_model()
    proveedores = [...]                                              # SIN CAMBIOS
    etiqueta = _MODELOS_CONOCIDOS.get(activo_proveedor, {}).get("label", activo_proveedor or "?")

    fijados = destinos_de_tarea("razonamiento")                      # NUEVO — CA-01
    fijado_por_tarea = None
    if fijados:
        fijado_por_tarea = {
            "etiqueta": " / ".join(_destino_legible(p, m) for p, m in fijados),
        }

    return {
        "proveedores": proveedores,
        "activo": {...},                                             # SIN CAMBIOS
        "fijado_por_tarea": fijado_por_tarea,                         # NUEVO — None si CA-05
    }
```

`fijados` con más de un destino (lista de rotación en `task_providers`) se muestra
concatenado con " / " — no hay ningún CA que exija un formato particular para ese caso
("Casos borde" de la SPEC solo pide que cuente igual como fijado); se documenta acá para
que `orion-ui`, si se convocara, o `orion-dev` no lo re-decidan sin saber que ya se pensó.

---

## 7. `ui/webview/frontend/js/composer.js` — CA-02/CA-05

```javascript
function alternarMenuDeModelos() {
  if (_modelos && _modelos.fijado_por_tarea) return;   // NUEVO — defensa en profundidad:
                                                          // el botón ya está `disabled`, esto
                                                          // cubre una apertura programática
  if (document.getElementById("model-menu") !== null) { ... }  // SIN CAMBIOS
  ...
}

export function renderModels(payload) {
  _modelos = payload;
  const etiqueta = document.getElementById("model-btn-label");
  const boton = document.getElementById("model-btn");
  const fijado = payload.fijado_por_tarea;                     // NUEVO

  if (fijado) {                                                 // NUEVO — CA-02
    if (etiqueta) etiqueta.textContent = `Fijado: ${fijado.etiqueta}`;
    if (boton) {
      boton.disabled = true;
      boton.title = `Fijado desde Configuración: ${fijado.etiqueta}`;
    }
    if (document.getElementById("model-menu") !== null) cerrarMenuDeModelos();
    return;
  }

  if (boton) boton.disabled = false;                            // NUEVO — CA-05: por si venía
                                                                   // deshabilitado de antes
  if (etiqueta) etiqueta.textContent = payload.activo.resumen || payload.activo.label || "modelo";
  if (boton) {
    boton.title = `Responde ${payload.activo.label}${payload.activo.modelo ? " · " + payload.activo.modelo : ""}`;
  }
  if (document.getElementById("model-menu") !== null) {
    cerrarMenuDeModelos();
    alternarMenuDeModelos();
  }
}
```

`ui/webview/frontend/js/app.js::onModelsLoaded()` no necesita ningún cambio: sigue siendo
un puente directo (`renderModels(JSON.parse(json))`), y `renderModels()` ya maneja el
campo nuevo sin que el llamador tenga que saber de su existencia.

---

## 8. `config_manager.py`

Sin cambios. `fallback_provider` sigue sin estar en `DEFAULT_CONFIG` — el default de este
REQ se aplica en tiempo de lectura (`_resolver_cadena_de_respaldo()`), nunca escribiendo la
clave. Se descarta documentarla ahí con un comentario: `DEFAULT_CONFIG` son valores que SÍ
se escriben en una config nueva (`load_config()`), y escribir `fallback_provider` ahí
convertiría el default implícito de este REQ en una config explícita indistinguible de la
que un usuario haya elegido a mano — exactamente lo que CA-08/CA-09 piden mantener
separado.

---

## 9. Dependencias nuevas

Ninguna. `re` es de la librería estándar (ya usado en `ui/tts_engine.py`; se agrega el
import en `ai/llm_provider.py`, que hoy no lo tiene). `requirements.txt` no cambia.

---

## 10. Diagrama de flujo de datos (aviso de cambio de modelo)

```
generate_response(..., aviso={})
   │
   ├─ swap preventivo (cooldown)? ──sí──► aviso.update(desde=activo, hacia=preferido)
   │
   └─ falla en vivo ──► _intentar_respaldos(..., aviso=aviso)
                             └─ respaldo responde ──► aviso.update(desde=activo, hacia=respaldo)

reasoning_loop.run() / _resolver_con_tools()
   │  (dueños del dict `aviso`, uno por intento de generate_response)
   ▼
con_aviso_de_cambio(texto, aviso, corto=...)
   │
   ├─ aviso vacío ──► texto sin tocar (CA-13)
   └─ aviso lleno ──► texto + "\n\nCambié a X porque Y no respondió."   (o forma corta)
                             │
                             ▼
              texto final: pantalla (Desktop/Telegram/Discord), historial, agent_context
                             │
                             ▼
        ui/tts_engine.py::prepare_for_speech(texto)   ← ÚNICO punto que decide qué se habla
                             │
                    reconoce el patrón largo (regex de ai/llm_provider.py)
                             │
                             ▼
                    lo reemplaza por "Cambié de modelo." si estaba
                             │
                             ▼
                          speak()
```

---

## 11. Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| Ollama no instalado o no corriendo, en el nuevo camino default (CA-06). | **Ya mitigado por código existente, sin cambios necesarios**: `_ask_ollama()` atrapa `requests.exceptions.ConnectionError` (línea 574-575) y devuelve de inmediato `"Error: Ollama no está ejecutándose..."` — no espera el `timeout=180` (ese timeout es para el caso "está corriendo pero el modelo es demasiado pesado", un escenario distinto y ya manejado con su propio mensaje). El nuevo default llama a `_ask_ollama()` por el mismo `_uncached_call()` de siempre — no hay un camino nuevo que lo bypasee. |
| OpenRouter en el default sin `OPENROUTER_API_KEY`. | `_cadena_de_respaldo_por_defecto()` chequea `config_manager.get_api_key("openrouter")` ANTES de agregarlo a la cadena — sin clave, OpenRouter directamente no entra en la lista, así que nunca se intenta la llamada condenada, ni se ensucia `provider_health` con un fallo que no fue tal (CA-07, explícito en Casos Borde de la SPEC). |
| Ambos (OpenRouter y Ollama) fallan o no están disponibles. | Cae a `SIN_PROVEEDOR` (CA-10/CA-11) — mensaje claro y ya reconocido por `core/resolution.py::es_respuesta_de_fallo()` para el camino local ("sube el volumen" sigue funcionando sin modelo). |
| El regex `AVISO_CAMBIO_RE` podría, en teoría, coincidir con una respuesta real del modelo que por casualidad tenga la forma "Cambié a X porque Y no respondió." al final. | Redacción específica y poco probable en una respuesta espontánea; la plantilla y el regex se generan a partir de la MISMA constante (`_PLANTILLA_AVISO_LARGO`), así que no pueden desincronizarse entre sí — el riesgo remanente es una coincidencia de contenido, no de mantenimiento. Mitigado además por un test de auto-consistencia (ver §12: generar un aviso con `texto_aviso_cambio()` y verificar que `AVISO_CAMBIO_RE` lo reconoce). |
| `aviso` mal propagado entre vueltas del bucle de `reasoning_loop.run()` (que el aviso de una vuelta que NO ganó termine avisando sobre una respuesta que no lo necesitaba). | `aviso_cambio` se recrea vacío en cada vuelta del `for`, y `aviso_final` solo se asigna en los dos puntos donde `final_text` se fija de verdad — nunca se acumula entre vueltas. Cubierto por test específico en `tests/test_reasoning_loop.py` (ver §12). |
| Selector del chat (`composer.js`) sin cobertura de test automatizado — no hay infraestructura de tests JS en este repo (confirmado, no existen `*.test.js`). | Fuera del alcance de `.claude/rules/testing.md` (pytest, Python). Riesgo aceptado y documentado: verificación de `renderModels()`/`alternarMenuDeModelos()` queda a revisión manual de `orion-qa`/el humano, igual que el resto de cambios de `composer.js` en REQs previos de este repo. |
| Cambiar el tipo interno de la cadena de respaldo (de `List[str]` a `List[Tuple[str,str]]` en el nuevo `_resolver_cadena_de_respaldo()`) rompe algo que llame a `_intentar_respaldos()`/`_cadena_de_respaldo()` fuera de `ai/llm_provider.py`. | Grep confirma que ambas son funciones privadas (prefijo `_`) usadas solo dentro de este módulo y de `tests/test_provider_fallback.py`. `_cadena_de_respaldo()` en sí no cambia de tipo — solo la nueva `_resolver_cadena_de_respaldo()` lo hace, y es de introducción nueva en este REQ. |

---

## 12. Pruebas sugeridas para `orion-tester`

Todas mockeadas, sin red real, siguiendo `.claude/rules/testing.md`. Se apoyan en
`tests/test_provider_fallback.py`, `tests/test_llm_provider.py`, `tests/test_reasoning_loop.py`
y `tests/test_webview_buttons.py` — extender en vez de crear archivos nuevos donde el REQ
lo permita, salvo que `orion-dev` prefiera aislar los de aviso de cambio en un archivo
propio (`tests/test_aviso_cambio_modelo.py`) si el volumen lo justifica.

**Decisión 1 — selector vs. task_providers (CA-01..05)**
- `_build_models_payload()` con `task_providers.razonamiento` fijado (mock de
  `destinos_de_tarea`) → payload trae `fijado_por_tarea` con la etiqueta esperada.
- `_build_models_payload()` sin nada fijado → `fijado_por_tarea` es `None` (CA-05,
  no-regresión).
- `set_model()` con destino fijado → `config_manager.set_ai_provider_and_model` NO se
  llama, `notice_shown` NO se emite (mock de ambos, `assert_not_called()`).
- `set_model()` sin nada fijado → comportamiento idéntico al de hoy (CA-05, test existente
  no debería necesitar cambios).

**Decisión 2 — fallback por defecto (CA-06..11)**
- `_cadena_de_respaldo_por_defecto("deepseek")` con `OPENROUTER_API_KEY` presente →
  `[("openrouter", "openrouter/free"), ("ollama", "qwen3:8b")]`.
- Ídem sin clave de OpenRouter (mock de `config_manager.get_api_key` → `""`) →
  `[("ollama", "qwen3:8b")]` únicamente (CA-07).
- `_cadena_de_respaldo_por_defecto("openrouter")` → Ollama solo, nunca se ofrece a sí
  mismo.
- `_resolver_cadena_de_respaldo()` con `fallback_config` explícito → idéntico a
  `_cadena_de_respaldo()` de hoy, ignorando el default (CA-08/09, no-regresión).
- `_intentar_respaldos()` con cadena totalmente vacía (sin default aplicable, sin config)
  → `SIN_PROVEEDOR`, nunca el string crudo de la excepción (CA-11 — reemplaza/actualiza
  `test_sin_respaldo_se_devuelve_el_error_del_principal`).
- Fallo de OpenRouter (sin clave) NO llama `provider_health.registrar_fallo("openrouter", ...)`
  — se verifica que la llamada mockeada a `_uncached_call` nunca ocurre con `"openrouter"`.

**Decisión 3 — aviso dentro de la respuesta (CA-12..15)**
- `generate_response()` con el proveedor activo en cooldown (mock de
  `provider_health.ordenar_por_disponibilidad`) y `aviso={}` pasado → `aviso` queda lleno
  con `proveedor_desde`/`proveedor_hacia` correctos (resuelve el punto (a) de arquitectura,
  con un test explícito que documente la decisión).
- `generate_response()` con el proveedor activo respondiendo a la primera → `aviso` queda
  `{}` (CA-13).
- `texto_aviso_cambio({}, corto=False) == ""`; con `aviso` lleno y `corto=False`, el texto
  contiene ambos nombres de proveedor; con `corto=True`, es exactamente
  `AVISO_CAMBIO_CORTO`, sin nombres.
- `con_aviso_de_cambio()` no modifica el texto cuando `aviso` está vacío (CA-13); lo
  concatena con `"\n\n"` cuando no.
- `reasoning_loop.run()`: mock de `generate_response` que llena `aviso` en la primera vuelta
  pero el `final_text` real viene de una vuelta posterior sin swap → el texto final NO
  lleva aviso (verifica el alcance "solo la vuelta que gana cuenta", documentado en §3).
- `reasoning_loop.run()`: swap ocurre en la vuelta que sí produce `final_text` → el texto
  final lo incluye.
- `_resolver_con_tools()`: mismo patrón, usando `con_aviso_de_cambio` con `corto=False` por
  default — el texto de Telegram/Discord también lo incluye (CA-15).
- `agent_context_manager.update_context` recibe el texto CON el aviso ya incluido (CA-14 —
  no alcanza con mockear solo `notice_shown`/logging).

**Decisión 4 — forma corta para voz (CA-16..18)**
- `reasoning_loop.run()` con `channel` que resuelve `ChannelType.VOICE` y hubo swap → el
  aviso en `final_text` es la forma corta.
- Con cualquier otro canal → forma larga.
- `AVISO_CAMBIO_RE` reconoce exactamente lo que genera `texto_aviso_cambio(aviso, corto=False)`
  para varios pares de nombres de proveedor/modelo (test de auto-consistencia, mitigación
  del riesgo de regex frágil de §11).
- `prepare_for_speech()` con un texto que contiene la forma larga → el resultado contiene
  `AVISO_CAMBIO_CORTO` y NO contiene nombres de proveedor/modelo — probado con
  `solo_voz=True` y `solo_voz=False`, para cubrir tanto el manos libres del webview como
  `ui/cli.py` en modo voz (CA-18).
- `prepare_for_speech()` sin ningún aviso en el texto → sale sin cambios respecto al
  comportamiento de hoy (no-regresión de REQ-021).

**Regresión general**
- Suite completa (`python -m pytest tests/ --tb=short -v`) sin nuevos fallos más allá del
  ya documentado en baseline (`test_task_slots.py::test_la_hora_dicha_se_respeta`, no
  relacionado).

---

## 13. Recomendación sobre `orion-security` / `orion-ui`

**Ninguno de los dos es necesario antes de `orion-dev`, a mi criterio — sujeto a que el
humano/orquestador lo confirme:**

- **`orion-ui`**: el único cambio visual es un botón que pasa de "clickeable" a
  "deshabilitado con una etiqueta distinta" — no hay mockup, captura ni layout nuevo que
  traducir; el criterio de accesibilidad relevante (que un `<button disabled>` no reciba
  foco de teclado ni dispare su handler) ya lo da gratis el atributo `disabled` nativo del
  HTML, sin tokens de color ni estados nuevos que diseñar.
- **`orion-security`**: no se introduce ninguna acción destructiva, ni un nuevo patrón de
  manejo de secretos — `get_api_key("openrouter")` ya es el punto único y ya auditado que
  usa el resto del sistema (`_avisos_de_claves()` lo usa igual). No hay logging de claves
  ni de datos sensibles nuevo; el aviso de cambio de modelo solo nombra proveedor/modelo,
  nunca una credencial.

Si el humano prefiere una pasada de `orion-security` de todos modos (por tocar
`ai/llm_provider.py`, superficie sensible por historial), no hay objeción — la propuesta
no depende de saltarlo.

---

**Estado: esperando aprobación humana explícita antes de continuar el flujo hacia
`orion-dev`.**
