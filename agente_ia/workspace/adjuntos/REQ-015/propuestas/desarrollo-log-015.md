# Desarrollo REQ-015 — Migrar panel de escritorio NODDOO a WebView (HTML/CSS/JS)

**Agente:** orion-dev
**Fecha:** 2026-08-19
**Nota:** esta es una **reanudación**. La ejecución anterior de `orion-dev` sobre esta
misma tarea se cortó a mitad de camino por expiración de credenciales OAuth del
proveedor (no fue un error propio ni un rechazo) mientras se diagnosticaba el layout con
dos scripts propios (`_diag_layout.py`, `_diag_step1.py`). Al reanudar, la implementación
de `arquitectura-015.md` §0-§10 ya estaba prácticamente completa en disco (11 archivos
backend de `ui/webview/`, frontend completo, 11 archivos de test nuevos, los 15 archivos
de REQ-013 ya en `git rm`). Este log documenta lo verificado/cerrado en esta reanudación,
no repite lo ya evidente en el propio código.

---

## Archivos modificados

- `agente_ia/main.py` — import de `update_gui_state` apuntando a `ui.webview.gui_state`;
  bloque `if __name__ == "__main__":` reemplazado por `MainWindow`/`window.show()` (sin
  `showMaximized()`); **+ fix nuevo de esta reanudación**: fijar DPI awareness
  `PER_MONITOR_AWARE_V2` como lo primero que hace el proceso, antes de cualquier otro
  import (ver "Decisiones de implementación" abajo).
- `agente_ia/ai/memory_manager.py` — `delete_conversation()` (CA-31), reimplementada
  desde cero.
- `agente_ia/core/security_manager.py` — `delete_conversation` registrada como
  `RiskLevel.YELLOW` (§10.2).
- `agente_ia/requirements.txt` — `PyQt6-WebEngine`, `markdown`, `Pygments`, `bleach`.
- `agente_ia/tests/conftest.py` — `PYTEST_QT_API=pyqt6` fijado antes de cualquier import
  de PyQt6 (§6).
- `agente_ia/ui/gui_workers.py` — solo docstring (referencia a `ui.gui.py` →
  `ui/webview/gui_state.py`), sin cambio de lógica.
- `agente_ia/ui/webview/frontend/css/chat.css` — **2 fixes nuevos de esta reanudación**,
  ver abajo.
- `agente_ia/tests/test_autostart.py`, `agente_ia/tests/test_main.py` — actualizados para
  la nueva arquitectura de arranque (ya en disco al reanudar, verificados contra la suite
  completa, sin cambios adicionales en esta pasada).

## Archivos eliminados (`git rm`, ya confirmados en `baseline-015.md`)

`ui/gui.py`, `ui/theme.py`, `ui/widgets/{center_panel, chat_bubble, chat_feed, composer,
conversation_list, header_bar, right_panel, system_status_card, quick_actions_card,
recent_activity_card, weather_card, sidebar, voice_orb}.py`,
`tests/{test_chat_widgets, test_gui_widgets, test_theme, test_wake_word_gui}.py`.

## Archivos nuevos (backend `ui/webview/`, ya en disco al reanudar)

`__init__.py`, `main_window.py`, `bridge.py`, `gui_state.py`, `wake_word_worker.py`,
`theme.py`, `markdown_render.py`, `file_drop.py`, `confirmation_adapter.py`,
`window_geometry.py`, `pygments_style.py` — los 11 de §2 de la arquitectura, verificados
uno por uno contra el contrato del bridge (§4) y contra §10.1/§10.2.

## Frontend nuevo (`ui/webview/frontend/`, ya en disco al reanudar)

`index.html`, `error.html`, `vendor/qwebchannel.js`, 10 archivos CSS, 8 archivos JS — ver
§2 de la arquitectura para el árbol completo.

## Tests nuevos (ya en disco al reanudar, ejecutados y en verde en esta pasada)

`test_memory_manager_delete_conversation.py`, `test_webview_bridge.py`,
`test_webview_confirmation_adapter.py`, `test_webview_contrast.py`,
`test_webview_file_drop.py`, `test_webview_gui_state.py`, `test_webview_markdown_render.py`,
`test_webview_safe_dom_insertion.py`, `test_webview_smoke.py`, `test_webview_theme.py`,
`test_webview_window_geometry.py`.

## Dependencias agregadas

- `requirements.txt` — `PyQt6-WebEngine`, `markdown`, `Pygments`, `bleach` (ya estaban
  agregadas al reanudar; verificadas presentes con `grep`).

---

## Qué se hizo en esta reanudación (además de verificar lo ya escrito)

### 1. Diagnóstico de layout heredado (`_diag_layout.py`/`_diag_step1.py`)

Ambos scripts medían `getBoundingClientRect()`/`getComputedStyle()` de los ids
`app-shell`, `sidebar`, `chat-area`, `composer`, etc. vía `page().runJavaScript()` sobre
un `QWebEngineView` offscreen construido a mano (sin `pytest`/`qtbot`). Al reanudar,
ambos crasheaban el intérprete (0xC0000409, *fail-fast*/stack-buffer-overrun a nivel de
Windows, sin traceback de Python) apenas se llamaba a `MainWindow()` — **antes** de
`window.show()`.

Diagnóstico: reproduje la misma medición pero dentro de un test real de `pytest`
(`qtbot`, mismo fixture que usa `test_webview_smoke.py`) en vez del script suelto —
ahí no crashea, corre limpio. La causa de que los scripts sueltos midieran valores
absurdos (`app-shell` de 2×2px, `window.innerHeight: 0`) antes de crashear era que
nunca llamaban `window.show()`/`qtbot.waitExposed()` — sin eso, `QWebEngineView`
offscreen nunca resuelve un viewport real. Con `show()` + `waitExposed()`, las medidas
salen correctas y consistentes con el CSS (`sidebar: 260px`, `main-column: 806px`,
`composer` debajo de `chat-area`, `body.scrollHeight (640) == window.innerHeight (640)`,
sin overflow vertical). **Conclusión: el layout se arma correctamente — el diagnóstico
que había quedado a mitad de camino estaba resuelto, solo faltaba el `show()`/
`waitExposed()` que el corte de OAuth interrumpió antes de que se aplicara.** No hay bug
de layout real detrás de esos dos scripts.

Los dos scripts (y una copia temporal de test usada para esta verificación,
`tests/test_zzz_diag_layout_tmp.py`) se borraron — eran instrumentación, no código final.

### 2. Verificación de §10.1 y §10.2 contra el código real (no solo el archivo existente)

- **§10.1** — `grep` de `innerHTML`/`insertAdjacentHTML` sobre los 4 archivos JS
  relevantes confirma que `chat.js` es el **único** que usa `innerHTML` (para el campo
  `html` ya sanitizado por `render_markdown()`); `sidebar.js`, `composer.js` y
  `confirm_modal.js` usan `.textContent` exclusivamente para los campos no confiables
  (`title`, `name`, `message`/`action_name`) — coincide exactamente con la regla del
  addendum.
- **§10.2** — `core/security_manager.py::_register_default_actions()` registra
  `sm.register_action("delete_conversation", RiskLevel.YELLOW)` en el mismo bloque que
  `delete_file`/`delete_folder`. `Bridge._delete_conversation_flow()` llama
  `security_manager.require_confirmation("delete_conversation", ChannelType.DESKTOP,
  details=format_details("webview:delete_conversation", {"name": conversation_id}),
  user_id="default")` antes de tocar `memory.delete_conversation()` — coincide
  exactamente con los 5 pasos descritos en §10.2.
- **Hallazgo B** (no bloqueante, asignado directo a `orion-dev`) — confirmado
  implementado en `ui/webview/confirmation_adapter.py`: `self._pending.pop(request_id,
  None)` tras cada resolución (se haya respondido a tiempo o no) y manejo defensivo
  (log + `return`, sin excepción) de un `request_id` desconocido en `confirm_response()`.

### 3. Verificación local (compilación + suite)

```
python -m py_compile main.py ai/memory_manager.py core/security_manager.py \
  ui/gui_workers.py ui/webview/*.py
```
→ limpio, exit 0, sobre los módulos nuevos/modificados de este REQ.

```
python -m pytest tests/ --tb=short -q -m "not webview_smoke"
→ 2 failed, 358 passed, 7 deselected
python -m pytest tests/ --tb=short -q -m "webview_smoke"
→ 7 passed
```
Total: **365 passed, 2 failed** — los 2 fallos son el mismo `ModuleNotFoundError:
No module named 'anthropic'` ambiental de `baseline-015.md` (`anthropic` no instalado),
no atribuibles a este REQ. Contra el baseline (2 failed, 305 passed) no hay ninguna
regresión — el delta (+60 tests) es exactamente la suite nueva de este REQ.

Nota de entorno: los 7 tests marcados `webview_smoke` pasan siempre, pero el *proceso*
de `pytest` termina con una violación de acceso (0xC0000005) **después** de imprimir
"7 passed" — un crash de `QWebEngineView` offscreen en la salida/teardown del proceso en
Windows, no durante los tests. Coincide con el riesgo ya documentado en
`arquitectura-015.md` §7 ("`QWebEngineView` offscreen en CI/Windows puede ser
lento/inestable"). No afecta el resultado de los tests (ya reportado en verde antes del
crash) ni requiere acción — se deja registrado para que `orion-tester`/`orion-qa` no lo
confundan con un fallo real si vuelven a correr la suite.

### 4. Verificación manual con la app real (`python main.py`, no offscreen)

Se lanzó `python main.py` de verdad (ventana propia, consola propia — **no** con stdin
redirigido: redirigir stdin hace que `ui.cli.get_input_method()` reciba EOF inmediato y
dispare el `finally: os._exit(0)` de `jarvis_runner` en `main.py`, que mata **todo el
proceso** incluida la GUI — comportamiento preexistente de REQ-009, no tocado por este
REQ, documentado acá porque hizo fallar el primer intento de captura).

Verificado con capturas reales (`PrintWindow` sobre el `HWND` de la ventana, no solo
`GetWindowRect`+recorte de pantalla completa — ver más abajo por qué):

- **(a) Sin bleed-through**: el fondo del `app-shell` es opaco en toda su superficie: solo
  se ve "a través" en el triángulo mínimo de la esquina redondeada (comportamiento
  buscado por diseño, `WA_TranslucentBackground` + `border-radius`), nunca detrás del
  contenido.
- **(b) Ventana dentro del área disponible**: `GetWindowRect` → `(96,16)`-`(1184,656)` =
  1088×640, calzando dentro de la pantalla disponible (1280×720) con margen — coincide
  con `fit_size_to_screen()`.
- **(c) Campo de texto visible con borde/placeholder**: confirmado visualmente
  (placeholder "Escribe un mensaje…" visible) y automatizado en
  `test_webview_smoke.py::test_composer_input_tiene_borde_fondo_y_placeholder` (dark +
  light, ambos verdes).
- **(d) Enviar un mensaje de punta a punta**: en vez de simular con mouse/teclado del
  sistema operativo (no disponible en este entorno de ejecución), se usó Chrome DevTools
  Protocol (`QTWEBENGINE_REMOTE_DEBUGGING`) contra la ventana real corriendo para escribir
  en `#composer-input` y hacer clic real (`.click()`) en `#send-btn` — exactamente los
  mismos elementos DOM que tocaría un click de mouse real, sin atajos por Python/bridge
  directo. Resultado: aparece la burbuja `.msg-user` con el texto exacto, el input se
  limpia, y minutos después aparece la respuesta del asistente como burbuja
  `.msg-assistant` ("Dígame, Señor. Estoy a su disposición.") — flujo de punta a punta
  confirmado funcionando contra la app real, no un mock.

**Dos bugs reales encontrados y corregidos en esta verificación** (ninguno visible en la
suite offscreen — exactamente el patrón de REQ-014 que este REQ buscaba dejar de repetir,
por eso se prioriza la prueba con la app real):

#### Bug 1 — indicador de "escribiendo" (CA-15) nunca se ocultaba

`chat.js::setTyping()` alterna el atributo `hidden` de `#typing-indicator`, pero
`chat.css` tenía `#typing-indicator { display: flex; ... }` con un selector de ID (más
específico que la regla `[hidden] { display: none }` del user-agent stylesheet) — el
`hidden` quedaba sin efecto y el indicador (3 puntos animados) se veía **siempre**,
incluso en reposo. Confirmado en vivo con CDP: `getComputedStyle(...).display` daba
`"flex"` tanto antes de enviar un mensaje como después de recibir la respuesta.

**Fix**: agregada la regla `#typing-indicator[hidden] { display: none; }` en
`ui/webview/frontend/css/chat.css` (selector ID+atributo, gana la especificidad).
Reverificado con CDP tras el fix: `display: "none"` en reposo, vuelve a `"none"` después
de la respuesta (antes del fix quedaba en `"flex"` permanentemente).

#### Bug 2 (investigado, no confirmado como bug de la app — ver detalle) — aparente
recorte horizontal del saludo en pantallas con escala ≠ 100%

En las primeras capturas de la ventana real (entorno con la pantalla al 150%,
`AppliedDPI=144`) el saludo del estado vacío ("Buenas noches") y parte del sidebar
parecían "cortados" por el borde derecho de la ventana en la captura de pantalla.
Investigación:

1. Descartado que fuera bleed-through o un problema de geometría de ventana (`(b)` de
   arriba ya estaba confirmado correcto).
2. Probé dos fixes de CSS (ampliar `max-width`, forzar `width: 100%` en
   `#empty-state-greeting`) — **ninguno cambió la captura**, señal de que el problema no
   estaba en el CSS.
3. Conecté Chrome DevTools Protocol directo contra la ventana real corriendo (más
   confiable que leer píxeles de una captura de pantalla) y consulté
   `getBoundingClientRect()`/`devicePixelRatio` reales: `window.innerWidth: 1088`,
   `#empty-state-greeting` → `width: 694.67px`, `right: 1021px` — **completamente dentro**
   de los 1088px de la ventana, con margen de sobra. El layout CSS real, medido desde
   adentro del propio motor de renderizado, está bien — no hay overflow.
4. La discrepancia estaba en la *captura*: `GetWindowRect` reportaba 1088×640 físicos
   pero `devicePixelRatio` era 1.5 (pantalla a 150%) — la firma típica de un desajuste de
   *DPI awareness* del proceso. Encontré la causa: varias skills ya existentes
   (`skills/screen_analysis_skill.py`, `os_integration/screenshot_tools.py`, ninguna
   tocada por este REQ) importan `pyautogui`, que en Windows llama
   `SetProcessDPIAware()` (System-Aware) como efecto secundario de su propio import —
   ese import ocurre antes de que exista `QApplication` (vía `skill_manager`, cargado al
   principio de `main.py`). Windows solo deja fijar el *DPI awareness context* del
   proceso una vez: si `pyautogui` gana la carrera, Qt/QtWebEngine ya no puede subir a
   `PER_MONITOR_AWARE_V2` (log real: `"SetProcessDpiAwarenessContext() failed: Acceso
   denegado"`).
5. **Corregido en `main.py`**: se fija `SetProcessDpiAwarenessContext` (Per-Monitor-V2)
   como lo **primero** que hace el proceso, antes de cualquier otro import — gana la
   carrera contra `pyautogui`. Es un cambio defensivo correcto independientemente de si
   era la causa completa de lo visto en capturas (abajo).
6. **Con el fix aplicado, la captura de pantalla no cambió** — seguía viéndose el mismo
   recorte aparente. Repetí la medición por CDP (fuente de verdad, inmune a cómo cada
   herramienta de captura interprete DPI) y el layout seguía midiendo perfecto (mismo
   `width: 694px` bien contenido). Until aquí, concluyo que **la propia app no tiene un
   bug de overflow real** — lo que se ve "cortado" en las capturas de pantalla es un
   artefacto de la herramienta de captura usada en este entorno (`GetWindowRect`/
   `PrintWindow` vía PowerShell, incluso llamado desde un proceso marcado explícitamente
   Per-Monitor-V2-aware, seguía reportando 1088×640 para una ventana cuyo contenido
   interno se comporta como si tuviera más superficie a 1.5x) — posiblemente específico
   de este entorno de ejecución en sandbox/automatización, no reproducido cuando se mide
   desde dentro del propio proceso (CDP).
7. Se mantiene el fix de `main.py` (paso 5) porque es correcto y necesario de todos
   modos —evita que una skill no relacionada le gane la carrera de DPI awareness a
   QtWebEngine, algo que sí puede causar problemas reales en otros escenarios— pero
   **se marca explícitamente para el humano**: la inspección visual real en su propia
   máquina, con especial atención a factores de escala ≠ 100% (pedido explícito de
   CA-04/§8 de la arquitectura), sigue siendo necesaria — este REQ no puede darla por
   cerrada solo con las capturas tomadas en este entorno de verificación, que resultaron
   no ser confiables como fuente de verdad para el escalado en particular (sí lo fueron,
   confirmado con CDP y con la interacción real de envío de mensaje, para todo lo demás).

---

## Decisiones de implementación (desvíos menores respecto a la propuesta, con motivo)

1. **Fix de DPI awareness en `main.py` (no está en `arquitectura-015.md`)** — motivo:
   hallazgo real durante la verificación manual obligatoria de esta reanudación (ítem 7
   del handoff), con causa raíz identificada y confirmada (`pyautogui` de skills no
   relacionadas ganando la carrera de `SetProcessDpiAwarenessContext` contra Qt/
   QtWebEngine). No es un rediseño de nada de §0-§10 — son 15 líneas defensivas al
   principio de `main.py`, dentro del archivo que la arquitectura ya listaba como
   "Modificado". Se documenta acá y en el contexto para que `orion-tester`/`orion-qa` lo
   tengan presente.
2. **Fix de `#typing-indicator[hidden]` en `chat.css` (no está en `arquitectura-015.md`)**
   — motivo: bug real de CA-15 encontrado con la app corriendo de verdad y confirmado con
   CDP (antes y después del fix). Una sola regla CSS, sin tocar el contrato del bridge ni
   ningún otro archivo.
3. **Se descartaron 2 intentos de fix en `chat.css`** (`max-width: 100%` y luego
   `width: 100%` sobre `#empty-state-greeting`) porque, verificado con CDP, no atacaban
   ningún problema real — el layout ya estaba correcto en el motor de renderizado. Se
   revirtieron a texto original para no dejar código que no corrige nada.

---

## Verificación local (resumen)

```
python -m py_compile main.py ai/memory_manager.py core/security_manager.py \
  ui/gui_workers.py ui/webview/*.py   → OK

python -m pytest tests/ --tb=short -q -m "not webview_smoke"
  → 2 failed (ambiental, anthropic), 358 passed, 7 deselected
python -m pytest tests/ --tb=short -q -m "webview_smoke"
  → 7 passed

Total: 365 passed, 2 failed (mismos 2 de baseline-015.md) — sin regresiones.
```

Verificación manual con `python main.py` real: bleed-through (a), geometría de ventana
(b) y campo de texto (c) confirmados visualmente + por captura; envío de mensaje de
punta a punta (d) confirmado interactuando con la app real vía CDP (no un mock). 2 bugs
reales encontrados y corregidos durante esta verificación (indicador de escritura, DPI
awareness). Un tercer hallazgo (aparente recorte visual en capturas a escala 150%)
investigado a fondo, con evidencia de que el layout real de la app es correcto (CDP) y de
que el artefacto está en la herramienta de captura de este entorno — **no cerrado como
"sin bug" al 100%**, se deja marcado para que el humano lo confirme en su propia máquina
como parte de la prueba manual final que exige el flujo.

---

📝 MENSAJE DE COMMIT SUGERIDO:
──────────────────────────────
```
feat(REQ-015): migrar UI de escritorio a WebView (HTML/CSS/JS) sobre QWebEngineView

- Reemplaza ui/gui.py + ui/theme.py + 13 widgets QWidget/QSS por un shell frameless con
  un único QWebEngineView (sidebar, chat, composer, modal) — cierra los 3 bugs de
  renderizado de REQ-014 (bleed-through, ventana fuera de pantalla, input invisible).
- Bridge Python↔JS vía QWebChannel (ui/webview/bridge.py), Markdown+código resaltado
  server-side (markdown+Pygments+bleach), confirmación YELLOW por modal WebView.
- Ajustes de seguridad post-auditoría (security-audit-015.md): inserción segura en el DOM
  (textContent/setAttribute, nunca innerHTML) en sidebar.js/composer.js/confirm_modal.js;
  delete_conversation() reclasificada a RiskLevel.YELLOW con confirmación real.
- delete_conversation() nueva en ai/memory_manager.py (CA-31).
- Fix: indicador de "escribiendo" (CA-15) que nunca se ocultaba por especificidad CSS.
- Fix: DPI awareness Per-Monitor-V2 fijado al inicio de main.py, antes que el import
  transitivo de pyautogui (skills de screenshot) pueda ganarle la carrera a QtWebEngine.
- requirements.txt: PyQt6-WebEngine, markdown, Pygments, bleach.
```
──────────────────────────────
**No ejecutado `git commit`.**
