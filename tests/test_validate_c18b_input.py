import json

from scripts.validate_c18b_input import validate


def _write_manifest(tmp_path, cases):
    manifest = {
        "batch_id": "batch-1",
        "expected_failure_count": len(cases),
        "reported_failure_count": len(cases),
        "cases": cases,
    }
    path = tmp_path / "c18b.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _case(case_id):
    return {
        "case_id": case_id,
        "task_group": "H-02",
        "script_name": "task_example.py",
        "screen_id": "unknown",
        "status": "safety_stop",
        "reason": "screen_not_confirmed",
        "screenshot_path": "evidence.png",
        "ordered_steps": [{"order": 1, "action": "observe", "screen_id": "unknown", "status": "safety_stop"}],
    }


def test_validate_accepts_complete_failure_bundle(tmp_path):
    assert validate(_write_manifest(tmp_path, [_case("case-1")])) == []


def test_validate_rejects_duplicate_case_ids(tmp_path):
    errors = validate(_write_manifest(tmp_path, [_case("case-1"), _case("case-1")]))

    assert "duplicate case_id: case-1" in errors
