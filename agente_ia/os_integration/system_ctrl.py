import os
import datetime
from pathlib import Path
import pyautogui

def get_current_time() -> str:
    """Devuelve la hora actual en formato amigable."""
    now = datetime.datetime.now()
    return f"Son las {now.strftime('%H:%M')}."

def volume_up() -> str:
    """Simula pulsación de tecla multimedia de Windows (Subir)."""
    # Usamos pyautogui para simular comandos nativos
    pyautogui.press("volumeup", presses=5) # Sube 10%
    return "Volumen subido."

def volume_down() -> str:
    """Simula pulsación de tecla multimedia de Windows (Bajar)."""
    pyautogui.press("volumedown", presses=5) # Baja 10%
    return "Volumen disminuido."

def volume_mute() -> str:
    """Simula pulsación de tecla multimedia de Windows (Silenciar)."""
    pyautogui.press("volumemute")
    return "Volumen mutado o desmutado."

def take_screenshot() -> str:
    """Toma una captura de pantalla y la guarda en el escritorio inteligente."""
    # Controla la peculiaridad de Windows donde OneDrive toma posesión de la carpeta Desktop
    desktop_onedrive = Path.home() / "OneDrive" / "Desktop"
    desktop_default = Path.home() / "Desktop"
    
    desktop_path = desktop_onedrive if desktop_onedrive.exists() else desktop_default
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_name = f"Captura_Jarvis_{timestamp}.png"
    save_path = desktop_path / file_name
    
    try:
        # Pide un segundo para no ver la consola
        pyautogui.sleep(1) 
        screenshot = pyautogui.screenshot()
        screenshot.save(save_path)
        return f"Captura de pantalla guardada en el escritorio como: {file_name}"
    except Exception as e:
        return f"Error al tomar captura: {e}"

def shutdown_pc() -> str:
    """Inicia una cuenta atrás de Windows para apagar (5 segundos)."""
    try:
        os.system("shutdown /s /t 5")
        return "Atención: El sistema se apagará en 5 segundos. Guarda tus archivos."
    except Exception as e:
         return "No se pudo invocar el apagado."
