# Baseline REQ-027 — estado del sistema ANTES del cambio

**Fecha:** 2026-09-08
**Levantado por:** `orion-architect` (el pipeline se acortó por decisión de Johan; el baseline
corto es parte del trabajo del arquitecto, no un paso omitido).
**Medido sobre el WORKING TREE, no sobre el último commit** — en REQ-026 esa diferencia importó.

---

## 1. Estado del repositorio

```
Rama actual : feature/mcp-correo-flujos
HEAD        : d75008a  feat(REQ-026): modos estrategicos en la barra del composer
```

`git status --porcelain`:

```
 M agente_ia/requerimientos.csv
?? agente_ia/workspace/adjuntos/REQ-027/
```

**Working tree limpio en todo lo que este REQ va a tocar.** Los dos únicos cambios sin
commitear son el CSV del tracker (movido por `orion-spec` a `SPEC_APROBADO`) y la carpeta de
evidencias de REQ-027. Ningún archivo de `core/`, `ai/` o `tests/` tiene modificaciones
locales: lo que está en disco es exactamente lo que está en `d75008a`.

> Nota de rama (P-5, todavía sin resolver por Johan y sin efecto sobre este diseño):
> `feature/mcp-correo-flujos` está 1 commit por delante de `main`, y ese commit es `d75008a`
> (REQ-026). O sea que hoy esta rama equivale a `main + REQ-026`, que es justo la base que
> este REQ necesita (CA-12 cuelga el presupuesto de `core/composer_modes.py`, archivo que
> `main` todavía no tiene).

---

## 2. Suite de tests — conteo de HOY

```
$ cd agente_ia && python -m pytest tests/ --tb=no -q
1828 passed, 11 warnings in 214.41s (0:03:34)
[exit code 0]
```

| Métrica | Valor |
|---|---|
| Tests que pasan | **1828** |
| Tests que fallan | **0** |
| Errores de colección | **0** |
| Warnings | 11 (todos preexistentes: `PytestReturnNotNoneWarning` en `tests/test_agents.py::test_ca1_orchestrator` y `DeprecationWarning` de numpy/joblib en el classifier) |
| Duración | 214,41 s |

**No hay fallos preexistentes.** Cualquier test rojo después de REQ-027 es responsabilidad de
REQ-027 — no hay ruido de fondo detrás del que esconderse. Es la referencia contra la que se
verifica **CA-44**.

---

## 3. Archivos que el REQ va a tocar — estado actual

| Archivo | Líneas hoy | Qué contiene hoy que este REQ cambia |
|---|---|---|
| `core/reasoning_loop.py` | 377 | `MAX_LLM_CALLS = 5` (:29); `_build_prompt()` (:193) re-serializa el historial de tools como texto plano en un único mensaje `user`; `_append_history_lines()` (:230); `run()` (:241) con `call = response.tool_calls[0]` (:322) que descarta el resto; `ActionDenied` corta con `break` sin volver a llamar al modelo (:334-340) |
| `ai/llm_provider.py` | 990 | `_ask_anthropic` (:558) envuelve TODO como `{"type":"text"}` (:568-570); `_ask_openai` (:699), `_ask_openrouter` (:774) y `_ask_deepseek` (:922) pasan `content` crudo y no contemplan `role="tool"`; `_llamada_en_streaming` (:853); `_uncached_call` (:56); `_cached_call`/`_cache_key` (:37-53); **5 ocurrencias de `max_tokens=1500`** en :595, :756, :834, :867, :974 |
| `core/composer_modes.py` | 113 | `ModoComposer` con `id/label/tool_names/tarea/prompt_hint` — **sin** campo de presupuesto; los 4 modos en `_MODOS` (:46-94); `get_mode()` fail-safe (:104) |
| `ai/claude_brain.py` | 338 | `MAX_TOOL_ROUNDS = 3` (:118); bucle propio (:148-204) que re-serializa resultados como texto; llamada de cierre sin herramientas ya existente (:206-212) |
| `tests/test_reasoning_loop.py` | 486 | 26 tests. Los que cambian de expectativa: `test_ca07_agota_5_llamadas_sin_una_sexta` (:172), `test_ca08_action_denied_corta_de_inmediato` (:189) |
| `tests/test_llm_provider.py` | 288 | 15 tests |
| `tests/test_composer_modes.py` | 85 | — |
| `tests/test_claude_brain.py` | 77 | — |

### Archivos que el REQ NO debe tocar (verificable con `git diff --stat`, CA-43)

| Archivo | Líneas hoy | Por qué queda intacto |
|---|---|---|
| `tests/modelo_falso.py` | 143 | `run()` falso, **función plana** con firma `(task, channel, user_id="default", agent_name="reasoning_loop", estado=None)` — sin `modo`. Un kwarg nuevo en `reasoning_loop.run()` explota con `TypeError`. CA-17 lo cierra de raíz. |
| `core/resolution.py` | ~710 | Llama a `reasoning_run()` con el patrón condicional de `:696-699` (pasa `modo` solo si no es `None`) por el problema de arriba. Sin cambio de firma, no se toca. |
| `agents/tool_registry.py` | — | `execute_tool()` (:201) sigue siendo el único gate. |
| `core/security_manager.py` | — | Modelo de seguridad REQ-005/006/019 intacto. |
| `core/cancelacion.py` | — | `abortar_si_cancelado()` se llama MÁS veces, pero el módulo no cambia. |
| `ui/webview/bridge.py` | — | Sin cambios de UI ni de catálogo visible. |

---

## 4. Hechos verificados en el código (no supuestos)

1. **Ningún `parameters_schema` del catálogo declara `additionalProperties: false`.** Verificado
   con `grep -n additionalProperties agents/tool_registry.py` → 0 coincidencias. Es lo que hace
   seguro reenviar al proveedor un `tool_use.input` con claves que el schema no declara.
2. **`_cache_key()` serializa `messages` con `json.dumps(..., sort_keys=True)`.** Un `content`
   estructurado no lo rompe (todo es JSON-serializable), pero sí haría cacheable una llamada
   con historial de herramientas. Ver D-3 de la arquitectura.
3. **`_uncached_call()` es el único embudo** por el que pasan tanto `generate_response()` como
   `_intentar_respaldos()` como `_cached_call()`. Es el punto correcto para el aplanado.
4. **Anthropic exige alternancia estricta de roles** `user`/`assistant`. Cualquier instrucción
   extra que se le quiera dar al modelo junto a los resultados tiene que ir como bloque DENTRO
   del mensaje de resultados, nunca como un `user` adicional.
5. **`ChannelType`** (`core/security_manager.py:59`) = `DESKTOP, TELEGRAM, DISCORD, VOICE, API,
   EMAIL, UNKNOWN`. El techo de canal de CA-15 se escribe como "todo lo que no sea `DESKTOP`",
   que es fail-closed por construcción.
6. **`_PROVEEDORES_CON_TOOLS = ("anthropic", "deepseek", "openai", "openrouter")**
   (`ai/llm_provider.py:209`) — una sola fuente, ya compartida por `generate_response()` y
   `_intentar_respaldos()`.
7. **`_ask_deepseek` difiere de `_ask_openai`/`_ask_openrouter`** en el último mensaje: DeepSeek
   manda `content` como string plano (y le concatena un aviso si hay imagen); los otros dos
   mandan una lista de bloques `{"type":"text"}`. Esa diferencia hay que preservarla byte a
   byte (CA-08).
