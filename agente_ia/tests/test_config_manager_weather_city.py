"""
tests/test_config_manager_weather_city.py
Pruebas de `config_manager.py:get_weather_city()/set_weather_city()` (REQ-012/CA-01,
CA-02) y del backfill de `weather_city` para archivos `config.json` viejos que no lo
tenían. Redirige `config_manager.CONFIG_FILE` a `tmp_path` — nunca toca el
`config.json` real del proyecto (.claude/rules/testing.md), mismo patrón que
`tests/test_config_manager_display_name.py`.
"""

import json

import config_manager


def test_get_weather_city_default_is_empty(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_file))

    assert config_manager.get_weather_city() == ""


def test_set_weather_city_persists_and_strips_whitespace(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_file))

    config_manager.set_weather_city("  Bogotá  ")

    assert config_manager.get_weather_city() == "Bogotá"
    with open(config_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["weather_city"] == "Bogotá"


def test_load_config_backfills_weather_city_for_old_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"agent_name": "glass"}), encoding="utf-8")
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_file))

    config = config_manager.load_config()

    assert config["weather_city"] == ""
    assert config["agent_name"] == "glass"


def test_default_config_includes_empty_weather_city():
    assert config_manager.DEFAULT_CONFIG["weather_city"] == ""
