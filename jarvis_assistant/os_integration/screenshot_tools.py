import pyautogui
import time
from pathlib import Path
from datetime import datetime

def _get_save_dir() -> Path:
    """Determina el directorio de guardado inteligente (OneDrive Desktop o Desktop local)."""
    onedrive_desktop = Path.home() / "OneDrive" / "Desktop"
    local_desktop    = Path.home() / "Desktop"
    screenshots_dir  = (onedrive_desktop if onedrive_desktop.exists() else local_desktop) / "Jarvis_Screenshots"
    screenshots_dir.mkdir(exist_ok=True)
    return screenshots_dir

def take_full_screenshot(delay: float = 1.0) -> str:
    """
    Toma una captura de pantalla completa.
    Agrega un delay para que la consola no aparezca en la captura.
    """
    try:
        save_dir  = _get_save_dir()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename  = f"Captura_{timestamp}.png"
        filepath  = save_dir / filename

        time.sleep(delay)
        screenshot = pyautogui.screenshot()
        screenshot.save(filepath)
        return f"Captura completa guardada en: Escritorio/Jarvis_Screenshots/{filename}"
    except Exception as e:
        return f"Error al tomar captura: {e}"

def take_region_screenshot(x: int, y: int, width: int, height: int) -> str:
    """Toma una captura de una región específica de la pantalla."""
    try:
        save_dir  = _get_save_dir()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename  = f"Region_{timestamp}.png"
        filepath  = save_dir / filename

        screenshot = pyautogui.screenshot(region=(x, y, width, height))
        screenshot.save(filepath)
        return f"Captura de región guardada en: Escritorio/Jarvis_Screenshots/{filename}"
    except Exception as e:
        return f"Error al capturar región: {e}"

def get_screen_resolution() -> str:
    """Devuelve la resolución actual de pantalla."""
    try:
        width, height = pyautogui.size()
        return f"Resolución actual de pantalla: {width} x {height} píxeles."
    except Exception as e:
        return f"No pude obtener la resolución: {e}"
