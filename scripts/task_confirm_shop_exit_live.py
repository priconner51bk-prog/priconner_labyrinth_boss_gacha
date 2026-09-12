"""ショップ退出確認を画面確認後に確定する。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.labyrinth_route import run_adb_coordinate_sequence
from vision.capture import AdbScreenCapture
from vision.ocr_service import OCRServiceAdapter
from decision.timing import AdaptiveWaitPolicy

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="ショップ退出確認のOKを押す")
    parser.add_argument("--serial", default="127.0.0.1:5555")
    args = parser.parse_args()
    capture = AdbScreenCapture(serial=args.serial)
    source = ROOT / "data/observations/live/task_confirm_shop_exit_source.png"
    probe = ROOT / "data/observations/live/task_confirm_shop_exit_probe.png"
    capture.capture(source)
    try:
        lines = OCRServiceAdapter(language="jpn").recognize(str(source))
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"ocr_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    text = "".join(line.text for line in lines).replace(" ", "")
    if "ショップから退出します" not in text or "OK" not in text.upper():
        print(json.dumps({"status": "safety_stop", "reason": "shop_exit_confirm_not_confirmed", "text": text}, ensure_ascii=False))
        return 2
    token = lambda: (capture.capture(probe), hashlib.sha1(probe.read_bytes()).hexdigest())[1]
    try:
        run_adb_coordinate_sequence(
            [(787, 495)], serial=args.serial, healthcheck=True,
            timing_policy=AdaptiveWaitPolicy(), screen_probe=token,
            require_screen_change=True, previous_screen_token=token(),
            debug_capture_dir=ROOT / "data/observations/live",
            debug_capture_prefix="task_confirm_shop_exit",
        )
    except Exception as exc:
        print(json.dumps({"status": "safety_stop", "reason": f"tap_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "confirmed", "x": 787, "y": 495}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
