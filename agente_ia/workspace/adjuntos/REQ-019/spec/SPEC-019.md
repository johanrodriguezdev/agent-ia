# SPEC-019 — Configuración de niveles de seguridad por el usuario (solo subir, nunca bajar)

**Estado:** ✅ COMPLETADO — Aprobado por Johan (2026-08-20), TAL CUAL, sin ajustes (incluidos
todos los puntos marcados ASUMIDO: categoría v1 "Apertura de aplicaciones y navegación", reinicio
requerido para aplicar cambios, persistencia en `config.json`, y el mapeo de nombres que colapsa
claves internas duplicadas en una sola fila de UI)
**Categoría:** SEGURIDAD
**Tipo:** FEATURE_NUEVA
**Fecha:** 2026-08-20

## Nota para el humano — puntos que requieren tu aprobación explícita

Esta SPEC incluye 5 puntos marcados **ASUMIDO** que orion-spec decidió por criterio propio porque
no fuiste consultado puntualmente sobre ellos (o porque expresamente me pediste proponer un
default razonable). Ningún otro punto de esta SPEC es negociable sin pasar de nuevo por acá —
son decisiones tuyas ya tomadas (ver `workspace/adjuntos/REQ-019/REQ-019-context.md`, sección
"Decisiones tomadas"):

- La categoría de acciones para v1 (propuesta abajo, sección "Alcance").
- Si el cambio de nivel requiere reiniciar la app o debe aplicar en caliente.
- El mapeo "acción de negocio → claves internas" que colapsa en una sola fila de UI.
- El mecanismo de persistencia (`config.json` extendido vs. otra alternativa).
- El detalle visual exacto de la pantalla de Configuración (respetando la referencia que
  compartiste, ver sección de diseño abajo) — lo grueso del layout es un requisito, el pixel a
  pixel es libertad de `orion-architect`/`orion-dev`.

**Recomendación no negociable de proceso:** este REQ modifica la lógica central de clasificación
de riesgo en `core/security_manager.py` (no solo la consume, como sí hacían REQ-016/017) — por lo
tanto el flujo pasa obligatoriamente por `orion-security` como paso dedicado antes de `orion-dev`,
igual que REQ-005. No es opcional ni queda a discreción de `orion-architect`.

## Objetivo
Permitir que el usuario suba (nunca baje) la exigencia de confirmación de una acción del sistema
desde una pantalla nueva de Configuración en la app de escritorio, manteniendo intacto el piso
fail-closed introducido por REQ-005: ninguna acción ya clasificada Amarilla/Roja en código puede
terminar ejecutándose "sin confirmar" por un cambio de configuración, y ninguna acción sin
clasificar puede ser tocada por este mecanismo.

## Alcance
- Incluye:
  - Un mecanismo de "override de configuración" que compara el nivel definido en código
    (`core/security_manager.py::_register_default_actions()` y las otras dos funciones de
    registro) contra un nivel guardado por el usuario, y siempre aplica
    `max(nivel_código, nivel_config)` — nunca `min`. Ver ASUMIDO sobre dónde persiste ese valor.
  - Una pantalla nueva **"Configuración"** en la app de escritorio (webview REQ-015/016),
    siguiendo el patrón visual de referencia compartido por Johan (app "WorkBuddy AI": modal con
    navegación lateral agrupada en secciones y un panel de contenido a la derecha con tarjetas;
    cada setting es una fila con etiqueta+descripción a la izquierda y su control a la derecha) —
    ver sección "Diseño de UI — referencia visual" abajo.
  - Dentro de esa pantalla, una sección **"Seguridad"** con una fila por cada acción de la
    categoría v1 (propuesta abajo), mostrando su nivel efectivo actual y un control para subirlo
    — nunca para bajarlo.
  - Nuevos `pyqtSlot`/señales en `ui/webview/bridge.py` para leer y guardar estos overrides,
    documentados explícitamente en el docstring del módulo (mismo patrón de whitelisting ya usado,
    CA-42 de SPEC-015, CA-34 de SPEC-016).
  - v1 acotada a **una sola categoría de acciones** (propuesta abajo como ASUMIDO), no las ~60
    acciones registradas hoy en el sistema.
  - Auditoría: todo intento de guardar un nivel (exitoso o rechazado por ser un intento de bajar)
    queda registrado en `audit.db`, mismo mecanismo ya usado por `register_action()`
    (`core/security_manager.py:206`, entrada `"reclasificacion_bloqueada"`) y
    `require_confirmation()`.
- No incluye:
  - Tocar acciones sin clasificar (`classify_action()` devuelve `None`) — quedan fuera de este
    REQ, siguen bloqueadas siempre por fail-closed (`core/security_manager.py:250-253`); la
    pantalla de Configuración ni las lista ni permite asignarles un nivel.
  - Configuración por canal (Desktop/Telegram/Discord/Voz/API) — la exigencia sube igual en todos
    los canales, no hay un control separado por canal.
  - Bajar el nivel de cualquier acción, sea cual sea su origen (código o un override previo del
    propio usuario) — ni la UI lo ofrece como opción, ni el backend lo aplica aunque alguien edite
    `config.json` a mano.
  - Reclasificar cualquiera de las 10 acciones 🔴 Rojo ya fijadas por REQ-005
    (`core/security_manager.py:330-340`) a un nivel superior a RED — no existe nivel superior a
    RED, por lo que esas acciones directamente no aparecen en la pantalla de v1 (no tiene sentido
    "subir" algo que ya está en el techo).
  - Aplicación en caliente del cambio sin reiniciar la app — ver ASUMIDO.
  - Categorías adicionales más allá de la propuesta para v1 — ver ASUMIDO, ajustable en el gate.
  - Cualquier cambio a `CHANNEL_ALLOWED_LEVELS` (`core/security_manager.py:54-61`) o al mecanismo
    de PIN maestro para RED (`has_pin()`/`verify_pin()`/`require_pin()`) — fuera de alcance,
    ninguna parte de este REQ los toca.
  - Un editor genérico de todas las acciones del sistema — la pantalla de v1 muestra solo la
    categoría aprobada, no un CRUD completo sobre las ~60 claves de
    `_register_default_actions()`/`_register_intent_actions()`/`_register_action_registry_actions()`.

## Módulos afectados
- `core/security_manager.py`:
  - Agregar un ranking explícito de niveles (`RiskLevel` es un `Enum` plano sin orden hoy —
    `core/security_manager.py:14` — no soporta comparación `>`/`<` de forma nativa) para poder
    calcular `max(nivel_código, nivel_config)`.
  - Agregar la función/método que aplica el merge código+config. **No reutilizar
    `register_action()` tal cual** para este propósito: hoy solo protege contra bajar RED
    (`core/security_manager.py:194-209`, confirmado también por
    `tests/test_security_manager.py:116`, `test_register_action_cannot_downgrade_red`, que solo
    cubre ese caso) — un YELLOW podría bajar a GREEN sin que el código actual lo impida. La nueva
    función debe proteger los tres niveles, no solo RED.
  - El resultado de este merge es lo que debe consultar `classify_action()`/
    `require_confirmation()` — el nivel "de código puro" y el nivel "efectivo" (con override
    aplicado) deben quedar distinguibles internamente para que la UI pueda mostrar ambos si hace
    falta (ej. "nivel base: Verde, tu ajuste: Amarillo").
- `config_manager.py` (o un módulo nuevo dedicado, ej. `core/security_config.py` — a criterio de
  `orion-architect`, documentando la decisión): persistencia de los overrides del usuario,
  siguiendo el patrón de manejo de errores ya usado en `load_config()`
  (`config_manager.py:33-57`: JSON corrupto/inexistente no crashea) — pero con una diferencia
  importante: ante config inválida o corrupta, el fallback correcto es **el nivel de código**,
  nunca "sin restricciones" ni el valor por default del dict de config.
- `ui/webview/bridge.py`:
  - Nuevo(s) `pyqtSlot` para leer el estado actual de la sección "Seguridad" (nivel efectivo por
    acción de la categoría v1) y para guardar un cambio de nivel, validando **también del lado
    Python** que el nuevo nivel es igual o superior al vigente (nunca confiar solo en que la UI no
    ofrezca la opción de bajar).
  - Señal(es) nueva(s) para confirmar al frontend que el guardado se aplicó (y, dado el ASUMIDO de
    reinicio, para comunicarle a la UI que el cambio requiere reiniciar la app).
  - Documentar los slots nuevos explícitamente en el docstring del módulo (mismo patrón de
    whitelisting que ya usan los slots de tareas/proyectos, `ui/webview/bridge.py:1-33`).
- `ui/webview/frontend/`:
  - `index.html`, `css/` (nuevo archivo o extensión de `modal.css`/`panels.css`) y un `js/`
    nuevo (ej. `settings_panel.js`) para la pantalla de Configuración completa (navegación lateral
    + panel de contenido con tarjetas), con una sección "Seguridad" mostrando las filas de la
    categoría v1.
  - `js/bridge_client.js` — wrappers nuevos para los slots del punto anterior, mismo patrón que
    `requestTasks()`/`createTask()` ya existentes.
  - Entrada nueva para abrir la pantalla (ícono/botón en el sidebar o el header), mismo patrón que
    los botones "Tareas"/"Proyectos" agregados en REQ-016.
  - Todo texto que provenga de Python (nombre de acción, descripción, nivel actual) se inserta
    exclusivamente vía `textContent`/`setAttribute` — nunca `innerHTML`/`insertAdjacentHTML`
    (regla ya establecida en `arquitectura-015.md §10.1`, extendida por `arquitectura-016.md §10`,
    verificada estructuralmente por `tests/test_webview_safe_dom_insertion.py`).
- `tests/`: nuevos tests para el merge código+config (incluyendo el caso estructural "intento de
  bajar un nivel vía config no tiene efecto"), la persistencia de overrides, los nuevos slots del
  bridge, y la extensión de `tests/test_webview_safe_dom_insertion.py` para cubrir el/los archivo(s)
  JS nuevos de la pantalla de Configuración.
- `.claude/rules/security-levels.md`: agregar una sección nueva documentando el mecanismo de
  override (mismo patrón que ya existe ahí la sección "REQ-005 — deny-list Rojo aplicada en
  código").
- **No se modifica:** `agents/tool_registry.py`, `agents/skill_tools.py`, `main.py` (salvo que
  `orion-architect` determine que el punto de aplicación del override en el arranque necesita
  engancharse ahí explícitamente — ver Caso borde sobre orden de registro).

## Diseño de UI — referencia visual (pantalla "Configuración")
Johan compartió como referencia el patrón de configuración de la app **"WorkBuddy AI"**: un modal
de "Settings" con navegación lateral agrupada en secciones (ej. "Settings" → General/Profile/
Keyboard Shortcuts, "Features" → Agents, "Data & Security" → Data Management, "About" aparte al
final) y un panel de contenido a la derecha con tarjetas por sección; dentro de cada tarjeta, cada
setting es una fila con etiqueta + descripción a la izquierda y su control (dropdown o toggle) a
la derecha.

Para REQ-019 esto se traduce en: una sección **"Seguridad"** dentro de esa navegación lateral, con
una tarjeta que contiene una fila por cada acción de la categoría v1 — etiqueta legible de la
acción (nunca la clave técnica interna) + su nivel efectivo actual a la izquierda, y un control
(dropdown o similar) a la derecha que solo ofrece el nivel actual y los niveles superiores
disponibles (nunca uno inferior). El detalle exacto de layout, spacing y componentes queda a
criterio de `orion-architect`/`orion-dev` respetando el theme claro/oscuro ya existente y el
contraste WCAG AA ya validado (CA-30 de SPEC-016) — este documento fija el **patrón estructural**
(navegación lateral por secciones + tarjetas + filas etiqueta/control), no el pixel a pixel.

## Comportamiento actual vs deseado
| Actual | Deseado |
|---|---|
| El nivel verde/amarillo/rojo de cada acción está fijo en código, sin forma de que el usuario lo cambie | El usuario puede subir (nunca bajar) el nivel de las acciones de una categoría acotada desde una pantalla de Configuración |
| No existe ninguna pantalla de "Configuración" en la app de escritorio | Pantalla nueva "Configuración" con navegación lateral por secciones y una sección "Seguridad" |
| `register_action()` solo protege contra bajar RED — un YELLOW podría bajar a GREEN sin aviso | El merge código+config protege los 3 niveles: nunca se aplica un nivel menor al de código, para ninguna acción tocada por este REQ |
| Una acción sin clasificar se bloquea siempre (fail-closed) | Se mantiene igual — este REQ no le da al usuario forma de tocar acciones sin clasificar |
| Todas las acciones ya registradas viven en 3 funciones de registro con ~60 claves técnicas, sin agrupación de negocio | Una categoría acotada (v1) se expone en la UI con etiquetas legibles, colapsando las claves internas duplicadas del mismo concepto en una sola fila |

## Criterios de aceptación

### Núcleo de seguridad — merge código + config
- [ ] CA-01: Existe un ranking explícito de `RiskLevel` (verde < amarillo < rojo) usado para
      comparar niveles — `RiskLevel` no tiene orden nativo hoy.
- [ ] CA-02: El nivel efectivo de una acción con override es siempre
      `max(nivel_código, nivel_config)`. Test estructural: registrar una acción en código como
      YELLOW, guardar un override que intente bajarla a GREEN, y verificar que
      `require_confirmation()` sigue pidiendo confirmación (se comporta como YELLOW).
- [ ] CA-03: Test estructural equivalente para RED: un override que intente bajar una acción RED
      a cualquier nivel inferior no tiene efecto — `require_confirmation()` sigue bloqueando/
      pidiendo PIN como si el override no existiera.
- [ ] CA-04: Un intento de bajar un nivel vía config (detectado en el merge) queda registrado en
      `audit.db`, igual que ya hace `register_action()` hoy para el caso RED
      (`core/security_manager.py:206`).
- [ ] CA-05: Acciones sin clasificar (`classify_action()` devuelve `None`) no son alcanzables por
      este mecanismo bajo ninguna circunstancia — ni la UI las lista, ni el backend acepta un
      override para una clave no registrada en código.
- [ ] CA-06: Un `config.json` corrupto, con una clave de override desconocida, o con un valor de
      nivel inválido (no es `green`/`yellow`/`red`) no crashea el sistema — la entrada inválida se
      ignora (se usa el nivel de código) y queda un `logger.warning` con el detalle.
- [ ] CA-07: El merge aplica igual sin importar el canal (`ChannelType`) — no existe ninguna
      variante del override que dependa de `channel`.
- [ ] CA-08: Las 10 acciones 🔴 Rojo de REQ-005 (`core/security_manager.py:330-340`) no aparecen
      como configurables en este REQ (no hay nivel superior a RED al que "subir").

### Persistencia y aplicación
- [ ] CA-09: El override guardado por el usuario persiste entre reinicios de la app (sobrevive a
      cerrar y volver a abrir O.R.I.O.N.).
- [ ] CA-10: Un cambio de nivel guardado desde la UI se refleja como "vigente" (efectivo) recién
      después de reiniciar la app — ver ASUMIDO. La UI comunica esto explícitamente al usuario al
      guardar (ej. mensaje "este cambio aplica la próxima vez que abras la app"), no lo deja
      implícito.
- [ ] CA-11: Guardar un override no requiere que el usuario reinicie el proceso de guardado en sí
      (no hay pérdida de datos si se cierra la app inmediatamente después de guardar) — la
      escritura a disco es síncrona respecto a la confirmación visual de "guardado".

### Pantalla "Configuración" — estructura general
- [ ] CA-12: Existe un punto de entrada nuevo (ícono/botón) en la app de escritorio que abre la
      pantalla "Configuración", mismo patrón visual que los accesos ya existentes a "Tareas"/
      "Proyectos" (REQ-016).
- [ ] CA-13: La pantalla sigue el patrón estructural de referencia (navegación lateral agrupada en
      secciones + panel de contenido a la derecha con tarjetas) — ver sección "Diseño de UI"
      arriba.
- [ ] CA-14: Existe una sección **"Seguridad"** en la navegación lateral.
- [ ] CA-15: La sección "Seguridad" muestra una tarjeta con una fila por cada acción de la
      categoría v1 (ver Asumidos): etiqueta legible + nivel efectivo actual a la izquierda,
      control para subir el nivel a la derecha.
- [ ] CA-16: El control de cada fila solo permite elegir el nivel actual o un nivel superior —
      nunca ofrece (ni deshabilitado, ni oculto-pero-seleccionable) un nivel inferior al vigente.
- [ ] CA-17: Toda etiqueta/descripción/nivel que la UI recibe del backend se inserta vía
      `textContent`/`setAttribute`, nunca `innerHTML`/`insertAdjacentHTML` — verificado por la
      extensión correspondiente de `tests/test_webview_safe_dom_insertion.py`.
- [ ] CA-18: Cerrar la pantalla de Configuración sin guardar no aplica ningún cambio pendiente en
      los controles.
- [ ] CA-19: Abrir la pantalla no agrega trabajo al arranque de la app — se carga perezosamente,
      solo cuando el usuario la abre (mismo criterio que CA-12 de SPEC-016 para el panel de
      Tareas).

### Bridge y contrato JS↔Python
- [ ] CA-20: Los slots nuevos del bridge para leer/guardar overrides de seguridad quedan
      documentados explícitamente en el docstring de `ui/webview/bridge.py` (mismo patrón de
      whitelisting que CA-42 de SPEC-015 / CA-34 de SPEC-016).
- [ ] CA-21: El backend (Python) valida de forma independiente que un nivel solicitado por JS sea
      igual o superior al vigente — nunca confía en que la UI ya lo filtró (defensa en profundidad:
      un script que invoque el slot directamente, sin pasar por la UI, tampoco puede bajar un
      nivel).
- [ ] CA-22: JS nunca calcula ni decide el nivel efectivo de una acción — solo muestra lo que el
      bridge le entrega y envía la intención de cambio; toda la lógica de merge/validación vive en
      Python.

### Seguridad y no-regresión general
- [ ] CA-23: `python -m py_compile` sobre todos los módulos Python nuevos/modificados no arroja
      errores.
- [ ] CA-24: La suite de tests completa sigue pasando (el conteo exacto de baseline lo documenta
      `orion-baseline`); cualquier cambio de contrato en un test existente se documenta
      explícitamente con el motivo.
- [ ] CA-25: `tests/test_security_manager.py:116` (`test_register_action_cannot_downgrade_red`) y
      el resto de los 49 tests de REQ-005 referenciados en `core/security_manager.py:29` siguen
      pasando sin modificación de su comportamiento esperado.
- [ ] CA-26: El mecanismo de override no introduce ninguna ruta nueva para exponer secretos, API
      keys o tokens — los overrides son únicamente `{acción: nivel}`, nunca contienen datos
      sensibles.
- [ ] CA-27: `.claude/rules/security-levels.md` queda actualizado con una sección nueva que
      documenta el mecanismo de override, mismo patrón que la sección existente "REQ-005 — deny-
      list Rojo aplicada en código".
- [ ] CA-28: Este REQ pasa por `orion-security` como paso dedicado antes de `orion-dev` — no es
      opcional (ver "Nota para el humano" arriba).

## Casos borde
- Un `config.json` sin la clave de overrides todavía (usuario que nunca usó la pantalla): se
  comporta exactamente igual que hoy, 100% nivel de código, sin excepciones ni crasheos.
- El usuario edita `config.json` a mano e intenta bajar un nivel: el merge en
  `core/security_manager.py` lo ignora en efecto (CA-02/CA-03), aunque el archivo en disco quede
  con el valor "bajo" escrito — el sistema nunca debe interpretar ese archivo como más permisivo.
- Una acción sube de nivel en código en un REQ futuro (ej. algo hoy YELLOW pasa a RED) mientras el
  usuario tenía un override propio en GREEN/YELLOW para esa misma acción: al reiniciar, el nivel
  efectivo pasa a ser el nuevo nivel de código más alto (`max` sigue funcionando correctamente sin
  necesidad de migrar el override guardado).
- Doble click rápido en el control de una fila de la sección "Seguridad": no dispara dos guardados
  concurrentes ni corrompe el archivo de persistencia (mismo tipo de guard ya usado contra doble
  apertura de paneles en REQ-016).
- Un override guardado apunta a una clave de acción que dejó de existir en código (ej. se eliminó
  o renombró en un REQ futuro): se ignora silenciosamente con logging, no rompe el arranque.
- Guardar un cambio y cerrar la app inmediatamente: el cambio queda persistido (CA-11), pero no
  vigente hasta el próximo arranque (CA-10) — coherente, sin estados intermedios ambiguos.
- Intentar invocar el slot de guardado del bridge directamente (sin pasar por el control de UI, ej.
  desde la consola de DevTools) con un nivel inferior al vigente: se rechaza igual, con el mismo
  registro de auditoría que un intento normal (CA-21).

## Asumidos
- ASUMIDO (interfaz — confirmado por Johan, no libre): pantalla nueva "Configuración" en la app de
  escritorio, con navegación lateral por secciones y panel de tarjetas, siguiendo el patrón visual
  de referencia "WorkBuddy AI" compartido — el detalle pixel a pixel queda a criterio de
  `orion-architect`/`orion-dev`.
- ASUMIDO (categoría v1 — orion-spec propone, Johan debe confirmar o ajustar en el gate): la
  categoría **"Apertura de aplicaciones y navegación"**, compuesta por las acciones hoy 🟢 Verde
  `open_app` (`core/security_manager.py:326`, alias conceptual del intent `OPEN_APP`,
  `core/security_manager.py:349` — misma fila de UI, sube ambas claves internas a la vez),
  `open_chrome`, `open_notepad`, `open_explorer`, `open_calculator`, `open_browser`,
  `open_spotify`, `open_url` (`core/security_manager.py:372-376`). Se eligió esta categoría (en
  vez de las acciones de borrado, ya Amarillas hoy) porque da el ejemplo más claro y de menor
  riesgo para demostrar el mecanismo "subir de Verde a Amarillo" en v1, sin tocar nada que ya pide
  confirmación. Si Johan prefiere otra categoría (ej. borrado, mensajería), se ajusta en el gate
  sin impacto en el resto de la SPEC.
- ASUMIDO (reinicio — orion-spec propone, Johan debe confirmar o pedir aplicación en caliente): un
  cambio de nivel requiere reiniciar la app para tomar efecto real en el gate de seguridad. Motivo
  técnico (ver `REQ-019-context.md`, hallazgo de timing): las acciones se registran en al menos 3
  módulos/momentos distintos del arranque (`core/security_manager.py`, `agents/tool_registry.py`,
  `main.py:65`) — aplicar el cambio sin reiniciar es significativamente más trabajo y no fue
  pedido explícitamente. Si Johan pide aplicación en caliente, es alcance adicional a re-evaluar
  con `orion-architect` antes de continuar.
- ASUMIDO (mapeo de nombres): una fila de la UI puede corresponder a más de una clave interna de
  `core/security_manager.py` cuando representan el mismo concepto de negocio alcanzado por rutas
  de código distintas (ej. `open_app` vía `Intent` vs. `open_app` como nombre canónico) — subir el
  nivel desde la UI sube todas las claves subyacentes de ese concepto a la vez, nunca una sola
  dejando la otra desalineada.
- ASUMIDO (persistencia): se extiende `config.json`/`config_manager.py` (patrón ya usado en el
  proyecto) en vez de crear una tabla nueva en una base de datos — dado que v1 es un conjunto
  acotado (una categoría, pocas claves) y no ~60 valores. `orion-architect` puede proponer una
  alternativa (ej. tabla nueva) si encuentra una razón técnica de peso; queda documentado como
  decisión suya si se aparta de este asumido.
- ASUMIDO: acciones sin clasificar quedan completamente fuera de este REQ (confirmado
  explícitamente por Johan, no es una suposición de orion-spec) — la pantalla nunca las lista ni
  el backend acepta overrides para claves no registradas en código.
- ASUMIDO: la configuración de "subir exigencia" aplica igual en todos los canales (confirmado
  explícitamente por Johan) — no hay UI ni lógica de override por canal en este REQ.
