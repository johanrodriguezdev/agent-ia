"""
action_registry.py
Registro central de todas las acciones atómicas que el Autopilot puede ejecutar.
Cada acción es una función con nombre, descripción y categoría para que el
planificador pueda seleccionarlas correctamente.
"""

import subprocess
import time
import pyautogui
import os
import shutil
from pathlib import Path
from datetime import datetime


# ─────────────────────────────────────────────
#  ACCIONES DE APLICACIONES
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
        return f"No pude abrir el navegador: {e}"


# ─────────────────────────────────────────────
#  ACCIONES DE ESCRITURA Y CONTROL
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
    """
    Guarda el documento activo mediante Ctrl+Shift+S (Guardar Como)
    y escribe la ruta del escritorio automáticamente.
    """
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
    # Aplicaciones
    "open_notepad":       {"fn": open_notepad,        "desc": "Abre el Bloc de Notas.", "category": "app"},
    "open_explorer":      {"fn": open_explorer,        "desc": "Abre el Explorador de Windows.", "category": "app"},
    "open_calculator":    {"fn": open_calculator,      "desc": "Abre la Calculadora.", "category": "app"},
    "open_browser":       {"fn": open_browser,         "desc": "Abre el navegador web.", "category": "app"},
    "close_window":       {"fn": close_window,         "desc": "Cierra la ventana activa.", "category": "app"},

    # Control y escritura
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
