"""Extract OCR rows that require local review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def extract(path: str | Path, *, confidence_threshold: float = 0.8) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if (
            row.get("error")
            or row.get("accepted") is False
            or row.get("confidence") is None
            or row.get("confidence", 1.0) < confidence_threshold
        ):
            result.append({**row, "final_decision": "WAITING_LOCAL_INPUT"})
    return result
