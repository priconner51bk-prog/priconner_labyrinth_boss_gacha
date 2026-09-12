import json

import pytest

from scripts.validate_c9b_input import validate


def _row():
    return {
        "task_id": "C9b", "run_id": "c9b-001",
        "capture_time": "2026-09-06T15:50:00+09:00",
        "screen_before": "startup_notice", "notice_variant": "maintenance_notice",
        "close_button_bbox": [1080, 45, 1240, 155], "close_tap_count": 1,
        "screen_after": "guild_select", "result": "success", "stop_reason": None,
        "screenshot_before_path": "notice-before.png",
        "screenshot_after_path": "notice-after.png",
        "operation_log_path": "operation.jsonl",
    }


def test_accepts_single_close_with_transition_and_evidence(tmp_path):
    for name in ("notice-before.png", "notice-after.png", "operation.jsonl"):
        (tmp_path / name).write_bytes(b"evidence")
    path = tmp_path / "result.jsonl"
    path.write_text(json.dumps(_row(), ensure_ascii=False), encoding="utf-8")
    assert validate(path, require_files=True)["status"] == "ok"


def test_rejects_repeated_close(tmp_path):
    row = _row()
    row["close_tap_count"] = 2
    path = tmp_path / "result.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one"):
        validate(path)


def test_rejects_notice_still_visible_as_success(tmp_path):
    row = _row()
    row["screen_after"] = "startup_notice"
    path = tmp_path / "result.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="known gacha-start screen"):
        validate(path)


@pytest.mark.parametrize(
    "bbox",
    ([1240, 45, 1080, 155], [-1, 45, 1240, 155], [1080, 45, 1281, 155]),
)
def test_rejects_invalid_close_bbox(tmp_path, bbox):
    row = _row()
    row["close_button_bbox"] = bbox
    path = tmp_path / "result.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="ordered region within 1280x720"):
        validate(path)
