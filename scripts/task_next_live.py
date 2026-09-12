"""勝利・報酬画面の「次へ」を最小ROI OCRで安全に進める。"""

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
    parser = argparse.ArgumentParser(description="次へボタンを確認して1回だけ押す")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    source = ROOT / "data/observations/live/task_next_source.png"
    roi_path = ROOT / "data/observations/live/task_next_roi.png"
    capture.capture(source)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False))
        return 2
    # 画面右下のボタンだけをOCRし、ゲーム外画面での誤タップを避ける。
    roi = image[570:720, 940:1280]
    cv2.imwrite(str(roi_path), roi)
    try:
        ocr = OCRServiceAdapter(language="jpn")
        text = "".join(line.text for line in ocr.recognize(str(roi_path))).replace(" ", "")
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    if "次へ" not in text:
        print(json.dumps({"status": "safety_stop", "reason": "next_target_not_confirmed", "text": text}, ensure_ascii=False))
        return 2
    probe_path = ROOT / "data/observations/live/task_next_probe.png"

    def screen_token() -> str:
        capture.capture(probe_path)
        return hashlib.sha1(probe_path.read_bytes()).hexdigest()

    previous = screen_token()
    try:
        run_adb_coordinate_sequence(
            [(1105, 650)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(), screen_probe=screen_token,
            require_screen_change=True, previous_screen_token=previous,
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_next",
        )
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}", "text": text}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "advanced", "text": text}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
