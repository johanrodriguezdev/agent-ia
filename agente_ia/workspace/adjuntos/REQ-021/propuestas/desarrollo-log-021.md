# Desarrollo REQ-021 — Conversación multi-turno real

**Agente:** orion-dev
**Fecha:** 2026-08-26
**Rama:** `feature/REQ-021-conversacion-multiturno` (creada por Johan; ningún agente ejecutó git)
**Entradas:** `spec/SPEC-021.md` (32 CA), `propuestas/arquitectura-021.md` (965 líneas),
`propuestas/security-audit-021.md`, `origen/baseline-021.md`, `REQ-021-context.md`

---

## Resultado de la suite

```
$ python -m pytest tests/ --tb=short -q
2 failed, 683 passed, 11 warnings in 30.48s
```

| | Baseline (orion-baseline) | Ahora |
|---|---|---|
| Fallan | **2** | **2** (los mismos) |
| Pasan | 560 | **683** (+123) |
| Fallos nuevos | — | **0** |

Los 2 fallos son los pre-existentes de entorno: `tests/test_llm_provider.py` hace
`patch("anthropic.Anthropic", ...)` y el paquete `anthropic` no está instalado
(comentado en `requirements.txt:70`). Zona `ai/llm_provider.py`, **fuera del alcance de
REQ-021 y no tocada**.

**Compilación:** `python -m py_compile` sobre los 13 módulos afectados → 13/13 OK.

---

## Archivos creados

### Producción (4)

| Archivo | Contenido |
|---|---|
| `agente_ia/core/dialog_state.py` | `PendingDialog` (frozen), `DialogStore` (RLock, expiración al leer), singleton `dialog_store`, `DIALOG_TTL_SECONDS = 180.0` |
| `agente_ia/core/dialog_questions.py` | `ask_question()`, `fallback_question()`, `FALLBACK_QUESTIONS` |
| `agente_ia/tasks/task_slots.py` | `SlotScan`, `scan_task_slots()`, `compose_task_sentence()`, `has_content_tokens()` |
| `agente_ia/voice/mic_window.py` | `ConversationWindow` (lock + deadline monotónico), `MIC_WINDOW_SECONDS = 15.0` |

### Tests (5)

| Archivo | Tests | Cubre |
|---|---|---|
| `agente_ia/tests/test_task_slots.py` | 20 | Fijación del comportamiento actual de `parse_natural_task` (0 tests hasta hoy), las 8 filas de §3.3, CA-02, CA-03, CA-21, decisión (d) |
| `agente_ia/tests/test_dialog_state.py` | 23 | CA-06, CA-07, CA-08, CA-19, CA-20, CA-32, H3 |
| `agente_ia/tests/test_dialog_resolution.py` | 38 | CA-01..CA-11, CA-17, CA-18 (2 escenarios), CA-19, CA-20, CA-21, CA-30, CA-31, CA-32, H2 |
| `agente_ia/tests/test_speech_prep.py` | 11 | CA-24, CA-27 (incluida la regresión de `ui/cli.py`, 0 tests hasta hoy) |
| `agente_ia/tests/test_mic_window.py` | 16 | CA-12, CA-13, CA-14, prohibición 6 (sin hilos ni timers) |

## Archivos modificados

### Producción (8)

| Archivo | Cambio |
|---|---|
| `agente_ia/core/resolution.py` | `expects_reply` en `ResolutionResult`; `_try_pending_dialog` + entrada 0 de `RESOLVERS`; rama `create` de `_try_task_tool` (scan antes de ejecutar); post-hook `_append_pending_question()` en `resolve()`; helpers `_answers_slot`, `_is_cancel_phrase`, `_is_question_phrase`, `_execute_completed_dialog`, `_as_inline_question` |
| `agente_ia/tasks/task_manager.py` | **Solo el move puro** de `task_triggers` → `TASK_TRIGGERS` y `date_patterns` → `TASK_DATE_PATTERNS` a constantes de módulo, con el comentario cruzado de la divergencia deliberada. `parse_natural_task` **no cambia de comportamiento** (fijado por test) |
| `agente_ia/core/reasoning_loop.py` | `CONTEXT_TURNS = 5`; `prior_turns` en `_build_prompt()`; `_load_prior_turns()`; extracción de `_append_history_lines()` |
| `agente_ia/voice/wake_word.py` | Parámetro `conversation_window=None`; `listen_started_at` antes de `listen()`; rama de aceptación sin wake word; `_report_state()`; retorno a `LISTENING_WAKE` al vencer |
| `agente_ia/voice/../ui/webview/wake_word_worker.py` | `self.conversation_window`; se pasa a `listen_for_wake_word()`; `cancel()` en el `finally` |
| `agente_ia/ui/webview/bridge.py` | `_speech_seq`/`_speech_done_seq`; `_hands_free_active()`; `_speak_response()`; `_on_speech_done()`/`_on_speech_error()`/`_finish_speech()`; `_open_conversation_window()`; TTS al final de `_on_resolve_done`; ventana en `_on_resolve_error`; `cancel()` en `_stop_wake_word_worker` |
| `agente_ia/ui/tts_engine.py` | `prepare_for_speech()` + `SPEECH_TRUNCATE_THRESHOLD`/`SPEECH_TRUNCATE_AT` + import de `core.address.vocative`. `speak()`, `is_speaking()`, `signal_barge_in()` y `_speak_edge()` **sin tocar** |
| `agente_ia/ui/cli.py` | `display_output` usa `prepare_for_speech()`; se quita el import de `vocative`/`vocative_start`, ya sin uso |

### Tests (3)

| Archivo | Cambio |
|---|---|
| `agente_ia/tests/conftest.py` | Fixture `autouse` `_clear_dialog_store()` |
| `agente_ia/tests/test_wake_word_comando.py` | Rename de §7.3 (misma aserción, docstring nuevo) + **10 tests nuevos** de la pieza 8 y la ventana |
| `agente_ia/tests/test_reasoning_loop.py` | **5 tests nuevos** de CA-22 |

**`requirements.txt` NO se tocó** — el diseño no añade ninguna dependencia (emojis y markdown
con `re`; reloj y locks con `time`/`threading`; estado en un `dict` en memoria).

---

## Los 3 cambios posteriores a la arquitectura, incorporados

| # | Qué | Dónde quedó |
|---|---|---|
| **CA-23 ajustado** (decisión de Johan) | El webview pronuncia **solo con el manos libres activo**, evaluado sobre `_wake_worker is not None and not stop_event.is_set()` — nunca sobre el texto ni el canal declarado | `bridge._hands_free_active()`, consultado como primera línea de `_speak_response()`. Test `test_ca23_solo_habla_con_el_manos_libres_activo` prueba las dos ramas (0 veces sin manos libres, 1 vez con) |
| **H2** (auditoría, obligatorio) | El post-hook de CA-31 **no** se cuelga de un resultado denegado | `_append_pending_question()` empieza con `if result.denied: return result`. El diálogo **no se cancela**: la repregunta reaparece al turno siguiente. Test `test_h2_un_resultado_denegado_no_lleva_la_repregunta_colgada` |
| **H3** (auditoría, obligatorio) | `DialogStore.open()` lanza `ValueError` con `user_id` falsy | `core/dialog_state.py::open()`. Test `test_h3_open_rechaza_user_id_vacio` (`""` y `None`) |

**CA-18 (reescrito)** se implementó con su redacción actual, no la original: el test verifica los
**2 escenarios**, no que la frase peligrosa nunca se ejecute.
- `test_ca18_a_fail_safe_con_el_slot_que_pendiente`: con el "qué" pendiente, `"cierra chrome"`
  se guarda como texto del slot y `dispatch()` **no se invoca** (fail-safe deliberado).
- `test_ca18_b_desvio_yellow_pasa_por_el_gate_con_el_canal_real`: con el "cuándo" pendiente, la
  misma frase se **desvía**, se resuelve como `intent:CLOSE_APP` y `require_confirmation()` se
  evalúa con el canal real del caller (`resolve_channel(llamada["channel"]) == DESKTOP`), con el
  veredicto intacto (`denied is True`).
- `test_ca18_b_desvio_red_sigue_bloqueado_por_el_fail_closed`: una acción `RED` sigue bloqueada
  por el fail-closed de REQ-005 con el diálogo abierto.

**CA-27 (reescrito)** también en su redacción actual: la consola **gana** la limpieza de
markdown y emojis, y se preservan aplanado, umbral 400, corte en 380 al último punto y coletilla
`"... La información completa está en su pantalla" + vocative() + "."` (con el espacio tras los
tres puntos y con `vocative()`, los dos detalles que el baseline §4.5 corrigió).

---

## Las 8 prohibiciones de la auditoría — cómo se respetaron

| # | Prohibición | Verificación |
|---|---|---|
| 1 | No debilitar `_resolution_in_flight` | El guard **no se tocó**. Sigue liberándose en el mismo punto de `_on_resolve_done`; el TTS se despacha después y la ventana se arma más tarde todavía. `test_ca15_la_ventana_solo_abre_con_el_guard_ya_liberado` fija el orden. El test existente conserva su aserción (solo cambió de nombre) |
| 2 | No leer el canal de `params` ni del texto | `DialogStore._channel_value()` solo lee el argumento que ya resolvió `resolve()`. `test_ca17_el_canal_llega_al_gate_desde_el_caller_no_del_dialogo` |
| 3 | No mover el gate | `require_confirmation()` sigue dentro de `execute_tool()`/`dispatch()`. `scan_task_slots()` corre fuera del gate por ser función pura — `test_scan_task_slots_es_puro` prueba que no llama al LLM ni abre conexión |
| 4 | El slot no puede cambiar `PendingDialog.action` | `PendingDialog` es `frozen=True` (endurecimiento sobre el diseño, que lo dejaba mutable): no hay setter posible, ni siquiera por accidente. `test_ca19_la_accion_destino_no_tiene_setter` |
| 5 | No persistir el diálogo en disco | `dict` en memoria del proceso. Cero `sqlite3`, cero `open()` de archivo en `core/dialog_state.py` |
| 6 | Sin hilo de fondo ni timer para expirar | Se evalúa en `get()` y en `expired_now()`. `test_no_hay_hilos_ni_timers` recorre el AST de `voice/mic_window.py` y prohíbe `Timer`/`Thread`/`wait`/`join`/`sleep` |
| 7 | No colgar la repregunta a una denegación | H2, arriba |
| 8 | No aceptar `user_id` vacío en `open()` | H3, arriba |

## Pruebas de seguridad obligatorias (última sección de la auditoría) — las 7

1. Slot `que` + `"apaga el pc"`/`"cierra chrome"` → se guarda como título, `dispatch` no se
   invoca → `test_ca18_a_fail_safe_con_el_slot_que_pendiente`, `test_ca19_...`
2. Slot `cuando` + frase YELLOW → se desvía y el gate se evalúa con el canal real →
   `test_ca18_b_desvio_yellow_pasa_por_el_gate_con_el_canal_real`
3. Acción RED con diálogo abierto → sigue bloqueada →
   `test_ca18_b_desvio_red_sigue_bloqueado_por_el_fail_closed`
4. Dos `user_id` en el mismo canal / dos canales del mismo `user_id` → sin fuga →
   `test_ca08_aislamiento_por_usuario_y_canal`, `test_ca08_aislamiento_entre_usuarios_del_mismo_canal`,
   `test_ca08_aislamiento_entre_canales_del_mismo_usuario`
5. `open()` con `user_id` vacío lanza → `test_h3_open_rechaza_user_id_vacio`
6. `denied=True` sin repregunta colgada → `test_h2_un_resultado_denegado_no_lleva_la_repregunta_colgada`
7. Mismo `matched_by` que hoy para los 7 resolvers con el store vacío → los 7 tests `test_ca09_*`

---

## Decisiones de implementación (ajustes menores respecto de la propuesta, con motivo)

1. **`PendingDialog` es `frozen=True`** (la arquitectura §4.1 lo dejaba como `@dataclass`
   mutable). Motivo: la prohibición 4 y CA-19 exigen que no exista ningún setter de `action`;
   con un dataclass mutable eso dependía de la disciplina del código, con `frozen` es
   estructural. `fill()`/`touch_question()` construyen una instancia nueva con
   `dataclasses.replace()` y la reemplazan en el `dict` — el estado avanza igual y el
   comportamiento externo es idéntico.

2. **`_speech_seq` se implementó como par de contadores** (`_speech_seq` despachadas /
   `_speech_done_seq` terminadas) en vez de comparar un número capturado. Motivo: la
   arquitectura §5.5 pide explícitamente que la comparación viva "dentro del propio método, no
   en una closure", y un método vinculado no recibe el número de su locución. Con dos
   contadores, `_finish_speech()` arma la ventana solo cuando no queda ninguna locución en
   vuelo — misma garantía del riesgo R10, sin closures. Test `test_r10_...`.

3. **El chequeo de `expired_now()` va al PRINCIPIO del `while`**, no al final (la arquitectura
   §5.3 decía "una sola línea más al final del `while`"). Motivo: varias ramas del cuerpo del
   bucle salen por `continue` (silencio, texto vacío, `RequestError`), así que una línea al
   final no se ejecutaría en el caso más frecuente — precisamente el de "la ventana venció sin
   que nadie hablara". Al principio se evalúa siempre, con el mismo coste (~1 Hz).

4. **`_COMPOUND_DATE_PATTERNS` en `task_slots.py`**: la alternancia
   `(?:mañana|pasado mañana|hoy)` de `TASK_DATE_PATTERNS` matchea "mañana" dentro de "pasado
   mañana" y dejaba "pasado" suelto pareciendo un título. Se quita el compuesto en un paso
   previo **propio del módulo nuevo**, sin modificar `TASK_DATE_PATTERNS` (que es un move puro).
   Test `test_scan_pasado_manana_no_deja_pasado_como_contenido`.

5. **`has_content_tokens()` se expone desde `task_slots.py`** y la usa
   `_answers_slot("que", ...)`. La arquitectura decía "≥1 token de contenido" sin nombrar la
   función; exportarla evita una segunda definición de "contenido" en `core/resolution.py`.

6. **La cancelación exige coincidencia EXACTA** de la frase normalizada. La arquitectura
   listaba `_CANCEL_PHRASES` sin decir cómo se comparan. Con `in` (substring), "cancela la
   reunión del lunes" cancelaría el diálogo en vez de ser el título del recordatorio. Test
   `test_ca06_cancelar_exige_coincidencia_exacta`.

7. **`_as_inline_question()`**: la repregunta colgada de CA-31 baja a minúscula la primera
   letra tras `¿`, para que "Por cierto, ¿qué quiere que le recuerde?" sea español correcto. La
   arquitectura interpolaba la pregunta tal cual ("Por cierto, ¿Qué..."). Cambio cosmético, en
   línea con CA-31 ("con naturalidad").

8. **`prepare_for_speech()` también barre `~` y backticks sueltos**, además de `*` y `#` que
   exige CA-24: `format_task_list()` usa `~` para el tachado y sonaría igual de mal.

9. **`_execute_completed_dialog()` se separó de `_try_pending_dialog()`** (la arquitectura los
   tenía en una sola función) y **rechaza cualquier acción que no sea `task_create`**,
   cancelando el diálogo y dejando que la frase se resuelva por el camino normal. Motivo: v1
   solo cablea `task_create`; un diálogo de otra acción sería uno que nadie sabe ejecutar.
   Falla en sentido seguro en vez de improvisar.

10. **`_load_prior_turns()` valida que el contexto sea una `list` de `dict`** antes de usarlo.
    Motivo: `tests/test_reasoning_loop.py::test_ca10_...` mockea `agent_context_manager`
    completo, y sin la validación el prompt se armaría con un `MagicMock`. Además protege de
    una fila corrupta en `agent_context.db`.

### Lo que NO se hizo (respetando el "Descartado" de la arquitectura)

- No se unificaron las dos listas de triggers (§3.5). Se fijó la relación con
  `test_triggers_de_resolution_son_subconjunto_de_task_manager`.
- No se tocó el fallback de `parse_natural_task:262`. Se fijó su comportamiento actual con
  `test_fijacion_fallback_de_titulo_sin_contenido`.
- No se construyó el `dict` de la tarea a mano: el diálogo recompone la frase y ejerce el mismo
  `parse_natural_task` del camino de un solo tiro.
- No se parametrizó `prepare_for_speech()` con modos.
- No se sondea `is_speaking()` en ninguna línea nueva.
- No se abre ninguna escucha ni ningún `sr.Microphone()` nuevo.
- No se añadió un cuarto estado de wake (`"CONVERSATION"`): se reusa `AWAKE`. Cero cambios en
  JS y CSS.
- No se implementó cola de comandos de voz diferidos.
- No se leyó `expects_reply` en ningún consumidor (CA-10): los 4 siguen sin cambiar una línea.

---

## Riesgos vivos para la prueba manual de Johan

1. **R1 — que el agente se escuche a sí mismo.** El doble candado está implementado y probado en
   unidad (la ventana solo se arma en el `on_done` del TTS; un chunk que empezó antes de
   `opened_at` se rechaza), pero cruza 3 hilos reales que ningún test puede reproducir. Es lo
   primero que hay que mirar en vivo.
2. **R2 + R6 — el ritmo.** Los 15 s de ventana y la llamada al LLM para redactar la repregunta
   pueden hacer que el caso de referencia funcione y aun así se sienta lento. `MIC_WINDOW_SECONDS`
   (`voice/mic_window.py`) y `DIALOG_TTL_SECONDS` (`core/dialog_state.py`) son constantes con
   nombre en un único lugar, justamente para ajustarlos sin rediseñar.
3. **R3 — cerrado por diseño** con el ajuste de CA-23: el webview no habla si el manos libres
   está apagado.
4. **Deuda P2 (H4 de la auditoría)** — la voz del webview sigue resolviendo como `DESKTOP` y no
   como `VOICE`. Sigue fuera de alcance. Las 2 condiciones técnicas que la auditoría puso están
   cumplidas (`consume()` limita a una frase por ventana; `MIC_WINDOW_SECONDS` en un solo
   lugar); la tercera —**convertir P2 en REQ propio**— es una acción de Johan, no de este agente.

---

## Nota de salida

`DEV OK | REQ-021 | archivos=20 (9 nuevos + 11 modificados) | tests_pasan=SI (2 failed pre-existentes, 683 passed) | siguiente=@orion-tester`


---

# Vuelta 2 — cierre de los 3 huecos de cobertura de `orion-tester`

**Agente:** orion-dev
**Fecha:** 2026-08-26
**Entrada:** `pruebas/test-results-021.md` (veredicto FAIL: 30/32 criterios verificados,
1 FAIL sin cobertura + 2 vacuidades)
**Alcance:** SOLO tests. **Cero líneas de código de producción modificadas.**

## Resultado de la suite

```
$ python -m pytest tests/ --tb=short -q
2 failed, 693 passed in 39.86s
```

Los 2 fallos siguen siendo los mismos pre-existentes de entorno
(`tests/test_llm_provider.py`, `anthropic` no instalado — `requirements.txt:70`).
Cero regresiones.

## Los 3 huecos, cerrados

### 1. CA-29 — FAIL (sin ningún test) -> 6 tests

`grep -rin "barge" tests/` daba CERO resultados en toda la suite. Las dos mitades del
criterio quedan cubiertas, y la del diálogo —la que introduce este REQ— con dos ángulos.

| Test | Archivo | Cubre |
|---|---|---|
| `test_ca29_el_dialogo_pendiente_sobrevive_al_barge_in` | `tests/test_dialog_resolution.py` | **(b)** Señalar el barge-in no toca el diálogo: mismos `action`, `slots`, `missing`, `question` y **el mismo `last_progress_at`** (interrumpir no compra ni pierde TTL). Después el turno siguiente sigue resolviendo por `pending_dialog`. |
| `test_ca29_la_frase_que_interrumpe_la_locucion_avanza_el_dialogo` | `tests/test_dialog_resolution.py` | **(b) de punta a punta**: agente hablando + diálogo abierto -> el usuario lo corta -> el bucle real de `listen_for_wake_word()` señala el barge-in y devuelve la frase -> esa frase hace avanzar el diálogo. Micrófono y altavoz mockeados. |
| `test_ca29_el_barge_in_corta_la_locucion_en_curso` | `tests/test_mic_window.py` | **(a)** `_play_mp3_windows()` real con un `ffplay` falso: con `_barge_in` señalado se mata el proceso en el primer chequeo, sin esperar a que el audio termine solo. |
| `test_ca29_sin_barge_in_la_locucion_termina_sola` | `tests/test_mic_window.py` | Control negativo de la anterior: sin interrupción no se corta nada. |
| `test_ca29_el_bucle_de_escucha_senala_el_barge_in_mientras_el_agente_habla` | `tests/test_mic_window.py` | **(a)** El bucle de `listen_for_wake_word()` llama a `signal_barge_in()` cuando entra audio con `is_speaking()` en `True`. |
| `test_ca29_sin_locucion_en_curso_el_bucle_no_senala_barge_in` | `tests/test_mic_window.py` | Control negativo: señalar un barge-in fantasma dejaría `_barge_in` pegado hasta el `finally` de `_speak_edge()` y apagaría la locución siguiente. |

### 2. CA-27 — vacuidad #1 (los valores no estaban fijados) -> 3 tests

El archivo usaba `SPEECH_TRUNCATE_THRESHOLD`/`SPEECH_TRUNCATE_AT` **simbólicamente** en
todas sus aserciones, así que moverlos a 300/280 dejaba los 11 tests en verde — incluido
el llamado `test_ca27_umbral_de_400_no_trunca`, que se reemplazó por uno honesto.

| Test | Cubre |
|---|---|
| `test_ca27_el_umbral_y_el_corte_estan_fijados_en_400_y_380` | Fijación literal de las dos constantes. Mismo patrón que `test_la_duracion_vive_en_un_solo_lugar` (`MIC_WINDOW_SECONDS == 15.0`) y `test_ca07_el_ttl_por_defecto_son_tres_minutos` (`DIALOG_TTL_SECONDS == 180.0`) — el patrón que faltaba aplicar acá. |
| `test_ca27_el_umbral_literal_de_400_decide_el_truncado` | El mismo umbral medido sobre la salida real, con el número escrito a mano: 400 caracteres pasan enteros, 401 se truncan. Fija el valor **y** la comparación estricta. Reemplaza a `test_ca27_umbral_de_400_no_trunca`. |
| `test_ca27_el_corte_literal_de_380_medido_sobre_la_salida_real` | Medición real con las longitudes escritas a mano: 900 caracteres de entrada -> **419** de salida, prefijo de **358** (el último punto por debajo del corte de 380) + coletilla con `vocative()`. Reproduce exactamente el número que `orion-tester` midió contra el comportamiento. |

### 3. CA-19 — vacuidad #2 (el guard era código muerto para los tests) -> 2 tests

El guard `if dialog.action != TASK_CREATE_ACTION:` de `_execute_completed_dialog()`
(desviación #6/#9) no lo ejercía ningún test: ninguno abría un diálogo con una acción
distinta de `task_create`.

| Test | Cubre |
|---|---|
| `test_ca19_una_accion_no_cableada_no_se_ejecuta_y_la_frase_sigue_el_camino_normal` | Diálogo abierto directamente en el store con `action="shutdown_pc"`, los 2 slots llenados vía `resolve()`. Al completarse: `execute_tool` **no** se invoca, `dispatch()` nunca recibe `shutdown_pc`, el diálogo queda **cancelado**, y la frase se resuelve por el orden normal de `RESOLVERS` sin repregunta colgada. |
| `test_ca19_el_mismo_dialogo_con_task_create_si_ejecuta` | Contraste: idéntico salvo la acción destino. Si el guard dejara pasar cualquier acción, los dos tests darían el mismo resultado. |

## Verificación por mutación (hecha por `orion-dev`, no delegada)

Cada test nuevo se verificó invirtiendo el comportamiento que dice cubrir. Las mutaciones
se aplicaron y **revirtieron una por una**, con verificación de restauración byte a byte
después de cada una. Nunca se usó git para restaurar (el árbol tiene 49 archivos sin
commitear ajenos al REQ).

| # | Mutación al código de producción | Resultado |
|---|---|---|
| M1 | `SPEECH_TRUNCATE_THRESHOLD` 400->300 y `SPEECH_TRUNCATE_AT` 380->280 | **3 failed** — exactamente los 3 tests nuevos de CA-27. Los 10 pre-existentes siguen en verde: confirma la vacuidad que reportó `orion-tester` y que los nuevos la cierran. |
| M2 | `if dialog.action != TASK_CREATE_ACTION:` -> `if False:` (la mutación literal de `orion-tester`) | **1 failed** — `test_ca19_una_accion_no_cableada...`. Antes de esta vuelta: 0 failed. |
| M3 | El bucle de `listen_for_wake_word()` nunca señala el barge-in (`if is_speaking():` -> `if False:`) | **2 failed** — el test del bucle y el de punta a punta. |
| M4 | `_play_mp3_windows()` no mata el proceso al detectar `_barge_in` | **1 failed** — `test_ca29_el_barge_in_corta_la_locucion_en_curso`. |
| M5 | `signal_barge_in()` además cancela el diálogo pendiente | **1 failed** — `test_ca29_el_dialogo_pendiente_sobrevive_al_barge_in`. Es la inversión exacta de "interrumpir no es cancelar". |
| M6 | Guard invertido: `if dialog.action == TASK_CREATE_ACTION:` | **3 failed** — los 2 nuevos de CA-19 más el pre-existente. |
| M7 | El bucle señala el barge-in siempre (`if True:`) | **1 failed** — el control negativo `test_ca29_sin_locucion_en_curso_...`. |
| M8 | La reproducción se corta siempre (`if True:`) | **1 failed** — el control negativo `test_ca29_sin_barge_in_la_locucion_termina_sola`. |

**8 de 8 mutaciones detectadas.** Ninguna quedó viva.

## Decisiones de implementación de esta vuelta

1. **`spy_dispatch`, fixture nueva en `tests/test_dialog_resolution.py`.** El test del guard
   de CA-19 necesita que la frase de cierre (`"mañana a las 9"`) siga el camino normal, y ese
   camino termina en `dispatch()`. Ejecutarlo de verdad no aporta nada y sí cuesta: el
   clasificador manda esa frase a `FIND_LARGEST` con `path="~"`, que **recorre el disco entero**
   (el test tardaba >5 min). La fixture espía `dispatch()` sin ejecutar la acción, y el test
   asevera sobre lo que importa — que `shutdown_pc` nunca llega ahí. Es distinta de la
   `sin_dispatch` existente, que aborta ante cualquier llamada: acá `dispatch()` **sí** debe
   invocarse, es la prueba de que la frase siguió el camino normal.
2. **CA-29 repartido en dos archivos, no en uno nuevo.** La mitad (b) vive en
   `test_dialog_resolution.py`, donde ya están las fixtures del diálogo (`preguntas`,
   `spy_execute_tool`, `sin_llm`, `_abrir_dialogo`); la mitad (a) en `test_mic_window.py`, que
   es donde vive la pieza 6. Un archivo nuevo habría exigido duplicar 4 fixtures. Cada bloque
   lleva un comentario de cabecera que apunta al otro.
3. **`monkeypatch.setattr(tts, "_barge_in", False)` en todo test que lo toque.** `_barge_in`
   es un global de proceso que en producción solo se limpia en el `finally` de `_speak_edge()`.
   Sin `monkeypatch` (que guarda y restaura), un test que lo señalara dejaría el siguiente
   con la locución cortada de entrada. Mismo criterio que la fixture `_clear_dialog_store`
   de `conftest.py`.
4. **Los controles negativos (M7, M8) son deliberados.** Un test que solo comprueba "se cortó"
   sigue en verde si el sistema corta SIEMPRE — y cortar una locución que nadie interrumpió
   deja `_barge_in` pegado y apaga la locución siguiente. El par afirmativo/negativo es lo que
   convierte la aserción en carga real.
5. **No se tocó ninguna línea de producción.** Se verificó explícitamente al terminar
   (`SPEECH_TRUNCATE_THRESHOLD = 400`, `SPEECH_TRUNCATE_AT = 380`, el guard de
   `_execute_completed_dialog()`, `if _barge_in:` de `_play_mp3_windows()` y `if is_speaking():`
   de `listen_for_wake_word()` intactos). Ningún test correcto reveló un bug real: los 8 tests
   nuevos pasaron a la primera contra el código tal como `orion-dev` lo dejó en la vuelta 1.

## Conteo de tests por archivo (actualiza la tabla de la vuelta 1)

| Archivo | Vuelta 1 | Vuelta 2 | Delta |
|---|---|---|---|
| `tests/test_dialog_resolution.py` | 38 | **42** | +4 |
| `tests/test_mic_window.py` | 16 | **20** | +4 |
| `tests/test_speech_prep.py` | 11 | **13** | +3 nuevos, -1 reemplazado |

## Verificacion de integridad del arbol tras las mutaciones

El arnes de mutacion reescribe el archivo entero, asi que se comprobo explicitamente que
los 5 puntos mutados quedaron con su texto original
(`SPEECH_TRUNCATE_THRESHOLD = 400`, `SPEECH_TRUNCATE_AT = 380`, el `if _barge_in:` de
`_play_mp3_windows()`, el guard `if dialog.action != TASK_CREATE_ACTION:` y el
`if is_speaking():` de `listen_for_wake_word()`), y `py_compile` sobre los 3 modulos de
produccion mutados + los 3 archivos de test = 6/6 OK.

Un detalle que conviene dejar anotado para `orion-qa`: el arnes escribe con finales de
linea LF, y `ui/tts_engine.py`, `core/resolution.py` y `voice/wake_word.py` quedaron en LF
en el working tree. **No es un cambio de contenido y no aparece en el diff**: el repo tiene
`core.autocrlf=true`, asi que git normaliza a LF en el indice de todos modos (el propio git
lo avisa con "LF will be replaced by CRLF the next time Git touches it"). Contrastado
ademas contra el diff real, que sigue siendo el de la vuelta 1 y no una reescritura
completa: `core/resolution.py` 244+/3-, `ui/tts_engine.py` 95+/1-, `voice/wake_word.py`
100+/12- — no 589/589, 191/191 ni 278/278. Los archivos LF conviven ya en el repo desde
antes de este REQ (40 de 163 `.py`, entre ellos `core/address.py`, `core/security_config.py`
y todo `ui/webview/`), incluidos `core/dialog_questions.py` y `tasks/task_slots.py`, que
esta vuelta no toco. Las unicas inspecciones de git de esta vuelta fueron de SOLO LECTURA
(`git config --get`, `git diff --numstat`) y con este unico fin; no se ejecuto `git add`,
`git commit` ni `git push`.

---

## Mensaje de commit sugerido (actualizado tras la vuelta 2)

Cubre el REQ entero: la produccion de la vuelta 1 mas los tests de la vuelta 2, porque el
commit todavia no se hizo. **NO ejecutado.** Sigue pendiente de `orion-qa` y de la prueba
manual de Johan, segun `.claude/rules/git.md`.

```
feat(REQ-021): conversacion multi-turno real (slot filling + ventana de microfono)

- core/dialog_state.py: PendingDialog (frozen) + DialogStore por (user_id, canal),
  expiracion al leer a los 180 s, sin hilos ni timers
- core/dialog_questions.py: repregunta redactada por el LLM con respaldo fijo natural
- tasks/task_slots.py: scan_task_slots() puro y determinista — detecta el "que" y el
  "cuando" que faltan sin consumir LLM; compose_task_sentence() reusa parse_natural_task
- core/resolution.py: _try_pending_dialog primero en RESOLVERS; el desvio de tema se
  responde y el dialogo sigue vivo sin reiniciar su TTL
- voice/mic_window.py + voice/wake_word.py: ventana de ~15 s que acepta una frase sin
  wake word, encadenada al fin del TTS y con rechazo de audio anterior a su apertura
- ui/tts_engine.py: prepare_for_speech() unica para consola y webview — sin markdown,
  sin HTML y sin emojis, conservando umbral 400, corte en 380 y coletilla con vocative()
- ui/webview/bridge.py: el webview pronuncia la respuesta, solo con manos libres activo
  y siempre por run_async, nunca desde el hilo de la GUI
- tests: +10 netos (693 passed). CA-29 pasa de 0 tests a 6, con el dialogo sobreviviendo
  al barge-in; 400/380 y el guard de _execute_completed_dialog() quedan fijados
- Sin dependencias nuevas: requirements.txt intacto
```
