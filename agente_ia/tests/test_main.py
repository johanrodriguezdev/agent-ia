"""
tests/test_main.py

REQ-006/CA-12 — bug de `main.py:_ProactiveAssistant.can_handle()`: antes de este REQ, el
método tenía un ternario que retornaba `0.0` en ambas ramas (nunca `0.6`), así que este
agente nunca podía ganar la selección de `AgentOrchestrator`. El fix es un `if/else` real.

Importar `main` completo dispara el registro de skills/logging habitual de arranque (ya
verificado en sesiones previas: no cuelga, no depende de red/mic). Se importa una sola vez
a nivel de módulo para no repetir ese costo por test.
"""

import main


def test_proactive_assistant_can_handle_briefing():
    assistant = main._ProactiveAssistant()
    assert assistant.can_handle("quiero un briefing") == 0.6
    assert assistant.can_handle("ponme un recordatorio") == 0.6


def test_proactive_assistant_can_handle_no_coincide():
    assistant = main._ProactiveAssistant()
    assert assistant.can_handle("hola, como estas") == 0.0


def test_proactive_assistant_ramas_devuelven_valores_distintos():
    """El bug H original: ambas ramas del ternario devolvían 0.0. Confirma que ahora
    difieren cuando el texto coincide vs. cuando no."""
    assistant = main._ProactiveAssistant()
    con_match = assistant.can_handle("dame el briefing de hoy")
    sin_match = assistant.can_handle("cuentame un chiste")
    assert con_match != sin_match
