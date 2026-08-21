# SPEC-015 — Migrar panel de escritorio NODDOO a WebView (HTML/CSS/JS real)

**Estado:** ✅ COMPLETADO — Aprobado por Johan (2026-08-19), tal cual, sin ajustes (incluidos los 7
puntos marcados ASUMIDO)
**Categoría:** UI
**Tipo:** REFACTOR
**Fecha:** 2026-08-19

## Nota para el humano — el punto de partida NO es la implementación de REQ-014

Verificado directamente contra `git` (no asumido): **ningún commit de REQ-014 llegó a `main`**.
Los 3 ciclos de dev→tester→qa→prueba manual de REQ-014 (43 CA de SPEC-014 + addendum §7 + fix
bloqueante) se hicieron enteramente sobre working tree sin commitear, y ese working tree completo
(código + los 43 CA verificados + el addendum) quedó resguardado por Johan en
`stash@{0}` ("REQ-014 (EN_QA, sin commitear)...") antes de crear la rama de REQ-015. El HEAD actual
de `feature/REQ-015-webview-ui` es `eb190b3`, el mismo commit del que partió REQ-014 — que contiene
la **arquitectura de REQ-013**, no la de REQ-014:

- `ui/gui.py`, `ui/theme.py` (con `DEFAULT_THEME = "dark"`), `ui/widgets/{center_panel, chat_bubble,
  chat_feed, composer, conversation_list, header_bar, right_panel, system_status_card,
  quick_actions_card, recent_activity_card, weather_card, voice_orb, sidebar}.py` — confirmado con
  `ls`/`git log` en esta misma sesión.
- `ui/main_window.py`, `ui/sidebar.py` (top-level), `ui/chat_area.py`, `ui/input_bar.py`,
  `ui/message_bubble.py`, `ui/typing_indicator.py`, `ui/animations.py`, `ui/workers.py`,
  `ui/components/{avatar,code_block,markdown_renderer}.py` (arquitectura de REQ-014) **no existen
  en disco** — viven solo dentro de `stash@{0}`.
- `ai/memory_manager.py` **no tiene `delete_conversation()`** en el working tree actual (confirmado
  con `grep def` en esta sesión) — esa función también vive solo en el stash. La premisa del mensaje
  original y de `REQ-015-context.md` ("memoria/historial ... incluyendo `delete_conversation()` ya
  implementada en REQ-014") es inexacta respecto al estado real en disco; queda corregida acá.
- El panel derecho SÍ está presente en el código committeado actual (`right_panel.py` + 4 tarjetas),
  pese a que fue eliminado en el addendum §7 de REQ-014 — esa eliminación tampoco llegó a `main`.
- `workspace/adjuntos/REQ-014/` (spec, arquitectura, qa-audit, context, capturas) quedó incluida sin
  querer en el mismo `stash@{0}` (se usó `git stash -u`, que también agarra no-trackeados como esa
  carpeta de evidencias). Restaurada al disco en esta sesión sin tocar el código (`git checkout
  stash@{0}^3 -- workspace/adjuntos/REQ-014/` + `git reset` para dejarla no-trackeada otra vez, tal
  como estaba) — el stash no se tocó, sigue disponible completo para lo que `orion-baseline`
  necesite consultar.

**Consecuencia práctica para el resto del pipeline:** el "actual" real que `orion-baseline` va a
encontrar y tiene que reemplazar/`git rm` es la arquitectura de archivos de **REQ-013** (tema
oscuro por defecto, panel derecho presente, sin `delete_conversation()`), no la de REQ-014. El
**diseño objetivo** a igualar en comportamiento —y a mejorar tecnológicamente— es el que documentan
`SPEC-014.md` + su addendum §7 completos (43 CA + 7 refinamientos visuales + eliminación del panel
derecho + tema claro por defecto), disponibles otra vez en `workspace/adjuntos/REQ-014/`. Esta SPEC
ya lo tiene en cuenta: la tabla "Comportamiento actual vs deseado" y "Módulos afectados" reflejan el
estado real en disco, no el de REQ-014.

Ninguna de las 5 decisiones que ya tomó Johan sobre REQ-015 cambia por este hallazgo (se reconfirman
todas más abajo) — es una corrección de premisa fáctica, no una nueva pregunta.

## Objetivo
Reconstruir la capa visual del panel de escritorio NODDOO como una interfaz HTML/CSS/JS real,
renderizada dentro de un WebView embebido en la app de escritorio existente, alcanzando el nivel de
comportamiento y pulido visual ya definido y aprobado en SPEC-014 + su addendum §7 (nivel
ChatGPT/Claude/DeepSeek/WorkBuddy), sin arrastrar los 3 bugs de renderizado/composición de Qt que
bloquearon 3 ciclos completos de la implementación en QWidget+QSS (bleed-through de ventana
translúcida, ventana más alta que el área disponible de pantalla, input bar invisible — ninguno
detectado por la suite headless, los 3 solo visibles en prueba manual real). El 100% de la lógica de
negocio (agente, memoria, voz, seguridad, scheduler) permanece en Python; el WebView solo renderiza.

## Alcance
- Incluye:
  - Sidebar colapsable con historial de conversaciones (crear/listar/cargar/eliminar), área de chat
    con burbujas Markdown + resaltado de código, indicador de "escribiendo...", animaciones de
    entrada de mensaje y de transición de tema, input multilínea con atajos e integración de voz,
    dos temas (oscuro/claro) — todo renderizado como HTML/CSS/JS real dentro de un WebView.
  - Reemplazo completo y desde cero del código de `ui/` actualmente committeado (arquitectura de
    REQ-013: `ui/gui.py`, `ui/theme.py`, `ui/widgets/*`) — decisión explícita de Johan: se descarta
    todo, no se parte de ningún shim ni archivo existente de `ui/`.
  - Un mecanismo NUEVO, diseñado desde cero por `orion-architect`, para que `voice/wake_word.py` y
    `ui/stt/transcriber.py` (ambos en la lista de módulos prohibidos de tocar) sigan pudiendo
    reflejar el estado de escucha/wake-word en la nueva UI — sin heredar el shim de `ui/gui.py` de
    REQ-014 (ese código quedó descartado dentro del stash, no se recupera).
  - Bridge Python↔JS (candidatos a evaluar por `orion-architect`: `QWebChannel` si el candidato
    técnico es `QWebEngineView`, o `js_api` si es `pywebview`) estrictamente limitado a disparar
    eventos tipados que Python resuelve — JS nunca ejecuta lógica de negocio ni invoca módulos de
    `core/`, `intent/`, `ai/`, `skills/`, `agents/`, `voice/`, `channels/` fuera de lo que el bridge
    expone explícitamente.
  - Persistencia de conversaciones: se sigue consumiendo la API de `ai/memory_manager.py`
    (`new_conversation_id`, `store_turn`, `list_conversations`, `get_conversation_turns`, ya
    presentes en el working tree actual) sin modificarla. `delete_conversation()` (ausente hoy en
    disco, ver Nota) debe quedar disponible con el mismo comportamiento ya validado en REQ-014
    (`test-results-014.md`, `qa-audit-014.md`) — recuperarla puntualmente del stash o reimplementarla
    es una decisión de `orion-baseline`/`orion-architect`, no de esta SPEC.
  - Framework/librería frontend (HTML/CSS/JS vanilla vs. React/Vue): sin preferencia del humano,
    queda a evaluación técnica de `orion-architect` (mismo criterio que `QWebEngineView` vs
    `pywebview`).
  - Fidelidad visual: mismo brief de REQ-014 confirmado por Johan (jerarquía clara, tipografía
    grande en el saludo vacío, input tipo píldora, paleta restringida a los tokens de la paleta
    oscura/clara ya validados, sin emoji en la interfaz, espaciado generoso) contra las 4 referencias
    (WorkBuddy AI, DeepSeek, ChatGPT, Claude), ahora con CSS real en vez de QSS.
  - Nuevas dependencias necesarias para el candidato técnico elegido (p. ej. `PyQt6-WebEngine` o
    `pywebview`) — a confirmar en arquitectura y agregar a `requirements.txt`.
- No incluye:
  - Panel derecho (`RightPanel`: estado del sistema, accesos rápidos, actividad reciente, clima) —
    **eliminado definitivamente en REQ-014 (addendum §7, confirmado por Johan) y reconfirmado por
    Johan para REQ-015: no se migra ni se reactiva.** Los 5 archivos que lo implementaban en REQ-013
    (`right_panel.py` + 4 tarjetas) se descartan junto con el resto de `ui/widgets/`.
  - Empaquetado como instalable (PyInstaller u otro) — fuera de alcance, igual que REQ-013/REQ-014.
  - Autenticación/soporte multiusuario real — se sigue usando `user_id="default"`.
  - Sincronización de historial entre canales (Telegram/Discord) — el historial funcional sigue
    siendo exclusivo del canal DESKTOP.
  - Activar como funcionales los ítems del sidebar hoy deshabilitados salvo "Conversaciones"
    (Memoria, Tareas, Archivos, Aplicaciones, Configuración siguen como placeholders).
  - Cualquier modificación a `core/`, `intent/`, `ai/` (salvo `delete_conversation()`, ver Alcance),
    `skills/`, `agents/`, `voice/`, `channels/`.

## Módulos afectados
- `ui/gui.py`, `ui/theme.py`, `ui/widgets/{center_panel, chat_bubble, chat_feed, composer,
  conversation_list, header_bar, right_panel, system_status_card, quick_actions_card,
  recent_activity_card, weather_card, voice_orb, sidebar}.py` — **arquitectura de REQ-013
  actualmente committeada en `eb190b3`**; se elimina por completo (`git rm` de contenido trackeado,
  no un simple descarte de working tree — mismo criterio que aplicó SPEC-014 en su momento) y se
  reemplaza por la arquitectura nueva basada en WebView que defina `orion-architect`.
- `ui/` — arquitectura de archivos completamente nueva a proponer por `orion-architect` (backend
  Python que sirve/controla el WebView + los assets HTML/CSS/JS del frontend).
- `ai/memory_manager.py` — única modificación autorizada: que `delete_conversation(conversation_id,
  user_id="default")` esté disponible con el comportamiento ya validado en REQ-014 (DELETE real,
  restringido por `user_id`, no lanza sobre conversación inexistente). El resto de la API
  (`new_conversation_id`, `store_turn`, `list_conversations`, `get_conversation_turns`) se consume
  sin tocar.
- `voice/wake_word.py`, `ui/stt/transcriber.py` — **no se modifican** (prohibido); `orion-architect`
  diseña desde cero cómo la nueva UI refleja su estado sin ellos saber que la UI cambió de
  tecnología.
- `config_manager.py` — se reutilizan `get_ui_theme()`/`set_ui_theme()` ya existentes, sin modificar
  salvo necesidad puntual justificada en arquitectura.
- `main.py` — candidato a tocar para instanciar el WebView en vez de `JarvisMainWindow`/widgets
  QWidget (equivalente al cambio ya hecho en REQ-014, ahora sobre destino WebView).
- `requirements.txt` — se agrega la dependencia del candidato técnico elegido (`PyQt6-WebEngine` o
  `pywebview`), y `markdown`/`Pygments` si el resaltado de código se resuelve server-side (a decidir
  en arquitectura).
- Tests: se reescriben para la arquitectura nueva — estructura exacta a definir en `orion-architect`.
  El patrón de `PYTEST_QT_API=pyqt6` en `tests/conftest.py` (mitigación de un riesgo de entorno de
  REQ-014, ver `baseline-014.md`) sigue vigente si el candidato elegido sigue usando `pytest-qt`.

## Comportamiento actual vs deseado
| Actual (arquitectura de REQ-013, committeada en `eb190b3`, verificado en disco) | Deseado (REQ-015) |
|---|---|
| `QWidget` + QSS puro, ventana `QMainWindow` estándar | Contenido renderizado en HTML/CSS/JS real dentro de un WebView embebido |
| Tema oscuro por defecto | Tema claro por defecto (ya validado y aprobado en REQ-014 addendum §7) |
| Panel derecho presente (`RightPanel` + 4 tarjetas) | Panel derecho ausente — eliminado definitivamente, no se migra |
| Sin `delete_conversation()` en `ai/memory_manager.py` | `delete_conversation()` disponible con el comportamiento ya validado en REQ-014 |
| Sidebar de navegación (`ui/widgets/sidebar.py`) sin historial de conversaciones colapsable | Sidebar colapsable 260px↔60px con historial funcional (crear/listar/cargar/eliminar) |
| Burbujas (`chat_bubble.py`) sin Markdown completo ni resaltado de código | Burbujas con Markdown completo + resaltado de código + tablas |
| Sin indicador de "escribiendo..." | Indicador animado mientras se espera la respuesta de la IA |
| Sin animaciones de entrada de mensaje ni transición de tema | Fade-in + slide-up ~300ms por mensaje, transición de tema suave — vía CSS/JS |
| Avatar/greeting sin el refinamiento visual de REQ-014 (tipografía chica, posible emoji) | Saludo con tipografía grande (~40px/700), avatar con inicial del agente, sin emoji |
| Input `QTextEdit` básico | Input tipo píldora, multilínea expandible, Enter/Shift+Enter, adjuntar/voz/enviar, drag&drop |
| 3 bugs de composición/tamaño de Qt bloquearon 3 ciclos de QA manual en REQ-014 (nunca detectados por la suite headless) | Los 3 comportamientos correspondientes quedan como criterios de no-regresión explícitos (CA-03/04/05) verificables en la app real |

## Criterios de aceptación

### Ventana / shell de la app
- [ ] CA-01: La app se presenta sin marco nativo del sistema operativo, con esquinas redondeadas y
      controles propios de minimizar/maximizar/cerrar — el mecanismo concreto (ventana Qt frameless
      con el WebView embebido como contenido central, o ventana propia del WebView) es decisión
      técnica de `orion-architect`, no de esta SPEC.
- [ ] CA-02: La ventana es redimensionable desde sus 4 bordes/esquinas y movible desde su barra de
      título.
- [ ] CA-03 (no-regresión bug #1 — bleed-through): En ningún tema ni estado, la ventana muestra
      contenido del escritorio detrás de sí ni texto superpuesto sin fondo pintado — verificado con
      inspección visual real en Windows (no solo con la suite headless, que en REQ-014 pasó 100% con
      este bug presente).
- [ ] CA-04 (no-regresión bug #2 — tamaño de ventana): Al abrir, la ventana nunca excede el área de
      trabajo disponible de la pantalla (excluyendo la barra de tareas de Windows), en ninguna
      resolución o porcentaje de escalado — el input bar queda siempre dentro del área clickeable.
- [ ] CA-05 (no-regresión bug #3 — input invisible): El campo de texto del input bar es siempre
      visualmente identificable (borde, fondo y placeholder visibles) en ambos temas — nunca aparece
      como un espacio vacío sin indicios de ser un campo de texto.

### Sidebar
- [ ] CA-06: El sidebar mide 260px expandido, colapsa a 60px, y el colapso/expansión anima
      suavemente (implementado con CSS/JS, no `QPropertyAnimation`).
- [ ] CA-07: Existe un control "+ Nuevo chat" que crea un `conversation_id` nuevo y limpia el chat
      activo, sin borrar conversaciones anteriores.
- [ ] CA-08: Cada ítem del listado muestra título (primeros 30 caracteres del primer mensaje), fecha
      relativa, y un control de eliminar visible en hover.
- [ ] CA-09: Click en una conversación carga sus turnos completos (usuario + IA) en el área de chat y
      la marca como activa.
- [ ] CA-10: El control de eliminar borra la conversación (vía `delete_conversation()`) tras una
      confirmación que evite borrados accidentales; desaparece del listado sin afectar las demás.
- [ ] CA-11: El listado de conversaciones limita/pagina resultados (no una consulta sin límite) para
      no degradar el arranque de la app con cientos de conversaciones históricas.

### Chat area — burbujas, Markdown, código
- [ ] CA-12: Mensajes de usuario y de IA son visualmente distinguibles entre sí (posición, avatar,
      estilo).
- [ ] CA-13: Las respuestas de la IA renderizan Markdown completo: negritas, cursivas, listas,
      bloques de código con resaltado de sintaxis, y tablas — mecanismo de resaltado (server-side con
      Pygments o client-side con una librería JS) a decisión de `orion-architect`.
- [ ] CA-14: Los mensajes de sistema se muestran centrados y visualmente distintos de las burbujas
      usuario/IA.
- [ ] CA-15: Existe un indicador de "escribiendo..." mientras se espera la respuesta de la IA, que
      desaparece al recibirla o si la resolución falla.
- [ ] CA-16: El área de chat autoscrollea al último mensaje al recibir uno nuevo, salvo que el
      usuario esté a más de ~40px del fondo (no le interrumpe la lectura).
- [ ] CA-17: El historial de una conversación carga en lotes de 50 mensajes (carga diferida), no
      todos de una vez.
- [ ] CA-18: Un mensaje de más de 500 caracteres se muestra colapsado con un control "Ver más" que lo
      expande.
- [ ] CA-19: Cada mensaje persistido respeta la estructura `{id, conversation_id, role, content,
      timestamp, metadata}` (sin cambios respecto al esquema ya existente).

### Input bar + voz
- [ ] CA-20: El input es multilínea, con forma de píldora, y se expande hasta 5 líneas visibles antes
      de scrollear internamente (elemento HTML — `textarea`/`contenteditable` u otro, a decisión de
      arquitectura).
- [ ] CA-21: Enter envía el mensaje; Shift+Enter inserta una nueva línea sin enviar.
- [ ] CA-22: Existen controles de adjuntar archivo, activar voz (STT) y enviar en el input bar.
- [ ] CA-23: El input bar acepta archivos por drag & drop.
- [ ] CA-24: El input (y el control de enviar) se deshabilita con feedback visual mientras se resuelve
      un comando, impidiendo el envío concurrente de un segundo mensaje antes de que el primero
      resuelva (no-regresión de la condición de carrera documentada en `qa-audit-013.md`).
- [ ] CA-25: El control de voz activa/desactiva STT consumiendo únicamente la API pública ya
      existente de `voice/`, sin modificar nada dentro de `voice/`.

### Persistencia de conversaciones (`ai/memory_manager.py` — excepción acotada)
- [ ] CA-26: El envío de un mensaje persiste el turno completo mediante `store_turn()` ya existente,
      sin modificarla.
- [ ] CA-27: El listado del sidebar usa `list_conversations()` ya existente, sin modificarla.
- [ ] CA-28: La carga de una conversación usa `get_conversation_turns()` ya existente, sin
      modificarla.
- [ ] CA-29: "Nueva conversación" usa `new_conversation_id()` ya existente, sin modificarla.
- [ ] CA-30: Ninguna función ni el esquema de `ai/memory_manager.py` se modifica en este REQ, salvo
      lo indicado en CA-31.
- [ ] CA-31: `delete_conversation(conversation_id, user_id="default")` está disponible en
      `ai/memory_manager.py` con el mismo comportamiento ya validado en REQ-014: DELETE real,
      restringida por `user_id` (no permite borrar conversaciones de otro usuario), no lanza
      excepción sobre una conversación inexistente o ya borrada (retorna `False`).

### Animaciones
- [ ] CA-32: Los mensajes nuevos entran con una animación de fade-in + slide-up de ~300ms,
      implementada con CSS/JS (transiciones/animaciones web) — no con `QPropertyAnimation` ni
      ninguna clase de Qt.
- [ ] CA-33: El cambio de tema se aplica con una transición visual suave, sin parpadeo/flash
      instantáneo.
- [ ] CA-34: Los elementos interactivos (botones, ítems de sidebar, chips) tienen transición de hover
      suave.

### Temas claro/oscuro
- [ ] CA-35: Existen dos paletas completas (oscura y clara), partiendo de los hex ya validados en
      REQ-014 (ver `REQ-014-context.md`) como punto de partida.
- [ ] CA-36: Todo par texto/fondo usado en la UI cumple contraste WCAG AA (≥4.5:1 texto normal,
      ≥3.0:1 texto grande), verificado con un test de contraste automatizado.
- [ ] CA-37: El cambio de tema se aplica en caliente a toda la ventana sin reiniciar la app.
- [ ] CA-38: El tema por defecto es el claro (ya validado en REQ-014 addendum §7) y la preferencia
      persiste entre reinicios, reutilizando `config_manager.get_ui_theme()`/`set_ui_theme()` ya
      existentes.

### Chips + seguridad — reflejo visual de niveles verde/amarillo/rojo
- [ ] CA-39: Los chips sobre el input bar mantienen el mismo contenido aprobado en REQ-013/REQ-014
      ("Resumen del día", "Recuérdame algo", "Investigación rápida" como plantillas; "Captura de
      pantalla", "Abrir navegador" como accesos directos) y el mismo mecanismo: los accesos directos
      pasan por `run_async(execute_action, ..., channel=ChannelType.DESKTOP)`, nunca invocan la
      acción directo ni desde JS.
- [ ] CA-40: Existe un componente visual (color/ícono) que representa los 3 niveles de
      `.claude/rules/security-levels.md`, aplicado como mínimo a los chips de acceso directo del
      input bar.
- [ ] CA-41: Ninguna acción amarilla o roja disparada desde la UI se ejecuta sin pasar por
      `security_manager.require_confirmation()` — ni JS ni el bridge Python auto-confirman ni
      bypassean el gate (no-regresión del patrón ya validado en REQ-013/REQ-014).
- [ ] CA-42: El bridge Python↔JS solo expone comandos/eventos específicos y tipados hacia Python —
      JS no puede ejecutar código Python arbitrario ni invocar directamente módulos de `core/`,
      `intent/`, `ai/`, `skills/`, `agents/`, `voice/`, `channels/` fuera de lo que el bridge expone
      explícitamente.

### Integración con la infraestructura existente
- [ ] CA-43: La app conserva un ícono de bandeja del sistema (tray) funcional.
- [ ] CA-44: El modo manos libres (wake word) sigue funcionando — `voice/wake_word.py` y
      `ui/stt/transcriber.py` no se modifican; la nueva UI refleja su estado mediante un mecanismo
      diseñado desde cero por `orion-architect`.
- [ ] CA-45: El autostart de Windows (REQ-011) sigue funcionando sin cambios de comportamiento.

### Fidelidad visual (verificación cualitativa)
- [ ] CA-46: La interfaz sigue el brief visual ya aprobado en REQ-014 (jerarquía clara, tipografía
      grande en el saludo vacío, input tipo píldora, paleta restringida a los tokens definidos, sin
      emoji en la interfaz — avatar con inicial del agente —, espaciado generoso), verificado por
      inspección visual del humano contra las 4 referencias (WorkBuddy AI, DeepSeek, ChatGPT,
      Claude).

### Regresión
- [ ] CA-47: `python -m py_compile` sobre todos los módulos Python nuevos/modificados no arroja
      errores.
- [ ] CA-48: La suite de tests completa sigue pasando (el conteo exacto de baseline lo documenta
      `orion-baseline`); cualquier cambio de contrato en un test existente se documenta
      explícitamente con el motivo.

## Casos borde
- Doble click rápido en "+ Nuevo chat" no crea conversaciones huérfanas vacías duplicadas.
- Eliminar la conversación actualmente activa: el chat area queda en un estado consistente (p. ej.
  pasa a una conversación nueva vacía), nunca mostrando una conversación que ya no existe.
- Cambio de tema mientras el input está deshabilitado (resolución en curso) no interrumpe la
  resolución en curso.
- Historial con cientos de conversaciones: el sidebar pagina/limita (CA-11) sin bloquear el arranque
  de la app.
- Filas legacy o de otros canales (CLI/voz, `conversation_id IS NULL`) en `memories` no rompen el
  listado ni aparecen mezcladas de forma inconsistente.
- Reinicio de la app en medio de una conversación: arranca con una conversación nueva vacía; la
  anterior sigue accesible desde el sidebar.
- Redimensionar la ventana no rompe el layout de sidebar/chat/input.
- Archivo droppeado en el input bar de un tipo no soportado: se rechaza con feedback claro, no
  silenciosamente.
- Borrar una conversación que no existe (ya borrada, doble click en el control eliminar) no lanza una
  excepción no controlada.
- El WebView falla al cargar (asset faltante, error de JS no capturado): la app no crashea por
  completo — degrada con un mensaje de error visible o un mecanismo de recuperación, a definir en
  arquitectura.
- Un mensaje malformado o inesperado llegando por el bridge JS→Python no ejecuta nada no autorizado
  ni tumba el proceso Python — se valida y descarta con logging.
- La app corre en una pantalla con escalado de Windows distinto de 100% (el mismo tipo de escenario
  que causó el bug #2 de REQ-014): el layout y el tamaño de ventana siguen siendo correctos.

## Asumidos
- ASUMIDO: el candidato técnico (`QWebEngineView` vs `pywebview`) lo evalúa y decide
  `orion-architect`, con los trade-offs ya documentados en el mensaje original (tamaño de
  dependencia, integración con `QMainWindow`/tray/autostart/`QThread` de voz existentes).
- ASUMIDO: el framework/librería frontend (vanilla HTML/CSS/JS vs. React/Vue) también queda a
  criterio técnico de `orion-architect` — sin preferencia previa del humano.
- ASUMIDO: el mecanismo de resaltado de código (Pygments server-side vs. librería JS client-side)
  se decide en arquitectura, siempre que el resultado visual cumpla CA-13.
- ASUMIDO: `delete_conversation()` se recupera puntualmente del stash (`stash@{0}` de la rama
  `feature/REQ-014-rediseno-ui-escritorio`, disponible completo) o se reimplementa desde cero — en
  cualquier caso el comportamiento final debe ser idéntico al ya validado en
  `test-results-014.md`/`qa-audit-014.md`; decisión de `orion-baseline`/`orion-architect`.
- ASUMIDO: el footer del sidebar (configuración/perfil) sigue como placeholder si no se detalla más
  — heredado de SPEC-014 (ASUMIDO original, sin cambios).
- ASUMIDO: la rama de trabajo es `feature/REQ-015-webview-ui`, confirmada y ya creada por Johan desde
  el mismo punto que `main` (sin divergencia de historia — la rama de REQ-014 nunca tuvo commits
  propios).
- ASUMIDO: los templates de código ilustrativos que el humano compartió en REQ-014 (`main_window.py`,
  `sidebar.py`, `message_bubble.py`, `markdown_renderer.py`, `input_bar.py`, `dark.qss`) eran
  específicos de la implementación en QWidget/QSS y no aplican como referencia de código para
  REQ-015 (tecnología distinta) — sirven, si acaso, como referencia del nivel de detalle esperado en
  el diseño, no como código a portar.
