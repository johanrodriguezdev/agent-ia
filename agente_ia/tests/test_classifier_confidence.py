"""
tests/test_classifier_confidence.py
Pruebas del umbral de confianza de `intent/ai_classifier.py`.

`LinearSVC` no sabe decir "no sé": siempre devuelve la clase más cercana. Sin umbral,
"el viernes" cerraba una aplicación llamada "el viernes" y "manana a las 9" lanzaba una
búsqueda por todo el disco del usuario. Estas pruebas fijan el comportamiento en los dos
sentidos: que el ruido deje de ejecutarse, y que los comandos reales sigan funcionando.

Los márgenes citados están medidos sobre el modelo entrenado del proyecto.
"""

import pytest

from intent.ai_classifier import MIN_DECISION_MARGIN, IntentClassifierSystem
from intent.intentions import Intent


@pytest.fixture(scope="module")
def clasificador():
    return IntentClassifierSystem()


# ── El ruido deja de ejecutarse ─────────────────────────────────────

@pytest.mark.parametrize("frase", [
    "el viernes",            # margen 0.03 — iba a CLOSE_APP
    "manana a las 9",        # margen 0.15 — iba a FIND_LARGEST (recorría el disco entero)
    "hola que tal",          # margen 0.03
    "olvidalo",              # margen 0.01
    "que opinas de esto",    # margen 0.00
])
def test_las_frases_ambiguas_no_ejecutan_un_intent(clasificador, frase):
    assert clasificador.predict(frase) == Intent.UNKNOWN.value


def test_una_frase_de_fecha_suelta_no_dispara_una_busqueda_de_disco(clasificador):
    """El caso concreto que encontró la auditoría: era una denegación de servicio."""
    assert clasificador.predict("manana a las 9") != "FIND_LARGEST"


# ── Los comandos reales siguen funcionando ──────────────────────────

@pytest.mark.parametrize("frase,esperado", [
    ("abre la calculadora", "OPEN_APP"),
    ("cierra chrome", "CLOSE_APP"),
    ("toma una captura", "TAKE_SCREENSHOT"),
    ("que hora es", "GET_TIME"),
    ("cuanto es 2 mas 2", "CALCULATE"),
    ("suma 3 mas 4", "CALCULATE"),            # margen 0.38, el legítimo más ajustado
    ("apaga el pc", "SYS_POWER_OFF"),
    ("cuanta memoria ram tengo", "RAM_INFO"),
    ("pon musica en youtube", "PLAY_MUSIC"),
    ("abre la carpeta de descargas", "OPEN_FOLDER"),
])
def test_los_comandos_legitimos_sobreviven_al_umbral(clasificador, frase, esperado):
    assert clasificador.predict(frase) == esperado


# ── Mecánica del margen ─────────────────────────────────────────────

def test_el_margen_separa_la_ganadora_de_la_siguiente(clasificador):
    from nlp.parser import clean_text

    margen = clasificador._decision_margin(clean_text("cierra chrome"))

    assert margen is not None
    assert margen > MIN_DECISION_MARGIN


def test_sin_decision_function_no_se_filtra_nada(clasificador, monkeypatch):
    """Degradación: si el pipeline no expone confianza, se comporta como antes del umbral."""
    class _SinConfianza:
        def predict(self, _x):
            return ["OPEN_APP"]

        def decision_function(self, _x):
            raise AttributeError("este pipeline no la expone")

    monkeypatch.setattr(clasificador, "pipeline", _SinConfianza())

    assert clasificador.predict("cualquier cosa") == "OPEN_APP"


def test_un_margen_no_medible_no_bloquea(clasificador, monkeypatch):
    """Con una sola clase no hay 'siguiente': no se puede medir y no se filtra."""
    class _UnaClase:
        def predict(self, _x):
            return ["OPEN_APP"]

        def decision_function(self, _x):
            return [[0.4]]

    monkeypatch.setattr(clasificador, "pipeline", _UnaClase())

    assert clasificador.predict("abre algo") == "OPEN_APP"


def test_el_umbral_esta_fijado():
    """Moverlo cambia qué frases se ejecutan sin pasar por el modelo."""
    assert MIN_DECISION_MARGIN == 0.25
