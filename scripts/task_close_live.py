"""汎用ダイアログの閉じるボタンを固定ROIテンプレートで確認して押す。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from decision.timing import AdaptiveWaitPolicy
from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture


def _match_center(image, template_path: Path, left: int, top: int, right: int, bottom: int) -> tuple[int, int] | None:
    roi = image[top:bottom, left:right]
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None or roi.shape[0] < template.shape[0] or roi.shape[1] < template.shape[1]:
        return None
    result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, point = cv2.minMaxLoc(result)
    if score < 0.75:
        return None
    return (left + point[0] + template.shape[1] // 2, top + point[1] + template.shape[0] // 2)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="閉じるボタンを確認して押す")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    source = ROOT / "data/observations/live/task_close_source.png"
    capture.capture(source)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False))
        return 2
    point = _match_center(image, ROOT / "data/observations/live/template_task_notice_close_text.png", 430, 520, 850, 650)
    if point is None:
        point = _match_center(image, ROOT / "data/observations/live/template_close_text_compact.png", 430, 520, 850, 650)
    if point is None:
        point = _match_center(image, ROOT / "data/observations/live/template_shop_exit_confirm_text.png", 980, 580, 1200, 680)
    if point is None:
        print(json.dumps({"status": "safety_stop", "reason": "close_target_not_confirmed"}, ensure_ascii=False))
        return 2
    x, y = point
    if not ((450 <= x <= 830 and 560 <= y <= 700) or (980 <= x <= 1200 and 580 <= y <= 680)):
        print(json.dumps({"status": "safety_stop", "reason": "close_coordinate_out_of_roi"}, ensure_ascii=False))
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
    except Exception as exc:  # noqa: BLE001 - safety-stop any ADB/vision failure
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "closed", "tap": [x, y]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
