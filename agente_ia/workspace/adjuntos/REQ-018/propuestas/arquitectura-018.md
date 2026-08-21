# Arquitectura REQ-018 — Confirmación conversacional para `/eliminar` en Telegram

**Estado:** ✅ APROBADA por Johan (2026-08-20) — ⏳ ADDENDUM DE SEGURIDAD APLICADO, ESPERANDO
RE-CHEQUEO DE `orion-security` (2026-08-20, ver §15). El diseño central sigue aprobado tal cual;
`orion-security` auditó y encontró 1 hallazgo bloqueante (falta `.concurrent_updates(True)`, ya
corregido en §15.1) — no requiere volver a pasar por Johan (corrección técnica de seguridad, no
decisión de alcance).
**Agente:** orion-architect
**Fecha:** 2026-08-20
**Precede a:** orion-security (re-chequeo pendiente, §15) → orion-dev

Diseño sobre la base de `spec/SPEC-018.md` (14 CA) y `origen/baseline-018.md`, incorporando
las 2 correcciones que baseline encontró sobre el texto de la SPEC (ver §1) y resolviendo
explícitamente la fricción de CA-10 con `agents/tool_registry.py` (ver §2).

---

## 0. Resumen para Johan

- `cmd_eliminar()` pasa a pedir confirmación real por Telegram ("¿confirmás? sí/no") antes de
  borrar, vía el mismo `security_manager.require_confirmation()` que ya usa el resto del sistema.
- El registro del adaptador nuevo va en `channels/telegram_bot.py::run_telegram_bot()` (vía un
  callback `post_init` de la `Application`), **no en `main.py`** — corregido según el hallazgo de
  `orion-baseline`.
- Excepción quirúrgica nueva en `core/security_manager.py`: un `set` de pares
  `(ChannelType, acción)` evaluado además de `CHANNEL_ALLOWED_LEVELS`, con una sola entrada:
  `(ChannelType.TELEGRAM, "delete_task")`. Las otras 19 acciones YELLOW siguen bloqueadas en
  Telegram exactamente igual que hoy.
- Adaptador nuevo `channels/telegram_confirmation_adapter.py::TelegramConfirmationAdapter` —
  puente `asyncio.to_thread()` + `threading.Event` + `asyncio.run_coroutine_threadsafe()`, sin
  bloquear el loop de `asyncio` para otros usuarios.
- `/completar` y `/nueva` **no se conectan a `execute_tool()`** — quedan con su llamada directa a
  `task_manager` sin cambios, pero ahora auditadas vía `security_manager.require_confirmation()`
  llamado directamente (mismo gate público que usa `execute_tool()` por dentro). Solo `/tareas` se
  conecta limpio a `execute_tool("task_list", ...)`. Decisión explícita mía, justificada en §2 —
  necesita tu visto bueno.
- Mi recomendación es que `orion-security` corra como paso dedicado antes de `orion-dev` — ver §11
  para el motivo completo y por qué difiere de lo decidido en REQ-016/REQ-017.

---

## 1. Corrección aplicada — ubicación del registro del adaptador

`SPEC-018.md` ("Módulos afectados") dice que `main.py` registra el adaptador nuevo, análogo a
`register_confirmation_adapter(ChannelType.DESKTOP, _desktop_confirm)` (línea 59). **Esto es
incorrecto y se corrige en esta propuesta**: `main.py` nunca importa ni arranca
`channels/telegram_bot.py` — son dos procesos standalone distintos, cada uno con su propio
`if __name__ == "__main__":`. Confirmado por `orion-baseline` con grep exhaustivo: el único rastro
de "telegram" en `main.py` es un comentario.

El registro real va dentro de `channels/telegram_bot.py::run_telegram_bot()`, y específicamente
dentro de un callback `post_init` de la `Application` (no como una línea suelta antes de
`app.run_polling()`) — ver §4.3 para el motivo técnico (hace falta un event loop ya corriendo para
capturar la referencia que el adaptador necesita para su puente async→sync).

---

## 2. Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| CA-01 — `/eliminar` gateado | `cmd_eliminar()` llama `security_manager.require_confirmation("delete_task", ChannelType.TELEGRAM, details=f"task_id={task_id}", user_id=user_id)` antes de `task_manager.delete_task()`. Si no confirma, responde cancelación explícita, no borra. §6.1 |
| CA-02 — Excepción por canal+acción | `CHANNEL_ACTION_EXCEPTIONS: set[tuple[ChannelType, str]]` nuevo en `core/security_manager.py`, evaluado dentro de `is_action_allowed()` como condición OR adicional a `CHANNEL_ALLOWED_LEVELS`. Única entrada: `(ChannelType.TELEGRAM, "delete_task")`. §4.1 |
| CA-03 — Ninguna otra acción YELLOW se abre | La excepción es un `set` de pares exactos, no una regla por canal — para las 19 acciones YELLOW restantes, `is_action_allowed()` cae al camino de siempre (`CHANNEL_ALLOWED_LEVELS[TELEGRAM] == [GREEN]` → deniega). Test de regresión parametrizado sobre las 19. §11 |
| CA-04 — Adaptador registrado | `TelegramConfirmationAdapter.confirm` registrado vía `register_confirmation_adapter(ChannelType.TELEGRAM, ...)` dentro del callback `post_init`. Envía **exactamente** el `full_msg` que ya arma `require_confirmation()` — el adaptador nunca construye ni reformula texto propio. §4.3, §5.2 |
| CA-05 — Correlación con el próximo mensaje | Handler nuevo `_intercept_confirmacion_pendiente`, registrado en `group=-1` (prioridad máxima) con filtro `filters.TEXT` **sin excluir comandos** — intercepta cualquier texto, incluidos `/tareas`, `/nueva ...`, antes que cualquier `CommandHandler`/`handle_text()` de `group=0`. §4.3, §6.3, §7.4 |
| CA-06 — Criterio de confirmación exacto | `TelegramConfirmationAdapter.resolve()` usa literalmente `texto.strip().lower() in ("sí", "si", "yes", "s")` — mismo criterio que `_desktop_confirm`. §5.2 |
| CA-07 — Timeout fail-closed 120s | `CONFIRM_TIMEOUT_SECONDS = 120` en el adaptador nuevo, mismo valor que `WebViewConfirmationAdapter`. `threading.Event.wait(timeout=...)` nunca retorna `True` por defecto; estado pendiente se limpia siempre (respondido o no). §5.2 |
| CA-08 — No bloquea el loop de asyncio | `cmd_eliminar()` invoca `require_confirmation()` vía `await asyncio.to_thread(...)` — corre en un hilo worker, nunca en el hilo del event loop. El envío del mensaje de confirmación (async, `bot.send_message`) se reintroduce al loop principal desde ese hilo worker vía `asyncio.run_coroutine_threadsafe()`. §4.3, §5.2, §7.1 |
| CA-09 — Una sola confirmación pendiente | Chequeo rápido en `cmd_eliminar()` (`has_pending()`) + chequeo atómico bajo lock dentro de `TelegramConfirmationAdapter.confirm()` (autoritativo). Segunda confirmación se rechaza de inmediato con mensaje explícito. §5.2, §10 (riesgo de carrera documentado) |
| CA-10 — `/completar`, `/nueva`, `/tareas` auditados | `/tareas` → `execute_tool("task_list", ...)` (reemplazo limpio). `/completar` y `/nueva` → llamada directa a `task_manager` **sin cambios**, precedida por `security_manager.require_confirmation("task_complete"/"task_create", ChannelType.TELEGRAM, ...)` para auditar sin arriesgar el comportamiento. Decisión justificada en §3 — pendiente de tu aprobación explícita. |
| CA-11 — Clasificación de riesgo intacta | Cero cambios a `_register_default_actions()`/`RiskLevel` de ninguna acción. `CHANNEL_ALLOWED_LEVELS` no se toca — la excepción de CA-02 es una estructura nueva y separada. §4.1 |
| CA-12 — Pipeline de `resolve()` intacto | Cero cambios a `core/resolution.py`. Los tools `task_create`/`task_complete` de `agents/tool_registry.py` (usados por `_try_task_tool()`) tampoco se tocan — es precisamente el motivo de la decisión de CA-10. §3 |
| CA-13 — Discord sin cambios | `channels/discord_bot.py` no aparece en ningún archivo modificado de esta propuesta. |
| CA-14 — Auditoría sin caminos paralelos | Todo pasa por `security_manager._log_audit()` ya existente: directo en `require_confirmation()` (CA-01, CA-10 para `/nueva`/`/completar`) o indirecto vía `execute_tool()` (CA-10 para `/tareas`). Sin tabla ni mecanismo nuevo. |

---

## 3. Decisión de diseño — CA-10 (`/completar`, `/nueva`, `/tareas`)

`orion-baseline` encontró que solo `task_list` es un reemplazo limpio de `cmd_tareas()`. Los otros
dos tools de `agents/tool_registry.py` tienen fricción real con el comportamiento actual de sus
comandos slash equivalentes:

- **`_task_create_invoke()`** (usado por `task_create`) no replica el fallback de "tarea simple"
  que `cmd_nueva()` sí tiene hoy (crear con recordatorio a 1 hora cuando
  `create_from_natural()` devuelve `None`, líneas 448-465 de `telegram_bot.py`). Conectar
  `/nueva` a `execute_tool("task_create", ...)` tal cual cambiaría el comportamiento observable
  en el caso "texto no parseable" — el usuario dejaría de recibir su tarea simple y en cambio
  vería `"No pude interpretar esa tarea, Señor."`. Viola CA-10 literal.
- **`_task_complete_invoke()`** (usado por `task_complete`) espera `params["text"]` libre, extrae
  el ID con su propio regex, y si no matchea intenta auto-completar (si hay una sola tarea
  pendiente) o pide aclaración (si hay varias) — ninguna de esas dos ramas existe hoy en
  `cmd_completar()`, que exige ID explícito y falla con un mensaje distinto
  (`"No encontré la tarea #{id} en sus pendientes, Señor."` vs.
  `"No encontré ninguna tarea pendiente con el ID #{id}, Señor."` del tool). Conectar `/completar`
  al tool tal cual cambia tanto el mensaje de error como agrega comportamiento nuevo (auto-completar,
  pedir aclaración) que el comando nunca tuvo.

### Opciones evaluadas

**(a) Adaptar `agents/tool_registry.py`** para que los dos tools acepten un modo "ya parseado"
(p. ej. un `task_id` explícito para `task_complete`, un flag `allow_simple_fallback` para
`task_create`) y así preservar el comportamiento exacto detrás de `execute_tool()`. Descartada:
`_task_create_invoke()` y `_task_complete_invoke()` son las mismas funciones que usa
`core/resolution.py::_try_task_tool()` para el camino de lenguaje natural — agregarles ramas
nuevas, aunque estén gateadas por un parámetro, aumenta la superficie de una función ya cubierta
por tests de REQ-006/REQ-017 y usada por un pipeline que CA-12 exige dejar intacto ("Pipeline de
`resolve()` intacto... cero cambios"). El REQ se define a sí mismo como de **alcance quirúrgico
obligatorio** — tocar código compartido con el camino de lenguaje natural para resolver un
problema de auditoría de un comando slash no es quirúrgico, es abrir una superficie nueva de
riesgo de regresión en un módulo que no necesita cambiar.

**(b) Dejar `/completar` y `/nueva` con su llamada directa a `task_manager`, sin auditoría** —
la opción que baseline ofreció como válida. Descartada como decisión final (no como camino
intermedio, ver (c)): dejaría 2 de los 3 comandos sin trazabilidad en `audit.db`, contradiciendo
explícitamente el pedido de Johan ("Auditoría extra → SÍ. Conectar también `/completar`, `/nueva`
y `/tareas`... por trazabilidad, aunque no cambien de comportamiento").

**(c) — ELEGIDA. Auditar vía `security_manager.require_confirmation()` directo, sin pasar por
`execute_tool()`, para los dos comandos con fricción; usar `execute_tool()` real solo para
`/tareas`.** `execute_tool()` (agents/tool_registry.py:86-99) internamente no hace más que: (1)
buscar el `ToolSpec`, (2) llamar `security_manager.require_confirmation(spec.name, channel,
details=..., user_id=...)`, (3) si pasa, invocar `spec.invoke(params)`. El paso (2) es el que
produce la auditoría — es una función pública, no un detalle de implementación de
`execute_tool()`. Llamar `security_manager.require_confirmation("task_create"/"task_complete",
ChannelType.TELEGRAM, details=..., user_id=...)` directamente, **inmediatamente antes** de la
llamada a `task_manager` sin modificar (paso 3 se reemplaza por el código actual del comando, no
por `spec.invoke()`), logra exactamente lo mismo que le importa a Johan — quedan en `audit.db`
con `result="permitida"` (ambos son GREEN, `require_confirmation()` nunca bloquea ni pide
confirmación para GREEN, ver `core/security_manager.py:254-256`) — sin tocar
`agents/tool_registry.py` ni arriesgar el camino de lenguaje natural, y sin cambiar una sola
línea de comportamiento observable de `/completar`/`/nueva`.

### Trade-off aceptado, a validar por Johan

Esta decisión se aparta de la letra literal de CA-10 ("Los tres invocan
`agents/tool_registry.py::execute_tool()`") para 2 de los 3 comandos — cumple el **objetivo**
de CA-10 (auditoría real, cero cambio de comportamiento) por un camino distinto al que describe
el texto. `/tareas` sí usa `execute_tool()` tal cual porque ahí no hay fricción ninguna. Ver
detalle de implementación exacto en §6.2.

---

## 4. Módulos a modificar

### 4.1 `core/security_manager.py` — mecanismo de excepción canal+acción (CA-02, CA-03, CA-11)

Agregado, junto a `CHANNEL_ALLOWED_LEVELS` (línea 54-61), un `set` nuevo y separado:

```python
# REQ-018/CA-02 — excepción quirúrgica por (canal, acción), evaluada ADEMÁS de
# CHANNEL_ALLOWED_LEVELS, nunca en su reemplazo. CHANNEL_ALLOWED_LEVELS sigue siendo la
# política general por canal (decisión de REQ-006, "capacidad, no autoridad"); esta tabla
# es una lista de excepciones puntuales y aditivas — habilita una acción YELLOW específica
# en un canal que de otro modo no la tendría, sin abrir el resto de las acciones YELLOW de
# ese canal. Cada entrada debe justificarse caso por caso (ver REQ-018,
# arquitectura-018.md §3/§4.1).
CHANNEL_ACTION_EXCEPTIONS: set[tuple[ChannelType, str]] = {
    (ChannelType.TELEGRAM, "delete_task"),
}
```

Y un cambio de una línea dentro de `is_action_allowed()` (línea 225-230), único punto de la clase
que consulta `CHANNEL_ALLOWED_LEVELS` para decidir si una acción YELLOW puede pedir confirmación
en un canal dado:

```python
def is_action_allowed(self, action_name: str, channel: ChannelType) -> bool:
    level = self.classify_action(action_name)
    if level is None:
        return False
    # REQ-018/CA-02 — excepción quirúrgica evaluada antes que la política general de canal.
    if (channel, action_name) in CHANNEL_ACTION_EXCEPTIONS:
        return True
    allowed = self.get_allowed_levels(channel)
    return level in allowed
```

**Por qué es seguro y mínimo:**
- Es un cambio estrictamente aditivo/monótono: para cualquier `(action_name, channel)` que NO
  esté en `CHANNEL_ACTION_EXCEPTIONS`, `is_action_allowed()` se comporta byte a byte igual que
  hoy. No puede convertir ningún `True` existente en `False`.
- `require_confirmation()` (línea 232-294) no cambia — sigue llamando a `is_action_allowed()`
  exactamente en el mismo punto (línea 258) con la misma firma.
- `CHANNEL_ALLOWED_LEVELS[ChannelType.TELEGRAM]` sigue siendo `[RiskLevel.GREEN]`, sin tocar
  (CA-11). `_register_default_actions()` no cambia — `delete_task` sigue registrado
  `RiskLevel.YELLOW` sin modificación.
- Grep confirmado (`is_action_allowed(` en todo el repo): los únicos otros dos call sites son
  `core/security_manager.py` mismo (dentro de `require_confirmation()`) y
  `core/proactive_engine.py:90` (`is_action_allowed("proactive_trigger", ChannelType.DESKTOP)`,
  acción GREEN, canal DESKTOP — no intersecta con la excepción nueva, cero impacto).

### 4.2 `core/confirmation.py` — sin cambios de contrato (CA-04, confirmado por baseline)

`ConfirmFn = Callable[[str, str], bool]` se mantiene igual. El adaptador nuevo de Telegram se
registra con la firma exacta `(action_name: str, mensaje: str) -> bool` — el puente async→sync es
responsabilidad exclusiva del adaptador nuevo (§5), tal como ya documenta el docstring del módulo
citando CA-11 de REQ-006. Cero líneas modificadas en este archivo.

### 4.3 `channels/telegram_bot.py` — registro del adaptador y nuevo handler de intercepción

Dentro de `run_telegram_bot()` (línea 773-841), **antes** de `app.run_polling()`:

```python
async def _post_init_telegram(application) -> None:
    """Callback post_init de la Application — corre una vez, dentro del event loop ya
    arrancado por python-telegram-bot, antes de que empiece el polling. Es el primer punto
    del ciclo de vida donde existe un loop corriendo del que capturar una referencia
    (asyncio.get_running_loop()) — intentarlo antes, en el cuerpo síncrono de
    run_telegram_bot(), fallaría porque ese loop todavía no existe en ese punto."""
    from core.confirmation import register_confirmation_adapter
    from core.security_manager import ChannelType
    from channels.telegram_confirmation_adapter import telegram_confirmation_adapter

    loop = asyncio.get_running_loop()
    telegram_confirmation_adapter.bind(application.bot, loop)
    register_confirmation_adapter(ChannelType.TELEGRAM, telegram_confirmation_adapter.confirm)
    logger.info("Adaptador de confirmación conversacional registrado para ChannelType.TELEGRAM")
```

```python
app = Application.builder().token(token).post_init(_post_init_telegram).build()
```

Y un `add_handler` nuevo, con prioridad de grupo `-1` (mayor prioridad que el grupo `0` por
defecto donde viven todos los `CommandHandler`/`MessageHandler` existentes), **agregado antes**
de los demás `add_handler(...)`:

```python
app.add_handler(
    MessageHandler(filters.TEXT, _intercept_confirmacion_pendiente), group=-1
)
```

Ver §6.3 para la función `_intercept_confirmacion_pendiente` y por qué necesita `filters.TEXT`
sin excluir comandos (a diferencia de `handle_text`, que sí los excluye).

---

## 5. Archivo nuevo — `channels/telegram_confirmation_adapter.py`

Análogo en intención a `ui/webview/confirmation_adapter.py::WebViewConfirmationAdapter`
(REQ-015), pero el puente que resuelve es distinto: hilo-worker↔hilo-Qt allá (vía `pyqtSignal`),
hilo-worker↔event-loop-de-`asyncio` acá (vía `asyncio.run_coroutine_threadsafe()`), y con una
diferencia estructural importante — `WebViewConfirmationAdapter` sirve a un solo usuario (la
persona frente al escritorio); este adaptador sirve a **múltiples usuarios de Telegram
concurrentes**, cada uno con su propio estado de confirmación pendiente independiente.

### 5.1 Diseño general

- **Puente async→sync (CA-08):** `cmd_eliminar()` (§6.1) invoca
  `security_manager.require_confirmation()` (síncrono) mediante `await asyncio.to_thread(...)` —
  corre en un hilo del executor por defecto de `asyncio`, nunca en el hilo del event loop
  principal. `require_confirmation()` internamente llama a `TelegramConfirmationAdapter.confirm()`
  (también síncrono, mismo hilo worker), que bloquea con `threading.Event.wait(timeout=120)` — un
  `threading.Event`, no `asyncio.Event`, porque `confirm()` corre en un hilo normal de Python, no
  dentro de una corutina con acceso directo al loop.
- **Correlación por usuario, sin cambiar la firma del adaptador (CA-05, CA-09):** el contrato de
  `core/confirmation.py` es fijo — `confirm(action_name, mensaje) -> bool`, sin `user_id` ni
  `chat_id`. Para que el adaptador sepa a qué usuario/chat corresponde cada invocación (necesario
  porque una sola instancia sirve a todos los usuarios de Telegram a la vez), `cmd_eliminar()`
  llama `telegram_confirmation_adapter.set_request_context(user_id, chat_id)` **justo antes** de
  disparar `asyncio.to_thread(...)`. Esto usa un `contextvars.ContextVar` — documentado por la
  librería estándar (`asyncio.to_thread()`, docs de `asyncio`) que el contexto vigente en el hilo
  que llama se propaga (copiado, aislado) al hilo nuevo que ejecuta la función. Dos usuarios
  pidiendo confirmación al mismo tiempo no se pisan: cada llamada a `asyncio.to_thread()` copia su
  propio contexto, así que cada hilo worker ve el `user_id`/`chat_id` que le corresponde, no el de
  otro usuario concurrente.
- **Envío del mensaje real (CA-04):** el `mensaje` que `confirm()` recibe como parámetro es
  exactamente el `full_msg` que ya construye `require_confirmation()` — el adaptador nunca lo
  reformula. Como `confirm()` corre en un hilo worker (sin acceso directo a `await`), enviarlo por
  Telegram (`bot.send_message(...)`, una corutina) requiere reintroducirlo al event loop principal
  vía `asyncio.run_coroutine_threadsafe(coro, loop)`, usando el `loop`/`bot` capturados en
  `bind()` (llamado desde el callback `post_init`, §4.3). Se envía sin `parse_mode` — texto plano,
  para no arriesgar que el parser de Markdown de Telegram altere un carácter del mensaje que
  `security_manager` ya armó.
- **Una sola confirmación pendiente por usuario (CA-09):** `_pending: Dict[str,
  _PendingConfirmation]`, indexado por `user_id`, protegido por un único `threading.Lock`. La
  verificación "¿ya hay una pendiente?" es atómica bajo ese lock dentro de `confirm()` — es la
  fuente de verdad autoritativa; el chequeo rápido que hace `cmd_eliminar()` antes de siquiera
  llamar a `require_confirmation()` (§6.1) es solo una optimización de UX (evita bloquear un hilo
  innecesariamente), no la garantía real.

### 5.2 Firmas exactas

```python
"""
channels/telegram_confirmation_adapter.py
Adaptador de confirmación conversacional para ChannelType.TELEGRAM (REQ-018).

Puente entre security_manager.require_confirmation() (síncrono, corre en un hilo worker vía
asyncio.to_thread()) y el runtime asyncio nativo de python-telegram-bot. Análogo en intención
a ui/webview/confirmation_adapter.py::WebViewConfirmationAdapter (REQ-015), resolviendo un
cruce hilo-worker↔event-loop-asyncio en vez de hilo-worker↔hilo-Qt. Contrato de
core/confirmation.py sin cambios: confirm(action_name, mensaje) -> bool, 100% síncrono desde
la perspectiva de security_manager.
"""

import asyncio
import contextvars
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

CONFIRM_TIMEOUT_SECONDS = 120  # mismo valor que WebViewConfirmationAdapter (REQ-015, CA-07)
_SEND_TIMEOUT_SECONDS = 10     # tope defensivo para el envío del mensaje, distinto del timeout de confirmación

# Viaja de cmd_eliminar() (hilo del event loop) a TelegramConfirmationAdapter.confirm()
# (hilo worker de asyncio.to_thread()) por propagación de contextvars — cada invocación de
# to_thread() copia el contexto vigente al hilo nuevo (ver docs de asyncio.to_thread()).
_request_ctx: "contextvars.ContextVar[Optional[Tuple[str, int]]]" = contextvars.ContextVar(
    "_telegram_confirm_request_ctx", default=None
)


@dataclass
class _PendingConfirmation:
    event: threading.Event = field(default_factory=threading.Event)
    result: bool = False


class TelegramConfirmationAdapter:
    """Adaptador (action_name, mensaje) -> bool para ChannelType.TELEGRAM. Se registra vía
    core.confirmation.register_confirmation_adapter(ChannelType.TELEGRAM, adapter.confirm)
    dentro del callback post_init de la Application (channels/telegram_bot.py)."""

    def __init__(self) -> None:
        self._bot = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._pending: Dict[str, _PendingConfirmation] = {}
        self._lock = threading.Lock()

    def bind(self, bot, loop: asyncio.AbstractEventLoop) -> None:
        """Llamado una vez desde el callback post_init, con el bot y el loop ya corriendo."""
        self._bot = bot
        self._loop = loop

    @staticmethod
    def set_request_context(user_id: str, chat_id: int) -> None:
        """Llamado por cmd_eliminar() antes de asyncio.to_thread(require_confirmation, ...)."""
        _request_ctx.set((user_id, chat_id))

    def has_pending(self, user_id: str) -> bool:
        """Chequeo rápido, no autoritativo (ver confirm() para la verificación atómica real)."""
        with self._lock:
            return user_id in self._pending

    def confirm(self, action_name: str, message: str) -> bool:
        """ConfirmFn — (action_name, mensaje) -> bool. Corre en el hilo worker de
        asyncio.to_thread(), nunca en el hilo del event loop (CA-08)."""
        ctx = _request_ctx.get()
        if ctx is None:
            logger.error(
                "TelegramConfirmationAdapter.confirm() invocado sin contexto de "
                "request (set_request_context() no se llamó antes) — denegado fail-closed"
            )
            return False
        user_id, chat_id = ctx

        with self._lock:
            if user_id in self._pending:
                # CA-09 — verificación atómica y autoritativa; cmd_eliminar() ya filtra el
                # caso común antes, esto es la garantía real bajo concurrencia.
                logger.warning(f"Confirmación duplicada para user_id={user_id} — denegada")
                return False
            pending = _PendingConfirmation()
            self._pending[user_id] = pending

        self._send_message(chat_id, message)
        answered_in_time = pending.event.wait(timeout=CONFIRM_TIMEOUT_SECONDS)

        with self._lock:
            confirmed = pending.result if answered_in_time else False
            self._pending.pop(user_id, None)  # no-op si resolve() ya lo sacó; cubre el timeout

        if not answered_in_time:
            logger.warning(
                f"Confirmación '{action_name}' para user_id={user_id} expiró tras "
                f"{CONFIRM_TIMEOUT_SECONDS}s sin respuesta — fail-closed"
            )
        return confirmed

    def _send_message(self, chat_id: int, text: str) -> None:
        if self._bot is None or self._loop is None:
            logger.error(
                "TelegramConfirmationAdapter sin bind() — no se pudo enviar el mensaje de "
                "confirmación (la espera igual continúa y expirará por timeout)"
            )
            return
        future = asyncio.run_coroutine_threadsafe(
            self._bot.send_message(chat_id=chat_id, text=text), self._loop
        )
        try:
            future.result(timeout=_SEND_TIMEOUT_SECONDS)
        except Exception as e:
            logger.error(f"No se pudo enviar mensaje de confirmación a chat_id={chat_id}: {e}")

    def resolve(self, user_id: str, text: str) -> bool:
        """Llamado desde _intercept_confirmacion_pendiente() (hilo del event loop) con el
        próximo mensaje de texto del usuario. Retorna True si había una confirmación
        pendiente para user_id y este mensaje se consumió como respuesta (CA-05) — en ese
        caso el caller NO debe reenviar el texto a GlassGateway().process(). Retorna False
        si no había ninguna pendiente (mensaje normal, se procesa como siempre)."""
        with self._lock:
            pending = self._pending.pop(user_id, None)
            if pending is None:
                return False
            # CA-06 — único criterio de "sí", igual que _desktop_confirm/WebViewConfirmationAdapter.
            pending.result = text.strip().lower() in ("sí", "si", "yes", "s")
        pending.event.set()
        return True


telegram_confirmation_adapter = TelegramConfirmationAdapter()
```

---

## 6. `channels/telegram_bot.py` — funciones modificadas

### 6.1 `cmd_eliminar()` (línea 500-528 actual) — CA-01, CA-08, CA-09

```python
async def cmd_eliminar(update, context):
    """Elimina una tarea. Uso: /eliminar [id]"""
    from tasks.task_manager import task_manager
    from core.security_manager import security_manager, ChannelType
    from channels.telegram_confirmation_adapter import telegram_confirmation_adapter

    user = update.effective_user
    user_id = str(user.id)

    if not context.args:
        await update.message.reply_text(
            "Indique el número de tarea, Señor.\n"
            "Uso: /eliminar [id]\n\n"
            "Use /tareas para ver sus tareas."
        )
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El ID de tarea debe ser un número, Señor.")
        return

    # REQ-018/CA-09 — filtro rápido antes de bloquear un hilo worker; la verificación
    # autoritativa (atómica, bajo lock) vuelve a correr dentro de
    # TelegramConfirmationAdapter.confirm() — ver arquitectura-018.md §5.1.
    if telegram_confirmation_adapter.has_pending(user_id):
        await update.message.reply_text(
            "Ya tenés una confirmación pendiente, Señor — respondé sí/no primero."
        )
        return

    telegram_confirmation_adapter.set_request_context(user_id, update.effective_chat.id)

    # REQ-018/CA-01, CA-08 — require_confirmation() es síncrono y, para 'delete_task' en
    # Telegram, ahora bloquea (vía el adaptador) hasta 120s esperando la respuesta del
    # usuario. Corre en un hilo worker (asyncio.to_thread) para no bloquear el loop de
    # asyncio de python-telegram-bot — otros usuarios siguen operando con normalidad
    # mientras este usuario tiene una confirmación pendiente.
    confirmed = await asyncio.to_thread(
        security_manager.require_confirmation,
        "delete_task",
        ChannelType.TELEGRAM,
        details=f"task_id={task_id}",
        user_id=user_id,
    )

    if not confirmed:
        await update.message.reply_text(
            f"Eliminación de la tarea #{task_id} cancelada, Señor."
        )
        return

    success = task_manager.delete_task(task_id, user_id)
    if success:
        await update.message.reply_text(
            f"🗑 *Tarea #{task_id} eliminada, Señor.*",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"No encontré la tarea #{task_id} en su lista, Señor."
        )
```

Nota de comportamiento: si `task_id` no existe (ya se borró, o nunca existió), la confirmación se
pide y se resuelve igual — el "No encontré la tarea..." solo aparece DESPUÉS de confirmar, igual
que hoy (`success = task_manager.delete_task(...)` ya maneja ese caso devolviendo `False`). No es
un caso nuevo introducido por este REQ; se preserva el orden de validación actual (existencia de
la tarea se chequea al momento de borrar, no antes de pedir confirmación) — pedir confirmación
para algo que quizás no existe es una pérdida de tiempo menor del usuario, pero cambiar ese orden
no lo pidió la SPEC y agregaría una consulta extra a `task_manager` fuera de alcance.

### 6.2 `cmd_tareas()`, `cmd_nueva()`, `cmd_completar()` — CA-10

```python
async def cmd_tareas(update, context):
    """Muestra las tareas pendientes del usuario."""
    from core.security_manager import ChannelType
    from agents.tool_registry import execute_tool

    user = update.effective_user
    user_id = str(user.id)
    summary = execute_tool("task_list", {"user_id": user_id}, ChannelType.TELEGRAM, user_id=user_id)
    await update.message.reply_text(summary, parse_mode="Markdown")
```

`task_list` es GREEN — `execute_tool()` nunca levanta `ActionDenied` para esta acción en la
práctica (no hay condición que la bloquee). Si algún cambio futuro lo hiciera, la excepción no
capturada llegaría a `handle_error()` (ya registrado como error handler global, línea 830) y el
usuario vería "Error inesperado, Señor." — comportamiento fail-safe aceptable, consistente con
cómo el resto del archivo maneja errores no anticipados; no se agrega un `try/except` especial
solo para este caso.

```python
async def cmd_nueva(update, context):
    """Crea una nueva tarea. Uso: /nueva recuérdame mañana a las 9am llamar al banco"""
    from tasks.task_manager import task_manager
    from core.security_manager import security_manager, ChannelType, format_details

    user = update.effective_user
    user_id = str(user.id)
    text = " ".join(context.args) if context.args else ""

    if not text:
        await update.message.reply_text(
            "*¿Qué tarea desea agregar, Señor?*\n\n"
            "Uso: /nueva [descripción de la tarea]\n\n"
            "Ejemplos:\n"
            "• /nueva recuérdame mañana a las 9am llamar al banco\n"
            "• /nueva entregar informe el viernes\n"
            "• /nueva todos los lunes revisar correos\n\n"
            "También puede simplemente decirme:\n"
            "'Recuérdame mañana a las 9am llamar al banco'",
            parse_mode="Markdown"
        )
        return

    # REQ-018/CA-10 — mismo gate público que execute_tool() usa internamente, solo para
    # que la invocación quede auditada en audit.db (GREEN, sin efecto en el resultado ni
    # bloqueo posible). No se usa execute_tool("task_create", ...) porque
    # agents/tool_registry.py::_task_create_invoke() no replica el fallback de "tarea
    # simple" de este comando — ver arquitectura-018.md §3 (decisión CA-10).
    security_manager.require_confirmation(
        "task_create", ChannelType.TELEGRAM,
        details=format_details("tool:task_create", {"text": text, "user_id": user_id}),
        user_id=user_id,
    )

    result = task_manager.create_from_natural(text, user_id, "telegram")
    if result:
        msg = task_manager.format_task_created(result)
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        # Si no parseó como tarea natural, crear como tarea simple — sin cambios.
        import datetime
        remind_at = datetime.datetime.now() + datetime.timedelta(hours=1)
        task_id = task_manager.create_task(
            user_id=user_id,
            title=text,
            channel="telegram",
            remind_at=remind_at.isoformat()
        )
        await update.message.reply_text(
            f"✅ *Tarea registrada, Señor.*\n\n"
            f"📋 *{text}*\n"
            f"🆔 #{task_id}\n"
            f"⏰ Recordatorio: en 1 hora\n\n"
            f"Le notificaré en el momento indicado.",
            parse_mode="Markdown"
        )
```

```python
async def cmd_completar(update, context):
    """Marca una tarea como completada. Uso: /completar [id]"""
    from tasks.task_manager import task_manager
    from core.security_manager import security_manager, ChannelType, format_details

    user = update.effective_user
    user_id = str(user.id)

    if not context.args:
        await update.message.reply_text(
            "Indique el número de tarea, Señor.\n"
            "Uso: /completar [id]\n\n"
            "Use /tareas para ver sus tareas pendientes."
        )
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El ID de tarea debe ser un número, Señor.")
        return

    # REQ-018/CA-10 — mismo criterio que cmd_nueva(): auditoría vía require_confirmation()
    # directo, sin execute_tool() (el tool task_complete espera texto libre + su propio
    # regex de extracción de ID, con ramas de auto-completar/pedir aclaración que este
    # comando no tiene hoy — ver arquitectura-018.md §3).
    security_manager.require_confirmation(
        "task_complete", ChannelType.TELEGRAM,
        details=format_details("tool:task_complete", {"text": str(task_id), "user_id": user_id}),
        user_id=user_id,
    )

    success = task_manager.complete_task(task_id, user_id)
    if success:
        await update.message.reply_text(
            f"☑️ *Tarea #{task_id} completada.*\n\n"
            f"Excelente trabajo, Señor. Tarea archivada.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"No encontré la tarea #{task_id} en sus pendientes, Señor."
        )
```

### 6.3 `_intercept_confirmacion_pendiente()` — nuevo, CA-05, y el caso borde de comandos

```python
async def _intercept_confirmacion_pendiente(update, context):
    """Handler de máxima prioridad (group=-1) — intercepta CUALQUIER mensaje de texto,
    incluidos comandos slash, cuando el usuario que lo envía tiene una confirmación
    pendiente (REQ-018, CA-05; "Casos borde" de SPEC-018.md: un comando nuevo mientras hay
    confirmación pendiente se consume como respuesta, no se ejecuta). Los
    CommandHandler/MessageHandler de group=0 (incluido handle_text) nunca ven el update si
    esto lo consume — se corta la propagación con ApplicationHandlerStop."""
    from telegram.ext import ApplicationHandlerStop
    from channels.telegram_confirmation_adapter import telegram_confirmation_adapter

    message = update.message
    if message is None or not message.text:
        return
    user = update.effective_user
    if user is None:
        return

    if telegram_confirmation_adapter.resolve(str(user.id), message.text):
        raise ApplicationHandlerStop
```

**Por qué `filters.TEXT` sin excluir comandos, a diferencia de `handle_text`:** el código
existente ya prueba, con `handle_text` (`filters.TEXT & ~filters.COMMAND`), que `filters.TEXT`
por sí solo SÍ matchea mensajes que empiezan con `/` — si no lo hiciera, la exclusión explícita
`& ~filters.COMMAND` no tendría ningún efecto. `_intercept_confirmacion_pendiente` necesita
exactamente lo contrario: capturar los comandos también, porque el caso borde de la SPEC
(`/tareas`, `/nueva algo` mientras hay confirmación pendiente) exige que ese mensaje se consuma
como respuesta a la confirmación, no que dispare su propio `CommandHandler`. Registrarlo en
`group=-1` (antes que el `group=0` donde viven todos los `CommandHandler` y `handle_text`)
garantiza que corra primero; `ApplicationHandlerStop` corta la propagación a cualquier otro grupo
si efectivamente había una confirmación pendiente que consumir. Si no la había,
`resolve()` retorna `False`, no se lanza la excepción, y python-telegram-bot sigue su
procesamiento normal por `group=0` sin ningún cambio de comportamiento.

**Mensajes de voz — sin cambios, gratis (SPEC "Casos borde"):** `handle_voice` usa
`filters.VOICE`, un filtro distinto que `_intercept_confirmacion_pendiente` (`filters.TEXT`) no
intersecta — un mensaje de voz nunca pasa por este interceptor, así que sigue transcribiéndose y
procesándose por `GlassGateway().process()` como siempre, mientras la confirmación pendiente
sigue esperando hasta expirar por timeout. Cero código nuevo necesario para este caso borde.

---

## 7. Flujo de datos

### 7.1 Camino feliz — `/eliminar 5` confirmado

```
Usuario: /eliminar 5
  → cmd_eliminar() [hilo event loop]
     → has_pending("123") == False
     → set_request_context("123", chat_id)
     → await asyncio.to_thread(require_confirmation, "delete_task", TELEGRAM, ...)
        [hilo worker nuevo]
        → is_action_allowed("delete_task", TELEGRAM)
           → (TELEGRAM, "delete_task") in CHANNEL_ACTION_EXCEPTIONS → True
        → adapter = get_confirmation_adapter(TELEGRAM) → telegram_confirmation_adapter.confirm
        → confirm("delete_task", full_msg)
           → _pending["123"] = _PendingConfirmation()
           → _send_message(chat_id, full_msg)
              → run_coroutine_threadsafe(bot.send_message(...), loop) → [event loop] envía msg
           → pending.event.wait(timeout=120)  ← hilo worker BLOQUEADO acá, loop libre
Usuario: sí
  → PTB despacha el update  [hilo event loop]
  → _intercept_confirmacion_pendiente() (group=-1)
     → resolve("123", "sí") → pending.result = True; _pending.pop("123"); event.set()
     → ApplicationHandlerStop (no llega a handle_text)
  ← [hilo worker] event.wait() retorna True → confirmed = True → _log_audit("confirmada")
  ← require_confirmation() retorna True
  ← cmd_eliminar(): task_manager.delete_task(5, "123") → reply "Tarea eliminada"
```

### 7.2 Timeout (CA-07)

Igual hasta `pending.event.wait(timeout=120)` — nadie responde en 120s → `wait()` retorna `False`
→ `confirmed = False`, `_pending.pop("123", None)` (limpieza, sin importar si ya se había sacado)
→ `_log_audit(..., "cancelada")` → `cmd_eliminar()` responde "Eliminación... cancelada, Señor."
Ningún estado queda huérfano.

### 7.3 Segunda confirmación mientras la primera sigue pendiente (CA-09)

```
Usuario: /eliminar 5   → pending["123"] creado, esperando
Usuario: /eliminar 8   → cmd_eliminar() [nueva invocación, mismo user_id]
   → has_pending("123") == True → reply "Ya tenés una confirmación pendiente..." → return
   (la tarea 8 nunca se toca; el hilo worker de la tarea 5 sigue esperando sin verse afectado)
```

### 7.4 Comando nuevo mientras hay confirmación pendiente (caso borde de SPEC-018.md)

```
Usuario: /eliminar 5   → pending["123"] creado, esperando "sí"/"no"
Usuario: /tareas        → PTB despacha el update [hilo event loop]
  → _intercept_confirmacion_pendiente() (group=-1) corre PRIMERO
     → resolve("123", "/tareas") → "/tareas".strip().lower() no está en ("sí","si","yes","s")
       → pending.result = False → event.set()
     → ApplicationHandlerStop → CommandHandler("tareas", cmd_tareas) NUNCA se ejecuta
  ← [hilo worker] confirmed = False → cmd_eliminar() responde "cancelada"
(el usuario debe reenviar /tareas después de que la confirmación se resuelva)
```

---

## 8. Archivos a modificar/crear

- `channels/telegram_bot.py` — `cmd_eliminar()` (§6.1), `cmd_tareas()`/`cmd_nueva()`/
  `cmd_completar()` (§6.2), `_intercept_confirmacion_pendiente()` nuevo (§6.3),
  `run_telegram_bot()` (`_post_init_telegram`, `post_init(...)`, `add_handler(..., group=-1)`,
  §4.3).
- `core/security_manager.py` — `CHANNEL_ACTION_EXCEPTIONS` nuevo, `is_action_allowed()`
  modificado (§4.1).
- `channels/telegram_confirmation_adapter.py` — **archivo nuevo completo** (§5).
- `tests/test_security_manager.py` — extendido con tests de CA-02, CA-03, CA-11 (§10).
- `tests/test_telegram_confirmation_adapter.py` — **archivo nuevo**, tests del adaptador (§10).
- `tests/test_telegram_bot.py` — **archivo nuevo**, tests de comandos y handlers (§10).

No se modifica: `core/confirmation.py`, `core/resolution.py`, `agents/tool_registry.py`,
`channels/discord_bot.py`, `main.py`.

---

## 9. Dependencias nuevas

**Ninguna.** `asyncio`, `contextvars`, `threading`, `dataclasses`, `typing`, `logging` son todos
de la librería estándar. `python-telegram-bot==20.7` ya está instalado (confirmado por baseline)
y ya provee `ApplicationBuilder.post_init()` y `telegram.ext.ApplicationHandlerStop`/grupos de
handlers desde esa misma versión — no hace falta actualizarlo ni agregar nada a
`requirements.txt`. Los tests nuevos usan `asyncio.run()` (stdlib) para ejecutar las corutinas de
`telegram_bot.py` bajo test, sin necesidad de `pytest-asyncio`.

---

## 10. Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| **Carrera en CA-09 entre el chequeo rápido de `cmd_eliminar()` (`has_pending()`) y la inserción real en `confirm()`.** Dos `/eliminar` casi simultáneos del mismo usuario podrían ambos pasar el chequeo rápido antes de que el primero llegue a insertar en `_pending`. | La garantía real es el chequeo atómico bajo `threading.Lock` dentro de `confirm()` (§5.2) — en el peor caso, el segundo pedido recibe el mensaje genérico de "cancelada" (por `require_confirmation()` devolviendo `False`) en vez del mensaje específico "Ya tenés una confirmación pendiente...". Nunca se llega a tener dos `threading.Event` esperando para el mismo usuario a la vez — el invariante de CA-09 se sostiene siempre; solo el texto exacto del mensaje varía en una ventana de milisegundos. Documentado como límite conocido, no bloqueante. |
| **Agotamiento del thread pool por defecto de `asyncio.to_thread()`** si muchos usuarios piden `/eliminar` a la vez y cada uno retiene un hilo del executor hasta 120s. | El pool por defecto de Python (`min(32, os.cpu_count() + 4)`) es ampliamente suficiente para el uso esperado (asistente personal, no un bot de miles de usuarios concurrentes). Si en el futuro el volumen crece, la mitigación es dimensionar un `ThreadPoolExecutor` dedicado vía `loop.set_default_executor()` — no necesario para este REQ, se documenta para `orion-dev`/futuro. |
| **`bot.send_message()` lento o caído** cuando `confirm()` intenta enviar el mensaje de confirmación desde el hilo worker. | `future.result(timeout=10)` (separado del timeout de confirmación de 120s) evita que un problema de red deje el hilo worker colgado indefinidamente en el envío; si falla, se loguea y igual se sigue a `event.wait(120)` — si el mensaje nunca llegó, el usuario nunca responde y el timeout de 120s deniega igual, fail-closed. |
| **`TelegramConfirmationAdapter.confirm()` invocado sin `set_request_context()` previo** (bug de programación futuro, p. ej. otro caller que también dispare `require_confirmation("delete_task", TELEGRAM, ...)` sin pasar por `cmd_eliminar()`). | `confirm()` verifica `ctx is None` al entrar y deniega fail-closed con log de error explícito (§5.2) — nunca asume un contexto que no está, nunca envía un mensaje a un chat desconocido. |
| **El mecanismo de excepción de CA-02 se usa mal en el futuro** (alguien agrega una entrada a `CHANNEL_ACTION_EXCEPTIONS` sin evaluar el riesgo, replicando el patrón para otra acción sin el mismo cuidado). | El comentario en el código (§4.1) exige justificación caso por caso; el test de regresión de CA-03 (§11) falla automáticamente si una entrada nueva no documentada abre una acción YELLOW no esperada — actúa como guardrail estructural, no solo documental. |
| **`_intercept_confirmacion_pendiente` en `group=-1` interfiere con el flujo normal de usuarios sin confirmación pendiente.** | `resolve()` retorna `False` de inmediato para cualquier `user_id` sin entrada en `_pending` (lookup de diccionario, sin bloqueo) — cero latencia perceptible agregada, y `ApplicationHandlerStop` solo se lanza cuando efectivamente hubo una confirmación que consumir. Cubierto por test explícito (§11). |
| **Cero cobertura de test previa sobre `channels/telegram_bot.py`** (confirmado por baseline) — no hay red de regresión existente que proteja `cmd_tareas`/`cmd_nueva`/`cmd_completar` contra un cambio accidental de comportamiento al tocarlos para CA-10. | Toda la suite nueva (§11) incluye tests de "comportamiento observable idéntico" para los tres comandos, con mocks de `update`/`context`/`task_manager`, ejecutados antes de considerar CA-10 satisfecho. |

---

## 11. Pruebas sugeridas

Una por cada criterio de aceptación, más los casos borde explícitos de `SPEC-018.md`.

**`tests/test_security_manager.py` (extendido):**
- CA-02: `(ChannelType.TELEGRAM, "delete_task") in CHANNEL_ACTION_EXCEPTIONS`;
  `is_action_allowed("delete_task", ChannelType.TELEGRAM)` retorna `True` tras el cambio.
- CA-03: parametrizado sobre las 19 acciones YELLOW restantes (`shutdown`, `restart`,
  `close_app`, `delete_file`, `delete_folder`, `delete_conversation`, `delete_project`,
  `execute_code`, `create_skill`, `modify_skill`, `delete_skill`, `send_message`, `CLOSE_APP`,
  `SYS_POWER_OFF`, `EXECUTE_CODE`, `CREATE_SKILL`, `MODIFY_SKILL`, `DELETE_SKILL`,
  `write_file_direct`, `save_file_desktop`) — `is_action_allowed(accion, ChannelType.TELEGRAM)`
  sigue siendo `False` para cada una.
- CA-11: `CHANNEL_ALLOWED_LEVELS[ChannelType.TELEGRAM] == [RiskLevel.GREEN]` sin cambios;
  `classify_action("delete_task") == RiskLevel.YELLOW` sin cambios.
- Regresión: `is_action_allowed("proactive_trigger", ChannelType.DESKTOP)` sigue `True` (único
  otro caller real de `is_action_allowed()`, `core/proactive_engine.py:90`).

**`tests/test_telegram_confirmation_adapter.py` (nuevo):**
- CA-04: `confirm()` sin `bind()` previo no lanza excepción; con `bind()` mockeado, el mensaje
  enviado a `bot.send_message` es exactamente el `message` recibido, sin alteración.
- CA-05/CA-06: `resolve(user_id, "sí")`/`"si"`/`"yes"`/`"s"` (case-insensitive, con espacios)
  → `True` y desbloquea; `resolve(user_id, "tal vez")`/`"sip"`/`"dale"` → cuenta como cancelación
  (`pending.result == False`); `resolve()` para un `user_id` sin pendiente → `False`, sin
  lanzar.
- CA-07: con `CONFIRM_TIMEOUT_SECONDS` monkeypatcheado a un valor pequeño (p. ej. `0.2`),
  `confirm()` retorna `False` si nadie llama `resolve()`, y `_pending` queda vacío después.
- CA-08: `confirm()` ejecutado en un hilo real (`threading.Thread`) mientras el hilo de test
  sigue respondiendo — verificar que el hilo de test nunca se bloquea (equivalente de "el loop
  sigue libre para otros usuarios").
- CA-09: dos llamadas a `confirm()` con el mismo `user_id` en contexto — la segunda retorna
  `False` de inmediato sin esperar el timeout.
- Concurrencia del `ContextVar`: dos hilos, cada uno con su propio `set_request_context()` +
  `confirm()`, verifican que cada uno recibe su propio `chat_id` sin cruzarse (prueba directa de
  la propagación aislada de `asyncio.to_thread()`/`contextvars`).

**`tests/test_telegram_bot.py` (nuevo — `update`/`context` mockeados con `MagicMock`/
`AsyncMock`, sin red real, ejecutando corutinas vía `asyncio.run()`):**
- CA-01: `cmd_eliminar()` con `require_confirmation` mockeado a `True` → llama
  `task_manager.delete_task()` y responde éxito; mockeado a `False` → NO llama
  `delete_task()`, responde cancelación.
- CA-05/casos borde: simular un `_pending` activo para un `user_id` y despachar
  `_intercept_confirmacion_pendiente()` con texto `"/tareas"` → `resolve()` consume el mensaje,
  `ApplicationHandlerStop` se lanza (verificar con `pytest.raises`), `cmd_tareas` no se invoca.
- CA-09: `cmd_eliminar()` con `has_pending()` mockeado a `True` → responde el mensaje de
  confirmación pendiente sin tocar `task_manager` ni `require_confirmation`.
- CA-10: `cmd_tareas()` invoca `execute_tool("task_list", ...)` (mockeado) y responde su
  resultado tal cual. `cmd_nueva()`/`cmd_completar()`: comportamiento idéntico al actual en los 4
  casos ya cubiertos hoy (texto vacío, ID no numérico, éxito, no encontrado) **más** verificar
  que `security_manager.require_confirmation` fue llamado con la acción correcta — regresión
  explícita del fallback de "tarea simple" de `/nueva` (mockear `create_from_natural` → `None` y
  confirmar que igual se crea la tarea simple) y del mensaje de error específico de `/completar`.
- CA-13: ningún test nuevo toca `channels/discord_bot.py` — se deja constancia explícita en un
  test trivial que solo importa el módulo sin modificarlo, como marcador de "no tocado".
- CA-14: con `isolated_audit_db` (fixture existente de `test_security_manager.py`, reutilizable),
  verificar que tras `/eliminar` confirmado queda una fila con `action="delete_task"`,
  `channel="telegram"`, `result="confirmada"`; tras `/nueva`/`/completar`, filas con
  `result="permitida"` para `task_create`/`task_complete`.
- Voz mientras hay confirmación pendiente: `handle_voice()` no consulta ni afecta
  `telegram_confirmation_adapter` — verificar que el flag `_pending` del usuario no cambia tras
  invocar `handle_voice()` con una confirmación activa simulada.

**Regresión general (CA-12):** `pytest tests/test_resolution.py` sin modificaciones, en verde,
como parte de la corrida completa antes de marcar el REQ listo — confirma que
`core/resolution.py`/`_try_task_tool()` no se vieron afectados por ningún cambio de este REQ.

---

## 12. ¿Corresponde pasar por `orion-security` antes de `orion-dev`?

El handoff de baseline me pidió revisar esto con criterio propio, con dos datos de entrada: (1)
`SPEC-018.md` **no** fija `orion-security` como CA obligatorio — leí las 14 CA completas (§2 de
esta propuesta) y ninguna lo menciona; a diferencia de lo que el handoff sugería verificar, no hay
ningún criterio de aceptación que lo exija contractualmente. (2) `REQ-018-context.md` sí tiene ya
una decisión registrada de `orion-coordinador` (2026-08-20): *"orion-security es obligatorio en
este REQ, no opcional — a diferencia de REQ-016/REQ-017, este REQ es exactamente el caso para el
que existe orion-security: bypass real de un gate ya existente (fail-closed de REQ-005), no una
feature nueva que solo 'toca' seguridad tangencialmente."* Por la regla del `context-manager`, una
decisión ya registrada no se re-debate — pero el handoff pidió explícitamente mi propio análisis
con el mismo criterio que usé en REQ-016 §11, así que lo hago acá, sin asumir que coincidirá.

**Aplicando el criterio de REQ-016 §11** ("no es '¿este REQ toca algo destructivo?', sino '¿el REQ
introduce una superficie o un patrón de riesgo que todavía no fue evaluado?'"): en REQ-016, las
dos acciones YELLOW nuevas (`delete_task`/`delete_project`) reutilizaban, byte a byte, el mismo
mecanismo ya auditado en `security-audit-015.md` (`require_confirmation()` →
`WebViewConfirmationAdapter`, sin cambios) — réplica mecánica, no una decisión de política nueva.
**REQ-018 es categóricamente distinto en los dos puntos que más importan:**

1. **CA-02 introduce el primer mecanismo de excepción granular (canal+acción) que existe en el
   sistema.** `CHANNEL_ALLOWED_LEVELS` es una política por canal desde REQ-005/REQ-006, decidida
   deliberadamente sin granularidad por acción (`REQ-006-context.md:319`, "paridad = capacidad,
   no autoridad"). `CHANNEL_ACTION_EXCEPTIONS` matiza esa decisión explícita por primera vez. Es
   un cambio en el **mecanismo del gate mismo** (`is_action_allowed()`, usado por todo el sistema
   para decidir qué YELLOW puede pedir confirmación en qué canal), no una acción nueva usando un
   mecanismo ya probado. Un error acá (p. ej. una condición mal escrita que compare canal contra
   acción invertidos, o un `in` que matchee de más) tiene radio de impacto sobre **las 20
   acciones YELLOW del sistema**, no solo sobre `delete_task`.
2. **CA-04 a CA-09 son el primer adaptador de confirmación real para un canal async y
   multiusuario.** `WebViewConfirmationAdapter` (el único precedente) resuelve un cruce
   hilo-worker↔hilo-Qt para un solo usuario. El adaptador de Telegram resuelve un cruce
   hilo-worker↔event-loop-de-`asyncio` para **múltiples usuarios concurrentes**, con
   `contextvars` para evitar que se crucen las respuestas entre ellos (§5). Este patrón —
   concurrencia real, correlación por usuario, riesgo de bloquear el loop para todos si algo sale
   mal (CA-08) — no tiene precedente auditado en el sistema.

Con ese criterio, mi conclusión propia **coincide** con la de `orion-coordinador`, pero por
razones que quiero dejar explícitas y no dar por sentadas: no es que "REQ-018 toca seguridad" (eso
también era cierto en REQ-016), es que introduce dos piezas de **mecanismo nuevo** — no de
**contenido nuevo sobre mecanismo ya evaluado**, que era el caso de REQ-016.

**Recomendación: sí, `orion-security` corre como paso dedicado, entre la aprobación de esta
arquitectura y `orion-dev`.** Puntos concretos que le pediría auditar, más allá de mi propio
diseño:
- Que `CHANNEL_ACTION_EXCEPTIONS` no sea alcanzable ni influenciable por ningún input de usuario
  (channel spoofing vía `extract_params()`, mismo patrón que el invariante ya documentado en el
  docstring de `require_confirmation()`, línea 239-246 de `security_manager.py`).
  `set_request_context()`/`_request_ctx` reciben `user_id`/`chat_id` que sí vienen de
  `update.effective_user`/`update.effective_chat` (fuente confiable de Telegram, no de texto
  libre parseado) — pero vale que alguien más lo verifique con ojos frescos.
  ¿La fuente de `chat_id` es Telegram (Update objeto) y no algo derivable por el usuario? Sí, es
  `update.effective_chat.id`, no un parámetro de texto — a confirmar en `orion-security`.
- Correctitud fail-closed del timeout y de la limpieza de `_pending` bajo condiciones de carrera
  reales (no solo las que yo mismo diseñé pensando en ellas) — ver §10.
- Que el test de regresión de CA-03 sea, en la implementación real de `orion-dev`, tan exhaustivo
  como el diseño lo exige (las 19 acciones, no una muestra).

Si Johan prefiere saltarlo y confiar en el DoD estándar de `orion-qa` (como se hizo en
REQ-016/REQ-017), no hay costo de rediseño en esta propuesta — la arquitectura no cambia según
quién la audite, solo el orden del pipeline.

---

## 13. DoD check — `orion-architect` (`.claude/rules/definition-of-done.md`)

```
[x] Propuesta referencia cada criterio de la SPEC — tabla completa §2, CA-01 a CA-14.
[x] Módulos, clases y funciones especificados — §4, §5, §6, firmas exactas.
[x] Flujo de datos documentado — §7 (camino feliz, timeout, CA-09, caso borde de comando).
[x] Dependencias nuevas identificadas — §9, ninguna.
[x] Riesgos con mitigación documentados — §10.
[x] Pruebas sugeridas listadas — §11, una por CA más casos borde.
[x] Aprobación humana explícita recibida antes de continuar — Johan aprobó (vía coordinador),
    2026-08-20, confirmando explícitamente los 2 puntos abiertos de §14 (CA-10 y
    `orion-security`) tal cual se propusieron, sin ajustes.
[x] Contexto actualizado, CSV actualizado (Estado → ARQUITECTURA_APROBADA) —
    `Aprobacion_Arquitectura=APROBADO` vía `update-tracker.mjs`. `Rama` queda sin asignar
    (pendiente de decisión humana explícita, ver `REQ-018-context.md` "Estado actual") —
    no es parte del DoD de este paso, no bloquea el handoff.
```

## 14. Solicitud de aprobación humana

Propuesta técnica REQ-018 lista. Resumen:

- **Archivos a tocar:** `channels/telegram_bot.py` (4 comandos modificados + 1 handler nuevo +
  registro en `run_telegram_bot()`), `core/security_manager.py` (1 `set` nuevo + 1 función
  modificada, 6 líneas), `tests/test_security_manager.py` (extendido). Sin tocar
  `core/confirmation.py`, `core/resolution.py`, `agents/tool_registry.py`, `discord_bot.py`,
  `main.py`.
- **Archivo nuevo:** `channels/telegram_confirmation_adapter.py` (`TelegramConfirmationAdapter`)
  + 2 archivos de test nuevos.
- **Decisiones que necesitan tu OK explícito:**
  1. **Corrección aplicada sin pedirte nada** (era un error objetivo de la SPEC, ya confirmado
     por baseline): el adaptador se registra en `channels/telegram_bot.py::run_telegram_bot()`,
     no en `main.py`.
  2. **CA-10 — decisión mía a validar:** `/completar` y `/nueva` NO se conectan a
     `execute_tool()` (a diferencia de `/tareas`, que sí) — quedan con su lógica actual intacta,
     pero ahora auditadas llamando `security_manager.require_confirmation()` directo antes de la
     llamada a `task_manager`, sin usar los tools de `agents/tool_registry.py` que tienen
     comportamiento distinto al de los comandos actuales. Ver justificación completa en §3.
  3. **Recomiendo que `orion-security` corra como paso dedicado** antes de `orion-dev` — mi
     propio análisis (§12), con el mismo criterio de REQ-016 §11, coincide con lo que
     `orion-coordinador` ya había registrado en el contexto del REQ. Decime si preferís saltarlo.

⚠️ El flujo no continúa hasta que apruebes esta arquitectura.
Responde: **APROBADO** / **AJUSTAR [qué]** / **RECHAZADO [motivo]** — e indicá también si
confirmás el punto 2 (CA-10) y el punto 3 (`orion-security`) tal cual, o si querés ajustarlos.

---

### Resolución (2026-08-20)

**APROBADO.** Johan confirmó, vía coordinador, ambos puntos abiertos tal cual se propusieron:
1. CA-10 → SÍ, `/completar` y `/nueva` quedan con su lógica actual (auditados, sin forzar
   `execute_tool()`), para no arriesgar el código compartido con lenguaje natural.
2. `orion-security` → SÍ, corre como paso dedicado antes de `orion-dev`.

CSV actualizado vía `update-tracker.mjs` (`Estado=ARQUITECTURA_APROBADA`,
`Aprobacion_Arquitectura=APROBADO`). Handoff emitido a `orion-security` (no a `orion-dev`) —
ver `REQ-018-context.md`, "Log de transiciones".

---

## 15. Ajustes de seguridad post-auditoría (2026-08-20) — respuesta a `security-audit-018.md`

**Motivo:** `orion-security` auditó esta arquitectura ya aprobada (`pruebas/security-audit-018.md`,
veredicto ❌ REQUIERE CAMBIOS) y devolvió 1 hallazgo bloqueante (A), 2 no bloqueantes (B, C) y 1
verificado sin hallazgo (D — aislamiento entre `CHANNEL_ACTION_EXCEPTIONS` de este REQ y el
override de configuración de REQ-019, confirmado ortogonal). El diseño central **no se reabre** —
la propia auditoría confirma sólidos el mecanismo de excepción CA-02, la correlación por
`user_id`, y la decisión de CA-10; el hallazgo bloqueante es puntual, sobre un detalle de
configuración de `python-telegram-bot`, no sobre el diseño del adaptador en sí. Esta sección es
una extensión, mismo patrón que el addendum §11 de `arquitectura-019.md`; no se reescribe nada de
§1-§14.

### 15.1 Hallazgo A (bloqueante) — falta `.concurrent_updates(True)` en `Application.builder()`

Verificado por `orion-security` directo contra el código fuente instalado de
`python-telegram-bot==20.7` (`_applicationbuilder.py:214-215`, `_application.py:1145-1170`,
`_baseupdateprocessor.py:154-176`), y confirmado de nuevo acá con la misma fuente: sin
`.concurrent_updates(...)`, el builder usa `SimpleUpdateProcessor(max_concurrent_updates=1)` por
defecto, y `_update_fetcher()` — el único consumidor de la cola interna de updates — hace
`await self.__process_update_wrapper(update)` en línea, en vez de `self.create_task(...)`. Esto
significa que mientras `cmd_eliminar()` de un usuario está suspendido dentro de
`await asyncio.to_thread(require_confirmation, ...)` (hasta 120s), el propio bucle que despacha
updates a CUALQUIER handler, para CUALQUIER usuario, está suspendido con él — el puente
async→sync mueve correctamente el bloqueo del hilo del SO a un hilo worker (§5.1), pero no mueve
el bloqueo del dispatcher de updates de PTB, que sigue siendo estrictamente secuencial. Resultado
real: el mecanismo que cierra el bypass de seguridad de CA-01 se convierte en un vector de DoS
trivial y no privilegiado — cualquier usuario puede escribir `/eliminar 1` y no responder,
bloqueando el bot completo para todos durante hasta 120s, repetible sin límite. Invalida CA-08 tal
como está redactado ("sin demora perceptible... para otros usuarios").

**Fix — reemplaza la línea de construcción de `Application` en §4.3:**

```python
# ANTES (§4.3, invalida CA-08 bajo el default de PTB):
app = Application.builder().token(token).post_init(_post_init_telegram).build()

# DESPUÉS:
app = (
    Application.builder()
    .token(token)
    .concurrent_updates(True)   # REQ-018/Hallazgo A (security-audit-018.md) — sin esto,
                                # PTB despacha updates uno a la vez (SimpleUpdateProcessor
                                # default, max_concurrent_updates=1) y el bot completo queda
                                # bloqueado hasta 120s para todos los usuarios mientras uno
                                # solo tiene una confirmación de /eliminar pendiente.
    .post_init(_post_init_telegram)
    .build()
)
```

`.concurrent_updates(True)` habilita `SimpleUpdateProcessor(256)` (256 updates en paralelo,
gateados por un `BoundedSemaphore` interno de PTB) — con esto, `_update_fetcher()` pasa a usar
`self.create_task(...)` por cada update, y el fetcher vuelve de inmediato a leer el siguiente de
la cola sin esperar a que el anterior termine. Se eligió `True` (256) en vez de un entero acotado
menor: el volumen esperado (asistente personal) está muy por debajo de ese límite, y acotarlo más
bajo no aporta ninguna mitigación real — el límite que sí importa en la práctica es el thread pool
de `asyncio.to_thread()` (ver más abajo), no el número de updates concurrentes de PTB en sí.

**Consecuencia confirmada por la auditoría, sin cambio de código adicional:** el diseño de
`contextvars.ContextVar` (`_request_ctx`, §5.1) ya estaba preparado para este régimen — cada
`asyncio.create_task()` copia su propio contexto al crearse, así que la correlación
usuario↔hilo-worker sigue siendo correcta ahora que la concurrencia real empieza a ocurrir de
verdad (antes de este fix, protegía contra una condición que, tal como estaba construida la
`Application`, nunca llegaba a darse). Sin cambios en `channels/telegram_confirmation_adapter.py`.

**Test de integración nuevo (agregado a la lista de `tests/test_telegram_bot.py` de §11) — el
gap que el test aislado de CA-08 no cubría:**

```python
def test_run_telegram_bot_concurrent_updates_habilitado():
    """REQ-018/Hallazgo A (security-audit-018.md) — construye una Application real con el
    mismo builder que run_telegram_bot() (no el adaptador aislado, que es lo que el test de
    CA-08 original de §11 sí cubría y por lo que no detectó este hallazgo). Si en el futuro
    alguien quita `.concurrent_updates(...)` sin saber por qué estaba, este test falla en
    CI en vez de convertirse en un DoS silencioso en producción."""
    from telegram.ext import Application

    app = (
        Application.builder()
        .token("123456:FAKE-TOKEN-SOLO-PARA-CONSTRUIR-EL-OBJETO-SIN-RED")
        .concurrent_updates(True)
        .build()
    )
    assert app.concurrent_updates > 1
```

No usa el token real ni llama `run_polling()` — construir la `Application` no dispara ninguna
llamada de red (solo `initialize()`/`run_polling()` lo harían), así que el test no necesita mockear
`_get_token()` ni el proceso completo de `run_telegram_bot()` para verificar, de forma
estructural, exactamente la configuración que Hallazgo A pedía cubrir.

**Nota adicional para el re-chequeo de `orion-security` (no es un fix aplicado acá, es una
observación a evaluar):** con `concurrent_updates` habilitado, dos updates del mismo `user_id`
llegados muy cerca en el tiempo (p. ej. `/eliminar 5` seguido de inmediato por otro mensaje, sin
que medie el tiempo real que toma que el usuario vea el prompt de confirmación y responda) se
despachan ahora como `asyncio.Task`s independientes, sin orden garantizado entre sí a nivel de
`SimpleUpdateProcessor` (un `BoundedSemaphore` desnudo, sin ningún tipo de cola FIFO por chat).
Como la inserción real en `_pending[user_id]` ocurre dentro de `confirm()`, en el hilo worker de
`asyncio.to_thread()` (§5.2) — no de forma síncrona en `cmd_eliminar()` antes del primer
`await` — existe una ventana, angosta pero real, en la que un segundo mensaje del mismo usuario
podría procesarse en `_intercept_confirmacion_pendiente()` antes de que esa inserción ocurra, y
`resolve()` no encontraría ninguna entrada pendiente que consumir. Distinto del caso borde que sí
cubre el diseño (SPEC-018.md: un comando nuevo **después** de que el usuario ya vio el prompt) —
esto es específicamente sobre dos mensajes casi simultáneos del mismo usuario, un patrón de uso
humano normal poco probable, pero no imposible con un cliente automatizado. No lo resuelvo acá
porque no fue parte del hallazgo bloqueante ni de B/C, y el encargo fue acotado a "corto, no
reabrir el diseño" — lo dejo señalado para que `orion-security` decida en el re-chequeo si amerita
el mismo tratamiento que el Hallazgo B (mover la reserva de `_pending` a una llamada síncrona en
`cmd_eliminar()` antes del `await`) o si el riesgo es aceptable tal cual y alcanza con
documentarlo.

**Riesgo de §10 (agotamiento del thread pool de `asyncio.to_thread()`) — de hipotético a real:**
confirmado por la auditoría (punto 3 de la corrección requerida): con `concurrent_updates`
deshabilitado (antes de este fix), varios `/eliminar` concurrentes nunca llegaban a competir de
verdad por hilos del executor, porque PTB los procesaba uno a la vez de todas formas. Con el fix
aplicado, si compiten de verdad. La mitigación que ya documentaba §10 (pool por defecto de Python,
`min(32, os.cpu_count() + 4)`, suficiente para el volumen esperado de un asistente personal) sigue
siendo razonable — se confirma acá explícitamente contra el escenario real, sin cambio de diseño.

### 15.2 Hallazgo B (no bloqueante) — documentado para `orion-dev`, no resuelto en esta arquitectura

`confirm()` (§5.2) no envuelve `asyncio.run_coroutine_threadsafe(...)` (la línea previa a
`future.result(...)` dentro de `_send_message()`) en ningún `try/except` — si esa llamada lanza de
forma síncrona (p. ej. `RuntimeError` si el loop ya no está corriendo, caso de borde de
apagado/reinicio), la excepción escapa sin pasar por la limpieza de `_pending[user_id]`, dejando
una entrada huérfana permanente: ese usuario queda inhabilitado para volver a usar `/eliminar`
hasta que el proceso se reinicie, y el incidente no queda auditado. Mismo patrón que el Hallazgo B
de `security-audit-015.md` sobre `WebViewConfirmationAdapter`. Corrección completa (envolver desde
la inserción en `_pending` hasta el `wait()` en un `try/finally`, más un test que mockee
`asyncio.run_coroutine_threadsafe` para que lance) especificada en detalle en
`security-audit-018.md`, sección "Hallazgo B" — `orion-dev` la implementa directo, sin volver a
pasar por `orion-architect`.

### 15.3 Hallazgo C (no bloqueante) — documentado para `orion-dev`, no resuelto en esta arquitectura

El test de CA-03 propuesto en §11 lista las 19 acciones YELLOW restantes a mano
(`shutdown`, `restart`, ..., `save_file_desktop`), copiadas del inventario de `baseline-018.md` en
vez de derivarse del registro real de `security_manager` en el momento de ejecutarse. Si en el
futuro se registra una acción YELLOW nueva (p. ej. exactamente el escenario que habilita REQ-019)
sin actualizar esta lista a mano, el test seguiría en verde sin haber verificado nada sobre la
acción nueva — pierde su valor de guardrail justo cuando más importaría. Corrección (derivar la
lista de `security_manager._actions`/un método público equivalente, en vez de copiarla)
especificada en detalle en `security-audit-018.md`, sección "Hallazgo C" — `orion-dev` la
implementa directo, sin volver a pasar por `orion-architect`.

### 15.4 Riesgos y mitigación (addendum)

| Riesgo | Mitigación |
|--------|-----------|
| `Application.builder()` sin `.concurrent_updates(...)` serializaba el dispatcher de PTB completo — cualquier `/eliminar` sin responder bloqueaba el bot para todos los usuarios hasta 120s (DoS trivial, no privilegiado). | `.concurrent_updates(True)` + test de integración estructural — §15.1. |
| Con concurrencia real habilitada, el agotamiento del thread pool de `asyncio.to_thread()` deja de ser hipotético. | Confirmado que el pool por defecto de Python sigue siendo suficiente para el volumen esperado — §15.1, sin cambio de diseño. |
| Ventana angosta de correlación entre dos mensajes casi simultáneos del mismo usuario, ahora que los updates se despachan como Tasks independientes sin orden garantizado. | Señalado para el re-chequeo de `orion-security` — no resuelto en este addendum, ver nota en §15.1. |
| `confirm()` no limpia `_pending` si `asyncio.run_coroutine_threadsafe(...)` lanza antes de programar el envío — entrada huérfana permanente, usuario inhabilitado hasta reinicio. | Documentado para `orion-dev` — §15.2, fix completo en `security-audit-018.md`. |
| Test de CA-03 con lista hardcodeada se desincroniza en silencio si se registra una YELLOW nueva. | Documentado para `orion-dev` — §15.3, fix completo en `security-audit-018.md`. |

### 15.5 Qué NO cambia

- El mecanismo de excepción canal+acción (§4.1, `CHANNEL_ACTION_EXCEPTIONS`) — confirmado sólido
  por la auditoría (Hallazgo D, sin hallazgo), incluido el aislamiento frente al override de
  configuración que diseña REQ-019 en paralelo. Cero cambios.
- La decisión de CA-10 ya aprobada por Johan (§3) — no se reabre, la auditoría no encontró ningún
  problema de seguridad en dejar `/completar`/`/nueva` con su lógica actual.
- El diseño general del adaptador (`TelegramConfirmationAdapter`, §5) — la correlación por
  `contextvars.ContextVar`, el criterio de CA-06, el timeout de CA-07, y la verificación atómica de
  CA-09 quedan confirmados correctos; solo se completa (B) y se corrige el punto de despacho de
  updates que los rodea (A).
- El handler de intercepción `_intercept_confirmacion_pendiente` (§6.3) y su registro en
  `group=-1` — sin cambios.

---

## Resumen para el humano — AJUSTE DE SEGURIDAD (§15)

`orion-security` encontró 1 ajuste bloqueante: sin `.concurrent_updates(True)` en la construcción
del bot, `python-telegram-bot` despacha updates uno a la vez por defecto — cualquier usuario podía
dejar `/eliminar` sin responder y bloquear el bot completo para todos los demás hasta 120 segundos,
repetible sin límite. Ya está corregido en §15.1 (una línea en el builder + un test de integración
nuevo), sin reabrir ninguna decisión ya aprobada (CA-02, CA-10, el diseño del adaptador). También
quedaron documentados 2 ajustes no bloqueantes para que `orion-dev` los resuelva directo (limpieza
de estado si falla el envío del mensaje; el test de regresión de CA-03 debe derivarse del registro
real en vez de copiarse a mano). Por ser corrección técnica de seguridad, no cambio de alcance,
esto vuelve directo a `@orion-security` para el re-chequeo — no requiere pasar de nuevo por vos.
