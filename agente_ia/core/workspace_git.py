"""
core/workspace_git.py
REQ-029 — Consultas de git sobre las carpetas habilitadas: `status`, `diff` y `log`.

Tres decisiones que no son negociables (CA-13):

- **Nunca `shell=True`.** El comando se arma como lista de argumentos y lo ejecuta el
  sistema operativo directo. Sin shell no hay `;`, `&&`, `|`, comillas ni expansión: la
  clase entera de inyección por parámetro deja de existir en vez de tener que filtrarse.
- **Lista blanca de subcomandos.** Solo `status`, `diff` y `log`. No hay forma de colar
  otro: `_correr()` verifica contra `SUBCOMANDOS_PERMITIDOS` antes de armar nada.
- **Ningún argumento crudo del modelo llega a la línea de comando.** Lo único que el
  modelo aporta es una ruta —que pasa por `workspace_files.resolver()` y se convierte en
  una ruta relativa al repo, detrás de `--`— y un entero de cantidad, que se acota.

`commit` y `push` NO están, y no es un olvido: `.claude/rules/git.md` dice que los commits
los hace el humano. Dárselos al agente contradice una regla vigente del proyecto.
"""

import logging
import os
import subprocess
from typing import List, Optional, Tuple

from core.workspace_files import RutaFueraDeRaiz, raices_efectivas, resolver

logger = logging.getLogger(__name__)

#: Lo único que este módulo puede pedirle a git. Consultas de lectura, nada que escriba.
SUBCOMANDOS_PERMITIDOS = frozenset({"status", "diff", "log"})

#: Un repo grande puede devolver un diff de megabytes. Se corta avisando.
_MAX_SALIDA = 30_000
_TIMEOUT_SEGUNDOS = 30
#: Techo de commits que puede pedir `log`, para que un número absurdo no traiga el repo entero.
_MAX_COMMITS = 50


def _repo_de(ruta: str, raices: Optional[List[str]] = None) -> Tuple[Optional[str], str]:
    """Return `(carpeta, error)`: sobre qué carpeta habilitada correr git.

    Sin ruta y con una sola raíz, esa. Sin ruta y con varias, se pide que elija: adivinar
    en cuál de tres repos quiso mirar el usuario es peor que preguntar.
    """
    activas = raices_efectivas(raices)
    if not activas:
        return None, (
            "No hay ninguna carpeta habilitada, así que no tengo ningún repositorio que "
            "consultar. El usuario tiene que habilitar una en code_workspaces.json."
        )
    if not str(ruta or "").strip():
        if len(activas) == 1:
            return activas[0], ""
        return None, (
            "Hay varias carpetas habilitadas y no me dijiste sobre cuál mirar. Elegí una "
            f"de: {', '.join(activas)}."
        )
    real = resolver(ruta, activas)
    if os.path.isdir(real):
        return real, ""
    return os.path.dirname(real), ""


def _correr(subcomando: str, argumentos: List[str], carpeta: str) -> Tuple[bool, str]:
    """Ejecuta `git <subcomando> [argumentos]` en `carpeta`. Return `(ok, salida)`.

    `shell=False` (el default de `subprocess.run` con una lista, explicitado acá porque es
    justamente el punto): los argumentos llegan al proceso tal cual, sin pasar por ningún
    intérprete de comandos.
    """
    if subcomando not in SUBCOMANDOS_PERMITIDOS:
        # Defensa en profundidad: hoy los tres call-sites pasan literales, así que esto
        # solo puede dispararlo un cambio futuro. Que falle ruidosamente es el punto.
        logger.critical(
            f"Subcomando de git no permitido bloqueado: {subcomando!r}. "
            f"Solo se admiten {sorted(SUBCOMANDOS_PERMITIDOS)}."
        )
        return False, "Ese comando de git no está permitido."

    comando = ["git", "--no-pager", subcomando] + list(argumentos)
    try:
        proceso = subprocess.run(
            comando,
            cwd=carpeta,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT_SEGUNDOS,
        )
    except FileNotFoundError:
        logger.error("git no está instalado o no está en el PATH")
        return False, "No encuentro git en esta máquina, así que no puedo consultar el repositorio."
    except subprocess.TimeoutExpired:
        logger.error(f"git {subcomando} superó los {_TIMEOUT_SEGUNDOS}s en {carpeta!r}")
        return False, f"La consulta a git tardó más de {_TIMEOUT_SEGUNDOS} segundos y la corté."
    except OSError as e:
        logger.error(f"No se pudo ejecutar git {subcomando} en {carpeta!r}: {e}")
        return False, "No pude ejecutar git en esa carpeta."

    if proceso.returncode != 0:
        detalle = (proceso.stderr or proceso.stdout or "").strip()
        logger.warning(f"git {subcomando} devolvió {proceso.returncode} en {carpeta!r}: {detalle}")
        if "not a git repository" in detalle.lower():
            return False, "Esa carpeta no es un repositorio git."
        return False, f"git no pudo responder: {_recortar(detalle)}"

    return True, proceso.stdout or ""


def _recortar(salida: str) -> str:
    if len(salida) <= _MAX_SALIDA:
        return salida
    return (
        salida[:_MAX_SALIDA]
        + f"\n[Salida recortada: superaba los {_MAX_SALIDA} caracteres.]"
    )


def estado(ruta: str = "", raices: Optional[List[str]] = None) -> str:
    """Return el estado del repositorio de una carpeta habilitada."""
    carpeta, error = _repo_de(ruta, raices)
    if carpeta is None:
        return error
    ok, salida = _correr("status", ["--short", "--branch"], carpeta)
    if not ok:
        return salida
    if not salida.strip():
        return f"El repositorio de {carpeta} no tiene cambios sin guardar."
    return f"Estado de {carpeta}:\n\n{_recortar(salida)}"


def diff(ruta: str = "", archivo: str = "", raices: Optional[List[str]] = None) -> str:
    """Return el diff del repositorio, opcionalmente acotado a un archivo."""
    carpeta, error = _repo_de(ruta, raices)
    if carpeta is None:
        return error

    argumentos: List[str] = []
    if str(archivo or "").strip():
        activas = raices_efectivas(raices)
        real = resolver(archivo, activas)
        # `--` separa rutas de opciones: aunque la ruta empezara con un guion, git la trata
        # como archivo y nunca como bandera. Se pasa relativa al repo, no absoluta.
        try:
            relativa = os.path.relpath(real, carpeta)
        except ValueError:
            return "Ese archivo no está dentro del repositorio que estoy mirando."
        if relativa.startswith(".."):
            return "Ese archivo no está dentro del repositorio que estoy mirando."
        argumentos = ["--", relativa]

    ok, salida = _correr("diff", argumentos, carpeta)
    if not ok:
        return salida
    if not salida.strip():
        objetivo = f" en {archivo}" if archivo else ""
        return f"No hay cambios sin confirmar{objetivo} en {carpeta}."
    return f"Diff de {carpeta}:\n\n{_recortar(salida)}"


def log(ruta: str = "", cantidad: int = 10, raices: Optional[List[str]] = None) -> str:
    """Return los últimos commits del repositorio de una carpeta habilitada."""
    carpeta, error = _repo_de(ruta, raices)
    if carpeta is None:
        return error
    try:
        n = int(cantidad)
    except (TypeError, ValueError):
        n = 10
    n = max(1, min(n, _MAX_COMMITS))

    ok, salida = _correr(
        "log", [f"-n{n}", "--date=short", "--pretty=format:%h %ad %an %s"], carpeta
    )
    if not ok:
        return salida
    if not salida.strip():
        return f"El repositorio de {carpeta} todavía no tiene commits."
    return f"Últimos {n} commits de {carpeta}:\n\n{_recortar(salida)}"


__all__ = [
    "SUBCOMANDOS_PERMITIDOS",
    "RutaFueraDeRaiz",
    "estado",
    "diff",
    "log",
]
