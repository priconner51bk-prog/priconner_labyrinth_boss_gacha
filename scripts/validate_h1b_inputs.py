"""Validate H1b guild-selection result rows before Cloud acceptance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPECTED_COUNTS = {"H1b-2": 4, "H1b-3": 4, "H1b-4": 3, "H1b-5": 3}
RESULTS = {"success", "safety_stop", "input_missing"}
REQUIRED_FIELDS = {
    "task_id",
    "run_id",
    "guild",
    "page",
    "swipe_direction",
    "swipe_count",
    "serial",
    "wm_size",
    "screen_before",
    "screen_after",
    "ocr",
    "tap_point",
    "result",
    "screenshot_path",
    "safety_reason",
}


def _read_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
        missing = sorted(REQUIRED_FIELDS - row.keys())
        if missing:
            raise ValueError(f"line {line_number}: missing fields: {', '.join(missing)}")
        rows.append(row)
    return rows


def _valid_box(value: object) -> bool:
    return isinstance(value, list) and len(value) == 4 and all(isinstance(item, (int, float)) for item in value)


def _valid_point(value: object) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(isinstance(item, (int, float)) for item in value)


def validate(path: Path, task_id: str, require_files: bool = False) -> dict:
    if task_id not in EXPECTED_COUNTS:
        raise ValueError(f"unsupported task_id: {task_id}")
    rows = _read_rows(path)
    if len(rows) != EXPECTED_COUNTS[task_id]:
        raise ValueError(f"{task_id}: expected {EXPECTED_COUNTS[task_id]} rows, got {len(rows)}")

    guilds: set[str] = set()
    base = path.parent
    for index, row in enumerate(rows, 1):
        prefix = f"row {index}"
        if row["task_id"] != task_id:
            raise ValueError(f"{prefix}: task_id must be {task_id}")
        guild = str(row["guild"]).strip()
        if not guild or guild in guilds:
            raise ValueError(f"{prefix}: guild must be non-empty and unique")
        guilds.add(guild)
        if not str(row["run_id"]).strip() or not str(row["serial"]).strip():
            raise ValueError(f"{prefix}: run_id and serial are required")
        if row["wm_size"] != "1280x720":
            raise ValueError(f"{prefix}: wm_size must be 1280x720")
        if not isinstance(row["page"], int) or row["page"] < 1:
            raise ValueError(f"{prefix}: page must be a positive integer")
        if row["swipe_direction"] not in {"left", "right", "none"}:
            raise ValueError(f"{prefix}: invalid swipe_direction")
        if not isinstance(row["swipe_count"], int) or row["swipe_count"] < 0:
            raise ValueError(f"{prefix}: swipe_count must be a non-negative integer")
        if row["result"] not in RESULTS:
            raise ValueError(f"{prefix}: invalid result")

        ocr = row["ocr"]
        if not isinstance(ocr, dict) or not {"text", "confidence", "bbox"} <= ocr.keys():
            raise ValueError(f"{prefix}: ocr must contain text, confidence, and bbox")
        confidence = ocr["confidence"]
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1 or not _valid_box(ocr["bbox"]):
            raise ValueError(f"{prefix}: invalid OCR confidence or bbox")

        if row["result"] == "success":
            if row["screen_before"] != "guild_select" or row["screen_after"] != "guild_confirm":
                raise ValueError(f"{prefix}: success requires guild_select -> guild_confirm")
            if str(ocr["text"]).strip() != guild or not _valid_point(row["tap_point"]):
                raise ValueError(f"{prefix}: success requires matching OCR text and tap_point")
            if row["safety_reason"] is not None:
                raise ValueError(f"{prefix}: success must not have safety_reason")
        elif not str(row["safety_reason"] or "").strip():
            raise ValueError(f"{prefix}: non-success requires safety_reason")

        evidence = Path(str(row["screenshot_path"]))
        if not str(row["screenshot_path"]).strip():
            raise ValueError(f"{prefix}: screenshot_path is required")
        if require_files and not (evidence if evidence.is_absolute() else base / evidence).is_file():
            raise ValueError(f"{prefix}: screenshot does not exist: {evidence}")

    return {"status": "ok", "task_id": task_id, "guild_count": len(guilds)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--task-id", required=True, choices=sorted(EXPECTED_COUNTS))
    parser.add_argument("--require-files", action="store_true")
    args = parser.parse_args()
    try:
        summary = validate(args.input, args.task_id, args.require_files)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
