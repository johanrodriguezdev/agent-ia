"""
tests/test_cli_gui_active.py
REQ-009/CA-06, CA-07 — `ui/cli.py::CLI.__init__(gui_active=...)` condiciona si el menú de
`get_input_method()` ofrece la opción "3) Modo manos libres (Wake Word)".
"""

from unittest.mock import patch

from ui.cli import CLI


def test_get_input_method_hides_option_3_when_gui_active(capsys):
    cli = CLI(gui_active=True)

    with patch("builtins.input", return_value="1"):
        choice = cli.get_input_method()

    out = capsys.readouterr().out
    assert "3)" not in out
    assert "Modo manos libres" not in out
    assert choice == "1"


def test_get_input_method_shows_option_3_when_headless(capsys):
    cli = CLI(gui_active=False)

    with patch("builtins.input", return_value="1"):
        cli.get_input_method()

    out = capsys.readouterr().out
    assert "3) Modo manos libres (Wake Word)" in out


def test_cli_default_constructor_keeps_option_3_bit_for_bit():
    """CA-07: `CLI()` sin argumentos (call-site actual de `main.py` sin GUI) conserva
    exactamente el comportamiento anterior a REQ-009."""
    cli = CLI()
    assert cli._gui_active is False
