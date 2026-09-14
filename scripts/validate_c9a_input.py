"""Validate real-device startup transition evidence for C9a."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

REQUIRED = {
    "task_id", "run_id", "capture_time", "screen_sequence", "wait_seconds",
    "timeout_seconds", "title_tap_count", "screen_after", "result",
    "stop_reason", "screenshots", "operation_log_path",
}
KNOWN_AFTER = {"guild_select", "item_reward", "startup_notice", "startup_error"}


def _path(base: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else base / candidate


def validate(path: Path, require_files: bool = False) -> dict:
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
    if len(rows) != 1:
        raise ValueError(f"expected exactly one C9a result, got {len(rows)}")

    row = rows[0]
    if row["task_id"] != "C9a" or not str(row["run_id"]).strip():
        raise ValueError("task_id must be C9a and run_id must be non-empty")
    try:
        captured = datetime.fromisoformat(str(row["capture_time"]))
    except ValueError as exc:
        raise ValueError("capture_time must be ISO-8601") from exc
    if captured.tzinfo is None:
        raise ValueError("capture_time must include a timezone")

    sequence = row["screen_sequence"]
    if not isinstance(sequence, list) or not sequence or any(not isinstance(v, str) or not v.strip() for v in sequence):
        raise ValueError("screen_sequence must be a non-empty list of screen IDs")
    for field in ("wait_seconds", "timeout_seconds"):
        value = row[field]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{field} must be a non-negative number")
    if row["timeout_seconds"] <= 0 or row["wait_seconds"] > row["timeout_seconds"]:
        raise ValueError("wait_seconds must not exceed a positive timeout_seconds")
    if not isinstance(row["title_tap_count"], int) or isinstance(row["title_tap_count"], bool):
        raise TypeError("title_tap_count must be an integer")

    screenshots = row["screenshots"]
    if not isinstance(screenshots, list) or len(screenshots) < 2 or any(not isinstance(v, str) or not v.strip() for v in screenshots):
        raise ValueError("screenshots must contain at least two non-empty paths")
    if not str(row["operation_log_path"]).strip():
        raise ValueError("operation_log_path must be non-empty")

    if row["result"] == "success":
        if "startup_splash" not in sequence or "title" not in sequence:
            raise ValueError("success requires startup_splash and title in screen_sequence")
        if sequence.index("startup_splash") > sequence.index("title"):
            raise ValueError("startup_splash must precede title")
        if sequence.count("title") != 1 or row["title_tap_count"] != 1:
            raise ValueError("success requires one title observation and exactly one title tap")
        if row["screen_after"] not in KNOWN_AFTER or sequence[-1] != row["screen_after"]:
            raise ValueError("success requires a final known screen_after")
        if row["stop_reason"] not in (None, ""):
            raise ValueError("success must not have stop_reason")
    elif row["result"] == "safety_stop":
        if row["title_tap_count"] not in (0, 1):
            raise ValueError("safety_stop permits at most one title tap")
        if not str(row["stop_reason"] or "").strip():
            raise ValueError("safety_stop requires stop_reason")
    else:
        raise ValueError("result must be success or safety_stop")

    if require_files:
        for value in [*screenshots, row["operation_log_path"]]:
            if not _path(path.parent, value).is_file():
                raise ValueError(f"evidence file does not exist: {value}")
    return {"status": "ok", "result": row["result"], "title_tap_count": row["title_tap_count"]}


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
