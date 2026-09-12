import json

import pytest

from diagnostics.safety_stop_analysis import analyze_safety_stop, enrich_safety_stop
from scripts.analyze_safety_stops import analyze_lines, markdown


def test_known_reason_has_actionable_retry_condition():
    result = analyze_safety_stop("notice_did_not_close")
    assert result["reason_class"] == "notice_did_not_close"
    assert "one tap" in result["retry_condition"]


def test_dynamic_guild_mismatch_uses_stable_class():
    result = analyze_safety_stop("guild_mismatch:OCR fragment")
    assert result["reason_class"] == "guild_mismatch"


def test_unknown_reason_is_not_guessed():
    result = analyze_safety_stop("new_failure")
    assert result["reason_class"] == "unclassified"
    assert "Preserve" in result["countermeasure"]


def test_non_stop_event_is_not_modified():
    event = {"status": "matched", "attempt": 1}
    assert enrich_safety_stop(event) == event


def test_jsonl_analysis_and_markdown_output():
    events = analyze_lines([
        json.dumps({"status": "matched"}),
        json.dumps({"status": "safety_stop", "reason": "adb_unavailable"}),
    ])
    assert len(events) == 1
    assert "Retry condition" in markdown(events)


def test_invalid_json_reports_line_number():
    with pytest.raises(ValueError, match="line 2"):
        analyze_lines(["{}", "{"])
