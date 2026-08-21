# Auditoría de seguridad REQ-015 — Migrar panel de escritorio NODDOO a WebView

**Agente:** orion-security
**Fecha:** 2026-08-19
**Entrada auditada:** `workspace/adjuntos/REQ-015/propuestas/arquitectura-015.md` (395 líneas, ✅ APROBADA
por Johan) + `SPEC-015.md` (48 CA) + `REQ-015-context.md` completo + código real de
`core/security_manager.py`, `core/confirmation.py`, `agents/action_registry.py`, `main.py`.

## Resumen ejecutivo

La arquitectura es sólida en su diseño central: el gate de riesgo verde/amarillo/rojo
(`core/security_manager.py::require_confirmation()`) no se toca, sigue fail-closed, y el bridge
Python↔JS (`Bridge(QObject)`) es efectivamente la única superficie invocable desde JS, con cada
slot recibiendo solo tipos primitivos. Verificado contra el código real (no solo contra el texto de
la arquitectura): el registro del adaptador de confirmación de consola ocurre a nivel de módulo en
`main.py:29` (import time), antes de que `MainWindow` pueda construirse — no hay ventana sin
adaptador activo.

Sin embargo, la introducción de `QWebChannel` cambia una premisa estructural que la arquitectura no
hace explícita en ningún punto: **una vez que hay una página web con `window.bridge` expuesto,
cualquier script que logre ejecutarse en esa página — sea código propio de `app.js` o código
inyectado por una falla de sanitización — tiene el mismo acceso a `window.bridge` que el código
legítimo.** No existe aislamiento de origen entre "JS de la app" y "JS inyectado" dentro de una
misma página QWebEngineView. Esto convierte la sanitización de **todo** texto no confiable que
llega al DOM (no solo el Markdown de la IA) en el control de seguridad más cargado de todo el
diseño — más incluso que cuál gate usa cada acción individual.

Dos hallazgos, ambos originados en esa premisa, requieren un ajuste (pequeño y acotado, no un
rediseño) de la arquitectura antes de pasar a `orion-dev`. Ninguno de los dos pone en duda las
decisiones técnicas centrales (§0.1-§0.4) ya aprobadas.

## Clasificación de riesgos implementados

| Punto auditado | Nivel | ¿Confirmación? | Estado |
|---|---|---|---|
| 1. Bridge Python↔JS — contrato cerrado (§4, CA-42) | 🟢 Verde (superficie ya restringida) | No aplica — el gate lo decide cada función invocada | ✅ |
| 1b. `run_chip_action` siempre vía `execute_action(..., channel=ChannelType.DESKTOP)` (CA-39) | 🟢 Verde | El gate real lo aplica `require_confirmation()` dentro de `execute_action()` | ✅ verificado contra `agents/action_registry.py:277-291` |
| 2a. Timeout de confirmación YELLOW retorna `False` (fail-closed) | 🟡 Amarillo (mecanismo de confirmación) | Sí, con timeout 120s | ✅ diseño correcto |
| 2b. Gate de `require_confirmation()`/`RiskLevel` no se toca | — | — | ✅ verificado contra `core/security_manager.py:232-294`, sin cambios propuestos |
| 2c. Sin ventana de tiempo sin adaptador activo | — | — | ✅ verificado contra `main.py:29` (registro a nivel de módulo, antes de `MainWindow`) |
| 2d. Concurrencia de `self._pending[request_id]` / reciclado / confirmación tardía | 🟡 Amarillo | Diseño base correcto (uuid4 por request, sin colisión práctica) | ⚠️ falta especificar limpieza y manejo de `request_id` desconocido — ver Hallazgo B |
| 3. Sanitización Markdown→HTML con `bleach` (§5.2) — allowlist | 🟢 Verde | No aplica | ✅ allowlist restrictiva (sin `script`/`iframe`/`on*`/`javascript:`) |
| 3b. Otros puntos de texto no confiable insertado en el DOM (título de conversación, nombre de archivo, mensaje de confirmación) | 🔴 Rojo (potencial, si no se especifica) | No especificado en la arquitectura | ❌ REQUIERE CAMBIO — ver Hallazgo A |
| 4. Drag & drop — validación antes de lectura (§5.3, CA-23) | 🟢 Verde | No aplica (solo lectura de metadatos: extensión/tamaño) | ✅ orden correcto: extraer → validar → notificar |
| 5. `delete_conversation()` sin gate central (§1 tabla, CA-10) | 🟡 Amarillo (reclasificar) | Hoy: solo modal JS, sin `require_confirmation()` | ❌ REQUIERE CAMBIO — ver Hallazgo C |

## Hallazgo A (bloqueante) — Texto no confiable fuera del Markdown de la IA sin regla explícita de inserción segura en el DOM

El contrato del bridge (§4.2) marca explícitamente `html` como el campo ya sanitizado en
`turns_loaded`/`message_appended` (viene de `render_markdown()`). Pero al menos otros cuatro campos
que cruzan el bridge son texto libre **sin ese tratamiento**, y la arquitectura nunca dice
explícitamente cómo debe insertarlos JS:

- `conversation_list_updated.title` (CA-08): "primeros 30 caracteres del primer mensaje" — texto
  escrito por el usuario o generado por la IA, sin pasar por `bleach`.
- `file_attached.name` (§5.3): **nombre de archivo tomado de `QDropEvent.mimeData().urls()`** — a
  diferencia del texto que el propio usuario tipea, un nombre de archivo puede venir de un tercero
  (archivo recibido por email/USB/red) y el usuario lo suelta sin haberlo escrito él mismo. Un
  nombre como `"><img src=x onerror=fetch('...')+window.bridge.request_delete_conversation(...)>.txt`
  (si `.txt` está en la allowlist) es contenido plenamente hostil y ajeno al usuario.
- `confirmation_requested.message`/`action_name` (§4.3): el mensaje del modal de confirmación
  amarilla incluye `details` (`format_details(f"action_registry:{name}", params)` en
  `agents/action_registry.py:286`), y `params` puede contener texto proveniente de un intent
  parseado por NLP — no está garantizado que sea texto "de confianza total" en todos los casos.
- `chips_loaded.label` (bajo riesgo — viene de config Python estática, no de input).

**Por qué esto es más grave que un XSS "normal":** si cualquiera de estos campos se inserta con
`innerHTML`/`insertAdjacentHTML` sin sanitizar y logra ejecutar un `<script>`/`onerror`, ese script
corre en la misma página que `window.bridge` — con acceso directo a **todos** los comandos del §4.1,
incluido `confirm_response(request_id, confirmed)`. Es decir, una falla de sanitización en
cualquiera de estos puntos no es "solo" un XSS decorativo: es una vía para que contenido hostil
(ej. un nombre de archivo) invoque directamente cualquier slot del bridge, incluyendo
autoconfirmar sus propias solicitudes YELLOW. Esto también responde directamente la pregunta que
`orion-architect` hizo en el handoff (punto 3): sí hay más puntos de inserción no cubiertos
explícitamente por `render_markdown()`/`bleach.clean()`.

**Ajuste requerido a la arquitectura (§4, agregar una subsección):**
1. Regla explícita: todo campo del bridge que no esté marcado como `html` (ya sanitizado) debe
   insertarse en el DOM exclusivamente vía `textContent`/`setAttribute` — nunca `innerHTML` ni
   `insertAdjacentHTML` — en `sidebar.js`, `composer.js` (chip de adjunto) y `confirm_modal.js`.
2. Agregar un test adversarial explícito a §8 (extensión de `test_webview_bridge.py` o un nuevo
   `test_webview_frontend_render.py` si el proyecto puede testear JS, o al menos un test Python que
   verifique que ningún handler JS use `innerHTML` sobre esos campos — grep estructural del código
   fuente como mínimo) cubriendo: título de conversación con `<img onerror=...>`, nombre de archivo
   con HTML embebido, y `details`/`message` de confirmación con HTML embebido.
3. Recomendación adicional (no bloqueante, defensa en profundidad): agregar un
   `<meta http-equiv="Content-Security-Policy">` en `index.html` que prohíba `unsafe-inline` para
   scripts y restrinja `connect-src`/`img-src` — reduce el impacto si en el futuro se abre otro
   punto de inserción no sanitizado.

## Hallazgo B (no bloqueante, requisito obligatorio para orion-dev) — Limpieza y manejo de `request_id` desconocido en el adaptador de confirmación

El diseño base de §4.3 es correcto y fail-closed (uuid4 por solicitud, timeout retorna `False`, el
gate de `RiskLevel` no se toca). No hay riesgo de que una confirmación tardía de una solicitud
expirada confirme por error una *distinta* solicitud posterior, porque cada una tiene su propio
`request_id`/`threading.Event` — no hay reciclado real dado el espacio de uuid4.

Lo que la arquitectura no especifica, y que `orion-dev` debe implementar explícitamente:
1. `self._pending[request_id]` debe eliminarse (`pop`) una vez que el hilo worker desbloquea
   (confirmado, cancelado, o timeout) — de lo contrario crece sin límite durante la vida del
   proceso (fuga de memoria menor, no crítica, pero evitable).
2. `confirm_response(request_id, confirmed)` debe manejar defensivamente un `request_id`
   desconocido o ya consumido (`self._pending.get(request_id)`, log de advertencia y `return` — no
   `KeyError`). Esto cubre tanto un bug de JS como un intento de invocar el slot con un id
   inventado.

Agregar ambos casos como pruebas explícitas a `tests/test_webview_confirmation_adapter.py` (§8, ya
listado) — no requiere volver a `orion-architect`, es una precisión del mismo diseño ya aprobado.

## Hallazgo C (bloqueante) — `delete_conversation()` debe pasar por el gate central, no solo por un modal JS

La arquitectura (§1 tabla CA-10) mantiene el mismo criterio que `qa-audit-014.md` aceptó como
observación no bloqueante en REQ-014: confirmación "a nivel UI" (modal JS propio), sin pasar por
`security_manager.require_confirmation()`. El propio `orion-architect` pidió reconfirmar este
criterio dado el bridge nuevo (ver handoff, punto 5) — la respuesta de esta auditoría es **no,
ya no corresponde mantenerlo tal cual**.

En REQ-014, el borrado se disparaba desde un `QPushButton` nativo: solo el propio proceso Python
podía invocar ese slot. En REQ-015, `request_delete_conversation(conversation_id)` es un
`@pyqtSlot` invocable por **cualquier script que corra en la página** — incluido, en el peor caso,
un script inyectado a través del Hallazgo A. Un modal JS que solo decide visualmente si llamar al
bridge no es una barrera real contra ese vector: el script hostil puede llamar
`window.bridge.request_delete_conversation(id)` directamente, sin pasar por el modal en absoluto.
Además, hoy esa ruta no deja ningún registro en el log de auditoría de `security_manager`
(`_log_audit`) — un borrado de conversación no queda trazado en ningún lado, a diferencia de
cualquier otra acción amarilla del sistema.

**Ajuste requerido a la arquitectura:**
- Registrar `delete_conversation` como acción `RiskLevel.YELLOW` en
  `core/security_manager.py::_register_default_actions()` (mismo patrón que `delete_file`/
  `delete_folder`, coherente con `.claude/rules/security-levels.md` — "Borrar archivos o carpetas").
- `Bridge.request_delete_conversation()` debe llamar `security_manager.require_confirmation(
  "delete_conversation", ChannelType.DESKTOP, details=..., user_id="default")` **usando el mismo
  `WebViewConfirmationAdapter`/modal que ya se construye para CA-41**, en vez de un modal JS
  paralelo con su propia lógica de confirmación. Esto no es trabajo adicional relevante — es
  reutilizar la misma pieza que la arquitectura ya diseña para las demás acciones amarillas — y
  además deja el borrado con auditoría (`_log_audit`) consistente con el resto del sistema.
- Nota honesta para que quede documentada: esto **no cierra completamente** el vector de un script
  hostil que también pudiera llamar `confirm_response(request_id, True)` a mano si logra leer el
  `request_id` del DOM. La mitigación real y de fondo de ese escenario es el Hallazgo A (que no
  exista contenido no sanitizado capaz de ejecutar script en la página). Pasar `delete_conversation`
  por el gate central es defensa en profundidad correcta y necesaria (auditoría, consistencia,
  UX uniforme) — no un sustituto del Hallazgo A.

## Secretos

- `config.json` (raíz del proyecto): sin API keys ni tokens — verificado con búsqueda de
  `api_key`/`API_KEY`/`token`/`TOKEN`, sin resultados.
- El proyecto usa `.env.example` (plantilla) con `.env` real fuera del repo (patrón ya establecido,
  no tocado por este REQ).
- REQ-015 no introduce ninguna API externa ni credencial nueva — las dependencias nuevas
  (`PyQt6-WebEngine`, `markdown`, `Pygments`, `bleach`) son todas locales/offline, sin llaves.
- Ningún hallazgo de secretos expuestos.

## Validación de inputs

- Regla general del bridge (§4, "Regla general para todo slot nuevo"): tipos primitivos o JSON
  parseado con `try/except` — correcta y suficiente para evitar `eval`/deserialización insegura.
- `channel` nunca se lee desde JS/params — siempre hardcodeado `ChannelType.DESKTOP` del lado
  Python en cada slot que dispara una acción (`send_message`, `run_chip_action`,
  `request_delete_conversation`, etc.) — consistente con el invariante de seguridad documentado en
  `core/security_manager.py::require_confirmation()` (líneas 239-246), verificado.
- `validate_dropped_file()` se ejecuta antes de cualquier lectura de contenido — solo se leen
  metadatos (extensión, tamaño) para decidir, orden correcto verificado en §5.3.
- Recomendación no bloqueante: la allowlist de extensiones de `file_drop.py` (a definir por
  `orion-dev`) debe excluir explícitamente extensiones ejecutables/script (`.exe`, `.bat`, `.cmd`,
  `.ps1`, `.vbs`, `.js`, `.msi`, `.scr`, `.lnk`, `.dll`) — la arquitectura no lista la allowlist
  concreta, dejarlo explícito evita que `orion-dev` la deje demasiado permisiva.
- Recomendación no bloqueante: `bleach` permite el atributo `class` sin restringir sus valores —
  en teoría un mensaje de la IA con HTML crudo (`<span class="msg-system">...</span>`, que
  Python-Markdown deja pasar como HTML crudo y `bleach` no bloquea porque `span`+`class` están
  permitidos) podría falsificar visualmente un mensaje de sistema dentro de una burbuja de chat.
  Impacto acotado a suplantación visual dentro del feed de chat (no ejecuta código, no toca el
  modal de confirmación real que se construye aparte en JS) — no bloqueante, pero recomendable
  restringir los valores de `class` permitidos a los que genera `codehilite` (ej. patrón
  `^codehilite$|^[a-z]{1,3}$`) en vez de aceptar cualquier valor.
- Observación no bloqueante: `QUrl.toLocalFile()` puede devolver una ruta UNC (archivo desde un
  recurso de red) — no es una escalación de privilegios nueva (el proceso ya tiene los permisos de
  filesystem del usuario), pero si se quiere ser estricto se puede rechazar explícitamente rutas
  que no correspondan a una unidad local. No se marca como hallazgo.
- Confirmado por SPEC: el alcance de REQ-015 para drag&drop termina en "validar + mostrar chip" —
  ninguna CA de esta SPEC envía el *contenido* del archivo a la IA ni lo sube a ningún lado. Si un
  REQ futuro agrega lectura de contenido de archivos adjuntos, necesitará su propia revisión de
  seguridad (lectura de rutas arbitrarias, tamaño real vs. declarado, etc.).

## Recomendaciones (resumen, no bloqueantes salvo lo indicado en Hallazgos A y C)

1. **[Bloqueante — Hallazgo A]** Agregar a §4 de la arquitectura una regla explícita de inserción
   segura en el DOM para todo campo del bridge no marcado como `html` pre-sanitizado, con prueba
   adversarial en §8.
2. **[Bloqueante — Hallazgo C]** Reclasificar `delete_conversation` a `RiskLevel.YELLOW` y enrutarla
   por `security_manager.require_confirmation()` reusando el `WebViewConfirmationAdapter` de CA-41,
   actualizando la tabla de CA-10 en §1.
3. [No bloqueante — Hallazgo B] Especificar limpieza de `self._pending` y manejo de `request_id`
   desconocido en `confirmation_adapter.py`; agregar los dos casos a
   `test_webview_confirmation_adapter.py`. Puede resolverse directo en `orion-dev` sin volver a
   `orion-architect`, ya que no cambia el diseño, solo lo completa.
4. [No bloqueante] CSP en `index.html` como defensa en profundidad.
5. [No bloqueante] Restringir valores de `class` en la allowlist de `bleach` a los patrones que
   genera `codehilite`.
6. [No bloqueante] Allowlist explícita de extensiones seguras (excluir ejecutables/scripts) en
   `file_drop.py`.

## Veredicto: ❌ REQUIERE CAMBIOS

Los hallazgos A y C son ajustes acotados (una regla de renderizado seguro + reclasificar una acción
a un gate que la arquitectura ya construye para otro propósito) — no cuestionan ninguna de las 4
decisiones técnicas centrales (§0.1-§0.4) ni el diseño del bridge en general, que está bien pensado
y cerrado en todo lo demás. No se recomienda diseñar de nuevo nada; se recomienda que
`orion-architect` incorpore ambos puntos a `arquitectura-015.md` (secciones §1 tabla CA-10, §4, y
§8) antes de pasar a `orion-dev`.
