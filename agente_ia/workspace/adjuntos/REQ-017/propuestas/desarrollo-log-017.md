# Desarrollo REQ-017 — Completar/listar/crear tareas en lote sin trabarse por falta de ID exacto

**Agente:** orion-dev
**Fecha:** 2026-08-20
**Fuente de verdad:** `workspace/adjuntos/REQ-017/propuestas/arquitectura-017.md` (✅ APROBADA por
Johan, con 2 ajustes menores — ver "Ajustes de Johan" al inicio de ese documento). Implementación
1:1 con el diseño de §2.1 y §2.2, sin desviaciones.

## Archivos modificados

- `agente_ia/core/resolution.py`
  - Se agrega `import re` a nivel de módulo.
  - Se agregan las constantes `_TASK_BULK_ALL_RE` (`\b(?:todas|todos)\b` — sin "todo" singular,
    ajuste de Johan) y `_TASK_BULK_COMPLETE_VERB_STEMS` (`"complet"`, `"termin"`, `"marc"`), y la
    función `_is_bulk_complete_phrase()`, insertadas después de `_is_task_complete_phrase()` y
    antes de `_try_task_tool()`.
  - `_try_task_tool()`: se inserta el bloque de desambiguación de "todas" entre el chequeo de
    `create` (sin cambios, mantiene prioridad) y el de `_is_task_complete_phrase()` (sin cambios,
    sigue siendo el último chequeo de la cadena). El bloque nuevo evalúa `bulk_all` y
    `list_trigger` juntos, y dentro de él el ID explícito (`has_explicit_task_id()`, importado de
    `agents/tool_registry.py`) gana siempre sobre `bulk_all` y sobre `list_trigger`.
  - `_TASK_CREATE_TRIGGERS`, `_TASK_LIST_TRIGGERS`, `_TASK_COMPLETE_TRIGGERS`,
    `_is_task_complete_phrase()`: **sin cambios**, tal como especifica la arquitectura.

- `agente_ia/agents/tool_registry.py`
  - `import re` se mueve de local (dentro de `_task_complete_invoke()`) a nivel de módulo.
  - Se agrega `_TASK_ID_RE = re.compile(r"(?:tarea|numero|número|id)\s*#?(\d+)|#(\d+)")` (regex
    ampliado: conserva la alternativa existente como grupo 1 y agrega `#N` suelto como grupo 2) y
    `has_explicit_task_id(text)`, expuesta para que `core/resolution.py` la reutilice sin duplicar
    el regex.
  - `_task_complete_invoke()`: única línea modificada es la extracción del `match`/`task_id`, ahora
    vía `_TASK_ID_RE` a nivel de módulo (`match.group(1) or match.group(2)`). El resto de la
    función queda intacto (auto-completar única pendiente, aclaración con >1 pendiente, mensaje de
    0 pendientes).
  - Se agrega `_TASK_COMPLETE_ALL_LIMIT = 20`, `_task_complete_all_invoke()` y el registro
    `register_tool(ToolSpec(name="task_complete_all", ..., risk_level=RiskLevel.GREEN, ...))`,
    después del registro existente de `task_complete`.

- `agente_ia/tests/test_resolution.py` — extendido (no reemplazado) con 8 tests nuevos para
  REQ-017 (CA-01 a CA-06 y una regresión de `task_create`).
- `agente_ia/tests/test_tool_registry.py` — extendido (no reemplazado) con 9 tests nuevos para
  REQ-017 (`task_complete_all`, `has_explicit_task_id()`, regex de ID ampliado, CA-07/CA-08/CA-09).

**Sin cambios** (confirmado, tal como preveía la arquitectura): `tasks/task_manager.py`,
`core/reasoning_loop.py`, `agents/skill_tools.py`, `channels/gateway.py`,
`channels/telegram_bot.py`, `channels/discord_bot.py`, `core/security_manager.py`,
`intent/intentions.py`, `RESOLVERS` (lista y orden).

## Dependencias agregadas

Ninguna. `requirements.txt` no se tocó en esta sesión (el diff que aparece en `git status` es de
REQ-015/016, preexistente en el working tree compartido, confirmado con `git diff --stat` antes de
esta entrega).

## Decisiones de implementación

Ninguna desviación respecto a `arquitectura-017.md`. La implementación siguió el pseudocódigo de
§2.1 y §2.2 literalmente, incluyendo:
- El punto de intercepción de "todas" ubicado ANTES de `_TASK_LIST_TRIGGERS` (hallazgo crítico de
  `orion-baseline`).
- El chequeo de ID explícito condicionado a `bulk_all or list_trigger` (no como gate independiente
  de nivel superior) — decisión de diseño ya documentada y aceptada por Johan en §2.1/§7 de la
  arquitectura.
- `task_complete_all` como `ToolSpec` nuevo (no como rama dentro de `_task_complete_invoke()`), con
  su propio `risk_level=RiskLevel.GREEN`.
- El bug preexistente "completa la tarea #3"/"completa mi tarea" (§0 de la arquitectura) **no se
  tocó**, tal como Johan confirmó explícitamente — ningún CA ni línea de código de esta entrega lo
  afecta.
- "Todo" (singular) **no** forma parte de `_TASK_BULK_ALL_RE` — solo "todas"/"todos", ajuste de
  Johan aplicado tal cual en el regex.

Un ajuste menor, no de diseño sino de datos de prueba: al escribir `test_un_pendiente_sin_id_sin_
cambios` (CA-03), se verificó con ejecución real que el texto que la arquitectura sugería como
ejemplo ("ya completé mi tarea") en realidad **no** matchea `_is_task_complete_phrase()` hoy
(`mentions_done` requiere el substring "completad", que "completé" no contiene) — es el mismo tipo
de imprecisión que ya había corregido `orion-baseline` para otras filas de la tabla de
comportamiento, simplemente no se había verificado esa variante puntual. Se usó en su lugar
"ya completé la tarea", que es un literal exacto de `_TASK_COMPLETE_TRIGGERS` y sí matchea
verificado con ejecución directa antes de escribir el test. No cambia ningún criterio de
aceptación ni ninguna línea de código de producción — solo el texto de prueba elegido para CA-03.

## Verificación local

```
python -m py_compile core/resolution.py agents/tool_registry.py tests/test_resolution.py tests/test_tool_registry.py
-> OK

python -m pytest tests/test_resolution.py tests/test_tool_registry.py --tb=short -q
-> 35 passed (17 tests nuevos de REQ-017: 8 en test_resolution.py, 9 en test_tool_registry.py)

python -m pytest tests/test_reasoning_loop.py --tb=short -q
-> 9 passed (CA-11: reasoning_loop sin cambios de comportamiento)

python -m pytest tests/ --tb=short -q
-> 2 failed, 437 passed
```

Los 2 fallos son los mismos documentados por `orion-baseline` en `baseline-017.md`
(`tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` y
`test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto`, `ModuleNotFoundError: No module named
'anthropic'`) — no relacionados con los archivos que este REQ modifica, confirmado corriendo esos
2 tests aislados (mismo `ModuleNotFoundError`). Antes de esta entrega la suite completa daba
`2 failed, 420 passed`; ahora `2 failed, 437 passed` — la diferencia de 17 son exactamente los tests
nuevos, sin ninguna regresión nueva (CA-12).

## Cobertura de los 12 CA de SPEC-017.md

| CA | Cubierto por |
|----|--------------|
| CA-01 | `test_bulk_complete_prioriza_sobre_list_trigger`, `test_bulk_complete_variantes_sin_palabra_tarea`, `test_task_complete_all_completa_todas_las_pendientes` |
| CA-02 | `test_mensaje_bulk_lista_ids_y_titulos`, `test_task_complete_all_completa_todas_las_pendientes` |
| CA-03 | `test_un_pendiente_sin_id_sin_cambios` |
| CA-04 | `test_cero_pendientes_sin_cambios`, `test_task_complete_all_cero_pendientes` |
| CA-05 | `test_id_explicito_gana_sobre_todas`, `test_has_explicit_task_id_variantes`, `test_task_complete_invoke_regex_existente_sin_cambios` |
| CA-06 | `test_id_explicito_gana_sobre_todas`, `test_mismo_texto_bulk_en_3_canales`, `test_task_complete_invoke_id_suelto_con_hash` |
| CA-07 | `test_task_complete_all_pasa_por_gate` |
| CA-08 | `test_task_complete_all_es_green_sin_confirmar` |
| CA-09 | `test_delete_task_yellow_sigue_bloqueado_en_lote` |
| CA-10 | No se tocó `channels/telegram_bot.py` (verificado, sin diff) |
| CA-11 | `tests/test_reasoning_loop.py` (9 passed, sin modificar), `RESOLVERS` sin cambios (verificado por lectura) |
| CA-12 | `pytest tests/ -q` → `2 failed, 437 passed`, mismos 2 fallos preexistentes de baseline |

Adicional (no CA literal, robustez del tool nuevo): `test_task_complete_all_respeta_limite_20`
verifica el tope `_TASK_COMPLETE_ALL_LIMIT=20` y el aviso de "puede haber más".

## Banner mostrado antes de escribir código

Sí, al inicio de la sesión, antes de la primera edición de código (`core/resolution.py`).
