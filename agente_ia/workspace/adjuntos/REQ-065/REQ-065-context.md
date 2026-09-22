# Contexto REQ-065 — Documentos, segunda vuelta: lo que falló al probarlo de verdad y el estilo guiado por el usuario

## Resumen ejecutivo
Johan pidió el 2026-09-21 validar el punto 4 de su lista (*"crear documentos, Excel y
presentaciones… siguiendo plantillas y estilos existentes, o guiados por el usuario"*,
REQ-040). Se validó **produciendo archivos reales** —plantilla Word con membrete y
marcadores partidos en runs, plantilla Excel con encabezado propio, presentación con tema,
PDF con Office y render a imagen— en vez de solo correr la suite (63 en verde). Lo central
funciona; salieron siete fallos concretos y una mitad del enunciado sin cubrir: sin
plantilla no había forma de pedir un aspecto ("Arial 11, títulos azules, logo, número de
página"). Johan aprobó corregir los fallos **y** agregar el estilo guiado (a + b).

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** SKILL | **Tipo:** MEJORA + FIX
- **Fecha:** 2026-09-21

## Origen
Validación en `origen/validacion-req040.py` (script que generó los archivos) y
`origen/antes-grafico-columna-equivocada.png` (el gráfico sobre plantilla graficando
*Cantidad* en vez de *Subtotal*). OpenClaw no tiene nada equivalente (solo docs de Feishu
en la nube): acá no hay "nivel OpenClaw" al que igualar.

## SPEC — criterios de aceptación

### (a) Fallos hallados
| # | Criterio | Cómo se comprueba |
|---|---|---|
| CA-01 | Una fórmula escrita en español (`=D5*0,19`, `=SI(B2>5;"alto";"bajo")`, `=SUMA(B2:B4)`, `=MÁX(...)`, `=REDONDEAR(x;2)`, `VERDADERO`) se guarda como Excel la entiende (`=D5*0.19`, `=IF(B2>5,"alto","bajo")`, `=SUM(...)`) | El .xlsx abre en Excel y calcula; test de `normalizar_formula` con esos casos y con fórmulas ya en inglés (no se tocan: `=ROUND(B5*1.19,2)` sigue igual) |
| CA-02 | Un gráfico sobre una plantilla Excel grafica la columna pedida por nombre y con su nombre de serie, aunque el encabezado no se reescriba | Test: plantilla con encabezado, `columnas: ["Subtotal"]` → la referencia de la serie apunta a la columna de Subtotal y la serie se llama "Subtotal" |
| CA-03 | `desde` respeta la columna (`C3` escribe desde C) y, si la plantilla ya tiene esos encabezados en esa fila o en la anterior, no los repite; los datos empiezan justo donde el modelo cree | Tests con `desde: "A5"` sobre plantilla con encabezado en la 4 (datos en la 5, sin duplicar) y con `desde: "C3"` |
| CA-04 | `document_edit` → `agregar` filas en una hoja con fila de totales las mete **antes** del total y la suma las incluye; las referencias de otras hojas al total siguen apuntando bien; las filas nuevas heredan el formato de la última fila de datos | Test: hoja con Total `=SUM(C2:C3)` + otra hoja con `=Clientes!C4` → tras agregar 1 fila: total en la 5 con `=SUM(C2:C4)`, referencia externa `=Clientes!C5` |
| CA-05 | Si tras rellenar una plantilla (Word o PowerPoint) quedan marcadores (`{{x}}`, `[FECHA]`) en cuerpo, tablas, encabezado o pie, **no se guarda**: se rechaza diciendo cuáles y dónde | Test: plantilla con `{{cliente}}` en el pie y contenido nuevo sin reemplazos → `DocumentoRechazado` que nombra `{{cliente}}` y "pie" |
| CA-06 | `agregar: {"despues_de": ..., "bloques": [...]}` (la forma "equivocada" pero natural) funciona igual que la documentada; y un `bloques` que sea un objeto sin sentido se rechaza en vez de escribir sus claves como párrafos | Tests de las dos formas |
| CA-07 | Al escribir un encabezado nuevo en una hoja de plantilla que ya tiene un encabezado con estilo, el nuevo copia ese estilo (relleno, fuente) en vez del azul fijo | Test: plantilla con encabezado verde en la fila 1 y hoja nueva con otros encabezados → relleno verde |

### (b) Estilo guiado por el usuario — parámetro `estilo`
| # | Criterio |
|---|---|
| CA-08 | `document_create` acepta `estilo` con `fuente`, `tamano`, `fuente_titulos`, `color_titulos`, `color_texto`, `margenes_cm` (número o `{superior, inferior, izquierdo, derecho}`), `orientacion` (`vertical`/`horizontal`), `encabezado`, `pie`, `logo` (+ `logo_ancho_cm`, `logo_posicion`), `numeracion` (número de página "Página N de M"), `justificado`, `interlineado`. Se aplica al .docx y, por tanto, al .pdf; en .html se aplican fuente y colores; en .md/.txt se avisa que no aplica |
| CA-09 | Colores: hex con o sin `#` y nombres en español (`azul`, `azul oscuro`, `verde`, `rojo`, `gris`, `naranja`, `morado`, `negro`); uno inválido se avisa y se ignora, no tumba el documento |
| CA-10 | `spreadsheet_create` acepta `estilo` con `fuente`, `tamano`, `color_encabezado`, `color_texto_encabezado`, `bordes` (bool); y cada hoja acepta `titulo` (fila de título combinada arriba del encabezado; el resultado dice en qué fila quedan encabezado y datos) |
| CA-11 | `presentation_create` acepta `estilo` con `fuente`, `color_titulos`, `color_texto`, `logo` (esquina superior derecha de cada diapositiva), `pie` (texto abajo a la izquierda) y `numeracion` (n / total abajo a la derecha) |
| CA-12 | `estilo` con una plantilla: se aplica **encima** de la plantilla (el usuario lo pidió explícitamente); sin `estilo`, nada cambia respecto a REQ-040 |
| CA-13 | Las tres herramientas del registro exponen `estilo` en su esquema y su descripción dice qué acepta; `spreadsheet_create` explica qué es `desde` y que las fórmulas pueden escribirse en español |

## Arquitectura (aprobada con la SPEC, en bloque)
Todo en `core/documentos.py`, tests en `tests/test_documentos.py`, esquemas en
`agents/tool_registry.py`. Sin dependencias nuevas.

- **Fórmulas** — `normalizar_formula(texto)` con `openpyxl.formula.tokenizer.Tokenizer`
  (no regex sobre el texto crudo: los `;` dentro de `"cadenas"` y las matrices `{1;2}` se
  respetan). Reglas: nombre de función → tabla `_FUNCIONES_ES` (sin tildes, mayúsculas);
  `;` separador → `,`; una `,` entre dos enteros es decimal si la fórmula lleva `;` o si
  está fuera de una función (`=D5*0,19`); dentro de una función y sin `;`, la `,` es
  separador (la fórmula venía en inglés). `VERDADERO`/`FALSO` → `TRUE`/`FALSE`. Se aplica
  en `_valor_de_celda`, que ya usan crear y editar.
- **Gráfico** — `_agregar_grafico` recibe los nombres de columna para buscar por nombre
  aunque no se escriban, y pone el nombre de serie con `SeriesLabel` en vez de
  `titles_from_data` (que dependía de que el encabezado estuviera justo arriba).
- **`desde`** — `_celda_a_indices("C3") → (3, 3)`. `_fila_de_encabezado_existente(ws,
  encabezados, columna, fila)` busca en `fila` y `fila-1` una fila cuyas celdas coincidan
  (sin tildes, sin mayúsculas) con al menos la mitad de los encabezados. Sin `desde`, se
  busca desde la última fila hacia arriba; si hay encabezado, datos debajo de la última
  fila sin repetirlo (comportamiento de REQ-040); si no lo hay, se escribe todo debajo.
  `_escribir_hoja` recibe `desde_columna` y aplica el desplazamiento a todo (totales,
  formatos, anchos, gráfico).
- **Agregar filas con totales** — `_fila_de_totales(ws)`: de abajo hacia arriba, la
  primera fila cuya primera celda con texto sea "Total"/"Totales" o que tenga una fórmula
  `SUM(`/`SUBTOTAL(`. Se insertan las filas ahí (`insert_rows`) y, como openpyxl **no**
  corrige fórmulas ni gráficos al insertar, `_desplazar_referencias(wb, hoja, desde_fila,
  cuantas)` recorre todas las fórmulas del libro (y las referencias de los gráficos de la
  hoja): las referencias a esa hoja con fila ≥ la insertada se corren, y los rangos que
  terminaban justo encima se extienden para abarcar lo nuevo. Formato: cada fila nueva
  copia el de la última fila de datos.
- **Marcadores restantes** — `_marcadores_restantes_docx(doc)` y `_marcadores_restantes_pptx(prs)`
  con `_MARCADOR_RE` (el mismo de `document_inspect`), después de reemplazar y antes de
  guardar, solo cuando hay plantilla. Se rechaza: un archivo con `{{cliente}}` impreso
  parece hecho y no lo está — mismo principio que el relleno.
- **Estilo** — `_estilo_de(spec)` normaliza claves (acepta `tamaño`/`tamano`,
  `márgenes`/`margenes_cm`), `_color_hex(valor)` resuelve nombres y hex.
  `_aplicar_estilo_docx(doc, estilo, avisos)`: `Normal` (fuente, tamaño, justificado,
  interlineado), `Title`/`Heading 1-4` (fuente y color de títulos), secciones (márgenes,
  orientación con intercambio de ancho/alto), encabezado/pie de texto, logo como imagen
  en el encabezado, numeración con campos `PAGE`/`NUMPAGES` (`fldChar`, python-docx no
  tiene API). `_estilo_encabezado_xlsx(...)` y `titulo` de hoja en `_escribir_hoja`.
  `_aplicar_estilo_pptx(prs, estilo, avisos)` sobre las diapositivas creadas: fuente y
  colores por run, logo/pie/número como formas añadidas (sobreviven a `ApplyTheme`, que
  solo toca el patrón).

## Decisiones tomadas
2026-09-21 | Johan | Corregir los siete fallos y agregar el estilo guiado (a + b) | Validación con archivos reales, no con la suite sola.
2026-09-21 | conversación principal | Marcadores restantes → rechazo, no aviso | Un archivo con `{{cliente}}` en el pie parece trabajo hecho; el modelo puede reintentar con `reemplazos` o preguntar.
2026-09-21 | conversación principal | Dentro de una función y sin `;`, la coma es separador | `=ROUND(B5*1.19,2)` es inglés legítimo; adivinar lo contrario rompería lo que ya funcionaba.
2026-09-21 | conversación principal | `titulo` de hoja desplaza la tabla (encabezado en la 3) y se informa | Ponerlo solo en el encabezado de impresión no se ve en la hoja; el desplazamiento se dice en el resultado y en el esquema.

## Archivos
- `core/documentos.py`: `normalizar_formula` + `_FUNCIONES_ES` + `_sin_tildes`;
  `_celda_a_indices`, `_fila_de_encabezado_existente`, `_celda_de_encabezado_con_estilo`,
  `_escribir_hoja` (columna de inicio, `titulo`, `estilo`, estilo copiado), `_agregar_grafico`
  (nombres + `SeriesLabel`), `_xlsx` (lógica de `desde`); `_marcadores_restantes_docx/pptx`;
  `_estilo_de`, `_color_hex`, `_margenes_de`, `_campo_de_word`, `_aplicar_estilo_docx`,
  `_aplicar_estilo_pptx`; `_fila_de_totales`, `_copiar_formato_de_fila`,
  `_desplazar_referencias`, `_insertar_filas_antes_del_total`; `_bloques_de` y
  `_editar_docx` tolerantes; `crear_documento`/`crear_hoja`/`crear_presentacion` con `estilo`.
- `agents/tool_registry.py`: `estilo` en las tres herramientas; descripciones de `desde`,
  fórmulas en español y rechazo por marcadores.
- `tests/test_documentos.py`: 37 tests nuevos (100 en total); uno de REQ-040 pasa de
  "se avisa" a "se rechaza" (CA-05).

## Qué puede hacer ahora (ejemplos)
- «Hazme el Excel de ventas con IVA» y el modelo escribe `=D5*0,19` o `=SI(...;...)` →
  el archivo abre y calcula (antes: Excel no lo abría, o `#¿NOMBRE?`).
- «Usá la plantilla de ventas de Documentos» → escribe debajo del encabezado verde de la
  plantilla sin repetirlo, el gráfico grafica *Subtotal* y no *Cantidad*, y el resultado
  dice «datos desde la fila 5» para que las fórmulas apunten bien.
- «Agregale a Vivero Los Pinos a la hoja de clientes» → entra antes de la fila Total, la
  suma lo incluye y la hoja Resumen sigue apuntando al total.
- «Hazme el informe en Arial 11, títulos en azul oscuro con Georgia, horizontal, con el
  logo arriba a la derecha, "Confidencial" en el pie y número de página» → sale así
  (`pruebas/despues-word-estilo.png`).
- «La presentación con letra Georgia, el logo en cada diapositiva y numeradas» →
  `pruebas/despues-pptx-estilo.png`.
- Si la plantilla trae `{{cliente}}` en el pie y no se le dio valor → no sale el archivo:
  «La plantilla quedó con marcadores sin rellenar: {{cliente}} (pie de página)».

## Qué no hace todavía
- Al insertar filas en Excel no se corrigen celdas combinadas ni formatos condicionales
  por debajo del total (sí fórmulas y gráficos).
- El estilo en PowerPoint va sobre las diapositivas creadas, no sobre el patrón: si
  después se agregan diapositivas con `document_edit`, esas no lo heredan.
- Un `.md`/`.txt` no lleva estilo (se avisa).

## Verificación
- `pruebas/suite-065.txt`: suite completa.
- `pruebas/revalidacion-office-real.py` + renders `despues-*.png`: con Word/Excel/PowerPoint
  reales (no simulados): Excel abre y calcula las fórmulas escritas en español, el
  gráfico sobre plantilla grafica la columna pedida, el total incluye la fila agregada.

## Prueba manual sugerida (Johan)
1. «Hazme una cotización con la plantilla de Documentos para Finca La Esperanza» sin dar
   la fecha: el agente debería preguntarla o decir qué marcador falta, no entregar un
   archivo con `[FECHA]`.
2. «Hazme un Excel con las ventas del mes, con IVA del 19 % y total» → abrirlo en Excel:
   sin diálogo de reparación y con los valores calculados.
3. «Hazme el informe en Arial 11, títulos verdes, horizontal y con número de página» →
   abrir el .docx y comprobar los cuatro.
4. «Agregale una fila a ese Excel» → la fila queda antes del Total y el total cambia.

## Log de transiciones
2026-09-21 | NUEVO → EN_DESARROLLO | conversación principal | Johan aprobó (a)+(b) tras la validación con archivos reales; spec y arquitectura en este contexto (pipeline acortado, como en las sesiones nocturnas).
2026-09-21 | EN_DESARROLLO → EN_PRUEBAS → EN_QA → LISTO_PARA_COMMIT | conversación principal | 100 tests de documentos en verde, suite completa en `pruebas/suite-065.txt`, revalidación con Office real. Prueba manual de Johan pendiente.
