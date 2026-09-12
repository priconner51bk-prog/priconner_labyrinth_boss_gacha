import json

import pytest

from scripts.validate_l1c_inputs import validate


def valid_rows():
    common = {"input_count": 1, "screenshots": ["evidence.png"]}
    return [
        {**common, "task_id": "L1c-1", "run_id": "run-1", "screen_sequence": ["guild_select", "boss_detail"], "result": "success", "boss_names": ["boss-a", "boss-b"], "ocr_outputs": ["boss-a", "boss-b"]},
        {**common, "task_id": "L1c-2", "run_id": "run-2", "screen_sequence": ["boss_detail", "withdraw_confirm"], "result": "withdraw_confirmed", "observed_boss": "boss-x", "allowed_bosses": ["boss-a"]},
        {**common, "task_id": "L1c-3", "run_id": "run-3", "screen_sequence": ["guild_select", "unknown"], "result": "safety_stop", "input_count": 0, "trigger": "unknown_screen", "stop_reason": "screen_not_recognized"},
        {**common, "task_id": "L1c-4", "run_id": "run-4", "screen_sequence": ["guild_select", "boss_detail"], "result": "resumed", "resume_screen": "guild_select", "boss_names": ["boss-a", "boss-b"]},
    ]


def write_rows(path, rows):
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_validate_accepts_complete_l1c_set(tmp_path):
    evidence = tmp_path / "evidence.png"
    evidence.write_bytes(b"png")
    path = tmp_path / "l1c_results.jsonl"
    write_rows(path, valid_rows())
    assert validate(path, require_files=True) == {"status": "ok", "task_count": 4, "run_count": 4}


def test_validate_rejects_safety_stop_after_input(tmp_path):
    rows = valid_rows()
    rows[2]["input_count"] = 1
    path = tmp_path / "l1c_results.jsonl"
    write_rows(path, rows)
    with pytest.raises(ValueError, match="input_count=0"):
        validate(path)
