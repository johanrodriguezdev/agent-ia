# Contexto REQ-028 — El manos libres muere cuando otra app toma el micrófono

## Resumen ejecutivo
El modo manos libres no se degrada ante un micrófono ocupado: se **muere**. Un `OSError` de
PyAudio (otra app toma el dispositivo, cambia el default de Windows) no está contemplado en
el bucle de escucha, propaga, cierra el micrófono y termina el worker. El toggle vuelve a
`INACTIVE` sin un solo aviso al usuario y no se recupera solo ni cuando el micrófono queda
libre. Objetivo: reconexión automática + aviso visible.

## Estado actual
- **Estado tracker:** NUEVO
- **Último agente:** conversación principal (coordinación) → siguiente: `orion-spec`
- **Fecha última actualización:** 2026-09-08
- **Rama git:** — (a definir con el humano; hoy la sesión está en `feature/REQ-027-reasoning-loop-nativo`)
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
