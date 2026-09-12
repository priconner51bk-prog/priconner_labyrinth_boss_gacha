import json

from scripts.extract_l1b_exceptions import extract


def test_extract_selects_only_low_confidence_rejected_or_error_rows(tmp_path):
    path = tmp_path / "ocr_results.jsonl"
    rows = [
        {"image_id": "ok", "confidence": 0.95, "accepted": True, "error": None},
        {"image_id": "low", "confidence": 0.40, "accepted": True, "error": None},
        {"image_id": "reject", "confidence": 0.99, "accepted": False, "error": None},
        {"image_id": "error", "confidence": None, "accepted": False, "error": "empty"},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    result = extract(path)

    assert [row["image_id"] for row in result] == ["low", "reject", "error"]
    assert all(row["final_decision"] == "WAITING_LOCAL_INPUT" for row in result)
