"""Analyze safety-stop events from JSON Lines."""

from __future__ import annotations

import json
from typing import Any


def analyze_lines(lines: list[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {number}") from exc
        if isinstance(event, dict) and event.get("status") == "safety_stop":
            events.append(event)
    return events


def markdown(events: list[dict[str, Any]]) -> str:
    rows = ["# Safety stops", "", "| Reason | Retry condition |", "|---|---|"]
    for event in events:
        reason = str(event.get("reason", "unclassified"))
        rows.append(f"| {reason} | Preserve the evidence and inspect before retrying. |")
    return "\n".join(rows) + "\n"
