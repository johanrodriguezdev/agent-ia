import subprocess
import os
import pyautogui
import time

# Mapa de nombres amigables a comandos ejecutables de Windows
APP_COMMANDS = {
    "bloc de notas":    "notepad.exe",
    "notepad":          "notepad.exe",
    "calculadora":      "calc.exe",
    "calculator":       "calc.exe",
    "explorador":       "explorer.exe",
    "explorador de archivos": "explorer.exe",
    "paint":            "mspaint.exe",
    "panel de control": "control.exe",
    "administrador de tareas": "taskmgr.exe",
    "task manager":     "taskmgr.exe",
    "cmd":              "cmd.exe",
    "command prompt":   "cmd.exe",
    "terminal":         "cmd.exe",
    "wordpad":          "wordpad.exe",
    "internet explorer": "iexplore.exe",
    "mapa de caracteres": "charmap.exe",
}

def open_notepad() -> str:
    """Abre el Bloc de Notas de Windows."""
    try:
        subprocess.Popen("notepad.exe")
        return "Bloc de notas abierto."
    except Exception as e:
        return f"No pude abrir el Bloc de Notas: {e}"

def open_file_explorer(path: str = "") -> str:
    """Abre el Explorador de Windows, opcionalmente en una carpeta específica."""
    try:
        if path and os.path.exists(path):
            subprocess.Popen(f'explorer.exe "{path}"')
            return f"Explorador de archivos abierto en: {path}"
        else:
            subprocess.Popen("explorer.exe")
            return "Explorador de archivos abierto."
    except Exception as e:
        return f"No pude abrir el Explorador: {e}"

def open_app_by_name(app_name: str) -> str:
    """Busca la aplicación en el mapa de comandos conocidos y la ejecuta."""
    name_lower = app_name.lower().strip()
    
    # Búsqueda directa en el diccionario
    cmd = APP_COMMANDS.get(name_lower)
    
    # Búsqueda parcial (si no hay coincidencia exacta)
    if not cmd:
        for key, val in APP_COMMANDS.items():
            if name_lower in key or key in name_lower:
                cmd = val
                break
    
    if cmd:
        try:
            subprocess.Popen(cmd)
            return f"Aplicación '{app_name}' iniciada correctamente."
        except Exception as e:
            return f"Error al iniciar '{app_name}': {e}"
    
    # Si no está en el mapa, intentar abrir con el menú de inicio de Windows
    try:
        pyautogui.hotkey('win')
        time.sleep(0.8)
        pyautogui.typewrite(app_name, interval=0.05)
        time.sleep(1.0)
        pyautogui.press('enter')
        return f"Búsqueda de '{app_name}' lanzada desde el menú de inicio."
    except Exception as e:
        return f"No reconozco '{app_name}' y tampoco pude buscarlo: {e}"

def write_text_to_active_app(text: str) -> str:
    """Escribe texto automáticamente en la aplicación activa usando pyautogui."""
    try:
        time.sleep(0.5)
        pyautogui.write(text, interval=0.04)
        return f"Texto escrito automáticamente en la aplicación activa."
    except Exception as e:
        return f"Error al escribir: {e}"

def close_active_window() -> str:
    """Cierra la ventana actualmente activa usando Alt+F4."""
    try:
        pyautogui.hotkey('alt', 'f4')
        return "Ventana activa cerrada."
    except Exception as e:
        return f"No pude cerrar la ventana: {e}"

def minimize_window() -> str:
    """Minimiza la ventana activa."""
    try:
        pyautogui.hotkey('win', 'down')
        return "Ventana minimizada."
    except Exception as e:
        return f"Error al minimizar: {e}"

def maximize_window() -> str:
    """Maximiza la ventana activa."""
    try:
        pyautogui.hotkey('win', 'up')
        return "Ventana maximizada."
    except Exception as e:
        return f"Error al maximizar: {e}"
