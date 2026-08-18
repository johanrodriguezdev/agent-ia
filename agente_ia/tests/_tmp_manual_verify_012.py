"""
Verificacion manual independiente de orion-tester para REQ-012 (NO forma parte de la
suite oficial - se borra al terminar). Objetivo: probar el flujo real end-to-end sin
mockear run_async ni config_manager, solo interceptando la llamada de red real
(urllib.request.urlopen), para confirmar que la ciudad configurada efectivamente viaja
hasta la URL de wttr.in a traves de QThreadPool real.
"""
import json
import io
from unittest.mock import patch, MagicMock

import config_manager


def test_manual_weather_city_end_to_end(tmp_path, monkeypatch, qtbot):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_file))
    config_manager.set_weather_city("Cartagena")

    fake_response = {
        "current_condition": [{"temp_C": "30", "lang_es": [{"value": "Soleado"}]}],
        "nearest_area": [{"areaName": [{"value": "Cartagena"}], "region": [{"value": "Bolivar"}], "country": [{"value": "Colombia"}]}],
    }

    captured_urls = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(fake_response).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        captured_urls.append(req.full_url)
        return FakeResp()

    with patch("os_integration.weather_data.urllib.request.urlopen", side_effect=fake_urlopen):
        from ui.widgets.weather_card import WeatherCard
        card = WeatherCard()
        qtbot.addWidget(card)

        qtbot.waitUntil(lambda: "Cartagena" in card._city_label.text(), timeout=3000)

    assert len(captured_urls) == 1
    assert "Cartagena" in captured_urls[0]
    assert card._temp_label.text() == "30°C"
    print("URL real usada:", captured_urls[0])


def test_manual_weather_city_empty_end_to_end(tmp_path, monkeypatch, qtbot):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_file))
    # sin set_weather_city -> default ""

    captured_urls = []

    def fake_urlopen(req, timeout=None):
        captured_urls.append(req.full_url)
        raise TimeoutError("simulado, no importa el resultado, solo la URL pedida")

    with patch("os_integration.weather_data.urllib.request.urlopen", side_effect=fake_urlopen):
        from ui.widgets.weather_card import WeatherCard
        card = WeatherCard()
        qtbot.addWidget(card)

        qtbot.waitUntil(lambda: len(captured_urls) == 1, timeout=3000)

    assert captured_urls[0] == "https://wttr.in/?format=j1&lang=es"
    print("URL real usada (sin ciudad):", captured_urls[0])
