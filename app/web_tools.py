"""Web search tool with Tavily and keyless DuckDuckGo fallback."""

from __future__ import annotations

import html
import importlib.util
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import httpx
from langchain_core.tools import BaseTool, tool

from app.config import Settings

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def _clean(text: Any, limit: int = 1000) -> str:
    value = html.unescape(_TAG_RE.sub(" ", str(text or "")))
    value = _SPACE_RE.sub(" ", value).strip()
    return value[:limit]


def _ddgs_installed() -> bool:
    return importlib.util.find_spec("ddgs") is not None


def _providers(settings: Settings) -> list[str]:
    provider = settings.web_search_provider
    if provider == "disabled":
        return []
    if provider == "tavily":
        return ["tavily"] if settings.tavily_key else []
    if provider == "bing":
        return ["bing"]
    if provider == "ddgs":
        return ["ddgs"] if _ddgs_installed() else []

    # auto: Tavily when configured, then Bing RSS, then DuckDuckGo.
    providers: list[str] = []
    if settings.tavily_key:
        providers.append("tavily")
    providers.append("bing")
    if _ddgs_installed():
        providers.append("ddgs")
    return providers


def web_search_available(settings: Settings) -> bool:
    return bool(_providers(settings))


def _tavily_search(settings: Settings, query: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        response = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.tavily_key,
                "query": query,
                "max_results": settings.web_search_max_results,
                "search_depth": "basic",
                "include_answer": False,
            },
            timeout=settings.web_search_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        return [], f"Tavily HTTP {exc.response.status_code}"
    except Exception as exc:
        return [], f"Tavily 请求失败：{type(exc).__name__}"

    results: list[dict[str, Any]] = []
    for item in payload.get("results", [])[: settings.web_search_max_results]:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        results.append(
            {
                "title": _clean(item.get("title") or url, 200),
                "url": url,
                "content": _clean(item.get("content") or "", 1000),
                "published_at": item.get("published_date"),
                "score": float(item.get("score") or 0.0),
            }
        )
    return results, None


def _bing_search(settings: Settings, query: str) -> tuple[list[dict[str, Any]], str | None]:
    """Use Bing's public RSS result feed as a keyless local fallback."""
    try:
        response = httpx.get(
            "https://www.bing.com/search",
            params={
                "q": query,
                "format": "rss",
                "setlang": "zh-hans",
                "cc": "cn",
            },
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
                )
            },
            timeout=settings.web_search_timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except httpx.HTTPStatusError as exc:
        return [], f"Bing HTTP {exc.response.status_code}"
    except ET.ParseError:
        return [], "Bing 返回了无法解析的结果"
    except Exception as exc:
        return [], f"Bing 请求失败：{type(exc).__name__}"

    results: list[dict[str, Any]] = []
    for item in root.findall(".//item")[: settings.web_search_max_results]:
        url = str(item.findtext("link") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        results.append(
            {
                "title": _clean(item.findtext("title") or url, 200),
                "url": url,
                "content": _clean(item.findtext("description") or "", 1000),
                "published_at": item.findtext("pubDate"),
                "score": 0.0,
            }
        )
    return results, None


def _ddgs_search(settings: Settings, query: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        from ddgs import DDGS
    except ImportError:
        return [], "未安装 ddgs，无法使用 DuckDuckGo 搜索"

    try:
        with DDGS(timeout=settings.web_search_timeout_seconds) as ddgs:
            raw_results = ddgs.text(
                query,
                max_results=settings.web_search_max_results,
                region="cn-zh",
            )
    except Exception as exc:
        return [], f"DuckDuckGo 请求失败：{type(exc).__name__}"

    results: list[dict[str, Any]] = []
    for item in raw_results or []:
        url = str(item.get("href") or item.get("url") or item.get("link") or "").strip()
        if not url:
            continue
        results.append(
            {
                "title": _clean(item.get("title") or url, 200),
                "url": url,
                "content": _clean(item.get("body") or item.get("snippet") or "", 1000),
                "published_at": item.get("published") or item.get("published_at"),
                "score": float(item.get("score") or 0.0),
            }
        )
    return results, None


def make_web_search_tool(settings: Settings) -> BaseTool:
    """Create a web search tool for the current runtime configuration."""

    @tool("web_search")
    def web_search(query: str) -> str:
        """Search the public web for current information.

        Use this for news, weather, prices, product releases, recent events, or
        anything that may have changed after the model's training cutoff. Do not
        use it for internal policies or team documents; use search_knowledge for
        those. Always cite the returned URL in the final answer.

        Args:
            query: A focused web search query.
        """
        providers = _providers(settings)
        if not providers:
            return json.dumps(
                {
                    "query": query,
                    "results": [],
                    "message": "联网搜索未启用。请配置 TAVILY_API_KEY 或启用 ddgs。",
                },
                ensure_ascii=False,
            )

        errors: list[str] = []
        for provider in providers:
            if provider == "tavily":
                results, error = _tavily_search(settings, query)
            elif provider == "bing":
                results, error = _bing_search(settings, query)
            else:
                results, error = _ddgs_search(settings, query)

            if results:
                return json.dumps(
                    {
                        "query": query,
                        "provider": provider,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "results": results,
                    },
                    ensure_ascii=False,
                )
            if error:
                errors.append(error)

        return json.dumps(
            {
                "query": query,
                "provider": providers[-1],
                "results": [],
                "message": "联网搜索没有返回结果。",
                "errors": errors,
            },
            ensure_ascii=False,
        )

    return web_search
