"""
tests/test_dreaming.py
Pruebas de `core/dreaming.py` — la consolidación automática de la memoria.

Lo que protege esta suite: **que no gaste dinero por su cuenta sin permiso ni sin motivo**.
Destilar cuesta varias llamadas al modelo, así que hay dos frenos: está desactivado salvo
que se active a propósito, y aun activado solo corre si hay material nuevo suficiente.

Ningún test llama al modelo ni espera tiempos reales.
"""

import pytest

from core import dreaming


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(dreaming, "DIARIO_PATH", str(tmp_path / "dreams.md"))
    dreaming._ultimo_total = 0
    dreaming._parar.clear()
    dreaming._hilo = None
    yield
    dreaming._parar.set()
    dreaming._hilo = None


# ── No gastar sin permiso ───────────────────────────────────────────

def test_esta_desactivado_por_defecto(monkeypatch):
    """Algo que consume API por su cuenta se activa a propósito, no por descuido."""
    monkeypatch.setattr("config_manager.load_config", lambda: {})

    assert dreaming.esta_activo() is False


def test_si_no_se_puede_leer_la_configuracion_no_se_asume_que_si(monkeypatch):
    def _explota():
        raise RuntimeError("configuración ilegible")

    monkeypatch.setattr("config_manager.load_config", _explota)

    assert dreaming.esta_activo() is False


def test_desactivado_no_deja_ni_un_hilo_de_fondo(monkeypatch):
    monkeypatch.setattr(dreaming, "esta_activo", lambda: False)

    assert dreaming.start_dreaming() is False
    assert dreaming._hilo is None


def test_activado_arranca_el_hilo(monkeypatch):
    monkeypatch.setattr(dreaming, "esta_activo", lambda: True)

    assert dreaming.start_dreaming() is True
    assert dreaming._hilo is not None and dreaming._hilo.daemon is True

    dreaming.stop_dreaming()


# ── No gastar sin motivo ────────────────────────────────────────────

def test_sin_material_nuevo_no_destila(monkeypatch):
    """Repetir la destilación sobre las mismas conversaciones paga por reescribir lo mismo."""
    llamadas = []
    monkeypatch.setattr(dreaming, "_contar_memorias", lambda uid: 100)
    monkeypatch.setattr(
        "skills.memory_digest_skill.MemoryDigestSkill.execute",
        lambda self, i, p: llamadas.append(1) or "destilado",
    )
    dreaming._ultimo_total = 100

    resultado = dreaming.ejecutar_una_pasada("owner")

    assert "Sin cambios suficientes" in resultado
    assert llamadas == []


def test_con_suficiente_material_nuevo_si_destila(monkeypatch):
    llamadas = []
    monkeypatch.setattr(dreaming, "_contar_memorias", lambda uid: 200)
    monkeypatch.setattr(
        "skills.memory_digest_skill.MemoryDigestSkill.execute",
        lambda self, i, p: llamadas.append(1) or "37 hechos",
    )
    dreaming._ultimo_total = 100

    resultado = dreaming.ejecutar_una_pasada("owner")

    assert llamadas == [1]
    assert "37 hechos" in resultado


def test_forzar_salta_el_umbral(monkeypatch):
    llamadas = []
    monkeypatch.setattr(dreaming, "_contar_memorias", lambda uid: 100)
    monkeypatch.setattr(
        "skills.memory_digest_skill.MemoryDigestSkill.execute",
        lambda self, i, p: llamadas.append(1) or "destilado",
    )
    dreaming._ultimo_total = 100

    dreaming.ejecutar_una_pasada("owner", forzar=True)

    assert llamadas == [1]


def test_la_primera_pasada_siempre_destila(monkeypatch):
    """Sin marca previa no hay con qué comparar: se destila y se toma esa como referencia."""
    llamadas = []
    monkeypatch.setattr(dreaming, "_contar_memorias", lambda uid: 5)
    monkeypatch.setattr(
        "skills.memory_digest_skill.MemoryDigestSkill.execute",
        lambda self, i, p: llamadas.append(1) or "destilado",
    )

    dreaming.ejecutar_una_pasada("owner")

    assert llamadas == [1]


# ── Poder explicarse después ────────────────────────────────────────

def test_cada_pasada_queda_registrada_en_el_diario(monkeypatch):
    """Un proceso que reescribe tu memoria mientras no miras tiene que poder explicarse."""
    import os

    monkeypatch.setattr(dreaming, "_contar_memorias", lambda uid: 200)
    monkeypatch.setattr(
        "skills.memory_digest_skill.MemoryDigestSkill.execute",
        lambda self, i, p: "37 hechos consolidados",
    )
    dreaming._ultimo_total = 100

    dreaming.ejecutar_una_pasada("owner")

    assert os.path.exists(dreaming.DIARIO_PATH)
    with open(dreaming.DIARIO_PATH, encoding="utf-8") as f:
        contenido = f.read()
    assert "37 hechos consolidados" in contenido
    assert "200 memorias revisadas" in contenido


def test_una_pasada_sin_destilar_no_ensucia_el_diario(monkeypatch):
    import os

    monkeypatch.setattr(dreaming, "_contar_memorias", lambda uid: 100)
    dreaming._ultimo_total = 100

    dreaming.ejecutar_una_pasada("owner")

    assert not os.path.exists(dreaming.DIARIO_PATH)


# ── Degradación ─────────────────────────────────────────────────────

def test_si_la_destilacion_falla_no_se_propaga(monkeypatch):
    monkeypatch.setattr(dreaming, "_contar_memorias", lambda uid: 200)
    monkeypatch.setattr(
        "skills.memory_digest_skill.MemoryDigestSkill.execute",
        lambda self, i, p: (_ for _ in ()).throw(RuntimeError("el modelo no responde")),
    )
    dreaming._ultimo_total = 100

    resultado = dreaming.ejecutar_una_pasada("owner")

    assert "Falló la destilación" in resultado


def test_un_fallo_no_actualiza_la_referencia(monkeypatch):
    """Si falló, la próxima vez debe volver a intentarlo, no darlo por hecho."""
    monkeypatch.setattr(dreaming, "_contar_memorias", lambda uid: 200)
    monkeypatch.setattr(
        "skills.memory_digest_skill.MemoryDigestSkill.execute",
        lambda self, i, p: (_ for _ in ()).throw(RuntimeError("caído")),
    )
    dreaming._ultimo_total = 100

    dreaming.ejecutar_una_pasada("owner")

    assert dreaming._ultimo_total == 100


def test_los_umbrales_estan_fijados():
    """Moverlos cambia cuánto gasta el agente por su cuenta."""
    assert dreaming.MIN_MEMORIAS_NUEVAS == 25
    assert dreaming.INTERVALO_SEGUNDOS == 6 * 3600
