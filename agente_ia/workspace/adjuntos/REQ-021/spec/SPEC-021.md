# SPEC-021 — Conversación multi-turno real (diálogo pendiente + ventana de micrófono)

**Estado:** ⏸️ ESPERANDO VALIDACIÓN
**Categoría:** CORE (secundaria: VOZ)
**Tipo:** FEATURE_NUEVA
**Fecha:** 2026-08-26

---

## Objetivo

Hoy O.R.I.O.N. resuelve toda frase de un solo tiro: si le falta un dato, lo inventa y cierra el
flujo. "Recuérdame algo" crea una tarea titulada "Algo" con recordatorio a una hora, sin preguntar
nada. Este REQ introduce un mecanismo general de **diálogo pendiente**: cuando falta un dato
obligatorio, el agente lo pregunta en vez de inventarlo, y mantiene el hilo hasta completarlo.
En manos libres, además, el micrófono queda abierto tras responder, para que la conversación
fluya sin repetir la wake word en cada turno.

---

## Alcance

**Incluye**
- Mecanismo **general y reutilizable** de diálogo pendiente por `(user_id, canal)`, con expiración.
- Contrato de datos obligatorios (slots) por acción, **cableado en v1 solo a `task_create`**.
- Motor **híbrido**: reglas deterministas detectan qué dato falta; el LLM redacta la repregunta y
  lleva el hilo conversacional. Ninguna frase se manda al LLM solo para detectar el dato faltante.
- Cancelación explícita del diálogo ("olvídalo", "cancela").
- Expiración silenciosa del diálogo a los ~3 min.
- Ventana de micrófono de ~15 s tras cada respuesta en manos libres, sin exigir wake word.
- **Pieza 8 — voz en el webview:** la respuesta del agente en la app de escritorio se pronuncia.
  Hoy no se pronuncia en absoluto, y sin esto el caso de referencia no puede funcionar (P1).
- `reasoning_loop` pasa los últimos N turnos de `agent_context` al LLM.
- Tests de regresión de los 3 canales existentes (escritorio/webview, Telegram, Discord).

**No incluye**
- Conectar el mecanismo a acciones distintas de tareas/recordatorios (se diseña general, se cablea
  a una sola acción). Cualquier otra acción se conecta en un REQ posterior.
- Guardar tareas con datos parciales — descartado explícitamente por Johan.
- Retomar un diálogo expirado en la siguiente sesión — descartado explícitamente por Johan.
- Conversación multi-turno nativa del proveedor LLM (`tool_use`/`tool_result`) — sigue vigente la
  decisión de `arquitectura-007.md` de mandar mensajes autocontenidos.
- Rediseño de UI. Ningún cambio visual en el webview más allá de lo que ya hace el chat.
- Corregir que el camino de voz del webview resuelva como `DESKTOP` y no como `VOICE`.
  **Riesgo aceptado y explícito** — ver la sección *Riesgo aceptado (P2)* más abajo.

---

## Módulos afectados

| Módulo | Qué cambia |
|--------|------------|
| `core/dialog_state.py` | **NUEVO.** Estado de diálogo pendiente por `(user_id, canal)`: acción destino, slots llenos, slot faltante, timestamp de expiración. Abrir / responder / cancelar / expirar. |
| `core/resolution.py` | Nuevo resolver `_try_pending_dialog`, **primero** en `RESOLVERS`. `_try_task_tool` (línea 177) deja de disparar `task_create` por keyword sin verificar contenido. `ResolutionResult` (línea 31) gana el campo `expects_reply: bool = False`. |
| `tasks/task_manager.py` | `parse_natural_task` (líneas 262-274) deja de ser el punto que inventa título ("Algo") y fecha (`now() + 1h`) para el camino conversacional. La detección de "falta el qué / falta el cuándo" debe quedar consultable antes de crear nada. |
| `core/reasoning_loop.py` | `_build_prompt` (línea 72) incorpora los últimos N turnos de `agent_context` (hoy se escribe en las líneas 157-158 y nunca se relee). |
| `voice/wake_word.py` | Ventana de escucha de ~15 s tras la respuesta, sin exigir wake word. Apoyada en `is_speaking()` / `signal_barge_in()` (líneas 145-150). |
| `ui/webview/wake_word_worker.py` | Señal/estado para abrir la ventana de conversación desde el bridge hacia el worker (hoy el flujo es de una sola dirección: `command_detected`, línea 32). |
| `ui/webview/bridge.py` | `_on_resolve_done` (línea 245) informa `expects_reply`, **pronuncia la respuesta (pieza 8)** vía `run_async`, y encadena la ventana de micrófono al fin de esa tarea de voz. Revisión del guard `_resolution_in_flight` (líneas 229 y 712). |
| `ui/tts_engine.py` | **Pieza 8.** Nueva función de preparación de texto para voz (aplanar saltos de línea, quitar markdown y emojis, truncar). `speak()` (línea 81) y `is_speaking()`/`signal_barge_in()` (18/22) **no se tocan**. |
| `ui/cli.py` | **Pieza 8.** `display_output` (líneas 44-53) pasa a usar la función común en vez de su lógica inline. Su salida audible **gana la limpieza de markdown/emojis** (CA-27 reescrito); el resto de su pipeline (aplanado, umbral, corte, coletilla) queda idéntico al de hoy. |
| `main.py`, `channels/gateway.py`, `core/orchestrator.py` | **Sin cambios funcionales esperados.** Son los otros 3 consumidores de `resolve()` (líneas 196, 92 y 50). Entran solo como superficie de verificación de no-regresión. |
| `tests/` | Tests nuevos de `dialog_state`, del resolver de diálogo, de la preparación de texto para voz y de la no-regresión de `resolve()` y de `ui/cli.py`. |

---

## Comportamiento actual vs deseado

| Actual | Deseado |
|--------|---------|
| "Recuérdame algo" → crea tarea "Algo" con recordatorio a 1 hora. | "Recuérdame algo" → "¿Qué quiere que le recuerde?" y no se crea nada todavía. |
| `resolve()` es stateless: entra texto, sale texto. Ninguna intención queda pendiente. | Una intención incompleta queda abierta por `(user_id, canal)` hasta completarse, cancelarse o expirar. |
| "Mañana a las 9" dicho suelto se resuelve como comando nuevo (o cae en el LLM). | Con diálogo abierto, se interpreta como la respuesta al dato que faltaba. |
| Tras responder, el worker de voz vuelve a exigir la wake word (`voice/wake_word.py:239`). | Tras responder, el micrófono queda abierto ~15 s. El silencio lo cierra y vuelve a modo wake word. |
| El LLM no ve turnos anteriores (`_build_prompt` arma un mensaje autocontenido). | El LLM recibe los últimos N turnos y puede sostener el hilo. |
| Falta un dato → se inventa. | Falta un dato → se pregunta, con una frase que suena a persona, no a formulario. |

---

## Caso de referencia (criterio de éxito narrativo, literal de Johan)

```
"Orión, recuérdame algo"      → "¿Qué quiere que le recuerde?"
"llamar al contador"          → "¿Para cuándo?"
"mañana a las 9"              → "Listo, mañana a las 9. ¿Algo más?"
```
Sin repetir la wake word ni una sola vez.

---

## Criterios de aceptación

### Diálogo pendiente — núcleo

- [ ] **CA-01** — `resolve("recuérdame algo", ...)` **no** invoca `execute_tool("task_create", ...)`,
      no inserta ninguna fila en `tasks.db`, y devuelve una repregunta por el dato faltante con
      `expects_reply == True`.
- [ ] **CA-02** — Ninguna tarea creada por el camino conversacional queda con título derivado de una
      frase sin contenido (nunca "Algo") ni con fecha inventada por defecto (`now() + 1h`). Tras
      completar el caso de referencia, la tarea tiene título "Llamar al contador" y `remind_at`
      correspondiente a mañana 09:00.
- [ ] **CA-03** — **No regresión de un solo tiro:** "recuérdame llamar al contador mañana a las 9"
      crea la tarea inmediatamente, sin repreguntar, con `expects_reply == False`. El comportamiento
      actual de las frases completas no cambia.
- [ ] **CA-04** — Con un diálogo abierto esperando el "qué", la frase suelta "llamar al contador" se
      resuelve por el resolver de diálogo (`matched_by` del diálogo pendiente) y **no** por
      `routine`, `autopilot`, `learned`, `task_tool`, `capability`, `intent` ni `claude`.
- [ ] **CA-05** — Tras llenar el "qué", el agente pregunta por el "cuándo"; "mañana a las 9" completa
      el diálogo, crea la tarea y la respuesta de cierre menciona el qué y el cuándo confirmados.
- [ ] **CA-06** — "olvídalo", "cancela", "déjalo" y "nada" con un diálogo abierto lo cierran: no se
      crea ninguna tarea, `expects_reply == False`, y la siguiente frase se resuelve como comando
      nuevo por el orden normal de `RESOLVERS`.
- [ ] **CA-07** — Un diálogo sin actividad por más del TTL (~3 min) se descarta **en silencio**: no
      se crea nada, no se emite ningún mensaje al usuario, y la siguiente frase se resuelve como
      comando nuevo. El test controla el reloj (monkeypatch / reloj inyectado), no usa `sleep` real.
- [ ] **CA-08** — Aislamiento del estado: un diálogo abierto del usuario A en `TELEGRAM` no afecta la
      resolución del usuario B, ni la del usuario A en `DESKTOP`. La clave del estado es
      `(user_id, canal)` y no hay fuga entre entradas.

### No regresión de los canales

- [ ] **CA-09** — Con el estado de diálogo vacío, `resolve()` produce el mismo `matched_by` que hoy
      para un set de regresión con al menos una frase por resolver (`routine`, `autopilot`,
      `learned`, `task_tool` en sus 4 ramas —crear / listar / completar / completar todas—,
      `capability`, `intent`, `claude`). Insertar el resolver de diálogo primero no altera ninguna.
- [ ] **CA-10** — `expects_reply` se agrega con valor por defecto `False`, de modo que los 4
      consumidores de `resolve()` (`main.py:196`, `channels/gateway.py:92`, `core/orchestrator.py:50`,
      `ui/webview/bridge.py:242`) siguen funcionando sin leerlo. La suite de tests existente pasa sin
      modificaciones.
- [ ] **CA-11** — Telegram y Discord siguen creando, listando y completando tareas exactamente como
      hoy. Un diálogo abierto en esos canales se comporta igual que en escritorio (mismo mecanismo,
      sin lógica duplicada por canal).

### Ventana de micrófono (manos libres)

- [ ] **CA-12** — Tras responder en manos libres, el micrófono acepta una frase nueva durante ~15 s
      **sin** wake word, y esa frase llega a `resolve()` por el mismo camino que un comando dictado
      después de la wake word.
- [ ] **CA-13** — Si pasan los ~15 s sin voz, la ventana se cierra, el worker vuelve a
      `LISTENING_WAKE`, y una frase posterior sin wake word **no** se resuelve.
- [ ] **CA-14** — **El agente no se escucha a sí mismo:** la respuesta del propio agente nunca se
      transcribe como turno del usuario. La ventana no empieza a contar ni acepta audio antes de
      que la locución haya terminado. **No basta con sondear `is_speaking()`** — ver CA-26 y la
      nota de diseño sobre `_speaking`.
- [ ] **CA-15** — El guard `_resolution_in_flight` (`ui/webview/bridge.py:229`, y su chequeo previo en
      `_on_voice_command`, línea 712) **no** descarta el segundo turno del caso de referencia. En el
      log del caso de referencia completo no aparece ninguna línea
      `"Comando por voz ignorado (resolución en curso)"`.
- [ ] **CA-16** — El caso de referencia completo (3 turnos del usuario, 3 respuestas del agente)
      se ejecuta de principio a fin en manos libres desde el webview, **con las 3 respuestas
      pronunciadas en voz alta**, sin repetir la wake word, y termina con la tarea creada
      correctamente.

### Seguridad

- [ ] **CA-17** — El mecanismo de diálogo **no** altera el nivel efectivo de ninguna acción. El gate
      `require_confirmation()` se sigue evaluando dentro de `execute_tool()` con el canal real que
      pasa el caller, nunca con un canal deducido del texto ni del estado del diálogo (mismo
      invariante de REQ-005/REQ-019).
- [ ] **CA-18** *(REESCRITO 2026-08-26 tras la auditoría de seguridad — ver nota al final de esta
      sección)* — **El diálogo no es una vía de escape:** el diálogo **no altera el nivel efectivo de
      riesgo de ninguna acción ni evita el gate de confirmación**. Se verifica en dos escenarios:
      (a) con el slot `que` pendiente, una frase no interrogativa con trigger `YELLOW` o `RED` se
      guarda como texto del slot y **no** ejecuta esa acción — *fail-safe* deliberado;
      (b) con el slot `cuando` pendiente, esa misma frase se desvía y se resuelve por el camino
      normal, y entonces `require_confirmation()` **se evalúa con el canal real del caller**,
      exactamente igual que si no hubiera ningún diálogo abierto. Test explícito con un trigger
      `YELLOW` y uno `RED` en ambos escenarios.

> **Nota de trazabilidad de CA-18.** La redacción original ("una frase con trigger `YELLOW`/`RED` se
> trata como texto del slot y no ejecuta esa acción", sin distinguir el slot pendiente) fue aprobada
> por Johan junto al resto de la SPEC. La auditoría de seguridad
> (`propuestas/security-audit-021.md`, hallazgo **H1**) encontró que **contradice a CA-30**: el
> criterio `_answers_slot()` es asimétrico a propósito — el slot `cuando` exige que el texto parsee
> como fecha, así que cualquier frase que no lo sea se desvía y se ejecuta por el camino normal. Con
> la redacción original, el test que la propia SPEC obliga a escribir fallaría por diseño.
> Verificado que **no es una vulnerabilidad**: el gate `require_confirmation()` se sigue evaluando
> con el canal real, el nivel efectivo no cambia, las acciones `RED` siguen bloqueadas por el
> fail-closed de REQ-005, y `PendingDialog.action` no tiene setter (CA-19 intacto). El diálogo no
> abre ninguna puerta que no estuviera ya abierta. Se reescribe el criterio para que afirme lo
> verificable y lo que de verdad importa, en vez de romper CA-30.
- [ ] **CA-19** — Un diálogo solo puede desembocar en la misma acción que la frase inicial habría
      disparado. No existe camino por el cual el contenido de un slot cambie la acción destino.
      En v1 la única acción alcanzable por diálogo es `task_create` (`GREEN`).

### Calidad conversacional

- [ ] **CA-20** — Las repreguntas las redacta el LLM y suenan a persona ("¿Qué quiere que le
      recuerde?"), no a formulario ("Campo requerido: título"). Si el LLM no responde o falla, hay un
      texto de respaldo fijo que **también** es una frase natural, y el flujo continúa igual.
- [ ] **CA-21** — Detectar qué dato falta es determinista y no consume LLM: con el LLM mockeado para
      fallar, el diálogo se abre igual y hace la repregunta de respaldo. Ninguna frase se envía al
      LLM con el único fin de decidir si falta un dato.
- [ ] **CA-22** — `_build_prompt` (`core/reasoning_loop.py`) incluye los últimos N turnos de
      `agent_context` cuando existen, y sigue produciendo el mismo prompt de hoy cuando no hay
      historial previo.

### Pieza 8 — voz en el webview

- [ ] **CA-23** *(AJUSTADO 2026-08-26 — ver nota al final de esta sección)* — La respuesta del agente
      en el webview **se pronuncia solo cuando el modo manos libres está activo**. Con `speak()`
      mockeado: se invoca exactamente una vez por turno resuelto con el worker de wake word activo
      (ni cero, ni dos veces por el mismo turno), y **cero veces** cuando Johan escribió el mensaje
      con el manos libres apagado. La condición se evalúa sobre el estado real del worker
      (`_wake_worker is not None`), nunca sobre el texto ni sobre el canal declarado.

> **Nota de trazabilidad de CA-23.** La redacción original ("la respuesta se pronuncia", sin
> condición) fue aprobada por Johan junto al resto de la SPEC. `orion-architect` la marcó como
> riesgo **R3** (§11 de `arquitectura-021.md`): al no distinguir voz de texto, el webview
> pronunciaría también las respuestas a mensajes escritos. Consultado explícitamente antes de
> empezar el desarrollo — y no en la prueba manual final —, Johan eligió **"solo en manos libres"**.
> R3 queda cerrado por diseño en vez de quedar como riesgo abierto a revertir después.
- [ ] **CA-24** — Se pronuncia **texto plano**: sin marcas de markdown (`*`, `#`, `_`, backticks), sin
      HTML, y sin emojis. Test con la salida real de `format_task_created()`
      (`tasks/task_manager.py:539`) —que trae `*#12*` y 🔁—: el texto que llega a `speak()` no contiene
      `*`, ni `#`, ni caracteres emoji. El origen del texto es la respuesta cruda (`resolution.text`),
      nunca el HTML de `render_markdown()`.
- [ ] **CA-25** — **No congela la UI:** `speak()` (bloqueante, `ui/tts_engine.py:81`) nunca se invoca
      desde el hilo de la GUI. Se despacha por `run_async` (`ui/gui_workers.py:53`), el mismo helper
      que el bridge ya usa para `resolve` y `memory.store_turn`.
- [ ] **CA-26** — La ventana de micrófono abre **encadenada al `on_done` de la tarea de voz**, no en
      `_on_resolve_done` ni por sondeo de `is_speaking()`. Es el mecanismo que hace cumplir CA-14.
- [ ] **CA-27** *(REESCRITO 2026-08-26 — ver nota al final de esta sección)* — La preparación del texto
      para voz vive en **un solo lugar**, reusado por el webview y por la consola. **Ambas superficies
      suenan limpias**: el texto que llega a `speak()` desde cualquiera de las dos no contiene markdown
      (`*`, `#`, `_`, backticks), ni HTML, ni emojis. **El resto del pipeline de la consola no cambia**:
      mismo aplanado de saltos de línea (`"\n"` → `". "`), mismo umbral de decisión de 400 caracteres,
      mismo corte en 380 al último punto, y misma coletilla
      `"... La información completa está en su pantalla" + vocative() + "."` (con `vocative()`, no un
      literal fijo, y con el espacio después de los tres puntos). Test de regresión sobre `ui/cli.py`.

> **Nota — cambio post-aprobación (2026-08-26, decidido por la sesión principal).**
> CA-27 fue reescrito **después** de que Johan aprobara la SPEC. `orion-baseline` verificó (§4.4 de
> `origen/baseline-021.md`) que CA-24 y la redacción original de CA-27 eran **incompatibles**: hoy
> `ui/cli.py` pronuncia literalmente los asteriscos y los emojis, así que una función común que
> limpiara el texto (CA-24) cambiaba por definición la salida audible de la consola (CA-27 original).
> **Resolución: se arregla en las dos vías** — la consola gana la mejora en vez de conservar el
> defecto. Lo único que se exige preservar es el resto del pipeline de la consola (aplanado, umbral,
> corte y coletilla). **Johan debe ver este cambio en el gate de aprobación de arquitectura.**
- [ ] **CA-28** — Un fallo del TTS (edge-tts no instalado, timeout de síntesis, fallo de reproducción)
      **no rompe el turno**: la respuesta ya está en pantalla, el fallo se registra en log, y la ventana
      de micrófono se abre igual — para no dejar la conversación muerta por un problema de audio.
- [ ] **CA-29** — El barge-in sigue funcionando: si el usuario habla mientras el agente pronuncia,
      `signal_barge_in()` corta la locución, y **el diálogo pendiente sobrevive a la interrupción**
      (interrumpir no equivale a cancelar).

### Desvío de tema con diálogo abierto

- [ ] **CA-30** — Con un diálogo abierto, una frase que claramente no responde al slot pendiente
      ("qué hora es") se resuelve como comando nuevo por el orden normal de `RESOLVERS`, el agente
      **responde esa pregunta**, y el diálogo pendiente **sigue vivo**.
- [ ] **CA-31** — En esa misma respuesta el agente **vuelve a formular la pregunta pendiente**, con
      naturalidad ("...Por cierto, ¿para cuándo le recuerdo lo del contador?"). Así la pregunta
      pendiente es siempre lo último que se preguntó, y la frase siguiente se lee sin ambigüedad como
      su respuesta.
- [ ] **CA-32** — El desvío **no reinicia** el contador de expiración: el TTL de ~3 min se cuenta desde
      el último turno que hizo *avanzar* el diálogo (abrirlo o llenar un slot), no desde el último turno
      cualquiera. Un diálogo con desvíos continuos expira igual a los ~3 min de su último avance real.


---

## Casos borde

- Frase con "recuérdame" pero sin contenido real: "recuérdame", "recuérdame algo",
  "recuérdame una cosa", "ponme un recordatorio" → todas abren diálogo, ninguna crea tarea.
- Frase con el "qué" pero sin el "cuándo": "recuérdame llamar al contador" → pregunta solo el
  cuándo, no vuelve a preguntar el qué.
- Frase con el "cuándo" pero sin el "qué": "recuérdame mañana a las 9" → pregunta solo el qué.
- Respuesta del usuario que **no** responde la pregunta (llega "qué hora es" mientras se espera el
  "cuándo"): se responde la pregunta nueva y el diálogo sigue vivo, re-formulando la pendiente en la
  misma respuesta. Resuelto por Johan — ver CA-30, CA-31 y CA-32.
- Respuesta vacía o ininteligible (el STT devuelve `""`): no cuenta como turno, no cierra ni avanza
  el diálogo, no reinicia el TTL por sí sola.
- Usuario abre un diálogo y luego dicta una frase completa de otra acción: no debe crear una tarea
  con el texto de esa otra frase.
- Dos canales en paralelo para el mismo `user_id` (Telegram y escritorio a la vez): dos diálogos
  independientes, sin contaminación cruzada.
- Ruido ambiente o TV durante la ventana de ~15 s: transcripciones espurias no deben crear tareas.
  La combinación de CA-14 y la confirmación final del diálogo es la mitigación de partida.
- Reinicio de la app con un diálogo abierto: el diálogo se pierde (es estado en memoria) y **no**
  crea nada. Consistente con la decisión de descartar en silencio.
- Barge-in: el usuario interrumpe al agente mientras habla. `signal_barge_in()` ya existe; el
  diálogo abierto debe sobrevivir a la interrupción, no cancelarse por ella.

---

## Asumidos

- **ASUMIDO** — ~15 s de ventana de micrófono y ~3 min de TTL del diálogo son valores de partida, no
  medidos. Se esperan ajustes tras la prueba en vivo. Deben quedar como constantes con nombre en un
  único lugar, no repartidas por el código.
- **ASUMIDO** — Los slots obligatorios de `task_create` en v1 son exactamente dos: el **qué**
  (título) y el **cuándo** (`remind_at`). Prioridad y recurrencia siguen siendo opcionales y se
  siguen infiriendo del texto como hoy, sin repreguntarse nunca.
- **ASUMIDO** — El estado de diálogo vive **en memoria del proceso**, no en SQLite. Se deriva de la
  decisión de Johan de descartar el diálogo en silencio y no retomarlo en la siguiente sesión.
- **ASUMIDO** — "N últimos turnos" de `agent_context` para el LLM = 5, alineado con el corte que ya
  usa `core/orchestrator.py:112` (`conversation[-5:]`).
- **ASUMIDO** — El orden de `RESOLVERS` cambia **solo** por la inserción del resolver de diálogo en
  primera posición. El orden relativo de los 7 resolvers actuales no se toca.
- **ASUMIDO** — Rama git `feature/REQ-021-conversacion-multiturno`, creada desde `main` por Johan
  manualmente. Ningún agente ejecuta git.

---

## Decisiones de Johan sobre los 3 puntos abiertos (cerradas 2026-08-26)

### P1 — RESUELTO: el manos libres se usa en el **webview**. Entra la pieza 8.

Johan usa manos libres desde la app de escritorio (el toggle de wake word del webview), no desde la
consola de `main.py`. Confirmado el hallazgo: cero ocurrencias de `speak`/`tts`/`read_aloud` en todo
`ui/webview/`. **Dar voz a las respuestas del webview entra al alcance como pieza 8.**

Datos del motor TTS verificados (`ui/tts_engine.py`), para que la pieza 8 no se diseñe a ciegas:

- `speak()` (línea 81) es **bloqueante**: sintetiza con edge-tts vía `asyncio.run()` y reproduce el
  mp3 esperando a que termine. Invocarlo desde el hilo de Qt congelaría la ventana. La vía correcta
  es `run_async` (`ui/gui_workers.py:53`), que además entrega un `on_done` en el hilo de la GUI —
  justo el gancho que necesita la ventana de micrófono (CA-26).
- `is_speaking()` (18) lee la global `_speaking`; `signal_barge_in()` (22) ya existe; `_speak_lock`
  es un `threading.Lock` (14).
- La consola prepara el texto en `ui/cli.py:44-53`: aplana saltos de línea y, si pasa de 400
  caracteres, trunca al último punto antes de 380 y agrega "...La información completa está en su
  pantalla". La pieza 8 reusa **ese mismo criterio**.
- `_on_resolve_done` (`bridge.py:245`) emite HTML vía `render_markdown()`. A `speak()` hay que darle
  texto plano: ni el HTML ni el markdown crudo. `format_task_created()`
  (`tasks/task_manager.py:539`) devuelve markdown con asteriscos y emojis, y es exactamente la
  respuesta del caso de referencia.

**Decisión explícita sobre extraer vs. duplicar (pedida por el coordinador): se EXTRAE.** La
preparación de texto para voz queda en una única función, consumida por el webview y por la consola
(CA-27). Duplicarla garantiza drift entre las dos superficies —el mismo problema que la regla de
`orion-ui` señala entre `theme.py` y `theme.css`—, y aquí el síntoma sería que el agente suene
distinto según desde dónde se le hable. Casa doméstica recomendada: `ui/tts_engine.py`, porque ambos
consumidores ya dependen de él y mantiene "qué se pronuncia" en un solo sitio. Si `orion-architect`
prefiere alojar la mitad de markdown en `ui/webview/markdown_render.py`, es aceptable **siempre que
siga siendo una sola función llamada por los dos consumidores**.

### P3 — RESUELTO: se responde el desvío y se mantiene el diálogo vivo

Con un diálogo abierto, si llega otra cosa ("qué hora es"), el agente responde esa pregunta y
mantiene el diálogo pendiente para retomarlo. **Descartado explícitamente:** abandonar el diálogo al
cambiar de tema, e insistir con la repregunta ignorando lo que se preguntó (wizard rígido).
Ver CA-30, CA-31 y CA-32.

**Decisión sobre la expiración durante un desvío (pedida por el coordinador): el desvío NO reinicia
el contador** (CA-32). El TTL corre desde el último avance real del diálogo. Si el desvío lo
reiniciara, una charla larga podría mantener vivo un diálogo indefinidamente y hacer aparecer
"¿Para cuándo?" veinte minutos después de que Johan se olvidó del tema — exactamente la sorpresa que
la decisión de "descartar en silencio" quiere evitar. Con el contador fijo, el comportamiento es
predecible y testeable.

---

## Riesgo aceptado (P2) — el camino de voz del webview resuelve como `DESKTOP`

`_on_voice_command` (`ui/webview/bridge.py:704-715`) reusa `send_message()`, que resuelve con
`ChannelType.DESKTOP`, no `VOICE`. Es decir: la regla "canal VOICE solo permite acciones VERDES"
(`.claude/rules/security-levels.md`) **no se aplica** a las frases dictadas en el webview.

- **Es preexistente.** No lo introduce este REQ, y `task_create` es `GREEN`, así que el caso de
  referencia no se ve afectado.
- **Queda fuera de alcance en v1**, por decisión del coordinador. Corregirlo bloquearía por voz todas
  las acciones `YELLOW` que hoy funcionan en el webview: una regresión que Johan no pidió.
- **Pero este REQ agranda la superficie.** La ventana de ~15 s hace que entren por esa vía muchas más
  frases que antes, y sin wake word de por medio. El riesgo no cambia de naturaleza, cambia de
  volumen.
- **Acción:** que `orion-security` lo revise explícitamente cuando le toque, y que quede como
  candidato a REQ propio. CA-17, CA-18 y CA-19 acotan el daño desde el lado del diálogo, pero no
  cierran este hueco.

## Notas de diseño para `orion-architect`

- El mayor riesgo de regresión es `core/resolution.py`: es el punto único de resolución de los 4
  canales, y el resolver de diálogo va **primero**. CA-09 y CA-10 son el cinturón de seguridad.
- `_try_task_tool` no puede limitarse a "no disparar si la frase es corta". El criterio tiene que ser
  la ausencia del slot, consultada sobre la misma lógica que usa `parse_natural_task`, para que la
  detección y la creación nunca se contradigan.
- El guard `_resolution_in_flight` se libera en `_on_resolve_done` (`bridge.py:264`), antes de
  cualquier TTS. La ventana de micrófono debe abrir **después** de que termine la locución, no al
  liberar el guard — son dos momentos distintos, y con la pieza 8 la distancia entre ambos es de
  varios segundos.
- **Por qué CA-14 no puede resolverse sondeando `is_speaking()`:** en `_speak_edge`
  (`ui/tts_engine.py:27-38`), la global `_speaking` se pone en `True` **después** de que edge-tts
  terminó de sintetizar el mp3 (`await asyncio.wait_for(communicate.save(...), timeout=15)`), justo
  antes de reproducirlo. Entre la llamada a `speak()` y el inicio real de la reproducción hay una
  ventana de hasta 15 s en la que `is_speaking()` devuelve `False` y el agente está a punto de
  hablar. Un sondeo abriría el micrófono exactamente ahí. Encadenar al `on_done` de la tarea de voz
  (CA-26) evita el problema entero, sin tocar `tts_engine.py`.
- `speak()` usa `asyncio.run()` internamente, así que debe correr en un hilo sin loop de asyncio
  activo. El worker de `run_async` cumple esa condición; conviene no cambiarlo por un despacho que
  ya tenga loop propio.
