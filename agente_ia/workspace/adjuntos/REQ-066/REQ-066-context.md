# Contexto REQ-066 — El aspecto también se cambia después, no solo al crear

## Resumen ejecutivo
REQ-065 dejó que el usuario pidiera el aspecto **al crear** un documento. Faltaba lo otro:
*"ponele el membrete a este informe"*, *"pasalo a horizontal con números de página"*,
*"ponele letra Arial"* sobre un archivo que ya existe. Este REQ abre `estilo` en
`document_edit` para Word, Excel y PowerPoint, y cierra los dos huecos que REQ-065 había
dejado anotados: las diapositivas agregadas no heredaban el estilo (y los números quedaban
desfasados), y al insertar filas no se corrían las celdas combinadas ni los formatos
condicionales.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** SKILL | **Tipo:** MEJORA
- **Fecha:** 2026-09-22

## Origen
Johan, 2026-09-22: «Continua», después de subir REQ-065 (`686c736`). Sus cuatro puntos
están cerrados, así que se siguió por los huecos que la propia entrega anterior dejó
anotados en «Qué no hace todavía», más el que apareció al usarlo: el aspecto solo se podía
decidir en el momento de crear.

## SPEC — criterios de aceptación
| # | Criterio |
|---|---|
| CA-01 | `document_edit` acepta `estilo` en `.docx` y lo aplica sin tocar una palabra del texto (fuente, tamaño, colores, márgenes, orientación, encabezado/pie, logo, numeración, justificado) |
| CA-02 | `estilo` **solo** ya es un cambio válido (no hace falta `cambios`); sin cambios ni estilo se rechaza nombrando las dos cosas |
| CA-03 | El `estilo` puesto dentro de `cambios` —donde el modelo lo pone la mitad de las veces— vale igual que el argumento aparte |
| CA-04 | En `.xlsx`, `fuente` y `tamano` van a lo que ya está escrito conservando negritas, y el tamaño **escala**: pedir «letra 10» en un libro de 11 deja el título de 16 en 14,5, no en 10 |
| CA-05 | En `.xlsx`, `color_encabezado` pinta la fila que parece el encabezado (la primera con dos o más textos, para no confundirla con un título de una sola celda) y el resultado dice cuál fue. Si no hay ninguna, se rechaza explicando el motivo en vez de guardar una copia idéntica |
| CA-06 | En `.pptx`, `estilo` se aplica a todas las diapositivas y **no duplica** logo ni pie si ya los tenía (las formas van marcadas con `ORION-estilo-`) |
| CA-07 | Una diapositiva agregada a una presentación con estilo **hereda** logo, letra, color de título, pie y número — el logo se saca del propio archivo, no hay ruta guardada |
| CA-08 | Agregar o quitar diapositivas **renumera** los «n / total» que puso un estilo: un número equivocado es peor que ninguno. También cuando se quita una y se agrega otra, que deja el mismo total pero corre todas las posiciones |
| CA-09 | Al insertar filas antes de la fila de totales, las celdas combinadas de más abajo se corren y los formatos condicionales se corren o se extienden para abarcar la fila nueva |
| CA-10 | La fila de totales se encuentra aunque haya una nota o una firma debajo de la tabla (se miran hasta 5 filas con contenido desde abajo); una tabla sin totales no inventa una |
| CA-11 | `document_edit` expone `estilo` en su esquema, ya no exige `cambios`, y su descripción dice para qué sirve |

## Arquitectura
Todo en `core/documentos.py` + el esquema en `agents/tool_registry.py`. Sin dependencias nuevas.

- **Marcado de las formas de estilo en PowerPoint** — `_MARCA_ESTILO = "ORION-estilo-"` en
  `shape.name` (`logo`, `pie`, `numero`). `_aplicar_estilo_pptx` empieza por
  `_quitar_formas_de_estilo(slide)`, así que reaplicar un estilo lo reemplaza en vez de
  apilarlo. La numeración usa la **posición real** de la diapositiva en la presentación
  (`slide_id` → índice), no su posición en la lista que se estila: al editar se tocan unas
  pocas y el «n / total» tiene que seguir siendo el de la presentación entera.
- **Herencia** — `_estilo_vigente_pptx(prs, hasta, carpeta_temporal)` lee de las
  diapositivas que ya están: el pie y la numeración de las formas marcadas, la fuente y los
  colores del título y del cuerpo (solo colores RGB; los del tema se dejan estar), y el
  logo **extrayendo la imagen del propio archivo** a un temporal. Por eso la aplicación
  ocurre dentro del `with tempfile.TemporaryDirectory()`.
- **Excel** — `_aplicar_estilo_xlsx(wb, estilo, avisos)`: fuente y tamaño celda por celda
  con `copy(celda.font)` (conserva negrita y color); el tamaño se multiplica por
  `pedido / tamaño_más_frecuente` y se redondea a medio punto, que es lo que conserva la
  jerarquía. `_fila_de_encabezado_visible(ws)` = la primera fila con ≥ 2 celdas de texto.
- **Insertar filas** — `_desplazar_combinadas` (unmerge + merge corrido) y
  `_desplazar_formatos_condicionales` (rangos corridos, y extendidos si terminaban justo
  encima de lo insertado), junto a lo que REQ-065 ya hacía con fórmulas y gráficos.
- **`_fila_de_totales`** — mira hasta `_FILAS_A_MIRAR_BUSCANDO_EL_TOTAL = 5` filas con
  contenido desde abajo, en vez de exigir que la de totales fuera la última.

## Decisiones tomadas
2026-09-22 | conversación principal | El tamaño de letra en Excel escala en vez de aplanar | «Letra 10» es el tamaño del cuerpo; dejar el título de 16 en 10 destruye una jerarquía que el usuario no pidió tocar.
2026-09-22 | conversación principal | La herencia recupera el logo extrayéndolo del archivo | Una diapositiva agregada sin logo se ve de inmediato que la pegó otro; y la ruta original no está guardada en ninguna parte.
2026-09-22 | conversación principal | Un estilo que no se pudo aplicar rechaza con el motivo | Guardar una copia idéntica diciendo «Listo» es el mismo error que el archivo con marcadores de REQ-065.
2026-09-22 | conversación principal | La numeración se recalcula sola al agregar o quitar diapositivas | Un «2 / 3» en una presentación de cuatro miente; ninguno sería mejor que eso. Se dispara por «hubo quitar o agregar», no por «cambió la cantidad»: quitar la primera y agregar una al final deja el mismo total y corre todo (hallado revisando el propio diff, con test de regresión).

## Qué puede hacer ahora
- «Ponele a este informe el membrete de la empresa, letra Arial, horizontal y numerado» →
  el texto queda igual, el aspecto cambia (`pruebas/despues-word-restilado.png`).
- «Agregale una diapositiva a la presentación» → sale con el mismo logo, la misma letra y
  el mismo pie que las demás, y se renumeran todas (`pruebas/despues-pptx-heredada.png`).
- «Ponele letra Calibri 10 y el encabezado en verde a esa hoja» → el cuerpo a 10, el título
  sigue más grande, el Total sigue en negrita.
- «Agregale una fila» a una hoja con total y una nota al pie → entra antes del total, la
  suma la incluye, la nota se corre y la regla de color abarca la fila nueva.

## Qué no hace todavía
- El estilo de PowerPoint va sobre las diapositivas, no sobre el patrón: una diapositiva
  agregada **a mano en PowerPoint** después no lo hereda (sí las que agrega el agente).
- Del estilo heredado no se recuperan los márgenes ni el tamaño de letra: se hereda lo que
  se ve (logo, letra, color, pie, número).
- En Word, restilar no redistribuye contenido: si el documento tenía saltos de página a
  mano, pasar a horizontal los deja donde estaban.

## Verificación
- `pruebas/suite-066.txt`: suite completa.
- `pruebas/validacion-office-real.py` y los `despues-*.png`: con Word y PowerPoint reales.
- 113 tests en `tests/test_documentos.py` (13 nuevos).

## Prueba manual sugerida (Johan)
1. Tomá un .docx tuyo cualquiera y pedí: «ponele letra Arial 11, títulos en azul oscuro y
   número de página». Abrilo: el texto intacto, el aspecto nuevo.
2. «Agregale una diapositiva sobre X» a una presentación que tenga logo: la nueva debe
   salir con el mismo logo y la misma letra, y todas renumeradas.
3. En una hoja con fila de Total, «agregale una fila»: tiene que entrar antes del Total.

## Log de transiciones
2026-09-22 | NUEVO → EN_DESARROLLO → LISTO_PARA_COMMIT | conversación principal | Spec y arquitectura en este contexto (pipeline acortado). 113 tests de documentos en verde, suite completa en `pruebas/suite-066.txt`, validación con Office real. Prueba manual de Johan pendiente.
