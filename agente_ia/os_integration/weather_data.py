"""
os_integration/weather_data.py
Clima estructurado (REQ-008/CA-10) para consumo de la GUI — temperatura, condición,
ciudad, hora y fecha como campos separados, en vez de la frase de una sola línea que
devuelve `skills/weather_skill.py` (formato `format=3`, sin tocar).

Usa `wttr.in/{city}?format=j1` (JSON) — mismo servicio, mismo timeout (5s) y mismo
patrón de manejo de errores que la skill conversacional existente. `time_str`/`date_str`
se calculan localmente con `datetime.now()`, no dependen de que wttr.in los incluya.
"""

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_WTTR_TIMEOUT_SECONDS = 5


@dataclass
class WeatherData:
    temp_c: float
    condition: str
    city: str
    time_str: str
    date_str: str


def get_weather_structured(city: str = "") -> Optional[WeatherData]:
    """Consulta wttr.in en formato JSON y retorna un `WeatherData`, o `None` si falla.

    Nunca inventa datos: si la petición de red falla o el JSON no tiene la forma
    esperada, retorna `None` explícitamente (el widget consumidor debe mostrar un
    estado "no disponible", nunca un valor de ejemplo fijo).
    """
    city_path = urllib.parse.quote_plus(city) if city else ""
    url = f"https://wttr.in/{city_path}?format=j1&lang=es"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_WTTR_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))

        current = data["current_condition"][0]
        temp_c = float(current["temp_C"])
        weather_desc = current.get("lang_es") or current.get("weatherDesc") or []
        condition = weather_desc[0]["value"] if weather_desc else "Desconocido"

        area = (data.get("nearest_area") or [{}])[0]
        area_name = area.get("areaName") or []
        region = area.get("region") or []
        country = area.get("country") or []
        # .get("value", "") en vez de ["value"]: un área presente pero sin la clave
        # "value" (forma inesperada de wttr.in) no debe hacer que toda la respuesta
        # falle — degrada a "Ubicación desconocida" en vez de reventar con KeyError.
        city_name = (area_name[0].get("value", "") if area_name else "") or city or "Ubicación desconocida"
        region_name = region[0].get("value", "") if region else ""
        country_name = country[0].get("value", "") if country else ""
        location = ", ".join(p for p in (city_name, region_name or country_name) if p)

        now = datetime.now()
        return WeatherData(
            temp_c=temp_c,
            condition=condition,
            city=location or city_name,
            time_str=now.strftime("%H:%M"),
            date_str=now.strftime("%d %b, %Y"),
        )
    except Exception as e:
        logger.error(f"Error obteniendo clima estructurado para '{city}': {e}")
        return None
