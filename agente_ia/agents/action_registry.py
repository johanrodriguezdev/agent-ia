"""
action_registry.py
Registro central de todas las acciones atómicas que el Autopilot puede ejecutar.
Cada acción es una función con nombre, descripción y categoría para que el
planificador pueda seleccionarlas correctamente.
"""

import logging
import subprocess
import time
import pyautogui
import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

from core.security_manager import security_manager, format_details
from core.errores import explicar

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  ACCIONES DIRECTAS (sin simulación)
# ─────────────────────────────────────────────

def open_chrome() -> str:
    """Abre Google Chrome directamente sin simular tecleo."""
    try:
        posibles = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            "chrome",
        ]
        for path in posibles:
            if os.path.isfile(path) or path == "chrome":
                subprocess.Popen([path, "--new-window", "https://www.google.com"])
                time.sleep(1.0)
                return "Google Chrome abierto."
        return "No encontré Chrome en las rutas habituales."
    except Exception as e:
        return explicar(e, "abrir Chrome")

def write_file_direct(text: str = "", filename: str = "") -> str:
    """Escribe texto directamente a un archivo en el Escritorio usando Python,
    sin simular tecleo ni diálogos."""
    if not text:
        return "No hay texto que escribir."
    desktop = Path.home() / "OneDrive" / "Desktop"
    if not desktop.exists():
        desktop = Path.home() / "Desktop"
    filepath = desktop / (filename or f"documento_{datetime.now().strftime('%H%M%S')}.txt")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(text)
    return f"Texto guardado directamente en: {filepath.name}"

def open_file_in_notepad(filename: str = "") -> str:
    """Abre un archivo existente en el Bloc de Notas."""
    desktop = Path.home() / "OneDrive" / "Desktop"
    if not desktop.exists():
        desktop = Path.home() / "Desktop"
    filepath = desktop / (filename or "documento.txt")
    if not filepath.exists():
        return f"El archivo {filepath.name} no existe."
    subprocess.Popen(["notepad.exe", str(filepath)])
    return f"Archivo {filepath.name} abierto en Bloc de Notas."

def get_active_window_info() -> str:
    """Retorna información de la ventana activa usando window_tracker."""
    try:
        from os_integration.window_tracker import get_active_window, format_open_windows
        active = get_active_window()
        if active:
            return f"Ventana activa: {active.get('title', active['process'])} ({active['process']})"
        return format_open_windows()
    except Exception as e:
        return explicar(e, "ver qué ventanas hay abiertas")


# ─────────────────────────────────────────────
#  ACCIONES DE APLICACIONES (legacy)
# ─────────────────────────────────────────────

def open_notepad() -> str:
    subprocess.Popen("notepad.exe")
    time.sleep(1.5)
    return "Bloc de notas abierto."

def open_explorer() -> str:
    subprocess.Popen("explorer.exe")
    time.sleep(1.0)
    return "Explorador de archivos abierto."

def open_calculator() -> str:
    subprocess.Popen("calc.exe")
    time.sleep(1.0)
    return "Calculadora abierta."

def open_browser() -> str:
    try:
        import webbrowser
        webbrowser.open("https://www.google.com")
        return "Navegador abierto con Google."
    except Exception as e:
        return explicar(e, "abrir el navegador")


def open_spotify() -> str:
    """Abre la aplicación de escritorio de Spotify si existe en una ruta conocida de
    instalación; si no, abre https://open.spotify.com en el navegador por defecto
    (REQ-008/CA-08). Sin login ni control de reproducción — mínimo viable."""
    posibles = [
        os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe"),
        r"C:\Program Files\Spotify\Spotify.exe",
        r"C:\Program Files (x86)\Spotify\Spotify.exe",
    ]
    try:
        for path in posibles:
            if path and os.path.isfile(path):
                subprocess.Popen([path])
                time.sleep(1.0)
                return "Spotify abierto."
        import webbrowser
        webbrowser.open("https://open.spotify.com")
        return "Spotify no está instalado; abrí open.spotify.com en el navegador."
    except Exception as e:
        logger.error(f"Error al abrir Spotify: {e}")
        return explicar(e, "abrir Spotify")


# ─────────────────────────────────────────────
#  ACCIONES DE ESCRITURA Y CONTROL (legacy)
# ─────────────────────────────────────────────

def write_text(text: str = "") -> str:
    if not text:
        return "No hay texto que escribir."
    time.sleep(0.4)
    pyautogui.write(text, interval=0.03)
    return f"Texto escrito: '{text[:60]}...'" if len(text) > 60 else f"Texto escrito: '{text}'"

def press_key(key: str = "enter") -> str:
    pyautogui.press(key)
    return f"Tecla '{key}' presionada."

def hotkey_action(keys: str = "ctrl,s") -> str:
    key_list = [k.strip() for k in keys.split(",")]
    pyautogui.hotkey(*key_list)
    return f"Combinación de teclas ejecutada: {keys}"

def save_file_desktop(filename: str = "documento_jarvis.txt") -> str:
    desktop = Path.home() / "OneDrive" / "Desktop"
    if not desktop.exists():
        desktop = Path.home() / "Desktop"
    filepath = str(desktop / filename)
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "shift", "s")
    time.sleep(1.5)
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.2)
    pyautogui.write(filepath, interval=0.03)
    time.sleep(0.3)
    pyautogui.press("enter")
    time.sleep(0.5)
    return f"Archivo guardado como: {filepath}"

def close_window() -> str:
    pyautogui.hotkey("alt", "f4")
    return "Ventana cerrada."

def take_screenshot(delay: float = 1.0) -> str:
    desktop = Path.home() / "OneDrive" / "Desktop"
    if not desktop.exists():
        desktop = Path.home() / "Desktop"
    folder = desktop / "Jarvis_Screenshots"
    folder.mkdir(exist_ok=True)
    ts   = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = folder / f"Captura_{ts}.png"
    time.sleep(delay)
    pyautogui.screenshot().save(path)
    return f"Captura guardada: {path.name}"

def wait_seconds(seconds: float = 1.0) -> str:
    time.sleep(seconds)
    return f"Esperé {seconds} segundos."


# ─────────────────────────────────────────────
#  ACCIONES DE INFORMACIÓN Y CONTENIDO
# ─────────────────────────────────────────────

def generate_ai_summary(topic: str = "inteligencia artificial") -> str:
    """
    Genera un resumen breve sobre un tema usando Wikipedia como fuente.
    Retorna el texto listo para ser escrito por write_text().
    """
    try:
        import wikipedia
        wikipedia.set_lang("es")
        summary = wikipedia.summary(topic, sentences=5, auto_suggest=True)
        return summary
    except Exception as e:
        return (
            f"Resumen de {topic}: La inteligencia artificial (IA) es la simulación de "
            "procesos de inteligencia humana por parte de sistemas informáticos. "
            "Incluye el aprendizaje automático, el procesamiento del lenguaje natural "
            "y la visión computacional entre sus ramas principales."
        )

def get_current_datetime() -> str:
    now = datetime.now()
    return f"Fecha y hora actual: {now.strftime('%d de %B de %Y, %H:%M')}"

def get_disk_info() -> str:
    disk = shutil.disk_usage(Path.home())
    free_gb  = disk.free  / (1024 ** 3)
    total_gb = disk.total / (1024 ** 3)
    used_pct = (disk.used / disk.total) * 100
    return f"Disco: {total_gb:.1f} GB total | {free_gb:.1f} GB libre ({used_pct:.1f}% usado)"

def open_url(url: str = "https://google.com") -> str:
    import webbrowser
    webbrowser.open(url)
    time.sleep(1.0)
    return f"URL abierta: {url}"

def search_google(query: str = "") -> str:
    import webbrowser
    url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    webbrowser.open(url)
    return f"Búsqueda de Google iniciada: '{query}'"


# ─────────────────────────────────────────────
#  REGISTRO CENTRAL DE ACCIONES
# ─────────────────────────────────────────────

ACTION_REGISTRY: dict[str, dict] = {
    # Aplicaciones (directas)
    "open_chrome":        {"fn": open_chrome,          "desc": "Abre Google Chrome directamente.", "category": "app"},
    "open_notepad":       {"fn": open_notepad,         "desc": "Abre el Bloc de Notas.", "category": "app"},
    "open_explorer":      {"fn": open_explorer,        "desc": "Abre el Explorador de Windows.", "category": "app"},
    "open_calculator":    {"fn": open_calculator,      "desc": "Abre la Calculadora.", "category": "app"},
    "open_browser":       {"fn": open_browser,         "desc": "Abre el navegador web.", "category": "app"},
    "open_spotify":       {"fn": open_spotify,         "desc": "Abre Spotify (app de escritorio o open.spotify.com).", "category": "app"},
    "close_window":       {"fn": close_window,         "desc": "Cierra la ventana activa.", "category": "app"},

    # Escritura directa (sin pyautogui)
    "write_file_direct":  {"fn": write_file_direct,    "desc": "Escribe texto directamente a un archivo en el Escritorio.", "category": "file", "needs_param": "text"},
    "open_file_in_notepad":{"fn": open_file_in_notepad,"desc": "Abre un archivo existente en Bloc de Notas.", "category": "file", "needs_param": "filename"},
    "get_active_window_info":{"fn": get_active_window_info,"desc": "Muestra qué ventana está activa.", "category": "info"},

    # Control y escritura (legacy - pyautogui)
    "write_text":         {"fn": write_text,           "desc": "Escribe texto en la aplicación activa.", "category": "input", "needs_param": "text"},
    "press_key":          {"fn": press_key,            "desc": "Presiona una tecla del teclado.", "category": "input", "needs_param": "key"},
    "hotkey_action":      {"fn": hotkey_action,        "desc": "Ejecuta una combinación de teclas.", "category": "input", "needs_param": "keys"},
    "save_file_desktop":  {"fn": save_file_desktop,    "desc": "Guarda el archivo activo en el Escritorio.", "category": "file", "needs_param": "filename"},
    "take_screenshot":    {"fn": take_screenshot,      "desc": "Toma una captura de pantalla.", "category": "system"},
    "wait_seconds":       {"fn": wait_seconds,         "desc": "Espera N segundos.", "category": "system", "needs_param": "seconds"},

    # Contenido e información
    "generate_ai_summary":{"fn": generate_ai_summary, "desc": "Genera resumen de un tema con Wikipedia.", "category": "content", "needs_param": "topic"},
    "get_current_datetime":{"fn": get_current_datetime,"desc": "Obtiene la fecha y hora actual.", "category": "info"},
    "get_disk_info":      {"fn": get_disk_info,        "desc": "Información del disco duro.", "category": "info"},
    "open_url":           {"fn": open_url,             "desc": "Abre una URL en el navegador.", "category": "web", "needs_param": "url"},
    "search_google":      {"fn": search_google,        "desc": "Busca en Google.", "category": "web", "needs_param": "query"},
}

def get_action(name: str):
    """Retorna el dict de la acción por nombre, o None si no existe."""
    return ACTION_REGISTRY.get(name)

def list_action_names() -> list[str]:
    """Lista todos los nombres de acciones disponibles."""
    return list(ACTION_REGISTRY.keys())

def execute_action(name: str, params: Optional[dict] = None, channel=None, user_id: str = "default") -> str:
    """Único punto de ejecución gateado del registro: resuelve la acción por nombre,
    exige confirmación de seguridad y solo entonces invoca la función subyacente."""
    info = ACTION_REGISTRY.get(name)
    if not info:
        return f"Acción '{name}' no reconocida."
    if not security_manager.require_confirmation(
        name,
        channel,
        details=format_details(f"action_registry:{name}", params),
        user_id=user_id,
    ):
        return f"⛔ Acción '{name}' no autorizada."
    fn = info["fn"]
    params = params or {}
    return fn(**params) if params else fn()
