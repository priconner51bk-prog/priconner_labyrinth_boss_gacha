import json

import pytest

from scripts.validate_h1b_inputs import validate


def rows(task_id="H1b-2", count=4):
    return [
        {
            "task_id": task_id,
            "run_id": "20260906-001",
            "guild": f"guild-{index}",
            "page": 1,
            "swipe_direction": "none",
            "swipe_count": 0,
            "serial": "emulator-5554",
            "wm_size": "1280x720",
            "screen_before": "guild_select",
            "screen_after": "guild_confirm",
            "ocr": {"text": f"guild-{index}", "confidence": 0.98, "bbox": [100, 200, 300, 260]},
            "tap_point": [200, 230],
            "result": "success",
            "screenshot_path": f"h1b-{index}.png",
            "safety_reason": None,
        }
        for index in range(1, count + 1)
    ]


def write_jsonl(path, values):
    path.write_text("\n".join(json.dumps(value) for value in values), encoding="utf-8")


def test_validate_accepts_complete_h1b_batch(tmp_path):
    path = tmp_path / "guild_results.jsonl"
    write_jsonl(path, rows())
    assert validate(path, "H1b-2") == {"status": "ok", "task_id": "H1b-2", "guild_count": 4}


def test_validate_rejects_success_without_expected_transition(tmp_path):
    values = rows("H1b-4", 3)
    values[0]["screen_after"] = "item_reward"
    path = tmp_path / "guild_results.jsonl"
    write_jsonl(path, values)
    with pytest.raises(ValueError, match="guild_select -> guild_confirm"):
        validate(path, "H1b-4")
