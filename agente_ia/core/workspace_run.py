"""
core/workspace_run.py
REQ-032 — Ejecutar un comando DENTRO de una carpeta habilitada y devolver su salida.

Existe para cerrar el ciclo de depuración: correr las pruebas, leer el fallo, corregir y
volver a correr. Sin esto el agente podía editar código pero no enterarse de si lo que
escribió funciona, que es la mitad de programar.

Es distinto de la terminal embebida (`core/terminal_session.py`), y las tres diferencias
son las que lo hacen servir para depurar:

- **Corre en la carpeta del proyecto**, no donde quedó parada la shell del usuario.
- **No escribe en la terminal que el usuario está mirando.** Es un proceso aparte, sin PTY:
  el agente corriendo la suite no le ensucia la sesión a nadie.
- **Devuelve la salida como texto para el modelo**, recortada por el final, que es donde
  pytest pone los fallos y el resumen.

Seguridad: el comando es libre (decisión explícita de Johan, 2026-09-09), así que el
control no está en QUÉ se ejecuta sino en DÓNDE y en que **cada llamada se confirma
mostrando el comando exacto**. Eso último no es cosmético: como un comando puede escribir
archivos (`echo x > a.py`), sin esa confirmación la de `file_write` quedaría decorativa —
habría un camino que la rodea.
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import List, Optional

from core.workspace_files import raices_efectivas, resolver

logger = logging.getLogger(__name__)

#: Un comando de proyecto normal (una suite, un build) termina en menos de dos minutos. El
#: techo existe para que un comando colgado —un servidor, un `--watch`— no deje el turno
#: esperando para siempre.
TIMEOUT_POR_DEFECTO = 120
TIMEOUT_MAXIMO = 600

#: Cuánto de la salida vuelve al modelo. Una suite grande escupe miles de líneas y el turno
#: no da para eso.
MAX_SALIDA = 8000
#: De ese tope, cuánto se guarda del PRINCIPIO. El resto se guarda del final: los fallos y
#: el resumen de pytest están abajo, y el principio suele ser la línea del comando y el
#: encabezado de versiones, que también sirve para entender qué corrió.
_CABEZA = 1200


@dataclass
class Resultado:
    """Lo que devuelve `ejecutar()`."""

    codigo: int
    salida: str
    carpeta: str
    truncada: bool = False
    expiro: bool = False


def _invocacion(comando: str) -> List[str]:
    """Return cómo se le pide al sistema que ejecute `comando`.

    En Windows se usa PowerShell, igual que la terminal embebida
    (`terminal_session.py:100`): si el usuario escribe sus comandos en PowerShell, el agente
    tiene que hablar el mismo idioma o `ls`, `$env:` y los pipes se comportan distinto.
    """
    if os.name == "nt":
        return ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", _para_powershell(comando)]
    return ["/bin/sh", "-c", comando]


#: Lo que se le agrega a todo comando en Windows para no perder su código de salida.
#:
#: `powershell -Command` devuelve **0 o 1** y se come el código real del proceso: con eso,
#: "¿pasaron las pruebas?" queda sin respuesta, porque pytest devuelve 1 si fallaron, 2 si
#: se interrumpió y 5 si no encontró ninguna — tres situaciones muy distintas que llegarían
#: como el mismo 1. Se captura `$?` ANTES que `$LASTEXITCODE` porque la propia asignación
#: pisaría `$?`.
_EPILOGO_POWERSHELL = (
    "\n$ok = $?; $codigo = $LASTEXITCODE\n"
    "if ($null -ne $codigo) { exit $codigo }\n"
    "if (-not $ok) { exit 1 }\n"
    "exit 0"
)


def _para_powershell(comando: str) -> str:
    """Return el comando ejecutable por PowerShell, conservando su código de salida.

    Dos arreglos que parecen detalles y no lo son:

    1. PowerShell no ejecuta un comando que empieza con una ruta entre comillas: lo trata
       como una cadena y devuelve `ParserError: UnexpectedToken`. Para eso existe el
       operador de llamada `&`. No es un caso de laboratorio: `"C:/.../python.exe" script.py`
       es exactamente lo que escribe cualquiera —persona o modelo— cuando la ruta del
       intérprete tiene espacios.
    2. El código de salida se pierde sin el epílogo de arriba.

    Los dos se encontraron porque los tests del propio REQ fallaron así.
    """
    limpio = comando.lstrip()
    prefijo = "& " if limpio.startswith(('"', "'")) else ""
    return f"{prefijo}{comando}{_EPILOGO_POWERSHELL}"


def _decodificar(crudo: bytes) -> str:
    """Return el texto de la salida, sin romperse por la codificación de la consola.

    Se captura en bytes a propósito: la consola de Windows puede escribir en la página de
    códigos del sistema y no en UTF-8, y un `decode` optimista deja la salida llena de
    símbolos raros justo cuando alguien intenta leer un error.
    """
    for codificacion in ("utf-8", "cp1252"):
        try:
            return crudo.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return crudo.decode("utf-8", errors="replace")


def _recortar(texto: str) -> "tuple[str, bool]":
    """Return `(texto, se_recorto)` conservando el principio y, sobre todo, el final."""
    if len(texto) <= MAX_SALIDA:
        return texto, False
    sobrante = len(texto) - MAX_SALIDA
    cola = MAX_SALIDA - _CABEZA
    return (
        f"{texto[:_CABEZA]}\n\n"
        f"[... {sobrante} caracteres recortados del medio ...]\n\n"
        f"{texto[-cola:]}",
        True,
    )


def carpeta_de_trabajo(ruta: str = "", raices: Optional[List[str]] = None) -> str:
    """Return la carpeta habilitada sobre la que correr. Levanta `RutaFueraDeRaiz`.

    Sin ruta y con una sola carpeta habilitada, esa. Sin ruta y con varias, se pide elegir:
    correr la suite en el repositorio equivocado es peor que preguntar.
    """
    from core.workspace_files import RutaFueraDeRaiz

    activas = raices_efectivas(raices)
    if not activas:
        raise RutaFueraDeRaiz(
            "No hay ninguna carpeta habilitada, así que no puedo ejecutar nada. El usuario "
            "tiene que habilitar la carpeta del proyecto primero."
        )
    texto = str(ruta or "").strip()
    if not texto:
        if len(activas) == 1:
            return activas[0]
        raise RutaFueraDeRaiz(
            "Hay varias carpetas habilitadas y no me dijiste en cuál correrlo. Elegí una "
            f"de: {', '.join(activas)}."
        )
    real = resolver(texto, activas)
    return real if os.path.isdir(real) else os.path.dirname(real)


def ejecutar(
    comando: str,
    ruta: str = "",
    raices: Optional[List[str]] = None,
    timeout: Optional[int] = None,
) -> Resultado:
    """Ejecuta `comando` dentro de una carpeta habilitada. Return `Resultado`.

    Levanta `RutaFueraDeRaiz` si la carpeta no se puede usar. Nunca levanta por el comando
    en sí: un comando que falla es información —el código de salida y el error— y no un
    accidente del sistema.
    """
    texto = str(comando or "").strip()
    if not texto:
        raise ValueError("comando vacío")

    carpeta = carpeta_de_trabajo(ruta, raices)
    segundos = TIMEOUT_POR_DEFECTO if timeout is None else max(1, min(int(timeout), TIMEOUT_MAXIMO))

    logger.warning(f"Ejecutando en «{carpeta}»: {texto}")
    try:
        proceso = subprocess.run(
            _invocacion(texto),
            cwd=carpeta,
            capture_output=True,
            timeout=segundos,
            shell=False,  # la lista ya lleva el intérprete: no hay una shell extra en el medio
        )
    except subprocess.TimeoutExpired as e:
        parcial = _decodificar((e.stdout or b"") + (e.stderr or b""))
        recortada, _ = _recortar(parcial)
        logger.warning(f"El comando superó los {segundos}s y se cortó: {texto}")
        return Resultado(codigo=-1, salida=recortada, carpeta=carpeta, expiro=True)
    except OSError as e:
        logger.error(f"no se pudo ejecutar '{texto}' en '{carpeta}': {e}")
        raise

    # stdout y stderr juntos y en ese orden: el error suele ir por stderr, y separarlos
    # obliga al modelo a reconstruir a mano qué pasó antes de qué.
    completo = _decodificar(proceso.stdout or b"")
    error = _decodificar(proceso.stderr or b"")
    if error:
        completo = f"{completo}\n{error}" if completo else error

    salida, truncada = _recortar(completo.strip())
    return Resultado(codigo=proceso.returncode, salida=salida, carpeta=carpeta,
                     truncada=truncada)


def describir(resultado: Resultado) -> str:
    """Return el resultado en el formato que lee el modelo."""
    if resultado.expiro:
        cabecera = f"El comando no terminó a tiempo y lo corté (carpeta: {resultado.carpeta})."
    elif resultado.codigo == 0:
        cabecera = f"Terminó bien (código 0, carpeta: {resultado.carpeta})."
    else:
        cabecera = f"Terminó con código {resultado.codigo} (carpeta: {resultado.carpeta})."

    cuerpo = resultado.salida or "(sin salida)"
    aviso = "\n\n[Salida recortada: se conservó el principio y el final.]" if resultado.truncada else ""
    return f"{cabecera}\n\n{cuerpo}{aviso}"
