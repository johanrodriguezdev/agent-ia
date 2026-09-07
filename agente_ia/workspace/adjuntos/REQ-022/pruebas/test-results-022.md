# Resultados de prueba REQ-022 — Selector de modelo del chat + fallback automático

**Fecha:** 2026-09-07
**Agente:** orion-tester

## Compilación
- `python -m py_compile ai/claude_brain.py ai/llm_provider.py core/reasoning_loop.py ui/tts_engine.py ui/webview/bridge.py` → **OK**, sin errores.
- `node -c ui/webview/frontend/js/composer.js` / `app.js` → **OK**, sin errores de sintaxis.

## Tests existentes
- Suite dirigida (`test_provider_fallback.py`, `test_provider_health.py`, `test_webview_buttons.py`, `test_llm_provider.py`, `test_reasoning_loop.py`): **99/99 OK**.
- Suite completa (`pytest tests/`): **1764/1764 OK**, sin fallos nuevos (incluye `test_task_slots.py::test_la_hora_dicha_se_respeta`, antes inestable, pasó también esta vez).

## Metodología
Cada uno de los 18 CA se verificó explícitamente, no solo por lectura de código. Para los CA
con test automatizado dedicado en el repo, se identificó y ejecutó ese test. Para los CA
**sin** test dedicado (ver hallazgo abajo), se ejecutó el flujo real mockeando únicamente el
límite de red al proveedor — mismo criterio que ya usa la suite existente
(`.claude/rules/testing.md`) — con dos scripts temporales en el scratchpad de esta sesión:
- `verify_req022_ca12_18.py` (CA-12 a CA-18 + swap preventivo por cooldown)
- `test_verify_ca03_ca04.py` (CA-03/CA-04, invocación directa del slot `set_model()`, vía
  el mismo patrón de fixture `Bridge` headless que `tests/test_webview_bridge.py`)

Ambos corrieron **8/8** y **3/3** verificaciones en PASS respectivamente. No se comitean —
son evidencia de esta sesión de pruebas, no reemplazo de tests del repo (ver hallazgo).

## Criterios de la SPEC

| Criterio | Resultado | Nota |
|----------|-----------|------|
| CA-01 | PASS | `_build_models_payload()` (`bridge.py:1927-1935`) incluye `fijado_por_tarea.etiqueta` vía `_destino_legible()` cuando `destinos_de_tarea("razonamiento")` no está vacío. Cubierto por `tests/test_webview_buttons.py::test_el_selector_de_modelo_se_deshabilita_si_esta_fijado_por_tarea` (GUI real, payload verificado end-to-end). |
| CA-02 | PASS | `composer.js::renderModels()` deja `boton.disabled = true` y el título "Fijado desde Configuración: …"; `alternarMenuDeModelos()` corta también la apertura programática. Mismo test que CA-01 confirma `model-menu === null` tras click. |
| CA-03 | PASS | `bridge.py::set_model()` (línea 1067) retorna antes de `config_manager.set_ai_provider_and_model()` cuando hay destino fijado. **No tenía test dedicado que invocara el slot directamente** (ver hallazgo) — verificado ahora con `test_verify_ca03_ca04.py::test_ca03_...` invocando `bridge.set_model()` directo: `escrituras == []`. |
| CA-04 | PASS | Mismo `return` temprano evita también `notice_shown.emit("ok", ...)`. **Sin test dedicado** (ver hallazgo) — verificado con `test_verify_ca03_ca04.py::test_ca04_...`: `notices == []`. |
| CA-05 | PASS | Sin destino fijado, comportamiento idéntico al anterior. Cubierto por `tests/test_webview_buttons.py::test_el_selector_de_modelo_muestra_el_activo_y_lo_cambia` (GUI) y reforzado por `test_verify_ca03_ca04.py::test_ca05_...` (slot directo: escribe config y emite el toast). |
| CA-06 | PASS | `_cadena_de_respaldo_por_defecto()` arma OpenRouter→Ollama sin `fallback_provider`. Cubierto por `tests/test_provider_health.py::test_sin_respaldo_configurado_se_usa_el_default_en_vez_del_apartado` y verificado además con clave presente (`_cadena_de_respaldo_por_defecto("deepseek")` con `get_api_key` mockeada a `"sk-or-test"` → `[("openrouter","openrouter/free"), ("ollama","qwen3:8b")]`). |
| CA-07 | PASS | Sin `OPENROUTER_API_KEY`, OpenRouter se omite (`activo != "openrouter" and config_manager.get_api_key("openrouter")`). Cubierto indirectamente por los dos tests de `test_provider_health.py` que mockean `get_api_key` a `""` y solo ven `ollama` en la cadena; confirmado directo (`_cadena_de_respaldo_por_defecto` con clave vacía → solo `[("ollama","qwen3:8b")]`). |
| CA-08 | PASS | `_resolver_cadena_de_respaldo()` usa `_cadena_de_respaldo()` tal cual cuando `fallback_config` es truthy, sin agregar el default. Verificado directo: `_resolver_cadena_de_respaldo("deepseek", "openai")` → `[("openai", "gpt-4o-mini")]`, sin rastro de OpenRouter/Ollama. |
| CA-09 | PASS | No-regresión — los 14 tests pre-existentes de `_cadena_de_respaldo()`/`_intentar_respaldos()` en `test_provider_fallback.py` siguen pasando sin editar (verificado: `_cadena_de_respaldo()` no cambió de firma ni comportamiento). |
| CA-10 | PASS | Sin ningún destino (cadena vacía incluso con el default), cae a `SIN_PROVEEDOR`, nunca una excepción sin manejar. Cubierto por `tests/test_provider_fallback.py::test_sin_ningun_destino_se_devuelve_sin_proveedor`. |
| CA-11 | PASS | La rama que antes devolvía `f"Error ({activo}): {error_original}"` crudo ahora delega siempre en `_intentar_respaldos()` (`llm_provider.py:357-360`), que solo devuelve `SIN_PROVEEDOR` o una respuesta real — nunca `"No module named"`/`"Traceback"`/repr de excepción. Cubierto por `test_sin_ningun_destino_se_devuelve_sin_proveedor` y `test_si_todos_fallan_se_avisa_sin_tecnicismos`. |
| CA-12 | PASS | El aviso ("Cambié a X porque Y no respondió.") queda en el texto real de la respuesta, en ambos puntos de ensamblado (`reasoning_loop.run()` y `claude_brain._resolver_con_tools()`), y también cuando el disparador es el swap preventivo por cooldown (punto (a) de arquitectura-022.md). **Sin test dedicado en el repo** (ver hallazgo) — verificado con `verify_req022_ca12_18.py` (4 de las 8 verificaciones cubren directamente este CA y su variante de cooldown). |
| CA-13 | PASS | Sin respaldo, `con_aviso_de_cambio()` devuelve el texto sin tocar (`texto_aviso_cambio()` retorna `""` si `aviso` no trae `proveedor_hacia`). **Sin test dedicado** — verificado directo: respuesta idéntica a la del mock, sin ninguna mención de "Cambié". |
| CA-14 | PASS | El aviso se concatena al `final_text` real (lo que se guarda en `agent_context` y se muestra), no pasa por `notice_shown` ni solo por logging — confirmado leyendo el valor de retorno completo de `reasoning_loop.run()`, no solo mockeando logging/notice. |
| CA-15 | PASS | `ai/claude_brain.py::_resolver_con_tools()` usa el mismo `con_aviso_de_cambio()`/`generate_response(..., aviso=...)` que `reasoning_loop.run()`. **No existe `tests/test_claude_brain.py`** — este módulo no tenía ningún test propio antes de este REQ tampoco (hallazgo agravado, ver abajo). Verificado directo con `verify_req022_ca12_18.py::test_ca15_...`. |
| CA-16 | PASS | `resolved_channel == ChannelType.VOICE` → `con_aviso_de_cambio(..., corto=True)` → "Cambié de modelo." sin nombres técnicos. **Sin test dedicado** — verificado directo. |
| CA-17 | PASS | Cualquier otro canal → forma larga con proveedor y modelo. **Sin test dedicado** — verificado directo (mismo script, canal `"desktop"`). |
| CA-18 | PASS | `ui/tts_engine.py::prepare_for_speech()` reconoce `AVISO_CAMBIO_RE` (ancla a fin de texto) y sustituye por `AVISO_CAMBIO_CORTO`, sin importar el canal resuelto — cubre el caso del manos libres del webview (`DESKTOP`) y el modo voz de `main.py`. **`tests/test_speech_prep.py` no tiene ningún caso de REQ-022** (solo CA-24/CA-27 de REQ-021) — verificado directo: texto largo con nombres de proveedor/modelo entra, sale con "Cambié de modelo." y sin "deepseek"/"ollama". |

**18/18 PASS** en comportamiento real.

## Regresión

| Área revisada | Resultado |
|----------------|-----------|
| Cadena de respaldo explícita (`fallback_provider` string/lista, pre-REQ-022) | Sin cambios — 14 tests originales de `test_provider_fallback.py` intactos y en PASS. |
| Selector de modelo sin destino fijado (comportamiento pre-REQ-022) | Sin cambios — CA-05 confirmado PASS por GUI y por invocación directa del slot. |
| Cooldown / disponibilidad de proveedores (`ai/provider_health.py`) | Sin cambios de comportamiento fuera de lo que pide CA-06 (default en vez de insistir con el apartado) — 20 tests de `test_provider_health.py` en PASS. |
| Resto del sistema (1764 tests) | Sin fallos nuevos. |

## Hallazgo — cobertura de tests incompleta para 7 de 18 CA (no es un bug funcional)

`SPEC-022.md` (tabla "Módulos afectados", fila `tests/`) prometía explícitamente tests
nuevos para "presencia/ausencia del aviso en el texto de respuesta por canal, y forma corta
del aviso en `ChannelType.VOICE`" — es decir, exactamente Decisión 3 y Decisión 4, el núcleo
de este REQ (CA-12 a CA-18). `.claude/rules/testing.md` además exige, sin condicional, que
"toda función pública debe tener al menos un test": `texto_aviso_cambio()` y
`con_aviso_de_cambio()` (ambas públicas, sin prefijo `_`, en `ai/llm_provider.py`) no tienen
ninguno en el repo.

Estado real encontrado:
- **CA-03/CA-04**: el gate del lado servidor de `set_model()` (invocación directa del slot,
  que es justo lo que pide la letra de la SPEC porque el slot es alcanzable desde cualquier
  script de la página) nunca se ejercita en ningún test existente — el test de GUI que más
  se le acerca (`test_el_selector_de_modelo_se_deshabilita_si_esta_fijado_por_tarea`) prueba
  CA-02 (la UI no deja abrir el menú), pero como el menú nunca se abre, el slot `set_model()`
  nunca se invoca en ese test, así que el gate real nunca corre.
- **CA-12 a CA-18** (7 criterios — todo el mecanismo del aviso: `texto_aviso_cambio()`,
  `con_aviso_de_cambio()`, la propagación en `reasoning_loop.run()` y en
  `claude_brain._resolver_con_tools()`, y el acortado en
  `ui/tts_engine.py::prepare_for_speech()`): **cero** menciones de `aviso`,
  `con_aviso_de_cambio`, `AVISO_CAMBIO_CORTO`/`AVISO_CAMBIO_RE`, o el texto "Cambié a ...
  porque ... no respondió." en todo `tests/`. `ai/claude_brain.py` no tiene archivo de test
  propio en absoluto (`tests/test_claude_brain.py` no existe), y `tests/test_speech_prep.py`
  solo cubre CA-24/CA-27 de REQ-021, nada de REQ-022.
- Cobertura menor también ausente: el camino positivo de CA-06/CA-07 (con
  `OPENROUTER_API_KEY` sí configurada, confirmando que OpenRouter se intenta antes que
  Ollama) solo tiene tests del lado "sin clave" — el lado "con clave" no está commiteado
  (sí lo verifiqué manualmente, ver tabla).

Por qué esto no es cosmético: son exactamente las funciones y puntos de integración nuevos
de mayor riesgo de este REQ — sin un test que falle si alguien rompe
`con_aviso_de_cambio()`, cambia el regex `AVISO_CAMBIO_RE`, o desconecta el aviso de
`claude_brain.py` en un cambio futuro, nadie se entera hasta que un usuario reporte que el
selector de modelo "volvió a mentir" o que el fallback "volvió a ser mudo" — el mismo tipo de
bug que motivó este REQ en primer lugar.

Confirmé el comportamiento en el flujo real (no solo por lectura de código) con los dos
scripts descritos en "Metodología" — el **veredicto de comportamiento es 18/18 PASS** — pero
esos scripts viven en el scratchpad de esta sesión, no en el repositorio, y por lo tanto no
protegen contra una regresión futura. Corresponde a `orion-dev` convertirlos en tests
commiteados antes de que este REQ pueda considerarse completo bajo `testing.md`.

### Feedback específico para `orion-dev`
1. `tests/test_webview_bridge.py` (o donde encaje mejor): agregar 2 tests que instancien
   `Bridge` headless (mismo patrón que el resto del archivo) e invoquen
   `bridge.set_model(...)` **directamente** (no vía click de UI) con
   `ai.llm_provider.destinos_de_tarea` mockeada para devolver un destino fijado en
   `"razonamiento"` — verificar que `config_manager.set_ai_provider_and_model` NO se llamó
   (CA-03) y que `bridge.notice_shown` NO se emitió (CA-04). Reemplazo casi directo de
   `test_verify_ca03_ca04.py` (scratchpad de esta sesión, 3 tests, los 3 en PASS).
2. `tests/test_reasoning_loop.py`: agregar tests con `generate_response` mockeado (mismo
   patrón que `test_ca07_agota_5_llamadas_sin_una_sexta` u otros de ese archivo) que rellenen
   el parámetro `aviso` recibido por kwargs, y verificar que `reasoning_loop.run(...)` con
   `channel="desktop"` devuelve el texto con la forma larga (CA-12/13/14/17) y con
   `channel="voice"` con la forma corta (CA-16).
3. Crear `tests/test_claude_brain.py` (no existe) con al menos un test de
   `_resolver_con_tools()` que confirme el mismo aviso que `reasoning_loop.run()` (CA-15).
4. `tests/test_speech_prep.py`: agregar un test de `prepare_for_speech()` con un texto que
   termine en la forma larga del aviso, confirmando que sale con "Cambié de modelo." y sin
   nombres de proveedor/modelo (CA-18).
5. (Menor, no bloqueante) `tests/test_provider_health.py` o `test_provider_fallback.py`:
   agregar el caso positivo de CA-06/07 con `OPENROUTER_API_KEY` configurada, confirmando
   que se intenta `openrouter` antes que `ollama`.

Los scripts de esta sesión (`verify_req022_ca12_18.py`,
`test_verify_ca03_ca04.py`, en el scratchpad de esta sesión de `orion-tester`) tienen la
lógica de mocking ya resuelta y pueden adaptarse directamente — no hace falta rediseñar el
enfoque, solo commitear la forma final en los archivos de test correspondientes.

## Veredicto: **FAIL** (proceso/cobertura — no hay ningún bug funcional encontrado)

Los 18 criterios de aceptación se comportan correctamente en el flujo real. El FAIL es
exclusivamente porque 7 CA (los que implementan el núcleo de la Decisión 3 y 4 de este REQ)
y la invocación directa de `set_model()` (CA-03/CA-04) no tienen ningún test commiteado que
los proteja, en contra de lo que `SPEC-022.md` prometía en su propia tabla de módulos
afectados y de lo que exige `.claude/rules/testing.md` para código nuevo. Devuelvo a
`orion-dev` únicamente para agregar esos tests — no hace falta tocar la lógica de producto,
que ya es correcta.

---

## Segunda vuelta — 2026-09-07 — verificación de la cobertura agregada

**Entradas leídas:** este mismo reporte (arriba, primera vuelta), la sección "Segunda vuelta"
de `propuestas/desarrollo-log-022.md` y la última entrada de `REQ-022-context.md`
(`orion-dev`, 2026-09-07). No asumí que el autorreporte de `orion-dev` fuera correcto — leí
yo mismo los 15 tests nuevos en los 5 archivos antes de correr nada.

### Compilación
- `python -m py_compile ai/claude_brain.py ai/llm_provider.py core/reasoning_loop.py ui/tts_engine.py ui/webview/bridge.py tests/test_llm_provider.py tests/test_reasoning_loop.py tests/test_claude_brain.py tests/test_speech_prep.py tests/test_webview_bridge.py` → **OK**, sin errores.

### Lectura directa de los 15 tests nuevos (no solo el autorreporte)

| Archivo | Tests | Verificación de contenido |
|---|---|---|
| `tests/test_llm_provider.py` (+5, sección "REQ-022: aviso de cambio") | `test_ca13_sin_cambio_de_destino_el_texto_no_se_toca`, `test_ca12_17_con_cambio_la_forma_larga_lleva_proveedor_y_modelo`, `test_ca16_con_cambio_y_corto_no_lleva_nombres_tecnicos`, `test_aviso_cambio_re_reconoce_exactamente_lo_que_arma_texto_aviso_cambio`, `test_ca06_07_con_openrouter_api_key_configurada_se_intenta_antes_que_ollama` | Reales: comparan strings exactos (`"Cambié a openrouter (openrouter/free) porque deepseek (deepseek-chat) no respondió."`), invocan `texto_aviso_cambio()`/`con_aviso_de_cambio()` directo (funciones públicas antes sin ningún test), verifican auto-consistencia del regex `AVISO_CAMBIO_RE` contra la salida real de `texto_aviso_cambio()`, y el caso positivo de CA-06/07 con clave mockeada comparando la lista completa devuelta. Ningún `assert True`/tautología. |
| `tests/test_reasoning_loop.py` (+3, sección "REQ-022/CA-12, CA-13, CA-14, CA-16, CA-17") | `test_ca12_14_17_aviso_de_cambio_queda_en_el_texto_final_por_defecto`, `test_ca13_sin_cambio_de_destino_el_texto_no_lleva_aviso`, `test_ca16_en_canal_voice_el_aviso_es_la_forma_corta_sin_nombres_tecnicos` | Reales: `generate_response` mockeado con `side_effect` que RELLENA el kwarg `aviso` in-place (mismo contrato que la función real, no un `return_value` fijo que lo ignoraría — exactamente el hueco que señalé en la primera vuelta), corren `reasoning_loop.run()` extremo a extremo y comparan el `result` completo carácter a carácter, y CA-14 se verifica de verdad leyendo `mock_ctx.update_context.call_args_list[-1]` (lo persistido en `agent_context`), no solo el valor de retorno. |
| `tests/test_claude_brain.py` (archivo nuevo, +2) | `test_ca15_el_aviso_de_cambio_se_propaga_igual_que_en_reasoning_loop`, `test_ca15_sin_cambio_de_destino_el_texto_no_lleva_aviso` | Real: primer test de este módulo en todo el repo, confirmado (`git log`/lectura directa, el archivo no existía antes de esta vuelta). Mismo patrón de fake que `test_reasoning_loop.py`, invoca `_resolver_con_tools()` con canal `"telegram"`/`"discord"` y compara el string final completo — cierra exactamente el hallazgo agravado de la primera vuelta. |
| `tests/test_speech_prep.py` (+2, sección "REQ-022/CA-18") | `test_ca18_la_forma_larga_del_aviso_se_acorta_sin_nombres_de_proveedor_o_modelo`, `test_ca18_sin_aviso_de_cambio_el_texto_no_se_toca` | Real: arma el texto largo con `con_aviso_de_cambio()` real (no un fixture inventado a mano), lo pasa por `prepare_for_speech()` real, y confirma que "deepseek"/"openrouter"/"openrouter/free" NO aparecen en la salida hablada. Documenta honestamente un efecto lateral del aplanado existente (`". . Cambié de modelo."` con doble punto) en vez de esconderlo con un texto de aviso artificial — coincide con lo que yo mismo observé al verificar manualmente en la primera vuelta. |
| `tests/test_webview_bridge.py` (+3, sección "REQ-022/CA-03, CA-04") | `test_ca03_set_model_no_escribe_config_si_hay_destino_fijado_por_tarea`, `test_ca04_set_model_no_emite_notice_si_hay_destino_fijado_por_tarea`, `test_ca05_set_model_sin_destino_fijado_escribe_config_y_avisa` | Real: invocan `bridge.set_model(...)` **directamente** (no vía click de UI, que es exactamente el gate que la primera vuelta encontró sin ejercitar), mockean `destinos_de_tarea` para simular un destino fijado, y verifican que `config_manager.set_ai_provider_and_model` NO se llamó (lista `escrituras == []`) y que `bridge.notice_shown` NO se emitió (lista `notices == []`). CA-05 es la contracara de no-regresión: sin destino fijado, sí escribe y sí avisa — confirmado con aserciones positivas concretas, no solo "no lanza excepción". |

Ninguno de los 15 tests es tautológico ni un placeholder — todos ejercitan el código de
producto real (no mocks del propio sistema bajo prueba) y afirman sobre valores concretos
(strings exactos, listas vacías/no vacías, contenido de lo persistido). Los 5 puntos
accionables de la primera vuelta quedan cerrados uno a uno, confirmado por lectura directa,
no por el autorreporte de `orion-dev`.

### Tests existentes / suite completa
- Suite dirigida (los 5 archivos tocados/creados): **154/154 OK** (corrida por mí, no solo
  tomada del log de `orion-dev`).
- Suite completa (`pytest tests/ --tb=short -q`): **1779/1779 OK**, sin fallos, sin
  inestabilidad (1764 de la primera vuelta + exactamente los 15 tests nuevos, ningún test
  pre-existente tocado ni removido).

### Criterios de la SPEC — segunda vuelta
El comportamiento de los 18 CA ya se había verificado PASS en la primera vuelta (ver tabla
arriba) y `orion-dev` no tocó lógica de producto en esta vuelta (confirmado: el diff de esta
vuelta es exclusivamente en `tests/`). Lo que cambia en esta vuelta es exclusivamente la
cobertura commiteada de CA-03, CA-04, CA-12 a CA-18 — confirmada arriba, test por test.

| Punto accionable (primera vuelta) | Estado |
|---|---|
| 1. `tests/test_webview_bridge.py` — CA-03/CA-04 vía `bridge.set_model()` directo | CERRADO — 2 tests + 1 de regresión (CA-05) |
| 2. `tests/test_reasoning_loop.py` — CA-12/13/14/16/17 con `aviso` por kwargs | CERRADO — 3 tests |
| 3. `tests/test_claude_brain.py` — CA-15 | CERRADO — archivo nuevo, 2 tests |
| 4. `tests/test_speech_prep.py` — CA-18 | CERRADO — 2 tests |
| 5. (menor) caso positivo CA-06/07 con `OPENROUTER_API_KEY` | CERRADO — 1 test |

### DoD `orion-dev` (segunda vuelta) — nota de proceso
El propio `desarrollo-log-022.md` deja sin marcar el ítem "Banner mostrado antes de escribir
código" para esta vuelta, documentado explícitamente como "omitido por error de proceso" en
vez de marcarlo falsamente. No es motivo de FAIL — es un ítem de proceso del banner, no de
contenido ni de veracidad de los tests, y `orion-dev` lo reportó con honestidad en vez de
ocultarlo. Se deja constancia para que quede en el historial, sin bloquear el avance.

### Regresión — segunda vuelta
| Área revisada | Resultado |
|---|---|
| Los 1764 tests de la primera vuelta | Intactos, sin ningún cambio de contenido (confirmado por conteo: 1779 - 15 = 1764). |
| Los 15 tests nuevos entre sí | Ninguno depende de red, micrófono, ni `subprocess` real — todos mockean `generate_response`/`config_manager`/`destinos_de_tarea` en el punto de entrada, cumpliendo `.claude/rules/testing.md`. |

## Veredicto — segunda vuelta: **PASS**

Los 5 puntos accionables de la primera vuelta quedaron cerrados con tests reales y verificados
por lectura directa (no por el autorreporte de `orion-dev`). Los 18 CA de `SPEC-022.md` siguen
en PASS de comportamiento (sin cambios en esta vuelta) y ahora tienen la cobertura commiteada
que `SPEC-022.md` y `.claude/rules/testing.md` exigían. Suite completa 1779/1779, sin fallos
nuevos. Avanza a `orion-qa`.
