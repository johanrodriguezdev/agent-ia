"""
os_integration/plataforma/_windows.py — cómo se le pide cada cosa a Windows.

Este archivo es una **mudanza, no una reescritura**: `shutdown /s /t`, el mapa de procesos
`.exe`, el par `tasklist`/`taskkill` y `explorer.exe` son exactamente los que estaban en
`system_ctrl.py` y `system_actions.py`, con los mismos mensajes. Se movieron para que al
lado pudiera existir `_linux.py` sin tocar lo que ya funcionaba.
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

NOMBRE = "Windows"

#: Nombre corriente → proceso real. Lo que el usuario dice no es lo que Windows llama.
PROCESOS = {
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

#: Nombre corriente → qué ejecutar para abrirlo.
APLICACIONES = {
    "bloc de notas": "notepad.exe",
    "notepad": "notepad.exe",
    "calculadora": "calc.exe",
    "calculator": "calc.exe",
    "explorador": "explorer.exe",
    "explorador de archivos": "explorer.exe",
    "paint": "mspaint.exe",
    "panel de control": "control.exe",
    "administrador de tareas": "taskmgr.exe",
    "task manager": "taskmgr.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "terminal": "cmd.exe",
    "wordpad": "wordpad.exe",
    "internet explorer": "iexplore.exe",
    "mapa de caracteres": "charmap.exe",
}


def apagar(segundos: int = 5) -> str:
    try:
        os.system(f"shutdown /s /t {int(segundos)}")
        logger.warning("Apagado del sistema iniciado por el usuario")
        return (f"Atención: El sistema se apagará en {int(segundos)} segundos. "
                f"Guarda tus archivos.")
    except Exception as e:
        logger.error(f"No se pudo invocar el apagado: {e}")
        return "No se pudo invocar el apagado."


def reiniciar(segundos: int = 5) -> str:
    try:
        os.system(f"shutdown /r /t {int(segundos)}")
        logger.warning("Reinicio del sistema iniciado por el usuario")
        return f"El sistema se reiniciará en {int(segundos)} segundos. Guarda tus archivos."
    except Exception as e:
        logger.error(f"No se pudo invocar el reinicio: {e}")
        return "No se pudo invocar el reinicio."


def cerrar_aplicacion(nombre: str) -> str:
    proceso = PROCESOS.get(nombre.lower().strip())
    if not proceso:
        limpio = nombre.lower().strip()
        proceso = limpio if limpio.endswith(".exe") else f"{limpio}.exe"
    try:
        revision = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {proceso}"],
            capture_output=True, text=True, timeout=5
        )
        if proceso.lower() not in revision.stdout.lower():
            return f"El programa '{nombre}' no parece estar ejecutándose"
        resultado = subprocess.run(
            ["taskkill", "/IM", proceso, "/F"],
            capture_output=True, text=True, timeout=10
        )
        if resultado.returncode == 0:
            logger.info(f"Programa '{nombre}' cerrado por el usuario")
            return f"Programa '{nombre}' cerrado exitosamente"
        return f"No pude cerrar '{nombre}': {resultado.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return f"El intento de cerrar '{nombre}' tardó demasiado."
    except Exception as e:
        logger.error(f"Error al cerrar '{nombre}': {e}")
        return f"Error al intentar cerrar '{nombre}': {str(e)[:60]}"


def abrir_carpeta(ruta: str = "") -> str:
    try:
        if ruta and os.path.exists(ruta):
            subprocess.Popen(f'explorer.exe "{ruta}"')
            return f"Explorador de archivos abierto en: {ruta}"
        subprocess.Popen("explorer.exe")
        return "Explorador de archivos abierto."
    except Exception as e:
        return f"No pude abrir el Explorador: {e}"


def abrir_aplicacion(nombre: str) -> str:
    limpio = nombre.lower().strip()
    comando = APLICACIONES.get(limpio)
    if not comando:
        for clave, valor in APLICACIONES.items():
            if limpio in clave or clave in limpio:
                comando = valor
                break
    if not comando:
        return ""
    try:
        subprocess.Popen(comando)
        return f"Abriendo {nombre}."
    except Exception as e:
        logger.error(f"no se pudo abrir «{nombre}»: {e}")
        return f"No pude abrir {nombre}: {e}"
