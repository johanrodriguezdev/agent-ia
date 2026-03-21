import pyautogui
import time

# Configuración de seguridad: Si algo sale mal, mover rápido el mouse a una esquina aborta la ejecución
pyautogui.FAILSAFE = True
# Breve pausa automática después de cada acción de PyAutoGUI
pyautogui.PAUSE = 0.5 

def open_application(app_name: str) -> str:
    """Invoca una aplicación al abrir el menú inicio de windows y escribir el nombre (simulación humana)."""
    try:
        pyautogui.press('win')
        time.sleep(0.5)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.5)
        pyautogui.press('enter')
        return f"Ejecuté la simulación humana para abrir {app_name}."
    except Exception as e:
        return f"Hubo un fallo automatizando la apertura: {e}"

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
