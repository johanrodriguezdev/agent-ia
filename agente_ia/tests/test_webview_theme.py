"""
tests/test_webview_theme.py
REQ-015/CA-35, CA-38 — `ui/webview/theme.py`.

`test_theme_css_no_diverge_de_los_tokens_python` es el test de drift explícito que pide
arquitectura-015.md §1 (fila CA-35): parsea `ui/webview/frontend/css/theme.css` (fuente
#2 de verdad) y compara byte a byte contra `DARK_TOKENS`/`LIGHT_TOKENS` (fuente #1, este
módulo) — si alguien cambia un hex en un solo lugar, este test falla.
"""

import re
from pathlib import Path

import pytest

from ui.webview.theme import DARK_TOKENS, DEFAULT_THEME, LIGHT_TOKENS, THEMES, resolve_theme_name

_THEME_CSS_PATH = (
    Path(__file__).resolve().parent.parent / "ui" / "webview" / "frontend" / "css" / "theme.css"
)

_BLOCK_RE = re.compile(r':root\[data-theme="(dark|light)"\]\s*\{([^}]*)\}')
_PROP_RE = re.compile(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;")


def _parse_theme_css() -> dict:
    """Devuelve `{"dark": {token: hex}, "light": {token: hex}}` desde el CSS real."""
    css = _THEME_CSS_PATH.read_text(encoding="utf-8")
    parsed = {}
    for theme_name, body in _BLOCK_RE.findall(css):
        tokens = {}
        for css_name, value in _PROP_RE.findall(body):
            tokens[css_name.replace("-", "_")] = value.lower()
        parsed[theme_name] = tokens
    return parsed


def test_theme_css_existe():
    assert _THEME_CSS_PATH.is_file(), f"no se encontró {_THEME_CSS_PATH}"


def test_theme_css_no_diverge_de_los_tokens_python():
    parsed = _parse_theme_css()
    assert "dark" in parsed and "light" in parsed

    for token, expected_hex in DARK_TOKENS.items():
        assert token in parsed["dark"], f"falta --{token.replace('_', '-')} en theme.css (dark)"
        assert parsed["dark"][token] == expected_hex.lower(), (
            f"drift en dark.{token}: CSS={parsed['dark'][token]!r} vs "
            f"Python={expected_hex.lower()!r}"
        )

    for token, expected_hex in LIGHT_TOKENS.items():
        assert token in parsed["light"], f"falta --{token.replace('_', '-')} en theme.css (light)"
        assert parsed["light"][token] == expected_hex.lower(), (
            f"drift en light.{token}: CSS={parsed['light'][token]!r} vs "
            f"Python={expected_hex.lower()!r}"
        )


def test_ambos_temas_definen_los_mismos_tokens():
    assert set(DARK_TOKENS.keys()) == set(LIGHT_TOKENS.keys())
    for token, value in {**DARK_TOKENS, **LIGHT_TOKENS}.items():
        assert value, f"token vacío: {token}"
        assert value.startswith("#"), f"token no-hex: {token}={value!r}"


def test_default_theme_es_light_ca38():
    """REQ-015/CA-38 — cambia de 'dark' (REQ-013) a 'light' (ya validado en REQ-014
    addendum §7)."""
    assert DEFAULT_THEME == "light"
    assert DEFAULT_THEME in THEMES


@pytest.mark.parametrize("raw", ["", "   ", "azul", "DARKK", None, 42, [], "dark "])
def test_resolve_theme_name_normaliza_valor_invalido(raw):
    resolved = resolve_theme_name(raw)
    assert resolved in THEMES
    if raw == "dark ":
        assert resolved == "dark"  # se normalizan espacios
    else:
        assert resolved == DEFAULT_THEME


@pytest.mark.parametrize("raw", ["dark", "DARK", " Light ", "light"])
def test_resolve_theme_name_acepta_los_del_catalogo(raw):
    assert resolve_theme_name(raw) == raw.strip().lower()
