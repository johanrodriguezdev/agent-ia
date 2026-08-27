# Resultados de prueba REQ-021 — Conversación multi-turno real

**Agente:** orion-tester
**Fecha:** 2026-08-26
**Rama:** `feature/REQ-021-conversacion-multiturno` (ningún agente ejecutó git en esta fase)
**Entradas:** `spec/SPEC-021.md` (32 CA), `propuestas/desarrollo-log-021.md`,
`propuestas/security-audit-021.md`, `propuestas/arquitectura-021.md`, `origen/baseline-021.md`

> **Método.** Este informe no se limita a comprobar que la suite pasa. Para cada criterio se
> identificó el test concreto que lo cubre y se verificó que **lo cubre de verdad**: se mutó el
> código de producción que el criterio protege y se comprobó que el test **falla**. Un test que
> sigue pasando con el código roto no prueba nada, y acá se marca como vacuidad. Las 15 mutaciones
> se aplicaron y se revirtieron una por una; el árbol de trabajo quedó exactamente como estaba.

---

## Compilación

`python -m py_compile` sobre los 13 módulos de producción tocados o consumidores directos:

```
core/dialog_state.py  core/dialog_questions.py  core/resolution.py  core/reasoning_loop.py
tasks/task_slots.py   tasks/task_manager.py     voice/mic_window.py voice/wake_word.py
ui/tts_engine.py      ui/cli.py                 ui/webview/bridge.py
ui/webview/wake_word_worker.py                  main.py
```

**Resultado: OK — 13/13.**

## Tests existentes

Verificación propia sobre los 7 archivos del REQ más la superficie de regresión de
`core/resolution.py`:

```
$ python -m pytest tests/test_task_slots.py tests/test_dialog_state.py \
    tests/test_dialog_resolution.py tests/test_speech_prep.py tests/test_mic_window.py \
    tests/test_wake_word_comando.py tests/test_reasoning_loop.py tests/test_resolution.py -q
173 passed en 5.34s
```

- Pasados (suite completa, medición de la sesión principal): **683 / 685**
- Nuevos fallos: **ninguno**
- Fallos pre-existentes: **2**, `tests/test_llm_provider.py` (`patch("anthropic.Anthropic")` con
  el paquete `anthropic` no instalado — `requirements.txt:70`). Zona `ai/llm_provider.py`, no
  tocada por este REQ. Idénticos al baseline.
- Delta sobre el baseline: **+123 tests**, 560 → 683.

---

## Criterios de la SPEC

Leyenda: **PASS** = existe test, se identificó, y la mutación del código que protege lo hace
fallar. **PASS\*** = cubierto, con una observación registrada abajo. **FAIL** = sin test.
**MANUAL** = no verificable en unidad por naturaleza del criterio.

### Diálogo pendiente — núcleo

| Criterio | Resultado | Test que lo cubre |
|----------|-----------|-------------------|
| CA-01 no crea nada y repregunta | PASS | `test_dialog_resolution.py::test_ca01_frase_sin_contenido_no_crea_nada_y_repregunta` (4 frases parametrizadas), `::test_ca01_falta_solo_el_cuando`, `::test_ca01_falta_solo_el_que` |
| CA-02 nunca título "Algo" ni `now()+1h` | PASS | `test_dialog_resolution.py::test_ca04_ca05_caso_de_referencia_completo` (título `"Llamar al contador"`, `remind_at` = mañana 09:00, con `parse_natural_task` REAL), `test_task_slots.py::test_ca02_cadena_compose_mas_parse_da_la_tarea_correcta` |
| CA-03 no regresión de un solo tiro | PASS | `test_dialog_resolution.py::test_ca03_no_regresion_de_un_solo_tiro`, `test_task_slots.py::test_fijacion_frase_completa_de_un_solo_tiro`, `test_ca09_task_tool_las_4_ramas` |
| CA-04 lo resuelve el diálogo, no otro resolver | PASS | `test_dialog_resolution.py::test_ca04_la_frase_suelta_no_la_resuelve_ningun_otro_resolver`, `::test_ca04_ca05_caso_de_referencia_completo` |
| CA-05 cierre menciona qué y cuándo | PASS | `test_dialog_resolution.py::test_ca04_ca05_caso_de_referencia_completo` |
| CA-06 cancelación explícita | PASS | `test_dialog_resolution.py::test_ca06_cancelacion` (4 frases), `::test_ca06_cancelar_exige_coincidencia_exacta` |
| CA-07 expiración silenciosa | PASS | `test_dialog_state.py::test_ca07_expira_al_leer_sin_hilo_de_fondo`, `::test_ca07_el_ttl_por_defecto_son_tres_minutos`, `::test_ca07_fill_reinicia_la_cuenta`, `test_dialog_resolution.py::test_ca07_dialogo_expirado_no_crea_nada_ni_avisa` |
| CA-08 aislamiento `(user_id, canal)` | PASS | `test_dialog_state.py::test_ca08_aislamiento_entre_usuarios_del_mismo_canal`, `::test_ca08_aislamiento_entre_canales_del_mismo_usuario`, `test_dialog_resolution.py::test_ca08_aislamiento_por_usuario_y_canal` |

### No regresión de los canales

| Criterio | Resultado | Test que lo cubre |
|----------|-----------|-------------------|
| CA-09 mismo `matched_by` de los 7 resolvers | PASS | `test_dialog_resolution.py::test_ca09_routine`, `::test_ca09_autopilot`, `::test_ca09_learned`, `::test_ca09_task_tool_las_4_ramas`, `::test_ca09_capability`, `::test_ca09_intent`, `::test_ca09_claude` |
| CA-10 `expects_reply` con default `False` | PASS | Los 7 `test_ca09_*` aseveran `expects_reply is False`; `tests/test_resolution.py` (434 líneas, aserciones intactas) y los tests de los 4 consumidores pasan sin modificación |
| CA-11 paridad Telegram / Discord | PASS | `test_dialog_resolution.py::test_ca11_mismo_dialogo_en_los_3_canales` (DESKTOP/TELEGRAM/DISCORD parametrizados), `test_telegram_bot.py::test_ca10_*` (intactos) |

### Ventana de micrófono (manos libres)

| Criterio | Resultado | Test que lo cubre |
|----------|-----------|-------------------|
| CA-12 frase aceptada sin wake word ~15 s | PASS | `test_mic_window.py::test_ca12_ca13_ciclo_de_la_ventana`, `::test_ca12_con_la_ventana_abierta_la_frase_se_acepta_sin_wake_word`, `::test_el_worker_pasa_su_ventana_a_listen_for_wake_word` + `test_wake_word_comando.py::test_worker_emite_el_comando_detectado`, `::test_bridge_resuelve_el_comando_de_voz_como_uno_escrito` |
| CA-13 vencimiento y vuelta a `LISTENING_WAKE` | PASS | `test_mic_window.py::test_ca13_con_la_ventana_cerrada_la_misma_frase_no_se_resuelve`, `::test_ca13_al_vencer_la_ventana_el_estado_vuelve_a_listening_wake`, `::test_ca13_expired_now_reporta_una_sola_vez` |
| CA-14 el agente no se escucha a sí mismo | PASS\* | `test_mic_window.py::test_ca14_un_chunk_anterior_a_la_apertura_se_rechaza` + `test_wake_word_comando.py::test_ca26_la_ventana_abre_al_terminar_la_locucion_no_antes` — **el doble candado está probado en unidad; el cruce real de 3 hilos NO. Ver §R1.** |
| CA-15 el guard no descarta el 2º turno | PASS | `test_wake_word_comando.py::test_ca15_la_ventana_solo_abre_con_el_guard_ya_liberado`, `::test_bridge_descarta_un_comando_de_voz_solapado_no_un_segundo_turno` |
| CA-16 caso de referencia completo en vivo | **MANUAL** | Sin test posible: exige el webview real, TTS audible y micrófono. Es la prueba de Johan. |

### Seguridad

| Criterio | Resultado | Test que lo cubre |
|----------|-----------|-------------------|
| CA-17 el canal del gate viene del caller | PASS | `test_dialog_resolution.py::test_ca17_el_canal_llega_al_gate_desde_el_caller_no_del_dialogo` + `::test_ca18_b_desvio_yellow_pasa_por_el_gate_con_el_canal_real` (espía sobre el `require_confirmation()` **real**, sin cambiar su veredicto) |
| CA-18 (a) slot `que` → fail-safe | PASS | `test_dialog_resolution.py::test_ca18_a_fail_safe_con_el_slot_que_pendiente` |
| CA-18 (b) slot `cuando` → desvío + gate con canal real | PASS | `::test_ca18_b_desvio_yellow_pasa_por_el_gate_con_el_canal_real`, `::test_ca18_b_desvio_red_sigue_bloqueado_por_el_fail_closed` |
| CA-19 el slot no cambia la acción destino | PASS\* | `test_dialog_resolution.py::test_ca19_el_contenido_de_un_slot_nunca_cambia_la_accion_destino`, `test_dialog_state.py::test_ca19_la_accion_destino_no_tiene_setter` — **el guard nuevo de `_execute_completed_dialog()` no tiene test. Ver §Vacuidad #2.** |

### Calidad conversacional

| Criterio | Resultado | Test que lo cubre |
|----------|-----------|-------------------|
| CA-20 el LLM redacta, el respaldo suena a persona | PASS | `test_dialog_state.py::test_ca20_respaldo_cuando_el_llm_falla`, `::test_ca20_respuestas_inservibles_caen_al_respaldo` (6 casos), `::test_ca20_usa_la_frase_del_llm_cuando_es_valida`, `::test_las_frases_de_respaldo_suenan_a_persona`, `test_dialog_resolution.py::test_ca20_la_repregunta_del_llm_se_usa_cuando_sirve` |
| CA-21 detectar es determinista, sin LLM | PASS | `test_dialog_resolution.py::test_ca21_detectar_no_consume_llm_y_el_respaldo_mantiene_el_flujo` (asevera `len(llamadas) == 1`: solo la redacción), `test_task_slots.py::test_scan_task_slots_es_puro` |
| CA-22 `_build_prompt` con los últimos N turnos | PASS | `test_reasoning_loop.py::test_ca22_sin_historial_el_prompt_es_el_de_siempre`, `::test_ca22_el_prompt_incluye_los_ultimos_n_turnos`, `::test_ca22_los_turnos_previos_conviven_con_el_historial_de_tools`, `::test_ca22_un_fallo_de_la_db_de_contexto_no_tumba_el_loop`, `::test_ca22_los_turnos_leidos_son_estrictamente_anteriores` |

### Pieza 8 — voz en el webview

| Criterio | Resultado | Test que lo cubre |
|----------|-----------|-------------------|
| CA-23 solo habla en manos libres | PASS | `test_wake_word_comando.py::test_ca23_solo_habla_con_el_manos_libres_activo`, `::test_la_ventana_no_se_abre_con_el_manos_libres_apagado` |
| CA-24 texto plano, sin markdown ni emojis | PASS | `test_speech_prep.py::test_ca24_salida_real_de_format_task_created_sin_markdown_ni_emojis`, `::test_ca24_el_id_no_se_pierde_al_barrer_la_almohadilla`, `::test_ca24_html_y_markdown_variados`, `::test_ca24_texto_vacio` + `test_wake_word_comando.py::test_ca24_se_pronuncia_el_texto_crudo_preparado_nunca_el_html` |
| CA-25 `speak()` nunca en el hilo de la GUI | PASS | `test_wake_word_comando.py::test_ca25_speak_nunca_se_invoca_desde_el_hilo_de_la_gui` |
| CA-26 la ventana abre en el `on_done` del TTS | PASS | `test_wake_word_comando.py::test_ca26_la_ventana_abre_al_terminar_la_locucion_no_antes`, `::test_r10_solo_la_locucion_mas_reciente_arma_la_ventana` |
| CA-27 una sola función; ambas vías limpias | PASS\* | `test_speech_prep.py::test_ca27_aplanado_de_saltos_de_linea`, `::test_ca27_umbral_de_400_no_trunca`, `::test_ca27_corte_en_380_al_ultimo_punto_con_coletilla`, `::test_ca27_display_output_usa_la_funcion_comun`, `::test_ca27_una_sola_implementacion` — **el umbral 400 y el corte 380 no están fijados. Ver §Vacuidad #1.** |
| CA-28 un fallo del TTS no rompe el turno | PASS | `test_wake_word_comando.py::test_ca28_un_fallo_del_tts_abre_la_ventana_igual`, `::test_el_error_de_resolucion_no_habla_pero_abre_la_ventana` |
| CA-29 barge-in + el diálogo sobrevive | **FAIL** | **Ninguno.** `grep -rin "barge" tests/` → 0 resultados en toda la suite. |

### Desvío de tema con diálogo abierto

| Criterio | Resultado | Test que lo cubre |
|----------|-----------|-------------------|
| CA-30 el desvío se responde, el diálogo vive | PASS | `test_dialog_resolution.py::test_ca30_ca31_desvio_se_responde_y_el_dialogo_sigue_vivo` |
| CA-31 la pregunta pendiente se reformula | PASS | `::test_ca30_ca31_desvio_se_responde_y_el_dialogo_sigue_vivo`, `::test_ca31_la_repregunta_no_se_cuelga_dos_veces_ni_al_propio_dialogo`, `::test_h2_un_resultado_denegado_no_lleva_la_repregunta_colgada` |
| CA-32 el desvío no reinicia el TTL | PASS | `test_dialog_resolution.py::test_ca32_el_desvio_no_reinicia_el_contador`, `test_dialog_state.py::test_ca32_touch_question_no_mueve_el_reloj`, `::test_ca32_fill_si_mueve_el_reloj` |

### Recuento

| | Cantidad |
|---|---|
| PASS (cobertura verificada) | **27** |
| PASS con observación (`PASS*`) | **3** — CA-14, CA-19, CA-27 |
| MANUAL (no verificable en unidad) | **1** — CA-16 |
| **FAIL (sin cobertura)** | **1** — CA-29 |
| Total | 32 |

---

## Verificación anti-vacuidad (15 mutaciones)

Cada mutación rompe deliberadamente el código que un criterio protege. "DETECTADA" significa que
el test correspondiente falló, es decir que la aserción es de carga.

| Mutación aplicada | Resultado |
|---|---|
| `_hands_free_active()` → `return True` | DETECTADA (CA-23, 1 failed) |
| `_speak_response()` abre la ventana antes de despachar el TTS | DETECTADA (CA-26, 1 failed) |
| `ConversationWindow.accepts()` ignora `listen_started_at >= opened_at` | DETECTADA (CA-14, 1 failed) |
| `_on_resolve_done()` habla ANTES de liberar `_resolution_in_flight` | DETECTADA (CA-15, 1 failed) |
| `_try_pending_dialog()` intercepta con el store vacío | DETECTADA (CA-09, **7 failed** — la red de seguridad de los 7 resolvers funciona) |
| `_try_intent()` manda `params["channel"] = "telegram"` al gate | DETECTADA (CA-18b, 1 failed — **la aserción de canal es de carga**) |
| `_execute_completed_dialog()` acepta cualquier acción | **VACUIDAD — sigue pasando** (ver #2) |
| `SPEECH_TRUNCATE_THRESHOLD/AT` → 300/280 | **VACUIDAD — 11 passed** (ver #1) |
| `_append_pending_question()` sin el guard `result.denied` | DETECTADA (H2, 1 failed) |
| `DialogStore.open()` acepta `user_id` vacío | DETECTADA (H3, 1 failed) |
| `fill()` no mueve `last_progress_at` | DETECTADA (CA-32, 1 failed) |
| `DialogStore.get()` nunca expira | DETECTADA (CA-07, 1 failed) |
| `_try_task_tool()` dispara `task_create` sin mirar los slots | DETECTADA (CA-01, **6 failed**) |
| `prepare_for_speech()` no barre el marcado sobrante | DETECTADA (CA-24, 2 failed) |
| `_is_cancel_phrase()` compara por substring | DETECTADA (CA-06, 1 failed) |

**13 de 15 detectadas. 2 vacuidades.**

### Vacuidad #1 — CA-27: el umbral de 400 y el corte de 380 no están fijados

`tests/test_speech_prep.py` importa `SPEECH_TRUNCATE_THRESHOLD` y `SPEECH_TRUNCATE_AT` y los usa
**simbólicamente** en todas las aserciones. Bajar el umbral a 300 y el corte a 280 deja los 11
tests en verde, incluido el que se llama `test_ca27_umbral_de_400_no_trunca`.

CA-27 exige literalmente "mismo umbral de decisión de **400** caracteres, mismo corte en **380** al
último punto". Esos dos números son parte del criterio y hoy nadie los sostiene. Nótese que el
patrón correcto ya existe en este mismo REQ: `test_mic_window.py::test_la_duracion_vive_en_un_solo_lugar`
asevera `MIC_WINDOW_SECONDS == 15.0` y `test_dialog_state.py::test_ca07_el_ttl_por_defecto_son_tres_minutos`
asevera `DIALOG_TTL_SECONDS == 180.0`. Acá se omitió.

**El código está bien.** Verificado contra el comportamiento REAL, no contra el número de la SPEC:

```
entrada 900 chars -> salida 419 chars
'... Esta es una frase de relleno... La información completa está en su pantalla, Señor Johan.'
```

Corte en 380 al último punto, coletilla añadida DESPUÉS del corte (por eso el resultado mide más
de 400 — el baseline §4.5 midió 423 con su propia entrada, acá 419 con otra), espacio tras los tres
puntos, y `vocative()` real y no un literal. Es exactamente el pipeline de la consola de hoy. Lo
que falta es la aserción que impida que alguien lo mueva mañana sin enterarse.

### Vacuidad #2 — CA-19: el guard de `_execute_completed_dialog()` es código muerto para los tests

La desviación #9 de `desarrollo-log-021.md` añadió a `core/resolution.py::_execute_completed_dialog()`:

```python
if dialog.action != TASK_CREATE_ACTION:
    logger.warning(f"[Diálogo] acción '{dialog.action}' no cableada en v1; se descarta")
    dialog_store.cancel(user_id, channel)
    return None
```

Sustituirlo por `if False:` deja `test_ca19_*` en verde. Ningún test abre un diálogo con una acción
distinta de `task_create`, así que esa rama nunca se ejecuta en toda la suite.

La mitad principal de CA-19 **sí** está probada y es sólida: `PendingDialog` es `frozen` (probado
con `pytest.raises` sobre la asignación), el contenido de un slot no cambia `dialog.action`
(probado), y la única acción alcanzable hoy es `task_create`. Pero la segunda frase del criterio
—"en v1 la única acción alcanzable por diálogo es `task_create`"— es precisamente lo que ese guard
implementa, y nadie lo ejerce. Es el candado que evitará el desastre cuando en v2 se cablee la
segunda acción; conviene que nazca con test.

---

## Regresión

| Área revisada | Resultado |
|---------------|-----------|
| `core/resolution.py` — orden de los 7 resolvers con el store vacío | OK. `tests/test_resolution.py` intacto y en verde; los 7 `test_ca09_*` fijan el `matched_by` de cada uno, incluidos los 4 que el baseline reportó sin cobertura (`routine`, `autopilot`, `learned`, `capability`) |
| `resolve()` — los 4 consumidores | OK. `grep -rn "expects_reply"` solo aparece en `core/resolution.py` y en `tests/test_dialog_resolution.py`: ningún consumidor lo lee. `main.py`, `channels/gateway.py`, `core/orchestrator.py` y `ui/webview/bridge.py` no cambiaron su lectura del resultado |
| `tasks/task_manager.py::parse_natural_task` | OK. Cambio confirmado como *move puro* (`task_triggers` → `TASK_TRIGGERS`, `date_patterns` → `TASK_DATE_PATTERNS`). Comportamiento fijado por 4 tests nuevos de `test_task_slots.py` sobre una función que llegó al REQ con **cero** tests |
| `ui/cli.py::display_output` | OK. Llegó con **cero** tests; ahora tiene 5. La salida audible cambia solo en la limpieza (CA-27 reescrito); aplanado, umbral, corte y coletilla verificados idénticos contra la medición real |
| Telegram — `/nueva`, `/tareas`, `/completar` | OK. No pasan por `resolve()`, van directo a `execute_tool()`: el diálogo no los intercepta. `test_telegram_bot.py::test_ca10_*` intactos y en verde |
| Discord — `gateway.process()` → `resolve()` | OK vía `test_ca11_mismo_dialogo_en_los_3_canales[DISCORD]`. Sin `tests/test_discord_bot.py` en el repo, la cobertura de Discord es la del camino común, no la del bot |
| `voice/wake_word.py` — camino sin ventana | OK. `test_mic_window.py::test_sin_ventana_el_comportamiento_es_el_de_siempre` y `::test_la_frase_con_wake_word_sigue_funcionando_con_la_ventana_cerrada`; el parámetro `conversation_window` es opcional con default `None` |
| `ui/tts_engine.py` — `speak()`/`is_speaking()`/`signal_barge_in()`/`_speak_edge()` | OK, sin tocar. Solo se agregó `prepare_for_speech()` y sus dos constantes |
| Guard `_resolution_in_flight` | **NO se debilitó.** Sigue en `send_message()` (línea 236) y en `_on_voice_command()` (línea 779), con la misma condición. El test existente conserva su aserción y solo cambió de nombre y docstring |
| `requirements.txt` | Sin cambios. Ninguna dependencia nueva |

---

## Las 7 pruebas de seguridad obligatorias de `security-audit-021.md`

| # | Prueba exigida | Test | Estado |
|---|---|---|---|
| 1 | Slot `que` + frase YELLOW → se guarda como título, `dispatch` NO se invoca | `test_ca18_a_fail_safe_con_el_slot_que_pendiente` (fixture `sin_dispatch` que **lanza** si se llama), `test_ca19_el_contenido_de_un_slot_nunca_cambia_la_accion_destino` | OK |
| 2 | Slot `cuando` + frase YELLOW → se desvía, gate con el canal REAL | `test_ca18_b_desvio_yellow_pasa_por_el_gate_con_el_canal_real` — espía sobre el `require_confirmation()` real sin alterar su veredicto; asevera `resolve_channel(llamada["channel"]) == DESKTOP` **y** `denied is True`. Mutación de canal → DETECTADA | OK |
| 3 | Acción RED con diálogo abierto → sigue bloqueada | `test_ca18_b_desvio_red_sigue_bloqueado_por_el_fail_closed` | OK |
| 4 | Fuga entre usuarios / entre canales | `test_ca08_aislamiento_entre_usuarios_del_mismo_canal`, `test_ca08_aislamiento_entre_canales_del_mismo_usuario`, `test_ca08_aislamiento_por_usuario_y_canal` | OK |
| 5 | `open()` con `user_id` vacío lanza | `test_h3_open_rechaza_user_id_vacio` (`""` y `None`). Mutación → DETECTADA | OK |
| 6 | `denied=True` sin repregunta colgada | `test_h2_un_resultado_denegado_no_lleva_la_repregunta_colgada`. Mutación → DETECTADA | OK |
| 7 | Mismo `matched_by` que hoy para los 7 resolvers | Los 7 `test_ca09_*`. Mutación → 7 failed | OK |

**7/7 presentes y de carga.** Además, las 8 prohibiciones de la auditoría se verificaron en el
código: el guard no se debilitó (1), `DialogStore._channel_value()` solo lee su argumento (2), el
gate sigue dentro de `execute_tool()`/`dispatch()` (3), `PendingDialog` es `frozen` (4), cero
`sqlite3` y cero `open()` de archivo en `core/dialog_state.py` (5), `test_no_hay_hilos_ni_timers`
recorre el AST de `voice/mic_window.py` y prohíbe `Timer`/`Thread`/`wait`/`join`/`sleep` (6),
H2 (7) y H3 (8).

---

## Revisión de las desviaciones declaradas por `orion-dev`

`desarrollo-log-021.md` declara 10 decisiones de implementación. Veredicto de cada una:

| # | Desviación | ¿Razonable? | ¿Probada? | ¿Rompe algún criterio? |
|---|---|---|---|---|
| 1 | `PendingDialog` es `frozen=True` (la arquitectura lo dejaba mutable) | Sí — endurecimiento sobre el diseño, exigido por la prohibición 4 | Sí: `test_ca19_la_accion_destino_no_tiene_setter`, `test_pending_dialog_es_inmutable` | No. Refuerza CA-19 |
| 2 | `_speech_seq`/`_speech_done_seq` como par de contadores en vez de comparar un número capturado | Sí — la arquitectura §5.5 prohibía la closure y un método vinculado no recibe su número de locución | Sí: `test_r10_solo_la_locucion_mas_reciente_arma_la_ventana` | No |
| 3 | `expired_now()` al PRINCIPIO del `while`, no al final | Sí, y es una corrección real: varias ramas del cuerpo salen por `continue` (silencio, texto vacío, `RequestError`), justo el caso más frecuente. Al final la línea no se ejecutaría casi nunca | Sí: `test_ca13_al_vencer_la_ventana_el_estado_vuelve_a_listening_wake` | No — sin esto CA-13 fallaría en vivo |
| 4 | `_COMPOUND_DATE_PATTERNS` local, sin tocar `TASK_DATE_PATTERNS` | Sí — mantiene el move puro de `task_manager.py` | Sí: `test_scan_pasado_manana_no_deja_pasado_como_contenido` | No |
| 5 | `has_content_tokens()` exportada y reusada por `_answers_slot("que", …)` | Sí — evita una segunda definición de "contenido" | Sí: `test_has_content_tokens` + el camino de CA-18(a) | No |
| 6 | Cancelación por coincidencia EXACTA, no substring | Sí, y es necesaria: con `in`, "cancela la reunión del lunes" cancelaría el diálogo en vez de ser el título | Sí: `test_ca06_cancelar_exige_coincidencia_exacta`. Mutación a substring → DETECTADA | No — protege CA-06 |
| 7 | `_as_inline_question()` baja la inicial tras `¿` | Sí — cosmético, alineado con "con naturalidad" de CA-31 | Sí: `test_ca30_ca31_…` asevera `"Por cierto, ¿pregunta por que?"` en minúscula | No |
| 8 | `prepare_for_speech()` también barre `~` y backticks | Sí — `format_task_list()` usa `~` para el tachado | Sí: `test_ca24_html_y_markdown_variados` | No. Supera CA-24 |
| 9 | **`_execute_completed_dialog()` rechaza toda acción que no sea `task_create`** | Sí — falla en sentido seguro en vez de improvisar; es la lectura correcta de "v1 solo cablea `task_create`" | **NO — ver Vacuidad #2** | No rompe CA-19: lo *refuerza*. Pero deja el refuerzo sin verificar |
| 10 | `_load_prior_turns()` valida que el contexto sea `list` de `dict` | Sí — protege del `MagicMock` del test y de una fila corrupta de `agent_context.db` | Sí: `test_ca22_un_fallo_de_la_db_de_contexto_no_tumba_el_loop` | No |

**Ninguna desviación rompe un criterio.** La única con problema es la #9, y el problema es de
cobertura, no de comportamiento.

---

## Lo que queda para la prueba manual de Johan

### R1 — el agente escuchándose a sí mismo (CA-14 + CA-26). El riesgo más grave del REQ.

**Lo que SÍ está probado en unidad —** el doble candado, verificado con mutación:

1. **La ventana solo se arma en el `on_done` de la tarea de voz.** `_speak_response()` despacha
   `speak` por `run_async` y NO abre nada; la apertura ocurre en `_on_speech_done` →
   `_finish_speech()` → `_open_conversation_window()`. Mutación que la abre antes → test falla.
   Además `_finish_speech()` no abre nada mientras quede otra locución en vuelo
   (`_speech_done_seq < _speech_seq`), probado con dos locuciones solapadas.
2. **Un chunk que empezó a capturarse antes de `opened_at` se rechaza.** `listen_started_at` se
   marca ANTES de `recognizer.listen()` y `accepts()` exige `listen_started_at >= opened_at`.
   Mutación que lo ignora → test falla.
3. **Nunca se sondea `is_speaking()`** en ninguna línea nueva — el problema que la SPEC documenta
   (la bandera `_speaking` se pone en `True` DESPUÉS de sintetizar el mp3, hasta 15 s tarde) se
   evita por construcción, no por mitigación.
4. **`consume()` cierra la ventana tras UNA frase**, así que un ruido continuo no encadena
   ejecuciones durante los 15 s.

**Lo que NO puede probarse en unidad, y hay que mirar en vivo:**

- El cruce real de los 3 hilos: el hilo de Qt (bridge), el worker de `run_async` (donde corre
  `speak()`) y el hilo del micrófono (`listen_for_wake_word`). Todos los tests fabrican el `Bridge`
  con `Bridge.__new__(Bridge)` y llaman a los métodos en el hilo del test. **El orden real de
  entrega del `on_done` de Qt no está ejercido por ningún test.**
- La **latencia de reproducción del altavoz**: `on_done` dispara cuando `_play_mp3_windows()`
  retorna. Si el driver de audio libera antes de que el último fonema salga por el parlante, la
  ventana abre con el agente todavía sonando. Es el escenario exacto de R1 y ningún test lo cubre.
- **Qué escucha el micrófono en la sala**: eco del parlante, TV, otra persona. La aritmética de
  `opened_at` no sabe de acústica.

**Cómo probarlo (2 minutos, con auriculares y sin ellos):** correr el caso de referencia completo
con el manos libres activo y quedarse **callado** los 15 s posteriores a cada respuesta. Si
aparece una tarea que nadie pidió, o si el segundo turno se llena solo con palabras de la propia
respuesta del agente, R1 se materializó. Con auriculares el eco desaparece: si falla solo sin
auriculares, es acústica y se ajusta con `MIC_WINDOW_SECONDS`; si falla con auriculares, es el
encadenamiento y vuelve a `orion-dev`.

### CA-16 — el caso de referencia de punta a punta

Los 3 turnos, las 3 respuestas **pronunciadas en voz alta**, sin repetir la wake word, y la tarea
"Llamar al contador" creada para mañana 09:00. Cada pieza está probada por separado; la cadena
completa en el webview real no. Es el criterio que solo Johan puede cerrar.

### CA-15 — la línea de log

El criterio pide que en el log del caso de referencia completo **no aparezca**
`"Comando por voz ignorado (resolución en curso)"`. El test prueba el invariante estructural que lo
garantiza (cuando se abre la ventana, el guard ya está libre), que es más fuerte que buscar una
cadena. Pero la ausencia literal de esa línea en el log real solo se ve corriendo el caso.

### R2/R6 — el ritmo

Los 15 s de ventana y la llamada al LLM para redactar cada repregunta pueden hacer que todo
funcione y aun así se sienta lento. `MIC_WINDOW_SECONDS` (`voice/mic_window.py`) y
`DIALOG_TTL_SECONDS` (`core/dialog_state.py`) son constantes con nombre en un único lugar, para
ajustarlos sin rediseñar. (Ver Vacuidad #1: `SPEECH_TRUNCATE_THRESHOLD`/`SPEECH_TRUNCATE_AT`
también deberían quedar fijados por test, como estos dos.)

---

## Veredicto: **FAIL**

**30 de 32 criterios con cobertura verificada** (27 PASS + 3 PASS con observación), 1 solo
verificable en la prueba manual (CA-16), y **1 sin ninguna cobertura: CA-29**.

Que quede claro lo que NO está mal: **no hay ningún fallo de comportamiento**. No hay regresiones,
la compilación pasa, las 7 pruebas de seguridad obligatorias existen y son de carga, las 8
prohibiciones de la auditoría se respetaron, el guard `_resolution_in_flight` no se debilitó, y
13 de 15 mutaciones fueron detectadas por la suite — es un trabajo de test sólido, muy por encima
de lo habitual. El REQ vuelve por **tres huecos de cobertura**, todos en `tests/`, ninguno en
producción.

### Lo que `orion-dev` tiene que hacer

**1. CA-29 — FAIL, es el bloqueante real. Falta el test entero.**

CA-29 tiene dos mitades y ninguna está cubierta: que `signal_barge_in()` corta la locución, y que
**el diálogo pendiente sobrevive a la interrupción** (interrumpir no es cancelar). La segunda mitad
es la que introduce este REQ y es perfectamente testeable en unidad. Sugerencia, en
`tests/test_dialog_resolution.py`:

```python
def test_ca29_el_dialogo_sobrevive_al_barge_in(preguntas, spy_execute_tool, sin_llm):
    """CA-29: interrumpir al agente mientras habla NO cancela el diálogo pendiente."""
    from ui.tts_engine import signal_barge_in

    _abrir_dialogo(preguntas, spy_execute_tool)          # queda el "qué" pendiente
    signal_barge_in()                                     # el usuario corta la locución

    assert dialog_store.get("u1", ChannelType.DESKTOP) is not None
    avance = resolve("llamar al contador", ChannelType.DESKTOP, user_id="u1")
    assert avance.matched_by == "pending_dialog"          # el hilo siguió donde estaba
```

Y la mitad del barge-in en `tests/test_mic_window.py` o `tests/test_wake_word.py`: que con
`is_speaking()` devolviendo `True`, el bucle de `listen_for_wake_word()` llama a
`signal_barge_in()`. Hoy **no hay una sola ocurrencia de "barge" en toda la suite** — es también
la única mitad de CA-29 que es comportamiento pre-existente, así que el test vale como red.

**2. CA-27 — fijar el umbral y el corte (Vacuidad #1).** Dos líneas en
`tests/test_speech_prep.py`, mismo patrón que `test_la_duracion_vive_en_un_solo_lugar`:

```python
def test_ca27_el_umbral_y_el_corte_son_los_de_la_consola_de_hoy():
    assert SPEECH_TRUNCATE_THRESHOLD == 400
    assert SPEECH_TRUNCATE_AT == 380
```

**3. CA-19 — ejercer el guard de `_execute_completed_dialog()` (Vacuidad #2).** Abrir un diálogo
directamente en el store con `action="shutdown_pc"`, llenar los dos slots vía `resolve()`, y
aseverar que `execute_tool` **no** se invoca, que el diálogo queda cancelado y que la frase se
resuelve por el camino normal.

Ninguno de los tres exige tocar código de producción. Con eso, el REQ pasa a `orion-qa`.

---

**Nota de salida:** `TEST FAIL | REQ-021 | criterios=30/32 verificados (1 FAIL: CA-29 sin test, 1 MANUAL: CA-16) | 2 vacuidades (CA-27, CA-19) | siguiente=@orion-dev`
