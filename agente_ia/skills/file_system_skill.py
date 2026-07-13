import re
from typing import Dict, List, Tuple, Any
from skills.base_skill import BaseSkill
from os_integration import file_system

class FileSystemSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "FileSystemSkill"
        
    @property
    def description(self) -> str:
        return "Administra carpetas y archivos locales (explorar, listar, crear)."

    def get_intents(self) -> List[str]:
        return ["OPEN_FOLDER", "LIST_FILES", "CREATE_FILE"]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            # OPEN_FOLDER
            ("abre la carpeta de descargas", "OPEN_FOLDER"), ("abre mis documentos", "OPEN_FOLDER"),
            ("muestra el directorio de musica", "OPEN_FOLDER"), ("ve a mi escritorio", "OPEN_FOLDER"),
            ("abre la carpeta videos", "OPEN_FOLDER"), ("ir a mis documentos", "OPEN_FOLDER"),
            ("navega a mis descargas", "OPEN_FOLDER"),
            # LIST_FILES
            ("que archivos hay en mi escritorio", "LIST_FILES"), ("lista los archivos de la carpeta", "LIST_FILES"),
            ("muestrame que hay aqui", "LIST_FILES"), ("ver archivos", "LIST_FILES"),
            ("lista mis descargas", "LIST_FILES"), ("que hay en mis documentos", "LIST_FILES"),
            ("ver contenido de la carpeta", "LIST_FILES"),
            # CREATE_FILE
            ("crea un archivo llamado notas", "CREATE_FILE"), ("haz un archivo de texto", "CREATE_FILE"),
            ("crea el archivo prueba", "CREATE_FILE"), ("nuevo archivo", "CREATE_FILE"),
            ("creame un archivo", "CREATE_FILE"), ("crea un documento llamado informe", "CREATE_FILE"),
        ]

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        params = {}
        if intent == "OPEN_FOLDER":
            match = re.search(r'\b(abre|muestra|ve a)\s+(?:la\s+carpeta(?: de)?\s+|el\s+directorio(?: de)?\s+|mis\s+|mi\s+)?(.*)', text)
            if match and match.group(2): params["path"] = match.group(2).strip()
            else: params["path"] = "."
        elif intent == "LIST_FILES":
            match = re.search(r'\b(en\s+|de\s+)(?:la\s+carpeta\s+|mi\s+|mis\s+)?(.*)', text)
            if match and match.group(2): params["path"] = match.group(2).strip()
            else: params["path"] = "."
        elif intent == "CREATE_FILE":
            match = re.search(r'\b(?:llamado\s+|archivo(?: de texto)?\s+)(.*)', text)
            if match and match.group(1): params["filename"] = match.group(1).strip()
            else: params["filename"] = "documento_nuevo.txt"
        return params

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        if intent == "OPEN_FOLDER":
            return file_system.open_folder(params.get("path", "."))
        elif intent == "LIST_FILES":
            return file_system.list_files(params.get("path", "."))
        elif intent == "CREATE_FILE":
            return file_system.create_file(params.get("filename", "documento.txt"))
        return "Acción de archivo no encontrada."
