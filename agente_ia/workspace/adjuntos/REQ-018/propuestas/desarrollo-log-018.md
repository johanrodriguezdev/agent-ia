# Desarrollo REQ-018 — Confirmación conversacional para `/eliminar` en Telegram

**Agente:** orion-dev | **Fecha:** 2026-08-21 | **Precede a:** orion-tester

Implementación completa de `arquitectura-018.md` §1-§14 (diseño aprobado por Johan) + §15
(addendum de seguridad, Hallazgo A) + los 3 hallazgos no bloqueantes del re-chequeo de
`orion-security` (`pruebas/security-audit-018.md`): Hallazgo B (try/finally en `confirm()`),
Hallazgo C (lista YELLOW derivada dinámicamente en el test de CA-03), Hallazgo E
(`reserve_pending()` síncrono antes del `await` en `cmd_eliminar()`).

## Archivos modificados

- `agente_ia/core/security_manager.py` — `CHANNEL_ACTION_EXCEPTIONS: set[tuple[ChannelType,
  str]]` nuevo (única entrada: `(ChannelType.TELEGRAM, "delete_task")`), evaluado dentro de
  `is_action_allowed()` como condición OR adicional a `CHANNEL_ALLOWED_LEVELS` (CA-02).
  `CHANNEL_ALLOWED_LEVELS` sin tocar (CA-11).
- `agente_ia/channels/telegram_bot.py`:
  - `cmd_eliminar()` — pasa a llamar `telegram_confirmation_adapter.reserve_pending(user_id)`
    (síncrono, Hallazgo E) y luego `security_manager.require_confirmation("delete_task",
    ChannelType.TELEGRAM, ...)` vía `await asyncio.to_thread(...)` (CA-01, CA-08), en vez de
    `task_manager.delete_task()` directo.
  - `cmd_tareas()` — pasa a invocar `execute_tool("task_list", ...)` (CA-10, reemplazo limpio).
  - `cmd_nueva()` / `cmd_completar()` — mantienen su lógica actual sin cambios de
    comportamiento observable, precedida por `security_manager.require_confirmation(
    "task_create"/"task_complete", ChannelType.TELEGRAM, ...)` llamado directo, solo para
    auditoría (CA-10, decisión §3 de la arquitectura, ya aprobada por Johan).
  - `_intercept_confirmacion_pendiente()` — handler nuevo, registrado en `group=-1`,
    intercepta cualquier mensaje de texto (incluidos comandos) cuando el usuario tiene una
    confirmación pendiente (CA-05).
  - `_post_init_telegram()` — callback nuevo, registra el adaptador de Telegram vía
    `register_confirmation_adapter()` dentro del event loop ya corriendo.
  - `run_telegram_bot()` — `Application.builder()` ahora incluye `.concurrent_updates(True)`
    (Hallazgo A) y `.post_init(_post_init_telegram)`; se agrega
    `app.add_handler(MessageHandler(filters.TEXT, _intercept_confirmacion_pendiente),
    group=-1)` antes de los demás handlers.
- `agente_ia/tests/test_security_manager.py` — 6 tests nuevos (CA-02, CA-03/Hallazgo C, CA-11,
  regresión de `proactive_trigger`).

## Archivos nuevos

- `agente_ia/channels/telegram_confirmation_adapter.py` — `TelegramConfirmationAdapter`
  completo (§5 de la arquitectura), con los Hallazgos B y E ya incorporados desde el diseño
  inicial (ver "Decisiones de implementación").
- `agente_ia/tests/test_telegram_confirmation_adapter.py` — 27 tests nuevos (CA-04 a CA-09,
  Hallazgo B, Hallazgo E, aislamiento de `contextvars` entre usuarios concurrentes).
- `agente_ia/tests/test_telegram_bot.py` — 24 tests nuevos (CA-01, CA-05 casos borde, CA-08/
  Hallazgo A, CA-09/Hallazgo E, CA-10, CA-13, CA-14). Primera suite de tests de este módulo
  (`baseline-018.md` confirmó cero cobertura previa).

## Dependencias agregadas

Ninguna. `python-telegram-bot==20.7` ya estaba en `requirements.txt` (línea 64, como
dependencia opcional comentada) y confirmado instalado en el entorno
(`python -c "import telegram; print(telegram.__version__)"` → `20.7`). Sin cambios a
`requirements.txt`, tal como indicó el handoff.

## Decisiones de implementación

1. **Hallazgos B y E se integraron juntos desde el diseño inicial del adaptador, no como
   parches separados.** La arquitectura original (§5.2) hacía la reserva de `_pending`
   *dentro* de `confirm()` (ya en el hilo worker). El Hallazgo E (re-chequeo de seguridad)
   mueve esa reserva a un método síncrono nuevo, `reserve_pending()`, invocado por
   `cmd_eliminar()` **antes** de `await asyncio.to_thread(...)`. Como consecuencia directa,
   `confirm()` ya no crea ni valida duplicados — asume que `reserve_pending()` ya reservó la
   entrada, y si no la encuentra, deniega fail-closed con log de error (nunca crea una
   entrada por su cuenta, para no reabrir la ventana que el propio Hallazgo E cierra). El
   Hallazgo B (limpieza incondicional de `_pending` si el envío del mensaje lanza) se
   implementó envolviendo `_send_message()` + `pending.event.wait()` en un único
   `try/except/finally` dentro de `confirm()` — cualquier excepción se resuelve a `False`
   (nunca escapa, nunca dispara `True`), y el `finally` limpia `_pending[user_id]` sin
   importar el camino de salida (respuesta, timeout o excepción). `cmd_eliminar()` ya no usa
   `has_pending()` como chequeo previo (el método sigue existiendo, expuesto para
   diagnóstico/tests) — `reserve_pending()` es ahora la única verificación atómica real de
   CA-09, más estricta que el diseño original (cierra la ventana en vez de solo acotarla, tal
   como pedía el re-chequeo de `orion-security`).

2. **Hallazgo C — CA-03 deriva la lista YELLOW de `security_manager._actions.items()`**, no
   de una lista de 19 nombres copiados a mano, tal como especificó el hallazgo. Se agregó un
   guardrail propio del test (`assert len(yellow_a_verificar) >= 15`) para que, si el registro
   real quedara vacío por algún motivo, el test falle por una razón obvia en vez de "pasar"
   sin haber verificado nada.

3. **Bug de test descubierto y corregido durante el desarrollo — `contextvars.ContextVar` en
   el hilo principal de pytest.** Al escribir `tests/test_telegram_confirmation_adapter.py`,
   un test que llamaba `set_request_context()` directo en el hilo principal (sin pasar por un
   `threading.Thread` nuevo) dejaba el valor del `ContextVar` filtrado a los tests
   siguientes dentro del mismo proceso — un test posterior que esperaba `ctx is None`
   terminaba viendo el contexto del test anterior y esperando el timeout real completo de
   120s antes de fallar-cerrado igual (aserción correcta, pero por el motivo equivocado, y
   122s más lento). Se agregó un fixture `autouse` (`_reset_request_context`) que resetea el
   `ContextVar` antes/después de cada test del archivo. No es un bug del código de
   producción — `asyncio.to_thread()` sí propaga el contexto correctamente al hilo worker
   real (comportamiento documentado de la librería estándar); es un artefacto exclusivo de
   cómo los tests invocan `confirm()` directamente sin pasar por `asyncio.to_thread()`.

4. **Bug de fuga de test descubierto y corregido — `register_confirmation_adapter()` no
   tiene "unregister".** El test de CA-14 (`test_ca14_eliminar_confirmado_queda_en_audit_db`)
   registra temporalmente un adaptador real para `ChannelType.TELEGRAM` y lo restauraba solo
   si había uno antes (`if original_adapter is not None`). Como en producción/tests no hay
   ningún adaptador TELEGRAM registrado por defecto, el `finally` no hacía nada — dejando el
   adaptador de ese test filtrado al resto de la suite completa. Esto rompía
   `tests/test_tool_registry.py::test_delete_task_yellow_sigue_bloqueado_en_lote` (test
   pre-existente de REQ-017 que asume que Telegram no tiene adaptador para `delete_task`) al
   correr la suite completa (aunque no al correr solo los archivos de REQ-018 en aislamiento).
   Corregido: si no había adaptador antes, el `finally` saca la entrada directo de
   `core.confirmation._ADAPTERS` en vez de dejarla. Verificado: `python -m pytest tests/`
   completo vuelve a mostrar únicamente los 2 fallos preexistentes documentados en
   `baseline-018.md` (`anthropic` no instalado, no relacionados con este REQ).

5. **`cmd_eliminar()` ya no llama a `has_pending()` como chequeo previo** — `reserve_pending()`
   hace la verificación atómica y la reserva en un solo paso, así que el chequeo separado que
   proponía la arquitectura original (§6.1, antes del Hallazgo E) queda redundante. El método
   `has_pending()` se mantiene en el adaptador (lectura, sin reservar) porque sigue siendo
   útil para tests/diagnóstico, pero `cmd_eliminar()` ya no lo usa.

Ningún otro ajuste respecto a lo aprobado en `arquitectura-018.md` — CA-06/CA-07/CA-12/CA-13
se implementaron tal cual estaban especificados, sin desviaciones.

## Verificación local

```
python -m py_compile channels/telegram_bot.py channels/telegram_confirmation_adapter.py core/security_manager.py
→ OK, sin errores.

python -m pytest tests/ --tb=short -q
→ 538 passed, 2 failed, 11 warnings.
```

Los 2 fallos son exactamente los mismos 2 documentados en `origen/baseline-018.md` como
pre-existentes y no atribuibles a este REQ (`tests/test_llm_provider.py::
test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` y
`test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto`, ambos por
`ModuleNotFoundError: No module named 'anthropic'`, paquete no instalado en el entorno local).
Sin fallos nuevos. 57 tests nuevos de este REQ, todos en verde:

- `tests/test_security_manager.py` — 6 nuevos (75 en total en el archivo, todos pasan).
- `tests/test_telegram_confirmation_adapter.py` — 27 nuevos (archivo nuevo).
- `tests/test_telegram_bot.py` — 24 nuevos (archivo nuevo).

`tests/test_resolution.py` (CA-12 — regresión del pipeline de `resolve()`) corrido junto con
la suite del REQ: sin modificaciones, en verde.

## DoD check — `orion-dev` (`.claude/rules/definition-of-done.md`)

```
[x] Solo se implementó lo aprobado en arquitectura (§1-§15 + los 4 hallazgos de seguridad)
[x] Sin API keys/tokens hardcodeados
[x] Sin `except: pass` silencioso — los 2 except de telegram_confirmation_adapter.py
    (`_send_message()`, `confirm()`) registran logger.error() en todos los casos
[x] Sin prints de debug en código final
[x] Sin dependencias nuevas — requirements.txt sin cambios (python-telegram-bot==20.7 ya
    estaba, confirmado instalado)
[x] No se tocaron skills — este REQ no crea ni modifica ningún skill de skills/
[x] Banner mostrado antes de escribir código
[x] desarrollo-log-018.md generado (este archivo)
[x] NO se ejecutó git commit
[x] Mensaje de commit sugerido entregado (ver handoff)
```
