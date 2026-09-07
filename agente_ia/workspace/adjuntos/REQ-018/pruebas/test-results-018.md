# Resultados de prueba REQ-018 — Confirmación conversacional para `/eliminar` en Telegram

**Agente:** orion-tester | **Fecha:** 2026-09-06 | **Precede a:** orion-qa

## Nota de contexto

El REQ estuvo detenido en `EN_PRUEBAS` desde 2026-08-21 (pipeline no continuado, no
abandonado). Al retomarlo se encontró que el código de REQ-018 ya está en `main`
(commit `1c895f6`, "feat: mejoras de agentes, canales y confirmaciones (REQ-018 a
REQ-020)", 2026-08-26, junto con REQ-019/REQ-020), pese a que `.claude/rules/git.md`
establece que ningún agente ejecuta `git commit`. Se deja constancia para el humano —
no es un hallazgo de este agente ni bloquea el veredicto de pruebas, pero excede el
mandato de `orion-tester` corregirlo.

También se detectó que `CHANNEL_ACTION_EXCEPTIONS` (el mecanismo que introdujo este
REQ) ya tiene 3 entradas más (`pc_type`, `pc_key`, `pc_click`) agregadas por un REQ
posterior de control de escritorio remoto. No es una desviación de REQ-018 — es el
mecanismo quirúrgico funcionando exactamente como fue diseñado, y el test dinámico de
CA-03 (Hallazgo C) las contempla explícitamente sin perder cobertura sobre el resto
de las acciones YELLOW.

## Compilación

```
python -m py_compile channels/telegram_bot.py channels/telegram_confirmation_adapter.py core/security_manager.py
```
- Resultado: **OK**, sin errores.

## Tests existentes

```
cd agente_ia && python -m pytest tests/ --tb=short -v
```
- Resultado: **1762 passed, 1 failed**.
- El único fallo es `tests/test_task_slots.py::test_la_hora_dicha_se_respeta` —
  **no es una regresión de REQ-018**. Es un test dependiente de la hora del día
  ("recuerdame llamar al banco hoy a las 5" — si se corre después de las 17:00, el
  parser de fecha natural en `tasks/task_manager.py::_parse_natural_date()` interpreta
  "las 5" como ya pasado y rueda al día siguiente). Verificado:
  - El commit de REQ-018/019/020 (`1c895f6`) no tocó `tests/test_task_slots.py` ni
    `tasks/task_manager.py` (solo `tasks/task_scheduler.py` dentro de `tasks/`).
  - Corrido en aislamiento a otra hora del día, pasa.
  - Los 2 fallos documentados en `origen/baseline-018.md` (`ModuleNotFoundError: No
    module named 'anthropic'`) ya no ocurren — el paquete está instalado en el entorno
    actual (`anthropic==0.86.0`), por cambio de entorno ajeno a este REQ.
- Nuevos fallos atribuibles a REQ-018: **ninguno**.

Suite específica de REQ-018 + regresión de CA-12, en aislamiento:
```
python -m pytest tests/test_telegram_bot.py tests/test_telegram_confirmation_adapter.py tests/test_security_manager.py tests/test_resolution.py --tb=short -q
→ 174 passed
```

## Criterios de la SPEC

| Criterio | Resultado | Nota |
|----------|-----------|------|
| CA-01 — `/eliminar` gateado vía `require_confirmation` | PASS | `cmd_eliminar()` (`channels/telegram_bot.py:613-619`) llama `require_confirmation("delete_task", ChannelType.TELEGRAM, ...)` antes de `task_manager.delete_task()`; si `confirmed` es `False` responde cancelación explícita y hace `return` sin borrar (línea 621-625). Tests: `test_ca01_cmd_eliminar_confirmado_borra_tarea`, `test_ca01_cmd_eliminar_cancelado_no_borra_tarea`. |
| CA-02 — Excepción por canal+acción, no por canal en bloque | PASS | `CHANNEL_ACTION_EXCEPTIONS: set[tuple[ChannelType,str]]` (`core/security_manager.py:107-124`) es una estructura separada de `CHANNEL_ALLOWED_LEVELS`, evaluada dentro de `is_action_allowed()` (línea 387-395) ANTES que la política general. `CHANNEL_ALLOWED_LEVELS[TELEGRAM]` sigue `[GREEN]` sin tocar (línea 74). Tests: `test_ca02_delete_task_telegram_registrado_en_channel_action_exceptions`, `test_ca02_is_action_allowed_delete_task_telegram_true_tras_excepcion`. |
| CA-03 — Ninguna otra YELLOW se vuelve alcanzable en Telegram | PASS | `test_ca03_todas_las_yellow_restantes_siguen_bloqueadas_en_telegram` deriva la lista YELLOW dinámicamente de `security_manager._actions.items()` (fix de Hallazgo C, no una copia a mano) y verifica `is_action_allowed(...) is False` para cada una no declarada en `CHANNEL_ACTION_EXCEPTIONS`, con guardrail `>= 15` acciones. `test_ca03_las_excepciones_declaradas_son_las_esperadas` fija el set exacto de excepciones conscientes. |
| CA-04 — Adaptador registrado, mensaje no reformulado | PASS | `TelegramConfirmationAdapter.confirm()` reenvía `message` recibido tal cual a `_send_message()` (`channels/telegram_confirmation_adapter.py:146`), sin reconstruirlo — el texto lo arma `require_confirmation()` centralmente (`core/security_manager.py:487-503`) y se registra vía `register_confirmation_adapter(ChannelType.TELEGRAM, telegram_confirmation_adapter.confirm)` en `_post_init_telegram()`. Test: `test_ca04_confirm_envia_mensaje_exacto_sin_reformular`. Nota: el texto exacto citado en SPEC-018 ("¿Estás seguro de que quieres ejecutar 'delete_task'?...") cambió desde entonces a `core/acciones_legibles.py::pregunta()` (cambio de un REQ posterior, ajeno a este) — el criterio real de CA-04 (que el adaptador no duplique/reformule) sigue cumplido igual. |
| CA-05 — Correlación con el próximo mensaje de texto | PASS | `_intercept_confirmacion_pendiente()` registrado en `group=-1` (máxima prioridad entre handlers de mensaje, antes de `handle_text`/comandos de `group=0`), llama `telegram_confirmation_adapter.resolve(user_id, text)` y corta con `ApplicationHandlerStop` si se consumió (`channels/telegram_bot.py:655-678`). `resolve()` hace `pop` de `_pending[user_id]` — se consume una sola vez. Test: `test_ca05_intercept_confirmacion_pendiente_consume_comando_y_corta_propagacion`. |
| CA-06 — Criterio de "sí" exacto, sin ambigüedad | PASS | `resolve()`: `text.strip().lower() in ("sí","si","yes","s")` (`channels/telegram_confirmation_adapter.py:205`), idéntico al resto del sistema. Tests parametrizados: `test_ca06_tokens_afirmativos_confirman`, `test_ca06_tokens_ambiguos_o_negativos_cancelan_fail_closed`. |
| CA-07 — Timeout fail-closed de 120s | PASS | `CONFIRM_TIMEOUT_SECONDS = 120` (línea 36); `pending.event.wait(timeout=...)`, si expira `confirmed = False` (nunca `True` por defecto) y el `finally` de `confirm()` hace `pop` incondicional del `_pending[user_id]` sin importar el camino de salida. Test: `test_ca07_timeout_resuelve_false_y_limpia_pending`. |
| CA-08 — No bloquea el loop de asyncio para otros usuarios | PASS | `run_telegram_bot()` incluye `.concurrent_updates(True)` en `Application.builder()` (`channels/telegram_bot.py:1059`, comentado explícitamente como fix de Hallazgo A — sin esto PTB serializa TODO el despacho de updates con `SimpleUpdateProcessor(max_concurrent_updates=1)`). `cmd_eliminar()` invoca `require_confirmation` vía `await asyncio.to_thread(...)` (línea 613), nunca en el hilo del event loop. Test: `test_ca08_confirm_corre_en_hilo_aparte_sin_bloquear_al_hilo_que_lo_lanza`. La aplicación real del flag se verificó por fuente y ya estaba respaldada por evidencia ejecutada en `security-audit-018.md` re-chequeo (`app.concurrent_updates` == 1 sin el fix, == 256 con él). |
| CA-09 — Una sola confirmación pendiente por usuario | PASS | `reserve_pending()` (`channels/telegram_confirmation_adapter.py:91-112`) es SÍNCRONA y atómica bajo `self._lock`, invocada por `cmd_eliminar()` ANTES del `await asyncio.to_thread(...)` (línea 599) — si ya hay una pendiente retorna `False` y el bot responde "Ya tenés una confirmación pendiente" sin llegar a invocar `require_confirmation` (Hallazgo E, cierra la ventana de carrera en vez de solo acotarla). Tests: `test_ca09_reserve_pending_niega_segunda_reserva_para_mismo_usuario`, `test_ca09_reserve_pending_permite_reservar_de_nuevo_tras_resolucion`, `test_ca09_reserve_pending_no_interfiere_entre_usuarios_distintos`, `test_ca09_segunda_confirmacion_pendiente_no_llama_require_confirmation`. |
| CA-10 — `/completar`, `/nueva`, `/tareas` auditados | PASS | `cmd_tareas()` usa `execute_tool("task_list", ...)` (línea 463). `cmd_nueva()`/`cmd_completar()` llaman `security_manager.require_confirmation("task_create"/"task_complete", ChannelType.TELEGRAM, ...)` directo antes de la lógica existente sin alterar el resultado observable — `require_confirmation` para GREEN solo audita y retorna `True` sin pedir confirmación (`core/security_manager.py:464-481`), consistente con "comportamiento observable idéntico". Tests: `test_ca10_cmd_tareas_usa_execute_tool`, `test_ca10_cmd_nueva_camino_feliz_ausita_y_preserva_mensaje`, `test_ca10_cmd_nueva_fallback_tarea_simple_preservado`, `test_ca10_cmd_completar_exito_audita_y_preserva_mensaje`, `test_ca10_cmd_completar_no_encontrada_mensaje_especifico_preservado`. |
| CA-11 — Clasificación de riesgo intacta | PASS | `delete_task` sigue YELLOW, `task_complete`/`task_create`/`task_list` siguen GREEN, `CHANNEL_ALLOWED_LEVELS` sin modificar. Tests: `test_ca11_channel_allowed_levels_telegram_sin_cambios`, `test_ca11_delete_task_sigue_clasificada_yellow`, `test_ca11_task_complete_create_list_siguen_green`. |
| CA-12 — Pipeline de `resolve()` intacto | PASS | `tests/test_resolution.py` corrido junto con la suite del REQ, sin modificaciones, en verde (incluido en el run de 174 tests en aislamiento). Cero cambios a `core/resolution.py` confirmados por `git show 1c895f6 --stat` (no aparece en la lista de archivos tocados). |
| CA-13 — Discord sin cambios | PASS | `channels/discord_bot.py` no aparece en los archivos modificados por el commit del REQ. Test explícito: `test_ca13_discord_bot_no_tocado_por_este_req`. |
| CA-14 — Auditoría sin caminos paralelos | PASS | `confirm()`/`require_confirmation()` usan `_log_audit()` existente con los mismos valores de `result` (`"confirmada"`, `"cancelada"`, etc.) — ningún mecanismo de auditoría nuevo. Tests: `test_ca14_eliminar_confirmado_queda_en_audit_db`, `test_ca14_nueva_y_completar_quedan_permitida_en_audit_db`. |

**14/14 criterios PASS.** Todos cuentan con al menos un test que los ejercita
directamente (no se asumió "la suite pasa" como cobertura implícita) — se verificó
además el código fuente real de `channels/telegram_bot.py`,
`channels/telegram_confirmation_adapter.py` y `core/security_manager.py` contra cada
criterio, no solo la descripción de `arquitectura-018.md`.

## Regresión

| Área revisada | Resultado |
|----------------|-----------|
| Suite completa (`pytest tests/`) | 1762 passed, 1 failed (no relacionado, ver arriba) |
| `tests/test_security_manager.py` (75 tests, incl. 6 nuevos de REQ-018) | Verde |
| `tests/test_telegram_confirmation_adapter.py` (27 tests, archivo nuevo) | Verde |
| `tests/test_telegram_bot.py` (24 tests, archivo nuevo) | Verde |
| `tests/test_resolution.py` (CA-12) | Verde |
| `tests/test_tool_registry.py::test_delete_task_yellow_sigue_bloqueado_en_lote` (regresión REQ-017 que el propio orion-dev reportó haber roto y corregido durante desarrollo) | Verde |

## Veredicto: PASS

14/14 criterios de aceptación verificados contra código real, compilación limpia, sin
regresiones atribuibles a este REQ. Listo para `orion-qa`.
