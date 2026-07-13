import re
from typing import Dict, List, Tuple, Any
from skills.base_skill import BaseSkill
from os_integration import system_ctrl

class SystemControlSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "SystemControlSkill"
        
    @property
    def description(self) -> str:
        return "Controla volumen, apagado de PC y captura de pantalla."

    def get_intents(self) -> List[str]:
        return ["SYS_VOL_UP", "SYS_VOL_DOWN", "SYS_MUTE", "TAKE_SCREENSHOT", "SYS_POWER_OFF", "GET_TIME"]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            # GET_TIME
            ("que hora es", "GET_TIME"), ("dime la hora", "GET_TIME"), 
            ("dame la hora actual", "GET_TIME"), ("a que hora estamos", "GET_TIME"),
            # TAKE_SCREENSHOT
            ("toma una captura", "TAKE_SCREENSHOT"), ("haz una captura de pantalla", "TAKE_SCREENSHOT"),
            ("toma un screenshot", "TAKE_SCREENSHOT"), ("pantallazo", "TAKE_SCREENSHOT"),
            ("toma foto de la pantalla", "TAKE_SCREENSHOT"),
            # SYS_VOL_UP
            ("sube el volumen", "SYS_VOL_UP"), ("ponlo mas fuerte", "SYS_VOL_UP"),
            ("aumenta el volumen", "SYS_VOL_UP"), ("mas volumen por favor", "SYS_VOL_UP"),
            # SYS_VOL_DOWN
            ("baja el volumen", "SYS_VOL_DOWN"), ("mas bajo", "SYS_VOL_DOWN"),
            ("reduce el volumen", "SYS_VOL_DOWN"),
            # SYS_MUTE
            ("silencia el equipo", "SYS_MUTE"), ("ponlo en mute", "SYS_MUTE"),
            ("quita el sonido", "SYS_MUTE"), ("silencio total", "SYS_MUTE"),
            # SYS_POWER_OFF
            ("apaga el ordenador", "SYS_POWER_OFF"), ("apaga la pc", "SYS_POWER_OFF"),
            ("apagar equipo", "SYS_POWER_OFF"), ("apaga la computadora", "SYS_POWER_OFF"),
        ]

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        return {} # No usa parámetros complejos extraídos por regex

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        if intent == "GET_TIME":
            return system_ctrl.get_current_time()
        elif intent == "SYS_VOL_UP":
            return system_ctrl.volume_up()
        elif intent == "SYS_VOL_DOWN":
            return system_ctrl.volume_down()
        elif intent == "SYS_MUTE":
            return system_ctrl.volume_mute()
        elif intent == "TAKE_SCREENSHOT":
            return system_ctrl.take_screenshot()
        elif intent == "SYS_POWER_OFF":
            return system_ctrl.shutdown_pc()
        return "Comando de sistema no válido."
