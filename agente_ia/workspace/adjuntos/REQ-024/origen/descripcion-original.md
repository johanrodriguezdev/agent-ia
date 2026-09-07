# REQ-024 — Descripción de origen

**Fecha:** 2026-09-07
**Reportado por:** Johan (vía auditoría comparativa contra OpenClaw)

## Fuente del hallazgo
Documento de referencia: `workspace/referencias/openclaw/02-gateway-canales-ruteo.md`,
sección "7.2, hallazgo 🟡 B4".

## Bug (verificado por lectura directa del archivo, 289 líneas leídas completas el 2026-09-07)

En `channels/gateway.py`, método `GlassGateway.process()`, el manejo de excepción general
(líneas ~105-109 al momento de abrir este REQ) es:

```python
except Exception as e:
    return GlassResponse(
        text=f"Lo siento, he encontrado un inconveniente: {str(e)[:80]}",
        speak=True
    )
```

### Problemas confirmados
1. **No hay logging del error** (`logger.error` ausente) — pese a que
   `.claude/rules/python-style.md` exige registrar cualquier excepción antes de manejarla.
   El traceback se pierde para siempre, sin ninguna señal en los logs de que algo falló.
2. **Los primeros 80 caracteres del mensaje de excepción crudo se envían tal cual al canal
   externo** (Telegram, Discord, cualquier canal que use `GlassGateway.process()`) — un
   `FileNotFoundError` o el mensaje de una librería puede incluir rutas absolutas del disco
   del usuario u otros detalles internos que no deberían salir del PC.

## Alcance — ÚNICO alcance de este REQ
Corrección de manejo de errores acotada, NO un rediseño del gateway.

### Fuera de alcance explícito
- Rediseñar `GlassGateway` a un gateway persistente (roadmap Fase 1, iniciativa más grande).
- Tocar el `except: pass` interno de `_save_semantic()` (líneas ~169-175) — YA loguea con
  `logger.warning`, no tiene el mismo problema.
- Tocar `_ask_claude_for_user()` — tiene su propio manejo de excepción distinto, con su propio
  patrón. Fuera de alcance salvo que la SPEC determine que comparte el mismo bug.

## Dirección de la corrección (a precisar en SPEC)
- Registrar la excepción completa con `logger.error(...)` (incluyendo traceback o al menos
  `exc_info=True`) ANTES de responder al usuario.
- Reemplazar el mensaje que se envía al canal por un texto genérico y seguro (sin el contenido
  crudo de `str(e)`), sin perder la brevedad ni el tono conversacional que ya tiene la
  respuesta actual.

## Verificación adicional hecha por orion-coordinador
Se releyó `channels/gateway.py` líneas 80-119 el 2026-09-07 y se confirmó que el bug sigue
presente tal cual se describe (líneas 105-109 en la versión actual del archivo).
