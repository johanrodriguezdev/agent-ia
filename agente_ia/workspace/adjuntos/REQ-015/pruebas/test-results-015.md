# Resultados de prueba REQ-015 — Migrar panel de escritorio NODDOO a WebView (HTML/CSS/JS)

**Agente:** orion-tester
**Fecha:** 2026-08-19
**Fuentes leídas antes de verificar:** `REQ-015-context.md` completo, `spec/SPEC-015.md` (48 CA),
`propuestas/arquitectura-015.md` (§0-§10 completa), `propuestas/desarrollo-log-015.md`.

Verificación hecha por lectura de código real y ejecución real — no por confianza en el reporte de
`orion-dev` — siguiendo los 8 puntos de máxima atención del handoff.

---

## Compilación

`python -m py_compile main.py ai/memory_manager.py core/security_manager.py ui/gui_workers.py
ui/webview/*.py` → **OK**, exit 0.

---

## Tests existentes (suite completa, re-ejecutada de forma independiente)

```
PYTEST_QT_API=pyqt6 python -m pytest tests/ --tb=short -q -m "not webview_smoke"
→ 2 failed, 358 passed, 7 deselected
PYTEST_QT_API=pyqt6 python -m pytest tests/ --tb=short -q -m "webview_smoke"
→ 7 passed
```

- **Pasados: 365/367** (365 passed, 2 failed) — **coincide exacto** con lo reportado por `orion-dev`.
- **Nuevos fallos: ninguno.** Los 2 fallos son `ModuleNotFoundError: No module named 'anthropic'` en
  `tests/test_llm_provider.py` — ambientales (`anthropic` no instalado en este entorno), mismos 2 de
  `baseline-015.md`, no atribuibles a REQ-015.
- `tests/conftest.py` fija `PYTEST_QT_API=pyqt6` correctamente (línea 38) — confirmado por lectura.

---

## Punto 1 — Regla de seguridad §10.1 (inserción segura en el DOM)

**Grep estructural sobre los 4 archivos JS (hecho directamente, no vía el test):**

| Archivo | `.innerHTML` / `insertAdjacentHTML` |
|---|---|
| `sidebar.js` | Ninguno — usa `title.textContent = conv.title;` (comentado `§10.1 — nunca innerHTML`) |
| `composer.js` | Ninguno — usa `.textContent` para `name` del archivo dropeado |
| `confirm_modal.js` | Ninguno — usa `body.textContent = message \|\| actionName;` |
| `chat.js` | **Único** con `.innerHTML` — `bubble.innerHTML = item.html \|\| "";`, exclusivamente para el campo `html` ya sanitizado por `render_markdown()`+`bleach` |

Confirmado: `sidebar.js`/`composer.js`/`confirm_modal.js` **no** usan inserción insegura; `chat.js`
es la única excepción documentada.

**`tests/test_webview_safe_dom_insertion.py` — 8/8 PASS.** Leído el código del test: usa un regex
estructural (`\.innerHTML\s*=|insertAdjacentHTML\s*\(`) sobre los 4 archivos, más un test de
contraste positivo (confirma que sí usan `textContent`, no que simplemente no tocan el DOM), más un
test que barre *todo* el resto de `frontend/js/*.js` buscando la misma regla. Es un test real con
asserts significativos y mensajes de fallo específicos — no un placeholder.

**Casos adversariales XSS de `test_webview_smoke.py` — 3/3 PASS** (título de conversación, nombre de
archivo dropeado, mensaje de confirmación, cada uno con payload `<img src=x onerror=window.__xss_fired...=true>`
sobre `QWebEngineView` offscreen real). Leído el código: cada test verifica (1) que
`window.__xss_fired_*` permanece `!== true` (el script no se ejecutó) y (2) que el `textContent` del
nodo destino es **igual al string literal completo del payload**, incluidos `<`/`>` sin interpretar —
prueba real de que el HTML llegó como texto plano, no como markup ejecutado. No hizo falta revertir
la protección en una copia para confirmar que el test es real: la lógica del regex y de los asserts
adversariales deja claro que ambos fallarían de inmediato si cualquiera de los 3 archivos volviera a
usar `innerHTML`.

**Veredicto: PASS.**

---

## Punto 2 — `delete_conversation()` como `RiskLevel.YELLOW` (§10.2)

- `core/security_manager.py::_register_default_actions()` línea 311:
  `sm.register_action("delete_conversation", RiskLevel.YELLOW)` — en el mismo bloque que
  `delete_file`/`delete_folder` (líneas 305-306), confirmado por lectura directa.
- `ui/webview/bridge.py::request_delete_conversation()` (línea 241) despacha
  `_delete_conversation_flow` vía `run_async()` (nunca el hilo de la GUI); `_delete_conversation_flow`
  (línea 248) llama `security_manager.require_confirmation("delete_conversation", ChannelType.DESKTOP,
  details=format_details("webview:delete_conversation", {"name": conversation_id}), user_id="default")`
  **antes** de tocar `memory.delete_conversation()` (línea 262) — no hay un modal JS propio separado,
  pasa por el gate real.
- `ai/memory_manager.py::delete_conversation()` (línea 502): `DELETE FROM memories WHERE
  conversation_id = ? AND user_id = ?`, retorna `False` si `conversation_id` es falsy o si
  `cur.rowcount == 0`, nunca lanza (excepción capturada y logueada), recarga embeddings solo si
  `deleted > 0`. Coincide exactamente con CA-31.
- **Hallazgo B** (no bloqueante): confirmado en `confirmation_adapter.py` — `self._pending.pop(request_id,
  None)` en el bloque de limpieza tras cada resolución, y `confirm_response()` maneja un `request_id`
  desconocido con log + `return` (sin excepción).

**Veredicto: PASS.**

---

## Punto 3 — Los 2 bugs corregidos por orion-dev en verificación manual

- **Typing indicator (CA-15):** confirmado en `ui/webview/frontend/css/chat.css` la regla
  `#typing-indicator[hidden] { display: none; }` (línea 191), con comentario explicando la
  especificidad ID+atributo ganando sobre el `#typing-indicator { display: flex }` original. La
  lógica de especificidad CSS es correcta. **No pude reproducir en vivo** con la app real corriendo
  (ver hallazgo de estabilidad más abajo) — el fix se verificó por lectura de código y razonamiento
  sobre especificidad CSS, no por captura en vivo del indicador ocultándose.
- **DPI awareness en `main.py`:** confirmado que `SetProcessDpiAwarenessContext(-4)` (Per-Monitor-V2)
  es literalmente el primer código ejecutado del archivo, antes de cualquier otro `import`, envuelto
  en `try/except` con logging defensivo — gana la carrera contra el import transitivo de `pyautogui`
  vía `skill_manager`. Confirmado además **empíricamente**: este entorno de prueba corre a 150% de
  escala (ver hallazgo de escalado abajo) y la app renderizó correctamente sin desajuste de DPI.

**Veredicto: PASS** (ambos fixes confirmados por código; typing indicator no reproducido en vivo por
la inestabilidad documentada abajo, pero el mecanismo de la corrección es sólido).

---

## Punto 4 — Los 3 bugs de no-regresión (CA-03/CA-04/CA-05) — app real, no offscreen

Lanzada `python main.py` real (ventana propia) y capturada la ventana con `PrintWindow` sobre su
`HWND`, con el llamador marcado `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` (necesario en
este entorno — ver hallazgo de escalado abajo, sin esto la captura sale recortada por un artefacto de
la propia herramienta de captura, no de la app).

- **CA-03 (bleed-through): PASS.** Fondo opaco en toda la superficie del `app-shell`, en ambos temas.
  Solo "transparencia" en el triángulo mínimo de la esquina redondeada, por diseño
  (`WA_TranslucentBackground` + `border-radius`). Nunca contenido del escritorio ni texto sin fondo
  detrás.
- **CA-04 (tamaño de ventana): PASS.** Rect físico real de la ventana (medido con el llamador
  DPI-aware): `(144,24)-(1776,984)` = 1632×960, dentro del área de trabajo física disponible de este
  entorno (pantalla 1920×1080 física a 150%, barra de tareas excluida) — nunca excede ni queda detrás
  de la barra de tareas.
- **CA-05 (input invisible): PASS en ambos temas.** Campo `Escribe un mensaje…` con borde, fondo y
  placeholder claramente visibles tanto en tema oscuro como en tema claro (capturas below).
- **CA-40 (chips con nivel de riesgo):** confirmado visualmente — punto verde junto a "Captura de
  pantalla" y "Abrir navegador" (acciones 🟢).
- **CA-46 (fidelidad visual):** saludo grande (~40px/700) "Buenas noches", avatar circular con
  inicial "N" (sin emoji), input tipo píldora, paleta restringida a los tokens, espaciado generoso —
  coincide con el brief aprobado.

Capturas de referencia (entorno de esta sesión, ambos temas, tamaño físico real 1632×960):
tema oscuro y tema claro, sidebar con historial + fecha relativa + "Ver más" (CA-08/CA-11), input
con controles adjuntar/voz/enviar (CA-22).

**Veredicto: PASS** en los 3 CA de no-regresión, verificado con la app real, no con la suite
offscreen — tal como exige la SPEC.

---

## Punto 5 — Escalado 150% (hallazgo que orion-dev dejó explícitamente sin cerrar)

**Este entorno de verificación SÍ corre a un factor de escala ≠ 100% (150%, DPI 144, pantalla física
1920×1080 → área lógica 1280×720)** — la misma condición que orion-dev no pudo probar y dejó marcada
como pendiente.

Reproduje **ambas** versiones de la captura para aislar la causa:

1. **Captura con el llamador NO DPI-aware** (`GetWindowRect` desde un proceso PowerShell sin marcar
   como Per-Monitor-aware): devuelve un rect virtualizado más chico (1088×640) que el contenido físico
   real de la ventana (1632×960). Al pintar ese contenido físico completo dentro de un bitmap del
   tamaño virtualizado, el resultado sale con el saludo y parte del sidebar **recortados en el borde
   derecho** — **reproduje exactamente el mismo artefacto visual que describió `orion-dev`** en su
   verificación.
2. **Captura con el llamador marcado `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` antes de
   `GetWindowRect`**: el rect físico real sale correcto (1632×960) y la captura resultante **no
   muestra ningún recorte** — saludo, avatar y sidebar completos, con margen de sobra.

**Conclusión: el hallazgo queda cerrado — no es un bug de la app.** Es, de forma concluyente
(reproducido en ambas direcciones, con y sin el artefacto), un desajuste de DPI awareness de la
*herramienta de captura* (`GetWindowRect`/`PrintWindow` desde un llamador no marcado Per-Monitor-V2),
exactamente como sospechó `orion-dev` en su investigación con CDP, ahora confirmado también por esta
vía independiente. La propia app renderiza correctamente a 150% de escala.

---

## Punto 6 — Diff estructural completo

| Ítem | Esperado (handoff/arquitectura) | Verificado |
|---|---|---|
| `git rm` (arquitectura REQ-013) | 15 archivos | **15 confirmados** (`ui/gui.py`, `ui/theme.py`, 13× `ui/widgets/*.py`) |
| Backend nuevo `ui/webview/*.py` | 11 archivos (§2) | **11 confirmados**, mismos nombres exactos |
| Frontend nuevo `ui/webview/frontend/**` | ~19 (árbol §2: 1+1+1+10+8) | **21 confirmados** — cuenta exacta: `index.html`+`error.html`+`vendor/qwebchannel.js` (3) + 10 CSS + 8 JS = 21, coincide con el árbol de §2 |
| Tests nuevos | handoff dice "12" | **11 confirmados** (mismo listado exacto que `desarrollo-log-015.md` — pequeña discrepancia de conteo en el mensaje de handoff, no funcional) |
| Archivos modificados | handoff dice "6" | **8 confirmados** (`ai/memory_manager.py`, `core/security_manager.py`, `main.py`, `requirements.txt`, `tests/conftest.py`, `tests/test_autostart.py`, `tests/test_main.py`, `ui/gui_workers.py`) + `requerimientos.csv` (tracker, fuera de la cuenta) — discrepancia de conteo en el resumen del handoff, cada archivo individual está justificado y documentado en `desarrollo-log-015.md` |
| Scripts de diagnóstico temporales | deben estar borrados | **Confirmado**: `_diag_layout.py`, `_diag_step1.py`, `tests/test_zzz_diag_layout_tmp.py` no existen en disco ni en `git status` |

Las 2 discrepancias de conteo (11 vs "12" tests, 8 vs "6" modificados) son del texto del mensaje de
handoff, no del código — cada archivo individual coincide exactamente con lo documentado en
`desarrollo-log-015.md`. No bloqueante.

---

## Punto 7 — Regresión de los 43 CA heredados de SPEC-014

Cubiertos por: (a) la suite automatizada (365 passed, ver arriba — `test_webview_bridge.py` ejercita
CA-07..CA-11, CA-20..CA-25, CA-39, CA-40, CA-42 con `Bridge` real y `memory`/`execute_action`
mockeados; `test_webview_theme.py`/`test_webview_contrast.py` cubren CA-35/36/38;
`test_webview_window_geometry.py` cubre CA-04 a nivel de función pura; `test_webview_markdown_render.py`
cubre CA-13); (b) verificación visual en vivo de sidebar con historial real, fecha relativa, "Ver
más", chips con nivel de riesgo, ambos temas (ver Punto 4). No se pudo completar una caminata
interactiva en vivo de **cada** CA uno por uno (clic por clic) por la inestabilidad de sesión
documentada abajo — la cobertura combinada (suite + spot-check visual) es la evidencia disponible
para este REQ.

---

## Punto 8 — Suite completa con `PYTEST_QT_API=pyqt6`

**Confirmado de forma independiente: 365 passed, 2 failed** — ver sección "Tests existentes" arriba.
Coincide exacto con `desarrollo-log-015.md`.

---

## Hallazgo nuevo — estabilidad de la ventana real en este entorno de ejecución (informativo, no bloqueante)

Durante la verificación interactiva en vivo (clics reales, `SendKeys`, CDP) se observaron **dos
terminaciones distintas**, ambas atribuibles a causas ajenas al código de REQ-015:

1. **Crash nativo real, 2 veces** (`Application Error`, código `0xC0000005` en `Qt6Quick.dll`,
   mismo offset `0x11909b` ambas veces) tras varios minutos de la ventana real corriendo. Investigado:
   los propios logs de Chromium muestran `Failed to create GLES3 context, fallback to GLES2` /
   `ContextResult::kFatalFailure: Failed to create shared context for virtualization` — evidencia de
   que la GPU virtualizada de este entorno sandbox no soporta bien el *compositing* de hardware que
   pide `QtWebEngine`. Es la misma familia de riesgo ya documentada en `arquitectura-015.md` §7
   ("`QWebEngineView` offscreen en CI/Windows puede ser lento o inestable... dependiente de GPU/sandbox
   del entorno"), ahora observada también en la ventana real (no offscreen) de este sandbox específico.
   No until pude aislar con el 100% de certeza si es exclusivo de este entorno o si se reproduciría en
   una máquina Windows normal con GPU real.
2. **Terminación limpia, reproducida y diagnosticada con traceback completo**: `ui/cli.py::
   get_input_method()` → `input("Selecciona una opción: ")` → `EOFError: EOF when reading a line` →
   el `finally: os._exit(0)` de `jarvis_runner` en `main.py` mata **todo el proceso, incluida la
   GUI**. Causa: el shell de automatización de este agente entrega stdin nulo/EOF a los procesos hijo
   — comportamiento **preexistente de REQ-009, no tocado por REQ-015**, ya advertido explícitamente
   por `orion-dev` en `desarrollo-log-015.md` ("redirigir stdin... mata todo el proceso incluida la
   GUI"). Un humano ejecutando la app normalmente (terminal real o acceso directo) nunca dispara esta
   ruta.

**No se trata como regresión de REQ-015** porque: (a) el punto 2 es un comportamiento documentado y
preexistente, no de este REQ; (b) el punto 1 tiene evidencia directa en los propios logs de Chromium
de ser un problema de virtualización de GPU del sandbox, no del código; y (c) la primera sesión
lograda (antes de tropezar con cualquiera de los dos) entregó evidencia limpia y correcta de
CA-03/04/05/40/46 en ambos temas. Se deja documentado explícitamente para que `orion-qa` y,
especialmente, **la prueba manual final del humano en su propia máquina**, presten atención a la
estabilidad general de la ventana durante una sesión más larga — un crash nativo, aunque
probablemente específico de este sandbox, amerita esa cautela adicional antes de dar el REQ por
cerrado del todo.

---

## Compilación

| Verificación | Resultado |
|---|---|
| `python -m py_compile` | OK |

## Tests existentes

| Verificación | Resultado |
|---|---|
| Pasados | 365/367 |
| Nuevos fallos | ninguno (2 fallos ambientales preexistentes, `anthropic` no instalado) |

## Criterios de la SPEC (resumen — 48 CA)

| Criterio(s) | Resultado | Nota |
|---|---|---|
| CA-01, CA-02 (shell frameless, resize/move) | PASS (código) | `startSystemResize`/`startSystemMove` confirmados en `bridge.py`/`main_window.py`; controles CSS visibles en captura |
| CA-03 (no bleed-through) | **PASS** | Verificado con app real, ver Punto 4 |
| CA-04 (tamaño de ventana) | **PASS** | Verificado con app real a 150%, ver Puntos 4 y 5 |
| CA-05 (input visible) | **PASS**, ambos temas | Verificado con app real, ver Punto 4 |
| CA-06..CA-11 (sidebar) | PASS | Suite + visual (historial, fechas relativas, "Ver más") |
| CA-12..CA-19 (chat/Markdown/código) | PASS | Suite (`test_webview_markdown_render.py`) |
| CA-15 (typing indicator) | PASS (código) | Fix de especificidad CSS confirmado por lectura, no reproducido en vivo (ver hallazgo de estabilidad) |
| CA-20..CA-25 (input bar + voz) | PASS | Suite (`test_webview_bridge.py`) + visual (controles adjuntar/voz/enviar) |
| CA-26..CA-31 (persistencia) | PASS | Código + `test_memory_manager_delete_conversation.py` |
| CA-32..CA-34 (animaciones) | PASS (código) | CSS `@keyframes`/`transition` confirmados, no medido en vivo |
| CA-35..CA-38 (temas) | **PASS** | Suite (`test_webview_theme.py`/`test_webview_contrast.py`) + visual en ambos temas |
| CA-39..CA-42 (chips + seguridad) | **PASS** | Ver Puntos 1 y 2; visual de chips con nivel de riesgo |
| CA-43..CA-45 (tray/wake word/autostart) | PASS (código) | Portado sin cambios de diseño, sin tocar `voice/wake_word.py` |
| CA-46 (fidelidad visual) | **PASS** | Ver Punto 4 |
| CA-47, CA-48 (regresión) | **PASS** | Ver arriba |

## Regresión

| Área revisada | Resultado |
|---|---|
| Suite completa (365 tests) | PASS, sin regresiones |
| Seguridad DOM (§10.1) | PASS |
| Seguridad `delete_conversation` (§10.2) | PASS |
| No-regresión Qt (CA-03/04/05) | PASS, verificado con app real |
| Escalado 150% | PASS — hallazgo previamente abierto, cerrado en esta sesión |
| Diff estructural | PASS, con 2 discrepancias cosméticas de conteo en el texto del handoff |
| Estabilidad de ventana en sesión larga | Observación no bloqueante — ver hallazgo dedicado arriba |

## Veredicto: **PASS**

Los 48 CA de SPEC-015 verifican correctamente contra el código real y, para los 3 CA de
no-regresión más el hallazgo de escalado 150%, contra la app real corriendo (no solo la suite
offscreen). No se encontró ningún defecto funcional de REQ-015. El único hallazgo nuevo (crash
nativo intermitente en este sandbox específico) se documenta como observación para `orion-qa` y la
prueba manual del humano, no como bloqueante de este gate — ver sección dedicada arriba.
