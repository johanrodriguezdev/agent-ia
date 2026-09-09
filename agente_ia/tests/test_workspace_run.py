"""
tests/test_workspace_run.py
REQ-032 — `core/workspace_run.py`: correr un comando en la carpeta del proyecto.

Es lo que cierra el ciclo de depuración. Antes de esto el agente podía escribir código pero
no enterarse de si funciona, que es la mitad de programar.

Todo corre dentro de `tmp_path` y con el intérprete de Python del propio entorno
(`sys.executable`), nunca con herramientas que pueden no estar instaladas
(.claude/rules/testing.md).
"""

import os
import sys

import pytest

from core.workspace_files import RutaFueraDeRaiz
from core.workspace_run import Resultado, describir, ejecutar


@pytest.fixture
def repo(tmp_path):
    """Un proyecto de mentira, habilitado como única raíz."""
    carpeta = tmp_path / "proyecto"
    carpeta.mkdir()
    return str(carpeta.resolve())


def _py(codigo: str) -> str:
    """Un comando que corre `codigo` con el mismo Python que corre los tests."""
    return f'"{sys.executable}" -c "{codigo}"'


# ─────────────────────────── CA-01 / CA-02: dónde corre ───────────────────────────

def test_corre_dentro_de_la_carpeta_habilitada(repo):
    """No alcanza con que ejecute: tiene que ejecutar EN el proyecto. Si corriera en el
    directorio del agente, un `pytest` correría la suite equivocada."""
    resultado = ejecutar(_py("import os; print(os.getcwd())"), raices=[repo])

    assert resultado.codigo == 0
    assert os.path.realpath(resultado.salida.strip()) == os.path.realpath(repo)


def test_sin_carpetas_habilitadas_no_ejecuta_nada():
    with pytest.raises(RutaFueraDeRaiz):
        ejecutar("echo hola", raices=[])


def test_una_ruta_fuera_de_las_raices_se_rechaza(repo, tmp_path):
    afuera = tmp_path / "otro-lado"
    afuera.mkdir()
    with pytest.raises(RutaFueraDeRaiz):
        ejecutar("echo hola", ruta=str(afuera), raices=[repo])


def test_con_varias_raices_y_sin_ruta_pide_elegir(tmp_path):
    """Correr la suite en el repositorio equivocado es peor que preguntar."""
    uno = tmp_path / "uno"
    dos = tmp_path / "dos"
    uno.mkdir()
    dos.mkdir()

    with pytest.raises(RutaFueraDeRaiz):
        ejecutar("echo hola", raices=[str(uno), str(dos)])


def test_un_comando_vacio_no_se_ejecuta(repo):
    with pytest.raises(ValueError):
        ejecutar("   ", raices=[repo])


# ─────────────────────────── CA-03: la salida completa ───────────────────────────

def test_devuelve_el_codigo_de_salida(repo):
    resultado = ejecutar(_py("raise SystemExit(3)"), raices=[repo])

    assert resultado.codigo == 3


def test_devuelve_stderr_y_no_solo_stdout(repo):
    """El error va por stderr: sin esto, depurar es adivinar."""
    resultado = ejecutar(
        _py("import sys; print('normal'); print('el fallo', file=sys.stderr)"), raices=[repo]
    )

    assert "normal" in resultado.salida
    assert "el fallo" in resultado.salida


def test_un_traceback_llega_entero(repo):
    """Lo que hace útil a esta herramienta es justamente esto."""
    (os.path.join(repo, "roto.py"))
    with open(os.path.join(repo, "roto.py"), "w", encoding="utf-8") as f:
        f.write("def f():\n    return 1 / 0\n\nf()\n")

    resultado = ejecutar(f'"{sys.executable}" roto.py', raices=[repo])

    assert resultado.codigo != 0
    assert "ZeroDivisionError" in resultado.salida
    assert "roto.py" in resultado.salida


# ─────────────────────────── CA-04 / CA-05: topes ───────────────────────────

def test_una_salida_enorme_se_recorta_conservando_el_final(repo):
    """El final es donde pytest pone los fallos y el resumen. Recortar por el principio
    dejaría justo lo que no sirve."""
    resultado = ejecutar(
        _py("print('R' * 40000); print('EL-FINAL-QUE-IMPORTA')"), raices=[repo]
    )

    assert resultado.truncada is True
    assert "EL-FINAL-QUE-IMPORTA" in resultado.salida
    assert "recortados" in resultado.salida


def test_un_comando_colgado_se_corta_y_se_avisa(repo):
    """Un `--watch` o un servidor no pueden dejar el turno esperando para siempre."""
    resultado = ejecutar(_py("import time; time.sleep(30)"), raices=[repo], timeout=1)

    assert resultado.expiro is True
    assert resultado.codigo != 0


def test_el_timeout_tiene_techo(repo):
    """Un timeout absurdo pedido por el modelo se acota."""
    from core.workspace_run import TIMEOUT_MAXIMO

    resultado = ejecutar(_py("print('rapido')"), raices=[repo], timeout=999_999)

    assert resultado.codigo == 0  # no se cuelga: el techo no rompe lo que termina rápido
    assert TIMEOUT_MAXIMO == 600


# ─────────────────────────── el texto que lee el modelo ───────────────────────────

def test_describir_dice_el_codigo_y_la_carpeta():
    texto = describir(Resultado(codigo=1, salida="algo falló", carpeta="C:/repo"))

    assert "código 1" in texto
    assert "C:/repo" in texto
    assert "algo falló" in texto


def test_describir_avisa_cuando_expiro():
    texto = describir(Resultado(codigo=-1, salida="", carpeta="C:/repo", expiro=True))

    assert "no terminó a tiempo" in texto


# ─────────────────── CA-15: el ciclo completo de desarrollo ───────────────────

def test_el_ciclo_correr_leer_corregir_volver_a_correr(repo):
    """La prueba que justifica el REQ entero: el agente encuentra un bug corriendo el
    proyecto, lo corrige con las herramientas que ya tenía, y comprueba que quedó bien.

    Se usa un script de comprobación en vez de pytest anidado a propósito: lo que se prueba
    es el CICLO, no la integración con un runner concreto.
    """
    from core.workspace_files import editar

    with open(os.path.join(repo, "calculadora.py"), "w", encoding="utf-8") as f:
        f.write("def sumar(a, b):\n    return a - b\n")   # el bug
    with open(os.path.join(repo, "comprobar.py"), "w", encoding="utf-8") as f:
        f.write("from calculadora import sumar\n"
                "assert sumar(2, 2) == 4, 'sumar(2,2) deberia dar 4'\n"
                "print('TODO BIEN')\n")

    # 1. correr: falla, y el error dice qué pasó
    primera = ejecutar(f'"{sys.executable}" comprobar.py', raices=[repo])
    assert primera.codigo != 0
    assert "AssertionError" in primera.salida

    # 2. corregir con la herramienta de edición de REQ-029
    editar("calculadora.py", "return a - b", "return a + b", raices=[repo])

    # 3. volver a correr: ahora pasa
    segunda = ejecutar(f'"{sys.executable}" comprobar.py', raices=[repo])
    assert segunda.codigo == 0
    assert "TODO BIEN" in segunda.salida
