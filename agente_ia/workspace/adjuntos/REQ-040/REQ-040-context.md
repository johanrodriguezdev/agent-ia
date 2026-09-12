# Contexto REQ-040 — Crear documentos de verdad: Word, Excel, PowerPoint, PDF y lo demás

## Resumen ejecutivo
Punto 4 de la lista de Johan: *"Crear documentos, Excel y presentaciones: no solamente
texto, debe producir artefactos completos siguiendo plantillas y estilos existentes. Que
pueda crear cualquier archivo —docx, pdf, excel, presentaciones y cualquier otra
extensión— pero no información vacía: tiene que hacerlo completo."*

## Estado actual
- **Estado tracker:** EN_PRUEBAS | **Categoría:** SKILL | **Tipo:** FEATURE_NUEVA
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo` | **Fecha:** 2026-09-12

## Qué había
El agente escribía texto plano (`file_write`, `write_file_direct`) y leía documentos de
Office (`FileAnalysisSkill`), pero no podía *producir* uno: "hazme el informe en Word"
terminaba en un `.txt` en el Escritorio. Y menos seguir una plantilla.

## Cómo se reparte el trabajo
El modelo escribe el contenido —**todo** el contenido— como una estructura, y
`core/documentos.py` lo convierte en un archivo bien formado. Es la misma división que en el
resto del proyecto: la inteligencia en el modelo, la mecánica acá.

| Herramienta | Produce | Nivel |
|---|---|---|
| `document_create` | `.docx`, `.pdf`, `.md`, `.html`, `.txt` — título, encabezados, párrafos, listas con subniveles, tablas, imágenes, citas, saltos | 🟡 |
| `spreadsheet_create` | `.xlsx`, `.csv` — varias hojas, encabezado con formato, fórmulas, fila de totales, formatos por columna, gráfico de barras/líneas/torta, filtro y panel fijo | 🟡 |
| `presentation_create` | `.pptx` y su `.pdf` — portada, viñetas con subniveles, tablas, imágenes, notas del orador, tema de diseño de Office | 🟡 |
| `file_create` | cualquier otra extensión: `.json` con sangría, `.sql`, `.py`, `.yaml`… | 🟡 |
| `document_inspect` | qué estilos, hojas, diseños, encabezados y marcadores tiene una plantilla | 🟢 solo escritorio |
| `document_to_pdf` | un `.docx`/`.xlsx`/`.pptx` existente a PDF con el propio Office | 🟡 |

## "No información vacía": lo que se rechaza
Un documento con marcadores de relleno **no se produce**: `lorem ipsum`, `[insertar aquí]`,
`por definir`, `{{...}}` en el contenido del modelo, `TODO`. Y un "documento" que es un
título sin nada debajo, una hoja sin filas o una presentación de puros títulos tampoco. El
motivo vuelve al modelo en palabras que le piden el contenido real. Un archivo con huecos
parece trabajo hecho y no lo es: peor que ningún archivo.

## Plantillas — el corazón del punto
Se abre el archivo de plantilla y se escribe **dentro** de él, así que conserva sus estilos,
encabezados, pies, márgenes, tema y patrones. Dos maneras, combinables:

- **`reemplazos`**: la plantilla trae marcadores —`{{cliente}}`, `[FECHA]`— y se sustituyen
  conservando el formato del texto que estaba, también dentro de tablas, encabezados y
  pies. Es lo que se hace con una cotización. Word parte el texto en "runs" según el
  formato y un marcador puede quedar repartido en tres: se sustituye sobre el párrafo entero
  y se reescribe en el primer run, que conserva su fuente.
- **contenido nuevo**: se vacía el cuerpo (nunca encabezados ni pies) y se escribe con los
  estilos que la plantilla define. Probado: el `Heading 1` del informe salió con el verde
  corporativo de la plantilla.

`document_inspect` va antes: lista estilos, membrete, hojas, diseños y marcadores, para
seguir la plantilla en vez de adivinarla.

## PDF
Con Office —como en esta máquina— se convierte con el propio Word, Excel o PowerPoint en
una instancia propia e invisible (`DispatchEx`): nunca la que el usuario tenga abierta. Es
la única forma de que el PDF se vea exactamente igual. Sin Office, un documento se maqueta
con PyMuPDF (`Story`); una hoja o una presentación no tienen ese respaldo y se dice.

## Lo que salió de mirar los archivos, no de suponerlos
- **El tema de la presentación.** python-pptx produce el blanco 4:3 de 2003. Sin plantilla,
  se aplica un tema de diseño de los 24 que trae Office (`Retrospect` por defecto, o el que
  se pida), con PowerPoint. Y 16:9.
- **La tabla montada sobre el título.** A una altura fija, en `Retrospect` la tabla tapaba
  el título. Todo lo que no va en un marcador se coloca debajo de donde termine el título.
- **"870.000" leído como 870.** La primera versión leía a la inglesa. En español el punto
  seguido de tres dígitos es de miles y la coma es el decimal; una hoja de costos quedó con
  ochocientos setenta pesos donde iban ochocientos setenta mil. Corregido y fijado por test.
- **La leyenda del gráfico cortada** al imprimir: va abajo.

## Dónde quedan
En el Escritorio, salvo otra carpeta dentro de la carpeta personal o de un espacio de
trabajo habilitado. Ni `AppData`, ni `.ssh`, ni fuera de ahí. **Nunca se pisa un archivo
existente**: `informe (2).docx`, como hacen los adjuntos de correo.

## Seguridad
- Crear un archivo es 🟡, como `write_file_direct` y `file_write`. La confirmación muestra
  el nombre, la plantilla y la carpeta (`nombre`, `plantilla`, `carpeta` en
  `_DETAILS_ALLOWED_KEYS`).
- `document_inspect` es 🟢 pero **solo escritorio**: lee encabezados y primeros párrafos de
  un archivo del usuario, por lo mismo que `file_read`.
- Ninguna está en la lista blanca del modo autonomía. Johan decide si la suma.

## Dependencias nuevas
`python-pptx` (nuevo). `python-docx`, `openpyxl`, `pymupdf` y `pywin32` ya estaban.

## Segunda entrega (2026-09-12) — lo que "no hacía", cerrado

| Antes | Ahora |
|---|---|
| No editaba un documento existente | `document_edit` 🟡: en Word reemplaza conservando formato, agrega bloques **después del párrafo que se pida** y quita párrafos; en Excel escribe celdas (`Hoja!B4`), agrega filas y reemplaza; en PowerPoint reemplaza, quita diapositivas por título o número y agrega. Por defecto deja el original intacto (`informe (2).docx`); `en_sitio` sobrescribe |
| No dibujaba gráficos en Word ni PowerPoint | Bloque `grafico` (barras, líneas, torta; varias series). En PowerPoint es **nativo y editable**; en Word y en el PDF sin Office, una imagen limpia con las cifras a la colombiana. La torta lleva porcentajes |
| Sin Office, hoja y presentación no iban a PDF | Se maquetan apaisadas con PyMuPDF. Las **fórmulas sencillas se calculan** —sumas, restas, SUMA, PROMEDIO, MÍN, MÁX— con un evaluador propio (nunca `eval`), y lo que no se sabe calcular se muestra escrito y se avisa |

### Región, no país fijo
Johan lo pidió pensando en otro país mañana. `"870.000"` es ochocientos setenta mil en
Colombia y 870 con decimales en Estados Unidos; México escribe a la inglesa. Ahora la
convención numérica y el separador del CSV salen de `region` en la configuración
(`es-CO` por defecto): `config_manager.get_region()`. Es el primer ajuste regional; el
multiidioma completo —respuestas, interfaz, voz— es un análisis aparte.

### Tres fallos que solo aparecieron ejecutándolo
- **python-docx inserta antes del `sectPr` final**, así que "lo nuevo a partir del índice N"
  era solo el `sectPr` y el contenido quedaba al final en vez de tras el ancla. Lo nuevo se
  reconoce por identidad, no por posición.
- **python-pptx nombra una diapositiva nueva por cantidad** (`slide{n+1}`), no mirando qué
  nombres existen: tras borrar la 2 de tres, la nueva se llamaba `slide3.xml` y chocaba con
  la 3. El archivo salía corrupto («Cierre» desaparecía). Se renumeran las partes al borrar.
- **openpyxl en modo normal no suelta el archivo con `close()`**, solo al recolectar el
  objeto; en Windows eso bloqueaba la carpeta temporal. Las lecturas van en modo solo
  lectura, que sí lo suelta.

## Lo que NO hace
- No convierte a PDF con el tema una presentación sin PowerPoint (sale maquetada en limpio).
- No inserta gráficos nativos en Word (son imagen; en Excel y PowerPoint sí son nativos).
- La región se cambia en `config.json` (`"region": "en-US"`); no tiene ajuste en la pantalla
  de configuración todavía.

## Pendiente
- Prueba manual de Johan: *"hazme una cotización con la plantilla de Documentos"*.
