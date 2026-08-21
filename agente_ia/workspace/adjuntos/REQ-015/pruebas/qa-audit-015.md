# Auditoría QA REQ-015 — Migrar panel de escritorio NODDOO a WebView (HTML/CSS/JS)

**Agente:** orion-qa
**Fecha:** 2026-08-19
**Fuentes leídas antes de auditar:** `REQ-015-context.md` completo (historial íntegro: mensaje
original con los 3 bugs de REQ-014, SPEC-015.md con 48 CA, baseline-015.md, arquitectura-015.md
§0-§10, security-audit-015.md, desarrollo-log-015.md, test-results-015.md).

Verificación hecha por lectura directa del código real implementado — no por confianza en lo que
reportaron `orion-dev`/`orion-tester` — sobre los 5 puntos del handoff de Johan.

---

## Punto 1 — Re-confirmación independiente de los 2 fixes de §10 (security-audit-015.md)

**Hallazgo A (inserción segura en el DOM).** Leí directamente los 4 archivos JS relevantes:

| Archivo | Inserción de texto no confiable | Mecanismo |
|---|---|---|
| `sidebar.js:49` | `conv.title` (derivado del primer mensaje del usuario) | `title.textContent = conv.title;` |
| `composer.js:96` | `name` del archivo dropeado (puede no ser texto del propio usuario) | `nameEl.textContent = accepted ? name : ...` |
| `confirm_modal.js:35` | `message`/`action_name` (construido desde `params` de un intent NLP) | `body.textContent = message \|\| actionName;` |
| `chat.js:42` | `item.html` — **único** campo marcado `html` pre-sanitizado | `bubble.innerHTML = item.html \|\| "";` |

Grep de `innerHTML`/`insertAdjacentHTML`/`eval(`/`document.write` sobre todo `ui/webview/frontend/js/`
confirma que `chat.js` es la única ocurrencia real de `innerHTML` en todo el frontend — coincide
exactamente con la regla de §10.1. `bridge_client.js`, `theme.js`, `window_chrome.js`, `app.js` no
insertan texto no confiable en el DOM en absoluto.

Además, seguí el camino real del campo `html`: `ui/webview/bridge.py` construye **todos** los
`message_appended`/`turns_loaded` con `render_markdown(text)` (líneas 166, 179, 197, 230, 312, 317
— sin excepción, ningún camino emite `html` sin pasar por ahí). `ui/webview/markdown_render.py`
aplica `bleach.clean()` con allowlist estricta (`ALLOWED_TAGS` sin `script`/`iframe`/`on*`,
`ALLOWED_PROTOCOLS = ["http", "https"]` — bloquea `javascript:`) sobre el HTML ya generado por
`markdown.markdown()`. Esto confirma el punto 5 del handoff en el mismo lugar: la sanitización no es
solo una función que existe, es el único camino real de datos hacia `innerHTML`.

**Hallazgo C (`delete_conversation` → YELLOW).** Confirmado por lectura directa:
- `core/security_manager.py:311` — `sm.register_action("delete_conversation", RiskLevel.YELLOW)`,
  en el mismo bloque que `delete_file`/`delete_folder` (líneas 305-306), con comentario explicando el
  motivo del cambio de criterio frente a REQ-014.
- `ui/webview/bridge.py::request_delete_conversation()` (línea 241) nunca toca `memory` directo —
  despacha `_delete_conversation_flow` vía `run_async()` (hilo worker, nunca el hilo de la GUI).
  `_delete_conversation_flow` (línea 248) llama `security_manager.require_confirmation(
  "delete_conversation", ChannelType.DESKTOP, details=format_details(...), user_id="default")`
  **antes** de `memory.delete_conversation()` (línea 262) — si `confirmed` es `False`, retorna sin
  tocar la base de datos.
- La clave `"name"` en `details` (en vez de `"conversation_id"`) está documentada y justificada:
  confirmé que `format_details()` tiene un `_DETAILS_ALLOWED_KEYS` explícito — usar una clave fuera
  de esa lista perdería trazabilidad de auditoría silenciosamente, así que la elección es correcta.

**Veredicto: PASS.** Ambos hallazgos bloqueantes de `security-audit-015.md` están implementados tal
cual lo aprobado en §10, confirmado con lectura directa del código, no solo del reporte de
`orion-tester`.

---

## Punto 2 — Bridge Python↔JS: superficie completa contra el contrato de §4

Leí `ui/webview/bridge.py` completo (412 líneas) y `ui/webview/frontend/js/bridge_client.js`
completo (57 líneas) en paralelo.

- **15 `@pyqtSlot`** en `Bridge`: `request_initial_state`, `send_message`, `new_conversation`,
  `select_conversation`, `request_delete_conversation`, `load_more_conversations`, `run_chip_action`,
  `set_theme`, `toggle_wake_word`, `confirm_response`, `start_resize`, `start_move`,
  `window_minimize`, `window_toggle_maximize`, `window_close`.
- `bridge_client.js` expone exactamente esos 15 comandos JS→Python, uno a uno, sin ningún método
  adicional que llame a `window.bridge` fuera de este archivo (comentario explícito en el propio
  archivo: "Ningún otro módulo del frontend toca `window.bridge`/`QWebChannel` directamente").
- **Ningún slot ejecuta `eval()`/`exec()`.** Grep sobre `ui/webview/*.py` no encontró ninguna
  ocurrencia.
- **Imports dentro de los slots están acotados a la lista aprobada:** `core.resolution.resolve`,
  `core.security_manager.{ChannelType, format_details, security_manager}`,
  `agents.action_registry.execute_action`, `ai.memory_manager.memory` (con sus 5 funciones
  documentadas: `store_turn`, `list_conversations`, `get_conversation_turns`, `new_conversation_id`,
  `delete_conversation`), `ui.webview.gui_state`, `ui.webview.markdown_render.render_markdown`,
  `ui.webview.theme.resolve_theme_name`, `ui.webview.wake_word_worker.WakeWordWorker`,
  `config_manager`. No hay ningún import dinámico ni `importlib` con nombre construido en runtime.
- `run_chip_action()` pasa `channel=ChannelType.DESKTOP` **hardcodeado del lado Python** (no leído de
  ningún parámetro que venga de JS) — respeta la regla de REQ-005/`security-levels.md` de que el gate
  nunca decide el canal a partir de la invocación entrante.

**Veredicto: PASS.** El bridge es la superficie documentada en §4, sin extensiones no auditadas.

---

## Punto 3 — Crash nativo intermitente (`0xC0000005`, `Qt6Quick.dll`)

Revisé el análisis de `orion-tester` en `test-results-015.md` (sección dedicada). Dos causas
distintas, ambas con evidencia directa:

1. **Crash de GPU virtualizada**: logs de Chromium citados textualmente muestran
   `Failed to create shared context for virtualization` — apunta a compositing de hardware no
   soportado por la GPU virtualizada de este sandbox específico, no a un bug de lógica de REQ-015.
   Es la misma familia de riesgo que ya documentó `orion-architect` en §7 de la arquitectura para
   `QWebEngineView` en entornos de CI/GPU limitada — no es una sorpresa nueva sin mitigación
   considerada.
2. **Terminación por `EOFError`/stdin nulo**: traceback completo señala `ui/cli.py::get_input_method()`
   → `os._exit(0)` de `jarvis_runner`, hazard preexistente de REQ-009 (shell de automatización sin
   stdin real), no tocado por este REQ.

Ninguno de los dos es reproducible por una acción del usuario dentro de la app (no es un botón, un
clic, ni un flujo que dispare código de REQ-015) — son artefactos del entorno de ejecución de este
sandbox. Estoy de acuerdo con el criterio de `orion-tester`: **no amerita bloquear el REQ**, porque
no hay evidencia de que el código nuevo cause el crash (los propios logs de Chromium apuntan a la
capa de virtualización de GPU, fuera del control de este REQ) y porque la sesión sí entregó evidencia
limpia de los CA de no-regresión antes de tropezar con cualquiera de los dos problemas. Corresponde
documentarlo como riesgo de entorno para que Johan preste atención a la estabilidad en su máquina
real (que previsiblemente no tiene GPU virtualizada ni el hazard de stdin del sandbox de automatización).

**Veredicto: no bloqueante — documentado explícitamente en la solicitud de prueba manual (abajo).**

---

## Punto 4 — Confirmación YELLOW nueva: timeout fail-closed y cobertura de adaptador

Leí `ui/webview/confirmation_adapter.py` completo (88 líneas):

- `confirm()` (línea 44): `event.wait(timeout=CONFIRM_TIMEOUT_SECONDS)` con
  `CONFIRM_TIMEOUT_SECONDS = 120`. Si `answered_in_time` es `False`, `confirmed = False` (línea 62)
  — nunca hay un camino donde el timeout retorne `True`. Confirmado fail-closed.
- Limpieza de `self._pending.pop(request_id, None)` ocurre **siempre**, se haya respondido a tiempo o
  no (línea 61, fuera del `if answered_in_time`) — cierra Hallazgo B sin dejar `Event`s huérfanos.
- `confirm_response()` con un `request_id` desconocido/ya resuelto: `logger.warning(...)` + `return`
  sin lanzar (líneas 80-85) — manejo defensivo correcto.
- **Registro sin ventana huérfana:** `main.py:58` registra `_desktop_confirm` (adaptador de consola)
  **a nivel de módulo**, antes de que exista cualquier instancia de `MainWindow`. `ui/webview/main_window.py:124-126`
  construye `WebViewConfirmationAdapter` y lo registra recién dentro de `MainWindow.__init__`, **solo
  si la construcción llega hasta ahí** — si falla (modo headless), el adaptador de consola sigue
  siendo el único registrado, sin momento donde `ChannelType.DESKTOP` quede sin ningún adaptador
  activo. Mismo patrón que ya había verificado `orion-security` contra la arquitectura, ahora
  confirmado contra el código implementado.

**Veredicto: PASS.**

---

## Punto 5 — Sanitización Markdown/XSS en el camino real de datos

Ya cubierto en detalle en el Punto 1 (mismo hallazgo, verificado en el mismo lugar del código): todo
mensaje de la IA pasa por `render_markdown()` (`bleach.clean()` con allowlist, sin `script`/`on*`,
protocolos limitados a `http`/`https`) antes de llegar al único `innerHTML` real del frontend
(`chat.js:42`). No hay ningún camino alternativo en `bridge.py` que arme el payload `html` sin pasar
por `render_markdown()`.

**Veredicto: PASS.**

---

## Seguridad — checklist estándar

- **Secretos/API keys hardcodeados:** ninguno. Grep de patrones de API key/token/password/Bearer/
  claves conocidas (`sk-`, `AIza`) sobre todo `ui/webview/` sin resultados relevantes (solo falsos
  positivos de la palabra "token"/"class" en CSS/comentarios, sin valor de secreto real).
- **Acciones destructivas piden confirmación:** `delete_conversation` (YELLOW, Punto 1); el resto de
  acciones YELLOW/RED preexistentes (`shutdown`, `restart`, `close_app`, `delete_file`,
  `delete_folder`, etc.) no se tocaron — siguen registradas igual en `security_manager.py`.
- **Niveles verde/amarillo/rojo respetados:** confirmado — `_build_chips_payload()` consulta
  `security_manager.classify_action()` en el momento (no hardcodea el color del chip), y
  `run_chip_action()` siempre pasa por `execute_action()` con canal fijo desde Python (Punto 2).
- **`except: pass` silencioso:** ninguno. Grep de `except.*:$` sobre todo `ui/webview/*.py` da solo 2
  resultados, ambos con logging explícito antes de retornar (`file_drop.py:55`
  `logger.warning(...)`, `wake_word_worker.py:53` `logger.error(...)`).
- **Validación de inputs:** `file_drop.py::validate_dropped_file()` usa allowlist de extensiones (no
  denylist), límite de tamaño (20MB) y `try/except OSError` con log — nunca lanza sobre un path
  externo. `bridge.py::send_message()` valida `text` vacío y un guard server-side
  (`_resolution_in_flight`) contra doble envío, no confía solo en el estado `disabled` del DOM.

---

## Logging

- Todo `except` en el código nuevo de `ui/webview/` registra el error antes de continuar
  (`logger.warning`/`logger.error`) — sin excepciones tragadas en silencio.
- Acción YELLOW (`delete_conversation`) queda trazada en el log de auditoría de `security_manager`
  al pasar por `require_confirmation()` (antes no lo estaba — ese era exactamente el motivo del
  Hallazgo C).
- Timeout de confirmación fail-closed registra `logger.warning` con `action_name` y `request_id`
  antes de retornar `False` (Punto 4).
- Fix de DPI awareness en `main.py` envuelto en `try/except Exception` con `logger.warning` — no
  silencioso pese a ser el primer código ejecutado del proceso.

---

## Consistencia de código

- Type hints presentes en las funciones nuevas revisadas (`bridge.py`, `confirmation_adapter.py`,
  `file_drop.py`, `markdown_render.py`).
- Imports ordenados stdlib → third-party → locales, con línea en blanco entre grupos (confirmado en
  `bridge.py`, `main_window.py`).
- `snake_case` en Python, sin violaciones detectadas en los módulos revisados.
- Sin prints de debug: grep de `console.log`/`debugger;`/`print(` sobre `ui/webview/` completo sin
  resultados.
- Sin dead code: los scripts de diagnóstico temporales (`_diag_layout.py`, `_diag_step1.py`,
  `tests/test_zzz_diag_layout_tmp.py`) que menciona `desarrollo-log-015.md` como borrados están
  efectivamente ausentes del disco y de `git status` — confirmado directamente, no solo por el
  reporte.
- `requirements.txt` actualizado con las 4 dependencias nuevas (`PyQt6-WebEngine`, `markdown`,
  `Pygments`, `bleach`) — confirmado por lectura directa.

---

## Veredicto: ✅ COMPLETADO

Los 2 hallazgos bloqueantes de la auditoría de seguridad dedicada (`security-audit-015.md`) están
implementados tal cual lo aprobado en §10 de la arquitectura, confirmado con lectura directa del
código real (no por confianza en `orion-dev`/`orion-tester`). El bridge Python↔JS no expone
superficie no documentada. La sanitización Markdown/XSS opera efectivamente en el único camino real
de datos hacia `innerHTML`. La confirmación YELLOW nueva es fail-closed y no deja ninguna ventana sin
adaptador activo. No hay secretos hardcodeados, `except: pass` silencioso, ni dead code. El crash
nativo intermitente reportado por `orion-tester` tiene evidencia directa de ser un artefacto de
entorno (GPU virtualizada del sandbox + hazard preexistente de REQ-009), no atribuible al código de
REQ-015 — se documenta como riesgo de entorno para la prueba manual, no como bloqueante.

Siguiente paso: prueba manual de Johan (ver solicitud abajo) antes de entregar el mensaje de commit.
