# Contexto REQ-019 — Configuración de niveles de seguridad por el usuario

## Resumen ejecutivo
Johan quiere que el propio usuario pueda decidir, desde una opción de configuración, qué
acciones requieren confirmación y cuáles no. Hoy esa clasificación verde/amarillo/rojo está fija
en código (`core/security_manager.py::_register_default_actions()`). El REQ agrega la capacidad
de que el usuario SUBA la exigencia de cualquier acción (ej. convertir algo Verde en "pide
confirmación"), pero **nunca** puede bajar una acción ya clasificada Amarilla/Roja — el
fail-closed de REQ-005 queda intacto como piso mínimo no reconfigurable.

## Mensaje original de Johan (verbatim)
> "Sobre los procesos de seguridad quiero que el mismo usuario decida que marcar o que no que
> tenga la opción en la configuración"

## Estado actual
- **Estado tracker:** SPEC_APROBADO (CSV actualizado vía `update-tracker.mjs`:
  NUEVO → EN_SPEC → SPEC_APROBADO, `Aprobacion_SPEC=APROBADO`, `Tipo_Cambio=FEATURE_NUEVA`)
- **Último agente:** orion-spec (✅ COMPLETADO — SPEC-019.md aprobada por Johan tal cual, sin
  ajustes; handoff emitido a `orion-baseline`)
- **Fecha última actualización:** 2026-08-20
- **Rama git:** feature/REQ-015-webview-ui (rama activa en el repo; confirmar con el humano si
  este REQ debe ir en rama propia antes de que orion-architect la fije)
- **Categoría:** SEGURIDAD
- **Tipo de cambio:** FEATURE_NUEVA (extiende `core/security_manager.py` y el sistema de
  clasificación verde/amarillo/rojo introducido/endurecido en REQ-005)

## Decisiones tomadas
2026-08-20 | orion-coordinador | Categoría detectada: SEGURIDAD | El REQ modifica directamente
`core/security_manager.py`, la clasificación verde/amarillo/rojo y el gate fail-closed de
REQ-005 — no es un REQ que solo consume la clasificación (como REQ-016/017), sino que altera el
propio sistema. Corresponde `orion-security` en el flujo, no es opcional.

2026-08-20 | orion-coordinador | Decisión de producto ya tomada por Johan — NO renegociar: opción
(a) "Configurable con piso de seguridad" sobre opción (b) "Totalmente libre". El usuario puede
SUBIR la exigencia de cualquier acción (Verde → pide confirmación) pero NUNCA bajar una acción ya
clasificada Amarilla/Roja a "sin confirmar". El fail-closed de REQ-005 (ver
`.claude/rules/security-levels.md`, sección "REQ-005 — deny-list Rojo aplicada en código") queda
intacto como piso mínimo no reconfigurable por el usuario.

2026-08-20 | orion-spec | Investigación técnica completada (config_manager.py,
core/security_manager.py, ui/webview/) — ver hallazgos en "Asumidos pendientes de confirmar" y
"Riesgos activos" | Preparación de preguntas de clarificación para Johan antes de redactar
SPEC-019.md; no se tomó ninguna decisión de producto nueva, solo se acotaron las preguntas ya
identificadas por orion-coordinador con evidencia de código

2026-08-20 | orion-spec | Respuestas de Johan (vía orion-coordinador) incorporadas — Interfaz:
pantalla nueva de Configuración en el webview (no archivo a mano), siguiendo referencia visual de
la app "WorkBuddy AI" (modal con navegación lateral por secciones + panel de tarjetas, fila
etiqueta/descripción + control). Acciones sin clasificar: fuera de alcance, siguen bloqueadas
siempre. Canales: la exigencia sube igual en todos, sin configuración por canal. | Decisiones
directas de Johan, no negociables sin volver a pasar por él.

2026-08-20 | orion-spec | Dos puntos que Johan dejó a criterio de orion-spec, documentados como
ASUMIDO explícito en SPEC-019.md para que los apruebe o ajuste en el gate: (1) categoría v1 =
"Apertura de aplicaciones y navegación" (`open_app`/`OPEN_APP`, `open_chrome`, `open_notepad`,
`open_explorer`, `open_calculator`, `open_browser`, `open_spotify`, `open_url`) — se eligió por
ser el ejemplo más claro y de menor riesgo (Verde→Amarillo) sin tocar nada ya Amarillo/Rojo; (2)
aplicación del cambio tras reiniciar la app (no en caliente) — motivo técnico: el registro de
acciones ocurre en 3 módulos/momentos distintos del arranque, aplicar sin reiniciar es
significativamente más trabajo | Ver SPEC-019.md, sección "Asumidos", para el detalle completo y
la justificación de cada uno

2026-08-20 | orion-spec | SPEC-019.md redactada y entregada —
`workspace/adjuntos/REQ-019/spec/SPEC-019.md` — con 28 criterios de aceptación agrupados en 5
áreas (núcleo de seguridad, persistencia/aplicación, pantalla de Configuración, bridge, seguridad/
no-regresión), sección dedicada de "Diseño de UI — referencia visual" documentando el patrón
WorkBuddy AI, y nota no negociable de que este REQ pasa obligatoriamente por `orion-security` antes
de `orion-dev` (categoría SEGURIDAD que modifica la lógica central de clasificación de riesgo, no
solo la consume) | Pendiente de aprobación humana explícita de Johan antes de continuar a
orion-baseline — estado tracker se mantiene en NUEVO hasta esa aprobación

2026-08-20 | orion-spec | SPEC aprobada | Aprobado por Johan (vía orion-coordinador) — TAL CUAL,
sin ajustes, incluida la categoría v1 propuesta ("Apertura de aplicaciones y navegación":
`open_chrome`, `open_notepad`, `open_calculator`, etc.) y el resto de los puntos ASUMIDO
(reinicio requerido para aplicar cambios, persistencia en `config.json`, mapeo de nombres que
colapsa claves internas duplicadas)

2026-08-20 | orion-spec | Tipo de cambio: FEATURE_NUEVA | Identificado en la entrevista con
Johan (vía orion-coordinador), reflejado en el encabezado de SPEC-019.md y en el CSV vía
`update-tracker.mjs --Tipo_Cambio "FEATURE_NUEVA"`

## Descartado (y por qué)
- Opción (b) "Totalmente libre" (el usuario puede reclasificar cualquier acción a cualquier
  nivel, incluyendo apagar confirmación de algo hoy Amarillo/Rojo): descartada explícitamente por
  Johan. Contradice el objetivo de REQ-005 de que el sistema sea fail-closed y que nadie pueda
  apagar por error/bug la confirmación de una acción destructiva (ej. borrar bases de datos).

## Asumidos pendientes de confirmar
Preguntas que orion-spec debe resolver con Johan — NO asumir, NO repetir la investigación desde
cero (ya está delimitada abajo):

1. **Dónde vive la config de usuario.** Investigar el mecanismo de configuración ya existente en
   el proyecto (`config.json` / `config_manager.py` o similar) para reusar el mismo patrón en vez
   de inventar uno nuevo.

2. **Representación del override.** Cómo se representaría "el usuario subió la exigencia de la
   acción X" — ¿un bloque tipo `{"security_overrides": {"open_browser": "yellow"}}` en config,
   aplicado en `core/security_manager.py::classify_action()` / `require_confirmation()` antes de
   usar el nivel default de `_register_default_actions()`? Definir el mecanismo exacto de merge
   entre override de config y nivel de código.

3. **Validación obligatoria (no negociable, ya decidido — solo falta especificar la
   implementación).** El override de config SOLO puede mover una acción hacia arriba en la
   escala (verde→amarillo, verde→rojo, amarillo→rojo), NUNCA hacia abajo (amarillo→verde,
   rojo→amarillo, rojo→verde). Si el usuario (o un archivo de config corrupto/editado a mano)
   intenta bajar el nivel de algo, el sistema debe ignorar ese override silenciosamente en
   términos de efecto (pero con logging) y quedarse con el nivel más restrictivo entre config y
   código (max(nivel_codigo, nivel_config), nunca min). Fail-closed también acá, consistente con
   REQ-005.

4. **Interfaz de configuración — PREGUNTAR a Johan, no asumir.** ¿Un archivo de config editado a
   mano alcanza para una primera versión, o quiere una UI (en el webview de escritorio,
   REQ-015/016) para gestionar esto?

5. **Alcance de "acciones" — PREGUNTAR a Johan, no asumir.** ¿Todas las acciones ya registradas
   en `_register_default_actions()`, o Johan quiere empezar acotado a una categoría (ej. solo las
   de tareas, dado que esta conversación viene junto con REQ-017/018)?

### Hallazgos de investigación (orion-spec, 2026-08-20)

**Sobre pregunta 1 (dónde vive la config):**
- `config_manager.py:13` — `CONFIG_FILE = config.json` en la raíz del proyecto. Es JSON plano,
  sin esquema ni validación de tipos/claves desconocidas.
- `config_manager.py:15-21` — `DEFAULT_CONFIG` es un dict cerrado con 5 claves fijas
  (`agent_name`, `agent_pronunciation`, `display_name`, `weather_city`, `ui_theme`). No hay un
  mecanismo genérico de "settings arbitrarios" — cada setting tiene su propio par
  `get_x()`/`set_x()` hardcodeado (ver `get_ui_theme()`/`set_ui_theme()` en líneas 122-138 como
  patrón de referencia más reciente, REQ-013).
- `config_manager.py:33-57` (`load_config()`) — si el JSON está corrupto o no existe, cae a
  `DEFAULT_CONFIG` sin crashear (línea 55-57), y rellena claves faltantes con default (líneas
  44-53). Es el patrón "fail-safe hacia el default", reusable para el override de seguridad, pero
  ojo: para seguridad el fallback correcto ante config inválida NO es "el default del dict" sino
  "el nivel de código" (ya definido como no negociable en el punto 3 de arriba) — hay que
  replicar el patrón de manejo de errores, no el valor de fallback.
- No existe hoy ninguna pantalla de "Configuración" en el webview de REQ-015/016. Revisé
  `ui/webview/frontend/js/` completo (`sidebar.js`, `app.js`, `chat.js`, `composer.js`,
  `tasks_panel.js`, `projects_panel.js`, `confirm_modal.js`) y no hay ningún ícono de engranaje,
  ruta ni módulo de "settings/configuración/preferences" (grep sin resultados). Una UI real para
  esto en la app de escritorio sería una pantalla NUEVA de cero, no "cablear algo que ya existe" —
  esto cambia el tamaño de la pregunta 4 de "interfaz" original.

**Sobre pregunta 2 (representación del override) — estructura de `security_manager.py`:**
- `core/security_manager.py:109-117` — `SecurityManager` es un singleton con
  `self._actions: Dict[str, RiskLevel]` (un dict plano nombre→nivel). Estructura simple, fácil de
  intercalar un override antes/después de leerla.
- `core/security_manager.py:194-209` (`register_action()`) — el único mecanismo de "protección
  contra downgrade" que existe HOY solo cubre RED: `if current == RiskLevel.RED and level !=
  RiskLevel.RED: return False` (línea 202). **No hay ninguna protección contra bajar YELLOW→GREEN**
  vía `register_action()` tal como está — confirmado también en `tests/test_security_manager.py:116`
  (`test_register_action_cannot_downgrade_red`), que solo prueba el caso RED. Esto es relevante
  porque la SPEC ya define "nunca bajar, solo subir" para TODOS los niveles (no solo RED) — si
  `orion-architect` reutiliza `register_action()` tal cual para aplicar el override de config, hay
  que agregar explícitamente la comparación `max(nivel_codigo, nivel_config)` en la capa de merge,
  no asumir que `register_action()` ya protege eso.
- **Gap técnico adicional:** `RiskLevel` (línea 14) es un `Enum` plano, no `IntEnum` — no tiene
  orden nativo. Implementar `max(nivel_codigo, nivel_config)` requiere que `orion-architect`
  defina un ranking explícito (ej. `{GREEN: 0, YELLOW: 1, RED: 2}`); hoy no existe en ningún lado
  del archivo (grep de "ORDER"/"rank" sin resultados).
- Grep de "override"/"custom"/"security_config" en todo el `.py` del proyecto: sin resultados
  relevantes (el único hit fue en un test de contraste de UI, no relacionado). Se parte de cero,
  como ya asumía el contexto original — confirmado, no hay que reconciliar con nada existente.
- **Hallazgo de timing/orden de registro (nuevo, no estaba en el contexto original):** las
  acciones NO se registran todas en un solo lugar ni en un solo momento:
  - `core/security_manager.py:385-387` registra ~60 acciones al importarse el módulo (3 funciones:
    `_register_default_actions()`, `_register_intent_actions()`, `_register_action_registry_actions()`).
  - `agents/tool_registry.py:152,172,184` registra 3 acciones MÁS (`task_create`, `task_list`,
    `task_complete`) en el top-level de ESE módulo, que se ejecuta en un import posterior.
  - `main.py:65` llama `register_skill_tools(skill_manager)` en el arranque, que re-lee
    `security_manager.classify_action(intent)` para cada skill (`agents/skill_tools.py:57`) y
    vuelve a registrar el mismo valor (no pisa nada nuevo, es idempotente).
  - Consecuencia: si el override de config se aplica una sola vez "al final" del módulo
    `security_manager.py` (el lugar más natural), NO alcanzaría a cubrir las 3 acciones que
    `agents/tool_registry.py` registra después. Un mecanismo correcto necesita aplicarse DESPUÉS
    de que terminen TODAS las fases de registro (código + tools + skills), no solo una vez al
    importar `security_manager.py`. Esto es una decisión de arquitectura (`orion-architect`), pero
    tiene una implicación de producto que sí vale preguntarle a Johan: ver pregunta nueva abajo
    sobre "aplicar en caliente vs. solo al reiniciar".
- Punto positivo encontrado: `ui/webview/bridge.py:589-603` (`_build_chips_payload()`) ya consulta
  `security_manager.classify_action()` en el momento (no cachea el nivel), según su propio
  comentario "CA-40 — risk_level se consulta en el momento (nunca hardcodeado)". Esto significa
  que si el override modifica `security_manager._actions` en memoria, los chips de acciones
  rápidas del webview reflejan el cambio automáticamente sin trabajo extra — un punto a favor de
  que, aunque la interfaz de config en v1 sea un archivo editado a mano, el efecto en la UI ya
  existente sea inmediato una vez aplicado el override.

**Sobre pregunta 3 (alcance de acciones) — inventario completo de `_register_default_actions()`
y las otras dos funciones de registro (todas en `core/security_manager.py`):**
- 🟡 Amarillo (14): `shutdown`, `restart`, `close_app`, `delete_file`, `delete_folder`,
  `delete_conversation`, `delete_task`, `delete_project`, `execute_code`, `create_skill`,
  `modify_skill`, `delete_skill`, `send_message` (líneas 302-322) + `write_file_direct`,
  `save_file_desktop` (línea 378, en `_register_action_registry_actions()`) + intents
  `CLOSE_APP`, `SYS_POWER_OFF`, `EXECUTE_CODE`, `CREATE_SKILL`, `MODIFY_SKILL`, `DELETE_SKILL`
  (línea 356-359, en `_register_intent_actions()`, mismo concepto con otro nombre).
- 🟢 Verde (6 + 29 intents + 18 action_registry): `system_info`, `search_files`, `chat`,
  `open_app`, `list_files`, `proactive_trigger` (líneas 323-328) + 29 valores de `Intent`
  (línea 348-355) + 18 acciones de `agents/action_registry.py` (línea 371-377) + `task_create`,
  `task_list`, `task_complete` (GREEN, registradas aparte en `agents/tool_registry.py:152-190`).
- 🔴 Rojo (10, fijo desde REQ-005 — no debería ser tocable por este REQ salvo que Johan diga
  explícitamente lo contrario): `format_disk`, `delete_database`, `expose_secrets`,
  `modify_source_code`, `send_email_as_user`, `post_social_media`, `elevated_system_command`,
  `install_uninstall_software`, `modify_system_env_vars`, `grant_third_party_access`
  (líneas 330-340).
- **Hallazgo relevante para la pregunta de alcance:** los nombres de acción NO viven en un solo
  espacio de nombres — hay 4 esquemas distintos mezclados (nombre "canónico" tipo `delete_file`,
  `Intent.value` en MAYÚSCULAS tipo `CLOSE_APP`, clave literal de `action_registry.py` tipo
  `open_chrome`, y nombre de `ToolSpec` tipo `task_create`), con solapamiento conceptual pero no
  textual (ej. `close_app` vs `CLOSE_APP` vs `close_window` son 3 claves distintas para conceptos
  parecidos). Exponerle a Johan ~60 claves técnicas internas para que elija cuáles subir de nivel
  no es una buena UX ni para v1 archivo-a-mano ni para una UI futura — probablemente el override
  deba pensarse por categoría/acción-de-negocio reconocible (ej. "borrar archivos", "ejecutar
  código") en vez de por clave interna cruda. Esto refuerza la necesidad de la pregunta de alcance
  de abajo.

## Riesgos activos
- Tensión directa con REQ-005: cualquier implementación que permita bajar el nivel de una acción
  Amarilla/Roja reabre el riesgo que REQ-005 cerró (apagar por error/bug la confirmación de algo
  destructivo, ej. borrar `memory.db` / `semantic_memory.db` / `tasks.db`). El piso de seguridad
  (opción a) mitiga esto, pero la implementación debe validarse explícitamente en
  `orion-security` antes de `orion-dev` — no basta con la spec, hay que auditar el código real.
- Si la interfaz de configuración termina siendo un archivo editado a mano, un archivo corrupto o
  mal formado no debe crashear el sistema ni debe interpretarse como "sin restricciones" —
  definir comportamiento ante config inválida (debe caer al nivel de código, nunca al más
  permisivo).
- **(Nuevo, hallado por orion-spec)** `register_action()` (`core/security_manager.py:194-209`)
  hoy solo bloquea el downgrade de RED — un YELLOW podría bajarse a GREEN sin que el código actual
  lo impida. Si `orion-architect` reutiliza esa función tal cual para aplicar el override de
  config, reintroduce el riesgo que este REQ busca cerrar. La capa de merge debe implementar su
  propia comparación `max(nivel_codigo, nivel_config)` para los tres niveles, no confiar en la
  protección parcial existente.
- **(Nuevo, hallado por orion-spec)** El registro de acciones ocurre en al menos 3 momentos/módulos
  distintos (`core/security_manager.py` al importarse, `agents/tool_registry.py` al importarse,
  `main.py:65` en el arranque vía `register_skill_tools()`). Un override que se aplique una sola
  vez "al final de `security_manager.py`" no cubriría las acciones que `agents/tool_registry.py`
  registra después. Afecta el diseño de `orion-architect`, y tiene una implicación de producto:
  ver pregunta sobre "aplicar en caliente vs. solo al reiniciar" en la lista de preguntas para
  Johan.
- **(Nuevo, hallado por orion-spec)** `RiskLevel` es un `Enum` plano sin orden nativo
  (`core/security_manager.py:14`) — no existe hoy ningún ranking verde<amarillo<rojo en código.
  Hay que crearlo para poder comparar niveles.

## Preguntas de clarificación pendientes (para Johan — orion-spec, 2026-08-20)
Sin responder estas 5 preguntas no se puede redactar SPEC-019.md. Ver investigación completa
arriba para el porqué de cada una.

1. **Interfaz.** ¿Alcanza con un archivo de configuración editable a mano para una primera
   versión, o necesitás una pantalla en la app de escritorio (webview REQ-015/016) para
   gestionar esto? Ojo: hoy NO existe ninguna pantalla de "Configuración" en el webview (no hay
   ícono de engranaje ni módulo de settings) — sería una pantalla nueva de cero, no algo que se
   cablea a algo ya construido.
2. **Alcance de acciones.** Hay ~60 acciones registradas repartidas en 4 esquemas de nombres
   distintos y no siempre alineados entre sí (nombre canónico, `Intent.value`, clave de
   `action_registry.py`, nombre de `ToolSpec`). ¿Querés poder subir la exigencia de TODAS, o
   empezamos acotado a una categoría/grupo reconocible (ej. "borrado de archivos/conversaciones/
   tareas", "ejecución de código", etc.)? Dado el mezclado de nombres internos, probablemente
   convenga exponerle al usuario conceptos de negocio, no las claves técnicas crudas.
3. **Acciones sin clasificar.** Hoy cualquier acción sin registrar se bloquea siempre
   (fail-closed, `core/security_manager.py:250-253`). El mecanismo de "solo subir, nunca bajar"
   ¿aplica también a estas (el usuario podría asignarles un nivel explícito, con el riesgo de
   clasificar mal algo grave como Verde), o quedan totalmente fuera de este REQ y siguen
   bloqueadas siempre, sin que el usuario pueda tocarlas?
4. **Canales.** El sistema ya distingue canales (Desktop, Telegram, Discord, Voz, API —
   `core/security_manager.py:45-61`) con niveles permitidos distintos por canal. ¿La
   configuración de "subir exigencia" debe aplicar igual en todos los canales, o querés poder
   configurarlo por canal (ej. ser más estricto en Voz que en Desktop)?
5. **Aplicación en caliente vs. reinicio.** Las acciones se registran en al menos 3 módulos/
   momentos distintos del arranque (`core/security_manager.py`, `agents/tool_registry.py`,
   `main.py:65`). Aplicar un cambio de configuración sin reiniciar la app es técnicamente más
   complejo que aplicarlo solo la próxima vez que arranca O.R.I.O.N. ¿Es aceptable para v1 que el
   cambio de nivel de una acción requiera reiniciar la aplicación, o necesitás que aplique de
   inmediato apenas el usuario lo guarda?

## Decisiones tomadas (cont.)
2026-08-20 | orion-baseline | Verificación exhaustiva línea por línea de todo lo citado por
orion-spec en el contexto/SPEC-019 — sin discrepancias encontradas. Confirmado con lectura directa
del código real (no se tomó la investigación previa como dada): `RiskLevel` líneas 14-17 (Enum
plano, sin orden), `SecurityManager._actions` línea 115, `register_action()` líneas 194-209 (solo
protege RED, confirmado el texto exacto), `classify_action()` líneas 211-212,
`require_confirmation()` líneas 232-294, y los 3 puntos de registro con sus líneas exactas de
invocación al final del módulo: `_register_default_actions()` línea 385 (definida 300-340),
`_register_intent_actions()` línea 386 (definida 343-363), `_register_action_registry_actions()`
línea 387 (definida 366-382). Las 9 claves de la categoría v1 propuesta (`open_app` línea 326,
`OPEN_APP` línea 349, `open_chrome`/`open_notepad`/`open_explorer`/`open_calculator`/
`open_browser` línea 372, `open_spotify` línea 373, `open_url` línea 376) confirmadas una por una,
todas GREEN hoy, sin solape textual con las 10 claves RED (330-340) ni las 20 YELLOW existentes |
Ver `origen/baseline-019.md` para el detalle completo con línea exacta de cada afirmación

2026-08-20 | orion-baseline | Confirmado que NO existe pantalla de "Configuración" en
`ui/webview/frontend/` — grep case-insensitive de config/settings/Configuraci/gear/engranaje sobre
todo el frontend solo matcheó `vendor/qwebchannel.js` (librería Qt de terceros, sin relación).
Patrón de referencia para el punto de entrada confirmado con precisión mayor a la del contexto
original: los botones `tasks-btn`/`projects-btn` viven en `index.html:55-62`, pero **el wiring del
click ocurre en `app.js:106-107` (import en líneas 30/33), no en `sidebar.js`** — corrección de una
asunción implícita razonable pero no verificada por orion-spec | Relevante para que
`orion-architect` ubique correctamente dónde enganchar el botón nuevo de Configuración

2026-08-20 | orion-baseline | Suite completa de pytest: 420 passed, 2 failed. Los 2 fallos
(`tests/test_llm_provider.py::test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse` y
`test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto`) son pre-existentes, causa raíz
confirmada: `ModuleNotFoundError: No module named 'anthropic'` (paquete no instalado en el
entorno, no es un bug de código). Ninguno de los dos toca `core/security_manager.py`,
`config_manager.py` ni `ui/webview/bridge.py`. `tests/test_security_manager.py` en aislamiento:
55 passed, 0 failed — `test_register_action_cannot_downgrade_red` (línea 116-120, referenciado por
CA-25) → PASSED, confirmado que hoy solo cubre el caso RED tal como decía el contexto |
`python -m py_compile` sin errores sobre los 3 módulos centrales

2026-08-20 | orion-baseline | 14 archivos identificados a modificar (previsión) + confirmación de
que `agents/tool_registry.py`, `agents/skill_tools.py`, `main.py` NO se tocan salvo decisión
explícita de `orion-architect` sobre el punto de aplicación del override en el arranque | Ver
`origen/baseline-019.md`, sección "Archivos que serán modificados"

## Riesgos activos
- **(orion-baseline)** `config_manager.py::load_config()` (líneas 55-57): ante JSON corrupto,
  sobreescribe TODO el archivo con `DEFAULT_CONFIG` — si REQ-019 extiende este mismo `config.json`
  con overrides de seguridad, un archivo corrupto haría perder también los overrides guardados
  previamente, no solo las 5 claves originales del config. El fallback es "todo o nada" a nivel de
  archivo, no por clave. `orion-architect` debe decidir si esto es aceptable para v1 o si amerita
  un archivo/tabla separada para los overrides de seguridad (ya contemplado como alternativa en el
  ASUMIDO de persistencia de SPEC-019).
- **(orion-baseline)** `save_config()` (líneas 60-65) escribe de forma síncrona sin journal ni
  escritura atómica (sin archivo temporal + rename) — un corte de energía a mitad de escritura
  podría corromper el archivo. No es un riesgo nuevo de este REQ, pero cualquier extensión de
  `config.json` lo hereda; vale que `orion-architect` lo tenga en cuenta si decide reforzar la
  escritura como parte de este cambio.
- Los 2 fallos pre-existentes de `tests/test_llm_provider.py` (falta el paquete `anthropic` en el
  entorno) no son atribuibles a este REQ y no están en ninguna zona que REQ-019 toque — documentado
  para que `orion-tester` no los confunda con una regresión propia.

## Estado actual
- Estado tracker: EN_ARQUITECTURA
- Último agente: orion-baseline
- Fecha última actualización: 2026-08-20

## Decisiones tomadas (cont. 2)
2026-08-20 | orion-architect | Propuesta técnica redactada —
`workspace/adjuntos/REQ-019/propuestas/arquitectura-019.md` — cubriendo los 28 CA de
SPEC-019 | Diseño clave: (1) `RiskLevel` NO se convierte a `IntEnum` — se agrega un dict
de ranking aparte (`_RISK_LEVEL_ORDER`) porque `IntEnum` rompería `.value` como string,
contrato ya consumido por `ui/webview/frontend/js/composer.js:110`
(`chip-risk-${chip.risk_level}`); (2) el merge código+config (`max`, nunca `min`) se
implementa DENTRO de `register_action()` (método extendido, mismo contrato público, RED
sigue protegido igual que hoy pero sobre un nuevo dict `_base_levels`), no como una
función aparte reutilizando `register_action()` tal cual — así se cubren los 4 puntos de
registro reales (los 3 de `security_manager.py` + `agents/tool_registry.py:73`, que
también llama `register_action()`) sin tocar `agents/tool_registry.py`,
`agents/skill_tools.py` ni `main.py`, resolviendo el problema de timing señalado por
`orion-spec`/`orion-baseline` sin depender del orden de import entre módulos.

2026-08-20 | orion-architect | Desvío propuesto del ASUMIDO de persistencia de SPEC-019:
archivo nuevo y separado `security_overrides.json` + módulo nuevo `core/security_config.py`
(escritura atómica vía `os.replace()`), en vez de extender `config.json`/`config_manager.py`
| Motivo: `config_manager.py::load_config()` (líneas 55-57) es "todo o nada" ante JSON
corrupto — si los overrides de seguridad vivieran en `config.json`, una corrupción de
CUALQUIER otra clave (ej. `weather_city`) borraría también los overrides de seguridad
guardados. Aislar el archivo aísla el radio de impacto en ambas direcciones y permite
escritura atómica exactamente donde la integridad importa más, sin retrofit-ear todo
`config_manager.py` (fuera de alcance de esta SPEC).

2026-08-20 | orion-coordinador (relayed) | Johan aprobó el desvío del ASUMIDO —
archivo separado `security_overrides.json`, no mezclar con `config.json` — y el resto de
`arquitectura-019.md` queda aprobado tal cual, sin más ajustes | Aprobación recibida por
`orion-architect` vía mensaje de `orion-coordinador` (no en interacción directa con Johan
dentro de esta sesión de `orion-architect`) — se deja constancia explícita del canal, mismo
criterio de trazabilidad ya usado en este documento para "Aprobado por Johan (vía
orion-coordinador)" en la aprobación de SPEC-019.

## Descartado (y por qué) — cont.
- Extender `config.json`/`config_manager.py` para los overrides de seguridad (el ASUMIDO
  original de SPEC-019): descartado por `orion-architect` con justificación técnica
  (riesgo de "todo o nada" de `load_config()`), propuesta alternativa aprobada por Johan
  (vía orion-coordinador) — ver "Decisiones tomadas (cont. 2)".
- Convertir `RiskLevel` a `IntEnum` para obtener orden nativo: descartado porque rompería
  el contrato `.value` (string `"green"/"yellow"/"red"`) ya consumido por
  `ui/webview/frontend/js/composer.js:110` para construir la clase CSS del chip de riesgo
  — se usa un dict de ranking aparte (`_RISK_LEVEL_ORDER`) en su lugar.

## Estado actual
- Estado tracker: ARQUITECTURA_APROBADA
- Último agente: orion-architect
- Fecha última actualización: 2026-08-20
- Rama git: sin fijar — la nota previa de `orion-coordinador` (ver "Estado actual"
  inicial de este documento) pedía confirmar con el humano si este REQ va en rama propia
  antes de fijarla; ni el handoff de aprobación de arquitectura ni el mensaje de
  `orion-coordinador` la resolvieron explícitamente. `orion-architect` NO asume una rama
  nueva (`.claude/rules/git.md`: "Nunca crear una rama sin preguntar antes al humano") —
  queda pendiente para quien la fije antes de que `orion-dev` escriba código (rama activa
  actual del repo: `feature/REQ-015-webview-ui`, no específica de REQ-019).
- Pendiente inmediato: `orion-security` (paso obligatorio no negociable, CA-28) antes de
  `orion-dev`.

## Decisiones tomadas (cont. 3)
2026-08-20 | orion-security | Auditoría completada — `pruebas/security-audit-019.md` —
Veredicto: ❌ REQUIERE CAMBIOS | Verificado línea por línea contra el código real
(`core/security_manager.py` completo, `agents/tool_registry.py:73`, `ui/webview/bridge.py`
docstring, `ui/gui_workers.py::CallableWorker.run()`, `tests/test_security_manager.py:116-120`)
y contra el pseudocódigo exacto de `arquitectura-019.md`, no contra el resumen en texto.
Diseño central (merge simétrico de 3 niveles vía `_RISK_LEVEL_ORDER`/`_merge_with_override()`,
catálogo estático `_SECURITY_ROWS_V1` que excluye estructuralmente las 10 claves RED de REQ-005,
separación de `security_overrides.json`, auditoría de intentos de bajada y de guardados)
confirmado sólido, sin necesidad de rediseño. Hallazgo positivo no pedido explícitamente:
`_merge_with_override()` protege contra downgrade de CUALQUIER acción (no solo las del catálogo
del bridge) incluso si `security_overrides.json` se edita a mano fuera de la UI — segunda capa de
defensa independiente del catálogo.

2026-08-20 | orion-security | Hallazgo A (BLOQUEANTE) — `core/security_config.py::load_security_overrides()`
(arquitectura-019.md §2) no captura `UnicodeDecodeError` (subclase de `ValueError`, no de
`OSError`/`IOError` ni de `json.JSONDecodeError`) — un `security_overrides.json` con bytes no-UTF-8
válidos (corrupción realista: corte de energía a mitad de escritura, archivo editado con otra
codificación) propaga la excepción sin capturar hasta `SecurityManager.__new__()`
(tiempo de import de `core/security_manager.py:297`), crasheando el arranque completo de
O.R.I.O.N., no solo la pantalla de Configuración | Viola directamente el requisito no negociable
de fail-closed (punto 2 del handoff de `orion-architect`: "nunca crashea el arranque completo del
sistema"). Ajuste acotado: ampliar el `except` a `(json.JSONDecodeError, UnicodeDecodeError,
OSError)` o a `Exception` genérico con logging (permitido por `.claude/rules/python-style.md`).
Handoff vuelto a `@orion-architect`, no a `@orion-dev`.

2026-08-20 | orion-security | Hallazgo B (no bloqueante, requisito obligatorio para orion-dev) —
`ui/webview/bridge.py::_save_security_override_flow()` (arquitectura-019.md §3.3) referencia
`_RISK_LEVEL_ORDER_LOCAL`, nunca definido en la propuesta (solo existe `_LEVEL_ORDER`, una lista de
strings con nombre y forma distintos). Verificado contra `ui/gui_workers.py` que el efecto de este
bug, tal cual escrito, es fail-closed (NameError capturado por `CallableWorker.run()` →
`security_override_save_rejected`), no fail-open — no es un hallazgo de seguridad, pero sin
corregir deja el mecanismo de "subir de nivel" inoperante. Recomendación: una sola fuente de verdad
del ranking, reusar `core.security_manager._RISK_LEVEL_ORDER` en vez de duplicar la representación
en `bridge.py` (la duplicación es en sí un riesgo de que ambas definiciones diverjan en un REQ
futuro y reabran un hueco de downgrade en la validación server-side de CA-21) | No requiere volver
a `orion-architect`, resoluble directo por `orion-dev`.

2026-08-20 | orion-security | Hallazgo C (no bloqueante, observación) — El catálogo v1 permite
subir una acción hoy Verde directo a Rojo (`options` no tiene techo en `_build_security_overrides_payload()`),
lo que puede autobloquear permanentemente una acción benigna (ej. "Abrir Chrome") si el usuario la
sube a Rojo sin `ORION_AUTH_PIN` configurado — no es un hueco de seguridad (más restrictivo, no
menos) y ningún CA lo prohíbe, pero excede el objetivo explícito de v1 ("demostrar Verde→Amarillo").
Sugerido a `orion-dev`/`orion-architect` acotar `options` a techo `yellow` en v1, o confirmar con
Johan si prefiere dejarlo abierto | No bloqueante.

## Riesgos activos
- **(orion-security)** Hasta que se resuelva el Hallazgo A, la implementación literal del
  pseudocódigo de `arquitectura-019.md` §2 tiene una ruta de crash de arranque completo ante un
  `security_overrides.json` corrupto con bytes no-UTF-8 — no debe pasar a `orion-dev` sin este
  ajuste incorporado a la arquitectura.
- **(orion-security)** Hallazgo B (nombre indefinido en `bridge.py`) debe resolverse durante
  `orion-dev` explícitamente con una única fuente de verdad de ranking — si se ignora, el REQ
  completo queda funcionalmente inoperante (aunque de forma segura), lo cual haría fallar
  `orion-tester` igual.

## Estado actual
- Estado tracker: ARQUITECTURA_APROBADA (sin cambios — el CSV no se toca en este paso; ver nota de
  `orion-security` sobre no escribir columnas que no le corresponden)
- Último agente: orion-security
- Fecha última actualización: 2026-08-20
- Pendiente inmediato: `@orion-architect` — incorporar el ajuste del Hallazgo A a
  `arquitectura-019.md` §2 antes de volver a `orion-security` o pasar directo a `orion-dev` (a
  criterio de `orion-architect`/Johan si el ajuste es suficientemente acotado para no requerir
  una segunda pasada completa de auditoría).

## Decisiones tomadas (cont. 3)
2026-08-20 | orion-security | Auditoría de `arquitectura-019.md` —
`pruebas/security-audit-019.md` — veredicto ❌ REQUIERE CAMBIOS: 1 hallazgo bloqueante
(A) + 2 no bloqueantes (B, C); diseño central del merge confirmado sólido, sin
rediseño | Hallazgo A: `load_security_overrides()` no capturaba `UnicodeDecodeError`
(no es subclase de `OSError`/`JSONDecodeError`) — como corre dentro de
`SecurityManager.__new__()` a tiempo de import, un `security_overrides.json` con bytes
no-UTF-8 crasheaba el arranque COMPLETO de O.R.I.O.N., no solo la pantalla de
Configuración. Hallazgo B (no bloqueante): `_RISK_LEVEL_ORDER_LOCAL` referenciado en el
pseudocódigo del bridge nunca estaba definido — efecto verificado como fail-closed (no
fail-open), pero inutilizaba la función de guardado si `orion-dev` lo copiaba literal.
Hallazgo C (no bloqueante, observación): el catálogo v1 permitía saltar de Verde
directo a Rojo, con riesgo de auto-bloqueo sin PIN configurado y sin vía de recuperación
desde la UI.

2026-08-20 | orion-architect | Addendum §11 agregado a `arquitectura-019.md` respondiendo
los 3 hallazgos, sin reabrir §1-§10 | (A, bloqueante) `except Exception` amplio en
`load_security_overrides()` + segunda capa de defensa en `_load_and_parse_overrides()`.
(B, no bloqueante) `bridge.py` pasa a importar y reusar
`core.security_manager._RISK_LEVEL_ORDER` como única fuente de verdad del ranking, en
vez de mantener `_LEVEL_ORDER`/`_RISK_LEVEL_ORDER_LOCAL` como representaciones
paralelas. (C, decisión propia) SE ADOPTA la sugerencia de la auditoría: techo de
`yellow` en las 8 filas del catálogo v1 (`_V1_MAX_OFFERABLE_LEVEL = RiskLevel.YELLOW`),
aplicado tanto en las `options` que arma el payload como revalidado server-side en el
slot de guardado — política del catálogo `bridge.py`, no del núcleo
`security_manager.py`. Se decidió sin volver a consultar a Johan (corrección técnica de
seguridad dentro del margen ya delegado a `orion-architect`/`orion-dev` por la propia
SPEC, no un cambio de alcance/política de producto) — mismo criterio que indicó
`orion-coordinador` al relayar el hallazgo.

## Estado actual
- Estado tracker: ARQUITECTURA_APROBADA (sin cambio — el ciclo de auditoría de
  `orion-security` no tiene una columna propia en `requerimientos.csv`, no está en la
  lista de Estados del tracker de `CLAUDE.md`)
- Último agente: orion-architect (addendum post-auditoría)
- Fecha última actualización: 2026-08-20
- Rama git: sigue sin fijar (ver nota de "Estado actual" anterior) — no resuelto en este
  ciclo, no era el objeto de la auditoría de seguridad
- Pendiente inmediato: re-chequeo de `orion-security` sobre el addendum §11 de
  `arquitectura-019.md`

## Decisiones tomadas (cont. 4)
2026-08-20 | orion-security | Re-auditoría (2da pasada) del addendum §11 de `arquitectura-019.md`
— `pruebas/security-audit-019.md`, sección "Re-auditoría — 2da pasada" — Veredicto: ✅ APROBADO |
Verificado que §1-§10 no cambiaron (solo §11 es nuevo) y que el REQ aún no pasó por `orion-dev`
(`core/security_config.py` no existe, `core/security_manager.py` sin símbolos de REQ-019) — la
verificación es sobre el pseudocódigo del addendum, no sobre un diff de código real.

- **Hallazgo A (bloqueante):** CERRADO. `except Exception as e:` amplio con `logger.warning`
  (incluye tipo y mensaje, no silencioso) en `load_security_overrides()` + segunda capa
  independiente en `_load_and_parse_overrides()` (`core/security_manager.py`) — ningún tipo de
  corrupción de `security_overrides.json` puede propagarse hasta `SecurityManager.__new__()`.
  Observación no bloqueante nueva: el `from core.security_config import load_security_overrides`
  de `_load_and_parse_overrides()` queda fuera del `try/except` — un `ImportError`/`SyntaxError`
  real del módulo nuevo no quedaría cubierto por esta capa, pero es una clase de falla distinta
  (bug de código, no corrupción de datos en runtime) que CA-23 (`py_compile`) ya cubre antes de que
  el REQ avance; mismo patrón de import perezoso sin guardia que ya usa hoy
  `require_confirmation()` con `core.confirmation`. No requiere acción de `orion-dev`, sí que
  `orion-tester` confirme el `py_compile` de `core/security_config.py` como parte de CA-23.
- **Hallazgo B (no bloqueante):** CERRADO. `bridge.py` importa directo
  `core.security_manager._RISK_LEVEL_ORDER` (mismo patrón ya usado hoy en `bridge.py:43` para
  `ChannelType` — sin riesgo de import circular, confirmado contra el archivo real). Se elimina
  `_LEVEL_ORDER`/`_RISK_LEVEL_ORDER_LOCAL`; `_ORDERED_LEVEL_VALUES` se deriva del dict único, nunca
  se mantiene a mano en paralelo. Observación cosmética no bloqueante: queda un import local
  redundante de `RiskLevel` en `_save_security_override_flow()` que `orion-dev` puede limpiar al
  implementar.
- **Hallazgo C (no bloqueante):** CERRADO. Techo `_V1_MAX_OFFERABLE_LEVEL = RiskLevel.YELLOW`
  aplicado en ambos lados — `options` del payload (verificada la aritmética para los 3 casos:
  GREEN→`["green","yellow"]`, YELLOW→`["yellow"]`, caso borde RED futuro protegido por `max()`) y
  revalidado server-side en `_save_security_override_flow()` sin depender del `<select>` de JS. Sin
  hueco de seguridad en ninguna dirección (más restrictivo, nunca menos). **Hallazgo nuevo, no
  bloqueante:** la sección "Pruebas sugeridas" de `arquitectura-019.md` (previa al addendum, sin
  actualizar) sigue diciendo que una fila con `effective_level == "yellow"` debe dar
  `options == ["yellow", "red"]` — ese valor quedó obsoleto/contradictorio con el techo de §11.3;
  el resultado correcto ahora es `options == ["yellow"]`. Nota dejada para `orion-dev`/
  `orion-tester`: usar `["yellow"]`, ignorar el valor literal pre-addendum en ese punto.

No se encontró ningún hallazgo bloqueante nuevo. Handoff emitido a `@orion-dev`.

## Riesgos activos (cont.)
- **(orion-security, 2da pasada)** Notas no bloqueantes para `orion-dev`/`orion-tester` al
  implementar REQ-019: (1) confirmar `py_compile` de `core/security_config.py` como parte de CA-23;
  (2) limpiar el import local redundante de `RiskLevel` en `_save_security_override_flow()`;
  (3) el test de CA-16 para una fila `effective_level == "yellow"` debe esperar
  `options == ["yellow"]` (techo v1 de §11.3), no `["yellow", "red"]` como decía la sección
  "Pruebas sugeridas" pre-addendum de `arquitectura-019.md`.

## Estado actual
- Estado tracker: ARQUITECTURA_APROBADA (sin cambio — sin columna propia de auditoría de
  seguridad en `requerimientos.csv`)
- Último agente: orion-security (re-auditoría del addendum §11, veredicto ✅ APROBADO)
- Fecha última actualización: 2026-08-20
- Rama git: sigue sin fijar — no resuelto en este ciclo, no era el objeto de la auditoría
- Pendiente inmediato: `@orion-dev` — implementar `arquitectura-019.md` §1-§11 completo
  (incluye el addendum §11, no solo §1-§10), con las 3 notas no bloqueantes de arriba

## Decisiones tomadas (cont. 5)
2026-08-20 | orion-dev | Implementación completa de `arquitectura-019.md` §1-§11 (addendum
incluido) — `workspace/adjuntos/REQ-019/propuestas/desarrollo-log-019.md` — 12 archivos
modificados + 3 nuevos (`core/security_config.py`,
`ui/webview/frontend/js/settings_panel.js`,
`ui/webview/frontend/css/settings_panel.css`) + 2 archivos de test nuevos
(`tests/test_security_config.py`, más extensión de `test_security_manager.py`/
`test_webview_bridge.py`/`test_webview_safe_dom_insertion.py`) | Cubre las 3 notas no
bloqueantes del handoff de `orion-security` (py_compile de `security_config.py` como parte
de CA-23; sin import local redundante de `RiskLevel` en `_save_security_override_flow()`;
test de CA-16 para `effective_level=="yellow"` usa `options==["yellow"]`, no
`["yellow","red"]`).

2026-08-20 | orion-dev | Desviación puntual del pseudocódigo de §3.3 —
`_on_security_override_error()` pasó a recibir `(row_id, message)` y emitir
`security_override_save_rejected(row_id)`, en vez de solo loguear como mostraba el
pseudocódigo literal del addendum | La propia arquitectura señalaba esto como nota de
implementación abierta ("confirmar el mecanismo exacto de `run_async()` ... no asumir la
forma del mensaje de error"); sin este ajuste CA-21 quedaría inoperante del lado del
frontend (el `<select>` nunca se rehabilitaría). Ver desarrollo-log-019.md, punto 4, para
el detalle completo y los 4 tests que lo cubren.

2026-08-20 | orion-dev | Verificación local completa: `python -m py_compile` sin errores
sobre los 3 módulos nuevos/modificados; `python -m pytest tests/ --tb=short -q` → 2 failed
(pre-existentes, `ModuleNotFoundError: No module named 'anthropic'`, ajenos a este REQ,
documentados por `orion-baseline`), 480 passed (incluye 38 tests nuevos de REQ-019).
`test_register_action_cannot_downgrade_red` (CA-25) pasa sin modificación de su propio
código | Sin regresiones nuevas atribuibles a REQ-019.

2026-08-20 | orion-dev | `requerimientos.csv` actualizado vía `update-tracker.mjs`
(Estado → EN_PRUEBAS) | Handoff emitido a `orion-tester`. NO se ejecutó `git commit` — se
entrega únicamente el mensaje de commit sugerido, pendiente de `orion-tester` + `orion-qa`
+ prueba manual del humano.

## Estado actual
- Estado tracker: EN_PRUEBAS
- Último agente: orion-dev
- Fecha última actualización: 2026-08-20
- Rama git: `feature/REQ-015-webview-ui` (confirmada explícitamente por Johan — se sigue
  trabajando sobre la misma rama que ya tiene REQ-015/016/017 sin commitear, no se creó
  rama nueva)
- Pendiente inmediato: `@orion-tester` — ejecutar los criterios de aceptación de
  SPEC-019.md contra la implementación real; ver
  `workspace/adjuntos/REQ-019/propuestas/desarrollo-log-019.md` para el detalle de
  archivos y verificación local ya realizada por `orion-dev`.

## Decisiones tomadas (cont. 6)
2026-08-20 | orion-tester | Veredicto: ✅ PASS — 28/28 CA de SPEC-019 verificados —
`pruebas/test-results-019.md` | Verificación por lectura directa del código real
(`core/security_manager.py`, `core/security_config.py`, `ui/webview/bridge.py`,
`ui/webview/frontend/js/settings_panel.js`/`app.js`/`bridge_client.js`, `index.html`,
`.claude/rules/security-levels.md`) contra `arquitectura-019.md` §1-§11 completo (addendum
incluido), no contra el resumen de `desarrollo-log-019.md`. Compilación (`py_compile`) OK.
Suite completa ejecutada 2 veces de forma independiente: 2 failed/514 passed (2da corrida) —
mismos 2 fallos pre-existentes de `tests/test_llm_provider.py` (`anthropic` no instalado) ya
documentados por baseline/dev; 1 fallo adicional en la 1ra corrida
(`tests/test_telegram_confirmation_adapter.py::test_send_message_future_result_timeout_no_impide_seguir_esperando_respuesta`)
confirmado flaky (pasa en aislamiento y en la 2da corrida completa), ajeno a los módulos de
este REQ. Archivos de test propios de REQ-019 ejecutados en aislamiento: 86 passed
(`test_security_manager.py`+`test_security_config.py`), 102 passed (`test_webview_bridge.py`),
14 passed (`test_webview_safe_dom_insertion.py`). `test_register_action_cannot_downgrade_red`
(CA-25) idéntico al documentado por baseline, PASS.

2026-08-20 | orion-tester | Verificación independiente adicional (21 checks propios, 0 FAIL,
scripts standalone que NO reutilizan código de los tests de `orion-dev`) sobre los puntos de
mayor riesgo señalados en el handoff | (1) CA-02/CA-03: acción YELLOW real + override GREEN
inyectado → `classify_action` sigue YELLOW, `require_confirmation()` sigue preguntando
(confirmado con `input()` real); mismo patrón sobre `format_disk` (RED real) → sigue RED,
bloqueado sin PIN. CA-06: 4 escenarios de corrupción real de archivo escritos a disco de
verdad (bytes no-UTF-8, JSON inválido, valor de nivel inválido, no-dict) leídos con
`load_security_overrides()` real — ninguno crashea; `_load_and_parse_overrides()` (la función
que corre dentro de `SecurityManager.__new__()`, el punto que la 1ra auditoría de seguridad
marcó bloqueante) tampoco propaga la excepción. (2) CA-08: las 10 claves RED reales
(extraídas del propio `security_manager._base_levels`, no copiadas a mano) no intersectan con
`_SECURITY_ROWS_V1`. CA-16: forzando `open_chrome` a YELLOW real vía `register_action()` real,
`options == ["yellow"]`; en su estado real (GREEN), `options == ["green","yellow"]`, nunca
incluye `"red"`. Coexistencia REQ-018/REQ-019: `CHANNEL_ACTION_EXCEPTIONS` y
`_config_overrides`/`_base_levels` confirmadas sin overlap de estado ni de fase de
evaluación (una decide el nivel, la otra si ese nivel alcanza para el canal). (3) CA-21:
`Bridge` real instanciado con `QApplication`/`QThreadPool.globalInstance()` reales (no el
`run_async` síncrono simulado de `tests/test_webview_bridge.py`) — intento directo de bajar
`open_chrome` de yellow a green vía `save_security_override()` (bypaseando el `<select>`)
rechazado, 0 escrituras a disco, `security_overrides.json` real del proyecto no tocado
(confirmado con `git status`) | Ver `pruebas/test-results-019.md`, secciones dedicadas, para
el detalle completo de cada script.

2026-08-20 | orion-tester | Desviación de `_on_security_override_error(row_id, message)`
evaluada como justificada, correctamente implementada y testeada | La propia
`arquitectura-019.md` §3.3 dejaba el mecanismo exacto de error abierto explícitamente;
confirmado contra `ui/gui_workers.py::run_async()` real que `on_error` solo recibe `str(e)`,
nunca `row_id` — sin capturar `row_id` por clausura, `security_override_save_rejected` no
podría llevar el `row_id` correcto y CA-21 quedaría inoperante del lado del frontend (el
`<select>` deshabilitado nunca se reactivaría). Verificado en runtime con el script
independiente de CA-21 (arriba), no solo con los 4 tests dedicados de `orion-dev` (también
ejecutados, PASS).

2026-08-20 | orion-tester | Coexistencia REQ-018/REQ-019 en `core/security_manager.py`
confirmada estructuralmente independiente, no solo porque los tests pasan juntos |
`CHANNEL_ACTION_EXCEPTIONS` (REQ-018, línea 84, `set` a nivel de módulo) se consulta
únicamente dentro de `is_action_allowed()`; `_config_overrides`/`_base_levels` (REQ-019,
atributos de instancia del singleton) se consultan únicamente dentro de
`register_action()`/`_merge_with_override()`. Ningún camino de código lee ambas estructuras a
la vez — son fases distintas del mismo pipeline (registro/arranque vs. evaluación de canal en
`require_confirmation()`), confirmado además con `test_ca03_todas_las_yellow_restantes...`
(REQ-018, deriva la lista YELLOW dinámicamente del registro real, ya diseñado para no
desincronizarse si REQ-019 agrega un override) y con verificación en runtime propia.

2026-08-20 | orion-tester | Observación fuera de alcance, no bloqueante para este REQ —
`require_confirmation()` (rama RED sin PIN) usa `print()` con el carácter `⛔`; en una consola
Windows con codepage `cp1252` (no UTF-8) esto lanza `UnicodeEncodeError` fuera del contexto de
`pytest` (que captura stdout de forma segura). Es código pre-existente de REQ-005, no tocado
por REQ-019 (`arquitectura-019.md` §1.3 confirma que `require_confirmation()`/
`classify_action()` no tienen cambios de código en este REQ) — no es un criterio de SPEC-019 ni
una regresión de este REQ, se deja registrado para que quede trazado.

2026-08-20 | orion-tester | `requerimientos.csv` actualizado vía `update-tracker.mjs`
(Estado → EN_QA) | Handoff emitido a `orion-qa`.

## Estado actual
- Estado tracker: EN_QA
- Último agente: orion-tester
- Fecha última actualización: 2026-08-20
- Rama git: `feature/REQ-015-webview-ui` (sin cambios)
- Pendiente inmediato: `@orion-qa` — revisar seguridad/logging/convenciones y emitir
  `qa-audit-019.md`; ver `pruebas/test-results-019.md` para el detalle completo de la
  verificación de los 28 CA.

## Log de transiciones
2026-08-20 | — → NUEVO | orion-coordinador | REQ creado
2026-08-20 | NUEVO → EN_SPEC → SPEC_APROBADO | orion-spec | SPEC-019.md aprobada por Johan tal
cual, sin ajustes; CSV actualizado vía `update-tracker.mjs` (`Aprobacion_SPEC=APROBADO`,
`Tipo_Cambio=FEATURE_NUEVA`); handoff emitido a `orion-baseline`
2026-08-20 | SPEC_APROBADO → EN_ARQUITECTURA | orion-baseline | Baseline documentado (ver
`origen/baseline-019.md`); 0 fallos pre-existentes atribuibles a las zonas que este REQ toca (2
fallos pre-existentes ajenos en `tests/test_llm_provider.py`, falta paquete `anthropic`); CSV
actualizado vía `update-tracker.mjs`; handoff emitido a `orion-architect`
2026-08-20 | EN_ARQUITECTURA → ARQUITECTURA_APROBADA | orion-architect | Propuesta técnica
entregada (`propuestas/arquitectura-019.md`, 28 CA cubiertos); desvío de persistencia
(`security_overrides.json` separado de `config.json`) aprobado por Johan vía
`orion-coordinador`; CSV actualizado vía `update-tracker.mjs`; handoff emitido a
`orion-security` (NO a `orion-dev` — CA-28, paso obligatorio no negociable fijado en
SPEC-019)
2026-08-20 | ARQUITECTURA_APROBADA (auditoría ❌ REQUIERE CAMBIOS → addendum) | orion-security
→ orion-architect | `security-audit-019.md`: 1 hallazgo bloqueante (excepción no capturada,
riesgo de crash de arranque completo) + 2 no bloqueantes; `orion-architect` respondió con
addendum §11 en `arquitectura-019.md` (sin reabrir el diseño central); CSV sin cambios
(sin columna de auditoría de seguridad); handoff de vuelta a `orion-security` para
re-chequeo del addendum
2026-08-20 | ARQUITECTURA_APROBADA → ARQUITECTURA_APROBADA (sin cambio de estado) | orion-security |
Auditoría entregada (`pruebas/security-audit-019.md`) — Veredicto: ❌ REQUIERE CAMBIOS (1 hallazgo
bloqueante: Hallazgo A, manejo de excepciones incompleto en `core/security_config.py::load_security_overrides()`
puede crashear el arranque completo ante un archivo corrupto con bytes no-UTF-8; 2 hallazgos no
bloqueantes: Hallazgo B nombre indefinido en `bridge.py` con efecto fail-closed, Hallazgo C
autobloqueo posible por salto directo a Rojo en v1); CSV no tocado (no corresponde a este paso);
handoff emitido a `orion-architect` con el detalle específico del Hallazgo A
2026-08-20 | ARQUITECTURA_APROBADA → ARQUITECTURA_APROBADA (sin cambio de estado) | orion-architect
→ orion-security | Addendum §11 agregado a `arquitectura-019.md` respondiendo los 3 hallazgos
(A, B, C) sin reabrir §1-§10; CSV no tocado; handoff de vuelta a `orion-security` para re-chequeo
2026-08-20 | ARQUITECTURA_APROBADA → ARQUITECTURA_APROBADA (sin cambio de estado) | orion-security |
Re-auditoría del addendum §11 (`pruebas/security-audit-019.md`, sección "Re-auditoría — 2da
pasada") — Veredicto: ✅ APROBADO. Los 3 hallazgos (A bloqueante, B y C no bloqueantes) quedan
cerrados; sin hallazgo bloqueante nuevo; 3 notas no bloqueantes dejadas para `orion-dev`/
`orion-tester` (py_compile de `core/security_config.py`, limpieza de import redundante en
`bridge.py`, corrección del valor esperado de CA-16 en "Pruebas sugeridas" pre-addendum: `["yellow"]`
en vez de `["yellow","red"]`); CSV no tocado (sin columna de auditoría de seguridad); handoff
emitido a `@orion-dev`
2026-08-20 | ARQUITECTURA_APROBADA → EN_PRUEBAS | orion-dev | Implementación completa de
`arquitectura-019.md` §1-§11 (`propuestas/desarrollo-log-019.md`); las 3 notas no
bloqueantes del handoff de `orion-security` resueltas; 480 passed / 2 failed
(pre-existentes, ajenos) en la suite completa; CSV actualizado vía `update-tracker.mjs`
(Estado → EN_PRUEBAS); NO se ejecutó `git commit`; handoff emitido a `orion-tester`
2026-08-20 | EN_PRUEBAS → EN_QA | orion-tester | 28/28 CA de SPEC-019 en PASS
(`pruebas/test-results-019.md`); suite completa sin regresiones atribuibles a REQ-019 (2
fallos pre-existentes ajenos, 1 fallo flaky descartado); 21 checks de verificación
independiente adicional (0 FAIL) sobre CA-02/CA-03/CA-06/CA-08/CA-16/CA-21; desviación de
`_on_security_override_error()` evaluada como justificada; coexistencia REQ-018/REQ-019
confirmada estructuralmente independiente; CSV actualizado vía `update-tracker.mjs`; handoff
emitido a `orion-qa`
