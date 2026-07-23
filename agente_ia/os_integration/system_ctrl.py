import os
import datetime
import logging
from pathlib import Path
import pyautogui

from core.security_manager import security_manager, ChannelType

logger = logging.getLogger(__name__)

def get_current_time() -> str:
    now = datetime.datetime.now()
    return f"Son las {now.strftime('%H:%M')}."

def volume_up() -> str:
    pyautogui.press("volumeup", presses=5)
    return "Volumen subido."

def volume_down() -> str:
    pyautogui.press("volumedown", presses=5)
    return "Volumen disminuido."

def volume_mute() -> str:
    pyautogui.press("volumemute")
    return "Volumen mutado o desmutado."

def take_screenshot() -> str:
    desktop_onedrive = Path.home() / "OneDrive" / "Desktop"
    desktop_default = Path.home() / "Desktop"
    desktop_path = desktop_onedrive if desktop_onedrive.exists() else desktop_default
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_name = f"Captura_Jarvis_{timestamp}.png"
    save_path = desktop_path / file_name
    try:
        pyautogui.sleep(1)
        screenshot = pyautogui.screenshot()
        screenshot.save(save_path)
        return f"Captura de pantalla guardada en el escritorio como: {file_name}"
    except Exception as e:
        logger.error(f"Error al tomar captura: {e}")
        return f"Error al tomar captura: {e}"

def _resolve_channel(channel=None):
    if channel is None:
        return ChannelType.DESKTOP
    if isinstance(channel, ChannelType):
        return channel
    channel_map = {
        "desktop": ChannelType.DESKTOP,
        "telegram": ChannelType.TELEGRAM,
        "discord": ChannelType.DISCORD,
        "voice": ChannelType.VOICE,
    }
    return channel_map.get(str(channel).lower(), ChannelType.DESKTOP)

def shutdown_pc(channel=None) -> str:
    ch = _resolve_channel(channel)
    if not security_manager.require_confirmation("shutdown", ch, "apagar el PC"):
        return "Apagado cancelado, Señor."
    try:
        os.system("shutdown /s /t 5")
        logger.warning("Apagado del sistema iniciado por el usuario")
        return "Atención: El sistema se apagará en 5 segundos. Guarda tus archivos."
    except Exception as e:
        logger.error(f"No se pudo invocar el apagado: {e}")
        return "No se pudo invocar el apagado."

def close_app(app_name: str, channel=None) -> str:
    import subprocess
    if not app_name:
        return "No me indicó qué programa cerrar, Señor."
    app_aliases = {
        "chrome": "chrome.exe", "google chrome": "chrome.exe",
        "firefox": "firefox.exe", "mozilla": "firefox.exe",
        "edge": "msedge.exe", "microsoft edge": "msedge.exe",
        "word": "WINWORD.EXE", "excel": "EXCEL.EXE",
        "powerpoint": "POWERPNT.EXE", "outlook": "OUTLOOK.EXE",
        "teams": "Teams.exe", "discord": "Discord.exe",
        "spotify": "Spotify.exe", "telegram": "Telegram.exe",
        "whatsapp": "WhatsApp.exe", "steam": "steam.exe",
        "epic games": "EpicGamesLauncher.exe",
        "notepad": "notepad.exe", "bloc de notas": "notepad.exe",
        "explorador": "explorer.exe", "explorer": "explorer.exe",
        "vscode": "Code.exe", "visual studio code": "Code.exe",
        "visual studio": "devenv.exe",
        "calculadora": "CalculatorApp.exe",
        "obs": "obs64.exe", "obs studio": "obs64.exe",
        "vlc": "vlc.exe", "brave": "brave.exe", "opera": "opera.exe",
    }
    app_lower = app_name.lower().strip()
    process_name = app_aliases.get(app_lower, None)
    if not process_name:
        process_name = app_lower if app_lower.endswith(".exe") else f"{app_lower}.exe"
    ch = _resolve_channel(channel)
    if not security_manager.require_confirmation("close_app", ch, f"cerrar {app_name} ({process_name})"):
        return f"Cierre de '{app_name}' cancelado, Señor."
    try:
        check = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
            capture_output=True, text=True, timeout=5
        )
        if process_name.lower() not in check.stdout.lower():
            return f"El programa '{app_name}' no parece estar ejecutándose, Señor."
        result = subprocess.run(
            ["taskkill", "/IM", process_name, "/F"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            logger.info(f"Programa '{app_name}' cerrado por el usuario")
            return f"Programa '{app_name}' cerrado exitosamente, Señor."
        else:
            return f"No pude cerrar '{app_name}': {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return f"El intento de cerrar '{app_name}' tardó demasiado."
    except Exception as e:
        logger.error(f"Error al cerrar '{app_name}': {e}")
        return f"Error al intentar cerrar '{app_name}': {str(e)[:60]}"
