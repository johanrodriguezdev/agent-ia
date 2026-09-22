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
    """Abre el editor de texto simple del sistema."""
    from os_integration import plataforma

    return plataforma.abrir_aplicacion("bloc de notas") or \
        "No encontré un editor de texto para abrir."

def open_file_explorer(path: str = "") -> str:
    """Abre el explorador de archivos, opcionalmente en una carpeta específica.

    El «cómo» —`explorer.exe` o `xdg-open`— vive en `os_integration/plataforma` (REQ-068).
    """
    from os_integration import plataforma

    return plataforma.abrir_carpeta(path)

def open_app_by_name(app_name: str) -> str:
    """Abre una aplicación por su nombre corriente.

    Primero el catálogo de la plataforma (REQ-068); si no la conoce, se cae al buscador
    del escritorio, que en Windows es el menú de inicio. Ese último recurso es de Windows
    a propósito: teclear en el menú de inicio no tiene un equivalente único en Linux
    —cada escritorio abre su buscador con una tecla distinta— y fingir que sí lo tiene
    sería peor que decir que no se encontró.
    """
    from os_integration import plataforma

    resultado = plataforma.abrir_aplicacion(app_name)
    if resultado:
        return resultado

    if os.name != "nt":
        return (f"No encontré '{app_name}' instalado. Decime el nombre del comando y lo "
                f"abro.")

    # Windows: último recurso, el menú de inicio.
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
