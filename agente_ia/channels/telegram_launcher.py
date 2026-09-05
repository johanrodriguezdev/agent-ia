"""
channels/telegram_launcher.py
Arranca el canal de Telegram junto con la app de escritorio, en su terminal.

Hasta ahora había que lanzarlo a mano en otra consola, así que en la práctica el agente casi
nunca estaba disponible desde el teléfono: la app se abría y el canal se quedaba apagado.

Va en una pestaña de la terminal embebida, pero en una **de solo lectura que corre un
comando fijo** — no una shell. La distinción es la que sostiene el modelo de seguridad:

`terminal_open` es 🟡 amarilla y pide confirmación humana porque abrir una shell concede la
capacidad de ejecutar cualquier cosa (`.claude/rules/security-levels.md`). Abrir una pestaña
al arrancar, sola, saltaría esa decisión. Pero lo que el gate protege es la SHELL, no la
pestaña: una vista que muestra la salida de un proceso fijo y descarta el teclado no
concede nada que no estuviera ya concedido. Si además aceptara teclado, sí — sería la shell
por la puerta de atrás, y por eso `TerminalSession.solo_lectura` descarta lo que se teclee.

El proceso muere con la ventana, como el resto de las pestañas.
"""

import logging
import os
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)

#: Cómo se invoca al bot. Con `-m` para que los imports absolutos del proyecto
#: (`from core...`, `from ai...`) resuelvan igual que cuando lo lanza el usuario a mano.
_COMANDO = ("-m", "channels.telegram_bot")

#: Marca en el entorno del hijo. Sirve para reconocerlo entre los procesos del sistema sin
#: depender de cómo Windows recorte la línea de comandos.
_MARCA_ENTORNO = "ORION_TELEGRAM_LANZADO_POR_LA_APP"

_proceso: Optional[subprocess.Popen] = None


def _ya_hay_uno_corriendo() -> bool:
    """Return True si otro proceso ya está haciendo polling con el mismo bot.

    Telegram solo admite un cliente haciendo `getUpdates` por token: el segundo recibe un
    `Conflict` y se queda inútil. Si el usuario ya lo tenía abierto en su consola, lo suyo
    es no abrir otro y decirlo, no dejar dos peleándose.
    """
    try:
        import psutil
    except ImportError:
        return False        # sin psutil no se puede saber; se intenta igual

    # La invocacion EXACTA, no "algo que mencione telegram_bot". Con la subcadena suelta se
    # marcaba cualquier proceso que nombrara el modulo —un editor con el archivo abierto, un
    # grep, un diagnostico— y el canal se quedaba sin arrancar por un falso positivo, que es
    # el peor desenlace posible: silencioso y con pinta de que nada fallo.
    esperado = ["-m", "channels.telegram_bot"]
    yo = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.info["pid"] == yo:
                continue
            argv = list(proc.info["cmdline"] or [])
            if len(argv) >= 3 and argv[-2:] == esperado and "python" in argv[0].lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
            # Procesos que mueren mientras se recorre la lista, o de otro usuario: no se
            # puede mirar dentro y tampoco hace falta.
            continue
    return False


def comando() -> list:
    """Return cómo se invoca al bot.

    Con `-m` para que los imports absolutos del proyecto (`from core...`, `from ai...`)
    resuelvan igual que cuando lo lanza el usuario a mano.
    """
    return [sys.executable, *_COMANDO]


def raiz_del_proyecto() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def motivo_para_no_arrancar() -> Optional[str]:
    """Return por qué NO se debe arrancar el canal, o `None` si se debe.

    Ninguno de los motivos es un error: son razones legítimas para no hacerlo. Se devuelven
    como texto para que quien llame lo registre y no parezca que falló en silencio.
    """
    try:
        from config_manager import get_telegram_autostart, get_telegram_token

        if not get_telegram_autostart():
            return "desactivado en la configuración (telegram_autostart)"
        if not get_telegram_token():
            return ("sin TELEGRAM_BOT_TOKEN configurado. Ponlo en la variable de entorno o "
                    "en config.json para usar el canal")
        if _ya_hay_uno_corriendo():
            return "ya hay un bot corriendo; no se arranca otro"
    except Exception as e:
        # Ante la duda NO se arranca: es un canal que habla con el exterior.
        logger.error(f"Telegram: no se pudo decidir si arrancar el canal: {e}")
        return f"no se pudo comprobar la configuración: {e}"
    return None


def arrancar_si_procede() -> Optional[subprocess.Popen]:
    """Lanza el bot en una consola aparte. Solo para el modo headless (sin ventana).

    Con la app de escritorio abierta se usa la pestaña de la terminal embebida
    (`ui/webview/bridge.py::abrir_canal_telegram`), que es lo que el usuario ve. Este camino
    queda para cuando no hay ventana donde mostrarla.
    """
    global _proceso

    if _proceso is not None and _proceso.poll() is None:
        return _proceso

    motivo = motivo_para_no_arrancar()
    if motivo:
        logger.info(f"Telegram: no se arranca — {motivo}")
        return None

    try:
        entorno = dict(os.environ, **{_MARCA_ENTORNO: "1"})
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        _proceso = subprocess.Popen(
            comando(), cwd=raiz_del_proyecto(), env=entorno, creationflags=flags,
        )
        logger.info(f"Telegram: canal arrancado en una consola aparte (pid {_proceso.pid})")
        return _proceso
    except Exception as e:
        logger.error(f"Telegram: no se pudo arrancar el canal: {e}")
        _proceso = None
        return None


def detener() -> None:
    """Termina el bot que arrancó esta sesión. Nunca lanza.

    Se llama al cerrar la aplicación, mismo criterio que la terminal embebida: no puede
    quedar un canal vivo, hablando con quien sea, sin nada que lo muestre.
    """
    global _proceso

    proceso, _proceso = _proceso, None
    if proceso is None or proceso.poll() is not None:
        return

    try:
        proceso.terminate()
        proceso.wait(timeout=5)
        logger.info("Telegram: canal detenido junto con la aplicación")
    except subprocess.TimeoutExpired:
        # No se fue por las buenas. Un bot que sigue atendiendo mensajes con la app cerrada
        # es peor que uno matado a la fuerza.
        try:
            proceso.kill()
            logger.warning("Telegram: el canal no respondió al cierre; se forzó")
        except Exception as e:
            logger.error(f"Telegram: no se pudo forzar el cierre del canal: {e}")
    except Exception as e:
        logger.error(f"Telegram: fallo al detener el canal: {e}")
