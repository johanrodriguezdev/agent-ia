from typing import Dict, List, Tuple, Any

class BaseSkill:
    """
    Clase base para construir habilidades (skills) modulares.
    Cualquier archivo de Python en la carpeta 'skills/' que herede de esta clase
    será cargado automáticamente al inicio del sistema.
    """
    
    @property
    def name(self) -> str:
        """Nombre identificador único de la skill. Ej: 'BrowserSkill'"""
        raise NotImplementedError

    @property
    def description(self) -> str:
        """Breve descripción para mostrar en el panel de ayuda/skills."""
        return "Sin descripción"

    def get_intents(self) -> List[str]:
        """
        Lista de strings que representan las intenciones que esta skill maneja.
        Ejemplo: ['OPEN_APP', 'CLOSE_APP']
        """
        return []

    def get_training_data(self) -> List[Tuple[str, str]]:
        """
        Provee datos de entrenamiento para el motor de Inteligencia Artificial.
        Cada elemento es una tupla: (texto_de_ejemplo, intent)
        """
        return []

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        """
        Recibe el texto procesado por NLP y extrae entidades si este intent le pertenece.
        """
        return {}

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        """
        Ejecuta la lógica de la skill y retorna el texto que O.R.I.O.N. dirá como respuesta.
        """
        raise NotImplementedError
