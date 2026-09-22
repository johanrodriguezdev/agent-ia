"""
os_integration/plataforma — lo que cada sistema operativo hace distinto, en un solo lugar.

**Qué había.** Apagar el PC era `os.system("shutdown /s /t 5")` escrito en medio de
`system_ctrl.py`; cerrar una aplicación era `taskkill`; abrir una carpeta, `explorer.exe`.
Todo correcto en Windows y todo muerto fuera de él, repartido en nueve archivos con sus
`if os.name == "nt"` sueltos.

**Cómo se reparte ahora.** Este paquete define QUÉ se puede pedirle al sistema —apagar,
reiniciar, cerrar un programa, abrir una carpeta, abrir un programa— y cada sistema trae su
CÓMO en su propio módulo. La implementación se elige una sola vez, al importar.

**Por qué así y no con más `if`.** Porque el objetivo era que Windows no cambiara: su
código está mudado tal cual, no reescrito, y los tests que ya existían lo siguen probando
igual. Un `if` más en cada función habría significado tocar cada función, y cada función
tocada es una función que puede romperse.

Las funciones devuelven texto en español porque su salida se la dice el agente al usuario.
Ninguna se auto-protege: el gate de seguridad (REQ-005) vive en el punto de entrada de cada
camino de ejecución, no acá dentro.
"""

import os
from typing import Protocol


class _Plataforma(Protocol):
    """Lo que cada sistema operativo tiene que saber hacer."""

    NOMBRE: str

    def apagar(self, segundos: int = 5) -> str: ...
    def reiniciar(self, segundos: int = 5) -> str: ...
    def cerrar_aplicacion(self, nombre: str) -> str: ...
    def abrir_carpeta(self, ruta: str = "") -> str: ...
    def abrir_aplicacion(self, nombre: str) -> str: ...


def _elegir():
    """Return el módulo de la plataforma en la que se está corriendo."""
    if os.name == "nt":
        from os_integration.plataforma import _windows

        return _windows
    from os_integration.plataforma import _linux

    return _linux


#: El módulo de esta plataforma. Se resuelve una vez, al importar.
actual = _elegir()

NOMBRE = actual.NOMBRE


def apagar(segundos: int = 5) -> str:
    """Apaga el equipo tras una cuenta atrás. Return qué pasó, en palabras."""
    return actual.apagar(segundos)


def reiniciar(segundos: int = 5) -> str:
    """Reinicia el equipo tras una cuenta atrás. Return qué pasó, en palabras."""
    return actual.reiniciar(segundos)


def cerrar_aplicacion(nombre: str) -> str:
    """Cierra un programa por su nombre corriente («chrome», «word»). Return qué pasó."""
    return actual.cerrar_aplicacion(nombre)


def abrir_carpeta(ruta: str = "") -> str:
    """Abre el explorador de archivos, en `ruta` si se da. Return qué pasó."""
    return actual.abrir_carpeta(ruta)


def abrir_aplicacion(nombre: str) -> str:
    """Abre un programa conocido por su nombre corriente. Return qué pasó."""
    return actual.abrir_aplicacion(nombre)


__all__ = ["NOMBRE", "actual", "apagar", "reiniciar", "cerrar_aplicacion",
           "abrir_carpeta", "abrir_aplicacion"]
