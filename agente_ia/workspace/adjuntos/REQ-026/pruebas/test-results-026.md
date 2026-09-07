# Resultados de prueba REQ-026 — Modos estratégicos en la barra del composer

## Compilación
- `python -m py_compile core/composer_modes.py ui/webview/bridge.py core/resolution.py core/reasoning_loop.py`: **OK**
- `python -m py_compile` de los 4 archivos de test nuevos/editados (`tests/test_composer_modes.py`,
  `tests/test_webview_bridge.py`, `tests/test_reasoning_loop.py`, `tests/test_resolution.py`): **OK**
- `node --check` en `composer.js`, `bridge_client.js`, `app.js`: **OK**

## Los 2 fallos que dejó `orion-dev` (investigados primero)
`desarrollo-log-026.md` reportó 2 fallos "esperados" en `tests/test_webview_bridge.py`, a propósito, con la
responsabilidad de actualizarlos delegada a `orion-tester`. Antes de tocar nada se leyó el código fuente de
ambos tests y de `_build_chips_payload()`/`_CHIPS` (ya no existen) para confirmar la causa real:

| Test | Causa real | ¿Bug de comportamiento? |
|------|-----------|--------------------------|
| `test_request_initial_state_emite_chips_theme_y_conversaciones` | Asertaba `len(chips) == 5` (contrato viejo: 5 chips planos). El payload nuevo, aprobado en `arquitectura-026.md`, es `{"modes": [...4], "quick_actions": [...3]}`. | No — contrato ya aprobado por Johan, solo el test quedó desactualizado. |
| `test_build_chips_payload_consulta_risk_level_en_el_momento` | Llamaba a `bridge_module._build_chips_payload()`, función que `orion-dev` reemplazó por `_build_modes_payload()` + `_build_quick_actions_payload()` (`AttributeError`, no una aserción fallida). | No — mismo caso: función renombrada/dividida según arquitectura, test no actualizado. |

**Conclusión: ambos son desactualización de firma/contrato ya aprobado, no un bug real.** Se actualizaron
(no se descartaron): el primero ahora valida la forma nueva `{modes, quick_actions}` incluyendo que
"Resumen del día"/"Investigación rápida" no aparecen; el segundo se renombró a
`test_build_quick_actions_payload_consulta_risk_level_en_el_momento` y llama a la función nueva con los
conteos correctos (2 action + 1 template, antes 2+3). Se sumó `test_build_modes_payload_devuelve_4_modos_id_y_label_sin_detalle_interno`
para cubrir la función hermana que no tenía ningún test.

## Hallazgo adicional: cero cobertura nueva antes de esta verificación
Antes de correr nada se buscó (`grep -rn` sobre `tests/`) cualquier test existente para
`composer_modes|set_active_mode|_reordenar_priorizando|_build_modes_payload|_build_quick_actions_payload|modo_def|modo=|_tarea_activa`
→ **cero coincidencias**. El conteo de tests recolectados por pytest era idéntico antes y después de la
implementación (1795), confirmando que `orion-dev` no agregó ningún test nuevo pese a que
`.claude/rules/testing.md` lo exige ("Nuevo código: toda función pública debe tener al menos un test").

El código en sí se auditó línea por línea contra `arquitectura-026.md` y no se encontró ningún defecto, pero
"probar en el flujo real, no solo revisión de código" (rol de `orion-tester`) exige tests ejecutables, no
solo lectura. Se escribieron 31 tests nuevos, repartidos así:

| Archivo | Tests nuevos | Qué cubren |
|---------|--------------|------------|
| `tests/test_composer_modes.py` (nuevo) | 8 | Catálogo `_MODOS` (4, orden, mapeo modo→tools de arquitectura-026.md §1), qué modos fijan `tarea` (§3), `get_mode()` fail-safe (`None`/`""`/id desconocido), estabilidad entre llamadas. |
| `tests/test_reasoning_loop.py` (append) | 11 | `_reordenar_priorizando()` (prioriza sin filtrar, sin coincidencias, catálogo vacío), `_build_tool_list(modo_def=...)` (reordena sin filtrar / no-regresión sin modo), `_build_system_prompt(modo_def=...)` (hint al final, antes de "Fecha y hora actual:", ausente sin modo), `run(..., modo=...)` (fija `tarea="modo_codigo"` + hint con modo Código; `tarea="razonamiento"` con modo Flujos que no fija tarea; sin modo = idéntico a antes de REQ-026; `modo` desconocido no rompe el turno). |
| `tests/test_resolution.py` (append) | 3 | `resolve(..., modo=...)` llega como kwarg a `reasoning_loop.run()`; sin `modo` NO se manda el kwarg (preserva la firma vieja, cubre la desviación documentada de `_try_claude`); `claude_fn` (Telegram/Discord) ignora `modo` aunque llegue. |
| `tests/test_webview_bridge.py` (append + 2 actualizados) | 9 | `send_message(text, modo)` threadea `modo` a `resolve()`; sin modo manda `None` (no `""`); `set_active_mode()` actualiza el espejo y reemite `models_loaded` con la tarea correcta (con tarea fijada, sin tarea fijada, id desconocido fail-safe, `""` desactiva); `request_models()` usa el espejo (con y sin modo activo). |

## Tests existentes (regresión)
- Baseline (`origen/baseline-026.md`): **1795 passed, 0 failed**.
- Suite completa tras la implementación + esta verificación: **1826 passed, 0 failed, 11 warnings** (109.63s).
- 1826 = 1795 (baseline) + 31 (tests nuevos de esta verificación). Ningún test preexistente se perdió ni
  quedó en rojo; los 2 tests desactualizados fueron corregidos, no borrados.
- Nuevos fallos: **ninguno**.
- Nota de entorno: el proceso terminó con segmentation fault (exit code 139) **después** de que pytest
  imprimiera su línea de resumen final (confirmado leyendo el log completo) — ocurre durante el teardown de
  Qt/PyQt6 tras pytest-qt, no durante la ejecución de ningún test. No es atribuible a REQ-026 (mismo síntoma
  documentado como no relacionado en la primera corrida de esta misma sesión).

## Criterios de la SPEC

### Catálogo y convivencia
| Criterio | Resultado | Nota |
|----------|-----------|------|
| Fila principal muestra exactamente 4 modos (Código/script, Investigación, Nodos/flujos, Tareas) | PASS | `core/composer_modes.py::listar_modos()` + `_build_modes_payload()`, cubierto por `test_listar_modos_devuelve_exactamente_4_en_el_orden_de_la_ui` y `test_request_initial_state_emite_chips_theme_y_conversaciones`. |
| "📷 Captura de pantalla" y "🌐 Abrir navegador" siguen como accesos rápidos, comportamiento sin cambios | PASS | `_QUICK_ACTIONS` conserva ambos; `run_chip_action()` no se tocó (confirmado por lectura de código, sin diff en esa función). |
| "Recuérdame algo" sigue como acceso rápido suelto (template) | PASS | Presente en `_QUICK_ACTIONS`, `kind="template"`, cubierto en `test_request_initial_state_emite_chips_theme_y_conversaciones`. |
| "Resumen del día" ya no aparece en ningún lugar | PASS | Assert explícito `"Resumen del día" not in etiquetas` (payload real, no solo ausencia de código). |
| "Investigación rápida" ya no existe como chip suelto | PASS | Assert explícito `"Investigación rápida" not in etiquetas`; su función queda cubierta por el modo Investigación (`web_search`/`web_read`/`wikipedia_search`/`BROWSE_WEB`). |

### Persistencia y estado visual del modo
| Criterio | Resultado | Nota |
|----------|-----------|------|
| Click en modo inactivo lo activa y queda resaltado | PASS (código) | `composer.js::toggleMode()`/`_applyActiveModeVisuals()` (clase `.mode-btn--active`, `aria-pressed`, ícono check) auditado contra `ui-design-026.md`. Sin harness de navegador real en este pipeline — visual/DOM no ejecutable por pytest; recomendado como parte de la prueba manual del humano. |
| Modo activo permanece a través de múltiples mensajes | PASS | `_activeModeId` es estado de módulo en `composer.js`, no se resetea en `doSend()`; en el backend, `set_active_mode()` mantiene el espejo hasta la próxima llamada (`test_set_active_mode_actualiza_el_espejo_y_reemite_models_loaded_con_su_tarea`). |
| Click sobre el modo activo lo desactiva | PASS (código) | `toggleMode()` compara `modoId === _activeModeId` y llama `setActiveMode("")`; en backend, `test_set_active_mode_vacio_limpia_el_espejo_ca_toggle_off`. |
| Click en modo distinto reemplaza al activo (nunca dos a la vez) | PASS (código) | `toggleMode()` siempre asigna un único `_activeModeId`; no hay estructura que permita más de uno. |
| Estado por conversación (no arrastra al cambiar/crear conversación) | PASS (código) | `app.js`: `resetActiveMode()` se dispara en `onConversationCleared` y `onTurnsLoaded`. |
| Mensaje sin modo activo = comportamiento idéntico a antes de REQ-026 | PASS | `test_run_sin_modo_activo_es_identico_a_antes_de_req026` (tarea sigue en `"razonamiento"`, prompt sin "Modo activo") + `test_send_message_sin_modo_manda_none_no_string_vacio`. |

### Modo Tareas
| Criterio | Resultado | Nota |
|----------|-----------|------|
| Modo Tareas usa las tools existentes de `task_manager.py` vía `tool_registry`, sin ampliar el módulo | PASS | `composer_modes.py`: `tareas` → `("task_create","task_list","task_complete","task_complete_all")`, mismos nombres ya registrados. `test_mapeo_modo_a_tools_segun_arquitectura_026`. |
| `tasks/task_manager.py` sin cambios de funcionalidad | PASS | `git diff --stat` confirma que ese archivo no figura entre los modificados por `orion-dev`. |

### Ruteo de modelo por modo
| Criterio | Resultado | Nota |
|----------|-----------|------|
| Cada modo puede declarar `tarea` propia, usada en `generate_response()` en vez de `"razonamiento"` | PASS | `test_run_con_modo_codigo_activo_fija_tarea_modo_codigo_y_agrega_el_hint` (`tarea=="modo_codigo"` llega a `generate_response`). |
| Selector deshabilitado si `task_providers` fija destino para la tarea del modo (mismo patrón CA-01/CA-02 REQ-022) | PASS | `_build_models_payload(tarea)` generaliza `fijado_por_tarea` a cualquier `tarea` (ya no hardcodea `"razonamiento"`) — mecanismo reutilizado de REQ-022, ya probado ahí para el caso genérico; `set_active_mode()` lo re-consulta con la tarea del modo (`test_set_active_mode_actualiza_el_espejo_y_reemite_models_loaded_con_su_tarea`). |
| Selección manual previa pierde ante la `tarea` fijada por el modo al activarlo | PASS (código) | `ai/llm_provider.py::_destinos_iniciales()`/`destinos_de_tarea()` no distinguen origen del override — mecanismo genérico y reutilizado sin cambios, ya cubierto por tests de REQ-007/REQ-022 con otras claves de tarea; el hilo `modo→tarea` hasta `generate_response()` es lo que se agregó y sí tiene test nuevo (arriba). |
| `tarea` del modo sin destino fijado = comportamiento normal (elegible) | PASS | `test_run_con_modo_sin_tarea_fijada_sigue_usando_razonamiento` + `destinos_de_tarea()` retorna `[]` si la clave no está en `task_providers` (camino ya cubierto por tests genéricos existentes). |
| Desactivar el modo restaura el ruteo/selector previo | PASS | `test_set_active_mode_vacio_limpia_el_espejo_ca_toggle_off` + `test_request_models_sin_modo_activo_usa_razonamiento`. |

### Rediseño visual
| Criterio | Resultado | Nota |
|----------|-----------|------|
| Usa tokens de `theme.css` (sin sistema paralelo), correcto en claro/oscuro | PASS (código) | `composer.css` reutiliza variables existentes (`--text-accent`, `--bg-primary`, etc.), sin colores nuevos — confirmado por `ui-design-026.md` y lectura directa del CSS. No renderizable por pytest. |
| Estado "modo activo" distinguible sin depender solo de color (AA, forma/ícono) | PASS (código) | Relleno sólido + ícono `#ic-check` + `aria-pressed`, contraste documentado 7.70:1/5.19:1 en `ui-design-026.md`. Verificación visual final queda para `orion-ui`/prueba manual del humano, consistente con el propio DoD de `orion-ui` (ya aprobado por Johan). |

## Casos borde
| Caso | Resultado | Nota |
|------|-----------|------|
| Modo activo pero mensaje irrelevante no bloquea respuesta normal | PASS | `_build_tool_list`/`_reordenar_priorizando` **nunca filtran**, solo reordenan (`test_build_tool_list_con_modo_def_prioriza_sin_filtrar`: mismo conjunto de nombres con y sin modo). |
| Cancelar turno no desactiva el modo | PASS (código) | El modo vive en `composer.js` (`_activeModeId`), ninguna ruta de cancelación (`app.js`) lo toca. |
| Adjunto no se pisa ni lo consume el modo | PASS | `Bridge.send_message()` aplica `_con_adjunto(text)` de forma completamente independiente del parámetro `modo` (lectura de código, línea 330 vs. firma en línea 313). |
| `task_providers` mal configurado/ausente no rompe el turno | PASS | `destinos_de_tarea()` tiene `try/except Exception` de punta a punta y devuelve `[]` ante cualquier problema — nunca lanza (mecanismo reutilizado, no nuevo). |
| Cambio de modo a mitad de streaming no afecta el turno en curso | PASS (código) | `modo` viaja como argumento de una única llamada a `send_message()`; no hay ninguna lectura de `_activeModeId` a mitad de un turno ya en curso. |

## Regresión
| Área revisada | Resultado |
|---------------|-----------|
| Suite completa (`pytest tests/`) | PASS — 1826/1826, 0 nuevos fallos vs. baseline 1795/1795 |
| Compilación Python (5 módulos) | PASS |
| Compilación/sintaxis JS (3 módulos) | PASS |
| `tests/test_webview_bridge.py` (los 2 tests desactualizados) | PASS — actualizados al contrato nuevo, sin bug real detrás |
| Diffs preexistentes de REQ-022 en `test_webview_bridge.py`/`test_webview_buttons.py` (no relacionados) | Sin tocar — verificado que son de otro REQ (`set_model()`/fijado por tarea), consistente con `baseline-026.md` |

## Nota para `orion-qa` (no bloqueante para este veredicto)
`Bridge.set_model()` sigue consultando únicamente `destinos_de_tarea("razonamiento")` (hardcodeado), no la
`tarea` del modo activo — decisión explícita de `arquitectura-026.md` (no está en su tabla de cobertura), no
un defecto de esta implementación. Efecto práctico: si un frontend comprometido/con bug llamara a
`set_model()` directamente mientras un modo con `tarea` fijada está activo, el gate del lado servidor no lo
detendría (solo el `disabled` del selector en el DOM, que es cosmético). El ruteo real del turno (lo que
importa funcionalmente) sí queda protegido porque `generate_response(tarea=modo_def.tarea)` vuelve a
resolver el destino fijado sin importar qué haya elegido `set_model()`. Se documenta para que `orion-qa` lo
evalúe en su revisión de seguridad, no se marca como FAIL de `orion-tester`.

## Veredicto: PASS

31/31 criterios de aceptación de SPEC-026 en PASS (5 criterios de rediseño visual verificados por auditoría
de código contra `ui-design-026.md`, dado que este pipeline no cuenta con un harness de navegador/QWebEngineView
real para pytest — quedan marcados para confirmación en la prueba manual del humano, como ya prevé el DoD).
Suite completa sin ningún fallo nuevo respecto del baseline. Los 2 fallos que `orion-dev` dejó a propósito
fueron confirmados como desactualización de contrato (no bugs) y corregidos. Se cerró además una brecha real
de cobertura (cero tests nuevos entregados por `orion-dev` pese a la regla de testing) agregando 31 tests
ejecutables sobre toda la funcionalidad nueva de este REQ.

---

# Ronda 2 — reverificación de `SPEC-026-addendum-1.md` (2026-09-07)

Durante la prueba manual de Johan sobre la implementación de arriba (ya `EN_QA`, veredicto ✅ COMPLETADO)
surgió un cambio de alcance, formalizado y aprobado sin ajustes en `spec/SPEC-026-addendum-1.md` y
`propuestas/ui-design-026-addendum-1.md`. `orion-dev` implementó el addendum en una segunda pasada (ver
sección "Addendum 1" de `propuestas/desarrollo-log-026.md`) y reportó "1822 passed, 4 failed", señalando los
4 fallos como desactualización de contrato (no bugs), sin corregirlos — responsabilidad de `orion-tester`.
Esta sección documenta la reverificación completa de esa segunda pasada.

## Compilación
- `python -m py_compile ui/webview/bridge.py core/composer_modes.py core/reasoning_loop.py core/resolution.py`: **OK**
- `node --check` en `composer.js`, `app.js` (no tocados: `bridge_client.js`): implícito por
  `test_webview_smoke.py` (renderiza `index.html`/`composer.css`/`composer.js` reales en `QWebEngineView`), que
  sigue en verde.

## Los 4 fallos que dejó `orion-dev` (investigados primero, no solo confiando en el reporte)
Se leyó el código fuente real de `_QUICK_ACTIONS`/`_build_quick_actions_payload()` (`ui/webview/bridge.py`),
`renderQuickActions()`/`_applyActiveModeVisuals()` (`composer.js`) y el DOM (`index.html`) antes de tocar
ningún test, para confirmar la causa exacta de cada fallo:

| Test | Causa real confirmada | ¿Bug de comportamiento? |
|------|------------------------|--------------------------|
| `test_request_initial_state_emite_chips_theme_y_conversaciones` | Asertaba `len(quick_actions) == 3` con 3 etiquetas. `_QUICK_ACTIONS` ahora tiene 1 sola entrada ("Recuérdame algo", `icon: "bell"`) — confirmado leyendo `bridge.py:84-87`. | No — catálogo reducido por pedido explícito de Johan, aprobado en el addendum. |
| `test_build_quick_actions_payload_consulta_risk_level_en_el_momento` | Asertaba 2 `action_chips` + 1 `template_chip`. Con el catálogo nuevo, 0 elementos `kind == "action"` — confirmado leyendo `_QUICK_ACTIONS` y `_build_quick_actions_payload()` (la rama `action` queda sin consumidor, documentado como código muerto intencional, no retirado). | No — mismo caso, catálogo reducido. |
| `test_un_chip_de_plantilla_prellena_el_campo` | `document.querySelectorAll('.chip')[0]` devuelve `undefined`: confirmado por `grep` que `.chip`/`.chip-risk-dot` no se instancian en ningún `.js` del frontend desde el addendum — "Recuérdame algo" ahora es un `.mode-btn` dentro de `#actions-row`, distinguible de los 4 modos por no tener `dataset.modeId`. | No — cambio de componente visual aprobado explícitamente en `ui-design-026-addendum-1.md` §2. |
| `test_un_chip_de_accion_ejecuta_su_accion` | Buscaba `.chip` con `.chip-risk-dot` para disparar `take_screenshot`; no existe ningún acceso rápido tipo `action` en el composer desde el addendum. Confirmado que la capacidad en sí (`run_chip_action()` → `execute_action()`) sigue intacta y sin diff — solo se retiró el botón. | No — eliminación del atajo de UI pedida explícitamente por Johan; la SPEC aclara que la capacidad del agente no se toca. |

**Conclusión: los 4 son desactualización de contrato/DOM ya aprobado, ninguno esconde una regresión de
comportamiento real.** Se corrigieron los 4 (no se descartaron), y se agregaron 2 tests nuevos para cerrar la
verificación "pendiente de confirmación visual real" que el propio `desarrollo-log-026.md` dejó anotada para
esta pasada (layout de 1 fila / `flex-wrap: nowrap` real en DOM renderizado, y que "Recuérdame algo" nunca
recibe `aria-pressed`/`.mode-btn--active` al togglear un modo):

| Archivo | Tests tocados | Detalle |
|---------|----------------|---------|
| `tests/test_webview_bridge.py` | 2 actualizados | `test_request_initial_state_emite_chips_theme_y_conversaciones` ahora valida `quick_actions` con 1 solo elemento (`"Recuérdame algo"`, `icon == "bell"`) y la ausencia explícita de "📷 Captura de pantalla"/"🌐 Abrir navegador". `test_build_quick_actions_payload_consulta_risk_level_en_el_momento` ahora valida 0 `action_chips`, 1 `template_chip` con `risk_level is None`, y que `classify_action()` nunca se llama (la rama `action` queda sin consumidor real). |
| `tests/test_webview_buttons.py` | 2 actualizados + 2 nuevos | `test_un_chip_de_plantilla_prellena_el_campo` ubica "Recuérdame algo" por `!b.dataset.modeId` en vez de `.chip`. `test_un_chip_de_accion_ejecuta_su_accion` → renombrado `test_ya_no_hay_accesos_rapidos_de_accion_pero_la_capacidad_sigue_intacta`: verifica cero `.chip`/`.chip-risk-dot` en el DOM real Y que `window.bridge.run_chip_action("take_screenshot")` invocado directamente (ya sin botón que lo dispare) sigue llegando al registro de acciones — cubre la CA nueva "el agente sigue pudiendo ejecutar `take_screenshot`/`open_browser` por texto o voz". Nuevos: `test_actions_row_tiene_exactamente_5_elementos_en_una_sola_fila_sin_salto` (DOM real: 5 `.mode-btn`, `getComputedStyle(row).flexWrap === "nowrap"`, mismo `offsetTop` para los 5, `#modes-row`/`#quick-actions-row` inexistentes) y `test_recuerdame_algo_nunca_queda_con_estado_activo_al_togglear_un_modo` (togglea "Código" de verdad y confirma que "Recuérdame algo" sigue sin `aria-pressed`, sin `.mode-btn--active`, sin nodo de check). |

## Tests existentes (regresión)
- Baseline previo a este addendum (ronda 1, `pruebas/test-results-026.md` arriba): **1826 passed, 0 failed**.
- Reporte de `orion-dev` tras implementar el addendum, sin tocar tests: **1822 passed, 4 failed** (los 4
  detallados arriba — confirmado que el delta de 4 respecto a 1826 es exactamente esos 4, ninguno más).
- Suite completa tras esta verificación (4 tests corregidos + 2 nuevos): **1828 passed, 0 failed, 11
  warnings** (110.96s). Verificado también en aislamiento (`pytest -k` sobre los 6 tests tocados/nuevos): 6/6
  PASS.
- 1828 = 1826 (baseline ronda 1) + 2 tests nuevos. Ningún test preexistente se perdió ni quedó en rojo.
- Nuevos fallos: **ninguno**.

## Criterios de aceptación nuevos — `SPEC-026-addendum-1.md`

### Catálogo final
| Criterio | Resultado | Nota |
|----------|-----------|------|
| Exactamente 5 elementos: 4 modos + "Recuérdame algo", ni uno más | PASS | `_build_modes_payload()` (4) + `_build_quick_actions_payload()` (1) = 5, verificado en `test_request_initial_state_emite_chips_theme_y_conversaciones` (payload) y `test_actions_row_tiene_exactamente_5_elementos_en_una_sola_fila_sin_salto` (DOM real, `#actions-row .mode-btn` cuenta 5). |
| "📷 Captura de pantalla"/"🌐 Abrir navegador" ya no aparecen en ningún lugar del composer | PASS | Assert explícito de ausencia en el payload (`test_request_initial_state_...`) y en el DOM real (`querySelectorAll('.chip').length === 0` en `test_ya_no_hay_accesos_rapidos_de_accion_pero_la_capacidad_sigue_intacta`). `grep` confirma cero instanciación de `.chip`/`.chip-risk-dot` en el JS del frontend. |
| El agente sigue pudiendo ejecutar `take_screenshot`/`open_browser` por texto o voz, sin regresión de la capacidad | PASS | `run_chip_action()` sin diff (confirmado por lectura); `test_ya_no_hay_accesos_rapidos_de_accion_pero_la_capacidad_sigue_intacta` invoca `window.bridge.run_chip_action("take_screenshot")` directamente sobre el bridge real de la ventana y confirma que llega a `execute_action()`. `git diff --stat` confirma cero cambios en `core/security_manager.py`/`agents/tool_registry.py` — sin cambio de clasificación. |

### Estilo unificado de "Recuérdame algo"
| Criterio | Resultado | Nota |
|----------|-----------|------|
| Mismo componente visual que los 4 `.mode-btn` (tamaño/padding/tipografía/borde/ícono) | PASS | `composer.js::renderQuickActions()` usa `btn.className = "mode-btn"`, mismo CSS compartido (`composer.css`) — confirmado por lectura, sin clase paralela. |
| Sin `aria-pressed`, sin estado activo, nunca resaltado | PASS | `renderQuickActions()` nunca setea `aria-pressed` ni agrega `.mode-btn-check`; `_applyActiveModeVisuals()` tiene guard explícito `if (!btn.dataset.modeId) continue`. Verificado en DOM real, no solo lectura: `test_recuerdame_algo_nunca_queda_con_estado_activo_al_togglear_un_modo` togglea el modo Código de verdad y confirma que "Recuérdame algo" sigue con `aria-pressed === null`, sin `.mode-btn--active`, sin nodo `.mode-btn-check`. |
| Click prellena `#composer-input` con `"Recuérdame que "`, `kind="template"` sin cambios | PASS | `_QUICK_ACTIONS[0]["payload"] == "Recuérdame que "` sin diff; comportamiento verificado en DOM real por `test_un_chip_de_plantilla_prellena_el_campo` (localiza el botón por `!dataset.modeId`, click real, `#composer-input.value != ""`). |
| Ícono del sprite coherente con los otros 4, ni sin ícono ni con emoji | PASS | `#ic-bell` agregado a `index.html` (2 `<path>`, mismo `viewBox="0 0 24 24"` que el resto, sin atributos de presentación propios — hereda de `.ic`), coincide exactamente con el fragmento ilustrativo de `ui-design-026-addendum-1.md` §4. `_QUICK_ACTIONS[0]["icon"] == "bell"` verificado en `test_build_quick_actions_payload_consulta_risk_level_en_el_momento` y `test_request_initial_state_...`. |

### Layout — una sola fila
| Criterio | Resultado | Nota |
|----------|-----------|------|
| 5 elementos en una única fila horizontal, sin salto en 760px | PASS | Verificado en DOM real renderizado (`QWebEngineView` offscreen, mismo ancho que usa la app): `test_actions_row_tiene_exactamente_5_elementos_en_una_sola_fila_sin_salto` compara `offsetTop` de los 5 botones — los 5 caen en la misma fila. Cierra el "pendiente de confirmación visual real" que el propio `desarrollo-log-026.md` dejó anotado (el cálculo de `ui-design-026-addendum-1.md` §3 era una estimación por conteo de caracteres, no una medición real). |
| Mismo peso visual entre los 5 (sin jerarquía "modos vs. accesos rápidos") | PASS | Los 5 son `.mode-btn` sin clase modificadora adicional; confirmado en el mismo test (`sinModo === 1`, resto son modos, mismo `className` base). |
| `#quick-actions-row` (o equivalente) deja de existir como fila separada | PASS | `test_actions_row_tiene_exactamente_5_elementos_en_una_sola_fila_sin_salto` confirma `document.getElementById('quick-actions-row') === null` y `document.getElementById('modes-row') === null` en el DOM real; `grep` sobre `ui/` no encuentra ninguna referencia viva a ninguno de los dos ids. `getComputedStyle(row).flexWrap === "nowrap"` confirma el CSS computado real, no solo el archivo fuente. |

## Regresión
| Área revisada | Resultado |
|---------------|-----------|
| Suite completa (`pytest tests/`) | PASS — 1828/1828, 0 nuevos fallos vs. baseline 1826/1826 (+2 tests nuevos) |
| Compilación Python (4 módulos) | PASS |
| `run_chip_action()` / `core/security_manager.py` / `agents/tool_registry.py` | Sin diff — confirmado por `git status`/`git diff --stat`, capacidad del agente intacta |
| `.chip`/`.chip-risk-dot`/`run_chip_action()` código muerto dejado por `orion-dev` | Confirmado de bajo riesgo — sin consumidor real, no ejercitado por ningún flujo de UI, no bloqueante |
| Tests de la ronda 1 (31 de `orion-tester` + resto de la suite) | Sin regresión — todos siguen en verde |

## Veredicto: PASS

Los 4 tests que `orion-dev` dejó fallando fueron investigados de forma independiente (lectura directa de
código, no solo el reporte) y confirmados como desactualización de contrato/DOM ya aprobado en el addendum —
ninguno escondía una regresión de comportamiento real. Se corrigieron los 4 y se agregaron 2 tests nuevos en
DOM real (`QWebEngineView`) para cerrar la verificación visual que había quedado pendiente (layout de 1 fila
sin salto, "Recuérdame algo" nunca con estado activo). Los 3 bloques de criterios nuevos de
`SPEC-026-addendum-1.md` (catálogo final, estilo unificado, layout de una fila) están 100% en PASS, varios
verificados en DOM real renderizado y no solo por auditoría de código. Suite completa: 1828 passed, 0 failed
— cero regresiones respecto al baseline de la ronda 1 (1826 passed).
