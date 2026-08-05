"""
tests/test_config_manager_display_name.py
Pruebas de `config_manager.py:get_display_name()/set_display_name()` (REQ-008/CA-04) y
del backfill de `display_name` para archivos `config.json` viejos que no lo tenían.
Redirige `config_manager.CONFIG_FILE` a `tmp_path` — nunca toca el `config.json` real
del proyecto (.claude/rules/testing.md).
"""

import json

import config_manager


def test_get_display_name_default_is_empty(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_file))

    assert config_manager.get_display_name() == ""


def test_set_display_name_persists_and_strips_whitespace(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_file))

    config_manager.set_display_name("  Ana  ")

    assert config_manager.get_display_name() == "Ana"
    with open(config_file, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["display_name"] == "Ana"


def test_load_config_backfills_display_name_for_old_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"agent_name": "glass"}), encoding="utf-8")
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_file))

    config = config_manager.load_config()

    assert config["display_name"] == ""
    assert config["agent_name"] == "glass"


def test_default_config_includes_empty_display_name():
    assert config_manager.DEFAULT_CONFIG["display_name"] == ""
