import subprocess

# Diccionario inteligente para mapear lenguaje natural a ejecutables de windows
APP_MAP = {
    "calculadora": "calc",
    "bloc de notas": "notepad",
    "cmd": "cmd",
    "consola": "cmd",
    "navegador": "msedge",
    "internet": "msedge",
    "paint": "mspaint",
    "word": "winword",
    "excel": "excel",
    "chrome": "chrome",
    "spotify": "spotify"
}

def open_application(app_name: str) -> str:
    # Intenta buscar un mapeo, de lo contrario envía el nombre real provisto por el usuario
    executable = APP_MAP.get(app_name.lower(), app_name)
    try:
        # shell=True permite que el sistema corra comandos/paths sin requerir la extensión o ruta explícita del exe.
        subprocess.Popen(executable, shell=True)
        return f"Ejecutando la aplicación '{app_name}'..."
    except Exception as e:
        return f"No se pudo iniciar la aplicación '{app_name}'. Error: {e}"
