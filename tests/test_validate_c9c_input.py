import json

import pytest

from scripts.validate_c9c_input import validate


def _row():
    return {
        "task_id": "C9c", "run_id": "c9c-001",
        "capture_time": "2026-09-06T15:30:00+09:00",
        "error_text": "通信エラー", "screen_before": "startup_error",
        "title_button_bbox": [420, 520, 860, 650], "title_tap_count": 1,
        "screen_after": "title", "result": "success", "stop_reason": None,
        "screenshot_path": "error.png", "operation_log_path": "operation.jsonl",
    }


def test_accepts_single_tap_recovery_with_evidence(tmp_path):
    (tmp_path / "error.png").write_bytes(b"png")
    (tmp_path / "operation.jsonl").write_text("{}\n", encoding="utf-8")
    path = tmp_path / "result.jsonl"
    path.write_text(json.dumps(_row(), ensure_ascii=False), encoding="utf-8")
    assert validate(path, require_files=True)["status"] == "ok"


def test_rejects_repeated_tap(tmp_path):
    row = _row()
    row["title_tap_count"] = 2
    path = tmp_path / "result.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one"):
        validate(path)


@pytest.mark.parametrize(
    "bbox",
    ([860, 520, 420, 650], [-1, 520, 860, 650], [420, 520, 1281, 650]),
)
def test_rejects_invalid_button_bbox(tmp_path, bbox):
    row = _row()
    row["title_button_bbox"] = bbox
    path = tmp_path / "result.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="ordered region within 1280x720"):
        validate(path)


def test_rejects_empty_evidence_path(tmp_path):
    row = _row()
    row["operation_log_path"] = " "
    path = tmp_path / "result.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="operation_log_path must be non-empty"):
        validate(path)
