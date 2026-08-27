# Baseline REQ-021 — Conversación multi-turno real

**Agente:** orion-baseline
**Fecha:** 2026-08-26
**Rama sobre la que se midió:** `feature/REQ-015-webview-ui` (con 49 archivos sin confirmar)
**Precondición:** SPEC-021.md aprobada por Johan ("Apruebo todo el spec"), 32 criterios.

> Este documento fija el estado del sistema **antes** de que `orion-dev` toque nada. Cualquier
> fallo listado acá NO es atribuible a REQ-021.

---

## 1. Fallos pre-existentes — suite completa

```
$ python -m pytest tests/ --tb=short -q
2 failed, 560 passed, 11 warnings in 49.53s
```

| Resultado | Valor |
|-----------|-------|
| Tests que pasan | **560** |
| Tests que fallan | **2** |
| Errores de colección | 0 |
| Tiempo total | **49.53 s** |
| Archivos de test | 47 |

### Los 2 fallos pre-existentes

Ambos en `tests/test_llm_provider.py`, **misma causa raíz**:

- `test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse`
- `test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto`

```
E   ModuleNotFoundError: No module named 'anthropic'
tests\test_llm_provider.py:60: with patch("anthropic.Anthropic", return_value=fake_client)
```

**Diagnóstico:** es un fallo de **entorno, no de código**. El paquete `anthropic` no está
instalado y en `requirements.txt` está **comentado** (línea 70: `# anthropic`). Los dos tests
hacen `patch("anthropic.Anthropic", ...)`, y `mock.patch` necesita importar el módulo real para
parchearlo. Verificado: `python -c "import anthropic"` → `ModuleNotFoundError`; `pip show
anthropic` → *Package(s) not found*.

- **No lo introduce REQ-021 y REQ-021 no debe arreglarlo.**
- Son deterministas: fallan siempre, no son flaky.
- **Zona:** `ai/llm_provider.py`. REQ-021 **no** toca ese módulo → sin solape con el alcance.
- Criterio para `orion-tester`: la línea de baseline a batir es **`2 failed, 560 passed`**.
  Cualquier tercer fallo es regresión de este REQ.

### Warnings pre-existentes (11) — ninguno bloqueante
- `InconsistentVersionWarning` ×4 — modelos sklearn pickleados con 1.8.0, cargados con 1.9.0.
- `DeprecationWarning` ×5 — `numpy` (shape), `aifc` y `audioop` de `speech_recognition`.
- `PytestReturnNotNoneWarning` ×1 — `tests/test_agents.py::test_ca1_orchestrator` hace `return`
  en vez de `assert`.

### Dependencia de micrófono/red en la suite
**Ninguna.** La suite corre completa sin micrófono, sin altavoces y sin red. `speech_recognition`
se importa (de ahí los DeprecationWarnings) pero no abre el dispositivo.

---

## 2. Compilación — los 9 módulos afectados

`python -m py_compile` sobre cada uno: **9 de 9 OK, 0 fallos.**

| Módulo | Líneas | Compila |
|--------|--------|---------|
| `core/resolution.py` | 348 | OK |
| `core/reasoning_loop.py` | 162 | OK |
| `tasks/task_manager.py` | 580 | OK |
| `voice/wake_word.py` | 243 | OK |
| `ui/webview/bridge.py` | 829 | OK |
| `ui/webview/wake_word_worker.py` | 75 | OK |
| `ui/tts_engine.py` | 103 | OK |
| `ui/cli.py` | 53 | OK |
| `main.py` | 271 | OK |

`core/dialog_state.py` **no existe** — confirmado. FEATURE_NUEVA correcto.

---

## 3. Cobertura de test actual de lo que vamos a tocar

### Con red de seguridad

| Área | Archivo | Tests | Nota |
|------|---------|-------|------|
| `resolve()` | `tests/test_resolution.py` | 19 | La mejor cobertura del REQ. Cubre trazas por canal, gate de seguridad y las 4 ramas de `task_tool`. |
| Worker de voz + puente | `tests/test_wake_word_comando.py` | 11 | Cubre `parse_wake_command`, emisión de `command_detected`, y el guard `_resolution_in_flight` del bridge. |
| `reasoning_loop` | `tests/test_reasoning_loop.py` | 9 | Cubre el loop de tools, no `_build_prompt` con historial. |
| `listen_for_wake_word` (parcial) | `tests/test_wake_word.py` | 5 | Solo `stop_event` y `_report_awake`. |

Tests directamente relevantes, por nombre:
- `tests/test_wake_word_comando.py::test_bridge_ignora_comando_de_voz_si_ya_hay_una_resolucion_en_curso`
  — **es el test que hoy afirma justo lo contrario de CA-15.** Habrá que revisarlo, no solo añadir uno nuevo.
- `tests/test_wake_word_comando.py::test_bridge_resuelve_el_comando_de_voz_como_uno_escrito`
- `tests/test_wake_word_comando.py::test_wake_word_sin_comando_escucha_el_dictado_siguiente`
- `tests/test_resolution.py::test_bulk_no_intercepta_create` — único test que ejerce la rama *create*.
- `tests/test_resolution.py::test_solo_verde_ejecuta_por_voz` — invariante de seguridad de CA-17.

### SIN cobertura — aquí una regresión pasa inadvertida

| Área | Estado | Impacto |
|------|--------|---------|
| **`tasks/task_manager.py::parse_natural_task`** | **CERO tests.** `grep -rln "parse_natural_task" tests/` → vacío. | Es la función que la SPEC manda modificar (CA-01, CA-02, CA-03). Se va a cambiar el corazón del parseo de recordatorios **sin una sola prueba de regresión existente**. Máxima prioridad para `orion-dev`: escribir los tests *antes* de tocarla. |
| **`ui/cli.py::display_output`** | **CERO tests.** `tests/test_cli_gui_active.py` tiene 3 tests y los 3 son de `get_input_method` (opción "3" del menú). | Es exactamente lo que CA-27 exige no cambiar. **No hay red de seguridad para CA-27.** Ver §4.5 para los valores exactos de hoy. |
| **`ui/tts_engine.py` — preparación de texto** | No existe la función; no hay tests de aplanado/truncado. | CA-24 y CA-27 son terreno virgen. |
| `matched_by` de `routine`, `autopilot`, `learned`, `capability` | **Nunca aseverados en ningún test.** Los únicos valores aseverados hoy son `intent:CALCULATE`, `intent:CLOSE_APP`, `claude` y `task_tool`. | **CA-09 pide una frase por resolver: hoy solo 4 de los 7 tienen aserción de `matched_by`.** El set de regresión de CA-09 hay que construirlo casi entero. |
| `listen_for_wake_word` — bucle principal | Sin test del bucle ni de `_listen_for_followup`. | Pieza 6 se construye sin red. |

---

## 4. Comportamiento actual verificado (ejecutado, no supuesto)

### 4.1 `parse_natural_task` — ejecutado el 2026-08-26 a las 12:51:21

| Entrada | `title` | `remind_at` |
|---------|---------|-------------|
| `"recuérdame algo"` | `'Algo'` | `'2026-08-26T13:51:22.298970'` (= now + 1h) |
| `"recuérdame llamar al contador mañana a las 9"` | `'Llamar al contador'` | `'2026-08-27T09:00:00'` |
| `"recuérdame"` | `'Recuérdame'` | now + 1h |
| `"recuérdame una cosa"` | `'Una cosa'` | now + 1h |
| `"ponme un recordatorio"` | `'Ponme un recordatorio'` | now + 1h |
| `"recuérdame llamar al contador"` | `'Llamar al contador'` | now + 1h |
| `"recuérdame mañana a las 9"` | `'Recuérdame mañana a las 9'` | `'2026-08-27T09:00:00'` |

Dict completo devuelto (ejemplo del caso de referencia):
```python
{'user_id': 'default', 'channel': 'telegram', 'title': 'Llamar al contador', 'description': '',
 'due_date': '2026-08-27T09:00:00', 'remind_at': '2026-08-27T09:00:00',
 'recurrence': None, 'priority': 'normal'}
```

**La SPEC queda confirmada en sus dos afirmaciones centrales:** "recuérdame algo" → `'Algo'` +
now()+1h, y el caso de un solo tiro de CA-03 → `'Llamar al contador'` + mañana 09:00.
`due_date` siempre es igual a `remind_at`.

**Valor de referencia para CA-03:** cuando `orion-tester` reejecute
`parse_natural_task("recuérdame llamar al contador mañana a las 9", "default")`, debe seguir
dando `title='Llamar al contador'` y `remind_at` = **día siguiente a las 09:00:00**.

### 4.2 SORPRESA 1 — `parse_natural_task` nunca reporta ausencia de dato

`tasks/task_manager.py:262-263`:
```python
if not title or len(title) < 3:
    title = text.strip()
```

Esta línea es la clave del REQ y **la SPEC no la menciona**. Hace que una frase sin contenido
real **nunca** produzca un título vacío: produce un título que *parece* válido.

- `"ponme un recordatorio"` → `'Ponme un recordatorio'`
- `"recuérdame mañana a las 9"` → `'Recuérdame mañana a las 9'` (¡conserva la fecha en el título!)
- `"recuérdame"` → `'Recuérdame'`

La nota de diseño de la SPEC dice que el criterio de "falta el slot" debe consultarse *"sobre la
misma lógica que usa `parse_natural_task`"*. **Hoy esa lógica no tiene ninguna señal de ausencia
que consultar** — el fallback la destruye. `orion-architect` tiene que diseñar la detección como
una función nueva y explícita (lista de frases-cáscara + comprobar si el título resultante es solo
el trigger o solo la expresión de fecha), no como un "leer lo que ya devuelve `parse_natural_task`".

Además, solo se recorta el trigger cuando **empieza** la frase (`text_lower.startswith(trigger)`,
línea 242), por eso "ponme un recordatorio" no se recorta.

### 4.3 SORPRESA 2 — dos listas de triggers ya divergentes

| Lista | Ubicación | Contenido |
|-------|-----------|-----------|
| `_TASK_CREATE_TRIGGERS` | `core/resolution.py:117-121` | 12 triggers |
| `task_triggers` | `tasks/task_manager.py:227-232` | 14 triggers |

Diferencias reales: `task_manager` tiene `"tengo que"`, `"debo"` y `"pendiente"` (suelto);
`resolution` no los tiene y usa `"pendiente:"` con dos puntos.

**Consecuencia:** "tengo que llamar al contador" **no** dispara `_try_task_tool` hoy (cae en
`claude`), pero `parse_natural_task` sí lo parsearía como tarea. Si `orion-dev` unifica las listas
al implementar la detección de slots, **cambia el comportamiento de frases que hoy van a Claude** →
riesgo de regresión silenciosa fuera de los criterios. Decisión para `orion-architect`: unificar o
no, explícitamente.

### 4.4 SORPRESA 3 — CA-24 y CA-27 se contradicen tal como están escritos

Capturado con `speak()` mockeado, entrada = salida real de `format_task_created()`:

```
VOZ HOY: 'Enseguida, Senor. ✅ *Tarea registrada, Señor Johan.*. . 📋 *Llamar al contador*.
          🆔 #12. ⏰ Recordatorio: 27/08/2026 a las 09:00. 🔁 Recurrencia: Diaria. .
          Le notificaré en el momento indicado.'
```

**Hoy la consola pronuncia literalmente los asteriscos y los emojis.** `ui/cli.py` (53 líneas
completas) **no quita markdown ni emojis** — solo aplana `\n` → `". "` y trunca.

- **CA-24** exige que el texto que llega a `speak()` no tenga `*`, `#` ni emojis.
- **CA-27** exige que *"la salida audible de la consola no cambia"*.

Si la función común hace las dos cosas, **la salida de la consola cambia por definición**. Son
incompatibles. `orion-architect` debe resolverlo — la vía natural es parametrizar (p. ej.
`prepare_for_speech(text, strip_markup=True)`, con la consola llamando igual y ganando la mejora, o
la consola conservando su comportamiento). **Hay que decidirlo y anotarlo, no descubrirlo en QA.**

### 4.5 Baseline exacto de `ui/cli.py::display_output` (para CA-27)

Orden real de operaciones (`ui/cli.py:35-53`):
1. `format_response(text)` — **personalidad, se aplica ANTES de hablar** (antepone "Enseguida, Senor. ").
   El webview NO hace esto: habla `resolution.text` crudo. La función común debe empezar *después* de este paso.
2. `print(f"\n[➡ {agent_name}]: {formal_text}")`
3. Si `read_aloud`: `text_to_speak = formal_text.replace("\n", ". ")`
4. Si `len(text_to_speak) > 400`:
   `short_text = text_to_speak[:380].rsplit('.', 1)[0] + f"... La información completa está en su pantalla{vocative()}."`

**Detalles que la SPEC cita mal y hay que corregir en el test de regresión:**
- La coletilla **incluye `vocative()`** (`core/address.py`), no es un literal fijo. Medido:
  `'... La información completa está en su pantalla, Señor Johan.'`
- Hay un **espacio después de los tres puntos**: `"... La información"`, no `"...La información"`.
- El resultado truncado **mide 423 caracteres**, no ≤400: la coletilla se añade *después* del corte
  en 380. El umbral de 400 es de decisión, no de resultado.
- La salida real de `format_task_created()` trae `📋 *Llamar al contador*` y `🆔 #12`. La SPEC
  (CA-24) menciona el literal `*#12*`, que **no existe**. El `*` y el `#` sí están, así que el
  criterio se puede probar, pero no aseverando esa cadena.

### 4.6 Orden actual de `RESOLVERS` (`core/resolution.py:297-305`)

```python
RESOLVERS = [
    ("routine",    _try_routine),
    ("autopilot",  _try_autopilot),
    ("learned",    _try_learned),
    ("task_tool",  _try_task_tool),
    ("capability", _try_capability),
    ("intent",     _try_intent),
    ("claude",     _try_claude),
]
```
7 resolvers. `_try_pending_dialog` debe quedar en posición 0 → serán 8, con los 7 actuales en su
orden relativo intacto (ASUMIDO de la SPEC, confirmado como verificable).

### 4.7 `ResolutionResult` — firma actual (`core/resolution.py:30-36`)

```python
@dataclass(frozen=True)
class ResolutionResult:
    text: str
    matched_by: str
    channel: "ChannelType"
    denied: bool = False
```
**7 líneas, 4 campos, y es `frozen=True`.** Añadir `expects_reply: bool = False` después de
`denied` es compatible. **Aviso para `orion-dev`: al ser `frozen`, ningún resolver puede mutar el
resultado — hay que construir una instancia nueva o usar `dataclasses.replace()`.**

### 4.8 Los 4 consumidores de `resolve()` — cómo consumen hoy (para CA-10)

| Consumidor | Línea | Código actual | Campos que lee |
|------------|-------|---------------|----------------|
| `main.py` | 196 | `resolution = resolve(command, channel)` → `result = resolution.text` | solo `.text` |
| `channels/gateway.py` | 92 | `resolution = resolve(text, message.channel, message.user_id, claude_fn=...)` → `result = resolution.text` | solo `.text` |
| `core/orchestrator.py` | 50 | `result = resolve(text, channel, user_id, claude_fn=self.fallback_to_claude)` → `return result.text` | `.text` y `.matched_by` (log, línea 53) |
| `ui/webview/bridge.py` | 243 | `run_async(resolve, self._on_resolve_done, self._on_resolve_error, text, ChannelType.DESKTOP, user_id="default")` | en `_on_resolve_done` (246): `resolution.text` y `getattr(resolution, "matched_by", "")` |

**Ninguno construye un `ResolutionResult` a mano ni desempaqueta posicionalmente.** Un campo nuevo
con default `False` **no rompe a ninguno de los 4**. CA-10 verificable. El del webview además usa
`getattr` con default, así que es el más tolerante.

### 4.9 Confirmado el hallazgo de CA-14 / CA-26 sobre `_speaking`

`ui/tts_engine.py:27-38`, verbatim:
```python
await asyncio.wait_for(communicate.save(mp3_path), timeout=15)   # línea 34
with _speak_lock:
    _speaking = True                                              # línea 36
_play_mp3_windows(mp3_path)
```
`_speaking = True` ocurre **después** de la síntesis, con hasta 15 s de ventana en la que
`is_speaking()` devuelve `False` y el agente está por hablar. **El hallazgo de `orion-spec` es
correcto.** `speak()` está en la línea 81, `is_speaking()` en 18, `signal_barge_in()` en 22.

### 4.10 SORPRESA 4 — ya existe `_listen_for_followup`, y trae una restricción dura para la pieza 6

`voice/wake_word.py:77-95`. Es el precedente exacto de la ventana de micrófono: escucha un comando
sin exigir wake word, con `timeout=6, phrase_time_limit=12`.

Su docstring documenta una restricción de plataforma que **la SPEC no recoge**:

> *"Reusa el `source` del micrófono ya abierto por `listen_for_wake_word()`: abrir un segundo
> `sr.Microphone()` anidado deja el dispositivo tomado y falla en Windows."*

**Implicación real para la pieza 6:** la ventana de ~15 s tiene que abrirse **dentro** de
`listen_for_wake_word()`, reusando el `source` abierto. Pero el disparador (el `on_done` del TTS,
CA-26) vive en el **bridge**, en el hilo de Qt. Es decir: la señal bridge → worker que menciona la
SPEC no es un detalle de implementación, es **el punto arquitectónico más delicado del REQ** —
`WakeWordWorker` hoy solo tiene comunicación en un sentido (`command_detected`, worker → bridge,
`wake_word_worker.py:32`) más `stop_event` (`threading.Event`, bridge → worker). Hace falta un
canal nuevo bridge → worker que el worker pueda consultar **sin cerrar el micrófono**.

### 4.11 El bucle que hoy cierra la conversación

`ui/webview/wake_word_worker.py:50-71`:
```python
while not self.stop_event.is_set():
    update_wake_state("LISTENING_WAKE")
    result = listen_for_wake_word(stop_event=..., wake_state_callback=...)
    ...
    self.signals.command_detected.emit(result.strip())
```
Tras emitir el comando, el `while` vuelve inmediatamente a `LISTENING_WAKE`. **Ese es el
comportamiento que la pieza 6 debe cambiar** — no la línea 239 de `wake_word.py` que citan la SPEC
y el CSV (esa línea es un `time.sleep(0.05)`). El mecanismo real está repartido entre el `return`
de `listen_for_wake_word()` y este bucle del worker.

### 4.12 `agent_context` — confirmado que se escribe y no se relee

`core/reasoning_loop.py`: `_build_prompt` en la **línea 72**; `agent_context_manager.update_context`
en las líneas 157 y 158. Única importación en la línea 16. **No hay ninguna lectura.** Confirmado.

---

## 5. Estado de git (solo lectura)

```
$ git branch --show-current
feature/REQ-015-webview-ui

$ git status --porcelain | wc -l
49
```

- **Rama activa: `feature/REQ-015-webview-ui`** — NO es la rama de este REQ.
- **49 archivos sin confirmar** (44 modificados + 5 sin seguimiento). Entre los modificados hay 8
  de los 9 módulos afectados por REQ-021, más `tasks/tasks.db` y `requerimientos.csv`.
- Sin seguimiento y **relevante**: `core/address.py` — `ui/cli.py:5` lo importa (`vocative`,
  `vocative_start`) y `ui/cli.py:50` lo usa en la coletilla de truncado. Un archivo que la pieza 8
  necesita **todavía no está en ningún commit**.
- Ramas existentes: `main`, `feature/REQ-014-rediseno-ui-escritorio`, `feature/REQ-015-webview-ui`.
- **`feature/REQ-021-conversacion-multiturno` NO existe todavía**, ni local ni en remoto. La crea
  Johan manualmente desde `main`. Último commit: `9f4235f Mejora visual UI`.
- Ningún agente ejecutó ni debe ejecutar `commit`, `push`, `checkout` ni `branch`.

**Aviso para Johan (no es una acción de este agente):** el baseline de esta medición se tomó sobre
`feature/REQ-015-webview-ui` con 49 archivos sin confirmar. Si la rama de REQ-021 se crea desde
`main` sin ese trabajo, **los números de esta medición no aplicarán** — `2 failed / 560 passed`
podría ser distinto sobre `main` limpio. Conviene confirmar ese trabajo antes de partir la rama, o
partirla desde el estado actual.

---

## 6. Resumen para `orion-architect`

**Lo que la SPEC da por bueno y quedó confirmado:**
- `parse_natural_task("recuérdame algo")` → `'Algo'` + now()+1h.
- `_speaking` se activa después de sintetizar (CA-14/CA-26 bien planteados).
- Los 4 consumidores de `resolve()` solo leen `.text`/`.matched_by` → `expects_reply` con default es seguro.
- `RESOLVERS` tiene 7 entradas; `core/dialog_state.py` no existe.
- Todas las referencias de línea de la SPEC son correctas dentro de ±1.

**Lo que hay que resolver antes de programar:**
1. **CA-24 vs CA-27 se contradicen** — la consola hoy pronuncia asteriscos y emojis (§4.4).
2. **`parse_natural_task` no expone ausencia de slot** — el fallback de la línea 262 la borra (§4.2).
3. **La ventana de micrófono debe reusar el `source` abierto** (restricción de Windows) pero se
   dispara desde el hilo de Qt (§4.10).
4. **Dos listas de triggers divergentes** — unificar o no, decidir explícitamente (§4.3).
5. **`ResolutionResult` es `frozen=True`** — no se puede mutar (§4.7).
6. `tests/test_wake_word_comando.py::test_bridge_ignora_comando_de_voz_si_ya_hay_una_resolucion_en_curso`
   afirma hoy lo contrario de CA-15.

**Dónde una regresión pasaría inadvertida:** `parse_natural_task` (0 tests), `display_output`
(0 tests), y el `matched_by` de `routine`/`autopilot`/`learned`/`capability` (nunca aseverado).
