"""
weather_tool.py

Fetches today's weather forecast using IP-based geolocation + Open-Meteo API.
No API keys required.
"""

import requests

# WMO Weather interpretation code → human-readable string
WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Icy fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Rain showers",
    82: "Heavy rain showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


LOCATION = {
    "latitude": 37.7762,
    "longitude": -122.4338,
    "city": "San Francisco",
    "region": "California",
}


def _get_forecast(latitude: float, longitude: float) -> dict:
    """Fetch today's forecast from Open-Meteo (free, no key)."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current_weather": True,
        "daily": ",".join([
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "weathercode",
        ]),
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
        "forecast_days": 1,
    }
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast", params=params, timeout=10
    )
    resp.raise_for_status()
    return resp.json()


def fetch_weather() -> dict:
    """
    Main entry point. Returns a structured weather summary dict:
      city, region, current_temp_f, high_f, low_f, precip_pct, conditions
    """
    loc = LOCATION
    raw = _get_forecast(loc["latitude"], loc["longitude"])

    current = raw["current_weather"]
    daily = raw["daily"]

    code = daily["weathercode"][0]

    return {
        "city": loc["city"],
        "region": loc["region"],
        "current_temp_f": round(current["temperature"]),
        "high_f": round(daily["temperature_2m_max"][0]),
        "low_f": round(daily["temperature_2m_min"][0]),
        "precip_pct": daily["precipitation_probability_max"][0],
        "conditions": WMO_CODES.get(code, f"Conditions (code {code})"),
    }


def format_weather(w: dict) -> str:
    """Format weather dict into a plain-text block for the Claude prompt."""
    return (
        f"Location: {w['city']}, {w['region']}\n"
        f"Current: {w['current_temp_f']}°F — {w['conditions']}\n"
        f"High: {w['high_f']}°F  |  Low: {w['low_f']}°F\n"
        f"Precipitation chance: {w['precip_pct']}%"
    )
