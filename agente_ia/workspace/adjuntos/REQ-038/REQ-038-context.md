# Contexto REQ-038 — Que pueda usar el computador: ver la página y actuar sobre ella

## Resumen ejecutivo
Punto 2 de la lista de Johan: *"Pueda usar el computador — interactuar con interfaces,
navegar por sitios y ejecutar procesos de varios pasos"*.

El agente ya manejaba Excel y el Bloc de notas con precisión exacta, porque `ui_tree.py` le
pregunta al sistema dónde está cada control. Con el navegador se quedaba ciego: veía la
barra de herramientas de Chrome y **nada del contenido de la página**. Para pulsar un enlace
tenía que estimar coordenadas sobre una captura, y con veinte píxeles de error esa es la
diferencia entre "Aceptar" y "Cancelar".

## Estado actual
- **Estado tracker:** EN_PRUEBAS | **Categoría:** AUTOMATIZACION | **Tipo:** FEATURE_NUEVA
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo` | **Fecha:** 2026-09-10

## El error que costó el primer diseño (y por qué queda escrito)

La primera versión de este REQ concluyó que:

1. Chrome no publica el contenido web salvo que arranque con `--force-renderer-accessibility`.
2. Ese flag no se puede encender en caliente.
3. Por lo tanto había que **pedirle al usuario que cerrara su navegador**.

Estaba medido —33-45 elementos sin el flag, 4.000 con él, sobre la misma página de
Wikipedia— y era falso. **El error estaba en el medidor.** Recorrer el árbol nodo por nodo
desde Python (`GetChildren()` recursivo, que es lo que hace `ui_tree`) tarda decenas de
segundos en una página real, así que el recorrido se quedaba sin presupuesto de tiempo
dentro de la barra de herramientas y nunca llegaba al contenido. Lo que se midió como
"Chrome no publica la página" era "mi recorrido no llegó".

Pidiéndoselo a UI Automation con `FindAll` —una sola llamada COM, resuelta dentro de
Windows— el Chrome del usuario, **sin flag y sin reiniciar nada**, devuelve el documento
entero en 0,1-0,3 segundos. Medido sobre sus dos ventanas abiertas: 92 y 362 nodos.

Consecuencia: **el diseño ya no le pide a nadie que cierre el navegador.** Sigue sin cerrar
nada por su cuenta —eso no cambia— pero el motivo para pedirlo no existía.

Queda escrito porque el camino equivocado era el intuitivo, y la próxima persona que lea
"Chrome no expone la página" va a llegar a la misma conclusión.

## Los otros dos hallazgos
- **Chromium construye el árbol cuando detecta que alguien lo lee**, no al cargar la página:
  medido, ~9 segundos. Preguntar una sola vez y concluir "no se ve" es el mismo error de
  antes en pequeño. Por eso `esperar_pagina()` reintenta, avisa al navegador con
  `WM_GETOBJECT` —lo que hace un lector de pantalla— y recorre dos niveles del árbol.
- **El primer `DocumentControl` del árbol suele estar vacío.** Chromium tiene varios; el de
  la página es el que más contenido tiene. Quedarse con el primero fue lo que hacía que la
  detección dijera "no veo nada" con la página delante.

## Lo que se hizo
| Dónde | Qué |
|---|---|
| `os_integration/navegador.py` | Reescrito sobre `FindAll`: `documento_de`, `ve_la_pagina`, `esperar_pagina`, `elementos_de_pagina`, `abrir`, `resumen_de_pagina`, `accionar` |
| `agents/tool_registry.py` | `browser_open` 🟢, `browser_page` 🟢, `browser_act` 🟡 |
| `core/security_manager.py` | `objetivo` y `texto` a `_DETAILS_ALLOWED_KEYS`: el modal tiene que decir sobre QUÉ se va a pulsar |
| `core/acciones_legibles.py` | Cómo se lee `browser_act` en una confirmación hablada |
| `tests/test_navegador.py` | 30 pruebas, ninguna abre un navegador |

## Rendimiento medido (Wikipedia, 4.749 nodos)
| Operación | Tiempo |
|---|---|
| Encontrar el documento y medirlo (`ve_la_pagina`) | ~1,8 s |
| Leer lo accionable de la página | ~3,4 s (125 elementos) |
| Ver la página desde que se abre | 3-11 s |

Tres decisiones salieron de ahí: una sola consulta con condición `OR` para los nueve tipos
en vez de nueve consultas (cada una recorre los 4.749 nodos por dentro), los nombres y las
posiciones pedidos **en la misma llamada** (`FindAllBuildCache`), y un tope por tipo, con los
enlaces al final: en una página larga sobran enlaces, nunca sobra el campo de un formulario.

## Seguridad
- `browser_open` 🟢 y `browser_page` 🟢 — abrir y mirar. Mismo criterio que `open_url` y
  `pc_look`, que ya existían.
- `browser_act` 🟡 y **solo escritorio** — actúa dentro de la sesión del usuario, con sus
  cuentas abiertas: un clic puede comprar, borrar o enviar. No hay entrada en
  `CHANNEL_ACTION_EXCEPTIONS`, así que no la alcanzan Telegram, Discord, correo ni voz.
- La confirmación **muestra el objetivo y el texto**. Un "sí" a «hacer clic en la página»
  sin ver que el objetivo es «Eliminar cuenta» no es una autorización.

## Puntería del clic
Pidiendo «Historia» en Wikipedia, la búsqueda por "aparece dentro" elegía **«Ver
historial»** — está más arriba en la página y contiene esas letras. Un clic en el sitio
equivocado dentro de la sesión del usuario no es un detalle de precisión. `_elegir()` va
ahora de lo estricto a lo flexible —exacto, empieza por, **palabra entera**, aparece
dentro— y entre varios candidatos gana el nombre más corto.

## Lo que NO hace todavía
- **No desplaza la página.** Solo actúa sobre lo que está renderizado; un elemento que
  requiere hacer scroll no aparece en la lista.
- **No maneja pestañas** (cambiar, cerrar, abrir en segundo plano).
- **No lee PDFs abiertos en el navegador** ni contenido dentro de un `<canvas>`: ahí no hay
  árbol de accesibilidad que leer.
- **No espera a que la página termine de cambiar** después de un clic: si un formulario
  carga la pantalla siguiente, hay que volver a pedir `browser_page`.
- Firefox no está en la lista de navegadores reconocidos (Chrome y Edge sí).

## Pendiente
- Prueba manual de Johan.
