"""Validate compact L1b OCR input manifests without reading image binaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable


REQUIRED_FIELDS = {
    "images": {"image_id", "screen_id", "resolution", "source_path", "visible_roi"},
    "labels": {"image_id", "area", "expected_text", "canonical_name", "roi", "label_confidence"},
    "ocr_results": {"image_id", "text", "confidence", "bbox", "matched_name", "accepted", "elapsed_ms", "error"},
}


def read_jsonl(path: Path, kind: str) -> list[dict]:
    rows: list[dict] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{kind}:{line_number}: invalid JSON: {exc.msg}") from exc
        missing = sorted(REQUIRED_FIELDS[kind] - row.keys())
        if missing:
            raise ValueError(f"{kind}:{line_number}: missing fields: {', '.join(missing)}")
        rows.append(row)
    return rows


def unique_ids(rows: Iterable[dict], kind: str) -> set[str]:
    ids = [str(row["image_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{kind}: duplicate image_id")
    return set(ids)


def validate(images_path: Path, labels_path: Path, results_path: Path) -> dict:
    images = read_jsonl(images_path, "images")
    labels = read_jsonl(labels_path, "labels")
    results = read_jsonl(results_path, "ocr_results")
    image_ids = unique_ids(images, "images")
    label_ids = unique_ids(labels, "labels")
    result_ids = unique_ids(results, "ocr_results")
    if image_ids != label_ids or image_ids != result_ids:
        raise ValueError("image_id sets do not match across images, labels, and ocr_results")
    return {"status": "ok", "image_count": len(image_ids)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--ocr-results", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = validate(args.images, args.labels, args.ocr_results)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
