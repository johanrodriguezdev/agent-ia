"""
tests/test_estilo_respuesta.py
REQ-071 — la economía de la respuesta, y poder comprobar que se cumple.

Lo que protege esta suite:

- **Que el contrato llegue al modelo por los DOS caminos.** El escritorio y la voz pasan
  por `reasoning_loop`; Telegram y Discord por `claude_brain`. Ya divergieron una vez y el
  agente sonaba distinto según el canal.
- **Que medir no pueda romper una conversación.** Si el disco está lleno o el archivo es
  ilegible, se pierde la medida, nunca la respuesta.
- **Que no se guarde el texto de nadie.** El registro lleva longitud, canal y si hubo
  herramientas. Para leer conversaciones está la memoria; este archivo no.
"""

import json

import pytest

from core import estilo_respuesta


@pytest.fixture(autouse=True)
def registro_aparte(tmp_path, monkeypatch):
    """Cada test con su propio archivo: nunca el del usuario."""
    monkeypatch.setattr(estilo_respuesta, "_ARCHIVO", str(tmp_path / "medidas.jsonl"))
    return str(tmp_path / "medidas.jsonl")


# ------------------------------------------------------------------ el contrato

def test_el_contrato_dice_lo_que_la_especificacion_pide():
    contrato = estilo_respuesta.bloque_para_el_prompt()

    # El ejemplo con contraste es lo que un modelo copia; sin él, «sé breve» es un adjetivo.
    assert "Abriendo Chrome" in contrato
    assert "MAL" in contrato and "BIEN" in contrato
    # Y la excepción, para que no se vuelva mudo cuando hace falta explicar.
    assert "pide entender" in contrato or "por qué" in contrato


def test_el_contrato_viaja_en_el_prompt_del_escritorio_y_la_voz(monkeypatch):
    from core import reasoning_loop

    prompt = reasoning_loop._build_system_prompt(None)

    assert "ECONOMÍA DE LA RESPUESTA" in prompt
    assert "Abriendo Chrome" in prompt


def test_el_contrato_viaja_tambien_por_telegram_y_discord():
    from ai import claude_brain

    prompt = claude_brain._build_system_prompt(channel="telegram")

    assert "ECONOMÍA DE LA RESPUESTA" in prompt
    assert "Abriendo Chrome" in prompt


# ------------------------------------------------------------------ la medición

def test_se_registra_la_longitud_y_no_el_texto(registro_aparte):
    estilo_respuesta.registrar("Abriendo Chrome.", canal="desktop")

    with open(registro_aparte, encoding="utf-8") as f:
        medida = json.loads(f.readline())

    assert medida["largo"] == len("Abriendo Chrome.")
    assert medida["canal"] == "desktop"
    assert medida["herramientas"] is False
    assert "Abriendo Chrome" not in json.dumps(medida)      # el texto NO se guarda


def test_una_respuesta_vacia_no_se_registra(registro_aparte):
    import os

    estilo_respuesta.registrar("", canal="desktop")
    estilo_respuesta.registrar(None, canal="desktop")

    assert not os.path.exists(registro_aparte)


def test_medir_nunca_rompe_la_conversacion(monkeypatch):
    """Si el registro falla, la respuesta del usuario no puede verse afectada."""
    monkeypatch.setattr(estilo_respuesta, "_ARCHIVO", "/ruta/que/no/existe/x.jsonl")
    monkeypatch.setattr(estilo_respuesta.os, "makedirs",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disco lleno")))

    estilo_respuesta.registrar("algo")          # no debe levantar


def test_las_estadisticas_cuentan_lo_que_importa():
    for texto, herramientas in [("Listo.", False),
                                ("x" * 500, False),
                                ("x" * 1000, True),
                                ("Son las 6:42.", False)]:
        estilo_respuesta.registrar(texto, canal="desktop", con_herramientas=herramientas)

    e = estilo_respuesta.estadisticas()

    assert e["respuestas"] == 4
    assert e["una_linea"] == 2                              # «Listo.» y la hora
    assert e["largas"] == 2                                 # las de 500 y 1000
    assert e["porcentaje_largas"] == 50


def test_se_pueden_mirar_solo_los_turnos_sin_herramientas():
    """Un turno que investigó y resumió cinco fuentes puede ser largo con razón; mezclarlo
    con las confirmaciones haría que la media no dijera nada."""
    estilo_respuesta.registrar("Listo.", con_herramientas=False)
    estilo_respuesta.registrar("x" * 3000, con_herramientas=True)

    todas = estilo_respuesta.estadisticas()
    charla = estilo_respuesta.estadisticas(solo_sin_herramientas=True)

    assert todas["respuestas"] == 2
    assert charla["respuestas"] == 1
    assert charla["largas"] == 0


def test_sin_medidas_el_resumen_lo_dice():
    assert "Todavía no tengo medidas" in estilo_respuesta.resumen()


def test_una_linea_corrupta_no_tumba_la_lectura(registro_aparte):
    estilo_respuesta.registrar("Listo.")
    with open(registro_aparte, "a", encoding="utf-8") as f:
        f.write("esto no es json\n")
    estilo_respuesta.registrar("Hecho.")

    assert estilo_respuesta.estadisticas()["respuestas"] == 2


def test_el_registro_no_crece_sin_limite(registro_aparte, monkeypatch):
    monkeypatch.setattr(estilo_respuesta, "MAX_MEDIDAS", 10)
    for _ in range(40):
        estilo_respuesta.registrar("Listo.")

    with open(registro_aparte, encoding="utf-8") as f:
        lineas = len(f.readlines())

    assert lineas <= 13                                     # 10 + el margen del recorte


# ------------------------------------------------------------------ REQ-073: el resto del contrato

def test_el_contrato_prohibe_fingir_que_se_hizo_algo():
    """§11 y §39: «Listo» cuando no está listo es una mentira que se descubre más tarde."""
    contrato = estilo_respuesta.bloque_para_el_prompt()

    assert "no lo hiciste" in contrato.lower() or "no ejecutaste" in contrato.lower()
    assert "«No pude»" in contrato or "No pude" in contrato


def test_el_contrato_separa_el_hecho_de_la_inferencia():
    """§28: «Encontré el archivo» no es lo mismo que «Creo que este es el que buscas»."""
    contrato = estilo_respuesta.bloque_para_el_prompt()

    assert "Encontré el archivo" in contrato
    assert "Creo que este es" in contrato
    assert "No lo sé" in contrato


def test_el_contrato_dice_cuando_callarse_el_humor():
    """§14: el sarcasmo con el usuario frustrado o con datos perdidos es una falta de tacto."""
    contrato = estilo_respuesta.bloque_para_el_prompt()

    assert "HUMOR" in contrato
    for cuando in ("error importante", "frustrado", "perdido información", "peligroso"):
        assert cuando in contrato, cuando


def test_el_contrato_sigue_siendo_corto():
    """Cada regla cuesta tokens en CADA llamada. Un contrato de economía que engorda el
    prompt sin límite se contradice a sí mismo."""
    assert len(estilo_respuesta.bloque_para_el_prompt()) < 2600
