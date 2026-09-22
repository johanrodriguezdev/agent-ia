import os
import datetime
import logging
from pathlib import Path
import pyautogui
from core.address import vocative, vocative_start

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

def shutdown_pc(channel=None) -> str:
    """Apagar el PC.

    INVARIANTE DE SEGURIDAD (REQ-005): esta función NO se auto-protege. Asume estar
    gateada por el punto central (`security_manager.require_confirmation()`), que se
    ejecuta en `router/dispatcher.py:dispatch()` o en `skills/skill_manager.py:execute()`
    antes de llegar acá. No invocarla directamente desde código nuevo sin pasar por uno
    de esos caminos: quedaría sin confirmación. El parámetro `channel` se conserva por
    compatibilidad de firma con los callers actuales.
    """
    from os_integration import plataforma

    return plataforma.apagar(5)

def close_app(app_name: str, channel=None) -> str:
    """Cerrar una aplicación por nombre.

    INVARIANTE DE SEGURIDAD (REQ-005): esta función NO se auto-protege. Asume estar
    gateada por el punto central (`security_manager.require_confirmation()`), que se
    ejecuta en `router/dispatcher.py:dispatch()` antes de llamar al handler legacy que
    llega acá. No invocarla directamente desde código nuevo sin pasar por ese camino:
    quedaría sin confirmación. El parámetro `channel` se conserva por compatibilidad de
    firma con los callers actuales.
    """
    from os_integration import plataforma

    if not app_name:
        return f"No me indicó qué programa cerrar{vocative()}."
    # El «cómo» —taskkill o pkill, y con qué nombre se llama cada programa— vive en
    # `os_integration/plataforma`. Acá queda lo que no depende del sistema: el trato al
    # usuario y el invariante de seguridad de arriba.
    return plataforma.cerrar_aplicacion(app_name) + vocative() + "."
