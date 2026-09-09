"""Weather providers: Open-Meteo, OpenWeatherMap, WeatherAPI."""

from __future__ import annotations

from typing import Any

from pixoo.plugins.base import DataSourcePlugin
from pixoo.utils.network_utils import clamp_timeout, http_client, with_retries
from pixoo.utils.secrets import resolve_secrets


class WeatherPlugin(DataSourcePlugin):
    name = "weather"
    description = "Weather (Open-Meteo / OpenWeatherMap / WeatherAPI)"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "provider": {
                "type": "string",
                "label": "Provider",
                "enum": ["open-meteo", "openweathermap", "weatherapi"],
                "default": "open-meteo",
            },
            "latitude": {"type": "number", "label": "Latitude", "default": 48.85},
            "longitude": {"type": "number", "label": "Longitude", "default": 2.35},
            "field": {
                "type": "string",
                "label": "Field",
                "enum": ["temperature", "condition", "humidity", "wind_speed", "all"],
                "default": "temperature",
            },
            "api_key": {"type": "string", "label": "API key (${ENV:...})", "default": ""},
            "cache_ttl": {"type": "integer", "label": "Cache TTL (s)", "default": 300},
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        try:
            float(config.get("latitude", 0))
            float(config.get("longitude", 0))
        except (TypeError, ValueError):
            return False
        return str(config.get("provider") or "open-meteo") in (
            "open-meteo",
            "openweathermap",
            "weatherapi",
        )

    def fetch_data(self, config: dict[str, Any]) -> Any:
        cfg = resolve_secrets(dict(config))
        provider = str(cfg.get("provider") or "open-meteo")
        lat = float(cfg.get("latitude") or 48.85)
        lon = float(cfg.get("longitude") or 2.35)
        field = str(cfg.get("field") or "temperature")
        timeout = clamp_timeout(cfg.get("timeout"), 8)

        if provider == "openweathermap":
            data = self._openweathermap(lat, lon, str(cfg.get("api_key") or ""), timeout)
        elif provider == "weatherapi":
            data = self._weatherapi(lat, lon, str(cfg.get("api_key") or ""), timeout)
        else:
            data = self._open_meteo(lat, lon, timeout)

        if field == "all":
            return data
        return data.get(field)

    def _open_meteo(self, lat: float, lon: float, timeout: float) -> dict[str, Any]:
        url = "https://api.open-meteo.com/v1/forecast"

        def _do() -> dict[str, Any]:
            with http_client(timeout=timeout) as client:
                r = client.get(
                    url,
                    params={
                        "latitude": lat,
                        "longitude": lon,
                        "current_weather": True,
                        "hourly": "relativehumidity_2m",
                    },
                )
                r.raise_for_status()
                return r.json()

        raw = with_retries(_do, retries=2)
        cw = raw.get("current_weather") or {}
        humidity = None
        hourly = raw.get("hourly") or {}
        if hourly.get("relativehumidity_2m"):
            humidity = hourly["relativehumidity_2m"][0]
        return {
            "temperature": cw.get("temperature"),
            "condition": cw.get("weathercode"),
            "weathercode": cw.get("weathercode"),
            "wind_speed": cw.get("windspeed"),
            "humidity": humidity,
        }

    def _openweathermap(self, lat: float, lon: float, api_key: str, timeout: float) -> dict[str, Any]:
        if not api_key:
            raise ValueError("OpenWeatherMap requires api_key / ${ENV:...}")

        def _do() -> dict[str, Any]:
            with http_client(timeout=timeout) as client:
                r = client.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={"lat": lat, "lon": lon, "appid": api_key, "units": "metric"},
                )
                r.raise_for_status()
                return r.json()

        raw = with_retries(_do, retries=2)
        weather = (raw.get("weather") or [{}])[0]
        main = raw.get("main") or {}
        wind = raw.get("wind") or {}
        return {
            "temperature": main.get("temp"),
            "condition": weather.get("main"),
            "humidity": main.get("humidity"),
            "wind_speed": wind.get("speed"),
        }

    def _weatherapi(self, lat: float, lon: float, api_key: str, timeout: float) -> dict[str, Any]:
        if not api_key:
            raise ValueError("WeatherAPI requires api_key / ${ENV:...}")

        def _do() -> dict[str, Any]:
            with http_client(timeout=timeout) as client:
                r = client.get(
                    "https://api.weatherapi.com/v1/current.json",
                    params={"key": api_key, "q": f"{lat},{lon}"},
                )
                r.raise_for_status()
                return r.json()

        raw = with_retries(_do, retries=2)
        cur = raw.get("current") or {}
        cond = cur.get("condition") or {}
        return {
            "temperature": cur.get("temp_c"),
            "condition": cond.get("text"),
            "humidity": cur.get("humidity"),
            "wind_speed": cur.get("wind_kph"),
        }


PLUGIN = WeatherPlugin()
