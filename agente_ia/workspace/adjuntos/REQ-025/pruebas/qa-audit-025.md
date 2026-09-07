# Auditoría QA REQ-025 — Logging y saneamiento del error filtrado a Discord en `_process_message()`

**Fecha:** 2026-09-07
**Agente:** orion-qa

Verificación **independiente** de código fuente (no se tomó como válido el reporte de
`orion-dev`/`orion-tester` sin comprobarlo): se releyó `channels/discord_bot.py` directamente, se
recreó `git diff`, se corrió `tests/test_discord_bot.py`, se contrastó carácter por carácter contra
`channels/gateway.py` (REQ-024, referencia de estilo obligatoria de este REQ), y se verificó longitud
de línea de cada línea nueva.

## Seguridad

- **Fuga de `str(e)` al canal externo (objetivo del REQ):** corregida y verificada. El bloque
  `except Exception as e:` de `_process_message()` (líneas 75-81 hoy) ya no interpola `e` en el
  valor retornado — el `return` es un literal fijo, sin `f-string`, sin `str(e)`. Confirmado
  leyendo el código:
  ```python
  except Exception as e:
      logger.error(
          f"Error en discord_bot._process_message() | usuario={user_id} ({user_name}) | "
          f"canal=discord: {e}",
          exc_info=True
      )
      return "Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."
  ```
- **El log sí registra el error real:** `logger.error(..., exc_info=True)` captura el traceback
  completo y el mensaje original de la excepción, con contexto de depuración (`user_id`,
  `user_name`, `canal=discord`). El log es interno (módulo `logging`), no sale del proceso ni llega
  a Discord — confirmado que no hay ningún `send`/`reply`/`embed` que reenvíe el contenido del log.
- **Secretos:** sin hallazgos. No se hardcodeó ningún API key/token en el cambio. El único uso de
  `DISCORD_BOT_TOKEN` en el archivo (línea 40, `os.environ.get(...)`) es código preexistente, fuera
  del diff de este REQ, y ya lee de variable de entorno correctamente.
- **Consistencia con REQ-024 (`channels/gateway.py`):** el texto genérico es **idéntico carácter
  por carácter** al usado en `GlassGateway.process()` (línea 105-115 de `gateway.py`):
  `"Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."` — tal
  como exigía SPEC-025. El formato del log también es consistente: mismo patrón
  `"Error en <origen> | usuario=... | canal=...: {e}"` con `exc_info=True`; la única diferencia
  (agregar `user_name` además de `user_id`) está documentada y justificada explícitamente en
  SPEC-025 ("Formato del log"), no es una divergencia accidental.

## Niveles de riesgo

- Verde (puede actuar): N/A — este REQ no agrega ninguna acción nueva del catálogo verde/amarillo/
  rojo, es un fix de logging/saneamiento de un `except` existente.
- Amarillo (debe confirmar): N/A — no aplica, no hay acción destructiva ni de canal externo nueva.
- Rojo (no ejecuta): N/A — no aplica.
- Se implementaron confirmaciones: N/A (no corresponde a este REQ; el cambio no introduce ninguna
  acción amarilla/roja nueva, solo reduce una fuga de información interna ya presente).

## Logging

- Sin `except: pass` ni `except Exception: pass` silencioso en el cambio. El único `except` tocado
  (líneas 75-81) ahora loguea antes de retornar — exactamente lo contrario de un `pass` silencioso.
- Los otros 6 bloques `except Exception` de `discord_bot.py` (líneas 52, 100-101, 140-141, 168-169,
  200-203, 244-247 hoy, equivalentes a 52, 95-96, 135-136, 163-164, 195-198, 239-242 antes del
  desplazamiento de +5 líneas que introduce este diff) se verificaron **sin cambios**, línea por
  línea, contra el estado documentado en `origen/baseline-025.md`. Confirmado con `git diff -- channels/discord_bot.py`:
  el hunk está acotado exactamente al bloque de `_process_message()` (5 líneas viejas → 10 líneas
  nuevas), no aparece ningún otro cambio en el archivo.

## Consistencia de código

- `python -m py_compile channels/discord_bot.py tests/test_discord_bot.py` → OK (verificado de
  forma independiente).
- `python -m pytest tests/test_discord_bot.py -q` → 7 passed (verificado de forma independiente).
- Alcance quirúrgico respetado: ningún otro `except Exception` del archivo fue tocado; el bloque
  `try` (camino feliz) tampoco cambió.
- Type hints: la firma de `_process_message()` no se modificó y ya tenía type hints completos; el
  cambio no agrega ninguna función/método nuevo en producción, así que no aplica type hints
  adicionales.
- Imports: no se agregó ningún import nuevo (`logging`/`logger` ya existían, confirmado en línea 36
  del archivo). No hay dependencias nuevas en `requirements.txt`.
- Sin `print()` de debug en el cambio nuevo.

### ❌ Hallazgo — longitud de línea excede el límite de `.claude/rules/python-style.md`

`.claude/rules/python-style.md` fija explícitamente: *"Longitud máxima de línea: 100 caracteres."*

La línea 81 de `channels/discord_bot.py` (el `return` del texto genérico) mide **102 caracteres**,
verificado con Python (`len(line.rstrip('\n'))`):

```python
        return "Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."
```

El propio archivo de referencia que SPEC-025 y arquitectura-025 exigen replicar para este REQ,
`channels/gateway.py::process()` (líneas 111-114), usa **el mismo texto exacto** pero lo parte en
dos líneas con concatenación implícita de strings precisamente para no violar este límite:

```python
            return GlassResponse(
                text="Lo siento, he encontrado un inconveniente inesperado. "
                     "Intente de nuevo en un momento.",
                speak=True
            )
```

`orion-dev` implementó el contenido correctamente (mismo texto, mismo tono, sin `str(e)`), pero no
replicó ese detalle de formato de `gateway.py` al ponerlo en una sola línea dentro de
`discord_bot.py`. No es un problema de seguridad ni de comportamiento — el texto es idéntico y
correcto — pero es una violación concreta y verificable de una regla de estilo explícita del
proyecto, en el mismo cambio cuya justificación (SPEC-025) es "consistencia con `gateway.py`".

**Fix sugerido (una línea, sin tocar nada más):**
```python
        return (
            "Lo siento, he encontrado un inconveniente inesperado. "
            "Intente de nuevo en un momento."
        )
```

## Veredicto: ❌ RECHAZADO

**Motivo concreto para `orion-dev`:** la línea 81 de `channels/discord_bot.py` (`return "Lo siento,
he encontrado un inconveniente inesperado. Intente de nuevo en un momento."`) mide 102 caracteres,
2 por encima del límite de 100 de `.claude/rules/python-style.md`. Partir el string en dos líneas
con concatenación implícita (igual que ya hace `gateway.py::process()`, líneas 111-114, con el
mismo texto) resuelve el hallazgo sin cambiar el contenido, el tono, el `logger.error(...)` ni
ningún otro bloque del archivo. No se requiere reejecutar `orion-architect`: es un ajuste de
formato dentro del "Paso a paso mecánico" ya aprobado, no un cambio de diseño. Tras el ajuste,
`orion-dev` debe volver a correr `python -m py_compile channels/discord_bot.py` y
`pytest tests/test_discord_bot.py -q` (deben seguir en 7 passed, el contenido del string no cambia,
solo su formato en el archivo fuente) y regenerar el diff acotado antes de reentregar a
`orion-tester`.

Todo lo demás auditado en este documento (seguridad, ausencia de secretos, logging con
`exc_info=True` y contexto, alcance quirúrgico, consistencia de contenido con `gateway.py`) está
correcto y no requiere cambios.

---

## Segunda vuelta — re-auditoría tras fix de formato

**Fecha:** 2026-09-07
**Agente:** orion-qa
**Motivo:** la primera vuelta rechazó únicamente por la línea 81 de `channels/discord_bot.py` (el
`return` del texto genérico), que medía 102 caracteres, 2 por encima del límite de 100 de
`.claude/rules/python-style.md`. `orion-dev` aplicó el fix sugerido (partir el string en varias
líneas con concatenación implícita, mismo patrón que `gateway.py::process()`) y `orion-tester`
volvió a dar PASS 9/9 de forma independiente (`pruebas/test-results-025.md`, sección "Segunda
vuelta"). Se re-audita desde cero, sin dar por buena ninguna de las dos verificaciones previas sin
comprobarlas directamente.

### Verificación independiente del hallazgo de estilo

Se leyó `channels/discord_bot.py` directamente (no el reporte de `orion-dev` ni el de
`orion-tester`) y se midió cada línea del bloque modificado con un script Python
(`len(line.rstrip('\n'))`), líneas 75 a 84:

```
75  26  '    except Exception as e:'
76  21  '        logger.error('
77  91  '            f"Error en discord_bot._process_message() | usuario={user_id} ({user_name}) | "'
78  34  '            f"canal=discord: {e}",'
79  25  '            exc_info=True'
80   9  '        )'
81  16  '        return ('
82  68  '            "Lo siento, he encontrado un inconveniente inesperado. "'
83  45  '            "Intente de nuevo en un momento."'
84   9  '        )'
```

Máximo del bloque: **91 caracteres** (línea 77, ya presente sin cambios desde la primera vuelta,
nunca fue el problema). Ninguna línea del bloque modificado supera el límite de 100. El hallazgo
que motivó el rechazo anterior queda **confirmado como resuelto**.

`return "Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."`
en una sola línea (102 caracteres, el hallazgo original) ya no existe en el archivo — fue
reemplazado por el `return (...)` de tres líneas con concatenación implícita mostrado arriba,
mismo patrón que `gateway.py::process()` (líneas 111-114), tal como se sugirió.

### Verificación de que contenido/logging/alcance no cambiaron

- `git diff -- channels/discord_bot.py` (contra HEAD) recreado de forma independiente: el único
  hunk sigue siendo el bloque `except Exception as e:` de `_process_message()` (líneas 73-84 hoy);
  ningún otro `except Exception` del archivo aparece en el diff. Alcance quirúrgico intacto.
- `logger.error(...)` (líneas 76-80): carácter por carácter idéntico al de la primera vuelta —
  `exc_info=True`, contexto `usuario={user_id} ({user_name})` y `canal=discord`, sin `str(e)` en el
  valor retornado al canal. El fix de formato no tocó el logging.
- Texto genérico retornado: concatenando las líneas 82-83 el literal resultante es
  `"Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."` —
  idéntico carácter por carácter al de la primera vuelta y a `gateway.py` (REQ-024). La
  concatenación implícita no introdujo ni omitió ningún espacio (mismo resultado que verificó
  `orion-tester` vía AST).
- No hay `str(e)` interpolado en ningún `return` del bloque: sin fuga de información interna al
  canal externo, que era el objetivo original de seguridad del REQ.
- Secretos: sin hallazgos nuevos. Sin cambios respecto a la primera vuelta.
- Niveles de riesgo verde/amarillo/rojo: no aplica, sin cambios respecto a la primera vuelta (este
  REQ no agrega ninguna acción nueva del catálogo).

### Verificación de ejecución (independiente, no confiada al reporte)

```
python -m py_compile channels/discord_bot.py
→ COMPILE OK

python -m pytest tests/test_discord_bot.py -q
→ 7 passed in 0.56s
```

Sin regresiones ni cambios de comportamiento en los tests — coincide con lo reportado por
`orion-tester` en la segunda vuelta.

### Consistencia de código — segunda vuelta

- Ningún `except: pass` ni `except Exception: pass` silencioso. Sin cambios respecto a la primera
  vuelta.
- Sin `print()` de debug. Sin imports nuevos. Sin dependencias nuevas.
- El fix de formato no introdujo ningún problema nuevo: no cambió el nombre de ninguna variable, no
  tocó la firma de `_process_message()`, no afectó a los otros 6 `except Exception` del archivo, y
  no dejó código muerto ni comentarios sobrantes.

## Veredicto (segunda vuelta): ✅ COMPLETADO

El único motivo de rechazo de la primera vuelta (línea de 102 caracteres) está verificado como
resuelto de forma independiente: ninguna línea del bloque modificado supera 100 caracteres. El
contenido, el tono, el `logger.error(...)` y el alcance quirúrgico siguen siendo exactamente los
que ya se habían aprobado como correctos en la primera vuelta de esta auditoría. No se introdujo
ningún problema nuevo de seguridad, logging o consistencia.

`orion-qa` aprueba REQ-025. Queda pendiente la prueba manual del humano antes de mover el tracker a
`LISTO_PARA_COMMIT` y antes de entregar el mensaje de commit sugerido.
