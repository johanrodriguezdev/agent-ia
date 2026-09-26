# Contexto REQ-069 — El navegador en Linux, por el protocolo del propio navegador

## Resumen ejecutivo
Las siete herramientas `browser_*` estaban construidas sobre UI Automation y por eso
estaban muertas fuera de Windows. Johan eligió el camino **híbrido**: en Windows no cambia
nada —sigue leyendo el Chrome que el usuario ya tiene abierto, con sus sesiones— y en
Linux el navegador se maneja por **CDP**, el protocolo que el propio Chromium publica, que
es el que usa OpenClaw. Las siete funciones públicas deciden en su primera línea; el código
de Windows no se movió.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** AUTOMATIZACION | **Tipo:** FEATURE_NUEVA
- **Fecha:** 2026-09-22

## Origen
Johan, 2026-09-22, eligiendo entre cuatro caminos: «Híbrido: Windows igual, CDP en Linux».
Se descartó CDP en los dos sistemas porque en Windows sería un **retroceso**: hoy el agente
lee el navegador que el usuario ya tiene abierto, y CDP no puede hacer eso.

## SPEC — criterios de aceptación
| # | Criterio |
|---|---|
| CA-01 | En Windows no cambia nada: las siete funciones entran en el código de UI Automation y los 62 tests de `test_navegador.py` siguen pasando |
| CA-02 | Las **siete** funciones públicas delegan fuera de Windows (una que se olvide ejecutaría UI Automation en Linux y fallaría sin explicar nada) |
| CA-03 | En Linux: abrir una dirección, listar pestañas, cambiar y cerrar pestañas — por HTTP, así que funcionan aunque falte la dependencia de WebSocket |
| CA-04 | Leer el texto de la página, enumerar lo accionable y pulsar/escribir — por WebSocket con `Runtime.evaluate` |
| CA-05 | El resumen numera lo accionable y se puede pulsar por número o por texto, igual que en Windows |
| CA-06 | Un objetivo con comillas no rompe el JavaScript inyectado (se escapa como JSON) |
| CA-07 | Cada fallo responde con una frase que se le puede decir al usuario: sin navegador instalado, sin la dependencia, sin pestañas, o el objetivo que no está en la página |
| CA-08 | Sin pantalla (contenedor, SSH, modo consola) el navegador arranca en modo «headless» en vez de morir |
| CA-09 | La limitación queda dicha: CDP no alcanza un navegador que ya estaba abierto |

## Arquitectura
- **`os_integration/navegador.py`** sigue siendo la fachada y el hogar de UI Automation. Se
  le agregó `_ES_WINDOWS` y `_cdp()`, y **una línea** al principio de cada una de las siete
  funciones públicas. No se movió una sola línea del código de Windows: lo que funciona se
  queda donde está.
- **`os_integration/navegador_cdp.py`** (nuevo): lanza su propio Chromium con
  `--remote-debugging-port` y un perfil descartable, y habla el protocolo. Listar, abrir,
  activar y cerrar por HTTP; leer y actuar por WebSocket. El JavaScript inyectado marca
  cada elemento accionable con `data-orion-id`, que es lo que permite «pulsá el 3».
- **Dependencia nueva:** `websocket-client`. Solo hace falta para leer y pulsar; abrir y
  cambiar de pestaña funcionan sin ella, y si falta se dice cuál es.

## Tres fallos que solo aparecieron ejecutándolo contra un Chromium real
Ninguno se ve leyendo el código. Por eso se probó dentro del contenedor y no solo con
tests de escritorio.

1. **`No usable sandbox!`** — Chromium se cerraba al instante. Faltaba el paquete
   `chromium-sandbox`, que es lo que el propio error recomienda **antes** que
   `--no-sandbox`. Se agregó a la imagen. Poner `--no-sandbox` de entrada habría
   «funcionado» apagando una protección real del navegador, que es justo la superficie por
   donde entra contenido ajeno.
2. **Sin pantalla, Chromium no arranca.** Dentro del contenedor no hay X11, y una ventana
   necesita dónde dibujarse. Ahora, si no hay `DISPLAY` ni `WAYLAND_DISPLAY`, se lanza con
   `--headless=new`: el agente lee y pulsa igual, solo que nadie lo ve. Con pantalla se
   abre normal, que es lo que se quiere en un escritorio.
3. **WebSocket rechazado con 403.** Chromium bloquea toda conexión con una cabecera
   `Origin` que no haya autorizado. La salida fácil era `--remote-allow-origins=*`, que
   abre la depuración del navegador a cualquier página que él mismo esté mostrando. Se
   resolvió **no mandando la cabecera** (`suppress_origin=True`): mismo resultado sin bajar
   ninguna defensa, y el puerto ya escucha solo en 127.0.0.1.

## Decisiones tomadas
2026-09-22 | Johan | Híbrido, no CDP en los dos sistemas | En Windows sería un retroceso: se perdería leer el Chrome ya abierto del usuario, con sus sesiones.
2026-09-22 | conversación principal | La delegación va en la primera línea de cada función, no moviendo el módulo | Mover 1300 líneas que funcionan es arriesgar lo que ya está probado para ganar elegancia.
2026-09-22 | conversación principal | Perfil propio y descartable | Con el perfil del usuario, Chrome se niega a abrir una segunda instancia y devolvería el control de nada.
2026-09-22 | conversación principal | Firefox queda fuera de este camino | Habla otro protocolo de depuración; elegirlo sería prometer algo que no se puede cumplir.
2026-09-22 | conversación principal | Sin sandbox SOLO dentro de un contenedor, y avisando en el log | Si Chromium no arranca de otro modo, ahí el aislamiento lo pone el contenedor. En un escritorio nunca.

## Qué puede hacer ahora en Linux
- «Abrí es.wikipedia.org y decime de qué trata» → abre, lee y resume.
- «¿Qué hay en esta página?» → la numera: `1. [a] Ver el detalle`, `2. [button] Aceptar`…
- «Pulsá Aceptar» / «pulsá el 2» → lo pulsa, y la página reacciona de verdad.
- «Escribí "palma de aceite" en el buscador» → lo escribe.
- «Cambiá a la pestaña del correo» / «cerrá esa pestaña».

## Qué NO hace (y hay que decirlo cuando se use)
- **No alcanza el navegador que el usuario ya tenía abierto.** Chrome no deja encender la
  depuración en caliente, así que el agente trabaja sobre **su propia ventana**, sin las
  sesiones del usuario: «leé mi correo» no funciona por esta vía. Para eso haría falta la
  extensión de navegador, que es el segundo mecanismo de OpenClaw y otro REQ.
- No hay Firefox.
- El árbol de accesibilidad de otras aplicaciones (`pc_act`, `pc_find`) sigue sin existir
  en Linux: eso es la fase 3 (AT-SPI).

## Verificación
- `pruebas/prueba-cdp-en-linux.py` y `pruebas/resultado-cdp-en-linux.txt`: **el ciclo
  completo contra un Chromium real dentro del contenedor** — abrir, listar, leer el texto,
  enumerar lo accionable, pulsar (y comprobar que la página reaccionó), escribir, rechazar
  lo inexistente y cerrar. La página de prueba se sirve desde el propio contenedor, así que
  no depende de internet.
- `tests/test_navegador_cdp.py`: 19 tests, incluido uno que comprueba que **las siete**
  funciones delegan.
- `tests/test_navegador.py`: los 62 de Windows, intactos.
- `pruebas/suite-069.txt`: suite completa.

## Prueba manual sugerida (en Linux)
1. «Abrí es.wikipedia.org y decime de qué trata la página» → tiene que abrir **su propia
   ventana** de Chromium, leerla y resumirla.
2. «¿Qué puedo pulsar ahí?» → la lista numerada.
3. «Pulsá el 1» → lo pulsa y cuenta qué pulsó.
4. Pedirle algo de una pestaña **tuya** ya abierta → tiene que decir que no la ve. Eso es
   lo esperado, no un fallo.

## Log de transiciones
2026-09-22 | NUEVO → EN_DESARROLLO | conversación principal | Híbrido elegido por Johan. Tres fallos encontrados ejecutando contra Chromium real, todos corregidos.
