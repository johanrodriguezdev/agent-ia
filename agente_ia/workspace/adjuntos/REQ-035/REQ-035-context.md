# Contexto REQ-035 — El índice se mantiene solo, y se puede refactorizar

## Resumen ejecutivo
Cierra dos de los "todavía no" que quedaron anotados al entregar REQ-034 y REQ-032. Johan
fue explícito: *"empieza a trabajar para que todo esté cubierto, no quiero que pares si no
está terminado"*.

1. **El índice ya no hay que mantenerlo a mano.** `code_search` refresca el índice antes de
   buscar. Comprobar que nada cambió cuesta **0,07s** (medido en REQ-034), así que pedirle
   al usuario que se acordara de reindexar era trasladarle un trabajo que la máquina hace
   sola.
2. **Se puede borrar y mover archivos.** Sin eso, el agente podía escribir código nuevo pero
   no reorganizar el que ya estaba — y eso es la mitad de un refactor.

## Estado actual
- **Estado tracker:** EN_PRUEBAS | **Categoría:** CORE | **Tipo:** MEJORA
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Fecha:** 2026-09-09

## Decisiones tomadas
2026-09-09 | conversación principal | El refresco va en la herramienta, no dentro de `buscar()` | `buscar()` es una función de búsqueda; que además escriba en la base sería mezclar responsabilidades y sorprender a quien la use desde otro lado
2026-09-09 | conversación principal | El refresco tiene tope de 20s | Si el repositorio es enorme y falta mucho, se busca con lo que hay y se avisa cuántos archivos faltan. Mejor un resultado parcial y honesto que 60s de espera
2026-09-09 | conversación principal | Solo se avisa del refresco cuando algo cambió | Un "[actualicé 0 archivos]" en cada búsqueda es ruido que el modelo tiene que leer todas las veces
2026-09-09 | conversación principal | `file_delete` no borra carpetas | Una carpeta entera es un riesgo de otra magnitud. Si alguien quiere vaciar un directorio, que sea archivo por archivo y que lo vea
2026-09-09 | conversación principal | `file_move` valida los DOS extremos | Validar solo el origen dejaría mover un archivo fuera de las carpetas permitidas: una forma elegante de sacar algo de donde estaba protegido
2026-09-09 | conversación principal | `file_move` no pisa un destino que ya existe | Perder un archivo por un renombre es de las cosas que no se notan hasta mucho después
2026-09-09 | conversación principal | **Borrar y mover quedan FUERA de la lista blanca del modo autonomía** | Escribir y editar se deshacen con git aunque el archivo sea nuevo; borrar y mover se deshacen **solo si el archivo estaba versionado**, y eso no lo sabe nadie a las 3 de la mañana. Se confirman siempre, aunque la autonomía esté encendida

## Verificación de punta a punta (con el modelo real)
```
1. buscar SIN haber indexado nunca  -> indexa solo y encuentra
   [Actualicé el índice antes de buscar: 1 nuevos, 0 cambiados, 0 borrados.]
2. agregar un archivo y buscar      -> aparece, sin reindexar a mano (0.1s)
3. buscar otra vez sin cambios      -> 0.02s
4. borrar un archivo                -> sale del índice solo
5. mover un archivo                 -> queda en el destino
```

## Log de transiciones
2026-09-09 | — → EN_PRUEBAS | conversación principal | Refresco automático, borrar y mover, 9 tests nuevos y verificación end-to-end
