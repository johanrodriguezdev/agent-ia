# Baseline REQ-025

**Fecha:** 2026-09-07
**Agente:** orion-baseline

## Estado actual del sistema

`channels/discord_bot.py::_process_message()` existe hoy (líneas 56-76) y es el punto único de
entrada que traduce un mensaje de Discord (texto o imagen) al `GlassGateway` compartido con el
resto de canales:

```python
def _process_message(user_id: str, user_name: str, text: str, image_path: str = None) -> str:
    """Procesa un mensaje a través del Gateway de Glass."""
    try:
        from channels.gateway import GlassGateway, GlassMessage, MessageType
        msg_type = MessageType.IMAGE if image_path else MessageType.TEXT
        msg = GlassMessage(
            # Sin prefijo de canal: `user_id` ya llega resuelto por
            # `core.user_identity.canonical_user_id()`. Envolverlo aqui ("discord_owner")
            # devolvia al dueno a un espacio de memoria propio de Discord.
            user_id=user_id,
            user_name=user_name,
            text=text,
            channel="discord",
            msg_type=msg_type,
            image_path=image_path
        )
        gateway = GlassGateway()
        response = gateway.process(msg)
        return response.text
    except Exception as e:
        return f"Error procesando su solicitud: {str(e)[:100]}"
```

El `except Exception as e:` (línea 75) no registra nada con `logger` antes de retornar — el
`try` completo (instanciación de `GlassMessage`, `GlassGateway()`, `gateway.process(msg)`) queda
sin log de fallo. La línea 76 arma `f"Error procesando su solicitud: {str(e)[:100]}"` y ese
string se usa tal cual como valor de retorno de la función. Ese retorno llega sin transformación
a los dos call sites de `_process_message()`:

- `on_message()` (línea ~185): el resultado se trunca a `result[:4096]` y se coloca directo en
  `embed.description` (línea 202), visible para cualquiera en el canal/servidor de Discord.
- `slash_noddoo()` (línea ~219): mismo patrón — `result[:4096]` en `embed.description` (línea
  225), visible como respuesta del comando `/noddoo`.

Es decir: hoy, cualquier excepción interna (ruta de archivo, nombre de módulo, mensaje de
librería, credencial mal formada, etc.) que ocurra dentro de `gateway.process()` o al construir
`GlassMessage`/`GlassGateway` puede terminar, hasta 100 caracteres, expuesta textualmente en un
canal de Discord — sin que quede ningún rastro en los logs internos para diagnosticarla. Es el
mismo patrón de bug que `channels/gateway.py::process()` tenía antes de REQ-024 (ya corregido en
ese archivo hermano).

Confirmé además, leyendo el archivo completo, que los otros 6 bloques `except Exception` de
`discord_bot.py` (línea 52 en `_get_agent_name()`, 95-96 en `_slash_autorizado()`, 135-136 en
`on_ready()` al sincronizar comandos, 163-164 en `on_message()` al borrar el temporal de imagen,
195-198 en `slash_limpiar()`, y el bloque de `slash_ayuda`/comandos de solo lectura alrededor de
239-242) **no** comparten el patrón exacto que corrige este REQ: ya loguean antes de actuar, o no
devuelven `str(e)` crudo al canal, o no interactúan con Discord en absoluto. Esto coincide con lo
que ya había registrado `orion-spec` en SPEC-025.md — no hay alcance adicional que abrir.

## Archivos que serán modificados (previsión)

- `agente_ia/channels/discord_bot.py` — único archivo de producción a tocar: el bloque
  `except Exception as e:` de `_process_message()` (líneas 75-76 hoy), para agregar
  `logger.error(..., exc_info=True)` con `user_id`/`user_name`/canal="discord" y reemplazar el
  `return` por el texto genérico fijo, según el formato ya fijado en SPEC-025.md (idéntico en
  espíritu al fix de `channels/gateway.py::process()` de REQ-024).
- `agente_ia/tests/test_discord_bot.py` — **no existe hoy** (confirmado: no aparece en el listado
  de `agente_ia/tests/`). SPEC-025 lo deja como "nuevo si no existe hoy, a confirmar por
  orion-baseline" — queda confirmado: es un archivo nuevo, no una modificación. Su contenido
  deberá cubrir, como mínimo, los criterios de aceptación de SPEC-025 (log con `exc_info=True` y
  contexto de usuario, retorno sin fragmentos de `str(e)`, texto genérico exacto, camino feliz sin
  cambios).

Ningún otro archivo del repo referencia directamente el bloque `except` de `_process_message()`
que este REQ toca, así que no se prevén modificaciones fuera de estos dos.

## Fallos pre-existentes (no atribuibles a este REQ)

- **`python -m py_compile channels/discord_bot.py channels/gateway.py`** → sin errores, ambos
  compilan limpio.
- **`python -m pytest tests/ --tb=short -q`** (suite completa, 1788 tests) → **1788 passed, 0
  failed**, 100.88s. Ninguno pre-existente.
  - Advertencias presentes (no son fallos, no bloquean nada, ya existían antes de este REQ):
    - `DeprecationWarning` de `speech_recognition` por los módulos `aifc`/`audioop` (se eliminan
      en Python 3.13, aún no aplica en este entorno con Python 3.12).
    - `PytestReturnNotNoneWarning` en `tests/test_agents.py::test_ca1_orchestrator` (el test
      retorna un objeto en vez de solo usar `assert`).
    - `InconsistentVersionWarning` de `sklearn` al deserializar el clasificador TF-IDF/SVM
      (entrenado con scikit-learn 1.9.0, entorno actual con 1.8.0) — afecta a
      `tests/test_classifier.py` y `tests/test_classifier_confidence.py`, ambos pasan igual.
- **Conclusión:** no hay ningún fallo pre-existente en `channels/discord_bot.py`, `channels/gateway.py`,
  ni en el resto de la suite. Si `orion-tester` encuentra un FAIL después de la implementación de
  REQ-025, es atribuible al cambio de este REQ, no a algo que ya estuviera roto.

## Riesgos activos identificados para este REQ

- Ninguno de seguridad nuevo — es una corrección que **reduce** superficie de fuga de
  información, no la aumenta. El único riesgo operativo a vigilar en `orion-architect`/`orion-dev`
  es no tocar por error alguno de los otros 6 `except Exception` del archivo (fuera de alcance
  explícito, confirmado arriba línea por línea).
