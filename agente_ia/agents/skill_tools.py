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
