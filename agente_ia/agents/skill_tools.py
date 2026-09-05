"""
agents/skill_tools.py
Migración de AgentTool (main.py + skill_manager.get_agent_tools()) a ToolSpec (REQ-007,
CA-14 a CA-17). No modifica agents/tool_registry.py ni skills/skill_manager.py — construye
ToolSpec nuevos desde afuera, reutilizando register_tool().
"""
import logging
from typing import Any, Dict

from agents.tool_registry import ToolSpec, register_tool
from core.security_manager import RiskLevel, security_manager
from router.dispatcher import dispatch_as_tool
from skills.base_skill import BaseSkill
from skills.skill_manager import SkillManager

logger = logging.getLogger(__name__)


def register_dispatcher_tool() -> None:
    """CONFIRMADO 5: catch-all, GREEN — el gate real por acción ocurre dentro de
    dispatch() según lo que resuelva classify_command()."""
    register_tool(ToolSpec(
        name="dispatcher",
        description=(
            "Ejecuta comandos directos del sistema cuando ninguna otra herramienta "
            "encaja mejor: abrir apps, controlar volumen, hora, etc. Pásale la frase del "
            "usuario TAL CUAL, sin reformularla ni traducirla a infinitivo."
        ),
        parameters_schema={
            "type": "object",
            "properties": {"task": {"type": "string", "description": (
                "El comando con las palabras EXACTAS del usuario. El clasificador que hay "
                "detrás está entrenado con la forma en que habla la gente ('abre la "
                "calculadora'), no con paráfrasis ('abrir la calculadora de windows')."
            )}},
            "required": ["task"],
        },
        risk_level=RiskLevel.GREEN,
        invoke=dispatch_as_tool,
    ))


#: Intents que el modelo ve como UNA herramienta en vez de como varias.
#:
#: El catalogo llego a 57 herramientas, y con esa lista delante un modelo mediano elige
#: peor: para pausar YouTube se fue a `pc_key` —simular una tecla, amarilla, con
#: confirmacion— teniendo opciones mas directas.
#:
#: Solo se agrupa lo que YA comparte nivel de riesgo. Juntar una verde con una amarilla
#: obligaria a darle a todo el grupo el nivel mas alto, y listar tareas pasaria a pedir
#: confirmacion: la granularidad del gate es por accion y eso no se negocia. Por eso
#: `SYS_POWER_OFF` (amarilla) no entra con las de volumen, ni `CREATE_FLOW` (amarilla) con
#: las de flujos.
#:
#: Cada intent conserva su nombre, su nivel y su gate: lo unico que cambia es cuantas
#: entradas ve el modelo. Se siguen alcanzando por `dispatcher` y por el diccionario de
#: abajo, que traduce la opcion elegida al intent real.
_FAMILIAS: Dict[str, Dict[str, Any]] = {
    "volumen": {
        "descripcion": "Controla el volumen del sistema: subirlo, bajarlo o silenciarlo.",
        "opciones": {
            "subir": "SYS_VOL_UP",
            "bajar": "SYS_VOL_DOWN",
            "silenciar": "SYS_MUTE",
        },
    },
    "info_del_sistema": {
        "descripcion": (
            "Consulta el estado del equipo: resumen general, procesador o memoria."
        ),
        "opciones": {
            "general": "SYSTEM_INFO",
            "procesador": "CPU_INFO",
            "memoria": "RAM_INFO",
        },
    },
    "flujo": {
        "descripcion": (
            "Trabaja con los flujos ya guardados: listarlos, ejecutar uno, reanudarlo o "
            "cancelarlo. Para CREAR un flujo nuevo está `CREATE_FLOW`, aparte."
        ),
        "opciones": {
            "listar": "LIST_FLOWS",
            "ejecutar": "RUN_FLOW",
            "reanudar": "RESUME_FLOW",
            "cancelar": "CANCEL_FLOW",
        },
    },
}

#: Intents que la familia cubre. Se siguen REGISTRANDO igual —con su nombre, su nivel y
#: su gate— y se siguen ejecutando por `execute_tool()`; lo unico que cambia es que no se
#: le muestran sueltos al modelo. Ocultar en la presentacion y no en el registro es lo que
#: mantiene intacto el modelo de seguridad: ninguna accion cambia de nivel ni de camino.
_AGRUPADOS = {i for f in _FAMILIAS.values() for i in f["opciones"].values()}

#: Duplicado exacto: `pc_screenshot` (os_integration) y `TAKE_SCREENSHOT` (skill) hacen lo
#: mismo, y tener las dos delante solo obliga al modelo a elegir entre gemelas. Se deja
#: visible la del sistema operativo, que es la que acompana a las demas de pantalla
#: (`pc_look`, `pc_find`). El intent sigue registrado y alcanzable.
_DUPLICADOS = {"TAKE_SCREENSHOT"}

#: Lo que `core/reasoning_loop.py::_build_tool_list()` NO le ofrece al modelo. Se exporta
#: desde aca para que la lista viva junto a las familias que la explican.
INTENTS_OCULTOS = _AGRUPADOS | _DUPLICADOS


def _make_family_invoke(manager: SkillManager, familia: str):
    """Traduce la opcion elegida al intent real y ejecuta por el camino de siempre."""
    opciones = _FAMILIAS[familia]["opciones"]

    def _invoke(params: Dict[str, Any]) -> str:
        opcion = str(params.get("opcion", "")).strip().lower()
        intent = opciones.get(opcion)
        if intent is None:
            return (f"Opción no válida para {familia}: '{opcion}'. "
                    f"Las que hay: {', '.join(opciones)}.")

        from agents.tool_registry import execute_tool
        from core.security_manager import security_manager as _sm

        # Por `execute_tool()` y con el nombre del INTENT: asi el gate se evalua sobre la
        # accion concreta, con su propio nivel, igual que si el modelo la hubiera llamado
        # suelta. La familia es solo una puerta de entrada, no un permiso agrupado.
        canal = _sm.resolve_channel(params.get("channel"))
        return execute_tool(
            intent,
            {"text": params.get("text", ""), "channel": canal.value,
             "user_id": params.get("user_id")},
            canal, params.get("user_id", "default"),
        )

    return _invoke


def register_family_tools(manager: SkillManager) -> None:
    """Registra una herramienta por familia. Se llama despues de `register_skill_tools()`."""
    for familia, datos in _FAMILIAS.items():
        niveles = {
            security_manager.classify_action(intent)
            for intent in datos["opciones"].values()
        }
        niveles.discard(None)
        if len(niveles) != 1:
            # Fail-closed: una familia con niveles mezclados no se registra. Presentarla
            # como una sola herramienta significaria un solo veredicto del gate para
            # acciones que el sistema clasifico distinto.
            logger.error(
                f"familia '{familia}' con niveles de riesgo mezclados ({niveles}): "
                f"no se agrupa, cada intent sigue suelto"
            )
            _AGRUPADOS.difference_update(datos["opciones"].values())
            continue

        register_tool(ToolSpec(
            name=familia,
            description=datos["descripcion"],
            parameters_schema={
                "type": "object",
                "properties": {
                    "opcion": {
                        "type": "string",
                        "enum": sorted(datos["opciones"]),
                        "description": "Qué hacer.",
                    },
                    "text": {
                        "type": "string",
                        "description": "La frase del usuario, tal cual.",
                    },
                },
                "required": ["opcion"],
            },
            risk_level=niveles.pop(),
            invoke=_make_family_invoke(manager, familia),
        ))


def _make_skill_invoke(skill: BaseSkill, intent: str):
    def _invoke(params: Dict[str, Any]) -> str:
        # CA-16: sin auto-gate acá — execute_tool() ya confirmó antes de llegar a esto.
        text = params.get("text", "")
        exec_params = dict(skill.extract_params(intent, text) or {})
        exec_params["channel"] = params.get("channel")
        exec_params["user_id"] = params.get("user_id")
        exec_params["text"] = text
        return skill.execute(intent, exec_params)
    return _invoke


def register_skill_tools(manager: SkillManager) -> None:
    """CA-14/CA-15/CA-16: un ToolSpec por intent de cada skill cargada. Nombre = Intent
    crudo (CONFIRMADO 4). risk_level derivado de security_manager.classify_action(intent),
    ya poblado por REQ-005 (CA-15) — nunca inventado."""
    count = 0
    for skill in manager.get_all_skills():
        for intent in skill.get_intents():
            risk_level = security_manager.classify_action(intent)
            if risk_level is None:
                # Fail-closed en el arranque: mejor romper visible que registrar un tool
                # con un nivel de riesgo inventado.
                raise RuntimeError(
                    f"Intent '{intent}' de la skill '{skill.name}' no tiene risk_level "
                    f"registrado en security_manager — no se migra sin clasificación explícita."
                )
            register_tool(ToolSpec(
                name=intent,
                description=f"{skill.name}: {skill.description}",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Frase del usuario; se usa para extraer los parámetros reales.",
                        },
                    },
                    "required": ["text"],
                },
                risk_level=risk_level,
                invoke=_make_skill_invoke(skill, intent),
            ))
            count += 1
    logger.info(f"{count} intents de skills migrados a ToolSpec")
