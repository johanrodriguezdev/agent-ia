# Arquitectura REQ-028

## Idea central
Hoy `listen_for_wake_word()` es una sesión de micrófono con un bucle adentro. Pasa a ser
**un bucle de sesiones**: si la sesión muere por un problema del dispositivo, se abre otra.

```
listen_for_wake_word()                    # firma pública intacta (CA-11)
  while not stop_event.is_set():
      try:
          return _escuchar_en_sesion(...)  # el cuerpo de hoy, tal cual
      except _MicrofonoPerdido:
          reportar RECONNECTING + notificar (solo la primera vez)
          _esperar_troceado(siguiente_espera(intento), stop_event)
```

## Piezas

| Pieza | Dónde | Qué hace |
|---|---|---|
| `_MicrofonoPerdido` | `voice/wake_word.py` | Excepción interna. El `except OSError` del bucle de escucha la levanta para cortar la sesión sin matar la función. |
| `_escuchar_en_sesion()` | `voice/wake_word.py` | El cuerpo actual (el `with sr.Microphone()` y su `while`), extraído sin cambios de comportamiento. |
| `siguiente_espera(intento)` | `voice/wake_word.py` | Función **pura**: 1, 2, 4, 8, 15, 30, 30... Testeable sin dormir, mismo criterio que `fit_size_to_screen()` y `resolver_maximizado()`. |
| `_esperar_troceado(segundos, stop_event)` | `voice/wake_word.py` | `stop_event.wait(0.5)` en bucle. Sin esto, apagar el manos libres tardaría hasta 30s (CA-06). |
| `RECONNECTING` | `ui/webview/gui_state.py` | Cuarto valor de `WAKE_STATE`, documentado junto a los otros tres. |
| Etiqueta | `ui/webview/frontend/js/composer.js::setWakeState` | "Modo manos libres: reconectando el micrófono". El botón no puede parecer apagado mientras reintenta. |
| Aviso | `core/notificaciones.py::notificar()` | Ya existe y es seguro desde un hilo trabajador. Uno al perder el micrófono, uno al recuperarlo (CA-09). |

## Flujo de datos
`_escuchar_en_sesion()` levanta `_MicrofonoPerdido` → el bucle exterior reporta el estado
por el `wake_state_callback` que ya recibe (o por `update_gui_state()` en headless, igual
que hoy) → espera troceada → sesión nueva. `WakeWordWorker` no cambia una línea: sigue
viendo una función que bloquea y devuelve comandos.

## Dependencias nuevas
Ninguna. Todo se resuelve con `threading.Event` y lo que ya está importado.

## Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| Bucle infinito si no hay micrófono conectado | CA-07: el fallo en la PRIMERA apertura se limita a 3 intentos y termina en `INACTIVE` con aviso. Solo se reintenta indefinidamente lo que alguna vez funcionó. |
| Inundar el log durante una reunión larga | CA-08: `error` la primera vez, `debug` los reintentos. |
| Romper el camino headless | CA-10: la reconexión vive en `wake_word.py`, que es el código compartido por la GUI y por `ui/cli.py`. |
| Tapar un error real de código con reintentos | Se captura **solo `OSError`** (el del dispositivo), nunca `Exception` genérico: un `TypeError` sigue subiendo y muriendo ruidosamente. |
| Reintentar mientras el agente habla o espera confirmación | La sesión nueva arranca en `LISTENING_WAKE` limpio; la ventana de conversación (REQ-021) se cierra sola por tiempo, así que no queda una ventana abierta apuntando a una sesión muerta. Verificar en desarrollo. |

## Pruebas sugeridas
`tests/test_wake_word_reconexion.py` — CA-01, CA-02, CA-03, CA-06, CA-07, con mocks de
`sr.Microphone` y `Recognizer.listen`, `time.sleep` parcheado y cero micrófono real (CA-12).
Más la corrida de `origen/reproduccion-mic-ocupado.py` para CA-13.
