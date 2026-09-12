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

## Segunda entrega — los cinco huecos que quedaban

Johan pidió cerrarlos todos. Se cerraron cuatro y el quinto queda reconocido pero sin medir.

| Hueco | Qué se hizo |
|---|---|
| No desplazaba la página | `ScrollItemPattern.ScrollIntoView()` antes de pulsar. Medido: un enlace a y=5352 baja a y=556 |
| No manejaba pestañas | `browser_tabs`, `browser_tab_switch` 🟢, `browser_tab_close` 🟡 |
| No leía PDFs ni texto | `browser_text` con `TextPattern`. **El PDF se lee**: probado con uno abierto en Chrome |
| No esperaba tras un clic | `_esperar_a_que_cambie`: espera a que cambie *y se quede quieta*, y dice en qué página quedaste |
| Firefox | Reconocido, **sin probar**: no está instalado en esta máquina |

### El cambio de fondo: patrones en vez de ratón
Cerrando estos huecos apareció algo más importante. Hacer todo con coordenadas se rompe por
todos lados, y se rompió de verdad en las pruebas:

1. Windows se negó a poner la ventana al frente — el clic se rechazó (bien) pero el paso no
   se hizo. Se arregló enganchándose al hilo de entrada (`AttachThreadInput`) y reintentando.
2. Al traer un enlace de Wikipedia a la vista, `ScrollIntoView` lo dejó **debajo de la
   cabecera fija** de la página: el punto exacto estaba tapado.

UI Automation permite *operar* los controles, no solo leerlos, y eso no tiene ninguno de
esos problemas. Ahora se pulsa con `InvokePattern`, se escribe con `SetFocus()` + teclado,
se cambia de pestaña con `SelectionItemPattern` y se cierra con el `InvokePattern` de su
botón. El clic por coordenadas sigue de respaldo, con todas las comprobaciones
(`_preparar_clic_fisico`), pero ya no es el camino normal.

### Y un tercer hueco que no estaba en la lista
El tope de elementos acotaba lo que se le *muestra* al modelo, pero también estaba acotando
lo que se podía *pulsar*: «Historia de Python» está en la página y el agente respondía "no
lo encontré" porque no había entrado en la muestra de 200. Ahora, si el nombre no está en la
lista, se le pregunta a Windows por ese nombre concreto antes de rendirse.

## Tercera entrega (2026-09-11) — leer lo que está dibujado

Un mapa, un lienzo, un vídeo con subtítulos, una imagen con texto: no publican árbol, pero
son píxeles con letras. `os_integration/ocr.py` usa el motor de reconocimiento de texto que
trae Windows (`Windows.Media.Ocr`, español instalado): local, sin modelo y sin red.

- `browser_text` cae al OCR de la ventana cuando la página no publica texto.
- `pc_read` 🟢 lee lo dibujado en cualquier ventana: un juego, un escritorio remoto, un PDF
  abierto en un visor que no publique texto.
- Las cifras se corrigen donde el OCR se confunde: `$1.250.OOO` → `$1.250.000`, solo dentro
  de palabras que ya son casi un número.

Y de paso, dos cosas que estaban mal y salieron al medir:

- **La captura de pantalla solo veía el monitor principal.** Johan tiene dos; una ventana
  en x=2880 daba una captura en negro. `pc_look` la describía como si no existiera. Ahora se
  captura el monitor donde está la ventana activa y se guarda su origen, porque un clic
  calculado sobre esa captura tiene que sumarle dónde empieza ese monitor.
- **La comprobación de lo escrito leía antes de que la aplicación terminara de teclear** y
  avisaba en falso. Ahora espera a que el contenido deje de cambiar.

## Lo que sigue sin hacer
- **Firefox no está medido.** No está instalado, y medirlo es instalarlo y abrirle ventanas
  en el equipo de Johan mientras lo usa. Se hace cuando él no esté delante.
- **No resuelve captchas ni el doble factor.** Están para impedir exactamente esto.

## Pendiente
- Prueba manual de Johan.
