# SPEC-014 — Rediseño completo desde cero UI escritorio NODDOO (nivel ChatGPT/Claude/DeepSeek/WorkBuddy)

**Estado:** ✅ COMPLETADO — Aprobado por Johan (2026-08-18), tal cual, sin ajustes (incluidos los 7
puntos marcados ASUMIDO: `delete_conversation()` queda como DELETE real; `voice_orb.py` y el
alcance del footer del sidebar quedan a decisión de `orion-architect`)
**Categoría:** UI
**Tipo:** FEATURE_NUEVA
**Fecha:** 2026-08-18

## Nota para el humano — el punto de partida NO es un baseline limpio
Verificado con `git log`/`git show` (confirmado independientemente por el humano): el commit
actual de `main` (`eb190b3`, "Fix mejora interfaz visual Agente IA") **ya contiene la 1ra pasada
completa de REQ-013 committeada**, no solo resguardada en el stash. Esto incluye `ui/theme.py`,
`ui/widgets/chat_bubble.py`, `chat_feed.py`, `conversation_list.py`, los cambios de `ui/gui.py`,
`center_panel.py`, `composer.py`, `header_bar.py`, y el esquema de `ai/memory_manager.py`
(`conversation_id`/`role`, `new_conversation_id()`, `store_turn()`, `list_conversations()`,
`get_conversation_turns()`). El `stash@{0}` solo contiene los refinamientos de la 2da-3ra pasada
(fixes de contraste CA-03, fix de condición de carrera del composer) y las actualizaciones de los
docs de `workspace/adjuntos/REQ-013/`.

Decisión explícita del humano (2026-08-18), pese a saber que ese código ya está en `main` y
testeado (308 tests): **se reemplaza por completo**. `orion-dev` no parte de un working tree
sucio ni de un simple descarte de cambios sin commitear — el reemplazo requiere reescribir/borrar
contenido ya trackeado en git (`git rm` de los archivos descartados + archivos nuevos), y el
mensaje de commit final de REQ-014 debe documentar explícitamente qué se borró y qué se creó.
`orion-baseline` debe reflejar esto con precisión en su documentación de estado actual.

La excepción a la restricción de no tocar `ai/` (ver "Alcance") queda MÁS ACOTADA de lo que
parecía inicialmente: como el esquema y las 4 funciones de historial ya están committeadas, la
única modificación nueva autorizada en `ai/memory_manager.py` es agregar `delete_conversation()`
(ver CA-30).

## Objetivo
Reconstruir por completo la interfaz de escritorio de NODDOO (PyQt6) con una arquitectura de
archivos nueva y distinta a la usada por REQ-013, alcanzando calidad visual y de interacción de
nivel ChatGPT/Claude/DeepSeek/WorkBuddy: ventana frameless con esquinas redondeadas, sidebar
colapsable con historial de conversaciones funcional (incluyendo borrado), área de chat con
burbujas Markdown + resaltado de código, indicador de "escribiendo...", animaciones de entrada de
mensajes y de transición de tema, input multilínea con atajos e integración de voz, y reflejo
visual de los niveles de seguridad verde/amarillo/rojo — sin modificar `core/`, `intent/`, `ai/`
(salvo la excepción puntual de CA-30), `skills/`, `agents/`, `voice/`, `channels/`.

## Alcance
- Incluye:
  - Ventana principal frameless (`FramelessWindowHint` + `WA_TranslucentBackground`), esquinas
    redondeadas 12px, barra de título propia (minimizar/maximizar/cerrar), resize desde bordes.
  - Sidebar colapsable (260px ↔ 60px): logo, botón "+ Nuevo chat", listado de conversaciones
    (título + fecha relativa + eliminar en hover), footer de configuración/perfil.
  - Área de chat: burbujas usuario (derecha, bordes 18px) / IA (izquierda, con avatar), Markdown
    completo con resaltado de código (Pygments), tablas, mensajes de sistema centrados, indicador
    de "escribiendo..." (3 puntos animados), scroll suave con autoscroll condicional, carga
    diferida en lotes de 50 mensajes, colapsar mensajes largos (>500 caracteres) con "Ver más".
  - Input bar: `QTextEdit` multilínea expandible hasta 5 líneas, Enter=enviar/Shift+Enter=nueva
    línea, botones adjuntar/voz/enviar, drag&drop de archivos, deshabilitado con feedback visual
    mientras se resuelve un comando (no-regresión de la condición de carrera de REQ-013).
  - Integración de voz en el input bar: **solo consumo** de la API pública ya existente de
    `voice/` (STT/TTS) — cero modificaciones dentro de `voice/`.
  - Persistencia de conversaciones: se **consume** la API ya existente y committeada de
    `ai/memory_manager.py` (`new_conversation_id`, `store_turn`, `list_conversations`,
    `get_conversation_turns`) sin modificarla, y se agrega **una única función nueva**,
    `delete_conversation()`, para soportar el borrado desde el sidebar.
  - Animaciones: entrada de mensaje fade-in + slide-up 300ms (`QPropertyAnimation` +
    `QEasingCurve.Type.OutCubic`), transición suave de tema, hover suave, colapso/expansión de
    sidebar en 200ms.
  - Dos paletas (oscura/clara) nuevas, partiendo de los hex entregados por el humano (ver
    contexto), verificadas contra contraste WCAG AA.
  - Reflejo visual de los niveles de seguridad verde/amarillo/rojo (`.claude/rules/
    security-levels.md`) en las acciones disparadas desde la UI (chips).
  - Nueva arquitectura de archivos en `ui/`: `main_window.py`, `sidebar.py`, `chat_area.py`,
    `input_bar.py`, `message_bubble.py`, `typing_indicator.py`, `theme.py`, `animations.py`,
    `components/{avatar.py, code_block.py, markdown_renderer.py, search_bar.py}`,
    `styles/{base.qss, dark.qss, light.qss}`, `workers.py` — nombres/división propuestos por el
    humano, punto de partida no cerrado, a confirmar/ajustar en `orion-architect`.
  - Conservación del panel derecho (`RightPanel`: estado del sistema, accesos rápidos, actividad
    reciente, clima) y de los chips de plantillas/accesos directos sobre el input bar, con el
    mismo contenido/mecanismo ya aprobado en REQ-013, re-vestidos visualmente para el nuevo estilo.
  - Nuevas dependencias: `markdown`, `Pygments` (agregadas a `requirements.txt`).
- No incluye:
  - Empaquetado como instalable (PyInstaller u otro) — fuera de alcance, igual que REQ-013.
  - Autenticación/soporte multiusuario real — se sigue usando `user_id="default"`.
  - Sincronización de historial entre canales (Telegram/Discord) — el historial funcional sigue
    siendo exclusivo del canal DESKTOP.
  - Activar como funcionales los ítems del sidebar hoy deshabilitados salvo "Conversaciones"
    (Memoria, Tareas, Archivos, Aplicaciones, Configuración siguen como placeholders).
  - `qasync` — descartado explícitamente por el humano; se mantiene `QThread`/workers.
  - Cualquier modificación a `core/`, `intent/`, `skills/`, `agents/`, `voice/`, `channels/`.
  - Cualquier modificación a `ai/memory_manager.py` más allá de agregar `delete_conversation()`
    (CA-30/CA-31).

## Módulos afectados
- `ui/gui.py` — **se elimina**, reemplazado por `ui/main_window.py`.
- `ui/theme.py` — **se reescribe por completo** (mismo nombre de archivo, contenido nuevo: nuevas
  paletas y `ThemeManager`); el actual (committeado en `eb190b3`) se descarta.
- `ui/widgets/chat_bubble.py`, `chat_feed.py`, `composer.py`, `center_panel.py`, `header_bar.py`,
  `conversation_list.py` — **se eliminan**, reemplazados por los nuevos `ui/chat_area.py`,
  `ui/input_bar.py`, `ui/message_bubble.py`, `ui/typing_indicator.py`, `ui/sidebar.py` (división
  exacta a confirmar en `orion-architect`).
- `ui/widgets/right_panel.py`, `system_status_card.py`, `quick_actions_card.py`,
  `recent_activity_card.py`, `weather_card.py` — **se conservan**, solo ajuste de estilos al nuevo
  QSS/paleta (CA-40).
- `ui/widgets/voice_orb.py` — a definir en `orion-architect` si se conserva (estado vacío, como en
  REQ-013) o se retira; no mencionado en el prompt detallado del humano.
- `ai/memory_manager.py` — **única modificación permitida**: agregar `delete_conversation()`
  (CA-30). Todo lo demás (`new_conversation_id`, `store_turn`, `list_conversations`,
  `get_conversation_turns`, el esquema `conversation_id`/`role`) se consume sin tocar.
- `config_manager.py` — se reutilizan `get_ui_theme()`/`set_ui_theme()` ya existentes, sin
  modificar salvo necesidad puntual justificada en arquitectura.
- `main.py` — no está en la lista de directorios prohibidos; candidato a tocar solo si
  `orion-architect` decide que `_desktop_confirm` (hoy un `input()` de consola bloqueante) necesita
  un mecanismo compatible con la UI para una eventual acción amarilla/roja (ver Asumidos).
- `requirements.txt` — se agregan `markdown`, `Pygments`.
- Tests: se reescriben/crean equivalentes a los que cubrían REQ-013 (`test_gui_widgets.py`,
  `test_chat_widgets.py`, `test_theme.py`, `test_config_manager_ui_theme.py`,
  `test_conversation_memory.py`, `test_wake_word_gui.py`) más tests nuevos para
  `delete_conversation()` y los widgets/animaciones nuevos — estructura exacta a definir en
  `orion-architect` dado el cambio de arquitectura de archivos.

## Comportamiento actual vs deseado
| Actual (ya committeado en `eb190b3`, 1ra pasada REQ-013) | Deseado (REQ-014) |
|---|---|
| Ventana `QMainWindow` con barra de título nativa del SO | Ventana frameless, esquinas redondeadas 12px, barra de título propia, resize desde bordes |
| Sidebar sin colapsar, con `ConversationList` interno | Sidebar colapsable 260px ↔ 60px, listado con fecha relativa y eliminar en hover |
| Sin borrado de conversaciones desde el sidebar | Eliminar conversación vía ícono en hover (`delete_conversation()` nueva) |
| `ChatBubble`/`ChatFeed` sin Markdown completo ni resaltado de código | Burbujas con Markdown completo + resaltado de código (Pygments) + tablas |
| Sin indicador de "escribiendo..." | Indicador de 3 puntos animados mientras se espera respuesta |
| Sin animación de entrada de mensajes | Fade-in + slide-up 300ms por mensaje nuevo |
| Carga completa del historial de la conversación seleccionada | Carga diferida en lotes de 50 mensajes |
| Paleta oscura/clara de REQ-013 (hex ya fijados y testeados) | Paleta nueva (hex de partida del humano, ver contexto), re-verificada contraste WCAG AA |
| Arquitectura: `ui/gui.py` + `ui/widgets/{chat_bubble,chat_feed,composer,conversation_list,center_panel,header_bar}.py` | Arquitectura nueva: `ui/main_window.py`, `sidebar.py`, `chat_area.py`, `input_bar.py`, `message_bubble.py`, `typing_indicator.py`, `theme.py`, `animations.py`, `components/`, `styles/*.qss`, `workers.py` |
| Chips de acceso directo sin indicador visual de nivel de riesgo | Indicador visual verde/amarillo/rojo asociado a las acciones de los chips |
| Panel derecho y chips (contenido REQ-013) | Se conservan igual, re-vestidos visualmente |

## Criterios de aceptación

### Ventana frameless
- [ ] CA-01: La ventana usa `FramelessWindowHint` + `WA_TranslucentBackground`, esquinas
      redondeadas de 12px y borde de 1px con el color `border` de la paleta activa.
- [ ] CA-02: Existe una barra de título propia con minimizar, maximizar/restaurar y cerrar
      funcionales.
- [ ] CA-03: La ventana es redimensionable arrastrando desde cualquiera de sus 4 bordes/esquinas.
- [ ] CA-04: La ventana es movible arrastrando desde la barra de título propia.

### Sidebar
- [ ] CA-05: El sidebar mide 260px expandido, colapsa a 60px, y el colapso/expansión anima en
      200ms.
- [ ] CA-06: Existe un botón "+ Nuevo chat" que crea un `conversation_id` nuevo y limpia el chat
      activo, sin borrar conversaciones anteriores.
- [ ] CA-07: Cada ítem del listado muestra título (primeros 30 caracteres del primer mensaje),
      fecha relativa, y un ícono de eliminar visible en hover.
- [ ] CA-08: Click en una conversación carga sus turnos completos (usuario + IA) en el área de
      chat y la marca como activa.
- [ ] CA-09: El ícono de eliminar borra la conversación (vía `delete_conversation()`) tras una
      confirmación que evite borrados accidentales; desaparece del listado sin afectar las demás.
- [ ] CA-10: El listado de conversaciones limita/pagina resultados (no una consulta sin límite)
      para no degradar el arranque de la app con cientos de conversaciones históricas.

### Chat area — burbujas, Markdown, código
- [ ] CA-11: Mensajes de usuario en burbujas a la derecha (bordes 18px); mensajes de IA a la
      izquierda con avatar — visualmente distinguibles entre sí.
- [ ] CA-12: Las burbujas de IA renderizan Markdown completo: negritas, cursivas, listas, bloques
      de código con resaltado de sintaxis (Pygments), y tablas.
- [ ] CA-13: Los mensajes de sistema se muestran centrados y visualmente distintos de las burbujas
      usuario/IA.
- [ ] CA-14: Existe un indicador de "escribiendo..." (3 puntos animados) mientras se espera la
      respuesta de la IA, que desaparece al recibirla o si la resolución falla.
- [ ] CA-15: El área de chat autoscrollea al último mensaje al recibir uno nuevo, salvo que el
      usuario esté a más de ~40px del fondo (no le arranca la lectura).
- [ ] CA-16: El historial de una conversación carga en lotes de 50 mensajes (carga diferida), no
      todos de una vez.
- [ ] CA-17: Un mensaje de más de 500 caracteres se muestra colapsado con un control "Ver más" que
      lo expande.
- [ ] CA-18: Cada mensaje persistido respeta la estructura `{id, conversation_id, role, content,
      timestamp, metadata}`.

### Input bar + voz
- [ ] CA-19: El input es un `QTextEdit` multilínea que se expande hasta 5 líneas visibles antes de
      scrollear internamente.
- [ ] CA-20: Enter envía el mensaje; Shift+Enter inserta una nueva línea sin enviar.
- [ ] CA-21: Existen botones de adjuntar archivo, activar voz (STT) y enviar en el input bar.
- [ ] CA-22: El input bar acepta archivos por drag & drop.
- [ ] CA-23: El input (y el botón de enviar) se deshabilita con feedback visual mientras se
      resuelve un comando, impidiendo el envío concurrente de un segundo mensaje antes de que el
      primero resuelva (no-regresión de la condición de carrera documentada en
      `qa-audit-013.md`).
- [ ] CA-24: El botón de voz activa/desactiva STT consumiendo únicamente la API pública ya
      existente de `voice/`, sin modificar nada dentro de `voice/`.

### Persistencia de conversaciones (`ai/memory_manager.py` — excepción acotada)
- [ ] CA-25: El envío de un mensaje persiste el turno completo mediante `store_turn()` ya
      existente, sin modificarla.
- [ ] CA-26: El listado del sidebar usa `list_conversations()` ya existente, sin modificarla.
- [ ] CA-27: La carga de una conversación usa `get_conversation_turns()` ya existente, sin
      modificarla.
- [ ] CA-28: "Nueva conversación" usa `new_conversation_id()` ya existente, sin modificarla.
- [ ] CA-29: Ninguna función ni el esquema de `ai/memory_manager.py` se modifica en este REQ,
      salvo lo indicado en CA-30.
- [ ] CA-30: Se agrega `delete_conversation(conversation_id, user_id="default")` (o firma
      equivalente) en `ai/memory_manager.py` — única modificación nueva autorizada a ese archivo —
      que borra de forma segura las filas de esa conversación, restringido por `user_id` (no
      permite borrar conversaciones de otro usuario).

### Animaciones
- [ ] CA-31: Los mensajes nuevos entran con fade-in + slide-up de 300ms
      (`QPropertyAnimation` + `QEasingCurve.Type.OutCubic`).
- [ ] CA-32: El cambio de tema se aplica con una transición visual suave, sin parpadeo/flash
      instantáneo.
- [ ] CA-33: Los elementos interactivos (botones, ítems de sidebar, chips) tienen transición de
      hover suave.

### Temas claro/oscuro
- [ ] CA-34: Existen dos paletas completas (oscura y clara), partiendo de los hex de referencia
      entregados por el humano (ver contexto), ajustadas donde sea necesario para cumplir CA-35.
- [ ] CA-35: Todo par texto/fondo usado en la UI cumple contraste WCAG AA (≥4.5:1 texto normal,
      ≥3.0:1 texto grande), verificado con un test de contraste automatizado (mismo criterio que
      CA-03 de SPEC-013).
- [ ] CA-36: El cambio de tema se aplica en caliente a toda la ventana (sidebar, chat, input,
      panel derecho) sin reiniciar la app.
- [ ] CA-37: La preferencia de tema persiste entre reinicios, reutilizando
      `config_manager.get_ui_theme()`/`set_ui_theme()` ya existentes.

### Panel derecho + chips (se mantienen)
- [ ] CA-38: El panel derecho (estado del sistema, accesos rápidos, actividad reciente, clima) se
      conserva visible coexistiendo con el nuevo layout, con el mismo contenido funcional que hoy.
- [ ] CA-39: Los chips sobre el input bar mantienen el mismo contenido aprobado en REQ-013
      ("Resumen del día", "Recuérdame algo", "Investigación rápida" como plantillas; "Captura de
      pantalla", "Abrir navegador" como accesos directos) y el mismo mecanismo: los accesos
      directos pasan por `run_async(execute_action, ..., channel=ChannelType.DESKTOP)`, nunca
      invocan la acción directo.

### Seguridad — reflejo visual de niveles verde/amarillo/rojo
- [ ] CA-40: Existe un componente visual (color/ícono) que representa los 3 niveles de
      `.claude/rules/security-levels.md`, aplicado como mínimo a los chips de acceso directo del
      input bar.
- [ ] CA-41: Ninguna acción amarilla o roja disparada desde la UI se ejecuta sin pasar por
      `security_manager.require_confirmation()` — la UI nunca auto-confirma ni bypassea el gate
      (no-regresión del patrón validado por CA-19 de SPEC-013).

### Regresión
- [ ] CA-42: `python -m py_compile` sobre todos los módulos nuevos/modificados no arroja errores.
- [ ] CA-43: La suite de tests completa sigue pasando (el conteo exacto de baseline lo documenta
      `orion-baseline`); cualquier cambio de contrato en un test existente se documenta
      explícitamente con el motivo.

## Casos borde
- Doble click rápido en "+ Nuevo chat" no crea conversaciones huérfanas vacías duplicadas.
- Eliminar la conversación actualmente activa: el chat area debe quedar en un estado consistente
  (p. ej. pasar a una conversación nueva vacía), nunca mostrando una conversación que ya no existe.
- Cambio de tema mientras el input está deshabilitado (resolución en curso) no debe interrumpir la
  resolución en curso.
- Historial con cientos de conversaciones: el sidebar pagina/limita (CA-10) sin bloquear el
  arranque de la app.
- Filas legacy o de otros canales (CLI/voz, `conversation_id IS NULL`) en `memories` no rompen el
  listado ni aparecen mezcladas de forma inconsistente — comportamiento ya resuelto por REQ-013,
  no se toca en este REQ.
- Reinicio de la app en medio de una conversación: arranca con una conversación nueva vacía; la
  anterior sigue accesible desde el sidebar.
- Redimensionar la ventana frameless desde una esquina no rompe el layout de sidebar/chat/panel
  derecho.
- Archivo droppeado en el input bar de un tipo no soportado: se rechaza con feedback claro, no
  silenciosamente.
- Borrar una conversación que no existe (ya borrada, doble click en el ícono eliminar) no debe
  lanzar una excepción no controlada.

## Asumidos
- ASUMIDO: la ubicación exacta y el alcance funcional de los botones de configuración/perfil del
  footer del sidebar quedan como placeholder si no se detallan más — a validar en
  `orion-architect`.
- ASUMIDO: los hex de partida entregados por el humano (ver `REQ-014-context.md`) pueden requerir
  ajustes puntuales para cumplir CA-35, igual que ocurrió en REQ-013 (2 hex ajustados);
  `orion-architect`/`orion-dev` documentan cualquier desviación de los valores originales.
- ASUMIDO: el mecanismo de confirmación de UI para una eventual acción amarilla/roja (CA-41) puede
  requerir actualizar el adaptador `_desktop_confirm` de `main.py` (hoy un `input()` de consola
  bloqueante, no viable desde un hilo de Qt) si `orion-architect` decide exponer alguna acción
  no-GREEN desde un chip nuevo — `main.py` no está en la lista de directorios prohibidos. Hoy
  todos los chips heredados de REQ-013 (CA-39) son GREEN, así que esto es una previsión, no un
  requisito activo salvo que arquitectura agregue una acción no-GREEN.
- ASUMIDO: `delete_conversation()` (CA-30) hace un borrado real (DELETE), no soft-delete — a
  confirmar en `orion-architect` si se prefiere soft-delete por recuperación.
- ASUMIDO: la reescritura de los archivos de `ui/` ya committeados en `eb190b3` requiere
  `git rm`/reescritura explícita de contenido trackeado — no un simple descarte de working tree
  sin commitear. El mensaje de commit final de REQ-014 debe documentar qué se borró y qué se creó.
- ASUMIDO: los templates de código ilustrativos compartidos por el humano (main_window.py,
  sidebar.py, message_bubble.py, markdown_renderer.py, input_bar.py, dark.qss) no se transcriben
  literal en esta SPEC — `orion-architect` debe pedirlos de nuevo si necesita el texto exacto para
  diseñar un componente puntual; se usan como referencia de nivel de detalle, no como código a
  copiar.
- ASUMIDO: `ui/widgets/voice_orb.py` — su conservación (como en el estado vacío de REQ-013) o
  retiro se decide en `orion-architect`; no está mencionado en el prompt detallado del humano.
