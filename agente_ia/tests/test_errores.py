"""
tests/test_errores.py
REQ-072 — un fallo se le cuenta al usuario, no se le vuelca encima (§12 de la spec).

Lo que protege esta suite:

- **Que el usuario lea una causa, no un volcado.** «no tengo permisos para hacerlo», no
  «[WinError 5] Acceso denegado».
- **Que el detalle técnico no se pierda**: va al log, y se puede pedir.
- **Que no se invente la causa.** Una excepción que no se reconoce se nombra como lo que
  es; un diagnóstico equivocado manda al usuario a buscar donde no es.
"""

import errno
import json
import socket
import subprocess

import pytest

from core import errores


@pytest.mark.parametrize("excepcion, esperado", [
    (PermissionError(), "no tengo permisos"),
    (FileNotFoundError(), "no encuentro el archivo"),
    (FileExistsError(), "ya existe"),
    (IsADirectoryError(), "es una carpeta"),
    (TimeoutError(), "tardó demasiado"),
    (subprocess.TimeoutExpired("cmd", 5), "tardó demasiado"),
    (ConnectionRefusedError(), "se cortó la conexión"),
    (socket.gaierror(), "no pude resolver la dirección"),
    (MemoryError(), "sin memoria"),
    (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "malo"), "codificación"),
])
def test_cada_fallo_se_explica_en_castellano_llano(excepcion, esperado):
    assert esperado in errores.causa(excepcion)


def test_los_codigos_del_sistema_se_traducen():
    sin_espacio = OSError(errno.ENOSPC, "No space left on device")
    en_uso = OSError()
    en_uso.winerror = 32

    assert "no queda espacio" in errores.causa(sin_espacio)
    assert "abierto en otro programa" in errores.causa(en_uso)


def test_falta_un_componente_dice_cual():
    assert "pywin32" in errores.causa(ModuleNotFoundError(name="pywin32"))


def test_lo_que_no_se_reconoce_no_se_inventa():
    """Decir «parece un problema de permisos» cuando no se sabe es peor que no decirlo."""
    motivo = errores.causa(ValueError("algo raro"))

    assert "no supe interpretar" in motivo
    assert "ValueError" in motivo                 # el tipo sí es un dato real
    assert "permiso" not in motivo


def test_el_mensaje_para_el_usuario_dice_que_se_intentaba():
    mensaje = errores.explicar(PermissionError(), "abrir Spotify")

    assert mensaje == "No pude abrir Spotify: no tengo permisos para hacerlo."


def test_sin_saber_que_se_intentaba_igual_sale_una_frase_entera():
    assert errores.explicar(FileNotFoundError()).startswith("No pude completar la operación:")


def test_el_mensaje_no_lleva_rutas_ni_volcados():
    """Lo que la §12 prohíbe: «[Errno 2] No such file or directory: 'C:\\Users\\...'»."""
    e = FileNotFoundError(2, "No such file or directory", r"C:\Users\Johan\secreto.docx")

    mensaje = errores.explicar(e, "leer el informe")

    assert "secreto.docx" not in mensaje
    assert "Errno" not in mensaje
    assert "C:\\" not in mensaje


def test_el_detalle_tecnico_queda_en_el_log(caplog):
    import logging

    with caplog.at_level(logging.ERROR):
        errores.explicar(PermissionError(13, "Permission denied"), "abrir Spotify")

    registrado = caplog.text
    assert "PermissionError" in registrado          # el detalle sí, pero en el log
    assert "Permission denied" in registrado


def test_el_detalle_se_puede_pedir():
    detalle = errores.detalle_tecnico(PermissionError(13, "Permission denied"))

    assert "PermissionError" in detalle
    assert "código 13" in detalle
    assert "\n" not in detalle                      # una línea, no un volcado de pila


def test_los_caminos_mas_usados_ya_lo_usan():
    """Abrir un programa o usar la terminal son de lo que más se pide; si esos siguen
    devolviendo la excepción cruda, el REQ no se nota."""
    import inspect

    from agents import action_registry
    from automation import pc_controller

    for modulo in (action_registry, pc_controller):
        fuente = inspect.getsource(modulo)
        assert "from core.errores import explicar" in fuente, modulo.__name__
        assert 'f"Error al abrir Chrome: {e}"' not in fuente
