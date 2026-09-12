"""エリアボス敗北画面で「再挑戦する」だけを安全に選択する。"""

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


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="敗北時のエリアボス再挑戦")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    source = ROOT / "data/observations/live/task_area_boss_retry_source.png"
    roi_path = ROOT / "data/observations/live/task_area_boss_retry_roi.png"
    capture.capture(source)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False))
        return 2
    roi = image[600:720, 850:1280]
    cv2.imwrite(str(roi_path), roi)
    try:
        lines = PaddleOCRAdapter.from_default_models(device=choose_ocr_device("gpu:0"), language="jpn").recognize(str(roi_path))
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    target = [line for line in lines if line.bbox and line.confidence >= 0.75 and "再挑戦" in line.text]
    if not target:
        print(json.dumps({"status": "safety_stop", "reason": "retry_target_not_confirmed"}, ensure_ascii=False))
        return 2
    box = target[0].bbox
    x = int((box[0] + box[2]) / 2) + 850
    y = int((box[1] + box[3]) / 2) + 600
    probe = ROOT / "data/observations/live/task_area_boss_retry_probe.png"
    token = lambda: (capture.capture(probe), hashlib.sha1(probe.read_bytes()).hexdigest())[1]
    try:
        run_adb_coordinate_sequence([(x, y)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(), screen_probe=token,
            # 敗北画面の背景アニメーションでハッシュが変わるため、
            # 画像差分を再挑戦成功の証拠にしない。呼び出し側で
            # 再挑戦後の画面を再確認する。
            require_screen_change=False, previous_screen_token=token(),
            debug_capture_dir=ROOT / "data/observations/live", debug_capture_prefix="task_area_boss_retry")
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"retry_tap_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "retry_selected", "x": x, "y": y}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
