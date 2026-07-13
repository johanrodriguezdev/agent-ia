import re
import urllib.request
import urllib.parse
from typing import Dict, List, Tuple, Any
from skills.base_skill import BaseSkill

class WeatherSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "WeatherSkill"
        
    @property
    def description(self) -> str:
        return "Obtiene un resumen del clima de una ciudad."

    def get_intents(self) -> List[str]:
        return ["GET_WEATHER"]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            ("como esta el clima en bogota", "GET_WEATHER"),
            ("dime el clima de mexico", "GET_WEATHER"),
            ("va a llover en madrid", "GET_WEATHER"),
            ("cual es la temperatura actual en buenos aires", "GET_WEATHER"),
            ("estado del tiempo en new york", "GET_WEATHER"),
            ("clima hoy", "GET_WEATHER") # Fallback a ciudad por IP
        ]

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        params = {}
        if intent == "GET_WEATHER":
            match = re.search(r'\b(?:en|de)\s+([a-zA-Z\s]+)', text)
            if match and match.group(1):
                params["city"] = match.group(1).strip()
            else:
                params["city"] = "" # Usa la ubicación basada en la IP de origen
        return params

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        if intent == "GET_WEATHER":
            city = params.get("city", "")
            city_path = urllib.parse.quote_plus(city) if city else ""
            try:
                # Usa Wttr.in con el formato 3 (Solo línea de texto corta)
                req = urllib.request.Request(f"https://wttr.in/{city_path}?format=3", headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as response:
                    clima = response.read().decode('utf-8').strip()
                return f"El clima actual para su consulta es: {clima}"
            except Exception as e:
                return "Disculpe, no he podido obtener la información climática en este momento."
        return "Comando de clima no reconocido."
