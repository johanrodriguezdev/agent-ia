# Contexto REQ-036 — Procesos que no terminan

## Resumen ejecutivo
El último "todavía no" del punto 1: **levantar un servidor, usarlo y bajarlo**. `project_run`
(REQ-032) espera a que el comando termine, así que un servidor de desarrollo terminaba
siempre igual — muerto por el timeout a los 120 segundos, con el turno perdido.

Tres herramientas: `project_start` deja el proceso vivo, `project_output` lee su salida y
dice si sigue corriendo, `project_stop` lo baja.

## Estado actual
- **Estado tracker:** EN_PRUEBAS | **Categoría:** CORE | **Tipo:** FEATURE_NUEVA
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Fecha:** 2026-09-09

## Lo que evita dejar basura
| Riesgo | Cómo se cierra |
|---|---|
| Un servidor huérfano ocupando el puerto 3000 después de cerrar el asistente | `MainWindow` llama a `cerrar_todos()` en `aboutToQuit`, igual que ya hacía con las terminales embebidas |
| La salida crece sin freno | Buffer circular de 1000 líneas: un servidor que loguea cada petición llenaría la memoria en una tarde |
| Un bucle del modelo levanta cincuenta servidores | Tope de 5 procesos simultáneos |
| El proceso se cuelga solo | Hay un hilo leyendo su salida. Sin él la tubería del sistema se llena y el proceso **se bloquea** esperando que alguien lea — y el síntoma, "se cuelga después de un rato", es de los peores de diagnosticar |
| Una pregunta interactiva que nadie va a contestar | `stdin` va a `DEVNULL` |

## Decisiones tomadas
2026-09-09 | conversación principal | `project_start` espera 1 segundo antes de devolver | La mayoría de los servidores fallan al arrancar (puerto ocupado, import roto) y ese error aparece enseguida. Devolverlo en el acto ahorra la vuelta entera de "arrancó bien" seguida de "no, estaba muerto"
2026-09-09 | conversación principal | `project_output` y `project_stop` son 🟢 | Es la salida de un proceso que el propio agente levantó con un comando ya confirmado. `project_run` devuelve su salida sin pedir un permiso aparte: partir el arranque de la lectura no puede agregar una confirmación que la versión síncrona no tiene. Y pedir permiso para limpiar sería premiar dejar basura corriendo
2026-09-09 | conversación principal | `project_start` SÍ entra en la lista blanca del modo autonomía | Es la misma clase de acción que `project_run`: un comando dentro de una carpeta habilitada. Sin esto, "levantá el server y corré las pruebas de integración" se frenaría en el primer paso justo la noche que no hay nadie

## El choque entre dos REQs propios, y cómo se resolvió
Al probar el flujo completo apareció que **`http_request` bloqueaba `localhost`** por la
guarda anti-SSRF de REQ-031: el agente podía levantar el servidor pero no pegarle.

No se aflojó la guarda. Se separó por camino, que es donde estaba la diferencia real:

- **`web_read` sigue con el bloqueo absoluto.** Es 🟢 verde y alcanzable desde Telegram: es
  el camino por el que un mensaje remoto o una inyección en una página podrían pedir una
  dirección interna sin que nadie lo vea. Ahí no se toca nada.
- **`http_request` puede alcanzar direcciones internas.** Es 🟡, solo de escritorio, y
  confirma **cada llamada mostrando la URL**: un humano ve `http://localhost:3000/api` antes
  de que ocurra.

La distinción quedó fijada por dos tests que se leen juntos: uno comprueba que
`http_request` llega, el otro que `web_read` sigue sin llegar.

## Log de transiciones
2026-09-09 | — → EN_PRUEBAS | conversación principal | Gestor de procesos, 3 herramientas, cierre al salir y 14 tests

2026-09-18 | → LISTO_PARA_COMMIT | conversación principal (sesión nocturna autorizada por Johan) | Sincronización del tracker con `main`: el código de este REQ ya está commiteado y mergeado y la evidencia (QA aprobado y/o suite en verde registrada en este contexto) estaba completa. Solo cambia el estado; no se toca código.
