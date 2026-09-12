# Contexto REQ-034 — Índice semántico de código

## Resumen ejecutivo
Cierra el punto 1 de las mejoras de Johan ("programar de forma avanzada"): el verbo que
faltaba era **analizar proyectos grandes**. `code_index` construye un índice incremental del
repositorio y `code_search` busca **por significado**, no por texto exacto — preguntar
*"¿dónde está la lógica de facturación?"* y caer en `billing.py` aunque nadie haya escrito
nunca la palabra "factura".

## Estado actual
- **Estado tracker:** EN_PRUEBAS
- **Último agente:** conversación principal
- **Fecha última actualización:** 2026-09-09
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** CORE
- **Tipo de cambio:** FEATURE_NUEVA

## Origen
Johan eligió explícitamente el índice persistente sobre las alternativas más baratas
("solo mejorar la búsqueda actual"), y al retomar pidió que el resultado fuera **profesional**.
Eso se tradujo en cuatro exigencias concretas, no en adjetivos:

1. **Incremental de verdad**, o nadie lo actualiza nunca.
2. **Troceado que respeta el código**, o los fragmentos no significan nada.
3. **Medido**, no supuesto.
4. **Que no se coma la RAM ni el turno** en un repositorio grande.

## Cómo quedó

| Pieza | Decisión |
|---|---|
| Troceado | `ast` en Python: una función o una clase es un fragmento. Si el archivo no parsea —justo cuando lo estás arreglando— cae a ventanas de 30 líneas con 8 de solape |
| Tamaño | 1200 caracteres por fragmento: `all-MiniLM` trunca a 256 word-pieces, y un fragmento más largo se indexa por su principio y el resto es invisible |
| Incremental | `mtime` + tamaño + hash SHA-256 por archivo. Los borrados desaparecen con sus fragmentos (`ON DELETE CASCADE`) |
| Interrumpible | Tope de 60s por llamada; el estado vive en SQLite, así que continuar es volver a llamar |
| Secretos | `.env`, `id_rsa`, `*.pem` y compañía **no se indexan**: meterlos en un índice semántico es dejar la clave a una búsqueda de distancia |
| Búsqueda | Coseno vectorizado sobre una matriz numpy cacheada por raíz, invalidada al reindexar |
| Ranking | Máximo 2 fragmentos por archivo: sin eso, un módulo con docstring largo se lleva los ocho lugares |

## La medición, y lo que enseñó

**Primera medición (47 archivos reales de `core/`, modelo real):** 8 fragmentos/s, 92s.
Proyección a mil archivos: 33 minutos. Malo.

Dos hipótesis, y el perfilado por etapas dijo cuál era cuál:

```
1. recorrer el arbol      : 0.01s (47 archivos)
2. hash de cada archivo   : 0.23s
3. leer y trocear         : 0.20s (743 fragmentos)
4. embeddings             : 25.7s -> 29 fragmentos/s
   => el modelo es el 99% del tiempo total
```

- **La hipótesis del lote era correcta pero menor**: se pasó de embeber archivo por archivo
  (lotes de ~15) a juntar fragmentos de varios archivos hasta 256. Ayuda, pero no era el cuello.
- **La diferencia grande era contención de CPU**: las primeras mediciones corrieron con la
  suite de tests y la app del usuario encima. Con la máquina tranquila:

```
indexado real: 47 archivos, 743 fragmentos en 27.5s -> 27 frag/s
proyeccion 1000 archivos: 9.7 min
reindexar sin cambios: 0.07s
```

**Los números honestos:** entre 10 y 27 fragmentos/s según la carga del equipo; unos 10
minutos para un repositorio de mil archivos, **una sola vez**; y 0,07s para comprobar que no
cambió nada. La búsqueda: **11-24 ms**. La base: 2,4 MB para 743 fragmentos.

El benchmark quedó en `pruebas/benchmark-indice.py`, con el modelo cargado **antes** de
medir — si no, sus segundos se cuentan como indexado y la cifra sale tres veces peor.

## Decisiones tomadas
2026-09-09 | conversación principal | El texto que se embebe lleva adelante el archivo y el símbolo | Quien pregunta "el confinamiento de rutas" tiene más chance de dar con `workspace_files.py :: resolver` si esas palabras están EN el texto embebido
2026-09-09 | conversación principal | Máximo 2 fragmentos por archivo en los resultados | Medido: tres de cada cuatro consultas devolvían el encabezado de módulo en los tres primeros puestos
2026-09-09 | conversación principal | El embebedor se puede inyectar | Los tests usan una bolsa de palabras determinista: no cargan el modelo, no dependen de que esté descargado, y prueban ranking real y no "no explotó"
2026-09-09 | conversación principal | `code_search` no reemplaza a `file_search` | Buscar un nombre de función que ya sabés es exacto y no necesita índice. Son dos herramientas para dos preguntas distintas, y la descripción de cada una lo dice

## Riesgos activos
- **Indexar un repositorio enorme lleva minutos.** Está acotado (60s por llamada, se
  continúa), pero la primera vez sobre un repo grande son varias llamadas.
- La matriz vive en RAM mientras se busca: ~1,5 KB por fragmento. Un repositorio de 50.000
  fragmentos son ~75 MB. Aceptable, pero conviene saberlo antes de indexar un monorepo.

## Log de transiciones
2026-09-09 | — → EN_PRUEBAS | conversación principal | Índice, herramientas, 18 tests y benchmark medido dos veces
