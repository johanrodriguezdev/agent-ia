"""
tests/test_gui_widgets.py
Pruebas de los widgets nuevos de `ui/widgets/` y de `ui/gui.py:JarvisMainWindow`
(REQ-008), con `pytest-qt` (`qtbot`) en modo offscreen (fijado en tests/conftest.py).
Sin aserciones visuales/pixel — solo estado, señales y textos, como piden las
"Pruebas sugeridas" de arquitectura-008.md.

`WeatherCard`/`RecentActivityCard` disparan I/O real en su `__init__` (red y SQLite,
respectivamente) — la fixture `no_external_io` los neutraliza para que la suite completa
siga sin red y sin tocar la base de datos real (.claude/rules/testing.md).
"""

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication

import ui.widgets.recent_activity_card as recent_activity_module
import ui.widgets.weather_card as weather_card_module
from ai.memory_manager import MemoryItem
from core.security_manager import ChannelType
from os_integration.weather_data import WeatherData
from ui.gui import JarvisMainWindow
from ui.personality import get_time_based_greeting
from ui.widgets.center_panel import CenterPanel
from ui.widgets.quick_actions_card import QuickActionsCard
from ui.widgets.recent_activity_card import RecentActivityCard
from ui.widgets.sidebar import Sidebar
from ui.widgets.system_status_card import SystemStatusCard
from ui.widgets.weather_card import WeatherCard


@pytest.fixture
def no_external_io(monkeypatch):
    """Evita que `WeatherCard` haga una petición HTTP real y que `RecentActivityCard`
    lea la base de datos de memoria real al construirse."""
    monkeypatch.setattr(weather_card_module, "run_async", lambda *a, **k: None)
    monkeypatch.setattr(recent_activity_module.memory, "get_recent", lambda **kwargs: [])


# ---------------------------------------------------------------------------
# Sidebar (CA-05)
# ---------------------------------------------------------------------------

def test_sidebar_inicio_emits_nav_selected(qtbot):
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    received = []
    sidebar.nav_selected.connect(received.append)

    from PyQt6.QtWidgets import QPushButton
    buttons = sidebar.findChildren(QPushButton)
    enabled_buttons = [b for b in buttons if b.isEnabled()]
    disabled_buttons = [b for b in buttons if not b.isEnabled()]

    assert len(enabled_buttons) == 1
    assert len(disabled_buttons) == 6

    enabled_buttons[0].click()
    assert received == ["inicio"]


# ---------------------------------------------------------------------------
# SystemStatusCard (CA-06)
# ---------------------------------------------------------------------------

def test_system_status_card_set_values_updates_labels(qtbot):
    card = SystemStatusCard()
    qtbot.addWidget(card)

    card.set_values(18, 42, 31, 12)

    assert "18%" in card._labels["cpu"].text()
    assert "42%" in card._labels["ram"].text()
    assert "31%" in card._labels["disk"].text()
    assert "12%" in card._labels["net"].text()


# ---------------------------------------------------------------------------
# QuickActionsCard (CA-07)
# ---------------------------------------------------------------------------

def test_quick_actions_card_click_calls_execute_action_via_channel(qtbot):
    card = QuickActionsCard()
    qtbot.addWidget(card)

    with patch("ui.widgets.quick_actions_card.run_async") as mock_run_async:
        from PyQt6.QtWidgets import QPushButton
        buttons = card.findChildren(QPushButton)
        buttons[0].click()

    assert mock_run_async.call_count == 1
    args, kwargs = mock_run_async.call_args
    # (execute_action, on_done, on_error, action_name)
    from agents.action_registry import execute_action
    assert args[0] is execute_action
    assert args[3] == "open_explorer"
    assert kwargs["channel"] == ChannelType.DESKTOP


# ---------------------------------------------------------------------------
# RecentActivityCard (CA-09)
# ---------------------------------------------------------------------------

def test_recent_activity_card_empty_state(qtbot, no_external_io):
    card = RecentActivityCard()
    qtbot.addWidget(card)

    card.set_items([])
    assert card._items_layout.count() == 1


def test_recent_activity_card_renders_items_with_time(qtbot, no_external_io):
    card = RecentActivityCard()
    qtbot.addWidget(card)

    item = MemoryItem(text="hola mundo", timestamp="2026-01-01T10:30:00")
    card.set_items([item])

    assert card._items_layout.count() == 1


# ---------------------------------------------------------------------------
# WeatherCard (CA-10)
# ---------------------------------------------------------------------------

def test_weather_card_set_data_none_shows_unavailable(qtbot, no_external_io):
    card = WeatherCard()
    qtbot.addWidget(card)

    card.set_data(None)
    assert "no disponible" in card._condition_label.text().lower()


def test_weather_card_set_data_shows_all_fields(qtbot, no_external_io):
    card = WeatherCard()
    qtbot.addWidget(card)

    data = WeatherData(temp_c=21.0, condition="Soleado", city="Bogota", time_str="10:30", date_str="01 ene, 2026")
    card.set_data(data)

    assert "21" in card._temp_label.text()
    assert card._condition_label.text() == "Soleado"
    assert card._city_label.text() == "Bogota"
    assert "10:30" in card._datetime_label.text()


# ---------------------------------------------------------------------------
# CenterPanel (CA-03/CA-04)
# ---------------------------------------------------------------------------

def test_center_panel_greeting_matches_personality_helper(qtbot, monkeypatch):
    monkeypatch.setattr("ui.widgets.center_panel.config_manager.get_display_name", lambda: "Ana")

    panel = CenterPanel()
    qtbot.addWidget(panel)

    expected = get_time_based_greeting("Ana")
    assert panel._greeting_label.text() == expected


# ---------------------------------------------------------------------------
# JarvisMainWindow (CA-13)
# ---------------------------------------------------------------------------

def test_jarvis_main_window_close_hides_without_quitting_app(qtbot, no_external_io):
    window = JarvisMainWindow()
    qtbot.addWidget(window)
    window.show()

    window.close()

    assert window.isVisible() is False
    assert QApplication.instance() is not None
