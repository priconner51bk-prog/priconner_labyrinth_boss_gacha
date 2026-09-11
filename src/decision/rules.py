from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class HardRule:
    rule_id: str
    priority: int
    matches: Callable[[dict[str, Any]], bool]
    decision: str
    reason: str


class HardRuleRegistry:
    """Evaluate deterministic rules in priority order without side effects."""

    def __init__(self, rules: list[HardRule] | None = None):
        self._rules: list[HardRule] = []
        for rule in rules or []:
            self.register(rule)

    def register(self, rule: HardRule) -> None:
        if rule.priority < 0:
            raise ValueError("rule priority must be non-negative")
        if any(existing.rule_id == rule.rule_id for existing in self._rules):
            raise ValueError(f"duplicate rule_id: {rule.rule_id}")
        self._rules.append(rule)
        self._rules.sort(key=lambda candidate: (-candidate.priority, candidate.rule_id))

    def evaluate(self, context: dict[str, Any]) -> dict[str, Any] | None:
        for rule in self._rules:
            if rule.matches(context):
                return {"rule_id": rule.rule_id, "decision": rule.decision, "reason": rule.reason, "policy": "hard_rule"}
        return None
