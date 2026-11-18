"""Lightweight Chinese/English lexical retrieval (BM25).

The MVP intentionally avoids a heavyweight embedding stack: Chinese text is
indexed as character bigrams plus Latin words, then ranked with BM25. This
works offline, keeps uploads fast, and provides deterministic tests. A
production deployment can swap this module for pgvector + a multilingual
embedding model without changing the tool/API contract.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

from app.knowledge.models import SearchHit, StoredChunk

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
_QUERY_STOPWORDS = {
    "什么",
    "怎么",
    "这个",
    "那个",
    "一下",
    "可以",
    "请问",
    "告诉",
    "我们",
    "是否",
    "如何",
    "以及",
    "相关",
    "帮我",
    "看看",
    "介绍",
    "文档",
    "知识",
    "资料",
    "内容",
    "the",
    "what",
    "how",
    "please",
    "tell",
    "about",
}


def tokenize(text: str) -> list[str]:
    """Tokenize Latin words and Chinese bigrams (single chars for short runs)."""
    normalized = unicodedata.normalize("NFKC", text or "").lower()
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(normalized):
        value = match.group(0)
        if value.isascii():
            tokens.append(value)
        elif len(value) == 1:
            tokens.append(value)
        else:
            tokens.extend(value[i : i + 2] for i in range(len(value) - 1))
    return tokens


def query_tokens(text: str) -> list[str]:
    return [token for token in tokenize(text) if token not in _QUERY_STOPWORDS]


def bm25_search(chunks: list[StoredChunk], query: str, top_k: int = 5) -> list[SearchHit]:
    tokens = query_tokens(query)
    if not tokens or not chunks:
        return []

    query_counts = Counter(tokens)
    document_count = len(chunks)
    document_frequency: Counter[str] = Counter()
    for chunk in chunks:
        document_frequency.update(chunk.tokens.keys())

    average_length = sum(max(chunk.token_count, 1) for chunk in chunks) / document_count
    k1, b = 1.5, 0.75
    compact_query = re.sub(r"\s+", "", unicodedata.normalize("NFKC", query).lower())

    scored: list[tuple[float, StoredChunk]] = []
    for chunk in chunks:
        length = max(chunk.token_count, 1)
        score = 0.0
        for token, query_count in query_counts.items():
            frequency = chunk.tokens.get(token, 0)
            if not frequency:
                continue
            df = document_frequency.get(token, 0)
            idf = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (1 - b + b * length / average_length)
            score += query_count * idf * (frequency * (k1 + 1)) / denominator

        if len(compact_query) >= 2:
            compact_content = re.sub(r"\s+", "", chunk.content.lower())
            if compact_query in compact_content:
                score += 3.0

        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    results: list[SearchHit] = []
    for score, chunk in scored[: max(1, top_k)]:
        results.append(
            SearchHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                filename=chunk.filename,
                chunk_index=chunk.chunk_index,
                page=chunk.page,
                heading=chunk.heading,
                content=chunk.content,
                score=round(score, 4),
            )
        )
    return results
