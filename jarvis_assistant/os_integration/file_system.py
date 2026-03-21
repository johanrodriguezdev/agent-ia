import os
from pathlib import Path

# Mapa de variables de entorno comunes a sus path de Windows
COMMON_PATHS = {
    "escritorio": "Desktop",
    "documentos": "Documents",
    "descargas": "Downloads",
    "musica": "Music",
    "fotos": "Pictures",
    "imagenes": "Pictures"
}

def resolve_natural_path(path_str: str) -> Path:
    """Intenta convertir un término en lenguaje natural a un directorio nativo."""
    if path_str in COMMON_PATHS:
        return Path.home() / COMMON_PATHS[path_str]
    elif path_str == ".":
        return Path.cwd()
    
    path = Path(path_str)
    if not path.is_absolute() and path_str:
        return Path.home() / path_str 
    return path

def open_folder(path_str: str) -> str:
    path = resolve_natural_path(path_str)

    if path.exists():
         os.startfile(path)
         return f"Carpeta abierta: {path}"
    return f"La carpeta '{path}' no existe."

def list_files(path_str: str) -> str:
     path = resolve_natural_path(path_str)
     
     try:
         files = os.listdir(path)
         if not files:
             return f"La carpeta {path} está vacía."
         return f"Archivos en {path}:\n" + "\n".join([f"- {f}" for f in files])
     except Exception as e:
         return f"Error al listar archivos: {e}"

def create_file(filename: str) -> str:
     try:
         with open(filename, 'w', encoding='utf-8') as f:
             f.write("") # Crea archivo vacío
         return f"Archivo '{filename}' creado exitosamente en {Path.cwd()}."
     except Exception as e:
         return f"Error al crear el archivo: {e}"
