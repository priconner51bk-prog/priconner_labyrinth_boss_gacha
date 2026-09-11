from __future__ import annotations

from typing import Any

from contracts import DecisionRecord
from memory.repository import SQLiteRepository


class DecisionRecorder:
    """Persist router output as an auditable decision; never execute it."""

    def __init__(self, repository: SQLiteRepository):
        self.repository = repository

    def record(self, result: dict[str, Any], *, state_id: str, intent_id: str, turn_id: str | None = None) -> DecisionRecord:
        route = str(result.get("route", "observation_gate"))
        source = {"hard_rule": "rule_engine", "score_rule": "rule_engine", "observation_gate": "observation", "human": "human"}.get(route, "observation")
        policy = route if route in {"hard_rule", "score_rule", "observation_gate", "human"} else "observation_gate"
        reason = result.get("reason", [])
        if isinstance(reason, str):
            reason = [reason]
        if not reason:
            reason = [f"route={route}"]
        decision = DecisionRecord(
            decision_id=str(result.get("decision_id") or f"decision:{turn_id or state_id}:{intent_id}"),
            state_id=state_id,
            intent_id=intent_id,
            decision=str(result.get("decision", "unknown")),
            reason=[str(item) for item in reason],
            policy=policy,
            source=source,
            confidence=float(result.get("confidence", 1.0 if route in {"hard_rule", "score_rule"} else 0.0)),
        )
        payload = decision.model_dump()
        if turn_id is not None:
            payload["turn_id"] = turn_id
        self.repository.save_decision(payload)
        return decision
