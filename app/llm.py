"""Chat-model construction, including a deterministic offline demo model."""

from __future__ import annotations

import json
import re
from typing import Any, Sequence
from uuid import uuid4

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from app.config import Settings

_EXPRESSION_RE = re.compile(r"\(?\s*[-+]?\d[\d\s+\-*/().%]*")
_TIME_KEYWORDS = (
    "几点",
    "时间",
    "日期",
    "今天",
    "现在",
    "current time",
    "what time",
    "date",
)
_WEATHER_KEYWORDS = (
    "天气",
    "气温",
    "温度",
    "下雨",
    "降雨",
    "风力",
    "空气质量",
    "weather",
    "temperature",
)


def _message_text(message: BaseMessage) -> str:
    """Extract plain text from a string or LangChain content-block list."""
    content = message.content
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


def _extract_expression(text: str) -> str | None:
    """Find a likely arithmetic expression in a natural-language message."""
    for match in reversed(_EXPRESSION_RE.findall(text)):
        candidate = match.strip()
        if not any(operator in candidate for operator in "+-*/%"):
            continue
        if not any(char.isdigit() for char in candidate):
            continue
        # Reject fragments such as "2026-11-18" from a time question.
        if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", candidate):
            continue
        return candidate
    return None


def _extract_city(text: str) -> str:
    cleaned = re.sub(
        r"今天|明天|后天|现在|当前|今日|最近|本周|这周|请问|帮我|查一下|查询|看看|"
        r"怎么样|如何|天气|气温|温度|下雨|降雨|风力|空气质量|预报|多少|会|要|吗|呢|"
        r"\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日|[，,。？！?\s]",
        "",
        text,
    )
    return cleaned[:8] or "北京"


def _weather_answer(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return "天气工具返回了无法解析的结果。"

    if payload.get("error"):
        return f"没有查到天气：{payload['error']}"

    current = payload.get("current") or {}
    location = payload.get("location") or "该城市"
    daily = payload.get("daily") or []
    lines = [f"{location}当前天气：{current.get('weather', '未知')}，气温 {current.get('temperature_c')}°C。"]
    if daily:
        next_day = daily[0]
        lines.append(
            f"今天 {next_day.get('min_c')}～{next_day.get('max_c')}°C，"
            f"降水概率 {next_day.get('precipitation_probability_percent')}%。"
        )
    lines.append("来源：[Open-Meteo](https://open-meteo.com/)")
    return "\n".join(lines)


def _knowledge_answer(raw: str) -> str:
    """Turn a search_knowledge JSON payload into a readable demo answer."""
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return f"知识库检索返回了无法解析的结果：{raw[:200]}"

    results = payload.get("results", []) if isinstance(payload, dict) else []
    if not results:
        return "我在当前团队的知识库里没有找到相关依据，无法确认。可以先上传相关文档后再问我。"

    lines = ["根据团队知识库："]
    for item in results[:3]:
        if not isinstance(item, dict):
            continue
        content = " ".join(str(item.get("content") or "").split())
        if len(content) > 420:
            content = content[:420] + "…"
        source = str(item.get("document") or "文档")
        if item.get("page"):
            source = f"{source}，第 {item['page']} 页"
        lines.append(f"- {content}（来源：[{source}]）")
    lines.append("\n以上内容来自当前团队的知识库。")
    return "\n".join(lines)


class DemoChatModel(BaseChatModel):
    """A tiny offline model that exercises the real LangChain tool loop.

    It understands arithmetic, current time, and knowledge-base search. This
    keeps the project runnable without an API key while preserving the same
    agent graph, tool calling, checkpointing, and citation pipeline used with a
    hosted model.
    """

    model_name: str = "demo-agent"

    @property
    def _llm_type(self) -> str:
        return "demo-chat-model"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | BaseTool | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> "DemoChatModel":
        # The demo model has fixed intents and does not need tool schemas.
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = self._respond(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _respond(self, messages: list[BaseMessage]) -> AIMessage:
        if not messages:
            return AIMessage(content="你好，我是团队知识库演示助手。")

        last = messages[-1]

        if isinstance(last, ToolMessage):
            tool_name = last.name or "tool"
            result = _message_text(last)
            if tool_name == "calculator":
                return AIMessage(content=f"计算结果是 **{result}**。")
            if tool_name == "current_time":
                return AIMessage(content=f"现在是 {result}。")
            if tool_name == "search_knowledge":
                return AIMessage(content=_knowledge_answer(result))
            if tool_name == "get_weather":
                return AIMessage(content=_weather_answer(result))
            return AIMessage(content=f"工具 {tool_name} 返回：{result}")

        if not isinstance(last, HumanMessage):
            return AIMessage(content="我准备好了，请继续提问。")

        text = _message_text(last).strip()
        lowered = text.lower()

        expression = _extract_expression(text)
        if expression:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "calculator",
                        "args": {"expression": expression},
                        "id": f"call_{uuid4().hex[:12]}",
                        "type": "tool_call",
                    }
                ],
            )

        if any(keyword in lowered for keyword in _WEATHER_KEYWORDS):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_weather",
                        "args": {"city": _extract_city(text)},
                        "id": f"call_{uuid4().hex[:12]}",
                        "type": "tool_call",
                    }
                ],
            )

        if any(keyword in lowered for keyword in _TIME_KEYWORDS):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "current_time",
                        "args": {"timezone": "Asia/Shanghai"},
                        "id": f"call_{uuid4().hex[:12]}",
                        "type": "tool_call",
                    }
                ],
            )

        if any(greeting in text for greeting in ("你好", "hello", "hi", "嗨")):
            return AIMessage(
                content=(
                    "你好！我是运行在 LangChain + FastAPI 上的团队知识库助手。\n\n"
                    "你可以：\n"
                    "- 上传 PDF、DOCX、Markdown 或 TXT 文档\n"
                    "- 询问制度、产品文档、会议纪要里的内容\n"
                    "- 让我给出带文件名和页码的引用\n\n"
                    "没有配置 API Key 时我会使用离线演示模型，但检索和引用链路是真实的。"
                )
            )

        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_knowledge",
                    "args": {"query": text},
                    "id": f"call_{uuid4().hex[:12]}",
                    "type": "tool_call",
                }
            ],
        )


def build_chat_model(settings: Settings) -> BaseChatModel:
    """Create the configured chat model (or the offline demo model)."""
    if settings.is_demo:
        return DemoChatModel()

    if not settings.api_key:
        raise ValueError(
            "LLM_API_KEY is required when DEMO_MODE=false. "
            "Set the key or remove DEMO_MODE to use demo mode."
        )

    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.api_key,
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
    )
