from scripts.preflight_gacha_result import preflight


def _payload():
    return {
        "status": "safety_stop", "reason": "notice_did_not_close",
        "attempt": 0, "max_attempts": 1000,
        "allowed_bosses": {"3": ["ボスA"], "5": ["ボスB"]},
        "last_screen": "notice",
        "last_action": {"type": "tap", "screen_before": "notice"},
        "evidence_paths": ["screen.png", "operations.jsonl"],
    }


def test_classified_stop_returns_read_only_resume_point(tmp_path):
    for name in ("screen.png", "operations.jsonl"):
        (tmp_path / name).write_text("evidence", encoding="utf-8")
    result = preflight(_payload(), base=tmp_path, require_files=True)
    assert result["status"] == "ready"
    assert result["next_local_screen"] == "notice"
    assert result["resume_rule"].startswith("observe_current_screen")


def test_completed_result_must_not_be_rerun(tmp_path):
    payload = _payload()
    payload.update(status="matched", reason=None, attempt=1, last_screen="boss_map")
    result = preflight(payload, base=tmp_path)
    assert result["status"] == "completed"
    assert result["next_local_screen"] is None
    assert result["resume_rule"] == "do_not_rerun_completed_result"


def test_rejects_attempt_above_limit(tmp_path):
    payload = _payload()
    payload["attempt"] = 1001
    result = preflight(payload, base=tmp_path)
    assert result["reason"] == "saved_attempt_bounds_invalid"


def test_rejects_empty_area_allowlist(tmp_path):
    payload = _payload()
    payload["allowed_bosses"]["5"] = []
    result = preflight(payload, base=tmp_path)
    assert result["reason"] == "saved_allowed_bosses_invalid"


def test_rejects_unknown_screen_or_action(tmp_path):
    payload = _payload()
    payload["last_screen"] = "mystery"
    assert preflight(payload, base=tmp_path)["reason"] == "saved_last_screen_unknown"
    payload = _payload()
    payload["last_action"] = {}
    assert preflight(payload, base=tmp_path)["reason"] == "saved_last_action_invalid"


def test_rejects_missing_evidence_file(tmp_path):
    result = preflight(_payload(), base=tmp_path, require_files=True)
    assert result["reason"] == "saved_evidence_file_missing"


def test_rejects_unclassified_safety_stop(tmp_path):
    payload = _payload()
    payload["reason"] = "new_unknown_reason"
    result = preflight(payload, base=tmp_path)
    assert result["reason"] == "saved_safety_stop_unclassified"
