"""
tests/test_weather_skill.py
REQ-012 — la ciudad del usuario se usa cuando no dice ninguna.

El bug original de REQ-012 ("el clima muestra una ubicación incorrecta") se escribió contra
el panel de clima de la GUI JARVIS, que se eliminó en REQ-015. Pero el camino que sobrevivió
—preguntarle el clima al agente— tenía el mismo problema: `skills/weather_skill.py` se caía
directo a la geolocalización por IP, que con un VPN o según el proveedor devuelve otra
ciudad, teniendo la del usuario ya configurada en `config_manager.get_weather_city()` y sin
consultarla nunca.

Sin red: `urlopen` está mockeado en todos los casos (.claude/rules/testing.md).
"""

from unittest.mock import MagicMock, patch

import pytest

from skills.weather_skill import WeatherSkill


def _respuesta(texto: str) -> MagicMock:
    """Doble de `urlopen` usado como context manager."""
    fake = MagicMock()
    fake.return_value.__enter__.return_value.read.return_value = texto.encode("utf-8")
    return fake


@pytest.fixture
def skill() -> WeatherSkill:
    return WeatherSkill()


def _url_consultada(fake_urlopen: MagicMock) -> str:
    return fake_urlopen.call_args[0][0].full_url


def test_sin_ciudad_dicha_usa_la_configurada(skill):
    fake = _respuesta("Medellin: ☀️ +24°C")
    with patch("config_manager.get_weather_city", return_value="Medellín"), \
         patch("urllib.request.urlopen", fake):
        skill.execute("GET_WEATHER", {"city": ""})

    assert "Medell" in _url_consultada(fake), "tenía que consultar por la ciudad configurada"


def test_la_ciudad_dicha_le_gana_a_la_configurada(skill):
    """Pedir "el clima en Madrid" no puede quedar pisado por la ciudad de configuración:
    lo que el usuario dice en la frase manda."""
    fake = _respuesta("Madrid: ☀️ +18°C")
    with patch("config_manager.get_weather_city", return_value="Medellín"), \
         patch("urllib.request.urlopen", fake):
        skill.execute("GET_WEATHER", {"city": "Madrid"})

    url = _url_consultada(fake)
    assert "Madrid" in url
    assert "Medell" not in url


def test_sin_ciudad_configurada_sigue_el_fallback_por_ip(skill):
    """El comportamiento de antes se conserva para quien no configuró nada: wttr.in sin
    ciudad geolocaliza por IP."""
    fake = _respuesta("Bogota: ☁️ +19°C")
    with patch("config_manager.get_weather_city", return_value=""), \
         patch("urllib.request.urlopen", fake):
        skill.execute("GET_WEATHER", {"city": ""})

    assert _url_consultada(fake).endswith("wttr.in/?format=3")


def test_un_fallo_de_red_no_revienta_ni_inventa_el_clima(skill):
    """Nunca un dato inventado: si la consulta falla, se dice que no se pudo."""
    with patch("config_manager.get_weather_city", return_value="Medellín"), \
         patch("urllib.request.urlopen", side_effect=OSError("sin red")):
        respuesta = skill.execute("GET_WEATHER", {"city": ""})

    assert "no he podido" in respuesta.lower()
