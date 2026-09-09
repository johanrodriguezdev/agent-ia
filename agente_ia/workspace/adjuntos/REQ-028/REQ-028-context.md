# Contexto REQ-028 — El manos libres muere cuando otra app toma el micrófono

## Resumen ejecutivo
El modo manos libres no se degrada ante un micrófono ocupado: se **muere**. Un `OSError` de
PyAudio (otra app toma el dispositivo, cambia el default de Windows) no está contemplado en
el bucle de escucha, propaga, cierra el micrófono y termina el worker. El toggle vuelve a
`INACTIVE` sin un solo aviso al usuario y no se recupera solo ni cuando el micrófono queda
libre. Objetivo: reconexión automática + aviso visible.

## Estado actual
- **Estado tracker:** ARQUITECTURA_APROBADA
- **Último agente:** conversación principal (spec + arquitectura por autorización) → siguiente: `orion-dev`
- **Fecha última actualización:** 2026-09-08
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo` (REQ-027 y el fix de ventana ya commiteados y pusheados)
- **Categoría:** VOZ
- **Tipo de cambio:** BUG_FIX

## Origen del REQ
Reporte de Johan (2026-09-08): *"cuando estuve en una reunión el agente dejó de escucharme
de pronto porque había otra app ocupando el micrófono"*.

Diagnóstico y reproducción hechos en la conversación principal antes de crear el REQ (ver
`origen/reproduccion-mic-ocupado.py`). El fallo está confirmado, no es una hipótesis.

## Hallazgos técnicos (evidencia para spec y arquitectura)

### La cadena exacta del fallo
1. `voice/wake_word.py:315` — `with sr.Microphone() as source:` abre el dispositivo **una
   sola vez, fuera del `while True`**. Ese stream tiene que sobrevivir toda la sesión de
   manos libres.
2. `voice/wake_word.py:460-476` — los `except` del bucle cubren `sr.WaitTimeoutError`,
   `sr.UnknownValueError`, `sr.RequestError` y `KeyboardInterrupt`. **No hay `except
   OSError`**, que es lo que lanza PyAudio cuando pierde el dispositivo
   (`-9988 Stream closed`, `-9999 Unanticipated host error`).
3. La excepción sale del `with` → el micrófono se cierra → llega a
   `ui/webview/wake_word_worker.py:76-83`, que la loguea con `logger.error` y **termina
   `run()`**. El `finally` reporta `update_wake_state("INACTIVE")`.
4. `ui/webview/frontend/js/composer.js:110-121` — `setWakeState()` solo cambia el `title` y
   el `aria-label` del botón. **Sin toast, sin aviso, sin nada**: el manos libres se apaga
   en silencio.

### Medición de la reproducción
```
== llamada directa a listen_for_wake_word() ==
   [mic] stream abierto
   [mic] stream CERRADO (sale del with)
   -> PROPAGA la excepcion: OSError: [Errno -9988] Stream closed

== el worker de la GUI ==
Error en WakeWordWorker (listen_for_wake_word): [Errno -9988] Stream closed
   estados reportados a la interfaz: ['LISTENING_WAKE', 'INACTIVE']
   veces que se intento escuchar: 2
```
**Cero reintentos.** Un error y se acabó hasta que el humano vuelva a apretar el botón.

### Segundo modo de fallo (mismo origen, sin excepción)
`sr.Microphone()` sin `device_index` se ata al dispositivo **por defecto del momento en que
abre**. Si al entrar a una reunión se conectan auriculares y Windows cambia el default, el
agente sigue leyendo el micrófono viejo. No hay error, pero tampoco escucha lo que el
usuario cree que está diciéndole. A confirmar por spec si entra en el alcance.

## Decisiones tomadas
<!-- FECHA | AGENTE | DECISIÓN | MOTIVO -->
2026-09-08 | coordinación | Categoría VOZ | Toca `voice/wake_word.py` y el worker de wake word; el síntoma es de captura de audio, no de UI
2026-09-08 | coordinación | Tipo BUG_FIX | El manos libres ya existe y promete escuchar; deja de cumplirlo ante una condición normal (una reunión)
2026-09-08 | coordinación | REQ propio en vez de parche al paso | `voice/wake_word.py` está marcado "prohibido tocar" en el diseño de REQ-015 (ver `ui/webview/wake_word_worker.py`, docstring); tocarlo exige pasar por spec y arquitectura

## Descartado (y por qué)
<!-- Opciones evaluadas y rechazadas — evita repetir el debate -->
2026-09-08 | Capturar `Exception` genérico en `WakeWordWorker.run()` y reintentar ahí | Reabre el micrófono desde fuera del módulo que lo administra y deja el bucle de `wake_word.py` igual de frágil para el uso headless de `ui/cli.py`, que no pasa por el worker

## Asumidos pendientes de confirmar
- Que el manos libres debe **volver solo** cuando el micrófono queda libre (vs. quedarse
  apagado esperando al humano). Es la decisión de producto central de este REQ.
- Que hay que avisar en pantalla, y no solo en el log.

## Riesgos activos
- **Bucle de reintentos infinito con el micrófono ocupado de forma permanente** (sin
  micrófono conectado): tiene que haber techo o backoff, no un `while True` golpeando PyAudio.
- **Ruido en el log**: un reintento cada segundo durante una reunión de una hora son 3600
  líneas de error.
- El fix toca el camino de voz completo, que es compartido por la GUI y por `ui/cli.py`
  (headless) — no puede romper el uso sin GUI.

## Pendiente para orion-spec
1. ¿El manos libres se reactiva solo o queda apagado con un aviso?
2. ¿Cuánto tiempo/reintentos antes de rendirse?
3. ¿Entra en el alcance el cambio de dispositivo por defecto (segundo modo de fallo)?
4. ¿El aviso va como toast en la ventana, notificación de bandeja, o las dos?

## Log de transiciones
<!-- FECHA | DE → A | AGENTE | NOTA -->
2026-09-08 | — → NUEVO | coordinación | REQ creado a partir del reporte de la reunión, con la reproducción ya adjunta

---

## Actualización 2026-09-08 — spec y arquitectura, sin el ciclo de agentes

Johan autorizó explícitamente saltar `orion-spec` y `orion-architect` e ir directo a
desarrollo. Los documentos existen igual, porque sin criterios de aceptación el dev inventa
el alcance y el tester no tiene contra qué medir:

- `spec/SPEC-028.md` — 13 criterios de aceptación testeables
- `propuestas/arquitectura-028.md` — piezas, flujo, riesgos y pruebas sugeridas
- `origen/baseline-028.md` — qué existe hoy y qué fallo es pre-existente

**Decisión de producto asumida:** el manos libres **vuelve solo** cuando el micrófono se
libera. Es la recomendación que se le dio a Johan y que él no corrigió al autorizar el
desarrollo. Si la decisión fuera la contraria (quedarse apagado con un aviso), cambian
CA-01, CA-03 y CA-05 de la SPEC — y nada más.

### Decisiones tomadas
2026-09-08 | conversación principal | Reconexión automática con backoff (1,2,4,8,15,30s) en vez de morir | Perder el micrófono es temporal (una reunión); apagarse es justo el fallo reportado
2026-09-08 | conversación principal | Solo se captura `OSError`, nunca `Exception` | Un error de código no puede quedar tapado detrás de reintentos infinitos
2026-09-08 | conversación principal | La reconexión vive en `voice/wake_word.py`, no en el worker de la GUI | El camino headless (`ui/cli.py`) no pasa por el worker y tiene el mismo problema
2026-09-08 | conversación principal | Estado nuevo `RECONNECTING`, distinto de `INACTIVE` | `INACTIVE` significa "lo apagaste vos"; el botón no puede mentir sobre por qué no escucha

### Log de transiciones
2026-09-08 | NUEVO → ARQUITECTURA_APROBADA | conversación principal | Spec + baseline + arquitectura escritos de una, por autorización explícita de Johan
2026-09-08 | ARQUITECTURA_APROBADA → (handoff) | conversación principal | Entregado a `orion-dev`

---

## Actualización 2026-09-08 — desarrollo (`orion-dev`)

Implementado lo aprobado en `propuestas/arquitectura-028.md`. Detalle completo en
`propuestas/desarrollo-log-028.md`.

`listen_for_wake_word()` pasó de ser **una sesión de micrófono con un bucle adentro** a ser
un **bucle de sesiones**. Firma pública intacta; el cuerpo de escucha (barge-in,
confirmación hablada, ventana de REQ-021) quedó igual, solo movido a `_escuchar_en_sesion()`.

**Archivos tocados:** `voice/wake_word.py`, `ui/webview/gui_state.py`,
`ui/webview/frontend/js/composer.js`, `ui/webview/frontend/css/composer.css`,
`tests/test_wake_word_reconexion.py` (nuevo, 25 tests) y
`origen/reproduccion-mic-ocupado.py` (adaptado). `ui/webview/wake_word_worker.py` NO se tocó.
Sin dependencias nuevas.

**Verificación:** `1904 passed, 1 failed` — el único fallo es el flaky de reloj pre-existente
(`test_task_slots.py::test_la_hora_dicha_se_respeta`), ya registrado en `origen/baseline-028.md`.
Baseline `1879 passed, 1 failed` → cero fallos nuevos. Los 13 criterios de aceptación quedan
cubiertos por test, salvo la parte de hardware real que va a la prueba manual.

### Decisiones tomadas
2026-09-08 | orion-dev | La recuperación se declara con una LECTURA buena, no con una apertura | En Windows un micrófono tomado por otra app se deja ABRIR igual y falla recién al leerlo; dar por recuperada la sesión al abrirla reiniciaría el backoff a 1 s en cada vuelta y produciría justo el bucle golpeando PyAudio que el REQ evita
2026-09-08 | orion-dev | El techo de 3 intentos de CA-07 se gobierna con `hubo_lectura_buena`, no con `al_abrir` a secas | Separa "no hay micrófono conectado" (se rinde) de "me lo quitaron en uso" (se reintenta indefinidamente), que es la distinción que pedía la arquitectura
2026-09-08 | orion-dev | Se agregó regla CSS para `RECONNECTING` en `composer.css`, no listada en la tabla de piezas | Sin ella ninguna regla matchea y el botón se pinta igual que `INACTIVE`: parecería apagado mientras sigue vivo reintentando, que es el aviso silencioso que el REQ vino a arreglar. Reusa `--danger`, sin tokens nuevos
2026-09-08 | orion-dev | `origen/reproduccion-mic-ocupado.py` se adaptó (worker en un hilo aparte) | Después del fix `run()` ya no retorna solo: llamarlo en línea colgaría el script para siempre. El encabezado conserva la salida del "antes" para comparar

### Riesgos activos (actualizado)
- Los dos riesgos de bucle infinito y de ruido en el log quedaron cerrados por CA-07 y CA-08,
  fijados por test.
- **Queda abierto** lo que no se puede probar sin hardware: que PyAudio en el equipo de Johan
  levante efectivamente `OSError` (y no otra excepción) al perder el dispositivo. La
  reproducción usa `-9988`/`-9999`, que son los códigos observados en el diagnóstico. Si en la
  prueba manual apareciera otro tipo de excepción, el fix no la captura a propósito (solo
  `OSError`, nunca `Exception`) y habría que ampliarlo con el tipo real a la vista.

### Log de transiciones
2026-09-08 | ARQUITECTURA_APROBADA → EN_PRUEBAS | orion-dev | Implementación completa, 25 tests nuevos, CA-13 verificado; handoff a `orion-tester`
