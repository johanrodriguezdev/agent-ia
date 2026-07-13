import os
import re
import time
import tempfile
from typing import Dict, List, Tuple, Any
from skills.base_skill import BaseSkill
from ai.llm_provider import generate_response

class ScreenAnalysisSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "ScreenAnalysisSkill"

    @property
    def description(self) -> str:
        return "Permite capturar la pantalla actual del usuario, usar Visión por Computadora para analizarla y responder preguntas sobre lo que se está mostrando."

    def get_intents(self) -> List[str]:
        return ["ANALYZE_SCREEN"]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            ("analiza mi pantalla", "ANALYZE_SCREEN"),
            ("que hay en mi pantalla", "ANALYZE_SCREEN"),
            ("mira mi pantalla y dime", "ANALYZE_SCREEN"),
            ("lee este error en mi pantalla", "ANALYZE_SCREEN"),
            ("que error sale en mi pantalla", "ANALYZE_SCREEN"),
            ("describe lo que ves en mi pantalla", "ANALYZE_SCREEN"),
            ("analiza el monitor", "ANALYZE_SCREEN"),
            ("dime que codigo tengo en la pantalla", "ANALYZE_SCREEN")
        ]

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        params = {"prompt": text}
        # Intentamos extraer si el usuario hace una pregunta específica sobre la pantalla
        m = re.search(r'(?:dime|lee|que hay|describe|sobre|que error)(.*)', text.lower())
        if m and len(m.group(1).strip()) > 3:
            params["question"] = m.group(1).strip()
        else:
            params["question"] = "Describe detalladamente todo lo que ves en esta pantalla."
        return params

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        question = params.get("question", "Describe la pantalla.")
        
        try:
            import pyautogui
        except ImportError:
            return "Señor, no puedo ver su pantalla porque no tengo instalada la librería 'pyautogui'. (pip install pyautogui)"

        # 1. Tomar captura de pantalla
        time.sleep(1) # Pequeña pausa por si el usuario acaba de cambiar de ventana
        screenshot = pyautogui.screenshot()
        
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False, mode='w', prefix="screen_vision_") as f:
            tmp_path = f.name
            
        screenshot.save(tmp_path)
        
        # 2. Pasarle la imagen al motor LLM de visión
        system_prompt = (
            "Eres el módulo de Visión por Computadora (Computer Vision) de un agente avanzado de IA. "
            "El usuario acaba de pedirte que analices su pantalla en tiempo real. "
            "Tu tarea es mirar la imagen atentamente y responder la pregunta del usuario con la mayor precisión posible. "
            "Si ves código de error, transcríbelo o explícalo. Si ves una interfaz, ubícate en contexto."
        )
        
        messages = [{"role": "user", "content": f"Esta es una captura actual de mi pantalla. Pregunta o tarea: {question}"}]
        
        try:
            # generate_response ya tiene soporte para recibir 'image_path' nativamente
            response = generate_response(messages, system_prompt, image_path=tmp_path)
            
            return f"*Análisis de tu pantalla (Vision AI)* 👁️:\n\n{response}"
            
        except Exception as e:
            return f"Error en mi módulo de visión ocular: {e}"
            
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
