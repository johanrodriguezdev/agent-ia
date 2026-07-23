import os
import importlib.util
import inspect
from typing import Dict, List, Tuple
from skills.base_skill import BaseSkill
from core.base_agent import AgentTool


class SkillManager:
    def __init__(self):
        self.skills: List[BaseSkill] = []
        self._intent_to_skill: Dict[str, BaseSkill] = {}
        self.load_all_skills()

    def load_all_skills(self):
        self.skills.clear()
        self._intent_to_skill.clear()

        skills_dir = os.path.dirname(__file__)
        if not os.path.exists(skills_dir):
            return

        for filename in os.listdir(skills_dir):
            if filename.endswith(".py") and filename not in ("__init__.py", "base_skill.py", "skill_manager.py"):
                module_name = f"skills.{filename[:-3]}"
                filepath = os.path.join(skills_dir, filename)

                spec = importlib.util.spec_from_file_location(module_name, filepath)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if inspect.isclass(attr) and issubclass(attr, BaseSkill) and attr is not BaseSkill:
                            try:
                                skill_instance = attr()
                                self.register_skill(skill_instance)
                            except Exception as e:
                                print(f"[SkillManager] Falla al inicializar {attr_name}: {e}")

    def register_skill(self, skill: BaseSkill):
        self.skills.append(skill)
        for intent in skill.get_intents():
            self._intent_to_skill[intent] = skill
        print(f"[SkillManager] Skill cargada: {skill.name} con intents: {skill.get_intents()}")

    def get_all_training_data(self) -> List[Tuple[str, str]]:
        data = []
        for skill in self.skills:
            data.extend(skill.get_training_data())
        return data

    def extract_params(self, intent: str, text: str) -> dict:
        skill = self._intent_to_skill.get(intent)
        if skill:
            return skill.extract_params(intent, text)
        return {}

    def handles_intent(self, intent: str) -> bool:
        return intent in self._intent_to_skill

    def execute(self, intent: str, params: dict) -> str:
        skill = self._intent_to_skill.get(intent)
        if skill:
            return skill.execute(intent, params)
        return f"Error: No hay una Skill registrada para manejar la intención '{intent}'."

    def get_all_skills(self) -> List[BaseSkill]:
        return self.skills

    def _discover_skills(self):
        self.load_all_skills()

    def get_agent_tools(self) -> List[AgentTool]:
        tools = []
        for skill in self.skills:
            for intent in skill.get_intents():
                tool = AgentTool(
                    name=f"skill_{intent.lower()}",
                    description=f"{skill.name}: {skill.description}",
                    function=lambda params, s=skill, i=intent: s.execute(i, params)
                )
                tools.append(tool)
        return tools


skill_manager = SkillManager()
