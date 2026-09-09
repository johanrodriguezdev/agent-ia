"""
tests/test_capabilities_router.py
`os_integration/capabilities_router.py` — el módulo no tenía ni un test.

El bug que motivó estos: `_JSON_PATH` se armaba como "al lado de este módulo", pero
`system_capabilities.json` vive en la RAÍZ del proyecto, junto a `config.json`. Resultado:
las 14 capacidades declaradas nunca se cargaban y `capability_run` no llegaba a registrarse
como herramienta — el agente no podía ejecutar ninguna de las cosas que el archivo declara.
Se encontró revisando por qué el arranque imprimía "[Aviso] No pude cargar
system_capabilities.json", un aviso que se perdía entre las líneas del arranque.

Sin red y sin ejecutar ninguna capacidad de verdad: acá solo se prueba la carga y el
emparejamiento de frases.
"""

import json
import os

import pytest

from os_integration import capabilities_router as cr


def test_el_json_se_busca_donde_de_verdad_esta():
    """La regresión del bug: la ruta tiene que apuntar a un archivo que exista."""
    assert os.path.exists(cr._JSON_PATH), (
        f"El loader busca en {cr._JSON_PATH} y ahí no hay nada. El archivo vive en la raíz "
        f"del proyecto, junto a config.json."
    )


def test_las_capacidades_declaradas_se_cargan():
    assert len(cr._CAPABILITIES) > 0, "el archivo existe pero no se cargó ninguna capacidad"


def test_cada_capacidad_declara_lo_minimo():
    """Una entrada sin `modulo`/`funcion` no se puede ejecutar: mejor que salte acá."""
    for cap in cr._CAPABILITIES:
        assert cap.get("frases"), f"capacidad sin frases: {cap}"
        assert cap.get("modulo"), f"capacidad sin módulo: {cap}"
        assert cap.get("funcion"), f"capacidad sin función: {cap}"


def test_una_frase_declarada_encuentra_su_capacidad():
    """El emparejamiento es por frase contenida, así que una frase con relleno alrededor
    también tiene que encontrarla."""
    primera = cr._CAPABILITIES[0]
    frase = primera["frases"][0]

    encontrada = cr.match_capability(f"por favor {frase} ahora")

    assert encontrada is not None
    assert encontrada["funcion"] == primera["funcion"]


def test_un_texto_cualquiera_no_encuentra_nada():
    assert cr.match_capability("contame un chiste sobre pingüinos") is None


# ─────────────────────────── la carga, ante un archivo roto ───────────────────────────

def test_sin_archivo_no_hay_capacidades_y_no_revienta(monkeypatch, tmp_path):
    """El archivo es OPCIONAL: una instalación sin él funciona igual."""
    monkeypatch.setattr(cr, "_JSON_PATH", str(tmp_path / "no-existe.json"))

    assert cr._load_capabilities() == []


def test_un_archivo_corrupto_no_habilita_nada_y_no_revienta(monkeypatch, tmp_path):
    roto = tmp_path / "system_capabilities.json"
    roto.write_text("{esto no es json", encoding="utf-8")
    monkeypatch.setattr(cr, "_JSON_PATH", str(roto))

    assert cr._load_capabilities() == []


def test_un_json_sin_la_clave_capacidades_no_revienta(monkeypatch, tmp_path):
    otro = tmp_path / "system_capabilities.json"
    otro.write_text(json.dumps({"otra_cosa": [1, 2, 3]}), encoding="utf-8")
    monkeypatch.setattr(cr, "_JSON_PATH", str(otro))

    assert cr._load_capabilities() == []


def test_un_archivo_valido_se_carga(monkeypatch, tmp_path):
    bueno = tmp_path / "system_capabilities.json"
    bueno.write_text(json.dumps({"capacidades": [
        {"frases": ["hacé la prueba"], "modulo": "un.modulo", "funcion": "una_funcion",
         "params": {}},
    ]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cr, "_JSON_PATH", str(bueno))

    cargadas = cr._load_capabilities()

    assert len(cargadas) == 1
    assert cargadas[0]["funcion"] == "una_funcion"
