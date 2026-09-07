# SPEC-026 — Modos estratégicos en la barra del composer

**Estado:** ⏸️ ESPERANDO VALIDACIÓN
**Categoría:** UI
**Tipo:** FEATURE_NUEVA
**Fecha:** 2026-09-07

## Objetivo
Reemplazar la fila principal de chips del composer por 4 "modos" (Código/script,
Investigación, Nodos/flujos, Tareas) que, mientras están activos, especializan el chat:
priorizan la capacidad existente correspondiente (`code_execution_skill`,
`web_browsing_skill`/`info_skill`, `flow_skill`, tools de `tasks/task_manager.py`) y pueden
fijar el modelo/proveedor vía el mecanismo de `tarea=` ya existente
(`ai/llm_provider.py::generate_response()` + `task_providers` de `config.json`), con un
rediseño visual de la barra que hoy es una simple fila de botones de texto.

## Alcance
- Incluye:
  - Un nuevo catálogo de 4 modos (reemplaza `ui/webview/bridge.py::_CHIPS` como fuente de la
    fila principal).
  - Estado de modo activo por conversación (toggle/pestaña), con indicación visual clara.
  - Ruteo del turno en curso: mientras un modo está activo, el turno prioriza la
    skill/capacidad asociada y puede fijar `tarea=` para el ruteo de modelo (reutilizando
    `task_providers`, sin crear un mecanismo de ruteo paralelo).
  - Conservar como accesos rápidos, fuera de la fila de modos: "📷 Captura de pantalla",
    "🌐 Abrir navegador" y "Recuérdame algo".
  - Descartar el chip "Resumen del día".
  - Rediseño visual de la barra completa (modos + accesos rápidos conservados).
- No incluye:
  - Ampliar `tasks/task_manager.py` (confirmado por Johan: alcanza tal cual).
  - Crear nuevas skills o tools — los 4 modos se apoyan en capacidades ya existentes.
  - Cambios al mecanismo de `task_providers`/`generate_response()` en sí — se reutiliza,
    no se rediseña.
  - Persistencia del modo activo entre conversaciones distintas o reinicios de la app (queda
    fuera de v1 salvo que orion-architect determine que es trivial de incluir; si no, se
    resetea a "sin modo" en cada conversación nueva).

## Módulos afectados
- `ui/webview/bridge.py` — `_CHIPS` se reemplaza por un catálogo `_MODES` (4 modos) +
  `_QUICK_ACTIONS` (3 accesos sueltos: captura, navegador, recuérdame algo).
  `_build_chips_payload()`/`chips_loaded` deben emitir ambos catálogos (o dos señales) al
  frontend. `send_message()` debe threadear el modo activo hacia `core/resolution.py::resolve()`.
  `_build_models_payload()` debe reflejar cuándo el modelo está "fijado" por el modo activo
  (mismo patrón que `fijado_por_tarea` de REQ-022, CA-01/CA-02/CA-05).
- `ui/webview/frontend/js/composer.js` — `renderChips()` se separa en render de modos
  (toggle, estado activo persistente) y render de accesos rápidos (comportamiento actual sin
  cambios). Debe existir estado de "modo activo" en el frontend y comunicarlo en cada
  `send_message()`.
- `ui/webview/frontend/js/bridge_client.js` — `onChipsLoaded()` (o su reemplazo) debe cubrir
  el nuevo payload de modos + accesos rápidos.
- `ui/webview/frontend/index.html` — el contenedor `#chips-row` pasa a alojar (o se divide
  en) la fila de modos y la fila/grupo de accesos rápidos.
- `ui/webview/frontend/css/composer.css` — rediseño visual: reglas nuevas para el estado
  "modo activo" (toggle resaltado) y separación visual entre modos y accesos rápidos.
- `core/resolution.py` — `resolve()` es el punto único de resolución (CA-01 de REQ-005); debe
  aceptar el modo activo y usarlo para priorizar el resolver/skill correspondiente dentro de
  `RESOLVERS` cuando hay un modo activo.
- `core/reasoning_loop.py` — `run()` hoy llama a `generate_response(..., tarea="razonamiento")`
  fijo; debe poder recibir y propagar una `tarea` derivada del modo activo.
- `config.json` (`task_providers`) — puede requerir nuevas claves de tarea (una por modo que
  fije modelo) documentadas, sin tocar el motor de `ai/llm_provider.py`.
- `agents/tool_registry.py` — sin cambios de capacidad (las tools de tareas ya existen), pero
  puede necesitar ajuste de cómo se prioriza/filtra el catálogo ofrecido al modelo cuando el
  modo "Tareas" está activo.

La solución técnica exacta (dónde vive el catálogo de modos, cómo se prioriza el resolver, cómo
se propaga el parámetro modo/tarea capa por capa) la define `orion-architect` — esta SPEC fija
el comportamiento observable y los criterios de aceptación, no el diseño.

## Comportamiento actual vs deseado
| Actual | Deseado |
|--------|---------|
| Fila `#chips-row` con 5 chips: 3 "template" (prellenan texto) + 2 "action" (ejecutan acción fija) | Fila con 4 modos (Código/script, Investigación, Nodos/flujos, Tareas) + 3 accesos rápidos sueltos (captura, navegador, recuérdame algo) |
| Click en chip "template" prellena el input; click en chip "action" ejecuta y no deja rastro de estado | Click en un modo lo activa (toggle) y queda resaltado hasta que el usuario lo desactiva o cambia de modo; los accesos rápidos siguen comportándose como antes |
| Todo turno de chat usa `tarea="razonamiento"` fijo en `reasoning_loop.run()` | Con un modo activo, el turno puede usar una `tarea` distinta (ruteo de modelo vía `task_providers`) y prioriza la skill asociada al modo |
| El selector de modelo del composer solo se deshabilita si "razonamiento" está fijado en `task_providers` | El selector también se deshabilita/reflejaba como "fijado" cuando el modo activo fija su propia `tarea`, con el mismo tratamiento visual que REQ-022 (CA-01/CA-02) |
| Chip "Resumen del día" disponible | Descartado, sin reemplazo |

## Criterios de aceptación

**Catálogo y convivencia (pregunta 1)**
- [ ] La fila principal del composer muestra exactamente 4 modos: Código/script,
  Investigación, Nodos/flujos, Tareas.
- [ ] "📷 Captura de pantalla" y "🌐 Abrir navegador" siguen disponibles como accesos rápidos
  fuera de la fila de modos, y su comportamiento (ejecución directa vía `run_chip_action()`)
  no cambia.
- [ ] "Recuérdame algo" sigue disponible como acceso rápido suelto (prellena el input, mismo
  comportamiento `kind="template"` actual).
- [ ] "Resumen del día" ya no aparece en ningún lugar del composer.
- [ ] "Investigación rápida" ya no existe como chip suelto — su función queda cubierta por el
  modo Investigación.

**Persistencia y estado visual del modo (pregunta 2)**
- [ ] Click en un modo inactivo lo activa; queda visualmente resaltado (no solo hover/focus).
- [ ] El modo activo permanece activo a través de múltiples mensajes enviados, sin
  desactivarse solo, hasta que el usuario lo desactive.
- [ ] Click sobre el modo ya activo lo desactiva (vuelve a "sin modo").
- [ ] Click sobre un modo distinto mientras hay uno activo cambia el modo activo al nuevo
  (nunca quedan dos modos activos a la vez).
- [ ] El estado de modo activo es por conversación: al cambiar a otra conversación o crear una
  nueva, no arrastra el modo que estaba activo en la anterior (arranca en "sin modo").
- [ ] Un mensaje enviado sin ningún modo activo se comporta exactamente igual que hoy (sin
  regresión del camino sin modo).

**Modo Tareas (pregunta 3)**
- [ ] Con el modo Tareas activo, un pedido de crear/listar/completar una tarea usa las tools
  existentes de `tasks/task_manager.py` (vía `agents/tool_registry.py`) sin necesitar
  ampliación de ese módulo.
- [ ] `tasks/task_manager.py` no recibe cambios de funcionalidad en este REQ (solo, si hace
  falta, cambios de cómo se prioriza su exposición al modelo).

**Ruteo de modelo por modo (pregunta 4)**
- [ ] Cada uno de los 4 modos puede declarar (opcionalmente) una `tarea` propia que, al estar
  ese modo activo, se usa en el llamado a `generate_response()` en lugar de
  `tarea="razonamiento"`.
- [ ] Si `task_providers` en `config.json` tiene un destino fijado para la `tarea` del modo
  activo, el selector de modelo del composer se muestra deshabilitado con la misma etiqueta
  informativa que usa hoy `fijado_por_tarea` (REQ-022, CA-01/CA-02) — no se permite elegir un
  modelo manual que el modo va a pisar igual.
- [ ] Si el usuario tenía un modelo elegido a mano ANTES de activar un modo cuya `tarea` está
  fijada en `task_providers`, al activar el modo el destino fijado por el modo gana (mismo
  criterio que REQ-022 ya aplica hoy entre selección manual y `tarea` fijada) — la SPEC define
  este comportamiento explícitamente para que no quede ambigüedad en implementación.
- [ ] Si la `tarea` del modo activo NO tiene destino fijado en `task_providers`, el selector de
  modelo se comporta igual que hoy sin modo (elegible, sin deshabilitar).
- [ ] Desactivar el modo restaura el comportamiento de ruteo/selector de modelo al estado
  previo a activarlo (sin modo = `tarea="razonamiento"`).

**Rediseño visual (pedido explícito de Johan)**
- [ ] La barra rediseñada usa los tokens de color/tipografía ya definidos en
  `ui/webview/frontend/css/theme.css` (sin introducir un sistema de estilos paralelo) y se ve
  correctamente en tema claro y oscuro.
- [ ] El estado "modo activo" es distinguible sin depender solo de color (contraste AA,
  también forma/ícono) — verificable por `orion-ui`.

## Casos borde
- Enviar un mensaje con un modo activo pero cuyo contenido no tiene nada que ver con esa
  capacidad (p. ej. modo Código activo, usuario pregunta la hora): el modo prioriza la skill/
  tarea pero no debe bloquear una respuesta normal si el modelo decide que no hace falta usar
  esa capacidad.
- Cancelar un turno (botón detener) con un modo activo: el modo activo no se desactiva por
  cancelar el turno.
- Adjuntar un archivo con un modo activo: el adjunto (`_con_adjunto()`) sigue viajando igual,
  el modo no lo pisa ni lo consume.
- `task_providers` mal configurado o ausente para la `tarea` de un modo: debe comportarse
  igual que hoy para "razonamiento" sin fijar (nunca romper el turno por config ausente).
- Cambiar de modo a mitad de una respuesta en streaming: el turno en curso no cambia de
  `tarea` a mitad de camino; el nuevo modo aplica desde el próximo mensaje.

## Asumidos
- ASUMIDO: cada uno de los 4 modos declara una skill/capacidad principal 1:1 (Código →
  `code_execution_skill`, Investigación → `web_browsing_skill`/`info_skill`, Nodos/flujos →
  `flow_skill`, Tareas → tools de `task_manager.py`) — confirmar con orion-architect que no
  hace falta un mapeo más fino (p. ej. Investigación repartida entre dos skills según el
  pedido).
- ASUMIDO: "priorizar" la skill/capacidad del modo activo significa influir el orden/selección
  dentro de `core/resolution.py::RESOLVERS` y/o el system prompt y catálogo de tools de
  `reasoning_loop.py`, nunca bloquear otras capacidades — el usuario puede seguir pidiendo algo
  fuera del modo y debe ser atendido. Confirmar con orion-architect el mecanismo exacto.
- ASUMIDO: no fijar `tarea` es una opción válida por modo (un modo puede priorizar solo skill/
  prompt sin rutear modelo) — a definir por modo en la arquitectura, no necesariamente los 4
  modos fijan `tarea`.
- ASUMIDO: el estado de modo activo vive en el frontend (JS) y viaja en cada `send_message()`
  hacia Python — no se persiste en `agent_context` ni en DB. Confirmar con orion-architect.
