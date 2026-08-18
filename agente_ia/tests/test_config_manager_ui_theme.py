"""
tests/test_config_manager_ui_theme.py
REQ-013/CA-02 — persistencia de la preferencia de tema en `config.json`.

`CONFIG_FILE` se redirige a `tmp_path` en cada prueba para no tocar el `config.json` real
del usuario (`.claude/rules/testing.md`).
"""

import json

import pytest

import config_manager


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_path))
    return config_path


def _write_config(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_get_ui_theme_default_dark_sin_archivo(isolated_config):
    assert config_manager.get_ui_theme() == "dark"


def test_get_ui_theme_default_dark_sin_clave(isolated_config):
    """Config antiguo (anterior a REQ-013), sin la clave `ui_theme`."""
    _write_config(isolated_config, {"agent_name": "noddoo", "display_name": "Johan"})

    assert config_manager.get_ui_theme() == "dark"


def test_load_config_completa_ui_theme_en_config_antiguo(isolated_config):
    _write_config(isolated_config, {"agent_name": "noddoo"})

    config = config_manager.load_config()
    assert config["ui_theme"] == "dark"


def test_set_ui_theme_persiste_y_se_relee(isolated_config):
    config_manager.set_ui_theme("light")

    assert config_manager.get_ui_theme() == "light"
    on_disk = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert on_disk["ui_theme"] == "light"


def test_set_ui_theme_normaliza_espacios_y_mayusculas(isolated_config):
    config_manager.set_ui_theme("  LIGHT  ")

    assert config_manager.get_ui_theme() == "light"


def test_set_ui_theme_no_pisa_otras_claves(isolated_config):
    _write_config(isolated_config, {"agent_name": "noddoo", "weather_city": "Bogotá"})

    config_manager.set_ui_theme("light")

    on_disk = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert on_disk["weather_city"] == "Bogotá"
    assert on_disk["agent_name"] == "noddoo"
    assert on_disk["ui_theme"] == "light"
