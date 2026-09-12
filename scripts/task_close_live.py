"""汎用ダイアログの閉じるボタンをOCR確認して1回だけ押す。"""

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
from vision.ocr import PaddleOCRAdapter, choose_ocr_device
from vision.ocr_service import OCRServiceAdapter


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="閉じるボタンを確認して押す")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    source = ROOT / "data/observations/live/task_close_source.png"
    roi_path = ROOT / "data/observations/live/task_close_roi.png"
    capture.capture(source)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False))
        return 2
    roi = image[520:650, 430:850]
    cv2.imwrite(str(roi_path), roi)
    try:
        ocr = OCRServiceAdapter(language="jpn")
        lines = ocr.recognize(str(roi_path))
        text = "".join(line.text for line in lines).replace(" ", "")
        full_lines = ocr.recognize(str(source))
        full_text = "".join(line.text for line in full_lines).replace(" ", "")
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    # SHOPは通常ダイアログと異なり、右下に専用の閉じるボタンがある。
    shop_screen = "ショップ" in full_text
    if shop_screen:
        x, y = 1090, 635
        close_lines = []
        text = full_text
    elif "閉じる" not in text:
        print(json.dumps({"status": "safety_stop", "reason": "close_target_not_confirmed", "text": text}, ensure_ascii=False))
        return 2
    else:
        close_lines = [line for line in lines if "閉じる" in line.text and line.bbox]
    if "ショップ" in full_text:
        pass
    elif not close_lines:
        print(json.dumps({"status": "safety_stop", "reason": "close_coordinate_not_confirmed", "text": text}, ensure_ascii=False))
        return 2
    else:
        bbox = close_lines[0].bbox
        x = int((bbox[0] + bbox[2]) / 2) + 430
        y = int((bbox[1] + bbox[3]) / 2) + 520
    if (shop_screen and not (980 <= x <= 1200 and 580 <= y <= 680)) or (
        not shop_screen and not (450 <= x <= 830 and 560 <= y <= 700)
    ):
        print(json.dumps({"status": "safety_stop", "reason": "close_coordinate_out_of_roi", "text": text}, ensure_ascii=False))
        return 2
    probe_path = ROOT / "data/observations/live/task_close_probe.png"

    def screen_token() -> str:
        capture.capture(probe_path)
        return hashlib.sha1(probe_path.read_bytes()).hexdigest()

    try:
        run_adb_coordinate_sequence(
            [(x, y)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(), screen_probe=screen_token,
            require_screen_change=True, previous_screen_token=screen_token(),
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_close",
        )
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}", "text": text}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "closed", "text": text}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
