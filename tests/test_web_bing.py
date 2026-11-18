import json

from app.config import Settings
from app.web_tools import make_web_search_tool


def test_bing_rss_fallback_maps_results(monkeypatch) -> None:
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>杭州天气预报</title>
          <link>https://weather.example.com/hangzhou</link>
          <description>今天晴，最高 14 度。</description>
          <pubDate>Wed, 18 Nov 2026 06:35:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """

    class FakeResponse:
        content = rss.encode("utf-8")

        def raise_for_status(self) -> None:
            return None

    def fake_get(*args, **kwargs):
        assert kwargs["params"]["format"] == "rss"
        return FakeResponse()

    monkeypatch.setattr("app.web_tools.httpx.get", fake_get)
    settings = Settings(
        _env_file=None,
        demo_mode=True,
        web_search_provider="bing",
    )
    tool = make_web_search_tool(settings)
    payload = json.loads(tool.invoke({"query": "杭州天气"}))

    assert payload["provider"] == "bing"
    assert payload["results"][0]["url"] == "https://weather.example.com/hangzhou"
    assert "14" in payload["results"][0]["content"]
