"""
tests/test_webview_contrast.py
REQ-015/CA-36 — reemplaza `tests/test_theme.py` (REQ-013, eliminado): mismo algoritmo
WCAG 2.1 de luminancia relativa, ahora contra los hex de `ui/webview/theme.py` y los
pares texto/fondo realmente usados en `ui/webview/frontend/css/*.css`.

Cada par de este archivo corresponde a una combinación real de CSS (no combinaciones
teóricas) — si se agrega un color hardcodeado nuevo a una hoja de estilo, agregar acá el
par correspondiente antes de usarlo en producción.
"""

import pytest

from ui.webview.theme import DARK_TOKENS, LIGHT_TOKENS

# Umbrales WCAG 2.1: 4.5:1 para texto normal (1.4.3 AA), 3.0:1 para texto grande/negrita y
# componentes de UI no textuales como iconos y indicadores (1.4.11).
_AA_NORMAL = 4.5
_AA_LARGE_OR_UI = 3.0

# Pares texto/fondo de tamaño normal (13-15px) que el layout combina de verdad — ver
# ui/webview/frontend/css/{layout,sidebar,chat,composer}.css.
_NORMAL_TEXT_PAIRS = [
    ("text_primary", "bg_primary"),
    ("text_primary", "bg_secondary"),
    ("text_primary", "bg_input"),
    ("text_primary", "bg_hover"),       # sidebar.css: .conv-item:hover sube a text_primary
    ("text_secondary", "bg_primary"),
    ("text_secondary", "bg_secondary"),
    ("text_secondary", "bg_input"),     # composer.css: ::placeholder
    ("text_accent", "bg_primary"),      # chat.css: enlaces / botón "Ver más"
    ("text_accent", "bg_secondary"),    # sidebar.css: botón "Ver más"
    ("text_primary", "bubble_agent"),   # chat.css: fondo de los bloques de codigo
    ("text_primary", "bubble_user"),    # chat.css: .msg-user .bubble
]


def _relative_luminance(hex_color: str) -> float:
    raw = hex_color.lstrip("#")
    channels = [int(raw[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    lum_a, lum_b = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def test_contrast_helper_matches_known_wcag_values():
    assert _contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0, abs=0.01)
    assert _contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize("theme_name,tokens", [("dark", DARK_TOKENS), ("light", LIGHT_TOKENS)])
def test_normal_text_pairs_cumplen_aa(theme_name, tokens):
    failures = []
    for fg, bg in _NORMAL_TEXT_PAIRS:
        ratio = _contrast_ratio(tokens[fg], tokens[bg])
        if ratio < _AA_NORMAL:
            failures.append(f"{theme_name}: {fg}/{bg} = {ratio:.2f} < {_AA_NORMAL}")
    assert not failures, "Pares de texto normal con contraste insuficiente:\n" + "\n".join(failures)


def test_burbuja_usuario_usa_text_primary_en_ambos_temas():
    """Rediseño — la burbuja del usuario dejó de ser un azul saturado (`#1f77b4` en
    oscuro) y pasó a ser una superficie neutra de la paleta. Con eso, `text_primary`
    encima cumple AA en los dos temas y ya no hace falta el override de `#ffffff` que
    `chat.css` tenía para el tema oscuro (había que forzarlo porque el par daba 4.08:1).

    Este test fija la decisión: si alguien vuelve a poner un color saturado en
    `bubble_user` y el par baja de AA, falla acá antes de llegar a la pantalla."""
    for theme_name, tokens in (("dark", DARK_TOKENS), ("light", LIGHT_TOKENS)):
        ratio = _contrast_ratio(tokens["text_primary"], tokens["bubble_user"])
        assert ratio >= _AA_NORMAL, (
            f"{theme_name}: text_primary/bubble_user = {ratio:.2f} < {_AA_NORMAL} — si el "
            "color de la burbuja tiene que ser ese, hay que volver a forzar el color del "
            "texto en chat.css (:root[data-theme=...] .msg-user .bubble)"
        )


def test_boton_enviar_dark_usa_bg_primary_no_blanco():
    """CA-36 — `composer.css` fuerza `color: var(--bg-primary)` en `.composer-send-btn`
    para el tema oscuro: blanco sobre `text_accent` (un azul claro) queda por debajo
    incluso del umbral de 3:1 para iconos/componentes de UI. El mismo override aplican
    `.panel-submit-btn` (panels.css) y `.settings-primary-btn` (settings_panel.css), que
    son los otros dos rellenos de acento de la interfaz."""
    ratio_white = _contrast_ratio("#ffffff", DARK_TOKENS["text_accent"])
    ratio_bg_primary = _contrast_ratio(DARK_TOKENS["bg_primary"], DARK_TOKENS["text_accent"])
    assert ratio_white < _AA_LARGE_OR_UI
    assert ratio_bg_primary >= _AA_LARGE_OR_UI


@pytest.mark.parametrize("theme_name,tokens", [("dark", DARK_TOKENS), ("light", LIGHT_TOKENS)])
def test_iconos_sobre_boton_danger_cumplen_umbral_de_componente_ui(theme_name, tokens):
    """`.window-btn-close:hover`/`.conv-delete-btn:hover` — glifo blanco sobre `danger`,
    tratado como componente de UI no textual (umbral 3:1, WCAG 1.4.11), no como texto
    normal (los iconos ✕/– son glifos decorativos pequeños, no párrafos de texto)."""
    ratio = _contrast_ratio("#ffffff", tokens["danger"])
    assert ratio >= _AA_LARGE_OR_UI, f"{theme_name}: blanco/danger = {ratio:.2f} < {_AA_LARGE_OR_UI}"


@pytest.mark.parametrize("theme_name,tokens", [("dark", DARK_TOKENS), ("light", LIGHT_TOKENS)])
def test_puntos_de_riesgo_de_chips_cumplen_umbral_de_componente_ui(theme_name, tokens):
    """`.chip-risk-dot` (CA-40) — indicador de color puro sobre `bg_primary`, componente
    de UI no textual (umbral 3:1)."""
    for token in ("success", "warning", "danger"):
        ratio = _contrast_ratio(tokens[token], tokens["bg_primary"])
        assert ratio >= _AA_LARGE_OR_UI, (
            f"{theme_name}: {token}/bg_primary = {ratio:.2f} < {_AA_LARGE_OR_UI}"
        )


def test_ambos_temas_definen_todos_los_tokens_usados():
    used_tokens = {fg for fg, _ in _NORMAL_TEXT_PAIRS} | {bg for _, bg in _NORMAL_TEXT_PAIRS}
    used_tokens |= {"bubble_user", "success", "warning", "danger"}
    for token in used_tokens:
        assert token in DARK_TOKENS, f"falta {token} en DARK_TOKENS"
        assert token in LIGHT_TOKENS, f"falta {token} en LIGHT_TOKENS"


def test_boton_confirmar_amarillo_cumple_aa_en_ambos_temas():
    """`.modal-btn-confirm` (modal.css) es el único relleno de `--warning` con texto
    encima: la confirmación de una acción 🟡. El amarillo del tema claro es más oscuro
    (tiene que contrastar contra fondo blanco), así que ahí el texto casi negro no llega
    a AA y el CSS lo pasa a blanco — este test fija los dos casos."""
    ratio_dark = _contrast_ratio("#1a1300", DARK_TOKENS["warning"])
    ratio_light = _contrast_ratio("#ffffff", LIGHT_TOKENS["warning"])
    assert ratio_dark >= _AA_NORMAL, f"dark: #1a1300/warning = {ratio_dark:.2f}"
    assert ratio_light >= _AA_NORMAL, f"light: #ffffff/warning = {ratio_light:.2f}"
