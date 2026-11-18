"""LangChain tools that expose the team knowledge base to the agent."""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, tool

from app.knowledge import KnowledgeBase


def make_search_tool(kb: KnowledgeBase, team_id: str) -> BaseTool:
    """Create a search tool whose scope is fixed to one team."""

    @tool("search_knowledge")
    def search_knowledge(query: str) -> str:
        """Search this team's uploaded documents for relevant passages.

        Use this tool for every question that might be answered by internal
        policies, product documentation, meeting notes, or uploaded files.
        Never answer such questions from memory. The result includes document
        names, page numbers, chunk ids, and source text for citations.

        Args:
            query: A focused search query, preferably keywords from the question.
        """
        hits = kb.search(team_id, query, top_k=kb.settings.retrieval_top_k)
        if not hits:
            return json.dumps(
                {
                    "query": query,
                    "count": 0,
                    "results": [],
                    "message": "知识库中没有找到相关内容，请明确告诉用户没有找到依据。",
                },
                ensure_ascii=False,
            )

        results = []
        for hit in hits:
            results.append(
                {
                    "document_id": hit.document_id,
                    "document": hit.filename,
                    "page": hit.page,
                    "chunk_id": hit.chunk_id,
                    "heading": hit.heading,
                    "score": hit.score,
                    "snippet": hit.content[:320],
                    "content": hit.content,
                }
            )
        return json.dumps(
            {"query": query, "count": len(results), "results": results},
            ensure_ascii=False,
        )

    return search_knowledge
