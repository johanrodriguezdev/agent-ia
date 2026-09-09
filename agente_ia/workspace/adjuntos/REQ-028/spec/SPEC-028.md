# SPEC-028 — El manos libres sobrevive a que otra app tome el micrófono

**Categoría:** VOZ | **Tipo:** BUG_FIX | **Fecha:** 2026-09-08

## Problema
Ver `REQ-028-context.md` para la cadena completa y la reproducción. En una frase: un
`OSError` de PyAudio mata el bucle de escucha, el manos libres se apaga en silencio, y no
vuelve nunca — ni cuando el micrófono queda libre.

## Decisión de producto
**El manos libres vuelve solo.** Perder el micrófono es una condición temporal y normal
(una reunión, una llamada), no el final de la sesión. Quedarse apagado esperando que el
humano apriete un botón es lo que hace hoy, y es exactamente el fallo reportado.

> Asumido por la conversación principal y autorizado por Johan el 2026-09-08 para ir
> directo a desarrollo, sin el ciclo de `orion-spec`/`orion-architect`. Si la decisión
> fuera la contraria (quedarse apagado con un aviso), cambian CA-01, CA-03 y CA-05.

## Criterios de aceptación

- [ ] **CA-01** — Un `OSError` durante la escucha NO termina `listen_for_wake_word()`: se
  cierra la sesión de micrófono, se espera, y se abre una sesión nueva.
  *Verificación:* pytest — `Recognizer.listen` lanza `OSError` una vez y después devuelve
  audio con la wake word; la función sigue viva y devuelve el comando.
- [ ] **CA-02** — Lo mismo si el fallo ocurre al ABRIR el micrófono (`sr.Microphone()`), no
  solo al leerlo. *Verificación:* pytest con un `__enter__` que lanza `OSError` la primera vez.
- [ ] **CA-03** — La espera entre reintentos crece y tiene techo: 1, 2, 4, 8, 15, 30, 30...
  segundos. *Verificación:* pytest sobre la función pura de backoff, sin dormir de verdad.
- [ ] **CA-04** — Mientras reintenta, el estado reportado es `RECONNECTING`, distinto de
  `INACTIVE` (que sigue significando "el manos libres está apagado") y de `LISTENING_WAKE`.
- [ ] **CA-05** — Al reconectar vuelve a `LISTENING_WAKE` y escucha como antes, sin que el
  usuario toque nada.
- [ ] **CA-06** — `stop_event` corta el reintento: apagar el manos libres mientras espera
  termina en menos de 1s, no al final del backoff. La espera es troceada, nunca un
  `sleep(30)` opaco. *Verificación:* pytest comprobando que se consulta `stop_event`.
- [ ] **CA-07** — Si NO hay micrófono al arrancar (dispositivo ausente), no hay bucle
  infinito: 3 intentos, aviso al usuario, y `INACTIVE`. Es un caso distinto de "lo perdí
  mientras funcionaba", y se distingue explícitamente.
- [ ] **CA-08** — El log no se inunda: primer fallo con `logger.error`, reintentos con
  `logger.debug`, recuperación con `logger.info`. Una reunión de una hora no puede dejar
  miles de líneas de error.
- [ ] **CA-09** — El usuario se entera: aviso visible (`core/notificaciones.py::notificar`)
  al perder el micrófono y al recuperarlo. Hoy solo cambia el `title` de un botón.
- [ ] **CA-10** — El camino headless (`ui/cli.py`, `wake_state_callback=None`) sigue
  funcionando: la reconexión vive DENTRO de `listen_for_wake_word()`, no en el worker de la
  GUI, porque el headless no pasa por el worker.
- [ ] **CA-11** — La firma pública de `listen_for_wake_word()` no cambia, y sus retornos
  (`str` / `True` / `False` / `None`) siguen significando lo mismo.
- [ ] **CA-12** — Ningún test toca el micrófono real (regla de `testing.md`): todo con
  mocks de `sr.Microphone` y `Recognizer.listen`.
- [ ] **CA-13** — `origen/reproduccion-mic-ocupado.py` termina con el worker VIVO y
  reintentando. Hoy termina con `run()` retornado: ese es el antes/después del REQ.

## Fuera de alcance (v1)
- Elegir el dispositivo de entrada desde Configuración (`device_index` fijo).
- Detectar el cambio de dispositivo por defecto cuando el stream viejo NO se cae: la
  reconexión toma el default del momento de reabrir, así que ese caso queda cubierto solo
  cuando además hay error. Anotado en el contexto como segundo modo de fallo.
- Barge-in, ventana de conversación y wake word: nada de eso cambia.
