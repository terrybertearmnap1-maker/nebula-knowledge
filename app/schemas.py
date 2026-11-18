"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
TEAM_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    team_id: str = Field(default="default", pattern=TEAM_ID_PATTERN)
    session_id: str | None = Field(default=None, pattern=SESSION_ID_PATTERN)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class ToolCallInfo(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: str = ""


class Citation(BaseModel):
    source_type: Literal["document", "web", "weather"] = "document"
    document_id: str = ""
    document: str = ""
    page: int | None = None
    chunk_id: str = ""
    snippet: str = ""
    score: float = 0.0
    url: str | None = None
    title: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    team_id: str
    answer: str
    tool_calls: list[ToolCallInfo] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    demo_mode: bool
    elapsed_ms: int


class HistoryToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[HistoryToolCall] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class HistoryResponse(BaseModel):
    session_id: str
    team_id: str
    messages: list[HistoryMessage] = Field(default_factory=list)
    demo_mode: bool


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    app: str
    version: str
    model: str
    demo_mode: bool
    web_search: bool = False


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("name must not be blank")
        return value


class TeamResponse(BaseModel):
    id: str
    name: str
    document_count: int = 0
    created_at: str


class DocumentResponse(BaseModel):
    id: str
    team_id: str
    filename: str
    content_type: str
    size_bytes: int
    page_count: int | None = None
    chunk_count: int
    created_at: str
    download_url: str


class DocumentListResponse(BaseModel):
    team_id: str
    documents: list[DocumentResponse] = Field(default_factory=list)


class TeamStatsResponse(BaseModel):
    team_id: str
    documents: int
    chunks: int
