"""初期キャラ候補の実機OCR（task_種別、入力は行わない）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision.capture import AdbScreenCapture
from vision.labyrinth_character_ocr import recognize_character_cards
from vision.ocr import PaddleOCRAdapter, choose_ocr_device
from vision.ocr_service import OCRServiceAdapter
from vision.template_screen_probe import load_template_probe_config


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="初期キャラ候補をカード単位OCR")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    parser.add_argument("--output", type=Path, default=ROOT / "data/observations/live/initial_character_candidates.png")
    parser.add_argument("--min-confidence", type=float, default=0.80)
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    try:
        screen_id = probe.observe_screen()
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"screen_observation_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    if screen_id != "initial_char":
        # 青い見出しを持つキャラ選択画面は、お知らせの簡易判定と
        # 外観が似るため、OCRで見出しを再確認する。
        fallback = args.output.with_name("initial_character_screen_check.png")
        try:
            capture.capture(fallback)
            fallback_text = "".join(line.text for line in OCRServiceAdapter(language="jpn").recognize(str(fallback)))
            if "キャラ選択" in fallback_text:
                screen_id = "initial_char"
        except Exception:
            pass
    if screen_id != "initial_char":
        print(json.dumps({"status": "safety_stop", "reason": f"unexpected_screen:{screen_id!r}"}, ensure_ascii=False))
        return 2
    capture.capture(args.output)
    image = cv2.imread(str(args.output), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False))
        return 2
    config = json.loads((ROOT / "configs/labyrinth_ocr_regions.json").read_text(encoding="utf-8"))
    regions = config.get("regions", {}).get("initial_character_cards")
    if not isinstance(regions, list) or len(regions) < 8:
        print(json.dumps({"status": "safety_stop", "reason": "character_card_regions_invalid"}, ensure_ascii=False))
        return 2
    ocr = PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"), language="jpn")
    candidates = recognize_character_cards(str(args.output), ocr, regions, min_confidence=args.min_confidence, preprocess=True)
    manifest = args.output.with_name(args.output.stem + "_manifest.json")
    manifest.write_text(json.dumps({"source": "initial", "screen": str(args.output), "candidates": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok" if candidates else "safety_stop", "screen_id": screen_id,
                      "candidates": candidates, "manifest": str(manifest), "reason": None if candidates else "character_names_not_recognized"}, ensure_ascii=False))
    return 0 if candidates else 2


if __name__ == "__main__":
    raise SystemExit(main())
