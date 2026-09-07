# Arquitectura REQ-024 — Logging y saneamiento de errores filtrados al canal externo en `channels/gateway.py`

**Estado:** ✅ APROBADA (aprobado bajo autorización nocturna en bloque del 2026-09-06 — no es
revisión en vivo del usuario)
**Categoría:** SEGURIDAD
**Tipo:** BUG_FIX
**Fecha:** 2026-09-07

## Resumen para aprobación (beneficio, no solo lo técnico)
Hoy, si algo falla dentro de `GlassGateway.process()`, `_ask_claude_for_user()` o
`_handle_screenshot()`, el error (a) desaparece sin dejar rastro en los logs — nadie puede
diagnosticar qué pasó — y (b) el texto crudo de la excepción de Python (que puede incluir rutas
absolutas del disco del usuario, nombres de archivo internos, etc.) se envía tal cual por
Telegram o Discord como si fuera una respuesta normal. Esta arquitectura cierra ambos problemas
en los tres puntos: cada error queda registrado completo (con traceback) en el log interno del
proceso, y el usuario recibe un mensaje genérico y con el mismo tono que ya usa el resto del
archivo, sin ningún fragmento del error interno. No cambia nada del camino feliz ni del
comportamiento observable cuando no hay errores.

## Cobertura de criterios de la SPEC

| Criterio (SPEC-024) | Cómo lo satisface esta propuesta |
|---|---|
| Log completo (`exc_info=True`) + mensaje original en `process()` | `logger.error(f"Error en GlassGateway.process() | usuario={message.user_id} | canal={message.channel}: {e}", exc_info=True)` insertado como primera línea del bloque `except` (línea 105), antes de construir la respuesta. |
| `GlassResponse.text` de `process()` sin fragmentos de `str(e)` | El `f-string` de la línea 107 se reemplaza por el literal fijo `"Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."`, sin interpolar `e`. |
| Log completo en `_ask_claude_for_user()` | `logger.error(f"Error en GlassGateway._ask_claude_for_user() | usuario={message.user_id} | canal={message.channel}: {e}", exc_info=True)` como primera línea del bloque `except` (línea 135), antes de la guarda del `pop()` existente. |
| Retorno de `_ask_claude_for_user()` sin fragmentos de `str(e)` | El `return` de la línea 138 pasa de `f"Error en inteligencia conversacional: {str(e)}"` a literal fijo `"Lo siento, no pude procesar esa solicitud en este momento. Intente de nuevo."` |
| Log completo en `_handle_screenshot()` | `logger.error(f"Error en GlassGateway._handle_screenshot() | usuario={session.user_id} | canal={session.channel}: {e}", exc_info=True)` como primera línea del bloque `except` (línea 163). |
| `GlassResponse.text` de `_handle_screenshot()` sin fragmentos de `str(e)`, conservando `vocative()` | El `f-string` de la línea 165 pasa de `f"No pude tomar la captura{vocative()}: {str(e)[:60]}"` a `f"No pude tomar la captura{vocative()}. Intente de nuevo en un momento."` — se mantiene la interpolación de `vocative()`, se elimina la de `str(e)`. |
| `_save_semantic()` intacto (no-regresión) | No se toca ninguna línea de `_save_semantic()` (169-175). Sigue usando `logger.warning(f"Error guardando memoria semántica: {e}")` sin cambios. |
| Camino feliz sin cambios | Ningún cambio de esta propuesta toca código fuera de los tres bloques `except`; los `try` y todo lo anterior a cada `except` quedan idénticos. |
| `python -m py_compile channels/gateway.py` sin errores | Cambios son solo dentro de bloques `except` existentes (una línea de log + un literal de texto) — sintaxis trivial, sin riesgo de romper compilación. Se verifica en `orion-dev`/`orion-tester` igualmente. |
| `pytest tests/` completo sin nuevos fallos vs. baseline (1779 passed) | Ningún otro módulo depende del contenido literal de estos tres mensajes (confirmado en baseline-024.md). El nuevo `tests/test_gateway.py` se suma sin afectar los 1779 existentes. |

## Módulos a modificar
- `channels/gateway.py` — los tres bloques `except Exception` de `process()` (líneas 105-109),
  `_ask_claude_for_user()` (líneas 135-138) y `_handle_screenshot()` (líneas 163-167). Ningún
  otro método ni import del archivo cambia. No se agrega ningún import nuevo: `logger` ya está
  definido en la línea 13 (`logger = logging.getLogger(__name__)`) y usado en `_save_semantic()`
  — los tres puntos nuevos reutilizan el mismo logger, mismo patrón.

## Nuevas clases/funciones
Ninguna. Este REQ no introduce clases, funciones ni métodos nuevos — es una corrección puntual
de tres bloques `except` ya existentes. No aplica sección de nuevas clases/funciones más allá de
lo declarado abajo en pruebas (donde sí se crean funciones de test, no de producción).

## Flujo de datos
No cambia el flujo de datos del sistema (entrada de mensaje → clasificación/resolución → memoria
→ respuesta). El único cambio de flujo es **dentro del camino de error**, exclusivamente:

1. **Antes:** excepción capturada → se construye directamente un texto que interpola `str(e)` →
   ese texto sale como `GlassResponse.text` (o como `str` en `_ask_claude_for_user()`, que luego
   `process()` reenvía igual como `GlassResponse.text` en la línea 103) → llega crudo al canal
   externo (Telegram/Discord) vía `discord_bot.py:73` o los múltiples puntos de
   `telegram_bot.py`.
2. **Después:** excepción capturada → `logger.error(mensaje_con_usuario_y_canal, exc_info=True)`
   registra el error completo (tipo, mensaje, traceback) en el log interno del proceso, que
   **nunca sale del proceso** → se construye un texto genérico fijo (sin interpolar `e`) → ese
   texto sale como `GlassResponse.text`/`str` → llega al canal externo igual que antes, pero sin
   contenido interno.

El punto de bifurcación (dónde el dato deja de ser interno y pasa a ser observable por el canal
externo) no se mueve: sigue siendo el valor de retorno de cada método. Lo único que cambia es qué
contiene ese valor en el camino de error.

## Archivos a modificar/crear
- `channels/gateway.py` — modificar (los tres bloques `except`, ver Paso a paso abajo).
- `tests/test_gateway.py` — crear (no existe hoy). Contenido detallado en "Pruebas sugeridas".

## Paso a paso mecánico (referencia directa para orion-dev)

### 1. `GlassGateway.process()` — reemplazar líneas 105-109
```python
        except Exception as e:
            logger.error(
                f"Error en GlassGateway.process() | usuario={message.user_id} | "
                f"canal={message.channel}: {e}",
                exc_info=True
            )
            return GlassResponse(
                text="Lo siento, he encontrado un inconveniente inesperado. "
                     "Intente de nuevo en un momento.",
                speak=True
            )
```

### 2. `GlassGateway._ask_claude_for_user()` — reemplazar líneas 135-138
```python
        except Exception as e:
            logger.error(
                f"Error en GlassGateway._ask_claude_for_user() | usuario={message.user_id} | "
                f"canal={message.channel}: {e}",
                exc_info=True
            )
            if session.conversation_history and session.conversation_history[-1]["role"] == "user":
                session.conversation_history.pop()
            return "Lo siento, no pude procesar esa solicitud en este momento. Intente de nuevo."
```
Nota: la guarda del `pop()` se preserva sin cambios, tal como fija la SPEC — solo cambia el orden
(el log va primero, ya que no depende de la guarda) y el `return` final.

### 3. `GlassGateway._handle_screenshot()` — reemplazar líneas 163-167
```python
        except Exception as e:
            logger.error(
                f"Error en GlassGateway._handle_screenshot() | usuario={session.user_id} | "
                f"canal={session.channel}: {e}",
                exc_info=True
            )
            return GlassResponse(
                text=f"No pude tomar la captura{vocative()}. Intente de nuevo en un momento.",
                speak=True
            )
```

No se toca ninguna otra línea de `channels/gateway.py` (imports, `_save_semantic()`, docstrings,
firmas de método).

## Dependencias nuevas
Ninguna. `logging` ya está importado (línea 6) y `logger` ya está instanciado (línea 13). No se
agrega ninguna entrada a `requirements.txt`.

## Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| Cambiar el texto de retorno rompe algún test que sí dependa del contenido literal | Baseline confirmó (grep exhaustivo) que ningún test ejercita el cuerpo real de estos tres métodos hoy — todos los tests de `test_telegram_bot.py` mockean `.process()` completo. Riesgo residual bajo; se valida igual con la suite completa en `orion-tester`. |
| El nuevo `logger.error(..., exc_info=True)` en `_ask_claude_for_user()` se dispara también en el caso borde de lista vacía en el `pop()` — no, ese caso ya no llega al `except` porque está protegido por `if` | No aplica: la guarda `if session.conversation_history and ...` ya evita el `IndexError`/`KeyError`, no está dentro de un `try` anidado. El `logger.error` del `except` externo solo se dispara por la excepción original de `ask_claude()`, igual que hoy. Sin cambio de comportamiento en ese punto. |
| Mensajes de log muy largos si `str(e)` es grande (p. ej. tracebacks de librerías verbosas como `pyautogui`) | Aceptado: el log es interno, nunca sale del proceso ni del disco del usuario que ya lo tiene. No se trunca — la SPEC pide el mensaje completo explícitamente para que sea accionable en debugging. |
| Alguien reintroduce `str(e)` en el texto del canal en un cambio futuro (regresión) | Los tests nuevos en `tests/test_gateway.py` (ver abajo) fuerzan una excepción con un mensaje distintivo y assertan que ese mensaje NO aparece en el texto de respuesta — cualquier regresión futura que reintroduzca `str(e)` en el `return`/`GlassResponse.text` rompe el test inmediatamente. |
| `message.user_id`/`message.channel` o `session.user_id`/`session.channel` no están poblados al momento del log | Ya cubierto por el baseline/SPEC: `GlassMessage` declara esos campos sin default (obligatorios), y `session` es creado por `registry.get_or_create(...)` con `user_id`/`channel` explícitos antes de llegar a estos métodos. No se agrega manejo adicional — consistente con "Casos borde" de la SPEC. |

## Pruebas sugeridas
`tests/test_gateway.py` no existe — se crea desde cero. Una prueba por cada criterio de
aceptación de la SPEC, más los casos borde que la SPEC ya identificó. Estructura sugerida
(sigue `.claude/rules/testing.md`: pytest, sin red externa, con mocks):

```python
"""
tests/test_gateway.py
Cobertura REQ-024: logging + saneamiento de errores en GlassGateway.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

from channels.gateway import GlassGateway, GlassMessage, MessageType


def _make_message(text="hola", msg_type=MessageType.TEXT, **kw):
    return GlassMessage(
        user_id="u1", user_name="Johan", text=text, channel="telegram",
        msg_type=msg_type, **kw
    )


class TestProcessErrorHandling:
    def test_process_loguea_error_con_exc_info(self, caplog):
        """CA: process() loguea con exc_info=True, usuario y canal, mensaje original."""
        gateway = GlassGateway()
        msg = _make_message(text="algo")
        with patch("ai.user_manager.registry.get_or_create") as mock_reg:
            mock_reg.side_effect = RuntimeError("fuga-interna-marca-XYZ")
            with caplog.at_level(logging.ERROR):
                gateway.process(msg)
        assert any("fuga-interna-marca-XYZ" in r.message for r in caplog.records)
        assert any(r.exc_info for r in caplog.records)
        assert any("usuario=u1" in r.message and "canal=telegram" in r.message
                    for r in caplog.records)

    def test_process_respuesta_sin_fragmentos_del_error(self):
        """CA: GlassResponse.text no contiene ningún fragmento de str(e)."""
        gateway = GlassGateway()
        msg = _make_message(text="algo")
        with patch("ai.user_manager.registry.get_or_create") as mock_reg:
            mock_reg.side_effect = RuntimeError("/ruta/absoluta/secreta/del/disco")
            resp = gateway.process(msg)
        assert "/ruta/absoluta/secreta/del/disco" not in resp.text
        assert resp.text == (
            "Lo siento, he encontrado un inconveniente inesperado. "
            "Intente de nuevo en un momento."
        )

    def test_process_camino_feliz_sin_cambios(self):
        """No-regresión: sin excepción, process() responde con el resultado normal."""
        gateway = GlassGateway()
        msg = _make_message(text="hola")
        session = MagicMock()
        with patch("ai.user_manager.registry.get_or_create", return_value=session), \
             patch("intent.classifier.classify_command", return_value=(None, {})), \
             patch("core.resolution.resolve") as mock_resolve, \
             patch.object(GlassGateway, "_save_semantic"):
            mock_resolve.return_value = MagicMock(text="respuesta normal")
            resp = gateway.process(msg)
        assert resp.text == "respuesta normal"


class TestAskClaudeForUserErrorHandling:
    def test_loguea_error_con_exc_info(self, caplog):
        gateway = GlassGateway()
        msg = _make_message(msg_type=MessageType.IMAGE)
        session = MagicMock(conversation_history=[])
        with patch("ai.claude_brain.ask_claude", side_effect=RuntimeError("marca-ABC")):
            with caplog.at_level(logging.ERROR):
                gateway._ask_claude_for_user(msg, session)
        assert any("marca-ABC" in r.message for r in caplog.records)
        assert any(r.exc_info for r in caplog.records)

    def test_respuesta_sin_fragmentos_del_error(self):
        gateway = GlassGateway()
        msg = _make_message(msg_type=MessageType.IMAGE)
        session = MagicMock(conversation_history=[])
        with patch("ai.claude_brain.ask_claude", side_effect=RuntimeError("dato-interno-123")):
            result = gateway._ask_claude_for_user(msg, session)
        assert "dato-interno-123" not in result
        assert result == "Lo siento, no pude procesar esa solicitud en este momento. Intente de nuevo."

    def test_pop_de_historial_se_conserva(self):
        """No-regresión: la guarda de pop() sigue funcionando igual."""
        gateway = GlassGateway()
        msg = _make_message(msg_type=MessageType.IMAGE)
        session = MagicMock(conversation_history=[{"role": "user", "content": "x"}])
        with patch("ai.claude_brain.ask_claude", side_effect=RuntimeError("boom")):
            gateway._ask_claude_for_user(msg, session)
        session.conversation_history.pop.assert_called_once()


class TestHandleScreenshotErrorHandling:
    def test_loguea_error_con_exc_info(self, caplog):
        gateway = GlassGateway()
        session = MagicMock(user_id="u1", channel="discord")
        with patch("pyautogui.screenshot", side_effect=RuntimeError("marca-DEF")):
            with caplog.at_level(logging.ERROR):
                gateway._handle_screenshot(session, "captura")
        assert any("marca-DEF" in r.message for r in caplog.records)
        assert any(r.exc_info for r in caplog.records)

    def test_respuesta_sin_fragmentos_del_error_y_conserva_vocative(self):
        gateway = GlassGateway()
        session = MagicMock(user_id="u1", channel="discord")
        with patch("pyautogui.screenshot", side_effect=RuntimeError("/tmp/ruta-secreta")):
            resp = gateway._handle_screenshot(session, "captura")
        assert "/tmp/ruta-secreta" not in resp.text
        assert "No pude tomar la captura" in resp.text
        assert "Intente de nuevo en un momento." in resp.text


class TestSaveSemanticNoRegression:
    def test_save_semantic_sigue_usando_warning(self, caplog):
        """No-regresión: _save_semantic() no se toca, sigue con logger.warning."""
        gateway = GlassGateway()
        session = MagicMock(user_id="u1")
        with patch("ai.memory_manager.memory.store", side_effect=RuntimeError("x")):
            with caplog.at_level(logging.WARNING):
                gateway._save_semantic(session, "texto", "resultado")
        assert any(r.levelname == "WARNING" for r in caplog.records)
```

Notas para `orion-dev`/`orion-tester`:
- Los `patch(...)` sobre `ai.user_manager.registry`, `ai.claude_brain.ask_claude`,
  `pyautogui.screenshot`, `ai.memory_manager.memory.store` respetan `.claude/rules/testing.md`
  (sin red, sin micrófono/altavoz, sin tocar archivos reales — `pyautogui`/`tempfile` quedan
  mockeados, nunca se ejecuta una captura real).
- Los imports dentro de los métodos (`from ai.user_manager import registry`, etc.) son imports
  locales — el `patch(...)` debe apuntar a la ruta del módulo origen (`ai.user_manager.registry`,
  `ai.claude_brain.ask_claude`, `pyautogui.screenshot`, `ai.memory_manager.memory.store`), no a
  `channels.gateway.*`, porque el import ocurre en tiempo de ejecución dentro del método.
- Además de estos tests nuevos, `orion-tester` debe correr `pytest tests/ --tb=short -v`
  completo y confirmar 1779+N passed, 0 failed (N = tests nuevos de este archivo), sin
  regresiones respecto al baseline.

## Aprobación de arquitectura
**APROBADO bajo autorización nocturna en bloque del 2026-09-06 — no es revisión en vivo del
usuario.** Encaja en el criterio de esa autorización: cambio mecánico y acotado a un archivo,
reduce superficie de fuga existente sin abrir superficie nueva, sin dependencias nuevas, sin
tocar niveles 🔴 Rojo, consistente con lo ya aprobado en SPEC-024.md.
