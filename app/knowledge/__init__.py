"""Team-scoped document knowledge base."""

from app.knowledge.errors import (
    DocumentNotFound,
    DocumentParseError,
    DuplicateDocument,
    KnowledgeBaseError,
    TeamNotFound,
    UnsupportedFileType,
)
from app.knowledge.store import KnowledgeBase

__all__ = [
    "DocumentNotFound",
    "DocumentParseError",
    "DuplicateDocument",
    "KnowledgeBase",
    "KnowledgeBaseError",
    "TeamNotFound",
    "UnsupportedFileType",
]
