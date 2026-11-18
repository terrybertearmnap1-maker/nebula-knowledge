"""Keyless weather tool backed by Open-Meteo."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
from langchain_core.tools import BaseTool, tool

from app.config import Settings

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_WEATHER_CODES = {
    0: "晴",
    1: "大部晴朗",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "强毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


def _weather_text(code: Any) -> str:
    try:
        return _WEATHER_CODES.get(int(code), f"天气代码 {code}")
    except (TypeError, ValueError):
        return "未知天气"


def _location_label(item: dict[str, Any]) -> str:
    parts = [str(item.get("name") or "").strip()]
    for key in ("admin1", "country"):
        value = str(item.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)
    return " · ".join(part for part in parts if part)


def _weather_error(message: str) -> str:
    return json.dumps(
        {
            "error": message,
            "results": [],
            "message": "无法获取天气数据，请换一个城市名或稍后重试。",
        },
        ensure_ascii=False,
    )


def make_weather_tool(settings: Settings) -> BaseTool:
    @tool("get_weather")
    def get_weather(city: str) -> str:
        """Get current weather and a 3-day forecast for a city.

        Use this for weather, temperature, rain, wind, or forecast questions.
        Pass a city name such as "深圳" or "杭州"; do not pass a full sentence.
        The result includes current conditions, daily forecast, and an
        Open-Meteo source URL that should be cited in the answer.

        Args:
            city: City name, e.g. "深圳" or "Hangzhou".
        """
        city = city.strip()
        if not city:
            return _weather_error("城市名为空")

        try:
            geo_response = httpx.get(
                GEOCODING_URL,
                params={"name": city, "count": 1, "language": "zh", "format": "json"},
                timeout=settings.web_search_timeout_seconds,
            )
            geo_response.raise_for_status()
            geo_payload = geo_response.json()
            matches = geo_payload.get("results") or []
            if not matches:
                return _weather_error(f"找不到城市：{city}")
            location = matches[0]

            forecast_response = httpx.get(
                FORECAST_URL,
                params={
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                    "current": (
                        "temperature_2m,relative_humidity_2m,apparent_temperature,"
                        "weather_code,wind_speed_10m"
                    ),
                    "daily": (
                        "weather_code,temperature_2m_max,temperature_2m_min,"
                        "precipitation_probability_max"
                    ),
                    "timezone": "auto",
                    "forecast_days": 3,
                },
                timeout=settings.web_search_timeout_seconds,
            )
            forecast_response.raise_for_status()
            forecast = forecast_response.json()
        except httpx.HTTPStatusError as exc:
            return _weather_error(f"Open-Meteo HTTP {exc.response.status_code}")
        except Exception as exc:
            return _weather_error(f"Open-Meteo 请求失败：{type(exc).__name__}")

        current_raw = forecast.get("current") or {}
        current = {
            "time": current_raw.get("time"),
            "temperature_c": current_raw.get("temperature_2m"),
            "apparent_temperature_c": current_raw.get("apparent_temperature"),
            "humidity_percent": current_raw.get("relative_humidity_2m"),
            "wind_kmh": current_raw.get("wind_speed_10m"),
            "weather": _weather_text(current_raw.get("weather_code")),
        }

        daily_raw = forecast.get("daily") or {}
        dates = daily_raw.get("time") or []
        max_values = daily_raw.get("temperature_2m_max") or []
        min_values = daily_raw.get("temperature_2m_min") or []
        rain_values = daily_raw.get("precipitation_probability_max") or []
        weather_values = daily_raw.get("weather_code") or []

        def at(values: list[Any], index: int) -> Any:
            return values[index] if index < len(values) else None

        daily: list[dict[str, Any]] = []
        for index, date in enumerate(dates[:3]):
            daily.append(
                {
                    "date": date,
                    "weather": _weather_text(at(weather_values, index)),
                    "max_c": at(max_values, index),
                    "min_c": at(min_values, index),
                    "precipitation_probability_percent": at(rain_values, index),
                }
            )

        return json.dumps(
            {
                "location": _location_label(location),
                "timezone": forecast.get("timezone"),
                "current": current,
                "daily": daily,
                "source": "Open-Meteo",
                "url": "https://open-meteo.com/",
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
        )

    return get_weather
