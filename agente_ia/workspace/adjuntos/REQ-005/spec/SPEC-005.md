# SPEC-005 — Deny-list central de acciones Rojo aplicada en código

**Estado:** ⏸️ ESPERANDO VALIDACIÓN
**Categoría:** SEGURIDAD
**Tipo:** SEGURIDAD
**Fecha:** 2026-07-31

## Objetivo
Hoy, el nivel 🔴 Rojo de `.claude/rules/security-levels.md` existe como documentación/regla y
como clasificación en `core/security_manager.py`, pero el bloqueo real es **opt-in**: cada
skill/handler debe decidir por su cuenta llamar a `security_manager.require_confirmation(...)`
antes de actuar. Nada en el punto de despacho intercepta esa llamada automáticamente, y una
acción no registrada se trata como "permitida" (fail-open). REQ-005 crea un punto central que
evalúa y bloquea las acciones Rojo **por código**, sin depender de que cada skill/handler/canal
se autorregule, y cierra el fail-open que permite que una acción no clasificada se ejecute sin
control.

## Alcance
- Incluye:
  - Bloqueo centralizado, por nombre de acción, de las 10 categorías 🔴 Rojo de
    `security-levels.md` (4 ya registradas en código + 6 sin implementación hoy, que se
    pre-registran para quedar bloqueadas por defecto si algún día se implementan).
  - Cambio de comportamiento por defecto: toda acción que llegue al punto central sin
    clasificación explícita (GREEN/YELLOW/RED) se **bloquea** (fail-closed), en vez de
    permitirse como ocurre hoy con `classify_action() -> None`.
  - Protección contra reclasificación: ninguna skill/handler puede degradar en tiempo de
    ejecución una acción ya clasificada como Rojo a un nivel menor.
  - Cobertura de los distintos caminos de ejecución existentes hoy (ver "Módulos afectados") de
    forma que ninguno permita alcanzar una acción Rojo sin pasar por el punto central.
  - Preservar el PIN maestro (`ORION_AUTH_PIN`) como única vía de excepción humana verificada
    para acciones Rojo, solo en canal DESKTOP.
  - Inventario y clasificación explícita de las acciones/intents que hoy existen y no tienen
    ninguna clasificación (para que el cambio a fail-closed no rompa funcionalidad GREEN
    existente).
- No incluye:
  - Sandboxing o interceptación de llamadas al sistema operativo dentro del código Python
    arbitrario que ejecuta `CodeExecutionSkill` (subprocess aislado). El deny-list bloquea por
    **nombre de acción/herramienta** en el punto de despacho, no por comportamiento del código
    que una skill ya autorizada decide ejecutar. Esto queda documentado como riesgo activo para
    REQ-006 (roadmap de la iniciativa OpenClaw-like).
  - Detección semántica de acciones equivalentes con nombre distinto (ej. una skill que
    implementa "borrar toda la base de datos" bajo un nombre de acción no listado). El deny-list
    es por identificador de acción, no por análisis de intención — limitación conocida, documentada
    como riesgo activo.
  - Cambios al nivel 🟡 Amarillo (su UX de confirmación no cambia).
  - Diseño de la ubicación exacta del punto central (dispatcher, security_manager extendido, o
    componente nuevo tipo gateway) — es decisión de `orion-architect`; esta SPEC define el
    comportamiento exigido, no la implementación.

## Módulos afectados
- `core/security_manager.py` — clasificación fail-closed por defecto, registro de las 6 acciones
  Rojo nuevas, protección contra reclasificación de acciones Rojo.
- `router/dispatcher.py` — uno de los puntos de entrada (`dispatch()`, `dispatch_as_tool()`) que
  hoy no pasa por ningún chequeo de seguridad.
- `skills/skill_manager.py` — `execute()` y `get_agent_tools()` son **dos caminos distintos** que
  llegan a `skill.execute()`; `get_agent_tools()` bypasea `dispatch()` por completo (se usa en
  `main.py` para registrar cada skill como `AgentTool` individual en el orquestador). Ambos deben
  quedar cubiertos.
- `executor/handlers.py`, `executor/system_action_handlers.py` — handlers legacy que hoy no
  invocan `security_manager` en absoluto; deben quedar clasificados (mayormente GREEN) para no
  romperse con el fail-closed.
- Todas las skills en `skills/*.py` — inventario de intents/acciones actuales, a cargo de
  `orion-baseline`, para que `orion-architect` diseñe el registro de clasificación sin dejar
  huecos que rompan funcionalidad existente.
- `main.py` — punto donde se registran ambos caminos de `AgentTool` (`dispatcher` y los
  individuales de `skill_manager.get_agent_tools()`).
- `tests/` — nuevos tests de seguridad (simulación de skill/handler que fuerza una acción Rojo,
  fail-closed sobre acción no clasificada, protección contra reclasificación).
- `.claude/rules/security-levels.md` — nota indicando que el nivel Rojo ahora se aplica también
  en código, no solo como regla de proceso.

## Comportamiento actual vs deseado
| Actual | Deseado |
|--------|---------|
| Una skill debe llamar `security_manager.require_confirmation(...)` por su cuenta para que una acción Rojo se evalúe. Si no lo hace (bug u omisión), la acción se ejecuta sin control. | Toda acción pasa obligatoriamente por el punto central antes de ejecutarse, sin importar si la skill/handler lo invoca explícitamente. |
| `classify_action()` devuelve `None` para acciones no registradas, y eso se trata como "permitida". | Una acción sin clasificación explícita se bloquea por defecto (fail-closed). |
| `register_action(name, level)` es público y sin protección: cualquier skill puede reclasificar `"format_disk"` a `GREEN` en tiempo de carga. | Las clasificaciones Rojo no pueden degradarse desde código externo. |
| `skill_manager.get_agent_tools()` expone cada skill como `AgentTool` que llama `skill.execute()` directo, sin pasar por `dispatch()` ni por ningún chequeo. | Ese camino también pasa por el punto central antes de ejecutar la skill. |
| El bloqueo Rojo solo se ha probado para las 4 acciones ya registradas (`format_disk`, `delete_database`, `expose_secrets`, `modify_source_code`); las otras 6 categorías del nivel Rojo no existen en código. | Las 10 categorías quedan pre-registradas como Rojo, bloqueadas por defecto si alguna vez se implementan. |

## Criterios de aceptación
- [ ] Existe un punto central único (ubicación a definir por `orion-architect`) que evalúa el
      nivel de riesgo de una acción antes de que se ejecute, cubriendo los tres caminos
      identificados: `router/dispatcher.py:dispatch()`, `skill_manager.execute()`, y los
      `AgentTool` individuales de `skill_manager.get_agent_tools()`.
- [ ] Las 10 categorías del nivel 🔴 Rojo de `security-levels.md` están registradas como
      `RiskLevel.RED`, incluidas las 6 sin implementación hoy (`send_email_as_user`,
      `post_social_media`, `elevated_system_command`, `install_uninstall_software`,
      `modify_system_env_vars`, `grant_third_party_access`).
- [ ] Toda acción sin clasificación explícita registrada es bloqueada por defecto
      (fail-closed) — test: invocar una acción con nombre inventado/no registrado y verificar
      que el punto central la rechaza en vez de permitirla.
- [ ] Test de resistencia a bug/omisión: una skill/handler simulado que intenta ejecutar
      directamente una acción Rojo (ej. `format_disk`) **sin** llamar por su cuenta a
      `security_manager.require_confirmation()` es bloqueado por el punto central antes de que
      el cuerpo de la acción se ejecute.
- [ ] Test de resistencia a prompt-injection: simular una respuesta de LLM/parámetros de skill
      que incluyen instrucciones o valores diseñados para forzar la ejecución de una acción Rojo
      (incluyendo intentos de pasar un "pin"/"confirmación" falso dentro de los parámetros de la
      acción) y verificar que no logran eludir el punto central.
- [ ] Test de reclasificación: una skill simulada que llama al método de registro de acciones
      intentando bajar el nivel de una acción ya clasificada como Rojo (ej. a `GREEN`) no logra
      alterar su clasificación real.
- [ ] Test por canal: repetir el test de resistencia (acción Rojo forzada) en los 3 canales
      (Telegram, Discord/API, Desktop) y confirmar que ninguno permite la ejecución sin la vía de
      excepción verificada.
- [ ] La única vía de excepción para una acción Rojo es el PIN maestro (`ORION_AUTH_PIN`,
      verificado con `verify_pin()`), exclusivamente en canal DESKTOP. Ningún dato proveniente
      del texto del usuario, parámetros de la skill, o respuesta del LLM sustituye esa
      verificación.
- [ ] Toda acción Rojo bloqueada o autorizada queda registrada en `audit.db`
      (`audit_log`) con timestamp, canal, acción y resultado.
- [ ] Regresión cero: las acciones actualmente GREEN (abrir apps, clima, hora, búsqueda,
      chat, etc. — inventario completo a cargo de `orion-baseline`) siguen ejecutándose sin
      bloqueo ni confirmación tras activar el fail-closed por defecto.
- [ ] Las acciones YELLOW existentes (`shutdown`, `close_app`, `delete_file`, `delete_folder`,
      `execute_code`, `create_skill`, `modify_skill`, `delete_skill`, `send_message`) mantienen
      su comportamiento de confirmación actual sin cambios de UX.
- [ ] Existen tests unitarios en `tests/` que cubren cada una de las 10 categorías Rojo con una
      acción simulada, más el caso de acción no clasificada (fail-closed) y el caso de intento de
      reclasificación.
- [ ] Se ejecuta la suite de tests existente sin nuevos fallos (`pytest tests/`).

## Casos borde
- Canal sin `ORION_AUTH_PIN` configurado (`has_pin() == False`): una acción Rojo debe bloquearse
  sin excepción posible — comportamiento ya correcto hoy, debe preservarse explícitamente.
- Channel spoofing: un skill/handler que reporta `channel="desktop"` en sus parámetros aunque la
  invocación real venga de Telegram/API. El punto central debe determinar el canal real a partir
  de la fuente de la invocación, no confiar en un valor que el skill puede manipular.
- Doble carga del módulo / múltiples instancias del singleton `SecurityManager` (por hot-reload
  de skills vía `skill_creator_skill.py`) no debe permitir resetear o perder las clasificaciones
  Rojo ya registradas.
- Una skill nueva creada dinámicamente por `SkillCreatorSkill` (generada por LLM) que use un
  nombre de acción no registrado cae en fail-closed por defecto — coherente con el criterio de
  fail-closed, pero debe verificarse que no rompe el flujo de creación de skills legítimas
  GREEN/YELLOW (deben clasificarse explícitamente al crearse, no quedar huérfanas).

## Asumidos
- ASUMIDO: la ubicación exacta del punto central (extender `core/security_manager.py`, envolver
  `router/dispatcher.py`, o crear un componente nuevo) la define `orion-architect` — confirmar en
  esa etapa. Esta SPEC exige el comportamiento, no la implementación.
- ASUMIDO: el inventario completo de acciones/intents actualmente sin clasificar (para el
  criterio de regresión cero) lo genera `orion-baseline` antes de que `orion-architect` diseñe el
  registro — confirmar que baseline cubre `executor/handlers.py`,
  `executor/system_action_handlers.py` y todas las skills en `skills/*.py`.
- ASUMIDO: el sandboxing de código arbitrario ejecutado por `CodeExecutionSkill` queda fuera de
  alcance de REQ-005 y se registra como riesgo activo para REQ-006 — confirmado por el humano.
- ASUMIDO: el PIN maestro se mantiene como única vía de excepción verificada para Rojo — confirmado
  por el humano.
