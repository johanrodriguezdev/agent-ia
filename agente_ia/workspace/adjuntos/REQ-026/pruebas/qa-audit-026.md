# Auditoría QA REQ-026 — Modos estratégicos en la barra del composer

**Agente:** orion-qa
**Fecha:** 2026-09-07
**Insumos leídos:** SPEC-026.md, arquitectura-026.md, ui-design-026.md, desarrollo-log-026.md,
test-results-026.md, REQ-026-context.md, más lectura directa de todos los diffs reales
(`git diff` contra HEAD) de los 9 archivos tocados y del contenido íntegro de
`core/composer_modes.py` (archivo nuevo).

## Metodología
No se confió únicamente en los reportes de `orion-dev`/`orion-tester`. Se releyó el diff real
de cada archivo (`core/composer_modes.py`, `ui/webview/bridge.py`, `core/resolution.py`,
`core/reasoning_loop.py`, `ui/webview/frontend/js/{composer,app,bridge_client}.js`,
`ui/webview/frontend/index.html`, `ui/webview/frontend/css/composer.css`), se corrió
`python -m py_compile` sobre los 4 módulos Python, y se re-ejecutó la suite dirigida
(`tests/test_composer_modes.py tests/test_reasoning_loop.py tests/test_resolution.py
tests/test_webview_bridge.py`): **178 passed, 0 failed**. Se confirmó además que
`agents/tool_registry.py`, `core/security_manager.py` y `tasks/task_manager.py` tienen **cero
diff** contra HEAD — el REQ no los toca, tal como afirman arquitectura y desarrollo-log.

## Seguridad

- **Secretos:** sin hallazgos. Grep de `api[_-]?key|secret|token|password` sobre los 9 diffs:
  cero coincidencias. Sin credenciales ni URLs con claves embebidas en ningún archivo nuevo o
  modificado.
- **`except: pass` silencioso:** sin hallazgos. `core/composer_modes.py` (archivo nuevo) no
  tiene ningún bloque `try/except`. `get_mode()` es fail-safe por diseño (`if not modo_id:
  return None`), no por captura de excepción — no hay nada que silenciar.
- **Acciones destructivas / confirmación:** el modo Código prioriza `EXECUTE_CODE`
  (`core/composer_modes.py`, tool_names). Confirmado por lectura directa de
  `agents/tool_registry.py::execute_tool()` (líneas 201-226, sin diff en este REQ): es el
  único punto de invocación real de cualquier tool, y llama a
  `security_manager.require_confirmation()` **antes** de `spec.invoke()`, sin importar en
  qué posición del catálogo apareció la tool. El mecanismo de REQ-026
  (`_reordenar_priorizando()`, `core/reasoning_loop.py`) solo cambia el ORDEN de la lista
  que ve el modelo al decidir qué tool pedir — nunca toca el gate de ejecución. Confirmado
  también que `EXECUTE_CODE` sigue clasificado 🟡 amarillo en `core/security_manager.py:643`
  (archivo sin diff). **Conclusión: priorizar la tool no saltea la confirmación existente.**
- **Niveles verde/amarillo/rojo:** ningún archivo de este REQ toca `security_manager.py`. El
  modo Código no crea ninguna vía nueva de ejecución, solo reordena qué ve el modelo primero.
  Los 4 modos son puramente UI + reordenamiento de catálogo + ruteo de `tarea` — ninguna
  acción nueva que requiera clasificación.
- **Superficie de canales remotos:** confirmado por lectura de `core/resolution.py::resolve()`
  y `_try_claude()` — el parámetro `modo` solo se lee en el camino `claude_fn is None`
  (escritorio). Los canales con `claude_fn` (Telegram/Discord) nunca leen `modo`, consistente
  con que los modos son un concepto exclusivo del composer de escritorio y no deben alcanzar
  canales remotos (mismo criterio que ya aplica `CHANNEL_ALLOWED_LEVELS` para acciones
  amarillas).
- **Hallazgo investigado y descartado como falso positivo propio:** al revisar
  `ui/webview/bridge.py::set_model()` se encontró un gate nuevo (`if destinos_de_tarea(
  "razonamiento"): ... return`) que en un primer vistazo parecía código no documentado de
  este REQ. Verificación con `git show HEAD:.../bridge.py` confirmó que ese gate NO existe en
  el último commit, así que se investigó su origen a fondo: pertenece a **REQ-022**
  (CA-03/CA-04, ver `workspace/adjuntos/REQ-022/propuestas/desarrollo-log-022.md:35` y
  `pruebas/qa-audit-022.md:44`), que tiene trabajo sin commitear en el mismo working tree
  (confirmado también en `baseline-026.md`, que documenta explícitamente cambios pendientes
  de otro REQ en `bridge.py`). **No es código de REQ-026**, `orion-dev` no lo tocó ni lo
  introdujo — el desarrollo-log-026.md ("`set_model()` queda sin tocar") es correcto respecto
  al alcance de este REQ.
- **Nota de `orion-tester` sobre `set_model()` — de acuerdo con el análisis:** ese gate de
  REQ-022 solo verifica `destinos_de_tarea("razonamiento")` (hardcodeado), no
  `self._tarea_activa()` — así que si un modo con `tarea` fijada está activo (Código/
  Investigación) y algo llamara a `set_model()` directo vía JS (bypaseando el `disabled` del
  DOM), el gate del lado servidor no lo bloquearía; sí quedaría reflejado como "Fijado" en el
  selector visual mientras tanto. Confirmado por lectura de `core/reasoning_loop.py::run()`:
  la `tarea` real de generación (`generate_response(tarea=tarea)`) se recalcula desde
  `modo_def.tarea` en cada llamada, **sin leer nunca** lo que `config_manager` tenga guardado
  de una invocación directa a `set_model()` — el ruteo real del turno queda protegido pase lo
  que pase con el selector. Es una inconsistencia cosmética de `config.json`
  (podría quedar con un `ai_provider`/`ai_model` que nunca se usa mientras el modo con tarea
  fijada esté activo), no una brecha de seguridad ni una regresión de REQ-026. Se registra
  como deuda conocida, no bloqueante — igual que ya lo dejó `orion-tester`. Si se quiere
  cerrar del todo, es trabajo de generalizar el gate de REQ-022 a `self._tarea_activa()`, algo
  que no le corresponde a este REQ ni fue pedido por su arquitectura.
- **Validación de inputs:** `Bridge.set_active_mode(modo_id: str)` y `send_message(text, modo)`
  resuelven `modo` vía `get_mode()`, fail-safe ante id vacío/desconocido — no hay ningún
  `eval`, `os.system` o `subprocess` involucrado en ningún archivo de este REQ.

## Niveles de riesgo
- **Verde (puede actuar):** todo el mecanismo de modos en sí (toggle de UI, reordenar
  catálogo de tools, elegir `tarea`) — no ejecuta nada, solo influye qué ve/prioriza el
  modelo.
- **Amarillo (debe confirmar):** `EXECUTE_CODE` (modo Código), ya clasificado así antes de
  este REQ, sin cambios. La confirmación sigue intacta (ver arriba).
- **Rojo (no ejecuta):** ninguna acción roja involucrada en este REQ.
- **Se implementaron confirmaciones:** no aplica — este REQ no agrega ninguna acción nueva
  amarilla/roja, solo prioriza el acceso a una tool amarilla ya existente y ya protegida.

## Logging
- `Bridge.send_message()` mantiene el `logger.warning` existente si hay una resolución en
  curso; sin cambios en el patrón de logging del archivo.
- `Bridge.set_active_mode()` no agrega logging propio (no lo necesita: no hay ninguna
  excepción posible de capturar — `get_mode()` es fail-safe por retorno, no por except).
- El gate heredado de REQ-022 en `set_model()` sí loguea (`logger.info`) cuando ignora una
  invocación — confirmado en el diff, consistente con `security-levels.md`.
- Sin hallazgos de `except`/error tragado en ningún archivo de este REQ.

## Consistencia de código
- Convenciones de `.claude/rules/python-style.md` respetadas: type hints en
  `core/composer_modes.py` (`Optional`, `Tuple`), `dataclass(frozen=True)` para un catálogo
  inmutable, docstrings imperativos, sin líneas de más de 100 caracteres revisadas
  puntualmente.
- Sin `print()` de debug en ningún archivo Python o JS tocado (grep dirigido, cero
  coincidencias).
- Sin dependencias nuevas — confirmado, `requirements.txt` sin diff en este REQ.
- Frontend: `composer.js` usa `textContent`/`document.createElement` para renderizar labels
  de modos y accesos rápidos (nunca `innerHTML` con datos del payload) — sin riesgo de
  inyección DOM vía el catálogo de modos/accesos rápidos.
- CSS: cero tokens de color/tipografía nuevos, reutiliza variables existentes de
  `theme.css`, tal como documenta `ui-design-026.md` — confirmado por lectura directa del
  diff de `composer.css`.

## Sobre la nota de `orion-tester` para QA (Bridge.set_model() hardcodeado)
Ver sección "Seguridad" arriba — **de acuerdo con el análisis de `orion-tester`**: no es un
defecto de REQ-026 (el gate pertenece a REQ-022, no a este REQ), y el ruteo real del turno
está protegido independientemente de lo que haga `set_model()`, porque `reasoning_loop.run()`
siempre recalcula `tarea` desde el modo activo antes de llamar a `generate_response()`. Se
confirma además, con evidencia adicional que `orion-tester` no tenía disponible (el origen
exacto del gate en REQ-022), que ni siquiera es código introducido por este REQ.

## Sobre la decisión de `orion-tester` de escribir 31 tests en vez de devolver a `orion-dev`
**Evaluación: decisión correcta en este caso concreto, con una observación de proceso.**
- Los 31 tests son reales, ejecutables, pasan (confirmado: se re-ejecutaron los 4 archivos
  de test dirigidos, 178 passed), y cubren funcionalidad genuina (catálogo de modos, reorden
  de tools, ruteo de `tarea`, threading de `modo` end-to-end) — no es cobertura superficial.
- El gap que cerraron es exactamente el que exige `.claude/rules/testing.md` ("Nuevo código:
  toda función pública debe tener al menos un test"), y `orion-dev` no lo cumplió — verificado
  independientemente: el grep que citó `orion-tester` (`composer_modes|set_active_mode|...`
  sobre `tests/`) efectivamente no tenía coincidencias antes de su intervención.
  El código en sí (auditado en esta revisión, línea por línea contra `arquitectura-026.md`)
  no tenía ningún defecto — la ausencia era pura falta de tests, no un bug que ameritara
  devolver a `orion-dev` para que lo arreglara.
- **Observación de proceso (no bloqueante para este REQ):** el rol de `orion-tester` según
  su definición es "verifica que el código compile y ejecuta los casos de prueba... si algún
  criterio falla, devuelve a `orion-dev`" — no "escribe la cobertura que falta". Escribir
  tests no es su función normal, y esto ya pasó antes (mencionado en el hallazgo mismo, sin
  ser la primera vez que `orion-dev` entrega sin tests). Corregirlo puntualmente en este REQ
  fue pragmático y de bajo riesgo (ningún fix de comportamiento, solo cobertura), pero si el
  patrón se repite en próximos REQs corresponde señalarlo a `orion-dev` de forma explícita
  como incumplimiento recurrente de DoD, no seguir compensándolo silenciosamente desde
  `orion-tester`.

## Checklist `.claude/rules/git.md`
```
[x] orion-qa verificó seguridad explícitamente (esta auditoría)
[ ] El humano hizo la prueba manual final y dio OK — PENDIENTE, se solicita a continuación
[x] requirements.txt actualizado si hay nuevas dependencias — no aplica, sin dependencias nuevas
[x] Sin API keys ni tokens hardcodeados
[x] Sin except: pass silencioso
[ ] El mensaje de commit incluye el REQ (feat(REQ-026): ...) — se entrega recién tras el OK del humano
```

## Veredicto: ✅ COMPLETADO

Sin hallazgos de seguridad. El mecanismo de priorización de `EXECUTE_CODE` en el modo Código
no saltea la confirmación amarilla existente (verificado en `execute_tool()`, sin diff en
este REQ). Sin secretos, sin `except: pass`, sin dependencias nuevas, sin tocar
`security_manager.py`/`tool_registry.py`/`task_manager.py`. La nota no bloqueante de
`orion-tester` sobre `Bridge.set_model()` fue investigada a fondo y se confirma correcta:
pertenece a REQ-022 (no a este REQ) y no compromete el ruteo real de ningún turno. La decisión
de `orion-tester` de cerrar la brecha de testing con 31 tests nuevos en vez de rebotar a
`orion-dev` se considera acertada para este caso puntual, con una observación de proceso (no
bloqueante) sobre el patrón recurrente de `orion-dev` de no entregar tests.

**Falta la prueba manual de Johan antes de cerrar el REQ.** No se ejecuta `git commit` bajo
ninguna circunstancia — el mensaje de commit se entrega recién después del OK explícito del
humano.

---

# Ronda 2 — reauditoría de `SPEC-026-addendum-1.md` (2026-09-07)

**Agente:** orion-qa
**Motivo:** durante la prueba manual final de Johan sobre el REQ ya aprobado en la ronda 1
(arriba) surgió un cambio de alcance, formalizado en `spec/SPEC-026-addendum-1.md` y
`propuestas/ui-design-026-addendum-1.md` (ambos aprobados por Johan sin ajustes),
implementado por `orion-dev` (sección "Addendum 1" de `propuestas/desarrollo-log-026.md`) y
reverificado por `orion-tester` (sección "Ronda 2" de `pruebas/test-results-026.md`,
veredicto PASS, 1828 passed/0 failed). Esta entrada reaudita **solo lo que cambió** en esta
ronda — no repite la auditoría de seguridad de la ronda 1 (secretos, `EXECUTE_CODE`/gate de
confirmación, `security_manager.py`/`tool_registry.py` sin diff), que sigue vigente porque
ninguno de esos archivos vuelve a tocarse en el addendum.

## Metodología
No se confió en los reportes de `orion-dev`/`orion-tester`. Se releyó el diff real
(`git diff`) de los 5 archivos que el addendum modifica (`ui/webview/bridge.py`,
`ui/webview/frontend/index.html`, `ui/webview/frontend/js/composer.js`,
`ui/webview/frontend/js/app.js`, `ui/webview/frontend/css/composer.css`), se confirmó por
`git diff --stat` que `core/security_manager.py`, `agents/tool_registry.py` y
`tasks/task_manager.py` tienen **cero diff** (ni en esta ronda ni en la anterior), se corrió
`python -m py_compile ui/webview/bridge.py` y `node --check` sobre los 3 módulos JS
tocados, y se re-ejecutó la suite completa de forma independiente (no solo la dirigida):
`python -m pytest tests/ --tb=short -q` → **1828 passed, 0 failed, 11 warnings, 115.17s**,
terminando con el mismo segmentation fault post-resumen (exit 139) durante el teardown de
Qt/PyQt6 ya documentado como no atribuible a ningún REQ (`pruebas/test-results-026.md`,
ronda 1) — confirmado leyendo el log completo: el segfault ocurre **después** de la línea
`1828 passed`, no durante la ejecución de ningún test.

**Nota de proceso sobre un falso indicio propio, investigado y descartado:** un intento
previo de correr solo la suite dirigida (`test_webview_bridge.py`, `test_webview_buttons.py`,
`test_composer_modes.py`, `test_reasoning_loop.py`, `test_resolution.py`, 5 archivos juntos)
reportó 3 fallos en `tests/test_resolution.py` (`test_traza_identica_por_canal_categoria_amarilla`,
`test_yellow_mismo_action_name_desktop_vs_voice`, `test_sin_modelo_el_gate_sigue_mandando`),
ninguno relacionado con `SPEC-026-addendum-1.md` ni con los 5 archivos que este addendum
toca. Se investigó antes de concluir nada: `python -m pytest tests/test_resolution.py
--tb=line -q` en aislamiento → **26 passed, 0 failed** — los 3 "fallos" no se reproducen
cuando ese archivo corre solo, y tampoco aparecen en la corrida de la suite completa
(1828/1828). Conclusión: contaminación de estado entre archivos de test al combinar
justo esa selección puntual de 5 (probablemente un mock/monkeypatch de
`test_webview_bridge.py`/`test_webview_buttons.py` que no se revierte del todo antes de que
corra `test_resolution.py` en esa combinación específica), no una regresión real de código
— la suite completa y el archivo en aislamiento son la fuente de verdad, y ambos están en
verde. No bloqueante para este veredicto; se deja registrado por transparencia de método,
no como hallazgo de QA.

## Seguridad (solo lo que cambió en el addendum)
- **Secretos:** sin hallazgos. Grep de `api[_-]?key|secret|token|password` sobre los 5
  diffs del addendum: cero coincidencias nuevas (las únicas coincidencias en
  `ui/webview/bridge.py` son nombres de campo/variable de entorno ya existentes desde antes
  de este REQ — `deepseek_api_key`, `ANTHROPIC_API_KEY`, etc. — sin diff en esa sección).
- **`except: pass` silencioso:** sin hallazgos. Los `except` de `ui/webview/bridge.py`
  siguen todos con captura nombrada y logging (`except Exception as e:`,
  `except ActionDenied as e:`, `except ValueError:` con `logger.warning` + `raise`, este
  último sin diff en el addendum). Ningún `except` nuevo en los 5 archivos tocados.
- **Eliminación de "📷 Captura de pantalla"/"🌐 Abrir navegador" del composer — la
  capacidad del agente no se tocó:** confirmado por lectura directa, no solo por el reporte.
  `run_chip_action()` (línea 1567 de `bridge.py`) es exactamente el mismo código que en la
  ronda 1, sigue siendo el único invocante real de `execute_action()` vía
  `agents.action_registry`, y sigue sin ningún consumidor de UI propio en el DOM (verificado
  con `grep` que ningún `.js` del frontend instancia `.chip`/`.chip-risk-dot`). La rama
  `kind == "action"` de `_build_quick_actions_payload()` queda sin elementos que la
  ejerciten (`_QUICK_ACTIONS` tiene una sola entrada `kind="template"`), documentada como
  código muerto intencional en el docstring de la función — no retirada, consistente con
  que la SPEC prohíbe explícitamente tocar la capacidad. Cero diff en
  `core/security_manager.py`/`agents/tool_registry.py` confirma que la clasificación de
  riesgo de `take_screenshot`/`open_browser` (si las tuviera registrada ese registry) no se
  movió.
- **"Recuérdame algo" nunca queda con estado de modo:** el riesgo real de este cambio de
  componente era que, al compartir `.mode-btn` con los 4 modos reales, terminara
  heredando por accidente `aria-pressed`/`.mode-btn--active` al togglear un modo distinto.
  Verificado en el diff de `composer.js::_applyActiveModeVisuals()`: itera
  `row.children` pero tiene el guard explícito `if (!btn.dataset.modeId) continue;` antes
  de tocar `aria-pressed`/la clase activa/el check — "Recuérdame algo" nunca recibe
  `dataset.modeId` (ni en `renderQuickActions()` ni en ningún otro lugar), así que el guard
  lo excluye siempre. No es solo lectura de código: `orion-tester` lo verificó además en
  DOM real (`test_recuerdame_algo_nunca_queda_con_estado_activo_al_togglear_un_modo`,
  confirmado que existe y pasa, ver "Regresión" abajo).
- **Ícono nuevo (`#ic-bell`) — sin superficie de riesgo:** es un `<symbol>` SVG estático
  agregado al sprite de `index.html`, dos `<path>` sin atributos de presentación propios
  (hereda `currentColor`/`stroke-width` de `.ic` en `icons.css`, igual que los 26 símbolos
  existentes) — no ejecuta nada, no es contenido dinámico, no hay vector de inyección.
- **Inserción DOM del nuevo `renderQuickActions()`:** sigue usando `textContent`/
  `document.createElement`/`icon()` (que a su vez usa `createElementNS` + `setAttribute`,
  nunca `innerHTML`) para pintar "Recuérdame algo" — mismo patrón seguro que
  `renderModes()`, sin riesgo de inyección vía el payload del catálogo.
- **Superficie de canales remotos:** el addendum no toca `core/resolution.py` ni
  `core/reasoning_loop.py` (confirmado, no están entre los 5 archivos con diff en esta
  ronda) — el parámetro `modo` y su exclusión de Telegram/Discord, ya auditados en la ronda
  1, siguen sin cambios.

## Niveles de riesgo
- **Verde:** todo el cambio de este addendum es UI pura (eliminar 2 botones, cambiar el
  componente visual de un tercero, fusionar 2 filas en 1, agregar un ícono) — no crea, no
  mueve y no reclasifica ninguna acción.
- **Amarillo:** sin cambios respecto a la ronda 1 (`EXECUTE_CODE` del modo Código sigue
  igual de protegido, sin diff en el gate).
- **Rojo:** ninguna acción roja involucrada.
- **Se implementaron confirmaciones:** no aplica — no hay ninguna acción nueva que
  confirmar; al contrario, este addendum **reduce** la superficie de UI (2 botones menos)
  sin tocar el mecanismo de confirmación que sigue protegiendo `take_screenshot`/
  `open_browser` cuando se invocan por texto/voz.

## Logging
- Sin hallazgos nuevos. `Bridge.set_active_mode()`/`_tarea_activa()` (sin diff en este
  addendum, ronda 1) siguen sin necesitar logging propio por ser fail-safe por retorno.
  Ningún `except` nuevo que silenciar en los 5 archivos de esta ronda.

## Consistencia de código
- `.claude/rules/python-style.md`: sin violaciones nuevas en el diff de `bridge.py`
  (docstrings imperativos, sin líneas evidentemente por encima de 100 caracteres en los
  bloques tocados, type hints preservados en las firmas sin cambios de este addendum).
- Sin `print()` de debug en ningún archivo tocado (grep dirigido, cero coincidencias).
- Sin dependencias nuevas — confirmado, `requirements.txt` sin diff en el addendum.
- **Código muerto dejado a propósito, y bien documentado como decisión — no como
  descuido:** verificado en 3 lugares distintos que la decisión está señalada
  explícitamente, no simplemente omitida:
  1. `ui/webview/bridge.py`, docstring de `_build_quick_actions_payload()`: explica que la
     rama `action` queda sin consumidor "se deja sin retirar por si vuelve a necesitarse...
     no es lo mismo que código a borrar a ciegas".
  2. `ui/webview/frontend/css/composer.css`, comentario sobre `.mode-btn`: señala que
     `.chip` "queda sin consumidores en el composer tras el addendum 1... no se retira del
     CSS" — y en el diff se confirma que las reglas `.chip`/`.chip:hover`/
     `.chip:focus-visible`/`.chip-risk-dot`/`.chip-risk-green|yellow|red` siguen presentes
     e intactas en el archivo (`grep -n ".chip" composer.css` las lista todas).
  3. `propuestas/desarrollo-log-026.md` y `REQ-026-context.md`, sección "Decisiones de
     implementación"/"Descartado", documentan el mismo criterio para
     `run_chip_action()`/la rama `action`.
  Es una decisión explícita y trazable en 3 documentos independientes, con el motivo
  correcto (la SPEC prohíbe tocar la capacidad `take_screenshot`/`open_browser`, retirar el
  mecanismo hubiera sido cambio de alcance no pedido) — no un olvido.
- Frontend: `renderQuickActions()` reescrito sigue el mismo patrón seguro que el resto del
  módulo (ver "Seguridad" arriba).

## Regresión
| Área revisada | Resultado |
|---|---|
| Suite completa (`pytest tests/`), corrida propia e independiente | **1828 passed, 0 failed**, 11 warnings, 115.17s — idéntico al número reportado por `orion-tester` en la ronda 2 de `test-results-026.md`. Termina con el mismo segfault post-resumen de Qt/PyQt6 en teardown (exit 139), ocurre después de la línea de resumen, no atribuible a ningún test — mismo síntoma ya documentado y no nuevo de esta ronda. |
| `test_resolution.py` en aislamiento | 26 passed, 0 failed — descarta que los 3 "fallos" vistos en una combinación puntual de 5 archivos sean una regresión real (ver "Nota de proceso" arriba). |
| Compilación Python (`bridge.py`) | OK |
| Sintaxis JS (`composer.js`, `app.js`) | OK (`node --check`) |
| `core/security_manager.py` / `agents/tool_registry.py` / `tasks/task_manager.py` | Cero diff — confirmado por `git diff --stat`, ni en esta ronda ni en la anterior |
| Tests nuevos de `orion-tester` (ronda 2): `test_actions_row_tiene_exactamente_5_elementos_en_una_sola_fila_sin_salto`, `test_recuerdame_algo_nunca_queda_con_estado_activo_al_togglear_un_modo`, `test_ya_no_hay_accesos_rapidos_de_accion_pero_la_capacidad_sigue_intacta` | Confirmados presentes en `tests/test_webview_buttons.py` (líneas 394/417/453) por lectura directa del archivo, no solo por el nombre citado en el reporte |
| Ícono `#ic-bell` → wiring end-to-end | `_QUICK_ACTIONS[0]["icon"] == "bell"` (`bridge.py:86`) → `renderQuickActions()` llama `icon(chip.icon)` → `icon("bell")` (`icons.js`) arma `href="#ic-bell"` → símbolo existe en el sprite de `index.html` con ese id exacto. Cadena completa verificada archivo por archivo, no solo el extremo final. |

## Veredicto: ✅ COMPLETADO

Sin hallazgos de seguridad nuevos. La eliminación de los 2 accesos rápidos de UI
("📷 Captura de pantalla"/"🌐 Abrir navegador") no tocó la capacidad real del agente —
`run_chip_action()`, `core/security_manager.py` y `agents/tool_registry.py` están sin diff,
confirmado por lectura directa. "Recuérdame algo" nunca hereda estado de modo activo
(guard explícito en `_applyActiveModeVisuals()`, verificado en código y en DOM real por
`orion-tester`). El código muerto dejado (`.chip`/`.chip-risk-dot`, la rama `kind=="action"`
de `_build_quick_actions_payload()`) está documentado como decisión explícita en 3 lugares
independientes, no como descuido. Suite completa reejecutada de forma independiente:
1828 passed, 0 failed, coincide exactamente con lo reportado por `orion-tester`. Una
combinación puntual de 5 archivos de test mostró 3 fallos no relacionados con este addendum
que no se reprodujeron ni en el archivo aislado ni en la suite completa — investigado y
descartado como contaminación de estado entre tests, no una regresión.

## Checklist `.claude/rules/git.md`
```
[x] orion-qa verificó seguridad explícitamente (esta reauditoría, ronda 2)
[ ] El humano hizo la SEGUNDA prueba manual final y dio OK — PENDIENTE, se solicita a continuación
[x] requirements.txt actualizado si hay nuevas dependencias — no aplica, sin dependencias nuevas
[x] Sin API keys ni tokens hardcodeados
[x] Sin except: pass silencioso
[ ] El mensaje de commit incluye el REQ (feat(REQ-026): ...) — se entrega recién tras el OK del humano
```

**Falta la SEGUNDA prueba manual de Johan antes de cerrar el REQ** (la primera fue la que
generó este addendum — el cambio de alcance ya está incorporado y verificado). No se
ejecuta `git commit` bajo ninguna circunstancia — el mensaje de commit se entrega recién
después del OK explícito del humano sobre esta segunda ronda.
