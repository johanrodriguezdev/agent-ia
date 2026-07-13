from typing import Dict, List, Tuple, Any
from skills.base_skill import BaseSkill
from executor import system_action_handlers

class InfoSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "InfoSkill"
        
    @property
    def description(self) -> str:
        return "Provee información vital del hardware y sistema (CPU, RAM, Specs)."

    def get_intents(self) -> List[str]:
        return ["SYSTEM_INFO", "CPU_INFO", "RAM_INFO"]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            # SYSTEM_INFO
            ("informacion del sistema", "SYSTEM_INFO"), ("que sistema operativo tengo", "SYSTEM_INFO"),
            ("dime info de mi pc", "SYSTEM_INFO"), ("specs de mi pc", "SYSTEM_INFO"),
            ("como esta mi computadora", "SYSTEM_INFO"),
            # CPU_INFO
            ("cuanto cpu estoy usando", "CPU_INFO"), ("uso del procesador", "CPU_INFO"),
            ("como esta mi cpu", "CPU_INFO"), ("cuantos nucleos tiene mi procesador", "CPU_INFO"),
            ("info del cpu", "CPU_INFO"),
            # RAM_INFO
            ("cuanta ram tengo", "RAM_INFO"), ("uso de memoria ram", "RAM_INFO"),
            ("como esta la ram", "RAM_INFO"), ("cuanta memoria disponible tengo", "RAM_INFO"),
            ("info de la memoria", "RAM_INFO"), ("cuanto ram esta libre", "RAM_INFO"),
        ]

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        return {}

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        if intent == "SYSTEM_INFO":
            return system_action_handlers.handle_system_info({})
        elif intent == "CPU_INFO":
            return system_action_handlers.handle_cpu_info({})
        elif intent == "RAM_INFO":
            return system_action_handlers.handle_ram_info({})
        return "No tengo esa información del sistema."
