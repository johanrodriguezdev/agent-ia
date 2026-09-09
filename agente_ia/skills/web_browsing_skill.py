import logging
import re
from typing import Dict, List, Tuple, Any
from skills.base_skill import BaseSkill
from ai.llm_provider import generate_response
from core.address import vocative, vocative_start

logger = logging.getLogger(__name__)

class WebBrowsingSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "WebBrowsingSkill"

    @property
    def description(self) -> str:
        return "Permite al agente visitar URLs en tiempo real (web crawler ligero), extraer su texto y analizar información fresca de internet."

    def get_intents(self) -> List[str]:
        return ["BROWSE_WEB"]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            ("lee esta pagina web", "BROWSE_WEB"),
            ("resume el articulo en esta url", "BROWSE_WEB"),
            ("que dice esta pagina", "BROWSE_WEB"),
            ("entra a este link y dime", "BROWSE_WEB"),
            ("busca en internet esta direccion", "BROWSE_WEB"),
            ("analiza la siguiente url", "BROWSE_WEB"),
            ("ve a la web y lee esto", "BROWSE_WEB"),
            ("extrae la informacion de este link", "BROWSE_WEB")
        ]

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        params = {"prompt": text}
        # Extraer la URL (http/https)
        url_match = re.search(r'(https?://[^\s]+)', text)
        if url_match:
            params["url"] = url_match.group(1)
            params["instruction"] = text.replace(params["url"], "").strip()
        else:
            params["url"] = ""
            params["instruction"] = text
        return params

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        url = params.get("url", "")
        instruction = params.get("instruction", "Resume los puntos clave de este artículo web.")
        
        if not url:
            return f"{vocative_start()}necesito que me proporcione una URL válida (http:// o https://) en su mensaje para poder entrar y leerla."
            
        try:
            # REQ-031 — mismo guard que `leer_pagina()`. Acá además importa que el
            # esquema quede validado: `urlopen()` entiende `file://`, así que un `url` que
            # llegara por un camino que no fuera `extract_params()` podía terminar leyendo
            # un archivo del disco. Hoy no es alcanzable, pero el execute() no se defendía
            # solo, y esa es la clase de suposición que envejece mal.
            from core.http_seguro import DestinoBloqueado, pedir

            try:
                respuesta = pedir(url, timeout=15)
            except DestinoBloqueado as e:
                logger.info(f"navegación rechazada por destino no permitido: {e}")
                return str(e)
            html = respuesta.texto
            
            # Limpiar HTML y extraer solo texto
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                
                # Eliminar tags innecesarios
                for tag in soup(["script", "style", "nav", "footer", "aside", "header"]):
                    tag.extract()
                    
                text_content = soup.get_text(separator=' ')
                text_content = re.sub(r'\s+', ' ', text_content).strip()
            except ImportError:
                # Fallback sin librerías
                text_content = re.sub(r'<[^>]+>', ' ', html)
                text_content = re.sub(r'\s+', ' ', text_content).strip()
                
            # Limite preventivo para no desbordar VRAM (cortamos a 15k letras)
            text_content = text_content[:15000]
            
            if len(text_content) < 50:
                return f"{vocative_start()}pude acceder a la web, pero el contenido está bloqueado o requiere iniciar sesión, por lo que no puedo leer el texto interno."
                
            system_prompt = (
                "Eres el módulo 'Web Crawler' de un agente de IA experto. Acabas de entrar a la URL indicada por el usuario y este es el contenido extraído de la web. "
                "Responde a la orden del usuario sintetizando de manera brillante y estructurada ÚNICAMENTE con la información hallada en el link."
            )
            
            final_prompt = f"Instrucción solicitada: {instruction}\n\nContenido extraído de ({url}):\n\n{text_content}"
            messages = [{"role": "user", "content": final_prompt}]
            
            # `tarea="ligera"`: resumir una página ya descargada es justo lo que un modelo
            # pequeño hace bien — el contenido va en el prompt, no hace falta que el modelo
            # lo sepa de antes.
            ai_response = generate_response(messages, system_prompt, tarea="ligera")
            
            return f"*Crawler Web Activado* 🌐\n\n{ai_response}"
            
        except Exception as e:
            # El detalle al log, una frase al canal. Mismo criterio que REQ-024 y REQ-025:
            # `str(e)` de un fallo de red puede traer rutas internas del disco o la URL
            # entera con sus parámetros, y este skill es alcanzable desde Telegram. La rama
            # de `urllib.error.URLError` se fue con el `urlopen()`: ahora la petición la
            # hace `core/http_seguro.py`, que levanta otras excepciones.
            logger.error(f"fallo navegando '{url[:80]}': {type(e).__name__}: {e}")
            return f"{vocative_start()}no pude acceder a esa página."
