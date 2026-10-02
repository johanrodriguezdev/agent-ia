"""
core/errores.py
REQ-072 — que un fallo se le cuente al usuario, no se le vuelque encima.

**Qué había.** 58 sitios devolvían la excepción cruda pegada a una frase:
`return f"No pude abrir Spotify: {e}"`. En la pantalla eso termina siendo
«No pude abrir Spotify: [WinError 5] Acceso denegado» o, peor,
«...: [Errno 2] No such file or directory: 'C:\\\\Users\\\\...'». El usuario no puede hacer
nada con eso, y la especificación de O.R.I.O.N. lo dice en su §12: el mensaje explica
**qué pasó y por qué**, y el detalle técnico queda disponible solo si lo piden.

**Qué hace este módulo.** Traduce una excepción a una causa en castellano llano —permisos,
no está, está en uso, no hay espacio, se acabó el tiempo, no hay conexión— y deja el
detalle completo en el log, que es donde sirve para arreglarlo.

**Lo que NO hace.** Inventar la causa. Si la excepción no se reconoce, se dice que falló y
se nombra el tipo, que es un dato real y corto. Un diagnóstico equivocado es peor que
decir «no sé qué pasó»: manda al usuario a buscar donde no es.
"""

import errno
import json
import logging
import socket
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

#: Códigos de Windows que importan y no vienen con un tipo de excepción propio.
_WINERROR = {
    5: "no tengo permisos para hacerlo",
    32: "el archivo está abierto en otro programa",
    123: "la ruta tiene algún carácter que el sistema no acepta",
    145: "la carpeta no está vacía",
    1920: "el sistema no me deja leer ese archivo",
}

#: Códigos POSIX equivalentes.
_ERRNO = {
    errno.EACCES: "no tengo permisos para hacerlo",
    errno.EPERM: "no tengo permisos para hacerlo",
    errno.ENOENT: "no existe",
    errno.ENOSPC: "no queda espacio en el disco",
    errno.EROFS: "el disco es de solo lectura",
    errno.EBUSY: "está en uso",
    errno.ENOTEMPTY: "la carpeta no está vacía",
    errno.EISDIR: "es una carpeta, no un archivo",
    errno.ENOTDIR: "no es una carpeta",
    errno.EEXIST: "ya existe",
    errno.ETIMEDOUT: "se agotó el tiempo de espera",
    errno.ECONNREFUSED: "no hay nada escuchando del otro lado",
    errno.ENETUNREACH: "no hay conexión de red",
}


def causa(e: BaseException) -> str:
    """Return en pocas palabras por qué falló, en castellano llano.

    Devuelve la causa a secas («no tengo permisos para hacerlo»), sin mayúscula inicial ni
    punto, para poder pegarla detrás de lo que cada sitio ya dice.
    """
    # Por tipo primero: es lo más fiable que hay.
    if isinstance(e, PermissionError):
        return "no tengo permisos para hacerlo"
    if isinstance(e, FileNotFoundError):
        return "no encuentro el archivo"
    if isinstance(e, FileExistsError):
        return "ya existe"
    if isinstance(e, IsADirectoryError):
        return "es una carpeta, no un archivo"
    if isinstance(e, NotADirectoryError):
        return "la ruta no es una carpeta"
    if isinstance(e, (TimeoutError, socket.timeout, subprocess.TimeoutExpired)):
        return "tardó demasiado y lo corté"
    if isinstance(e, (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError)):
        return "se cortó la conexión"
    if isinstance(e, socket.gaierror):
        return "no pude resolver la dirección"
    if isinstance(e, ConnectionError):
        return "no hay conexión"
    if isinstance(e, MemoryError):
        return "me quedé sin memoria"
    if isinstance(e, json.JSONDecodeError):
        return "el archivo no tiene el formato esperado"
    if isinstance(e, UnicodeDecodeError):
        return "el texto está en una codificación que no pude leer"
    if isinstance(e, ModuleNotFoundError):
        falta = getattr(e, "name", "") or ""
        return f"falta un componente del sistema ({falta})" if falta else "falta un componente"
    if isinstance(e, (KeyboardInterrupt, SystemExit)):
        return "se interrumpió"

    # Después, por código: un OSError genérico suele traer el motivo real acá.
    codigo_windows = getattr(e, "winerror", None)
    if codigo_windows in _WINERROR:
        return _WINERROR[codigo_windows]
    if isinstance(e, OSError) and e.errno in _ERRNO:
        return _ERRNO[e.errno]

    # Y si no se reconoce, se dice que no se reconoce. Sin adivinar.
    return f"falló por algo que no supe interpretar ({type(e).__name__})"


def explicar(e: BaseException, intento: str = "", contexto: str = "") -> str:
    """Return la frase completa para el usuario, y deja el detalle técnico en el log.

    `intento` es lo que se estaba haciendo, en infinitivo o gerundio y sin punto final:
    «abrir Spotify», «guardar la configuración». `contexto` es para el log, no se muestra.

        >>> explicar(PermissionError(), "abrir Spotify")
        'No pude abrir Spotify: no tengo permisos para hacerlo.'

    El detalle va a `logger.error` con la excepción entera: es lo que hace falta para
    arreglarlo, y no es lo que el usuario necesita leer.
    """
    logger.error(f"{contexto or intento or 'operación'} falló: {type(e).__name__}: {e}",
                 exc_info=True)
    motivo = causa(e)
    if intento:
        return f"No pude {intento}: {motivo}."
    return f"No pude completar la operación: {motivo}."


def detalle_tecnico(e: BaseException) -> str:
    """Return el detalle para quien lo pida: tipo, mensaje y código si lo hay.

    La §12 de la especificación lo contempla: el usuario puede pedir el detalle, y ahí sí
    se le da — en una línea, no en un volcado de pila.
    """
    partes = [type(e).__name__]
    texto = str(e).strip()
    if texto:
        partes.append(texto)
    codigo = getattr(e, "winerror", None) or getattr(e, "errno", None)
    if codigo:
        partes.append(f"código {codigo}")
    return " · ".join(partes)
