"""Validate a compact Local result package without inspecting binary contents."""

from __future__ import annotations

import json
from pathlib import Path

REQUIRED_MANIFEST = {"run_id", "task_id", "result_count", "failure_count", "artifact_paths", "redaction_check"}
REQUIRED_RESULT = {"run_id", "task_id", "result"}


def validate(manifest_path: Path, results_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_MANIFEST - manifest.keys())
    if missing:
        raise ValueError(f"manifest missing fields: {', '.join(missing)}")
    rows = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for index, row in enumerate(rows, 1):
        missing = sorted(REQUIRED_RESULT - row.keys())
        if missing:
            raise ValueError(f"results:{index} missing fields: {', '.join(missing)}")
        if row["run_id"] != manifest["run_id"]:
            raise ValueError(f"results:{index} run_id mismatch")
        if row["task_id"] != manifest["task_id"]:
            raise ValueError(f"results:{index} task_id mismatch")
    failures = sum(row["result"] != "success" for row in rows)
    if int(manifest["result_count"]) != len(rows) or int(manifest["failure_count"]) != failures:
        raise ValueError("manifest counts do not match results")
    if manifest["redaction_check"] is not True:
        raise ValueError("redaction_check must be true")
    return {"status": "ok", "result_count": len(rows), "failure_count": failures}
