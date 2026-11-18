import json

from app.citations import citations_from_web_result, filter_citations_for_answer
from app.config import Settings
from app.schemas import Citation
from app.web_tools import make_web_search_tool, web_search_available


def test_web_search_can_be_disabled() -> None:
    settings = Settings(
        _env_file=None,
        demo_mode=True,
        web_search_provider="disabled",
    )
    assert web_search_available(settings) is False

    tool = make_web_search_tool(settings)
    payload = json.loads(tool.invoke({"query": "今天天气"}))
    assert payload["results"] == []
    assert "未启用" in payload["message"]


def test_tavily_results_are_mapped_and_citable(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "results": [
                    {
                        "title": "Example News",
                        "url": "https://example.com/news",
                        "content": "A recent update about the product.",
                        "published_date": "2026-11-18",
                        "score": 0.93,
                    }
                ]
            }

    def fake_post(*args, **kwargs):
        assert kwargs["json"]["query"] == "product update"
        assert kwargs["json"]["api_key"] == "test-tavily-key"
        return FakeResponse()

    monkeypatch.setattr("app.web_tools.httpx.post", fake_post)
    settings = Settings(
        _env_file=None,
        demo_mode=True,
        web_search_provider="tavily",
        tavily_api_key="test-tavily-key",
    )
    assert web_search_available(settings) is True

    tool = make_web_search_tool(settings)
    payload = json.loads(tool.invoke({"query": "product update"}))
    assert payload["provider"] == "tavily"
    assert payload["results"][0]["url"] == "https://example.com/news"

    citations = citations_from_web_result(tool.invoke({"query": "product update"}))
    assert len(citations) == 1
    assert citations[0].source_type == "web"
    assert citations[0].url == "https://example.com/news"
    assert citations[0].title == "Example News"
    assert "recent update" in citations[0].snippet


def test_web_citations_follow_urls_used_in_answer() -> None:
    citations = [
        Citation(source_type="web", document="A", title="A", url="https://a.example/page"),
        Citation(source_type="web", document="B", title="B", url="https://b.example/page"),
    ]
    filtered = filter_citations_for_answer(
        citations,
        "来源：[A](https://a.example/page)",
    )
    assert [item.title for item in filtered] == ["A"]
