"""初期キャラ候補の実機OCR（task_種別、入力は行わない）。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision.capture import AdbScreenCapture
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
    except Exception as exc:  # noqa: BLE001 - convert probe failures to safety_stop
        print(json.dumps({"status": "safety_stop", "reason": f"screen_observation_failed:{type(exc).__name__}"}, ensure_ascii=False))
        return 2
    if screen_id != "initial_char":
        print(json.dumps({"status": "safety_stop", "reason": f"unexpected_screen:{screen_id!r}"}, ensure_ascii=False))
        return 2
    capture.capture(args.output)
    image = cv2.imread(str(args.output), cv2.IMREAD_COLOR)
    if image is None:
        print(json.dumps({"status": "safety_stop", "reason": "capture_failed"}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "user_assist_required", "screen_id": screen_id,
                      "screenshot": str(args.output), "reason": "candidate_names_require_manual_confirmation_without_ocr"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
