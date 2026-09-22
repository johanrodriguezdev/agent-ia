"""
os_integration/plataforma/_linux.py — cómo se le pide cada cosa a Linux.

Las diferencias que importan respecto de Windows, y que no son de traducción:

- **Apagar no siempre se puede.** En Windows, el usuario de escritorio apaga su equipo. En
  Linux depende de quién seas: con una sesión de escritorio, `systemctl poweroff` lo hace
  por vos; por SSH o dentro de un contenedor, hace falta permiso de administrador. Acá se
  intenta el camino de la sesión y, si no se puede, **se dice por qué** en vez de fallar en
  silencio. Un «no tengo permiso para apagar» es una respuesta; un cuelgue no lo es.
- **Cerrar un programa no es matar un `.exe`.** Los procesos se llaman `firefox`, `code`,
  `soffice`. Se busca por nombre y, si no aparece, se prueba con el nombre tal cual.
- **No hay un «explorador».** Lo que hay es `xdg-open`, que abre cada cosa con lo que el
  usuario tenga puesto por defecto. Es más correcto que elegir nosotros un gestor de
  archivos: respeta su escritorio.
- **Dentro de un contenedor**, apagar apagaría el contenedor y no el equipo. Se detecta y
  se dice, porque «apagá el PC» ahí dentro no significa lo que el usuario cree.
"""

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

NOMBRE = "Linux"

#: Nombre corriente → nombre del proceso. En Linux no hay extensión ni mayúsculas.
PROCESOS = {
    "chrome": "chrome", "google chrome": "chrome", "chromium": "chromium",
    "firefox": "firefox", "mozilla": "firefox",
    "edge": "msedge", "microsoft edge": "msedge",
    "word": "soffice", "excel": "soffice", "powerpoint": "soffice",
    "libreoffice": "soffice", "writer": "soffice", "calc": "soffice",
    "teams": "teams", "discord": "Discord", "spotify": "spotify",
    "telegram": "telegram-desktop", "whatsapp": "whatsapp", "steam": "steam",
    "vscode": "code", "visual studio code": "code",
    "terminal": "gnome-terminal", "vlc": "vlc", "brave": "brave",
    "opera": "opera", "obs": "obs", "obs studio": "obs",
    "calculadora": "gnome-calculator", "bloc de notas": "gedit", "notepad": "gedit",
}

#: Nombre corriente → qué ejecutar. Se comprueba que exista antes de prometerlo.
APLICACIONES = {
    "bloc de notas": ("gedit", "kate", "mousepad", "xed"),
    "notepad": ("gedit", "kate", "mousepad", "xed"),
    "calculadora": ("gnome-calculator", "kcalc", "galculator"),
    "calculator": ("gnome-calculator", "kcalc", "galculator"),
    "explorador": ("nautilus", "dolphin", "thunar", "nemo"),
    "explorador de archivos": ("nautilus", "dolphin", "thunar", "nemo"),
    "terminal": ("gnome-terminal", "konsole", "xfce4-terminal", "xterm"),
    "cmd": ("gnome-terminal", "konsole", "xfce4-terminal", "xterm"),
    "paint": ("gimp", "pinta", "krita"),
    "monitor del sistema": ("gnome-system-monitor", "ksysguard"),
    "administrador de tareas": ("gnome-system-monitor", "ksysguard"),
    "task manager": ("gnome-system-monitor", "ksysguard"),
}


def _en_contenedor() -> bool:
    """Return si esto corre dentro de un contenedor, donde apagar no significa lo mismo."""
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", encoding="utf-8", errors="replace") as f:
            return any(marca in f.read() for marca in ("docker", "containerd", "kubepods"))
    except OSError:
        return False


def _apagar_o_reiniciar(accion: str, segundos: int) -> str:
    """Comparten todo salvo el verbo: se intenta systemd y se explica si no se puede."""
    es_apagar = accion == "poweroff"
    verbo = "apagará" if es_apagar else "reiniciará"

    if _en_contenedor():
        return (f"Estoy dentro de un contenedor: {'apagarlo' if es_apagar else 'reiniciarlo'} "
                f"cerraría la aplicación, no el equipo. Si querés {'apagar' if es_apagar else 'reiniciar'} "
                f"la máquina, hacelo desde el sistema.")

    binario = shutil.which("systemctl")
    if not binario:
        return (f"No encuentro 'systemctl' para {'apagar' if es_apagar else 'reiniciar'} "
                f"este equipo.")

    try:
        # `systemctl poweroff` pide permiso a logind, que se lo da a quien tenga una sesión
        # gráfica activa. Por SSH o sin sesión, responde que hace falta autenticación.
        resultado = subprocess.run([binario, accion], capture_output=True, text=True, timeout=15)
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.error(f"no se pudo invocar {accion}: {e}")
        return f"No se pudo invocar el {'apagado' if es_apagar else 'reinicio'}."

    if resultado.returncode == 0:
        logger.warning(f"{accion} del sistema iniciado por el usuario")
        return f"El sistema se {verbo} enseguida. Guarda tus archivos."

    detalle = (resultado.stderr or "").strip()
    if "auth" in detalle.lower() or "polkit" in detalle.lower() or "denied" in detalle.lower():
        return (f"No tengo permiso para {'apagar' if es_apagar else 'reiniciar'} este equipo: "
                f"el sistema pide autenticación de administrador. Hacelo vos, o dame permiso "
                f"en polkit.")
    return f"No pude {'apagar' if es_apagar else 'reiniciar'}: {detalle[:120] or 'sin detalle'}"


def apagar(segundos: int = 5) -> str:
    return _apagar_o_reiniciar("poweroff", segundos)


def reiniciar(segundos: int = 5) -> str:
    return _apagar_o_reiniciar("reboot", segundos)


def cerrar_aplicacion(nombre: str) -> str:
    limpio = nombre.lower().strip()
    if not limpio:
        return "No me indicó qué programa cerrar"
    proceso = PROCESOS.get(limpio, limpio)

    if not shutil.which("pkill"):
        return "No encuentro 'pkill' para cerrar programas en este equipo."
    try:
        # `pgrep -f` primero: sin esto no se distingue «no estaba abierto» de «no se pudo».
        existe = subprocess.run(["pgrep", "-fi", proceso], capture_output=True,
                                text=True, timeout=5)
        if existe.returncode != 0:
            return f"El programa '{nombre}' no parece estar ejecutándose"
        resultado = subprocess.run(["pkill", "-fi", proceso], capture_output=True,
                                   text=True, timeout=10)
        if resultado.returncode == 0:
            logger.info(f"Programa '{nombre}' cerrado por el usuario")
            return f"Programa '{nombre}' cerrado exitosamente"
        return f"No pude cerrar '{nombre}': {(resultado.stderr or '').strip()[:80]}"
    except subprocess.TimeoutExpired:
        return f"El intento de cerrar '{nombre}' tardó demasiado."
    except Exception as e:
        logger.error(f"Error al cerrar '{nombre}': {e}")
        return f"Error al intentar cerrar '{nombre}': {str(e)[:60]}"


def abrir_carpeta(ruta: str = "") -> str:
    destino = ruta if (ruta and os.path.exists(ruta)) else os.path.expanduser("~")
    abridor = shutil.which("xdg-open")
    if not abridor:
        return "No encuentro 'xdg-open' para abrir carpetas en este equipo."
    try:
        subprocess.Popen([abridor, destino],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Explorador de archivos abierto en: {destino}"
    except Exception as e:
        return f"No pude abrir el explorador: {e}"


def abrir_aplicacion(nombre: str) -> str:
    limpio = nombre.lower().strip()
    candidatos = APLICACIONES.get(limpio)
    if not candidatos:
        for clave, valores in APLICACIONES.items():
            if limpio in clave or clave in limpio:
                candidatos = valores
                break
    # Lo que no está en el catálogo se intenta tal cual: en Linux el nombre del programa
    # suele ser el del comando («gimp», «code»), así que acertar es lo normal.
    candidatos = candidatos or (limpio,)

    for candidato in candidatos:
        binario = shutil.which(candidato)
        if not binario:
            continue
        try:
            subprocess.Popen([binario],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Abriendo {nombre}."
        except Exception as e:
            logger.error(f"no se pudo abrir «{nombre}» con {binario}: {e}")
            return f"No pude abrir {nombre}: {e}"
    return ""
