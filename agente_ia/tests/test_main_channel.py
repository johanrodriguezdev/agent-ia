"""
tests/test_main_channel.py

REQ-006/CA-05 — `main.py` calcula `channel` una vez por ciclo de captura y lo propaga,
en vez de los 6 literales `"desktop"` hardcodeados que existían antes de este REQ.

Se extrae la expresión real de `main.py` por regex y se evalúa (no se reimplementa la
lógica en el test, para no perder cobertura si la expresión cambia en el archivo real).
"""

import re
from pathlib import Path

from core.security_manager import ChannelType

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_PY = REPO_ROOT / "main.py"


def test_voice_input_emite_channel_voice():
    source = MAIN_PY.read_text(encoding="utf-8")
    match = re.search(
        r"channel\s*=\s*(ChannelType\.VOICE if choice in \([^)]*\) else ChannelType\.DESKTOP)",
        source,
    )
    assert match, "main.py ya no calcula `channel` con la expresión esperada de CA-05"

    expr = match.group(1)
    cases = [
        ("1", ChannelType.DESKTOP),
        ("2", ChannelType.VOICE),
        ("3", ChannelType.VOICE),
        ("q", ChannelType.DESKTOP),
    ]
    for choice, expected in cases:
        result = eval(expr, {"ChannelType": ChannelType, "choice": choice})
        assert result == expected, f"choice={choice!r} -> {result}, esperado {expected}"
