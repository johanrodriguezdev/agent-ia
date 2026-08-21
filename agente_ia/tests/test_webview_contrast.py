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
    ("text_primary", "bubble_agent"),   # chat.css: .msg-assistant .bubble
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


def test_burbuja_usuario_dark_usa_texto_blanco_no_text_primary():
    """CA-36 — `chat.css` fuerza `color: #ffffff` en `.msg-user .bubble` para el tema
    oscuro: `text_primary` (#e6edf3) sobre `bubble_user` (#1f77b4) da solo 4.08:1 (por
    debajo de AA normal); blanco puro da 4.82:1. Este test documenta y fija esa decisión
    contra un futuro cambio de paleta que la rompa en silencio."""
    ratio_text_primary = _contrast_ratio(DARK_TOKENS["text_primary"], DARK_TOKENS["bubble_user"])
    ratio_white = _contrast_ratio("#ffffff", DARK_TOKENS["bubble_user"])
    assert ratio_text_primary < _AA_NORMAL, (
        "si este par ahora cumple AA, revisar si sigue haciendo falta el override "
        "de #ffffff en chat.css (ver comentario ':root[data-theme=\"dark\"] .msg-user .bubble')"
    )
    assert ratio_white >= _AA_NORMAL


def test_burbuja_usuario_light_usa_text_primary():
    ratio = _contrast_ratio(LIGHT_TOKENS["text_primary"], LIGHT_TOKENS["bubble_user"])
    assert ratio >= _AA_NORMAL


def test_boton_enviar_dark_usa_bg_primary_no_blanco():
    """CA-36 — `composer.css` fuerza `color: var(--bg-primary)` en `.composer-send-btn`
    para el tema oscuro: blanco sobre `text_accent` (#58a6ff, azul claro) da solo 2.53:1,
    por debajo incluso del umbral de 3:1 para iconos/componentes de UI."""
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
