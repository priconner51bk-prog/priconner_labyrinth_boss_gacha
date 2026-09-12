import json

import pytest

from scripts.validate_l1b_inputs import validate


def write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")


def valid_rows():
    image = {"image_id": "img-1", "screen_id": "guild_select", "resolution": "1280x720", "source_path": "a.png", "visible_roi": [0, 0, 1, 1]}
    label = {"image_id": "img-1", "area": "guild", "expected_text": "美食殿", "canonical_name": "美食殿", "roi": [0, 0, 1, 1], "label_confidence": "HIGH"}
    result = {"image_id": "img-1", "text": "美食殿", "confidence": 0.99, "bbox": [0, 0, 1, 1], "matched_name": "美食殿", "accepted": True, "elapsed_ms": 10, "error": None}
    return image, label, result


def test_validate_accepts_matching_compact_inputs(tmp_path):
    paths = [tmp_path / name for name in ("images.jsonl", "labels.jsonl", "ocr_results.jsonl")]
    for path, row in zip(paths, valid_rows()):
        write_jsonl(path, [row])
    assert validate(*paths) == {"status": "ok", "image_count": 1}


def test_validate_rejects_mismatched_image_ids(tmp_path):
    image, label, result = valid_rows()
    result["image_id"] = "img-2"
    paths = [tmp_path / name for name in ("images.jsonl", "labels.jsonl", "ocr_results.jsonl")]
    for path, row in zip(paths, (image, label, result)):
        write_jsonl(path, [row])
    with pytest.raises(ValueError, match="image_id sets do not match"):
        validate(*paths)
