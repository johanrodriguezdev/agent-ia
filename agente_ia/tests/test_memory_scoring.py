"""
tests/test_memory_scoring.py
Pruebas de `core/memory_scoring.py` — qué recuerdos se ganan entrar en la memoria durable.

Lo que decide este módulo acaba inyectado en cada respuesta del agente, así que lo que entra
de más no es neutro: desplaza a lo que importa. Por eso la suite se centra en el orden —que
lo repetido y lo concreto ganen— y en que agrupar no pierda información.
"""

import pytest

from core import memory_scoring as ms


# ── Agrupar lo que dice lo mismo ────────────────────────────────────

def test_los_hechos_repetidos_se_agrupan():
    lotes = [
        ["- Johan trabaja con Unipalma gestionando copias de seguridad"],
        ["- Johan trabaja con Unipalma y gestiona copias semanales"],
    ]

    candidatos = ms.agrupar_candidatos(lotes)

    assert len(candidatos) == 1
    assert candidatos[0].apariciones == 2


def test_los_hechos_distintos_no_se_mezclan():
    lotes = [["- Escucha rock clásico, sobre todo Bon Jovi y Aerosmith"],
             ["- Su equipo se llama Hansel y usa Windows 11"]]

    assert len(ms.agrupar_candidatos(lotes)) == 2


def test_al_agrupar_se_conserva_la_formulacion_mas_completa():
    """Entre "usa VS Code" y "usa VS Code en Windows 11", la segunda contiene a la primera."""
    lotes = [
        ["- Johan usa VS Code"],
        ["- Johan usa VS Code en Windows 11 para el proyecto agente_ia"],
    ]

    candidatos = ms.agrupar_candidatos(lotes)

    assert len(candidatos) == 1
    assert "Windows 11" in candidatos[0].texto


def test_repetir_dentro_del_mismo_lote_no_cuenta_como_refuerzo():
    """Es el modelo insistiendo, no el hecho sosteniéndose en el tiempo."""
    lotes = [[
        "- Johan trabaja con Unipalma gestionando copias de seguridad",
        "- Johan trabaja con Unipalma y gestiona copias semanales",
    ]]

    candidatos = ms.agrupar_candidatos(lotes)

    assert len(candidatos) == 1
    assert candidatos[0].apariciones == 1


# ── La puntuación ───────────────────────────────────────────────────

def test_lo_repetido_gana_a_lo_dicho_una_vez():
    """La señal más fiable que hay sin preguntarle a nadie."""
    lotes = [
        ["- Johan trabaja con Unipalma gestionando copias", "- Le interesa la tecnología"],
        ["- Johan trabaja con Unipalma y gestiona copias semanales"],
        ["- Johan trabaja con Unipalma revisando esas copias"],
    ]

    promovidos, _ = ms.promover(lotes)

    assert "Unipalma" in promovidos[0].texto


def test_lo_concreto_gana_a_lo_vago():
    lotes = [["- Le gusta la tecnología en general",
              "- Su equipo se llama Hansel y corre Windows 11"]]

    promovidos, _ = ms.promover(lotes)

    assert "Hansel" in promovidos[0].texto


def test_un_hecho_telegrafico_puntua_menos_que_uno_util():
    lotes = [["- Usa VS Code", "- Trabaja de noche en el proyecto agente_ia con Python 3.12"]]

    promovidos, _ = ms.promover(lotes)

    assert "Python" in promovidos[0].texto


def test_un_parrafo_disfrazado_de_hecho_puntua_menos():
    """Lo demasiado largo es un resumen, no un hecho."""
    corto = "- Vive en Villavicencio, Meta, Colombia"
    largo = "- " + ("palabras de relleno " * 40)
    lotes = [[largo, corto]]

    promovidos, _ = ms.promover(lotes)

    assert promovidos[0].texto == corto


# ── El resumen de lo que pasó ───────────────────────────────────────

def test_el_resumen_explica_que_se_hizo():
    """Sin esto la consolidación sería una caja negra que reescribe la memoria."""
    lotes = [
        ["- Johan trabaja con Unipalma gestionando copias", "- Escucha Bon Jovi"],
        ["- Johan trabaja con Unipalma y gestiona copias semanales"],
    ]

    _, resumen = ms.promover(lotes)

    assert resumen["propuestos"] == 3
    assert resumen["agrupados"] == 2
    assert resumen["reforzados"] == 1


def test_sin_candidatos_el_resumen_va_en_ceros():
    promovidos, resumen = ms.promover([])

    assert promovidos == []
    assert resumen["promovidos"] == 0


# ── Tope ────────────────────────────────────────────────────────────

def test_no_se_promueven_mas_de_la_cuenta():
    """Por encima del tope, MEMORY.md deja de ser memoria y pasa a ser transcripción."""
    # Vocabulario inventado y sin una sola palabra en común entre hechos: con texto normal
    # ("durante", "horas") acaban compartiendo términos, se agrupan, y el test mediría la
    # agrupación en vez del tope.
    lotes = [[f"- alfa{i} beta{i} gamma{i} delta{i}" for i in range(80)]]

    promovidos, _ = ms.promover(lotes)

    assert len(promovidos) == ms.MAX_PROMOVIDOS


def test_el_tope_se_puede_ajustar():
    lotes = [[f"- alfa{i} beta{i} gamma{i} delta{i}" for i in range(20)]]

    promovidos, _ = ms.promover(lotes, maximo=5)

    assert len(promovidos) == 5


# ── Formato para el consolidador ────────────────────────────────────

def test_se_marca_lo_que_se_repitio():
    """El consolidador necesita saber qué se sostiene para ordenarlo primero."""
    lotes = [
        ["- Johan trabaja con Unipalma gestionando copias"],
        ["- Johan trabaja con Unipalma y gestiona copias semanales"],
    ]
    promovidos, _ = ms.promover(lotes)

    texto = ms.formatear_para_consolidar(promovidos)

    assert "visto en 2 tramos" in texto


def test_lo_dicho_una_vez_no_lleva_marca():
    promovidos, _ = ms.promover([["- Escucha Bon Jovi y Aerosmith"]])

    texto = ms.formatear_para_consolidar(promovidos)

    assert "visto en" not in texto


# ── Degradación ─────────────────────────────────────────────────────

def test_lotes_vacios_no_rompen():
    promovidos, resumen = ms.promover([[], [], []])

    assert promovidos == []
    assert resumen["propuestos"] == 0


def test_lineas_en_blanco_se_ignoran():
    candidatos = ms.agrupar_candidatos([["", "   ", "- Un hecho de verdad sobre Johan"]])

    assert len(candidatos) == 1


def test_los_umbrales_estan_fijados():
    """Moverlos cambia qué recuerda el agente y cuánto ocupa cada respuesta."""
    assert ms.MAX_PROMOVIDOS == 40
    assert ms.UMBRAL_DUPLICADO == 0.5


# ── El nombre del usuario sale de la configuración, no del código ───

def test_el_nombre_configurado_no_cuenta_como_palabra_significativa(monkeypatch):
    """Estaba escrito "johan" en la lista de palabras vacías: el repositorio es de quien
    lo instale, así que el nombre que se descarta es el que cada uno configuró."""
    import config_manager

    monkeypatch.setattr(config_manager, "get_display_name", lambda: "María José")

    palabras = ms._palabras_significativas("María José prefiere el modo oscuro")

    assert "maria" not in palabras and "jose" not in palabras
    assert "prefiere" in palabras and "oscuro" in palabras


def test_sin_nombre_configurado_no_se_descarta_nada(monkeypatch):
    import config_manager

    monkeypatch.setattr(config_manager, "get_display_name", lambda: "")

    assert "johan" in ms._palabras_significativas("Johan prefiere el modo oscuro")


def test_si_la_configuracion_falla_el_puntaje_sigue_funcionando(monkeypatch):
    import config_manager

    def _explota():
        raise OSError("config ilegible")

    monkeypatch.setattr(config_manager, "get_display_name", _explota)

    assert "prefiere" in ms._palabras_significativas("Johan prefiere el modo oscuro")
