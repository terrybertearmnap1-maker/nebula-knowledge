"""Internal data structures for parsing, storage, and retrieval."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Section:
    text: str
    page: int | None = None
    heading: str | None = None


@dataclass(frozen=True)
class ParsedDocument:
    sections: tuple[Section, ...]
    page_count: int | None = None


@dataclass(frozen=True)
class ChunkDraft:
    index: int
    content: str
    page: int | None
    heading: str | None


@dataclass(frozen=True)
class TeamRecord:
    id: str
    name: str
    created_at: str
    document_count: int = 0


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    team_id: str
    filename: str
    content_type: str
    size_bytes: int
    page_count: int | None
    chunk_count: int
    created_at: str
    stored_path: str


@dataclass(frozen=True)
class StoredChunk:
    id: str
    document_id: str
    filename: str
    chunk_index: int
    page: int | None
    heading: str | None
    content: str
    tokens: dict[str, int]
    token_count: int


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    document_id: str
    filename: str
    chunk_index: int
    page: int | None
    heading: str | None
    content: str
    score: float
