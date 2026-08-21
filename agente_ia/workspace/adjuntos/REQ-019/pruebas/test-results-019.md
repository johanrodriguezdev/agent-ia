# Resultados de prueba REQ-019 — Configuración de niveles de seguridad por el usuario

**Agente:** orion-tester
**Fecha:** 2026-08-20
**Entrada:** `arquitectura-019.md` §1-§11 (addendum incluido), `security-audit-019.md` (2 pasadas,
✅ APROBADO), `desarrollo-log-019.md`, código real (`core/security_manager.py`,
`core/security_config.py`, `ui/webview/bridge.py`, `ui/webview/frontend/js/settings_panel.js`,
`app.js`, `bridge_client.js`, `index.html`, `.claude/rules/security-levels.md`).

Metodología: cada uno de los 28 CA se verificó por lectura directa del código real contra el
addendum §11 (no contra el resumen de `desarrollo-log-019.md`), más ejecución real de la suite
existente y **3 scripts de verificación independientes** (no reutilizan código de
`tests/test_security_manager.py`/`test_security_config.py`/`test_webview_bridge.py`) para los
puntos de mayor riesgo señalados en el handoff: CA-02/CA-03 (núcleo del merge), CA-06
(fail-closed ante corrupción real de archivo), CA-08/CA-16 (catálogo v1 y techo yellow) y CA-21
(revalidación server-side, ejercitada con el `QThreadPool` **real** de producción, no el
`run_async` síncrono simulado de los tests de `orion-dev`).

## Compilación

`python -m py_compile core/security_manager.py core/security_config.py ui/webview/bridge.py
main.py` → **OK**, sin errores.

## Tests existentes (suite completa, ejecutada de forma independiente)

- 1ra corrida: `3 failed, 513 passed` (143s)
- 2da corrida (para descartar flakiness): `2 failed, 514 passed` (141s)
- **Fallos consistentes en ambas corridas (pre-existentes, ajenos a REQ-019):**
  - `tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse`
  - `tests/test_llm_provider.py::test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto`
  - Causa raíz confirmada: `ModuleNotFoundError: No module named 'anthropic'` (paquete no
    instalado en el entorno). Documentado también por `orion-baseline` sobre 420 casos y por
    `orion-dev` sobre 480 — consistente en las 3 mediciones, no es una regresión de este REQ.
- **Fallo NO reproducible detectado en la 1ra corrida:**
  `tests/test_telegram_confirmation_adapter.py::test_send_message_future_result_timeout_no_impide_seguir_esperando_respuesta`
  — falla solo cuando corre después de ~500 tests (contención de timing/threads), pasa en
  aislamiento y pasa en la 2da corrida completa. No toca ningún módulo de este REQ
  (`core/security_manager.py`, `core/security_config.py`, `ui/webview/bridge.py`,
  `ui/webview/frontend/`) — test flaky preexistente ajeno a REQ-019, no atribuible al merge de
  seguridad ni a la persistencia de overrides.
- El total de `passed` (513-514) es mayor al reportado por `orion-dev` (480) porque la suite
  incluye tests de otros REQs (014/017/018) agregados/modificados en la misma rama sin commitear
  entre la corrida de `orion-dev` y esta verificación — no es una discrepancia atribuible a
  REQ-019.

### Archivos de test específicos de REQ-019 (aislados)
| Archivo | Resultado |
|---|---|
| `tests/test_security_manager.py` + `tests/test_security_config.py` | 86 passed |
| `tests/test_webview_bridge.py` | 102 passed |
| `tests/test_webview_safe_dom_insertion.py` | 14 passed |

`test_register_action_cannot_downgrade_red` (CA-25) — **PASS**, código del test idéntico al
documentado por baseline, sin ninguna modificación de su comportamiento esperado.

## Verificación independiente adicional (scripts propios, fuera de la suite de orion-dev)

Tres scripts standalone (no importan ni reutilizan ningún `tests/test_*.py` existente),
ejecutados contra el código real del repo:

1. **CA-02/CA-03 + CA-06 (12 checks, 0 FAIL):** registro real de una acción YELLOW con override
   GREEN inyectado → `classify_action` sigue YELLOW, `require_confirmation()` sigue preguntando
   (confirmado con `input()` real devolviendo "no" → `False`, prueba que pasó por la rama YELLOW
   y no fue tratado como GREEN). Mismo patrón sobre `format_disk` (RED real) con override GREEN
   → sigue RED, `require_confirmation()` sigue bloqueando sin PIN. CA-06: 4 escenarios de
   corrupción real de archivo (bytes no-UTF-8, JSON sintácticamente inválido, valor de nivel
   inválido mezclado con uno válido, archivo que no es un objeto JSON) escritos a disco de verdad
   en un directorio temporal y leídos con `load_security_overrides()` real — ninguno crashea,
   todos caen a `{}` (o descartan solo la entrada inválida), y se confirmó además que
   `_load_and_parse_overrides()` (la función que corre dentro de `SecurityManager.__new__()`, el
   punto de import real que la 1ra auditoría de seguridad marcó como bloqueante) tampoco propaga
   la excepción con el archivo de bytes no-UTF-8.
2. **CA-08/CA-16 + coexistencia REQ-018 (6 checks, 0 FAIL):** las 10 claves RED reales
   (extraídas del propio `security_manager._base_levels`, no de una lista copiada a mano) no
   intersectan con el catálogo real `_SECURITY_ROWS_V1` del bridge. Forzando el estado real de
   `open_chrome` a YELLOW vía `register_action()` real, `_build_security_overrides_payload()`
   devuelve `options == ["yellow"]` (nunca `["yellow","red"]`); en su estado real actual (GREEN),
   devuelve `["green","yellow"]` (nunca incluye `"red"`, techo v1 confirmado también desde GREEN).
   Coexistencia: `CHANNEL_ACTION_EXCEPTIONS` (REQ-018) es una estructura de módulo separada sin
   overlap de atributos con `_config_overrides`/`_base_levels`/`_actions` (REQ-019);
   `is_action_allowed("delete_task", TELEGRAM)` sigue `True` vía la excepción de REQ-018 sin
   ningún override de REQ-019 activo — confirmado que operan en fases distintas
   (`register_action()`/merge decide el NIVEL; `is_action_allowed()` decide si ese nivel alcanza
   para el canal) sin punto de intersección de estado.
3. **CA-21 con `QThreadPool` real de producción (3 checks, 0 FAIL):** se instanció el `Bridge`
   real con `QApplication` real (`QT_QPA_PLATFORM=offscreen`) y se invocó
   `save_security_override("open_chrome", "green")` directo (bypaseando el `<select>` de JS) con
   `open_chrome` puesto en YELLOW real — usando el `run_async()` **real** (no el síncrono
   simulado que usa `tests/test_webview_bridge.py`), a través del `QThreadPool.globalInstance()`
   real. Resultado: `security_override_save_rejected` emitida, `security_override_saved` nunca
   emitida, `classify_action("open_chrome")` sigue en `YELLOW`, y `save_security_overrides()`
   nunca fue invocada (0 escrituras a disco). El `security_overrides.json` real del proyecto no
   se tocó en ningún momento de esta verificación (confirmado con `git status` antes/después).

## Desviación reportada por orion-dev — evaluación

`_on_security_override_error()` pasó a recibir `(row_id, message)` y emitir
`security_override_save_rejected(row_id)`, en vez de solo loguear como mostraba el pseudocódigo
literal de §3.3 del addendum. **Verificado como correcta y necesaria:**
- La propia `arquitectura-019.md` §3.3 deja esto explícitamente abierto ("confirmar el mecanismo
  exacto de `run_async()`/`ui/gui_workers.py` para no asumir la forma del mensaje de error"), no
  es una desviación no autorizada.
- Confirmado contra `ui/gui_workers.py::run_async()` (código real, no el pseudocódigo): `on_error`
  recibe únicamente `str(e)`, nunca `row_id` — sin capturar `row_id` por clausura en el lambda
  (`ui/webview/bridge.py:566`, `lambda message: self._on_security_override_error(row_id,
  message)`), sería imposible que `security_override_save_rejected` llevara el `row_id` correcto.
- Sin este ajuste, CA-21 quedaría **funcionalmente inoperante del lado del frontend**: el
  `<select>` deshabilitado en `settings_panel.js` (línea 149, `select.disabled = true`) nunca se
  reactivaría tras un rechazo, dejando la fila permanentemente bloqueada en la UI.
- Verificado en runtime (script independiente CA-21 arriba): la señal se emite correctamente con
  el `row_id` esperado usando el camino real de `run_async`, no solo el simulado en tests de
  `orion-dev`.
- Cubierto por 4 tests dedicados en `tests/test_webview_bridge.py` (row_id desconocido, nivel
  inválido, intento de bajada, nivel por encima del techo v1) — los 4 ejecutados y en PASS.

**Veredicto sobre la desviación: justificada, correctamente implementada, no rompe ningún CA.**

## Coexistencia REQ-018 / REQ-019 en `core/security_manager.py`

Confirmado estructuralmente independientes, no solo por tests que pasan juntos:
- `CHANNEL_ACTION_EXCEPTIONS` (REQ-018, línea 84) es un `set[tuple[ChannelType, str]]` a nivel de
  módulo, consultado únicamente dentro de `is_action_allowed()` (línea 330).
- `_config_overrides`/`_base_levels` (REQ-019) son atributos de instancia del singleton
  `SecurityManager`, consultados únicamente dentro de `register_action()`/`_merge_with_override()`
  (líneas 254-294).
- Ningún camino de código lee ambas estructuras a la vez ni una depende del resultado de la otra:
  el merge de REQ-019 decide el **nivel efectivo** de una acción (fase de registro, arranque);
  `is_action_allowed()` de REQ-018/REQ-006 decide si ese nivel ya calculado **alcanza para el
  canal** (fase de `require_confirmation()`, en cada invocación). Son ejes ortogonales del mismo
  pipeline, no hay escritura cruzada de estado.
- `tests/test_security_manager.py::test_ca03_todas_las_yellow_restantes_siguen_bloqueadas_en_telegram`
  (REQ-018) deriva la lista de acciones YELLOW **dinámicamente** del registro real en el momento
  de ejecutarse — dejado así explícitamente por su propio comentario para no desincronizarse en
  silencio si REQ-019 registra una acción YELLOW nueva vía override. Ejecutado, PASS.
- Verificado además con script independiente (ver arriba, punto 2).

## Criterios de la SPEC (28/28)

| CA | Descripción resumida | Resultado | Nota |
|----|----|----|----|
| CA-01 | Ranking explícito `_RISK_LEVEL_ORDER` | PASS | Dict `{GREEN:0,YELLOW:1,RED:2}` confirmado en código + test dedicado |
| CA-02 | Nivel efectivo = max(código,config), YELLOW→GREEN no baja | PASS | Verificado independientemente (script propio) + test de orion-dev |
| CA-03 | Igual que CA-02 para RED | PASS | Verificado independientemente (script propio) + test de orion-dev |
| CA-04 | Intento de bajada queda auditado | PASS | `_merge_with_override`→`"override_bajada_ignorada"`, `log_override_attempt`→`"override_guardado_rechazado_bajada"`, tests PASS |
| CA-05 | Acciones sin clasificar inalcanzables | PASS | Omitidas en payload y rechazadas en el slot de guardado, tests PASS |
| CA-06 | `security_overrides.json` corrupto no crashea | PASS | Verificado independientemente con 4 escenarios reales de corrupción + `_load_and_parse_overrides()` |
| CA-07 | Merge no depende del canal | PASS | `_merge_with_override()` no recibe `channel`, confirmado en código y test |
| CA-08 | Las 10 RED de REQ-005 no configurables | PASS | Verificado independientemente contra el catálogo real y las 10 claves RED reales del singleton |
| CA-09 | Override persiste entre reinicios | PASS | Persistencia en archivo + recarga única en `__new__()`; round-trip real en disco confirmado |
| CA-10 | UI comunica que requiere reinicio | PASS | `settings_panel.js::handleSecurityOverrideSaved()` — banner explícito, verificado por lectura |
| CA-11 | Escritura atómica antes de confirmar guardado | PASS | `os.replace()` corre dentro del worker, antes de que `on_done` emita la señal; tests de atomicidad PASS |
| CA-12 | Punto de entrada nuevo (`#settings-btn`) | PASS | Confirmado en `index.html` y wiring en `app.js` |
| CA-13 | Nav lateral + panel de tarjetas | PASS | `renderShell()` en `settings_panel.js`, confirmado por lectura |
| CA-14 | Sección "Seguridad" en la nav | PASS | Confirmado en código |
| CA-15 | Tarjeta con fila por acción v1 | PASS | 8 filas, confirmado en catálogo real y payload |
| CA-16 | Control nunca ofrece nivel inferior (techo yellow) | PASS | Verificado independientemente para YELLOW y GREEN reales — nunca incluye "red" |
| CA-17 | Inserción DOM solo textContent/setAttribute | PASS | Lectura completa de `settings_panel.js` (cero `innerHTML`) + 14 tests de `test_webview_safe_dom_insertion.py` PASS |
| CA-18 | Cerrar sin guardar no aplica cambios | PASS | Modelo "aplicar al elegir" por construcción, sin botón de guardado separado — confirmado en código |
| CA-19 | Carga perezosa (no en arranque) | PASS | `requestSecurityOverrides()` solo en `openSettingsPanel()`; test dedicado PASS |
| CA-20 | Slots documentados en docstring del bridge | PASS | Docstring líneas 1-27 confirmado, incluye REQ-019 |
| CA-21 | Validación server-side independiente de la UI | PASS | Verificado independientemente con `QThreadPool` real de producción (no el fake síncrono de los tests de orion-dev) |
| CA-22 | JS nunca calcula rank | PASS | `settings_panel.js` solo pinta `options`/`effective_level`, reenvía intención — confirmado por lectura completa |
| CA-23 | `py_compile` sin errores | PASS | Ejecutado, incluye `core/security_config.py` (nota no bloqueante de la 2da auditoría) |
| CA-24 | Suite completa sin regresiones nuevas | PASS | 514/516 passed en 2da corrida, mismos 2 fallos pre-existentes que baseline/dev; 1 fallo flaky no atribuible descartado |
| CA-25 | Tests de REQ-005 (incl. `test_register_action_cannot_downgrade_red`) intactos | PASS | Test idéntico, ejecutado, PASS |
| CA-26 | Overrides son solo `{acción: nivel}` | PASS | `_VALID_LEVEL_VALUES={"green","yellow","red"}`, sin campos de texto libre |
| CA-27 | `.claude/rules/security-levels.md` actualizado | PASS | Sección "REQ-019" confirmada presente y completa |
| CA-28 | Pasó por `orion-security` antes de `orion-dev` | PASS | 2 pasadas documentadas en contexto, veredicto final ✅ APROBADO antes del handoff a `orion-dev` |

**28/28 CA en PASS.**

## Observación fuera de alcance (no bloqueante para este REQ)

`core/security_manager.py::require_confirmation()`, rama RED sin PIN (línea ~395), usa
`print(msg)` con el carácter `⛔`. En una consola Windows con code page `cp1252` (no UTF-8), un
`print()` directo de ese emoji lanza `UnicodeEncodeError` — reproducido al ejercitar esta rama
fuera de `pytest` (que captura stdout de forma segura). Es código **pre-existente de REQ-005**,
no tocado por REQ-019 (`require_confirmation()` no tiene cambios de código en este REQ, confirmado
en `arquitectura-019.md` §1.3: "`require_confirmation()` y `classify_action()` no se tocan en
absoluto"). No es un criterio de esta SPEC ni una regresión de este REQ — se deja anotado para que
quede registrado, no bloquea el veredicto.

## Regresión

| Área revisada | Resultado |
|---|---|
| `core/security_manager.py` completo (REQ-005/REQ-006/REQ-018/REQ-019) | Sin regresión — 86 tests PASS |
| `core/security_config.py` (nuevo) | Sin hallazgos — 13 tests propios + verificación independiente PASS |
| `ui/webview/bridge.py` (superficie completa del contrato JS↔Python) | Sin regresión — 102 tests PASS, incluye `_EXPECTED_SLOTS`/`_EXPECTED_SIGNALS` |
| `tests/test_webview_safe_dom_insertion.py` | Sin regresión — 14 tests PASS |
| Suite completa del proyecto | Sin regresión atribuible a REQ-019 — mismos 2 fallos pre-existentes que baseline (paquete `anthropic` ausente) |

## Veredicto: ✅ PASS

Los 28 CA de SPEC-019 están implementados correctamente según `arquitectura-019.md` §1-§11
(addendum incluido) y verificados por ejecución real, no solo por lectura — incluyendo 21 checks
de verificación independiente propios (fuera de la suite de `orion-dev`) sobre los puntos de mayor
riesgo del REQ (núcleo del merge, fail-closed ante corrupción real de archivo, techo v1, y
revalidación server-side con el `QThreadPool` real de producción). La desviación reportada por
`orion-dev` (`_on_security_override_error(row_id, message)`) está correctamente justificada,
implementada y testeada. La coexistencia con REQ-018 (`CHANNEL_ACTION_EXCEPTIONS`) es
estructuralmente independiente, confirmado por lectura de código y verificación en runtime, no
solo porque los tests pasan juntos. Sin regresiones atribuibles a este REQ.
