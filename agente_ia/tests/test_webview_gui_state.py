"""
tests/test_webview_gui_state.py
REQ-015/CA-44 (base) — `ui/webview/gui_state.py`: estado puro, cero imports de Qt.
Reemplaza la porción de cobertura de `tests/test_wake_word_gui.py` (REQ-009, eliminado)
que ejercitaba `GLOBAL_STATE`/`WAKE_STATE`/`update_gui_state`/`update_wake_state` en
aislamiento — acá sin ningún widget ni `qtbot`.
"""

import ui.webview.gui_state as gui_state


def test_valores_iniciales():
    assert gui_state.GLOBAL_STATE == "IDLE"
    assert gui_state.WAKE_STATE == "INACTIVE"


def test_update_gui_state_muta_variable_de_modulo():
    gui_state.update_gui_state("PROCESSING")
    assert gui_state.GLOBAL_STATE == "PROCESSING"
    gui_state.update_gui_state("IDLE")  # restaurar para no afectar otros tests
    assert gui_state.GLOBAL_STATE == "IDLE"


def test_update_wake_state_muta_variable_de_modulo():
    gui_state.update_wake_state("LISTENING_WAKE")
    assert gui_state.WAKE_STATE == "LISTENING_WAKE"
    gui_state.update_wake_state("INACTIVE")
    assert gui_state.WAKE_STATE == "INACTIVE"


def test_update_gui_state_y_wake_state_son_independientes():
    """REQ-009/CA-02 (portado) — nunca se pisan ni se confunden entre sí."""
    gui_state.update_gui_state("RESPONDING")
    gui_state.update_wake_state("AWAKE")

    assert gui_state.GLOBAL_STATE == "RESPONDING"
    assert gui_state.WAKE_STATE == "AWAKE"

    gui_state.update_gui_state("IDLE")
    gui_state.update_wake_state("INACTIVE")
