# Desarrollo REQ-006 [A] (CA-01 a CA-17)

`orion-dev` — implementación siguiendo `propuestas/arquitectura-006.md` al pie de la letra.
No se implementó nada de la sección [B] (CA-18 a CA-24, `core/reasoning_loop.py`) — queda
estrictamente para REQ-007.

## Archivos creados

- `agente_ia/core/resolution.py` — punto único de resolución (CA-01/02/03/04/06/07). `resolve()`
  camina `RESOLVERS` (`routine → autopilot → learned → task_tool → capability → intent → claude`)
  en orden fijo, mismo para cualquier canal.
- `agente_ia/tests/conftest.py` — registra un adaptador de confirmación DESKTOP para que la
  suite de tests pueda ejercer el camino YELLOW sin importar `main.py`.
- `agente_ia/tests/test_resolution.py` — CA-01, CA-02, CA-03, CA-04, CA-06, CA-07.
- `agente_ia/tests/test_tool_registry.py` — CA-08, CA-14, CA-15, CA-16, CA-17.
- `agente_ia/tests/test_confirmation.py` — CA-10.
- `agente_ia/tests/test_base_agent.py` — CA-09 (regresión del bug H7).
- `agente_ia/tests/test_main.py` — CA-12 (`_ProactiveAssistant.can_handle()`).
- `agente_ia/tests/test_main_channel.py` — CA-05 (`channel` real por ciclo de captura, no
  hardcodeado).

## Archivos modificados

- `agente_ia/core/security_manager.py` — nueva excepción `ActionDenied`; la rama YELLOW de
  `require_confirmation()` deja de llamar `input()` directo y consulta
  `core/confirmation.py::get_confirmation_adapter()` (CA-09/CA-10). `CHANNEL_ALLOWED_LEVELS`,
  `RiskLevel`, `register_action()` y el resto del contrato de `require_confirmation()` — sin
  cambios.
- `agente_ia/core/base_agent.py` — `_DynamicAgentInstance.execute()` distingue `except
  ActionDenied: continue` de una excepción genérica (CA-09/H7). `AgentTool.execute()` no se
  tocó (Observación A de `orion-security`: sin consumidor vivo en [A]).
- `agente_ia/core/orchestrator.py` — `process_task()` delega a `core.resolution.resolve()`.
  `_try_quick_dispatch()`, `_process_with_agents()`, `_decompose()`, `_execute_single_agent()`,
  `_execute_agent_chain()` y `fallback_to_claude()` sin cambios (se mantienen por compatibilidad
  estructural con `tests/test_agents.py`; `_decompose()` es CA-24, de REQ-007, fuera de alcance).
- `agente_ia/router/dispatcher.py` — `dispatch()` levanta `ActionDenied` en vez de retornar el
  string `"⛔ Acción no autorizada."` (CA-09). `dispatch_as_tool()` sin cambios.
- `agente_ia/main.py` — importa y usa `core.resolution.resolve()`; registra
  `core.confirmation.register_confirmation_adapter(ChannelType.DESKTOP, _desktop_confirm)`
  (único adaptador real de este REQ, CA-10); calcula `channel` una vez por ciclo de captura
  (`ChannelType.VOICE` si `choice in ('2','3')`, si no `ChannelType.DESKTOP`) reemplazando los 6
  literales `"desktop"` hardcodeados (CA-05); corrige `_ProactiveAssistant.can_handle()` (CA-12).
- `agente_ia/channels/gateway.py` — `GlassGateway.process()` delega a `resolve()`; se eliminan
  `_try_create_task()`, `_try_list_tasks()`, `_try_complete_task()` (CA-02 — su función pasó al
  resolver `task_tool` de `core/resolution.py`, ahora gateado vía `execute_tool()`, cerrando el
  hallazgo de baseline H3). `_save_semantic()` deja de tener un `except Exception: pass` silencioso.
- `agente_ia/channels/telegram_bot.py` — se elimina el pre-matching de "apaga/reinicia el pc" en
  `handle_text()`/`handle_voice()` (B6, CA-02); `_handle_shutdown()`/`_handle_restart()` sin
  cambios (ya gateaban correctamente desde REQ-005).
- `agente_ia/tests/test_security_manager.py` — dos tests actualizados para reflejar el nuevo
  contrato de denegación de `dispatch()` (ver "Decisiones de implementación").
- `agente_ia/tests/test_classifier.py`, `agente_ia/tests/test_dispatcher.py` — casos reales
  colectables por pytest (CA-13; antes reportaban "0 tests collected").

## Sin cambios (confirmado, no se tocaron)

- `agente_ia/agents/tool_registry.py` — ya existía completo y coincide exactamente con la
  arquitectura (`ToolSpec`, `register_tool()`, `execute_tool()`, tools `task_create`/
  `task_list`/`task_complete` pre-registradas en GREEN).
- `agente_ia/core/confirmation.py` — ya existía completo (`ConfirmFn`, registro de adaptadores
  por canal, fail-closed sin adaptador).
- `agente_ia/agents/action_registry.py`, `agente_ia/tasks/task_manager.py` — sin cambios de
  código, per arquitectura.

## Dependencias agregadas

Ninguna. `requirements.txt` no se modificó.

## Decisiones de implementación

1. **`tests/conftest.py` duplica el adaptador `_desktop_confirm` de `main.py`.** La mayoría de
   los archivos de test no importan `main.py` (módulo pesado, con efectos de arranque). Para que
   `tests/test_security_manager.py` y el resto puedan ejercer la rama YELLOW/DESKTOP sin
   importar `main`, se registra el mismo adaptador (idéntica lógica de comparación) desde
   `conftest.py`. Duplicación deliberada y documentada, no un cambio de contrato.

2. **`resolve()` acepta `claude_fn` como parámetro opcional**, más allá de la firma literal
   `resolve(text, channel, user_id="default")` de la arquitectura. Necesario para que
   `channels/gateway.py` siga usando su `_ask_claude_for_user()` (historial de sesión por
   usuario, soporte de imágenes) sin que `core/resolution.py` tenga que conocer `GlassMessage`
   ni sesiones de usuario. El ORDEN de resolución (CA-03) es idéntico en los tres canales; solo
   el detalle de implementación del último paso (`claude`) puede variar, igual que ya variaba
   antes de este REQ.

3. **`channels/gateway.py::process()` conserva dos casos especiales pre-`resolve()`**:
   `MessageType.IMAGE` (ningún resolver de la cadena opera sobre imágenes — es un tipo de
   entrada distinto, no una bifurcación de canal/orden) y `Intent.TAKE_SCREENSHOT` (mismo
   patrón que ya existía, capturas de pantalla no pasan por el flujo de texto). Se consideró y
   se **descartó** un tercer caso especial para `Intent.UNKNOWN` (saltar directo a Claude) por
   violar CA-03: eso habría reproducido el bug de motores divergentes que este REQ cierra,
   saltándose `routine`/`autopilot`/`learned`/`task_tool`/`capability` cuando el clasificador
   legacy no reconoce el texto pero otro resolver sí podría.

4. **`main.py` conserva el caso especial `Intent.TEACH_COMMAND`** pre-`resolve()` (multi-turno
   interactivo de enseñanza de comandos) — sin resolver equivalente en la cadena, comportamiento
   preexistente sin cambios funcionales.

5. **Bug encontrado y corregido en `core/resolution.py::_try_intent`, no anticipado por la
   arquitectura.** `intent/classifier.py:classify_command()` puede devolver un `str` plano (no
   un miembro de `Intent`) porque `intent/ai_classifier.py::IntentClassifierSystem.predict()`
   hace `return str(prediction)`. La primera versión de `_try_intent` asumía siempre un
   `Intent` y llamaba `intent.value`, lo que rompía con `AttributeError: 'str' object has no
   attribute 'value'` en cualquier resolución real. `router/dispatcher.py:dispatch()` ya tenía
   el patrón defensivo correcto (`intent.value if hasattr(intent, "value") else str(intent)`);
   se replicó el mismo patrón en `_try_intent`. Verificado con
   `tests/test_classifier.py::test_classify_then_resolve_desktop_executes_green_intent`.

6. **Dos tests de `tests/test_security_manager.py` actualizados** —
   `test_skill_failure_fallback_does_not_execute_when_gate_denied` y
   `test_yellow_prompt_includes_identifying_param` — porque `dispatch()` ahora levanta
   `ActionDenied` en vez de retornar `"⛔ Acción no autorizada."`; se envolvió la llamada en
   `with pytest.raises(ActionDenied):` preservando el resto de cada aserción. Consecuencia
   directa y mínima del cambio de contrato exigido por CA-09, no una decisión de diseño nueva.

7. **`test_classifier.py`**: dos datos de prueba se ajustaron a la salida real del clasificador
   ML entrenado (no a una expectativa asumida): `classify_command("busca en google sobre la
   luna")` extrae `query="sobre la luna"` (no `"la luna"`), y el modelo TF-IDF+SVM entrenado casi
   nunca predice `UNKNOWN` en texto libre (fuera de alcance de este REQ reentrenar el modelo) —
   `test_classify_command_unknown_falls_back` mockea `ai_system.predict` para probar el contrato
   de forma determinista en vez de depender del comportamiento incidental del modelo.

## Verificación local

```
cd agente_ia && python -m py_compile main.py core/resolution.py core/security_manager.py \
  core/base_agent.py core/orchestrator.py core/confirmation.py router/dispatcher.py \
  agents/tool_registry.py channels/gateway.py channels/telegram_bot.py
# -> compila sin errores

cd agente_ia && python -m pytest tests/ --tb=short -q
# -> 92 passed, 3 warnings (2 DeprecationWarning de speech_recognition/aifc, 1
#    PytestReturnNotNoneWarning de test_agents.py::test_ca1_orchestrator — ambos
#    pre-existentes, documentados en baseline-006.md, no relacionados con este REQ)
```

Baseline (`origen/baseline-006.md`): 54 tests pre-existentes (49 de `test_security_manager.py`
+ 5 de `test_agents.py`), 0 fallos. Después de REQ-006: 92 tests, 0 fallos — los 38 tests nuevos
son los que cubren CA-01 a CA-17; cero regresiones sobre los 54 originales.
