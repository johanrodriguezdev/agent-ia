# Desarrollo REQ-019 — Configuración de niveles de seguridad por el usuario

**Agente:** orion-dev
**Fecha:** 2026-08-20
**Basado en:** `arquitectura-019.md` §1-§11 completo (el addendum §11 reemplaza el
pseudocódigo original de §2/§3.1/§3.3/§3.4 en los puntos que corrige, no lo complementa) +
`security-audit-019.md` completo (2 pasadas, veredicto final ✅ APROBADO) + las 3 notas no
bloqueantes del handoff de `orion-security`.

## Archivos modificados

- `core/security_manager.py` — `_RISK_LEVEL_ORDER`, `_load_and_parse_overrides()`
  (módulo, con doble capa de `except Exception` — §11.1), `_base_levels`/
  `_config_overrides` en `SecurityManager.__new__()`, `register_action()` extendido
  (protege RED sobre `_base_levels`, calcula el nivel efectivo vía
  `_merge_with_override()`), `_merge_with_override()` nuevo, `classify_action_base()`
  nuevo, `log_override_attempt()` nuevo. `classify_action()`/`require_confirmation()` sin
  cambios de código (siguen leyendo `self._actions`, que ahora es el nivel efectivo).
- `core/security_config.py` (**nuevo**) — `load_security_overrides()` (con
  `except Exception` amplio, §11.1/Hallazgo A), `save_security_overrides()`,
  `_atomic_write()` (`os.replace()`, con `mkstemp()` también dentro de manejo de errores).
- `ui/webview/bridge.py` — import de `RiskLevel`/`_RISK_LEVEL_ORDER` directo de
  `core.security_manager` (§11.2/Hallazgo B, mismo patrón ya usado para `ChannelType`),
  `_SECURITY_ROWS_V1`/`_SECURITY_ROW_BY_ID` (catálogo v1, 8 filas/9 claves),
  `_ORDERED_LEVEL_VALUES` (derivado de `_RISK_LEVEL_ORDER`, nunca mantenido a mano),
  `_V1_MAX_OFFERABLE_LEVEL = RiskLevel.YELLOW` (§11.3/Hallazgo C), 3 señales nuevas
  (`security_overrides_loaded`, `security_override_saved`, `security_override_save_rejected`),
  2 slots nuevos (`request_security_overrides()`, `save_security_override()`),
  `_save_security_override_flow()`, `_on_security_override_error()`,
  `_build_security_overrides_payload()`, docstring del módulo extendido (CA-20).
- `ui/webview/frontend/index.html` — botón `#settings-btn` (junto a `#tasks-btn`/
  `#projects-btn`), `<link>` a `css/settings_panel.css`.
- `ui/webview/frontend/js/app.js` — import + wiring de `openSettingsPanel` y las 3
  señales nuevas.
- `ui/webview/frontend/js/bridge_client.js` — 2 wrappers JS→Python
  (`requestSecurityOverrides`, `saveSecurityOverride`), 3 wrappers Python→JS.
- `ui/webview/frontend/js/settings_panel.js` (**nuevo**) — pantalla "Configuración"
  completa (nav lateral + tarjeta "Seguridad"), modelo "aplicar al elegir" (resuelve
  CA-18 por construcción), inserción DOM exclusivamente vía `textContent`/`setAttribute`.
- `ui/webview/frontend/css/settings_panel.css` (**nuevo**) — layout de 2 columnas sobre
  `.modal-overlay`/`.modal-box` de `modal.css`, tokens de tema existentes (sin paleta
  nueva).
- `.claude/rules/security-levels.md` — sección nueva "REQ-019 — override de
  configuración de usuario (solo subir, nunca bajar)" (CA-27).
- `tests/test_security_manager.py` — 13 tests nuevos (CA-01, CA-02, CA-03, estructural
  RED/YELLOW/GREEN parametrizado, CA-04 ×2, CA-06 ×2, CA-07, `classify_action_base` ×2).
- `tests/test_security_config.py` (**nuevo**) — 13 tests (archivo inexistente/corrupto/
  bytes no-UTF-8/valor inválido/no-dict, round-trip, merge, limpieza de temporales, fallo
  de `os.replace`/`mkstemp`).
- `tests/test_webview_bridge.py` — 12 tests nuevos (CA-08, CA-19, CA-16 ×2, CA-05, CA-21,
  techo v1, row_id/nivel inválido, atomicidad de fila, guardado exitoso) + extensión de
  `_EXPECTED_SLOTS`/`_EXPECTED_SIGNALS` (CA-42).
- `tests/test_webview_safe_dom_insertion.py` — `"settings_panel.js"` agregado a
  `_MUST_NOT_USE_INNERHTML`.

## Dependencias agregadas

Ninguna. `requirements.txt` sin cambios (`json`/`os`/`tempfile` son de librería estándar,
ya usados en el proyecto).

## Decisiones de implementación

1. **Nota no bloqueante (1) de `orion-security` — `py_compile` de `core/security_config.py`
   como parte de CA-23.** Verificado explícitamente: `python -m py_compile
   core/security_manager.py core/security_config.py ui/webview/bridge.py` sin errores (ver
   sección "Verificación local" abajo).

2. **Nota no bloqueante (2) — import local redundante de `RiskLevel` en
   `_save_security_override_flow()`.** Resuelto: el import local dentro de la función es
   `from core.security_manager import security_manager` (solo el singleton, que no puede
   importarse a nivel de módulo por el mismo motivo que el resto de `bridge.py` lo importa
   perezoso en cada flow). `RiskLevel` se usa desde el import de módulo
   (`from core.security_manager import ChannelType, RiskLevel, _RISK_LEVEL_ORDER`), sin
   una segunda importación local redundante.

3. **Nota no bloqueante (3) — valor esperado de CA-16 para `effective_level == "yellow"`.**
   El test `test_ca16_fila_con_effective_level_yellow_solo_ofrece_yellow` en
   `tests/test_webview_bridge.py` usa `options == ["yellow"]` (techo v1 de §11.3), no
   `["yellow", "red"]` como decía la sección "Pruebas sugeridas" pre-addendum de
   `arquitectura-019.md` — con un comentario explícito en el test señalando por qué.

4. **Desviación puntual del pseudocódigo de §3.3 — `_on_security_override_error()` sí
   emite `security_override_save_rejected`.** El pseudocódigo literal del addendum
   mostraba `_on_security_override_error(self, message: str)` solo con `logger.warning`,
   sin emitir la señal de rechazo — pero la propia arquitectura señala esto explícitamente
   como una nota de implementación abierta ("éste debe emitir
   `security_override_save_rejected(row_id)` — confirmar el mecanismo exacto de
   `run_async()`/`ui/gui_workers.py` para no asumir la forma del mensaje de error").
   Verificado contra `ui/gui_workers.py::run_async()`: `on_error` solo recibe el mensaje de
   la excepción (`str(e)`), no `row_id`. Se implementó `save_security_override()` con
   lambdas que capturan `row_id` por clausura (`lambda message:
   self._on_security_override_error(row_id, message)`), y `_on_security_override_error()`
   ahora recibe `(row_id, message)` y emite la señal — sin esto, CA-21 quedaría
   funcionalmente inoperante para el frontend (el `<select>` nunca se re-habilitaría ni se
   mostraría el banner de rechazo). Cubierto por 4 tests dedicados en
   `tests/test_webview_bridge.py` (row_id desconocido, nivel inválido, intento de bajada,
   nivel por encima del techo v1) que verifican `security_override_save_rejected` se
   emite en los 4 casos.

5. **Adopción de la Recomendación no bloqueante 4 de la 1ra pasada de
   `security-audit-019.md`** (no parte del addendum §11, pero de bajo costo y ya
   señalada): en `core/security_config.py::_atomic_write()`, `tempfile.mkstemp()` se
   movió dentro de su propio `try/except OSError` (antes quedaba fuera del bloque
   protegido) — un fallo ahí (permiso denegado, disco lleno) ahora también se maneja sin
   propagar excepción, en vez de depender únicamente de que el hilo de `run_async()` lo
   capture genéricamente. Cubierto por
   `test_fallo_de_mkstemp_no_propaga_excepcion` en `tests/test_security_config.py`.

6. **Verificación de que no hay import circular real** (no solo teórica): se ejecutó
   `import core.security_manager`, `import core.security_config` y `import
   ui.webview.bridge` en un intérprete limpio — sin error, confirmando lo que
   `security-audit-019.md` ya había verificado contra el precedente de `ChannelType` en
   `bridge.py:43`.

## Verificación local

```
python -m py_compile core/security_manager.py core/security_config.py ui/webview/bridge.py \
    tests/test_security_manager.py tests/test_security_config.py tests/test_webview_bridge.py \
    tests/test_webview_safe_dom_insertion.py
→ sin errores

python -m pytest tests/test_security_manager.py tests/test_security_config.py -q
→ 79 passed

python -m pytest tests/test_webview_bridge.py -q
→ 102 passed

python -m pytest tests/test_webview_safe_dom_insertion.py -q
→ 14 passed

python -m pytest tests/ --tb=short -q
→ 2 failed, 480 passed
```

Los 2 fallos son exactamente los pre-existentes documentados por `orion-baseline`
(`tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` y
`test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto`, `ModuleNotFoundError: No module
named 'anthropic'` — paquete no instalado en el entorno, ajeno a este REQ). El conteo total
sube de 420 a 480 passed por los tests nuevos de REQ-019 (38 tests nuevos: 13 en
`test_security_manager.py`, 13 en `test_security_config.py`, 12 en
`test_webview_bridge.py`) más los tests de REQ-015/016/017 ya presentes sin commitear al
momento del baseline. `test_register_action_cannot_downgrade_red` (CA-25) pasa sin
modificación de su propio código.

## Cobertura de CA — resumen

Los 28 CA de SPEC-019 quedan implementados según `arquitectura-019.md` §1-§11. Puntos
verificados explícitamente con test dedicado: CA-01, CA-02, CA-03, CA-04, CA-05, CA-06,
CA-07, CA-08, CA-09/CA-11 (round-trip + escritura atómica), CA-16, CA-17 (grep
estructural), CA-19, CA-20 (docstring), CA-21, CA-22 (JS nunca calcula rank —
`settings_panel.js` solo pinta `options`/`effective_level` y reenvía `row_id`/`level`),
CA-25 (test preexistente intacto), CA-26 (esquema `{clave: nivel}` cerrado), CA-27
(sección nueva en `security-levels.md`), CA-28 (ya cumplido por el flujo previo). CA-10,
CA-12..CA-15, CA-18, CA-23, CA-24 verificados por inspección/compilación (no requieren
test unitario aislado — CA-10/18 son de UX de frontend, CA-12..15/CA-13 son estructura de
DOM ya cubierta indirectamente por `test_webview_safe_dom_insertion.py`, CA-23/CA-24
verificados en la sección "Verificación local" arriba).
