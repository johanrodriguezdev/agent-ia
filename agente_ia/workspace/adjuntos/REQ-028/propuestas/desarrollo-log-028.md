# Desarrollo REQ-028 — El manos libres sobrevive a que otra app tome el micrófono

**Fecha:** 2026-09-08 | **Agente:** `orion-dev` | **Rama:** `feature/REQ-027-reasoning-loop-nativo`

## Qué se implementó

`listen_for_wake_word()` era **una sesión de micrófono con un bucle adentro**. Ahora es un
**bucle de sesiones**: cuando el dispositivo se cae, se cierra esa sesión, se espera con
backoff y se abre otra. La firma pública no cambió (CA-11) y el cuerpo de escucha —barge-in,
confirmación hablada, ventana de conversación de REQ-021— quedó intacto, solo movido a
`_escuchar_en_sesion()` con la misma indentación.

## Archivos modificados

- `agente_ia/voice/wake_word.py` — el cambio real (+232/-11)
- `agente_ia/ui/webview/gui_state.py` — `RECONNECTING` documentado como cuarto valor de `WAKE_STATE`
- `agente_ia/ui/webview/frontend/js/composer.js` — etiqueta del estado nuevo en `setWakeState()`
- `agente_ia/ui/webview/frontend/css/composer.css` — color del botón en `RECONNECTING`
- `agente_ia/tests/test_wake_word_reconexion.py` — **nuevo**, 25 tests
- `agente_ia/workspace/adjuntos/REQ-028/origen/reproduccion-mic-ocupado.py` — adaptado para medir el después

`ui/webview/wake_word_worker.py` **no se tocó**, como decía la arquitectura: sigue viendo una
función que bloquea y devuelve comandos.

## Piezas construidas (`voice/wake_word.py`)

| Pieza | Qué hace |
|---|---|
| `_MicrofonoPerdido(Exception)` | Excepción interna. `al_abrir` separa "nunca pude tomar el micrófono" de "lo tenía y me lo quitaron". |
| `siguiente_espera(intento)` | Pura: 1, 2, 4, 8, 15, 30, 30… Testeable sin dormir. |
| `_esperar_troceado(segundos, stop_event)` | `stop_event.wait(0.5)` en bucle. Devuelve `False` si hay que parar. |
| `_sesion_de_microfono(recognizer, agent_label)` | Context manager que abre, anuncia y calibra, traduciendo el `OSError` del dispositivo. |
| `_escuchar_en_sesion(...)` | El cuerpo de siempre, sin cambios de comportamiento. |
| `listen_for_wake_word(...)` | El bucle de sesiones nuevo, con backoff, estado y avisos. |

## Dependencias agregadas

**Ninguna.** `contextlib.contextmanager` es de la librería estándar; `requirements.txt` no se tocó.

## Cobertura de los criterios de aceptación

| CA | Cómo queda cubierto |
|---|---|
| CA-01 | `except OSError` alrededor de `recognizer.listen()` → `_MicrofonoPerdido` → sesión nueva. Tests `test_ca01_*`. |
| CA-02 | `_sesion_de_microfono` traduce el `OSError` de construcción/`__enter__`/`adjust_for_ambient_noise`. Tests `test_ca02_*`. |
| CA-03 | `siguiente_espera()`, fijada por test contra `[1, 2, 4, 8, 15, 30, 30, 30]`. |
| CA-04 | `_report_state(..., "RECONNECTING")` antes de cada espera; el test verifica además que **no** se reporta `INACTIVE`. |
| CA-05 | `al_leer_bien()` vuelve a `LISTENING_WAKE` en cuanto el dispositivo responde. |
| CA-06 | `_esperar_troceado()` en trozos de 0.5 s; test de reloj real: apagar corta en <1 s de una espera de 30 s. |
| CA-07 | 3 aperturas fallidas seguidas **sin haber leído nunca** → aviso + `INACTIVE` + `return None`. |
| CA-08 | Primer fallo `logger.error` (una vez por caída), reintentos `logger.debug`, recuperación `logger.info`. |
| CA-09 | `notificar()` al perder ("Micrófono no disponible"), al recuperar ("Micrófono recuperado") y al rendirse ("Sin micrófono"). |
| CA-10 | La reconexión vive en `voice/wake_word.py`; test explícito con `wake_state_callback=None`. |
| CA-11 | Test con `inspect.signature`: mismos 3 parámetros, todos con default `None`. |
| CA-12 | Cero micrófono real: `sr.Microphone` y `Recognizer.listen` mockeados, espera sustituida por un espía. |
| CA-13 | `reproduccion-mic-ocupado.py` termina con el worker vivo y `exit 0`. |

## Decisiones de implementación

Tres ajustes menores respecto de la propuesta, todos dentro de su intención:

1. **La señal de recuperación es una LECTURA, no una apertura** (`al_leer_bien()`).
   La arquitectura no fijaba cuándo se da por terminada una caída. Elegir "cuando el
   micrófono abre" habría sido un bug: en Windows un dispositivo tomado por otra aplicación
   **se deja abrir igual** y falla recién al leerlo, así que el backoff se habría reiniciado
   a 1 s en cada vuelta y el resultado sería el bucle golpeando PyAudio una vez por segundo
   que el REQ vino a evitar. Un `WaitTimeoutError` cuenta como lectura buena: significa que
   se leyó silencio durante el timeout entero, o sea que el dispositivo responde.
   Fijado por `test_ca07_el_backoff_no_se_reinicia_si_el_microfono_no_responde`.

2. **`hubo_lectura_buena` decide si se abandona, no `al_abrir` solo.** CA-07 dice "no hay
   micrófono" y CA-01 dice "me lo quitaron"; el límite de 3 intentos aplica únicamente
   cuando el dispositivo **nunca** llegó a responder. Un micrófono que funcionó y después
   desaparece se sigue esperando indefinidamente, como pide la arquitectura
   ("solo se reintenta indefinidamente lo que alguna vez funcionó").

3. **Se agregó una regla CSS para `RECONNECTING`** (`composer.css`), que la tabla de piezas
   no listaba. Sin ella ninguna regla matchea y el botón se pinta igual que `INACTIVE`: el
   manos libres *parecería apagado* justo mientras sigue vivo reintentando, que es
   literalmente el aviso silencioso que el REQ vino a arreglar. Reusa `--danger`, ya
   definido en los dos temas — cero tokens nuevos, sin impacto en `test_webview_contrast.py`.

Además, `reproduccion-mic-ocupado.py` tuvo que adaptarse: llamaba a `worker.run()` en línea,
y después del fix `run()` ya no retorna solo. Ahora lo corre en un hilo aparte, comprueba que
sigue vivo reintentando y lo apaga con su propio `stop_event` (que es como lo apaga el
usuario desde la ventana). El encabezado del script conserva la salida del *antes* para poder
comparar.

## Verificación

```
python -m py_compile voice/wake_word.py ui/webview/gui_state.py \
    ui/webview/wake_word_worker.py tests/test_wake_word_reconexion.py \
    workspace/adjuntos/REQ-028/origen/reproduccion-mic-ocupado.py     -> OK
node --check composer.js (como .mjs)                                  -> OK

python -m pytest tests/ -q
    -> 1904 passed, 1 failed  (172.95s)
```

El único fallo es `tests/test_task_slots.py::test_la_hora_dicha_se_respeta`, **pre-existente**
y registrado en `origen/baseline-028.md`: depende del reloj de pared y falla cualquier día
después de las 17:00. Baseline: `1879 passed, 1 failed`. Ahora: `1904 passed, 1 failed`
(+25 tests nuevos, cero fallos nuevos).

### El antes/después de CA-13

```
$ python workspace/adjuntos/REQ-028/origen/reproduccion-mic-ocupado.py

== 1) llamada directa a listen_for_wake_word() ==
   -> retorno normal: None  (no propago la excepcion)
   sesiones de microfono reintentadas: 4
   backoff pedido (segundos): [1.0, 2.0, 4.0, 8.0]

== 2) el worker de la GUI (WakeWordWorker.run) ==
   llego a reintentar: True
   worker VIVO mientras reintentaba: True
   estados reportados a la interfaz: ['LISTENING_WAKE', 'RECONNECTING', 'INACTIVE']
   backoff pedido (segundos): [1.0, 2.0, 4.0]
   worker terminado tras apagar el toggle: True

RESULTADO: el manos libres sobrevivio al microfono ocupado y siguio reintentando.
```

Antes decía `-> PROPAGA la excepcion: OSError: [Errno -9988] Stream closed` y
`run() retorno -> el manos libres quedo apagado sin reintentar`.

## Lo que queda para la prueba manual del humano

Nada de esto se puede probar sin hardware real, y es donde el REQ se gana o se pierde:

1. Activar el manos libres, abrir Zoom/Meet/Teams y dejar que tome el micrófono. Tiene que
   aparecer el aviso "Micrófono no disponible" y el botón del composer quedar en rojo
   (`RECONNECTING`), no apagado.
2. Cerrar la reunión. Sin tocar nada, el aviso "Micrófono recuperado" y el botón de vuelta en
   amarillo, escuchando la wake word. Como máximo 30 s de espera.
3. Decirle algo al agente después de la reconexión: tiene que responder como antes.
4. Apagar el manos libres **mientras** está reconectando: el botón tiene que apagarse en el
   acto, no al final del backoff.
5. Modo headless (`main.py`, opción 3) con el micrófono ocupado: mismo comportamiento, sin GUI.

## Estado

- Estado tracker: `EN_PRUEBAS`
- Último agente: `orion-dev`
- Siguiente: `orion-tester`
