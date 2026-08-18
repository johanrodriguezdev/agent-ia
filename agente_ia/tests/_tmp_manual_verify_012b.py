"""
Verificacion manual independiente (2/2) de orion-tester para REQ-012 (NO forma parte
de la suite oficial - se borra al terminar). Objetivo: confirmar que el QTimer de
CenterPanel realmente dispara en el event loop real de Qt (no solo timeout.emit()
manual como hacen los tests de orion-dev) y que el saludo se actualiza sin
reconstruir el widget, usando un intervalo corto real y qtbot.waitSignal.
"""
from unittest.mock import MagicMock


def test_manual_timer_fires_in_real_qt_event_loop(qtbot, monkeypatch):
    import ui.widgets.center_panel as center_panel_mod

    # Intervalo corto real (50ms) en vez de 60_000ms, solo para no esperar 1 minuto real.
    monkeypatch.setattr(center_panel_mod, "_GREETING_REFRESH_MS", 50)

    mock_greeting = MagicMock(side_effect=["Buenas tardes", "Buenas noches", "Buenas noches"])
    monkeypatch.setattr(center_panel_mod, "get_time_based_greeting", mock_greeting)

    panel = center_panel_mod.CenterPanel()
    qtbot.addWidget(panel)
    assert panel._greeting_label.text() == "Buenas tardes"

    # Espera real al disparo del QTimer real (event loop de Qt), NO emit() manual.
    with qtbot.waitSignal(panel._greeting_timer.timeout, timeout=2000, raising=True):
        pass

    # Procesar eventos pendientes para que el slot conectado corra.
    qtbot.wait(50)

    assert panel._greeting_label.text() == "Buenas noches"
    assert panel.isVisible() is False  # no requirio mostrarse/reabrirse (CA-08)


def test_manual_timer_stops_on_widget_destroy(qtbot, monkeypatch):
    import ui.widgets.center_panel as center_panel_mod
    import sip if False else None  # noop, evitar import roto

    panel = center_panel_mod.CenterPanel()
    qtbot.addWidget(panel)
    timer_ref = panel._greeting_timer
    assert timer_ref.isActive()

    panel.deleteLater()
    qtbot.wait(50)

    # Tras destruirse el padre, el timer (hijo de Qt) tambien deja de existir/activo.
    import sip as _sip  # puede no existir en PyQt6; se maneja abajo
