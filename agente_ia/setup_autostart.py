"""setup_autostart.py — REQ-011: activar/desactivar el arranque automático de Noddoo con
Windows (arranque minimizado a bandeja).

Script standalone (funciones a nivel de módulo, sin clases — no hay estado que justifique
una clase, ver propuestas/arquitectura-011.md, Decisión 3). Escribe/borra una entrada en
`HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run` vía `winreg` (stdlib, sin
dependencias nuevas).

Uso:
    python setup_autostart.py --activar
    python setup_autostart.py --desactivar
    python setup_autostart.py --estado

Modificar la configuración de inicio de Windows es una acción 🟡 Amarillo según
`.claude/rules/security-levels.md` ("Cambiar configuraciones del sistema"). Por eso
`activar()`/`desactivar()` piden confirmación interactiva explícita antes de mutar el
registro (`_confirmar()`, mismo patrón que `main.py::_desktop_confirm()`) y dejan un
`logger.warning(...)` en cada acción real (CA-07 de SPEC-011).
"""

import argparse
import logging
import os
import sys
import winreg

logger = logging.getLogger(__name__)

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = "Noddoo"  # constante fija — independiente de get_agent_name(), para
                                  # que activar/desactivar detecten la misma entrada aunque
                                  # cambie el nombre de marca mostrado en la UI (REQ-010)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = os.path.join(PROJECT_ROOT, "main.py")


def _resolver_pythonw() -> str:
    """Devolver la ruta a pythonw.exe junto al intérprete activo (sys.executable) si
    existe; si no, caer a sys.executable y registrar un WARNING (arranque automático
    mostraría una consola visible en cada login — ver Riesgos en arquitectura-011.md)."""
    directorio = os.path.dirname(sys.executable)
    candidato = os.path.join(directorio, "pythonw.exe")
    if os.path.isfile(candidato):
        return candidato
    logger.warning(
        "setup_autostart: no se encontró pythonw.exe junto al intérprete activo (%s); "
        "se usará %s, lo que mostrará una consola visible en cada inicio de sesión.",
        directorio,
        sys.executable,
    )
    return sys.executable


def construir_comando_autostart() -> str:
    """Armar la línea de comando a registrar en HKCU\\...\\Run."""
    pythonw = _resolver_pythonw()
    return f'"{pythonw}" "{MAIN_SCRIPT}" --tray'


def esta_activo() -> bool:
    """Devolver True si AUTOSTART_VALUE_NAME existe hoy en HKCU\\...\\Run."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def activar() -> bool:
    """Crear o actualizar la entrada de auto-inicio (idempotente, CA-05). Loggea WARNING
    (CA-07). Devuelve False solo ante un OSError inesperado (logueado, nunca propagado)."""
    comando = construir_comando_autostart()
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, comando)
        logger.warning(
            "setup_autostart: auto-inicio ACTIVADO (mecanismo=registro HKCU Run, valor=%s, comando=%s)",
            AUTOSTART_VALUE_NAME,
            comando,
        )
        return True
    except OSError as e:
        logger.error(f"setup_autostart: fallo al activar el auto-inicio: {e}")
        return False


def desactivar() -> bool:
    """Borrar la entrada de auto-inicio si existe; si no existe, no falla (CA-06) y
    retorna True. Loggea WARNING solo cuando sí borró algo (CA-07)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_WRITE) as key:
            winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
        logger.warning(
            "setup_autostart: auto-inicio DESACTIVADO (mecanismo=registro HKCU Run, valor=%s)",
            AUTOSTART_VALUE_NAME,
        )
        return True
    except FileNotFoundError:
        # No había nada que borrar (caso borde CA-06 / SPEC-011) — no es un error.
        return True
    except OSError as e:
        logger.error(f"setup_autostart: fallo al desactivar el auto-inicio: {e}")
        return False


def _confirmar(mensaje: str) -> bool:
    """Confirmación interactiva en consola — mismo patrón que main.py::_desktop_confirm().
    Implementa el gate 🟡 Amarillo de security-levels.md para este script (no hay canal ni
    dispatch involucrado, ver arquitectura-011.md, 'Por qué el gate Amarillo se implementa
    acá')."""
    respuesta = input(mensaje)
    return respuesta.strip().lower() in ("sí", "si", "yes", "s")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        description="Activa o desactiva el arranque automático de Noddoo con Windows."
    )
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--activar", action="store_true", help="Activa el auto-inicio con Windows.")
    grupo.add_argument("--desactivar", action="store_true", help="Desactiva el auto-inicio con Windows.")
    grupo.add_argument("--estado", action="store_true", help="Informa si el auto-inicio está activo.")
    args = parser.parse_args()

    if args.estado:
        if esta_activo():
            print(f"El auto-inicio de Noddoo está ACTIVO ({AUTOSTART_VALUE_NAME} en HKCU\\{RUN_KEY_PATH}).")
        else:
            print("El auto-inicio de Noddoo NO está activo.")
        sys.exit(0)

    if args.activar:
        comando_preview = construir_comando_autostart()
        confirmado = _confirmar(
            f"Esto va a registrar a Noddoo para que arranque automáticamente con Windows "
            f"(minimizado a la bandeja), ejecutando:\n  {comando_preview}\n"
            f"¿Confirmás? (sí/no): "
        )
        if not confirmado:
            print("Activación cancelada.")
            sys.exit(0)
        if activar():
            print("Auto-inicio ACTIVADO.")
        else:
            print("No se pudo activar el auto-inicio. Ver logs para más detalle.")
            sys.exit(1)

    elif args.desactivar:
        confirmado = _confirmar(
            "Esto va a quitar a Noddoo del arranque automático de Windows. ¿Confirmás? (sí/no): "
        )
        if not confirmado:
            print("Desactivación cancelada.")
            sys.exit(0)
        if desactivar():
            print("Auto-inicio DESACTIVADO.")
        else:
            print("No se pudo desactivar el auto-inicio. Ver logs para más detalle.")
            sys.exit(1)
