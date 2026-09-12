"""Validate real-device notice-close evidence for C9b."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


REQUIRED = {
    "task_id", "run_id", "capture_time", "screen_before", "notice_variant",
    "close_button_bbox", "close_tap_count", "screen_after", "result",
    "stop_reason", "screenshot_before_path", "screenshot_after_path",
    "operation_log_path",
}
SUCCESS_SCREENS = {"guild_select", "item_reward"}
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720


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
        raise ValueError(f"expected exactly one C9b result, got {len(rows)}")

    row = rows[0]
    if row["task_id"] != "C9b" or not str(row["run_id"]).strip():
        raise ValueError("task_id must be C9b and run_id must be non-empty")
    try:
        captured = datetime.fromisoformat(str(row["capture_time"]))
    except ValueError as exc:
        raise ValueError("capture_time must be ISO-8601") from exc
    if captured.tzinfo is None:
        raise ValueError("capture_time must include a timezone")
    if row["screen_before"] != "startup_notice" or not str(row["notice_variant"]).strip():
        raise ValueError("screen_before=startup_notice and notice_variant are required")

    bbox = row["close_button_bbox"]
    if not (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(v, int) and not isinstance(v, bool) for v in bbox)
    ):
        raise ValueError("close_button_bbox must contain four integers")
    left, top, right, bottom = bbox
    if not (0 <= left < right <= SCREEN_WIDTH and 0 <= top < bottom <= SCREEN_HEIGHT):
        raise ValueError("close_button_bbox must be an ordered region within 1280x720")

    evidence_fields = (
        "screenshot_before_path", "screenshot_after_path", "operation_log_path"
    )
    for field in evidence_fields:
        if not str(row[field]).strip():
            raise ValueError(f"{field} must be non-empty")

    if row["result"] == "success":
        if row["close_tap_count"] != 1:
            raise ValueError("success requires exactly one close-button tap")
        if row["screen_after"] not in SUCCESS_SCREENS:
            raise ValueError("success requires transition to a known gacha-start screen")
        if row["stop_reason"] not in (None, ""):
            raise ValueError("success must not have stop_reason")
    elif row["result"] == "safety_stop":
        if row["close_tap_count"] not in (0, 1):
            raise ValueError("safety_stop permits at most one close-button tap")
        if not str(row["stop_reason"] or "").strip():
            raise ValueError("safety_stop requires stop_reason")
    else:
        raise ValueError("result must be success or safety_stop")

    if require_files:
        for field in evidence_fields:
            if not _path(path.parent, str(row[field])).is_file():
                raise ValueError(f"{field} does not exist: {row[field]}")
    return {"status": "ok", "result": row["result"], "close_tap_count": row["close_tap_count"]}


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
