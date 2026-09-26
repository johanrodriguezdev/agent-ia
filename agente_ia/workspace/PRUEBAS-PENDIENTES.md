# Pruebas manuales pendientes — al 2026-09-22

Todo lo de acá está implementado, con la suite en verde (3451 tests) y verificado hasta
donde se puede verificar sin un humano delante. Lo que falta es exactamente lo que una
suite no puede decir: si el resultado **sirve**.

Orden recomendado: **A** primero (es lo más nuevo y lo menos probado con material tuyo),
**B** después (rápido, todo seguido en la misma ventana), **C** cuando tengas el Linux.

En cada prueba: qué pedirle · qué tiene que pasar · **qué significa si falla**.

---

## Bloque A — Documentos (Windows, ~20 min) — LO MÁS IMPORTANTE

Es lo más importante porque mi validación fue con plantillas que me inventé yo. Nunca se
probó contra un documento tuyo de verdad. REQ-040, 065 y 066.

**Preparación:** tené a mano una plantilla tuya en `Documentos` (una cotización, un
membrete, lo que uses de verdad) y un `.docx` cualquiera ya escrito.

### A1 · La cotización con tu plantilla ← la prueba clave
> «Hazme una cotización con la plantilla de Documentos para Finca La Esperanza»
> (a propósito: **no le des la fecha**)

- **Tiene que:** preguntarte la fecha, o decirte qué marcador le falta.
- **No tiene que:** entregarte un archivo con `[FECHA]` o `{{fecha}}` impreso.
- **Si falla:** es el fallo que arreglé en REQ-065 (marcadores sin rellenar). Decime qué
  marcadores usa tu plantilla y cómo están escritos.

### A2 · El Excel con fórmulas ← el bug más grave que había
> «Hazme un Excel con las ventas del mes, con IVA del 19 % y una fila de total»

- **Tiene que:** abrir en Excel **sin el diálogo de "recuperar/reparar"** y con los valores
  calculados (no `#¿NOMBRE?`).
- **Si falla:** es el fallo de las fórmulas en español. Es el más importante de los siete,
  porque antes el agente decía «Listo» y el archivo no abría.

### A3 · El estilo guiado
> «Hazme el informe de X en Arial 11, títulos en verde oscuro, horizontal y con número de página»

- **Tiene que:** cumplir **los cuatro**. Abrí el .docx y comprobalos uno por uno.
- **Si falla:** decime cuál de los cuatro no salió.

### A4 · Cambiar el aspecto de un documento que ya existe (REQ-066)
> Con un `.docx` tuyo: «ponele a este documento letra Arial 11, títulos en azul oscuro y número de página»

- **Tiene que:** cambiar el aspecto y **no tocar una palabra del texto**.
- **Si falla:** revisá si el documento tenía estilos propios raros.

### A5 · Agregar una fila a una hoja con total
> «Agregale una fila a ese Excel con [producto, cantidad, precio]»

- **Tiene que:** entrar **antes** de la fila Total, y el total tiene que cambiar.
- **Si falla:** mirá si tu hoja llama a esa fila de otra forma que «Total».

### A6 · Agregar una diapositiva
> Con una presentación que tenga logo: «agregale una diapositiva sobre X»

- **Tiene que:** salir con el mismo logo y la misma letra que las demás, y renumerarse todas.

---

## Bloque B — La interfaz del chat (Windows, ~20 min)

Once REQs de las noches del 20 y 21. Se prueban seguidos, en la misma ventana. Son rápidos.

| # | Qué hacer | Qué tiene que pasar | REQ |
|---|---|---|---|
| B1 | `Win+Shift+S`, recortar algo, `Ctrl+V` en el chat, escribir «¿qué dice?» | Chip con miniatura → la burbuja muestra la imagen → el agente la describe | 054 |
| B2 | Click en la miniatura | Visor a tamaño completo; `Escape` cierra | 054 |
| B3 | Cerrar la conversación y reabrirla desde Recientes | La miniatura sigue ahí | 054 |
| B4 | Dos capturas pegadas, «¿qué cambió?» | Las compara. Si dice que no ve imágenes → Configuración → Modelos → «Ver imágenes» | 063 |
| B5 | Pegar una captura y Enter **sin texto** | Se manda sola | 063 |
| B6 | «Regenerar» sobre la última respuesta | Se va y llega otra; en Recientes sigue habiendo **una sola** conversación | 055 |
| B7 | «Regenerar» sobre la **primera** respuesta de un chat largo | Modal que dice cuántos mensajes se van; al confirmar, la conversación vuelve ahí | 064 |
| B8 | Cancelar ese modal | No cambia nada | 064 |
| B9 | «Editar» un mensaje tuyo del medio | El texto vuelve al cuadro (con sus imágenes si tenía) | 064 |
| B10 | «guardá esta conversación en un archivo» | Modal → aviso con la ruta → el `.md` está en el Escritorio | 056 |
| B11 | Pedir algo lento e irte a otra ventana | Al terminar, aviso del sistema con la primera línea | 057 |
| B12 | Lo mismo con la ventana al frente | **No** llega ningún aviso | 057 |
| B13 | `Ctrl+F` en una conversación larga, buscar una palabra | Contador + resaltados; Enter salta entre hallazgos; Escape cierra | 058 |
| B14 | Buscar con acento y sin él | Mismo resultado | 058 |
| B15 | Preguntar algo que use herramientas, cerrar y reabrir el chat | Los pasos («2 pasos · Buscando en internet») siguen ahí | 059 |
| B16 | Subir con la rueda en un chat largo | Aparece «Ir al final»; click y baja | 060 |
| B17 | Quedarte arriba mientras responde | Dice «Nuevos mensajes» y **el chat no se mueve solo** | 060 |
| B18 | Pasar el mouse por un mensaje | La hora, al lado de «Copiar» | 060 |
| B19 | Guardar una captura en el Escritorio: «mirá la captura X y decime qué dice» | «1 paso · Mirando la imagen» + la descripción | 062 |
| B20 | Pedirle mirar una imagen de `C:\Windows` | Tiene que **negarse**: solo mira tu carpeta personal | 062 |

**Si B1/B4/B19 fallan diciendo que no ve imágenes:** es la clave de Gemini.
`vision_provider` está en `gemini` y necesita `GEMINI_API_KEY`, o cambiá el modelo en
Configuración → Modelos → «Ver imágenes».

---

## Bloque C — Linux (el equipo de tu amigo, ~30 min)

**Preparación:** que tenga Docker instalado y una sesión gráfica.

```bash
git clone https://github.com/johanrodriguezdev/agent-ia.git
cd agent-ia/agente_ia/docker
./orion.sh --construir     # tarda: descarga varios GB
./orion.sh
```

### C1 · Que abra la ventana ← si esto falla, lo demás no importa
- **Tiene que:** abrirse la ventana de O.R.I.O.N.
- **Si falla con `could not load the Qt platform plugin "xcb"`:** es permiso de pantalla.
  Probá `xhost +SI:localuser:$(id -un)` y volvé a lanzar.
- **Si falla con otra cosa:** mandame el mensaje completo. Verifiqué que QtWebEngine carga
  dentro de la imagen, así que un fallo acá es de la sesión gráfica, no del código.

### C2 · Que hable
Pegar una clave en Configuración → Conexiones y conversar.
- **Ojo:** el archivo queda en `docker/datos/config.json`, no dentro de la imagen.

### C3 · El PDF con LibreOffice
> «Hazme un informe en Word sobre X y pasalo a PDF»
- **Tiene que:** el PDF conserva el formato, y el agente dice **«convertido con LibreOffice»**
  (no «con Word»: eso sería el fallo que arreglé).

### C4 · La terminal del panel
- **Tiene que:** salir **tu shell** (bash o zsh), no PowerShell.

### C5 · Las acciones del sistema (REQ-068)
> «Cerrá Firefox» (con Firefox abierto) · «Abrí la carpeta de Descargas» · «Apagá el PC»
- Cerrar: tiene que cerrarse.
- Abrir: tiene que abrir el gestor de archivos **de su escritorio**.
- Apagar **dentro del contenedor**: tiene que **avisar que es un contenedor** y no apagarse.

### C6 · El navegador (REQ-069, cuando lo cierre)
> «Abrí es.wikipedia.org y decime de qué trata la página»
- **Tiene que:** abrir **su propia ventana** de Chromium, leerla y resumirla.
- **Esperado:** no son las pestañas del usuario y no tiene sus sesiones. Eso es la
  limitación de CDP, no un fallo.

### C7 · La trampa de Wayland
Si al arrancar el lanzador avisa «tu sesión es Wayland»: el chat, la voz y los documentos
funcionan igual, pero **mover el ratón, teclear en otras apps y capturar la pantalla no**.
Para eso hay que entrar en la sesión **Xorg** desde la pantalla de inicio.

---

## Qué mirar además, sin probar nada

**El CI en GitHub** → pestaña *Actions* del repositorio. Tiene que haber dos trabajos en
verde (Ubuntu y Windows) más la construcción de la imagen. **Si está rojo, decímelo**: es
información que yo no puedo ver desde acá y vale mucho.

---

## Cómo reportarme lo que falle

Con esto me alcanza para arreglarlo sin ida y vuelta:

1. **Qué pediste**, textual.
2. **Qué pasó** (y el archivo, si generó uno).
3. **Qué esperabas**.

Si es un documento, el archivo mismo vale más que la descripción.
