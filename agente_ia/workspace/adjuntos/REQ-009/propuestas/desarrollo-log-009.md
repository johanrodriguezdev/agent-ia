# Desarrollo REQ-009

## Archivos modificados
- `agente_ia/voice/wake_word.py`
- `agente_ia/ui/gui.py`
- `agente_ia/ui/widgets/center_panel.py`
- `agente_ia/ui/widgets/header_bar.py`
- `agente_ia/ui/cli.py`
- `agente_ia/main.py`

## Dependencias agregadas
Ninguna. Solo se usó lo ya presente en `requirements.txt` (`PyQt6`, `threading` de stdlib).

## Decisiones de implementación

Implementación exactamente según `arquitectura-009.md`, sin desviaciones de diseño. Un par de
detalles menores de "cableado" que la arquitectura dejaba abiertos a criterio de `orion-dev`:

- **Reporte de `"LISTENING_WAKE"`**: la arquitectura describe que `WakeWordWorker.run()` llama
  `update_wake_state("LISTENING_WAKE")` *antes* de invocar `listen_for_wake_word()` (CA-03), y que
  al re-entrar tras detectar la wake word "reporta LISTENING_WAKE de nuevo" (CA-04). Se implementó
  como un `while not self.stop_event.is_set():` en `WakeWordWorker.run()` que llama
  `update_wake_state("LISTENING_WAKE")` al tope de cada iteración, antes de cada llamada a
  `listen_for_wake_word()`. `voice/wake_word.py` solo usa `wake_state_callback` para reportar
  `"AWAKE"` (nunca `"LISTENING_WAKE"`, que es responsabilidad exclusiva del worker) — evita que dos
  lugares reporten el mismo estado y mantiene `voice/wake_word.py` con la menor superficie nueva
  posible, tal como pedía la arquitectura.
- **`_report_awake()` helper**: se extrajo una función privada `_report_awake(wake_state_callback)`
  en `voice/wake_word.py` para no triplicar el `try/except Exception as e: logger.error(...)` que
  exige CA-04/riesgos ("cada invocación del callback se envuelve en su propio try/except") en los 3
  puntos donde se detecta la wake word (con comando extraído, sin comando en el camino principal, y
  en el camino de fallback de `sr.RequestError`). Se llama `_report_awake()` también cuando hay
  `extracted_cmd` (no solo en el camino "Lo escucho, Señor"): CA-04 exige que el indicador pase a
  "despierto" en cualquier detección de wake word, no solo cuando no hay comando extra.
- **`result is False` en `WakeWordWorker.run()`**: además de `result is None` (parada cooperativa),
  se sale del loop si `listen_for_wake_word()` retorna `False` (camino de `KeyboardInterrupt`,
  improbable en un hilo de `QThreadPool` pero mantenido por simetría/robustez) — evita que el
  worker quede en un loop sin salida si esa rama se disparara alguna vez.
- **QSS/tooltips de los 3 estados visuales**: la arquitectura no especificaba textos ni colores
  concretos para el toggle/indicador — se usaron íconos (🎙/🎙/🟢) y tooltips descriptivos
  ("Modo manos libres: inactivo/escuchando wake word/despierto"), con la propiedad Qt `wakeState`
  ya prevista por la arquitectura para permitir estilizado por estado vía QSS. No es una decisión
  de negocio, es detalle visual dentro del margen normal de implementación.

Sin ningún otro ajuste respecto a lo aprobado. No se tocó ningún camino existente del CLI/headless
más allá de lo estrictamente necesario para CA-06/CA-07 (parámetro `gui_active`, default `False`).
No se tocaron los `except Exception: pass` preexistentes de `voice/wake_word.py`
(líneas de barge-in y `_get_whisper`/`_transcribe_whisper`) — fuera de alcance de este REQ, tal
como anotó `orion-baseline`.

## Verificación local
- `python -m py_compile` de los 6 archivos: OK, sin errores.
- `pytest tests/ --tb=short -q`: **175 passed**, mismos 3 warnings pre-existentes que
  `baseline-009.md` (aifc/audioop deprecation + `PytestReturnNotNoneWarning` en
  `test_agents.py::test_ca1_orchestrator`) — sin regresiones. No se agregaron tests nuevos en este
  paso (corresponde a `orion-tester`, según el DoD de este REQ y la cobertura ya prevista en
  `arquitectura-009.md`, sección "Pruebas sugeridas").

## Checklist DoD `orion-dev`
- [x] Solo se implementó lo aprobado en arquitectura-009.md
- [x] Sin API keys/tokens hardcodeados
- [x] Sin `except: pass` silencioso en código nuevo (todo `except Exception as e: logger.error(...)`)
- [x] Sin prints de debug nuevos (los `print()` existentes en `voice/wake_word.py` son
      pre-existentes, consola informativa del modo manos libres, no debug)
- [x] Sin dependencias nuevas — `requirements.txt` sin cambios
- [x] `voice/wake_word.py`/`ui/gui.py` no son skills — no aplica herencia de `BaseSkill`
- [x] Banner mostrado antes de escribir código
- [x] `desarrollo-log-009.md` generado (este archivo)
- [x] NO se ejecutó `git commit`
- [x] Mensaje de commit sugerido entregado (ver handoff)

---

## Ciclo 2 — Retorno desde prueba manual del humano (2026-08-05)

### Reporte de Johan (verbatim, relayado por la sesión orquestadora)
> "Probe lo manos libres activando el audio pero no me escucha"

Diagnóstico previo ya reunido (relayado, no re-preguntado): el ícono/indicador SÍ pasó a
"escuchando" (`LISTENING_WAKE`) al activar el toggle — sin excepción silenciosa, sin
traceback en consola — y se quedó ahí. El modo manos libres por CLI (opción 3, pre-REQ-009)
había funcionado antes en esta máquina diciendo "Orion".

### Investigación (orden de la tarea, documentando qué se descartó y por qué)

**1. ¿Wiring/threading nuevo de REQ-009?** DESCARTADO como causa. Se releyó
`ui/gui.py::WakeWordWorker.run()`/`JarvisMainWindow._on_hands_free_toggled`/`_poll_state()`
completos y `voice/wake_word.py::listen_for_wake_word()` completo. La lógica de captura
(`with sr.Microphone() as source: recognizer.adjust_for_ambient_noise(...);
recognizer.listen(...); recognizer.recognize_google(...)`) es exactamente la misma que
usaba el camino CLI antes de REQ-009 — solo se le agregaron los parámetros opcionales
`stop_event`/`wake_state_callback`, ambos ya cubiertos por los 22 tests de `orion-tester`
(CA-07 verifica bit-a-bit que sin ellos el comportamiento no cambia). Correr esa misma
lógica dentro de un `QRunnable` de `QThreadPool.globalInstance()` en vez del hilo daemon
`jarvis_runner` no introduce ningún problema conocido de PyAudio/`sr.Microphone()` en
Windows para este caso (no se usa WASAPI loopback ni ninguna API que exija
`CoInitialize` explícito en el hilo que abre el stream; `PyAudio`/`portaudio` con el host
API por defecto (MME/DirectSound) no requiere el mismo hilo que lo abrió). El hecho de que
el ícono llegara a "escuchando" y **se quedara ahí sin revertir a "inactivo"** confirma que
no hubo excepción en el `with sr.Microphone()` ni en `adjust_for_ambient_noise()` — si la
hubiera habido, `WakeWordWorker.run()` la captura y el `finally` fuerza
`update_wake_state("INACTIVE")` (ver arquitectura-009.md, CA-10), lo cual habría revertido
el ícono. Johan confirmó que no revirtió. Conclusión: el hilo worker entró correctamente al
loop interno de `listen_for_wake_word()` y quedó escuchando con normalidad.

**2. ¿Las wake words configuradas incluyen "nodo"?** DESCARTADO como causa. Se ejecutó
`config_manager.get_wake_words()` con la config real del proceso
(`agent_name="Noddoo"`, `agent_pronunciation="Nodo"`) y se confirmó que la lista generada
incluye `"nodo"` como entrada exacta (además de `"hey nodo"`, `"oye nodo"`, `"hola nodo"`,
`"despierta nodo"`, `"hey nodo despierta"`, y las mismas variantes con `"noddoo"`). Se
probó `voice/wake_word.py::parse_wake_command()` con `clean_text()` de por medio contra
`"Nodo"`, `"nodo"`, `"Nodo."`, `"Hola Nodo"`, `"nodo,"` — todos matchean correctamente
(`is_wake=True`). `clean_text()` no destruye "nodo" (no tiene acentos que remover, y no hay
ninguna lista de stopwords que lo filtre). Conclusión: si Google Speech transcribe
literalmente "nodo", el matching funciona sin problema.

**3. ¿Problema de sensibilidad/reconocimiento, no de código?** CONFIRMADO como la causa
raíz más probable — y se encontró un **hallazgo separado y más grave** en el camino: no es
solo que "Nodo" sea una palabra corta difícil de reconocer, es que **cualquier fallo de
`recognizer.recognize_google()` (con o sin relación a "nodo") queda completamente silencioso
y sin ningún rastro**, porque el fallback local (`_transcribe_whisper()`, paquete `whisper`)
**no está instalado** (`openai-whisper` está comentado en `requirements.txt`, se confirmó
`import whisper` → `ModuleNotFoundError` en este entorno). El código (sin cambios de
comportamiento desde antes de REQ-009) hacía:
```python
except (sr.RequestError, sr.UnknownValueError):
    text = _transcribe_whisper(audio)   # siempre "" si whisper no está instalado
if not text:
    continue   # silencio total, ningún log, ningún error visible
```
Esto significa que **tanto** (a) Google no pudo transcribir el audio (`UnknownValueError` —
plausible con "Nodo", palabra corta de 2 sílabas, vs. "Orion" que Johan probó con éxito
antes) **como** (b) un fallo de red/cuota con la API de Google (`RequestError`) producen
exactamente el mismo síntoma que reportó Johan: el ícono se queda en "escuchando"
indefinidamente, sin ningún error en consola ni en los logs. No hay forma de distinguir
estas dos causas con el código anterior — este es el hallazgo que bloqueaba el diagnóstico
final.

### Cambio aplicado (diagnóstico mínimo, no rediseño)
Se agregó logging de diagnóstico en `voice/wake_word.py::listen_for_wake_word()`, sin tocar
el control de flujo existente (mismos `continue`, mismo fallback a Whisper, mismos
retornos):
- Se separó el `except (sr.RequestError, sr.UnknownValueError):` único en dos `except`
  distintos, cada uno con su propio `logger.info()`/`logger.warning()`, para poder
  diferenciar en el próximo log "Google no entendió el audio" de "falló la conexión con la
  API de Google".
- Cuando ningún motor devuelve texto (`if not text:`), se agregó `logger.info()` indicando
  que ni Google ni el fallback local produjeron texto en ese ciclo.
- Cuando sí hay texto pero no matchea ninguna wake word (`else` del `if is_wake:`), se
  agregó `logger.info()` con el texto transcripto real — esta es la evidencia clave
  pendiente para la próxima prueba de Johan.

Los tres `logger.info()`/`logger.warning()` corren al nivel por defecto (`INFO`,
`core/logger_setup.py`), así que quedan tanto en consola como en `logs/orion.log`
(`RotatingFileHandler`) — visibles aunque la GUI no tenga consola adjunta.

### Veredicto y siguiente paso
No se encontró ningún bug de wiring/threading introducido por REQ-009 (puntos 1 y 2
descartados con evidencia). El síntoma reportado por Johan es consistente con una
**limitación preexistente al rename "Orion"→"Nodo"** (hecho fuera de este pipeline, en otra
sesión): "Nodo" es una palabra corta y `whisper` (fallback local) nunca se instaló, así que
cualquier fallo de reconocimiento de Google Speech —sea por la palabra en sí o por
red/cuota— es indistinguible de silencio total. **No se tapó con un cambio grande fuera de
alcance** — se agregó solo el logging mínimo necesario para confirmarlo empíricamente en la
próxima prueba manual.

**Recomendación explícita**: si la próxima prueba de Johan confirma vía
`logs/orion.log`/consola que Google transcribe "Nodo" como otra palabra (o que
`RequestError` se dispara), esto amerita **un REQ nuevo** (categoría VOZ) para atacarlo de
raíz — opciones a evaluar en ese REQ: instalar `openai-whisper` como fallback real,
ajustar `energy_threshold`/`dynamic_energy_threshold`, o agregar wake words alternativas
más largas/distintivas (p. ej. "hey nodo" en vez de solo "nodo", ya soportado hoy por
`get_wake_words()` pero no necesariamente lo que Johan dijo en la prueba). No corresponde
resolverlo dentro de REQ-009, cuyo alcance es el control de GUI, no el motor de
reconocimiento de voz.

### Verificación local (ciclo 2)
- `python -m py_compile voice/wake_word.py`: OK.
- `pytest tests/ --tb=short -q`: **197 passed**, mismos 3 warnings pre-existentes, sin
  regresiones (incluye los 19 tests específicos de wake word:
  `tests/test_wake_word.py` + `tests/test_wake_word_gui.py`, todos PASS sin modificación —
  el cambio es aditivo y no altera ninguna rama de retorno cubierta por esos tests).

### Checklist DoD `orion-dev` (ciclo 2)
- [x] Solo se tocó lo mínimo para el hallazgo de diagnóstico (logging), nada fuera de lo
      pedido en el handoff de retorno
- [x] Sin API keys/tokens hardcodeados
- [x] Sin `except: pass` silencioso (los 2 `except` nuevos tienen `logger.info`/`logger.warning`)
- [x] Sin prints de debug nuevos
- [x] Sin dependencias nuevas — `requirements.txt` sin cambios (no se instaló `whisper`,
      queda como recomendación para un REQ nuevo, no ejecutado acá)
- [x] Banner mostrado antes de escribir código
- [x] `desarrollo-log-009.md` actualizado (esta sección)
- [x] NO se ejecutó `git commit`
- [x] Mensaje de commit sugerido entregado (ver handoff)
