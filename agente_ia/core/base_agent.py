import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Callable, Any

from core.security_manager import ActionDenied

logger = logging.getLogger(__name__)

class AgentTool:
    def __init__(self, name: str, description: str, function: Callable):
        self.name = name
        self.description = description
        self.function = function

    def execute(self, params: dict) -> str:
        try:
            result = self.function(params)
            logger.info(f"AgentTool '{self.name}' ejecutado exitosamente")
            return str(result)
        except Exception as e:
            logger.error(f"AgentTool '{self.name}' falló: {e}")
            return f"Error en herramienta '{self.name}': {str(e)[:100]}"


class BaseAgent(ABC):
    def __init__(self, name: str, description: str, system_prompt: str):
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.tools: List[AgentTool] = []

    @abstractmethod
    def can_handle(self, task: str) -> float:
        pass

    @abstractmethod
    def execute(self, task: str, context: dict = None) -> str:
        pass

    def add_tool(self, tool: AgentTool):
        self.tools.append(tool)

    def communicate(self, result: str, target_agent_name: str) -> dict:
        return {
            "from": self.name,
            "to": target_agent_name,
            "result": result
        }


class DynamicAgentFactory:
    def __init__(self, llm_provider=None):
        self._llm = llm_provider
        self._agent_cache: Dict[str, BaseAgent] = {}

    def create_agent(self, task_description: str, available_tools: List[AgentTool]) -> BaseAgent:
        import hashlib
        task_hash = hashlib.md5(task_description.encode()).hexdigest()[:8]
        if task_hash in self._agent_cache:
            logger.info(f"Agente reutilizado de cache para tarea: {task_description[:50]}")
            return self._agent_cache[task_hash]

        name = f"Agent_{task_hash}"
        description = f"Agente especializado en: {task_description[:100]}"
        prompt = self._generate_prompt(task_description, available_tools)

        agent = _DynamicAgentInstance(name, description, prompt, available_tools)
        self._agent_cache[task_hash] = agent
        logger.info(f"Agente dinámico creado: {name} para: {task_description[:50]}")
        return agent

    def _generate_prompt(self, task: str, tools: List[AgentTool]) -> str:
        tool_list = "\n".join(f"- {t.name}: {t.description}" for t in tools)
        return (
            f"Eres un agente especializado de Noddoo.\n\n"
            f"Tu tarea: {task}\n\n"
            f"Herramientas disponibles:\n{tool_list}\n\n"
            f"Responde de manera concisa y directa. Si no puedes completar la tarea, "
            f"indica claramente qué información adicional necesitas."
        )

    def clear_cache(self):
        self._agent_cache.clear()
        logger.info("Cache de agentes dinámicos limpiado")


class _DynamicAgentInstance(BaseAgent):
    def __init__(self, name: str, description: str, system_prompt: str,
                 tools: List[AgentTool]):
        super().__init__(name, description, system_prompt)
        self.tools = tools

    def can_handle(self, task: str) -> float:
        return 0.8

    def execute(self, task: str, context: dict = None) -> str:
        """REQ-007/CA-01: ya no itera `self.tools` en un `for` de orden fijo — delega el
        razonamiento real (decide->ejecuta->evalúa, dirigido por LLM) a
        `core/reasoning_loop.py::run()`. `self.tools` queda como atributo estructural sin
        uso funcional acá: la fuente de tools del loop es siempre
        `agents/tool_registry.py` (ver `core/reasoning_loop.py::_build_tool_list()`), no
        esta lista — se conserva por ser dependencia dura de `skills/skill_manager.py`
        (no modificable en este REQ) y de `tests/test_agents.py` (REQ-002).
        """
        logger.info(f"Agente '{self.name}' delega a reasoning_loop: {task[:80]}")
        context = context or {}
        channel = context.get("channel")
        user_id = context.get("user_id", "default")

        from core.reasoning_loop import run as reasoning_run

        return reasoning_run(task, channel, user_id)
