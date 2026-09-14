from __future__ import annotations

import json
from typing import Any


def export_approved_rule(candidate: dict[str, Any]) -> str:
    """Export only an explicitly approved rule as inert Python data."""
    if candidate.get("status") != "approved":
        raise ValueError("only approved rules can be exported")
    rule_id = candidate.get("id") or candidate.get("rule_id")
    required = ("rule", "confidence")
    missing = [key for key in required if key not in candidate]
    if not isinstance(rule_id, str) or not rule_id.strip():
        missing.append("id or rule_id")
    if missing:
        raise ValueError(f"approved rule is missing fields: {', '.join(missing)}")
    try:
        confidence = float(candidate["confidence"])
    except (TypeError, ValueError) as exc:
        raise ValueError("approved rule confidence must be numeric") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("approved rule confidence must be between 0 and 1")
    if not isinstance(candidate["rule"], dict) or not candidate["rule"]:
        raise ValueError("approved rule must contain a non-empty rule object")
    conditions = candidate.get("applicable_conditions", {})
    if not isinstance(conditions, dict):
        raise TypeError("approved rule applicable_conditions must be an object")
    payload = {"rule_id": rule_id, "rule": candidate["rule"], "confidence": confidence, "applicable_conditions": conditions}
    try:
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    except (TypeError, ValueError) as exc:
        raise ValueError("approved rule contains non-serializable data") from exc
    return "# Generated inert rule data; review before registration.\nRULE = " + serialized + "\n"
