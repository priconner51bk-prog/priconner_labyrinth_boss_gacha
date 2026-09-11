from __future__ import annotations

from typing import Any, Callable


def evaluate_retrieval(cases: list[dict[str, Any]], retrieve: Callable[[str, int], list[dict[str, Any]]], k: int = 5) -> dict[str, Any]:
    """Calculate deterministic retrieval metrics for local RAG fixtures."""
    if k < 1:
        raise ValueError("k must be positive")
    rows = []
    for case in cases:
        expected = set(case.get("relevant_ids", []))
        results = retrieve(case["query"], k)
        ids = [result["id"] for result in results[:k]]
        hits = len(expected.intersection(ids))
        first_rank = next((index + 1 for index, item_id in enumerate(ids) if item_id in expected), None)
        rows.append({"id": case["id"], "query": case["query"], "precision_at_k": hits / k, "recall_at_k": hits / len(expected) if expected else 0.0, "reciprocal_rank": 1 / first_rank if first_rank else 0.0})
    total = len(rows)
    return {"k": k, "total": total, "precision_at_k": sum(row["precision_at_k"] for row in rows) / total if total else 0.0, "recall_at_k": sum(row["recall_at_k"] for row in rows) / total if total else 0.0, "mrr": sum(row["reciprocal_rank"] for row in rows) / total if total else 0.0, "rows": rows}
