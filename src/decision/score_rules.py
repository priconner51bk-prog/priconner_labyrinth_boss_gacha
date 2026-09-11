from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ScoreRule:
    rule_id: str
    label: str
    weight: float
    matches: Callable[[dict[str, Any]], bool]


class ScoreRuleSet:
    """Produce a deterministic score with an auditable contribution breakdown."""

    def __init__(self, rules: list[ScoreRule]):
        if not rules or any(rule.weight < 0 for rule in rules):
            raise ValueError("score rules must be non-empty and non-negative")
        self.rules = rules
        total = sum(rule.weight for rule in rules)
        if total <= 0:
            raise ValueError("score rule weights must have a positive total")
        self._total_weight = total

    def evaluate(self, context: dict[str, Any], decision: str = "score_selected") -> dict[str, Any] | None:
        contributions = []
        for rule in self.rules:
            if rule.matches(context):
                contributions.append({"rule_id": rule.rule_id, "label": rule.label, "weight": rule.weight})
        if not contributions:
            return None
        score = sum(item["weight"] for item in contributions) / self._total_weight
        return {"decision": decision, "confidence": round(score, 4), "score_breakdown": contributions, "reason": [item["label"] for item in contributions]}
