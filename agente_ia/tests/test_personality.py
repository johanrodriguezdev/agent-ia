"""
tests/test_personality.py
El saludo del agente y la hora.
"""

from unittest.mock import patch

import pytest


# ─────────────────────────────────────────────
#  Dos relojes que decían cosas distintas
# ─────────────────────────────────────────────

@pytest.mark.parametrize("hora,esperado", [
    (8, "Buenos días"), (11, "Buenos días"),
    (12, "Buenas tardes"), (18, "Buenas tardes"),
    (19, "Buenas noches"), (23, "Buenas noches"), (2, "Buenas noches"),
])
def test_el_saludo_del_agente_mira_el_reloj(hora, esperado):
    """A las 23:30 la pantalla saludaba "Buenas noches" —lo calcula de la hora local— y el
    agente contestaba "Buenos días" en la misma ventana. No era una diferencia de opinión:
    `get_random_greeting()` elegía al azar de una lista fija y la primera entrada empezaba
    con "Buenos dias". Eran dos relojes, y uno no existía.
    """
    import datetime as dt

    import ui.personality as personality

    class _Reloj(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 9, 4, hora, 30)

    with patch.object(personality, "datetime", _Reloj):
        assert personality.get_random_greeting().startswith(esperado)


def test_las_franjas_coinciden_con_las_de_la_pantalla():
    """Los cortes son los mismos que los de `ui/webview/frontend/js/app.js`: si se mueven
    en un lado y no en el otro, vuelve el desacuerdo entre lo que dice la pantalla y lo que
    dice el agente."""
    from pathlib import Path

    app_js = (Path(__file__).resolve().parent.parent
              / "ui" / "webview" / "frontend" / "js" / "app.js").read_text(encoding="utf-8")

    assert "from: 5, to: 12" in app_js, "cambió la franja de mañana en la pantalla"
    assert "from: 12, to: 19" in app_js, "cambió la franja de tarde en la pantalla"


def test_el_modelo_recibe_la_hora_y_la_zona():
    """Sin esto el modelo no sabe qué hora es y lo resuelve como puede. `claude_brain` ya
    se lo decía a Telegram; el escritorio y la voz eran justo los que no."""
    from core.address import momento_actual
    from core.reasoning_loop import _build_system_prompt

    momento = momento_actual()

    assert "zona horaria" in momento
    assert momento.split()[0] in (
        "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"
    ), f"el día debería estar en español: {momento}"
    assert momento in _build_system_prompt()


def test_la_hora_va_al_final_del_prompt():
    """Los proveedores con caché de prefijo solo reutilizan lo que no cambia desde el
    principio: con la hora al minuto en medio, todo lo que viene detrás se recalcularía
    cada 60 segundos."""
    from core.reasoning_loop import _build_system_prompt

    prompt = _build_system_prompt()

    assert prompt.rstrip().endswith(
        prompt[prompt.index("Fecha y hora actual:"):].rstrip()
    )
