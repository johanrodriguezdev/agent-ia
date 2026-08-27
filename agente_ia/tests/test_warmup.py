"""
tests/test_warmup.py
Pruebas de `core/warmup.py` — la precarga en segundo plano del arranque.

Este módulo corre en el arranque de la aplicación, así que lo que protege esta suite no es
que precargue rápido, sino que **no pueda estropear el arranque**: no bloquea, no duplica
trabajo, y un fallo cargando cualquier cosa no impide que la aplicación funcione ni que las
demás se carguen.

Ningún test carga los modelos reales: las tareas se sustituyen por simulaciones.
"""

import threading
import time

import pytest

from core import warmup


@pytest.fixture(autouse=True)
def _reset():
    # Esperar al hilo del test anterior antes de empezar: `start_warmup()` no arranca si ya
    # hay uno vivo, asi que un hilo rezagado hacia que el test siguiente no precargara nada
    # y fallara por un motivo que no tenia que ver con lo que estaba probando.
    if warmup._hilo is not None:
        warmup._hilo.join(timeout=3)
    warmup._terminado.clear()
    warmup._hilo = None
    originales = list(warmup._TAREAS)
    yield
    if warmup._hilo is not None:
        warmup._hilo.join(timeout=3)
    warmup._TAREAS = originales
    warmup._terminado.clear()
    warmup._hilo = None


def _tarea_falsa(registro, nombre, demora=0.0):
    def _t():
        if demora:
            time.sleep(demora)
        registro.append(nombre)
    return _t


# ── No bloquea ──────────────────────────────────────────────────────

def test_arrancar_la_precarga_devuelve_el_control_de_inmediato():
    """Si bloqueara, la ventana tardaría un minuto en aparecer."""
    hechas = []
    warmup._TAREAS = [("lenta", _tarea_falsa(hechas, "lenta", demora=0.4))]

    t0 = time.time()
    warmup.start_warmup()
    transcurrido = time.time() - t0

    assert transcurrido < 0.15          # volvió sin esperar a la tarea
    assert warmup.esperar(timeout=3) is True
    assert hechas == ["lenta"]


def test_el_hilo_es_daemon_para_no_retener_el_cierre():
    warmup._TAREAS = [("x", _tarea_falsa([], "x", demora=0.2))]

    warmup.start_warmup()

    assert warmup._hilo.daemon is True


# ── No duplica trabajo ──────────────────────────────────────────────

def test_llamarlo_dos_veces_no_precarga_dos_veces():
    hechas = []
    warmup._TAREAS = [("una", _tarea_falsa(hechas, "una", demora=0.3))]

    warmup.start_warmup()
    warmup.start_warmup()          # mientras la primera sigue viva
    warmup.esperar(timeout=3)

    assert hechas == ["una"]


# ── No puede romper el arranque ─────────────────────────────────────

def test_una_tarea_que_falla_no_impide_las_demas():
    """Cada módulo conserva su carga perezosa: lo peor que pasa es volver a como estaba."""
    hechas = []

    def _explota():
        raise RuntimeError("el modelo no está")

    warmup._TAREAS = [
        ("rota", _explota),
        ("buena", _tarea_falsa(hechas, "buena")),
    ]

    warmup.start_warmup()
    warmup.esperar(timeout=3)

    assert hechas == ["buena"]
    assert warmup.esta_lista() is True     # termina igual


def test_si_fallan_todas_la_precarga_termina_sin_lanzar():
    def _explota():
        raise RuntimeError("nada carga hoy")

    warmup._TAREAS = [("a", _explota), ("b", _explota)]

    warmup.start_warmup()

    assert warmup.esperar(timeout=3) is True


# ── Estado ──────────────────────────────────────────────────────────

def test_no_esta_lista_hasta_que_termina():
    arrancada = threading.Event()

    def _lenta():
        arrancada.set()
        time.sleep(0.4)

    warmup._TAREAS = [("lenta", _lenta)]

    warmup.start_warmup()
    arrancada.wait(timeout=2)
    assert warmup.esta_lista() is False

    warmup.esperar(timeout=3)
    assert warmup.esta_lista() is True


def test_el_orden_pone_primero_lo_que_hace_falta_antes():
    """El clasificador se usa en CADA mensaje; los embeddings solo si hay que recordar."""
    nombres = [n for n, _ in warmup._TAREAS]

    assert nombres.index("clasificador de intenciones") < nombres.index("modelo de embeddings")


def test_las_tareas_reales_estan_declaradas():
    nombres = {n for n, _ in warmup._TAREAS}

    assert "clasificador de intenciones" in nombres
    assert "modelo de embeddings" in nombres
    assert all(callable(fn) for _, fn in warmup._TAREAS)
