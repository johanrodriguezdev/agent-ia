# Auditoría QA — REQ-021 (Conversación multi-turno real)

**Fecha:** 2026-08-26
**Agente:** `orion-qa`
**Rama:** `feature/REQ-021-conversacion-multiturno`
**Entradas:** `SPEC-021.md`, `arquitectura-021.md`, `security-audit-021.md`,
`desarrollo-log-021.md` (vueltas 1 y 2), `test-results-021.md`, `REQ-021-context.md`.

**Alcance auditado:** los 12 archivos de producción del REQ (4 nuevos, 8 modificados) y sus
8 archivos de test. Los 49 archivos sin commitear ajenos al REQ (REQ-015/webview y otros)
quedan **explícitamente fuera** por instrucción del coordinador: no se auditan, no se
revierten y no se reportan. Ningún comando de git en modo escritura fue ejecutado.

**Verificación propia:** compilación 12/12 OK. Suite de los 6 archivos de test del REQ:
**150 passed en 7.85 s**. No se reejecutó la suite completa (ya verificada por el
coordinador: `2 failed, 693 passed`, los 2 pre-existentes de `anthropic` no instalado).

---

## Veredicto: ✅ COMPLETADO

Cero hallazgos bloqueantes. Cero secretos. Cero `except: pass` en código nuevo. Las 8
prohibiciones de la auditoría de seguridad se respetaron **todas**, verificadas una por una
contra el código real y no contra la declaración de `orion-dev`. El mecanismo de diálogo no
abre ninguna vía a YELLOW/RED.

Se registra **1 hallazgo 🟡 amarillo que NO es de este REQ pero que este REQ hace más
alcanzable**, y que merece REQ propio con prioridad alta (Q1), más 5 observaciones verdes.

---

## Seguridad

### Las 8 prohibiciones, una por una

| # | Prohibición | Estado | Evidencia en el código real |
|---|---|---|---|
| 1 | No debilitar el guard `_resolution_in_flight` | ✅ **RESPETADA** | Sigue intacto en `ui/webview/bridge.py:236` (`send_message`) y `:779` (`_on_voice_command`), con la misma condición y el mismo `return`. `_speak_response()` se llama DESPUÉS de `self._resolution_in_flight = False` (bridge.py:271-275) y la ventana se arma más tarde todavía, en el `on_done` de la locución: CA-15 se cumple por separación temporal, sin tocar el guard. |
| 2 | No leer el canal de `params` ni del texto | ✅ **RESPETADA** | `grep` sobre los 12 archivos: **cero lecturas**. Las 3 ocurrencias de `params["channel"]` (`resolution.py:307`, `:495`, `reasoning_loop.py:182`) son **escrituras incondicionales** pre-existentes que pisan lo que venga. `DialogStore._channel_value()` (dialog_state.py:77-84) solo lee el argumento del caller y lo documenta. `_execute_completed_dialog()` pasa `channel` como argumento posicional a `execute_tool()`, aparte del dict. |
| 3 | No mover el gate de `execute_tool()` | ✅ **RESPETADA** | `require_confirmation()` sigue en `agents/tool_registry.py:96-99`, dentro de `execute_tool()`, antes de `spec.invoke()`. **Ningún archivo del REQ añade una llamada nueva a `require_confirmation()`** (verificado con grep global). `scan_task_slots()` corre fuera del gate porque es pura: solo `re` + `_parse_natural_date()`, sin ejecutar, persistir ni consultar red. |
| 4 | `PendingDialog.action` sin setter | ✅ **RESPETADA — y endurecida** | `@dataclass(frozen=True)` (dialog_state.py:41). Es más fuerte que lo pedido: la arquitectura §4.1 lo dejaba mutable y `orion-dev` lo cerró estructuralmente. `fill()` y `touch_question()` usan `dataclasses.replace()`, que **nunca** toca `action`. Cero `object.__setattr__` en todo el REQ. |
| 5 | No persistir el diálogo en disco | ✅ **RESPETADA** | `core/dialog_state.py` no importa `json`, `pickle`, `sqlite3`, `shelve`, `os` ni `pathlib`. Estado en `Dict[Tuple[str,str], PendingDialog]` en memoria del proceso. Cero `open()` de archivo, cero `.write()`. |
| 6 | Sin hilo de fondo ni timer para la expiración | ✅ **RESPETADA** | `dialog_state.py` y `mic_window.py` usan `threading` **solo** para `RLock`/`Lock` (sincronización, no concurrencia). Cero `Thread(`, `Timer(`, `QTimer`, `sleep()`. La expiración se evalúa al leer: `DialogStore.get()` purga, `ConversationWindow.expired_now()` se consulta al principio del `while` ya existente (~1 Hz). Fijado por `tests/test_mic_window.py::test_no_hay_hilos_ni_timers`, que camina el **AST** de `mic_window.py` y prohíbe `Timer/Thread/wait/join/sleep`. |
| 7 | El post-hook no se cuelga de un `denied=True` | ✅ **RESPETADA** | `_append_pending_question()` (resolution.py) arranca literalmente con `if result.denied: return result`, **antes** de cualquier otra condición. El diálogo NO se cancela — la repregunta reaparece al turno siguiente. Cubierto por `test_h2_un_resultado_denegado_no_lleva_la_repregunta_colgada`. |
| 8 | `DialogStore.open()` rechaza `user_id` vacío | ✅ **RESPETADA** | `raise ValueError` con `user_id` falsy (dialog_state.py:98-102), más un segundo guard: `open()` también rechaza `action` vacía. Y `get()` retorna `None` con `user_id` falsy, así que no hay lectura de la clave `("", canal)` por ninguna vía. Cubierto por `test_h3_open_rechaza_user_id_vacio`. |

### Las 7 pruebas de seguridad obligatorias

7/7 presentes, localizadas y ejecutándose en verde:

1. Slot `que` + `"apaga el pc"` → se guarda como título, `dispatch` no se invoca (fixture `sin_dispatch`, que lanza `AssertionError` si corre).
2. Slot `cuando` + trigger YELLOW → `test_ca18_b_desvio_yellow_pasa_por_el_gate_con_el_canal_real`.
3. Acción RED con diálogo abierto → `test_ca18_b_desvio_red_sigue_bloqueado_por_el_fail_closed`.
4. Aislamiento entre usuarios y entre canales → `test_ca08_aislamiento_por_usuario_y_canal`, `test_ca08_aislamiento_entre_usuarios_del_mismo_canal`, `test_ca08_aislamiento_entre_canales_del_mismo_usuario`, `test_ca11_mismo_dialogo_en_los_3_canales`.
5. `open()` con `user_id` vacío lanza → `test_h3_open_rechaza_user_id_vacio`.
6. `denied=True` sin repregunta colgada → `test_h2_...`.
7. `matched_by` idéntico para los 7 resolvers con el store vacío → los 7 tests `test_ca09_*`.

Más `test_ca17_el_canal_llega_al_gate_desde_el_caller_no_del_dialogo`, que espía
`require_confirmation()` y asevera sobre el canal recibido.

### Secretos

**Sin hallazgos.** Cero API keys, tokens, contraseñas o credenciales en los 12 archivos.
Cero dependencias nuevas (`requirements.txt` intacto). Las coincidencias de "token" son
`_NON_CONTENT_TOKENS` / `_content_tokens()` de `task_slots.py`: tokens de texto, no de auth.

`ask_question()` revisado explícitamente. Manda al LLM: el nombre de la acción
(`"task_create"`), una descripción fija del slot, y los slots ya llenos — que son texto que
el usuario acaba de dictar. **No** manda `user_id`, **no** manda el canal, **no** manda
rutas, **no** manda el historial. En la primera repregunta (`slots={}`) el prompt no lleva
ni una palabra del usuario. Ver la observación Q2 sobre la vía de egreso nueva.

---

## Niveles de riesgo

- **🟢 Verde (puede actuar):** `task_create` — `RiskLevel.GREEN` en
  `agents/tool_registry.py:181`, registrado vía `register_tool()` → `register_action()`.
  Es la **única** acción alcanzable por el mecanismo de diálogo en v1.
- **🟡 Amarillo (debe confirmar):** ninguna alcanzable por diálogo. Una frase con trigger
  YELLOW durante un diálogo abierto o (a) se traga como texto del slot `que` y no se
  ejecuta (fail-safe), o (b) se desvía al camino normal y pasa por `require_confirmation()`
  con el canal real. En ningún caso el diálogo baja el nivel efectivo.
- **🔴 Rojo (no ejecuta):** ninguna alcanzable. El fail-closed de REQ-005 sigue operando sin
  cambios; el diálogo no toca `security_manager` en ninguna línea.

**Se implementaron confirmaciones: sí — sin cambios respecto de hoy, que es lo correcto.**
REQ-021 no añade ni quita un solo gate. El cierre estructural es
`_execute_completed_dialog()`, que rechaza **toda** acción distinta de `task_create`,
cancela el diálogo y deja que la frase siga el camino normal. Falla en sentido seguro: un
diálogo de otra acción no se improvisa, se descarta. Ejercido por 2 tests de la vuelta 2
(un diálogo con `action="shutdown_pc"` que asevera que `execute_tool` no se invoca y que
`dispatch()` nunca recibe `shutdown_pc`).

**Verificación del checklist de `.claude/rules/security-levels.md`:**
- [x] Toda acción destructiva tiene su nivel clasificado — sin cambios, ninguna nueva.
- [x] Las acciones Amarillo piden confirmación — el gate no se movió ni se debilitó.
- [x] Las acciones Rojo bloqueadas — fail-closed intacto.
- [x] Los logs registran las acciones sensibles — sin acciones sensibles nuevas.
- [x] Sin `os.system()`/`subprocess` sin validación — los 4 módulos nuevos no importan
      ninguno de los dos.

---

## Logging

**Sin hallazgos en código nuevo.** Cero `except: pass` y cero `except Exception: pass` en
los 4 módulos nuevos y en las secciones REQ-021 de los 8 modificados.

Los `except` del REQ registran todos su motivo:

- `dialog_questions.py:77` → `logger.warning(f"... el LLM no pudo redactar la repregunta ({e}); uso el respaldo")`.
- `dialog_questions.py:83` (respuesta inservible tras `_sanitize`) → `logger.info(...)`.
- `reasoning_loop.py:89` (`_load_prior_turns`) → `logger.warning(f"No se pudo leer el contexto previo de {agent_name}/{user_id}: {e}")`.

El punto que el coordinador pidió mirar con atención — `dialog_questions.py` envuelve todo
en `try/except Exception` y "nunca lanza" — está **correctamente resuelto**: las dos vías de
fallo (excepción del proveedor y respuesta basura) se registran con nivel distinto y
motivo, y las dos retornan la frase de respaldo, que es una frase natural, no un error. El
diseño "nunca lanza" no es "nunca dice nada".

Trazabilidad del diálogo: `open()` registra acción, slots faltantes, usuario y canal;
`get()` registra la expiración silenciosa; la cancelación por el usuario y el rechazo de
acción no cableada también quedan registrados. Ninguno de esos logs vuelca el **contenido**
de los slots.

---

## Consistencia de código

Contra `.claude/rules/python-style.md`, sobre los 4 archivos nuevos y las secciones nuevas
de los 8 modificados:

- **Longitud de línea ≤ 100:** ✅ 4/4 nuevos limpios. También limpios `core/resolution.py`,
  `core/reasoning_loop.py`, `ui/tts_engine.py`, `ui/cli.py`, `voice/wake_word.py`,
  `ui/webview/wake_word_worker.py`. Ver Q5.
- **Type hints:** ✅ completos en todas las funciones y métodos nuevos, incluidos los
  retornos (`-> Optional[PendingDialog]`, `-> SlotScan`, `-> bool`, `-> None`).
- **Docstrings:** ✅ todas las funciones públicas nuevas los tienen, en imperativo
  ("Return...", "Abrir...", "Quitar..."). Las privadas obvias los omiten correctamente.
- **Naming:** ✅ `snake_case` / `PascalCase` / `UPPER_CASE` respetados. Constantes
  (`DIALOG_TTL_SECONDS`, `MIC_WINDOW_SECONDS`, `SPEECH_TRUNCATE_THRESHOLD`,
  `SPEECH_TRUNCATE_AT`) cada una en **un solo lugar**, como pedía la condición 2 del H4.
- **Imports ordenados:** ✅ estándar → third-party → locales, con línea en blanco. Los
  imports diferidos dentro de función (`from tasks.task_slots import ...`) siguen el patrón
  ya establecido de `resolution.py` para romper ciclos, no son desorden.
- **Sin prints de debug:** ✅ cero `print()` en los 4 nuevos. Los `print()` de
  `wake_word.py` y `cli.py` son salida de consola pre-existente y deliberada.
- **Sin dead code:** ✅ las 2 vacuidades que había detectado `orion-tester` (el guard de
  `_execute_completed_dialog()` y los umbrales 400/380) están cerradas en la vuelta 2 y
  verificadas por mutación (8 mutaciones, 8 detectadas).
- **`__init__.py` sin lógica:** ✅ ninguno tocado.
- **Una clase principal por archivo:** ✅ `DialogStore` + `PendingDialog` (auxiliar
  pequeño), `ConversationWindow`, `SlotScan`.

### Las 10 desviaciones de `orion-dev`, desde seguridad y convenciones

Confirmadas como razonables. **Ninguna tiene impacto negativo de seguridad; tres son
endurecimientos netos:**

- **#1 (`frozen=True`)** — endurecimiento. Convierte la prohibición 4 y CA-19 de disciplina
  a garantía estructural. Es la desviación más valiosa del REQ.
- **#6 (cancelación por coincidencia exacta)** — endurecimiento funcional. Con `in`,
  "cancela la reunión del lunes" habría cancelado el diálogo en vez de ser el título.
- **#9 (`_execute_completed_dialog()` rechaza toda acción ≠ `task_create`)** —
  endurecimiento. Es lo que cierra estructuralmente la vía a YELLOW/RED en v1.
- **#2 (par de contadores `_speech_seq`/`_speech_done_seq`)** — neutra en seguridad,
  mejor en convenciones: evita closures capturando estado entre hilos, que era el patrón
  más frágil disponible.
- **#3 (`expired_now()` al principio del `while`)** — corrige un defecto real de la
  arquitectura: varias ramas salen por `continue` y la línea al final no se habría
  ejecutado justo en el caso frecuente.
- **#4, #5, #7, #8** — cosméticas o de correctitud de parseo, sin superficie de seguridad.
  #5 (`has_content_tokens()` exportada) evita una segunda definición de "contenido", que es
  exactamente el drift que el REQ intenta prevenir en otros lados.
- **#10 (`_load_prior_turns()` valida `list` de `dict`)** — endurecimiento menor contra una
  fila corrupta en `agent_context.db`. Correcto.
- **Vuelta 2, fixture `spy_dispatch`** — correcta y necesaria. Pero el motivo por el que
  hizo falta es un hallazgo del sistema por derecho propio: ver **Q1**.

---

## Hallazgos

### 🔴 Rojo — bloqueantes

**Ninguno.**

### 🟡 Q1 — El clasificador de intents no tiene umbral de confianza ni salida a UNKNOWN

**No lo causa REQ-021. No bloquea este REQ. Merece REQ propio con prioridad alta.**

`orion-dev` reportó que tuvo que espiar `dispatch()` porque el clasificador manda
`"mañana a las 9"` a `FIND_LARGEST` con `path="~"`, que recorre el disco entero. **Lo
reproduje y es peor que lo reportado.** Ejecutando `classify_command()` sobre frases sueltas
de fecha y de contenido de recordatorio:

| Frase | Intent asignado | Params | Nivel | Consecuencia real |
|---|---|---|---|---|
| `"mañana a las 9"` | `FIND_LARGEST` | `path="~"` | 🟢 GREEN | `rglob("*")` + `stat()` sobre **todo el perfil de usuario**. Minutos de I/O al 100 %, sin confirmación. |
| `"en 2 horas"` | `PC_CLICK` | `{}` | 🟢 GREEN | Clic sintético en la ventana que tenga el foco. Sin confirmación. |
| `"el viernes"` | `CLOSE_APP` | `app_name="el viernes"` | 🟡 YELLOW | Pide confirmación (correcto), pero es un prompt espurio desde una frase inocua. |
| `"a las 8 de la noche"` | `RAM_INFO` | `{}` | 🟢 GREEN | Inocuo. |
| `"llamar al contador"`, `"comprar pan"`, `"pasado mañana"` | `CALCULATE` | `{}` | 🟢 GREEN | Inocuo. |

**Causa raíz:** `intent/ai_classifier.py::predict()` es
`self.pipeline.predict([clean])[0]` a secas. `LinearSVC` **siempre** devuelve la clase más
cercana; no hay `decision_function`, no hay `predict_proba`, no hay umbral, no hay ruta a
`UNKNOWN`. Verificado por grep: cero ocurrencias de `threshold` / `confidence` /
`decision_function` en todo `intent/`.

**Qué cambia REQ-021 aquí, con precisión:**

- **Lo mejora dentro del diálogo.** `_try_pending_dialog` va PRIMERO en `RESOLVERS`, así que
  con un diálogo abierto `"mañana a las 9"` se lee como el slot `cuando` y **nunca llega**
  a `_try_intent`. Es una mejora real y medible sobre el estado de hoy.
- **Lo empeora fuera del diálogo.** La ventana de micrófono de ~15 s por turno aumenta el
  volumen de frases sueltas —conversación ambiente, televisión, alguien más en la sala— que
  entran a `resolve()` sin wake word y caen hasta `_try_intent`, donde siempre se les asigna
  algún intent.

**Por qué esto reclasifica el hallazgo H4 de la auditoría de seguridad.** H4 concluyó que la
ventana "no cambia QUÉ puede ejecutarse, solo cuántas veces se intenta", y describió el
peor caso GREEN como "abrir app, buscar, decir la hora" — benigno. Con Q1 medido, el peor
caso GREEN real es **una denegación de servicio sobre la propia máquina de Johan** (barrido
recursivo del perfil completo) o **la inyección de un clic sintético**. El veredicto de H4
("sigue siendo aceptable en v1") **se sostiene** —ninguna acción destructiva pasa sin
confirmación, y la mitigación de `consume()` está implementada y probada—, pero su
fundamento hay que corregirlo: el suelo GREEN no es tan benigno como se asumió.

**Recomendación:** REQ propio, fusionado con la deuda P2 que la condición 3 del H4 ya pedía
convertir en REQ. Ámbito sugerido: (a) umbral de confianza en `predict()` con caída a
`UNKNOWN` cuando el margen sea bajo — es lo que convierte "siempre acierta algo" en "sabe
que no sabe"; (b) resolver `_on_voice_command` como `VOICE` (deuda P2), revisando a la vez
qué acciones amarillas se quieren permitir por voz; (c) acotar el `path` por defecto de
`FIND_LARGEST` / `FOLDER_SIZE`, o clasificarlas YELLOW cuando el path no sea explícito.

### 🟢 Q2 — `ask_question()` abre una vía de egreso nueva para el contenido del recordatorio

Antes de REQ-021, `"recuérdame X"` **nunca llegaba al LLM**: `_try_task_tool` lo capturaba
por keyword y ejecutaba `task_create` directo (es el hallazgo #2 del diagnóstico previo del
propio REQ). Ahora, cuando falta un slot, el contenido ya dictado viaja al proveedor LLM
configurado dentro del prompt de `ask_question()`.

Es **consecuencia directa e inevitable del motor híbrido que Johan aprobó** ("el LLM redacta
la repregunta"), el proveedor es el mismo que ya ve todo el chat, y el volumen es mínimo
(solo los slots llenos; en la primera repregunta, nada). No es un defecto y no requiere
acción en v1. Se registra porque nadie lo había dicho con estas palabras y la auditoría de
seguridad concluyó "sin cambio en la superficie de exposición", que es cierto a nivel de
proveedor pero no a nivel de *qué contenido* sale.

Mitigación futura casi gratis, si alguna vez importa: `fallback_question()` ya existe, ya es
completamente funcional y produce preguntas naturales sin LLM. Un flag de configuración
bastaría para el modo sin egreso.

### 🟢 Q3 — El log registra la frase transcrita completa aceptada sin wake word

`voice/wake_word.py:224` → `logger.info(f"[Ventana] frase aceptada sin wake word: {text!r}")`.
Con el micrófono aceptando una frase por ventana durante ~15 s por turno, el log puede
capturar conversación ambiente que no iba dirigida al agente. `resolve()` ya registra los
primeros 80 caracteres de todo (pre-existente), así que no es un patrón nuevo. Sin acción en
v1; a considerar bajar a `DEBUG` si el log se comparte alguna vez.

### 🟢 Q4 — `except Exception: pass` en el bloque de barge-in — PRE-EXISTENTE

`voice/wake_word.py`, el `try` alrededor de `is_speaking()` / `signal_barge_in()`.
**Verificado con `git show HEAD:./voice/wake_word.py`: existe en HEAD, líneas 97-98.
REQ-021 no lo introduce ni lo toca.** Se registra solo porque cae en un archivo del REQ y
porque los tests de CA-29 de la vuelta 2 lo cubren por primera vez. Recomendación para un
REQ futuro: `logger.debug(f"...: {e}")` en vez de `pass`.

### 🟢 Q5 — Dos líneas > 100 chars en `tasks/task_manager.py` — move puro

`TASK_DATE_PATTERNS` líneas 244-245 (112 y 107 chars). Verificado contra
`git show HEAD`: contenido **idéntico**, estaban en las líneas 251-252 con más indentación.
Es el "move puro" que la arquitectura pidió. No es código nuevo y no se corrige acá:
reformatearlas rompería la garantía de move puro que `tests/test_task_slots.py` fija.

### 🟢 Q6 — `except (PermissionError, OSError): pass` en `filesystem_actions.py`

`system_actions/filesystem_actions.py:122-125`, dos ocurrencias. Pre-existente, fuera del
alcance de REQ-021. Se anota porque es la misma función (`find_largest_folders`) del
hallazgo Q1 y debería revisarse en ese REQ.

---

## Lo que este REQ hace bien y conviene dejar registrado

- **La detección de slots es una función pura y está fuera del gate a propósito**, con el
  motivo documentado en el propio código. Es la razón por la que el gate no tuvo que moverse.
- **El doble candado de CA-14** (la ventana solo se arma en el `on_done` del TTS, y un chunk
  que empezó antes de `opened_at` se rechaza aunque termine después) es la mitigación
  correcta del riesgo más alto del REQ, y no depende de sondear `is_speaking()`, que era la
  trampa que `orion-spec` había detectado.
- **`consume()` está implementado de verdad** — una frase por ventana. Era la condición 1 del
  H4 de la auditoría y es lo que impide que un ruido continuo encadene ejecuciones.
- **Los tres valores ajustables viven cada uno en un solo lugar** (`DIALOG_TTL_SECONDS`,
  `MIC_WINDOW_SECONDS`, `SPEECH_TRUNCATE_THRESHOLD` / `_AT`), con test que lo fija. Bajar la
  ventana tras la prueba en vivo cuesta una línea.
- **La divergencia de las dos listas de triggers se documentó con el motivo del costo de
  error opuesto y se fijó con un test de subconjunto**, en vez de unificarlas y cambiar el
  comportamiento de frases que hoy caen en `claude`.

---

## Riesgos que sobreviven a QA y solo cierra la prueba manual

Ninguno bloquea el commit; los tres son de acústica y cronometraje real, que ningún test
unitario puede ejercer:

1. **[ALTO] El agente escuchándose a sí mismo (R1).** El doble candado está probado en
   unidad, pero el cruce real de los 3 hilos + la latencia del altavoz + la acústica de la
   sala no. **Primero a mirar en vivo, con y sin auriculares.**
2. **[MEDIO] Los ~15 s pueden quedar largos o cortos.** Valor de partida sin medir.
3. **[MEDIO] CA-16** — único criterio de los 32 que no tiene cobertura posible en unidad.

---

## Veredicto: ✅ COMPLETADO

Aprobado para prueba manual de Johan. **No se ejecutó `git commit`, `add`, `push`,
`checkout`, `branch` ni `restore`.** El mensaje de commit se entrega solo después del OK
humano, según `.claude/rules/git.md`.
