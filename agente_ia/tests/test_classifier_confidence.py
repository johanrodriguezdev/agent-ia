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

from intent.ai_classifier import (MIN_DECISION_MARGIN, MIN_DECISION_SCORE,
                                  IntentClassifierSystem)
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

# ── El texto que no se parece a NADA tampoco ejecuta ────────────────
#
# `MIN_DECISION_MARGIN` compara la primera clase con la segunda: responde "cual de las
# dos", no "es alguna de ellas". Un texto que queda del lado equivocado del hiperplano de
# TODAS las clases puede igual estar un poco mas cerca de una y colarse con margen de
# sobra. Para eso esta `MIN_DECISION_SCORE`.

_JSON_DE_COSECHA = (
    '[{"ini": 0, "fin": 12, "color": "#92D050", "label": "0 - 12 dias" },'
    '{"ini": 13, "fin": 16, "color": "#ECEF12", "label": "13 - 16 dias"},'
    '{"ini": 17, "fin":20, "color": "#DF720D", "label": "17 - 20 dias"},'
    '{"ini": 21, "fin": 1000, "color": "#DE0000", "label": "> 20 dias"}] '
    "este json con diferentes colores quiero que me ayudes a mejorar esta visualizacion "
    "para que le asignes otra paleta de colores mejor, esto es para los ciclos de cosecha."
)


def test_un_json_de_colores_no_termina_en_la_calculadora(clasificador):
    """El caso real que lo destapo. `clean_text()` deja "ini 0 fin 12 color 92d050 label
    0 12 dias ..." —una sopa de numeros— y el SVM lo mandaba a CALCULATE con la ganadora
    en -0.245: margen 0.29, suficiente para el umbral relativo. El usuario pidio mejorar
    una paleta de colores y recibio "0 x 12 = 0", porque el modelo nunca vio el mensaje."""
    assert clasificador.predict(_JSON_DE_COSECHA) == Intent.UNKNOWN.value


@pytest.mark.parametrize("frase", [
    "que opinas de esta paleta de colores",       # -0.35 — iba a RECALL_MEMORY
    "mejora este json de colores para los ciclos de cosecha",   # -0.62 — iba a CREATE_SKILL
    "revisa este codigo y dime que esta mal",
    "como interpretas estos datos",
    # "ayudame a redactar un correo" NO va aca: cae en SEND_EMAIL, y esta bien que caiga.
    # La skill de correo pide lo que le falta ("a quien?") en vez de inventarlo, asi que
    # el usuario recibe una pregunta, no una accion equivocada. Lo que este umbral tiene
    # que frenar es lo que se ejecuta a ciegas, no lo que sabe preguntar.
])
def test_pedir_analisis_no_ejecuta_un_intent(clasificador, frase):
    """Pedirle al agente que piense sobre algo no es darle una orden al sistema."""
    assert clasificador.predict(frase) == Intent.UNKNOWN.value


@pytest.mark.parametrize("frase,esperado", [
    ("abre la calculadora", "OPEN_APP"),
    ("multiplica 40 por 60", "CALCULATE"),
    ("sube el volumen", "SYS_VOL_UP"),
    ("toma una captura", "TAKE_SCREENSHOT"),
    ("apaga el computador", "SYS_POWER_OFF"),
    ("que hora es", "GET_TIME"),
])
def test_el_piso_absoluto_no_se_lleva_por_delante_las_ordenes(clasificador, frase, esperado):
    """La otra mitad: las ordenes reales puntuan entre +0.42 y +0.85, muy por encima."""
    assert clasificador.predict(frase) == esperado


def test_el_piso_es_el_lado_correcto_del_hiperplano(clasificador):
    """Fija el criterio, no el numero: por debajo de cero el texto no se parece a ninguna
    clase, y ahi no hay orden que ejecutar."""
    assert MIN_DECISION_SCORE == 0.0
