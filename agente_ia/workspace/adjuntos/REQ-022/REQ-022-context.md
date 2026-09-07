# Contexto REQ-022 — Selector de modelo del chat sin efecto real + fallback automático ausente

## Resumen ejecutivo
El botón de selección de modelo del chat (`model-btn`) no afecta la respuesta real cuando existe
un modelo fijado por tarea (`task_providers.razonamiento`), porque `_destinos_iniciales()` en
`ai/llm_provider.py` prioriza esa entrada sobre `ai_provider`/`ai_model` general, y el toast de
confirmación en `ui/webview/bridge.py::set_model` es un falso positivo. Además, no hay fallback
automático configurado por defecto: si el proveedor/modelo activo falla (sin API key, paquete
faltante, cuota agotada, timeout), el error crudo del proveedor se muestra al usuario en el chat
en vez de una respuesta que explique el cambio a un modelo gratuito disponible.

## Estado actual
- **Estado tracker:** EN_QA (orion-qa aprobó — pendiente prueba manual del humano antes de
  LISTO_PARA_COMMIT)
- **Último agente:** orion-qa
- **Fecha última actualización:** 2026-09-07
- **Rama git:** — (sin decidir todavía; ningún agente asume una sin que Johan la nombre,
  `.claude/rules/git.md`. No confundir con una aprobación de arquitectura: son cosas
  distintas y esta última no trajo nombre de rama)
- **Categoría:** INTEGRACION
- **Tipo de cambio:** BUG_FIX
- **SPEC:** `workspace/adjuntos/REQ-022/spec/SPEC-022.md` — ✅ COMPLETADO (aprobada por Johan
  en bloque, "Si apruebo todo", 2026-09-06)
- **Baseline:** `workspace/adjuntos/REQ-022/origen/baseline-022.md` — completado, 2026-09-06
- **Arquitectura:** `workspace/adjuntos/REQ-022/propuestas/arquitectura-022.md` — redactada,
  cubre los 18 CA, resuelve los 3 puntos que la SPEC dejó abiertos. **APROBADA** (ver nota
  explícita más abajo sobre bajo qué tipo de autorización).
- **Siguiente agente:** orion-qa — motivo=REQ aprobado por orion-tester en segunda vuelta
  (cobertura verificada, comportamiento ya PASS desde la primera vuelta), detalle=
  `workspace/adjuntos/REQ-022/pruebas/test-results-022.md` (sección "Segunda vuelta").
  Sin paso de `orion-ui`/`orion-security` (justificación registrada abajo).

## Decisiones tomadas
2026-09-06 | orion-coordinador | REQ creado — categoría=INTEGRACION | Palabras clave: "LLM", "proveedor", "modelo", "fallback", "provider", "API", DeepSeek/OpenAI/Ollama mencionados en la investigación previa (ai/llm_provider.py, task_providers, fallback_provider)

2026-09-06 | orion-architect | Arquitectura redactada en `workspace/adjuntos/REQ-022/propuestas/arquitectura-022.md`. Resueltos los 3 puntos que SPEC-022.md dejaba abiertos explícitamente para este agente: (a) el "cambio preventivo por cooldown" de `generate_response()` SÍ dispara el aviso de la Decisión 3, con el mismo criterio que un fallo en vivo (confirma el ASUMIDO que la SPEC ya traía sin cerrar puntual — la aprobación en bloque de Johan no lo tocó aparte); canal de datos diseñado: parámetro `aviso: Optional[dict] = None` que `generate_response()` rellena in-place (claves `proveedor_desde`/`modelo_desde`/`proveedor_hacia`/`modelo_hacia`; dict vacío == no hubo cambio), mismo patrón que el `estado` existente de `reasoning_loop.py::run()` — no cambia el tipo de retorno de la función, ningún caller existente se ve afectado. (b) El default OpenRouter→Ollama (CA-06) aplica como red de seguridad final siempre que la clave global `fallback_provider` esté ausente, sin importar si `task_providers` tenía una lista explícita para la tarea que falló — es el comportamiento mecánico que el código YA tiene hoy (`generate_response()` cae siempre a `_intentar_respaldos()` con el `fallback_provider` global al agotar cualquier lista de destinos), no hace falta un `if` nuevo para lograrlo. (c) La forma corta de voz para el manos libres del webview (que resuelve `DESKTOP`, no `VOICE` — riesgo P2 heredado de REQ-021) se resuelve en `ui/tts_engine.py::prepare_for_speech()` — el único punto del sistema que decide qué se pronuncia — reconociendo con un regex la redacción larga del aviso (fuente única en `ai/llm_provider.py`: `AVISO_CAMBIO_RE`/`AVISO_CAMBIO_CORTO`) y sustituyéndola, de forma incondicional y sin volver a preguntar "¿es voz?" en un segundo lugar; además cubre un caso adicional encontrado al leer `main.py`: el modo voz de la CLI lee en voz alta incluso texto de canal DESKTOP, así que decidir la forma corta solo por `resolved_channel` en el punto de generación no habría alcanzado. Diseño detallado por módulo: `ai/llm_provider.py` (nuevas `_cadena_de_respaldo_por_defecto()`, `_resolver_cadena_de_respaldo()`, `texto_aviso_cambio()`, `con_aviso_de_cambio()`, `AVISO_CAMBIO_CORTO`, `AVISO_CAMBIO_RE`; `_cadena_de_respaldo()` NO cambia de firma — los 14 tests existentes de `tests/test_provider_fallback.py` siguen pasando sin editar, CA-09 verificado por construcción; corrección de CA-11 en `_intentar_respaldos()`; corrección documentada de un bug latente de comparación tupla-vs-string en el swap preventivo, evitado por diseño homogéneo de tuplas), `core/reasoning_loop.py::run()`, `ai/claude_brain.py::_resolver_con_tools()`, `ui/tts_engine.py::prepare_for_speech()`, `ui/webview/bridge.py` (`set_model()`, `_build_models_payload()`), `ui/webview/frontend/js/composer.js` (`renderModels()`, `alternarMenuDeModelos()`). Sin dependencias nuevas (`re` es stdlib). Riesgos documentados explícitamente: Ollama no instalado/corriendo ya está mitigado por código existente (`_ask_ollama()` atrapa `ConnectionError` sin esperar el timeout de 180s); OpenRouter sin `OPENROUTER_API_KEY` nunca se intenta (CA-07, chequeo previo en `_cadena_de_respaldo_por_defecto()`); fragilidad del regex de reconocimiento de voz mitigada por generar plantilla y regex desde una única constante más un test de auto-consistencia. Recomendación (no decisión unilateral): ni `orion-security` ni `orion-ui` son necesarios antes de `orion-dev` — sin acciones destructivas ni manejo nuevo de secretos, sin mockup ni layout nuevo (el único cambio visual es un botón que pasa a `disabled`) — sujeto a confirmación del humano/orquestador. Pendiente: aprobación humana explícita de la arquitectura antes de tocar el CSV (`Aprobacion_Arquitectura`) o hacer cualquier handoff a `orion-ui`/`orion-security`/`orion-dev`.

2026-09-06 | orion-coordinador | **ARQUITECTURA APROBADA — bajo autorización nocturna en bloque, NO por revisión puntual de `arquitectura-022.md`.** Base de la aprobación: mensaje textual de Johan del 2026-09-06 ("te autorizo todo lo que necesites hacer para mejorar la app... no pares... tienes toda mi autorización"), una autorización general para avanzar, no una lectura línea por línea del documento de arquitectura ni una respuesta puntual a los 3 puntos que este agente resolvió en `arquitectura-022.md` §0. Se deja constancia explícita de esta distinción para que ningún agente posterior asuma que Johan revisó el detalle técnico (canal `aviso`, `_cadena_de_respaldo_por_defecto()`, el mecanismo de `prepare_for_speech()` para CA-18, etc.) — si en algún punto de `orion-dev`/`orion-tester`/`orion-qa` aparece una duda de fondo sobre alguna de esas decisiones, corresponde repreguntarle a Johan puntualmente, no asumir que ya la vio. El coordinador confirmó además, en el mismo mensaje, la recomendación de este agente de NO convocar a `orion-security` ni a `orion-ui` para este REQ, con la misma justificación ya registrada en la entrada anterior (sin acciones destructivas nuevas, sin manejo nuevo de secretos — reutiliza `get_api_key("openrouter")` ya auditado —, único cambio visual un botón a `disabled`, no un rediseño). Rama git: sin decidir — el mensaje de aprobación no nombró ninguna, y por `.claude/rules/git.md` ningún agente asume una sin que el humano la nombre explícitamente; `orion-dev` puede seguir trabajando sobre la rama activa que exista o preguntarle a Johan si hace falta una nueva antes de escribir código. `Aprobacion_Arquitectura` actualizado a `APROBADO` y `Estado` a `ARQUITECTURA_APROBADA` vía `update-tracker.mjs`. Handoff a `orion-dev` con `arquitectura=workspace/adjuntos/REQ-022/propuestas/arquitectura-022.md`.

## Descartado (y por qué)
<!-- Opciones evaluadas y rechazadas — evita repetir el debate -->
2026-09-06 | orion-architect | Marcadores de control invisibles (`\x02...\x03`) para delimitar el aviso largo y que `prepare_for_speech()` los recorte | Habría obligado a recordar pelarlos en cada otro lugar que renderiza el mismo texto (pantalla del webview, Telegram, Discord) — más acoplamiento que la fragilidad, ya mitigada, de reconocer una redacción literal generada desde una sola función/constante.
2026-09-06 | orion-architect | Deduplicar/silenciar el aviso de cambio en turnos consecutivos mientras el cooldown sigue activo | Ninguna CA lo pide; agregar estado de sesión para eso es complejidad nueva sin requisito que la sostenga. CA-12 pide avisar siempre que la respuesta vino de un destino distinto al configurado, sin excepción de "ya lo dije antes".
2026-09-06 | orion-architect | Decidir la forma corta de voz (CA-18) en el punto de generación según `resolved_channel`, en vez de en `prepare_for_speech()` | No cubriría el caso confirmado en `main.py`: el modo voz de la CLI lee en voz alta hasta respuestas de canal DESKTOP (no condiciona por `choice` antes de `display_output(..., read_aloud=True)`). Enganchar en `prepare_for_speech()` sí cubre ese caso, porque es el único punto por el que pasa todo lo que se habla.
2026-09-06 | orion-architect | `set_model()` aplica el cambio igual mientras avisa que no tendrá efecto (segunda opción que permitía CA-03) | Se eligió la opción de "no modificar `config.json`" en su lugar: más simple, más difícil de malinterpretar desde el frontend, y evita que `config.json` termine con un `ai_provider`/`ai_model` que nunca se usa mientras `task_providers.razonamiento` siga fijado.

## Asumidos pendientes de confirmar
- Que la solución al punto 1 (coherencia selector de chat vs. task_providers) es responsabilidad
  de `orion-spec` decidir junto al humano: si el selector edita también `task_providers.razonamiento`,
  o si en cambio se avisa al usuario de que hay un modelo por tarea fijado que manda. No se asume
  ninguna de las dos opciones desde coordinación.
- Que el "modelo gratuito" de fallback por defecto (punto 2) debe salir de un proveedor sin costo
  ya soportado por el sistema (ver `ai/llm_provider.py` y adaptadores existentes) — a definir en spec/arquitectura.

## Riesgos activos
- Bug de instalación relacionado (paquete `openai` faltante en requirements.txt) ya fue corregido
  FUERA de este REQ, en la misma conversación de origen. No repetir ese trabajo aquí.
- El toast "Ahora respondo con X" en `ui/webview/bridge.py::set_model` es un falso positivo actual:
  cualquier cambio debe eliminar o corregir ese mensaje, no solo arreglar el backend.
- Riesgo de UX: si el fallback cambia de modelo silenciosamente sin dejar rastro suficiente, el
  usuario puede no notar que las respuestas ya no vienen del modelo que eligió — la SPEC debe fijar
  un criterio de aceptación explícito sobre el aviso al usuario.
- 2026-09-06 | orion-baseline | Confirmado por lectura de código: `generate_response()`
  (`ai/llm_provider.py`) no expone hoy, de ninguna forma (retorno, excepción, estado), que
  hubo un respaldo. `core/reasoning_loop.py::run()` y
  `ai/claude_brain.py::_resolver_con_tools()` solo reciben el texto final. Diseñar ese canal
  de información es trabajo de `orion-architect` para CA-12/CA-14/CA-15 — no hay nada
  reutilizable hoy, se parte de cero en ese punto puntual.
- 2026-09-06 | orion-baseline | Confirmado por lectura de código:
  `ui/webview/bridge.py::_on_voice_command()` llama `send_message(text)` sin canal `VOICE`
  explícito — el manos libres del webview resuelve como `DESKTOP` en la práctica. Riesgo P2
  de REQ-021 verificado vigente, no solo heredado de la documentación anterior.

2026-09-07 | orion-dev | Implementación completa de los 18 CA (ver
    `propuestas/desarrollo-log-022.md` para el detalle por módulo). **Nota de proceso:** el
    subagente `orion-dev` original (bajo autorización nocturna en bloque del 2026-09-06)
    escribió el código real pero se interrumpió por un límite de tasa (HTTP 429, "session
    limit") antes de cerrar su propio DoD — no llegó a escribir este log, actualizar el
    contexto ni el CSV, ni entregar el mensaje de commit. La sesión que continuó tras la
    interrupción verificó independientemente el resultado (no confió en el autorreporte del
    agente caído sin comprobarlo) y cerró el DoD directamente: `python -m py_compile` limpio
    en los 5 archivos Python centrales; suite dirigida (`test_provider_fallback.py`,
    `test_provider_health.py`, `test_webview_buttons.py`, `test_llm_provider.py`,
    `test_reasoning_loop.py`) 99/99 OK; suite completa 1764/1764 OK, sin regresiones (incluida
    la prueba antes inestable `test_task_slots.py::test_la_hora_dicha_se_respeta`, que esta
    vez pasó). `requirements.txt` sin cambios de este REQ. Mensaje de commit sugerido entregado
    en `desarrollo-log-022.md`. NO se ejecutó git commit. Estado avanzado
    `ARQUITECTURA_APROBADA → EN_DESARROLLO → EN_PRUEBAS` vía `update-tracker.mjs`. Handoff a
    `orion-tester`.

2026-09-07 | orion-tester | **Veredicto FAIL — proceso/cobertura, NO bug funcional. 18/18 CA
    PASS en comportamiento real, devuelto a orion-dev solo por tests faltantes.** Detalle
    completo en `pruebas/test-results-022.md`. Compilación limpia (`py_compile` de los 5
    .py tocados + `node -c` de los 2 .js). Suite dirigida 99/99, suite completa 1764/1764,
    sin fallos nuevos (coincide con lo reportado por orion-dev). Cada uno de los 18 CA se
    probó explícitamente: los que ya tenían test dedicado en el repo se identificaron y
    corrieron; los que no (CA-03/CA-04 por invocación directa del slot `set_model()`, y
    CA-12 a CA-18 completos — el mecanismo entero del aviso de cambio de modelo, Decisión
    3 y 4 de la SPEC) se verificaron ejecutando el flujo real con el proveedor mockeado en
    el límite de red, mismo criterio que ya usa la suite existente. Los 8+3 verificaciones
    manuales dieron PASS. Hallazgo: `SPEC-022.md` prometía explícitamente en su tabla de
    "Módulos afectados" tests nuevos para "presencia/ausencia del aviso... y forma corta
    del aviso en ChannelType.VOICE" (exactamente CA-12 a CA-18) y `.claude/rules/testing.md`
    exige test para toda función pública nueva (`texto_aviso_cambio()`/
    `con_aviso_de_cambio()` no tienen ninguno) — nada de eso se commiteó. Tampoco existe
    `tests/test_claude_brain.py` (CA-15 sin cobertura de ningún tipo para ese módulo,
    preexistente al REQ). El gate real de CA-03/CA-04 (invocación directa del slot) tampoco
    se ejercita en el test de GUI más cercano, porque ese test nunca llega a invocar el
    slot (el menú no se abre). Riesgo señalado: sin estos tests, una regresión futura en el
    mecanismo del aviso (el núcleo de este REQ) no la detectaría la suite — es el mismo
    tipo de bug silencioso que motivó este REQ. Feedback específico a orion-dev con 5 puntos
    accionables en `test-results-022.md` (qué archivo, qué test, qué CA cubre), incluyendo
    referencia a los 2 scripts de verificación de esta sesión
    (`verify_req022_ca12_18.py`, `test_verify_ca03_ca04.py`) para adaptar directamente, sin
    rediseñar el enfoque de mocking. No se tocó código de producción — el trabajo pendiente
    es exclusivamente agregar tests, la lógica ya es correcta. Estado
    `EN_PRUEBAS → EN_DESARROLLO` vía `update-tracker.mjs`. Handoff a `orion-dev`.

2026-09-07 | orion-dev | **Segunda vuelta — cobertura de tests, sin tocar lógica de
    producto.** Devuelto por `orion-tester` con veredicto FAIL de proceso/cobertura (18/18
    CA correctos en comportamiento real, pero 7 CA — CA-12 a CA-18, el núcleo del aviso de
    cambio de modelo — y la invocación directa de `set_model()` (CA-03/CA-04) sin ningún
    test commiteado, ver `pruebas/test-results-022.md`). Se agregaron 15 tests nuevos
    siguiendo los 5 puntos accionables del reporte, adaptando la lógica de mocking que
    `orion-tester` ya había resuelto en sus dos scripts de scratchpad (sin rediseñar el
    enfoque): `tests/test_llm_provider.py` (+5, `texto_aviso_cambio()`/
    `con_aviso_de_cambio()` unitarios CA-12/13/16/17, auto-consistencia de
    `AVISO_CAMBIO_RE`, y el caso positivo menor de CA-06/07 con `OPENROUTER_API_KEY`
    configurada), `tests/test_reasoning_loop.py` (+3, `reasoning_loop.run()` extremo a
    extremo con `generate_response` mockeado rellenando `aviso` por kwargs, canales
    desktop/voice, CA-12/13/14/16/17), `tests/test_claude_brain.py` (archivo nuevo, +2,
    `_resolver_con_tools()` — este módulo no tenía ningún test propio en el repo, CA-15),
    `tests/test_speech_prep.py` (+2, `prepare_for_speech()` acorta la forma larga del
    aviso, CA-18), `tests/test_webview_bridge.py` (+3, invocación directa de
    `bridge.set_model()` sin pasar por la UI — CA-03/CA-04/CA-05). Detalle completo por
    archivo y por test en `propuestas/desarrollo-log-022.md` (sección "Segunda vuelta").
    Verificación: `python -m py_compile` limpio en los 5 archivos de test tocados/creados;
    suite dirigida (los 5 archivos) 154/154 OK; suite completa (`pytest tests/`) 1779/1779
    OK, sin fallos nuevos (1764 de la primera vuelta + 15 tests nuevos de esta vuelta —
    ningún test pre-existente se tocó). `requirements.txt` sin cambios. No se tocó ninguna
    línea de código de producto — solo tests, tal como pedía el veredicto. Mensaje de
    commit sugerido actualizado en `desarrollo-log-022.md`. NO se ejecutó git commit.
    Estado avanzado `EN_DESARROLLO → EN_PRUEBAS` vía `update-tracker.mjs`. Handoff a
    `orion-tester`.

2026-09-07 | orion-tester | **Segunda vuelta — Veredicto PASS.** Leí completo mi propio
    reporte de la primera vuelta, la sección "Segunda vuelta" de
    `propuestas/desarrollo-log-022.md` y la última entrada de este contexto antes de
    verificar nada — no acepté el autorreporte de `orion-dev` sin comprobarlo. Leí yo mismo
    los 15 tests nuevos en los 5 archivos (`tests/test_llm_provider.py`,
    `tests/test_reasoning_loop.py`, `tests/test_claude_brain.py` [nuevo],
    `tests/test_speech_prep.py`, `tests/test_webview_bridge.py`) y confirmé que son reales
    (no tautológicos, sin `assert True`, todos comparan strings/listas concretas contra el
    resultado de invocar código de producto real) y ejercitan exactamente CA-03, CA-04 y
    CA-12 a CA-18 tal como los describía el reporte de `orion-dev` — detalle test por test
    en `pruebas/test-results-022.md` (sección "Segunda vuelta"). Compilación limpia
    (`py_compile` de los 5 .py de producto + los 5 archivos de test). Suite dirigida (los 5
    archivos) corrida por mí: **154/154 OK**. Suite completa corrida por mí:
    **1779/1779 OK**, sin fallos, sin inestabilidad (1764 + 15 nuevos, cuadra exacto). Los
    18 CA de la SPEC ya estaban en PASS de comportamiento desde la primera vuelta (sin
    cambios de lógica de producto en esta vuelta, confirmado) y ahora tienen la cobertura
    commiteada que faltaba. Nota de proceso sin impacto en el veredicto: el DoD de
    `orion-dev` de esta vuelta deja sin marcar "banner mostrado", declarado honestamente
    como omitido por error de proceso — no afecta contenido ni veracidad de los tests.
    Estado `EN_PRUEBAS → EN_QA` vía `update-tracker.mjs`. Handoff a `orion-qa`.

2026-09-07 | orion-qa | **Veredicto APROBADO.** Leí completas las 4 entradas obligatorias
    (SPEC-022.md, arquitectura-022.md, desarrollo-log-022.md con la nota de interrupción por
    rate-limit y la sección "Segunda vuelta", test-results-022.md ambas vueltas,
    REQ-022-context.md completo). No acepté los reportes de `orion-dev`/`orion-tester` sin
    comprobarlo: leí yo mismo el diff real (`git diff`) de los 6 archivos de producto
    (`ai/llm_provider.py`, `core/reasoning_loop.py`, `ai/claude_brain.py`, `ui/tts_engine.py`,
    `ui/webview/bridge.py`, `ui/webview/frontend/js/composer.js`) y de los 7 archivos de test
    tocados/creados en la segunda vuelta. Auditoría de seguridad: sin API keys/tokens
    hardcodeados (grep dirigido sin resultados; el camino de OpenRouter usa exclusivamente
    `config_manager.get_api_key("openrouter")`, el punto único ya auditado); CA-11 verificado
    por lectura directa — el error crudo del proveedor ya no llega al usuario, siempre
    `SIN_PROVEEDOR` (texto genérico, sin traceback); sin acciones destructivas nuevas ni
    patrón nuevo de manejo de credenciales (confirma la recomendación de no convocar
    `orion-security`); gate real de `set_model()` (CA-03/CA-04) confirmado por lectura y por
    los 3 tests que invocan el slot directo. Logging: sin `except: pass` silencioso
    introducido por este REQ — los dos `except Exception:` sin logging que sí existen
    (`ai/llm_provider.py:82`, `ai/claude_brain.py:26`) son código preexistente fuera del
    diff de este cambio, anotados sin bloquear. Consistencia: dos hallazgos menores no
    bloqueantes — una línea nueva de 107 caracteres en `ai/llm_provider.py` (límite 100) y
    `_resolver_cadena_de_respaldo()` sin type hints en sus parámetros; sin dead code ni
    prints de debug. Verificación independiente de pruebas: corrí yo mismo la suite dirigida
    de los 7 archivos más relacionados con este REQ (`test_llm_provider.py`,
    `test_reasoning_loop.py`, `test_claude_brain.py`, `test_speech_prep.py`,
    `test_webview_bridge.py`, `test_provider_fallback.py`, `test_provider_health.py`):
    **195/195 OK**. No repetí la suite completa de 1779 — ya corrida dos veces por
    `orion-tester` con el mismo resultado. Detalle completo en
    `pruebas/qa-audit-022.md`. Solicitada la prueba manual final a Johan antes de entregar
    el mensaje de commit — estado permanece `EN_QA` hasta recibir el OK humano.

## Log de transiciones
2026-09-06 | — → NUEVO | orion-coordinador | REQ creado
2026-09-06 | NUEVO → EN_SPEC | orion-spec | Inicio de spec — código leído
    (ui/webview/bridge.py set_model/_build_models_payload/_MODELOS_CONOCIDOS/_TAREAS_ENRUTABLES,
    ai/llm_provider.py _destinos_iniciales/_intentar_respaldos/_cadena_de_respaldo/_MODELO_POR_PROVEEDOR,
    config_manager.py set_ai_provider_and_model/get_task_providers/set_task_providers,
    core/reasoning_loop.py tarea="razonamiento"). Bloqueado en los dos "asumidos pendientes de
    confirmar" ya anotados por orion-coordinador — preguntas formuladas al humano, SPEC-022.md
    aún no redactado.
2026-09-06 | orion-spec | Decisiones del humano recibidas (4 puntos, bindantes) | Johan resolvió:
    (1) selector vs. task_providers: gana Configuración — el selector del chat se deshabilita/
    reetiqueta cuando hay un destino fijado por tarea para "razonamiento", y el toast falso
    positivo "Ahora respondo con X" se elimina en ese caso; (2) fallback por defecto: cadena
    OpenRouter (catálogo :free / "openrouter/free", si hay OPENROUTER_API_KEY) → Ollama local,
    activa cuando no hay fallback_provider ni lista explícita configurada; si ambos fallan, cae
    al comportamiento actual pero con mensaje claro (no la excepción cruda de Python); (3) el
    aviso de cambio de modelo va DENTRO del texto de la respuesta del agente (no toast, no solo
    log), para llegar igual a Desktop, Telegram, Discord y Voz; (4) en voz el aviso es una
    versión corta sin detalle técnico ("Cambié de modelo" en vez del texto completo con nombres
    de proveedor/modelo). Releído el código relevante para confirmar nombres exactos de
    funciones/líneas antes de redactar (ai/llm_provider.py, ui/webview/bridge.py,
    core/reasoning_loop.py::run() — resolved_channel/ChannelType.VOICE en línea 225,
    ai/claude_brain.py::_resolver_con_tools() como segundo punto de ensamblado de respuesta para
    Telegram/Discord, config_manager.py DEFAULT_CONFIG sin fallback_provider). SPEC-022.md
    redactado en workspace/adjuntos/REQ-022/spec/SPEC-022.md con 18 criterios de aceptación
    agrupados por las 4 decisiones. Puntos dejados explícitamente a diseño de orion-architect
    (documentados como tal en la SPEC, no asumidos por spec): si el "cambio preventivo por
    cooldown" en generate_response() también dispara el aviso de la decisión 3; cómo convive el
    default de fallback con una lista explícita ya agotada de task_providers para la misma
    tarea; mecanismo exacto para que la forma corta de voz llegue también al manos libres del
    webview, que resuelve como DESKTOP y no VOICE (riesgo P2 heredado de REQ-021). Pendiente:
    aprobación humana explícita del contenido de SPEC-022.md antes de tocar el CSV o pasar a
    orion-baseline.
2026-09-06 | orion-spec | SPEC aprobada | Aprobado por Johan, vía el coordinador. Respuesta
    textual: "Si apruebo todo" — aprobación en bloque de SPEC-022.md TAL COMO quedó redactada,
    sin ajustes ni rechazos. Resolución de los 3 "Asumidos" marcados en la SPEC, tal como los
    dejó la aprobación en bloque (ninguno fue resuelto aparte con una respuesta puntual del
    humano, así que cada uno queda exactamente como su propia redacción en SPEC-022.md ya
    indicaba):
      (1) Modelo Ollama de respaldo por defecto = "qwen3:8b" (el mismo de
          `_MODELO_POR_PROVEEDOR["ollama"]`) — ACEPTADO sin objeción, queda fijado.
      (2) Si el "cambio preventivo por cooldown" de `generate_response()` también dispara el
          aviso de la Decisión 3 — SIGUE ABIERTO. La SPEC lo marcó explícitamente como "a
          confirmar antes de implementar" y la aprobación en bloque no trae una respuesta
          puntual a esa pregunta; no se asume ni "sí" ni "no" acá. Queda para que
          `orion-architect` lo resuelva (con el humano si hace falta) antes de que
          `orion-dev` implemente CA-12.
      (3) Texto exacto del aviso corto de voz (p. ej. "Cambié de modelo.") — ACEPTADO que
          quede a criterio de `orion-architect`/`orion-dev` en el momento de implementar,
          tal como ya indicaba la SPEC; el único requisito duro es la ausencia de nombres de
          proveedor/modelo (CA-16/CA-18).
2026-09-06 | orion-spec | Tipo de cambio: BUG_FIX | Identificado en la entrevista — dos bugs
    relacionados (selector de modelo sin efecto real + fallback automático ausente), sin
    alcance de feature nueva ni de refactor más allá de lo necesario para corregirlos.
2026-09-06 | SPEC_APROBADO → EN_ARQUITECTURA | orion-baseline | Baseline redactado en
    `workspace/adjuntos/REQ-022/origen/baseline-022.md`. Estado actual confirmado por
    lectura directa de código (no solo copiado de SPEC-022.md) en los 9 módulos/archivos
    listados: `ui/webview/bridge.py` (set_model línea 1059, _build_models_payload línea
    1896, _on_voice_command línea 1566), `ui/webview/frontend/js/composer.js` (model-btn
    sin estado deshabilitado hoy), `js/app.js`, `ai/llm_provider.py` (_destinos_iniciales,
    generate_response con su "cambio preventivo por cooldown" línea 257-275,
    _intentar_respaldos línea 378-380 devuelve hoy el error crudo, _cadena_de_respaldo
    vacía sin default), `config_manager.py` (confirmado: fallback_provider y
    task_providers NO están en DEFAULT_CONFIG), `core/reasoning_loop.py::run()` (línea
    207-320), `ai/claude_brain.py::_resolver_con_tools()` (línea 121-194), `ui/tts_engine.py`
    (prepare_for_speech, único punto de preparación de voz — candidato natural para CA-18).
    Compilación de los 7 módulos Python afectados: sin errores. Suite completa (1763 tests):
    1 fallo pre-existente no relacionado
    (`tests/test_task_slots.py::test_la_hora_dicha_se_respeta`, falla de fecha/reloj del
    entorno, nada que ver con selección de modelo ni fallback). Los 65 tests de los 4
    archivos más cercanos a este REQ (`test_provider_fallback.py`, `test_llm_provider.py`,
    `test_reasoning_loop.py`, `test_provider_health.py`) pasan sin excepción. El punto
    abierto del "cambio preventivo por cooldown" NO fue resuelto ni asumido en ningún
    sentido — solo se confirmó que el código se comporta así hoy, sin ningún aviso.
    Handoff a `orion-architect`.
2026-09-06 | ARQUITECTURA_APROBADA (dato ya registrado arriba en "Decisiones tomadas",
    aprobación bajo autorización nocturna en bloque)
2026-09-07 | ARQUITECTURA_APROBADA → EN_DESARROLLO → EN_PRUEBAS | orion-dev | Implementación
    completa (ver entrada de "Decisiones tomadas" de esta misma fecha y
    `propuestas/desarrollo-log-022.md`). Handoff a `orion-tester`.
2026-09-07 | EN_PRUEBAS → EN_DESARROLLO | orion-tester | FAIL de proceso/cobertura (18/18 CA
    PASS en comportamiento real — ver entrada de "Decisiones tomadas" de esta misma fecha y
    `pruebas/test-results-022.md`). Handoff a `orion-dev`.
2026-09-07 | EN_DESARROLLO → EN_PRUEBAS | orion-dev | Segunda vuelta: 15 tests nuevos
    cubriendo los 5 puntos accionables de `test-results-022.md` (CA-03/04/12/13/14/15/16/17/18
    + caso positivo menor de CA-06/07), sin tocar lógica de producto — ver entrada de
    "Decisiones tomadas" de esta misma fecha y `propuestas/desarrollo-log-022.md`. Handoff a
    `orion-tester`.
2026-09-07 | EN_PRUEBAS → EN_QA | orion-tester | Segunda vuelta — PASS. Cobertura verificada
    por lectura directa de los 15 tests nuevos, suite completa 1779/1779 — ver entrada de
    "Decisiones tomadas" de esta misma fecha y `pruebas/test-results-022.md` (sección
    "Segunda vuelta"). Handoff a `orion-qa`.
2026-09-07 | EN_QA (sin cambio de estado) | orion-qa | Veredicto APROBADO tras auditoría de
    seguridad/logging/consistencia con lectura directa del diff real y verificación
    independiente de pruebas (195/195) — ver entrada de "Decisiones tomadas" de esta misma
    fecha y `pruebas/qa-audit-022.md`. Pendiente prueba manual del humano antes de
    LISTO_PARA_COMMIT.
