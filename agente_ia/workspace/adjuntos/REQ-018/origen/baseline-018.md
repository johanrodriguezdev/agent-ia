# Baseline REQ-018 — Confirmación conversacional para `/eliminar` en Telegram

**Agente:** orion-baseline | **Fecha:** 2026-08-20 | **Precede a:** orion-architect

Verificación exhaustiva sobre código real (no se asume lo investigado por `orion-spec`, aunque
se confirma coincidente salvo lo señalado en "Discrepancias nuevas encontradas" más abajo).

## Estado actual del sistema

### 1. `channels/telegram_bot.py` — comandos slash y handler de texto (código real)

**`cmd_tareas()` (línea 416-421):**
```python
async def cmd_tareas(update, context):
    """Muestra las tareas pendientes del usuario."""
    from tasks.task_manager import task_manager
    user = update.effective_user
    summary = task_manager.get_task_summary(str(user.id))
    await update.message.reply_text(summary, parse_mode="Markdown")
```
Llama `task_manager.get_task_summary(user_id)` directo. Sin gate, sin auditoría.

**`cmd_nueva()` (línea 424-465):**
```python
async def cmd_nueva(update, context):
    """Crea una nueva tarea. Uso: /nueva recuérdame mañana a las 9am llamar al banco"""
    from tasks.task_manager import task_manager
    user = update.effective_user
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text(...)  # uso/ejemplos
        return
    result = task_manager.create_from_natural(text, str(user.id), "telegram")
    if result:
        msg = task_manager.format_task_created(result)
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        # Si no parseó como tarea natural, crear como tarea simple
        import datetime
        remind_at = datetime.datetime.now() + datetime.timedelta(hours=1)
        task_id = task_manager.create_task(
            user_id=str(user.id), title=text, channel="telegram",
            remind_at=remind_at.isoformat()
        )
        await update.message.reply_text(f"✅ *Tarea registrada...* ... ⏰ Recordatorio: en 1 hora ...")
```
**Tiene un fallback que crea una tarea simple con recordatorio a 1 hora cuando
`create_from_natural()` no puede parsear el texto.** Ver "Discrepancias nuevas" — el tool
`task_create` de `agents/tool_registry.py` NO tiene este fallback.

**`cmd_completar()` (línea 468-497):**
```python
async def cmd_completar(update, context):
    """Marca una tarea como completada. Uso: /completar [id]"""
    from tasks.task_manager import task_manager
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("Indique el número de tarea, Señor. Uso: /completar [id] ...")
        return
    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El ID de tarea debe ser un número, Señor.")
        return
    success = task_manager.complete_task(task_id, str(user.id))
    if success:
        await update.message.reply_text(f"☑️ *Tarea #{task_id} completada.* ...", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"No encontré la tarea #{task_id} en sus pendientes, Señor.")
```
Requiere ID numérico explícito. Llama `task_manager.complete_task(task_id, user_id)` directo —
bool. Ver "Discrepancias nuevas" — el tool `task_complete` no tiene esta forma de invocación.

**`cmd_eliminar()` (línea 500-528) — el bypass real:**
```python
async def cmd_eliminar(update, context):
    """Elimina una tarea. Uso: /eliminar [id]"""
    from tasks.task_manager import task_manager
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("Indique el número de tarea, Señor. Uso: /eliminar [id] ...")
        return
    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("El ID de tarea debe ser un número, Señor.")
        return
    success = task_manager.delete_task(task_id, str(user.id))
    if success:
        await update.message.reply_text(f"🗑 *Tarea #{task_id} eliminada, Señor.*", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"No encontré la tarea #{task_id} en su lista, Señor.")
```
Llama `task_manager.delete_task(task_id, user_id) -> bool` **directo**, sin
`security_manager.require_confirmation("delete_task", ...)`, sin `execute_tool()`, sin entrada en
`audit.db`. `delete_task` está registrado `RiskLevel.YELLOW` en
`core/security_manager.py:316` (`_register_default_actions()`). Confirmado: es el único bypass
con impacto real de autorización (no solo de auditoría) de todo el archivo.

**`handle_text()` (línea 533-562):**
```python
async def handle_text(update, context):
    from channels.gateway import GlassGateway, GlassMessage, MessageType
    user = update.effective_user
    text = (update.message.text or "").strip()
    if not text:
        return
    voice_mode = context.user_data.get("voice_mode", False)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    # REQ-006/B6: comentario sobre resolve() gateando SYS_POWER_OFF, etc.
    msg = GlassMessage(
        user_id=str(user.id), user_name=user.first_name or "Usuario",
        text=text, channel="telegram", msg_type=MessageType.TEXT
    )
    response = GlassGateway().process(msg)
    await _send_response(update, context, response, send_voice=voice_mode)
```
Registrado en `run_telegram_bot()` (línea 824-826) como
`MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)` — solo intercepta texto que NO
empieza con `/`. Hoy no tiene ningún mecanismo para interceptar "la próxima respuesta del
usuario" antes de pasarla a `GlassGateway().process()`. CA-05/CA-06 de SPEC-018 exigen que un
handler nuevo, o esta misma función con lógica agregada al inicio, intercepte el texto cuando el
`user_id` tiene una confirmación pendiente — hoy ese camino no existe en absoluto.

### 2. Registro de comandos y arranque del bot — hallazgo importante para `orion-architect`

`run_telegram_bot()` (línea 773-841) es un **punto de entrada standalone**, no una función que
`main.py` importe o invoque:
```python
def run_telegram_bot():
    ...
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    ...
    app.add_handler(CommandHandler("tareas", cmd_tareas))
    app.add_handler(CommandHandler("nueva", cmd_nueva))
    app.add_handler(CommandHandler("completar", cmd_completar))
    app.add_handler(CommandHandler("eliminar", cmd_eliminar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    ...
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    run_telegram_bot()
```
Se ejecuta como `python channels/telegram_bot.py`, proceso separado del de `main.py`
(desktop/WebView). Confirmado con grep: `main.py` **no importa `channels.telegram_bot` en
ningún punto** — el único rastro de "telegram" en `main.py` es un comentario en la línea 106
(`task_scheduler.start()   # REQ-016/CA-10 — antes solo arrancaba desde
channels/telegram_bot.py`), que documenta justamente que son procesos distintos.

## Discrepancias nuevas encontradas (no estaban en la investigación de `orion-spec`)

1. **SPEC-018.md, "Módulos afectados", dice que `main.py` "registra el adaptador nuevo al
   iniciar el bot de Telegram, análogo a como ya registra
   `register_confirmation_adapter(ChannelType.DESKTOP, _desktop_confirm)` (línea 59)".** Esto no
   es correcto tal como está escrito: `main.py` nunca inicia el bot de Telegram — son dos
   procesos distintos (ver punto anterior). El registro de
   `register_confirmation_adapter(ChannelType.TELEGRAM, ...)` para que exista en el proceso
   correcto en runtime **tiene que hacerse dentro de `channels/telegram_bot.py::run_telegram_bot()`**
   (antes de `app.run_polling()`), no en `main.py`. Señalar a `orion-architect` para que lo corrija
   en la propuesta — no se resuelve acá.

2. **CA-10 ("comportamiento observable idéntico") es más delicado de lo que sugiere la SPEC para
   `/nueva` y `/completar`** — verificado en `agents/tool_registry.py:92-149`:
   - El tool `task_create` (`_task_create_invoke`, línea 92-100) llama
     `task_manager.create_from_natural(...)` y si devuelve `None` responde
     `"No pude interpretar esa tarea, Señor."` — **no tiene el fallback que sí tiene
     `cmd_nueva()` hoy** (crear una tarea simple con recordatorio a 1 hora vía
     `task_manager.create_task()` cuando el parseo natural falla, línea 448-465 de
     `telegram_bot.py`). Conectar `/nueva` directo a `execute_tool("task_create", ...)` sin más
     cambiaría el comportamiento observable en el caso "texto no parseable" — violaría CA-10 tal
     como está redactado, salvo que `orion-architect` decida preservar el fallback de algún modo
     (p. ej. mantenerlo en `cmd_nueva()` y solo enrutar el camino feliz por `execute_tool`, o
     replicarlo dentro del tool).
   - El tool `task_complete` (`_task_complete_invoke`, línea 109-149) **no acepta un `task_id`
     numérico directo** — recibe `params["text"]` (texto libre) y extrae el ID con su propio
     regex `r"(?:tarea|numero|número|id)\s*#?(\d+)"`; si no matchea, intenta auto-completar si
     hay una sola tarea pendiente, o pide aclaración si hay varias. `cmd_completar()` hoy exige
     ID explícito y usa `task_manager.complete_task(task_id, user_id)` directo, con el mensaje
     de error `"No encontré la tarea #{task_id} en sus pendientes, Señor."` — el tool devuelve en
     cambio `"No encontré ninguna tarea pendiente con el ID #{task_id}, Señor."` (texto distinto)
     para el mismo caso, y tiene ramas de comportamiento (auto-completar, pedir aclaración) que
     `cmd_completar()` no tiene hoy. Conectar `/completar [id]` a `execute_tool("task_complete",
     {"text": ...})` requiere construir el `text` con cuidado para que el regex matchee, y aun
     así el mensaje de error y las ramas nuevas cambian el comportamiento observable respecto a
     hoy.
   - El tool `task_list` (`_task_list_invoke`, línea 103-106) sí es un equivalente limpio y
     directo de `cmd_tareas()` — mismo `task_manager.get_task_summary(user_id)`, sin diferencias.
   - Señalado para que `orion-architect` decida explícitamente cómo resolver esto (p. ej.
     mantener lógica de extracción de ID en `telegram_bot.py` y pasar un `text` ya normalizado al
     tool, o aceptar el cambio de mensaje/comportamiento y documentarlo como desviación menor
     aprobada) — no se resuelve en baseline.

## Confirmación: `core/security_manager.py`

- `CHANNEL_ALLOWED_LEVELS` (líneas 54-61):
  ```python
  CHANNEL_ALLOWED_LEVELS: Dict[ChannelType, List[RiskLevel]] = {
      ChannelType.DESKTOP: [RiskLevel.GREEN, RiskLevel.YELLOW],
      ChannelType.TELEGRAM: [RiskLevel.GREEN],
      ChannelType.DISCORD: [RiskLevel.GREEN],
      ChannelType.VOICE: [RiskLevel.GREEN],
      ChannelType.API: [RiskLevel.GREEN],
      ChannelType.UNKNOWN: [RiskLevel.GREEN],
  }
  ```
  Confirmado: es una lista **por canal**, sin ninguna granularidad por acción hoy. `orion-spec`
  tenía razón — no existe ningún mecanismo de excepción por canal+acción todavía; hay que
  diseñarlo desde cero (CA-02).

- `is_action_allowed()` (línea 225-230) y `require_confirmation()` (línea 232-294): el flujo real
  para YELLOW (línea 257-282) es: `is_action_allowed()` primero (usa `CHANNEL_ALLOWED_LEVELS`
  directo, sin excepción posible hoy) → si pasa, arma `msg` → busca adaptador vía
  `core.confirmation.get_confirmation_adapter(channel)` → si no hay adaptador, deniega
  fail-closed (`"bloqueada_sin_adaptador"`) → si hay adaptador, lo invoca síncrono y audita el
  resultado (`"confirmada"`/`"cancelada"`). El texto exacto del prompt (línea 262, 274):
  ```
  ¿Estás seguro de que quieres ejecutar '{action_name}'? ({details})
  ⚠️  {msg}
  Escribe 'sí' para confirmar, o cualquier otra cosa para cancelar:
  ```
  Confirma textualmente el criterio citado en CA-04 de la SPEC.

- `_register_default_actions()` (línea 300-341) — `delete_task` registrado YELLOW en línea 316,
  con comentario que referencia REQ-016 (delete_conversation/task/project como `@pyqtSlot`
  invocables). `task_complete`/`task_create`/`task_list` **no aparecen acá** — se registran en
  `agents/tool_registry.py:register_tool()` (línea 58, `security_manager.register_action(spec.name,
  spec.risk_level)`) como GREEN, según se ve en las tres definiciones de `ToolSpec` (líneas
  152-194 de `tool_registry.py`).

- **Lista completa de acciones YELLOW registradas hoy** (verificado línea por línea, confirma
  CA-03 de la SPEC exactamente):
  - `_register_default_actions()` (líneas 300-322): `shutdown`, `restart`, `close_app`,
    `delete_file`, `delete_folder`, `delete_conversation`, `delete_task`, `delete_project`,
    `execute_code`, `create_skill`, `modify_skill`, `delete_skill`, `send_message`.
  - `_register_intent_actions()` (líneas 356-359): `CLOSE_APP`, `SYS_POWER_OFF`, `EXECUTE_CODE`,
    `CREATE_SKILL`, `MODIFY_SKILL`, `DELETE_SKILL`.
  - `_register_action_registry_actions()` (línea 378): `write_file_direct`, `save_file_desktop`.
  - Total: 20 acciones YELLOW. Coincide exactamente con la lista de CA-03 de `SPEC-018.md`.

## Confirmación: `core/confirmation.py`

Contrato completo leído (41 líneas). `ConfirmFn = Callable[[str, str], bool]` — síncrono,
`(action_name, mensaje) -> bool`. `register_confirmation_adapter(channel, fn)` guarda/reemplaza
en un dict `_ADAPTERS` (sin acumular). `get_confirmation_adapter(channel)` devuelve `None` si no
hay adaptador — "ausencia de adaptador es una condición válida y esperada", documentado en
docstring, no un error. Módulo 100% síncrono, sin ningún import de `asyncio`. Confirma
textualmente CA-11 de REQ-006 citado en SPEC-018: "si un canal async necesita confirmar de
verdad, es responsabilidad de ese canal construir el puente async→sync" — este módulo no cambia.

## Confirmación: ningún adaptador de confirmación existe hoy para Telegram/Discord

Grep de `register_confirmation_adapter(` en todo el repo (`*.py`) — resultados:
- `core/confirmation.py:28` — la definición de la función, no una llamada.
- `main.py:59` — `register_confirmation_adapter(ChannelType.DESKTOP, _desktop_confirm)`.
- `ui/webview/main_window.py:126` — `register_confirmation_adapter(ChannelType.DESKTOP,
  self._confirmation_adapter.confirm)` (reemplaza al de `main.py` en runtime si `MainWindow` se
  construye con éxito).
- `tests/conftest.py:57` — mismo registro DESKTOP, para tests.
- `tests/test_confirmation.py:41,52,64,65` — registros DESKTOP y API **dentro de tests**
  (`test_register_confirmation_adapter_reemplaza_no_acumula` usa `ChannelType.API` con lambdas
  fake, no una implementación real de producción).

**Cero registros para `ChannelType.TELEGRAM` o `ChannelType.DISCORD` en código de producción o
tests.** Confirma el hallazgo de `orion-spec`: hay que diseñar el adaptador desde cero.

## Referencia de patrón existente — `ui/webview/confirmation_adapter.py`

`WebViewConfirmationAdapter` (88 líneas, leído completo) es el único precedente real de un
adaptador YELLOW distinto al de consola. Patrón: `confirm()` (síncrono, corre en el hilo worker)
crea un `request_id` + `threading.Event`, emite una señal Qt, espera con
`event.wait(timeout=CONFIRM_TIMEOUT_SECONDS)` (== 120, línea 27), limpia `self._pending` siempre
al finalizar (respondido o no) y solo devuelve `True` si `event.wait()` retornó `True` Y hubo una
respuesta afirmativa capturada — nunca por defecto. `confirm_response()` (corre en el hilo de la
GUI, vía `@pyqtSlot`) maneja defensivamente un `request_id` desconocido (ya resuelto/expirado) sin
lanzar. Es la referencia directa para el "Asumido" de SPEC-018 sobre el mecanismo
async→sync del adaptador de Telegram (`asyncio.to_thread()` + `threading.Event`, o equivalente).

## Confirmación: `agents/tool_registry.py` — tools existentes para CA-10

- `execute_tool(name, params, channel, user_id="default")` (línea 71-84): único punto de gate
  además de `dispatch()`. Levanta `ActionDenied` si el tool no existe o si
  `security_manager.require_confirmation()` deniega. Nunca invoca `spec.invoke()` sin pasar por
  el gate.
- `task_create` (línea 152-170), `task_list` (línea 172-182), `task_complete` (línea 184-194):
  las tres registradas `RiskLevel.GREEN`. Firmas y comportamiento documentados arriba en
  "Discrepancias nuevas encontradas".
- **No existe ningún tool `task_delete`** — confirma el "Asumido" de que este REQ no agrega
  borrado por lenguaje natural.

## Archivos que serán modificados (previsión)

- `agente_ia/channels/telegram_bot.py` — `cmd_eliminar()` (línea 500) pasa a gatear vía
  `security_manager.require_confirmation("delete_task", ChannelType.TELEGRAM, ...)`;
  `cmd_completar()` (468), `cmd_nueva()` (424), `cmd_tareas()` (416) pasan a invocar
  `execute_tool()` (con las salvedades de "Discrepancias nuevas" arriba); `handle_text()` (533) o
  un handler nuevo con prioridad debe interceptar la próxima respuesta del usuario con
  confirmación pendiente; `run_telegram_bot()` (773-841) es donde debe registrarse el adaptador
  nuevo (no `main.py`, ver "Discrepancias nuevas" punto 1) y donde probablemente haga falta
  `app.add_handler(...)` para el nuevo interceptor si se implementa como handler separado en vez
  de código agregado a `handle_text()`.
- `agente_ia/core/security_manager.py` — nuevo mecanismo de excepción canal+acción (CA-02), sin
  tocar `CHANNEL_ALLOWED_LEVELS` en bloque ni ningún `RiskLevel` existente. Punto de inserción
  natural: dentro de `is_action_allowed()` (línea 225) o `require_confirmation()` (línea 258),
  antes/junto a la consulta actual de `CHANNEL_ALLOWED_LEVELS`.
- Archivo nuevo — adaptador de confirmación conversacional para `ChannelType.TELEGRAM` (nombre y
  ubicación a definir por `orion-architect`; análogo funcionalmente a
  `ui/webview/confirmation_adapter.py::WebViewConfirmationAdapter`, resolviendo un puente
  async/asyncio en vez de hilo-worker↔hilo-Qt).
- `agente_ia/channels/telegram_bot.py::run_telegram_bot()` — registro del adaptador nuevo
  (corregido respecto a lo que dice "Módulos afectados" de SPEC-018.md — ver "Discrepancias
  nuevas" punto 1; **no** es `main.py`, porque `main.py` no inicia el proceso del bot de
  Telegram).
- `agente_ia/tests/` — cobertura nueva para CA-01 a CA-14. Hoy **no existe ningún archivo de test
  para `channels/telegram_bot.py`** (`tests/test_telegram*.py` no existe) — la cobertura de este
  módulo parte de cero, no hay tests de regresión previos que proteger para
  `cmd_eliminar`/`cmd_completar`/`cmd_nueva`/`cmd_tareas`/`handle_text` específicamente.

## Fallos pre-existentes (no atribuibles a este REQ)

Ejecutado: `python -m pytest tests/ --tb=short -q` — 420 passed, 2 failed, 45.27s.

- `tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` — FAIL
  (`ModuleNotFoundError: No module named 'anthropic'`).
- `tests/test_llm_provider.py::test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto` — FAIL
  (mismo `ModuleNotFoundError: No module named 'anthropic'`).

Ambos fallos son por falta del paquete `anthropic` en el entorno local (no instalado), no
relacionados con `channels/telegram_bot.py`, `core/security_manager.py`,
`core/confirmation.py` ni ningún módulo que este REQ vaya a tocar. No se atribuyen a REQ-018.

`python -m py_compile` sobre los 4 módulos centrales del REQ (`channels/telegram_bot.py`,
`core/security_manager.py`, `core/confirmation.py`, `main.py`) — sin errores, compilan limpio.

`python-telegram-bot` instalado: versión `20.7`, coincide con `requirements.txt:64`
(`# python-telegram-bot==20.7`) y con el mensaje de error de `run_telegram_bot()` si faltara.

## Riesgos activos identificados en baseline (para orion-architect)

1. La ubicación de registro del adaptador que indica SPEC-018.md ("Módulos afectados") es
   incorrecta — debe corregirse a `channels/telegram_bot.py::run_telegram_bot()`, no `main.py`
   (ver "Discrepancias nuevas" punto 1). Riesgo si se implementa tal cual la SPEC: el adaptador
   quedaría registrado en un proceso (`main.py`) que nunca ejecuta el bot de Telegram, y
   `delete_task` seguiría cayendo en `"bloqueada_sin_adaptador"` en producción pese a que el
   código "parezca" completo.
2. CA-10 ("comportamiento observable idéntico") tiene fricción real con la implementación actual
   de `task_create`/`task_complete` en `agents/tool_registry.py` (ver "Discrepancias nuevas" punto
   2) — requiere una decisión explícita de diseño, no un cableado directo.
3. Cero cobertura de test previa sobre `channels/telegram_bot.py` — cualquier verificación de "no
   rompí nada" para `/tareas`/`/nueva`/`/completar` depende de tests nuevos que orion-dev/tester
   escriban desde cero, no de una regresión contra tests existentes.
