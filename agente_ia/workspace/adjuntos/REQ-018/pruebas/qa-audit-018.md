# Auditoría QA REQ-018 — Confirmación conversacional para `/eliminar` en Telegram

**Agente:** orion-qa | **Fecha:** 2026-09-07 | **Precede a:** revisión manual de Johan

## Nota de proceso — commit `1c895f6` (no es hallazgo de seguridad)

Confirmado directamente, no solo repetido de `orion-tester`:

```
git show --stat 1c895f6
commit 1c895f61f4ea7775a8b97b8426a9f43d40ba53f4
Author: soporte_sigaind <soporte@sigag.com>
Date:   Wed Aug 26 22:50:26 2026 -0500
    feat: mejoras de agentes, canales y confirmaciones (REQ-018 a REQ-020)
```

El código de REQ-018 (`channels/telegram_bot.py`, `channels/telegram_confirmation_adapter.py`
nuevo, `core/security_manager.py`, `tests/test_telegram_bot.py`) está efectivamente commiteado en
`main` desde el 2026-08-26, bundleado junto con REQ-019/REQ-020, bajo el autor `soporte_sigaind`
— no `orion-dev` ni ningún otro agente de este pipeline (`.claude/rules/git.md` prohíbe que un
agente ejecute `git commit`, y ninguna sesión de este pipeline lo hizo). Interpretación más
probable: Johan commiteó él mismo el trabajo en algún punto, y el pipeline de documentación
(tracker/contexto) no se puso al día en su momento — el REQ quedó "detenido" en `EN_PRUEBAS` desde
el 2026-08-21 hasta que `orion-tester` lo retomó el 2026-09-06. Esto es una nota de proceso para
el morning summary, no un hallazgo de seguridad: el commit en sí no introduce ningún problema de
seguridad nuevo (el código auditado abajo es exactamente el que está en `main`). Consecuencia
directa para este veredicto: aunque yo apruebe, el Estado del tracker **no avanza a
`LISTO_PARA_COMMIT`** — ese commit ya existe y Johan no lo confirmó explícitamente dentro de este
pipeline; necesita revisarlo él mismo (ver "Veredicto" al final).

## 1. Seguridad — clasificación de riesgo y niveles verde/amarillo/rojo

### 1.1 `CHANNEL_ACTION_EXCEPTIONS` — quirúrgico, no una relajación general

Verificado en `core/security_manager.py:107-124` (leído directo, no solo citado por el tester):

```python
CHANNEL_ACTION_EXCEPTIONS: set[tuple[ChannelType, str]] = {
    (ChannelType.TELEGRAM, "delete_task"),
    (ChannelType.TELEGRAM, "pc_type"),
    (ChannelType.TELEGRAM, "pc_key"),
    (ChannelType.TELEGRAM, "pc_click"),
}
```

4 entradas, todas `(ChannelType.TELEGRAM, <acción específica>)`. La entrada de este REQ
(`delete_task`) es la única que me corresponde auditar; las 3 restantes (`pc_type`/`pc_key`/
`pc_click`) pertenecen a un REQ posterior de control remoto de escritorio — confirmado que **no
es una desviación de REQ-018**, es el mecanismo diseñado en CA-02 funcionando exactamente como se
previó ("cada entrada debe justificarse caso por caso", comentario del propio código,
línea 105-106): cada acción sigue siendo YELLOW, sigue pasando por el mismo adaptador de
confirmación conversacional, y ninguna baja de nivel a GREEN.

`is_action_allowed()` (`core/security_manager.py:387-395`) sigue siendo la misma condición OR
aditiva descrita en `arquitectura-018.md` §4.1 — leído línea por línea:

```python
def is_action_allowed(self, action_name: str, channel: ChannelType) -> bool:
    level = self.classify_action(action_name)
    if level is None:
        return False
    if (channel, action_name) in CHANNEL_ACTION_EXCEPTIONS:
        return True
    allowed = self.get_allowed_levels(channel)
    return level in allowed
```

Byte a byte lo que la arquitectura aprobó. `CHANNEL_ALLOWED_LEVELS[ChannelType.TELEGRAM]`
(línea 74) sigue siendo `[RiskLevel.GREEN]` — sin tocar. La excepción no reemplaza la política
general, la complementa. **Sin hallazgos.**

### 1.2 Test de regresión CA-03 — deriva dinámicamente, no lista hardcodeada

Verificado directo en `tests/test_security_manager.py:820-838` (no asumido por la descripción del
tester): la lista de YELLOW a verificar se construye con
`[name for name, level in security_manager._actions.items() if level == RiskLevel.YELLOW]`, filtra
las declaradas en `CHANNEL_ACTION_EXCEPTIONS`, y exige `len(yellow_a_verificar) >= 15` como
guardrail propio. Esto es exactamente el fix del Hallazgo C de `security-audit-018.md` —
confirmado implementado, no solo documentado. **Sin hallazgos.**

### 1.3 Gate de `/eliminar` — CA-01 verificado en código real

`cmd_eliminar()` (`channels/telegram_bot.py:570-636`): llama
`security_manager.require_confirmation("delete_task", ChannelType.TELEGRAM, ...)` vía
`asyncio.to_thread()` (línea 613-619) antes de cualquier llamada a `task_manager.delete_task()`
(línea 627). Si `confirmed` es `False`, hace `return` inmediato con mensaje de cancelación
explícito (línea 621-625) — la tarea no se toca. Sin caminos alternativos que salteen el gate.
**Sin hallazgos.**

### 1.4 Fix del hallazgo bloqueante A (DoS) — confirmado presente en código real

No asumido por la palabra de `orion-tester` — leído directo:

```
channels/telegram_bot.py:1056-1064
app = (
    Application.builder()
    .token(token)
    .concurrent_updates(True)   # REQ-018/Hallazgo A ...
    .post_init(_post_init_telegram)
    .build()
)
```

`.concurrent_updates(True)` está presente, en el builder real usado por `run_telegram_bot()`, con
el comentario que documenta por qué existe. Sin esto, `python-telegram-bot` serializa el
dispatcher completo y el bug de DoS trivial (cualquier `/eliminar` sin responder bloquea el bot
para todos hasta 120s) reaparecería. **Confirmado resuelto — sin hallazgos.**

### 1.5 `reserve_pending()` — atomicidad bajo lock (Hallazgo E)

`channels/telegram_confirmation_adapter.py:91-112`:

```python
def reserve_pending(self, user_id: str, especulativa: bool = False) -> bool:
    with self._lock:
        if user_id in self._pending:
            return False
        self._pending[user_id] = _PendingConfirmation(consume_respuestas=not especulativa)
        return True
```

La verificación "¿ya hay una pendiente?" y la inserción ocurren dentro del mismo bloque
`with self._lock:` — atómico de verdad, no dos operaciones separadas con una ventana entre medio.
`cmd_eliminar()` (`channels/telegram_bot.py:599`) la invoca **antes** del `await
asyncio.to_thread(...)` (línea 613), en el mismo hilo/Task que procesa el update — exactamente el
fix que cierra la ventana de carrera del Hallazgo E (no solo la acota, como hacía el diseño
original con la reserva dentro de `confirm()`). `confirm()` (línea 114-173) ya no crea ni valida
duplicados — asume la reserva previa y deniega fail-closed (`pending is None` → `return False`,
línea 131-139) si no la encuentra, sin reabrir la ventana. **Confirmado — sin hallazgos.**

**Nota fuera de alcance, sin impacto en este REQ:** existe un segundo caller de `reserve_pending()`
(`channels/telegram_bot.py:748`, `especulativa=True`) agregado por un REQ posterior (agente con
herramientas, `pc_type`/`pc_key`/`pc_click`). Revisado brevemente para descartar que debilite la
garantía de `delete_task`: reserva/libera alrededor de cada mensaje de texto normal, y si la
reserva falla (ya hay una pendiente — p. ej. un `/eliminar` en curso) el mensaje se procesa "sin
contexto", lo que hace que `confirm()` deniegue fail-closed cualquier acción amarilla que
apareciera por ese camino (línea 750-753, comentario explícito en el código). No compromete CA-09
de `delete_task`. No es objeto de esta auditoría — pertenece a un REQ distinto — se deja
constatado por transparencia.

### 1.6 Timeout fail-closed (CA-07)

`CONFIRM_TIMEOUT_SECONDS = 120` (línea 36). `pending.event.wait(timeout=CONFIRM_TIMEOUT_SECONDS)`
(línea 147) — si expira, `answered_in_time` es `False` y `confirmed = pending.result if
answered_in_time else False` (línea 148-149) fuerza `False` explícitamente, nunca `True` por
defecto. El bloque `finally` (línea 168-173) hace `self._pending.pop(user_id, None)`
incondicionalmente — respuesta, timeout o excepción, siempre se limpia. **Sin hallazgos.**

### 1.7 Secretos — sin hardcodeo

`channels/telegram_confirmation_adapter.py` completo: sin API keys, tokens ni credenciales
embebidas — el archivo no toca autenticación, solo el puente de confirmación. `channels/
telegram_bot.py:1034`: `token = _get_token()` — el token del bot se obtiene por función, no está
escrito en el archivo (confirmado que no hay ningún string con forma de token de Telegram en
ninguno de los 2 archivos vía lectura completa). `requirements.txt:72`:
`# python-telegram-bot==20.7` sigue comentado como dependencia opcional, sin cambios de este REQ.
**Sin hallazgos.**

## 2. Logging — sin `except: pass` silencioso

Los 2 únicos `except Exception as e:` de `channels/telegram_confirmation_adapter.py` (línea 156 y
187) registran el error antes de devolver un valor seguro:

- Línea 156-167 (dentro de `confirm()`, Hallazgo B): captura cualquier excepción entre el envío
  del mensaje y la resolución, hace `logger.error(...)` con el `user_id` y la excepción, y
  retorna `False` (fail-closed) — nunca deja escapar la excepción ni deja el estado en `_pending`
  sin limpiar (el `finally` de línea 168-173 corre siempre).
- Línea 185-188 (dentro de `_send_message()`): si `future.result(timeout=...)` lanza (mensaje no
  se pudo enviar), `logger.error(...)` y continúa — la espera de `confirm()` sigue su curso y
  expira por timeout si el usuario nunca vio el mensaje, también fail-closed.

Ninguno de los dos es un `except: pass`. Coincide con el fix documentado del Hallazgo B de
`security-audit-018.md`. `require_confirmation()` (`core/security_manager.py:442-`) sigue
registrando `logger.warning`/`logger.info` en cada rama (bloqueada, confirmada, cancelada, sin
adaptador) y `_log_audit()` sin caminos paralelos nuevos (CA-14). **Sin hallazgos.**

## 3. Convenciones de código

- Type hints presentes en las firmas nuevas (`reserve_pending(self, user_id: str, especulativa:
  bool = False) -> bool`, `confirm(self, action_name: str, message: str) -> bool`, etc.).
- `logger = logging.getLogger(__name__)` al inicio del módulo nuevo, sin `print()`.
- Imports ordenados (estándar → third-party → locales, en los imports diferidos dentro de las
  funciones de `telegram_bot.py`, patrón ya existente en el archivo antes de este REQ).
- Docstrings explicando el porqué, no solo el qué — consistente con el resto del código de este
  REQ y del repo.
- Sin líneas evidentemente por encima de 100 caracteres en los bloques revisados.

**Sin hallazgos de estilo.**

## 4. Cobertura de los 14 CA — verificación propia, no solo repetición de orion-tester

Re-verifiqué contra código fuente real (no solo la tabla de `test-results-018.md`) los puntos de
mayor riesgo: CA-01 (§1.3), CA-02/CA-03 (§1.1/§1.2), CA-08 (§1.4), CA-09 (§1.5), CA-07 (§1.6),
CA-11 (`CHANNEL_ALLOWED_LEVELS[TELEGRAM]` sin tocar, confirmado línea 74; `delete_task` sigue
`RiskLevel.YELLOW` — confirmado por `test_ca11_delete_task_sigue_clasificada_yellow` en verde). El
resto de los criterios (CA-04, CA-05, CA-06, CA-10, CA-12, CA-13, CA-14) coinciden con lo que
`orion-tester` reportó y no encontré discrepancias al leer el código citado en su tabla — no los
repito en detalle acá para no duplicar `test-results-018.md`, que ya cita línea y test por
criterio.

## 5. Riesgos activos al cierre

Ninguno de seguridad. El único punto abierto es de proceso (commit ya en `main` sin confirmación
explícita de Johan dentro de este pipeline, §0) — no bloquea la aprobación técnica, sí bloquea el
avance del tracker a `LISTO_PARA_COMMIT`.

## Veredicto: ✅ APROBADO

Sin hallazgos de seguridad, logging o convenciones. Los 3 hallazgos de `security-audit-018.md`
(A bloqueante, B y C no bloqueantes) están confirmados resueltos en el código real, no solo en la
documentación. El mecanismo de excepción canal+acción (CA-02) sigue siendo quirúrgico incluso
después de que un REQ posterior le sumó 3 entradas más — el guardrail de CA-03 lo protege
correctamente. `delete_task` sigue Amarillo, `CHANNEL_ALLOWED_LEVELS` intacto.

**El Estado del tracker permanece en `EN_QA`** — no avanza a `LISTO_PARA_COMMIT` pese al
veredicto aprobatorio, por dos motivos acumulativos: (1) el DoD de `orion-qa` exige que el humano
haga la prueba manual final y dé OK antes de ese avance, y esa prueba todavía no ocurrió dentro de
este pipeline; (2) el código ya está commiteado en `main` (`1c895f6`) sin que quede registro de
que Johan lo haya confirmado explícitamente como el resultado final de este pipeline — necesita
revisarlo él mismo antes de que el REQ se cierre como listo. No se ejecutó `git commit` en esta
sesión ni en ninguna de este pipeline.

### Mensaje de commit sugerido (para cuando Johan confirme, no para uso inmediato)

```
📝 MENSAJE DE COMMIT SUGERIDO:
──────────────────────────────
feat(REQ-018): confirmación conversacional real para /eliminar en Telegram

- Cierra bypass del gate Amarillo: /eliminar ahora pasa por
  security_manager.require_confirmation() antes de borrar
- Adaptador nuevo channels/telegram_confirmation_adapter.py (puente
  asyncio.to_thread + threading.Event, multiusuario, fail-closed a 120s)
- Excepción quirúrgica CHANNEL_ACTION_EXCEPTIONS (canal+acción), sin
  relajar CHANNEL_ALLOWED_LEVELS en bloque
- .concurrent_updates(True) en el bot de Telegram — corrige DoS trivial
  encontrado en auditoría de seguridad (bot completo se bloqueaba hasta
  120s por cualquier /eliminar sin responder)
- /completar, /nueva y /tareas quedan auditados en audit.db
```

Nota: este mensaje describe el contenido de `1c895f6`, que ya existe en `main` mezclado con
REQ-019/REQ-020 — se entrega igual, tal como pide `.claude/rules/git.md`, pero su utilidad
práctica depende de qué decida Johan al revisar la situación del commit.
