"""
tests/test_personality_greeting.py
Pruebas de `ui/personality.py:get_time_based_greeting()` (REQ-008/CA-03/CA-04). Cubre
los 3 rangos horarios exactos de SPEC-008 (19:00-04:59 noche, 05:00-11:59 día,
12:00-18:59 tarde, con el rango nocturno evaluado primero por envolver medianoche) y la
resolución con/sin `display_name`.
"""

from datetime import datetime
from unittest.mock import patch

import pytest

from ui.personality import get_time_based_greeting


def _fake_now(hour: int):
    return datetime(2026, 1, 1, hour, 0, 0)


@pytest.mark.parametrize("hour", [19, 22, 0, 4])
def test_greeting_is_buenas_noches_in_night_range(hour):
    with patch("ui.personality.datetime") as mock_dt:
        mock_dt.now.return_value = _fake_now(hour)
        assert get_time_based_greeting() == "Buenas noches"


@pytest.mark.parametrize("hour", [5, 8, 11])
def test_greeting_is_buenos_dias_in_morning_range(hour):
    with patch("ui.personality.datetime") as mock_dt:
        mock_dt.now.return_value = _fake_now(hour)
        assert get_time_based_greeting() == "Buenos días"


@pytest.mark.parametrize("hour", [12, 15, 18])
def test_greeting_is_buenas_tardes_in_afternoon_range(hour):
    with patch("ui.personality.datetime") as mock_dt:
        mock_dt.now.return_value = _fake_now(hour)
        assert get_time_based_greeting() == "Buenas tardes"


def test_greeting_appends_display_name_with_comma():
    with patch("ui.personality.datetime") as mock_dt:
        mock_dt.now.return_value = _fake_now(9)
        assert get_time_based_greeting("Ana") == "Buenos días, Ana"


def test_greeting_without_display_name_has_no_trailing_comma():
    with patch("ui.personality.datetime") as mock_dt:
        mock_dt.now.return_value = _fake_now(9)
        greeting = get_time_based_greeting("")
        assert greeting == "Buenos días"
        assert "," not in greeting
