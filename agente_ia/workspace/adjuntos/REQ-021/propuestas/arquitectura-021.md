# Arquitectura REQ-021 — Conversación multi-turno real (diálogo pendiente + ventana de micrófono)

**Agente:** orion-architect
**Fecha:** 2026-08-26
**Entradas:** `spec/SPEC-021.md` (32 CA, aprobada por Johan), `origen/baseline-021.md`, `REQ-021-context.md`
**Estado:** ⏸️ ESPERANDO APROBACIÓN HUMANA — el gate lo gestiona la sesión principal con Johan.

> Este documento NO implementa código. Define módulos, clases, firmas, flujo de datos, riesgos y
> pruebas. `orion-dev` implementa exactamente esto y nada más.

---

## 0. Cambio post-aprobación incorporado a la SPEC

**CA-27 fue reescrito por la sesión principal después de la aprobación de Johan**, para resolver la
incompatibilidad con CA-24 que detectó `orion-baseline` (§4.4 del baseline: hoy la consola pronuncia
literalmente los asteriscos y los emojis).

| | Redacción |
|---|---|
| **Antes** | "La preparación del texto para voz vive en un solo lugar... **La salida audible de la consola no cambia**." |
| **Ahora** | "La preparación del texto para voz vive en **un solo lugar**, reusado por el webview y por la consola. **Ambas superficies suenan limpias** (sin markdown, sin HTML, sin emojis). El resto del pipeline de la consola **no cambia**: mismo aplanado de saltos de línea (`"\n" -> ". "`), mismo umbral de decisión de 400 caracteres, mismo corte en 380 al último punto, y misma coletilla `"... La información completa está en su pantalla" + vocative() + "."`." |

**Se arregla en las dos vías.** La consola gana la mejora en lugar de conservar el defecto. Ya está
aplicado en `spec/SPEC-021.md`. Johan debe verlo en el gate de arquitectura.

---

## 1. Las 6 decisiones que el baseline dejó abiertas — resueltas

| # | Hallazgo del baseline | Decisión |
|---|-----------------------|----------|
| (a) | CA-24 vs CA-27 incompatibles | **Se arreglan las dos vías.** Función única `prepare_for_speech()`, sin parámetro de modo. La consola pasa a sonar limpia. Ver §0 y §6. |
| (b) | `parse_natural_task` nunca reporta ausencia de dato | **Función nueva y explícita** `scan_task_slots()` en un módulo nuevo `tasks/task_slots.py`. `parse_natural_task` **no se toca** (salvo un *move* puro de sus listas a constantes de módulo). El fallback de la línea 262 **se deja intacto**. Ver §3. |
| (c) | Ventana de micrófono: `source` reusado (Windows) vs disparador en el hilo de Qt | **La ventana NO abre un micrófono nuevo ni una escucha nueva.** Es un *predicado de aceptación* dentro del bucle ya existente de `listen_for_wake_word()`. El canal bridge→worker es un objeto `ConversationWindow` (lock + deadline monotónico), mismo patrón que el `stop_event` que ya existe. Ver §5. |
| (d) | Dos listas de triggers divergentes | **NO se unifican.** Se documenta la divergencia en código y se fija con un test. Ver §3.5. |
| (e) | `ResolutionResult` es `frozen=True` | Los resolvers **construyen**, nunca mutan. `dataclasses.replace()` se usa en **un único punto**: el post-hook de CA-31 dentro de `resolve()`. Ver §4.4. |
| (f) | `test_bridge_ignora_comando_de_voz_...` afirma lo contrario de CA-15 | **El guard se conserva sin debilitarlo.** CA-15 se cumple **por construcción del timeline**, no aflojando el guard. El test conserva su aserción y **cambia de nombre y docstring**; se añade un test de invariante de orden. Ver §7. |

---

## 2. Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| **CA-01** | `_try_task_tool` llama a `scan_task_slots(text)` **antes** de `execute_tool`. Si `scan.missing`, abre diálogo y retorna `ResolutionResult(text=<repregunta>, matched_by="task_tool:dialog_open", expects_reply=True)`. `execute_tool` no se invoca: cero filas en `tasks.db`. |
| **CA-02** | El diálogo, al completarse, **compone una frase canónica** (`compose_task_sentence`) y la pasa a `execute_tool("task_create", {"text": compuesta, ...})`. `parse_natural_task` recibe `"recuérdame llamar al contador mañana a las 9"` → `title='Llamar al contador'`, `remind_at=mañana 09:00`. Nunca "Algo", nunca `now()+1h`, porque una frase incompleta jamás llega a `execute_tool`. |
| **CA-03** | `parse_natural_task` no cambia. `scan_task_slots("recuérdame llamar al contador mañana a las 9")` → `missing=()` → rama `execute_tool` de hoy, `matched_by="task_tool"`, `expects_reply=False`. |
| **CA-04** | `_try_pending_dialog` es el resolver en posición 0. Con diálogo abierto esperando `"que"`, `"llamar al contador"` pasa `_answers_slot("que", ...)` → `matched_by="pending_dialog"`. Ningún otro resolver se ejecuta (el bucle de `resolve()` corta en el primero no-`None`). |
| **CA-05** | `fill("que", ...)` deja `missing=("cuando",)` → repregunta. `"mañana a las 9"` pasa `_answers_slot("cuando", ...)` (`_parse_natural_date` no-`None`) → `missing=()` → `execute_tool` → texto = `format_task_created()` (ya nombra título y `remind_at`) + coda `_DIALOG_CLOSING`. |
| **CA-06** | `_CANCEL_PHRASES` (`"olvídalo"/"olvidalo"/"cancela"/"cancelar"/"déjalo"/"dejalo"/"nada"/"olvídate"`) se evalúa **antes** de `_answers_slot`. `dialog_store.cancel()` → `expects_reply=False`. La frase siguiente encuentra `get()==None` → `_try_pending_dialog` retorna `None` → orden normal. |
| **CA-07** | `DialogStore.get()` **purga al leer**, comparando `clock() - last_progress_at > ttl_seconds`. Sin hilo de fondo, sin timer, sin mensaje al usuario. `clock` es inyectable (`DialogStore(clock=fake_clock)`) → test sin `sleep`. |
| **CA-08** | Clave del `dict` interno: `(user_id, channel.value)`, construida siempre desde los argumentos que ya recibió el resolver — nunca del texto. `ChannelType` ya llega resuelto por `resolve()`. |
| **CA-09** | Con `dialog_store` vacío, `_try_pending_dialog` retorna `None` en su primera línea (`get()` → `None`) → los 7 resolvers corren en su orden actual, sin cambios. El único `matched_by` que cambia es el de una frase de tarea **incompleta**, que hoy no está en ningún test (`"task_tool"` → `"task_tool:dialog_open"`); las 4 ramas actuales de `task_tool` (`test_bulk_*`, `test_bulk_no_intercepta_create`) siguen dando `"task_tool"`. |
| **CA-10** | `expects_reply: bool = False` se añade **después** de `denied` (último campo). **Ningún consumidor lo lee en v1** — es superficie de contrato para los canales y los tests. Los 4 consumidores no cambian una línea. |
| **CA-11** | Todo el mecanismo vive en `core/` y se ejecuta dentro de `resolve()`, que Telegram y Discord ya usan. Cero código por canal. La partición `(user_id, canal)` da a Telegram el aislamiento multiusuario. |
| **CA-12** | La frase capturada dentro de la ventana se devuelve por el mismo `return` de `listen_for_wake_word()` → mismo `command_detected.emit()` → mismo `_on_voice_command` → mismo `send_message()` → mismo `resolve()`. Cero caminos nuevos. |
| **CA-13** | `ConversationWindow.is_open()` compara contra `monotonic()`; vencido el deadline retorna `False` y el bucle vuelve a exigir wake word. El worker publica `update_wake_state("LISTENING_WAKE")` al cerrarse la ventana. |
| **CA-14** | Doble candado: (1) la ventana **solo** se arma en `_on_speech_done`, encadenado al `on_done` de `run_async(speak, ...)` (CA-26) — nunca por sondeo de `is_speaking()`; (2) el bucle registra `listen_started_at = monotonic()` **antes** de `recognizer.listen()` y acepta sin wake word solo si `listen_started_at >= window.opened_at`. Un chunk que empezó a capturarse mientras el agente hablaba queda descartado aunque termine después. |
| **CA-15** | El guard se libera en `_on_resolve_done` **antes** del TTS; la ventana abre en `_on_speech_done`, **después** del TTS. Son dos instantes separados por toda la locución, y el segundo turno solo puede entrar por la ventana. El guard nunca está tomado cuando llega. Ver §7. |
| **CA-16** | Composición de CA-01..CA-05 + CA-12..CA-14 + CA-23..CA-26. Prueba manual de Johan. |
| **CA-17** | El único camino a `tasks.db` sigue siendo `execute_tool("task_create", ..., channel, user_id)` con el `channel` que pasó el caller. `dialog_store` no toca `security_manager` ni transporta canal alguno hacia el gate: guarda `channel.value` **solo** como parte de la clave de partición. |
| **CA-18** | `_try_pending_dialog` está en posición 0: con diálogo abierto la frase se consume ahí y **nunca llega** a `_try_intent`/`_try_capability`/`_try_task_tool`. Un trigger YELLOW/RED se convierte en texto de slot. Falla en sentido seguro. |
| **CA-19** | `PendingDialog.action` se fija en `open()` y **no hay ningún setter**. `_try_pending_dialog` invoca `execute_tool(dialog.action, ...)`, jamás una acción derivada del contenido del slot. En v1 el único `open()` del sistema está en `_try_task_tool` con `action="task_create"` literal. |
| **CA-20** | `core/dialog_questions.py::ask_question()` pide al LLM una frase de una línea. Si devuelve `None` (fallo, vacío, >200 chars, no-`str`), se usa `FALLBACK_QUESTIONS[slot]` — frases naturales fijas ("¿Qué quiere que le recuerde?" / "¿Para cuándo se lo recuerdo?"). El flujo sigue idéntico. |
| **CA-21** | `scan_task_slots()` y `_answers_slot()` son puros: `re` + `_parse_natural_date`, cero red. `ask_question()` **solo** se invoca cuando la decisión "falta X" ya está tomada, para redactar. Test con `generate_response` mockeado para lanzar excepción: el diálogo se abre igual y sale la frase de respaldo. |
| **CA-22** | `_build_prompt(task, history, prior_turns=None)`. `run()` lee `agent_context_manager.get_context(...).conversation[-CONTEXT_TURNS:]` **una vez, antes del bucle** (el turno actual se escribe al final, así que lo leído es estrictamente anterior). Si `history` y `prior_turns` están vacíos, `return task` — byte a byte el prompt de hoy. |
| **CA-23** | Exactamente un `run_async(speak, ...)` por `_on_resolve_done`. `_on_resolve_error` **no** habla (un error no es respuesta del agente — mismo criterio que ya usa para no persistirlo). |
| **CA-24** | `prepare_for_speech(resolution.text)` — sobre el texto crudo, nunca sobre el HTML de `render_markdown()`. Barrido final incondicional de `*` y `#` (con `#\d+` → `número \d+` antes, para que "🆔 #12" suene "número 12"), tags HTML, y rangos Unicode de emoji. |
| **CA-25** | `speak()` se invoca **siempre** vía `run_async` (`ui/gui_workers.py:53`). Ninguna llamada directa desde el hilo de la GUI. |
| **CA-26** | La ventana se arma en `_on_speech_done` / `_on_speech_error`, ambos callbacks del `run_async` de la tarea de voz. `is_speaking()` no se consulta en ninguna línea nueva. |
| **CA-27** (reescrito) | `prepare_for_speech()` en `ui/tts_engine.py`, llamada por `ui/cli.py::display_output` y por `bridge._on_resolve_done`. Constantes `SPEECH_TRUNCATE_THRESHOLD=400` / `SPEECH_TRUNCATE_AT=380`. Aplanado, umbral, corte al último punto y coletilla con `vocative()` idénticos a hoy. |
| **CA-28** | `_on_speech_done` y `_on_speech_error` llaman **al mismo** `_open_conversation_window()`. Además `speak()` ya traga sus propios fallos (loguea y retorna), así que el camino de fallo entra por `on_done`. Un TTS roto no deja la conversación muerta. |
| **CA-29** | El barge-in de `voice/wake_word.py:142-148` no se toca. `dialog_store` vive en `core/` y no tiene ninguna relación con `_speaking`/`_barge_in`: interrumpir mata la locución, no el diálogo. Al cortar la locución, `speak()` retorna → `on_done` → la ventana abre antes. |
| **CA-30** | `_answers_slot()` retorna `False` para una frase interrogativa ("qué hora es") → `_try_pending_dialog` retorna `None` → siguen los 7 resolvers en orden normal. `dialog_store` **no se toca** (ni `fill` ni `cancel`): el diálogo sigue vivo. |
| **CA-31** | Post-hook `_append_pending_question()` en `resolve()`, ejecutado solo cuando (i) el resultado NO vino del diálogo y (ii) sigue habiendo diálogo abierto: `dataclasses.replace(result, text=f"{result.text}\n\nPor cierto, {dialog.question}", expects_reply=True)`. Determinista, sin LLM. |
| **CA-32** | `PendingDialog.last_progress_at` se actualiza **solo** en `open()` y en `fill()`. El post-hook de CA-31 y `touch_question()` no lo tocan. Un desvío no compra tiempo. |

---

## 3. Pieza A — Detección de slots (hallazgo (b))

### 3.1 Dónde vive

**Módulo nuevo: `tasks/task_slots.py`.** No dentro de `tasks/task_manager.py` (580 líneas, ya al
límite de "una clase principal por archivo") y no en `core/` (la lógica es específica del dominio de
tareas; `core/` solo debe conocer el *contrato* de slots, no las expresiones regulares de fechas en
español).

Dirección de dependencias, sin ciclos:

```
core/resolution.py ──import lazy──> tasks/task_slots.py ──import──> tasks/task_manager.py
                   └─import lazy──> core/dialog_state.py      (sin dependencias de tareas)
                   └─import lazy──> core/dialog_questions.py ──> ai/llm_provider.py
```

`tasks/task_manager.py` **nunca** importa `task_slots` → no hay ciclo.

### 3.2 Firma y contrato

```python
# tasks/task_slots.py

SLOT_WHAT = "que"
SLOT_WHEN = "cuando"

@dataclass(frozen=True)
class SlotScan:
    action: str                    # siempre "task_create" en v1
    filled: dict[str, str]         # {"que": "llamar al contador", "cuando": "mañana a las 9"}
    missing: tuple[str, ...]       # ("que",) | ("cuando",) | ("que", "cuando") | ()
    source_text: str

    @property
    def is_complete(self) -> bool: ...


def scan_task_slots(text: str) -> SlotScan:
    """Return qué slots obligatorios de `task_create` trae `text` y cuáles faltan.

    Determinista y puro: solo `re` y `_parse_natural_date`. Nunca consulta el LLM, nunca
    toca la base de datos, nunca ejecuta nada (CA-21).
    """


def compose_task_sentence(slots: dict[str, str]) -> str:
    """Return una frase canónica de creación a partir de los slots llenos.

    `{"que": "llamar al contador", "cuando": "mañana a las 9"}`
      -> `"recuérdame llamar al contador mañana a las 9"`

    Es la ÚNICA forma en que el diálogo llega a `task_create`: se reusa entero el parseo de
    hoy (título, fecha, recurrencia, prioridad) en vez de construir el dict a mano. Así la
    detección y la creación no pueden contradecirse (CA-02), y recurrencia y prioridad
    siguen infiriéndose del texto sin repreguntarse nunca.
    """
```

> **Por qué la frase canónica y no un dict:** construir el `dict` de la tarea a mano desde el diálogo
> abriría un **segundo** camino de creación, que se desincronizaría del de `parse_natural_task` a la
> primera modificación de cualquiera de los dos — el mismo drift que la SPEC quiere evitar entre
> consola y webview. Recomponiendo la frase, el diálogo termina ejerciendo exactamente el mismo
> código que hoy usa el camino de un solo tiro, y CA-02 y CA-03 quedan probando la misma función.

### 3.3 Algoritmo de `scan_task_slots` — cómo distingue los 3 casos

Orden normativo:

1. **`cuando`** — `_parse_natural_date(text) is not None`. **Esta señal ya es honesta hoy**: la
   ausencia de fecha se ve porque `_parse_natural_date` retorna `None`; quien la borra es el
   `if remind_at is None: now()+1h` de `parse_natural_task`, no el parser. Se consulta la función
   real, no una copia → detección y creación no pueden divergir en el "cuándo".
   `filled["cuando"] = <fragmento de fecha detectado en el texto>` (para poder recomponer).
2. **`que`** — cuatro pasos, todos sobre `text.lower()` normalizado (espacios colapsados,
   puntuación de bordes recortada):
   1. Quitar **todas** las apariciones de un trigger (regex de alternación con límites de palabra),
      no solo la del inicio. Esto corrige la limitación de `startswith` de `task_manager.py:242`
      **sin tocar** `parse_natural_task`.
   2. Quitar las expresiones de fecha con `TASK_DATE_PATTERNS` — la **misma** lista que usa
      `parse_natural_task`, promovida a constante de módulo (ver §3.5).
   3. Tokenizar el resto y descartar los tokens de `_NON_CONTENT_TOKENS`: artículos, preposiciones,
      pronombres átonos, verbos imperativos de creación (`ponme`, `pon`, `agenda`, `anota`,
      `apunta`, `crea`, `créame`, `hazme`, `añade`, `agrega`), sustantivos-cáscara (`algo`, `cosa`,
      `cosas`, `vaina`, `eso`, `esto`, `nada`) y sustantivos de la propia acción (`tarea`, `tareas`,
      `recordatorio`, `recordatorios`).
   4. `que` está presente ⇔ queda **al menos un token de contenido de ≥3 caracteres**.
      `filled["que"] = <resto sin fechas ni triggers, con la capitalización original>`.

Verificación contra la tabla medida por `orion-baseline` (§4.1):

| Entrada | resto tras 1+2 | tokens de contenido | `missing` |
|---|---|---|---|
| `"recuérdame algo"` | `algo` | — (cáscara) | `("que", "cuando")` |
| `"recuérdame"` | *(vacío)* | — | `("que", "cuando")` |
| `"recuérdame una cosa"` | `una cosa` | — (artículo + cáscara) | `("que", "cuando")` |
| `"ponme un recordatorio"` | `ponme un` (se quita `recordatorio`, que es trigger) | — (verbo de creación + artículo) | `("que", "cuando")` |
| `"recuérdame mañana a las 9"` | *(vacío — fecha quitada)* | — | `("que",)` |
| `"recuérdame llamar al contador"` | `llamar al contador` | `llamar`, `contador` | `("cuando",)` |
| `"recuérdame llamar al contador mañana a las 9"` | `llamar al contador` | `llamar`, `contador` | `()` |
| `"recuérdame completar todas mis tareas mañana"` | `completar todas mis` | `completar` | `()` ← preserva `test_bulk_no_intercepta_create` |

`missing` se ordena siempre `("que", "cuando")` — se pregunta primero el qué, que es como habla una
persona y es el orden del caso de referencia.

**Las tres distinciones que pedía el hallazgo (b), explícitas:**

| Frase | `cuando` | `que` | Resultado |
|---|---|---|---|
| "recuérdame algo" | `_parse_natural_date` → `None` | resto = cáscara | faltan **los dos** → se pregunta el qué primero |
| "recuérdame mañana a las 9" | `_parse_natural_date` → fecha | resto vacío tras quitar la fecha | falta **solo el qué** |
| "recuérdame llamar al contador" | `_parse_natural_date` → `None` | `llamar`, `contador` | falta **solo el cuándo** |

### 3.4 Qué pasa con el fallback de `task_manager.py:262-263`

**Se deja intacto.** Justificación:

- Tiene **cero tests** (baseline §3). Cambiarlo es una modificación a ciegas de una función que usan
  Telegram, Discord, el webview y cualquier `task_create` que proponga el LLM.
- Con el diseño de frase canónica (§3.2), el camino conversacional **nunca** llega a ese fallback con
  un título vacío: `compose_task_sentence` siempre entrega un "qué" real.
- Desde `_try_task_tool` el fallback queda **inalcanzable** para frases incompletas, porque el
  resolver ya no llama a `execute_tool` cuando `scan.missing`.
- CA-02 está redactado sobre **el camino conversacional**, no sobre la función. Se cumple.
- El fallback sigue siendo la red de último recurso para cualquier otro caller (p. ej. un
  `task_create` que el LLM invente desde `reasoning_loop`), que es exactamente para lo que existe.

Acción para `orion-dev`: **antes** de tocar nada, escribir `tests/test_task_slots.py` con las 8 filas
de la tabla de §3.3 **y** un test que fije el comportamiento actual del fallback
(`parse_natural_task("ponme un recordatorio")["title"] == "Ponme un recordatorio"`), para que si
alguien lo cambia en el futuro, salte.

### 3.5 Decisión (d) — las dos listas de triggers NO se unifican

**Decisión: se mantienen separadas.** Solo se elimina el riesgo de una *tercera* copia.

Justificación:

1. **Responden preguntas distintas, con costos de error opuestos.**
   `_TASK_CREATE_TRIGGERS` (`core/resolution.py:117`) responde *"¿le robo esta frase al LLM y la trato
   como comando de tarea?"* — un falso positivo secuestra una conversación normal, así que tiene que
   ser conservadora. `task_triggers` (`tasks/task_manager.py:227`) responde *"ya decidí que esto es
   una tarea: ¿dónde empieza el título?"* — corre sobre texto ya clasificado, así que puede ser
   liberal sin costo.
2. **Unificar cambiaría comportamiento fuera de los criterios.** Sumar `"tengo que"`, `"debo"` y
   `"pendiente"` (suelto) a la lista de `resolution` mandaría a `task_create` frases conversacionales
   corrientísimas: *"tengo que pensarlo"*, *"debo decir que..."*, *"lo dejo pendiente"*. Hoy caen en
   `claude` y así deben seguir. Sería una regresión silenciosa que ningún CA cubre.
3. **Hay precedente en el repo.** REQ-017 sacó `"todo"` (singular) del set de "todas" exactamente por
   este motivo: era la palabra de mayor riesgo de falso positivo. Misma lógica, misma decisión.
4. **REQ-021 no necesita la unificación.** El scan usa una lista de triggers solo para *recortar* el
   prefijo (pregunta 2), así que reusa la lista liberal de `task_manager` — que es la correcta para
   ese trabajo.
5. **La divergencia es inofensiva en la dirección que importa.** La lista de 14 de `task_manager`
   **contiene por substring** a la de 12 de `resolution` (`"pendiente:"` implica `"pendiente"`; el
   resto es idéntico). Es decir: **toda frase que `_try_task_tool` acepta, `parse_natural_task`
   también la reconoce como tarea.** No existe el caso "el resolver dispara y el parser retorna
   `None`".

Acción concreta:
- En `tasks/task_manager.py`, **mover** la lista `task_triggers` del cuerpo de `parse_natural_task` a
  una constante de módulo `TASK_TRIGGERS` (move puro, sin cambiar contenido ni orden), y lo mismo con
  `date_patterns` → `TASK_DATE_PATTERNS`. `task_slots.py` las importa en vez de copiarlas.
- Añadir en ambas listas un comentario cruzado que documente la divergencia como **deliberada**, con
  el número de este REQ y un puntero a esta sección.
- Test nuevo `test_triggers_de_resolution_son_subconjunto_de_task_manager`: garantiza que la relación
  no se invierta sin que nadie se entere.

---

## 4. Pieza B — Diálogo pendiente (`core/`)

### 4.1 `core/dialog_state.py` (NUEVO)

```python
DIALOG_TTL_SECONDS: float = 180.0   # ~3 min (ASUMIDO de la SPEC, ajustable tras prueba en vivo)

@dataclass
class PendingDialog:
    action: str                 # fijado en open(), sin setter (CA-19)
    slots: dict[str, str]
    missing: tuple[str, ...]
    question: str               # última repregunta emitida (la usa CA-31)
    user_id: str
    channel_value: str
    last_progress_at: float     # monotonic; SOLO open() y fill() lo mueven (CA-32)

class DialogStore:
    def __init__(self, ttl_seconds: float = DIALOG_TTL_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None: ...
    def open(self, user_id, channel, *, action, slots, missing, question) -> PendingDialog: ...
    def get(self, user_id, channel) -> Optional[PendingDialog]: ...      # purga al leer (CA-07)
    def fill(self, user_id, channel, slot, value) -> Optional[PendingDialog]: ...  # avanza + reloj
    def touch_question(self, user_id, channel, question) -> None: ...    # NO mueve el reloj
    def cancel(self, user_id, channel) -> None: ...
    def clear_all(self) -> None: ...     # solo para tests

dialog_store = DialogStore()   # singleton de módulo, mismo patrón que task_manager/security_manager
```

- **Clave:** `(user_id, channel.value)`. Construida siempre desde los argumentos del resolver, nunca
  del texto (CA-08, CA-17).
- **`threading.RLock`** en todos los métodos: `resolve()` corre en un hilo de `QThreadPool` en el
  webview, en el hilo del bot en Telegram/Discord y en el hilo principal en la consola.
- **Sin hilo de fondo ni timer.** La expiración se evalúa en `get()`. Un diálogo abandonado no
  consume nada y no emite nada (CA-07).
- **Estado en memoria del proceso** — reiniciar la app lo pierde, por decisión de Johan.

### 4.2 `core/dialog_questions.py` (NUEVO)

```python
FALLBACK_QUESTIONS: dict[str, str] = {
    "que":    "¿Qué quiere que le recuerde?",
    "cuando": "¿Para cuándo se lo recuerdo?",
}
_MAX_QUESTION_CHARS = 200

def ask_question(action: str, slot: str, slots: dict[str, str]) -> str:
    """Return la repregunta redactada por el LLM, o la de respaldo si falla (CA-20).

    Nunca decide SI falta un dato — eso ya lo decidió `scan_task_slots()` (CA-21).
    """
```

Contrato defensivo, todo dentro de un `try/except Exception` con `logger.warning`:
`generate_response(messages, system_prompt, tools=None)`; se descarta la respuesta y se cae al
respaldo si no es `str`, si viene vacía, si excede `_MAX_QUESTION_CHARS` o si trae saltos de línea
(se colapsan). **Nunca lanza.** El respaldo también es una frase natural, no un formulario.

### 4.3 `core/resolution.py` — cambios

**(1) `ResolutionResult` gana un campo, último y con default (hallazgo (e)):**

```python
@dataclass(frozen=True)
class ResolutionResult:
    text: str
    matched_by: str
    channel: "ChannelType"
    denied: bool = False
    expects_reply: bool = False   # REQ-021: quedó una pregunta en el aire
```

Regla que `orion-dev` debe respetar literalmente: **ningún resolver muta un resultado.** Se construye
uno nuevo. El único `dataclasses.replace()` de todo el REQ está en §4.4.

**(2) Resolver nuevo `_try_pending_dialog`, en posición 0 de `RESOLVERS`:**

```python
def _try_pending_dialog(text, channel, user_id) -> Optional[ResolutionResult]:
    dialog = dialog_store.get(user_id, channel)        # purga expirados (CA-07)
    if dialog is None:
        return None                                    # camino de coste ~0 (CA-09)
    stripped = text.strip()
    if not stripped:
        return None                                    # STT vacío: no avanza ni cierra
    if _is_cancel_phrase(stripped):                    # CA-06
        dialog_store.cancel(user_id, channel)
        return ResolutionResult(_CANCEL_ACK, "pending_dialog:cancel", channel)
    slot = dialog.missing[0]
    if not _answers_slot(slot, stripped):              # CA-30: desvío de tema
        return None
    updated = dialog_store.fill(user_id, channel, slot, stripped)   # mueve el reloj (CA-32)
    if updated.missing:
        question = ask_question(updated.action, updated.missing[0], updated.slots)
        dialog_store.touch_question(user_id, channel, question)
        return ResolutionResult(question, "pending_dialog", channel, expects_reply=True)
    # Completo -> mismo camino de ejecución de siempre, con el gate intacto (CA-17, CA-19)
    composed = compose_task_sentence(updated.slots)
    try:
        result = execute_tool(updated.action,
                              {"text": composed, "user_id": user_id, "channel": channel.value},
                              channel, user_id)
    except ActionDenied as e:
        dialog_store.cancel(user_id, channel)
        return ResolutionResult(_denied_message(e), "pending_dialog", channel, denied=True)
    dialog_store.cancel(user_id, channel)              # cierra el diálogo
    return ResolutionResult(f"{result}\n\n{_DIALOG_CLOSING}", "pending_dialog", channel)
```

`_answers_slot(slot, text)` — determinista, asimétrico **a propósito**:

| Slot | Criterio de "sí responde" | Por qué |
|---|---|---|
| `cuando` | `_parse_natural_date(text) is not None` | Hay un parser duro: se puede exigir match positivo. "qué hora es" no parsea como fecha → desvío. |
| `que` | **No** es interrogativa (no empieza por `qué/cuál/cómo/cuándo/dónde/quién/por qué/para qué`, no termina en `?`) **y** tiene ≥1 token de contenido | El "qué" es texto libre: solo se puede rechazar ante señales fuertes. La forma interrogativa es la señal fuerte del caso borde de la SPEC ("qué hora es" con el "qué" pendiente). |

Consecuencia deliberada y **fail-safe** (CA-18): con el "qué" pendiente, `"apaga el pc"` se guarda
como título del recordatorio y **no se ejecuta**. Es exactamente lo que pide la SPEC.

**(3) `_try_task_tool` — solo cambia la rama `create`:**

```python
if any(t in text_lower for t in _TASK_CREATE_TRIGGERS):
    scan = scan_task_slots(text)                       # puro, sin gate: no ejecuta nada
    if scan.missing:
        question = ask_question("task_create", scan.missing[0], scan.filled)
        dialog_store.open(user_id, channel, action="task_create",
                          slots=scan.filled, missing=scan.missing, question=question)
        return ResolutionResult(question, "task_tool:dialog_open", channel, expects_reply=True)
    result = execute_tool("task_create", {...}, channel, user_id)   # rama de hoy, sin tocar
    return ResolutionResult(result, "task_tool", channel)
```

Las ramas `list` / `complete` / `complete_all` **no se tocan**.

> Nota de seguridad: llamar a `scan_task_slots()` fuera del gate es correcto porque es una función
> pura — no ejecuta, no persiste, no consulta red. El gate sigue estando exactamente donde estaba,
> dentro de `execute_tool()`.

### 4.4 Post-hook de `resolve()` — CA-31 (y el único `replace()`)

```python
result = <el del resolver ganador>
if not result.matched_by.startswith("pending_dialog") \
        and result.matched_by != "task_tool:dialog_open":
    dialog = dialog_store.get(user_id, resolved_channel)
    if dialog is not None and dialog.question:
        result = replace(result,
                         text=f"{result.text}\n\nPor cierto, {dialog.question}",
                         expects_reply=True)
```

- Vive en `resolve()`, no dentro de un resolver, porque el desvío lo puede resolver **cualquiera** de
  los 7 y `ResolutionResult` es `frozen` (hallazgo (e)).
- Determinista, sin LLM: reusa `dialog.question`, la última pregunta ya redactada.
- **No mueve `last_progress_at`** → CA-32.
- Si el resolver ganador canceló o completó el diálogo, `get()` ya retorna `None` → no-op.
- Con `dialog_store` vacío el hook es un `get()` que retorna `None` → CA-09 intacto.

---

## 5. Pieza C — Ventana de micrófono y canal bridge → worker (hallazgo (c))

### 5.1 La idea central

La restricción de Windows (`voice/wake_word.py:80-81`: un segundo `sr.Microphone()` anidado deja el
dispositivo tomado) hace inviable "abrir una escucha nueva de 15 s". La solución evita el problema
entero:

> **La ventana no abre nada. Cambia el predicado de aceptación del bucle que ya está escuchando.**

`listen_for_wake_word()` ya corre un `while True` con `recognizer.listen(source, timeout=1,
phrase_time_limit=6)` dentro de un único `with sr.Microphone() as source`. Ese bucle ya transcribe
todo lo que oye; hoy simplemente descarta lo que no trae wake word (línea 211). La ventana solo hace
que, durante ~15 s, **no** se descarte.

Consecuencias: cero micrófonos nuevos, cero llamadas bloqueantes nuevas, cero riesgo de dispositivo
trabado, y el sondeo del estado de la ventana sale gratis a ~1 Hz por el `timeout=1` que ya existe.

### 5.2 `voice/mic_window.py` (NUEVO — sin PyQt, testeable con pytest puro)

```python
MIC_WINDOW_SECONDS: float = 15.0   # ASUMIDO de la SPEC, único lugar donde vive

class ConversationWindow:
    """Canal bridge -> worker de voz. Mismo patrón que el `stop_event` que ya existe.

    El hilo de Qt solo escribe (`open`/`cancel`); el hilo del micrófono solo lee
    (`accepts`/`consume`/`expired_now`). Ninguno espera al otro: no hay `join`, no hay
    `wait`, no hay deadlock posible.
    """
    def __init__(self, duration_s: float = MIC_WINDOW_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None: ...

    def open(self) -> None:
        """Arma la ventana. Llamado desde el hilo de Qt, en el `on_done` del TTS."""

    def cancel(self) -> None:
        """Cierra la ventana ya. Manos libres OFF, parada de la app."""

    def opened_at(self) -> Optional[float]: ...

    def accepts(self, listen_started_at: float) -> bool:
        """True si un chunk que EMPEZÓ a capturarse en `listen_started_at` puede aceptarse
        sin wake word: la ventana está abierta, no vencida, y el chunk empezó DESPUÉS de
        abrirse (CA-14)."""

    def consume(self) -> None:
        """Cierra la ventana tras aceptar una frase: una frase por ventana."""

    def expired_now(self) -> bool:
        """True en la transición abierta -> vencida, una sola vez (para CA-13)."""
```

Implementación: un `threading.Lock` + dos floats (`_opened_at`, `_deadline`). No hay `Event.wait()`
en ninguna parte, así que **ningún hilo puede quedarse colgado esperando al otro**.

### 5.3 Cambios en `voice/wake_word.py`

Firma: `listen_for_wake_word(stop_event=None, wake_state_callback=None, conversation_window=None)`.
El tercer parámetro es opcional con default `None` → el uso headless desde `ui/cli.py` y los 5 tests
existentes de `test_wake_word.py` no cambian una línea.

Dentro del `while True`, dos inserciones:

```python
listen_started_at = time.monotonic()                 # ANTES de listen() — clave de CA-14
audio = recognizer.listen(source, timeout=1, phrase_time_limit=6)
...
text = <transcripción de hoy, sin cambios>
if not text:
    continue

if conversation_window is not None and conversation_window.accepts(listen_started_at):
    conversation_window.consume()                    # una frase por ventana
    _report_awake(wake_state_callback)
    logger.info(f"[Ventana] frase aceptada sin wake word: {text!r}")
    return text.strip()

is_wake, extracted_cmd = parse_wake_command(text)    # camino de hoy, intacto
...
```

Y una sola línea más al final del `while`, para que el estado visible vuelva solo:

```python
if conversation_window is not None and conversation_window.expired_now():
    _report_state(wake_state_callback, "LISTENING_WAKE")   # CA-13
```

**Estado de UI:** se reusa `AWAKE` mientras la ventana está abierta y se vuelve a `LISTENING_WAKE` al
vencer. **No se inventa un cuarto estado** — la SPEC prohíbe cambios visuales y añadir
`"CONVERSATION"` obligaría a tocar JS y CSS.

El barge-in de las líneas 142-148 **no se toca**.

> **Consecuencia aceptada:** una frase dicha *mientras el agente habla* (barge-in) empieza a
> capturarse antes de `opened_at`, así que `accepts()` la rechaza y sigue el camino de wake word.
> Es correcto: ese chunk contiene, casi con seguridad, la voz del propio agente. El barge-in sigue
> cortando la locución (que es su función); lo que no hace es colar un turno.

### 5.4 Cambios en `ui/webview/wake_word_worker.py`

```python
class WakeWordWorker(QRunnable):
    def __init__(self):
        ...
        self.conversation_window = ConversationWindow()   # público: lo lee el Bridge

    def run(self):
        while not self.stop_event.is_set():
            update_wake_state("LISTENING_WAKE")
            result = listen_for_wake_word(
                stop_event=self.stop_event,
                wake_state_callback=update_wake_state,
                conversation_window=self.conversation_window,   # ← único cambio real
            )
            ...
        finally:
            self.conversation_window.cancel()
            update_wake_state("INACTIVE")
```

El bucle del worker **no cambia de forma** (baseline §4.11): sigue llamando a `listen_for_wake_word()`
en loop. Lo que cambia es que esa llamada ahora puede devolver una frase sin wake word. Cada vuelta
del `while` reabre `sr.Microphone()` de forma **secuencial** — que es lo que hace hoy y lo que
Windows sí tolera; lo prohibido es el anidamiento.

### 5.5 Cambios en `ui/webview/bridge.py`

```python
def _on_resolve_done(self, resolution) -> None:
    ...  # message_appended, typing_stopped, store_turn, _pending_user_text = ""
    self._resolution_in_flight = False          # (5) guard liberado — posición SIN CAMBIO
    self._load_conversations(offset=0)
    self._speak_response(resolution.text)       # (7) TTS DESPUÉS de liberar el guard

def _speak_response(self, raw_text: str) -> None:
    from ui.tts_engine import prepare_for_speech, speak
    speech_text = prepare_for_speech(raw_text)
    if not speech_text:
        self._open_conversation_window(); return
    self._speech_seq += 1
    run_async(speak, self._on_speech_done, self._on_speech_error, speech_text)   # CA-25

def _on_speech_done(self, _result) -> None:
    self._open_conversation_window()            # CA-26 + CA-28

def _on_speech_error(self, message: str) -> None:
    logger.warning(f"TTS falló, la ventana se abre igual: {message}")
    self._open_conversation_window()            # CA-28

def _open_conversation_window(self) -> None:
    worker = self._wake_worker
    if worker is None or worker.stop_event.is_set():
        return                                  # manos libres OFF: no se abre nada
    worker.conversation_window.open()

def _on_resolve_error(self, message: str) -> None:
    ...                                         # no habla (un error no es respuesta del agente)
    self._resolution_in_flight = False
    self._open_conversation_window()            # pero no deja la conversación muerta (CA-28)
```

- `_on_speech_done`/`_on_speech_error` son **métodos vinculados** del `Bridge` (`QObject` del hilo de
  la GUI), como exige la regla de `ui/gui_workers.py`. Nunca `lambda`, nunca funciones sueltas.
- `self._speech_seq` (entero, inicializado en `__init__`) sirve para descartar el `on_done` de una
  locución superada por otra más nueva (riesgo R10): `orion-dev` lo implementa comparando el valor
  capturado con el actual dentro del propio método, no con una closure.
- `_stop_wake_word_worker()` añade `self._wake_worker.conversation_window.cancel()` **antes** de
  `stop_event.set()`.

### 5.6 Flujo de datos completo — 3 hilos, primer turno del caso de referencia

```
HILO MICRÓFONO (QThreadPool)           HILO GUI (Qt)                HILO WORKER (QThreadPool)
────────────────────────────           ─────────────                ─────────────────────────
listen() [wake word]
 └─"orión recuérdame algo"
     emit command_detected ────────────► _on_voice_command
                                         └─ send_message()
                                            _resolution_in_flight=True
                                            run_async(resolve) ──────► resolve()
                                                                       _try_pending_dialog -> None
                                                                       _try_task_tool
                                                                        scan -> missing=(que,cuando)
                                                                        dialog_store.open(...)
                                                                        ask_question()  [LLM]
                                         _on_resolve_done ◄──────────── ResolutionResult
                                         ├─ pinta la repregunta
                                         ├─ _resolution_in_flight=False   ← guard LIBRE
                                         └─ run_async(speak) ───────────► speak("¿Qué quiere...")
                                                                          [sintetiza ≤15s]
                                                                          [reproduce]
listen() sigue girando cada 1s           _on_speech_done ◄─────────────── fin de la locución
 (rechaza todo: ventana cerrada)         └─ window.open()  ── t0=monotonic(), deadline=t0+15
listen_started_at = t0+2 ≥ t0
 └─"llamar al contador"
     accepts(t0+2) -> True
     consume()  → ventana cerrada
     return "llamar al contador"
     emit command_detected ────────────► _on_voice_command  (guard LIBRE → no se descarta)
                                                  ... el ciclo se repite ...
```

### 5.7 Los cuatro casos difíciles del hallazgo (c), respondidos

| Pregunta | Respuesta |
|---|---|
| **¿Qué mecanismo de sincronización entre hilos?** | Un objeto con `threading.Lock` y dos floats monotónicos, escrito solo por el hilo de Qt y leído solo por el hilo del micrófono. Sin `Event.wait()`, sin `join()`, sin cola. Es el mismo patrón que el `stop_event` que ya cruza esos dos hilos hoy. |
| **¿Y si la ventana expira mientras el TTS aún habla?** | **Imposible por construcción.** La ventana no existe hasta que el `on_done` de la tarea de voz la arma. Antes de eso `accepts()` retorna `False` siempre. Si `speak()` tarda su máximo (15 s de síntesis + 60 s de tope de reproducción), la ventana abre tarde pero abre; nunca "abre y vence" mientras habla. |
| **¿Y si Johan apaga el manos libres a mitad?** | `_stop_wake_word_worker()` hace `conversation_window.cancel()` + `stop_event.set()`. La ventana se cierra en ese instante (el siguiente `accepts()` da `False`) y el worker sale en ≤1 s (el `timeout=1` del `listen`). Un `on_speech_done` tardío encuentra `stop_event.is_set()` en `_open_conversation_window()` y no hace nada. |
| **¿Cómo se evita un deadlock o un micrófono trabado?** | (1) Ningún hilo espera al otro: la comunicación es un flag, no una cita. (2) No se abre ningún `sr.Microphone()` nuevo — el único `with sr.Microphone()` del sistema sigue siendo el de `listen_for_wake_word()`. (3) Si el bridge muere o nunca llama a `open()`, el sistema degrada exactamente al comportamiento de hoy (wake word obligatoria): **fail-closed hacia el estado seguro**. (4) `consume()` cierra la ventana tras la primera frase, así que una ventana nunca puede lanzar dos resoluciones. |

---

## 6. Pieza D — Voz en el webview y texto limpio (pieza 8)

### 6.1 `ui/tts_engine.py` — función nueva, `speak()` intacto

```python
SPEECH_TRUNCATE_THRESHOLD: int = 400   # umbral de DECISIÓN (idéntico a ui/cli.py:49)
SPEECH_TRUNCATE_AT: int = 380          # punto de corte (idéntico a ui/cli.py:50)

def prepare_for_speech(text: str) -> str:
    """Return `text` listo para `speak()`: sin markdown, sin HTML, sin emojis, en una línea
    y truncado. Único lugar del sistema donde se decide QUÉ se pronuncia (CA-27)."""
```

Orden normativo de operaciones (el orden importa: los marcadores de encabezado y de lista se anclan a
principio de línea, así que el barrido de marcado va **antes** del aplanado):

1. **Marcado** — bloques cercados y backticks (se quitan los delimitadores, se conserva el contenido);
   `[texto](url)` → `texto`; viñetas `^[-*+]\s+`; encabezados `^#{1,6}\s*`; énfasis `*`/`_`;
   tags HTML `<[^>]+>`.
2. **`#N` → `número N`**, para que `🆔 #12` suene "número 12" y no se pierda el dato.
3. **Barrido final incondicional de `*` y `#`** — CA-24 exige que no quede ninguno.
4. **Emojis** — rangos Unicode explícitos, con `re`, sin dependencias nuevas: `U+2300–23FF`,
   `U+2600–27BF`, `U+2B00–2BFF`, `U+1F000–1FAFF`, más `U+FE0E/FE0F` (selectores de variación) y
   `U+200D` (ZWJ). Cubre los de `format_task_created()`: ✅ 📋 🆔 ⏰ 🔁 ⚠️ ☑️ ⛔.
5. **Higiene de espacios** — colapsar runs de espacios/tabs que dejaron los emojis. **Inaudible**: no
   altera lo que se oye.
6. **Aplanado** — `text.replace("\n", ". ")`, **literal como hoy** (`ui/cli.py:46`).
7. **Truncado** — `if len(t) > SPEECH_TRUNCATE_THRESHOLD:
   t = t[:SPEECH_TRUNCATE_AT].rsplit('.', 1)[0] + f"... La información completa está en su pantalla{vocative()}."`
   Mismo umbral, mismo corte, misma coletilla **con `vocative()`** y **con el espacio tras los tres
   puntos** — los dos detalles que el baseline (§4.5) señaló que la SPEC citaba mal.

**Dependencia de módulo:** `ui/tts_engine.py` pasa a importar `core.address.vocative`. Sin ciclo:
`core/address.py` solo importa `config_manager`, y `voice/wake_word.py` ya importa ambos.

### 6.2 Los dos consumidores

| Consumidor | Cambio | Nota |
|---|---|---|
| `ui/cli.py::display_output` | Las líneas 44-53 se reemplazan por `speak(prepare_for_speech(formal_text))`. | La personalidad (`format_response`) se sigue aplicando **antes**, como hoy: la función común empieza después de ese paso (baseline §4.5). Cambio audible **buscado**: deja de pronunciar asteriscos y emojis. |
| `ui/webview/bridge.py::_speak_response` | `speak(prepare_for_speech(resolution.text))` sobre el texto **crudo**, nunca sobre `render_markdown()`. | El webview **no** aplica `format_response`: no se le añade el "Enseguida, Señor." de la consola, y su texto visible no cambia. |

**Decisión abierta, señalada como riesgo:** CA-23 está redactado sin condición, así que el webview
pronuncia **toda** respuesta, también las de mensajes escritos. Es un cambio de comportamiento
perceptible para Johan si suele escribir. Ver §9, riesgo R3.

### 6.3 `core/reasoning_loop.py` — CA-22

```python
CONTEXT_TURNS = 5   # alineado con core/orchestrator.py:112 (conversation[-5:])

def _build_prompt(task: str, history: list[dict], prior_turns: Optional[list[dict]] = None) -> str:
    if not history and not prior_turns:
        return task                       # prompt de hoy, byte a byte (CA-22)
    ...
```

`run()` lee el historial **una sola vez antes del bucle**
(`agent_context_manager.get_context(agent_name, user_id).conversation[-CONTEXT_TURNS:]`), envuelto en
`try/except Exception` con `logger.warning` (si la DB de contexto falla, el loop debe seguir). Como
las dos escrituras de contexto siguen al final de `run()` (líneas 157-158), lo leído es estrictamente
anterior al turno en curso.

---

## 7. Hallazgo (f) — `_resolution_in_flight` y el test que lo contradice

### 7.1 Diagnóstico

El guard mezcla dos protecciones distintas:

1. **Concurrencia real** — `self._pending_user_text` es un slot único; dos `resolve()` simultáneos
   cruzan los turnos que se persisten y duplican burbujas. Esto **sigue siendo necesario**.
2. **Doble envío** — que hoy se resuelve como efecto colateral de lo anterior.

Lo que **no** protege el guard es "segundo turno de una conversación", y por eso CA-15 choca con él.

### 7.2 Cómo se distingue un segundo turno legítimo de un doble envío

**Por el momento en que puede llegar, no por una heurística sobre el texto.** El diseño de la ventana
de micrófono impone este orden:

```
resolve() termina → guard LIBERADO → TTS empieza → TTS termina → ventana ABRE → llega el 2º turno
                    ▲                                            ▲
                    └── instante A                               └── instante B (segundos después)
```

Un **segundo turno legítimo** solo puede entrar por la ventana, y la ventana solo existe después del
instante B. En B el guard lleva libre toda la locución. **CA-15 se cumple por construcción del
timeline, sin tocar el guard.**

Un **doble envío accidental** (dos `command_detected` seguidos, o el usuario escribiendo mientras
resuelve) llega **antes** de A → el guard lo descarta, que es lo correcto. Y `consume()` garantiza
que una misma ventana no pueda emitir dos frases.

### 7.3 Qué pasa con el test existente

`tests/test_wake_word_comando.py::test_bridge_ignora_comando_de_voz_si_ya_hay_una_resolucion_en_curso`:

- **Su aserción se conserva.** Descartar un comando de voz que llega con una resolución en curso
  sigue siendo el comportamiento correcto: es una colisión, no un turno.
- **Cambia de nombre y de docstring** a
  `test_bridge_descarta_un_comando_de_voz_solapado_no_un_segundo_turno`, con un docstring que explique
  que la ventana de micrófono es lo que garantiza que un segundo turno nunca llegue en ese estado, y
  que apunte a §7.2 de este documento. El problema del test era su **alcance implícito**, no su
  aserción.
- **Se añade el test que sí cubre CA-15**, sobre el invariante de orden en vez de sobre el texto:
  `test_la_ventana_de_microfono_solo_abre_con_el_guard_ya_liberado` — con `run_async` falso, verifica
  que en el instante en que se invoca `_open_conversation_window()`, `_resolution_in_flight is False`,
  y que `_speak_response` se invoca **después** de liberar el guard.

**No se implementa cola de comandos diferidos.** Se evaluó y se descarta: introduce reentrada
(`send_message` llamado desde dentro de `_on_resolve_done`) y riesgo de bucle, para cubrir un caso que
el diseño de la ventana ya hace imposible. Ver §12 "Descartado".

---

## 8. Archivos a modificar/crear

### Nuevos (4 de producción + 5 de test)

| Archivo | Contenido |
|---|---|
| `core/dialog_state.py` | `PendingDialog`, `DialogStore`, `dialog_store`, `DIALOG_TTL_SECONDS` |
| `core/dialog_questions.py` | `ask_question()`, `FALLBACK_QUESTIONS` |
| `tasks/task_slots.py` | `SlotScan`, `scan_task_slots()`, `compose_task_sentence()` |
| `voice/mic_window.py` | `ConversationWindow`, `MIC_WINDOW_SECONDS` |
| `tests/test_task_slots.py`, `tests/test_dialog_state.py`, `tests/test_dialog_resolution.py`, `tests/test_speech_prep.py`, `tests/test_mic_window.py` | Ver §10 |

### Modificados (8 de producción + 2 de test)

| Archivo | Cambio |
|---|---|
| `core/resolution.py` | `expects_reply` en `ResolutionResult`; `_try_pending_dialog` + entrada 0 de `RESOLVERS`; rama `create` de `_try_task_tool`; post-hook `_append_pending_question` en `resolve()` |
| `tasks/task_manager.py` | **Solo** promover `task_triggers` → `TASK_TRIGGERS` y `date_patterns` → `TASK_DATE_PATTERNS` a constantes de módulo (move puro) + comentario cruzado sobre la divergencia. **`parse_natural_task` no cambia de comportamiento.** |
| `core/reasoning_loop.py` | `CONTEXT_TURNS`; `prior_turns` en `_build_prompt`; lectura de `agent_context` en `run()` |
| `voice/wake_word.py` | Parámetro `conversation_window=None`; `listen_started_at`; rama de aceptación sin wake word; retorno a `LISTENING_WAKE` al vencer |
| `ui/webview/wake_word_worker.py` | `self.conversation_window`; se pasa a `listen_for_wake_word()`; `cancel()` en el `finally` |
| `ui/webview/bridge.py` | `_speech_seq`; `_speak_response`; `_on_speech_done`/`_on_speech_error`; `_open_conversation_window`; TTS al final de `_on_resolve_done`; ventana en `_on_resolve_error`; `cancel()` en `_stop_wake_word_worker` |
| `ui/tts_engine.py` | `prepare_for_speech()` + 2 constantes + import de `core.address.vocative`. **`speak()`, `is_speaking()`, `signal_barge_in()` y `_speak_edge()` no se tocan.** |
| `ui/cli.py` | `display_output` usa `prepare_for_speech()` |
| `tests/test_wake_word_comando.py` | Rename del test de §7.3 + 4 tests nuevos |
| `tests/conftest.py` | Fixture `autouse` que llama a `dialog_store.clear_all()` |

### Sin cambios (superficie de verificación de no-regresión)

`main.py`, `channels/gateway.py`, `core/orchestrator.py`, `agents/tool_registry.py`,
`core/security_manager.py`, `ui/webview/markdown_render.py`, todo `ui/webview/frontend/`.

---

## 9. Dependencias nuevas

**Ninguna. `requirements.txt` no se toca.**

| Necesidad | Se cubre con |
|---|---|
| Quitar emojis | `re` con rangos Unicode explícitos (stdlib). Se **descarta** `emoji`/`demoji`: dependencia nueva para 6 líneas de regex, en un módulo que ya usa `re`. |
| Quitar markdown | `re`. Se **descarta** reusar `markdown`+`bleach` (ya instalados) para "renderizar y desnudar": produce entidades HTML (`&amp;`) que habría que revertir, y es más lento. |
| Reloj monotónico / hilos | `time.monotonic`, `threading` (stdlib). |
| Estado de diálogo | `dict` en memoria del proceso. Sin SQLite, por decisión de Johan. |

**Aviso de git (no es acción de este agente):** `core/address.py` sigue **sin versionar** y la pieza 8
depende de él (`prepare_for_speech` usa `vocative()`). Si la rama de REQ-021 se crea desde `main`
limpio, `ui/cli.py` y `ui/tts_engine.py` no importarán. Johan debe confirmar ese archivo antes de
partir la rama.

---

## 10. Pruebas sugeridas

Todas sin micrófono, sin red y sin `sleep` real (`.claude/rules/testing.md`). `tests/conftest.py` gana
una fixture `autouse` que llama a `dialog_store.clear_all()` — sin ella, un diálogo abierto por un
test contaminaría a los 560 existentes.

### `tests/test_task_slots.py` — **zona sin red hoy (0 tests)**
1. Las **8 filas** de la tabla de §3.3, parametrizadas: entrada → `missing` esperado.
2. `compose_task_sentence` + `parse_natural_task` en cadena → `title == "Llamar al contador"` y
   `remind_at` = mañana 09:00 (**CA-02**).
3. **Fijación del fallback actual**: `parse_natural_task("ponme un recordatorio")["title"] ==
   "Ponme un recordatorio"` — pinta el comportamiento que se decide NO cambiar.
4. `parse_natural_task("recuérdame llamar al contador mañana a las 9")` → título y hora del baseline
   (**CA-03**).
5. `TASK_TRIGGERS` ⊇ `_TASK_CREATE_TRIGGERS` por substring (§3.5, decisión (d)).

### `tests/test_dialog_state.py`
6. `open`/`get`/`fill`/`cancel` (**CA-06**).
7. Expiración con reloj inyectado, sin `sleep` (**CA-07**).
8. `touch_question` **no** mueve `last_progress_at`; `fill` **sí** (**CA-32**).
9. Aislamiento: A/TELEGRAM vs B/TELEGRAM vs A/DESKTOP (**CA-08**).

### `tests/test_dialog_resolution.py`
10. `resolve("recuérdame algo")` con `execute_tool` espiado → **cero llamadas**, `expects_reply is True` (**CA-01**).
11. Caso de referencia completo por `resolve()`, 3 turnos, `matched_by` de cada uno (**CA-04, CA-05**).
12. Cancelación con las 4 frases de la SPEC (**CA-06**).
13. Desvío: `"qué hora es"` con diálogo abierto → no lo resuelve `pending_dialog`, el diálogo sigue
    vivo, y la respuesta **termina con la pregunta pendiente** (**CA-30, CA-31**).
14. **Set de regresión de `matched_by`** con `dialog_store` vacío — **hay que construirlo casi entero:
    `routine`, `autopilot`, `learned` y `capability` no se aseveran en ningún test hoy** (**CA-09**).
15. `expects_reply` por defecto `False` en las 7 rutas actuales (**CA-10**).
16. Seguridad: con diálogo abierto, un trigger YELLOW (`"cierra chrome"`) y uno RED
    (`"borra la base de datos"`) → `dispatch`/`execute_action` **nunca** se invocan y el texto queda
    como slot (**CA-18**).
17. La acción destino nunca cambia: `dialog.action == "task_create"` tras llenar un slot con texto de
    otra acción (**CA-19**).
18. `generate_response` mockeada para lanzar → el diálogo se abre igual con la frase de respaldo, y el
    LLM **nunca** se llama para detectar (**CA-20, CA-21**).
19. Los 3 canales: mismo diálogo, mismo resultado (**CA-11**).

### `tests/test_speech_prep.py` — **zona sin red hoy (0 tests)**
20. Salida real de `format_task_created()` → sin `*`, sin `#`, sin emojis (**CA-24**).
21. Aplanado, umbral 400, corte en 380 al último punto, coletilla **con `vocative()` y con espacio
    tras los puntos** (**CA-27**).
22. Regresión de `ui/cli.py::display_output` con `speak` mockeado: se invoca **una vez** y con el
    texto que devuelve `prepare_for_speech(format_response(t))` — el resto del pipeline intacto
    (**CA-27**).
23. Idempotencia: `prepare_for_speech(prepare_for_speech(t)) == prepare_for_speech(t)`.

### `tests/test_mic_window.py`
24. `accepts()` es `False` antes de `open()`, `True` dentro de la ventana, `False` pasado el deadline
    (reloj inyectado) (**CA-12, CA-13**).
25. **CA-14:** un chunk con `listen_started_at < opened_at` se rechaza aunque la ventana esté abierta.
26. `consume()` cierra: la segunda frase de la misma ventana se rechaza.
27. `cancel()` cierra en el acto (manos libres OFF a mitad).
28. `listen_for_wake_word` con recognizer falso: devuelve la frase sin wake word con la ventana
    abierta, y **no** la devuelve con la ventana cerrada (**CA-12, CA-13**).

### `tests/test_wake_word_comando.py` (modificado)
29. Renombrar `test_bridge_ignora_comando_de_voz_si_ya_hay_una_resolucion_en_curso` →
    `test_bridge_descarta_un_comando_de_voz_solapado_no_un_segundo_turno` (misma aserción, §7.3).
30. **Nuevo:** `test_la_ventana_de_microfono_solo_abre_con_el_guard_ya_liberado` (**CA-15**).
31. **Nuevo:** `_on_resolve_done` invoca `run_async(speak, ...)` **exactamente una vez** y nunca
    `speak()` directo (**CA-23, CA-25**).
32. **Nuevo:** `_on_speech_error` y `_on_resolve_error` abren la ventana igual (**CA-28**).
33. **Nuevo:** `prepare_for_speech` recibe `resolution.text`, **nunca** el HTML de `render_markdown`
    (**CA-24**).

### `tests/test_reasoning_loop.py` (ampliado)
34. `_build_prompt(task, [], None) == task` (**CA-22**).
35. Con 7 turnos en `agent_context`, el prompt incluye los últimos 5 y no los 2 primeros (**CA-22**).

**Línea a batir (baseline):** `2 failed, 560 passed`. Cualquier tercer fallo es regresión de REQ-021.

---

## 11. Riesgos y mitigación

| # | Riesgo | Prob. | Impacto | Mitigación |
|---|--------|-------|---------|-----------|
| **R1** | **El micrófono capta la respuesta del propio agente** y crea tareas fantasma. Es el riesgo #1 del REQ. | Media | Alto | Doble candado: la ventana solo se arma en el `on_done` del TTS (CA-26) **y** el chunk debe haber empezado a capturarse después de `opened_at` (CA-14). `consume()` limita a una frase por ventana. Tests 24-28. |
| **R2** | **Ruido ambiente / TV durante los 15 s** produce transcripciones espurias que llenan un slot. | Media | Medio | `_answers_slot("cuando", ...)` exige que parsee como fecha; el "qué" solo se llena con contenido real. El diálogo siempre confirma antes de crear (CA-05). Residual aceptado por la SPEC; `MIC_WINDOW_SECONDS` está en un único sitio para bajarlo tras la prueba. |
| **R3** | **El webview empieza a hablar en respuestas escritas.** CA-23 no lo condiciona a manos libres. | Alta | Medio | Es lo que dice el criterio aprobado. Se implementa así y **se pregunta a Johan en la prueba manual**; condicionarlo a `_wake_worker is not None` son 2 líneas si molesta. |
| **R4** | Regresión en `core/resolution.py`, punto único de los 4 canales. | Baja | Alto | `_try_pending_dialog` retorna `None` en su primera línea con el store vacío. CA-09 (set de regresión de los 7 resolvers) + CA-10 son el cinturón. |
| **R5** | `_answers_slot("que", ...)` acepta como título una frase que era un comando nuevo no interrogativo ("apaga el pc"). | Media | Bajo | **Es el comportamiento exigido por CA-18** y falla en sentido seguro (no ejecuta nada). Se cancela con "olvídalo". Documentado como decisión, no como defecto. |
| **R6** | La repregunta del LLM añade **latencia** (una llamada extra por turno de diálogo). | Alta | Bajo | Es la decisión de motor híbrido ya cerrada. `FALLBACK_QUESTIONS` cubre el fallo, no la lentitud. Si molesta en la prueba, invertir el orden (respaldo inmediato + LLM solo en el cierre) es un cambio de 3 líneas. |
| **R7** | `reasoning_loop` puede invocar `task_create` con texto incompleto por su cuenta (el scan solo gatea `_try_task_tool`). | Baja | Bajo | Toda frase con trigger de creación es interceptada por `_try_task_tool` **antes** de llegar a `claude`, así que el LLM solo ve frases sin trigger. Residual conocido; mover el scan dentro de `_task_create_invoke` queda como candidato de v2. |
| **R8** | `core/address.py` sin versionar; la pieza 8 depende de él. | Media | Alto | Fuera del alcance del agente. Johan debe confirmarlo antes de crear la rama desde `main`. Ya avisado. |
| **R9** | Cambiar `ui/cli.py` sin red de tests (0 tests hoy). | Media | Medio | Tests 20-23 se escriben **antes** de tocar el archivo. |
| **R10** | Dos locuciones solapadas (usuario escribe mientras el agente habla) abren la ventana dos veces. | Baja | Bajo | `_speech_seq`: solo el `on_done` de la locución más reciente arma la ventana. |
| **R11** | Deuda P2 aceptada: la voz del webview resuelve como `DESKTOP`, no `VOICE`. La ventana **aumenta el volumen** de frases por esa vía. | — | Medio | Riesgo aceptado explícito de la SPEC. **`orion-security` debe revisarlo cuando le toque.** El diseño no lo agrava más allá de lo previsto: CA-18 hace que, con diálogo abierto, esas frases ni siquiera se ejecuten. |

### Los 3 que más probablemente exploten en la prueba manual de Johan

1. **R1 — el agente se escucha a sí mismo.** Toda la cadena (bridge → `run_async` → `on_done` →
   `ConversationWindow.open()` → `accepts(listen_started_at)`) tiene que estar bien de punta a punta,
   y cruza tres hilos. Si falla, el síntoma es ruidoso y desmoralizante: tareas fantasma con el texto
   de la propia respuesta del agente. Es lo primero que hay que mirar en la prueba.
2. **R3 — el webview hablando en respuestas escritas.** No es un bug, es CA-23 al pie de la letra,
   pero es el cambio que Johan va a notar en el primer minuto y el más probable de que pida revertir.
   Mejor anticiparlo que descubrirlo.
3. **R2 + R6 juntos — el ritmo de la conversación.** 15 s puede quedarse corto para pensar la
   respuesta y largo para el ruido; y la llamada al LLM para redactar la repregunta mete un silencio
   entre el "recuérdame algo" y el "¿Qué quiere que le recuerde?". El caso de referencia puede
   funcionar perfecto y aun así **sentirse** mal. Los dos números son constantes con nombre en un
   único lugar, justamente para poder ajustarlos sin rediseñar.

---

## 12. Orden de implementación sugerido para `orion-dev`

Cada paso deja la suite verde antes de pasar al siguiente.

1. **Red de seguridad primero** — `tests/test_task_slots.py` (fijación del comportamiento actual de
   `parse_natural_task`) y el set de regresión de `matched_by` de CA-09. **Sin tocar código de
   producción.** Es donde el baseline detectó que no hay red.
2. `prepare_for_speech()` + tests + `ui/cli.py`. Aislado, sin hilos, cierra CA-24/CA-27.
3. `tasks/task_slots.py` + el *move* de las dos constantes en `task_manager.py`.
4. `core/dialog_state.py` + `core/dialog_questions.py` + tests.
5. `core/resolution.py`: `expects_reply` → `_try_pending_dialog` → `_try_task_tool` → post-hook.
6. `core/reasoning_loop.py` (CA-22). Independiente del resto.
7. `voice/mic_window.py` + `voice/wake_word.py` + `wake_word_worker.py` + tests.
8. `ui/webview/bridge.py` (pieza 8 + ventana). **Último**: depende de 2 y de 7.
9. Suite completa: la línea a batir es `2 failed, 560 passed`.

### Descartado (y por qué)

- **Unificar las dos listas de triggers** — cambia el comportamiento de frases que hoy van a `claude`,
  fuera de los criterios (§3.5).
- **Modificar el fallback de `parse_natural_task:262`** — cero tests, alcance ajeno y el diseño lo
  vuelve inalcanzable desde el camino conversacional (§3.4).
- **Construir el `dict` de la tarea a mano desde el diálogo** — abriría un segundo camino de creación
  que se desincronizaría del actual. Se recompone la frase (§3.2).
- **Parametrizar `prepare_for_speech(strip_markup=...)`** — dos modos de sonar es exactamente el drift
  que la decisión de extraer quería evitar. Se arregla en las dos vías (§0).
- **Sondear `is_speaking()` para abrir la ventana** — `_speaking` se activa después de sintetizar
  (baseline §4.9): abriría el micrófono justo antes de hablar.
- **Abrir una escucha nueva de 15 s** — segundo `sr.Microphone()`, falla en Windows (baseline §4.10).
- **Un cuarto estado de wake `"CONVERSATION"`** — obligaría a tocar JS/CSS; la SPEC prohíbe cambios
  visuales. Se reusa `AWAKE`.
- **Cola de comandos de voz diferidos en el bridge** — introduce reentrada y riesgo de bucle para
  cubrir un caso que el diseño de la ventana ya hace imposible (§7.3).
- **Debilitar `_resolution_in_flight`** — sigue protegiendo `_pending_user_text` de dos resoluciones
  concurrentes. CA-15 se cumple por orden temporal, no aflojando el guard.
- **Persistir el diálogo en SQLite** — descartado por Johan.
- **Leer `expects_reply` en algún consumidor en v1** — nadie lo necesita; leerlo inventaría
  comportamiento que ningún CA pide y pondría en riesgo CA-10.

---

## 13. Nota de seguridad para `orion-security`

Este REQ **no crea ningún camino de ejecución nuevo**. Todo lo que puede tocar el sistema sigue
pasando por `execute_tool()` con el `channel` que pasa el caller (CA-17). Puntos a auditar:

1. `_try_pending_dialog` en posición 0 hace que, con diálogo abierto, una frase con trigger
   YELLOW/RED **no se ejecute** (CA-18). Verificar que no exista ninguna ruta que salte el resolver.
2. `PendingDialog.action` se fija al abrir y no tiene setter (CA-19).
3. `scan_task_slots()` corre fuera del gate — verificar que sea puro (sin I/O, sin ejecución).
4. `dialog_store` guarda `channel.value` **solo** como clave de partición; nunca lo pasa al gate.
5. **Deuda P2 aceptada:** la voz del webview resuelve como `DESKTOP`, no `VOICE`, y la ventana de
   15 s aumenta el volumen de frases que entran por esa vía. Revisar y decidir si merece REQ propio.

---

## 14. Nota de salida

`ARCH OK | REQ-021 | archivos=19 (9 nuevos + 10 modificados) | schema=NO | aprobado=PENDIENTE | siguiente=@orion-dev (tras gate humano)`
