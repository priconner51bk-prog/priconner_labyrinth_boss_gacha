"""難易度変更画面で難易度10と変更ボタンを確認して進める。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.bottom_button import bottom_button_center, find_bottom_button
from vision.capture import AdbScreenCapture
from vision.ocr_service import OCRServiceAdapter


def button_looks_disabled(image, bbox: tuple[int, int, int, int]) -> bool:
    """確定ボタン周辺がグレー系なら無効（目的値が選択済み）と判定する。"""
    x1, y1, x2, y2 = bbox
    left = max(0, x1 - 120); top = max(0, y1 - 35)
    right = min(image.shape[1], x2 + 120); bottom = min(image.shape[0], y2 + 35)
    roi = image[top:bottom, left:right]
    if roi.size == 0:
        return False
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mean_saturation = float(hsv[:, :, 1].mean())
    blue = ((roi[:, :, 0].astype("int16") > roi[:, :, 2].astype("int16") + 20)
            & (roi[:, :, 0] > 100))
    blue_ratio = float(blue.mean())
    # A disabled gray button has both low saturation and almost no blue
    # background.  Requiring both avoids treating a blue enabled button as
    # disabled merely because its OCR/text area contains white pixels.
    return mean_saturation < 55.0 and blue_ratio < 0.025


def main() -> int:
    parser = argparse.ArgumentParser(description="難易度10を確認して変更する")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    source = ROOT / "data/observations/live/task_difficulty_source.png"
    capture.capture(source)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False)); return 2
    try:
        lines = OCRServiceAdapter(language="jpn").recognize(str(source))
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    normalized = "".join(line.text.replace(" ", "") for line in lines if line.confidence >= 0.70)
    if "難易度変更" not in normalized or "難易度10" not in normalized:
        print(json.dumps({"status": "safety_stop", "reason": "difficulty10_screen_not_confirmed"}, ensure_ascii=False)); return 2
    buttons = find_bottom_button(lines, "変更する")
    if len(buttons) != 1:
        print(json.dumps({"status": "safety_stop", "reason": "difficulty_change_button_not_unique", "count": len(buttons)}, ensure_ascii=False)); return 2
    bbox = buttons[0].bbox
    x, y = bottom_button_center(tuple(bbox))
    if not (620 <= x <= 950 and 580 <= y <= 700):
        print(json.dumps({"status": "safety_stop", "reason": "difficulty_change_button_out_of_bounds", "x": x, "y": y}, ensure_ascii=False)); return 2
    difficulty_rows = [line for line in lines if line.confidence >= 0.70 and "難易度10" in line.text and line.bbox]
    if len(difficulty_rows) != 1:
        print(json.dumps({"status": "safety_stop", "reason": "difficulty10_target_not_unique", "count": len(difficulty_rows)}, ensure_ascii=False)); return 2
    difficulty_bbox = difficulty_rows[0].bbox
    # The OCR label is the row caption; the actionable radio is the fixed
    # left-side control on that same row.
    difficulty_x = 378
    difficulty_y = int((difficulty_bbox[1] + difficulty_bbox[3]) / 2) + 25
    if not (300 <= difficulty_x <= 1000 and 430 <= difficulty_y <= 560):
        print(json.dumps({"status": "safety_stop", "reason": "difficulty10_target_out_of_bounds", "x": difficulty_x, "y": difficulty_y}, ensure_ascii=False)); return 2
    def live_token() -> str:
        capture.capture(source)
        return hashlib.sha1(source.read_bytes()).hexdigest()

    def difficulty_dialog_visible() -> bool:
        try:
            lines_now = OCRServiceAdapter(language="jpn").recognize(str(source))
        except Exception:
            return True
        text_now = "".join(line.text.replace(" ", "") for line in lines_now if line.confidence >= 0.70)
        return "難易度変更" in text_now and "難易度10" in text_now

    before = live_token()
    try:
        run_adb_coordinate_sequence(
            [(difficulty_x, difficulty_y), (x, y)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(),
            screen_probe=live_token,
            previous_screen_token=before, require_screen_change=False,
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_difficulty",
        )
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"difficulty_change_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2

    # 確定操作後に画面が変わったかを確認する。変化がなければ、
    # その時点の画面でキャンセルボタンを再確認してからキャンセルする。
    after = before
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        after = live_token()
        if not difficulty_dialog_visible():
            print(json.dumps({"status": "completed", "difficulty": 10, "tap": [x, y]}, ensure_ascii=False)); return 0
        time.sleep(0.15)

    try:
        lines_after = OCRServiceAdapter(language="jpn").recognize(str(source))
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"cancel_check_ocr_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    cancels = find_bottom_button(lines_after, "キャンセル")
    if len(cancels) != 1:
        print(json.dumps({"status": "safety_stop", "reason": "cancel_button_not_unique_after_no_change", "count": len(cancels)}, ensure_ascii=False)); return 2
    cancel_bbox = cancels[0].bbox
    cancel_x, cancel_y = bottom_button_center(tuple(cancel_bbox))
    if not (300 <= cancel_x <= 700 and 580 <= cancel_y <= 700):
        print(json.dumps({"status": "safety_stop", "reason": "cancel_button_out_of_bounds", "x": cancel_x, "y": cancel_y}, ensure_ascii=False)); return 2
    try:
        run_adb_coordinate_sequence(
            [(cancel_x, cancel_y)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(), screen_probe=live_token,
            previous_screen_token=after, require_screen_change=False,
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_difficulty_cancel",
        )
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"cancel_failed:{type(exc).__name__}"}, ensure_ascii=False)); return 2
    print(json.dumps({"status": "canceled", "reason": "no_change_after_confirm", "difficulty": 10}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
