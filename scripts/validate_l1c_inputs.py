"""Validate L1c real-device flow results before Cloud acceptance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

TASKS = {"L1c-1", "L1c-2", "L1c-3", "L1c-4"}
REQUIRED = {"task_id", "run_id", "screen_sequence", "result", "input_count", "screenshots"}


def _read(path: Path) -> list[dict]:
    rows = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {number}: invalid JSON: {exc.msg}") from exc
        missing = sorted(REQUIRED - row.keys())
        if missing:
            raise ValueError(f"line {number}: missing fields: {', '.join(missing)}")
        rows.append(row)
    return rows


def _text_list(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)


def validate(path: Path, require_files: bool = False) -> dict:
    rows = _read(path)
    if len(rows) != len(TASKS):
        raise ValueError(f"expected exactly {len(TASKS)} rows, got {len(rows)}")
    by_task = {str(row["task_id"]): row for row in rows}
    if set(by_task) != TASKS or len(by_task) != len(rows):
        raise ValueError("task_id must contain each of L1c-1 through L1c-4 exactly once")

    base = path.parent
    run_ids = set()
    for task_id in sorted(TASKS):
        row = by_task[task_id]
        run_id = str(row["run_id"]).strip()
        if not run_id or run_id in run_ids:
            raise ValueError(f"{task_id}: run_id must be non-empty and unique")
        run_ids.add(run_id)
        if not _text_list(row["screen_sequence"]):
            raise ValueError(f"{task_id}: screen_sequence must be a non-empty string list")
        if not isinstance(row["input_count"], int) or row["input_count"] < 0:
            raise ValueError(f"{task_id}: input_count must be a non-negative integer")
        if not _text_list(row["screenshots"]):
            raise ValueError(f"{task_id}: screenshots must be a non-empty path list")
        if require_files:
            for value in row["screenshots"]:
                evidence = Path(value)
                if not (evidence if evidence.is_absolute() else base / evidence).is_file():
                    raise ValueError(f"{task_id}: screenshot does not exist: {evidence}")

    normal = by_task["L1c-1"]
    if normal["result"] != "success" or normal["input_count"] < 1:
        raise ValueError("L1c-1: normal flow requires success and at least one input")
    if not _text_list(normal.get("boss_names")) or not _text_list(normal.get("ocr_outputs")):
        raise ValueError("L1c-1: boss_names and ocr_outputs are required")

    withdraw = by_task["L1c-2"]
    if withdraw["result"] != "withdraw_confirmed" or not str(withdraw.get("observed_boss", "")).strip():
        raise ValueError("L1c-2: observed_boss and withdraw_confirmed are required")
    if not _text_list(withdraw.get("allowed_bosses")) or withdraw["observed_boss"] in withdraw["allowed_bosses"]:
        raise ValueError("L1c-2: observed_boss must be outside allowed_bosses")

    stopped = by_task["L1c-3"]
    if stopped["result"] != "safety_stop" or stopped["input_count"] != 0:
        raise ValueError("L1c-3: safety_stop requires input_count=0")
    if stopped.get("trigger") not in {"unknown_screen", "low_ocr_confidence"} or not str(stopped.get("stop_reason", "")).strip():
        raise ValueError("L1c-3: valid trigger and stop_reason are required")

    resume = by_task["L1c-4"]
    if resume["result"] != "resumed" or not str(resume.get("resume_screen", "")).strip():
        raise ValueError("L1c-4: resume_screen and resumed result are required")
    if not _text_list(resume.get("boss_names")):
        raise ValueError("L1c-4: boss_names are required after re-evaluation")

    return {"status": "ok", "task_count": len(rows), "run_count": len(run_ids)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--require-files", action="store_true")
    args = parser.parse_args()
    try:
        result = validate(args.input, args.require_files)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
