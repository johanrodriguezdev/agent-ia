# Auditoría QA REQ-009 — Control de modo manos libres (wake word) en la GUI JARVIS

## Alcance de la auditoría
Revisión directa de los 6 archivos modificados (`voice/wake_word.py`, `ui/gui.py`,
`ui/widgets/center_panel.py`, `ui/widgets/header_bar.py`, `ui/cli.py`, `main.py`), más
verificación independiente de compilación y suite de tests (no solo lectura de los reportes
de `orion-dev`/`orion-tester`).

## Verificación independiente
- `python -m py_compile` sobre los 6 archivos: **OK**, sin errores (re-ejecutado por QA).
- `pytest tests/ --tb=short -q`: **197 passed**, mismos 3 warnings pre-existentes (deprecation
  `aifc`/`audioop`, `PytestReturnNotNoneWarning` en `test_agents.py::test_ca1_orchestrator`).
  Coincide exactamente con lo reportado en `test-results-009.md`.
- `grep` de patrones `api[_-]?key|token|secret|password|sk-` sobre los 6 archivos: sin
  hallazgos.

## Seguridad

### Secretos
Sin hallazgos. No hay API keys, tokens ni contraseñas hardcodeadas en ninguno de los 6
archivos modificados.

### Acciones destructivas y confirmación
No aplica — este REQ no introduce ninguna acción destructiva (no borra archivos, no apaga el
sistema, no ejecuta comandos con `os.system()`/`subprocess`). El toggle solo enciende/apaga un
listener de audio pasivo y actualiza estado visual.

### Niveles de riesgo (verde/amarillo/rojo)
- **Verde (puede actuar sin preguntar):** encender/apagar la escucha pasiva del wake word desde
  el toggle de la GUI (`CenterPanel._on_wake_toggle_clicked` → `hands_free_toggled` →
  `JarvisMainWindow._on_hands_free_toggled`).
- **Amarillo:** ninguno introducido por este REQ.
- **Rojo:** ninguno introducido por este REQ.
- **Confirmaciones implementadas:** no aplica (nada Amarillo/Rojo en este REQ).

**Sobre la clasificación Verde propuesta por `orion-architect`:** confirmo el veredicto, con
una precisión. Verifiqué en código (no solo en la arquitectura) que la cadena de este REQ nunca
invoca `core/resolution.py:resolve()` — CA-04 lo exige explícitamente y `WakeWordWorker.run()` /
`listen_for_wake_word()` no importan ni llaman `resolve` en ningún camino; el ciclo termina en
"detectó la wake word, vuelve a escuchar". Por lo tanto el riesgo real es equivalente a "detectar
una palabra clave en audio ambiente", sin ejecución de ningún comando — consistente con el
espíritu de 🟢 Verde (no destructivo, sin efectos fuera de la UI).

Dicho esto, `.claude/rules/security-levels.md` **no lista explícitamente** "activar/desactivar
escucha pasiva de wake word" bajo 🟢 Verde hoy — la lista Verde actual cubre acciones análogas
(leer info del sistema, buscar archivos, clima, etc.) pero no menciona micrófono/audio en
absoluto, ni siquiera para la opción "3" preexistente del CLI que este REQ no crea, solo expone
en la GUI. Esto es una omisión preexistente al REQ-009 (la función ya existía sin clasificar
formalmente), no algo que este REQ haya empeorado. Recomiendo, como mejora de documentación (no
bloqueante para este REQ), agregar una línea explícita en `security-levels.md` bajo 🟢 Verde:
"Escuchar pasivamente la palabra de activación (wake word), sin ejecutar comandos". No lo trato
como motivo de rechazo porque (a) el comportamiento en código ya es consistente con Verde, (b) es
un REQ de categoría UI que no fue enrutado a `orion-security`, decisión que comparto dado el
análisis anterior, y (c) es un ajuste de un archivo de reglas, no de código funcional.

### Concurrencia — cancelación cooperativa del hilo de escucha
Revisé específicamente los tres riesgos de concurrencia señalados en el encargo:

1. **Race condition al togglear rápido (doble clic):** mitigado.
   `JarvisMainWindow._on_hands_free_toggled(True)` ignora el clic si `self._wake_worker is not
   None` (aunque ese worker ya esté deteniéndose), evitando dos `WakeWordWorker` compitiendo por
   `sr.Microphone()`. Cubierto por `test_double_click_toggle_does_not_start_two_workers`, que pasa.

2. **Memory leak de `QThreadPool`:** sin hallazgos. `WakeWordWorker(QRunnable)` no llama
   `setAutoDelete(False)`, por lo que usa el default `autoDelete=True` de Qt — `QThreadPool` libera
   el `QRunnable` automáticamente al terminar `run()`. No hay acumulación de workers: solo existe
   uno a la vez (por el guard de doble clic) y `_poll_state()` limpia la referencia Python
   (`self._wake_worker = None`) en cuanto observa `WAKE_STATE == "INACTIVE"`.

3. **Worker huérfano al cerrar la ventana:** `closeEvent()` minimiza a bandeja sin tocar el
   worker (comportamiento heredado de REQ-008/CA-13, intencional — el modo manos libres debe
   seguir corriendo en segundo plano al ocultar la ventana). El cierre *real* del proceso pasa por
   "Salir" del menú de bandeja → `QApplication.instance().quit()` → señal `aboutToQuit`, conectada
   a `_stop_wake_word_worker()` en `_setup_tray_icon()` (verificado en código, línea 212 de
   `ui/gui.py`) → pide `stop_event.set()` best-effort. Como el hilo de `QThreadPool` no es un
   `threading.Thread` de Python no-daemon, no bloquea la finalización del intérprete tras
   `sys.exit(app.exec())` aunque el hilo tarde unos segundos más en terminar — razonamiento
   correcto y consistente con lo documentado en `arquitectura-009.md`. Cubierto por
   `test_about_to_quit_signal_stops_active_worker`, que pasa.

**Observación no bloqueante (riesgo residual, recomendación de hardening):**
`WakeWordWorker` no llama `self.setAutoDelete(False)`, y `JarvisMainWindow` mantiene una
referencia Python de larga vida (`self._wake_worker`) para leer `.stop_event` — incluyendo desde
`_stop_wake_word_worker()`, invocable tanto por el toggle OFF como por `aboutToQuit`. Existe una
ventana teórica (hasta ~100ms, un ciclo de `_poll_state()`) entre el momento en que `run()`
termina naturalmente (parada cooperativa, excepción, o el camino `KeyboardInterrupt`/`result is
False`) y el momento en que `_poll_state()` limpia `self._wake_worker = None`, durante la cual
`QThreadPool` puede haber reclamado el `QRunnable` (autoDelete) mientras `JarvisMainWindow`
todavía lo referencia. En la práctica esto es de bajo riesgo real porque `QRunnable` (a diferencia
de `QObject`) no tiene el mecanismo de "wrapper invalidado" de PyQt que rompe el acceso a
atributos Python tras la destrucción C++, así que `self.stop_event.set()` sobre un runnable ya
finalizado muy probablemente sigue funcionando sin excepción. Pero es una suposición sin
verificación empírica: los 22 tests nuevos mockean `QThreadPool.globalInstance()` por completo
(confirmado en `tests/test_wake_word_gui.py`, línea 43), por lo que ningún test ejercita el ciclo
de vida real de `autoDelete`. Sugerencia (no bloqueante, puede resolverse en este mismo REQ si
Johan lo pide, o quedar como deuda técnica anotada): agregar `self.setAutoDelete(False)` en
`WakeWordWorker.__init__()`, ya que `JarvisMainWindow` es quien controla su ciclo de vida
completo de todas formas — elimina la ambigüedad sin cambiar ningún comportamiento observable.

## Niveles de riesgo
- Verde (puede actuar): encender/apagar la escucha pasiva del wake word desde el toggle de la GUI.
- Amarillo (debe confirmar): ninguno introducido por este REQ.
- Rojo (no ejecuta): ninguno introducido por este REQ.
- Se implementaron confirmaciones: no aplica (nada Amarillo/Rojo en este REQ).

## Logging

### Código nuevo de REQ-009
Sin `except: pass` silencioso. Verificado punto por punto:
- `voice/wake_word.py::_report_awake()` — envuelve la invocación del callback en
  `try/except Exception as e: logger.error(f"fallo en wake_state_callback: {e}")`. Nunca silencioso.
- `ui/gui.py::WakeWordWorker.run()` — envuelve el loop completo en
  `try/except Exception as e: logger.error(f"Error en WakeWordWorker (listen_for_wake_word): {e}")`,
  con `finally: update_wake_state("INACTIVE")` para no dejar el toggle trabado. Cubre CA-10.
  Verificado con `test_wake_word_worker_logs_error_and_resets_to_inactive` (usa `caplog`, pasa).
- Ninguna otra función nueva (`update_wake_state`, `_on_hands_free_toggled`,
  `_stop_wake_word_worker`, `CenterPanel.set_wake_state`, `HeaderBar.set_wake_state`,
  `CLI.__init__(gui_active=...)`) contiene manejo de excepciones silencioso — no lo requieren
  (no hacen I/O que pueda fallar).

### Deuda técnica preexistente (no atribuible a REQ-009, no bloqueante)
Confirmado en código: el patrón `except Exception: pass` sin logging que `orion-baseline` había
detectado en `voice/wake_word.py` **sigue presente**, en las líneas actuales:
- Líneas 97-98 (silenciar fallo al importar/usar `signal_barge_in()` en el chequeo de barge-in).
- Líneas 104-105 y 151-152 (silenciar fallo de `update_gui_state()` sobre el canal `GLOBAL_STATE`
  viejo, al entrar/salir de cada iteración del loop).

Confirmo que el **nuevo** canal `WAKE_STATE` no repite este patrón: las tres ubicaciones citadas
están todas dentro de las ramas `if wake_state_callback is None:` — es decir, solo se ejecutan en
el camino CLI/headless preexistente (`stop_event`/`wake_state_callback` no provistos), nunca en el
camino de la GUI (que siempre pasa `wake_state_callback=update_wake_state`, activando en cambio
`_report_awake()`, que sí loguea). Verificado leyendo el archivo completo, no solo el diff.

Este patrón preexistente queda anotado como deuda técnica no bloqueante para REQ-009, heredada del
código anterior a este REQ — consistente con lo que ya había señalado `orion-baseline`. No se pide
su corrección en este REQ.

Adicionalmente, de forma incidental (fuera del listado del encargo), se observó un
`except Exception: pass` similar y preexistente en `main.py` (~línea 173-174, guardado de embedding
semántico en memoria) — tampoco introducido ni tocado por REQ-009 (los cambios de `main.py` en
este REQ se limitan a la firma de `main()` y al closure de `gui_active` en `jarvis_runner()`). Se
menciona solo para que quede registrado como deuda técnica general del proyecto, no específica de
este REQ.

Las ramas `except sr.WaitTimeoutError: pass` / `except sr.UnknownValueError: pass` (líneas
127-130) no se consideran parte de este problema: son flujo de control esperado dentro de un loop
de polling de audio (timeout normal, sin voz reconocible), no errores que deban registrarse —
loguearlas en cada ciclo (cada ~1-7s mientras el modo está activo) sería ruido, no señal.

## Consistencia de código
- **Type hints:** presentes en todas las funciones/métodos nuevos
  (`listen_for_wake_word(stop_event: Optional[threading.Event] = None, wake_state_callback:
  Optional[Callable[[str], None]] = None)`, `_report_awake(wake_state_callback:
  Optional[Callable[[str], None]]) -> None`, `update_wake_state(new_state: str)`,
  `_on_hands_free_toggled(self, checked: bool) -> None`, `CLI.__init__(self, gui_active: bool =
  False)`, etc.). Consistente con el resto del código nuevo del proyecto.
- **Naming:** `snake_case` en funciones/variables (`_on_hands_free_toggled`,
  `_stop_wake_word_worker`, `wake_state_callback`), `PascalCase` en clases (`WakeWordWorker`),
  `UPPER_CASE` en la constante de módulo (`WAKE_STATE`). Sin violaciones.
- **Logging vs. `print()`:** el código nuevo usa exclusivamente el módulo `logging` (`logger =
  logging.getLogger(__name__)`, ya presente en ambos archivos). Los `print()` que aparecen en
  `voice/wake_word.py` (líneas 82, 118, 144) son preexistentes — mensajes informativos de consola
  para el operador del modo manos libres, no `print()` de debug agregados por este REQ.
- **Longitud de línea (máx. 100):** verificado con `git diff` restringido a líneas agregadas en
  los 6 archivos — ninguna línea nueva supera los 100 caracteres. (Sí existen líneas preexistentes
  que superan el límite en `ui/cli.py`, `header_bar.py` y `main.py`, pero ninguna fue tocada ni
  agregada por REQ-009 — fuera de alcance.)
- **Dead code / prints de debug:** ninguno encontrado en el código nuevo.
- **Imports:** orden estándar → third-party → locales respetado en los 6 archivos.

## Veredicto: ✅ APROBADO

Todos los puntos del DoD de `orion-qa` se verificaron directamente sobre el código (no solo
sobre los reportes de agentes previos): compilación, suite completa (197/197, re-ejecutada de
forma independiente), ausencia de secretos, clasificación de riesgo Verde razonada y confirmada,
ausencia de `except: pass` silencioso en el código nuevo, y convenciones de `python-style.md`
respetadas.

Se documentan dos observaciones **no bloqueantes**:
1. Deuda técnica preexistente confirmada en `voice/wake_word.py` (patrón `except Exception: pass`
   sin logging en el canal `GLOBAL_STATE` legado, ya señalada por `orion-baseline`) y una similar
   en `main.py`, ninguna introducida por este REQ.
2. Riesgo residual teórico y no verificado empíricamente en la interacción entre el ciclo de vida
   `autoDelete` de `QThreadPool`/`QRunnable` y la referencia Python de larga vida que
   `JarvisMainWindow` mantiene sobre `WakeWordWorker` — recomendación de hardening
   (`setAutoDelete(False)`), no un defecto confirmado.

Ninguna de las dos bloquea la aprobación: ambas son de bajo impacto, no afectan ningún criterio
de aceptación de SPEC-009, y quedan registradas para que Johan decida si las quiere resolver ahora
o dejarlas para un REQ/ajuste posterior.

---

## Ciclo 2 — Retorno tras prueba manual fallida y diagnóstico (2026-08-05)

### Alcance de esta actualización
Johan reportó que el modo manos libres "no lo escucha" en la prueba manual posterior a la
aprobación original. `orion-dev` investigó (descartó wiring/threading/wake-words mal
configuradas) y confirmó la causa raíz: el fallback local Whisper nunca se instaló, así que
cualquier fallo de `recognizer.recognize_google()` quedaba en silencio total, sin evidencia.
Agregó logging de diagnóstico dentro de `voice/wake_word.py::listen_for_wake_word()`.
`orion-tester` re-verificó 197/197 tests y 10/10 criterios en PASS. Esta sección re-audita
específicamente el cambio incremental de este ciclo — no repite la auditoría general del ciclo 1
(seguridad/arquitectura/convenciones), que sigue vigente.

### Verificación independiente (no solo lectura de reportes)
- Leí `desarrollo-log-009.md` sección "Ciclo 2" y `test-results-009.md` sección "Ciclo 2".
- `git status --porcelain`: confirmé que `voice/wake_word.py` es el único archivo de los 6 del
  REQ modificado *después* del resto — los otros 5 (`ui/gui.py`, `ui/widgets/center_panel.py`,
  `ui/widgets/header_bar.py`, `ui/cli.py`, `main.py`) tienen `mtime` entre 10:01 y 10:17;
  `voice/wake_word.py` tiene `mtime` 11:18, más de una hora después. No hay commits
  intermedios entre ciclo 1 y ciclo 2 (ningún agente ejecuta `git commit` en este pipeline), así
  que no pude usar `git diff` acotado a un rango de commits — usé el diferencial de `mtime` como
  evidencia independiente de que ningún otro archivo fue tocado en esta ventana, consistente con
  lo declarado por `orion-dev`/`orion-tester`.
- Leí el archivo completo `voice/wake_word.py` (191 líneas), no solo el fragmento citado en el
  log de desarrollo.
- `python -m py_compile voice/wake_word.py`: OK, re-ejecutado.
- `pytest tests/ --tb=short -q`: 197 passed, coincide con lo reportado.

### 1. Sin `except: pass` silencioso nuevo — verificado directamente sobre el código
Inventario completo de los bloques `except` del archivo actual (no solo los citados en el diff):
- Línea 110 `except sr.UnknownValueError:` → `logger.info(...)` explícito, luego fallback a
  Whisper. **Nuevo en este ciclo.** No es `pass`.
- Línea 120 `except sr.RequestError as e:` → `logger.warning(f"... ({e}); probando fallback
  local")` explícito, luego fallback a Whisper. **Nuevo en este ciclo.** No es `pass`.
- Línea 130 `if not text:` → `logger.info(...)` antes de `continue`. **Nuevo en este ciclo.** No
  es una rama `except`, pero es el mismo espíritu (no tragar el caso silenciosamente): confirmado
  que loguea antes de continuar el loop.
- Línea 152 (rama `else` de `if is_wake:`) → `logger.info(...)` con el texto reconocido.
  **Nuevo en este ciclo.**
- Líneas 97-98, 104-105, 163-166, 183-188: `except Exception: pass` / `except
  sr.WaitTimeoutError: pass` / `except sr.UnknownValueError: pass` — **todos preexistentes,
  sin diff**, ya señalados como deuda técnica no bloqueante en la auditoría del ciclo 1. Confirmé
  que ninguno fue ampliado, movido, ni recibió una rama nueva de código dentro de su bloque.

Conclusión: **confirmado independientemente** — los 4 puntos nuevos de este ciclo usan
`logger.info`/`logger.warning` explícito, ninguno es `except: pass`. Coincide con lo reportado
por `orion-dev` y re-verificado por `orion-tester`.

### 2. Nada tocado fuera del archivo declarado
Confirmado por `git status` + análisis de `mtime` (ver arriba). Los 5 archivos restantes del REQ
no tienen cambios posteriores al ciclo 1. Ningún archivo nuevo fue creado en este ciclo.

### 3. Privacidad del logging nuevo — hallazgo con nota, no bloqueante

Este es el punto que requiere análisis propio, no solo confirmar lo ya reportado.

**Qué se loguea ahora:**
- Metadatos de fallo (tipo de excepción, sin contenido de audio) en las líneas 110/120/130 — sin
  problema de privacidad, es equivalente a cualquier log de error de una llamada a API externa.
- **Línea 152-161: el texto transcripto completo** cuando Google Speech sí devuelve texto pero no
  matchea ninguna wake word configurada:
  ```python
  logger.info(
      f"[Wake word] Texto reconocido no coincide con ninguna wake word "
      f"configurada: '{text}'"
  )
  ```

**Por qué esto importa:** `listen_for_wake_word()` corre en modo de escucha pasiva continua
mientras el toggle está activo — `recognizer.listen(source, timeout=1, phrase_time_limit=6)` en
loop, capturando cualquier fragmento de audio de hasta 6s que supere el umbral de energía, no
solo audio dirigido al asistente. Cualquier frase dicha cerca del micrófono (por Johan o por
cualquier otra persona presente en el hogar) mientras el modo manos libres está activo y que no
contenga la wake word queda, desde este ciclo, escrita en texto plano en `logs/orion.log`. Antes
de este cambio esa transcripción se descartaba en memoria (`continue`) sin persistir en ningún
lado; ahora sí persiste en disco.

**Evaluación de severidad:**
- No es un secreto/credencial — no cae bajo la prohibición explícita de `security-levels.md`
  ("exponer API keys, tokens o credenciales").
- El log es **local** (`RotatingFileHandler`, `logs/orion.log`, 5MB × 3 backups ≈ 20MB máx.,
  verificado en `core/logger_setup.py`), sin transmisión de red ni a terceros — el único lector
  es el propio Johan en su propia máquina.
- El propósito de este ciclo es explícitamente que Johan revise ese archivo para diagnosticar el
  fallo de reconocimiento — es decir, la persistencia del texto transcripto es funcionalmente
  necesaria para el objetivo del ciclo, no un efecto colateral gratuito.
- El riesgo real es de **privacidad doméstica**, no de seguridad del sistema: conversación
  ambiental de cualquier persona en la casa (no solo Johan) puede terminar en texto plano en
  disco, sin que esas personas lo sepan, mientras el modo esté activo. Esto ya era cierto para el
  envío del audio a la API de Google Speech (comportamiento preexistente, no introducido por
  REQ-009 ni por este ciclo) — lo nuevo es específicamente la persistencia local del texto.

**Veredicto sobre este punto:** no amerita rechazo. Es un cambio de diagnóstico quirúrgico,
temporal en su propósito, solicitado explícitamente para resolver un fallo funcional bloqueante,
en una aplicación de escritorio personal de un solo usuario. Sí amerita una **nota de privacidad
explícita**, que agrego como observación no bloqueante (ver Veredicto), y una recomendación: una
vez que Johan confirme la causa raíz vía este logging, evaluar en un REQ de categoría VOZ si
conviene (a) bajar esa línea específica a nivel `DEBUG` en vez de `INFO` por defecto, o (b)
agregar una nota de retención/purga de logs, dado que ahora puede contener fragmentos de
conversación ambiental. No se implementa en este REQ — está fuera de su alcance (UI, no motor de
voz) y ya fue señalado como fuera de alcance por `orion-dev` en el mismo log.

### Consistencia de código (ciclo 2)
- Naming, type hints y estilo de los 4 puntos nuevos consistentes con el resto del archivo y con
  `python-style.md`. Ninguna línea nueva supera 100 caracteres (verificado por inspección directa
  de las líneas agregadas).
- Sin `print()` de debug nuevos.
- Sin dependencias nuevas.

### Veredicto (ciclo 2): ✅ APROBADO

Se confirma independientemente lo reportado por `orion-dev`/`orion-tester`: cambio acotado a
`voice/wake_word.py`, sin `except: pass` nuevo, sin secretos, sin control de flujo alterado.

Se agrega una observación **no bloqueante** nueva de este ciclo:
3. El logging nuevo persiste en `logs/orion.log` el texto completo transcripto por Google Speech
   cuando no matchea ninguna wake word — incluye potencialmente audio ambiental de cualquier
   persona en el hogar, no solo comandos dirigidos al asistente. Aceptable para este ciclo
   (diagnóstico solicitado explícitamente, log local sin transmisión a terceros), pero se
   recomienda evaluar en un REQ futuro de categoría VOZ si amerita nivel `DEBUG` o política de
   retención/purga.

Ninguna de las tres observaciones acumuladas (2 del ciclo 1 + 1 de este ciclo) bloquea la
aprobación.
