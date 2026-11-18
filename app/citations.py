"""Turn knowledge/web tool JSON into API citations."""

from __future__ import annotations

import json
from urllib.parse import urlparse

from app.schemas import Citation, ToolCallInfo


def citations_from_tool_result(raw: str) -> list[Citation]:
    """Citations from the search_knowledge tool."""
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []

    citations: list[Citation] = []
    for item in payload.get("results", []):
        if not isinstance(item, dict):
            continue
        document_id = str(item.get("document_id") or "")
        chunk_id = str(item.get("chunk_id") or "")
        if not document_id or not chunk_id:
            continue
        page = item.get("page")
        citations.append(
            Citation(
                source_type="document",
                document_id=document_id,
                document=str(item.get("document") or "文档"),
                page=int(page) if isinstance(page, int) else None,
                chunk_id=chunk_id,
                snippet=str(item.get("snippet") or ""),
                score=float(item.get("score") or 0.0),
            )
        )
    return citations


def citations_from_web_result(raw: str) -> list[Citation]:
    """Citations from the web_search tool."""
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []

    citations: list[Citation] = []
    for item in payload.get("results", []):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        title = str(item.get("title") or url)
        citations.append(
            Citation(
                source_type="web",
                document=title,
                title=title,
                url=url,
                snippet=str(item.get("content") or "")[:320],
                score=float(item.get("score") or 0.0),
            )
        )
    return citations


def citations_from_weather_result(raw: str) -> list[Citation]:
    """Citations from the get_weather tool."""
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or not payload.get("location"):
        return []

    current = payload.get("current") or {}
    location = str(payload.get("location"))
    temperature = current.get("temperature_c")
    weather = current.get("weather")
    snippet = f"{location}：{weather or ''}，{temperature}°C" if temperature is not None else location
    return [
        Citation(
            source_type="weather",
            document=f"Open-Meteo · {location}",
            title=f"Open-Meteo · {location}",
            url=str(payload.get("url") or "https://open-meteo.com/"),
            snippet=snippet,
            score=1.0,
        )
    ]


def _citation_key(citation: Citation) -> str:
    if citation.source_type in {"web", "weather"}:
        return f"{citation.source_type}:{citation.url}"
    return f"document:{citation.chunk_id}"


def _is_mentioned(citation: Citation, answer: str) -> bool:
    if not citation.url:
        return False
    if citation.url.rstrip("/") in answer:
        return True
    host = urlparse(citation.url).netloc
    if host and host in answer:
        return True
    return bool(citation.title and citation.title in answer)


def filter_citations_for_answer(citations: list[Citation], answer: str) -> list[Citation]:
    """Keep document/weather sources and only web URLs actually used in the answer."""
    documents = [c for c in citations if c.source_type == "document"]
    weather = [c for c in citations if c.source_type == "weather"][:1]
    web_sources = [c for c in citations if c.source_type == "web"]
    if answer and web_sources:
        web_sources = [c for c in web_sources if _is_mentioned(c, answer)]
    return [*documents, *weather, *web_sources[:3]]


def citations_from_tool_calls(
    calls: list[ToolCallInfo],
    answer: str | None = None,
) -> list[Citation]:
    merged: list[Citation] = []
    seen: set[str] = set()
    for call in calls:
        if call.name == "search_knowledge":
            candidates = citations_from_tool_result(call.result)
        elif call.name == "web_search":
            candidates = citations_from_web_result(call.result)
        elif call.name == "get_weather":
            candidates = citations_from_weather_result(call.result)
        else:
            continue

        for citation in candidates:
            key = _citation_key(citation)
            if key in seen:
                continue
            seen.add(key)
            merged.append(citation)
            if len(merged) >= 8:
                break

    return filter_citations_for_answer(merged, answer or "")
