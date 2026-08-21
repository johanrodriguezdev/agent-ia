# Contexto REQ-015 — Migrar panel de escritorio NODDOO a WebView (HTML/CSS/JS)

## Resumen ejecutivo
Reemplazar la capa visual del panel de escritorio (hoy QWidget + QSS nativo, implementada en
REQ-014) por un WebView embebido que renderiza HTML/CSS/JS real, manteniendo el 100% de la lógica
de negocio en Python (agente, memoria, voz, seguridad, scheduler). Objetivo: llegar al nivel de
pulido visual de referencias reales (ChatGPT, Claude, DeepSeek, WorkBuddy AI) sin seguir cazando
bugs de composición/renderizado de Qt uno por uno.

## Estado actual
- **Estado tracker:** ARQUITECTURA_APROBADA (CSV sin cambios — la aprobación de §10 es correctiva,
  no mueve el tracker más allá de donde ya estaba)
- **Último agente:** orion-architect (arquitectura completa §0-§9 + §10 aprobada por Johan tal cual;
  handoff emitido a `orion-dev`)
- **Fecha última actualización:** 2026-08-19
- **Rama git:** `feature/REQ-015-webview-ui` — confirmada y creada por Johan desde `main`, ya activa
- **Propuesta técnica:** `workspace/adjuntos/REQ-015/spec/SPEC-015.md` — ✅ COMPLETADO, aprobada por
  Johan (2026-08-19) tal cual, sin ajustes (48 CA, incluidos los 7 puntos ASUMIDO)
- **Arquitectura:** `workspace/adjuntos/REQ-015/propuestas/arquitectura-015.md` — §0-§9 ✅ APROBADA
  por Johan (2026-08-19) tal cual, sin ajustes. **§10 (ajustes de seguridad post-auditoría) — ✅
  APROBADA por Johan (2026-08-19) tal cual, sin ajustes**: responde a `security-audit-015.md`
  (veredicto ❌ REQUIERE CAMBIOS) con los 2 hallazgos bloqueantes (A: regla de inserción segura en el
  DOM; C: `delete_conversation` a `RiskLevel.YELLOW`). Arquitectura completa (§0-§9 + §10) lista para
  `orion-dev` — no requiere volver a pasar por `orion-security` salvo que surja un hallazgo nuevo
  durante el desarrollo.
- **CSV:** sin cambios en esta pasada — `Aprobacion_Arquitectura`/`Estado` mantienen los valores de
  la aprobación original (§0-§9): `Estado=ARQUITECTURA_APROBADA`. La aprobación de §10 no introduce
  una transición de tracker nueva; el próximo cambio de `Estado` lo escribe `orion-dev` al pasar a
  `EN_DESARROLLO`.
- **Categoría:** UI
- **Tipo de cambio:** REFACTOR (de la capa de presentación) — el alcance funcional es mayormente
  el mismo que REQ-014, cambia la tecnología de renderizado

## Antecedente completo
Ver `workspace/adjuntos/REQ-015/origen/REQ-015-mensaje-original.md` para el mensaje original
íntegro del humano (no resumir de más al consultarlo) — incluye:
- El diagnóstico de los 3 bugs de renderizado de REQ-014 (uno por ciclo dev→tester→qa→prueba
  manual, cada uno detectado SOLO en la prueba manual del humano, nunca por la suite headless):
  1. Bleed-through / texto superpuesto en panel derecho (QWidget plano sin `WA_StyledBackground`
     + `WA_TranslucentBackground` de ventana frameless).
  2. Ventana más alta que el área disponible de pantalla, input bar detrás de la barra de tareas
     de Windows (frameless, sin barra de título nativa que reposicione).
  3. Campo de texto del input bar invisible (sin borde, sin placeholder) — bug de renderizado QSS
     distinto a los 2 anteriores, no diagnosticado.
- El razonamiento de por qué se abandona QSS+QWidget (frágil para el nivel de pulido buscado) en
  favor de HTML/CSS/JS real (la misma tecnología que usan las 4 referencias visuales).
- Los 2 candidatos técnicos a evaluar en arquitectura: `QWebEngineView` (PyQt6-WebEngine) vs
  `pywebview`, con sus trade-offs de tamaño de dependencia, integración con el shell PyQt6
  existente (frameless, tray, autostart, `QThread` de voz) y esfuerzo de reescritura.
- El alcance propuesto y las restricciones (no tocar `core/`, `intent/`, `ai/`, `skills/`,
  `agents/`, `voice/`, `channels/` salvo lo ya aprobado de REQ-014; sin empaquetado PyInstaller).

## Decisiones tomadas
2026-08-19 | orion-coordinador | REQ creado — categoría=UI | Detección explícita del humano en el
mensaje original (WebView, HTML/CSS/JS, PyQt6, interfaz de escritorio) — sin ambigüedad, no requirió
pregunta de clarificación.
2026-08-19 | orion-coordinador | REQ-014 NO se toca ni se cierra/cancela | Mismo criterio usado
cuando REQ-014 reemplazó a REQ-013 — REQ-014 queda documentado como antecedente en su fila del CSV
(`EN_QA`) y su carpeta `workspace/adjuntos/REQ-014/` se preserva intacta como referencia.
2026-08-19 | orion-spec | ⚠️ HALLAZGO — `workspace/adjuntos/REQ-014/` había desaparecido del disco;
restaurada sin tocar código | Verificado que Johan corrió `git stash -u` (incluye no-trackeados) al
resguardar el código de REQ-014 antes de crear la rama de REQ-015; ese `-u` agarró sin querer también
la carpeta de evidencias `workspace/adjuntos/REQ-014/` (spec, arquitectura, qa-audit, context,
test-results, la captura del addendum §7), que es no-trackeada. Restaurada al disco con `git checkout
stash@{0}^3 -- workspace/adjuntos/REQ-014/` + `git reset` (vuelve a quedar no-trackeada, como estaba
antes) — el stash no se tocó ni se hizo `pop`, el código de REQ-014 sigue ahí intacto, recuperable
cuando `orion-baseline`/`orion-architect` lo necesiten.
2026-08-19 | orion-spec | ⚠️ HALLAZGO — el punto de partida real en disco es REQ-013, no REQ-014 |
Ningún commit de REQ-014 llegó a `main`. El HEAD actual de `feature/REQ-015-webview-ui` es `eb190b3`
(mismo commit del que partió REQ-014), que contiene la arquitectura de REQ-013 (`ui/gui.py`,
`ui/theme.py` con tema oscuro por defecto, `ui/widgets/{center_panel, chat_bubble, chat_feed,
composer, conversation_list, header_bar, right_panel, system_status_card, quick_actions_card,
recent_activity_card, weather_card, voice_orb, sidebar}.py`), no la arquitectura nueva de REQ-014
(`main_window.py`, `chat_area.py`, `input_bar.py`, etc. — esos archivos no existen en disco, solo
dentro de `stash@{0}`). `ai/memory_manager.py` tampoco tiene `delete_conversation()` en el working
tree actual (confirmado con `grep def`) — vive solo en el stash. La premisa del mensaje original y
del resumen ejecutivo de este contexto ("memoria/historial incluyendo `delete_conversation()` ya
implementada") queda corregida: no está implementada en disco, solo en el stash. Ver la Nota inicial
de `SPEC-015.md` para el detalle completo y la consecuencia práctica para `orion-baseline`. Ninguna
de las decisiones ya tomadas por Johan cambia por este hallazgo.

## Descartado (y por qué)
- Seguir iterando sobre QWidget + QSS puro (enfoque de REQ-014): descartado tras 3 ciclos completos
  dev→tester→qa→prueba manual, cada uno rechazado por un bug de renderizado/composición de Qt
  distinto, ninguno detectado por la suite de tests headless. Ver antecedente completo arriba.
2026-08-19 | orion-architect | `pywebview` como candidato técnico | Descartado frente a
`QWebEngineView` — reescribiría desde cero infraestructura ya probada en REQ-008/REQ-009/REQ-011
(tray, `WakeWordWorker`/`QThreadPool`, autostart) por el único beneficio de un menor tamaño en
disco. Ver `propuestas/arquitectura-015.md` §0.1 para la tabla de trade-offs completa.
2026-08-19 | orion-architect | React/Vue como framework frontend | Descartado — introduciría un
toolchain Node.js/npm/bundler inexistente hoy en el proyecto, superficie de build nueva sin
beneficio claro para una UI acotada (sidebar/chat/composer/modal) mantenida por un agente IA, no
por un equipo humano con convenciones de industria. Ver arquitectura-015.md §0.2.
2026-08-19 | orion-architect | Resaltado de código client-side (`highlight.js`+`marked`+`DOMPurify`
vendorizados) | Descartado a favor de Pygments server-side — 3 dependencias JS vendorizadas a mano
sin `npm` vs. una responsabilidad Python (`markdown`+`Pygments`+`bleach`) testeable con `pytest`
puro. Ver arquitectura-015.md §0.3.
2026-08-19 | orion-architect | Recrear `ui/gui.py` como shim de estado puro en el mismo path que
hoy (análogo al shim descartado de REQ-014) | Descartado tras confirmar con grep que ni
`voice/wake_word.py` ni `ui/stt/transcriber.py` dependen de ese path cuando hay una GUI activa —
ambos ya degradan solos en modo headless (`try/except`/fallback `lambda` ya presentes en el código
actual). Se usa un path nuevo, `ui/webview/gui_state.py`, sin ningún import hardcodeado externo que
lo obligue a llamarse `ui.gui`. Ver arquitectura-015.md §0.4.
2026-08-19 | orion-architect | `git checkout stash@{0} -- ai/memory_manager.py` para recuperar
`delete_conversation()` | Descartado — se reimplementa desde cero con comportamiento idéntico
(verificado contra el código del stash documentado en `baseline-015.md`) para no arrastrar sin
querer otros cambios del addendum de REQ-014 que pudieran estar mezclados en ese archivo dentro del
stash (riesgo señalado explícitamente por `orion-baseline`).

## Asumidos pendientes de confirmar
- **Candidato técnico** (`QWebEngineView` vs `pywebview`): sin decidir — orion-architect debe
  evaluar ambos con sus trade-offs documentados en el antecedente, no asumir uno de entrada.
- **Framework/librería frontend** (vanilla vs React/Vue): sin preferencia del humano, a decidir por
  orion-architect (respuesta de Johan, 2026-08-19).
- **Mecanismo de resaltado de código** (Pygments server-side vs librería JS client-side): a decidir
  por orion-architect, siempre que cumpla CA-13 de SPEC-015.
- **`delete_conversation()`**: recuperar del stash vs reimplementar — a decidir por
  orion-baseline/orion-architect; el comportamiento final debe ser idéntico al ya validado en
  REQ-014.

## Resuelto — respuestas de Johan (2026-08-19, ronda de clarificación de orion-spec)
1. **Código `ui/` de REQ-014 (12 archivos)**: se descarta TODO — se reemplaza entero por la capa
   WebView; `orion-architect` diseña desde cero la conexión con `voice/wake_word.py`, sin heredar el
   shim de `ui/gui.py` de REQ-014 (ese código queda descartado dentro del stash).
2. **Panel derecho**: sigue eliminado — decisión ya tomada en REQ-014 addendum §7 (no aparece en
   ninguna de las 4 referencias visuales), reconfirmada por Johan para REQ-015. No se migra ni se
   reactiva.
3. **Framework JS**: sin preferencia — decide orion-architect (mismo criterio que
   `QWebEngineView`/`pywebview`).
4. **Brief visual**: se mantiene el mismo de REQ-014 (jerarquía, tipografía grande en el saludo,
   input tipo píldora, paleta restringida, sin emoji, espaciado generoso) contra las 4 referencias,
   ahora con CSS real.
5. **Rama de trabajo**: confirmada y ya creada por Johan — `feature/REQ-015-webview-ui`, desde el
   mismo punto que `main` (sin divergencia de historia, la rama de REQ-014 nunca tuvo commits
   propios). Johan ya está parado en esa rama con el working tree limpio de código de REQ-014.

2026-08-19 | orion-spec | SPEC aprobada | Aprobado por Johan, TAL CUAL sin ajustes (relayada por
orion-coordinador) — incluidos los 7 puntos marcados ASUMIDO (candidato técnico `QWebEngineView` vs
`pywebview`, framework/librería frontend, mecanismo de resaltado de código, recuperación vs
reimplementación de `delete_conversation()`, footer del sidebar como placeholder, rama de trabajo,
templates ilustrativos de REQ-014 sin aplicar como código a portar). `workspace/adjuntos/REQ-015/
spec/SPEC-015.md` actualizada a ✅ COMPLETADO.
2026-08-19 | orion-spec | Tipo de cambio: REFACTOR | Confirmado en SPEC, coincide con lo registrado
por orion-coordinador.
2026-08-19 | orion-baseline | Confirmado en disco (no solo heredado del handoff): HEAD `eb190b3` de
`feature/REQ-015-webview-ui` = arquitectura REQ-013 completa, sin `delete_conversation()` en
`ai/memory_manager.py` (`grep def` exit 1) | Ver `origen/baseline-015.md` para el detalle completo
(archivos a `git rm`, py_compile, conteo de tests).
2026-08-19 | orion-baseline | 15 archivos trackeados identificados a `git rm` (arquitectura REQ-013):
`ui/gui.py`, `ui/theme.py` + 13 archivos de `ui/widgets/*` | Confirmados presentes en disco uno por
uno, coincide exactamente con la lista de `SPEC-015.md` §Módulos afectados.
2026-08-19 | orion-baseline | `delete_conversation()` confirmada completa y disponible en
`stash@{0}` (`git show stash@{0}:agente_ia/ai/memory_manager.py`, líneas 502-526), sin aplicar el
stash | Queda documentada íntegra en `origen/baseline-015.md` como referencia para que
`orion-architect` decida recuperarla o reimplementarla — mismo comportamiento (DELETE real,
restringido por `user_id`, retorna `False` sin excepción si no existe).
2026-08-19 | orion-baseline | Fallos pre-existentes registrados: 2 failed, 305 passed (con
`PYTEST_QT_API=pyqt6` fijado manualmente) | Los 2 fallos son `ModuleNotFoundError: No module named
'anthropic'` en `tests/test_llm_provider.py` (ambiental, `anthropic` no instalado, no atribuible a
REQ-015) — coincide exacto con el conteo de referencia de `baseline-014.md` para el mismo HEAD.
2026-08-19 | orion-baseline | Confirmado que `tests/conftest.py` de esta rama NO fija
`PYTEST_QT_API=pyqt6` (solo `QT_QPA_PLATFORM=offscreen` de REQ-008) | Sin esa variable, la misma
suite da 66 failed / 241 passed (verificado en esta sesión) — el fix vive solo en
`stash@{0}:agente_ia/tests/conftest.py`, no en disco. Trasladado a "Riesgos activos".
2026-08-19 | orion-baseline | `python -m py_compile` limpio (exit 0) sobre los 20 módulos relevantes
de `ui/`, `ai/memory_manager.py`, `config_manager.py`, `main.py` | Sin errores de compilación en
`eb190b3`.
2026-08-19 | orion-architect | Candidato técnico: `QWebEngineView` (PyQt6-WebEngine) | Se integra
como `QWidget` único dentro del `QMainWindow`/tray/`QThreadPool` ya probados (REQ-008/009/011); usa
además `startSystemResize()`/`startSystemMove()` nativos de `QWindow` (Qt 5.15+) para CA-01/CA-02
sin reimplementar drag/resize a mano. Ver arquitectura-015.md §0.1 para la tabla completa de
trade-offs contra `pywebview`.
2026-08-19 | orion-architect | Framework frontend: vanilla HTML/CSS/JS con módulos ES6, sin build
step ni `npm`/bundler | Ver arquitectura-015.md §0.2.
2026-08-19 | orion-architect | Resaltado de código: Pygments server-side (`markdown` + extensión
`codehilite`) + sanitización HTML con `bleach` antes de insertar en el WebView (mitigación central
de XSS) | JS nunca parsea Markdown ni sanitiza — solo hace `innerHTML` de HTML ya confiable. Ver
arquitectura-015.md §0.3 y §5.2.
2026-08-19 | orion-architect | Mecanismo de reflejo de estado de voz: `ui/webview/gui_state.py`
(estado puro, sin Qt) + `ui/webview/wake_word_worker.py` (mismo diseño que el `WakeWordWorker` de
hoy, sobre `voice/wake_word.py` sin modificarlo) | Confirmado por grep que `ui/stt/transcriber.py`
es exclusivo de la CLI de texto (no lo usa la GUI actual) y que la rama de `voice/wake_word.py` que
importa `ui.gui` solo se alcanza en modo headless sin GUI, ya con fallback defensivo. Ver
arquitectura-015.md §0.4.
2026-08-19 | orion-architect | `delete_conversation()` se reimplementa desde cero en
`ai/memory_manager.py` (no se recupera del stash), con comportamiento idéntico al documentado en
`baseline-015.md` (DELETE real, filtrado por `user_id`, retorna `False` sin excepción sobre
conversación inexistente) | Ver "Descartado" arriba para el motivo.
2026-08-19 | orion-architect | Confirmación YELLOW (CA-41) vía un nuevo adaptador registrado en
`ChannelType.DESKTOP` que muestra un modal en el WebView y bloquea el hilo worker (nunca el hilo de
la GUI) con `threading.Event(timeout=120s, fail-closed)` | Reemplaza en runtime al adaptador de
consola (`main.py::_desktop_confirm`) solo cuando `MainWindow` se construye con éxito — en modo
headless el adaptador de consola sigue siendo el activo, sin cambio de comportamiento. El gate de
clasificación de riesgo de `core/security_manager.py` no se toca. Ver arquitectura-015.md §4.3.
2026-08-19 | orion-architect | Se recomienda un pase de `orion-security` antes de `orion-dev` | El
bridge Python↔JS, la confirmación YELLOW nueva y la lectura de rutas de archivo desde drag&drop son
superficie de seguridad genuinamente nueva frente a REQ-013/REQ-014 (ambos 🟢 Verde completo). Ver
arquitectura-015.md §9.
2026-08-19 | orion-architect | `tests/conftest.py`: se fija `os.environ.setdefault("PYTEST_QT_API",
"pyqt6")` (una línea, mismo fix probado en `stash@{0}` de REQ-014) | Cierra el riesgo de entorno que
señaló `orion-baseline` — evita que `orion-tester` confunda los 66 fallos ambientales con
regresiones reales de REQ-015.
2026-08-19 | orion-architect | Propuesta técnica completa redactada en
`propuestas/arquitectura-015.md` — cubre los 48 CA de SPEC-015, contrato exacto del bridge
Python↔JS (comandos JS→Python y eventos Python→JS), 11 archivos Python nuevos + estructura de
frontend estático, dependencias nuevas (`PyQt6-WebEngine`, `markdown`, `Pygments`, `bleach`),
riesgos con mitigación, y 10 archivos de test nuevos/reemplazados | PENDIENTE de aprobación humana
explícita — el flujo no continúa a `orion-dev` (ni, si corresponde, a `orion-security`) hasta
recibirla.
2026-08-19 | orion-architect | Arquitectura aprobada por Johan (relayado por el coordinador) — tal
cual, sin ajustes | Johan confirmó además la recomendación del §9 de arquitectura-015.md: el REQ
pasa por `orion-security` ANTES de `orion-dev` (no se salta ese paso), dado el bridge Python↔JS, la
confirmación amarilla nueva y la lectura de rutas de archivo por drag&drop — superficie de
seguridad nueva frente a REQ-013/REQ-014 (ambos 🟢 Verde completo). CSV actualizado vía
update-tracker.mjs: Estado → ARQUITECTURA_APROBADA, Aprobacion_Arquitectura → APROBADO, Rama →
`feature/REQ-015-webview-ui`.
2026-08-19 | orion-architect | Addendum §10 redactado en `arquitectura-015.md` respondiendo a los 2
hallazgos bloqueantes de `security-audit-015.md` (Hallazgo A y C) — no se reescribió nada de §0-§9,
mismo patrón usado en el addendum §7 de `arquitectura-014.md` | §10.1: regla general nueva sobre §4
— todo campo del bridge no marcado como `html` pre-sanitizado se inserta en el DOM solo vía
`textContent`/`setAttribute`, nunca `innerHTML`, especificada punto por punto para `sidebar.js`
(título), `composer.js` (nombre de archivo) y `confirm_modal.js` (mensaje/`action_name`) — más 2
pruebas nuevas en §8 (`test_webview_safe_dom_insertion.py` grep estructural + extensión adversarial
de `test_webview_smoke.py` con `<img src=x onerror=...>` sobre `QWebEngineView` offscreen real).
§10.2: `delete_conversation` reclasificada a `RiskLevel.YELLOW`, registrada en
`core/security_manager.py::_register_default_actions()` (patrón confirmado por grep del código real,
línea 300-329/374 — mismo bloque que `delete_file`/`delete_folder`) — `Bridge.
request_delete_conversation()` pasa ahora por `security_manager.require_confirmation()` reutilizando
el `WebViewConfirmationAdapter` ya diseñado para CA-41 en §4.3, sin un segundo mecanismo de
confirmación; se documentó explícitamente por qué `details` usa la clave `"name"` (`conversation_id`
no está en `_DETAILS_ALLOWED_KEYS`, confirmado leyendo `format_details()` línea 79-106) para que el
borrado no pierda trazabilidad de auditoría. Hallazgo B (no bloqueante) queda referenciado en §10.3
sin cambio de arquitectura, tal como pidió `orion-security`. CSV deliberadamente NO actualizado —
requiere nueva aprobación humana explícita antes de continuar a `orion-dev`. Siguiente: humano
(APROBADO / AJUSTAR / RECHAZADO sobre §10).
2026-08-19 | orion-security | ❌ REQUIERE CAMBIOS — auditoría completa en
`pruebas/security-audit-015.md` | Verificado contra el código real (`core/security_manager.py`,
`core/confirmation.py`, `agents/action_registry.py`, `main.py`), no solo contra el texto de la
arquitectura: el gate `require_confirmation()` sigue fail-closed y sin tocar, el registro del
adaptador de confirmación de consola en `main.py:29` ocurre a nivel de módulo (antes de que
`MainWindow` pueda construirse) — no hay ventana sin adaptador activo, y `run_chip_action` sí pasa
siempre por `execute_action()` con `channel=ChannelType.DESKTOP` hardcodeado del lado Python.
**Hallazgo A (bloqueante):** la arquitectura marca `html` como el único campo pre-sanitizado del
bridge (§4.2), pero no especifica cómo debe insertarse en el DOM el resto de campos de texto libre
(`title` de conversación, `name` de archivo dropeado — que puede venir de un tercero, no del propio
usuario —, `message`/`action_name` del modal de confirmación amarilla) — sin una regla explícita de
`textContent`/`setAttribute` (nunca `innerHTML`), cualquiera de esos puntos podría ejecutar script
en la misma página donde vive `window.bridge`, con acceso directo a todos sus comandos (incluido
autoconfirmar sus propias solicitudes YELLOW vía `confirm_response`). **Hallazgo C (bloqueante):**
`delete_conversation()` sigue documentada con confirmación "a nivel UI" (modal JS, sin pasar por
`security_manager.require_confirmation()`) — mismo criterio no bloqueante que aceptó
`qa-audit-014.md`, pero ya no aplica: en REQ-014 el borrado solo lo disparaba un `QPushButton`
nativo (inalcanzable desde fuera del proceso Python), en REQ-015 `request_delete_conversation()` es
un `@pyqtSlot` invocable por cualquier script que corra en la página — el modal JS no es una
barrera real contra ese vector, y además el borrado hoy no queda registrado en el log de auditoría
de `security_manager`. Recomendado reclasificar a `RiskLevel.YELLOW` y reusar el mismo
`WebViewConfirmationAdapter` que ya se construye para CA-41. **Hallazgo B (no bloqueante, para
`orion-dev` directo):** falta especificar en §4.3 la limpieza de `self._pending[request_id]` tras
resolución y el manejo defensivo de un `request_id` desconocido en `confirm_response()` — el diseño
base (uuid4 por solicitud, timeout fail-closed) es correcto, solo falta completarlo. Ninguna de las
4 decisiones técnicas centrales (§0.1-§0.4) ni el diseño general del bridge se cuestionan — ajustes
acotados, no rediseño. Handoff: @orion-architect con los 2 puntos bloqueantes (A y C) para
incorporar a `arquitectura-015.md` (§1 tabla CA-10, §4, §8) antes de repasar a `orion-security`/
`orion-dev`.
2026-08-19 | orion-architect | Addendum §10 aprobado por Johan (relayado por el coordinador) — tal
cual, sin ajustes | Cierra los 2 hallazgos bloqueantes de `security-audit-015.md` (A y C). Arquitectura
completa (§0-§9 base + §10 ajustes de seguridad) queda lista como única referencia para `orion-dev`.
CSV sin cambios — la aprobación de §10 no mueve el tracker, sigue en `ARQUITECTURA_APROBADA`; el
próximo estado (`EN_DESARROLLO`) lo escribe `orion-dev`. Siguiente: @orion-dev.

## Riesgos activos
- (orion-security) `QWebChannel` no aísla origen: cualquier script que corra en la página del
  WebView (propio o inyectado por una falla de sanitización) tiene el mismo acceso a
  `window.bridge` que el código legítimo de `app.js`. Mientras no se cierre el Hallazgo A
  (`security-audit-015.md`), todo campo de texto no confiable insertado en el DOM sin
  `textContent`/`setAttribute` es una vía potencial hacia el control total del bridge, incluida la
  autoconfirmación de solicitudes YELLOW. Bloqueante — ver `pruebas/security-audit-015.md`.
- (orion-security) `delete_conversation()` queda sin trazabilidad en el log de auditoría de
  `security_manager` mientras no se enrute por `require_confirmation()` (Hallazgo C). Bloqueante —
  ver `pruebas/security-audit-015.md`.
- Dependencia nueva potencialmente pesada si se elige `QWebEngineView` (~150-200MB, Chromium
  embebido) — a ponderar en arquitectura contra el riesgo de reescribir el shell de la app si se
  elige `pywebview`.
- Bridge Python↔JS es superficie nueva: debe quedar estrictamente limitado a disparar eventos que
  Python resuelve — JS no debe ejecutar lógica de negocio ni saltarse el gate de seguridad
  verde/amarillo/rojo ya vigente (REQ-005/REQ-006).
- Riesgo de repetir el patrón de REQ-014 (tests headless en verde, bug real solo visible en
  prueba manual) si la nueva suite de tests tampoco cubre renderizado real del WebView — a
  considerar en orion-tester/orion-qa cuando corresponda.
- `tests/conftest.py` de esta rama no fija `PYTEST_QT_API=pyqt6` (confirmado por orion-baseline) —
  sin esa variable, la suite muestra 66 fallos falsos por conflicto `isinstance()` PyQt6/PySide6 en
  `qtbot.addWidget()` (ambos paquetes están instalados en este entorno). El fix ya existe probado en
  `stash@{0}:agente_ia/tests/conftest.py` (línea `os.environ.setdefault("PYTEST_QT_API", "pyqt6")`)
  pero no se aplicó al disco — decisión de `orion-architect`/`orion-dev` si se vuelve a fijar. Sin
  este fix, `orion-tester` podría confundir fallos ambientales de entorno con regresiones reales de
  REQ-015. Referencia correcta de no-regresión (CA-48): **2 failed, 305 passed** con la variable
  fijada. `orion-architect` decidió fijarlo en la propuesta — ver "Decisiones tomadas".
- (orion-architect) Interceptar el drop nativo de archivos (CA-23) a nivel de `QMainWindow` antes de
  que `QWebEngineView`/Chromium lo consuma internamente no está garantizado por documentación
  oficial — riesgo técnico a validar empíricamente por `orion-dev`. Mitigación de respaldo ya
  documentada: deshabilitar `DragDropEnabled` en `QWebEngineSettings` si el `eventFilter` no
  alcanza. Ver arquitectura-015.md §5.3 y §7.
- (orion-architect) `QWebEngineView` en modo offscreen para los smoke tests automatizados de CA-03/
  CA-05 (arquitectura-015.md §8) puede ser lento o inestable según el entorno de CI/GPU — se marcan
  aparte del resto de la suite para no bloquearla si el entorno no los soporta bien.

## Log de transiciones
2026-08-19 | — → NUEVO | orion-coordinador | REQ creado
2026-08-19 | NUEVO → SPEC_APROBADO | orion-spec | SPEC-015.md redactada (48 CA) tras resolver una
ronda de clarificación con el humano (destino del código `ui/` de REQ-014, panel derecho, framework
JS, brief visual, rama de trabajo) y 2 hallazgos de git corregidos en el camino: (1)
`workspace/adjuntos/REQ-014/` restaurada al disco (había quedado incluida sin querer en el `git
stash -u` del código, sin tocar el stash ni el código); (2) el punto de partida real en disco es la
arquitectura de REQ-013 (`eb190b3`), no la de REQ-014 (que nunca se commiteó, vive completa en
`stash@{0}`). Aprobada por Johan tal cual, sin ajustes, incluidos los 7 puntos ASUMIDO. CSV
actualizado vía update-tracker.mjs. Siguiente: @orion-baseline
2026-08-19 | SPEC_APROBADO → EN_ARQUITECTURA | orion-baseline | Baseline redactado en
`origen/baseline-015.md`: confirmado en disco que HEAD `eb190b3` es arquitectura REQ-013 completa
(15 archivos trackeados a `git rm`), sin `delete_conversation()` en `ai/memory_manager.py`. Suite de
tests corrida con `PYTEST_QT_API=pyqt6`: 2 failed (ambiental, `anthropic` no instalado), 305 passed —
ninguno atribuible a REQ-015. `py_compile` limpio sobre 20 módulos relevantes. `delete_conversation()`
confirmada íntegra en `stash@{0}` (no aplicado, solo consultado) como referencia para
`orion-architect`. Riesgo de entorno (`PYTEST_QT_API` no fijado en `tests/conftest.py` de esta rama)
documentado en "Riesgos activos". CSV actualizado vía update-tracker.mjs. Siguiente: @orion-architect
2026-08-19 | EN_ARQUITECTURA → ARQUITECTURA_APROBADA | orion-architect | Propuesta técnica redactada
en `propuestas/arquitectura-015.md` (48 CA cubiertos, candidato técnico `QWebEngineView`, frontend
vanilla HTML/CSS/JS, resaltado server-side con Pygments+`bleach`, mecanismo de estado de voz nuevo
sin recrear `ui/gui.py`, contrato completo del bridge Python↔JS, confirmación amarilla vía modal +
`threading.Event`, `delete_conversation()` reimplementada desde cero, fix de `PYTEST_QT_API` en
`tests/conftest.py`). Aprobada por Johan tal cual, sin ajustes, incluida la recomendación de pasar
por `orion-security` antes de `orion-dev`. CSV actualizado vía update-tracker.mjs. Siguiente:
@orion-security
2026-08-19 | ARQUITECTURA_APROBADA → ARQUITECTURA_APROBADA (sin cambio) | orion-security | Auditoría
completa en `pruebas/security-audit-015.md` — veredicto ❌ REQUIERE CAMBIOS, verificado contra el
código real (`core/security_manager.py`, `core/confirmation.py`, `agents/action_registry.py`,
`main.py`), no solo contra el texto de la arquitectura. **Hallazgo A (bloqueante):** falta una regla
explícita de inserción segura en el DOM para los campos del bridge que no son `html` pre-sanitizado
(título de conversación, nombre de archivo dropeado, mensaje/`action_name` del modal amarillo) — sin
ella, cualquiera podría ejecutar script con acceso directo a `window.bridge`, incluida la
autoconfirmación de solicitudes YELLOW. **Hallazgo C (bloqueante):** `delete_conversation()` sigue
con confirmación "a nivel UI" (modal JS, sin pasar por `security_manager.require_confirmation()`) —
criterio que era válido en REQ-014 (borrado solo alcanzable vía `QPushButton` nativo) pero ya no
aplica en REQ-015 (`request_delete_conversation()` es un `@pyqtSlot` invocable desde cualquier script
de la página); recomienda reclasificar a `RiskLevel.YELLOW` reusando el `WebViewConfirmationAdapter`
de CA-41. **Hallazgo B (no bloqueante):** documentado directo para `orion-dev` — limpieza de
`self._pending[request_id]` tras resolución y manejo defensivo de `request_id` desconocido en
`confirm_response()`. Las 4 decisiones técnicas centrales (§0.1-§0.4) y el diseño general del bridge
no se cuestionan. CSV no tocado — Estado permanece en `ARQUITECTURA_APROBADA`. Siguiente:
@orion-architect (incorporar hallazgos A y C).
2026-08-19 | ARQUITECTURA_APROBADA → ARQUITECTURA_APROBADA (sin cambio) | orion-architect | Aplicados
los 2 ajustes bloqueantes de `security-audit-015.md` en la sección nueva §10 de
`arquitectura-015.md`, sin reescribir nada de §0-§9. **Hallazgo A:** regla general nueva sobre §4 —
todo campo del bridge no marcado como `html` pre-sanitizado se inserta en el DOM solo vía
`textContent`/`setAttribute`, nunca `innerHTML`, especificada punto por punto para `sidebar.js`
(título), `composer.js` (nombre de archivo) y `confirm_modal.js` (mensaje/`action_name`) — más 2
pruebas nuevas en §8 (`test_webview_safe_dom_insertion.py` grep estructural + extensión adversarial
de `test_webview_smoke.py` con `<img src=x onerror=...>` sobre `QWebEngineView` offscreen real).
**Hallazgo C:** `delete_conversation` reclasificada a `RiskLevel.YELLOW`, registrada en
`core/security_manager.py::_register_default_actions()` (mismo bloque que `delete_file`/
`delete_folder`) — `Bridge.request_delete_conversation()` pasa ahora por
`security_manager.require_confirmation()` reutilizando el `WebViewConfirmationAdapter` ya diseñado
para CA-41 en §4.3, sin un segundo mecanismo de confirmación, con trazabilidad en el log de
auditoría. Hallazgo B queda referenciado en §10.3 sin cambio de arquitectura, tal como pidió
`orion-security`. CSV deliberadamente NO actualizado — §10 requiere nueva aprobación humana explícita
antes de continuar a `orion-dev`. Siguiente: humano (APROBADO / AJUSTAR [qué] / RECHAZADO [motivo]
sobre §10).
2026-08-19 | ARQUITECTURA_APROBADA → ARQUITECTURA_APROBADA (sin cambio) | orion-architect | Johan
aprobó el addendum §10 tal cual, sin ajustes (relayado por el coordinador). No hay transición de
`Estado` nueva que hacer — la aprobación de §10 es correctiva sobre una arquitectura ya aprobada, el
tracker sigue en `ARQUITECTURA_APROBADA`; CSV sin cambios en esta pasada. Arquitectura completa y
vigente para `orion-dev`: `propuestas/arquitectura-015.md` §0-§9 (base, aprobada 2026-08-19) + §10
(ajustes de seguridad post-auditoría, aprobado 2026-08-19). Siguiente: @orion-dev.
2026-08-19 | orion-dev | Implementación verificada y cerrada en `propuestas/desarrollo-log-015.md`
(reanudación tras corte por expiración de OAuth — NO fue error ni rechazo; el código de §0-§10 ya
estaba prácticamente completo en disco al reanudar) | Verificado punto por punto contra el código
real (no solo contra los nombres de archivo): §10.1 (inserción segura en el DOM, `sidebar.js`/
`composer.js`/`confirm_modal.js` usan solo `textContent`, `chat.js` es el único con `innerHTML` para
el campo ya sanitizado) y §10.2 (`delete_conversation` registrada `RiskLevel.YELLOW` en
`core/security_manager.py`, `Bridge._delete_conversation_flow()` pasa por
`require_confirmation()`) confirmados implementados tal cual la arquitectura. Hallazgo B (no
bloqueante) también confirmado implementado en `confirmation_adapter.py`. Diagnóstico heredado
(`_diag_layout.py`/`_diag_step1.py`) resuelto: el layout se arma correctamente (sidebar 260px,
chat-area/composer bien dimensionados, sin overflow vertical) — los scripts crasheaban por no
llamar `window.show()`/`waitExposed()` antes de medir, no por un bug real; ambos borrados (eran
instrumentación temporal). Suite completa: 365 passed, 2 failed (mismos 2 ambientales de
`baseline-015.md`, `anthropic` no instalado) — sin regresiones.
2026-08-19 | orion-dev | 2 bugs reales encontrados y corregidos durante la verificación manual con
`python main.py` real (no offscreen) | **CA-15** — `#typing-indicator[hidden]` no tenía efecto por
especificidad CSS (`#typing-indicator{display:flex}`, un ID, le ganaba a la regla `[hidden]` del
user-agent) — el indicador de "escribiendo" quedaba visible siempre, confirmado con Chrome DevTools
Protocol contra la ventana real antes/después de enviar un mensaje. Fix: regla
`#typing-indicator[hidden]{display:none}` en `chat.css`. **DPI awareness** — varias skills no
relacionadas con este REQ (`screen_analysis_skill.py`, `screenshot_tools.py`) importan `pyautogui`,
que en Windows llama `SetProcessDPIAware()` como efecto secundario de su propio import, antes de que
exista `QApplication` — le gana la carrera a Qt/QtWebEngine para fijar
`DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2` (log real: "Acceso denegado"). Fix: se fija el contexto
correcto como lo primero que hace `main.py`, antes de cualquier otro import. Ninguno de los 2 fixes
está en `arquitectura-015.md` — son hallazgos de la verificación manual, documentados con motivo en
`desarrollo-log-015.md` (DoD `orion-dev`: "cualquier ajuste menor respecto a la propuesta, con
motivo").
2026-08-19 | orion-dev | ⚠️ Hallazgo NO cerrado al 100% — recorte visual aparente del saludo/sidebar
en capturas de pantalla a escala 150%, en el entorno de verificación de esta sesión | Investigado a
fondo (ver `desarrollo-log-015.md` sección "Bug 2"): medido con Chrome DevTools Protocol
(`getBoundingClientRect()`) directo contra la ventana real corriendo, el layout CSS está
correctamente contenido dentro de la ventana (sin overflow) — la discrepancia está en la herramienta
de captura de pantalla usada en este entorno (`GetWindowRect`/`PrintWindow` vía PowerShell), no
confirmada como un bug de la propia app. Se aplicó igual el fix de DPI awareness (arriba, correcto y
necesario de todos modos) pero no cambió la captura, reforzando que el layout interno ya estaba bien.
**Se deja marcado explícitamente para la prueba manual final del humano** — CA-04/§8 de la
arquitectura piden inspección visual real "con especial atención a un factor de escala distinto de
100%"; este REQ no lo da por cerrado solo con las capturas de este entorno de verificación.
2026-08-19 | orion-dev | Estado tracker → EN_PRUEBAS | `desarrollo-log-015.md` completo, mensaje de
commit sugerido entregado (no ejecutado). Siguiente: @orion-tester.
2026-08-19 | orion-tester | 48/48 CA PASS — veredicto PASS | Ver `pruebas/test-results-015.md`.
Verificado por lectura de código real (no por confianza en el reporte de `orion-dev`): §10.1 (grep
estructural + 8/8 `test_webview_safe_dom_insertion.py` + 3/3 casos adversariales XSS de
`test_webview_smoke.py`, leído el código de los tests para confirmar que son reales, no
placeholders), §10.2 (`delete_conversation` YELLOW en `security_manager.py` línea 311,
`Bridge.request_delete_conversation()` pasa por `require_confirmation()` antes de tocar `memory`),
Hallazgo B (limpieza de `_pending` + manejo defensivo confirmados en `confirmation_adapter.py`), fix
de typing indicator (`#typing-indicator[hidden]` en `chat.css`, confirmado por lectura — no
reproducido en vivo, ver hallazgo de estabilidad) y fix de DPI awareness en `main.py` (confirmado
como primera línea ejecutada del proceso). Suite completa re-ejecutada de forma independiente:
**365 passed, 2 failed** (mismos 2 ambientales de `baseline-015.md`) — coincide exacto con lo
reportado por `orion-dev`. Diff estructural confirmado: 15 `git rm`, 11 backend nuevo, 21 frontend
nuevo (coincide con el árbol de §2), 11 tests nuevos (handoff decía "12", discrepancia cosmética del
texto del handoff, no del código), 8 archivos modificados (handoff decía "6", misma discrepancia
cosmética) — cada archivo individual coincide con `desarrollo-log-015.md`.
2026-08-19 | orion-tester | ✅ CERRADO — hallazgo de escalado 150% que `orion-dev` dejó pendiente |
Este entorno de verificación corre a 150% de escala (DPI 144, pantalla física 1920×1080). Reproduje
ambas versiones de la captura de la ventana real: con el llamador de `GetWindowRect`/`PrintWindow`
SIN marcar `SetProcessDpiAwarenessContext`, reproduje exactamente el mismo recorte visual que
describió `orion-dev` (rect virtualizado 1088×640 vs. contenido físico real 1632×960); con el
llamador marcado `PER_MONITOR_AWARE_V2` ANTES de `GetWindowRect`, el rect físico real sale correcto
(1632×960) y la captura no muestra ningún recorte — saludo, avatar y sidebar completos, con margen.
Confirma de forma concluyente e independiente (sin CDP, por una vía distinta a la que usó
`orion-dev`) que el recorte era 100% un artefacto de la herramienta de captura (llamador no
DPI-aware), no un bug de la app. La app renderiza correctamente a 150% de escala, verificado en
ambos temas (oscuro y claro).
2026-08-19 | orion-tester | ⚠️ Hallazgo nuevo, no bloqueante — crash nativo intermitente
(`0xC0000005` en `Qt6Quick.dll`) de la ventana real en este sandbox, 2 veces reproducido | Logs de
Chromium muestran `Failed to create shared context for virtualization` — atribuible a la GPU
virtualizada de este sandbox específico, misma familia de riesgo ya documentada en
`arquitectura-015.md` §7 para `QWebEngineView` offscreen, ahora también observada en la ventana real
de este entorno. Distinto y adicional: toda sesión lanzada por este agente muere a los ~15s por un
hazard preexistente y ya documentado de REQ-009 (stdin nulo del shell de automatización →
`EOFError` en `ui/cli.py::get_input_method()` → `os._exit(0)` de `jarvis_runner` mata todo el
proceso incluida la GUI) — reproducido con traceback completo, confirmado no ser una regresión de
REQ-015. Ninguno de los dos se trata como bloqueante — la primera sesión lograda entregó evidencia
limpia de CA-03/04/05/40/46 en ambos temas antes de tropezar con cualquiera de los dos. Documentado
para que `orion-qa` y la prueba manual final del humano (en su propia máquina, con GPU real) presten
atención a la estabilidad de una sesión larga. Ver `pruebas/test-results-015.md` sección dedicada.
2026-08-19 | orion-tester | Estado tracker → EN_QA | Veredicto PASS, 48/48 CA. Siguiente: @orion-qa.

## Estado actual (actualización orion-dev)
- Estado tracker: EN_PRUEBAS
- Último agente: orion-dev
- Archivos: ver `propuestas/desarrollo-log-015.md`
- Tests: 365 passed, 2 failed (ambientales, sin regresión)
- Pendiente explícito para @orion-tester / prueba manual humana: confirmar visualmente en una
  máquina real (no el entorno de este REQ) que no hay recorte/overflow visual a escalas de pantalla
  ≠ 100%, ver hallazgo "no cerrado al 100%" arriba.

## Estado actual (actualización orion-tester)
- Estado tracker: EN_QA
- Último agente: orion-tester
- Veredicto: PASS — 48/48 CA, ver `pruebas/test-results-015.md`
- Tests: 365 passed, 2 failed (ambientales, confirmado de forma independiente, sin regresión)
- Escalado 150%: CERRADO — confirmado que el recorte que veía `orion-dev` era un artefacto de la
  herramienta de captura (llamador no DPI-aware), no un bug de la app. La app renderiza
  correctamente a 150% de escala.
- Pendiente para @orion-qa / prueba manual humana: prestar atención a la estabilidad de la ventana
  en una sesión larga — se observó un crash nativo intermitente (`0xC0000005` en `Qt6Quick.dll`) en
  este sandbox específico, atribuido con evidencia de logs a virtualización de GPU del entorno, no al
  código de REQ-015. No bloqueante para este gate, ver hallazgo dedicado en
  `pruebas/test-results-015.md`.

2026-08-19 | orion-qa | ✅ COMPLETADO — auditoría completa en `pruebas/qa-audit-015.md` | Verificado
por lectura directa del código real (no por confianza en `orion-dev`/`orion-tester`), siguiendo los 5
puntos del handoff de Johan: (1) Hallazgo A (`sidebar.js`/`composer.js`/`confirm_modal.js` usan solo
`textContent`; `chat.js` es el único con `innerHTML`, exclusivamente para el campo `html` ya pasado
por `render_markdown()`+`bleach` en `bridge.py`) y Hallazgo C (`delete_conversation` YELLOW en
`security_manager.py:311`, `Bridge._delete_conversation_flow()` pasa por `require_confirmation()`
antes de tocar `memory`) re-confirmados contra el código implementado. (2) Bridge: 15 `@pyqtSlot` en
`bridge.py`, los 15 coinciden uno a uno con `bridge_client.js`, sin superficie no documentada, sin
`eval`/`exec`, imports acotados a la lista aprobada, canal `ChannelType.DESKTOP` siempre hardcodeado
del lado Python. (3) Crash nativo intermitente: evidencia directa en logs de Chromium de ser
virtualización de GPU del sandbox + hazard preexistente de REQ-009 (stdin nulo) — no bloqueante,
documentado como riesgo de entorno para la prueba manual. (4) Timeout de confirmación YELLOW
fail-closed confirmado (`confirm() ` retorna `False` si expira, nunca `True` por defecto);
`_desktop_confirm` registrado a nivel de módulo en `main.py` antes de que `MainWindow` pueda
construirse — nunca hay una ventana sin adaptador activo. (5) `bleach.clean()` confirmado en el
camino real de datos: todo `message_appended`/`turns_loaded` pasa por `render_markdown()` sin
excepción antes de llegar al único `innerHTML` real (`chat.js:42`). Checklist estándar sin
hallazgos: sin secretos hardcodeados, sin `except: pass` silencioso, sin dead code (scripts de
diagnóstico temporales confirmados ausentes de disco), `requirements.txt` actualizado con las 4
dependencias nuevas. CSV actualizado vía update-tracker.mjs (Estado se mantiene en `EN_QA` hasta
recibir el OK de la prueba manual). Siguiente: prueba manual de Johan — ver mensaje de solicitud
entregado en el handoff de esta sesión.
