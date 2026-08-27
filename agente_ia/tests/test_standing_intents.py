"""
tests/test_standing_intents.py
Pruebas de `core/standing_intents.py` — recordatorios que se disparan por lo que dices.

Dos invariantes que sostienen esta función:

- **No se dispara cuando no toca.** Un recordatorio que salta en cada frase deja de ser útil
  y pasa a ser ruido: el usuario lo ignora, que es la peor forma de fallar para algo cuyo
  único trabajo es que le hagan caso.
- **No cruza usuarios.** La intención de uno no puede saltarle a otro.

Ningún test usa el reloj real para medir plazos: el tiempo se inyecta.
"""

import os

import pytest

from core import standing_intents as si


@pytest.fixture
def store(tmp_path):
    return si.StandingIntentStore(str(tmp_path / "intents.db"))


# ── Extracción de disparadores ──────────────────────────────────────

def test_los_disparadores_descartan_las_palabras_vacias():
    """"cuando hable del contador" deja "contador", no "cuando" ni "del"."""
    triggers = si.extraer_triggers("cuando hable del contador")

    assert "contador" in triggers
    assert "cuando" not in triggers
    assert "del" not in triggers


def test_las_palabras_muy_cortas_no_sirven_de_disparador():
    """"ok" o "eh" saltarían en cualquier conversación."""
    triggers = si.extraer_triggers("ok eh ya")

    assert triggers == ()


def test_no_se_repiten_disparadores():
    triggers = si.extraer_triggers("factura factura factura contador")

    assert triggers == ("factura", "contador")


# ── Alta ────────────────────────────────────────────────────────────

def test_crear_una_intencion_devuelve_sus_datos(store):
    intent = store.crear("owner", "preguntar por la factura", ("contador",))

    assert intent is not None
    assert intent.descripcion == "preguntar por la factura"
    assert intent.triggers == ("contador",)
    assert intent.disparos_restantes == si.DISPAROS_POR_DEFECTO


def test_una_intencion_sin_dueno_no_se_crea(store):
    """Sin dueño no hay a quién recordárselo, y podría saltarle a cualquiera."""
    assert store.crear("", "algo", ("contador",)) is None
    assert store.crear(None, "algo", ("contador",)) is None


def test_una_intencion_sin_disparadores_no_se_crea(store):
    assert store.crear("owner", "algo", ()) is None


def test_una_intencion_sin_descripcion_no_se_crea(store):
    assert store.crear("owner", "   ", ("contador",)) is None


# ── Disparo ─────────────────────────────────────────────────────────

def test_se_dispara_cuando_aparece_el_tema(store):
    store.crear("owner", "preguntar por la factura", ("contador",))

    disparadas = store.comprobar("mañana hablo con el contador", "owner")

    assert len(disparadas) == 1
    assert disparadas[0].descripcion == "preguntar por la factura"


def test_no_se_dispara_con_una_frase_cualquiera(store):
    store.crear("owner", "algo", ("contador",))

    assert store.comprobar("hola qué tal", "owner") == []
    assert store.comprobar("abre la calculadora", "owner") == []


def test_se_compara_por_palabra_completa_no_por_subcadena(store):
    """"contador" no debe saltar dentro de otra palabra por casualidad."""
    store.crear("owner", "algo", ("contar",))

    assert store.comprobar("necesito un contenedor", "owner") == []


def test_los_acentos_no_impiden_el_disparo(store):
    store.crear("owner", "algo", si.extraer_triggers("reunión"))

    assert len(store.comprobar("tengo una reunion mañana", "owner")) == 1


# ── No convertirse en ruido ─────────────────────────────────────────

def test_no_se_dispara_dos_veces_seguidas(store):
    """Hablar tres frases del contador no debe soltar el mismo aviso tres veces."""
    store.crear("owner", "algo", ("contador",))

    assert len(store.comprobar("el contador", "owner")) == 1
    assert store.comprobar("otra vez el contador", "owner") == []


def test_pasado_el_enfriamiento_vuelve_a_avisar(store):
    intent = store.crear("owner", "algo", ("contador",), ahora=1000.0)
    store.comprobar("el contador", "owner", ahora=1000.0)

    despues = 1000.0 + si.ENFRIAMIENTO_SEGUNDOS + 1
    assert len(store.comprobar("el contador", "owner", ahora=despues)) == 1


def test_la_intencion_se_agota_tras_sus_disparos(store):
    store.crear("owner", "algo", ("contador",), disparos=2, ahora=0.0)

    t = 0.0
    for _ in range(2):
        assert len(store.comprobar("el contador", "owner", ahora=t)) == 1
        t += si.ENFRIAMIENTO_SEGUNDOS + 1

    assert store.comprobar("el contador", "owner", ahora=t) == []


def test_una_intencion_caducada_no_se_dispara(store):
    store.crear("owner", "algo", ("contador",), dias=1, ahora=0.0)

    muy_despues = 2 * 86400
    assert store.comprobar("el contador", "owner", ahora=muy_despues) == []


# ── Aislamiento entre usuarios ──────────────────────────────────────

def test_la_intencion_de_uno_no_le_salta_a_otro(store):
    store.crear("owner", "secreto de owner", ("contador",))

    assert store.comprobar("el contador", "otro_usuario") == []
    assert len(store.comprobar("el contador", "owner")) == 1


def test_cada_usuario_ve_solo_las_suyas(store):
    store.crear("owner", "de owner", ("contador",))
    store.crear("otro", "de otro", ("factura",))

    assert [i.descripcion for i in store.listar("owner")] == ["de owner"]
    assert [i.descripcion for i in store.listar("otro")] == ["de otro"]


def test_nadie_puede_cancelar_la_intencion_de_otro(store):
    intent = store.crear("owner", "de owner", ("contador",))

    assert store.cancelar(intent.id, "otro_usuario") is False
    assert len(store.listar("owner")) == 1


# ── Cancelación y limpieza ──────────────────────────────────────────

def test_cancelar_retira_la_intencion(store):
    intent = store.crear("owner", "algo", ("contador",))

    assert store.cancelar(intent.id, "owner") is True
    assert store.listar("owner") == []


def test_cancelar_algo_inexistente_no_rompe(store):
    assert store.cancelar(9999, "owner") is False


def test_purgar_borra_las_agotadas(store):
    store.crear("owner", "agotada", ("contador",), disparos=1, ahora=0.0)
    store.comprobar("el contador", "owner", ahora=0.0)

    assert store.purgar() >= 1
    assert store.listar("owner", incluir_muertas=True) == []


# ── Degradación ─────────────────────────────────────────────────────

def test_comprobar_sin_texto_o_sin_usuario_no_rompe(store):
    assert store.comprobar("", "owner") == []
    assert store.comprobar("algo", "") == []


def test_persisten_entre_sesiones(tmp_path):
    """Un diálogo dura tres minutos; esto puede esperar semanas."""
    ruta = str(tmp_path / "intents.db")
    primera = si.StandingIntentStore(ruta)
    primera.crear("owner", "sobrevivir al reinicio", ("contador",))

    segunda = si.StandingIntentStore(ruta)

    assert [i.descripcion for i in segunda.listar("owner")] == ["sobrevivir al reinicio"]


# ── El aviso ────────────────────────────────────────────────────────

def test_el_aviso_nombra_lo_que_hay_que_recordar(store):
    intent = store.crear("owner", "preguntar por la factura", ("contador",))

    aviso = si.formatear_aviso([intent])

    assert "preguntar por la factura" in aviso


def test_varias_intenciones_se_listan(store):
    a = store.crear("owner", "una cosa", ("contador",))
    b = store.crear("owner", "otra cosa", ("factura",))

    aviso = si.formatear_aviso([a, b])

    assert "una cosa" in aviso and "otra cosa" in aviso


def test_sin_intenciones_no_hay_aviso():
    assert si.formatear_aviso([]) == ""
