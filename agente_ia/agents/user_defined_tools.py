"""
agents/user_defined_tools.py
Las tres capacidades que hasta ahora SOLO existian como resolvers delante del modelo:
rutinas, comandos aprendidos y el planificador de Autopilot.

Al invertir el orden de resolucion —el modelo lee primero y decide el, ver
`core/resolution.py::RESOLVERS`— esos tres caminos se quedaban sin ninguna puerta de
entrada: nadie los llamaba y el usuario perdia lo que habia configurado. Aca dejan de
depender de que una heuristica reconozca la frase antes que nadie, y pasan a ser
herramientas que el modelo elige como cualquier otra.

Nivel de riesgo: GREEN en las tres, mismo criterio que el tool `dispatcher`
(`agents/skill_tools.py`) — no son acciones en si, son despachadores. El gate real ocurre
adentro, por accion: `execute_routine_actions()` y `TaskExecutor.execute()` pasan cada paso
por `agents/action_registry.py::execute_action()`, y el callback de los comandos aprendidos
hace `classify_command() -> dispatch()`, que es el otro punto de gate del sistema. Marcarlas
YELLOW pediria una confirmacion por el envoltorio y otra por cada accion de adentro.
"""

import logging
from typing import Any, Dict

from agents.tool_registry import ToolSpec, register_tool
from core.security_manager import RiskLevel

logger = logging.getLogger(__name__)


# ── Rutinas definidas por el usuario ────────────────────────────────

def _routine_list_invoke(params: Dict[str, Any]) -> str:
    from learning.routines_engine import _load_routines

    rutinas = _load_routines()
    if not rutinas:
        return "El usuario no tiene ninguna rutina definida."

    lineas = []
    for nombre, rutina in rutinas.items():
        acciones = rutina.get("actions", [])
        disparadores = rutina.get("triggers", [nombre])
        lineas.append(
            f"- {nombre}: {len(acciones)} accion(es). Se la nombra como: "
            f"{', '.join(str(d) for d in disparadores)}"
        )
    return "Rutinas definidas por el usuario:\n" + "\n".join(lineas)


def _routine_run_invoke(params: Dict[str, Any]) -> str:
    from learning.routines_engine import execute_routine_actions, get_routine

    nombre = str(params.get("name", "")).strip()
    if not nombre:
        return "Falta el nombre de la rutina."

    rutina = get_routine(nombre)
    if rutina is None:
        from learning.routines_engine import list_routine_names

        disponibles = list_routine_names()
        return (f"No existe una rutina llamada '{nombre}'. "
                f"Las que hay: {', '.join(disponibles) if disponibles else 'ninguna'}.")

    acciones = rutina.get("actions", [])
    if not acciones:
        return f"La rutina '{nombre}' no tiene ninguna accion configurada."

    detalle = execute_routine_actions(acciones, channel=params.get("channel"))
    return f"Rutina '{nombre}' ejecutada:\n{detalle}"


# ── Comandos que el usuario le enseño ───────────────────────────────

def _learned_list_invoke(params: Dict[str, Any]) -> str:
    from learning.command_learning import get_custom_commands

    comandos = get_custom_commands()
    if not comandos:
        return "El usuario no le enseño ningun comando."

    return "Comandos que el usuario enseño:\n" + "\n".join(
        f"- '{frase}': {len(acciones)} accion(es)" for frase, acciones in comandos.items()
    )


def _learned_run_invoke(params: Dict[str, Any]) -> str:
    """Ejecuta un comando aprendido.

    El callback que corre cada accion es PRIVADO de esta funcion y siempre hace
    `classify_command() -> dispatch()`: es la misma mitigacion que ya aplicaba
    `core/resolution.py::_try_learned()` (Hallazgo 1.7 de orion-security). Que el gate no
    dependa de que un caller futuro sea disciplinado sigue valiendo igual ahora que quien
    llama es el modelo.
    """
    from core.security_manager import ActionDenied
    from learning.command_learning import run_custom_command

    frase = str(params.get("phrase", "")).strip()
    if not frase:
        return "Falta la frase del comando aprendido."

    resultado = {"pasos": [], "denegado": False}

    def _ejecutar(texto_accion: str) -> None:
        from intent.classifier import classify_command
        from router.dispatcher import dispatch

        intent, intent_params = classify_command(texto_accion)
        intent_params["channel"] = params.get("channel")
        try:
            resultado["pasos"].append(str(dispatch(intent, intent_params)))
        except ActionDenied as e:
            resultado["denegado"] = True
            resultado["pasos"].append(f"accion denegada: {e.reason or 'denegada'}")

    if not run_custom_command(frase, _ejecutar):
        from learning.command_learning import get_custom_commands

        conocidas = list(get_custom_commands())
        return (f"No hay ningun comando aprendido para '{frase}'. "
                f"Los que hay: {', '.join(conocidas) if conocidas else 'ninguno'}.")

    return "\n".join(resultado["pasos"]) or "El comando aprendido no produjo salida."


# ── Autopilot: planificar y ejecutar una tarea de varios pasos ──────

def _autopilot_invoke(params: Dict[str, Any]) -> str:
    from agents.task_executor import TaskExecutor
    from agents.task_planner import TaskPlanner

    instruccion = str(params.get("task", "")).strip()
    if not instruccion:
        return "Falta la instruccion a planificar."

    plan = TaskPlanner().generate_plan(instruccion)
    if not plan:
        # Que no haya plan NO es un error: el planificador solo reconoce las plantillas que
        # tiene. Se dice claro para que el modelo resuelva por su cuenta en vez de insistir.
        return ("Autopilot no tiene ninguna plantilla para eso. "
                "Resuelvelo con las otras herramientas o respondiendo directamente.")

    return TaskExecutor().execute(plan, channel=params.get("channel"))


# ── Capacidades declaradas en system_capabilities.json ──────────────

def _capability_invoke(params: Dict[str, Any]) -> str:
    from os_integration.capabilities_router import execute_capability, match_capability

    texto = str(params.get("text", "")).strip()
    if not texto:
        return "Falta la frase de la capacidad."

    cap = match_capability(texto)
    if cap is None:
        return "Ninguna capacidad declarada coincide con eso."
    return execute_capability(cap, channel=params.get("channel"))


def register_user_defined_tools() -> None:
    """Registra las cinco herramientas. Se llama una vez al arrancar, como el resto."""
    register_tool(ToolSpec(
        name="routine_list",
        description=(
            "Lista las rutinas que el usuario definio, con las frases por las que suele "
            "nombrarlas. Consultala si el usuario menciona algo que suena a una rutina suya."
        ),
        parameters_schema={"type": "object", "properties": {}},
        risk_level=RiskLevel.GREEN,
        invoke=_routine_list_invoke,
    ))
    register_tool(ToolSpec(
        name="routine_run",
        description=(
            "Ejecuta una rutina definida por el usuario (una secuencia de acciones que el "
            "guardo con un nombre, por ejemplo 'modo trabajo')."
        ),
        parameters_schema={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Nombre de la rutina."}},
            "required": ["name"],
        },
        risk_level=RiskLevel.GREEN,
        invoke=_routine_run_invoke,
    ))
    register_tool(ToolSpec(
        name="learned_command_list",
        description="Lista los comandos que el usuario le enseño al agente.",
        parameters_schema={"type": "object", "properties": {}},
        risk_level=RiskLevel.GREEN,
        invoke=_learned_list_invoke,
    ))
    register_tool(ToolSpec(
        name="learned_command_run",
        description=(
            "Ejecuta un comando que el usuario enseño previamente, identificandolo por la "
            "frase con la que lo guardo."
        ),
        parameters_schema={
            "type": "object",
            "properties": {"phrase": {"type": "string", "description": "Frase del comando."}},
            "required": ["phrase"],
        },
        risk_level=RiskLevel.GREEN,
        invoke=_learned_run_invoke,
    ))
    register_tool(ToolSpec(
        name="autopilot_run",
        description=(
            "Planifica y ejecuta una tarea de varios pasos con las plantillas de Autopilot "
            "(por ejemplo redactar algo y guardarlo en un archivo). Si no hay plantilla "
            "para lo pedido, lo dice y no ejecuta nada."
        ),
        parameters_schema={
            "type": "object",
            "properties": {"task": {"type": "string", "description": "La tarea en lenguaje natural."}},
            "required": ["task"],
        },
        risk_level=RiskLevel.GREEN,
        invoke=_autopilot_invoke,
    ))

    # Solo si hay capacidades declaradas. `system_capabilities.json` es opcional y en la
    # mayoria de las instalaciones no existe: registrar el tool igual sumaria una linea
    # mas al prompt de CADA turno para algo que no puede hacer nada. Cuando el archivo
    # existe, la capacidad sigue alcanzable — que es lo que habia que no perder.
    try:
        from os_integration.capabilities_router import _CAPABILITIES

        hay_capacidades = bool(_CAPABILITIES)
    except Exception as e:
        logger.debug(f"No se pudieron leer las capacidades declaradas: {e}")
        hay_capacidades = False

    if hay_capacidades:
        register_tool(ToolSpec(
            name="capability_run",
            description=(
                "Ejecuta una capacidad del sistema declarada en system_capabilities.json, "
                "identificandola por la frase con la que esta declarada."
            ),
            parameters_schema={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "La frase del usuario."}},
                "required": ["text"],
            },
            risk_level=RiskLevel.GREEN,
            invoke=_capability_invoke,
        ))
