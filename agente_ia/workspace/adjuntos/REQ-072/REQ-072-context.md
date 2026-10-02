# Contexto REQ-072 — Errores que se entienden (§12 de la especificación)

## Resumen ejecutivo
58 sitios devolvían la excepción cruda pegada a una frase (`f"No pude abrir Spotify: {e}"`),
así que el usuario leía «[WinError 5] Acceso denegado» o rutas completas de su propio disco.
La §12 de la especificación pide lo contrario: el mensaje explica **qué pasó y por qué**, y
el detalle técnico queda disponible solo si lo piden.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** CORE | **Fecha:** 2026-10-02

## Qué se hizo
- **`core/errores.py`**: `causa(e)` traduce la excepción a castellano llano —por tipo
  primero, que es lo más fiable, y por código (`winerror`/`errno`) después—; `explicar(e,
  intento)` arma la frase para el usuario y manda el detalle completo al log con
  `exc_info`; `detalle_tecnico(e)` es lo que se entrega si lo piden, en una línea y no en
  un volcado de pila.
- **Aplicado en 23 sitios**, los que se tocan a diario: abrir programas y el navegador, la
  terminal, el teclado y el clic, el correo (recuperar, marcar leído, guardar adjuntos,
  revisar), los archivos y el disco, las capturas de pantalla y la calculadora.
- Quedan 36 sitios en caminos menos frecuentes; el patrón está listo para ellos.

## La regla que más importa
**Lo que no se reconoce NO se inventa.** Decir «parece un problema de permisos» sin saberlo
manda al usuario a buscar donde no es; se nombra el tipo de error, que es un dato real y
corto. Está fijado por test.

## Antes y después
| Antes | Ahora |
|---|---|
| `No pude abrir Spotify: [WinError 5] Acceso denegado` | `No pude abrir Spotify: no tengo permisos para hacerlo.` |
| `Error al crear el archivo: [Errno 28] No space left on device` | `No pude crear el archivo: no queda espacio en el disco.` |
| `No pude guardar «x.pdf»: [Errno 2] ... 'C:\Users\Johan\...'` | `No pude guardar «x.pdf»: no encuentro el archivo.` |

## Verificación
- `tests/test_errores.py`: 19 tests — cada tipo de fallo, los códigos del sistema, que no
  se inventen causas, que el mensaje no lleve rutas ni volcados, y que el detalle sí quede
  en el log.
- `pruebas/suite-072.txt`: suite completa.

## Prueba manual sugerida (Johan)
1. Pedile abrir algo sobre lo que no tenga permisos: el mensaje debe explicar la causa sin
   `WinError` ni rutas de tu disco.
2. Pedile el detalle técnico después: ahí sí debe darlo, en una línea.

## Log de transiciones
2026-10-02 | NUEVO → LISTO_PARA_COMMIT | conversación principal | Documentado junto a REQ-071.
