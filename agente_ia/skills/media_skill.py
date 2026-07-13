import re
import urllib.parse
import urllib.request
import webbrowser
from typing import Dict, List, Tuple, Any
from skills.base_skill import BaseSkill

class MediaSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "MediaSkill"
        
    @property
    def description(self) -> str:
        return "Reproduce música o videos automáticamente buscando en YouTube y reproduciendo el primero."

    def get_intents(self) -> List[str]:
        return ["PLAY_MUSIC"]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            ("pon musica de coldplay", "PLAY_MUSIC"),
            ("reproduce la cancion de despacito", "PLAY_MUSIC"),
            ("pon videos de risa en youtube", "PLAY_MUSIC"),
            ("quiero escuchar rock", "PLAY_MUSIC"),
            ("toca musica clasica", "PLAY_MUSIC"),
            ("reproducir metallica", "PLAY_MUSIC"),
            ("ponme la ultima de bad bunny", "PLAY_MUSIC"),
            ("abre un video de programacion", "PLAY_MUSIC"),
            ("reproduce la cancion que te indique en youtube", "PLAY_MUSIC"),
            ("reproduce en youtube", "PLAY_MUSIC"),
            ("pon la cancion en yt", "PLAY_MUSIC"),
            ("busca y reproduce musica", "PLAY_MUSIC"),
            ("pon a reproducir esta cancion", "PLAY_MUSIC"),
        ]

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        params = {}
        if intent == "PLAY_MUSIC":
            # Extraer el query de forma más robusta
            match = re.search(r'\b(?:pon|reproduce|quiero escuchar|toca|reproducir|videos de|musica de|la cancion|en youtube)(?:\s+de|\s+la)?\s+(.*)', text)
            if match and match.group(1):
                clean_query = re.sub(r'(?i)\b(?:en youtube|youtube|yt)\b', '', match.group(1)).strip()
                params["query"] = clean_query if clean_query else text
            else:
                params["query"] = text
        return params

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        if intent == "PLAY_MUSIC":
            query = params.get("query", "")
            if not query:
                return "No especificó qué desea escuchar."

            encoded_query = urllib.parse.quote_plus(query)
            try:
                # Hacer la petición de búsqueda en YouTube
                url = f"https://www.youtube.com/results?search_query={encoded_query}"
                html = urllib.request.urlopen(url)
                video_ids = re.findall(r"watch\?v=(\S{11})", html.read().decode())
                
                if video_ids:
                    # Encontró un video, reproducir el primero exactamente
                    first_video = f"https://www.youtube.com/watch?v={video_ids[0]}"
                    webbrowser.open(first_video)
                    return f"Módulo multimedia activo: Reproduciendo '{query}' automáticamente en YouTube."
                else:
                    # Fallback a la red de búsqueda
                    webbrowser.open(url)
                    return f"No se encontró un video exacto, abriendo resultados de YouTube para '{query}'."
            except Exception as e:
                return f"No pude completar la reproducción por un error de red: {str(e)}"
        
        return "Acción multimedia no reconocida."
