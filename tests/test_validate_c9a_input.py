import json

import pytest

from scripts.validate_c9a_input import validate


def _row():
    return {
        "task_id": "C9a", "run_id": "c9a-001",
        "capture_time": "2026-09-06T16:00:00+09:00",
        "screen_sequence": ["startup_splash", "title", "guild_select"],
        "wait_seconds": 12.5, "timeout_seconds": 60,
        "title_tap_count": 1, "screen_after": "guild_select",
        "result": "success", "stop_reason": None,
        "screenshots": ["splash.png", "title.png", "after.png"],
        "operation_log_path": "operation.jsonl",
    }


def _write(tmp_path, row):
    path = tmp_path / "result.jsonl"
    path.write_text(json.dumps(row), encoding="utf-8")
    return path


def test_accepts_single_title_tap_and_known_transition(tmp_path):
    row = _row()
    for name in (*row["screenshots"], row["operation_log_path"]):
        (tmp_path / name).write_bytes(b"evidence")
    assert validate(_write(tmp_path, row), require_files=True)["status"] == "ok"


def test_rejects_repeated_title_or_tap(tmp_path):
    row = _row()
    row["screen_sequence"] = ["startup_splash", "title", "title", "guild_select"]
    row["title_tap_count"] = 2
    with pytest.raises(ValueError, match="one title observation"):
        validate(_write(tmp_path, row))


def test_rejects_wait_beyond_timeout(tmp_path):
    row = _row()
    row["wait_seconds"] = 61
    with pytest.raises(ValueError, match="must not exceed"):
        validate(_write(tmp_path, row))


def test_rejects_unknown_success_destination(tmp_path):
    row = _row()
    row["screen_sequence"][-1] = "unknown"
    row["screen_after"] = "unknown"
    with pytest.raises(ValueError, match="final known"):
        validate(_write(tmp_path, row))


def test_safety_stop_requires_reason_and_at_most_one_tap(tmp_path):
    row = _row()
    row.update(result="safety_stop", stop_reason="timeout", title_tap_count=2)
    with pytest.raises(ValueError, match="at most one"):
        validate(_write(tmp_path, row))
