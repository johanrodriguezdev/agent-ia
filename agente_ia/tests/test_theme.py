"""
tests/test_theme.py
REQ-013/CA-01, CA-03 — paleta única de `ui/theme.py`.

`test_palette_contrast_ratios` es el criterio OBJETIVO de CA-03: recalcula el ratio de
contraste WCAG real de cada par texto/fondo del layout y falla si alguno baja del umbral.
Si un par no llega, se ajusta el hex de la paleta y se documenta el cambio en
`desarrollo-log-013.md` — nunca se relaja el umbral de este test.
"""

from dataclasses import asdict
from string import Template

import pytest

from ui.theme import (
    DARK_PALETTE,
    DEFAULT_THEME,
    LIGHT_PALETTE,
    THEMES,
    Palette,
    ThemeManager,
    qss_tokens,
    resolve_theme_name,
)

# Umbrales WCAG 2.1: 4.5:1 para texto normal (1.4.3 AA), 3.0:1 para texto grande (>=24px)
# y componentes de UI no textuales (1.4.11).
_AA_NORMAL = 4.5
_AA_LARGE = 3.0

# Pares texto/fondo que el layout realmente combina. Cada uno debe ser legible en AMBAS
# paletas (ver arquitectura-013.md §3.1).
_PAIRS_NORMAL_TEXT = [
    ("text_primary", "bg_window"),
    ("text_primary", "bg_surface"),
    ("text_primary", "bg_elevated"),
    ("text_primary", "bg_input"),
    ("text_primary", "bg_hover"),
    ("text_secondary", "bg_window"),
    ("text_secondary", "bg_surface"),
    ("text_secondary", "bg_elevated"),
    ("text_secondary", "bg_input"),
    ("text_muted", "bg_window"),
    ("text_muted", "bg_surface"),
    ("text_muted", "bg_elevated"),
    ("text_muted", "bg_input"),
    ("text_muted", "bg_hover"),
    ("text_muted", "bubble_ai_bg"),
    ("accent", "bg_window"),
    ("accent", "bg_surface"),
    ("accent", "bg_elevated"),
    ("accent", "bg_input"),
    # REQ-013 (2da pasada, CA-03 FAIL de orion-tester): se usaba en `_PAIRS_LARGE_TEXT`
    # (umbral 3.0:1) pese a estilar texto normal de 12-14px en producción — `#ModePill`
    # (header_bar.py), `#NewConversationButton` (conversation_list.py) y `#WakeIndicator`
    # (header_bar.py), ninguno >=18.66px/24px. Reclasificado al umbral correcto de 4.5:1.
    ("accent", "accent_soft"),
    ("bubble_user_fg", "bubble_user_bg"),
    ("bubble_ai_fg", "bubble_ai_bg"),
    ("on_accent", "accent"),
    ("success", "bg_surface"),
    ("success", "bg_elevated"),
    ("warning", "bg_elevated"),
    ("danger", "bg_surface"),
    ("danger", "bg_elevated"),
    # REQ-013 (2da pasada, CA-03 FAIL de orion-tester): `text_disabled` no tenía cobertura
    # y su contraste real contra `bg_surface` (usado en `#SidebarNavButton:disabled`,
    # sidebar.py:126 — los 5 ítems de navegación deshabilitados) medía muy por debajo de
    # AA en ambos temas. Ver desarrollo-log-013.md.
    ("text_disabled", "bg_surface"),
]

# REQ-013 (2da pasada): vacío por ahora — el único par que vivía acá (`accent`/
# `accent_soft`) se reclasificó a `_PAIRS_NORMAL_TEXT` porque su uso real en producción
# es texto de 12-14px, no texto grande. Se deja la lista (y el umbral `_AA_LARGE`) para el
# día que un par realmente proteja texto >=24px o >=18.66px en negrita.
_PAIRS_LARGE_TEXT: list = []


def _relative_luminance(hex_color: str) -> float:
    """Luminancia relativa WCAG 2.1 de un color `#rrggbb`."""
    raw = hex_color.lstrip("#")
    channels = [int(raw[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    lum_a, lum_b = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def test_contrast_helper_matches_known_wcag_values():
    """El helper es la vara de medir de CA-03 — se verifica antes de usarlo."""
    assert _contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0, abs=0.01)
    assert _contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize("palette", [DARK_PALETTE, LIGHT_PALETTE], ids=["dark", "light"])
def test_palette_contrast_ratios(palette):
    """CA-03 — contraste legible entre texto y fondo en ambos modos."""
    tokens = qss_tokens(palette)
    failures = []

    for fg, bg in _PAIRS_NORMAL_TEXT:
        ratio = _contrast_ratio(tokens[fg], tokens[bg])
        if ratio < _AA_NORMAL:
            failures.append(f"{palette.name}: {fg}/{bg} = {ratio:.2f} < {_AA_NORMAL}")

    for fg, bg in _PAIRS_LARGE_TEXT:
        ratio = _contrast_ratio(tokens[fg], tokens[bg])
        if ratio < _AA_LARGE:
            failures.append(f"{palette.name}: {fg}/{bg} = {ratio:.2f} < {_AA_LARGE}")

    assert not failures, "Pares con contraste insuficiente:\n" + "\n".join(failures)


def test_ambos_temas_definen_todos_los_tokens():
    dark, light = asdict(DARK_PALETTE), asdict(LIGHT_PALETTE)
    assert dark.keys() == light.keys()

    for token in dark:
        if token == "orb_colors":
            continue
        assert dark[token], f"token vacío en dark: {token}"
        assert light[token], f"token vacío en light: {token}"

    for palette in (DARK_PALETTE, LIGHT_PALETTE):
        assert set(palette.orb_colors) == {"IDLE", "LISTENING", "PROCESSING", "RESPONDING"}
        for state_colors in palette.orb_colors.values():
            assert set(state_colors) == {"core", "glow", "ring"}


def test_qss_tokens_excluye_orb_colors_y_es_todo_string():
    tokens = qss_tokens(DARK_PALETTE)
    assert "orb_colors" not in tokens
    assert all(isinstance(value, str) for value in tokens.values())


@pytest.mark.parametrize("raw", ["", "   ", "azul", "DARKK", None, 42, [], "light "])
def test_resolve_theme_name_normaliza_valor_invalido(raw):
    resolved = resolve_theme_name(raw)
    assert resolved in THEMES
    if raw == "light ":
        assert resolved == "light"  # se normalizan espacios
    else:
        assert resolved == DEFAULT_THEME


@pytest.mark.parametrize("raw", ["dark", "DARK", " Light ", "light"])
def test_resolve_theme_name_acepta_los_del_catalogo(raw):
    assert resolve_theme_name(raw) == raw.strip().lower()


def test_qss_templates_sustituyen_sin_keyerror():
    """Todo módulo con QSS por paleta debe sustituir sin dejar ningún `$token` suelto.

    Es la red de seguridad de la decisión "`string.Template`, no `str.format`":
    si alguien agrega un token nuevo al QSS y olvida agregarlo a `Palette`,
    `substitute()` lanza `KeyError` acá y no en producción.
    """
    import ui.gui as gui_module
    import ui.widgets.center_panel as center_panel
    import ui.widgets.chat_feed as chat_feed
    import ui.widgets.composer as composer
    import ui.widgets.conversation_list as conversation_list
    import ui.widgets.header_bar as header_bar
    import ui.widgets.quick_actions_card as quick_actions_card
    import ui.widgets.recent_activity_card as recent_activity_card
    import ui.widgets.right_panel as right_panel
    import ui.widgets.sidebar as sidebar
    import ui.widgets.system_status_card as system_status_card
    import ui.widgets.weather_card as weather_card

    modules = [
        gui_module, center_panel, chat_feed, composer, conversation_list, header_bar,
        quick_actions_card, recent_activity_card, right_panel, sidebar,
        system_status_card, weather_card,
    ]

    for module in modules:
        assert isinstance(module._QSS_TEMPLATE, Template), f"{module.__name__} sin plantilla"
        for palette in (DARK_PALETTE, LIGHT_PALETTE):
            qss = module._qss(palette)
            assert "$" not in qss, f"token sin sustituir en {module.__name__} ({palette.name})"


# ---------------------------------------------------------------------------
# ThemeManager
# ---------------------------------------------------------------------------

def test_theme_manager_toggle_alterna_y_emite(monkeypatch):
    manager = ThemeManager()
    persisted = []
    monkeypatch.setattr("ui.theme.config_manager.set_ui_theme", persisted.append)

    received = []
    manager.theme_changed.connect(received.append)

    assert manager.current_name() == "dark"
    assert manager.toggle() == "light"
    assert manager.palette() is LIGHT_PALETTE
    assert persisted == ["light"]
    assert len(received) == 1
    assert isinstance(received[0], Palette)

    assert manager.toggle() == "dark"
    assert persisted == ["light", "dark"]
    assert len(received) == 2


def test_theme_manager_set_theme_mismo_valor_no_emite(monkeypatch):
    manager = ThemeManager()
    monkeypatch.setattr("ui.theme.config_manager.set_ui_theme", lambda _name: None)

    received = []
    manager.theme_changed.connect(received.append)

    manager.set_theme("dark")  # ya es el activo
    assert received == []


def test_theme_manager_load_from_config_no_persiste(monkeypatch):
    manager = ThemeManager()
    monkeypatch.setattr("ui.theme.config_manager.get_ui_theme", lambda: "light")
    monkeypatch.setattr(
        "ui.theme.config_manager.set_ui_theme",
        lambda _name: pytest.fail("load_from_config() no debe reescribir config.json"),
    )

    manager.load_from_config()
    assert manager.current_name() == "light"


def test_theme_manager_load_from_config_valor_corrupto_cae_a_dark(monkeypatch):
    manager = ThemeManager()
    monkeypatch.setattr("ui.theme.config_manager.get_ui_theme", lambda: "#hackeado { }")
    monkeypatch.setattr("ui.theme.config_manager.set_ui_theme", lambda _name: None)

    manager.load_from_config()
    assert manager.current_name() == DEFAULT_THEME


def test_register_themed_aplica_y_suscribe(monkeypatch):
    from PyQt6.QtCore import QObject

    import ui.theme as theme_module

    manager = ThemeManager()
    monkeypatch.setattr(theme_module, "theme_manager", manager)
    monkeypatch.setattr("ui.theme.config_manager.set_ui_theme", lambda _name: None)

    class Themed(QObject):
        def __init__(self):
            super().__init__()
            self.applied = []

        def apply_theme(self, palette):
            self.applied.append(palette.name)

    widget = Themed()
    theme_module.register_themed(widget)
    assert widget.applied == ["dark"]

    manager.set_theme("light")
    assert widget.applied == ["dark", "light"]
