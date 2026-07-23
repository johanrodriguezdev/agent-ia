import subprocess
import os
import pyautogui
import time

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.5 

# Mapa de nombres comunes a ejecutables para apertura directa
_APP_EXEC_MAP = {
    "chrome":           "chrome",
    "google chrome":    "chrome",
    "edge":             "msedge",
    "microsoft edge":   "msedge",
    "firefox":          "firefox",
    "notepad":          "notepad",
    "bloc de notas":    "notepad",
    "calculadora":      "calc",
    "calculator":       "calc",
    "explorador":       "explorer",
    "explorador de archivos": "explorer",
    "paint":            "mspaint",
    "word":             "winword",
    "excel":            "excel",
    "powerpoint":       "powerpnt",
    "cmd":              "cmd",
    "terminal":         "cmd",
    "símbolo del sistema": "cmd",
    "spotify":          "spotify",
    "discord":          "discord",
    "whatsapp":         "whatsapp",
    "outlook":          "outlook",
}

def _try_direct_open(app_name: str) -> str | None:
    """Intenta abrir la aplicación con subprocess.Popen directamente (sin simulación)."""
    name = app_name.lower().strip()
    exec_name = _APP_EXEC_MAP.get(name)
    if not exec_name:
        return None
    try:
        subprocess.Popen([exec_name], shell=True)
        return f"{app_name} abierto directamente."
    except Exception:
        return None

def open_application(app_name: str) -> str:
    """Abre una aplicación: primero intento directo, después simulación como respaldo."""
    result = _try_direct_open(app_name)
    if result:
        return result
    try:
        pyautogui.press('win')
        time.sleep(0.5)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.5)
        pyautogui.press('enter')
        return f"Aplicación '{app_name}' abierta."
    except Exception as e:
        return f"Hubo un fallo abriendo la aplicación: {e}"

def click_position(x: int, y: int) -> str:
    """Haz que el puntero del mouse vaya físicamente al punto y haga un clic izquierdo."""
    try:
        pyautogui.click(x=x, y=y)
        return f"He hecho clic en las coordenadas ({x}, {y})."
    except Exception as e:
        return f"Error ejecutando el clic: {e}"

def type_text(text: str) -> str:
    """Escribe rápidamente una serie de teclas en la ventana u originador de enfoque actual."""
    try:
        pyautogui.write(text, interval=0.02)
        return f"Texto escrito en teclado: '{text}'"
    except Exception as e:
        return f"Falló la escritura automatizada: {e}"

def scroll(direction: str, amount: int = 500) -> str:
    """Gira la rueda del mouse emulada."""
    try:
        if direction.lower() in ['arriba', 'up']:
            pyautogui.scroll(amount)
            return "Pantalla desplazada hacia arriba."
        elif direction.lower() in ['abajo', 'down']:
            pyautogui.scroll(-amount) # Los scroll de PyAutoGUI consideran números negativos para down
            return "Pantalla desplazada hacia abajo."
        return "No reconozco esa dirección. Dije arriba o abajo."
    except Exception as e:
        return f"Imposible desplazar pantalla: {e}"
