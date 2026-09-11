from __future__ import annotations

import json
import re
from typing import Any

from .repository import SQLiteRepository


class MemoryRetriever:
    """Local lexical retriever for memory items; no embeddings or network."""

    def __init__(self, repository: SQLiteRepository):
        self.repository = repository

    def search(self, query: str, memory_types: list[str] | None = None, limit: int = 5) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        if not query:
            return []
        types = list(dict.fromkeys(memory_types or ["short_term", "episodic", "semantic", "rule", "correction"]))
        terms = [term for term in re.split(r"\s+", query.strip()) if term]
        results = []
        for memory_type in types:
            for item in self.repository.search_memory(memory_type, limit=10000):
                haystack = json.dumps(item["content"], ensure_ascii=False)
                score = sum(haystack.count(term) for term in terms)
                if score:
                    results.append({**item, "relevance": score})
        results.sort(key=lambda item: (-item["relevance"], item["created_at"]))
        return results[:limit]
