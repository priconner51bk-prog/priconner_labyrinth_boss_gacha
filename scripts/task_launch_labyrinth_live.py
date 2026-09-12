"""ホーム画面からクエスト入口をOCR確認してラビリンスへ進む。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.ocr_service import OCRServiceAdapter
from vision.template_screen_probe import load_template_probe_config


def main() -> int:
    parser = argparse.ArgumentParser(description="ホーム画面からクエスト入口を開く")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    probe = load_template_probe_config(ROOT / "configs/live_screen_templates.json", capture)
    current_screen = probe.observe_screen()
    if current_screen == "labyrinth_top":
        print(json.dumps({"status": "safety_stop", "reason": "already_in_labyrinth", "screen_id": current_screen}, ensure_ascii=False))
        return 2
    source = ROOT / "data/observations/live/task_launch_source.png"
    roi_path = ROOT / "data/observations/live/task_launch_bottom_roi.png"
    # quest_menu is already inside the quest screen.  Its safe target is the
    # dedicated lower-right labyrinth card, not the bottom navigation label
    # 「クエスト」 used by the home-screen flow.
    if probe.observe_screen() == "quest_menu":
        capture.capture(source)
        image = cv2.imread(str(source), cv2.IMREAD_COLOR)
        if image is None:
            print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False)); return 2
        card = image[450:630, 1000:1280]
        cv2.imwrite(str(roi_path), card)
        try:
            lines = OCRServiceAdapter(language="jpn").recognize(str(roi_path))
        except Exception as exc:
            print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
        matches = [line for line in lines if line.confidence >= 0.70 and ("ラビリンス" in line.text or "黎明境" in line.text) and line.bbox]
        if len(matches) != 1:
            print(json.dumps({"status": "safety_stop", "reason": "labyrinth_target_not_unique", "match_count": len(matches)}, ensure_ascii=False)); return 2
        bbox = matches[0].bbox
        x = int((bbox[0] + bbox[2]) / 2) + 1000
        y = int((bbox[1] + bbox[3]) / 2) + 450
        if not (1000 <= x <= 1280 and 450 <= y <= 630):
            print(json.dumps({"status": "safety_stop", "reason": "labyrinth_target_out_of_bounds", "x": x, "y": y}, ensure_ascii=False)); return 2
        try:
            run_adb_coordinate_sequence(
                [(x, y)], serial=args.serial, healthcheck=True,
                timing_policy=AdaptiveWaitPolicy(), require_screen_change=False,
                debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_launch_labyrinth",
            )
            after = probe.observe_screen()
        except Exception as exc:
            print(json.dumps({"status": "safety_stop", "reason": f"launch_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
        print(json.dumps({"status": "completed", "screen_after": after, "tap": [x, y]}, ensure_ascii=False)); return 0
    capture.capture(source)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False)); return 2
    roi = image[560:720, 0:1280]
    cv2.imwrite(str(roi_path), roi)
    try:
        lines = OCRServiceAdapter(language="jpn").recognize(str(roi_path))
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    matches = [line for line in lines if line.confidence >= 0.70 and "クエスト" in line.text and line.bbox]
    if len(matches) != 1:
        print(json.dumps({"status": "safety_stop", "reason": "quest_target_not_unique", "match_count": len(matches)}, ensure_ascii=False)); return 2
    bbox = matches[0].bbox
    x = int((bbox[0] + bbox[2]) / 2)
    y = int((bbox[1] + bbox[3]) / 2) + 560
    if not (560 <= x <= 900 and 600 <= y <= 720):
        print(json.dumps({"status": "safety_stop", "reason": "quest_target_out_of_bounds", "x": x, "y": y}, ensure_ascii=False)); return 2
    before_path = ROOT / "data/observations/live/task_launch_before.png"
    capture.capture(before_path)
    previous = hashlib.sha1(before_path.read_bytes()).hexdigest()
    try:
        run_adb_coordinate_sequence(
            [(x, y)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(),
            screen_probe=lambda: hashlib.sha1(before_path.read_bytes()).hexdigest(),
            require_screen_change=False, previous_screen_token=previous,
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_launch",
        )
        after = probe.observe_screen()
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"launch_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    print(json.dumps({"status": "completed", "screen_after": after, "tap": [x, y]}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
