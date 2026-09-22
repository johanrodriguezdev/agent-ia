"""
tests/test_plataforma.py
Pruebas de `os_integration/plataforma` — REQ-068, las acciones del sistema por adaptador.

Lo que protege esta suite:

- **Windows no cambió.** Apagar sigue siendo `shutdown /s /t`, cerrar sigue siendo el par
  `tasklist`/`taskkill`, y abrir una carpeta sigue siendo `explorer.exe`. Eso se comprueba
  sobre el adaptador de Windows aunque la suite corra en Linux.
- **Linux hace lo equivalente, no lo mismo.** `systemctl`, `pkill`, `xdg-open`.
- **Lo que no se puede, se dice.** Sin permiso para apagar, dentro de un contenedor, o sin
  la herramienta instalada, la respuesta explica el motivo en vez de fallar en silencio:
  un «no tengo permiso» es una respuesta, un cuelgue no lo es.

Los dos adaptadores se importan y se prueban en cualquier sistema: lo que se simula es el
`subprocess`, nunca se apaga nada.
"""

import subprocess
import types

import pytest

from os_integration.plataforma import _linux, _windows


class _Resultado:
    """Lo que devuelve `subprocess.run`, con lo justo que el código mira."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ------------------------------------------------------------------ la elección del adaptador

def test_se_elige_el_adaptador_del_sistema_en_el_que_se_corre():
    import os as _os

    from os_integration import plataforma

    esperado = "Windows" if _os.name == "nt" else "Linux"
    assert plataforma.NOMBRE == esperado
    assert plataforma.actual.NOMBRE == esperado


def test_los_dos_adaptadores_ofrecen_lo_mismo():
    """Si uno gana una función y el otro no, el agente hace cosas distintas según el
    sistema sin que nadie lo haya decidido."""
    publicas = {n for n in dir(_windows) if not n.startswith("_") and callable(getattr(_windows, n))}
    publicas_linux = {n for n in dir(_linux) if not n.startswith("_") and callable(getattr(_linux, n))}

    esperadas = {"apagar", "reiniciar", "cerrar_aplicacion", "abrir_carpeta", "abrir_aplicacion"}
    assert esperadas <= publicas
    assert esperadas <= publicas_linux


# ------------------------------------------------------------------ Windows, como estaba

def test_windows_apaga_con_shutdown(monkeypatch):
    ordenes = []
    monkeypatch.setattr(_windows.os, "system", lambda c: ordenes.append(c) or 0)

    respuesta = _windows.apagar(5)

    assert ordenes == ["shutdown /s /t 5"]
    assert "apagará en 5 segundos" in respuesta


def test_windows_reinicia_con_shutdown_r(monkeypatch):
    ordenes = []
    monkeypatch.setattr(_windows.os, "system", lambda c: ordenes.append(c) or 0)

    _windows.reiniciar(10)
    assert ordenes == ["shutdown /r /t 10"]


def test_windows_cierra_con_tasklist_y_taskkill(monkeypatch):
    llamadas = []

    def _run(cmd, **kwargs):
        llamadas.append(cmd)
        if cmd[0] == "tasklist":
            return _Resultado(stdout="chrome.exe    1234 Console")
        return _Resultado(returncode=0)

    monkeypatch.setattr(_windows.subprocess, "run", _run)
    respuesta = _windows.cerrar_aplicacion("chrome")

    assert llamadas[0][0] == "tasklist"
    assert llamadas[1] == ["taskkill", "/IM", "chrome.exe", "/F"]
    assert "cerrado exitosamente" in respuesta


def test_windows_dice_que_no_estaba_abierto_sin_matar_nada(monkeypatch):
    llamadas = []

    def _run(cmd, **kwargs):
        llamadas.append(cmd)
        return _Resultado(stdout="INFO: No tasks are running")

    monkeypatch.setattr(_windows.subprocess, "run", _run)
    respuesta = _windows.cerrar_aplicacion("chrome")

    assert len(llamadas) == 1                      # no se llegó a taskkill
    assert "no parece estar ejecutándose" in respuesta


def test_windows_abre_la_carpeta_con_el_explorador(monkeypatch, tmp_path):
    lanzados = []
    monkeypatch.setattr(_windows.subprocess, "Popen", lambda c, **k: lanzados.append(c))

    respuesta = _windows.abrir_carpeta(str(tmp_path))

    assert "explorer.exe" in lanzados[0]
    assert str(tmp_path) in respuesta


# ------------------------------------------------------------------ Linux, lo equivalente

def test_linux_apaga_con_systemctl(monkeypatch):
    llamadas = []
    monkeypatch.setattr(_linux, "_en_contenedor", lambda: False)
    monkeypatch.setattr(_linux.shutil, "which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(_linux.subprocess, "run",
                        lambda cmd, **k: llamadas.append(cmd) or _Resultado(0))

    respuesta = _linux.apagar()

    assert llamadas == [["/usr/bin/systemctl", "poweroff"]]
    assert "se apagará" in respuesta


def test_linux_reinicia_con_systemctl(monkeypatch):
    llamadas = []
    monkeypatch.setattr(_linux, "_en_contenedor", lambda: False)
    monkeypatch.setattr(_linux.shutil, "which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(_linux.subprocess, "run",
                        lambda cmd, **k: llamadas.append(cmd) or _Resultado(0))

    _linux.reiniciar()
    assert llamadas == [["/usr/bin/systemctl", "reboot"]]


def test_linux_sin_permiso_para_apagar_lo_explica(monkeypatch):
    """El caso real de un equipo con varias sesiones o por SSH: logind pide autenticación."""
    monkeypatch.setattr(_linux, "_en_contenedor", lambda: False)
    monkeypatch.setattr(_linux.shutil, "which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(_linux.subprocess, "run", lambda cmd, **k: _Resultado(
        1, stderr="Interactive authentication required."))

    respuesta = _linux.apagar()

    assert "permiso" in respuesta.lower()
    assert "autenticación" in respuesta.lower()


def test_linux_dentro_de_un_contenedor_avisa_en_vez_de_apagarse(monkeypatch):
    """«Apagá el PC» dentro del contenedor cerraría la aplicación, no el equipo."""
    llamadas = []
    monkeypatch.setattr(_linux, "_en_contenedor", lambda: True)
    monkeypatch.setattr(_linux.subprocess, "run",
                        lambda cmd, **k: llamadas.append(cmd) or _Resultado(0))

    respuesta = _linux.apagar()

    assert llamadas == []                          # no se intentó apagar nada
    assert "contenedor" in respuesta.lower()


def test_linux_cierra_con_pkill_y_comprueba_antes(monkeypatch):
    llamadas = []

    def _run(cmd, **kwargs):
        llamadas.append(cmd)
        return _Resultado(0)

    monkeypatch.setattr(_linux.shutil, "which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(_linux.subprocess, "run", _run)

    respuesta = _linux.cerrar_aplicacion("firefox")

    assert llamadas[0] == ["pgrep", "-fi", "firefox"]
    assert llamadas[1] == ["pkill", "-fi", "firefox"]
    assert "cerrado exitosamente" in respuesta


def test_linux_traduce_el_nombre_del_programa(monkeypatch):
    """«cerrá word» en Linux es cerrar LibreOffice, no un WINWORD.EXE que no existe."""
    llamadas = []
    monkeypatch.setattr(_linux.shutil, "which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(_linux.subprocess, "run",
                        lambda cmd, **k: llamadas.append(cmd) or _Resultado(0))

    _linux.cerrar_aplicacion("word")
    assert llamadas[0] == ["pgrep", "-fi", "soffice"]


def test_linux_dice_que_no_estaba_abierto(monkeypatch):
    monkeypatch.setattr(_linux.shutil, "which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(_linux.subprocess, "run", lambda cmd, **k: _Resultado(1))

    assert "no parece estar ejecutándose" in _linux.cerrar_aplicacion("firefox")


def test_linux_abre_la_carpeta_con_xdg_open(monkeypatch, tmp_path):
    lanzados = []
    monkeypatch.setattr(_linux.shutil, "which", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(_linux.subprocess, "Popen", lambda c, **k: lanzados.append(c))

    respuesta = _linux.abrir_carpeta(str(tmp_path))

    assert lanzados == [["/usr/bin/xdg-open", str(tmp_path)]]
    assert str(tmp_path) in respuesta


def test_linux_abre_el_primero_que_este_instalado(monkeypatch):
    """El catálogo lista varios porque cada escritorio trae el suyo."""
    lanzados = []
    monkeypatch.setattr(_linux.shutil, "which",
                        lambda n: "/usr/bin/mousepad" if n == "mousepad" else None)
    monkeypatch.setattr(_linux.subprocess, "Popen", lambda c, **k: lanzados.append(c))

    respuesta = _linux.abrir_aplicacion("bloc de notas")

    assert lanzados == [["/usr/bin/mousepad"]]      # gedit y kate no estaban
    assert "Abriendo" in respuesta


def test_linux_sin_la_aplicacion_devuelve_vacio_para_que_el_caller_lo_diga(monkeypatch):
    monkeypatch.setattr(_linux.shutil, "which", lambda n: None)

    assert _linux.abrir_aplicacion("un-programa-que-nadie-tiene") == ""


def test_linux_sin_la_herramienta_del_sistema_lo_dice(monkeypatch):
    monkeypatch.setattr(_linux, "_en_contenedor", lambda: False)
    monkeypatch.setattr(_linux.shutil, "which", lambda n: None)

    assert "systemctl" in _linux.apagar()
    assert "pkill" in _linux.cerrar_aplicacion("firefox")
    assert "xdg-open" in _linux.abrir_carpeta("/tmp")
