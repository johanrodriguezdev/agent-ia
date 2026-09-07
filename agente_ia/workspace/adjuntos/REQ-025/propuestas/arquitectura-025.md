# Arquitectura REQ-025 — Logging y saneamiento del error filtrado a Discord en `_process_message()`

**Estado:** ✅ APROBADA (aprobado bajo autorización nocturna en bloque del 2026-09-06 — no es
revisión en vivo del usuario)
**Categoría:** SEGURIDAD
**Tipo:** BUG_FIX
**Fecha:** 2026-09-07

## Resumen para aprobación (beneficio, no solo lo técnico)
Hoy, si algo falla dentro de `_process_message()` de `channels/discord_bot.py` (construir el
`GlassMessage`, instanciar `GlassGateway` o `gateway.process(msg)`), el error (a) desaparece sin
dejar rastro en los logs internos — nadie puede diagnosticar qué pasó — y (b) hasta 100 caracteres
del texto crudo de la excepción de Python (que puede incluir rutas de archivo, nombres de módulo o
mensajes de librerías) se envían tal cual a Discord, visibles en el `embed.description` que ve
cualquiera en el canal o servidor. Esta arquitectura cierra ambos problemas en el único punto que
los tiene: el error queda registrado completo (con traceback y contexto del usuario) en el log
interno del proceso, y Discord recibe un mensaje genérico, con el mismo tono ya usado en
`gateway.py` tras REQ-024, sin ningún fragmento del error interno. No cambia nada del camino feliz
ni de los otros 6 bloques `except Exception` del archivo, ya verificados fuera de patrón por
`orion-baseline`.

## Cobertura de criterios de la SPEC

| Criterio (SPEC-025) | Cómo lo satisface esta propuesta |
|---|---|
| Log con `exc_info=True` y mensaje original de la excepción | `logger.error(f"Error en discord_bot._process_message() | usuario={user_id} ({user_name}) | canal=discord: {e}", exc_info=True)` insertado como primera línea del bloque `except` (línea 75 hoy), antes del `return`. |
| Log incluye `user_id` y `user_name` | Ambos parámetros ya llegan a la función (firma de `_process_message`, sin derivarse de nada que pueda fallar antes) y se interpolan directo en el mensaje del log, igual formato que `gateway.py::process()` (`usuario={message.user_id}`). |
| Retorno sin ningún fragmento de `str(e)` | El `f"Error procesando su solicitud: {str(e)[:100]}"` de la línea 76 se reemplaza por el literal fijo `"Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."`, sin interpolar `e`. |
| Texto genérico exacto | Se usa textualmente el mismo string ya aprobado en `gateway.py::process()` (REQ-024) — SPEC-025 lo fija así por ser el punto más análogo (entrada general de procesamiento, no un sub-flujo). |
| Ningún otro `except Exception` del archivo modificado | Esta propuesta toca únicamente las líneas 75-76 de `_process_message()`. Los otros 6 bloques (52, 95-96, 135-136, 163-164, 195-198, 239-242) no aparecen en ningún paso de esta arquitectura ni en el "Paso a paso mecánico" de abajo. |
| Camino feliz sin cambios | El cambio vive enteramente dentro del bloque `except`; el `try` (construcción de `GlassMessage`, `GlassGateway()`, `gateway.process(msg)`, `return response.text`) no se toca. |
| `python -m py_compile channels/discord_bot.py` sin errores | Cambio es una línea de log + un literal de texto dentro de un `except` existente — sintaxis trivial. Se verifica igual en `orion-dev`/`orion-tester`. |
| `pytest tests/` completo sin nuevos fallos vs. baseline (1788 passed) | Baseline confirmó que ningún otro módulo depende del contenido literal del mensaje de error actual. El nuevo `tests/test_discord_bot.py` se suma sin afectar los 1788 existentes. |

## Módulos a modificar
- `channels/discord_bot.py` — el bloque `except Exception as e:` de `_process_message()` (líneas
  75-76 hoy). Ningún otro bloque, método ni import del archivo cambia. No se agrega ningún import
  nuevo: `logger` ya está definido en la línea 36 (`logger = logging.getLogger(__name__)`) y usado
  en otros puntos del mismo archivo (líneas 92, 96, 164, 197) — el nuevo log reutiliza el mismo
  logger, mismo patrón que el resto del módulo.

## Nuevas clases/funciones
Ninguna. Este REQ no introduce clases, funciones ni métodos nuevos en producción — es una
corrección puntual de un bloque `except` ya existente. La única función nueva es de test (ver
"Pruebas sugeridas" abajo), no de producción.

## Flujo de datos
No cambia el flujo de datos del sistema (mensaje de Discord → `_process_message()` →
`GlassGateway.process()` → `response.text` → `embed.description` en `on_message()`/
`slash_noddoo()`). El único cambio de flujo es **dentro del camino de error** de
`_process_message()`, exclusivamente:

1. **Antes:** excepción capturada en el `except` de `_process_message()` → se construye
   directamente `f"Error procesando su solicitud: {str(e)[:100]}"` → ese string se retorna tal
   cual → llega sin transformación a `on_message()` (línea ~185) o `slash_noddoo()` (línea ~219) →
   se trunca a `result[:4096]` y se coloca en `embed.description` → visible para cualquiera en el
   canal/servidor de Discord.
2. **Después:** excepción capturada → `logger.error(mensaje_con_usuario_y_canal, exc_info=True)`
   registra el error completo (tipo, mensaje, traceback) en el log interno del proceso, que
   **nunca sale del proceso** → se retorna un texto genérico fijo (sin interpolar `e`) → ese texto
   sigue el mismo camino hacia `embed.description`, pero sin contenido interno.

El punto de bifurcación (dónde el dato deja de ser interno y pasa a ser observable por el canal
externo) no se mueve: sigue siendo el valor de retorno de `_process_message()`. Lo único que
cambia es qué contiene ese valor en el camino de error.

## Archivos a modificar/crear
- `channels/discord_bot.py` — modificar (el bloque `except` de `_process_message()`, ver "Paso a
  paso mecánico" abajo).
- `tests/test_discord_bot.py` — crear (confirmado inexistente por `orion-baseline`). Contenido
  detallado en "Pruebas sugeridas".

## Paso a paso mecánico (referencia directa para orion-dev)

### `_process_message()` — reemplazar líneas 75-76

```python
    except Exception as e:
        logger.error(
            f"Error en discord_bot._process_message() | usuario={user_id} ({user_name}) | "
            f"canal=discord: {e}",
            exc_info=True
        )
        return "Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."
```

No se toca ninguna otra línea de `channels/discord_bot.py` (imports, docstrings, firmas de
función, ni los otros 6 bloques `except Exception` de líneas 52, 95-96, 135-136, 163-164, 195-198
y 239-242).

## Dependencias nuevas
Ninguna. `logging` ya está importado (línea 28) y `logger` ya está instanciado (línea 36). No se
agrega ninguna entrada a `requirements.txt`.

## Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| Cambiar el texto de retorno rompe algún test que dependa del contenido literal actual | Baseline no encontró ningún test existente para `discord_bot.py` (el archivo `tests/test_discord_bot.py` no existe hoy) ni referencias externas al string actual. Riesgo residual nulo; se valida igual con la suite completa en `orion-tester`. |
| Tocar por error alguno de los otros 6 `except Exception` del archivo (fuera de alcance) | El "Paso a paso mecánico" de esta arquitectura delimita el cambio a las líneas 75-76 exactas. `orion-dev` debe hacer un `git diff` acotado a ese bloque antes de considerar terminado el REQ; `orion-tester`/`orion-qa` verifican que las líneas 52, 95-96, 135-136, 163-164, 195-198 y 239-242 quedan idénticas. |
| Mensaje de log muy largo si `str(e)` es grande | Aceptado: el log es interno, nunca sale del proceso. No se trunca — igual que en `gateway.py` tras REQ-024, la SPEC pide el mensaje completo para que sea accionable en debugging. |
| Alguien reintroduce `str(e)` en el texto devuelto al canal en un cambio futuro (regresión) | Los tests nuevos en `tests/test_discord_bot.py` (ver abajo) fuerzan una excepción con un mensaje distintivo y assertan que ese mensaje NO aparece en el string retornado — cualquier regresión futura que reintroduzca `str(e)` en el `return` rompe el test inmediatamente. |
| `user_id`/`user_name` no están poblados al momento del log | No aplica: son parámetros de la función (`_process_message(user_id, user_name, text, image_path=None)`), no derivados de nada dentro del `try` que pueda fallar antes de llegar al `except`. Siempre están disponibles, confirmado en SPEC-025 ("Casos borde"). |

## Pruebas sugeridas
`tests/test_discord_bot.py` no existe — se crea desde cero. Una prueba por cada criterio de
aceptación de SPEC-025, más los casos borde que la SPEC ya identificó. Estructura sugerida (sigue
`.claude/rules/testing.md`: pytest, sin red externa, con mocks):

```python
"""
tests/test_discord_bot.py
Cobertura REQ-025: logging + saneamiento del error filtrado en _process_message().
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

from channels.discord_bot import _get_agent_name, _process_message


class TestProcessMessageErrorHandling:
    def test_loguea_error_con_exc_info_y_contexto(self, caplog):
        """CA: logger.error con exc_info=True, incluye user_id, user_name, canal=discord."""
        with patch("channels.gateway.GlassGateway") as mock_gateway_cls:
            mock_gateway_cls.return_value.process.side_effect = RuntimeError(
                "fuga-interna-marca-XYZ"
            )
            with caplog.at_level(logging.ERROR):
                _process_message("u1", "Johan", "hola")
        assert any("fuga-interna-marca-XYZ" in r.message for r in caplog.records)
        assert any(r.exc_info for r in caplog.records)
        assert any(
            "usuario=u1" in r.message and "Johan" in r.message and "canal=discord" in r.message
            for r in caplog.records
        )

    def test_retorno_sin_fragmentos_del_error(self):
        """CA: el string retornado no contiene ningún fragmento de str(e)."""
        with patch("channels.gateway.GlassGateway") as mock_gateway_cls:
            mock_gateway_cls.return_value.process.side_effect = RuntimeError(
                "/ruta/absoluta/secreta/del/disco"
            )
            result = _process_message("u1", "Johan", "hola")
        assert "/ruta/absoluta/secreta/del/disco" not in result

    def test_texto_generico_exacto(self):
        """CA: el texto genérico devuelto es exactamente el fijado en SPEC-025."""
        with patch("channels.gateway.GlassGateway") as mock_gateway_cls:
            mock_gateway_cls.return_value.process.side_effect = ValueError("boom")
            result = _process_message("u2", "Ana", "algo")
        assert result == (
            "Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."
        )

    def test_camino_feliz_sin_cambios(self):
        """No-regresión: sin excepción, _process_message() retorna response.text normal."""
        mock_response = MagicMock(text="respuesta normal")
        with patch("channels.gateway.GlassGateway") as mock_gateway_cls:
            mock_gateway_cls.return_value.process.return_value = mock_response
            result = _process_message("u1", "Johan", "hola")
        assert result == "respuesta normal"

    def test_str_error_vacio_igual_loguea_con_exc_info(self, caplog):
        """Caso borde: str(e) vacío — el log igual muestra el tipo vía exc_info=True."""
        with patch("channels.gateway.GlassGateway") as mock_gateway_cls:
            mock_gateway_cls.return_value.process.side_effect = RuntimeError()
            with caplog.at_level(logging.ERROR):
                result = _process_message("u1", "Johan", "hola")
        assert any(r.exc_info for r in caplog.records)
        assert result == (
            "Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."
        )

    def test_user_name_con_caracteres_especiales_no_rompe(self):
        """Caso borde: user_name con emoji no rompe el log ni el retorno (f-string Unicode)."""
        with patch("channels.gateway.GlassGateway") as mock_gateway_cls:
            mock_gateway_cls.return_value.process.side_effect = RuntimeError("boom")
            result = _process_message("u3", "Ana 🎉", "hola")
        assert result == (
            "Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."
        )


class TestOtrosExceptSinModificar:
    def test_get_agent_name_no_modificado(self):
        """No-alcance: _get_agent_name() (línea 52) sigue devolviendo NODDOO por defecto en
        error, sin log nuevo — confirma que este REQ no tocó ese bloque."""
        with patch("config_manager.load_config", side_effect=RuntimeError("boom")):
            assert _get_agent_name() == "NODDOO"
```

Notas para `orion-dev`/`orion-tester`:
- El import de `GlassGateway`/`GlassMessage`/`MessageType` dentro de `_process_message()` es un
  import local (`from channels.gateway import ...` en tiempo de ejecución) — el `patch(...)` debe
  apuntar a `channels.gateway.GlassGateway` (el atributo del módulo origen), no a
  `channels.discord_bot.GlassGateway`, porque el símbolo se resuelve recién al llamar a la
  función. `GlassMessage` no se mockea: se instancia normal con los parámetros del test, ya que su
  construcción no es lo que falla en ningún escenario de prueba.
- Los `patch(...)` respetan `.claude/rules/testing.md` (sin red externa, sin `discord.py` real
  importado — solo se ejercita `_process_message()`, no `run_discord_bot()` ni los handlers
  `on_message`/`slash_noddoo`, que requerirían un cliente de Discord real).
- Además de estos tests nuevos, `orion-tester` debe correr `pytest tests/ --tb=short -v` completo
  y confirmar 1788+N passed, 0 failed (N = tests nuevos de este archivo), sin regresiones respecto
  al baseline documentado en `origen/baseline-025.md`.

## Aprobación de arquitectura
**APROBADO bajo autorización nocturna en bloque del 2026-09-06 — no es revisión en vivo del
usuario.** Encaja en el criterio de esa autorización: cambio mecánico acotado a un único bloque de
un archivo, reduce superficie de fuga existente sin abrir superficie nueva, sin dependencias
nuevas, sin tocar niveles 🔴 Rojo, y replica exactamente el patrón de fix ya aprobado por el humano
en REQ-024 para `channels/gateway.py`. A diferencia de REQ-023 (excluido de la autorización por
abrir un listener HTTP nuevo), REQ-025 no introduce ninguna superficie nueva.
