# Auditoría QA REQ-013 — Rediseño UI escritorio NODDOO estilo chat de IA

**Agente:** orion-qa · **Fecha:** 2026-08-17
**Entradas revisadas:** `REQ-013-context.md`, `spec/SPEC-013.md` (22 CA), `pruebas/test-results-013.md`
(veredicto PASS, 22/22, 2 pasadas), `propuestas/desarrollo-log-013.md` (incl. 2da pasada fix CA-03),
`propuestas/arquitectura-013.md`. Verificación hecha contra el código real (`git diff`, lectura
directa de los módulos tocados), no solo contra los reportes de `orion-dev`/`orion-tester`.

## Seguridad

- **Secretos:** `grep` de `api[_-]?key|secret|token|password|bearer` sobre los 15+ archivos nuevos/
  modificados (`ui/theme.py`, `ui/widgets/chat_bubble.py`, `chat_feed.py`, `composer.py`,
  `conversation_list.py`, `ui/gui.py`, `ai/memory_manager.py`, `config_manager.py`) — sin
  hallazgos. Las únicas coincidencias son el mapa `_ENV_KEY_MAP` preexistente de
  `config_manager.py` (nombres de variables de entorno, no valores) y comentarios/nombres de
  función relacionados con `qss_tokens`/`Template`. Confirmado con `git diff -- config_manager.py`
  que ese bloque es preexistente, no tocado por REQ-013.
- **Gate fail-closed de chips de acción (CA-19):** confirmado en `ui/widgets/composer.py:184-199`
  — `_on_chip_clicked()` para `kind="action"` llama exclusivamente
  `run_async(execute_action, self._on_action_done, self._on_action_error, chip["payload"],
  channel=ChannelType.DESKTOP, user_id="default")`. La función subyacente (`take_screenshot`,
  `open_browser`) nunca se importa ni se invoca directo — solo se importa `execute_action` de
  `agents/action_registry.py`. Cubierto además por
  `tests/test_chat_widgets.py::test_composer_chip_accion_llama_execute_action_con_channel_desktop`.
  Sin hallazgos.
- **`ALTER TABLE ADD COLUMN` sobre `ai/unified_memory.db` (idempotencia):** confirmado en
  `ai/memory_manager.py:125-146` (`_migrate_schema`). Antes de cada `ALTER` consulta
  `PRAGMA table_info(memories)` y solo agrega la columna que falta; corrida N veces no vuelve a
  alterar nada. `ADD COLUMN` sin `NOT NULL`/`DEFAULT` es O(1) en SQLite (no reescribe la tabla, sin
  `DROP`/`RENAME`/copia). Todo el bloque está envuelto en `try/except Exception as e:
  logger.error(...)` — no es un `except: pass` silencioso, y una migración fallida no deja la DB a
  medio migrar (SQLite ejecuta cada `ALTER` como sentencia atómica propia). Sin hallazgos de
  seguridad ni de integridad en este punto.
- **Niveles verde/amarillo/rojo:** correcto clasificar el REQ como 🟢 Verde completo — no hay acción
  destructiva nueva, los colores nunca vienen de `config.json` (solo el nombre del tema, normalizado
  por `resolve_theme_name()`), y la única escritura nueva a disco de usuario (`ui_theme` en
  `config.json`) sigue el mismo precedente 🟢 que `display_name`/`weather_city`.
- **`except Exception: pass` de `main.py` (~línea 173):** confirmado con `git diff -- main.py` que
  el único cambio real en `main.py` en el working tree es de REQ-011 (flag `--tray`), NO de
  REQ-013. El `except Exception: pass` de la sección `# Guardar embedding semántico` sigue
  exactamente igual, preexistente, y `main.py` no fue tocado por este REQ. Confirmado que
  `desarrollo-log-013.md` y `arquitectura-013.md` documentan correctamente este hallazgo como fuera
  de alcance — no se coló en el código nuevo de REQ-013 ni se atribuye erróneamente.

## Niveles de riesgo

- **Verde (puede actuar):** cambio de tema (solo selecciona entre 2 paletas constantes), lectura de
  conversaciones/turnos, feed de burbujas, chips de plantilla (solo prellenan texto).
- **Amarillo (debe confirmar):** ninguno nuevo en este REQ.
- **Rojo (no ejecuta):** ninguno nuevo en este REQ.
- **Se implementaron confirmaciones:** N/A — no hay acciones amarillas/rojas nuevas. Los 2 chips de
  acceso directo (`take_screenshot`, `open_browser`) ya eran 🟢 Verde antes de este REQ y pasan por
  el mismo gate fail-closed que `QuickActionsCard`.

## Logging

- `store_turn()`, `list_conversations()`, `get_conversation_turns()`, `_migrate_schema()`: todos con
  `try/except Exception as e: logger.error/warning(...)`, ninguno silencioso. Casos borde (texto de
  usuario o respuesta vacíos en `store_turn`) registran `logger.warning` explícito en vez de fallar
  silenciosamente.
- `CallableWorker.run()` (preexistente, `ui/gui_workers.py`, no tocado por REQ-013): captura la
  excepción, hace `logger.error(...)` y emite la señal `error` — confirmado que aplica también a la
  llamada `run_async(memory.store_turn, None, None, ...)` (sin callbacks `on_done`/`on_error`): si
  `store_turn()` lanzara una excepción no capturada internamente, quedaría logueada igual, no
  perdida en silencio.
- Sin `except: pass` nuevo en ningún archivo tocado por REQ-013 (verificado por `grep` dirigido +
  lectura completa de los módulos nuevos).

## Consistencia de código

- Type hints presentes en las funciones nuevas de `ai/memory_manager.py`, `ui/theme.py` y los 4
  widgets nuevos. Naming `snake_case`/`PascalCase` consistente. Sin `print()` de debug (`grep`
  limpio). Uso correcto de `string.Template` (nunca `.format()`) en los 5 módulos con QSS nuevo,
  como exige la arquitectura.
- `desarrollo-log-013.md` documenta con motivo cada desviación menor respecto de la arquitectura
  aprobada (2 hex de paleta, `CircularProgress.set_colors()`, 2 literales de `HeaderBar`,
  `_wake_toggle` como property) — ninguna contradice lo aprobado por Johan.

## Hallazgo bloqueante — condición de carrera real en la persistencia del turno (CA-09)

**No cubierto por ningún test.** `JarvisMainWindow` introduce en este REQ un único slot de estado
mutable, `self._pending_user_text` (`ui/gui.py:111`), para poder pasarle a `memory.store_turn()` el
texto del usuario cuando llega la respuesta async de `resolve()`. El problema: **nada impide que el
usuario envíe un segundo comando mientras el primero sigue resolviéndose** — el composer
(`ui/widgets/composer.py`) nunca deshabilita `_input`/`_send_button` durante el estado PROCESSING
(confirmado: `grep -n "setEnabled" ui/widgets/composer.py ui/widgets/center_panel.py ui/gui.py` no
encuentra ningún guard), y `resolve()` puede tardar segundos reales porque su último recurso es
`ai/claude_brain.ask_claude()` vía red (`core/resolution.py:220-240`).

**Secuencia concreta que corrompe el historial persistido:**

1. Usuario envía "A". `_handle_command("A")`: burbuja "A" pintada, `_pending_user_text = "A"`,
   `run_async(resolve, ...)` arranca en background (tarda, p. ej., por la llamada a Claude).
2. Antes de que resuelva, usuario envía "B". `_handle_command("B")`: burbuja "B" pintada,
   **`_pending_user_text = "B"` pisa el valor anterior**, se lanza un segundo `resolve()`.
3. Cuando termina de resolver "A", `_on_command_done(resolution_A)` corre:
   `run_async(memory.store_turn, None, None, self._pending_user_text, resolution_A.text, ...)` —
   pero `self._pending_user_text` ya vale `"B"`. **Se persiste `user_text="B"` junto con la
   respuesta real de "A"** — un turno con atribución incorrecta en la base de datos permanente.
   Luego `self._pending_user_text = ""`.
4. Cuando termina de resolver "B", `_on_command_done(resolution_B)` corre con
   `self._pending_user_text == ""` → `store_turn()` entra al branch
   `else: logger.warning("texto de usuario vacío...")` y **no escribe la fila `role="user"`**, pero
   sí escribe la fila `role="assistant"` con la respuesta de "B" — **una fila huérfana sin su turno
   de usuario correspondiente**.

Resultado neto: dos turnos reales del usuario terminan como una fila mal atribuida (texto de "B"
pegado a la respuesta de "A") y una fila huérfana solo-asistente. Esto ocurre en el feed visible
también de forma inconsistente respecto de lo persistido — al recargar esa conversación desde el
sidebar (CA-06), `get_conversation_turns()` mostrará algo que no coincide con lo que el usuario vio
en vivo, exactamente el escenario que la arquitectura señala como el motivo de NO mezclar los
resultados de los chips de acción con el feed (§4.5) — pero aquí ocurre igual por otra vía no
cubierta.

**Por qué es un hallazgo genuino de este REQ y no preexistente:** antes de REQ-013,
`_on_command_done` llamaba `memory.store(f"{resolution.matched_by} | {result_text}", ...)` —
toda la información necesaria viajaba dentro del propio objeto `resolution`, sin depender de ningún
estado compartido de la ventana. `_pending_user_text` es un mecanismo nuevo, introducido
específicamente para CA-09, y es el que abre la ventana de carrera. Confirmado con
`git diff -- ui/gui.py`.

**Por qué no es solo teórico:** no hace falta doble-click accidental — alcanza con que el usuario
escriba un segundo mensaje mientras espera la respuesta del primero (patrón normal de uso de
cualquier chat), y que `resolve()` involucre una llamada de red a Claude con latencia perceptible.
Ningún test de `tests/test_gui_widgets.py` ni `tests/test_chat_widgets.py` ejercita el envío
concurrente de dos comandos antes de que el primero resuelva (`grep` dirigido sin resultados
relevantes más allá de un único `window._pending_user_text = "hola"` seteado a mano en un test que
asume un solo turno en vuelo).

**Sugerencia concreta para `orion-dev`:** deshabilitar `Composer` (`_input` y `_send_button`, o al
menos rechazar un segundo envío) mientras haya una resolución en curso — p. ej.
`self.center_panel.set_input_enabled(False)` en `_handle_command()` y reactivarlo en
`_on_command_done()`/`_on_command_error()`. Esto también resuelve por construcción el caso borde ya
mencionado en la SPEC ("Cambio de tema mientras hay una respuesta en curso... no debe interrumpir la
resolución") sin tocar `run_async`/`gui_workers.py`. Alternativa más invasiva (no recomendada sin
volver a arquitectura): dejar de depender de un único slot compartido y correlacionar cada
`resolve()` con su texto de usuario vía closure/`functools.partial`, pero eso choca con la regla
documentada en `ui/gui_workers.py` de que los callbacks de `run_async` deben ser bound methods de un
`QObject` para que Qt resuelva el hilo de entrega correctamente — la opción de deshabilitar el input
es la que respeta esa restricción sin rediseñar el mecanismo de callbacks.

## Veredicto: ❌ RECHAZADO

Los 22 criterios de SPEC-013 pasan tal como verificó `orion-tester`, la auditoría de secretos y
niveles de riesgo no encuentra hallazgos, y el gate de seguridad de los chips de acción (CA-19) está
correctamente implementado. Sin embargo, la verificación específica pedida sobre la persistencia
asíncrona del turno (`run_async` fuera del hilo de la GUI) encontró una condición de carrera real y
reproducible que corrompe silenciosamente el historial persistido (`ai/unified_memory.db`) bajo un
patrón de uso normal — no un caso extremo forzado. Esto viola la garantía implícita de CA-09
("se persiste tanto el texto original del usuario como la respuesta de la IA, asociados a un
`conversation_id` común") en el escenario de doble envío, y no está cubierto por ningún test
existente.

**Motivo concreto y accionable para `orion-dev`:** `ui/gui.py` — `_pending_user_text` (línea 111) es
un slot único compartido que se pisa si el usuario envía un segundo comando antes de que el primero
reciba respuesta de `resolve()`. Agregar un guard que impida (o encole) un segundo envío mientras hay
uno en curso — el punto natural es `Composer`/`CenterPanel` deshabilitando el input entre
`_handle_command()` y `_on_command_done()`/`_on_command_error()` — y agregar un test de regresión que
ejerza el envío de un segundo comando antes de que el primero resuelva, verificando que
`store_turn()` no reciba nunca un `user_text` que no corresponda a su propia respuesta.

---

## Re-auditoría — 2da pasada QA (cierre del hallazgo de condición de carrera)

**Agente:** orion-qa · **Fecha:** 2026-08-17
**Origen:** REQ-013 vuelve a `EN_QA` tras la 3ra pasada de `orion-dev` (fix) y la 3ra pasada de
`orion-tester` (re-verificación, PASS 22/22, 307/307 tests). Entradas revisadas:
`desarrollo-log-013.md` sección "3ra pasada — fix condición de carrera", `test-results-013.md`
sección "3ra pasada — re-verificación fix condición de carrera", `REQ-013-context.md` completo, y
el código real (`ui/gui.py`, `ui/widgets/composer.py`, `ui/widgets/center_panel.py`).

Esta pasada NO repite la auditoría de seguridad/secretos/niveles de riesgo/logging de la sección
anterior (sin hallazgos entonces, y los archivos donde se auditó eso no cambiaron en esta pasada).
Se enfoca en: (1) verificar en código real que el fix cierra la carrera y no solo la oculta, (2)
confirmar que `_on_command_error()` reactiva el composer, (3) buscar efectos secundarios nuevos
(chips de acción), y (4) re-pasar el checklist DoD sobre el diff nuevo de esta 3ra pasada.

### 1. El fix cierra la carrera por construcción — verificado en código real, no solo en el reporte

Leído directamente `ui/widgets/composer.py:178-189` (`set_input_enabled`) y `ui/gui.py:199-260`
(`_handle_command`/`_on_command_done`/`_on_command_error`):

```python
def set_input_enabled(self, enabled: bool) -> None:
    self._input.setEnabled(enabled)
    self._send_button.setEnabled(enabled)
    self._input.setPlaceholderText(_PLACEHOLDER_IDLE if enabled else _PLACEHOLDER_BUSY)
```

`_handle_command()` fija `_pending_user_text = text` y llama `set_input_enabled(False)` ANTES de
`run_async(resolve, ...)`. `_on_command_done()` lee `_pending_user_text` para `store_turn()`, lo
limpia (`= ""`) y recién después llama `set_input_enabled(True)`; `_on_command_error()` hace lo
mismo (limpia y reactiva). Como el hilo de la GUI es cooperativo (ningún evento se procesa hasta
que el handler actual retorna), no existe ninguna ventana en la que `_pending_user_text` pueda
leerse y escribirse en hilos distintos ni en llamadas intercaladas: mientras el composer esté
deshabilitado, físicamente no puede dispararse un segundo `_handle_command()`.

Verificación empírica adicional (no solo lectura de código): confirmado en este entorno real de
PyQt6 que `QPushButton.click()` sobre un botón con `setEnabled(False)` NO emite `clicked`:

```
clicked count after click() on disabled button: 0
```

Esto descarta la duda razonable de si `.click()` programático (usado en el test de regresión)
podría saltarse el `isEnabled()` — no lo hace. El bloqueo es una propiedad del framework Qt
(el widget deshabilitado no procesa el evento), no un `if` en `_emit_command()` que un futuro
segundo punto de entrada pudiera olvidar replicar. Confirmado también con
`grep -rn "command_submitted.emit"` (un solo emisor, en `Composer._emit_command`) que no existe
otro camino (voz, tray, atajos) hacia `_handle_command()`.

**Conclusión: el fix cierra la carrera por construcción. No es un guard lógico que reduce la
ventana — la elimina, porque Qt no entrega el evento al origen.**

### 2. `_on_command_error()` reactiva el composer — confirmado

```python
def _on_command_error(self, message: str) -> None:
    self.center_panel.show_response(f"Error: {message}")
    self._pending_user_text = ""
    self.center_panel.set_input_enabled(True)
```

Un timeout de red (el camino más probable dado que `resolve()` puede llegar hasta
`ai/claude_brain.ask_claude()`) no deja al usuario con la UI bloqueada permanentemente. Esto era
justamente el riesgo de UX/seguridad nuevo que este fix podría haber introducido si solo se
hubiera tocado el camino feliz — verificado que no es el caso, y cubierto por
`test_main_window_on_command_error_no_persiste_turno`, ejecutado de forma independiente en esta
auditoría: **PASS**.

### 3. Efecto secundario revisado: chips de acción del composer durante PROCESSING

Los chips (`_build_chips_row()`/`_on_chip_clicked()`) NO están gateados por `set_input_enabled()`
— ese método solo toca `_input`/`_send_button` (confirmado por lectura completa del método, 3
líneas). Los 5 botones de chip siguen clickeables mientras el composer está "pensando".

Analizado si esto reabre el mismo problema por otra vía:
- Chips `kind="template"` (3): solo hacen `self._input.setText(...)`/`setFocus()` sobre el
  `QLineEdit` deshabilitado. `setText()` programático funciona igual en un widget deshabilitado
  (la propiedad `enabled` bloquea interacción del usuario, no llamadas de API); no interactúa con
  `_pending_user_text` ni con `store_turn()`. Sin riesgo de corrupción de datos — a lo sumo, una
  curiosidad de UX menor (el placeholder "Noddoo está pensando..." se pisa visualmente con el
  texto de la plantilla mientras el input sigue bloqueado para edición/envío real).
- Chips `kind="action"` (2, `take_screenshot`/`open_browser`): van por
  `run_async(execute_action, self._on_action_done, self._on_action_error, ...)`, completamente
  desacoplado de `_pending_user_text`/`store_turn()`/`resolve()`. El resultado se escribe en
  `self._action_status` (un `QLabel` de solo estado), nunca se persiste ni se convierte en
  burbuja — decisión de arquitectura ya documentada en el contexto (§ "Resultado de los chips de
  acceso directo va a un label de estado del composer... no se persiste"). Dos clics de acción en
  paralelo (o uno durante PROCESSING) podrían, como mucho, pisarse entre sí el texto de
  `_action_status` — un efecto cosmético ya preexistente a este REQ y no relacionado con CA-09,
  no con la integridad de `ai/unified_memory.db`.

**Conclusión: los chips no reabren la condición de carrera de CA-09 por ninguna vía — el
mecanismo de persistencia que causaba el hallazgo original (`_pending_user_text`/`store_turn`)
es inalcanzable desde el código de chips.** No se exige fix: no hay corrupción de datos posible,
y el comportamiento de los chips durante PROCESSING no está definido como criterio de aceptación
en SPEC-013. Queda como nota para una futura mejora de UX (deshabilitar también los chips durante
PROCESSING), sin bloquear este REQ.

### 4. Checklist DoD completo re-pasado sobre el diff de la 3ra pasada

Archivos tocados: `ui/gui.py`, `ui/widgets/composer.py`, `ui/widgets/center_panel.py`,
`tests/test_gui_widgets.py`, `tests/test_chat_widgets.py`.

- **Secretos:** `grep -inE "api[_-]?key|secret|token|password|bearer"` sobre los 3 archivos de
  producción tocados — únicas coincidencias son `qss_tokens`/`register_themed` (nombres de
  función preexistentes, sin relación con credenciales). Sin hallazgos.
- **Acciones destructivas / niveles de riesgo:** el fix no agrega ninguna acción nueva
  verde/amarillo/roja — solo habilita/deshabilita un widget de UI. Sin cambios de clasificación.
- **`except: pass` silencioso:** único `except` en los 3 archivos de producción es
  `ui/gui.py:92` (`WakeWordWorker`, preexistente de REQ-009, con `logger.error(...)` — no
  silencioso, y no tocado por esta pasada). Sin hallazgos nuevos.
- **Logging:** el fix no agrega ninguna operación nueva que requiera logging propio (es
  manipulación directa de widgets Qt); no se removió logging existente.
- **Prints de debug:** `grep -n "print("` sobre los 3 archivos — sin resultados.
- **Convenciones (`python-style.md`):** type hints presentes (`enabled: bool`, `-> None`),
  docstrings en imperativo, sin líneas >100 caracteres en el método nuevo, naming consistente.
- **Compilación independiente:** `python -m py_compile ui/gui.py ui/widgets/composer.py
  ui/widgets/center_panel.py tests/test_gui_widgets.py tests/test_chat_widgets.py` → OK.
- **Tests dirigidos ejecutados de forma independiente por `orion-qa`** (no solo leídos del
  reporte de `orion-tester`):
  `test_main_window_segundo_envio_bloqueado_mientras_resuelve_el_primero`,
  `test_main_window_on_command_error_no_persiste_turno`,
  `test_composer_set_input_enabled_bloquea_envio_y_cambia_placeholder` → **3 passed**.
- **Suite completa ejecutada de forma independiente:** `python -m pytest tests/ --tb=short -q` →
  **307 passed, 3 warnings** (mismos 3 warnings preexistentes de siempre). Coincide exactamente
  con lo reportado por `orion-dev`/`orion-tester`.

Sin hallazgos nuevos en esta pasada.

### Veredicto: ✅ COMPLETADO

El hallazgo bloqueante original (condición de carrera en `_pending_user_text`, CA-09) queda
**cerrado por construcción**, verificado de forma independiente contra el código real y con
ejecución propia de tests (no solo contra los reportes de `orion-dev`/`orion-tester`):
`Composer.set_input_enabled(False)` aprovecha que Qt no entrega eventos de input a un widget
deshabilitado, eliminando la ventana de carrera en su origen. `_on_command_error()` reactiva el
composer, evitando que un fallo de red deje la UI bloqueada permanentemente. Los chips de acción
del composer, aunque no están gateados por `set_input_enabled()`, no pueden reabrir la carrera de
CA-09 porque su mecanismo de resultado está completamente desacoplado de
`_pending_user_text`/`store_turn()`. Checklist DoD completo re-pasado sobre el diff de la 3ra
pasada sin hallazgos nuevos. 307/307 tests passed, confirmado de forma independiente.

REQ-013 avanza a validación manual del humano antes de cerrar `LISTO_PARA_COMMIT`.
