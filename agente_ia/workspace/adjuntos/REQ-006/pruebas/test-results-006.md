# Resultados de prueba REQ-006 [A] (CA-01 a CA-17)

`orion-tester` — verificación independiente de la implementación de `orion-dev`
(`propuestas/desarrollo-log-006.md`). CA-18 a CA-24 son de REQ-007, fuera de alcance,
no evaluados aquí.

> **Actualización 2026-08-04 (segunda ronda):** `orion-dev` corrigió el único bloqueante
> (CA-03) con un cambio acotado a `tests/test_resolution.py`. Re-verificado de forma
> independiente — ver sección "Re-verificación CA-03" al final de este documento.
> **Veredicto final: PASS, 17/17.**

## Compilación

```
cd agente_ia && python -m py_compile core/resolution.py core/security_manager.py \
  core/base_agent.py core/orchestrator.py router/dispatcher.py main.py \
  channels/gateway.py channels/telegram_bot.py agents/tool_registry.py core/confirmation.py
```
Resultado: **OK** — 0 errores en los 9 módulos.

## Tests existentes

```
cd agente_ia && python -m pytest tests/ --tb=short -v
```
Resultado (ronda 1, antes del fix de CA-03): **92 passed, 0 failed, 3 warnings** en 1.37s.
Resultado (ronda 2, después del fix de CA-03): **95 passed, 0 failed, 3 warnings** en 1.28s.

Recuento manual línea por línea del output verboso de la ronda 2 (independiente del
reporte de `orion-dev`): `test_agents.py`=5, `test_base_agent.py`=4,
`test_classifier.py`=8, `test_confirmation.py`=4, `test_dispatcher.py`=5,
`test_main.py`=3, `test_main_channel.py`=1, `test_resolution.py`=9 (6 originales + 3
nuevos: `test_traza_identica_por_canal_categoria_amarilla`,
`_categoria_desconocida`, `_categoria_multi_paso`), `test_security_manager.py`=49,
`test_tool_registry.py`=7. Suma = 95. Coincide exactamente con lo reportado por
`orion-dev` (92 preexistentes + 3 nuevos). Mismos 3 warnings de siempre (2
`DeprecationWarning` de `speech_recognition`/`aifc`, 1 `PytestReturnNotNoneWarning`
preexistente), sin warnings nuevos.

Warnings: 2 `DeprecationWarning` (speech_recognition/aifc — dependencia externa, no
relacionado con este REQ), 1 `PytestReturnNotNoneWarning` (`test_agents.py::test_ca1_orchestrator`,
preexistente en baseline). Ninguno es nuevo por causa de este REQ salvo que el
`DeprecationWarning` ahora aparece porque `test_main.py` importa `main.py` completo por
primera vez — no es un fallo, es una dependencia transitiva ya presente antes del REQ.

## Regresión

| Área revisada | Resultado |
|---|---|
| `tests/test_security_manager.py` (49 tests preexistentes de REQ-005) | PASS — mismo conteo exacto que baseline-006.md, 0 nuevos fallos |
| `tests/test_agents.py` (5 tests preexistentes) | PASS — sin cambios |
| `CHANNEL_ALLOWED_LEVELS` (`core/security_manager.py`) | Sin cambios, byte a byte igual al baseline |
| `grep -rn "async def" core/ router/ intent/ skills/` | 0 resultados, igual que baseline (CA-11) |

No se introdujeron fallos nuevos respecto a `origen/baseline-006.md`.

## Criterios de la SPEC

| Criterio | Resultado | Nota |
|---|---|---|
| CA-01 — único punto de entrada | PASS | `main.py` y `channels/gateway.py` importan y llaman `core.resolution.resolve()`; `channels/gateway.py` ya no importa `tasks.task_manager` directo. Verificado en código fuente, no solo en el test. |
| CA-02 — sin pre-matching | PASS | `GlassGateway` ya no tiene `_try_create_task`/`_try_list_tasks`/`_try_complete_task`; `telegram_bot.py` ya no pre-matchea "apaga/reinicia el pc". Confirmado por grep directo en el código, no solo por el test. |
| CA-03 — traza idéntica entre canales | **PASS** (tras fix de `orion-dev`) | Ver "Re-verificación CA-03" al final. |
| CA-04 — mismo `action_name` amarillo desktop/voice | PASS | `test_yellow_mismo_action_name_desktop_vs_voice` confirma mismo `require_confirmation("close_app", ...)` para VOICE (deniega sin `input()`) y DESKTOP (pide confirmación, 1 llamada a `input()`), solo difiere el veredicto. |
| CA-05 — canal real por ciclo de captura | PASS | `main.py` calcula `channel = ChannelType.VOICE if choice in ('2','3') else ChannelType.DESKTOP` una vez por ciclo, reemplazando los 6 literales `"desktop"`. Confirmado en código fuente (línea ~131) y con `test_main_channel.py` (extrae la expresión real por regex y la evalúa contra los 4 casos de `choice`). |
| CA-06 — solo verde ejecuta por voz | PASS | `test_solo_verde_ejecuta_por_voz` (amarillo denegado por voz) + `test_red_action_blocked_per_channel[voice]` preexistente (rojo denegado por voz) + `test_traza_identica_por_canal` (verde sí resuelve/ejecuta por voz, `denied=False`). Cobertura combinada suficiente. |
| CA-07 — sin romper los 49 tests de seguridad | PASS | Conteo exacto verificado (49/49), contenido de los 2 tests modificados revisado línea por línea (`test_yellow_prompt_includes_identifying_param`, `test_skill_failure_fallback_does_not_execute_when_gate_denied` — ambos ahora usan `pytest.raises(ActionDenied)`, cambio mínimo y directo consecuencia de CA-09). `test_cobertura_total_de_tools_y_acciones` nuevo confirma que ningún tool/acción/intent queda sin clasificar. |
| CA-08 — `risk_level` no autoritativo | PASS | `CHANNEL_ALLOWED_LEVELS` sin cambios confirmado por grep; `test_risk_level_declarado_no_es_autoritativo` en `test_tool_registry.py` confirma que `security_manager` puede reclasificar por encima del `risk_level` declarado en el `ToolSpec`. |
| CA-09 — `ActionDenied` nunca se confunde con éxito | PASS | `router/dispatcher.py::dispatch()` levanta `ActionDenied` (ya no retorna el string `"⛔ Acción no autorizada."`). `core/base_agent.py::_DynamicAgentInstance.execute()` distingue `except ActionDenied: continue` de excepción genérica — y el chequeo por substring (`"Error" not in result[:10]`) fue **eliminado por completo** del código, no solo parcheado, lo que satisface por construcción el caso borde donde un texto de éxito legítimo contendría la palabra "Error". |
| CA-10 — adaptador de confirmación por canal, fail-closed | PASS | `require_confirmation()` ya no llama `input()` directo; usa `core/confirmation.py::get_confirmation_adapter()`. Sin adaptador registrado (ej. DISCORD) devuelve `False` sin colgar (confirmado en `test_confirmation.py`). |
| CA-11 — sin `async def` nuevo | PASS | `grep -rn "async def" core/ router/ intent/ skills/` → 0 resultados, igual que baseline. `core/confirmation.py` documentado como 100% síncrono. |
| CA-12 — fix de `_ProactiveAssistant.can_handle()` | PASS | Confirmado en código fuente (`main.py`) y en `test_main.py`: ternario ahora retorna `0.6`/`0.0` según coincidencia real, ya no `0.0` en ambas ramas. |
| CA-13 — `test_classifier.py`/`test_dispatcher.py` dejan de dar 0 tests | PASS | Confirmado por conteo en pytest -v (8 y 5 tests respectivamente) y por `git diff` (cambios puramente aditivos, `run_tests()` legacy preservado). `test_classify_then_resolve_desktop_executes_green_intent` ejercita la cadena completa clasificación→resolve→dispatch con canal real, no solo el intent clasificado. |
| CA-14 — forma de `ToolSpec` | PASS | `test_toolspec_shape` en `test_tool_registry.py` confirma `parameters_schema` como JSON Schema (`type: object`, `properties`), validación manual mínima (opción explícitamente permitida por la arquitectura). |
| CA-15 — `risk_level` obligatorio | PASS | `test_tool_sin_risk_level_no_compila` confirma `TypeError` al omitir `risk_level` — fail-closed por construcción del dataclass. |
| CA-16 — mismo contrato para origen remoto | PASS | `test_tool_origen_remoto_mismo_contrato` confirma que un tool con `origin` distinto de `"local"` pasa por `execute_tool()` de forma idéntica. |
| CA-17 — sin campos de identidad de usuario en `ToolSpec` | PASS | `test_toolspec_no_tiene_campo_de_usuario` confirma ausencia de campos como `user_id` en el contrato del tool. |

**17 de 17 PASS.**

## Re-verificación CA-03 (ronda 2, 2026-08-04)

### Hallazgo original (ronda 1)

Texto literal de `SPEC-006.md`: *"Para un conjunto de peticiones representativas (una
verde, una amarilla, una desconocida, una multi-paso), la traza de resolución —herramienta
elegida y parámetros extraídos— es idéntica en desktop, telegram y voice. Solo puede
diferir el veredicto del gate."*

El test original, `tests/test_resolution.py::test_traza_identica_por_canal`, solo
ejercitaba la categoría **verde**. Faltaban amarilla-vía-TELEGRAM, desconocida y
multi-paso comparadas entre los tres canales.

### Cambio de `orion-dev`

`orion-dev` agregó 3 tests nuevos en `tests/test_resolution.py`, sin tocar ningún otro
archivo de código o test:

- `test_traza_identica_por_canal_categoria_amarilla` (líneas 68-98): "cierra chrome"
  (CLOSE_APP) en DESKTOP/TELEGRAM/VOICE con `input()` mockeado. Verificado
  independientemente: compara `matched_by` (idéntico, `"intent:CLOSE_APP"`, en los 3
  canales), `denied` (`True` en los 3), y además el conteo de llamadas a `input()` por
  canal (DESKTOP=1, TELEGRAM=0, VOICE=0) — documentando explícitamente que la única
  diferencia entre canales es el mecanismo del veredicto del gate (TELEGRAM/VOICE
  deniegan sin preguntar porque YELLOW no está en su `CHANNEL_ALLOWED_LEVELS`; DESKTOP sí
  pregunta), consistente con "solo puede diferir el veredicto del gate" de la SPEC.
- `test_traza_identica_por_canal_categoria_desconocida` (líneas 101-122): fuerza
  `ai_system.predict` a devolver `"UNKNOWN"` (mismo mecanismo determinista que
  `test_classifier.py::test_classify_command_unknown_falls_back`, sin red real),
  `claude_fn` mockeado. Verificado independientemente: `matched_by == "claude"` idéntico
  en los 3 canales, ninguno denegado, mismo texto de salida (`echo:...`) en los 3.
- `test_traza_identica_por_canal_categoria_multi_paso` (líneas 125-165): "haz un modo
  trabajo" (rutina que dispara `open_chrome` + `open_notepad`), con
  `ACTION_REGISTRY["open_chrome"]["fn"]` y `["open_notepad"]["fn"]` monkeypatcheados
  (sin abrir procesos reales, cumple `.claude/rules/testing.md`). Verificado
  independientemente: mismo `matched_by` en los 3 canales, misma secuencia exacta de
  llamadas `(("open_chrome", {}), ("open_notepad", {}))` en los 3 canales, ninguno
  denegado (ambos pasos son GREEN).

Los tres tests genuinamente comparan la traza (`matched_by`, y en el caso multi-paso la
secuencia completa de llamadas con sus parámetros) entre los tres canales — no solo
existen con nombres relacionados, ejercen el criterio tal como lo exige el texto de
`SPEC-006.md`.

### Verificación de alcance del cambio

```
find . -type f -newer workspace/adjuntos/REQ-006/pruebas/test-results-006.md \
  -not -path "./.git/*" -not -path "*/__pycache__/*" -not -path "*/.pytest_cache/*"
```
(usando como marca de tiempo la primera escritura de este documento, antes del fix)
Resultado: solo `tests/test_resolution.py` (el cambio de `orion-dev`), más
`agent_context.db`/`audit.db`/`logs/orion.log` (artefactos de runtime generados por
correr la suite) y `requerimientos.csv`/`REQ-006-context.md` (tocados por mí,
`orion-tester`, en la ronda 1). Confirmado: **ningún archivo de código de producción
fue modificado** — el fix quedó acotado a un solo archivo de test, como reportó
`orion-dev`.

### Suite completa (ronda 2)

`python -m pytest tests/ --tb=short -v` → **95 passed, 0 failed, 3 warnings** (mismos 3
warnings de siempre, ninguno nuevo). Conteo recontado manualmente línea por línea,
independiente del reporte de `orion-dev`: coincide exactamente (92 preexistentes de la
ronda 1 + 3 nuevos).

## Veredicto: PASS

17 de 17 criterios (CA-01 a CA-17) pasan con test genuino que ejerce cada uno, no solo
con nombre relacionado. Cero regresiones sobre los 54 tests preexistentes de
`origen/baseline-006.md`, y cero regresiones entre la ronda 1 (92 tests) y la ronda 2
(95 tests) de este REQ. Compilación limpia en los 9 módulos. Listo para `orion-qa`.
