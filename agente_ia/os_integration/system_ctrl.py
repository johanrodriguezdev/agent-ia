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

def close_app(app_name: str) -> str:
    """Cierra un programa/proceso por nombre en Windows."""
    import subprocess
    
    if not app_name:
        return "No me indicó qué programa cerrar, Señor."
    
    # Mapeo de nombres comunes a nombres de proceso reales
    app_aliases = {
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "firefox": "firefox.exe",
        "mozilla": "firefox.exe",
        "edge": "msedge.exe",
        "microsoft edge": "msedge.exe",
        "word": "WINWORD.EXE",
        "excel": "EXCEL.EXE",
        "powerpoint": "POWERPNT.EXE",
        "outlook": "OUTLOOK.EXE",
        "teams": "Teams.exe",
        "discord": "Discord.exe",
        "spotify": "Spotify.exe",
        "telegram": "Telegram.exe",
        "whatsapp": "WhatsApp.exe",
        "steam": "steam.exe",
        "epic games": "EpicGamesLauncher.exe",
        "notepad": "notepad.exe",
        "bloc de notas": "notepad.exe",
        "explorador": "explorer.exe",
        "explorer": "explorer.exe",
        "vscode": "Code.exe",
        "visual studio code": "Code.exe",
        "visual studio": "devenv.exe",
        "calculadora": "CalculatorApp.exe",
        "obs": "obs64.exe",
        "obs studio": "obs64.exe",
        "vlc": "vlc.exe",
        "brave": "brave.exe",
        "opera": "opera.exe",
    }
    
    # Buscar el nombre del proceso
    app_lower = app_name.lower().strip()
    process_name = app_aliases.get(app_lower, None)
    
    if not process_name:
        # Si no está en los alias, intentar con el nombre + .exe
        process_name = app_lower if app_lower.endswith(".exe") else f"{app_lower}.exe"
    
    try:
        # Verificar si el proceso está corriendo
        check = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
            capture_output=True, text=True, timeout=5
        )
        
        if process_name.lower() not in check.stdout.lower():
            return f"El programa '{app_name}' no parece estar ejecutándose, Señor."
        
        # Cerrar el proceso
        result = subprocess.run(
            ["taskkill", "/IM", process_name, "/F"],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode == 0:
            return f"Programa '{app_name}' cerrado exitosamente, Señor."
        else:
            return f"No pude cerrar '{app_name}': {result.stderr.strip()}"
            
    except subprocess.TimeoutExpired:
        return f"El intento de cerrar '{app_name}' tardó demasiado."
    except Exception as e:
        return f"Error al intentar cerrar '{app_name}': {str(e)[:60]}"
