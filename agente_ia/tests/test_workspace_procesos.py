"""
tests/test_workspace_procesos.py
REQ-036 — `core/workspace_procesos.py`: procesos que no terminan.

`project_run` espera a que el comando termine, así que un servidor de desarrollo siempre
acababa igual: muerto por el timeout a los 120 segundos. Esto lo deja vivo.

Todos los procesos se lanzan con `sys.executable` (el mismo Python que corre los tests) y
la fixture `sin_procesos` garantiza que ninguno sobreviva al test, pase lo que pase.
"""

import os
import sys
import time

import pytest

import core.workspace_procesos as wp
from core.workspace_files import RutaFueraDeRaiz


@pytest.fixture(autouse=True)
def sin_procesos():
    """Ningún test puede dejar un proceso vivo en la máquina de nadie."""
    yield
    wp.cerrar_todos()


@pytest.fixture
def repo(tmp_path):
    carpeta = tmp_path / "proyecto"
    carpeta.mkdir()
    return str(carpeta.resolve())


def _py(codigo: str) -> str:
    return f'"{sys.executable}" -c "{codigo}"'


def _esperar(condicion, limite: float = 5.0) -> bool:
    """Espera activa corta: los procesos tardan un poco en escribir su primera línea."""
    comenzo = time.monotonic()
    while time.monotonic() - comenzo < limite:
        if condicion():
            return True
        time.sleep(0.05)
    return False


# ─────────────────────────── arrancar ───────────────────────────

def test_un_proceso_largo_queda_vivo(repo):
    """El caso que motiva el REQ: con project_run, esto moría por timeout."""
    vivo = wp.iniciar(_py("import time; time.sleep(30)"), raices=[repo])

    assert vivo.vivo is True
    assert vivo.identificador
    assert vivo.carpeta == os.path.realpath(repo)


def test_la_salida_se_va_acumulando(repo):
    vivo = wp.iniciar(
        _py("import time,sys\nfor i in range(5):\n    print('linea', i); sys.stdout.flush(); time.sleep(0.1)"),
        raices=[repo],
    )

    assert _esperar(lambda: "linea 4" in vivo.salida()), f"salida: {vivo.salida()!r}"


def test_el_error_tambien_llega_no_solo_lo_normal(repo):
    """stderr va al mismo buffer: un servidor que revienta al arrancar lo dice por ahí."""
    vivo = wp.iniciar(
        _py("import sys; print('el fallo', file=sys.stderr); sys.stderr.flush()"),
        raices=[repo],
    )

    assert _esperar(lambda: "el fallo" in vivo.salida())


def test_no_arranca_nada_fuera_de_las_carpetas_habilitadas(repo, tmp_path):
    afuera = tmp_path / "otro-lado"
    afuera.mkdir()

    with pytest.raises(RutaFueraDeRaiz):
        wp.iniciar(_py("print(1)"), ruta=str(afuera), raices=[repo])


def test_sin_carpetas_habilitadas_no_arranca_nada():
    with pytest.raises(RutaFueraDeRaiz):
        wp.iniciar("echo hola", raices=[])


def test_un_comando_vacio_no_arranca(repo):
    with pytest.raises(ValueError):
        wp.iniciar("   ", raices=[repo])


def test_hay_un_tope_de_procesos_simultaneos(repo):
    """Sin tope, un bucle del modelo levanta cincuenta servidores mientras nadie mira."""
    for _ in range(wp.MAX_PROCESOS):
        wp.iniciar(_py("import time; time.sleep(30)"), raices=[repo])

    with pytest.raises(RuntimeError):
        wp.iniciar(_py("import time; time.sleep(30)"), raices=[repo])


# ─────────────────────────── mirar y detener ───────────────────────────

def test_detener_mata_el_proceso(repo):
    vivo = wp.iniciar(_py("import time; time.sleep(30)"), raices=[repo])

    salida = wp.detener(vivo.identificador)

    assert vivo.vivo is False
    assert "Detuve" in salida
    assert wp.obtener(vivo.identificador) is None


def test_detener_uno_que_no_existe_lo_dice_sin_reventar():
    assert "No tengo" in wp.detener("p9999")


def test_un_proceso_que_termino_solo_se_reporta_como_terminado(repo):
    vivo = wp.iniciar(_py("print('listo')"), raices=[repo])

    assert _esperar(lambda: not vivo.vivo)
    assert "terminado" in wp.describir(vivo)


def test_listar_muestra_los_que_estan_vivos(repo):
    wp.iniciar(_py("import time; time.sleep(30)"), raices=[repo])
    wp.iniciar(_py("import time; time.sleep(30)"), raices=[repo])

    assert len(wp.listar()) == 2


def test_cerrar_todos_no_deja_nada_corriendo(repo):
    """Lo que evita el servidor huérfano ocupando el puerto 3000 después de cerrar la app."""
    procesos = [wp.iniciar(_py("import time; time.sleep(30)"), raices=[repo]) for _ in range(3)]

    cerrados = wp.cerrar_todos()

    assert cerrados == 3
    assert wp.listar() == []
    for p in procesos:
        assert p.vivo is False


def test_la_salida_no_crece_sin_freno(repo):
    """Un servidor que loguea cada petición llenaría la memoria en una tarde."""
    vivo = wp.iniciar(
        _py(f"for i in range({wp.MAX_LINEAS + 200}): print('linea', i)"),
        raices=[repo],
    )
    _esperar(lambda: not vivo.vivo, limite=10)

    assert len(vivo.lineas) <= wp.MAX_LINEAS


def test_describir_dice_comando_carpeta_y_estado(repo):
    vivo = wp.iniciar(_py("import time; time.sleep(30)"), raices=[repo])

    texto = wp.describir(vivo)

    assert vivo.identificador in texto
    assert "corriendo" in texto
    assert repo.split(os.sep)[-1] in texto
