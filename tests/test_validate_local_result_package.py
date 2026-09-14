import json

import pytest

from scripts.validate_local_result_package import validate


def write_package(tmp_path, *, failure_count=1):
    manifest = {
        "run_id": "run-1", "task_id": "L1c-3", "result_count": 2,
        "failure_count": failure_count, "artifact_paths": ["a.png"], "redaction_check": True,
    }
    rows = [
        {"run_id": "run-1", "task_id": "L1c-3", "result": "success"},
        {"run_id": "run-1", "task_id": "L1c-3", "result": "safety_stop"},
    ]
    manifest_path = tmp_path / "manifest.json"
    results_path = tmp_path / "results.jsonl"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    results_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return manifest_path, results_path


def test_validate_accepts_consistent_package(tmp_path):
    assert validate(*write_package(tmp_path)) == {"status": "ok", "result_count": 2, "failure_count": 1}


def test_validate_rejects_count_mismatch(tmp_path):
    with pytest.raises(ValueError, match="counts do not match"):
        validate(*write_package(tmp_path, failure_count=0))


def test_validate_rejects_task_id_mismatch(tmp_path):
    manifest_path, results_path = write_package(tmp_path)
    rows = json.loads(results_path.read_text(encoding="utf-8").splitlines()[0])
    rows["task_id"] = "other-task"
    lines = results_path.read_text(encoding="utf-8").splitlines()
    lines[0] = json.dumps(rows)
    results_path.write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(ValueError, match="task_id mismatch"):
        validate(manifest_path, results_path)
