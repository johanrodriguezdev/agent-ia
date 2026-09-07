# QA Audit — REQ-019

**Agente:** orion-qa
**Fecha:** 2026-09-07
**Nota de proceso:** esta ejecución de `orion-qa` estaba pendiente desde que `orion-tester`
cerró su verificación (ver `pruebas/test-results-019.md`) — el handoff nunca se había
lanzado. Se retoma ahora bajo la autorización nocturna en bloque del 2026-09-06 (el usuario
autorizó continuar el pipeline sin pausas de aprobación intermedias; git commit/push y
acciones 🔴 Rojo siguen prohibidas igual, y la aprobación humana final de este REQ sigue
pendiente).

**Alcance:** auditoría de solo lectura sobre los archivos que tocó REQ-019. No se modificó
ni se tocó ningún archivo de REQ-018 (en testing) ni REQ-022 (en desarrollo), ambos activos
en el árbol en paralelo.

## Documentación leída (en orden)

1. `REQ-019-context.md` — historial completo coordinador → tester.
2. `spec/SPEC-019.md` — 28 criterios de aceptación (CA-01..CA-28).
3. `propuestas/arquitectura-019.md` — diseño aprobado, incluyendo addendum §11 post-auditoría.
4. `pruebas/security-audit-019.md` — 2 pasadas de `orion-security` (1ª: ❌ REQUIERE CAMBIOS
   con 3 hallazgos; 2ª, tras el addendum §11: ✅ APROBADO).
5. `pruebas/test-results-019.md` — veredicto de `orion-tester`: ✅ PASS, 28/28 CA, 21 checks
   de verificación independiente con objetos reales (no reutiliza los tests de `orion-dev`).
6. `.claude/rules/security-levels.md` — sección "REQ-019" al final (CA-27 verificado: existe
   y describe correctamente el mecanismo implementado).
7. `propuestas/desarrollo-log-019.md` — lista de archivos tocados por `orion-dev` y su propia
   verificación local, usada como checklist cruzada (no como fuente de verdad — cada punto se
   re-verificó contra el código real, no contra lo que el log afirma).

## Verificación de código — no solo de documentación

A diferencia de las pasadas anteriores, esta auditoría releyó el código real (no el
pseudocódigo de arquitectura) de cada archivo tocado por REQ-019, para confirmar que las 3
correcciones del addendum §11 (Hallazgos A/B/C de `orion-security`) están efectivamente en
el árbol de trabajo y no solo en el documento de diseño.

### `core/security_config.py` (nuevo, 95 líneas)

- `load_security_overrides()`: `except Exception as e` amplio (Hallazgo A cerrado — cubre
  `UnicodeDecodeError`, que es subclase de `ValueError` y quedaba fuera del `except
  (json.JSONDecodeError, IOError)` original). Nunca silencioso: siempre `logger.warning(...)`
  antes de retornar. Archivo ausente → `{}`. JSON no es `dict` → `{}` con warning. Entradas con
  clave/valor no-string o valor fuera de `_VALID_LEVEL_VALUES` → se descartan una a una con
  warning, el resto de entradas válidas se conserva.
- `save_security_overrides()` hace read-modify-write y delega a `_atomic_write()`.
- `_atomic_write()`: `tempfile.mkstemp()` dentro de su propio `try/except OSError` (mejora no
  bloqueante adoptada de la recomendación #4 de la 1ª pasada de auditoría), y `os.replace()`
  para el swap atómico (Windows `MoveFileEx` / POSIX rename). Ningún branch de error deja la
  excepción sin loguear ni usa `except: pass`.
- `SECURITY_OVERRIDES_FILE` es una constante de ruta propia, **separada** de la constante que
  usa `config.json` en el resto del proyecto — confirmado por inspección: no hay ningún punto
  donde ambos archivos compartan lectura/escritura o un mismo `open()`.

### `core/security_manager.py` (685 líneas)

- `_RISK_LEVEL_ORDER: Dict[RiskLevel, int] = {GREEN: 0, YELLOW: 1, RED: 2}` a nivel de módulo.
  `RiskLevel` se mantiene como `Enum` plano (no `IntEnum`) a propósito, para no romper el
  contrato de `.value` (`"green"/"yellow"/"red"`) que consume `composer.js:110` para nombres de
  clase CSS — el orden se resuelve aparte, vía este dict, nunca comparando los miembros del
  enum entre sí.
- `_load_and_parse_overrides()`: segunda capa defensiva (Hallazgo A) — envuelve la llamada a
  `load_security_overrides()` en su propio `try/except Exception`, con `logger.warning` y
  fallback a `raw = {}`. Cada valor se intenta convertir a `RiskLevel(value)`; un `ValueError`
  individual se loguea y se descarta esa entrada sin abortar el resto.
- `SecurityManager.__new__()`: construye `_base_levels` (nivel de código puro),
  `_config_overrides` (cargado **una sola vez** por proceso, en la construcción del singleton —
  de aquí que el cambio requiera reiniciar la app; no hay recarga en caliente en v1) y
  `_actions` (nivel efectivo).
- `register_action()`: si la acción ya está clasificada como `RED` en `_base_levels` y se
  intenta re-registrar con un nivel distinto de `RED`, lo bloquea (`logger.critical` +
  `_log_audit(..., "reclasificacion_bloqueada", ...)`, retorna `False` sin aplicar el cambio).
  Si no, actualiza `_base_levels[name]` y calcula `_actions[name] =
  self._merge_with_override(name, level)`.
- `_merge_with_override()`: comparación simétrica vía `_RISK_LEVEL_ORDER` para los 3 niveles —
  si `override < base` (en orden), se ignora el override, se loguea `logger.warning` +
  `_log_audit(..., "override_bajada_ignorada", ...)` y se retorna `base_level`. Nunca hay una
  rama que retorne `override` cuando es menor. No hay recursión hacia `register_action()`.
- Las 10 acciones 🔴 Rojo de REQ-005 (`format_disk`, `delete_database`, `expose_secrets`,
  `modify_source_code`, `send_email_as_user`, `post_social_media`, `elevated_system_command`,
  `install_uninstall_software`, `modify_system_env_vars`, `grant_third_party_access`) siguen
  registradas como `RiskLevel.RED` sin cambios de este REQ.
- Sin secretos hardcodeados: `AUTH_PIN_ENV = "ORION_AUTH_PIN"` es el **nombre** de la variable
  de entorno, no un valor. Sin `except: pass` en todo el archivo.

### `ui/webview/bridge.py` (secciones REQ-019)

- Docstring del módulo (líneas 1-44) documenta explícitamente los slots/señales whitelisteados
  de este REQ (CA-20).
- `_SECURITY_ROWS_V1`: catálogo v1 de 8 filas / 9 claves internas (apertura de apps y
  navegación, per SPEC-019 — **no** incluye ninguna de las 10 claves RED de REQ-005).
- `_ORDERED_LEVEL_VALUES` se deriva de `_RISK_LEVEL_ORDER` vía `sorted()` — no es una lista
  duplicada mantenida a mano (Hallazgo B cerrado: la arquitectura pre-addendum tenía un nombre
  indefinido `_RISK_LEVEL_ORDER_LOCAL`; el código real importa `_RISK_LEVEL_ORDER` directo de
  `core.security_manager`, mismo patrón ya usado para `ChannelType`).
- `_V1_MAX_OFFERABLE_LEVEL = RiskLevel.YELLOW` (Hallazgo C cerrado): aplicado tanto en
  `_build_security_overrides_payload()` (recorta `options` a `[current_rank : ceiling_rank+1]`
  con `ceiling_rank = max(current_rank, YELLOW)`) como, de forma independiente, en
  `_save_security_override_flow()` server-side (rechaza si `requested > _V1_MAX_OFFERABLE_LEVEL`
  sin importar lo que el `<select>` del frontend haya ofrecido — defensa en profundidad real,
  CA-21).
- `_save_security_override_flow()`: valida `row_id` contra el catálogo (si no existe,
  `ValueError`), valida `level` contra `RiskLevel` (si no es válido, `ValueError`), aplica el
  techo v1, y por cada clave interna de la fila comprueba `can_apply = _RISK_LEVEL_ORDER[requested]
  >= _RISK_LEVEL_ORDER[current]` — todo-o-nada por fila (`PermissionError` si no todas las
  claves aceptan o si `accepted_keys` queda vacío). Cada intento se audita vía
  `security_manager.log_override_attempt()` antes de decidir. Solo si pasa todo llama a
  `save_security_overrides({key: requested.value for key in accepted_keys})`.
- `_on_security_override_error(row_id, message)`: desviación documentada y aprobada
  (arquitectura §3.3 lo dejaba abierto explícitamente) — captura `row_id` por clausura porque
  `run_async()`/`ui/gui_workers.py::CallableWorker.run()` solo pasa `str(e)` al callback de
  error. Sin esto, `security_override_save_rejected` nunca llevaría el `row_id` correcto y el
  `<select>` del frontend quedaría deshabilitado para siempre tras un rechazo. Confirmado
  presente en el código real, no solo en el log de `orion-dev`.
- `agents/tool_registry.py:133` — `security_manager.register_action(spec.name, nivel)`: éste es
  el 4º punto de registro (los otros 3 viven dentro de `core/security_manager.py`). Al llamar a
  `register_action()`, que internamente invoca `_merge_with_override()`, el override se aplica
  de forma consistente también en este punto — no hay una ruta paralela que asigne
  `_actions[name]` sin pasar por el merge.

### `ui/webview/frontend/js/settings_panel.js` (nuevo, sección "Seguridad")

- `renderSecurityOverrides()`/`buildSecurityRow()`: todo dato que llega de Python (`row.label`,
  `row.description`, `opt`/nivel, `row.row_id` vía `dataset`) se inserta exclusivamente con
  `textContent`/`setAttribute`/`.value`/`.selected` — cero usos de `innerHTML` o
  `insertAdjacentHTML` en todo el archivo (verificado por lectura completa línea a línea, 728
  líneas). El único texto insertado sin escapar es literal propio del frontend ("Configuración",
  "Perfil", etc.), correctamente comentado como tal.
- `tests/test_webview_safe_dom_insertion.py` confirma `"settings_panel.js"` está en
  `_MUST_NOT_USE_INNERHTML` (línea 32) y corre ambos tests parametrizados sobre ese archivo
  (grep estructural, no basado en confianza).
- **CA-16**: el `<select>` de cada fila solo agrega `<option>` por cada valor en `row.options`
  — nunca genera opciones fuera de lo que Python decidió ofrecer.
- **CA-18** (modelo "aplicar al elegir"): no existe botón de guardado separado para la sección
  Seguridad; el evento `change` del `<select>` llama `saveSecurityOverride()` de inmediato, con
  un guard `_pendingRowId` contra doble-evento en la misma fila. No hay estado "elegido pero no
  guardado" que un cierre de modal pueda descartar silenciosamente — resuelto por construcción.
- **CA-19** (carga perezosa): `requestSecurityOverrides()` solo se llama desde la rama `else`
  de `renderActiveSection()` (sección "seguridad"), nunca desde código de arranque/estado
  inicial.
- Mensaje de UX confirma CA-10 explícitamente: `"Cambio guardado. Se aplicará la próxima vez
  que abras la app."`

### Entry point (CA-12)

- `ui/webview/frontend/index.html:160` — botón `#settings-btn`.
- `ui/webview/frontend/js/app.js:185` — `document.getElementById("settings-btn")
  .addEventListener("click", openSettingsPanel)`. Wiring vive en `app.js`, no en `sidebar.js`,
  tal como especificaba la arquitectura.

## Compilación

```
python -m py_compile core/security_config.py core/security_manager.py ui/webview/bridge.py \
    agents/tool_registry.py
→ sin errores
```
Confirma de forma independiente (no reutilizando la evidencia de `orion-dev`/`orion-tester`)
que los 4 módulos Python tocados compilan.

## Búsqueda final de `except: pass` y secretos hardcodeados

Grep dirigido sobre los 5 archivos con lógica de seguridad de este REQ
(`core/security_config.py`, `core/security_manager.py`, `ui/webview/bridge.py`,
`agents/tool_registry.py`, `ui/webview/frontend/js/settings_panel.js`):

- `except.*:\s*pass` → un único match, y es una línea de **comentario en prosa** dentro de
  `core/security_config.py` explicando por qué el `except Exception` amplio no cuenta como
  "except: pass silencioso" (cita textual de `python-style.md`) — no es código.
- Patrón de posible secreto hardcodeado (`api_key|secret|token|password = "..."`) → sin
  coincidencias en los 3 archivos Python del núcleo de seguridad.

## Hallazgos

| Nivel | Hallazgo |
|---|---|
| 🟢 Verde | Los 3 hallazgos de la 1ª auditoría de `orion-security` (A/B/C) están correctamente cerrados en el código real, no solo en la documentación de arquitectura. |
| 🟢 Verde | El invariante `max(nivel_código, nivel_config)` se cumple en los 4 puntos de registro del sistema, incluyendo el 4º (`agents/tool_registry.py:133`), sin una ruta paralela que lo evite. |
| 🟢 Verde | `security_overrides.json` está completamente separado de `config.json` — no hay lectura/escritura compartida. |
| 🟢 Verde | Un archivo de overrides ausente, corrupto, con bytes inválidos, o con JSON que no es un objeto, siempre resuelve a `{}` (= sin overrides = nivel de código puro), nunca a "sin restricciones". Doble capa defensiva (`security_config.py` + `_load_and_parse_overrides()`). |
| 🟢 Verde | Las 10 acciones RED de REQ-005 quedan fuera del catálogo v1 ofrecido en el frontend y `register_action()` bloquea activamente cualquier intento de reclasificar una acción ya RED. |
| 🟢 Verde | El cambio requiere reinicio: `_config_overrides` se carga una única vez en `SecurityManager.__new__()`, sin ningún mecanismo de recarga en caliente. |
| 🟢 Verde | CA-17 (inserción DOM segura) verificado por lectura completa línea a línea de `settings_panel.js` y por el test estructural existente. |
| 🟢 Verde | Sin `except: pass` silencioso ni secretos hardcodeados en ningún archivo tocado por este REQ. |
| 🟢 Verde | `python -m py_compile` sin errores en los 4 módulos Python tocados (verificación independiente). |

No se encontraron hallazgos 🟡 amarillos ni 🔴 rojos. No hay nada pendiente de corrección.

## Convenciones de código

- Type hints presentes en todas las funciones nuevas de `core/security_config.py` y
  `core/security_manager.py`.
- Logging vía `logging`/`logger`, sin `print()` de depuración.
- Naming (`snake_case`/`PascalCase`/`UPPER_CASE`) consistente con `python-style.md`.
- `requirements.txt` sin cambios — correcto, no se agregó ninguna dependencia nueva (solo
  `json`/`os`/`tempfile` de librería estándar).

## Veredicto

## ✅ APROBADO

REQ-019 cumple su Definition of Done de `orion-qa`. Los 28 criterios de aceptación de
SPEC-019 están implementados y verificados contra el código real (no solo contra la
documentación del pipeline). Las 3 correcciones de seguridad de la 1ª auditoría están
cerradas correctamente. No hay hallazgos pendientes de ningún nivel.

**Siguiente paso:** se solicita la **prueba manual del humano** (Johan) antes de cerrar el
REQ — abrir la app, ir a Configuración → Seguridad, subir el nivel de una acción, confirmar
el mensaje "se aplicará la próxima vez que abras la app", reiniciar y confirmar que el nuevo
nivel efectivamente pide confirmación. Solo después de ese OK manual el estado avanza a
`LISTO_PARA_COMMIT` y se entrega el mensaje de commit sugerido — **no antes**. No se ejecutó
`git commit` en ningún momento de esta auditoría.
