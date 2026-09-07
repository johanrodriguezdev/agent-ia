"""
tests/test_speech_prep.py

REQ-021 (pieza 8) — `ui/tts_engine.py::prepare_for_speech()` y la regresión de
`ui/cli.py::display_output`, que llegó a este REQ con CERO tests (baseline-021.md §3).

CA-24: se pronuncia texto plano — sin markdown, sin HTML, sin emojis.
CA-27: una sola función para las dos superficies (consola y webview); el resto del
pipeline de la consola (aplanado, umbral 400, corte en 380, coletilla con `vocative()`)
no cambia.

Sin red, sin altavoces: `speak` siempre mockeado (.claude/rules/testing.md).
"""

import re
from unittest.mock import patch

import pytest

from core.address import vocative
from ui.tts_engine import (
    SPEECH_TRUNCATE_AT,
    SPEECH_TRUNCATE_THRESHOLD,
    prepare_for_speech,
)

_EMOJI_TEST_RE = re.compile(
    "[" + "".join(
        f"{chr(lo)}-{chr(hi)}" for lo, hi in (
            (0x2190, 0x21FF), (0x2300, 0x23FF), (0x2460, 0x24FF), (0x25A0, 0x27BF),
            (0x2B00, 0x2BFF), (0x1F000, 0x1FAFF), (0xFE0E, 0xFE0F), (0x200D, 0x200D),
        )
    ) + "]"
)


def _tarea_creada_real() -> str:
    """Salida REAL de `format_task_created()` — trae `*`, `#` y emojis (CA-24)."""
    from tasks.task_manager import task_manager

    return task_manager.format_task_created({
        "title": "Llamar al contador",
        "id": 12,
        "remind_at": "2026-08-27T09:00:00",
        "recurrence": "daily",
        "priority": "normal",
    })


# ─────────────────────────────────────────────
#  CA-24 — texto plano
# ─────────────────────────────────────────────

def test_ca24_salida_real_de_format_task_created_sin_markdown_ni_emojis():
    crudo = _tarea_creada_real()
    assert "*" in crudo and "#" in crudo, "el fixture dejó de ser representativo"
    assert _EMOJI_TEST_RE.search(crudo), "el fixture dejó de traer emojis"

    hablado = prepare_for_speech(crudo)

    assert "*" not in hablado
    assert "#" not in hablado
    assert _EMOJI_TEST_RE.search(hablado) is None, hablado
    assert "Llamar al contador" in hablado
    assert "Recurrencia: Diaria" in hablado


def test_ca24_el_id_no_se_pierde_al_barrer_la_almohadilla():
    """`🆔 #12` tiene que sonar "número 12", no "12" a secas ni "almohadilla 12"."""
    assert "número 12" in prepare_for_speech("🆔 *#12* Llamar al contador")


def test_ca24_html_y_markdown_variados():
    entrada = (
        "# Encabezado\n"
        "- Punto de lista con **negrita** y `código`\n"
        "<p>Un <strong>párrafo</strong> HTML</p>\n"
        "Un [enlace](https://ejemplo.com) y ~~tachado~~\n"
        "```python\nprint('hola')\n```"
    )
    hablado = prepare_for_speech(entrada)

    for simbolo in ("*", "#", "`", "~", "<", ">", "]("):
        assert simbolo not in hablado, (simbolo, hablado)
    assert "Encabezado" in hablado
    assert "Un enlace" in hablado
    assert "párrafo" in hablado


def test_ca24_texto_vacio():
    assert prepare_for_speech("") == ""
    assert prepare_for_speech(None) == ""


def test_idempotencia():
    """Aplicarla dos veces no cambia el resultado — evita sorpresas si alguna superficie
    futura la llama sobre un texto ya preparado."""
    for entrada in (_tarea_creada_real(), "Hola.\nAdiós.", "**hola** 🆔 #7"):
        una = prepare_for_speech(entrada)
        assert prepare_for_speech(una) == una, entrada


# ─────────────────────────────────────────────
#  REQ-022/CA-18 — aviso de cambio de modelo, acortado antes de hablar
# ─────────────────────────────────────────────
#
# `tests/test_speech_prep.py` no tenía ningún caso de REQ-022 (test-results-022.md,
# hallazgo de orion-tester) — solo CA-24/CA-27 de REQ-021. `prepare_for_speech()` es el
# único punto de todo el sistema que decide qué se dice de verdad en voz alta (cubre tanto
# el manos libres del webview, que resuelve DESKTOP, como el modo voz de `main.py`), así
# que reconoce la forma LARGA del aviso (`ai.llm_provider.AVISO_CAMBIO_RE`) sin importar el
# canal que la generó, y la sustituye por la forma corta.

def test_ca18_la_forma_larga_del_aviso_se_acorta_sin_nombres_de_proveedor_o_modelo():
    from ai.llm_provider import con_aviso_de_cambio

    aviso = {
        "proveedor_desde": "deepseek", "modelo_desde": "deepseek-chat",
        "proveedor_hacia": "openrouter", "modelo_hacia": "openrouter/free",
    }
    texto_largo = con_aviso_de_cambio("la respuesta es 42", aviso)
    assert "deepseek" in texto_largo and "openrouter" in texto_largo   # el fixture es representativo

    hablado = prepare_for_speech(texto_largo)

    # El doble "\n\n" que agrega `con_aviso_de_cambio()` se aplana carácter a carácter
    # (paso 6, literal como `ui/cli.py`), así que quedan dos puntos seguidos — comportamiento
    # ya existente del aplanado, no algo que este REQ deba corregir.
    assert hablado == "la respuesta es 42. . Cambié de modelo."
    assert "deepseek" not in hablado
    assert "openrouter" not in hablado
    assert "openrouter/free" not in hablado


def test_ca18_sin_aviso_de_cambio_el_texto_no_se_toca():
    """Contracara: un texto que no termina en la forma larga del aviso pasa intacto por
    este punto (más allá del resto del pipeline de limpieza, ya cubierto por CA-24)."""
    assert "Cambié" not in prepare_for_speech("la respuesta es 42, sin ningún cambio de modelo")


# ─────────────────────────────────────────────
#  CA-27 — el resto del pipeline de la consola no cambia
# ─────────────────────────────────────────────

def test_ca27_aplanado_de_saltos_de_linea():
    """Aplanado literal `"\\n"` -> `". "`, igual que `ui/cli.py:46` antes de REQ-021."""
    assert prepare_for_speech("Primera línea\nSegunda línea") == (
        "Primera línea. Segunda línea"
    )


def _texto_de(n: int) -> str:
    """Return un texto de EXACTAMENTE `n` caracteres, sin espacios en los bordes.

    Los bordes importan: `prepare_for_speech()` hace `.strip()` antes de medir, así que un
    texto que termine en espacio no tendría la longitud que dice tener.
    """
    texto = ("Frase de relleno. " * (n // 18 + 2))[:n]
    assert texto == texto.strip() and len(texto) == n, texto[-3:]
    return texto


def test_ca27_el_umbral_y_el_corte_estan_fijados_en_400_y_380():
    """Fijación de los valores literales que exige CA-27, mismo patrón que
    `test_la_duracion_vive_en_un_solo_lugar` (MIC_WINDOW_SECONDS) y
    `test_ca07_el_ttl_por_defecto_son_tres_minutos` (DIALOG_TTL_SECONDS).

    Sin esto, el resto de los tests de este archivo usa las constantes SIMBÓLICAMENTE y
    sigue en verde aunque alguien las mueva — la vacuidad #1 que reportó `orion-tester`.
    """
    assert SPEECH_TRUNCATE_THRESHOLD == 400
    assert SPEECH_TRUNCATE_AT == 380


def test_ca27_el_umbral_literal_de_400_decide_el_truncado():
    """El mismo umbral, medido sobre la salida real y con el número escrito a mano: 400
    caracteres pasan enteros, 401 se truncan. Fija el valor Y la comparación estricta."""
    exacto_400 = _texto_de(400)
    assert prepare_for_speech(exacto_400) == exacto_400, "400 caracteres no deben truncarse"

    exacto_401 = _texto_de(401)
    hablado = prepare_for_speech(exacto_401)
    assert hablado != exacto_401, "401 caracteres sí deben truncarse"
    assert hablado.endswith("está en su pantalla" + vocative() + ".")


def test_ca27_el_corte_literal_de_380_medido_sobre_la_salida_real():
    """Medición real, con las longitudes escritas a mano (verificadas por `orion-tester`
    contra el comportamiento actual y coherentes con `baseline-021.md` §4.5):
    900 caracteres de entrada -> 419 de salida, cortando en el último punto por debajo
    de 380, que cae en el índice 358.

    Si alguien mueve el corte, el prefijo deja de coincidir y este test salta.
    """
    frase = "Esta es una frase de relleno. " * 30
    assert len(frase) == 900, "el fixture dejó de medir 900 caracteres"

    hablado = prepare_for_speech(frase)

    # 12 frases completas menos su punto final = 358 caracteres: el último punto que cabe
    # por debajo del corte de 380.
    prefijo = ("Esta es una frase de relleno. " * 12).strip()[:-1]
    assert len(prefijo) == 358
    assert hablado.startswith(prefijo), hablado[:60]

    coletilla = f"... La información completa está en su pantalla{vocative()}."
    assert hablado == prefijo + coletilla
    assert len(hablado) == 358 + len(coletilla)


def test_ca27_corte_en_380_al_ultimo_punto_con_coletilla():
    frase = "Esta es una frase de relleno. " * 30          # >> 400 caracteres
    hablado = prepare_for_speech(frase)

    esperado_prefijo = frase.strip()[:SPEECH_TRUNCATE_AT].rsplit(".", 1)[0]
    assert hablado.startswith(esperado_prefijo)
    assert hablado.endswith(
        f"... La información completa está en su pantalla{vocative()}."
    )
    # Detalles que la SPEC citaba mal y el baseline (§4.5) corrigió: hay un espacio
    # después de los tres puntos, y la coletilla usa `vocative()`, no un literal fijo.
    assert "... La información" in hablado
    assert "...La información" not in hablado


def test_ca27_display_output_usa_la_funcion_comun(monkeypatch):
    """Regresión de `ui/cli.py::display_output`: `speak()` se invoca UNA vez y con
    exactamente `prepare_for_speech(format_response(texto))`."""
    from ui import cli as cli_module

    dichos = []
    monkeypatch.setattr(cli_module, "speak", dichos.append)
    monkeypatch.setattr(cli_module, "format_response", lambda t: f"Enseguida, Senor. {t}")

    cli_module.CLI().display_output(_tarea_creada_real())

    assert len(dichos) == 1
    esperado = prepare_for_speech("Enseguida, Senor. " + _tarea_creada_real())
    assert dichos[0] == esperado
    assert "*" not in dichos[0] and "#" not in dichos[0]


def test_ca27_display_output_sin_voz_no_habla(monkeypatch):
    from ui import cli as cli_module

    dichos = []
    monkeypatch.setattr(cli_module, "speak", dichos.append)

    cli_module.CLI().display_output("hola", read_aloud=False)

    assert dichos == []


def test_ca27_una_sola_implementacion():
    """CA-27 estructural: `ui/cli.py` ya no tiene lógica propia de aplanado ni de
    truncado — delega en `prepare_for_speech()`. Si alguien la reintroduce, esto salta."""
    from pathlib import Path

    cli_src = Path(__file__).resolve().parent.parent / "ui" / "cli.py"
    codigo = [
        linea.split("#", 1)[0]
        for linea in cli_src.read_text(encoding="utf-8").splitlines()
    ]
    codigo_src = "\n".join(codigo)

    assert "prepare_for_speech" in codigo_src
    assert "rsplit" not in codigo_src, "el truncado volvió a duplicarse en la consola"
    assert 'replace("\\n"' not in codigo_src, "el aplanado volvió a duplicarse"
    assert "380" not in codigo_src and "400" not in codigo_src
