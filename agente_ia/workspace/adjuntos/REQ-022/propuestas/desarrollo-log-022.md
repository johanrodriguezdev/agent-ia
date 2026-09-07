# Desarrollo REQ-022 — Selector de modelo del chat + fallback automático

## Nota de proceso — interrupción por límite de tasa
El subagente `orion-dev` original (bajo autorización nocturna en bloque del 2026-09-06) implementó
el código real de este REQ, pero se interrumpió antes de cerrar su propio DoD (rate limit / HTTP 429,
"session limit"), sin escribir este log, sin actualizar `REQ-022-context.md` ni el CSV, y sin entregar
el mensaje de commit sugerido. Su último mensaje visible fue: "Only the pre-existing baseline failure
remains. Now let's write the requirements.txt check (no new deps expected), the desarrollo-log, update
context, and update the tracker." — es decir, la implementación y verificación de código ya estaban
terminadas.

Yo (la sesión que continuó tras la interrupción) verifiqué independientemente el resultado — no acepté
el autorreporte del agente caído sin comprobarlo — y completé el cierre del DoD de `orion-dev`
directamente: esta nota documenta esa verificación y ese cierre.

## Alcance implementado
Cubre los 18 CA de `SPEC-022.md`, según el diseño aprobado en `propuestas/arquitectura-022.md`
(aprobación registrada como "bajo autorización nocturna en bloque", ver `REQ-022-context.md`):

- **`ai/llm_provider.py`**: canal `aviso: Optional[dict]` en `generate_response()` (claves
  `proveedor_desde`/`modelo_desde`/`proveedor_hacia`/`modelo_hacia`); `_cadena_de_respaldo_por_defecto()`
  y `_resolver_cadena_de_respaldo()` (default OpenRouter `:free` → Ollama `qwen3:8b` cuando no hay
  `fallback_provider` ni lista explícita); `texto_aviso_cambio()` / `con_aviso_de_cambio()` +
  constantes `AVISO_CAMBIO_CORTO` / `AVISO_CAMBIO_RE` (fuente única para la forma larga y corta del
  aviso); corrección de CA-11 en `_intentar_respaldos()`; corrección de un bug latente de comparación
  tupla-vs-string en el swap preventivo por cooldown.
- **`core/reasoning_loop.py`**: propaga el `aviso` de `generate_response()` hacia el texto final de
  la respuesta (CA-12/CA-14/CA-15).
- **`ai/claude_brain.py`**: mismo propagado en `_resolver_con_tools()`, segundo punto de ensamblado
  de respuesta (Telegram/Discord).
- **`ui/tts_engine.py::prepare_for_speech()`**: reconoce la redacción larga vía `AVISO_CAMBIO_RE` y
  la sustituye por la forma corta antes de hablar — único punto de preparación de voz, cubre también
  el caso de `main.py` (modo voz de CLI leyendo canal DESKTOP) y el manos libres del webview
  (riesgo P2 heredado de REQ-021).
- **`ui/webview/bridge.py`**: `set_model()` deja de escribir `config.json` cuando hay un destino fijado
  por tarea para "razonamiento" (elimina el toast falso positivo "Ahora respondo con X");
  `_build_models_payload()` ajustado en consecuencia.
- **`ui/webview/frontend/js/composer.js`**: `renderModels()` / `alternarMenuDeModelos()` reflejan el
  estado deshabilitado/reetiquetado del selector cuando `task_providers.razonamiento` manda.

## Verificación (realizada directamente, no solo tomada del autorreporte del agente caído)
```
python -m py_compile ai/claude_brain.py ai/llm_provider.py core/reasoning_loop.py \
    ui/tts_engine.py ui/webview/bridge.py
→ OK, sin errores

python -m pytest tests/test_provider_fallback.py tests/test_provider_health.py \
    tests/test_webview_buttons.py tests/test_llm_provider.py tests/test_reasoning_loop.py \
    --tb=short -q
→ 99 passed

python -m pytest tests/ --tb=line -q   (suite completa)
→ 1764 passed, 0 failures (incluye la prueba antes inestable
  test_task_slots.py::test_la_hora_dicha_se_respeta, que esta vez pasó — dependiente de
  fecha/reloj del entorno, no relacionada con este REQ)
```

## requirements.txt
Sin dependencias nuevas de este REQ. El único diff presente (`openai` SDK) es previo y no
relacionado — ya documentado como corregido fuera de REQ-022 (ver `REQ-022-context.md`, "Riesgos
activos").

## DoD `orion-dev` — checklist
```
[x] Solo se implementó lo aprobado en arquitectura (18 CA, arquitectura-022.md)
[x] Sin API keys/tokens hardcodeados
[x] Sin `except: pass` silencioso
[x] Sin prints de debug en código final
[x] Sin dependencias nuevas — requirements.txt sin cambios de este REQ
[x] No tocó skills — N/A
[x] Banner mostrado antes de escribir código (agente original, sesión previa)
[x] desarrollo-log-022.md generado (este archivo)
[x] NO se ejecutó git commit
[x] Mensaje de commit sugerido entregado (ver abajo)
```

## Mensaje de commit sugerido
```
feat(REQ-022): coherencia selector de modelo del chat + fallback automático a modelo gratuito

- ai/llm_provider.py: canal `aviso` en generate_response(), cadena de respaldo por defecto
  (OpenRouter :free -> Ollama qwen3:8b), texto largo/corto del aviso de cambio de modelo
- core/reasoning_loop.py y ai/claude_brain.py: propagan el aviso al texto de la respuesta
- ui/tts_engine.py: forma corta de voz sin nombres de proveedor/modelo
- ui/webview/bridge.py y composer.js: elimina el toast falso positivo de set_model() cuando
  hay un modelo fijado por tarea para "razonamiento"
- tests: cobertura de CA-03/CA-04 (gate real de set_model()) y CA-12 a CA-18 (núcleo del
  aviso de cambio de modelo), ausente en la primera vuelta — ver sección siguiente
```

---

## Segunda vuelta — 2026-09-07 — cobertura de tests (devuelto por orion-tester)

`orion-tester` devolvió el REQ con veredicto FAIL de **proceso/cobertura, no de
comportamiento**: los 18 CA de `SPEC-022.md` pasaban en el flujo real (verificados con dos
scripts de scratchpad de esa sesión, `verify_req022_ca12_18.py` y
`test_verify_ca03_ca04.py`), pero 7 de ellos (CA-12 a CA-18, el núcleo de las Decisiones 3
y 4 — el aviso de cambio de modelo dentro de la respuesta y su forma corta de voz) y la
invocación directa de `set_model()` (CA-03/CA-04) no tenían ningún test commiteado que los
protegiera, en contra de lo que `.claude/rules/testing.md` exige para toda función pública
nueva y de lo que la propia tabla de "Módulos afectados" de `SPEC-022.md` prometía. Detalle
completo del hallazgo y de los 5 puntos accionables: `pruebas/test-results-022.md`.

**No se tocó lógica de producto** — el trabajo de esta vuelta fue exclusivamente agregar
tests, adaptando la lógica de mocking que `orion-tester` ya había resuelto en sus dos
scripts de scratchpad, sin rediseñar el enfoque.

### Tests agregados

- **`tests/test_llm_provider.py`** (5 tests nuevos, sección "REQ-022: aviso de cambio"):
  - `test_ca13_sin_cambio_de_destino_el_texto_no_se_toca` — CA-13: `texto_aviso_cambio()`/
    `con_aviso_de_cambio()` sin cambio de destino no agregan nada.
  - `test_ca12_17_con_cambio_la_forma_larga_lleva_proveedor_y_modelo` — CA-12/CA-17: forma
    larga con proveedor y modelo de origen/destino, agregada al final del texto.
  - `test_ca16_con_cambio_y_corto_no_lleva_nombres_tecnicos` — CA-16: `corto=True` siempre
    devuelve `AVISO_CAMBIO_CORTO`, sin nombres técnicos.
  - `test_aviso_cambio_re_reconoce_exactamente_lo_que_arma_texto_aviso_cambio` —
    auto-consistencia entre `AVISO_CAMBIO_RE` (lo que reconoce `tts_engine.py`) y lo que
    arma `texto_aviso_cambio()` (riesgo documentado en `arquitectura-022.md`).
  - `test_ca06_07_con_openrouter_api_key_configurada_se_intenta_antes_que_ollama` — caso
    positivo de CA-06/07 (punto 5, menor, de `test-results-022.md`): con
    `OPENROUTER_API_KEY` configurada, `_cadena_de_respaldo_por_defecto()` ofrece OpenRouter
    antes que Ollama.

- **`tests/test_reasoning_loop.py`** (3 tests nuevos, sección "REQ-022/CA-12, CA-13,
  CA-14, CA-16, CA-17"): `generate_response` mockeado con un `side_effect` que rellena el
  kwarg `aviso` (mismo contrato que la función real), verificando `reasoning_loop.run(...)`
  extremo a extremo:
  - `test_ca12_14_17_aviso_de_cambio_queda_en_el_texto_final_por_defecto` — canal
    `"desktop"`: forma larga en `final_text`, y confirma además (CA-14) que lo que se
    persiste en `agent_context_manager.update_context()` es el texto CON el aviso.
  - `test_ca13_sin_cambio_de_destino_el_texto_no_lleva_aviso` — sin swap, `final_text` no
    gana ninguna línea.
  - `test_ca16_en_canal_voice_el_aviso_es_la_forma_corta_sin_nombres_tecnicos` — canal
    `"voice"` → `ChannelType.VOICE` → forma corta.

- **`tests/test_claude_brain.py`** (archivo nuevo — no existía ningún test de este módulo
  en el repo, "hallazgo agravado" de `test-results-022.md`): mismo patrón de mocking que
  `test_reasoning_loop.py`, aplicado a `_resolver_con_tools()` (el camino de
  Telegram/Discord):
  - `test_ca15_el_aviso_de_cambio_se_propaga_igual_que_en_reasoning_loop` — CA-15: mismo
    aviso en el texto final que produce `reasoning_loop.run()`.
  - `test_ca15_sin_cambio_de_destino_el_texto_no_lleva_aviso` — contracara sin swap.

- **`tests/test_speech_prep.py`** (2 tests nuevos, sección "REQ-022/CA-18"):
  - `test_ca18_la_forma_larga_del_aviso_se_acorta_sin_nombres_de_proveedor_o_modelo` —
    CA-18: `prepare_for_speech()` reconoce `AVISO_CAMBIO_RE` y sustituye por
    `AVISO_CAMBIO_CORTO`, sin nombres de proveedor/modelo. (Nota: el resultado exacto es
    `"...42. . Cambié de modelo."` — el doble `\n\n` que agrega `con_aviso_de_cambio()` se
    aplana carácter a carácter por el paso 6, comportamiento de aplanado ya existente, no
    algo introducido por este REQ.)
  - `test_ca18_sin_aviso_de_cambio_el_texto_no_se_toca` — contracara: texto sin la forma
    larga del aviso pasa intacto por este punto.

- **`tests/test_webview_bridge.py`** (3 tests nuevos, sección "REQ-022/CA-03, CA-04"):
  invocan `bridge.set_model(...)` **directamente** (no vía click de UI), reemplazando el
  patrón de `test_verify_ca03_ca04.py` de la sesión de `orion-tester`:
  - `test_ca03_set_model_no_escribe_config_si_hay_destino_fijado_por_tarea` — CA-03: con
    `destinos_de_tarea("razonamiento")` fijado, `config_manager.set_ai_provider_and_model`
    NO se llama.
  - `test_ca04_set_model_no_emite_notice_si_hay_destino_fijado_por_tarea` — CA-04: mismo
    caso, `bridge.notice_shown` NO se emite.
  - `test_ca05_set_model_sin_destino_fijado_escribe_config_y_avisa` — regresión de CA-05:
    sin destino fijado, el comportamiento pre-REQ-022 sigue intacto (sí escribe, sí avisa).

### Verificación
```
python -m py_compile tests/test_llm_provider.py tests/test_reasoning_loop.py \
    tests/test_claude_brain.py tests/test_speech_prep.py tests/test_webview_bridge.py
→ OK, sin errores

python -m pytest tests/test_llm_provider.py tests/test_reasoning_loop.py \
    tests/test_claude_brain.py tests/test_speech_prep.py tests/test_webview_bridge.py \
    --tb=short -q
→ 154 passed

python -m pytest tests/ --tb=short -q   (suite completa)
→ 1779 passed, 0 failures (1764 de la primera vuelta + 15 tests nuevos de esta vuelta;
  sin fallos nuevos, sin inestabilidad — la suite dirigida y la completa coinciden)
```

### requirements.txt
Sin cambios — esta vuelta no agregó ninguna dependencia (solo tests con los mocks ya
disponibles en el repo).

### DoD `orion-dev` (segunda vuelta) — checklist
```
[x] Solo se implementó lo aprobado — en este caso, exactamente los 5 puntos accionables de
    test-results-022.md, sin tocar lógica de producto
[x] Sin API keys/tokens hardcodeados
[x] Sin `except: pass` silencioso
[x] Sin prints de debug en código final
[x] Sin dependencias nuevas — requirements.txt sin cambios
[x] No tocó skills — N/A
[ ] Banner mostrado antes de escribir código — OMITIDO por error de proceso en esta vuelta;
    se deja registrado en vez de marcarlo falsamente. No afecta el contenido ni la
    veracidad de los tests agregados.
[x] desarrollo-log-022.md actualizado (esta sección)
[x] NO se ejecutó git commit
[x] Mensaje de commit sugerido actualizado (ver arriba)
```
