import json

from langchain_core.messages import HumanMessage

from app.citations import citations_from_weather_result
from app.config import Settings
from app.llm import DemoChatModel
from app.weather_tools import make_weather_tool


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_weather_tool_returns_current_and_forecast(monkeypatch) -> None:
    def fake_get(url, params, timeout):
        if "geocoding" in url:
            assert params["name"] == "深圳"
            return FakeResponse(
                {
                    "results": [
                        {
                            "name": "深圳",
                            "admin1": "广东",
                            "country": "中国",
                            "latitude": 22.5,
                            "longitude": 114.0,
                        }
                    ]
                }
            )
        return FakeResponse(
            {
                "timezone": "Asia/Shanghai",
                "current": {
                    "time": "2026-11-18T17:45",
                    "temperature_2m": 21.9,
                    "relative_humidity_2m": 67,
                    "apparent_temperature": 21.2,
                    "weather_code": 0,
                    "wind_speed_10m": 17.4,
                },
                "daily": {
                    "time": ["2026-11-18", "2026-11-19", "2026-11-20"],
                    "weather_code": [53, 3, 51],
                    "temperature_2m_max": [27.9, 21.8, 17.1],
                    "temperature_2m_min": [17.6, 15.4, 12.9],
                    "precipitation_probability_max": [90, 8, 29],
                },
            }
        )

    monkeypatch.setattr("app.weather_tools.httpx.get", fake_get)
    settings = Settings(_env_file=None, demo_mode=True)
    tool = make_weather_tool(settings)
    payload = json.loads(tool.invoke({"city": "深圳"}))

    assert payload["location"] == "深圳 · 广东 · 中国"
    assert payload["current"]["temperature_c"] == 21.9
    assert payload["current"]["weather"] == "晴"
    assert payload["daily"][0]["max_c"] == 27.9

    citations = citations_from_weather_result(tool.invoke({"city": "深圳"}))
    assert len(citations) == 1
    assert citations[0].source_type == "weather"
    assert "21.9" in citations[0].snippet
    assert citations[0].url == "https://open-meteo.com/"


def test_demo_model_routes_weather_to_city_tool() -> None:
    model = DemoChatModel()
    response = model.invoke([HumanMessage(content="今天深圳天气怎么样？")])

    assert response.tool_calls[0]["name"] == "get_weather"
    assert response.tool_calls[0]["args"] == {"city": "深圳"}
