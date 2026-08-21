"""
tests/test_security_config.py
REQ-019 — `core/security_config.py`: persistencia de los overrides de seguridad
(`security_overrides.json`), archivo separado de `config.json` (ver arquitectura-019.md,
sección "Desvío documentado de un ASUMIDO").

Convenciones (.claude/rules/testing.md): nunca toca el `security_overrides.json` real del
proyecto — `SECURITY_OVERRIDES_FILE` se redirige a `tmp_path` en cada test vía monkeypatch.
"""

import json

import pytest

import core.security_config as security_config


@pytest.fixture(autouse=True)
def isolated_overrides_file(monkeypatch, tmp_path):
    """Redirige SECURITY_OVERRIDES_FILE a un archivo temporal — nunca toca el archivo
    real del proyecto (CA-06/CA-09/CA-11)."""
    path = tmp_path / "security_overrides.json"
    monkeypatch.setattr(security_config, "SECURITY_OVERRIDES_FILE", str(path))
    return path


def test_archivo_inexistente_devuelve_dict_vacio(isolated_overrides_file):
    assert not isolated_overrides_file.exists()
    assert security_config.load_security_overrides() == {}


def test_archivo_con_json_corrupto_no_crashea(isolated_overrides_file):
    isolated_overrides_file.write_text("{esto no es json valido", encoding="utf-8")
    assert security_config.load_security_overrides() == {}


def test_archivo_con_bytes_no_utf8_no_crashea(isolated_overrides_file):
    """Hallazgo A de security-audit-019.md — UnicodeDecodeError (subclase de ValueError,
    no de OSError/JSONDecodeError) es el escenario de corrupción más realista (corte de
    energía a mitad de escritura) y debía cubrirse con `except Exception` amplio."""
    isolated_overrides_file.write_bytes(b"\xff\xfe\x00\x01no-es-utf8-valido")
    assert security_config.load_security_overrides() == {}


def test_archivo_con_valor_invalido_se_descarta_esa_entrada_y_conserva_el_resto(isolated_overrides_file):
    isolated_overrides_file.write_text(
        json.dumps({"open_chrome": "purple", "open_notepad": "yellow"}), encoding="utf-8",
    )
    result = security_config.load_security_overrides()
    assert "open_chrome" not in result
    assert result == {"open_notepad": "yellow"}


def test_archivo_con_valor_no_string_se_descarta(isolated_overrides_file):
    # JSON no permite claves no-string de forma nativa, pero un valor no-string (ej. una
    # lista) en la posición de "value" sí es representable y debe descartarse igual.
    isolated_overrides_file.write_text(
        json.dumps({"open_chrome": ["no", "es", "un", "string"]}), encoding="utf-8",
    )
    assert security_config.load_security_overrides() == {}


def test_archivo_que_no_es_un_objeto_json_devuelve_dict_vacio(isolated_overrides_file):
    isolated_overrides_file.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert security_config.load_security_overrides() == {}


def test_save_y_load_round_trip(isolated_overrides_file):
    security_config.save_security_overrides({"open_chrome": "yellow", "open_url": "red"})
    result = security_config.load_security_overrides()
    assert result == {"open_chrome": "yellow", "open_url": "red"}


def test_save_security_overrides_hace_merge_con_lo_existente(isolated_overrides_file):
    security_config.save_security_overrides({"open_chrome": "yellow"})
    security_config.save_security_overrides({"open_notepad": "yellow"})

    result = security_config.load_security_overrides()
    assert result == {"open_chrome": "yellow", "open_notepad": "yellow"}


def test_save_security_overrides_no_deja_archivos_temporales(isolated_overrides_file, tmp_path):
    security_config.save_security_overrides({"open_chrome": "yellow"})

    leftover = list(tmp_path.glob(".security_overrides_*"))
    assert leftover == [], f"quedaron archivos temporales sin limpiar: {leftover}"


def test_fallo_de_escritura_no_propaga_excepcion_y_conserva_archivo_original(
    isolated_overrides_file, monkeypatch,
):
    security_config.save_security_overrides({"open_chrome": "yellow"})
    original_content = isolated_overrides_file.read_text(encoding="utf-8")

    def boom(*_a, **_kw):
        raise OSError("fallo simulado de os.replace")

    monkeypatch.setattr(security_config.os, "replace", boom)

    security_config.save_security_overrides({"open_notepad": "yellow"})  # no debe lanzar

    assert isolated_overrides_file.read_text(encoding="utf-8") == original_content


def test_fallo_de_mkstemp_no_propaga_excepcion(isolated_overrides_file, monkeypatch):
    """Recomendación no bloqueante 4 de security-audit-019.md — mkstemp() también puede
    fallar (permiso denegado, disco lleno); no debe propagar la excepción."""
    def boom(*_a, **_kw):
        raise OSError("fallo simulado de mkstemp")

    monkeypatch.setattr(security_config.tempfile, "mkstemp", boom)

    security_config.save_security_overrides({"open_chrome": "yellow"})  # no debe lanzar
