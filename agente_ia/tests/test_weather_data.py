"""
tests/test_weather_data.py
Pruebas de `os_integration/weather_data.py:get_weather_structured()` (REQ-008/CA-10).
Sin red real: mockea `urllib.request.urlopen` con un JSON de ejemplo con la forma de
wttr.in `format=j1`, y cubre el camino de fallo (nunca debe inventar datos).
"""

import json
from unittest.mock import MagicMock, patch

from os_integration.weather_data import WeatherData, get_weather_structured

_SAMPLE_J1 = {
    "current_condition": [
        {
            "temp_C": "23",
            "lang_es": [{"value": "Parcialmente nublado"}],
            "weatherDesc": [{"value": "Partly cloudy"}],
        }
    ],
    "nearest_area": [
        {
            "areaName": [{"value": "Bogota"}],
            "region": [{"value": "Bogota D.C."}],
            "country": [{"value": "Colombia"}],
        }
    ],
}


def _mock_response(payload: dict):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    return mock_resp


def test_get_weather_structured_parses_valid_response():
    with patch("urllib.request.urlopen", return_value=_mock_response(_SAMPLE_J1)):
        data = get_weather_structured("Bogota")

    assert isinstance(data, WeatherData)
    assert data.temp_c == 23.0
    assert data.condition == "Parcialmente nublado"
    assert "Bogota" in data.city
    assert data.time_str
    assert data.date_str


def test_get_weather_structured_returns_none_on_network_error():
    with patch("urllib.request.urlopen", side_effect=OSError("sin conexión")):
        data = get_weather_structured("Bogota")
    assert data is None


def test_get_weather_structured_returns_none_on_malformed_json():
    with patch("urllib.request.urlopen", return_value=_mock_response({"unexpected": "shape"})):
        data = get_weather_structured("Bogota")
    assert data is None


def test_get_weather_structured_never_fabricates_default_city():
    """Sin ciudad y sin datos de área — nunca debe rellenar con un nombre inventado."""
    payload = {
        "current_condition": [{"temp_C": "10", "weatherDesc": [{"value": "Clear"}]}],
        "nearest_area": [{}],
    }
    with patch("urllib.request.urlopen", return_value=_mock_response(payload)):
        data = get_weather_structured("")
    assert data is not None
    assert data.city == "Ubicación desconocida"
