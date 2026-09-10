"""
tests/test_nombre_del_agente.py
REQ-037 — El nombre del agente es el que eligió el usuario, en toda la interfaz.

Johan lo encontró en el botón de Flujos: el panel vacío decía *"Pedíselo a O.R.I.O.N.
hablando"* con el nombre escrito a mano, así que quien renombró a su agente leía un nombre
que nunca puso. Al buscarlo aparecieron seis lugares más.

El test que de verdad importa es el guard: revisa TODO el frontend en vez de un mensaje
puntual. Un texto nuevo que escriba el nombre a mano lo hace fallar acá y no en la pantalla
de alguien.
"""

import os

import pytest

_FRONTEND = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "webview", "frontend"
)

#: Cómo se llamó el agente por defecto en distintos momentos del proyecto. Cualquiera de
#: estos dentro de un texto que se le muestra al usuario es el bug.
NOMBRES_FIJOS = ("O.R.I.O.N", "ORION", "Orion", "NODDOO", "Noddoo")

#: Lo que NO es un texto para el usuario y por lo tanto puede nombrarlos: comentarios que
#: explican el porqué, y las variables globales internas.
_PERMITIDOS = ("__ORION_", "ORION_AUTH_PIN")


def _archivos_de_interfaz():
    for carpeta, _subdirs, archivos in os.walk(_FRONTEND):
        if "vendor" in carpeta or "fonts" in carpeta:
            continue
        for nombre in archivos:
            if nombre.endswith((".js", ".html")):
                yield os.path.join(carpeta, nombre)


def _lineas_de_codigo(ruta):
    """Devuelve las líneas que NO son comentarios: ahí es donde el nombre sería un bug."""
    with open(ruta, "r", encoding="utf-8") as f:
        for numero, linea in enumerate(f, start=1):
            limpia = linea.strip()
            if limpia.startswith(("//", "*", "/*", "<!--")):
                continue
            yield numero, linea


def test_ningun_texto_de_la_interfaz_escribe_el_nombre_a_mano():
    """El guard. Si esto falla, alguien volvió a escribir el nombre del agente en un texto
    en vez de preguntárselo a `nombreDelAgente()`."""
    hallazgos = []
    for ruta in _archivos_de_interfaz():
        for numero, linea in _lineas_de_codigo(ruta):
            if any(p in linea for p in _PERMITIDOS):
                continue
            for nombre in NOMBRES_FIJOS:
                if nombre in linea:
                    hallazgos.append(f"{os.path.basename(ruta)}:{numero}: {linea.strip()[:90]}")

    assert not hallazgos, (
        "El nombre del agente lo elige el usuario y no puede estar escrito a mano en la "
        "interfaz. Usá `nombreDelAgente()` de `agente.js`:\n  " + "\n  ".join(hallazgos)
    )


def test_el_modulo_del_nombre_existe_y_lo_exporta():
    """La otra mitad del arreglo: que exista un único lugar que sepa el nombre."""
    ruta = os.path.join(_FRONTEND, "js", "agente.js")

    assert os.path.exists(ruta), "falta ui/webview/frontend/js/agente.js"
    with open(ruta, encoding="utf-8") as f:
        contenido = f.read()
    assert "export function nombreDelAgente" in contenido
    assert "export function fijarNombreDelAgente" in contenido


def test_quien_repinta_la_identidad_publica_el_nombre():
    """`setAgentIdentity()` es el único punto por donde entra un nombre nuevo (al arrancar y
    al renombrar). Si no lo publica, la global se queda con el nombre del arranque y los
    paneles muestran el viejo hasta reiniciar — que era la mitad de fondo de este bug."""
    ruta = os.path.join(_FRONTEND, "js", "app.js")
    with open(ruta, encoding="utf-8") as f:
        contenido = f.read()

    inicio = contenido.index("function setAgentIdentity")
    cuerpo = contenido[inicio:inicio + 900]
    assert "fijarNombreDelAgente(" in cuerpo


# ─────────────────────── el lado de Python ───────────────────────
#
# Acá se prueba el MENSAJE que sale, no el código fuente. El primer intento revisaba las
# líneas del archivo y marcaba dos `logger.critical()` como si fueran texto para el
# usuario: un log puede nombrar al producto, lo que no puede es el mensaje que lee una
# persona o el modelo.

@pytest.fixture(autouse=True)
def sin_autonomia(monkeypatch, tmp_path):
    """El confinamiento se abre con el modo total: estos tests corren con el modo apagado."""
    import core.autonomy as autonomy

    monkeypatch.setattr(autonomy, "ARCHIVO_AUTONOMIA", str(tmp_path / "autonomy.json"))


def test_el_mensaje_de_confinamiento_no_nombra_al_agente():
    """Lo lee el modelo y termina en la conversación: tiene que hablar en primera persona."""
    from core.workspace_files import RutaFueraDeRaiz, resolver

    propio = os.path.join(os.path.dirname(_FRONTEND), "..", "..", "main.py")

    with pytest.raises(RutaFueraDeRaiz) as fallo:
        resolver(os.path.abspath(propio), ["C:/una-carpeta-cualquiera"])

    mensaje = str(fallo.value)
    assert "O.R.I.O.N" not in mensaje
    assert "mi propio código" in mensaje


def test_el_mensaje_de_la_rama_no_nombra_al_agente(monkeypatch, tmp_path):
    """El que ve Johan si intenta encender el nivel total sin repositorio git."""
    import core.autonomy as autonomy

    monkeypatch.setattr(autonomy, "_CARPETA_ORION", str(tmp_path))

    with pytest.raises(RuntimeError) as fallo:
        autonomy.preparar_rama()

    assert "O.R.I.O.N" not in str(fallo.value)


def test_la_carpeta_propia_rechazada_habla_en_primera_persona():
    """Mismo criterio en `workspace_config`: el agente habla de sí mismo sin suponer cómo
    se llama."""
    import core.workspace_config as wc

    with pytest.raises(wc.RaizRechazada) as fallo:
        wc.agregar_raiz(os.path.abspath(os.path.join(_FRONTEND, "..", "..", "..")))

    assert "O.R.I.O.N" not in str(fallo.value)
